"""Small adversarial exports and real isolated-process Heap persistence checks."""

import json
from types import SimpleNamespace

import pytest

from benchmarks.text.acceptance import (
    acceptance_report, build_subsets, canonical, inspect_subsets, load_preparation,
    read_json, reopen_heap, verify_heap,
)
from benchmarks.text.corpus import TEXT_LIMIT, preflight, select_queries, validate_documents
from benchmarks.text.sources import file_hash, write_json
from engine.storage import HeapFile, Record


SIZES = (5, 10, 12)


def prepare(root):
    root.mkdir()
    queries = {1: {"id": 1, "text": "café", "length": 1},
               2: {"id": 2, "text": "base de datos", "length": 3},
               3: {"id": 3, "text": "una base de datos textual", "length": 5}}
    report = preflight(queries, {(1, 31): 3, (2, 32): 2, (3, 33): 1}, per_group=1)
    report["dataset"] = {"dataset": "unit", "version": "v1", "split": "test"}
    write_json(root / "query_preflight.json", report)
    rows = [{"id": pid, "text": "" if pid == 1 else f"  café cafe\u0301\nProducto {pid}  "}
            for pid in list(range(1, 13)) + [31, 32, 33]]
    validation = validate_documents(rows, root, {31, 32, 33}, minimum_documents=12)
    validation.update(preflight_sha256=file_hash(root / "query_preflight.json"), dataset=report["dataset"])
    write_json(root / "document_validation.json", validation)
    select_queries(report, validation, root)
    return root


def built(tmp_path):
    preparation = prepare(tmp_path / "preparation")
    target = tmp_path / "export"
    build_subsets(preparation, target, {(1, 31): 3, (2, 32): 2, (3, 33): 1, (1, 2): 0}, sizes=SIZES)
    return preparation, target


def refresh(target, size, name):
    """Repair file receipts so corruption tests exercise semantic checks too."""
    manifest = read_json(target / "subsets_manifest.json")
    path = target / str(size) / name
    manifest["subsets"][str(size)]["files"][name] = {"sha256": file_hash(path), "bytes": path.stat().st_size}
    local = read_json(target / str(size) / "manifest.json")
    local["files"] = manifest["subsets"][str(size)]["files"]
    write_json(target / str(size) / "manifest.json", local)
    manifest["subset_manifest_sha256"][str(size)] = file_hash(target / str(size) / "manifest.json")
    write_json(target / "subsets_manifest.json", manifest)


def test_exports_are_byte_reproducible_nested_and_preserve_all_originals(tmp_path):
    preparation, target = built(tmp_path)
    report = inspect_subsets(target, sizes=SIZES, required_per_group=1)
    assert [r["documents"] for r in report.values()] == list(SIZES)
    assert all(r["positive_documents"] == r["positive_pairs"] == 3 for r in report.values())
    second = tmp_path / "second"
    build_subsets(preparation, second, {(1, 31): 3, (2, 32): 2, (3, 33): 1, (1, 2): 0}, sizes=SIZES)
    for path in target.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (second / path.relative_to(target)).read_bytes()
    contents = [(target / str(size) / "documents.jsonl").read_bytes().splitlines() for size in SIZES]
    assert contents[0] == contents[1][:5] == contents[2][:5]
    assert contents[1] == contents[2][:10]
    for line in contents[-1]:
        row = json.loads(line)
        if row["id"] != 1:
            assert row["text"] == f"  café cafe\u0301\nProducto {row['id']}  "
    for size in SIZES:
        encoded_sizes = [12 + len(json.loads(line)["text"].encode("utf-8")) for line in contents[-1][:size]]
        statistics = report[str(size)]["encoded_record_bytes"]
        assert statistics["min"] == min(encoded_sizes)
        assert statistics["max"] == max(encoded_sizes)
        assert statistics["mean"] == sum(encoded_sizes) / size
        assert sum(statistics["histogram_upper_bounds"].values()) == size
    # A zero grade is retained iff the judged document belongs to that subset.
    for size in SIZES:
        rows = [json.loads(line) for line in (target / str(size) / "documents.jsonl").read_bytes().splitlines()]
        assert ("1\t0\t2\t0" in (target / str(size) / "qrels.tsv").read_text()) == any(r["id"] == 2 for r in rows)


