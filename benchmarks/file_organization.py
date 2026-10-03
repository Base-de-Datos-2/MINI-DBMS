"""Task 10.5: Heap File versus Paged Sequential File (REQUIREMENTS.md §9.1).

For one dataset size and repetition it measures, on fresh files:

* insertion: loading every row one by one in the dataset's random key order
  (both files), plus an ascending-order load of the sequential file;
* primary-key search: present and absent keys. The Heap has no order, so a
  search scans until the key is found (or the end); the sequential file
  locates its first candidate page by binary search;
* disk space after loading;
* reorganization: after lazily deleting a fixed fraction of rows, the
  sequential file's wasted-space ratio and ``reorganize()`` time and sizes.
  The Heap has no reorganization; its counterpart is free-space reuse, so the
  same number of new rows is inserted after the deletions and its growth is
  recorded.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import random

from engine.storage import HeapFile, PagedSequentialFile, Record

from .datasets import KEY_COLUMN, SCHEMA, generate
from .harness import ResultWriter, file_bytes, timed, workspace


EXPERIMENT = "file_organization"
DELETE_FRACTION = 0.40


def _records(rows):
    return [Record(SCHEMA, list(row)) for row in rows]


def _load(storage, records) -> None:
    for record in records:
        storage.insert(record)
    storage.flush()


def _heap_lookup(heap: HeapFile, key: int) -> bool:
    with closing(heap.scan()) as rows:
        for _, record in rows:
            if record[KEY_COLUMN] == key:
                return True  # keys are unique: stop at the first match
    return False


def _sequential_lookup(sequential: PagedSequentialFile, key: int) -> bool:
    with closing(sequential.search(key)) as rows:
        return any(True for _ in rows)


def run(
    size: int,
    repetition: int,
    writer: ResultWriter,
    workdir: Path,
    *,
    present_keys: int = 100,
    absent_keys: int = 20,
) -> None:
    rows = generate(size)
    records = _records(rows)
    rng = random.Random(size * 1_000 + repetition)
    present = rng.sample([row[0] for row in rows], min(present_keys, size))
    absent = [size + offset for offset in range(1, absent_keys + 1)]
    victims = set(rng.sample([row[0] for row in rows], int(size * DELETE_FRACTION)))
    extra = _records(
        (size + absent_keys + offset, "Nuevo Registro", "CS", 20, 50)
        for offset in range(1, len(victims) + 1)
    )

    def record(structure, operation, elapsed, count=None, **values):
        writer.record(
            experiment=EXPERIMENT, structure=structure, operation=operation,
            size=size, repetition=repetition, elapsed_seconds=elapsed, count=count,
            **values,
        )

    with workspace(workdir, f"files-{size}-{repetition}") as directory:
        # ---------------------------------------------------------- Heap File
        heap_path = directory / "table.heap"
        heap = HeapFile.create(heap_path, SCHEMA)
        try:
            _, elapsed = timed(lambda: _load(heap, records))
            record("heap", "load", elapsed, size,
                   file_bytes=file_bytes(heap_path), data_pages=heap.data_page_count)
            for label, keys in (("pk_search_present", present), ("pk_search_absent", absent)):
                found, elapsed = timed(lambda keys=keys: [_heap_lookup(heap, key) for key in keys])
                record("heap", label, elapsed, len(keys), found=sum(found))
            doomed = [rid for rid, item in heap.scan() if item.values[0] in victims]
            _, elapsed = timed(lambda: [heap.delete(rid) for rid in doomed])
            record("heap", "delete_fraction", elapsed, len(doomed),
                   delete_fraction=DELETE_FRACTION, file_bytes=file_bytes(heap_path))
            before = file_bytes(heap_path)
            _, elapsed = timed(lambda: _load(heap, extra))
            record("heap", "reinsert_after_delete", elapsed, len(extra),
                   file_bytes_before=before, file_bytes=file_bytes(heap_path),
                   data_pages=heap.data_page_count)
        finally:
            heap.close()

        # -------------------------------------------- Paged Sequential File
        for label, ordered in (("load", records), ("load_ascending", sorted(records, key=lambda r: r.values[0]))):
            path = directory / f"{label}.seq"
            sequential = PagedSequentialFile.create(
                path, SCHEMA, KEY_COLUMN, allow_duplicate_keys=False,
            )
            try:
                _, elapsed = timed(lambda: _load(sequential, ordered))
                record("sequential", label, elapsed, size,
                       file_bytes=file_bytes(path), data_pages=sequential.data_page_count)
                if label != "load":
                    continue
                for operation, keys in (("pk_search_present", present), ("pk_search_absent", absent)):
                    found, elapsed = timed(
                        lambda keys=keys: [_sequential_lookup(sequential, key) for key in keys]
                    )
                    record("sequential", operation, elapsed, len(keys), found=sum(found))
                doomed = [rid for rid, item in sequential.scan() if item.values[0] in victims]
                _, elapsed = timed(lambda: [sequential.delete(rid) for rid in doomed])
                waste = sequential.wasted_space_ratio()
                record("sequential", "delete_fraction", elapsed, len(doomed),
                       delete_fraction=DELETE_FRACTION, wasted_space_ratio=waste,
                       should_reorganize=sequential.should_reorganize(),
                       file_bytes=file_bytes(path))
                metrics, elapsed = timed(sequential.reorganize)
                record("sequential", "reorganize", elapsed, sequential.record_count,
                       file_bytes_before=metrics.file_size_before,
                       file_bytes=metrics.file_size_after,
                       pages_read=metrics.pages_read, pages_written=metrics.pages_written,
                       wasted_space_ratio=sequential.wasted_space_ratio(),
                       data_pages=sequential.data_page_count)
            finally:
                sequential.close()
