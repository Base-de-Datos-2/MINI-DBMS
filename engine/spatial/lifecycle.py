"""Spatial associations participate in the existing owner locks and physical undo."""
from dataclasses import replace

from engine.maintenance.service import MutationService
from engine.transactions.runtime import TableRuntime
from .index import SpatialIndex


class SpatialMutationService(MutationService):
    def __init__(self, indexes: dict[str, SpatialIndex]):
        self.indexes = indexes

    def validate_insert(self, table_name, record):
        if table_name in self.indexes:
            self.indexes[table_name].validate_insert(record)

    def after_insert(self, table_name, record, rid):
        if table_name in self.indexes:
            self.indexes[table_name].inserted(rid, record)

    def after_delete(self, table_name, completed_rows):
        if completed_rows and table_name in self.indexes:
            self.indexes[table_name].rebuild()

    def insert(self, **kwargs):
        report = super().insert(**kwargs)
        index = self.indexes.get(kwargs['table_name'])
        return report if index is None else replace(report,
            indexes_maintained=(*report.indexes_maintained, index.mapping.index_name),
            index_association_updates=report.index_association_updates + 1)

    def delete(self, **kwargs):
        report = super().delete(**kwargs)
        index = self.indexes.get(kwargs['table_name'])
        return report if index is None else replace(report,
            indexes_maintained=(*report.indexes_maintained, index.mapping.index_name),
            indexes_rebuilt=(*report.indexes_rebuilt, index.mapping.index_name) if report.affected_rows else report.indexes_rebuilt)


class SpatialTableRuntime(TableRuntime):
    def __init__(self, catalog, environment, storages, indexes, spatial_indexes, mappings, root):
        super().__init__(catalog, environment, storages, indexes)
        self.spatial_indexes, self.mappings, self.root = spatial_indexes, mappings, root
        self._reopening = set()

    def flush(self, files):
        super().flush(files)
        if files.name in self.mappings:
            self.spatial_indexes[files.name].flush()

    def close_table(self, files):
        index = self.spatial_indexes.pop(files.name, None)
        if index is not None:
            self.environment.unregister_spatial(files.name)
            index.close()
        super().close_table(files)

    def reopen(self, files):
        self._reopening.add(files.name)
        try:
            super().reopen(files)
        finally:
            self._reopening.discard(files.name)
        if files.name in self.mappings:
            mapping = self.mappings[files.name]
            self.spatial_indexes[files.name] = SpatialIndex.open_or_build(
                self.environment.storage_for(files.name), mapping, self.root / mapping.index_filename)
            self.environment.register_spatial(files.name, self.spatial_indexes[files.name])
        self.validate(files)

    def validate(self, files):
        super().validate(files)
        if files.name in self.mappings and files.name not in self._reopening:
            self.spatial_indexes[files.name].validate_structure()
