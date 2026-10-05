"""Stage 10 Task 10.12: full-path integration check against a real server.

It prepares a fresh demo database in its own directory, starts ``python -m
api`` as a separate process (the way it is deployed) and drives it only over
HTTP: the compiled frontend, the demo presets, SQL errors and recovery, table
creation from CSV on both organizations with every index type, two client
sessions competing for a lock, commit and rollback, and finally a clean
restart that must preserve exactly the committed state.

Run from the repository root (the frontend must be built first)::

    python scripts/integration_check.py

It prints one line per check and exits with status 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any
from urllib import error, request

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from api.__main__ import port_is_free  # noqa: E402
from benchmarks.datasets import generate  # noqa: E402


class Server:
    """One ``python -m api`` process owning ``data_dir``."""

    def __init__(self, data_dir: Path, port: int, launch_options: tuple[str, ...] = ()) -> None:
        self.data_dir, self.port = data_dir, port
        self.launch_options = launch_options
        self.base = f"http://127.0.0.1:{port}"
        self.process: subprocess.Popen | None = None

    def wait_for_port(self) -> float:
        """Seconds until the launcher's own port probe accepts the port again."""

        started = time.perf_counter()
        while not port_is_free("127.0.0.1", self.port):
            if time.perf_counter() - started > 180:
                raise RuntimeError(f"port {self.port} stayed busy")
            time.sleep(1)
        return time.perf_counter() - started

    def start(self) -> float:
        started = time.perf_counter()
        self.process = subprocess.Popen(
            [sys.executable, "-m", "api", "--allow-writes", "--data-dir", str(self.data_dir),
             "--port", str(self.port), *self.launch_options],
            cwd=REPOSITORY, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("server exited during startup:\n" + self.process.stdout.read())
            try:
                if self.get("/api/health")["status"] == "ready":
                    return time.perf_counter() - started
            except (error.URLError, ConnectionError):
                time.sleep(0.2)
        raise RuntimeError("server did not become ready")

    def stop(self) -> tuple[int, str]:
        """Stop like Ctrl+C; return the exit status and the server output."""

        assert self.process is not None
        self.process.send_signal(signal.SIGINT)
        output, _ = self.process.communicate(timeout=30)
        return self.process.returncode, output

    def _call(self, method: str, path: str, body: Any = None, token: str | None = None):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Session-Token"] = token
        req = request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with request.urlopen(req, timeout=60) as response:
                raw = response.read()
                kind = response.headers.get("Content-Type", "")
                return response.status, (json.loads(raw) if "json" in kind else raw.decode())
        except error.HTTPError as failure:
            return failure.code, json.loads(failure.read())

    def get(self, path: str, token: str | None = None):
        status, body = self._call("GET", path, token=token)
        if status != 200:
            raise RuntimeError(f"GET {path} -> {status}: {body}")
        return body

    def raw(self, path: str):
        return self._call("GET", path)

    def query(self, sql: str, token: str | None = None, **options):
        return self._call("POST", "/api/query", {"sql": sql, **options}, token)

    def post(self, path: str, body: Any = None, token: str | None = None):
        return self._call("POST", path, body, token)


class Checks:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        self.results.append({"check": name, "ok": bool(condition), "detail": detail})
        print(f"[{'OK ' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
              flush=True)
        return bool(condition)

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [item for item in self.results if not item["ok"]]


def stopped(checks: Checks, name: str, exit_code: int, output: str) -> None:
    """Graceful stop: shutdown completed and no traceback other than Ctrl+C."""

    graceful = "Application shutdown complete" in output
    checks.check(name, graceful, f"shutdown complete: {graceful}; exit {exit_code}")
    checks.check(f"{name}: exit status 0 without traceback",
                 exit_code == 0 and "Traceback" not in output, f"exit {exit_code}")


def plan_text(body: dict[str, Any]) -> str:
    return json.dumps(body.get("execution_plan"), ensure_ascii=False)


def rows(body: dict[str, Any]) -> list:
    return body.get("rows", [])


def run(data_dir: Path, port: int, report: Path | None, *, include_frontend: bool = True) -> int:
    checks = Checks()
    if data_dir.exists():
        if not (data_dir / ".minidbms-demo").exists():
            sys.exit(f"{data_dir} exists and is not a demo directory; refusing to delete it")
        shutil.rmtree(data_dir)
    subprocess.run([sys.executable, "scripts/setup_demo.py", "--data-dir", str(data_dir)],
                   cwd=REPOSITORY, check=True, capture_output=True)
    server = Server(data_dir, port)
    seconds = server.start()
    checks.check("server starts on a fresh demo database", True, f"{seconds:.1f} s")
    try:
        # ------------------------------------------------ frontend and API
        health = server.get("/api/health")
        checks.check("health reports ready with writes enabled",
                     health["status"] == "ready" and health["writes_enabled"], health["mode"])
        if include_frontend:
            status, page = server.raw("/")
            assets = [part.split('"')[0] for part in page.split('src="')[1:]] if status == 200 else []
            asset_status = server.raw(assets[0])[0] if assets else None
            checks.check("compiled frontend is served with its assets",
                         status == 200 and "<div id=\"root\"" in page and asset_status == 200,
                         f"index {status}, {assets[:1]} {asset_status}")
        tables = {table["name"] for table in server.get("/api/tables")}
        checks.check("catalog lists the demo tables",
                     {"students", "enrollments", "students_big"} <= tables, ", ".join(sorted(tables)))

        # ---------------------------------------------- presets and plans
        status, body = server.query("SELECT * FROM students WHERE id = 3;")
        checks.check("equality uses the hash index",
                     rows(body) == [[3, "Sol", "CS", 24]] and "IndexScan" in plan_text(body)
                     and "students_id_hash" in plan_text(body), str(rows(body)))
        status, body = server.query("SELECT * FROM students WHERE id = 3;", use_indexes=False)
        checks.check("disabling indexes changes the real plan, not the answer",
                     rows(body) == [[3, "Sol", "CS", 24]] and "TableScan" in plan_text(body)
                     and "IndexScan" not in plan_text(body))
        status, body = server.query(
            "SELECT s.career, COUNT(*) AS inscripciones, AVG(e.grade) AS promedio "
            "FROM students_big s JOIN enrollments_big e ON s.id = e.student_id "
            "GROUP BY s.career ORDER BY s.career;")
        text = plan_text(body)
        checks.check("join, group and sort run the external operators",
                     status == 200 and all(name in text for name in
                                           ("GraceHashJoin", "ExternalHashGroup", "ExternalSort")),
                     f"{len(rows(body))} groups")

        # -------------------------------------------- errors and recovery
        status, body = server.query("SELEC name FROM students;")
        syntax = status >= 400 and "error" in body
        status, body = server.query("SELECT unknown_column FROM students;")
        semantic = status >= 400 and "error" in body
        status, body = server.query("SELECT name FROM students WHERE age > 20 ORDER BY name;")
        checks.check("syntax and semantic errors are reported and the server recovers",
                     syntax and semantic and rows(body) == [["Ana"], ["Omar"], ["Sol"]],
                     str(rows(body)))

        # ---------------------------------------- tables created from CSV
        data = generate(500)
        csv_text = "id,name,career,age,score\n" + "\n".join(",".join(map(str, row)) for row in data)
        columns = [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "VARCHAR"},
                   {"name": "career", "type": "VARCHAR"}, {"name": "age", "type": "INTEGER"},
                   {"name": "score", "type": "INTEGER"}]
        created = {}
        for name, organization, key, indexes in (
            ("it_heap", "HEAP", None, [{"column": "id", "type": "BPLUS", "unique": True},
                                       {"column": "career", "type": "EXTENDIBLE_HASH"}]),
            ("it_seq", "SEQUENTIAL", "id", [{"column": "id", "type": "BPLUS", "unique": True}]),
        ):
            status, body = server.post("/api/tables", {
                "name": name, "organization": organization, "key_column": key,
                "columns": columns, "indexes": indexes,
                "csv": {"text": csv_text, "filename": f"{name}.csv"},
            })
            created[name] = body
            checks.check(f"CSV import creates {organization} table {name}",
                         status == 201 and body.get("loaded_rows") == 500,
                         f"status {status}, rows {body.get('loaded_rows')}")
        key = data[123][0]
        expected = [list(data[123])]
        for name in created:
            status, body = server.query(f"SELECT * FROM {name} WHERE id = {key};")
            checks.check(f"{name}: equality on the imported table uses its B+ index",
                         rows(body) == expected and "IndexScan" in plan_text(body), str(rows(body)))
        status, body = server.query("SELECT COUNT(*) AS n FROM it_heap WHERE career = 'CS';")
        cs = sum(1 for row in data if row[2] == "CS")
        checks.check("it_heap: equality on a hash-indexed column",
                     rows(body) == [[cs]] and "IndexScan" in plan_text(body), str(rows(body)))
        status, body = server.query("SELECT id FROM it_seq WHERE id >= 10 AND id <= 14 ORDER BY id;")
        checks.check("it_seq: ordered range on the sequential table",
                     rows(body) == [[10], [11], [12], [13], [14]], str(rows(body)))

        # --------------------------------- sessions, locks and transactions
        status, a = server.post("/api/sessions")
        status, b = server.post("/api/sessions")
        token_a, token_b = a["token"], b["token"]
        server.query("BEGIN TRANSACTION;", token_a)
        status, body = server.query("INSERT INTO enrollments VALUES (9, 'X');", token_a)
        inserted = status == 200
        waiting: dict[str, Any] = {}

        def reader() -> None:
            waiting["started"] = time.perf_counter()
            waiting["response"] = server.query("SELECT COUNT(*) AS n FROM enrollments;", token_b)
            waiting["finished"] = time.perf_counter()

        thread = threading.Thread(target=reader)
        thread.start()
        time.sleep(1.5)
        blocked = thread.is_alive()
        lock_view = server.get("/api/session", token_b)
        status, body = server.query("END TRANSACTION;", token_a)
        committed = status == 200
        thread.join(timeout=30)
        count_after = rows(waiting.get("response", (0, {}))[1])
        checks.check("a second session waits for the writer's lock until END",
                     inserted and blocked and committed and count_after == [[5]],
                     f"blocked {blocked}, waited {waiting.get('finished', 0) - waiting.get('started', 0):.1f} s, "
                     f"count {count_after}, session view: {json.dumps(lock_view, ensure_ascii=False)[:160]}")
        server.query("BEGIN TRANSACTION;", token_a)
        server.query("INSERT INTO enrollments VALUES (10, 'Y');", token_a)
        status, body = server.query("ROLLBACK;", token_a)
        status, body = server.query("SELECT COUNT(*) AS n FROM enrollments;", token_b)
        checks.check("ROLLBACK discards the provisional insert", rows(body) == [[5]], str(rows(body)))
    finally:
        exit_code, output = server.stop()
    stopped(checks, "server stops cleanly (Ctrl+C)", exit_code, output)

    # ------------------------------------------------------------ restart
    waited = server.wait_for_port()
    checks.check("port free for the launcher right after the stop", waited < 1,
                 f"waited {waited:.0f} s (TCP TIME_WAIT after client connections)")
    seconds = server.start()
    try:
        tables = {table["name"]: table for table in server.get("/api/tables")}
        checks.check("restart reopens the same files", True, f"{seconds:.1f} s")
        checks.check("created tables and their indexes survive the restart",
                     {"it_heap", "it_seq"} <= set(tables)
                     and tables["it_heap"]["row_count"] == 500
                     and tables["it_heap"]["index_count"] == 2
                     and tables["it_seq"]["index_count"] == 1,
                     ", ".join(f"{name}={tables[name]['row_count']}" for name in ("it_heap", "it_seq") if name in tables))
        status, body = server.query("SELECT COUNT(*) AS n FROM enrollments;")
        status2, body2 = server.query("SELECT course FROM enrollments WHERE student_id = 9;")
        status3, body3 = server.query("SELECT course FROM enrollments WHERE student_id = 10;")
        checks.check("only the committed insert is durable",
                     rows(body) == [[5]] and rows(body2) == [["X"]] and rows(body3) == [],
                     f"count {rows(body)}, committed {rows(body2)}, rolled back {rows(body3)}")
        status, body = server.query(f"SELECT name FROM it_seq WHERE id = {key};")
        checks.check("indexed lookups work after the restart",
                     rows(body) == [[data[123][1]]] and "IndexScan" in plan_text(body))
    finally:
        exit_code, output = server.stop()
    stopped(checks, "server stops cleanly after the restart", exit_code, output)

    print(f"\n{len(checks.results) - len(checks.failed)}/{len(checks.results)} checks passed")
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(checks.results, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return 1 if checks.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path,
                        default=REPOSITORY / "data" / "generated" / "integration-check")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--report", type=Path, default=None,
                        help="optional JSON file with every check and its detail")
    parser.add_argument("--backend-only", action="store_true",
                        help="validate HTTP and persistence without compiled frontend assets")
    args = parser.parse_args()
    return run(args.data_dir, args.port, args.report, include_frontend=not args.backend_only)


if __name__ == "__main__":
    sys.exit(main())
