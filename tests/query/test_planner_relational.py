"""Tasks 7.18-7.20: SQL routes to Stage 6 sort, group, and join operators."""

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
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes.index_catalog import build_catalog_index
from engine.operators import (
    ExternalHashGroup,
    ExternalSort,
    GraceHashJoin,
    IndexNestedLoopJoin,
    NestedLoopJoin,
    Projection,
    collect,
)
from engine.operators.aggregation import MINIMUM_GROUP_BUDGET_BYTES
from engine.operators.join import MINIMUM_JOIN_BUDGET_BYTES
from engine.operators.sorting import MINIMUM_FAN_IN, MINIMUM_SORT_BUDGET_BYTES
from engine.query import (
    JoinPlanningStrategy,
    PhysicalPlanningOptions,
    QueryEnvironment,
    build_select_plan,
    parse_sql,
    prepare_select_plan,
)
from engine.storage import HeapFile, Record


STUDENTS = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
    Column("career", DataType.VARCHAR),
    Column("age", DataType.INTEGER),
])

ENROLLMENTS = Schema([
    Column("id", DataType.INTEGER),
    Column("student_id", DataType.INTEGER),
    Column("course", DataType.VARCHAR),
    Column("owner_age", DataType.INTEGER),
])

STUDENT_ROWS = (
    (1, "Ana", "CS", 22),
    (2, "Luis", "EE", 19),
    (3, "Sol", "CS", 24),
    (4, "Omar", "EE", 23),
    (5, "Kai", "CS", 23),
)

ENROLLMENT_ROWS = (
    (10, 1, "DB2", 22),
    (11, 1, "OS", 22),
    (12, 3, "DB2", 24),
    (13, 3, "AI", 24),
    (14, 3, "DB2", 24),
    (15, 99, "GHOST", 0),
)


def _values(operator, *, limit=20_000):
    return tuple(row.values for row in collect(operator, limit=limit))


@pytest.fixture
def environment(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    catalog.register_table(TableMetadata("enrollments", ENROLLMENTS))
    env = QueryEnvironment(catalog)
    students = HeapFile.create(tmp_path / "students.heap", STUDENTS)
    enrollments = HeapFile.create(tmp_path / "enrollments.heap", ENROLLMENTS)
    env.register_storage("students", students)
    env.register_storage("enrollments", enrollments)
    for row in STUDENT_ROWS:
        students.insert(Record(STUDENTS, row))
    for row in ENROLLMENT_ROWS:
        enrollments.insert(Record(ENROLLMENTS, row))
    try:
        yield env, students, enrollments
    finally:
        enrollments.close()
        students.close()


def test_planning_options_reject_invalid_resource_and_strategy_values():
    with pytest.raises(ValidationError, match="sort_memory_budget_bytes"):
        PhysicalPlanningOptions(sort_memory_budget_bytes=1)
    with pytest.raises(InvalidTypeError, match="sort_max_fan_in"):
        PhysicalPlanningOptions(sort_max_fan_in=True)
    with pytest.raises(ValidationError, match="group_partition_count"):
        PhysicalPlanningOptions(group_partition_count=1)
    with pytest.raises(InvalidTypeError, match="join_strategy"):
        PhysicalPlanningOptions(join_strategy="GRACE_HASH")


def test_order_by_uses_external_sort_before_projection_and_keeps_hidden_key(
    environment,
):
    env, _, _ = environment
    plan = build_select_plan(
        env,
        parse_sql("SELECT name FROM students ORDER BY age DESC"),
    )

    assert isinstance(plan, Projection)
    assert isinstance(plan.child, ExternalSort)
    assert _values(plan) == (("Sol",), ("Omar",), ("Kai",), ("Ana",), ("Luis",))


def test_order_by_output_alias_takes_precedence_and_equal_keys_are_stable(environment):
    env, _, _ = environment
    alias_plan = build_select_plan(
        env,
        parse_sql("SELECT id AS age FROM students ORDER BY age DESC"),
    )
    stable_plan = build_select_plan(
        env,
        parse_sql("SELECT name FROM students ORDER BY age ASC"),
    )

    assert _values(alias_plan) == ((5,), (4,), (3,), (2,), (1,))
    assert _values(stable_plan) == (
        ("Luis",), ("Ana",), ("Omar",), ("Kai",), ("Sol",),
    )


def test_sql_order_by_can_force_multiple_real_merge_passes(tmp_path):
    schema = Schema([
        Column("id", DataType.INTEGER),
        Column("payload", DataType.VARCHAR),
    ])
    catalog = Catalog()
    catalog.register_table(TableMetadata("wide_rows", schema))
    env = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "wide.heap", schema)
    env.register_storage("wide_rows", storage)
    for number in range(600):
        storage.insert(Record(schema, [number, f"{number:04d}" + "x" * 500]))
    try:
        plan = build_select_plan(
            env,
            parse_sql("SELECT id FROM wide_rows ORDER BY payload DESC"),
            options=PhysicalPlanningOptions(
                sort_memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
                sort_max_fan_in=MINIMUM_FAN_IN,
            ),
        )
        sort = plan.child
        assert _values(plan, limit=601) == tuple((number,) for number in range(599, -1, -1))
        assert isinstance(sort, ExternalSort)
        assert sort.metrics.initial_runs > sort.fan_in
        assert sort.metrics.merge_passes >= 2
        assert sort.metrics.temporary_pages_written > 0
        assert sort.metrics.temporary_pages_read > 0
    finally:
        storage.close()


