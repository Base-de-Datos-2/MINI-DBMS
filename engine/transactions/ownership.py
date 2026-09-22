"""Reject duplicate in-process owners of one physical database directory."""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from .errors import TransactionUnavailableError


_mutex = Lock()
_claimed: set[Path] = set()


class DirectoryLease:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._released = False

    def release(self) -> None:
        with _mutex:
            if not self._released:
                _claimed.discard(self.path)
                self._released = True


def claim_directory(path: Path) -> DirectoryLease:
    resolved = Path(path).resolve()
    with _mutex:
        if resolved in _claimed:
            raise TransactionUnavailableError(
                f"A database owner already holds {resolved} in this process"
            )
        _claimed.add(resolved)
    return DirectoryLease(resolved)
