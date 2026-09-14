"""Task 6.3: execution-row identity, provenance and derived output schemas."""

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, UnknownColumnError, ValidationError
from engine.operators import (
    ColumnReference,
    LayoutField,
    RowLayout,
    RowProvenance,
    as_reference,
)
from engine.storage import Record, RID
from tests.operator_helpers import ENROLLMENTS, STUDENTS


@pytest.fixture
def students_layout():
    return RowLayout(STUDENTS, relation="students")


@pytest.fixture
def enrollments_layout():
    return RowLayout(ENROLLMENTS, relation="enrollments")


def test_provenance_pairs_a_relation_with_a_rid_and_rejects_partial_identity():
    provenance = RowProvenance("students", RID(1, 2))

    assert provenance.relation == "students"
    assert provenance.rid == RID(1, 2)
    with pytest.raises(InvalidTypeError):
        RowProvenance("students", (1, 2))
    with pytest.raises(InvalidTypeError):
        RowProvenance(7, RID(1, 2))
    with pytest.raises(ValidationError):
        RowProvenance("   ", RID(1, 2))


def test_column_reference_qualifies_only_when_a_relation_is_supplied():
    assert ColumnReference("id").qualified_name == "id"
    assert ColumnReference("id", "students").qualified_name == "students.id"
    assert as_reference("id") == ColumnReference("id")
    assert as_reference(ColumnReference("id", "s")).relation == "s"
    with pytest.raises(InvalidTypeError):
        as_reference(3)
    with pytest.raises(ValidationError):
        ColumnReference("")


def test_layout_binds_positions_and_preserves_declared_types(students_layout):
    assert len(students_layout) == 4
    assert students_layout.schema is STUDENTS
    assert students_layout.resolve("name") == 1
    assert students_layout.data_type("age") is DataType.INTEGER
    assert students_layout.relations == ("students",)
    assert students_layout.positions(["age", "id"]) == (3, 0)
    assert [field.position for field in students_layout] == [0, 1, 2, 3]
    with pytest.raises(UnknownColumnError):
        students_layout.resolve("missing")


def test_unqualified_layout_reports_no_relation_and_still_resolves():
    layout = RowLayout(STUDENTS)

    assert layout.relations == ()
    assert layout.resolve("career") == 2
    assert layout.field("career").relation is None


def test_combined_layout_is_wider_and_keeps_both_same_named_columns(
    students_layout, enrollments_layout
):
    joined = RowLayout.combine(students_layout, enrollments_layout)

    assert len(joined) == len(students_layout) + len(enrollments_layout)
    assert [column.name for column in joined.schema] == [
        "students.id",
        "name",
        "career",
        "age",
        "enrollments.id",
        "student_id",
        "course",
    ]
    assert joined.resolve(ColumnReference("id", "students")) == 0
    assert joined.resolve(ColumnReference("id", "enrollments")) == 4
    assert joined.relations == ("students", "enrollments")


def test_combined_layout_rejects_an_ambiguous_bare_reference(
    students_layout, enrollments_layout
):
    joined = RowLayout.combine(students_layout, enrollments_layout)

    with pytest.raises(ValidationError, match="Ambiguous column"):
        joined.resolve("id")
    assert joined.resolve("students.id") == 0
    assert joined.resolve("name") == 1


def test_combining_unqualified_collisions_demands_an_alias():
    with pytest.raises(ValidationError, match="alias it before joining"):
        RowLayout.combine(RowLayout(STUDENTS), RowLayout(ENROLLMENTS))
    with pytest.raises(ValidationError, match="same qualified column twice"):
        RowLayout.combine(
            RowLayout(STUDENTS, relation="s"), RowLayout(STUDENTS, relation="s")
        )
    with pytest.raises(InvalidTypeError):
        RowLayout.combine(RowLayout(STUDENTS), STUDENTS)


def test_projection_layout_reorders_subsets_and_preserves_types(students_layout):
    projected = students_layout.project(["age", "name"])

    assert [column.name for column in projected.schema] == ["age", "name"]
    assert projected.data_type("age") is DataType.INTEGER
    assert projected.data_type("name") is DataType.VARCHAR
    assert projected.field("age").relation == "students"


def test_projection_alias_renames_and_drops_the_base_relation(students_layout):
    projected = students_layout.project(["id", "name"], ["student_id", None])

    assert [column.name for column in projected.schema] == ["student_id", "name"]
    assert projected.field("student_id").relation is None
    assert projected.field("name").relation == "students"
    with pytest.raises(UnknownColumnError):
        projected.resolve(ColumnReference("id", "students"))


def test_projection_repeats_a_column_only_when_the_repeats_are_aliased(
    students_layout,
):
    twice = students_layout.project(["id", "id"], [None, "copy"])

    assert [column.name for column in twice.schema] == ["id", "copy"]
    with pytest.raises(ValidationError, match="same output name twice"):
        students_layout.project(["id", "id"])
    with pytest.raises(ValidationError, match="one alias entry"):
        students_layout.project(["id", "name"], ["only_one"])
    with pytest.raises(InvalidTypeError):
        students_layout.project("id")


def test_derived_layout_has_a_schema_but_no_base_relation(students_layout):
    derived = students_layout.derive(
        Schema([Column("career", DataType.VARCHAR), Column("total", DataType.INTEGER)])
    )

    assert derived.relations == ()
    assert derived.resolve("total") == 1
    with pytest.raises(InvalidTypeError):
        students_layout.derive(STUDENTS.columns)


def test_layout_equality_hashing_and_repr_expose_origins(students_layout):
    assert RowLayout(STUDENTS, relation="students") == students_layout
    assert RowLayout(STUDENTS) != students_layout
    assert students_layout != STUDENTS
    assert hash(RowLayout(STUDENTS, relation="students")) == hash(students_layout)
    assert "students.id" in repr(students_layout)


def test_published_name_requires_a_field_of_this_layout(
    students_layout, enrollments_layout
):
    joined = RowLayout.combine(students_layout, enrollments_layout)

    assert joined.published_name(joined.fields[0]) == "students.id"
    assert joined.published_name(joined.fields[1]) == "name"
    with pytest.raises(ValidationError, match="does not belong"):
        joined.published_name(students_layout.fields[0])
    with pytest.raises(InvalidTypeError):
        joined.published_name("id")


def test_layout_field_validates_its_own_components():
    field = LayoutField(0, "id", DataType.INTEGER, "students")

    assert field.reference == ColumnReference("id", "students")
    with pytest.raises(ValidationError):
        LayoutField(-1, "id", DataType.INTEGER)
    with pytest.raises(InvalidTypeError):
        LayoutField(True, "id", DataType.INTEGER)
    with pytest.raises(InvalidTypeError):
        LayoutField(0, "id", "INTEGER")


def test_a_retained_row_cannot_change_when_its_producer_advances():
    schema = Schema([Column("id", DataType.INTEGER)])
    retained = Record(schema, [1])
    values = retained.values

    later = Record(schema, [2])

    assert retained.values == values == (1,)
    assert later.values == (2,)
    with pytest.raises(AttributeError):
        retained.values = (99,)


def test_record_rejects_a_value_count_that_disagrees_with_its_schema():
    with pytest.raises(ValidationError):
        Record(STUDENTS, [1, "Ana", "CS"])
    with pytest.raises(InvalidTypeError):
        Record(STUDENTS, [1, "Ana", "CS", 22.0])


def test_layout_requires_a_schema_and_a_usable_relation_name():
    with pytest.raises(InvalidTypeError):
        RowLayout(STUDENTS.columns)
    with pytest.raises(ValidationError):
        RowLayout(STUDENTS, relation="  ")
