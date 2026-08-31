# Minigestor de Base de Datos Multimodal

Proyecto académico de **Base de Datos 2 (2026-2)**. El objetivo es implementar
un motor de base de datos propio, comenzando por la Parte 1 relacional.

## Estado actual

**Etapa 1 en desarrollo:** estructura del repositorio, configuración Python,
`DataType`, `Column`, `Schema`, `RID`, `Record`, metadatos de tablas/índices y
`Catalog` en memoria, con pruebas unitarias y de integración del modelo.

Todavía no existen almacenamiento físico, índices físicos, consultas SQL, transacciones,
API ejecutable ni interfaz gráfica. Los directorios correspondientes reservan
su ubicación; no representan funcionalidades implementadas.

## Requisitos e instalación

- Python **3.11 o superior**; los comandos de Windows utilizan Python 3.12.
- `pip` y `venv`.
- Sin dependencias de ejecución del motor en esta etapa; `pytest` es la única
  dependencia directa de pruebas. `setuptools` se utiliza para empaquetar.

Desde la raíz del repositorio, en **Windows / PowerShell**:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

Se invoca el intérprete del entorno explícitamente: no es necesario activar el
entorno ni modificar la política de ejecución de PowerShell. Evita usar un
`python` global que pudiera apuntar a Python 2. Si utilizas otra versión de
Python compatible, ajusta el selector del primer comando.

En **Linux / macOS**, con `python3` de versión 3.11 o superior:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m pytest -q
```

La instalación inicial puede necesitar acceso a Internet para descargar las
dependencias de construcción y pruebas. Una vez instalado el entorno, las
pruebas no necesitan red, servicios externos ni un DBMS instalado.

## Uso del modelo actual

Abre el intérprete del entorno virtual e importa las clases del catálogo:

```python
from engine.catalog import (
    Catalog, Column, DataType, IndexMetadata, IndexType, Schema, TableMetadata,
)
from engine.storage import RID, Record

schema = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
    Column("active", DataType.BOOLEAN),
])

assert len(schema) == 3
assert schema.column("name") == schema.column(1)
assert schema.index_of("active") == 2

catalog = Catalog()
catalog.register_table(TableMetadata("students", schema))
record = Record(catalog.get_table("students").schema, [1, "Ana", True])
rid = RID(page_id=4, slot_id=2)

index = IndexMetadata("idx_students_id", "students", "id", IndexType.BPLUS)
catalog.register_index(index)

