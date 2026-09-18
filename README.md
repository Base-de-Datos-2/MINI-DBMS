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

**Etapa 3 completa y auditada (2026-09-02):** `HeapFile` permite
insertar registros en varias páginas, leerlos por RID, eliminarlos, reutilizar
slots/huecos, recorrer registros activos de forma perezosa y continuar después
de cerrar y reabrir con objetos nuevos. `PagedSequentialFile` ya persiste su
clave, ordena inserciones arbitrarias mediante redistribución de páginas,
recorre y busca con duplicados estables, elimina mediante tombstones, mide el
desperdicio y reorganiza mediante un reemplazo compacto validado. Las pruebas
de cierre comparan ambas organizaciones con el mismo dataset y verifican sus
archivos independientes. Los 50 criterios de la Etapa 3 se cumplen.

**Etapa 4 completa y auditada (2026-09-03):** están terminadas las tareas 4.1–4.31.
Existe el diseño persistente B+, `BPlusFileHeader`, codificación determinista de
claves, RIDs y nodos, E/S mediante `PageManager`, ciclo de vida del árbol vacío,
descenso con captura de ruta y búsquedas exactas y por rango sobre hojas
enlazadas. La inserción ordenada ya divide hojas e internos, propaga separadores
y crea una nueva raíz persistente cuando corresponde. La eliminación exacta
conserva duplicados, repara separadores, redistribuye o fusiona hojas e internos
y registra y reutiliza las páginas liberadas. Ya existen reducción de raíz,
validación estructural, reinicio completo, construcción/reconstrucción atómica
desde almacenamiento y adaptadores B+ unclustered/clustered sobre HeapFile y
PagedSequentialFile. También existen integración con metadatos del catálogo,
contadores estructurales y comparación end-to-end. Los 59 criterios de la
Definition of Done se cumplen y el cierre está registrado en
[la auditoría de la Etapa 4](docs/ETAPA_04_AUDIT.md).

**Etapa 5 completa y auditada (2026-09-06):** `ExtendibleHashIndex` implementa
formatos deterministas, búsqueda/inserción/eliminación exactas, splits,
duplicación del directorio, reinicio y validación estructural. Puede construirse
y reconstruirse desde HeapFile; `UnclusteredHashIndex` mantiene mutaciones y las
fábricas del catálogo despachan, reabren y eliminan archivos físicos. Existen
métricas reales y pruebas diferenciales. La revisión de los cuatro bloques
(2026-09-10) corrige y verifica los 47 criterios bajo las decisiones
arquitectónicas documentadas, con **1772 pruebas estrictas**
(cierre original: 1621); consulta
[la auditoría de la Etapa 5](docs/ETAPA_05_AUDIT.md). Merge/shrink son opcionales
y están diferidos.

**Etapa 6 completa y auditada (2026-09-11):** `engine/operators/` contiene la
capa de ejecución física. Hay scans de tabla e índice, filtro y proyección en
streaming, y los **tres algoritmos externos obligatorios** de la Parte 1:
`ExternalSort` con mezcla k-way multipasada para `ORDER BY`,
`ExternalHashGroup` con particionamiento en disco para `GROUP BY` y
`GraceHashJoin` para `JOIN`, todos demostrados con volcados a disco forzados.
`NestedLoopJoin` es la línea base de corrección, y las rutas opcionales
`IndexNestedLoopJoin` e `IndexOrderedGroup` aprovechan los índices de las
Etapas 4 y 5. Los 59 criterios se cumplen con 2252 pruebas estrictas; consulta
[la auditoría de la Etapa 6](docs/ETAPA_06_AUDIT.md). Esta capa física también
puede ensamblarse y medirse directamente con objetos Python.

**Etapa 7 completa y auditada (2026-09-18):** el lexer y parser SQL se
implementan manualmente mediante descenso recursivo, con AST y ubicaciones de
origen independientes. El binding usa `Catalog`; el planificador conecta SQL a
TableScan, índices B+/hash y a los operadores externos reales de la Etapa 6.
`SqlEngine` expone preparación, descripciones, resultados SELECT en streaming e
INSERT/DELETE síncronos a través de una capa compartida de mantenimiento. Las
pruebas públicas cubren el dataset de aceptación, reinicio, spills, fallbacks,
limpieza, fallos inyectados y comparación con rutas base. Los 63 criterios se
cumplen y la suite estricta completa pasa **2556 pruebas**. Consulta la
[guía del motor SQL](docs/sql.md) y la
[auditoría de la Etapa 7](docs/ETAPA_07_AUDIT.md). La Parte 1 sigue pendiente:
la Etapa 8 de transacciones y concurrencia es la siguiente y aún no comenzó.

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

