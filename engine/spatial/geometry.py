"""Local point geometry in latitude/longitude, with distances in metres."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math

from engine.errors import ValidationError
from .metadata import EARTH_RADIUS_METRES as R, ORIGIN, validate_coordinates


def number(value, name: str) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValidationError(f"{name} must be a finite number")
    return float(value)


@dataclass(frozen=True, slots=True)
class Point:
    latitude: float
    longitude: float

    def __post_init__(self):
        latitude = number(self.latitude, "latitude")
        longitude = number(self.longitude, "longitude")
        validate_coordinates(latitude, longitude)
        object.__setattr__(self, "latitude", latitude)
        object.__setattr__(self, "longitude", longitude)


class Metric(str, Enum):
    HAVERSINE = "haversine"
    EUCLIDEAN = "euclidean"


def metric_value(value: Metric | str) -> Metric:
    try:
        return Metric(value)
    except (ValueError, TypeError) as error:
        raise ValidationError("Metric must be haversine or euclidean") from error


def radius_value(value) -> float:
    radius = number(value, "radius")
    if radius < 0:
        raise ValidationError("Radius must be non-negative metres")
    return radius


def k_value(value) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError("k must be a non-negative integer")
    return value


_X_SCALE = R * math.cos(math.radians(ORIGIN[0]))


def local_xy(point: Point) -> tuple[float, float]:
    return (_X_SCALE * math.radians(point.longitude - ORIGIN[1]),
            R * math.radians(point.latitude - ORIGIN[0]))


def distance(first: Point, second: Point, metric: Metric | str = Metric.HAVERSINE) -> float:
    selected = metric_value(metric)
    if selected is Metric.EUCLIDEAN:
        x1, y1 = local_xy(first)
        x2, y2 = local_xy(second)
        return math.hypot(x2 - x1, y2 - y1)
    phi1, phi2 = math.radians(first.latitude), math.radians(second.latitude)
    dphi = math.radians(second.latitude - first.latitude)
    dlam = math.radians(second.longitude - first.longitude)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(min(1.0, max(0.0, a))))


@dataclass(frozen=True, slots=True)
class MBR:
    min_latitude: float
    min_longitude: float
    max_latitude: float
    max_longitude: float

    def __post_init__(self):
        minimum = Point(self.min_latitude, self.min_longitude)
        maximum = Point(self.max_latitude, self.max_longitude)
        if minimum.latitude > maximum.latitude or minimum.longitude > maximum.longitude:
            raise ValidationError("MBR minima must not exceed maxima")
        for name, value in zip(self.__dataclass_fields__,
                               (minimum.latitude, minimum.longitude, maximum.latitude, maximum.longitude)):
            object.__setattr__(self, name, value)

    @classmethod
    def at(cls, point: Point) -> MBR:
        return cls(point.latitude, point.longitude, point.latitude, point.longitude)

    @property
    def area(self) -> float:
        return (self.max_latitude - self.min_latitude) * (self.max_longitude - self.min_longitude)

    def union(self, other: MBR) -> MBR:
        return MBR(min(self.min_latitude, other.min_latitude), min(self.min_longitude, other.min_longitude),
                   max(self.max_latitude, other.max_latitude), max(self.max_longitude, other.max_longitude))

    def enlargement(self, other: MBR) -> float:
        area = ((max(self.max_latitude, other.max_latitude) - min(self.min_latitude, other.min_latitude))
                * (max(self.max_longitude, other.max_longitude) - min(self.min_longitude, other.min_longitude)))
        return area - self.area

    def contains(self, other: MBR) -> bool:
        return (self.min_latitude <= other.min_latitude <= other.max_latitude <= self.max_latitude
                and self.min_longitude <= other.min_longitude <= other.max_longitude <= self.max_longitude)

    def intersects(self, other: MBR) -> bool:
        return not (self.max_latitude < other.min_latitude or other.max_latitude < self.min_latitude
                    or self.max_longitude < other.min_longitude or other.max_longitude < self.min_longitude)

    def lower_bound(self, point: Point, metric: Metric | str) -> float:
        selected = metric_value(metric)
        latitude_gap = max(self.min_latitude - point.latitude, 0.0, point.latitude - self.max_latitude)
        if selected is Metric.HAVERSINE:
            # Any great-circle route must cover at least its change in latitude.
            # Longitude is deliberately ignored; this bound is conservative.
            return max(0.0, R * math.radians(latitude_gap) - 1e-8)
        longitude_gap = max(self.min_longitude - point.longitude, 0.0, point.longitude - self.max_longitude)
        return max(0.0, math.hypot(R * math.radians(latitude_gap),
                                  _X_SCALE * math.radians(longitude_gap)) - 1e-8)


def covering(boxes) -> MBR | None:
    boxes = tuple(boxes)
    if not boxes:
        return None
    return MBR(min(box.min_latitude for box in boxes), min(box.min_longitude for box in boxes),
               max(box.max_latitude for box in boxes), max(box.max_longitude for box in boxes))


def _cross(a: Point, b: Point, p: Point) -> float:
    return ((b.longitude - a.longitude) * (p.latitude - a.latitude)
            - (b.latitude - a.latitude) * (p.longitude - a.longitude))


def _orientation_error(a: Point, b: Point, p: Point) -> float:
    # Scale with the segment and representable coordinates, not a fixed area:
    # centimetre-sized valid polygons must not become degenerate or all boundary.
    return 8 * (abs(b.longitude - a.longitude) * max(math.ulp(point.latitude) for point in (a, b, p))
                + abs(b.latitude - a.latitude) * max(math.ulp(point.longitude) for point in (a, b, p)))


def _on_edge(a: Point, b: Point, p: Point) -> bool:
    return (abs(_cross(a, b, p)) <= _orientation_error(a, b, p)
            and min(a.latitude, b.latitude) <= p.latitude <= max(a.latitude, b.latitude)
            and min(a.longitude, b.longitude) <= p.longitude <= max(a.longitude, b.longitude))


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    if any((_on_edge(a, b, c), _on_edge(a, b, d), _on_edge(c, d, a), _on_edge(c, d, b))):
        return True
    ab_c, ab_d, cd_a, cd_b = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    return ab_c * ab_d < 0 and cd_a * cd_b < 0


@dataclass(frozen=True, slots=True)
class Polygon:
    vertices: tuple[Point, ...]
    _box: MBR = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        vertices = tuple(self.vertices)
        if not all(isinstance(point, Point) for point in vertices):
            raise ValidationError("Polygon vertices must be typed points")
        if len(vertices) > 1 and vertices[0] == vertices[-1]:
            vertices = vertices[:-1]
        if len(vertices) < 3 or len(set(vertices)) != len(vertices):
            raise ValidationError("A polygon needs at least three distinct vertices")
        edges = list(zip(vertices, vertices[1:] + vertices[:1]))
        # Translate to one vertex to avoid subtracting large geographic products.
        triangles = [(vertices[0], a, b) for a, b in edges]
        area_twice = math.fsum(_cross(a, b, p) for a, b, p in triangles)
        area_error = sum(_orientation_error(a, b, p) for a, b, p in triangles)
        if abs(area_twice) <= area_error:
            raise ValidationError("Polygon must have non-zero area")
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges[i + 1:], i + 1):
                if j == i + 1 or (i == 0 and j == len(edges) - 1):
                    continue
                if _segments_intersect(a, b, c, d):
                    raise ValidationError("Only simple polygons without intersections are supported")
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "_box", covering(MBR.at(point) for point in vertices))

    @property
    def box(self) -> MBR:
        return self._box

    def contains(self, point: Point) -> bool:
        if not self.box.contains(MBR.at(point)):
            return False
        inside = False
        for a, b in zip(self.vertices, self.vertices[1:] + self.vertices[:1]):
            if _on_edge(a, b, point):
                return True
            if (a.latitude > point.latitude) != (b.latitude > point.latitude):
                x = a.longitude + (point.latitude - a.latitude) * (b.longitude - a.longitude) / (b.latitude - a.latitude)
                if point.longitude < x:
                    inside = not inside
        return inside
