"""PageHeader round-trips and validates metadata, not records or disk state."""

from dataclasses import FrozenInstanceError, replace
import struct

import pytest

from engine.errors import InvalidTypeError, ValidationError
from engine.storage import PageHeader


def test_empty_page_header_defaults_and_golden_bytes():
    header = PageHeader(page_id=0)
    assert header.slot_count == header.active_record_count == 0
    assert header.free_space_start == 12
    assert header.free_space_end == 4096
    assert header.contiguous_free_space == 4084
    assert header.serialize() == bytes.fromhex("00000000 0000 0c00 0010 0000")
    assert len(header.serialize()) == 12


@pytest.mark.parametrize("page_id", [0, 1, 0x12345678, 2**32 - 1])
def test_page_id_round_trip_does_not_require_allocation(page_id):
    header = PageHeader(page_id)
    assert PageHeader.deserialize(header.serialize()) == header


def test_nonempty_header_golden_bytes_and_round_trip():
    header = PageHeader(0x12345678, 2, 22, 4070, 1)
    expected = bytes.fromhex("78563412 0200 1600 e60f 0100")
    assert header.serialize() == expected
    assert PageHeader.deserialize(expected) == header
    assert header.contiguous_free_space == 4048


def test_fragmented_page_with_no_live_records_does_not_imply_all_bytes_are_free():
    header = PageHeader(0, 2, 22, 4000, 0)
    assert header.contiguous_free_space == 3978
    assert PageHeader.deserialize(header.serialize()) == header


def test_full_page_and_maximum_directory_size():
    assert PageHeader(0, 1, 17, 17, 1).contiguous_free_space == 0
    header = PageHeader(0, 816, 4092, 4096, 816)
    assert PageHeader.deserialize(header.serialize()) == header
    assert header.contiguous_free_space == 4


def test_page_header_is_immutable_and_replacements_are_validated():
    header = PageHeader(0)
    with pytest.raises(FrozenInstanceError):
        header.page_id = 1
    with pytest.raises(FrozenInstanceError):
        header.slot_count = 2
    assert replace(header, page_id=1) == PageHeader(1)
    with pytest.raises(ValidationError):
        replace(header, slot_count=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"page_id": -1}, {"page_id": 2**32},
        {"slot_count": -1}, {"slot_count": 65536},
        {"slot_count": 817, "free_space_start": 4097},
        {"active_record_count": -1}, {"active_record_count": 1},
        {"active_record_count": 65536},
        {"free_space_start": 11}, {"free_space_start": 13},
        {"free_space_start": 65536},
        {"free_space_end": -1}, {"free_space_end": 11},
        {"free_space_end": 4095}, {"free_space_end": 4097},
    ],
)
def test_invalid_metadata_is_rejected_on_construction(changes):
    with pytest.raises(ValidationError):
        PageHeader(**({"page_id": 0} | changes))


@pytest.mark.parametrize(
    "field", ["page_id", "slot_count", "free_space_start", "free_space_end", "active_record_count"]
)
@pytest.mark.parametrize("value", [True, 1.0, "1", None])
def test_header_requires_exact_integer_fields(field, value):
    with pytest.raises(InvalidTypeError):
        PageHeader(**({"page_id": 0} | {field: value}))


def test_custom_integer_subclass_is_not_a_header_integer():
    class CustomInt(int):
        pass

    with pytest.raises(InvalidTypeError):
        PageHeader(CustomInt(0))


@pytest.mark.parametrize("size", [0, 1, 11, 13, 4096])
def test_header_deserialization_requires_exact_header_length(size):
    with pytest.raises(ValidationError, match="exactly 12"):
        PageHeader.deserialize(bytes(size))


@pytest.mark.parametrize("payload", [None, "", [], bytearray(12), memoryview(bytes(12))])
def test_header_deserialization_requires_bytes(payload):
    with pytest.raises(InvalidTypeError):
        PageHeader.deserialize(payload)


@pytest.mark.parametrize(
    "fields",
    [
        (0, 0, 0, 4096, 0),  # header/directory boundary
        (0, 0, 12, 4095, 0),  # payload without slots
        (0, 2, 22, 4096, 3),  # active > slots
        (0, 817, 4097, 4097, 0),  # too many slots
        (0, 2, 21, 4096, 0),  # wrong directory boundary
        (0, 2, 22, 21, 0),  # overlapping free area
        (0, 2, 22, 4097, 0),  # outside page
        (0, 65535, 65535, 65535, 65535),
    ],
)
def test_correctly_sized_but_corrupt_header_bytes_are_rejected(fields):
    with pytest.raises(ValidationError):
        PageHeader.deserialize(struct.pack("<IHHHH", *fields))
