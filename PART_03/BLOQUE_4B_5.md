# Bloques 4B y 5 — integración textual y demo

Fecha: 3 de noviembre de 2026. Alcance: los bloques 4B y 5 de Parte 3, no las Partes 4 y 5 del PDF. Esta entrega sustituye las limitaciones de las notas `AVANCE_*` anteriores. El bloque 6 experimental continúa fuera de este cierre.

## Implementación

La consulta textual sigue la ruta `parser → binder → planner → TextIndexScan/TextScan → QueryResult`. Ya no se ejecuta mediante un binder alternativo dentro de HTTP. `SqlEngine`, las sesiones, `/api/query` y los paneles existentes consumen el mismo plan nativo.

- `engine/query/text_binding.py` valida una tabla, MATCH único, campo VARCHAR publicado, modelo TF_IDF/BM25, proyecciones, alias de SCORE, orden y LIMIT. Rechaza JOIN, GROUP BY, predicados compuestos y órdenes fuera del contrato.
- `QueryEnvironment` toma prestados lectores textuales y exige un Heap sellado compatible. El owner conserva su propiedad y cierre. La validación de planes detecta cambios de asociación; las sesiones conservan la política de replanificación por generación.
- `TextScanSpec` crea operadores reales. Estos llaman al ranking propio, que usa postings para índice y Heap para scan. El ranking aplica el orden total antes de LIMIT; usa TopKHeap solo cuando corresponde y ExternalSort para las demás rutas. Los descriptores incluyen modelo, colección/generación, orden, límite y métricas observadas, incluida la selección realmente ejecutada. Es un operador compuesto: no se presenta un árbol ficticio de hijos que no tiene.
- La ejecución comparte el contexto, la cancelación cooperativa, los locks y el ciclo de vida de resultados existentes. Cerrar un consumidor no cierra los archivos permanentes prestados.
- `api/text_sql.py` queda como compatibilidad para llamadores anteriores: delega a la sesión nativa y al serializador estándar. `/api/query` ejecuta directamente la ruta ordinaria del motor.
- El endpoint tipado conserva recuperación/serialización de las filas dentro de la lectura protegida y de su ámbito de cancelación.

## Preparación y publicación

`Database.prepare_text()` acepta tablas y filas iterables, crea exclusivamente un directorio nuevo y carga mediante el owner existente. La carga Heap admite flujo sin retener todos los textos. Tras cerrar el owner y el coordinador, construye SPIMI, valida la asociación completa Heap/índice y sella todos los índices secundarios declarados y el Heap. El registro versionado se publica una sola vez al final. Los fallos no publican una colección incompleta; el directorio fallido se conserva para inspección y se reconstruye en otro destino.

Finalmente abre un owner nuevo y valida los índices publicados. `scripts/setup_text.py` ofrece una muestra explícita para demo y una entrada CSV UTF-8. La muestra no constituye un experimento ni se presenta como corpus académico real. El owner alternativo `engine.database.Database` sigue rechazando colecciones textuales que no administra.

`python -m api --text` abre ese mismo owner. `--text` y `--spatial` son excluyentes. El registro textual es obligatorio para el modo textual. El panel Files muestra el índice SPIMI y su tamaño; Query, Results y Execution Plan presentan el SQL y la ejecución nativa. El panel textual permite elegir colección, modelo e índice/scan, ver scores y enviar ejemplos al editor.

## Instalación y ejecución

Desde la raíz del proyecto, en Anaconda Prompt o una terminal con Python 3.11 o superior:

```bash
python -m pip install -e ".[test,api]"
python scripts/setup_text.py
python -m api --text
```

Abrir `http://127.0.0.1:8000`. El ZIP incluye `frontend/dist` compilado. Para reconstruirlo:

```bash
cd frontend
npm ci
npm run build
npm test
```

No preparar sobre un directorio existente. Para una segunda preparación, elegir un destino nuevo:

```bash
python scripts/setup_text.py --data-dir data/generated/text_nuevo
python -m api --text --data-dir data/generated/text_nuevo
```

Para datos propios, con columnas `id` y `contenido`:

```bash
python scripts/setup_text.py --csv documentos.csv --data-dir data/generated/text_csv
python -m api --text --data-dir data/generated/text_csv
```

Se admiten `--table`, `--text-column` y `--memory-budget-bytes`. Los IDs deben ser enteros únicos compatibles con INTEGER; el tamaño máximo del texto sigue siendo el del registro Heap. Los datos inválidos causan error, no truncamiento silencioso.

