"""Independent mathematical anchors for the future production text rankers."""

from decimal import Decimal
import json
import math
from pathlib import Path

import pytest

from tests.text.reference import (
    SCORE_ABS_TOL, SCORE_REL_TOL, collection_statistics, rank,
)


DIRECTORY = Path(__file__).with_name("fixtures")
WORKED = json.loads((DIRECTORY / "worked_example.v1.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((DIRECTORY / "expected.v1.json").read_text(encoding="utf-8"))["worked_example"]


def test_worked_example_frequencies_and_lengths_are_exact():
    stats = collection_statistics(WORKED["documents"])
    assert stats["N"] == 4
    assert stats["lengths"] == {30: 3, 7: 1, 11: 2, 90: 0}
    assert stats["total_tokens"] == 6
    assert stats["avgdl"] == Decimal("1.5")
    assert stats["df"] == {"base": 2, "datos": 2, "índice": 1}
    assert stats["frequencies"][30] == {"base": 2, "datos": 1}
    assert stats["frequencies"][90] == {}
    assert stats["norms"][90] == 0


def test_tfidf_norms_and_balanced_scores_against_closed_form_calculations():
    # Work directly from the four rows, not from the reference's tf/df helpers.
    a = 1 + math.log(5 / 3)
    z = 1 + math.log(5 / 2)
    r = 1 + math.log(2)
    stats = collection_statistics(WORKED["documents"])
    norms = {30: a * math.sqrt(r * r + 1), 7: a, 11: math.hypot(a, z), 90: 0}
    for identifier, norm in norms.items():
        assert float(stats["norms"][identifier]) == pytest.approx(norm, rel=SCORE_REL_TOL, abs=SCORE_ABS_TOL)
    closed_form = {
        30: (r + 1) / math.sqrt(2 * (r * r + 1)),
        7: 1 / math.sqrt(2),
        11: a / math.sqrt(2 * (a * a + z * z)),
    }
    actual = rank(WORKED["documents"], ["base", "datos"], "TF_IDF")
    assert [identifier for identifier, _ in actual] == [30, 7, 11]
    for identifier, score in actual:
        assert float(score) == pytest.approx(closed_form[identifier], rel=SCORE_REL_TOL, abs=SCORE_ABS_TOL)
        frozen = next(row for row in EXPECTED["queries"]["balanced"]["TF_IDF"] if row["id"] == identifier)
        assert float(frozen["score"]) == pytest.approx(closed_form[identifier], rel=SCORE_REL_TOL, abs=SCORE_ABS_TOL)


def test_bm25_scores_against_simplified_rational_coefficients():
    # Both terms have IDF ln(2). Substituting the fixed lengths, avgdl=1.5,
    # k1=6/5, b=3/4 gives these exact rational multipliers independently.
    closed_form = {
        30: math.log(2) * (44 / 41 + 22 / 31),
        7: math.log(2) * 22 / 19,
        11: math.log(2) * 22 / 25,
    }
    actual = rank(WORKED["documents"], ["base", "datos"], "BM25")
    assert [identifier for identifier, _ in actual] == [30, 7, 11]
    for identifier, score in actual:
        assert float(score) == pytest.approx(closed_form[identifier], rel=SCORE_REL_TOL, abs=SCORE_ABS_TOL)
        frozen = next(row for row in EXPECTED["queries"]["balanced"]["BM25"] if row["id"] == identifier)
        assert float(frozen["score"]) == pytest.approx(closed_form[identifier], rel=SCORE_REL_TOL, abs=SCORE_ABS_TOL)


def test_repeated_query_terms_change_cosine_but_not_bm25():
    r = 1 + math.log(2)
    a = 1 + math.log(5 / 3)
    z = 1 + math.log(5 / 2)
    expected = {30: 1.0, 7: r / math.sqrt(r * r + 1),
                11: a / (math.hypot(a, z) * math.sqrt(r * r + 1))}
    repeated = dict(rank(WORKED["documents"], ["base", "base", "datos"], "TF_IDF"))
    for identifier, score in repeated.items():
        assert float(score) == pytest.approx(expected[identifier], rel=SCORE_REL_TOL, abs=SCORE_ABS_TOL)
    assert repeated != dict(rank(WORKED["documents"], ["base", "datos"], "TF_IDF"))
    assert rank(WORKED["documents"], ["base", "base", "datos"], "BM25") == rank(
        WORKED["documents"], ["base", "datos"], "BM25",
    )


@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
def test_unknown_terms_are_projected_out_before_query_norm(model):
    assert rank(WORKED["documents"], ["base", "datos", "desconocidozz"], model) == rank(
        WORKED["documents"], ["base", "datos"], model,
    )
    assert rank(WORKED["documents"], ["desconocidozz"], model) == []
    assert rank(WORKED["documents"], [], model) == []


@pytest.mark.parametrize("documents", [[], [{"id": 1, "tokens": []}], [{"id": 1, "tokens": []}, {"id": 2, "tokens": []}]])
@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
def test_zero_norm_and_zero_average_length_collections(documents, model):
    stats = collection_statistics(documents)
    assert stats["N"] == len(documents)
    assert stats["avgdl"] == 0
    assert stats["df"] == {}
    assert all(norm == 0 for norm in stats["norms"].values())
    assert rank(documents, ["base"], model) == []


@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
@pytest.mark.parametrize("order", ["score_desc", "score_asc"])
def test_equal_scores_use_exact_id_order_even_with_shuffled_input(model, order):
    documents = [{"id": identifier, "tokens": ["base", "datos"]} for identifier in (45, 3)]
    assert [identifier for identifier, _ in rank(documents, ["base"], model, order)] == [3, 45]
    assert [identifier for identifier, _ in rank(documents, ["base"], model, order, 1)] == [3]
    assert rank(documents, ["base"], model, order, 0) == []
