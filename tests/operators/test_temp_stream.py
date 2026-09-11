"""Task 6.12: schema-aware temporary row streams with bounded buffers."""

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import (
    InvalidTypeError,
    SchemaError,
    ValidationError,
)
from engine.operators import (
    TemporaryRowReader,
    TemporaryRowWriter,
    TemporaryRun,
    TemporaryWorkspace,
)
from engine.operators.temp_stream import (
    CHUNK_PAYLOAD_SIZE,
    DESCRIPTOR_PAGE_ID,
    DESCRIPTOR_SLOT_ID,
    MAX_TEMPORARY_ROW_BYTES,
    ROW_LENGTH_SIZE,
)
from engine.storage import Page, PageManager, Record
from tests.operator_helpers import STUDENTS, students


WIDE = Schema([Column("id", DataType.INTEGER), Column("text", DataType.VARCHAR)])
MIXED = Schema(
    [
        Column("i", DataType.INTEGER),
        Column("f", DataType.FLOAT),
        Column("b", DataType.BOOLEAN),
        Column("s", DataType.VARCHAR),
    ]
)


@pytest.fixture
def workspace(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as owner:
        yield owner


def round_trip(workspace, schema, rows):
    writer = TemporaryRowWriter(workspace, schema, label="run")
    with writer:
        for row in rows:
            writer.write(row)
        run = writer.finish()
    reader = TemporaryRowReader(workspace, run)
    with reader:
        read_back = []
        while (row := reader.next_row()) is not None:
            read_back.append(row)
    return run, read_back


def test_an_empty_stream_round_trips_as_zero_rows(workspace):
    run, rows = round_trip(workspace, STUDENTS, [])

    assert rows == []
    assert run.row_count == 0
    assert run.page_count == 0
    assert run.byte_length == 0


def test_every_supported_value_type_round_trips_unchanged(workspace):
    rows = [
        Record(MIXED, [0, 0.0, False, ""]),
        Record(MIXED, [-1, -0.0, True, "ñandú 漢字 🎓"]),
        Record(MIXED, [2**62, float("inf"), True, "x" * 100]),
        Record(MIXED, [-(2**62), float("-inf"), False, "tab\tnewline\n"]),
    ]

    _, read_back = round_trip(workspace, MIXED, rows)

    assert read_back == rows
    assert read_back[1].values[3] == "ñandú 漢字 🎓"


def test_duplicate_rows_are_preserved_as_separate_occurrences(workspace):
    rows = students() * 3

    run, read_back = round_trip(workspace, STUDENTS, rows)

    assert read_back == rows
    assert run.row_count == 12


def test_a_multipage_stream_streams_back_in_order(workspace):
    rows = [Record(WIDE, [number, f"value-{number}"]) for number in range(2000)]

    run, read_back = round_trip(workspace, WIDE, rows)

    assert run.page_count > 1
    assert read_back == rows


def test_a_row_wider_than_a_page_spans_pages_instead_of_being_truncated(workspace):
    rows = [
        Record(WIDE, [1, "a" * (CHUNK_PAYLOAD_SIZE * 2)]),
        Record(WIDE, [2, "b"]),
    ]

    run, read_back = round_trip(workspace, WIDE, rows)

    assert read_back == rows
    assert len(read_back[0].values[1]) == CHUNK_PAYLOAD_SIZE * 2
    assert run.page_count >= 3


@pytest.mark.parametrize("filler", [-1, 0, 1])
def test_rows_landing_exactly_on_a_chunk_boundary_round_trip(workspace, filler):
    text_length = CHUNK_PAYLOAD_SIZE - ROW_LENGTH_SIZE - 8 - 4 + filler
    rows = [Record(WIDE, [1, "a" * text_length]), Record(WIDE, [2, "tail"])]

    _, read_back = round_trip(workspace, WIDE, rows)

    assert read_back == rows


def test_a_row_above_the_documented_maximum_is_rejected_before_writing(workspace):
    writer = TemporaryRowWriter(workspace, WIDE, label="run")
    oversized = Record(WIDE, [1, "a" * (MAX_TEMPORARY_ROW_BYTES + 1)])

    with writer:
        with pytest.raises(ValidationError, match="exceeds the temporary maximum"):
            writer.write(oversized)

        writer.write(Record(WIDE, [2, "fits"]))
        run = writer.finish()

    assert run.row_count == 1


def test_a_completed_stream_can_be_reopened_within_its_owner_lifetime(workspace):
    rows = students()
    run, first = round_trip(workspace, STUDENTS, rows)

    second_reader = TemporaryRowReader(workspace, run)
    with second_reader:
        second = []
        while (row := second_reader.next_row()) is not None:
            second.append(row)

    assert first == second == rows


def test_two_readers_stream_one_run_independently(workspace):
    rows = students()
    run, _ = round_trip(workspace, STUDENTS, rows)

    first = TemporaryRowReader(workspace, run)
    second = TemporaryRowReader(workspace, run)
    try:
        assert first.next_row() == rows[0]
        assert second.next_row() == rows[0]
        assert first.next_row() == rows[1]
        assert second.next_row() == rows[1]
        assert first.rows_read == second.rows_read == 2
    finally:
        first.close()
        second.close()


def test_writers_reject_rows_of_another_schema(workspace):
    writer = TemporaryRowWriter(workspace, STUDENTS, label="run")

    with writer:
        with pytest.raises(SchemaError, match="differs from the temporary"):
            writer.write(Record(WIDE, [1, "x"]))
        with pytest.raises(InvalidTypeError):
            writer.write((1, "Ana", "CS", 22))


def test_a_writer_can_only_be_finished_once_and_refuses_later_rows(workspace):
    writer = TemporaryRowWriter(workspace, STUDENTS, label="run")
    writer.write(students()[0])
    writer.finish()

    with pytest.raises(RuntimeError, match="only be finished once"):
        writer.finish()
    with pytest.raises(RuntimeError, match="cannot accept rows"):
        writer.write(students()[1])
    writer.close()


def test_an_unfinished_writer_discards_its_file_on_close(workspace):
    writer = TemporaryRowWriter(workspace, STUDENTS, label="run")
    path = writer.path
    writer.write(students()[0])

    writer.close()

    assert not path.exists()
    assert workspace.tracked_paths == ()


def test_closing_a_reader_twice_is_safe_and_releases_the_file_once(workspace):
    rows = students()
    run, _ = round_trip(workspace, STUDENTS, rows)
    reader = TemporaryRowReader(workspace, run)

    reader.close()
    reader.close()

    assert reader.closed is True
    with pytest.raises(RuntimeError, match="closed temporary reader"):
        reader.next_row()


def test_a_reader_holds_a_discarded_run_open_until_it_closes(workspace):
    run, _ = round_trip(workspace, STUDENTS, students())
    reader = TemporaryRowReader(workspace, run)

    workspace.discard(run.path)
    assert run.path.exists()
    assert reader.next_row() is not None

    reader.close()
    assert not run.path.exists()


def test_a_truncated_final_record_is_distinguished_from_a_clean_end(workspace):
    rows = [Record(WIDE, [number, f"value-{number}"]) for number in range(200)]
    run, _ = round_trip(workspace, WIDE, rows)

    with PageManager.open(run.path) as manager:
        last = manager.allocated_page_count - 1
        page = manager.read_page(last)
        payload = page.read(DESCRIPTOR_SLOT_ID)
        truncated = Page(last)
        truncated.insert(payload[: len(payload) // 2])
        manager.write_page(truncated)

    reader = TemporaryRowReader(workspace, run)
    with reader:
        with pytest.raises(ValidationError, match="truncated|inside a row"):
            while reader.next_row() is not None:
                pass


def test_a_run_descriptor_disagreeing_with_the_file_is_refused_at_open(workspace):
    run, _ = round_trip(workspace, STUDENTS, students())
    inflated = TemporaryRun(
        path=run.path,
        schema=run.schema,
        row_count=run.row_count + 1,
        byte_length=run.byte_length,
        page_count=run.page_count,
    )

    with pytest.raises(ValidationError, match="differ from their run descriptor"):
        TemporaryRowReader(workspace, inflated)


def test_a_stream_holding_fewer_rows_than_declared_is_reported_at_the_end(
    workspace,
):
    rows = students()
    run, _ = round_trip(workspace, STUDENTS, rows)

    # Corrupt the persisted descriptor and the run descriptor together, so the
    # open-time cross-check passes and only the end-of-stream count can notice.
    with PageManager.open(run.path) as manager:
        page = manager.read_page(DESCRIPTOR_PAGE_ID)
        document = page.read(DESCRIPTOR_SLOT_ID).replace(
            b'"row_count":4', b'"row_count":9'
        )
        replacement = Page(DESCRIPTOR_PAGE_ID)
        replacement.insert(document)
        manager.write_page(replacement)

    inflated = TemporaryRun(
        path=run.path,
        schema=run.schema,
        row_count=9,
        byte_length=run.byte_length,
        page_count=run.page_count,
    )

    reader = TemporaryRowReader(workspace, inflated)
    with reader:
        with pytest.raises(ValidationError, match="declares 9"):
            while reader.next_row() is not None:
                pass


def test_an_incompatible_format_version_is_refused(workspace):
    run, _ = round_trip(workspace, STUDENTS, students())

    with PageManager.open(run.path) as manager:
        page = manager.read_page(DESCRIPTOR_PAGE_ID)
        document = page.read(DESCRIPTOR_SLOT_ID).replace(
            b'"version":1', b'"version":99'
        )
        replacement = Page(DESCRIPTOR_PAGE_ID)
        replacement.insert(document)
        manager.write_page(replacement)

    with pytest.raises(ValidationError, match="Unsupported temporary stream version"):
        TemporaryRowReader(workspace, run)


def test_a_file_that_is_not_a_temporary_stream_is_refused(workspace):
    path = workspace.allocate("foreign")
    with PageManager.create(path) as manager:
        page_id = manager.allocate_page()
        page = Page(page_id)
        page.insert(b"not json at all")
        manager.write_page(page)

    run = TemporaryRun(path=path, schema=STUDENTS, row_count=0, byte_length=0, page_count=0)

    with pytest.raises(ValidationError, match="not valid JSON|not a temporary"):
        TemporaryRowReader(workspace, run)


def test_temporary_io_is_visible_through_real_page_counters(workspace):
    rows = [Record(WIDE, [number, f"value-{number}"]) for number in range(500)]
    writer = TemporaryRowWriter(workspace, WIDE, label="run")
    with writer:
        for row in rows:
            writer.write(row)
        assert writer.pages_written > 1
        run = writer.finish()

    reader = TemporaryRowReader(workspace, run)
    with reader:
        while reader.next_row() is not None:
            pass
        assert reader.pages_read > 1


def test_readers_and_writers_validate_their_arguments(workspace):
    with pytest.raises(InvalidTypeError, match="TemporaryWorkspace"):
        TemporaryRowWriter(object(), STUDENTS)
    with pytest.raises(InvalidTypeError, match="Schema"):
        TemporaryRowWriter(workspace, STUDENTS.columns)
    with pytest.raises(InvalidTypeError, match="TemporaryWorkspace"):
        TemporaryRowReader(object(), None)
    with pytest.raises(InvalidTypeError, match="TemporaryRun"):
        TemporaryRowReader(workspace, "run")
    with pytest.raises(ValidationError):
        TemporaryRun(path="p", schema=STUDENTS, row_count=-1, byte_length=0, page_count=0)
    with pytest.raises(InvalidTypeError):
        TemporaryRun(path="p", schema=None, row_count=0, byte_length=0, page_count=0)
