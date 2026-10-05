"""Check result completeness, analytic counts and archived source provenance."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

from benchmarks.spatial.results import digest, positive_number, require


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def validate_rows(rows, sizes, repetitions):
    keys = set()
    for row in rows:
        size, repetition, operation = row["size"], row["repetition"], row["operation"]
        require(size in sizes and repetition in range(1, repetitions + 1), "Unexpected repetition context")
        key = size, repetition, row["experiment"], row["structure"], operation, row.get("selectivity")
        require(key not in keys, "Duplicate measurement")
        keys.add(key)
        require(positive_number(row["elapsed_seconds"]), "Invalid measured time")
        count = row["count"]
        require(type(count) is int and count > 0, "Invalid operation count")
        require(abs(row["per_operation_ms"] - row["elapsed_seconds"] * 1000 / count) < 1e-9,
                "Incorrect unit conversion")
        if operation in {"pk_search_present", "pk_search_absent", "equality_present", "equality_absent"}:
            require(row["found"] == (count if operation.endswith("present") else 0), "Incorrect lookup count")
        elif operation == "range":
            require(row["rows_returned"] == count * max(1, int(size * row["selectivity"])),
                    "Incorrect analytic range count")
        elif operation in {"load", "load_ascending", "build", "ordered_retrieval"}:
            require(count == size, "Incomplete dataset consumption")
            if operation == "build":
                require(row["entry_count"] == size and row["index_bytes"] > 0, "Incomplete built index")
        elif operation in {"delete_fraction", "reinsert_after_delete"}:
            require(count == int(size * .4), "Incorrect deletion/reinsertion count")
        elif operation == "reorganize":
            require(count == size - int(size * .4) and row["wasted_space_ratio"] == 0,
                    "Incorrect reorganization result")
        elif operation == "insert_delete_workload":
            require(row["valid"] is True and count == row["inserted"] + row["deleted"]
                    and row["entry_count"] == size + row["inserted"] - row["deleted"],
                    "Inconsistent mixed workload")
        else:
            raise ValueError("Unexpected measured operation")
    expected = set()
    files = {"heap": ("load", "pk_search_present", "pk_search_absent", "delete_fraction", "reinsert_after_delete"),
             "sequential": ("load", "load_ascending", "pk_search_present", "pk_search_absent", "delete_fraction", "reorganize")}
    for size in sizes:
        for repetition in range(1, repetitions + 1):
            for structure, operations in files.items():
                expected.update((size, repetition, "file_organization", structure, operation, None) for operation in operations)
            for structure in ("clustered_bplus", "unclustered_bplus", "extendible_hash"):
                expected.update((size, repetition, "indexes", structure, operation, None) for operation in
                                ("build", "equality_present", "equality_absent", "ordered_retrieval", "insert_delete_workload"))
                expected.update((size, repetition, "indexes", structure, "range", selectivity)
                                for selectivity in (.001, .01, .1))
    require(keys == expected, "Missing or unexpected measurement configurations")


def archived_digest(archive):
    members = {member.name: member for member in archive.getmembers() if member.isfile() and member.name.endswith(".py")}
    result = hashlib.sha256()
    for root in ("engine", "benchmarks"):
        for name in sorted(name for name in members if name.startswith(root + "/")):
            result.update(name.encode())
            with archive.extractfile(members[name]) as source:
                result.update(source.read())
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fresh = args.repository / "benchmarks/results/relational/2026-10-04"
    metadata = json.loads((fresh / "completed.json").read_text(encoding="utf-8"))
    rows = read_rows(fresh / "results.jsonl")
    validate_rows(rows, (1000, 10000), 5)
    require(digest(fresh / "results.jsonl") == metadata["results_sha256"], "Raw result checksum mismatch")
    require(digest(fresh / "driver.py") == metadata["driver_sha256"], "Driver checksum mismatch")
    require(digest(fresh / "source.tar.gz") == metadata["source_snapshot"]["archive_sha256"], "Source checksum mismatch")
    with tarfile.open(fresh / "source.tar.gz", "r:gz") as archive:
        require(archived_digest(archive) == metadata["environment"]["source_sha256"], "Measured source digest mismatch")
    require(all(row["environment"] == metadata["environment"] for row in rows), "Mixed code/environment provenance")
    for name, expected in metadata["figure_sha256"].items():
        require(digest(args.repository / "docs/experimentos/actualizados_1k_10k" / name) == expected,
                "Figure checksum mismatch")
    old_paths = [args.repository / "benchmarks/results" / f"part1_results_100k_{kind}.jsonl"
                 for kind in ("files", "indexes")]
    historical = [row for path in old_paths for row in read_rows(path)]
    validate_rows(historical, (100000,), 3)
    commits = {row["environment"]["git_commit"] for row in historical}
    require(len(commits) == 1, "Historical 100k sources differ")
    commit = next(iter(commits))
    archive_bytes = subprocess.run(["git", "-C", str(args.repository), "archive", commit, "engine", "benchmarks"],
                                   check=True, stdout=subprocess.PIPE).stdout
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        old_digest = archived_digest(archive)
    require(all(row["environment"]["source_sha256"] == old_digest for row in historical),
            "Historical 100k source cannot be recovered from Git")
    result = {"new_rows": len(rows), "historical_100000_rows": len(historical),
              "new_source_archive_verified": True, "new_analytic_counts_verified": True,
              "historical_source_commit": commit, "historical_source_digest_verified": old_digest,
              "historical_times_not_claimed_current": True,
              "raw_sha256": {str(path.relative_to(args.repository)): digest(path)
                             for path in [fresh / "results.jsonl", *old_paths]}}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
