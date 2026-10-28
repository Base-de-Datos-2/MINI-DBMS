"""Block 3 acceptance against frozen/Decimal oracles and actual access paths."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
import json
import math
from pathlib import Path
import random
import subprocess
import sys
from threading import Barrier
from types import MappingProxyType

import pytest

from engine.catalog import Column, DataType, Schema, TableMetadata
from engine.errors import DatabaseError, ValidationError
from engine.operators import ExecutionContext
from engine.operators.context import cancellation_scope
from engine.operators.sorting import MINIMUM_SORT_BUDGET_BYTES
from engine.storage import HeapFile, Record
from engine.storage.base import Storage
from engine.storage.binary import INTEGER_MAX, INTEGER_MIN
from engine.text import TextIndex, build_spimi, search_text
from tests.text.reference import rank, SCORE_ABS_TOL, SCORE_REL_TOL


FIXTURES = Path(__file__).with_name("fixtures")
COLLECTIONS = json.loads((FIXTURES / "collections.v1.json").read_text(encoding="utf-8"))["collections"]
CASES = json.loads((FIXTURES / "queries.v1.json").read_text(encoding="utf-8"))["cases"]
EXPECTED = json.loads((FIXTURES / "expected.v1.json").read_text(encoding="utf-8"))
WORKED = json.loads((FIXTURES / "worked_example.v1.json").read_text(encoding="utf-8"))
SCHEMA = Schema([Column("id", DataType.INTEGER), Column("contenido", DataType.VARCHAR)])
TABLE = TableMetadata("documentos", SCHEMA)


@contextmanager
def prepared(root, rows):
    with HeapFile.create(root / "source.heap", SCHEMA) as heap:
        for doc_id, text in rows:
            heap.insert(Record(SCHEMA, [doc_id, text]))
        build_spimi(root / "index", heap, TABLE, collection_id="ranking-test",
            memory_budget_bytes=4096, merge_fan_in=2, io_buffer_bytes=16)
        with TextIndex.open(root / "index", buffer_bytes=16) as index:
            yield heap, index


@pytest.fixture(scope="module")
def collections(tmp_path_factory):
    with ExitStack() as stack:
        result = {}
        for key, fixture in COLLECTIONS.items():
            root = tmp_path_factory.mktemp(f"rank-{key}")
            table = TableMetadata(key, Schema([Column("id", DataType.INTEGER),
                Column(fixture["text_column"], DataType.VARCHAR)]))
            heap = stack.enter_context(HeapFile.create(root / "source.heap", table.schema))
            for doc in fixture["documents"]:
                heap.insert(Record(table.schema, [doc["id"], doc["text"]]))
            build_spimi(root / "index", heap, table, collection_id=key, text_column=fixture["text_column"],
                memory_budget_bytes=2048, merge_fan_in=2)
            index = stack.enter_context(TextIndex.open(root / "index", buffer_bytes=16))
            result[key] = heap, index
        yield result


def assert_matches(actual, expected):
    assert [hit.doc_id for hit in actual.hits] == [doc_id for doc_id, score in expected]
    assert [hit.score for hit in actual.hits] == pytest.approx(
        [float(score) for doc_id, score in expected], rel=SCORE_REL_TOL, abs=SCORE_ABS_TOL)
    assert all(math.isfinite(hit.score) and hit.score >= 0 for hit in actual.hits)


@pytest.mark.parametrize("use_indexes", [True, False], ids=["index", "scan"])
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_all_frozen_queries_match_exact_ids_order_and_scores(collections, case, use_indexes):
    heap, index = collections[case["collection"]]
    result = search_text(index, case["text"], model=case["model"], order=case["order"],
        limit=case["limit"], use_indexes=use_indexes, storage=heap, buffer_bytes=16)
    expected = [(row["id"], row["score"]) for row in EXPECTED["queries"][case["id"]]]
    assert_matches(result, expected)
    assert result.report.access == ("TextIndexScan" if use_indexes else "TextScan")
    assert result.report.rows_returned == len(expected)
    assert all(hit.rid == index.documents[hit.doc_id].rid for hit in result.hits)
    if expected:
        assert result.report.selection == ("TopKHeap" if case["order"] == "score_desc" and case["limit"] is not None else "ExternalSort")


@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
@pytest.mark.parametrize("order", ["score_desc", "score_asc", "id_asc", "id_desc"])
@pytest.mark.parametrize("limit", [None, 0, 1, 4, 1000])
def test_all_orders_and_limits_index_scan_and_decimal_oracle_agree(collections, model, order, limit):
    heap, index = collections["documentos"]
    expected = rank(COLLECTIONS["documentos"]["documents"], ["base", "datos"], model, order, limit)
    indexed = search_text(index, "base datos", model=model, order=order, limit=limit)
    scanned = search_text(index, "base datos", model=model, order=order, limit=limit,
        use_indexes=False, storage=heap)
    assert_matches(indexed, expected)
    assert_matches(scanned, expected)
    assert indexed.hits == scanned.hits  # Same stable arithmetic, not just similar ranks.
    if indexed.hits and order == "score_desc" and limit is not None:
        assert indexed.report.peak_heap_entries <= limit
        assert indexed.report.sort_initial_runs == 0
    elif indexed.hits:
        assert indexed.report.peak_heap_entries == 0
        assert indexed.report.sort_initial_runs > 0


@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
def test_worked_scores_follow_analytic_anchors_and_complete_document_norm(tmp_path, model):
    with prepared(tmp_path, [(d["id"], d["text"]) for d in WORKED["documents"]]) as (heap, index):
        result = search_text(index, "base datos", model=model)
        expected = {"TF_IDF": [(30, 0.96843882194433620), (7, 0.70710678118654752), (11, 0.43779123108611478)],
            "BM25": [(30, 1.2357761692752447), (7, 0.80259147222730510), (11, 0.60996951889275187)]}[model]
        assert_matches(result, expected)
        assert result.report.candidates_scored == 3
        assert result.report.known_terms == ("base", "datos")
        if model == "TF_IDF":
            # ID 11's unqueried índice weight must remain in its full norm.
            assert result.hits[-1].score < 0.5
        else:
            assert (result.report.bm25_k1, result.report.bm25_b) == (1.2, 0.75)


@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
def test_query_repetition_and_oov_projection_are_model_specific(collections, model):
    _, index = collections["documentos"]
    baseline = search_text(index, "base datos", model=model)
    unknown = search_text(index, "BASE datos desconocidozz", model=model)
    repeated = search_text(index, "base base datos", model=model)
    assert baseline.hits == unknown.hits
    assert baseline.report.query_norm == unknown.report.query_norm
    if model == "BM25":
        assert baseline.hits == repeated.hits
    else:
        assert baseline.hits != repeated.hits
        assert baseline.report.query_norm != repeated.report.query_norm


@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
def test_default_order_and_topk_respect_exact_ties_and_signed_id_extremes(tmp_path, model):
    identifiers = [INTEGER_MAX, 45, 3, INTEGER_MIN, -5]
    with prepared(tmp_path, [(i, "base datos") for i in identifiers]) as (heap, index):
        result = search_text(index, "base", model=model, limit=3)
        assert [hit.doc_id for hit in result.hits] == [INTEGER_MIN, -5, 3]
        assert len(set(hit.score for hit in result.hits)) == 1
        full = search_text(index, "base", model=model)
        assert [hit.doc_id for hit in full.hits] == sorted(identifiers)
        assert full.hits[:3] == result.hits


@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
def test_order_is_resolved_before_limit_before_and_after_reopening(tmp_path, model):
    rows = [(3, "a z z z"), (1, "a " + "z " * 15), (2, "a a a")]
    expected = {"score_desc": 2, "score_asc": 1, "id_asc": 1, "id_desc": 3}
    with prepared(tmp_path, rows) as (heap, index):
        for order, winner in expected.items():
            for use_indexes in (True, False):
                result = search_text(index, "a", model=model, order=order, limit=1,
                    use_indexes=use_indexes, storage=heap)
                assert [hit.doc_id for hit in result.hits] == [winner]
    with TextIndex.open(tmp_path / "index") as index:
        with HeapFile.open(tmp_path / "source.heap", index.table.schema) as heap:
            for order, winner in expected.items():
                for use_indexes in (True, False):
                    result = search_text(index, "a", model=model, order=order, limit=1,
                        use_indexes=use_indexes, storage=heap)
                    assert [hit.doc_id for hit in result.hits] == [winner]


def test_literal_three_score_counterexample_and_no_tolerance_tie_grouping():
    from engine.text.ranking import _external_select, _heap_select
    scores = {1: 0.2, 2: 0.9, 3: 0.5}
    heap_hits, _, _ = _heap_select(scores, 1)
    assert heap_hits == [(2, 0.9)]
    for order, winner in (("score_asc", 1), ("id_asc", 1), ("id_desc", 3)):
        selected, _ = _external_select(scores, order, 1, MINIMUM_SORT_BUDGET_BYTES, 2, None)
        assert selected[0][0] == winner
    # Assertion tolerances must never collapse nearby, unequal scores to an ID tie.
    close_scores = {1: 0.5, 2: 0.5 + 1e-13}
    assert _heap_select(close_scores, 1)[0][0][0] == 2
    selected, _ = _external_select(close_scores, "score_desc", None, MINIMUM_SORT_BUDGET_BYTES, 2, None)
    assert [doc_id for doc_id, score in selected] == [2, 1]


@pytest.mark.parametrize("seed", [41, 20261028])
@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
def test_seeded_shuffled_corpus_matches_independent_decimal_oracle(tmp_path, seed, model):
    rng = random.Random(seed)
    documents = [{"id": i - 10, "tokens": [rng.choice(["a", "b", "c", "d"]) for _ in range(rng.randrange(9))]}
                 for i in range(25)]
    # Distinct off-query components avoid proportional-vector ties whose last
    # Decimal digit depends on finite-precision cancellation. Exact ties and
    # unequal float scores separated by 1e-13 have dedicated assertions above.
    for i, document in enumerate(documents):
        document["tokens"].extend([f"unique{i}"] * (i + 1))
    rng.shuffle(documents)
    with prepared(tmp_path, [(d["id"], " ".join(d["tokens"])) for d in documents]) as (heap, index):
        for order in ("score_desc", "score_asc", "id_asc", "id_desc"):
            expected = rank(documents, ["a", "c", "a", "oov"], model, order, 7)
            for use_indexes in (True, False):
                result = search_text(index, "a c a oov", model=model, order=order, limit=7,
                    use_indexes=use_indexes, storage=heap, buffer_bytes=16)
                assert_matches(result, expected)


@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
@pytest.mark.parametrize("rows", [[], [(9, ""), (4, "... ¿?!")]])
def test_empty_and_tokenless_collections_return_no_artificial_zero_matches(tmp_path, model, rows):
    with prepared(tmp_path, rows) as (heap, index):
        for query in ("", "...", "unknown"):
            for use_indexes in (True, False):
                result = search_text(index, query, model=model, use_indexes=use_indexes, storage=heap)
                assert result.hits == ()
                assert result.report.candidates_scored == result.report.postings_read == result.report.documents_examined == 0
                assert result.report.selection == "empty"


class ScanSpy(Storage):
    def __init__(self, heap):
        self.heap = heap
        self.scans = 0
        self.closed_scans = 0
        self.reads = 0

    def scan(self):
        self.scans += 1
        cursor = self.heap.scan()
        try:
            yield from cursor
        finally:
            cursor.close()
            self.closed_scans += 1

    def read(self, rid):
        self.reads += 1
        return self.heap.read(rid)

    def insert(self, record):
        raise AssertionError("ranker cannot mutate source")

    def delete(self, rid):
        raise AssertionError("ranker cannot mutate source")


def test_scan_does_not_consult_postings_and_examined_counters_are_real(collections, monkeypatch):
    heap, index = collections["documentos"]
    def forbidden(*args, **kwargs):
        raise AssertionError("scan cannot find candidates from postings")
    monkeypatch.setattr(index, "postings", forbidden)
    storage = ScanSpy(heap)
    result = search_text(index, "base datos", model="BM25", use_indexes=False, storage=storage, limit=2)
    assert storage.scans == storage.closed_scans == 1 and storage.reads == 0
    assert result.report.documents_examined == 16
    assert result.report.postings_read == result.report.posting_buffer_bytes == 0
    assert result.report.scan_identity_estimated_bytes > 0
    assert result.report.peak_scan_document_estimated_bytes > 0


def test_index_uses_only_known_query_postings_and_memory_report_keeps_accumulator(collections, monkeypatch):
    heap, index = collections["documentos"]
    called = []
    original = index.postings
    def postings(term, **kwargs):
        called.append(term)
        return original(term, **kwargs)
    monkeypatch.setattr(index, "postings", postings)
    storage = ScanSpy(heap)
    result = search_text(index, "DATOS base oov base", model="TF_IDF", limit=1,
        storage=storage, buffer_bytes=17)
    assert called == ["base", "datos"]
    assert storage.scans == storage.reads == 0
    report = result.report
    assert report.postings_read == index.lexicon["base"].df + index.lexicon["datos"].df
    assert report.documents_examined == 0 and report.posting_buffer_bytes == 16
    assert report.candidates_scored > report.rows_returned == report.peak_heap_entries == 1
    assert report.accumulator_estimated_bytes > report.result_estimated_bytes > 0
    assert report.query_estimated_bytes > 0 and report.selection_estimated_bytes > 0


@pytest.mark.parametrize("change", ["text", "count"])
def test_scan_detects_changed_storage_without_pretending_to_seal_it(tmp_path, change):
    with prepared(tmp_path, [(1, "a"), (2, "b")]) as (heap, index):
        if change == "text":
            rid = index.documents[1].rid
            heap.delete(rid)
            heap.insert(Record(SCHEMA, [1, "cambiado"]))
        else:
            heap.insert(Record(SCHEMA, [3, "a"]))
        with pytest.raises(ValidationError, match="generation"):
            search_text(index, "a", model="BM25", use_indexes=False, storage=heap)


@pytest.mark.parametrize("options", [
    {"model": "unknown"}, {"model": None}, {"order": "unknown"}, {"order": []},
    {"limit": -1}, {"limit": True}, {"limit": 1.5}, {"use_indexes": 1},
    {"use_indexes": False}, {"buffer_bytes": 0}, {"buffer_bytes": True},
    {"sort_memory_budget_bytes": 1}, {"sort_max_fan_in": 1}, {"context": object()},
])
def test_invalid_requests_are_domain_errors_without_closing_borrowed_handles(collections, options):
    heap, index = collections["documentos"]
    with pytest.raises(DatabaseError):
        search_text(index, "base", **{"model": "BM25", **options})
    assert list(index.postings("base")) and heap.record_count == 16


@pytest.mark.parametrize("query", [None, b"a", 1])
def test_query_requires_text(collections, query):
    _, index = collections["documentos"]
    with pytest.raises(DatabaseError):
        search_text(index, query, model="BM25")


def test_closed_index_or_context_are_controlled(tmp_path):
    with prepared(tmp_path, [(1, "a")]) as (heap, index):
        context = ExecutionContext()
        context.close()
        with pytest.raises(ValidationError, match="context is closed"):
            search_text(index, "a", model="BM25", context=context)
        index.close()
        with pytest.raises(ValidationError, match="index is closed"):
            search_text(index, "a", model="BM25")
        assert heap.record_count == 1


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1])
def test_nonfinite_and_negative_scores_cannot_enter_heap_or_sort(collections, monkeypatch, score):
    from engine.text import ranking
    _, index = collections["documentos"]
    monkeypatch.setattr(ranking, "_contribution", lambda *args: score)
    for limit in (1, None):
        with pytest.raises(ValidationError, match="score must be finite"):
            search_text(index, "base", model="BM25", limit=limit)


def test_zero_document_norm_never_produces_a_match(collections, monkeypatch):
    _, index = collections["documentos"]
    zero = index.documents[90]  # A valid tokenless DocumentEntry, shared under base IDs for this guard test.
    mapping = {doc_id: zero for doc_id in index.documents}
    monkeypatch.setattr(index, "documents", MappingProxyType(mapping))
    assert search_text(index, "base", model="TF_IDF", limit=1).hits == ()


def test_fresh_process_preserves_scores_ids_rids_and_all_order_routes(tmp_path):
    rows = [(3, "a z z z"), (1, "a " + "z " * 15), (2, "a a a")]
    with prepared(tmp_path, rows):
        pass
    script = """
