"""Stage 5.4: stable typed hashing and least-significant-bit routing."""

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes import HashCodec


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"", 0xCBF29CE484222325),
        (b"a", 0xAF63DC4C8601EC8C),
        (b"hello", 0xA430D84680AABD0B),
    ],
)
def test_fnv1a_64_golden_vectors(payload, expected):
    assert HashCodec.hash_bytes(payload) == expected


def test_typed_key_hash_reuses_canonical_key_bytes():
    assert HashCodec.encode_key(DataType.INTEGER, 1) == bytes.fromhex(
        "01 0100000000000000"
    )
    assert HashCodec.hash_key(DataType.INTEGER, 1) != HashCodec.hash_key(
        DataType.VARCHAR, "1"
    )
    assert HashCodec.hash_key(DataType.VARCHAR, "á😀") == HashCodec.hash_key(
        DataType.VARCHAR, "á😀"
    )
    assert HashCodec.hash_key(DataType.INTEGER, 0) != HashCodec.hash_key(
        DataType.FLOAT, 0.0
    )


def test_equal_signed_float_zeros_share_canonical_bytes_and_hash():
    positive = HashCodec.encode_key(DataType.FLOAT, 0.0)
    negative = HashCodec.encode_key(DataType.FLOAT, -0.0)
    assert positive == negative
    assert HashCodec.hash_key(DataType.FLOAT, 0.0) == HashCodec.hash_key(
        DataType.FLOAT, -0.0
    )
    assert HashCodec.decode_key(DataType.FLOAT, negative) == 0.0


@pytest.mark.parametrize(
    ("value", "depth", "expected"),
    [(0b110101, 0, 0), (0b110101, 1, 1), (0b110101, 3, 0b101), (0b110101, 6, 0b110101)],
)
def test_directory_index_selects_lsb_suffix(value, depth, expected):
    assert HashCodec.directory_index(value, depth) == expected


def test_hash_and_depth_validation_is_strict():
    with pytest.raises(InvalidTypeError):
        HashCodec.hash_bytes(bytearray(b"a"))
    with pytest.raises(InvalidTypeError):
        HashCodec.directory_index(True, 1)
    with pytest.raises(ValidationError):
        HashCodec.directory_index(-1, 1)
    with pytest.raises(ValidationError):
        HashCodec.directory_index(1, 65)
