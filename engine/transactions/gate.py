"""Short owner-local reader/writer gate for coherent metadata publication."""

from __future__ import annotations

from contextlib import contextmanager
from threading import Condition, RLock


class MetadataGate:
    """A fair reader/writer gate used only around metadata inspection/publication.

    Logical schema S/X locks protect transaction lifetimes. This separate gate
    covers pure prepare/list calls, which intentionally do not start a
    transaction, and prevents them from observing CREATE's multi-registry
    publication half way through.
    """

    def __init__(self) -> None:
        self._condition = Condition(RLock())
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @contextmanager
    def read(self):
        with self._condition:
            while self._writer or self._waiting_writers:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                self._condition.notify_all()

    @contextmanager
    def write(self):
        with self._condition:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers:
                    self._condition.wait()
                self._writer = True
            finally:
                self._waiting_writers -= 1
        try:
            yield
        finally:
            with self._condition:
                self._writer = False
                self._condition.notify_all()


__all__ = ["MetadataGate"]
