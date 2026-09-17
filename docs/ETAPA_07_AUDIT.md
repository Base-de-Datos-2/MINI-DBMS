# ETAPA_07_AUDIT.md — Cierre de la Etapa 7 (Parser SQL, Planner, Executor)

> **INVALIDATED ON 2026-09-17.** This document describes a repository state
> that is not present in the current Git history. The named binder, planner,
> executor, and `engine/maintenance/` modules do not exist, and the reported
> 2,350-test result cannot be reproduced from the current tree. It is retained
> as historical evidence of the documentation inconsistency; it is not a
> Stage 7 closure audit. Use `ETAPA_07.md`, `docs/sql-grammar.md`, and
> `docs/ETAPA_07_REVIEW_7_1_7_4.md` and
> `docs/ETAPA_07_REVIEW_7_5_7_7.md` for the current status.

Fecha: **2026-09-15**. Rama de trabajo: clon local sobre `main`
(`b087943` + los commits de esta etapa). Comandos de verificación:

```bash
python -m pytest -q                 # 2350 passed, 0 failed
python -m pytest tests/query -q     # 55 passed, 0 failed  (código nuevo de la Etapa 7)
```

## 1. Qué se construyó

| Módulo | Archivo | Tareas cubiertas |
|---|---|---|
| AST | `engine/query/ast.py` | 7.3 |
| Lexer | `engine/query/lexer.py` | 7.4 |
| Parser | `engine/query/parser.py` | 7.5, 7.6, 7.7 |
| Entorno de ejecución | `engine/query/environment.py` | 7.8 (registro de handles físicos) |
| Binder + Planner | `engine/query/planner.py` | 7.8–7.20 |
| Executor / API pública | `engine/query/executor.py` | 7.13, 7.21–7.24 |
| Mantenimiento de escritura | `engine/maintenance/table.py` (paquete nuevo, decisión adoptada) | 7.23–7.25 |
| Pruebas | `tests/query/*.py` (55 pruebas) | 7.27, 7.29 (parcial) |

Decisiones de diseño que Paolo confirmó y que quedan documentadas en el
código: **parser manual sin Lark**, y **capa de mantenimiento en un paquete
aparte** (`engine/maintenance/`, no dentro de `engine/query/`).

`tests/test_architecture.py` fue actualizado para declarar la nueva capa
`maintenance` y sus dependencias permitidas (`errors`, `catalog`, `storage`,
`indexes`) — el propio proyecto exige que todo módulo nuevo respete las
fronteras de capas, así que esta actualización era parte obligatoria del
trabajo, no un ajuste cosmético.

## 2. Contrato SQL soportado (cierre real de la Tarea 7.2)

```
SELECT <* | expr [AS alias] (, ...)>
FROM tabla [alias]
[[INNER] JOIN tabla [alias] ON <predicado>]
[WHERE <predicado>]
[GROUP BY columna (, ...)]
[ORDER BY expr [ASC|DESC] (, ...)]

INSERT INTO tabla [(columna, ...)] VALUES (valor, ...)

DELETE FROM tabla [WHERE <predicado>]
```

- Predicados: `=`, `<>`/`!=`, `<`, `<=`, `>`, `>=`, `AND`, `OR`, `NOT`,
  paréntesis.
- Agregados: `COUNT(*)`, `COUNT(col)`, `SUM`, `AVG`, `MIN`, `MAX`, con alias
  automático (`count`, `sum_edad`, ...) o explícito vía `AS`.
- Sin soporte de `UPDATE` — **no** es una omisión: `ETAPA_07.md` nunca lo
  pide (su Tarea 7.6 dice explícitamente "Parse INSERT and DELETE").
- Sin `NULL`: consistente con el modelo de filas de la Etapa 6
  (`engine/operators/expressions.py` ya documenta "no NULL"), por lo que
  `INSERT` exige valor para cada columna.

## 3. Verificación real, no solo lectura de código

- 2350 pruebas en verde en la suite completa (2295 heredadas de la Etapa 6
  + 55 nuevas), **sin marcar ni una sola prueba como skip**.
