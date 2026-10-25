# Plan de implementación — Parte 3: búsqueda textual

## 1. Objetivo y criterio de alcance

Implementar en MINI-DBMS **recuperación textual persistente mediante vectores dispersos de términos, un índice invertido SPIMI, TF-IDF/coseno y BM25**. Exponerla mediante SQL y compararla de forma reproducible con **PostgreSQL GIN + ranking nativo**.

El vocabulario V de la colección define el espacio vectorial: cada término distinto corresponde a una dimensión y cada documento tiene |V| componentes. La componente de frecuencia es `tf(t,d)`; los términos ausentes tienen valor cero. Persistir el léxico con una asignación estable `término → dimensión` y los postings `(doc_id, tf)` conserva únicamente las componentes no nulas, agrupadas por término. Por tanto, esos archivos representan de forma dispersa los vectores documentales sin guardar una matriz densa ni duplicar un vector por cada modelo. Las frecuencias persistidas, `df`, N y las normas permiten reconstruir los pesos TF-IDF; BM25 utiliza las mismas frecuencias más las longitudes y la longitud media. La consulta se proyecta al mismo vocabulario. BM25 es una función de ranking sobre esa representación, no una similitud del coseno adicional.

Este documento es un plan, no evidencia por sí solo de funcionalidades implementadas. Revisión del 22 de octubre de 2026: se precisan representación vectorial, propietario de índices, ordenamiento, inmutabilidad y aceptación del corpus; la segunda revisión añade rechazo antes de capturar undo, lectura concurrente de postings, orden dentro de los bloques SPIMI y separación entre desarrollo con fixtures y aprobación del corpus. Los bloques 1A y 1B están cerrados. La solicitud posterior del 24 de octubre autorizó **1B.5–1B.8**; la aceptación real del corpus está en PASS, documentada en [BLOQUE_1B.md](BLOQUE_1B.md). Los bloques posteriores quedan pendientes. Se basa en `Proyecto_Final.pdf`, sección 2.3 (páginas 3–4), y en el repositorio revisado en el commit `85db1bec94e0515dfff621dfa1ae8dece4c6ca08`. Las Partes 3–5 no se consideran completadas.

El PDF no incluye una rúbrica numérica separada. Por ello, la matriz siguiente convierte sus requisitos explícitos en criterios verificables; no inventa puntajes ni obligaciones adicionales. El Avance 3 requiere **Partes 3 y 4**: completar este plan cubre solamente la Parte 3.

### Requisitos y evidencia de cumplimiento

| Requisito del enunciado | Implementación mínima completa | Evidencia de aceptación |
|---|---|---|
| Índice invertido mediante SPIMI | Construcción por bloques con presupuesto de memoria, escritura temporal y mezcla final; léxico y frecuencias persistidas representan vectores dispersos | Una prueba que fuerce varios bloques, compare con un oráculo y reconstruya componentes al reabrir |
| TF-IDF + coseno | Pesos, normas y ranking propios | Scores calculados a mano y comparación contra evaluación exhaustiva |
| BM25 | Fórmula propia, longitudes y estadísticas del corpus | Casos conocidos y ranking contrastado con un oráculo independiente |
| Extensión SQL | `MATCH`, `USING TF_IDF`, `USING BM25`, `SCORE()`, alias, orden y límite | Los dos ejemplos del PDF ejecutados por el motor |
| Comparación de tres técnicas | TF-IDF/coseno y BM25 sobre SPIMI; PostgreSQL GIN con `ts_rank` | Mismos documentos, consultas y reglas de coincidencia |
| Tres tamaños | 1 000, 10 000 y 100 000 documentos | Manifiestos reproducibles con IDs y hashes |
| Tres longitudes de consulta | 1, 3 y 5 o más palabras | Consultas etiquetadas por longitud y preservadas en archivos |
| Construcción, consulta, relevancia y recursos | Tiempos, Precision@10, Recall@10, memoria y disco | Datos crudos, metodología y resultados por configuración |
| Presentación experimental | Gráficas y tabla de ventajas/desventajas | Informe con conclusiones respaldadas por las mediciones |

## 2. Decisiones para mantener el proyecto simple

1. **Reutilizar el motor existente.** Mantener Heap, catálogo, sesiones, SQL, API y frontend. PostgreSQL continúa como comparador experimental; no ejecuta las búsquedas de MINI-DBMS.
2. **Un campo textual por índice y una tabla por consulta textual.** No agregar búsquedas combinadas con JOIN, GROUP BY, mapas o multimedia en esta entrega.
3. **Un índice compartido por ambos rankings.** Conservar frecuencias y estadísticas que permitan ejecutar TF-IDF y BM25 sobre los mismos postings.
4. **Carga por lotes y colección textual publicada en modo solo lectura.** El enunciado de la Parte 3 no exige mantenimiento incremental del índice. Construir/reconstruir mediante un script en un directorio nuevo y rechazar las mutaciones sobre la colección publicada desde el motor, incluidos sus servicios y accesos directos soportados al almacenamiento. Persistir esa política y restablecerla antes de exponer la colección tras cualquier reapertura (§5.2). Las tablas relacionales existentes conservan su comportamiento. Esta restricción evita rankings obsoletos sin diseñar un nuevo sistema transaccional.
5. **Textos cortos que quepan en las páginas actuales.** Serializar la fila con el codec real y comprobar además el límite efectivo del Heap/página; el codec por sí solo no impone capacidad de página. No implementar overflow, BLOB, extracción PDF ni fragmentación automática para esta entrega.
6. **Preprocesamiento sencillo y determinista.** El contrato 1A.3 fija NFC → minúsculas → NFC y secuencias máximas Unicode `str.isalnum()`; sin stemming, sinónimos, corrección ortográfica ni eliminación de stopwords. Aplicar `engine.text.tokenize` a documentos y consultas y persistir su firma de algoritmo/versión Unicode con cada índice futuro. Detalles y pruebas en [BLOQUE_1A.md](BLOQUE_1A.md).
7. **Búsqueda léxica con vectores dispersos.** No incorporar embeddings, LLM, una base vectorial externa ni un framework de recuperación. El título “vectorial” no requiere esas tecnologías: aquí los vectores son los pesos por término.
8. **Reutilizar los cuatro paneles del frontend.** Añadir consultas de ejemplo, mostrar scores y el plan; no crear una interfaz nueva ni otro endpoint de búsqueda si `POST /api/query` resulta suficiente.

