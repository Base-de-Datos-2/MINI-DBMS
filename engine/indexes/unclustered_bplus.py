"""Unclustered B+ adapter over an independently ordered HeapFile."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import closing
import os

from engine.errors import InvalidReferenceError, InvalidTypeError, ValidationError
from engine.storage.heap_file import HeapFile
from engine.storage.record import Record, RecordValue
from engine.storage.rid import RID

from .base import OrderedIndex
from .bplus_codec import BPlusKeyCodec, BPlusRIDCodec
from .bplus_metrics import BPlusBuildMetrics
from .bplus_tree import BPlusTree, BPlusValidationReport


class UnclusteredBPlusIndex(OrderedIndex):
    """Resolve one B+ association file against a borrowed open HeapFile.

    This adapter owns and closes its B+ tree. The HeapFile remains owned by the
    caller, allowing multiple independent unclustered indexes over one table.
    """

    def __init__(self, tree: BPlusTree, heap: HeapFile) -> None:
        if not isinstance(tree, BPlusTree):
            raise InvalidTypeError("tree must be a BPlusTree")
        if not isinstance(heap, HeapFile):
            raise InvalidTypeError("heap must be a HeapFile")
        if tree.header.clustered:
            raise ValidationError("Unclustered adapter requires clustered=False")
        column = heap.schema.column(tree.header.key_column)
        if column.data_type is not tree.key_type:
            raise ValidationError("B+ key type does not match the Heap column")
        self._tree = tree
        self._heap = heap

    @classmethod
    def build(
        cls,
        path: str | os.PathLike[str],
        *,
        heap: HeapFile,
        index_name: str,
        table_name: str,
        key_column: str,
        allow_duplicate_keys: bool = True,
    ) -> "UnclusteredBPlusIndex":
        if not isinstance(heap, HeapFile):
            raise InvalidTypeError("heap must be a HeapFile")
        tree = BPlusTree.build_from_storage(
            path,
            storage=heap,
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            clustered=False,
            allow_duplicate_keys=allow_duplicate_keys,
        )
        try:
            return cls(tree, heap)
        except BaseException:
            tree.close()
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        heap: HeapFile,
        index_name: str | None = None,
        table_name: str | None = None,
        key_column: str | None = None,
        allow_duplicate_keys: bool | None = None,
    ) -> "UnclusteredBPlusIndex":
        if not isinstance(heap, HeapFile):
            raise InvalidTypeError("heap must be a HeapFile")
        tree = BPlusTree.open(
            path,
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            clustered=False,
            allow_duplicate_keys=allow_duplicate_keys,
        )
        try:
            return cls(tree, heap)
        except BaseException:
            tree.close()
            raise

    @property
    def tree(self) -> BPlusTree:
        self._require_open()
        return self._tree

    @property
    def heap(self) -> HeapFile:
        self._require_open()
        if self._heap.closed:
            raise RuntimeError("Borrowed HeapFile is closed")
        return self._heap

    @property
    def key_column(self) -> str:
        return self.tree.header.key_column

    @property
    def entry_count(self) -> int:
        return self.tree.entry_count

    @property
    def build_metrics(self) -> BPlusBuildMetrics | None:
        return self.tree.build_metrics

    @property
    def closed(self) -> bool:
        return self._tree.closed

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("Unclustered B+ index is closed")

    def _record_for_association(
        self,
        key: RecordValue,
        rid: RID,
    ) -> tuple[RecordValue, Record]:
        checked_key = BPlusKeyCodec.validate(self.tree.key_type, key)
        BPlusRIDCodec.encode(rid)
        record = self.heap.read(rid)
        record_key = record[self.key_column]
        if BPlusKeyCodec.compare(self.tree.key_type, checked_key, record_key) != 0:
            raise InvalidReferenceError(
                "B+ key/RID association does not match the Heap record"
            )
        return checked_key, record

    def insert(self, key: RecordValue, rid: RID) -> None:
        checked_key, _ = self._record_for_association(key, rid)
        self.tree.insert(checked_key, rid)

    def search(self, key: RecordValue) -> Generator[RID, None, None]:
        self._require_open()
        return self.tree.search(key)

    def search_records(
        self,
        key: RecordValue,
    ) -> Generator[tuple[RID, Record], None, None]:
        self._require_open()
        checked_key = BPlusKeyCodec.validate(self.tree.key_type, key)

        def iterator() -> Generator[tuple[RID, Record], None, None]:
            self._require_open()
            with closing(self.tree.search(checked_key)) as matches:
                for rid in matches:
                    _, record = self._record_for_association(checked_key, rid)
                    yield rid, record

        return iterator()

    def range_search(
        self,
        lower: RecordValue | None = None,
        upper: RecordValue | None = None,
        *,
        include_lower: bool = True,
        include_upper: bool = True,
    ) -> Generator[RID, None, None]:
        self._require_open()
        return self.tree.range_search(
            lower,
            upper,
            include_lower=include_lower,
            include_upper=include_upper,
        )

    def range_records(
        self,
        lower: RecordValue | None = None,
        upper: RecordValue | None = None,
        *,
        include_lower: bool = True,
        include_upper: bool = True,
    ) -> Generator[tuple[RID, Record], None, None]:
        self._require_open()
        matches = self.tree.range_search(
            lower,
            upper,
            include_lower=include_lower,
            include_upper=include_upper,
        )

        def iterator() -> Generator[tuple[RID, Record], None, None]:
            self._require_open()
            previous_key: RecordValue | None = None
            has_previous = False
            with closing(matches):
                for rid in matches:
                    record = self.heap.read(rid)
                    key = record[self.key_column]
                    BPlusKeyCodec.validate(self.tree.key_type, key)
                    with closing(self.tree.search(key)) as exact_matches:
                        if rid not in exact_matches:
                            raise InvalidReferenceError(
                                "B+ range RID is stale for its Heap record key"
                            )
                    if lower is not None:
                        comparison = BPlusKeyCodec.compare(
                            self.tree.key_type, key, lower
                        )
                        if comparison < 0 or (comparison == 0 and not include_lower):
                            raise InvalidReferenceError(
                                "B+ range association disagrees with its Heap key"
                            )
                    if upper is not None:
                        comparison = BPlusKeyCodec.compare(
                            self.tree.key_type, key, upper
                        )
                        if comparison > 0 or (comparison == 0 and not include_upper):
                            raise InvalidReferenceError(
                                "B+ range association disagrees with its Heap key"
                            )
                    if has_previous and BPlusKeyCodec.compare(
                        self.tree.key_type, previous_key, key
                    ) > 0:
                        raise ValidationError(
                            "Heap records resolved from B+ range are not ordered"
                        )
                    previous_key = key
                    has_previous = True
                    yield rid, record

        return iterator()

    def delete(self, key: RecordValue, rid: RID) -> None:
        checked_key, _ = self._record_for_association(key, rid)
        self.tree.delete(checked_key, rid)

    def insert_record(self, record: Record) -> RID:
        """Insert one Heap row and its index association with best-effort undo."""

        self._require_open()
        rid = self.heap.insert(record)
        try:
            self.tree.insert(record[self.key_column], rid)
            return rid
        except BaseException as index_error:
            try:
                self.heap.delete(rid)
            except BaseException as cleanup_error:
                raise ExceptionGroup(
                    "B+ insertion and Heap rollback both failed",
                    [index_error, cleanup_error],
                ) from index_error
            raise

    def delete_record(self, rid: RID) -> None:
        """Remove the exact index association before freeing its Heap slot."""

        self._require_open()
        BPlusRIDCodec.encode(rid)
        record = self.heap.read(rid)
        key = record[self.key_column]
        self.tree.delete(key, rid)
        try:
            self.heap.delete(rid)
        except BaseException as storage_error:
            try:
                self.tree.insert(key, rid)
            except BaseException as cleanup_error:
                raise ExceptionGroup(
                    "Heap deletion and B+ rollback both failed",
                    [storage_error, cleanup_error],
                ) from storage_error
            raise

    def read(self, rid: RID) -> Record:
        self._require_open()
        return self.heap.read(rid)

    def rebuild(self) -> BPlusBuildMetrics:
        """Atomically reconstruct all associations from active Heap rows."""

        self._require_open()
        return self._tree.rebuild_from_storage(self.heap)

    def validate_structure(self) -> BPlusValidationReport:
        """Validate both the tree and its one-to-one live Heap associations."""

        report = self.tree.validate_structure()
        if report.entry_count != self.heap.record_count:
            raise ValidationError("B+ entry count does not match active Heap rows")
        with closing(self.heap.scan()) as rows:
            for rid, record in rows:
                key = record[self.key_column]
                with closing(self.tree.search(key)) as matches:
                    found = rid in matches
                if not found:
                    raise ValidationError(
                        "Active Heap record is missing from the B+ index"
                    )
        return report

    def flush(self) -> None:
        self._require_open()
        self.heap.flush()
        self.tree.flush()

    def close(self) -> None:
        self._tree.close()

    def __enter__(self) -> "UnclusteredBPlusIndex":
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False
