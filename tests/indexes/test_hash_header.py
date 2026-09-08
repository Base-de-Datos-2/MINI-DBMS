"""Stage 5.3: complete canonical metadata for restart."""

from dataclasses import replace
import json

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes import HashFileHeader


def header(**overrides):
    values = {
        "index_name": "idx_people_id_hash",
        "table_name": "people",
        "key_column": "id",
        "key_type": DataType.INTEGER,
    }
    values.update(overrides)
    return HashFileHeader(**values)


def test_hash_header_round_trip_contains_every_behavioral_choice():
    original = header()
    payload = original.serialize()
    assert HashFileHeader.deserialize(payload) == original
    document = json.loads(payload)
    assert document["hash_algorithm"] == "FNV1A"
    assert document["hash_width"] == 64
    assert document["bit_selection"] == "LSB"
    assert document["directory_format_version"] == 1
    assert document["bucket_format_version"] == 1
    assert document["global_depth"] == 1
    assert document["directory_entry_count"] == 2


@pytest.mark.parametrize(
    "change",
    [
        {"magic": "wrong"},
        {"version": 2},
        {"hash_algorithm": "runtime-hash"},
        {"hash_width": 32},
        {"bit_selection": "MSB"},
        {"directory_format_version": 2},
        {"bucket_format_version": 2},
        {"directory_entry_count": 3},
        {"global_depth": 21, "maximum_global_depth": 21},
        {"directory_page_count": 0},
        {"bucket_count": 0},
        {"index_page_count": 1},
    ],
)
def test_hash_header_rejects_incompatible_or_impossible_metadata(change):
    with pytest.raises(ValidationError):
        replace(header(), **change)


def test_hash_header_requires_exact_field_types_and_set():
    with pytest.raises(InvalidTypeError):
        header(global_depth=True)
    document = json.loads(header().serialize())
    document.pop("hash_algorithm_version")
    with pytest.raises(ValidationError, match="missing"):
        HashFileHeader.deserialize(json.dumps(document).encode())


def test_hash_header_rejects_truncated_json():
    with pytest.raises(ValidationError, match="Malformed"):
        HashFileHeader.deserialize(header().serialize()[:-1])
