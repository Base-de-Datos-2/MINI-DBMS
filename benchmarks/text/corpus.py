"""Streaming acceptance preparation for 1B.2–1B.4; no index or ranking code."""

from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path, PurePosixPath
import tarfile

from engine.catalog import Column, ColumnConstraint, DataType, Schema, TableMetadata
from engine.errors import ValidationError
from engine.maintenance.validation import validate_record
from engine.storage import Record, RecordCodec
from engine.storage.binary import INTEGER_MIN, INTEGER_MAX, INTEGER_STRUCT, MAX_RECORD_SIZE, VARCHAR_LENGTH_STRUCT
from engine.text import tokenize, tokenizer_signature

from .sources import FILES, file_hash, write_json


GROUPS = ("1", "3", "5plus")
SCHEMA = Schema([Column("id", DataType.INTEGER), Column("contenido", DataType.VARCHAR)])
TEXT_LIMIT = MAX_RECORD_SIZE - INTEGER_STRUCT.size - VARCHAR_LENGTH_STRUCT.size
TABLE = TableMetadata("documentos", SCHEMA, constraints=(
    ColumnConstraint("id", primary_key=True), ColumnConstraint("contenido", varchar_length=TEXT_LIMIT),
))


def identifier(value):
    """Canonical decimal IDs fit the project's codec, without coercion aliases."""
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="strict")
    if not isinstance(value, str):
        raise ValueError("ID must be canonical decimal text")
    number = int(value)
    if str(number) != value or not INTEGER_MIN <= number <= INTEGER_MAX:
        raise ValueError("ID is noncanonical or outside signed 64-bit range")
    return number


def _line(raw):
    # Remove one TSV record terminator, preserving all other original spaces.
    raw = raw[:-1] if raw.endswith(b"\n") else raw
    return raw[:-1] if raw.endswith(b"\r") else raw


@contextmanager
def member_stream(path, member):
    """Open a plain TSV or one regular tar member, without extraction to disk."""
    path = Path(path)
    if path.suffix == ".tsv":
        with path.open("rb") as stream:
            yield stream
        return
    with tarfile.open(path, "r|gz") as archive:
        found = False
        for entry in archive:
            if entry.isfile() and PurePosixPath(entry.name).name == member:
                if found:
                    raise ValueError(f"Duplicate archive member: {member}")
                found = True
                with archive.extractfile(entry) as stream:
                    yield stream
                # Continue to detect duplicate matching members; never extract paths.
        if not found:
            raise ValueError(f"Required archive member missing: {member}")


def parse_queries(lines):
    queries = {}
    for position, raw in enumerate(lines, 1):
        left, separator, text = _line(raw).partition(b"\t")
        if not separator:
            raise ValueError(f"Malformed query TSV at row {position}")
        qid = identifier(left)
        if qid in queries:
            raise ValueError(f"Duplicate query ID at row {position}")
        original = text.decode("utf-8", errors="strict")
        queries[qid] = {"id": qid, "text": original, "length": len(tokenize(original))}
    return queries


def parse_qrels(lines):
    judgments = {}
    identical_duplicates = 0
    for position, raw in enumerate(lines, 1):
        fields = raw.split()
        if len(fields) != 4 or fields[1] not in {b"0", b"Q0"}:
            raise ValueError(f"Malformed TREC qrels at row {position}")
        qid, pid = identifier(fields[0]), identifier(fields[2])
        relevance = int(fields[3])
        if relevance < 0:
            raise ValueError(f"Negative relevance at row {position}")
        key = (qid, pid)
        if key in judgments:
            if judgments[key] != relevance:
                raise ValueError(f"Conflicting qrels pair at row {position}")
            identical_duplicates += 1
            continue
        judgments[key] = relevance
    return judgments, identical_duplicates


