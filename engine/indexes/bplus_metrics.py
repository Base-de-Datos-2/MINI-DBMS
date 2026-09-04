"""Measured results produced by persistent B+ operations."""

from dataclasses import dataclass

from engine.storage.metrics import ReorganizationMetrics


@dataclass(frozen=True, slots=True)
class BPlusBuildMetrics:
    """Actual elapsed time, I/O deltas, and final size of one index build."""

    elapsed_seconds: float
    entries_indexed: int
    storage_pages_read: int
    index_pages_read: int
    index_pages_written: int
    index_pages_allocated: int
    index_file_size: int


@dataclass(frozen=True, slots=True)
class BPlusStructuralMetrics:
    """In-memory counters for structural mutations in one open tree session.

    Page reads, writes, and allocations remain the responsibility of
    :class:`PageManager`.  These counters describe logical B+ events and are
    intentionally reset on reopen because they are measurement data, not
    persistent tree state.
    """

    leaf_splits: int = 0
    internal_splits: int = 0
    root_splits: int = 0
    leaf_redistributions: int = 0
    internal_redistributions: int = 0
    leaf_merges: int = 0
    internal_merges: int = 0
    root_shrinks: int = 0

    @property
    def node_splits(self) -> int:
        return self.leaf_splits + self.internal_splits

    @property
    def redistributions(self) -> int:
        return self.leaf_redistributions + self.internal_redistributions

    @property
    def node_merges(self) -> int:
        return self.leaf_merges + self.internal_merges


@dataclass(frozen=True, slots=True)
class ClusteredReorganizationMetrics:
    """Measurements for the physical rewrite and mandatory B+ rebuild."""

    storage: ReorganizationMetrics
    index: BPlusBuildMetrics

    @property
    def elapsed_seconds(self) -> float:
        return self.storage.elapsed_seconds + self.index.elapsed_seconds
