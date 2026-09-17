"""Tasks 7.8-7.12: read-only Catalog-backed semantic binding."""

import math
from types import SimpleNamespace

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
from engine.errors import (
    DuplicateError,
    InvalidReferenceError,
    SchemaError,
    UnknownColumnError,
    UnknownTableError,
    ValidationError,
)
from engine.indexes import Index, build_catalog_index
from engine.operators import Avg, Count, CountColumn
from engine.storage import HeapFile, PagedSequentialFile, RID, Record, Storage
from engine.query import (
    BoundDelete,
    BoundInsert,
    BoundSelect,
    QueryEnvironment,
    SqlBindingError,
    bind_statement,
    parse_sql,
)


STUDENTS = Schema(
    [
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
        Column("career", DataType.VARCHAR),
        Column("age", DataType.INTEGER),
        Column("score", DataType.FLOAT),
        Column("active", DataType.BOOLEAN),
    ]
)
ENROLLMENTS = Schema(
    [
        Column("id", DataType.INTEGER),
        Column("student_id", DataType.INTEGER),
        Column("course", DataType.VARCHAR),
    ]
)
BAD_JOIN = Schema([Column("student_id", DataType.VARCHAR)])


class SpyStorage(Storage):
    def __init__(self, schema):
        self.schema = schema
        self.insert_calls = 0
        self.delete_calls = 0

    def insert(self, record):
        self.insert_calls += 1
        return RID(1, 0)

    def read(self, rid):
        raise InvalidReferenceError("empty")

    def delete(self, rid):
        self.delete_calls += 1

    def scan(self):
        if False:
            yield


class SpyIndex(Index):
    def __init__(self, matches=(), header=None):
        self.insert_calls = 0
        self.delete_calls = 0
        self.matches = tuple(matches)
        self.header = header

    def insert(self, key, rid):
        self.insert_calls += 1

    def search(self, key):
        yield from self.matches

    def delete(self, key, rid):
        self.delete_calls += 1


@pytest.fixture
def environment():
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    catalog.register_table(TableMetadata("enrollments", ENROLLMENTS))
    catalog.register_table(TableMetadata("bad_join", BAD_JOIN))
    env = QueryEnvironment(catalog)
    env.register_storage("students", SpyStorage(STUDENTS))
    env.register_storage("enrollments", SpyStorage(ENROLLMENTS))
    env.register_storage("bad_join", SpyStorage(BAD_JOIN))
    return env


def _bind(environment, sql):
    return bind_statement(environment, parse_sql(sql))


def test_environment_rejects_wrong_catalog_runtime_pairs():
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    env = QueryEnvironment(catalog)

    with pytest.raises(SchemaError):
        env.register_storage("students", SpyStorage(ENROLLMENTS))
    env.register_storage("students", SpyStorage(STUDENTS))
    with pytest.raises(DuplicateError):
        env.register_storage("students", SpyStorage(STUDENTS))


def test_environment_does_not_reuse_one_runtime_object_for_two_identities():
    catalog = Catalog()
    catalog.register_table(TableMetadata("first", STUDENTS))
    catalog.register_table(TableMetadata("second", STUDENTS))
    environment = QueryEnvironment(catalog)
    shared_storage = SpyStorage(STUDENTS)
    environment.register_storage("first", shared_storage)
    with pytest.raises(DuplicateError, match="two Catalog tables"):
        environment.register_storage("second", shared_storage)

    first_index = IndexMetadata(
        "ix_first_id",
        "first",
        "id",
        IndexType.EXTENDIBLE_HASH,
    )
    second_index = IndexMetadata(
        "ix_first_age",
        "first",
        "age",
        IndexType.EXTENDIBLE_HASH,
    )
    catalog.register_index(first_index)
    catalog.register_index(second_index)
    shared_index = SpyIndex()
    environment.register_index(first_index.name, shared_index)
    with pytest.raises(DuplicateError, match="two Catalog indexes"):
        environment.register_index(second_index.name, shared_index)


def test_environment_distinguishes_unknown_table_from_missing_runtime_storage():
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    env = QueryEnvironment(catalog)

    with pytest.raises(UnknownTableError):
        env.storage_for("missing")
    with pytest.raises(InvalidReferenceError, match="No runtime storage"):
        env.storage_for("students")


def test_environment_validates_and_accepts_a_real_catalog_index(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    metadata = IndexMetadata(
        "ix_students_age",
        "students",
        "age",
        IndexType.BPLUS,
        file_path=str(tmp_path / "students_age.bplus"),
    )
    catalog.register_index(metadata)
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "students.heap", STUDENTS)
    index = None
    try:
        environment.register_storage("students", storage)
        index = build_catalog_index(catalog, metadata.name, storage)
        environment.register_index(metadata.name, index)

        assert environment.index_for(metadata.name) is index
        assert environment.registered_indexes_for("students")[0].metadata == metadata
    finally:
        if index is not None:
            index.close()
        storage.close()


