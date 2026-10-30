"""Block 2: external construction, independent oracles and reader lifecycles."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import random
import subprocess
import sys
from threading import Barrier

import pytest

from engine.catalog import Column, ColumnConstraint, DataType, Schema, TableMetadata
from engine.errors import DatabaseError, DuplicateError, InsufficientBudgetError, ValidationError
from engine.storage import HeapFile, Record, RID
from engine.storage.base import Storage
from engine.storage.binary import INTEGER_MAX, INTEGER_MIN
from engine.text import TextIndex, build_spimi
from engine.text.format import HEADER, POSTING, file_receipt, json_bytes
from tests.text.reference import collection_statistics


SCHEMA = Schema([Column("id", DataType.INTEGER), Column("contenido", DataType.VARCHAR)])
TABLE = TableMetadata("documentos", SCHEMA)
FIXTURES = json.loads((Path(__file__).with_name("fixtures") / "collections.v1.json").read_text(encoding="utf-8"))["collections"]


@contextmanager
def source(tmp_path, rows, table=TABLE):
    with HeapFile.create(tmp_path / "source.heap", table.schema) as heap:
        rids = {}
        for doc_id, text in rows:
            rids[doc_id] = heap.insert(Record(table.schema, [doc_id, text]))
        yield heap, rids


def build(tmp_path, heap, **options):
    return build_spimi(tmp_path / "index", heap, TABLE, collection_id="test-collection", **options)


def rewrite_receipts(directory):
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {filename: file_receipt(directory / filename) for filename in manifest["files"]}
    manifest_path.write_bytes(json_bytes(manifest))


def edit_manifest(directory, edit):
    path = directory / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    edit(manifest)
    path.write_bytes(json_bytes(manifest))


@pytest.mark.parametrize("collection_name", ["documentos", "articulos"])
def test_fixture_postings_dimensions_full_norms_and_rids_match_independent_oracle(tmp_path, collection_name):
    fixture = FIXTURES[collection_name]
    table = TableMetadata(collection_name, Schema([
        Column("id", DataType.INTEGER), Column(fixture["text_column"], DataType.VARCHAR),
    ]))
    documents = fixture["documents"]
    oracle = collection_statistics(documents)  # Frozen tokens, 60-digit Decimal; no index/tokenizer.
    with source(tmp_path, [(d["id"], d["text"]) for d in documents], table) as (heap, rids):
        before = list(heap.scan())
        report = build_spimi(tmp_path / "index", heap, table, collection_id="fixture",
            text_column=fixture["text_column"], memory_budget_bytes=2048, merge_fan_in=2, io_buffer_bytes=16)
        assert report.initial_blocks > 2 and report.merge_passes > 1
        assert report.peak_open_runs <= 2
        assert report.peak_block_estimated_bytes <= report.memory_budget_bytes
        assert report.metadata_estimated_bytes > 0
        assert report.peak_document_estimated_bytes > 0
        assert list(heap.scan()) == before
        with TextIndex.open(tmp_path / "index", collection_id="fixture", generation=report.generation, table=table) as index:
            index.validate()
            index.verify_storage(heap)
            assert index.table == table
            assert index.statistics.document_count == len(documents)
            assert index.statistics.total_tokens == oracle["total_tokens"]
            assert index.statistics.average_length == float(oracle["avgdl"])
            assert list(index.lexicon) == sorted(oracle["df"])
            vectors = {d["id"]: {} for d in documents}
            for dimension, (term, entry) in enumerate(index.lexicon.items()):
                assert entry.dimension == dimension
                assert entry.df == oracle["df"][term]
                expected = sorted((doc_id, counts[term]) for doc_id, counts in oracle["frequencies"].items() if counts[term])
                assert list(index.postings(term, buffer_bytes=16)) == expected
                for doc_id, tf in index.postings(term):
                    vectors[doc_id][term] = tf
            for doc_id, document in index.documents.items():
                assert vectors[doc_id] == oracle["frequencies"][doc_id]
                assert document.rid == rids[doc_id]
                assert document.length == oracle["lengths"][doc_id]
                assert document.norm == pytest.approx(float(oracle["norms"][doc_id]), rel=1e-10, abs=1e-12)
                assert heap.read(document.rid)["id"] == doc_id
            assert list(index.postings("términoausente")) == []
            assert index.build_report == asdict(report)
    assert {p.name for p in (tmp_path / "index").iterdir()} == {"manifest.json", "postings.bin", "documents.jsonl", "lexicon.jsonl"}


@pytest.mark.parametrize("seed", [7, 41, 20261028])
def test_random_input_signed_ids_many_passes_and_high_df_lists(tmp_path, seed):
    identifiers = list(range(-30, 40)) + [INTEGER_MIN, INTEGER_MAX]
    random.Random(seed).shuffle(identifiers)
    rows = [(doc_id, "común " * (1 + i % 4) + f"grupo{i % 5}") for i, doc_id in enumerate(identifiers)]
    expected = {}
    for i, doc_id in enumerate(identifiers):
        expected.setdefault("común", []).append((doc_id, 1 + i % 4))
        expected.setdefault(f"grupo{i % 5}", []).append((doc_id, 1))
    with source(tmp_path, rows) as (heap, _):
        report = build(tmp_path, heap, memory_budget_bytes=1800, merge_fan_in=2, io_buffer_bytes=16)
        assert report.initial_blocks > 30
        assert report.merge_passes >= 5
        with TextIndex.open(tmp_path / "index", buffer_bytes=16) as index:
            index.validate()
            for term in expected:
                assert list(index.postings(term)) == sorted(expected[term])


@pytest.mark.parametrize("rows", [[], [(4, ""), (-3, "... ¿?!")]])
def test_empty_and_tokenless_collections_persist_explicit_zero_statistics(tmp_path, rows):
    with source(tmp_path, rows) as (heap, _):
        report = build(tmp_path, heap)
        assert report.initial_blocks == report.merge_passes == report.posting_count == 0
        with TextIndex.open(tmp_path / "index") as index:
            index.validate()
            index.verify_storage(heap)
            assert index.statistics.document_count == len(rows)
            assert index.statistics.average_length == 0.0
            assert index.statistics.total_tokens == index.statistics.vocabulary_size == 0
            assert index.lexicon == {}
            assert all(d.norm == d.length == 0 for d in index.documents.values())
            assert list(index.postings("nada")) == []


@pytest.mark.parametrize("rows", [
    [(7, "base"), (7, "datos")],
    [(7, ""), (8, "base datos índice " * 12), (7, "")],
    [(7, "base datos " * 15), (8, "otro texto"), (7, "...")],
])
def test_duplicate_ids_even_tokenless_and_across_blocks_never_publish(tmp_path, rows):
    with source(tmp_path, rows) as (heap, _):
        before = list(heap.scan())
        with pytest.raises(DuplicateError, match="Duplicate document ID"):
            build(tmp_path, heap, memory_budget_bytes=1200, merge_fan_in=2)
        assert not (tmp_path / "index").exists()
        assert list(heap.scan()) == before


@pytest.mark.parametrize("option,value", [
    ("memory_budget_bytes", 1), ("memory_budget_bytes", 0), ("memory_budget_bytes", True),
    ("merge_fan_in", 1), ("merge_fan_in", True), ("io_buffer_bytes", 15), ("io_buffer_bytes", False),
])
def test_invalid_or_insufficient_budgets_leave_no_generation(tmp_path, option, value):
    with source(tmp_path, [(1, "texto")]) as (heap, _):
        with pytest.raises(ValidationError if value is not True and value is not False else TypeError):
            build(tmp_path, heap, **{option: value})
        assert not (tmp_path / "index").exists()
        assert heap.record_count == 1


def test_existing_destination_is_preserved(tmp_path):
    destination = tmp_path / "index"
    destination.mkdir()
    (destination / "keep").write_bytes(b"original")
    with source(tmp_path, [(1, "texto")]) as (heap, _):
        with pytest.raises(FileExistsError):
            build(tmp_path, heap)
    assert (destination / "keep").read_bytes() == b"original"


def test_stored_rows_must_respect_declared_schema_constraints(tmp_path):
    table = TableMetadata("documentos", SCHEMA, (ColumnConstraint("contenido", varchar_length=3),))
    with source(tmp_path, [(1, "demasiado")]) as (heap, _):
        with pytest.raises(ValidationError, match="VARCHAR"):
            build_spimi(tmp_path / "index", heap, table, collection_id="constraint")
        assert not (tmp_path / "index").exists()


@pytest.mark.parametrize("phase", ["_write_block", "_merge_runs", "_finish"])
def test_injected_build_io_failure_cleans_runs_and_keeps_borrowed_heap(tmp_path, monkeypatch, phase):
    from engine.text import spimi
    def fail(*args):
        raise OSError("injected SPIMI failure")
    monkeypatch.setattr(spimi, phase, fail)
    with source(tmp_path, [(i, "base datos índice") for i in range(8)]) as (heap, _):
        with pytest.raises(OSError, match="injected"):
            build(tmp_path, heap, memory_budget_bytes=1200, merge_fan_in=2)
        assert not (tmp_path / "index").exists()
        assert heap.record_count == 8
        assert len(list(heap.scan())) == 8


def test_publication_failure_does_not_leave_a_complete_manifest(tmp_path, monkeypatch):
    original = Path.replace
    def fail_last(path, destination):
        if path.name == "manifest.json":
            raise OSError("injected publication failure")
        return original(path, destination)
    monkeypatch.setattr(Path, "replace", fail_last)
    with source(tmp_path, [(1, "texto")]) as (heap, _):
        with pytest.raises(OSError, match="publication"):
            build(tmp_path, heap)
        assert not (tmp_path / "index").exists()


def test_fresh_isolated_process_restores_schema_dimensions_norms_and_heap_mapping(tmp_path):
    rows = [(42, "Base datos datos"), (-1, ""), (7, "cafe\u0301 café")]
    with source(tmp_path, rows) as (heap, _):
        report = build(tmp_path, heap, memory_budget_bytes=1800, merge_fan_in=2)
    script = """
