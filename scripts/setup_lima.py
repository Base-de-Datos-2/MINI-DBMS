"""Create a new spatial demo with a reproducible OpenStreetMap Lima extract."""
from __future__ import annotations
import argparse
import csv
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))
from scripts.setup_spatial import prepare, SPATIAL_DATABASE
from api.database import Database, NewTable
from engine.catalog import DataType
from engine.spatial.metadata import validate_coordinates


def prepare_lima(directory: Path) -> None:
    source = REPOSITORY / "data/lima/lugares_lima.csv"
    rows = []
    with source.open(encoding="utf-8", newline="") as stream:
        for item in csv.DictReader(stream):
            lat, lon = float(item["latitud"]), float(item["longitud"])
            validate_coordinates(lat, lon)
            rows.append((int(item["id"]), item["nombre"], item["categoria"], lat, lon, item["osm_url"]))
    # Exclusive creation: existing user data is never overwritten.
    prepare(directory)
    columns = (("id", DataType.INTEGER), ("nombre", DataType.VARCHAR),
               ("categoria", DataType.VARCHAR), ("latitud", DataType.FLOAT),
               ("longitud", DataType.FLOAT), ("osm_url", DataType.VARCHAR))
    with Database.open(SPATIAL_DATABASE, directory) as database:
        database.create_gui_table(NewTable("lugares_lima", columns), rows,
                                  origin="csv", source_filename=source.name)
    with Database.open(SPATIAL_DATABASE, directory) as database:
        assert database.spatial_mapping_for("lugares_lima") is not None
        print(f"lugares_lima: {database.describe_table('lugares_lima').row_count} lugares de OpenStreetMap; registro espacial listo")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY / "data/generated/demo_lima")
    args = parser.parse_args()
    prepare_lima(args.data_dir.resolve())


if __name__ == "__main__":
    main()
