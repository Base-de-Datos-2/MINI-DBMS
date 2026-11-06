"""Strict read-only registry of offline-published multimedia collections.

``multimedia_tables.json`` is created once by the owner after every
collection has been built, sealed and checked. Same rules as Part 3's
``text_tables.json``: exclusive one-time publication and strict reading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path

from engine.errors import ValidationError

from .files import read_json

REGISTRY_FILENAME = "multimedia_tables.json"
_FIELDS = {"table", "column", "modality", "collection_id", "generation", "directory"}


@dataclass(frozen=True, slots=True)
class MultimediaRegistration:
    table: str
    column: str          # the media-key column
    modality: str
    collection_id: str
    generation: str
    directory: str


def read_multimedia_registry(root: Path) -> tuple[MultimediaRegistration, ...]:
    path = Path(root) / REGISTRY_FILENAME
    if not path.exists():
        return ()
    payload = read_json(path, "Multimedia registry")
    if set(payload) != {"version", "collections"} or payload["version"] != 1 \
            or type(payload["collections"]) is not list:
        raise ValidationError("Unsupported multimedia registry format")
    result, seen = [], set()
    for item in payload["collections"]:
        if type(item) is not dict or set(item) != _FIELDS:
            raise ValidationError("Invalid multimedia registration")
        if any(type(item[key]) is not str or not item[key].strip() for key in _FIELDS):
            raise ValidationError("Multimedia registration fields must be nonempty strings")
        if item["modality"] not in ("image", "audio"):
            raise ValidationError("Multimedia registration has an unknown modality")
        relative = Path(item["directory"])
        if (relative.is_absolute() or len(relative.parts) != 1 or relative.parts[0] in {".", ".."}
                or "/" in item["directory"] or "\\" in item["directory"]):
            raise ValidationError("Multimedia collection directory must be a single safe name")
        if item["table"] in seen:
            raise ValidationError("Duplicate multimedia table registration")
        seen.add(item["table"])
        result.append(MultimediaRegistration(**item))
    return tuple(result)


def publish_multimedia_registry(root: Path, entries: tuple[MultimediaRegistration, ...]) -> None:
    import json
    path = Path(root) / REGISTRY_FILENAME
    if path.exists():
        raise ValidationError("Multimedia registry already published; rebuild in a new directory")
    temporary = Path(root) / "multimedia_tables.preparing"
    try:
        with temporary.open("xb") as stream:
            stream.write(json.dumps({"version": 1, "collections": [asdict(e) for e in entries]},
                                    indent=2, sort_keys=True).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)          # exclusive: never overwrite a publication
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["MultimediaRegistration", "read_multimedia_registry", "publish_multimedia_registry"]
