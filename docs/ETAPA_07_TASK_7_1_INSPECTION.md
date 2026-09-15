# Task 7.1 — Inspección de la Etapa 6 completada y línea base real

Fecha: **2026-09-14**. Alcance: Tarea 7.1 de [ETAPA_07.md](../ETAPA_07.md) —
"Inspect the completed Stage 6 implementation".

Este documento **no implementa nada**. Establece, con evidencia real de
repositorio, los contratos exactos que la Etapa 7 va a invocar, y señala las
brechas que `ETAPA_07.md` da por existentes pero que **no existen todavía**
en el código.

## 1. Comandos ejecutados y resultado real

```bash
git clone https://github.com/Base-de-Datos-2/MINI-DBMS.git
pip install -e ".[test]"
python -m pytest -q
```

Resultado: **2295 pruebas, 0 fallos, 0 errores** (rama `main`,
commit `b087943` — "INDICACIONES DE LA ETAPA 07").

Esto confirma lo que ya declaran `README.md`, `PROJECT_CONTEXT.md` y
`PLAN.md`: **las Etapas 1–6 están cerradas y auditadas** (ver
[ETAPA_06_AUDIT.md](ETAPA_06_AUDIT.md) y su revalidación del 2026-09-13).
La cifra de 2252 pruebas de esa auditoría creció a 2295 por commits
posteriores de corrección de la Etapa 6 (`aa85cc7`, etc.), sin regresiones.

## 2. Estado real de `ETAPA_07.md`

`ETAPA_07.md` **sí existe** (fue el último commit antes de esta auditoría),
pero es la traducción de indicaciones/plantilla del curso al repositorio —
equivalente a lo que en etapas previas fue el insumo de partida, **no** el
documento de auditoría/decisiones ya ejecutado como lo son
`ETAPA_06_AUDIT.md`, `ETAPA_06_TASK_6_1_INSPECTION.md`, etc. Es decir: la
sospecha de Paolo era correcta — hay indicaciones, pero todavía no hay
trabajo de la Etapa 7 ejecutado ni verificado sobre ellas.

`PROJECT_CONTEXT.md:1994` y `PLAN.md:1339` siguen marcando
**"Stage 7 — not started"**; ninguno de los dos ha sido actualizado todavía
con los punteros de esta etapa (eso corresponde a la Tarea 7.30, al cierre).

## 3. Código existente para la Etapa 7

`engine/query/__init__.py` contiene únicamente:

```python
"""Reserved for SQL parsing, planning, and execution."""
```

No hay AST, lexer, parser, binder, planner ni executor. **Cero líneas de
código de la Etapa 7 existen hoy.** Tampoco hay dependencia de `Lark` en
`pyproject.toml` (`dependencies = []`).

## 4. Contratos reales que la Etapa 7 debe invocar (no reimplementar)

| Componente | Ubicación real | Contrato relevante |
|---|---|---|
| Catálogo | `engine/catalog/catalog.py` | `Catalog` en memoria, no persistente, nombres exactos case-sensitive, sin espacio de nombres compartido entre tablas e índices. `register_table`, `get_table`, `list_tables`, `register_index`, resolución de referencias con `UnknownTableError`/`UnknownColumnError`. |
| Esquema/tipos | `engine/catalog/schema.py`, `types.py`, `metadata.py` | Tipado de columnas y metadata de tabla/índice usados por operadores Etapa 6. |
| Operadores | `engine/operators/base.py` | Contrato `Operator(ABC)` **open/next/close** *pull-based*; instancia arranca cerrada; `None` es la única señal de agotamiento; cierre obligatorio en toda ruta (éxito, corte temprano, excepción). Este es el contrato que el executor de la Etapa 7 debe reutilizar tal cual. |
| Expresiones | `engine/operators/expressions.py` | Modelo de expresiones tipadas ya usado por `Filter`/`Join`/agregaciones — es lo que el binder (7.9) debe producir, no un motor de expresiones nuevo. |
| Filas/])esquema físico | `engine/operators/rows.py` | `ColumnReference`, `RowLayout`, `RowProvenance` — identidad de columna después de operadores que cambian esquema; clave para 7.10 (ORDER BY oculto) y 7.17 (pushdown). |
| Acceso físico | `engine/operators/scan.py`, `index_strategies.py` | Rutas de acceso ya implementadas para *scan* e índice. |
| Ordenamiento externo | `engine/operators/sorting.py` | `ExternalSort` k-way — la Etapa 7 debe alcanzar esta implementación desde `ORDER BY`, no reescribirla. |
| Agrupación | `engine/operators/aggregation.py` | Ruta de `GROUP BY` optimizada aceptada en la Etapa 6. |
| Joins | `engine/operators/join.py` | Variantes de join aceptadas en la Etapa 6 (Grace Hash / Nested Loop / Index Nested Loop según lo cerrado ahí). |
| Índices | `engine/indexes/index_catalog.py`, `bplus_catalog.py`, `hash_catalog.py` | `build_catalog_index` — despacho de un índice registrado a su clase física real (B+ o Hash, clustered/unclustered). Es la pieza que el planner (7.15–7.16) debe consultar para elegibilidad de índice. |

