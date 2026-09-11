# Etapa 6 — incremento D: joins

Fecha: **2026-09-11**. Alcance: tareas **6.22 a 6.25** de
[ETAPA_06.md](../ETAPA_06.md), es decir la condición de salida del incremento D
de su sección 9: *la línea base y `GraceHashJoin` coinciden, incluidos los
casos de duplicados y sesgo*.

Continúa los incrementos [A](ETAPA_06_INCREMENTO_A.md),
[B](ETAPA_06_INCREMENTO_B.md) y [C](ETAPA_06_INCREMENTO_C.md). No cierra la
Etapa 6: quedan los incrementos E (índices opcionales, **declarado opcional**
por la propia guía) y F (integración y entrega).

## Estado por tarea

| Tarea | Entregable | Estado |
|---|---|---|
| 6.22 | `engine/operators/join.py` — `NestedLoopJoin` y `RowSpool` | Completa |
| 6.23 | `join.py` — `HashJoinKernel` acotado | Completa |
| 6.24 | `join.py` — `GraceHashJoin` | Completa |
| 6.25 | `join.py` — sesgo, progreso y fallback de bucle anidado por bloques | Completa |

## Requisito oficial cubierto

`REQUIREMENTS.md` §5.3 exige que `JOIN` se optimice con **hashing externo y/o
uso estratégico de índices**. Queda satisfecho por `GraceHashJoin`, la ruta
aprobada en la [tarea 6.2](ETAPA_06_TASK_6_2_DECISIONS.md), y **demostrado con
particiones en disco reales**. `NestedLoopJoin` es la línea base de corrección
y **no se presenta por sí sola como el join optimizado**, ni en su descriptor
ni en la documentación.

Con esto, los **tres** algoritmos externos obligatorios de la Parte 1 están
implementados:

| Requisito | Ruta | Incremento |
|---|---|---|
| §5.1 `ORDER BY` | `ExternalSort` con mezcla k-way multipasada | B |
| §5.2 `GROUP BY` | `ExternalHashGroup` con particionamiento en disco | C |
| §5.3 `JOIN` | `GraceHashJoin` con particionamiento de ambas entradas | D |

## Decisiones de diseño relevantes

### La entrada interna siempre se vuelca (6.22)

La guía permite dos opciones: reabrir un scan repetible documentado, o volcar
una entrada interna no repetible a un flujo temporal. Se adoptó **volcar
siempre**, mediante `RowSpool`:

- Es correcto para **cualquier** productor, sin depender de suposiciones sobre
  si el hijo se puede rebobinar. Hay una prueba con un productor que lanza
  excepción si se abre por segunda vez.
- Cuesta una escritura, y a cambio elimina una clase entera de errores.
- El mismo mecanismo sirve al fallback por bloques de la tarea 6.25.

`NestedLoopJoin` admite un bloque acotado de filas externas y recorre el
interno una vez por bloque. Con `block_rows=1` es el bucle anidado por tuplas
del libro de texto; con el bloque acotado por memoria es el bucle anidado por
bloques. **El tamaño de bloque cambia el número de pasadas pero nunca el
resultado**, y hay una prueba parametrizada que lo comprueba.

### El kernel guarda todas las ocurrencias (6.23)

`HashJoinKernel` almacena **cada** fila de build de una clave, no solo la
última, que es el error clásico que rompe la multiplicidad. Una fila de probe
que casa con *m* filas de build emite *m* pares, cedidos **de uno en uno**
desde el bucket almacenado: no se construye ninguna lista por sondeo, de modo
que una clave con muchas coincidencias no cuesta memoria adicional.

El desborde se reporta **antes** de que exista salida alguna basada en una
tabla de build incompleta: la fase de build termina entera antes de sondear.

### GraceHashJoin (6.24)

1. Particionar ambas entradas con la misma función de hash sobre sus claves
   respectivas, de modo que las claves iguales caen en el mismo índice de
   partición en ambos lados.
2. Por cada par de particiones, elegir como lado de build el **más pequeño en
   bytes**, dato que el particionador ya registró: **no se escanea ninguna
   entrada a memoria solo para estimar su tamaño**. El estado realmente
   admitido es lo que decide si cabe de verdad.
3. Construir y sondear con el kernel de 6.23.
4. Liberar el par cuando su flujo de resultados se agota.
5. Reparticionar **ambos lados** de un par sobredimensionado antes de emitir
   nada de ese par, preservando el emparejamiento.

Un índice de partición presente en un solo lado no puede producir ninguna fila
en un join interno, así que se libera sin leerlo (`pairs_skipped_empty`).

**El intercambio físico del lado de build no altera el orden lógico de las
columnas de salida.** Hay una prueba explícita para eso.

### Sesgo (6.25)

Las ocurrencias repetidas de **una misma clave** no pueden separarse cambiando
el hash sin romper la co-locación, que es justo lo que el join necesita. Ante
un par que deja de encogerse, o que alcanza `max_level`, se activa un **bucle
anidado por bloques acotado** sobre los mismos archivos de partición: se
mantiene un bloque admitido de un lado y el otro se transmite/re-lee, emitiendo
el producto cartesiano de coincidencias **de forma incremental**. No hay
`list(build_matches)`, ni lista de producto cruzado, ni caché que crezca con la
salida total.