import json, sys
from engine.text import TextIndex
from engine.storage import HeapFile
with TextIndex.open(sys.argv[1], collection_id='test-collection', generation=sys.argv[3]) as index:
    with HeapFile.open(sys.argv[2], index.table.schema) as heap:
        index.validate()
        index.verify_storage(heap)
        print(json.dumps({'N': index.statistics.document_count,
            'postings': list(index.postings('datos')), 'cafe': list(index.postings('café')),
            'lengths': {k: v.length for k, v in index.documents.items()},
            'tokens': [c.name for c in index.table.schema]}))
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script,
        str(tmp_path / "index"), str(tmp_path / "source.heap"), report.generation],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"N": 3, "postings": [[42, 2]], "cafe": [[7, 2]],
        "lengths": {"-1": 0, "7": 2, "42": 3}, "tokens": ["id", "contenido"]}


@pytest.mark.parametrize("key,value", [("collection_id", "other"), ("generation", "other"),
    ("table", TableMetadata("other", SCHEMA))])
def test_open_rejects_wrong_collection_generation_or_table(tmp_path, key, value):
    with source(tmp_path, [(1, "texto")]) as (heap, _):
        build(tmp_path, heap)
    with pytest.raises(ValidationError, match="different collection"):
        TextIndex.open(tmp_path / "index", **{key: value})


