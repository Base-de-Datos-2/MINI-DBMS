"""Stage 9: the launcher never opens the data when its port is taken."""

import socket

import pytest

import api.__main__ as launcher


def test_a_taken_port_stops_the_launcher_before_opening_any_file(
    prepared_directory, monkeypatch
):
    opened = []
    monkeypatch.setattr(
        launcher.Database, "open", lambda *args, **kwargs: opened.append(args)
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        taken = holder.getsockname()[1]

        with pytest.raises(SystemExit, match="ya está en uso"):
            launcher.main(["--data-dir", str(prepared_directory), "--port", str(taken)])

    assert opened == []


def test_a_free_port_is_reported_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        free = holder.getsockname()[1]
    assert launcher.port_is_free("127.0.0.1", free) is True


def test_a_missing_database_is_an_actionable_startup_error(tmp_path):
    with pytest.raises(SystemExit, match="setup_demo.py"):
        launcher.main(["--data-dir", str(tmp_path / "missing"), "--port", "0"])
