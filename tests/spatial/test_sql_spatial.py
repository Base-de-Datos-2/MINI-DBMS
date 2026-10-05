import math

import pytest

from api.database import Database
from benchmarks.spatial.datasets import FIXTURE_ROWS
from engine.query.errors import SqlBindingError
from engine.spatial.geometry import Metric, Point
from engine.spatial.metadata import EARTH_RADIUS_METRES, ORIGIN
from scripts.setup_spatial import SPATIAL_DATABASE, prepare


POINT = "POINT(-12.0464, -77.0428)"


@pytest.fixture
def database(tmp_path):
    directory = tmp_path / "spatial"
    prepare(directory)
    with Database.open(SPATIAL_DATABASE, directory) as owner:
        yield owner


def rows(runner, sql, **options):
    return [row.values for row in runner.execute(sql, **options).fetchall(limit=100)]


def oracle(row, metric):
    latitude, longitude = row[2:]
    phi1, phi2 = map(math.radians, [ORIGIN[0], latitude])
    dphi, dlambda = math.radians(latitude - ORIGIN[0]), math.radians(longitude - ORIGIN[1])
    if metric == "euclidean":
        return EARTH_RADIUS_METRES * math.hypot(dphi, dlambda * math.cos(phi1))
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_METRES * math.asin(math.sqrt(value))


@pytest.mark.parametrize("metric", ["haversine", "euclidean"])
@pytest.mark.parametrize("indexed", [False, True])
def test_official_radius_and_knn_sql_match_independent_oracle(database, metric, indexed):
    expression = f"distancia(ubicacion, {POINT}, '{metric}')"
    expected_radius = sorted(row[0] for row in FIXTURE_ROWS if oracle(row, metric) < 5000)
    sql = f"SELECT * FROM tiendas WHERE {expression} < 5000 ORDER BY id"
    result = database.engine.execute(sql, use_indexes=indexed)
    actual = result.fetchall(limit=100)
    assert [row.values[0] for row in actual] == expected_radius
    assert len(result.schema.columns) == 4
    descriptor = next(node for node in result.report.runtime.root.walk()
                      if node.name in {"SpatialScan", "SpatialIndexScan"})
    assert dict(descriptor.details)["access"] == ("RTree" if indexed else "exhaustive")
    expected_knn = sorted(FIXTURE_ROWS, key=lambda row: (oracle(row, metric), row[0]))[:3]
    actual = rows(database.engine, f"SELECT id, {expression} AS metres FROM tiendas ORDER BY metres LIMIT 3", use_indexes=indexed)
    assert [row[0] for row in actual] == [row[0] for row in expected_knn]
    for got, source in zip(actual, expected_knn):
        assert got[1] == pytest.approx(oracle(source, metric), abs=1e-8)


def test_residual_filter_precedes_knn_limit_and_or_keeps_complete_candidates(database):
    sql = f"SELECT id FROM tiendas WHERE id > 2 ORDER BY distancia(ubicacion, {POINT}) LIMIT 2"
    expected = sorted((row for row in FIXTURE_ROWS if row[0] > 2), key=lambda row: (oracle(row, "haversine"), row[0]))[:2]
    prepared = database.engine.prepare(sql)
    assert "SpatialIndexScan" not in [node.name for node in prepared.describe().walk()]
    assert [row[0] for row in rows(database.engine, sql)] == [row[0] for row in expected]
    sql = f"SELECT id FROM tiendas WHERE distancia(ubicacion, {POINT}) < 0 OR id = 8 ORDER BY id"
    assert rows(database.engine, sql) == [(8,)]
    assert rows(database.engine, f"SELECT id FROM tiendas WHERE distancia(ubicacion, {POINT}) <= 0 ORDER BY id") == [(1,), (2,)]
    assert rows(database.engine, f"SELECT id FROM tiendas WHERE distancia(ubicacion, {POINT}) < -1") == []


def test_aliases_zero_limit_reverse_comparison_and_hidden_fields(database):
    assert rows(database.engine, f"SELECT t.id FROM tiendas t WHERE 0 >= distancia(t.ubicacion, {POINT}) ORDER BY t.id") == [(1,), (2,)]
    assert rows(database.engine, f"SELECT * FROM tiendas ORDER BY distancia(ubicacion, {POINT}) LIMIT 0") == []
    result = rows(database.engine, f"SELECT *, distancia(ubicacion, {POINT}) AS d FROM tiendas ORDER BY d LIMIT 1")
    assert len(result[0]) == 5
    assert result[0][0] == 1
    assert result[0][-1] == 0.0


@pytest.mark.parametrize("expression", [
    "POINT(-12, -77)", "distancia(id, POINT(-12, -77))", "distancia(ubicacion, POINT(-77, -12))",
    "distancia(ubicacion, POINT(TRUE, -77))", "distancia(ubicacion, POINT(-12))",
    "distancia(ubicacion, POINT(-12, -77), 'manhattan')", "distancia(ubicacion)",
])
def test_invalid_spatial_expressions_fail_before_opening(database, expression):
    with pytest.raises(SqlBindingError):
        database.engine.prepare(f"SELECT id FROM tiendas ORDER BY {expression} LIMIT 1")
    assert rows(database.engine, "SELECT COUNT(*) AS n FROM tiendas") == [(len(FIXTURE_ROWS),)]


def test_prepared_sql_rebinds_after_rollback_and_survives_reopen(database):
    sql = f"SELECT id FROM tiendas WHERE distancia(ubicacion, {POINT}) <= 0 ORDER BY id"
    session = database.open_session()
    try:
        prepared = session.prepare(sql)
        session.execute("BEGIN TRANSACTION")
        session.execute("DELETE FROM tiendas WHERE id = 1")
        assert rows(session, prepared) == [(2,)]
        session.execute("ROLLBACK")
        assert rows(session, prepared) == [(1,), (2,)]
        session.execute("INSERT INTO tiendas VALUES (99, 'Nueva', -12.0464, -77.0428)")
    finally:
        session.close()
    directory = database.directory
    database.close()
    with Database.open(SPATIAL_DATABASE, directory) as reopened:
        assert rows(reopened.engine, sql) == [(1,), (2,), (99,)]


def test_point_parameters_are_isolated_and_prepared_values_are_immutable(database):
    sql = "SELECT id FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 2"
    coordinates = list(ORIGIN)
    prepared = database.engine.prepare(sql, parameters={"mi_ubicacion": coordinates})
    coordinates[:] = [-12.2, -77.2]
    assert rows(database.engine, prepared) == [(1,), (2,)]
    assert rows(database.engine, sql, parameters={"mi_ubicacion": ORIGIN}) == [(1,), (2,)]
    with pytest.raises(SqlBindingError, match="Missing point parameter"):
        database.engine.prepare(sql)
    with pytest.raises(SqlBindingError):
        database.engine.prepare(sql, parameters={"mi_ubicacion": [True, -77]})
    with pytest.raises(SqlBindingError):
        database.engine.prepare(sql, parameters={"mi_ubicacion": "POINT(-12,-77)"})
    with database.open_session() as session:
        prepared = session.prepare(sql, parameters={"mi_ubicacion": ORIGIN})
        session.execute("BEGIN TRANSACTION")
        session.execute("DELETE FROM tiendas WHERE id = 1")
        session.execute("ROLLBACK")
        assert rows(session, prepared) == [(1,), (2,)]
