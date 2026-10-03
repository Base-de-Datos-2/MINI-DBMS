"""Tasks 10.6–10.8: clustered B+, unclustered B+ and Extendible Hashing.

REQUIREMENTS.md §9.2 asks for exact-equality and range searches, sorting,
index construction time, query time, extra disk space and behavior under
frequent insertions/deletions. For one size and repetition this module:

* loads the dataset once into a Heap File and a Paged Sequential File (load
  time is the file-organization experiment's subject, not this one's);
* builds each index on its own copy of the base file, so mutations made by
  one structure never affect another: unclustered B+ and Hash on a Heap, the
  clustered B+ on the Paged Sequential File it orders;
* measures equality (present/absent keys), ranges of three selectivities and
  full ordered retrieval. Extendible Hashing has no order: its range queries
  and sorting are measured as the work the engine really does without an
  ordered index, a Heap scan with a filter and the SQL engine's ExternalSort;
* runs a mixed insert/delete workload bounded by operations and by a time
  budget, and validates each structure afterwards. The clustered index must
  rebuild after every insertion because sequential RIDs may move, so it may
  finish fewer operations within the budget; the result records how many.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import random
import shutil
from time import perf_counter

from engine.catalog import Catalog, TableMetadata
from engine.indexes.clustered_bplus import ClusteredBPlusIndex
from engine.indexes.unclustered_bplus import UnclusteredBPlusIndex
from engine.indexes.unclustered_hash import UnclusteredHashIndex
from engine.operators.context import DEFAULT_BUDGET_BYTES
from engine.query import QueryEnvironment, SqlEngine
from engine.storage import HeapFile, PagedSequentialFile, Record

from .datasets import KEY_COLUMN, SCHEMA, generate
from .harness import ResultWriter, file_bytes, timed, workspace


EXPERIMENT = "indexes"
SELECTIVITIES = (0.001, 0.01, 0.10)
CLUSTERED = "clustered_bplus"
UNCLUSTERED = "unclustered_bplus"
HASH = "extendible_hash"


def _consume(iterator) -> int:
    with closing(iterator) as rows:
        return sum(1 for _ in rows)


def _heap_range_scan(heap: HeapFile, low: int, high: int) -> int:
    with closing(heap.scan()) as rows:
        return sum(1 for _, record in rows if low <= record[KEY_COLUMN] <= high)


def _sql_order_by(heap: HeapFile) -> tuple[int, list[str]]:
    """Sort the whole table with the engine's real planner and operators."""

    catalog = Catalog()
    catalog.register_table(TableMetadata("t", SCHEMA))
    environment = QueryEnvironment(catalog)
    environment.register_storage("t", heap)
    engine = SqlEngine(environment)
    rows = 0
    with engine.execute(f"SELECT * FROM t ORDER BY {KEY_COLUMN}") as result:
        while batch := result.fetchmany(1_000):
            rows += len(batch)
        report = result.report.runtime
    operators = []
    node = None if report is None else report.root
    while node is not None:
        operators.append(node.name)
        node = node.children[0] if node.children else None
    engine.close()
    return rows, operators


