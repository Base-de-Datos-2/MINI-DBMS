"""Interface checks only; concrete algorithm conformance belongs to later stages."""

from collections.abc import Generator
from inspect import Parameter, signature
from typing import get_type_hints

import pytest

from engine.indexes import Index, OrderedIndex
from engine.operators import Operator
from engine.storage import RID, Record, Storage


@pytest.mark.parametrize(
    ("contract", "methods"),
    [
        (Storage, {"insert", "read", "delete", "scan"}),
        (Index, {"insert", "search", "delete"}),
        (OrderedIndex, {"insert", "search", "delete", "range_search"}),
        (Operator, {"open", "next", "close"}),
    ],
)
def test_contracts_require_every_declared_operation(contract, methods):
    assert contract.__abstractmethods__ == methods
    with pytest.raises(TypeError, match="abstract"):
        contract()

    def stub(self, *args, **kwargs):
        raise AssertionError("Only ABC enforcement is under test")

    for missing in methods:
        partial = type("Partial", (contract,), {
            name: stub for name in methods - {missing}
        })
        with pytest.raises(TypeError, match=missing):
            partial()

    complete = type("Complete", (contract,), {name: stub for name in methods})
    assert isinstance(complete(), contract)


def test_storage_contract_connects_records_rids_and_closable_scans():
    assert get_type_hints(Storage.insert) == {"record": Record, "return": RID}
    assert get_type_hints(Storage.read) == {"rid": RID, "return": Record}
    assert get_type_hints(Storage.delete) == {"rid": RID, "return": type(None)}
    assert get_type_hints(Storage.scan)["return"] == Generator[tuple[RID, Record], None, None]


def test_equality_only_index_can_implement_contract_without_ranges():
    # A scripted test double, not a hash/index implementation.
    class EqualityProbe(Index[int]):
        def insert(self, key: int, rid: RID) -> None:
            self.inserted = (key, rid)

        def search(self, key: int) -> Generator[RID, None, None]:
            self.searched = key
            try:
                yield RID(4, 2)
            finally:
                self.search_closed = True

        def delete(self, key: int, rid: RID) -> None:
            self.deleted = (key, rid)

    index = EqualityProbe()
    assert not isinstance(index, OrderedIndex)
    assert not hasattr(index, "range_search")
    rid = RID(4, 2)
    assert index.insert(7, rid) is None
    assert index.inserted == (7, rid)
    results = index.search(7)
    try:
        assert next(results) == rid
        assert index.searched == 7
    finally:
        results.close()
    assert index.search_closed
    assert index.delete(7, rid) is None
    assert index.deleted == (7, rid)


def test_index_search_contracts_stream_rids():
    for method in (Index.search, OrderedIndex.range_search):
        assert get_type_hints(method)["return"] == Generator[RID, None, None]
    for method in (Index.insert, Index.delete):
        assert get_type_hints(method)["rid"] is RID
        assert get_type_hints(method)["return"] is type(None)


def test_ordered_index_adds_optional_bounds_and_keyword_only_inclusion_flags():
    assert issubclass(OrderedIndex, Index)
    parameters = signature(OrderedIndex.range_search).parameters
    assert parameters["lower"].default is None
    assert parameters["upper"].default is None
    for name in ("include_lower", "include_upper"):
        assert parameters[name].kind is Parameter.KEYWORD_ONLY
        assert parameters[name].default is True
        assert get_type_hints(OrderedIndex.range_search)[name] is bool


def test_operator_contract_distinguishes_rows_from_exhaustion():
    assert get_type_hints(Operator.open) == {"return": type(None)}
    assert get_type_hints(Operator.next) == {"return": Record | None}
    assert get_type_hints(Operator.close) == {"return": type(None)}
