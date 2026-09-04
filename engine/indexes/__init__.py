"""Index contracts and the persistent B+ foundation."""

from engine.indexes.base import Index, OrderedIndex
from engine.indexes.bplus_codec import BPlusKeyCodec, BPlusRIDCodec
from engine.indexes.bplus_header import BPlusFileHeader
from engine.indexes.bplus_io import BPlusHeaderPageIO, BPlusNodePageIO
from engine.indexes.bplus_catalog import (
    build_catalog_bplus,
    open_catalog_bplus,
)
from engine.indexes.bplus_metrics import (
    BPlusBuildMetrics,
    BPlusStructuralMetrics,
    ClusteredReorganizationMetrics,
)
from engine.indexes.bplus_node import (
    BPlusFreeNode,
    BPlusInternalNode,
    BPlusLeafNode,
    BPlusNodeType,
)
from engine.indexes.bplus_node_codec import BPlusNodeCodec
from engine.indexes.bplus_tree import (
    BPlusDescent,
    BPlusPathEntry,
    BPlusTree,
    BPlusValidationReport,
)
from engine.indexes.unclustered_bplus import UnclusteredBPlusIndex
from engine.indexes.clustered_bplus import ClusteredBPlusIndex

__all__ = [
    "Index",
    "OrderedIndex",
    "BPlusFileHeader",
    "BPlusKeyCodec",
    "BPlusRIDCodec",
    "BPlusNodeType",
    "BPlusLeafNode",
    "BPlusInternalNode",
    "BPlusFreeNode",
    "BPlusNodeCodec",
    "BPlusHeaderPageIO",
    "BPlusNodePageIO",
    "BPlusBuildMetrics",
    "BPlusStructuralMetrics",
    "ClusteredReorganizationMetrics",
    "BPlusPathEntry",
    "BPlusDescent",
    "BPlusTree",
    "BPlusValidationReport",
    "UnclusteredBPlusIndex",
    "ClusteredBPlusIndex",
    "build_catalog_bplus",
    "open_catalog_bplus",
]