Un matiz que las pruebas dejaron claro y conviene registrar: **con selección de
lado de build, un par sesgado solo necesita el fallback si *ambos* lados son
grandes**. Si un lado es pequeño, cabe como build y el par se resuelve por hash
aunque todas las filas compartan una clave. Hay una prueba para cada caso.

La salida del join es **desordenada** y puede ser mucho mayor que ambas
entradas, así que se transmite y nunca se materializa.

## Evidencia medida

`test_grace_join_partitions_inputs_far_beyond_its_memory_grant`: 3000 filas por
lado, 300 claves distintas, presupuesto 65 536 B, fan-out 8.

| Medida | Valor observado |
|---|---|
| Tamaño de las entradas | ~858 000 B, **13,1× el presupuesto** |
| Pares de particiones | 16 |
| Resueltos por hash | 15 |
| Desbordes de build | 1 |
| Reparticiones | 1 |
| Fallbacks de bucle anidado | **0** |
| Páginas temporales escritas / leídas | 84 / 87 |
| Filas emitidas | 29 975 |
| Equivalencia con `NestedLoopJoin` | multiset idéntico |

Es decir: ninguna de las dos entradas cabe en la memoria concedida, y aun así
la ruta de hashing externo completa el join por sí sola con E/S de particiones
real.

## Definition of Done — sección "Joins"

| Criterio | Estado |
|---|---|
| `NestedLoopJoin` proporciona una línea base correcta e independiente | Cumple |
| Las entradas internas no repetibles se manejan con volcado acotado o contrato de rescan explícito | Cumple (volcado siempre) |
| El kernel de hash-join guarda todas las ocurrencias de build coincidentes | Cumple |
| `GraceHashJoin` particiona demostrablemente más allá de su asignación de memoria | Cumple |

## Validación

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
.venv/bin/python -m compileall -q engine tests
git diff --check
```

| Medida | Resultado |
|---|---|
| Línea base del incremento C | 1986 pruebas aprobadas |
| Suite completa tras el incremento D | **2036 aprobadas en 75,63 s**, advertencias como errores |
| Pruebas nuevas | **50** (`test_join` 48, integración 2) |
| Regresión de Etapas 1–5 | Sin cambios |
| `compileall` y `git diff --check` | Correctos |

### Defectos encontrados y corregidos durante la implementación

1. **Contador acumulado usado como señal por par.** `_pairs` decidía si
   reparticionar consultando `build_overflows == 0`, que es un total de toda la
   ejecución. Un par que legítimamente no casa con nada habría sido
   reparticionado sin motivo. Ahora el kernel reporta el desborde de **ese**
   par mediante una bandera explícita, porque la ausencia de salida no puede
   sustituir a la señal de desborde.
2. **Bucle de admisión del baseline con lógica muerta.** La primera versión
   ajustaba `outer_rows` hacia atrás y hacia delante para reinsertar la fila
   disparadora. Se reescribió con un patrón claro en el que la fila
   disparadora permanece en la variable del bucle a través del vaciado.

### Pruebas propias corregidas

- Una fuente vacía necesita esquema explícito, igual que en el incremento C.
- `pairs_skipped_empty` se comprobaba con claves elegidas al azar, que llenaban
  todas las particiones de ambos lados. Ahora el test calcula con
  `partition_hash` qué claves caen en particiones distintas.
- La prueba de sesgo asumía que 300 filas de una clave contra 20 forzaban el
  fallback. No es así, y es correcto que no lo sea: el lado pequeño cabe como
  build. Se dividió en dos pruebas, una por cada comportamiento.

## Ejemplos de aceptación instanciados

- **Ejemplo C — preservar la multiplicidad del join:** implementado para las
  dos rutas en `tests/operators/test_join.py::test_example_c_preserves_join_multiplicity`
  y contra almacenamiento paginado real en
  `tests/integration/test_stage6_pipelines.py::test_example_c_preserves_join_multiplicity_over_persisted_storage`.
  Claves izquierda `[7, 7, 9]` y derecha `[7, 7, 7, 10]` producen exactamente
  **6** filas, incluso cuando los valores proyectados se ven idénticos.
- Con esto los ejemplos **A, B, C, D y E** de la sección 11 están todos
  instanciados.
- `test_the_full_stage_six_pipeline_runs_over_paged_storage` ensambla a mano
  `TableScan → Filter → GraceHashJoin → ExternalHashGroup → ExternalSort` sobre
  dos archivos paginados, sin SQL.

## Límite de este informe

Se determinaron las tareas **6.22–6.25**. No se certifica la Definition of Done
de la Etapa 6, que exige además la consolidación de planes manuales, las
métricas y descriptores completos, las pruebas de límites de persistencia y la
documentación de cierre (tareas 6.27–6.31). La tarea 6.26 es opcional porque
ambas rutas de hashing externo están completas.
