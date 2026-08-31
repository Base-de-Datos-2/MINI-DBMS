"""Page-local operations: capacity, opaque bytes, slot reuse and corruption."""

from dataclasses import FrozenInstanceError
import random

import pytest

from engine.errors import InvalidReferenceError, InvalidTypeError, ValidationError
from engine.storage import Page, PageHeader, SlotEntry
from engine.storage.binary import (
    MAX_RECORD_SIZE, MAX_SLOTS, PAGE_HEADER_SIZE, PAGE_HEADER_STRUCT, PAGE_SIZE,
    SLOT_ACTIVE, SLOT_FREE, SLOT_SIZE, SLOT_STRUCT,
)
from tests.page_corruption import INVALID_PAGE_HEADER_FIELDS, INVALID_SLOT_FIELDS


def populated_page():
    page = Page(7)
    assert page.insert(b"alpha") == 0
    assert page.insert(b"beta") == 1
    return page


@pytest.mark.parametrize("page_id", [0, 1, 0x12345678, 2**32 - 1])
def test_empty_page_metadata_and_byte_round_trip(page_id):
    page = Page(page_id)
    assert page.page_id == page_id
    assert page.header == PageHeader(page_id)
    assert page.slots == ()
    assert page.slot_count == page.active_record_count == 0
    assert page.free_space() == PAGE_SIZE - PAGE_HEADER_SIZE == 4084
    serialized = page.serialize()
    assert type(serialized) is bytes
    assert len(serialized) == 4096
    assert serialized[12:] == bytes(4084)
    recovered = Page.deserialize(serialized)
    assert recovered is not page
    assert recovered.header == page.header
    assert recovered.serialize() == serialized
    recovered.insert(b"new")
    assert page.slot_count == 0


def test_empty_page_has_golden_header_bytes():
    expected = bytes.fromhex("78563412 0000 0c00 0010 0000") + bytes(4084)
    assert Page(0x12345678).serialize() == expected


@pytest.mark.parametrize("page_id", [-1, 2**32, 2**100])
def test_invalid_page_id_ranges_are_rejected(page_id):
    with pytest.raises(ValidationError):
        Page(page_id)


@pytest.mark.parametrize("page_id", [True, False, 1.0, "1", None])
def test_page_id_types_are_rejected(page_id):
    with pytest.raises(InvalidTypeError):
        Page(page_id)


@pytest.mark.parametrize("size", [0, 12, 4095, 4097, 8192])
def test_empty_page_decode_rejects_incorrect_buffer_sizes(size):
    with pytest.raises(ValidationError, match="exactly 4096"):
        Page.deserialize(bytes(size))


@pytest.mark.parametrize("payload", [None, "", [], bytearray(4096), memoryview(bytes(4096))])
def test_empty_page_decode_requires_bytes(payload):
    with pytest.raises(InvalidTypeError):
        Page.deserialize(payload)


@pytest.mark.parametrize(
    "fields", [(0, 0, 0, 4096, 0), (0, 0, 12, 4095, 0), (0, 0, 12, 4096, 1)],
)
def test_empty_page_decode_rejects_invalid_header(fields):
    payload = PAGE_HEADER_STRUCT.pack(*fields) + bytes(4084)
    with pytest.raises(ValidationError):
        Page.deserialize(payload)


def test_empty_page_round_trip_preserves_opaque_unused_bytes():
    payload = PageHeader(3).serialize() + b"x" * 4084
    page = Page.deserialize(payload)
    assert page.slot_count == 0
    assert page.serialize() == payload


@pytest.mark.parametrize("delete", [False, True])
def test_reconstruction_preserves_active_or_deleted_slots(delete):
    page = Page(0)
    slot_id = page.insert(b"row")
    if delete:
        page.delete(slot_id)
    recovered = Page.deserialize(page.serialize())
    assert recovered.header == page.header
    assert recovered.slots == page.slots
    assert recovered.serialize() == page.serialize()
    if delete:
        with pytest.raises(InvalidReferenceError, match="free/deleted"):
            recovered.read(slot_id)
    else:
        assert recovered.read(slot_id) == b"row"


