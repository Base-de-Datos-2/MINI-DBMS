"""The academic tables shared by offline preparation and server registration."""

from engine.catalog import DataType


PAPER_COLUMNS = (
    ("paper_id", DataType.INTEGER), ("authors", DataType.VARCHAR),
    ("year", DataType.INTEGER), ("title", DataType.VARCHAR),
    ("abstract", DataType.VARCHAR),
)
CHUNK_COLUMNS = (
    ("chunk_id", DataType.INTEGER), ("paper_id", DataType.INTEGER),
    ("position", DataType.INTEGER), ("content", DataType.VARCHAR),
)
