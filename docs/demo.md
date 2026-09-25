# Demo de la Etapa 9 — runbook

Interfaz gráfica local sobre el motor SQL real del proyecto. Cumplió el hito
**«Stage 9 emergency demo ready»** de [ETAPA_09.md](../ETAPA_09.md) el
2026-09-18. Desde el 2026-09-25 integra además las transacciones de la Etapa 8
según el [handoff](ETAPA_08_STAGE_9_HANDOFF.md): cada pestaña del navegador
tiene su propia sesión del motor, `BEGIN TRANSACTION`/`END TRANSACTION`/
`ROLLBACK` agrupan peticiones separadas, y las sesiones se ejecutan en paralelo
con los locks reales del motor (sección 8).

## 1. Requisitos

- Python 3.11 o superior, con el entorno del repositorio.
- Node.js 20 o superior y npm, solo para compilar el frontend.

Instalación, una sola vez, desde la raíz del repositorio:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test,api]"
(cd frontend && npm ci)
```

En Windows, `.venv\Scripts\python.exe` sustituye a `.venv/bin/python`.

## 2. Preparar los datos (con el servidor detenido)

```bash
.venv/bin/python scripts/setup_demo.py
```

Crea `data/generated/demo`, que está excluido de git, en unos 16 s. Solo se
hace una vez: el servidor reabre esos archivos y **nunca** los vuelve a
sembrar, ni al recargar la página ni al consultar.

Para volver al estado inicial, siempre con el servidor detenido:

```bash
.venv/bin/python scripts/setup_demo.py --reset
```

El reset solo borra un directorio que tenga el marcador `.minidbms-demo` que
crea el propio script. Jamás toca otro directorio de datos.

## 3. Compilar el frontend

```bash
(cd frontend && npm run build)
```

Genera `frontend/dist`, que el servidor sirve en `/`.

## 4. Arrancar

```bash
.venv/bin/python -m api
```

Abre <http://127.0.0.1:8000>. El servidor arranca **un proceso, un worker y
sin auto-reload**: un único proceso debe ser el dueño del directorio de datos.
Se detiene con `Ctrl+C`. La salida esperada es:

```text
Base de demo abierta en 0.1 s · modo read-only
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Opciones: `--port`, `--data-dir`, `--frontend-dir` y `--allow-writes`
(sección 8). `--allow-writes` también habilita el botón **Nueva tabla** del
panel Archivos (sección 7.1). Si el puerto ya está ocupado (por ejemplo, otro servidor de la
demo sigue abierto), el lanzador se detiene antes de abrir ningún archivo de
datos.

Para la demo basta este único proceso: sirve la API y el frontend compilado
en `frontend/dist`. Después de cambiar el frontend hay que repetir
`npm run build` para que el 8000 muestre los cambios.

### Modo desarrollo del frontend

Opcional: solo sirve para editar el frontend con recarga en caliente, no para
presentar. No reemplaza al 8000: Vite sirve la interfaz desde el código fuente
y reenvía las consultas al servidor de la API. Con el servidor ya levantado,
en otra terminal:

```bash
(cd frontend && npm run dev)
```

Abre <http://127.0.0.1:5173>. Vite reenvía `/api` al puerto 8000, así que el
navegador siempre habla con un único origen.

## 5. Guion de la presentación

| Paso | Acción | Qué se ve |
|---|---|---|
| 1 | Panel **Archivos**: elegir `students` y luego `courses` | Esquema real del catálogo, organización (Heap / Paged Sequential) e índices |
| 2 | Preset **Filtro y ORDER BY** → Ejecutar | Ana, Omar, Sol; plan con `IndexScan` sobre `students_age_bplus` y `ExternalSort` |
| 3 | Preset **Igualdad por clave** | `(3, Sol, CS, 24)`; el planner elige el índice hash `students_id_hash` |
| 4 | Preset **Rango** | Ana y Omar; B+ `students_age_bplus` |
| 5 | Preset **GROUP BY** | (CS, 2), (EE, 2); `ExternalHashGroup` |
| 6 | Preset **JOIN** | Ana/DB2, Ana/OS, Omar/OS, Sol/DB2; `GraceHashJoin` |
| 7 | Preset **Error semántico**, luego repetir el paso 2 | Error útil junto al editor y recuperación sin reiniciar |
| 8 | Preset **JOIN + GROUP BY con disco** | `GraceHashJoin` → `ExternalHashGroup` → `ExternalSort`, con ~362 KiB volcados a disco |
| 9 | Desmarcar **Usar índices** y repetir el paso 3 | El plan real pasa a `TableScan`; el resultado no cambia |
| 10 | Con `--allow-writes`, abrir una **segunda pestaña** (B). En A: **BEGIN**, luego `INSERT INTO enrollments VALUES (9, 'X');` | A muestra «Transacción T1 activa · locks: enrollments» y el INSERT como **provisional** |
| 11 | En B: `SELECT COUNT(*) AS n FROM enrollments;` | B queda esperando: «Esperando lock S sobre enrollments, retenido por T1» |
| 12 | En A: **END** | A: «END TRANSACTION: transacción T1 confirmada» con el undo copiado; B recibe 5 al instante |
| 13 | Repetir 10–11 y pulsar **Cancelar** en B, luego **ROLLBACK** en A | B: «Transacción cancelada»; A: grupo abortado; el conteo vuelve a su valor |
| 14 | Explicar lo pendiente | Experimentos 1K/10K/100K (Etapa 10) |

