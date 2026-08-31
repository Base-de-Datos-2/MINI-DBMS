"""Exact file-prefix bytes, immutable metadata, and domain validation."""

from dataclasses import FrozenInstanceError, replace

import pytest

from engine.errors import InvalidTypeError, ValidationError
from engine.storage import FileHeader
from engine.storage.binary import FILE_HEADER_STRUCT, FILE_MAGIC, UINT32_MAX


@pytest.mark.parametrize("count", [0, 1, 256, UINT32_MAX])
def test_file_header_round_trip(count, no_file_io):
    with no_file_io():
        header = FileHeader(allocated_page_count=count)
        assert header.magic == FILE_MAGIC
        assert header.version == 1
        assert header.page_size == 4096
        assert header.allocated_page_count == count
        assert len(header.serialize()) == 20
        assert FileHeader.deserialize(header.serialize()) == header


def test_file_header_has_golden_little_endian_bytes():
    assert FileHeader(allocated_page_count=0x12345678).serialize() == bytes.fromhex(
        "4d494e4944420000 01000000 00100000 78563412"
    )


def test_file_header_is_immutable_and_replace_revalidates():
    header = FileHeader()
    with pytest.raises(FrozenInstanceError):
        header.allocated_page_count = 1
    updated = replace(header, allocated_page_count=3)
    assert updated.allocated_page_count == 3
    assert header.allocated_page_count == 0
    with pytest.raises(ValidationError):
        replace(header, page_size=8192)


@pytest.mark.parametrize("magic", [b"", b"MINIDB", b"OTHERDB!", b"MINIDB\x00\x01", FILE_MAGIC + b"x"])
def test_wrong_magic_is_rejected_before_struct_can_pad_or_truncate(magic):
    with pytest.raises(ValidationError, match="signature"):
        FileHeader(magic=magic)


@pytest.mark.parametrize("magic", ["MINIDB", None, bytearray(FILE_MAGIC), 1])
def test_magic_requires_bytes(magic):
    with pytest.raises(InvalidTypeError):
        FileHeader(magic=magic)


@pytest.mark.parametrize("field", ["version", "page_size", "allocated_page_count"])
@pytest.mark.parametrize("value", [-1, UINT32_MAX + 1, 2**100])
def test_fields_require_uint32_range(field, value):
    with pytest.raises(ValidationError):
        FileHeader(**{field: value})


@pytest.mark.parametrize("field", ["version", "page_size", "allocated_page_count"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_fields_require_exact_int(field, value):
    with pytest.raises(InvalidTypeError):
        FileHeader(**{field: value})


@pytest.mark.parametrize("version", [0, 2, UINT32_MAX])
def test_unsupported_version_is_rejected(version):
    with pytest.raises(ValidationError, match="version"):
        FileHeader(version=version)


@pytest.mark.parametrize("page_size", [0, 20, 4095, 4097, 8192, UINT32_MAX])
def test_unsupported_page_size_is_rejected(page_size):
    with pytest.raises(ValidationError, match="page size"):
        FileHeader(page_size=page_size)


@pytest.mark.parametrize("size", [0, 1, 19, 21, 4096])
def test_deserialization_requires_exactly_twenty_bytes(size):
    with pytest.raises(ValidationError, match="exactly 20"):
        FileHeader.deserialize(bytes(size))


@pytest.mark.parametrize("payload", [None, "", [], bytearray(20), memoryview(bytes(20))])
def test_deserialization_requires_immutable_bytes(payload):
    with pytest.raises(InvalidTypeError):
        FileHeader.deserialize(payload)


@pytest.mark.parametrize(
    "fields", [(b"WRONG!!!", 1, 4096, 0), (FILE_MAGIC, 0, 4096, 0),
               (FILE_MAGIC, 2, 4096, 0), (FILE_MAGIC, 1, 8192, 0)],
)
def test_deserialization_validates_decoded_fields(fields):
    with pytest.raises(ValidationError):
        FileHeader.deserialize(FILE_HEADER_STRUCT.pack(*fields))
