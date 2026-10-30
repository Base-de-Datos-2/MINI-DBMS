# Parte 3 — Bloque 3: ranking TF-IDF/coseno y BM25

Fecha: 2026-10-28. **Estado: CERRADO.** La solicitud del usuario autoriza el bloque 3 de
[PLAN_PARTE_03.md](PLAN_PARTE_03.md), §§3.2–3.3, 4.2–4.3 y 7. El núcleo
implementa el ranking Python sobre el índice persistente del bloque 2 y un
scan real del Heap. Sellado del almacenamiento e integración owner/SQL
corresponden a 4A/4B; no se anticipan esas fases.

## Implementación y criterios

| Criterio | Implementación y aceptación |
|---|---|
| TF-IDF con coseno | Pesos logarítmicos e IDF suavizado; norma de consulta después de proyectarla al vocabulario. Usa la norma documental completa persistida por SPIMI. Ejemplo analítico y fixtures congeladas contrastados con Decimal independiente. |
| BM25 | IDF BM25, frecuencia y normalización por longitud con `k1=1.2`, `b=0.75`; parámetros registrados en el reporte. Una contribución por término distinto de consulta. |
| Semántica OR | Solo candidatos con términos conocidos; consultas vacías/desconocidas y colecciones vacías/sin tokens devuelven cero hits. No se agregan epsilon ni coincidencias artificiales de score cero. |
| Repeticiones y estabilidad | Repetir términos afecta TF-IDF, no BM25. Las contribuciones se acumulan por orden estable del vocabulario. No se redondean ni agrupan scores por tolerancia; se rechazan scores no finitos o negativos. |
| Orden y top-k | Heap de tamaño k solo para score DESC/id ASC con LIMIT. Los demás órdenes y score DESC sin límite usan el ExternalSort real de la etapa 6. LIMIT se aplica después de resolver el orden total. |
| Índice/scan | Con `use_indexes=True` se recorren únicamente los postings consultados. Con `False` se tokenizan todas las filas del Heap y se reutilizan las mismas estadísticas/fórmulas; no se leen postings para descubrir candidatos. |
| Reapertura y concurrencia | Se conservan IDs, scores y RIDs después de abrir en otro proceso. Dos consultas con listas parcialmente compartidas producen los mismos hits que sus ejecuciones seriales sobre un lector común. |
| Recursos y fallos | Se cierran iteradores, scans y temporales, conservando los handles prestados. Cancelación cooperativa mediante `cancellation_scope`; errores de escritura y cancelación durante sort liberan sus reservas/handles. |

Archivos principales: `engine/text/ranking.py`, exportaciones en
`engine/text/__init__.py`, pruebas en `tests/text/test_ranking.py`. La regla
de dependencias permite text→operators para reutilizar ExternalSort y los
puntos de cancelación; no se añadieron dependencias hacia query/API ni código
de scoring en el frontend.

## API y ordenamiento

```python
from engine.storage import HeapFile
from engine.text import TextIndex, search_text

with TextIndex.open("data/generated/documentos_spimi") as index:
    with HeapFile.open("data/generated/documentos.heap", index.table.schema) as heap:
        indexed = search_text(
            index, "base de datos vectorial", model="TF_IDF", limit=10,
        )
        scanned = search_text(
            index, "base de datos vectorial", model="TF_IDF", limit=10,
            use_indexes=False, storage=heap,
        )
        assert indexed.hits == scanned.hits
        for hit in indexed.hits:
            original = heap.read(hit.rid)
            print(hit.doc_id, hit.score, original.values)
```

`model` es obligatorio: `TF_IDF` o `BM25`. No cambia las fórmulas congeladas
en [text-ranking-contract.md](../docs/text-ranking-contract.md).

| `order` | Orden total | Con LIMIT | Sin LIMIT |
|---|---|---|---|
| `score_desc` (predeterminado) | score DESC, ID ASC | TopKHeap → ordenar ganadores | ExternalSort de todas las coincidencias |
| `score_asc` | score ASC, ID ASC | ExternalSort → LIMIT | ExternalSort |
| `id_asc` | ID ASC | ExternalSort → LIMIT | ExternalSort |
| `id_desc` | ID DESC | ExternalSort → LIMIT | ExternalSort |

`limit=None` devuelve todas las coincidencias; `limit=0` no lee postings ni
filas. El ID acompaña siempre al score en este núcleo, preparando la dependencia
oculta necesaria cuando 4B permita omitirlo en la proyección SQL. El binder
resolverá aliases, ASC implícito y formas SQL; aquí se recibe el orden ya
resuelto. No se modificó el parser.

El contraejemplo de IDs 1/2/3 se verifica con scores literales 0.2/0.9/0.5
y con documentos reales en ambos modelos: con LIMIT 1, score DESC elige 2,
score ASC e ID ASC eligen 1 e ID DESC elige 3. Las rutas por índice y scan
conservan estas decisiones al reabrir. Un test separado asegura que scores
distintos por 1e-13 no se conviertan en un empate por aplicar tolerancias.

## Recursos, consistencia y resultado

`TextSearchResult` contiene una tupla eager de `TextHit(doc_id, score, rid)` y
un `TextRankingReport` inmutable. No carga textos originales ni sustituye al
`QueryResult` streaming de SQL; esa integración pertenece a 4B.

El reporte registra trabajo real: postings consumidos, filas del scan,
candidatos puntuados, hits entregados, ruta de selección y máximo de entradas
del heap. En ExternalSort conserva runs iniciales, pasadas, filas/bytes
derramados y fan-in realmente usado; cero significa que esa ruta no se ejecutó.
El tiempo corresponde a la llamada del núcleo, no a SQL/HTTP ni a un benchmark
experimental controlado.

