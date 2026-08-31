# Minigestor de Base de Datos Multimodal

Proyecto académico de **Base de Datos 2 (2026-2)**. El objetivo es implementar
un motor de base de datos propio, comenzando por la Parte 1 relacional.

## Estado actual

**Etapa 1 completa y auditada (2026-08-31):** estructura del repositorio, configuración Python,
`DataType`, `Column`, `Schema`, `RID`, `Record`, metadatos de tablas/índices y
`Catalog` en memoria. Ya existen los contratos abstractos de almacenamiento,
índices y operadores, y errores de dominio compatibles con las validaciones
anteriores, con pruebas unitarias, de interfaces, de comportamiento mediante
dobles, de integración y de arquitectura. El cierre se verificó con 400 pruebas.

**Etapa 2 en curso, tareas 2.2–2.6 completas:** diseño físico documentado,
constantes e invariantes binarios, `ValueCodec`, `RecordCodec` y `PageHeader`.
**696 pruebas pasan**, incluidas las 400 anteriores y 296 nuevas. Este bloque
trabaja con bytes en memoria; no implementa páginas completas ni persistencia.

El cierre anterior está registrado en [la auditoría de la Etapa 1](docs/ETAPA_01_AUDIT.md).
El avance actual se registra en [ETAPA_02.md](ETAPA_02.md). La Etapa 2 y la
Parte 1 del proyecto todavía no están completas.

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
- Las validaciones explícitas utilizan errores de `engine.errors`, derivados
  de `DatabaseError`, que siguen siendo capturables como `TypeError`,
  `ValueError`, `KeyError` o `IndexError`, según el caso. Se conservan los
  mensajes y las reglas anteriores.

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
`Record` no limita los enteros lógicos; `RecordCodec` rechaza los que no caben
en int64. `FLOAT` admite NaN e infinitos: el codec normaliza NaN y conserva los
infinitos y el cero con signo. Los operadores SQL definirán sus propias reglas
más adelante. Un esquema vacío admite un registro con una secuencia vacía.

### Formato físico y codecs (Etapa 2 parcial)

Se adoptó un formato v1 de páginas de **4096 bytes**, little-endian y directorio
de slots. Este tamaño es una decisión del proyecto, no un requisito oficial.
`PageHeader` ocupa 12 bytes. Los formatos futuros reservan 5 bytes por slot y
20 bytes de cabecera al inicio del archivo. Las constantes e invariantes están
centralizadas en `engine/storage/binary.py`.

```python
from engine.storage import PageHeader, RecordCodec, ValueCodec

payload = RecordCodec.serialize(record)
recovered = RecordCodec.deserialize(schema, payload)
assert recovered == record

header = PageHeader(page_id=0)  # Metadatos de página vacía; no asigna una página.
assert header.contiguous_free_space == 4084
assert PageHeader.deserialize(header.serialize()) == header
assert ValueCodec.encode(DataType.BOOLEAN, True) == b"\x01"
```

- `INTEGER`: entero con signo de 64 bits, entre `-2**63` y `2**63 - 1`.
- `FLOAT`: IEEE-754 de 64 bits; NaN se codifica como un NaN quieto canónico.
  Para comparar un NaN recuperado, utiliza `math.isnan`, no igualdad.
- `BOOLEAN`: un byte, exclusivamente `0` o `1`.
- `VARCHAR`: longitud en bytes como uint32 seguida de UTF-8 estricto. Admite
  Unicode y NUL embebido; rechaza surrogates aislados y UTF-8 malformado.
- El registro concatena valores según el esquema, sin guardar esquema, etiquetas
  de tipos ni `NULL`. Se requiere el esquema correcto al decodificar. Se rechazan
  truncamientos y bytes sobrantes; no se detecta toda alteración de datos válidos.
- Las APIs binarias reciben `bytes`. Tipos incorrectos producen
  `InvalidTypeError`; datos malformados o fuera de rango, `ValidationError`.
- El codec no impone la capacidad de una página. La futura `Page` rechazará
  registros de más de 4079 bytes; no se han adoptado páginas de desbordamiento.

