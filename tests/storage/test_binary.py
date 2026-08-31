"""Adopted physical constants and geometry, without a Page implementation."""

import pytest

from engine.errors import InvalidTypeError, ValidationError
from engine.storage import binary


def layout(**changes):
    fields = dict(
        page_id=0,
        slot_count=2,
        free_space_start=22,
        free_space_end=4000,
        active_record_count=2,
    )
    fields.update(changes)
    binary.validate_page_layout(**fields)


def test_version_one_layout_sizes_and_limits():
    assert binary.PAGE_SIZE == 4096
    assert binary.FILE_MAGIC == b"MINIDB\x00\x00"
    assert len(binary.FILE_MAGIC) == 8
    assert binary.FORMAT_VERSION == 1
    assert binary.PAGE_HEADER_FORMAT == "<IHHHH"
    assert binary.PAGE_HEADER_SIZE == 12
    assert binary.SLOT_FORMAT == "<HHB"
    assert binary.SLOT_SIZE == 5
    assert binary.FILE_HEADER_FORMAT == "<8sIII"
    assert binary.FILE_HEADER_SIZE == 20
    assert binary.MAX_SLOTS == 816
    assert binary.MAX_RECORD_SIZE == 4079
    assert (binary.SLOT_FREE, binary.SLOT_ACTIVE) == (0, 1)
    assert binary.INTEGER_MIN == -(2**63)
    assert binary.INTEGER_MAX == 2**63 - 1
    assert binary.UINT16_MAX == 65535
    assert binary.UINT32_MAX == 4294967295
    assert binary.STRING_ENCODING == "utf-8"


@pytest.mark.parametrize(
    ("format_name", "struct_name", "size"),
    [
        ("PAGE_HEADER_FORMAT", "PAGE_HEADER_STRUCT", 12),
        ("SLOT_FORMAT", "SLOT_STRUCT", 5),
        ("FILE_HEADER_FORMAT", "FILE_HEADER_STRUCT", 20),
        ("INTEGER_FORMAT", "INTEGER_STRUCT", 8),
        ("FLOAT_FORMAT", "FLOAT_STRUCT", 8),
        ("BOOLEAN_FORMAT", "BOOLEAN_STRUCT", 1),
        ("VARCHAR_LENGTH_FORMAT", "VARCHAR_LENGTH_STRUCT", 4),
    ],
)
def test_all_formats_have_explicit_byte_order_and_no_padding(format_name, struct_name, size):
    codec = getattr(binary, struct_name)
    assert codec.format == getattr(binary, format_name)
    assert codec.format.startswith("<")
    assert codec.size == size


def test_planned_file_header_format_has_fixed_golden_bytes():
    # A format declaration only: no FileHeader or file operations yet.
    assert binary.FILE_HEADER_STRUCT.pack(binary.FILE_MAGIC, 1, 4096, 2) == (
        b"MINIDB\x00\x00\x01\x00\x00\x00\x00\x10\x00\x00\x02\x00\x00\x00"
    )


def test_page_buffer_validator_checks_size_only():
    binary.validate_page_buffer(bytes(4096))
    binary.validate_page_buffer(b"x" * 4096)


@pytest.mark.parametrize("size", [0, 12, 4095, 4097, 8192])
def test_page_buffer_rejects_other_lengths(size):
    with pytest.raises(ValidationError, match="exactly 4096"):
        binary.validate_page_buffer(bytes(size))


@pytest.mark.parametrize("payload", [None, "text", [], bytearray(4096), memoryview(b"")])
def test_page_buffer_requires_bytes(payload):
    with pytest.raises(InvalidTypeError):
        binary.validate_page_buffer(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"page_id": -1}, {"page_id": 2**32},
        {"slot_count": -1}, {"slot_count": 817}, {"slot_count": 65536},
        {"active_record_count": -1}, {"active_record_count": 3},
        {"active_record_count": 65536},
        {"free_space_start": 0}, {"free_space_start": 21},
        {"free_space_start": 23}, {"free_space_start": 65536},
        {"free_space_end": -1}, {"free_space_end": 21},
        {"free_space_end": 4097}, {"free_space_end": 65536},
        {"slot_count": 0, "active_record_count": 0, "free_space_start": 12},
    ],
)
def test_page_layout_rejects_invalid_fields(changes):
    with pytest.raises(ValidationError):
        layout(**changes)


@pytest.mark.parametrize(
    "field", ["page_id", "slot_count", "active_record_count", "free_space_start", "free_space_end"]
)
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_page_layout_requires_exact_integer_fields(field, value):
    with pytest.raises(InvalidTypeError):
        layout(**{field: value})


def test_empty_page_and_directory_capacity_boundaries():
    layout(slot_count=0, active_record_count=0, free_space_start=12, free_space_end=4096)
    layout(page_id=2**32 - 1, slot_count=816, active_record_count=0,
           free_space_start=4092, free_space_end=4096, active_regions=[])
    layout(free_space_end=22, active_regions=[(22, 1), (23, 4073)])
    layout(slot_count=1, active_record_count=1, free_space_start=17,
           free_space_end=17, active_regions=[(17, 4079)])


@pytest.mark.parametrize(
    "regions",
    [
        [(4000, 48), (4048, 48)],  # adjacency
        [(4080, 16), (4000, 3)],  # unordered and fragmented
        [(4096, 0), (4096, 0)],  # empty-schema records occupy no bytes
        [(4000, 96), (4096, 0)],
    ],
)
def test_active_regions_allow_adjacent_ranges_holes_and_empty_payloads(regions):
    layout(active_regions=regions)


@pytest.mark.parametrize(
    "regions",
    [
        [(4000, 50), (4049, 1)],  # overlap
        [(4000, 96), (4001, 1)],  # nesting
        [(4000, 1), (4000, 1)],  # duplicate
        [(3999, 1), (4096, 0)],  # in contiguous free space
        [(21, 1), (4096, 0)],  # directory
        [(4000, 97), (4096, 0)],  # past page end
        [(4097, 0), (4096, 0)],
        [(-1, 0), (4096, 0)],
        [(4096, -1), (4096, 0)],
        [(65536, 0), (4096, 0)],
        [(4000, 65536), (4096, 0)],
        [], [(4000, 1)],  # count mismatch
        [(4000,), (4096, 0)],
        [(4000, 0, 1), (4096, 0)],
    ],
)
def test_active_regions_reject_bad_extents_or_counts(regions):
    with pytest.raises(ValidationError):
        layout(active_regions=regions)


@pytest.mark.parametrize(
    "regions",
    [
        "", b"", bytearray(), {}, iter([]),
        [None, (4096, 0)], ["xx", (4096, 0)],
        [(True, 1), (4096, 0)], [(4000, False), (4096, 0)],
        [(4000.0, 1), (4096, 0)], [(4000, "1"), (4096, 0)],
    ],
)
def test_active_regions_reject_invalid_argument_types(regions):
    with pytest.raises(InvalidTypeError):
        layout(active_regions=regions)
