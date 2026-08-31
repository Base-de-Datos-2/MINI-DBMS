"""Equality/range examples and failure cleanup, without index algorithms."""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidReferenceError, InvalidTypeError, ValidationError
from engine.indexes import OrderedIndex
from engine.storage import RID, Record
from tests.doubles import EqualityIndexDouble, OrderedIndexDouble


@pytest.fixture(params=[EqualityIndexDouble, OrderedIndexDouble])
def index(request):
    return request.param()


def test_index_empty_duplicates_multiple_rids_and_exact_pair_deletion(index):
    first, second = RID(0, 0), RID(0, 1)
    assert list(index.search(7)) == []
    assert index.insert(7, first) is None
    index.insert(7, first)
    index.insert(7, second)
    assert set(index.search(7)) == {first, second}
    assert len(list(index.search(7))) == 2
    assert list(index.search(99)) == []
    assert index.delete(7, first) is None
    for key, rid in ((7, first), (99, second)):
        with pytest.raises(InvalidReferenceError):
            index.delete(key, rid)
    assert list(index.search(7)) == [second]
    index.delete(7, second)
    assert list(index.search(7)) == []


def test_equality_double_does_not_promise_ordered_access():
    index = EqualityIndexDouble()
    assert not isinstance(index, OrderedIndex)
    assert not hasattr(index, "range_search")


@pytest.mark.parametrize("wrong_key", [True, 1.0, "1", None])
def test_index_validation_preserves_associations_and_rejects_coercion(index, wrong_key):
    rid = RID(0, 0)
    index.insert(1, rid)
    for operation in (index.insert, index.delete):
        with pytest.raises(InvalidTypeError):
            operation(wrong_key, rid)
        with pytest.raises(InvalidTypeError):
            operation(1, (0, 0))
    with closing(index.search(wrong_key)) as results:
        with pytest.raises(InvalidTypeError):
            list(results)  # Validation may be deferred until consumption.
    assert index.searches.active == 0
    assert list(index.search(1)) == [rid]


@pytest.mark.parametrize(
    ("data_type", "key"),
    [(DataType.INTEGER, 7), (DataType.FLOAT, 1.5),
     (DataType.BOOLEAN, False), (DataType.VARCHAR, "Árbol 東京")],
)
def test_index_uses_each_supported_record_key_type(data_type, key):
    index = EqualityIndexDouble(data_type)
    rid = RID(0, 0)
    record = Record(Schema([Column("key", data_type)]), [key])
    index.insert(record["key"], rid)
    assert list(index.search(key)) == [rid]


def test_float_indexes_reject_nan_without_restricting_records_and_accept_infinity():
    index = OrderedIndexDouble(DataType.FLOAT)
    nan = float("nan")
    record = Record(Schema([Column("value", DataType.FLOAT)]), [nan])
    assert record["value"] is nan
    for operation in (index.insert, index.delete):
        with pytest.raises(ValidationError, match="NaN"):
            operation(nan, RID(0, 0))
    for results in (index.search(nan), index.range_search(nan), index.range_search(upper=nan)):
        with closing(results), pytest.raises(ValidationError, match="NaN"):
            list(results)
    index.insert(float("inf"), RID(0, 1))
    index.insert(float("-inf"), RID(0, 0))
    assert list(index.range_search()) == [RID(0, 0), RID(0, 1)]
    assert list(index.search(float("inf"))) == [RID(0, 1)]


@pytest.mark.parametrize(
    ("bounds", "flags", "expected"),
    [
        ((), {}, [1, 2, 3]),
        ((2,), {}, [2, 3]),
        ((None, 2), {}, [1, 2]),
        ((1, 3), {"include_lower": False}, [2, 3]),
        ((1, 3), {"include_upper": False}, [1, 2]),
        ((1, 3), {"include_lower": False, "include_upper": False}, [2]),
        ((2, 2), {}, [2]),
        ((2, 2), {"include_lower": False}, []),
        ((2, 2), {"include_upper": False}, []),
        ((None, None), {"include_lower": False, "include_upper": False}, [1, 2, 3]),
        ((4, 9), {}, []),
    ],
)
def test_ordered_ranges_follow_bounds_not_insertion_order(bounds, flags, expected):
    index = OrderedIndexDouble()
    for key in (3, 1, 2):
        index.insert(key, RID(0, key))
    assert list(index.range_search(*bounds, **flags)) == [RID(0, key) for key in expected]
    assert index.searches.active == 0


@pytest.mark.parametrize(
    ("arguments", "error"),
    [({"lower": 3, "upper": 1}, ValidationError),
     ({"lower": True}, InvalidTypeError), ({"upper": "3"}, InvalidTypeError),
     ({"include_lower": 1}, InvalidTypeError), ({"include_upper": None}, InvalidTypeError)],
)
def test_range_errors_do_not_change_associations(arguments, error):
    index = OrderedIndexDouble()
    index.insert(2, RID(0, 0))
    with closing(index.range_search(**arguments)) as results, pytest.raises(error):
        list(results)
    assert list(index.search(2)) == [RID(0, 0)]
    assert index.searches.active == 0


def test_ranges_preserve_pairs_with_tied_keys_and_repeated_rids():
    index = OrderedIndexDouble()
    first, second = RID(0, 0), RID(0, 1)
    for pair in ((2, second), (1, first), (1, second), (1, first)):
        index.insert(*pair)
    results = list(index.range_search())
    assert set(results[:2]) == {first, second}
    assert results[2:] == [second]
    assert list(index.range_search(9, 10)) == []


def test_string_range_order_is_native_and_case_sensitive():
    index = OrderedIndexDouble(DataType.VARCHAR)
    for position, key in enumerate(("á", "a", "A")):
        index.insert(key, RID(0, position))
    assert list(index.range_search("A", "a")) == [RID(0, 2), RID(0, 1)]


@pytest.mark.parametrize("search_kind", ["equality", "range"])
@pytest.mark.parametrize("exit_mode", ["exhausted", "early", "consumer_error", "source_error"])
def test_searches_are_lazy_independent_and_always_releasable(search_kind, exit_mode):
    index = OrderedIndexDouble()
    for number in range(3):
        index.insert(7, RID(0, number))
    search = (lambda: index.search(7)) if search_kind == "equality" else index.range_search
    unused = search()
    unused.close()
    assert index.searches.opened == 0
    marker = RuntimeError("search failure")
    if exit_mode == "source_error":
        index.searches.fail_after, index.searches.error = 1, marker

    def consume():
        with closing(search()) as results:
            assert next(results) in {RID(0, number) for number in range(3)}
            assert index.searches.yielded == 1
            if exit_mode == "consumer_error":
                raise marker
            if exit_mode != "early":
                list(results)

    if exit_mode.endswith("error"):
        with pytest.raises(RuntimeError) as caught:
            consume()
        assert caught.value is marker
    else:
        consume()
    assert index.searches.opened == index.searches.closed == 1
    assert index.searches.active == 0
    index.searches.fail_after = None
    with closing(search()) as first, closing(search()) as second:
        a, b = next(first), next(second)
        assert index.searches.active == 2
        assert set([a, *first]) == set([b, *second]) == {RID(0, n) for n in range(3)}
    assert index.searches.active == 0
