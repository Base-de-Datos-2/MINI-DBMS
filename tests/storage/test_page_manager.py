"""Page-level disk operations in disposable files, never a record storage engine."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from engine.errors import InvalidReferenceError, InvalidTypeError, ValidationError
from engine.storage import FileHeader, Page, PageManager
from engine.storage.binary import FILE_HEADER_SIZE, FILE_HEADER_STRUCT, FILE_MAGIC, PAGE_SIZE, UINT32_MAX


def counters(manager):
    return manager.pages_read, manager.pages_written, manager.pages_allocated


def test_create_and_reopen_header_only_file(tmp_path):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        assert not manager.closed
        assert manager.path == path.absolute()
        assert manager.header == FileHeader()
        assert manager.allocated_page_count == 0
        assert path.read_bytes() == FileHeader().serialize()
        assert counters(manager) == (0, 0, 0)
    assert manager.closed
    with PageManager.open(str(path)) as reopened:
        assert reopened.path == path.absolute()
        assert reopened.header == FileHeader()
        assert counters(reopened) == (0, 0, 0)


def test_create_never_overwrites_an_existing_path(tmp_path):
    path = tmp_path / "existing.db"
    original = b"existing user data"
    path.write_bytes(original)
    with pytest.raises(FileExistsError):
        PageManager.create(path)
    assert path.read_bytes() == original


def test_open_never_creates_a_missing_file(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        PageManager.open(path)
    assert not path.exists()


def test_create_does_not_silently_create_parent_directories(tmp_path):
    path = tmp_path / "missing" / "database.db"
    with pytest.raises(FileNotFoundError):
        PageManager.create(path)
    assert not path.parent.exists()


@pytest.mark.parametrize("path", [None, True, 1, 1.0, b"database.db", []])
@pytest.mark.parametrize("method", ["create", "open"])
def test_paths_reject_invalid_types_without_opening_files(path, method, no_file_io):
    with no_file_io(), pytest.raises(InvalidTypeError):
        getattr(PageManager, method)(path)


def test_pathlike_returning_bytes_is_rejected(no_file_io):
    class BytesPath:
        def __fspath__(self):
            return b"database.db"

    with no_file_io(), pytest.raises(InvalidTypeError):
        PageManager.create(BytesPath())


def test_constructor_rejects_non_boolean_create_flag(tmp_path):
    with pytest.raises(InvalidTypeError):
        PageManager(tmp_path / "database.db", create=1)
    assert not list(tmp_path.iterdir())


def test_allocation_initializes_consecutive_pages_at_exact_offsets(tmp_path):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        original_header = manager.header
        for page_id in range(4):
            assert manager.allocate_page() == page_id
            assert manager.allocated_page_count == page_id + 1
            assert path.stat().st_size == FILE_HEADER_SIZE + (page_id + 1) * PAGE_SIZE
            raw = path.read_bytes()
            assert FileHeader.deserialize(raw[:20]) == manager.header
            assert raw[20 + page_id * PAGE_SIZE:] == Page(page_id).serialize()
        assert original_header.allocated_page_count == 0
        with pytest.raises(FrozenInstanceError):
            manager.header.allocated_page_count = 9
        assert counters(manager) == (0, 4, 4)
        for page_id in reversed(range(4)):
            assert manager.read_page(page_id).serialize() == Page(page_id).serialize()
        assert counters(manager) == (4, 4, 4)
    with PageManager.open(path) as reopened:
        assert reopened.allocated_page_count == 4
        assert reopened.allocate_page() == 4
        assert counters(reopened) == (0, 1, 1)


def test_write_rewrite_flush_and_reopen_preserve_neighboring_pages(tmp_path):
    path = tmp_path / "database.db"
    expected = {}
    with PageManager.create(path) as manager:
        for _ in range(3):
            page_id = manager.allocate_page()
            page = manager.read_page(page_id)
            page.insert(bytes([page_id]) * 1200)
            page.insert(b"keep" + bytes([page_id]))
            manager.write_page(page)
            expected[page_id] = page.serialize()
        middle = manager.read_page(1)
        middle.delete(0)
        middle.compact()
        assert middle.insert(b"replacement" * 100) == 0
        manager.write_page(middle)
        expected[1] = middle.serialize()
        manager.flush()
        assert path.stat().st_size == 20 + 3 * PAGE_SIZE
        for page_id in (2, 0, 1):
            assert manager.read_page(page_id).serialize() == expected[page_id]
    with PageManager.open(path) as reopened:
        assert reopened.allocated_page_count == 3
        for page_id in (1, 2, 0):
            assert reopened.read_page(page_id).serialize() == expected[page_id]


def test_pages_are_independent_copies_and_changes_require_write_page(tmp_path):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        page_id = manager.allocate_page()
        page = manager.read_page(page_id)
        page.insert(b"local only")
        assert manager.read_page(page_id).slot_count == 0
        manager.write_page(page)
        page.delete(0)
        assert manager.read_page(page_id).read(0) == b"local only"
        assert counters(manager) == (3, 2, 1)
    with PageManager.open(path) as reopened:
        assert reopened.read_page(page_id).read(0) == b"local only"


@pytest.mark.parametrize("page_id", [-1, 1, 2, UINT32_MAX, UINT32_MAX + 1, 2**100])
def test_read_rejects_unallocated_page_ids_without_io(page_id, tmp_path):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        manager.allocate_page()
        before = path.read_bytes()
        with pytest.raises(InvalidReferenceError):
            manager.read_page(page_id)
        assert counters(manager) == (0, 1, 1)
        assert path.read_bytes() == before


@pytest.mark.parametrize("page_id", [True, False, 0.0, "0", None])
def test_read_rejects_non_integer_page_ids(page_id, tmp_path):
    with PageManager.create(tmp_path / "database.db") as manager:
        with pytest.raises(InvalidTypeError):
            manager.read_page(page_id)
        assert counters(manager) == (0, 0, 0)


def test_empty_file_has_no_page_zero_until_allocation(tmp_path):
    with PageManager.create(tmp_path / "database.db") as manager:
        for operation in (lambda: manager.read_page(0), lambda: manager.write_page(Page(0))):
            with pytest.raises(InvalidReferenceError):
                operation()
        assert counters(manager) == (0, 0, 0)


@pytest.mark.parametrize("value", [None, b"", 0, "page", object()])
def test_write_requires_page_instance(value, tmp_path):
    with PageManager.create(tmp_path / "database.db") as manager:
        with pytest.raises(InvalidTypeError):
            manager.write_page(value)
        assert counters(manager) == (0, 0, 0)


@pytest.mark.parametrize("page_id", [1, 2, UINT32_MAX])
def test_write_does_not_implicitly_allocate_or_extend_file(page_id, tmp_path):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        manager.allocate_page()
        before = path.read_bytes()
        with pytest.raises(InvalidReferenceError):
            manager.write_page(Page(page_id))
        assert path.read_bytes() == before
        assert counters(manager) == (0, 1, 1)


def test_invalid_page_metadata_is_rejected_without_overwriting_disk(tmp_path):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        manager.allocate_page()
        page = manager.read_page(0)
        page.insert(b"valid")
        manager.write_page(page)
        before = path.read_bytes()
        page._data[16] = 2  # Invalid first-slot state.
        with pytest.raises(ValidationError):
            manager.write_page(page)
        assert path.read_bytes() == before
        assert counters(manager) == (1, 2, 1)


@pytest.mark.parametrize(
    "payload",
    [b"", bytes(19), bytes(20),
     FILE_HEADER_STRUCT.pack(b"WRONG!!!", 1, PAGE_SIZE, 0),
     FILE_HEADER_STRUCT.pack(FILE_MAGIC, 2, PAGE_SIZE, 0),
     FILE_HEADER_STRUCT.pack(FILE_MAGIC, 1, 8192, 0),
     FileHeader(allocated_page_count=1).serialize(),
     FileHeader(allocated_page_count=1).serialize() + bytes(PAGE_SIZE - 1),
     FileHeader().serialize() + Page(0).serialize(),
     FileHeader().serialize() + b"extra",
     FileHeader(allocated_page_count=UINT32_MAX).serialize()],
)
def test_open_rejects_malformed_files_and_closes_handle(payload, tmp_path, monkeypatch):
    path = tmp_path / "database.db"
    path.write_bytes(payload)
    handles = []
    original_open = Path.open

    def track_open(self, *args, **kwargs):
        handle = original_open(self, *args, **kwargs)
        handles.append(handle)
        return handle

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", track_open)
        with pytest.raises(ValidationError):
            PageManager.open(path)
    assert len(handles) == 1
    assert handles[0].closed
    assert path.read_bytes() == payload


@pytest.mark.parametrize("corruption", ["identity", "slot", "header"])
def test_page_corruption_is_detected_on_read_and_full_transfer_is_counted(corruption, tmp_path):
    path = tmp_path / "database.db"
    page = Page(0)
    page.insert(b"payload")
    raw = bytearray(page.serialize())
    if corruption == "identity":
        raw[0:4] = (1).to_bytes(4, "little")
    elif corruption == "slot":
        raw[16] = 2
    else:
        raw[6:8] = (12).to_bytes(2, "little")
    path.write_bytes(FileHeader(allocated_page_count=1).serialize() + raw)
    with PageManager.open(path) as manager:
        assert counters(manager) == (0, 0, 0)  # Open does not eagerly read data pages.
        with pytest.raises(ValidationError):
            manager.read_page(0)
        assert counters(manager) == (1, 0, 0)


def test_counters_reflect_actual_transfers_and_reset_only_session_metrics(tmp_path):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        manager.allocate_page()
        assert counters(manager) == (0, 1, 1)
        first = manager.read_page(0)
        manager.read_page(0)  # No cache: a second physical file read.
        assert counters(manager) == (2, 1, 1)
        first.insert(b"in memory")
        first.compact()
        assert counters(manager) == (2, 1, 1)
        manager.write_page(first)
        manager.write_page(first)  # Identical bytes still involve another write.
        assert counters(manager) == (2, 3, 1)
        manager.flush()
        assert counters(manager) == (2, 3, 1)
        before = path.read_bytes()
        manager.reset_counters()
        assert counters(manager) == (0, 0, 0)
        assert path.read_bytes() == before
        assert manager.allocated_page_count == 1
        with pytest.raises(AttributeError):
            manager.pages_read = 100
        manager.allocate_page()
        assert counters(manager) == (0, 1, 1)
    assert counters(manager) == (0, 1, 1)  # Inspection remains valid after close.
    with PageManager.open(path) as reopened:
        assert counters(reopened) == (0, 0, 0)
        assert reopened.allocated_page_count == 2


def test_allocation_limit_is_checked_before_io_without_creating_huge_file(tmp_path, monkeypatch):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        monkeypatch.setattr(manager, "_header", FileHeader(allocated_page_count=UINT32_MAX))
        with pytest.raises(ValidationError, match="uint32 limit"):
            manager.allocate_page()
        assert path.read_bytes() == FileHeader().serialize()
        assert counters(manager) == (0, 0, 0)


def test_close_is_idempotent_and_reopen_requires_a_new_manager(tmp_path):
    path = tmp_path / "database.db"
    manager = PageManager.create(path)
    manager.close()
    manager.close()
    assert manager.closed
    operations = [manager.allocate_page, lambda: manager.read_page(0),
                  lambda: manager.write_page(Page(0)), manager.flush,
                  manager.reset_counters, manager.__enter__]
    for operation in operations:
        with pytest.raises(RuntimeError, match="closed"):
            operation()
    with PageManager.open(path) as reopened:
        assert reopened.allocate_page() == 0


def test_context_manager_closes_on_exception_without_suppressing_it(tmp_path):
    with pytest.raises(RuntimeError, match="caller failed"):
        with PageManager.create(tmp_path / "database.db") as manager:
            raise RuntimeError("caller failed")
    assert manager.closed


def test_commit_validated_sibling_replacement_reopens_same_manager(tmp_path):
    path = tmp_path / "database.db"
    manager = PageManager.create(path)
    manager.allocate_page()
    original_page = Page(0)
    original_page.insert(b"original")
    manager.write_page(original_page)

    candidate_path = manager.temporary_replacement_path()
    with PageManager.create(candidate_path) as candidate:
        candidate.allocate_page()
        replacement_page = Page(0)
        replacement_page.insert(b"replacement")
        candidate.write_page(replacement_page)

    manager.commit_replacement(candidate_path)

    assert not manager.closed
    assert manager.path == path.absolute()
    assert manager.read_page(0).read(0) == b"replacement"
    assert not candidate_path.exists()
    manager.close()


def test_replacement_helpers_reject_unrelated_paths(tmp_path):
    path = tmp_path / "database.db"
    unrelated = tmp_path / "unrelated.db"
    unrelated.write_bytes(b"keep")
    with PageManager.create(path) as manager:
        with pytest.raises(ValidationError, match="sibling replacement"):
            manager.commit_replacement(unrelated)
        with pytest.raises(ValidationError, match="sibling replacement"):
            manager.discard_replacement(unrelated)
        assert unrelated.read_bytes() == b"keep"


def test_flush_calls_fsync_and_close_releases_handle_even_if_fsync_fails(tmp_path, monkeypatch):
    manager = PageManager.create(tmp_path / "database.db")
    calls = []

    def fsync(descriptor):
        calls.append(descriptor)

    monkeypatch.setattr("engine.storage.page_manager.os.fsync", fsync)
    manager.flush()
    assert calls == [manager._file.fileno()]

    def fail(descriptor):
        raise OSError("sync failed")

    monkeypatch.setattr("engine.storage.page_manager.os.fsync", fail)
    with pytest.raises(OSError, match="sync failed"):
        manager.close()
    assert manager.closed
    manager.close()
