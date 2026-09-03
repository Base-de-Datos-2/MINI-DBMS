"""Single-owner page file I/O, without a buffer pool or record-level policies."""

from dataclasses import replace
import os
from pathlib import Path
from uuid import uuid4

from engine.errors import InvalidReferenceError, InvalidTypeError, ValidationError
from engine.storage.binary import FILE_HEADER_SIZE, PAGE_SIZE, UINT32_MAX
from engine.storage.file_header import FileHeader
from engine.storage.page import Page


class PageManager:
    """Own an unbuffered binary handle; callers explicitly write modified Pages.

    create() is exclusive, open() never creates/truncates. Only one owner/writer
    is supported; there are no locks, WAL, recovery, checksums or page cache.
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
        self._path = Path(path).absolute()
        self._pages_read = 0
        self._pages_written = 0
        self._pages_allocated = 0
        self._file = self._path.open("x+b" if create else "r+b", buffering=0)
        try:
            if create:
                self._header = FileHeader()
                self._write_at(0, self._header.serialize())
            else:
                self._header = FileHeader.deserialize(self._read_exact(FILE_HEADER_SIZE))
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
    def header(self) -> FileHeader:
        return self._header

    @property
    def path(self) -> Path:
        """Return the stable absolute path owned by this manager."""

        return self._path

    @property
    def allocated_page_count(self) -> int:
        return self._header.allocated_page_count

    @property
    def closed(self) -> bool:
        return self._file.closed

    @property
    def pages_read(self) -> int:
        return self._pages_read

    @property
    def pages_written(self) -> int:
        return self._pages_written

    @property
    def pages_allocated(self) -> int:
        return self._pages_allocated

    def reset_counters(self) -> None:
        """Reset this open manager's session metrics, without touching the file."""
        self._require_open()
        self._pages_read = self._pages_written = self._pages_allocated = 0

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

    def commit_replacement(self, path: object) -> None:
        """Atomically replace this file with a prevalidated sibling candidate.

        The current handle is closed before the same-directory ``os.replace``
        required by Windows. If close or replacement fails, the unchanged
        destination is reopened before the original exception is propagated.
        A successful commit also reopens this manager as a new I/O session.
        """

        self._require_open()
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

    def _check_file_size(self) -> None:
        expected = self._physical_offset(self.allocated_page_count)
        actual = os.fstat(self._file.fileno()).st_size
        if actual != expected:
            raise ValidationError(
                f"Database file length mismatch: expected {expected} bytes, found {actual}"
            )

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

    def allocate_page(self) -> int:
        """Append a valid empty page and update the header, returning its id.

        No search for free space, page recycling or implicit record insertion.
        A full uint32 page count raises ValidationError without allocating.
        """
        self._require_open()
        page_id = self.allocated_page_count
        if page_id == UINT32_MAX:
            raise ValidationError("Allocated page count has reached the uint32 limit")
        self._check_file_size()
        updated_header = replace(self._header, allocated_page_count=page_id + 1)
        self._write_at(self._physical_offset(page_id), Page(page_id).serialize())
        self._pages_written += 1
        self._write_at(0, updated_header.serialize())
        self._header = updated_header
        self._pages_allocated += 1
        return page_id

    def read_page(self, page_id: int) -> Page:
        """Read a fresh Page; reject unallocated ids and malformed physical data."""
        self._require_open()
        self._require_allocated(page_id)
        self._check_file_size()
        self._file.seek(self._physical_offset(page_id))
        payload = self._read_exact(PAGE_SIZE)
        self._pages_read += 1
        page = Page.deserialize(payload)
        if page.page_id != page_id:
            raise ValidationError(
                f"Stored page_id {page.page_id} does not match physical page_id {page_id}"
            )
        return page

    def write_page(self, page: Page) -> None:
        """Rewrite one allocated page; reject invalid data before touching disk."""
        self._require_open()
        if not isinstance(page, Page):
            raise InvalidTypeError("page must be a Page")
        page_id = page.page_id
        self._require_allocated(page_id)
        payload = page.serialize()
        self._check_file_size()
        self._write_at(self._physical_offset(page_id), payload)
        self._pages_written += 1

    def flush(self) -> None:
        """Request synchronization of prior writes, including the file header."""
        self._require_open()
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        """Flush and release the handle; idempotent, even after a failed write."""
        if not self.closed:
            try:
                self.flush()
            finally:
                self._file.close()

    def __enter__(self) -> "PageManager":
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