## Uso de las capas fundamentales

Para configurar almacenamiento, índices y ejecutar el subconjunto SQL soportado,
consulta la [guía del motor SQL](docs/sql.md). El ejemplo siguiente muestra
solamente el modelo fundamental de catálogo, esquema, registro y RID.

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
infinitos y el cero con signo. El motor SQL conserva tipos exactos y no soporta
NULL. Un esquema vacío admite un registro con una secuencia vacía.

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

### Paged Sequential File (Etapa 3)

```python
from engine.storage import PagedSequentialFile, Record

with PagedSequentialFile.create(path, schema, "id") as ordered:
    ordered.insert(Record(schema, [3]))
    ordered.insert(Record(schema, [1]))
    ordered.insert(Record(schema, [2]))
    assert [row.values[0] for _, row in ordered.scan()] == [1, 2, 3]
    assert [row.values[0] for _, row in ordered.search(2)] == [2]
    current_rid = next(ordered.search(2))[0]
    ordered.delete(current_rid)
    assert ordered.wasted_space_ratio() > 0.0
    metrics = ordered.reorganize()
    assert ordered.deleted_record_count == 0
    assert ordered.wasted_space_ratio() == 0.0
    assert metrics.pages_read > 0
    assert metrics.file_size_after == ordered.file_size
```

El comparador rechaza conversiones implícitas y NaN, y usa el mismo orden para
insertar, recorrer y buscar. Una división crea páginas adyacentes y desplaza el
sufijo físico mediante `PageManager`; no existe un B+ oculto. Como una inserción
estructural puede mover registros, los RIDs secuenciales anteriores quedan
invalidados según la política documentada. La eliminación solo marca el slot
`FREE`; la razón de desperdicio cuenta huecos de payload y bytes de entradas
`FREE`, pero no la capacidad ordinaria sin usar. `should_reorganize()` aplica
`ratio > threshold` sin escribir. `reorganize()` crea, valida y sincroniza un
archivo hermano compacto antes de pedir a `PageManager` el reemplazo físico.
La métrica devuelta conserva tiempo, E/S agregada y tamaños reales de esa
operación aunque el gestor reabierto inicie una nueva sesión de contadores.

### B+ Tree persistente (Etapa 4, tareas 4.1–4.31)

```python
from engine.catalog import DataType
from engine.indexes import (
    BPlusFileHeader, BPlusKeyCodec, BPlusLeafNode, BPlusRIDCodec, BPlusTree,
)
from engine.storage import RID

header = BPlusFileHeader(
    index_name="idx_students_id",
    table_name="students",
    key_column="id",
    key_type=DataType.INTEGER,
)
assert BPlusFileHeader.deserialize(header.serialize()) == header

rid = RID(1, 0)
assert BPlusRIDCodec.decode(BPlusRIDCodec.encode(rid)) == rid
assert BPlusKeyCodec.decode(
    DataType.INTEGER,
    BPlusKeyCodec.encode(DataType.INTEGER, -10),
) == -10

leaf = BPlusLeafNode(1, DataType.INTEGER, [7], [rid])
assert leaf.keys == (7,)
assert leaf.rids == (rid,)

with BPlusTree.create(
    "students-id.idx",
    index_name="idx_students_id",
    table_name="students",
    key_column="id",
    key_type=DataType.INTEGER,
) as tree:
    tree.insert(7, rid)
    assert list(tree.search(7)) == [rid]
    assert list(tree.range_search()) == [rid]
```

La cabecera, los nodos y sus enlaces ya tienen representaciones persistentes y
deterministas. Cada nodo ocupa una página física completa y toda E/S pasa por
`PageManager`. Una hoja guarda pares repetidos `clave → RID`; los RIDs de claves
iguales se ordenan para evitar asociaciones idénticas duplicadas. Las
capacidades se calculan desde el límite físico de la página y el peor tamaño de
clave; `VARCHAR` admite hasta 255 bytes UTF-8 y NaN no es indexable.

