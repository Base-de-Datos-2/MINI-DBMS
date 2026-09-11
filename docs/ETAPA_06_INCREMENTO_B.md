# Etapa 6 — incremento B: temporales y ordenamiento externo

Fecha: **2026-09-10**. Alcance: tareas **6.11 a 6.16** de
[ETAPA_06.md](../ETAPA_06.md), es decir la condición de salida del incremento B
de su sección 9: *ExternalSort multipasada respaldado por disco, que funciona y
limpia sus temporales*.

Continúa el [incremento A](ETAPA_06_INCREMENTO_A.md). No cierra la Etapa 6:
quedan pendientes los incrementos C (agrupación), D (joins), E (índices
opcionales) y F (integración y entrega).

## Estado por tarea

| Tarea | Entregable | Estado |
|---|---|---|
| 6.11 | `engine/operators/temp_files.py` — `TemporaryWorkspace` | Completa |
| 6.12 | `engine/operators/temp_stream.py` — lector/escritor paginado | Completa |
| 6.13 | `engine/operators/sorting.py` — `SortSpec`, `BoundSortSpec` | Completa |
| 6.14 | `sorting.py` — generación de runs acotados por memoria | Completa |
| 6.15 | `sorting.py` — mezcla k-way acotada | Completa |
| 6.16 | `sorting.py` — `ExternalSort` multipasada | Completa |

## Requisito oficial cubierto

`REQUIREMENTS.md` §5.1 exige que `ORDER BY` use **ordenamiento externo con
mezcla k-way**. Queda satisfecho, y **demostrado con volcados reales forzados**,
no inferido del nombre de la clase. Falta conectarlo a la sintaxis SQL, que es
Etapa 7.

## Decisiones de diseño relevantes

### Propiedad de los temporales (6.11)

- Cada ejecución recibe un directorio propio vía `tempfile.mkdtemp()` con
  prefijo `minidb-exec-`.
- La limpieza usa **`rmdir`, nunca un borrado recursivo**. Un archivo
  inesperado dentro del directorio se **reporta como no reclamado** en vez de
  destruirse: el workspace solo borra rutas que él mismo registró.
- `discard()` sobre una ruta ajena lanza `ValidationError`. Una tabla base o un
  índice no pueden ser alcanzados por la limpieza ni por accidente.
- Un run se mantiene vivo por **conteo de lectores**: `discard()` marca, y el
  archivo desaparece cuando el último lector lo libera. Un consumidor nunca
  puede quedarse leyendo una ruta que se borró bajo sus pies.
- No hay barrido de arranque de un directorio compartido. La retención para
  depuración es explícita y está desactivada por defecto.

### Formato de los temporales (6.12)

Un run es un archivo paginado por `PageManager`:

```text
página 0   descriptor JSON: magic, versión, esquema, row_count, byte_length
página 1+  un slot por página con un trozo del flujo de bytes
```

Dentro del flujo, cada fila va enmarcada como `uint32 longitud || payload`.
Como el marco vive en un **flujo continuo cortado en páginas**, una fila más
ancha que una página **atraviesa páginas** en lugar de ser truncada o
rechazada. Eso importa para el incremento D: una fila unida de dos registros
base supera el límite de una página.

- Máximo documentado por fila: `MAX_TEMPORARY_ROW_BYTES` = 65536 bytes. Acota
  lo que un prefijo de longitud corrupto podría pedir reservar.
- El buffer del escritor y el del lector son de **una página**, sea cual sea el
  número de filas.
- Se distingue fin limpio de flujo truncado: quedarse sin bytes a mitad de un
  prefijo o de un payload es `ValidationError`; terminar con menos filas de las
  declaradas también.
- Magic y versión se verifican al abrir; una versión distinta se rechaza, no se
  adivina.
- Toda la E/S pasa por `PageManager`, de modo que el trabajo temporal aparece
  en los mismos contadores de páginas que el almacenamiento base.

### Estabilidad del orden (6.13)

Las filas con clave igual **conservan su orden de entrada**, y se consigue sin
almacenar una columna de secuencia:

1. Dentro de un chunk, `list.sort` de Python es estable y solo compara las
   tuplas de clave.
2. Entre runs, la mezcla desempata por **índice de run**, y un run anterior
   siempre contiene entrada anterior.

Como el índice de run es único entre las cabezas vivas del heap, **dos objetos
`Record` nunca se comparan entre sí**, que es lo que la tarea 6.13 exige.

Otras decisiones: direcciones mixtas ASC/DESC se soportan envolviendo el valor
en `_Descending` (no se puede negar una cadena ni invertir un orden compuesto);
`NaN` se rechaza al construir la clave; una `SortSpec` vacía es legal y
significa *preservar el orden de entrada*.

