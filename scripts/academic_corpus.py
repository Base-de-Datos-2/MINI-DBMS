"""Validate local academic PDFs and form the exact Stage 2 storage rows."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PureWindowsPath
import re

from engine.catalog import Column, DataType, Schema
from engine.storage.binary import MAX_RECORD_SIZE
from engine.storage.record import Record
from engine.storage.record_codec import RecordCodec


MAX_SAFE_ID = 2**53 - 1
MIN_WORDS, TARGET_WORDS, MAX_WORDS = 200, 250, 500
PAPER_COLUMNS = (
    ("paper_id", DataType.INTEGER), ("authors", DataType.VARCHAR),
    ("year", DataType.INTEGER), ("title", DataType.VARCHAR),
    ("abstract", DataType.VARCHAR),
)
CHUNK_COLUMNS = (
    ("chunk_id", DataType.INTEGER), ("paper_id", DataType.INTEGER),
    ("position", DataType.INTEGER), ("content", DataType.VARCHAR),
)
PAPER_SCHEMA = Schema([Column(name, kind) for name, kind in PAPER_COLUMNS])
CHUNK_SCHEMA = Schema([Column(name, kind) for name, kind in CHUNK_COLUMNS])
PaperRow = tuple[int, str, int, str, str]
ChunkRow = tuple[int, int, int, str]


@dataclass(frozen=True)
class PaperSource:
    path: Path
    digest: str
    row: PaperRow


def require_id(value, label):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_ID:
        raise ValueError(f"{label}: expected a positive, JavaScript-safe integer")


def _row_size(schema, row, label):
    try:
        return len(RecordCodec.serialize(Record(schema, row)))
    except (ValueError, TypeError) as error:
        raise ValueError(f"{label}: {error}") from error


def require_row_fits(schema, row, label):
    size = _row_size(schema, row, label)
    if size > MAX_RECORD_SIZE:
        raise ValueError(f"{label}: serialized row is {size} bytes; maximum is {MAX_RECORD_SIZE}")
    return size


def validate_paper(row, label):
    paper_id, authors, year, title, abstract = row
    require_id(paper_id, f"{label} paper_id")
    if type(year) is not int:
        raise ValueError(f"{label}: year must be an integer")
    for field, value in (("authors", authors), ("title", title), ("abstract", abstract)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label}: {field} must be nonempty text")
    return require_row_fits(PAPER_SCHEMA, row, label)


def _text_field(entry, field, label):
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: {field} must be nonempty text")
    return value.strip()


def load_manifest(manifest: Path, pdf_dir: Path) -> list[PaperSource]:
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Manifest {manifest.name}: {error}") from error
    if not isinstance(entries, list) or not entries:
        raise ValueError("Manifest must be a nonempty array of paper objects")
    root = pdf_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"PDF directory does not exist: {pdf_dir}")

    papers, ids, paths, digests = [], set(), set(), set()
    for position, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Manifest entry {position}: expected a paper object")
        paper_id = entry.get("paper_id")
        filename = _text_field(entry, "pdf", f"Manifest entry {position} (paper_id={paper_id!r})")
        label = f"Paper {paper_id!r} ({filename})"
        require_id(paper_id, f"{label} paper_id")
        if paper_id in ids:
            raise ValueError(f"{label}: duplicate paper_id")
        for field in ("source_url", "version"):
            _text_field(entry, field, label)
        digest = _text_field(entry, "sha256", label).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"{label}: sha256 must contain 64 hexadecimal characters")
        relative = PureWindowsPath(filename)
        if relative.anchor or ".." in relative.parts:
            raise ValueError(f"{label}: pdf path must stay inside the PDF directory")
        path = root.joinpath(*relative.parts).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"{label}: pdf path must stay inside the PDF directory")
        if not path.is_file():
            raise ValueError(f"{label}: missing PDF or not a regular file")
        if path in paths or digest in digests:
            raise ValueError(f"{label}: duplicate PDF path or hash")

        row = (paper_id, _text_field(entry, "authors", label), entry.get("year"),
               _text_field(entry, "title", label), _text_field(entry, "abstract", label))
        validate_paper(row, label)
        papers.append(PaperSource(path, digest, row))
        ids.add(paper_id)
        paths.add(path)
        digests.add(digest)
    return sorted(papers, key=lambda paper: paper.row[0])


def extract_pdf(source: PaperSource) -> tuple[str, int, int]:
    # Import only during extraction so verify-only can run without the PDF extra.
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    label = f"Paper {source.row[0]} ({source.path.name})"
    try:
        data = source.path.read_bytes()
    except OSError as error:
        raise ValueError(f"{label}: could not read PDF: {error}") from error
    if sha256(data).hexdigest() != source.digest:
        raise ValueError(f"{label}: PDF SHA-256 mismatch")
    try:
        with PdfReader(BytesIO(data)) as reader:
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("encrypted PDF requires a password")
            pages = [page.extract_text() or "" for page in reader.pages]
    except (PyPdfError, ValueError, OSError) as error:
        raise ValueError(f"{label}: could not extract PDF: {error}") from error

    text = " ".join(" ".join(pages).split())
    if not any(character.isalnum() for character in text):
        raise ValueError(f"{label}: PDF contains no usable text")
    return text, len(pages), sum(not page.strip() for page in pages)


def split_chunks(text: str, paper_id: int, first_id: int, label: str) -> list[ChunkRow]:
    """Try balanced splits near 250 words, with half ties rounded up."""
    words = text.split()
    total = len(words)
    if total < MIN_WORDS:
        raise ValueError(f"{label}: only {total} words; at least {MIN_WORDS} required")
    minimum_count = (total + MAX_WORDS - 1) // MAX_WORDS
    maximum_count = total // MIN_WORDS
    preferred = (total + TARGET_WORDS // 2) // TARGET_WORDS
    first_count = min(max(preferred, minimum_count), maximum_count)
    for count in range(first_count, maximum_count + 1):
        require_id(first_id + count - 1, f"{label} last chunk_id")
        width, extra = divmod(total, count)
        offset, rows = 0, []
        for index in range(count):
            end = offset + width + (index < extra)
            row = (first_id + index, paper_id, index + 1, " ".join(words[offset:end]))
            if _row_size(CHUNK_SCHEMA, row, f"{label}, chunk {row[0]}") > MAX_RECORD_SIZE:
                break
            rows.append(row)
            offset = end
        if len(rows) == count:
            return rows
    raise ValueError(f"{label}: no balanced split satisfies {MIN_WORDS}–{MAX_WORDS} words "
                     f"and the {MAX_RECORD_SIZE}-byte serialized row limit")
