"""Phase-1 media fixtures and the imagenes/canciones metadata contract."""

import hashlib
import json
from pathlib import Path
import struct
import wave
import zlib

import pytest

from engine.errors import ValidationError
from engine.catalog import Column, ColumnConstraint, DataType, Schema, TableMetadata
from engine.maintenance.validation import validate_record
from engine.multimedia import Modality, media_key_modality
from engine.multimedia.contracts import MAX_MEDIA_KEY_LENGTH, MAX_METADATA_TEXT_LENGTH
from engine.storage import HeapFile, Record
from engine.storage.binary import (
    INTEGER_STRUCT, MAX_RECORD_SIZE, VARCHAR_LENGTH_STRUCT,
)
from tests.multimedia import make_fixtures

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MANIFEST = json.loads((FIXTURES / "manifest.v1.json").read_text(encoding="utf-8"))
ENTRIES = {entry["name"]: entry for entry in MANIFEST["files"]}


def table(name, text_columns):
    columns = [Column("id", DataType.INTEGER)] + [Column(c, DataType.VARCHAR) for c in text_columns]
    limits = {"media_key": MAX_MEDIA_KEY_LENGTH}
    return TableMetadata(name, Schema(columns), constraints=(
        ColumnConstraint("id", primary_key=True),
        *(ColumnConstraint(c, varchar_length=limits.get(c, MAX_METADATA_TEXT_LENGTH))
          for c in text_columns)))


IMAGENES = table("imagenes", ["nombre", "media_key"])
CANCIONES = table("canciones", ["nombre", "artista", "media_key"])


