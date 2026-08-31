# ETAPA_01.md

## Etapa 1 — Arquitectura y modelo de datos

**Parte:** Base de Datos Relacional  
**Dependencias:** ninguna  
**Siguiente etapa:** Etapa 2 — Páginas, registros y persistencia

---

# 1. Propósito

La Etapa 1 establece los contratos y estructuras conceptuales sobre los que se construirá todo el MiniDBMS.

En esta etapa **no se busca almacenar todavía registros completos en páginas binarias**.

El objetivo es conseguir que el sistema pueda representar de manera clara:

- tipos;
- columnas;
- esquemas;
- registros;
- identificadores físicos;
- metadata de tablas;
- catálogo;
- contratos de almacenamiento;
- contratos de índices;
- contratos de operadores.

La Etapa 1 debe reducir la probabilidad de que etapas posteriores tengan que redefinir conceptos fundamentales.

---

# 2. Resultado esperado

Al terminar esta etapa debería ser posible escribir código conceptual similar a:

```python
schema = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
    Column("age", DataType.INTEGER),
])

record = Record(schema, [1, "Ana", 21])

table = TableMetadata(
    name="students",
    schema=schema,
)
```

y:

```python
catalog.register_table(table)

catalog.get_table("students")
```

También debe existir un tipo:

```python
RID(page_id=4, slot_id=2)
```

aunque todavía no exista un Heap File real que lo produzca.

---

# 3. Fuentes que Codex debe leer antes de implementar

Antes de tocar código:

1. `AGENTS.md`
2. `REQUIREMENTS.md`
3. `PROJECT_CONTEXT.md`
4. `PLAN.md`
5. `ETAPA_01.md`
6. repositorio existente

Codex debe inspeccionar primero si ya existen clases equivalentes.

No crear duplicados como:

```text
Schema
TableSchema
RelationSchema
```

si todos representan el mismo concepto.

---

# 4. Alcance de la Etapa 1

## Incluye

```text
DataType
Column
Schema
Record
RID
TableMetadata
IndexMetadata (metadata solamente)
Catalog
Storage interface
Index interface
Operator interface
errores base
tests
```

## No incluye

```text
Page binaria
PageManager real
HeapFile
PagedSequentialFile
B+ Tree
ExtendibleHash
SQL parser
Planner
Executor
Transactions
FastAPI
React
Benchmarks
```

Si alguna de esas piezas ya existe en el repositorio, conservarla.

No extenderla innecesariamente durante esta etapa.

---

# 5. Estructura objetivo inicial

Una posible organización:

```text
engine/
├── __init__.py
│
├── catalog/
│   ├── __init__.py
│   ├── types.py
│   ├── schema.py
│   ├── metadata.py
│   └── catalog.py
│
├── storage/
│   ├── __init__.py
│   ├── rid.py
│   ├── record.py
│   └── base.py
│
├── indexes/
│   ├── __init__.py
│   └── base.py
│
└── operators/
    ├── __init__.py
    └── base.py

tests/
├── catalog/
├── storage/
├── indexes/
└── operators/
```

Esta estructura es orientativa.

Si el repositorio ya usa otra organización coherente, no migrarla solamente para hacer coincidir los nombres de este documento.

---

# 6. Tarea 1.1 — Inspeccionar el repositorio

## Objetivo

Determinar el estado real antes de implementar.

## Acciones

Codex debe:

- listar la estructura relevante;
- buscar clases existentes relacionadas con:
  - schema;
  - record;
  - table;
  - RID;
  - catalog;
  - storage;
  - indexes;
  - operators;
- revisar tests;
- identificar código que pueda reutilizarse;
- detectar decisiones ya tomadas.

## Salida esperada

Un reporte breve:

```text
Existing:
- ...

Missing:
- ...

Potential conflicts:
- ...

Recommended implementation order:
- ...
```

## Restricción

No modificar código todavía.

---

# 7. Tarea 1.2 — Crear/normalizar `DataType`

## Objetivo

Representar los tipos básicos usados por los esquemas.

## Tipos iniciales recomendados

```text
INTEGER
FLOAT
BOOLEAN
VARCHAR
```

Estos tipos son una decisión inicial del proyecto, no una exigencia literal del documento oficial.

## Posible interfaz

```python
from enum import Enum

class DataType(Enum):
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    VARCHAR = "VARCHAR"
```

No es obligatorio copiar esta implementación.

## Requisitos

- comparación clara;
- serializable posteriormente;
- no depender de Lark;
- no depender de FastAPI;
- no depender de React.

