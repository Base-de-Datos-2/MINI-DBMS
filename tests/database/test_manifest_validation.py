"""Strict manifest decoding and clean-open failure boundaries."""

import json

import pytest

from engine.database import (
    Database,
    DatabaseManifestError,
    MANIFEST_FILENAME,
    decode_manifest,
)


def test_manifest_rejects_duplicate_keys_unknown_fields_and_versions():
    with pytest.raises(DatabaseManifestError, match="Duplicate manifest field"):
        decode_manifest(
            b'{"magic":"MINIDB_CATALOG","magic":"x","version":1,'
            b'"database":{"id":"00000000000000000000000000000000",'
            b'"name":"db"},"tables":[]}'
        )

    base = {
        "database": {"id": "0" * 32, "name": "db"},
        "magic": "MINIDB_CATALOG",
        "tables": [],
        "version": 1,
    }
    for update, message in (
        ({"extra": True}, "fields"),
        ({"version": 2}, "version"),
    ):
        with pytest.raises(DatabaseManifestError, match=message):
            decode_manifest(json.dumps(base | update).encode())


def test_open_rejects_missing_manifest_instead_of_inferring_legacy_files(tmp_path):
    (tmp_path / "legacy.heap").write_bytes(b"not a managed database")

    with pytest.raises(DatabaseManifestError, match="Missing database manifest"):
        Database.open(tmp_path)


def test_open_rejects_missing_or_incomplete_index_before_exposure(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute(
            "CREATE TABLE items (id INT PRIMARY KEY, value VARCHAR(5))"
        )
        index_path = database.path_for("__pk__items")
    index_path.unlink()

    with pytest.raises(ValueError, match="Missing managed index file"):
        Database.open(tmp_path)


def test_open_rejects_false_ready_marker_and_absolute_or_traversal_files(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE items (id INT PRIMARY KEY)")
    path = tmp_path / MANIFEST_FILENAME
    valid = json.loads(path.read_text("utf-8"))

    incomplete = json.loads(json.dumps(valid))
    incomplete["tables"][0]["indexes"][0]["ready"] = False
    path.write_text(json.dumps(incomplete), encoding="utf-8")
    with pytest.raises(ValueError, match="marked incomplete"):
        Database.open(tmp_path)

    for filename in (str((tmp_path / "outside.heap").resolve()), "../outside.heap"):
        malformed = json.loads(json.dumps(valid))
        malformed["tables"][0]["file"] = filename
        path.write_text(json.dumps(malformed), encoding="utf-8")
        with pytest.raises(DatabaseManifestError, match="relative filename"):
            Database.open(tmp_path)


def test_open_cross_checks_manifest_schema_against_heap_header(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE items (id INT, value VARCHAR(5))")
    path = tmp_path / MANIFEST_FILENAME
    document = json.loads(path.read_text("utf-8"))
    document["tables"][0]["columns"][1]["name"] = "renamed"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="persisted schema"):
        Database.open(tmp_path)


def test_open_cross_checks_manifest_index_identity_against_bplus_header(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE left_table (id INT PRIMARY KEY)")
        database.engine.execute("CREATE TABLE right_table (id INT PRIMARY KEY)")
    path = tmp_path / MANIFEST_FILENAME
    document = json.loads(path.read_text("utf-8"))
    left = document["tables"][0]["indexes"][0]
    right = document["tables"][1]["indexes"][0]
    left["id"], right["id"] = right["id"], left["id"]
    left["file"], right["file"] = right["file"], left["file"]
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match=r"B\+ index metadata mismatch"):
        Database.open(tmp_path)
