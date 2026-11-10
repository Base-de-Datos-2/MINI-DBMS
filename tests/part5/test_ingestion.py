from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from api.database import Database, DatabaseDefinition, NewTable
from engine.errors import DuplicateError
from engine.storage.binary import MAX_RECORD_SIZE
from engine.text.registry import read_text_registry
from scripts.academic_corpus import (
    CHUNK_COLUMNS, CHUNK_SCHEMA, PAPER_COLUMNS,
    extract_pdf, load_manifest, require_row_fits, split_chunks,
)
from scripts.setup_academic import main, prepare_academic


def write_pdf(path, *pages):
    pdf = pytest.importorskip("pypdf", reason="Install the academic extra for PDF ingestion tests")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = pdf.PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 10 Tf 50 700 Td (" + text.encode("cp1252") + b") Tj ET")
        page.replace_contents(content)
    writer.write(path)


@pytest.fixture
def inputs(tmp_path):
    pdf_dir = tmp_path / "inputs"
    pdf_dir.mkdir()
    entries = []
    for paper_id in (8, 2):
        path = pdf_dir / f"paper_{paper_id}.pdf"
        write_pdf(path, "Café " + "first " * 249 + f"end-{paper_id}",
                  "Start " + "second " * 250)
        entries.append({
            "paper_id": paper_id, "pdf": path.name,
            "source_url": f"https://example.invalid/{path.name}", "version": "v1",
            "sha256": sha256(path.read_bytes()).hexdigest(), "authors": "Test Author",
            "year": 2020, "title": f"Paper {paper_id}", "abstract": "Complete abstract.",
        })
    manifest = tmp_path / "corpus.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    return manifest, pdf_dir, entries


@pytest.mark.parametrize(("updates", "match"), [
    ({"abstract": None}, "abstract must be nonempty"),
    ({"paper_id": True}, "JavaScript-safe integer"),
    ({"paper_id": "8"}, "JavaScript-safe integer"),
    ({"paper_id": 2**53}, "JavaScript-safe integer"),
    ({"paper_id": 2}, "duplicate paper_id"),
    ({"year": True}, "year must be an integer"),
    ({"year": "2020"}, "year must be an integer"),
    ({"pdf": "missing.pdf"}, "missing PDF"),
    ({"pdf": "../paper_8.pdf"}, "inside the PDF directory"),
    ({"pdf": "/paper_8.pdf"}, "inside the PDF directory"),
    ({"sha256": "invalid"}, "64 hexadecimal characters"),
    ({"sha256": "0" * 64}, "SHA-256 mismatch"),
    ({"abstract": "é" * 2200}, "serialized row is"),
])
def test_bad_input_leaves_destination_absent(inputs, tmp_path, updates, match):
    manifest, pdf_dir, entries = inputs
    entries[0].update(updates)
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    dest = tmp_path / "database"
    with pytest.raises(ValueError, match=match):
        prepare_academic(manifest, pdf_dir, dest)
    assert not dest.exists()


@pytest.mark.parametrize("same_path", [False, True])
def test_duplicate_pdf_path_or_hash(inputs, same_path):
    manifest, pdf_dir, entries = inputs
    if same_path:
        entries[0]["pdf"] = entries[1]["pdf"]
    else:
        (pdf_dir / entries[0]["pdf"]).write_bytes((pdf_dir / entries[1]["pdf"]).read_bytes())
        entries[0]["sha256"] = entries[1]["sha256"]
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate PDF path or hash"):
        load_manifest(manifest, pdf_dir)


