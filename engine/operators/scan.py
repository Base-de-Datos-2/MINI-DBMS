"""Access-path operators: full storage scans and bound index lookups."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass

from engine.errors import InvalidTypeError, ValidationError
from engine.indexes.base import Index, OrderedIndex
from engine.storage.base import Storage
from engine.storage.paged_sequential_file import PagedSequentialFile
from engine.storage.record import Record, RecordValue
from engine.storage.rid import RID

from .base import ExecutionOperator
from .rows import ColumnReference, RowLayout, RowProvenance, validate_identifier


class TableScan(ExecutionOperator):
    """Stream every live row of one storage file through its scan contract.

    The cursor is created on ``open`` and closed on ``close``; the storage
    itself is borrowed and is never closed here. Two TableScans over one table
    hold two independent cursors, because ``Storage.scan`` returns a fresh
    generator per call.

    A Heap scan advertises no ordering: its physical order is not even
    chronological once deleted slots are reused. A paged sequential scan does
    advertise its configured key, because that organization keeps active rows
    physically ordered by it.
    """

    __slots__ = ("_storage", "_relation", "_cursor", "_ordering")

    def __init__(self, storage: Storage, *, relation: str) -> None:
        if not isinstance(storage, Storage):
            raise InvalidTypeError("TableScan requires a Storage")
        self._storage = storage
        self._relation = validate_identifier(relation, "TableScan relation")
        self._cursor: Generator[tuple[RID, Record], None, None] | None = None
        self._ordering: ColumnReference | None = (
            ColumnReference(storage.key_column, self._relation)
            if isinstance(storage, PagedSequentialFile)
            else None
        )
        super().__init__()

    def _build_layout(self) -> RowLayout:
        return RowLayout(self._storage.schema, relation=self._relation)

    @property
    def storage(self) -> Storage:
        """Return the borrowed storage this scan reads."""

        return self._storage

    @property
    def relation(self) -> str:
        """Return the relation name qualifying every emitted column."""

        return self._relation

    @property
    def ordering(self) -> ColumnReference | None:
        """Return the sequential key column, or None for a Heap file."""

        return self._ordering

    def _open(self) -> None:
        self._cursor = self._storage.scan()

    def _next(self) -> Record | None:
        entry = next(self._cursor, None)
        if entry is None:
            return None
        rid, record = entry
        self._statistics.rows_examined += 1
        self._provenance = (RowProvenance(self._relation, rid),)
        return record

    def _close(self) -> None:
        cursor, self._cursor = self._cursor, None
        if cursor is not None:
            cursor.close()

    def _details(self) -> tuple[tuple[str, str], ...]:
        details = [("relation", self._relation), ("access", "sequential scan")]
        if self._ordering is not None:
            details.append(("ordered_by", self._ordering.qualified_name))
        return tuple(details)


@dataclass(frozen=True, slots=True)
class EqualitySearch:
    """Look up every association of one exact key."""

    key: RecordValue


@dataclass(frozen=True, slots=True)
class RangeSearch:
    """Traverse an ordered index between optional bounds.

    ``None`` marks an unbounded end, never a NULL key. Both ends are inclusive
    by default; an inverted interval is rejected by the index itself.
    """

    lower: RecordValue | None = None
    upper: RecordValue | None = None
    include_lower: bool = True
    include_upper: bool = True

    def __post_init__(self) -> None:
        for name, flag in (
            ("include_lower", self.include_lower),
            ("include_upper", self.include_upper),
        ):
            if type(flag) is not bool:
                raise InvalidTypeError(f"RangeSearch {name} must be a bool")


def _index_storage(index: Index) -> Storage:
    """Return the storage an index adapter resolves its RIDs against."""

    for attribute in ("heap", "sequential"):
        storage = getattr(index, attribute, None)
        if isinstance(storage, Storage):
            return storage
    raise ValidationError(
        "IndexScan requires an index adapter bound to its storage, such as "
        "UnclusteredBPlusIndex, ClusteredBPlusIndex or UnclusteredHashIndex"
    )


class IndexScan(ExecutionOperator):
    """Stream rows located through one explicitly chosen access path.

    The index is supplied by the caller: this operator performs no planner
    selection. It reuses the adapter's record-resolving cursors, which already
    reject a RID whose stored key no longer matches the association rather
    than silently returning a different row.

    Extendible Hashing offers equality only. A range against a hash index is
    refused instead of being answered by a full scan wearing an index's name.
    """

    __slots__ = ("_index", "_search", "_relation", "_storage", "_cursor", "_ordering")

    def __init__(
        self,
        index: Index,
        search: EqualitySearch | RangeSearch,
        *,
        relation: str,
    ) -> None:
        if not isinstance(index, Index):
            raise InvalidTypeError("IndexScan requires an Index")
        if not isinstance(search, (EqualitySearch, RangeSearch)):
            raise InvalidTypeError(
                "IndexScan requires an EqualitySearch or a RangeSearch"
            )
        if isinstance(search, RangeSearch) and not isinstance(index, OrderedIndex):
            raise ValidationError(
                "This index supports equality access only; a range search "
                "cannot be served by Extendible Hashing"
            )
        self._index = index
        self._search = search
        self._relation = validate_identifier(relation, "IndexScan relation")
        self._storage = _index_storage(index)
        self._cursor: Generator[tuple[RID, Record], None, None] | None = None
        key_column = getattr(index, "key_column", None)
        self._ordering = (
            ColumnReference(key_column, self._relation)
            if isinstance(index, OrderedIndex) and isinstance(key_column, str)
            else None
        )
        super().__init__()

    @classmethod
    def equality(
        cls,
        index: Index,
        key: RecordValue,
        *,
        relation: str,
    ) -> "IndexScan":
        """Build an exact-key lookup over any compatible index."""

        return cls(index, EqualitySearch(key), relation=relation)

    @classmethod
    def between(
        cls,
        index: Index,
        lower: RecordValue | None = None,
        upper: RecordValue | None = None,
        *,
        relation: str,
        include_lower: bool = True,
        include_upper: bool = True,
    ) -> "IndexScan":
        """Build a bounded or open-ended traversal over an ordered index."""

        return cls(
            index,
            RangeSearch(lower, upper, include_lower, include_upper),
            relation=relation,
        )

    def _build_layout(self) -> RowLayout:
        return RowLayout(self._storage.schema, relation=self._relation)

    @property
    def index(self) -> Index:
        """Return the borrowed index this scan probes."""

        return self._index

    @property
    def search(self) -> EqualitySearch | RangeSearch:
        """Return the bound search specification."""

        return self._search

    @property
    def relation(self) -> str:
        """Return the relation name qualifying every emitted column."""

        return self._relation

    @property
    def ordering(self) -> ColumnReference | None:
        """Return the index key for an ordered path, or None for a hash path."""

        return self._ordering

    def _open(self) -> None:
        if isinstance(self._search, EqualitySearch):
            self._cursor = self._index.search_records(self._search.key)
            return
        self._cursor = self._index.range_records(
            self._search.lower,
            self._search.upper,
            include_lower=self._search.include_lower,
            include_upper=self._search.include_upper,
        )

    def _next(self) -> Record | None:
        entry = next(self._cursor, None)
        if entry is None:
            return None
        rid, record = entry
        self._statistics.rows_examined += 1
        self._provenance = (RowProvenance(self._relation, rid),)
        return record

    def _close(self) -> None:
        cursor, self._cursor = self._cursor, None
        if cursor is not None:
            cursor.close()

    def _details(self) -> tuple[tuple[str, str], ...]:
        access = (
            "hash equality"
            if not isinstance(self._index, OrderedIndex)
            else (
                "b+ equality"
                if isinstance(self._search, EqualitySearch)
                else "b+ range"
            )
        )
        details = [
            ("relation", self._relation),
            ("index", type(self._index).__name__),
            ("access", access),
        ]
        key_column = getattr(self._index, "key_column", None)
        if isinstance(key_column, str):
            details.append(("key_column", key_column))
        if isinstance(self._search, EqualitySearch):
            details.append(("key", repr(self._search.key)))
        else:
            details.append(
                (
                    "bounds",
                    f"{'[' if self._search.include_lower else '('}"
                    f"{self._search.lower!r}, {self._search.upper!r}"
                    f"{']' if self._search.include_upper else ')'}",
                )
            )
        if self._ordering is not None:
            details.append(("ordered_by", self._ordering.qualified_name))
        return tuple(details)
