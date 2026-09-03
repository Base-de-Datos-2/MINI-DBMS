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

**Etapa 2 completa y auditada (2026-08-31):** diseño físico documentado,
constantes e invariantes binarios, codecs, `PageHeader`, `SlotEntry` y `Page`
en memoria con inserción, lectura, eliminación y reutilización de slots.
Ya existen compactación explícita, reconstrucción completa de páginas,
`FileHeader`, `PageManager` y contadores de E/S. Las páginas se guardan y
recuperan después de cerrar y reabrir archivos. El recorrido completo de
`Record` hasta disco y de vuelta se verifica también en procesos independientes,
con esquemas externos, varias páginas, slots eliminados y reescrituras.
**1155 pruebas pasan**: las 1067 anteriores y 88 adicionales para este cierre.

Los cierres están registrados en [la auditoría de la Etapa 1](docs/ETAPA_01_AUDIT.md)
y [la auditoría de la Etapa 2](docs/ETAPA_02_AUDIT.md). Los 47 criterios de
[ETAPA_02.md](ETAPA_02.md) se cumplen.

**Etapa 3 activa (2026-09-02), tareas 3.1–3.11 completas:** `HeapFile` ya permite
insertar registros en varias páginas, leerlos por RID, eliminarlos, reutilizar
slots/huecos, recorrer registros activos de forma perezosa y continuar después
de cerrar y reabrir con objetos nuevos. El directorio de espacio se reconstruye
al abrir. Todavía no se implementa Paged Sequential File. Tampoco existen
índices físicos, consultas SQL, transacciones, API ejecutable ni interfaz
gráfica. La Parte 1 sigue pendiente.

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
conceptual elegido por el ejemplo: no implica que esa página esté asignada.
`PageManager`, descrito más abajo, asigna y valida las páginas de un archivo.

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

### Formato físico y codecs (Etapa 2)

Se adoptó un formato v1 de páginas de **4096 bytes**, little-endian y directorio
de slots. Este tamaño es una decisión del proyecto, no un requisito oficial.
`PageHeader` ocupa 12 bytes y `SlotEntry`, 5 bytes. `FileHeader` es una cabecera
inicial de archivo de 20 bytes. Las constantes e invariantes están
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
- El codec no impone la capacidad de una página. `Page` rechaza
  registros de más de 4079 bytes; no se han adoptado páginas de desbordamiento.

