"""Stage 10 Task 10.2c: balanced page splits in the Paged Sequential File."""

import random

from engine.catalog import Column, DataType, Schema
from engine.storage import PagedSequentialFile, Record


SCHEMA = Schema([Column("id", DataType.INTEGER), Column("label", DataType.VARCHAR)])


def load(path, keys):
    sequential = PagedSequentialFile.create(path, SCHEMA, "id", allow_duplicate_keys=False)
    for key in keys:
        sequential.insert(Record(SCHEMA, [key, f"row-{key}".ljust(60, ".")]))
    return sequential


def records_per_page(sequential):
    return sequential.record_count / sequential.data_page_count


def test_random_order_loads_keep_pages_at_least_half_full(tmp_path):
    keys = list(range(3000))
    random.Random(4).shuffle(keys)
    with load(tmp_path / "random.db", keys) as sequential:
        with load(tmp_path / "ascending.db", sorted(keys)) as ascending:
            full = records_per_page(ascending)
            # Before 10.2c a split left the overflow, often one record, alone on
            # a new page, and random loads averaged a few records per page.
            assert records_per_page(sequential) >= full / 2
            assert [r.values[0] for _, r in sequential.scan()] == sorted(keys)


def test_ascending_loads_still_fill_pages_completely(tmp_path):
    with load(tmp_path / "ascending.db", range(3000)) as sequential:
        sizes = {}
        for rid, _ in sequential.scan():
            sizes[rid.page_id] = sizes.get(rid.page_id, 0) + 1
        counts = [sizes[page_id] for page_id in sorted(sizes)]
        # Appends at the end keep the greedy fill: every page but the last is full.
        assert len(set(counts[:-1])) == 1 and counts[-1] <= counts[0]
        assert sequential.wasted_space_ratio() == 0.0


def test_a_middle_split_produces_two_pages_of_similar_size(tmp_path):
    with load(tmp_path / "split.db", range(0, 2000, 2)) as sequential:
        pages_before = sequential.data_page_count
        first_page_keys = [r.values[0] for rid, r in sequential.scan() if rid.page_id == 1]
        middle = first_page_keys[len(first_page_keys) // 2] + 1
        sequential.insert(Record(SCHEMA, [middle, "split".ljust(60, ".")]))
        assert sequential.data_page_count == pages_before + 1
        sizes = {}
        for rid, _ in sequential.scan():
            sizes[rid.page_id] = sizes.get(rid.page_id, 0) + 1
        assert abs(sizes[1] - sizes[2]) <= 1
