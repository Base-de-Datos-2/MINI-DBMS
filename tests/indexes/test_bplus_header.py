"""Persistent B+ metadata round trips and rejects incompatible state."""

from dataclasses import FrozenInstanceError, replace
import json

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes import BPlusFileHeader
from engine.storage.binary import MAX_RECORD_SIZE, PAGE_SIZE, UINT32_MAX


def empty_header(**overrides):
    values = {
        "index_name": "idx_students_id",
        "table_name": "students",
        "key_column": "id",
        "key_type": DataType.INTEGER,
    }
    values.update(overrides)
    return BPlusFileHeader(**values)


def test_empty_bplus_header_round_trip_is_canonical_and_bounded(no_file_io):
    with no_file_io():
        header = empty_header()
        encoded = header.serialize()
        assert len(encoded) <= MAX_RECORD_SIZE
        assert BPlusFileHeader.deserialize(encoded) == header
        assert BPlusFileHeader.deserialize(encoded).serialize() == encoded
        assert header.root_page_id is None
        assert header.first_leaf_page_id is None
        assert header.height == header.entry_count == header.node_page_count == 0


def test_nonempty_header_tracks_root_first_leaf_height_entries_and_free_head():
    header = empty_header(
        root_page_id=4,
        first_leaf_page_id=1,
        height=2,
        entry_count=37,
        node_page_count=6,
        free_node_head_page_id=5,
    )
    assert BPlusFileHeader.deserialize(header.serialize()) == header
    assert header.root_page_id == 4
    assert header.first_leaf_page_id == 1
    assert header.height == 2
    assert header.entry_count == 37
    assert header.node_page_count == 6
    assert header.free_node_head_page_id == 5


def test_height_one_root_is_the_first_leaf():
    header = empty_header(
        root_page_id=1,
        first_leaf_page_id=1,
        height=1,
        entry_count=1,
        node_page_count=1,
    )
    assert BPlusFileHeader.deserialize(header.serialize()) == header


def test_empty_tree_may_retain_allocated_pages_on_free_list():
    header = empty_header(node_page_count=3, free_node_head_page_id=2)
    assert header.entry_count == 0
    assert header.root_page_id is header.first_leaf_page_id is None


def test_bplus_header_is_immutable_and_replace_revalidates():
    header = empty_header()
    with pytest.raises(FrozenInstanceError):
        header.height = 1
    with pytest.raises(ValidationError, match="non-empty"):
        replace(header, entry_count=1)


@pytest.mark.parametrize("field", ["index_name", "table_name", "key_column"])
@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_header_rejects_blank_names(field, value):
    with pytest.raises(ValidationError, match="must not be empty"):
        empty_header(**{field: value})


@pytest.mark.parametrize("field", ["index_name", "table_name", "key_column"])
@pytest.mark.parametrize("value", [None, 1, True, b"name"])
def test_header_rejects_non_string_names(field, value):
    with pytest.raises(InvalidTypeError, match="string"):
        empty_header(**{field: value})


@pytest.mark.parametrize("key_type", ["INTEGER", None, int, 1])
def test_header_requires_data_type_member(key_type):
    with pytest.raises(InvalidTypeError, match="DataType"):
        empty_header(key_type=key_type)


@pytest.mark.parametrize(
    "field", ["clustered", "allow_duplicate_keys", "build_complete"]
)
@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_header_requires_exact_boolean_flags(field, value):
    with pytest.raises(InvalidTypeError, match="bool"):
        empty_header(**{field: value})


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"magic": "OTHER"}, "signature"),
        ({"version": 2}, "version"),
        ({"page_size": 8192}, "page size"),
        ({"root_page_id": 0}, "page 0"),
        ({"first_leaf_page_id": 2, "node_page_count": 1}, "range"),
        ({"height": 1}, "empty"),
        ({"entry_count": 1}, "non-empty"),
        ({"root_page_id": 1, "first_leaf_page_id": 1,
          "height": 2, "entry_count": 1, "node_page_count": 2}, "multi-level"),
        ({"root_page_id": 1, "first_leaf_page_id": 1,
          "height": 1, "entry_count": 1, "node_page_count": 1,
          "free_node_head_page_id": 1}, "free-node"),
    ],
)
def test_header_rejects_inconsistent_metadata(updates, message):
    with pytest.raises(ValidationError, match=message):
        empty_header(**updates)


