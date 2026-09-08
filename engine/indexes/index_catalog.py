"""Shared Catalog dispatch for the Stage 4 and Stage 5 index families."""

from __future__ import annotations

from pathlib import Path

from engine.catalog import Catalog, IndexType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage import HeapFile, PagedSequentialFile

from .bplus_catalog import BPlusRuntimeIndex, build_catalog_bplus, open_catalog_bplus
from .bplus_tree import BPlusTree
from .extendible_hash import ExtendibleHashIndex
from .hash_catalog import build_catalog_hash, open_catalog_hash
from .unclustered_hash import UnclusteredHashIndex


CatalogRuntimeIndex = BPlusRuntimeIndex | UnclusteredHashIndex


def build_catalog_index(
    catalog: Catalog,
    index_name: str,
    storage: HeapFile | PagedSequentialFile,
) -> CatalogRuntimeIndex:
    """Dispatch a registered definition to its real physical builder."""

    if not isinstance(catalog, Catalog):
        raise InvalidTypeError("catalog must be a Catalog")
    metadata = catalog.get_index(index_name)
    if metadata.index_type is IndexType.BPLUS:
        return build_catalog_bplus(catalog, index_name, storage)
    if metadata.index_type is IndexType.EXTENDIBLE_HASH:
        if not isinstance(storage, HeapFile):
            raise InvalidTypeError("Extendible Hash requires a HeapFile")
        return build_catalog_hash(catalog, index_name, storage)
    raise ValidationError(f"Unsupported index type: {metadata.index_type!r}")


def open_catalog_index(
    catalog: Catalog,
    index_name: str,
    storage: HeapFile | PagedSequentialFile,
) -> CatalogRuntimeIndex:
    """Dispatch reopening without hidden format or constructor defaults."""

    if not isinstance(catalog, Catalog):
        raise InvalidTypeError("catalog must be a Catalog")
    metadata = catalog.get_index(index_name)
    if metadata.index_type is IndexType.BPLUS:
        return open_catalog_bplus(catalog, index_name, storage)
    if metadata.index_type is IndexType.EXTENDIBLE_HASH:
        if not isinstance(storage, HeapFile):
            raise InvalidTypeError("Extendible Hash requires a HeapFile")
        return open_catalog_hash(catalog, index_name, storage)
    raise ValidationError(f"Unsupported index type: {metadata.index_type!r}")


def drop_catalog_index(catalog: Catalog, index_name: str) -> None:

    #Remueve un archivo de índice físico independiente y luego sus metadatos de catálogo.

    if not isinstance(catalog, Catalog):
        raise InvalidTypeError("catalog must be a Catalog")
    if not isinstance(index_name, str):
        raise InvalidTypeError("index_name must be a string")
    metadata = catalog.get_index(index_name)
    if metadata.file_path is None:
        raise ValidationError("Catalog index metadata requires file_path")
    table = catalog.get_table(metadata.table_name)
    key_type = table.schema.column(metadata.column_name).data_type
    # Validate identity and format before unlinking so a stale catalog path can
    # never authorize deletion of an unrelated file.
    if metadata.index_type is IndexType.BPLUS:
        physical = BPlusTree.open(
            metadata.file_path,
            index_name=metadata.name,
            table_name=metadata.table_name,
            key_column=metadata.column_name,
            key_type=key_type,
            clustered=metadata.clustered,
            allow_duplicate_keys=metadata.allow_duplicate_keys,
        )
    elif metadata.index_type is IndexType.EXTENDIBLE_HASH:
        physical = ExtendibleHashIndex.open(
            metadata.file_path,
            index_name=metadata.name,
            table_name=metadata.table_name,
            key_column=metadata.column_name,
            key_type=key_type,
            allow_duplicate_keys=metadata.allow_duplicate_keys,
        )
    else:  # pragma: no cover - current Enum is exhaustive
        raise ValidationError(f"Unsupported index type: {metadata.index_type!r}")
    physical.close()
    Path(metadata.file_path).unlink()
    catalog.unregister_index(index_name)
