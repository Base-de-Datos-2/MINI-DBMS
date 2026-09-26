"""Parse CSV uploads and check GUI table definitions before any file exists.

This module only reads text and validates names and values. It never touches
storage, indexes or the Catalog: the rows it produces are handed to the demo
owner, which inserts them through the engine's own storage classes.

* Parsing uses the standard-library ``csv`` module. The first row is the header.
* Type inference is deliberately small and predictable: a column is INTEGER if
  every value is a signed 64-bit integer, FLOAT if every value is a finite
  decimal number, BOOLEAN if every value is ``true``/``false``, and VARCHAR
  otherwise. The engine has no NULL, so an empty cell only fits VARCHAR.
* Names must be plain SQL identifiers according to the handwritten lexer, so a
  table created from the GUI can always be queried with SQL afterwards.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import math
from pathlib import PurePath
import re

from engine.catalog import DataType
from engine.errors import ValidationError
from engine.query.lexer import tokenize
from engine.query.tokens import TokenType
from engine.storage.binary import INTEGER_MAX, INTEGER_MIN


#: Largest CSV text accepted, in UTF-8 bytes.
MAX_CSV_BYTES = 8 * 1024 * 1024

#: Largest number of data rows one import may load. Loading costs a few
#: milliseconds per row and per index, and the engine stays admitted meanwhile.
MAX_IMPORT_ROWS = 10_000

MAX_COLUMNS = 32
MAX_INDEXES = 8
MAX_IDENTIFIER_CHARS = 48

#: Rows returned by a preview; the preview never loads anything.
PREVIEW_ROWS = 5

DELIMITERS = {",": "coma", ";": "punto y coma", "\t": "tabulador", "|": "barra"}

_INTEGER_RE = re.compile(r"[+-]?[0-9]+\Z")
_DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_BOOLEANS = {"true": True, "false": False}


class DefinitionError(ValidationError):
    """A table definition from the GUI is invalid; nothing was created."""


class CsvError(ValidationError):
    """A CSV upload cannot be parsed or converted; nothing was created."""

    def __init__(self, message: str, *, line: int | None = None,
                 column: str | None = None) -> None:
        super().__init__(message)
        self.line = line
        self.column = column


# ---------------------------------------------------------------- identifiers


def check_identifier(name: object, what: str) -> str:
    """Return ``name`` if the SQL lexer reads it as one plain identifier."""

    if type(name) is not str or not name:
        raise DefinitionError(f"El nombre de {what} no puede estar vacío.")
    if len(name) > MAX_IDENTIFIER_CHARS:
        raise DefinitionError(
            f"El nombre de {what} {name!r} supera {MAX_IDENTIFIER_CHARS} caracteres."
        )
    try:
        tokens = tokenize(name)
    except ValidationError:
        tokens = []
    if (
        len(tokens) != 2
        or tokens[0].type is not TokenType.IDENTIFIER
        or tokens[0].lexeme != name
    ):
        raise DefinitionError(
            f"{name!r} no sirve como nombre de {what}: usa letras, dígitos y _, "
            "empieza con una letra y evita palabras reservadas de SQL."
        )
    return name


def suggest_identifier(raw: str, used: set[str], fallback: str) -> str:
    """Turn a CSV header or file name into a free, valid identifier."""

    text = "".join(char if char.isalnum() or char == "_" else "_" for char in raw.strip())
    text = re.sub(r"_+", "_", text).strip("_").lower()[:MAX_IDENTIFIER_CHARS] or fallback
    if not (text[0].isalpha() or text[0] == "_"):
        text = f"{fallback}_{text}"[:MAX_IDENTIFIER_CHARS]
    candidate = text
    suffix = 2
    while True:
        try:
            check_identifier(candidate, "columna")
            valid = True
        except DefinitionError:
            valid = False
        if valid and candidate not in used:
            used.add(candidate)
            return candidate
        # Reserved words and repeats get a numeric suffix until one is free.
        candidate = f"{text[:MAX_IDENTIFIER_CHARS - 4]}_{suffix}"
        suffix += 1


def suggest_table_name(filename: str | None, taken: set[str]) -> str:
    stem = PurePath(filename).stem if filename else ""
    return suggest_identifier(stem, set(taken), "tabla")


# ---------------------------------------------------------------- parsing


@dataclass(frozen=True, slots=True)
class ParsedCsv:
    delimiter: str
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    lines: tuple[int, ...]  # physical line where each data row ends


def detect_delimiter(text: str) -> str:
    """Pick the candidate delimiter that splits the header line most often."""

    header = text.lstrip("﻿").split("\n", 1)[0]
    counts = {delimiter: header.count(delimiter) for delimiter in DELIMITERS}
    best = max(counts, key=lambda delimiter: counts[delimiter])
    return best if counts[best] > 0 else ","


def parse_csv(text: str, delimiter: str | None = None) -> ParsedCsv:
    """Parse a whole CSV upload, header first, rejecting ragged rows."""

    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise CsvError(f"El CSV excede el límite de {MAX_CSV_BYTES // (1024 * 1024)} MiB.")
    text = text.lstrip("﻿")
    if delimiter is None:
        delimiter = detect_delimiter(text)
    if delimiter not in DELIMITERS:
        raise CsvError("Separador no soportado; usa coma, punto y coma, tabulador o barra.")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    header: list[str] | None = None
    rows: list[tuple[str, ...]] = []
    lines: list[int] = []
    try:
        for record in reader:
            if not record:
                continue  # a blank line
            if header is None:
                header = [name.strip() for name in record]
                if len(header) > MAX_COLUMNS:
                    raise CsvError(f"El CSV tiene más de {MAX_COLUMNS} columnas.", line=1)
                continue
            if len(record) != len(header):
                raise CsvError(
                    f"La fila tiene {len(record)} valores y la cabecera {len(header)} columnas.",
                    line=reader.line_num,
                )
            if len(rows) == MAX_IMPORT_ROWS:
                limit = f"{MAX_IMPORT_ROWS:,}".replace(",", " ")
                raise CsvError(
                    f"El CSV tiene más de {limit} filas de datos, el límite de "
                    "importación desde la interfaz.",
                    line=reader.line_num,
                )
            rows.append(tuple(record))
            lines.append(reader.line_num)
    except csv.Error as error:
        raise CsvError(f"CSV mal formado: {error}", line=reader.line_num) from None
    if header is None:
        raise CsvError("El CSV está vacío: se necesita al menos la fila de cabecera.")
    if any(not name for name in header):
        raise CsvError("La cabecera tiene una columna sin nombre.", line=1)
    return ParsedCsv(delimiter, tuple(header), tuple(rows), tuple(lines))


# ---------------------------------------------------------------- values


def _integer(text: str) -> int | None:
    stripped = text.strip()
    if _INTEGER_RE.fullmatch(stripped) is None:
        return None
    value = int(stripped)
    return value if INTEGER_MIN <= value <= INTEGER_MAX else None


def _float(text: str) -> float | None:
    stripped = text.strip()
    if _DECIMAL_RE.fullmatch(stripped) is None:
        return None
    value = float(stripped)
    return value if math.isfinite(value) else None


def _boolean(text: str) -> bool | None:
    return _BOOLEANS.get(text.strip().lower())


def infer_type(values) -> DataType:
    """Infer the narrowest engine type that accepts every value."""

    values = list(values)
    if not values:
        return DataType.VARCHAR
    if all(_integer(value) is not None for value in values):
        return DataType.INTEGER
    if all(_float(value) is not None for value in values):
        return DataType.FLOAT
    if all(_boolean(value) is not None for value in values):
        return DataType.BOOLEAN
    return DataType.VARCHAR


_TYPE_LABELS = {
    DataType.INTEGER: "un entero de 64 bits",
    DataType.FLOAT: "un número decimal finito",
    DataType.BOOLEAN: "true o false",
}


def convert_value(text: str, data_type: DataType, *, line: int, column: str):
    """Convert one CSV cell to its declared type or explain why it cannot."""

    if data_type is DataType.VARCHAR:
        return text
    parser = {
        DataType.INTEGER: _integer,
        DataType.FLOAT: _float,
        DataType.BOOLEAN: _boolean,
    }[data_type]
    value = parser(text)
    if value is None:
        shown = "vacío (el motor no tiene NULL)" if text.strip() == "" else repr(text)
        raise CsvError(
            f"El valor {shown} no es {_TYPE_LABELS[data_type]}.",
            line=line,
            column=column,
        )
    return value


def convert_rows(parsed: ParsedCsv, columns: tuple[tuple[str, DataType], ...]):
    """Convert every parsed row to engine values under the declared columns."""

    if len(columns) != len(parsed.header):
        raise DefinitionError(
            f"La definición tiene {len(columns)} columnas y el CSV {len(parsed.header)}."
        )
    converted = []
    for row, line in zip(parsed.rows, parsed.lines):
        converted.append(
            tuple(
                convert_value(cell, data_type, line=line, column=name)
                for cell, (name, data_type) in zip(row, columns)
            )
        )
    return converted


def preview(text: str, *, filename: str | None, delimiter: str | None,
            taken_names: set[str]) -> dict:
    """Describe an upload without loading it: header, inferred types, samples."""

    parsed = parse_csv(text, delimiter)
    used: set[str] = set()
    columns = []
    for position, raw in enumerate(parsed.header):
        values = (row[position] for row in parsed.rows)
        columns.append(
            {
                "source": raw,
                "name": suggest_identifier(raw, used, f"col{position + 1}"),
                "type": infer_type(values).value,
            }
        )
    return {
        "delimiter": parsed.delimiter,
        "columns": columns,
        "sample_rows": [list(row) for row in parsed.rows[:PREVIEW_ROWS]],
        "row_count": len(parsed.rows),
        "suggested_table_name": suggest_table_name(filename, taken_names),
    }
