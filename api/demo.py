"""Deterministic demonstration data and the verified presentation presets.

The database combines two fixtures:

* ``students`` and ``enrollments`` are exactly the Stage 7 acceptance fixture
  (ETAPA_09.md Section 10). Their answers are known by hand, and they include
  duplicate values, a no-match condition, a join and grouped output.
* ``students_big``, ``courses`` and ``enrollments_big`` are a modest seeded
  fixture, large enough that sorting, grouping and joining really spill to disk
  under :data:`DEMO_MEMORY_BUDGET_BYTES`. It is the only evidence of external
  execution; the four-row fixture proves correctness, not disk spilling.

No hash index is declared on the larger tables: reopening a hash index verifies
its coverage row by row, which made startup slow, and the join column is left
unindexed on purpose so the planner's default route is Grace hash join.
"""

from __future__ import annotations

from dataclasses import dataclass
import random

from engine.catalog import Column, DataType, IndexType, Schema

from .database import (
    HEAP,
    SEQUENTIAL,
    DatabaseDefinition,
    IndexDefinition,
    TableDefinition,
)


#: Accounted working memory per query. Modest, so the larger fixture exceeds it
#: and every blocking operator visibly spills, yet enough for three nested
#: blocking operators (sort over group over a Grace join) to receive their
#: minimum grants. 128 KiB was measured too small for that plan.
DEMO_MEMORY_BUDGET_BYTES = 192 * 1024

#: File created by the setup script; only a directory holding it may be reset.
DEMO_MARKER = ".minidbms-demo"

STUDENTS = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
    Column("career", DataType.VARCHAR),
    Column("age", DataType.INTEGER),
])
ENROLLMENTS = Schema([
    Column("student_id", DataType.INTEGER),
    Column("course", DataType.VARCHAR),
])
COURSES = Schema([
    Column("code", DataType.VARCHAR),
    Column("title", DataType.VARCHAR),
    Column("credits", DataType.INTEGER),
])
ENROLLMENTS_BIG = Schema([
    Column("id", DataType.INTEGER),
    Column("student_id", DataType.INTEGER),
    Column("course_code", DataType.VARCHAR),
    Column("grade", DataType.INTEGER),
])

#: The Stage 7 acceptance rows, verbatim.
STUDENT_ROWS = (
    (1, "Ana", "CS", 22),
    (2, "Luis", "EE", 19),
    (3, "Sol", "CS", 24),
    (4, "Omar", "EE", 23),
)
ENROLLMENT_ROWS = ((1, "DB2"), (1, "OS"), (3, "DB2"), (4, "OS"))

CAREERS = ("CS", "EE", "ME", "CE", "MA", "PH", "BI", "EC")
FIRST_NAMES = (
    "Ana", "Luis", "Sol", "Omar", "Lucía", "Diego", "Valeria", "Mateo",
    "Camila", "Joaquín", "Renata", "Andrés", "Paula", "Iván", "Elena", "Tomás",
)
LAST_NAMES = (
    "Quispe", "Mamani", "Flores", "Rojas", "Torres", "Huamán", "Vargas",
    "Castillo", "Ramos", "Chávez", "Medina", "Paredes",
)
SUBJECTS = (
    ("BD1", "Bases de Datos I", 4), ("BD2", "Bases de Datos II", 4),
    ("ALG", "Algoritmos", 5), ("EDA", "Estructuras de Datos", 5),
    ("SO", "Sistemas Operativos", 4), ("RED", "Redes", 3),
    ("CAL1", "Cálculo I", 5), ("CAL2", "Cálculo II", 5),
    ("FIS1", "Física I", 4), ("FIS2", "Física II", 4),
    ("EST", "Estadística", 3), ("IA", "Inteligencia Artificial", 4),
    ("COMP", "Compiladores", 4), ("GRAF", "Computación Gráfica", 3),
    ("ING", "Ingeniería de Software", 4), ("ETI", "Ética Profesional", 2),
)


def big_students(count: int = 1000, seed: int = 2026):
    """Seeded rows of ``students_big``; the same seed always yields them."""

    rng = random.Random(seed)
    for student_id in range(1, count + 1):
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        yield (student_id, name, rng.choice(CAREERS), rng.randrange(17, 35))


def big_enrollments(count: int = 3000, students: int = 1000, seed: int = 2027):
    """Seeded rows of ``enrollments_big``."""

    rng = random.Random(seed)
    for enrollment_id in range(1, count + 1):
        yield (
            enrollment_id,
            rng.randrange(1, students + 1),
            rng.choice(SUBJECTS)[0],
            rng.randrange(0, 21),
        )


