"""Physical operators for SIMILAR_TO: VectorIndexScan (IVF/HNSW) and VectorScan."""

from engine.operators.base import ExecutionOperator
from engine.operators.rows import RowLayout, RowProvenance
from engine.storage import Record

from .contracts import IndexMethod, Metric


class VectorScan(ExecutionOperator):
    """Exhaustive exact search; the "Usar índices" off path and the oracle."""

    use_index = False

    def __init__(self, relation, access, schema, limit):
        self._relation, self._access, self._schema, self._limit = relation, access, schema, limit
        self._hits = iter(())
        self._search = None
        super().__init__()

    def _build_layout(self):
        return RowLayout(self._schema)

    def _open(self):
        access = self._access
        self._search = access.collection.search(
            access.media_key, Metric(access.metric), access.k,
            method=IndexMethod(access.method), use_index=self.use_index)
        hits = list(zip(self._search.result.neighbors, self._search.rids))
        if self._limit is not None:
            hits = hits[:self._limit]
        self._hits = iter(hits)
        self._statistics.rows_examined = self._search.result.evaluated

    def _next(self):
        item = next(self._hits, None)
        if item is None:
            return None
        neighbor, rid = item
        record = self._relation.storage.read(rid)
        self._provenance = (RowProvenance(self._relation.exposed_name, rid),)
        return Record(self.output_schema, tuple(neighbor.score if field is None else record[field]
                                               for field in self._access.fields))

    def _close(self):
        self._hits = iter(())

    def _details(self):
        access = self._access
        result = [("table", self._relation.metadata.name), ("modality", access.collection.modality.value),
                  ("media_key", access.media_key), ("k", str(access.k)), ("limit", str(self._limit)),
                  ("requested", access.method), ("metric", access.metric),
                  ("score", "-distance" if access.metric == "euclidean" else access.metric),
                  ("model", access.collection.model.fingerprint[:12]),
                  ("collection", access.collection.collection_id), ("generation", access.collection.generation)]
        if self._search is not None:
            search = self._search
            result.append(("executed", search.executed_method))
            result.append(("evaluations", str(search.result.evaluated)))
            # Short keys: the plan panel lays details out in a narrow column.
            short = {"nprobe_requested": "nprobe", "nprobe_effective": "nprobe_used",
                     "centroid_evaluations": "centroids"}
            for name, value in search.result.details.items():
                if name not in ("metric", "distance_evaluations"):
                    result.append((short.get(name, name), str(value)))
            result.append(("extract_ms", f"{search.timings['extract_seconds'] * 1000:.3f}"))
            result.append(("search_ms", f"{search.timings['search_seconds'] * 1000:.3f}"))
        return tuple(result)


class VectorIndexScan(VectorScan):
    use_index = True


__all__ = ["VectorScan", "VectorIndexScan"]
