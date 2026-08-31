"""Logical relational types, independent from their future binary encoding."""

from enum import Enum


class DataType(Enum):
    """Supported type identifiers with explicit, stable textual values."""

    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    VARCHAR = "VARCHAR"
