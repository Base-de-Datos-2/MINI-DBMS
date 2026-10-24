"""Offline preparation acceptance, with small adversarial source inputs."""

from io import BytesIO
from hashlib import sha256
import json
from pathlib import Path
import tarfile

import pytest

from benchmarks.text.corpus import (
    TEXT_LIMIT, identifier, member_stream, parse_queries, parse_qrels,
    preflight, prepare_preflight, select_queries, validate_documents, validate_source_binding,
)
from benchmarks.text.esci import asin_id, esci_documents, esci_queries
from benchmarks.text.sources import FILES, file_hash, fetch_source, write_json
from engine.storage.binary import INTEGER_MAX, INTEGER_MIN, MAX_RECORD_SIZE


def _queries():
    return parse_queries([b"1\tbase\n", b"2\tbase de datos\n", b"3\tuna base de datos textual\n"])


def _preflight():
    return preflight(_queries(), {(1, 11): 1, (2, 12): 1, (3, 13): 1}, per_group=1)


@pytest.mark.parametrize("value", [str(INTEGER_MIN), "0", str(INTEGER_MAX)])
def test_identifiers_use_canonical_signed_64_bit_text(value):
    assert identifier(value) == int(value)


@pytest.mark.parametrize("value", ["01", "+1", " 1", "1.0", str(INTEGER_MAX + 1), str(INTEGER_MIN - 1), True, b"\xff"])
def test_invalid_or_aliased_identifiers_are_rejected(value):
    with pytest.raises((ValueError, UnicodeError)):
        identifier(value)


def test_query_text_is_original_and_token_length_is_shared():
    query = parse_queries(["1\t CAFÉ cafe\u0301  \r\n".encode("utf-8")])[1]
    assert query["text"] == " CAFÉ cafe\u0301  "
    assert query["length"] == 2


@pytest.mark.parametrize("lines", [[b"no separator\n"], [b"1\ta\n", b"1\tb\n"], [b"1\t\xff\n"]])
def test_malformed_duplicate_or_invalid_utf8_queries_fail(lines):
    with pytest.raises((ValueError, UnicodeError)):
        parse_queries(lines)


def test_redundant_qrels_are_counted_without_inflating_positives():
    judgments, duplicates = parse_qrels([b"1 0 11 1\n", b"1 0 11 1\n", b"1 0 12 0\n"])
    assert judgments == {(1, 11): 1, (1, 12): 0}
    assert duplicates == 1


@pytest.mark.parametrize("lines", [[b"1 0 11 1\n", b"1 0 11 0\n"], [b"1 0 11 -1\n"], [b"1 11 1\n"]])
def test_conflicting_or_malformed_judgments_fail(lines):
    with pytest.raises(ValueError):
        parse_qrels(lines)


def test_preflight_gates_groups_references_and_distinct_queries():
    good = _preflight()
    assert good["status"] == "PASS"
    assert good["eligible_counts"] == {"1": 1, "3": 1, "5plus": 1}
    assert good["corpus_acceptance"] == "PENDING"
    missing = preflight(_queries(), {(1, 11): 1, (2, 12): 1}, per_group=1)
    assert missing["status"] == "FAIL"
    unresolved = preflight(_queries(), {(999, 11): 1}, per_group=1)
    assert unresolved["status"] == "FAIL"
    assert unresolved["missing_query_references"] == [999]
    repeated = parse_queries([b"1\tbase\n", b"4\tBASE!\n"])
    report = preflight(repeated, {(1, 1): 1, (4, 2): 1}, per_group=2)
    assert report["eligible_counts"]["1"] == 1
    assert report["eligible_query_id_counts"]["1"] == 2


def test_document_validation_preserves_text_and_counts_actual_bytes(tmp_path):
    rows = iter([b"42\t  base\ttext  \n", "7\tcafe\u0301\n".encode(), b"90\t\n"])
    report = validate_documents(rows, tmp_path, {7, 90, 999}, minimum_documents=3)
    assert report["status"] == "PASS"
    assert report["accepted_pool_rows"] == 3
    assert report["accepted_positive_ids"] == [7, 90]
    assert report["missing_positive_ids"] == [999]
    actual = [json.loads(line) for line in (tmp_path / "accepted_pool.jsonl").read_text(encoding="utf-8").splitlines()]
    assert actual == [{"id": 42, "text": "  base\ttext  "}, {"id": 7, "text": "cafe\u0301"}, {"id": 90, "text": ""}]
    assert report["encoded_record_bytes"]["min"] == 12
    assert report["corpus_acceptance"] == "PENDING"
    assert report["heap_reopen"] == "NOT_RUN_1B6"


