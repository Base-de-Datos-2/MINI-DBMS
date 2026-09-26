"""Stage 9 transaction-aware HTTP: stable sessions over the Stage 8 engine.

These tests follow the verification checklist of
``docs/ETAPA_08_STAGE_9_HANDOFF.md``. Concurrent schedules use real HTTP
requests on real threads, synchronized by polling the engine's own lock state
(never by sleeping for a guessed duration).
"""

import threading
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.database import Database
from api.demo import DEMO_MEMORY_BUDGET_BYTES, PRESETS
from api.engine_service import EngineService
from api.schemas import QueryRequest, SESSION_HEADER
from tests.api_helpers import open_service, small_demo


# ------------------------------------------------------------------ helpers


class Background:
    """Run one blocking HTTP call on its own thread and keep its outcome."""

    def __init__(self, call):
        self.response = None
        self.error = None
        self._thread = threading.Thread(target=self._run, args=(call,))
        self._thread.start()

    def _run(self, call):
        try:
            self.response = call()
        except BaseException as error:  # noqa: BLE001 - re-raised in join()
            self.error = error

    def join(self, timeout=20):
        self._thread.join(timeout)
        assert not self._thread.is_alive(), "the background request never finished"
        if self.error is not None:
            raise self.error
        return self.response


def wait_until(predicate, timeout=10.0):
    deadline = monotonic() + timeout
    pause = threading.Event()
    while monotonic() < deadline:
        if predicate():
            return
        pause.wait(0.01)
    raise AssertionError("condition not reached in time")


def open_token(client):
    response = client.post("/api/sessions")
    assert response.status_code == 201, response.json()
    return response.json()["token"]


def sql(client, token, text, **options):
    headers = {} if token is None else {SESSION_HEADER: token}
    return client.post("/api/query", json={"sql": text, **options}, headers=headers)


def status(client, token):
    return client.get("/api/session", headers={SESSION_HEADER: token})


def count(client, table):
    return sql(client, None, f"SELECT COUNT(*) AS n FROM {table}").json()["rows"][0][0]


def waiting(client, token):
    return status(client, token).json()["waiting"]


@pytest.fixture
def api(writable_directory):
    service = open_service(writable_directory, allow_writes=True)
    with TestClient(create_app(service, presets=PRESETS)) as client:
        yield client, service, writable_directory
    service.close()


def short_lock_timeout(service, seconds=0.5):
    # Test-only: the owner builds its lock manager with the 30 s default.
    service._database.session_coordinator.locks._default_timeout = seconds


# ------------------------------------------------------------------ lifecycle


def test_tokens_are_opaque_and_a_new_session_is_idle(api):
    client, _, _ = api
    body = client.post("/api/sessions").json()

    assert len(body["token"]) >= 24
    assert body["token"] != str(body["session"]["session_id"])
    assert body["session"]["state"] == "IDLE"
    assert body["session"]["busy"] is False
    assert body["session"]["transaction"] is None
    assert body["session"]["expires_in_seconds"] > 0


