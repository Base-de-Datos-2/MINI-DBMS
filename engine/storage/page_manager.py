"""Page file I/O with short per-handle latches, without a buffer pool."""

from dataclasses import replace
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import os
from pathlib import Path
from threading import RLock
from time import perf_counter
from uuid import uuid4

from engine.errors import InvalidReferenceError, InvalidTypeError, ReadOnlyError, ValidationError
from engine.storage.binary import FILE_HEADER_SIZE, FILE_MAGIC, PAGE_SIZE, SEALED_FORMAT_VERSION, UINT32_MAX
from engine.storage.file_header import FileHeader
from engine.storage.page import Page


_LATCH_OBSERVER = ContextVar("minidb_physical_latch_observer", default=None)
_PAGE_IO_OBSERVER = ContextVar("minidb_page_io_observer", default=None)

# In-process publication exclusion follows owner/coordinator lifetimes, not
# individual handles: an undo close/reopen must not permit sealing in between.
_publication_mutex = RLock()
_managed_roots: dict[Path, int] = {}
_policy_mutex = RLock()
_sealed_paths: set[Path] = set()


def register_managed_root(path):
    root = Path(path).resolve()
    with _publication_mutex:
        _managed_roots[root] = _managed_roots.get(root, 0) + 1
    return root


def unregister_managed_root(root):
    with _publication_mutex:
        count = _managed_roots.get(root, 0)
        if count <= 1:
            _managed_roots.pop(root, None)
        else:
            _managed_roots[root] = count - 1


@contextmanager
def physical_latch_scope(observer):
    token = _LATCH_OBSERVER.set(observer)
    try:
        yield
    finally:
        _LATCH_OBSERVER.reset(token)


@contextmanager
def page_io_scope(observer):
    token = _PAGE_IO_OBSERVER.set(observer)
    try:
        yield
    finally:
        _PAGE_IO_OBSERVER.reset(token)


def _record_physical_latch_wait(seconds: float, operation: str) -> None:
    observer = _LATCH_OBSERVER.get()
    if observer is not None:
        observer(max(0.0, seconds), operation)


def _record_page_io(manager: object, operation: str) -> None:
    observer = _PAGE_IO_OBSERVER.get()
    if observer is not None:
        observer(manager, operation)


def _latched(method):
    """Keep one physical operation, including seek and transfer, indivisible."""

    @wraps(method)
    def call(self, *args, **kwargs):
        started = perf_counter()
        self._mutex.acquire()
        _record_physical_latch_wait(
            perf_counter() - started,
            f"PageManager.{method.__name__}",
        )
        try:
            return method(self, *args, **kwargs)
        finally:
            self._mutex.release()

    return call