import json, sys
from engine.text import TextIndex, search_text
from engine.storage import HeapFile
out = []
with TextIndex.open(sys.argv[1]) as index:
    with HeapFile.open(sys.argv[2], index.table.schema) as heap:
        for model in ('TF_IDF', 'BM25'):
            for order in ('score_desc', 'score_asc', 'id_asc', 'id_desc'):
                indexed = search_text(index, 'a', model=model, order=order, limit=1)
                scanned = search_text(index, 'a', model=model, order=order, limit=1, use_indexes=False, storage=heap)
                assert indexed.hits == scanned.hits
                out.append([model, order, indexed.hits[0].doc_id, indexed.hits[0].score])
print(json.dumps(out))
"""
    process = subprocess.run([sys.executable, "-I", "-B", "-c", script,
        str(tmp_path / "index"), str(tmp_path / "source.heap")], cwd=tmp_path,
        capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    results = json.loads(process.stdout)
    assert [row[2] for row in results] == [2, 1, 1, 3] * 2
    assert all(math.isfinite(row[3]) for row in results)


@pytest.fixture(scope="module")
def many_matches(tmp_path_factory):
    root = tmp_path_factory.mktemp("ranking-many")
    with prepared(root, [(i, f"común grupo{i % 5}") for i in range(799, -1, -1)]) as pair:
        yield pair


def capture_workspaces(monkeypatch, tmp_path):
    from engine.operators import sorting
    original = sorting.TemporaryWorkspace
    paths = []
    def workspace(**options):
        created = original(parent_directory=tmp_path, **options)
        paths.append(created.directory)
        return created
    monkeypatch.setattr(sorting, "TemporaryWorkspace", workspace)
    return paths


def test_other_orders_spill_all_candidates_before_limit_and_release_sort_resources(many_matches, monkeypatch, tmp_path):
    heap, index = many_matches
    paths = capture_workspaces(monkeypatch, tmp_path)
    context = ExecutionContext(memory_budget_bytes=2 * MINIMUM_SORT_BUDGET_BYTES)
    try:
        result = search_text(index, "común", model="BM25", order="id_desc", limit=3,
            sort_memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES, sort_max_fan_in=2, context=context)
        assert [hit.doc_id for hit in result.hits] == [799, 798, 797]
        report = result.report
        assert report.selection == "ExternalSort" and report.peak_heap_entries == 0
        assert report.candidates_scored == 800
        assert report.sort_initial_runs > 2 and report.sort_merge_passes > 1
        assert report.sort_rows_spilled >= 800 and report.sort_bytes_spilled > 0
        assert report.sort_max_fan_in == 2
        assert report.accumulator_estimated_bytes > report.sort_budget_bytes
        assert context.reserved_bytes == context.open_handle_count == 0
        assert context.statistics.peak_live_temporary_bytes > 0
        assert paths and all(not path.exists() for path in paths)
        assert not context.closed and heap.record_count == 800
    finally:
        context.close()


class Cancelled(RuntimeError):
    pass


def test_cancelled_posting_iteration_closes_only_its_buffer(collections, monkeypatch):
    _, index = collections["documentos"]
    original = index.postings
    observers = []
    state = {"cancel": False}
    class Observed:
        def __init__(self, term, **options):
            self.iterator = original(term, **options)
            self.closed = False
            self.count = 0
            observers.append(self)
        def __iter__(self):
            return self
        def __next__(self):
            item = next(self.iterator)
            self.count += 1
            if self.count == 2:
                state["cancel"] = True
            return item
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            self.iterator.close()
            self.closed = True
    monkeypatch.setattr(index, "postings", Observed)
    def check():
        if state["cancel"]:
            raise Cancelled("cancel during posting read")
    with cancellation_scope(check), pytest.raises(Cancelled):
        search_text(index, "base datos", model="TF_IDF", limit=1, buffer_bytes=16)
    assert observers and all(reader.closed for reader in observers)
    monkeypatch.setattr(index, "postings", original)
    assert search_text(index, "base", model="BM25", limit=1).hits


def test_cancelled_scan_closes_cursor_and_preserves_borrowed_storage(collections):
    heap, index = collections["documentos"]
    state = {"cancel": False}
    class CancelScan(ScanSpy):
        def scan(self):
            rows = super().scan()
            try:
                for item in rows:
                    state["cancel"] = True
                    yield item
            finally:
                rows.close()
    storage = CancelScan(heap)
    def check():
        if state["cancel"]:
            raise Cancelled("cancel during scan")
    with cancellation_scope(check), pytest.raises(Cancelled):
        search_text(index, "base", model="BM25", use_indexes=False, storage=storage)
    assert storage.scans == storage.closed_scans == 1
    assert heap.record_count == 16


@pytest.mark.parametrize("failure", ["cancel", "write"])
def test_sort_failure_or_cancellation_cleans_workspaces_and_context(many_matches, monkeypatch, tmp_path, failure):
    from engine.text import ranking
    from engine.operators import sorting
    heap, index = many_matches
    paths = capture_workspaces(monkeypatch, tmp_path)
    context = ExecutionContext(memory_budget_bytes=2 * MINIMUM_SORT_BUDGET_BYTES)
    state = {"cancel": False, "calls": 0}
    if failure == "cancel":
        original = ranking._ScoreRows._next
        def next_row(source):
            state["calls"] += 1
            if state["calls"] == 10:
                state["cancel"] = True
            return original(source)
        monkeypatch.setattr(ranking._ScoreRows, "_next", next_row)
    else:
        original = sorting.TemporaryRowWriter.write
        def write(writer, record):
            state["calls"] += 1
            if state["calls"] == 10:
                raise OSError("injected sort write failure")
            return original(writer, record)
        monkeypatch.setattr(sorting.TemporaryRowWriter, "write", write)
    def check():
        if state["cancel"]:
            raise Cancelled("cancel during external sort")
    try:
        with cancellation_scope(check), pytest.raises(Cancelled if failure == "cancel" else OSError):
            search_text(index, "común", model="BM25", order="id_asc", limit=1, context=context)
        assert context.reserved_bytes == context.open_handle_count == 0
        assert paths and all(not path.exists() for path in paths)
        assert not context.closed and heap.record_count == 800
        assert list(index.postings("común"))
    finally:
        context.close()


@pytest.mark.parametrize("model", ["TF_IDF", "BM25"])
def test_two_queries_share_reader_with_partially_shared_lists_and_serial_equivalence(tmp_path, monkeypatch, model):
    with prepared(tmp_path, [(i, "común uno dos") for i in range(24)]) as (heap, index):
        serial = {query: search_text(index, query, model=model, limit=7).hits
                  for query in ("común uno", "común dos")}
        barrier = Barrier(2)
        original = index.postings
        class Interleaved:
            def __init__(self, term, **options):
                self.iterator = original(term, **options)
            def __iter__(self):
                return self
            def __next__(self):
                item = next(self.iterator)
                barrier.wait(timeout=10)
                return item
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                self.iterator.close()
        monkeypatch.setattr(index, "postings", Interleaved)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {query: pool.submit(search_text, index, query, model=model, limit=7, buffer_bytes=16)
                       for query in serial}
            for query in serial:
                assert pending[query].result(timeout=20).hits == serial[query]
        monkeypatch.setattr(index, "postings", original)
        assert heap.record_count == 24 and list(index.postings("común"))
