"""Prepare Part 4 image/audio collections in a NEW directory (server stopped).

    python scripts/setup_multimedia.py [--data-dir DIR] [--assets DIR]

Without ``--assets`` the collections are built from the synthetic fixtures in
``tests/multimedia/fixtures`` (labelled as such; no result on them is
evidence about real media). ``--assets`` takes a directory with a
``collections.json`` describing real demo media (see docs/multimedia.md).
Both PDF example queries work afterwards:

    SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=10)
    USING HNSW WITH METRIC=cosine;
"""

import argparse
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from api.database import Database, MultimediaSource, NewTable  # noqa: E402
from engine.catalog import DataType  # noqa: E402
from engine.multimedia import HnswParameters, Modality  # noqa: E402

FIXTURES = REPOSITORY / "tests" / "multimedia" / "fixtures"
TYPES = {"INTEGER": DataType.INTEGER, "VARCHAR": DataType.VARCHAR, "FLOAT": DataType.FLOAT}
# Tiny collections: a graph with M=16 over 8 objects would be complete anyway.
SMALL_HNSW = HnswParameters(m=4, m0=8, ef_construction=16, min_ef_search=16)


def fixture_sources():
    manifest = json.loads((FIXTURES / "manifest.v1.json").read_text(encoding="utf-8"))
    images = [e for e in manifest["files"] if e["modality"] == "image" and e["role"] == "gallery"]
    clips = [e for e in manifest["files"] if e["modality"] == "audio" and e["role"] == "gallery"]
    return [
        MultimediaSource(
            NewTable("imagenes", (("id", DataType.INTEGER), ("nombre", DataType.VARCHAR),
                                  ("media_key", DataType.VARCHAR))),
            [(i, e["metadata"]["nombre"], e["name"]) for i, e in enumerate(images, 1)],
            "id", "media_key", Modality.IMAGE, FIXTURES, (FIXTURES / "foto_consulta.jpg",),
            vocabulary_size=16, hnsw_parameters=SMALL_HNSW),
        MultimediaSource(
            NewTable("canciones", (("id", DataType.INTEGER), ("nombre", DataType.VARCHAR),
                                   ("artista", DataType.VARCHAR), ("media_key", DataType.VARCHAR))),
            [(i, e["metadata"]["nombre"], e["metadata"]["artista"], e["name"]) for i, e in enumerate(clips, 1)],
            "id", "media_key", Modality.AUDIO, FIXTURES, (FIXTURES / "audio_query.mp3",),
            vocabulary_size=8, hnsw_parameters=SMALL_HNSW),
    ]


def asset_sources(assets: Path):
    """Collections described by ``<assets>/collections.json``."""
    description = json.loads((assets / "collections.json").read_text(encoding="utf-8"))
    sources = []
    for item in description["collections"]:
        columns = tuple((name, TYPES[kind]) for name, kind in item["columns"])
        media = assets / item["media_directory"]
        hnsw = item.get("hnsw")
        sources.append(MultimediaSource(
            NewTable(item["table"], columns), [tuple(row) for row in item["rows"]],
            item["id_column"], item["key_column"], Modality(item["modality"]), media,
            tuple(assets / q for q in item.get("queries", ())),
            vocabulary_size=item.get("vocabulary_size"),
            hnsw_parameters=None if hnsw is None else HnswParameters(**hnsw)))
    return sources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY / "data/generated/multimedia")
    parser.add_argument("--assets", type=Path, help="directory with collections.json (real demo media)")
    args = parser.parse_args(argv)
    sources = fixture_sources() if args.assets is None else asset_sources(args.assets)
    registrations = Database.prepare_multimedia(args.data_dir, sources)
    for registration in registrations:
        print(f"{registration.table}: {registration.modality} collection published")
    if args.assets is None:
        print("Synthetic fixture collections only; no experimental result is claimed.")


if __name__ == "__main__":
    main()
