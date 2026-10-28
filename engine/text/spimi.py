"""Single-pass in-memory indexing and bounded fan-in external merging.

The budget covers a conservative Python block/sort estimate, not process RSS.
Document identity/statistics are O(N) and measured separately. Only the current
page-sized document is tokenized; no corpus text or entire merged list is kept.
"""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack, closing
from dataclasses import asdict, dataclass
from hashlib import sha256
import heapq
import math
from pathlib import Path
import shutil
from sys import getsizeof
from tempfile import TemporaryDirectory
from uuid import uuid4

from engine.catalog import TableMetadata
from engine.errors import DuplicateError, InsufficientBudgetError, ValidationError
from engine.storage.base import Storage
from engine.storage.rid import RID

from .format import (
    COMPONENTS, COUNT, HEADER, MAX_TERM_BYTES, POSTING, POSTINGS_MAGIC, RUN_MAGIC,
    TERM_LENGTH, VERSION, checked_payload, file_receipt, integer, json_bytes,
    name, table_document, validate_columns,
)
from .index import TextIndex
from .tokenizer import tokenize, tokenizer_signature


@dataclass(frozen=True, slots=True)
class SpimiBuildReport:
    generation: str
    document_count: int
    vocabulary_size: int
    posting_count: int
    initial_blocks: int
    merge_passes: int
    peak_open_runs: int
    memory_budget_bytes: int
    peak_block_estimated_bytes: int
    peak_document_estimated_bytes: int
    metadata_estimated_bytes: int
    metadata_sort_workspace_bytes: int
    merge_workspace_estimated_bytes: int
    io_buffer_bytes: int
    merge_fan_in: int


class _Block:
    """Charge tuples/integers plus conservative dict/list/sorting headroom.

    512 bytes per term cover its mapping/list slots and sorted-key workspace;
    four pointer slots per posting cover list over-allocation and Timsort's
    temporary pointers. Shared IDs/strings are charged again conservatively.
    This explicit allocation model is a spill policy, not an allocator/RSS cap.
    """

    def __init__(self):
        self.terms = {}
        self.estimated_bytes = 256

    def cost(self, term, posting):
        return (getsizeof(posting) + sum(getsizeof(value) for value in posting) + 32
                + (getsizeof(term) + 512 if term not in self.terms else 0))

    def add(self, term, posting, cost):
        self.terms.setdefault(term, []).append(posting)
        self.estimated_bytes += cost


def _write_block(path, block):
    with path.open("wb", buffering=8192) as stream:
        stream.write(HEADER.pack(RUN_MAGIC, VERSION))
        for term in sorted(block.terms):
            postings = block.terms[term]
            postings.sort()  # IDs may arrive in arbitrary order.
            _write_term(stream, term, len(postings))
            previous = None
            for doc_id, tf in postings:
                if previous is not None and doc_id <= previous:
                    raise DuplicateError("Duplicate document in a SPIMI block")
                stream.write(POSTING.pack(doc_id, tf))
                previous = doc_id


def _write_term(stream, term, count):
    encoded = term.encode("utf-8")
    stream.write(TERM_LENGTH.pack(len(encoded)))
    stream.write(encoded)
    stream.write(COUNT.pack(count))


class _RunReader:
    """At most one fixed buffer per input run; never read an entire term list."""

    def __init__(self, path, buffer_bytes):
        self.stream = path.open("rb", buffering=0)
        self.capacity = buffer_bytes
        self.term = None
        self.remaining = 0
        self.count = 0
        self.buffer = b""
        self.position = 0
        try:
            if self._exact(HEADER.size) != HEADER.pack(RUN_MAGIC, VERSION):
                raise ValidationError("Invalid SPIMI temporary header")
            self.advance()
        except BaseException:
            self.close()
            raise

    def _exact(self, amount):
        data = self.stream.read(amount)
        if len(data) != amount:
            raise ValidationError("Truncated SPIMI temporary run")
        return data

    def advance(self):
        if self.remaining:
            raise ValidationError("SPIMI term list was not consumed")
        raw = self.stream.read(TERM_LENGTH.size)
        if not raw:
            self.term = None
            return
        if len(raw) != TERM_LENGTH.size:
            raise ValidationError("Truncated SPIMI term frame")
        size, = TERM_LENGTH.unpack(raw)
        if not 1 <= size <= MAX_TERM_BYTES:
            raise ValidationError("Invalid SPIMI term length")
        try:
            term = self._exact(size).decode("utf-8")
        except UnicodeError as error:
            raise ValidationError("Invalid SPIMI term encoding") from error
        if self.term is not None and term <= self.term:
            raise ValidationError("Unordered SPIMI terms")
        self.term = term
        self.count, = COUNT.unpack(self._exact(COUNT.size))
        if not self.count:
            raise ValidationError("Empty SPIMI posting list")
        self.remaining = self.count
        self.buffer = b""
        self.position = 0
        self.previous = None

    def next_posting(self):
        if not self.remaining:
            return None
        if self.position == len(self.buffer):
            self.buffer = b""
            self.buffer = self._exact(min(self.capacity, self.remaining * POSTING.size))
            self.position = 0
        doc_id, tf = POSTING.unpack_from(self.buffer, self.position)
        if not tf or (self.previous is not None and doc_id <= self.previous):
            raise ValidationError("Duplicate/unordered IDs or invalid SPIMI frequency")
        self.previous = doc_id
        self.remaining -= 1
        self.position += POSTING.size
        return doc_id, tf

    def close(self):
        self.buffer = b""
        self.stream.close()