@pytest.mark.parametrize("component", ["manifest.json", "postings.bin", "lexicon.jsonl", "documents.jsonl"])
def test_missing_or_partial_components_fail_closed(tmp_path, component):
    with source(tmp_path, [(1, "texto")]) as (heap, _):
        build(tmp_path, heap)
    (tmp_path / "index" / component).unlink()
    with pytest.raises(ValidationError):
        TextIndex.open(tmp_path / "index")


@pytest.mark.parametrize("change", [
    lambda m: m.update(version=999), lambda m: m.update(version=True),
    lambda m: m.update(state="building"),
    lambda m: m["tokenizer"].update(algorithm="changed"),
    lambda m: m["tokenizer"].update(unicode_version="changed"),
    lambda m: m["statistics"].update(N=2),
    lambda m: m["statistics"].update(avgdl=99),
    lambda m: m.update(text_column="id"),
])
def test_incompatible_manifest_tokenizer_and_statistics_are_rejected(tmp_path, change):
    with source(tmp_path, [(1, "texto")]) as (heap, _):
        build(tmp_path, heap)
    edit_manifest(tmp_path / "index", change)
    with pytest.raises(ValidationError):
        TextIndex.open(tmp_path / "index")


@pytest.mark.parametrize("filename", ["postings.bin", "lexicon.jsonl", "documents.jsonl"])
def test_component_hash_detects_same_size_corruption(tmp_path, filename):
    with source(tmp_path, [(1, "texto")]) as (heap, _):
        build(tmp_path, heap)
    path = tmp_path / "index" / filename
    payload = bytearray(path.read_bytes())
    payload[-1] ^= 1
    path.write_bytes(payload)
    with pytest.raises(ValidationError, match="hash mismatch"):
        TextIndex.open(tmp_path / "index")


