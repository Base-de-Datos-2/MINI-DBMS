"""Tasks 7.23-7.25: table-wide maintenance, stable targets, and repair."""

import pytest

from engine.catalog import (
    Catalog,
    Column,
    DataType,
    IndexMetadata,
    IndexType,
    Schema,
    TableMetadata,
)
from engine.errors import UnsupportedAccessError, ValidationError
from engine.indexes import BPlusTree, UnclusteredBPlusIndex
from engine.indexes.index_catalog import build_catalog_index, open_catalog_index
from engine.maintenance import DeleteTargetSpool, MaintenanceError, MutationService
from engine.operators.context import MINIMUM_BUDGET_BYTES
from engine.query import QueryEnvironment, ResultKind, SqlEngine, run_sql
from engine.storage import HeapFile, PagedSequentialFile, Record


ROWS = Schema(
    [
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
        Column("age", DataType.INTEGER),
    ]
)


def _heap_environment(tmp_path, *, include_hash=True, include_bplus=True):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", ROWS))
    if include_hash:
        catalog.register_index(
            IndexMetadata(
                "ux_students_id",
                "students",
                "id",
                IndexType.EXTENDIBLE_HASH,
                unique=True,
                file_path=str(tmp_path / "students_id.hash"),
            )
        )
    if include_bplus:
        catalog.register_index(
            IndexMetadata(
                "ix_students_age",
                "students",
                "age",
                IndexType.BPLUS,
                file_path=str(tmp_path / "students_age.bplus"),
            )
        )
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "students.heap", ROWS)
    environment.register_storage("students", storage)
    indexes = []
    for metadata in catalog.get_indexes("students"):
        index = build_catalog_index(catalog, metadata.name, storage)
        environment.register_index(metadata.name, index)
        indexes.append(index)
    return environment, storage, tuple(indexes)


def _close(storage, indexes):
    for index in reversed(indexes):
        index.close()
    storage.close()


def test_command_result_is_synchronous_and_updates_every_heap_index(tmp_path):
    environment, storage, indexes = _heap_environment(tmp_path)
    try:
        result = run_sql(
            environment,
            "INSERT INTO students VALUES (1, 'Ana', 22)",
        )
        assert result.kind is ResultKind.COMMAND
        assert result.affected_rows == result.report.affected_rows == 1
        assert result.statistics.indexes_maintained == (
            "ux_students_id",
            "ix_students_age",
        )
        assert result.statistics.index_association_updates == 2
        with pytest.raises(UnsupportedAccessError, match="do not contain rows"):
            _ = result.rows

        rid = next(environment.index_for("ux_students_id").search(1))
        assert storage.read(rid).values == (1, "Ana", 22)
        assert list(environment.index_for("ix_students_age").search(22)) == [rid]

        # Reading command metadata is observational and cannot execute again.
        assert result.affected_rows == 1
        assert result.report.runtime is result.statistics
        assert storage.record_count == 1

        run_sql(environment, "INSERT INTO students VALUES (2, 'Bea', 22)")
        assert len(list(environment.index_for("ix_students_age").search(22))) == 2
    finally:
        _close(storage, indexes)


def test_insert_without_indexes_survives_reopen(tmp_path):
    environment, storage, indexes = _heap_environment(
        tmp_path, include_hash=False, include_bplus=False
    )
    try:
        result = run_sql(environment, "INSERT INTO students VALUES (7, 'Noa', 30)")
        assert result.affected_rows == 1
        assert result.statistics.indexes_maintained == ()
    finally:
        _close(storage, indexes)

    reopened = HeapFile.open(tmp_path / "students.heap", ROWS)
    try:
        assert [record.values for _, record in reopened.scan()] == [(7, "Noa", 30)]
    finally:
        reopened.close()


def test_prepared_insert_rechecks_unique_constraints_immediately_before_write(tmp_path):
    environment, storage, indexes = _heap_environment(
        tmp_path, include_bplus=False
    )
    try:
        engine = SqlEngine(environment)
        prepared = engine.prepare("INSERT INTO students VALUES (4, 'First', 20)")
        run_sql(environment, "INSERT INTO students VALUES (4, 'Winner', 21)")

        with pytest.raises(ValidationError, match="already contains key"):
            prepared.execute()

        assert [record["name"] for _, record in storage.scan()] == ["Winner"]
        assert len(list(environment.index_for("ux_students_id").search(4))) == 1
    finally:
        _close(storage, indexes)


