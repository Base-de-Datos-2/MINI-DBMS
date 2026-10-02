"""Stage 10 Task 10.2b: binary-search page location in the Paged Sequential File.

The insertion target and the start of ``search`` are found by binary search
over the ordered pages. These tests compare the file against a plain sorted
model under random insertions, duplicates and deletions that leave fully
emptied pages in the middle, and bound how many pages one insertion reads.
"""

import math
import random

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import DuplicateError
from engine.storage import PagedSequentialFile, Record


SCHEMA = Schema([Column("id", DataType.INTEGER), Column("label", DataType.VARCHAR)])


def row(key, label, width=40):
    return Record(SCHEMA, [key, label.ljust(width, ".")])


def keys_and_labels(sequential):
    return [(record.values[0], record.values[1].rstrip(".")) for _, record in sequential.scan()]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_inserts_and_deletes_match_a_sorted_model(tmp_path, seed):
    rng = random.Random(seed)
    model: list[tuple[int, str]] = []  # stable: equal keys keep arrival order
    with PagedSequentialFile.create(tmp_path / "seq.db", SCHEMA, "id") as sequential:
        for step in range(600):
            key = rng.randrange(0, 150)
            label = f"s{step}"
            sequential.insert(row(key, label))
            position = sum(1 for existing, _ in model if existing <= key)
            model.insert(position, (key, label))
            if step % 7 == 0 and model:
                # Delete a whole key range sometimes, which empties pages.
                low = rng.randrange(0, 150)
                high = low + rng.randrange(1, 25)
                doomed = [rid for rid, record in sequential.scan()
                          if low <= record.values[0] < high]
                for rid in doomed:
                    sequential.delete(rid)
                model = [item for item in model if not low <= item[0] < high]

        assert keys_and_labels(sequential) == model
        for probe in range(-1, 152):
            expected = [label for key, label in model if key == probe]
            found = [record.values[1].rstrip(".") for _, record in sequential.search(probe)]
            assert found == expected


def test_insert_order_matches_the_model_exactly_with_deletions(tmp_path):
    rng = random.Random(7)
    model: list[tuple[int, str]] = []
    with PagedSequentialFile.create(tmp_path / "seq.db", SCHEMA, "id") as sequential:
        for step in range(400):
            key = rng.randrange(0, 80)
            label = f"r{step}"
            sequential.insert(row(key, label))
            position = sum(1 for existing, _ in model if existing <= key)
            model.insert(position, (key, label))
            if step % 5 == 4:
                victim = rng.choice(model)
                rid = next(rid for rid, record in sequential.scan()
                           if record.values[1].rstrip(".") == victim[1])
                sequential.delete(rid)
                model.remove(victim)
            assert keys_and_labels(sequential) == model


def test_emptied_middle_pages_do_not_misplace_new_keys(tmp_path):
    with PagedSequentialFile.create(tmp_path / "seq.db", SCHEMA, "id") as sequential:
        for key in range(0, 300):
            sequential.insert(row(key, f"k{key}", width=200))
        assert sequential.data_page_count > 10
        middle = [rid for rid, record in sequential.scan() if 100 <= record.values[0] < 200]
        for rid in middle:
            sequential.delete(rid)
        for key in (150, 99, 200, 100, 199, -5, 500):
            sequential.insert(row(key, f"n{key}", width=200))
        keys = [record.values[0] for _, record in sequential.scan()]
        assert keys == sorted(keys)
        assert [record.values[0] for _, record in sequential.search(150)] == [150]
        assert list(sequential.search(120)) == []


def test_unique_files_still_reject_duplicates_anywhere(tmp_path):
    with PagedSequentialFile.create(
        tmp_path / "unique.db", SCHEMA, "id", allow_duplicate_keys=False
    ) as sequential:
        for key in range(0, 400, 2):
            sequential.insert(row(key, f"k{key}", width=200))
        doomed = [rid for rid, record in sequential.scan() if 100 <= record.values[0] < 160]
        for rid in doomed:
            sequential.delete(rid)
        for key in (0, 98, 160, 398, 200):
            with pytest.raises(DuplicateError):
                sequential.insert(row(key, "dup", width=200))
        for key in (120, 1, 399, 130):
            sequential.insert(row(key, "new", width=200))
        keys = [record.values[0] for _, record in sequential.scan()]
        assert keys == sorted(keys) and len(keys) == len(set(keys))


def test_locating_the_insertion_page_reads_a_logarithmic_number_of_pages(tmp_path):
    with PagedSequentialFile.create(tmp_path / "seq.db", SCHEMA, "id") as sequential:
        for key in range(0, 2000, 2):
            sequential.insert(row(key, f"k{key}", width=300))
        pages = sequential.data_page_count
        assert pages > 60
        sequential.reset_counters()
        target, entries, duplicate = sequential._find_insertion_target(1001)
        # Binary-search probes, the target page and its left neighbour. The old
        # algorithm decoded every page before the target. (A split of a full
        # page still shifts the following pages: that is the file's design.)
        assert sequential.pages_read <= math.ceil(math.log2(pages)) + 3
        assert not duplicate
        assert entries[0][0] <= 1001 < entries[-1][0] or entries[0][0] > 1001

        sequential.reset_counters()
        assert [record.values[0] for _, record in sequential.search(1000)] == [1000]
        assert sequential.pages_read <= math.ceil(math.log2(pages)) + 2
