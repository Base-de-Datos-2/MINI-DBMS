"""Assemble the small real-media demo committed under ``data/multimedia_demo``.

    python -m benchmarks.multimedia.demo_assets --images 120

* images: the first gallery images (split order) whose COCO/Flickr license
  allows derivative works (the stored copies are resized), plus five held-out
  query images; ``foto_consulta.jpg`` is the first of them (PDF example);
* audio: the FMA clips produced by ``benchmarks.multimedia.fma``.

Writes ``collections.json`` for ``scripts/setup_multimedia.py --assets`` and
``ATTRIBUTION.md`` with every source URL and license. This is demo media, not
the experimental corpus (which stays local under ``data/generated``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

COCO = Path("data/generated/multimedia/coco")
DERIVATIVES_ALLOWED = {1, 2, 4, 5, 7, 8}       # excludes the two NoDerivs licenses
QUERY_COUNT = 5


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/multimedia_demo"))
    parser.add_argument("--images", type=int, default=120)
    parser.add_argument("--audio", type=Path, default=Path("data/multimedia_demo/audio"))
    args = parser.parse_args(argv)
    split = json.loads((COCO / "split.json").read_text(encoding="utf-8"))
    records = {}
    for line in (COCO / "download.jsonl").read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if item["status"] == "stored":
            records[item["coco_id"]] = item
    licenses = {int(k): v for k, v in split["licenses"].items()}
    images_dir = args.output / "images"
    images_dir.mkdir(parents=True, exist_ok=False)

    def allowed(coco_id):
        return records[coco_id]["license"] in DERIVATIVES_ALLOWED

    gallery = [i for i in split["gallery"] if allowed(i)][:args.images]
    queries = [i for i in split["queries"] if allowed(i)][:QUERY_COUNT]
    attribution = ["# Demo media attribution", "",
                   "Images: COCO 2017 train (cocodataset.org), Flickr originals resized to a longest side of "
                   "512 px and re-encoded as JPEG quality 90. Only licenses that allow derivative works.", "",
                   "| File | COCO id | License | Source |", "|---|---|---|---|"]
    rows, query_files = [], []
    for index, coco_id in enumerate(gallery, 1):
        record = records[coco_id]
        shutil.copyfile(COCO / "images" / record["media_key"], images_dir / record["media_key"])
        rows.append([index, f"COCO {coco_id}", record["media_key"]])
        attribution.append(f"| {record['media_key']} | {coco_id} | {licenses[record['license']]['name']} | "
                           f"{record['coco_url']} |")
    for position, coco_id in enumerate(queries):
        record = records[coco_id]
        name = "foto_consulta.jpg" if position == 0 else f"consulta_{coco_id:012d}.jpg"
        shutil.copyfile(COCO / "images" / record["media_key"], images_dir / name)
        query_files.append(f"images/{name}")
        attribution.append(f"| {name} (query) | {coco_id} | {licenses[record['license']]['name']} | "
                           f"{record['coco_url']} |")
    audio_manifest = json.loads((args.audio / "manifest.json").read_text(encoding="utf-8"))
    audio_rows, audio_queries = [], []
    attribution += ["", "Audio: Free Music Archive (fma_small, Defferrard et al., ISMIR 2017), 10-second "
                    "mono MP3 clips re-encoded at 64 kbit/s.", "",
                    "| File | Track | Title | Artist | License |", "|---|---|---|---|---|"]
    for clip in audio_manifest["clips"]:
        if clip["role"] == "gallery":
            audio_rows.append([clip["id"], clip["title"], clip["artist"], clip["media_key"]])
        else:
            audio_queries.append(f"{args.audio.relative_to(args.output)}/{clip['media_key']}")
        attribution.append(f"| {clip['media_key']} | {clip['track_id']} | {clip['title']} | {clip['artist']} | "
                           f"{clip['license']} |")
    collections = {"collections": [
        {"table": "imagenes", "modality": "image", "id_column": "id", "key_column": "media_key",
         "columns": [["id", "INTEGER"], ["nombre", "VARCHAR"], ["media_key", "VARCHAR"]],
         "rows": rows, "media_directory": "images", "queries": query_files, "vocabulary_size": 256},
        {"table": "canciones", "modality": "audio", "id_column": "id", "key_column": "media_key",
         "columns": [["id", "INTEGER"], ["nombre", "VARCHAR"], ["artista", "VARCHAR"], ["media_key", "VARCHAR"]],
         "rows": audio_rows, "media_directory": str(args.audio.relative_to(args.output)),
         "queries": audio_queries, "vocabulary_size": 64},
    ]}
    (args.output / "collections.json").write_text(json.dumps(collections, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
    (args.output / "ATTRIBUTION.md").write_text("\n".join(attribution) + "\n", encoding="utf-8")
    print(f"{len(rows)} images + {len(query_files)} queries, {len(audio_rows)} clips + {len(audio_queries)} "
          f"queries", flush=True)


if __name__ == "__main__":
    main()
