"""Tasks 7.26-7.30: public SQL acceptance and differential evidence."""

from collections import Counter

import pytest

from engine.catalog import (
    Catalog,
    Column,
    DataType,
    IndexMetadata,
    IndexType,
    Schema,
    TableMetadata,
)
from engine.errors import ValidationError
from engine.indexes.index_catalog import build_catalog_index, open_catalog_index
from engine.query import (
    JoinPlanningStrategy,
    PhysicalPlanningOptions,
    QueryEnvironment,
    SqlEngine,
    run_sql,
)
from engine.storage import HeapFile, PagedSequentialFile, Record


STUDENTS = Schema(
    [
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
        Column("career", DataType.VARCHAR),
        Column("age", DataType.INTEGER),
    ]
)

ENROLLMENTS = Schema(
    [
        Column("student_id", DataType.INTEGER),
        Column("course", DataType.VARCHAR),
    ]
)

STUDENT_ROWS = (
    (1, "Ana", "CS", 22),
    (2, "Luis", "EE", 19),
    (3, "Sol", "CS", 24),
    (4, "Omar", "EE", 23),
)

ENROLLMENT_ROWS = (
    (1, "DB2"),
    (1, "OS"),
    (3, "DB2"),
    (4, "OS"),
)


def _values(result):
    return tuple(record.values for record in result.rows)


def _node(descriptor, name):
    return next(node for node in descriptor.walk() if node.name == name)


