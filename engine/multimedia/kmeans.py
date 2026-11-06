"""Own seeded K-Means for the IVF coarse partition (Part 4, decision D1).

The vocabulary uses scikit-learn as a feature helper; the IVF partition is
part of the index we implement, so it uses this code:

* k-means++ initialization (seeded, first center uniform, then D² sampling);
* Lloyd iterations with squared Euclidean distances computed in float64
  batches (``‖x‖² − 2x·c + ‖c‖²``, clamped at zero);
* empty clusters are refilled deterministically with the point farthest from
  its current center, so every list starts nonempty on the training sample;
* stop when no assignment changes or after ``max_iterations``;
* keep the best of a few seeded restarts, since one k-means++ start can end in
  a poor local optimum.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from engine.errors import ValidationError


@dataclass(frozen=True, slots=True)
class KMeansResult:
    centers: np.ndarray       # float64 n_clusters x d
    labels: np.ndarray        # int64 per training point
    inertia: float            # sum of squared distances to the assigned center
    iterations: int
    refilled_empty: int       # empty clusters refilled during training


def squared_distances(points: np.ndarray, centers: np.ndarray, batch_rows: int = 8192) -> np.ndarray:
    """N x C squared Euclidean distances, computed in float64 row batches."""
    points = np.asarray(points, dtype=np.float64)
    centers = np.asarray(centers, dtype=np.float64)
    center_norms = np.einsum("ij,ij->i", centers, centers)
    result = np.empty((len(points), len(centers)), dtype=np.float64)
    for start in range(0, len(points), batch_rows):
        block = points[start:start + batch_rows]
        distances = (np.einsum("ij,ij->i", block, block)[:, None] - 2.0 * (block @ centers.T)
                     + center_norms[None, :])
        np.maximum(distances, 0.0, out=distances)
        result[start:start + batch_rows] = distances
    return result


def nearest_center(points: np.ndarray, centers: np.ndarray, batch_rows: int = 8192):
    """(labels, squared distance) per point; ties go to the lower center."""
    labels = np.empty(len(points), dtype=np.int64)
    best = np.empty(len(points), dtype=np.float64)
    for start in range(0, len(points), batch_rows):
        distances = squared_distances(points[start:start + batch_rows], centers, batch_rows)
        labels[start:start + batch_rows] = np.argmin(distances, axis=1)
        best[start:start + batch_rows] = distances[np.arange(len(distances)),
                                                   labels[start:start + batch_rows]]
    return labels, best


def kmeans_plus_plus(points: np.ndarray, n_clusters: int, rng: np.random.Generator) -> np.ndarray:
    centers = np.empty((n_clusters, points.shape[1]), dtype=np.float64)
    centers[0] = points[rng.integers(len(points))]
    closest = squared_distances(points, centers[:1])[:, 0]
    for index in range(1, n_clusters):
        total = closest.sum()
        if total <= 0:
            raise ValidationError("Not enough distinct points for the requested clusters")
        choice = int(np.searchsorted(np.cumsum(closest), rng.random() * total, side="right"))
        choice = min(choice, len(points) - 1)
        centers[index] = points[choice]
        closest = np.minimum(closest, squared_distances(points, centers[index:index + 1])[:, 0])
    return centers


def update_centers(points: np.ndarray, labels: np.ndarray, previous: np.ndarray) -> np.ndarray:
    """Mean of each cluster; a cluster left without points keeps its center."""
    counts = np.bincount(labels, minlength=len(previous))
    order = np.argsort(labels, kind="stable")
    starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
    centers = previous.copy()
    nonempty = counts > 0
    sums = np.add.reduceat(points[order], starts[nonempty], axis=0)
    centers[nonempty] = sums / counts[nonempty][:, None]
    return centers


def kmeans(points: np.ndarray, n_clusters: int, *, seed: int, max_iterations: int = 50,
           restarts: int = 3) -> KMeansResult:
    """Best of ``restarts`` seeded runs (lowest inertia; ties keep the first)."""
    if type(restarts) is not int or restarts < 1:
        raise ValidationError("restarts must be a positive integer")
    best = None
    for run in range(restarts):
        result = _kmeans_once(points, n_clusters, seed=seed + run, max_iterations=max_iterations)
        if best is None or result.inertia < best.inertia:
            best = result
    return best


def _kmeans_once(points: np.ndarray, n_clusters: int, *, seed: int, max_iterations: int) -> KMeansResult:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or not len(points):
        raise ValidationError("K-Means needs a nonempty points matrix")
    if type(n_clusters) is not int or n_clusters < 1:
        raise ValidationError("The number of clusters must be a positive integer")
    if not np.all(np.isfinite(points)):
        raise ValidationError("K-Means points must be finite")
    if len(np.unique(points, axis=0)) < n_clusters:
        raise ValidationError(f"Fewer than {n_clusters} distinct points for {n_clusters} clusters")
    rng = np.random.default_rng(seed)
    centers = kmeans_plus_plus(points, n_clusters, rng)
    labels = np.full(len(points), -1, dtype=np.int64)
    refilled = 0
    iteration = 0
    for iteration in range(1, max_iterations + 1):
        new_labels, distances = nearest_center(points, centers)
        counts = np.bincount(new_labels, minlength=n_clusters)
        empty = np.flatnonzero(counts == 0)
        if len(empty):
            # Refill each empty cluster with the farthest point (ties: lower row),
            # taking it from its previous cluster.
            order = np.lexsort((np.arange(len(points)), -distances))
            for cluster, row in zip(empty, order):
                new_labels[row] = cluster
                distances[row] = 0.0
            refilled += len(empty)
        changed = not np.array_equal(new_labels, labels)
        labels = new_labels
        centers = update_centers(points, labels, centers)
        if not changed:
            break
    labels, distances = nearest_center(points, centers)
    return KMeansResult(centers, labels, float(distances.sum()), iteration, refilled)


__all__ = ["KMeansResult", "kmeans", "kmeans_plus_plus", "nearest_center", "squared_distances", "update_centers"]
