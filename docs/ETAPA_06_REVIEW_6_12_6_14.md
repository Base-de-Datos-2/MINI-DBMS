# Revisión de 6.12–6.14

Fecha: 2026-09-13. Alcance: flujos temporales de filas, política de orden y
generación de runs. Continúa el [bloque anterior](ETAPA_06_REVIEW_6_1_6_4_6_6_6_10.md).
El [incremento B](ETAPA_06_INCREMENTO_B.md) registra el diseño de 2026-09-10;
sus cifras originales de presupuesto y E/S fueron sustituidas por la
[corrección de recursos](ETAPA_06_REVIEW_6_5_6_11_6_15_6_16.md).

| Tarea | Evidencia contrastada | Resultado |
|---|---|---|
| 6.12 | `TemporaryRowWriter`/`Reader`, `PageManager`, formato con versión/esquema y prefijo de longitud; pruebas de UTF-8, duplicados, filas entre páginas, reapertura, truncamiento e incompatibilidad | Formato y lectura acotada coherentes. Se añadió verificación de longitud total al EOF. |
| 6.13 | `SortSpec`/`BoundSortSpec`, claves ASC/DESC y mixtas, comparación tipada y estabilidad de empates en runs/merge | La misma clave ligada se usa en las dos fases; las pruebas contrastan entrada en memoria y con volcado. `NULL` está fuera del modelo y `NaN` se rechaza. |
| 6.14 | `ExternalSort._generate_runs`, reserva de chunk y fila pendiente, `RunCatalog` en disco; pruebas de entradas vacías, anchos variables, límite, duplicados y varios runs | Los chunks admitidos se vuelcan a archivos reales sin perder la fila que cruza el límite. La admisión usa el presupuesto corregido de la revisión anterior. |

## Hallazgo y corrección

El lector comparaba al abrir el esquema, el número de filas y los bytes del
descriptor persistido con `TemporaryRun`, pero al terminar solo comprobaba el
número de filas. Si ambos descriptores declaraban una longitud errónea, aceptaba
el flujo. La regresión modifica ambos descriptores para declarar un byte
adicional: **falló antes del cambio** y ahora produce `CorruptTemporaryError`
al llegar al EOF. Esto distingue una lectura completa de una longitud
declarada inconsistente sin cargar el flujo en memoria.

La memoria del lector sigue acotada por una página y una fila parcial de hasta
65 536 bytes; no significa que su uso total sea literalmente una sola página.
La memoria de los operadores se reporta como trabajo contabilizado, no RSS.

## Verificación

Con advertencias como errores y plugins externos deshabilitados,
`tests/operators/test_temp_stream.py` y `tests/operators/test_sorting.py` pasan
**51 pruebas en 32,37 s**. La regresión nueva se ejecutó primero contra el
comportamiento anterior y falló por no lanzar el error esperado.

Este bloque tampoco ratifica la etapa completa. Sigue la revisión de
6.17–6.18 y 6.20–6.21, luego 6.22–6.26 y la comprobación transversal de 6.31
y los 59 criterios.
