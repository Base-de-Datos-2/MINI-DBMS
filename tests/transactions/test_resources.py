"""Stage 8 Task 8.6: metadata-only complete lock-resource mapping."""

import pytest

from api.database import Database as LegacyDatabase
from engine.database import Database
from engine.query import parse_sql
from engine.transactions import (
    LockMode,
    ResourceCatalog,
    SchemaMode,
    StaleAccessPlanError,
    TableFiles,
)
from engine.errors import ValidationError
from tests.api_helpers import small_demo


def _plan(database, sql):
    return database.session_coordinator.resources.plan(parse_sql(sql))


def test_managed_aliases_joins_ranges_and_missing_keys_use_stable_base_resources(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE left_rows (id INT PRIMARY KEY, value INT)")
        database.engine.execute("CREATE TABLE right_rows (id INT PRIMARY KEY)")
        resources = database.session_coordinator.resources

        self_join = _plan(
            database,
            "SELECT a.id FROM left_rows AS a JOIN left_rows AS b ON a.id = b.id",
        )
        assert self_join.schema is SchemaMode.S
        assert len(self_join.tables) == 1
        assert self_join.tables[0].mode is LockMode.S
        assert self_join.tables[0].files == (
            database.path_for("left_rows"),
            database.path_for("__pk__left_rows"),
        )

        join = _plan(
            database,
            "SELECT a.id FROM left_rows AS a JOIN right_rows AS b ON a.id = b.id",
        )
        assert {item.table_name for item in join.tables} == {"left_rows", "right_rows"}
        assert [item.resource for item in join.tables] == sorted(
            item.resource for item in join.tables
        )
        assert all(item.resource.database_identity == database.identity for item in join.tables)
        assert all(item.mode is LockMode.S for item in join.tables)

        for sql in (
            "SELECT id FROM left_rows WHERE id = 999",
            "SELECT id FROM left_rows WHERE id >= 4",
        ):
            assert _plan(database, sql).tables[0].resource == self_join.tables[0].resource
        resources.validate(join)


def test_mutations_explanations_ddl_and_controls_have_exact_intents(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        for sql in (
            "INSERT INTO t VALUES (7)",
            "DELETE FROM t WHERE id = 7",
        ):
            access = _plan(database, sql)
            assert access.schema is SchemaMode.S
            assert len(access.tables) == 1
            assert access.tables[0].mode is LockMode.X
            assert access.tables[0].files == (
                database.path_for("t"), database.path_for("__pk__t")
            )

        explain = _plan(database, "EXPLAIN SELECT id FROM t WHERE id = 999")
        assert explain.schema is SchemaMode.S and explain.tables == ()
        analyze = _plan(database, "EXPLAIN ANALYZE SELECT id FROM t")
        assert analyze.schema is SchemaMode.S
        assert len(analyze.tables) == 1 and analyze.tables[0].mode is LockMode.S
        create = _plan(database, "CREATE TABLE u (id INT)")
        assert create.schema is SchemaMode.X and create.tables == ()
        for sql in ("BEGIN TRANSACTION", "END TRANSACTION", "ROLLBACK"):
            control = _plan(database, sql)
            assert control.schema is SchemaMode.NONE and control.tables == ()


def test_generation_change_invalidates_prepared_access_plan(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        resources = database.session_coordinator.resources
        prepared_access = _plan(database, "SELECT id FROM t")
        resources.validate(prepared_access)
        assert resources.bump_generation("t") == 1
        with pytest.raises(StaleAccessPlanError, match="changed"):
            resources.validate(prepared_access)
        refreshed = _plan(database, "SELECT id FROM t")
        assert refreshed.tables[0].generation == 1
        resources.validate(refreshed)

        planned_create = _plan(database, "CREATE TABLE u (id INT)")
        database.engine.execute("CREATE TABLE v (id INT)")
        with pytest.raises(StaleAccessPlanError, match="Schema changed"):
            resources.validate(planned_create)


def test_legacy_mapping_includes_sequential_bplus_and_hash_files(tmp_path):
    with LegacyDatabase.create(small_demo(), tmp_path) as database:
        resources = database.session_coordinator.resources
        for table in database.table_names():
            access = _plan(database, f"SELECT * FROM {table}")
            assert len(access.tables) == 1
            intent = access.tables[0]
            assert intent.resource.table_identity == table
            assert intent.files[0] == database._paths[table].resolve()
            expected = {database._paths[item.name].resolve()
                        for item in database.catalog.get_indexes(table)}
            assert set(intent.files[1:]) == expected


def test_resource_registration_requires_every_declared_index_and_correct_path(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        with pytest.raises(ValidationError, match="every declared index"):
            ResourceCatalog(
                database.identity,
                database.catalog,
                (TableFiles("t", "stable", database.path_for("t")),),
            )
        with pytest.raises(ValidationError, match="Catalog path"):
            ResourceCatalog(
                database.identity,
                database.catalog,
                (TableFiles(
                    "t", "stable", database.path_for("t"),
                    (("__pk__t", tmp_path / "wrong.bpt"),),
                ),),
            )
