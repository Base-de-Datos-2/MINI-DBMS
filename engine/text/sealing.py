"""Offline one-way publication policy, independent of SQL/owner registries."""

from collections.abc import Sequence
from dataclasses import replace

from engine.errors import InvalidTypeError, ValidationError
from engine.indexes.unclustered_bplus import UnclusteredBPlusIndex
from engine.indexes.unclustered_hash import UnclusteredHashIndex
from engine.storage.heap_file import HeapFile
from engine.storage.seal import StorageSeal

from .index import TextIndex


def seal_text_collection(storage: HeapFile, index: TextIndex, *, secondary_indexes=()) -> StorageSeal:
    """Validate and seal all declared ordinary indexes, then the exact Heap.

    The caller enumerates the collection's complete secondary-index set. No
    directory registry is written here (4B). All owners/coordinators must be
    closed. Failure during publication may leave a partially sealed NEW build;
    policy disagreement fails closed on adapter reopen. Rebuild elsewhere;
    never unseal or restore a mutable image over a sealed file.
    """
    if not isinstance(storage, HeapFile) or not isinstance(index, TextIndex):
        raise InvalidTypeError("Text sealing requires a HeapFile and TextIndex")
    with storage.offline_publication():
        return _seal_offline(storage, index, secondary_indexes)


def _seal_offline(storage, index, secondary_indexes):
    storage.require_offline_publication()
    index._require_open()
    if storage.schema != index.table.schema:
        raise ValidationError("Text seal schema differs from the source Heap")
    if isinstance(secondary_indexes, (str, bytes)) or not isinstance(secondary_indexes, Sequence):
        raise InvalidTypeError("secondary_indexes must be a sequence")
    names = set()
    for item in secondary_indexes:
        if not isinstance(item, (UnclusteredBPlusIndex, UnclusteredHashIndex)):
            raise InvalidTypeError("Text sealing supports only Heap B+ and hash secondary indexes")
        if item.heap is not storage:
            raise ValidationError("A secondary index belongs to a different Heap handle")
        core = item.tree if isinstance(item, UnclusteredBPlusIndex) else item.index
        if core.header.table_name != index.table.name or core.header.index_name in names:
            raise ValidationError("Invalid or duplicate secondary-index association")
        names.add(core.header.index_name)
        item.require_offline_publication()
        item.validate_structure()
    descriptor = StorageSeal(index.collection_id, index.generation)
    replace(storage.metadata, seal=descriptor).serialize()  # capacity before any mutation
    index.validate()
    index.verify_storage(storage)
    for item in secondary_indexes:
        item.seal()
    storage.seal(collection_id=descriptor.collection_id, generation=descriptor.generation)
    index.require_compatible_storage(storage)
    return descriptor


__all__ = ["seal_text_collection"]
