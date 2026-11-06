"""Phase 4: multilayer HNSW graph (own implementation)."""

from concurrent.futures import ThreadPoolExecutor
import json

import numpy as np
import pytest

from engine.errors import ValidationError
from engine.multimedia import HnswParameters, Metric, recall_at_k
from engine.multimedia.hnsw import HnswIndex, _Objective, layer0_reachable, select_neighbors
from engine.multimedia.vectors import VectorStore

FINGERPRINT = "e" * 64
SMALL = HnswParameters(m=8, m0=16, ef_construction=40, min_ef_search=32)


def sparse(n, k=24, seed=5):
    rng = np.random.default_rng(seed)
    vectors = rng.gamma(1.0, 1.0, size=(n, k)).astype(np.float32)
    vectors[rng.random(size=(n, k)) < 0.6] = 0.0
    vectors[:, 0] += 0.05
    return vectors


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    directory = tmp_path_factory.mktemp("hnsw")
    vectors = sparse(1500)
    ids = np.arange(10_000, 10_000 + 1500, dtype=np.int64)
    store = VectorStore.create(directory / "store", ids, vectors, model_fingerprint=FINGERPRINT)
    graphs = {metric: HnswIndex.build(directory / metric.value, store, metric, parameters=SMALL)
              for metric in Metric}
    yield store, graphs
    for graph in graphs.values():
        graph.close()
    store.close()


def in_distribution_queries(count=25, seed=8):
    return sparse(count, seed=seed)


def test_graph_has_a_real_hierarchy_with_an_entry_point_on_top(built):
    store, graphs = built
    for graph in graphs.values():
        manifest = graph.manifest
        assert graph.max_level >= 2
        counts = manifest["statistics"]["nodes_per_layer"]
        assert counts[0] == store.size and all(a > b for a, b in zip(counts, counts[1:]))
        assert graph.neighbors(graph.entry_point, graph.max_level) is not None


def test_links_respect_degree_caps_layer_membership_and_reciprocity(built):
    store, graphs = built
    graph = graphs[Metric.EUCLIDEAN]
    levels = graph._graph.levels
    reciprocal = total = 0
    for row in range(store.size):
        linked = graph.neighbors(row, 0)
        assert len(linked) <= SMALL.m0 and row not in linked and len(set(linked)) == len(linked)
        total += len(linked)
        reciprocal += sum(row in graph.neighbors(other, 0) for other in linked)
        for layer in range(1, int(levels[row]) + 1):
            upper = graph.neighbors(row, layer)
            assert len(upper) <= SMALL.m and np.all(levels[upper] >= layer)
    # Shrinking overflowing nodes drops some back-links, but most links are mutual.
    assert reciprocal / total > 0.6


def test_almost_every_element_is_reachable_from_the_entry_point(built):
    store, graphs = built
    for graph in graphs.values():
        reachable = graph.manifest["statistics"]["layer0_reachable_from_entry"]
        assert reachable == layer0_reachable(graph._graph.layer0, graph.entry_point)
        assert reachable >= 0.995 * store.size


@pytest.mark.parametrize("metric", [Metric.EUCLIDEAN, Metric.COSINE])
def test_recall_against_the_exact_scan_is_high_and_measured(built, metric):
    store, graphs = built
    recalls = []
    for query in in_distribution_queries():
        approximate = graphs[metric].search(query, metric, 10)
        exact = store.search(query, metric, 10)
        recalls.append(recall_at_k([n.object_id for n in approximate.neighbors],
                                   [n.object_id for n in exact.neighbors]))
        assert approximate.method == "HNSW" and not approximate.details["shortfall"]
    assert np.mean(recalls) >= 0.9


def test_dot_graph_uses_the_augmented_euclidean_form(built):
    store, graphs = built
    # Maximum inner product is harder than plain NN: with the reduced test
    # parameters (M=8) it needs a wider efSearch; M=16 reaches ~0.99 at ef 64.
    recalls = [recall_at_k([n.object_id for n in
                            graphs[Metric.DOT].search(q, Metric.DOT, 10, ef_search=128).neighbors],
                           [n.object_id for n in store.search(q, Metric.DOT, 10).neighbors])
               for q in in_distribution_queries()]
    assert np.mean(recalls) >= 0.9