## 5. Brecha crítica encontrada: no existe una capa de mantenimiento de escrituras

`ETAPA_07.md` (Tareas 7.12, 7.23–7.25 y la tabla de módulos sugeridos en
§11) da por sentado un **"Existing maintenance module"** que inserte/borre
en el storage físico y mantenga todos los índices afectados de forma
consistente.

Ese módulo **no existe en el repositorio**. Búsqueda exhaustiva
(`grep -rln "def insert\|def delete\|class.*Maintenance"` en `engine/`)
solo encuentra métodos de bajo nivel dentro de cada estructura física
(`HeapFile`, `PagedSequentialFile`, `BPlusTree`, `ExtendibleHashIndex`,
etc.), **no** un servicio que combine "escribir el registro" +
"actualizar cada índice afectado" +  "reportar fallo a medio camino" como
exige la Tarea 7.25.

**Consecuencia para la Etapa 7:** antes de poder ejecutar 7.23 (INSERT) y
7.24 (DELETE) tal como están redactadas, hace falta construir esa capa de
mantenimiento (tabla lógica = storage físico + sus índices registrados en
Catálogo). Esto es trabajo genuino de la Etapa 7, no una reutilización de
algo ya cerrado en la Etapa 6 — Etapa 6 fue puramente de **lectura**
(operadores relacionales sobre datos ya existentes).

## 6. Otras verificaciones de la Tarea 7.1

- **Duplicados y NULL:** los operadores de la Etapa 6 preservan
  duplicados (semántica de bolsa) y su política de `NULL` está definida en
  `engine/operators/expressions.py`; el binder de la Etapa 7 debe heredar
  esa política, no definir una propia.
- **RID y reorganización:** `engine/storage/rid.py` y
  `sequential_ordering.py` confirman que el storage secuencial/clustered
  puede mover RIDs existentes al insertar — esto es exactamente el riesgo
  que la Tarea 7.24 exige controlar en DELETE (no borrar una fila
  recién movida solo porque ocupa un slot antiguo).
- **Presupuestos de memoria:** `engine/operators/context.py` expone
  `ExecutionContext` con los presupuestos ya usados por `ExternalSort` /
  `ExternalHashGroup` / `GraceHashJoin`; el executor de la Etapa 7 debe
  reutilizar esta misma clase, no crear un contexto paralelo.

## 7. Conclusión de la Tarea 7.1

- El reporte de Paolo de que "las etapas previas están finalizadas" es
  **correcto y verificado**: Etapa 6 cerrada, 2295/2295 pruebas en verde.
- `ETAPA_07.md` existe como especificación, **no** como trabajo ejecutado.
- El punto de partida real de código es **cero** para parser/binder/
  planner/executor, y falta además una pieza arquitectónica no prevista
  explícitamente en la Etapa 6: el servicio de mantenimiento de
  escritura + índices.
- Dado el tamaño real de la Etapa 7 (30 tareas, 16 invariantes de
  ejecución en §7, ~50 ítems de Definition of Done en §14, todos exigiendo
  evidencia verificada de pruebas), **no es honesto ni verificable
  declararla completa al 100% sin ejecutar y probar cada incremento**,
  tal como el propio documento exige en su Acceptance de cada tarea y en
  la Tarea 7.30 ("Do not mark Stage 7 complete without evidence"). Se
  procede en incrementos A–F, igual que en las Etapas 3–6, con pruebas
  verificadas después de cada uno.
