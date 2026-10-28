# Parte 3 — Bloque 2: núcleo SPIMI persistente

Fecha: 2026-10-28. **Estado: CERRADO.** La solicitud del usuario autoriza
exclusivamente el bloque 2 de [PLAN_PARTE_03.md](PLAN_PARTE_03.md), §§4.1,
4.1.1 y 7. Los bloques 1A/1B conservan sus cierres anteriores.

## Implementación y condiciones de salida

| Criterio | Implementación y evidencia | Estado |
|---|---|---|
| Entrada por flujo, IDs desordenados y unicidad global | `build_spimi` toma un `Storage` prestado y `TableMetadata`; valida filas y conserva IDs INTEGER signed-64, incluidos extremos y negativos. Rechaza duplicados, también vacíos y entre bloques. | PASS |
| SPIMI con presupuesto configurable | Diccionario término → postings `(doc_id, tf)`, una frecuencia por documento/término. Derrame previo a exceder el presupuesto estimado; términos y postings ordenados en cada bloque. Un documento puede repartirse entre bloques. | PASS |
| Mezcla externa acotada | K-way merge propio con `heapq`, fan-in configurable ≥2, pasadas adicionales y un buffer fijo por lector. No concatena listas completas; rechaza IDs duplicados durante la mezcla. | PASS |
| Representación vectorial dispersa | Postings binarios, léxico con dimensiones por orden Unicode, offsets, longitud y df definitivo. Las fixtures reconstruyen exactamente las frecuencias de cada documento. | PASS |
| Estadísticas completas | N, longitudes, total de tokens, avgdl y normas TF-IDF con N/df finales; documentos sin tokens tienen longitud/norma cero y permanecen en el mapa. Corpus vacío explícito. | PASS |
| Asociación y persistencia | Mapa ID→RID y SHA-256 de la fila original completa; colección, generación, esquema, restricciones, columnas y firma del tokenizador persistidos. Reapertura en intérprete aislado sin reutilizar objetos de la carga. | PASS |
| Integridad y publicación | Destino nuevo exclusivo; se valida el índice y cada RID/fila antes de mover el manifiesto final. Errores de entrada, I/O y publicación limpian el destino propio y conservan el Heap prestado. | PASS |
| Lecturas por offset y concurrencia | Un latch físico cubre cada seek/read y el cierre. Cada iterador tiene cursor lógico y buffer propios; cierre anticipado libera solo su buffer. Pruebas intercaladas y con dos threads sobre un lector. | PASS |

El cálculo de normas es parte de la construcción exigida por §4.1.6; **no se
implementó el ranking de consultas del bloque 3**. Tampoco se agregaron SQL
textual, owner/registro textual, sellado del Heap, endpoints ni UI. Esas
integraciones siguen las fases 3, 4A, 4B y posteriores.

## Archivos y API

- `engine/text/format.py`: formato versionado y metadatos inmutables.
- `engine/text/spimi.py`: construcción, bloques, mezcla y reporte de recursos.
- `engine/text/index.py`: reapertura, validación y lectores por offset.
- `engine/text/__init__.py`: exportaciones públicas, conservando el tokenizador.
- `tests/text/test_spimi.py`: aceptación funcional, fallos y concurrencia.
- `tests/test_architecture.py`: permite dependencias text→catalog/storage,
  manteniendo prohibidas las dependencias hacia query, API y benchmarks.

Uso Python, con un Heap existente y sin escritores concurrentes:

```python
from engine.storage import HeapFile
from engine.text import TextIndex, build_spimi

# TABLE es el TableMetadata real del Heap; no se crea otro almacenamiento.
with HeapFile.open("data/generated/documentos.heap", TABLE.schema) as heap:
    report = build_spimi(
        "data/generated/documentos_spimi", heap, TABLE,
        collection_id="documentos-v1", id_column="id", text_column="contenido",
        memory_budget_bytes=8 * 1024 * 1024, merge_fan_in=16,
        io_buffer_bytes=4096,
    )

with TextIndex.open(
    "data/generated/documentos_spimi", collection_id="documentos-v1",
    generation=report.generation, table=TABLE,
) as index:
    index.validate()
    # Se recibe un término exacto ya normalizado; la consulta SQL vendrá después.
    with index.postings("datos", buffer_bytes=4096) as postings:
        for doc_id, tf in postings:
            document = index.documents[doc_id]  # RID, longitud, norma, hash
```

El directorio contiene solamente:

| Archivo | Contrato v1 |
|---|---|
| `postings.bin` | Cabecera little-endian `<8sI` con magic `MDBTXT01` y versión 1; postings `<qQ` de 16 bytes: ID signed-64 y tf unsigned-64 positivo. |
| `lexicon.jsonl` | Términos normalizados, dimensión contigua desde cero, offset absoluto, df y longitud en bytes. Listas contiguas, sin huecos ni bytes sobrantes. |
| `documents.jsonl` | IDs ordenados, RID único, longitud, norma y SHA-256 de `RecordCodec.serialize(record)`; incluye documentos sin tokens. |
| `manifest.json` | Estado completo del artefacto, versión, identificadores de colección/generación, metadatos de tabla/columnas, tokenizador, estadísticas, tamaños/hashes y reporte de construcción. |

La generación es nueva en cada construcción. Los índices no guardan rutas
absolutas al Heap; el llamador proporciona su identidad de colección y puede
exigir colección/generación/esquema esperados al abrir. `verify_storage(heap)`
comprueba todas las filas, RIDs y hashes contra el almacenamiento prestado.
La futura integración con el owner debe aplicar esa asociación antes de
registrar el lector y conservar la generación correspondiente al Heap.

