"""Stage 5 restart lifecycle and deterministic differential oracle checks."""

from collections import defaultdict
import random

import pytest

from engine.catalog import DataType
from engine.errors import InvalidReferenceError
from engine.indexes import ExtendibleHashIndex
from engine.storage import RID


ARGUMENTS = {
    "index_name": "idx_values_hash",
    "table_name": "values",
    "key_column": "value",
    "key_type": DataType.INTEGER,
}


def test_full_restart_delete_continue_growth_and_reopen_again(tmp_path):
    path = tmp_path / "restart.hash"
    expected: dict[int, set[RID]] = defaultdict(set)
    index = ExtendibleHashIndex.create(path, **ARGUMENTS)
    for number in range(700):
        key = number % 37
        rid = RID(number, number % 3)
        index.insert(key, rid)
        expected[key].add(rid)
    assert index.global_depth > 1
    index.flush()
    index.close()
    del index

    reopened = ExtendibleHashIndex.open(path, **ARGUMENTS)
    for key, rids in expected.items():
        assert set(reopened.search(key)) == rids
    for number in range(0, 700, 4):
        key = number % 37
        rid = RID(number, number % 3)
        reopened.delete(key, rid)
        expected[key].remove(rid)
    for number in range(700, 900):
        key = number % 37
        rid = RID(number, number % 3)
        reopened.insert(key, rid)
        expected[key].add(rid)
    reopened.validate_structure()
    reopened.close()
    del reopened

    final = ExtendibleHashIndex.open(path, **ARGUMENTS)
    try:
        for key in range(37):
            assert set(final.search(key)) == expected[key]
        assert final.validate_structure().association_count == sum(
            len(rids) for rids in expected.values()
        )
    finally:
        final.close()


def test_deterministic_randomized_operations_match_map_oracle(tmp_path):
    path = tmp_path / "differential.hash"
    rng = random.Random(20260906)
    oracle: dict[int, set[RID]] = defaultdict(set)
    index = ExtendibleHashIndex.create(path, **ARGUMENTS)
    try:
        for step in range(240):
            key = rng.randrange(25)
            rid = RID(rng.randrange(80), rng.randrange(4))
            if rng.random() < 0.62:
                index.insert(key, rid)
                oracle[key].add(rid)
            elif rid in oracle[key]:
                index.delete(key, rid)
                oracle[key].remove(rid)
            else:
                with pytest.raises(InvalidReferenceError):
                    index.delete(key, rid)

            for candidate in range(25):
                assert set(index.search(candidate)) == oracle[candidate]
            index.validate_structure()
            if step and step % 60 == 0:
                index.flush()
                index.close()
                del index
                index = ExtendibleHashIndex.open(path, **ARGUMENTS)

        report = index.validate_structure()
        assert report.association_count == sum(len(rids) for rids in oracle.values())
        for key in range(25):
            assert set(index.search(key)) == oracle[key]
    finally:
        index.close()