def preflight(queries, judgments, per_group=10):
    if type(per_group) is not int or per_group < 1:
        raise ValueError("Queries required per group must be a positive integer")
    missing_queries = sorted({qid for qid, _ in judgments} - queries.keys())
    positives = {}
    for (qid, pid), relevance in judgments.items():
        if relevance > 0:
            positives.setdefault(qid, {})[pid] = relevance
    counts = Counter()
    distinct = {group: set() for group in GROUPS}
    candidates = []
    for qid, row in sorted(queries.items()):
        length = row["length"]
        group = str(length) if length in (1, 3) else "5plus" if length >= 5 else "other"
        counts["all_" + group] += 1
        if group not in GROUPS or qid not in positives:
            continue
        counts[group] += 1
        distinct[group].add(" ".join(tokenize(row["text"])))
        candidates.append({**row, "group": group, "positives": [
            {"id": pid, "relevance": grade} for pid, grade in sorted(positives[qid].items())
        ]})
    eligible = {group: len(distinct[group]) for group in GROUPS}
    status = "PASS" if not missing_queries and all(count >= per_group for count in eligible.values()) else "FAIL"
    return {
        "format_version": 1, "status": status, "tokenizer": tokenizer_signature(),
        "query_count": len(queries), "judgment_count": len(judgments),
        "queries_with_positive_judgments": len(positives), "query_length_counts": dict(counts),
        "eligible_counts": eligible, "required_per_group": per_group,
        "eligible_query_id_counts": {group: counts[group] for group in GROUPS},
        "missing_query_references": missing_queries,
        "selection_rule": "group order 1,3,5plus; canonical numeric query ID ascending; no ranking-based selection",
        "shortlist": {group: [row["id"] for row in candidates if row["group"] == group][:per_group * 10]
                      for group in GROUPS},
        "candidates": candidates, "corpus_acceptance": "PENDING",
    }


def validate_documents(lines, output_dir, positive_ids=(), minimum_documents=100000):
    """Validate a 100k pool plus every candidate positive while scanning all IDs.

    Texts are streamed to JSONL. Only IDs and bounded counters stay in memory;
    the global seen-ID set grows with scanned records and its size is reported.
    Unselected distractor texts are not codec-validated or counted as accepted.
    A duplicate anywhere makes the result unusable, even if its first copy was
    provisionally written. Source rows are never shortened to fit the engine.
    """
    if type(minimum_documents) is not int or minimum_documents < 1:
        raise ValueError("Minimum documents must be a positive integer")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pool_path, positives_path = output_dir / "accepted_pool.jsonl", output_dir / "candidate_positives.jsonl"
    wanted = set(positive_ids)
    accepted_positives, rejected_positives = set(), {}
    seen = set()
    rejected, histogram = Counter(), Counter()
    scanned = validated = accepted = pool_count = total_bytes = 0
    minimum_size, maximum_size = None, 0
    with pool_path.open("x", encoding="utf-8", newline="\n") as pool, positives_path.open("x", encoding="utf-8", newline="\n") as positives:
        for raw in lines:
            scanned += 1
            original_source_id = None
            if isinstance(raw, dict):
                pid = raw.get("id")
                if type(pid) is not int or not INTEGER_MIN <= pid <= INTEGER_MAX:
                    rejected["invalid_id"] += 1
                    continue
                original_source_id = raw.get("source_id")
                text_bytes = None
            else:
                left, separator, text_bytes = _line(raw).partition(b"\t")
                if not separator:
                    rejected["malformed_record"] += 1
                    continue
                try:
                    pid = identifier(left)
                except (ValueError, UnicodeError):
                    rejected["invalid_id"] += 1
                    continue
            if pid in seen:
                rejected["duplicate_id"] += 1
                if pid in wanted:
                    accepted_positives.discard(pid)
                    rejected_positives[pid] = "duplicate_id"
                continue
            seen.add(pid)
            if pool_count >= minimum_documents and pid not in wanted:
                continue
            validated += 1
            reason = None
            try:
                text = raw.get("text") if isinstance(raw, dict) else text_bytes.decode("utf-8", errors="strict")
                if not isinstance(text, str):
                    reason = "invalid_text_type"
                    raise TypeError("Text field must be a string")
                text.encode("utf-8", errors="strict")
                row = Record(SCHEMA, [pid, text])
                if len(text) > TEXT_LIMIT:
                    reason = "declared_length"
                elif len(RecordCodec.serialize(row)) > MAX_RECORD_SIZE:
                    reason = "record_size"
                else:
                    payload = validate_record(TABLE, row)
            except UnicodeError:
                reason = "invalid_utf8"
            except TypeError:
                reason = "invalid_text_type"
            except ValidationError:
                reason = "engine_validation"
            if reason:
                rejected[reason] += 1
                if pid in wanted:
                    rejected_positives[pid] = reason
                continue
            accepted += 1
            size = len(payload)
            total_bytes += size
            minimum_size = size if minimum_size is None else min(minimum_size, size)
            maximum_size = max(maximum_size, size)
            upper = next((bound for bound in (512, 1024, 2048, MAX_RECORD_SIZE) if size <= bound))
            histogram[str(upper)] += 1
            document = {"id": pid, "text": text}
            if original_source_id is not None:
                document["source_id"] = original_source_id
            serialized = json.dumps(document, ensure_ascii=False) + "\n"
            if pool_count < minimum_documents:
                pool.write(serialized)
                pool_count += 1
            if pid in wanted:
                positives.write(serialized)
                accepted_positives.add(pid)
    missing = wanted - accepted_positives - rejected_positives.keys()
    # Invalid individual rows are rejected. Duplicate IDs make a provisional
    # pool ambiguous and therefore invalidate the run rather than overwriting.
    structural_errors = rejected["duplicate_id"]
    report = {
        "format_version": 1, "status": "PASS" if pool_count >= minimum_documents and not structural_errors else "FAIL",
        "scope": "first valid pool plus every candidate positive; full-stream ID uniqueness check",
        "scanned_rows": scanned, "unique_ids_seen": len(seen), "codec_validated_rows": validated,
        "accepted_validated_rows": accepted, "accepted_pool_rows": pool_count,
        "unselected_rows_not_codec_validated": scanned - validated - sum(
            rejected[reason] for reason in ("invalid_id", "duplicate_id", "malformed_record")),
        "minimum_documents": minimum_documents, "rejections": dict(rejected),
        "encoded_record_bytes": {"min": minimum_size, "max": maximum_size,
                                 "mean": total_bytes / accepted if accepted else 0,
                                 "histogram_upper_bounds": dict(sorted(histogram.items(), key=lambda item: int(item[0])))},
        "max_record_size": MAX_RECORD_SIZE, "declared_text_characters": TEXT_LIMIT,
        "tokenizer": tokenizer_signature(), "seen_id_set_entries": len(seen),
        "accepted_positive_ids": sorted(accepted_positives),
        "rejected_positive_ids": {str(pid): reason for pid, reason in sorted(rejected_positives.items())},
        "missing_positive_ids": sorted(missing),
        "outputs": {path.name: {"sha256": file_hash(path), "bytes": path.stat().st_size}
                    for path in (pool_path, positives_path)},
        "heap_reopen": "NOT_RUN_1B6", "nested_subsets": "NOT_BUILT_1B5", "corpus_acceptance": "PENDING",
    }
    write_json(output_dir / "document_validation.json", report)
    return report


