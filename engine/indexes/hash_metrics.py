"""Measured results and session counters for Extendible Hash indexes."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HashBuildMetrics:
    """Actual elapsed time, source reads, and final physical build costs."""

    elapsed_seconds: float
    associations_indexed: int
    storage_pages_read: int
    index_pages_read: int
    index_pages_written: int
    index_pages_allocated: int
    index_file_size: int


@dataclass(frozen=True, slots=True)
class HashStructuralMetrics:

    """Estos valores no se persisten : describen el trabajo realizado por el tiempo de ejecución actual, mientras que el header sigue siendo la fuente de verdad para
    la topología duradera."""

    bucket_splits: int = 0
    directory_doublings: int = 0
    bucket_merges: int = 0
    directory_shrinks: int = 0
    associations_inspected: int = 0


@dataclass(frozen=True, slots=True)
class HashMetrics:
    #snapshot inmutable de métricas de hash extendible, combinando I/O tipado, estructura y tamaño actual.

    directory_page_reads: int
    directory_page_writes: int
    directory_page_allocations: int
    bucket_page_reads: int
    bucket_page_writes: int
    bucket_page_allocations: int
    bucket_page_frees: int
    bucket_splits: int
    directory_doublings: int
    bucket_merges: int
    directory_shrinks: int
    associations_inspected: int
    current_global_depth: int
    current_live_bucket_count: int
    allocated_index_pages: int
    allocated_index_bytes: int