No forman parte del alcance: frases exactas, proximidad, resaltado avanzado, consultas difusas, ranking híbrido, compresión sofisticada, WAND/Block-Max WAND, GPU, sharding, WAL, nuevos mecanismos de concurrencia, índices IVF/HNSW o la aplicación de la Parte 5.

## 3. Datos y contrato de consulta

### 3.1 Colección y almacenamiento

Usar una tabla conceptual `documentos(id INTEGER, contenido VARCHAR(...))`. El largo declarado debe calcularse según el límite conjunto de la fila, incluidos encabezados y demás campos. Mantener los IDs originales del corpus si caben en INTEGER; de lo contrario, persistir un mapeo estable.

Reutilizar Heap para los textos y mantener una tabla auxiliar interna `doc_id → RID` para recuperar los documentos ganadores sin escanear toda la colección. Persistirla junto con las estadísticas. El índice y los RIDs pertenecen a la misma colección inmutable; no reutilizarlos después de reconstruirla.

Preparar dos conjuntos:

- **Fixture pequeño en español:** entre 10 y 20 textos legibles, con repeticiones de términos, documentos de distintas longitudes, empates y respuestas comprobables. Sirve para pruebas y demo.
- **Corpus experimental real aceptado:** el candidato inicial MS MARCO Passage Ranking falla la puerta de consultas de una palabra (2 elegibles en dev, 4 en train). La alternativa aceptada es Amazon ESCI, large_version/test/us, con el título original íntegro de cada producto como documento y sus consultas/juicios originales. Registrar versión, origen, campo elegido y condiciones de uso. Procesar documentos como flujo; no cargar el corpus textual completo en memoria. Decisiones y evidencia: [BLOQUE_1B.md](BLOQUE_1B.md).

**Aceptación global del corpus: PASS.** MS MARCO v1 queda rechazado para esta matriz de longitudes. ESCI completa 1B.1–1B.8: subconjuntos exactos 1 000 ⊂ 10 000 ⊂ 100 000 con semilla 20261024; 30 consultas originales y sus 439 documentos positivos presentes desde 1k; 100 000 filas verificadas mediante Heap real y reapertura en otro proceso. El informe y la reproducción independiente de 13 artefactos están en [BLOQUE_1B.md](BLOQUE_1B.md). Esto aprueba el corpus seleccionado, no completa el motor textual ni los experimentos de recuperación.

### 3.1.1 Puerta de aceptación del corpus — obligatoria antes de adoptarlo

Preparar una exportación local TSV/JSONL mediante un script de preparación; no agregar una dependencia de descarga al motor. El script debe producir `corpus_feasibility.json` con estado PASS/FAIL y los siguientes resultados medidos:

| Comprobación | Condición de aprobación | Evidencia conservada |
|---|---|---|
| Fuente accesible | Corpus, consultas originales y qrels de versiones/splits compatibles disponibles | Fuente, versión, hashes y tamaño de descarga |
| Capacidad real | Al menos 100 000 IDs únicos con texto íntegro admitido por el esquema, `RecordCodec` y el máximo de registro del Heap/página | Cantidad inspeccionada/aceptada, motivos de rechazo, máximo y distribución de bytes codificados |
| Inserción y reapertura | Las filas seleccionadas se insertan en Heap temporal con el esquema definitivo y vuelven a leerse sin cambios | Conteos y hashes del contenido antes/después; errores de límites y codificación |
| Consultas originales | Al menos 10 consultas distintas en cada grupo de 1, 3 y 5+ tokens según el tokenizer definitivo | IDs, texto original y longitud de las 30 consultas |
| Juicios utilizables | Cada consulta tiene al menos un positivo almacenado; todos los positivos conocidos de esas consultas en los qrels utilizados caben íntegros, y sus IDs se resuelven | Qrels filtrados, positivos por consulta y comprobación de referencias |
| Subconjuntos anidados | La unión de positivos conocidos de las 30 consultas cabe dentro de 1 000 documentos; se completan 1 000 ⊂ 10 000 ⊂ 100 000 con IDs válidos | Manifiestos de los tres conjuntos, semilla y hashes |

Usar el límite importado del motor, no un valor aproximado de 4 KiB. La serialización incluye todos los campos y sus prefijos; la comprobación de capacidad debe incorporar los límites de registro/slot. Validar las 100 000 filas seleccionadas, no extrapolar una muestra. El informe de viabilidad y los manifiestos son evidencia de preparación, no mediciones finales de rendimiento.

No truncar documentos ni acortar consultas originales conservando automáticamente sus juicios. Si faltan consultas de una longitud o sus positivos no caben, escoger otras consultas originales evaluables; si el candidato sigue fallando, seleccionar otro corpus con juicios y repetir esta misma puerta. No reducir los tres tamaños ni eliminar grupos de longitud para declarar éxito. Solo un PASS de toda la puerta permite congelar el corpus del experimento. Mientras siga pendiente, se puede avanzar con la fixture y componentes independientes del corpus dentro del alcance autorizado, sin afirmar aceptación completa ni calidad experimental medida.

### 3.2 Semántica mínima

- `MATCH(campo, consulta)` encuentra documentos que contengan **al menos uno** de los términos normalizados de la consulta: semántica OR.
- Los términos fuera del vocabulario no generan candidatos. Una consulta vacía o sin términos conocidos devuelve cero filas.
- Un documento vacío no produce coincidencias; se maneja sin división por cero.
- `USING` selecciona exclusivamente `TF_IDF` o `BM25`. En la forma textual será obligatorio, para evitar un valor predeterminado implícito.
- Sin `ORDER BY`, las coincidencias se entregan por score descendente e ID ascendente. El contrato exacto de órdenes y desempates se define en §3.3; el planner debe resolverlo antes de elegir top-k.
- `SCORE()` es un FLOAT calculado para el MATCH actual; fuera de una consulta textual válida produce un error semántico claro.
- `LIMIT` limita el resultado **después de aplicar el orden solicitado**, no necesariamente después de ordenar por relevancia descendente. Sin LIMIT se mantiene la semántica de devolver todas las coincidencias; la vista HTTP conserva su límite de presentación y señala la truncación.
- Para mantener acotada la extensión, admitir un MATCH como condición completa, una tabla, proyección de columnas o `*`, `SCORE()` y orden por relevancia/ID. Rechazar combinaciones textuales con JOIN, agregación, varios MATCH o expresiones booleanas compuestas en esta primera versión.

