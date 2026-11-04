"""Native textual physical operators borrowing owner-managed Heap/SPIMI files."""
from dataclasses import asdict
from engine.operators.base import ExecutionOperator
from engine.operators.rows import RowLayout, RowProvenance
from engine.operators.sorting import MINIMUM_SORT_BUDGET_BYTES
from engine.storage import Record
from .ranking import search_text


class TextScan(ExecutionOperator):
    use_index = False

    def __init__(self, relation, access, schema, limit, options):
        self._relation, self._access = relation, access
        self._schema, self._limit, self._options = schema, limit, options
        self._hits = iter(())
        self._report = None
        super().__init__()

    def _build_layout(self):
        return RowLayout(self._schema)

    def _open(self):
        access = self._access
        result = search_text(access.index, access.query, model=access.model, order=access.order,
            limit=self._limit, use_indexes=self.use_index, storage=self._relation.storage,
            sort_memory_budget_bytes=self._options.sort_memory_budget_bytes or MINIMUM_SORT_BUDGET_BYTES,
            sort_max_fan_in=self._options.sort_max_fan_in, context=self.context)
        self._report = result.report
        self._hits = iter(result.hits)
        self._statistics.rows_examined = result.report.candidates_scored

    def _next(self):
        hit = next(self._hits, None)
        if hit is None:
            return None
        record = self._relation.storage.read(hit.rid)
        self._provenance = (RowProvenance(self._relation.exposed_name, hit.rid),)
        return Record(self.output_schema, tuple(hit.score if field is None else record[field]
                                               for field in self._access.fields))

    def _close(self):
        self._hits = iter(())

    def _details(self):
        access = self._access
        result = [('table', self._relation.metadata.name), ('column', access.column),
                  ('model', access.model), ('order', access.order), ('limit', str(self._limit)),
                  ('collection', access.index.collection_id), ('generation', access.index.generation)]
        if self.use_index:
            result.append(('index_name', f'{self._relation.metadata.name}_spimi'))
        if self._report is not None:
            result.extend((name, str(value)) for name, value in asdict(self._report).items())
        return tuple(result)


class TextIndexScan(TextScan):
    use_index = True