## Secuencia de demo

1. Preparar con el servidor detenido y arrancar con `--text`.
2. Elegir `documentos` en Files; comprobar esquema e índice SPIMI.
3. Ejecutar el primer ejemplo literal del PDF:

```sql
SELECT * FROM documentos
WHERE MATCH(contenido, 'base de datos vectorial')
USING TF_IDF LIMIT 10;
```

4. Ejecutar el segundo ejemplo literal, con la tabla y campo originales:

```sql
SELECT *, SCORE() as relevancia FROM articulos
WHERE MATCH(texto, 'machine learning')
USING BM25
ORDER BY relevancia DESC;
```

5. Observar filas/scores y el plan TextIndexScan. Desactivar «Usar índices» y repetir: resultados iguales, ruta TextScan.
6. Anteponer EXPLAIN y EXPLAIN ANALYZE: el primero prepara sin puntuar; el segundo ejecuta y publica mediciones.
7. Consultar desde el panel textual con ambos modelos. No prometer un modelo ganador: las diferencias dependen del corpus y la consulta.
8. Detener con Ctrl+C y arrancar otra vez; repetir las consultas y comparar filas, orden y scores.
9. Si se desea demostrar el sello, arrancar con `--allow-writes` e intentar INSERT/DELETE sobre la colección: deben rechazarse. Las pruebas incluyen además el rollback de cambios previos en otra tabla mutable.

## Reproducción de las verificaciones

```bash
python -m pytest -q tests/text tests/api -W error
python -m pytest -q -W error
```

Para la aceptación automatizada con navegador y un servidor nuevo:

```bash
cd frontend
npm ci
npx playwright install chromium
npm run test:browser:text
```

El script crea una base temporal exclusiva, arranca un servidor real en un puerto libre, usa Chromium, verifica los dos ejemplos por UI, modelos, acceso, Files, EXPLAIN/ANALYZE, lectores HTTP concurrentes y escritura rechazada, reinicia el servidor y contrasta resultados. No utiliza mocks de API. Acepta `PYTHON_EXECUTABLE`, `BROWSER_EXECUTABLE_PATH` y `REPORT_PATH` como variables de entorno. La demo espacial conserva su script anterior.

## Evidencia y límites

- Aceptación focalizada nativa: 51 pruebas aprobadas, incluyendo motor autónomo sin HTTP, ambas consultas del PDF, órdenes con ID oculto, límites, errores semánticos, planes reutilizados, cancelación, dos lectores, fallo de publicación, fallo de apertura sin fuga de lectores, CSV y sellado de índices secundarios.
- Frontend: compilación TypeScript/Vite correcta y 43 pruebas existentes aprobadas.
- Navegador real: ocho grupos de comprobaciones en PASS, Chromium 153.0.8010.0. Evidencia estructurada en `docs/evidence/text_browser.json`.
- Regresión global final: **3 547 pruebas aprobadas, sin fallos**, en 133,59 segundos, mediante `python -m pytest -q -n 4 -W error` (pytest-xdist 3.8.0). Incluye las 51 focalizadas; no deben sumarse otra vez. La ejecución secuencial equivalente no requiere xdist. Registro completo: `docs/evidence/text_backend_regression.txt`.

Durante el primer recorrido global se detectaron dos fallos de arquitectura: un ciclo binder/text_binding y la regla que aún no admitía query → text. Se separaron los datos de enlace del binder general, se declaró únicamente esa dependencia necesaria y se repitió la suite completa hasta obtener el resultado anterior. Las comprobaciones de capas y ausencia de ciclos permanecen activas. Las ejecuciones interrumpidas o anteriores a la corrección no se presentan como aprobación.

**Dictamen de alcance: bloques 4B y 5 implementados y verificados**, con los límites de plataforma y arquitectura que siguen. El estado no equivale al cierre experimental ni a una garantía de ausencia absoluta de defectos.

Se probó en Linux/Python 3.12; no se afirma haber ejecutado Windows. Se conservan los límites ya declarados del motor: un proceso propietario, sin WAL ni recuperación automática de caídas ni commit atómico entre varios archivos. El acumulador de candidatos del ranking es O(C); los bytes estimados no equivalen a RSS. No se reejecutó la matriz experimental ESCI/PostgreSQL de 1k/10k/100k y no se inventaron métricas, gráficos ni cifras de relevancia. Esa comparación pertenece al bloque 6. Este cierre no sustituye el video general ni la entrega de las Partes 4/5 del PDF.