`BPlusTree` puede crear y reabrir el árbol, descender nodos persistidos y
recorrer hojas enlazadas para búsquedas exactas y rangos con extremos inclusivos,
exclusivos o abiertos. La inserción reconstruye solamente los nodos inmutables
afectados, conserva el orden `(clave, RID)`, divide hojas e internos usando sus
capacidades físicas y crea una nueva raíz al propagar una división hasta arriba.
Los enlaces son unidireccionales y la navegación hacia padres conserva la ruta
en memoria. La eliminación borra una asociación exacta, repara mínimos y
redistribuye o fusiona hojas e internos cuando hay underflow. La raíz se reduce
y las páginas liberadas se reutilizan desde una lista persistente. El validador
comprueba el árbol completo. `UnclusteredBPlusIndex` construye/resuelve sobre
HeapFile sin alterar su orden físico y `ClusteredBPlusIndex` exige un
PagedSequentialFile ordenado por la misma clave. Cuando una inserción o
reorganización secuencial mueve RIDs, el adaptador clustered marca el índice
incompleto y lo reconstruye mediante un archivo candidato validado antes del
reemplazo. Sin WAL, una falla intermedia puede dejar el almacenamiento cambiado
y el índice bloqueado hasta reconstruirlo explícitamente.

`IndexMetadata` distingue `clustered`, `unique` y `file_path`; el catálogo
conserva solo estas definiciones inmutables. Las funciones
`build_catalog_bplus()`/`open_catalog_bplus()` crean objetos abiertos separados.
Los contadores estructurales observan divisiones, redistribuciones, fusiones y
cambios de raíz, mientras las lecturas/escrituras/asignaciones siguen viniendo
del `PageManager` real.

### Hashing Extensible persistente (Etapa 5 completa)

`ExtendibleHashIndex` implementa acceso exacto `clave -> RID` mediante FNV-1a
de 64 bits y los bits menos significativos del hash. El directorio puede ocupar
varias páginas, cada bucket persiste su profundidad local y su capacidad se
calcula con los bytes serializados de claves completas y RIDs. Una inserción
puede dividir un bucket, duplicar el directorio y repetir la operación hasta que
la asociación quepa. Duplicados, unicidad, límite de profundidad y colisiones
inseparables siguen políticas acotadas y persistidas. La eliminación retira el
par exacto y conserva buckets vacíos; `validate_structure()` prueba aliases,
placement, unicidad, contadores y propiedad de páginas. La construcción y
reconstrucción desde Heap, el mantenimiento de RIDs, el despacho por catálogo y
las métricas de E/S/estructura completan la etapa. Buddy merge y shrink del
directorio permanecen opcionalmente diferidos.

Construye una definición nueva con `build_and_register_catalog_hash(catalog,
metadata, heap)`: recorre filas activas, valida, sincroniza el índice y solo
entonces registra los metadatos. `open_catalog_index(catalog, name, heap)`
despacha por tipo físico y comprueba cobertura contra Heap. El catálogo global
sigue en memoria: tras reiniciar hay que registrar de nuevo la tabla y su
definición de índice; el header físico conserva tipo, identidad, unicidad,
formato, hash y profundidades sin parámetros ocultos.

Usa `insert_record`, `delete_record` y `update_record` del adaptador para mantener
su índice; `update_record` devuelve el RID vigente. Tanto `search` como
`search_records` comprueban la clave actual en Heap. Si se modifica Heap por
fuera, hay que reconstruir los índices afectados con `rebuild()` antes de
consultarlos. No hay coordinación automática de varios índices ni generaciones
de RID para identificar una fila histórica después de reutilizar su slot.

Un rollback fallido intenta marcar el hash como incompleto y bloquea su uso
hasta reconstrucción; si también falla esa marca, cierra la instancia y conserva
los errores agrupados. Sin WAL no se garantiza atomicidad entre ambos archivos.
`validate_structure()` comprueba estructura y cobertura, pero no repara datos.

Para medir consultas, usa `index.reset_counters()` antes de la operación y toma
`index.metrics` y los contadores de Heap después; la validación/reapertura
también genera E/S. `build_metrics` es una instantánea de construcción, no un
contador persistido ni el coste total de `rebuild()`. La reconstrucción abre una
nueva sesión de E/S; mide su tiempo completo externamente con `perf_counter`.
Consulta [la revisión final](docs/ETAPA_05_REVIEW_5_22_5_27.md) para criterios,
recuperación y límites de medición.

### Operadores relacionales y algoritmos externos (Etapa 6 completa)

Un plan físico se ensambla con objetos Python ya ligados; esta capa no analiza
SQL ni elige rutas de acceso. Cada operador comprueba columnas y tipos **al
construirse**, de modo que un plan inválido falla antes de leer una fila.

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from engine.catalog import Column, DataType, Schema
from engine.operators import (
    Avg, Compare, ComparisonOperator, Count, ExternalHashGroup,
    ExternalSort, Filter, SortSpec, TableScan, column, run_plan,
)
from engine.storage import HeapFile, Record