def test_environment_rejects_incompatible_or_incomplete_runtime_indexes(environment):
    bplus = IndexMetadata(
        "ix_students_age",
        "students",
        "age",
        IndexType.BPLUS,
    )
    environment.catalog.register_index(bplus)
    with pytest.raises(ValidationError, match="ordering capability"):
        environment.register_index(bplus.name, SpyIndex())

    hashed = IndexMetadata(
        "ix_students_id",
        "students",
        "id",
        IndexType.EXTENDIBLE_HASH,
    )
    environment.catalog.register_index(hashed)
    incomplete = SpyIndex(header=SimpleNamespace(build_complete=False))
    with pytest.raises(ValidationError, match="not completely built"):
        environment.register_index(hashed.name, incomplete)


def test_relation_instances_aliases_and_deterministic_star_order(environment):
    bound = _bind(
        environment,
        "SELECT s.*, e.* FROM students s JOIN enrollments e "
        "ON s.id = e.student_id",
    )

    assert isinstance(bound, BoundSelect)
    assert [relation.instance_id for relation in bound.relations] == [0, 1]
    assert [relation.exposed_name for relation in bound.relations] == ["s", "e"]
    assert [column.name for column in bound.output_schema] == [
        "s.id",
        "name",
        "career",
        "age",
        "score",
        "active",
        "e.id",
        "student_id",
        "course",
    ]


def test_self_join_has_distinct_relation_instances(environment):
    bound = _bind(
        environment,
        "SELECT a.id AS left_id, b.id AS right_id FROM students a "
        "JOIN students b ON a.id = b.id",
    )
    assert bound.relations[0].metadata is bound.relations[1].metadata
    assert bound.relations[0].instance_id != bound.relations[1].instance_id


def test_table_column_and_alias_resolution_is_exact_case_sensitive(environment):
    bound = _bind(
        environment,
        "SELECT S.id AS student_id, s.id AS enrollment_id FROM students S "
        "JOIN enrollments s ON S.id = s.student_id",
    )
    assert [relation.exposed_name for relation in bound.relations] == ["S", "s"]

    with pytest.raises(UnknownTableError):
        _bind(environment, "SELECT * FROM Students")
    with pytest.raises(UnknownColumnError):
        _bind(environment, "SELECT s.id FROM students S")


@pytest.mark.parametrize(
    "sql,error",
    [
        ("SELECT * FROM missing", UnknownTableError),
        ("SELECT nope FROM students", UnknownColumnError),
        (
            "SELECT id FROM students s JOIN enrollments e ON s.id = e.student_id",
            ValidationError,
        ),
        (
            "SELECT students.id FROM students s",
            UnknownColumnError,
        ),
        (
            "SELECT * FROM students x JOIN enrollments x ON x.id = x.student_id",
            SqlBindingError,
        ),
    ],
)
def test_relation_and_column_resolution_failures_are_controlled(environment, sql, error):
    with pytest.raises(error):
        _bind(environment, sql)


def test_predicates_use_exact_types_and_preserve_boolean_structure(environment):
    bound = _bind(
        environment,
        "SELECT id FROM students WHERE (age >= 20 AND NOT active = FALSE) "
        "OR name = 'Ana'",
    )
    predicate = bound.where
    assert predicate is not None
    assert {ref.name for ref in predicate.references} == {"age", "active", "name"}
    assert predicate.bound.matches((1, "Ana", "CS", 19, 3.5, False)) is True
    assert predicate.bound.matches((2, "Luis", "EE", 21, 3.0, True)) is True
    assert predicate.bound.matches((3, "Sol", "CS", 21, 4.0, False)) is False


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM students WHERE score = 1",
        "SELECT * FROM students WHERE age = 1.0",
        "SELECT * FROM students WHERE age = 999999999999999999999999999999",
    ],
)
def test_predicate_type_and_integer_range_errors_are_located(environment, sql):
    with pytest.raises(SqlBindingError) as excinfo:
        _bind(environment, sql)
    assert excinfo.value.position > 0


def test_index_candidates_are_only_safe_conjuncts_and_normalize_signed_zero(environment):
    bound = _bind(
        environment,
        "SELECT id FROM students WHERE -0.0 = score AND age >= 20 "
        "AND name <> 'retained-as-residual'",
    )
    conditions = bound.where.index_conditions
    assert [(condition.column.name, condition.operator.value) for condition in conditions] == [
        ("score", "="),
        ("age", ">="),
    ]
    assert conditions[0].value == 0.0
    assert math.copysign(1.0, conditions[0].value) == 1.0

    disjunction = _bind(
        environment,
        "SELECT id FROM students WHERE score = 0.0 OR age = 20",
    )
    assert disjunction.where.index_conditions == ()