def test_grouping_filters_first_orders_aggregate_alias_and_projects_schema(environment):
    env, _, _ = environment
    plan = build_select_plan(
        env,
        parse_sql(
            "SELECT career, COUNT(*) AS n, AVG(age) AS mean_age "
            "FROM students WHERE age >= 22 GROUP BY career "
            "ORDER BY n DESC, career ASC"
        ),
    )

    assert isinstance(plan, Projection)
    assert isinstance(plan.child, ExternalSort)
    assert isinstance(plan.child.child, ExternalHashGroup)
    assert [column.name for column in plan.output_schema] == [
        "career", "n", "mean_age",
    ]
    assert _values(plan) == (("CS", 3, 23.0), ("EE", 1, 23.0))


def test_global_count_over_an_empty_filtered_input_preserves_stage6_behavior(environment):
    env, _, _ = environment
    plan = build_select_plan(
        env,
        parse_sql("SELECT COUNT(*) AS n FROM students WHERE age > 999"),
    )

    assert isinstance(plan.child, ExternalHashGroup)
    assert _values(plan) == ((0,),)


def test_aggregate_alias_can_match_a_hidden_group_key_without_layout_collision(
    environment,
):
    env, _, _ = environment
    plan = build_select_plan(
        env,
        parse_sql(
            "SELECT COUNT(*) AS career FROM students "
            "GROUP BY career ORDER BY career DESC"
        ),
    )

    assert [column.name for column in plan.output_schema] == ["career"]
    assert _values(plan) == ((3,), (2,))


def test_sql_group_by_exercises_external_partitioning_when_state_does_not_fit(tmp_path):
    schema = Schema([
        Column("bucket", DataType.VARCHAR),
        Column("amount", DataType.INTEGER),
    ])
    catalog = Catalog()
    catalog.register_table(TableMetadata("sales", schema))
    env = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "sales.heap", schema)
    env.register_storage("sales", storage)
    for number in range(4_000):
        storage.insert(Record(schema, [f"r{number % 400}", number % 17]))
    try:
        plan = build_select_plan(
            env,
            parse_sql(
                "SELECT bucket, COUNT(*) AS n, SUM(amount) AS total, "
                "AVG(amount) AS mean, MIN(amount) AS lo, MAX(amount) AS hi "
                "FROM sales GROUP BY bucket"
            ),
            options=PhysicalPlanningOptions(
                group_memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
                group_partition_count=2,
            ),
        )
        group = plan.child
        rows = _values(plan, limit=401)
        assert len(rows) == 400
        assert sum(row[1] for row in rows) == 4_000
        assert isinstance(group, ExternalHashGroup)
        assert group.metrics.kernel_overflows > 0
        assert group.metrics.repartitions > 0
        assert group.metrics.temporary_pages_written > 0
        assert group.metrics.temporary_pages_read > 0
    finally:
        storage.close()


def test_default_join_uses_grace_hash_and_preserves_duplicate_multiplicity(environment):
    env, _, _ = environment
    plan = build_select_plan(
        env,
        parse_sql(
            "SELECT s.career, e.course FROM students AS s "
            "JOIN enrollments AS e ON s.id = e.student_id"
        ),
        options=PhysicalPlanningOptions(
            join_memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES,
            join_partition_count=2,
        ),
    )
    join = plan.child
    rows = _values(plan)

    assert isinstance(join, GraceHashJoin)
    assert Counter(rows) == Counter({
        ("CS", "DB2"): 3,
        ("CS", "OS"): 1,
        ("CS", "AI"): 1,
    })
    assert join.metrics.pairs_joined_by_hash > 0
    assert join.metrics.temporary_pages_written > 0
    assert join.metrics.temporary_pages_read > 0


