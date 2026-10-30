"""Lexical TF-IDF/cosine and BM25 over SPIMI or a genuine storage scan.

This is the standalone Block 3 core. Callers borrow the index/storage and
keep the collection unchanged; owner registration, sealing and SQL are 4A/4B.
The candidate accumulator is O(C), independently of a size-k selection heap.
"""

from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import heapq
import math
from sys import getsizeof
from time import perf_counter

from engine.catalog import Column, DataType, Schema
from engine.errors import InsufficientBudgetError, InvalidTypeError, ValidationError
from engine.operators.base import ExecutionOperator
from engine.operators.context import ExecutionContext, cancellation_point
from engine.operators.rows import RowLayout
from engine.operators.sorting import (
    DEFAULT_MAX_FAN_IN, MINIMUM_SORT_BUDGET_BYTES, ExternalSort, SortKey, SortSpec,
)
from engine.operators.temp_files import cleanup_preserving_error
from engine.storage.base import Storage
from engine.storage.record import Record
from engine.storage.rid import RID

from .format import POSTING, checked_payload, integer
from .index import TextIndex
from .tokenizer import tokenize


BM25_K1 = 1.2
BM25_B = 0.75
_ORDERS = {"score_desc", "score_asc", "id_asc", "id_desc"}
_SCORE_SCHEMA = Schema([Column("doc_id", DataType.INTEGER), Column("score", DataType.FLOAT)])


@dataclass(frozen=True, slots=True)
class TextHit:
    doc_id: int
    score: float
    rid: RID


@dataclass(frozen=True, slots=True)
class TextRankingReport:
    model: str
    access: str
    order: str
    limit: int | None
    known_terms: tuple[str, ...]
    query_token_count: int
    query_norm: float | None
    bm25_k1: float | None
    bm25_b: float | None
    postings_read: int
    documents_examined: int
    candidates_scored: int
    rows_returned: int
    selection: str
    peak_heap_entries: int
    accumulator_estimated_bytes: int
    query_estimated_bytes: int
    scan_identity_estimated_bytes: int
    peak_scan_document_estimated_bytes: int
    posting_buffer_bytes: int
    selection_estimated_bytes: int
    result_estimated_bytes: int
    sort_budget_bytes: int
    sort_initial_runs: int
    sort_merge_passes: int
    sort_rows_spilled: int
    sort_bytes_spilled: int
    sort_max_fan_in: int
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class TextSearchResult:
    """Eager ID/score/RID results; no original document texts are materialized."""
    hits: tuple[TextHit, ...]
    report: TextRankingReport


@dataclass(frozen=True, slots=True)
class _TermWeight:
    idf: float
    query_weight: float
    bm25_idf: float


def _prepare(index, query, model):
    tokens = tokenize(query)
    counts = Counter(term for term in tokens if term in index.lexicon)
    weights = {}
    n = index.statistics.document_count
    for term in sorted(counts):
        cancellation_point()
        df = index.lexicon[term].df
        idf = 1 + math.log((n + 1) / (df + 1))
        weights[term] = _TermWeight(idf, (1 + math.log(counts[term])) * idf,
            math.log1p((n - df + 0.5) / (df + 0.5)))
    norm = math.sqrt(math.fsum(w.query_weight * w.query_weight for w in weights.values())) if model == "TF_IDF" else None
    estimated = (getsizeof(tokens) + sum(getsizeof(t) for t in tokens)
        + getsizeof(counts) + sum(getsizeof(t) + getsizeof(tf) for t, tf in counts.items())
        + getsizeof(weights) + sum(getsizeof(t) + getsizeof(w) + 3 * getsizeof(0.0)
                                  for t, w in weights.items()))
    return weights, norm, len(tokens), estimated


def _contribution(weight, tf, document, index, model):
    if model == "TF_IDF":
        return (1 + math.log(tf)) * weight.idf * weight.query_weight
    length_ratio = document.length / index.statistics.average_length
    return (weight.bm25_idf * tf * (BM25_K1 + 1)
        / (tf + BM25_K1 * (1 - BM25_B + BM25_B * length_ratio)))


def _checked_score(score):
    # Tolerances belong only to assertions, never sorting or tie grouping.
    if not math.isfinite(score) or score < 0:
        raise ValidationError("A text score must be finite and nonnegative")
    return score


