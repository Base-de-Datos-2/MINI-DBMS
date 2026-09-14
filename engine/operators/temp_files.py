"""Execution-owned temporary paths with a disk-backed ownership registry."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from engine.errors import InvalidTypeError, ValidationError
from .context import ExecutionContext

WORKSPACE_PREFIX = "minidb-exec-"
REGISTRY_SLOT_BYTES = 512
REGISTRY_WORK_BYTES = 2048


def _component(value, label, *, empty=False):
    if not isinstance(value, str):
        raise InvalidTypeError(f"{label} must be a string")
    if (not empty and not value.strip()) or any(c in value for c in '/\\:<>|?*\x00'):
        raise ValidationError(f"{label} must be a filename component, not a path")
    if value in (".", "..") or len(value.encode("utf-8")) > 100:
        raise ValidationError(f"Invalid {label}")
    return value


def cleanup_preserving_error(callback, original=None):
    """Attempt cleanup without replacing an already propagating exception."""
    if original is None:
        original = sys.exception()
    try:
        callback()
    except BaseException as error:
        if original is None or isinstance(original, GeneratorExit):
            raise
        original.add_note(f"Cleanup also failed: {type(error).__name__}: {error}")


@dataclass(slots=True)
class _TrackedFile:
    path: Path
    ordinal: int
    readers: int = 0
    discard_requested: bool = False
    active: bool = True
    physical_size: int = 0


@dataclass(slots=True)
class WorkspaceStatistics:
    files_allocated: int = 0
    files_deleted: int = 0
    readers_opened: int = 0
    peak_tracked_files: int = 0
    metadata_reads: int = 0
    metadata_writes: int = 0
    data_pages_read: int = 0
    data_pages_written: int = 0
    bytes_spilled: int = 0
    live_temporary_bytes: int = 0
    peak_live_temporary_bytes: int = 0


class TemporaryWorkspace:
    """Own exact allocations without a growing in-memory dictionary of paths.

    Fixed-size ownership entries live in a private random-access metadata file.
    Only currently open resources are retained in Python. All metadata handles
    are short lived and participate in the same handle limit as data streams.
    ``tracked_paths`` is an explicit diagnostic snapshot; execution and cleanup
    use the bounded iterator instead.
    """

    def __init__(self, *, label="query", parent_directory=None,
                 retain_for_debug=False, context=None):
        _component(label, "Workspace label")
        if type(retain_for_debug) is not bool:
            raise InvalidTypeError("retain_for_debug must be a bool")
        if context is not None and not isinstance(context, ExecutionContext):
            raise InvalidTypeError("context must be an ExecutionContext")
        if parent_directory is not None:
            if not isinstance(parent_directory, (str, os.PathLike)):
                raise InvalidTypeError("parent_directory must be a path")
            if not Path(parent_directory).is_dir():
                raise ValidationError("Workspace parent directory does not exist")
        self.context = context
        self._reservation = None if context is None else context.reserve(
            REGISTRY_WORK_BYTES, "temporary-ownership-metadata")
        self._closed = False
        self._retain = retain_for_debug
        self._statistics = WorkspaceStatistics()
        self._unreclaimed = ()
        self._resources = {}
        self._active_count = 0
        self._registry_bytes = 0
        self._directory = None
        try:
            self._directory = Path(tempfile.mkdtemp(
                prefix=f"{WORKSPACE_PREFIX}{label}-", dir=parent_directory)).resolve()
            self._registry = self._directory / "ownership.registry"
            with self._registry_file("xb"):
                pass
            if context is not None:
                context.manage(self)
        except BaseException as error:
            # A failed constructor has no caller-visible owner to close later.
            # Return its budget even if removing an owned path also fails.
            try:
                if self._directory is not None:
                    for path in (self._registry, self._directory):
                        try:
                            if path == self._directory:
                                path.rmdir()
                            else:
                                path.unlink(missing_ok=True)
                        except OSError as cleanup_error:
                            error.add_note(
                                f"Temporary cleanup left path {path}: {cleanup_error}")
            finally:
                self._closed = True
                if self._reservation is not None:
                    self._reservation.release()
            raise

    @property
    def directory(self):
        return self._directory

    @property
    def closed(self):
        return self._closed

    @property
    def retain_for_debug(self):
        return self._retain

    @property
    def statistics(self):
        return self._statistics

    @property
    def tracked_paths(self):
        return tuple(entry.path for entry in self._entries() if entry.active)

    @property
    def unreclaimed_paths(self):
        return self._unreclaimed

    def _require_open(self):
        if self._closed:
            raise RuntimeError("The temporary workspace is closed")

    def _check_directory(self):
        if self._directory.is_symlink() or self._directory.resolve() != self._directory:
            raise ValidationError("Temporary directory was replaced by a link")

    def lease(self, label="temporary"):
        return None if self.context is None else self.context.acquire_handle(label)

    @contextmanager
    def _registry_file(self, mode):
        self._check_directory()
        if self._registry.is_symlink():
            raise ValidationError("Temporary registry must not be a link")
        lease = self.lease("temporary-registry")
        try:
            with self._registry.open(mode) as stream:
                yield stream
        finally:
            if lease is not None:
                lease.release()

    def _read(self, ordinal):
        with self._registry_file("rb") as stream:
            stream.seek(ordinal * REGISTRY_SLOT_BYTES)
            payload = stream.read(REGISTRY_SLOT_BYTES)
        self.record_temporary_io(metadata_reads=1)
        try:
            name, readers, discard, active, size = json.loads(payload.rstrip(b"\x00"))
            path = self._directory / name
            if path.parent != self._directory or path.name != name:
                raise ValueError("path outside workspace")
            if type(size) is not int or size < 0:
                raise ValueError("invalid temporary size")
            return _TrackedFile(path, ordinal, readers, discard, active, size)
        except (ValueError, TypeError) as error:
            raise ValidationError("Corrupt temporary ownership registry") from error

    def _write(self, entry):
        payload = json.dumps([entry.path.name, entry.readers,
                              entry.discard_requested, entry.active,
                              entry.physical_size],
                             ensure_ascii=True).encode("ascii")
        if len(payload) > REGISTRY_SLOT_BYTES:
            raise ValidationError("Temporary ownership entry is too large")
        with self._registry_file("r+b") as stream:
            stream.seek(entry.ordinal * REGISTRY_SLOT_BYTES)
            stream.write(payload.ljust(REGISTRY_SLOT_BYTES, b"\x00"))
        self.record_temporary_io(metadata_writes=1)

    def record_temporary_io(self, *, pages_read=0, pages_written=0,
                            metadata_reads=0, metadata_writes=0,
                            bytes_spilled=0):
        stats = self._statistics
        stats.data_pages_read += pages_read
        stats.data_pages_written += pages_written
        stats.metadata_reads += metadata_reads
        stats.metadata_writes += metadata_writes
        stats.bytes_spilled += bytes_spilled
        if self.context is not None:
            self.context.record_temporary_io(
                pages_read=pages_read, pages_written=pages_written,
                metadata_reads=metadata_reads, metadata_writes=metadata_writes,
                bytes_spilled=bytes_spilled,
            )

    def _adjust_size(self, delta):
        stats = self._statistics
        stats.live_temporary_bytes += delta
        stats.peak_live_temporary_bytes = max(
            stats.peak_live_temporary_bytes, stats.live_temporary_bytes)
        if self.context is not None:
            self.context.adjust_temporary_bytes(delta)

    def note_size(self, path, physical_size):
        """Account the actual size of one owned file, including page headers."""
        if type(physical_size) is not int or physical_size < 0:
            raise ValidationError("Temporary physical size must be non-negative")
        entry = self._tracked(path)
        delta = physical_size - entry.physical_size
        if delta:
            entry.physical_size = physical_size
            self._write(entry)
            self._adjust_size(delta)

    def _entries(self):
        for ordinal in range(self._statistics.files_allocated):
            yield self._read(ordinal)

    def _tracked(self, path):
        if not isinstance(path, (str, os.PathLike)):
            raise InvalidTypeError("path must be a path")
        path = Path(path).absolute()
        match = re.search(r"-(\d{6,})(?:\.[^.]+)?$", path.name)
        if path.parent == self._directory and match:
            ordinal = int(match.group(1))
            if ordinal < self._statistics.files_allocated:
                entry = self._read(ordinal)
                if entry.path == path and entry.active:
                    return entry
        raise ValidationError(f"This workspace does not own {path}")

    def allocate(self, label="run", suffix=".tmp"):
        self._require_open()
        _component(label, "Temporary file label")
        _component(suffix, "Temporary file suffix", empty=True)
        if suffix and (not suffix.startswith(".") or "." in suffix[1:]):
            raise ValidationError("Temporary suffix must be empty or one extension")
        self._check_directory()
        ordinal = self._statistics.files_allocated
        path = self._directory / f"{label}-{ordinal:06d}{suffix}"
        if path.exists() or path.is_symlink():
            raise ValidationError(f"Temporary path already exists: {path}")
        self._write(_TrackedFile(path, ordinal))
        self._statistics.files_allocated += 1
        self._registry_bytes += REGISTRY_SLOT_BYTES
        self._adjust_size(REGISTRY_SLOT_BYTES)
        self._active_count += 1
        self._statistics.peak_tracked_files = max(
            self._statistics.peak_tracked_files, self._active_count)
        return path

    def acquire(self, path):
        self._require_open()
        entry = self._tracked(path)
        if entry.discard_requested:
            raise ValidationError("A discarded file cannot accept a new reader")
        if entry.path.is_symlink():
            raise ValidationError("Temporary files must not be links")
        entry.readers += 1
        self._write(entry)
        self._statistics.readers_opened += 1
        return entry.path

    def release(self, path):
        entry = self._tracked(path)
        entry.readers = max(0, entry.readers - 1)
        self._write(entry)
        if entry.discard_requested and not entry.readers:
            self._delete(entry)

    def manage(self, resource):
        self._resources[id(resource)] = resource

    def forget(self, resource):
        self._resources.pop(id(resource), None)

    def discard(self, path):
        entry = self._tracked(path)
        entry.discard_requested = True
        self._write(entry)
        if not entry.readers:
            self._delete(entry)

    def _delete(self, entry):
        self._check_directory()
        if not self._retain:
            try:
                entry.path.unlink()
            except FileNotFoundError:
                pass
            else:
                self._statistics.files_deleted += 1
            if entry.physical_size:
                self._adjust_size(-entry.physical_size)
                entry.physical_size = 0
        entry.active = False
        self._write(entry)
        self._active_count -= 1

    @contextmanager
    def metadata_file(self, path, mode):
        """Open an owned catalog file under the shared handle ceiling."""
        path = self.acquire(path)
        lease = None
        try:
            lease = self.lease("run-catalog")
            with path.open(mode) as stream:
                yield stream
        finally:
            if lease is not None:
                lease.release()
            self.release(path)

    def close(self):
        if self._closed:
            return
        failures = []
        # Each resource unregisters itself; only a bounded handle set lives here.
        for resource in reversed(tuple(self._resources.values())):
            try:
                resource.close()
            except BaseException as error:
                failures.append(error)
        self._closed = True
        if self.context is not None:
            self.context.forget(self)
        unreclaimed = []
        try:
            registry_readable = True
            try:
                self._check_directory()
                for entry in self._entries():
                    if not entry.active:
                        continue
                    try:
                        if entry.readers:
                            unreclaimed.append(entry.path)
                        else:
                            self._delete(entry)
                    except (OSError, ValidationError) as error:
                        failures.append(error)
                        unreclaimed.append(entry.path)
            except (OSError, ValidationError) as error:
                # Without a readable ownership registry there is no safe way
                # to infer the remaining owned paths. Keep it for diagnosis.
                failures.append(error)
                registry_readable = False
                unreclaimed.extend((self._registry, self._directory))
            if registry_readable:
                try:
                    self._registry.unlink()
                    self._adjust_size(-self._registry_bytes)
                    self._registry_bytes = 0
                except OSError as error:
                    failures.append(error)
                    unreclaimed.append(self._registry)
                if not self._retain:
                    try:
                        self._directory.rmdir()
                    except OSError:
                        unreclaimed.append(self._directory)
        finally:
            if self._reservation is not None:
                self._reservation.release()
        self._unreclaimed = tuple(unreclaimed)
        if unreclaimed or failures:
            message = ", ".join(map(str, unreclaimed))
            error = ValidationError(f"Temporary cleanup left files behind: {message}")
            for failure in failures:
                error.add_note(str(failure))
            raise error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        cleanup_preserving_error(self.close, exc_value)
