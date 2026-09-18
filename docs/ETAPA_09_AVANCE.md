# Etapa 9 — avance: demo de emergencia lista

Fecha: **2026-09-18**. Alcance: tareas **9.1–9.18** de
[ETAPA_09.md](../ETAPA_09.md). Estado: **«Stage 9 emergency demo ready»**.

Esto **no** es el cierre de la Etapa 9 ni de la Parte 1. Por la excepción de
orden autorizada (sección 1 de la guía), la Etapa 8 se implementa después, y
la integración transaccional de la API queda pendiente hasta entonces. La
forma de lanzar y usar la demo está en [demo.md](demo.md).

## 9.1 — Inspección y línea base

La Etapa 7 estaba **formalmente cerrada** (63 criterios, 2556 pruebas). Línea
base previa a cualquier cambio: `tests/query` más arquitectura, **280 pruebas
aprobadas en 36 s** con advertencias como errores.

| Responsabilidad del adaptador | API real de la Etapa 7 |
|---|---|
| Parsear, clasificar y planificar sin ejecutar | `SqlEngine.prepare(sql, use_indexes=, planning_options=)` → `PreparedQuery.kind` |
| Ejecutar una sola vez | `PreparedQuery.execute()` → `QueryResult` (`SELECT`) o `CommandResult` (`INSERT`/`DELETE`) |
| Vista previa acotada y cierre del cursor | `QueryResult.fetchmany(n)` + context manager; queda `CLOSED` si se cierra antes del final |
| Plan preparado y plan medido | `PreparedQuery.describe()` y `result.report.runtime` (`PlanReport`) |
| Alcance de las métricas | Locales a cada ejecución; no hay contadores globales que reiniciar |
| Fallos de escritura | `MaintenanceError` con `completed_rows` e `unavailable_indexes` |
| Sesión | Un resultado activo a la vez (`SqlEngine.active_result`) |

El parser manual ya rechaza `BEGIN/END TRANSACTION`, `COMMIT`, `ROLLBACK`,
DDL, `UPDATE` y los envíos con varias sentencias, así que la API no necesita
lógica SQL propia para eso. No existía código previo de API ni de frontend
que reutilizar más allá del stack acordado (FastAPI y React/TypeScript/Vite).

## Decisiones congeladas (9.2)

El contrato completo está en `api/schemas.py` y en la sección 7 de
[demo.md](demo.md). Estas son las decisiones que conviene revisar en equipo:

| Decisión | Motivo |
|---|---|
| Rutas `/api/health`, `/api/presets`, `/api/tables`, `/api/tables/{id}`, `/api/query` | Las cuatro de la guía más una de presets, que no toca el motor |
| Opciones `use_indexes` y `join_strategy` en la petición | Son controles reales del planner que cambian lo que se ejecuta; la guía solo prohíbe interruptores que cambien una etiqueta |
| Dos fixtures en una base | El de aceptación de la Etapa 7 (respuestas conocidas) y uno mayor (volcados reales a disco) |
| Sin índices hash en las tablas mayores | Reabrir un índice hash verifica su cobertura fila por fila: con ellos la reapertura tardaba unos 11 s; sin ellos, 0,1 s |
| Presupuesto de 192 KiB por consulta | 128 KiB no alcanzaba para tres operadores bloqueantes anidados; con 192 KiB caben y se sigue escribiendo a disco |
| Plan en árbol anidado, sin numerar pasos | La guía advierte que una secuencia numerada induce a error en joins con ramas |

## Defectos encontrados y corregidos durante la implementación

1. **Tope de bytes con una reserva adivinada.** Se restaban 32 KiB fijos para
   los metadatos. Con un tope pequeño el presupuesto quedaba negativo y se
   declaraba que «no cabe ni una fila» cuando la respuesta real sí cabía. Ahora
   la cota incremental solo sirve para dejar de leer filas pronto, y la
   decisión exacta se toma sobre la respuesta real ya codificada.
2. **Faltaba la cabecera `X-Request-ID` en los 500.** Starlette resuelve las
   excepciones no controladas en su middleware externo, antes que el propio.
   Ahora se capturan en el middleware de la API y el sobre del 500 es idéntico
   a los demás.
3. **Mensajes de error entre comillas.** Los errores del motor derivados de
   `KeyError` (columna o tabla desconocida) llegaban como `"Unknown column…"`.
4. **Nombres accesibles ambiguos.** Envolver cada `<select>` en su `<label>`
   hacía que el nombre del control incluyera el texto de sus opciones: «Join»
   coincidía también con el desplegable de presets. Se añadieron `aria-label`
   explícitos.
5. **Plurales** («1 páginas», «1 índices») en el panel de Archivos.

Los defectos 1 y 2 los detectó la suite de la API; el 3, el 4 y el 5, la
prueba en navegador real y sus capturas.

