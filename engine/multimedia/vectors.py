"""Persistent vector store and exhaustive VectorScan (Part 4, own code).

Files in a store directory, written once into a NEW directory:

* ``ids.npy``     int64 object ids in vector-row order (unique);
* ``vectors.npy`` float32 N x K unnormalized TF-IDF vectors;
* ``norms.npy``   float64 L2 norms of the stored float32 rows;
* ``manifest.json`` version, shape, dtypes, model fingerprint and SHA-256s.

Opening memory-maps the arrays read-only and checks cheap structure (shapes,
dtypes, sizes, fingerprint). ``verify=True`` also recomputes checksums. The
exact scan scores in float64 batches and keeps a bounded best-first top-k
(score DESC, id ASC), never a full N x N matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np

from engine.errors import InvalidTypeError, ValidationError

from .contracts import Metric, Neighbor, validate_k


STORE_VERSION = 1
STORE_FILES = ("ids.npy", "vectors.npy", "norms.npy")
DEFAULT_BATCH_ROWS = 8192


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    neighbors: tuple[Neighbor, ...]
    evaluated: int          # vectors scored (distance evaluations)
    method: str = "VectorScan"


def prepare_query(query, dimension: int) -> np.ndarray:
    array = np.asarray(query, dtype=np.float64)
    if array.ndim != 1 or len(array) != dimension:
        raise ValidationError(f"Query vector must have dimension {dimension}")
    if not np.all(np.isfinite(array)):
        raise ValidationError("Query vector components must be finite")
    if not np.any(array):
        raise ValidationError("Zero-norm vectors cannot be indexed or queried")
    return array


def batch_scores(rows: np.ndarray, norms: np.ndarray, query: np.ndarray, query_norm: float,
                 metric: Metric) -> np.ndarray:
    """SIMILARITY_SCORE for a block of stored rows (higher is better)."""
    block = rows.astype(np.float64)
    if metric is Metric.EUCLIDEAN:
        difference = block - query
        return -np.sqrt(np.einsum("ij,ij->i", difference, difference))
    if metric is Metric.DOT:
        return block @ query
    if metric is Metric.COSINE:
        return (block @ query) / (norms * query_norm)
    raise InvalidTypeError("metric must be a Metric")


def merge_top_k(best_ids: np.ndarray, best_scores: np.ndarray, ids: np.ndarray, scores: np.ndarray,
                k: int) -> tuple[np.ndarray, np.ndarray]:
    """Keep the k best by score DESC, id ASC (exact even across ties)."""
    all_ids = np.concatenate((best_ids, ids))
    all_scores = np.concatenate((best_scores, scores))
    if len(all_ids) > 4 * k:
        # Anything strictly worse than the k-th best score cannot survive.
        threshold = np.partition(all_scores, len(all_scores) - k)[len(all_scores) - k]
        keep = all_scores >= threshold
        all_ids, all_scores = all_ids[keep], all_scores[keep]
    order = np.lexsort((all_ids, -all_scores))[:k]
    return all_ids[order], all_scores[order]


def to_neighbors(ids: np.ndarray, scores: np.ndarray) -> tuple[Neighbor, ...]:
    return tuple(Neighbor(int(i), float(s)) for i, s in zip(ids, scores))


class VectorStore:
    """Read-only N x K vectors with their ids and norms."""

    __slots__ = ("_directory", "_ids", "_vectors", "_norms", "_manifest", "_closed")

    def __init__(self) -> None:
        raise TypeError("Use VectorStore.create() or VectorStore.open()")

    @classmethod
    def create(cls, directory: Path, ids, vectors, *, model_fingerprint: str) -> "VectorStore":
        directory = Path(directory)
        ids = np.asarray(ids)
        vectors = np.asarray(vectors)
        if ids.ndim != 1 or ids.dtype.kind not in "iu":
            raise InvalidTypeError("ids must be a 1-D integer array")
        ids = ids.astype(np.int64)
        if vectors.ndim != 2 or vectors.dtype != np.float32:
            raise InvalidTypeError("vectors must be a float32 matrix")
        if len(ids) != len(vectors) or not len(ids) or vectors.shape[1] < 1:
            raise ValidationError("Need one nonempty vector per id")
        if len(np.unique(ids)) != len(ids):
            raise ValidationError("Object ids must be unique")
        if not np.all(np.isfinite(vectors)):
            raise ValidationError("Vectors must be finite")
        norms = np.sqrt(np.einsum("ij,ij->i", vectors.astype(np.float64), vectors.astype(np.float64)))
        if np.any(norms == 0):
            raise ValidationError("Zero-norm vectors cannot be indexed or queried")
        if type(model_fingerprint) is not str or len(model_fingerprint) != 64:
            raise ValidationError("A 64-character model fingerprint is required")
        directory.mkdir(parents=True, exist_ok=False)
        for name, array in zip(STORE_FILES, (ids, np.ascontiguousarray(vectors), norms)):
            _write_array(directory / name, array)
        manifest = {"version": STORE_VERSION, "size": len(ids), "dimension": int(vectors.shape[1]),
                    "dtype": "float32", "model_fingerprint": model_fingerprint,
                    "files": {name: _sha256(directory / name) for name in STORE_FILES}}
        _write_bytes(directory / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode())
        return cls.open(directory, expected_fingerprint=model_fingerprint)

    @classmethod
    def open(cls, directory: Path, *, expected_fingerprint: str | None = None,
             verify: bool = False) -> "VectorStore":
        directory = Path(directory)
        missing = [n for n in ("manifest.json", *STORE_FILES) if not (directory / n).is_file()]
        if missing:
            raise ValidationError(f"Vector store is missing {', '.join(missing)}")
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValidationError("Vector store manifest is not valid JSON") from None
        if type(manifest) is not dict or manifest.get("version") != STORE_VERSION:
            raise ValidationError("Unsupported vector store version")
        if expected_fingerprint is not None and manifest["model_fingerprint"] != expected_fingerprint:
            raise ValidationError("Vector store belongs to a different feature model")
        if verify:
            for name, digest in manifest["files"].items():
                if _sha256(directory / name) != digest:
                    raise ValidationError(f"Vector store file {name} does not match its checksum")
        store = object.__new__(cls)
        store._directory = directory
        store._manifest = manifest
        store._closed = False
        size, dimension = manifest["size"], manifest["dimension"]
        try:
            store._ids = _map(directory / "ids.npy", np.int64, (size,))
            store._vectors = _map(directory / "vectors.npy", np.float32, (size, dimension))
            store._norms = _map(directory / "norms.npy", np.float64, (size,))
        except BaseException:
            store.close()
            raise
        return store

    # -- properties ---------------------------------------------------------
    def _require_open(self):
        if self._closed:
            raise ValidationError("Vector store is closed")

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def size(self) -> int:
        return self._manifest["size"]

    @property
    def dimension(self) -> int:
        return self._manifest["dimension"]

    @property
    def model_fingerprint(self) -> str:
        return self._manifest["model_fingerprint"]

    @property
    def ids(self) -> np.ndarray:
        self._require_open()
        return self._ids

    @property
    def vectors(self) -> np.ndarray:
        self._require_open()
        return self._vectors

    @property
    def norms(self) -> np.ndarray:
        self._require_open()
        return self._norms

    def row_of(self, object_id: int) -> int:
        self._require_open()
        rows = np.flatnonzero(self._ids == object_id)
        if not len(rows):
            raise ValidationError(f"Unknown object id {object_id}")
        return int(rows[0])

    # -- exact scan ---------------------------------------------------------
    def search(self, query, metric: Metric, k: int, *, batch_rows: int = DEFAULT_BATCH_ROWS) -> VectorSearchResult:
        """Exhaustive top-k over every stored vector (the exact reference)."""
        self._require_open()
        validate_k(k)
        if not isinstance(metric, Metric):
            raise InvalidTypeError("metric must be a Metric")
        q = prepare_query(query, self.dimension)
        q_norm = float(np.sqrt(q @ q))
        best_ids = np.empty(0, dtype=np.int64)
        best_scores = np.empty(0, dtype=np.float64)
        for start in range(0, self.size, batch_rows):
            stop = min(self.size, start + batch_rows)
            scores = batch_scores(self._vectors[start:stop], self._norms[start:stop], q, q_norm, metric)
            best_ids, best_scores = merge_top_k(best_ids, best_scores, self._ids[start:stop], scores, k)
        return VectorSearchResult(to_neighbors(best_ids, best_scores), self.size)

    def score_rows(self, rows: np.ndarray, query, metric: Metric) -> np.ndarray:
        """Exact scores for selected rows (used by approximate indexes)."""
        self._require_open()
        q = prepare_query(query, self.dimension)
        rows = np.asarray(rows, dtype=np.int64)
        return batch_scores(self._vectors[rows], self._norms[rows], q, float(np.sqrt(q @ q)), metric)

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        """Drop the store's memory maps; idempotent.

        The maps are released, not force-closed: force-closing a mapping that
        a caller's array view still references would crash on access. Once no
        view remains, the operating system releases the file (as Windows
        requires before deletion).
        """
        for name in ("_ids", "_vectors", "_norms"):
            setattr(self, name, None)
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> "VectorStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _map(path: Path, dtype, shape) -> np.ndarray:
    try:
        array = np.load(path, mmap_mode="r", allow_pickle=False)
    except ValueError:
        raise ValidationError(f"{path.name} is not a valid array file") from None
    if array.dtype != dtype or array.shape != shape:
        found = f"{array.dtype}{array.shape}"
        del array
        raise ValidationError(f"{path.name} has {found}; expected {np.dtype(dtype)}{shape}")
    return array


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_bytes(path: Path, data: bytes) -> None:
    with open(path, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _write_array(path: Path, array: np.ndarray) -> None:
    buffer = io.BytesIO()
    np.save(buffer, np.ascontiguousarray(array), allow_pickle=False)
    _write_bytes(path, buffer.getvalue())


__all__ = ["VectorStore", "VectorSearchResult", "prepare_query", "batch_scores", "merge_top_k", "to_neighbors"]
