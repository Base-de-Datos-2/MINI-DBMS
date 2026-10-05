"""Ensure a fresh Git checkout preserves experimental evidence checksums."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    roots = ("benchmarks/results/spatial/2026-10-04", "docs/figuras/spatial",
             "benchmarks/results/relational/2026-10-04", "docs/experimentos/actualizados_1k_10k")
    data = subprocess.run(["git", "-C", str(args.repository), "archive", "HEAD", *roots],
                          check=True, stdout=subprocess.PIPE).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        contents = {member.name: archive.extractfile(member).read() for member in archive.getmembers()
                    if member.isfile()}
    verification = json.loads(contents[roots[1] + "/verificacion.json"])
    checked = []
    for root, section in zip(roots, ("input_sha256", "output_sha256")):
        for name, expected in verification[section].items():
            path = root + "/" + name
            actual = hashlib.sha256(contents[path]).hexdigest()
            if actual != expected:
                raise ValueError(f"Git changes evidence bytes: {path}")
            checked.append(path)
    relational = json.loads(contents[roots[2] + "/completed.json"])
    expected_files = {roots[2] + "/results.jsonl": relational["results_sha256"],
                      roots[2] + "/driver.py": relational["driver_sha256"],
                      roots[2] + "/source.tar.gz": relational["source_snapshot"]["archive_sha256"],
                      **{roots[3] + "/" + name: expected for name, expected in relational["figure_sha256"].items()}}
    for path, expected in expected_files.items():
        if hashlib.sha256(contents[path]).hexdigest() != expected:
            raise ValueError(f"Git changes evidence bytes: {path}")
        checked.append(path)
    result = {"git_blob_checksums_verified": len(checked), "paths": checked}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(checked)} archived Git artifacts")


if __name__ == "__main__":
    main()