def run(
    size: int,
    repetition: int,
    writer: ResultWriter,
    workdir: Path,
    *,
    present_keys: int = 200,
    absent_keys: int = 50,
    ranges_per_selectivity: int = 10,
    workload_operations: int = 200,
    workload_budget_seconds: float = 60.0,
) -> None:
    rows = generate(size)
    records = [Record(SCHEMA, list(row)) for row in rows]
    keys = [row[0] for row in rows]
    rng = random.Random(size * 7_919 + repetition)
    present = rng.sample(keys, min(present_keys, size))
    absent = [size + offset for offset in range(1, absent_keys + 1)]
    ranges = {
        selectivity: [
            (low, low + max(1, int(size * selectivity)) - 1)
            for low in (
                rng.randint(1, max(1, size - max(1, int(size * selectivity)) + 1))
                for _ in range(ranges_per_selectivity)
            )
        ]
        for selectivity in SELECTIVITIES
    }

    def record(structure, operation, elapsed, count=None, **values):
        writer.record(
            experiment=EXPERIMENT, structure=structure, operation=operation,
            size=size, repetition=repetition, elapsed_seconds=elapsed, count=count,
            **values,
        )

    with workspace(workdir, f"indexes-{size}-{repetition}") as directory:
        # Base files, loaded once and copied per structure (not measured here).
        base_heap = directory / "base.heap"
        heap = HeapFile.create(base_heap, SCHEMA)
        for item in records:
            heap.insert(item)
        heap.close()
        base_sequential = directory / "base.seq"
        sequential = PagedSequentialFile.create(
            base_sequential, SCHEMA, KEY_COLUMN, allow_duplicate_keys=False,
        )
        for item in sorted(records, key=lambda r: r[KEY_COLUMN]):
            sequential.insert(item)
        sequential.close()

        structures = {}
        for name, base, suffix in (
            (UNCLUSTERED, base_heap, ".heap"),
            (HASH, base_heap, ".heap"),
            (CLUSTERED, base_sequential, ".seq"),
        ):
            data_path = directory / f"{name}{suffix}"
            shutil.copyfile(base, data_path)
            index_path = directory / f"{name}.idx"
            if name == CLUSTERED:
                storage = PagedSequentialFile.open(data_path, SCHEMA)
                build = lambda storage=storage, index_path=index_path: ClusteredBPlusIndex.build(
                    index_path, sequential=storage, index_name="pk", table_name="t",
                    key_column=KEY_COLUMN, allow_duplicate_keys=False,
                )
            else:
                storage = HeapFile.open(data_path, SCHEMA)
                factory = UnclusteredBPlusIndex if name == UNCLUSTERED else UnclusteredHashIndex
                build = lambda storage=storage, index_path=index_path, factory=factory: factory.build(
                    index_path, heap=storage, index_name="pk", table_name="t",
                    key_column=KEY_COLUMN, allow_duplicate_keys=False,
                )
            index, elapsed = timed(build)
            index.flush()
            record(name, "build", elapsed, size,
                   index_bytes=file_bytes(index_path), base_bytes=file_bytes(data_path),
                   entry_count=index.entry_count)
            structures[name] = (index, storage, index_path)

        try:
            for name, (index, storage, _) in structures.items():
                # ------------------------------------------------- equality
                for operation, probe in (("equality_present", present), ("equality_absent", absent)):
                    found, elapsed = timed(
                        lambda probe=probe, index=index: [_consume(index.search_records(key)) for key in probe]
                    )
                    record(name, operation, elapsed, len(probe), found=sum(found))

                # ---------------------------------------------------- range
                for selectivity, bounds in ranges.items():
                    if name == HASH:
                        found, elapsed = timed(
                            lambda bounds=bounds, storage=storage: [
                                _heap_range_scan(storage, low, high) for low, high in bounds
                            ]
                        )
                        record(name, "range", elapsed, len(bounds), selectivity=selectivity,
                               rows_returned=sum(found), access="heap scan + filter (hash has no order)")
                    else:
                        found, elapsed = timed(
                            lambda bounds=bounds, index=index: [
                                _consume(index.range_records(low, high)) for low, high in bounds
                            ]
                        )
                        record(name, "range", elapsed, len(bounds), selectivity=selectivity,
                               rows_returned=sum(found), access="index range")

                # ---------------------------------------- ordered retrieval
                if name == HASH:
                    (rows_sorted, operators), elapsed = timed(lambda storage=storage: _sql_order_by(storage))
                    record(name, "ordered_retrieval", elapsed, rows_sorted,
                           access="SQL ORDER BY: " + " <- ".join(operators),
                           memory_budget_bytes=DEFAULT_BUDGET_BYTES)
                else:
                    rows_sorted, elapsed = timed(lambda index=index: _consume(index.range_records()))
                    record(name, "ordered_retrieval", elapsed, rows_sorted, access="full index range")

            # ----------------------------------------- insert/delete workload
            for name, (index, storage, index_path) in structures.items():
                workload_rng = random.Random(size * 104_729 + repetition)
                live = list(keys)
                next_key = size + 10_000
                before = file_bytes(index_path)
                done = inserted = deleted = 0
                started = perf_counter()
                while done < workload_operations and perf_counter() - started < workload_budget_seconds:
                    if done % 2 == 0:
                        index.insert_record(Record(SCHEMA, [next_key, "Carga Mixta", "CS", 21, 50]))
                        live.append(next_key)
                        next_key += 1
                        inserted += 1
                    else:
                        victim = live.pop(workload_rng.randrange(len(live)))
                        with closing(index.search(victim)) as rids:
                            rid = next(rids)
                        index.delete_record(rid)
                        deleted += 1
                    done += 1
                elapsed = perf_counter() - started
                validation, validation_seconds = timed(index.validate_structure)
                record(name, "insert_delete_workload", elapsed, done,
                       inserted=inserted, deleted=deleted,
                       operations_target=workload_operations,
                       budget_seconds=workload_budget_seconds,
                       completed_target=done == workload_operations,
                       operations_per_second=done / elapsed if elapsed else None,
                       index_bytes_before=before, index_bytes=file_bytes(index_path),
                       entry_count=index.entry_count,
                       validation_seconds=validation_seconds,
                       valid=validation is not None)
        finally:
            for index, storage, _ in structures.values():
                index.close()
                storage.close()
