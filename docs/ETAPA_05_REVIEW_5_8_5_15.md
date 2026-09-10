# Revisión y correcciones de las tareas 5.8–5.15

Fecha: **2026-09-10**. Alcance: ciclo de vida, búsquedas, inserciones,
divisiones, duplicados y colisiones de Extendible Hashing según
[ETAPA_05.md](../ETAPA_05.md). Se preservan las correcciones del
[bloque 5.1–5.7](ETAPA_05_REVIEW_5_1_5_7.md) y el formato persistente v1.

## Resultado por criterio de aceptación

| Tarea | Resultado | Evidencia revisada o añadida |
|---|---|---|
| 5.8 — Ciclo de vida | Cumple tras corregir los tipos de metadatos esperados por `open()`. | Estructura vacía validada antes/después de reapertura; profundidades iniciales 0, 1 y 3, límite y unicidad persistidos; cierre idempotente; archivo B+ rechazado sin alterarlo; cierre del gestor tras apertura fallida; fallos físicos de creación limpian exclusivamente el archivo nuevo. |
| 5.9 — Búsqueda exacta | Cumple tras comprobar profundidad local contra global durante la lectura del bucket seleccionado. | Generadores diferidos/cerrables; igualdad de clave completa, duplicados y colisiones; consulta sobre la segunda página del directorio con exactamente dos lecturas de directorio y una de bucket, bloqueando cualquier acceso a buckets ajenos. |
| 5.10 — Inserción sin crecimiento | Cumple tras extender la misma comprobación contextual a inserción. | Se capturan las escrituras: únicamente bucket objetivo y cabecera; profundidad y aliases permanecen iguales; claves/RID inválidos no modifican un byte ni incrementan escrituras. |
| 5.11 — Split con d < D | Cumple dentro de la política de fallos documentada. | Verificación de aliases ajenos intactos, hijos a profundidad d+1, tamaño de directorio constante, entradas conservadas y reapertura inmediata; claves de tamaños distintos respetan la capacidad real en bytes. |
| 5.12 — Duplicación | Cumple dentro de la política de fallos documentada. | Duplicación LSB, referencias intactas de buckets no afectados, orden observado de publicación, extensión hasta tres páginas y fallos de escritura en las distintas fases de una división. |
| 5.13 — Splits repetidos | Cumple; el bucle y la planificación existentes se conservan. | Claves con diez bits bajos comunes llevan de D=1 a D=11, con lados vacíos, aliases correctos y tres páginas; búsquedas y validación tras reapertura. El mismo escenario con máximo D=10 falla antes de asignar o escribir. |
| 5.14 — Duplicados/unicidad | Cumple tras preservar idempotencia en el límite del contador. | Matriz pública contrastada con B+ antes de dividir y después de dividir/reabrir: mismo par, segundo RID, error único, borrado parcial/final y reinserción. Unicidad e idempotencia mantienen los bytes sin cambios. |
| 5.15 — Colisiones inseparables | Cumple con la política adoptada de error acotado. | Pruebas existentes con hash constante y claves distintas, más un bucket lleno con una sola clave y muchos RIDs; rechazo sin modificar archivo, reinserción idempotente y recuperación de todas las asociaciones tras reabrir. |

Pruebas nuevas:
[test_hash_growth_review.py](../tests/indexes/test_hash_growth_review.py).
También se revisaron y ejecutaron `test_extendible_hash.py`,
`test_hash_restart_differential.py`, `test_hash_integration.py` y la suite
acumulada de las etapas anteriores.

## Correcciones de código

1. `open()` comparaba valores sin exigir tipos: Python considera `1 == True` y
   `0 == False`, por lo que aceptaba metadatos esperados con tipos inválidos.
   Ahora distingue error de tipo de incompatibilidad de valor.
2. El codec de bucket validaba el rango absoluto de profundidad, pero búsqueda
   e inserción no comprobaban su relación con la profundidad global. El helper
   `_read_routed_bucket()` aplica la comprobación a la página ya seleccionada;
   no convierte las búsquedas en recorridos globales ni añade lecturas físicas.
3. El límite uint64 del contador se comprobaba antes de reconocer un par ya
   existente. Ahora se aplica únicamente a asociaciones nuevas, después de
   idempotencia y unicidad. La prueba del límite es sintética en memoria y
   restaura la cabecera original; no pretende construir un dataset de 2^64 filas.

Estas correcciones se limitan a
[extendible_hash.py](../engine/indexes/extendible_hash.py). No fue necesario
reescribir los algoritmos de split/doubling ni cambiar sus formatos.

## Fallos físicos y precedencia arquitectónica

La secuencia conceptual de 5.12 menciona persistir el directorio antes de
dividir el bucket. Se conserva el orden estable de `PROJECT_CONTEXT.md`:
planificar en memoria, escribir buckets inicializados, escribir directorio y
publicar cabecera. Esto respeta la regla que impide que el plan de una tarea
reemplace una decisión arquitectónica estable.

Para rechazos de validación, unicidad, límite de profundidad y colisión
inseparable, se verificó preservación byte a byte del archivo. El plan completo
de splits se resuelve antes de iniciar asignaciones.

Para fallos físicos, las pruebas inyectan `OSError` en el handle usado por
`PageManager`, no en un sustituto del algoritmo hash. Se prueban los seis
puntos de escritura de una división simple: asignación de página vacía,
cabecera física de asignación, nuevo bucket, bucket anterior, directorio y
cabecera del índice. En todos ellos el gestor se cierra y rechaza continuar
consultando a través de esa instancia. Si falla la primera escritura, los bytes
originales siguen intactos y reabren; en los restantes escenarios probados, la
reapertura detecta la publicación incompleta.

No hay WAL ni rollback físico automático: un fallo de E/S tras escrituras
parciales puede requerir reconstrucción desde el almacenamiento. La afirmación
de preservación en 5.13 no se extiende a cualquier fallo del sistema operativo;
se interpreta conforme a esos límites arquitectónicos. Las pruebas de fallos
inyectados no demuestran recuperación ante todos los posibles cortes de energía.

## Validación

Línea base heredada del bloque previo: **1683 pruebas aprobadas** con
advertencias como errores. La primera tanda de este bloque reprodujo
**5 fallos y 24 aprobaciones**, correspondientes a los tres defectos anteriores.
Tras corregirlos, la tanda junto con pruebas existentes de crecimiento,
reinicio e integración pasó **62 pruebas**. La tanda nueva definitiva añade
**33 casos**, incluidos fallos de creación y claves de longitudes distintas.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider tests/indexes/test_hash_growth_review.py
.\.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q engine tests
git diff --check
```

- Pruebas nuevas: **33/33 aprobadas**.
- Suite completa: **1716 aprobadas en 52,98 s**, con advertencias como errores,
  sin omisiones ni xfails; incluye las pruebas existentes de arquitectura e
  importaciones y las correcciones del bloque anterior.
- `compileall` y `git diff --check`: correctos.
- Enlaces locales de los documentos revisados: sin referencias rotas.

Resultado: **las ocho tareas 5.8–5.15 cumplen sus criterios bajo las políticas
arquitectónicas adoptadas y los límites de recuperación descritos arriba**.

## Límite de esta revisión

Se determinaron los criterios de **5.8–5.15**, sin volver a certificar el cierre
global de la Etapa 5. Permanecen pendientes los hallazgos ya identificados en
5.23 (rollback Heap/índice), 5.25 (E/S tipada de creación), 5.26 (validación
diferencial por mutación) y 5.27/cierre (trazabilidad de los 47 criterios).
