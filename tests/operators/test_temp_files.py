"""Task 6.11: execution-owned temporary files and safe cleanup."""

from pathlib import Path

import pytest

from engine.errors import InvalidTypeError, ValidationError
from engine.operators import TemporaryWorkspace
from engine.operators.temp_files import WORKSPACE_PREFIX


def test_a_workspace_owns_a_unique_directory_it_created(tmp_path):
    with TemporaryWorkspace(label="sort", parent_directory=tmp_path) as workspace:
        directory = workspace.directory

        assert directory.is_dir()
        assert directory.parent == tmp_path
        assert directory.name.startswith(f"{WORKSPACE_PREFIX}sort-")
        assert workspace.closed is False

    assert not directory.exists()


def test_two_independent_workspaces_never_share_a_directory(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as first, TemporaryWorkspace(
        parent_directory=tmp_path
    ) as second:
        first_path = first.allocate("run")
        second_path = second.allocate("run")
        first_path.write_bytes(b"first")
        second_path.write_bytes(b"second")

        assert first.directory != second.directory
        assert first_path != second_path

        first.close()
        assert not first_path.exists()
        assert second_path.exists()
        assert second_path.read_bytes() == b"second"


def test_allocate_registers_a_path_without_creating_the_file(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        path = workspace.allocate("run")

        assert not path.exists()
        assert workspace.tracked_paths == (path,)
        assert workspace.statistics.files_allocated == 1


def test_a_partially_created_allocation_is_still_cleaned_up(tmp_path):
    workspace = TemporaryWorkspace(parent_directory=tmp_path)
    created = workspace.allocate("created")
    never_created = workspace.allocate("missing")
    created.write_bytes(b"payload")
    directory = workspace.directory

    workspace.close()

    assert not created.exists()
    assert not never_created.exists()
    assert not directory.exists()
    assert workspace.unreclaimed_paths == ()


def test_a_discarded_file_survives_until_its_last_reader_releases_it(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        path = workspace.allocate("run")
        path.write_bytes(b"payload")
        workspace.acquire(path)
        workspace.acquire(path)

        workspace.discard(path)
        assert path.exists()

        workspace.release(path)
        assert path.exists()

        workspace.release(path)
        assert not path.exists()
        assert workspace.tracked_paths == ()


def test_a_file_discarded_with_no_readers_disappears_at_once(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        path = workspace.allocate("run")
        path.write_bytes(b"payload")

        workspace.discard(path)

        assert not path.exists()
        assert workspace.statistics.files_deleted == 1


def test_a_file_being_discarded_refuses_a_new_reader(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        path = workspace.allocate("run")
        path.write_bytes(b"payload")
        workspace.acquire(path)
        workspace.discard(path)

        with pytest.raises(ValidationError, match="cannot accept a new reader"):
            workspace.acquire(path)

        workspace.release(path)


def test_cleanup_refuses_paths_the_workspace_did_not_allocate(tmp_path):
    sentinel = tmp_path / "base_table.heap"
    sentinel.write_bytes(b"a real table")

    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        for method in (workspace.discard, workspace.acquire, workspace.release):
            with pytest.raises(ValidationError, match="does not own"):
                method(sentinel)

        with pytest.raises(InvalidTypeError):
            workspace.discard(7)

    assert sentinel.exists()
    assert sentinel.read_bytes() == b"a real table"


def test_close_is_idempotent_and_reports_nothing_left_behind(tmp_path):
    workspace = TemporaryWorkspace(parent_directory=tmp_path)
    workspace.allocate("run").write_bytes(b"payload")

    workspace.close()
    workspace.close()

    assert workspace.closed is True
    assert workspace.unreclaimed_paths == ()


def test_an_unexpected_file_is_reported_rather_than_deleted(tmp_path):
    workspace = TemporaryWorkspace(parent_directory=tmp_path)
    tracked = workspace.allocate("run")
    tracked.write_bytes(b"payload")
    intruder = workspace.directory / "not-ours.dat"
    intruder.write_bytes(b"someone else")

    with pytest.raises(ValidationError, match="left files behind"):
        workspace.close()

    assert intruder.exists()
    assert not tracked.exists()
    assert workspace.unreclaimed_paths == (workspace.directory,)

    intruder.unlink()
    workspace.directory.rmdir()


def test_debug_retention_keeps_the_files_and_is_off_by_default(tmp_path):
    workspace = TemporaryWorkspace(parent_directory=tmp_path, retain_for_debug=True)
    path = workspace.allocate("run")
    path.write_bytes(b"payload")
    directory = workspace.directory

    workspace.close()

    assert workspace.retain_for_debug is True
    assert path.exists()
    assert directory.exists()

    assert TemporaryWorkspace(parent_directory=tmp_path).retain_for_debug is False
    path.unlink()
    directory.rmdir()


def test_a_closed_workspace_refuses_new_work(tmp_path):
    workspace = TemporaryWorkspace(parent_directory=tmp_path)
    workspace.close()

    with pytest.raises(RuntimeError, match="closed"):
        workspace.allocate("run")


def test_workspace_arguments_are_validated(tmp_path):
    with pytest.raises(ValidationError):
        TemporaryWorkspace(label=" ", parent_directory=tmp_path)
    with pytest.raises(InvalidTypeError):
        TemporaryWorkspace(retain_for_debug="yes")
    with pytest.raises(InvalidTypeError):
        TemporaryWorkspace(parent_directory=7)
    with pytest.raises(ValidationError, match="does not exist"):
        TemporaryWorkspace(parent_directory=tmp_path / "missing")

    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        with pytest.raises(ValidationError):
            workspace.allocate("  ")
        with pytest.raises(InvalidTypeError):
            workspace.allocate("run", suffix=7)