def test_augmented_distance_orders_exactly_like_descending_dot():
    vectors = sparse(50, k=6, seed=3)
    objective = _Objective(vectors, Metric.DOT)
    assert objective.data.shape == (50, 7)
    assert np.allclose(np.linalg.norm(objective.data.astype(np.float64), axis=1),
                       np.linalg.norm(vectors.astype(np.float64), axis=1).max(), rtol=1e-5)
    query = np.random.default_rng(1).gamma(1.0, 1.0, size=6)
    distances = objective.to_rows(objective.prepare(query), np.arange(50))
    dots = vectors.astype(np.float64) @ query
    assert np.argsort(distances, kind="stable").tolist() == np.argsort(-dots, kind="stable").tolist()


def test_search_is_not_a_disguised_scan(built):
    store, graphs = built
    result = graphs[Metric.COSINE].search(in_distribution_queries()[0], Metric.COSINE, 10, ef_search=10)
    assert result.evaluated < store.size / 2
    assert result.details["distance_evaluations"] == result.evaluated


def test_stored_vectors_recover_themselves(built):
    store, graphs = built
    for row in (0, 77, 1499):
        for metric in (Metric.EUCLIDEAN, Metric.COSINE):
            top = graphs[metric].search(store.vectors[row], metric, 1).neighbors[0]
            assert top.object_id == int(store.ids[row])


def test_returned_scores_are_exact_and_best_first(built):
    store, graphs = built
    query = in_distribution_queries()[3]
    result = graphs[Metric.EUCLIDEAN].search(query, Metric.EUCLIDEAN, 10)
    rows = [store.row_of(n.object_id) for n in result.neighbors]
    assert [n.score for n in result.neighbors] == store.score_rows(np.array(rows), query, Metric.EUCLIDEAN).tolist()
    keys = [(-n.score, n.object_id) for n in result.neighbors]
    assert keys == sorted(keys)


def test_large_ef_on_a_small_graph_returns_every_reachable_element(tmp_path):
    vectors = sparse(60, seed=11)
    with VectorStore.create(tmp_path / "s", np.arange(60), vectors, model_fingerprint=FINGERPRINT) as store, \
            HnswIndex.build(tmp_path / "g", store, Metric.COSINE, parameters=SMALL) as graph:
        query = vectors[5]
        result = graph.search(query, Metric.COSINE, 100)
        assert result.neighbors == store.search(query, Metric.COSINE, 100).neighbors


def test_concurrent_searches_keep_query_local_state(built):
    store, graphs = built
    graph = graphs[Metric.COSINE]
    queries = in_distribution_queries(40, seed=21)
    sequential = [graph.search(q, Metric.COSINE, 10) for q in queries]
    with ThreadPoolExecutor(max_workers=8) as pool:
        concurrent = list(pool.map(lambda q: graph.search(q, Metric.COSINE, 10), queries))
    assert concurrent == sequential


def test_construction_is_reproducible_with_a_fixed_seed(tmp_path):
    vectors = sparse(300, seed=13)
    with VectorStore.create(tmp_path / "s", np.arange(300), vectors, model_fingerprint=FINGERPRINT) as store:
        first = HnswIndex.build(tmp_path / "a", store, Metric.EUCLIDEAN, parameters=SMALL, seed=4)
        second = HnswIndex.build(tmp_path / "b", store, Metric.EUCLIDEAN, parameters=SMALL, seed=4)
        other = HnswIndex.build(tmp_path / "c", store, Metric.EUCLIDEAN, parameters=SMALL, seed=5)
        assert np.array_equal(first._graph.layer0, second._graph.layer0)
        assert np.array_equal(first._graph.levels, second._graph.levels)
        assert not np.array_equal(first._graph.levels, other._graph.levels)