La compactación conserva los RIDs vivos.
La reutilización de slots eliminados ya existe: un RID antiguo no garantiza
identidad histórica. El catálogo seguirá en memoria durante la Etapa 2, y el
llamador aportará el esquema al recuperar registros.
Consulta [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md#physical-format-v1) para los
campos, límites, políticas y responsabilidades del formato.

### Slots y página en memoria

`SlotEntry(offset, length, status)` es inmutable. El estado es `0` (libre) o
`1` (activo), ambos enteros exactos, no booleanos. Un slot libre exige offset y
longitud cero; un registro activo vacío usa offset 4096 y longitud cero. El
`slot_id` es la posición en el directorio, no un campo adicional de la entrada.

```python
from engine.storage import Page

page = Page(page_id=0)  # Solo memoria; no asigna ni abre archivos.
assert page.free_space() == 4084
assert Page.deserialize(page.serialize()).header == page.header  # Página vacía.

slot_id = page.insert(payload)  # payload se obtiene del ejemplo de RecordCodec.
rid = RID(page.page_id, slot_id)
assert RecordCodec.deserialize(schema, page.read(rid.slot_id)) == record
assert len(page.serialize()) == 4096
assert Page.deserialize(page.serialize()).read(slot_id) == payload

free_before = page.free_space()
page.delete(slot_id)
assert not page.slots[slot_id].is_active
assert page.free_space() == free_before  # El hueco aún no se recupera.
page.compact()
assert page.free_space() == free_before + len(payload)
assert page.insert(payload) == slot_id  # Reutiliza la entrada del directorio.
```

- `insert(bytes) -> slot_id` coloca bytes opacos desde el final de la zona libre.
  Si necesita una entrada nueva, también descuenta 5 bytes. Reutiliza primero
  el slot libre de menor posición. Admite registros de cero bytes.
- `free_space()` informa solo del espacio contiguo. Eliminar no mueve registros,
  no recorta el directorio ni aumenta este espacio; conserva los bytes antiguos
  como huecos hasta llamar a `compact()`. No es un borrado seguro de bytes.
- Reutilizar un slot evita su coste de directorio, pero requiere espacio contiguo
  para el nuevo payload. Una página llena puede seguir rechazando registros
  no vacíos después de eliminar uno. `compact()` recupera esos huecos, pero
  `insert()` no la invoca automáticamente.
- `compact() -> None` mueve los bytes activos, actualiza offsets y conserva
  todos los `slot_id`, incluidos los eliminados. Nunca recorta el directorio.
  Ordena el empaquetado por posición de slot y rellena con ceros la zona no
  utilizada del nuevo buffer. Es idempotente, no un borrado seguro en disco.
- Los argumentos incorrectos generan `InvalidTypeError`. Los slots inexistentes
  y libres/eliminados generan `InvalidReferenceError`, con mensajes distintos;
  los metadatos corruptos y la falta de espacio generan `ValidationError`.
  Una segunda eliminación falla. Los fallos de validación no modifican la página.
- `header`, `slots`, los registros leídos y los bytes serializados son snapshots
  inmutables. Las operaciones validan estados, contadores, límites y solapamientos.
- `serialize()` conserva los 4096 bytes del estado actual. `deserialize()`
  reconstruye páginas vacías, activas, fragmentadas, eliminadas y compactadas,
  validando toda la geometría y creando un buffer independiente. Conserva
  también los bytes no utilizados; no compacta ni descarta filas implícitamente.

### Archivos de páginas y contadores de E/S

`FileHeader` es inmutable: firma `b"MINIDB\x00\x00"`, versión 1, tamaño de página
4096 y cantidad de páginas asignadas (uint32). Su serialización `<8sIII` ocupa
exactamente 20 bytes. `PageManager` centraliza la dirección física:
`20 + page_id * 4096`, con páginas numeradas desde cero.

Este ejemplo usa un archivo temporal, eliminado automáticamente al terminar:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from engine.storage import PageManager

with TemporaryDirectory() as directory:
    path = Path(directory) / "demo.db"
    with PageManager.create(path) as manager:
        page_id = manager.allocate_page()
        page = manager.read_page(page_id)
        slot_id = page.insert(b"registro de ejemplo")
        manager.write_page(page)  # Modificar Page por sí solo no guarda en disco.
        manager.flush()
        assert manager.pages_read == 1
        assert manager.pages_written == 2  # Página vacía asignada + reescritura.
        assert manager.pages_allocated == 1

    with PageManager.open(path) as reopened:
        assert reopened.allocated_page_count == 1
        assert reopened.pages_read == 0  # Contadores de una nueva sesión.
        recovered_page = reopened.read_page(page_id)
        assert recovered_page.read(slot_id) == b"registro de ejemplo"
```

- `create(path)` crea exclusivamente un archivo nuevo: nunca sobrescribe uno
  existente ni crea directorios padre. `open(path)` exige que exista y no lo
  trunca. Se aceptan rutas de texto o `Path`. El constructor
  `PageManager(path, create=False)` equivale a abrir un archivo existente.
- Al abrir se validan cabecera y longitud exacta del archivo, sin cargar todas
  las páginas. `read_page` devuelve una copia independiente y comprueba la
  geometría y que su `page_id` coincida con la posición física.
- `allocate_page()` agrega una página vacía al final y actualiza la cabecera.
  `write_page(page)` solo reescribe páginas ya asignadas. No busca espacio libre
  entre páginas, no es Heap File y no implementa aún el contrato `Storage`.
- `flush()` vacía el handle y solicita sincronización mediante `os.fsync`.
  `close()` hace flush y cierra; es idempotente y libera el handle incluso si
  falla la sincronización. Usa `with` o cierra explícitamente. Las operaciones
  posteriores al cierre generan `RuntimeError`; los metadatos y contadores
  siguen disponibles para consulta.
- `pages_read`, `pages_written` y `pages_allocated` son propiedades de solo
  lectura. `reset_counters()` las pone a cero sin modificar el archivo ni su
  cantidad de páginas. No se guardan entre sesiones.
- Se cuentan transferencias **completas de páginas** por el handle del gestor,
  no lecturas físicas del hardware ni fallos de caché del sistema operativo.
  No cuentan cabeceras, seeks, flush/cierre, cambios en memoria ni validaciones
  fallidas. Leer dos veces cuenta dos lecturas: no existe caché de páginas.
- Una página totalmente leída pero corrupta cuenta como lectura. Una
  transferencia parcial fallida no cuenta como página completa. Si se escribe
  la página nueva pero falla la actualización de cabecera, cuenta una escritura
  y ninguna asignación exitosa. Las transferencias cortas se completan en bucles.
- Tipos incorrectos generan `InvalidTypeError`; páginas no asignadas,
  `InvalidReferenceError`; bytes corruptos, truncamientos, tamaños incoherentes
  o límite de páginas agotado, `ValidationError`. Los errores del sistema de
  archivos conservan su tipo nativo, por ejemplo `FileExistsError`,
  `FileNotFoundError` y `OSError`.
- Un fallo de escritura cierra el gestor y propaga el error. Puede dejar bytes
  parciales o un archivo nuevo incompleto; no hay rollback ni reparación
  automática. Flush/fsync no garantiza asignaciones atómicas ante una caída.
  Se admite un solo propietario/escritor por archivo; no hay protección de
  concurrencia, buffer pool, WAL ni recuperación ante fallos.

El catálogo sigue en memoria. Un archivo manejado directamente por
`PageManager` no contiene esquema; el consumidor debe aportarlo a
`RecordCodec`. Los archivos organizados de la Etapa 3 sí guardan una copia
ordenada de su propio esquema, pero todavía no persisten el registro completo
de tablas e índices del `Catalog`.

### Organización de archivo y Heap File (Etapa 3)

Cada organización usa un archivo paginado independiente. La página física 0
contiene un único `OrganizationMetadata`; las páginas de datos empiezan en 1.
Esto conserva intactas las cabeceras binarias de la Etapa 2 y permite rechazar
la apertura con una clase de organización incorrecta.

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from engine.catalog import Column, DataType, Schema
from engine.storage import HeapFile, OrganizationType, Record

schema = Schema([Column("id", DataType.INTEGER)])
with TemporaryDirectory() as directory:
    path = Path(directory) / "students.heap"
    with HeapFile.create(path, schema) as heap:
        rid = heap.insert(Record(schema, [1]))
        assert heap.read(rid).values == (1,)
        assert heap.metadata.organization_type is OrganizationType.HEAP

    with HeapFile.open(path, schema) as reopened:
        assert reopened.read(rid).values == (1,)
        assert list(reopened.scan()) == [(rid, Record(schema, [1]))]
```

`HeapFreeSpaceTracker` mantiene en memoria, por página, la mayor carga útil que
podría insertarse después de compactar localmente. Al reabrir, `HeapFile` lee
una vez cada página de datos, valida los contadores persistidos y reconstruye
el directorio. La elección usa el menor `page_id` elegible, pero `Page.insert`
seguirá siendo la autoridad final ante información obsoleta. El seguimiento no
es un índice ni se persiste por separado. `scan()` lee una página de datos cada
vez, omite slots eliminados y produce `(RID, Record)` en orden físico. Reutilizar
un slot puede hacer que un RID eliminado pase a identificar un registro nuevo.

### Ejemplo completo de persistencia de registros

Solo el archivo y el RID pasan de la escritura a la lectura; el lector crea un
esquema nuevo a partir de información que aporta la aplicación. En este ejemplo,
el directorio temporal y su archivo se eliminan al terminar:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from engine.catalog import Column, DataType, Schema
from engine.storage import PageManager, Record, RecordCodec, RID


def write_example(path):
    schema = Schema([
        Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR),
    ])
    with PageManager.create(path) as manager:
        page_id = manager.allocate_page()
        page = manager.read_page(page_id)
        row = Record(schema, [1, "Lucía 😀"])
        slot_id = page.insert(RecordCodec.serialize(row))
        manager.write_page(page)
    return RID(page_id, slot_id)  # No devuelve el Record, Schema, Page ni gestor.


