"""Phase 3: own K-Means and the IVF index (IVFFlat scope)."""

import json
from pathlib import Path

import numpy as np
import pytest

from engine.errors import ValidationError
from engine.multimedia import Metric, Modality, recall_at_k
from engine.multimedia.ivf import IvfIndex, collect_candidates, routing_objective
from engine.multimedia.kmeans import kmeans, nearest_center, update_centers
from engine.multimedia.vectors import VectorStore

FINGERPRINT = "c" * 64
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def blobs(seed=1, clusters=10, per=300, dim=8):
    rng = np.random.default_rng(seed)
    centers = rng.normal(0, 5, size=(clusters, dim))
    return np.vstack([rng.normal(c, 0.5, size=(per, dim)) for c in centers])


def sparse_vectors(n=600, k=16, seed=2):
    rng = np.random.default_rng(seed)
    vectors = rng.gamma(1.0, 1.0, size=(n, k)).astype(np.float32)
    vectors[rng.random(size=(n, k)) < 0.6] = 0.0
    vectors[:, 0] += 0.05
    return np.arange(5000, 5000 + n, dtype=np.int64), vectors


@pytest.fixture
def store(tmp_path):
    ids, vectors = sparse_vectors()
    with VectorStore.create(tmp_path / "store", ids, vectors, model_fingerprint=FINGERPRINT) as created:
        yield created


@pytest.fixture
def index(store, tmp_path):
    with IvfIndex.build(tmp_path / "ivf", store) as built:
        yield built


# --- Own K-Means -----------------------------------------------------------

def test_own_kmeans_reaches_the_library_optimum_on_separated_blobs():
    from sklearn.cluster import KMeans
    points = blobs()
    reference = KMeans(10, n_init=10, random_state=0).fit(points).inertia_
    for seed in range(5):
        assert kmeans(points, 10, seed=seed).inertia == pytest.approx(reference, rel=1e-6)


def test_kmeans_is_deterministic_and_labels_every_point():
    points = blobs(seed=4)
    first, second = kmeans(points, 7, seed=9), kmeans(points, 7, seed=9)
    assert np.array_equal(first.centers, second.centers) and np.array_equal(first.labels, second.labels)
    assert first.labels.shape == (len(points),) and set(first.labels) <= set(range(7))
    labels, distances = nearest_center(points, first.centers)
    assert np.array_equal(labels, first.labels)
    assert distances.sum() == pytest.approx(first.inertia)


def test_kmeans_needs_enough_distinct_points_and_valid_arguments():
    with pytest.raises(ValidationError, match="distinct"):
        kmeans(np.ones((20, 3)), 2, seed=0)
    with pytest.raises(ValidationError):
        kmeans(np.ones((0, 3)), 1, seed=0)
    with pytest.raises(ValidationError):
        kmeans(blobs(), 0, seed=0)
    with pytest.raises(ValidationError):
        kmeans(blobs(), 3, seed=0, restarts=0)


def test_one_cluster_per_distinct_point_has_zero_inertia():
    points = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [5.0, 5.0]])
    result = kmeans(points, 4, seed=1)
    assert result.inertia == 0.0 and len(set(result.labels)) == 4


def test_a_cluster_left_empty_keeps_its_previous_center():
    points = np.array([[0.0, 0.0], [2.0, 0.0], [10.0, 10.0]])
    previous = np.array([[1.0, 1.0], [9.0, 9.0], [50.0, 50.0]])
    centers = update_centers(points, np.array([0, 0, 1]), previous)
    assert centers.tolist() == [[1.0, 0.0], [10.0, 10.0], [50.0, 50.0]]


# --- IVF structure ---------------------------------------------------------

def test_default_parameters_and_every_vector_in_exactly_one_list_per_space(index, store):
    assert index.nlist == 24 and index.nprobe == 8            # round(sqrt(600)) and min(8, nlist)
    for metric in (Metric.EUCLIDEAN, Metric.COSINE):
        lists = index.lists(metric)
        rows = np.concatenate(lists)
        assert sorted(rows.tolist()) == list(range(store.size))
        assert all(np.all(np.diff(rows_in_list) > 0) for rows_in_list in lists if len(rows_in_list))
    # Euclidean and dot share the raw partition; cosine uses normalized vectors.
    assert all(np.array_equal(a, b) for a, b in zip(index.lists(Metric.EUCLIDEAN), index.lists(Metric.DOT)))
    assert np.allclose(np.linalg.norm(index.centers(Metric.COSINE), axis=1) <= 1.0 + 1e-12, True)