Hallazgo sobre la Etapa 5, sin modificarla: reabrir un
`UnclusteredHashIndex` cuesta unos 2,6 ms por fila, porque la comprobación de
cobertura hace una búsqueda puntual por cada fila del Heap y deserializa el
bucket completo en cada una. No afecta a la corrección, pero conviene que lo
revise quien lleva la Etapa 5.

## Verificación (9.14 y 9.15)

| Evidencia | Resultado |
|---|---|
| Suite de la API (`tests/api`) | 93 pruebas: cargador, script de preparación, serialización, servicio, HTTP y presets |
| Admisión concurrente | Sincronización con `threading.Event`, sin `sleep`: la segunda operación nunca llega a `SqlEngine.prepare` |
| Frontend | `tsc --noEmit` limpio, 15 pruebas de Vitest y build de producción |
| Suite completa del repositorio | **2649 pruebas aprobadas** con advertencias como errores: las 2556 del cierre de la Etapa 7 más las 93 de la API |
| Navegador real | Chromium headless (Playwright) ejecutó el guion completo: 32 comprobaciones, **todas correctas**, cero excepciones de JavaScript |
| Reinicio desde disco | Parada con `Ctrl+C`, arranque de nuevo (0,1 s) y el mismo guion otra vez: todo correcto |
| Solo lectura | SHA-256 de los 10 archivos de datos antes y después de dos sesiones completas: **idénticos** |
| Comandos del runbook | `pip install -e ".[test,api]"`, `setup_demo.py`, `npm ci`, `npm run build` y `python -m api` ejecutados tal como están escritos |

Playwright se instaló en un entorno aislado fuera del repositorio. No es una
dependencia del proyecto.

## Checklist «Emergency Stage 9 demo ready»

| Criterio | Estado |
|---|---|
| Se inspeccionaron los puntos de entrada de la Etapa 7 y su línea base | Cumple |
| Se registró la excepción de orden; la Etapa 8 sigue pendiente | Cumple |
| Se reutiliza el parser manual, sin un segundo parser | Cumple |
| Datos de demo persistentes, deterministas y separados de los datos normales | Cumple |
| Un proceso dueño de los datos y un único guard de admisión | Cumple |
| Las peticiones que compiten se rechazan; excepciones y desconexiones no liberan la admisión antes de tiempo | Cumple, con la salvedad 1 |
| Escrituras y comandos de transacción rechazados por defecto antes de ejecutar | Cumple |
| Cada petición aceptada llega al motor real una sola vez | Cumple |
| Topes de filas y bytes con estado completo/parcial y totales veraces | Cumple |
| Cursores y temporales cerrados antes de liberar la admisión | Cumple |
| Los cuatro paneles funcionan | Cumple |
| Planes e índices salen de descriptores reales del motor | Cumple |
| Estados vacío, error, ocupado, truncado y servidor caído son claros | Cumple |
| Valores y esquemas conservan orden, tipos y duplicados (`NULL` no existe en el motor) | Cumple |
| Pruebas de API y motor y build del frontend pasan, con el alcance registrado | Cumple |
| La demo funciona en navegador tras un arranque y una reapertura limpios | Cumple |
| Un compañero puede seguir el runbook | Cumple, con la salvedad 2 |
| Límites conocidos y seguimiento de las Etapas 8 y 10 documentados | Cumple |

### Opcionales

- **9.16, escrituras:** implementadas tras `--allow-writes` (apagado por
  defecto). Probado: se ejecutan una sola vez con su recuento, se leen de
  vuelta, coinciden por índice y por scan, persisten tras reabrir, no se
  deduplican, y se suspenden si los índices quedan en estado incierto.
  **No** se ensayaron en navegador.
- **9.17, pulido:** accesibilidad (`aria-label`), concordancia de plurales y
  estados visuales. Sin dependencias nuevas.

### Salvedades

1. **Desconexión del navegador.** Los endpoints son síncronos: FastAPI los
   ejecuta en un hilo que no se cancela cuando el cliente se desconecta, así
   que la operación termina y libera la admisión en su propio `finally`. Lo
   cubren pruebas de fallo durante la conversión, pero no se simuló un corte
   de red real.
2. **Runbook en Windows.** Los comandos se ensayaron en Linux (WSL2). En
   Windows cambia la ruta del intérprete, como indica el runbook, pero no se
   ejecutaron allí.

## Validación final

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
2649 passed in 254.49s

(cd frontend && npx tsc --noEmit && npx vitest run && npm run build)
tsc sin errores · 15 passed · build de producción correcto
```

Entorno: Linux (WSL2), Python 3.11.9, pytest 8.4.2, FastAPI 0.141.1,
Starlette 1.6.0, anyio 4.14.2 (fijada por debajo de 4.15, ver
`pyproject.toml`), Node 20.19.1, React 18.3 y Vite 6. Las auditorías de etapas
anteriores se ejecutaron en Windows.
