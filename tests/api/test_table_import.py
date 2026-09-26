"""CSV parsing, type inference and identifier checks for GUI table creation."""

import pytest

from api.table_import import (
    MAX_IMPORT_ROWS,
    CsvError,
    DefinitionError,
    check_identifier,
    convert_rows,
    detect_delimiter,
    infer_type,
    parse_csv,
    preview,
    suggest_identifier,
)
from engine.catalog import DataType


def test_parse_keeps_header_rows_and_physical_lines():
    parsed = parse_csv("id,name\r\n1,Ana\r\n\r\n2,\"Sol, M.\"\r\n")

    assert parsed.delimiter == ","
    assert parsed.header == ("id", "name")
    assert parsed.rows == (("1", "Ana"), ("2", "Sol, M."))
    assert parsed.lines == (2, 4)


def test_delimiter_is_detected_from_the_header_and_bom_is_ignored():
    assert detect_delimiter("a;b;c\n1;2;3") == ";"
    assert detect_delimiter("a\tb\n1\t2") == "\t"
    assert detect_delimiter("solo\n1") == ","
    assert parse_csv("﻿id;nota\n1;20").header == ("id", "nota")


def test_ragged_rows_and_empty_uploads_are_rejected_with_their_line():
    with pytest.raises(CsvError) as ragged:
        parse_csv("a,b\n1,2\n3\n")
    with pytest.raises(CsvError):
        parse_csv("\n\n")
    with pytest.raises(CsvError):
        parse_csv("a,,c\n1,2,3")

    assert ragged.value.line == 3


def test_too_many_rows_are_refused_before_anything_is_loaded():
    text = "x\n" + "1\n" * (MAX_IMPORT_ROWS + 1)

    with pytest.raises(CsvError, match="límite"):
        parse_csv(text)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1", "-2", " 3 "], DataType.INTEGER),
        (["1", "2.5", "-.5", "1e3"], DataType.FLOAT),
        (["true", "FALSE", " True "], DataType.BOOLEAN),
        (["1", "", "3"], DataType.VARCHAR),
        (["1", "nan"], DataType.VARCHAR),
        (["9223372036854775808"], DataType.FLOAT),
        (["1_000"], DataType.VARCHAR),
        ([], DataType.VARCHAR),
    ],
)
def test_inference_picks_the_narrowest_type_that_fits_every_value(values, expected):
    assert infer_type(values) is expected


def test_conversion_reports_the_line_and_column_of_a_bad_value():
    parsed = parse_csv("id,nota\n1,20\n2,veinte\n")

    with pytest.raises(CsvError) as error:
        convert_rows(parsed, (("id", DataType.INTEGER), ("nota", DataType.INTEGER)))

    assert (error.value.line, error.value.column) == (3, "nota")
    assert "veinte" in str(error.value)


def test_conversion_keeps_varchar_verbatim_and_rejects_empty_numbers():
    parsed = parse_csv("n,t\n 7 , hola \n")
    rows = convert_rows(parsed, (("n", DataType.INTEGER), ("t", DataType.VARCHAR)))

    assert rows == [(7, " hola ")]
    with pytest.raises(CsvError, match="NULL"):
        convert_rows(parse_csv("n\n\"\"\n"), (("n", DataType.INTEGER),))


def test_identifiers_follow_the_sql_lexer():
    assert check_identifier("nota_final", "columna") == "nota_final"
    assert check_identifier("año", "columna") == "año"
    for invalid in ("select", "1a", "a b", "", "x-y"):
        with pytest.raises(DefinitionError):
            check_identifier(invalid, "columna")


def test_suggestions_are_valid_distinct_identifiers():
    used: set[str] = set()
    suggested = [
        suggest_identifier(raw, used, f"col{position}")
        for position, raw in enumerate(["Nota Final", "nota final", "SELECT", "2do", "%%"])
    ]

    assert suggested == ["nota_final", "nota_final_2", "select_2", "col3_2do", "col4"]
    for name in suggested:
        check_identifier(name, "columna")


def test_preview_describes_without_loading():
    body = preview(
        "Id;Nombre;Nota\n1;Ana;20\n2;Luis;18\n",
        filename="Alumnos BD2.csv",
        delimiter=None,
        taken_names={"students"},
    )

    assert body["delimiter"] == ";"
    assert body["columns"] == [
        {"source": "Id", "name": "id", "type": "INTEGER"},
        {"source": "Nombre", "name": "nombre", "type": "VARCHAR"},
        {"source": "Nota", "name": "nota", "type": "INTEGER"},
    ]
    assert body["row_count"] == 2
    assert body["sample_rows"] == [["1", "Ana", "20"], ["2", "Luis", "18"]]
    assert body["suggested_table_name"] == "alumnos_bd2"


def test_preview_never_suggests_an_existing_table_name():
    body = preview("a\n1\n", filename="students.csv", delimiter=None,
                   taken_names={"students"})

    assert body["suggested_table_name"] == "students_2"
