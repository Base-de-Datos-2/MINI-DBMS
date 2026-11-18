"""Protect the explicit legacy-font extraction path and original abstracts."""

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.academic_corpus import PaperSource, extract_pdf
from tests.part5.test_ingestion import write_pdf


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "legacy.pdf"
    write_pdf(path, "Café first", "Second page")
    return PaperSource(
        path, sha256(path.read_bytes()).hexdigest(),
        (12, "Author", 1995, "Title", "Full abstract"), "pdftotext",
    )


def test_poppler_extracts_real_pdf_pages_in_order(source):
    if shutil.which("pdftotext") is None:
        pytest.skip("Install Poppler to run the selected legacy-font extractor")
    assert extract_pdf(source) == ("Café first Second page", 2, 0)


@pytest.mark.parametrize("failure", [
    FileNotFoundError(),
    subprocess.CalledProcessError(1, ["pdftotext"]),
    subprocess.TimeoutExpired(["pdftotext"], 60),
])
def test_selected_extractor_failure_is_explicit(source, monkeypatch, failure):
    def fail(command, **kwargs):
        assert command == ["pdftotext", "-enc", "UTF-8", "-eol", "unix", "-", "-"]
        assert kwargs["input"] == source.path.read_bytes()
        assert kwargs["timeout"] == 60
        raise failure

    monkeypatch.setattr("scripts.academic_corpus.subprocess.run", fail)
    with pytest.raises(ValueError, match=r"Paper 12 \(legacy.pdf\).*could not extract"):
        extract_pdf(source)


def test_poppler_page_count_must_match_the_actual_pdf(source, monkeypatch):
    monkeypatch.setattr(
        "scripts.academic_corpus.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"only one page\f"),
    )
    with pytest.raises(ValueError, match="page count differs"):
        extract_pdf(source)


def test_hash_failure_prevents_external_extraction(source, monkeypatch):
    source.path.write_bytes(source.path.read_bytes() + b"changed")
    monkeypatch.setattr(
        "scripts.academic_corpus.subprocess.run",
        lambda *args, **kwargs: pytest.fail("Hash mismatch reached pdftotext"),
    )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        extract_pdf(source)


def test_extra_manifest_keeps_complete_abstracts_and_explicit_extractors():
    manifest = Path(__file__).resolve().parents[2] / "PART_05" / "corpus_extra.json"
    entries = {entry["paper_id"]: entry for entry in json.loads(manifest.read_text(encoding="utf-8"))}
    assert entries[11].get("text_extractor", "pypdf") == "pypdf"
    assert entries[12]["text_extractor"] == entries[13]["text_extractor"] == "pdftotext"
    assert entries[11]["abstract"].endswith(
        "considering an overall concave term frequency in the context of ad hoc IR."
    )
    assert "The two successes have been in query expansion and in routing term selection." in entries[12]["abstract"]
    assert entries[13]["abstract"].startswith("The importance of a Web page")
    assert entries[13]["abstract"].endswith("apply PageRank to search and to user navigation.")
    assert entries[12]["abstract_source_url"].startswith("https://pages.nist.gov/")
    assert entries[13]["year"] == 1998
    assert all(not any(ord(character) < 32 for character in entry["abstract"]) for entry in entries.values())
