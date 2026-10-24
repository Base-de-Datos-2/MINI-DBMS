"""Amazon ESCI replacement candidate; Parquet is decoded only as input data."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import urllib.request

from engine.text import tokenize

from .corpus import preflight
from .sources import fetch_source, file_hash, write_json


REPOSITORY = "https://github.com/amazon-science/esci-data"
FILENAMES = {role: f"shopping_queries_dataset_{role}.parquet" for role in ("examples", "products")}
GRADES = {"I": 0, "C": 1, "S": 2, "E": 3}


def acquire_esci(directory, examples_only=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "source_manifest.json"
    if manifest_path.exists():
        revision = json.loads(manifest_path.read_text(encoding="utf-8"))["revision"]
    else:
        request = urllib.request.Request("https://api.github.com/repos/amazon-science/esci-data/commits/main",
                                         headers={"User-Agent": "MINI-DBMS-academic-corpus-preparation"})
        with urllib.request.urlopen(request, timeout=30) as response:
            revision = json.load(response)["sha"]
    base = f"https://media.githubusercontent.com/media/amazon-science/esci-data/{revision}/shopping_queries_dataset/"
    roles = ["examples"] if examples_only else ["examples", "products"]
    def download(role):
        return fetch_source(directory, role, url=base + FILENAMES[role], filename=FILENAMES[role])
    with ThreadPoolExecutor(max_workers=2) as pool:
        files = list(pool.map(download, roles))
    manifest = {
        "format_version": 1, "dataset": "Amazon Shopping Queries Dataset (ESCI)",
        "version": "large_version", "revision": revision, "split": "test", "locale": "us",
        "documentation": REPOSITORY, "files": files,
        "terms": {"url": f"{REPOSITORY}/blob/{revision}/LICENSE", "license": "Apache-2.0",
                  "citation": "Reddy et al. (2022), Shopping Queries Dataset, arXiv:2206.06588"},
        "indexed_field": "product_title (entire original field, unchanged)",
        "id_mapping": "fixed-width uppercase 10-character ASIN interpreted as base36 integer; source_id retained",
        "relevance_mapping": GRADES, "positive_rule": "all supplied labels with grade > 0 (C,S,E)",
        "compatibility": "same pinned repository revision; join products by (product_locale, product_id)",
        "candidate_approved": False, "corpus_acceptance": "PENDING",
    }
    write_json(manifest_path, manifest)
    return manifest


def asin_id(value):
    if not isinstance(value, str) or len(value) != 10 or any(character not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" for character in value):
        raise ValueError("ASIN must have exactly 10 uppercase base36 characters")
    return int(value, 36)


def parquet_rows(path, columns):
    try:
        from pyarrow.parquet import ParquetFile
    except ImportError as error:
        raise RuntimeError("Parquet preparation requires the optional corpus dependency: pip install -e '.[corpus]'") from error
    with ParquetFile(path) as source:
        for batch in source.iter_batches(batch_size=4096, columns=columns, use_threads=False):
            yield from batch.to_pylist()


def esci_queries(rows, locale="us", split="test"):
    queries, judgments = {}, {}
    for row in rows:
        if row["product_locale"] != locale or row["split"] != split or not row["large_version"]:
            continue
        qid = row["query_id"]
        if type(qid) is not int or not isinstance(row["query"], str):
            raise ValueError("Invalid ESCI original query")
        query = {"id": qid, "text": row["query"], "length": len(tokenize(row["query"]))}
        if qid in queries and queries[qid] != query:
            raise ValueError("ESCI query ID has inconsistent original texts")
        queries[qid] = query
        if row["esci_label"] not in GRADES:
            raise ValueError("Unknown ESCI relevance label")
        pid, grade = asin_id(row["product_id"]), GRADES[row["esci_label"]]
        if (qid, pid) in judgments and judgments[qid, pid] != grade:
            raise ValueError("Conflicting ESCI relevance judgments")
        judgments[qid, pid] = grade
    return queries, judgments


def esci_documents(rows, locale="us"):
    for row in rows:
        if row["product_locale"] == locale:
            yield {"id": asin_id(row["product_id"]), "source_id": row["product_id"],
                   "text": row["product_title"]}


def esci_preflight(source_dir, output_dir):
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / "query_preflight.json").exists():
        raise FileExistsError("Query preflight already exists; use a fresh preparation directory")
    manifest = json.loads((source_dir / "source_manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("version"), manifest.get("split"), manifest.get("locale")) != ("large_version", "test", "us"):
        raise ValueError("Unsupported ESCI version/split/locale association")
    item = next(item for item in manifest["files"] if item["role"] == "examples")
    if item["filename"] != FILENAMES["examples"]:
        raise ValueError("ESCI source filename disagrees with source role")
    source = source_dir / item["filename"]
    if file_hash(source) != item["sha256"]:
        raise ValueError("ESCI example source hash mismatch")
    columns = ["query_id", "query", "product_id", "product_locale", "split", "large_version", "esci_label"]
    queries, judgments = esci_queries(parquet_rows(source, columns), manifest["locale"], manifest["split"])
    report = preflight(queries, judgments)
    report["dataset"] = {key: manifest[key] for key in ("dataset", "version", "revision", "split", "locale")}
    report["source_sha256"] = {"examples": item["sha256"]}
    write_json(output_dir / "query_preflight.json", report)
    return report
