"""Explicit compaction and full byte reconstruction, without file access."""

import random

import pytest

from engine.errors import InvalidReferenceError, ValidationError
from engine.storage import Page, RID, SlotEntry
from engine.storage.binary import MAX_RECORD_SIZE, MAX_SLOTS, PAGE_HEADER_SIZE, PAGE_SIZE, SLOT_SIZE


def assert_records(page, expected):
    assert page.active_record_count == len(expected)
    for slot_id in range(page.slot_count):
        rid = RID(page.page_id, slot_id)
        if rid in expected:
            assert page.read(slot_id) == expected[rid]
        else:
            assert page.slots[slot_id] == SlotEntry()
            with pytest.raises(InvalidReferenceError, match="free/deleted"):
                page.read(slot_id)


def test_compaction_preserves_rids_and_recovers_holes_for_new_insert(no_file_io):
    with no_file_io():
        page = Page(17)
        payloads = [b"a" * 900, b"b" * 1400, b"c" * 1200, b""]
        expected = {RID(17, page.insert(payload)): payload for payload in payloads}
        page.delete(1)
        del expected[RID(17, 1)]
        before_free = page.free_space()
        old_offset = page.slots[2].offset
        with pytest.raises(ValidationError, match="Insufficient"):
            page.insert(b"new" * 500)
        assert page.compact() is None
        assert page.free_space() == before_free + 1400
        assert page.slots[2].offset != old_offset
        assert page.slots[3].offset == PAGE_SIZE  # Empty active payload remains canonical.
        assert page.slot_count == 4
        assert_records(page, expected)
        assert page.insert(b"new" * 500) == 1
        expected[RID(17, 1)] = b"new" * 500
        assert_records(page, expected)
        assert_records(Page.deserialize(page.serialize()), expected)


@pytest.mark.parametrize("deleted", [(), (0,), (1,), (2,), (0, 2), (0, 1, 2)])
def test_compaction_and_round_trip_of_varied_deleted_positions(deleted):
    page = Page(4)
    expected = {RID(4, page.insert(p)): p for p in (b"first", bytes(range(256)), b"last" * 25)}
    for slot_id in deleted:
        page.delete(slot_id)
        del expected[RID(4, slot_id)]
    snapshot = page.serialize()
    recovered = Page.deserialize(snapshot)
    assert recovered.serialize() == snapshot  # Includes holes and unused bytes.
    assert recovered.header == page.header
    assert recovered.slots == page.slots
    assert_records(recovered, expected)
    recovered.compact()
    assert recovered.free_space() == PAGE_SIZE - PAGE_HEADER_SIZE - 3 * SLOT_SIZE - sum(
        map(len, expected.values())
    )
    assert recovered.slot_count == 3
    assert_records(recovered, expected)
    assert page.serialize() == snapshot  # Reconstructed buffer has independent ownership.
    packed = recovered.serialize()
    recovered.compact()
    assert recovered.serialize() == packed  # Idempotent packing.
    restored = Page.deserialize(packed)
    assert restored.serialize() == packed
    assert_records(restored, expected)


def test_all_deleted_full_page_can_reuse_its_entire_payload_capacity():
    page = Page(0)
    page.insert(b"x" * MAX_RECORD_SIZE)
    page.delete(0)
    assert page.free_space() == 0
    page.compact()
    assert page.slot_count == 1  # Tombstone and directory cost remain.
    assert page.free_space() == MAX_RECORD_SIZE
    assert page.serialize()[PAGE_HEADER_SIZE:] == bytes(PAGE_SIZE - PAGE_HEADER_SIZE)
    assert page.insert(b"y" * MAX_RECORD_SIZE) == 0
    assert page.read(0) == b"y" * MAX_RECORD_SIZE
    assert page.free_space() == 0


@pytest.mark.parametrize("payload", [None, b"", b"x" * MAX_RECORD_SIZE])
def test_compact_empty_or_already_packed_page_is_a_noop(payload):
    page = Page(0)
    if payload is not None:
        page.insert(payload)
    before = page.serialize()
    page.compact()
    assert page.serialize() == before
    assert Page.deserialize(before).serialize() == before


def test_compaction_does_not_reclaim_slot_directory_bytes_or_renumber_slots():
    page = Page(0)
    for _ in range(MAX_SLOTS):
        page.insert(b"")
    for slot_id in range(MAX_SLOTS - 1):
        page.delete(slot_id)
    page.compact()
    assert page.slot_count == MAX_SLOTS
    assert page.read(MAX_SLOTS - 1) == b""
    assert page.free_space() == 4
    assert page.insert(b"1234") == 0
    assert Page.deserialize(page.serialize()).read(MAX_SLOTS - 1) == b""
    before = page.serialize()
    with pytest.raises(ValidationError):
        page.insert(b"no")
    assert page.serialize() == before


def test_compaction_after_slot_reuse_reads_from_original_not_overlapping_destination():
    page = Page(2)
    page.insert(b"a" * 100)
    page.insert(b"b" * 300)
    page.insert(b"c" * 200)
    page.delete(0)
    assert page.insert(b"d" * 500) == 0
    expected = {RID(2, i): page.read(i) for i in range(3)}
    page.compact()
    assert_records(page, expected)
    assert_records(Page.deserialize(page.serialize()), expected)


def test_seeded_mixed_compaction_and_round_trips_match_rid_model():
    rng = random.Random(212213)
    page = Page(3)
    expected = {}
    for _ in range(200):
        operation = rng.choice(["insert", "delete", "compact", "round_trip"])
        if operation == "insert":
            payload = rng.randbytes(rng.randrange(220))
            required = len(payload) + (0 if page.slot_count > len(expected) else SLOT_SIZE)
            if required > page.free_space():
                before = page.serialize()
                with pytest.raises(ValidationError):
                    page.insert(payload)
                assert page.serialize() == before
            else:
                expected[RID(3, page.insert(payload))] = payload
        elif operation == "delete" and expected:
            rid = rng.choice(list(expected))
            page.delete(rid.slot_id)
            del expected[rid]
        elif operation == "compact":
            old_slots = page.slot_count
            page.compact()
            assert page.slot_count == old_slots
            assert page.free_space() == (
                PAGE_SIZE - PAGE_HEADER_SIZE - SLOT_SIZE * old_slots - sum(map(len, expected.values()))
            )
        else:
            before = page.serialize()
            page = Page.deserialize(before)
            assert page.serialize() == before
        assert_records(page, expected)