def select_queries(preflight_report, validation_report, output_dir, positive_cap=1000):
    """Take the first eligible queries whose complete positives fit the cap."""
    if preflight_report["status"] != "PASS" or validation_report["status"] != "PASS":
        raise ValueError("Cannot select from failed preflight or document validation")
    if preflight_report["tokenizer"] != validation_report["tokenizer"] or preflight_report["tokenizer"] != tokenizer_signature():
        raise ValueError("Tokenizer signature mismatch between preparation stages")
    output_dir = Path(output_dir)
    if type(positive_cap) is not int or positive_cap < 1:
        raise ValueError("Positive union cap must be a positive integer")
    if preflight_report.get("source_sha256"):
        preflight_path = output_dir / "query_preflight.json"
        if file_hash(preflight_path) != validation_report.get("preflight_sha256"):
            raise ValueError("Query preflight changed after document validation")
        if json.loads(preflight_path.read_text(encoding="utf-8")) != preflight_report:
            raise ValueError("Selection input differs from the bound query preflight")
        if validation_report.get("dataset") != preflight_report.get("dataset"):
            raise ValueError("Dataset/split association changed between stages")
    if (output_dir / "selected_queries.json").exists() or (output_dir / "selected_positives.jsonl").exists():
        raise FileExistsError("Selection output already exists; use a fresh preparation directory")
    source = output_dir / "candidate_positives.jsonl"
    receipt = validation_report["outputs"][source.name]
    if file_hash(source) != receipt["sha256"]:
        raise ValueError("Candidate-positive spool hash mismatch")
    accepted = set(validation_report["accepted_positive_ids"])
    required = preflight_report["required_per_group"]
    selected, positive_union, excluded, query_keys = [], set(), Counter(), set()
    for group in GROUPS:
        chosen = 0
        for query in sorted(preflight_report["candidates"], key=lambda row: row["id"]):
            if query["group"] != group:
                continue
            query_key = tuple(tokenize(query["text"]))
            if len(query_key) != query["length"]:
                raise ValueError("Preflight query length no longer matches original text")
            if query_key in query_keys:
                excluded[group + ":duplicate_normalized_query"] += 1
                continue
            pids = {row["id"] for row in query["positives"]}
            if not pids or not pids <= accepted:
                excluded[group + ":unusable_positive"] += 1
                continue
            if len(positive_union | pids) > positive_cap:
                excluded[group + ":positive_union_cap"] += 1
                continue
            selected.append(query)
            query_keys.add(query_key)
            positive_union.update(pids)
            chosen += 1
            if chosen == required:
                break
    counts = {group: sum(query["group"] == group for query in selected) for group in GROUPS}
    report = {"format_version": 1, "status": "PASS" if all(n == required for n in counts.values()) else "FAIL",
              "selection_rule": preflight_report["selection_rule"], "selected_counts": counts,
              "query_count": len(selected), "positive_union_count": len(positive_union),
              "positive_ids": sorted(positive_union), "positive_cap": positive_cap,
              "exclusions_examined": dict(excluded), "tokenizer": tokenizer_signature(),
              "queries": selected, "candidate_approved": False, "corpus_acceptance": "PENDING"}
    selected_path = output_dir / "selected_positives.jsonl"
    temporary = selected_path.with_suffix(".jsonl.partial")
    with temporary.open("x", encoding="utf-8", newline="\n") as output:
        written = set()
        with (output_dir / "candidate_positives.jsonl").open(encoding="utf-8") as source:
            for line in source:
                row = json.loads(line)
                if row["id"] in positive_union:
                    if row["id"] in written:
                        raise ValueError("Duplicate positive document in preparation output")
                    output.write(line)
                    written.add(row["id"])
        if written != positive_union:
            raise ValueError("Selected positive text is missing from preparation output")
    temporary.replace(selected_path)
    report["selected_positives_sha256"] = file_hash(selected_path)
    report["qrels"] = [{"query_id": query["id"], "document_id": row["id"], "relevance": row["relevance"]}
                       for query in selected for row in query["positives"]]
    # Publish a PASS report only after every selected original is accounted for.
    write_json(output_dir / "selected_queries.json", report)
    return report