def test_insert_failure_between_index_updates_repairs_every_index(
    tmp_path, monkeypatch
):
    environment, storage, indexes = _heap_environment(tmp_path)
    original_insert = BPlusTree.insert
    failed = False

    def fail_once(tree, key, rid):
        nonlocal failed
        if tree.header.index_name == "ix_students_age" and not failed:
            failed = True
            raise OSError("injected second-index failure")
        return original_insert(tree, key, rid)

    monkeypatch.setattr(BPlusTree, "insert", fail_once)
    try:
        with pytest.raises(MaintenanceError) as raised:
            run_sql(environment, "INSERT INTO students VALUES (8, 'Bad', 27)")

        assert isinstance(raised.value.__cause__, OSError)
        assert raised.value.completed_rows == 0
        assert raised.value.unavailable_indexes == ()
        assert list(storage.scan()) == []
        for metadata in environment.catalog.get_indexes("students"):
            environment.index_for(metadata.name).validate_structure()
    finally:
        _close(storage, indexes)


def test_delete_reports_confirmed_prefix_and_repairs_failed_target(
    tmp_path, monkeypatch
):
    environment, storage, indexes = _heap_environment(tmp_path)
    for row in ((1, "A", 20), (2, "B", 21), (3, "C", 22)):
        run_sql(
            environment,
            f"INSERT INTO students VALUES ({row[0]}, '{row[1]}', {row[2]})",
        )

    original_delete = HeapFile.delete
    calls = 0

    def fail_second(heap, rid):
        nonlocal calls
        if heap is storage:
            calls += 1
            if calls == 2:
                raise OSError("injected second-row storage failure")
        return original_delete(heap, rid)

    monkeypatch.setattr(HeapFile, "delete", fail_second)
    try:
        with pytest.raises(MaintenanceError) as raised:
            run_sql(environment, "DELETE FROM students")

        assert raised.value.completed_rows == 1
        assert raised.value.unavailable_indexes == ()
        remaining = [(rid, record) for rid, record in storage.scan()]
        assert [record["id"] for _, record in remaining] == [2, 3]
        for rid, record in remaining:
            assert rid in environment.index_for("ux_students_id").search(record["id"])
            assert rid in environment.index_for("ix_students_age").search(record["age"])
        for index in indexes:
            index.validate_structure()
    finally:
        _close(storage, indexes)


def test_delete_spools_more_than_its_memory_grant_without_collecting_targets(tmp_path):
    environment, storage, indexes = _heap_environment(
        tmp_path, include_hash=False, include_bplus=False
    )
    try:
        for value in range(120):
            storage.insert(Record(ROWS, [value, "x" * 80, value]))

        result = run_sql(
            environment,
            "DELETE FROM students",
            memory_budget_bytes=MINIMUM_BUDGET_BYTES,
            max_open_handles=1,
        )

        assert result.affected_rows == 120
        assert result.statistics.targets_spooled == 120
        assert result.statistics.spool_bytes > MINIMUM_BUDGET_BYTES
        assert result.statistics.discovery is not None
        assert list(storage.scan()) == []
    finally:
        _close(storage, indexes)


def test_delete_spool_never_deletes_a_replacement_in_a_reused_slot(tmp_path):
    storage = HeapFile.create(tmp_path / "students.heap", ROWS)
    try:
        original = Record(ROWS, [1, "Original", 20])
        rid = storage.insert(original)
        with DeleteTargetSpool() as spool:
            spool.append(rid, original)
            spool.seal()

            storage.delete(rid)
            replacement = Record(ROWS, [2, "Replacement", 21])
            assert storage.insert(replacement) == rid

            with pytest.raises(MaintenanceError, match="ordinary row-maintenance") as raised:
                MutationService().delete(
                    table_name="students",
                    storage=storage,
                    indexes=(),
                    targets=spool.targets(ROWS),
                    target_count=spool.count,
                    spool_bytes=spool.size,
                )

        assert raised.value.completed_rows == 0
        assert storage.read(rid) == replacement
    finally:
        storage.close()