assert record["name"] == "Ana"
assert {rid: record}[RID(4, 2)] is record
assert catalog.get_index("idx_students_id") is index
assert catalog.get_indexes("students") == (index,)
```

Este ejemplo trabaja únicamente con registros y metadatos en memoria. No crea
una tabla en disco, no construye un índice B+ ni ejecuta SQL. El RID es un valor
conceptual: todavía no existe un archivo que asigne o valide esa ubicación.

### Reglas del modelo

- `DataType` es un `Enum` con valores textuales estables: `INTEGER`, `FLOAT`,
  `BOOLEAN` y `VARCHAR`. `Column` exige un miembro del enum, no un texto.
- `Column` y `Schema` son inmutables. El esquema conserva una copia de las
  columnas en una tupla, respetando su orden.
- Los nombres son sensibles a mayúsculas/minúsculas y no se normalizan ni
  recortan. Se rechazan nombres vacíos o compuestos únicamente por espacios.
- `Schema` acepta una secuencia de columnas, incluida una secuencia vacía;
  rechaza elementos que no sean `Column` y nombres exactamente duplicados.
- `column(nombre_o_posicion)` accede por nombre exacto o posición entera desde
  cero. No admite posiciones negativas, booleanos ni slices.
- `index_of(nombre)` devuelve la posición; `columns`, `len(schema)` e iteración
  permiten inspeccionar el esquema.
- Se utilizan `TypeError` para tipos de argumento incorrectos, `ValueError`
  para definiciones inválidas, `KeyError` para nombres desconocidos e
  `IndexError` para posiciones fuera de rango. La jerarquía general de errores
  del motor sigue pendiente.

### RID y registros

- `RID(page_id, slot_id)` es inmutable, comparable y utilizable como clave de
  diccionario. Sus componentes deben ser `int` incorporados de Python, no
  booleanos, y no negativos. El orden compara primero página y luego slot.
- Un RID identifica una ubicación dentro de un archivo de almacenamiento; no
  es un identificador global entre tablas. No verifica la existencia de páginas
  ni fija límites binarios de tamaño en esta etapa.
- `Record(schema, values)` requiere un `Schema` y una secuencia con exactamente
  un valor por columna. Copia los valores a una tupla inmutable y permite acceder
  mediante `record["nombre_columna"]`, respetando el nombre exacto.
- La compatibilidad exige tipos incorporados exactos; no se admiten subclases
  personalizadas. No hay conversiones implícitas:

| Tipo de columna | Valor Python admitido | Ejemplos rechazados |
|---|---|---|
| `INTEGER` | `int` | `True`, `1.0`, `"123"` |
| `FLOAT` | `float` | `1`, `True`, `"1.5"` |
| `BOOLEAN` | `bool` | `0`, `1`, `"true"` |
| `VARCHAR` | `str` | `123`, `b"texto"` |

Si se desea guardar un entero en una columna `FLOAT`, el llamador debe convertirlo
explícitamente, por ejemplo con `float(1)`. `None`/SQL `NULL` no está soportado.
No se fijan rangos binarios para `INTEGER`; `FLOAT` admite los valores del tipo
Python, incluidos NaN e infinitos. Su tratamiento en operadores SQL y la
serialización se definirán en etapas posteriores. Un esquema vacío admite un
registro con una secuencia vacía.

### Metadatos y catálogo

- `TableMetadata(name, schema)` es inmutable y solo describe una tabla; no
  contiene registros, rutas de archivos ni configuración física.
- `IndexMetadata(name, table_name, column_name, index_type, clustered=False)`
  es inmutable y describe un índice de una sola columna. `IndexType` admite
  `BPLUS` y `EXTENDIBLE_HASH`. Solo `BPLUS` admite `clustered=True`; esa bandera
  declara la organización futura, pero no implementa agrupamiento físico.
- Los nombres siguen la misma política exacta de `Column`. Los metadatos de un
  índice se pueden construir antes de registrar su tabla; `Catalog` comprueba
  las referencias al registrarlo.
- `Catalog` ofrece `register_table`, `get_table`, `has_table`, `list_tables`,
  `register_index`, `get_index` y `get_indexes(table_name)`.
- Los nombres de tabla son únicos dentro del catálogo. Los nombres de índice
  también son únicos en todo el catálogo, incluso entre tablas distintas; ambos
  grupos de nombres son independientes.
- Se permite como máximo un índice B+ agrupado por tabla. Otros índices con
  nombres distintos pueden coexistir, incluso sobre la misma columna.
- Registrar un índice exige una tabla y columna existentes. Si falla cualquier
  validación, no se reemplazan metadatos ni se reserva el nombre del índice.
- `list_tables()` y `get_indexes()` devuelven tuplas independientes en orden de
  registro. Los elementos son inmutables. Una tabla sin índices devuelve `()`;
  consultar una tabla o índice inexistente genera `KeyError`.
- Cada catálogo tiene su propio estado en memoria. No hay persistencia, gestión
  de filas, eliminación de metadatos ni protección concurrente todavía.

## Organización

```text
engine/
  catalog/       # Tipos, esquemas, metadatos y catálogo en memoria
  storage/       # RID y Record; páginas y archivos aún pendientes
  indexes/       # Reservado: B+ y Extendible Hashing
  operators/     # Reservado: operadores relacionales
  query/         # Reservado: parser, planificador y ejecutor
  transactions/  # Reservado: transacciones y concurrencia
api/             # Paquete reservado; aún sin servidor
frontend/        # Reservado para la interfaz
tests/
  catalog/       # Pruebas del modelo implementado
  storage/       # Pruebas de RID y Record
  indexes/       # Reservado
  operators/     # Reservado
  test_catalog_record_integration.py  # Integración sin acceso a disco
benchmarks/      # Reservado para experimentos
data/            # Reservado para datos
docs/            # Reservado para documentación adicional
```

Los archivos `.gitkeep` conservan en Git los directorios que aún están vacíos.
Los paquetes Python se conservan mediante sus archivos `__init__.py`.

## Arquitectura

El catálogo actual utiliza solamente la biblioteca estándar de Python. No
depende del almacenamiento, del parser, de una API ni de la interfaz gráfica.
`Record` depende de `Schema` y `DataType`; `RID` no depende del catálogo. Ninguno
de estos componentes realiza acceso a disco. Las demás capas se implementarán
progresivamente según el plan.

## Validación

En Windows, desde la raíz:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/catalog -q
.\.venv\Scripts\python.exe -m pytest tests/storage -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q engine api
```

En Linux/macOS, sustituye `.\.venv\Scripts\python.exe` por `.venv/bin/python`.

## Documentos de coordinación y siguiente paso

- [REQUIREMENTS.md](REQUIREMENTS.md): requisitos académicos.
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md): arquitectura y decisiones estables.
- [PLAN.md](PLAN.md): las diez etapas de la Parte 1.
- [ETAPA_01.md](ETAPA_01.md): tareas y criterios de cierre de la etapa vigente.
- [AGENTS.md](AGENTS.md): reglas de trabajo en el repositorio.

La siguiente tarea pendiente es definir los contratos de almacenamiento, índices
y operadores (tarea 1.10 de `ETAPA_01.md`). La Etapa 1 **no está completa**:
faltan esos contratos, los errores de dominio y la revisión final de sus criterios
de cierre. Ya existe una prueba de integración entre esquema, registro,
metadatos y catálogo, que prohíbe acceso a disco durante las operaciones.
