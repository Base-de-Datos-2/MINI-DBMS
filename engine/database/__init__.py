"""Persistent engine-owned database discovery and DDL orchestration."""

from .manifest import (
    DatabaseManifest,
    DatabaseManifestError,
    MANIFEST_FILENAME,
    MANIFEST_MAGIC,
    MANIFEST_VERSION,
    ManifestIndex,
    ManifestTable,
    decode_manifest,
    encode_manifest,
)
from .owner import Database, DatabaseSetupError, DatabaseUnavailableError

__all__ = [
    "Database",
    "DatabaseManifest",
    "DatabaseManifestError",
    "DatabaseSetupError",
    "DatabaseUnavailableError",
    "ManifestIndex",
    "ManifestTable",
    "decode_manifest",
    "encode_manifest",
]
