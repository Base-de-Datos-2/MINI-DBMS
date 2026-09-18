"""Stage 9 Task 9.7: lossless value encoding and bounded plan trees."""

import json
import math

import pytest

from engine.catalog import Column, DataType, Schema
from engine.operators import OperatorDescriptor
from engine.query import SqlSyntaxError, parse_sql
from engine.storage import Record
from api import serialization
from api.schemas import JS_SAFE_INTEGER
from api.serialization import (
    column_descriptors,
    encode_row,
    encode_value,
    encoded_size,
    sql_location,
)


def test_integers_beyond_javascript_precision_travel_as_exact_strings():
    assert encode_value(DataType.INTEGER, JS_SAFE_INTEGER) == JS_SAFE_INTEGER
    assert encode_value(DataType.INTEGER, JS_SAFE_INTEGER + 1) == "9007199254740992"
    assert encode_value(DataType.INTEGER, -(2**63)) == str(-(2**63))
    assert encode_value(DataType.INTEGER, -5) == -5


def test_non_finite_floats_travel_as_their_conventional_spelling():
    assert encode_value(DataType.FLOAT, math.inf) == "Infinity"
    assert encode_value(DataType.FLOAT, -math.inf) == "-Infinity"
    assert encode_value(DataType.FLOAT, math.nan) == "NaN"
    assert encode_value(DataType.FLOAT, 0.1) == 0.1


def test_booleans_and_strings_are_their_own_json_values():
    assert encode_value(DataType.BOOLEAN, False) is False
    assert encode_value(DataType.VARCHAR, "") == ""
    assert encode_value(DataType.VARCHAR, "Lucía 漢字") == "Lucía 漢字"


def test_columns_declare_position_type_and_encoding_in_order():
    schema = Schema([
        Column("b", DataType.FLOAT), Column("a", DataType.INTEGER),
        Column("c", DataType.BOOLEAN), Column("d", DataType.VARCHAR),
    ])

    assert column_descriptors(schema) == [
        {"position": 0, "name": "b", "type": "FLOAT", "encoding": "float64"},
        {"position": 1, "name": "a", "type": "INTEGER", "encoding": "int64"},
        {"position": 2, "name": "c", "type": "BOOLEAN", "encoding": "boolean"},
        {"position": 3, "name": "d", "type": "VARCHAR", "encoding": "string"},
    ]


def test_an_encoded_row_is_always_strict_json():
    schema = Schema([Column("x", DataType.FLOAT), Column("n", DataType.INTEGER)])
    row = encode_row(Record(schema, [math.inf, 2**62]))

    assert row == ["Infinity", str(2**62)]
    assert json.loads(json.dumps(row, allow_nan=False)) == row
    assert encoded_size(row) == len(json.dumps(row, separators=(",", ":")).encode())


def test_encoded_size_counts_utf8_bytes_not_characters():
    assert encoded_size("ñ") == len('"ñ"'.encode("utf-8")) == 4


def _chain(length):
    node = OperatorDescriptor(name="TableScan", operator_id="leaf")
    for position in range(length - 1):
        node = OperatorDescriptor(
            name="Filter", operator_id=str(position), children=(node,)
        )
    return node


def test_plan_trees_are_bounded_and_say_when_they_were_cut(monkeypatch):
    monkeypatch.setattr(serialization, "MAX_PLAN_DEPTH", 3)
    tree = serialization._operator_node(_chain(6), 1, serialization._PlanBudget())

    depth = 0
    node = tree
    while node is not None:
        depth += 1
        node = node["children"][0] if node["children"] else None
    assert depth == 3

    budget = serialization._PlanBudget()
    serialization._operator_node(_chain(6), 1, budget)
    assert budget.truncated is True


def test_sql_errors_keep_their_source_location():
    with pytest.raises(SqlSyntaxError) as caught:
        parse_sql("SELECT id\nFROM")

    location = sql_location(caught.value)

    assert location["line"] == 2
    assert isinstance(location["column"], int)
    assert sql_location(ValueError("x")) is None