@pytest.mark.parametrize(("content", "match"), [
    (None, "could not extract PDF"),
    ("", "no usable text"),
])
def test_rejects_unreadable_and_textless_pdf(inputs, content, match):
    manifest, pdf_dir, entries = inputs
    entry = entries[0]
    path = pdf_dir / entry["pdf"]
    if content is None:
        path.write_bytes(b"%PDF-1.4\ninvalid")
    else:
        write_pdf(path, content)
    entry["sha256"] = sha256(path.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(ValueError, match=rf"Paper 8 \(paper_8.pdf\).*{match}"):
        extract_pdf(load_manifest(manifest, pdf_dir)[1])


def test_extracts_ordered_pages_and_keeps_unicode(inputs):
    manifest, pdf_dir, _ = inputs
    first = load_manifest(manifest, pdf_dir)[0]
    text, page_count, empty_pages = extract_pdf(first)
    assert (page_count, empty_pages) == (2, 0)
    assert text == "Café " + "first " * 249 + "end-2 Start " + "second " * 249 + "second"


@pytest.mark.parametrize(("count", "lengths"), [
    (200, [200]), (251, [251]), (501, [251, 250]), (1001, [251, 250, 250, 250]),
])
def test_balanced_chunks(count, lengths):
    text = " ".join(f"w{number}" for number in range(count))
    rows = split_chunks(text, 5, 9, "Paper 5")
    assert [len(content.split()) for _, _, _, content in rows] == lengths
    assert [row[:3] for row in rows] == [(9 + i, 5, 1 + i) for i in range(len(lengths))]
    assert " ".join(row[3] for row in rows) == text
    assert split_chunks(text, 5, 9, "Paper 5") == rows


def test_rejects_short_paper_without_padding():
    with pytest.raises(ValueError, match="only 199 words"):
        split_chunks("short " * 199, 1, 1, "Paper 1")


def test_complete_utf8_row_size_at_limit():
    overhead = require_row_fits(CHUNK_SCHEMA, (1, 1, 1, ""), "chunk")
    pairs, remainder = divmod(MAX_RECORD_SIZE - overhead, 2)
    content = "é" * pairs + "x" * remainder
    assert require_row_fits(CHUNK_SCHEMA, (1, 1, 1, content), "chunk") == MAX_RECORD_SIZE
    with pytest.raises(ValueError, match=rf"{MAX_RECORD_SIZE + 1} bytes"):
        require_row_fits(CHUNK_SCHEMA, (1, 1, 1, content + "x"), "chunk")


def test_rebalances_for_bytes_and_rejects_impossible_rows():
    word = "é" * 9
    text = " ".join([word] * 1000)
    rows = split_chunks(text, 1, 1, "Paper 1")
    assert [len(row[3].split()) for row in rows] == [200] * 5
    assert " ".join(row[3] for row in rows) == text
    with pytest.raises(ValueError, match="no balanced split"):
        split_chunks(("é" * 20 + " ") * 200, 1, 1, "Paper 1")


def test_prepares_reproducible_companion_and_indexed_rows(inputs, tmp_path):
    manifest, pdf_dir, entries = inputs
    dest = tmp_path / "database"
    report = prepare_academic(manifest, pdf_dir, dest)
    assert report["status"] == "PASS"
    assert report["rows_match_inputs"]
    assert (report["papers"], report["chunks"]) == (2, 4)
    assert [paper["paper_id"] for paper in report["per_paper"]] == [2, 8]
    manifest.write_text(json.dumps(entries[::-1]), encoding="utf-8")
    reordered = prepare_academic(manifest, pdf_dir, tmp_path / "reordered")
    assert reordered["logical_sha256"] == report["logical_sha256"]

    with pytest.raises(FileExistsError, match="already exists"):
        prepare_academic(manifest, pdf_dir, dest)
    for pdf in pdf_dir.iterdir():
        pdf.unlink()
    cli = Path(__file__).resolve().parents[2] / "scripts" / "setup_academic.py"
    run = subprocess.run(
        [sys.executable, "-X", "utf8", str(cli), "--verify-only", "--data-dir", str(dest)],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    fresh = json.loads(run.stdout)
    assert fresh["status"] == "PASS"
    for key in ("logical_sha256", "index_generation", "per_paper", "registration"):
        assert fresh[key] == report[key]
    assert fresh["registration"] == "chunks.content"


def test_duplicate_names_rejected_before_creating_destination(tmp_path):
    destination = tmp_path / "database"
    chunks = NewTable("chunks", CHUNK_COLUMNS)
    with pytest.raises(DuplicateError, match="distinct names"):
        Database.prepare_text(destination, [(chunks, [], "chunk_id", "content")],
                              companion_tables=[(chunks, [])])
    assert not destination.exists()


def test_text_preparation_without_companions(tmp_path):
    directory = tmp_path / "part3"
    papers = NewTable("papers", PAPER_COLUMNS)
    Database.prepare_text(directory, [(papers, [(1, "Author", 2020, "Title", "Text")],
                                       "paper_id", "abstract")])
    assert [(item.table, item.column) for item in read_text_registry(directory)] == [
        ("papers", "abstract"),
    ]
    with Database.open(DatabaseDefinition("text"), directory) as database:
        assert database.table_names() == ("papers",)
        assert database.describe_table("papers").row_count == 1


def test_publication_failure_releases_owner_and_reports_failure(inputs, tmp_path, monkeypatch, capsys):
    manifest, pdf_dir, _ = inputs
    dest = tmp_path / "failed"

    def fail(*args, **kwargs):
        raise OSError("injected publication failure")

    monkeypatch.setattr("engine.text.build_spimi", fail)
    assert main(["--manifest", str(manifest), "--pdf-dir", str(pdf_dir),
                 "--data-dir", str(dest)]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert "injected publication failure" in output.err
    assert not read_text_registry(dest)
    with Database.open(DatabaseDefinition("text"), dest) as database:
        assert set(database.table_names()) == {"papers", "chunks"}
