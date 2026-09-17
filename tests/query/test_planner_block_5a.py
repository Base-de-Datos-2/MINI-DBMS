"""Tasks 7.13-7.17: reusable basic physical plans and safe access paths."""

from dataclasses import FrozenInstanceError

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
from engine.errors import UnsupportedAccessError
from engine.indexes.index_catalog import build_catalog_index
from engine.operators import (
    EqualitySearch,
    Filter,
    IndexScan,
    Literal,
    OperatorState,
    Projection,
    RangeSearch,
    TableScan,
    Compare,
    ComparisonOperator,
    column,
    collect,
)
from engine.storage import HeapFile, PagedSequentialFile, Record

from engine.query import (
    DeletePlanSpec,
    IndexScanSpec,
    InsertPlanSpec,
    SelectPlanSpec,
    StalePlanError,
    build_select_plan,
    parse_sql,
    prepare_plan,
    prepare_select_plan,
)
from engine.query.environment import QueryEnvironment
from engine.query.environment import RegisteredIndex


STUDENTS = Schema(
    [
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
        Column("age", DataType.INTEGER),
    ]
)

ROWS = (
    (1, "Ana", 22),
    (2, "Luis", 19),
    (3, "Sol", 24),
    (4, "Omar", 23),
    (5, "Kai", 23),
)


def _leaf(operator):
    node = operator
    while hasattr(node, "child"):
        node = node.child
    return node


def _values(operator):
    return tuple(row.values for row in collect(operator, limit=100))


@pytest.fixture
def heap_environment(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "students.heap", STUDENTS)
    environment.register_storage("students", storage)
    rids = [storage.insert(Record(STUDENTS, row)) for row in ROWS]
    try:
        yield environment, storage, rids
    finally:
        storage.close()


@pytest.fixture
def indexed_environment(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    catalog.register_index(
        IndexMetadata(
            "a_age_hash",
            "students",
            "age",
            IndexType.EXTENDIBLE_HASH,
            file_path=str(tmp_path / "students_age.hash"),
        )
    )
    catalog.register_index(
        IndexMetadata(
            "z_age_bplus",
            "students",
            "age",
            IndexType.BPLUS,
            file_path=str(tmp_path / "students_age.bplus"),
        )
    )
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "students.heap", STUDENTS)
    environment.register_storage("students", storage)
    for row in ROWS:
        storage.insert(Record(STUDENTS, row))

    hash_index = build_catalog_index(catalog, "a_age_hash", storage)
    bplus_index = build_catalog_index(catalog, "z_age_bplus", storage)
    environment.register_index("a_age_hash", hash_index)
    environment.register_index("z_age_bplus", bplus_index)
    try:
        yield environment, storage, hash_index, bplus_index
    finally:
        bplus_index.close()
        hash_index.close()
        storage.close()


def test_prepared_spec_is_immutable_describable_and_builds_fresh_closed_trees(
    heap_environment,
):
    environment, storage, _ = heap_environment
    storage.reset_counters()
    prepared = prepare_select_plan(
        environment,
        parse_sql("SELECT name AS n FROM students WHERE age >= 22"),
    )

    assert isinstance(prepared, SelectPlanSpec)
    assert prepared.describe().render().splitlines()[0].startswith("Projection")
    assert storage.pages_read == 0
    with pytest.raises(FrozenInstanceError):
        prepared.indexes_enabled = False

    first = prepared.instantiate()
    second = prepared.instantiate()
    assert first is not second
    assert first.child is not second.child
    assert first.state is OperatorState.CREATED
    assert second.state is OperatorState.CREATED
    assert _values(first) == (("Ana",), ("Sol",), ("Omar",), ("Kai",))
    assert _values(second) == (("Ana",), ("Sol",), ("Omar",), ("Kai",))


def test_table_scan_baseline_keeps_filter_before_final_projection_and_duplicates(
    heap_environment,
):
    environment, _, _ = heap_environment
    plan = build_select_plan(
        environment,
        parse_sql("SELECT age FROM students WHERE age >= 23"),
    )

    assert isinstance(plan, Projection)
    assert isinstance(plan.child, Filter)
    assert isinstance(plan.child.child, TableScan)
    assert _values(plan) == ((24,), (23,), (23,))


def test_table_scan_baseline_matches_a_manual_stage6_pipeline(heap_environment):
    environment, storage, _ = heap_environment
    planned = build_select_plan(
        environment,
        parse_sql("SELECT s.name AS n FROM students AS s WHERE s.age >= 22"),
        use_indexes=False,
    )
    manual = Projection(
        Filter(
            TableScan(storage, relation="s"),
            Compare(
                column("age", relation="s"),
                ComparisonOperator.GREATER_OR_EQUAL,
                Literal(22),
            ),
        ),
        ["name"],
        ["n"],
    )

    assert planned.output_schema == manual.output_schema
    assert _values(planned) == _values(manual)