### SQL que debe funcionar

```sql
SELECT * FROM documentos
WHERE MATCH(contenido, 'base de datos vectorial')
USING TF_IDF LIMIT 10;

SELECT *, SCORE() AS relevancia FROM articulos
WHERE MATCH(texto, 'machine learning')
USING BM25 ORDER BY relevancia DESC;
```

Crear una fixture `articulos(id, texto)` para ejecutar literalmente el segundo ejemplo. No es necesario duplicar el corpus de 100 000 documentos.

Añadir a las pruebas y a la demo:

```sql
SELECT id, SCORE() AS relevancia FROM documentos
WHERE MATCH(contenido, 'base de datos vectorial')
USING BM25 ORDER BY relevancia DESC LIMIT 10;

EXPLAIN ANALYZE
SELECT id, SCORE() AS relevancia FROM documentos
WHERE MATCH(contenido, 'base de datos vectorial')
USING TF_IDF LIMIT 10;
```

### 3.3 Ordenamiento antes de LIMIT y top-k

Aceptar únicamente las siguientes formas para consultas textuales. `relevancia` representa cualquier alias válido de `SCORE()`; omitir ASC/DESC significa ASC, como en SQL. Una columna o combinación no incluida se rechaza explícitamente en el binder.

| Orden solicitado | Orden total efectivo | Ejecución inicial |
|---|---|---|
| Sin ORDER BY | score DESC, id ASC | Top-k por esa clave si hay LIMIT; orden completo si no lo hay |
| `ORDER BY relevancia DESC` | score DESC, id ASC | Igual al anterior |
| `ORDER BY relevancia DESC, id ASC` | score DESC, id ASC | Igual al anterior |
| `ORDER BY relevancia ASC` o `ORDER BY relevancia` | score ASC, id ASC | Todas las coincidencias → orden solicitado → LIMIT |
| `ORDER BY relevancia ASC, id ASC` | score ASC, id ASC | Todas las coincidencias → orden solicitado → LIMIT |
| `ORDER BY id ASC` o `ORDER BY id` | id ASC | Todas las coincidencias → orden solicitado → LIMIT |
| `ORDER BY id DESC` | id DESC | Todas las coincidencias → orden solicitado → LIMIT |

El ID es único en la colección. `ORDER BY id` también funciona si el ID no se proyecta: conservarlo como dependencia oculta. Para ordenar por score en esta versión, usar un alias de `SCORE()` en SELECT; no hace falta agregar `ORDER BY SCORE()` directo.

**Regla de corrección:** no descartar candidatos por score antes de resolver ORDER BY. El heap que conserva los mayores scores se permite exclusivamente cuando el orden total efectivo es `(score DESC, id ASC)` y existe LIMIT k. Debe respetar también el desempate por ID y ordenar los k ganadores antes de entregarlos. Para los demás órdenes, reutilizar `ExternalSort` sobre todas las coincidencias y aplicar LIMIT después. No optimizar esas otras rutas en esta entrega.

Prueba mínima que detecta el error: tres coincidencias con `(id, score) = (1, 0.2), (2, 0.9), (3, 0.5)`. Con LIMIT 1, `ORDER BY id ASC` y `ORDER BY relevancia ASC` devuelven ID 1; relevancia DESC devuelve ID 2; ID DESC devuelve ID 3. Estas expectativas deben mantenerse con índice, scan y después de reabrir.

## 4. Índice SPIMI y ranking

### 4.1 Construcción externa

1. Leer documentos secuencialmente y contar frecuencias por documento. No suponer que los IDs originales llegan ordenados. Validar su unicidad en toda la colección, incluidos documentos vacíos y duplicados distribuidos entre bloques; un ID repetido invalida la construcción antes de publicar.
2. Mantener un diccionario temporal `término → [(doc_id, tf), ...]`; cada posting representa una frecuencia, no una entrada por aparición.
3. Al alcanzar el presupuesto configurable, ordenar los términos del bloque y, para cada término, ordenar sus postings por doc_id antes de volcarlo a disco. Ordenar términos no ordena las listas de documentos. Contabilizar la memoria de esa ordenación y del registro de IDs; documentar cómo se estima la memoria de las estructuras Python, sin equiparar el presupuesto al RSS total del proceso.
4. Mezclar los bloques con k-way merge y fan-in limitado. Si hay más bloques que entradas permitidas, realizar varias pasadas. Para un término presente en varios bloques, mezclar sus listas ya ordenadas por doc_id mediante iteradores acotados, sin concatenarlas completas en memoria. Conservar las frecuencias y rechazar IDs repetidos en la lista resultante; calcular df a partir de documentos únicos.
5. Escribir postings ordenados por doc_id, un léxico con dimensión estable por término, offsets/longitudes y `df`, y estadísticas `N`, longitudes documentales y longitud media.
6. Calcular las normas TF-IDF con los `df` definitivos mediante una pasada por los postings, acumulando por doc_id.
7. Publicar la colección y sus archivos terminados; limpiar temporales. Una construcción fallida no debe registrar un índice aparentemente válido.

Formato inicial suficiente: postings binarios de enteros con versión; léxico y manifiesto simples; vectores de estadísticas y mapeo de documentos. Mantener léxico y estadísticas en memoria si las mediciones lo permiten, pero **no cargar todos los postings ni el corpus** al abrir. Leer las listas necesarias por offset e iterarlas.

Persistir configuración de tokenización, esquema/campo, cantidad de documentos y asociación a la colección. Validar archivos y consistencia básica al reabrir. No prometer recuperación ante crashes: preparar en un directorio nuevo, cerrar correctamente y abrir una colección completa basta para el alcance adoptado.

### 4.1.1 Lecturas concurrentes del índice publicado

El owner comparte lectores permanentes entre sesiones (§5.1). La inmutabilidad del archivo no vuelve seguro un cursor de archivo compartido: los locks de lectura de tabla permiten consultas simultáneas y no impiden que dos operaciones `seek/read` se intercalen.

