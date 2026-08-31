"""Record identifiers, rows, and the abstract storage contract."""

from engine.storage.base import Storage
from engine.storage.record import Record
from engine.storage.rid import RID

__all__ = ["RID", "Record", "Storage"]