def test_missing_or_unknown_tokens_never_create_a_session(api):
    client, service, _ = api
    before = len(service.sessions)

    for headers in ({}, {SESSION_HEADER: "no-such-token"}):
        response = client.get("/api/session", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert sql(client, "no-such-token", "BEGIN TRANSACTION").status_code == 404
    assert len(service.sessions) == before


def test_begin_insert_end_across_separate_requests_form_one_group(api):
    client, _, _ = api
    token = open_token(client)

    begin = sql(client, token, "BEGIN TRANSACTION").json()
    group = begin["transaction_report"]["transaction_id"]
    insert = sql(client, token, "INSERT INTO enrollments VALUES (9, 'X')").json()
    end = sql(client, token, "END TRANSACTION").json()

    assert begin["kind"] == "transaction" and begin["statement"] == "BEGIN"
    assert begin["transaction_report"]["state"] == "ACTIVE"
    assert begin["session"]["transaction"] == {
        "id": group, "state": "ACTIVE", "explicit": True, "tables": [],
    }
    # Inside the group the count is provisional until END succeeds.
    assert insert["affected_rows"] == 1
    assert insert["transaction"] == {"id": group, "committed": False, "provisional": True}
    assert insert["session"]["transaction"]["tables"] == ["enrollments"]
    assert end["statement"] == "END"
    assert end["transaction_report"]["transaction_id"] == group
    assert end["transaction_report"]["state"] == "COMMITTED"
    assert end["transaction_report"]["tables_touched"] == ["enrollments"]
    assert end["transaction_report"]["undo"]["bytes_captured"] > 0
    assert end["session"]["state"] == "IDLE"
    assert count(client, "enrollments") == 5


def test_rollback_restores_every_file_and_leaves_no_artifacts(api):
    client, service, directory = api
    token = open_token(client)
    sql(client, token, "BEGIN TRANSACTION")
    assert sql(client, token, "INSERT INTO enrollments VALUES (9, 'X')").status_code == 200
    assert sql(client, token, "DELETE FROM students WHERE id = 1").json()["affected_rows"] == 1

    rollback = sql(client, token, "ROLLBACK").json()

    report = rollback["transaction_report"]
    assert report["state"] == "ABORTED"
    assert report["tables_touched"] == ["enrollments", "students"]
    assert report["undo"]["bytes_restored"] > 0
    assert count(client, "enrollments") == 4
    # The hash index was restored together with its table.
    assert sql(client, None, "SELECT name FROM students WHERE id = 1").json()["rows"] == [["Ana"]]
    service.close()
    # A fresh open refuses leftover undo images or an unclean marker.
    Database.open(small_demo(), directory).close()


# ------------------------------------------------------------------ concurrency


def test_a_blocked_request_does_not_prevent_its_blocker_from_committing(api):
    client, _, _ = api
    writer, reader, other = open_token(client), open_token(client), open_token(client)
    group = sql(client, writer, "BEGIN TRANSACTION").json()["transaction_report"]["transaction_id"]
    sql(client, writer, "INSERT INTO enrollments VALUES (9, 'X')")

    blocked = Background(lambda: sql(client, reader, "SELECT COUNT(*) AS n FROM enrollments"))
    wait_until(lambda: waiting(client, reader) is not None)
    state = status(client, reader).json()

    assert state["busy"] is True
    assert state["waiting"] == {"resource": "enrollments", "mode": "S", "blocker_ids": [group]}
    # Unrelated work is not serialized behind the blocked request...
    assert sql(client, other, "SELECT name FROM students WHERE id = 1").json()["rows"] == [["Ana"]]
    # ...and the same session refuses a second call without changing anything.
    reentrant = sql(client, reader, "SELECT id FROM students")
    assert reentrant.status_code == 409
    assert reentrant.json()["error"]["code"] == "SESSION_BUSY"

    end = sql(client, writer, "END TRANSACTION")
    assert end.json()["transaction_report"]["state"] == "COMMITTED"
    assert blocked.join().json()["rows"] == [[5]]


def test_readers_share_and_independent_table_writers_overlap(api):
    client, _, _ = api
    first, second = open_token(client), open_token(client)
    sql(client, first, "BEGIN TRANSACTION")
    sql(client, first, "SELECT COUNT(*) FROM students")
    sql(client, first, "INSERT INTO enrollments VALUES (9, 'X')")

    # S/S on students is compatible, and students is not enrollments.
    assert sql(client, second, "SELECT COUNT(*) AS n FROM students").json()["rows"] == [[4]]
    other_table = sql(client, second, "INSERT INTO courses VALUES ('ZZ9', 'Tesis', 6)")
    assert other_table.json()["transaction"]["committed"] is True

    assert sql(client, first, "END TRANSACTION").status_code == 200


def test_a_deadlock_victim_is_aborted_and_the_survivor_commits(api):
    client, _, directory = api
    left, right = open_token(client), open_token(client)
    sql(client, left, "BEGIN TRANSACTION")
    sql(client, left, "SELECT COUNT(*) FROM students")
    sql(client, right, "BEGIN TRANSACTION")
    sql(client, right, "SELECT COUNT(*) FROM enrollments")

    survivor = Background(lambda: sql(client, left, "INSERT INTO enrollments VALUES (8, 'Y')"))
    wait_until(lambda: waiting(client, left) is not None)
    victim = sql(client, right, "INSERT INTO students VALUES (8, 'Eva', 'CS', 20)")

    assert victim.status_code == 409
    error = victim.json()["error"]
    assert error["code"] == "TRANSACTION_ABORTED"
    assert error["details"]["cause"] == "deadlock"
    assert error["details"]["group_aborted"] is True
    assert error["details"]["transaction"]["state"] == "ABORTED"
    assert victim.json()["session"]["state"] == "IDLE"
    assert str(directory) not in victim.text
    assert survivor.join().json()["transaction"]["provisional"] is True
    assert sql(client, left, "END TRANSACTION").json()["transaction_report"]["state"] == "COMMITTED"
    assert count(client, "enrollments") == 5
    assert count(client, "students") == 4


def test_a_lock_timeout_aborts_the_waiting_group_only(api):
    client, service, _ = api
    short_lock_timeout(service)
    holder, waiter = open_token(client), open_token(client)
    sql(client, holder, "BEGIN TRANSACTION")
    sql(client, holder, "INSERT INTO enrollments VALUES (9, 'X')")
    sql(client, waiter, "BEGIN TRANSACTION")

    timed_out = sql(client, waiter, "SELECT COUNT(*) FROM enrollments")

    assert timed_out.status_code == 409
    assert timed_out.json()["error"]["code"] == "LOCK_TIMEOUT"
    assert timed_out.json()["error"]["details"]["group_aborted"] is True
    assert status(client, waiter).json()["state"] == "IDLE"
    assert status(client, holder).json()["state"] == "ACTIVE"
    assert sql(client, holder, "END TRANSACTION").status_code == 200


def test_cancel_ends_a_waiting_request_at_a_safe_point(api):
    client, _, _ = api
    holder, waiter = open_token(client), open_token(client)
    sql(client, holder, "BEGIN TRANSACTION")
    sql(client, holder, "INSERT INTO enrollments VALUES (9, 'X')")
    idle = client.post("/api/session/cancel", headers={SESSION_HEADER: waiter}).json()
    assert idle["cancel_requested"] is False  # nothing runs: nothing to cancel

    blocked = Background(lambda: sql(client, waiter, "SELECT COUNT(*) FROM enrollments"))
    wait_until(lambda: waiting(client, waiter) is not None)
    cancel = client.post("/api/session/cancel", headers={SESSION_HEADER: waiter})

    assert cancel.json()["cancel_requested"] is True
    response = blocked.join()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TRANSACTION_CANCELLED"
    assert response.json()["session"]["state"] == "IDLE"
    assert sql(client, holder, "END TRANSACTION").status_code == 200
    # The cancelled session is usable again.
    assert sql(client, waiter, "SELECT COUNT(*) AS n FROM enrollments").json()["rows"] == [[5]]


def test_closing_a_session_aborts_its_group_and_frees_its_locks(api):
    client, service, _ = api
    short_lock_timeout(service)
    owner = open_token(client)
    group = sql(client, owner, "BEGIN TRANSACTION").json()["transaction_report"]["transaction_id"]
    sql(client, owner, "INSERT INTO enrollments VALUES (9, 'X')")

    closed = client.delete("/api/session", headers={SESSION_HEADER: owner}).json()

    assert closed == {"closed": True, "aborted_transaction_id": group}
    # The lock is free at once: this implicit write does not time out.
    assert sql(client, None, "INSERT INTO enrollments VALUES (10, 'Z')").status_code == 200
    assert count(client, "enrollments") == 5
    assert status(client, owner).status_code == 404


# ------------------------------------------------------------------ protocol


def test_protocol_errors_keep_the_documented_state(api):
    client, _, _ = api
    token = open_token(client)

    stray_end = sql(client, token, "END TRANSACTION")
    assert stray_end.json()["error"]["code"] == "TRANSACTION_PROTOCOL"
    assert status(client, token).json()["state"] == "IDLE"

    group = sql(client, token, "BEGIN TRANSACTION").json()["transaction_report"]["transaction_id"]
    nested = sql(client, token, "BEGIN TRANSACTION")
    assert nested.json()["error"]["code"] == "TRANSACTION_PROTOCOL"
    # A protocol error neither commits nor aborts the current group.
    assert status(client, token).json()["transaction"]["id"] == group
    assert sql(client, token, "ROLLBACK").json()["transaction_report"]["state"] == "ABORTED"


def test_an_execute_error_aborts_the_whole_group(api):
    client, _, _ = api
    token = open_token(client)
    sql(client, token, "BEGIN TRANSACTION")
    sql(client, token, "INSERT INTO enrollments VALUES (9, 'X')")

    duplicate = sql(client, token, "INSERT INTO students VALUES (1, 'Dup', 'CS', 20)")

    error = duplicate.json()["error"]
    assert error["code"] == "EXECUTION_REFUSED"
    assert error["details"]["group_aborted"] is True
    assert error["details"]["transaction"]["state"] == "ABORTED"
    # The earlier successful statement was undone with the group.
    assert count(client, "enrollments") == 4
    # A later END after the automatic abort is a protocol error.
    assert sql(client, token, "END TRANSACTION").json()["error"]["code"] == "TRANSACTION_PROTOCOL"


def test_malformed_sql_aborts_an_open_group_like_the_engine(api):
    client, _, _ = api
    token = open_token(client)
    sql(client, token, "BEGIN TRANSACTION")

    broken = sql(client, token, "SELEC name FROM students")

    assert broken.json()["error"]["code"] == "SQL_ERROR"
    assert broken.json()["error"]["details"]["group_aborted"] is True
    assert status(client, token).json()["state"] == "IDLE"


def test_a_statement_refused_by_policy_never_touches_the_group(prepared_directory):
    service = open_service(prepared_directory)  # read-only mode
    try:
        with TestClient(create_app(service)) as client:
            token = open_token(client)
            sql(client, token, "BEGIN TRANSACTION")
            refused = sql(client, token, "INSERT INTO students VALUES (9, 'Eva', 'CS', 20)")
            assert refused.status_code == 403
            assert refused.json()["error"]["code"] == "STATEMENT_DISABLED"
            assert status(client, token).json()["state"] == "ACTIVE"
            assert sql(client, token, "SELECT COUNT(*) AS n FROM students").json()["rows"] == [[4]]
            assert sql(client, token, "END TRANSACTION").json()["transaction_report"][
                "state"
            ] == "COMMITTED"
    finally:
        service.close()


def test_creating_a_table_inside_an_open_group_is_refused_without_side_effects(api):
    client, _, _ = api
    token = open_token(client)
    headers = {SESSION_HEADER: token}
    definition = {"name": "notas", "columns": [{"name": "id", "type": "INTEGER"}]}
    sql(client, token, "BEGIN TRANSACTION")

    refused = client.post("/api/tables", json=definition, headers=headers)

    assert refused.json()["error"]["code"] == "TRANSACTION_PROTOCOL"
    assert status(client, token).json()["state"] == "ACTIVE"
    sql(client, token, "ROLLBACK")
    created = client.post("/api/tables", json=definition, headers=headers)
    assert created.status_code == 201
    assert created.json()["session"]["state"] == "IDLE"


# ------------------------------------------------------------------ results


def test_explain_and_explain_analyze_are_served_in_read_only_mode(client):
    plain = sql(client, None, "EXPLAIN SELECT * FROM students WHERE id = 3").json()
    analyzed = sql(client, None, "EXPLAIN ANALYZE SELECT name FROM students WHERE age > 20").json()

    assert plain["kind"] == "explanation" and plain["statement"] == "EXPLAIN"
    assert plain["explanation"]["analyzed"] is False
    assert plain["execution_plan"]["runtime"] is None
    assert plain["plan_status"] == "prepared"
    assert analyzed["statement"] == "EXPLAIN_ANALYZE"
    assert analyzed["explanation"]["analyzed"] is True
    assert analyzed["explanation"]["output_rows"] == 3
    # ANALYZE runs once and discards its rows; only the evidence comes back.
    assert analyzed["rows"] == []
    assert analyzed["execution_plan"]["runtime"]["root"]["rows_emitted"] == 3
    assert analyzed["metrics"]["engine"]["rows_produced"] == 3


def test_definition_results_have_their_own_serialization(service, tmp_path):
    from engine.database import Database as ManagedDatabase

    managed = ManagedDatabase.create(tmp_path / "managed")
    try:
        result = managed.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        body = service._dispatch(result, QueryRequest(sql="CREATE TABLE t (id INT PRIMARY KEY)"))
    finally:
        managed.close()

    assert body["kind"] == "definition"
    assert body["definition"] == {"table_name": "t", "primary_index_name": "__pk__t"}


# ------------------------------------------------------------------ bounds and expiry


def test_idle_sessions_expire_and_their_groups_are_aborted(writable_directory):
    now = [0.0]
    database = Database.open(
        small_demo(), writable_directory, memory_budget_bytes=DEMO_MEMORY_BUDGET_BYTES
    )
    service = EngineService(
        database, allow_writes=True, idle_timeout_seconds=10, clock=lambda: now[0]
    )
    try:
        with TestClient(create_app(service)) as client:
            token = open_token(client)
            sql(client, token, "BEGIN TRANSACTION")
            sql(client, token, "INSERT INTO enrollments VALUES (9, 'X')")
            now[0] = 9.0
            assert service.sessions.sweep() == 0
            now[0] = 20.0
            assert service.sessions.sweep() == 1

            assert status(client, token).json()["error"]["code"] == "SESSION_NOT_FOUND"
            assert count(client, "enrollments") == 4
    finally:
        service.close()


def test_the_session_registry_is_bounded(writable_directory):
    database = Database.open(
        small_demo(), writable_directory, memory_budget_bytes=DEMO_MEMORY_BUDGET_BYTES
    )
    service = EngineService(database, max_sessions=2)
    try:
        with TestClient(create_app(service)) as client:
            first = open_token(client)
            open_token(client)
            refused = client.post("/api/sessions")
            assert refused.status_code == 429
            assert refused.json()["error"]["code"] == "SESSION_LIMIT"
            client.delete("/api/session", headers={SESSION_HEADER: first})
            assert client.post("/api/sessions").status_code == 201
            assert client.get("/api/health").json()["sessions"]["open"] == 2
    finally:
        service.close()


def test_shutdown_cancels_waiting_work_and_closes_cleanly(api):
    client, service, directory = api
    holder, waiter = open_token(client), open_token(client)
    sql(client, holder, "BEGIN TRANSACTION")
    sql(client, holder, "INSERT INTO enrollments VALUES (9, 'X')")
    blocked = Background(lambda: sql(client, waiter, "SELECT COUNT(*) FROM enrollments"))
    wait_until(lambda: waiting(client, waiter) is not None)

    service.close()

    assert service.state == "closed"
    cancelled = blocked.join().json()["error"]
    assert cancelled["code"] == "TRANSACTION_CANCELLED"
    assert cancelled["details"]["cause"] == "shutdown"
    assert client.post("/api/sessions").json()["error"]["code"] == "ENGINE_UNAVAILABLE"
    # The open group was aborted and no undo artifact blocks a fresh open.
    reopened = Database.open(small_demo(), directory)
    try:
        assert reopened.describe_table("enrollments").row_count == 4
    finally:
        reopened.close()