Implementar en el lector textual una operación de lectura por offset que proteja **todo el seek y la lectura exacta del bloque** mediante un latch físico, siguiendo el patrón existente de `PageManager`. El alcance del latch termina al copiar el bloque; no mantenerlo durante scoring, entrega de filas o la consulta completa. Cada iterador conserva su propio offset lógico y sus límites de lista, y los usa en cada lectura; nunca depende de la posición que dejó otro iterador. Los buffers de lectura son acotados y se contabilizan por consulta. No crear otro gestor de locks transaccionales ni serializar todas las búsquedas con un guard global.

El cierre del lector se coordina con el mismo latch y con el ciclo de vida del owner: primero finalizar/cancelar consultas, después cerrar handles permanentes. Los operadores cierran solo sus iteradores y buffers. Una lectura incompleta o posterior al cierre produce un error controlado.

Aceptación: dos consultas con listas distintas y parcialmente compartidas se intercalan de forma determinista sobre el mismo lector. Sus postings, IDs y scores deben coincidir con las ejecuciones seriales, con buffers pequeños que obliguen a varias lecturas. Cubrir también cierre anticipado/cancelación de un iterador sin afectar al otro. Al integrar sesiones, repetir el caso mediante dos sesiones concurrentes del mismo owner.

### 4.2 TF-IDF + coseno

Fijar una variante explícita, sin dejar fórmulas implícitas:

El [contrato de ranking 1A.5](../docs/text-ranking-contract.md) conserva estas
fórmulas y registra ejemplos resueltos, resultados congelados y tolerancias
de aserción (relativa 1e-10, absoluta 1e-12). La tolerancia no agrupa scores
en empates ni permite diferencias de IDs/orden. Los cálculos de referencia
de 1A están en tests; el ranking de producción corresponde a la fase 3.

```text
tf_weight(tf) = 1 + ln(tf), si tf > 0; 0 en otro caso
idf(t) = ln((N + 1) / (df(t) + 1)) + 1
w(t,d) = tf_weight(tf(t,d)) × idf(t)
w(t,q) = tf_weight(tf(t,q)) × idf(t)
score(d,q) = sum_t[w(t,d) × w(t,q)] / (norm(d) × norm(q))
```

La norma documental usa todo su vector, no únicamente los términos consultados. La consulta se proyecta al vocabulario del corpus. Norma nula implica score cero y no genera una coincidencia artificial.

### 4.3 BM25

```text
idf_BM25(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
score(d,q) = sum_t idf_BM25(t) ×
             [tf(t,d) × (k1 + 1)] /
             [tf(t,d) + k1 × (1 - b + b × len(d)/avgdl)]
```

Usar `k1 = 1.2` y `b = 0.75`, fijos y registrados. Sumar una vez por término distinto de consulta, sin componente adicional de frecuencia de consulta. No realizar una búsqueda de hiperparámetros: no la exige el proyecto. Tratar explícitamente corpus vacío y `avgdl = 0`.

Ambos métodos recorren la unión de postings consultados. Una acumulación de scores por documento candidato es suficiente para 100 000 documentos, siempre que se mida su memoria. Resolver primero el orden total de §3.3. Solo con LIMIT k y orden score DESC/id ASC, usar un heap de tamaño k; para relevancia ASC u orden por ID, ordenar todas las coincidencias antes de LIMIT. Sin LIMIT, ordenar todas las coincidencias según la solicitud. No presentar el heap como un límite de toda la memoria: el acumulador de candidatos sigue existiendo.

## 5. Integración en el repositorio

Las siguientes rutas nuevas son propuestas, no archivos existentes. Mantener pocos módulos y separarlos solo por responsabilidad real.

| Ubicación | Trabajo |
|---|---|
| `engine/text/` — nuevo | Tokenización, construcción SPIMI, lectura persistente y ranking |
| `engine/query/lexer.py`, `tokens.py`, `ast.py`, `parser.py` | MATCH, USING y SCORE sin reemplazar el parser manual |
| `engine/query/binder.py`, `planner.py`, `executor.py` | Validar campo/modelo, enlazar SCORE y ejecutar el acceso textual |
| `engine/operators/` | Operador textual siguiendo el ciclo open/next/close y los reportes existentes |
| `api/database.py` | Único owner de índices textuales para preparación, reapertura y UI; orquesta funciones del motor, registro de handles y cierre |
| `engine/text/` y `engine/query/environment.py` | Metadatos/lector del índice y registro prestado en QueryEnvironment; el registro no posee ni cierra handles |
| `engine/storage/organization.py`, `heap_file.py`, `engine/maintenance/service.py` | Política persistente de inmutabilidad y rechazo previo a toda mutación soportada |
| `engine/transactions/completion.py`, `session.py` y contrato del runtime | Comprobar la política de escritura antes de capturar undo en rutas SQL y programáticas; preservar rollback de cambios válidos anteriores |
| `engine/transactions/runtime.py` y adaptador utilizado por el owner | Conservar la política al reabrir handles; mantener el cierre y la vida útil de índices textuales |
| `api/__main__.py` | Selección explícita de la base textual mediante `--text`, usando el mismo owner y servicio HTTP |
| `api/` y `frontend/` | Reutilizar `/api/query`, resultados y plan; agregar ejemplos textuales |
| `scripts/setup_text.py` — nuevo | Preparar tablas con `api.database.Database`, construir/sellar/publicar mediante el motor y verificar una reapertura real |
| `benchmarks/text/` — nuevo | Adaptador PostgreSQL, matriz experimental, métricas y gráficos |
| `tests/` | Pruebas focalizadas del núcleo, SQL, persistencia e integración |
| `docs/text.md`, `docs/EXPERIMENTOS_TEXTO.md` — nuevos | Uso, decisiones y resultados; actualizar README |

### 5.1 Un único propietario para preparación, persistencia y frontend

**Decisión:** extender `api.database.Database`, utilizado actualmente por `scripts/setup_spatial.py` y `api/__main__.py`. `engine.database.Database` es un owner diferente, respaldado por un manifiesto; no es el que abre la base del frontend actual. No migrar la UI ni implementar el ciclo de vida textual en ambos owners en esta entrega. El owner alternativo debe rechazar una colección textual que no sabe administrar, en lugar de abrirla parcialmente o hacerla escribible.

Ruta concreta propuesta:

