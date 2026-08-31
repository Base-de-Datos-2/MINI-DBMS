"""RID validation, value comparisons, and use as a dictionary key."""

from dataclasses import FrozenInstanceError

import pytest

from engine.storage import RID


@pytest.mark.parametrize(("page_id", "slot_id"), [(0, 0), (4, 2), (2**80, 2**70)])
def test_create_rid(page_id, slot_id):
    rid = RID(page_id=page_id, slot_id=slot_id)
    assert rid.page_id == page_id
    assert rid.slot_id == slot_id


def test_rid_equality_and_hashing():
    rid = RID(4, 2)
    assert rid == RID(4, 2)
    assert rid != RID(4, 3)
    assert rid != RID(5, 2)
    assert rid != (4, 2)
    assert hash(rid) == hash(RID(4, 2))
    assert {rid: "row"}[RID(4, 2)] == "row"
    assert len({rid, RID(4, 2), RID(4, 3)}) == 2


def test_rid_order_is_page_then_slot():
    assert sorted([RID(1, 0), RID(0, 5), RID(0, 1)]) == [
        RID(0, 1), RID(0, 5), RID(1, 0)
    ]
    assert RID(1, 0) <= RID(1, 0)
    assert RID(2, 0) > RID(1, 99)
    with pytest.raises(TypeError):
        RID(0, 0) < (0, 1)


@pytest.mark.parametrize("field", ["page_id", "slot_id"])
@pytest.mark.parametrize("value", [-1, -100])
def test_rid_rejects_negative_components(field, value):
    arguments = {"page_id": 0, "slot_id": 0, field: value}
    with pytest.raises(ValueError, match=f"{field} must be non-negative"):
        RID(**arguments)


@pytest.mark.parametrize("field", ["page_id", "slot_id"])
@pytest.mark.parametrize("value", [True, False, None, "1", 1.0, [], {}])
def test_rid_rejects_non_integer_components(field, value):
    arguments = {"page_id": 0, "slot_id": 0, field: value}
    with pytest.raises(TypeError, match=f"{field} must be an integer"):
        RID(**arguments)


@pytest.mark.parametrize("field", ["page_id", "slot_id"])
def test_rid_is_immutable(field):
    with pytest.raises(FrozenInstanceError):
        setattr(RID(4, 2), field, 7)
