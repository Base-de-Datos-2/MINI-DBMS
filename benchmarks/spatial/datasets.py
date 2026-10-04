"""Seeded local points; identical CSV inputs for own engine and PostgreSQL."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import random

from engine.spatial.metadata import CONVENTIONS, LATITUDE_BOUNDS, LONGITUDE_BOUNDS

REQUIRED_SIZES = (1000, 10000, 100000)
SEED = 20261003
QUERY_COUNT = 100
HEADER = ("id", "nombre", "latitud", "longitud")
# A synthetic L-shaped polygon near the origin. Pairs are (latitude, longitude).
FIXTURE_POLYGON = (
    (-12.06, -77.06), (-12.06, -77.02), (-12.04, -77.02),
    (-12.04, -77.04), (-12.02, -77.04), (-12.02, -77.06),
    (-12.06, -77.06),
)
FIXTURE_ROWS = (
    (1, "Centro", -12.0464, -77.0428),
    (2, "Centro duplicado", -12.0464, -77.0428),
    (3, "Vecino este", -12.0464, -77.0418),
    (4, "Vecino norte", -12.0454, -77.0428),
    (5, "Interior oeste", -12.03, -77.05),
    (6, "En el borde", -12.04, -77.03),
    (7, "En MBR, fuera del poligono", -12.03, -77.03),
    (8, "Fuera del MBR", -12.01, -77.01),
    (9, "Lejano", -12.22, -77.20),
)
FIXTURE_POLYGON_IDS = (1, 2, 3, 4, 5, 6)


def point_rows(size: int, seed: int = SEED):
    if type(size) is not int or size < 0 or type(seed) is not int:
        raise ValueError("size must be nonnegative and seed must be an integer")
    rng = random.Random(seed)
    for identity in range(1, size + 1):
        yield (identity, f"punto_{identity}",
               round(rng.uniform(*LATITUDE_BOUNDS), 8),
               round(rng.uniform(*LONGITUDE_BOUNDS), 8))


def query_centers(seed: int = SEED):
    # Separate random stream: query centers never depend on dataset size.
    rng = random.Random(seed + 1)
    return tuple((identity, round(rng.uniform(*LATITUDE_BOUNDS), 8),
                  round(rng.uniform(*LONGITUDE_BOUNDS), 8))
                 for identity in range(1, QUERY_COUNT + 1))


def _csv(path: Path, header, rows) -> str:
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(directory: Path, sizes=REQUIRED_SIZES, seed: int = SEED) -> dict:
    sizes = tuple(sizes)
    if not sizes or len(set(sizes)) != len(sizes) or any(
        type(size) is not int or size <= 0 for size in sizes
    ) or type(seed) is not int:
        raise ValueError("Provide distinct positive sizes and an integer seed")
    # New directory only: an existing benchmark's inputs cannot be overwritten.
    directory.mkdir(parents=True, exist_ok=False)
    hashes = {f"points_{size}.csv": _csv(directory / f"points_{size}.csv", HEADER,
                                       point_rows(size, seed)) for size in sizes}
    hashes["queries.csv"] = _csv(directory / "queries.csv",
                                ("query_id", "latitud", "longitud"), query_centers(seed))
    hashes["fixture.csv"] = _csv(directory / "fixture.csv", HEADER, FIXTURE_ROWS)
    manifest = {
        "format": "MINIDBMS_SPATIAL_INPUTS", "version": 1, "seed": seed,
        "sizes": list(sizes), "query_count": QUERY_COUNT, "conventions": CONVENTIONS,
        "radii_metres": [1000, 5000, 10000], "k": [10, 50, 100],
        "sha256": hashes, "fixture_polygon": FIXTURE_POLYGON,
        "fixture_polygon_ids": FIXTURE_POLYGON_IDS,
    }
    (directory / "inputs.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
