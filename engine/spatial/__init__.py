"""Own spatial geometry, exhaustive Heap queries and a persistent R-Tree."""
from .geometry import MBR, Metric, Point, Polygon, distance
from .index import SpatialIndex
from .metadata import SpatialMapping, validate_coordinates
from .rtree import RTree, SpatialEntry, SpatialHit, SpatialResult

__all__ = ['MBR', 'Metric', 'Point', 'Polygon', 'distance', 'SpatialIndex',
           'SpatialMapping', 'validate_coordinates', 'RTree', 'SpatialEntry',
           'SpatialHit', 'SpatialResult']
