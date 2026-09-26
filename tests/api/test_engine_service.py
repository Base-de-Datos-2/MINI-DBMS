"""Stage 9 Tasks 9.4, 9.5, 9.7 and 9.8: the engine service contract."""

import threading

import pytest

from engine.maintenance import MaintenanceError
from engine.query import SqlEngine
from api import engine_service
from api.database import Database
from api.engine_service import EngineService, ServiceError
from api.schemas import QueryRequest
from tests.api_helpers import BIG_ENROLLMENTS, names, open_service, small_demo


def run(service, sql, **options):
    return service.execute(QueryRequest(sql=sql, **options), "test-request")


def fail(service, sql, **options):
    with pytest.raises(ServiceError) as caught:
        run(service, sql, **options)
    return caught.value


# --- Task 9.4: ownership, readiness and shutdown ---------------------------

def test_health_is_cached_and_never_needs_admission(service):
    with service._admitted():
        health = service.health()

    assert health["status"] == "ready"
    assert health["mode"] == "read-only"
    assert health["writes_enabled"] is False
    assert health["tables"] == [
        "students", "enrollments", "students_big", "courses", "enrollments_big",
    ]


def test_closing_waits_for_admitted_work_then_refuses_everything(writable_directory):
    service = open_service(writable_directory)
    admitted = threading.Event()
    release = threading.Event()

    def hold():
        with service._admitted():
            admitted.set()
            release.wait()

    worker = threading.Thread(target=hold)
    worker.start()
    admitted.wait()
    closer = threading.Thread(target=service.close)
    closer.start()
    closer.join(timeout=0.2)

    assert closer.is_alive(), "close() must wait for the admitted operation"
    assert service.state == "closing"
    release.set()
    worker.join()
    closer.join()
    assert service.state == "closed"
    assert fail(service, "SELECT id FROM students").code == "ENGINE_UNAVAILABLE"
    service.close()


def test_the_service_requires_an_open_database(writable_directory):
    database = Database.open(small_demo(), writable_directory)
    database.close()

    with pytest.raises(Exception, match="open Database"):
        EngineService(database)
    with pytest.raises(TypeError, match="open Database"):
        EngineService("demo")


# --- Task 9.5: exclusive admission and statement policy --------------------

def test_statement_allowlists_fail_closed_for_future_engine_kinds(
    service, writable_directory
):
    assert service._allowed() == frozenset({"SELECT", "EXPLAIN", "EXPLAIN_ANALYZE"})

    writable = open_service(writable_directory, allow_writes=True)
    try:
        assert writable._allowed() == frozenset(
            {"SELECT", "EXPLAIN", "EXPLAIN_ANALYZE", "INSERT", "DELETE"}
        )
    finally:
        writable.close()


def test_a_competing_sessionless_operation_is_refused_immediately(service):
    admitted = threading.Event()
    release = threading.Event()

    def hold():
        with service._admitted():
            admitted.set()
            release.wait()

    worker = threading.Thread(target=hold)
    worker.start()
    admitted.wait()
    try:
        busy = fail(service, "SELECT id FROM students")
        # Metadata reads use the engine's metadata gate, not this admission.
        tables = service.list_tables()
    finally:
        release.set()
        worker.join()

    assert busy.code == "ENGINE_BUSY" and busy.status == 409
    assert [table["id"] for table in tables][0] == "students"
    # Admission is usable again once the holder finished its cleanup.
    assert run(service, "SELECT id FROM students")["total_rows"] == 4


def test_the_second_operation_never_reaches_the_engine(service, monkeypatch):
    prepared = []
    original = SqlEngine.prepare

    def counting_prepare(self, *args, **kwargs):
        prepared.append(args[0])
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SqlEngine, "prepare", counting_prepare)
    with service._admitted():
        fail(service, "SELECT name FROM students")

    assert prepared == []


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO students VALUES (9, 'Eva', 'CS', 20)",
        "DELETE FROM students WHERE id = 1",
    ],
)
def test_writes_are_refused_by_statement_kind_before_execution(service, sql):
    before = [service._database.describe_table(name).row_count
              for name in service._database.table_names()]

    error = fail(service, sql)

    assert error.code == "STATEMENT_DISABLED" and error.status == 403
    assert error.statement in {"INSERT", "DELETE"}
    assert error.execution_plan["runtime"] is None
    after = [service._database.describe_table(name).row_count
             for name in service._database.table_names()]
    assert after == before


