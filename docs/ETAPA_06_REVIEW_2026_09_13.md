# Revisión de coherencia de la Etapa 6

Fecha: 2026-09-13. Entorno de revisión: Windows, Python 3.12.4, pytest 8.4.2.

> Seguimiento: la [corrección de 6.5, 6.11, 6.15 y 6.16](ETAPA_06_REVIEW_6_5_6_11_6_15_6_16.md)
> aborda recursos del sort, metadatos de runs y aislamiento de temporales, y
> la [revisión de 6.19 y 6.27–6.30](ETAPA_06_REVIEW_6_19_6_27_6_30.md)
> corrige el cierre del particionador y los informes de E/S. El texto
> siguiente conserva la evidencia anterior a ambas correcciones.

## Dictamen

La implementación es coherente con la arquitectura, las familias de operadores
y las rutas algorítmicas principales de `ETAPA_06.md`. Sin embargo, esta revisión
**no ratifica el cumplimiento de los 59 criterios ni el cierre técnico completo**:
hay defectos reproducibles en el presupuesto de memoria, los límites de archivos
abiertos, los metadatos de runs, la limpieza y las métricas de E/S.

Los problemas descritos no requieren implementar la Etapa 7 ni sustituir los
algoritmos. Requieren completar garantías ya exigidas por la Etapa 6.

Esta revisión no modifica el código ni cambia los estados de los documentos de
coordinación. Distingue las conclusiones de la auditoría anterior de las
observaciones obtenidas directamente del código y de ejecuciones específicas.

## Correspondencia con el plan

| Área del plan | Implementación observada | Evaluación |
|---|---|---|
| 6.3–6.4: filas, esquema y ciclo de vida | `RowLayout`, `ColumnReference`, `ExecutionOperator`, `open/next/close` | Contratos presentes; el cierre ante ciertos fallos tiene el defecto H3 |
| 6.6–6.10: predicados y operadores en flujo | `TableScan`, `IndexScan`, `Filter`, `Projection` | Estructura coherente; tipos ligados, multiplicidad, acceso B+ por igualdad/rango y hash por igualdad |
| 6.11–6.12: temporales | `TemporaryWorkspace`, `TemporaryRowReader/Writer`, `PageManager` | Archivos reales, framing y reapertura; aislamiento y limpieza incompletos, H3–H4 |
| 6.13–6.16: ordenamiento externo | `ExternalSort`, runs ordenados, `heapq`, mezcla estable y múltiples pasadas | Algoritmo presente; recursos y metadatos incumplen H1–H2 |
| 6.17–6.21: agrupación externa | Agregados, `HashGroupKernel`, `HashPartitioner`, `ExternalHashGroup` | Ruta de hashing externo real, reintento de partición completa y fallback por sort |
| 6.22–6.25: joins | `NestedLoopJoin`, `HashJoinKernel`, `GraceHashJoin` | Baseline independiente, duplicados conservados, particionado y fallback por bloques |
| 6.26: estrategias opcionales | `IndexNestedLoopJoin`, `IndexOrderedGroup` | Se agregan a las rutas externas obligatorias, sin sustituirlas |
| 6.27–6.28: composición y observabilidad | `PhysicalPlan`, `run_plan`, descriptores y métricas | Ejecución manual coherente; medición y límites incompletos, H1 y H5 |
| 6.29–6.31: verificación y entrega | Pruebas unitarias/integración, auditoría e informes por incremento | Cobertura sustancial, pero la afirmación de cumplimiento completo excede la evidencia |

Las decisiones de no admitir NULL, no convertir tipos numéricos implícitamente
y limitarse a inner equijoins están documentadas en `PROJECT_CONTEXT.md`; no se
consideran omisiones respecto de un estándar SQL completo. La ausencia de parser,
planner SQL, transacciones y frontend es coherente con el alcance de esta etapa.
Las campañas comparativas 1K/10K/100K corresponden a la Etapa 10.

## Hallazgos

### H1 — Alta: la mezcla no respeta ni registra todos sus recursos

