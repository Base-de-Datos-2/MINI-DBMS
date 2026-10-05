"""Stage 9: the launcher never opens the data when its port is taken."""

import socket
import shutil
import sys

import pytest

import api.__main__ as launcher
from scripts.integration_check import Server


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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX socket reuse policy")
def test_time_wait_is_free_but_an_active_listener_is_not():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = holder.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port)) as client:
            connection, _ = holder.accept()
            connection.close()
            assert client.recv(1) == b""
        assert launcher.port_is_free("127.0.0.1", port) is False
    assert launcher.port_is_free("127.0.0.1", port) is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGINT subprocess contract")
def test_real_server_stops_and_restarts_immediately(prepared_directory, tmp_path):
    directory = tmp_path / "demo"
    shutil.copytree(prepared_directory, directory)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
    server = Server(directory, port)
    for _ in range(2):
        try:
            server.start()
            status, body = server.query("SELECT COUNT(*) FROM students;")
            assert status == 200
            assert body["rows"] == [[4]]
        finally:
            if server.process is not None and server.process.poll() is None:
                exit_code, output = server.stop()
                assert exit_code == 0
                assert "Application shutdown complete" in output
                assert "Traceback" not in output
        assert server.wait_for_port() < 1
