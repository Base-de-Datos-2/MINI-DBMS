"""Explicit coordinate mapping over existing FLOAT records.

The registry describes coordinates, not a ready spatial index. Only the
offline loader creates it in E1. No parser or HTTP dependency belongs here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re

from engine.catalog import DataType, Schema
from engine.errors import ValidationError

REGISTRY_FILENAME = "spatial_tables.json"
FORMAT = "MINIDBMS_SPATIAL_TABLES"
VERSION = 1
LATITUDE_BOUNDS = (-12.30, -11.80)
LONGITUDE_BOUNDS = (-77.25, -76.75)
ORIGIN = (-12.0464, -77.0428)
# WGS84 mean radius (2*a+b)/3, matching the geography spherical comparator.
EARTH_RADIUS_METRES = 6371008.771415059
CONVENTIONS = {
    "point_order": "latitude,longitude",
    "latitude_bounds": list(LATITUDE_BOUNDS),
    "longitude_bounds": list(LONGITUDE_BOUNDS),
    "origin": list(ORIGIN),
    "earth_radius_metres": EARTH_RADIUS_METRES,
    "default_metric": "haversine",
    "distance_unit": "metres",
    "polygon_boundary": "included",
    "knn_tie_break": "id",
}


def validate_coordinates(latitude: float, longitude: float) -> None:
    """Require finite float coordinates inside the declared local domain."""
    for value, bounds, name in (
        (latitude, LATITUDE_BOUNDS, "latitude"),
        (longitude, LONGITUDE_BOUNDS, "longitude"),
    ):
        if type(value) is not float or not math.isfinite(value):
            raise ValidationError(f"{name} must be a finite FLOAT")
        if not bounds[0] <= value <= bounds[1]:
            raise ValidationError(f"{name} is outside the supported Lima domain")


@dataclass(frozen=True, slots=True)
class SpatialMapping:
    table: str
    latitude_column: str = "latitud"
    longitude_column: str = "longitud"
    identity_column: str = "id"
    location_name: str = "ubicacion"

    @property
    def index_name(self) -> str:
        return f"__spatial_{self.table}"

    @property
    def index_filename(self) -> str:
        return f"{self.index_name}.rtree"

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            if type(value) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value) is None:
                raise ValidationError("Spatial mapping names must be plain identifiers")
        if len({self.latitude_column, self.longitude_column, self.identity_column,
                self.location_name}) != 4:
            raise ValidationError("Spatial mapping names must be distinct")

    def validate_schema(self, schema: Schema) -> None:
        for name in (self.latitude_column, self.longitude_column):
            if schema.column(name).data_type is not DataType.FLOAT:
                raise ValidationError(f"Spatial coordinate {name!r} must be FLOAT")
        if schema.column(self.identity_column).data_type is not DataType.INTEGER:
            raise ValidationError("Spatial record identity must be INTEGER")
        if self.location_name in {column.name for column in schema}:
            raise ValidationError("Logical location conflicts with a physical column")


def read_mappings(root: Path) -> tuple[SpatialMapping, ...]:
    path = root / REGISTRY_FILENAME
    if not path.exists():
        return ()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if type(document) is not dict or set(document) != {
            "format", "version", "conventions", "tables"
        }:
            raise ValueError("invalid fields")
        if (document["format"] != FORMAT or type(document["version"]) is not int
                or document["version"] != VERSION or document["conventions"] != CONVENTIONS):
            raise ValueError("unsupported format or coordinate conventions")
        if type(document["tables"]) is not list:
            raise ValueError("tables must be a list")
        mappings = tuple(SpatialMapping(**item) for item in document["tables"])
        if len({mapping.table for mapping in mappings}) != len(mappings):
            raise ValueError("duplicate table mapping")
        return mappings
    except (ValueError, TypeError) as error:
        raise ValidationError(f"Invalid {REGISTRY_FILENAME}: {error}") from error


def write_mappings(root: Path, mappings: tuple[SpatialMapping, ...]) -> None:
    """Publish a new offline registry exclusively; never replace live metadata."""
    if len({mapping.table for mapping in mappings}) != len(mappings):
        raise ValidationError("Duplicate spatial table mapping")
    document = {"format": FORMAT, "version": VERSION, "conventions": CONVENTIONS,
                "tables": [asdict(mapping) for mapping in mappings]}
    with (root / REGISTRY_FILENAME).open("x", encoding="utf-8", newline="\n") as output:
        json.dump(document, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
