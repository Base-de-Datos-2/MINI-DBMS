"""Relational types, immutable metadata, and the in-memory catalog."""

from engine.catalog.catalog import Catalog
from engine.catalog.metadata import (
    MAX_DECLARED_VARCHAR_CODEPOINTS,
    ColumnConstraint,
    IndexMetadata,
    IndexType,
    TableMetadata,
)
from engine.catalog.schema import Column, Schema
from engine.catalog.types import DataType

__all__ = [
    "Catalog", "Column", "ColumnConstraint", "DataType", "IndexMetadata",
    "IndexType", "Schema", "TableMetadata",
]
