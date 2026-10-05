import copy
import math

import pytest

from benchmarks.spatial.measurement import SETTINGS
from benchmarks.spatial.results import summarize


def measured_rows(method="scan"):
    centers = {1: [0, 0], 2: [0, .01]}
    references = {str(identity): {f"{kind}:{value}": {"count": identity, "ids_sha256": f"hash-{identity}"}
                                 for kind, value in SETTINGS} for identity in centers}
    rows = [{"kind": kind, "value": value, "query_id": identity, "center": center,
             "method": method, "size": 1000, "metric": "haversine", "validated": True,
             "result_count": identity, "result_ids_sha256": f"hash-{identity}",
             "elapsed_seconds": .001 if identity == 1 else .009,
             "access": {"scan": "SpatialScan", "rtree": "RTree", "gist": "GiST"}[method],
             "server_seconds": .0005,
             "plan": {"Node Type": "Aggregate", "Plans": [{"Node Type": "Index Scan",
                                                             "Index Name": "points_location_gist"}]}}
            for kind, value in SETTINGS for identity, center in centers.items()]
    return rows, centers, references


def test_means_use_all_queries_and_keep_server_time_separate():
    rows, centers, references = measured_rows("gist")
    result = summarize(rows, method="gist", size=1000, centers=centers, references=references)
    assert len(result) == 6
    assert all(row["sample_count"] == 2 and row["mean_ms"] == pytest.approx(5)
               and row["min_ms"] == 1 and row["max_ms"] == 9
               and row["mean_server_ms"] == .5 for row in result)


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "checksum", "center", "unverified",
                                         "negative", "nan", "access", "plan"])
def test_missing_or_corrupt_measurements_cannot_be_graphed(corruption):
    rows, centers, references = measured_rows("gist")
    rows = copy.deepcopy(rows)
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate":
        rows[-1] = copy.deepcopy(rows[-2])
    else:
        key, value = {
            "checksum": ("result_ids_sha256", "incorrect"), "center": ("center", [0, 1]),
            "unverified": ("validated", False), "negative": ("elapsed_seconds", -1),
            "nan": ("elapsed_seconds", math.nan), "access": ("access", "SpatialScan"),
            "plan": ("plan", {"Node Type": "Seq Scan"}),
        }[corruption]
        rows[0][key] = value
    with pytest.raises(ValueError):
        summarize(rows, method="gist", size=1000, centers=centers, references=references)