1. `scripts/setup_text.py` crea una base nueva con `api.database.Database.create(DatabaseDefinition("text"), directorio)` y tablas mediante el mecanismo persistente existente `create_gui_table`/`gui_tables.json`. Carga textos por flujo mientras aún están en preparación.
2. Una operación de publicación coordinada por ese mismo owner llama a constructores de `engine/text/`: construye los archivos, valida estadísticas y asociación tabla/columna/IDs y sella el Heap según §5.2. Escribe **al final** un registro textual versionado, propuesto como `text_tables.json`, con el estado publicado y las referencias necesarias. El formato y validación pertenecen al motor; `api/database.py` solo orquesta. No introducir SQL CREATE INDEX.
3. Cierra la base de preparación. El script abre de nuevo con `api.database.Database.open(DatabaseDefinition("text"), directorio)` y valida una consulta conocida. No reutiliza handles, objetos ni definiciones guardados en memoria por la carga.
4. Al abrir, el owner valida el registro textual, abre los Heap sellados y los lectores del índice, y los conserva en un registro de recursos propio, propuesto como `_text_indexes`. Los registra como referencias prestadas en `QueryEnvironment` mediante una extensión textual, utilizada por el binder y los operadores. Un archivo requerido ausente, un sello ausente o una asociación inconsistente causa error antes de atender consultas; no reconstruir índices silenciosamente al abrir.
5. `python -m api --text --data-dir <directorio>` — opción por implementar y excluyente con `--spatial` — abre **ese mismo owner**, lo entrega al `EngineService` actual y conserva `/api/query` y las sesiones existentes. `describe_table` incorpora los resúmenes de índices textuales para el panel de archivos. Todas las fábricas de `SqlEngine` de las sesiones comparten las mismas referencias y políticas.
6. En cierre normal o fallo de apertura: detener/cancelar consultas y cerrar sesiones; después cerrar todos los lectores textuales, los demás índices, los Heap y finalmente liberar el directorio. Ampliar `_close_handles()` para incluir los handles textuales, sin duplicar su propiedad. `QueryEnvironment` y los operadores no cierran los handles permanentes que toman prestados.

Criterio de aceptación: preparar → cerrar → abrir un proceso servidor nuevo → consultar por UI → cerrar libera todos los recursos y conserva scores, documentos y política de escritura. También probar apertura parcial fallida sin fuga de handles. El uso de `api.database.Database` como owner no mueve SPIMI, ranking ni validaciones del almacenamiento a la capa HTTP.

### 5.2 Inmutabilidad persistente dentro del motor

**Invariante:** una colección publicada no admite cambios por ninguna ruta de mutación soportada, incluso con `--allow-writes`, llamadas Python directas o después de reabrirla. Una comprobación del endpoint o del parser es insuficiente.

Solución acotada propuesta:

- Añadir a los metadatos persistentes del archivo organizado un estado de escritura/sello, interpretado por `engine/storage/`. Versionar el formato: los archivos anteriores siguen siendo mutables al abrirse con el motor nuevo; los archivos sellados usan la versión nueva. Un binario anterior debe rechazarlos por versión desconocida, no ignorar el sello. No reescribir automáticamente las bases relacionales existentes.
- Durante preparación, el Heap nuevo es mutable. Tras terminar y validar el índice, persistir el sello mediante una operación de publicación del motor, actualizar el handle vivo y cerrar los handles de construcción. Publicar el registro final solo después. No exponer una operación normal para quitar el sello; reconstruir significa crear otra colección en otro directorio.
- El guard del almacenamiento debe ejecutarse **antes de escribir páginas, modificar contadores o cambiar índices**. `HeapFile.insert/delete` lo aplican incluso cuando se invocan directamente. `HeapFile.open` lo restaura desde el propio archivo, sin depender de que el llamador sea el owner HTTP ni de un argumento opcional `read_only=True`.
- **Rechazo anterior a undo:** el flujo actual de `SqlSession` llama a `prepare_write()` antes de ejecutar INSERT/DELETE; los caminos programáticos también pasan por esa preparación. Extender el contrato del runtime para comprobar la política persistente y efectuar la comprobación dentro de la preparación de escritura, bajo los locks correspondientes, antes de flush/captura de undo y de registrar la tabla como modificada. Auditar todos sus llamadores, incluidos hooks programáticos. Los guards de `MutationService` y Heap se conservan para accesos directos; por sí solos llegan demasiado tarde en una sesión coordinada.
- `MutationService.insert/delete` comprueban la misma propiedad antes de cualquier efecto. Esto es necesario porque un borrado puede tocar un índice antes de llamar al Heap. La política también debe verificarse antes de callbacks de mantenimiento, importación o sustitución de una tabla existente. Los scripts de preparación solo crean destinos nuevos; no ofrecen un bypass para sobrescribir una colección publicada.
- Auditar y enumerar las rutas públicas soportadas de mutación de colecciones: sesiones SQL, SqlEngine directo, servicios de mantenimiento, importadores/operaciones del owner y handles de almacenamiento. Los handles de páginas o índices que puedan modificar una colección gestionada deben quedar protegidos por el mismo control o no exponerse como acceso mutable soportado. No dejar un camino público de escritura que omita el guard. Esto no pretende impedir manipulación externa arbitraria de los bytes del archivo.
- La reapertura completa y cualquier reapertura interna de `TableRuntime` deben conservar el sello antes de registrar el handle. La publicación ocurre offline, sin sesiones de usuario ni transacciones que puedan restaurar una versión anterior mutable. Una operación rechazada no debe crear una imagen undo de la colección sellada ni provocar su restauración física, reparación o reconstrucción de índices. Si una transacción explícita ya modificó otras tablas mutables, conservar la política de aborto existente y restaurar esos cambios anteriores; el rechazo no debe desactivar el rollback legítimo de otras tablas.
- Abrir una colección marcada como publicada con Heap mutable, registro inválido o componentes faltantes debe fallar de forma cerrada. Las tablas ordinarias no selladas conservan sus operaciones actuales.