El fixture de cuatro filas prueba **corrección**, no volcado a disco. El
trabajo externo real se demuestra con las tablas `*_big` (pasos 8 y 9).

Texto sugerido:

> Esta interfaz ejecuta SQL con nuestro propio almacenamiento, índices y
> operadores. Cada pestaña es una sesión del motor: sus transacciones usan
> locks S/X de tabla con 2PL riguroso, detección de deadlocks y rollback por
> imágenes previas. Lo que se ve en la barra de sesión sale del lock manager
> real, no de la interfaz.

## 6. Presets verificados

Medidos sobre `data/generated/demo` con `max_rows=500`. Cada uno tiene su
prueba en `tests/api/test_presets.py`.

| Preset | Resultado | Operadores ejecutados (padre ← hijos) | Índice abierto | Volcado |
|---|---|---|---|---:|
| Filtro y ORDER BY | 3 filas | Projection ← ExternalSort ← Filter ← IndexScan | students_age_bplus | 100 B |
| Igualdad por clave | 1 fila | Projection ← Filter ← IndexScan | students_id_hash | 0 B |
| Rango | 2 filas | Projection ← Filter ← IndexScan | students_age_bplus | 0 B |
| GROUP BY | 2 filas | Projection ← ExternalSort ← ExternalHashGroup ← TableScan | — | 170 B |
| JOIN | 4 filas | Projection ← ExternalSort ← Filter ← GraceHashJoin ← IndexScan, TableScan | students_age_bplus | 365 B |
| Sin coincidencias | 0 filas | Projection ← Filter ← IndexScan | students_age_bplus | 0 B |
| Error semántico | `SQL_ERROR` (422) | — | — | — |
| Error de sintaxis | `SQL_ERROR` (422), línea 1 columna 1 | — | — | — |
| ORDER BY con disco | 3000 filas, vista previa truncada | Projection ← ExternalSort ← TableScan | — | 211 588 B |
| JOIN + GROUP BY con disco | 8 filas | Projection ← ExternalSort ← ExternalHashGroup ← GraceHashJoin ← TableScan, TableScan | — | 370 251 B |
| Rango en tabla mayor | 99 filas | Projection ← ExternalSort ← Filter ← IndexScan | students_big_age_bplus | 4 228 B |

El índice que usa cada consulta lo decide el planner, no una etiqueta. Si el
planner cambia, el panel de Plan mostrará la ruta nueva, no la de esta tabla.

## 7. Contrato HTTP

| Ruta | Uso | ¿Admisión al motor? |
|---|---|---|
| `GET /api/health` | Estado en caché, modo y límites | No |
| `GET /api/presets` | Presets (etiqueta, propósito, SQL) | No |
| `GET /api/tables` | Resumen de tablas del catálogo | Sí |
| `GET /api/tables/{id}` | Columnas, tipos, organización e índices | Sí |
| `POST /api/sessions` | Abre una sesión del motor y devuelve su token opaco | — |
| `GET /api/session` | Estado de la sesión del header: transacción, locks, espera actual | No |
| `POST /api/session/cancel` | Cancela la sentencia en curso de esa sesión | No |
| `DELETE /api/session` | Cierra la sesión: aborta su grupo abierto y libera sus locks | — |
| `POST /api/query` | Ejecuta una sentencia con vista previa acotada | Solo sin sesión |
| `POST /api/import/preview` | Lee un CSV e infiere tipos; no carga nada | No |
| `POST /api/tables` | Crea una tabla y, opcionalmente, carga un CSV (`--allow-writes`) | Sí |