def prepare_preflight(source_dir, output_dir):
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / "query_preflight.json").exists():
        raise FileExistsError("Query preflight already exists; use a fresh preparation directory")
    manifest = json.loads((source_dir / "source_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != "v1" or manifest.get("split") not in {"dev", "train"}:
        raise ValueError("Unsupported or incompatible source manifest")
    split = manifest["split"]
    roles = {item["role"]: item for item in manifest["files"]}
    if manifest.get("query_member") != f"queries.{split}.tsv":
        raise ValueError("Query archive member disagrees with source split")
    for role in ("queries", "qrels_" + split):
        item = roles[role]
        if item["filename"] != FILES[role]:
            raise ValueError("Source filename disagrees with source role/split")
        if file_hash(source_dir / item["filename"]) != item["sha256"]:
            raise ValueError("Source hash mismatch")
    with member_stream(source_dir / roles["queries"]["filename"], f"queries.{split}.tsv") as stream:
        queries = parse_queries(stream)
    with (source_dir / roles["qrels_" + split]["filename"]).open("rb") as stream:
        judgments, duplicates = parse_qrels(stream)
    report = preflight(queries, judgments)
    report["identical_duplicate_judgment_rows"] = duplicates
    report["qrels_raw_rows"] = len(judgments) + duplicates
    report["dataset"] = {"version": "v1", "split": split, "query_member": f"queries.{split}.tsv"}
    report["source_sha256"] = {role: roles[role]["sha256"] for role in ("queries", "qrels_" + split)}
    write_json(output_dir / "query_preflight.json", report)
    return report


def validate_source_binding(manifest, preflight_report):
    """Prevent combining queries and documents from different revisions/splits."""
    for key, value in preflight_report["dataset"].items():
        if manifest.get(key) != value:
            raise ValueError("Source dataset/version/split does not match the query preflight")
    roles = {item["role"]: item for item in manifest["files"]}
    for role, digest in preflight_report["source_sha256"].items():
        if role not in roles or roles[role].get("sha256") != digest:
            raise ValueError("Source file identity changed after query preflight")
