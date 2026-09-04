"""Stage 4 B+ binary constants and capacity invariants.

The generic database file prefix and the outer slotted-page framing remain
owned by :mod:`engine.storage`.  These constants describe only payloads stored
inside the B+ index metadata page and node pages.
"""

from enum import IntEnum
from struct import Struct

from engine.catalog.types import DataType
from engine.storage.binary import MAX_RECORD_SIZE, UINT32_MAX


BPLUS_FILE_MAGIC = "MINIDB_BPLUS"
BPLUS_FORMAT_VERSION = 1

BPLUS_NODE_MAGIC = b"BPND"
BPLUS_NODE_FORMAT_VERSION = 1
# magic, version, node type, key count, page id, leaf/free-list pointer
BPLUS_NODE_HEADER_FORMAT = "<4sBBHII"
BPLUS_RID_FORMAT = "<II"
BPLUS_CHILD_FORMAT = "<I"

BPLUS_NODE_HEADER_STRUCT = Struct(BPLUS_NODE_HEADER_FORMAT)
BPLUS_RID_STRUCT = Struct(BPLUS_RID_FORMAT)
BPLUS_CHILD_STRUCT = Struct(BPLUS_CHILD_FORMAT)

BPLUS_NODE_HEADER_SIZE = BPLUS_NODE_HEADER_STRUCT.size
BPLUS_RID_SIZE = BPLUS_RID_STRUCT.size
BPLUS_CHILD_SIZE = BPLUS_CHILD_STRUCT.size
BPLUS_NODE_PAYLOAD_SIZE = MAX_RECORD_SIZE

# PageManager can allocate page IDs 0 .. UINT32_MAX - 1.  The all-one value is
# consequently available as the on-disk null pointer for B+ metadata/nodes.
BPLUS_NULL_PAGE_ID = UINT32_MAX
BPLUS_MAX_NODE_PAGE_ID = UINT32_MAX - 1

# A bounded key size makes the fixed entry-count capacity safe for every node,
# including nodes whose current VARCHAR keys happen to be short.
BPLUS_MAX_VARCHAR_KEY_BYTES = 255


class BPlusNodeType(IntEnum):
    """Stable type tags used by the node-page codec."""

    LEAF = 1
    INTERNAL = 2
    FREE = 3


_MAX_ENCODED_KEY_SIZES = {
    DataType.INTEGER: 8,
    DataType.FLOAT: 8,
    DataType.BOOLEAN: 1,
    # Stage 2 VARCHAR encoding includes its four-byte byte-length prefix.
    DataType.VARCHAR: 4 + BPLUS_MAX_VARCHAR_KEY_BYTES,
}


def maximum_encoded_key_size(data_type: DataType) -> int:
    """Return the reserved encoded size for one key of ``data_type``."""

    return _MAX_ENCODED_KEY_SIZES[data_type]


def maximum_leaf_keys(data_type: DataType) -> int:
    """Maximum repeated ``(key, RID)`` pairs in one leaf node."""

    entry_size = maximum_encoded_key_size(data_type) + BPLUS_RID_SIZE
    return (BPLUS_NODE_PAYLOAD_SIZE - BPLUS_NODE_HEADER_SIZE) // entry_size


def maximum_internal_keys(data_type: DataType) -> int:
    """Maximum separators in one internal node with ``n + 1`` children."""

    available = (
        BPLUS_NODE_PAYLOAD_SIZE
        - BPLUS_NODE_HEADER_SIZE
        - BPLUS_CHILD_SIZE
    )
    entry_size = maximum_encoded_key_size(data_type) + BPLUS_CHILD_SIZE
    return available // entry_size