Petición de `POST /api/query`:

```json
{"sql": "SELECT name FROM students WHERE age > 20 ORDER BY name;",
 "max_rows": 100, "use_indexes": true, "join_strategy": "AUTO"}
```

`use_indexes` y `join_strategy` (`AUTO`, `GRACE_HASH`, `NESTED_LOOP`) se pasan
tal cual al planner y cambian lo que se ejecuta de verdad.

Con el header `X-Session-Token: <token>` la sentencia corre en esa sesión;
sin él, en la sesión por defecto (sección 8). Toda respuesta con sesión trae
`session` con su estado final. El campo `kind` distingue cinco resultados:

| `kind` | Sentencias | Campos propios |
|---|---|---|
| `rows` | SELECT | `columns`, `rows`, vista previa y métricas |
| `command` | INSERT, DELETE | `affected_rows` y `transaction {id, committed, provisional}` |
| `explanation` | EXPLAIN, EXPLAIN ANALYZE | `explanation` (ejecutado o no, filas producidas y descartadas, tiempos) y el plan |
| `transaction` | BEGIN/END TRANSACTION, ROLLBACK | `transaction_report`: estado, tablas, espera, bloqueadores, bytes de undo, causa |
| `definition` | CREATE en SQL | Solo por exhaustividad: aquí CREATE en SQL está deshabilitado |

### Límites

| Límite | Valor |
|---|---:|
| Filas por defecto | 100 |
| Máximo de filas por respuesta | 500 |
| Texto SQL | 32 KiB en UTF-8 |
| Cuerpo HTTP | 64 KiB (17 MiB en las dos rutas de importación) |
| CSV importado | 8 MiB y 10 000 filas de datos |
| Respuesta codificada | 1 MiB |
| Nodos / profundidad del plan | 128 / 32 |
| Memoria de trabajo por consulta | 192 KiB |
| Sesiones abiertas | 16 |
| Expiración de una sesión sin uso | 5 min (aborta su grupo abierto) |
| Espera máxima por un lock | 30 s (timeout del motor) |
| Espera acotada al cerrar una sesión o el servidor | 5 s |

### Semántica de la vista previa

Se consumen como máximo `max_rows + 1` filas. La fila extra solo demuestra que
hay más resultados:

- **Completo** (`result_complete: true`): el motor llegó al final;
  `total_rows` es exacto.
- **Truncado por filas** (`row_limit`): `total_rows: null` y las métricas se
  marcan como parciales.
- **Truncado por bytes** (`byte_limit`): se devuelve el prefijo que cabe y
  ningún valor se recorta. Si no cabe ni una sola fila, la respuesta es el
  error `RESULT_TOO_LARGE`.

Codificación sin pérdida: los enteros fuera de ±(2⁵³−1) viajan como texto y
los flotantes no finitos como `"Infinity"`/`"-Infinity"`/`"NaN"`. Cada columna
declara su codificación. El motor no tiene `NULL`.

### Errores

Todos comparten el sobre `{"error": {code, message, request_id, location?}}`.
La traza completa queda solo en el log del servidor, que se cruza con el
`request_id`.

| Código | HTTP | Cuándo |
|---|---:|---|
| `INVALID_REQUEST` | 422 | Campos de la petición inválidos |
| `SQL_ERROR` | 422 | Error léxico, sintáctico o semántico, con línea y columna |
| `EXECUTION_REFUSED` | 422 | El motor rechaza ejecutar la sentencia |
| `RESULT_TOO_LARGE` | 422 | La respuesta no cabe en 1 MiB |
| `STATEMENT_DISABLED` | 403 | Sentencia no permitida en el modo actual |
| `WRITES_DISABLED` | 403 | Crear tablas requiere `--allow-writes` |
| `DEFINITION_ERROR` | 422 | Nombre, tipo, organización o índice inválidos |
| `CSV_ERROR` | 422 | CSV mal formado o valor que no encaja en su tipo (`details`: línea y columna) |
| `TABLE_EXISTS` | 409 | Ya existe una tabla con ese nombre |
| `SESSION_NOT_FOUND` | 404 | Token inexistente, expirado o cerrado; nunca se crea otra sesión sola |
| `SESSION_BUSY` | 409 | Esa sesión ya está ejecutando otra petición; nada se reintenta |
| `SESSION_LIMIT` | 429 | Se alcanzó el máximo de sesiones abiertas |
| `TRANSACTION_PROTOCOL` | 409 | END/ROLLBACK sin grupo, BEGIN anidado, control sin sesión; el estado no cambia |
| `TRANSACTION_ABORTED` | 409 | Deadlock (víctima) u otro aborto: el grupo completo se deshizo |
| `TRANSACTION_CANCELLED` | 409 | Cancelada por el cliente o por el cierre del servidor |
| `LOCK_TIMEOUT` | 409 | La espera de un lock superó 30 s: el grupo se abortó |

