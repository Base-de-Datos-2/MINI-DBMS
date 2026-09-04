"""Persistent B+ lifecycle, queries, insertion, and underflow repair."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import closing
from dataclasses import dataclass, replace
import os
from time import perf_counter

from engine.catalog.schema import Schema
from engine.catalog.types import DataType
from engine.errors import (
    DuplicateError,
    InvalidReferenceError,
    InvalidTypeError,
    ValidationError,
)
from engine.storage.base import Storage
from engine.storage.page_manager import PageManager
from engine.storage.record import RecordValue
from engine.storage.rid import RID

from .base import OrderedIndex
from .bplus_codec import BPlusKeyCodec, BPlusRIDCodec
from .bplus_header import BPlusFileHeader
from .bplus_io import BPlusHeaderPageIO, BPlusNodePageIO
from .bplus_metrics import BPlusBuildMetrics, BPlusStructuralMetrics
from .bplus_node import BPlusFreeNode, BPlusInternalNode, BPlusLeafNode


@dataclass(frozen=True, slots=True)
class BPlusPathEntry:
    """One internal ancestor and the child selected during lower-bound descent."""

    node: BPlusInternalNode
    child_index: int


@dataclass(frozen=True, slots=True)
class BPlusDescent:
    """Target leaf plus root-to-parent mutation path."""

    leaf: BPlusLeafNode
    ancestors: tuple[BPlusPathEntry, ...]


@dataclass(frozen=True, slots=True)
class BPlusValidationReport:
    """Observed global structure after a successful validation pass."""

    height: int
    entry_count: int
    leaf_count: int
    internal_count: int
    free_page_count: int


class BPlusTree(OrderedIndex):
    """Shared persistent B+ core used by both Stage 4 storage adapters.

    Exact association deletion repairs leaf and internal underflow while
    preserving right-min separators. Released pages are reused through a
    persistent free list, and complete trees can be built or atomically rebuilt
    from Stage 3 storage.
    """

    def __init__(self, manager: PageManager, header: BPlusFileHeader) -> None:
        if not isinstance(manager, PageManager):
            raise InvalidTypeError("manager must be a PageManager")
        if not isinstance(header, BPlusFileHeader):
            raise InvalidTypeError("header must be a BPlusFileHeader")
        if manager.allocated_page_count != header.node_page_count + 1:
            raise ValidationError(
                "B+ header node-page count does not match the physical file"
            )
        self._manager = manager
        self._header = header
        self._nodes = BPlusNodePageIO(manager, header.key_type)
        self._build_metrics: BPlusBuildMetrics | None = None
        self._structural_metrics = BPlusStructuralMetrics()

    @classmethod
    def _create_with_header(
        cls,
        path: str | os.PathLike[str],
        header: BPlusFileHeader,
    ) -> "BPlusTree":
        header.serialize()
        manager = PageManager.create(path)
        try:
            BPlusHeaderPageIO.initialize(manager, header)
            return cls(manager, header)
        except BaseException:
            try:
                manager.close()
            except BaseException:
                pass
            raise

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        index_name: str,
        table_name: str,
        key_column: str,
        key_type: DataType,
        clustered: bool = False,
        allow_duplicate_keys: bool = True,
    ) -> "BPlusTree":
        header = BPlusFileHeader(
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            key_type=key_type,
            clustered=clustered,
            allow_duplicate_keys=allow_duplicate_keys,
        )
        return cls._create_with_header(path, header)

    @classmethod
    def build_from_storage(
        cls,
        path: str | os.PathLike[str],
        *,
        storage: Storage,
        index_name: str,
        table_name: str,
        key_column: str,
        clustered: bool = False,
        allow_duplicate_keys: bool = True,
    ) -> "BPlusTree":
        """Incrementally build a complete index from one open Stage 3 storage.

        The source remains borrowed and open. A failed build remains on disk
        with ``build_complete=False`` and normal ``open`` rejects it.
        """

        if not isinstance(storage, Storage):
            raise InvalidTypeError("storage must implement Storage")
        try:
            schema = storage.schema
        except AttributeError as exc:
            raise InvalidTypeError("storage must expose its Schema") from exc
        if not isinstance(schema, Schema):
            raise InvalidTypeError("storage schema must be a Schema")
        column = schema.column(key_column)
        if type(clustered) is not bool:
            raise InvalidTypeError("clustered must be a bool")
        if clustered:
            metadata = getattr(storage, "metadata", None)
            physical_key = getattr(metadata, "key_column", None)
            if physical_key != key_column:
                raise ValidationError(
                    "Clustered B+ build requires matching ordered storage"
                )
        try:
            storage_reads_before = storage.pages_read
        except AttributeError as exc:
            raise InvalidTypeError(
                "storage must expose actual page-I/O counters"
            ) from exc
        if type(storage_reads_before) is not int:
            raise InvalidTypeError("storage pages_read must be an int")

        started_at = perf_counter()
        header = BPlusFileHeader(
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            key_type=column.data_type,
            clustered=clustered,
            allow_duplicate_keys=allow_duplicate_keys,
            build_complete=False,
        )
        tree = cls._create_with_header(path, header)
        indexed = 0
        try:
            with closing(storage.scan()) as rows:
                for rid, record in rows:
                    tree.insert(record[key_column], rid)
                    indexed += 1
            tree._write_header(replace(tree._header, build_complete=True))
            tree._build_metrics = BPlusBuildMetrics(
                elapsed_seconds=perf_counter() - started_at,
                entries_indexed=indexed,
                storage_pages_read=storage.pages_read - storage_reads_before,
                index_pages_read=tree.pages_read,
                index_pages_written=tree.pages_written,
                index_pages_allocated=tree.pages_allocated,
                index_file_size=tree.file_size,
            )
            return tree
        except BaseException:
            try:
                tree.close()
            except BaseException:
                pass
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        index_name: str | None = None,
        table_name: str | None = None,
        key_column: str | None = None,
        key_type: DataType | None = None,
        clustered: bool | None = None,
        allow_duplicate_keys: bool | None = None,
    ) -> "BPlusTree":
        manager = PageManager.open(path)
        try:
            header = BPlusHeaderPageIO.read(manager)
            if not header.build_complete:
                raise ValidationError("B+ index build is incomplete")
            expected = {
                "index_name": index_name,
                "table_name": table_name,
                "key_column": key_column,
                "key_type": key_type,
                "clustered": clustered,
                "allow_duplicate_keys": allow_duplicate_keys,
            }
            for field, value in expected.items():
                if value is not None and getattr(header, field) != value:
                    raise ValidationError(f"B+ index metadata mismatch for {field}")
            return cls(manager, header)
        except BaseException:
            try:
                manager.close()
            except BaseException:
                pass
            raise

    @property
    def header(self) -> BPlusFileHeader:
        self._require_open()
        return self._header

    @property
    def key_type(self) -> DataType:
        self._require_open()
        return self._header.key_type

    @property
    def height(self) -> int:
        self._require_open()
        return self._header.height

    @property
    def entry_count(self) -> int:
        self._require_open()
        return self._header.entry_count

    @property
    def node_page_count(self) -> int:
        self._require_open()
        return self._header.node_page_count

    @property
    def build_metrics(self) -> BPlusBuildMetrics | None:
        """Return metrics for this process's build, or ``None`` after reopen."""

        self._require_open()
        return self._build_metrics

    @property
    def structural_metrics(self) -> BPlusStructuralMetrics:
        """Return an immutable snapshot of structural events this session."""

        self._require_open()
        return self._structural_metrics

    @property
    def allocated_page_count(self) -> int:
        self._require_open()
        return self._manager.allocated_page_count

    @property
    def file_size(self) -> int:
        self._require_open()
        return self._manager.file_size

    @property
    def pages_read(self) -> int:
        self._require_open()
        return self._manager.pages_read

    @property
    def pages_written(self) -> int:
        self._require_open()
        return self._manager.pages_written

    @property
    def pages_allocated(self) -> int:
        self._require_open()
        return self._manager.pages_allocated

    @property
    def closed(self) -> bool:
        return self._manager.closed

    def reset_counters(self) -> None:
        self._require_open()
        self._manager.reset_counters()
        self._structural_metrics = BPlusStructuralMetrics()

    def _count_structural(self, field: str) -> None:
        self._structural_metrics = replace(
            self._structural_metrics,
            **{field: getattr(self._structural_metrics, field) + 1},
        )

    def mark_incomplete(self) -> None:
        """Persistently prevent reopening a tree whose storage may be stale."""

        self._require_open()
        if self._header.build_complete:
            self._write_header(replace(self._header, build_complete=False))

    def rebuild_from_storage(self, storage: Storage) -> BPlusBuildMetrics:
        """Atomically replace this index with a build from current storage.

        The old index remains physically intact until a complete candidate has
        been built, structurally validated, flushed, and closed.  The returned
        metrics include the candidate build; PageManager counters on this tree
        begin a fresh session after replacement.
        """

        self._require_open()
        temporary_path = self._manager.temporary_replacement_path()
        candidate: BPlusTree | None = None
        committed = False
        try:
            candidate = type(self).build_from_storage(
                temporary_path,
                storage=storage,
                index_name=self._header.index_name,
                table_name=self._header.table_name,
                key_column=self._header.key_column,
                clustered=self._header.clustered,
                allow_duplicate_keys=self._header.allow_duplicate_keys,
            )
            candidate.validate_structure()
            candidate.flush()
            metrics = candidate.build_metrics
            if metrics is None:  # pragma: no cover - construction guarantees it
                raise ValidationError("Replacement B+ build produced no metrics")
            structural_metrics = candidate.structural_metrics
            candidate.close()
            candidate = None

            self._manager.commit_replacement(temporary_path)
            committed = True
            header = BPlusHeaderPageIO.read(self._manager)
            header.validate_definition(
                index_name=self._header.index_name,
                table_name=self._header.table_name,
                key_column=self._header.key_column,
                key_type=self._header.key_type,
                clustered=self._header.clustered,
                allow_duplicate_keys=self._header.allow_duplicate_keys,
            )
            if not header.build_complete:
                raise ValidationError("Replacement B+ build is incomplete")
            self._header = header
            self._nodes = BPlusNodePageIO(self._manager, header.key_type)
            self._build_metrics = metrics
            self._structural_metrics = structural_metrics
            return metrics
        finally:
            if candidate is not None:
                candidate.close()
            if not committed:
                self._manager.discard_replacement(temporary_path)

    def flush(self) -> None:
        self._require_open()
        self._manager.flush()

    def close(self) -> None:
        self._manager.close()

    def __enter__(self) -> "BPlusTree":
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("B+ tree is closed")

    def _validate_node_reference(self, page_id: object, label: str) -> int:
        if type(page_id) is not int:
            raise ValidationError(f"{label} is not an integer page reference")
        if not 1 <= page_id <= self._header.node_page_count:
            raise ValidationError(f"{label} is outside the B+ node-page range")
        if page_id == self._header.free_node_head_page_id:
            raise ValidationError(f"{label} points to the B+ free-node list")
        return page_id

    def _read_reachable_node(self, page_id: object, label: str):
        checked = self._validate_node_reference(page_id, label)
        node = self._nodes.read_node(checked)
        if isinstance(node, BPlusFreeNode):
            raise ValidationError(f"{label} points to a released B+ node page")
        if isinstance(node, BPlusLeafNode) and not self._header.allow_duplicate_keys:
            for previous, current in zip(node.keys, node.keys[1:]):
                if BPlusKeyCodec.compare(
                    self._header.key_type, previous, current
                ) == 0:
                    raise ValidationError(
                        "B+ leaf contains duplicates forbidden by its header"
                    )
        return node

    def descend(self, key: RecordValue) -> BPlusDescent | None:
        """Perform duplicate-aware lower-bound descent and capture ancestors."""

        self._require_open()
        checked_key = BPlusKeyCodec.validate(self._header.key_type, key)
        if self._header.entry_count == 0:
            return None

        current_page_id = self._validate_node_reference(
            self._header.root_page_id, "B+ root"
        )
        visited: set[int] = set()
        ancestors: list[BPlusPathEntry] = []

        for level in range(self._header.height):
            if current_page_id in visited:
                raise ValidationError("Cycle detected in B+ child pointers")
            visited.add(current_page_id)
            node = self._read_reachable_node(current_page_id, "B+ child")
            is_leaf_level = level == self._header.height - 1
            if is_leaf_level:
                if not isinstance(node, BPlusLeafNode):
                    raise ValidationError("B+ height expects a leaf at the final level")
                if node.key_count == 0:
                    raise ValidationError("Non-empty B+ tree references an empty leaf")
                return BPlusDescent(node, tuple(ancestors))
            if not isinstance(node, BPlusInternalNode):
                raise ValidationError("B+ height expects an internal node")

            child_index = 0
            while (
                child_index < node.key_count
                and BPlusKeyCodec.compare(
                    self._header.key_type,
                    node.keys[child_index],
                    checked_key,
                ) < 0
            ):
                child_index += 1
            ancestors.append(BPlusPathEntry(node, child_index))
            current_page_id = self._validate_node_reference(
                node.children[child_index], "B+ child pointer"
            )

        raise ValidationError("B+ descent did not reach a leaf")

    def _read_next_leaf(
        self,
        leaf: BPlusLeafNode,
        visited: set[int],
    ) -> BPlusLeafNode | None:
        next_page_id = leaf.next_leaf_page_id
        if next_page_id is None:
            return None
        checked = self._validate_node_reference(next_page_id, "B+ next-leaf pointer")
        if checked in visited:
            raise ValidationError("Cycle detected in B+ leaf links")
        visited.add(checked)
        next_node = self._read_reachable_node(checked, "B+ next leaf")
        if not isinstance(next_node, BPlusLeafNode):
            raise ValidationError("B+ leaf link points to a non-leaf node")
        if next_node.key_count == 0:
            raise ValidationError("B+ leaf chain contains an empty leaf")
        if leaf.key_count:
            comparison = BPlusKeyCodec.compare(
                self._header.key_type, leaf.keys[-1], next_node.keys[0]
            )
            if comparison > 0:
                raise ValidationError("B+ leaf chain is not ordered")
            if comparison == 0:
                if not self._header.allow_duplicate_keys:
                    raise ValidationError(
                        "B+ leaf chain contains duplicates forbidden by its header"
                    )
                if leaf.rids[-1] >= next_node.rids[0]:
                    raise ValidationError(
                        "Equal keys are not in deterministic RID order across leaves"
                    )
        return next_node

    @staticmethod
    def _compare_entries(
        key_type: DataType,
        left_key: RecordValue,
        left_rid: RID,
        right_key: RecordValue,
        right_rid: RID,
    ) -> int:
        key_comparison = BPlusKeyCodec.compare(key_type, left_key, right_key)
        if key_comparison:
            return key_comparison
        return (left_rid > right_rid) - (left_rid < right_rid)

    def _validate_mutation_path(self, descent: BPlusDescent) -> None:
        """Validate that a captured path still reaches its reported leaf."""

        if len(descent.ancestors) != self._header.height - 1:
            raise ValidationError("B+ mutation path does not match tree height")
        child_page_id = descent.leaf.page_id
        for entry in reversed(descent.ancestors):
            if not 0 <= entry.child_index < len(entry.node.children):
                raise ValidationError("B+ mutation path child index is invalid")
            if entry.node.children[entry.child_index] != child_page_id:
                raise ValidationError("B+ mutation path does not reach its child")
            child_page_id = entry.node.page_id
        if child_page_id != self._header.root_page_id:
            raise ValidationError("B+ mutation path does not begin at the root")

    def _successor_descent(self, descent: BPlusDescent) -> BPlusDescent | None:
        """Return the structurally next leaf and its path, validating the link.

        The ancestor path is advanced like an ordered-tree cursor. This avoids
        persisted parent pointers and avoids a second root descent when a
        duplicate group crosses leaf boundaries.
        """

        self._validate_mutation_path(descent)
        ancestors = descent.ancestors
        for depth in range(len(ancestors) - 1, -1, -1):
            entry = ancestors[depth]
            next_child_index = entry.child_index + 1
            if next_child_index >= len(entry.node.children):
                continue

            next_path = list(ancestors[:depth])
            next_path.append(BPlusPathEntry(entry.node, next_child_index))
            current_page_id = self._validate_node_reference(
                entry.node.children[next_child_index],
                "B+ successor child pointer",
            )
            visited = {item.node.page_id for item in next_path}

            while len(next_path) < self._header.height - 1:
                if current_page_id in visited:
                    raise ValidationError("Cycle detected in B+ child pointers")
                visited.add(current_page_id)
                node = self._read_reachable_node(
                    current_page_id, "B+ successor child"
                )
                if not isinstance(node, BPlusInternalNode):
                    raise ValidationError(
                        "B+ height expects an internal successor node"
                    )
                next_path.append(BPlusPathEntry(node, 0))
                current_page_id = self._validate_node_reference(
                    node.children[0], "B+ successor child pointer"
                )

            if current_page_id in visited:
                raise ValidationError("Cycle detected in B+ child pointers")
            node = self._read_reachable_node(current_page_id, "B+ successor leaf")
            if not isinstance(node, BPlusLeafNode):
                raise ValidationError("B+ height expects a successor leaf")
            if node.key_count == 0:
                raise ValidationError("B+ leaf chain contains an empty leaf")
            if descent.leaf.next_leaf_page_id != node.page_id:
                raise ValidationError(
                    "B+ next-leaf link does not match structural leaf order"
                )
            return BPlusDescent(node, tuple(next_path))

        if descent.leaf.next_leaf_page_id is not None:
            raise ValidationError("B+ final leaf has an unexpected next-leaf link")
        return None

    def _locate_leaf_entry(
        self,
        key: RecordValue,
        rid: RID,
    ) -> tuple[BPlusDescent, int, bool]:
        """Locate the globally ordered insertion position for ``(key, rid)``."""

        descent = self.descend(key)
        if descent is None:  # pragma: no cover - caller separates empty state
            raise ValidationError("Cannot locate an entry in an empty B+ tree")

        while True:
            leaf = descent.leaf
            insertion_position: int | None = None
            for position, (existing_key, existing_rid) in enumerate(
                zip(leaf.keys, leaf.rids)
            ):
                key_comparison = BPlusKeyCodec.compare(
                    self._header.key_type, key, existing_key
                )
                if key_comparison == 0:
                    if rid == existing_rid:
                        return descent, position, True
                    if not self._header.allow_duplicate_keys:
                        raise DuplicateError(
                            f"Duplicate key is not allowed by this B+ index: {key!r}"
                        )
                if insertion_position is None and self._compare_entries(
                    self._header.key_type,
                    key,
                    rid,
                    existing_key,
                    existing_rid,
                ) < 0:
                    insertion_position = position

            if insertion_position is not None:
                return descent, insertion_position, False

            successor = self._successor_descent(descent)
            if successor is None:
                return descent, leaf.key_count, False

            successor_key = successor.leaf.keys[0]
            successor_rid = successor.leaf.rids[0]
            key_comparison = BPlusKeyCodec.compare(
                self._header.key_type, key, successor_key
            )
            if key_comparison == 0 and not self._header.allow_duplicate_keys:
                if rid == successor_rid:
                    return successor, 0, True
                raise DuplicateError(
                    f"Duplicate key is not allowed by this B+ index: {key!r}"
                )
            if self._compare_entries(
                self._header.key_type,
                key,
                rid,
                successor_key,
                successor_rid,
            ) < 0:
                return descent, leaf.key_count, False
            descent = successor

    def _write_header(self, header: BPlusFileHeader) -> None:
        """Persist one validated metadata image and then publish it in memory."""

        BPlusHeaderPageIO.write(self._manager, header)
        self._header = header

    def _allocate_node_page(
        self,
        free_head_page_id: int | None,
    ) -> tuple[int, int | None]:
        """Pop one validated free page, otherwise append a physical page."""

        if free_head_page_id is None:
            return self._nodes.allocate_page(), None
        if type(free_head_page_id) is not int or not (
            1 <= free_head_page_id <= self._header.node_page_count
        ):
            raise ValidationError("B+ free-list head is outside the node-page range")
        released = self._nodes.read_node(free_head_page_id)
        if not isinstance(released, BPlusFreeNode):
            raise ValidationError("B+ free-list head is not a released node page")
        next_page_id = released.next_free_page_id
        if next_page_id is not None and next_page_id in {
            self._header.root_page_id,
            self._header.first_leaf_page_id,
        }:
            raise ValidationError("B+ free list points to a live root/first leaf")
        return released.page_id, next_page_id

    def _insert_first_entry(self, key: RecordValue, rid: RID) -> None:
        page_id, free_head = self._allocate_node_page(
            self._header.free_node_head_page_id
        )
        leaf = BPlusLeafNode(
            page_id,
            self._header.key_type,
            [key],
            [rid],
        )
        self._nodes.write_node(leaf)
        updated = replace(
            self._header,
            root_page_id=page_id,
            first_leaf_page_id=page_id,
            height=1,
            entry_count=1,
            node_page_count=self._manager.allocated_page_count - 1,
            free_node_head_page_id=free_head,
        )
        self._write_header(updated)

    def _propagate_split(
        self,
        descent: BPlusDescent,
        separator: RecordValue,
        left_page_id: int,
        right_page_id: int,
        free_head_page_id: int | None,
    ) -> tuple[int, int, int | None]:
        """Insert a split result, returning root, height, and free-list head."""

        free_head = free_head_page_id

        for entry in reversed(descent.ancestors):
            parent = entry.node
            child_index = entry.child_index
            if parent.children[child_index] != left_page_id:
                raise ValidationError("B+ split path does not reference its left child")

            keys = list(parent.keys)
            children = list(parent.children)
            keys.insert(child_index, separator)
            children.insert(child_index + 1, right_page_id)

            if len(keys) <= parent.maximum_key_count:
                self._nodes.write_node(
                    BPlusInternalNode(
                        parent.page_id,
                        self._header.key_type,
                        keys,
                        children,
                    )
                )
                return self._header.root_page_id, self._header.height, free_head

            split_position = len(keys) // 2
            promoted_separator = keys[split_position]
            new_right_page_id, free_head = self._allocate_node_page(free_head)
            left = BPlusInternalNode(
                parent.page_id,
                self._header.key_type,
                keys[:split_position],
                children[: split_position + 1],
            )
            right = BPlusInternalNode(
                new_right_page_id,
                self._header.key_type,
                keys[split_position + 1 :],
                children[split_position + 1 :],
            )
            left.validate_occupancy(is_root=False)
            right.validate_occupancy(is_root=False)
            self._nodes.write_node(right)
            self._nodes.write_node(left)
            self._count_structural("internal_splits")
            separator = promoted_separator
            left_page_id = left.page_id
            right_page_id = right.page_id

        new_root_page_id, free_head = self._allocate_node_page(free_head)
        root = BPlusInternalNode(
            new_root_page_id,
            self._header.key_type,
            [separator],
            [left_page_id, right_page_id],
        )
        root.validate_occupancy(is_root=True)
        self._nodes.write_node(root)
        self._count_structural("root_splits")
        return new_root_page_id, self._header.height + 1, free_head

    def insert(self, key: RecordValue, rid: RID) -> None:
        self._require_open()
        checked_key = BPlusKeyCodec.validate(self._header.key_type, key)
        BPlusRIDCodec.encode(rid)
        if self._header.entry_count == (1 << 64) - 1:
            raise ValidationError("B+ entry count has reached the uint64 limit")

        if self._header.entry_count == 0:
            self._insert_first_entry(checked_key, rid)
            return

        descent, position, already_exists = self._locate_leaf_entry(
            checked_key, rid
        )
        if already_exists:
            return
        self._validate_mutation_path(descent)

        keys = list(descent.leaf.keys)
        rids = list(descent.leaf.rids)
        keys.insert(position, checked_key)
        rids.insert(position, rid)

        if len(keys) <= descent.leaf.maximum_key_count:
            self._nodes.write_node(
                BPlusLeafNode(
                    descent.leaf.page_id,
                    self._header.key_type,
                    keys,
                    rids,
                    next_leaf_page_id=descent.leaf.next_leaf_page_id,
                )
            )
            self._write_header(
                replace(self._header, entry_count=self._header.entry_count + 1)
            )
            return

        split_position = len(keys) // 2
        free_head = self._header.free_node_head_page_id
        new_right_page_id, free_head = self._allocate_node_page(free_head)
        left = BPlusLeafNode(
            descent.leaf.page_id,
            self._header.key_type,
            keys[:split_position],
            rids[:split_position],
            next_leaf_page_id=new_right_page_id,
        )
        right = BPlusLeafNode(
            new_right_page_id,
            self._header.key_type,
            keys[split_position:],
            rids[split_position:],
            next_leaf_page_id=descent.leaf.next_leaf_page_id,
        )
        # Even a former root leaf becomes a non-root child after this split.
        left.validate_occupancy(is_root=False)
        right.validate_occupancy(is_root=False)
        self._nodes.write_node(right)
        self._nodes.write_node(left)
        self._count_structural("leaf_splits")

        root_page_id, height, free_head = self._propagate_split(
            descent,
            right.keys[0],
            left.page_id,
            right.page_id,
            free_head,
        )
        self._write_header(
            replace(
                self._header,
                root_page_id=root_page_id,
                height=height,
                entry_count=self._header.entry_count + 1,
                node_page_count=self._manager.allocated_page_count - 1,
                free_node_head_page_id=free_head,
            )
        )

    def _locate_existing_entry(
        self,
        key: RecordValue,
        rid: RID,
    ) -> tuple[BPlusDescent, int] | None:
        """Find one exact persisted association across duplicate leaf spans."""

        descent = self.descend(key)
        if descent is None:
            return None
        while True:
            for position, (existing_key, existing_rid) in enumerate(
                zip(descent.leaf.keys, descent.leaf.rids)
            ):
                comparison = self._compare_entries(
                    self._header.key_type,
                    existing_key,
                    existing_rid,
                    key,
                    rid,
                )
                if comparison == 0:
                    return descent, position
                if comparison > 0:
                    return None
            successor = self._successor_descent(descent)
            if successor is None:
                return None
            if self._compare_entries(
                self._header.key_type,
                successor.leaf.keys[0],
                successor.leaf.rids[0],
                key,
                rid,
            ) > 0:
                return None
            descent = successor

    def _update_minimum_in_ancestors(
        self,
        ancestors: tuple[BPlusPathEntry, ...],
        minimum: RecordValue,
    ) -> None:
        """Update the first separator that materializes one subtree minimum."""

        for entry in reversed(ancestors):
            if entry.child_index == 0:
                continue
            keys = list(entry.node.keys)
            separator_index = entry.child_index - 1
            if BPlusKeyCodec.compare(
                self._header.key_type,
                keys[separator_index],
                minimum,
            ) == 0:
                return
            keys[separator_index] = minimum
            self._nodes.write_node(
                BPlusInternalNode(
                    entry.node.page_id,
                    self._header.key_type,
                    keys,
                    entry.node.children,
                )
            )
            return

    def _subtree_minimum(self, page_id: int) -> RecordValue:
        """Read the left edge of one live subtree and return its minimum key."""

        current_page_id = page_id
        visited: set[int] = set()
        while True:
            if current_page_id in visited:
                raise ValidationError("Cycle detected while reading a B+ subtree minimum")
            visited.add(current_page_id)
            node = self._read_reachable_node(current_page_id, "B+ subtree")
            if isinstance(node, BPlusLeafNode):
                if node.key_count == 0:
                    raise ValidationError("A live B+ subtree has an empty leaf")
                return node.keys[0]
            if not isinstance(node, BPlusInternalNode):  # pragma: no cover
                raise ValidationError("A live B+ subtree contains an invalid node")
            current_page_id = self._validate_node_reference(
                node.children[0], "B+ subtree child pointer"
            )

    def _read_leaf_sibling(self, page_id: int) -> BPlusLeafNode:
        node = self._read_reachable_node(page_id, "B+ leaf sibling")
        if not isinstance(node, BPlusLeafNode):
            raise ValidationError("B+ leaf sibling pointer targets a non-leaf node")
        node.validate_occupancy(is_root=False)
        return node

    def _read_internal_sibling(self, page_id: int) -> BPlusInternalNode:
        node = self._read_reachable_node(page_id, "B+ internal sibling")
        if not isinstance(node, BPlusInternalNode):
            raise ValidationError(
                "B+ internal sibling pointer targets a non-internal node"
            )
        node.validate_occupancy(is_root=False)
        return node

    def _register_free_page(
        self,
        page_id: int,
        free_head_page_id: int | None,
        *,
        allow_header_reference: bool = False,
    ) -> int:
        if not allow_header_reference and page_id in {
            self._header.root_page_id, self._header.first_leaf_page_id
        }:
            raise ValidationError("A live B+ root/first leaf cannot be released")
        self._nodes.write_node(
            BPlusFreeNode(page_id, next_free_page_id=free_head_page_id)
        )
        return page_id

    def _shrink_root(
        self,
        root_page_id: int,
        height: int,
        free_head_page_id: int | None,
    ) -> tuple[int, int, int | None]:
        """Collapse every zero-key internal root and release its old page."""

        root_id = root_page_id
        current_height = height
        free_head = free_head_page_id
        while current_height > 1:
            root = self._nodes.read_node(root_id)
            if not isinstance(root, BPlusInternalNode):
                raise ValidationError("A multi-level B+ root must be internal")
            if root.key_count != 0:
                root.validate_occupancy(is_root=True)
                break
            if len(root.children) != 1:
                raise ValidationError("An empty internal root requires one child")
            child_page_id = root.children[0]
            free_head = self._register_free_page(
                root.page_id,
                free_head,
                allow_header_reference=True,
            )
            root_id = child_page_id
            current_height -= 1
            self._count_structural("root_shrinks")
        return root_id, current_height, free_head

    def _repair_internal_underflow(
        self,
        node: BPlusInternalNode,
        ancestors: tuple[BPlusPathEntry, ...],
        subtree_minimum: RecordValue,
        free_head_page_id: int | None,
    ) -> int | None:
        """Repair one internal underflow and propagate it toward the root."""

        path = ancestors
        current = node
        current_minimum = subtree_minimum
        free_head = free_head_page_id

        while True:
            if not path:
                self._nodes.write_node(current)
                return free_head
            if current.key_count >= current.minimum_key_count:
                current.validate_occupancy(is_root=False)
                self._nodes.write_node(current)
                self._update_minimum_in_ancestors(path, current_minimum)
                return free_head
            if current.minimum_key_count - current.key_count != 1:
                raise ValidationError("B+ internal node has an unexpected underflow")

            parent_entry = path[-1]
            parent = parent_entry.node
            child_index = parent_entry.child_index
            if parent.children[child_index] != current.page_id:
                raise ValidationError(
                    "B+ internal repair path does not reference its child"
                )

            parent_keys = list(parent.keys)
            parent_children = list(parent.children)
            if child_index > 0:
                parent_keys[child_index - 1] = current_minimum

            left = (
                self._read_internal_sibling(parent.children[child_index - 1])
                if child_index > 0
                else None
            )
            right = (
                self._read_internal_sibling(parent.children[child_index + 1])
                if child_index + 1 < len(parent.children)
                else None
            )

            if left is not None and left.key_count > left.minimum_key_count:
                borrowed_minimum = left.keys[-1]
                updated_left = BPlusInternalNode(
                    left.page_id,
                    self._header.key_type,
                    left.keys[:-1],
                    left.children[:-1],
                )
                updated_current = BPlusInternalNode(
                    current.page_id,
                    self._header.key_type,
                    [parent_keys[child_index - 1], *current.keys],
                    [left.children[-1], *current.children],
                )
                parent_keys[child_index - 1] = borrowed_minimum
                updated_parent = BPlusInternalNode(
                    parent.page_id,
                    self._header.key_type,
                    parent_keys,
                    parent_children,
                )
                updated_left.validate_occupancy(is_root=False)
                updated_current.validate_occupancy(is_root=False)
                self._nodes.write_node(updated_left)
                self._nodes.write_node(updated_current)
                self._nodes.write_node(updated_parent)
                self._count_structural("internal_redistributions")
                return free_head

            if right is not None and right.key_count > right.minimum_key_count:
                updated_current = BPlusInternalNode(
                    current.page_id,
                    self._header.key_type,
                    [*current.keys, parent_keys[child_index]],
                    [*current.children, right.children[0]],
                )
                updated_right = BPlusInternalNode(
                    right.page_id,
                    self._header.key_type,
                    right.keys[1:],
                    right.children[1:],
                )
                parent_keys[child_index] = right.keys[0]
                updated_parent = BPlusInternalNode(
                    parent.page_id,
                    self._header.key_type,
                    parent_keys,
                    parent_children,
                )
                updated_current.validate_occupancy(is_root=False)
                updated_right.validate_occupancy(is_root=False)
                self._nodes.write_node(updated_current)
                self._nodes.write_node(updated_right)
                self._nodes.write_node(updated_parent)
                if child_index == 0:
                    self._update_minimum_in_ancestors(path[:-1], current_minimum)
                self._count_structural("internal_redistributions")
                return free_head

            if left is not None:
                merged = BPlusInternalNode(
                    left.page_id,
                    self._header.key_type,
                    [*left.keys, parent_keys[child_index - 1], *current.keys],
                    [*left.children, *current.children],
                )
                parent_keys.pop(child_index - 1)
                parent_children.pop(child_index)
                released_page_id = current.page_id
            elif right is not None:
                merged = BPlusInternalNode(
                    current.page_id,
                    self._header.key_type,
                    [*current.keys, parent_keys[child_index], *right.keys],
                    [*current.children, *right.children],
                )
                parent_keys.pop(child_index)
                parent_children.pop(child_index + 1)
                released_page_id = right.page_id
            else:
                raise ValidationError("Underfull B+ internal node has no sibling")

            merged.validate_occupancy(is_root=False)
            updated_parent = BPlusInternalNode(
                parent.page_id,
                self._header.key_type,
                parent_keys,
                parent_children,
            )
            self._nodes.write_node(merged)
            free_head = self._register_free_page(released_page_id, free_head)
            self._nodes.write_node(updated_parent)
            self._count_structural("internal_merges")

            current = updated_parent
            current_minimum = self._subtree_minimum(current.children[0])
            path = path[:-1]

    def _repair_leaf_underflow(
        self,
        descent: BPlusDescent,
        leaf: BPlusLeafNode,
        minimum_changed: bool,
        free_head_page_id: int | None,
    ) -> int | None:
        """Borrow or merge with a same-parent leaf, preferring the left side."""

        parent_entry = descent.ancestors[-1]
        parent = parent_entry.node
        child_index = parent_entry.child_index
        if parent.children[child_index] != leaf.page_id:
            raise ValidationError("B+ leaf repair path does not reference its child")
        needed = leaf.minimum_key_count - leaf.key_count
        if needed != 1:
            raise ValidationError("B+ leaf has an unexpected underflow")

        left = (
            self._read_leaf_sibling(parent.children[child_index - 1])
            if child_index > 0
            else None
        )
        right = (
            self._read_leaf_sibling(parent.children[child_index + 1])
            if child_index + 1 < len(parent.children)
            else None
        )
        if left is not None and left.next_leaf_page_id != leaf.page_id:
            raise ValidationError("Left B+ leaf sibling has a broken next link")
        if right is not None and leaf.next_leaf_page_id != right.page_id:
            raise ValidationError("Right B+ leaf sibling has a broken next link")

        parent_keys = list(parent.keys)
        if left is not None and left.key_count > left.minimum_key_count:
            updated_left = BPlusLeafNode(
                left.page_id,
                self._header.key_type,
                left.keys[:-1],
                left.rids[:-1],
                next_leaf_page_id=left.next_leaf_page_id,
            )
            updated_leaf = BPlusLeafNode(
                leaf.page_id,
                self._header.key_type,
                [left.keys[-1], *leaf.keys],
                [left.rids[-1], *leaf.rids],
                next_leaf_page_id=leaf.next_leaf_page_id,
            )
            parent_keys[child_index - 1] = updated_leaf.keys[0]
            updated_parent = BPlusInternalNode(
                parent.page_id,
                self._header.key_type,
                parent_keys,
                parent.children,
            )
            updated_left.validate_occupancy(is_root=False)
            updated_leaf.validate_occupancy(is_root=False)
            self._nodes.write_node(updated_left)
            self._nodes.write_node(updated_leaf)
            self._nodes.write_node(updated_parent)
            self._count_structural("leaf_redistributions")
            return free_head_page_id

        if right is not None and right.key_count > right.minimum_key_count:
            updated_leaf = BPlusLeafNode(
                leaf.page_id,
                self._header.key_type,
                [*leaf.keys, right.keys[0]],
                [*leaf.rids, right.rids[0]],
                next_leaf_page_id=leaf.next_leaf_page_id,
            )
            updated_right = BPlusLeafNode(
                right.page_id,
                self._header.key_type,
                right.keys[1:],
                right.rids[1:],
                next_leaf_page_id=right.next_leaf_page_id,
            )
            parent_keys[child_index] = updated_right.keys[0]
            if child_index > 0:
                parent_keys[child_index - 1] = updated_leaf.keys[0]
            updated_parent = BPlusInternalNode(
                parent.page_id,
                self._header.key_type,
                parent_keys,
                parent.children,
            )
            updated_leaf.validate_occupancy(is_root=False)
            updated_right.validate_occupancy(is_root=False)
            self._nodes.write_node(updated_leaf)
            self._nodes.write_node(updated_right)
            self._nodes.write_node(updated_parent)
            if child_index == 0 and minimum_changed:
                self._update_minimum_in_ancestors(
                    descent.ancestors[:-1], updated_leaf.keys[0]
                )
            self._count_structural("leaf_redistributions")
            return free_head_page_id

        if left is not None:
            merged = BPlusLeafNode(
                left.page_id,
                self._header.key_type,
                [*left.keys, *leaf.keys],
                [*left.rids, *leaf.rids],
                next_leaf_page_id=leaf.next_leaf_page_id,
            )
            parent_keys.pop(child_index - 1)
            parent_children = list(parent.children)
            parent_children.pop(child_index)
            released_page_id = leaf.page_id
            parent_minimum_changed = False
        elif right is not None:
            merged = BPlusLeafNode(
                leaf.page_id,
                self._header.key_type,
                [*leaf.keys, *right.keys],
                [*leaf.rids, *right.rids],
                next_leaf_page_id=right.next_leaf_page_id,
            )
            parent_keys.pop(child_index)
            parent_children = list(parent.children)
            parent_children.pop(child_index + 1)
            released_page_id = right.page_id
            parent_minimum_changed = minimum_changed
        else:
            raise ValidationError("Underfull B+ leaf has no sibling")

        merged.validate_occupancy(is_root=False)
        updated_parent = BPlusInternalNode(
            parent.page_id,
            self._header.key_type,
            parent_keys,
            parent_children,
        )
        self._nodes.write_node(merged)
        free_head = self._register_free_page(
            released_page_id, free_head_page_id
        )
        self._nodes.write_node(updated_parent)
        self._count_structural("leaf_merges")

        parent_path = descent.ancestors[:-1]
        if not parent_path:
            return free_head
        parent_minimum = self._subtree_minimum(updated_parent.children[0])
        if updated_parent.key_count >= updated_parent.minimum_key_count:
            updated_parent.validate_occupancy(is_root=False)
            if parent_minimum_changed:
                self._update_minimum_in_ancestors(parent_path, parent_minimum)
            return free_head
        return self._repair_internal_underflow(
            updated_parent,
            parent_path,
            parent_minimum,
            free_head,
        )

    def delete(self, key: RecordValue, rid: RID) -> None:
        self._require_open()
        checked_key = BPlusKeyCodec.validate(self._header.key_type, key)
        BPlusRIDCodec.encode(rid)
        if self._header.entry_count == 0:
            raise InvalidReferenceError(f"Unknown B+ key/RID association: {key!r}, {rid!r}")

        located = self._locate_existing_entry(checked_key, rid)
        if located is None:
            raise InvalidReferenceError(
                f"Unknown B+ key/RID association: {key!r}, {rid!r}"
            )
        descent, position = located
        self._validate_mutation_path(descent)
        if self._header.entry_count == 1:
            if descent.ancestors or descent.leaf.key_count != 1:
                raise ValidationError(
                    "Single-entry B+ metadata does not describe one root leaf"
                )
            free_head = self._register_free_page(
                descent.leaf.page_id,
                self._header.free_node_head_page_id,
                allow_header_reference=True,
            )
            self._write_header(
                replace(
                    self._header,
                    root_page_id=None,
                    first_leaf_page_id=None,
                    height=0,
                    entry_count=0,
                    free_node_head_page_id=free_head,
                )
            )
            self._count_structural("root_shrinks")
            return

        keys = list(descent.leaf.keys)
        rids = list(descent.leaf.rids)
        removed_first_key = position == 0
        old_minimum = keys[0]
        keys.pop(position)
        rids.pop(position)
        updated_leaf = BPlusLeafNode(
            descent.leaf.page_id,
            self._header.key_type,
            keys,
            rids,
            next_leaf_page_id=descent.leaf.next_leaf_page_id,
        )
        minimum_changed = (
            removed_first_key
            and updated_leaf.key_count > 0
            and BPlusKeyCodec.compare(
                self._header.key_type, old_minimum, updated_leaf.keys[0]
            ) != 0
        )

        free_head = self._header.free_node_head_page_id
        if not descent.ancestors:
            self._nodes.write_node(updated_leaf)
        elif updated_leaf.key_count >= updated_leaf.minimum_key_count:
            updated_leaf.validate_occupancy(is_root=False)
            self._nodes.write_node(updated_leaf)
            if minimum_changed:
                self._update_minimum_in_ancestors(
                    descent.ancestors, updated_leaf.keys[0]
                )
        else:
            free_head = self._repair_leaf_underflow(
                descent,
                updated_leaf,
                minimum_changed,
                free_head,
            )

        root_page_id, height, free_head = self._shrink_root(
            self._header.root_page_id,
            self._header.height,
            free_head,
        )
        self._write_header(
            replace(
                self._header,
                root_page_id=root_page_id,
                height=height,
                entry_count=self._header.entry_count - 1,
                free_node_head_page_id=free_head,
            )
        )

    def validate_structure(self) -> BPlusValidationReport:
        """Read the complete index and prove its persisted global invariants."""

        self._require_open()
        # Re-run header field validation even though normal construction/opening
        # already does so; callers use this method after deliberate corruption.
        self._header.serialize()
        live_pages: set[int] = set()
        leaf_nodes: list[BPlusLeafNode] = []
        internal_count = 0
        observed_entries = 0

        def checked_page_id(page_id: object, label: str) -> int:
            if type(page_id) is not int or not (
                1 <= page_id <= self._header.node_page_count
            ):
                raise ValidationError(f"{label} is outside the B+ node-page range")
            return page_id

        def visit(
            page_id: object,
            depth: int,
            *,
            is_root: bool,
        ) -> tuple[tuple[RecordValue, RID], tuple[RecordValue, RID]]:
            nonlocal internal_count, observed_entries
            checked = checked_page_id(page_id, "B+ child")
            if checked in live_pages:
                raise ValidationError("B+ child graph has a cycle or shared node")
            live_pages.add(checked)
            node = self._nodes.read_node(checked)
            if isinstance(node, BPlusFreeNode):
                raise ValidationError("B+ live tree references a released page")

            if isinstance(node, BPlusLeafNode):
                if depth != self._header.height:
                    raise ValidationError("B+ leaves do not share the header depth")
                if node.key_count == 0:
                    raise ValidationError("A non-empty B+ tree contains an empty leaf")
                node.validate_occupancy(is_root=is_root)
                if not self._header.allow_duplicate_keys:
                    for previous, current in zip(node.keys, node.keys[1:]):
                        if BPlusKeyCodec.compare(
                            self._header.key_type, previous, current
                        ) == 0:
                            raise ValidationError(
                                "Unique B+ index contains duplicate keys"
                            )
                observed_entries += node.key_count
                leaf_nodes.append(node)
                return (node.keys[0], node.rids[0]), (node.keys[-1], node.rids[-1])

            if not isinstance(node, BPlusInternalNode):  # pragma: no cover
                raise ValidationError("B+ tree contains an unknown node model")
            if depth >= self._header.height:
                raise ValidationError("B+ header height expects a leaf")
            node.validate_occupancy(is_root=is_root)
            internal_count += 1
            child_ranges = [
                visit(child, depth + 1, is_root=False)
                for child in node.children
            ]
            for index, separator in enumerate(node.keys):
                right_minimum = child_ranges[index + 1][0]
                if BPlusKeyCodec.compare(
                    self._header.key_type, separator, right_minimum[0]
                ) != 0:
                    raise ValidationError("B+ right-min separator is incorrect")
                left_maximum = child_ranges[index][1]
                if self._compare_entries(
                    self._header.key_type,
                    left_maximum[0],
                    left_maximum[1],
                    right_minimum[0],
                    right_minimum[1],
                ) >= 0:
                    raise ValidationError(
                        "B+ child key/RID ranges overlap or are out of order"
                    )
                if (
                    not self._header.allow_duplicate_keys
                    and BPlusKeyCodec.compare(
                        self._header.key_type,
                        left_maximum[0],
                        right_minimum[0],
                    ) == 0
                ):
                    raise ValidationError("Unique B+ index contains duplicate keys")
            return child_ranges[0][0], child_ranges[-1][1]

        if self._header.entry_count == 0:
            if any(
                value is not None
                for value in (
                    self._header.root_page_id,
                    self._header.first_leaf_page_id,
                )
            ) or self._header.height != 0:
                raise ValidationError("Invalid empty B+ tree state")
        else:
            if self._header.root_page_id is None or self._header.height == 0:
                raise ValidationError("Non-empty B+ tree has no root")
            visit(self._header.root_page_id, 1, is_root=True)
            if not leaf_nodes:
                raise ValidationError("Non-empty B+ tree has no leaves")
            if self._header.first_leaf_page_id != leaf_nodes[0].page_id:
                raise ValidationError("B+ first-leaf pointer is incorrect")
            for index, leaf in enumerate(leaf_nodes):
                expected_next = (
                    leaf_nodes[index + 1].page_id
                    if index + 1 < len(leaf_nodes)
                    else None
                )
                if leaf.next_leaf_page_id != expected_next:
                    raise ValidationError(
                        "B+ leaf chain does not match structural leaf order"
                    )
            if observed_entries != self._header.entry_count:
                raise ValidationError(
                    "B+ header entry count does not match reachable leaves"
                )

        free_pages: set[int] = set()
        free_page_id = self._header.free_node_head_page_id
        while free_page_id is not None:
            checked = checked_page_id(free_page_id, "B+ free-list page")
            if checked in live_pages:
                raise ValidationError("B+ free list overlaps the live tree")
            if checked in free_pages:
                raise ValidationError("Cycle detected in the B+ free list")
            free_pages.add(checked)
            free_node = self._nodes.read_node(checked)
            if not isinstance(free_node, BPlusFreeNode):
                raise ValidationError("B+ free list references a live node")
            free_page_id = free_node.next_free_page_id

        expected_pages = set(range(1, self._header.node_page_count + 1))
        if live_pages | free_pages != expected_pages:
            raise ValidationError("B+ file contains untracked node pages")
        return BPlusValidationReport(
            height=self._header.height,
            entry_count=observed_entries,
            leaf_count=len(leaf_nodes),
            internal_count=internal_count,
            free_page_count=len(free_pages),
        )

    def search(self, key: RecordValue) -> Generator[RID, None, None]:
        self._require_open()
        checked_key = BPlusKeyCodec.validate(self._header.key_type, key)

        def iterator() -> Generator[RID, None, None]:
            self._require_open()
            descent = self.descend(checked_key)
            if descent is None:
                return
            leaf = descent.leaf
            visited = {leaf.page_id}
            while True:
                self._require_open()
                for leaf_key, rid in zip(leaf.keys, leaf.rids):
                    comparison = BPlusKeyCodec.compare(
                        self._header.key_type, leaf_key, checked_key
                    )
                    if comparison == 0:
                        yield rid
                    elif comparison > 0:
                        return
                next_leaf = self._read_next_leaf(leaf, visited)
                if next_leaf is None:
                    return
                leaf = next_leaf

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
        if type(include_lower) is not bool or type(include_upper) is not bool:
            raise InvalidTypeError("B+ range inclusion flags must be booleans")
        checked_lower = (
            None
            if lower is None
            else BPlusKeyCodec.validate(self._header.key_type, lower)
        )
        checked_upper = (
            None
            if upper is None
            else BPlusKeyCodec.validate(self._header.key_type, upper)
        )
        if (
            checked_lower is not None
            and checked_upper is not None
            and BPlusKeyCodec.compare(
                self._header.key_type, checked_lower, checked_upper
            ) > 0
        ):
            raise ValidationError("B+ range lower bound exceeds upper bound")

        def iterator() -> Generator[RID, None, None]:
            self._require_open()
            if self._header.entry_count == 0:
                return
            if (
                checked_lower is not None
                and checked_upper is not None
                and BPlusKeyCodec.compare(
                    self._header.key_type, checked_lower, checked_upper
                ) == 0
                and (not include_lower or not include_upper)
            ):
                return

            if checked_lower is None:
                first_page_id = self._validate_node_reference(
                    self._header.first_leaf_page_id, "B+ first leaf"
                )
                first_node = self._read_reachable_node(first_page_id, "B+ first leaf")
                if not isinstance(first_node, BPlusLeafNode):
                    raise ValidationError("B+ first-leaf pointer targets a non-leaf")
                leaf = first_node
            else:
                descent = self.descend(checked_lower)
                if descent is None:
                    return
                leaf = descent.leaf
            if leaf.key_count == 0:
                raise ValidationError("Non-empty B+ tree references an empty leaf")

            visited = {leaf.page_id}
            yielded = 0
            full_scan = checked_lower is None and checked_upper is None
            while True:
                self._require_open()
                for key, rid in zip(leaf.keys, leaf.rids):
                    if checked_lower is not None:
                        lower_comparison = BPlusKeyCodec.compare(
                            self._header.key_type, key, checked_lower
                        )
                        if lower_comparison < 0 or (
                            lower_comparison == 0 and not include_lower
                        ):
                            continue
                    if checked_upper is not None:
                        upper_comparison = BPlusKeyCodec.compare(
                            self._header.key_type, key, checked_upper
                        )
                        if upper_comparison > 0 or (
                            upper_comparison == 0 and not include_upper
                        ):
                            return
                    yielded += 1
                    yield rid

                next_leaf = self._read_next_leaf(leaf, visited)
                if next_leaf is None:
                    if full_scan and yielded != self._header.entry_count:
                        raise ValidationError(
                            "B+ header entry count does not match the leaf chain"
                        )
                    return
                leaf = next_leaf

        return iterator()
