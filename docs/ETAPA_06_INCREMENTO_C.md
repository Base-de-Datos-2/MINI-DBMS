# Etapa 6 — incremento C: agrupación externa

Fecha: **2026-09-11**. Alcance: tareas **6.17 a 6.21** de
[ETAPA_06.md](../ETAPA_06.md), es decir la condición de salida del incremento C
de su sección 9: *la agrupación externa supera la memoria con seguridad y
maneja el sesgo*.

Continúa los incrementos [A](ETAPA_06_INCREMENTO_A.md) y
[B](ETAPA_06_INCREMENTO_B.md). No cierra la Etapa 6: quedan los incrementos
D (joins), E (índices opcionales) y F (integración y entrega).

## Estado por tarea

| Tarea | Entregable | Estado |
|---|---|---|
| 6.17 | `engine/operators/aggregation.py` — `Count`, `CountColumn`, `Sum`, `Min`, `Max`, `Avg` | Completa |
| 6.18 | `aggregation.py` — `HashGroupKernel` acotado | Completa |
| 6.19 | `engine/operators/partitioning.py` — `HashPartitioner` reutilizable | Completa |
| 6.20 | `aggregation.py` — `ExternalHashGroup` | Completa |
| 6.21 | `aggregation.py` — sesgo, progreso y fallback ordenado | Completa |

## Requisito oficial cubierto

`REQUIREMENTS.md` §5.2 exige que `GROUP BY` se optimice con **hashing externo
y/o uso estratégico de índices**. Queda satisfecho por la ruta de hashing
externo aprobada en la [tarea 6.2](ETAPA_06_TASK_6_2_DECISIONS.md), y
**demostrado con E/S de particiones real**, no declarado. Falta conectarlo a la
sintaxis SQL, que es Etapa 7.

## Defecto principal encontrado: los bits bajos de FNV-1a

Este es el hallazgo más importante del incremento y merece registro explícito.

La primera versión del particionamiento mezclaba el nivel de recursión como un
**prefijo de bytes** (`b"L0|"`, `b"L1|"`, …) antes de la clave, y tomaba
`digest % partition_count`. Con `partition_count = 2` la recursión no separaba
absolutamente nada: cada repartición mandaba **todas** las filas del padre a un
único hijo.

La causa es una propiedad de FNV-1a. Su paso es
`value = (value XOR byte) * PRIME`, y `PRIME` es impar. Módulo 2, multiplicar
por un impar no cambia la paridad, así que:

```text
bit_bajo(digest) = bit_bajo(base) XOR bit_bajo(byte_1) XOR ... XOR bit_bajo(byte_n)
```

El bit bajo de un digest FNV es **la paridad XOR de sus bytes de entrada**.
Cambiar `'0'` (0x30) por `'1'` (0x31) en el prefijo altera exactamente un bit
de esa paridad, y por lo tanto **invierte el bit bajo de todas las claves a la
vez**. El reparto del nivel 1 quedaba perfectamente anticorrelacionado con el
del nivel 0.

Evidencia reproducida antes de corregir:

```text
nivel 0: 400 claves -> {0: 200, 1: 200}
_partition(level=0) -> [(0, 2011), (1, 1989)]
_partition(level=1) -> [(0, 1989)]      <- los 1989 en un solo hijo
_partition(level=1) -> [(1, 2011)]      <- los 2011 en un solo hijo
```

**Corrección:** se añadió `avalanche64`, un finalizador de 64 bits de tipo
splitmix, y la semilla de nivel se mezcla por XOR en vez de por prefijo:

```python
seed = avalanche64((level + 1) * _LEVEL_STRIDE)
return avalanche64(HashCodec.hash_bytes(payload) ^ seed)
```

Resultado tras la corrección, mismo escenario:

```text
particion 0 del nivel 0 -> nivel 1: {1: 100, 0: 96}
particion 1 del nivel 0 -> nivel 1: {1: 105, 0: 99}
```

