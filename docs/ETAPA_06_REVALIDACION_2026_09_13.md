# Revalidación transversal de la Etapa 6

Fecha: **2026-09-13**. Alcance: tareas **6.1–6.31** y los **59 criterios** de la
Definition of Done de [ETAPA_06.md](../ETAPA_06.md#13-definition-of-done).
Esta revisión continúa la [auditoría histórica](ETAPA_06_AUDIT.md) y la
[revisión independiente](ETAPA_06_REVIEW_2026_09_13.md). No inicia la Etapa 7.

La numeración de los criterios se conserva exactamente como en la auditoría
histórica: las siete secciones del checklist tienen 8, 7, 8, 9, 9, 9 y 9
criterios, respectivamente. Las 59 filas de evidencia de aquella auditoría
siguen siendo la referencia de alcance; los informes siguientes registran la
inspección y las correcciones posteriores:

| Criterios | Tareas | Evidencia de la revisión actual |
|---|---|---|
| 1–8: prerrequisitos y contratos | 6.1–6.5 | [6.1–6.4 y 6.6–6.10](ETAPA_06_REVIEW_6_1_6_4_6_6_6_10.md), [6.5](ETAPA_06_REVIEW_6_5_6_11_6_15_6_16.md) |
| 9–15: operadores en flujo y acceso | 6.6–6.10 | [Scans, Filter, Projection y guardián B+](ETAPA_06_REVIEW_6_1_6_4_6_6_6_10.md) |
| 16–23: ordenamiento externo | 6.11–6.16 | [Recursos y runs](ETAPA_06_REVIEW_6_5_6_11_6_15_6_16.md), [temporales y sort](ETAPA_06_REVIEW_6_12_6_14.md) |
| 24–32: agrupación | 6.17–6.21 | [Agregados, presupuesto y fallback](ETAPA_06_REVIEW_6_17_6_18_6_20_6_21.md), [particionador](ETAPA_06_REVIEW_6_19_6_27_6_30.md) |
| 33–41: joins | 6.22–6.26 | [Baseline, Grace y rutas opcionales](ETAPA_06_REVIEW_6_22_6_26.md) |
| 42–50: composición y limpieza | 6.27–6.29 | [Plan, métricas y fallos](ETAPA_06_REVIEW_6_19_6_27_6_30.md), además de las pruebas de temporales, sort y joins de los bloques anteriores |
| 51–59: observabilidad y entrega | 6.27–6.31 | [Informes y pruebas diferenciales](ETAPA_06_REVIEW_6_19_6_27_6_30.md), esta revalidación y la suite completa |

## Resultado técnico

Las rutas obligatorias siguen siendo `ExternalSort`, `ExternalHashGroup` y
`GraceHashJoin`; las rutas por índice son adicionales. Las correcciones
reproducidas y comprobadas abordan recursos compartidos y catálogos de runs,
limpieza y E/S del particionador, métricas de plan, integridad de temporales,
estado de agregación y procedencia de joins espoleados. La suite estricta
transversal pasa **2295 pruebas**. Con la evidencia del checklist histórico,
las revisiones por bloque y esta regresión, los 59 criterios tienen respaldo
técnico actual bajo las decisiones documentadas de la etapa.

Los joins con spool o particiones publican procedencia vacía porque los
temporales guardan valores, no RIDs por fila. Esto satisface la opción de
procedencia ausente de la tarea 6.3 y corrige la formulación abreviada del
criterio 6 en la auditoría histórica. `IndexNestedLoopJoin` sí combina los
RIDs exactos de cada par.

Los presupuestos expresan **memoria de trabajo contabilizada**, no RSS del
intérprete. El espacio temporal informa bytes físicos propios vivos y el
volcado informa bytes de filas acumulados, magnitudes distintas. Las
salvedades C (guardián B+ sin cota) y D (pico temporal no observado) del
cierre histórico quedaron resueltas en las revisiones de
[scans e índices](ETAPA_06_REVIEW_6_1_6_4_6_6_6_10.md) y de
[métricas](ETAPA_06_REVIEW_6_19_6_27_6_30.md), respectivamente. Las
decisiones de 6.2 constan en
[su documento](ETAPA_06_TASK_6_2_DECISIONS.md) y en
[PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md); se mantiene la salvedad
histórica de que el equipo debe revisar las que condicionan la Etapa 7 antes
de iniciarla. `engine/query/` y `engine/transactions/` siguen sin
implementación de esa etapa y no existe `ETAPA_07.md`.

## Verificación

Entorno: Windows, Python 3.12.4, pytest 8.4.2, plugins externos deshabilitados,
advertencias tratadas como errores.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider -x
.\.venv\Scripts\python.exe -m compileall -q engine tests
git diff --check
```

La suite completa pasó **2295 pruebas en 1033,17 s**, sin fallos. El primer
intento detectó una prueba de métricas que fijaba literalmente el mínimo
anterior de agrupación (34 816 bytes); se actualizó para usar
`MINIMUM_GROUP_BUDGET_BYTES` (36 864 bytes) y conservar el fallback forzado.
Las 33 pruebas de métricas y recursos y las 94 pruebas diferenciales pasaron
también por separado. `compileall` y `git diff --check` pasan.