@pytest.mark.parametrize("change", ["dimension", "offset", "df", "length", "duplicate_doc", "duplicate_rid", "norm", "tokens"])
def test_structural_validation_survives_recomputed_component_receipts(tmp_path, change):
    with source(tmp_path, [(1, "texto"), (2, "otro")]) as (heap, _):
        build(tmp_path, heap)
    directory = tmp_path / "index"
    filename = "lexicon.jsonl" if change in {"dimension", "offset", "df", "length"} else "documents.jsonl"
    path = directory / filename
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if change in {"dimension", "offset", "df"}:
        values[0][change] += 1
    elif change == "length":
        values[0]["byte_length"] += 1
    elif change == "duplicate_doc":
        values[1]["id"] = values[0]["id"]
    elif change == "duplicate_rid":
        values[1]["page_id"], values[1]["slot_id"] = values[0]["page_id"], values[0]["slot_id"]
    elif change == "norm":
        values[0]["norm"] = -1
    else:
        values[0]["length"] += 1
    path.write_bytes(b"".join(json_bytes(value) for value in values))
    rewrite_receipts(directory)
    with pytest.raises(ValidationError):
        TextIndex.open(directory)


@pytest.mark.parametrize("change", ["duplicate", "frequency", "unknown", "norm"])
def test_deep_postings_validation_detects_semantic_corruption_with_forged_receipts(tmp_path, change):
    with source(tmp_path, [(1, "texto"), (2, "texto")]) as (heap, _):
        build(tmp_path, heap)
    directory = tmp_path / "index"
    if change == "norm":
        path = directory / "documents.jsonl"
        values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        values[0]["norm"] = 99.0
        path.write_bytes(b"".join(json_bytes(value) for value in values))
    else:
        path = directory / "postings.bin"
        payload = bytearray(path.read_bytes())
        doc_id, tf = {"duplicate": (1, 1), "frequency": (2, 0), "unknown": (99, 1)}[change]
        POSTING.pack_into(payload, HEADER.size + POSTING.size, doc_id, tf)
        path.write_bytes(payload)
    rewrite_receipts(directory)
    with TextIndex.open(directory) as index:
        with pytest.raises(ValidationError):
            index.validate()


def test_storage_verification_detects_changes_without_implementing_sealing(tmp_path):
    with source(tmp_path, [(1, "texto"), (2, "texto")]) as (heap, rids):
        build(tmp_path, heap)
        with TextIndex.open(tmp_path / "index") as index:
            heap.delete(rids[1])
            heap.insert(Record(SCHEMA, [1, "cambiado"]))
            with pytest.raises(ValidationError, match="generation"):
                index.verify_storage(heap)


def test_interleaved_iterators_independent_offsets_early_close_and_bounded_buffers(tmp_path):
    rows = [(i, "compartido par" if i % 2 == 0 else "compartido impar") for i in range(15, -1, -1)]
    with source(tmp_path, rows) as (heap, _):
        build(tmp_path, heap)
    with TextIndex.open(tmp_path / "index", buffer_bytes=16) as index:
        shared = index.postings("compartido")
        evens = index.postings("par")
        assert next(shared) == next(evens) == (0, 1)
        assert next(evens) == (2, 1)
        assert next(shared) == (1, 1)
        assert shared.buffer_capacity_bytes == evens.buffer_capacity_bytes == 16
        shared.close()
        assert list(shared) == []
        assert list(evens) == [(i, 1) for i in range(4, 16, 2)]
        assert list(index.postings("impar")) == [(i, 1) for i in range(1, 16, 2)]
        active = index.postings("compartido", buffer_bytes=32)
        next(active)
        index.close()
        index.close()
        with pytest.raises(ValidationError, match="closed"):
            next(active)  # Even a locally buffered posting must not survive reader close.
        active.close()


