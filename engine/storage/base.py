"""Storage boundary only: no files, pages, allocation, or persistence here."""

from abc import ABC, abstractmethod
from collections.abc import Generator

from engine.storage.record import Record
from engine.storage.rid import RID


class Storage(ABC):
    """Abstract storage for records sharing one fixed schema.

    Concrete organizations decide how that schema is supplied. They must
    validate inputs before mutation and keep live RIDs usable in this storage.
    RIDs are storage-relative; callers must not pass one from another table.
    This interface does not prescribe ordering, files, pages, transactions,
    concurrent mutation semantics, or a physical resource-opening API.

    ABC enforces method implementation, not the behavioral rules documented
    here. Future concrete implementations need their own conformance tests.
    """

    @abstractmethod
    def insert(self, record: Record) -> RID:
        """Insert one row and return its RID; equal rows may coexist.

        Raise InvalidTypeError (TypeError) if record is not a Record, or
        SchemaError (ValueError) if its schema differs from this storage's
        schema, including column order. Neither error may change stored rows.
        No implicit conversions or index maintenance are performed by this
        contract. Physical capacity and I/O errors belong to later stages.
        """
        raise NotImplementedError

    @abstractmethod
    def read(self, rid: RID) -> Record:
        """Return the live row at rid, without removing it.

        Raise InvalidTypeError for a non-RID argument; raise
        InvalidReferenceError (KeyError) for an absent or deleted location.
        Never return None to represent a missing row.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, rid: RID) -> None:
        """Remove the live row at rid; return None on success.

        Use the same errors as read. Deleting an absent/deleted RID is an
        InvalidReferenceError, not a silent success. Other rows are unchanged.
        Physical reclamation and reuse are implementation responsibilities.
        """
        raise NotImplementedError

    @abstractmethod
    def scan(self) -> Generator[tuple[RID, Record], None, None]:
        """Yield each live (RID, Record) pair once, excluding deleted rows.

        With no concurrent mutation, a scan covers all live rows. No common
        ordering is promised. Empty storage yields nothing (StopIteration).
        Each call creates a fresh, independently consumable generator.

        A scan must stream, not require materializing the entire table.
        Implementations release scan-owned resources in a finally block on
        exhaustion, failure, or close(). Callers that may stop early must use
        contextlib.closing or a try/finally calling the generator's close().
        Closing a scan must not close the borrowed storage itself.
        """
        raise NotImplementedError
