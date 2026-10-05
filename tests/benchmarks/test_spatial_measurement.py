import json
import math
import sys
from types import SimpleNamespace

import pytest

from benchmarks.postgres_client import identifier
from benchmarks.spatial.datasets import FIXTURE_ROWS
from benchmarks.spatial.measurement import NEIGHBORS, RADII, SCHEMA, measure_native
from benchmarks.spatial.validation import identities_hash, oracle, spherical_distance, validate
from engine.spatial.metadata import EARTH_RADIUS_METRES, ORIGIN
from engine.storage import HeapFile, Record


def test_independent_oracle_has_analytic_north_distance_and_duplicate_id_ties():
    actual = spherical_distance(ORIGIN[0] + .001, ORIGIN[1], ORIGIN)
    assert actual == pytest.approx(EARTH_RADIUS_METRES * math.radians(.001), abs=1e-8)
    expected = oracle(FIXTURE_ROWS, ORIGIN, [1], [2])
    assert expected["knn:2"]["pairs"] == [(1, 0.0), (2, 0.0)]
    assert expected["radius:1"]["count"] == 2
    points = {row[0]: row for row in FIXTURE_ROWS}
    for bad in [[(1, 0.0), (1, 0.0)], [(2, 0.0), (1, 0.0)], [(1, 1.0), (2, 0.0)]]:
        with pytest.raises(ValueError):
            validate(bad, expected["knn:2"], points, ORIGIN)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux RSS experiment protocol")
@pytest.mark.parametrize("method", ["scan", "rtree"])
def test_native_harness_measures_real_heap_queries_and_persistent_index(tmp_path, method):
    heap = tmp_path / "points.heap"
    with HeapFile.create(heap, SCHEMA) as storage:
        for values in FIXTURE_ROWS:
            storage.insert(Record(SCHEMA, values))
    expected = {"centers": [(1, *ORIGIN)],
                "references": {"1": oracle(FIXTURE_ROWS, ORIGIN, RADII, NEIGHBORS)}}
    args = SimpleNamespace(method=method, size=9, heap=heap, index=tmp_path / "index.rtree",
                           output=tmp_path / "times.jsonl")
    resources = measure_native(args, FIXTURE_ROWS, expected)
    samples = [json.loads(line) for line in args.output.read_text().splitlines()]
    assert len(samples) == 6 and all(row["validated"] and row["elapsed_seconds"] > 0 for row in samples)
    assert all(row["access"] == ("RTree" if method == "rtree" else "SpatialScan") for row in samples)
    nearest = next(row for row in samples if row["kind"] == "knn" and row["value"] == 10)
    assert nearest["result_ids_sha256"] == identities_hash(range(1, 10))
    assert resources["peak_rss_bytes"] > 0 and resources["data_bytes"] == heap.stat().st_size
    assert (resources["build_seconds"] is None) == (method == "scan")
    assert (resources["index_bytes"] > 0) == (method == "rtree")


@pytest.mark.parametrize("name", ["old; DROP SCHEMA public", "public.points", "../data", "'name'", ""])
def test_comparator_schema_names_cannot_escape_the_isolated_namespace(name):
    with pytest.raises(ValueError):
        identifier(name)
