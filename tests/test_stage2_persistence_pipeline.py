"""Full Record/codec/Page/file pipeline, including separate interpreter lifetimes."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from engine.catalog import Catalog, Column, DataType, Schema
from engine.errors import InvalidTypeError, ValidationError
from engine.storage import PageManager, Record, RecordCodec


WORKER = Path(__file__).resolve().parent / "helpers" / "stage2_restart.py"
EXTERNAL_SCHEMA = [("id", "INTEGER"), ("score", "FLOAT"), ("active", "BOOLEAN"), ("name", "VARCHAR")]


def run_phase(phase, path, compact, cwd):
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-W", "error", "-X", "utf8", str(WORKER),
         phase, str(path), json.dumps(EXTERNAL_SCHEMA), "yes" if compact else "no"],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    return json.loads(result.stdout)


@pytest.mark.parametrize("compact", [False, True], ids=["fragmented", "compacted"])
def test_pipeline_survives_independent_writer_reader_and_rewriter_processes(compact, tmp_path):
    path = tmp_path / "persistencia 😀.db"
    # Each completed subprocess exits before the next starts. Only the path and
    # external schema declaration are supplied; no Records/Pages/bytes are IPC input.
    for phase, count, reads, writes, allocations in (
        ("write", 4, 4, 8, 4), ("read", 4, 4, 0, 0),
        ("rewrite", 5, 7, 4, 1), ("final", 5, 5, 0, 0),
    ):
        before = path.read_bytes() if phase in {"read", "final"} else None
        assert run_phase(phase, path, compact, tmp_path) == {
            "phase": phase, "page_count": count, "pages_read": reads,
            "pages_written": writes, "pages_allocated": allocations,
        }
        if before is not None:
            assert path.read_bytes() == before


@pytest.mark.parametrize("data_type,payload", [
    (DataType.INTEGER, bytes(7)), (DataType.FLOAT, bytes(7)),
    (DataType.BOOLEAN, b"\x02"),
    (DataType.VARCHAR, b"\x01\x00\x00\x00\xff"),
    (DataType.VARCHAR, b"\xff\xff\xff\xff"),
    (DataType.VARCHAR, b"\x02\x00\x00\x00a"),
    (DataType.INTEGER, bytes(8) + b"extra"), (None, b"extra"),
])
def test_malformed_record_from_valid_disk_page_is_rejected_by_codec_not_page(data_type, payload, tmp_path):
    path = tmp_path / "malformed-row.db"
    with PageManager.create(path) as manager:
        page = manager.read_page(manager.allocate_page())
        page.insert(payload)  # Opaque bytes are legal at Page's layer.
        manager.write_page(page)
    del manager, page
    with PageManager.open(path) as manager:
        schema = Schema([] if data_type is None else [Column("value", data_type)])
        stored = manager.read_page(0).read(0)
        assert stored == payload
        with pytest.raises(ValidationError):
            RecordCodec.deserialize(schema, stored)
        assert manager.pages_read == 1
        assert manager.pages_written == 0


def test_schema_is_external_and_compatible_but_wrong_schema_cannot_be_detected(tmp_path):
    path = tmp_path / "external-schema.db"
    with PageManager.create(path) as manager:
        schema = Schema([Column("original_name", DataType.INTEGER)])
        page = manager.read_page(manager.allocate_page())
        page.insert(RecordCodec.serialize(Record(schema, [42])))
        manager.write_page(page)
    del manager, schema, page
    with PageManager.open(path) as manager:
        assert Catalog().list_tables() == ()
        payload = manager.read_page(0).read(0)
        with pytest.raises(InvalidTypeError):
            RecordCodec.deserialize(None, payload)
        supplied = Schema([Column("caller_supplied_name", DataType.INTEGER)])
        recovered = RecordCodec.deserialize(supplied, payload)
        assert recovered["caller_supplied_name"] == 42
        assert recovered.schema is supplied  # Names/types are not stored with rows.
