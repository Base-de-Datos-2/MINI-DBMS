"""Execute owner-registered spatial searches inside the SQL lifecycle."""

from engine.operators.base import ExecutionOperator
from engine.operators.rows import RowLayout, RowProvenance


class SpatialScan(ExecutionOperator):
    use_index = False

    def __init__(self, index, relation, center, kind, value, metric, inclusive=False):
        self._index, self._relation, self._center = index, relation, center
        self._kind, self._value, self._metric = kind, value, metric
        self._inclusive = inclusive
        self._stats = None
        self._hits = iter(())
        super().__init__()

    def _build_layout(self):
        return RowLayout(self._index.storage.schema, relation=self._relation)

    def _open(self):
        options = {"metric": self._metric, "use_index": self.use_index}
        if self._kind == "radius":
            options["inclusive"] = self._inclusive
        result = getattr(self._index, self._kind)(self._center, self._value, **options)
        self._hits = iter(result.hits)
        self._stats = result.stats
        self._statistics.rows_examined = result.stats.candidates

    def _next(self):
        hit = next(self._hits, None)
        if hit is None:
            return None
        self._provenance = (RowProvenance(self._relation, hit.rid),)
        return hit.record

    def _close(self):
        self._hits = iter(())

    def _details(self):
        details = [
            ("table", self._index.mapping.table), ("relation", self._relation),
            ("access", "RTree" if self.use_index else "exhaustive"),
            ("search", self._kind), ("value", str(self._value)),
            ("metric", self._metric.value), ("unit", "metres"),
        ]
        if self._stats is not None:
            stats = self._stats
            details.extend((name, str(getattr(stats, name))) for name in
                           ("visited_nodes", "candidates", "base_records_read"))
        return tuple(details)


class SpatialIndexScan(SpatialScan):
    use_index = True