Ubicación: [sorting.py:427](../engine/operators/sorting.py#L427),
[temp_stream.py:287](../engine/operators/temp_stream.py#L287).

`ExternalSort._merge_rows()` abre lectores y conserva las filas cabeza y el heap
sin reservar su memoria ni adquirir permisos de archivo. Los lectores y escritores
temporales tampoco incorporan por sí mismos un `ExecutionContext`. Calcular el
fan-in con el número de buffers no sustituye la reserva de las filas decodificadas,
especialmente cuando abarcan varias páginas, ni controla la suma de handles de
operadores que ejecutan simultáneamente.

Reproducciones ejecutadas:

1. Tres registros `(INTEGER, VARCHAR)` con strings de 7000 caracteres, un sort
   con asignación de 16 384 bytes y contexto padre de 32 768 bytes. Tras pedir la
   primera fila de la mezcla: tres lectores abiertos, cero handles registrados
   y cero bytes reservados en el contexto del sort. Las tres filas retenidas
   suman **21 420 bytes según `row_footprint_bytes` del propio proyecto**, antes
   de añadir buffers o heap. No es una comparación contra el RSS de Python.
2. `GraceHashJoin` sobre dos `ExternalSort`, 100 claves INTEGER por lado,
   asignación de 12 237 bytes para cada bloqueante, contexto de 65 536 bytes,
   dos particiones y `max_open_handles=3`. La instrumentación de aperturas y
   cierres de `PageManager` observó **4 archivos simultáneos**; el informe
   declaró un pico de **2**. La ejecución devolvió las 100 filas esperadas.

Contradice el invariante 10 y las tareas 6.5, 6.15, 6.27–6.30. Las aserciones
actuales sobre `peak_reserved_bytes` y `peak_open_handles` no detectan recursos
que nunca fueron registrados.

Corrección necesaria: conectar lectores/escritores y estado retenido a las
reservas y permisos compartidos; calcular la admisión y el fan-in considerando
las filas cabeza y el resto del estado simultáneo.

### H2 — Alta: el total de metadatos de runs crece sin límite

Ubicación: [sorting.py:389](../engine/operators/sorting.py#L389),
[temp_files.py:155](../engine/operators/temp_files.py#L155).

`_generate_runs()` acumula todos los descriptores en una lista y el workspace
mantiene un diccionario con todos sus paths. No hay reserva para estos metadatos,
límite explícito de runs ni catálogo en disco. Que cada `TemporaryRun` tenga un
tamaño pequeño no hace que la colección completa sea acotada.

Con la misma asignación de **12 237 bytes**, 100 filas INTEGER produjeron
**2 runs/paths**, y 1000 filas produjeron **17 runs/paths**. Al terminar la
generación seguían retenidos y el contexto del sort registraba **0 bytes**.
La lista crece con la entrada antes de que empiece la reducción por pasadas.

Contradice explícitamente las tareas 6.5 y 6.16 y el control del riesgo de
metadatos ilimitados de la sección 14.

Corrección necesaria: almacenar los descriptores en disco, reducirlos de forma
incremental o imponer y documentar un límite real cuya memoria esté reservada.

### H3 — Alta: un fallo al finalizar particiones impide cerrar los escritores

Ubicación: [partitioning.py:310](../engine/operators/partitioning.py#L310).

`HashPartitioner.finish()` marca `_finished=True` antes de finalizar todos los
writers. Su `finally` vacía `_writers` y libera los permisos, pero no cierra los
escritores pendientes si `writer.finish()` falla. Después, `close()` omite
`_release()` porque el particionador ya está marcado como terminado.

Se inyectó `OSError` en `TemporaryRowWriter.finish()` con dos particiones:
después de `partitioner.close()`, los dos managers conservados para inspección
seguían abiertos, mientras el contexto declaraba **0 handles** y el particionador
ya no retenía writers para cerrarlos. Se cerraron manualmente al acabar la prueba.

También se reprodujo a través de `collect(ExternalHashGroup(...))`: en Windows
la limpieza falló con `ValidationError: Temporary cleanup left files behind`,
y el writer que había fallado seguía abierto. Los archivos de esta reproducción
se cerraron y eliminaron al finalizarla.

Contradice las tareas 6.4, 6.11, 6.19 y 6.29: un error de escritura ordinario debe
liberar los recursos adquiridos y conservar la causa original de la operación.

Corrección necesaria: intentar cerrar todos los writers en el camino de error,
antes de descartar sus referencias y devolver los permisos.

### H4 — Alta: la asignación permite escapar del directorio temporal

Ubicación: [temp_files.py:146](../engine/operators/temp_files.py#L146).

`TemporaryWorkspace.allocate()` concatena `label` y `suffix` sin rechazar
componentes de ruta ni comprobar que la ruta resuelta permanezca dentro del
directorio propio. El simple registro en `_files` convierte esa ruta en un
objetivo de limpieza, aunque el workspace no haya creado su contenido.

Reproducción aislada, usando solamente un archivo desechable creado para esta
revisión:

```python
with TemporaryDirectory() as parent:
    sentinel = Path(parent) / "outside-000000.tmp"
    sentinel.write_text("review-only sentinel")
    workspace = TemporaryWorkspace(parent_directory=parent)
    workspace.allocate("../outside")
    workspace.close()
    # sentinel.exists() es False
```

Los operadores actuales utilizan etiquetas internas fijas; el defecto se activa
al llamar esta API de soporte con una etiqueta que contiene una ruta. Aun así,
la garantía de que la limpieza nunca toca archivos ajenos no se cumple.

Contradice el invariante 7, la tarea 6.11 y el criterio de aislamiento de limpieza
de la Definition of Done.

Corrección necesaria: validar etiquetas/sufijos y la pertenencia de la ruta
resuelta, y evitar registrar como propio un archivo ajeno preexistente.

### H5 — Media: las páginas escritas reportadas no son el contador real de E/S

Ubicación: [sorting.py:386](../engine/operators/sorting.py#L386),
[partitioning.py:315](../engine/operators/partitioning.py#L315),
[page_manager.py:216](../engine/storage/page_manager.py#L216).

Se incrementa `temporary_pages_written` con `run.page_count + 1`, que cuenta
páginas del archivo terminado. Sin embargo, `PageManager.allocate_page()` escribe
la página vacía y `write_page()` la vuelve a escribir con su contenido. El
contador real del gestor registra ambas operaciones.

En un `ExternalSort` de **una fila**, instrumentando los contadores al cerrar
cada `PageManager`, hubo **4 escrituras de página**, pero el operador reportó
**2**. No se incluyen aquí escrituras adicionales del encabezado del archivo,
que tienen su propia política en etapas anteriores.

Esto no es la salvedad de no medir el pico de espacio temporal: se está
subcontando una métrica presentada como trabajo de E/S realmente realizado.
Contradice la tarea 6.28 y el criterio de observabilidad de E/S real.

Corrección necesaria: conservar y propagar los contadores reales antes del
cierre, separando cantidad de páginas almacenadas de operaciones de escritura.

## Pruebas y alcance de la evidencia

- Se contrastaron `REQUIREMENTS.md`, `PROJECT_CONTEXT.md`, `PLAN.md`,
  `ETAPA_06.md`, la auditoría de cierre y los informes de incrementos relevantes.
- Se inspeccionaron los operadores y sus utilidades, las pruebas de
  `tests/operators/` y las de integración `test_stage6_*`.
- Las reproducciones anteriores se ejecutaron en procesos Python independientes,
  con instrumentación temporal mediante `unittest.mock`; no cambiaron fuentes
  ni pruebas del repositorio.
- La ejecución estricta completa terminó con **2252 pruebas aprobadas en
  712,96 segundos**, sin fallos, omisiones ni xfails y con advertencias tratadas
  como errores. Incluye la regresión de las etapas anteriores.
- `git diff --check` no reportó errores. La única incorporación al repositorio
  de esta revisión es este informe.

Comando de regresión utilizado en PowerShell:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider
```

La ejecución actual reproduce el total de 2252 pruebas aprobadas declarado por
la auditoría anterior. Los hallazgos H1–H5 se confirmaron mediante las
reproducciones adicionales descritas arriba: no son fallos reportados por esa
suite. El propio test de límites del pipeline consulta los contadores del
contexto; necesita además verificar que las aperturas y retenciones reales se
registren.

## Consecuencia para el cierre

Los algoritmos externos requeridos están implementados: no corresponde rehacer
la etapa ni exigir SQL para considerarlos presentes. Sí corresponde resolver
H1–H5 y añadir regresiones para esos casos antes de ratificar su Definition of
Done. Las salvedades ya declaradas sobre `visited` de B+, aprobación de decisiones
y ausencia de pico de espacio temporal no cubren estos defectos nuevos.