## Tests

```text
test_integer_type_exists
test_float_type_exists
test_boolean_type_exists
test_varchar_type_exists
```

Si se implementa parsing desde texto:

```text
test_datatype_from_string
test_invalid_datatype
```

## Definition of Done

`DataType` puede ser usado por `Column` y `Schema`.

---

# 8. Tarea 1.3 — Implementar `Column`

## Objetivo

Representar metadata de una columna.

## Campos mínimos recomendados

```text
name
data_type
```

Campos futuros posibles:

```text
nullable
length
primary_key
```

Pero no agregarlos si todavía no son necesarios.

Evitar diseñar un sistema completo de constraints en esta etapa.

## Posible uso

```python
Column(
    name="id",
    data_type=DataType.INTEGER,
)
```

## Validaciones mínimas

- nombre no vacío;
- tipo válido.

## Tests

```text
test_create_column
test_column_rejects_empty_name
test_column_has_type
```

---

# 9. Tarea 1.4 — Implementar `Schema`

## Objetivo

Representar el conjunto ordenado de columnas de una tabla.

## Capacidades mínimas

```text
columns
len(schema)
get column by name
get column by position
detect duplicate names
```

## Ejemplo

```python
schema = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
])
```

## Comportamiento recomendado

```python
schema.column("id")
```

debe devolver la metadata correspondiente.

Puede existir:

```python
schema.index_of("id")
```

para ayudar a operadores futuros.

## Validaciones

- no aceptar columnas duplicadas;
- preservar orden;
- nombres consistentes.

Definir si los nombres son case-sensitive.

Si todavía no se ha decidido, no introducir normalización silenciosa.

## Tests

```text
test_schema_preserves_column_order
test_schema_get_column_by_name
test_schema_get_column_by_index
test_schema_rejects_duplicate_names
test_schema_unknown_column
```

---

# 10. Tarea 1.5 — Implementar `RID`

## Objetivo

Representar la dirección física lógica de un registro.

Diseño conceptual:

```text
RID(page_id, slot_id)
```

## Propiedades recomendadas

- inmutable;
- comparable;
- hashable;
- validable.

Ejemplo posible:

```python
@dataclass(frozen=True)
class RID:
    page_id: int
    slot_id: int
```

## Validaciones

Recomendación:

```text
page_id >= 0
slot_id >= 0
```

Si se necesita un valor sentinel en etapas futuras, documentarlo antes de cambiar esta regla.

## Tests

```text
test_create_rid
test_rid_equality
test_rid_hashable
test_rid_rejects_negative_page
test_rid_rejects_negative_slot
```

## Importancia futura

El RID será utilizado especialmente por:

```text
HeapFile
B+ unclustered
Extendible Hashing
IndexScan
```

---

# 11. Tarea 1.6 — Implementar `Record`

## Objetivo

Representar una fila relacional.

El Record no debe conocer detalles de:

- Page;
- HeapFile;
- B+;
- SQL;
- HTTP.

## Diseño recomendado

El Record debe mantener:

```text
schema
values
```

o una representación equivalente.

Ejemplo:

```python
Record(
    schema=schema,
    values=[1, "Ana", 21],
)
```

## Validaciones

Debe verificarse:

```text
len(values) == len(schema.columns)
```

Idealmente también:

```text
valor compatible con DataType
```

pero esta validación puede mantenerse simple en la primera versión.

## Compatibilidad de tipos

Ejemplo conceptual:

```text
INTEGER -> int
FLOAT   -> float/int según política
BOOLEAN -> bool
VARCHAR -> str
```

La coerción automática agresiva debe evitarse.

Por ejemplo:

```text
"123"
```

no debería convertirse silenciosamente a:

```text
123
```

sin una regla explícita.

## Acceso

Recomendación:

```python
record["name"]
```

o:

```python
record.get("name")
```

No es obligatorio implementar ambas.

## Tests

```text
test_create_record
test_record_rejects_wrong_value_count
test_record_access_by_column
test_record_preserves_schema
test_record_type_validation
```

---

# 12. Tarea 1.7 — Metadata de tabla

## Objetivo

Representar una tabla sin implementar todavía su almacenamiento físico.

## Tipo recomendado

```text
TableMetadata
```

Campos mínimos:

```text
name
schema
```

Campos que podrán aparecer después:

```text
storage_type
file_path
primary_key
indexes
```

No introducir todos desde el principio si todavía no se usan.

## Ejemplo

