"""Regression checks for the strict 4B read-only registry format."""
import json
import pytest
from engine.errors import ValidationError
from engine.text.registry import read_text_registry


def test_absent_registry_is_empty(tmp_path):
    assert read_text_registry(tmp_path) == ()


def test_published_registry_fields(tmp_path):
    payload = {'version': 1, 'collections': [{
        'table': 'documentos', 'column': 'contenido', 'collection_id': 'corpus',
        'generation': 'g1', 'directory': 'text_corpus',
    }]}
    (tmp_path / 'text_tables.json').write_text(json.dumps(payload), encoding='utf-8')
    (entry,) = read_text_registry(tmp_path)
    assert (entry.table, entry.column, entry.generation) == ('documentos', 'contenido', 'g1')


@pytest.mark.parametrize('directory', ['../escape', '/tmp/index', 'a/b', r'a\\b', '.'])
def test_registry_rejects_unsafe_paths(tmp_path, directory):
    payload = {'version': 1, 'collections': [{
        'table': 'documentos', 'column': 'contenido', 'collection_id': 'corpus',
        'generation': 'g1', 'directory': directory,
    }]}
    (tmp_path / 'text_tables.json').write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValidationError):
        read_text_registry(tmp_path)


def test_duplicate_table_rejected(tmp_path):
    entry = {'table': 't', 'column': 'text', 'collection_id': 'c',
             'generation': 'g', 'directory': 'idx'}
    (tmp_path / 'text_tables.json').write_text(json.dumps(
        {'version': 1, 'collections': [entry, entry]}), encoding='utf-8')
    with pytest.raises(ValidationError):
        read_text_registry(tmp_path)
