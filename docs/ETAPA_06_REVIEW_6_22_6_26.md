# Revisión de 6.22–6.26

Fecha: 2026-09-13. Alcance: join de referencia, kernel de hash, GraceHashJoin,
sesgo y las dos rutas opcionales con índices. Continúa la
[revisión de agrupación](ETAPA_06_REVIEW_6_17_6_18_6_20_6_21.md).

| Tarea | Evidencia contrastada | Dictamen |
|---|---|---|
| 6.22 | `NestedLoopJoin`, `RowSpool`, scans no rebobinables, multiplicidad y parada temprana | Baseline independiente del hash y correcto en valores. Se corrigió la procedencia errónea de pares reconstruidos desde spool. |
| 6.23 | `HashJoinKernel`, reserva de cada ocurrencia build y sondeo perezoso | El desborde se señala antes de publicar resultados de una tabla incompleta; las colisiones no eliminan coincidencias. |
| 6.24 | `GraceHashJoin`, particionado de ambos lados, elección por bytes y validación de cabida real | Ejecuta el join grande con E/S de particiones y conserva el orden lógico de columnas al intercambiar el lado build. |
| 6.25 | Prueba de progreso, límite de repartición y bucle anidado por bloques | Los casos sesgados terminan y emiten el producto correcto en flujo; el fallback aparece en métricas y descriptor. |
| 6.26 | `IndexNestedLoopJoin` y `IndexOrderedGroup` sobre adaptadores persistentes | Las rutas son adicionales a las obligatorias, exigen precondiciones y muestran sondeos/recorridos reales. Se endureció la validación de la lista de agregados. |

## Correcciones

`NestedLoopJoin` volcaba el lado interno a un temporal que guarda valores, no
RIDs. Durante el recorrido del spool, leía `left.provenance` y
`right.provenance`, que ya podían corresponder a otra fila o al EOF. Una
regresión con dos Heap Files reales y bloque de una fila reprodujo la atribución
del RID de la *siguiente* fila izquierda al primer resultado. El baseline ahora
publica procedencia vacía para esos pares; `GraceHashJoin` ya hacía lo mismo.
`IndexNestedLoopJoin` sí puede combinar las procedencias porque conserva el
outer actual y recibe el RID exacto de cada coincidencia del índice. Se retiró
además una lista auxiliar de claves del bloque anidado: las claves se calculan
al comparar cada par, sin duplicar un estado proporcional al bloque.

`IndexOrderedGroup` convertía `aggregates` a tupla antes de comprobar que fuera
una secuencia. Ahora una cadena o un entero se rechazan con `InvalidTypeError`,
igual que en los demás operadores. La regresión focal cubre ambos tipos.

## Verificación y límites

Con advertencias como errores y plugins externos deshabilitados,
`test_join.py` y `test_index_strategies.py` pasan **75 pruebas en 96,93 s**;
la validación nueva de argumentos pasa además en ejecución focal posterior.
La regresión de procedencia falló antes del cambio y pasó después. Las pruebas
comparan las bags de `NestedLoopJoin`, `GraceHashJoin` e
`IndexNestedLoopJoin`, incluidas claves duplicadas y sesgo, y comprueban
limpieza y memoria/handles en rutas externas.

Los temporales no guardan procedencia por fila. La ausencia de RIDs en joins
espoleados/particionados es una decisión explícita compatible con la tarea
6.3, que permite procedencia combinada **o ausente** para filas de join. El
estado de un grupo en `IndexOrderedGroup` es acotado por una fila base y por el
número de agregados del plan; esta ruta opcional no sustituye a la agrupación
externa obligatoria. La ratificación transversal de la etapa sigue pendiente.
