"""Clustered B+ adapter over a key-compatible PagedSequentialFile."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import closing
import os

from engine.errors import (
    DuplicateError,
    InvalidReferenceError,
    InvalidTypeError,
    SchemaError,
    ValidationError,
)
from engine.storage.binary import MAX_RECORD_SIZE
from engine.storage.paged_sequential_file import PagedSequentialFile
from engine.storage.record import Record, RecordValue
from engine.storage.record_codec import RecordCodec
from engine.storage.rid import RID

from .base import OrderedIndex
from .bplus_codec import BPlusKeyCodec, BPlusRIDCodec
from .bplus_metrics import BPlusBuildMetrics, ClusteredReorganizationMetrics
from .bplus_tree import BPlusTree, BPlusValidationReport


class ClusteredBPlusIndex(OrderedIndex):
    """Coordinate one B+ association file with ordered physical storage.

    The adapter owns and closes the B+ tree but borrows the sequential file.
    Sequential insertion and reorganization can move live RIDs, so those
    operations persistently mark the index incomplete and rebuild it from the
    resulting storage before publishing a usable index again.
    """

    def __init__(self, tree: BPlusTree, sequential: PagedSequentialFile) -> None:
        if not isinstance(tree, BPlusTree):
            raise InvalidTypeError("tree must be a BPlusTree")
        if not isinstance(sequential, PagedSequentialFile):
            raise InvalidTypeError("sequential must be a PagedSequentialFile")
        if not tree.header.clustered:
            raise ValidationError("Clustered adapter requires clustered=True")
        tree.header.validate_clustered_storage(sequential.key_column)
        column = sequential.schema.column(tree.header.key_column)
        if column.data_type is not tree.key_type:
            raise ValidationError("B+ key type does not match the sequential column")
        if tree.header.allow_duplicate_keys != sequential.allow_duplicate_keys:
            raise ValidationError(
                "B+ duplicate policy does not match the sequential file"
            )
        self._tree = tree
        self._sequential = sequential
        self._consistent = tree.header.build_complete

    @classmethod
    def build(
        cls,
        path: str | os.PathLike[str],
        *,
        sequential: PagedSequentialFile,
        index_name: str,
        table_name: str,
        key_column: str,
        allow_duplicate_keys: bool = True,
    ) -> "ClusteredBPlusIndex":
        if not isinstance(sequential, PagedSequentialFile):
            raise InvalidTypeError("sequential must be a PagedSequentialFile")
        tree = BPlusTree.build_from_storage(
            path,
            storage=sequential,
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            clustered=True,
            allow_duplicate_keys=allow_duplicate_keys,
        )
        try:
            return cls(tree, sequential)
        except BaseException:
            tree.close()
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        sequential: PagedSequentialFile,
        index_name: str | None = None,
        table_name: str | None = None,
        key_column: str | None = None,
        allow_duplicate_keys: bool | None = None,
    ) -> "ClusteredBPlusIndex":
        if not isinstance(sequential, PagedSequentialFile):
            raise InvalidTypeError("sequential must be a PagedSequentialFile")
        tree = BPlusTree.open(
            path,
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            clustered=True,
            allow_duplicate_keys=allow_duplicate_keys,
        )
        try:
            return cls(tree, sequential)
        except BaseException:
            tree.close()
            raise

    @property
    def tree(self) -> BPlusTree:
        self._require_open()
        return self._tree

    @property
    def sequential(self) -> PagedSequentialFile:
        self._require_open()
        if self._sequential.closed:
            raise RuntimeError("Borrowed PagedSequentialFile is closed")
        return self._sequential

    @property
    def key_column(self) -> str:
        return self.tree.header.key_column

    @property
    def entry_count(self) -> int:
        self._require_consistent()
        return self.tree.entry_count

    @property
    def build_metrics(self) -> BPlusBuildMetrics | None:
        return self.tree.build_metrics

    @property
    def closed(self) -> bool:
        return self._tree.closed

    @property
    def consistent(self) -> bool:
        return not self.closed and self._consistent and self._tree.header.build_complete

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("Clustered B+ index is closed")

    def _require_consistent(self) -> None:
        self._require_open()
        if not self._consistent or not self._tree.header.build_complete:
            raise ValidationError(
                "Clustered B+ index is incomplete and must be rebuilt"
            )

    def _validate_new_record(self, record: object) -> tuple[Record, RecordValue]:
        if not isinstance(record, Record):
            raise InvalidTypeError("Clustered B+ insertion requires a Record")
        if record.schema != self.sequential.schema:
            raise SchemaError("Record schema differs from sequential storage schema")
        key = BPlusKeyCodec.validate(self.tree.key_type, record[self.key_column])
        if len(RecordCodec.serialize(record)) > MAX_RECORD_SIZE:
            raise ValidationError(
                f"Record payload exceeds page capacity of {MAX_RECORD_SIZE} bytes"
            )
        if not self.tree.header.allow_duplicate_keys:
            with closing(self.sequential.search(key)) as matches:
                if next(matches, None) is not None:
                    raise DuplicateError(
                        f"Duplicate sequential key: {key!r}"
                    )
        return record, key

    def _record_for_association(
        self,
        key: RecordValue,
        rid: RID,
    ) -> tuple[RecordValue, Record]:
        self._require_consistent()
        checked_key = BPlusKeyCodec.validate(self.tree.key_type, key)
        BPlusRIDCodec.encode(rid)
        record = self.sequential.read(rid)
        if BPlusKeyCodec.compare(
            self.tree.key_type, checked_key, record[self.key_column]
        ) != 0:
            raise InvalidReferenceError(
                "B+ key/RID association does not match the sequential record"
            )
        return checked_key, record

    def insert(self, key: RecordValue, rid: RID) -> None:
        checked_key, _ = self._record_for_association(key, rid)
        self.tree.insert(checked_key, rid)

    def delete(self, key: RecordValue, rid: RID) -> None:
        checked_key, _ = self._record_for_association(key, rid)
        self.tree.delete(checked_key, rid)

    def search(self, key: RecordValue) -> Generator[RID, None, None]:
        self._require_consistent()
        return self.tree.search(key)

    def search_records(
        self,
        key: RecordValue,
    ) -> Generator[tuple[RID, Record], None, None]:
        self._require_consistent()
        checked_key = BPlusKeyCodec.validate(self.tree.key_type, key)

        def iterator() -> Generator[tuple[RID, Record], None, None]:
            self._require_consistent()
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
        self._require_consistent()
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
        self._require_consistent()
        matches = self.tree.range_search(
            lower,
            upper,
            include_lower=include_lower,
            include_upper=include_upper,
        )

        def iterator() -> Generator[tuple[RID, Record], None, None]:
            self._require_consistent()
            previous_key: RecordValue | None = None
            has_previous = False
            with closing(matches):
                for rid in matches:
                    record = self.sequential.read(rid)
                    key = record[self.key_column]
                    BPlusKeyCodec.validate(self.tree.key_type, key)
                    with closing(self.tree.search(key)) as exact_matches:
                        if rid not in exact_matches:
                            raise InvalidReferenceError(
                                "B+ range RID is stale for its sequential record key"
                            )
                    if lower is not None:
                        comparison = BPlusKeyCodec.compare(
                            self.tree.key_type, key, lower
                        )
                        if comparison < 0 or (comparison == 0 and not include_lower):
                            raise InvalidReferenceError(
                                "B+ range association disagrees with its sequential key"
                            )
                    if upper is not None:
                        comparison = BPlusKeyCodec.compare(
                            self.tree.key_type, key, upper
                        )
                        if comparison > 0 or (comparison == 0 and not include_upper):
                            raise InvalidReferenceError(
                                "B+ range association disagrees with its sequential key"
                            )
                    if has_previous and BPlusKeyCodec.compare(
                        self.tree.key_type, previous_key, key
                    ) > 0:
                        raise ValidationError(
                            "Sequential records resolved from B+ are not ordered"
                        )
                    previous_key = key
                    has_previous = True
                    yield rid, record

        return iterator()

    def rebuild(self) -> BPlusBuildMetrics:
        """Recreate every association from active sequential records."""

        self._require_open()
        metrics = self._tree.rebuild_from_storage(self.sequential)
        self._consistent = True
        return metrics

    def insert_record(self, record: Record) -> RID:
        """Insert physically, then rebuild because existing RIDs may move."""

        self._require_consistent()
        checked_record, _ = self._validate_new_record(record)
        self._tree.mark_incomplete()
        self._consistent = False
        rid = self.sequential.insert(checked_record)
        self.rebuild()
        return rid

    def delete_record(self, rid: RID) -> None:
        """Remove the exact association before creating a sequential tombstone."""

        self._require_consistent()
        BPlusRIDCodec.encode(rid)
        record = self.sequential.read(rid)
        key = record[self.key_column]
        self.tree.delete(key, rid)
        try:
            self.sequential.delete(rid)
        except BaseException as storage_error:
            try:
                self.tree.insert(key, rid)
            except BaseException as cleanup_error:
                self._tree.mark_incomplete()
                self._consistent = False
                raise ExceptionGroup(
                    "Sequential deletion and B+ rollback both failed",
                    [storage_error, cleanup_error],
                ) from storage_error
            raise

    def reorganize(self) -> ClusteredReorganizationMetrics:
        """Compact sequential storage and rebuild every invalidated RID."""

        self._require_consistent()
        self._tree.mark_incomplete()
        self._consistent = False
        storage_metrics = self.sequential.reorganize()
        index_metrics = self.rebuild()
        return ClusteredReorganizationMetrics(storage_metrics, index_metrics)

    def read(self, rid: RID) -> Record:
        self._require_consistent()
        return self.sequential.read(rid)

    def validate_structure(self) -> BPlusValidationReport:
        """Prove tree structure and one-to-one live sequential associations."""

        self._require_consistent()
        report = self.tree.validate_structure()
        if report.entry_count != self.sequential.record_count:
            raise ValidationError(
                "B+ entry count does not match active sequential rows"
            )
        with closing(self.sequential.scan()) as rows:
            for rid, record in rows:
                key = record[self.key_column]
                with closing(self.tree.search(key)) as matches:
                    if rid not in matches:
                        raise ValidationError(
                            "Active sequential record is missing from the B+ index"
                        )
        return report

    def flush(self) -> None:
        self._require_open()
        self.sequential.flush()
        self.tree.flush()

    def close(self) -> None:
        self._tree.close()

    def __enter__(self) -> "ClusteredBPlusIndex":
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False
