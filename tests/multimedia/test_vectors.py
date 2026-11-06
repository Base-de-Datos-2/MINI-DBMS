"""Phase 2: persistent vector store and exact VectorScan."""

import json

import numpy as np
import pytest

from engine.errors import InvalidTypeError, ValidationError
from engine.multimedia import Metric, exact_top_k
from engine.multimedia.vectors import VectorStore, merge_top_k

FINGERPRINT = "a" * 64


def random_vectors(n=300, k=12, seed=4):
    rng = np.random.default_rng(seed)
    vectors = rng.gamma(1.0, 1.0, size=(n, k)).astype(np.float32)
    vectors[rng.random(size=(n, k)) < 0.5] = 0.0
    vectors[:, 0] += 0.01                       # no zero rows
    ids = rng.permutation(np.arange(1000, 1000 + n)).astype(np.int64)
    return ids, vectors


@pytest.fixture
def store(tmp_path):
    ids, vectors = random_vectors()
    with VectorStore.create(tmp_path / "store", ids, vectors, model_fingerprint=FINGERPRINT) as created:
        yield created


@pytest.mark.parametrize("metric", list(Metric))
@pytest.mark.parametrize("k", [1, 10, 299, 300, 5000])
def test_exact_scan_equals_the_scalar_oracle(store, metric, k):
    query = np.random.default_rng(9).gamma(1.0, 1.0, size=store.dimension)
    result = store.search(query, metric, k, batch_rows=64)
    items = [(int(i), v.tolist()) for i, v in zip(store.ids, store.vectors)]
    expected = exact_top_k(items, query.tolist(), metric, k)
    assert [n.object_id for n in result.neighbors] == [n.object_id for n in expected]
    assert [n.score for n in result.neighbors] == pytest.approx([n.score for n in expected], rel=1e-9)
    assert result.evaluated == 300 and len(result.neighbors) == min(k, 300)


def test_ties_across_batches_are_broken_by_ascending_id(tmp_path):
    vectors = np.tile(np.array([[1.0, 2.0]], dtype=np.float32), (50, 1))
    ids = np.arange(50, 0, -1)                       # descending ids, identical vectors
    with VectorStore.create(tmp_path / "ties", ids, vectors, model_fingerprint=FINGERPRINT) as store:
        result = store.search([1.0, 2.0], Metric.COSINE, 7, batch_rows=8)
        assert [n.object_id for n in result.neighbors] == [1, 2, 3, 4, 5, 6, 7]


def test_merge_keeps_every_tie_at_the_threshold():
    ids, scores = merge_top_k(np.array([5, 9]), np.array([0.9, 0.5]),
                              np.array([1, 2, 3, 4, 6, 7, 8, 10, 11]),
                              np.array([0.5, 0.5, 0.1, 0.5, 0.2, 0.3, 0.5, 0.0, 0.5]), 3)
    assert ids.tolist() == [5, 1, 2]
    assert scores.tolist() == [0.9, 0.5, 0.5]


def test_store_reopens_read_only_with_identical_contents(store, tmp_path):
    directory = store.directory
    ids, vectors = store.ids.copy(), store.vectors.copy()
    store.close()
    with VectorStore.open(directory, expected_fingerprint=FINGERPRINT, verify=True) as reopened:
        assert np.array_equal(reopened.ids, ids) and np.array_equal(reopened.vectors, vectors)
        assert np.allclose(reopened.norms, np.linalg.norm(vectors.astype(np.float64), axis=1))
        with pytest.raises(ValueError):
            reopened.vectors[0, 0] = 1.0
        assert reopened.row_of(int(ids[3])) == 3
    with pytest.raises(ValidationError, match="closed"):
        reopened.search(np.ones(12), Metric.DOT, 1)
    reopened.close()                                  # closing twice is safe


def test_store_refuses_existing_directories_and_foreign_models(store):
    ids, vectors = random_vectors()
    with pytest.raises(FileExistsError):
        VectorStore.create(store.directory, ids, vectors, model_fingerprint=FINGERPRINT)
    with pytest.raises(ValidationError, match="different feature model"):
        VectorStore.open(store.directory, expected_fingerprint="b" * 64)


@pytest.mark.parametrize("change, message", [
    (lambda ids, v: (np.concatenate([ids[:-1], ids[:1]]), v), "unique"),
    (lambda ids, v: (ids, np.where(np.arange(v.size).reshape(v.shape) == 0, np.nan, v).astype(np.float32)), "finite"),
    (lambda ids, v: (ids, np.vstack([np.zeros((1, v.shape[1]), np.float32), v[1:]])), "Zero-norm"),
    (lambda ids, v: (ids[:-1], v), "one nonempty vector"),
])
def test_invalid_contents_are_rejected_before_writing(tmp_path, change, message):
    ids, vectors = change(*random_vectors())
    with pytest.raises(ValidationError, match=message):
        VectorStore.create(tmp_path / "bad", ids, vectors, model_fingerprint=FINGERPRINT)
    assert not (tmp_path / "bad").exists()


def test_types_are_never_coerced(tmp_path):
    ids, vectors = random_vectors()
    with pytest.raises(InvalidTypeError):
        VectorStore.create(tmp_path / "f64", ids, vectors.astype(np.float64), model_fingerprint=FINGERPRINT)
    with pytest.raises(InvalidTypeError):
        VectorStore.create(tmp_path / "ids", ids.astype(np.float64), vectors, model_fingerprint=FINGERPRINT)


def test_damage_and_shape_mismatch_are_detected_on_open(store):
    directory = store.directory
    store.close()
    vectors_file = directory / "vectors.npy"
    data = bytearray(vectors_file.read_bytes())
    data[-3] ^= 0x55
    vectors_file.write_bytes(bytes(data))
    with pytest.raises(ValidationError, match="checksum"):
        VectorStore.open(directory, verify=True)
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["dimension"] = 13
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValidationError, match="expected float32"):
        VectorStore.open(directory)
    (directory / "norms.npy").unlink()
    with pytest.raises(ValidationError, match="missing norms.npy"):
        VectorStore.open(directory)


@pytest.mark.parametrize("query, message", [
    (np.ones(11), "dimension 12"), (np.zeros(12), "Zero-norm"), (np.full(12, np.nan), "finite"),
])
def test_invalid_queries_are_rejected(store, query, message):
    with pytest.raises(ValidationError, match=message):
        store.search(query, Metric.COSINE, 3)


def test_invalid_k_and_metric_are_rejected(store):
    with pytest.raises(ValidationError):
        store.search(np.ones(12), Metric.DOT, 0)
    with pytest.raises(InvalidTypeError):
        store.search(np.ones(12), "dot", 3)


def test_selected_rows_are_scored_exactly(store):
    query = np.linspace(0.1, 1.2, 12)
    full = {n.object_id: n.score for n in store.search(query, Metric.EUCLIDEAN, 300).neighbors}
    rows = np.array([0, 5, 17])
    scores = store.score_rows(rows, query, Metric.EUCLIDEAN)
    assert scores.tolist() == pytest.approx([full[int(store.ids[r])] for r in rows])
