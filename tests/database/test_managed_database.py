"""Stage 7 Tasks 7.34–7.35 managed CREATE and constraint integration."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from engine.catalog import DataType
from engine.database import Database, MANIFEST_FILENAME
from engine.errors import DuplicateError
from engine.maintenance import MaintenanceError
from engine.query import DefinitionResult, ResultKind, StatementKind
from engine.query.errors import SqlBindingError
from engine.query.environment import QueryEnvironment
from engine.storage import HeapFile


CREATE_ALUMNOS = """-- Crear la tabla
CREATE TABLE alumnos (
    id INT PRIMARY KEY,
    nombre VARCHAR(100),
    carrera_id INT,
    nota INT
);"""


def _rows(database, sql):
    with database.engine.execute(sql) as result:
        return [record.values for record in result]


def _managed_files(root: Path) -> set[str]:
    return {path.name for path in root.iterdir()}


def test_create_is_preparable_side_effect_free_and_durably_queryable(tmp_path):
    with Database.create(tmp_path, name="universidad") as database:
        prepared = database.engine.prepare(CREATE_ALUMNOS)

        assert prepared.kind is StatementKind.CREATE
        assert prepared.reusable is False
        assert _managed_files(tmp_path) == {MANIFEST_FILENAME}

        result = prepared.execute()
        assert isinstance(result, DefinitionResult)
        assert result.kind is ResultKind.DEFINITION
        assert result.statement_kind is StatementKind.CREATE
        assert result.table_name == "alumnos"
        assert result.primary_index_name == "__pk__alumnos"
        assert not hasattr(result, "affected_rows")
        assert _rows(database, "SELECT * FROM alumnos") == []

        metadata = database.catalog.get_table("alumnos")
        assert metadata.primary_key == "id"
        assert metadata.varchar_length("nombre") == 100
        table_path = database.path_for("alumnos")
        index_path = database.path_for("__pk__alumnos")
        assert table_path.name.startswith("t_") and table_path.suffix == ".heap"
        assert index_path.name.startswith("i_") and index_path.suffix == ".bpt"
        assert "alumnos" not in table_path.name

        database.engine.execute(
            "INSERT INTO alumnos VALUES (1, 'Pérez, Juan', 3, 17)"
        )

    with Database.open(tmp_path) as reopened:
        assert reopened.name == "universidad"
        assert reopened.table_names() == ("alumnos",)
        assert _rows(reopened, "SELECT * FROM alumnos WHERE id = 1") == [
            (1, "Pérez, Juan", 3, 17)
        ]
        assert reopened.index_for("__pk__alumnos").entry_count == 1


def test_primary_key_length_uniqueness_delete_and_reinsert_survive_reopen(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute(CREATE_ALUMNOS)
        database.engine.execute("INSERT INTO alumnos VALUES (1, 'Ana', 2, 14)")

        with pytest.raises(MaintenanceError):
            database.engine.execute(
                "INSERT INTO alumnos VALUES (1, 'Duplicada', 9, 20)"
            )
        assert _rows(database, "SELECT * FROM alumnos") == [(1, "Ana", 2, 14)]

        with pytest.raises(MaintenanceError, match="before the first write"):
            database.engine.execute(
                "INSERT INTO alumnos VALUES (2, '" + "é" * 101 + "', 2, 15)"
            )
        assert _rows(database, "SELECT * FROM alumnos WHERE id = 2") == []

        database.engine.execute("DELETE FROM alumnos WHERE id = 1")
        database.engine.execute("INSERT INTO alumnos VALUES (1, 'Nueva', 4, 18)")

    with Database.open(tmp_path) as reopened:
        assert _rows(reopened, "SELECT * FROM alumnos") == [(1, "Nueva", 4, 18)]
        with pytest.raises(MaintenanceError):
            reopened.engine.execute(
                "INSERT INTO alumnos VALUES (1, 'Otra', 1, 11)"
            )


def test_programmatic_insert_uses_the_same_constraints_and_maintenance(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute(CREATE_ALUMNOS)
        report = database.insert("alumnos", [7, "á" * 100, 1, 20])
        assert report.affected_rows == 1
        assert report.indexes_maintained == ("__pk__alumnos",)

        with pytest.raises(ValueError, match=r"VARCHAR\(100\)"):
            database.insert("alumnos", [8, "á" * 101, 1, 20])
        with pytest.raises(DuplicateError):
            database.insert("alumnos", [7, "duplicate", 1, 20])
        assert database.storage_for("alumnos").record_count == 1


def test_repeated_create_preserves_existing_rows_files_and_manifest(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute(CREATE_ALUMNOS)
        database.engine.execute("INSERT INTO alumnos VALUES (1, 'Ana', 2, 14)")
        before_files = _managed_files(tmp_path)
        before_manifest = database.manifest_path.read_bytes()

        with pytest.raises(ValueError, match="Duplicate table"):
            database.engine.execute(CREATE_ALUMNOS)

        assert _managed_files(tmp_path) == before_files
        assert database.manifest_path.read_bytes() == before_manifest
        assert _rows(database, "SELECT * FROM alumnos") == [(1, "Ana", 2, 14)]


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("CREATE TABLE bad (id INT, id VARCHAR(10))", "Duplicate column"),
        (
            "CREATE TABLE bad (left_id INT PRIMARY KEY, right_id INT PRIMARY KEY)",
            "at most one primary key",
        ),
        (
            "CREATE TABLE bad (value VARCHAR(4076))",
            "VARCHAR length must be between 1 and 4075",
        ),
    ],
)
def test_semantically_invalid_create_is_rejected_before_file_allocation(
    tmp_path,
    sql,
    message,
):
    with Database.create(tmp_path) as database:
        before = database.manifest_path.read_bytes()

        with pytest.raises(SqlBindingError, match=message):
            database.engine.prepare(sql)

        assert _managed_files(tmp_path) == {MANIFEST_FILENAME}
        assert database.manifest_path.read_bytes() == before
        assert database.table_names() == ()


def test_integer_alias_binds_to_the_same_persisted_physical_type(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE aliases (id INTEGER, score INT)")
        metadata = database.catalog.get_table("aliases")
        assert tuple(column.data_type for column in metadata.schema) == (
            DataType.INTEGER,
            DataType.INTEGER,
        )

    with Database.open(tmp_path) as reopened:
        metadata = reopened.catalog.get_table("aliases")
        assert tuple(column.data_type for column in metadata.schema) == (
            DataType.INTEGER,
            DataType.INTEGER,
        )


def test_primary_varchar_key_limit_is_checked_before_the_base_write(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute(
            "CREATE TABLE codes (code VARCHAR(200) PRIMARY KEY)"
        )
        with pytest.raises(MaintenanceError, match="before the first write"):
            database.engine.execute(
                "INSERT INTO codes VALUES ('" + "é" * 128 + "')"
            )
        assert database.storage_for("codes").record_count == 0
        assert database.index_for("__pk__codes").entry_count == 0


def test_manifest_reopens_in_a_fresh_python_process_without_definitions(tmp_path):
    with Database.create(tmp_path, name="fresh") as database:
        database.engine.execute(CREATE_ALUMNOS)
        database.engine.execute("INSERT INTO alumnos VALUES (9, 'Sol', 1, 19)")

    script = """
