"""Slot v1 fields, states, canonical empty payloads and binary boundaries."""

from dataclasses import FrozenInstanceError, replace

import pytest

from engine.errors import InvalidTypeError, ValidationError
from engine.storage import SlotEntry
from engine.storage.binary import SLOT_ACTIVE, SLOT_FREE, SLOT_STRUCT, validate_slot_layout


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ((0, 0, SLOT_FREE), "0000 0000 00"),
        ((4093, 3, SLOT_ACTIVE), "fd0f 0300 01"),
        ((4096, 0, SLOT_ACTIVE), "0010 0000 01"),
        ((17, 4079, SLOT_ACTIVE), "1100 ef0f 01"),
    ],
)
def test_slots_round_trip_with_fixed_expected_bytes(fields, expected):
    slot = SlotEntry(*fields)
    encoded = bytes.fromhex(expected)
    assert slot.serialize() == encoded
    assert len(encoded) == 5
    assert SlotEntry.deserialize(encoded) == slot
    assert slot.is_active is (fields[2] == SLOT_ACTIVE)
    validate_slot_layout(offset=slot.offset, length=slot.length, status=slot.status)


def test_default_slot_is_free_not_an_active_empty_record():
    free = SlotEntry()
    empty = SlotEntry(4096, 0, SLOT_ACTIVE)
    assert free == SlotEntry(0, 0, SLOT_FREE)
    assert free != empty
    assert not free.is_active
    assert empty.is_active
    assert SlotEntry.deserialize(free.serialize()) != SlotEntry.deserialize(empty.serialize())


def test_slot_is_an_immutable_hashable_value():
    slot = SlotEntry(4000, 10, SLOT_ACTIVE)
    assert {slot: "row"}[SlotEntry(4000, 10, SLOT_ACTIVE)] == "row"
    with pytest.raises(FrozenInstanceError):
        slot.offset = 4001
    with pytest.raises(FrozenInstanceError):
        slot.status = SLOT_FREE
    assert replace(slot, length=20) == SlotEntry(4000, 20, SLOT_ACTIVE)
    with pytest.raises(ValidationError):
        replace(slot, status=SLOT_FREE)


@pytest.mark.parametrize(
    "fields",
    [
        (-1, 1, 1), (65536, 1, 1), (0, 1, 1), (12, 1, 1), (16, 1, 1),
        (4096, 1, 1), (4097, 0, 1), (65535, 1, 1),
        (4000, -1, 1), (4000, 65536, 1), (4000, 65535, 1), (4000, 97, 1),
        (17, 4080, 1), (4000, 0, 1), (0, 0, 1),  # Noncanonical active empty slots.
        (1, 0, 0), (0, 1, 0), (4096, 0, 0), (4000, 2, 0),
        (0, 0, -1), (0, 0, 2), (0, 0, 255), (0, 0, 256),
    ],
)
def test_invalid_slot_fields_are_rejected(fields):
    with pytest.raises(ValidationError):
        SlotEntry(*fields)


@pytest.mark.parametrize("field", ["offset", "length", "status"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_slot_fields_require_exact_builtin_integers(field, value):
    fields = dict(offset=4000, length=10, status=SLOT_ACTIVE)
    fields[field] = value
    with pytest.raises(InvalidTypeError):
        SlotEntry(**fields)


@pytest.mark.parametrize("field", ["offset", "length", "status"])
def test_custom_integer_subclasses_are_rejected(field):
    class CustomInt(int):
        pass

    fields = dict(offset=4000, length=10, status=SLOT_ACTIVE)
    fields[field] = CustomInt(fields[field])
    with pytest.raises(InvalidTypeError):
        SlotEntry(**fields)


@pytest.mark.parametrize("size", [0, 1, 2, 3, 4, 6, 4096])
def test_slot_requires_exactly_five_bytes(size):
    with pytest.raises(ValidationError, match="exactly 5"):
        SlotEntry.deserialize(bytes(size))


@pytest.mark.parametrize("payload", [None, "", [], 5, bytearray(5), memoryview(bytes(5))])
def test_slot_binary_input_requires_bytes(payload):
    with pytest.raises(InvalidTypeError):
        SlotEntry.deserialize(payload)


@pytest.mark.parametrize(
    "fields",
    [(0, 0, 2), (4000, 5, 0), (0, 1, 0), (4096, 1, 1),
     (4000, 65535, 1), (0, 0, 1), (16, 1, 1), (4000, 0, 1)],
)
def test_correct_length_but_malformed_slot_bytes_are_rejected(fields):
    with pytest.raises(ValidationError):
        SlotEntry.deserialize(SLOT_STRUCT.pack(*fields))