def test_vectors_are_assigned_to_their_nearest_center(index, store):
    vectors = np.asarray(store.vectors, dtype=np.float64)
    labels, _ = nearest_center(vectors, index.centers(Metric.EUCLIDEAN))
    for list_number, rows in enumerate(index.lists(Metric.EUCLIDEAN)):
        assert np.all(labels[rows] == list_number)


@pytest.mark.parametrize("metric", list(Metric))
@pytest.mark.parametrize("k", [1, 10, 600, 1000])
def test_probing_every_list_equals_the_exact_scan_exactly(index, store, metric, k):
    query = np.random.default_rng(7).gamma(1.0, 1.0, size=store.dimension)
    approximate = index.search(query, metric, k, nprobe=index.nlist)
    exact = store.search(query, metric, k)
    assert approximate.neighbors == exact.neighbors          # ids and scores, bit for bit
    assert approximate.evaluated == store.size


@pytest.mark.parametrize("metric", list(Metric))
def test_exhaustive_probing_keeps_the_id_tie_break(tmp_path, metric):
    vectors = np.tile(np.array([[1.0, 2.0, 0.0]], np.float32), (30, 1))
    vectors[::3] = [0.0, 1.0, 3.0]
    ids = np.arange(300, 0, -10)
    with VectorStore.create(tmp_path / "ties", ids, vectors, model_fingerprint=FINGERPRINT) as store, \
            IvfIndex.build(tmp_path / "ivf", store, nlist=2) as index:
        query = [1.0, 2.0, 0.5]
        assert index.search(query, metric, 12, nprobe=2).neighbors == store.search(query, metric, 12).neighbors


def test_limited_probing_is_approximate_and_reports_its_work(index, store):
    rng = np.random.default_rng(11)
    recalls = []
    for _ in range(20):
        query = rng.gamma(1.0, 1.0, size=store.dimension)
        result = index.search(query, Metric.EUCLIDEAN, 10, nprobe=2)
        exact = store.search(query, Metric.EUCLIDEAN, 10)
        recalls.append(recall_at_k([n.object_id for n in result.neighbors],
                                   [n.object_id for n in exact.neighbors]))
        assert result.method == "IVF" and result.details["nprobe_requested"] == 2
        assert result.details["nprobe_effective"] >= 2
        assert result.evaluated == result.details["candidates"] < store.size
        assert [n.score for n in result.neighbors] == sorted((n.score for n in result.neighbors), reverse=True)
    assert 0.0 < np.mean(recalls) <= 1.0


def test_lists_with_too_few_candidates_trigger_extra_probes(index, store):
    query = np.ones(store.dimension)
    result = index.search(query, Metric.COSINE, store.size, nprobe=1)
    assert len(result.neighbors) == store.size
    assert result.details["nprobe_effective"] == index.nlist
    assert result.neighbors == store.search(query, Metric.COSINE, store.size).neighbors


def test_candidate_collection_skips_empty_lists_and_counts_them_as_probed():
    offsets = np.array([0, 2, 2, 2, 5])
    rows = np.array([7, 8, 1, 2, 3])
    candidates, probed = collect_candidates(np.array([1, 2, 0, 3]), offsets, rows, nprobe=2, needed=1)
    assert candidates.tolist() == [7, 8] and probed == 3
    candidates, probed = collect_candidates(np.array([3, 0, 1, 2]), offsets, rows, nprobe=1, needed=4)
    assert candidates.tolist() == [1, 2, 3, 7, 8] and probed == 2


def test_routing_orders_centers_by_each_query_objective():
    centers = np.array([[10.0, 0.0], [1.0, 1.0], [0.0, 3.0]])
    query = np.array([1.0, 0.2])
    assert np.argsort(routing_objective(centers, query, Metric.EUCLIDEAN)).tolist() == [1, 2, 0]
    assert np.argsort(routing_objective(centers, query, Metric.DOT)).tolist() == [0, 1, 2]
    assert np.argsort(routing_objective(centers, query / np.linalg.norm(query), Metric.COSINE)).tolist() == [0, 1, 2]


