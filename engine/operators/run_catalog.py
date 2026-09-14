"""Disk-backed run descriptors; one fixed-size metadata record per run."""

import json

from engine.errors import CorruptTemporaryError, ValidationError

from .temp_stream import TemporaryRun


CATALOG_SLOT_BYTES = 512
CATALOG_WORK_BYTES = 2048
RUN_ENTRY_BYTES = 512


class RunCatalog:
    """An indexed metadata stream with no in-memory list proportional to input.

    Metadata uses bounded fixed slots and short-lived handles. It is separate
    from row-page I/O and is counted in the workspace's metadata statistics.
    """

    def __init__(self, workspace, schema):
        self.workspace = workspace
        self.schema = schema
        self.count = 0
        self.max_row_bytes = 0
        self.closed = False
        self.reservation = workspace.context.reserve(CATALOG_WORK_BYTES, "run-catalog")
        self.path = None
        try:
            self.path = workspace.allocate("catalog", ".meta")
            with workspace.metadata_file(self.path, "xb"):
                pass
            workspace.manage(self)
        except BaseException:
            self.reservation.release()
            raise

    def __len__(self):
        return self.count

    def append(self, run):
        document = [run.path.name, run.row_count, run.byte_length,
                    run.page_count, run.max_row_bytes]
        payload = json.dumps(document).encode("ascii")
        if len(payload) > CATALOG_SLOT_BYTES:
            raise ValidationError("Run descriptor exceeds its fixed metadata slot")
        with self.workspace.metadata_file(self.path, "r+b") as stream:
            stream.seek(self.count * CATALOG_SLOT_BYTES)
            stream.write(payload.ljust(CATALOG_SLOT_BYTES, b"\x00"))
        self.workspace.note_size(self.path, (self.count + 1) * CATALOG_SLOT_BYTES)
        self.workspace.record_temporary_io(metadata_writes=1)
        self.count += 1
        self.max_row_bytes = max(self.max_row_bytes, run.max_row_bytes)

    def read(self, index):
        if not 0 <= index < self.count:
            raise IndexError(index)
        with self.workspace.metadata_file(self.path, "rb") as stream:
            stream.seek(index * CATALOG_SLOT_BYTES)
            payload = stream.read(CATALOG_SLOT_BYTES)
        self.workspace.record_temporary_io(metadata_reads=1)
        try:
            name, rows, length, pages, width = json.loads(payload.rstrip(b"\x00"))
            path = self.workspace.directory / name
            if path.parent != self.workspace.directory or path.name != name:
                raise ValueError("invalid run path")
            return TemporaryRun(path, self.schema, rows, length, pages, width)
        except (ValueError, TypeError) as error:
            raise CorruptTemporaryError("Corrupt run catalog") from error

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.workspace.forget(self)
        try:
            self.workspace.discard(self.path)
        finally:
            self.reservation.release()
