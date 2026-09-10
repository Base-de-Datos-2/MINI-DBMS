"""Stage 6 operator doubles and schema fixtures shared across test modules."""

from engine.catalog import Column, DataType, Schema
from engine.operators import ExecutionOperator, RowLayout
from engine.storage import Record


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
        Column("id", DataType.INTEGER),
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


def students(rows=STUDENT_ROWS):
    """Build Records for the shared students fixture."""

    return [Record(STUDENTS, list(row)) for row in rows]


class RowSource(ExecutionOperator):
    """Emit a fixed list of rows, recording lifecycle calls for assertions.

    This double exists to exercise the lifecycle without a file: it is not a
    storage organization and never claims an ordering it does not have.
    """

    __slots__ = ("_rows", "_relation", "_position", "opens", "closes", "fail_at")

    def __init__(self, rows, *, relation="rows", fail_at=None, children=()):
        self._rows = tuple(rows)
        self._relation = relation
        self._position = 0
        self.opens = 0
        self.closes = 0
        self.fail_at = fail_at
        super().__init__(children=children)

    def _build_layout(self) -> RowLayout:
        schema = self._rows[0].schema if self._rows else STUDENTS
        return RowLayout(schema, relation=self._relation)

    def _open(self) -> None:
        self.opens += 1
        self._position = 0

    def _next(self):
        if self.fail_at is not None and self._position == self.fail_at:
            raise ValueError("injected row failure")
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        self._statistics.rows_examined += 1
        return row

    def _close(self) -> None:
        self.closes += 1


class FailingOpen(ExecutionOperator):
    """Fail inside ``_open`` to exercise partial-open cleanup."""

    __slots__ = ("closes",)

    def __init__(self, children=()):
        self.closes = 0
        super().__init__(children=children)

    def _build_layout(self) -> RowLayout:
        return RowLayout(STUDENTS, relation="failing")

    def _open(self) -> None:
        raise ValueError("injected open failure")

    def _next(self):
        return None

    def _close(self) -> None:
        self.closes += 1
