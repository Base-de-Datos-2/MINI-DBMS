# Etapa 10 — verificación de integración (Tarea 10.12)

**Fecha:** 2026-10-04 · **Rama:** `feat/close-etapa-10`, sobre `main` en
`adaf3d3` (incluye la Parte 2 E1/E2) · **Máquina:** Linux (WSL2), Python 3.11.9,
Node 20.

La verificación recorre la ruta completa de la Parte 1: frontend → API →
`SqlEngine` → operadores → índices y almacenamiento → páginas → disco, y un
reinicio limpio.

## 1. Servidor real por HTTP — `scripts/integration_check.py`

El script prepara una base de demo nueva en su propio directorio
(`data/generated/integration-check`), levanta `python -m api --allow-writes`
como proceso aparte (igual que en un despliegue) y lo maneja solo por HTTP.

```bash
(cd frontend && npm run build)
python scripts/integration_check.py
```

Resultado: **22 de 25 comprobaciones aprobadas.** Las 3 que fallan son dos
detalles del lanzador, descritos en la sección 4; ninguna afecta a datos ni a
resultados.

| Área | Comprobación | Resultado |
|---|---|---|
| Arranque | El servidor abre una base nueva y responde `ready` con escrituras habilitadas | OK (0,6 s) |
| Frontend | `/` sirve el frontend compilado y su JavaScript | OK |
| Catálogo | `/api/tables` lista las tablas de la demo | OK |
| Planes reales | `WHERE id = 3` usa `IndexScan` sobre `students_id_hash`; con índices deshabilitados usa `TableScan` y da la misma respuesta | OK |
| Operadores externos | JOIN + GROUP BY + ORDER BY ejecuta `GraceHashJoin`, `ExternalHashGroup` y `ExternalSort` | OK |
| Errores | Un error de sintaxis y uno semántico se reportan, y la consulta siguiente funciona sin reiniciar | OK |
| Carga de tablas | Importación de 500 filas CSV como tabla Heap (B+ único en `id` y Hash en `career`) y como tabla Secuencial (B+ agrupado en `id`) | OK |
| Índices de tablas nuevas | Igualdad por B+ en ambas, igualdad por Hash y rango ordenado en la secuencial | OK |
| Concurrencia | La sesión B espera el lock que retiene la sesión A durante su transacción y recibe el conteo confirmado tras `END TRANSACTION` | OK (espera de 1,5 s) |
| Transacciones | `ROLLBACK` descarta la inserción provisional | OK |
| Apagado | Ctrl+C completa el apagado ordenado de uvicorn y cierra la base | OK; termina con código -2 y traceback (sección 4) |
| Reinicio | El puerto queda libre para el lanzador recién ~60 s después del apagado | Falla (sección 4) |
| Reinicio | Reabre los mismos archivos; las tablas creadas conservan filas e índices | OK (1,0 s) |
| Durabilidad | Solo la inserción confirmada persiste; la revertida no | OK |
| Después del reinicio | Las búsquedas indexadas siguen usando su índice | OK |

## 2. Navegador real

Chromium sin interfaz (Playwright 1.63) sobre el mismo servidor, con dos
pestañas, cada una con su propia sesión del motor: **7 de 7 aprobadas.**

| Comprobación | Resultado |
|---|---|
| La interfaz carga y lista las tablas del catálogo | OK |
| Una consulta muestra su resultado y el plan real (`IndexScan` sobre `students_id_hash`) | OK |
| Desmarcar **Usar índices** cambia el plan a `TableScan` | OK |
| Un error de sintaxis aparece junto al editor con su línea y columna | OK |
| La consulta siguiente funciona y muestra `ExternalSort` | OK |
| Con **BEGIN** e INSERT en la pestaña A, la pestaña B muestra «Esperando lock S sobre enrollments, retenido por T4» | OK |
| Tras **END** en A, B recibe el conteo confirmado (5) | OK |

El script de navegador es una herramienta local de verificación y no forma
parte del repositorio, igual que en la auditoría de la Etapa 9.

## 3. Pruebas automáticas

| Verificación | Resultado |
|---|---|
| Suite completa con advertencias como errores (`pytest -W error`) | **2968 aprobadas** en 232 s |
| Frontend: `tsc --noEmit`, Vitest y `npm run build` | sin errores; 32 pruebas aprobadas |

## 4. Hallazgos

1. **Reinicio inmediato bloqueado ~60 s.** Tras cerrar el servidor, las
   conexiones de los clientes quedan en `TIME_WAIT` (comportamiento normal de
   TCP). El chequeo previo de puerto del lanzador (`api/__main__.py::port_is_free`)
   no usa `SO_REUSEADDR`, así que informa "puerto en uso" aunque uvicorn sí
   podría escuchar. Quien reinicia el servidor enseguida tiene que esperar un
   minuto o usar otro puerto. Corrección propuesta: usar `SO_REUSEADDR` en el
   chequeo en sistemas POSIX, como hace uvicorn; en Windows esa opción tiene
   otro significado y no debe usarse.
2. **Ctrl+C termina con traceback.** uvicorn 0.53 completa el apagado ordenado y
   después vuelve a lanzar la señal; Python la convierte en `KeyboardInterrupt`,
   imprime un traceback y sale con código -2 (130 en la terminal). La base se
   cierra igual, porque el cierre está en un `finally`, y el reinicio posterior
   reabre los archivos sin problemas. Corrección propuesta: capturar ese
   `KeyboardInterrupt` después del apagado.
3. **Panel Archivos desactualizado entre pestañas.** Cuando otra pestaña
   confirma una inserción, el panel Archivos de la pestaña actual sigue
   mostrando el conteo anterior hasta que se vuelve a cargar. Los resultados de
   las consultas sí son correctos. Es un detalle de presentación.

Los hallazgos 1 y 2 están en el lanzador de la Etapa 9, que es un módulo
cerrado; quedan propuestos y no se aplicaron sin aprobación.
