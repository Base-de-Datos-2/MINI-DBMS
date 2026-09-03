import json

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, SchemaError, ValidationError
from engine.storage import OrganizationMetadata, OrganizationType


@pytest.fixture
def schema():
    return Schema(
        [
            Column("id", DataType.INTEGER),
            Column("descripción", DataType.VARCHAR),
            Column("activo", DataType.BOOLEAN),
        ]
    )


def test_heap_metadata_is_canonical_and_round_trips_without_file_io(schema, no_file_io):
    metadata = OrganizationMetadata(OrganizationType.HEAP, schema)

    with no_file_io():
        first = metadata.serialize()
        second = metadata.serialize()
        rebuilt = OrganizationMetadata.deserialize(first)

    assert first == second
    assert first.decode("utf-8") == json.dumps(
        json.loads(first),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert rebuilt == metadata
    assert rebuilt.data_page_ids == range(1, 1)


def test_sequential_metadata_persists_key_policy_threshold_and_page_references(schema):
    metadata = OrganizationMetadata(
        OrganizationType.PAGED_SEQUENTIAL,
        schema,
        active_record_count=3,
        deleted_record_count=1,
        data_page_count=2,
        key_column="id",
        allow_duplicate_keys=True,
        reorganization_threshold=0.30,
    )

    rebuilt = OrganizationMetadata.deserialize(metadata.serialize())

    assert rebuilt == metadata
    assert rebuilt.data_page_ids == range(1, 3)
    assert rebuilt.schema.column("id").data_type is DataType.INTEGER


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"organization_type": "heap"}, InvalidTypeError),
        ({"schema": []}, InvalidTypeError),
        ({"active_record_count": True}, InvalidTypeError),
        ({"active_record_count": -1}, ValidationError),
        ({"deleted_record_count": 1}, ValidationError),
        ({"first_data_page_id": 0}, ValidationError),
        ({"data_page_count": 2**32 - 1}, ValidationError),
        ({"key_column": "id"}, ValidationError),
    ],
)
def test_heap_metadata_rejects_invalid_invariants(schema, changes, error):
    arguments = {"organization_type": OrganizationType.HEAP, "schema": schema}
    arguments.update(changes)

    with pytest.raises(error):
        OrganizationMetadata(**arguments)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"key_column": None}, ValidationError),
        ({"key_column": "missing"}, SchemaError),
        ({"allow_duplicate_keys": 1}, InvalidTypeError),
        ({"reorganization_threshold": 1}, InvalidTypeError),
        ({"reorganization_threshold": 0.0}, ValidationError),
        ({"reorganization_threshold": 1.01}, ValidationError),
        ({"reorganization_threshold": float("nan")}, ValidationError),
    ],
)
def test_sequential_metadata_rejects_invalid_invariants(schema, changes, error):
    arguments = {
        "organization_type": OrganizationType.PAGED_SEQUENTIAL,
        "schema": schema,
        "data_page_count": 1,
        "key_column": "id",
        "allow_duplicate_keys": True,
        "reorganization_threshold": 0.30,
    }
    arguments.update(changes)

    with pytest.raises(error):
        OrganizationMetadata(**arguments)


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        b'{"magic":"MINIDB_ORGANIZATION","magic":"duplicate"}',
        b'{"active_record_count":NaN}',
        b"\xff",
    ],
)
def test_deserialize_rejects_malformed_documents(payload):
    with pytest.raises(ValidationError):
        OrganizationMetadata.deserialize(payload)


def test_deserialize_rejects_missing_extra_and_unknown_fields(schema):
    document = json.loads(
        OrganizationMetadata(OrganizationType.HEAP, schema).serialize()
    )

    missing = dict(document)
    del missing["schema"]
    with pytest.raises(ValidationError, match="missing"):
        OrganizationMetadata.deserialize(json.dumps(missing).encode())

    extra = dict(document, unexpected=True)
    with pytest.raises(ValidationError, match="extra"):
        OrganizationMetadata.deserialize(json.dumps(extra).encode())

    unknown_type = dict(document, organization_type="tree")
    with pytest.raises(ValidationError, match="Unknown"):
        OrganizationMetadata.deserialize(json.dumps(unknown_type).encode())


@pytest.mark.parametrize(
    ("schema_descriptor", "error"),
    [
        ({}, InvalidTypeError),
        (["not a pair"], ValidationError),
        ([[1, "INTEGER"]], InvalidTypeError),
        ([["id", "UNKNOWN"]], SchemaError),
        ([["id", "INTEGER"], ["id", "FLOAT"]], SchemaError),
    ],
)
def test_deserialize_rejects_invalid_persisted_schemas(
    schema, schema_descriptor, error
):
    document = json.loads(
        OrganizationMetadata(OrganizationType.HEAP, schema).serialize()
    )
    document["schema"] = schema_descriptor

    with pytest.raises(error):
        OrganizationMetadata.deserialize(json.dumps(document).encode())


def test_oversized_schema_descriptor_is_rejected_before_page_access():
    schema = Schema(
        [Column(f"column_{position:04d}_with_a_long_name", DataType.VARCHAR)
         for position in range(180)]
    )
    metadata = OrganizationMetadata(OrganizationType.HEAP, schema)

    with pytest.raises(ValidationError, match="does not fit"):
        metadata.serialize()


def test_metadata_binary_api_requires_immutable_bytes():
    with pytest.raises(InvalidTypeError):
        OrganizationMetadata.deserialize(bytearray(b"{}"))