La memoria se distingue explícitamente:

- Acumulador de scores O(C), medido por `getsizeof` del diccionario y sus
  IDs/floats. **Un top-k pequeño no limita este acumulador.**
- Consulta tokenizada, frecuencias y pesos: estimado separado.
- Scan: conjunto de IDs de verificación O(N) y máximo estimado de la fila
  tokenizada/Counter. No se retiene el corpus textual.
- Selección y tupla de resultados O(R): estimados separados. Para el heap se
  contabilizan entradas y reserva de ordenación de ganadores.
- `sort_memory_budget_bytes` limita solo las reservas del ExternalSort
  existente; no el acumulador, metadatos del índice, resultado ni RSS.
- `buffer_bytes` limita un iterador de postings activo por consulta. Se
  redondea hacia abajo a múltiplos de 16 y se registra cuando hubo lecturas.

Un `ExecutionContext` opcional se presta al ExternalSort, que devuelve sus
reservas y handles al terminar/fallar. El contexto del llamador, el índice y
el Heap permanecen abiertos. No se crea otro gestor de sesiones o locks.
La cancelación usa los safe points existentes durante scoring, scan,
selección y generación/consumo de filas del sort.

El scan comprueba esquema, cada ID/RID, hash de la fila original, longitud
tokenizada y conteo total. Una diferencia produce error de generación. El
acceso por índice usa sus postings/estadísticas persistentes sin escanear el
Heap. La fuente debe mantenerse sin modificaciones en ambos casos; la
comprobación del scan no implementa el sellado persistente de 4A.

## Validación

La regresión focalizada ampliada aprobó **757 pruebas en 164.49 segundos**,
con advertencias como errores, Python 3.12.6 en Windows. Incluye texto,
arquitectura, codecs, Heap, contrato del parser, binder, apertura de bases,
ExternalSort, contextos, ciclo de operadores y temporales. No es una nueva
ejecución de toda la suite del proyecto ni una validación SQL textual/HTTP.

Código y pruebas: commit **d9bcf94**. El
[recibo de cierre](../docs/implementacion/evidencias/text_block3_closure.json)
conserva runtime, comando y cinco ejecuciones del ejemplo resuelto: TF-IDF
y BM25 por índice/scan con hits idénticos, más BM25 ascendente con LIMIT 1
mediante ExternalSort (ganador ID 11). Incluye scores, RIDs y reportes de
trabajo/memoria; los tiempos de muestra no son benchmarks experimentales.

```powershell
New-Item -ItemType Directory -Force tmp | Out-Null
$env:TEMP = (Resolve-Path tmp).Path
$env:TMP = $env:TEMP
python -m pytest -q -W error -p no:cacheprovider --tb=short `
  --basetemp tmp/part03_block3_regression `
  tests/text tests/test_architecture.py `
  tests/storage/test_record_codec.py tests/storage/test_value_codec.py `
  tests/storage/test_heap_file.py tests/storage/test_heap_persistence.py `
  tests/query/test_parser_contract.py tests/query/test_binder.py `
  tests/api/test_database.py tests/operators/test_sorting.py `
  tests/operators/test_context.py tests/operators/test_lifecycle.py `
  tests/operators/test_temp_files.py
```

Usar un basetemp nuevo al repetir. El ajuste TEMP/TMP del comando se limita al
proceso/sesión de validación; no modifica variables persistentes del sistema.

Primera verificación completa del ranking y arquitectura: **154 pruebas
aprobadas en 89.17 s**, con advertencias como errores. Incluye 130 pruebas
nuevas de ranking y los controles de arquitectura, no son 154 pruebas nuevas.
Estas pruebas están incluidas en las 757, no se suman como casos adicionales.

La verificación usa las 20 consultas congeladas (incluidos sus textos del
enunciado, mediante API Python), la matriz de cuatro órdenes y cinco límites
en ambos modelos, oráculo Decimal de 60 dígitos, extremos INTEGER, corpus
sembrados con normas distintas, empates y colecciones vacías. Los snapshots y
el oráculo congelado no se regeneraron para acomodar la implementación.

La prueba de recursos fuerza varias pasadas con 800 coincidencias, fan-in 2
y el presupuesto mínimo de ExternalSort. Se valida que todas las coincidencias
entren en la ordenación antes de LIMIT y que el acumulador no se presente como
parte del heap de tamaño k.

En este entorno Windows el TEMP predeterminado no permite abrir el registro
de temporales del sort. Los comandos de validación usan TEMP/TMP del proceso
en `tmp/` del repositorio. Esto no modifica la configuración persistente del
usuario ni cambia el algoritmo para evitar los derrames externos.

## Límites

- No se ejecutó la matriz experimental ESCI/100k ni PostgreSQL GIN; no se
  atribuyen Precision@10, Recall@10 o ventajas de rendimiento a estas pruebas.
- No se implementaron sello persistente, registro del owner, SQL MATCH/USING/
  SCORE, EXPLAIN textual, endpoints ni UI. Esas fases conservan su alcance.
- La comparación índice/scan en Python y los threads del lector no equivalen
  a la futura aceptación con dos sesiones HTTP del mismo owner.
- Los resultados son ID/score/RID en memoria; el futuro operador SQL controlará
  proyección, streaming y el preview HTTP con los contratos existentes.

El siguiente bloque pendiente es **4A: política persistente de escritura**.
