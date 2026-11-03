# Entrega incremental 4B/5 — integración SQL textual

## Cambios implementados

- `api/text_sql.py`: validación estricta del subconjunto SQL textual y ejecución a través de la colección publicada propiedad de `api.database.Database`. Reconoce `MATCH`, `USING TF_IDF/BM25`, `SCORE()`, alias, `ORDER BY` y `LIMIT` con puntuaciones y RIDs reales.
- `api/engine_service.py`: enruta las consultas textuales analizadas desde `POST /api/query`, incluyendo `EXPLAIN` sin ejecución y `EXPLAIN ANALYZE` con una ejecución. Las consultas SQL relacionales existentes mantienen su ruta.
- `engine/query/parser.py`: evita consumir `USING` como alias de tabla sin WHERE.
- `tests/text/test_text_sql_adapter_4b.py`: casos de proyección, orden, preview, explain, modelo, errores semánticos y ejemplos de la tarea (con dobles de colección para aislar la capa SQL).

## Verificación ejecutada

- `python -m compileall -q api/text_sql.py api/engine_service.py`: correcto.
- `PYTHONPATH=. pytest -q tests/text --disable-warnings --maxfail=1`: **467 aprobadas** después de `pip install -e . --no-deps --no-build-isolation`.
- `npm run build` **no verificado**: no existe `frontend/node_modules`; TypeScript informa que falta `vite/client`.
- Suite completa de todo el proyecto: **no concluida** en este entorno.

## Limitaciones pendientes (no presentar como 100 %)

- El SQL textual está integrado en el adaptador HTTP, pero **no** en `engine.query.binder/planner/executor` para sesiones de `SqlEngine` utilizadas fuera de la API.
- La suite de aceptación con colecciones publicadas reales, reapertura, dos lectores y navegador no se ha ejecutado de extremo a extremo.
- `EXPLAIN` textual devuelve un árbol descriptivo del adaptador, no un plan físico del planner relacional.
- La vista textual del frontend y los endpoints dedicados venían del avance anterior y no han podido compilarse en este entorno.

## Ejemplos SQL desde el panel SQL

```sql
SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;
SELECT *, SCORE() AS relevancia FROM articulos WHERE MATCH(texto, 'machine learning') USING BM25 ORDER BY relevancia DESC;
EXPLAIN SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 LIMIT 10;
```

Requieren tablas publicadas y registradas mediante el flujo offline de Parte 3; no se generan datos falsos.
