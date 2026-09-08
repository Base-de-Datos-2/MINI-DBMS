"""Create/open persistent hash runtimes from immutable catalog metadata."""

from __future__ import annotations

from pathlib import Path

from engine.catalog import Catalog, IndexMetadata, IndexType
from engine.errors import DuplicateError, InvalidTypeError, SchemaError, ValidationError
from engine.storage import HeapFile

from .unclustered_hash import UnclusteredHashIndex


def _resolve_hash_definition(
    catalog: object,
    index_name: object,
    storage: object,
) -> tuple[IndexMetadata, HeapFile]:
    if not isinstance(catalog, Catalog):
        raise InvalidTypeError("catalog must be a Catalog")
    if not isinstance(index_name, str):
        raise InvalidTypeError("index_name must be a string")
    metadata = catalog.get_index(index_name)
    if metadata.index_type is not IndexType.EXTENDIBLE_HASH:
        raise ValidationError("Catalog definition is not an EXTENDIBLE_HASH index")
    if metadata.file_path is None:
        raise ValidationError("EXTENDIBLE_HASH catalog metadata requires file_path")
    if not isinstance(storage, HeapFile):
        raise InvalidTypeError("Extendible Hash metadata requires a HeapFile")
    table = catalog.get_table(metadata.table_name)
    if storage.schema != table.schema:
        raise SchemaError("Open storage schema does not match catalog table schema")
    return metadata, storage


def build_catalog_hash(
    catalog: Catalog,
    index_name: str,
    storage: HeapFile,
) -> UnclusteredHashIndex:
    """Build one already registered hash definition over active Heap rows."""

    metadata, heap = _resolve_hash_definition(catalog, index_name, storage)
    return UnclusteredHashIndex.build(
        metadata.file_path,
        heap=heap,
        index_name=metadata.name,
        table_name=metadata.table_name,
        key_column=metadata.column_name,
        allow_duplicate_keys=metadata.allow_duplicate_keys,
    )


def open_catalog_hash(
    catalog: Catalog,
    index_name: str,
    storage: HeapFile,
) -> UnclusteredHashIndex:
    """Reopen and validate a registered hash against fresh Heap state."""

    metadata, heap = _resolve_hash_definition(catalog, index_name, storage)
    return UnclusteredHashIndex.open(
        metadata.file_path,
        heap=heap,
        index_name=metadata.name,
        table_name=metadata.table_name,
        key_column=metadata.column_name,
        allow_duplicate_keys=metadata.allow_duplicate_keys,
    )


def build_and_register_catalog_hash(
    catalog: Catalog,
    metadata: IndexMetadata,
    storage: HeapFile,
) -> UnclusteredHashIndex:
    """Build completely before publishing a new definition in the Catalog."""

    if not isinstance(catalog, Catalog):
        raise InvalidTypeError("catalog must be a Catalog")
    if not isinstance(metadata, IndexMetadata):
        raise InvalidTypeError("metadata must be IndexMetadata")
    if metadata.index_type is not IndexType.EXTENDIBLE_HASH:
        raise ValidationError("Metadata is not an EXTENDIBLE_HASH index")
    if metadata.file_path is None:
        raise ValidationError("EXTENDIBLE_HASH catalog metadata requires file_path")
    if not isinstance(storage, HeapFile):
        raise InvalidTypeError("Extendible Hash metadata requires a HeapFile")
    table = catalog.get_table(metadata.table_name)
    table.schema.column(metadata.column_name)
    if storage.schema != table.schema:
        raise SchemaError("Open storage schema does not match catalog table schema")
    for existing in catalog.list_indexes():
        if existing.name == metadata.name:
            raise DuplicateError(f"Duplicate index name: {metadata.name!r}")
        if existing.file_path == metadata.file_path:
            raise DuplicateError(f"Duplicate index file path: {metadata.file_path!r}")

    runtime = UnclusteredHashIndex.build(
        metadata.file_path,
        heap=storage,
        index_name=metadata.name,
        table_name=metadata.table_name,
        key_column=metadata.column_name,
        allow_duplicate_keys=metadata.allow_duplicate_keys,
    )
    try:
        # Catalog visibility is the final publication step after a valid build.
        catalog.register_index(metadata)
        return runtime
    except BaseException:
        runtime.close()
        Path(metadata.file_path).unlink(missing_ok=True)
        raise