schema = Schema([
    Column("id", DataType.INTEGER), Column("career", DataType.VARCHAR),
    Column("age", DataType.INTEGER),
])
with TemporaryDirectory() as directory:
    with HeapFile.create(Path(directory) / "students.heap", schema) as heap:
        for row in [(1, "CS", 22), (2, "EE", 19), (3, "CS", 24), (4, "EE", 23)]:
            heap.insert(Record(schema, list(row)))

        plan = ExternalSort(
            ExternalHashGroup(
                Filter(
                    TableScan(heap, relation="students"),
                    Compare(column("age"), ComparisonOperator.GREATER, 20),
                ),
                ["career"],
                [Count(), Avg("age")],
            ),
            SortSpec.ascending("career"),
        )
        rows, report = run_plan(plan, memory_budget_bytes=64 * 4096, limit=100)

print([tuple(row.values) for row in rows])  # [('CS', 2, 23.0), ('EE', 1, 23.0)]
print(report.render())
```

`report.render()` muestra el árbol de operadores **realmente ejecutado**, con
su ruta de acceso, runs, pasadas de mezcla, particiones y fallbacks medidos,
además de la memoria máxima reservada y los handles abiertos. Es la base del
futuro panel de plan de ejecución.

| Operador | Uso |
|---|---|
| `TableScan`, `IndexScan` | Leer un `HeapFile`/`PagedSequentialFile` o sondear un índice B+ (igualdad y rango) o hash (solo igualdad) |
| `Filter`, `Projection` | Seleccionar filas y columnas; la proyección nunca es `DISTINCT` |
| `ExternalSort` | `ORDER BY` con runs en disco y mezcla k-way acotada |
| `ExternalHashGroup` | `GROUP BY` con `COUNT`, `SUM`, `MIN`, `MAX` y `AVG` |
| `GraceHashJoin` | `JOIN` por igualdad con particionamiento de ambas entradas |
| `NestedLoopJoin` | Línea base de corrección; no es el join optimizado |
| `IndexNestedLoopJoin`, `IndexOrderedGroup` | Rutas opcionales asistidas por índice |

Reglas clave: no existe NULL en las filas de ejecución; no hay conversión
implícita entre INTEGER y FLOAT; NaN se rechaza como clave de comparación,
agrupación u orden. Los archivos temporales pertenecen a un directorio propio
de cada ejecución y se eliminan al cerrar, incluso tras un error o una parada
anticipada, sin tocar nunca tablas ni índices. Las decisiones completas están
en `PROJECT_CONTEXT.md`, sección *Relational operators*.

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
- Cada catálogo tiene su propio estado en memoria. `unregister_index` elimina
  una definición; `drop_catalog_index` verifica la identidad del archivo, lo
  elimina y luego retira sus metadatos. Cierra los runtimes antes de eliminar.
  No hay persistencia global, gestión de filas ni protección concurrente.

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
| `UnsupportedAccessError` | `ValueError` | Una ruta de acceso no ofrece la capacidad pedida, como un rango sobre un índice hash |
| `InsufficientBudgetError` | `ValueError` | Presupuesto de memoria o de handles insuficiente para un operador o un plan |
| `OversizedRowError` | `ValueError` | Una fila supera un límite documentado de memoria o de formato temporal |
| `CorruptTemporaryError` | `ValueError` | Un archivo temporal de ejecución está truncado, mal enmarcado o tiene otra versión |

Todos derivan de `DatabaseError`. `SchemaError`, `DuplicateError` y los cuatro
errores de ejecución de la Etapa 6 derivan además de `ValidationError`; los errores de tabla/columna desconocida derivan
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
índices prestados. Las ABC exigen métodos; `ExecutionOperator` (Etapa 6)
implementa estas reglas y sus operadores concretos tienen pruebas propias de
ciclo de vida, agotamiento y liberación de recursos.

## Organización

```text
engine/
  errors.py      # Errores compartidos, sin dependencias de otros componentes
  catalog/       # Tipos, esquemas, metadatos y catálogo en memoria
  storage/       # Páginas, PageManager, HeapFile y PagedSequentialFile
  indexes/       # Contratos, B+ y Hashing Extensible completos hasta Etapa 5
  operators/     # Operadores físicos, algoritmos externos y runner de planes
  query/         # AST, lexer/parser manual, binding, planes y ejecución SQL
  maintenance/   # Mantenimiento compartido de storage e índices para escrituras
  transactions/  # Reservado: transacciones y concurrencia
