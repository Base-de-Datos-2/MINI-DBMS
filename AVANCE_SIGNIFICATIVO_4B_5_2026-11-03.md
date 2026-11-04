# Avance significativo de los bloques 4B y 5 (2026-11-03)

## Cambios de esta entrega

- `tests/text/test_4b_5_real_published_sql.py`: seis pruebas de integración con Heap real, SPIMI construido en disco, sellado, registro textual, apertura y reapertura real, ranking BM25/TF-IDF, índice/scan, EXPLAIN, EXPLAIN ANALYZE, vista previa y dos sesiones lectoras concurrentes independientes. Verifica también que la tabla textual está sellada y otra tabla sigue siendo modificable.
- `api/text_sql.py`: el plan describe `TextIndexScan` de forma coherente con el operador reportado por el motor.
- `frontend/src/components/TextPanel.tsx`: muestra SQL de ejemplo para la colección publicada, botones para enviar SQL y EXPLAIN al editor, literales SQL escapados, protección frente a resultados obsoletos y limpieza de resultados al cambiar filtros.
- `frontend/src/App.tsx`: conecta los botones del panel textual al editor SQL existente y limpia parámetros espaciales previos.
- Conserva la integración API/SQL y frontend de las iteraciones anteriores.

## Pruebas ejecutadas

- `python -m pytest -q tests/text --disable-warnings --maxfail=1`: **473 aprobadas**.
- `python -m pytest -q tests/api --disable-warnings --maxfail=1`: **181 aprobadas**.
- **654 pruebas aprobadas** en estos dos grupos.

## Pendientes antes de afirmar 100 %

- Integrar el operador textual nativamente en `engine.query.binder/planner/executor` para ejecución fuera de la API; hoy se ejecuta desde el adaptador de servicio.
- Compilar el frontend: `npm ci --offline` no encontró dependencias cacheadas y la instalación en línea agotó el tiempo disponible. No se ha verificado `npm run build`.
- Ejecutar suite total de regresión y prueba de navegador Playwright.

## SQL de aceptación

```sql
SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;
SELECT *, SCORE() AS relevancia FROM articulos WHERE MATCH(texto, 'machine learning') USING BM25 ORDER BY relevancia DESC;
```

Requiere colecciones publicadas reales en el registro; no se fabrican resultados ni se modifica una colección sellada.
