"""Write-once array/JSON files shared by the Part 4 persistent components."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np

from engine.errors import ValidationError


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_bytes(path: Path, data: bytes) -> None:
    """Exclusive creation plus fsync: an existing file is never replaced."""
    with open(path, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def write_array(path: Path, array: np.ndarray) -> None:
    buffer = io.BytesIO()
    np.save(buffer, np.ascontiguousarray(array), allow_pickle=False)
    write_bytes(path, buffer.getvalue())


def write_json(path: Path, payload: dict) -> None:
    write_bytes(path, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))


def read_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationError(f"{label} is not valid JSON") from None
    if type(payload) is not dict:
        raise ValidationError(f"{label} must be a JSON object")
    return payload


def read_array(path: Path, dtype, shape=None, *, mmap: bool = False) -> np.ndarray:
    """Load a pickle-free ``.npy`` file and check dtype (and shape)."""
    try:
        array = np.load(path, mmap_mode="r" if mmap else None, allow_pickle=False)
    except (OSError, ValueError):
        raise ValidationError(f"{Path(path).name} is not a valid array file") from None
    if array.dtype != dtype or (shape is not None and array.shape != tuple(shape)):
        found = f"{array.dtype}{array.shape}"
        del array
        expected = f"{np.dtype(dtype)}{'' if shape is None else tuple(shape)}"
        raise ValidationError(f"{Path(path).name} has {found}; expected {expected}")
    if not mmap:
        array.setflags(write=False)
    return array


def require_files(directory: Path, names, label: str) -> None:
    missing = [name for name in names if not (Path(directory) / name).is_file()]
    if missing:
        raise ValidationError(f"{label} is missing {', '.join(missing)}")


def verify_checksums(directory: Path, checksums: dict, label: str) -> None:
    if type(checksums) is not dict:
        raise ValidationError(f"{label} checksums are malformed")
    for name, digest in checksums.items():
        if sha256_file(Path(directory) / name) != digest:
            raise ValidationError(f"{label} file {name} does not match its checksum")


__all__ = ["sha256_file", "write_bytes", "write_array", "write_json", "read_json", "read_array",
           "require_files", "verify_checksums"]
