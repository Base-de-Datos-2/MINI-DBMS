"""Execution-row identity, provenance, and derived output schemas."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from engine.catalog import Column, DataType, Schema
from engine.errors import (
    InvalidTypeError,
    UnknownColumnError,
    ValidationError,
)
from engine.storage.rid import RID


QUALIFIER_SEPARATOR = "."


def validate_identifier(value: object, label: str) -> str:
    """Apply the exact-name policy already used by Column and TableMetadata."""

    if not isinstance(value, str):
        raise InvalidTypeError(f"{label} must be a string")
    if not value.strip():
        raise ValidationError(f"{label} must not be empty or whitespace-only")
    return value


@dataclass(frozen=True, slots=True)
class RowProvenance:
    """One base-table origin of an execution row.

    A RID is only meaningful together with the relation that produced it, so
    the pair always travels as a unit. Rows produced by aggregation carry no
    provenance at all rather than a fabricated base RID.
    """

    relation: str
    rid: RID

    def __post_init__(self) -> None:
        validate_identifier(self.relation, "Provenance relation")
        if not isinstance(self.rid, RID):
            raise InvalidTypeError("Provenance rid must be a RID")


@dataclass(frozen=True, slots=True)
class ColumnReference:
    """A column selected by exact name, optionally qualified by relation."""

    name: str
    relation: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.name, "Column reference name")
        if self.relation is not None:
            validate_identifier(self.relation, "Column reference relation")

    @property
    def qualified_name(self) -> str:
        """Return ``relation.name`` when qualified, otherwise the bare name."""

        if self.relation is None:
            return self.name
        return f"{self.relation}{QUALIFIER_SEPARATOR}{self.name}"


def as_reference(value: object) -> ColumnReference:
    """Accept a ColumnReference or a bare column name, rejecting anything else."""

    if isinstance(value, ColumnReference):
        return value
    if isinstance(value, str):
        return ColumnReference(value)
    raise InvalidTypeError("Column selector must be a ColumnReference or a name")


@dataclass(frozen=True, slots=True)
class LayoutField:
    """One output position together with the origin of its value.

    ``name`` and ``relation`` describe where the value came from, which is not
    always how the layout publishes it: a join that has to disambiguate two
    ``id`` columns changes the published schema name while the origin stays
    intact, so a qualified reference keeps resolving.
    """

    position: int
    name: str
    data_type: DataType
    relation: str | None = None

    def __post_init__(self) -> None:
        if type(self.position) is not int:
            raise InvalidTypeError("Layout field position must be an int")
        if self.position < 0:
            raise ValidationError("Layout field position must be non-negative")
        validate_identifier(self.name, "Layout field name")
        if not isinstance(self.data_type, DataType):
            raise InvalidTypeError("Layout field data_type must be a DataType")
        if self.relation is not None:
            validate_identifier(self.relation, "Layout field relation")

    @property
    def reference(self) -> ColumnReference:
        """Return the fully qualified reference that always resolves here."""

        return ColumnReference(self.name, self.relation)


class RowLayout:
    """Bind qualified column identity to the positions of one output schema.

    A layout is built once per run, before any row is read, so unknown or
    ambiguous references fail during ``open`` instead of mid-stream. The
    schema is the public output contract, while ``fields`` records where each
    position came from: that separation is what lets two joined relations each
    contribute a column named ``id`` without colliding.

    Layouts are immutable. Derived layouts are produced by ``combine``,
    ``project`` and ``derive`` rather than by mutating an existing one.
    """

    __slots__ = ("_schema", "_fields")

    def __init__(self, schema: Schema, *, relation: str | None = None) -> None:
        if not isinstance(schema, Schema):
            raise InvalidTypeError("Row layout requires a Schema")
        if relation is not None:
            validate_identifier(relation, "Row layout relation")
        fields = tuple(
            LayoutField(position, column.name, column.data_type, relation)
            for position, column in enumerate(schema)
        )
        self._schema = schema
        self._fields = fields

    @classmethod
    def _build(
        cls,
        fields: Sequence[LayoutField],
        names: Sequence[str],
    ) -> "RowLayout":
        """Assemble a layout from field origins and their published names."""

        ordered = tuple(fields)
        published = tuple(names)
        schema = Schema(
            [
                Column(name, field.data_type)
                for name, field in zip(published, ordered)
            ]
        )
        layout = cls.__new__(cls)
        layout._schema = schema
        layout._fields = ordered
        return layout

    @property
    def schema(self) -> Schema:
        """Return the output schema every emitted row must satisfy."""

        return self._schema

    @property
    def fields(self) -> tuple[LayoutField, ...]:
        """Return the output fields in position order."""

        return self._fields

    @property
    def relations(self) -> tuple[str, ...]:
        """Return the distinct contributing relations, in first-seen order."""

        seen: list[str] = []
        for field in self._fields:
            if field.relation is not None and field.relation not in seen:
                seen.append(field.relation)
        return tuple(seen)

    def published_name(self, field: LayoutField) -> str:
        """Return the output-schema name a field of this layout is published as."""

        if not isinstance(field, LayoutField):
            raise InvalidTypeError("published_name requires a LayoutField")
        if field is not self._fields[field.position]:
            raise ValidationError("LayoutField does not belong to this layout")
        return self._schema.columns[field.position].name

    def __len__(self) -> int:
        """Return the number of output columns."""

        return len(self._fields)

    def __iter__(self) -> Iterator[LayoutField]:
        """Iterate over output fields in position order."""

        return iter(self._fields)

    def __eq__(self, other: object) -> bool:
        """Compare the output schema and every field origin."""

        if not isinstance(other, RowLayout):
            return NotImplemented
        return self._schema == other._schema and self._fields == other._fields

    def __hash__(self) -> int:
        """Hash the immutable schema and field origins."""

        return hash((self._schema, self._fields))

    def __repr__(self) -> str:
        """Show the qualified identity of every output position."""

        names = ", ".join(
            column.name
            if column.name == field.reference.qualified_name
            else f"{column.name}<-{field.reference.qualified_name}"
            for column, field in zip(self._schema, self._fields)
        )
        return f"RowLayout({names})"

    def field(self, selector: object) -> LayoutField:
        """Resolve a reference or bare name to exactly one output field.

        A qualified reference matches on both relation and column name. A bare
        name matches every field with that column name; more than one match is
        ambiguous and raises ValidationError instead of silently choosing one.
        A bare name that matches no origin falls back to the output schema
        name, which is how a caller addresses a column the layout had to
        qualify after a join.
        """

        reference = as_reference(selector)
        if reference.relation is not None:
            matches = [
                field
                for field in self._fields
                if field.relation == reference.relation
                and field.name == reference.name
            ]
        else:
            matches = [
                field for field in self._fields if field.name == reference.name
            ]
            if not matches:
                matches = [
                    field
                    for field, column in zip(self._fields, self._schema)
                    if column.name == reference.name
                ]
        if not matches:
            raise UnknownColumnError(
                f"Unknown column: {reference.qualified_name!r}"
            )
        if len(matches) > 1:
            origins = ", ".join(
                repr(field.reference.qualified_name) for field in matches
            )
            raise ValidationError(
                f"Ambiguous column {reference.qualified_name!r}; "
                f"qualify it as one of: {origins}"
            )
        return matches[0]

    def resolve(self, selector: object) -> int:
        """Return the row position a reference or bare name binds to."""

        return self.field(selector).position

    def data_type(self, selector: object) -> DataType:
        """Return the declared type of the referenced column."""

        return self.field(selector).data_type

    @classmethod
    def combine(cls, left: "RowLayout", right: "RowLayout") -> "RowLayout":
        """Concatenate two layouts, qualifying names only where they collide.

        Joined rows are wider than either base record. A column name present on
        both sides keeps its origin and is published as ``relation.name``; an
        unqualified collision cannot be published unambiguously and is rejected
        so the plan can supply an alias instead.
        """

        for layout in (left, right):
            if not isinstance(layout, RowLayout):
                raise InvalidTypeError("Row layouts can only combine with layouts")
        sources = left._fields + right._fields
        occurrences = Counter(field.name for field in sources)
        fields: list[LayoutField] = []
        names: list[str] = []
        for position, field in enumerate(sources):
            if occurrences[field.name] == 1:
                names.append(field.name)
            elif field.relation is None:
                raise ValidationError(
                    f"Column {field.name!r} appears on both join inputs without a "
                    "relation to qualify it; alias it before joining"
                )
            else:
                names.append(field.reference.qualified_name)
            fields.append(
                LayoutField(position, field.name, field.data_type, field.relation)
            )
        repeated = Counter(names)
        duplicated = sorted(name for name, count in repeated.items() if count > 1)
        if duplicated:
            raise ValidationError(
                "Join inputs publish the same qualified column twice: "
                + ", ".join(repr(name) for name in duplicated)
            )
        return cls._build(fields, names)

    def project(
        self,
        selections: Sequence[object],
        aliases: Sequence[str | None] | None = None,
    ) -> "RowLayout":
        """Return the layout produced by selecting columns in the given order.

        An alias renames the output column and drops its relation, because the
        renamed column no longer denotes the same base column. Selecting the
        same column twice is legal only when the repeats are aliased apart.
        """

        if isinstance(selections, (str, bytes, bytearray)) or not isinstance(
            selections, Sequence
        ):
            raise InvalidTypeError("Projection selections must be a sequence")
        chosen = tuple(selections)
        if aliases is None:
            labels: tuple[str | None, ...] = (None,) * len(chosen)
        else:
            if isinstance(aliases, (str, bytes, bytearray)) or not isinstance(
                aliases, Sequence
            ):
                raise InvalidTypeError("Projection aliases must be a sequence")
            labels = tuple(aliases)
            if len(labels) != len(chosen):
                raise ValidationError(
                    "Projection requires one alias entry per selected column"
                )
        fields: list[LayoutField] = []
        names: list[str] = []
        for position, (selector, alias) in enumerate(zip(chosen, labels)):
            source = self.field(selector)
            if alias is None:
                fields.append(
                    LayoutField(
                        position, source.name, source.data_type, source.relation
                    )
                )
                names.append(self.published_name(source))
                continue
            validate_identifier(alias, "Projection alias")
            fields.append(LayoutField(position, alias, source.data_type))
            names.append(alias)
        repeated = Counter(names)
        duplicated = sorted(name for name, count in repeated.items() if count > 1)
        if duplicated:
            raise ValidationError(
                "Projection would publish the same output name twice: "
                + ", ".join(repr(name) for name in duplicated)
            )
        return RowLayout._build(fields, names)

    def derive(self, schema: Schema) -> "RowLayout":
        """Return a layout for rows this operator computes rather than reads.

        Grouped and aggregated rows have a derived identity: they keep their
        own schema but no base relation, so a later reference cannot pretend
        the value still belongs to a stored column.
        """

        if not isinstance(schema, Schema):
            raise InvalidTypeError("Derived layout requires a Schema")
        return RowLayout(schema)

    def positions(self, selectors: Sequence[object]) -> tuple[int, ...]:
        """Resolve several selectors at once, preserving their given order."""

        if isinstance(selectors, (str, bytes, bytearray)) or not isinstance(
            selectors, Sequence
        ):
            raise InvalidTypeError("Column selectors must be a sequence")
        return tuple(self.resolve(selector) for selector in selectors)