def _merge_runs(paths, destination, buffer_bytes):
    with ExitStack() as stack:
        readers = []
        for path in paths:
            reader = _RunReader(path, buffer_bytes)
            stack.callback(reader.close)
            readers.append(reader)
        stream = stack.enter_context(destination.open("wb", buffering=8192))
        stream.write(HEADER.pack(RUN_MAGIC, VERSION))
        terms = [(reader.term, i) for i, reader in enumerate(readers) if reader.term is not None]
        heapq.heapify(terms)
        while terms:
            term = terms[0][0]
            group = []
            while terms and terms[0][0] == term:
                _, i = heapq.heappop(terms)
                group.append(i)
            _write_term(stream, term, sum(readers[i].count for i in group))
            postings = []
            for i in group:
                doc_id, tf = readers[i].next_posting()
                heapq.heappush(postings, (doc_id, tf, i))
            previous = None
            while postings:
                doc_id, tf, i = heapq.heappop(postings)
                if previous is not None and doc_id <= previous:
                    raise DuplicateError("Duplicate document across SPIMI runs")
                stream.write(POSTING.pack(doc_id, tf))
                previous = doc_id
                item = readers[i].next_posting()
                if item is not None:
                    heapq.heappush(postings, (*item, i))
            for i in group:
                readers[i].advance()
                if readers[i].term is not None:
                    heapq.heappush(terms, (readers[i].term, i))


def _finish(stage, run_path, documents, buffer_bytes):
    """Write dimensions/postings and derive norms using final N/df, not blocks."""
    squares = dict.fromkeys(documents, 0.0)
    vocabulary_size = 0
    posting_count = 0
    with ExitStack() as stack:
        output = stack.enter_context((stage / "postings.bin").open("wb", buffering=8192))
        lexicon = stack.enter_context((stage / "lexicon.jsonl").open("wb", buffering=8192))
        output.write(HEADER.pack(POSTINGS_MAGIC, VERSION))
        if run_path is not None:
            reader = _RunReader(run_path, buffer_bytes)
            stack.callback(reader.close)
            while reader.term is not None:
                df = reader.count
                lexicon.write(json_bytes({"term": reader.term, "dimension": vocabulary_size,
                    "offset": output.tell(), "df": df, "byte_length": df * POSTING.size}))
                idf = math.log((len(documents) + 1) / (df + 1)) + 1
                while (item := reader.next_posting()) is not None:
                    doc_id, tf = item
                    output.write(POSTING.pack(doc_id, tf))
                    weight = (1 + math.log(tf)) * idf
                    squares[doc_id] += weight * weight
                    posting_count += 1
                vocabulary_size += 1
                reader.advance()
    with (stage / "documents.jsonl").open("wb", buffering=8192) as stream:
        for doc_id in sorted(documents):
            rid, length, record_hash = documents[doc_id]
            stream.write(json_bytes({"id": doc_id, "page_id": rid.page_id, "slot_id": rid.slot_id,
                "length": length, "norm": math.sqrt(squares[doc_id]), "record_sha256": record_hash}))
    return vocabulary_size, posting_count