Prueba de aceptación: para cada ruta soportada, intentar insertar y borrar antes y después de cerrar/reabrir en otro proceso, incluida apertura directa de `HeapFile` y acceso desde `QueryEnvironment.storage_for`. Esperar el mismo error de solo lectura, comprobar que conteos y hashes de datos/índices no cambian, y ejecutar una búsqueda posterior con los mismos resultados. Instrumentar captura/restauración de undo y reconstrucción de índices: ninguna debe ejecutarse para la tabla sellada por la escritura rechazada. Probar además una transacción que modifica una tabla mutable y después intenta escribir en la sellada: el primer cambio se revierte conforme al contrato existente y la colección sellada permanece intacta. Repetir con `--allow-writes` y comprobar que una tabla relacional ordinaria sí se puede modificar. Registrar la matriz de rutas auditadas: no basta una prueba HTTP.

### 5.3 Planes y acceso secuencial

El plan debe describir el operador realmente ejecutado, el modelo, el índice y las estadísticas disponibles. Basta registrar términos consultados, candidatos puntuados, filas entregadas y tiempo. Reutilizar cancelación, cierre de recursos y locks de lectura existentes. No crear un gestor de sesiones paralelo.

El selector actual «Usar índices» debe tener semántica honesta. Reutilizar el evaluador exhaustivo como ruta `TextScan` cuando esté desactivado: usar las mismas estadísticas del corpus y las mismas fórmulas; cambiar únicamente el acceso a candidatos. Así se verifica equivalencia sin añadir una cuarta técnica a la matriz académica. No etiquetar una consulta como scan si sigue recorriendo postings para encontrar candidatos.

## 6. Experimento reproducible

### 6.1 Corpus y consultas congelados

La puerta §3.1.1 está en PASS y los subconjuntos anidados de **1 000, 10 000 y 100 000** documentos están congelados con semilla **20261024**; manifiestos y hashes en BLOQUE_1B.md. Para futuras reconstrucciones, exigir de nuevo el PASS antes de adoptarlas. Incluir desde el subconjunto pequeño los documentos con juicio positivo de las consultas elegidas y completar con distractores seleccionados mediante semilla fija. Registrar este sesgo: se mide un corpus seleccionado, no el benchmark oficial completo.

Propuesta manejable: **30 consultas**, 10 por longitud (1, 3 y 5+ palabras), reutilizadas en los tres tamaños. El PDF no exige una cantidad de consultas ni repeticiones para Parte 3; esta es una decisión metodológica. Verificar en la primera fase que existan consultas originales suficientes con juicios. No acortar preguntas originales y conservar sus etiquetas sin revalidación.

Medir longitud tras tokenización y guardar también el texto original. Congelar los archivos de consultas, documentos y juicios antes de medir; no seleccionar consultas según qué modelo resulte ganador.

### 6.2 Relevancia

Usar juicios independientes del motor (`qrels`: consulta, documento y relevancia). Para el subconjunto D:

```text
R(q,D) = documentos con juicio positivo para q que pertenecen a D
Precision@10 = positivos presentes en los primeros 10 / 10
Recall@10 = positivos presentes en los primeros 10 / |R(q,D)|
```

Si se devuelven menos de 10 documentos, Precision@10 conserva denominador 10. Evitar consultas sin positivos en D; si ocurren, reportarlas como no evaluables para recall y contabilizarlas, sin inventar un cero. Calcular promedio por consulta, longitud, tamaño y método.

El candidato ESCI tiene juicios limitados por consulta: un producto no juzgado puede ser relevante. La regla congelada I/C/S/E → 0/1/2/3 considera positivos los grados >0, sobre títulos íntegros y juicios de producto. Reportar **Precision@10 y Recall@10 respecto de los juicios disponibles**, con esta limitación y el campo textual elegido visibles. No interpretarlos como exhaustividad semántica absoluta ni convertir el top-10 de BM25 en verdad de referencia. Revisar manualmente algunos resultados para ilustrar errores, sin cambiar retroactivamente las etiquetas para favorecer un método.

### 6.3 Comparador PostgreSQL

GIN es una estructura de acceso, no una tercera fórmula de ranking. La etiqueta completa será **PostgreSQL FTS + GIN + ts_rank**.

Usar una tabla con los mismos IDs/textos y una columna `tsvector` indexada con GIN. Aplicar la misma normalización previa y una configuración simple, sin stemming. Comprobar que los lexemas y las coincidencias coinciden con el motor para los documentos aceptados; resolver las diferencias del parser de PostgreSQL antes de medir.

Construir la `tsquery` con OR entre los términos normalizados, de forma segura y parametrizada. No usar una conversión que introduzca AND mientras MINI-DBMS usa OR. Ordenar por `ts_rank` descendente e ID ascendente, con `LIMIT 10`. Fijar y registrar la normalización elegida para `ts_rank` y verificar el plan real con EXPLAIN ANALYZE.

El ranking nativo no equivale a BM25 ni al coseno propio; las diferencias de resultados son parte del experimento. Si PostgreSQL elige scan para alguna consulta, reportar ese plan. No afirmar que todas las consultas usaron GIN ni forzarlo silenciosamente.

### 6.4 Mediciones y límites

| Medida | Protocolo |
|---|---|
| Construcción | Cronometrar desde datos base cargados hasta índice consultable; incluir tokenización, estadísticas y normas en el motor; conversión a tsvector y creación GIN en PostgreSQL |
| Desglose de construcción | Conservar tiempos por etapa; SPIMI se comparte entre TF-IDF y BM25, por lo que no se suma ni presenta como dos índices independientes |
| Consulta | Una pasada de calentamiento y tres repeticiones medidas; orden alternado de métodos; registrar promedio y mediana |
| Frontera temporal | En el motor: consulta hasta obtener top-10 IDs/scores; en PostgreSQL: ejecución y lectura de esos mismos campos, indicando transporte local incluido. Excluir UI, gráficos y recuperación de textos completos de ambos |
| Relevancia | Calcular sobre IDs del ranking con los mismos qrels; no requiere recalcularse para cada repetición idéntica |
| Disco | Separar datos base, índice, estadísticas y temporales máximos. En PostgreSQL separar tabla/tsvector, GIN y otros índices |
| Memoria | Medir pico y base de RSS en construcción y consulta; distinguir proceso Python, cliente y backend PostgreSQL. No comparar solo la memoria del cliente PostgreSQL con todo el motor |
| Reproducibilidad | Guardar commit, versiones, SO, CPU/RAM, semilla, hashes, tokenización, presupuesto SPIMI y parámetros de ranking/PostgreSQL |

