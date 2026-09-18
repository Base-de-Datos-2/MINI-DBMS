"""Stage 9 Task 9.13: every presentation preset is verified through HTTP."""

from collections import Counter, defaultdict

import pytest

from api.demo import PRESETS, big_enrollments, big_students
from tests.api_helpers import (
    BIG_ENROLLMENTS,
    BIG_STUDENTS,
    details_of,
    names,
    query,
)


SMALL = [preset for preset in PRESETS if preset.expected is not None]
BIG = {preset.label: preset for preset in PRESETS if preset.expected is None}


@pytest.mark.parametrize("preset", SMALL, ids=[preset.label for preset in SMALL])
def test_small_presets_return_their_known_answers(client, preset):
    response = query(client, preset.sql, max_rows=500)
    body = response.json()

    if preset.expected == "SQL_ERROR":
        assert response.status_code == 422
        assert body["error"]["code"] == "SQL_ERROR"
        return
    rows = [tuple(row) for row in body["rows"]]
    expected = [tuple(row) for row in preset.expected]
    if preset.ordered:
        assert rows == expected
    else:
        assert Counter(rows) == Counter(expected)
    assert body["result_complete"] is True
    assert body["total_rows"] == len(expected)


def test_the_key_equality_preset_really_opens_a_declared_index(client):
    body = query(client, "SELECT * FROM students WHERE id = 3;").json()

    scan = details_of(body["execution_plan"]["runtime"]["root"], "IndexScan")
    assert scan is not None
    assert scan["index_name"] in {"students_id_hash", "students_age_bplus"}
    assert body["metrics"]["engine"]["pages"]["index_read"] > 0


def test_the_range_preset_really_uses_the_age_bplus_index(client):
    body = query(client, "SELECT name FROM students WHERE age >= 22 AND age < 24;").json()

    scan = details_of(body["execution_plan"]["runtime"]["root"], "IndexScan")
    assert scan["index_name"] == "students_age_bplus"


def test_the_big_order_by_preset_spills_and_is_sorted(client):
    body = query(client, BIG["ORDER BY con disco"].sql, max_rows=500).json()

    expected = sorted(
        ((row[0], row[1], row[3]) for row in big_enrollments(BIG_ENROLLMENTS, BIG_STUDENTS)),
        key=lambda row: (-row[2], row[0]),
    )
    assert [tuple(row) for row in body["rows"]] == expected
    assert "ExternalSort" in names(body["execution_plan"]["runtime"]["root"])
    assert body["metrics"]["engine"]["temporary"]["bytes_spilled"] > 0


def test_the_big_join_group_preset_uses_grace_and_external_grouping(client):
    body = query(client, BIG["JOIN + GROUP BY con disco"].sql).json()

    careers = {row[0]: row[2] for row in big_students(BIG_STUDENTS)}
    groups = defaultdict(list)
    for _, student_id, _, grade in big_enrollments(BIG_ENROLLMENTS, BIG_STUDENTS):
        groups[careers[student_id]].append(grade)
    expected = [
        (career, len(grades), sum(grades) / len(grades))
        for career, grades in sorted(groups.items())
    ]
    rows = [tuple(row) for row in body["rows"]]
    assert [row[:2] for row in rows] == [row[:2] for row in expected]
    assert all(abs(got[2] - want[2]) < 1e-9 for got, want in zip(rows, expected))
    operators = names(body["execution_plan"]["runtime"]["root"])
    assert "GraceHashJoin" in operators and "ExternalHashGroup" in operators
    assert body["metrics"]["engine"]["temporary"]["bytes_spilled"] > 0


def test_the_big_range_preset_uses_its_bplus_index(client):
    body = query(client, BIG["Rango en tabla mayor"].sql).json()

    expected = sorted(
        (row[0], row[1], row[3]) for row in big_students(BIG_STUDENTS)
        if 30 <= row[3] <= 31
    )
    assert [tuple(row) for row in body["rows"]] == expected
    scan = details_of(body["execution_plan"]["runtime"]["root"], "IndexScan")
    assert scan["index_name"] == "students_big_age_bplus"
