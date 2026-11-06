"""IVF with full vectors (IVFFlat scope), own implementation (Part 4 phase 3).

Construction, per coarse space:

* ``raw`` partitions the unnormalized vectors and serves Euclidean and dot;
* ``unit`` partitions L2-normalized vectors and serves cosine.

Each space trains our own K-Means (``kmeans.py``) on a seeded bounded sample,
assigns every vector to its nearest center (L2) and persists the centers, the
list offsets and the vector rows grouped by list (ascending inside a list).

Search routes the query to lists in order of the query objective against the
centers (Euclidean: squared distance; cosine: 1 − cosine; dot: −dot), probes
``nprobe`` lists, probes more when they hold fewer than ``min(k, N)``
candidates, and scores every candidate exactly on the stored vectors. Routing
is approximate; scores are not. Probing every list equals the exact scan.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from engine.errors import InvalidTypeError, ValidationError

from .contracts import IndexMethod, Metric, default_nlist, default_nprobe, validate_k
from .files import (
    read_array, read_json, require_files, sha256_file, verify_checksums, write_array, write_json,
)
from .kmeans import kmeans, nearest_center
from .vectors import VectorSearchResult, VectorStore, merge_top_k, prepare_query, to_neighbors


IVF_VERSION = 1
DEFAULT_TRAINING_SAMPLE = 50_000
DEFAULT_SEED = 20_261_106


def space_for(metric: Metric) -> str:
    if not isinstance(metric, Metric):
        raise InvalidTypeError("metric must be a Metric")
    return "unit" if metric is Metric.COSINE else "raw"


def _space_files(space: str) -> tuple[str, str, str]:
    return (f"centers_{space}.npy", f"offsets_{space}.npy", f"rows_{space}.npy")


def _space_vectors(vectors: np.ndarray, space: str) -> np.ndarray:
    block = np.asarray(vectors, dtype=np.float64)
    if space == "unit":
        block = block / np.linalg.norm(block, axis=1)[:, None]
    return block


def routing_objective(centers: np.ndarray, query: np.ndarray, metric: Metric) -> np.ndarray:
    """Lower is better: the query objective evaluated against each center."""
    if metric is Metric.EUCLIDEAN:
        difference = centers - query
        return np.einsum("ij,ij->i", difference, difference)
    if metric is Metric.DOT:
        return -np.einsum("ij,j->i", centers, query)
    norms = np.linalg.norm(centers, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cosine = np.einsum("ij,j->i", centers, query) / (norms * np.linalg.norm(query))
    return np.where(norms > 0, 1.0 - cosine, np.inf)


def collect_candidates(order: np.ndarray, offsets: np.ndarray, rows: np.ndarray, nprobe: int,
                       needed: int) -> tuple[np.ndarray, int]:
    """Rows of the first ``nprobe`` lists, plus more lists until ``needed`` exist.

    Returns (candidate rows, effective number of lists probed). Empty lists
    count as probed but contribute nothing.
    """
    chosen = []
    total = 0
    probed = 0
    for list_number in order:
        if probed >= nprobe and total >= needed:
            break
        start, stop = offsets[list_number], offsets[list_number + 1]
        if stop > start:
            chosen.append(rows[start:stop])
            total += stop - start
        probed += 1
    if not chosen:
        return np.empty(0, dtype=np.int64), probed
    return np.concatenate(chosen), probed


@dataclass(frozen=True, slots=True)
class _Space:
    centers: np.ndarray
    offsets: np.ndarray
    rows: np.ndarray


class IvfIndex:
    """Read-only IVF over a ``VectorStore``; build once into a NEW directory."""

    __slots__ = ("_directory", "_store", "_manifest", "_spaces", "_closed")

    def __init__(self) -> None:
        raise TypeError("Use IvfIndex.build() or IvfIndex.open()")

    @classmethod
    def build(cls, directory: Path, store: VectorStore, *, metrics: Iterable[Metric] = tuple(Metric),
              nlist: int | None = None, nprobe: int | None = None, seed: int = DEFAULT_SEED,
              training_sample: int = DEFAULT_TRAINING_SAMPLE, max_iterations: int = 50) -> "IvfIndex":
        metrics = tuple(metrics)
        if not metrics or any(not isinstance(m, Metric) for m in metrics):
            raise InvalidTypeError("metrics must be a nonempty sequence of Metric")
        size = store.size
        nlist = default_nlist(size) if nlist is None else nlist
        if type(nlist) is not int or not 1 <= nlist <= size:
            raise ValidationError("nlist must be an integer between 1 and N")
        nprobe = default_nprobe(nlist) if nprobe is None else nprobe
        if type(nprobe) is not int or not 1 <= nprobe <= nlist:
            raise ValidationError("nprobe must be an integer between 1 and nlist")
        if type(training_sample) is not int or training_sample < nlist:
            raise ValidationError("The training sample must hold at least nlist vectors")
        spaces = sorted({space_for(metric) for metric in metrics})
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        training = {}
        rng = np.random.default_rng(seed)
        sample_rows = (np.arange(size) if size <= training_sample
                       else np.sort(rng.choice(size, size=training_sample, replace=False)))
        for space in spaces:
            vectors = _space_vectors(store.vectors, space)
            result = kmeans(vectors[sample_rows], nlist, seed=seed, max_iterations=max_iterations)
            labels, _ = nearest_center(vectors, result.centers)
            order = np.lexsort((np.arange(size), labels))
            offsets = np.concatenate(([0], np.cumsum(np.bincount(labels, minlength=nlist)))).astype(np.int64)
            centers_file, offsets_file, rows_file = _space_files(space)
            write_array(directory / centers_file, result.centers)
            write_array(directory / offsets_file, offsets)
            write_array(directory / rows_file, order.astype(np.int64))
            training[space] = {"sample_size": int(len(sample_rows)), "iterations": result.iterations,
                               "sample_inertia": result.inertia, "refilled_empty": result.refilled_empty,
                               "empty_lists": int(np.sum(np.diff(offsets) == 0)),
                               "largest_list": int(np.max(np.diff(offsets)))}
        files = [name for space in spaces for name in _space_files(space)]
        write_json(directory / "manifest.json", {
            "version": IVF_VERSION, "method": IndexMethod.IVF.value, "nlist": nlist, "nprobe": nprobe,
            "seed": seed, "max_iterations": max_iterations, "spaces": spaces,
            "metrics": sorted(m.value for m in metrics), "store": store.identity, "training": training,
            "files": {name: sha256_file(directory / name) for name in files}})
        return cls.open(directory, store)

    @classmethod
    def open(cls, directory: Path, store: VectorStore, *, verify: bool = False) -> "IvfIndex":
        """Open lists and centers; never retrains or repartitions."""
        directory = Path(directory)
        require_files(directory, ("manifest.json",), "IVF index")
        manifest = read_json(directory / "manifest.json", "IVF manifest")
        if manifest.get("version") != IVF_VERSION or manifest.get("method") != IndexMethod.IVF.value:
            raise ValidationError("Unsupported IVF index version")
        if manifest.get("store") != store.identity:
            raise ValidationError("IVF index was built for a different vector store")
        spaces = manifest.get("spaces")
        if not spaces or not set(spaces) <= {"raw", "unit"}:
            raise ValidationError("IVF manifest declares no valid coarse space")
        require_files(directory, [n for s in spaces for n in _space_files(s)], "IVF index")
        if verify:
            verify_checksums(directory, manifest["files"], "IVF index")
        nlist, size, dimension = manifest["nlist"], store.size, store.dimension
        loaded = {}
        for space in spaces:
            centers_file, offsets_file, rows_file = _space_files(space)
            centers = read_array(directory / centers_file, np.float64, (nlist, dimension))
            offsets = read_array(directory / offsets_file, np.int64, (nlist + 1,))
            rows = read_array(directory / rows_file, np.int64, (size,))
            if not np.all(np.isfinite(centers)):
                raise ValidationError("IVF centers must be finite")
            if offsets[0] != 0 or offsets[-1] != size or np.any(np.diff(offsets) < 0):
                raise ValidationError("IVF list offsets are inconsistent")
            if not np.array_equal(np.sort(rows), np.arange(size)):
                raise ValidationError("IVF lists must hold every vector row exactly once")
            loaded[space] = _Space(centers, offsets, rows)
        index = object.__new__(cls)
        index._directory = directory
        index._store = store
        index._manifest = manifest
        index._spaces = loaded
        index._closed = False
        return index

    @property
    def nlist(self) -> int:
        return self._manifest["nlist"]

    @property
    def nprobe(self) -> int:
        return self._manifest["nprobe"]

    @property
    def metrics(self) -> tuple[Metric, ...]:
        return tuple(Metric(m) for m in self._manifest["metrics"])

    @property
    def manifest(self) -> dict:
        return dict(self._manifest)

    def lists(self, metric: Metric) -> list[np.ndarray]:
        """Vector rows per list for the space serving ``metric`` (tests/reports)."""
        space = self._space(metric)
        return [space.rows[space.offsets[i]:space.offsets[i + 1]] for i in range(self.nlist)]

    def centers(self, metric: Metric) -> np.ndarray:
        return self._space(metric).centers

    def _space(self, metric: Metric) -> _Space:
        if self._closed:
            raise ValidationError("IVF index is closed")
        if metric not in self.metrics:
            raise ValidationError(f"This IVF index was not built for metric {metric.value}")
        return self._spaces[space_for(metric)]

    def search(self, query, metric: Metric, k: int, *, nprobe: int | None = None) -> VectorSearchResult:
        validate_k(k)
        space = self._space(metric)
        nprobe = self.nprobe if nprobe is None else nprobe
        if type(nprobe) is not int or not 1 <= nprobe <= self.nlist:
            raise ValidationError("nprobe must be an integer between 1 and nlist")
        q = prepare_query(query, self._store.dimension)
        routing_query = q / np.linalg.norm(q) if metric is Metric.COSINE else q
        objective = routing_objective(space.centers, routing_query, metric)
        order = np.lexsort((np.arange(self.nlist), objective))
        needed = min(k, self._store.size)
        rows, probed = collect_candidates(order, space.offsets, space.rows, nprobe, needed)
        scores = self._store.score_rows(rows, q, metric)
        ids, best = merge_top_k(np.empty(0, np.int64), np.empty(0, np.float64),
                                self._store.ids[rows], scores, k)
        return VectorSearchResult(to_neighbors(ids, best), int(len(rows)), IndexMethod.IVF.value, {
            "metric": metric.value, "nlist": self.nlist, "nprobe_requested": nprobe,
            "nprobe_effective": probed, "candidates": int(len(rows)),
            "centroid_evaluations": self.nlist})

    def close(self) -> None:
        self._spaces = {}
        self._closed = True

    def __enter__(self) -> "IvfIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


__all__ = ["IvfIndex", "collect_candidates", "routing_objective", "space_for"]
