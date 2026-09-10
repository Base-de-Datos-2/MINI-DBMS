# Etapa 6 — incremento A: contratos y operadores en streaming

Fecha: **2026-09-10**. Alcance: tareas **6.1 a 6.10** de
[ETAPA_06.md](../ETAPA_06.md), es decir la condición de salida del incremento A
de su sección 9: *pipelines tipados de scan/filter/projection funcionando, con
el ciclo de vida y las decisiones de memoria explícitos*.

Este informe no cierra la Etapa 6. Los incrementos B (ordenamiento externo),
C (agrupación), D (joins), E (índices opcionales) y F (integración y entrega)
siguen pendientes.

## Estado por tarea

| Tarea | Entregable | Estado |
|---|---|---|
| 6.1 | [Inspección y línea base](ETAPA_06_TASK_6_1_INSPECTION.md) | Completa |
| 6.2 | [Decisiones de ejecución](ETAPA_06_TASK_6_2_DECISIONS.md) | Completa |
| 6.3 | `engine/operators/rows.py` — procedencia, identidad calificada, esquemas derivados | Completa |
| 6.4 | `engine/operators/base.py` — `ExecutionOperator`, `execute`, `collect` | Completa |
| 6.5 | `engine/operators/context.py` — presupuesto, reservas, handles | Completa |
| 6.6 | `engine/operators/expressions.py` — predicados tipados ligados | Completa |
| 6.7 | `engine/operators/scan.py` — `TableScan` | Completa |
| 6.8 | `engine/operators/scan.py` — `IndexScan` | Completa |
| 6.9 | `engine/operators/filter.py` — `Filter` | Completa |
| 6.10 | `engine/operators/projection.py` — `Projection` | Completa |

## Decisiones de diseño relevantes

- **El `Operator` de la Etapa 1 se conserva sin cambios.** `ExecutionOperator`
  lo extiende con estado, propiedad de hijos, contadores y descriptor. Las
  pruebas existentes del contrato abstracto siguen pasando intactas.
- **El layout se construye durante `__init__`, no en `open()`.** Un plan que
  nombra una columna inexistente, ambigua o de tipo incompatible falla al
  ensamblarse, no a mitad del flujo. `open()` solo adquiere recursos del run.
- **Identidad de origen separada del nombre publicado.** Un `LayoutField`
  recuerda `(relación, columna)` mientras el esquema de salida puede publicar
  `students.id`. Sin esa separación, un join de dos tablas con columna `id`
  rompía la resolución calificada; el defecto se reprodujo y se corrigió
  durante la implementación.
- **El presupuesto se llama `memory_budget_bytes`** y se documenta como
  memoria de trabajo contabilizada, nunca como garantía sobre el proceso.
  Un contexto anidado reserva sus bytes del padre, de modo que dos operadores
  bloqueantes no pueden prometer la misma memoria.
- **`compare_values` es la única semántica de comparación** de predicados,
  agrupación, join y orden. Reproduce la lógica de `BPlusKeyCodec.compare` sin
  su límite de tamaño de clave indexable.
- **El orden se declara por columna, no por un booleano.** `ordering` devuelve
  `ColumnReference | None`. `HeapFile` devuelve `None`; `PagedSequentialFile`
  devuelve su columna clave; `Projection` conserva el orden heredado solo si
  esa columna sobrevive a la proyección.
- **`collect` exige un `limit` explícito** y falla si el plan produce más filas
  de las pedidas, para no ofrecer una vía cómoda de materializar una tabla
  entera y anular el contrato de streaming.

## Invariantes de la sección 5 cubiertos por este incremento