@pytest.mark.parametrize("field", ["height", "entry_count", "node_page_count"])
@pytest.mark.parametrize("value", [True, 1.0, "1", None])
def test_header_counters_require_exact_int(field, value):
    with pytest.raises(InvalidTypeError):
        empty_header(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("height", -1),
        ("height", UINT32_MAX + 1),
        ("entry_count", -1),
        ("entry_count", 1 << 64),
        ("node_page_count", UINT32_MAX),
    ],
)
def test_header_counters_have_explicit_binary_bounds(field, value):
    with pytest.raises(ValidationError):
        empty_header(**{field: value})


def test_deserialize_rejects_wrong_magic_version_page_size_and_key_type():
    document = json.loads(empty_header().serialize())
    for field, value, message in (
        ("magic", "WRONG", "signature"),
        ("version", 99, "version"),
        ("page_size", PAGE_SIZE * 2, "page size"),
        ("key_type", "DECIMAL", "key type"),
    ):
        changed = dict(document)
        changed[field] = value
        with pytest.raises(ValidationError, match=message):
            BPlusFileHeader.deserialize(
                json.dumps(changed, separators=(",", ":"), sort_keys=True).encode()
            )


def test_deserialize_rejects_malformed_duplicate_missing_and_extra_fields():
    with pytest.raises(ValidationError, match="Malformed"):
        BPlusFileHeader.deserialize(b"{")
    with pytest.raises(ValidationError, match="Duplicate"):
        BPlusFileHeader.deserialize(b'{"magic":"a","magic":"b"}')

    document = json.loads(empty_header().serialize())
    document.pop("height")
    with pytest.raises(ValidationError, match="missing"):
        BPlusFileHeader.deserialize(json.dumps(document).encode())
    document["height"] = 0
    document["unexpected"] = 1
    with pytest.raises(ValidationError, match="extra"):
        BPlusFileHeader.deserialize(json.dumps(document).encode())


@pytest.mark.parametrize("payload", [None, "{}", bytearray(b"{}"), memoryview(b"{}")])
def test_deserialize_requires_immutable_bytes(payload):
    with pytest.raises(InvalidTypeError):
        BPlusFileHeader.deserialize(payload)


def test_definition_and_clustered_physical_order_are_validated():
    header = empty_header(clustered=True, allow_duplicate_keys=False)
    header.validate_definition(
        index_name="idx_students_id",
        table_name="students",
        key_column="id",
        key_type=DataType.INTEGER,
        clustered=True,
        allow_duplicate_keys=False,
    )
    header.validate_clustered_storage("id")
    with pytest.raises(ValidationError, match="key_type"):
        header.validate_definition(
            index_name="idx_students_id",
            table_name="students",
            key_column="id",
            key_type=DataType.FLOAT,
            clustered=True,
            allow_duplicate_keys=False,
        )
    with pytest.raises(ValidationError, match="physical storage"):
        header.validate_clustered_storage("other")
    with pytest.raises(ValidationError, match="physical storage"):
        header.validate_clustered_storage(None)


def test_unclustered_header_does_not_require_a_physical_ordering_key():
    empty_header(clustered=False).validate_clustered_storage(None)


def test_header_preserves_unicode_names_and_rejects_unencodable_names():
    header = empty_header(index_name="índice_東京", table_name="estudiantes_😀")
    assert BPlusFileHeader.deserialize(header.serialize()) == header
    with pytest.raises(ValidationError, match="UTF-8"):
        empty_header(index_name="bad\ud800").serialize()
