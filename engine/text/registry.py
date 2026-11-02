"""Strict, read-only registry for offline-published text collections.

The owner creates/publishes this file only after sealing the heap and indexes.
This module intentionally does not create or mutate database files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engine.errors import ValidationError
from .format import read_json

REGISTRY_FILENAME = 'text_tables.json'

@dataclass(frozen=True, slots=True)
class TextRegistration:
    table: str
    column: str
    collection_id: str
    generation: str
    directory: str


def read_text_registry(root: Path) -> tuple[TextRegistration, ...]:
    path = root / REGISTRY_FILENAME
    if not path.exists():
        return ()
    payload = read_json(path)
    if type(payload) is not dict or set(payload) != {'version', 'collections'} or payload['version'] != 1:
        raise ValidationError('Unsupported text registry format')
    entries = payload['collections']
    if type(entries) is not list:
        raise ValidationError('Text registry collections must be a list')
    result = []
    seen = set()
    for item in entries:
        fields = {'table', 'column', 'collection_id', 'generation', 'directory'}
        if type(item) is not dict or set(item) != fields:
            raise ValidationError('Invalid text registration')
        if any(type(item[key]) is not str or not item[key].strip() for key in fields):
            raise ValidationError('Text registration fields must be nonempty strings')
        relative = Path(item['directory'])
        if (relative.is_absolute() or len(relative.parts) != 1 or
                relative.parts[0] in {'.', '..'} or '/' in item['directory'] or '\\' in item['directory']):
            raise ValidationError('Text index directory must be a single safe directory name')
        if item['table'] in seen:
            raise ValidationError('Duplicate text table registration')
        seen.add(item['table'])
        result.append(TextRegistration(**item))
    return tuple(result)
