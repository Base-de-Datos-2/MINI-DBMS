"""Original quadratic-split R-Tree with exact searches and explicit JSON persistence.

Traversal is in memory. This format provides clean restart, not a paged index,
WAL, or multi-file crash recovery. Leaves retain distinct stable IDs and RIDs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import heapq
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from engine.errors import DuplicateError, ValidationError
from engine.operators.context import cancellation_point
from engine.storage import RID, Record
from .geometry import MBR, Metric, Point, Polygon, covering, distance, k_value, metric_value, radius_value
from .metadata import CONVENTIONS


@dataclass(frozen=True, slots=True)
class SpatialEntry:
    identity: int
    rid: RID
    point: Point
    box: MBR = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if type(self.identity) is not int or not isinstance(self.rid, RID) or not isinstance(self.point, Point):
            raise ValidationError("Spatial entries need an integer ID, RID and typed point")
        object.__setattr__(self, "box", MBR.at(self.point))


@dataclass(frozen=True, slots=True)
class SpatialHit:
    entry: SpatialEntry
    distance_metres: float | None = None
    record: Record | None = None

    @property
    def identity(self):
        return self.entry.identity

    @property
    def rid(self):
        return self.entry.rid

    @property
    def point(self):
        return self.entry.point


@dataclass(slots=True)
class SearchStats:
    access: str
    metric: str | None = None
    visited_nodes: int = 0
    candidates: int = 0
    base_records_read: int = 0


@dataclass(frozen=True, slots=True)
class SpatialResult:
    hits: tuple[SpatialHit, ...]
    stats: SearchStats


@dataclass(slots=True)
class _Node:
    leaf: bool
    entries: list
    box: MBR | None = None

    def recompute(self):
        self.box = covering(entry.box for entry in self.entries)


class RTree:
    def __init__(self, capacity: int = 16):
        if type(capacity) is not int or not 4 <= capacity <= 64:
            raise ValidationError("R-Tree capacity must be an integer from 4 to 64")
        self.capacity = capacity
        self.minimum = capacity // 2
        self._root = _Node(True, [])
        self._identities: dict[int, SpatialEntry] = {}
        self._rids: set[RID] = set()

    @property
    def entry_count(self) -> int:
        return len(self._identities)

    def has_identity(self, identity: int) -> bool:
        return identity in self._identities

    def insert(self, entry: SpatialEntry) -> None:
        if not isinstance(entry, SpatialEntry):
            raise ValidationError("R-Tree inserts require SpatialEntry")
        if entry.identity in self._identities or entry.rid in self._rids:
            raise DuplicateError("Spatial ID and RID must each be unique; coordinates may repeat")
        cancellation_point()
        sibling = self._insert(self._root, entry)
        if sibling is not None:
            self._root = _Node(False, [self._root, sibling])
            self._root.recompute()
        self._identities[entry.identity] = entry
        self._rids.add(entry.rid)

    def _insert(self, node: _Node, entry: SpatialEntry) -> _Node | None:
        if node.leaf:
            node.entries.append(entry)
        else:
            child = min(enumerate(node.entries), key=lambda pair: (
                pair[1].box.enlargement(entry.box), pair[1].box.area,
                len(pair[1].entries), pair[0]))[1]
            sibling = self._insert(child, entry)
            if sibling is not None:
                node.entries.append(sibling)
        node.recompute()
        return self._split(node) if len(node.entries) > self.capacity else None

    def _split(self, node: _Node) -> _Node:
        # Guttman quadratic seeds: largest wasted area if stored together.
        items = node.entries
        first, second = max(((i, j) for i in range(len(items)) for j in range(i + 1, len(items))),
                            key=lambda pair: items[pair[0]].box.union(items[pair[1]].box).area
                            - items[pair[0]].box.area - items[pair[1]].box.area)
        left, right = [items[first]], [items[second]]
        pending = [item for i, item in enumerate(items) if i not in (first, second)]
        left_box, right_box = left[0].box, right[0].box
        while pending:
            if len(left) + len(pending) == self.minimum:
                left.extend(pending)
                break
            if len(right) + len(pending) == self.minimum:
                right.extend(pending)
                break
            chosen = max(range(len(pending)), key=lambda i:
                         abs(left_box.enlargement(pending[i].box) - right_box.enlargement(pending[i].box)))
            item = pending.pop(chosen)
            left_cost = (left_box.enlargement(item.box), left_box.area, len(left))
            right_cost = (right_box.enlargement(item.box), right_box.area, len(right))
            if left_cost <= right_cost:
                left.append(item)
                left_box = left_box.union(item.box)
            else:
                right.append(item)
                right_box = right_box.union(item.box)
        node.entries = left
        node.recompute()
        sibling = _Node(node.leaf, right)
        sibling.recompute()
        return sibling

    def entries(self):
        stack = [self._root]
        while stack:
            cancellation_point()
            node = stack.pop()
            if node.leaf:
                yield from node.entries
            else:
                stack.extend(reversed(node.entries))

    def radius(self, center: Point, radius: float, *, metric: Metric | str = Metric.HAVERSINE,
               inclusive: bool = False) -> SpatialResult:
        selected, radius = metric_value(metric), radius_value(radius)
        if not isinstance(center, Point) or type(inclusive) is not bool:
            raise ValidationError("Radius queries need a typed center and boolean boundary option")
        stats, hits = SearchStats("RTree", selected.value), []
        stack = [self._root] if self._root.box is not None else []
        while stack:
            cancellation_point()
            node = stack.pop()
            stats.visited_nodes += 1
            if node.box.lower_bound(center, selected) > radius:
                continue
            if node.leaf:
                for entry in node.entries:
                    cancellation_point()
                    stats.candidates += 1
                    actual = distance(center, entry.point, selected)
                    if actual < radius or (inclusive and actual == radius):
                        hits.append(SpatialHit(entry, actual))
            else:
                stack.extend(child for child in node.entries
                             if child.box.lower_bound(center, selected) <= radius)
        return SpatialResult(tuple(sorted(hits, key=lambda hit: hit.identity)), stats)

    def polygon(self, polygon: Polygon) -> SpatialResult:
        if not isinstance(polygon, Polygon):
            raise ValidationError("Polygon query requires a validated Polygon")
        box, stats, hits = polygon.box, SearchStats("RTree"), []
        stack = [self._root] if self._root.box is not None else []
        while stack:
            cancellation_point()
            node = stack.pop()
            stats.visited_nodes += 1
            if not node.box.intersects(box):
                continue
            if node.leaf:
                for entry in node.entries:
                    cancellation_point()
                    stats.candidates += 1
                    if polygon.contains(entry.point):
                        hits.append(SpatialHit(entry))
            else:
                stack.extend(child for child in node.entries if child.box.intersects(box))
        return SpatialResult(tuple(sorted(hits, key=lambda hit: hit.identity)), stats)

    def knn(self, center: Point, k: int, *, metric: Metric | str = Metric.HAVERSINE) -> SpatialResult:
        selected, k = metric_value(metric), k_value(k)
        if not isinstance(center, Point):
            raise ValidationError("k-NN query needs a typed center")
        stats = SearchStats("RTree", selected.value)
        if not k or self._root.box is None:
            return SpatialResult((), stats)
        frontier = [(self._root.box.lower_bound(center, selected), 0, self._root)]
        serial, best = 0, []
        while frontier:
            cancellation_point()
            bound, _, node = heapq.heappop(frontier)
            # Equality must still be explored: a smaller ID could win a tie.
            if len(best) == k and bound > -best[0][0]:
                break
            stats.visited_nodes += 1
            if node.leaf:
                for entry in node.entries:
                    cancellation_point()
                    stats.candidates += 1
                    actual = distance(center, entry.point, selected)
                    candidate = (-actual, -entry.identity, entry)
                    if len(best) < k:
                        heapq.heappush(best, candidate)
                    elif (actual, entry.identity) < (-best[0][0], -best[0][1]):
                        heapq.heapreplace(best, candidate)
            else:
                for child in node.entries:
                    serial += 1
                    child_bound = child.box.lower_bound(center, selected)
                    if len(best) < k or child_bound <= -best[0][0]:
                        heapq.heappush(frontier, (child_bound, serial, child))
        hits = [SpatialHit(entry, -negative) for negative, _, entry in best]
        return SpatialResult(tuple(sorted(hits, key=lambda hit: (hit.distance_metres, hit.identity))), stats)

    def validate_structure(self) -> dict[str, int]:
        depths, seen_nodes, ids, rids = set(), set(), {}, set()
        leaves = 0
        def visit(node, depth, root=False):
            nonlocal leaves
            cancellation_point()
            if depth > 64 or id(node) in seen_nodes:
                raise ValidationError("R-Tree contains a cycle, shared node or excessive depth")
            seen_nodes.add(id(node))
            size = len(node.entries)
            if size > self.capacity or (not root and size < self.minimum):
                raise ValidationError("R-Tree occupancy is invalid")
            if not node.leaf and root and size < 2:
                raise ValidationError("Internal root must have at least two children")
            if node.box != covering(entry.box for entry in node.entries):
                raise ValidationError("R-Tree parent coverage is invalid")
            if node.leaf:
                leaves += 1
                depths.add(depth)
                for entry in node.entries:
                    if not isinstance(entry, SpatialEntry) or entry.identity in ids or entry.rid in rids:
                        raise ValidationError("Invalid or duplicated R-Tree leaf association")
                    ids[entry.identity] = entry
                    rids.add(entry.rid)
            else:
                for child in node.entries:
                    if not isinstance(child, _Node):
                        raise ValidationError("Internal R-Tree entry must be a node")
                    visit(child, depth + 1)
        visit(self._root, 0, True)
        if len(depths) != 1 or ids != self._identities or rids != self._rids:
            raise ValidationError("R-Tree depth or association counts disagree")
        return {"height": next(iter(depths)) + 1, "nodes": len(seen_nodes),
                "leaves": leaves, "entries": len(ids)}

    def save(self, path: Path, *, metadata: dict | None = None) -> None:
        self.validate_structure()
        def encode(node):
            box = None if node.box is None else [getattr(node.box, name) for name in node.box.__dataclass_fields__]
            if node.leaf:
                entries = [[item.identity, item.rid.page_id, item.rid.slot_id,
                            item.point.latitude, item.point.longitude] for item in node.entries]
            else:
                entries = [encode(child) for child in node.entries]
            return {"leaf": node.leaf, "box": box, "entries": entries}
        payload = {"format": "MINIDBMS_RTREE", "version": 1, "conventions": CONVENTIONS,
                   "capacity": self.capacity, "metadata": {} if metadata is None else metadata,
                   "root": encode(self._root)}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        document = {"sha256": hashlib.sha256(encoded.encode()).hexdigest(), "payload": payload}
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=".rtree-",
                                    dir=Path(path).parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(document, stream, separators=(",", ":"), allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            cancellation_point()
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path, *, metadata: dict | None = None) -> RTree:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
            if set(document) != {"sha256", "payload"}:
                raise ValueError("invalid document fields")
            payload = document["payload"]
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if hashlib.sha256(encoded.encode()).hexdigest() != document["sha256"]:
                raise ValueError("checksum mismatch")
            if (set(payload) != {"format", "version", "conventions", "capacity", "metadata", "root"}
                    or payload["format"] != "MINIDBMS_RTREE" or type(payload["version"]) is not int
                    or payload["version"] != 1 or payload["conventions"] != CONVENTIONS
                    or not isinstance(payload["metadata"], dict)
                    or (metadata is not None and payload["metadata"] != metadata)):
                raise ValueError("unsupported format, conventions or mapping")
            tree = cls(payload["capacity"])
            def decode(saved, depth=0):
                if depth > 64 or set(saved) != {"leaf", "box", "entries"} or type(saved["leaf"]) is not bool:
                    raise ValueError("invalid saved node")
                if type(saved["entries"]) is not list or len(saved["entries"]) > tree.capacity:
                    raise ValueError("invalid saved occupancy")
                entries = []
                for item in saved["entries"]:
                    if saved["leaf"]:
                        if type(item) is not list or len(item) != 5:
                            raise ValueError("invalid leaf entry")
                        identity, page, slot, latitude, longitude = item
                        entry = SpatialEntry(identity, RID(page, slot), Point(latitude, longitude))
                        if identity in tree._identities or entry.rid in tree._rids:
                            raise ValueError("duplicate saved association")
                        tree._identities[identity] = entry
                        tree._rids.add(entry.rid)
                        entries.append(entry)
                    else:
                        entries.append(decode(item, depth + 1))
                box = saved["box"]
                if box is not None and (type(box) is not list or len(box) != 4):
                    raise ValueError("invalid saved bounding box")
                return _Node(saved["leaf"], entries, None if box is None else MBR(*box))
            tree._root = decode(payload["root"])
            tree.validate_structure()
            return tree
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
            raise ValidationError(f"Invalid R-Tree file: {error}") from error
