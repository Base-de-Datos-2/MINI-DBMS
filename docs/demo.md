# Demo de la Etapa 9 — runbook

Interfaz gráfica local sobre el motor SQL real del proyecto. Cumple el hito
**«Stage 9 emergency demo ready»** de [ETAPA_09.md](../ETAPA_09.md). La
**Etapa 8 (transacciones y concurrencia) cerró el 2026-09-24**, pero esta demo
HTTP todavía no expone sesiones transaccionales entre peticiones ni promete
concurrencia HTTP; conserva su guard global hasta completar el
[handoff](ETAPA_08_STAGE_9_HANDOFF.md).

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
(sección 8). Si el puerto ya está ocupado (por ejemplo, otro servidor de la
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
| 10 | Explicar lo pendiente | Transacciones, concurrencia y experimentos (Etapas 8 y 10) |

El fixture de cuatro filas prueba **corrección**, no volcado a disco. El
trabajo externo real se demuestra con las tablas `*_big` (pasos 8 y 9).

Texto sugerido:

> Esta interfaz ejecuta SQL con nuestro propio almacenamiento, índices y
> operadores. El modo actual admite una operación del motor a la vez. La
> agrupación transaccional y el control de concurrencia son el siguiente hito;
> la interfaz no afirma esas garantías.

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
| `POST /api/query` | Ejecuta una sentencia con vista previa acotada | Sí |

Petición de `POST /api/query`:

```json
{"sql": "SELECT name FROM students WHERE age > 20 ORDER BY name;",
 "max_rows": 100, "use_indexes": true, "join_strategy": "AUTO"}
```

`use_indexes` y `join_strategy` (`AUTO`, `GRACE_HASH`, `NESTED_LOOP`) se pasan
tal cual al planner y cambian lo que se ejecuta de verdad.

### Límites

| Límite | Valor |
|---|---:|
| Filas por defecto | 100 |
| Máximo de filas por respuesta | 500 |
| Texto SQL | 32 KiB en UTF-8 |
| Cuerpo HTTP | 64 KiB |
| Respuesta codificada | 1 MiB |
| Nodos / profundidad del plan | 128 / 32 |
| Memoria de trabajo por consulta | 192 KiB |

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
| `NOT_FOUND` | 404 | Tabla inexistente en el catálogo |
| `ENGINE_BUSY` | 409 | Hay otra operación del motor en curso |
| `REQUEST_TOO_LARGE` | 413 | SQL o cuerpo demasiado grandes |
| `ENGINE_UNAVAILABLE` | 503 | El motor quedó inutilizable: reiniciar |
| `INTERNAL_ERROR` | 500 | Fallo inesperado |

## 8. Política temporal del adaptador (vigente después de la Etapa 8)

- **Una operación del motor a la vez.** Una segunda petición recibe
  `ENGINE_BUSY` al instante; no hay cola. La admisión cubre preparar,
  clasificar, ejecutar, convertir la vista previa, copiar métricas y cerrar el
  cursor, y la toma y la libera el mismo hilo que hace el trabajo síncrono.
- **Solo `SELECT` por defecto.** Se decide con el tipo de sentencia que
  devuelve `SqlEngine.prepare()`, nunca por texto. El motor ya
  implementa `EXPLAIN`, `EXPLAIN ANALYZE` y CREATE manifest-backed, pero este
  adaptador conserva deliberadamente su allowlist y su base legacy: todavía no
  serializa explicaciones ni expone DDL. `BEGIN/END TRANSACTION` y `ROLLBACK`
  existen en el motor, pero la allowlist HTTP los rechaza; `COMMIT`, `UPDATE`,
  el DDL restante y los envíos con varias sentencias siguen fuera de sus
  límites correspondientes.
- **`--allow-writes` (opcional, tarea 9.16).** Habilita `INSERT` y `DELETE`
  sobre la base de demo desechable. Cada envío se ejecuta **una sola vez**, sin
  reintentos ni deduplicación. Cada comando usa una transacción implícita de
  una sentencia con rollback ordinario de la Etapa 8; no hay agrupación entre
  peticiones ni recuperación ante caída. Si el owner queda en cuarentena o el
  motor informa índices en estado incierto, las escrituras se suspenden y el
  modo vuelve a solo lectura.
- Si al limpiar queda una sesión activa en el motor, el servicio pasa a 503
  hasta que se reinicie.

**El guard es control de admisión del servidor, no el mecanismo de la Etapa
8.** El motor subyacente sí tiene sesiones, rollback y locks, pero el adaptador
todavía no expone agrupación entre peticiones ni concurrencia HTTP. Ningún otro
proceso debe abrir el directorio de datos mientras corre el servidor: el guard
es local al proceso.

## 9. Pendiente después del cierre de la Etapa 8

- Migrar la demo al owner manifest-backed y añadir dispatch exhaustivo para
  `DEFINITION` y `EXPLANATION` antes de habilitar CREATE/EXPLAIN por HTTP.
- Conectar tokens de sesión estables y transacciones (`BEGIN/END TRANSACTION`)
  a la API y reflejar identidad, estado, espera y resultado en la interfaz.
- Alinear la vida del cursor, los fallos y las desconexiones con la semántica
  transaccional implementada.
- Probar peticiones simultáneas bajo el mecanismo real de concurrencia. La
  demostración obligatoria del motor con hilos ya existe en
  `demos/transactions_demo.py` y está auditada por la Etapa 8.
- Mantener el guard de admisión hasta que la protección real esté verificada a
  través de HTTP.
- Serializar explícitamente resultados de filas, comandos, definiciones,
  explicaciones y controles, e integrar cancelación con `SqlSession.cancel()`.
- La Etapa 10 (experimentos 1K/10K/100K y entrega final) sigue aparte.

## 10. Verificación rápida

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider tests/api
(cd frontend && npx tsc --noEmit && npx vitest run && npm run build)
```