El finalizador es **local a la ejecución de consultas** y no toca el formato
persistente de la Etapa 5, cuya elección de bits de directorio es su propia
decisión documentada. Esto es exactamente lo que la tarea 6.19 anticipa al
pedir *«reutilizar las primitivas de hash estables de la Etapa 5 solo donde
sean compatibles; mantener las elecciones de semilla/bits locales a la
consulta»*.

Nótese que el chequeo de no-progreso ya existía y **capturó el fallo**: el
resultado era correcto incluso con el hash degenerado, porque caía al fallback
ordenado. El defecto no producía datos erróneos, producía una ruta de hashing
inútil. Sin la métrica `fallback_partitions` habría pasado desapercibido.

## Decisiones de diseño relevantes

### Agregados (6.17)

| Agregado | Tipo de salida | Estado por grupo |
|---|---|---|
| `COUNT(*)` | INTEGER | un entero |
| `COUNT(columna)` | INTEGER | un entero |
| `SUM` | el del columna (INTEGER o FLOAT) | un total |
| `MIN` / `MAX` | el de la columna, cualquier tipo | el valor extremo |
| `AVG` | siempre FLOAT | `(total, conteo)` |

- **`AVG` nunca promedia promedios.** Su estado es el par total/conteo y su
  `merge` suma ambos componentes, de modo que un grupo grande y uno pequeño no
  se ponderan igual. Hay una prueba que contrasta la fusión correcta contra la
  ingenua.
- **`SUM` sobre INTEGER rechaza salir del rango de 64 bits con signo** en vez
  de desbordar en silencio.
- **`COUNT(*)` y `COUNT(columna)` coinciden** porque el modelo de filas no
  admite NULL. Se mantienen como operaciones separadas, con la columna resuelta
  y validada, para que la distinción tenga sentido el día que exista NULL en
  lugar de perderse.
- **`MIN`, `MAX` y `AVG` sobre entrada global vacía lanzan `ValidationError`.**
  Su valor no es representable sin NULL, y un error de recurso o de dominio no
  puede presentarse como un resultado completo. `COUNT` devuelve `0` y `SUM`
  un cero tipado.
- `merge` está implementado y probado aunque la ruta partition-first adoptada
  nunca lo necesita: las claves iguales jamás se finalizan en particiones
  distintas.

### Kernel acotado (6.18)

- La memoria crece con los **grupos distintos vivos**, no con las filas: un
  grupo con 20 000 filas cuesta lo mismo que uno con una.
- `admit()` devuelve `False` al agotarse la capacidad **sin haber aplicado la
  fila**: se calcula el estado nuevo, se cobra el delta, y solo entonces se
  confirma. Una reserva denegada no puede dejar media fila aplicada.
- Las colisiones se resuelven por igualdad completa de clave, no por hash.
- `results()` itera el mapa perezosamente, sin copiarlo a otra lista.

### ExternalHashGroup (6.20) y sesgo (6.21)

La ruta es **partition-first**, la que la guía recomienda por ser más fácil de
validar:

1. Particionar las filas crudas por la clave de agrupación completa.
2. Cerrar todos los escritores antes de leer ninguna partición.
3. Procesar una partición a la vez con el kernel acotado.
4. Si cabe, emitir sus grupos finalizados y liberar la partición.
5. Si no cabe, **descartar el estado tentativo por completo** y reparticionar la
   partición original entera a un nivel más profundo.

Descartar en vez de conservar estado parcial es lo que hace imposible el doble
conteo, y la fila que disparó el desborde no se pierde porque sigue en el
archivo de la partición.

Ante sesgo:

- **Una clave dominante no es un problema**: un estado de tamaño fijo procesa
  un grupo arbitrariamente grande. Probado con 20 000 filas en un grupo, sin
  desbordes ni reparticiones.
