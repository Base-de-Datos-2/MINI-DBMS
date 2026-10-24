"""Explicit MS MARCO v1 passage downloads; never imported by the engine."""

from concurrent.futures import ThreadPoolExecutor
from collections import deque
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import urllib.request


DATASET_PAGE = "https://microsoft.github.io/msmarco/Datasets.html"
BASE_URL = "https://msmarco.z22.web.core.windows.net/msmarcoranking/"
FILES = {"collection": "collection.tar.gz", "queries": "queries.tar.gz",
         "qrels_dev": "qrels.dev.tsv", "qrels_train": "qrels.train.tsv"}
PUBLISHED_SIZES = {"collection": "2.9 GB", "queries": "42.0 MB",
                   "qrels_dev": "1.1 MB", "qrels_train": "10.1 MB"}


def write_json(path, document):
    """Write a complete report without leaving an apparently valid partial JSON."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def file_hash(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_source(directory, role, *, url=None, filename=None, published_size=None):
    """Verify remote metadata, then download/reuse bytes with a content hash."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    filename = filename or FILES[role]
    if Path(filename).name != filename:
        raise ValueError("Source filename must be a basename")
    destination = directory / filename
    receipt_path = directory / (filename + ".receipt.json")
    url = url or BASE_URL + filename
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as response:
        size = int(response.headers["Content-Length"])
        etag = response.headers.get("ETag")
        metadata = {"role": role, "filename": filename, "url": url, "http_status": response.status,
                    "published_size_label": published_size or PUBLISHED_SIZES.get(role, "not specified"), "content_length": size,
                    "etag": etag, "last_modified": response.headers.get("Last-Modified"),
                    "verified_at_utc": datetime.now(timezone.utc).isoformat()}
    expected_lfs_hash = (etag.strip('"') if "media.githubusercontent.com/" in url and etag
                         and len(etag.strip('"')) == 64 else None)
    if destination.exists():
        if not receipt_path.is_file():
            raise ValueError(f"Existing source has no download receipt: {filename}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        digest = file_hash(destination)
        if destination.stat().st_size != size or receipt.get("url") != url or receipt.get("etag") != etag or receipt.get("sha256") != digest:
            raise ValueError(f"Existing source disagrees with remote metadata or hash: {filename}")
        if expected_lfs_hash and digest != expected_lfs_hash:
            raise ValueError("Existing source disagrees with the pinned Git LFS SHA-256")
        return {**metadata, "sha256": digest, "downloaded_bytes": size}
    temporary = directory / (filename + ".partial")
    digest = sha256()
    transferred = 0
    resume = temporary.exists() and expected_lfs_hash is not None
    if resume:
        # A strong upstream content hash permits reusing untrusted partial bytes:
        # the entire completed file must still match that hash before publication.
        if temporary.stat().st_size > size:
            raise ValueError("Partial download exceeds the verified source length")
        with temporary.open("rb") as partial:
            for chunk in iter(lambda: partial.read(1024 * 1024), b""):
                digest.update(chunk)
                transferred += len(chunk)
    owned_partial = False
    try:
        with temporary.open("ab" if resume else "xb") as output:
            owned_partial = not resume
            # Explicit ranges avoid stalled whole-object responses from the
            # static Azure endpoint and keep each network read bounded.
            chunk_size = 8 * 1024 * 1024
            def read_range(start):
                end = min(start + chunk_size, size) - 1
                headers = {"Range": f"bytes={start}-{end}"}
                if etag:
                    headers["If-Match"] = etag
                request = urllib.request.Request(url, headers=headers)
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(request, timeout=60) as response:
                            if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                                raise ValueError("Server did not honor the requested byte range")
                            if response.headers.get("ETag") != etag:
                                raise ValueError("Source changed between HEAD and GET")
                            data = response.read(end - start + 1)
                            if len(data) != end - start + 1:
                                raise ValueError("Truncated source range")
                            return data
                    except OSError:
                        if attempt == 2:
                            raise
            # Sixteen bounded blocks (128 MiB), not the full source in memory.
            starts = iter(range(transferred, size, chunk_size))
            with ThreadPoolExecutor(max_workers=16) as pool:
                pending = deque(pool.submit(read_range, start) for start in [next(starts, None) for _ in range(16)] if start is not None)
                while pending:
                    data = pending.popleft().result()
                    output.write(data)
                    digest.update(data)
                    transferred += len(data)
                    start = next(starts, None)
                    if start is not None:
                        pending.append(pool.submit(read_range, start))
        if transferred != size:
            raise ValueError("Download length disagrees with verified Content-Length")
        metadata.update(sha256=digest.hexdigest(), downloaded_bytes=transferred)
        if expected_lfs_hash and metadata["sha256"] != expected_lfs_hash:
            raise ValueError("Downloaded bytes disagree with the pinned Git LFS SHA-256")
        temporary.replace(destination)
        write_json(receipt_path, metadata)
        return metadata
    except BaseException:
        # Only this operation's newly created partial file may be removed.
        # A pre-existing partial indicates an interrupted run and is retained.
        if owned_partial:
            temporary.unlink(missing_ok=True)
        raise


def acquire(directory, split="dev", include_collection=True):
    if split not in {"dev", "train"}:
        raise ValueError("Passage split must be dev or train")
    roles = ["queries", "qrels_" + split]
    if include_collection:
        roles.append("collection")
    with ThreadPoolExecutor(max_workers=3) as pool:
        files = list(pool.map(lambda role: fetch_source(directory, role), roles))
    manifest = {
        "format_version": 1, "dataset": "MS MARCO passage ranking", "version": "v1",
        "split": split, "documentation": DATASET_PAGE,
        "terms": {"url": DATASET_PAGE + "#terms-and-conditions",
                  "summary": "Non-commercial research only; provided as-is; no underlying IP rights granted.",
                  "citation": "Bajaj et al. (2016), arXiv:1611.09268"},
        "query_member": f"queries.{split}.tsv", "qrels_format": "qid iteration pid relevance",
        "collection_member": "collection.tsv", "files": files,
        "compatibility": "v1 passage IDs and matching query/qrels split; references require local validation",
        "candidate_approved": False, "corpus_acceptance": "PENDING",
    }
    write_json(Path(directory) / "source_manifest.json", manifest)
    return manifest
