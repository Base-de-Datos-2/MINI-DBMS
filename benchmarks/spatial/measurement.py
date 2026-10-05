"""Complete-query measurements with independent preflight verification."""

import csv
import json
from pathlib import Path
from time import perf_counter

from engine.catalog import Column, DataType, Schema
from engine.spatial.geometry import Point
from engine.spatial.index import SpatialIndex, scan_knn, scan_radius
from engine.spatial.metadata import SpatialMapping
from engine.spatial.rtree import RTree
from engine.storage import HeapFile

from .validation import peak_rss_bytes, validate


SCHEMA = Schema([Column("id", DataType.INTEGER), Column("nombre", DataType.VARCHAR),
                 Column("latitud", DataType.FLOAT), Column("longitud", DataType.FLOAT)])
MAPPING = SpatialMapping("puntos")
RADII = (1000, 5000, 10000)
NEIGHBORS = (10, 50, 100)
SETTINGS = tuple(("radius", value) for value in RADII) + tuple(("knn", value) for value in NEIGHBORS)


def read_points(path):
    with Path(path).open(encoding="utf-8", newline="") as source:
        return [(int(row["id"]), row["nombre"], float(row["latitud"]), float(row["longitud"]))
                for row in csv.DictReader(source)]


def native_query(storage, index, center, kind, value):
    point = Point(*center)
    if index is not None:
        result = getattr(index, kind)(point, value)
    else:
        function = scan_radius if kind == "radius" else scan_knn
        result = function(storage, MAPPING, point, value)
    pairs = [(hit.identity, hit.distance_metres) for hit in result.hits]
    # Include complete projection and serialization/decoding in all client times.
    return json.loads(json.dumps(pairs)), result.stats


def measure_settings(method, size, centers, references, points, query, output, memory):
    points_by_id = {row[0]: row for row in points}
    with Path(output).open("x", encoding="utf-8") as destination:
        for kind, value in SETTINGS:
            key = f"{kind}:{value}"
            for query_id, latitude, longitude in centers:
                pairs, _ = query((latitude, longitude), kind, value, preflight=True)
                validate(pairs, references[str(query_id)][key], points_by_id, (latitude, longitude))
            print(f"{method} N={size} {key}: preflight {len(centers)} correcto", flush=True)
            for query_id, latitude, longitude in centers:
                started = perf_counter()
                pairs, details = query((latitude, longitude), kind, value)
                elapsed = perf_counter() - started
                elapsed = details.pop("measured_elapsed_seconds", elapsed)
                expected = references[str(query_id)][key]
                validate(pairs, expected, points_by_id, (latitude, longitude))
                row = {
                    "method": method, "size": size, "metric": "haversine", "kind": kind,
                    "value": value, "query_id": query_id, "center": [latitude, longitude],
                    "elapsed_seconds": elapsed, "result_count": len(pairs),
                    "result_ids_sha256": expected["ids_sha256"], "validated": True,
                    **details,
                }
                destination.write(json.dumps(row, ensure_ascii=False) + "\n")
                destination.flush()
            print(f"{method} N={size} {key}: {len(centers)} tiempos guardados", flush=True)
    return memory()


def measure_native(args, points, oracle):
    with HeapFile.open(args.heap, SCHEMA) as storage:
        index = None
        build_seconds = None
        if args.method == "rtree":
            index = SpatialIndex(storage, MAPPING, Path(args.index), RTree())
            if index.path.exists():
                raise FileExistsError("Benchmark index already exists")
            started = perf_counter()
            index.rebuild()
            build_seconds = perf_counter() - started
            index.validate_structure()
        def query(center, kind, value, *, preflight=False):
            pairs, stats = native_query(storage, index, center, kind, value)
            return pairs, {"access": stats.access, "visited_nodes": stats.visited_nodes,
                           "candidates": stats.candidates, "base_records_read": stats.base_records_read}
        memory = measure_settings(args.method, args.size, oracle["centers"], oracle["references"],
                                  points, query, args.output, peak_rss_bytes)
        return {"method": args.method, "size": args.size, "build_seconds": build_seconds,
                "build_includes": "Heap traversal, R-Tree construction, serialization and fsync" if index else None,
                "data_bytes": Path(args.heap).stat().st_size,
                "index_bytes": index.path.stat().st_size if index else 0,
                "peak_rss_bytes": memory, "memory_scope": "isolated Python worker lifetime peak RSS",
                "memory_includes": "imports, oracle inputs/validation, result buffers and index construction",
                "query_count_per_setting": len(oracle["centers"]),
                "preflight": "all query centers before timing each setting; same order repeated once"}
