"""Strict version-1 discovery manifest for engine-owned databases."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from engine.catalog import (
    Column,
    ColumnConstraint,
    DataType,
    IndexMetadata,
    IndexType,
    MAX_DECLARED_VARCHAR_CODEPOINTS,
    Schema,
    TableMetadata,
)
from engine.errors import InvalidTypeError, ValidationError


MANIFEST_FILENAME = "database.catalog.json"
MANIFEST_MAGIC = "MINIDB_CATALOG"
MANIFEST_VERSION = 1
MAX_MANIFEST_BYTES = 4 * 1024 * 1024

_IDENTITY_RE = re.compile(r"[0-9a-f]{32}\Z")
_TABLE_FILE_RE = re.compile(r"t_([0-9a-f]{32})\.heap\Z")
_INDEX_FILE_RE = re.compile(r"i_([0-9a-f]{32})\.bpt\Z")


class DatabaseManifestError(ValidationError):
    """A database discovery manifest is missing, malformed, or inconsistent."""


def _require_fields(document: object, expected: set[str], label: str) -> dict:
    if type(document) is not dict:
        raise DatabaseManifestError(f"{label} must be a JSON object")
    actual = set(document)
    if actual != expected:
        raise DatabaseManifestError(
            f"Invalid {label} fields; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    return document


def _require_string(value: object, label: str) -> str:
    if type(value) is not str:
        raise InvalidTypeError(f"{label} must be a string")
    if not value.strip():
        raise DatabaseManifestError(f"{label} must not be empty")
    return value


def _require_identity(value: object, label: str) -> str:
    identity = _require_string(value, label)
    if _IDENTITY_RE.fullmatch(identity) is None:
        raise DatabaseManifestError(
            f"{label} must contain 32 lowercase hexadecimal characters"
        )
    return identity


def _require_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise InvalidTypeError(f"{label} must be a boolean")
    return value


def _require_relative_file(
    value: object,
    identity: str,
    pattern: re.Pattern[str],
    label: str,
) -> str:
    filename = _require_string(value, label)
    if Path(filename).is_absolute() or Path(filename).name != filename:
        raise DatabaseManifestError(f"{label} must be one relative filename")
    match = pattern.fullmatch(filename)
    if match is None or match.group(1) != identity:
        raise DatabaseManifestError(f"{label} does not match its physical identity")
    return filename


@dataclass(frozen=True, slots=True)
class ManifestIndex:
    name: str
    identity: str
    table_name: str
    column_name: str
    index_type: IndexType
    unique: bool
    clustered: bool
    filename: str
    ready: bool

    def metadata(self, root: Path) -> IndexMetadata:
        return IndexMetadata(
            self.name,
            self.table_name,
            self.column_name,
            self.index_type,
            clustered=self.clustered,
            unique=self.unique,
            file_path=str(managed_path(root, self.filename)),
        )

    def document(self) -> dict[str, object]:
        return {
            "clustered": self.clustered,
            "column": self.column_name,
            "file": self.filename,
            "id": self.identity,
            "name": self.name,
            "ready": self.ready,
            "table": self.table_name,
            "type": self.index_type.value,
            "unique": self.unique,
        }


@dataclass(frozen=True, slots=True)
class ManifestTable:
    name: str
    identity: str
    filename: str
    metadata: TableMetadata
    indexes: tuple[ManifestIndex, ...]

    def document(self) -> dict[str, object]:
        return {
            "columns": [
                {
                    "name": column.name,
                    "type": column.data_type.value,
                    "varchar_length": self.metadata.varchar_length(column.name),
                }
                for column in self.metadata.schema
            ],
            "file": self.filename,
            "id": self.identity,
            "indexes": [index.document() for index in self.indexes],
            "name": self.name,
            "organization": "HEAP",
            "primary_key": self.metadata.primary_key,
        }


@dataclass(frozen=True, slots=True)
class DatabaseManifest:
    name: str
    identity: str
    tables: tuple[ManifestTable, ...] = ()

    def document(self) -> dict[str, object]:
        return {
            "database": {"id": self.identity, "name": self.name},
            "magic": MANIFEST_MAGIC,
            "tables": [table.document() for table in self.tables],
            "version": MANIFEST_VERSION,
        }


def new_manifest(name: str) -> DatabaseManifest:
    return DatabaseManifest(_require_string(name, "Database name"), uuid4().hex)


def managed_path(root: Path, filename: str) -> Path:
    """Resolve one already-validated managed filename inside ``root``."""

    if not isinstance(root, Path):
        raise InvalidTypeError("Database root must be a Path")
    if type(filename) is not str or Path(filename).name != filename:
        raise DatabaseManifestError("Managed file must be one relative filename")
    resolved_root = root.resolve()
    resolved = (resolved_root / filename).resolve()
    if resolved.parent != resolved_root:
        raise DatabaseManifestError("Managed file escapes the database root")
    return resolved


def _decode_column(document: object) -> tuple[Column, int | None]:
    value = _require_fields(
        document,
        {"name", "type", "varchar_length"},
        "column",
    )
    name = _require_string(value["name"], "Column name")
    if type(value["type"]) is not str:
        raise InvalidTypeError("Column type must be a string")
    try:
        data_type = DataType(value["type"])
    except ValueError as error:
        raise DatabaseManifestError("Unknown manifest column type") from error
    if data_type not in {DataType.INTEGER, DataType.VARCHAR}:
        raise DatabaseManifestError(
            "Manifest-backed SQL tables support INTEGER and VARCHAR only"
        )
    length = value["varchar_length"]
    if data_type is DataType.INTEGER:
        if length is not None:
            raise DatabaseManifestError("INTEGER columns cannot declare VARCHAR length")
    else:
        if type(length) is not int:
            raise InvalidTypeError("VARCHAR length must be an integer")
        if not 1 <= length <= MAX_DECLARED_VARCHAR_CODEPOINTS:
            raise DatabaseManifestError(
                "VARCHAR length is outside the supported declaration range"
            )
    return Column(name, data_type), length


def _decode_index(document: object, table_name: str) -> ManifestIndex:
    value = _require_fields(
        document,
        {"clustered", "column", "file", "id", "name", "ready", "table", "type", "unique"},
        "index",
    )
    identity = _require_identity(value["id"], "Index identity")
    persisted_table = _require_string(value["table"], "Index table")
    if persisted_table != table_name:
        raise DatabaseManifestError("Index table reference does not match its owner")
    if value["type"] != IndexType.BPLUS.value:
        raise DatabaseManifestError("Version-1 managed indexes must use BPLUS")
    return ManifestIndex(
        name=_require_string(value["name"], "Index name"),
        identity=identity,
        table_name=table_name,
        column_name=_require_string(value["column"], "Index column"),
        index_type=IndexType.BPLUS,
        unique=_require_bool(value["unique"], "Index unique"),
        clustered=_require_bool(value["clustered"], "Index clustered"),
        filename=_require_relative_file(
            value["file"], identity, _INDEX_FILE_RE, "Index file"
        ),
        ready=_require_bool(value["ready"], "Index ready"),
    )


def _decode_table(document: object) -> ManifestTable:
    value = _require_fields(
        document,
        {"columns", "file", "id", "indexes", "name", "organization", "primary_key"},
        "table",
    )
    name = _require_string(value["name"], "Table name")
    identity = _require_identity(value["id"], "Table identity")
    if value["organization"] != "HEAP":
        raise DatabaseManifestError("Version-1 managed tables must use HEAP")
    if type(value["columns"]) is not list or not value["columns"]:
        raise DatabaseManifestError("Managed table columns must be a non-empty list")
    decoded_columns = tuple(_decode_column(item) for item in value["columns"])
    schema = Schema([item[0] for item in decoded_columns])
    primary_key = value["primary_key"]
    if primary_key is not None:
        primary_key = _require_string(primary_key, "Primary key")
        try:
            schema.column(primary_key)
        except KeyError as error:
            raise DatabaseManifestError("Primary key references an unknown column") from error

    constraints = []
    for column, length in decoded_columns:
        is_primary = column.name == primary_key
        if length is not None or is_primary:
            constraints.append(ColumnConstraint(column.name, length, is_primary))
    metadata = TableMetadata(name, schema, tuple(constraints))

    if type(value["indexes"]) is not list:
        raise InvalidTypeError("Table indexes must be a list")
    indexes = tuple(_decode_index(item, name) for item in value["indexes"])
    index_names = [index.name for index in indexes]
    if len(index_names) != len(set(index_names)):
        raise DatabaseManifestError("Duplicate manifest index name")
    for index in indexes:
        try:
            schema.column(index.column_name)
        except KeyError as error:
            raise DatabaseManifestError("Index references an unknown column") from error

    primary_name = f"__pk__{name}" if primary_key is not None else None
    primary_indexes = [index for index in indexes if index.name == primary_name]
    if primary_key is not None:
        if len(primary_indexes) != 1:
            raise DatabaseManifestError("Primary key requires its managed B+ index")
        primary = primary_indexes[0]
        if (
            primary.column_name != primary_key
            or not primary.unique
            or primary.clustered
        ):
            raise DatabaseManifestError("Managed primary-key index definition is invalid")
    if any(index.name.startswith("__pk__") for index in indexes if index.name != primary_name):
        raise DatabaseManifestError("The __pk__ index prefix is engine-reserved")

    return ManifestTable(
        name=name,
        identity=identity,
        filename=_require_relative_file(
            value["file"], identity, _TABLE_FILE_RE, "Table file"
        ),
        metadata=metadata,
        indexes=indexes,
    )


def decode_manifest(payload: bytes) -> DatabaseManifest:
    if not isinstance(payload, bytes):
        raise InvalidTypeError("Manifest payload must be bytes")
    if len(payload) > MAX_MANIFEST_BYTES:
        raise DatabaseManifestError("Database manifest exceeds its size limit")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DatabaseManifestError(f"Duplicate manifest field: {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise DatabaseManifestError(f"Invalid manifest JSON constant: {value}")

    try:
        document = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except DatabaseManifestError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DatabaseManifestError("Malformed database manifest") from error

    root = _require_fields(document, {"database", "magic", "tables", "version"}, "manifest")
    if root["magic"] != MANIFEST_MAGIC:
        raise DatabaseManifestError("Invalid database manifest signature")
    if type(root["version"]) is not int or root["version"] != MANIFEST_VERSION:
        raise DatabaseManifestError("Unsupported database manifest version")
    database = _require_fields(root["database"], {"id", "name"}, "database identity")
    if type(root["tables"]) is not list:
        raise InvalidTypeError("Manifest tables must be a list")
    tables = tuple(_decode_table(item) for item in root["tables"])

    table_names = [table.name for table in tables]
    index_names = [index.name for table in tables for index in table.indexes]
    identities = [table.identity for table in tables]
    identities.extend(index.identity for table in tables for index in table.indexes)
    files = [table.filename for table in tables]
    files.extend(index.filename for table in tables for index in table.indexes)
    for values, label in (
        (table_names, "table name"),
        (index_names, "index name"),
        (identities, "physical identity"),
        (files, "managed file"),
    ):
        if len(values) != len(set(values)):
            raise DatabaseManifestError(f"Duplicate manifest {label}")

    return DatabaseManifest(
        name=_require_string(database["name"], "Database name"),
        identity=_require_identity(database["id"], "Database identity"),
        tables=tables,
    )


def encode_manifest(manifest: DatabaseManifest) -> bytes:
    if not isinstance(manifest, DatabaseManifest):
        raise InvalidTypeError("manifest must be a DatabaseManifest")
    try:
        payload = (
            json.dumps(
                manifest.document(),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise DatabaseManifestError("Manifest names must use strict UTF-8") from error
    if len(payload) > MAX_MANIFEST_BYTES:
        raise DatabaseManifestError("Database manifest exceeds its size limit")
    # Round-trip through the strict decoder before persistence.
    decode_manifest(payload)
    return payload


def read_manifest(path: Path) -> DatabaseManifest:
    if not isinstance(path, Path):
        raise InvalidTypeError("Manifest path must be a Path")
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_MANIFEST_BYTES + 1)
    except FileNotFoundError as error:
        raise DatabaseManifestError(f"Missing database manifest: {path.name}") from error
    if len(payload) > MAX_MANIFEST_BYTES:
        raise DatabaseManifestError("Database manifest exceeds its size limit")
    return decode_manifest(payload)


def write_manifest_atomic(path: Path, manifest: DatabaseManifest) -> None:
    """Replace one canonical manifest after flushing its same-directory temp."""

    if not isinstance(path, Path):
        raise InvalidTypeError("Manifest path must be a Path")
    payload = encode_manifest(manifest)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Directory fsync is unavailable on some supported Windows/Python
        # combinations. The committed file itself is always flushed first.
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except (AttributeError, OSError):
            return
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            try:
                os.close(directory_fd)
            except OSError:
                # The manifest has already been atomically installed. A
                # best-effort directory durability aid must not turn that
                # committed replacement into a reported CREATE failure.
                pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "DatabaseManifest",
    "DatabaseManifestError",
    "ManifestIndex",
    "ManifestTable",
    "decode_manifest",
    "encode_manifest",
    "managed_path",
    "new_manifest",
    "read_manifest",
    "write_manifest_atomic",
]
