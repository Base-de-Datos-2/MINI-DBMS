"""Offline one-way publication of a multimedia collection (reuses the storage seal).

Same policy as Part 3 (``engine.text.sealing``): every declared ordinary
secondary index is validated and sealed, then the exact Heap, with the
collection's id and generation as descriptor. No registry is written here.
All owners/coordinators must be closed; never unseal or restore a mutable
image over a sealed file. A failure may leave a partially sealed NEW build,
which is rebuilt elsewhere.
"""

from collections.abc import Sequence
from dataclasses import replace

from engine.errors import InvalidTypeError, ValidationError
from engine.indexes.unclustered_bplus import UnclusteredBPlusIndex
from engine.indexes.unclustered_hash import UnclusteredHashIndex
from engine.storage.heap_file import HeapFile
from engine.storage.seal import StorageSeal

from .collection import MultimediaCollection


def seal_multimedia_collection(storage: HeapFile, collection: MultimediaCollection, *,
                               secondary_indexes=()) -> StorageSeal:
    if not isinstance(storage, HeapFile) or not isinstance(collection, MultimediaCollection):
        raise InvalidTypeError("Multimedia sealing requires a HeapFile and MultimediaCollection")
    with storage.offline_publication():
        storage.require_offline_publication()
        if isinstance(secondary_indexes, (str, bytes)) or not isinstance(secondary_indexes, Sequence):
            raise InvalidTypeError("secondary_indexes must be a sequence")
        names = set()
        for item in secondary_indexes:
            if not isinstance(item, (UnclusteredBPlusIndex, UnclusteredHashIndex)):
                raise InvalidTypeError("Multimedia sealing supports only Heap B+ and hash secondary indexes")
            if item.heap is not storage:
                raise ValidationError("A secondary index belongs to a different Heap handle")
            core = item.tree if isinstance(item, UnclusteredBPlusIndex) else item.index
            if core.header.table_name != collection.table_name or core.header.index_name in names:
                raise ValidationError("Invalid or duplicate secondary-index association")
            names.add(core.header.index_name)
            item.require_offline_publication()
            item.validate_structure()
        descriptor = StorageSeal(collection.collection_id, collection.generation)
        replace(storage.metadata, seal=descriptor).serialize()   # capacity before any mutation
        if storage.record_count != collection.size:
            raise ValidationError("Heap record count differs from the multimedia collection")
        collection.verify_storage(storage)
        for item in secondary_indexes:
            item.seal()
        storage.seal(collection_id=descriptor.collection_id, generation=descriptor.generation)
        collection.require_compatible_storage(storage)
        return descriptor


__all__ = ["seal_multimedia_collection"]
