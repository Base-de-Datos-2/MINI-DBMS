"""Prepare a new spatial fixture via the application's existing owner."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from api.database import Database, DatabaseDefinition, NewTable  # noqa: E402
from benchmarks.spatial.datasets import FIXTURE_ROWS, REQUIRED_SIZES, point_rows  # noqa: E402
from engine.catalog import DataType  # noqa: E402
from engine.spatial.metadata import (  # noqa: E402
    SpatialMapping, validate_coordinates, write_mappings,
)

SPATIAL_DATABASE = DatabaseDefinition("spatial")


def prepare(directory: Path, *, size: int | None = None) -> None:
    """Create exclusively, so existing demo/user data is never replaced."""
    if size is not None and (type(size) is not int or size not in REQUIRED_SIZES):
        raise ValueError("Benchmark size must be 1000, 10000 or 100000")
    rows = FIXTURE_ROWS if size is None else tuple(point_rows(size))
    names = ("tiendas", "restaurantes") if size is None else ("puntos",)
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    for _, _, latitude, longitude in rows:
        validate_coordinates(latitude, longitude)
    columns = (("id", DataType.INTEGER), ("nombre", DataType.VARCHAR),
               ("latitud", DataType.FLOAT), ("longitud", DataType.FLOAT))
    with Database.create(SPATIAL_DATABASE, directory) as database:
        for name in names:
            database.create_gui_table(NewTable(name, columns), rows,
                                      origin="csv", source_filename="fixture.csv" if size is None else f"points_{size}.csv")
    write_mappings(directory, tuple(SpatialMapping(name)
                                   for name in names))
    # Fresh owner: no original in-memory definitions or open files are reused.
    with Database.open(SPATIAL_DATABASE, directory) as database:
        for name in database.table_names():
            mapping = database.spatial_mapping_for(name)
            assert mapping is not None
            print(f"{name}: {database.describe_table(name).row_count} rows; "
                  f"{mapping.location_name}=({mapping.latitude_column}, {mapping.longitude_column})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path,
                        default=None)
    parser.add_argument("--size", type=int, choices=REQUIRED_SIZES,
                        help="prepare one seeded benchmark table instead of the nine-row fixture")
    args = parser.parse_args(argv)
    default_name = 'spatial' if args.size is None else f'spatial_{args.size}'
    prepare(args.data_dir or REPOSITORY / 'data/generated' / default_name, size=args.size)


if __name__ == "__main__":
    main()
