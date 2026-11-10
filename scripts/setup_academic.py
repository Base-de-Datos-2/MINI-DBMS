"""Prepare or verify the offline Part 5 academic database."""

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from api.database import Database, DatabaseDefinition, NewTable
from engine.errors import DatabaseError
from engine.storage.binary import MAX_RECORD_SIZE
from engine.text.registry import read_text_registry
from scripts.academic_corpus import (
    CHUNK_COLUMNS, CHUNK_SCHEMA, MAX_WORDS, MIN_WORDS, PAPER_COLUMNS,
    extract_pdf, load_manifest, require_id, require_row_fits, split_chunks, validate_paper,
)


def _read_rows(database, table, columns):
    summary = database.describe_table(table)
    expected_columns = tuple((name, kind.value) for name, kind in columns)
    expected_indexes = [] if table == "papers" else [("SPIMI", "content")]
    actual_indexes = [(index.index_type, index.column) for index in summary.indexes]
    if summary.organization != "HEAP" or summary.columns != expected_columns:
        raise ValueError(f"Unexpected schema or storage organization for {table}")
    if actual_indexes != expected_indexes:
        raise ValueError(f"Unexpected indexes for {table}")
    names = ", ".join(name for name, _ in columns)
    with database.engine.execute(f"SELECT {names} FROM {table} ORDER BY {columns[0][0]};") as result:
        rows = [tuple(row.values) for row in result]
    if len(rows) != summary.row_count:
        raise ValueError(f"{table}: SQL rows differ from the stored row count")
    return rows


def _measure(papers, chunks):
    if not papers:
        raise ValueError("Academic database must contain papers")
    measurements = {}
    for row in papers:
        paper_id = row[0]
        size = validate_paper(row, f"Stored paper {paper_id}")
        if paper_id in measurements:
            raise ValueError(f"Duplicate stored paper_id {paper_id}")
        measurements[paper_id] = {"paper_id": paper_id, "metadata_bytes": size, "chunks": 0,
                                  "min_words": MAX_WORDS, "max_words": 0, "max_chunk_bytes": 0}

    previous_paper = 0
    for expected_id, row in enumerate(chunks, 1):
        chunk_id, paper_id, position, content = row
        label = f"Stored chunk {chunk_id} (paper {paper_id})"
        require_id(chunk_id, label)
        stats = measurements.get(paper_id)
        if chunk_id != expected_id or stats is None or paper_id < previous_paper:
            raise ValueError(f"{label}: invalid global ID order or paper association")
        if position != stats["chunks"] + 1:
            raise ValueError(f"{label}: positions must be consecutive and one-based")
        words = content.split()
        if not MIN_WORDS <= len(words) <= MAX_WORDS or " ".join(words) != content:
            raise ValueError(f"{label}: expected normalized text with {MIN_WORDS}–{MAX_WORDS} words")
        size = require_row_fits(CHUNK_SCHEMA, row, label)
        stats["chunks"] += 1
        stats["min_words"] = min(stats["min_words"], len(words))
        stats["max_words"] = max(stats["max_words"], len(words))
        stats["max_chunk_bytes"] = max(stats["max_chunk_bytes"], size)
        previous_paper = paper_id

    for stats in measurements.values():
        if not stats["chunks"]:
            raise ValueError(f"Stored paper {stats['paper_id']} has no chunks")
    per_paper = list(measurements.values())
    return {
        "papers": len(papers), "chunks": len(chunks), "per_paper": per_paper,
        "min_chunk_words": min(item["min_words"] for item in per_paper),
        "max_chunk_words": max(item["max_words"] for item in per_paper),
        "max_chunk_bytes": max(item["max_chunk_bytes"] for item in per_paper),
        "max_metadata_bytes": max(item["metadata_bytes"] for item in per_paper),
        "record_limit_bytes": MAX_RECORD_SIZE,
        "logical_sha256": sha256(json.dumps([papers, chunks], ensure_ascii=False).encode("utf-8")).hexdigest(),
    }


def verify_database(directory: Path, *, expected=None):
    with Database.open(DatabaseDefinition("text"), directory) as database:
        if set(database.table_names()) != {"papers", "chunks"}:
            raise ValueError("Academic database must contain exactly papers and chunks")
        registrations = read_text_registry(directory)
        if [(entry.table, entry.column) for entry in registrations] != [("chunks", "content")]:
            raise ValueError("Academic database must publish only chunks.content")
        papers = _read_rows(database, "papers", PAPER_COLUMNS)
        chunks = _read_rows(database, "chunks", CHUNK_COLUMNS)
        if expected is not None and (papers, chunks) != expected:
            raise ValueError("Reopened academic rows differ from validated input rows")
        measurements = _measure(papers, chunks)

        environment = database.engine.environment
        index = environment.text_for("chunks")
        storage = environment.storage_for("chunks")
        if index is None or index.id_column != "chunk_id" or not storage.read_only:
            raise ValueError("Academic index requires chunk_id and sealed chunks storage")
        if environment.storage_for("papers").read_only:
            raise ValueError("Academic metadata must remain an ordinary Heap table")
        index.validate()
        index.verify_storage(storage)
    return {
        "status": "PASS", "directory": str(directory), "registration": "chunks.content",
        "index_generation": registrations[0].generation, **measurements,
    }


def prepare_academic(manifest: Path, pdf_dir: Path, directory: Path):
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(f"Destination already exists: {directory}. Choose a fresh directory.")
    papers, chunks, sources = [], [], []
    for source in load_manifest(manifest, pdf_dir):
        paper_id = source.row[0]
        text, pages, empty_pages = extract_pdf(source)
        label = f"Paper {paper_id} ({source.path.name})"
        rows = split_chunks(text, paper_id, len(chunks) + 1, label)
        if " ".join(row[3] for row in rows) != text:
            raise ValueError(f"{label}: chunks do not reconstruct the normalized text")
        papers.append(source.row)
        chunks.extend(rows)
        sources.append({
            "paper_id": paper_id, "pdf": source.path.name, "pages": pages,
            "empty_text_pages": empty_pages, "input_sha256": source.digest,
            "first_chunk_id": rows[0][0], "last_chunk_id": rows[-1][0],
        })

    Database.prepare_text(
        directory, [(NewTable("chunks", CHUNK_COLUMNS), chunks, "chunk_id", "content")],
        companion_tables=[(NewTable("papers", PAPER_COLUMNS), papers)],
    )
    report = verify_database(directory, expected=(papers, chunks))
    return {**report, "pdfs": len(sources), "extractor": f"pypdf {version('pypdf')}",
            "input_hashes_verified": True, "rows_match_inputs": True, "sources": sources}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pdf-dir", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_only and (args.manifest is not None or args.pdf_dir is not None):
        parser.error("--verify-only uses only --data-dir")
    if not args.verify_only and (args.manifest is None or args.pdf_dir is None):
        parser.error("preparation requires --manifest and --pdf-dir")
    try:
        if args.verify_only:
            report = verify_database(args.data_dir)
        else:
            report = prepare_academic(args.manifest, args.pdf_dir, args.data_dir)
    except (DatabaseError, OSError, ValueError) as error:
        print(f"Academic {'verification' if args.verify_only else 'preparation'} failed "
              f"for {args.data_dir}: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"mode": "verify-only" if args.verify_only else "prepare", **report},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