def test_join_binding_extracts_cross_input_keys_and_keeps_residuals(environment):
    bound = _bind(
        environment,
        "SELECT s.name, e.course FROM students s JOIN enrollments e "
        "ON s.id = e.student_id AND e.course = 'DB2'",
    )
    assert [(key.left.qualified_name, key.right.qualified_name) for key in bound.join_keys] == [
        ("s.id", "e.student_id")
    ]
    assert bound.join_predicate is not None
    assert len(bound.join_predicate.references) == 3


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM students s JOIN enrollments e ON s.age > 0",
        "SELECT * FROM students s JOIN bad_join b ON s.id = b.student_id",
        "SELECT * FROM students s JOIN enrollments e "
        "ON s.id = e.student_id OR s.age = e.id",
    ],
)
def test_unsupported_or_incompatible_join_conditions_are_rejected(environment, sql):
    with pytest.raises(SqlBindingError):
        _bind(environment, sql)


def test_projection_alias_and_hidden_order_key_contract(environment):
    bound = _bind(
        environment,
        "SELECT name AS student_name FROM students ORDER BY age DESC",
    )
    assert [column.name for column in bound.output_schema] == ["student_name"]
    assert bound.order_by[0].source.name == "age"
    assert bound.order_by[0].hidden is True
    assert bound.order_by[0].descending is True


def test_order_by_prefers_an_output_alias_but_where_cannot_see_it(environment):
    ordered = _bind(
        environment,
        "SELECT name AS age FROM students ORDER BY age",
    )
    assert ordered.order_by[0].output_position == 0
    assert ordered.order_by[0].source.name == "name"

    with pytest.raises(UnknownColumnError):
        _bind(environment, "SELECT age AS years FROM students WHERE years = 20")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name AS x, career AS x FROM students",
        "SELECT name, name FROM students",
        "SELECT name FROM students ORDER BY 1",
        "SELECT name FROM students ORDER BY 'name'",
    ],
)
def test_projection_and_order_policy_rejects_ambiguous_outputs(environment, sql):
    with pytest.raises(SqlBindingError):
        _bind(environment, sql)


def test_grouping_reuses_stage6_aggregate_signatures_and_exact_output_schema(environment):
    bound = _bind(
        environment,
        "SELECT career, COUNT(*) AS n, COUNT(age), AVG(age) AS mean "
        "FROM students GROUP BY career ORDER BY n DESC",
    )
    assert [column.name for column in bound.output_schema] == [
        "career",
        "n",
        "count_age",
        "mean",
    ]
    assert isinstance(bound.aggregates[0], Count)
    assert isinstance(bound.aggregates[1], CountColumn)
    assert isinstance(bound.aggregates[2], Avg)
    assert bound.projection[0].group_key_index == 0
    assert bound.order_by[0].output_position == 1


def test_global_count_is_adopted_and_typed(environment):
    bound = _bind(environment, "SELECT COUNT(*) AS n FROM students")
    assert bound.grouped is True
    assert bound.group_keys == ()
    assert bound.output_schema.column("n").data_type is DataType.INTEGER


def test_grouped_order_can_carry_an_unselected_group_key(environment):
    bound = _bind(
        environment,
        "SELECT COUNT(*) AS n FROM students GROUP BY career ORDER BY career",
    )
    assert bound.order_by[0].source.name == "career"
    assert bound.order_by[0].hidden is True


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT career FROM students GROUP BY career",
        "SELECT name, COUNT(*) FROM students GROUP BY career",
        "SELECT * FROM students GROUP BY career",
        "SELECT career, COUNT(*) FROM students",
        "SELECT SUM(name) FROM students",
        "SELECT COUNT(*) FROM students GROUP BY career ORDER BY age",
    ],
)
def test_invalid_aggregate_and_grouping_semantics_fail_during_binding(environment, sql):
    with pytest.raises(SqlBindingError):
        _bind(environment, sql)


def test_insert_column_reordering_builds_schema_order_without_writing(environment):
    storage = environment.storage_for("students")
    bound = _bind(
        environment,
        "INSERT INTO students (name, id, career, age, score, active) "
        "VALUES ('Ana', 1, 'CS', 22, 4.5, TRUE)",
    )
    assert isinstance(bound, BoundInsert)
    assert bound.record.values == (1, "Ana", "CS", 22, 4.5, True)
    assert storage.insert_calls == 0


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO students VALUES (1, 'Ana')",
        "INSERT INTO students (id, id, name, career, age, score, active) "
        "VALUES (1, 2, 'A', 'CS', 20, 1.0, TRUE)",
        "INSERT INTO students (id, name) VALUES (1, 'Ana')",
        "INSERT INTO students VALUES (1, 'Ana', 'CS', 20, 1, TRUE)",
        "INSERT INTO students VALUES (999999999999999999999, 'A', 'CS', 20, 1.0, TRUE)",
    ],
)
def test_insert_predictable_failures_happen_before_any_write(environment, sql):
    storage = environment.storage_for("students")
    with pytest.raises((SqlBindingError, UnknownColumnError)):
        _bind(environment, sql)
    assert storage.insert_calls == 0