def test_a_select_hidden_behind_leading_text_is_classified_by_the_parser(service):
    # Classification uses the parsed statement, so comments or case never
    # smuggle a write past the policy, and a SELECT is never misread.
    body = run(service, "   select name from students where id = 1")

    assert body["statement"] == "SELECT"
    assert body["rows"] == [["Ana"]]


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        # A group in the shared default session would leak across clients.
        ("BEGIN TRANSACTION", "TRANSACTION_PROTOCOL"),
        ("END TRANSACTION", "TRANSACTION_PROTOCOL"),
        ("ROLLBACK", "TRANSACTION_PROTOCOL"),
        ("COMMIT", "SQL_ERROR"),
        ("SELECT id FROM students; SELECT id FROM enrollments", "SQL_ERROR"),
        ("CREATE TABLE t (id INTEGER)", "STATEMENT_DISABLED"),
    ],
)
def test_sessionless_control_multiple_statements_and_sql_create_never_succeed(
    service, sql, code
):
    assert fail(service, sql).code == code


# --- Task 9.7: bounded preview ----------------------------------------------

def test_an_empty_result_is_complete_and_keeps_its_schema(service):
    body = run(service, "SELECT name, age FROM students WHERE age > 100")

    assert body["rows"] == []
    assert [column["name"] for column in body["columns"]] == ["name", "age"]
    assert body["result_complete"] is True
    assert body["total_rows"] == 0
    assert body["truncated"] is False


def test_fewer_rows_than_the_cap_are_complete(service):
    body = run(service, "SELECT id FROM students", max_rows=10)

    assert body["returned_rows"] == body["total_rows"] == 4
    assert body["result_complete"] is True


def test_exactly_the_cap_is_still_complete_thanks_to_one_row_of_lookahead(service):
    body = run(service, "SELECT id FROM students", max_rows=4)

    assert body["returned_rows"] == 4
    assert body["truncated"] is False
    assert body["result_complete"] is True
    assert body["total_rows"] == 4


def test_one_row_beyond_the_cap_truncates_without_claiming_a_total(service):
    body = run(service, "SELECT id FROM students", max_rows=3)

    assert body["returned_rows"] == 3
    assert body["truncated"] is True
    assert body["truncation_reason"] == "row_limit"
    assert body["result_complete"] is False
    assert body["total_rows"] is None
    assert body["metrics"]["partial"] is True


def test_the_preview_consumes_at_most_one_row_beyond_the_cap(service):
    body = run(service, "SELECT id FROM enrollments_big", max_rows=5)

    runtime_root = body["execution_plan"]["runtime"]["root"]
    assert runtime_root["rows_emitted"] == 6
    assert body["returned_rows"] == 5


def test_a_zero_row_preview_only_checks_whether_output_exists(service):
    body = run(service, "SELECT id FROM students", max_rows=0)

    assert body["rows"] == []
    assert body["truncated"] is True
    assert body["total_rows"] is None


def test_an_early_closed_preview_releases_its_temporary_files(service):
    body = run(
        service, "SELECT id FROM enrollments_big ORDER BY grade, id", max_rows=5
    )

    temporary = body["metrics"]["engine"]["temporary"]
    assert temporary["bytes_spilled"] > 0
    assert temporary["live_bytes_after"] == 0
    assert service._database.engine.active_result is None


def test_the_byte_cap_truncates_with_its_own_reason(service, monkeypatch):
    sql = "SELECT id, student_id, course_code FROM enrollments_big"
    full = run(service, sql, max_rows=500)
    rows_bytes = engine_service.encoded_size(full["rows"])
    # Leave room for the metadata and only about half of the rows.
    cap = engine_service.encoded_size(full) - rows_bytes // 2
    monkeypatch.setattr(engine_service, "MAX_RESPONSE_BYTES", cap)

    body = run(service, sql, max_rows=500)

    assert full["returned_rows"] == BIG_ENROLLMENTS
    assert body["truncated"] is True
    assert body["truncation_reason"] == "byte_limit"
    assert 0 < body["returned_rows"] < BIG_ENROLLMENTS
    assert body["rows"] == full["rows"][: body["returned_rows"]]
    assert engine_service.encoded_size(body) <= cap


