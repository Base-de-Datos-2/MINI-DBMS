"""Bounded temporary hash partitioning, shared by grouping and joins."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.catalog import DataType, Schema
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes.hash_codec import HashCodec
from engine.storage.record import Record, RecordValue
from engine.storage.value_codec import ValueCodec

from .context import ExecutionContext
from .expressions import validate_comparable
from .temp_files import TemporaryWorkspace
from .temp_stream import CHUNK_PAYLOAD_SIZE, TemporaryRowWriter, TemporaryRun


#: Default number of partitions produced by one partitioning step.
DEFAULT_PARTITION_COUNT = 8

#: Hard ceiling on recursive repartitioning, so a pathological key distribution
#: cannot loop forever before the documented fallback takes over.
MAX_PARTITION_LEVEL = 4

#: Mask and odd multipliers of the 64-bit avalanche applied to the FNV result.
_MASK64 = (1 << 64) - 1
_MIX_A = 0xFF51AFD7ED558CCD
_MIX_B = 0xC4CEB9FE1A85EC53
#: Odd constant used to turn a recursion level into a well-spread seed.
_LEVEL_STRIDE = 0x9E3779B97F4A7C15


def avalanche64(value: int) -> int:
    """Spread a 64-bit value so that every output bit depends on every input bit.

    FNV-1a multiplies by an odd prime, which leaves its **low** bits almost
    linear: the least significant bit of an FNV digest is just the parity of
    the input bytes. Taking ``digest % partition_count`` for a power-of-two
    fan-out would therefore read a near-XOR of the key, and changing a seed
    byte would flip that bit for *every* key at once, sending a whole
    partition into a single child and making recursion useless.

    This finalizer is local to query execution and does not change the
    persistent Stage 5 index format, whose directory bits are its own decision.
    """

    value &= _MASK64
    value ^= value >> 33
    value = (value * _MIX_A) & _MASK64
    value ^= value >> 33
    value = (value * _MIX_B) & _MASK64
    value ^= value >> 33
    return value


def encode_partition_key(data_type: DataType, value: RecordValue) -> bytes:
    """Return canonical bytes for one grouping or join key value.

    The one-byte type tags are the Stage 5 tags, so an INTEGER 0 and a FLOAT
    0.0 stay distinct exactly as they do in the persistent hash index. The
    encoded-size limits of the index key codec are deliberately not applied:
    a grouping key may be a string longer than any indexable key.
    """

    checked = validate_comparable(data_type, value)
    if data_type is DataType.FLOAT and checked == 0.0:
        # Python equality treats both signed zeros as one key, so the bytes
        # that decide the partition must treat them as one key too.
        checked = 0.0
    return HashCodec.TYPE_TAGS[data_type] + ValueCodec.encode(data_type, checked)


def partition_hash(
    values: Sequence[RecordValue],
    data_types: Sequence[DataType],
    *,
    level: int = 0,
) -> int:
    """Hash a complete composite key, mixing the recursion level as the seed.

    Repeating an identical hash function at a deeper level would send every
    row of a difficult partition to the same child and make no progress, so
    the level becomes a seed that is mixed into the digest and the result is
    put through :func:`avalanche64`. Both steps are needed: seeding alone is
    not enough because FNV's low bits stay near-linear in the input.
    """

    if type(level) is not int or level < 0:
        raise ValidationError("Partition level must be a non-negative int")
    payload = b""
    for data_type, value in zip(data_types, values):
        encoded = encode_partition_key(data_type, value)
        # The length prefix keeps ("ab", "c") distinct from ("a", "bc").
        payload += len(encoded).to_bytes(4, "little") + encoded
    seed = avalanche64((level + 1) * _LEVEL_STRIDE)
    return avalanche64(HashCodec.hash_bytes(payload) ^ seed)


@dataclass(frozen=True, slots=True)
class Partition:
    """One completed partition file plus the routing that produced it."""

    index: int
    level: int
    run: TemporaryRun

    @property
    def row_count(self) -> int:
        """Return how many rows landed in this partition."""

        return self.run.row_count

    @property
    def byte_length(self) -> int:
        """Return the framed size of this partition's rows."""

        return self.run.byte_length

    @property
    def path(self) -> object:
        """Return the workspace-owned path backing this partition."""

        return self.run.path


