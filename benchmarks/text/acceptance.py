"""Seeded corpus exports and measured Heap acceptance, outside the engine."""

from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

from engine.maintenance.validation import validate_record
from engine.storage import HeapFile, Record
from engine.storage.binary import MAX_RECORD_SIZE
from engine.text import tokenize, tokenizer_signature

from .corpus import GROUPS, SCHEMA, TABLE, TEXT_LIMIT, validate_source_binding
from .esci import esci_queries, parquet_rows
from .sources import file_hash, write_json


SIZES = (1000, 10000, 100000)
SEED = 20261024
PREPARATION_FILES = ("query_preflight.json", "document_validation.json", "selected_queries.json",
                     "accepted_pool.jsonl", "selected_positives.jsonl")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical(row):
    return (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def row_hash(identifier, text):
    """Unambiguous, versioned ID + original UTF-8 content hash; no normalization."""
    return sha256(canonical({"id": identifier, "text": text})).hexdigest()


def _receipt(path):
    return {"sha256": file_hash(path), "bytes": path.stat().st_size}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _queries(selection, required):
    queries = selection["queries"]
    counts, identifiers, normalized, positives = Counter(), set(), set(), set()
    for query in queries:
        tokens = tokenize(query["text"])
        length = len(tokens)
        group = "1" if length == 1 else "3" if length == 3 else "5plus" if length >= 5 else None
        _require(type(query["id"]) is int and query["id"] not in identifiers, "Duplicate/invalid query ID")
        _require(tokens not in normalized and group == query["group"] and length == query["length"],
                 "Query group, length or distinctness mismatch")
        identifiers.add(query["id"])
        normalized.add(tokens)
        counts[group] += 1
        pids = [row["id"] for row in query["positives"]]
        _require(pids and len(pids) == len(set(pids)) and all(row["relevance"] > 0 for row in query["positives"]),
                 "Missing or duplicate positive judgments")
        positives.update(pids)
    _require(dict(counts) == {group: required for group in GROUPS}, "Insufficient query groups")
    _require(sorted(positives) == selection["positive_ids"], "Positive union mismatch")
    expected_qrels = {(q["id"], p["id"]): p["relevance"] for q in queries for p in q["positives"]}
    _require(expected_qrels == {(r["query_id"], r["document_id"]): r["relevance"] for r in selection["qrels"]},
             "Selected positive qrels mismatch")
    return queries, positives, expected_qrels


def load_preparation(directory):
    directory = Path(directory)
    preflight, validation, selection = (read_json(directory / name) for name in PREPARATION_FILES[:3])
    for report in (preflight, validation, selection):
        _require(report["status"] == "PASS", "A preparation stage failed")
        _require(report["tokenizer"] == tokenizer_signature(), "Tokenizer signature mismatch")
    _require(validation.get("preflight_sha256") == file_hash(directory / "query_preflight.json"),
             "Preflight binding mismatch")
    _require(validation.get("dataset") == preflight.get("dataset"), "Dataset binding mismatch")
    _require(file_hash(directory / "accepted_pool.jsonl") == validation["outputs"]["accepted_pool.jsonl"]["sha256"],
             "Accepted pool hash mismatch")
    _require(file_hash(directory / "selected_positives.jsonl") == selection["selected_positives_sha256"],
             "Selected positive spool hash mismatch")
    queries, _, _ = _queries(selection, preflight["required_per_group"])
    originals = {query["id"]: query for query in preflight["candidates"]}
    _require(all(query == originals.get(query["id"]) for query in queries), "Selected original query changed")
    return preflight, validation, selection


def _index_documents(directory, selection):
    """Retain offsets/hashes, never the full corpus text; recheck actual row capacity."""
    index = {}
    positives_seen = set()
    for filename in ("accepted_pool.jsonl", "selected_positives.jsonl"):
        seen = set()
        with (directory / filename).open("rb") as stream:
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line:
                    break
                row = json.loads(line)
                identifier = row["id"]
                _require(type(identifier) is int and identifier not in seen, "Duplicate/invalid document ID")
                seen.add(identifier)
                _require(isinstance(row["text"], str), "Invalid original document text")
                validate_record(TABLE, Record(SCHEMA, [identifier, row["text"]]))
                digest = sha256(canonical(row)).hexdigest()
                if identifier in index:
                    _require(index[identifier][2] == digest, "Conflicting overlapping document text/source identity")
                index[identifier] = (filename, offset, digest)
        if filename == "selected_positives.jsonl":
            positives_seen = seen
    _require(positives_seen == set(selection["positive_ids"]), "Missing/unexpected selected positive document")
    return index


def ordered_ids(index, positives, seed, size):
    _require(type(seed) is int, "Seed must be an integer")
    _require(len(positives) <= size <= len(index), "Insufficient documents or excessive positives")
    # SHA-256 priority is independent of Python RNG implementation and input order.
    distractors = sorted(index.keys() - positives,
                         key=lambda pid: (sha256(f"nested-v1:{seed}:{pid}".encode("ascii")).digest(), pid))
    return sorted(positives) + distractors[:size - len(positives)]


def build_subsets(preparation_dir, output_dir, judgments=None, *, sizes=SIZES, seed=SEED):
    preparation_dir, output_dir = Path(preparation_dir), Path(output_dir)
    preflight, _, selection = load_preparation(preparation_dir)
    queries, positives, positive_qrels = _queries(selection, preflight["required_per_group"])
    _require(len(sizes) == 3 and all(type(n) is int and n > 0 for n in sizes)
             and sizes[0] < sizes[1] < sizes[2], "Subset sizes must be strictly increasing")
    _require(len(positives) <= sizes[0], "Positive union exceeds smallest subset")
    judgments = dict(positive_qrels if judgments is None else judgments)
    _require({pair: grade for pair, grade in judgments.items() if grade > 0} == positive_qrels,
             "Original positive judgments changed or are missing")
    qids = {q["id"] for q in queries}
    _require(all(qid in qids and type(grade) is int and grade >= 0 for (qid, _), grade in judgments.items()),
             "Unexpected query or invalid judgment")
    index = _index_documents(preparation_dir, selection)
    order = ordered_ids(index, positives, seed, sizes[-1])
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"format_version": 1, "status": "PASS", "seed": seed, "sizes": list(sizes),
                "selection_algorithm": "nested-v1: positives by numeric ID, then SHA256(nested-v1:seed:id) ascending",
                "tokenizer": tokenizer_signature(), "dataset": preflight["dataset"],
                "preparation_sha256": {name: file_hash(preparation_dir / name) for name in PREPARATION_FILES},
                "positive_union_count": len(positives), "subsets": {}}
    with ExitStack() as stack:
        sources = {name: stack.enter_context((preparation_dir / name).open("rb"))
                   for name in ("accepted_pool.jsonl", "selected_positives.jsonl")}
        outputs = {}
        for size in sizes:
            target = output_dir / str(size)
            target.mkdir()
            outputs[size] = stack.enter_context((target / "documents.jsonl").open("xb"))
        for position, identifier in enumerate(order):
            filename, offset, digest = index[identifier]
            sources[filename].seek(offset)
            row = json.loads(sources[filename].readline())
            line = canonical(row)
            _require(sha256(line).hexdigest() == digest, "Document spool changed during export")
            for size, stream in outputs.items():
                if position < size:
                    stream.write(line)
    for size in sizes:
        target, ids = output_dir / str(size), set(order[:size])
        write_json(target / "queries.json", {"format_version": 1, "tokenizer": tokenizer_signature(), "queries": queries})
        filtered = [(qid, pid, grade) for (qid, pid), grade in sorted(judgments.items()) if pid in ids]
        with (target / "qrels.tsv").open("x", encoding="utf-8", newline="\n") as stream:
            for qid, pid, grade in filtered:
                stream.write(f"{qid}\t0\t{pid}\t{grade}\n")
        manifest["subsets"][str(size)] = {"document_count": size, "query_count": len(queries),
            "positive_union_count": len(positives), "judgment_count": len(filtered),
            "positive_judgment_count": sum(grade > 0 for _, _, grade in filtered),
            "files": {name: _receipt(target / name) for name in ("documents.jsonl", "queries.json", "qrels.tsv")}}
        write_json(target / "manifest.json", {"format_version": 1, "seed": seed, "tokenizer": tokenizer_signature(),
                                             **manifest["subsets"][str(size)]})
    manifest["subset_manifest_sha256"] = {str(n): file_hash(output_dir / str(n) / "manifest.json") for n in sizes}
    write_json(output_dir / "subsets_manifest.json", manifest)
    return manifest


