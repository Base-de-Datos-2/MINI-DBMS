"""Frozen fixture integrity, independent scores and actual storage round trips."""

from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from engine.catalog import Column, ColumnConstraint, DataType, Schema, TableMetadata
from engine.maintenance.validation import validate_record
from engine.storage import HeapFile, Record
from engine.storage.binary import INTEGER_STRUCT, MAX_RECORD_SIZE, VARCHAR_LENGTH_STRUCT
from engine.text import tokenize, tokenizer_signature
from tests.text.reference import (
    SCORE_ABS_TOL, SCORE_REL_TOL, collection_statistics, frozen_statistics, rank,
)


DIRECTORY = Path(__file__).with_name("fixtures")


def _read(name):
    return json.loads((DIRECTORY / name).read_text(encoding="utf-8"))


COLLECTION_FILE = _read("collections.v1.json")
COLLECTIONS = COLLECTION_FILE["collections"]
CASES = _read("queries.v1.json")["cases"]
EXPECTED = _read("expected.v1.json")
MANIFEST = _read("manifest.v1.json")


def _float_ranking(documents, case):
    """Second calculation: dense float vectors and direct scalar BM25 sums."""
    counts = {row["id"]: Counter(row["tokens"]) for row in documents}
    vocabulary = sorted({term for row in counts.values() for term in row})
    n = len(counts)
    df = {term: sum(term in row for row in counts.values()) for term in vocabulary}
    query = Counter(case["tokens"])
    idf = [math.log((n + 1) / (df[term] + 1)) + 1 for term in vocabulary]
    qvector = [(1 + math.log(query[term])) * weight if query[term] else 0.0
               for term, weight in zip(vocabulary, idf)]
    qnorm = math.sqrt(math.fsum(weight * weight for weight in qvector))
    average_length = sum(sum(row.values()) for row in counts.values()) / n if n else 0
    results = []
    for identifier, row in counts.items():
        terms = set(query) & set(row)
        if not terms:
            continue
        if case["model"] == "TF_IDF":
            vector = [(1 + math.log(row[term])) * weight if row[term] else 0.0
                      for term, weight in zip(vocabulary, idf)]
            norm = math.sqrt(math.fsum(weight * weight for weight in vector))
            score = math.fsum(d * q for d, q in zip(vector, qvector)) / (norm * qnorm)
        else:
            length = sum(row.values())
            score = math.fsum(
                math.log1p((n - df[term] + 0.5) / (df[term] + 0.5)) *
                (row[term] * 2.2) / (row[term] + 1.2 * (0.25 + 0.75 * length / average_length))
                for term in sorted(terms)
            )
        results.append((identifier, score))
    key = {"score_desc": lambda row: (-row[1], row[0]), "score_asc": lambda row: (row[1], row[0]),
           "id_asc": lambda row: row[0], "id_desc": lambda row: -row[0]}[case["order"]]
    results.sort(key=key)
    return results if case["limit"] is None else results[:case["limit"]]


