# Auditoría de cierre — Etapa 10 y Parte 1

**Fecha:** 2026-10-04 · **Rama:** `feat/close-etapa-10` (desde `main` en
`adaf3d3`) · **Plan:** [PART_01/ETAPA_10.md](../PART_01/ETAPA_10.md)

**Decisión: la Etapa 10 queda cerrada y, con ella, la Parte 1.** Las 14 tareas
y los 10 criterios de la Definición de Terminado se cumplen, y todos los
puntos del checklist de la Parte 1 (`REQUIREMENTS.md` §14) tienen evidencia.
Quedan dos detalles del lanzador del servidor, propuestos y sin aplicar porque
pertenecen a un módulo cerrado (sección 6).

## 1. Tareas

| Tarea | Resultado | Evidencia |
|---|---|---|
| 10.1 | Inspección: la carga de 100 000 registros no era viable con el código de las etapas cerradas | `ETAPA_10.md` §2 |
| 10.2–10.2d | Cuatro ajustes aprobados en página, Archivo Secuencial, B+ y Hash; ninguna técnica exigida cambió | [registro](ETAPA_10_CAMBIOS_MODULOS_PREVIOS.md), [versión para el informe](informe/ajustes_modulos_previos.md) |
| 10.3 | Contrato de experimentos congelado (datos, medición, repeticiones, salida) | `ETAPA_10.md` §4 |
| 10.4 | Paquete `benchmarks/`: datos, harness, experimentos, CLI y reporte, con pruebas | `benchmarks/`, `tests/benchmarks/` |
| 10.5–10.8 | Corridas oficiales: 1 000 y 10 000 registros con 5 repeticiones (350 mediciones); 100 000 con 3 (105 mediciones) | `benchmarks/results/part1_results*.jsonl`, `benchmarks/results/logs/` |
| 10.9 | Confirmación desde SQL: 36 consultas con `EXPLAIN ANALYZE`, con y sin índices | [planes_sql.md](experimentos/planes_sql.md), `part1_sql_plans.jsonl` |
| 10.10 | 11 gráficos y tablas generados desde los resultados crudos con un comando | [experimentos/](experimentos/resultados.md) |
| 10.11 | Informe experimental: método, resultados, ventajas y desventajas, conclusiones, limitaciones | [EXPERIMENTOS.md](EXPERIMENTOS.md) |
| 10.12 | Verificación de punta a punta con servidor real (22/25) y navegador real (7/7) | [ETAPA_10_INTEGRACION.md](ETAPA_10_INTEGRACION.md), `scripts/integration_check.py` |
| 10.13 | Documentos de entrega | sección 3 |
| 10.14 | Esta auditoría y actualización de los documentos de coordinación | sección 5 |

## 2. Definición de Terminado

| Criterio | Estado | Evidencia |
|---|---|---|
| Los datos de 1 000, 10 000 y 100 000 registros se reproducen desde su semilla | Cumple | `benchmarks/datasets.py` (`20 261 000 + N`); `test_datasets_are_reproducible_unique_and_in_random_key_order` |
| Cada medición de `REQUIREMENTS` §9 existe para cada estructura y tamaño, de corridas reales | Cumple | 455 mediciones oficiales; tablas de `experimentos/resultados.md` sin celdas vacías |
| Resultados crudos, configuración y entorno guardados y versionados | Cumple | cada fila JSONL lleva configuración, plataforma, Python, commit y SHA-256 del código; 100 000 sobre el commit limpio `231ffc0` |
| Gráficos y tablas regenerables con un comando | Cumple | `python -m benchmarks report --results ...` |
| Las conclusiones dicen cuándo conviene cada estructura y salen de los datos | Cumple | `EXPERIMENTOS.md` §5–§6, cada afirmación con su cifra |
| El código de experimentos está fuera de `engine/` y `api/` | Cumple | vive en `benchmarks/`; `test_benchmark_code_never_lives_in_or_is_imported_by_the_engine`; ningún archivo de `api/` ni `engine/` lo importa |
| La verificación de punta a punta pasa tras un reinicio limpio | Cumple | reinicio con estado confirmado exacto, tablas, índices y búsquedas indexadas (`ETAPA_10_INTEGRACION.md` §1) |
| La suite estricta completa y las verificaciones del frontend pasan | Cumple | 2968 pruebas con `-W error` en 232 s; `tsc`, 32 pruebas Vitest y build sin errores |
| Existen los documentos de entrega de `REQUIREMENTS` §10 | Cumple | sección 3 (el video y la exposición los graba y presenta el equipo) |
| `PROJECT_CONTEXT.md`, `PLAN_PARTE_01.md`, `AGENTS.md` y `README.md` registran el cierre | Cumple | sección 5 |

## 3. Documentos de entrega (`REQUIREMENTS` §10)

