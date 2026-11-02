# Avance verificable de 4B y 5 — NO es el cierre al 100 %

## Cambios implementados en esta entrega

- `api/text_search.py`: consulta tipada de colecciones publicadas, recuperación de filas originales por RID, score, ruta de acceso y métricas reales de ranking.
- `api/schemas.py`: validación estricta de entrada para consulta textual.
- `api/engine_service.py`: admisión por sesiones, errores estructurados, límites de respuesta y acceso a colecciones publicadas.
- `api/app.py`: `GET /api/text/tables` y `POST /api/text/query`.
- `frontend/src/components/TextPanel.tsx`: panel React para escoger colección, modelo BM25/TF-IDF, índice/scan y mostrar score, resultados y operador.
- `frontend/src/api.ts` y `frontend/src/App.tsx`: cliente y navegación del panel.
- `tests/text/test_text_http_integration.py`: contratos de validación y rechazo de índices inexistentes.

## Verificaciones ejecutadas

- `python -m pytest -q tests/text/test_text_http_integration.py tests/text/test_registry_4b.py tests/api`: **191 passed**.
- Tras `python -m pip install -e . --no-deps --no-build-isolation`, `python -m pytest -q tests/text/test_ranking.py tests/text/test_ranking_contract.py tests/api`: **328 passed**.
- `python -m compileall -q api`: OK.

## Pendientes que impiden declarar 4B y 5 completados

1. El SQL textual `MATCH`, `USING`, `SCORE()` y `EXPLAIN` **no está integrado** en parser, binder, planner y executor; los dos ejemplos SQL oficiales aún no se ejecutan desde el editor SQL.
2. El panel añadido es una interfaz HTTP tipada, no una integración completa del editor SQL y sus paneles de plan/resultado.
3. La build del frontend y pruebas en navegador no fueron reproducidas. `npm ci --offline` falló por caché incompleta; `npm ci` online agotó el tiempo. El código fuente React está presente, pero **no se incluye `frontend/dist` compilado**.
4. Falta demostrar el flujo completo contra una colección publicada real por HTTP, incluyendo dos sesiones lectoras, reapertura aislada, errores de sellado y todas las matrices A01–A17 / R01–R26.
5. No se ha ejecutado toda la suite de regresión del repositorio.

## Uso de la API nueva (tras instalar dependencias y publicar una colección)

`GET /api/text/tables` lista las colecciones publicadas. `POST /api/text/query` recibe:

```json
{"table":"documentos","column":"contenido","query":"base de datos","model":"BM25","order":"score_desc","limit":10,"max_rows":10,"use_indexes":true}
```

El servicio rechaza tablas o columnas sin registro textual compatible. Para usar la UI React se debe compilar el frontend con `npm ci && npm run build` en un entorno con acceso al registro de npm.

**Advertencia:** no sustituir la rama estable del equipo por este avance sin revisión y pruebas de integración.
