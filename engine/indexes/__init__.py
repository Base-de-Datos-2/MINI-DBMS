"""Index contracts plus persistent B+ and Extendible Hash foundations."""

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
from engine.indexes.extendible_hash import ExtendibleHashIndex, HashValidationReport
from engine.indexes.hash_bucket import HashBucket, HashBucketCodec
from engine.indexes.hash_codec import HashCodec
from engine.indexes.hash_directory import (
    HashDirectory,
    HashDirectoryCodec,
    HashDirectoryPage,
)
from engine.indexes.hash_header import HashFileHeader
from engine.indexes.hash_io import (
    HashBucketPageIO,
    HashDirectoryPageIO,
    HashHeaderPageIO,
)
from engine.indexes.hash_catalog import (
    build_and_register_catalog_hash,
    build_catalog_hash,
    open_catalog_hash,
)
from engine.indexes.hash_metrics import (
    HashBuildMetrics,
    HashMetrics,
    HashStructuralMetrics,
)
from engine.indexes.index_catalog import (
    build_catalog_index,
    drop_catalog_index,
    open_catalog_index,
)
from engine.indexes.unclustered_hash import UnclusteredHashIndex

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
    # Stage 5 public surface. Directory and bucket mutation stay
    # behind the facade even though their models/codecs remain testable.
    "HashCodec",
    "HashFileHeader",
    "HashDirectory",
    "HashDirectoryPage",
    "HashDirectoryCodec",
    "HashBucket",
    "HashBucketCodec",
    "HashHeaderPageIO",
    "HashDirectoryPageIO",
    "HashBucketPageIO",
    "ExtendibleHashIndex",
    "HashValidationReport",
    "HashBuildMetrics",
    "HashStructuralMetrics",
    "HashMetrics",
    "UnclusteredHashIndex",
    "build_catalog_hash",
    "open_catalog_hash",
    "build_and_register_catalog_hash",
    "build_catalog_index",
    "open_catalog_index",
    "drop_catalog_index",
]
