"""Scoped guards that do not interfere with pytest/import file handling."""

import builtins
from contextlib import contextmanager
import io
import os

import pytest


@pytest.fixture
def no_file_io(monkeypatch):
    @contextmanager
    def guard():
        def forbidden(*args, **kwargs):
            pytest.fail("Stage 1 model/contract operations must not access files")

        with monkeypatch.context() as patch:
            patch.setattr(builtins, "open", forbidden)
            patch.setattr(io, "open", forbidden)
            patch.setattr(os, "open", forbidden)
            yield

    return guard
