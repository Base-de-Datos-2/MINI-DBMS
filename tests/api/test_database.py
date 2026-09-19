"""Stage 9 Task 9.3: persistent, repeatable demonstration data."""

import pytest

from engine.catalog import Column, DataType, IndexType, Schema
from engine.errors import DuplicateError, ValidationError
from engine.storage import HeapFile
from api.database import (
    HEAP,
    SEQUENTIAL,
    Database,
    DatabaseDefinition,
    DatabaseSetupError,
    IndexDefinition,
    TableDefinition,
)
from api.demo import ENROLLMENT_ROWS, STUDENT_ROWS

from tests.api_helpers import BIG_ENROLLMENTS, BIG_STUDENTS, small_demo


ITEMS = Schema([Column("id", DataType.INTEGER), Column("label", DataType.VARCHAR)])


def test_create_seeds_every_declared_table_and_index(tmp_path):
    with Database.create(small_demo(), tmp_path) as database:
        counts = {name: database.describe_table(name).row_count
                  for name in database.table_names()}

    assert counts == {
        "students": len(STUDENT_ROWS),
        "enrollments": len(ENROLLMENT_ROWS),
        "students_big": BIG_STUDENTS,
        "courses": 16,
        "enrollments_big": BIG_ENROLLMENTS,
    }
    files = sorted(path.name for path in tmp_path.iterdir())
    assert "students_id_hash.hsh" in files
    assert "courses_code_bplus.bpt" in files


def test_open_reads_the_same_rows_with_fresh_engine_objects(tmp_path):
    Database.create(small_demo(), tmp_path).close()

    for _ in range(2):
        with Database.open(small_demo(), tmp_path) as database:
            with database.engine.execute(
                "SELECT id, name FROM students WHERE id = 3"
            ) as result:
                assert [row.values for row in result] == [(3, "Sol")]
            assert database.describe_table("students").row_count == 4


def test_open_refuses_a_missing_or_partial_directory(tmp_path):
    with pytest.raises(DatabaseSetupError, match="not a prepared database"):
        Database.open(small_demo(), tmp_path / "missing")

    Database.create(small_demo(), tmp_path).close()
    (tmp_path / "courses_code_bplus.bpt").unlink()

    with pytest.raises(DatabaseSetupError, match="courses_code_bplus.bpt"):
        Database.open(small_demo(), tmp_path)


def test_create_refuses_to_overwrite_existing_files(tmp_path):
    Database.create(small_demo(), tmp_path).close()

    with pytest.raises(DatabaseSetupError, match="already holds database files"):
        Database.create(small_demo(), tmp_path)


def test_a_table_summary_describes_structure_and_indexes(tmp_path):
    with Database.create(small_demo(), tmp_path) as database:
        students = database.describe_table("students")
        courses = database.describe_table("courses")

    assert students.organization == HEAP
    assert students.columns == (
        ("id", "INTEGER"), ("name", "VARCHAR"), ("career", "VARCHAR"),
        ("age", "INTEGER"),
    )
    by_name = {index.name: index for index in students.indexes}
    assert by_name["students_id_hash"].supports_range is False
    assert by_name["students_age_bplus"].supports_range is True
    assert courses.organization == SEQUENTIAL
    assert courses.key_column == "code"
    (clustered,) = courses.indexes
    assert clustered.clustered is True and clustered.unique is True


def test_closing_is_idempotent_and_releases_every_file(tmp_path):
    database = Database.create(small_demo(), tmp_path)

    database.close()
    database.close()

    assert database.closed is True
    with Database.open(small_demo(), tmp_path) as reopened:
        assert reopened.describe_table("enrollments").row_count == 4


def test_a_failed_create_closes_what_it_already_opened(tmp_path, monkeypatch):
    closed = []
    original = HeapFile.close

    def tracking_close(self):
        closed.append(self)
        return original(self)

    monkeypatch.setattr(HeapFile, "close", tracking_close)
    definition = DatabaseDefinition(
        name="broken",
        tables=(
            TableDefinition(
                "items", ITEMS,
                indexes=(
                    IndexDefinition("same_name", "id", IndexType.BPLUS),
                    IndexDefinition("same_name", "label", IndexType.BPLUS),
                ),
                rows=lambda: [(1, "a")],
            ),
        ),
    )

    with pytest.raises(DuplicateError):
        Database.create(definition, tmp_path)

    assert len(closed) == 1


def test_definitions_reject_impossible_organizations():
    with pytest.raises(ValidationError, match="needs a key column"):
        TableDefinition("items", ITEMS, organization=SEQUENTIAL)
    with pytest.raises(ValidationError, match="HEAP or SEQUENTIAL"):
        TableDefinition("items", ITEMS, organization="HASHED")
    with pytest.raises(ValidationError, match="Clustered index"):
        TableDefinition(
            "items", ITEMS,
            indexes=(IndexDefinition("ix", "id", IndexType.BPLUS, clustered=True),),
        )


def test_a_database_is_only_built_through_its_factories(tmp_path):
    with pytest.raises(TypeError, match="Database.open"):
        Database()
    with pytest.raises(TypeError, match="DatabaseDefinition"):
        Database.create("demo", tmp_path)
    with pytest.raises(TypeError, match="DatabaseDefinition"):
        Database.open("demo", tmp_path)