def _index_scores(index, weights, model, buffer_bytes):
    scores = {}
    postings_read = 0
    for term, weight in weights.items():  # Stable vocabulary order.
        with index.postings(term, buffer_bytes=buffer_bytes) as postings:
            for doc_id, tf in postings:
                cancellation_point()
                postings_read += 1
                document = index.documents[doc_id]
                if document.norm == 0:
                    continue
                contribution = _contribution(weight, tf, document, index, model)
                scores[doc_id] = scores.get(doc_id, 0.0) + contribution
    return scores, postings_read


def _scan_scores(index, storage, weights, model):
    scores = {}
    seen = set()
    peak_document = 0
    with closing(storage.scan()) as rows:
        for rid, record in rows:
            cancellation_point()
            index._require_open()
            payload = checked_payload(index.table, record)
            doc_id = record[index.id_column]
            document = index.documents.get(doc_id)
            if (document is None or doc_id in seen or rid != document.rid
                    or sha256(payload).hexdigest() != document.record_sha256):
                raise ValidationError("TextScan source differs from the indexed collection generation")
            seen.add(doc_id)
            tokens = tokenize(record[index.text_column])
            counts = Counter(tokens)
            peak_document = max(peak_document, getsizeof(payload) + getsizeof(tokens)
                + sum(getsizeof(t) for t in tokens) + getsizeof(counts)
                + sum(getsizeof(t) + getsizeof(tf) for t, tf in counts.items()))
            if document.length != len(tokens):
                raise ValidationError("TextScan token lengths disagree with index statistics")
            if document.norm == 0:
                continue
            score = 0.0
            matched = False
            for term, weight in weights.items():
                if counts[term]:
                    score += _contribution(weight, counts[term], document, index, model)
                    matched = True
            if matched:
                scores[doc_id] = score
    if len(seen) != index.statistics.document_count:
        raise ValidationError("TextScan source count differs from the indexed collection")
    identity_bytes = getsizeof(seen) + sum(getsizeof(doc_id) for doc_id in seen)
    return scores, len(seen), identity_bytes, peak_document


class _ScoreRows(ExecutionOperator):
    """Borrow accumulated scores as narrow rows for the existing ExternalSort."""

    def __init__(self, scores):
        self._scores = scores
        self._cursor = None
        super().__init__()

    def _build_layout(self):
        return RowLayout(_SCORE_SCHEMA)

    def _open(self):
        self._cursor = iter(self._scores.items())

    def _next(self):
        cancellation_point()
        item = next(self._cursor, None)
        if item is None:
            return None
        self._statistics.rows_examined += 1
        return Record(_SCORE_SCHEMA, item)

    def _close(self):
        self._cursor = None


def _heap_select(scores, limit):
    heap = []
    for doc_id, score in scores.items():
        cancellation_point()
        # Root is the WORST retained hit: lower score, then larger document ID.
        item = (score, -doc_id, doc_id)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    estimated = getsizeof(heap) + sum(getsizeof(item) + sum(getsizeof(v) for v in item) for item in heap)
    estimated += 32 * len(heap)  # winner sort/key pointer workspace estimate
    return [(doc_id, score) for score, _, doc_id in sorted(heap, key=lambda item: (-item[0], item[2]))], len(heap), estimated


def _external_select(scores, order, limit, budget, fan_in, context):
    if order in {"score_desc", "score_asc"}:
        spec = SortSpec([SortKey("score", descending=order == "score_desc"), SortKey("doc_id")])
    else:
        spec = SortSpec([SortKey("doc_id", descending=order == "id_desc")])
    sorter = ExternalSort(_ScoreRows(scores), spec, memory_budget_bytes=budget, max_fan_in=fan_in)
    selected = []
    try:
        sorter.open(context)
        while limit is None or len(selected) < limit:
            cancellation_point()
            row = sorter.next()
            if row is None:
                break
            selected.append((row["doc_id"], row["score"]))
    finally:
        cleanup_preserving_error(sorter.close)
    return selected, sorter.metrics


