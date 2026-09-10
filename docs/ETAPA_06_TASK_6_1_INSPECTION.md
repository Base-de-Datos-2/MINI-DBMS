# Inspección previa de la Etapa 6 — tarea 6.1

Fecha: **2026-09-10**. Alcance: contratos, cursores, codecs, métricas y
políticas de las Etapas 1–5 que condicionan los operadores relacionales y los
algoritmos externos. Esta inspección fue de solo lectura; la línea base se
comprobó antes de implementar 6.3–6.10.

## Resultado de la línea base

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
1716 passed in 37.87s
```

Sin fallos, omisiones ni xfails, con advertencias tratadas como errores. La
cifra coincide con la registrada en la
[revisión de 5.8–5.15](ETAPA_05_REVIEW_5_8_5_15.md), de modo que la línea base
heredada se reproduce en un entorno nuevo. No se detectaron pruebas de
persistencia ni de integración de índices omitidas.

`engine/operators/` contenía únicamente el ABC `Operator` de la Etapa 1
(`open`/`next`/`close`) y su reexportación. No existían operadores concretos,
contexto de ejecución, expresiones, archivos temporales ni algoritmos externos.
`engine/query/` y `engine/transactions/` siguen vacíos y quedan fuera de esta
etapa.

## Verificación de los prerrequisitos de la Etapa 5

La Definition of Done de la Etapa 5 se comprobó contra código y pruebas, no
contra marcas de checklist:

- `ExtendibleHashIndex` y `UnclusteredHashIndex` existen, persisten cabecera,
  directorio y buckets, y sus pruebas de reinicio, crecimiento y validación
  forman parte de las 1716 aprobadas.
- Los bloques **5.1–5.7** y **5.8–5.15** fueron revisados y corregidos
  ([bloque de fundamentos](ETAPA_05_REVIEW_5_1_5_7.md),
  [bloque de crecimiento](ETAPA_05_REVIEW_5_8_5_15.md)).
- Permanecen **pendientes** los hallazgos declarados en 5.23 (rollback
  Heap/índice), 5.25 (E/S tipada de creación), 5.26 (validación diferencial por
  mutación) y 5.27 (trazabilidad de los 47 criterios).

Ninguno de esos pendientes bloquea la Etapa 6: los cuatro afectan a rutas de
**mutación** del índice, y el invariante 9 de [ETAPA_06.md](../ETAPA_06.md)
declara que la ejecución de consultas de esta etapa es de solo lectura sobre el
almacenamiento base. Los operadores no deben invocar `insert_record`,
`delete_record` ni `update_record`.

## Mapa de compatibilidad: APIs reutilizables

### Modelo y catálogo (Etapa 1)

- `Schema` es inmutable y ordenado, admite esquemas vacíos y expone
  `__len__`, `__iter__`, `column(nombre|posición)` e `index_of(nombre)` con
  búsqueda exacta y sensible a mayúsculas.
- `Column(name, data_type)` y `DataType` cubren `INTEGER`, `FLOAT`, `BOOLEAN` y
  `VARCHAR`.
- `Record(schema, values)` es inmutable (`frozen`, `slots`) y valida el tipo
  exacto por columna: `bool` no satisface `INTEGER` y no hay conversión
  implícita. **`None`/NULL no está soportado** en ningún nivel del motor.
- `record[nombre]` resuelve por nombre y lanza `UnknownColumnError`.
- `TableMetadata(name, schema)` no declara clave primaria; `IndexMetadata`
  aporta `index_type`, `clustered`, `unique`, `file_path` y las propiedades
  derivadas `allow_duplicate_keys` y `supports_equality`.
- `Catalog` es un registro **en memoria**: no persiste y debe reconstruirse en
  cada proceso.

### Errores (Etapa 1)

`engine/errors.py` define el vocabulario compartido y su compatibilidad con
excepciones nativas: `InvalidTypeError`/`TypeError`,
`ValidationError`/`ValueError`, `SchemaError`, `DuplicateError`,
`InvalidReferenceError`/`KeyError`, `UnknownTableError`, `UnknownColumnError`,
`ColumnPositionError`/`IndexError`. Los operadores deben reutilizarlo en lugar
de introducir jerarquías nuevas.

### Almacenamiento (Etapas 2–3)

- `Storage` declara `insert`, `read`, `delete` y `scan`. `scan()` devuelve un
  generador **perezoso y cerrable** de `(RID, Record)`, excluye tombstones,
  no promete orden común y crea un cursor nuevo e independiente en cada
  llamada. Cerrar un scan no cierra el almacenamiento prestado.
- `HeapFile` recorre en orden físico `(page_id, slot_id)`, que **no** es
  cronológico después de reutilizar slots. No expone propiedad de orden.
- `PagedSequentialFile` mantiene el orden por la clave configurada, y añade
  `search(...)`, `reorganize() -> ReorganizationMetrics` y propiedades de
  espacio desperdiciado.
- Ambas se abren con `create(path, schema, ...)` / `open(path, schema=None)`,
  son gestores de contexto y validan su propio esquema persistido.
- `RID(page_id, slot_id)` es inmutable, ordenable, no negativo y **relativo a
  un archivo**: no identifica una fila entre tablas distintas.

### Índices (Etapas 4–5)

- `Index` declara `insert`, `search`, `delete`; `OrderedIndex` añade
  `range_search(lower, upper, *, include_lower, include_upper)` con extremos
  opcionales, rechazo de rangos invertidos y orden ascendente nativo del tipo.
- Adaptadores disponibles: `UnclusteredBPlusIndex` y `UnclusteredHashIndex`
  sobre `HeapFile`, y `ClusteredBPlusIndex` sobre `PagedSequentialFile`.
- Los tres exponen `search_records(key)`; los B+ añaden
  `range_records(...)`. Ambos devuelven `(RID, Record)` y **resuelven el RID
  contra el almacenamiento**, de modo que la Etapa 6 no necesita reimplementar
  la resolución.
- `range_records()` ya aplica la política de obsolescencia exigida por la
  tarea 6.8: relee la clave del registro, comprueba que sigue asociada al RID,
  verifica los extremos y el orden, y lanza `InvalidReferenceError` o
  `ValidationError` en vez de devolver silenciosamente otra fila.
- `BPlusKeyCodec.validate(key_type, key)` y `BPlusKeyCodec.compare(...)` son la
  semántica de comparación ya adoptada, compartida por B+ y hash. Rechazan
  `NaN` como clave; los flotantes infinitos sí se admiten.
- Los índices poseen y cierran su estructura física; el `HeapFile` o
  `PagedSequentialFile` subyacente permanece **prestado** y lo cierra quien lo
  abrió.

## Streaming real frente a materialización

Se inspeccionó explícitamente si las rutas de acceso construyen listas
completas antes de entregar resultados:

| Ruta | Comportamiento observado |
|---|---|
| `HeapFile.scan()` / `PagedSequentialFile.scan()` | Generador perezoso, una página viva a la vez |
| `BPlusTree.search()` / `range_search()` | Validan argumentos con antelación y luego recorren hoja por hoja siguiendo los enlaces |
| `UnclusteredBPlusIndex.search_records()` / `range_records()` | Generadores que envuelven el recorrido con `closing(...)` y resuelven un registro por iteración |
| `ExtendibleHashIndex.search()` | Perezoso; selecciona una entrada de directorio y lee un único bucket |
| `PageManager.read_page()` | E/S física real en cada llamada |

**Ninguna ruta materializa el resultado completo**, de modo que los operadores
pueden apoyarse en ellas sin romper el invariante de streaming.

## Contadores de E/S y memoria disponibles

- `PageManager` expone `pages_read`, `pages_written`, `pages_allocated` y
  `reset_counters()`. **No implementa buffer pool ni caché de páginas**: cada
  lectura es transferencia real, así que los contadores son honestos y ninguna
  caché inferior puede eludir en silencio el presupuesto de la tarea 6.5.
- Existen `BPlusBuildMetrics`, `BPlusStructuralMetrics`, `HashBuildMetrics`,
  `HashStructuralMetrics` y `ReorganizationMetrics` como precedente de formato
  para las estadísticas de la tarea 6.28.

### Salvedad de acumulación detectada

`BPlusTree.search()` y `range_search()` mantienen un conjunto `visited` de
`page_id` de hojas para detectar ciclos en la cadena de enlaces. Ese conjunto
crece proporcionalmente al número de hojas recorridas, no al presupuesto del
operador. Es un guardián de integridad, no una caché de filas, pero la
contabilidad de memoria de la tarea 6.5 debe declararlo como consumo del
recorrido en vez de anunciarlo como estado constante.

## Políticas registradas

| Política | Valor vigente en el repositorio |
|---|---|
| Esquema | Exacto y ordenado; el almacenamiento rechaza un `Record` con otro esquema, incluido otro orden de columnas |
| Tipos | Estrictos, sin coerción; `bool` no es `int` |
| NULL | **No soportado** en `Record`, índices ni codecs |
| Flotantes | `NaN` prohibido como clave de índice y permitido como valor de fila; infinitos admitidos; cero canónico fijado en los codecs |
| Duplicados | Una clave admite varios RIDs; repetir el par `(clave, RID)` es idempotente; `unique` lo restringe vía catálogo |
| Movimiento de RID | `HeapFile` puede reasignar un RID liberado a otra fila; `PagedSequentialFile` mueve RIDs al reorganizar, y `ClusteredBPlusIndex` se reconstruye tras ese movimiento |
| Propiedad de recursos | Quien abre cierra; los adaptadores cierran su índice y nunca el almacenamiento prestado |
| Cursores | Perezosos, independientes, cerrables; el consumidor usa `contextlib.closing` al abandonar antes de tiempo |

## Conflictos y prerrequisitos declarados

1. **Ubicación de los archivos temporales.** La sección 10 de
   [ETAPA_06.md](../ETAPA_06.md) sugiere `engine/storage/temp_files.py`, pero
   `tests/test_architecture.py::test_raw_file_access_dependencies_are_confined_to_page_manager`
   prohíbe que cualquier módulo de `engine.storage` distinto de `page_manager`
   importe `os`, `io`, `pathlib`, `mmap` o `tempfile`. La guía declara que sus
   nombres son ilustrativos, así que la gestión de temporales de la tarea 6.11
   se ubicará en `engine/operators/`, conservando la regla de arquitectura.
2. **NULL.** El modelo no admite `None`. Las tareas 6.6 y 6.3 se implementan
   con rechazo explícito de NULL en vez de una tabla de verdad de tres valores;
   la decisión queda registrada en la tarea 6.2.
3. **Catálogo en memoria.** No hay resolución persistente de nombre de tabla a
   archivo, de modo que los planes manuales de esta etapa reciben objetos de
   almacenamiento e índice ya abiertos, no nombres.
4. **`TableMetadata` sin clave primaria.** Los operadores no pueden asumir una
   clave primaria declarada; la identidad de fila se expresa con `(relación,
   RID)`.
5. **Contenido de `__all__`.**
   `tests/test_architecture.py::test_public_imports_work_from_fresh_isolated_interpreters`
   resuelve cada símbolo exportado contra su módulo de definición mediante
   `value.__module__`. Un entero no tiene ese atributo, de modo que las
   constantes de presupuesto quedan importables desde
   `engine.operators.context` pero **fuera** de `__all__`. Es la convención
   que ya seguían los paquetes anteriores.
6. **Límite de comparación de los codecs de índice.** `BPlusKeyCodec.compare`
   valida además el tamaño codificado de la clave (255 bytes para `VARCHAR`),
   lo cual es correcto para un índice pero incorrecto para un predicado sobre
   una columna no indexada. La Etapa 6 implementa `compare_values` con la
   misma semántica lógica y sin ese límite físico.

## Aceptación

No se duplicó ninguna abstracción existente: los operadores reutilizarán
`Schema`, `Record`, `RID`, los contratos `Storage`/`Index`/`OrderedIndex`, los
adaptadores de índice, `BPlusKeyCodec` para comparación y el vocabulario de
errores. Toda afirmación de verificación de etapas anteriores se apoya en la
ejecución registrada arriba y en los informes enlazados, no en marcas de
checklist.
