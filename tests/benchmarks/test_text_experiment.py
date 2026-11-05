import copy
import hashlib
import json

import pytest

from benchmarks.text import fts
from benchmarks.text.experiment import METHODS, REPETITIONS, engine_sql, sql_literal
from benchmarks.text.metrics import evaluate, mean, positives, precision_at_k, read_qrels, recall_at_k
from benchmarks.text.results import load_queries


def test_precision_keeps_denominator_ten_and_recall_uses_subset_positives():
    relevant = {1, 2, 3, 4}
    assert precision_at_k([1, 9, 2], relevant) == pytest.approx(0.2)
    assert recall_at_k([1, 9, 2], relevant) == pytest.approx(0.5)
    ranking = list(range(1, 21))
    assert precision_at_k(ranking, relevant) == pytest.approx(0.4)
    assert recall_at_k(ranking, relevant) == 1


def test_zero_positives_is_not_evaluable_rather_than_zero():
    assert recall_at_k([1, 2], set()) is None
    result = evaluate([1, 2], set())
    assert result["precision_at_10"] == 0 and result["recall_at_10"] is None
    assert mean([None, 0.5, 1.0]) == pytest.approx(0.75)
    assert mean([None]) is None


def test_rankings_cannot_repeat_documents():
    with pytest.raises(ValueError):
        precision_at_k([1, 1], {1})


def test_qrels_positives_respect_grade_and_subset(tmp_path):
    path = tmp_path / "qrels.tsv"
    path.write_text("7\t0\t10\t3\n7\t0\t11\t0\n7\t0\t12\t1\n8\t0\t10\t2\n", encoding="utf-8")
    judgments = read_qrels(path)
    assert positives(judgments[7]) == {10, 12}
    assert positives(judgments[7], {10, 11}) == {10}
    path.write_text("7\t0\t10\t3\n7\t0\t10\t1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_qrels(path)


def test_tsquery_is_an_or_of_quoted_distinct_engine_terms():
    assert fts.tsquery_text("Machine  LEARNING machine") == "'machine' | 'learning'"
    assert fts.tsquery_text("$44red ' phone") == "'44red' | 'phone'"
    assert fts.tsquery_text("!!! ...") is None


def test_tsvector_text_keeps_engine_terms_positions_and_symbols_postgres_drops():
    assert fts.tsvector_text("No. 10 Envelopes ½ no") == "'no':1,5 '10':2 'envelopes':3 '½':4"


def test_lexeme_digest_is_id_ordered_and_frequency_aware():
    count, digest = fts.lexeme_digest([(2, "b a a"), (1, "")])
    expected = hashlib.md5("1:\n2:a/2 b/1".encode()).hexdigest()
    assert (count, digest) == (2, expected)
    assert fts.ids_digest([3, 1]) == (2, hashlib.md5(b"1,3").hexdigest())


def test_engine_sql_escapes_quotes_and_uses_the_native_contract():
    assert sql_literal("men's") == "'men''s'"
    assert engine_sql("bm25", "men's shoes") == (
        "SELECT id, SCORE() AS s FROM documentos WHERE MATCH(contenido, 'men''s shoes') USING BM25 LIMIT 10")
    assert engine_sql("tfidf", "x", limit=False, order_by_id=True).endswith("USING TF_IDF ORDER BY id ASC")


def measured(tmp_path, size=1000):
    rows = [{"size": size, "method": method, "query_id": query_id, "group": "1", "length": 1,
             "repetition": repetition, "elapsed_seconds": 0.001, "precision_at_10": 0.1,
             "recall_at_10": 0.5, "server_seconds": 0.0005 if method == "postgres" else None, "top10": []}
            for method in METHODS for query_id in (1, 2) for repetition in range(REPETITIONS)]
    return rows


def write_rows(tmp_path, rows, size=1000):
    (tmp_path / f"queries_{size}.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_complete_query_matrix_loads(tmp_path):
    write_rows(tmp_path, measured(tmp_path))
    assert len(load_queries(tmp_path, 1000, {1, 2})) == len(METHODS) * 2 * REPETITIONS


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "negative", "server", "foreign"])
def test_incomplete_or_invalid_matrices_are_rejected(tmp_path, corruption):
    rows = copy.deepcopy(measured(tmp_path))
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate":
        rows[-1] = copy.deepcopy(rows[-2])
    elif corruption == "negative":
        rows[0]["elapsed_seconds"] = -1
    elif corruption == "server":
        next(row for row in rows if row["method"] == "postgres")["server_seconds"] = None
    else:
        rows[0]["query_id"] = 99
    write_rows(tmp_path, rows)
    with pytest.raises(ValueError):
        load_queries(tmp_path, 1000, {1, 2})
