# Etapa 9 — revisión del 2026-09-25

Alcance: auditar la Etapa 9 contra [ETAPA_09.md](../ETAPA_09.md) y el
[handoff de la Etapa 8](ETAPA_08_STAGE_9_HANDOFF.md), revisar el reporte de un
conteo de índices incorrecto, añadir la creación e importación de tablas desde
el panel Archivos y, en una segunda parte del mismo día, implementar todo lo
que faltaba de la integración transaccional (sección 3).

**Estado:** todos los puntos del checklist del handoff y de la sección 11 de
`ETAPA_09.md` están cumplidos y verificados. El **cierre formal** de la
Etapa 9 queda a decisión del equipo. La Etapa 10 sigue pendiente.

## 1. Reporte: «con un índice y 4 tablas salen 4 índices»

**No se pudo reproducir en `main`.**

| Comprobación | Resultado |
|---|---|
| `GET /api/tables` sobre la base de demo real | students 2, enrollments 0, students_big 1, courses 1, enrollments_big 0: correcto |
| Owner manifest-backed: 4 tablas con `CREATE TABLE`, una con `PRIMARY KEY` | 1 índice (`__pk__a`) en total, también tras reabrir |
| `Catalog.get_indexes(tabla)` | Filtra por `index.table_name`; no devuelve índices de otras tablas |

Hay dos causas probables:

1. **La etiqueta del índice.** El panel Archivos mostraba «4 entradas» debajo
   de cada índice: el número de filas indexadas, no de índices. Con 4 filas y
   1 índice se lee «4». Ahora dice «indexa 4 filas».
2. **Código que no está en git.** `data/generated/demo` contiene
   `alumnos.heap`, `alumnos_id_hash.hsh`, `alumnos_nota_bplus.bpt` y
   `csv_tables.json` del 2026-09-18. Ningún commit, rama local ni remota tiene
   el importador que los creó, así que el defecto pudo estar en ese código.
   `main` ignora esos archivos. Se eliminan con
   `python scripts/setup_demo.py --reset`, con el servidor detenido.

Queda una regresión fija:
`tests/api/test_gui_tables.py::test_index_counts_stay_per_table_with_several_tables_and_one_index`.
Crea 3 tablas sin índices y 1 con un índice, y comprueba los conteos por
tabla, en la lista y en el detalle, antes y después de reabrir.

## 2. Añadido: crear e importar tablas desde el panel Archivos

Contrato completo en [demo.md, sección 7.1](demo.md). Resumen:

- `POST /api/import/preview` lee el CSV, infiere tipos y devuelve muestras.
  No carga nada ni toca el motor.
- `POST /api/tables` crea una tabla vacía o importa el CSV. Permite elegir Heap
  o Paged Sequential, e índices B+ o Hash extensible con las reglas del motor.
  Solo funciona con `--allow-writes`.
- La definición se guarda en `gui_tables.json`, que se escribe de forma
  atómica. Los archivos llevan nombres UUID opacos. Cualquier fallo deshace la
  creación y borra los archivos creados.
- La creación corre bajo el lock de esquema de la sesión por defecto
  (`run_schema_change`) y bajo el guard de admisión del servidor.
- En la interfaz, el diálogo **Nueva tabla** tiene dos pestañas: «Importar CSV»
  (con vista previa y tipos editables) y «Definir columnas».

La decisión de diseño está en `PROJECT_CONTEXT.md` (sección API). No cambia la
decisión previa: `CREATE TABLE` escrito en SQL sigue requiriendo el owner
manifest-backed. Ese owner solo admite tablas Heap e índices B+ de clave
primaria. Migrar la demo a él habría quitado de la interfaz el Paged
Sequential File y el Hash extensible.

### Correcciones hechas durante la auditoría

| Defecto | Corrección |
|---|---|
| Resultados decía «sin transacción ni rollback (Etapa 8 pendiente)», falso desde el cierre de la Etapa 8 | La respuesta de un comando incluye `transaction {id, committed}` y la interfaz muestra la transacción implícita |
| La insignia de modo decía «Transacciones pendientes» | Ahora dice «BEGIN/END por HTTP pendiente», que es lo que falta de verdad |
| Un owner en cuarentena respondía `500 INTERNAL_ERROR` | Ahora responde `503 ENGINE_UNAVAILABLE` y el servicio pasa a `unavailable` |
| «N entradas» en cada índice se confundía con un conteo de índices | «indexa N filas» |

## 3. Segunda parte: integración transaccional por HTTP

Primero se listó lo que faltaba (tabla de abajo) y luego se implementó todo.
El contrato de uso está en [demo.md, sección 8](demo.md) y las decisiones
estables en `PROJECT_CONTEXT.md` (sección API).

