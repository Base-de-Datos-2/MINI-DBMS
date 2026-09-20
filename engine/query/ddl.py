"""Narrow query-to-database boundary for synchronous schema creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from engine.catalog import TableMetadata


@dataclass(frozen=True, slots=True)
class CreatedTable:
    """Durably published identity returned by one completed CREATE."""

    table_name: str
    primary_index_name: str | None = None


@runtime_checkable
class DdlService(Protocol):
    """Database-owned CREATE operations used by the query executor."""

    def validate_create(self, table: TableMetadata) -> None:
        """Validate current state without files, registration, or mutation."""

    def create_table(self, table: TableMetadata) -> CreatedTable:
        """Create, publish, and durably register one table synchronously."""


__all__ = ["CreatedTable", "DdlService"]
