"""Create/open B+ runtime adapters from immutable catalog metadata."""

from __future__ import annotations

from engine.catalog import Catalog, IndexMetadata, IndexType
from engine.errors import InvalidTypeError, SchemaError, ValidationError
from engine.storage import HeapFile, PagedSequentialFile

from .clustered_bplus import ClusteredBPlusIndex
from .unclustered_bplus import UnclusteredBPlusIndex


BPlusRuntimeIndex = ClusteredBPlusIndex | UnclusteredBPlusIndex


def _resolve_definition(
    catalog: object,
    index_name: object,
    storage: object,
) -> tuple[IndexMetadata, HeapFile | PagedSequentialFile]:
    if not isinstance(catalog, Catalog):
        raise InvalidTypeError("catalog must be a Catalog")
    if not isinstance(index_name, str):
        raise InvalidTypeError("index_name must be a string")
    metadata = catalog.get_index(index_name)
    if metadata.index_type is not IndexType.BPLUS:
        raise ValidationError("Catalog definition is not a BPLUS index")
    if metadata.file_path is None:
        raise ValidationError("BPLUS catalog metadata requires file_path")
    if metadata.clustered:
        if not isinstance(storage, PagedSequentialFile):
            raise InvalidTypeError(
                "Clustered B+ metadata requires a PagedSequentialFile"
            )
    elif not isinstance(storage, HeapFile):
        raise InvalidTypeError("Unclustered B+ metadata requires a HeapFile")
    table = catalog.get_table(metadata.table_name)
    if storage.schema != table.schema:
        raise SchemaError("Open storage schema does not match catalog table schema")
    return metadata, storage


def build_catalog_bplus(
    catalog: Catalog,
    index_name: str,
    storage: HeapFile | PagedSequentialFile,
) -> BPlusRuntimeIndex:
    """Build the registered B+ file and return a separately owned runtime."""

    metadata, checked_storage = _resolve_definition(catalog, index_name, storage)
    arguments = dict(
        index_name=metadata.name,
        table_name=metadata.table_name,
        key_column=metadata.column_name,
        allow_duplicate_keys=metadata.allow_duplicate_keys,
    )
    if metadata.clustered:
        return ClusteredBPlusIndex.build(
            metadata.file_path,
            sequential=checked_storage,
            **arguments,
        )
    return UnclusteredBPlusIndex.build(
        metadata.file_path,
        heap=checked_storage,
        **arguments,
    )


def open_catalog_bplus(
    catalog: Catalog,
    index_name: str,
    storage: HeapFile | PagedSequentialFile,
) -> BPlusRuntimeIndex:
    """Open and validate a registered B+ against fresh storage state."""

    metadata, checked_storage = _resolve_definition(catalog, index_name, storage)
    arguments = dict(
        index_name=metadata.name,
        table_name=metadata.table_name,
        key_column=metadata.column_name,
        allow_duplicate_keys=metadata.allow_duplicate_keys,
    )
    if metadata.clustered:
        return ClusteredBPlusIndex.open(
            metadata.file_path,
            sequential=checked_storage,
            **arguments,
        )
    return UnclusteredBPlusIndex.open(
        metadata.file_path,
        heap=checked_storage,
        **arguments,
    )