def test_sequential_insert_rebuilds_moved_rids_and_delete_keeps_targets_stable(
    tmp_path,
):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", ROWS))
    metadata = IndexMetadata(
        "cx_students_id",
        "students",
        "id",
        IndexType.BPLUS,
        clustered=True,
        file_path=str(tmp_path / "students_id.bplus"),
    )
    catalog.register_index(metadata)
    environment = QueryEnvironment(catalog)
    path = tmp_path / "students.seq"
    storage = PagedSequentialFile.create(path, ROWS, "id")
    environment.register_storage("students", storage)
    index = build_catalog_index(catalog, metadata.name, storage)
    environment.register_index(metadata.name, index)
    try:
        for row in ((30, "C", 30), (10, "A", 10), (20, "B", 20)):
            result = run_sql(
                environment,
                f"INSERT INTO students VALUES ({row[0]}, '{row[1]}', {row[2]})",
            )
            assert result.statistics.indexes_rebuilt == (metadata.name,)

        assert [record["id"] for _, record in storage.scan()] == [10, 20, 30]
        for key in (10, 20, 30):
            rid = next(index.search(key))
            assert storage.read(rid)["id"] == key

        deleted = run_sql(environment, "DELETE FROM students WHERE id >= 20")
        assert deleted.affected_rows == 2
        assert deleted.statistics.targets_spooled == 2
        assert [record["id"] for _, record in storage.scan()] == [10]
        index.validate_structure()

        index.close()
        storage.close()
        reopened_storage = PagedSequentialFile.open(path, ROWS, "id")
        reopened_index = open_catalog_index(catalog, metadata.name, reopened_storage)
        try:
            assert [record["id"] for _, record in reopened_storage.scan()] == [10]
            reopened_index.validate_structure()
        finally:
            reopened_index.close()
            reopened_storage.close()
    finally:
        if not index.closed:
            index.close()
        if not storage.closed:
            storage.close()


def test_failed_repair_persists_incomplete_index_marker(tmp_path, monkeypatch):
    environment, storage, indexes = _heap_environment(
        tmp_path, include_hash=False, include_bplus=True
    )
    index = indexes[0]
    original_insert = BPlusTree.insert

    def always_fail_target(tree, key, rid):
        if tree.header.index_name == "ix_students_age":
            raise OSError("injected persistent B+ failure")
        return original_insert(tree, key, rid)

    def fail_rebuild(adapter):
        raise OSError("injected persistent rebuild failure")

    monkeypatch.setattr(BPlusTree, "insert", always_fail_target)
    monkeypatch.setattr(UnclusteredBPlusIndex, "rebuild", fail_rebuild)
    try:
        with pytest.raises(MaintenanceError) as raised:
            run_sql(environment, "INSERT INTO students VALUES (9, 'X', 99)")

        assert raised.value.completed_rows == 0
        assert raised.value.unavailable_indexes == ("ix_students_age",)
        assert list(storage.scan()) == []
        with pytest.raises(ValidationError, match="not completely built"):
            environment.index_for("ix_students_age")

        index.close()
        storage.close()
        reopened_storage = HeapFile.open(tmp_path / "students.heap", ROWS)
        try:
            with pytest.raises(ValidationError, match="incomplete"):
                open_catalog_index(
                    environment.catalog,
                    "ix_students_age",
                    reopened_storage,
                )
        finally:
            reopened_storage.close()
    finally:
        if not index.closed:
            index.close()
        if not storage.closed:
            storage.close()


def test_sequential_rebuild_failure_compensates_row_and_repairs_index(
    tmp_path, monkeypatch
):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", ROWS))
    metadata = IndexMetadata(
        "cx_students_id",
        "students",
        "id",
        IndexType.BPLUS,
        clustered=True,
        file_path=str(tmp_path / "students_id.bplus"),
    )
    catalog.register_index(metadata)
    environment = QueryEnvironment(catalog)
    storage = PagedSequentialFile.create(
        tmp_path / "students.seq", ROWS, "id"
    )
    environment.register_storage("students", storage)
    index = build_catalog_index(catalog, metadata.name, storage)
    environment.register_index(metadata.name, index)
    original_rebuild = type(index).rebuild
    calls = 0

    def fail_first_rebuild(adapter):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected RID-remap rebuild failure")
        return original_rebuild(adapter)

    monkeypatch.setattr(type(index), "rebuild", fail_first_rebuild)
    try:
        with pytest.raises(MaintenanceError) as raised:
            run_sql(environment, "INSERT INTO students VALUES (5, 'X', 30)")

        assert raised.value.completed_rows == 0
        assert raised.value.unavailable_indexes == ()
        assert list(storage.scan()) == []
        environment.index_for(metadata.name).validate_structure()
    finally:
        index.close()
        storage.close()
