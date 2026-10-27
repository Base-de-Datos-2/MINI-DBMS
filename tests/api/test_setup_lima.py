"""The bundled real-place demo preserves coordinates and survives reopening."""
import csv
import pytest
from api.database import Database
from scripts.setup_spatial import SPATIAL_DATABASE
from scripts.setup_lima import prepare_lima, REPOSITORY
from engine.spatial.metadata import validate_coordinates


def test_real_place_demo_reopens_and_never_overwrites(tmp_path):
    directory = tmp_path / 'lima'
    prepare_lima(directory)
    with Database.open(SPATIAL_DATABASE, directory) as database:
        assert database.describe_table('lugares_lima').row_count == 20
        assert database.spatial_mapping_for('lugares_lima') is not None
    before = (directory / 'gui_tables.json').read_bytes()
    with pytest.raises(FileExistsError):
        prepare_lima(directory)
    assert (directory / 'gui_tables.json').read_bytes() == before


def test_real_place_coordinates_have_unique_ids_and_provenance():
    with (REPOSITORY / 'data/lima/lugares_lima.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len({row['id'] for row in rows}) == 20
    for row in rows:
        validate_coordinates(float(row['latitud']), float(row['longitud']))
        assert row['nombre'] and row['categoria']
        assert row['osm_url'].startswith('https://www.openstreetmap.org/node/')
