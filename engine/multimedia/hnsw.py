"""Hierarchical Navigable Small World graph, own implementation (Part 4 phase 4).

Follows Malkov & Yashunin (arXiv:1603.09320):

* each element gets a seeded random level ``floor(−ln U · mL)``, mL = 1/ln M;
* insertion descends greedily (ef = 1) from the entry point through the upper
  layers, then runs a best-first search with ``efConstruction`` on every layer
  from its level down to 0 (Algorithm 2);
* neighbors are chosen with the paper's heuristic (Algorithm 4, with
  keepPrunedConnections and without extended candidates), links are
  reciprocal, and a node whose degree overflows (M on upper layers, M0 = 2M on
  layer 0) is shrunk with the same heuristic;
* search descends greedily to layer 1 and explores layer 0 with
  ``efSearch = max(64, k)``; the ef best candidates are then rescored exactly
  on the stored vectors and the best-first top-k (score DESC, id ASC) returned.

One graph serves one objective: Euclidean (squared distance), cosine
(1 − cosine on normalized vectors) or dot (augmented Euclidean form, whose
order equals descending dot exactly; see ``_Objective``).
Visited state is local to each search, so concurrent readers are safe.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from pathlib import Path

import numpy as np

from engine.errors import InvalidTypeError, ValidationError

from .contracts import HnswParameters, IndexMethod, Metric, default_ef_search, validate_k
from .files import (
    read_array, read_json, require_files, sha256_file, verify_checksums, write_array, write_json,
)
from .vectors import VectorSearchResult, VectorStore, merge_top_k, prepare_query, to_neighbors


HNSW_VERSION = 1
DEFAULT_SEED = 20_261_106
MAX_LEVEL = 16


class _Objective:
    """Lower-is-better objective between a query and stored rows.

    Dot product is turned into a Euclidean problem (Bachrach et al., 2014):
    each vector gains a coordinate ``sqrt(M² − ‖x‖²)`` (M = largest norm) and
    the query a 0, so ``‖q' − x'‖² = ‖q‖² + M² − 2 q·x``: ascending augmented
    distance is exactly descending dot, and the graph is built on a true
    metric instead of the non-metric −dot.
    """

    def __init__(self, vectors: np.ndarray, metric: Metric):
        if not isinstance(metric, Metric):
            raise InvalidTypeError("metric must be a Metric")
        data = np.asarray(vectors, dtype=np.float64)
        if metric is Metric.COSINE:
            data = data / np.linalg.norm(data, axis=1)[:, None]
        elif metric is Metric.DOT:
            squared = np.einsum("ij,ij->i", data, data)
            data = np.hstack([data, np.sqrt(np.maximum(squared.max() - squared, 0.0))[:, None]])
        self.metric = metric
        self.data = np.ascontiguousarray(data, dtype=np.float32)
        self.squared_norms = (np.einsum("ij,ij->i", self.data, self.data)
                              if metric is not Metric.COSINE else None)
        self.evaluations = 0

    def fork(self) -> "_Objective":
        """Same read-only data, private evaluation counter (one per search)."""
        other = object.__new__(_Objective)
        other.metric, other.data, other.squared_norms = self.metric, self.data, self.squared_norms
        other.evaluations = 0
        return other

    def prepare(self, query: np.ndarray) -> np.ndarray:
        query = np.asarray(query, dtype=np.float64)
        if self.metric is Metric.COSINE:
            query = query / np.linalg.norm(query)
        elif self.metric is Metric.DOT:
            query = np.append(query, 0.0)
        return query.astype(np.float32)

    def to_rows(self, query: np.ndarray, rows: np.ndarray) -> np.ndarray:
        self.evaluations += len(rows)
        products = self.data[rows] @ query
        if self.metric is Metric.COSINE:
            return 1.0 - products
        # Euclidean, and dot in its augmented Euclidean form.
        return np.maximum(self.squared_norms[rows] - 2.0 * products + float(query @ query), 0.0)

    def between(self, row: int, rows: np.ndarray) -> np.ndarray:
        return self.to_rows(self.data[row], rows)


def search_layer(objective: _Objective, query: np.ndarray, entries: list[tuple[float, int]],
                 neighbors_of, ef: int, size: int) -> list[tuple[float, int]]:
    """Best-first search on one layer (Algorithm 2); returns ≤ ef (dist, row) sorted."""
    visited = np.zeros(size, dtype=bool)
    candidates = []
    results = []                                        # max-heap via (-dist, -row)
    for distance, row in entries:
        visited[row] = True
        heapq.heappush(candidates, (distance, row))
        heapq.heappush(results, (-distance, -row))
        if len(results) > ef:
            heapq.heappop(results)
    while candidates:
        distance, row = heapq.heappop(candidates)
        if distance > -results[0][0] and len(results) >= ef:
            break
        linked = neighbors_of(row)
        if not len(linked):
            continue
        fresh = linked[~visited[linked]]
        if not len(fresh):
            continue
        visited[fresh] = True
        distances = objective.to_rows(query, fresh)
        for value, other in zip(distances.tolist(), fresh.tolist()):
            if len(results) < ef or value < -results[0][0]:
                heapq.heappush(candidates, (value, other))
                heapq.heappush(results, (-value, -other))
                if len(results) > ef:
                    heapq.heappop(results)
    return sorted((-d, -r) for d, r in results)


def select_neighbors(objective: _Objective, candidates: list[tuple[float, int]], limit: int,
                     keep_pruned: bool = True) -> list[int]:
    """Paper heuristic (Algorithm 4): keep a candidate only if it is closer to the
    base element than to every neighbor already kept (candidates sorted by
    distance to base). With ``keep_pruned`` (the paper's keepPrunedConnections)
    the discarded candidates then fill the remaining slots in distance order,
    which keeps degrees, and therefore reachability, from collapsing."""
    kept: list[int] = []
    pruned: list[int] = []
    for distance, row in candidates:
        if len(kept) >= limit:
            break
        if not kept or distance < float(np.min(objective.between(row, np.array(kept, dtype=np.int64)))):
            kept.append(row)
        else:
            pruned.append(row)
    if keep_pruned:
        kept.extend(pruned[:limit - len(kept)])
    return kept


@dataclass(frozen=True, slots=True)
class _Graph:
    levels: np.ndarray                    # int8 level per vector row
    layer0: np.ndarray                    # int32 N x M0, -1 padded
    upper_nodes: tuple[np.ndarray, ...]   # layer l>=1: sorted rows present on that layer
    upper_links: tuple[np.ndarray, ...]   # layer l>=1: int32 n_l x M, -1 padded
    entry_point: int
    max_level: int


def layer0_reachable(layer0: np.ndarray, entry_point: int) -> int:
    """Elements reachable from the entry point through layer-0 links (BFS)."""
    seen = np.zeros(len(layer0), dtype=bool)
    seen[entry_point] = True
    frontier = np.array([entry_point], dtype=np.int64)
    while len(frontier):
        linked = layer0[frontier].ravel()
        linked = linked[linked >= 0]
        fresh = np.unique(linked[~seen[linked]])
        seen[fresh] = True
        frontier = fresh
    return int(seen.sum())


def _validate_graph(graph: _Graph, size: int, m: int, m0: int) -> None:
    levels = graph.levels
    if levels.shape != (size,) or np.any(levels < 0) or np.any(levels > MAX_LEVEL):
        raise ValidationError("HNSW levels are invalid")
    if graph.max_level != int(levels.max()) or levels[graph.entry_point] != graph.max_level:
        raise ValidationError("HNSW entry point must lie on the top layer")
    if len(graph.upper_nodes) != graph.max_level or len(graph.upper_links) != graph.max_level:
        raise ValidationError("HNSW layer count does not match the maximum level")

    def check(links: np.ndarray, members: np.ndarray, cap: int, layer: int) -> None:
        if links.ndim != 2 or links.shape[1] != cap or len(links) != len(members):
            raise ValidationError(f"HNSW layer {layer} adjacency has the wrong shape")
        valid = links >= 0
        # -1 padding only after the valid prefix, ids in range, no self links.
        if (np.any(links < -1) or np.any(valid[:, 1:] & ~valid[:, :-1])
                or np.any(links[valid] >= size)):
            raise ValidationError(f"HNSW layer {layer} has invalid link references")
        if np.any(links == members[:, None]):
            raise ValidationError(f"HNSW layer {layer} has self links")
        if np.any(levels[links[valid]] < layer):
            raise ValidationError(f"HNSW layer {layer} links to elements absent from that layer")
        ordered = np.sort(links, axis=1)
        if np.any((ordered[:, 1:] == ordered[:, :-1]) & (ordered[:, 1:] >= 0)):
            raise ValidationError(f"HNSW layer {layer} has duplicate links")

    check(graph.layer0, np.arange(size), m0, 0)
    for layer in range(1, graph.max_level + 1):
        nodes = graph.upper_nodes[layer - 1]
        if not np.array_equal(nodes, np.flatnonzero(levels >= layer)):
            raise ValidationError(f"HNSW layer {layer} membership disagrees with the levels")
        check(graph.upper_links[layer - 1], nodes, m, layer)


class HnswIndex:
    """Read-only HNSW graph for one metric over a ``VectorStore``."""

    __slots__ = ("_directory", "_store", "_manifest", "_graph", "_objective", "_slots", "_closed")

    def __init__(self) -> None:
        raise TypeError("Use HnswIndex.build() or HnswIndex.open()")

    @classmethod
    def build(cls, directory: Path, store: VectorStore, metric: Metric, *,
              parameters: HnswParameters = HnswParameters(), seed: int = DEFAULT_SEED) -> "HnswIndex":
        if not isinstance(metric, Metric):
            raise InvalidTypeError("metric must be a Metric")
        m, m0, ef_construction = parameters.m, parameters.m0, parameters.ef_construction
        if m < 2 or m0 < m or ef_construction < 1:
            raise ValidationError("HNSW needs M >= 2, M0 >= M and efConstruction >= 1")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        size = store.size
        objective = _Objective(store.vectors, metric)
        rng = np.random.default_rng(seed)
        level_scale = 1.0 / math.log(m)
        uniforms = rng.random(size)
        levels = np.minimum(np.floor(-np.log(np.maximum(uniforms, 1e-300)) * level_scale),
                            MAX_LEVEL).astype(np.int8)
        layer0 = np.full((size, m0), -1, dtype=np.int32)
        degree0 = np.zeros(size, dtype=np.int32)
        upper: list[dict[int, list[int]]] = [dict() for _ in range(int(levels.max()))]

        def links_of(layer: int):
            if layer == 0:
                return lambda row: layer0[row, :degree0[row]]
            table = upper[layer - 1]
            return lambda row: np.array(table[row], dtype=np.int64)

        def set_links(layer: int, row: int, values: list[int]) -> None:
            if layer == 0:
                layer0[row, :] = -1
                layer0[row, :len(values)] = values
                degree0[row] = len(values)
            else:
                upper[layer - 1][row] = list(values)

        def connect(layer: int, row: int, other: int) -> None:
            cap = m0 if layer == 0 else m
            current = links_of(layer)(other).tolist()
            if row in current:
                return
            if len(current) < cap:
                set_links(layer, other, current + [row])
                return
            pool = np.array(current + [row], dtype=np.int64)
            distances = objective.between(other, pool)
            ranked = sorted(zip(distances.tolist(), pool.tolist()))
            set_links(layer, other, select_neighbors(objective, ranked, cap))

        entry, top = 0, int(levels[0])
        for layer in range(1, top + 1):
            upper[layer - 1][0] = []
        for row in range(1, size):
            level = int(levels[row])
            query = objective.data[row]
            current = [(float(objective.to_rows(query, np.array([entry]))[0]), entry)]
            for layer in range(top, level, -1):
                current = search_layer(objective, query, current, links_of(layer), 1, size)[:1]
            for layer in range(min(top, level), -1, -1):
                found = search_layer(objective, query, current, links_of(layer), ef_construction, size)
                chosen = select_neighbors(objective, found, m)
                set_links(layer, row, chosen)
                for other in chosen:
                    connect(layer, row, other)
                current = found
            for layer in range(top + 1, level + 1):
                upper[layer - 1][row] = []
            if level > top:
                entry, top = row, level

        upper_nodes, upper_links = [], []
        for layer in range(1, top + 1):
            nodes = np.array(sorted(upper[layer - 1]), dtype=np.int32)
            links = np.full((len(nodes), m), -1, dtype=np.int32)
            for slot, node in enumerate(nodes.tolist()):
                values = upper[layer - 1][node]
                links[slot, :len(values)] = values
            upper_nodes.append(nodes)
            upper_links.append(links)
        graph = _Graph(levels, layer0, tuple(upper_nodes), tuple(upper_links), entry, top)
        _validate_graph(graph, size, m, m0)
        write_array(directory / "levels.npy", levels)
        write_array(directory / "layer0.npy", layer0)
        files = ["levels.npy", "layer0.npy"]
        for layer in range(1, top + 1):
            for prefix, array in (("nodes", upper_nodes[layer - 1]), ("links", upper_links[layer - 1])):
                name = f"{prefix}_{layer}.npy"
                write_array(directory / name, array)
                files.append(name)
        edges = int((layer0 >= 0).sum()) + sum(int((links >= 0).sum()) for links in upper_links)
        write_json(directory / "manifest.json", {
            "version": HNSW_VERSION, "method": IndexMethod.HNSW.value, "metric": metric.value,
            "m": m, "m0": m0, "ef_construction": ef_construction, "min_ef_search": parameters.min_ef_search,
            "seed": seed, "entry_point": entry, "max_level": top, "store": store.identity,
            "statistics": {"edges": edges, "nodes_per_layer": [size] + [len(n) for n in upper_nodes],
                           "layer0_reachable_from_entry": layer0_reachable(layer0, entry),
                           "construction_distance_evaluations": objective.evaluations},
            "files": {name: sha256_file(directory / name) for name in files}})
        return cls.open(directory, store)

    @classmethod
    def open(cls, directory: Path, store: VectorStore, *, verify: bool = False) -> "HnswIndex":
        """Load the persisted graph; never inserts or rebuilds."""
        directory = Path(directory)
        require_files(directory, ("manifest.json", "levels.npy", "layer0.npy"), "HNSW index")
        manifest = read_json(directory / "manifest.json", "HNSW manifest")
        if manifest.get("version") != HNSW_VERSION or manifest.get("method") != IndexMethod.HNSW.value:
            raise ValidationError("Unsupported HNSW index version")
        if manifest.get("store") != store.identity:
            raise ValidationError("HNSW index was built for a different vector store")
        metric = Metric(manifest["metric"])
        top = manifest["max_level"]
        names = [f"{p}_{layer}.npy" for layer in range(1, top + 1) for p in ("nodes", "links")]
        require_files(directory, names, "HNSW index")
        if verify:
            verify_checksums(directory, manifest["files"], "HNSW index")
        size, m, m0 = store.size, manifest["m"], manifest["m0"]
        graph = _Graph(read_array(directory / "levels.npy", np.int8, (size,)),
                       read_array(directory / "layer0.npy", np.int32, (size, m0)),
                       tuple(read_array(directory / f"nodes_{layer}.npy", np.int32) for layer in range(1, top + 1)),
                       tuple(read_array(directory / f"links_{layer}.npy", np.int32) for layer in range(1, top + 1)),
                       manifest["entry_point"], top)
        _validate_graph(graph, size, m, m0)
        index = object.__new__(cls)
        index._directory = directory
        index._store = store
        index._manifest = manifest
        index._graph = graph
        index._objective = _Objective(store.vectors, metric)
        index._slots = tuple({int(node): slot for slot, node in enumerate(nodes.tolist())}
                             for nodes in graph.upper_nodes)
        index._closed = False
        return index

    @property
    def metric(self) -> Metric:
        return Metric(self._manifest["metric"])

    @property
    def max_level(self) -> int:
        return self._graph.max_level

    @property
    def entry_point(self) -> int:
        return self._graph.entry_point

    @property
    def manifest(self) -> dict:
        return dict(self._manifest)

    def neighbors(self, row: int, layer: int = 0) -> np.ndarray:
        """Vector rows linked to ``row`` on ``layer`` (inspection/tests)."""
        graph = self._graph
        if layer == 0:
            links = graph.layer0[row]
        else:
            links = graph.upper_links[layer - 1][self._slots[layer - 1][row]]
        return links[links >= 0].astype(np.int64)

    def search(self, query, metric: Metric, k: int, *, ef_search: int | None = None) -> VectorSearchResult:
        if self._closed:
            raise ValidationError("HNSW index is closed")
        validate_k(k)
        if metric is not self.metric:
            raise ValidationError(f"This HNSW graph was built for metric {self.metric.value}, "
                                  f"not {getattr(metric, 'value', metric)}")
        ef = default_ef_search(k, HnswParameters(min_ef_search=self._manifest["min_ef_search"])) \
            if ef_search is None else ef_search
        if type(ef) is not int or ef < k:
            raise ValidationError("efSearch must be an integer of at least k")
        q = prepare_query(query, self._store.dimension)
        objective = self._objective.fork()
        prepared = objective.prepare(q)
        size, graph = self._store.size, self._graph
        entry = graph.entry_point
        current = [(float(objective.to_rows(prepared, np.array([entry]))[0]), entry)]
        for layer in range(graph.max_level, 0, -1):
            links, slots = graph.upper_links[layer - 1], self._slots[layer - 1]

            def neighbors_of(row, links=links, slots=slots):
                values = links[slots[row]]
                return values[values >= 0].astype(np.int64)
            current = search_layer(objective, prepared, current, neighbors_of, 1, size)[:1]

        def layer0_of(row):
            values = graph.layer0[row]
            return values[values >= 0].astype(np.int64)
        found = search_layer(objective, prepared, current, layer0_of, ef, size)
        rows = np.array([row for _, row in found], dtype=np.int64)
        scores = self._store.score_rows(rows, q, metric)
        ids, best = merge_top_k(np.empty(0, np.int64), np.empty(0, np.float64), self._store.ids[rows], scores, k)
        expected = min(k, size)
        return VectorSearchResult(to_neighbors(ids, best), objective.evaluations, IndexMethod.HNSW.value, {
            "metric": metric.value, "ef_search": ef, "max_level": graph.max_level,
            "candidates": int(len(rows)), "distance_evaluations": objective.evaluations,
            "shortfall": len(ids) < expected})

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> "HnswIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


__all__ = ["HnswIndex", "layer0_reachable", "search_layer", "select_neighbors"]
