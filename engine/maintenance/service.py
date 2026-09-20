"""Best-effort table-wide mutation consistency before transactions exist."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import struct
from tempfile import TemporaryDirectory

from engine.catalog import TableMetadata
from engine.errors import (
    DuplicateError,
    InvalidTypeError,
    UnsupportedAccessError,
    ValidationError,
)
from engine.indexes import Index
from engine.maintenance.validation import validate_record
from engine.storage import RID, Record, RecordCodec, Storage
from engine.storage.binary import UINT32_MAX


_SPOOL_MAGIC = b"MDBDEL01"
_SPOOL_HEADER = struct.Struct(">8sQ")
_SPOOL_FRAME = struct.Struct(">III")


class MaintenanceError(ValidationError):
    """A mutation failed, with its confirmed completion and repair state."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        table_name: str,
        completed_rows: int = 0,
        unavailable_indexes: Sequence[str] = (),
        failures: Sequence[BaseException] = (),
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.table_name = table_name
        self.completed_rows = completed_rows
        self.unavailable_indexes = tuple(unavailable_indexes)
        self.failures = tuple(failures)
        for failure in self.failures:
            self.add_note(f"{type(failure).__name__}: {failure}")


@dataclass(frozen=True, slots=True)
class MaintenanceIndex:
    """One table index and the column whose associations it maintains."""

    name: str
    column_name: str
    unique: bool
    index: Index

    def __post_init__(self) -> None:
        for label, value in (("Index name", self.name), ("Index column", self.column_name)):
            if not isinstance(value, str):
                raise InvalidTypeError(f"{label} must be a string")
            if not value.strip():
                raise ValidationError(f"{label} must not be empty")
        if type(self.unique) is not bool:
            raise InvalidTypeError("Index uniqueness must be a bool")
        if not isinstance(self.index, Index):
            raise InvalidTypeError("Maintenance index must implement Index")


@dataclass(frozen=True, slots=True)
class MutationReport:
    """Measured facts from one successfully completed synchronous mutation."""

    operation: str
    affected_rows: int
    indexes_maintained: tuple[str, ...]
    index_association_updates: int = 0
    indexes_rebuilt: tuple[str, ...] = ()
    targets_spooled: int = 0
    spool_bytes: int = 0


class DeleteTargetSpool:
    """One framed, disk-backed stream of exact RID/old-record identities."""

    __slots__ = (
        "_directory",
        "_path",
        "_writer",
        "_count",
        "_size",
        "_sealed",
        "_closed",
    )

    def __init__(self) -> None:
        self._count = 0
        self._size = 0
        self._sealed = False
        self._closed = False
        self._directory = TemporaryDirectory(prefix="minidb-delete-targets-")
        self._path = Path(self._directory.name) / "targets.bin"
        try:
            self._writer = self._path.open("w+b")
            self._writer.write(_SPOOL_HEADER.pack(_SPOOL_MAGIC, 0))
        except BaseException as error:
            try:
                self._directory.cleanup()
            except BaseException as cleanup:
                error.add_note(
                    f"Delete spool construction cleanup also failed: {cleanup}"
                )
            raise

    @property
    def count(self) -> int:
        return self._count

    @property
    def size(self) -> int:
        return self._size

    def append(self, rid: RID, record: Record) -> None:
        if self._sealed or self._closed:
            raise RuntimeError("Delete target spool is not writable")
        if not isinstance(rid, RID) or not isinstance(record, Record):
            raise InvalidTypeError("Delete targets require one RID and Record")
        if rid.page_id > UINT32_MAX or rid.slot_id > UINT32_MAX:
            raise ValidationError("Delete target RID exceeds the persisted page range")
        payload = RecordCodec.serialize(record)
        if len(payload) > UINT32_MAX:
            raise ValidationError("Delete target record is too large to spool")
        self._writer.write(_SPOOL_FRAME.pack(rid.page_id, rid.slot_id, len(payload)))
        self._writer.write(payload)
        self._count += 1

    def seal(self) -> None:
        if self._closed:
            raise RuntimeError("Delete target spool is closed")
        if self._sealed:
            return
        self._writer.seek(0)
        self._writer.write(_SPOOL_HEADER.pack(_SPOOL_MAGIC, self._count))
        self._writer.flush()
        self._writer.close()
        self._writer = None
        self._size = self._path.stat().st_size
        self._sealed = True

    @staticmethod
    def _read_exact(stream, size: int, label: str) -> bytes:
        payload = stream.read(size)
        if len(payload) != size:
            raise ValidationError(f"Truncated delete target spool {label}")
        return payload

    def targets(self, schema) -> Generator[tuple[RID, Record], None, None]:
        if not self._sealed or self._closed:
            raise RuntimeError("Delete target spool must be sealed before reading")

        def iterator() -> Generator[tuple[RID, Record], None, None]:
            observed = 0
            with self._path.open("rb") as stream:
                header = self._read_exact(stream, _SPOOL_HEADER.size, "header")
                magic, expected = _SPOOL_HEADER.unpack(header)
                if magic != _SPOOL_MAGIC or expected != self._count:
                    raise ValidationError("Invalid delete target spool header")
                while observed < expected:
                    frame = self._read_exact(stream, _SPOOL_FRAME.size, "frame")
                    page_id, slot_id, payload_size = _SPOOL_FRAME.unpack(frame)
                    payload = self._read_exact(stream, payload_size, "record")
                    observed += 1
                    yield RID(page_id, slot_id), RecordCodec.deserialize(schema, payload)
                if stream.read(1):
                    raise ValidationError("Trailing bytes in delete target spool")

        return iterator()

    def close(self) -> None:
        if self._closed:
            return
        failure: BaseException | None = None
        if self._writer is not None:
            try:
                self._writer.close()
            except BaseException as error:
                failure = error
            self._writer = None
        try:
            self._directory.cleanup()
        except BaseException as error:
            if failure is None:
                failure = error
            else:
                failure.add_note(f"Spool directory cleanup also failed: {error}")
        self._closed = True
        if failure is not None:
            raise failure

    def __enter__(self) -> "DeleteTargetSpool":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            self.close()
        except BaseException as cleanup:
            if exc_value is None:
                raise
            exc_value.add_note(
                f"Delete spool cleanup also failed: {type(cleanup).__name__}: {cleanup}"
            )
        return False


