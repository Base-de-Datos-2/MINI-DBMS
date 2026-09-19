"""Stage 9 Task 9.3: the offline setup script only resets its own directory."""

import importlib.util
from pathlib import Path

import pytest

from api.demo import DEMO_MARKER
from tests.api_helpers import small_demo


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "setup_demo.py"


def load_script():
    spec = importlib.util.spec_from_file_location("setup_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_creates_the_files_and_its_marker(tmp_path):
    target = tmp_path / "demo"

    load_script().prepare(target, reset=False, definition=small_demo())

    assert (target / DEMO_MARKER).is_file()
    assert (target / "students.heap").is_file()


def test_setup_refuses_an_existing_directory_without_reset(tmp_path):
    script = load_script()
    target = tmp_path / "demo"
    script.prepare(target, reset=False, definition=small_demo())

    with pytest.raises(SystemExit, match="--reset"):
        script.prepare(target, reset=False, definition=small_demo())


def test_reset_never_deletes_a_directory_it_did_not_create(tmp_path):
    foreign = tmp_path / "project-data"
    foreign.mkdir()
    (foreign / "important.heap").write_bytes(b"real data")

    with pytest.raises(SystemExit, match="marcador"):
        load_script().prepare(foreign, reset=True, definition=small_demo())

    assert (foreign / "important.heap").read_bytes() == b"real data"


def test_reset_recreates_a_demo_directory(tmp_path):
    script = load_script()
    target = tmp_path / "demo"
    script.prepare(target, reset=False, definition=small_demo())
    (target / "students.heap").write_bytes(b"corrupted")

    script.prepare(target, reset=True, definition=small_demo())

    assert (target / "students.heap").read_bytes() != b"corrupted"
    assert (target / DEMO_MARKER).is_file()
