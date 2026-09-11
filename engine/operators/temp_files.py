"""Execution-owned temporary files, isolated from base tables and indexes."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile

from engine.errors import InvalidTypeError, ValidationError


#: Prefix of every execution directory, so a stray directory is identifiable.
WORKSPACE_PREFIX = "minidb-exec-"


@dataclass(slots=True)
class _TrackedFile:
    """One temporary path this workspace created and is responsible for."""

    path: Path
    readers: int = 0
    discard_requested: bool = False


@dataclass(slots=True)
class WorkspaceStatistics:
    """Measured temporary-file activity of one workspace."""

    files_allocated: int = 0
    files_deleted: int = 0
    readers_opened: int = 0
    peak_tracked_files: int = 0


class TemporaryWorkspace:
    """A unique directory of files created and destroyed by one execution.

    Every path handed out is registered, and cleanup touches only registered
    paths plus the directory this workspace created itself. The directory is
    removed with ``rmdir``, never a recursive delete: anything unexpected
    inside it makes cleanup report an unreclaimed path instead of silently
    destroying a file nobody accounted for.

    A run or partition stays alive while readers hold it. ``discard`` marks it
    for deletion, and the file disappears once the last reader releases it, so
    a consumer can never read a path that was pulled out from under it.

    There is no startup sweep of a shared directory: a workspace only ever
    deletes what it allocated during its own lifetime.
    """

    __slots__ = ("_directory", "_files", "_closed", "_retain", "_statistics",
                 "_unreclaimed")

    def __init__(
        self,
        *,
        label: str = "query",
        parent_directory: object = None,
        retain_for_debug: bool = False,
    ) -> None:
        if not isinstance(label, str) or not label.strip():
            raise ValidationError("Workspace label must be a non-empty string")
        if type(retain_for_debug) is not bool:
            raise InvalidTypeError("retain_for_debug must be a bool")
        if parent_directory is not None:
            if not isinstance(parent_directory, (str, os.PathLike)):
                raise InvalidTypeError("parent_directory must be a path")
            parent = Path(parent_directory)
            if not parent.is_dir():
                raise ValidationError(
                    f"Workspace parent directory does not exist: {parent}"
                )
        else:
            parent = None
        self._directory = Path(
            tempfile.mkdtemp(prefix=f"{WORKSPACE_PREFIX}{label}-", dir=parent)
        )
        self._files: dict[Path, _TrackedFile] = {}
        self._closed = False
        self._retain = retain_for_debug
        self._statistics = WorkspaceStatistics()
        self._unreclaimed: tuple[Path, ...] = ()

    @property
    def directory(self) -> Path:
        """Return the directory this workspace owns exclusively."""

        return self._directory

    @property
    def closed(self) -> bool:
        """Report whether this workspace has been closed."""

        return self._closed

    @property
    def retain_for_debug(self) -> bool:
        """Report whether cleanup deliberately keeps the files on disk."""

        return self._retain

    @property
    def statistics(self) -> WorkspaceStatistics:
        """Return the measured temporary-file counters."""

        return self._statistics

    @property
    def tracked_paths(self) -> tuple[Path, ...]:
        """Return the paths currently registered to this workspace."""

        return tuple(self._files)

    @property
    def unreclaimed_paths(self) -> tuple[Path, ...]:
        """Return the exact paths a previous cleanup could not remove."""

        return self._unreclaimed

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("The temporary workspace is closed")

    def _tracked(self, path: object) -> _TrackedFile:
        if not isinstance(path, (str, os.PathLike)):
            raise InvalidTypeError("path must be a path")
        resolved = Path(path)
        tracked = self._files.get(resolved)
        if tracked is None:
            raise ValidationError(
                f"This workspace does not own {resolved}; cleanup refuses paths "
                "it did not allocate"
            )
        return tracked

    def allocate(self, label: str = "run", suffix: str = ".tmp") -> Path:
        """Register and return a fresh path inside this workspace.

        The file is not created here: the caller creates it through the page
        layer, so an allocation that never materializes still gets cleaned up
        and never leaves an untracked file behind.
        """

        self._require_open()
        if not isinstance(label, str) or not label.strip():
            raise ValidationError("Temporary file label must be a non-empty string")
        if not isinstance(suffix, str):
            raise InvalidTypeError("Temporary file suffix must be a string")
        ordinal = self._statistics.files_allocated
        path = self._directory / f"{label}-{ordinal:06d}{suffix}"
        if path in self._files:
            raise ValidationError(f"Temporary path already allocated: {path}")
        self._files[path] = _TrackedFile(path)
        self._statistics.files_allocated += 1
        if len(self._files) > self._statistics.peak_tracked_files:
            self._statistics.peak_tracked_files = len(self._files)
        return path

    def acquire(self, path: object) -> Path:
        """Record that one more consumer is reading this temporary file."""

        self._require_open()
        tracked = self._tracked(path)
        if tracked.discard_requested:
            raise ValidationError(
                f"Temporary file {tracked.path} is being discarded and cannot "
                "accept a new reader"
            )
        tracked.readers += 1
        self._statistics.readers_opened += 1
        return tracked.path

    def release(self, path: object) -> None:
        """Record that one consumer finished; delete if discard is pending."""

        tracked = self._tracked(path)
        if tracked.readers > 0:
            tracked.readers -= 1
        if tracked.discard_requested and tracked.readers == 0:
            self._delete(tracked)

    def discard(self, path: object) -> None:
        """Delete a temporary file now, or as soon as its readers release it."""

        tracked = self._tracked(path)
        tracked.discard_requested = True
        if tracked.readers == 0:
            self._delete(tracked)

    def _delete(self, tracked: _TrackedFile) -> None:
        if self._retain:
            self._files.pop(tracked.path, None)
            return
        try:
            tracked.path.unlink()
        except FileNotFoundError:
            # An allocated path whose file was never created is already clean.
            pass
        else:
            self._statistics.files_deleted += 1
        self._files.pop(tracked.path, None)

    def close(self) -> None:
        """Remove every tracked file and this workspace's own directory.

        Cleanup attempts all paths even when one fails, then reports the exact
        paths it could not reclaim. When this runs while another exception is
        propagating, that original error stays the active exception and this
        failure is chained to it.
        """

        if self._closed:
            return
        self._closed = True
        if self._retain:
            self._files.clear()
            return
        unreclaimed: list[Path] = []
        for tracked in list(self._files.values()):
            try:
                self._delete(tracked)
            except OSError:
                unreclaimed.append(tracked.path)
        self._files.clear()
        try:
            self._directory.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            unreclaimed.append(self._directory)
        self._unreclaimed = tuple(unreclaimed)
        if unreclaimed:
            listed = ", ".join(str(path) for path in unreclaimed)
            raise ValidationError(f"Temporary cleanup left files behind: {listed}")

    def __enter__(self) -> "TemporaryWorkspace":
        """Return this workspace for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Clean up on every exit path, including exceptions."""

        self.close()