```python
TableMetadata(
    name="students",
    schema=student_schema,
)
```

## Tests

```text
test_create_table_metadata
test_table_has_schema
test_table_rejects_empty_name
```

---

# 13. Tarea 1.8 — Metadata de índices

## Objetivo

Preparar el catálogo para registrar índices sin implementar todavía B+ o Hash.

Posible estructura:

```text
IndexMetadata
```

Campos posibles:

```text
name
table_name
column_name
index_type
clustered
```

Pero esta tarea debe mantenerse minimalista.

## Tipos futuros

```text
BPLUS
EXTENDIBLE_HASH
```

No crear nodos B+ ni buckets todavía.

## Tests

```text
test_create_index_metadata
test_index_references_table
test_index_references_column
```

---

# 14. Tarea 1.9 — Implementar `Catalog`

## Objetivo

Mantener metadata de tablas e índices.

El catálogo de esta etapa puede ser in-memory.

La persistencia del catálogo puede diseñarse en una etapa posterior si no existe todavía una decisión oficial.

## Operaciones mínimas

```text
register_table(table)
get_table(name)
has_table(name)
list_tables()
drop/unregister table (opcional en esta etapa)
```

Para índices:

```text
register_index(index)
get_indexes(table)
```

si `IndexMetadata` se incluye en la primera versión.

## Validaciones

- no permitir tabla duplicada;
- no devolver metadata mutable accidentalmente si esto rompe invariantes;
- comprobar referencias básicas de índices.

## Tests

```text
test_register_table
test_get_table
test_list_tables
test_reject_duplicate_table
test_unknown_table
test_register_index
test_index_requires_existing_table
```

---

# 15. Tarea 1.10 — Definir contratos abstractos

Esta es la última pieza importante de la Etapa 1.

No deben contener implementación real de algoritmos posteriores.

## 15A. Storage interface

### Objetivo

Permitir que Heap File y otras organizaciones tengan una interfaz común.

Conceptualmente:

```python
class Storage:
    def insert(self, record) -> RID: ...
    def read(self, rid) -> Record: ...
    def delete(self, rid) -> None: ...
    def scan(self): ...
```

Puede utilizarse:

```text
ABC
Protocol
duck typing
```

según el estilo del repositorio.

### No debe

- abrir archivos reales todavía;
- crear páginas;
- implementar Heap File.

## 15B. Index interface

Conceptualmente:

```python
class Index:
    def insert(self, key, rid): ...
    def search(self, key): ...
    def delete(self, key, rid): ...
```

Range search puede pertenecer:

- a una interfaz especializada;
- o al contrato B+ posterior.

No obligar a Extendible Hashing a fingir que soporta rangos.

Una separación válida:

```text
Index
└── OrderedIndex
```

donde:

```text
OrderedIndex.range_search(...)
```

## 15C. Operator interface

Conceptualmente:

```text
open()
next()
close()
```

o:

```python
__iter__()
```

No implementar TableScan todavía.

## Tests

Para interfaces puras puede no ser necesario testear comportamiento, pero sí comprobar:

- estructura;
- clases dummy;
- que implementaciones incompletas sean detectables si se usa ABC.

---

# 16. Tarea 1.11 — Errores base

Crear errores solamente cuando aporten claridad.

Ejemplos:

```text
DatabaseError
CatalogError
SchemaError
UnknownTableError
DuplicateTableError
UnknownColumnError
```

No crear una jerarquía enorme.

El objetivo es evitar excepciones genéricas como:

```text
Exception("bad")
```

en módulos centrales.

---

# 17. Tarea 1.12 — Test de integración de la Etapa 1

Crear por lo menos un test que conecte los componentes.

Ejemplo conceptual:

```python
def test_catalog_schema_record_integration():
    schema = Schema([
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
    ])

    table = TableMetadata("students", schema)

    catalog = Catalog()
    catalog.register_table(table)

    record = Record(schema, [1, "Ana"])

    assert catalog.get_table("students").schema == schema
    assert record["name"] == "Ana"
```

Este test no debe tocar disco todavía.

---

# 18. Orden recomendado de implementación

```text
1.1 Inspect repository
        |
        v
1.2 DataType
        |
        v
1.3 Column
        |
        v
1.4 Schema
        |
        +--------------+
        |              |
        v              v
1.5 RID           1.6 Record
        |              |
        +------+-------+
               |
               v
        1.7 TableMetadata
               |
               v
        1.8 IndexMetadata
               |
               v
        1.9 Catalog
               |
               v
        1.10 Interfaces
               |
               v
        1.11 Errors
               |
               v
        1.12 Integration test
```

