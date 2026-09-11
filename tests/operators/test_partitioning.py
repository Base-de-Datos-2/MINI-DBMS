"""Task 6.19: reusable bounded hash partitioning."""

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, ValidationError
from engine.operators import (
    ExecutionContext,
    HashPartitioner,
    TemporaryRowReader,
    TemporaryWorkspace,
    maximum_partition_count,
    partition_hash,
)
from engine.operators.partitioning import (
    DEFAULT_PARTITION_COUNT,
    avalanche64,
    encode_partition_key,
)
from engine.operators.temp_stream import CHUNK_PAYLOAD_SIZE
from engine.storage import Record


KEYED = Schema(
    [Column("key", DataType.VARCHAR), Column("value", DataType.INTEGER)]
)


@pytest.fixture
def workspace(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as owner:
        yield owner


def partitioner(workspace, *, count=4, level=0, context=None, schema=KEYED):
    return HashPartitioner(
        workspace,
        schema,
        key_positions=[0],
        key_types=[schema.columns[0].data_type],
        partition_count=count,
        level=level,
        context=context,
    )


def read_partition(workspace, partition):
    reader = TemporaryRowReader(workspace, partition.run)
    with reader:
        rows = []
        while (row := reader.next_row()) is not None:
            rows.append(row)
    return rows


def test_equal_keys_always_route_to_the_same_partition(workspace):
    rows = [Record(KEYED, [f"k{number % 20}", number]) for number in range(500)]
    routing = partitioner(workspace)

    with routing:
        seen = {}
        for row in rows:
            seen.setdefault(row.values[0], set()).add(routing.write(row))
        partitions = routing.finish()

    assert all(len(indexes) == 1 for indexes in seen.values())
    assert sum(partition.row_count for partition in partitions) == len(rows)


def test_every_row_occurrence_belongs_to_exactly_one_partition(workspace):
    rows = [Record(KEYED, [f"k{number % 7}", number]) for number in range(300)]
    routing = partitioner(workspace)

    with routing:
        for row in rows:
            routing.write(row)
        partitions = routing.finish()

    recovered = []
    for partition in partitions:
        recovered.extend(read_partition(workspace, partition))

    assert sorted(tuple(row.values) for row in recovered) == sorted(
        tuple(row.values) for row in rows
    )


def test_all_equal_keys_land_in_one_partition_without_losing_rows(workspace):
    rows = [Record(KEYED, ["same", number]) for number in range(200)]
    routing = partitioner(workspace)

    with routing:
        for row in rows:
            routing.write(row)
        partitions = routing.finish()

    assert len(partitions) == 1
    assert partitions[0].row_count == 200
    assert len(read_partition(workspace, partitions[0])) == 200


def test_many_distinct_keys_spread_across_every_partition(workspace):
    rows = [Record(KEYED, [f"k{number}", number]) for number in range(2000)]
    routing = partitioner(workspace, count=8)

    with routing:
        for row in rows:
            routing.write(row)
        partitions = routing.finish()

    assert len(partitions) == 8
    assert min(partition.row_count for partition in partitions) > 100


def test_empty_partitions_are_discarded_rather_than_represented(workspace):
    rows = [Record(KEYED, ["same", number]) for number in range(20)]
    routing = partitioner(workspace, count=8)

    with routing:
        for row in rows:
            routing.write(row)
        partitions = routing.finish()

    assert len(partitions) == 1
    assert workspace.tracked_paths == (partitions[0].path,)


def test_a_deeper_level_redistributes_a_partition_instead_of_collapsing_it():
    keys = [f"k{number}" for number in range(400)]
    at_level_zero = {}
    for key in keys:
        index = partition_hash((key,), (DataType.VARCHAR,), level=0) % 2
        at_level_zero.setdefault(index, []).append(key)

    for subset in at_level_zero.values():
        children = {}
        for key in subset:
            index = partition_hash((key,), (DataType.VARCHAR,), level=1) % 2
            children[index] = children.get(index, 0) + 1
        # FNV's low bit is the parity of its input, so a seed that only flips
        # one byte would move every key together. Both children must be used.
        assert len(children) == 2
        assert min(children.values()) > len(subset) // 4


def test_the_avalanche_finalizer_decorrelates_neighbouring_values():
    digests = [avalanche64(value) for value in range(256)]

    # Consecutive inputs must not share a low bit pattern, which is exactly
    # what raw FNV fails at. Zero is a fixed point of this mixer, which is
    # harmless because the hash is always mixed with a non-zero level seed.
    assert {digest % 2 for digest in digests} == {0, 1}
    assert {digest % 8 for digest in digests} == set(range(8))
    assert len(set(digests)) == len(digests)
    assert all(digest < (1 << 64) for digest in digests)


def test_routing_normalizes_signed_zero_and_rejects_nan():
    floats = (DataType.FLOAT,)

    assert partition_hash((-0.0,), floats) == partition_hash((0.0,), floats)
    assert encode_partition_key(DataType.FLOAT, -0.0) == encode_partition_key(
        DataType.FLOAT, 0.0
    )
    with pytest.raises(ValidationError, match="NaN"):
        partition_hash((float("nan"),), floats)


def test_routing_keeps_composite_keys_unambiguous():
    text = (DataType.VARCHAR, DataType.VARCHAR)

    assert partition_hash(("ab", "c"), text) != partition_hash(("a", "bc"), text)


def test_routing_distinguishes_equal_looking_values_of_different_types():
    assert partition_hash((0,), (DataType.INTEGER,)) != partition_hash(
        (0.0,), (DataType.FLOAT,)
    )
    assert partition_hash((1,), (DataType.INTEGER,)) != partition_hash(
        (True,), (DataType.BOOLEAN,)
    )


def test_a_long_key_is_routable_even_though_it_is_not_indexable():
    long_key = "x" * 5000

    assert partition_hash((long_key,), (DataType.VARCHAR,)) >= 0


def test_partitioning_reserves_its_buffers_and_handles(workspace):
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        routing = partitioner(workspace, count=4, context=context)

        assert context.reserved_bytes == 4 * CHUNK_PAYLOAD_SIZE
        assert context.open_handle_count == 4

        routing.write(Record(KEYED, ["k", 1]))
        routing.finish()

        assert context.reserved_bytes == 0
        assert context.open_handle_count == 0


def test_a_fan_out_beyond_the_granted_resources_is_refused(workspace):
    with ExecutionContext(memory_budget_bytes=4 * CHUNK_PAYLOAD_SIZE) as context:
        with pytest.raises(ValidationError, match="exceeds the"):
            partitioner(workspace, count=8, context=context)

        assert context.reserved_bytes == 0
        assert context.open_handle_count == 0


def test_the_handle_limit_bounds_the_fan_out(workspace):
    with ExecutionContext(
        memory_budget_bytes=256 * 4096, max_open_handles=3
    ) as context:
        assert maximum_partition_count(context.memory_budget_bytes, 3) == 2
        with pytest.raises(ValidationError, match="exceeds the"):
            partitioner(workspace, count=4, context=context)


def test_maximum_partition_count_leaves_room_for_an_input_buffer():
    assert maximum_partition_count(3 * CHUNK_PAYLOAD_SIZE, 32) == 2
    assert maximum_partition_count(CHUNK_PAYLOAD_SIZE, 32) == 0
    assert maximum_partition_count(0, 32) == 0


def test_an_unfinished_partition_file_cannot_be_consumed_as_valid_data(workspace):
    routing = partitioner(workspace, count=2)
    routing.write(Record(KEYED, ["k", 1]))
    paths = [writer.path for writer in routing._writers]

    routing.close()

    assert all(not path.exists() for path in paths)
    assert workspace.tracked_paths == ()


def test_a_partitioner_can_only_be_finished_once(workspace):
    routing = partitioner(workspace, count=2)
    routing.write(Record(KEYED, ["k", 1]))
    routing.finish()

    with pytest.raises(RuntimeError, match="only be finished once"):
        routing.finish()
    with pytest.raises(RuntimeError, match="cannot accept rows"):
        routing.write(Record(KEYED, ["k", 2]))


def test_partitioner_arguments_are_validated(workspace):
    with pytest.raises(InvalidTypeError, match="TemporaryWorkspace"):
        HashPartitioner(object(), KEYED, key_positions=[0], key_types=[DataType.VARCHAR])
    with pytest.raises(InvalidTypeError, match="Schema"):
        HashPartitioner(workspace, KEYED.columns, key_positions=[0], key_types=[])
    with pytest.raises(ValidationError, match="at least two partitions"):
        partitioner(workspace, count=1)
    with pytest.raises(ValidationError, match="non-negative"):
        partitioner(workspace, level=-1)
    with pytest.raises(ValidationError, match="needs a data type"):
        HashPartitioner(
            workspace, KEYED, key_positions=[0, 1], key_types=[DataType.VARCHAR]
        )
    with pytest.raises(InvalidTypeError):
        partitioner(workspace, count="4")
    routing = partitioner(workspace, count=2)
    with routing:
        with pytest.raises(InvalidTypeError, match="requires a Record"):
            routing.write(("k", 1))


def test_partition_descriptors_stay_small_as_rows_grow(workspace):
    rows = [Record(KEYED, [f"k{number}", number]) for number in range(1000)]
    routing = partitioner(workspace, count=DEFAULT_PARTITION_COUNT)

    with routing:
        for row in rows:
            routing.write(row)
        partitions = routing.finish()

    for partition in partitions:
        assert partition.level == 0
        assert isinstance(partition.row_count, int)
        assert isinstance(partition.byte_length, int)
        assert partition.path.exists()