api/             # Paquete reservado; aún sin servidor
frontend/        # Reservado para la interfaz
tests/
  doubles.py     # Implementaciones mínimas solo para pruebas; no son el motor
  conftest.py    # Bloqueo de apertura de archivos durante operaciones de integración
  catalog/       # Pruebas del modelo implementado
  storage/       # Modelo, codecs, páginas, archivos, organización/Heap y fallos de E/S
  indexes/       # Contratos y pruebas persistentes de B+ y Hashing Extensible
  operators/     # Ciclo de vida, operadores, temporales y algoritmos externos
  query/         # Parser, binding, planificación, ejecución y aceptación SQL
  integration/   # Planes completos, persistencia, limpieza y pruebas diferenciales
  operator_helpers.py  # Fuentes de filas y fixtures de prueba de la Etapa 6
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
`OrganizationMetadata`, `HeapFile`, `PagedSequentialFile`, B+ y Hashing
Extensible se apoyan en él sin repetir offsets físicos. Los índices reutilizan
el codec canónico de claves y mantienen sus algoritmos visibles en
`engine/indexes`. Los operadores de `engine/operators` consumen los contratos
`Storage` e `Index` y los adaptadores de índice sin conocer páginas ni nodos, y
escriben sus temporales a través de `PageManager`; la gestión de directorios
temporales vive en esta capa porque la de almacenamiento reserva el acceso a
archivos para `PageManager`. `engine/query` construye planes sobre esos
operadores y `engine/maintenance` coordina las escrituras de storage e índices
sin depender del parser. Las capas de transacciones, API y frontend se
implementarán progresivamente según el plan.

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
.\.venv\Scripts\python.exe -m pytest tests -q -W error -p no:cacheprovider
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

La verificación formal de cierre de la Etapa 7 se ejecutó en Windows con las
advertencias tratadas como errores y sin caché de pytest: **2556 pruebas
aprobadas en 936.76 segundos**. Incluye las suites anteriores y las pruebas de
aceptación SQL, reinicio, rutas externas, recursos, mutaciones y diferencias.
`compileall`, `pip check` y la revisión del diff también pasan.

## Documentos de coordinación y siguiente paso

- [REQUIREMENTS.md](REQUIREMENTS.md): requisitos académicos.
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md): arquitectura y decisiones estables.
- [PLAN.md](PLAN.md): las diez etapas de la Parte 1.
- [ETAPA_01.md](ETAPA_01.md): etapa de fundamentos, cerrada y auditada.
- [ETAPA_02.md](ETAPA_02.md): etapa de persistencia, cerrada y auditada.
- [ETAPA_03.md](ETAPA_03.md): etapa de organizaciones de archivo, cerrada.
- [Auditoría de la Etapa 3](docs/ETAPA_03_AUDIT.md): evidencia de cierre.
- [ETAPA_04.md](ETAPA_04.md): etapa B+ cerrada; tareas 4.1–4.31 completas.
- [Inspección inicial de la Etapa 4](docs/ETAPA_04_TASK_4_1_INSPECTION.md):
  compatibilidad y extensiones mínimas identificadas antes de programar.
- [Auditoría de la Etapa 4](docs/ETAPA_04_AUDIT.md): evidencia de sus 59
  criterios, validación estricta y límites conocidos.
- [ETAPA_05.md](ETAPA_05.md): guía completa de Extendible Hashing.
- [Auditoría de la Etapa 5](docs/ETAPA_05_AUDIT.md): matriz conciliada de los 47
  criterios, 1772 pruebas tras revisión y límites conocidos.
- [ETAPA_06.md](ETAPA_06.md): etapa de operadores y algoritmos externos, cerrada.
- [Auditoría de la Etapa 6](docs/ETAPA_06_AUDIT.md): evidencia de los 59
  criterios, 2252 pruebas, salvedades declaradas y traspaso a la Etapa 7.
- [ETAPA_07.md](ETAPA_07.md): etapa SQL cerrada; tareas 7.1–7.30 completas.
- [Guía del motor SQL](docs/sql.md): API pública, sintaxis, planes, resultados,
  mutaciones, errores y límites soportados.
- [Auditoría de la Etapa 7](docs/ETAPA_07_AUDIT.md): evidencia de los 63
  criterios y 2556 pruebas estrictas.
- [AGENTS.md](AGENTS.md): reglas de trabajo en el repositorio.

Las **Etapas 1–7 están completas y auditadas**. La **Etapa 8 — Transactions and
Concurrency** es la siguiente en `PLAN.md`; todavía no se ha iniciado y no se
afirma que exista un plan detallado `ETAPA_08.md`.
