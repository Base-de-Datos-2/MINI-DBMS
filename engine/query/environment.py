"""Runtime object registry paired with immutable Catalog metadata.

The Catalog deliberately owns definitions only.  Query planning and mutation
execution also need the already-open storage and index objects that implement
those definitions.  ``QueryEnvironment`` joins the two without taking
ownership of either object and without performing any I/O during lookup.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.catalog import Catalog, IndexMetadata
from engine.errors import (
    DuplicateError,
    InvalidReferenceError,
    InvalidTypeError,
    SchemaError,
    ValidationError,
)
from engine.indexes import Index, OrderedIndex
from engine.storage import Storage


@dataclass(frozen=True, slots=True)
class RegisteredIndex:
    """One catalog definition paired with its borrowed runtime index."""

    metadata: IndexMetadata
    index: Index


class QueryEnvironment:
    """Resolve Catalog names to borrowed, live runtime objects.

    Registration is explicit so a missing or mismatched handle fails before a
    plan is executed.  The environment never opens, closes, builds, or mutates
    a storage/index object; the caller retains lifecycle ownership.
    """

    __slots__ = ("_catalog", "_storages", "_indexes")

    def __init__(self, catalog: Catalog) -> None:
        if not isinstance(catalog, Catalog):
            raise InvalidTypeError("QueryEnvironment requires a Catalog")
        self._catalog = catalog
        self._storages: dict[str, Storage] = {}
        self._indexes: dict[str, Index] = {}

    @property
    def catalog(self) -> Catalog:
        """Return the borrowed metadata catalog."""

        return self._catalog

    def register_storage(self, table_name: str, storage: Storage) -> None:
        """Pair an exact table name with one borrowed storage adapter."""

        table = self._catalog.get_table(table_name)
        if not isinstance(storage, Storage):
            raise InvalidTypeError("Registered table storage must implement Storage")
        if table.name in self._storages:
            raise DuplicateError(
                f"Storage is already registered for table {table.name!r}"
            )
        if any(registered is storage for registered in self._storages.values()):
            raise DuplicateError(
                "One runtime storage object cannot represent two Catalog tables"
            )
        if getattr(storage, "closed", False):
            raise ValidationError(
                f"Cannot register closed storage for table {table.name!r}"
            )

        # Storage's Stage 1 interface does not require a schema property, but
        # every persistent organization in this project exposes one.  Validate
        # it when available without weakening compatibility with other valid
        # Storage implementations.
        runtime_schema = getattr(storage, "schema", None)
        if runtime_schema is not None and runtime_schema != table.schema:
            raise SchemaError(
                f"Storage schema does not match table {table.name!r} metadata"
            )
        self._storages[table.name] = storage

    def storage_for(self, table_name: str) -> Storage:
        """Return the borrowed storage for an existing Catalog table."""

        table = self._catalog.get_table(table_name)
        try:
            storage = self._storages[table.name]
        except KeyError as error:
            raise InvalidReferenceError(
                f"No runtime storage is registered for table {table.name!r}"
            ) from error
        if getattr(storage, "closed", False):
            raise InvalidReferenceError(
                f"Runtime storage for table {table.name!r} is closed"
            )
        return storage

    def unregister_storage(self, table_name: str) -> Storage:
        """Remove and return one borrowed storage association without closing it."""

        table = self._catalog.get_table(table_name)
        try:
            return self._storages.pop(table.name)
        except KeyError as error:
            raise InvalidReferenceError(
                f"No runtime storage is registered for table {table.name!r}"
            ) from error

    def register_index(self, index_name: str, index: Index) -> None:
        """Pair an exact Catalog index definition with a borrowed adapter."""

        metadata = self._catalog.get_index(index_name)
        if not isinstance(index, Index):
            raise InvalidTypeError("Registered runtime index must implement Index")
        if metadata.name in self._indexes:
            raise DuplicateError(
                f"Runtime index is already registered for {metadata.name!r}"
            )
        if any(registered is index for registered in self._indexes.values()):
            raise DuplicateError(
                "One runtime index object cannot represent two Catalog indexes"
            )
        if getattr(index, "closed", False):
            raise ValidationError(
                f"Cannot register closed index {metadata.name!r}"
            )

        # An index adapter is meaningful to this query environment only beside
        # the exact table storage whose RIDs it resolves.
        self.storage_for(metadata.table_name)
        self._validate_index_identity(metadata, index)
        self._indexes[metadata.name] = index

    def _validate_index_identity(
        self,
        metadata: IndexMetadata,
        index: Index,
    ) -> None:
        """Cross-check runtime headers exposed by the Stage 4/5 adapters."""

        is_ordered = isinstance(index, OrderedIndex)
        if metadata.supports_range != is_ordered:
            raise ValidationError(
                f"Runtime index {metadata.name!r} ordering capability does not "
                "match its Catalog index type"
            )

        core = getattr(index, "tree", None)
        if core is None:
            core = getattr(index, "index", None)
        if core is None:
            core = index
        header = getattr(core, "header", None)
        if header is not None:
            if getattr(header, "build_complete", True) is not True:
                raise ValidationError(
                    f"Runtime index {metadata.name!r} is not completely built"
                )

            expected = {
                "index_name": metadata.name,
                "table_name": metadata.table_name,
                "key_column": metadata.column_name,
                "clustered": metadata.clustered,
                "allow_duplicate_keys": metadata.allow_duplicate_keys,
            }
            for attribute, value in expected.items():
                runtime_value = getattr(header, attribute, value)
                if runtime_value != value:
                    raise ValidationError(
                        f"Runtime index {metadata.name!r} has incompatible "
                        f"{attribute}: expected {value!r}, got {runtime_value!r}"
                    )

            key_type = self._catalog.get_table(metadata.table_name).schema.column(
                metadata.column_name
            ).data_type
            runtime_key_type = getattr(core, "key_type", key_type)
            if runtime_key_type is not key_type:
                raise ValidationError(
                    f"Runtime index {metadata.name!r} key type does not match "
                    "its Catalog column"
                )

        borrowed_storage = getattr(index, "heap", None)
        if borrowed_storage is None:
            borrowed_storage = getattr(index, "sequential", None)
        registered_storage = self._storages.get(metadata.table_name)
        if metadata.clustered and borrowed_storage is None:
            raise ValidationError(
                f"Clustered index {metadata.name!r} requires its coordinated "
                "storage adapter"
            )
        if (
            borrowed_storage is not None
            and registered_storage is not None
            and borrowed_storage is not registered_storage
        ):
            raise ValidationError(
                f"Runtime index {metadata.name!r} is attached to a different "
                "storage object than its table"
            )

    def index_for(self, index_name: str) -> Index:
        """Return a registered runtime index after validating its definition."""

        metadata = self._catalog.get_index(index_name)
        try:
            index = self._indexes[metadata.name]
        except KeyError as error:
            raise InvalidReferenceError(
                f"No runtime index is registered for {metadata.name!r}"
            ) from error
        if getattr(index, "closed", False):
            raise InvalidReferenceError(
                f"Runtime index {metadata.name!r} is closed"
            )
        # Registration proves compatibility at one instant. Recheck the
        # borrowed objects before every later use because a coordinated
        # rebuild may temporarily mark an index incomplete and the table
        # storage may have been closed independently by its owner.
        self.storage_for(metadata.table_name)
        self._validate_index_identity(metadata, index)
        return index

    def unregister_index(self, index_name: str) -> Index:
        """Remove and return one borrowed index association without closing it."""

        metadata = self._catalog.get_index(index_name)
        try:
            return self._indexes.pop(metadata.name)
        except KeyError as error:
            raise InvalidReferenceError(
                f"No runtime index is registered for {metadata.name!r}"
            ) from error

    def registered_indexes_for(self, table_name: str) -> tuple[RegisteredIndex, ...]:
        """Return available table indexes in deterministic Catalog order."""

        return tuple(
            RegisteredIndex(metadata, self.index_for(metadata.name))
            for metadata in self._catalog.get_indexes(table_name)
            if metadata.name in self._indexes
        )

    def require_indexes_for(self, table_name: str) -> tuple[RegisteredIndex, ...]:
        """Return every declared index or reject an unsafe mutation setup."""

        bindings = []
        for metadata in self._catalog.get_indexes(table_name):
            bindings.append(RegisteredIndex(metadata, self.index_for(metadata.name)))
        return tuple(bindings)


__all__ = ["QueryEnvironment", "RegisteredIndex"]
