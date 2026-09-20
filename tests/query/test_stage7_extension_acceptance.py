"""Tasks 7.39-7.40: exact CREATE/EXPLAIN extension acceptance."""

from __future__ import annotations

import pytest

from engine.database import Database
from engine.maintenance import MaintenanceError
from engine.query import ResultKind, ResultState, StatementKind
from engine.query.errors import SqlBindingError, SqlSyntaxError, SqlUnsupportedError


CREATE_ALUMNOS = """-- Crear la tabla
CREATE TABLE alumnos (
    id INT PRIMARY KEY,
    nombre VARCHAR(100),
    carrera_id INT,
    nota INT
);"""

SELECT_NAME = """-- 1
SELECT * FROM alumnos
WHERE nombre = 'Pérez, Juan';"""

SELECT_GRADE = """-- 2
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;"""

SELECT_MISSING = """-- 3
SELECT * FROM alumnos
WHERE id = 999;"""

EXPLAIN_GRADE = """-- 4
EXPLAIN
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;"""

ANALYZE_GRADE = """-- 5
EXPLAIN ANALYZE
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;"""

INSERTS = (
    "INSERT INTO alumnos VALUES (3, 'Pérez, Juan', 1, 17);",
    "INSERT INTO alumnos VALUES (1, 'Ana', 2, 14);",
    "INSERT INTO alumnos VALUES (2, 'Luis', 1, 10);",
)

ALUMNOS_COLUMNS = ("id", "nombre", "carrera_id", "nota")
EXPECTED_BY_NAME = ((3, "Pérez, Juan", 1, 17),)
EXPECTED_BY_GRADE = (
    (1, "Ana", 2, 14),
    (3, "Pérez, Juan", 1, 17),
)


def _rows(database: Database, sql: str, *, use_indexes: bool = True):
    result = database.engine.execute(sql, use_indexes=use_indexes)
    assert result.kind is ResultKind.ROWS
    assert result.statement_kind is StatementKind.SELECT
    columns = tuple(column.name for column in result.schema)
    with result:
        rows = tuple(record.values for record in result)
    assert result.state is ResultState.COMPLETE
    assert database.engine.active_result is None
    return columns, rows


def _assert_plain_explanation(database: Database):
    before = (
        database.storage_for("alumnos").record_count,
        database.index_for("__pk__alumnos").entry_count,
    )
    result = database.engine.execute(EXPLAIN_GRADE)

    assert result.kind is ResultKind.EXPLANATION
    assert result.statement_kind is StatementKind.EXPLAIN
    assert result.executed is False
    assert result.complete is True
    assert result.statistics is None
    assert result.output_rows is None
    assert result.execution_seconds is None
    assert tuple(node.name for node in result.plan.walk()) == (
        "Projection",
        "ExternalSort",
        "Filter",
        "TableScan",
    )
    assert (
        database.storage_for("alumnos").record_count,
        database.index_for("__pk__alumnos").entry_count,
    ) == before
    assert database.engine.active_result is None


def _assert_analyzed_explanation(database: Database, output_rows: int):
    result = database.engine.execute(ANALYZE_GRADE)

    assert result.kind is ResultKind.EXPLANATION
    assert result.statement_kind is StatementKind.EXPLAIN_ANALYZE
    assert result.executed is True
    assert result.complete is True
    assert result.state is ResultState.COMPLETE
    assert result.output_rows == output_rows
    assert result.statistics.rows_produced == output_rows
    assert result.statistics.live_temporary_bytes == 0
    assert tuple(node.name for node in result.statistics.operators) == (
        "Projection",
        "ExternalSort",
        "Filter",
        "TableScan",
    )
    assert database.engine.active_result is None


def _assert_empty_scenario(database: Database):
    for sql in (SELECT_NAME, SELECT_GRADE, SELECT_MISSING):
        columns, rows = _rows(database, sql)
        assert columns == ALUMNOS_COLUMNS
        assert rows == ()
    _assert_plain_explanation(database)
    _assert_analyzed_explanation(database, 0)


def _assert_populated_scenario(database: Database):
    assert _rows(database, SELECT_NAME) == (ALUMNOS_COLUMNS, EXPECTED_BY_NAME)
    assert _rows(database, SELECT_GRADE) == (ALUMNOS_COLUMNS, EXPECTED_BY_GRADE)
    assert _rows(database, SELECT_MISSING) == (ALUMNOS_COLUMNS, ())
    _assert_plain_explanation(database)
    _assert_analyzed_explanation(database, 2)


