"""Stage 5.5/5.7: logical directory aliases and strict paged bytes."""

import pytest

from engine.errors import ValidationError
from engine.indexes import HashDirectory, HashDirectoryCodec, HashDirectoryPage
from engine.storage.binary import MAX_RECORD_SIZE


def test_directory_lookup_update_and_lsb_doubling():
    directory = HashDirectory(1, [10, 20])
    assert directory.lookup_bucket(0b100) == 10
    assert directory.lookup_bucket(0b101) == 20
    doubled = directory.double()
    assert doubled.global_depth == 2
    assert doubled.entries == (10, 20, 10, 20)
    assert doubled.set_entry(2, 30).entries == (10, 20, 30, 20)


def test_directory_page_codec_is_exact_and_round_trips_aliases():
    page = HashDirectoryPage(3, [7, 7, 9], next_page_id=12)
    payload = HashDirectoryCodec.serialize(page)
    assert len(payload) == MAX_RECORD_SIZE
    assert HashDirectoryCodec.deserialize(payload) == page


@pytest.mark.parametrize("position", [0, -1])
def test_directory_codec_rejects_corrupted_signature_or_padding(position):
    payload = bytearray(
        HashDirectoryCodec.serialize(HashDirectoryPage(0, [2, 3]))
    )
    payload[position] ^= 0xFF
    with pytest.raises(ValidationError):
        HashDirectoryCodec.deserialize(bytes(payload))


def test_directory_shape_and_page_count_are_bounded():
    with pytest.raises(ValidationError, match=r"2\^global_depth"):
        HashDirectory(2, [1, 2])
    with pytest.raises(ValidationError, match="entry count"):
        HashDirectoryPage(0, [])