def test_heuristic_prefers_diverse_neighbors_then_fills_with_pruned_ones():
    points = np.array([[0.0, 0.0], [1.0, 0.0], [1.1, 0.0], [0.0, 1.5], [3.0, 0.0]], dtype=np.float32)
    objective = _Objective(points, Metric.EUCLIDEAN)
    distances = objective.between(0, np.arange(1, 5))
    ranked = sorted(zip(distances.tolist(), range(1, 5)))
    # Row 2 is closer to row 1 than to the base; row 4 lies behind row 1.
    assert select_neighbors(objective, ranked, 4, keep_pruned=False) == [1, 3]
    assert select_neighbors(objective, ranked, 3, keep_pruned=True) == [1, 3, 2]


def test_graph_serves_only_its_own_metric_and_validates_ef(built):
    _, graphs = built
    with pytest.raises(ValidationError, match="built for metric euclidean"):
        graphs[Metric.EUCLIDEAN].search(np.ones(24), Metric.COSINE, 3)
    with pytest.raises(ValidationError, match="efSearch"):
        graphs[Metric.EUCLIDEAN].search(np.ones(24), Metric.EUCLIDEAN, 10, ef_search=5)


def test_reopening_reproduces_results_without_rebuilding(built, monkeypatch):
    store, graphs = built
    import engine.multimedia.hnsw as hnsw_module
    graph = graphs[Metric.COSINE]
    queries = in_distribution_queries(10, seed=30)
    before = [graph.search(q, Metric.COSINE, 10) for q in queries]
    monkeypatch.setattr(hnsw_module, "select_neighbors", None)   # any insertion would fail
    with HnswIndex.open(graph._directory, store, verify=True) as reopened:
        assert [reopened.search(q, Metric.COSINE, 10) for q in queries] == before


def corrupt(directory, name, change):
    array = np.load(directory / name)
    change(array)
    (directory / name).unlink()
    np.save(directory / name, array)


@pytest.mark.parametrize("name, change, message", [
    ("layer0.npy", lambda a: a.__setitem__((0, 0), 10**6), "invalid link references"),
    ("layer0.npy", lambda a: a.__setitem__((3, 0), 3), "self links"),
    ("layer0.npy", lambda a: a.__setitem__((4, slice(0, 2)), [9, 9]), "duplicate links"),
    ("levels.npy", lambda a: a.__setitem__(np.argmax(a), 0), "entry point|membership|levels"),
])
def test_structural_damage_is_rejected_on_open(tmp_path, name, change, message):
    vectors = sparse(200, seed=17)
    with VectorStore.create(tmp_path / "s", np.arange(200), vectors, model_fingerprint=FINGERPRINT) as store:
        HnswIndex.build(tmp_path / "g", store, Metric.EUCLIDEAN, parameters=SMALL).close()
        corrupt(tmp_path / "g", name, change)
        with pytest.raises(ValidationError, match=message):
            HnswIndex.open(tmp_path / "g", store)


def test_upper_layer_links_to_lower_elements_are_rejected(tmp_path):
    vectors = sparse(400, seed=19)
    with VectorStore.create(tmp_path / "s", np.arange(400), vectors, model_fingerprint=FINGERPRINT) as store:
        graph = HnswIndex.build(tmp_path / "g", store, Metric.EUCLIDEAN, parameters=SMALL)
        ground = int(np.flatnonzero(graph._graph.levels == 0)[0])
        graph.close()
        corrupt(tmp_path / "g", "links_1.npy", lambda a: a.__setitem__((0, 0), ground))
        with pytest.raises(ValidationError, match="absent from that layer"):
            HnswIndex.open(tmp_path / "g", store)


def test_graph_is_bound_to_its_store_and_never_overwritten(built, tmp_path):
    store, graphs = built
    with VectorStore.create(tmp_path / "other", np.arange(1500), sparse(1500, seed=6),
                            model_fingerprint=FINGERPRINT) as other:
        with pytest.raises(ValidationError, match="different vector store"):
            HnswIndex.open(graphs[Metric.DOT]._directory, other)
    with pytest.raises(FileExistsError):
        HnswIndex.build(graphs[Metric.DOT]._directory, store, Metric.DOT)
    manifest = json.loads((graphs[Metric.DOT]._directory / "manifest.json").read_text())
    assert manifest["metric"] == "dot" and manifest["m"] == 8