def test_exact_alumnos_scenario_runs_empty_populated_and_after_clean_reopen(tmp_path):
    old_storage = None
    with Database.create(tmp_path, name="universidad") as database:
        definition = database.engine.execute(CREATE_ALUMNOS)
        assert definition.kind is ResultKind.DEFINITION
        assert definition.statement_kind is StatementKind.CREATE
        assert definition.table_name == "alumnos"
        assert definition.primary_index_name == "__pk__alumnos"

        table = database.catalog.get_table("alumnos")
        assert tuple(column.name for column in table.schema) == ALUMNOS_COLUMNS
        assert table.primary_key == "id"
        assert table.varchar_length("nombre") == 100
        assert database.storage_for("alumnos").record_count == 0
        assert database.index_for("__pk__alumnos").entry_count == 0
        _assert_empty_scenario(database)

        for sql in INSERTS:
            inserted = database.engine.execute(sql)
            assert inserted.kind is ResultKind.COMMAND
            assert inserted.statement_kind is StatementKind.INSERT
            assert inserted.affected_rows == 1
        _assert_populated_scenario(database)

        before_rows = _rows(database, "SELECT * FROM alumnos ORDER BY id")[1]
        before_index_entries = database.index_for("__pk__alumnos").entry_count
        with pytest.raises(SqlBindingError, match="Duplicate table"):
            database.engine.execute(CREATE_ALUMNOS)
        assert _rows(database, "SELECT * FROM alumnos ORDER BY id")[1] == before_rows
        assert database.index_for("__pk__alumnos").entry_count == before_index_entries
        old_storage = database.storage_for("alumnos")

    assert old_storage.closed is True
    with Database.open(tmp_path) as reopened:
        assert reopened.storage_for("alumnos") is not old_storage
        assert tuple(
            column.name for column in reopened.catalog.get_table("alumnos").schema
        ) == ALUMNOS_COLUMNS
        assert reopened.catalog.get_table("alumnos").primary_key == "id"
        _assert_populated_scenario(reopened)

        indexed = _rows(reopened, SELECT_NAME, use_indexes=True)[1]
        scanned = _rows(reopened, SELECT_NAME, use_indexes=False)[1]
        assert indexed == scanned == EXPECTED_BY_NAME

        before_rows = _rows(reopened, "SELECT * FROM alumnos ORDER BY id")[1]
        before_index_entries = reopened.index_for("__pk__alumnos").entry_count
        with pytest.raises(MaintenanceError, match="before the first write"):
            reopened.engine.execute(
                "INSERT INTO alumnos VALUES (1, 'Duplicada', 9, 20)"
            )
        assert _rows(reopened, "SELECT * FROM alumnos ORDER BY id")[1] == before_rows
        assert reopened.index_for("__pk__alumnos").entry_count == before_index_entries


def test_constraint_boundaries_delete_reuse_and_restart_remain_consistent(tmp_path):
    exact = "á" * 100
    with Database.create(tmp_path) as database:
        database.engine.execute(CREATE_ALUMNOS)
        database.engine.execute(
            f"INSERT INTO alumnos VALUES (1, '{exact}', 1, 14)"
        )

        with pytest.raises(MaintenanceError, match="before the first write"):
            database.engine.execute(
                "INSERT INTO alumnos VALUES (2, '" + "á" * 101 + "', 1, 15)"
            )
        assert _rows(
            database,
            "SELECT * FROM alumnos WHERE id = 1",
            use_indexes=True,
        )[1] == _rows(
            database,
            "SELECT * FROM alumnos WHERE id = 1",
            use_indexes=False,
        )[1] == ((1, exact, 1, 14),)

        deleted = database.engine.execute("DELETE FROM alumnos WHERE id = 1")
        assert deleted.statement_kind is StatementKind.DELETE
        assert deleted.affected_rows == 1
        database.engine.execute(
            "INSERT INTO alumnos VALUES (1, 'Reutilizada', 2, 18)"
        )
        assert database.storage_for("alumnos").record_count == 1
        assert database.index_for("__pk__alumnos").entry_count == 1

    with Database.open(tmp_path) as reopened:
        assert _rows(reopened, "SELECT * FROM alumnos WHERE id = 1")[1] == (
            (1, "Reutilizada", 2, 18),
        )
        reopened.index_for("__pk__alumnos").validate_structure()


def test_complete_submission_boundary_rejects_batches_before_any_effect(tmp_path):
    with Database.create(tmp_path) as database:
        with pytest.raises(SqlSyntaxError, match="Only one SQL statement"):
            database.engine.execute(
                CREATE_ALUMNOS + "\nSELECT * FROM alumnos;"
            )
        assert database.table_names() == ()

        database.engine.execute(CREATE_ALUMNOS)
        database.engine.execute(
            "INSERT INTO alumnos VALUES (1, 'A; -- B', 1, 14); -- accepted"
        )
        before = _rows(database, "SELECT * FROM alumnos")[1]

        for sql in (
            "SELECT * FROM alumnos; SELECT * FROM alumnos",
            "INSERT INTO alumnos VALUES (2, 'X', 1, 15); SELECT * FROM alumnos",
        ):
            with pytest.raises(SqlSyntaxError, match="Only one SQL statement"):
                database.engine.execute(sql)
            assert _rows(database, "SELECT * FROM alumnos")[1] == before

        assert _rows(
            database,
            "SELECT * FROM alumnos WHERE nombre = 'A; -- B'; -- trailing",
        )[1] == ((1, "A; -- B", 1, 14),)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE INDEX ix ON alumnos (id)",
        "EXPLAIN INSERT INTO alumnos VALUES (2, 'X', 1, 15)",
        "EXPLAIN DELETE FROM alumnos WHERE id = 1",
        "EXPLAIN CREATE TABLE other (id INT)",
        "EXPLAIN EXPLAIN SELECT * FROM alumnos",
    ],
)
def test_unsupported_extension_forms_fail_without_mutating_the_database(
    tmp_path,
    sql,
):
    with Database.create(tmp_path) as database:
        database.engine.execute(CREATE_ALUMNOS)
        database.engine.execute("INSERT INTO alumnos VALUES (1, 'Ana', 2, 14)")
        before = _rows(database, "SELECT * FROM alumnos")[1]

        with pytest.raises(SqlUnsupportedError):
            database.engine.execute(sql)

        assert database.table_names() == ("alumnos",)
        assert _rows(database, "SELECT * FROM alumnos")[1] == before
        assert database.index_for("__pk__alumnos").entry_count == 1
