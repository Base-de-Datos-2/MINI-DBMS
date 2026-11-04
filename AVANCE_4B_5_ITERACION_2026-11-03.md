# Avance 4B y 5 — 2026-11-03 (iteración adicional)

## Cambios reales
- `api/text_sql.py`: el árbol preparado de EXPLAIN ahora incluye como hijo explícito el acceso físico `TextIndexScan` o `TextScan`, con tabla, columna y modelo. El acceso mostrado coincide con la ejecución.
- `tests/text/test_4b_5_real_published_sql.py`: nuevas pruebas reales para verificar el operador de EXPLAIN frente a la ejecución, orden ascendente de SCORE y orden por ID.
- `frontend/src/components/TextPanel.tsx`: invalidación de resultados y estado de carga cuando cambian los parámetros; respuestas antiguas no sustituyen los resultados nuevos; limpieza al desmontar el componente.

## Verificaciones de esta iteración
- `python -m pytest -q tests/text/test_4b_5_real_published_sql.py tests/text/test_text_sql_adapter_4b.py --disable-warnings --maxfail=1`: **20 passed**.
- Intento de `npm run build`: no completado; faltan tipos `vite/client` porque las dependencias de npm no están completas. `npm ci` agotó el tiempo disponible.
- La suite completa del repositorio no terminó en esta iteración.

## Estado y límites
Este archivo es un **avance**, no una entrega al 100 %. El operador textual todavía se despacha desde la capa de servicio/API en vez de incorporarse como plan nativo reutilizable del `SqlEngine` independiente. Queda pendiente compilar frontend, ejecutar pruebas de navegador y suite integral.
