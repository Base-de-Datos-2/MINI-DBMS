"""Versioned SPIMI files and immutable metadata; no query/HTTP dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from struct import Struct

from engine.catalog import Column, ColumnConstraint, DataType, Schema, TableMetadata
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.binary import INTEGER_MAX, INTEGER_MIN, MAX_RECORD_SIZE
from engine.storage.record import Record
from engine.storage.record_codec import RecordCodec
from engine.storage.rid import RID


VERSION = 1
HEADER = Struct("<8sI")
POSTING = Struct("<qQ")  # signed document ID, positive term frequency
TERM_LENGTH = Struct("<I")
COUNT = Struct("<Q")
POSTINGS_MAGIC = b"MDBTXT01"
RUN_MAGIC = b"MDBRUN01"
COMPONENTS = ("postings.bin", "lexicon.jsonl", "documents.jsonl")
MAX_TERM_BYTES = MAX_RECORD_SIZE * 4  # Unicode lower/NFC expansion headroom


def integer(value, name: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int:
        raise InvalidTypeError(f"{name} must be a built-in integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValidationError(f"{name} is outside its supported range")
    return value


def name(value, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValidationError(f"{label} must be a nonempty string")
    return value


def finite(value, label: str) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValidationError(f"{label} must be finite and nonnegative")
    return float(value)


def digest(value) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValidationError("Invalid SHA-256 digest")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValidationError(f"Non-finite JSON constant: {value}")


def decode_json(payload: str):
    try:
        return json.loads(payload, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeError) as error:
        raise ValidationError("Invalid text-index JSON") from error


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def read_json(path: Path):
    try:
        return decode_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise ValidationError(f"Cannot read text-index component {path.name}") from error


def json_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                value = decode_json(line)
                if type(value) is not dict:
                    raise ValidationError(f"Invalid row in {path.name}")
                yield value
    except (OSError, UnicodeError) as error:
        raise ValidationError(f"Cannot read text-index component {path.name}") from error


def file_receipt(path: Path) -> dict:
    hasher = sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": hasher.hexdigest()}


def table_document(table: TableMetadata) -> dict:
    return {
        "name": table.name,
        "schema": [[column.name, column.data_type.value] for column in table.schema],
        "constraints": [[c.column_name, c.varchar_length, c.primary_key] for c in table.constraints],
    }


def restore_table(value) -> TableMetadata:
    try:
        if type(value) is not dict or set(value) != {"name", "schema", "constraints"}:
            raise ValidationError("Invalid text-index table metadata")
        return TableMetadata(
            value["name"], Schema([Column(n, DataType(t)) for n, t in value["schema"]]),
            tuple(ColumnConstraint(n, length, primary) for n, length, primary in value["constraints"]),
        )
    except (TypeError, ValueError, KeyError) as error:
        raise ValidationError("Invalid text-index schema or constraints") from error


def validate_columns(table: TableMetadata, id_column: str, text_column: str) -> None:
    if not isinstance(table, TableMetadata):
        raise InvalidTypeError("SPIMI requires TableMetadata")
    if table.schema.column(id_column).data_type is not DataType.INTEGER:
        raise ValidationError("Text document IDs must use INTEGER")
    if table.schema.column(text_column).data_type is not DataType.VARCHAR:
        raise ValidationError("Indexed text must use VARCHAR")


def checked_payload(table: TableMetadata, record: Record) -> bytes:
    """Check a borrowed stored row, including declared and physical limits."""
    if not isinstance(record, Record) or record.schema != table.schema:
        raise ValidationError("Text source schema differs from table metadata")
    for constraint in table.constraints:
        if constraint.varchar_length is not None and len(record[constraint.column_name]) > constraint.varchar_length:
            raise ValidationError("Text source exceeds a declared VARCHAR length")
    payload = RecordCodec.serialize(record)
    if len(payload) > MAX_RECORD_SIZE:
        raise ValidationError("Text source row exceeds page capacity")
    return payload


@dataclass(frozen=True, slots=True)
class DocumentEntry:
    doc_id: int
    rid: RID
    length: int
    norm: float
    record_sha256: str

    def __post_init__(self):
        integer(self.doc_id, "doc_id", INTEGER_MIN, INTEGER_MAX)
        if not isinstance(self.rid, RID) or self.rid.page_id < 1:
            raise ValidationError("A text RID must reference a Heap data page")
        integer(self.length, "document length", maximum=MAX_TERM_BYTES)
        finite(self.norm, "document norm")
        digest(self.record_sha256)
        if (self.length == 0) != (self.norm == 0):
            raise ValidationError("Only tokenless documents have a zero norm")


@dataclass(frozen=True, slots=True)
class TermEntry:
    dimension: int
    offset: int
    df: int
    byte_length: int


@dataclass(frozen=True, slots=True)
class CollectionStatistics:
    document_count: int
    total_tokens: int
    average_length: float
    vocabulary_size: int


__all__ = ["DocumentEntry", "TermEntry", "CollectionStatistics"]
