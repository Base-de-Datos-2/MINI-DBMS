# MINI-DBMS — continuación 4B y 5

## Cambios implementados

- `api/engine_service.py`: las búsquedas textuales HTTP sin token ahora abren una sesión lectora independiente por petición. La política de sesión predeterminada para SQL relacional y escrituras permanece sin cambios; los tokens explícitos conservan su sesión. El cambio afecta tanto a `/api/text/query` como a las consultas textuales de `/api/query`.
- `tests/text/test_4b_5_real_http_acceptance.py`: regresión de concurrencia de 24 solicitudes paralelas con ocho trabajadores para cada endpoint, utilizando un índice SPIMI real y almacenamiento Heap sellado. Comprueba HTTP 200 y resultados consistentes.
- `frontend/src/components/TextPanel.tsx`: al actualizar colecciones se invalidan inmediatamente las búsquedas pendientes, y un error de actualización borra colecciones obsoletas para evitar mostrar datos de otra generación.

## Validación

- `python -m pytest -q tests/text/test_4b_5_real_http_acceptance.py tests/text/test_4b_5_real_published_sql.py tests/text/test_text_sql_adapter_4b.py`: **27 passed**.
- Se intentó ejecutar `tests/text tests/api` conjuntamente, pero el proceso excedió el tiempo disponible; no se afirma que haya finalizado.
- Frontend React/Vite: **no compilado ni probado en navegador en esta iteración**.

## Pendiente para declarar 100 %

- Integración del operador textual en el binder, planner y executor nativos de `engine.query`, independiente del adaptador HTTP.
- Compilación del frontend y prueba de navegador.
- Ejecución completa de regresiones del repositorio.

**Este ZIP es un avance verificable y no una entrega final al 100 %.**
