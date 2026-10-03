"""E1: reproducibility, coordinate conventions and real owner reopen."""

from contextlib import closing
import csv
import json

import pytest

from api.database import Database, DatabaseDefinition, DatabaseSetupError, NewTable
from benchmarks.spatial.datasets import (
    FIXTURE_ROWS, LATITUDE_BOUNDS, LONGITUDE_BOUNDS, export, point_rows, query_centers,
)
from benchmarks.spatial.postgres import setup_sql
from engine.catalog import DataType
from engine.errors import ValidationError
from engine.spatial.metadata import (
    REGISTRY_FILENAME, SpatialMapping, read_mappings, validate_coordinates, write_mappings,
)
from scripts.setup_spatial import SPATIAL_DATABASE, prepare


def test_required_sizes_share_a_reproducible_prefix_and_independent_queries():
    small = list(point_rows(1000))
    large = list(point_rows(100000))
    assert large[:1000] == small
    assert len(large) == 100000
    assert [row[0] for row in large] == list(range(1, 100001))
    assert all(LATITUDE_BOUNDS[0] <= row[2] <= LATITUDE_BOUNDS[1]
               and LONGITUDE_BOUNDS[0] <= row[3] <= LONGITUDE_BOUNDS[1] for row in large)
    assert len(query_centers()) == 100
    assert query_centers() == query_centers()
    assert query_centers(7) != query_centers()