def test_insert_has_correct_header_directory_and_payload_bytes():
    page = Page(1)
    assert page.insert(b"abc") == 0
    expected = (
        bytes.fromhex("01000000 0100 1100 fd0f 0100")
        + bytes.fromhex("fd0f 0300 01")
        + bytes(4076)
        + b"abc"
    )
    assert page.serialize() == expected
    assert page.slots == (SlotEntry(4093, 3, SLOT_ACTIVE),)
    assert page.free_space() == 4076
    assert page.read(0) == b"abc"


def test_multiple_variable_sized_payloads_preserve_previous_slots_and_records():
    page = Page(0)
    payloads = [b"a", bytes(range(256)), b"\xff\x00\x80", b"", b"long" * 100]
    used = 0
    for i, payload in enumerate(payloads):
        slot_id = page.insert(payload)
        assert type(slot_id) is int
        assert slot_id == i
        used += len(payload) + SLOT_SIZE
        assert page.free_space() == 4084 - used
        assert page.slot_count == page.active_record_count == i + 1
        assert len(page.serialize()) == PAGE_SIZE
        assert [page.read(j) for j in range(i + 1)] == payloads[:i + 1]
    assert page.slots[3] == SlotEntry(PAGE_SIZE, 0, SLOT_ACTIVE)


def test_header_slots_and_record_results_are_immutable_snapshots():
    page = populated_page()
    header, slots, serialized, record = page.header, page.slots, page.serialize(), page.read(0)
    with pytest.raises(FrozenInstanceError):
        header.slot_count = 7
    with pytest.raises(FrozenInstanceError):
        slots[0].offset = 0
    with pytest.raises(TypeError):
        slots[0] = SlotEntry()
    with pytest.raises(TypeError):
        record[0] = 0
    for attribute, value in (("header", header), ("slots", slots), ("page_id", 9)):
        with pytest.raises(AttributeError):
            setattr(page, attribute, value)
    page.delete(0)
    assert header.active_record_count == 2
    assert slots[0].is_active
    assert record == b"alpha"
    assert serialized != page.serialize()


@pytest.mark.parametrize("payload", [None, "row", [], {}, 1, True, bytearray(b"row"), memoryview(b"row")])
def test_insert_rejects_nonbytes_without_mutation(payload):
    page = populated_page()
    before = page.serialize()
    with pytest.raises(InvalidTypeError):
        page.insert(payload)
    assert page.serialize() == before
    assert page.read(0) == b"alpha"
    assert page.read(1) == b"beta"


@pytest.mark.parametrize("size", [4080, 4096, 8192])
def test_oversized_insert_leaves_an_empty_page_unchanged(size):
    page = Page(0)
    before = page.serialize()
    with pytest.raises(ValidationError, match="capacity"):
        page.insert(bytes(size))
    assert page.serialize() == before


def test_maximum_record_fills_page_and_failed_inserts_preserve_it():
    page = Page(0)
    payload = b"x" * MAX_RECORD_SIZE
    assert page.insert(payload) == 0
    assert page.free_space() == 0
    assert page.header.free_space_end == page.header.free_space_start == 17
    before = page.serialize()
    for rejected in (b"", b"a", bytes(MAX_RECORD_SIZE), bytes(MAX_RECORD_SIZE + 1)):
        with pytest.raises(ValidationError):
            page.insert(rejected)
        assert page.serialize() == before
        assert page.read(0) == payload


def test_payload_space_without_space_for_a_new_slot_is_insufficient():
    page = Page(0)
    page.insert(bytes(MAX_RECORD_SIZE - 4))
    assert page.free_space() == 4
    before = page.serialize()
    with pytest.raises(ValidationError, match="requires 5 bytes"):
        page.insert(b"")
    assert page.serialize() == before


