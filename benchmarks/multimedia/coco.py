"""Acquire the Part 4 COCO 2017 image corpus within the measured storage limit.

The host has about 32 GB of free physical storage, so ``train2017.zip``
(19.3 GB) plus its extraction does not fit. Instead:

1. ``captions_train2017.json`` (inside the annotations zip) supplies the image
   list, licenses and URLs; it is much smaller than ``instances_*``.
2. A seeded permutation of all train2017 image ids defines the candidates. The
   first accepted images form the nested 1,000 ⊂ 10,000 ⊂ 100,000 gallery;
   the 30 query and 50 tuning images come from the end of the permutation, so
   they are disjoint from the gallery by id.
3. Each original is downloaded, hashed (SHA-256) and decoded; an
   aspect-preserving color copy with longest side <= 512 px is stored as JPEG
   quality 90. The stored copy is the collection's media file: features are
   computed from it for gallery and queries alike.

Resumable: ``download.jsonl`` holds one record per attempted image, and a
rerun skips ids already recorded. Byte-identical originals are rejected as
duplicates. Run:

    python -m benchmarks.multimedia.coco --output data/generated/multimedia/coco
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import random
import threading
import time
import urllib.request
import zipfile

ANNOTATIONS_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
CAPTIONS_MEMBER = "annotations/captions_train2017.json"
SEED = 20_261_106
GALLERY_SIZE = 100_000
QUERY_COUNT = 30
TUNING_COUNT = 50
MAX_SIDE = 512
JPEG_QUALITY = 90
USER_AGENT = "mini-dbms-coursework/1.0"


def fetch(url: str, timeout: float = 60.0, attempts: int = 4) -> bytes:
    last = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as error:  # network errors are retried, then recorded
            last = error
            time.sleep(1.5 * (attempt + 1))
    raise last


def catalog(output: Path) -> dict:
    """Return {'images': [...], 'licenses': {...}} from the captions file."""
    target = output / "captions_train2017.json"
    if not target.exists():
        archive = output / "annotations_trainval2017.zip"
        if not archive.exists():
            archive.write_bytes(fetch(ANNOTATIONS_URL, timeout=600))
        with zipfile.ZipFile(archive) as bundle:
            target.write_bytes(bundle.read(CAPTIONS_MEMBER))
        archive.unlink()
    payload = json.loads(target.read_text(encoding="utf-8"))
    licenses = {item["id"]: {"name": item["name"], "url": item["url"]} for item in payload["licenses"]}
    images = sorted(({"id": item["id"], "file_name": item["file_name"], "coco_url": item["coco_url"],
                      "flickr_url": item.get("flickr_url"), "license": item["license"],
                      "width": item["width"], "height": item["height"]}
                     for item in payload["images"]), key=lambda item: item["id"])
    return {"images": images, "licenses": licenses, "captions_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def permutation(images: list[dict]) -> list[dict]:
    order = list(images)
    random.Random(SEED).shuffle(order)
    return order


def store(image: dict, directory: Path) -> dict:
    import cv2
    import numpy as np

    record = {"coco_id": image["id"], "file_name": image["file_name"], "coco_url": image["coco_url"],
              "license": image["license"]}
    try:
        data = fetch(image["coco_url"])
    except Exception as error:
        return {**record, "status": "download_failed", "error": type(error).__name__}
    record.update(original_sha256=hashlib.sha256(data).hexdigest(), original_bytes=len(data))
    pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if pixels is None or pixels.size == 0:
        return {**record, "status": "undecodable"}
    height, width = pixels.shape[:2]
    scale = MAX_SIDE / max(height, width)
    if scale < 1:
        pixels = cv2.resize(pixels, (max(1, round(width * scale)), max(1, round(height * scale))),
                            interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        return {**record, "status": "encode_failed"}
    stored = encoded.tobytes()
    media_key = f"{image['id']:012d}.jpg"
    (directory / media_key).write_bytes(stored)
    return {**record, "status": "stored", "media_key": media_key, "original_width": width,
            "original_height": height, "stored_width": pixels.shape[1], "stored_height": pixels.shape[0],
            "stored_sha256": hashlib.sha256(stored).hexdigest(), "stored_bytes": len(stored)}


def reject(output: Path, rejected: dict) -> None:
    """Record feature-stage rejections so the next run downloads replacements.

    A rejected image keeps its download record; a later ``rejected_features``
    record removes it from the accepted gallery (the log is append-only).
    """
    with (output / "download.jsonl").open("a", encoding="utf-8") as stream:
        for coco_id, reason in sorted(rejected.items()):
            stream.write(json.dumps({"coco_id": int(coco_id), "status": "rejected_features",
                                     "reason": reason}, sort_keys=True) + "\n")


def run(output: Path, workers: int, limit: int | None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    images_dir = output / "images"
    images_dir.mkdir(exist_ok=True)
    info = catalog(output)
    order = permutation(info["images"])
    reserve = QUERY_COUNT + TUNING_COUNT
    held_out = order[-reserve:]
    candidates = order[:-reserve]
    log_path = output / "download.jsonl"
    done = {}
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            done[item["coco_id"]] = item
    # Hashes of every downloaded original, including later rejections, so a
    # byte-identical copy can never re-enter as a "new" image.
    hashes = set()
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item.get("status") == "stored":
                hashes.add(item["original_sha256"])
    lock = threading.Lock()
    wanted = GALLERY_SIZE if limit is None else limit

    def accepted_gallery():
        return sum(1 for image in candidates if done.get(image["id"], {}).get("status") == "stored")

    def submit_batch(batch, stream):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(store, image, images_dir): image for image in batch}
            for future in as_completed(futures):
                item = future.result()
                with lock:
                    if item.get("status") == "stored" and item["original_sha256"] in hashes:
                        (images_dir / item["media_key"]).unlink(missing_ok=True)
                        item = {key: item[key] for key in ("coco_id", "file_name", "coco_url", "license",
                                                            "original_sha256", "original_bytes")}
                        item["status"] = "duplicate_bytes"
                    elif item.get("status") == "stored":
                        hashes.add(item["original_sha256"])
                    done[item["coco_id"]] = item
                    stream.write(json.dumps(item, sort_keys=True) + "\n")
                    stream.flush()

    with log_path.open("a", encoding="utf-8") as stream:
        submit_batch([image for image in held_out if image["id"] not in done], stream)
        position = 0
        started = time.monotonic()
        while accepted_gallery() < wanted and position < len(candidates):
            missing = wanted - accepted_gallery()
            batch = []
            while len(batch) < max(missing, 1) and position < len(candidates):
                if candidates[position]["id"] not in done:
                    batch.append(candidates[position])
                position += 1
            for start in range(0, len(batch), 2000):
                submit_batch(batch[start:start + 2000], stream)
                print(f"{accepted_gallery()} gallery images stored, "
                      f"{time.monotonic() - started:.0f} s", flush=True)

    gallery = [image["id"] for image in candidates if done.get(image["id"], {}).get("status") == "stored"][:wanted]
    queries = [image["id"] for image in held_out if done.get(image["id"], {}).get("status") == "stored"]
    split = {"seed": SEED, "source": "COCO 2017 train", "captions_sha256": info["captions_sha256"],
             "gallery": gallery, "queries": queries[:QUERY_COUNT],
             "tuning": queries[QUERY_COUNT:QUERY_COUNT + TUNING_COUNT],
             "licenses": info["licenses"]}
    (output / "split.json").write_text(json.dumps(split, sort_keys=True) + "\n", encoding="utf-8")
    print(f"split.json: {len(gallery)} gallery, {len(split['queries'])} queries, "
          f"{len(split['tuning'])} tuning", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/generated/multimedia/coco"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--limit", type=int, help="gallery size (default 100,000)")
    parser.add_argument("--reject-from", type=Path,
                        help="features counts.json whose rejected images must be replaced")
    args = parser.parse_args(argv)
    if args.reject_from is not None:
        reject(args.output, json.loads(args.reject_from.read_text(encoding="utf-8"))["rejected"])
    run(args.output, args.workers, args.limit)


if __name__ == "__main__":
    main()