def test_a_row_that_cannot_fit_is_an_error_not_an_empty_success(
    service, monkeypatch
):
    sql = "SELECT name FROM students"

    # Runtime timings make two real response envelopes differ by a few encoded
    # bytes.  Model only this boundary here: metadata fits at 100 bytes, while
    # the same envelope containing at least one row needs 110 bytes.  Other
    # tests exercise the real JSON-size implementation.
    real_encoded_size = engine_service.encoded_size

    def boundary_size(value):
        if isinstance(value, dict) and value.get("kind") == "rows":
            return 100 + (10 if value["rows"] else 0)
        return real_encoded_size(value)

    monkeypatch.setattr(engine_service, "encoded_size", boundary_size)
    monkeypatch.setattr(engine_service, "MAX_RESPONSE_BYTES", 105)

    error = fail(service, sql)

    assert error.code == "RESULT_TOO_LARGE"
    assert "Ni una sola fila" in error.message
    assert service._database.engine.active_result is None


def test_metadata_that_cannot_fit_is_an_error(service, monkeypatch):
    monkeypatch.setattr(engine_service, "MAX_RESPONSE_BYTES", 1)

    error = fail(service, "SELECT name FROM students")

    assert error.code == "RESULT_TOO_LARGE"
    assert service.state == "ready"


def test_values_keep_order_unicode_and_duplicates(service):
    body = run(
        service,
        "SELECT career FROM students ORDER BY career",
        max_rows=10,
    )

    assert body["rows"] == [["CS"], ["CS"], ["EE"], ["EE"]]


def test_a_join_keeps_both_same_named_columns_positionally(service):
    body = run(
        service,
        "SELECT s.name, b.name FROM students s JOIN students_big b ON s.id = b.id",
        max_rows=10,
    )

    assert len(body["columns"]) == 2
    assert [column["position"] for column in body["columns"]] == [0, 1]
    assert all(len(row) == 2 for row in body["rows"])
    assert body["total_rows"] == 4


# --- Task 9.8: errors and measurements --------------------------------------

def test_sql_errors_carry_the_parser_location(service):
    error = fail(service, "SELECT name\nFROM students\nWHERE")

    assert error.code == "SQL_ERROR" and error.status == 422
    assert error.location["line"] == 3


def test_semantic_errors_are_sql_errors_too(service):
    error = fail(service, "SELECT unknown_column FROM students")

    assert error.code == "SQL_ERROR"
    assert "unknown_column" in error.message
    # The engine error derives from KeyError; its message must not be quoted.
    assert not error.message.startswith('"')
    assert error.message.startswith("Unknown column")


def test_oversized_sql_is_refused_before_any_engine_work(service):
    error = fail(service, "SELECT name FROM students WHERE name = '" + "a" * 40_000 + "'")

    assert error.code == "REQUEST_TOO_LARGE" and error.status == 413


def test_measurements_come_from_this_execution_only(service):
    first = run(service, "SELECT id FROM enrollments_big ORDER BY grade, id",
                max_rows=500)
    second = run(service, "SELECT id FROM students WHERE id = 2")

    assert first["metrics"]["engine"]["temporary"]["bytes_spilled"] > 0
    assert second["metrics"]["engine"]["temporary"]["bytes_spilled"] == 0
    assert second["metrics"]["scope"].startswith("backend: parse")
    assert second["metrics"]["backend_elapsed_ms"] >= 0


def test_the_runtime_plan_is_the_tree_that_produced_the_rows(service):
    body = run(service, "SELECT name FROM students WHERE age > 20 ORDER BY name")

    prepared = body["execution_plan"]["prepared"]["root"]
    runtime = body["execution_plan"]["runtime"]["root"]
    assert names(prepared) == names(runtime)
    assert body["plan_status"] == "execution-observed"


def test_a_failure_during_conversion_releases_admission_and_the_cursor(
    service, monkeypatch
):
    calls = {"count": 0}
    original = engine_service.encode_row

    def exploding(record):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("injected conversion failure")
        return original(record)

    monkeypatch.setattr(engine_service, "encode_row", exploding)
    with pytest.raises(RuntimeError, match="injected conversion failure"):
        run(service, "SELECT id FROM students")
    monkeypatch.undo()

    assert service._database.engine.active_result is None
    assert service.state == "ready"
    assert run(service, "SELECT id FROM students")["total_rows"] == 4