### Presupuesto y fan-in (6.14–6.16)

- El fan-in **se deriva de los recursos**, no del número de runs:
  `min(handles-1, (presupuesto - buffer_salida) // buffer_por_lector, max_fan_in)`.
- `MINIMUM_SORT_BUDGET_BYTES` = `(2 + 1) × 4079` = **12237 bytes**. Un
  presupuesto menor podría generar runs que jamás podría combinar, así que el
  plan se **rechaza al construirse**, no a mitad de un volcado.
- La fila pendiente se conserva a través del volcado: no se pierde ninguna fila
  entre chunks.
- Una fila que no cabe en el presupuesto produce un error determinista.
- Los archivos de una pasada se reclaman **solo** cuando su reemplazo está
  completo y todos sus lectores están cerrados.
- **La mezcla final se transmite, no se materializa**, de modo que la última
  pasada no cuesta una escritura extra. Queda declarado en `final_merge_streamed`.

## Evidencia medida de comportamiento externo

Escenario de `test_more_runs_than_fan_in_force_several_merge_passes`: 2000
filas, presupuesto mínimo, `max_fan_in=2`.

| Medida | Valor observado |
|---|---|
| Runs iniciales | 36 |
| Fan-in derivado | 2 (por memoria, aunque se pidieran 3) |
| Pasadas de mezcla | 6 |
| Filas volcadas a disco | 2000 |
| Bytes volcados | 40 890 |
| Páginas temporales escritas / leídas | 173 / 173 |
| Salida | orden exacto, multiset exacto, estable |

Se contrasta contra un oráculo en memoria (`sorted`) de solo pruebas, y se
comprueba que `initial_runs > fan_in` y `merge_passes >= 2`.

## Definition of Done — sección "External sorting"

| Criterio | Estado |
|---|---|
| Los chunks iniciales y el espacio de trabajo caben en su memoria concedida | Cumple |
| Los runs ordenados se escriben en almacenamiento temporal real | Cumple |
| Una única política de comparación y desempate en runs y pasadas | Cumple |
| Mezcla k-way con buffers y descriptores de archivo acotados | Cumple |
| Más runs que fan-in se resuelven con varias pasadas | Cumple |
| Una prueba fuerza al menos dos pasadas de mezcla | Cumple |
| La salida está ordenada y tiene el multiset exacto de la entrada | Cumple |
| El cierre temprano y los fallos limpian los runs intermedios | Cumple |

## Validación

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
.venv/bin/python -m compileall -q engine tests
git diff --check
```

| Medida | Resultado |
|---|---|
| Línea base del incremento A | 1848 pruebas aprobadas |
| Suite completa tras el incremento B | **1914 aprobadas en 45,21 s**, advertencias como errores |
| Pruebas nuevas | **66** (`test_temp_files` 13, `test_temp_stream` 23, `test_sorting` 27, integración 3) |
| Regresión de Etapas 1–5 | Sin cambios |
| `compileall` y `git diff --check` | Correctos |

### Defectos encontrados y corregidos durante la implementación

1. **Presupuesto mínimo insuficiente para mezclar.** El mínimo genérico del
   contexto (4224 bytes) permitía generar runs pero daba fan-in 0, de modo que
   un sort con ese presupuesto fallaba al abrir. Se introdujo
   `MINIMUM_SORT_BUDGET_BYTES`, validado al construir el plan.
2. **Entrada vacía sin flujo cerrable.** El camino de cero runs devolvía
   `iter(())`, que no tiene `close()`, y la limpieza fallaba con
   `AttributeError`. Ahora todos los caminos devuelven un generador.
3. **`ordering` devolvía la referencia sin calificar** que el llamante hubiera
   escrito, en vez de la referencia resuelta contra el layout, a diferencia del
   resto de operadores.

## Ejemplos de aceptación instanciados

- **Ejemplo D — forzar ordenamiento externo:** implementado en
  `tests/integration/test_stage6_pipelines.py::test_example_d_forces_real_external_sorting_over_persisted_storage`,
  con 3000 filas sobre un `HeapFile` multipágina. Comprueba escrituras de run
  mayores que cero, al menos dos pasadas, fan-in máximo dentro del límite,
  salida ordenada con el multiset exacto y ningún temporal superviviente.
- **Ejemplos B y C** siguen pendientes de los incrementos C y D.

## Límite de este informe

Se determinaron las tareas **6.11–6.16**. No se certifica la Definition of Done
de la Etapa 6, que exige además agrupación externa, joins optimizados,
tratamiento de sesgo y la documentación de cierre.