| # | Invariante | Evidencia |
|---:|---|---|
| 1 | Esquema de salida estable | `ExecutionOperator.next()` rechaza toda fila que no coincida con el esquema anunciado (`test_a_row_that_violates_the_advertised_schema_fails_the_run`) |
| 2 | Se preservan las ocurrencias | `test_filter_never_deduplicates_equal_rows`, `test_projection_preserves_every_occurrence_of_identical_rows` |
| 3 | La proyección no es DISTINCT | `test_projection_is_not_distinct` |
| 4 | Los operadores en streaming no acumulan su entrada | `TableScan`, `IndexScan`, `Filter` y `Projection` mantienen solo un cursor o una fila |
| 5 | B+ da igualdad y rango; hash solo igualdad | `test_a_range_over_a_hash_index_is_refused_rather_than_faked` |
| 6 | Semántica de comparación única | `compare_values` compartida; `test_comparison_refuses_mismatched_types_without_implicit_conversion` |
| 8 | Agotamiento, parada temprana y excepción liberan recursos | `test_execute_closes_when_the_consumer_stops_early`, `test_execute_closes_when_the_plan_fails_mid_stream`, `test_a_failing_open_releases_partially_acquired_children_and_stays_closed` |
| 9 | Ejecución de solo lectura sobre el almacenamiento base | Ningún operador llama a `insert`, `delete` ni `update` |
| 10 | El límite cubre el trabajo simultáneo | `test_nested_contexts_cannot_promise_the_same_bytes_twice` |
| 11 | Las métricas cuentan trabajo real | `rows_examined` y `rows_emitted` se cuentan por separado (`test_filter_counts_rows_examined_and_emitted_separately`) |
| 12 | El comportamiento externo se demuestra | **Pendiente**: corresponde a los incrementos B, C y D |

Los invariantes 7 (propiedad de archivos temporales) y 12 quedan fuera de este
incremento por construcción.

## Ejemplos de aceptación instanciados

Del catálogo de la sección 11 de [ETAPA_06.md](../ETAPA_06.md):

- **Ejemplo A — proyección filtrada:** implementado y ejecutado contra
  almacenamiento paginado real en
  `tests/integration/test_stage6_pipelines.py::test_example_a_filtered_projection_runs_over_real_paged_storage`.
  El descriptor del plan reproduce literalmente la pila
  `Projection → Filter → TableScan`.
- **Ejemplo E — cerrar y reejecutar:** implementado en
  `test_example_e_close_everything_reopen_and_rerun_the_same_pipeline`, con
  gestores nuevos tras reabrir y **dos presupuestos válidos distintos** que
  producen la misma respuesta lógica.
- **Ejemplos B, C y D** requieren agrupación, joins y ordenamiento externo:
  pendientes de los incrementos B a D.

## Validación

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
.venv/bin/python -m compileall -q engine tests
git diff --check
```

| Medida | Resultado |
|---|---|
| Línea base heredada | 1716 pruebas aprobadas |
| Suite completa tras el incremento A | **1848 aprobadas en 39,44 s**, advertencias como errores, sin omisiones ni xfails |
| Pruebas nuevas | **132** (`test_rows` 17, `test_context` 13, `test_expressions` 20, `test_lifecycle` 22, `test_scan` 27, `test_filter_projection` 24, integración 9) |
| Regresión de Etapas 1–5 | Sin cambios: las 1716 anteriores siguen pasando |
| `compileall` y `git diff --check` | Correctos |

### Defectos encontrados y corregidos durante la implementación

1. **Identidad calificada rota tras `combine`.** El nombre publicado
   sobrescribía el nombre de origen, de modo que
   `ColumnReference("id", "students")` dejaba de resolver sobre un layout de
   join. Se separaron ambos conceptos y se añadió `published_name()`.
2. **`__all__` con constantes enteras.** La prueba de arquitectura existente
   falló en 15 parametrizaciones porque un `int` no tiene `__module__`. Las
   constantes salieron de `__all__` conservando su importabilidad.

Ambos fueron detectados por las pruebas antes de cualquier entrega, no
después.

## Límite de este informe

Se determinaron las tareas **6.1–6.10**. No se certifica la Definition of Done
de la Etapa 6, que exige además ordenamiento externo con mezcla k-way,
agrupación externa, joins optimizados, gestión de temporales y evidencia de
volcado forzado a disco.