def test_rejections_distinguish_encoding_characters_bytes_and_ids(tmp_path):
    rows = [b"bad\tx\n", b"1\t\xff\n", ("2\t" + "x" * (TEXT_LIMIT + 1) + "\n").encode(),
            ("3\t" + "é" * (TEXT_LIMIT // 2 + 1) + "\n").encode(), b"4\tok\n"]
    report = validate_documents(iter(rows), tmp_path, {1, 2, 3}, minimum_documents=1)
    assert report["status"] == "PASS"
    assert report["rejections"] == {"invalid_id": 1, "invalid_utf8": 1, "declared_length": 1, "record_size": 1}
    assert report["accepted_pool_rows"] == 1
    assert report["rejected_positive_ids"] == {"1": "invalid_utf8", "2": "declared_length", "3": "record_size"}


def test_exact_capacity_is_validated_through_the_engine(tmp_path):
    report = validate_documents(iter([(f"1\t{'x' * TEXT_LIMIT}\n").encode()]), tmp_path, minimum_documents=1)
    assert report["status"] == "PASS"
    assert report["encoded_record_bytes"]["max"] == MAX_RECORD_SIZE


def test_full_stream_duplicates_invalidate_a_provisional_pool(tmp_path):
    report = validate_documents(iter([b"1\ta\n", b"9\t\n", b"1\tb\n"]), tmp_path, {1}, minimum_documents=1)
    assert report["status"] == "FAIL"
    assert report["rejections"]["duplicate_id"] == 1
    assert report["accepted_positive_ids"] == []
    assert report["rejected_positive_ids"] == {"1": "duplicate_id"}


def test_missing_capacity_does_not_report_a_pass(tmp_path):
    report = validate_documents(iter([b"1\ta\n"]), tmp_path, minimum_documents=2)
    assert report["status"] == "FAIL"
    assert report["accepted_pool_rows"] == 1


def test_late_positive_is_validated_after_pool_is_full(tmp_path):
    report = validate_documents(iter([b"1\ta\n", b"2\tignored\n", b"3\tpositive\n"]), tmp_path, {3}, minimum_documents=1)
    assert report["codec_validated_rows"] == 2
    assert report["unselected_rows_not_codec_validated"] == 1
    assert report["accepted_positive_ids"] == [3]


def test_real_target_cannot_be_satisfied_by_extrapolating_a_sample(tmp_path):
    report = validate_documents((f"{number}\tdocumento {number}\n".encode() for number in range(100000)), tmp_path)
    assert report["status"] == "PASS"
    assert report["scanned_rows"] == report["codec_validated_rows"] == report["accepted_pool_rows"] == 100000


def test_selection_is_deterministic_and_retains_all_original_positives(tmp_path):
    pre = _preflight()
    pre["candidates"].insert(0, {"id": 0, "text": "inutilizable", "length": 1, "group": "1", "positives": [{"id": 999, "relevance": 1}]})
    validation = validate_documents(iter([b"11\ta\n", b"12\tb\n", b"13\tc\n"]), tmp_path, {11, 12, 13, 999}, minimum_documents=3)
    report = select_queries(pre, validation, tmp_path)
    assert report["status"] == "PASS"
    assert [row["id"] for row in report["queries"]] == [1, 2, 3]
    assert report["positive_ids"] == [11, 12, 13]
    assert report["exclusions_examined"] == {"1:unusable_positive": 1}
    assert report["qrels"] == [{"query_id": qid, "document_id": pid, "relevance": 1} for qid, pid in [(1, 11), (2, 12), (3, 13)]]
    assert report["corpus_acceptance"] == "PENDING"


def test_union_cap_and_incomplete_group_prevent_selection_pass(tmp_path):
    validation = validate_documents(iter([b"11\ta\n", b"12\tb\n", b"13\tc\n"]), tmp_path, {11, 12, 13}, minimum_documents=3)
    report = select_queries(_preflight(), validation, tmp_path, positive_cap=2)
    assert report["status"] == "FAIL"
    assert report["query_count"] == 2


def test_any_missing_positive_disqualifies_the_query(tmp_path):
    pre = _preflight()
    pre["candidates"][0]["positives"].append({"id": 999, "relevance": 1})
    validation = validate_documents(iter([b"11\ta\n", b"12\tb\n", b"13\tc\n"]), tmp_path, {11, 12, 13, 999}, minimum_documents=3)
    report = select_queries(pre, validation, tmp_path)
    assert report["status"] == "FAIL"
    assert report["selected_counts"]["1"] == 0


def test_modified_positive_spool_is_rejected(tmp_path):
    validation = validate_documents(iter([b"11\ta\n"]), tmp_path, {11}, minimum_documents=1)
    (tmp_path / "candidate_positives.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        select_queries(_preflight(), validation, tmp_path)
    assert not (tmp_path / "selected_queries.json").exists()


@pytest.mark.parametrize("asin", ["0000000000", "0999999999", "B012345678", "ZZZZZZZZZZ"])
def test_asin_encoding_is_exact_bijective_and_within_codec(asin):
    number = asin_id(asin)
    assert 0 <= number <= INTEGER_MAX
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digits = ""
    while number:
        number, remainder = divmod(number, 36)
        digits = alphabet[remainder] + digits
    assert digits.zfill(10) == asin


@pytest.mark.parametrize("asin", ["b012345678", "short", "00000000000", None, "B01234567!"])
def test_asin_aliases_are_not_coerced(asin):
    with pytest.raises(ValueError):
        asin_id(asin)


def test_esci_filtering_and_labels_keep_original_queries():
    rows = [{"query_id": 1, "query": "Original QUERY", "product_id": "B012345678", "product_locale": "us",
             "split": "test", "large_version": 1, "esci_label": grade} for grade in ["E"]]
    rows += [{**rows[0], "query_id": 2, "product_locale": "es"}, {**rows[0], "query_id": 3, "split": "train"}]
    queries, judgments = esci_queries(iter(rows))
    assert queries == {1: {"id": 1, "text": "Original QUERY", "length": 2}}
    assert judgments == {(1, asin_id("B012345678")): 3}


def test_esci_title_retains_newlines_and_source_mapping(tmp_path):
    rows = [{"product_id": "B012345678", "product_locale": "us", "product_title": "  título\noriginal\t "},
            {"product_id": "B012345679", "product_locale": "us", "product_title": None}]
    report = validate_documents(esci_documents(iter(rows)), tmp_path, minimum_documents=1)
    data = json.loads((tmp_path / "accepted_pool.jsonl").read_text(encoding="utf-8"))
    assert data["text"] == "  título\noriginal\t "
    assert data["source_id"] == "B012345678"
    assert report["accepted_pool_rows"] == 1


def test_tar_reads_only_the_requested_regular_member(tmp_path):
    path = tmp_path / "queries.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in [("../ignored.tsv", b"not extracted"), ("folder/queries.dev.tsv", b"1\tbase\n")]:
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, BytesIO(data))
    with member_stream(path, "queries.dev.tsv") as stream:
        assert parse_queries(stream)[1]["text"] == "base"
    assert not (tmp_path.parent / "ignored.tsv").exists()


def test_source_manifest_split_or_hash_mismatch_is_rejected(tmp_path):
    manifest = {"version": "v1", "split": "dev", "query_member": "queries.train.tsv", "files": []}
    write_json(tmp_path / "source_manifest.json", manifest)
    with pytest.raises(ValueError, match="split"):
        prepare_preflight(tmp_path, tmp_path / "out")


def test_network_download_verifies_ranges_hashes_and_cache(monkeypatch, tmp_path):
    payload = b"source bytes"
    class Response(BytesIO):
        def __init__(self, content, status, headers):
            super().__init__(content)
            self.status, self.headers = status, headers
    def open_url(request, **kwargs):
        if request.get_method() == "HEAD":
            return Response(b"", 200, {"Content-Length": str(len(payload)), "ETag": '"version1"'})
        return Response(payload, 206, {"Content-Range": f"bytes 0-{len(payload)-1}/{len(payload)}", "ETag": '"version1"'})
    monkeypatch.setattr("benchmarks.text.sources.urllib.request.urlopen", open_url)
    receipt = fetch_source(tmp_path, "qrels_dev")
    assert receipt["downloaded_bytes"] == len(payload)
    assert receipt["sha256"] == file_hash(tmp_path / FILES["qrels_dev"])
    assert fetch_source(tmp_path, "qrels_dev")["sha256"] == receipt["sha256"]
    (tmp_path / FILES["qrels_dev"]).write_bytes(b"modified")
    with pytest.raises(ValueError, match="disagrees"):
        fetch_source(tmp_path, "qrels_dev")


def test_network_range_mismatch_never_publishes_a_source(monkeypatch, tmp_path):
    class Response(BytesIO):
        status = 200
        headers = {"Content-Length": "3", "ETag": '"v1"'}
    monkeypatch.setattr("benchmarks.text.sources.urllib.request.urlopen", lambda *a, **kw: Response(b"bad"))
    with pytest.raises(ValueError, match="byte range"):
        fetch_source(tmp_path, "qrels_dev")
    assert not (tmp_path / FILES["qrels_dev"]).exists()
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5])
def test_thresholds_cannot_turn_an_empty_preparation_into_a_pass(tmp_path, invalid):
    with pytest.raises(ValueError):
        preflight({}, {}, per_group=invalid)
    with pytest.raises(ValueError):
        validate_documents(iter([]), tmp_path, minimum_documents=invalid)


def test_selection_is_reproducible_in_independent_output_directories(tmp_path):
    reports = []
    for name in ("first", "second"):
        directory = tmp_path / name
        validation = validate_documents(iter([b"11\ta\n", b"12\tb\n", b"13\tc\n"]), directory, {11, 12, 13}, minimum_documents=3)
        reports.append(select_queries(_preflight(), validation, directory))
    assert reports[0] == reports[1]


def test_selection_checks_the_preflight_binding_before_writing(tmp_path):
    pre = _preflight()
    pre["source_sha256"] = {"queries": "source-input-hash"}
    pre["dataset"] = {"version": "test"}
    write_json(tmp_path / "query_preflight.json", pre)
    validation = validate_documents(iter([b"11\ta\n", b"12\tb\n", b"13\tc\n"]), tmp_path, {11, 12, 13}, minimum_documents=3)
    validation["preflight_sha256"] = file_hash(tmp_path / "query_preflight.json")
    validation["dataset"] = pre["dataset"]
    modified = {**pre, "dataset": {"version": "changed"}}
    write_json(tmp_path / "query_preflight.json", modified)
    with pytest.raises(ValueError, match="changed after document validation"):
        select_queries(pre, validation, tmp_path)
    assert not (tmp_path / "selected_queries.json").exists()


def test_selection_failure_does_not_publish_pass_before_positive_texts_exist(tmp_path):
    validation = validate_documents(iter([b"11\ta\n"]), tmp_path, {11}, minimum_documents=1)
    validation["accepted_positive_ids"] = [11, 12, 13]
    with pytest.raises(ValueError, match="text is missing"):
        select_queries(_preflight(), validation, tmp_path)
    assert not (tmp_path / "selected_queries.json").exists()


def test_null_and_non_utf8_scalar_titles_are_rejected_without_conversion(tmp_path):
    report = validate_documents(iter([{"id": 1, "text": None}, {"id": 2, "text": "\ud800"},
                                     {"id": 3, "text": "valid"}]), tmp_path, {1, 2}, minimum_documents=1)
    assert report["status"] == "PASS"
    assert report["rejections"] == {"invalid_text_type": 1, "invalid_utf8": 1}


def test_existing_unverified_partial_is_preserved(monkeypatch, tmp_path):
    class Response(BytesIO):
        status = 200
        headers = {"Content-Length": "10", "ETag": '"not-a-content-hash"'}
    monkeypatch.setattr("benchmarks.text.sources.urllib.request.urlopen", lambda *a, **kw: Response())
    partial = tmp_path / (FILES["qrels_dev"] + ".partial")
    partial.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        fetch_source(tmp_path, "qrels_dev")
    assert partial.read_bytes() == b"preserve"


def test_git_lfs_resume_is_accepted_only_after_full_content_hash_verification(monkeypatch, tmp_path):
    data = b"complete original source"
    etag = '"' + sha256(data).hexdigest() + '"'
    class Response(BytesIO):
        def __init__(self, body, status, headers):
            super().__init__(body)
            self.status, self.headers = status, headers
    def open_url(request, **kwargs):
        if request.get_method() == "HEAD":
            return Response(b"", 200, {"Content-Length": str(len(data)), "ETag": etag})
        start, end = map(int, request.get_header("Range")[6:].split("-"))
        return Response(data[start:end+1], 206, {"Content-Range": f"bytes {start}-{end}/{len(data)}", "ETag": etag})
    monkeypatch.setattr("benchmarks.text.sources.urllib.request.urlopen", open_url)
    filename = "input.parquet"
    (tmp_path / (filename + ".partial")).write_bytes(data[:5])
    receipt = fetch_source(tmp_path, "products", url="https://media.githubusercontent.com/media/pinned/input", filename=filename)
    assert receipt["sha256"] == sha256(data).hexdigest()
    assert (tmp_path / filename).read_bytes() == data


def test_source_binding_rejects_cross_revision_or_cross_split_data():
    pre = {"dataset": {"revision": "original", "split": "test"}, "source_sha256": {"examples": "sha"}}
    manifest = {"revision": "original", "split": "test", "files": [{"role": "examples", "sha256": "sha"}]}
    validate_source_binding(manifest, pre)
    with pytest.raises(ValueError, match="dataset/version/split"):
        validate_source_binding({**manifest, "revision": "changed"}, pre)
    with pytest.raises(ValueError, match="file identity"):
        validate_source_binding({**manifest, "files": [{"role": "examples", "sha256": "changed"}]}, pre)


def test_reports_use_portable_lf_bytes(tmp_path):
    path = tmp_path / "report.json"
    write_json(path, {"text": "á"})
    assert b"\r\n" not in path.read_bytes()
    assert json.loads(path.read_text(encoding="utf-8")) == {"text": "á"}
