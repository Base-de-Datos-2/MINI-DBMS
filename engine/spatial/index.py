"""Heap-backed spatial queries and one explicit persisted R-Tree association."""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, replace
import heapq
from pathlib import Path

from engine.errors import DuplicateError, ValidationError
from engine.operators.context import cancellation_point
from engine.storage import HeapFile, Record, RID
from .geometry import Metric, Point, Polygon, distance, k_value, metric_value, radius_value
from .metadata import SpatialMapping, validate_coordinates
from .rtree import RTree, SearchStats, SpatialEntry, SpatialHit, SpatialResult


def entry_from_record(mapping: SpatialMapping, rid: RID, record: Record) -> SpatialEntry:
    latitude, longitude = record[mapping.latitude_column], record[mapping.longitude_column]
    validate_coordinates(latitude, longitude)
    return SpatialEntry(record[mapping.identity_column], rid, Point(latitude, longitude))


def scan_entries(storage, mapping: SpatialMapping):
    with closing(storage.scan()) as rows:
        for rid, record in rows:
            cancellation_point()
            yield entry_from_record(mapping, rid, record), record


def scan_radius(storage, mapping: SpatialMapping, center: Point, radius: float, *,
                metric: Metric | str = Metric.HAVERSINE, inclusive: bool = False) -> SpatialResult:
    selected, radius = metric_value(metric), radius_value(radius)
    if not isinstance(center, Point) or type(inclusive) is not bool:
        raise ValidationError("Radius queries need a typed center and boolean boundary option")
    stats, hits = SearchStats("SpatialScan", selected.value), []
    for entry, record in scan_entries(storage, mapping):
        stats.candidates += 1
        stats.base_records_read += 1
        actual = distance(center, entry.point, selected)
        if actual < radius or (inclusive and actual == radius):
            hits.append(SpatialHit(entry, actual, record))
    return SpatialResult(tuple(sorted(hits, key=lambda hit: hit.identity)), stats)


def scan_polygon(storage, mapping: SpatialMapping, polygon: Polygon) -> SpatialResult:
    if not isinstance(polygon, Polygon):
        raise ValidationError("Polygon query requires a validated Polygon")
    stats, hits = SearchStats("SpatialScan"), []
    for entry, record in scan_entries(storage, mapping):
        stats.candidates += 1
        stats.base_records_read += 1
        if polygon.contains(entry.point):
            hits.append(SpatialHit(entry, record=record))
    return SpatialResult(tuple(sorted(hits, key=lambda hit: hit.identity)), stats)


def scan_knn(storage, mapping: SpatialMapping, center: Point, k: int, *,
             metric: Metric | str = Metric.HAVERSINE) -> SpatialResult:
    selected, k = metric_value(metric), k_value(k)
    if not isinstance(center, Point):
        raise ValidationError("k-NN query needs a typed center")
    stats, best = SearchStats("SpatialScan", selected.value), []
    if not k:
        return SpatialResult((), stats)
    for entry, record in scan_entries(storage, mapping):
        stats.candidates += 1
        stats.base_records_read += 1
        actual = distance(center, entry.point, selected)
        candidate = (-actual, -entry.identity, SpatialHit(entry, actual, record))
        if len(best) < k:
            heapq.heappush(best, candidate)
        elif (actual, entry.identity) < (-best[0][0], -best[0][1]):
            heapq.heapreplace(best, candidate)
    return SpatialResult(tuple(sorted((item[2] for item in best),
                                     key=lambda hit: (hit.distance_metres, hit.identity))), stats)


class SpatialIndex:
    """Owner-local borrowed Heap and replaceable cached tree; caller holds locks."""
    def __init__(self, storage: HeapFile, mapping: SpatialMapping, path: Path, tree: RTree):
        if not isinstance(storage, HeapFile):
            raise ValidationError("Spatial indexes require stable-RID Heap storage")
        self.storage, self.mapping, self.path, self.tree = storage, mapping, Path(path), tree
        self._closed = False

    @classmethod
    def open_or_build(cls, storage: HeapFile, mapping: SpatialMapping, path: Path):
        if path.exists():
            tree = RTree.load(path, metadata=asdict(mapping))
            result = cls(storage, mapping, path, tree)
            result.validate_structure()
        else:
            result = cls(storage, mapping, path, RTree())
            result.rebuild()
        return result

    def _require_open(self):
        if self._closed:
            raise ValidationError("Spatial index is closed; retrieve the current owner object")

    def validate_insert(self, record: Record):
        self._require_open()
        validate_coordinates(record[self.mapping.latitude_column], record[self.mapping.longitude_column])
        identity = record[self.mapping.identity_column]
        if type(identity) is not int:
            raise ValidationError("Spatial ID must be an integer")
        if self.tree.has_identity(identity):
            raise DuplicateError(f"Spatial ID {identity} already exists")

    def inserted(self, rid: RID, record: Record):
        self._require_open()
        self.tree.insert(entry_from_record(self.mapping, rid, record))
        self.flush()

    def rebuild(self):
        self._require_open()
        tree = RTree(self.tree.capacity)
        for entry, _ in scan_entries(self.storage, self.mapping):
            tree.insert(entry)
        # Publish the file and object only after a complete valid build.
        tree.save(self.path, metadata=asdict(self.mapping))
        self.tree = tree

    def flush(self):
        self._require_open()
        self.tree.save(self.path, metadata=asdict(self.mapping))

    def validate_structure(self):
        self._require_open()
        statistics = self.tree.validate_structure()
        remaining = {entry.rid: entry for entry in self.tree.entries()}
        identities = set()
        for entry, _ in scan_entries(self.storage, self.mapping):
            if entry.identity in identities or remaining.pop(entry.rid, None) != entry:
                raise ValidationError("Spatial index does not match the current Heap rows")
            identities.add(entry.identity)
        if remaining or len(identities) != self.storage.record_count:
            raise ValidationError("Spatial index coverage differs from the Heap")
        return statistics

    def _resolve(self, result: SpatialResult):
        hits = []
        for hit in result.hits:
            cancellation_point()
            record = self.storage.read(hit.rid)
            if entry_from_record(self.mapping, hit.rid, record) != hit.entry:
                raise ValidationError("Indexed RID no longer identifies the same spatial point")
            hits.append(replace(hit, record=record))
            result.stats.base_records_read += 1
        return SpatialResult(tuple(hits), result.stats)

    def radius(self, center, radius, *, metric=Metric.HAVERSINE, inclusive=False, use_index=True):
        self._require_open()
        if not use_index:
            return scan_radius(self.storage, self.mapping, center, radius, metric=metric, inclusive=inclusive)
        return self._resolve(self.tree.radius(center, radius, metric=metric, inclusive=inclusive))

    def knn(self, center, k, *, metric=Metric.HAVERSINE, use_index=True):
        self._require_open()
        if not use_index:
            return scan_knn(self.storage, self.mapping, center, k, metric=metric)
        return self._resolve(self.tree.knn(center, k, metric=metric))

    def polygon(self, polygon, *, use_index=True):
        self._require_open()
        if not use_index:
            return scan_polygon(self.storage, self.mapping, polygon)
        return self._resolve(self.tree.polygon(polygon))

    def close(self):
        # No borrowed Heap handles are closed here. Mutations already persist.
        self._closed = True