Tras un error de ejecución, `details.transaction` dice qué transacción terminó
y en qué estado, y `details.group_aborted` si se perdió un grupo explícito.
| `NOT_FOUND` | 404 | Tabla inexistente en el catálogo |
| `ENGINE_BUSY` | 409 | Hay otra operación del motor en curso |
| `REQUEST_TOO_LARGE` | 413 | SQL o cuerpo demasiado grandes |
| `ENGINE_UNAVAILABLE` | 503 | El motor quedó inutilizable: reiniciar |
| `INTERNAL_ERROR` | 500 | Fallo inesperado |

### 7.1 Crear e importar tablas desde el panel Archivos

Con `--allow-writes`, **Nueva tabla** abre un diálogo con dos pestañas:

- **Importar CSV.** El navegador lee el archivo y el servidor devuelve la
  cabecera, los tipos inferidos y las primeras filas, sin cargar nada. La
  primera fila es la cabecera; el separador (coma, punto y coma, tabulador o
  barra) se detecta solo. Una columna es INTEGER si todos sus valores son
  enteros de 64 bits, FLOAT si son decimales finitos, BOOLEAN si son
  `true`/`false` y VARCHAR en otro caso. El motor no tiene NULL: una celda
  vacía solo cabe en VARCHAR. Los nombres se sanean a identificadores SQL
  válidos (`Nota Final` → `nota_final`) y se pueden editar, igual que los tipos.
- **Definir columnas.** Una tabla vacía con las columnas que se escriban.

En ambos casos se elige la organización y los índices, con las mismas reglas
del motor:

| Organización | Índices permitidos |
|---|---|
| Heap File | B+ unclustered e Hash extensible, sobre cualquier columna, únicos o no |
| Paged Sequential File | Solo el B+ clustered sobre la clave |

Los índices se nombran `<tabla>_<columna>_bplus` o `<tabla>_<columna>_hash`.
Las filas se insertan con la propia organización elegida y cada índice se
construye después desde ese archivo, como los fixtures de la demo. La creación
corre bajo el lock de esquema de la sesión por defecto (Etapa 8) y la admisión
del servidor: mientras carga, las demás peticiones reciben `ENGINE_BUSY`.

**Persistencia.** Los archivos usan identidades opacas
(`g_<uuid>.heap/.seq/.bpt/.hsh`), nunca el nombre lógico. La definición se
publica al final en `gui_tables.json`, que se reescribe de forma atómica. Si
algo falla antes, se deshace el registro en memoria y se borran los archivos
creados; una caída del proceso a mitad de carga deja archivos huérfanos que
nunca se abren. Al arrancar, el servidor reabre primero los fixtures y luego
las tablas de `gui_tables.json`. `setup_demo.py --reset` las elimina junto con
el resto del directorio.

**Coste medido en esta máquina (WSL2):** unos 3 ms por fila insertada y otros
3–4 ms por fila por cada índice. Cargar 10 000 filas con un índice tarda
alrededor de un minuto. Además, reabrir un índice hash verifica su cobertura
fila por fila (~2,6 ms por fila), así que un hash sobre una tabla grande
alarga el arranque del servidor.

`CREATE TABLE` escrito en el editor SQL sigue rechazado: esa sentencia
requiere el owner manifest-backed (ver sección 9).

## 8. Sesiones, transacciones y concurrencia

**Una sesión por pestaña.** Al cargar la página, el frontend abre una sesión
(`POST /api/sessions`) y envía su token en cada sentencia. El token es un
secreto aleatorio: no se deriva del número de sesión del motor, que solo se
muestra. El registro admite 16 sesiones; una sesión sin uso durante 5 minutos
expira, lo que aborta su grupo abierto y libera sus locks. Cerrar la pestaña
cierra la sesión al momento (`DELETE` con `keepalive`), y recargar la página
abre otra nueva.