def test_a_leaked_engine_session_makes_the_service_unavailable(
    writable_directory, monkeypatch
):
    service = open_service(writable_directory)
    monkeypatch.setattr(SqlEngine, "_release_result", lambda self, result: None)

    run(service, "SELECT id FROM students")

    assert service.state == "unavailable"
    assert fail(service, "SELECT id FROM students").code == "ENGINE_UNAVAILABLE"
    assert service.health()["status"] == "unavailable"
    monkeypatch.undo()
    service._database.engine._active_result = None
    service.close()


def test_real_planner_options_change_the_executed_plan(service):
    sql = "SELECT s.id FROM students s JOIN enrollments e ON s.id = e.student_id"

    grace = run(service, sql, join_strategy="GRACE_HASH")
    nested = run(service, sql, join_strategy="NESTED_LOOP")
    scanned = run(service, "SELECT id FROM students WHERE id = 3", use_indexes=False)

    assert "GraceHashJoin" in names(grace["execution_plan"]["runtime"]["root"])
    assert "NestedLoopJoin" in names(nested["execution_plan"]["runtime"]["root"])
    assert "IndexScan" not in names(scanned["execution_plan"]["runtime"]["root"])
    assert sorted(grace["rows"]) == sorted(nested["rows"])


# --- Task 9.16: optional, explicitly enabled writes ---------------------------

def test_enabled_writes_run_once_and_are_read_back(writable_directory):
    service = open_service(writable_directory, allow_writes=True)
    try:
        assert service.mode == "serialized-writes"
        inserted = run(service, "INSERT INTO students VALUES (5, 'Eva', 'ME', 21)")
        read_back = run(service, "SELECT name FROM students WHERE id = 5")
        by_scan = run(service, "SELECT name FROM students WHERE id = 5",
                      use_indexes=False)
        deleted = run(service, "DELETE FROM students WHERE id = 5")
        gone = run(service, "SELECT name FROM students WHERE id = 5")
    finally:
        service.close()

    assert inserted["kind"] == "command" and inserted["affected_rows"] == 1
    assert read_back["rows"] == by_scan["rows"] == [["Eva"]]
    assert deleted["affected_rows"] == 1
    assert gone["rows"] == []

    reopened = open_service(writable_directory)
    try:
        assert run(reopened, "SELECT id FROM students")["total_rows"] == 4
    finally:
        reopened.close()


def test_a_repeated_insert_is_executed_again_never_deduplicated(writable_directory):
    service = open_service(writable_directory, allow_writes=True)
    try:
        run(service, "INSERT INTO students VALUES (6, 'Leo', 'CS', 30)")
        duplicate = fail(service, "INSERT INTO students VALUES (6, 'Leo', 'CS', 30)")
    finally:
        service.close()

    # The second submission is processed again, never merged or retried by the
    # transport; the engine refuses the duplicate unique key while executing,
    # and its implicit transaction ends aborted before any write.
    assert duplicate.code == "EXECUTION_REFUSED"
    assert "Unique index" in duplicate.message
    assert duplicate.details["transaction"]["state"] == "ABORTED"
    assert duplicate.details["rolled_back"] is True


def test_a_failed_write_is_rolled_back_by_its_implicit_transaction(
    writable_directory, monkeypatch
):
    """Stage 8: a mutation failure restores the table and all its indexes.

    Before Stage 8 the API suspended writes when indexes were left uncertain.
    Now the implicit transaction restores the complete file set, so the
    response reports the rollback and writing stays enabled.
    """

    service = open_service(writable_directory, allow_writes=True)
    from engine.maintenance import MutationService

    original = MutationService.insert

    def failing_insert(self, **kwargs):
        original(self, **kwargs)  # the row really reaches the files first
        raise MaintenanceError(
            "injected maintenance failure",
            operation="INSERT",
            table_name="students",
            completed_rows=1,
            unavailable_indexes=("students_id_hash",),
        )

    monkeypatch.setattr(MutationService, "insert", failing_insert)
    try:
        error = fail(service, "INSERT INTO students VALUES (7, 'Ian', 'CS', 20)")
    finally:
        monkeypatch.undo()
    try:
        assert error.code == "EXECUTION_REFUSED"
        assert error.details["transaction"]["state"] == "ABORTED"
        assert error.details["rolled_back"] is True
        assert error.details["writes_suspended"] is False
        assert service.mode == "serialized-writes"
        # The row that reached the files was undone, in base and index.
        assert run(service, "SELECT id FROM students WHERE id = 7")["rows"] == []
        assert run(service, "SELECT COUNT(*) FROM students")["rows"] == [[4]]
    finally:
        service.close()
