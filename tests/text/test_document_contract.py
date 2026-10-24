"""Verify the 1A.2 contract against the existing codec and persistent Heap.

These four contract samples are not the full 1A.6 ranking/demo fixture.
"""

from collections import Counter

import pytest

from engine.catalog import Column, ColumnConstraint, DataType, Schema, TableMetadata
from engine.errors import InvalidTypeError, ValidationError
from engine.maintenance.validation import validate_record
from engine.storage import HeapFile, Record, RecordCodec
from engine.storage.binary import (
    INTEGER_MAX,
    INTEGER_MIN,
    INTEGER_STRUCT,
    MAX_RECORD_SIZE,
    VARCHAR_LENGTH_STRUCT,
)
from engine.text import tokenize


SCHEMA = Schema([Column("id", DataType.INTEGER), Column("contenido", DataType.VARCHAR)])
MAX_TEXT_BYTES = MAX_RECORD_SIZE - INTEGER_STRUCT.size - VARCHAR_LENGTH_STRUCT.size
TABLE = TableMetadata(
    "documentos", SCHEMA,
    constraints=(
        ColumnConstraint("id", primary_key=True),
        ColumnConstraint("contenido", varchar_length=MAX_TEXT_BYTES),
    ),
)
CONTRACT_ROWS = (
    (30, "¡ÁRBOL, árbol! 2026"),
    (7, "cafe\u0301 y café"),
    (90, ""),
    (12, "... ¿?!"),
)


def test_contract_samples_fit_and_keep_original_text_and_rids_after_reopen(tmp_path):
    path = tmp_path / "documents.heap"
    document_rids = {}
    with HeapFile.create(path, SCHEMA) as heap:
        for identifier, text in CONTRACT_ROWS:
            row = Record(SCHEMA, [identifier, text])
            payload = validate_record(TABLE, row)
            assert len(payload) == INTEGER_STRUCT.size + VARCHAR_LENGTH_STRUCT.size + len(text.encode("utf-8"))
            assert RecordCodec.deserialize(SCHEMA, payload) == row
            document_rids[identifier] = heap.insert(row)

    with HeapFile.open(path, SCHEMA) as heap:
        assert heap.record_count == len(CONTRACT_ROWS)
        assert len(set(document_rids.values())) == len(CONTRACT_ROWS)
        for identifier, original_text in CONTRACT_ROWS:
            assert heap.read(document_rids[identifier]).values == (identifier, original_text)
        assert [(row["id"], row["contenido"]) for _, row in heap.scan()] == list(CONTRACT_ROWS)


def test_contract_statistics_include_documents_without_tokens():
    documents = [Counter(tokenize(text)) for _, text in CONTRACT_ROWS]
    lengths = [sum(frequencies.values()) for frequencies in documents]
    document_frequencies = Counter(term for frequencies in documents for term in frequencies)

    assert lengths == [3, 3, 0, 0]
    assert len(documents) == 4
    assert sum(lengths) / len(documents) == 1.5
    assert documents[0] == {"árbol": 2, "2026": 1}
    assert documents[1] == {"café": 2, "y": 1}
    assert document_frequencies == {"árbol": 1, "2026": 1, "café": 1, "y": 1}


def test_exact_record_byte_boundary_is_accepted_and_next_byte_is_rejected(tmp_path):
    maximum = Record(SCHEMA, [1, "x" * MAX_TEXT_BYTES])
    oversized = Record(SCHEMA, [2, "x" * (MAX_TEXT_BYTES + 1)])
    assert len(validate_record(TABLE, maximum)) == MAX_RECORD_SIZE
    # The codec itself deliberately has no page capacity restriction.
    assert len(RecordCodec.serialize(oversized)) == MAX_RECORD_SIZE + 1
    with HeapFile.create(tmp_path / "boundary.heap", SCHEMA) as heap:
        rid = heap.insert(maximum)
        with pytest.raises(ValidationError, match="page capacity"):
            heap.insert(oversized)
        assert heap.record_count == 1
        assert heap.read(rid) == maximum


def test_character_length_does_not_substitute_for_encoded_row_size(tmp_path):
    oversized = Record(SCHEMA, [1, "é" * (MAX_TEXT_BYTES // 2 + 1)])
    assert len(oversized["contenido"]) <= TABLE.varchar_length("contenido")
    assert len(RecordCodec.serialize(oversized)) > MAX_RECORD_SIZE
    with pytest.raises(ValidationError, match="page capacity"):
        validate_record(TABLE, oversized)
    with HeapFile.create(tmp_path / "multibyte.heap", SCHEMA) as heap:
        with pytest.raises(ValidationError, match="page capacity"):
            heap.insert(oversized)
        assert heap.record_count == 0
        assert heap.data_page_count == 0


@pytest.mark.parametrize("identifier", [INTEGER_MIN, INTEGER_MAX])
def test_document_id_uses_the_existing_signed_64_bit_codec(identifier):
    row = Record(SCHEMA, [identifier, ""])
    assert RecordCodec.deserialize(SCHEMA, validate_record(TABLE, row)) == row


@pytest.mark.parametrize("identifier", [INTEGER_MIN - 1, INTEGER_MAX + 1])
def test_document_id_outside_the_codec_range_is_rejected(identifier):
    with pytest.raises(ValidationError, match="signed 64-bit"):
        validate_record(TABLE, Record(SCHEMA, [identifier, ""]))


@pytest.mark.parametrize("values", [[True, "text"], [1, None], [1, b"text"]])
def test_contract_does_not_coerce_ids_or_text(values):
    with pytest.raises(InvalidTypeError):
        Record(SCHEMA, values)
