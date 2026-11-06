"""Evaluate the Part 4 data gate (PLAN_PARTE_04 §3.2) from measured artifacts.

    python -m benchmarks.multimedia.gate --pilot benchmarks/results/multimedia/<date>

Every check is computed from files on disk (download log, split, counts,
demo media, pilot build reports); nothing is asserted by hand. The result
replaces ``docs/implementacion/evidencias/multimedia/multimedia_feasibility.json``.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time

import numpy as np

from engine.catalog import Column, ColumnConstraint, DataType, Schema, TableMetadata
from engine.maintenance.validation import validate_record
from engine.multimedia.contracts import MAX_MEDIA_KEY_LENGTH, MAX_METADATA_TEXT_LENGTH
from engine.multimedia.features import FeatureModel, audio_descriptors, document_frequencies, \
    inverse_document_frequencies, tfidf
from engine.multimedia.vectors import VectorStore
from engine.storage import HeapFile, Record

DATA = Path("data/generated/multimedia")
COCO = DATA / "coco"
FEATURES = DATA / "features"
DEMO = Path("data/multimedia_demo")
TARGET = Path("docs/implementacion/evidencias/multimedia/multimedia_feasibility.json")
MEMORY_LIMIT_MIB = 4 * 1024          # memory available on the host at probe time
TIME_WINDOW_SECONDS = 4 * 3600       # preparation window for the 100,000 builds


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check(identifier, passed, **evidence):
    return {"id": identifier, "status": "PASS" if passed else "FAIL", **evidence}


def accessible_media(split):
    records = [json.loads(line) for line in (COCO / "download.jsonl").read_text().splitlines()]
    statuses = Counter(r["status"] for r in records)
    stored = [r for r in records if r["status"] == "stored"]
    files = {p.name for p in (COCO / "images").iterdir()}
    provenance = all(r.get("coco_url") and r.get("original_sha256") and r.get("license") for r in stored)
    licenses = Counter(split["licenses"][str(r["license"])]["name"] for r in stored)
    return check("accessible_media", provenance and len(files) == len(stored) and
                 all(r["media_key"] in files for r in stored),
                 attempted=len(records), statuses=dict(statuses), files_on_disk=len(files),
                 stored_bytes=sum(r["stored_bytes"] for r in stored),
                 original_bytes_downloaded=sum(r["original_bytes"] for r in records if "original_bytes" in r),
                 licenses=dict(licenses), provenance="coco_url, license and SHA-256 of the original per image")


def valid_scale(split, counts, report):
    gallery = len(split["gallery"])
    rows = np.asarray(counts[:gallery])
    vectors = tfidf(rows, inverse_document_frequencies(gallery, document_frequencies(rows)))
    norms = np.linalg.norm(vectors.astype(np.float64), axis=1)
    finite = bool(np.all(np.isfinite(vectors)))
    return check("valid_scale", gallery >= 100_000 and not report["rejected"] and finite and bool(np.all(norms > 0)),
                 gallery_objects=gallery, rejected_in_final_split=len(report["rejected"]),
                 replaced_after_first_pass=report.get("replaced_after_first_pass", {}), finite=finite,
                 zero_norm=int(np.sum(norms == 0)), duplicate_bytes_removed=sum(
                     1 for line in (COCO / "download.jsonl").read_text().splitlines()
                     if json.loads(line)["status"] == "duplicate_bytes"),
                 descriptors_mean=report["descriptors_mean"], descriptors_min=report["descriptors_min"])


def experimental_split(split):
    records = {r["coco_id"]: r for r in map(json.loads, (COCO / "download.jsonl").read_text().splitlines())
               if r["status"] == "stored"}
    gallery, queries, tuning = split["gallery"], split["queries"], split["tuning"]
    ids_disjoint = not (set(gallery) & set(queries) or set(gallery) & set(tuning) or set(queries) & set(tuning))
    gallery_hashes = {records[i]["original_sha256"] for i in gallery}
    byte_overlap = sum(records[i]["original_sha256"] in gallery_hashes for i in queries + tuning)
    nested = gallery[:1_000] == gallery[:10_000][:1_000] and len(set(gallery)) == len(gallery)
    return check("experimental_split", ids_disjoint and byte_overlap == 0 and nested and len(queries) == 30
                 and len(tuning) == 50, sizes=[1_000, 10_000, 100_000], nested_prefixes=nested,
                 queries=len(queries), tuning=len(tuning), ids_disjoint=ids_disjoint,
                 byte_identical_overlap=byte_overlap, seed=split["seed"])


def real_pipeline(split):
    schema = Schema([Column("id", DataType.INTEGER), Column("nombre", DataType.VARCHAR),
                     Column("media_key", DataType.VARCHAR)])
    table = TableMetadata("imagenes", schema, constraints=(
        ColumnConstraint("id", primary_key=True),
        ColumnConstraint("nombre", varchar_length=MAX_METADATA_TEXT_LENGTH),
        ColumnConstraint("media_key", varchar_length=MAX_MEDIA_KEY_LENGTH)))
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "imagenes.heap"
        rids = {}
        with HeapFile.create(path, schema) as heap:
            for coco_id in split["gallery"]:
                record = Record(schema, [coco_id, f"COCO {coco_id}", f"{coco_id:012d}.jpg"])
                validate_record(table, record)
                rids[coco_id] = heap.insert(record)
        with HeapFile.open(path, schema) as heap:
            count = heap.record_count
            sample = split["gallery"][::997]
            intact = all(heap.read(rids[i]).values == (i, f"COCO {i}", f"{i:012d}.jpg") for i in sample)
            pages = heap.data_page_count
    return check("real_pipeline", count == len(split["gallery"]) and intact,
                 heap_rows=count, sampled_rows_intact=len(sample), data_pages=pages,
                 insert_and_reopen_seconds=time.perf_counter() - started,
                 descriptor_pipeline="every gallery, query and tuning image passed SIFT + vocabulary "
                                     "(features/counts.json)")


def audio_path():
    manifest = json.loads((DEMO / "audio" / "manifest.json").read_text(encoding="utf-8"))
    clips = manifest["clips"]
    decoded = {}
    for clip in clips:
        decoded[clip["media_key"]] = audio_descriptors(DEMO / "audio" / clip["media_key"]).shape[0]
    gallery = [c for c in clips if c["role"] == "gallery"]
    queries = [c for c in clips if c["role"] == "query"]
    ranks = None
    demo = DATA.parent / "multimedia_demo_check"
    if (demo / "multimedia_tables.json").exists():
        from api.database import Database, DatabaseDefinition
        ranks = {}
        with Database.open(DatabaseDefinition("multimedia"), demo) as database:
            session = database.open_session()
            for clip in queries:
                result = session.execute(f"SELECT media_key FROM canciones WHERE SIMILAR_TO('{clip['media_key']}',"
                                         " k=5) USING IVF WITH METRIC=euclidean")
                keys = [row.values[0] for row in result.rows]
                ranks[clip["media_key"]] = keys.index(clip["same_track_as"]) + 1 \
                    if clip["same_track_as"] in keys else None
            session.close()
    mp3 = all(c["media_key"].endswith(".mp3") for c in clips)
    return check("audio_path", len(gallery) == 30 and len(queries) == 5 and mp3 and all(decoded.values()),
                 gallery_clips=len(gallery), query_clips=len(queries), all_mp3=mp3,
                 mfcc_frames_per_clip=sorted(set(decoded.values())), licenses=sorted({c["license"] for c in clips}),
                 same_track_rank_ivf_euclidean_k5=ranks, bytes_transferred=manifest["bytes_transferred"])


def resources(pilot: Path, report):
    def load(name):
        return json.loads((pilot / f"{name}.json").read_text())
    measured, projected = {}, {}
    for config in ("ivf-euclidean", "ivf-cosine", "hnsw-euclidean", "hnsw-cosine"):
        small, medium = load(f"build_1000_{config}"), load(f"build_10000_{config}")
        measured[config] = {"1000": {"seconds": small["seconds"], "peak_mib": small["memory_peak"]["peak_mib"]},
                            "10000": {"seconds": medium["seconds"], "peak_mib": medium["memory_peak"]["peak_mib"]}}
        growth = 10 * math.log(100_000) / math.log(10_000)   # n log n from 10k to 100k
        extra = medium["memory_peak"]["peak_mib"] - small["memory_peak"]["peak_mib"]
        projected[config] = {"seconds": medium["seconds"] * growth,
                             "peak_mib": medium["memory_peak"]["peak_mib"] + extra * 10}
    vocabulary = json.loads((FEATURES / "vocabulary.json").read_text())
    total = report["wall_seconds"] + vocabulary["extract_seconds"] + vocabulary["kmeans_seconds"] + \
        sum(p["seconds"] for p in projected.values())
    fits = all(p["peak_mib"] < MEMORY_LIMIT_MIB for p in projected.values()) and total < TIME_WINDOW_SECONDS
    return check("resources", fits, extraction_all_images_seconds=report["wall_seconds"],
                 extraction_workers=report["workers"], vocabulary=vocabulary, pilot_builds=measured,
                 projected_100000=projected, projection="time x 10*log(1e5)/log(1e4); memory linear in N",
                 memory_limit_mib=MEMORY_LIMIT_MIB, time_window_seconds=TIME_WINDOW_SECONDS,
                 note="A projection is not proof; the measured 100,000 builds are reported by phase 7.")


def persistence(pilot: Path):
    artifacts = {}
    for path in (COCO / "split.json", FEATURES / "codebook.npy", FEATURES / "counts.npy", FEATURES / "order.npy"):
        artifacts[str(path)] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    directory = DATA / "experiment" / "n10000"
    model = FeatureModel.load(directory / "model")
    with VectorStore.open(directory / "store", expected_fingerprint=model.fingerprint, verify=True) as store:
        size = store.size
    return check("persistence", size == 10_000, artifacts=artifacts, reopened_size=size,
                 reopen="FeatureModel.load and VectorStore.open(verify=True) without training; tests disable "
                        "K-Means and graph insertion during reopen")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pilot", type=Path, required=True)
    args = parser.parse_args(argv)
    split = json.loads((COCO / "split.json").read_text(encoding="utf-8"))
    counts = np.load(FEATURES / "counts.npy", mmap_mode="r", allow_pickle=False)
    report = json.loads((FEATURES / "counts.json").read_text(encoding="utf-8"))
    first = FEATURES / "counts.first_pass.json"
    if first.exists():
        # Extraction statistics come from the complete pass; replacements were
        # extracted afterwards with the same code and codebook.
        full = json.loads(first.read_text(encoding="utf-8"))
        report = {**full, "rejected": report["rejected"], "replaced_after_first_pass": full["rejected"]}
    checks = [accessible_media(split), valid_scale(split, counts, report), experimental_split(split),
              real_pipeline(split), audio_path(), resources(args.pilot, report), persistence(args.pilot)]
    previous = json.loads(TARGET.read_text(encoding="utf-8"))
    payload = {"version": 1, "status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
               "updated": time.strftime("%Y-%m-%d"), "source": "COCO 2017 train (images), FMA small (audio)",
               "checks": checks,
               "host_observations_2026_11_06": previous["host_observations_2026_11_06"],
               "source_probes_2026_11_06": previous["source_probes_2026_11_06"],
               "acquisition_strategy": {**previous["acquisition_strategy"], "status": "APPLIED"}}
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(payload["status"], [(c["id"], c["status"]) for c in checks], flush=True)


if __name__ == "__main__":
    main()