def test_baseline_skips_deleted_rows_and_projects_a_hidden_filter_dependency(
    heap_environment,
):
    environment, storage, rids = heap_environment
    storage.delete(rids[2])

    plan = build_select_plan(
        environment,
        parse_sql("SELECT name FROM students WHERE age >= 23"),
    )
    assert _values(plan) == (("Omar",), ("Kai",))


def test_paged_sequential_storage_uses_the_same_table_scan_baseline(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    environment = QueryEnvironment(catalog)
    storage = PagedSequentialFile.create(
        tmp_path / "students.seq",
        STUDENTS,
        "id",
    )
    environment.register_storage("students", storage)
    try:
        for row in reversed(ROWS):
            storage.insert(Record(STUDENTS, row))
        plan = build_select_plan(environment, parse_sql("SELECT id FROM students"))
        assert isinstance(_leaf(plan), TableScan)
        assert _values(plan) == ((1,), (2,), (3,), (4,), (5,))
    finally:
        storage.close()


def test_declared_but_unavailable_index_falls_back_to_table_scan(heap_environment):
    environment, _, _ = heap_environment
    environment.catalog.register_index(
        IndexMetadata(
            "ix_missing",
            "students",
            "age",
            IndexType.BPLUS,
        )
    )

    plan = build_select_plan(
        environment,
        parse_sql("SELECT id FROM students WHERE age = 23"),
    )
    assert isinstance(_leaf(plan), TableScan)
    assert sorted(_values(plan)) == [(4,), (5,)]


def test_disable_indexes_mode_is_equivalent_to_the_deterministic_hash_equality(
    indexed_environment,
):
    environment, _, hash_index, _ = indexed_environment
    statement = parse_sql("SELECT id FROM students WHERE 23 = age")

    indexed = build_select_plan(environment, statement)
    baseline = build_select_plan(environment, statement, use_indexes=False)
    leaf = _leaf(indexed)
    assert isinstance(leaf, IndexScan)
    assert leaf.index is hash_index
    assert leaf.search == EqualitySearch(23)
    assert isinstance(_leaf(baseline), TableScan)
    assert sorted(_values(indexed)) == sorted(_values(baseline)) == [(4,), (5,)]


def test_bplus_equality_is_used_when_it_is_the_only_compatible_index(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    metadata = IndexMetadata(
        "ix_age",
        "students",
        "age",
        IndexType.BPLUS,
        file_path=str(tmp_path / "age.bplus"),
    )
    catalog.register_index(metadata)
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "students.heap", STUDENTS)
    environment.register_storage("students", storage)
    for row in ROWS:
        storage.insert(Record(STUDENTS, row))
    index = build_catalog_index(catalog, metadata.name, storage)
    environment.register_index(metadata.name, index)
    try:
        plan = build_select_plan(
            environment,
            parse_sql("SELECT id FROM students WHERE age = 23"),
        )
        assert isinstance(_leaf(plan), IndexScan)
        assert _leaf(plan).index is index
        assert sorted(_values(plan)) == [(4,), (5,)]
    finally:
        index.close()
        storage.close()


def test_clustered_bplus_adapter_is_selected_without_changing_storage(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    metadata = IndexMetadata(
        "cx_age",
        "students",
        "age",
        IndexType.BPLUS,
        clustered=True,
        file_path=str(tmp_path / "age.clustered.bplus"),
    )
    catalog.register_index(metadata)
    environment = QueryEnvironment(catalog)
    storage = PagedSequentialFile.create(
        tmp_path / "students.seq",
        STUDENTS,
        "age",
    )
    environment.register_storage("students", storage)
    for row in ROWS:
        storage.insert(Record(STUDENTS, row))
    index = build_catalog_index(catalog, metadata.name, storage)
    environment.register_index(metadata.name, index)
    try:
        count_before = storage.record_count
        plan = build_select_plan(
            environment,
            parse_sql("SELECT id FROM students WHERE age = 23"),
        )
        leaf = _leaf(plan)
        assert isinstance(leaf, IndexScan)
        assert leaf.index is index
        assert sorted(_values(plan)) == [(4,), (5,)]
        assert storage.record_count == count_before
    finally:
        index.close()
        storage.close()


def test_invalid_range_capability_is_rejected_before_an_operator_is_built(
    indexed_environment,
):
    environment, _, hash_index, _ = indexed_environment
    prepared = prepare_select_plan(
        environment,
        parse_sql("SELECT id FROM students WHERE age = 23"),
    )
    relation = prepared.bound.relations[0]
    metadata = environment.catalog.get_index("a_age_hash")

    with pytest.raises(UnsupportedAccessError, match="hash index"):
        IndexScanSpec(
            environment,
            relation,
            RegisteredIndex(metadata, hash_index),
            RangeSearch(lower=20),
        )


def test_index_marked_incomplete_after_registration_is_skipped(
    indexed_environment,
):
    environment, _, hash_index, bplus_index = indexed_environment
    hash_index.index.mark_incomplete()

    plan = build_select_plan(
        environment,
        parse_sql("SELECT id FROM students WHERE age = 23"),
    )
    leaf = _leaf(plan)
    assert isinstance(leaf, IndexScan)
    assert leaf.index is bplus_index
    assert sorted(_values(plan)) == [(4,), (5,)]


@pytest.mark.parametrize(
    ("predicate", "expected", "lower", "upper", "include_lower", "include_upper"),
    [
        ("age < 23", [(1,), (2,)], None, 23, True, False),
        ("age >= 23", [(3,), (4,), (5,)], 23, None, True, True),
        ("23 <= age", [(3,), (4,), (5,)], 23, None, True, True),
        ("age >= 20 AND age < 24", [(1,), (4,), (5,)], 20, 24, True, False),
        ("age >= 23 AND age <= 23", [(4,), (5,)], 23, 23, True, True),
    ],
)
def test_bplus_ranges_combine_bounds_and_match_the_scan_baseline(
    indexed_environment,
    predicate,
    expected,
    lower,
    upper,
    include_lower,
    include_upper,
):
    environment, _, _, bplus_index = indexed_environment
    statement = parse_sql(f"SELECT id FROM students WHERE {predicate}")

    indexed = build_select_plan(environment, statement)
    baseline = build_select_plan(environment, statement, use_indexes=False)
    leaf = _leaf(indexed)
    assert isinstance(leaf, IndexScan)
    assert leaf.index is bplus_index
    assert leaf.search == RangeSearch(
        lower,
        upper,
        include_lower,
        include_upper,
    )
    assert sorted(_values(indexed)) == sorted(_values(baseline)) == expected


@pytest.mark.parametrize(
    "predicate",
    [
        "age = 19 OR age = 24",
        "NOT age = 23",
        "age <> 23",
        "age > 23 AND age <= 23",
    ],
)
def test_non_contiguous_or_contradictory_conditions_keep_table_scan(
    indexed_environment,
    predicate,
):
    environment, _, _, _ = indexed_environment
    statement = parse_sql(f"SELECT id FROM students WHERE {predicate}")
    optimized = build_select_plan(environment, statement)
    baseline = build_select_plan(environment, statement, use_indexes=False)

    assert isinstance(_leaf(optimized), TableScan)
    assert sorted(_values(optimized)) == sorted(_values(baseline))


def test_extra_and_predicate_remains_a_full_residual_filter(indexed_environment):
    environment, _, _, _ = indexed_environment
    plan = build_select_plan(
        environment,
        parse_sql("SELECT name FROM students WHERE age = 23 AND name = 'Kai'"),
    )

    assert isinstance(plan.child, Filter)
    assert isinstance(plan.child.child, IndexScan)
    assert _values(plan) == (("Kai",),)


def test_prepared_index_plan_rejects_catalog_change(indexed_environment):
    environment, _, _, _ = indexed_environment
    prepared = prepare_select_plan(
        environment,
        parse_sql("SELECT id FROM students WHERE age = 23"),
    )
    environment.catalog.unregister_index("a_age_hash")

    with pytest.raises(StalePlanError, match="no longer usable"):
        prepared.instantiate()


def test_prepared_plan_rejects_an_unversioned_table_definition_replacement(
    heap_environment,
):
    environment, _, _ = heap_environment
    prepared = prepare_select_plan(environment, parse_sql("SELECT id FROM students"))
    environment.catalog._tables["students"] = TableMetadata("students", STUDENTS)

    with pytest.raises(StalePlanError, match="Catalog definition changed"):
        prepared.instantiate()


def test_mutation_plan_variants_are_complete_but_do_not_write(heap_environment):
    environment, storage, _ = heap_environment
    before = storage.record_count

    insert = prepare_plan(
        environment,
        parse_sql("INSERT INTO students VALUES (9, 'Nia', 20)"),
    )
    delete = prepare_plan(
        environment,
        parse_sql("DELETE FROM students WHERE age < 20"),
    )

    assert isinstance(insert, InsertPlanSpec)
    assert isinstance(delete, DeletePlanSpec)
    assert storage.record_count == before
    first = delete.instantiate_candidates()
    second = delete.instantiate_candidates()
    assert first is not second
    assert _values(first) == ((2, "Luis", 19),)
    assert storage.record_count == before


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM students ORDER BY age",
        "SELECT COUNT(*) FROM students",
    ],
)
def test_later_planner_blocks_fail_explicitly_instead_of_building_partial_plans(
    heap_environment,
    sql,
):
    environment, _, _ = heap_environment
    with pytest.raises(UnsupportedAccessError, match="not implemented"):
        prepare_select_plan(environment, parse_sql(sql))