Algunas tareas pueden implementarse juntas si el cambio sigue siendo pequeño.

---

# 19. Estrategia de commits para esta etapa

Ejemplo:

```text
docs: add part 1 implementation plan

feat(catalog): add relational data types and columns

feat(catalog): add schema representation

feat(storage): add record identifier

feat(storage): add record model

feat(catalog): add table metadata and catalog

feat(core): add storage and index contracts

test(stage1): add architecture model integration tests
```

No es obligatorio usar exactamente estos commits.

La idea es mantener cambios revisables.

---

# 20. Comandos de validación

Si se usa pytest:

```bash
pytest
```

Durante desarrollo:

```bash
pytest tests/catalog -q
pytest tests/storage -q
pytest tests/indexes -q
```

Al terminar:

```bash
pytest -q
```

También se recomienda:

```bash
python -m compileall engine
```

si resulta útil para detectar errores de sintaxis/import.

No añadir linters o formatters nuevos sin necesidad si el repositorio no los usa.

---

# 21. Definition of Done de la Etapa 1

La Etapa 1 está completa solamente si:

## Arquitectura

```text
[ ] existe una estructura modular razonable
[ ] no se introdujeron dependencias frontend -> storage
[ ] no se introdujeron algoritmos de etapas futuras
```

## Modelo de datos

```text
[ ] DataType
[ ] Column
[ ] Schema
[ ] Record
[ ] RID
```

## Metadata

```text
[ ] TableMetadata
[ ] Catalog
[ ] metadata de índices si fue incluida
```

## Contratos

```text
[ ] Storage interface
[ ] Index interface
[ ] Operator interface
```

## Calidad

```text
[ ] tests unitarios
[ ] test de integración
[ ] todos los tests relevantes pasan
[ ] no hay código duplicado equivalente
[ ] documentación actualizada
```

---

# 22. Qué NO debe hacerse para declarar la etapa completa

No es necesario:

```text
[ ] guardar páginas binarias
[ ] crear Heap File
[ ] implementar B+
[ ] implementar Extendible Hash
[ ] aceptar SELECT
[ ] crear FastAPI
[ ] crear React
```

Hacer cualquiera de estas cosas no compensa una base conceptual incompleta.

---

# 23. Preguntas que deben resolverse antes de la Etapa 2

Al terminar la Etapa 1, deben quedar identificadas explícitamente estas decisiones:

## 23.1 Tamaño de página

Ejemplo posible:

```text
4096 bytes
```

pero todavía debe aprobarse/documentarse.

## 23.2 Layout de Page

Por ejemplo:

```text
PageHeader
SlotDirectory
FreeSpace
Records
```

## 23.3 Longitud de registros

Decidir si la primera versión soportará:

```text
fixed length
variable length
```

o un esquema unificado.

Esto debe ser compatible con los requisitos generales del proyecto y el código previo disponible.

## 23.4 Formato binario

Debe elegirse una estrategia coherente para:

```text
integers
floats
booleans
strings
headers
```

## 23.5 Catálogo persistente

Decidir si:

- se persiste desde la Etapa 2;
- o se mantiene inicialmente separado y se persiste posteriormente.

---

# 24. Prompt recomendado para iniciar la Etapa 1 con Codex

```text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md and ETAPA_01.md.

Then inspect the entire repository, focusing on existing schema, record,
RID, catalog, storage-interface, index-interface and operator-interface code.

Do not modify any files yet.

Report:
1. which Stage 1 requirements already exist;
2. which are missing;
3. any naming or architectural conflicts;
4. which existing code should be reused;
5. a minimal implementation sequence for the missing Stage 1 tasks.

Do not implement Stage 2 or later functionality.
```

---

# 25. Prompt recomendado para comenzar a implementar

Después de revisar el reporte:

```text
Implement only the first missing task from ETAPA_01.md.

Reuse existing compatible code.
Do not implement future-stage functionality.

Add or update the relevant pytest tests.
Run only the relevant tests first and report the result.
```

---

# 26. Condición para pasar a ETAPA 2

Solo pasar a Etapa 2 cuando:

```text
Stage 1 model
      +
Stage 1 contracts
      +
Stage 1 tests
      +
stable imports
      +
documented unresolved decisions
      =
READY FOR STAGE 2
```

La siguiente etapa debe construir sobre estas abstracciones, no reemplazarlas.