**Transacciones entre peticiones.** `BEGIN TRANSACTION`, las sentencias
siguientes y `END TRANSACTION` pueden llegar en peticiones separadas: forman
un solo grupo de la sesión. Dentro del grupo, el recuento de un INSERT/DELETE
es **provisional** hasta que END confirma. `ROLLBACK` restaura todos los
archivos tocados (base e índices) desde sus imágenes previas. Fuera de un
grupo, cada sentencia es una transacción implícita que se confirma o aborta
sola. Se aplica el contrato del motor (`docs/transactions.md`):

- un error de ejecución dentro del grupo lo aborta completo, incluidos un
  constraint, un lock timeout, un deadlock o SQL mal formado; la respuesta lo
  dice (`details.group_aborted`);
- los errores de protocolo (END sin grupo, BEGIN anidado) no cambian nada;
- una sentencia rechazada por la política del servidor **nunca** llega al
  motor, así que tampoco toca el grupo.

**Concurrencia real.** Las peticiones con sesión no pasan por ningún mutex
global: esperan en el lock manager de la Etapa 8 (S/X de tabla, 2PL riguroso,
FIFO, detección de ciclos, timeout de 30 s). Una petición bloqueada nunca
impide que su bloqueador envíe END o ROLLBACK desde otra pestaña. Mientras
espera, `GET /api/session` informa el lock que espera y qué transacciones lo
retienen, y la interfaz lo muestra en la barra de sesión. **Cancelar** pide la
cancelación cooperativa (`SqlSession.cancel()`): la sentencia termina en el
siguiente punto seguro con `TRANSACTION_CANCELLED` y aborta el grupo.

**Sin sesión** (por ejemplo, con `curl`) la sentencia corre en la sesión por
defecto como transacción implícita, de a una: otra petición sin sesión recibe
`ENGINE_BUSY`. `BEGIN`/`END`/`ROLLBACK` sin sesión se rechazan con
`TRANSACTION_PROTOCOL`, porque un grupo en la sesión compartida mezclaría
clientes distintos. Las rutas del catálogo leen bajo el gate de metadatos del
motor y no esperan a nadie; sus conteos son físicos y pueden incluir cambios
provisionales de un grupo abierto.

**Política de sentencias.** Se decide por el AST del parser manual, nunca por
texto. Solo lectura admite SELECT, EXPLAIN y EXPLAIN ANALYZE; `--allow-writes`
añade INSERT, DELETE y la creación de tablas desde el panel Archivos. El
control de transacciones se admite en ambos modos, pero solo con sesión.
`CREATE TABLE` escrito en SQL sigue deshabilitado (requiere el owner
manifest-backed). Cada envío se ejecuta **una sola vez**: nada se reintenta ni
se deduplica.

**Desconexiones y cierre.** Si la red se corta a mitad de una petición, la
sentencia termina en el servidor y cierra su cursor; un grupo explícito
conserva sus locks hasta END, ROLLBACK, el cierre de la sesión o su
expiración. Con `Ctrl+C`, el servidor rechaza trabajo nuevo, cancela al
instante las sentencias en curso (que responden `TRANSACTION_CANCELLED`),
aborta los grupos abiertos con `Database.shutdown` acotado y recién entonces
cierra los archivos. Si algo no termina a tiempo, no cierra archivos bajo
trabajo en curso y lo informa.

Estas garantías son las de la Etapa 8: atomicidad en proceso y reapertura
limpia, **no** recuperación ante caídas (no hay WAL). Ningún otro proceso debe
abrir el directorio de datos mientras corre el servidor.

## 9. Pendiente

- La Etapa 10 (experimentos 1K/10K/100K y entrega final) sigue aparte. La
  importación CSV de la interfaz sirve para inspeccionar datos, pero no
  reemplaza a los benchmarks, que deben correr fuera del servidor.
- `CREATE TABLE` escrito en SQL requiere migrar la demo al owner
  manifest-backed, que hoy solo admite Heap y B+ de clave primaria.
- El cierre formal de la Etapa 9 queda a decisión del equipo; la evidencia
  está en [ETAPA_09_REVISION_2026_09_25.md](ETAPA_09_REVISION_2026_09_25.md).

## 10. Verificación rápida

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider tests/api
(cd frontend && npx tsc --noEmit && npx vitest run && npm run build)
```