La apertura verifica firma de algoritmo **y versión Unicode**, versión de
archivos, hashes, esquema, mapa, conteos y geometría del léxico/postings.
`validate()` añade el recorrido semántico completo para comprobar referencias,
orden, frecuencias, longitudes y normas; la construcción lo ejecuta antes de
publicar. No se reconstruyen archivos corruptos silenciosamente.

## Memoria y vida útil

`memory_budget_bytes` es el límite del **modelo estimado de bloque y
ordenación**, no un límite de RSS. Se carga cada posting con el tamaño Python
de su tupla/enteros y 32 bytes de punteros; cada término nuevo añade su tamaño
Python y 512 bytes de reserva para diccionario, lista y ordenación. La base es
256 bytes. Se derrama antes de superar esa cuenta. Un término/posting que no
cabe por sí solo produce `InsufficientBudgetError`, sin truncarlo.

El reporte `SpimiBuildReport`, también persistido en el manifiesto, separa:

- máximo estimado de bloques, presupuesto y máximo estimado de la fila
  tokenizada/Counter;
- metadatos ID/RID/hash/longitud y acumulador de normas, **O(N)**; incluyen
  la comprobación de IDs y RIDs únicos, con estimación basada en `getsizeof`;
- reserva para ordenar IDs de documentos y espacio estimado de mezcla;
- bloques iniciales, pasadas, máximo real de lectores de runs, fan-in y tamaño
  de buffer por lector.

La lista de nombres de runs requiere O(B), siendo B los bloques iniciales.
Los estimados no cubren el intérprete, el asignador, todos los temporales de
normalización, el Heap ni el total del proceso. No se presentan como una
medición experimental de memoria. Léxico y estadísticas pueden permanecer en
memoria al abrir; no se conservan el corpus ni listas completas de postings.
Los hashes de componentes se calculan por bloques de 64 KiB. Cada iterador
tiene un buffer explícito (por defecto 4 KiB, mínimo un posting); los tamaños
se redondean hacia abajo a múltiplos de 16 bytes.

El latch termina al copiar cada bloque. Scoring, iteración y entrega de filas
quedan fuera. Cerrar/cancelar un iterador no cierra el handle permanente. El
cierre del lector usa el mismo latch; lecturas posteriores o incompletas
producen un error de dominio. La coordinación con sesiones se probará en 4B,
cuando exista el owner textual y el ranking.

## Validación ejecutada

Regresión con advertencias como errores, Python 3.12.6 en Windows:
**551 pruebas aprobadas en 95.84 s**, el 2026-10-28.

Código y pruebas: commit **89731d4**. El
[recibo de cierre](../docs/implementacion/evidencias/text_block2_closure.json)
registra runtime, comando y una construcción adicional sobre los 16 documentos
de la fixture española: **61 tokens, 29 términos, 55 postings, 27 bloques y
5 pasadas** con presupuesto estimado de 2.048 bytes y fan-in 2. Se comprobaron
sus postings contra los tokens congelados y todos sus RIDs/filas. Los máximos
estimados de bloque y metadatos fueron 1.803 y 7.776 bytes respectivamente;
esto ilustra que el presupuesto del bloque no limita la memoria total.

```powershell
python -m pytest -q -W error -p no:cacheprovider --tb=short `
  --basetemp tmp/part03_block2_regression `
  tests/text tests/test_architecture.py `
  tests/storage/test_record_codec.py tests/storage/test_value_codec.py `
  tests/storage/test_heap_file.py tests/storage/test_heap_persistence.py `
  tests/query/test_parser_contract.py tests/query/test_binder.py `
  tests/api/test_database.py
```

Usar un `--basetemp` nuevo al repetir. La verificación inicial del núcleo y
arquitectura aprobó 81 pruebas; está contenida conceptualmente en la regresión
ampliada, no se suma como una suite independiente.

Las pruebas nuevas usan las dos fixtures congeladas de 1A, el oráculo Decimal
independiente, tres entradas desordenadas con semilla y extremos INTEGER,
presupuestos pequeños/fan-in 2 y 3, listas comunes largas, corpus vacíos y
sin tokens, corrupción con y sin hashes recalculados, procesos aislados,
fallos de scan/escritura/mezcla/publicación y dos threads sobre un lector.

## Límites del cierre

- Los 100.000 documentos reales y la aceptación ESCI conservan la evidencia
  de 1B. Esta ejecución no volvió a descargar el corpus ni midió SPIMI sobre
  esos 100.000 documentos. Las pruebas pequeñas fuerzan los caminos externos.
- La suite anterior es una regresión focalizada; no es una nueva ejecución de
  toda la suite del proyecto ni una validación HTTP/browser.
- El Heap sigue siendo mutable. El llamador debe construir offline y conservar
  la colección sin cambios. Detectar diferencias con `verify_storage` no
  implementa el sello persistente de 4A ni locks de sesiones de 4B.
- El manifiesto completo identifica un artefacto del núcleo; no es todavía el
  registro de una colección publicada por `api.database.Database`.
- No se promete WAL, recuperación ante crashes, mantenimiento incremental,
  relevancia medida, ranking, SQL textual, comparador GIN ni IVF/HNSW.

El siguiente bloque pendiente es el **3: ranking TF-IDF/coseno y BM25**.