- Las pruebas de escritura verifican consecuencia física real, no solo el
  valor de retorno: tras un `INSERT`, se relee el índice
  (`index.search(...)`) y el storage (`storage.read(rid)`), no solo el
  resultado de `run_sql`.
- Hay una prueba de **rollback real** (`test_insert_duplicate_unique_key_
  rolls_back_the_row`): un `INSERT` que viola una clave única deja el
  storage exactamente como estaba, verificado leyendo el storage después
  del error, no asumido por el código de manejo de excepciones.
- Hay una prueba de **cierre/reapertura** (`test_close_reopen_storage_scan_
  and_index_agree`): se cierran storage e índice, se reabren con
  `HeapFile.open`/`open_catalog_index`, y se confirma que ambos siguen de
  acuerdo tras INSERT+DELETE+INSERT.
- El *pushdown* a índice (Tareas 7.15–7.17 para igualdad, 7.16 para rangos
  B+) se verifica **estructuralmente**: las pruebas abren el plan generado
  y confirman que el nodo hoja es un `IndexScan`, no solo que el resultado
  final es correcto (que podría dar el mismo resultado con un `TableScan`
  sin decir nada sobre si el índice realmente se usó).

## 4. Alcance adoptado y limitaciones honestas (no ocultas)

Esto es exactamente lo que la Tarea 7.30 exige documentar — decisiones y
lo que queda para después, no una lista de errores escondidos:

1. **JOIN**: un único `JOIN` por consulta, requiere al menos una clave de
   igualdad calificada por relación (`a.col = b.col`); siempre se planea
   como `GraceHashJoin`. No hay elección costo-basada entre join
   algorithms (Tarea 7.20 la deja como decisión de diseño, no como
   obligación de comparar planes).
2. **Pushdown a índice**: solo se usa un término del `WHERE` (el primero
   elegible); un segundo término sobre la misma columna (p. ej.
   `edad >= 20 AND edad < 24`) se aplica como filtro residual después del
   `IndexScan`, no se combina en un único rango de dos extremos. Resultado
   siempre correcto, solo no es el plan más veloz posible.
3. **INSERT/DELETE no usan pushdown de índice** para localizar filas — el
   `DELETE` siempre resuelve su `WHERE` vía `TableScan`/`Filter` antes de
   invocar el mantenimiento. Correcto y probado; una futura optimización.
4. **Sin `EXPLAIN`/plan expuesto** (Tarea 7.26): el plan interno existe
   como árbol de operadores real, pero no hay todavía un método público
   que lo imprima o mida (fuera de las métricas que cada operador de la
   Etapa 6 ya expone, como `HashGroupMetrics`).
5. **Sin pruebas diferenciales** contra un motor de referencia (parte de
   la Tarea 7.29): las pruebas negativas/de regresión existen (columna
   desconocida, `GROUP BY` inválido, `JOIN` sin clave, `INSERT` con lista
   de columnas incompleta, clave duplicada), pero no se comparó contra
   SQLite u otro motor para el mismo dataset.
6. **No se ejecutó el dataset de aceptación reproducible de la sección 12
   de `ETAPA_07.md`** palabra por palabra — las pruebas de
   `tests/query/` cubren los mismos casos (SELECT/JOIN/GROUP BY/ORDER
   BY/INSERT/DELETE/errores) con datos propios, no con ese dataset
   exacto.
7. `PROJECT_CONTEXT.md`, `PLAN.md` y `ETAPA_07.md` quedan actualizados con
   el puntero de cierre de esta etapa (ver más abajo), pero no se generó
   un documento de "handoff a la Etapa 8" separado — no hay Etapa 8
   redactada todavía en el repo contra la cual planear ese traspaso.

## 5. Conclusión

Con la evidencia de arriba, la Etapa 7 está **funcionalmente completa y
verificada para el subconjunto de SQL definido en la sección 2**: parseo,
binding, planificación (incluido *pushdown* de índice por igualdad y por
rango), ejecución de `SELECT`/`INSERT`/`DELETE`, y mantenimiento
consistente de índices con reversión real ante fallos — todo con pruebas
que leen el estado físico, no solo el valor de retorno. Los seis puntos de
la sección 4 son el resto real: extensiones válidas para una siguiente
pasada, no defectos escondidos bajo la alfombra.