@pytest.fixture
def acceptance_environment(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    catalog.register_table(TableMetadata("enrollments", ENROLLMENTS))
    catalog.register_index(
        IndexMetadata(
            "students_id_hash",
            "students",
            "id",
            IndexType.EXTENDIBLE_HASH,
            unique=True,
            file_path=str(tmp_path / "students_id.hash"),
        )
    )
    catalog.register_index(
        IndexMetadata(
            "students_age_bplus",
            "students",
            "age",
            IndexType.BPLUS,
            file_path=str(tmp_path / "students_age.bplus"),
        )
    )
    environment = QueryEnvironment(catalog)
    students_path = tmp_path / "students.heap"
    enrollments_path = tmp_path / "enrollments.heap"
    students = HeapFile.create(students_path, STUDENTS)
    enrollments = HeapFile.create(enrollments_path, ENROLLMENTS)
    environment.register_storage("students", students)
    environment.register_storage("enrollments", enrollments)
    for row in STUDENT_ROWS:
        students.insert(Record(STUDENTS, row))
    for row in ENROLLMENT_ROWS:
        enrollments.insert(Record(ENROLLMENTS, row))
    indexes = tuple(
        build_catalog_index(catalog, metadata.name, students)
        for metadata in catalog.get_indexes("students")
    )
    for metadata, index in zip(catalog.get_indexes("students"), indexes):
        environment.register_index(metadata.name, index)
    try:
        yield (
            environment,
            catalog,
            students,
            enrollments,
            indexes,
            students_path,
        )
    finally:
        for index in reversed(indexes):
            if not index.closed:
                index.close()
        if not enrollments.closed:
            enrollments.close()
        if not students.closed:
            students.close()


def test_reproducible_selection_matrix_and_truthful_access_reports(
    acceptance_environment,
):
    environment, _, students, _, _, _ = acceptance_environment
    engine = SqlEngine(environment)
    before = tuple(record.values for _, record in students.scan())

    basic = engine.execute(
        "SELECT name, career FROM students WHERE age > 20 ORDER BY name"
    )
    assert [(column.name, column.data_type) for column in basic.schema] == [
        ("name", DataType.VARCHAR),
        ("career", DataType.VARCHAR),
    ]
    assert _values(basic) == (
        ("Ana", "CS"),
        ("Omar", "EE"),
        ("Sol", "CS"),
    )
    assert "ExternalSort" in [node.name for node in basic.report.runtime.operators]

    equality = engine.prepare("SELECT * FROM students WHERE id = 3")
    prepared_scan = _node(equality.describe(), "IndexScan")
    assert dict(prepared_scan.details) == {
        "relation": "students",
        "table": "students",
        "storage": "HeapFile",
        "index": "students_id_hash",
        "access": "equality 3",
    }
    equality_result = equality.execute()
    assert _values(equality_result) == ((3, "Sol", "CS", 24),)
    runtime_scan = next(
        node
        for node in equality_result.report.runtime.operators
        if node.name == "IndexScan"
    )
    assert dict(runtime_scan.details)["index_name"] == "students_id_hash"
    assert dict(runtime_scan.details)["access"] == "hash equality"

    bplus_equality = engine.execute(
        "SELECT name FROM students WHERE age = 23"
    )
    assert _values(bplus_equality) == (("Omar",),)
    bplus_node = next(
        node for node in bplus_equality.report.runtime.operators
        if node.name == "IndexScan"
    )
    assert dict(bplus_node.details)["access"] == "b+ equality"

    ranged = engine.execute(
        "SELECT name FROM students "
        "WHERE age >= 22 AND age < 24 AND career = 'EE'"
    )
    assert _values(ranged) == (("Omar",),)
    range_nodes = ranged.report.runtime.operators
    assert dict(next(node for node in range_nodes if node.name == "IndexScan").details)[
        "access"
    ] == "b+ range"
    assert any(node.name == "Filter" for node in range_nodes)

    fallback = engine.prepare(
        "SELECT id FROM students "
        "WHERE id = 1 OR career = 'EE' ORDER BY id"
    )
    assert "IndexScan" not in [node.name for node in fallback.describe().walk()]
    fallback_result = fallback.execute()
    assert _values(fallback_result) == ((1,), (2,), (4,))
    assert "TableScan" in [
        node.name for node in fallback_result.report.runtime.operators
    ]
    assert tuple(record.values for _, record in students.scan()) == before


def test_group_join_hidden_order_and_runtime_strategy_reports(
    acceptance_environment,
):
    environment, _, _, _, _, _ = acceptance_environment
    engine = SqlEngine(environment)

    hidden = engine.execute("SELECT name FROM students ORDER BY age")
    assert [column.name for column in hidden.schema] == ["name"]
    assert _values(hidden) == (("Luis",), ("Ana",), ("Omar",), ("Sol",))

    grouped = engine.execute(
        "SELECT career, COUNT(*) AS total FROM students "
        "GROUP BY career ORDER BY career"
    )
    assert [column.name for column in grouped.schema] == ["career", "total"]
    assert _values(grouped) == (("CS", 2), ("EE", 2))
    group_node = next(
        node for node in grouped.report.runtime.operators
        if node.name == "ExternalHashGroup"
    )
    assert dict(group_node.details)["strategy"] == "hash partitions"

    joined = engine.execute(
        "SELECT s.name, e.course FROM students AS s "
        "JOIN enrollments AS e ON s.id = e.student_id "
        "WHERE s.age > 20 ORDER BY s.name"
    )
    assert [column.name for column in joined.schema] == ["name", "course"]
    assert _values(joined) == (
        ("Ana", "DB2"),
        ("Ana", "OS"),
        ("Omar", "OS"),
        ("Sol", "DB2"),
    )
    join_node = next(
        node for node in joined.report.runtime.operators
        if node.name == "GraceHashJoin"
    )
    assert dict(join_node.details)["strategy"].startswith("grace hash join")
    assert joined.report.runtime.temporary_pages_written > 0


def test_mutations_report_real_work_and_survive_fresh_manager_reopen(
    acceptance_environment,
):
    environment, catalog, students, enrollments, indexes, students_path = (
        acceptance_environment
    )
    engine = SqlEngine(environment)

    prepared_insert = engine.prepare(
        "INSERT INTO students VALUES (5, 'Eva', 'CS', 21)"
    )
    insert_details = dict(prepared_insert.describe().details)
    assert students.record_count == 4
    assert insert_details["storage"] == "HeapFile"
    assert set(insert_details["indexes"].split(", ")) == {
        "students_id_hash",
        "students_age_bplus",
    }
    inserted = prepared_insert.execute()
    assert inserted.affected_rows == 1
    assert inserted.statistics.index_association_updates == 2

    deleted = engine.execute("DELETE FROM students WHERE age < 21")
    assert deleted.affected_rows == 1
    assert deleted.statistics.targets_spooled == 1
    assert deleted.statistics.discovery is not None
    assert [
        node.name for node in deleted.statistics.discovery.operators
    ] == ["Filter", "TableScan"]
    assert _values(engine.execute("SELECT id, name FROM students ORDER BY id")) == (
        (1, "Ana"),
        (3, "Sol"),
        (4, "Omar"),
        (5, "Eva"),
    )

    for index in reversed(indexes):
        index.close()
    students.close()

    reopened_environment = QueryEnvironment(catalog)
    reopened_students = HeapFile.open(students_path, STUDENTS)
    reopened_environment.register_storage("students", reopened_students)
    reopened_indexes = tuple(
        open_catalog_index(catalog, metadata.name, reopened_students)
        for metadata in catalog.get_indexes("students")
    )
    for metadata, index in zip(
        catalog.get_indexes("students"), reopened_indexes
    ):
        reopened_environment.register_index(metadata.name, index)
    try:
        reopened_engine = SqlEngine(reopened_environment)
        assert _values(
            reopened_engine.execute("SELECT name FROM students WHERE id = 5")
        ) == (("Eva",),)
        assert _values(
            reopened_engine.execute("SELECT name FROM students WHERE age < 21")
        ) == ()
        assert tuple(record["id"] for _, record in reopened_students.scan()) == (
            1,
            3,
            4,
            5,
        )
        for index in reopened_indexes:
            index.validate_structure()
    finally:
        for index in reversed(reopened_indexes):
            index.close()
        reopened_students.close()
    assert enrollments.closed is False


def test_clustered_bplus_is_a_real_sql_access_variant(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    metadata = IndexMetadata(
        "students_id_clustered",
        "students",
        "id",
        IndexType.BPLUS,
        unique=True,
        clustered=True,
        file_path=str(tmp_path / "students_id_clustered.bplus"),
    )
    catalog.register_index(metadata)
    environment = QueryEnvironment(catalog)
    storage = PagedSequentialFile.create(
        tmp_path / "students.seq",
        STUDENTS,
        "id",
        allow_duplicate_keys=False,
    )
    environment.register_storage("students", storage)
    index = None
    try:
        for row in reversed(STUDENT_ROWS):
            storage.insert(Record(STUDENTS, row))
        index = build_catalog_index(catalog, metadata.name, storage)
        environment.register_index(metadata.name, index)
        result = run_sql(environment, "SELECT name FROM students WHERE id >= 3")
        assert Counter(_values(result)) == Counter({("Sol",): 1, ("Omar",): 1})
        scan = next(
            node for node in result.report.runtime.operators
            if node.name == "IndexScan"
        )
        assert dict(scan.details)["index"] == "ClusteredBPlusIndex"
        assert dict(scan.details)["storage"] == "PagedSequentialFile"
        assert dict(scan.details)["access"] == "b+ range"
    finally:
        if index is not None:
            index.close()
        storage.close()


def test_public_optimized_routes_match_scan_and_join_baselines(
    acceptance_environment,
):
    environment, _, _, _, _, _ = acceptance_environment
    for sql in (
        "SELECT name FROM students WHERE id = 3",
        "SELECT id, name FROM students WHERE age >= 22 AND age < 24",
        "SELECT id FROM students WHERE NOT (id = 3) AND "
        "(career = 'CS' OR age < 20)",
    ):
        optimized = _values(run_sql(environment, sql, use_indexes=True))
        baseline = _values(run_sql(environment, sql, use_indexes=False))
        assert Counter(optimized) == Counter(baseline)

    join_sql = (
        "SELECT s.name, e.course FROM students AS s "
        "JOIN enrollments AS e ON s.id = e.student_id"
    )
    grace = _values(
        run_sql(
            environment,
            join_sql,
            planning_options=PhysicalPlanningOptions(
                join_strategy=JoinPlanningStrategy.GRACE_HASH
            ),
        )
    )
    nested = _values(
        run_sql(
            environment,
            join_sql,
            planning_options=PhysicalPlanningOptions(
                join_strategy=JoinPlanningStrategy.NESTED_LOOP
            ),
        )
    )
    assert Counter(grace) == Counter(nested)


def test_invalid_complete_api_requests_leave_storage_and_indexes_unchanged(
    acceptance_environment,
):
    environment, _, students, _, indexes, _ = acceptance_environment
    engine = SqlEngine(environment)
    before = tuple(record.values for _, record in students.scan())
    invalid = (
        "SELECT * FROM students; DELETE FROM students WHERE id = 1",
        "SELECT missing FROM students",
        "SELECT name, COUNT(*) FROM students GROUP BY career",
        "INSERT INTO students VALUES (8, 'Mia', 'CS', 'not-an-integer')",
        "SELECT id FROM students WHERE age = 'young'",
        "BEGIN TRANSACTION",
    )
    for sql in invalid:
        with pytest.raises(ValidationError):
            engine.execute(sql)
        assert tuple(record.values for _, record in students.scan()) == before

    prepared = engine.prepare("SELECT name FROM students WHERE id = 3")
    with pytest.raises(ValidationError, match="fixed planning options"):
        engine.execute(prepared, use_indexes=False)
    assert _values(prepared.execute()) == (("Sol",),)
    for index in indexes:
        index.validate_structure()
