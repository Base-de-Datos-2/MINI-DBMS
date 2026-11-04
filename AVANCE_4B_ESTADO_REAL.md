# Avance técnico verificable de 4B (NO es entrega 4B/5 completa)

Este archivo distingue trabajo realizado de trabajo pendiente. No se debe presentar este ZIP como cumplimiento total de 4B/5.

## Implementado en esta copia
- `engine/text/registry.py`: lectura estricta de un registro `text_tables.json` v1; validación de formato, unicidad de tabla y directorio seguro.
- `api/database.py`: apertura y validación de índices textuales publicados contra el Heap sellado, cierre de handles y operación tipada de búsqueda textual protegida por la sesión lectora.
- `tests/text/test_registry_4b.py`: pruebas del formato y rechazos.

## Verificado
- 74 pruebas focalizadas de registro, API Database y sellado: PASS.
- Suite `tests/text tests/api` se interrumpe tras 124 PASS y un fallo de importación en subproceso aislado (`ModuleNotFoundError: engine`). Se intentó instalar en editable pero el entorno sin acceso a paquetes impidió descargar `setuptools>=68`. No se atribuye ese fallo a SPIMI.

## No implementado / no verificado
- Publicación offline coordinada y escritura atómica del registro.
- Parser, AST, binder, operador SQL, `MATCH`, `SCORE()`, `USING`, `EXPLAIN` y matriz de aceptación A01-A17/R01-R26.
- API HTTP textual, interfaz de búsqueda, score/modelo/plan, demo navegador.
- Matriz integral de escrituras, dos sesiones lectoras de punta a punta y reapertura publicada en proceso independiente.
- Suite global de regresión.

## Advertencia
No sustituir una entrega estable del equipo sin revisión. La versión 1 del registro es un diseño nuevo de este avance y requiere aprobación del equipo y completar el publicador. Las funciones nuevas no están conectadas a SQL ni HTTP.
