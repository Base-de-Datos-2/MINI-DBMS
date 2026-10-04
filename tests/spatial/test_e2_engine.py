"""Differential geometry/tree checks and the real owner mutation/undo lifecycle."""
from concurrent.futures import ThreadPoolExecutor
import math
import random
from time import monotonic, sleep

import pytest

from api.database import Database
from benchmarks.spatial.datasets import FIXTURE_POLYGON, FIXTURE_ROWS, point_rows, query_centers
from engine.errors import DuplicateError, ValidationError
from engine.operators.context import cancellation_scope
from engine.spatial.geometry import MBR, Metric, Point, Polygon, distance
from engine.spatial.metadata import EARTH_RADIUS_METRES, ORIGIN
from engine.spatial.rtree import RTree, SpatialEntry
from engine.storage import RID
from scripts.setup_spatial import SPATIAL_DATABASE, prepare


def ids(result):
    return [hit.identity for hit in result.hits]


def fixture_polygon():
    return Polygon(tuple(Point(*pair) for pair in FIXTURE_POLYGON))


def entries(size):
    return [SpatialEntry(identity, RID(identity // 30 + 1, identity % 30), Point(latitude, longitude))
            for identity, _, latitude, longitude in point_rows(size)]


def test_metrics_have_declared_units_and_genuinely_different_rankings():
    origin = Point(*ORIGIN)
    north = Point(ORIGIN[0] + .001, ORIGIN[1])
    east = Point(ORIGIN[0], ORIGIN[1] + .001)
    expected_north = EARTH_RADIUS_METRES * math.radians(.001)
    assert distance(origin, origin) == 0
    assert distance(origin, north) == pytest.approx(expected_north, abs=1e-8)
    assert distance(origin, north, Metric.EUCLIDEAN) == pytest.approx(expected_north, abs=1e-8)
    assert distance(origin, east, Metric.EUCLIDEAN) == pytest.approx(expected_north * math.cos(math.radians(ORIGIN[0])), abs=1e-8)
    center = Point(-12.22, -77.10)
    first, second = Point(-12.22, -77.099), Point(-12.2190224, -77.10)
    assert distance(center, first) < distance(center, second)
    assert distance(center, first, Metric.EUCLIDEAN) > distance(center, second, Metric.EUCLIDEAN)
    tree = RTree()
    tree.insert(SpatialEntry(1, RID(1, 1), first))
    tree.insert(SpatialEntry(2, RID(1, 2), second))
    assert ids(tree.knn(center, 1)) == [1]
    assert ids(tree.knn(center, 1, metric=Metric.EUCLIDEAN)) == [2]


@pytest.mark.parametrize('bad', [(-77., -12.), (float('nan'), -77.), (-12., float('inf')),
                                  (True, -77.), (-12., -78.), (10**1000, -77.)])
def test_points_reject_invalid_coordinates(bad):
    with pytest.raises(ValidationError):
        Point(*bad)


def test_mbr_operations_and_conservative_metric_bounds():
    box = MBR(-12.1, -77.1, -12., -77.)
    other = MBR(-12.2, -77.05, -12.05, -76.9)
    assert box.intersects(other)
    assert box.union(other).contains(box)
    assert box.union(other).contains(other)
    assert box.area == pytest.approx(.01)
    assert box.enlargement(other) > 0
    rng = random.Random(51)
    for _ in range(80):
        center = Point(rng.uniform(-12.3, -11.8), rng.uniform(-77.25, -76.75))
        target = Point(rng.uniform(box.min_latitude, box.max_latitude),
                       rng.uniform(box.min_longitude, box.max_longitude))
        for metric in Metric:
            assert box.lower_bound(center, metric) <= distance(center, target, metric) + 1e-8
    with pytest.raises(ValidationError):
        MBR(-12., -77., -12.1, -77.1)


def test_concave_polygon_includes_edges_but_not_all_its_mbr():
    polygon = fixture_polygon()
    points = [(identity, Point(latitude, longitude)) for identity, _, latitude, longitude in FIXTURE_ROWS]
    assert [identity for identity, point in points if polygon.contains(point)] == [1, 2, 3, 4, 5, 6]
    reversed_polygon = Polygon(tuple(reversed(polygon.vertices)))
    assert [identity for identity, point in points if reversed_polygon.contains(point)] == [1, 2, 3, 4, 5, 6]
    assert polygon.contains(polygon.vertices[0])
    assert polygon.box.contains(MBR.at(points[6][1]))
    assert not polygon.contains(points[6][1])


@pytest.mark.parametrize('pairs', [(), ((-12., -77.),) * 3,
    ((-12.1, -77.1), (-12., -77.), (-11.9, -76.9)),
    ((-12.1, -77.1), (-12., -77.), (-12.1, -77.), (-12., -77.1))])
def test_degenerate_or_self_intersecting_polygons_fail(pairs):
    with pytest.raises(ValidationError):
        Polygon(tuple(Point(*pair) for pair in pairs))


def test_small_valid_polygon_does_not_lose_area_to_geographic_cancellation():
    polygon = Polygon((Point(-12., -77.), Point(-12., -77.0000001),
                       Point(-12.0000001, -77.0000001), Point(-12.0000001, -77.)))
    assert polygon.contains(Point(-12.00000005, -77.00000005))
    assert polygon.contains(polygon.vertices[0])
    assert not polygon.contains(Point(-12.00000015, -77.00000005))


@pytest.mark.parametrize('capacity', [4, 7, 16])
def test_multilevel_tree_matches_exhaustive_radius_knn_and_polygon(capacity, tmp_path):
    points = entries(350)
    tree = RTree(capacity)
    for entry in points:
        tree.insert(entry)
    structural = tree.validate_structure()
    assert structural['height'] >= 3
    assert structural['entries'] == 350
    for _, latitude, longitude in query_centers()[:6]:
        center = Point(latitude, longitude)
        for metric in Metric:
            expected = sorted(points, key=lambda entry: (distance(center, entry.point, metric), entry.identity))
            for k in (0, 1, 10, 50, 400):
                answer = tree.knn(center, k, metric=metric)
                assert ids(answer) == [entry.identity for entry in expected[:k]]
            for radius in (0, 1000, 5000, 10000):
                answer = tree.radius(center, radius, metric=metric)
                assert ids(answer) == sorted(entry.identity for entry in points if distance(center, entry.point, metric) < radius)
    polygon = fixture_polygon()
    assert ids(tree.polygon(polygon)) == sorted(entry.identity for entry in points if polygon.contains(entry.point))
    center = Point(-12.299, -77.249)
    answer = tree.knn(center, 10)
    assert 0 < answer.stats.candidates < tree.entry_count
    assert 0 < answer.stats.visited_nodes < structural['nodes']
    path = tmp_path / 'tree.rtree'
    tree.save(path, metadata={'table': 'test'})
    reopened = RTree.load(path, metadata={'table': 'test'})
    assert reopened.validate_structure() == structural
    assert ids(reopened.knn(center, 10)) == ids(answer)
    with pytest.raises(ValidationError, match='mapping'):
        RTree.load(path, metadata={'table': 'wrong'})


@pytest.mark.parametrize('metric', list(Metric))
def test_duplicates_boundary_ties_empty_and_invalid_queries(metric):
    tree = RTree(4)
    center = Point(*ORIGIN)
    assert ids(tree.radius(center, 100)) == ids(tree.knn(center, 3)) == ids(tree.polygon(fixture_polygon())) == []
    # Insert tied entries in reverse ID order; the smaller ID must still win.
    for identity in reversed(range(1, 15)):
        tree.insert(SpatialEntry(identity, RID(1, identity), center))
    assert ids(tree.knn(center, 3, metric=metric)) == [1, 2, 3]
    assert ids(tree.radius(center, 0, metric=metric)) == []
    assert ids(tree.radius(center, 0, metric=metric, inclusive=True)) == list(range(1, 15))
    distant = SpatialEntry(15, RID(2, 0), Point(ORIGIN[0] + .001, ORIGIN[1]))
    tree.insert(distant)
    boundary = distance(center, distant.point, metric)
    assert 15 not in ids(tree.radius(center, boundary, metric=metric))
    assert 15 in ids(tree.radius(center, boundary, metric=metric, inclusive=True))
    with pytest.raises(DuplicateError):
        tree.insert(SpatialEntry(1, RID(2, 1), distant.point))
    with pytest.raises(DuplicateError):
        tree.insert(SpatialEntry(16, RID(1, 1), distant.point))
    for bad in (-1, True, 1.5):
        with pytest.raises(ValidationError):
            tree.knn(center, bad)
    for bad in (-1, float('nan'), float('inf'), True):
        with pytest.raises(ValidationError):
            tree.radius(center, bad)
    with pytest.raises(ValidationError):
        tree.knn(center, 0, metric='unknown')


def test_corrupt_file_and_failed_atomic_save_preserve_previous_tree(tmp_path, monkeypatch):
    import engine.spatial.rtree as module
    tree = RTree()
    tree.insert(entries(1)[0])
    path = tmp_path / 'tree.rtree'
    tree.save(path)
    previous = path.read_bytes()
    tree.insert(entries(2)[1])
    def fail(*args):
        raise OSError('injected publish failure')
    monkeypatch.setattr(module.os, 'replace', fail)
    with pytest.raises(OSError):
        tree.save(path)
    assert path.read_bytes() == previous
    assert list(tmp_path.glob('.rtree-*')) == []
    assert RTree.load(path).entry_count == 1
    path.write_bytes(previous.replace(b'"capacity":16', b'"capacity":15'))
    with pytest.raises(ValidationError, match='checksum'):
        RTree.load(path)


@pytest.fixture
def spatial_database(tmp_path):
    directory = tmp_path / 'spatial'
    prepare(directory)
    with Database.open(SPATIAL_DATABASE, directory) as database:
        yield database


def test_real_heap_index_and_scan_paths_match_and_resolve_records(spatial_database):
    database = spatial_database
    center = Point(*ORIGIN)
    for metric in Metric:
        for family, argument in (('radius', 5000), ('knn', 10)):
            query = getattr(database, f'spatial_{family}')
            indexed = query('tiendas', center, argument, metric=metric)
            baseline = query('tiendas', center, argument, metric=metric, use_index=False)
            assert indexed.hits == baseline.hits
            assert all(hit.record.values[0] == hit.identity for hit in indexed.hits)
            assert indexed.stats.access == 'RTree'
            assert baseline.stats.access == 'SpatialScan'
            assert indexed.stats.base_records_read == len(indexed.hits)
    assert ids(database.spatial_polygon('tiendas', fixture_polygon())) == [1, 2, 3, 4, 5, 6]
    assert database.spatial_polygon('tiendas', fixture_polygon()).hits == database.spatial_polygon('tiendas', fixture_polygon(), use_index=False).hits


def test_sql_mutations_commit_rollback_reopen_and_refresh_stale_objects(spatial_database):
    database = spatial_database
    center = Point(*ORIGIN)
    files = database.session_coordinator.resources.table_files('tiendas')
    assert len(files.auxiliary) == 1
    assert files.auxiliary[0][1] in files.physical_files
    with database.open_session() as session:
        session.execute('BEGIN TRANSACTION')
        inserted = session.execute("INSERT INTO tiendas VALUES (99, 'Nuevo', -12.0464, -77.0428)")
        assert '__spatial_tiendas' in inserted.statistics.indexes_maintained
        assert ids(database.spatial_radius('tiendas', center, 0, inclusive=True, session=session)) == [1, 2, 99]
        old = database._spatial_indexes['tiendas']
        session.execute('ROLLBACK')
        assert database._spatial_indexes['tiendas'] is not old
        with pytest.raises(ValidationError, match='closed'):
            old.knn(center, 3)
        assert ids(database.spatial_radius('tiendas', center, 0, inclusive=True, session=session)) == [1, 2]
        session.execute("INSERT INTO tiendas VALUES (99, 'Nuevo', -12.0464, -77.0428)")
        session.execute('BEGIN TRANSACTION')
        session.execute('DELETE FROM tiendas WHERE id = 1')
        assert ids(database.spatial_radius('tiendas', center, 0, inclusive=True, session=session)) == [2, 99]
        session.execute('ROLLBACK')
        assert ids(database.spatial_radius('tiendas', center, 0, inclusive=True, session=session)) == [1, 2, 99]
        session.execute('DELETE FROM tiendas WHERE id = 1')
    directory = database.directory
    database.close()
    with Database.open(SPATIAL_DATABASE, directory) as reopened:
        assert ids(reopened.spatial_radius('tiendas', center, 0, inclusive=True)) == [2, 99]
        assert reopened.spatial_knn('tiendas', center, 10).hits == reopened.spatial_knn('tiendas', center, 10, use_index=False).hits


@pytest.mark.parametrize('values', ["(99, 'Invalid', -77.0, -12.0)", "(1, 'Duplicate ID', -12.0, -77.0)"])
def test_invalid_spatial_insert_leaves_heap_and_tree_unchanged(spatial_database, values):
    database = spatial_database
    before = database.spatial_knn('tiendas', Point(*ORIGIN), 100).hits
    with pytest.raises(ValidationError):
        database.engine.execute(f'INSERT INTO tiendas VALUES {values}')
    assert database.available
    assert database.spatial_knn('tiendas', Point(*ORIGIN), 100).hits == before


def test_spatial_publish_failure_restores_heap_and_index(spatial_database, monkeypatch):
    database = spatial_database
    original = RTree.save
    def save(tree, *args, **kwargs):
        if tree.has_identity(99):
            raise OSError('injected spatial write failure')
        return original(tree, *args, **kwargs)
    monkeypatch.setattr(RTree, 'save', save)
    before = database.spatial_knn('tiendas', Point(*ORIGIN), 100).hits
    with pytest.raises(ValidationError):
        database.engine.execute("INSERT INTO tiendas VALUES (99, 'Fail', -12.0464, -77.0428)")
    assert database.available
    assert database.spatial_knn('tiendas', Point(*ORIGIN), 100).hits == before


def test_spatial_read_waits_for_writer_and_observes_only_committed_state(spatial_database):
    database = spatial_database
    with database.open_session() as writer, database.open_session() as reader:
        writer.execute('BEGIN TRANSACTION')
        writer.execute("INSERT INTO tiendas VALUES (99, 'Nuevo', -12.0464, -77.0428)")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(database.spatial_radius, 'tiendas', Point(*ORIGIN), 0,
                                 inclusive=True, session=reader)
            deadline = monotonic() + 5
            while not any(resource.waiters for resource in database.session_coordinator.locks.snapshot().resources):
                assert monotonic() < deadline
                sleep(.01)
            assert not future.done()
            writer.execute('ROLLBACK')
            assert ids(future.result(timeout=5)) == [1, 2]


def test_cancellation_interrupts_tree_search(spatial_database):
    class Cancelled(Exception):
        pass
    def cancel():
        raise Cancelled()
    with cancellation_scope(cancel), pytest.raises(Cancelled):
        spatial_database._spatial_indexes['tiendas'].tree.knn(Point(*ORIGIN), 10)


def test_waiting_spatial_session_can_cancel_without_harming_writer(spatial_database):
    from engine.transactions.errors import TransactionAbortError
    database = spatial_database
    with database.open_session() as writer, database.open_session() as reader:
        writer.execute('BEGIN TRANSACTION')
        writer.execute("INSERT INTO tiendas VALUES (99, 'Nuevo', -12.0464, -77.0428)")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(database.spatial_knn, 'tiendas', Point(*ORIGIN), 3, session=reader)
            deadline = monotonic() + 5
            while not any(item.waiters for item in database.session_coordinator.locks.snapshot().resources):
                assert monotonic() < deadline
                sleep(.01)
            assert reader.cancel()
            with pytest.raises(TransactionAbortError):
                future.result(timeout=5)
        assert reader.active_transaction is None
        writer.execute('END TRANSACTION')
        assert ids(database.spatial_radius('tiendas', Point(*ORIGIN), 0, inclusive=True, session=reader)) == [1, 2, 99]


def test_offline_benchmark_loading_builds_once_and_reopens(tmp_path, monkeypatch):
    calls = []
    original = RTree.save
    def save(tree, path, **kwargs):
        calls.append(tree.entry_count)
        return original(tree, path, **kwargs)
    monkeypatch.setattr(RTree, 'save', save)
    directory = tmp_path / 'benchmark'
    prepare(directory, size=1000)
    assert calls == [1000]
    with Database.open(SPATIAL_DATABASE, directory) as database:
        assert database.describe_table('puntos').row_count == 1000
        assert database._spatial_indexes['puntos'].tree.entry_count == 1000
        center = Point(*ORIGIN)
        for metric in Metric:
            assert database.spatial_knn('puntos', center, 50, metric=metric).hits == database.spatial_knn('puntos', center, 50, metric=metric, use_index=False).hits
            indexed = database.spatial_radius('puntos', center, 5000, metric=metric)
            scanned = database.spatial_radius('puntos', center, 5000, metric=metric, use_index=False)
            assert indexed.hits == scanned.hits
            assert 0 < indexed.stats.candidates < scanned.stats.candidates


def test_closed_or_corrupt_owner_rejects_spatial_reads_and_releases_lease(tmp_path):
    directory = tmp_path / 'database'
    prepare(directory)
    database = Database.open(SPATIAL_DATABASE, directory)
    mapping = database.spatial_mapping_for('tiendas')
    tree_path = directory / mapping.index_filename
    original = tree_path.read_bytes()
    database.close()
    with pytest.raises(ValidationError):
        database.spatial_knn('tiendas', Point(*ORIGIN), 3)
    tree_path.write_text('broken', encoding='utf-8')
    with pytest.raises(ValidationError):
        Database.open(SPATIAL_DATABASE, directory)
    tree_path.write_bytes(original)
    with Database.open(SPATIAL_DATABASE, directory) as reopened:
        assert ids(reopened.spatial_knn('tiendas', Point(*ORIGIN), 2)) == [1, 2]
