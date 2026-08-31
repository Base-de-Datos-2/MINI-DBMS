"""File-level boundary matrix plus the same page corruption cases used in memory."""

import pytest

from engine.errors import DatabaseError, InvalidReferenceError, InvalidTypeError, ValidationError
from engine.storage import FileHeader, Page, PageManager
from engine.storage.binary import (
    FILE_HEADER_SIZE, FILE_HEADER_STRUCT, FILE_MAGIC, PAGE_HEADER_SIZE,
    PAGE_HEADER_STRUCT, PAGE_SIZE, SLOT_SIZE, SLOT_STRUCT, UINT32_MAX,
)
from tests.page_corruption import INVALID_PAGE_HEADER_FIELDS, INVALID_SLOT_FIELDS


def valid_file_bytes(count=3):
    frames = []
    for page_id in range(count):
        page = Page(page_id)
        page.insert(b"alpha")
        page.insert(b"beta")
        frames.append(page.serialize())
    return FileHeader(allocated_page_count=count).serialize() + b"".join(frames)


@pytest.mark.parametrize("cut", [
    0, 1, 7, 8, FILE_HEADER_SIZE - 1, FILE_HEADER_SIZE,
    FILE_HEADER_SIZE + 1, FILE_HEADER_SIZE + PAGE_HEADER_SIZE,
    FILE_HEADER_SIZE + PAGE_HEADER_SIZE + SLOT_SIZE - 1,
    FILE_HEADER_SIZE + PAGE_SIZE - 1, FILE_HEADER_SIZE + PAGE_SIZE,
    FILE_HEADER_SIZE + PAGE_SIZE + PAGE_HEADER_SIZE - 1,
    FILE_HEADER_SIZE + 2 * PAGE_SIZE, FILE_HEADER_SIZE + 3 * PAGE_SIZE - 1,
])
def test_valid_multi_page_file_truncated_at_structural_boundaries_is_rejected(cut, tmp_path):
    path = tmp_path / "truncated.db"
    payload = valid_file_bytes()[:cut]
    path.write_bytes(payload)
    with pytest.raises(ValidationError) as error:
        PageManager.open(path)
    assert isinstance(error.value, DatabaseError)
    assert isinstance(error.value, ValueError)
    assert path.read_bytes() == payload


@pytest.mark.parametrize("byte_index", range(len(FILE_MAGIC)))
def test_every_magic_byte_is_validated_when_opening_a_populated_file(byte_index, tmp_path):
    payload = bytearray(valid_file_bytes())
    payload[byte_index] ^= 1
    path = tmp_path / "signature.db"
    path.write_bytes(payload)
    with pytest.raises(ValidationError, match="signature"):
        PageManager.open(path)
    assert path.read_bytes() == payload


@pytest.mark.parametrize("version,page_size,count", [
    (0, PAGE_SIZE, 3), (2, PAGE_SIZE, 3), (UINT32_MAX, PAGE_SIZE, 3),
    (1, 0, 3), (1, PAGE_SIZE - 1, 3), (1, PAGE_SIZE + 1, 3), (1, 8192, 3),
    (1, PAGE_SIZE, 0), (1, PAGE_SIZE, 2), (1, PAGE_SIZE, 4), (1, PAGE_SIZE, UINT32_MAX),
])
def test_incompatible_header_or_page_count_is_rejected_without_repair(version, page_size, count, tmp_path):
    payload = FILE_HEADER_STRUCT.pack(FILE_MAGIC, version, page_size, count) + valid_file_bytes()[20:]
    path = tmp_path / "incompatible.db"
    path.write_bytes(payload)
    with pytest.raises(ValidationError):
        PageManager.open(path)
    assert path.read_bytes() == payload


def assert_corrupted_seventh_page_rejected(payload, tmp_path):
    path = tmp_path / "corrupt-page.db"
    path.write_bytes(payload)
    with PageManager.open(path) as manager:
        assert manager.pages_read == 0
        with pytest.raises(ValidationError):
            manager.read_page(7)
        assert manager.pages_read == 1  # Complete transfer before validation.
        # Validation of the corrupt page does not damage or hide other pages.
        assert manager.read_page(0).read(0) == b"alpha"
        assert manager.read_page(8).read(1) == b"beta"
        assert manager.pages_read == 3
        assert manager.pages_written == manager.pages_allocated == 0
    assert path.read_bytes() == payload


@pytest.mark.parametrize("fields", INVALID_SLOT_FIELDS)
def test_disk_loader_reuses_in_memory_slot_corruption_cases(fields, tmp_path):
    payload = bytearray(valid_file_bytes(9))
    start = FILE_HEADER_SIZE + 7 * PAGE_SIZE + PAGE_HEADER_SIZE
    payload[start:start + SLOT_SIZE] = SLOT_STRUCT.pack(*fields)
    assert_corrupted_seventh_page_rejected(payload, tmp_path)


@pytest.mark.parametrize("fields", INVALID_PAGE_HEADER_FIELDS)
def test_disk_loader_reuses_in_memory_header_corruption_cases(fields, tmp_path):
    payload = bytearray(valid_file_bytes(9))
    start = FILE_HEADER_SIZE + 7 * PAGE_SIZE
    payload[start:start + PAGE_HEADER_SIZE] = PAGE_HEADER_STRUCT.pack(*fields)
    assert_corrupted_seventh_page_rejected(payload, tmp_path)


def test_overlapping_slots_are_rejected_after_loading_from_disk(tmp_path):
    payload = bytearray(valid_file_bytes(9))
    start = FILE_HEADER_SIZE + 7 * PAGE_SIZE + PAGE_HEADER_SIZE + SLOT_SIZE
    payload[start:start + SLOT_SIZE] = SLOT_STRUCT.pack(4092, 4, 1)
    assert_corrupted_seventh_page_rejected(payload, tmp_path)


@pytest.mark.parametrize("page_id", [-1, 3, 4, UINT32_MAX, UINT32_MAX + 1])
def test_reopened_file_rejects_unallocated_pages_without_transfers(page_id, tmp_path):
    path = tmp_path / "bounds.db"
    original = valid_file_bytes()
    path.write_bytes(original)
    with PageManager.open(path) as manager:
        with pytest.raises(InvalidReferenceError):
            manager.read_page(page_id)
        if 0 <= page_id <= UINT32_MAX:
            with pytest.raises(InvalidReferenceError):
                manager.write_page(Page(page_id))
        assert manager.pages_read == manager.pages_written == manager.pages_allocated == 0
    assert path.read_bytes() == original


@pytest.mark.parametrize("slot_id,error", [
    (-1, InvalidReferenceError), (2, InvalidReferenceError), (UINT32_MAX, InvalidReferenceError),
    (True, InvalidTypeError), (0.0, InvalidTypeError), ("0", InvalidTypeError),
])
def test_reconstructed_page_enforces_slot_lookup_and_delete_bounds(slot_id, error, tmp_path):
    path = tmp_path / "slots.db"
    original = valid_file_bytes()
    path.write_bytes(original)
    with PageManager.open(path) as manager:
        page = manager.read_page(1)
        before = page.serialize()
        for operation in (page.read, page.delete):
            with pytest.raises(error):
                operation(slot_id)
        assert page.serialize() == before
        assert manager.pages_read == 1
        assert manager.pages_written == 0
    assert path.read_bytes() == original