@pytest.mark.parametrize("method", ["read", "delete"])
@pytest.mark.parametrize("slot_id", [-1, 2, 816, 2**100])
def test_unknown_slot_ids_are_distinct_from_deleted_slots(method, slot_id):
    page = populated_page()
    before = page.serialize()
    with pytest.raises(InvalidReferenceError, match="Unknown slot_id"):
        getattr(page, method)(slot_id)
    assert page.serialize() == before


@pytest.mark.parametrize("method", ["read", "delete"])
@pytest.mark.parametrize("slot_id", [True, False, 0.0, "0", None, [], slice(0, 1)])
def test_slot_id_requires_exact_integer_type(method, slot_id):
    page = populated_page()
    before = page.serialize()
    with pytest.raises(InvalidTypeError):
        getattr(page, method)(slot_id)
    assert page.serialize() == before


def test_integer_subclass_is_not_a_slot_id():
    class CustomInt(int):
        pass

    page = populated_page()
    for method in (page.read, page.delete):
        with pytest.raises(InvalidTypeError):
            method(CustomInt(0))


def test_empty_page_has_no_addressable_slots():
    page = Page(0)
    for method in (page.read, page.delete):
        with pytest.raises(InvalidReferenceError, match="Unknown slot_id"):
            method(0)


def test_delete_marks_only_target_slot_and_count_without_erasing_or_reclaiming_bytes():
    page = populated_page()
    header = page.header
    old_slot, survivor = page.slots
    before = page.serialize()
    assert page.delete(0) is None
    assert page.active_record_count == 1
    assert page.slot_count == 2
    assert page.slots == (SlotEntry(), survivor)
    assert page.header.free_space_start == header.free_space_start
    assert page.header.free_space_end == header.free_space_end
    assert page.free_space() == header.contiguous_free_space
    after = page.serialize()
    assert after[old_slot.offset:old_slot.offset + old_slot.length] == b"alpha"
    assert after[header.free_space_start:] == before[header.free_space_start:]
    assert after[12:17] == bytes(5)
    assert page.read(1) == b"beta"
    for method in (page.read, page.delete):
        with pytest.raises(InvalidReferenceError, match="free/deleted"):
            method(0)
        assert page.serialize() == after


def test_deleted_slot_reuse_costs_payload_bytes_only_and_preserves_other_slots():
    page = Page(0)
    page.insert(b"a" * 10)
    page.insert(b"b" * 4060)
    assert page.free_space() == 4
    survivor = page.slots[1]
    page.delete(0)
    before = page.serialize()
    with pytest.raises(ValidationError, match="Insufficient"):
        page.insert(b"12345")
    assert page.serialize() == before
    assert page.insert(b"1234") == 0
    assert page.slot_count == page.active_record_count == 2
    assert page.free_space() == 0
    assert page.slots[1] == survivor
    assert page.read(1) == b"b" * 4060
    assert page.read(0) == b"1234"


def test_first_free_slot_is_reused_regardless_of_deletion_order():
    page = Page(0)
    for payload in (b"a", b"b", b"c", b"d"):
        page.insert(payload)
    survivor = page.slots[2]
    page.delete(3)
    page.delete(1)
    assert page.insert(b"new") == 1
    assert page.insert(b"newer") == 3
    assert page.slot_count == page.active_record_count == 4
    assert page.slots[2] == survivor
    assert page.read(2) == b"c"


def test_deleting_a_full_page_leaves_a_hole_until_explicit_compaction():
    page = Page(0)
    page.insert(b"x" * MAX_RECORD_SIZE)
    page.delete(0)
    assert page.free_space() == 0
    assert page.active_record_count == 0
    assert page.slot_count == 1
    before = page.serialize()
    with pytest.raises(ValidationError, match="compaction"):
        page.insert(b"x")
    assert page.serialize() == before
    # Reusing the slot for an empty record costs neither a new slot nor payload.
    assert page.insert(b"") == 0
    assert page.read(0) == b""
    assert page.slots[0] == SlotEntry(PAGE_SIZE, 0, SLOT_ACTIVE)
    assert page.free_space() == 0


