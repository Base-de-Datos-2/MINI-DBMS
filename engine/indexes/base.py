"""Equality and ordered-index boundaries, with no physical index algorithms."""

from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Generic, TypeVar

from engine.storage.rid import RID


Key = TypeVar("Key", int, float, bool, str)


class Index(ABC, Generic[Key]):
    """Index key/RID associations for one column of one storage.

    Concrete indexes are configured with one exact built-in key type, following
    Record's typing policy; no coercion (including bool/int mixing) is allowed.
    Wrong key/RID types raise InvalidTypeError (TypeError). NaN keys raise
    ValidationError (ValueError): they do not have reflexive equality. FLOAT
    records may still contain NaN; the restriction is on indexing those values.
    Infinite float keys are allowed. RIDs are not resolved through storage here.

    A key may reference multiple RIDs. Search methods stream through fresh,
    closable generators; no match means an empty generator, never None. Unless
    range_search specifies otherwise, result order is unspecified. Generator
    errors may surface at first iteration, so callers must protect consumption
    as well as creation. Resources owned by a search must be released on
    exhaustion, failure, or close(); callers use contextlib.closing on early exit.
    Closing results does not close the index. Mutation during iteration and
    physical persistence are outside this contract.

    ABC checks required methods only; implementations must test these semantics.
    Hash indexes implement this class without implementing range_search.
    """

    @abstractmethod
    def insert(self, key: Key, rid: RID) -> None:
        """Add an association; inserting the same (key, RID) again is a no-op.

        Different RIDs for the same key are allowed. Validation failures must
        leave associations unchanged. This operation does not insert a row.
        """
        raise NotImplementedError

    @abstractmethod
    def search(self, key: Key) -> Generator[RID, None, None]:
        """Yield each RID associated with this exact key once."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: Key, rid: RID) -> None:
        """Remove only this association, returning None on success.

        Raise InvalidReferenceError (KeyError) if the pair does not exist,
        even if the key exists with other RIDs. Errors leave the index unchanged.
        Deleting an association never deletes the referenced storage row.
        """
        raise NotImplementedError


class OrderedIndex(Index[Key]):
    """An index that additionally supports ascending traversal by key."""

    @abstractmethod
    def range_search(
        self,
        lower: Key | None = None,
        upper: Key | None = None,
        *,
        include_lower: bool = True,
        include_upper: bool = True,
    ) -> Generator[RID, None, None]:
        """Yield RIDs in ascending key order within the requested bounds.

        None means an unbounded end, not a NULL key. Both bounds are inclusive
        by default; flags must be built-in bools or raise InvalidTypeError.
        Bounds follow the index's exact key type and NaN validation rules.
        An inverted interval raises ValidationError. Equal bounds yield
        equality matches only when both ends are included, otherwise nothing.
        Flags for unbounded ends have no effect. With no bounds, traverse all
        associations. Each pair appears once; order among equal keys is not
        specified, and a RID may recur if associated with different keys.

        Use Python's native ordering for the configured type, including
        case-sensitive Unicode string ordering. Cleanup and lazy error rules
        are the same as for search().
        """
        raise NotImplementedError
