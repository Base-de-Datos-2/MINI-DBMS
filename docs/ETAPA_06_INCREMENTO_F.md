# Etapa 6 — incremento F: integración, observabilidad y cierre

Fecha: **2026-09-11**. Alcance: tareas **6.27 a 6.31** de
[ETAPA_06.md](../ETAPA_06.md). La condición de salida del incremento F es:
*planes manuales, evidencia medida, limpieza ante fallos y suite de regresión
aprobada*.

## Estado por tarea

| Tarea | Entregable | Estado |
|---|---|---|
| 6.27 | `engine/operators/pipeline.py` — `PhysicalPlan`, `run_plan` | Completa |
| 6.28 | Descriptores con identidad y esquema, tiempo inclusivo, `PlanReport`, errores de dominio | Completa |
| 6.29 | `tests/integration/test_stage6_persistence.py` | Completa |
| 6.30 | `tests/integration/test_stage6_differential.py` | Completa |
| 6.31 | `PROJECT_CONTEXT.md`, `PLAN.md`, `AGENTS.md`, [auditoría de cierre](ETAPA_06_AUDIT.md) | Completa |

## 6.27 — Runner de planes físicos

`PhysicalPlan` abre un contexto de ejecución fresco, abre la raíz, transmite
sus filas y cierra todo en cualquier camino de salida. `run_plan` lo usa para
ejecutar hasta el final y devolver filas más un `PlanReport` medido.

Lo que **no** hace es tan importante como lo que hace: no analiza texto, no
elige rutas de acceso y no reescribe operadores. Es el *pequeño ayudante de
ciclo de vida* que la sección 4 de la guía declara dentro del alcance, no el
ejecutor de la Etapa 7.

`verify()` comprueba expectativas antes de ejecutar: columnas, tipos y orden.
Verificar un orden **pregunta a los operadores qué garantizan de verdad**, y
un plan cuya ruta de acceso no entrega el orden pedido se rechaza con
`UnsupportedAccessError` en vez de producir filas silenciosamente desordenadas.

## 6.28 — Descriptores, métricas y errores

### Descriptores

`OperatorDescriptor` pasó de nombre y detalles a una descripción completa
derivada de la instancia viva:

| Campo | Contenido |
|---|---|
| `operator_id` | Ruta posicional estable en el plan: `0`, `0.0`, `0.1`… |
| `output_columns` | Pares `(nombre, tipo)` realmente emitidos |
| `details` | Ruta de acceso, especificación ligada y estrategia usadas de verdad |
| `ordered` / `ordered_by` | Solo si el operador garantiza realmente ese orden |
| `rows_examined` / `rows_emitted` | Contadores **locales** |
| `elapsed_seconds` | Tiempo **inclusivo** |

Un fallback cambia lo que dice el descriptor, porque se construye desde la
instancia tras ejecutarse, no desde una etiqueta fijada al montar el plan.

### Reglas de conteo declaradas

- Las filas son **locales** a cada operador. Sumar las de un padre y un hijo
  contaría dos veces la misma fila, así que el informe expone la salida de la
  raíz y nunca una suma.
- El tiempo es **inclusivo**: cubre `open` y `next` del operador, que incluyen
  las llamadas a sus hijos. Los tiempos de padre e hijo se solapan y no se
  suman; el informe usa el de la raíz. Hay una prueba que comprueba que un
  padre nunca es más rápido que su hijo.
- No existe ninguna estimación en esta etapa: todo número es observado.

### Errores de dominio estables

Añadidos en `engine/errors.py` como subclases de `ValidationError`, de modo
que todo código existente que captura `ValidationError` sigue funcionando:

| Error | Se lanza cuando |
|---|---|
| `UnsupportedAccessError` | Una ruta de acceso no ofrece la capacidad pedida: rango sobre hash, índice sobre otra columna, orden no garantizado |
| `InsufficientBudgetError` | Un presupuesto o tope de handles es demasiado pequeño |
| `OversizedRowError` | Una fila supera un límite documentado de memoria o de formato temporal |
| `CorruptTemporaryError` | Un temporal está truncado, mal enmarcado o tiene otra versión |

Los errores de esquema/expresión y de RID obsoleto ya tenían vocabulario
estable (`SchemaError`, `UnknownColumnError`, `InvalidReferenceError`).

## Dos defectos de recursos encontrados en este incremento

Ambos los destapó la tarea 6.29 al ejecutar planes **sin presupuestos
explícitos**. Todas las pruebas anteriores de operadores anidados habían dado
presupuestos a mano, y eso los ocultaba.

### 1. El primer operador bloqueante se quedaba con todo el presupuesto

Es exactamente el riesgo que la sección 14 de la guía lista como *«every child
independently consumes the full budget»*.

