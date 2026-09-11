"""Schema-aware paged temporary row streams for spilled intermediate results."""

from __future__ import annotations

from dataclasses import dataclass
import json

from engine.catalog import Column, DataType, Schema
from engine.errors import (
    InvalidTypeError,
    SchemaError,
    ValidationError,
)
from engine.storage.binary import MAX_RECORD_SIZE, PAGE_SIZE, VARCHAR_LENGTH_STRUCT
from engine.storage.page import Page
from engine.storage.page_manager import PageManager
from engine.storage.record import Record
from engine.storage.record_codec import RecordCodec

from .temp_files import TemporaryWorkspace


#: Identifier stored in the descriptor page of every temporary row stream.
TEMPORARY_MAGIC = "MINIDB-TEMPROWS"

#: Version of the temporary framing. A mismatch is rejected, never guessed.
TEMPORARY_VERSION = 1

#: Bytes of stream payload carried by one physical page.
CHUNK_PAYLOAD_SIZE = MAX_RECORD_SIZE

#: Width of the per-row length prefix inside the byte stream.
ROW_LENGTH_SIZE = VARCHAR_LENGTH_STRUCT.size

#: Largest single execution row a temporary stream accepts. Rows span pages, so
#: this is not a page limit; it bounds the buffer a corrupt length prefix could
#: otherwise ask for. A joined row built from two base records stays far below.
MAX_TEMPORARY_ROW_BYTES = 16 * PAGE_SIZE

DESCRIPTOR_PAGE_ID = 0
DESCRIPTOR_SLOT_ID = 0