def test_insert_rejects_a_row_larger_than_one_storage_page(environment):
    value = "x" * 5000
    with pytest.raises(SqlBindingError, match="page capacity"):
        _bind(
            environment,
            "INSERT INTO students VALUES "
            f"(1, '{value}', 'CS', 20, 1.0, TRUE)",
        )


def test_insert_identifies_every_index_and_defers_unique_check_without_writing(environment):
    metadata = IndexMetadata(
        "ux_students_id",
        "students",
        "id",
        IndexType.EXTENDIBLE_HASH,
        unique=True,
    )
    environment.catalog.register_index(metadata)
    index = SpyIndex()
    environment.register_index(metadata.name, index)

    bound = _bind(
        environment,
        "INSERT INTO students VALUES (1, 'Ana', 'CS', 22, 4.5, TRUE)",
    )
    assert bound.indexes[0].key == 1
    assert bound.indexes[0].requires_unique_check is True
    assert index.insert_calls == 0


def test_insert_reports_a_known_unique_violation_without_writing(environment):
    metadata = IndexMetadata(
        "ux_students_id",
        "students",
        "id",
        IndexType.EXTENDIBLE_HASH,
        unique=True,
    )
    environment.catalog.register_index(metadata)
    index = SpyIndex([RID(1, 0)])
    environment.register_index(metadata.name, index)

    with pytest.raises(SqlBindingError, match="already contains key"):
        _bind(
            environment,
            "INSERT INTO students VALUES (1, 'Ana', 'CS', 22, 4.5, TRUE)",
        )
    assert environment.storage_for("students").insert_calls == 0
    assert index.insert_calls == 0


def test_insert_honors_paged_sequential_unique_key_without_writing(tmp_path):
    schema = Schema(
        [Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)]
    )
    catalog = Catalog()
    catalog.register_table(TableMetadata("items", schema))
    environment = QueryEnvironment(catalog)
    storage = PagedSequentialFile.create(
        tmp_path / "items.seq",
        schema,
        "id",
        allow_duplicate_keys=False,
    )
    try:
        storage.insert(Record(schema, [1, "existing"]))
        environment.register_storage("items", storage)

        valid = _bind(environment, "INSERT INTO items VALUES (2, 'new')")
        assert valid.storage_key == 2
        assert valid.requires_storage_unique_check is True
        assert storage.record_count == 1

        with pytest.raises(SqlBindingError, match="already exists"):
            _bind(environment, "INSERT INTO items VALUES (1, 'duplicate')")
        assert storage.record_count == 1
    finally:
        storage.close()


def test_mutation_rejects_a_declared_but_unavailable_index(environment):
    environment.catalog.register_index(
        IndexMetadata(
            "ix_students_age",
            "students",
            "age",
            IndexType.BPLUS,
        )
    )
    with pytest.raises(InvalidReferenceError, match="No runtime index"):
        _bind(
            environment,
            "INSERT INTO students VALUES (1, 'Ana', 'CS', 22, 4.5, TRUE)",
        )


def test_delete_binds_target_predicate_and_requires_real_rids_without_writing(environment):
    storage = environment.storage_for("students")
    bound = _bind(environment, "DELETE FROM students WHERE age >= 20")

    assert isinstance(bound, BoundDelete)
    assert bound.requires_stable_rid is True
    assert bound.where is not None
    assert bound.where.bound.matches((1, "Ana", "CS", 22, 4.5, True)) is True
    assert storage.delete_calls == 0


def test_whole_table_delete_binding_is_read_only(environment):
    storage = environment.storage_for("students")
    bound = _bind(environment, "DELETE FROM students")
    assert bound.where is None
    assert storage.delete_calls == 0


def test_invalid_delete_predicate_and_unknown_target_do_not_write(environment):
    storage = environment.storage_for("students")
    with pytest.raises(SqlBindingError):
        _bind(environment, "DELETE FROM students WHERE age = 'old'")
    with pytest.raises(UnknownTableError):
        _bind(environment, "DELETE FROM missing")
    assert storage.delete_calls == 0


def test_public_environment_rejects_non_contract_objects(environment):
    environment.catalog.register_index(
        IndexMetadata(
            "ix_students_id",
            "students",
            "id",
            IndexType.BPLUS,
        )
    )
    with pytest.raises(TypeError):
        environment.register_index("ix_students_id", object())
