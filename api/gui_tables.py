"""Persist the tables created from the GUI next to the demo database.

The demo owner is definition-driven: its fixtures are declared in Python and
reopened by name. Tables created later through the Files panel (empty or
imported from CSV) have no Python declaration, so their definitions live in
``gui_tables.json`` inside the same data directory. The server rewrites that
file atomically only after every file of a new table is built and flushed, so
it is the publication point of a GUI CREATE: a crash before it leaves orphan
files that are never opened, never a half-registered table.

Logical names never become paths. Every table and index file uses an opaque
UUID4 identity (``g_<uuid32>.heap``/``.seq``/``.bpt``/``.hsh``), so two names
that differ only in case cannot collide on a case-insensitive file system.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from engine.catalog import DataType, IndexType
from engine.errors import ValidationError


REGISTRY_FILENAME = "gui_tables.json"
REGISTRY_FORMAT = "MINIDBMS_GUI_TABLES"
REGISTRY_VERSION = 1

HEAP = "HEAP"
SEQUENTIAL = "SEQUENTIAL"

_TABLE_SUFFIX = {HEAP: ".heap", SEQUENTIAL: ".seq"}
_INDEX_SUFFIX = {IndexType.BPLUS: ".bpt", IndexType.EXTENDIBLE_HASH: ".hsh"}
_IDENTITY_RE = re.compile(r"[0-9a-f]{32}\Z")


class RegistryError(ValidationError):
    """The GUI table registry is malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class GuiIndex:
    """One persisted single-column index of a GUI-created table."""

    name: str
    identity: str
    column: str
    index_type: IndexType
    unique: bool
    clustered: bool

    @property
    def filename(self) -> str:
        return f"g_{self.identity}{_INDEX_SUFFIX[self.index_type]}"


@dataclass(frozen=True, slots=True)
class GuiTable:
    """One persisted GUI-created table and where its rows came from."""

    name: str
    identity: str
    organization: str
    key_column: str | None
    columns: tuple[tuple[str, DataType], ...]
    indexes: tuple[GuiIndex, ...]
    origin: str
    source_filename: str | None
    loaded_rows: int

    @property
    def filename(self) -> str:
        return f"g_{self.identity}{_TABLE_SUFFIX[self.organization]}"


def new_identity() -> str:
    """Return a fresh opaque file identity."""

    return uuid4().hex


def registry_path(root: Path) -> Path:
    return root / REGISTRY_FILENAME


def _encode(tables: tuple[GuiTable, ...]) -> bytes:
    document = {
        "format": REGISTRY_FORMAT,
        "version": REGISTRY_VERSION,
        "tables": [
            {
                "name": table.name,
                "id": table.identity,
                "organization": table.organization,
                "key_column": table.key_column,
                "columns": [
                    {"name": name, "type": data_type.value}
                    for name, data_type in table.columns
                ],
                "indexes": [
                    {
                        "name": index.name,
                        "id": index.identity,
                        "column": index.column,
                        "type": index.index_type.value,
                        "unique": index.unique,
                        "clustered": index.clustered,
                    }
                    for index in table.indexes
                ],
                "origin": {
                    "kind": table.origin,
                    "filename": table.source_filename,
                    "rows": table.loaded_rows,
                },
            }
            for table in tables
        ],
    }
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _field(document: object, key: str, kind: type | tuple[type, ...], label: str):
    if type(document) is not dict or key not in document:
        raise RegistryError(f"{label}: falta el campo {key!r}")
    value = document[key]
    if not isinstance(value, kind) or (kind is int and type(value) is bool):
        raise RegistryError(f"{label}: el campo {key!r} tiene un tipo inválido")
    return value


def _identity(value: str, label: str) -> str:
    if _IDENTITY_RE.fullmatch(value) is None:
        raise RegistryError(f"{label}: identidad de archivo inválida")
    return value


def _decode_index(document: object, label: str) -> GuiIndex:
    try:
        index_type = IndexType(_field(document, "type", str, label))
    except ValueError:
        raise RegistryError(f"{label}: tipo de índice desconocido") from None
    return GuiIndex(
        name=_field(document, "name", str, label),
        identity=_identity(_field(document, "id", str, label), label),
        column=_field(document, "column", str, label),
        index_type=index_type,
        unique=_field(document, "unique", bool, label),
        clustered=_field(document, "clustered", bool, label),
    )


def _decode_table(document: object) -> GuiTable:
    label = "gui_tables.json"
    name = _field(document, "name", str, label)
    label = f"gui_tables.json, tabla {name!r}"
    organization = _field(document, "organization", str, label)
    if organization not in _TABLE_SUFFIX:
        raise RegistryError(f"{label}: organización desconocida")
    key_column = document.get("key_column")
    if key_column is not None and type(key_column) is not str:
        raise RegistryError(f"{label}: key_column inválida")
    columns = []
    for column in _field(document, "columns", list, label):
        try:
            data_type = DataType(_field(column, "type", str, label))
        except ValueError:
            raise RegistryError(f"{label}: tipo de columna desconocido") from None
        columns.append((_field(column, "name", str, label), data_type))
    origin = _field(document, "origin", dict, label)
    source_filename = origin.get("filename")
    if source_filename is not None and type(source_filename) is not str:
        raise RegistryError(f"{label}: origin.filename inválido")
    return GuiTable(
        name=name,
        identity=_identity(_field(document, "id", str, label), label),
        organization=organization,
        key_column=key_column,
        columns=tuple(columns),
        indexes=tuple(
            _decode_index(item, label)
            for item in _field(document, "indexes", list, label)
        ),
        origin=_field(origin, "kind", str, label),
        source_filename=source_filename,
        loaded_rows=_field(origin, "rows", int, label),
    )


def read_registry(root: Path) -> tuple[GuiTable, ...]:
    """Return the GUI tables of ``root`` in creation order; none if absent."""

    path = registry_path(root)
    if not path.is_file():
        return ()
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryError(f"gui_tables.json no es JSON válido: {error}") from None
    if (
        type(document) is not dict
        or document.get("format") != REGISTRY_FORMAT
        or document.get("version") != REGISTRY_VERSION
    ):
        raise RegistryError("gui_tables.json tiene un formato o versión desconocidos")
    tables = tuple(
        _decode_table(item) for item in _field(document, "tables", list, "gui_tables.json")
    )
    names = [table.name for table in tables]
    if len(names) != len(set(names)):
        raise RegistryError("gui_tables.json repite un nombre de tabla")
    return tables


def write_registry(root: Path, tables: tuple[GuiTable, ...]) -> None:
    """Atomically replace the registry after flushing a same-directory temp."""

    path = registry_path(root)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(_encode(tables))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Directory fsync is unavailable on some Windows/Python combinations;
        # the registry file itself is always flushed first.
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except (AttributeError, OSError):
            return
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