class PageManager:
    """Own an unbuffered binary handle; callers explicitly write modified Pages.

    create() is exclusive, open() never creates/truncates. Only one owner/writer
    is supported. A short reentrant latch protects shared handle offset,
    headers, counters, replacement and close. Logical transaction locks,
    WAL, recovery, checksums and page caching are separate concerns.
    flush()/close() request OS synchronization, not atomic multi-page commits.

    Counters measure completed page-sized transfers through this handle (not
    hardware cache misses). Headers, seeks, flushes and failed preconditions do
    not count. Allocation writes one empty page, thus increments both written
    and allocated. A fully read but malformed page still counts as a read.
    Partial transfers on failure do not count as completed page transfers.
    """

    def __init__(self, path: str | os.PathLike[str], *, create: bool = False) -> None:
        if not isinstance(path, (str, os.PathLike)):
            raise InvalidTypeError("path must be a string or text PathLike")
        if not isinstance(os.fspath(path), str):
            raise InvalidTypeError("path must be a text path, not bytes")
        if type(create) is not bool:
            raise InvalidTypeError("create must be a bool")
        self._mutex = RLock()
        self._path = Path(path).absolute()
        self._policy_path = self._path.resolve()
        self._pages_read = 0
        self._pages_written = 0
        self._pages_allocated = 0
        self._write_guard = None
        self._file = self._path.open("x+b" if create else "r+b", buffering=0)
        try:
            if create:
                self._header = FileHeader()
                self._write_at(0, self._header.serialize())
            else:
                self._header = FileHeader.deserialize(self._read_exact(FILE_HEADER_SIZE))
            with _policy_mutex:
                if create:
                    _sealed_paths.discard(self._policy_path)
                elif self._header.version == SEALED_FORMAT_VERSION:
                    _sealed_paths.add(self._policy_path)
            self._check_file_size()
        except BaseException:
            self._file.close()
            raise

    @classmethod
    def create(cls, path: str | os.PathLike[str]) -> "PageManager":
        """Create a new header-only file; existing paths raise FileExistsError."""
        return cls(path, create=True)

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "PageManager":
        """Validate an existing file's header/length; pages validate when read."""
        return cls(path)

    @property
    @_latched
    def read_only(self) -> bool:
        self._require_open()
        # A one-way policy needs no header read on every ordinary write. New
        # opens read disk; publication informs preexisting in-process aliases.
        # Concurrent cross-process writers remain outside the engine contract.
        with _policy_mutex:
            return self._header.version == SEALED_FORMAT_VERSION or self._policy_path in _sealed_paths

    @_latched
    def require_writable(self) -> None:
        if self.read_only:
            raise ReadOnlyError("Storage/index is sealed read-only")
        if self._write_guard is not None:
            self._write_guard()

    @staticmethod
    def require_mutable_path(path) -> None:
        """Reject physical undo of a sealed file, even with no live handle.

        Undo also owns non-page auxiliary files and repairs damaged mutable
        files. Only the recognized v2 seal marker is rejected here.
        """
        candidate = Path(path)
        with _policy_mutex:
            if candidate.resolve() in _sealed_paths:
                raise ReadOnlyError("Physical undo cannot capture or restore a sealed file")
        if not candidate.exists():
            return
        with candidate.open("rb") as stream:
            prefix = stream.read(FILE_HEADER_SIZE)
        if (prefix[:8] == FILE_MAGIC and len(prefix) >= 12
                and int.from_bytes(prefix[8:12], "little") == SEALED_FORMAT_VERSION):
            raise ReadOnlyError("Physical undo cannot capture or restore a sealed file")

    @_latched
    def bind_write_guard(self, guard) -> None:
        """Bind a borrowed base policy once; callers cannot remove/replace it."""
        if not callable(guard):
            raise InvalidTypeError("write guard must be callable")
        if self._write_guard is not None and self._write_guard != guard:
            raise ValidationError("A physical write guard cannot be replaced")
        self._write_guard = guard

    def require_offline_publication(self) -> None:
        with _publication_mutex:
            self.require_writable()
            if any(self._path.resolve().is_relative_to(root) for root in _managed_roots):
                raise ValidationError("Seal publication is offline-only; close the database owner/coordinator first")

    @contextmanager
    def offline_publication(self):
        """Exclude new owner/coordinator claims across the entire seal sequence.

        Queries and ordinary I/O do not take this admission latch. Always take
        it before a handle latch, including low-level single-file sealing.
        """
        with _publication_mutex:
            self.require_offline_publication()
            yield

    def seal(self, final_metadata_page: Page | None = None) -> None:
        """Freeze this file at v2, optionally finalizing organized page zero.

        No public unseal operation. Failure closes the handle; mixed metadata/
        header states fail closed on organized reopen. This is not crash undo.
        """
        with self.offline_publication(), self._mutex:
            if final_metadata_page is not None:
                if not isinstance(final_metadata_page, Page) or final_metadata_page.page_id != 0:
                    raise ValidationError("Final seal metadata must be page zero")
                self._require_allocated(0)
                payload = final_metadata_page.serialize()
            try:
                # Mark before the first publication write. Failure is closed
                # for every existing alias; mixed disk states must be rebuilt.
                with _policy_mutex:
                    _sealed_paths.add(self._policy_path)
                if final_metadata_page is not None:
                    self._write_at(self._physical_offset(0), payload)
                    self._pages_written += 1
                    _record_page_io(self, "write")
                self._header = replace(self._header, version=SEALED_FORMAT_VERSION)
                self._write_at(0, self._header.serialize())
                self.flush()
            except BaseException:
                self._file.close()
                raise

    @property
    @_latched
    def header(self) -> FileHeader:
        return self._header

    @property
    @_latched
    def path(self) -> Path:
        """Return the stable absolute path owned by this manager."""

        return self._path

    @property
    @_latched
    def allocated_page_count(self) -> int:
        return self._header.allocated_page_count

    @property
    @_latched
    def file_size(self) -> int:
        """Return the validated physical file size without changing counters."""

        self._require_open()
        return self._check_file_size()

    @property
    @_latched
    def closed(self) -> bool:
        return self._file.closed

    @property
    @_latched
    def pages_read(self) -> int:
        return self._pages_read

    @property
    @_latched
    def pages_written(self) -> int:
        return self._pages_written

    @property
    @_latched
    def pages_allocated(self) -> int:
        return self._pages_allocated

    @_latched
    def reset_counters(self) -> None:
        """Reset this open manager's session metrics, without touching the file."""
        self._require_open()
        self._pages_read = self._pages_written = self._pages_allocated = 0

    @contextmanager
    def counter_scope(self):
        """Attribute a short transfer and its counter delta to one adapter."""

        with self._mutex:
            yield

    @_latched
    def temporary_replacement_path(self) -> Path:
        """Return a unique, uncreated sibling path for a validated rewrite."""

        self._require_open()
        return self._path.with_name(
            f".{self._path.name}.{uuid4().hex}.replacement"
        )

    def _validate_replacement_path(self, path: object) -> Path:
        if not isinstance(path, (str, os.PathLike)):
            raise InvalidTypeError("replacement path must be a string or text PathLike")
        if not isinstance(os.fspath(path), str):
            raise InvalidTypeError("replacement path must be text, not bytes")
        candidate = Path(path).absolute()
        expected_prefix = f".{self._path.name}."
        if (
            candidate.parent != self._path.parent
            or not candidate.name.startswith(expected_prefix)
            or not candidate.name.endswith(".replacement")
            or candidate == self._path
        ):
            raise ValidationError("Invalid sibling replacement path")
        return candidate

    @_latched
    def discard_replacement(self, path: object) -> None:
        """Remove an uncommitted sibling candidate, if one exists."""

        candidate = self._validate_replacement_path(path)
        candidate.unlink(missing_ok=True)

    def _adopt_reopened_handle(self, reopened: "PageManager") -> None:
        self._path = reopened._path
        self._file = reopened._file
        self._header = reopened._header
        self._pages_read = reopened._pages_read
        self._pages_written = reopened._pages_written
        self._pages_allocated = reopened._pages_allocated

    @_latched
    def commit_replacement(self, path: object) -> None:
        """Atomically replace this file with a prevalidated sibling candidate.

        The current handle is closed before the same-directory ``os.replace``
        required by Windows. If close or replacement fails, the unchanged
        destination is reopened before the original exception is propagated.
        A successful commit also reopens this manager as a new I/O session.
        """

        self.require_writable()
        candidate = self._validate_replacement_path(path)
        destination = self._path
        try:
            self.close()
        except BaseException:
            self._adopt_reopened_handle(type(self).open(destination))
            raise
        try:
            os.replace(candidate, destination)
        except BaseException:
            self._adopt_reopened_handle(type(self).open(destination))
            raise
        self._adopt_reopened_handle(type(self).open(destination))

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("PageManager is closed")

    @staticmethod
    def _physical_offset(page_id: int) -> int:
        # Also used with page_count to compute the expected end of the file.
        return FILE_HEADER_SIZE + page_id * PAGE_SIZE

    def _check_file_size(self) -> int:
        expected = self._physical_offset(self.allocated_page_count)
        actual = os.fstat(self._file.fileno()).st_size
        if actual != expected:
            raise ValidationError(
                f"Database file length mismatch: expected {expected} bytes, found {actual}"
            )
        return actual

    def _require_allocated(self, page_id: int) -> None:
        if type(page_id) is not int:
            raise InvalidTypeError("page_id must be a built-in int")
        if not 0 <= page_id < self.allocated_page_count:
            raise InvalidReferenceError(f"Unallocated page_id: {page_id}")

    def _read_exact(self, size: int) -> bytes:
        payload = bytearray()
        while len(payload) < size:
            chunk = self._file.read(size - len(payload))
            if not chunk:
                raise ValidationError(f"Truncated file: expected {size} bytes, read {len(payload)}")
            payload.extend(chunk)
        return bytes(payload)

    def _write_at(self, offset: int, payload: bytes) -> None:
        """Complete short writes; fail closed if an I/O operation fails.

        A failed write can leave partial data on disk. Do not keep using this
        handle or pretend allocation was committed; crash recovery is out of scope.
        """
        try:
            self._file.seek(offset)
            remaining = memoryview(payload)
            while remaining:
                written = self._file.write(remaining)
                if written is None or written <= 0:
                    raise OSError("File write made no progress")
                remaining = remaining[written:]
        except BaseException:
            self._file.close()
            raise

    @_latched
    def allocate_page(self) -> int:
        """Append a valid empty page and update the header, returning its id.

        No search for free space, page recycling or implicit record insertion.
        A full uint32 page count raises ValidationError without allocating.
        """
        self.require_writable()
        page_id = self.allocated_page_count
        if page_id == UINT32_MAX:
            raise ValidationError("Allocated page count has reached the uint32 limit")
        self._check_file_size()
        updated_header = replace(self._header, allocated_page_count=page_id + 1)
        self._write_at(self._physical_offset(page_id), Page(page_id).serialize())
        self._pages_written += 1
        _record_page_io(self, "write")
        self._write_at(0, updated_header.serialize())
        self._header = updated_header
        self._pages_allocated += 1
        return page_id

    @_latched
    def read_page(self, page_id: int) -> Page:
        """Read a fresh Page; reject unallocated ids and malformed physical data."""
        self._require_open()
        self._require_allocated(page_id)
        self._check_file_size()
        self._file.seek(self._physical_offset(page_id))
        payload = self._read_exact(PAGE_SIZE)
        self._pages_read += 1
        _record_page_io(self, "read")
        page = Page.deserialize(payload)
        if page.page_id != page_id:
            raise ValidationError(
                f"Stored page_id {page.page_id} does not match physical page_id {page_id}"
            )
        return page

    @_latched
    def write_page(self, page: Page) -> None:
        """Rewrite one allocated page; reject invalid data before touching disk."""
        self.require_writable()
        if not isinstance(page, Page):
            raise InvalidTypeError("page must be a Page")
        page_id = page.page_id
        self._require_allocated(page_id)
        payload = page.serialize()
        self._check_file_size()
        self._write_at(self._physical_offset(page_id), payload)
        self._pages_written += 1
        _record_page_io(self, "write")

    @_latched
    def flush(self) -> None:
        """Request synchronization of prior writes, including the file header."""
        self._require_open()
        self._file.flush()
        os.fsync(self._file.fileno())

    @_latched
    def close(self) -> None:
        """Flush and release the handle; idempotent, even after a failed write."""
        if not self.closed:
            try:
                self.flush()
            finally:
                self._file.close()

    @_latched
    def __enter__(self) -> "PageManager":
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