class MutationService:
    """Coordinate one storage mutation with every declared table index.

    This service provides ordinary-exception compensation and repair. It does
    not claim transaction rollback, concurrent-write safety, or crash atomicity.
    """

    __slots__ = ()

    @staticmethod
    def _validate_common(
        table_name: str,
        storage: Storage,
        indexes: Sequence[MaintenanceIndex],
    ) -> tuple[MaintenanceIndex, ...]:
        if not isinstance(table_name, str) or not table_name.strip():
            raise ValidationError("Mutation table name must be non-empty")
        if not isinstance(storage, Storage):
            raise InvalidTypeError("Mutation storage must implement Storage")
        if isinstance(indexes, (str, bytes, bytearray)) or not isinstance(
            indexes, Sequence
        ):
            raise InvalidTypeError("Mutation indexes must be a sequence")
        checked = tuple(indexes)
        if any(not isinstance(item, MaintenanceIndex) for item in checked):
            raise InvalidTypeError("Every mutation index must be MaintenanceIndex")
        names = tuple(item.name for item in checked)
        if len(set(names)) != len(names):
            raise ValidationError("Mutation index names must be distinct")
        return checked

    @staticmethod
    def _core(index: Index):
        return getattr(index, "tree", getattr(index, "index", index))

    @classmethod
    def _mark_incomplete(cls, item: MaintenanceIndex) -> None:
        marker = getattr(item.index, "mark_incomplete", None)
        if callable(marker):
            marker()
            return
        core = cls._core(item.index)
        marker = getattr(core, "mark_incomplete", None)
        if not callable(marker):
            raise UnsupportedAccessError(
                f"Index {item.name!r} has no persistent incomplete marker"
            )
        marker()
        flush = getattr(core, "flush", None)
        if callable(flush):
            flush()

    @classmethod
    def _invalidate_indexes(
        cls,
        indexes: Sequence[MaintenanceIndex],
    ) -> tuple[list[str], list[BaseException]]:
        unavailable: list[str] = []
        failures: list[BaseException] = []
        for item in indexes:
            try:
                cls._mark_incomplete(item)
            except BaseException as error:
                failures.append(error)
            unavailable.append(item.name)
        return unavailable, failures

    @classmethod
    def _repair_indexes(
        cls,
        indexes: Sequence[MaintenanceIndex],
    ) -> tuple[list[str], list[str], list[BaseException]]:
        rebuilt: list[str] = []
        unavailable: list[str] = []
        failures: list[BaseException] = []
        for item in indexes:
            try:
                cls._mark_incomplete(item)
            except BaseException as error:
                failures.append(error)
            rebuild = getattr(item.index, "rebuild", None)
            if not callable(rebuild):
                unavailable.append(item.name)
                failures.append(
                    UnsupportedAccessError(
                        f"Index {item.name!r} has no storage rebuild path"
                    )
                )
                continue
            try:
                rebuild()
            except BaseException as error:
                failures.append(error)
                unavailable.append(item.name)
                try:
                    cls._mark_incomplete(item)
                except BaseException as marker_error:
                    failures.append(marker_error)
            else:
                rebuilt.append(item.name)
        return rebuilt, unavailable, failures

    @staticmethod
    def _flush(
        storage: Storage,
        indexes: Sequence[MaintenanceIndex],
    ) -> None:
        flush_storage = getattr(storage, "flush", None)
        if callable(flush_storage):
            flush_storage()
        for item in indexes:
            flush_index = getattr(item.index, "flush", None)
            if callable(flush_index):
                flush_index()

    @staticmethod
    def _check_constraints(
        storage: Storage,
        record: Record,
        indexes: Sequence[MaintenanceIndex],
        *,
        storage_key,
        requires_storage_unique_check: bool,
    ) -> None:
        if requires_storage_unique_check:
            search = getattr(storage, "search", None)
            if not callable(search):
                raise UnsupportedAccessError(
                    "Unique storage validation requires an exact search path"
                )
            with closing(search(storage_key)) as matches:
                if next(matches, None) is not None:
                    raise DuplicateError(
                        f"Storage key {storage_key!r} already exists"
                    )
        for item in indexes:
            if not item.unique:
                continue
            key = record[item.column_name]
            with closing(item.index.search(key)) as matches:
                if next(matches, None) is not None:
                    raise DuplicateError(
                        f"Unique index {item.name!r} already contains key {key!r}"
                    )

    @staticmethod
    def _count_delta(storage: Storage, before: int | None) -> int:
        after = getattr(storage, "record_count", None)
        if type(before) is int and type(after) is int:
            return max(0, after - before)
        return 0

    def _raise_failure(
        self,
        message: str,
        *,
        operation: str,
        table_name: str,
        original: BaseException,
        completed_rows: int,
        unavailable: Sequence[str] = (),
        failures: Sequence[BaseException] = (),
    ) -> None:
        error = MaintenanceError(
            message,
            operation=operation,
            table_name=table_name,
            completed_rows=completed_rows,
            unavailable_indexes=unavailable,
            failures=(original, *failures),
        )
        raise error from original

    def insert(
        self,
        *,
        table_name: str,
        table_metadata: TableMetadata | None = None,
        storage: Storage,
        record: Record,
        indexes: Sequence[MaintenanceIndex],
        storage_may_move_rids: bool,
        storage_key=None,
        requires_storage_unique_check: bool = False,
    ) -> MutationReport:
        indexes = self._validate_common(table_name, storage, indexes)
        if not isinstance(record, Record):
            raise InvalidTypeError("INSERT maintenance requires a Record")
        if table_metadata is not None:
            if not isinstance(table_metadata, TableMetadata):
                raise InvalidTypeError("table_metadata must be TableMetadata or None")
            if table_metadata.name != table_name:
                raise ValidationError(
                    "INSERT table metadata name does not match the mutation target"
                )
            validate_record(table_metadata, record)
        if type(storage_may_move_rids) is not bool:
            raise InvalidTypeError("storage_may_move_rids must be a bool")
        if type(requires_storage_unique_check) is not bool:
            raise InvalidTypeError("requires_storage_unique_check must be a bool")
        self._check_constraints(
            storage,
            record,
            indexes,
            storage_key=storage_key,
            requires_storage_unique_check=requires_storage_unique_check,
        )

        before_count = getattr(storage, "record_count", None)
        rebuilt: list[str] = []
        association_updates = 0
        if storage_may_move_rids and indexes:
            _, marker_failures = self._invalidate_indexes(indexes)
            if marker_failures:
                repaired, unavailable, repair_failures = self._repair_indexes(indexes)
                self._raise_failure(
                    "INSERT could not establish a safe RID-remap boundary",
                    operation="INSERT",
                    table_name=table_name,
                    original=marker_failures[0],
                    completed_rows=0,
                    unavailable=unavailable,
                    failures=(*marker_failures[1:], *repair_failures),
                )

        try:
            rid = storage.insert(record)
        except BaseException as operation_error:
            repaired, unavailable, repair_failures = self._repair_indexes(indexes)
            self._raise_failure(
                "INSERT storage mutation failed",
                operation="INSERT",
                table_name=table_name,
                original=operation_error,
                completed_rows=self._count_delta(storage, before_count),
                unavailable=unavailable,
                failures=repair_failures,
            )

        try:
            if storage_may_move_rids:
                rebuilt, unavailable, repair_failures = self._repair_indexes(indexes)
                if unavailable:
                    raise MaintenanceError(
                        "INSERT could not rebuild every RID-based index",
                        operation="INSERT",
                        table_name=table_name,
                        completed_rows=1,
                        unavailable_indexes=unavailable,
                        failures=repair_failures,
                    )
            else:
                for item in indexes:
                    item.index.insert(record[item.column_name], rid)
                    association_updates += 1
            self._flush(storage, indexes)
        except BaseException as operation_error:
            cleanup_failures: list[BaseException] = []
            try:
                storage.delete(rid)
            except BaseException as cleanup_error:
                cleanup_failures.append(cleanup_error)
            repaired, unavailable, repair_failures = self._repair_indexes(indexes)
            cleanup_failures.extend(repair_failures)
            self._raise_failure(
                "INSERT failed after the base record changed",
                operation="INSERT",
                table_name=table_name,
                original=operation_error,
                completed_rows=self._count_delta(storage, before_count),
                unavailable=unavailable,
                failures=cleanup_failures,
            )

        return MutationReport(
            "INSERT",
            1,
            tuple(item.name for item in indexes),
            index_association_updates=association_updates,
            indexes_rebuilt=tuple(rebuilt),
        )

    def delete(
        self,
        *,
        table_name: str,
        storage: Storage,
        indexes: Sequence[MaintenanceIndex],
        targets: Generator[tuple[RID, Record], None, None],
        target_count: int,
        spool_bytes: int,
    ) -> MutationReport:
        indexes = self._validate_common(table_name, storage, indexes)
        if not isinstance(targets, Generator):
            raise InvalidTypeError("DELETE targets must be a closable generator")
        for label, value in (("target_count", target_count), ("spool_bytes", spool_bytes)):
            if type(value) is not int:
                raise InvalidTypeError(f"DELETE {label} must be an int")
            if value < 0:
                raise ValidationError(f"DELETE {label} must be non-negative")

        completed = 0
        association_updates = 0
        try:
            with closing(targets):
                for rid, old_record in targets:
                    try:
                        current = storage.read(rid)
                        if current != old_record:
                            raise ValidationError(
                                "DELETE target RID no longer identifies its original row"
                            )
                        for item in indexes:
                            item.index.delete(old_record[item.column_name], rid)
                            association_updates += 1
                        storage.delete(rid)
                    except BaseException as operation_error:
                        repaired, unavailable, repair_failures = self._repair_indexes(
                            indexes
                        )
                        self._raise_failure(
                            "DELETE stopped after an ordinary row-maintenance failure",
                            operation="DELETE",
                            table_name=table_name,
                            original=operation_error,
                            completed_rows=completed,
                            unavailable=unavailable,
                            failures=repair_failures,
                        )
                    completed += 1
        except MaintenanceError:
            raise
        except BaseException as spool_error:
            repaired, unavailable, repair_failures = self._repair_indexes(indexes)
            self._raise_failure(
                "DELETE target spool failed during the mutation pass",
                operation="DELETE",
                table_name=table_name,
                original=spool_error,
                completed_rows=completed,
                unavailable=unavailable,
                failures=repair_failures,
            )

        if completed != target_count:
            mismatch = ValidationError(
                f"DELETE spool declared {target_count} targets but produced {completed}"
            )
            repaired, unavailable, repair_failures = self._repair_indexes(indexes)
            self._raise_failure(
                "DELETE target spool count changed during the mutation pass",
                operation="DELETE",
                table_name=table_name,
                original=mismatch,
                completed_rows=completed,
                unavailable=unavailable,
                failures=repair_failures,
            )

        try:
            self._flush(storage, indexes)
        except BaseException as flush_error:
            unavailable, marker_failures = self._invalidate_indexes(indexes)
            self._raise_failure(
                "DELETE completed logically but persistence flush failed",
                operation="DELETE",
                table_name=table_name,
                original=flush_error,
                completed_rows=completed,
                unavailable=unavailable,
                failures=marker_failures,
            )

        return MutationReport(
            "DELETE",
            completed,
            tuple(item.name for item in indexes),
            index_association_updates=association_updates,
            targets_spooled=target_count,
            spool_bytes=spool_bytes,
        )


__all__ = [
    "DeleteTargetSpool",
    "MaintenanceError",
    "MaintenanceIndex",
    "MutationReport",
    "MutationService",
]
