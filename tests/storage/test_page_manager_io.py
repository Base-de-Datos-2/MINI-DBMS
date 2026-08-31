"""Short-transfer and failure accounting using a wrapper around real temp files."""

import pytest

from engine.errors import ValidationError
from engine.storage import FileHeader, Page, PageManager
from engine.storage.binary import FILE_HEADER_SIZE, PAGE_SIZE


class FileProbe:
    """Test-only handle wrapper: limit chunks and inject errors, no DBMS logic."""

    def __init__(self, handle, *, chunk_size=97, write_budget=None, read_budget=None,
                 fail_header=False, no_write_progress=False):
        self.handle = handle
        self.chunk_size = chunk_size
        self.write_budget = write_budget
        self.read_budget = read_budget
        self.fail_header = fail_header
        self.no_write_progress = no_write_progress
        self.bytes_read = 0
        self.bytes_written = 0

    def __getattr__(self, name):
        return getattr(self.handle, name)

    def read(self, size):
        if self.read_budget == 0:
            return b""
        size = min(size, self.chunk_size)
        if self.read_budget is not None:
            size = min(size, self.read_budget)
        payload = self.handle.read(size)
        self.bytes_read += len(payload)
        if self.read_budget is not None:
            self.read_budget -= len(payload)
        return payload

    def write(self, payload):
        if self.fail_header and self.handle.tell() < FILE_HEADER_SIZE:
            raise OSError("injected header write failure")
        if self.write_budget == 0:
            raise OSError("injected partial write failure")
        if self.no_write_progress:
            return 0
        size = min(len(payload), self.chunk_size)
        if self.write_budget is not None:
            size = min(size, self.write_budget)
        written = self.handle.write(payload[:size])
        self.bytes_written += written
        if self.write_budget is not None:
            self.write_budget -= written
        return written


def test_short_transfers_are_completed_and_counted_once_per_whole_page(tmp_path):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        probe = FileProbe(manager._file)
        manager._file = probe
        assert manager.allocate_page() == 0
        page = manager.read_page(0)
        page.insert(b"row")
        manager.write_page(page)
        assert manager.read_page(0).read(0) == b"row"
        assert probe.bytes_read == 2 * PAGE_SIZE
        assert probe.bytes_written == 2 * PAGE_SIZE + FILE_HEADER_SIZE
        assert manager.pages_read == 2
        assert manager.pages_written == 2
        assert manager.pages_allocated == 1
    with PageManager.open(path) as reopened:
        assert reopened.read_page(0).read(0) == b"row"


@pytest.mark.parametrize("operation", ["allocate", "write"])
def test_partial_page_write_closes_handle_and_does_not_count_complete_transfer(operation, tmp_path):
    manager = PageManager.create(tmp_path / "database.db")
    try:
        if operation == "write":
            manager.allocate_page()
        original_count = manager.allocated_page_count
        manager.reset_counters()
        probe = FileProbe(manager._file, write_budget=100)
        manager._file = probe
        with pytest.raises(OSError, match="partial write failure"):
            if operation == "allocate":
                manager.allocate_page()
            else:
                manager.write_page(Page(0))
        assert probe.bytes_written == 100
        assert manager.closed
        assert manager.pages_written == manager.pages_allocated == 0
        assert manager.allocated_page_count == original_count
        with pytest.raises(RuntimeError, match="closed"):
            manager.allocate_page()
    finally:
        manager.close()


def test_failed_header_update_counts_written_page_but_not_successful_allocation(tmp_path):
    path = tmp_path / "database.db"
    manager = PageManager.create(path)
    try:
        manager._file = FileProbe(manager._file, fail_header=True)
        with pytest.raises(OSError, match="header write failure"):
            manager.allocate_page()
        assert manager.closed
        assert manager.pages_written == 1
        assert manager.pages_read == manager.pages_allocated == 0
        assert manager.allocated_page_count == 0
        assert path.stat().st_size == FILE_HEADER_SIZE + PAGE_SIZE
        assert FileHeader.deserialize(path.read_bytes()[:20]).allocated_page_count == 0
        # No recovery/rollback claim: a failed append can leave an inconsistent file.
        with pytest.raises(ValidationError, match="length mismatch"):
            PageManager.open(path)
    finally:
        manager.close()


def test_write_without_progress_raises_instead_of_looping(tmp_path):
    manager = PageManager.create(tmp_path / "database.db")
    try:
        manager._file = FileProbe(manager._file, no_write_progress=True)
        with pytest.raises(OSError, match="no progress"):
            manager.allocate_page()
        assert manager.closed
        assert manager.pages_written == manager.pages_allocated == 0
    finally:
        manager.close()


def test_truncated_transfer_after_size_check_is_not_counted_as_a_page_read(tmp_path):
    with PageManager.create(tmp_path / "database.db") as manager:
        manager.allocate_page()
        manager._file = FileProbe(manager._file, read_budget=100)
        with pytest.raises(ValidationError, match="Truncated file"):
            manager.read_page(0)
        assert manager.pages_read == 0
        assert manager._file.bytes_read == 100


@pytest.mark.parametrize("operation", ["read", "write", "allocate"])
@pytest.mark.parametrize("size_change", [-1, 1])
def test_changed_file_length_is_rejected_before_page_io(operation, size_change, tmp_path):
    path = tmp_path / "database.db"
    with PageManager.create(path) as manager:
        manager.allocate_page()
        manager._file.truncate(FILE_HEADER_SIZE + PAGE_SIZE + size_change)
        manager.reset_counters()
        before = path.read_bytes()
        with pytest.raises(ValidationError, match="length mismatch"):
            if operation == "read":
                manager.read_page(0)
            elif operation == "write":
                manager.write_page(Page(0))
            else:
                manager.allocate_page()
        assert path.read_bytes() == before
        assert manager.pages_read == manager.pages_written == manager.pages_allocated == 0


def test_failed_create_closes_its_handle_without_reporting_success(tmp_path, monkeypatch):
    from pathlib import Path

    original_open = Path.open
    probes = []

    def faulty_open(self, *args, **kwargs):
        probe = FileProbe(original_open(self, *args, **kwargs), write_budget=5)
        probes.append(probe)
        return probe

    path = tmp_path / "database.db"
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", faulty_open)
        with pytest.raises(OSError, match="partial write failure"):
            PageManager.create(path)
    assert probes[0].closed
    assert path.stat().st_size == 5  # Failure may leave this newly created partial file.
    with pytest.raises(ValidationError):
        PageManager.open(path)


def test_native_read_error_propagates_without_counter_increment(tmp_path, monkeypatch):
    with PageManager.create(tmp_path / "database.db") as manager:
        manager.allocate_page()
        probe = FileProbe(manager._file)
        manager._file = probe

        def fail(size):
            raise OSError("injected read failure")

        monkeypatch.setattr(probe, "read", fail)
        with pytest.raises(OSError, match="injected read failure"):
            manager.read_page(0)
        assert manager.pages_read == 0
