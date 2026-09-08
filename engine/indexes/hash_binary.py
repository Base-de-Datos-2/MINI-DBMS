"""Binary constants for the Stage 5 persistent Extendible Hash index.

The comments in this module make the adopted disk format visible: the outer
4096-byte frame remains a normal storage ``Page`` and these structures occupy
the single active payload stored inside that page.
"""

from struct import Struct

from engine.storage.binary import MAX_RECORD_SIZE, UINT32_MAX


# The header is canonical JSON, while directory and bucket pages use these
# stable binary signatures and versions.
HASH_FILE_MAGIC = "MINIDB_EHASH"
HASH_FORMAT_VERSION = 1
HASH_DIRECTORY_MAGIC = b"HDIR"
HASH_BUCKET_MAGIC = b"HBKT"
HASH_PAGE_FORMAT_VERSION = 1

# FNV-1a is deliberately small and teachable, but—unlike Python's hash()—its
# result is reproducible in every process.
HASH_ALGORITHM = "FNV1A"
HASH_ALGORITHM_VERSION = 1
HASH_WIDTH = 64
HASH_BIT_SELECTION = "LSB"
HASH_INITIAL_GLOBAL_DEPTH = 1
HASH_DEFAULT_MAX_GLOBAL_DEPTH = 20

# Directory page: magic, version, reserved, entries in this page, ordinal,
# next-page pointer. Every logical entry is one uint32 bucket page identifier.
HASH_DIRECTORY_HEADER_STRUCT = Struct("<4sBBHII")
HASH_DIRECTORY_ENTRY_STRUCT = Struct("<I")
HASH_DIRECTORY_HEADER_SIZE = HASH_DIRECTORY_HEADER_STRUCT.size
HASH_DIRECTORY_ENTRY_SIZE = HASH_DIRECTORY_ENTRY_STRUCT.size
HASH_DIRECTORY_ENTRIES_PER_PAGE = (
    MAX_RECORD_SIZE - HASH_DIRECTORY_HEADER_SIZE
) // HASH_DIRECTORY_ENTRY_SIZE

# Bucket page: magic, version, local depth, association count, physical page
# identifier, and exact number of meaningful bytes including this header.
HASH_BUCKET_HEADER_STRUCT = Struct("<4sBBHII")
HASH_BUCKET_KEY_LENGTH_STRUCT = Struct("<H")
HASH_BUCKET_HEADER_SIZE = HASH_BUCKET_HEADER_STRUCT.size
HASH_BUCKET_KEY_LENGTH_SIZE = HASH_BUCKET_KEY_LENGTH_STRUCT.size
HASH_BUCKET_PAYLOAD_SIZE = MAX_RECORD_SIZE

# PageManager never allocates UINT32_MAX, so the all-one value is a persistent
# null pointer in directory chains.
HASH_NULL_PAGE_ID = UINT32_MAX
HASH_MAX_PAGE_ID = UINT32_MAX - 1
HASH_UINT64_MAX = (1 << 64) - 1