def test_parameters_and_unbuilt_metrics_are_validated(store, tmp_path):
    with pytest.raises(ValidationError, match="nlist"):
        IvfIndex.build(tmp_path / "a", store, nlist=store.size + 1)
    with pytest.raises(ValidationError, match="nprobe"):
        IvfIndex.build(tmp_path / "b", store, nlist=4, nprobe=5)
    with IvfIndex.build(tmp_path / "c", store, metrics=(Metric.EUCLIDEAN,)) as euclidean_only:
        with pytest.raises(ValidationError, match="not built for metric cosine"):
            euclidean_only.search(np.ones(16), Metric.COSINE, 3)
        with pytest.raises(ValidationError, match="nprobe"):
            euclidean_only.search(np.ones(16), Metric.EUCLIDEAN, 3, nprobe=0)
        assert not (tmp_path / "c" / "centers_unit.npy").exists()


# --- Persistence -----------------------------------------------------------

def test_reopening_restores_identical_results_without_retraining(index, store, monkeypatch):
    import engine.multimedia.ivf as ivf_module
    directory = index._directory
    query = np.linspace(0.2, 2.0, store.dimension)
    before = {m: index.search(query, m, 10) for m in Metric}
    index.close()
    monkeypatch.setattr(ivf_module, "kmeans", None)       # any retraining would fail
    with IvfIndex.open(directory, store, verify=True) as reopened:
        for metric in Metric:
            assert reopened.search(query, metric, 10) == before[metric]


def test_index_is_bound_to_its_vector_store(index, store, tmp_path):
    ids, vectors = sparse_vectors(seed=3)
    with VectorStore.create(tmp_path / "other", ids, vectors, model_fingerprint=FINGERPRINT) as other:
        with pytest.raises(ValidationError, match="different vector store"):
            IvfIndex.open(index._directory, other)


def test_damaged_lists_and_manifests_are_rejected(index, store):
    directory = index._directory
    index.close()
    rows_file = directory / "rows_raw.npy"
    rows = np.load(rows_file)
    rows[0], rows[1] = rows[1], rows[1]                     # one row twice, one row missing
    rows_file.unlink()
    np.save(rows_file, rows)
    with pytest.raises(ValidationError, match="exactly once"):
        IvfIndex.open(directory, store)
    with pytest.raises(ValidationError, match="checksum"):
        IvfIndex.open(directory, store, verify=True)
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["version"] = 7
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValidationError, match="version"):
        IvfIndex.open(directory, store)


def test_existing_destination_is_never_overwritten(index, store):
    with pytest.raises(FileExistsError):
        IvfIndex.build(index._directory, store)


def test_ivf_centers_live_in_vector_space_not_descriptor_space(tmp_path):
    from engine.multimedia.features import build_collection_features, train_vocabulary
    manifest = json.loads((FIXTURES / "manifest.v1.json").read_text())
    gallery = [e["name"] for e in manifest["files"] if e["modality"] == "image" and e["role"] == "gallery"]
    codebook = train_vocabulary(Modality.IMAGE, [FIXTURES / n for n in gallery], 16)
    features = build_collection_features(Modality.IMAGE, [(i, FIXTURES / n) for i, n in enumerate(gallery, 1)],
                                         codebook)
    with VectorStore.create(tmp_path / "s", features.ids, features.vectors,
                            model_fingerprint=features.model.fingerprint) as store, \
            IvfIndex.build(tmp_path / "ivf", store) as index:
        assert features.model.codebook.shape == (16, 128)       # visual words: SIFT space
        assert index.centers(Metric.EUCLIDEAN).shape == (3, 16)  # coarse lists: TF-IDF space
        query = features.model.encode(FIXTURES / "foto_consulta.jpg")
        assert index.search(query, Metric.COSINE, 3, nprobe=3).neighbors == \
            store.search(query, Metric.COSINE, 3).neighbors
