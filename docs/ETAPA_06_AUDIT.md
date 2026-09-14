# Auditoría de cierre de la Etapa 6

> Nota de revisión (2026-09-13): este documento conserva el cierre histórico.
> La [revisión independiente](ETAPA_06_REVIEW_2026_09_13.md) encontró defectos
> posteriores a esa verificación. La [corrección del primer bloque](ETAPA_06_REVIEW_6_5_6_11_6_15_6_16.md)
> se limita a 6.5, 6.11, 6.15 y 6.16. El [segundo bloque](ETAPA_06_REVIEW_6_19_6_27_6_30.md)
> revisa 6.19 y 6.27–6.30. Ninguno ratifica por sí solo los 59 criterios.

Fecha: **2026-09-11**. Alcance: operadores relacionales y algoritmos externos,
tareas **6.1 a 6.31** de [ETAPA_06.md](../ETAPA_06.md).

Resultado: **Etapa 6 completa.** Se cumplen los **59 criterios** de la
[Definition of Done](../ETAPA_06.md#13-definition-of-done); tres de ellos llevan
una salvedad declarada que no impide el cumplimiento y se explica abajo. La
suite completa pasa **2252 pruebas con advertencias tratadas como errores**,
ya integrada la revisión de la Etapa 5 fusionada desde `main`.
**La Etapa 7 no se ha iniciado.**

## Informes por incremento

| Incremento | Tareas | Informe |
|---|---|---|
| Inspección y decisiones | 6.1, 6.2 | [Inspección](ETAPA_06_TASK_6_1_INSPECTION.md), [decisiones](ETAPA_06_TASK_6_2_DECISIONS.md) |
| A — contratos y streaming | 6.1–6.10 | [Incremento A](ETAPA_06_INCREMENTO_A.md) |
| B — temporales y ordenamiento | 6.11–6.16 | [Incremento B](ETAPA_06_INCREMENTO_B.md) |
| C — agrupación | 6.17–6.21 | [Incremento C](ETAPA_06_INCREMENTO_C.md) |
| D — joins | 6.22–6.25 | [Incremento D](ETAPA_06_INCREMENTO_D.md) |
| E — índices (opcional) | 6.26 | [Incremento E](ETAPA_06_INCREMENTO_E.md) |
| F — integración y cierre | 6.27–6.31 | [Incremento F](ETAPA_06_INCREMENTO_F.md) |

## Requisitos oficiales satisfechos

| Requisito de `REQUIREMENTS.md` | Ruta física | Evidencia de volcado real |
|---|---|---|
| §5.1 `ORDER BY` con external sorting y mezcla k-way | `ExternalSort` | 36 runs, fan-in 2, 6 pasadas sobre 2000 filas |
| §5.2 `GROUP BY` con hashing externo | `ExternalHashGroup` | 28 particiones, 13 reparticiones, 400 grupos, 0 fallbacks |
| §5.3 `JOIN` con hashing externo | `GraceHashJoin` | entradas 13,1× el presupuesto, 16 pares, 0 fallbacks |

Estas rutas están implementadas y demostradas **a nivel físico**. Su conexión a
la sintaxis SQL es trabajo de la Etapa 7; esta auditoría no afirma lo
contrario.

## Evidencia por criterio

Cada fila corresponde al checklist de la sección 13, en el mismo orden.

### Prerrequisitos y contratos

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 1 | Se comprobó la Etapa 5 contra el repositorio real | [Inspección 6.1](ETAPA_06_TASK_6_1_INSPECTION.md): 1716 pruebas reproducidas en entorno nuevo; revisión 5.16–5.27 integrada después y verificada con la suite completa (ver A) | Cumple |
| 2 | Se reportaron los fallos de la línea base anterior | No hubo ninguno: 1716 aprobadas, sin omisiones | Cumple |
| 3 | Las decisiones de la sección 6 son explícitas y están aprobadas | [Decisiones 6.2](ETAPA_06_TASK_6_2_DECISIONS.md), promovidas a `PROJECT_CONTEXT.md` | Cumple, con salvedad B |
| 4 | Un ciclo de vida y una convención de agotamiento compartidos | `ExecutionOperator`; `next()` devuelve `None`, nunca `StopIteration`; `test_lifecycle.py` | Cumple |
| 5 | Esquemas de salida y columnas calificadas correctos | `RowLayout.combine` publica `students.id`; `test_rows.py` | Cumple |
| 6 | Las filas derivadas no se hacen pasar por registros persistidos | Filas agrupadas con procedencia vacía; joins con procedencia combinada | Cumple |
| 7 | Semántica de duplicados, null, float, agrupación y join probada | Rechazo de NULL y NaN, cero con signo, infinitos, multiplicidad `m*n` | Cumple |
| 8 | Propiedad de memoria y recursos temporales definida | `ExecutionContext`, `operator_context`, `TemporaryWorkspace` | Cumple |

### Operadores en streaming y rutas de acceso

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 9 | `TableScan` transmite registros activos de Heap y secuencial | `test_scan.py`: vacío, una fila, multipágina, slots borrados y reusados | Cumple |
| 10 | `IndexScan` B+ soporta acceso exacto y por rango | Límites inclusivos, exclusivos y abiertos; rango invertido rechazado | Cumple |
| 11 | `IndexScan` hash solo igualdad, sin falsos rangos | Rango sobre hash lanza `UnsupportedAccessError` | Cumple |
| 12 | Resultados grandes no eluden el modelo de memoria | Los operadores en streaming retienen a lo sumo una fila | Cumple, con salvedad C |
| 13 | RIDs obsoletos o inválidos se tratan explícitamente | `InvalidReferenceError` en `IndexScan` e `IndexNestedLoopJoin` | Cumple |
| 14 | `Filter` retiene solo filas coincidentes sin materializar | Estado constante; `test_filter_projection.py` | Cumple |
| 15 | `Projection` preserva multiplicidad y emite el esquema correcto | `test_projection_is_not_distinct` | Cumple |

### Ordenamiento externo

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 16 | Chunks y espacio de trabajo caben en su memoria | Admisión reservada antes de retener | Cumple |
| 17 | Runs escritos en almacenamiento temporal real | Vía `PageManager`, con contadores reales | Cumple |
| 18 | Una política de comparación y desempate en runs y pasadas | `BoundSortSpec.key` único; desempate por índice de run | Cumple |
| 19 | Mezcla k-way con buffers y handles acotados | Fan-in derivado de recursos | Cumple |
| 20 | Más runs que fan-in se resuelven con varias pasadas | `_reduce_runs` | Cumple |
| 21 | Una prueba fuerza al menos dos pasadas | `test_hard_gate_sort_forces_more_runs_than_fan_in_and_two_passes` | Cumple |
| 22 | Salida ordenada con el multiset exacto de la entrada | Oráculo `sorted` estable, nueve formas de datos, tres presupuestos | Cumple |
| 23 | Cierre temprano y fallos limpian los runs intermedios | Fallos inyectados en mezcla final, pasada intermedia y volcado | Cumple |

### Agrupación

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 24 | Agregados con acumulación y finalización probadas | `test_aggregates.py`, incluida la fusión de `AVG` | Cumple |
| 25 | Comportamiento vacío, global y agrupado explícito | Vacío agrupado: 0 filas; global: `COUNT=0`; `MIN`/`MAX`/`AVG` global vacío: error | Cumple |
| 26 | Procesa más grupos distintos de los que caben en memoria | `test_hard_gate_grouping_forces_group_states_beyond_the_grant` | Cumple |
| 27 | El desborde parcial no duplica ni pierde la fila disparadora | Estado tentativo descartado; conteos exactos tras desborde | Cumple |
| 28 | Las colisiones usan igualdad completa de clave | Hash constante: resultados correctos | Cumple |
| 29 | Una clave caliente no crea una lista ilimitada de filas | 20 000 filas en un grupo, estado de tamaño fijo | Cumple |
| 30 | La repartición termina por progreso y fallback probado | Detección de no-progreso y `max_level` | Cumple |
| 31 | La salida agrupada no promete orden | `ordering` es `None` | Cumple |
| 32 | La optimización aprobada tiene evidencia observable | `HashGroupMetrics` y descriptor | Cumple |

### Joins

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 33 | `NestedLoopJoin` es una línea base independiente y correcta | No usa hashing; coincide con las otras dos rutas | Cumple |
| 34 | Entradas internas no repetibles con volcado o contrato de rescan | Volcado siempre; productor que prohíbe reabrir | Cumple |
| 35 | El kernel guarda todas las ocurrencias de build | Bucket con todas las filas | Cumple |
| 36 | `GraceHashJoin` particiona más allá de su asignación | `test_hard_gate_grace_join_uses_real_partitions_not_only_its_kernel` | Cumple |
| 37 | Particiones emparejadas con la misma normalización y hash | `partition_hash` compartido; `JoinSpec` exige un tipo por pareja | Cumple |
| 38 | El intercambio del lado de build preserva el orden de columnas | `test_grace_join_swaps_the_build_side_towards_the_smaller_partition` | Cumple |
| 39 | Claves duplicadas producen `m*n` coincidencias en flujo | Ejemplo C: 6 filas; proyección de filas idénticas: 20 | Cumple |
| 40 | Sesgo y no-progreso terminan con un fallback acotado | Bucle anidado por bloques; hash constante | Cumple |
| 41 | La optimización aprobada tiene evidencia observable | `GraceHashJoinMetrics` y descriptor | Cumple |

### Composición, persistencia y limpieza

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 42 | Planes manuales sin SQL, HTTP ni frontend | `PhysicalPlan`; `test_architecture.py` prohíbe esas dependencias | Cumple |
| 43 | Composiciones con reservas simultáneas compatibles | `operator_context`; tres bloqueantes anidados con el presupuesto por defecto | Cumple |
| 44 | El runner no recolecta resultados de tamaño arbitrario | `collect` y `run_plan` exigen `limit` y no truncan en silencio | Cumple |
| 45 | Temporales completos se reabren con lectores nuevos | `test_a_completed_temporary_file_reopens_with_fresh_readers` | Cumple |
| 46 | Operadores correctos sobre tablas e índices reabiertos | Reapertura vía `Catalog` con gestores nuevos | Cumple |
| 47 | Los operadores de solo lectura preservan tablas e índices | Comparación **byte a byte** antes y después | Cumple |
| 48 | Éxito, parada temprana y excepciones liberan recursos | Directorios temporales ausentes tras cada camino | Cumple |
| 49 | Temporales truncados o corruptos fallan con errores de dominio | `CorruptTemporaryError` | Cumple |
| 50 | La limpieza nunca toca archivos ajenos o permanentes | Archivo ajeno y tabla base intactos; `rmdir`, nunca borrado recursivo | Cumple |

### Observabilidad y entrega

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 51 | Los descriptores describen operadores y rutas reales | Construidos desde la instancia; reflejan fallbacks | Cumple |
| 52 | E/S real distinguida de estimaciones y sin doble conteo | No hay estimaciones; contadores locales; tiempos inclusivos no sumados | Cumple |
| 53 | Memoria máxima, espacio temporal y handles observables | `PlanReport` y métricas por operador | Cumple, con salvedad D |
| 54 | Las pruebas diferenciales preservan la semántica de multiset | Comparación con `Counter`, nunca con conjuntos | Cumple |
| 55 | Presupuestos válidos distintos dan resultados equivalentes | `test_results_are_independent_of_the_valid_memory_budget` | Cumple |
| 56 | Pasan las pruebas de la Etapa 6 y de las anteriores | 2252 aprobadas, incluida la Etapa 5 revisada | Cumple |
| 57 | Decisiones estables y limitaciones documentadas | `PROJECT_CONTEXT.md` y esta auditoría | Cumple |
| 58 | Los metadatos de etapa registran el cierre y el traspaso | `PLAN.md`, `AGENTS.md`, `PROJECT_CONTEXT.md`, `ETAPA_06.md` | Cumple |
| 59 | No se mezcló implementación de etapas futuras | Sin parser, planner, AST, API ni transacciones | Cumple |

## Salvedades declaradas

Ninguna impide el cumplimiento del criterio correspondiente, pero ninguna debe
quedar oculta. Quedan **tres vigentes** (B, C y D); la A se resolvió después
del cierre.

**A. Revisión de la Etapa 5 — resuelta.** Al cerrar esta etapa, la revisión
posterior de los bloques 5.16–5.27 seguía abierta, con hallazgos en 5.23
(rollback Heap/índice), 5.25 (E/S tipada de creación), 5.26 (validación
diferencial por mutación) y 5.27 (trazabilidad de 47 criterios). El equipo la
completó en `main` ([5.16–5.21](ETAPA_05_REVIEW_5_16_5_21.md),
[5.22–5.27](ETAPA_05_REVIEW_5_22_5_27.md)) y se fusionó en esta rama.

El cambio no era solo documental: el adaptador hash ahora **valida la
correspondencia clave/RID también en `search()`**, **verifica la cobertura al
reabrir** y **bloquea consultas sobre un índice marcado incompleto**. Todo ello
refuerza, sin contradecir, lo que asumen `IndexScan` e `IndexNestedLoopJoin`.
Tras el merge, la suite completa pasa **2252 pruebas** (1772 de las Etapas 1–5
revisadas más las 480 de esta etapa) **sin cambiar una línea de
`engine/operators/`**, que es la verificación de integración que importa. Esta
salvedad ya no aplica y se conserva solo como registro.

**B. Aprobación de las decisiones.** Las decisiones de la tarea 6.2 están
registradas, se aplicaron de forma consistente y se revisaron incremento a
incremento. Varias condicionan directamente la Etapa 7 (subconjunto de
predicados, agregados adoptados, ausencia de NULL, comparación sin coerción
numérica), así que conviene que **el equipo las revise antes de iniciarla**.

**C. Guardián de ciclos del recorrido B+.** `BPlusTree.search()` y
`range_search()` mantienen un conjunto `visited` de páginas hoja para detectar
ciclos, que crece con las hojas recorridas y **no se carga al presupuesto** de
ejecución. Es un guardián de integridad de la Etapa 4, no una caché de filas,
y se declaró en la [inspección 6.1](ETAPA_06_TASK_6_1_INSPECTION.md). Los
operadores de la Etapa 6 no retienen filas de esos recorridos.

**D. Espacio temporal acumulado, no pico vivo.** El espacio temporal se expone
como bytes volcados y páginas temporales escritas y leídas, **acumulados** por
operador. No se mide un pico de bytes temporales vivos simultáneamente. Del
mismo modo, las páginas de las **tablas base** siguen contándose en su propio
`PageManager` y no se agregan en `PlanReport`. Ambos son candidatos naturales
para la Etapa 10.

## Validación final

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
.venv/bin/python -m compileall -q engine tests
git diff --check
```

| Medida | Resultado |
|---|---|
| Línea base de entrada (Etapas 1–5) | 1716 pruebas aprobadas |
| Suite completa de cierre | **2196 aprobadas en 163,33 s**, advertencias como errores, sin omisiones ni xfails |
| Línea base de las Etapas 1–5 tras la revisión 5.16–5.27 | 1772 pruebas |
| Suite tras fusionar esa revisión desde `main` | **2252 aprobadas en 170,00 s**, advertencias como errores, sin omisiones ni xfails |
| Pruebas añadidas por la Etapa 6 | **480** |
| Regresión de las Etapas 1–5 | Las 1716 originales y las 1772 revisadas siguen aprobando; la Etapa 6 solo añadió cuatro subclases de error en `engine/errors.py` |
| `compileall` y `git diff --check` | Correctos |

Entorno de esta verificación: Linux (WSL2), Python 3.11.9, pytest 8.4.2. Las
auditorías de etapas anteriores se ejecutaron en Windows con Python 3.12.4.

## Condición para iniciar la Etapa 7

Según la sección 17 de la guía, la capa física ya puede:

- recibir expresiones ya ligadas y especificaciones de acceso explícitas;
- transmitir resultados de scan, filtro y proyección;
- ordenar más allá de su memoria disponible con mezcla k-way;
- agrupar y unir con las rutas de optimización requeridas y demostradas;
- componer estas operaciones de forma segura dentro del contrato de recursos;
- exponer esquemas, descripciones de operadores, errores y estadísticas
  medidas reales;
- liberar recursos de forma fiable tras completarse o fallar.

La Etapa 7 deberá generar `ETAPA_07.md` y conciliarlo con el
`PROJECT_CONTEXT.md` vigente antes de implementar nada. Su responsabilidad será
traducir el subconjunto SQL requerido a estos operadores físicos ya probados,
sin reimplementar almacenamiento, ordenamiento, particionamiento, agrupación
ni joins.