Con esta propuesta: 3 tamaños × 3 métodos × 30 consultas × 3 repeticiones = **810 ejecuciones cronometradas**, sin contar calentamiento ni construcción. No trasladar a esta parte las 5 400 consultas del experimento espacial.

Ejecutar cada medición de memoria en un proceso aislado cuando corresponda; registrar el alcance y las limitaciones de la herramienta usada en Windows. Si no puede medirse el backend PostgreSQL correctamente, marcar la cifra como no disponible y resolverlo antes del cierre experimental, sin sustituirla por memoria del cliente.

Guardar los resultados completos en CSV/JSON. Un timeout o fallo es una observación identificada, no un cero ni una fila descartada. No prometer que BM25 ganará en relevancia ni que el índice siempre será más rápido.

### 6.5 Entrega experimental mínima

Producir cuatro figuras legibles, cada una con paneles cuando haga falta:

1. Tiempo de construcción frente a número de documentos, con desglose compartido de SPIMI.
2. Tiempo de consulta frente a tamaño, separado por longitud de consulta.
3. Precision@10 y Recall@10 por método y tamaño, con detalle por longitud en los datos/tablas.
4. Memoria y espacio en disco, distinguiendo sus alcances.

Añadir una tabla de ventajas, desventajas y cuándo usar cada opción. Las recomendaciones deben derivarse de los resultados obtenidos y explicar el costo de saturación/longitud de BM25, la normalización vectorial de coseno y el contexto de ejecución de PostgreSQL, sin confundir estructura de índice con función de ranking.

## 7. Secuencia de implementación y condiciones de salida

Los bloques 1A y 1B están cerrados. La autorización posterior cubre **1B.5–1B.8**; el corpus real tiene PASS con evidencia, validación completa de Heap y reproducción en [BLOQUE_1B.md](BLOQUE_1B.md). Los bloques restantes se ejecutarán cuando se autoricen. Separar dos dependencias: los contratos y la fixture habilitan el desarrollo del núcleo y su integración; el PASS completo del corpus habilita su adopción y los experimentos finales.

| Fase | Trabajo concreto | Condición para continuar |
|---|---|---|
| 1A. Contratos y fixture — COMPLETADA 2026-10-24 | Semántica, tokenización, fórmulas y fixtures con respuestas verificables; evidencia en BLOQUE_1A.md | 390 tests focalizados aprobados en 1A; núcleo y ranking de producción siguen pendientes; aceptación real cerrada en 1B |
| 1B. Aceptación de datos — COMPLETADA 2026-10-24 | 1B.1–1B.8: fuentes verificadas, 30 consultas con 439 positivos, conjuntos anidados exactos y reproducción independiente | `corpus_feasibility.json` en PASS; 100 000 filas, IDs, textos y RID verificados tras reapertura real de Heap; 476 tests focalizados aprobados |
| 2. Núcleo SPIMI | Construcción por bloques con postings ordenados, mezcla, persistencia, léxico, estadísticas y lectura concurrente por offset | Igualdad con índice de referencia; IDs desordenados y duplicados; varios bloques/pasadas, reapertura y lectores intercalados |
| 3. Ranking | TF-IDF/coseno, BM25, órdenes de §3.3 y top-k condicionado al orden | Scores y filas correctos para DESC, ASC e ID; igualdad índice/scan y desempates |
| 4A. Política persistente de escritura | Sello y compatibilidad de formato; guards en almacenamiento/mantenimiento y rechazo antes de undo | Incremento validado por separado: archivos anteriores siguen funcionando, tablas selladas rechazan escrituras sin captura/restauración y el rollback de otras tablas se conserva |
| 4B. Integración textual | Owner `api.database.Database`, registro textual, parser/binder, operador y EXPLAIN; depende de 4A | Los dos SQL del PDF funcionan; reapertura real; matriz de escritura y dos sesiones lectoras verificadas |
| 5. API y demo | Consultas de ejemplo y uso de los paneles existentes | Búsqueda completa por UI; score/modelo/plan visibles; reapertura conserva resultados |
| 6. Comparación | Con fase 1B en PASS y motor integrado, preparar PostgreSQL, comprobar semántica, ejecutar la matriz y generar figuras | Resultados de tres métodos, tres tamaños y tres longitudes; métricas completas |
| 7. Cierre | Documentación, demo y regresión | Lista final aprobada con evidencia, sin resultados inventados ni pendientes ocultos |

No ampliar el alcance durante estas fases. Si aparece un impedimento técnico, elegir la solución más pequeña que preserve el requisito: por ejemplo, seleccionar documentos cortos válidos antes que rediseñar el almacenamiento general.

## 8. Pruebas necesarias

Concentrar las pruebas en riesgos reales y reutilizar fixtures:

- Tokenización idéntica en construcción y consulta: mayúsculas, Unicode, puntuación, repeticiones, vacío y términos desconocidos.
- SPIMI: IDs de entrada desordenados, término distribuido entre bloques, frecuencias correctas, postings ordenados, `df`, mezcla de varias pasadas y presupuesto pequeño forzado. Rechazar IDs duplicados dentro y entre bloques, incluidos documentos vacíos, sin publicar una colección parcial.
- Ranking y orden: scores manuales; normas y longitud en BM25; cada orden de §3.3, incluyendo `ORDER BY relevancia` (ASC implícito), ID no proyectado, empates, k=0, k mayor que candidatos y ausencia de LIMIT/coincidencias. Contrastar el heap permitido con ordenamiento exhaustivo e incluir el contraejemplo de tres IDs.
- Oráculo: ranking exhaustivo independiente frente al índice para ambos modelos, con tolerancia numérica declarada y desempate exacto.
- Persistencia y owner: cerrar y abrir en otro proceso mediante `api.database.Database` conserva metadatos, dimensiones, frecuencias, IDs, scores y documentos. Reconstruir un vector disperso conocido desde postings. Validar cierre de lectores antes que Heap y rechazo de construcción incompleta.
- Lectura concurrente: intercalar dos iteradores sobre un lector compartido con buffers pequeños y listas distintas/solapadas; comparar con el resultado serial. Repetir mediante dos sesiones y comprobar que cerrar/cancelar una consulta no invalida la otra (§4.1.1).
- Integración: dos consultas literales del PDF; alias de SCORE; EXPLAIN sin ejecutar y ANALYZE ejecutando; cierre/cancelación; error controlado para uso inválido.
- Coherencia: matriz de rutas de §5.2 — SQL/HTTP, sesiones, SqlEngine directo, MutationService, importación y Heap directo — antes/después de reapertura; rechazo previo a efectos con hashes y conteos intactos. Verificar ausencia de captura/restauración undo y reconstrucción para la tabla sellada, además del rollback correcto de cambios previos en otra tabla mutable. Incluir reapertura interna, compatibilidad de formato y conservación de escrituras relacionales ordinarias.
- Métricas: ejemplos pequeños conocidos para Precision@10/Recall@10, menos de diez resultados y cero positivos.
- Regresión: ejecutar la suite existente de Partes 1 y 2 y las comprobaciones de frontend pertinentes una vez integrada la entrega; repetir solo si se corrige un fallo.