def test_zero_length_records_consume_directory_capacity_and_can_be_deleted():
    page = Page(0)
    for i in range(MAX_SLOTS):
        assert page.insert(b"") == i
    assert page.slot_count == page.active_record_count == MAX_SLOTS == 816
    assert page.free_space() == 4
    before = page.serialize()
    with pytest.raises(ValidationError):
        page.insert(b"")
    assert page.serialize() == before
    assert page.read(0) == page.read(815) == b""
    page.delete(0)
    assert page.insert(b"1234") == 0
    assert page.free_space() == 0
    assert page.read(0) == b"1234"
    assert page.read(815) == b""
    assert len(page.serialize()) == PAGE_SIZE


@pytest.mark.parametrize("fields", INVALID_SLOT_FIELDS)
@pytest.mark.parametrize("operation", ["read", "delete", "insert", "serialize", "compact", "deserialize"])
def test_corrupt_slot_metadata_is_rejected_before_read_or_mutation(fields, operation):
    page = populated_page()
    # Deliberate raw-buffer corruption; public APIs expose no mutable buffer.
    page._data[12:17] = SLOT_STRUCT.pack(*fields)
    corrupted = bytes(page._data)
    with pytest.raises(ValidationError):
        if operation == "insert":
            page.insert(b"more")
        elif operation in {"serialize", "compact"}:
            getattr(page, operation)()
        elif operation == "deserialize":
            Page.deserialize(corrupted)
        else:
            getattr(page, operation)(1)  # Even a different slot cannot mask corruption.
    assert bytes(page._data) == corrupted


@pytest.mark.parametrize("operation", ["read", "compact", "deserialize"])
def test_overlapping_active_slots_are_rejected(operation):
    page = populated_page()
    page._data[17:22] = SLOT_STRUCT.pack(4092, 4, SLOT_ACTIVE)
    with pytest.raises(ValidationError, match="overlap"):
        if operation == "read":
            page.read(0)
        elif operation == "compact":
            page.compact()
        else:
            Page.deserialize(bytes(page._data))


@pytest.mark.parametrize("fields", INVALID_PAGE_HEADER_FIELDS)
@pytest.mark.parametrize("operation", ["read", "compact", "deserialize"])
def test_corrupt_header_is_not_treated_as_a_missing_record(fields, operation):
    page = populated_page()
    page._data[:12] = PAGE_HEADER_STRUCT.pack(*fields)
    with pytest.raises(ValidationError):
        if operation == "read":
            page.read(0)
        elif operation == "compact":
            page.compact()
        else:
            Page.deserialize(bytes(page._data))


def test_truncated_internal_buffer_is_rejected_instead_of_returning_short_payload():
    page = populated_page()
    page._data.pop()
    with pytest.raises(ValidationError, match="exactly 4096"):
        page.read(0)


def test_pages_with_equal_ids_still_own_independent_memory():
    first, second = Page(0), Page(0)
    first.insert(b"first")
    second.insert(b"second")
    first.delete(0)
    assert second.read(0) == b"second"
    assert second.active_record_count == 1


def test_deterministic_mixed_operations_match_a_small_test_only_model():
    rng = random.Random(20260831)
    page = Page(2)
    expected = {}
    for _ in range(180):
        if expected and rng.random() < 0.4:
            slot_id = rng.choice(list(expected))
            page.delete(slot_id)
            del expected[slot_id]
        else:
            payload = rng.randbytes(rng.randrange(0, 140))
            header, slots = page.header, page.slots
            expected_id = next((i for i, slot in enumerate(slots) if not slot.is_active), len(slots))
            needed = len(payload) + (SLOT_SIZE if expected_id == len(slots) else 0)
            before = page.serialize()
            if needed > header.contiguous_free_space:
                with pytest.raises(ValidationError):
                    page.insert(payload)
                assert page.serialize() == before
            else:
                assert page.insert(payload) == expected_id
                expected[expected_id] = payload
        assert page.active_record_count == len(expected)
        assert len(page.serialize()) == PAGE_SIZE
        assert {i: page.read(i) for i in expected} == expected
    for i, slot in enumerate(page.slots):
        assert slot.is_active is (i in expected)
