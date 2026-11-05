# Bloques 6 y 7 — comparación experimental y cierre

Fecha: 4 de noviembre de 2026. Alcance: fases 6 y 7 del
[plan de la Parte 3](PLAN_PARTE_03.md). No incluye las Partes 4 y 5 del PDF.

## Fase 6: comparación

**Qué se agregó.**

- `benchmarks/text/fts.py`: comparador PostgreSQL FTS + GIN + `ts_rank`.
- `benchmarks/text/experiment.py`: procesos aislados de construcción y de consultas, y orquestador de los tres tamaños.
- `benchmarks/text/metrics.py`: Precision@10 y Recall@10.
- `benchmarks/text/results.py`: tablas y figuras. Rechaza matrices incompletas, duplicadas o con la verificación semántica fallida.
- `benchmarks/postgres_client.py`: ahora acepta configuraciones de sesión. Su valor por defecto, usado por el experimento espacial, no cambió.
- El motor (`engine/`, `api/`) no se modificó. El desglose de SPIMI se mide envolviendo sus funciones internas desde el proceso del benchmark.

**Corpus.** Se regeneró desde las fuentes oficiales de ESCI. Los 13
artefactos coinciden byte a byte con los hashes congelados del
[bloque 1B](BLOQUE_1B.md). La firma del tokenizador exige Unicode 15.0.0, por
lo que se usó CPython 3.12.3.

**Semántica verificada antes de medir**, en los tres tamaños:

- lexemas y frecuencias idénticos entre motor y PostgreSQL;
- conjuntos de coincidencias idénticos en las 30 consultas;
- top-10 con índice igual al scan exhaustivo, para TF-IDF y BM25.

La primera ejecución de prueba detectó que el parser `simple` de PostgreSQL
descarta `½`, que el tokenizador del motor conserva. Se resolvió entregando a
PostgreSQL los tokens del motor en la sintaxis de entrada de `tsvector`. Los
detalles están en [EXPERIMENTOS_TEXTO.md](../docs/EXPERIMENTOS_TEXTO.md).

**Matriz medida.** 3 tamaños × 3 métodos × 30 consultas × 3 repeticiones =
**810 tiempos**, tras una pasada de calentamiento y con el orden de los
métodos rotado. Se midieron también construcción y su desglose, P@10, R@10,
disco y pico de RSS. Los planes de PostgreSQL se registraron sin forzar el
acceso: GIN en 11, 29 y 30 de las 30 consultas.

Al revisar la primera corrida completa se vio que el pico de memoria de
consultas incluía la verificación semántica previa. Se separó la medición
(sesión PostgreSQL nueva y reinicio del pico de Python) y se repitió **toda**
la matriz. Los resultados publicados provienen de esa única ejecución final.

Resultados principales a 100 000 documentos:

| Técnica | Construcción | Consulta media | P@10 | R@10 |
|---|---:|---:|---:|---:|
| TF-IDF/coseno | 25,45 s (SPIMI compartido) | 12,62 ms | 0,283 | 0,165 |
| BM25 | 25,45 s (SPIMI compartido) | 10,72 ms | 0,297 | 0,189 |
| PostgreSQL FTS + GIN + `ts_rank` | 1,18 s | 6,52 ms | 0,227 | 0,157 |

## Fase 7: cierre

**Documentación actualizada.**

- [EXPERIMENTOS_TEXTO.md](../docs/EXPERIMENTOS_TEXTO.md) (nuevo): protocolo, resultados, revisión manual, tabla de ventajas/desventajas, límites y reproducción.
- [informe_parte_03.md](../docs/informe/informe_parte_03.md) (nuevo): sección del informe incremental con los algoritmos y los resultados.
- [README.md](../README.md): estado de la Parte 3 y fila de experimentos textuales.
- [docs/text.md](../docs/text.md) y [text-sql-contract.md](../docs/text-sql-contract.md): ya no dicen que el SQL textual está pendiente.
- [PLAN_PARTE_03.md](PLAN_PARTE_03.md): fases 6 y 7 completadas y checklist de §9.

**Regresión.**

| Comprobación | Resultado |
|---|---|
| Suite backend completa, Python 3.12.3, `-n 4 -W error` | **3 561 aprobadas, 0 fallos** (85,66 s) |
| Suite backend completa, Python 3.11.9, `-n 4 -W error` | **3 561 aprobadas, 0 fallos** (100,31 s) |
| Pruebas de benchmarks (incluye 13 nuevas del experimento textual) | 42 aprobadas |
| Frontend: `npm test`, `npm run typecheck`, `npm run build` | 43 aprobadas; tipos y compilación correctos |

Las 3 561 pruebas incluyen las 3 547 registradas en 4B/5. La aceptación con
navegador real no se repitió: el frontend no cambió desde el bloque 5
(`docs/evidence/text_browser.json`).

Evidencia estructurada:
[text_block6_7_closure.json](../docs/implementacion/evidencias/text_block6_7_closure.json).
Contiene versiones, el SHA-256 del código medido, los hashes de resultados y
figuras, y los comandos de prueba.

## Guion de demo para el video (unos 3 minutos)

Preparar con el servidor detenido y una base nueva:

```bash
python scripts/setup_text.py --data-dir data/generated/text_video
python -m api --text --data-dir data/generated/text_video
```

| Tiempo | Acción | Qué decir |
|---|---|---|
| 0:00 | Files: elegir `documentos` y mostrar el índice SPIMI. | "El índice invertido se construyó con SPIMI: bloques en memoria, volcado a disco y mezcla k-way." |
| 0:20 | `SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;` | Señalar scores y el plan `TextIndexScan` con modelo TF_IDF. |
| 0:45 | La misma consulta con `USING BM25`. | "Mismo índice, otra fórmula: el orden puede cambiar." Mostrar una diferencia real si aparece; no prometer un ganador. |
| 1:05 | `SELECT *, SCORE() AS relevancia FROM articulos WHERE MATCH(texto, 'machine learning') USING BM25 ORDER BY relevancia DESC;` | El segundo ejemplo literal del PDF. |
| 1:25 | Desmarcar «Usar índices» y repetir. | "Con `TextScan` el resultado es el mismo; solo cambia el acceso." |
| 1:45 | `EXPLAIN ANALYZE` sobre la primera consulta. | Candidatos puntuados, selección y tiempo. |
| 2:05 | Ctrl+C, arrancar de nuevo y repetir una consulta. | "La colección se reabre con los mismos resultados." |
| 2:25 | Mostrar las figuras de [EXPERIMENTOS_TEXTO.md](../docs/EXPERIMENTOS_TEXTO.md). | "Con 100 000 títulos, BM25 tuvo la mejor relevancia media; PostgreSQL fue más rápido; las consultas largas cuestan más por la semántica OR." |

## Límites

- Los juicios ESCI son incompletos: P@10 y R@10 son respecto de los juicios disponibles.
- Una sola matriz en WSL2 con caché caliente y poca memoria libre: no hay intervalos de confianza.
- Los tiempos de cliente de PostgreSQL incluyen transporte local; el tiempo del servidor se reporta aparte.
- No se probaron otras normalizaciones de `ts_rank`, `ts_rank_cd` ni ajustes de k1/b.
- Los límites del motor siguen igual: un proceso propietario, sin WAL ni recuperación automática, y colecciones textuales inmutables.
- La grabación del video es tarea del equipo; aquí queda preparado el guion.

**Dictamen: fases 6 y 7 de la Parte 3 completadas y verificadas**, con los
límites anteriores. No equivale a entregar las Partes 4 y 5.