@dataclass(frozen=True, slots=True)
class TemporaryRun:
    """A completed temporary stream: a small descriptor, never its rows.

    Run descriptors stay this size no matter how many rows a run holds, so a
    sort with many runs keeps bounded metadata in memory.
    """

    path: object
    schema: Schema
    row_count: int
    byte_length: int
    page_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.schema, Schema):
            raise InvalidTypeError("A temporary run requires a Schema")
        for name in ("row_count", "byte_length", "page_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValidationError(f"Temporary run {name} must be non-negative")


def _encode_descriptor(schema: Schema, row_count: int, byte_length: int) -> bytes:
    document = {
        "byte_length": byte_length,
        "magic": TEMPORARY_MAGIC,
        "row_count": row_count,
        "schema": [[column.name, column.data_type.value] for column in schema],
        "version": TEMPORARY_VERSION,
    }
    payload = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(payload) > MAX_RECORD_SIZE:
        raise ValidationError(
            "Temporary stream descriptor does not fit in one page slot"
        )
    return payload


def _decode_descriptor(payload: bytes) -> tuple[Schema, int, int]:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError("Temporary stream descriptor is not valid JSON") from error
    if type(document) is not dict:
        raise ValidationError("Temporary stream descriptor must be a JSON object")
    if document.get("magic") != TEMPORARY_MAGIC:
        raise ValidationError("File is not a temporary row stream")
    if document.get("version") != TEMPORARY_VERSION:
        raise ValidationError(
            f"Unsupported temporary stream version: {document.get('version')!r}"
        )
    columns_document = document.get("schema")
    if type(columns_document) is not list:
        raise ValidationError("Temporary stream schema must be encoded as a list")
    columns: list[Column] = []
    for descriptor in columns_document:
        if type(descriptor) is not list or len(descriptor) != 2:
            raise ValidationError(
                "Each temporary schema column must be a [name, type] pair"
            )
        name, type_name = descriptor
        if type(name) is not str or type(type_name) is not str:
            raise InvalidTypeError("Temporary schema entries must be strings")
        try:
            columns.append(Column(name, DataType(type_name)))
        except ValueError as error:
            raise SchemaError(
                f"Unknown temporary data type: {type_name!r}"
            ) from error
    for name in ("row_count", "byte_length"):
        value = document.get(name)
        if type(value) is not int or value < 0:
            raise ValidationError(f"Temporary stream {name} must be a non-negative int")
    return Schema(columns), document["row_count"], document["byte_length"]


class TemporaryRowWriter:
    """Append execution rows to one temporary stream with a single page buffer.

    Rows are framed into a continuous byte stream and cut into page-sized
    chunks, so a row wider than a page spans pages instead of being truncated
    or rejected. Buffering is bounded to one chunk regardless of row count.

    All I/O goes through PageManager, so temporary work appears in the same
    page counters as base storage rather than hiding from them.
    """

    __slots__ = ("_workspace", "_path", "_schema", "_manager", "_buffer",
                 "_row_count", "_byte_length", "_page_count", "_finished")

    def __init__(
        self,
        workspace: TemporaryWorkspace,
        schema: Schema,
        *,
        label: str = "run",
    ) -> None:
        if not isinstance(workspace, TemporaryWorkspace):
            raise InvalidTypeError("A temporary writer requires a TemporaryWorkspace")
        if not isinstance(schema, Schema):
            raise InvalidTypeError("A temporary writer requires a Schema")
        self._workspace = workspace
        self._schema = schema
        self._path = workspace.allocate(label)
        self._buffer = bytearray()
        self._row_count = 0
        self._byte_length = 0
        self._page_count = 0
        self._finished = False
        self._manager = PageManager.create(self._path)
        try:
            allocated = self._manager.allocate_page()
            if allocated != DESCRIPTOR_PAGE_ID:
                raise ValidationError("Temporary stream descriptor page must be page 0")
        except BaseException:
            self._manager.close()
            workspace.discard(self._path)
            raise

    @property
    def path(self) -> object:
        """Return the workspace-owned path being written."""

        return self._path

    @property
    def schema(self) -> Schema:
        """Return the schema every written row must match."""

        return self._schema

    @property
    def row_count(self) -> int:
        """Return how many rows have been written so far."""

        return self._row_count

    @property
    def pages_written(self) -> int:
        """Return the real page writes performed by this writer."""

        return self._manager.pages_written if not self._manager.closed else 0

    def write(self, record: Record) -> None:
        """Frame one row into the stream, flushing whole pages as they fill."""

        if self._finished:
            raise RuntimeError("A finished temporary writer cannot accept rows")
        if not isinstance(record, Record):
            raise InvalidTypeError("A temporary writer requires a Record")
        if record.schema != self._schema:
            raise SchemaError("Row schema differs from the temporary stream schema")
        payload = RecordCodec.serialize(record)
        if len(payload) > MAX_TEMPORARY_ROW_BYTES:
            raise ValidationError(
                f"Execution row of {len(payload)} bytes exceeds the temporary "
                f"maximum of {MAX_TEMPORARY_ROW_BYTES} bytes"
            )
        self._buffer += VARCHAR_LENGTH_STRUCT.pack(len(payload))
        self._buffer += payload
        self._row_count += 1
        self._byte_length += ROW_LENGTH_SIZE + len(payload)
        while len(self._buffer) >= CHUNK_PAYLOAD_SIZE:
            self._flush_chunk(CHUNK_PAYLOAD_SIZE)

    def _flush_chunk(self, size: int) -> None:
        chunk = bytes(self._buffer[:size])
        del self._buffer[:size]
        page_id = self._manager.allocate_page()
        page = Page(page_id)
        page.insert(chunk)
        self._manager.write_page(page)
        self._page_count += 1

    def finish(self) -> TemporaryRun:
        """Flush the tail, persist the descriptor, and return the run."""

        if self._finished:
            raise RuntimeError("A temporary writer can only be finished once")
        if self._buffer:
            self._flush_chunk(len(self._buffer))
        descriptor = Page(DESCRIPTOR_PAGE_ID)
        slot = descriptor.insert(
            _encode_descriptor(self._schema, self._row_count, self._byte_length)
        )
        if slot != DESCRIPTOR_SLOT_ID:
            raise ValidationError("Temporary descriptor must occupy slot 0")
        self._manager.write_page(descriptor)
        self._manager.flush()
        self._finished = True
        run = TemporaryRun(
            path=self._path,
            schema=self._schema,
            row_count=self._row_count,
            byte_length=self._byte_length,
            page_count=self._page_count,
        )
        self._manager.close()
        return run

    def close(self) -> None:
        """Release the handle; an unfinished stream discards its file."""

        if not self._manager.closed:
            self._manager.close()
        if not self._finished:
            self._buffer.clear()
            self._workspace.discard(self._path)

    def __enter__(self) -> "TemporaryRowWriter":
        """Return this writer for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Close the writer on every exit path."""

        self.close()


class TemporaryRowReader:
    """Stream rows back from a completed temporary run, one page at a time.

    The reader holds the current page chunk plus at most one partially framed
    row, so memory stays bounded however long the run is. It registers itself
    with the workspace, which keeps the file alive until the last reader is
    released even if the run was already discarded.
    """

    __slots__ = ("_workspace", "_run", "_manager", "_buffer", "_next_page",
                 "_rows_read", "_bytes_read", "_closed", "_schema")

    def __init__(self, workspace: TemporaryWorkspace, run: TemporaryRun) -> None:
        if not isinstance(workspace, TemporaryWorkspace):
            raise InvalidTypeError("A temporary reader requires a TemporaryWorkspace")
        if not isinstance(run, TemporaryRun):
            raise InvalidTypeError("A temporary reader requires a TemporaryRun")
        self._workspace = workspace
        self._run = run
        self._buffer = bytearray()
        self._next_page = DESCRIPTOR_PAGE_ID + 1
        self._rows_read = 0
        self._bytes_read = 0
        self._closed = False
        path = workspace.acquire(run.path)
        try:
            self._manager = PageManager.open(path)
        except BaseException:
            workspace.release(run.path)
            raise
        try:
            descriptor = self._manager.read_page(DESCRIPTOR_PAGE_ID)
            schema, row_count, byte_length = _decode_descriptor(
                descriptor.read(DESCRIPTOR_SLOT_ID)
            )
            if schema != run.schema:
                raise SchemaError(
                    "Persisted temporary schema differs from its run descriptor"
                )
            if row_count != run.row_count or byte_length != run.byte_length:
                raise ValidationError(
                    "Persisted temporary counts differ from their run descriptor"
                )
            self._schema = schema
        except BaseException:
            self._manager.close()
            workspace.release(run.path)
            raise

    @property
    def run(self) -> TemporaryRun:
        """Return the run descriptor this reader streams."""

        return self._run

    @property
    def rows_read(self) -> int:
        """Return how many rows have been returned so far."""

        return self._rows_read

    @property
    def closed(self) -> bool:
        """Report whether this reader has been closed."""

        return self._closed

    @property
    def pages_read(self) -> int:
        """Return the real page reads performed by this reader."""

        return self._manager.pages_read if not self._manager.closed else 0

    def _fill(self, required: int) -> bool:
        """Read pages until the buffer holds ``required`` bytes, or data ends."""

        while len(self._buffer) < required:
            if self._next_page >= self._manager.allocated_page_count:
                return False
            page = self._manager.read_page(self._next_page)
            self._next_page += 1
            self._buffer += page.read(DESCRIPTOR_SLOT_ID)
        return True

    def next_row(self) -> Record | None:
        """Return the next row, or None at a clean end of stream."""

        if self._closed:
            raise RuntimeError("A closed temporary reader cannot produce rows")
        if not self._fill(ROW_LENGTH_SIZE):
            if self._buffer:
                raise ValidationError(
                    "Temporary stream ends inside a row length prefix"
                )
            if self._rows_read != self._run.row_count:
                raise ValidationError(
                    f"Temporary stream ended after {self._rows_read} rows but its "
                    f"descriptor declares {self._run.row_count}"
                )
            return None
        (length,) = VARCHAR_LENGTH_STRUCT.unpack_from(self._buffer, 0)
        if length > MAX_TEMPORARY_ROW_BYTES:
            raise ValidationError(
                f"Temporary row length {length} exceeds the supported maximum"
            )
        if not self._fill(ROW_LENGTH_SIZE + length):
            raise ValidationError(
                "Temporary stream ends inside a row payload; the file is truncated"
            )
        payload = bytes(self._buffer[ROW_LENGTH_SIZE:ROW_LENGTH_SIZE + length])
        del self._buffer[:ROW_LENGTH_SIZE + length]
        self._rows_read += 1
        self._bytes_read += ROW_LENGTH_SIZE + length
        if self._rows_read > self._run.row_count:
            raise ValidationError(
                "Temporary stream holds more rows than its descriptor declares"
            )
        return RecordCodec.deserialize(self._schema, payload)

    def close(self) -> None:
        """Close the handle and release this reader's hold on the file."""

        if self._closed:
            return
        self._closed = True
        self._buffer.clear()
        try:
            if not self._manager.closed:
                self._manager.close()
        finally:
            self._workspace.release(self._run.path)

    def __enter__(self) -> "TemporaryRowReader":
        """Return this reader for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Close the reader on every exit path."""

        self.close()