from engine.database import Database
import sys
with Database.open(sys.argv[1]) as database:
    with database.engine.execute('SELECT nombre, nota FROM alumnos WHERE id = 9') as result:
        assert [row.values for row in result] == [('Sol', 19)]
    assert database.catalog.get_table('alumnos').primary_key == 'id'
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("failure_point", ["heap", "index", "registry", "manifest"])
def test_create_failures_remove_only_new_files_and_allow_a_later_create(
    tmp_path,
    monkeypatch,
    failure_point,
):
    import engine.database.owner as owner_module

    with Database.create(tmp_path) as database:
        before = database.manifest_path.read_bytes()
        with monkeypatch.context() as patch:
            if failure_point == "heap":
                patch.setattr(
                    HeapFile,
                    "create",
                    classmethod(lambda cls, path, schema: (_ for _ in ()).throw(OSError("heap"))),
                )
            elif failure_point == "index":
                patch.setattr(
                    owner_module,
                    "build_catalog_index",
                    lambda *args, **kwargs: (_ for _ in ()).throw(OSError("index")),
                )
            elif failure_point == "registry":
                original = QueryEnvironment.register_index

                def fail_registration(self, name, index):
                    if self is database.environment:
                        raise OSError("registry")
                    return original(self, name, index)

                patch.setattr(QueryEnvironment, "register_index", fail_registration)
            else:
                patch.setattr(
                    owner_module,
                    "write_manifest_atomic",
                    lambda *args, **kwargs: (_ for _ in ()).throw(OSError("manifest")),
                )

            with pytest.raises(OSError):
                database.engine.execute(
                    "CREATE TABLE failed (id INT PRIMARY KEY, value VARCHAR(10))"
                )

        assert database.manifest_path.read_bytes() == before
        assert database.catalog.has_table("failed") is False
        assert _managed_files(tmp_path) == {MANIFEST_FILENAME}

        result = database.engine.execute("CREATE TABLE recovered (id INT)")
        assert result.table_name == "recovered"


def test_manifest_contains_only_the_documented_version_one_shape(tmp_path):
    with Database.create(tmp_path, name="shape") as database:
        database.engine.execute(CREATE_ALUMNOS)
    document = json.loads((tmp_path / MANIFEST_FILENAME).read_text("utf-8"))

    assert set(document) == {"database", "magic", "tables", "version"}
    assert document["magic"] == "MINIDB_CATALOG"
    assert document["version"] == 1
    assert set(document["database"]) == {"id", "name"}
    assert document["tables"][0]["organization"] == "HEAP"
    assert document["tables"][0]["primary_key"] == "id"
    assert document["tables"][0]["indexes"][0]["ready"] is True
