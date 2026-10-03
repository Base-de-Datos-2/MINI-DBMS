"""Deterministic benchmark datasets: the same logical rows for every structure.

Each size has its own fixed seed, so a dataset is reproduced exactly by
``generate(size)``. Keys ``id`` are a random permutation of ``1..size``:
records arrive in random key order, which is the order every structure loads.
"""

from __future__ import annotations

import csv
from pathlib import Path
import random

from engine.catalog import Column, DataType, Schema


#: Sizes required by REQUIREMENTS.md §9.
REQUIRED_SIZES = (1_000, 10_000, 100_000)

SCHEMA = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
    Column("career", DataType.VARCHAR),
    Column("age", DataType.INTEGER),
    Column("score", DataType.INTEGER),
])
KEY_COLUMN = "id"

CAREERS = ("CS", "EE", "ME", "CE", "MA", "PH", "BI", "EC")
FIRST_NAMES = (
    "Ana", "Luis", "Sol", "Omar", "Lucía", "Diego", "Valeria", "Mateo",
    "Camila", "Joaquín", "Renata", "Andrés", "Paula", "Iván", "Elena", "Tomás",
)
LAST_NAMES = (
    "Quispe", "Mamani", "Flores", "Rojas", "Torres", "Huamán", "Vargas",
    "Castillo", "Ramos", "Chávez", "Medina", "Paredes",
)

Row = tuple[int, str, str, int, int]


def seed_for(size: int) -> int:
    """Return the fixed generation seed of one dataset size."""

    return 20_261_000 + size


def generate(size: int, seed: int | None = None) -> list[Row]:
    """Return ``size`` rows in arrival order; ``id`` is unique in ``1..size``."""

    if type(size) is not int or size < 1:
        raise ValueError("size must be a positive integer")
    rng = random.Random(seed_for(size) if seed is None else seed)
    keys = list(range(1, size + 1))
    rng.shuffle(keys)
    return [
        (
            key,
            f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            rng.choice(CAREERS),
            rng.randrange(17, 40),
            rng.randrange(0, 101),
        )
        for key in keys
    ]


def write_csv(rows: list[Row], path: Path) -> Path:
    """Write rows with a header, e.g. to import them through the GUI."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([column.name for column in SCHEMA])
        writer.writerows(rows)
    return path