def demo_database(*, big_students_count: int = 1000,
                  big_enrollments_count: int = 3000) -> DatabaseDefinition:
    """Return the declared demonstration database."""

    return DatabaseDefinition(
        name="demo",
        tables=(
            TableDefinition(
                name="students",
                schema=STUDENTS,
                organization=HEAP,
                indexes=(
                    IndexDefinition(
                        "students_id_hash", "id", IndexType.EXTENDIBLE_HASH,
                        unique=True,
                    ),
                    IndexDefinition("students_age_bplus", "age", IndexType.BPLUS),
                ),
                rows=lambda: STUDENT_ROWS,
            ),
            TableDefinition(
                name="enrollments",
                schema=ENROLLMENTS,
                organization=HEAP,
                rows=lambda: ENROLLMENT_ROWS,
            ),
            TableDefinition(
                name="students_big",
                schema=STUDENTS,
                organization=HEAP,
                indexes=(
                    IndexDefinition("students_big_age_bplus", "age", IndexType.BPLUS),
                ),
                rows=lambda: big_students(big_students_count),
            ),
            TableDefinition(
                name="courses",
                schema=COURSES,
                organization=SEQUENTIAL,
                key_column="code",
                indexes=(
                    IndexDefinition(
                        "courses_code_bplus", "code", IndexType.BPLUS,
                        unique=True, clustered=True,
                    ),
                ),
                rows=lambda: SUBJECTS,
            ),
            TableDefinition(
                name="enrollments_big",
                schema=ENROLLMENTS_BIG,
                organization=HEAP,
                rows=lambda: big_enrollments(
                    big_enrollments_count, big_students_count
                ),
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class Preset:
    """One presentation query. ``expected`` is for tests and docs, never the UI."""

    label: str
    purpose: str
    sql: str
    expected: tuple | str | None = None
    ordered: bool = True


#: Verified presentation presets. Selecting one only fills the editor; running
#: it always goes through POST /api/query like any typed statement.
PRESETS = (
    Preset(
        "Filtro y ORDER BY",
        "Filtra por edad y ordena por nombre.",
        "SELECT name FROM students WHERE age > 20 ORDER BY name;",
        (("Ana",), ("Omar",), ("Sol",)),
    ),
    Preset(
        "Igualdad por clave",
        "Búsqueda exacta por id; el planner puede usar el índice hash.",
        "SELECT * FROM students WHERE id = 3;",
        ((3, "Sol", "CS", 24),),
    ),
    Preset(
        "Rango",
        "Rango de edades; el planner puede usar el índice B+.",
        "SELECT name FROM students WHERE age >= 22 AND age < 24;",
        (("Ana",), ("Omar",)),
        ordered=False,
    ),
    Preset(
        "GROUP BY",
        "Cuenta estudiantes por carrera (valores repetidos).",
        "SELECT career, COUNT(*) AS total FROM students GROUP BY career ORDER BY career;",
        (("CS", 2), ("EE", 2)),
    ),
    Preset(
        "JOIN",
        "Une estudiantes con sus matrículas.",
        "SELECT s.name, e.course FROM students AS s JOIN enrollments AS e "
        "ON s.id = e.student_id WHERE s.age > 20 ORDER BY s.name;",
        (("Ana", "DB2"), ("Ana", "OS"), ("Omar", "OS"), ("Sol", "DB2")),
        ordered=False,
    ),
    Preset(
        "Sin coincidencias",
        "Una condición que ninguna fila cumple: resultado vacío, no error.",
        "SELECT name FROM students WHERE age > 100;",
        (),
    ),
    Preset(
        "Error semántico",
        "Columna inexistente: el motor responde con un error útil.",
        "SELECT unknown_column FROM students;",
        "SQL_ERROR",
    ),
    Preset(
        "Error de sintaxis",
        "Palabra clave mal escrita: el error indica línea y columna.",
        "SELEC name FROM students;",
        "SQL_ERROR",
    ),
    Preset(
        "ORDER BY con disco",
        "3000 filas ordenadas con ordenamiento externo (runs en disco).",
        "SELECT id, student_id, grade FROM enrollments_big ORDER BY grade DESC, id;",
    ),
    Preset(
        "JOIN + GROUP BY con disco",
        "Grace hash join y agrupación externa sobre el fixture mayor.",
        "SELECT s.career, COUNT(*) AS inscripciones, AVG(e.grade) AS promedio "
        "FROM students_big s JOIN enrollments_big e ON s.id = e.student_id "
        "GROUP BY s.career ORDER BY s.career;",
    ),
    Preset(
        "Rango en tabla mayor",
        "Rango sobre 1000 filas con el índice B+ de edad.",
        "SELECT id, name, age FROM students_big WHERE age >= 30 AND age <= 31 ORDER BY id;",
    ),
)