def test_changed_seed_changes_distractors_but_keeps_complete_positives(tmp_path):
    preparation, target = built(tmp_path)
    other = tmp_path / "seed"
    build_subsets(preparation, other, sizes=SIZES, seed=123)
    assert file_hash(target / "12" / "documents.jsonl") != file_hash(other / "12" / "documents.jsonl")
    assert inspect_subsets(other, sizes=SIZES, required_per_group=1)["5"]["positive_documents"] == 3


@pytest.mark.parametrize("mode", ["duplicate", "oversized", "missing_positive", "overlap_conflict"])
def test_builder_rejects_invalid_documents_even_with_updated_spool_receipt(tmp_path, mode):
    preparation = prepare(tmp_path / "preparation")
    name = "selected_positives.jsonl" if mode in {"missing_positive", "overlap_conflict"} else "accepted_pool.jsonl"
    path = preparation / name
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    if mode == "duplicate":
        rows.append(rows[0])
    elif mode == "oversized":
        rows[0]["text"] = "é" * TEXT_LIMIT
    elif mode == "missing_positive":
        rows.pop()
    else:
        rows.append({"id": 1, "text": "changed overlap"})
    path.write_bytes(b"".join(canonical(row) for row in rows))
    if name == "accepted_pool.jsonl":
        report = read_json(preparation / "document_validation.json")
        report["outputs"][name]["sha256"] = file_hash(path)
        write_json(preparation / "document_validation.json", report)
    else:
        report = read_json(preparation / "selected_queries.json")
        report["selected_positives_sha256"] = file_hash(path)
        write_json(preparation / "selected_queries.json", report)
    with pytest.raises(ValueError):
        build_subsets(preparation, tmp_path / "bad", sizes=SIZES)
    assert not (tmp_path / "bad" / "subsets_manifest.json").exists()


@pytest.mark.parametrize("mode", ["missing_grade", "changed_grade", "extra_positive"])
def test_complete_original_judgments_are_required(tmp_path, mode):
    preparation = prepare(tmp_path / "preparation")
    judgments = {(1, 31): 3, (2, 32): 2, (3, 33): 1}
    if mode == "missing_grade":
        judgments.pop((1, 31))
    elif mode == "changed_grade":
        judgments[1, 31] = 1
    else:
        judgments[1, 9] = 1
    with pytest.raises(ValueError, match="positive judgments"):
        build_subsets(preparation, tmp_path / "bad", judgments, sizes=SIZES)


def test_insufficient_query_groups_and_incomplete_spool_fail_early(tmp_path):
    preparation = prepare(tmp_path / "preparation")
    path = preparation / "selected_queries.json"
    report = read_json(path)
    report["queries"].pop()
    write_json(path, report)
    with pytest.raises(ValueError, match="Insufficient query groups"):
        build_subsets(preparation, tmp_path / "bad", sizes=SIZES)


@pytest.mark.parametrize("damage", ["nesting", "text", "duplicate", "hash", "positive", "queries"])
def test_inspector_detects_corruption_even_when_receipts_are_repaired(tmp_path, damage):
    _, target = built(tmp_path)
    size, name = (10, "documents.jsonl")
    path = target / str(size) / name
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    if damage == "nesting":
        rows[3]["id"] = 999
    elif damage == "text":
        rows[0]["text"] += " changed"
    elif damage == "duplicate":
        rows[-1] = rows[0]
    elif damage == "positive":
        size = 5
        path = target / str(size) / name
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        rows[0]["id"] = 999
    elif damage == "queries":
        name, size = "queries.json", 10
        path = target / str(size) / name
        report = read_json(path)
        report["queries"][0]["text"] = "altered"
        write_json(path, report)
    if damage != "queries":
        path.write_bytes(b"".join(canonical(row) for row in rows))
    if damage != "hash":
        refresh(target, size, name)
    else:
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        inspect_subsets(target, sizes=SIZES, required_per_group=1)


def test_actual_heap_reopens_in_distinct_isolated_process_and_preserves_every_rid(tmp_path):
    _, target = built(tmp_path)
    report = verify_heap(target, size=12)
    assert report["status"] == "PASS", report
    assert report["child"]["process_id"] != report["writer_process_id"]
    assert report["child"]["rows"] == report["child"]["verified_rid_mappings"] == 12
    assert report["child"]["content_before_sha256"] == report["child"]["content_after_sha256"]


