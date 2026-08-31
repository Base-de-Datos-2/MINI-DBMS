"""Record identifiers and rows; physical storage remains unimplemented."""

from engine.storage.record import Record
from engine.storage.rid import RID

__all__ = ["RID", "Record"]