La política adoptada conserva RIDs vivos al compactar, pero permite reutilizar
slots eliminados; un RID antiguo no garantiza identidad histórica. Estas
operaciones todavía no están implementadas. El catálogo seguirá en memoria
durante la Etapa 2, y el llamador aportará el esquema al recuperar registros.
Consulta [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md#physical-format-v1) para los
campos, límites, políticas y responsabilidades del formato.

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

### Errores de dominio

Se importan desde `engine.errors`:

| Error | Compatible con | Caso |
|---|---|---|
| `InvalidTypeError` | `TypeError` | Argumento o valor con tipo incorrecto |
| `ValidationError` | `ValueError` | Validaciones del modelo, valores fuera del rango binario, bytes malformados o geometría inválida |
| `SchemaError` | `ValueError` | Nombre de columna vacío o columnas duplicadas |
| `DuplicateError` | `ValueError` | Tabla/índice duplicado o segundo índice agrupado |
| `InvalidReferenceError` | `KeyError` | Índice desconocido; base para referencias inexistentes |
| `UnknownTableError` | `KeyError` | Tabla inexistente |
| `UnknownColumnError` | `KeyError` | Columna inexistente, incluso al registrar un índice |
| `ColumnPositionError` | `IndexError` | Posición fuera del esquema |

Todos derivan de `DatabaseError`. `SchemaError` y `DuplicateError` derivan
además de `ValidationError`; los errores de tabla/columna desconocida derivan
de `InvalidReferenceError`. Los errores propios de Python al construir un enum,
modificar un objeto inmutable o manipular una tupla no se envuelven.

### Contratos abstractos

```python
from engine.storage import Storage
from engine.indexes import Index, OrderedIndex
from engine.operators import Operator
```

Son clases abstractas (`ABC`): no se pueden instanciar sin implementar sus
métodos. No contienen algoritmos físicos ni operadores concretos.

- `Storage`: `insert(record) -> RID`, `read(rid) -> Record`,
  `delete(rid) -> None` y `scan()`. El almacenamiento tendrá un esquema fijo;
  insertar un registro de otro esquema genera `SchemaError`. Leer o eliminar
  un RID ausente/eliminado genera `InvalidReferenceError`. `scan()` entrega
  pares `(RID, Record)` vivos, sin imponer un orden común.
- `Index`: `insert(key, rid) -> None`, `search(key)` y
  `delete(key, rid) -> None`. Admite varios RIDs por clave; repetir exactamente
  el mismo par al insertar no hace nada. Eliminar un par inexistente genera
  `InvalidReferenceError`. No inserta ni elimina registros del almacenamiento.
- `OrderedIndex` añade `range_search(lower=None, upper=None, *,
  include_lower=True, include_upper=True)`. `None` significa sin límite;
  los extremos son inclusivos por defecto y los resultados siguen el orden
  ascendente de las claves. Un intervalo invertido genera `ValidationError`.
  Extendible Hashing no está obligado a implementar este contrato ordenado.
- `Operator`: `open()`, `next() -> Record | None` y `close()`.
  `None` indica agotamiento, incluso en llamadas posteriores; un registro vacío
  sigue siendo un resultado válido. `next()` sin abrir o después de cerrar, y
  `open()` sobre una ejecución ya abierta, generan `RuntimeError`. Cerrar es
  idempotente; reabrir después de cerrar inicia otra ejecución desde el principio.

Las claves de un índice tendrán un único tipo incorporado exacto, sin
conversiones ni mezcla `bool`/`int`. Se rechaza NaN como clave o límite con
`ValidationError`; los infinitos están permitidos. Esto **no cambia** la
validación de valores de `Record`.

`scan()`, `search()` y `range_search()` devuelven generadores cerrables y no
exigen cargar todos los resultados en memoria. Sin coincidencias no producen
elementos. Deben liberar sus recursos al agotarse, fallar o cerrarse; sus
errores pueden aparecer durante la iteración. Para abandonar un recorrido
anticipadamente, el consumidor puede usar:

```python
from contextlib import closing

# storage será una implementación concreta de una etapa posterior.
with closing(storage.scan()) as rows:
    for rid, record in rows:
        process(rid, record)
```

El consumidor de un operador debe envolver **toda** la ejecución, incluido
`open()`, en `try/finally` y llamar siempre a `close()`. El operador cierra sus
recorridos y operadores hijos propios, no los gestores de almacenamiento o
índices prestados. Las ABC exigen métodos; las implementaciones futuras deberán
probar el cumplimiento de estas reglas de comportamiento y recursos.

## Organización

```text
engine/
  errors.py      # Errores compartidos, sin dependencias de otros componentes
  catalog/       # Tipos, esquemas, metadatos y catálogo en memoria
  storage/       # RID, Record, Storage abstracto, codecs y PageHeader; sin Page ni disco
  indexes/       # Index y OrderedIndex abstractos; sin B+ ni hashing físicos
  operators/     # Operator abstracto; sin operadores concretos
  query/         # Reservado: parser, planificador y ejecutor
  transactions/  # Reservado: transacciones y concurrencia
api/             # Paquete reservado; aún sin servidor
frontend/        # Reservado para la interfaz
tests/
  doubles.py     # Implementaciones mínimas solo para pruebas; no son el motor
  conftest.py    # Bloqueo de apertura de archivos durante operaciones de integración
  catalog/       # Pruebas del modelo implementado
  storage/       # Modelo, contrato Storage, formatos, codecs y PageHeader
  indexes/       # Contratos de igualdad/rangos mediante dobles
  operators/     # Ciclo de vida, agotamiento y liberación de recursos
  test_contracts.py  # Firmas y obligatoriedad de los contratos abstractos
  test_errors.py     # Errores propios y compatibilidad con excepciones anteriores
  test_architecture.py  # Dependencias e importaciones aisladas
  test_catalog_record_integration.py  # Integración sin acceso a disco
  test_codec_header_integration.py    # Catálogo, codecs y metadatos sin archivos
benchmarks/      # Reservado para experimentos
data/            # Reservado para datos
docs/            # Evidencia de auditoría y documentación adicional
```

Los archivos `.gitkeep` conservan en Git los directorios que aún están vacíos.
Los paquetes Python se conservan mediante sus archivos `__init__.py`.

## Arquitectura

El catálogo actual utiliza solamente la biblioteca estándar de Python. No
depende del almacenamiento, del parser, de una API ni de la interfaz gráfica.
`Record` depende de `Schema` y `DataType`; `RID` no depende del catálogo. Ninguno
de estos componentes realiza acceso a disco. Los codecs conocen tipos/esquemas;
`PageHeader` y los validadores de geometría no conocen registros ni tipos SQL.
Las demás capas se implementarán progresivamente según el plan.

Los dobles `StorageDouble`, `EqualityIndexDouble`, `OrderedIndexDouble` y
`OperatorDouble` viven solamente en `tests/`. Usan datos pequeños en memoria
para comprobar la interacción de los contratos; no son Heap Files, B+, hashing
ni operadores relacionales de producción. No se empaquetan con el motor.

## Validación

En Windows, desde la raíz:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/catalog -q
.\.venv\Scripts\python.exe -m pytest tests/storage -q
.\.venv\Scripts\python.exe -m pytest tests/indexes tests/operators -q
.\.venv\Scripts\python.exe -m pytest tests/test_contracts.py tests/test_errors.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_catalog_record_integration.py tests/test_architecture.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_codec_header_integration.py -q
.\.venv\Scripts\python.exe -m pytest -ra -W error
.\.venv\Scripts\python.exe -m compileall -q engine api tests
.\.venv\Scripts\python.exe -m pip check
```

En Linux/macOS, sustituye `.\.venv\Scripts\python.exe` por `.venv/bin/python`.

Las pruebas de importación requieren la instalación editable indicada arriba:
ejecutan intérpretes aislados desde fuera del repositorio para detectar
dependencias del directorio actual o de módulos precargados por pytest.
Las pruebas de arquitectura leen fuentes; las de integración bloquean las
aperturas de archivos únicamente durante las operaciones del modelo, contratos,
codecs y cabeceras bajo prueba.

La verificación actual se ejecutó en Windows con Python 3.12.4 y pytest 8.4.2:
696 pruebas aprobadas, sin omisiones, xfails ni advertencias con `-W error`.
`compileall` y `pip check` también pasan. Las implementaciones físicas futuras deberán
añadir sus propias pruebas de conformidad, persistencia y concurrencia.

## Documentos de coordinación y siguiente paso

- [REQUIREMENTS.md](REQUIREMENTS.md): requisitos académicos.
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md): arquitectura y decisiones estables.
- [PLAN.md](PLAN.md): las diez etapas de la Parte 1.
- [ETAPA_01.md](ETAPA_01.md): etapa de fundamentos, cerrada y auditada.
- [ETAPA_02.md](ETAPA_02.md): etapa vigente; tareas 2.2–2.6 completadas.
- [AGENTS.md](AGENTS.md): reglas de trabajo en el repositorio.

La Definition of Done de `ETAPA_01.md` está satisfecha y marcada por completo.
Consulta [la auditoría de cierre](docs/ETAPA_01_AUDIT.md) para ver la evidencia
por criterio, los comandos ejecutados y los límites de la validación.

Este bloque se detiene después de **PageHeader (2.6)**. El siguiente paso es
**SlotEntry / directorio de slots (2.7)**, cuando se solicite continuar.
No se implementaron `SlotEntry`, `Page`, `FileHeader`, `PageManager` ni acceso
a disco. La Definition of Done de la Etapa 2 sigue incompleta.
