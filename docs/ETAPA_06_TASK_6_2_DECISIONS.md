# Decisiones de ejecución de la Etapa 6 — tarea 6.2

Fecha: **2026-09-10**. Convierte las propuestas de la sección 6 de
[ETAPA_06.md](../ETAPA_06.md) en decisiones explícitas del proyecto. Se apoya
en la [inspección 6.1](ETAPA_06_TASK_6_1_INSPECTION.md) y no modifica ningún
requisito oficial de [REQUIREMENTS.md](../REQUIREMENTS.md). Las decisiones
estables se promoverán a [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) en la
tarea 6.31.

## 1. Ciclo de vida y contrato de fila

| Decisión | Valor adoptado |
|---|---|
| Ciclo de vida | Se conserva el `Operator` de la Etapa 1: `open()` / `next()` / `close()` |
| Fin de flujo | `next()` devuelve `None`; **nunca** `StopIteration` |
| Contexto | `open(context=None)` acepta un `ExecutionContext` opcional; el operador raíz lo propaga a sus hijos |
| Reejecución | `close()` seguido de `open()` inicia un run nuevo; abrir un operador ya abierto o agotado lanza `RuntimeError` |
| Estados | `created → open → (exhausted \| failed) → closed`; `close()` es idempotente en todos ellos |
| Propiedad | Cada operador cierra a sus hijos y sus cursores; nunca cierra almacenamientos ni índices prestados |
| Fila | `Record` sin envoltorio nuevo; la identidad de columna se resuelve al construir cada operador a posiciones preligadas |
| Procedencia | Opcional, `RowProvenance(relation, rid)`; jamás se fabrica un RID para una fila derivada |

Se mantiene `Record` como fila de ejecución porque es inmutable y ya valida
tipos: un consumidor que retiene una fila no puede observar mutaciones cuando
el productor avanza, sin necesidad de copias defensivas.

## 2. Identidad de columna

Las referencias se resuelven con **identidad calificada opcional**
`(relación, columna)`, y se preligan a posiciones enteras durante la construcción
del plan.
Un nombre sin calificar es válido solo si es único en el esquema de entrada;
si dos entradas de un join aportan `id`, un nombre desnudo es ambiguo y se
rechaza con `ValidationError` antes de leer ninguna fila.

## 3. Semántica de valores

| Aspecto | Decisión |
|---|---|
| NULL | **No soportado.** Ninguna fila puede contener `None`; no se implementa lógica de tres valores. Un predicado sobre datos válidos es TRUE o FALSE |
| Comparación | Una única función `compare_values(data_type, izq, der)` en `engine/operators/expressions.py`, compartida por predicados, claves de agrupación, claves de join y ordenamiento, para que no puedan discrepar. Reproduce la semántica lógica de `BPlusKeyCodec.compare` pero **sin** sus límites de tamaño codificado: un `WHERE` puede comparar una cadena más larga que cualquier clave indexable |
| Coerción numérica | **Ninguna.** `INTEGER` y `FLOAT` no se comparan entre sí; los tipos deben coincidir exactamente, igual que en `Record` e índices |
| `BOOLEAN` | Comparable por igualdad y por orden (`False < True`), coherente con Python |
| `VARCHAR` | Orden Unicode nativo, sensible a mayúsculas, igual que `OrderedIndex` |
| `NaN` | **Rechazado** como clave de comparación, ordenamiento, agrupación o join, con `ValidationError`. Se permite como valor transportado en columnas no usadas como clave |
| Infinitos | Permitidos |
| Cero con signo | `-0.0` y `0.0` son el mismo valor de agrupación y comparación, coherente con el cero canónico de los codecs |

## 4. Subconjunto de predicados aprobado

Comparaciones `=`, `<>`, `<`, `<=`, `>`, `>=` entre una referencia de columna y
un literal, o entre dos referencias de columna del mismo tipo. Composición
booleana `AND`, `OR`, `NOT`. No se admiten `LIKE`, `IN`, `BETWEEN`,
subconsultas ni aritmética en esta etapa; se rechazan explícitamente en vez de
degradarse en silencio. **No se usa `eval` ni `exec`, y ningún predicado se
expresa como cadena SQL.**

## 5. Presupuesto de memoria

| Decisión | Valor adoptado |
|---|---|
| Unidad | **Bytes de trabajo contabilizados**, no RSS del proceso |
| Nombre | `ExecutionContext.memory_budget_bytes`, para no sugerir una garantía de proceso |
| Modelo | Conservador: se contabiliza el tamaño serializado de la fila mediante `RecordCodec` más una sobrecarga fija declarada por fila retenida |
| Reserva | Se reserva **antes** de retener o crecer estado y se libera al volcar a disco o al cerrar |
| Anidamiento | Un operador bloqueante hijo recibe una subreserva del padre; si el presupuesto restante es inferior al mínimo viable, la construcción falla antes de ejecutar |
| Mínimo viable | Se declara por operador; por debajo de él se lanza `ValidationError` en vez de degradar a memoria ilimitada |
| Fila sobredimensionada | Error determinista `ValidationError` cuando una sola fila no cabe en el presupuesto mínimo |
| Descriptores | Los runs se catalogan en disco y solo se cargan los del fan-in actual; el fan-out de particiones es acotado y no se guarda una lista ilimitada de metadatos |
| Handles | Se acotan por separado del límite de bytes |

## 6. Rutas de optimización seleccionadas

Se aprueba la **ruta por defecto** de la guía, con las dos decisiones tomadas
de forma independiente:

