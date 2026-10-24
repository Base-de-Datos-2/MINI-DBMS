"""Offline Part 3 corpus acceptance; run from the repository root."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.text.sources import acquire  # noqa: E402
from benchmarks.text.corpus import (member_stream, prepare_preflight, select_queries, validate_documents, validate_source_binding)  # noqa: E402
from benchmarks.text.sources import file_hash, write_json  # noqa: E402
from benchmarks.text.esci import acquire_esci, esci_preflight, esci_documents, parquet_rows  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    download = subparsers.add_parser("download", help="verify/download official v1 passage files")
    download.add_argument("--source-dir", type=Path, required=True)
    download.add_argument("--split", choices=("dev", "train"), default="dev")
    download.add_argument("--metadata-only", action="store_true", help="download query/qrels files only")
    esci = subparsers.add_parser("download-esci", help="download pinned official ESCI replacement sources")
    esci.add_argument("--source-dir", type=Path, required=True)
    esci.add_argument("--metadata-only", action="store_true")
    for command in ("preflight", "validate", "select"):
        action = subparsers.add_parser(command)
        action.add_argument("--source-dir", type=Path, required=True)
        action.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command in {"download", "download-esci"}:
        manifest = (acquire(args.source_dir, args.split, not args.metadata_only) if args.command == "download"
                    else acquire_esci(args.source_dir, args.metadata_only))
        print(json.dumps({"files": [{"name": item["filename"], "bytes": item["downloaded_bytes"]}
                                    for item in manifest["files"]], "corpus_acceptance": "PENDING"}))
    elif args.command == "preflight":
        manifest = json.loads((args.source_dir / "source_manifest.json").read_text(encoding="utf-8"))
        report = (esci_preflight(args.source_dir, args.output_dir) if "ESCI" in manifest["dataset"]
                  else prepare_preflight(args.source_dir, args.output_dir))
        print(json.dumps({key: report[key] for key in ("status", "query_count", "judgment_count", "eligible_counts")}))
        return 0 if report["status"] == "PASS" else 1
    elif args.command == "validate":
        preflight = json.loads((args.output_dir / "query_preflight.json").read_text(encoding="utf-8"))
        if preflight["status"] != "PASS":
            parser.error("Query preflight failed; choose a compatible source before scanning documents")
        manifest = json.loads((args.source_dir / "source_manifest.json").read_text(encoding="utf-8"))
        validate_source_binding(manifest, preflight)
        is_esci = "ESCI" in manifest["dataset"]
        collection = next(item for item in manifest["files"] if item["role"] == ("products" if is_esci else "collection"))
        source = args.source_dir / collection["filename"]
        if file_hash(source) != collection["sha256"]:
            parser.error("Collection source hash mismatch")
        preflight_hash = file_hash(args.output_dir / "query_preflight.json")
        wanted = {positive["id"] for query in preflight["candidates"] for positive in query["positives"]}
        if is_esci:
            records = esci_documents(parquet_rows(source, ["product_id", "product_locale", "product_title"]), manifest["locale"])
            report = validate_documents(records, args.output_dir, wanted)
        else:
            with member_stream(source, "collection.tsv") as stream:
                report = validate_documents(stream, args.output_dir, wanted)
        report["preflight_sha256"] = preflight_hash
        report["dataset"] = preflight["dataset"]
        report["source_sha256"] = {**preflight["source_sha256"], collection["role"]: collection["sha256"]}
        write_json(args.output_dir / "document_validation.json", report)
        print(json.dumps({key: report[key] for key in ("status", "scanned_rows", "accepted_pool_rows", "codec_validated_rows", "rejections")}))
        return 0 if report["status"] == "PASS" else 1
    else:
        preflight = json.loads((args.output_dir / "query_preflight.json").read_text(encoding="utf-8"))
        validation = json.loads((args.output_dir / "document_validation.json").read_text(encoding="utf-8"))
        manifest = json.loads((args.source_dir / "source_manifest.json").read_text(encoding="utf-8"))
        validate_source_binding(manifest, preflight)
        report = select_queries(preflight, validation, args.output_dir)
        print(json.dumps({key: report[key] for key in ("status", "selected_counts", "positive_union_count", "corpus_acceptance")}))
        return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