Sin presupuesto explícito, cada operador bloqueante tomaba
`min(DEFAULT, presupuesto_del_padre)`, es decir, **todo** el presupuesto del
padre. Como los hijos se abren antes que los padres, en
`ExternalSort(ExternalHashGroup(...))` la agrupación se abría primero y se
llevaba los 262 144 bytes, y la ordenación de arriba fallaba:

```text
InsufficientBudgetError: plan: cannot reserve 262144 bytes; 0 of 262144 remain
```

**Corrección:** una regla única, `operator_context`, que usan los tres
operadores bloqueantes. Una petición explícita se concede exacta; sin ella, el
operador toma **la mitad de lo que su padre aún tiene disponible**, nunca menos
que su propio mínimo. Si eso no cabe, el plan se rechaza con
`InsufficientBudgetError` antes de leer una sola fila, con un mensaje que dice
que los operadores bloqueantes no caben simultáneamente. Se comprobó una
cadena de tres (`GraceHashJoin` → `ExternalHashGroup` → `ExternalSort`) dentro
del presupuesto por defecto.

### 2. Los handles de un contexto anidado eran invisibles para la raíz

Un `HandleLease` tomado en un contexto hijo solo se contaba en ese hijo. El
contexto raíz no lo veía, con dos consecuencias:

- el `PlanReport` informaba `peak_handles=0` aunque las particiones habían
  tenido varios archivos abiertos: **el informe mentía**;
- dos contextos hermanos podían superar juntos el tope de handles de la raíz.

**Corrección:** un lease en un contexto anidado toma también un lease en cada
ancestro, primero el del ancestro. La raíz ve y acota todos los handles del
plan, y liberar un lease libera la cadena entera.

## 6.29 — Persistencia, limpieza y fallos

La frontera es deliberada: reabrir fuentes persistidas y temporales completos
es obligatorio; **reanudar una consulta interrumpida por una caída del proceso
no lo es**, y no se simula.

| Requisito de la guía | Prueba |
|---|---|
| Crear tablas e índices, cerrarlos, destruir sus gestores y reabrir vía `Catalog` | `test_operators_run_over_sources_reopened_through_the_catalog` |
| Temporales completos que se reabren con lectores nuevos | `test_a_completed_temporary_file_reopens_with_fresh_readers` |
| Registros truncados | `test_a_truncated_temporary_file_fails_through_a_domain_error` |
| Formato temporal no soportado | `test_an_unsupported_temporary_format_is_refused` |
| Fallos de E/S de lectura y escritura | fallo en la mezcla final, en una pasada intermedia y al volcar |
| Parar tras pocas filas ordenadas, agrupadas o unidas | dos pruebas de parada temprana |
| Fallo del padre después de que el hijo creara temporales | `test_a_parent_failing_after_a_child_created_temporaries_cleans_up_both` |
| Comparar el contenido de los archivos base antes y después | `test_a_read_only_query_does_not_modify_its_base_files`, **comparación byte a byte** |
| Archivo ajeno en el directorio temporal padre | `test_cleanup_is_scoped_to_the_execution_directory` |

## 6.30 — Pruebas diferenciales y de estrés

Política de oráculo: bucles, diccionarios y `sorted` de solo pruebas sobre
fixtures acotados. Los resultados desordenados se comparan como **multisets
con `Counter`**, nunca como conjuntos; los ordenados, como secuencias.

| Dimensión | Cubierta con |
|---|---|
| Cardinalidad | `empty`, `one`, fixtures de una página, multipágina y mayores que la memoria |
| Anchura | valores fijos, cadenas variables hasta 600 bytes, filas unidas |
| Duplicados | `duplicates`, claves repetidas de grupo y de join |
| Distribución | `uniform`, `sorted`, `reverse`, `dominant`, `all_one_key` |
| Hash | normal, colisiones, hash deliberadamente constante |
| Ciclo de vida | consumo total, parada temprana, excepción, ejecución fresca tras un fallo |
| Almacenamiento | Heap, secuencial, B+ reabierto, hash reabierto |
| Recursos | tres presupuestos válidos, presupuesto bajo el mínimo, tope de handles |
| Composición | varios operadores en streaming y bloqueantes anidados |

Las **cinco puertas de evidencia duras** de la guía tienen cada una su prueba
`test_hard_gate_*`. La independencia respecto del presupuesto se comprueba con
el mismo pipeline completo bajo tres presupuestos distintos, que deben producir
exactamente las mismas filas.

## Validación

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
.venv/bin/python -m compileall -q engine tests
git diff --check
```

| Medida | Resultado |
|---|---|
| Línea base del incremento E | 2062 pruebas aprobadas |
| Suite completa de cierre | **2196 aprobadas en 163,33 s**, advertencias como errores, sin omisiones ni xfails |
| Pruebas nuevas del incremento F | **134** (`test_pipeline` 21, `test_stage6_persistence` 19, `test_stage6_differential` 94) |
| `compileall` y `git diff --check` | Correctos |