La prueba a 100 000 documentos pertenece al experimento de aceptación, no a cada ejecución rápida de pruebas unitarias.

## 9. Demostración y definición de terminado

Demo breve de la Parte 3:

1. Mostrar la tabla textual y su índice construido con SPIMI.
2. Ejecutar una consulta TF-IDF y observar documentos, scores y plan.
3. Ejecutar el mismo texto con BM25; explicar una diferencia real o un empate, sin prometer un ganador.
4. Ejecutar ambas formas SQL del enunciado, incluida `SELECT *, SCORE()`.
5. Comparar índice y scan en la fixture y comprobar igualdad del resultado.
6. Mostrar que la colección vuelve a abrirse con los mismos resultados.
7. Presentar las gráficas y una conclusión con sus límites de evaluación.

Checklist de cierre:

- [ ] SPIMI propio con varios bloques reales y mezcla externa validada.
- [ ] Postings ordenados dentro de cada bloque y durante la mezcla, con entrada desordenada e IDs duplicados comprobados.
- [ ] Un índice persistente compartido por TF-IDF/coseno y BM25.
- [ ] Los dos ejemplos SQL del PDF funcionan en el motor y por la API.
- [ ] Resultados y planes visibles mediante el frontend existente.
- [ ] Owner único `api.database.Database` registra, abre y cierra índices textuales, integrado con la UI.
- [ ] Política de inmutabilidad persistida y aplicada dentro del motor en todas las rutas soportadas, antes y después de reabrir.
- [ ] Rechazo de escrituras selladas anterior a captura undo, sin restaurarlas ni reconstruir índices; rollback de otras tablas preservado.
- [ ] Lecturas concurrentes por offset verificadas sobre el mismo lector y mediante dos sesiones, sin interferencia de cursores ni cierre de handles prestados.
- [ ] LIMIT respeta todos los órdenes admitidos; heap de mayores scores solo en score DESC/id ASC.
- [ ] Puerta de viabilidad del corpus en PASS, con evidencia medida; MS MARCO no se da por aceptado de antemano.
- [ ] Corpus de 1 000, 10 000 y 100 000 documentos reales, con consultas de 1, 3 y 5+ palabras.
- [ ] Comparación con PostgreSQL GIN + ranking nativo, con semántica y fronteras temporales explícitas.
- [ ] Construcción, consulta, Precision@10, Recall@10, memoria y disco reportados.
- [ ] Datos crudos, configuración, gráficas y tabla de recomendaciones conservados.
- [ ] README, explicación de algoritmos, instrucciones reproducibles e informe incremental actualizados.
- [ ] Demo preparada para incorporarse al video general de 5–10 minutos exigido por el proyecto.
- [ ] Regresión de las funcionalidades existentes sin fallos atribuibles a esta extensión.

No se considera terminada la Parte 3 solamente porque devuelve resultados: también deben completarse la comparación experimental y sus evidencias.

## 10. Fuentes y trazabilidad

- **Fuente normativa:** `Proyecto_Final.pdf`, §2.3.1–2.3.3, páginas 3–4; §3, entregables; §4, calendario. No se encontró una rúbrica de puntajes dentro del PDF.
- **Base del código:** [README del commit revisado](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/85db1bec94e0515dfff621dfa1ae8dece4c6ca08/README.md).
- **Contrato SQL y límites existentes:** [docs/sql-grammar.md](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/85db1bec94e0515dfff621dfa1ae8dece4c6ca08/docs/sql-grammar.md).
- **Owner y preparación existentes:** [api/database.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/85db1bec94e0515dfff621dfa1ae8dece4c6ca08/api/database.py), [scripts/setup_spatial.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/85db1bec94e0515dfff621dfa1ae8dece4c6ca08/scripts/setup_spatial.py) y [api/__main__.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/85db1bec94e0515dfff621dfa1ae8dece4c6ca08/api/__main__.py).
- **Guard y capacidad a extender:** [organization.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/85db1bec94e0515dfff621dfa1ae8dece4c6ca08/engine/storage/organization.py), [record_codec.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/85db1bec94e0515dfff621dfa1ae8dece4c6ca08/engine/storage/record_codec.py) y [maintenance/service.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/85db1bec94e0515dfff621dfa1ae8dece4c6ca08/engine/maintenance/service.py). El sello y las rutas textuales descritas son cambios propuestos.
- **Candidato inicial rechazado por longitudes:** [MS MARCO — datasets oficiales](https://microsoft.github.io/msmarco/Datasets.html); evidencia dev/train en BLOQUE_1B.md.
- **Alternativa preparada, pendiente de aceptación completa:** [Amazon ESCI — fuente oficial](https://github.com/amazon-science/esci-data/tree/7916cdf6ab75a462e77f20ab40428a10923998d5), large_version/test/us, títulos íntegros y juicios originales. Campo elegido, mapeos y límites en [text-corpus-preparation.md](../docs/text-corpus-preparation.md).
- **Comparador:** [PostgreSQL: control de búsqueda textual](https://www.postgresql.org/docs/17/textsearch-controls.html) y [tipos de índices textuales](https://www.postgresql.org/docs/17/textsearch-indexes.html). Registrar la versión realmente instalada al ejecutar el experimento.

Las fórmulas, los 30 casos de consulta, las tres repeticiones, el corpus candidato sujeto a aceptación y el modo de publicación por lotes son decisiones explícitas de este plan; no se atribuyen como requisitos adicionales al enunciado.