def test_join_applies_on_residual_inside_join_and_where_after_join(environment):
    env, _, _ = environment
    prepared = prepare_select_plan(
        env,
        parse_sql(
            "SELECT s.name, e.id FROM students AS s "
            "JOIN enrollments AS e "
            "ON s.id = e.student_id AND e.course = 'DB2' "
            "WHERE s.age > 22"
        ),
    )
    plan = prepared.instantiate()

    assert prepared.describe().children[0].name == "Filter"
    assert _values(plan) == (("Sol", 12), ("Sol", 14))


def test_grace_hash_matches_nested_loop_and_no_match_query_is_empty(environment):
    env, _, _ = environment
    sql = parse_sql(
        "SELECT s.id, e.id FROM students AS s "
        "JOIN enrollments AS e ON s.id = e.student_id AND s.age = e.owner_age"
    )
    grace = build_select_plan(
        env,
        sql,
        options=PhysicalPlanningOptions(
            join_strategy=JoinPlanningStrategy.GRACE_HASH,
        ),
    )
    nested = build_select_plan(
        env,
        sql,
        options=PhysicalPlanningOptions(
            join_strategy=JoinPlanningStrategy.NESTED_LOOP,
        ),
    )

    assert isinstance(grace.child, GraceHashJoin)
    assert isinstance(nested.child, NestedLoopJoin)
    assert Counter(_values(grace)) == Counter(_values(nested))
    no_matches = build_select_plan(
        env,
        parse_sql(
            "SELECT s.id FROM students AS s JOIN enrollments AS e "
            "ON s.id = e.student_id WHERE e.student_id = 404"
        ),
    )
    assert _values(no_matches) == ()


def test_many_to_many_join_emits_the_full_m_times_n_multiplicity(tmp_path):
    left_schema = Schema([
        Column("key", DataType.INTEGER),
        Column("left_value", DataType.VARCHAR),
    ])
    right_schema = Schema([
        Column("key", DataType.INTEGER),
        Column("right_value", DataType.VARCHAR),
    ])
    catalog = Catalog()
    catalog.register_table(TableMetadata("left_rows", left_schema))
    catalog.register_table(TableMetadata("right_rows", right_schema))
    env = QueryEnvironment(catalog)
    left = HeapFile.create(tmp_path / "left.heap", left_schema)
    right = HeapFile.create(tmp_path / "right.heap", right_schema)
    env.register_storage("left_rows", left)
    env.register_storage("right_rows", right)
    for row in ((7, "l1"), (7, "l2")):
        left.insert(Record(left_schema, row))
    for row in ((7, "r1"), (7, "r2"), (7, "r3")):
        right.insert(Record(right_schema, row))
    try:
        plan = build_select_plan(
            env,
            parse_sql(
                "SELECT l.left_value, r.right_value FROM left_rows AS l "
                "JOIN right_rows AS r ON l.key = r.key"
            ),
        )

        assert Counter(_values(plan)) == Counter({
            ("l1", "r1"): 1,
            ("l1", "r2"): 1,
            ("l1", "r3"): 1,
            ("l2", "r1"): 1,
            ("l2", "r2"): 1,
            ("l2", "r3"): 1,
        })
    finally:
        right.close()
        left.close()


def test_auto_join_uses_only_an_eligible_exact_inner_index(environment, tmp_path):
    env, _, enrollments = environment
    metadata = IndexMetadata(
        "enrollment_student_hash",
        "enrollments",
        "student_id",
        IndexType.EXTENDIBLE_HASH,
        file_path=str(tmp_path / "enrollment_student.hash"),
    )
    env.catalog.register_index(metadata)
    index = build_catalog_index(env.catalog, metadata.name, enrollments)
    env.register_index(metadata.name, index)
    try:
        eligible = build_select_plan(
            env,
            parse_sql(
                "SELECT s.name, e.course FROM students AS s "
                "JOIN enrollments AS e ON s.id = e.student_id"
            ),
        )
        multi_key = build_select_plan(
            env,
            parse_sql(
                "SELECT s.name, e.course FROM students AS s "
                "JOIN enrollments AS e "
                "ON s.id = e.student_id AND s.age = e.owner_age"
            ),
        )

        assert isinstance(eligible.child, IndexNestedLoopJoin)
        assert Counter(_values(eligible)) == Counter({
            ("Ana", "DB2"): 1,
            ("Ana", "OS"): 1,
            ("Sol", "DB2"): 2,
            ("Sol", "AI"): 1,
        })
        assert eligible.child.metrics.index_probes == len(STUDENT_ROWS)
        assert isinstance(multi_key.child, GraceHashJoin)
    finally:
        index.close()
