# Avance verificable — Parte 3, bloque 4B

## Implementado en esta iteración
- AST `TextMatch` y campo `SelectStatement.text_model`.
- Parser para `MATCH(columna, 'consulta') USING TF_IDF|BM25`, incluyendo alias de tabla y paréntesis en WHERE.
- Parser de `SCORE()` en proyecciones, con alias.
- Pruebas de parser en `tests/text/test_sql_text_parser_4b.py`.

## Verificación
`python -m pytest -q tests/text/test_sql_text_parser_4b.py tests/query/test_parser.py`
Resultado: **25 passed**.

## Pendiente (NO ES UNA ENTREGA FINAL)
- Binding semántico y registro textual en planes SQL.
- Operador de ejecución, puntuaciones y ordenamiento con LIMIT.
- EXPLAIN/ANALYZE textual y validación de todos los casos del contrato.
- Integración de las consultas SQL completas por API y frontend.
- Pruebas de reapertura, concurrencia y navegador de extremo a extremo.

El endpoint textual tipado y el panel de texto son los heredados del ZIP anterior. No se ha validado una demo de navegador en esta iteración.