| Obligación de [REQUIREMENTS.md](../REQUIREMENTS.md) | Ruta aprobada |
|---|---|
| `ORDER BY` (§5.1) | `ExternalSort`: generación de runs acotados por memoria + mezcla k-way con fan-in limitado y múltiples pasadas |
| `GROUP BY` (§5.2) | `ExternalHashGroup`: particionamiento en disco por hash de la clave de grupo, con agregación acotada por partición |
| `JOIN` (§5.3) | `GraceHashJoin`, con `NestedLoopJoin` como línea base de corrección |

Las estrategias asistidas por índice de la tarea 6.26 quedan como **opcionales**
y no sustituyen a las anteriores.

### Retrocesos acotados ante sesgo

- **Agrupación:** si una partición no cabe en memoria, se reparticiona con una
  semilla distinta hasta un número máximo de niveles declarado. Agotado ese
  límite, se agrega esa partición mediante ordenamiento externo por clave de
  grupo, que siempre termina.
- **Join:** misma política de reparticionamiento; agotado el límite, la
  partición conflictiva se resuelve con el join anidado de línea base, que no
  requiere que ningún lado quepa en memoria.

Ambos retrocesos son terminantes por construcción y quedan instrumentados.

## 7. Agregados adoptados

`COUNT(*)`, `COUNT(columna)`, `SUM`, `MIN`, `MAX` y `AVG`. Todos mantienen
estado de tamaño constante por grupo. Sobre entrada vacía, un `GROUP BY` no
emite filas; `COUNT` sin grupos devuelve `0` solo cuando se solicita una
agregación escalar sin claves. `SUM`/`AVG` exigen columna numérica y
`MIN`/`MAX` cualquier tipo comparable. Una fila de salida agrupada contiene
**claves de grupo más agregados**, nunca una columna sin agrupar arbitraria.

## 8. Semántica de join

Mínimo obligatorio: **equijoin interno** sobre una o más parejas de columnas
del mismo tipo. Se preserva la multiplicidad: `m` coincidencias por la
izquierda y `n` por la derecha producen `m*n` filas. La proyección **no** es
`DISTINCT`. Los outer joins, los joins por predicado general y las
subconsultas correlacionadas quedan fuera de la etapa.

## 9. Formato y ciclo de vida de los temporales

| Decisión | Valor adoptado |
|---|---|
| Formato | Flujo secuencial paginado consciente del esquema, reutilizando `RecordCodec` y el marco de página de la Etapa 2 |
| Propiedad | Cada archivo temporal pertenece a **un** `ExecutionContext` con directorio propio |
| Limpieza | Determinista al cerrar, también ante parada temprana, error de validación y excepción de E/S |
| Reapertura | Basta reabrir un lector temporal **dentro del mismo proceso**; no se promete reanudación tras caída |
| Aislamiento | La limpieza solo toca rutas registradas por esa ejecución; nunca borra tablas ni índices base |
| Fila grande | Se admite hasta `MAX_RECORD_SIZE`; por encima, error determinista |
| Ubicación | `engine/operators/`, no `engine/storage/`, por la regla de arquitectura descrita en la [inspección](ETAPA_06_TASK_6_1_INSPECTION.md#conflictos-y-prerrequisitos-declarados) |

## 10. Adaptadores de streaming necesarios

Las APIs de las Etapas 4 y 5 **ya hacen streaming** y no necesitan adaptadores
de compatibilidad. La Etapa 6 las consume directamente:

- `search_records(key)` en los tres adaptadores;
- `range_records(lower, upper, ...)` en los dos adaptadores B+;
- `ExtendibleHashIndex` **no** ofrece rango: `IndexScan` rechaza una
  especificación de rango sobre hash con `ValidationError`, y no se disfraza de
  rango un recorrido completo de tabla.

## 11. Frontera con la Etapa 7

La Etapa 6 entrega un ayudante mínimo de ejecución que abre un plan ya
construido, lo consume hasta agotarlo o hasta un límite del consumidor y
garantiza `close()` en `finally`. **No** incluye gramática, AST, resolución de
nombres desde texto SQL, selección de índice, estimación de costes ni
orquestación de sentencias: todo eso pertenece a la Etapa 7. El ayudante nunca
devuelve una lista ilimitada por defecto.

## 12. Observabilidad

Cada operador expone un descriptor veraz (nombre, hijos, ruta de acceso real,
propiedades de orden solo cuando se preservan de verdad) y estadísticas
medidas: filas examinadas y emitidas, páginas leídas/escritas reales, memoria
máxima contabilizada, runs generados, pasadas de mezcla, fan-in máximo,
particiones creadas y niveles de reparticionamiento. Los costes esperados y la
E/S observada se reportan por separado.

## 13. Matriz semántica revisada

| Caso | Comportamiento decidido |
|---|---|
| Filas duplicadas en la entrada | Se preservan; ningún operador deduplica implícitamente |
| Predicado con NULL | Imposible por construcción: NULL no existe en el modelo |
| Join con claves iguales repetidas | Multiplicidad `m*n` preservada |
| Agregación sobre entrada vacía | `GROUP BY` no emite filas |
| `NaN` como clave de grupo, orden o join | `ValidationError` explícito |
| Rango sobre índice hash | `ValidationError`; no hay retroceso silencioso a scan |
| Columna ambigua tras un join | `ValidationError` en `open()`, antes de leer filas |
| Proyección que elimina una clave de orden posterior | Plan rechazado, salvo que la clave se transporte deliberadamente como campo interno |
| Operación no soportada | Rechazo explícito, nunca degradación silenciosa |

## Aceptación

No queda ninguna elección tácita sobre semántica de tipo SQL ni sobre
comportamiento de memoria. La ruta por defecto conserva íntegras las
obligaciones oficiales de `ORDER BY`, `GROUP BY` y `JOIN`.