@pytest.mark.parametrize("damage", ["duplicate", "oversized", "missing", "missing_file", "child_failure", "child_timeout"])
def test_heap_failures_publish_fail_receipts(tmp_path, monkeypatch, damage):
    _, target = built(tmp_path)
    path = target / "12" / "documents.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    if damage == "duplicate":
        rows[-1] = rows[0]
    elif damage == "oversized":
        rows[0]["text"] = "é" * TEXT_LIMIT
    elif damage == "missing":
        rows.pop()
    elif damage == "child_failure":
        monkeypatch.setattr("benchmarks.text.acceptance.subprocess.run",
                            lambda *a, **k: SimpleNamespace(returncode=1, stderr="injected failure"))
    else:
        import subprocess
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("child", 1)
        monkeypatch.setattr("benchmarks.text.acceptance.subprocess.run", timeout)
    path.write_bytes(b"".join(canonical(row) for row in rows))
    if damage == "missing_file":
        path.unlink()
    report = verify_heap(target, size=12)
    assert report["status"] == "FAIL" and report["errors"] and not report["fresh_process"]
    assert read_json(target / "heap_verification.json") == report


def test_reopen_checks_actual_content_not_just_count_or_forged_rids(tmp_path):
    _, target = built(tmp_path)
    assert verify_heap(target, size=12)["status"] == "PASS"
    work = target / "heap_verification"
    rid_path = work / "rids.jsonl"
    rows = [json.loads(line) for line in rid_path.read_bytes().splitlines()]
    rows[0]["sha256"] = "0" * 64
    rid_path.write_bytes(b"".join(canonical(row) for row in rows))
    with pytest.raises(ValueError, match="RID/content"):
        reopen_heap(work / "documents.heap", target / "12" / "documents.jsonl", rid_path)


def test_reopen_compares_every_row_without_requiring_expected_file_order(tmp_path):
    _, target = built(tmp_path)
    rows = [{"id": pid, "text": "x" * length} for pid, length in enumerate(
        [3900, 200, 10, 3500, 500, 1, 3300, 1000, 90, 3400, 1000, 1], 100)]
    (target / "12" / "documents.jsonl").write_bytes(b"".join(canonical(row) for row in rows))
    report = verify_heap(target, size=12)
    assert report["status"] == "PASS", report
    # The content checker keys by ID/RID; export-order checks belong to the
    # subset gate. Reordering this expectation file preserves logical contents.
    path = target / "12" / "documents.jsonl"
    path.write_bytes(b"".join(canonical(row) for row in reversed(rows)))
    work = target / "heap_verification"
    child = reopen_heap(work / "documents.heap", path, work / "rids.jsonl")
    assert child["rows"] == 12
    assert child["content_before_sha256"] == report["child"]["content_after_sha256"]


def test_reopen_detects_changed_heap_content_despite_unchanged_count(tmp_path):
    _, target = built(tmp_path)
    assert verify_heap(target, size=12)["status"] == "PASS"
    path = target / "heap_verification" / "documents.heap"
    with HeapFile.open(path) as heap:
        rid, record = next(heap.scan())
        heap.delete(rid)
        heap.insert(Record(heap.schema, [record.values[0], "changed original content"]))
        assert heap.record_count == 12
    with pytest.raises(ValueError, match="RID/content"):
        reopen_heap(path, target / "12" / "documents.jsonl", target / "heap_verification" / "rids.jsonl")


def test_formal_acceptance_never_promotes_small_fixture_to_real_corpus(tmp_path):
    preparation, target = built(tmp_path)
    verify_heap(target, size=12)
    report = acceptance_report(tmp_path / "no_sources", preparation, target)
    assert report["status"] == report["corpus_acceptance"] == "FAIL"
    assert not report["candidate_approved"]
    assert len(report["criteria"]) == 6
    assert all(gate["status"] == "FAIL" for gate in report["criteria"].values())
    assert read_json(target / "corpus_feasibility.json") == report


def test_exports_are_immutable_and_preparation_hashes_are_bound(tmp_path):
    preparation, target = built(tmp_path)
    with pytest.raises(FileExistsError):
        build_subsets(preparation, target, sizes=SIZES)
    path = preparation / "accepted_pool.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="pool hash"):
        load_preparation(preparation)