def test_two_real_threads_share_one_reader_without_serializing_whole_queries(tmp_path):
    rows = [(i, "ambos primero" if i % 2 else "ambos segundo") for i in range(40)]
    with source(tmp_path, rows) as (heap, _):
        build(tmp_path, heap)
    with TextIndex.open(tmp_path / "index", buffer_bytes=16) as index:
        barrier = Barrier(2)
        def consume(term):
            results = []
            with index.postings(term) as iterator:
                for item in iterator:
                    barrier.wait(timeout=10)
                    results.append(item)
                    barrier.wait(timeout=10)
            return results
        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(consume, "primero")
            right = pool.submit(consume, "segundo")
            assert left.result(timeout=15) == [(i, 1) for i in range(1, 40, 2)]
            assert right.result(timeout=15) == [(i, 1) for i in range(0, 40, 2)]
        assert list(index.postings("ambos")) == [(i, 1) for i in range(40)]


def test_truncation_during_read_is_controlled_and_iterator_never_owns_handle(tmp_path):
    with source(tmp_path, [(1, "texto"), (2, "texto")]) as (heap, _):
        build(tmp_path, heap)
    with TextIndex.open(tmp_path / "index", buffer_bytes=16) as index:
        iterator = index.postings("texto")
        assert next(iterator) == (1, 1)
        # Inject a short physical read without platform-dependent sharing/truncate behavior.
        original = index._handle
        class ShortRead:
            def seek(self, offset):
                return original.seek(offset)
            def read(self, amount):
                return original.read(amount - 1)
            def close(self):
                return original.close()
        index._handle = ShortRead()
        with pytest.raises(ValidationError, match="Incomplete"):
            next(iterator)
        iterator.close()
        assert not original.closed


def test_one_document_can_span_many_blocks_without_losing_term_frequencies(tmp_path):
    terms = [f"palabra{i}" for i in range(40)]
    text = " ".join(terms + terms[::2])
    with source(tmp_path, [(9, text), (3, "palabra0")]) as (heap, _):
        report = build(tmp_path, heap, memory_budget_bytes=1200, merge_fan_in=3, io_buffer_bytes=33)
        assert report.initial_blocks >= 40
        assert report.io_buffer_bytes == 32
        with TextIndex.open(tmp_path / "index") as index:
            index.validate()
            assert index.documents[9].length == 60
            assert list(index.postings("palabra0")) == [(3, 1), (9, 2)]
            assert list(index.postings("palabra1")) == [(9, 1)]


def test_one_term_larger_than_block_budget_is_rejected_without_truncation(tmp_path):
    with source(tmp_path, [(9, "é" * 1500)]) as (heap, _):
        with pytest.raises(InsufficientBudgetError):
            build(tmp_path, heap, memory_budget_bytes=1200)
        assert heap.read(next(heap.scan())[0])["contenido"] == "é" * 1500
        assert not (tmp_path / "index").exists()


class SourceFault(Storage):
    """Only scan/read are allowed; simulate a broken or changing source."""
    def __init__(self, heap, mode):
        self.heap = heap
        self.mode = mode
        self.scans = 0
        self.scans_closed = 0

    def scan(self):
        self.scans += 1
        number = self.scans
        iterator = self.heap.scan()
        first_rid = None
        try:
            for position, (rid, record) in enumerate(iterator):
                first_rid = rid if first_rid is None else first_rid
                if self.mode == "duplicate_rid" and position:
                    rid = first_rid
                if self.mode == "bad_rid" and position:
                    rid = RID(99, 0)
                if self.mode == "changed_on_verification" and number == 2 and position:
                    record = Record(SCHEMA, [record["id"], "cambiado"])
                yield rid, record
                if self.mode == "scan_error":
                    raise OSError("injected scan error")
        finally:
            iterator.close()
            self.scans_closed += 1

    def read(self, rid):
        return self.heap.read(rid)

    def insert(self, record):
        raise AssertionError("builder must not write to its source")

    def delete(self, rid):
        raise AssertionError("builder must not write to its source")