with TemporaryDirectory() as directory:
    path = Path(directory) / "records.db"
    rid = write_example(path)
    external_schema = Schema([
        Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR),
    ])
    with PageManager.open(path) as reader:
        payload = reader.read_page(rid.page_id).read(rid.slot_id)
        recovered = RecordCodec.deserialize(external_schema, payload)
        assert recovered.values == (1, "Lucía 😀")
```

Las pruebas de reinicio ejecutan escritura, lectura, reescritura y lectura final
en cuatro procesos separados por escenario, fuera del repositorio y con la
instalación editable. El esquema se proporciona en cada proceso; no se guardan
objetos Python ni un catálogo auxiliar. Se comprueban páginas fragmentadas y
compactadas, RIDs vivos, slots libres, valores Unicode/NaN/infinitos y contadores.
Esto demuestra persistencia tras cierre normal, no recuperación tras una caída.

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
| `InvalidReferenceError` | `KeyError` | Índice desconocido, página no asignada, slot inexistente o libre/eliminado; base para referencias inexistentes |
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
  storage/       # Modelo, páginas, PageManager, metadatos de organización y Heap inicial
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
  storage/       # Modelo, codecs, páginas, archivos, organización/Heap y fallos de E/S
  indexes/       # Contratos de igualdad/rangos mediante dobles
  operators/     # Ciclo de vida, agotamiento y liberación de recursos
  test_contracts.py  # Firmas y obligatoriedad de los contratos abstractos
  test_errors.py     # Errores propios y compatibilidad con excepciones anteriores
  test_architecture.py  # Dependencias e importaciones aisladas
  test_catalog_record_integration.py  # Integración sin acceso a disco
  test_codec_header_integration.py    # Catálogo, codecs, slots y páginas sin archivos
  test_stage2_persistence_pipeline.py # Recorrido completo y procesos independientes
  page_corruption.py                 # Casos compartidos de corrupción de metadatos
  helpers/stage2_restart.py           # Escenario de prueba; no es un algoritmo del motor
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
`Page`, `SlotEntry`, `PageHeader` y los validadores de geometría no conocen
registros lógicos ni tipos SQL. Page recibe bytes, no objetos Record.
`PageManager` conoce páginas y cabecera de archivo, pero no registros, esquemas,
codecs ni organizaciones como Heap File. Es el propietario del acceso a disco.
`OrganizationMetadata` y `HeapFile` se apoyan en él sin importar `os` ni
repetir offsets físicos; `HeapFile` conecta además el contrato `Storage` y
`RecordCodec`. Las demás capas se implementarán progresivamente según el plan.

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
.\.venv\Scripts\python.exe -m pytest tests/storage/test_persistence.py tests/storage/test_malformed_files.py tests/test_stage2_persistence_pipeline.py -q -W error
.\.venv\Scripts\python.exe -m pytest -ra -W error
.\.venv\Scripts\python.exe -m compileall -q engine api tests
.\.venv\Scripts\python.exe -m pip check
```