def build_spimi(directory, storage: Storage, table: TableMetadata, *, collection_id: str,
                id_column="id", text_column="contenido", memory_budget_bytes=8 * 1024 * 1024,
                merge_fan_in=16, io_buffer_bytes=4096) -> SpimiBuildReport:
    """Build exclusively into a NEW directory from a quiescent borrowed Heap.

    Publication writes the complete manifest last, after validating the index
    and every original RID/row. Failure removes only this newly created output;
    existing destinations and the borrowed source are never overwritten/closed.
    No SQL, storage sealing or database-owner registration is performed here.
    """
    if not isinstance(storage, Storage):
        raise ValidationError("SPIMI requires a Storage instance")
    validate_columns(table, id_column, text_column)
    name(collection_id, "collection_id")
    integer(memory_budget_bytes, "memory_budget_bytes", 1)
    integer(merge_fan_in, "merge_fan_in", 2)
    integer(io_buffer_bytes, "io_buffer_bytes", POSTING.size)
    io_buffer_bytes -= io_buffer_bytes % POSTING.size
    target = Path(directory)
    target.mkdir()  # Exclusive reservation; fail before touching an existing path.
    try:
        with TemporaryDirectory(prefix=".spimi-", dir=target) as temporary:
            stage = Path(temporary)
            documents = {}
            rids = set()
            block = _Block()
            runs = []
            peak_block = 0
            peak_document = 0
            total_tokens = 0
            with closing(storage.scan()) as rows:
                for rid, record in rows:
                    payload = checked_payload(table, record)
                    doc_id = record[id_column]
                    if doc_id in documents:
                        raise DuplicateError("Duplicate document ID in text collection")
                    if not isinstance(rid, RID) or rid.page_id < 1 or rid in rids:
                        raise DuplicateError("Invalid or duplicate text document RID")
                    tokens = tokenize(record[text_column])
                    counts = Counter(tokens)
                    peak_document = max(peak_document, getsizeof(payload) + getsizeof(tokens)
                        + sum(getsizeof(t) for t in tokens) + getsizeof(counts)
                        + sum(getsizeof(t) + getsizeof(tf) for t, tf in counts.items()))
                    documents[doc_id] = (rid, len(tokens), sha256(payload).hexdigest())
                    rids.add(rid)
                    total_tokens += len(tokens)
                    for term, tf in counts.items():
                        posting = (doc_id, tf)
                        cost = block.cost(term, posting)
                        if block.terms and block.estimated_bytes + cost > memory_budget_bytes:
                            path = stage / f"block-{len(runs)}.run"
                            _write_block(path, block)
                            runs.append(path)
                            block = _Block()
                            cost = block.cost(term, posting)
                        if block.estimated_bytes + cost > memory_budget_bytes:
                            raise InsufficientBudgetError("SPIMI budget cannot hold one term/posting with sort workspace")
                        block.add(term, posting, cost)
                        peak_block = max(peak_block, block.estimated_bytes)
            if block.terms:
                path = stage / f"block-{len(runs)}.run"
                _write_block(path, block)
                runs.append(path)
            del block
            initial_blocks = len(runs)
            passes = 0
            peak_open_runs = 1 if runs else 0
            while len(runs) > 1:
                next_runs = []
                for start in range(0, len(runs), merge_fan_in):
                    group = runs[start:start + merge_fan_in]
                    if len(group) == 1:
                        next_runs.append(group[0])
                        continue
                    destination = stage / f"merge-{passes}-{start}.run"
                    peak_open_runs = max(peak_open_runs, len(group))
                    _merge_runs(group, destination, io_buffer_bytes)
                    next_runs.append(destination)
                    for path in group:
                        path.unlink()
                passes += 1
                runs = next_runs
            vocabulary_size, posting_count = _finish(stage, runs[0] if runs else None, documents, io_buffer_bytes)
            if runs:
                runs[0].unlink()
            n = len(documents)
            metadata_bytes = (getsizeof(documents) + getsizeof(rids)
                + sum(getsizeof(doc_id) + getsizeof(row) + getsizeof(row[0])
                      + getsizeof(row[1]) + getsizeof(row[2]) + 64 for doc_id, row in documents.items())
                + n * 64)  # norms accumulator's values and dictionary slots
            report = SpimiBuildReport(
                uuid4().hex, n, vocabulary_size, posting_count, initial_blocks, passes,
                peak_open_runs, memory_budget_bytes, peak_block, peak_document,
                metadata_bytes, 16 * n + 64,
                peak_open_runs * (io_buffer_bytes + MAX_TERM_BYTES + 512) + 8192,
                io_buffer_bytes, merge_fan_in,
            )
            del documents, rids
            manifest = {
                "version": VERSION, "state": "complete", "collection_id": collection_id,
                "generation": report.generation, "table": table_document(table),
                "id_column": id_column, "text_column": text_column,
                "tokenizer": tokenizer_signature(),
                "statistics": {"N": n, "total_tokens": total_tokens,
                    "avgdl": total_tokens / n if n else 0.0, "vocabulary_size": vocabulary_size},
                "files": {filename: file_receipt(stage / filename) for filename in COMPONENTS},
                "build": asdict(report),
            }
            (stage / "manifest.json").write_bytes(json_bytes(manifest))
            with TextIndex.open(stage) as index:
                index.validate()
                index.verify_storage(storage)
            for filename in (*COMPONENTS, "manifest.json"):
                (stage / filename).replace(target / filename)
        return report
    except BaseException:
        shutil.rmtree(target)
        raise


__all__ = ["SpimiBuildReport", "build_spimi"]