def inspect_subsets(output_dir, *, sizes=SIZES, required_per_group=10):
    """Read every export, checking contents as well as file receipts and references."""
    from .corpus import parse_qrels
    output_dir = Path(output_dir)
    manifest = read_json(output_dir / "subsets_manifest.json")
    _require(manifest["sizes"] == list(sizes) and manifest["tokenizer"] == tokenizer_signature(),
             "Subset sizes or tokenizer mismatch")
    previous, query_bytes, summary = {}, None, {}
    for size in sizes:
        target = output_dir / str(size)
        entry = manifest["subsets"][str(size)]
        _require(file_hash(target / "manifest.json") == manifest["subset_manifest_sha256"][str(size)],
                 "Subset manifest hash mismatch")
        local = read_json(target / "manifest.json")
        _require(local == {"format_version": 1, "seed": manifest["seed"], "tokenizer": tokenizer_signature(), **entry},
                 "Subset manifest metadata mismatch")
        for name, receipt in entry["files"].items():
            _require(_receipt(target / name) == receipt, "Subset export hash/size mismatch")
        current = {}
        encoded_min, encoded_max, encoded_total, histogram = MAX_RECORD_SIZE, 0, 0, Counter()
        with (target / "documents.jsonl").open("rb") as stream:
            for line in stream:
                row = json.loads(line)
                _require(type(row["id"]) is int and row["id"] not in current, "Duplicate/invalid subset document ID")
                encoded_size = len(validate_record(TABLE, Record(SCHEMA, [row["id"], row["text"]])))
                encoded_min, encoded_max = min(encoded_min, encoded_size), max(encoded_max, encoded_size)
                encoded_total += encoded_size
                histogram[str(((encoded_size + 255) // 256) * 256)] += 1
                current[row["id"]] = sha256(canonical(row)).hexdigest()
        _require(len(current) == size == entry["document_count"], "Subset document count mismatch")
        _require(all(current.get(pid) == digest for pid, digest in previous.items()), "Broken subset nesting/text identity")
        raw_queries = (target / "queries.json").read_bytes()
        _require(query_bytes is None or query_bytes == raw_queries, "Original queries differ between subsets")
        query_bytes = raw_queries
        query_report = read_json(target / "queries.json")
        queries = query_report["queries"]
        selection = {"queries": queries, "positive_ids": sorted({p["id"] for q in queries for p in q["positives"]}),
                     "qrels": [{"query_id": q["id"], "document_id": p["id"], "relevance": p["relevance"]}
                               for q in queries for p in q["positives"]]}
        _, positives, expected = _queries(selection, required_per_group)
        _require(positives <= current.keys(), "Missing positive reference in subset")
        with (target / "qrels.tsv").open("rb") as stream:
            qrels, duplicate_count = parse_qrels(stream)
        _require(duplicate_count == 0 and len(qrels) == entry["judgment_count"], "Duplicate/count mismatch in filtered qrels")
        _require(all(qid in {q["id"] for q in queries} and pid in current for qid, pid in qrels), "Broken judgment reference")
        _require({pair: grade for pair, grade in qrels.items() if grade > 0} == expected, "Missing/changed positive judgment")
        summary[str(size)] = {"documents": len(current), "query_groups": dict(Counter(q["group"] for q in queries)),
                              "positive_documents": len(positives), "positive_pairs": len(expected),
                              "judged_pairs": len(qrels), "missing_positive_references": 0,
                              "encoded_record_bytes": {"min": encoded_min, "max": encoded_max,
                                  "mean": encoded_total / size, "histogram_upper_bounds": dict(histogram)}}
        previous = current
    return summary


def reopen_heap(heap_path, documents_path, rids_path):
    """Child-process entry point: no schema, RIDs or writer state is inherited."""
    expected = {}
    digest_before, digest_after = sha256(), sha256()
    with Path(documents_path).open("rb") as stream:
        for line in stream:
            row = json.loads(line)
            _require(row["id"] not in expected, "Duplicate expected document ID")
            digest = row_hash(row["id"], row["text"])
            expected[row["id"]] = digest
    with Path(rids_path).open(encoding="utf-8") as stream:
        saved_rids = {}
        for line in stream:
            saved = json.loads(line)
            _require(saved["id"] not in saved_rids, "Duplicate saved RID document ID")
            saved_rids[saved["id"]] = saved
    _require(saved_rids.keys() == expected.keys(), "Saved RID count/ID mismatch")
    seen = set()
    observed = {}
    with HeapFile.open(heap_path) as heap:
        _require(heap.schema == SCHEMA and heap.record_count == len(expected), "Reopened schema/count mismatch")
        for rid, record in heap.scan():
            identifier, text = record.values
            digest = row_hash(identifier, text)
            _require(saved_rids.get(identifier) == {"id": identifier, "rid": [rid.page_id, rid.slot_id], "sha256": digest},
                     "Reopened RID/content hash mismatch")
            _require(identifier not in seen and expected.get(identifier) == digest, "Reopened ID/content mismatch")
            seen.add(identifier)
            observed[identifier] = digest
        _require(seen == expected.keys(), "Reopened row/RID count mismatch")
    for identifier in sorted(expected):
        digest_before.update(bytes.fromhex(expected[identifier]))
        digest_after.update(bytes.fromhex(observed[identifier]))
    _require(digest_before.digest() == digest_after.digest(), "Reopened ordered content hash mismatch")
    return {"status": "PASS", "rows": len(seen), "unique_ids": len(seen), "verified_rid_mappings": len(seen),
            "content_before_sha256": digest_before.hexdigest(), "content_after_sha256": digest_after.hexdigest(),
            "process_id": __import__("os").getpid(), "schema_restored_from_disk": True}


def verify_heap(output_dir, *, size=100000, timeout=600):
    output_dir = Path(output_dir).resolve()
    work = output_dir / "heap_verification"
    work.mkdir(exist_ok=False)
    documents, heap_path, rids_path = output_dir / str(size) / "documents.jsonl", work / "documents.heap", work / "rids.jsonl"
    started, inserted = perf_counter(), 0
    report = {"format_version": 1, "status": "FAIL", "expected_rows": size, "inserted_rows": 0,
              "documents_sha256": None, "tokenizer": tokenizer_signature(),
              "writer_process_id": __import__("os").getpid(), "fresh_process": False, "errors": []}
    try:
        report["documents_sha256"] = file_hash(documents)
        seen = set()
        minimum, maximum, total = MAX_RECORD_SIZE, 0, 0
        with HeapFile.create(heap_path, SCHEMA) as heap, rids_path.open("x", encoding="utf-8", newline="\n") as rids:
            with documents.open("rb") as source:
                for line in source:
                    row = json.loads(line)
                    identifier, text = row["id"], row["text"]
                    _require(type(identifier) is int and identifier not in seen, "Duplicate/invalid Heap document ID")
                    encoded = validate_record(TABLE, Record(SCHEMA, [identifier, text]))
                    rid = heap.insert(Record(SCHEMA, [identifier, text]))
                    rids.write(canonical({"id": identifier, "rid": [rid.page_id, rid.slot_id],
                                          "sha256": row_hash(identifier, text)}).decode("utf-8"))
                    seen.add(identifier)
                    inserted += 1
                    minimum, maximum, total = min(minimum, len(encoded)), max(maximum, len(encoded)), total + len(encoded)
            _require(inserted == size == heap.record_count, "Inserted Heap row count mismatch")
        report["insert_and_close_seconds"] = perf_counter() - started
        # Isolated interpreter, explicit entry script, and no inherited Python path.
        script = Path(__file__).resolve().parents[2] / "scripts" / "verify_text_heap.py"
        result = subprocess.run([sys.executable, "-I", "-B", str(script), str(heap_path), str(documents), str(rids_path)],
                                cwd=work, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        _require(result.returncode == 0, "Fresh-process Heap verification failed: " + result.stderr.strip())
        child = json.loads(result.stdout)
        _require(child["status"] == "PASS" and child["rows"] == size and child["process_id"] != report["writer_process_id"],
                 "Invalid fresh-process verification receipt")
        _require(file_hash(documents) == report["documents_sha256"], "Documents changed during Heap verification")
        report.update(status="PASS", fresh_process=True, child=child,
                      encoded_record_bytes={"min": minimum, "max": maximum, "mean": total / inserted},
                      heap=_receipt(heap_path), rids=_receipt(rids_path))
    except Exception as error:
        from scripts.sanitize_evidence import sanitize
        report["errors"].append(sanitize(f"{type(error).__name__}: {error}"))
    report.update(inserted_rows=inserted, elapsed_seconds=perf_counter() - started)
    write_json(output_dir / "heap_verification.json", report)
    return report


def source_judgments(source_dir, preparation_dir):
    """Verify pinned inputs and recover ALL original labels for the selected queries."""
    source_dir, preparation_dir = Path(source_dir), Path(preparation_dir)
    preflight, validation, selection = load_preparation(preparation_dir)
    manifest = read_json(source_dir / "source_manifest.json")
    validate_source_binding(manifest, preflight)
    _require("ESCI" in manifest["dataset"] and manifest["relevance_mapping"] == {"I": 0, "C": 1, "S": 2, "E": 3},
             "Unsupported source or changed relevance mapping")
    for item in manifest["files"]:
        path = source_dir / item["filename"]
        _require(file_hash(path) == item["sha256"] and path.stat().st_size == item["downloaded_bytes"],
                 "Source hash/byte size mismatch")
        _require(validation["source_sha256"].get(item["role"]) == item["sha256"], "Validation source binding mismatch")
    examples = next(item for item in manifest["files"] if item["role"] == "examples")
    selected = {q["id"]: q for q in selection["queries"]}
    columns = ["query_id", "query", "product_id", "product_locale", "split", "large_version", "esci_label"]
    rows = (row for row in parquet_rows(source_dir / examples["filename"], columns) if row["query_id"] in selected)
    queries, judgments = esci_queries(rows, manifest["locale"], manifest["split"])
    _require(all(queries.get(qid) == {key: query[key] for key in ("id", "text", "length")}
                 for qid, query in selected.items()), "Original source query mismatch")
    _, _, positives = _queries(selection, preflight["required_per_group"])
    _require({pair: grade for pair, grade in judgments.items() if grade > 0} == positives,
             "Complete original positive judgments mismatch")
    return manifest, judgments


def acceptance_report(source_dir, preparation_dir, output_dir):
    """Publish FAIL for any unmeasured/failed gate; never infer real acceptance from tests."""
    output_dir, preparation_dir = Path(output_dir), Path(preparation_dir)
    criteria = {}
    report = {"format_version": 1, "recorded_utc": datetime.now(timezone.utc).isoformat(),
              "status": "FAIL", "corpus_acceptance": "FAIL", "candidate_approved": False,
              "runtime": {"python": platform.python_version(), "platform": platform.system()},
              "tokenizer": tokenizer_signature(), "criteria": criteria, "errors": []}

    def check(name, action):
        try:
            evidence = action()
            criteria[name] = {"status": "PASS", "evidence": evidence}
            return evidence
        except Exception as error:
            from scripts.sanitize_evidence import sanitize
            message = sanitize(f"{type(error).__name__}: {error}")
            criteria[name] = {"status": "FAIL", "error": message}
            report["errors"].append(name + ": " + message)
            return None

    source = check("compatible_verified_sources", lambda: source_judgments(source_dir, preparation_dir))
    if source is not None:
        manifest, judgments = source
        criteria["compatible_verified_sources"]["evidence"] = {"dataset": manifest["dataset"],
            "version": manifest["version"], "revision": manifest["revision"], "split": manifest["split"], "locale": manifest["locale"],
            "files": [{key: item[key] for key in ("role", "sha256", "downloaded_bytes")} for item in manifest["files"]]}
    else:
        judgments = None

    def preparation_gate():
        preflight, validation, selection = load_preparation(preparation_dir)
        _require(validation["accepted_pool_rows"] >= 100000 and not validation["rejections"].get("duplicate_id"),
                 "Insufficient unique accepted documents")
        return {key: validation[key] for key in ("scanned_rows", "codec_validated_rows", "accepted_validated_rows",
                "accepted_pool_rows", "rejections", "unselected_rows_not_codec_validated", "encoded_record_bytes")}

    check("streaming_source_capacity", preparation_gate)

    def query_gate():
        _, _, selection = load_preparation(preparation_dir)
        queries, positives, qrels = _queries(selection, 10)
        _require(len(positives) <= 1000, "Known positive union exceeds 1000")
        return {"query_groups": dict(Counter(q["group"] for q in queries)), "queries": queries,
                "positive_union_count": len(positives), "positive_pairs": len(qrels)}

    check("original_queries_and_positives", query_gate)
    check("nested_subsets_and_references", lambda: inspect_subsets(output_dir))

    def seeded_gate():
        from .corpus import parse_qrels
        _require(judgments is not None, "Verified original judgments unavailable")
        preflight, _, selection = load_preparation(preparation_dir)
        subset_manifest = read_json(output_dir / "subsets_manifest.json")
        _require(subset_manifest["preparation_sha256"] == {name: file_hash(preparation_dir / name) for name in PREPARATION_FILES},
                 "Export preparation binding mismatch")
        _require(subset_manifest["dataset"] == preflight["dataset"], "Export dataset mismatch")
        index = _index_documents(preparation_dir, selection)
        order = ordered_ids(index, set(selection["positive_ids"]), subset_manifest["seed"], 100000)
        for size in SIZES:
            target = output_dir / str(size)
            with (target / "documents.jsonl").open("rb") as stream:
                ids = []
                for line in stream:
                    row = json.loads(line)
                    _require(row["id"] in index and sha256(canonical(row)).hexdigest() == index[row["id"]][2],
                             "Export differs from validated original document")
                    ids.append(row["id"])
            _require(ids == order[:size], "Seeded subset order mismatch")
            expected_queries = {"format_version": 1, "tokenizer": tokenizer_signature(), "queries": selection["queries"]}
            _require(read_json(target / "queries.json") == expected_queries, "Exported original queries changed")
            with (target / "qrels.tsv").open("rb") as stream:
                filtered, _ = parse_qrels(stream)
            wanted = set(ids)
            _require(filtered == {pair: grade for pair, grade in judgments.items() if pair[1] in wanted},
                     "Filtered original judgments mismatch")
        return {"seed": subset_manifest["seed"], "algorithm": subset_manifest["selection_algorithm"],
                "every_export_compared_to_validated_original": True,
                "all_original_positive_and_zero_grade_labels_checked": True}

    check("seeded_original_content_and_judgments", seeded_gate)

    def heap_gate():
        heap = read_json(output_dir / "heap_verification.json")
        _require(heap["status"] == "PASS" and heap["fresh_process"] and heap["inserted_rows"] == 100000
                 and heap["expected_rows"] == 100000 and heap["tokenizer"] == tokenizer_signature(), "Heap acceptance failed")
        child = heap["child"]
        _require(child["rows"] == child["unique_ids"] == child["verified_rid_mappings"] == 100000
                 and child["process_id"] != heap["writer_process_id"] and child["schema_restored_from_disk"]
                 and child["content_before_sha256"] == child["content_after_sha256"], "Incomplete fresh-process evidence")
        _require(heap["documents_sha256"] == file_hash(output_dir / "100000" / "documents.jsonl"), "Heap input changed")
        for key, name in (("heap", "documents.heap"), ("rids", "rids.jsonl")):
            _require(heap[key] == _receipt(output_dir / "heap_verification" / name), "Verified Heap artifact changed")
        _require(heap["encoded_record_bytes"]["max"] <= MAX_RECORD_SIZE, "Heap record capacity exceeded")
        return heap

    check("actual_heap_fresh_process_persistence", heap_gate)
    report["schema"] = {"table": "documentos", "columns": [["id", "INTEGER"], ["contenido", "VARCHAR"]],
                        "primary_key": "id", "declared_text_characters": TEXT_LIMIT, "max_record_size": MAX_RECORD_SIZE,
                        "content_hash": "SHA256(canonical UTF8 JSON {id,text} + LF); numeric-ID-ordered digest of row digests"}
    if all(item["status"] == "PASS" for item in criteria.values()):
        report.update(status="PASS", corpus_acceptance="PASS", candidate_approved=True)
    report["artifacts"] = {name: _receipt(output_dir / name) for name in ("subsets_manifest.json", "heap_verification.json")
                           if (output_dir / name).exists()}
    write_json(output_dir / "corpus_feasibility.json", report)
    return report