En Linux/macOS, sustituye `.\.venv\Scripts\python.exe` por `.venv/bin/python`.

Las pruebas de importación requieren la instalación editable indicada arriba:
ejecutan intérpretes aislados desde fuera del repositorio para detectar
dependencias del directorio actual o de módulos precargados por pytest.
Las pruebas de arquitectura leen fuentes; las de integración **sin disco** bloquean las
aperturas de archivos únicamente durante las operaciones del modelo, contratos,
codecs, cabeceras, slots y páginas bajo prueba. Las pruebas de `PageManager`
usan archivos temporales de pytest y mantienen ese acceso separado del modelo.
Las de persistencia e integración completa usan archivos temporales reales;
las de procesos independientes no comparten objetos del escritor con el lector.

La verificación actual se ejecutó en Windows con Python 3.12.4 y pytest 8.4.2:
1229 pruebas aprobadas, sin omisiones ni xfails. `compileall` y `pip check`
también pasan. Las operaciones físicas restantes deberán añadir sus propias
pruebas de conformidad, persistencia y concurrencia.

## Documentos de coordinación y siguiente paso

- [REQUIREMENTS.md](REQUIREMENTS.md): requisitos académicos.
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md): arquitectura y decisiones estables.
- [PLAN.md](PLAN.md): las diez etapas de la Parte 1.
- [ETAPA_01.md](ETAPA_01.md): etapa de fundamentos, cerrada y auditada.
- [ETAPA_02.md](ETAPA_02.md): etapa de persistencia, cerrada y auditada.
- [ETAPA_03.md](ETAPA_03.md): etapa de organizaciones de archivo, activa.
- [AGENTS.md](AGENTS.md): reglas de trabajo en el repositorio.

Las Definitions of Done de las Etapas 1 y 2 están satisfechas. Consulta
[la auditoría de la Etapa 2](docs/ETAPA_02_AUDIT.md) para la evidencia de cada
criterio, los comandos ejecutados y los límites de la validación.

La **Etapa 3 está activa** y las tareas 3.1–3.11 están completas. El siguiente
paso es la tarea 3.12: materializar el contrato común de ordenamiento que usará
Paged Sequential File, sin iniciar ninguna etapa posterior.