def maximum_partition_count(budget_bytes: int, max_open_handles: int) -> int:
    """Return the largest fan-out that leaves an input buffer and a handle.

    Under the simplified one-page-per-stream model, ``budget`` must cover one
    output buffer per partition plus one buffer for the input being read.
    """

    by_memory = (budget_bytes // CHUNK_PAYLOAD_SIZE) - 1
    by_handles = max_open_handles - 1
    return max(min(by_memory, by_handles), 0)


class HashPartitioner:
    """Route rows into bounded temporary partitions by their complete key.

    Every row occurrence lands in exactly one partition for a given level, and
    two equal keys always land together, which is what lets grouping finalize
    a group from one partition and lets a join match both of its sides.

    Buffering is one page per open partition, so memory and handles are
    bounded by the fan-out rather than by the input size.
    """

    __slots__ = (
        "_workspace",
        "_schema",
        "_key_positions",
        "_key_types",
        "_count",
        "_level",
        "_writers",
        "_leases",
        "_context",
        "_reservation",
        "_finished",
        "_rows_written",
        "_pages_written",
        "_label",
    )

    def __init__(
        self,
        workspace: TemporaryWorkspace,
        schema: Schema,
        *,
        key_positions: Sequence[int],
        key_types: Sequence[DataType],
        partition_count: int = DEFAULT_PARTITION_COUNT,
        level: int = 0,
        context: ExecutionContext | None = None,
        label: str = "part",
    ) -> None:
        if not isinstance(workspace, TemporaryWorkspace):
            raise InvalidTypeError("A partitioner requires a TemporaryWorkspace")
        if not isinstance(schema, Schema):
            raise InvalidTypeError("A partitioner requires a Schema")
        if type(partition_count) is not int:
            raise InvalidTypeError("partition_count must be an int")
        if partition_count < 2:
            raise ValidationError("Partitioning needs at least two partitions")
        if type(level) is not int or level < 0:
            raise ValidationError("Partition level must be a non-negative int")
        if context is not None and not isinstance(context, ExecutionContext):
            raise InvalidTypeError("context must be an ExecutionContext")
        self._workspace = workspace
        self._schema = schema
        self._key_positions = tuple(key_positions)
        self._key_types = tuple(key_types)
        if len(self._key_positions) != len(self._key_types):
            raise ValidationError("Each partition key position needs a data type")
        self._count = partition_count
        self._level = level
        self._context = context
        self._label = label
        self._finished = False
        self._rows_written = 0
        self._pages_written = 0
        self._leases: list[object] = []
        self._reservation = None
        self._writers: list[TemporaryRowWriter] = []
        self._acquire()

    def _acquire(self) -> None:
        needed = self._count * CHUNK_PAYLOAD_SIZE
        try:
            if self._context is not None:
                allowed = maximum_partition_count(
                    self._context.memory_budget_bytes,
                    self._context.max_open_handles,
                )
                if self._count > allowed:
                    raise ValidationError(
                        f"A fan-out of {self._count} partitions exceeds the "
                        f"{allowed} the granted resources allow"
                    )
                self._reservation = self._context.reserve(needed, "partition-buffers")
            for index in range(self._count):
                if self._context is not None:
                    self._leases.append(
                        self._context.acquire_handle(f"{self._label}-{index}")
                    )
                self._writers.append(
                    TemporaryRowWriter(
                        self._workspace,
                        self._schema,
                        label=f"{self._label}{self._level}-{index}",
                    )
                )
        except BaseException:
            self._release()
            raise

    def _release(self) -> None:
        for writer in self._writers:
            self._pages_written += writer.pages_written
            writer.close()
        self._writers = []
        for lease in self._leases:
            lease.release()
        self._leases = []
        if self._reservation is not None:
            self._reservation.release()
            self._reservation = None

    @property
    def partition_count(self) -> int:
        """Return the configured fan-out."""

        return self._count

    @property
    def level(self) -> int:
        """Return the recursion level this partitioner writes."""

        return self._level

    @property
    def rows_written(self) -> int:
        """Return how many rows have been routed so far."""

        return self._rows_written

    @property
    def pages_written(self) -> int:
        """Return the real page writes performed by the partition writers."""

        if self._writers:
            return sum(writer.pages_written for writer in self._writers)
        return self._pages_written

    def index_for(self, values: Sequence[RecordValue]) -> int:
        """Return the partition a key belongs to at this level."""

        key = tuple(values[position] for position in self._key_positions)
        return partition_hash(key, self._key_types, level=self._level) % self._count

    def write(self, record: Record) -> int:
        """Route one row to its partition and return that partition index."""

        if self._finished:
            raise RuntimeError("A finished partitioner cannot accept rows")
        if not isinstance(record, Record):
            raise InvalidTypeError("A partitioner requires a Record")
        index = self.index_for(record.values)
        self._writers[index].write(record)
        self._rows_written += 1
        return index

    def finish(self) -> tuple[Partition, ...]:
        """Publish every non-empty partition and discard the empty ones.

        A partition becomes readable only when its descriptor page is written,
        which happens last. A partitioner that dies mid-write therefore leaves
        files that cannot be mistaken for complete data.
        """

        if self._finished:
            raise RuntimeError("A partitioner can only be finished once")
        self._finished = True
        partitions: list[Partition] = []
        try:
            for index, writer in enumerate(self._writers):
                run = writer.finish()
                self._pages_written += run.page_count + 1
                if run.row_count == 0:
                    # An empty partition costs nothing to represent as absence.
                    self._workspace.discard(run.path)
                    continue
                partitions.append(Partition(index=index, level=self._level, run=run))
        finally:
            self._writers = []
            for lease in self._leases:
                lease.release()
            self._leases = []
            if self._reservation is not None:
                self._reservation.release()
                self._reservation = None
        return tuple(partitions)

    def close(self) -> None:
        """Release buffers and handles; unfinished partitions are discarded."""

        if not self._finished:
            self._finished = True
            self._release()

    def __enter__(self) -> "HashPartitioner":
        """Return this partitioner for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Release partition resources on every exit path."""

        self.close()