| Requisito | Documento |
|---|---|
| Código fuente en un repositorio Git | este repositorio |
| Documentación técnica / README | [README.md](../README.md) |
| Arquitectura del sistema y diseño arquitectónico | [informe §1](informe/informe_parte_01.md), README "Arquitectura" |
| Organización del código | README "Organización", informe §1 |
| Manual de instalación | README "Requisitos e instalación", [demo.md](demo.md), [despliegue.md](despliegue.md) |
| Video de 5–10 minutos | [guion_video.md](informe/guion_video.md) (grabación a cargo del equipo) |
| Informe incremental | [informe_parte_01.md](informe/informe_parte_01.md) §5 y las auditorías de cada etapa |
| Dominio de datos | informe §2 |
| Explicación de algoritmos | informe §3 |
| Sección experimental | [EXPERIMENTOS.md](EXPERIMENTOS.md), informe §4 |
| Presentación final | [presentacion.md](informe/presentacion.md) (exposición a cargo del equipo) |

## 4. Checklist de la Parte 1 (`REQUIREMENTS` §14)

| Área | Punto | Evidencia principal |
|---|---|---|
| Almacenamiento | Heap File, almacenamiento en páginas, reutilización de espacio | `engine/storage/heap_file.py`, `page.py`; `tests/storage/test_heap_file.py`, `test_heap_free_space.py`, `test_page.py`; experimento de reinserción (+1,2 % con 100 000) |
| | Archivo Secuencial Paginado, inserción ordenada, eliminación lazy, reorganización | `engine/storage/paged_sequential_file.py`; `test_paged_sequential_file.py`, `test_paged_sequential_maintenance.py`, `test_paged_sequential_binary_search.py`, `test_paged_sequential_split.py` |
| Índices | B+ agrupado, B+ no agrupado, Hash extensible | `engine/indexes/`; `test_clustered_bplus.py`, `test_unclustered_bplus.py`, `test_bplus_tree_*.py`, `test_extendible_hash.py`, `test_hash_*.py` |
| Algoritmos externos | External Sort con k-way merge; GROUP BY y JOIN con hashing externo | `engine/operators/`; `tests/operators/test_sorting.py`, `test_grouping.py`, `test_join.py`, `test_partitioning.py` |
| SQL | SELECT, WHERE, ORDER BY, GROUP BY, INSERT, DELETE | `engine/query/`; `tests/query/test_stage7_acceptance.py`, `test_executor_writes.py`, `test_planner_*.py` |
| Transacciones | BEGIN / END TRANSACTION, control de concurrencia | `engine/transactions/`; `tests/transactions/test_controls.py`, `test_locks.py`, `test_sql_integration.py`; integración HTTP y navegador (bloqueo entre sesiones) |
| | Demostración con hilos, condición de carrera, ejecución protegida correcta | `demos/transactions_demo.py` (sin control: 1; con control y en serie: 2); `tests/transactions/test_controlled_evidence.py` |
| Frontend | Paneles Archivos, Consulta, Resultados y Plan | `frontend/src/components/`; Vitest; navegador real 7/7 |
| Experimentos | Datos de 1 000 / 10 000 / 100 000; Heap vs Secuencial; B+ agrupado vs no agrupado; Hash; gráficos; tabla resumen; conclusiones | `EXPERIMENTOS.md`, `experimentos/` |

## 5. Documentos de coordinación actualizados

- `PART_01/ETAPA_10.md`: estado, tareas y Definición de Terminado marcados.
- `PART_01/PLAN_PARTE_01.md`: Etapa 10 cerrada.
- `PROJECT_CONTEXT.md`: alcance actual, etapa actual y contrato de
  experimentos adoptado.
- `AGENTS.md`: última etapa cerrada y bloque actual.
- `README.md`: sección de entrega, instalación, organización y estado.
- `docs/spatial.md` y `PART_02/PLAN_PARTE_02.md`: estado de la Parte 1
  corregido (las corridas de 100 000 están terminadas).

## 6. Pendientes y límites conocidos

1. **Lanzador del servidor (Etapa 9, sin aplicar).** El chequeo de puerto no
   usa `SO_REUSEADDR` y bloquea ~60 s un reinicio inmediato; Ctrl+C termina con
   un traceback de `KeyboardInterrupt` y código -2 aunque la base se cierra
   bien. Las correcciones están descritas en `ETAPA_10_INTEGRACION.md` §4 y
   esperan aprobación por tratarse de un módulo cerrado.
2. **Corridas de 100 000 en Windows (E1.5 de la Parte 2).** Un integrante lanzó
   en Windows otras corridas de 100 000 con resultados separados
   (`part1_e1_5_launch.json`); no están en el repositorio. Las corridas
   oficiales son las de WSL, en la misma máquina que 1 000 y 10 000; las de
   Windows, si se completan, solo sirven como evidencia complementaria y no se
   deben mezclar con las oficiales.
3. **Procedencia.** Las corridas de 1 000/10 000 se hicieron sobre cambios aún
   sin commit, identificados por su SHA-256 del código; las de 100 000 sobre un
   commit limpio. La corrida de planes SQL marca `git_dirty` solo por un archivo
   ajeno sin seguimiento (`BD2_PROYECTO.zip`).
4. **Límites de la Parte 1**, documentados en el informe §6: sin WAL ni
   recuperación ante caídas, un solo proceso por directorio, planner sin
   costos, B+ agrupado reconstruido en cada inserción, SQL acotado.
