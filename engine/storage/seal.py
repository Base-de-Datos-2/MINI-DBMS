"""Persistent identity of an immutable text collection; independent of I/O."""

from dataclasses import dataclass

from engine.errors import ValidationError


@dataclass(frozen=True, slots=True)
class StorageSeal:
    collection_id: str
    generation: str

    def __post_init__(self):
        for value in (self.collection_id, self.generation):
            if type(value) is not str or not value.strip():
                raise ValidationError("A storage seal requires collection and generation identifiers")
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeError as error:
                raise ValidationError("Storage seal identifiers must be valid UTF-8") from error
