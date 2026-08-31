"""Small shared error vocabulary, preserving Python exception compatibility.

Only explicit engine validations use these errors. Native Enum construction,
immutable dataclass assignment, and Python container operations keep their
standard exceptions. This module has no dependencies on engine components.
"""


class DatabaseError(Exception):
    """Base for errors explicitly reported by the database engine."""


class InvalidTypeError(DatabaseError, TypeError):
    """An argument or row value has an unsupported Python type."""


class ValidationError(DatabaseError, ValueError):
    """A correctly typed value violates a model or operation invariant."""


class SchemaError(ValidationError):
    """An invalid column/schema definition, including duplicate column names."""


class DuplicateError(ValidationError):
    """A registration would duplicate a name or an exclusive catalog role."""


class InvalidReferenceError(DatabaseError, KeyError):
    """A name, RID, or key/RID pair does not resolve in its owning component."""


class UnknownTableError(InvalidReferenceError):
    """A table name is not registered in the catalog."""


class UnknownColumnError(InvalidReferenceError):
    """A column name does not belong to the referenced schema."""


class ColumnPositionError(DatabaseError, IndexError):
    """A numeric column position is outside the schema."""