def test_exports_are_identical_and_refuse_to_replace_existing_inputs(tmp_path):
    first = export(tmp_path / "first", (1000, 10000))
    second = export(tmp_path / "second", (1000, 10000))
    assert first == second
    for filename in first["sha256"]:
        assert (tmp_path / "first" / filename).read_bytes() == (tmp_path / "second" / filename).read_bytes()
    with (tmp_path / "first/queries.csv").open(encoding="utf-8", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 100
    with pytest.raises(FileExistsError):
        export(tmp_path / "first")


@pytest.mark.parametrize("coordinates", [
    (-77.0428, -12.0464), (float("nan"), -77.0), (-12.0, float("inf")),
    (-13.0, -77.0), (-12, -77.0), (True, -77.0),
])
def test_invalid_coordinates_are_refused(coordinates):
    with pytest.raises(ValidationError):
        validate_coordinates(*coordinates)


def test_fixture_is_discovered_after_fresh_owner_reopen_and_preserves_duplicates(tmp_path):
    directory = tmp_path / "spatial"
    prepare(directory)
    with Database.open(SPATIAL_DATABASE, directory) as database:
        assert database.table_names() == ("tiendas", "restaurantes")
        mapping = database.spatial_mapping_for("tiendas")
        assert mapping == SpatialMapping("tiendas")
        with database.engine.execute("SELECT * FROM tiendas ORDER BY id") as result:
            assert [row.values for row in result] == list(FIXTURE_ROWS)
        with database.engine.execute("SELECT id FROM tiendas WHERE latitud < -12.2") as result:
            assert [row.values for row in result] == [(9,)]
        storage = database.session_coordinator.environment.storage_for("tiendas")
        with closing(storage.scan()) as rows:
            associations = list(rows)
        assert associations[0][0] != associations[1][0]
        assert associations[0][1].values[2:] == associations[1][1].values[2:]
    with pytest.raises(FileExistsError):
        prepare(directory)


def test_ordinary_owner_without_registry_still_opens(tmp_path):
    definition = DatabaseDefinition("plain")
    with Database.create(definition, tmp_path) as database:
        database.create_gui_table(NewTable("ordinary", (("id", DataType.INTEGER),)), [(1,)])
        assert database.spatial_mapping_for("ordinary") is None
    with Database.open(definition, tmp_path) as database:
        assert database.spatial_mapping_for("ordinary") is None


@pytest.mark.parametrize("problem", ["duplicate", "wrong_version", "bad_columns", "unknown_table"])
def test_bad_registry_refuses_reopen_and_releases_owner(tmp_path, problem):
    directory = tmp_path / "spatial"
    prepare(directory)
    path = directory / REGISTRY_FILENAME
    original = path.read_text(encoding="utf-8")
    document = json.loads(original)
    if problem == "duplicate":
        document["tables"].append(document["tables"][0])
    elif problem == "wrong_version":
        document["version"] = True
    elif problem == "bad_columns":
        document["tables"][0]["latitude_column"] = "nombre"
    else:
        document["tables"][0]["table"] = "missing"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises((ValidationError, DatabaseSetupError)):
        Database.open(SPATIAL_DATABASE, directory)
    path.write_text(original, encoding="utf-8")
    with Database.open(SPATIAL_DATABASE, directory) as database:
        assert database.available


def test_spatial_mapping_is_explicit_for_other_table_names(tmp_path):
    definition = DatabaseDefinition("other")
    with Database.create(definition, tmp_path) as database:
        database.create_gui_table(NewTable("sucursales", (
            ("identidad", DataType.INTEGER), ("lat", DataType.FLOAT), ("lon", DataType.FLOAT)
        )), [(1, -12.04, -77.04)])
    mapping = SpatialMapping("sucursales", "lat", "lon", "identidad", "punto")
    write_mappings(tmp_path, (mapping,))
    with Database.open(definition, tmp_path) as database:
        assert database.spatial_mapping_for("sucursales") == mapping
    assert read_mappings(tmp_path) == (mapping,)


def test_comparator_refuses_changed_inputs_before_any_connection(tmp_path):
    export(tmp_path / "inputs", (1000,))
    setup_sql(tmp_path / "inputs", 1000)
    path = tmp_path / "inputs/points_1000.csv"
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        setup_sql(tmp_path / "inputs", 1000)


@pytest.mark.parametrize("fail_sql", [False, True])
def test_docker_comparator_uses_container_paths_and_cleans_up_on_failure(tmp_path, monkeypatch, fail_sql):
    import subprocess
    from types import SimpleNamespace
    import benchmarks.spatial.postgres as comparator

    directory = tmp_path / "inputs with ' quote"
    export(directory, (1000,))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "mktemp" in command:
            return SimpleNamespace(stdout="/tmp/minidbms-spatial.AbcD1234\n")
        if command[:3] == ["docker", "exec", "-i"]:
            sql = kwargs["input"]
            assert str(directory.resolve().as_posix()).replace("'", "''") not in sql
            assert "/tmp/minidbms-spatial.AbcD1234/points_1000.csv" in sql
            assert "/tmp/minidbms-spatial.AbcD1234/queries.csv" in sql
            assert "CREATE INDEX points_location_gist" in sql
            assert "-h" not in command
            if fail_sql:
                raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(comparator.subprocess, "run", run)
    args = ["--inputs", str(directory), "--container", "pg-spatial"]
    if fail_sql:
        with pytest.raises(subprocess.CalledProcessError):
            comparator.main(args)
    else:
        comparator.main(args)
    assert len([command for command, _ in calls if command[:2] == ["docker", "cp"]]) == 2
    assert calls[-2][0] == ["docker", "exec", "pg-spatial", "rm", "-f", "--",
                           "/tmp/minidbms-spatial.AbcD1234/points_1000.csv",
                           "/tmp/minidbms-spatial.AbcD1234/queries.csv"]
    assert calls[-1][0] == ["docker", "exec", "pg-spatial", "rmdir", "--",
                           "/tmp/minidbms-spatial.AbcD1234"]


def test_docker_comparator_rejects_modified_input_before_contacting_docker(tmp_path, monkeypatch):
    import benchmarks.spatial.postgres as comparator

    directory = tmp_path / "inputs"
    export(directory, (1000,))
    (directory / "queries.csv").write_text("changed", encoding="utf-8")

    def unexpected_call(*args, **kwargs):
        pytest.fail("Docker was contacted before input verification")

    monkeypatch.setattr(comparator.subprocess, "run", unexpected_call)
    with pytest.raises(ValueError, match="checksum"):
        comparator.main(["--inputs", str(directory), "--container", "pg-spatial"])


def test_docker_comparator_rejects_unsafe_temporary_path(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import benchmarks.spatial.postgres as comparator

    directory = tmp_path / "inputs"
    export(directory, (1000,))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="/var/lib/postgresql/data\n")

    monkeypatch.setattr(comparator.subprocess, "run", run)
    with pytest.raises(ValueError, match="temporary directory"):
        comparator.main(["--inputs", str(directory), "--container", "pg-spatial"])
    assert len(calls) == 1


def test_spatial_launcher_uses_the_existing_http_application(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import api.__main__ as launcher

    directory = tmp_path / "spatial"
    prepare(directory)
    answers = []

    class ProbeServer:
        def __init__(self, config, service):
            self.app = config.app

        def run(self):
            with TestClient(self.app) as client:
                tables = client.get("/api/tables")
                answer = client.post("/api/query", json={
                    "sql": "SELECT id FROM tiendas ORDER BY id"
                })
                assert tables.status_code == answer.status_code == 200
                assert [item["id"] for item in tables.json()] == ["tiendas", "restaurantes"]
                answers.append(answer.json()["rows"])

    monkeypatch.setattr(launcher, "_Server", ProbeServer)
    launcher.main(["--spatial", "--data-dir", str(directory), "--port", "0"])
    assert answers == [[[identity] for identity in range(1, 10)]]
    # Launcher shutdown must release the owner even in the spatial mode.
    with Database.open(SPATIAL_DATABASE, directory) as database:
        assert database.available


def test_spatial_launcher_refuses_unprepared_directory(tmp_path):
    import api.__main__ as launcher

    with pytest.raises(SystemExit, match="setup_spatial.py"):
        launcher.main(["--spatial", "--data-dir", str(tmp_path), "--port", "0"])