def test_fixture_versions_signatures_and_content_hashes():
    assert MANIFEST["fixture_version"] == "text-contract-v1"
    for name, digest in MANIFEST["sha256"].items():
        assert sha256((DIRECTORY / name).read_bytes()).hexdigest() == digest, name
        assert _read(name)["format_version"] == 1
    assert MANIFEST["format_version"] == 1
    # This is source-fixture provenance, not an index opened under a different
    # runtime. Exact token checks below validate compatibility on other Python
    # Unicode versions; a future index build records its own runtime signature.
    assert COLLECTION_FILE["tokenizer"]["algorithm"] == tokenizer_signature()["algorithm"]
    assert COLLECTION_FILE["tokenizer"]["unicode_version"] == "15.0.0"
    assert MANIFEST["ranking"] == {
        "tfidf": "log-tf-smoothed-idf-cosine-v1", "bm25": "positive-idf-distinct-query-v1",
        "k1": "1.2", "b": "0.75", "score_rel_tol": "1e-10", "score_abs_tol": "1e-12",
    }
    assert len({case["id"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("name", COLLECTIONS)
def test_fixtures_have_unique_shuffled_ids_and_exact_tokenization(name):
    documents = COLLECTIONS[name]["documents"]
    identifiers = [row["id"] for row in documents]
    assert identifiers != sorted(identifiers)
    assert len(identifiers) == len(set(identifiers))
    for row in documents:
        assert type(row["id"]) is int
        assert tokenize(row["text"]) == tuple(row["tokens"])
    assert frozen_statistics(documents) == EXPECTED["collections"][name]
    if name == "documentos":
        assert len(documents) == 16
        stats = EXPECTED["collections"][name]
        assert (stats["N"], stats["total_tokens"], stats["avgdl"]) == (16, 61, "3.8125")
        assert stats["df"]["base"] == 5
        assert stats["df"]["datos"] == 6
    else:
        assert any("machine learning" in row["text"] for row in documents)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_frozen_rankings_match_two_independent_calculations(case):
    assert tokenize(case["text"]) == tuple(case["tokens"])
    documents = COLLECTIONS[case["collection"]]["documents"]
    frozen = EXPECTED["queries"][case["id"]]
    decimal_rows = rank(documents, case["tokens"], case["model"], case["order"], case["limit"])
    float_rows = _float_ranking(documents, case)
    expected_ids = [row["id"] for row in frozen]
    assert [identifier for identifier, _ in decimal_rows] == expected_ids
    assert [identifier for identifier, _ in float_rows] == expected_ids
    for actual in (decimal_rows, float_rows):
        for (_, score), row in zip(actual, frozen):
            assert math.isfinite(float(score))
            assert float(score) == pytest.approx(float(row["score"]), rel=SCORE_REL_TOL, abs=SCORE_ABS_TOL)


def test_fixture_expectations_anchor_ties_unknown_terms_and_limits():
    results = EXPECTED["queries"]
    assert results["pair_bm25"] == results["repeat_bm25"] == results["mixed_unknown_bm25"]
    assert results["pair_tfidf"] == results["mixed_unknown_tfidf"]
    assert results["pair_tfidf"] != results["repeat_tfidf"]
    assert [row["id"] for row in results["pair_tfidf"]] == [3, 45, 12, 42, 9, 61]
    assert results["pair_tfidf"][0]["score"] == results["pair_tfidf"][1]["score"]
    assert [row["id"] for row in results["assignment_bm25"]] == [4, 14, 33, 21]
    assert results["assignment_bm25"][0]["score"] == results["assignment_bm25"][1]["score"]
    assert results["limit_large"] == results["pair_bm25"]
    assert results["lowest_score"][0]["id"] == 9
    assert results["lowest_id"][0]["id"] == 3
    assert results["highest_id"][0]["id"] == 61
    for name in ("empty", "punctuation", "unknown", "limit_zero"):
        assert results[name] == []


@pytest.mark.parametrize("case", _read("invalid_documents.v1.json")["cases"], ids=lambda case: case["id"])
def test_duplicate_id_inputs_remain_separate_negative_acceptance_cases(case):
    assert case["expected_error"] == "duplicate_id"
    for row in case["documents"]:
        assert tokenize(row["text"]) == tuple(row["tokens"])
    with pytest.raises(ValueError, match="Duplicate document ID"):
        collection_statistics(case["documents"])
    # This checks reference/input validity; SPIMI block rejection is phase 2.


@pytest.mark.parametrize("name", COLLECTIONS)
def test_all_fixture_rows_survive_heap_and_a_fresh_process(tmp_path, name):
    collection = COLLECTIONS[name]
    schema = Schema([Column("id", DataType.INTEGER), Column(collection["text_column"], DataType.VARCHAR)])
    text_limit = MAX_RECORD_SIZE - INTEGER_STRUCT.size - VARCHAR_LENGTH_STRUCT.size
    table = TableMetadata(name, schema, constraints=(
        ColumnConstraint("id", primary_key=True),
        ColumnConstraint(collection["text_column"], varchar_length=text_limit),
    ))
    heap_path = tmp_path / "fixture.heap"
    manifest = []
    with HeapFile.create(heap_path, schema) as heap:
        for source in collection["documents"]:
            row = Record(schema, [source["id"], source["text"]])
            assert len(validate_record(table, row)) <= MAX_RECORD_SIZE
            rid = heap.insert(row)
            manifest.append({"id": source["id"], "text": source["text"], "rid": [rid.page_id, rid.slot_id],
                             "sha256": sha256(source["text"].encode("utf-8")).hexdigest()})
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    # The child has no writer objects, schema instances or in-memory RID map.
    script = '''
from hashlib import sha256
import json
from pathlib import Path
import sys
from engine.storage import HeapFile, RID

rows = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
with HeapFile.open(sys.argv[1]) as heap:
    assert heap.record_count == len(rows)
    scanned = [(rid.page_id, rid.slot_id, record.values[0], record.values[1])
               for rid, record in heap.scan()]
    assert scanned == [(row["rid"][0], row["rid"][1], row["id"], row["text"]) for row in rows]
    for row in rows:
        record = heap.read(RID(*row["rid"]))
        assert record.values == (row["id"], row["text"])
        assert sha256(record.values[1].encode("utf-8")).hexdigest() == row["sha256"]
print("fresh-process round trip verified")
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(heap_path), str(snapshot_path)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "fresh-process round trip verified"
    with HeapFile.open(heap_path) as heap:
        assert [row.values for _, row in heap.scan()] == [(row["id"], row["text"]) for row in manifest]