| # | Faltaba | Estado 2026-09-25 |
|---|---|---|
| 1 | Sesiones HTTP con token opaco sobre `SqlSession` | `api/sessions.py`: registro acotado (16), expiración por inactividad (5 min, barrido cada 15 s), cierre y cancelación |
| 2 | `BEGIN`/`END`/`ROLLBACK` por HTTP | Permitidos con sesión en ambos modos; sin sesión, `TRANSACTION_PROTOCOL` |
| 3 | EXPLAIN y EXPLAIN ANALYZE en solo lectura (el código contradecía a `PROJECT_CONTEXT.md`) | Permitidos y serializados como `explanation` |
| 4 | Despacho exhaustivo de resultados | `rows`, `command`, `explanation`, `transaction` y `definition` |
| 5 | Códigos de error transaccionales | `SESSION_BUSY`, `SESSION_NOT_FOUND`, `SESSION_LIMIT`, `TRANSACTION_PROTOCOL`, `TRANSACTION_ABORTED`, `TRANSACTION_CANCELLED` y `LOCK_TIMEOUT`, con la transacción que terminó (según la traza del motor) y si se perdió el grupo |
| 6 | Cancelación conectada a `SqlSession.cancel()` | `POST /api/session/cancel` y botón **Cancelar** |
| 7 | Apagado con `Database.shutdown(timeout)` | Al pedir la parada se cancelan primero las sentencias en curso y luego se hace `shutdown` acotado. Con `Ctrl+C` real y una petición esperando un lock: salida en 0,3 s, respuesta `TRANSACTION_CANCELLED`, sin artefactos de undo |
| 8 | Reemplazar el guard global | Las peticiones con sesión solo esperan en el lock manager; el guard quedó para las peticiones **sin sesión** en la sesión por defecto |
| 9 | Estado transaccional en la interfaz | Barra de sesión: número de sesión, transacción, locks, espera actual con sus bloqueadores, y los botones BEGIN/END/ROLLBACK/Cancelar/Nueva sesión |
| 10 | `completed_rows` tras un fallo de escritura | **Verificado:** el fallo se deshace por la transacción implícita. La respuesta ahora dice `rolled_back: true` y ya no suspende las escrituras; solo lo hace si el estado final no es `ABORTED` |

Decisiones que conviene conocer:

- **Semántica del motor, sin atajos.** La API ya no prepara antes de ejecutar:
  clasifica por el AST (sin efectos) y pasa el SQL a `SqlSession.execute`.
  Así, un error de ejecución dentro del grupo (clave duplicada, deadlock,
  timeout o incluso SQL mal formado) lo aborta completo, como establece
  `docs/transactions.md`. Una sentencia rechazada por política nunca llega al
  motor ni toca el grupo.
- **Un INSERT duplicado** ahora es `EXECUTION_REFUSED` con el mensaje del
  índice único (antes `SQL_ERROR`), porque se detecta al ejecutar.
- **`CREATE TABLE` en SQL** responde `STATEMENT_DISABLED` con la explicación,
  en lugar de un error de sintaxis.
- **Metadatos sin guard.** El catálogo se lee bajo el gate de metadatos del
  motor; los conteos son físicos y pueden incluir filas provisionales, y la
  interfaz lo indica.
- **Cerrar la pestaña** cierra su sesión (`DELETE` con `keepalive`), así que
  un grupo abandonado no retiene locks hasta la expiración.


## 4. Verificación

| Evidencia | Resultado |
|---|---|
| `tests/api` | **154 aprobadas** con advertencias como errores: las 97 previas (7 adaptadas a los cambios de contrato de la sección 3) y 57 nuevas, entre ellas 20 de sesiones HTTP concurrentes en `test_sessions.py` |
| Estabilidad de las pruebas concurrentes | `test_sessions.py` repetido 6 veces: 6/6 sin fallos. Se sincronizan consultando el estado real del lock manager, no con esperas a ciegas |
| Suite completa del repositorio | **2888 aprobadas en 314 s** con advertencias como errores (2831 del cierre de la Etapa 8 + 57 nuevas) |
| Frontend | `tsc --noEmit` limpio, **26 pruebas** de Vitest (11 nuevas) y build de producción correcto |
| Navegador real: tablas (Chromium headless, Playwright en un entorno aislado fuera del repo) | 19/19: importar con hash y B+, plan con los índices importados, error de CSV con línea y columna, tabla secuencial vacía con INSERT y orden por clave, recarga, cero excepciones de JavaScript |
| Navegador real: dos pestañas | 16/16: sesiones distintas, BEGIN e INSERT provisional en A, espera visible en B con su bloqueador, END libera a B, Cancelar, ROLLBACK, error que aborta el grupo, EXPLAIN ANALYZE, y cerrar la pestaña libera el lock |
| `Ctrl+C` real con una petición esperando un lock | El servidor sale en 0,3 s; la petición recibe `TRANSACTION_CANCELLED` (causa `shutdown`); el grupo abierto se aborta; no quedan artefactos de undo ni marcador `unclean`; la base se reabre con los datos confirmados |
| Reinicio sin `--allow-writes` | Las tablas creadas reaparecen con sus conteos; **Nueva tabla** queda deshabilitado |

### Límites conocidos

- No se simuló un corte de red real a mitad de una petición. La política está
  documentada: la sentencia termina y cierra su cursor, y un grupo explícito
  conserva sus locks hasta END, ROLLBACK, el cierre de la sesión o su
  expiración (5 min).
- El timeout de locks es el del motor (30 s, fijo en el coordinador). Las
  pruebas lo acortan tocando un atributo privado, solo en la prueba.
- Las garantías son las de la Etapa 8: atomicidad en proceso y reapertura
  limpia, no recuperación ante caídas.
- Los comandos del runbook se ensayaron en Linux (WSL2), no en Windows.
