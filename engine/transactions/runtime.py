"""Owner-backed table handles used by transaction completion.

The adapter only touches one table at a time. Callers retain its table X lock
through every call; unrelated tables keep their existing handles and files.
"""

from __future__ import annotations

from threading import RLock

from engine.catalog import Catalog
from engine.indexes import open_catalog_index
from engine.query.environment import QueryEnvironment
from engine.storage import HeapFile, PagedSequentialFile

from .resources import TableFiles


class TableRuntime:
    def __init__(
        self,
        catalog: Catalog,
        environment: QueryEnvironment,
        storages: dict,
        indexes: dict,
    ) -> None:
        self.catalog = catalog
        self.environment = environment
        self.storages = storages
        self.indexes = indexes
        self._mutex = RLock()
        self._kinds = {
            name: type(storage) for name, storage in storages.items()
        }

    def flush(self, files: TableFiles) -> None:
        # Adapter flushes include their borrowed base; the base is also flushed
        # explicitly for tables without indexes.
        self.environment.storage_for(files.name).flush()
        for name, _ in files.indexes:
            self.environment.index_for(name).flush()

    def close_table(self, files: TableFiles) -> None:
        for name, _ in files.indexes:
            index = self.environment.unregister_index(name)
            index.close()
            with self._mutex:
                self.indexes.pop(name, None)
        storage = self.environment.unregister_storage(files.name)
        with self._mutex:
            self._kinds[files.name] = type(storage)
        storage.close()
        with self._mutex:
            self.storages.pop(files.name, None)

    def reopen(self, files: TableFiles) -> None:
        with self._mutex:
            kind = self._kinds[files.name]
        if kind not in (HeapFile, PagedSequentialFile):
            raise TypeError(f"Unsupported persistent storage adapter: {kind!r}")
        schema = self.catalog.get_table(files.name).schema
        storage = kind.open(files.base, schema)
        opened = []
        try:
            self.environment.register_storage(files.name, storage)
            with self._mutex:
                self.storages[files.name] = storage
            for name, _ in files.indexes:
                index = open_catalog_index(self.catalog, name, storage)
                opened.append((name, index))
                self.environment.register_index(name, index)
                with self._mutex:
                    self.indexes[name] = index
            self.validate(files)
        except BaseException:
            for name, index in reversed(opened):
                with self._mutex:
                    registered = name in self.indexes
                if registered:
                    self.environment.unregister_index(name)
                    with self._mutex:
                        self.indexes.pop(name, None)
                index.close()
            with self._mutex:
                registered_storage = files.name in self.storages
            if registered_storage:
                self.environment.unregister_storage(files.name)
                with self._mutex:
                    self.storages.pop(files.name, None)
            storage.close()
            raise

    def validate(self, files: TableFiles) -> None:
        storage = self.environment.storage_for(files.name)
        # Count/scan verifies the reopened page and slot state, and each adapter
        # verifies both its physical structure and one-to-one base coverage.
        from contextlib import closing
        with closing(storage.scan()) as rows:
            count = sum(1 for _ in rows)
        if count != storage.record_count:
            raise ValueError(f"Stored row count disagrees with scan of {files.name!r}")
        for name, _ in files.indexes:
            self.environment.index_for(name).validate_structure()
