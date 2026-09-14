# Etapa 6 — incremento E: estrategias asistidas por índice (opcional)

Fecha: **2026-09-11**. Alcance: tarea **6.26** de [ETAPA_06.md](../ETAPA_06.md).

## Naturaleza de este incremento

La tarea 6.26 es **opcional**, y lo sigue siendo. Su propio enunciado dice:

> *This is optional when both default external-hashing routes are completed.*

Ambas rutas de hashing externo están completas y son las que satisfacen los
requisitos oficiales:

| Requisito | Ruta que lo satisface | Incremento |
|---|---|---|
| `REQUIREMENTS.md` §5.2 `GROUP BY` | `ExternalHashGroup` | [C](ETAPA_06_INCREMENTO_C.md) |
| `REQUIREMENTS.md` §5.3 `JOIN` | `GraceHashJoin` | [D](ETAPA_06_INCREMENTO_D.md) |

Lo implementado aquí **añade** rutas alternativas; no sustituye ni reinterpreta
ninguna obligación. La [tarea 6.2](ETAPA_06_TASK_6_2_DECISIONS.md) ya había
registrado las estrategias de índice como opcionales, y esa decisión no cambia.

El motivo de implementarlas es que el proyecto ya tiene índices B+ y hash
persistentes de las Etapas 4 y 5, y demostrar que los operadores saben
aprovecharlos es material útil para la demo y para el panel de plan de
ejecución de la Etapa 9.

## Estado por entregable

| Entregable | Módulo | Estado |
|---|---|---|
| `IndexNestedLoopJoin` | `engine/operators/index_strategies.py` | Completa |
| `IndexOrderedGroup` | `engine/operators/index_strategies.py` | Completa |

## Precondiciones explícitas y verificadas

El criterio de aceptación de la tarea es tajante:

> *A selected strategic-index route has explicit preconditions and measured
> evidence; an index's mere presence is not sufficient.*

Por eso ninguna de las dos rutas acepta un índice por el hecho de existir.

### `IndexNestedLoopJoin`

| Precondición | Cuándo se comprueba | Si falla |
|---|---|---|
| El objeto es un `Index` ligado a su almacenamiento | construcción | `InvalidTypeError` / `ValidationError` |
| La condición tiene exactamente **una** pareja de igualdad | construcción | `ValidationError` |
| El lado interno de esa pareja es **exactamente** la columna que cubre el índice | construcción | `ValidationError` |
| Ambos lados comparten tipo declarado | construcción | `ValidationError` |

Comportamiento:

- Transmite la entrada externa y sondea el índice **una vez por fila**.
  Funciona igual con B+ y con Extendible Hashing, a través de la interfaz
  compartida.
- **No mantiene ninguna caché de claves sondeadas.** Los registros internos
  coincidentes llegan en flujo, uno a uno.
- Preserva la multiplicidad `m*n` y admite predicado residual.
- La comprobación de asociaciones obsoletas la aporta el adaptador de índice,
  que relee la clave del registro y rechaza un RID que ya no corresponde.
- La procedencia de la fila de salida combina la del lado externo con
  `(relación interna, RID)` real.

### `IndexOrderedGroup`

| Precondición | Cuándo se comprueba | Si falla |
|---|---|---|
| El índice es **ordenado** (`OrderedIndex`) | construcción | `ValidationError` |
| La clave de agrupación es una sola columna | construcción | `ValidationError` |
| Esa columna es **exactamente** la que cubre el índice | construcción | `ValidationError` |
| El índice tiene **una entrada por fila viva** del almacenamiento | apertura del run | `ValidationError` |

La última es la más importante y la que cumple *«verify that the index covers
every input row required by the grouping semantics»*. Un índice parcial
produciría silenciosamente menos filas de las debidas, así que al abrir el run
se comparan `index.entry_count` y `storage.record_count`, y una discrepancia es
un error, no un resultado. Hay una prueba que inserta una fila directamente en
el `HeapFile`, saltándose el adaptador, y comprueba que la agrupación se niega
a ejecutarse.

Comportamiento:

- Recorre el índice en orden ascendente y mantiene el estado de **un solo
  grupo adyacente a la vez**.
- Las columnas no indexadas que los agregados necesitan se leen del
  almacenamiento a través del adaptador. No se inventa cobertura index-only:
  hay una prueba que agrupa por `id` y calcula `MIN(name)`/`MAX(name)`.
- **Nunca se supone que un índice hash produce grupos ordenados**: un
  `UnclusteredHashIndex` se rechaza en la construcción.
- A diferencia de `ExternalHashGroup`, esta ruta **sí** anuncia ordenación:
  `ordering` devuelve la columna de agrupación, porque un recorrido B+
  realmente es ascendente por ella. Un `ExternalSort` posterior es innecesario.

## Evidencia medida

Datos: 60 estudiantes con `id` en 0–19 (tres filas por id), 90 matrículas con
`student_id` en 0–24.

### Join

| Medida | Valor observado |
|---|---|
| Sondeos al índice | 90, uno por fila externa |
| Filas internas recuperadas | 225 |
| Sondeos sin coincidencia | 15 (los `student_id` 20–24, que no existen) |
| Pares emitidos | 225 |
| Concordancia con `NestedLoopJoin` | multiset idéntico |
| Concordancia con `GraceHashJoin` | multiset idéntico |

Las **tres** rutas de join del proyecto producen exactamente el mismo multiset.
Eso es lo que hace del baseline una comprobación independiente útil.

### Agrupación

| Medida | Valor observado |
|---|---|
| Filas leídas por el recorrido | 60 |
| Grupos emitidos | 20 |
| Cobertura verificada | 60 entradas = 60 filas |
| Concordancia con `ExternalHashGroup` | resultados idénticos |
| Orden de salida | ascendente por la clave, sin ordenar después |

También se prueba sobre un `ClusteredBPlusIndex` apoyado en
`PagedSequentialFile`, no solo sobre el adaptador unclustered.

## Validación

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
.venv/bin/python -m compileall -q engine tests
git diff --check
```

| Medida | Resultado |
|---|---|
| Línea base del incremento D | 2036 pruebas aprobadas |
| Suite completa tras el incremento E | **2062 aprobadas en 87,69 s**, advertencias como errores |
| Pruebas nuevas | **26** (`test_index_strategies`) |
| Regresión de Etapas 1–5 | Sin cambios |
| `compileall` y `git diff --check` | Correctos |

### Refactorizaciones acompañantes

- `build_grouped_layout` se extrajo de `ExternalHashGroup` a una función de
  `aggregation.py`, para que las dos rutas de agrupación publiquen el mismo
  esquema de salida sin duplicar la lógica.
- `_index_storage` de `scan.py` pasó a ser pública como `index_storage`, porque
  el repositorio no importa nombres privados entre módulos.

### Pruebas propias corregidas

Dos expectativas de prueba tenían aritmética equivocada: los 90 sondeos
producen **225** pares y **15** sondeos sin coincidencia, no los valores que
había estimado a ojo. Se sustituyeron por un cálculo explícito a partir del
propio fixture, de modo que la prueba explica de dónde sale cada número en vez
de afirmar una constante mágica.

## Límite de este informe

Se determinó la tarea **6.26**, que es opcional. No se certifica la Definition
of Done de la Etapa 6: quedan las tareas **6.27–6.31** del incremento F
(consolidación de planes manuales, descriptores y métricas completos, límites
de persistencia y limpieza, pruebas diferenciales y de estrés, y documentación
de cierre).