def search_text(index: TextIndex, query: str, *, model: str, order="score_desc", limit=None,
                use_indexes=True, storage: Storage | None = None, buffer_bytes=4096,
                sort_memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
                sort_max_fan_in=DEFAULT_MAX_FAN_IN,
                context: ExecutionContext | None = None) -> TextSearchResult:
    """Rank OR matches using frozen formulas and apply LIMIT after total order.

    Models: TF_IDF, BM25. Orders: score_desc (default), score_asc, id_asc,
    id_desc. Only score_desc with LIMIT uses a heap; all other nonempty routes
    use Stage 6 ExternalSort. ID is retained for ordering regardless of future
    SQL projection. A scan requires the exact unchanged source Storage and
    never reads postings. Both permanent handles are borrowed, never closed.

    Results contain only ID/score/RID. Accumulator, query, selection and result
    sizes are separate estimates, not process RSS or the sort memory grant.
    Cooperative cancellation uses the existing cancellation_scope callback.
    """
    started = perf_counter()
    if not isinstance(index, TextIndex):
        raise InvalidTypeError("search_text requires a TextIndex")
    index._require_open()
    if type(model) is not str or model not in {"TF_IDF", "BM25"}:
        raise ValidationError("Text model must be TF_IDF or BM25")
    if type(order) is not str or order not in _ORDERS:
        raise ValidationError("Unsupported text ranking order")
    if limit is not None:
        integer(limit, "limit")
    if type(use_indexes) is not bool:
        raise InvalidTypeError("use_indexes must be a bool")
    if not use_indexes and not isinstance(storage, Storage):
        raise InvalidTypeError("TextScan requires its source Storage")
    if isinstance(storage, Storage):
        index.require_compatible_storage(storage)
    integer(buffer_bytes, "buffer_bytes", POSTING.size)
    buffer_bytes -= buffer_bytes % POSTING.size
    integer(sort_memory_budget_bytes, "sort_memory_budget_bytes", 1)
    if sort_memory_budget_bytes < MINIMUM_SORT_BUDGET_BYTES:
        raise InsufficientBudgetError("Text result sorting needs the ExternalSort minimum grant")
    integer(sort_max_fan_in, "sort_max_fan_in", 2)
    if context is not None:
        if not isinstance(context, ExecutionContext):
            raise InvalidTypeError("context must be an ExecutionContext")
        if context.closed:
            raise ValidationError("Text execution context is closed")
    cancellation_point()
    weights, query_norm, token_count, query_bytes = _prepare(index, query, model)
    postings_read = examined = identity_bytes = peak_document = 0
    heap_entries = selection_bytes = 0
    sort_metrics = None
    selected = []
    scores = {}
    selection = "empty"
    if (weights and limit != 0 and index.statistics.document_count > 0
            and index.statistics.average_length > 0 and query_norm != 0):
        if use_indexes:
            scores, postings_read = _index_scores(index, weights, model, buffer_bytes)
        else:
            scores, examined, identity_bytes, peak_document = _scan_scores(index, storage, weights, model)
        for doc_id, value in scores.items():
            cancellation_point()
            if model == "TF_IDF":
                value /= index.documents[doc_id].norm * query_norm
            scores[doc_id] = _checked_score(value)
        if scores:
            if order == "score_desc" and limit is not None:
                selection = "TopKHeap"
                selected, heap_entries, selection_bytes = _heap_select(scores, limit)
            else:
                selection = "ExternalSort"
                selected, sort_metrics = _external_select(scores, order, limit,
                    sort_memory_budget_bytes, sort_max_fan_in, context)
    index._require_open()
    cancellation_point()
    hits = tuple(TextHit(doc_id, score, index.documents[doc_id].rid) for doc_id, score in selected)
    accumulator_bytes = getsizeof(scores) + sum(getsizeof(doc_id) + getsizeof(score) for doc_id, score in scores.items())
    selection_bytes += getsizeof(selected) + sum(
        getsizeof(pair) + sum(getsizeof(value) for value in pair) for pair in selected)
    result_bytes = getsizeof(hits) + sum(getsizeof(hit) + getsizeof(hit.score) for hit in hits)
    metrics = sort_metrics
    report = TextRankingReport(
        model, "TextIndexScan" if use_indexes else "TextScan", order, limit,
        tuple(weights), token_count, query_norm,
        BM25_K1 if model == "BM25" else None, BM25_B if model == "BM25" else None,
        postings_read, examined, len(scores), len(hits), selection, heap_entries,
        accumulator_bytes, query_bytes, identity_bytes, peak_document,
        buffer_bytes if postings_read else 0, selection_bytes, result_bytes,
        sort_memory_budget_bytes if metrics is not None else 0,
        0 if metrics is None else metrics.initial_runs,
        0 if metrics is None else metrics.merge_passes,
        0 if metrics is None else metrics.rows_spilled,
        0 if metrics is None else metrics.bytes_spilled,
        0 if metrics is None else metrics.max_fan_in,
        perf_counter() - started,
    )
    return TextSearchResult(hits, report)


__all__ = ["TextHit", "TextRankingReport", "TextSearchResult", "search_text"]
