"""Tiny behavioral examples for Stage 1 contracts, exclusively for tests.

Dicts/lists and synthetic RIDs are fixtures, not Heap Files, B+ trees, hashing,
page allocation, or production operators. No persistence or concurrency is
simulated. These examples do not replace conformance tests for future engines.
"""

from collections.abc import Callable, Generator, Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from math import isnan
from typing import TypeVar

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidReferenceError, InvalidTypeError, SchemaError, ValidationError
from engine.indexes import Index, OrderedIndex
from engine.operators import Operator
from engine.storage import RID, Record, Storage
from engine.storage.record import RecordValue


T = TypeVar("T")


@dataclass
class StreamProbe:
    """Observe lazy consumption and deterministic cleanup without real resources."""

    active: int = 0
    opened: int = 0
    closed: int = 0
    yielded: int = 0
    fail_after: int | None = None
    error: Exception | None = None

    def stream(self, items: Iterable[T]) -> Generator[T, None, None]:
        self.active += 1
        self.opened += 1
        try:
            for position, item in enumerate(items):
                if self.fail_after == position:
                    raise self.error if self.error is not None else RuntimeError("Injected failure")
                self.yielded += 1
                yield item
        finally:
            self.active -= 1
            self.closed += 1


class StorageDouble(Storage):
    """Model-only mapping with monotonically assigned synthetic identifiers."""

    def __init__(self, schema: Schema):
        self.schema = schema
        self._rows: dict[RID, Record] = {}
        self._next_slot = 0
        self.scans = StreamProbe()

    def insert(self, record: Record) -> RID:
        if not isinstance(record, Record):
            raise InvalidTypeError("Storage requires a Record")
        if record.schema != self.schema:
            raise SchemaError("Record schema differs from storage schema")
        rid = RID(0, self._next_slot)  # No page exists or is allocated.
        self._next_slot += 1
        self._rows[rid] = record
        return rid

    def read(self, rid: RID) -> Record:
        if not isinstance(rid, RID):
            raise InvalidTypeError("Storage requires a RID")
        if rid not in self._rows:
            raise InvalidReferenceError(f"Unknown RID: {rid!r}")
        return self._rows[rid]

    def delete(self, rid: RID) -> None:
        self.read(rid)
        del self._rows[rid]

    def scan(self) -> Generator[tuple[RID, Record], None, None]:
        yield from self.scans.stream(self._rows.items())


class EqualityIndexDouble(Index):
    """A tiny association list, deliberately without a range-search method."""

    def __init__(self, data_type: DataType = DataType.INTEGER):
        self._key_schema = Schema([Column("key", data_type)])
        self._pairs: list[tuple[RecordValue, RID]] = []
        self.searches = StreamProbe()

    def _validate_key(self, key: RecordValue) -> None:
        Record(self._key_schema, [key])  # Reuse the actual strict model validation.
        if type(key) is float and isnan(key):
            raise ValidationError("NaN is not an index key")

    def _validate_pair(self, key: RecordValue, rid: RID) -> None:
        self._validate_key(key)
        if not isinstance(rid, RID):
            raise InvalidTypeError("Index requires a RID")

    def insert(self, key: RecordValue, rid: RID) -> None:
        self._validate_pair(key, rid)
        if (key, rid) not in self._pairs:
            self._pairs.append((key, rid))

    def search(self, key: RecordValue) -> Generator[RID, None, None]:
        self._validate_key(key)
        yield from self.searches.stream(rid for value, rid in self._pairs if value == key)

    def delete(self, key: RecordValue, rid: RID) -> None:
        self._validate_pair(key, rid)
        if (key, rid) not in self._pairs:
            raise InvalidReferenceError(f"Unknown association: {(key, rid)!r}")
        self._pairs.remove((key, rid))


class OrderedIndexDouble(EqualityIndexDouble, OrderedIndex):
    """Keep the tiny fixture list ordered on insertion; this is not a B+ tree."""

    def insert(self, key: RecordValue, rid: RID) -> None:
        super().insert(key, rid)
        self._pairs.sort(key=lambda pair: pair[0])

    def range_search(
        self, lower: RecordValue | None = None, upper: RecordValue | None = None,
        *, include_lower: bool = True, include_upper: bool = True,
    ) -> Generator[RID, None, None]:
        for bound in (lower, upper):
            if bound is not None:
                self._validate_key(bound)
        if type(include_lower) is not bool or type(include_upper) is not bool:
            raise InvalidTypeError("Range inclusion flags must be bool")
        if lower is not None and upper is not None and lower > upper:
            raise ValidationError("Inverted range")
        yield from self.searches.stream(
            rid for key, rid in self._pairs
            if (lower is None or key > lower or (include_lower and key == lower))
            and (upper is None or key < upper or (include_upper and key == upper))
        )


class OperatorDouble(Operator):
    """Lifecycle probe around an injected row source, without relational logic."""

    def __init__(
        self, source: Callable[[], Generator[Record, None, None]],
        *, children: tuple[Operator, ...] = (),
    ):
        self._source = source
        self._children = children
        self._stack: ExitStack | None = None
        self._stream: Generator[Record, None, None] | None = None
        self._exhausted = False
        self._failed = False

    def open(self) -> None:
        if self._stack is not None:
            raise RuntimeError("Operator is already open")
        self._stack = ExitStack()
        self._exhausted = self._failed = False
        try:
            for child in self._children:
                self._stack.callback(child.close)
                child.open()
            self._stream = self._source()
            self._stack.callback(self._stream.close)
        except BaseException:
            self.close()
            raise

    def next(self) -> Record | None:
        if self._stack is None or self._failed:
            raise RuntimeError("Operator needs an open, non-failed run")
        if self._exhausted:
            return None
        try:
            return next(self._stream)
        except StopIteration:
            self._exhausted = True
            return None
        except BaseException:
            self._failed = True
            raise

    def close(self) -> None:
        stack, self._stack = self._stack, None
        self._stream = None
        if stack is not None:
            # ExitStack attempts every callback even when one cleanup raises.
            stack.close()