- **Muchas claves distintas que el hash no separa** sí lo son. Se detecta que
  un hijo conserva el recuento completo del padre (sin progreso), o que se
  alcanzó `max_level`, y se activa el **fallback acotado**: ordenar la
  partición por la clave de grupo con `ExternalSort` y plegar claves iguales
  adyacentes con un único estado. Siempre termina.
- El fallback se cuenta aparte (`fallback_partitions`, `fallback_rows`) y
  aparece en el descriptor del plan. **No se presenta como ejecución hash.**
- La salida agrupada es **desordenada** y no anuncia ninguna ordenación.

## Evidencia medida

Escenario de `test_more_distinct_groups_than_memory_still_produce_one_row_each`:
4000 filas, 400 grupos distintos, presupuesto mínimo, fan-out 2, cinco
agregados.

| Medida | Valor observado |
|---|---|
| Particiones escritas | 28 |
| Particiones resueltas por hash | 15 |
| Reparticiones | 13 |
| Nivel más profundo | 3 |
| Desbordes del kernel | 13 |
| Fallbacks ordenados | **0** |
| Páginas temporales escritas / leídas | 118 / 144 |
| Grupos emitidos | 400, todos correctos contra el oráculo |

Es decir: la ruta de hashing externo resuelve el caso completa por sí sola, con
E/S de particiones real y sin recurrir al fallback.

## Definition of Done — sección "Grouping"

| Criterio | Estado |
|---|---|
| El conjunto de agregados adoptado tiene semántica de acumulación y finalización probada | Cumple |
| Comportamiento vacío / global / agrupado explícito | Cumple |
| `ExternalHashGroup` particiona y procesa más grupos distintos de los que caben en memoria | Cumple |
| El desborde parcial de una partición no puede duplicar ni perder la fila disparadora | Cumple |
| Las colisiones de hash usan igualdad completa de clave | Cumple |
| Una clave caliente no crea una lista ilimitada de filas miembro | Cumple |
| La repartición termina mediante chequeos de progreso y un fallback probado | Cumple |
| La salida agrupada no promete ninguna ordenación no soportada | Cumple |
| La optimización de agrupación aprobada tiene evidencia observable | Cumple |

## Validación

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
.venv/bin/python -m compileall -q engine tests
git diff --check
```

| Medida | Resultado |
|---|---|
| Línea base del incremento B | 1914 pruebas aprobadas |
| Suite completa tras el incremento C | **1986 aprobadas en 72,38 s**, advertencias como errores |
| Pruebas nuevas | **72** (`test_partitioning` 19, `test_aggregates` 25, `test_grouping` 25, integración 3) |
| Regresión de Etapas 1–5 | Sin cambios |
| `compileall` y `git diff --check` | Correctos |

### Otros ajustes durante la implementación

- `RowSource` de pruebas acepta un esquema explícito: una fuente vacía no puede
  inferirlo de sus filas y antes heredaba en silencio el de `students`.
- `bytes_partitioned` no se estaba acumulando en las métricas.
- Una aserción de prueba afirmaba `avalanche64(0) != 0`, que es falsa: el cero
  es punto fijo de ese mezclador. Es inofensivo porque la entrada siempre se
  mezcla con una semilla no nula, y la aserción se sustituyó por las
  propiedades que sí importan.

## Ejemplos de aceptación instanciados

- **Ejemplo B — agrupar y luego ordenar:** implementado en
  `tests/integration/test_stage6_pipelines.py::test_example_b_group_then_sort_over_persisted_storage`,
  con la variante a escala
  `test_example_b_at_scale_forces_real_partition_io`, que supera la asignación
  de memoria de estados distintos con 500 grupos y 5000 filas.
- **Ejemplo C** requiere joins: pendiente del incremento D.

## Límite de este informe

Se determinaron las tareas **6.17–6.21**. No se certifica la Definition of Done
de la Etapa 6, que exige además los joins optimizados, sus casos de sesgo y la
documentación de cierre.
