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


#: Part 2 examples over the spatial demo (scripts/setup_lima.py): radius, k-NN
#: and the R-Tree plan. POINT is (latitude, longitude); distances are metres.
SPATIAL_PRESETS = (
    Preset(
        "Radio de 200 m",
        "Puntos a menos de 200 m del centro (haversine); repite sin índices para ver SpatialScan.",
        "SELECT id, nombre FROM tiendas "
        "WHERE distancia(ubicacion, POINT(-12.0464, -77.0428), 'haversine') < 200 ORDER BY id;",
    ),
    Preset(
        "Radio de 5 km (PDF)",
        "Ejemplo del enunciado: la métrica por defecto es haversine.",
        "SELECT id, nombre FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000 ORDER BY id;",
    ),
    Preset(
        "k vecinos más cercanos",
        "Los 3 puntos más cercanos; los empates se resuelven por id.",
        "SELECT id, nombre FROM tiendas "
        "ORDER BY distancia(ubicacion, POINT(-12.0464, -77.0428), 'haversine') LIMIT 3;",
    ),
    Preset(
        "Euclidiana frente a haversine",
        "Misma consulta k-NN con la otra métrica.",
        "SELECT id, nombre FROM tiendas "
        "ORDER BY distancia(ubicacion, POINT(-12.0464, -77.0428), 'euclidean') LIMIT 5;",
    ),
    Preset(
        "Lugares reales de Lima",
        "Los 5 lugares de OpenStreetMap más cercanos, con su distancia en metros.",
        "SELECT nombre, categoria, distancia(ubicacion, POINT(-12.0464, -77.0428)) AS metros "
        "FROM lugares_lima ORDER BY distancia(ubicacion, POINT(-12.0464, -77.0428)) LIMIT 5;",
    ),
    Preset(
        "Radio sobre lugares reales",
        "Lugares de Lima a menos de 200 m del centro.",
        "SELECT nombre, categoria FROM lugares_lima "
        "WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 200 ORDER BY nombre;",
    ),
    Preset(
        "Plan del R-Tree",
        "EXPLAIN ANALYZE muestra nodos visitados, candidatos y filas leídas del Heap.",
        "EXPLAIN ANALYZE SELECT id FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 200;",
    ),
)


#: Part 3 examples (scripts/setup_text.py): both literal queries of the
#: assignment (§2.3) and real ESCI product titles for TF-IDF versus BM25.
TEXT_PRESETS = (
    Preset(
        "Documentos con TF-IDF (PDF)",
        "Primer ejemplo del enunciado: TF-IDF con similitud de coseno.",
        "SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;",
    ),
    Preset(
        "Artículos con BM25 (PDF)",
        "Segundo ejemplo del enunciado, con el score como columna.",
        "SELECT *, SCORE() AS relevancia FROM articulos WHERE MATCH(texto, 'machine learning') "
        "USING BM25 ORDER BY relevancia DESC;",
    ),
    Preset(
        "Productos con BM25",
        "1 000 títulos reales de Amazon (ESCI); desmarca «Usar índices» para ver TextScan.",
        "SELECT id, titulo, SCORE() AS relevancia FROM productos "
        "WHERE MATCH(titulo, 'wireless headphones') USING BM25 ORDER BY relevancia DESC LIMIT 10;",
    ),
    Preset(
        "Consulta larga con BM25",
        "Consulta real del corpus de 7 palabras; compárala con la versión TF-IDF.",
        "SELECT id, titulo, SCORE() AS relevancia FROM productos "
        "WHERE MATCH(titulo, 'black natural hair dye without ammonia or peroxide') "
        "USING BM25 ORDER BY relevancia DESC LIMIT 10;",
    ),
    Preset(
        "Consulta larga con TF-IDF",
        "La misma consulta con TF-IDF + coseno: el orden cambia.",
        "SELECT id, titulo, SCORE() AS relevancia FROM productos "
        "WHERE MATCH(titulo, 'black natural hair dye without ammonia or peroxide') "
        "USING TF_IDF ORDER BY relevancia DESC LIMIT 10;",
    ),
    Preset(
        "Temas del curso",
        "Búsqueda en español sobre los documentos de ejemplo.",
        "SELECT id, contenido, SCORE() AS relevancia FROM documentos "
        "WHERE MATCH(contenido, 'índice para búsqueda por rango') USING BM25 ORDER BY relevancia DESC LIMIT 5;",
    ),
    Preset(
        "Plan con EXPLAIN ANALYZE",
        "Muestra el índice SPIMI, el modelo, los candidatos puntuados y la selección top-k.",
        "EXPLAIN ANALYZE SELECT id, titulo, SCORE() AS relevancia FROM productos "
        "WHERE MATCH(titulo, 'wireless headphones') USING BM25 ORDER BY relevancia DESC LIMIT 10;",
    ),
)


#: Part 4 examples: both literal queries of the assignment (§2.4.3) plus the
#: comparison switches. They only fill the editor; POST /api/query runs them.
MULTIMEDIA_PRESETS = (
    Preset(
        "Imágenes similares (PDF)",
        "Primer ejemplo del enunciado: HNSW con similitud del coseno.",
        "SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=10) USING HNSW WITH METRIC=cosine;",
        None,
    ),
    Preset(
        "Canciones similares (PDF)",
        "Segundo ejemplo del enunciado: IVF con distancia euclidiana (score = −distancia).",
        "SELECT nombre, artista, SIMILARITY_SCORE() AS score FROM canciones "
        "WHERE SIMILAR_TO('audio_query.mp3', k=5) USING IVF WITH METRIC=euclidean ORDER BY score DESC;",
        None,
    ),
    Preset(
        "Canciones con reproductor",
        "Igual que el ejemplo del PDF, proyectando media_key para escuchar cada resultado.",
        "SELECT nombre, artista, media_key, SIMILARITY_SCORE() AS score FROM canciones "
        "WHERE SIMILAR_TO('audio_query.mp3', k=5) USING IVF WITH METRIC=euclidean ORDER BY score DESC;",
        None,
    ),
    Preset(
        "Misma consulta con IVF",
        "Cambia el índice; desmarca «Usar índices» para ver la búsqueda exacta (VectorScan).",
        "SELECT id, nombre, media_key, SIMILARITY_SCORE() AS score FROM imagenes "
        "WHERE SIMILAR_TO('foto_consulta.jpg', k=10) USING IVF WITH METRIC=cosine;",
        None,
    ),
    Preset(
        "Euclidiana frente a coseno",
        "La métrica cambia el orden; el score euclidiano es −distancia.",
        "SELECT id, nombre, media_key, SIMILARITY_SCORE() AS score FROM imagenes "
        "WHERE SIMILAR_TO('foto_consulta.jpg', k=10) USING HNSW WITH METRIC=euclidean;",
        None,
    ),
    Preset(
        "Plan con EXPLAIN ANALYZE",
        "Muestra método, métrica, candidatos evaluados y tiempos de extracción y búsqueda.",
        "EXPLAIN ANALYZE SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=10) "
        "USING HNSW WITH METRIC=cosine;",
        None,
    ),
)
