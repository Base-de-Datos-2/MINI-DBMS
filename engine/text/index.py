"""Read-only postings with independent bounded iterators over a shared handle."""

from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import math
from pathlib import Path
from threading import RLock
from types import MappingProxyType

from engine.errors import ValidationError
from engine.storage.rid import RID

from .format import (
    COMPONENTS, HEADER, POSTING, POSTINGS_MAGIC, VERSION, CollectionStatistics,
    DocumentEntry, TermEntry, checked_payload, digest, file_receipt, finite,
    integer, json_rows, name, read_json, restore_table, validate_columns,
)
from .tokenizer import tokenize, tokenizer_signature


def _buffer_bytes(value):
    integer(value, "buffer_bytes", POSTING.size)
    return value - value % POSTING.size


class TextIndex:
    """Own one permanent binary reader; iterators borrow it and never close it.

    Opening hashes components in 64 KiB chunks and loads only the lexicon and
    document statistics. It does not retain text or materialize posting lists.
    The caller owns storage and must prevent mutation for this index's lifetime.
    Persistent storage sealing and database-owner integration belong to 4A/4B.
    """

    @classmethod
    def open(cls, directory, *, collection_id=None, generation=None, table=None,
             buffer_bytes=4096):
        instance = cls()
        instance._mutex = RLock()
        instance._handle = None
        instance._closed = False
        instance._buffer_bytes = _buffer_bytes(buffer_bytes)
        try:
            instance._load(Path(directory), collection_id, generation, table)
            return instance
        except BaseException:
            instance.close()
            raise

    def _load(self, directory, expected_collection, expected_generation, expected_table):
        manifest = read_json(directory / "manifest.json")
        fields = {"version", "state", "collection_id", "generation", "table", "id_column",
                  "text_column", "tokenizer", "statistics", "files", "build"}
        if type(manifest) is not dict or set(manifest) != fields:
            raise ValidationError("Incomplete or invalid text-index manifest")
        if type(manifest["version"]) is not int or manifest["version"] != VERSION or manifest["state"] != "complete":
            raise ValidationError("Unsupported or incomplete text-index generation")
        self.collection_id = name(manifest["collection_id"], "collection_id")
        self.generation = name(manifest["generation"], "generation")
        self.table = restore_table(manifest["table"])
        self.id_column = name(manifest["id_column"], "id_column")
        self.text_column = name(manifest["text_column"], "text_column")
        validate_columns(self.table, self.id_column, self.text_column)
        for expected, actual in ((expected_collection, self.collection_id),
                                 (expected_generation, self.generation), (expected_table, self.table)):
            if expected is not None and expected != actual:
                raise ValidationError("Text index belongs to a different collection, generation or schema")
        if manifest["tokenizer"] != tokenizer_signature():
            raise ValidationError("Incompatible text-index tokenizer or Unicode version")
        receipts = manifest["files"]
        if type(receipts) is not dict or set(receipts) != set(COMPONENTS):
            raise ValidationError("Missing text-index components")
        for filename in COMPONENTS:
            receipt = receipts[filename]
            if type(receipt) is not dict or set(receipt) != {"bytes", "sha256"}:
                raise ValidationError("Invalid text-index component receipt")
            integer(receipt["bytes"], "component bytes")
            digest(receipt["sha256"])
            try:
                actual = file_receipt(directory / filename)
            except OSError as error:
                raise ValidationError(f"Missing text-index component {filename}") from error
            if actual != receipt:
                raise ValidationError(f"Text-index size/hash mismatch: {filename}")
        self._file_size = receipts["postings.bin"]["bytes"]
        documents = {}
        rids = set()
        previous = None
        for row in json_rows(directory / "documents.jsonl"):
            if set(row) != {"id", "page_id", "slot_id", "length", "norm", "record_sha256"}:
                raise ValidationError("Invalid text document metadata")
            entry = DocumentEntry(row["id"], RID(row["page_id"], row["slot_id"]),
                                  row["length"], row["norm"], row["record_sha256"])
            if (previous is not None and entry.doc_id <= previous) or entry.rid in rids:
                raise ValidationError("Duplicate/unordered document IDs or duplicate RIDs")
            previous = entry.doc_id
            rids.add(entry.rid)
            documents[entry.doc_id] = entry
        statistics = manifest["statistics"]
        if type(statistics) is not dict or set(statistics) != {"N", "total_tokens", "avgdl", "vocabulary_size"}:
            raise ValidationError("Invalid text collection statistics")
        n = integer(statistics["N"], "N")
        total = integer(statistics["total_tokens"], "total_tokens")
        vocabulary_size = integer(statistics["vocabulary_size"], "vocabulary_size")
        average = finite(statistics["avgdl"], "avgdl")
        if n != len(documents) or total != sum(d.length for d in documents.values()) or average != (total / n if n else 0.0):
            raise ValidationError("Inconsistent text collection statistics")
        lexicon = {}
        offset = HEADER.size
        previous_term = None
        for row in json_rows(directory / "lexicon.jsonl"):
            if set(row) != {"term", "dimension", "offset", "df", "byte_length"}:
                raise ValidationError("Invalid lexicon entry")
            term = name(row["term"], "term")
            if tokenize(term) != (term,) or (previous_term is not None and term <= previous_term):
                raise ValidationError("Lexicon terms must be normalized, unique and sorted")
            dimension = integer(row["dimension"], "dimension")
            term_offset = integer(row["offset"], "offset", HEADER.size)
            df = integer(row["df"], "df", 1, n)
            length = integer(row["byte_length"], "byte_length", POSTING.size)
            if dimension != len(lexicon) or term_offset != offset or length != df * POSTING.size:
                raise ValidationError("Inconsistent lexicon dimension, offset or length")
            lexicon[term] = TermEntry(dimension, offset, df, length)
            offset += length
            previous_term = term
        if vocabulary_size != len(lexicon) or offset != self._file_size:
            raise ValidationError("Lexicon does not cover the postings file")
        if bool(total) != bool(lexicon):
            raise ValidationError("Vocabulary is inconsistent with token counts")
        try:
            self._handle = (directory / "postings.bin").open("rb", buffering=0)
            if self._handle.read(HEADER.size) != HEADER.pack(POSTINGS_MAGIC, VERSION):
                raise ValidationError("Invalid postings header/version")
        except OSError as error:
            raise ValidationError("Cannot open text postings") from error
        self.documents = MappingProxyType(documents)
        self.lexicon = MappingProxyType(lexicon)
        self.statistics = CollectionStatistics(n, total, average, vocabulary_size)
        # Build telemetry is descriptive, never a prerequisite for reading.
        if type(manifest["build"]) is not dict:
            raise ValidationError("Invalid text-index build report")
        self.build_report = MappingProxyType(dict(manifest["build"]))

    def _require_open(self):
        if self._closed:
            raise ValidationError("Text index is closed")

    def _read_at(self, offset, length):
        # The latch covers seek AND transfer; never yield or score under it.
        with self._mutex:
            self._require_open()
            if offset < HEADER.size or length < 0 or offset + length > self._file_size:
                raise ValidationError("Text postings read is outside its component")
            try:
                self._handle.seek(offset)
                data = self._handle.read(length)
            except OSError as error:
                raise ValidationError("Cannot read text postings") from error
            if len(data) != length:
                raise ValidationError("Incomplete text postings read")
            return data

    def postings(self, term: str, *, buffer_bytes=None):
        """Read an exact normalized term; unknown terms have no postings."""
        self._require_open()
        if type(term) is not str:
            raise ValidationError("A posting-list term must be a string")
        capacity = self._buffer_bytes if buffer_bytes is None else _buffer_bytes(buffer_bytes)
        return PostingIterator(self, self.lexicon.get(term), capacity)

    def validate(self):
        """Stream all postings and verify lengths and complete-vector norms."""
        self._require_open()
        lengths = dict.fromkeys(self.documents, 0)
        squares = dict.fromkeys(self.documents, 0.0)
        for term, entry in self.lexicon.items():
            idf = math.log((self.statistics.document_count + 1) / (entry.df + 1)) + 1
            with self.postings(term) as postings:
                for doc_id, tf in postings:
                    lengths[doc_id] += tf
                    weight = (1 + math.log(tf)) * idf
                    squares[doc_id] += weight * weight
        for doc_id, document in self.documents.items():
            if lengths[doc_id] != document.length or not math.isclose(
                math.sqrt(squares[doc_id]), document.norm, rel_tol=1e-10, abs_tol=1e-12,
            ):
                raise ValidationError("Postings disagree with document lengths or norms")

    def verify_storage(self, storage):
        """Verify every live RID and full original row against this generation.

        No storage handle is owned/closed here. The caller must keep the source
        quiescent; this check is not persistent sealing or crash recovery.
        """
        self._require_open()
        self.require_compatible_storage(storage)
        seen = set()
        with closing(storage.scan()) as rows:
            for rid, record in rows:
                payload = checked_payload(self.table, record)
                doc_id = record[self.id_column]
                expected = self.documents.get(doc_id)
                if doc_id in seen or expected is None or rid != expected.rid or sha256(payload).hexdigest() != expected.record_sha256:
                    raise ValidationError("Storage does not match the indexed collection generation")
                # Check the RID resolves to the same row, not merely scan output.
                if storage.read(rid) != record:
                    raise ValidationError("Indexed RID does not resolve to its original row")
                seen.add(doc_id)
        if len(seen) != self.statistics.document_count:
            raise ValidationError("Storage document count differs from the index")

    def require_compatible_storage(self, storage):
        """A sealed Heap belongs only to the collection generation it froze."""
        self._require_open()
        if storage.read_only:
            descriptor = getattr(storage, "seal_descriptor", None)
            if (descriptor is None or descriptor.collection_id != self.collection_id
                    or descriptor.generation != self.generation):
                raise ValidationError("Sealed Heap belongs to a different text collection generation")

    def close(self):
        with self._mutex:
            if not self._closed:
                self._closed = True
                if self._handle is not None:
                    self._handle.close()

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, *exc):
        self.close()


class PostingIterator:
    """A bounded buffer and logical cursor; early close affects no other reader."""

    def __init__(self, reader, entry, capacity):
        self._reader = reader
        self._offset = 0 if entry is None else entry.offset
        self._remaining = 0 if entry is None else entry.df
        self.buffer_capacity_bytes = capacity
        self._buffer = b""
        self._position = 0
        self._previous = None
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._closed:
            raise StopIteration
        self._reader._require_open()
        if not self._remaining:
            self.close()
            raise StopIteration
        if self._position == len(self._buffer):
            self._buffer = b""
            amount = min(self.buffer_capacity_bytes, self._remaining * POSTING.size)
            self._buffer = self._reader._read_at(self._offset, amount)
            self._position = 0
        doc_id, tf = POSTING.unpack_from(self._buffer, self._position)
        if not tf or doc_id not in self._reader.documents or (self._previous is not None and doc_id <= self._previous):
            self.close()
            raise ValidationError("Invalid frequency, reference or posting-list order")
        self._previous = doc_id
        self._position += POSTING.size
        self._offset += POSTING.size
        self._remaining -= 1
        return doc_id, tf

    def close(self):
        self._buffer = b""
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


__all__ = ["TextIndex", "PostingIterator"]
