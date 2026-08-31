"""Exercise the Storage contract with a model-only test double, never pages."""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidReferenceError, InvalidTypeError, SchemaError
from engine.storage import RID, Record, Storage
from tests.doubles import StorageDouble


@pytest.fixture
def storage():
    return StorageDouble(Schema([
        Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR),
    ]))


def test_storage_empty_insert_duplicate_rows_read_and_delete(storage):
    assert isinstance(storage, Storage)
    assert list(storage.scan()) == []
    record = Record(storage.schema, [1, "Ana"])
    first, second = storage.insert(record), storage.insert(record)
    assert isinstance(first, RID) and isinstance(second, RID)
    assert first != second
    assert storage.read(first) is record
    assert dict(storage.scan()) == {first: record, second: record}
    assert storage.delete(first) is None
    for operation in (storage.read, storage.delete):
        with pytest.raises(InvalidReferenceError):
            operation(first)
    assert dict(storage.scan()) == {second: record}
    assert storage.read(second) is record


def test_storage_accepts_equal_schema_but_rejects_changed_order_names_and_types(storage):
    equivalent = Schema(list(storage.schema))
    record = Record(equivalent, [1, "Ana"])
    rid = storage.insert(record)
    invalid_records = [
        Record(Schema(list(reversed(storage.schema.columns))), ["Ana", 1]),
        Record(Schema([Column("other", DataType.INTEGER)]), [1]),
        Record(Schema([Column("id", DataType.FLOAT), Column("name", DataType.VARCHAR)]), [1.0, "Ana"]),
    ]
    for invalid in invalid_records:
        with pytest.raises(SchemaError):
            storage.insert(invalid)
        assert dict(storage.scan()) == {rid: record}
    with pytest.raises(InvalidTypeError):
        storage.insert([1, "Ana"])
    assert dict(storage.scan()) == {rid: record}


@pytest.mark.parametrize("operation", ["read", "delete"])
def test_storage_distinguishes_wrong_rid_type_from_missing_location(storage, operation):
    with pytest.raises(InvalidTypeError):
        getattr(storage, operation)((0, 0))
    with pytest.raises(InvalidReferenceError):
        getattr(storage, operation)(RID(999, 999))
    assert list(storage.scan()) == []


def test_storage_scans_are_lazy_independent_and_close_before_start_is_safe(storage):
    records = [Record(storage.schema, [number, "row"]) for number in range(3)]
    expected = {storage.insert(record): record for record in records}
    unused = storage.scan()
    unused.close()
    assert storage.scans.opened == 0
    with closing(storage.scan()) as first, closing(storage.scan()) as second:
        a, b = next(first), next(second)
        assert storage.scans.active == 2
        assert storage.scans.yielded == 2  # Neither scan has consumed the whole input.
        assert dict([a, *first]) == expected
        assert storage.scans.active == 1
        assert dict([b, *second]) == expected
    assert storage.scans.active == 0
    assert storage.scans.opened == storage.scans.closed == 2


@pytest.mark.parametrize("exit_mode", ["exhausted", "early", "consumer_error", "source_error"])
def test_storage_scan_releases_resources_on_every_exit(storage, exit_mode):
    record = Record(storage.schema, [1, "Ana"])
    rid = storage.insert(record)
    storage.insert(record)
    marker = RuntimeError("scan failure")
    if exit_mode == "source_error":
        storage.scans.fail_after, storage.scans.error = 1, marker

    def consume():
        with closing(storage.scan()) as rows:
            assert next(rows)[1] == record
            if exit_mode == "consumer_error":
                raise marker
            if exit_mode != "early":
                list(rows)

    if exit_mode.endswith("error"):
        with pytest.raises(RuntimeError) as caught:
            consume()
        assert caught.value is marker
    else:
        consume()
    assert storage.scans.active == 0
    assert storage.scans.opened == storage.scans.closed == 1
    assert storage.read(rid) == record  # A scan does not close its borrowed manager.