def decode_png(data):
    """Decode the generator's RGB8, filter-0 PNG files."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, depth, color = struct.unpack(">IIBB", data[16:26])
    assert (depth, color) == (8, 2)
    idat, offset = b"", 8
    while offset < len(data):
        (length,), kind = struct.unpack(">I", data[offset:offset + 4]), data[offset + 4:offset + 8]
        if kind == b"IDAT":
            idat += data[offset + 8:offset + 8 + length]
        offset += 12 + length
    raw = zlib.decompress(idat)
    stride = 1 + 3 * width
    rows = [raw[y * stride:(y + 1) * stride] for y in range(height)]
    assert all(row[0] == 0 for row in rows)
    return [[tuple(row[1 + 3 * x:4 + 3 * x]) for x in range(width)] for row in rows]


def wav_samples(name):
    with wave.open(str(FIXTURES / name), "rb") as reader:
        params = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate())
        frames = reader.readframes(reader.getnframes())
    return params, struct.unpack(f"<{len(frames) // 2}h", frames)


def test_manifest_lists_exactly_the_committed_files_with_matching_hashes():
    on_disk = {p.name for p in FIXTURES.iterdir()} - {"manifest.v1.json", "README.md"}
    assert on_disk == set(ENTRIES)
    assert MANIFEST["version"] == 1 and MANIFEST["synthetic"] is True
    for name, entry in ENTRIES.items():
        data = (FIXTURES / name).read_bytes()
        assert len(data) == entry["bytes"], name
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], name


def test_every_fixture_name_is_a_valid_media_key_of_its_modality():
    for name, entry in ENTRIES.items():
        assert media_key_modality(name, Modality(entry["modality"])) is Modality(entry["modality"])


def test_roles_cover_gallery_queries_and_explicit_rejections():
    for modality in Modality:
        roles = [e for e in ENTRIES.values() if e["modality"] == modality.value]
        assert sum(e["role"] == "gallery" for e in roles) >= 6
        assert [e["name"] for e in roles if e["role"] == "query"]
        assert {e.get("expected_rejection") for e in roles if e["role"] == "invalid"} >= {"undecodable"}
    assert ENTRIES["blank.png"]["expected_rejection"] == "no_descriptors"
    assert ENTRIES["silencio.wav"]["expected_rejection"] == "no_signal"
    # The literal file names of both PDF examples exist as registered queries.
    assert ENTRIES["foto_consulta.jpg"]["role"] == ENTRIES["audio_query.mp3"]["role"] == "query"
    for entry in ENTRIES.values():
        if "near_duplicate_of" in entry:
            assert ENTRIES[entry["near_duplicate_of"]]["role"] == "gallery"


def test_png_fixtures_decode_and_come_from_the_documented_generator():
    expected = {
        "scene_a.png": make_fixtures.scene(1),
        "scene_a_shifted.png": make_fixtures.scene(1, shift=(9, 6)),
        "scene_b_mirror.png": make_fixtures.mirror(make_fixtures.scene(2)),
        "scene_f.png": make_fixtures.scene(6),
        "blank.png": make_fixtures.uniform(128),
    }
    for name, pixels in expected.items():
        decoded = decode_png((FIXTURES / name).read_bytes())
        assert [list(row) for row in decoded] == [list(row) for row in pixels], name
    assert len({p for row in decode_png((FIXTURES / "blank.png").read_bytes()) for p in row}) == 1
    assert len({p for row in decode_png((FIXTURES / "scene_c.png").read_bytes()) for p in row}) > 10


def test_query_and_invalid_files_have_the_declared_container_formats():
    jpeg = (FIXTURES / "foto_consulta.jpg").read_bytes()
    assert jpeg[:2] == b"\xff\xd8" and jpeg[-2:] == b"\xff\xd9"
    mp3 = (FIXTURES / "audio_query.mp3").read_bytes()
    assert mp3[:3] == b"ID3" or (mp3[0] == 0xFF and mp3[1] & 0xE0 == 0xE0)
    for name in ("corrupt.jpg", "corrupt.mp3"):
        data = (FIXTURES / name).read_bytes()
        assert not data.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF", b"ID3", b"\xff\xfb"))


def test_wav_fixtures_are_mono_16_bit_22050_hz_and_match_the_generator():
    for name, entry in ENTRIES.items():
        if entry["format"] == "wav":
            params, samples = wav_samples(name)
            assert params == (1, 2, 22_050) and len(samples) == entry["frames"]
            peak = max(abs(s) for s in samples)
            assert (peak == 0) == (name == "silencio.wav"), name
    # Regenerated samples agree within one quantization step (libm-independent).
    _, committed = wav_samples("acorde_grave.wav")
    regenerated = make_fixtures.tones((220.0, 277.18, 329.63))
    assert max(abs(c - round(s * 32767)) for c, s in zip(committed, regenerated)) <= 1


def test_worst_case_metadata_rows_fit_one_record():
    # Names may use 4-byte UTF-8 characters; media keys are ASCII by contract.
    name = "\U0001F3B5" * MAX_METADATA_TEXT_LENGTH
    key = "x" * (MAX_MEDIA_KEY_LENGTH - 4) + ".jpg"
    for metadata, texts in ((IMAGENES, [name, key]), (CANCIONES, [name, name, key])):
        row = Record(metadata.schema, [1] + texts)
        payload = validate_record(metadata, row)
        assert len(payload) == (INTEGER_STRUCT.size + len(texts) * VARCHAR_LENGTH_STRUCT.size
                                + sum(len(v.encode("utf-8")) for v in texts))
        assert len(payload) < MAX_RECORD_SIZE
    assert len(payload) == 1_748   # canciones worst case quoted in the contract


def test_over_long_names_are_rejected_not_truncated():
    row = Record(CANCIONES.schema, [1, "x" * (MAX_METADATA_TEXT_LENGTH + 1), "a", "c.wav"])
    with pytest.raises(ValidationError, match="VARCHAR|length|characters"):
        validate_record(CANCIONES, row)


def test_fixture_metadata_persists_in_heap_with_unique_rids_after_reopen(tmp_path):
    images = [e for e in ENTRIES.values() if e["modality"] == "image" and e["role"] == "gallery"]
    clips = [e for e in ENTRIES.values() if e["modality"] == "audio" and e["role"] == "gallery"]
    plans = (
        (IMAGENES, [[i, e["metadata"]["nombre"], e["name"]] for i, e in enumerate(images, 1)]),
        (CANCIONES, [[i, e["metadata"]["nombre"], e["metadata"]["artista"], e["name"]]
                     for i, e in enumerate(clips, 101)]),
    )
    for metadata, rows in plans:
        path = tmp_path / f"{metadata.name}.heap"
        rids = {}
        with HeapFile.create(path, metadata.schema) as heap:
            for values in rows:
                record = Record(metadata.schema, values)
                validate_record(metadata, record)
                rids[values[0]] = heap.insert(record)
        assert len(set(rids.values())) == len(rows)
        with HeapFile.open(path, metadata.schema) as heap:
            for values in rows:
                assert list(heap.read(rids[values[0]]).values) == values