@pytest.mark.parametrize("mode", ["duplicate_rid", "bad_rid", "changed_on_verification", "scan_error"])
def test_source_fault_closes_scan_and_never_publishes_wrong_rid_associations(tmp_path, mode):
    with source(tmp_path, [(1, "texto"), (2, "otro")]) as (heap, _):
        broken = SourceFault(heap, mode)
        with pytest.raises((DatabaseError, OSError)):
            build_spimi(tmp_path / "index", broken, TABLE, collection_id="fault")
        assert broken.scans == broken.scans_closed
        assert not (tmp_path / "index").exists()
        assert heap.record_count == 2


def test_merge_respects_actual_handle_fan_in_and_never_materializes_a_whole_list(tmp_path, monkeypatch):
    from engine.text import spimi
    original_init, original_close = spimi._RunReader.__init__, spimi._RunReader.close
    live = set()
    maximum = 0
    def init(reader, *args):
        nonlocal maximum
        original_init(reader, *args)
        live.add(id(reader))
        maximum = max(maximum, len(live))
    def close(reader):
        live.discard(id(reader))
        return original_close(reader)
    monkeypatch.setattr(spimi._RunReader, "__init__", init)
    monkeypatch.setattr(spimi._RunReader, "close", close)
    with source(tmp_path, [(i, "común repetido " * 4) for i in range(24)]) as (heap, _):
        report = build(tmp_path, heap, memory_budget_bytes=1200, merge_fan_in=3, io_buffer_bytes=16)
        assert maximum == report.peak_open_runs == 3
        assert live == set()
        with TextIndex.open(tmp_path / "index", buffer_bytes=16) as index:
            with index.postings("común") as postings:
                for expected, item in enumerate(postings):
                    assert item == (expected, 4)
                    assert len(postings._buffer) <= 16


def test_merge_rejects_duplicate_postings_from_separate_sorted_runs(tmp_path):
    from engine.text.spimi import _merge_runs
    from engine.text.format import COUNT, RUN_MAGIC, TERM_LENGTH, VERSION
    paths = []
    for number in range(2):
        path = tmp_path / f"duplicate-{number}.run"
        path.write_bytes(HEADER.pack(RUN_MAGIC, VERSION) + TERM_LENGTH.pack(4)
            + b"base" + COUNT.pack(1) + POSTING.pack(7, 1))
        paths.append(path)
    with pytest.raises(DuplicateError, match="across SPIMI runs"):
        _merge_runs(paths, tmp_path / "merged.run", 16)


@pytest.mark.parametrize("kind", ["header", "truncate", "trailing"])
def test_postings_geometry_rejects_corruption_even_if_hashes_are_recomputed(tmp_path, kind):
    with source(tmp_path, [(1, "texto")]) as (heap, _):
        build(tmp_path, heap)
    directory = tmp_path / "index"
    path = directory / "postings.bin"
    payload = path.read_bytes()
    if kind == "header":
        payload = b"badmagic" + payload[8:]
    elif kind == "truncate":
        payload = payload[:-1]
    else:
        payload += b"\x00"
    path.write_bytes(payload)
    rewrite_receipts(directory)
    with pytest.raises(ValidationError):
        TextIndex.open(directory)


@pytest.mark.parametrize("payload", ['{"version":1,"version":1}', '{"version":NaN}', '[]', '{'])
def test_malformed_duplicate_or_nonfinite_manifest_json_is_controlled(tmp_path, payload):
    directory = tmp_path / "index"
    directory.mkdir()
    (directory / "manifest.json").write_text(payload, encoding="utf-8")
    with pytest.raises(ValidationError):
        TextIndex.open(directory)


@pytest.mark.parametrize("buffer_bytes", [0, 15, True])
def test_posting_iterator_rejects_invalid_buffer_capacity(tmp_path, buffer_bytes):
    with source(tmp_path, [(1, "texto")]) as (heap, _):
        build(tmp_path, heap)
    with TextIndex.open(tmp_path / "index") as index:
        with pytest.raises((TypeError, ValidationError)):
            index.postings("texto", buffer_bytes=buffer_bytes)
