# Auditoría técnica independiente de MINI-DBSM

Fecha: 2026-10-04. Fuente académica: [Proyecto_Final.pdf](../../Proyecto_Final.pdf), siete páginas. Base inspeccionada: commit fabe4cca7e06afaeae06b731f35a0b8259600696. Alcance: las cinco partes y los entregables, aunque la implementación activa se concentre en las Partes 1 y 2.

## 1. Dictamen

El proyecto tiene un motor relacional propio, integrado y extensamente probado. No alcanza todavía la entrega multimodal completa. El cumplimiento verificado es **48,48 % global** y **46,48 % funcional**; la cobertura implementada es 49,35 % y 46,95 %, respectivamente. Estos porcentajes corresponden a requisitos atómicos de esta auditoría, no a una calificación oficial ni a una estimación de horas restantes.

La Parte 1 alcanza **98,77 %**: 26 requisitos completos y uno incorrecto bajo la lectura literal de orden de llegada del Heap. La reproducción usa tres inserciones sin borrados y obtiene orden físico 1,3,2. La suite existente no detecta este caso. No se observó pérdida de filas ni incoherencia de índices en las verificaciones ejecutadas.

La Parte 2 alcanza **42,22 %**. R-Tree, radio, k-NN, polígonos y ambas distancias funcionan en el dominio geográfico declarado. Una prueba adicional con 100.000 filas reales aprobó 38/38 comprobaciones, incluida reapertura. Faltan SQL espacial, mapa y la comparación experimental completa con GiST. Las Partes 3, 4 y 5 tienen **0 %**: se comprobó ausencia de implementación, no simplemente ausencia de tests.

Se reprodujeron los tres fallos del comprobador HTTP: dos terminaciones con estado -2 tras Ctrl+C y una demora de 62 segundos para que la comprobación de puerto permita relanzar. Son defectos operativos del lanzador; commit, rollback, bloqueos y reapertura funcional aprobaron. Se propone corregirlos sin modificar el ciclo de transacciones.

La arquitectura permite continuar de forma localizada. No hay motivo acreditado para sustituir el almacenamiento, el B+ o el parser por una biblioteca o DBMS externo. PostgreSQL aparece solamente como comparador exigido para los experimentos futuros.

## 2. Fuente, alcance e interpretaciones

El PDF define todas las obligaciones. REQUIREMENTS.md, AGENTS.md, planes, comentarios, auditorías de etapas y experimentos anteriores se usaron como referencias contrastables; no incorporan requisitos académicos nuevos. Esta elección sigue la instrucción expresa del usuario, aunque AGENTS.md coloque REQUIREMENTS.md antes del PDF. No se modificó ninguno de esos documentos.

El catálogo [REQUISITOS_FIJADOS.json](evidencias/REQUISITOS_FIJADOS.json) contiene **77 requisitos y 220 criterios**. Se fijó antes de asignar puntuaciones. Parte → Etapa → Paso organiza la auditoría; las etapas son agrupaciones, no obligaciones adicionales. Los criterios de persistencia, exactitud o integración son comprobaciones operativas del requisito correspondiente, no funcionalidades extra.

Decisiones de lectura que afectan la evaluación:

- Heap: el PDF pide almacenar en orden de llegada y reutilizar espacio. Se comprueba llegada en una carga inicial sin borrados, evitando imponer orden a SELECT sin ORDER BY o exigir simultáneamente orden físico cronológico después de reutilizar huecos. Si el docente aclara que llegada significa exclusivamente ausencia de ordenamiento por clave, cambia un solo criterio: +0,43 puntos globales y +1,23 puntos de Parte 1. Hasta entonces se conserva la lectura literal y la evidencia contraria.
- El 30 % de desperdicio es un ejemplo. No se convierte en umbral obligatorio.
- GROUP BY y JOIN pueden usar hashing externo **o** uso estratégico de índices. No se exigen ambas alternativas por duplicado.
- El parser puede ser limitado. No se exigen todo SQL, NULL general, UPDATE, MVCC, WAL, recuperación automática tras crash ni optimizador por costes. ROLLBACK se verifica como funcionalidad implementada, sin añadir un requisito atómico extra.
- El PDF prescribe 1.000/10.000/100.000 para archivos de Parte 1. El párrafo de índices pide comparación y carga frecuente, pero no repite expresamente esos tamaños. La carga agrupada incompleta en 100k limita las conclusiones de ese tamaño; no invalida el requisito mínimo satisfecho en tamaños menores.
- Parte 2 exige ambas distancias y consultas geográficas, pero no cobertura mundial, un R-Tree paginado ni una proyección geodésica concreta. Se explicita el dominio local implementado y sus unidades.
- Parte 4 exige SIFT para imágenes y MFCC para audio, IVF y HNSW, y las tres métricas. K-Means **o** Tree Quantization es una alternativa. No se exige duplicar las dos cuantizaciones.
- El Anexo A exige escoger **una** aplicación. No hay elección acreditada; se evalúan los requisitos comunes y se registra esa decisión pendiente. No se exige implementar las cuatro opciones. Los embeddings opcionales de RAG o los embeddings preentrenados de reconocimiento facial no reemplazan las obligaciones separadas de Parte 4.
- El empleo futuro de bibliotecas para SIFT/MFCC debe respetar la implementación educativa. El PDF no define expresamente hasta qué nivel se permite delegar esa extracción; dejar constancia de la decisión antes de adoptar una dependencia que sustituya el algoritmo. No afecta ninguna implementación actual.

El calendario del PDF es una referencia de entregas, no otro denominador de funcionalidades. El informe incremental se evalúa para las partes ya desarrolladas; el video y la exposición final no se dan por realizados a partir de sus guiones.

## 3. Entorno y verificación ejecutada

El remoto origin es https://github.com/Base-de-Datos-2/MINI-DBMS. La consulta remota de HEAD/main coincidió con el commit local indicado. Al comenzar había un DOCX versionado eliminado y dos archivos no versionados: Proyecto_Final.docx y Proyecto_Final.pdf. Se preservaron. No se alteró código, tests existentes, planes ni documentación anterior.

La regresión se ejecutó sobre una copia de git archive del commit en WSL Ubuntu, en /local-user/.cache/minidbms-audit-20261004/source, con bases separadas para HTTP, navegador y espacial. Los archivos de pytest, compilación y dependencias quedaron en esa copia y su entorno aislado. La reproducción del Heap también se ejecutó en Windows con un TemporaryDirectory. No se usó la base demo del usuario.

Entorno efectivo: Python 3.11.9; pytest 8.4.2; FastAPI 0.142.2; Starlette 1.7.0; Uvicorn 0.54.0; httpx2 2.13.1; AnyIO 4.14.2; Matplotlib 3.11.2; Playwright 1.63.0; Node 18.20.5; npm 10.8.2. El lock de frontend fija Vite 6.4.3 y Vitest 3.2.7. La instalación siguió pyproject.toml y package-lock.json. Las dependencias del navegador ausentes se extrajeron en un directorio privado; no se instaló software global.

| Verificación actual | Resultado | Evidencia |
|---|---|---|
| Python, suite completa, warnings como errores | 2.968 aprobadas; 0 fallos, 0 omitidas; 136,49 s | pytest.log y pytest.xml |
| Comprobación de tipos de frontend | Aprobada | frontend_typecheck.log |
| Tests de frontend | 32/32 | frontend_tests.log |
| Compilación de frontend | Aprobada | frontend_build.log |
| Demo real de hilos | Sin protección: 1; protegido: 2; serial: 2 | demo_threads.json |
| Servidor HTTP, sesiones y reinicio | 22/25; los tres fallos son operativos y se detallan abajo | integracion_http.json y .log |
| Chromium real, dos páginas/sesiones | 11/11; sin errores JS | navegador.json, navegador.png y navegador_dom.html |
| Espacial con Heap real de 100.000 filas | 38/38, incluida reapertura | espacial_100k_real.json y .log |
| Heap con filas de tamaño variable | Defecto reproducido antes/después de abrir | heap_orden_llegada.json |
| Reconstrucción de tablas y gráficos de experimentos | Tablas idénticas, 111 líneas; 11 PNG generados | reporte_contrastado.json y reporte_regenerado/ |
| Repetición diagnóstica del benchmark actual, 1k | 35 mediciones; no reemplaza los ensayos oficiales | repeticion_1k.jsonl |
| Imports explícitos de engine, AST | 102 módulos, grafo acíclico; sin biblioteca sustitutiva | arquitectura.json e inventario_codigo.json |

Las pruebas HTTP comprobaron consultas indexadas y scan con iguales resultados y planes diferentes; ORDER/GROUP/JOIN reales; errores sintácticos y semánticos con recuperación; importación de 500 filas a Heap y secuencial; índices B+/hash; dos sesiones con espera de 1,5 s; commit, rollback y reapertura con solo cambios confirmados. Chromium comprobó esos flujos visibles, el estado de bloqueo y los cuatro paneles. La captura se inspeccionó visualmente: resultados, esquema y plan legibles sin superposiciones.

Las 38 comprobaciones espaciales incluyen 36 combinaciones de tres centros, dos métricas, radios 1/5/10 km y k 10/50/100, más polígono y reapertura. La referencia exhaustiva usa matemática independiente: Haversine mediante ángulo de vectores unitarios (atan2 de producto cruzado/producto punto), proyección euclidiana reimplementada y un polígono cóncavo con prueba propia de pertenencia. El R-Tree quedó con altura 5, 9.738 nodos y 8.874 hojas. Este ensayo funcional **no es** la comparación de 100 consultas promedio contra GiST exigida por el PDF.

Los ejemplos espaciales, textuales y multimedia del PDF se probaron por el parser público. Seis consultas fueron rechazadas: no existen sus funciones/operadores; LIMIT está reconocido como no soportado. La variante SELECT *, SCORE también necesita ampliar la lista de proyección. No se otorgó crédito por palabras presentes solamente en planes.

### 3.1 Qué prueban los tests y qué omiten

La suite tiene oráculos independientes para sorting (sorted), agrupación (diccionario), joins (bucles/multiconjuntos, preservando duplicados), B+/hash (mapas y comparación tras reapertura) y almacenamiento (filas/RIDs/conteos/archivos). Las pruebas de operadores y SQL fuerzan presupuestos pequeños, runs, particiones y fallos con limpieza. Las pruebas de transacciones usan schedules controlados, eventos y conflictos reales; una demo observacional por sí sola no reemplaza esos tests.

Se revisaron divisiones internas/de hoja/raíz, reutilización, borrado, reorganización, cambios de RID, duplicados, colisiones, procesamiento externo, fallos inyectados y reapertura. Los detalles y archivos de cobertura por requisito están en la sección 8. Los tests no solo importan clases: comparan resultados, asociaciones y estados persistentes.

Persisten límites del alcance de los oráculos:

- HeapFreeSpaceTracker tiene un test que exige elegir la página apta de menor identificador. Confirma la implementación, pero no la contrasta con llegada de filas de tamaños diferentes. El nuevo caso demuestra esa omisión.
- Algunas referencias espaciales de la suite comparten distance/geometry con el índice: pueden coincidir ante un mismo error matemático. La referencia independiente adicional reduce ese riesgo; no prueba geometría mundial fuera del dominio admitido.
- Vitest valida principalmente helpers/contratos. No acredita por sí solo el render completo, foco, bloqueo entre pestañas o comunicación HTTP. La prueba actual de navegador complementa ese hueco.
- Las pruebas del lanzador no cubren de extremo a extremo SIGINT y puerto en TIME_WAIT. Su aprobación no invalida los tres fallos reales observados.
- Los tests de benchmarks son pequeños y comprueban formatos/rutas. No acreditan que una carga de 100k contenga borrados ni que varias estructuras reciban el mismo número de mutaciones.
- La inspección AST detecta ciclos de imports explícitos, no todos los ciclos posibles de objetos en ejecución. Las pruebas de integración comprueban el ensamblaje actual.

### 3.2 Evidencia histórica, repetición y ausencia de comprobación

Los conteos y tiempos publicados de auditorías anteriores son históricos. No sustituyen los resultados actuales de esta auditoría. Los 455 registros JSONL oficiales de Parte 1 sí se inspeccionaron: 143 de archivos y 312 de índices. Hay 175 registros de 1k, 175 de 10k y 105 de 100k, con cinco repeticiones en los dos primeros tamaños y tres en el mayor. Se revisaron unidades en segundos/bytes, semillas, consultas/selectividades, configuración, tiempos finitos, números de operaciones y correspondencia con tablas/gráficos.

La huella de código registrada para 100k, 1697f753539b46be8e89bdf73f3b82ad4a209d84d13973d9c0f7ee5c52c28dab, coincide con los blobs engine/benchmarks del commit 075eae correspondiente, usando el mismo orden de hashing del harness. La huella del HEAD actual es d74b979ff2bc31415202f5246dfc34a878118bf5fa95cd0ae2cadcd819376378. Esto permite distinguir revisiones diferentes en vez de atribuir todos los ensayos al HEAD actual.

Los ensayos 1k/10k registran commit 0deafe3 y árbol dirty, con una huella propia. El commit solo no permite reconstruir ese árbol no versionado; falta su snapshot exacto. Es una limitación de procedencia/reproducibilidad, **no prueba de fabricación**. Las medidas siguen siendo evidencia histórica registrada, con esa salvedad. Las afirmaciones causales sobre diferencias entre tamaños deben reconocer cambios de versión y de configuración.

En carga mixta, B+ agrupado hizo 35–37 operaciones por repetición a 1k y tres a 10k (dos inserciones/una eliminación). A 100k realizó **una inserción y cero eliminaciones** por repetición, en 373–432 s. Hash/no agrupado hicieron 200 operaciones (100/100). El presupuesto de 60 s se comprueba entre operaciones y no puede interrumpir una inserción larga. Por tanto, ops/s describe trabajo y mezcla diferentes: a 100k no es evidencia de eliminación frecuente del agrupado. El mínimo de comparación de índices existe en los tamaños menores; se clasifica la ampliación como mejora experimental, sin inventar un requisito para los tres tamaños.

Se regeneraron las tablas desde los JSONL oficiales y se verificó igualdad exacta. Se inspeccionó el gráfico de carga mixta; necesita una nota explícita de mezcla/número de operaciones en 100k. La repetición nueva 1k usa el código actual, una repetición y presupuesto corto. Coincidió temporalmente con el ensayo espacial, por lo que se utiliza solo como prueba diagnóstica de rutas y formatos; no se compara su latencia con resultados oficiales ni se calculan intervalos de confianza.

No se ejecutaron comparaciones PostgreSQL/GiST/GIN ni benchmarks completos de Partes 2–4. Sí existe preparación espacial: benchmarks/spatial/postgres.py genera/importa datos, crea GiST y registra EXPLAIN; spatial_e1_setup.json y sus logs son históricos. No hay un harness de comparación completa con 100 consultas por caso, ni comparadores textuales/multimedia. La consulta actual docker ps falló por daemon no disponible; no se pudo contrastar el contenedor histórico ni acreditar PostGIS actual. Falta esa evidencia; no se sustituyó por resultados de otra base. Tampoco se acreditaron un video existente fuera del repositorio, la selección de Anexo A o la exposición final. Los intentos de Chromium fallidos por bibliotecas del entorno quedaron registrados antes de resolverlos; no se consideran defectos del producto.

## 4. Porcentajes reproducibles

Cada requisito tiene peso 1. Sus n criterios reciben peso 1/n. Para un bloque con R requisitos:

~~~text
Cobertura implementada = 100/R * sum_i(sum_j I_ij / n_i)
Cumplimiento verificado = 100/R * sum_i(sum_j V_ij / n_i)
Pendiente de validacion = 100/R * sum_i(sum_j P_ij / n_i)
~~~

I vale 1 cuando existe implementación real, aunque sea defectuosa; V vale 1 cuando se acredita conformidad; P vale 1 cuando existe implementación pero no está acreditada su conformidad. Se cumple V+P <= I. Un criterio defectuoso tiene I=1,V=0,P=0. Un artefacto externo de existencia desconocida tiene I=V=P=0 y estado NO VERIFICADO: P no mide toda incertidumbre posible, solo implementación existente pendiente de validación.

No se asigna 50 % automático a PARCIAL. El CSV guarda los criterios, sus tres listas de 0/1 y los nueve campos de cada paso. evaluar.py usa Fraction; PORCENTAJES.json conserva numeradores equivalentes exactos. El proyecto pesa 77 requisitos y el subtotal funcional 71. Los tests adicionales no amplían denominadores.

Estados: COMPLETO requiere todos los criterios satisfechos; PARCIAL conserva una parte acreditada; INCORRECTO tiene una implementación con incumplimiento demostrado; NO IMPLEMENTADO requiere ausencia comprobada; NO VERIFICADO conserva incertidumbre. Los estados son una síntesis; el cálculo siempre usa criterios.


| Bloque | Requisitos | Cobertura implementada | Cumplimiento verificado | Pendiente de validación |
|---|---:|---:|---:|---:|
| Parte 1: Relacional | 27 | 100.00 % | 98.77 % | 0.00 % |
| Parte 2: Espacial | 15 | 42.22 % | 42.22 % | 0.00 % |
| Parte 3: Texto | 10 | 0.00 % | 0.00 % | 0.00 % |
| Parte 4: Multimedia | 15 | 0.00 % | 0.00 % | 0.00 % |
| Parte 5: Aplicación | 4 | 0.00 % | 0.00 % | 0.00 % |
| Entregables transversales | 6 | 77.78 % | 72.22 % | 0.00 % |


### 4.1 Subtotal y global


| Bloque | Requisitos | Cobertura implementada | Cumplimiento verificado | Pendiente de validación |
|---|---:|---:|---:|---:|
| Subtotal funcional (Partes 1–5) | 71 | 46.95 % | 46.48 % | 0.00 % |
| Proyecto con entregables | 77 | 49.35 % | 48.48 % | 0.00 % |


### 4.2 Por etapa de auditoría


| Bloque | Requisitos | Cobertura implementada | Cumplimiento verificado | Pendiente de validación |
|---|---:|---:|---:|---:|
| 1.1: Archivos | 6 | 100.00 % | 94.44 % | 0.00 % |
| 1.2: Indices y algoritmos externos | 6 | 100.00 % | 100.00 % | 0.00 % |
| 1.3: SQL | 3 | 100.00 % | 100.00 % | 0.00 % |
| 1.4: Transacciones y concurrencia | 3 | 100.00 % | 100.00 % | 0.00 % |
| 1.5: Cuatro paneles | 4 | 100.00 % | 100.00 % | 0.00 % |
| 1.6: Experimentos | 5 | 100.00 % | 100.00 % | 0.00 % |
| 2.1: Nucleo espacial | 6 | 100.00 % | 100.00 % | 0.00 % |
| 2.2: Mapa | 2 | 0.00 % | 0.00 % | 0.00 % |
| 2.3: SQL espacial | 2 | 0.00 % | 0.00 % | 0.00 % |
| 2.4: Experimentos espaciales | 5 | 6.67 % | 6.67 % | 0.00 % |
| 3.1: Indice y ranking | 3 | 0.00 % | 0.00 % | 0.00 % |
| 3.2: Experimentos textuales | 6 | 0.00 % | 0.00 % | 0.00 % |
| 3.3: SQL textual | 1 | 0.00 % | 0.00 % | 0.00 % |
| 4.1: Extraccion y representacion | 4 | 0.00 % | 0.00 % | 0.00 % |
| 4.2: Indices y metricas | 5 | 0.00 % | 0.00 % | 0.00 % |
| 4.3: SQL multimedia | 1 | 0.00 % | 0.00 % | 0.00 % |
| 4.4: Experimentos multimedia | 5 | 0.00 % | 0.00 % | 0.00 % |
| 5.1: Aplicacion del Anexo A | 4 | 0.00 % | 0.00 % | 0.00 % |
| T.1: Entrega | 6 | 77.78 % | 72.22 % | 0.00 % |



El global verificado es (112/3)/77 = 48,484848... %. Son 35 pasos completos, tres parciales, uno incorrecto, 37 no implementados y uno no verificado. La cobertura es 38/77. El pendiente implementado sin validar es 0 % en esta fotografía: los criterios existentes pudieron comprobarse o demostrar su defecto. Eso no afirma certeza sobre entregables externos. Un video conforme y la acreditación final de la exposición sumarían como máximo 1,73 puntos globales; actualmente no se contabilizan. Los porcentajes deben recalcularse si aparece nueva evidencia o una aclaración docente.

## 5. Arquitectura, persistencia y extensibilidad

~~~mermaid
flowchart TD
  F[React: cuatro paneles] --> A[FastAPI: transporte y contratos]
  A --> S[SqlSession: transacciones y locks]
  S --> Q[Lexer / Parser / AST / Binder]
  Q --> P[Planner / PhysicalPlan]
  P --> O[Executor / operadores propios]
  O --> IX[B+ / Extendible Hash]
  O --> ST[Heap / Secuencial]
  IX --> ST
  ST --> PG[PageManager / codecs / disco]
  S --> M[Mantenimiento de indices / undo]
  M --> ST
  A -. propietario API: acceso programatico .-> SP[SpatialIndex / RTree]
  SP --> ST
  SP --> JS[Snapshot JSON propio]
~~~

La flecha programática espacial no representa una ruta SQL ni un endpoint de consultas espaciales existente. Ese ensamblaje todavía falta.

| Responsabilidad | Implementación y resultado | Implicación |
|---|---|---|
| Frontend/API | React consume contratos; FastAPI delega al motor. El navegador comprobó planes reales. | Reutilizar API y componentes para las extensiones. |
| SQL | Lexer/parser escritos a mano; AST y binding separados; planner selecciona scan, B+/hash y operadores externos. | Agregar funciones tipadas y acceso multimodal en estas capas, sin ejecutar consultas en el parser. |
| Operadores | ExternalSort, ExternalHashGroup, GraceHashJoin y rutas indexadas propios; presupuestos, temporales y cierre. | Reutilizar ExecutionContext, layouts y lifecycle. Los presupuestos no son RSS medido. |
| Almacenamiento/índices | Slotted pages de 4096 bytes, secuencial, B+ compartido, hash persistente. Mutaciones coordinan cambios de RID/rebuild. | Evitar reorganización cruda con índices activos. Mantener sus adaptadores. |
| Transacciones | S/X locks, latches, sesiones, undo físico acotado, publicación y cancelación. | Funciona entre sesiones del mismo propietario/proceso. Una instancia/worker por base. |
| Espacial | RTree propio con split cuadrático, MBR, radio, best-first k-NN y polígono exacto; snapshot checksum/fsync/replace. | El árbol reside en RAM; guardar todo tras mutación y reconstruir tras borrado tiene coste. No se exige paginación espacial por el PDF. |
| Composición | engine.database.Database y api.database.Database comparten piezas, pero ensamblan manifest/CREATE y definiciones demo/importación/espacial de formas diferentes. | Duplicación parcial del ownership. Antes de ampliar, reutilizar/extraer servicios concretos; no sustituir una clase sin revisar consumidores. |

Referencias principales: engine/transactions/session.py:280 y :851 (SqlSession y run_programmatic_read); engine/database/owner.py:51; api/database.py:185; engine/query/environment.py:44; engine/spatial/rtree.py:80, :212 y :282; engine/spatial/index.py:78. La matriz aporta símbolos y líneas específicas de cada operación. inventario_codigo.json conserva todos los símbolos, imports y huellas inspeccionados.

El núcleo no importa un DBMS/ORM ni bibliotecas sustitutivas de B+, hash, joins o sorting. El grafo de imports explícitos es acíclico. No se encontró dependencia de storage hacia frontend. PageManager no representa toda la E/S del proceso: manifests, snapshots espaciales y temporales también usan archivos. No presentar sus contadores como disco total.

Hay funciones largas (SqlSession.execute, 272 líneas; lexer, 182; una ruta de executor, 161). Su tamaño es una observación de mantenibilidad, no un defecto demostrado. La extracción futura debe seguir cambios concretos y tests de comportamiento; una reescritura general no está justificada.

El codec relacional admite INTEGER, FLOAT, BOOLEAN y VARCHAR. El payload máximo de una fila es **4079 bytes** (engine/storage/binary.py:41), incluidos los campos codificados. No insertar PDFs, descriptores ni vectores grandes como cadenas improvisadas. La extensión recomendada es identificar documentos/objetos en tablas y almacenar contenido/vectores en archivos auxiliares propios con formato, checksum y referencia estables. Integrar alta/baja/publicación con el mismo propietario y mantenimiento; prever undo o una política explícita de objetos inmutables. No crear motores paralelos ni cambiar el codec existente sin necesidad.

El dominio espacial publicado es Lima: latitud [-12.30,-11.80], longitud [-77.25,-76.75], origen (-12.0464,-77.0428). Euclidiana usa una proyección plana fija en metros y Haversine radio 6371008,771415059 m. El límite inferior de MBR Haversine utiliza solo latitud: es seguro, pero puede descartar pocos candidatos. En las consultas de la prueba se examinaron 3.287–39.134 candidatos Haversine y 70–13.119 euclidianos. Son conteos descriptivos, no una comparación de latencia ni prueba de optimalidad.

Undo tiene límites de 1 GiB por transacción y 2 GiB total; bloques de 1 MiB. No hay WAL, recuperación automática, locks entre procesos ni commit crash-atómico de varios archivos. Son límites declarados fuera del PDF actual. Reapertura limpia aprobada no equivale a resistencia a cortes de energía. El frontend/API validado se ejecuta desde la raíz del repositorio, como prescribe el manual; no se acredita un paquete redistribuible autosuficiente del API.

## 6. Hallazgos y acciones de aceptación

Se distinguen **defectos demostrados**, **brechas obligatorias**, **limitaciones** y **riesgos futuros**. Los dos primeros bloques fijan el trabajo necesario. Las mejoras no se convierten en obligaciones académicas.

### H1. CRÍTICA: llegada inicial del Heap

Tipo: defecto demostrado bajo lectura literal del PDF, p. 1 §2.1.1. Impacto: el almacenamiento inicial no cumple la política de llegada; no cambia la validez de SELECT sin ORDER BY y no se observó pérdida de datos.

Reproducción: esquema id INTEGER/value VARCHAR; insertar id 1 y 2 con textos de 3200 caracteres, luego id 3 con 100. RIDs: (1,0),(2,0),(1,1). Scan: [1,3,2] antes y después de abrir, sin borrados. Evidencia: heap_orden_llegada.json y probar_heap_llegada.py. Componentes: HeapFile.insert/scan y HeapFreeSpaceTracker; tests/storage/test_heap_free_space.py exige first-fit de menor página.

Corrección localizada: priorizar la página final para filas nuevas; distinguir huecos liberados por borrado de sobrantes nunca ocupados en páginas antiguas. Conservar codecs y RIDs. Revisar consumidores del tracker y mantenimiento de índices. No reordenar archivos existentes ni inferir cronología a partir de una clave cualquiera. Si se migra una carga antigua, recargar desde su fuente con orden original y reconstruir todos los índices.

Aceptación: regresión variable 3200/3200/100 produce colocación y scan 1,2,3 tras reapertura; los casos de borrado/reutilización siguen aprobando; B+/hash siguen coherentes. Si existe aclaración docente compatible con first-fit, registrarla y reevaluar el criterio en vez de introducir un cambio innecesario.

### H2. CRÍTICA operativa: salida y relanzamiento HTTP

Tipo: tres fallos reales del comprobador; no una inferencia del número de tests. Evidencia: integracion_http.json, dos salidas -2 y puerto no disponible para la sonda durante 62 s. navegador.json confirma salida -2 con todos los flujos de UI aprobados. Componentes: api/__main__.py:56 (sonda bind de puerto), main:64 y lifecycle de Uvicorn; scripts/integration_check.py:305. La limpieza de servidor/base llegó a finalizar; falló el estado de salida esperado.

Corrección localizada: manejar KeyboardInterrupt en el punto de entrada después de finalizar correctamente el cierre, conservando excepciones reales de cleanup. Ajustar la sonda al comportamiento del servidor en POSIX, usando reutilización de dirección para TIME_WAIT cuando corresponda y verificando un listener activo. No trasladar sin evaluación esa opción a Windows, donde pueden cambiar las condiciones de ocupación/compartición del puerto. No desactivar la protección contra otro servidor real.

Dependencias: ciclo de cierre/lease de base, plataforma del socket y CLI. Aceptación: dos ciclos reales arrancar–consultar–SIGINT–relanzar inmediatamente terminan con estado 0 sin traceback; un puerto con listener activo sigue rechazado; 25/25 del comprobador y navegador pasan; datos confirmados conservados, provisionales ausentes. No ampliar el admission guard de sesiones: los locks actuales ya coordinan sus conflictos.

### H3. IMPORTANTE: interfaz pública espacial pendiente

Tipo: brecha obligatoria, no defecto del R-Tree. El núcleo existe pero no tiene SQL espacial ni mapa. Componentes: lexer/parser/AST/binder/planner, QueryEnvironment, propietario API, contratos y frontend. Evidencia: filas 2.2 y 2.3 de la matriz, rechazo de ejemplos en espacial_100k_real.json e inventario de funciones.

Corrección: agregar POINT/distancia tipadas, acceso espacial con filtro geométrico residual exacto, orden por distancia y LIMIT real; reutilizar SpatialIndex y run_programmatic_read con locks/owner adecuados. Mostrar en el plan la ruta efectivamente usada. Agregar mapa de puntos y resultados resaltados con contratos del API. No ejecutar el R-Tree directamente desde React.

Dependencias: núcleo existente, binding de ubicación/columnas y contrato de resultado. Aceptación: ejemplos del PDF por API/UI, igualdad contra scan, ambas métricas, radio exacto y orden/k correctos con empates; errores recuperables; sesiones aisladas; reapertura; selección espacial visible en mapa y plan.

### H4. IMPORTANTE: comparación espacial ausente

Tipo: brecha obligatoria. Tener 100k puntos y diferencial correcto no satisface tiempos promedio de 100 consultas, GiST, memoria/disco y presentación. Componentes: benchmarks nuevos separados del motor y docs experimentales. Dependencias: núcleo; no requiere terminar el mapa para empezar a medir.

Corrección: scan/R-Tree/GiST con datos idénticos, 1k/10k/100k, radios 1/5/10 km, k 10/50/100 y 100 consultas equivalentes. Definir unidades, proyección, tratamiento de bordes/empates y semántica geodésica equivalente en PostgreSQL. Si una función de PostGIS usa elipsoide, no compararla como si fuera la esfera implementada sin ajustar o explicar diferencias. Acreditar el uso real de GiST con EXPLAIN, no solo CREATE INDEX.

Aceptación: resultados diferenciales idénticos dentro de tolerancia definida; configuración/versión/semillas/consultas archivadas; construcción, tiempos, memoria y bytes medidos; gráficas y tabla trazables a datos crudos. PostgreSQL permanece exclusivamente como comparador.

### H5. IMPORTANTE: documentación y entregables desalineados

Tipo: obligación parcialmente satisfecha y evidencia externa faltante. README contiene arquitectura/organización, pero enlaces antiguos a planes/etapas en raíz y omisiones de engine/database/espacial. PROJECT_CONTEXT.md conserva una frase de Stage 10 pendiente (línea 2616) junto a cierre reciente. No se encontró video ni enlace a un video; guion no acredita duración/funcionalidades. Hay material de exposición, no prueba de exposición final 15+5.

Corrección futura: actualizar solo referencias/estado que se contradicen, diagrama de propietarios y límites de persistencia; conectar README con rutas reales de PART_01 y PART_02. Conservar historial de cierres, explicitando qué fue revalidado. Producir o localizar video 5–10 min cuando esté el alcance final, y preparar/verificar exposición 15+5. No modificar esos archivos durante esta auditoría.

Aceptación: enlaces locales resuelven, instrucciones funcionan en entorno limpio, esquema representa componentes reales; video accesible y duración comprobada con demostraciones de todas las partes; presentación cubre el proyecto y reserva preguntas. Dependencias: cierre funcional de las partes para la entrega final.

### H6. IMPORTANTE: texto, multimedia y aplicación aún no implementados

Tipo: ausencias comprobadas, detalladas en los 29 pasos de Partes 3–5. No se atribuye al motor relacional una obligación de contener texto/multimedia antes de la solicitud de implementación; esta auditoría evalúa la entrega completa autorizada.

Corrección: construir persistencia auxiliar de documentos/objetos e identificadores; SPIMI con spill/merge propio, TF-IDF/coseno y BM25; SQL textual y GIN experimental; SIFT/MFCC, cuantización permitida, histogramas TF-IDF, IVF/HNSW propios y métricas; SQL multimedia y experimentos/galería. Elegir una opción del anexo e integrar dos tipos de datos mediante el API. No implementar cuatro aplicaciones ni sustituir los índices por PostgreSQL.

Dependencias y pruebas de aceptación individuales: sección 8. Las interfaces de identificadores/publicación deben resolverse antes de duplicar almacenamiento. La aplicación puede desarrollarse incrementalmente al disponer de sus modalidades.

### H7. MEJORA: fuerza de las conclusiones experimentales de Parte 1

Tipo: limitación, no nueva obligación. Evidencia: 455 medidas, snapshots de código distintos y carga mixta desigual. Corregir la interpretación de gráficas; el grouped 100k no demuestra borrados frecuentes. El presupuesto entre operaciones no es timeout estricto.

Mejora localizada: registrar snapshot exacto del árbol medido, incluida suciedad; separar costes de inserción y borrado; ejecutar un prefijo fijo compartido de mutaciones o presentar explícitamente mezclas y cantidades diferentes; registrar cumplimiento/rebase del presupuesto. Si se repite 100k, obtener al menos un borrado real del agrupado sin usarlo para fingir una mezcla extensa. No prometer una duración máxima que una operación indivisible puede exceder.

Aceptación: reconstrucción exacta de código/consulta/configuración; conteos por tipo de mutación visibles junto a ops/s; notas causales de cambio de versión; tablas/gráficas regenerables. Componentes: harness/reporte y documentación, sin sustitución de estructuras. Optimización del agrupado solo después de medir y revisar todos los consumidores de RID.

### H8. MEJORAS de mantenibilidad y rendimiento, con alcance limitado

Riesgos futuros: duplicación de propietarios al integrar nuevas modalidades; funciones largas; archivos auxiliares fuera del contador de PageManager; snapshots espaciales completos y rebuild en borrados; límite Haversine poco selectivo; lecturas individuales por RID en B+; panel de archivos que puede quedar desactualizado tras cambios de otra pestaña hasta recargar.

No se demostró incorrección por estas observaciones. Mantenerlas como mejoras. Extraer servicios compartidos concretos, reforzar métricas de E/S/RSS y refresh de UI cuando sus consumidores lo requieran. Aceptación: mismo contrato público/resultados y regresión relevante aprobada; mejora medida con workload equivalente. No emprender migración del motor completo sin un problema y un plan de compatibilidad acreditados.

## 7. Siguiente plan de trabajo

Este plan define correcciones recomendadas; no las implementa ni altera los planes anteriores. Cada paso remite a aceptación concreta de la sección 6 o de la matriz.

| Orden | Prioridad | Acción localizada | Dependencias | Cierre comprobable |
|---:|---|---|---|---|
| 1 | CRÍTICA | Resolver llegada inicial del Heap o acreditar aclaración docente | H1; tracker/RIDs | Criterio 1.1.2 y reutilización/reapertura |
| 2 | CRÍTICA operativa | SIGINT y relanzamiento de puerto | H2; lifecycle CLI | 25/25 HTTP, salida 0, relanzamiento y listener protegido |
| 3 | IMPORTANTE | Corregir referencias/estados documentales actuales | H5; arquitectura inspeccionada | README enlaza rutas reales y no afirma funciones ausentes |
| 4 | IMPORTANTE | Elegir una opción de Anexo A y fijar dominio | Paso 5.1.4 | Decisión acreditada, requisitos condicionales de una sola opción |
| 5 | IMPORTANTE | Spatial SQL, POINT/distancia, orden y LIMIT | H3; núcleo espacial, binder/planner/owner | Pasos 2.3.1–2 y diferencial por API |
| 6 | IMPORTANTE | Mapa interactivo y resultados resaltados | Contrato espacial/API | Pasos 2.2.1–2 en navegador real |
| 7 | IMPORTANTE | Harness scan/R-Tree/GiST y resultados completos | H4; puede avanzar antes del mapa | Pasos 2.4.1–5; 100 consultas y matriz prescrita |
| 8 | IMPORTANTE | Identificadores/documentos/objetos auxiliares propios | Owner/undo/manifest; dominio elegido | Alta/baja/reapertura/fallo sin objetos o referencias huérfanos |
| 9 | IMPORTANTE | SPIMI, TF-IDF/coseno, BM25 y SQL textual | Persistencia de documentos; parser/LIMIT | Pasos 3.1 y 3.3 con referencia independiente |
| 10 | IMPORTANTE | GIN, relevancia etiquetada y experimentos textuales | Ranking propio/dataset/qrels | Pasos 3.2; Precision@10/Recall@10 reproducibles |
| 11 | IMPORTANTE | SIFT/MFCC, vocabulario e histogramas TF-IDF | Objetos/dominio/decisión de dependencias | Pasos 4.1 con artefactos y semillas verificables |
| 12 | IMPORTANTE | Métricas, IVF/HNSW propios y SQL multimedia | Vectores/IDs/LIMIT/planner | Pasos 4.2–4.3, diferencial exacto y Recall@10 |
| 13 | IMPORTANTE | Experimentos multimedia y galeria | Datos/índices; consulta exacta | Pasos 4.4, casos reales de éxito/error |
| 14 | IMPORTANTE | Aplicación real con API y dos modalidades | Opción elegida/modalidades disponibles | Pasos 5.1; flujo completo de esa opción |
| 15 | IMPORTANTE | Consolidar informe, video y presentación | Alcance funcional final | T.1, video 5–10 y exposición 15+5 |
| 16 | MEJORA | Mejorar comparabilidad/snapshot de Parte 1 | H7 | Mezcla visible y datos crudos regenerables |
| 17 | MEJORA | Optimizar costes y extraer duplicación concreta | H8; mediciones/consumidores | Contratos conservados y beneficio medido |

No todas las filas son estrictamente secuenciales: los experimentos espaciales pueden avanzar con el acceso programático; la app puede consumir modalidades ya terminadas. Las dependencias protegen integración y persistencia, sin imponer una reescritura preventiva.

## 8. Evaluación completa: Parte → Etapa → Paso

Todos los pasos contienen los nueve campos solicitados. Las tablas de criterios exponen el cálculo: I = implementado, V = conforme verificado, P = implementado pendiente de validar. Un 0 en V no significa por sí solo ausencia: consultar el estado y los problemas. Los paths de código son relativos a la raíz del repositorio y las líneas pertenecen al commit/base inspeccionados.



### Parte 1: Relacional



#### Etapa 1.1: Archivos



##### Paso 1.1.1: Heap File en páginas de disco


**Requisito:** Heap File en páginas de disco. PDF, página(s) 1, sección 2.1.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** HeapFile codifica Record en slotted pages de 4096 bytes y mantiene metadatos persistentes.


**Evidencia:** engine/storage/heap_file.py:204 (def insert(); engine/storage/page_manager.py:72 (class PageManager); tests/storage/test_heap_persistence.py:1


**Evaluación:** Cumple almacenamiento propio en páginas y reapertura con gestores nuevos; las pruebas de persistencia y E/S pasan.


**Problemas:** No se reprodujo un defecto del requisito. No ofrece recuperación automática ante caída, que el PDF no exige.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Conservar PageManager, RecordCodec y la estructura paginada existente.


**Validación:** Insertar múltiples páginas, cerrar, abrir y comparar filas y RIDs; ver suite estricta y persistencia en procesos independientes.


**Dependencias:** Codecs y PageManager.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Registros codificados en páginas | 1 | 1 | 0 |
| Escritura y lectura de archivos reales | 1 | 1 | 0 |
| Reapertura conserva filas | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.1.2: Heap sin ordenamiento por clave y con inserción en orden de llegada


**Requisito:** Heap sin ordenamiento por clave y con inserción en orden de llegada. PDF, página(s) 1, sección 2.1.1.


**Estado:** ❌ INCORRECTO.


**Estado actual:** Inserta sin ordenar por clave; selecciona la primera página apta mediante HeapFreeSpaceTracker.


**Evidencia:** engine/storage/heap_file.py:204 (def insert(); engine/storage/heap_file.py:288 (def scan(); tests/storage/test_heap_free_space.py:54 (def test_tracker_chooses_lowest); docs/auditoria/evidencias/heap_orden_llegada.json


**Evaluación:** Bajo la lectura literal de almacenamiento en orden de llegada del PDF, la carga inicial ya falla con filas variables: entrada 1,2,3; páginas/RIDs y scan 1,3,2. Dos criterios de tres están satisfechos.


**Problemas:** Las filas de 3200,3200,100 bytes colocan la tercera en el hueco nunca ocupado de la primera página. No hubo borrados; reapertura conserva el mismo orden físico. Los tests validan first-fit sin contrastar este requisito.


**Corrección:** Priorizar la última página para carga nueva y distinguir huecos reutilizados tras borrado de espacio sobrante de páginas anteriores. Documentar la compatibilidad entre llegada inicial y reutilización posterior.


**Implementación recomendada:** Cambiar solo la selección de página en HeapFile.insert y su información de reutilización; conservar tracker, codecs y RIDs existentes. Aplicar la política a nuevas inserciones sin reordenar archivos antiguos; para corregir una carga antigua usar su fuente original y reconstruir índices.


**Validación:** Añadir regresión 3200/3200/100 sin borrados: colocación y scan físico 1,2,3 antes/después de abrir; mantener tests de reutilización real. No imponer ORDER BY a un SELECT sin orden explícito.


**Dependencias:** 1.1.1 y 1.1.3; revisar consumidores del tracker y adaptadores de índices. Si el docente interpreta llegada solo como ausencia de orden por clave, registrar esa aclaración y reevaluar este único criterio.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Inserción inicial conserva llegada | 1 | 0 | 0 |
| No ordena por clave | 1 | 1 | 0 |
| Política de reutilización explícita | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 66.67 %; pendiente 0.00 %.



##### Paso 1.1.3: Reutilización de espacio libre del Heap


**Requisito:** Reutilización de espacio libre del Heap. PDF, página(s) 1, sección 2.1.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** Actualiza espacio libre tras borrado; reutiliza slots, compacta cuando hace falta y reconstruye el directorio al abrir.


**Evidencia:** engine/storage/heap_file.py:174 (def _rebuild_free_space(); engine/storage/heap_file.py:274 (def delete(); tests/storage/test_heap_free_space.py:1


**Evaluación:** Las pruebas comprueban bytes recuperables y reutilización después de reapertura; los experimentos registran crecimiento real.


**Problemas:** El directorio es reconstruible en memoria; su reconstrucción lee las páginas. Es un coste de arranque, no incumplimiento.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Conservar el directorio reconstruible y las invariantes de slots.


**Validación:** Borrar registros, insertar tamaños que caben en huecos, verificar páginas no añadidas innecesariamente y repetir tras abrir.


**Dependencias:** 1.1.1.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Borrado libera espacio | 1 | 1 | 0 |
| Inserción reutiliza espacio | 1 | 1 | 0 |
| Reapertura reconstruye reutilización | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.1.4: Inserción ordenada en Archivo Secuencial Paginado


**Requisito:** Inserción ordenada en Archivo Secuencial Paginado. PDF, página(s) 1, sección 2.1.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** PagedSequentialFile busca página por clave, redistribuye/divide y desplaza el sufijo del archivo contiguo.


**Evidencia:** engine/storage/paged_sequential_file.py:400 (def insert(); tests/storage/test_paged_sequential_split.py:1; tests/storage/test_paged_sequential_binary_search.py:1


**Evaluación:** Inserción, orden con duplicados, divisiones y reapertura están verificados. La implementación es propia.


**Problemas:** Los desplazamientos pueden cambiar RIDs y aumentar el coste. Los adaptadores existentes reconstruyen índices para mantener corrección.


**Corrección:** No reemplazar el almacenamiento por este coste. Mejorar mantenimiento solo si la evidencia experimental justifica el cambio.


**Implementación recomendada:** Conservar la política actual; para optimización futura, publicar cambios de RID de forma explícita y actualizar todos los consumidores.


**Validación:** Cargar orden inverso y aleatorio; forzar divisiones de dos/tres páginas y comparar scan ordenado antes y después de abrir.


**Dependencias:** 1.1.1; comparador y codecs.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Entradas desordenadas quedan ordenadas | 1 | 1 | 0 |
| División multipágina conserva orden | 1 | 1 | 0 |
| Reapertura conserva orden | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.1.5: Eliminación lazy del secuencial


**Requisito:** Eliminación lazy del secuencial. PDF, página(s) 1, sección 2.1.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** La eliminación crea tombstones, ajusta conteos y excluye filas del scan sin compactación inmediata.


**Evidencia:** engine/storage/paged_sequential_file.py:538 (def delete(); tests/storage/test_paged_sequential_maintenance.py:1


**Evaluación:** El borrado es lazy y persistente, con recuperación posterior mediante reorganización.


**Problemas:** No se reprodujo un incumplimiento del requisito.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Conservar tombstones y validación de RIDs.


**Validación:** Comprobar filas excluidas, desperdicio conservado y reapertura antes de reorganizar.


**Dependencias:** 1.1.4.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Borrado lógico | 1 | 1 | 0 |
| Scan excluye eliminados | 1 | 1 | 0 |
| Persistencia de tombstones | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.1.6: Estrategia de reorganización del secuencial


**Requisito:** Estrategia de reorganización del secuencial. PDF, página(s) 1, sección 2.1.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** Mide desperdicio por bytes, aplica umbral y crea un reemplazo compacto validado con métricas.


**Evidencia:** engine/storage/paged_sequential_file.py:567 (def should_reorganize(); engine/storage/paged_sequential_file.py:626 (def reorganize(); engine/indexes/clustered_bplus.py:343 (def reorganize(); tests/storage/test_paged_sequential_maintenance.py:1


**Evaluación:** Hay una estrategia real de activación y reorganización. El 30% del PDF es un ejemplo, no una obligación universal.


**Problemas:** Mover registros exige reconstrucción de asociaciones. La ruta agrupada la coordina; no invocar reorganización cruda con índices activos sin mantenimiento.


**Corrección:** Ninguna corrección del algoritmo identificada; mantener las rutas públicas coordinadas.


**Implementación recomendada:** Conservar reemplazo validado y reconstrucción de índices afectados.


**Validación:** Borrar más del umbral, reorganizar, verificar igualdad de filas, menor desperdicio, índices y reapertura.


**Dependencias:** 1.1.4, 1.1.5 y mantenimiento de índices.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Criterio de activación documentado | 1 | 1 | 0 |
| Reorganización compacta | 1 | 1 | 0 |
| Filas e índices conservan coherencia | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



#### Etapa 1.2: Indices y algoritmos externos



##### Paso 1.2.1: Índice B+ agrupado


**Requisito:** Índice B+ agrupado. PDF, página(s) 1, sección 2.1.2.


**Estado:** ✅ COMPLETO.


**Estado actual:** ClusteredBPlusIndex asocia un B+ persistente propio a un secuencial físicamente ordenado por la misma clave.


**Evidencia:** engine/indexes/clustered_bplus.py:28 (class ClusteredBPlusIndex); engine/indexes/bplus_tree.py:780 (def insert(); tests/indexes/test_clustered_bplus.py:1


**Evaluación:** Cumple agrupamiento físico, búsquedas, mutación y persistencia. El PDF no exige almacenar las filas dentro de las hojas del B+.


**Problemas:** Reconstruye el índice en cada inserción; en 100k una inserción tarda 373–432 s en los resultados históricos. Las lecturas por RID tampoco agrupan páginas.


**Corrección:** Es una limitación de rendimiento, no una estructura conceptualmente inválida. Completar primero la medición de borrados; evitar reescritura sin necesidad.


**Implementación recomendada:** Mantener el adaptador. Como mejora, propagar cambios concretos de RID o agrupar mantenimiento de lotes con publicación segura.


**Validación:** Verificar igualdad/rango contra scan, divisiones/fusiones, inserción con RIDs movidos, reorganización y reapertura.


**Dependencias:** 1.1.4 y núcleo B+ compartido.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| B+ propio | 1 | 1 | 0 |
| Almacenamiento ordenado por clave indexada | 1 | 1 | 0 |
| Igualdad y rango correctos | 1 | 1 | 0 |
| Mantenimiento tras mutaciones | 1 | 1 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.2.2: Índice B+ no agrupado


**Requisito:** Índice B+ no agrupado. PDF, página(s) 1, sección 2.1.2.


**Estado:** ✅ COMPLETO.


**Estado actual:** UnclusteredBPlusIndex conserva asociaciones clave/RID hacia Heap independiente.


**Evidencia:** engine/indexes/unclustered_bplus.py:20 (class UnclusteredBPlusIndex); engine/indexes/bplus_tree.py:1583 (def range_entries(); tests/indexes/test_unclustered_bplus.py:1; tests/indexes/test_bplus_tree_delete.py:1


**Evaluación:** Igualdad, rango, splits, reparación de underflow, duplicados y reapertura tienen cobertura real.


**Problemas:** Leer una página por RID penaliza rangos amplios. No significa que el índice esté incorrecto.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Reutilizar el núcleo B+; una futura lectura por lotes puede agrupar RIDs por página sin perder el orden solicitado.


**Validación:** Comparar asociaciones con un mapa independiente y resultados de rango con un scan tras operaciones aleatorias y reinicios.


**Dependencias:** 1.1.1 y núcleo B+.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| B+ propio | 1 | 1 | 0 |
| RIDs hacia almacenamiento independiente | 1 | 1 | 0 |
| Igualdad y rango correctos | 1 | 1 | 0 |
| Mantenimiento tras mutaciones | 1 | 1 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.2.3: Hash dinámico extensible


**Requisito:** Hash dinámico extensible. PDF, página(s) 1, sección 2.1.2.


**Estado:** ✅ COMPLETO.


**Estado actual:** ExtendibleHashIndex tiene directorio paginado, profundidad global/local, split, duplicación y hash determinista.


**Evidencia:** engine/indexes/extendible_hash.py:74 (class ExtendibleHashIndex); tests/indexes/test_hash_restart_differential.py:1; tests/indexes/test_hash_growth_review.py:1


**Evaluación:** Cumple hashing extensible propio, búsquedas, colisiones, borrado y persistencia. Merge/shrink no son obligaciones explícitas del PDF.


**Problemas:** La profundidad tiene un límite y las colisiones no separables se rechazan de forma controlada. Los límites están cubiertos.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Mantener el directorio y validación existentes; no atribuirle capacidad de rango.


**Validación:** Forzar colisiones, split con/sin doubling, borrar asociaciones exactas y comparar con diccionario tras reapertura.


**Dependencias:** 1.1.1; codec determinista de claves.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Directorio y profundidades | 1 | 1 | 0 |
| Split y doubling | 1 | 1 | 0 |
| Igualdad y colisiones | 1 | 1 | 0 |
| Borrado y reapertura | 1 | 1 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.2.4: ORDER BY con External Sorting k-way merge


**Requisito:** ORDER BY con External Sorting k-way merge. PDF, página(s) 1, sección 2.1.2.


**Estado:** ✅ COMPLETO.


**Estado actual:** ExternalSort genera runs paginados y realiza merge k-way con heap, varias pasadas y presupuesto explícito.


**Evidencia:** engine/operators/sorting.py:406 (def _generate_runs(); engine/operators/sorting.py:446 (def _merge_rows(); engine/query/planner.py:33 (ExternalSort); tests/integration/test_stage6_differential.py:100 (def test_external_sort_matches)


**Evaluación:** ORDER BY usa el operador real desde SQL; los tests fuerzan derrame y comparan secuencias estables con sorted.


**Problemas:** El presupuesto modela objetos y buffers; no es medición RSS del proceso. No presentarlo como memoria física observada.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Conservar runs y merge; usar RSS separadamente cuando un experimento pida memoria real.


**Validación:** Presupuesto mínimo, múltiples runs y pasadas, claves repetidas, filas anchas, salida ordenada y temporales eliminados tras fallo/cierre.


**Dependencias:** Scans, RowLayout, temporales y ExecutionContext.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Generación de runs en disco | 1 | 1 | 0 |
| Merge k-way | 1 | 1 | 0 |
| Integración SQL | 1 | 1 | 0 |
| Resultados y limpieza | 1 | 1 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.2.5: GROUP BY optimizado con hashing externo o índices


**Requisito:** GROUP BY optimizado con hashing externo o índices. PDF, página(s) 1, sección 2.1.2.


**Estado:** ✅ COMPLETO.


**Estado actual:** ExternalHashGroup particiona a disco, acumula agregados y resuelve skew mediante rutas acotadas.


**Evidencia:** engine/operators/aggregation.py:714 (class ExternalHashGroup); engine/operators/partitioning.py:1; tests/integration/test_stage6_differential.py:118 (def test_external_grouping_matches)


**Evaluación:** Cumple la alternativa de hashing externo y está conectado al planner SQL; no hace falta exigir también la alternativa por índices.


**Problemas:** El PDF no fija lista completa de agregados SQL ni semántica de NULL. El subconjunto implementado tiene límites explícitos.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Mantener agregados y particionado propios; reutilizar estados mergeables.


**Validación:** Comparar con agrupación por diccionario, incluyendo AVG ponderado, claves dominantes, vacío, duplicados y presupuestos distintos.


**Dependencias:** 1.2.4 para fallbacks que necesiten ordenar; particiones y expresión tipada.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Algoritmo propio compatible | 1 | 1 | 0 |
| Ruta externa o indexada real | 1 | 1 | 0 |
| Integración SQL | 1 | 1 | 0 |
| Agregados correctos | 1 | 1 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.2.6: JOIN optimizado con hashing externo o índices


**Requisito:** JOIN optimizado con hashing externo o índices. PDF, página(s) 1, sección 2.1.2.


**Estado:** ✅ COMPLETO.


**Estado actual:** GraceHashJoin y rutas indexadas realizan equijoins reales; NestedLoopJoin proporciona una referencia alternativa.


**Evidencia:** engine/operators/join.py:652 (class GraceHashJoin); engine/operators/index_strategies.py:53 (class IndexNestedLoopJoin); tests/integration/test_stage6_differential.py:143 (def test_grace_join_matches)


**Evaluación:** Los resultados preservan multiplicidad y las pruebas fuerzan particiones externas y skew. Cumple la optimización requerida.


**Problemas:** Solo se soportan joins del subconjunto acordado. El PDF no exige todos los joins del estándar.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Mantener GraceHashJoin y estrategia indexada elegible; no sustituirlos por operaciones de un DBMS externo.


**Validación:** Comparar como multiconjunto contra bucles independientes, con duplicados, tablas vacías, skew y todas las rutas seleccionables.


**Dependencias:** Scans, particionado y acceso por igualdad.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Algoritmo propio compatible | 1 | 1 | 0 |
| Ruta externa o indexada real | 1 | 1 | 0 |
| Integración SQL | 1 | 1 | 0 |
| Multiplicidad correcta | 1 | 1 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



#### Etapa 1.3: SQL



##### Paso 1.3.1: SELECT y WHERE básicos


**Requisito:** SELECT y WHERE básicos. PDF, página(s) 1–2, sección 2.1.3.


**Estado:** ✅ COMPLETO.


**Estado actual:** Lexer y parser manuales producen AST; binder resuelve catálogo; planner construye operadores propios.


**Evidencia:** engine/query/parser.py:87 (class _Parser); engine/query/binder.py:1; engine/query/planner.py:1; tests/query/test_stage7_acceptance.py:127 (def test_reproducible_selection_matrix)


**Evaluación:** SELECT, proyección y condiciones soportadas se ejecutan por el motor. Errores sintácticos/semánticos se verificaron también por HTTP y navegador.


**Problemas:** LIMIT, funciones espaciales y rankings están ausentes. Es correcto para Parte 1, pero bloquea extensiones posteriores.


**Corrección:** No exigir un SQL completo; ampliar AST/binder/planner de forma localizada al implementar los requisitos posteriores.


**Implementación recomendada:** Conservar descenso recursivo y spans; incorporar nodos tipados para capacidades multimodales.


**Validación:** Oráculos de resultados, comparaciones con/sin índices, SQL inválido, límites de parser y recuperación de la consulta siguiente.


**Dependencias:** Catálogo, almacenamiento y operadores.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Parser y AST | 1 | 1 | 0 |
| Binding de tablas y columnas | 1 | 1 | 0 |
| Ejecución y resultados | 1 | 1 | 0 |
| Errores controlados | 1 | 1 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.3.2: INSERT INTO VALUES


**Requisito:** INSERT INTO VALUES. PDF, página(s) 1–2, sección 2.1.3.


**Estado:** ✅ COMPLETO.


**Estado actual:** INSERT valida columnas y tipos, escribe una vez y mantiene índices mediante MutationService bajo sesión.


**Evidencia:** engine/maintenance/service.py:401 (def insert(); engine/query/executor.py:1127 (class SqlEngine); tests/query/test_executor_writes.py:1


**Evaluación:** Escritura real, mantenimiento y publicación/rollback están cubiertos; la API muestra resultados provisionales correctamente.


**Problemas:** La ruta cruda de SqlEngine sin coordinador tiene garantías distintas a la sesión pública. No usarla como fachada concurrente.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Mantener las escrituras bajo el owner y SqlSession; reservar rutas sin coordinador para pruebas/demos controladas.


**Validación:** Insertar tipos correctos/incorrectos, duplicados de PK, confirmar/revertir y comprobar todos los índices tras reapertura.


**Dependencias:** 1.1, 1.2 y 1.4.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Sintaxis requerida | 1 | 1 | 0 |
| Escritura real | 1 | 1 | 0 |
| Mantenimiento de índices | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.3.3: DELETE WHERE


**Requisito:** DELETE WHERE. PDF, página(s) 1–2, sección 2.1.3.


**Estado:** ✅ COMPLETO.


**Estado actual:** DELETE descubre RIDs en un spool acotado antes de escribir y coordina borrado y reparación de índices.


**Evidencia:** engine/maintenance/service.py:87 (class DeleteTargetSpool); engine/maintenance/service.py:512 (def delete(); tests/query/test_mutation_maintenance.py:1


**Evaluación:** Los targets exactos evitan invalidación del scan durante mutación; las sesiones añaden undo y aislamiento.


**Problemas:** La compensación aislada del servicio conserva prefijos en fallos ordinarios; no equivale al rollback coordinado. El sistema documenta ambas rutas.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Conservar discovery cerrado y verificación RID/registro; ejecutar públicamente mediante sesiones.


**Validación:** Borrado selectivo/no coincidente, fallos inyectados y rollback; comparar almacenamiento e índices y comprobar limpieza del spool.


**Dependencias:** 1.3.1 y mantenimiento de índices/transacciones.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Sintaxis requerida | 1 | 1 | 0 |
| Selección y borrado exactos | 1 | 1 | 0 |
| Mantenimiento de índices | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



#### Etapa 1.4: Transacciones y concurrencia



##### Paso 1.4.1: BEGIN TRANSACTION y END TRANSACTION


**Requisito:** BEGIN TRANSACTION y END TRANSACTION. PDF, página(s) 2, sección 2.1.4.


**Estado:** ✅ COMPLETO.


**Estado actual:** BEGIN/END agrupan sentencias en SqlSession; END publica commit y ROLLBACK restaura imágenes físicas.


**Evidencia:** engine/transactions/session.py:280 (class SqlSession); engine/transactions/completion.py:1; tests/transactions/test_sql_integration.py:1


**Evaluación:** Agrupación entre peticiones reales y aislamiento por token fueron corroborados por HTTP y Chromium.


**Problemas:** No hay WAL ni recuperación automática de crash. Se detecta estado no limpio; el PDF no obliga a esos mecanismos.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Conservar owner, locks y before-images; declarar los límites de fallo.


**Validación:** BEGIN con varias mutaciones, END, otra sesión observando, rollback y reapertura conservando solo lo confirmado.


**Dependencias:** 1.3 y gestor de transacciones.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Agrupación entre sentencias | 1 | 1 | 0 |
| Publicación al END | 1 | 1 | 0 |
| Aislamiento por sesión | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.4.2: Control de concurrencia para múltiples usuarios


**Requisito:** Control de concurrencia para múltiples usuarios. PDF, página(s) 2, sección 2.1.4.


**Estado:** ✅ COMPLETO.


**Estado actual:** Locks S/X por tabla, cola FIFO, wait-for graph, víctima de deadlock y latches físicos.


**Evidencia:** engine/transactions/locks.py:92 (class LockManager); tests/transactions/test_locks.py:1; tests/transactions/test_controlled_evidence.py:1


**Evaluación:** Múltiples sesiones comparten el owner; los lectores/writers en conflicto esperan en el gestor, sin serializar todas las peticiones HTTP.


**Problemas:** Los locks y el lease son de un solo proceso. Ejecutar varios workers sobre la misma base queda fuera del contrato actual.


**Corrección:** Mantener un worker por base. Un bloqueo entre procesos sería una ampliación de despliegue, no requisito del PDF.


**Implementación recomendada:** Conservar locks del motor y cancelar/abortar mediante el ciclo de vida existente.


**Validación:** Lectores compatibles, escritor excluyente, deadlock, timeout, cancelación y liberación solo después del estado terminal.


**Dependencias:** 1.4.1; owner único por proceso.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Locks o mecanismo equivalente propio | 1 | 1 | 0 |
| Lectores y escritores concurrentes | 1 | 1 | 0 |
| Conflictos gestionados correctamente | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.4.3: Demostración obligatoria con threads


**Requisito:** Demostración obligatoria con threads. PDF, página(s) 2, sección 2.1.4.


**Estado:** ✅ COMPLETO.


**Estado actual:** La demo ejecuta la misma operación de incremento sin protección, protegida y en serie usando threads.


**Evidencia:** demos/transactions_demo.py:1; tests/transactions/test_controlled_evidence.py:1; docs/auditoria/evidencias/demo_threads.json


**Evaluación:** Se ejecutó nuevamente: resultado sin protección 1, protegido 2 y referencia serial 2; evidencia de intentos y conflictos real.


**Problemas:** El adaptador inseguro está deliberadamente fuera del motor productivo.


**Corrección:** Ninguna corrección obligatoria identificada.


**Implementación recomendada:** Preservar el calendario determinista y explicar qué protección se omite en la demostración.


**Validación:** Dos operaciones terminadas, race visible y resultado protegido idéntico al serial; ejecución con warnings como errores.


**Dependencias:** 1.4.1 y 1.4.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Transacciones simultáneas | 1 | 1 | 0 |
| Race condition reproducida | 1 | 1 | 0 |
| Resultado protegido comparado con referencia | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



#### Etapa 1.5: Cuatro paneles



##### Paso 1.5.1: Panel de Archivos


**Requisito:** Panel de Archivos. PDF, página(s) 2, sección 2.1.5.


**Estado:** ✅ COMPLETO.


**Estado actual:** FilesPanel muestra tablas, columnas, tipos, organización e índices desde /api/tables.


**Evidencia:** frontend/src/components/FilesPanel.tsx:1; api/database.py:606 (def describe_table(); docs/auditoria/evidencias/navegador.json


**Evaluación:** Tablas y estructura se observaron en Chromium real. Cuenta datos físicos y advierte sobre valores provisionales.


**Problemas:** Otra pestaña puede mantener conteos antiguos hasta refrescar; no afecta los resultados SQL ni la estructura mostrada.


**Corrección:** No se identificó una corrección obligatoria del requisito; las mejoras se priorizan aparte.


**Implementación recomendada:** Como mejora, refrescar metadatos al volver a enfocar o después de detectar una nueva versión; conservar la advertencia de provisionalidad.


**Validación:** Cargar GUI, seleccionar tabla y contrastar esquema con /api/tables; verificar refresco entre pestañas al corregir esa mejora.


**Dependencias:** API, serialización y SqlEngine/SqlSession.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Tablas cargadas visibles | 1 | 1 | 0 |
| Estructura de tablas visible | 1 | 1 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.5.2: Panel de Consultas


**Requisito:** Panel de Consultas. PDF, página(s) 2, sección 2.1.5.


**Estado:** ✅ COMPLETO.


**Estado actual:** QueryPanel ofrece textarea SQL, presets y controles que envían opciones reales al motor.


**Evidencia:** frontend/src/components/QueryPanel.tsx:1; frontend/src/api.ts:109 (runQuery); docs/auditoria/evidencias/navegador.json


**Evaluación:** Editor, envío, errores con línea/columna y recuperación pasaron en navegador.


**Problemas:** No se reprodujo un defecto del requisito.


**Corrección:** No se identificó una corrección obligatoria del requisito; las mejoras se priorizan aparte.


**Implementación recomendada:** Conservar API y gating de solicitudes; ampliar presets solo cuando existan consultas multimodales reales.


**Validación:** Enviar SELECT válido/inválido y comprobar que cada envío se ejecuta una vez.


**Dependencias:** API, serialización y SqlEngine/SqlSession.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Editor SQL | 1 | 1 | 0 |
| Envío al motor | 1 | 1 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.5.3: Panel de Resultados


**Requisito:** Panel de Resultados. PDF, página(s) 2, sección 2.1.5.


**Estado:** ✅ COMPLETO.


**Estado actual:** ResultsPanel renderiza filas reales y distingue comandos, explicaciones, vacío y previews parciales.


**Evidencia:** frontend/src/components/ResultsPanel.tsx:1; api/serialization.py:1; docs/auditoria/evidencias/navegador.json


**Evaluación:** Las filas del navegador coinciden con el JSON y los casos HTTP; rollback mostró resultado vacío correcto.


**Problemas:** Las previews tienen límite de filas/bytes; el panel lo declara. No equivale a materializar todo el resultado.


**Corrección:** No se identificó una corrección obligatoria del requisito; las mejoras se priorizan aparte.


**Implementación recomendada:** Conservar límites y estados de completitud; añadir vistas especializadas cuando se implementen nuevos tipos.


**Validación:** Comparar celdas con resultados del motor, vacío, error y respuesta truncada.


**Dependencias:** API, serialización y SqlEngine/SqlSession.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Resultados reales en tabla | 1 | 1 | 0 |
| Errores visibles | 1 | 1 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.5.4: Panel de Plan de Ejecución


**Requisito:** Panel de Plan de Ejecución. PDF, página(s) 2, sección 2.1.5.


**Estado:** ✅ COMPLETO.


**Estado actual:** PlanPanel distingue plan preparado y observado, muestra árbol de operadores, índices y métricas reales.


**Evidencia:** frontend/src/components/PlanPanel.tsx:1; api/serialization.py:151 (def runtime_json(); docs/auditoria/evidencias/navegador.json


**Evaluación:** Activar/desactivar índices cambió IndexScan a TableScan sin alterar filas; ORDER BY mostró ExternalSort.


**Problemas:** Las métricas de preview pueden ser parciales y el panel lo indica; la memoria reservada es un modelo de ejecución.


**Corrección:** No se identificó una corrección obligatoria del requisito; las mejoras se priorizan aparte.


**Implementación recomendada:** Conservar serialización de descriptores reales; para nuevas modalidades crear operadores/reportes reales antes de añadir etiquetas UI.


**Validación:** Contrastar el árbol con el runtime, índices abiertos y orden de ejecución; verificar EXPLAIN sin confundirlo con ejecución.


**Dependencias:** API, serialización y SqlEngine/SqlSession.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Operadores reales | 1 | 1 | 0 |
| Índices realmente usados | 1 | 1 | 0 |
| Orden de operaciones | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



#### Etapa 1.6: Experimentos



##### Paso 1.6.1: Comparación experimental Heap frente a secuencial


**Requisito:** Comparación experimental Heap frente a secuencial. PDF, página(s) 2, sección 2.1.6.


**Estado:** ✅ COMPLETO.


**Estado actual:** Hay 143 mediciones de archivos: 55 por tamaño 1k/10k y 33 en 100k, con cargas, búsquedas, disco y reorganización.


**Evidencia:** benchmarks/file_organization.py:57 (def run(); docs/EXPERIMENTOS.md:71 (## 2.); benchmarks/results/part1_results*.jsonl; docs/auditoria/evidencias/experimentos_auditados.json


**Evaluación:** Datos y repeticiones requeridos presentes; las tablas se regeneraron desde los JSONL. El harness se repitió a 1k como diagnóstico.


**Problemas:** No se volvieron a ejecutar todas las corridas. Las de 1k/10k registran working tree sucio; su snapshot exacto no queda identificado solo por el commit.


**Corrección:** Guardar un snapshot o manifiesto por archivo para futuras mediciones; conservar los resultados originales y su procedencia.


**Implementación recomendada:** Reutilizar datos reproducibles y el harness. Registrar fsync/caché y entorno explícitos; no mezclar la repetición diagnóstica con resultados oficiales.


**Validación:** Cobertura de operaciones y tamaños, búsquedas con conteos esperados, repetición selectiva y tablas idénticas a las publicadas.


**Dependencias:** 1.1 y harness de medición propio.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Datos 1000 10000 100000 | 1 | 1 | 0 |
| Tiempo inserción | 1 | 1 | 0 |
| Búsqueda PK | 1 | 1 | 0 |
| Espacio disco | 1 | 1 | 0 |
| Reorganización | 1 | 1 | 0 |


Peso del paso: 1; 5 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.6.2: Comparación experimental B+ agrupado no agrupado y hash


**Requisito:** Comparación experimental B+ agrupado no agrupado y hash. PDF, página(s) 2, sección 2.1.6.


**Estado:** ✅ COMPLETO.


**Estado actual:** Hay 312 mediciones de índices; igualdad, rango, orden, construcción y disco están registrados para las tres estructuras.


**Evidencia:** benchmarks/indexes.py:207 (while done < workload_operations); docs/EXPERIMENTOS.md:197 (**Agrupado frente a no agrupado.**); docs/auditoria/evidencias/experimentos_auditados.json


**Evaluación:** La comparación mínima del PDF está cubierta: a 1k el agrupado sí realiza 17–18 borrados y 18–19 inserciones por repetición. La matriz ampliada a 100k no demuestra borrados frecuentes: inserted=1, deleted=0.


**Problemas:** El límite de 60 s se evalúa entre operaciones; una inserción duró 373–432 s. A 10k solo hubo un borrado por repetición. La tasa mide workloads distintos.


**Corrección:** Como mejora de la comparación ampliada, medir INSERT y DELETE por separado y completar un prefijo mixto común; etiquetar corridas censuradas y operaciones completadas.


**Implementación recomendada:** Conservar harness e índices. Añadir una medición explícita de borrado agrupado, o un lote mixto mínimo completo, aceptando y reportando su coste sin timeout ficticio.


**Validación:** Las corridas 1k acreditan ambas mutaciones; al ampliar la evaluación a 100k completar borrados y validar filas/índices al final. No extrapolar el dato faltante. El PDF no fija explícitamente tamaños para este subexperimento de índices.


**Dependencias:** 1.2.1–1.2.3; no requiere reescribir el B+ antes de medir.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Tres estructuras reales | 1 | 1 | 0 |
| Igualdad | 1 | 1 | 0 |
| Rango | 1 | 1 | 0 |
| Ordenamiento | 1 | 1 | 0 |
| Construcción | 1 | 1 | 0 |
| Consulta | 1 | 1 | 0 |
| Espacio adicional | 1 | 1 | 0 |
| Inserciones y borrados frecuentes | 1 | 1 | 0 |


Peso del paso: 1; 8 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.6.3: Gráficos comparativos relacionales


**Requisito:** Gráficos comparativos relacionales. PDF, página(s) 2, sección 2.1.6.


**Estado:** ✅ COMPLETO.


**Estado actual:** Existen once PNG y tablas generadas por benchmarks.report.


**Evidencia:** benchmarks/report.py:195 (def render(); docs/experimentos/resultados.md:1; docs/auditoria/evidencias/reporte_contrastado.json


**Evaluación:** La regeneración con los tres JSONL oficiales produce tablas textualmente idénticas y once gráficos.


**Problemas:** El comando sin --results toma solo el archivo de 1k/10k; para reproducir todo deben pasarse los tres archivos. La gráfica de carga mixta hereda su limitación.


**Corrección:** Documentar el comando completo o ajustar el default en una corrección futura; revisar la leyenda de la carga mixta.


**Implementación recomendada:** Conservar generación desde datos crudos; no dibujar mediciones inexistentes.


**Validación:** Regenerar y comparar tablas; inspeccionar etiquetas, unidades, series de 100k y notas de censura.


**Dependencias:** 1.6.1 y 1.6.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Gráficos existentes | 1 | 1 | 0 |
| Correspondencia con datos crudos | 1 | 1 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.6.4: Tabla de ventajas y desventajas relacionales


**Requisito:** Tabla de ventajas y desventajas relacionales. PDF, página(s) 2, sección 2.1.6.


**Estado:** ✅ COMPLETO.


**Estado actual:** EXPERIMENTOS contiene ventajas y desventajas de Heap, secuencial, ambos B+ y hash.


**Evidencia:** docs/EXPERIMENTOS.md:232 (## 5.)


**Evaluación:** La tabla requerida existe y coincide con comportamiento y cifras observadas.


**Problemas:** El agrupado se describe con throughput de una sola inserción a 100k. Mantener explícito ese alcance al comparar mantenimiento.


**Corrección:** Ajustar esa celda tras completar 1.6.2.


**Implementación recomendada:** Conservar recomendaciones específicas de esta implementación y sus limitaciones.


**Validación:** Cada ventaja/desventaja debe enlazar a un comportamiento probado o medición concreta, distinguiendo inferencias.


**Dependencias:** 1.6.1 y 1.6.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Todas las técnicas requeridas | 1 | 1 | 0 |
| Ventajas y desventajas | 1 | 1 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 1.6.5: Conclusiones de cuándo usar cada estructura


**Requisito:** Conclusiones de cuándo usar cada estructura. PDF, página(s) 2, sección 2.1.6.


**Estado:** ✅ COMPLETO.


**Estado actual:** Hay conclusiones por organización e índice, con cifras y límites de selectividad.


**Evidencia:** docs/EXPERIMENTOS.md:242 (## 6.)


**Evaluación:** Las recomendaciones están respaldadas por búsquedas, carga, espacio y rangos medidos.


**Problemas:** Tres tamaños no demuestran complejidad asintótica; la atribución del coste de hash a splits no fue aislada. El cruce 4–5% se reconoce como estimación.


**Corrección:** Reformular O(1) como comportamiento observado/expectativa bajo supuestos y la atribución causal como hipótesis; no añadir mediciones inventadas.


**Implementación recomendada:** Separar conclusiones empíricas, complejidad teórica y estimaciones; conservar las recomendaciones útiles.


**Validación:** Trazar cada cifra a la mediana y cada afirmación causal a evidencia o etiqueta de inferencia.


**Dependencias:** 1.6.1–1.6.4.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Heap y secuencial | 1 | 1 | 0 |
| B+ agrupado y no agrupado y hash | 1 | 1 | 0 |
| Conclusiones respaldadas por mediciones | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



### Parte 2: Espacial



#### Etapa 2.1: Nucleo espacial



##### Paso 2.1.1: R-Tree propio sobre puntos latitud longitud


**Requisito:** R-Tree propio sobre puntos latitud longitud. PDF, página(s) 3, sección 2.2.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** RTree implementa nodos/MBR, quadratic split, elección de subárbol y persistencia JSON versionada con checksum.


**Evidencia:** engine/spatial/rtree.py:80 (class RTree); engine/spatial/rtree.py:123 (def _split(); engine/spatial/index.py:78 (class SpatialIndex); tests/spatial/test_e2_engine.py:1; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** Es un R-Tree propio multinivel, asociado a RIDs del Heap y validado estructuralmente; el PDF no exige R-Tree paginado.


**Problemas:** El árbol completo vive en RAM; INSERT guarda todo el JSON y DELETE reconstruye todo el árbol. No confundir persistencia con paginación externa.


**Corrección:** Ninguna corrección obligatoria del algoritmo identificada; atender los límites señalados al integrarlo.


**Implementación recomendada:** Reutilizar el núcleo; medir memoria y mantenimiento antes de considerar nodos paginados o actualización incremental.


**Validación:** Inserciones con varios niveles, ocupación, MBR, cobertura de RIDs, duplicados y reapertura; prueba actual sobre Heap de 100k.


**Dependencias:** Heap estable, SpatialMapping y owner/sesiones para consultas públicas.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Nodos y MBR propios | 1 | 1 | 0 |
| Inserción y división | 1 | 1 | 0 |
| Árbol multinivel | 1 | 1 | 0 |
| Persistencia y asociación con datos | 1 | 1 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 2.1.2: Consultas espaciales por rango o radio


**Requisito:** Consultas espaciales por rango o radio. PDF, página(s) 3, sección 2.2.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** radius usa bounds conservadores y una comprobación exacta de distancia; existe SpatialScan independiente del traversal.


**Evidencia:** engine/spatial/rtree.py:166 (def radius(); engine/spatial/index.py:30 (def scan_radius(); tests/spatial/test_e2_engine.py:1; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** Resultados indexados y scan coinciden; se comprobó además contra un cálculo matemático independiente con Heap real.


**Problemas:** La cota Haversine solo usa latitud: es segura, pero puede podar poco en distribuciones de latitud similar.


**Corrección:** Ninguna corrección obligatoria del algoritmo identificada; atender los límites señalados al integrarlo.


**Implementación recomendada:** Conservar el residual exacto. Mejorar la cota únicamente con una prueba de que nunca excede la distancia mínima real.


**Validación:** Radios 0/1/5/10 km, límites incluidos/excluidos, centros en los bordes y consultas dentro del dominio admitido.


**Dependencias:** Heap estable, SpatialMapping y owner/sesiones para consultas públicas.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Resultados correctos | 1 | 1 | 0 |
| Traversal del índice real | 1 | 1 | 0 |
| Validación contra secuencial | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 2.1.3: k vecinos más cercanos


**Requisito:** k vecinos más cercanos. PDF, página(s) 3, sección 2.2.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** knn hace best-first sobre MBR y heap acotado de candidatos; ordena por distancia e ID.


**Evidencia:** engine/spatial/rtree.py:212 (def knn(); engine/spatial/index.py:57 (def scan_knn(); tests/spatial/test_e2_engine.py:1; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** k, empates, duplicados y k mayor que N tienen pruebas; el probe 100k comprueba k=10/50/100 con referencia independiente.


**Problemas:** El resultado materializa hasta k filas y no tiene presupuesto de consultas espaciales equivalente al pipeline relacional.


**Corrección:** Ninguna corrección obligatoria del algoritmo identificada; atender los límites señalados al integrarlo.


**Implementación recomendada:** Conservar ranking estable; al exponer por HTTP imponer límites de salida y definir un operador TopK con métricas reales.


**Validación:** Comparar IDs y orden con ordenamiento exhaustivo, k=0/1/N/N+1, empates y ambas métricas.


**Dependencias:** Heap estable, SpatialMapping y owner/sesiones para consultas públicas.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Orden por distancia | 1 | 1 | 0 |
| k y empates | 1 | 1 | 0 |
| Traversal indexado real | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 2.1.4: Intersección de puntos con polígonos


**Requisito:** Intersección de puntos con polígonos. PDF, página(s) 3, sección 2.2.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** El índice filtra MBR y Polygon.contains aplica predicado exacto, con borde incluido y polígonos simples cóncavos.


**Evidencia:** engine/spatial/geometry.py:168 (class Polygon); engine/spatial/rtree.py:191 (def polygon(); tests/spatial/test_e2_engine.py:1; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** Cumple intersección de puntos con polígonos. El PDF no exige polígonos con agujeros o geometrías arbitrarias.


**Problemas:** El dominio es local y la convención del borde debe conservarse al conectar SQL, mapa y GiST.


**Corrección:** Ninguna corrección obligatoria del algoritmo identificada; atender los límites señalados al integrarlo.


**Implementación recomendada:** Reutilizar Polygon y MBR; validar datos y revelar la convención de borde en la interfaz.


**Validación:** Puntos interiores, exteriores dentro del MBR, vértices, aristas, concavidad, inversión de orientación y polígonos inválidos.


**Dependencias:** Heap estable, SpatialMapping y owner/sesiones para consultas públicas.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Filtro MBR | 1 | 1 | 0 |
| Predicado geométrico exacto | 1 | 1 | 0 |
| Límites y polígonos cóncavos | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 2.1.5: Distancia Euclidiana


**Requisito:** Distancia Euclidiana. PDF, página(s) 3, sección 2.2.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** Distancia planar en metros mediante proyección local fija alrededor de Lima.


**Evidencia:** engine/spatial/geometry.py:63 (def local_xy(); engine/spatial/geometry.py:68 (def distance(); engine/spatial/metadata.py:23 (ORIGIN =); tests/spatial/test_e2_engine.py:1; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** Implementa Euclidiana en un plano declarado, no sobre grados sin conversión. Las pruebas comprueban unidades y ranking diferente de Haversine.


**Problemas:** Solo se admiten coordenadas del dominio local fijado. El PDF no impone cobertura mundial; debe mostrarse ese límite.


**Corrección:** Ninguna corrección obligatoria del algoritmo identificada; atender los límites señalados al integrarlo.


**Implementación recomendada:** Mantener proyección y unidades; al ampliar dominio, introducir una convención/proyección explícita y una nueva versión compatible.


**Validación:** Casos analíticos norte/este, identidad, simetría y comparación con cálculo planar independiente.


**Dependencias:** Heap estable, SpatialMapping y owner/sesiones para consultas públicas.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Métrica implementada | 1 | 1 | 0 |
| Unidades y proyección explícitas | 1 | 1 | 0 |
| Resultado verificado | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso 2.1.6: Distancia geodésica Haversine


**Requisito:** Distancia geodésica Haversine. PDF, página(s) 3, sección 2.2.1.


**Estado:** ✅ COMPLETO.


**Estado actual:** distance implementa Haversine esférica en metros con radio medio WGS84 declarado.


**Evidencia:** engine/spatial/geometry.py:68 (def distance(); engine/spatial/metadata.py:25 (EARTH_RADIUS_METRES =); tests/spatial/test_e2_engine.py:1; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** La fórmula, unidad y uso en consultas son correctos en el dominio; el probe utiliza ángulo entre vectores unitarios como referencia distinta.


**Problemas:** El comparador PostgreSQL debe usar esfera, radio compatible y residual exacto; el modo spheroid por defecto no sería equivalente.


**Corrección:** Ninguna corrección obligatoria del algoritmo identificada; atender los límites señalados al integrarlo.


**Implementación recomendada:** Conservar Haversine y hacer explícito use_spheroid=false en futuras mediciones GiST.


**Validación:** Distancia cero, norte/este, equivalencia con referencia esférica y orden en radio/k-NN.


**Dependencias:** Heap estable, SpatialMapping y owner/sesiones para consultas públicas.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Fórmula implementada | 1 | 1 | 0 |
| Unidades explícitas | 1 | 1 | 0 |
| Resultado verificado | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



#### Etapa 2.2: Mapa



##### Paso 2.2.1: Panel de mapa interactivo


**Requisito:** Panel de mapa interactivo. PDF, página(s) 3, sección 2.2.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** La GUI actual contiene cuatro paneles relacionales; no hay componente ni dependencia de mapa.


**Evidencia:** frontend/src/App.tsx:1; frontend/package.json:1; docs/auditoria/evidencias/navegador.png


**Evaluación:** Los puntos almacenados no se pueden visualizar en un mapa interactivo.


**Problemas:** Existe preparación espacial en backend, pero no visualización espacial.


**Corrección:** Añadir un panel de mapa conectado a datos reales del motor.


**Implementación recomendada:** Usar una biblioteca de mapa como transporte visual, con latitud/longitud explícitas, navegación y carga acotada de puntos.


**Validación:** Abrir una tabla espacial y ver sus posiciones reales; pan/zoom no deben alterar identidades ni invertir ejes.


**Dependencias:** 2.3 y una ruta HTTP espacial.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Mapa interactivo | 0 | 0 | 0 |
| Puntos almacenados visibles | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 2.2.2: Resultados espaciales resaltados en el mapa


**Requisito:** Resultados espaciales resaltados en el mapa. PDF, página(s) 3, sección 2.2.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay selección ni resaltado espacial en frontend.


**Evidencia:** frontend/src/App.tsx:1; docs/auditoria/evidencias/inventario_codigo.json


**Evaluación:** La salida espacial tipada existe, pero ningún flujo GUI la consume.


**Problemas:** No se demuestra rango, k-NN o polígono sobre mapa.


**Corrección:** Conectar resultados con marcadores resaltados y selección por ID.


**Implementación recomendada:** Mantener una capa de puntos base y una capa de resultados; mostrar centro/radio o polígono y lista de distancias concordante.


**Validación:** IDs del mapa, tabla y respuesta del motor idénticos; limpiar resaltado anterior ante vacío/error y conservar orden k-NN.


**Dependencias:** 2.2.1, 2.3 y serialización espacial.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Consultas conectadas al mapa | 0 | 0 | 0 |
| Resultados resaltados | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



#### Etapa 2.3: SQL espacial



##### Paso 2.3.1: SQL espacial por distancia y POINT


**Requisito:** SQL espacial por distancia y POINT. PDF, página(s) 3, sección 2.2.3.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** SqlSession admite consultas relacionales; el parser rechaza distancia/POINT. El owner tiene spatial_radius programático.


**Evidencia:** engine/query/parser.py:50 (_AGGREGATE_FUNCTIONS); api/database.py:569 (def spatial_radius(); docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** Un método Python no satisface la extensión SQL requerida.


**Problemas:** Faltan nodos AST, binding de ubicación, planificación espacial y ejecución SQL; tampoco hay endpoint espacial público.


**Corrección:** Extender la cadena parser→AST→binder→planner→executor con consultas por distancia.


**Implementación recomendada:** Añadir POINT(lat,lon), expresión de distancia y un operador SpatialScan/SpatialIndexScan que reutilice SpatialIndex bajo los locks de sesión; conservar residual estricto <.


**Validación:** Ejecutar el ejemplo del PDF sobre tiendas, comparar índice y scan, ambas métricas, borde, errores de ejes/unidades y plan observado.


**Dependencias:** 2.1; integración del owner y metadatos espaciales con QueryEnvironment.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Sintaxis espacial | 0 | 0 | 0 |
| Binding de ubicación | 0 | 0 | 0 |
| Ejecución con resultados reales | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 2.3.2: SQL espacial k-NN por distancia y LIMIT


**Requisito:** SQL espacial k-NN por distancia y LIMIT. PDF, página(s) 3, sección 2.2.3.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** ORDER BY solo acepta expresiones del subconjunto relacional y LIMIT está explícitamente fuera de él.


**Evidencia:** engine/query/parser.py:66 (_UNSUPPORTED_TRAILING_KEYWORDS); api/database.py:575 (def spatial_knn(); docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** El ejemplo k-NN SQL no se puede ejecutar; el núcleo k-NN correcto no completa esta interfaz.


**Problemas:** Falta resolver mi_ubicacion o un centro literal, expresión de distancia y límite de resultados.


**Corrección:** Añadir LIMIT entero no negativo y reconocimiento de ORDER BY distancia para la ruta k-NN.


**Implementación recomendada:** Resolver centros mediante parámetros explícitos o POINT; seleccionar un operador TopK espacial y devolver distancia/IDs ordenados sin ordenar toda la tabla innecesariamente.


**Validación:** Ejemplo funcional con k=10, límites 0/N/N+1, empates estables, métrica elegida y plan que identifique el acceso real.


**Dependencias:** 2.3.1; AST/binding de funciones y contrato de resultados.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Ordenamiento por distancia | 0 | 0 | 0 |
| Límite k | 0 | 0 | 0 |
| Integración con motor espacial | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



#### Etapa 2.4: Experimentos espaciales



##### Paso 2.4.1: Comparador secuencial R-Tree propio y GiST PostgreSQL


**Requisito:** Comparador secuencial R-Tree propio y GiST PostgreSQL. PDF, página(s) 3, sección 2.2.4.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** Hay scan, R-Tree y SQL de preparación GiST, además de logs históricos de setup PostGIS.


**Evidencia:** benchmarks/spatial/postgres.py:21 (def setup_sql(); benchmarks/spatial/__main__.py:9 (def main(); benchmarks/results/spatial_e1_setup.json:1; docs/auditoria/evidencias/comparador_entorno_actual.json


**Evaluación:** No hay un harness que mida y compare las tres técnicas. EXPLAIN de preparación no equivale al experimento requerido.


**Problemas:** No existen mediciones comparativas completas ni validación cruzada de las 100 consultas. Docker CLI está instalado, pero docker ps falla porque no está disponible el daemon; el contenedor histórico no pudo consultarse. Disponibilidad actual de PostGIS: NO VERIFICADA.


**Corrección:** Implementar adapters de medición secuencial/R-Tree/GiST sobre los mismos CSV y centros.


**Implementación recomendada:** Reutilizar datasets y setup; registrar plans GiST y equivalencia exacta de IDs. Evitar que PostgreSQL participe como almacenamiento del motor propio.


**Validación:** Cada combinación debe producir resultados equivalentes y filas de medición con técnica, tamaño, consulta, configuración y unidades.


**Dependencias:** 2.1 y comparador PostgreSQL preparado; 2.3 no bloquea benchmarks directos.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Secuencial medido | 0 | 0 | 0 |
| R-Tree medido | 0 | 0 | 0 |
| GiST medido | 0 | 0 | 0 |
| Consultas y datos equivalentes | 0 | 0 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 2.4.2: Experimentos espaciales con radios k y tamaños requeridos


**Requisito:** Experimentos espaciales con radios k y tamaños requeridos. PDF, página(s) 3, sección 2.2.4.


**Estado:** 🟡 PARCIAL.


**Estado actual:** El generador exporta 1k/10k/100k y 100 centros; el manifiesto enumera radios y k requeridos.


**Evidencia:** benchmarks/spatial/datasets.py:63 (def export(); tests/spatial/test_e1_inputs.py:1


**Evaluación:** Se acredita preparación de los tres tamaños; no ejecución del experimento completo con las familias de radio y k.


**Problemas:** El probe de auditoría 100k es funcional, con tres centros; no reemplaza las 100 consultas ni la comparación de técnicas.


**Corrección:** Ejecutar la matriz radio=1000/5000/10000 m, k=10/50/100 y N=1000/10000/100000.


**Implementación recomendada:** Consumir los CSV/manifiesto compartidos y 100 centros por combinación; conservar hashes y separar warmup de medición.


**Validación:** Cobertura automática de tamaños, familias y parámetros; archivos sin huecos, IDs correctos y semillas reproducibles.


**Dependencias:** 2.4.1.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Radios 1 5 10 km | 0 | 0 | 0 |
| k 10 50 100 | 0 | 0 | 0 |
| 1000 10000 100000 puntos | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 33.33 %; cumplimiento 33.33 %; pendiente 0.00 %.



##### Paso 2.4.3: Tiempos espaciales de construcción y consulta


**Requisito:** Tiempos espaciales de construcción y consulta. PDF, página(s) 3, sección 2.2.4.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay tiempos completos de construcción y promedio de 100 consultas para las tres técnicas.


**Evidencia:** benchmarks/spatial/__main__.py:1; benchmarks/spatial/postgres.py:1


**Evaluación:** El setup y los smoke tests no satisfacen las mediciones solicitadas.


**Problemas:** Faltan crudos por consulta y agregación comparable.


**Corrección:** Medir construcción y consultas con límites temporales claros.


**Implementación recomendada:** Excluir generación/importación cuando se mida construcción del índice; explicitar el tratamiento de carga de datos para cada técnica y medir consultas equivalentes.


**Validación:** Promedio calculable desde 100 tiempos crudos por caso, con resultados correctos y repeticiones/entorno declarados.


**Dependencias:** 2.4.1–2.4.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Tiempo construcción | 0 | 0 | 0 |
| Promedio de 100 consultas | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 2.4.4: Memoria y espacio en disco espaciales


**Requisito:** Memoria y espacio en disco espaciales. PDF, página(s) 3, sección 2.2.4.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** Se conocen archivos del R-Tree/Heap, pero no existe una medición experimental de memoria y disco espacial.


**Evidencia:** engine/spatial/rtree.py:282 (def save(); engine/operators/context.py:58 (ROW_OVERHEAD_BYTES =)


**Evaluación:** Contadores de candidatos o memoria reservada relacional no son RSS ni espacio del comparador.


**Problemas:** El árbol es residente y JSON puede aumentar el pico durante guardado; PostgreSQL requiere métricas específicas de sus relaciones.


**Corrección:** Añadir memoria real y tamaños base/índice para cada técnica.


**Implementación recomendada:** Medir RSS pico por proceso/subproceso, bytes de archivos propios y pg_relation_size/pg_total_relation_size; declarar métricas no comparables directamente.


**Validación:** Resultados con unidades y alcance, baseline de proceso y ausencia de ceros ficticios o estimaciones presentadas como mediciones.


**Dependencias:** 2.4.1 y política experimental común.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Memoria medida | 0 | 0 | 0 |
| Disco medido | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 2.4.5: Presentación experimental espacial


**Requisito:** Presentación experimental espacial. PDF, página(s) 3, sección 2.2.4.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay gráficos ni tabla experimental espacial derivados de una matriz completa.


**Evidencia:** docs/spatial.md:1; benchmarks/report.py:1


**Evaluación:** La presentación relacional no satisface la comparación espacial.


**Problemas:** Faltan datos base, gráficos y recomendaciones espaciales medidos.


**Corrección:** Generar gráficos y tabla desde los nuevos crudos.


**Implementación recomendada:** Reutilizar el estilo del reporte relacional con series secuencial/R-Tree/GiST y notas sobre memoria, disco y equivalencia.


**Validación:** Cada cifra trazable a mediciones; gráficas por tamaño/radio/k y tabla de cuándo usar cada técnica.


**Dependencias:** 2.4.1–2.4.4.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Gráficas comparativas | 0 | 0 | 0 |
| Tabla de cuándo usar cada técnica | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



### Parte 3: Texto



#### Etapa 3.1: Indice y ranking



##### Paso 3.1.1: Índice invertido con SPIMI


**Requisito:** Índice invertido con SPIMI. PDF, página(s) 3, sección 2.3.1.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** Solo existe almacenamiento de VARCHAR relacional; no hay índice invertido ni SPIMI.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Un campo de texto y un B+ sobre cadenas no indexan términos ni postings; documentos largos pueden exceder una página.


**Corrección:** Añadir almacenamiento gestionado de documentos e índice SPIMI propio.


**Implementación recomendada:** Definir doc_id estable, tokenización reproducible y bloques acotados término→postings; persistir bloques y fusionarlos por término conservando tf y estadísticas.


**Validación:** Oracle de postings en corpus pequeño, documentos repetidos/vacíos, Unicode, bloques externos forzados y reapertura.


**Dependencias:** IDs/catálogo, owner/auxiliares, almacenamiento de texto fuera de filas de una sola página.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Procesamiento de documentos | 0 | 0 | 0 |
| Bloques SPIMI | 0 | 0 | 0 |
| Postings y merge propios | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 3.1.2: Ranking TF-IDF con similitud coseno


**Requisito:** Ranking TF-IDF con similitud coseno. PDF, página(s) 3, sección 2.3.1.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** La presencia de VARCHAR no incluye TF-IDF ni vectores sparse de términos.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No hay estadísticas tf/df ni normalización de documentos/consulta.


**Corrección:** Implementar ranking TF-IDF + coseno.


**Implementación recomendada:** Obtener df y N del índice SPIMI, definir fórmula/normalización explícitas y acumular productos por postings; ordenar scores con tie-break por doc_id.


**Validación:** Corpus con puntuaciones calculadas manualmente, consulta sin términos, términos repetidos y rankings estables tras reabrir.


**Dependencias:** 3.1.1.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Pesos TF-IDF | 0 | 0 | 0 |
| Coseno | 0 | 0 | 0 |
| Ranking correcto | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 3.1.3: Ranking BM25


**Requisito:** Ranking BM25. PDF, página(s) 3, sección 2.3.1.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No se encontró BM25 en engine ni en rutas API.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Faltan longitud de documentos, promedio y cálculo de score.


**Corrección:** Implementar BM25 sobre los mismos postings.


**Implementación recomendada:** Persistir document length y avgdl; definir k1/b configurables y reutilizar las estadísticas del corpus sin duplicar el índice.


**Validación:** Scores de referencia, documentos de longitudes distintas, consulta vacía/OOV y orden descendente estable.


**Dependencias:** 3.1.1.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Fórmula y estadísticas | 0 | 0 | 0 |
| Ranking correcto | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



#### Etapa 3.2: Experimentos textuales



##### Paso 3.2.1: Comparación TF-IDF Coseno BM25 y GIN PostgreSQL


**Requisito:** Comparación TF-IDF Coseno BM25 y GIN PostgreSQL. PDF, página(s) 3, sección 2.3.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay harness TF-IDF/BM25/GIN.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** PostGIS espacial no es un comparador GIN textual.


**Corrección:** Construir adapters para las tres técnicas con el mismo corpus y consultas.


**Implementación recomendada:** Configurar explícitamente tokenización y ranking PostgreSQL; documentar diferencias en stemming/stopwords en vez de atribuirlas al índice.


**Validación:** Mismos IDs/corpus, consultas registradas y tres resultados comparables por caso.


**Dependencias:** 3.1.1–3.1.3; PostgreSQL como comparador.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Tres técnicas medidas | 0 | 0 | 0 |
| Mismas consultas | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 3.2.2: Datasets y longitud de consulta textual


**Requisito:** Datasets y longitud de consulta textual. PDF, página(s) 3, sección 2.3.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No se encontró corpus textual ni consultas de 1, 3 y 5+ palabras.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No hay datos reproducibles para evaluar la Parte 3.


**Corrección:** Preparar corpus de 1k/10k/100k documentos y consultas estratificadas por longitud.


**Implementación recomendada:** Guardar origen, hashes, doc_ids y consultas compartidas; evitar que una partición de texto cuente como documentos independientes sin explicarlo.


**Validación:** Conteos exactos, texto recuperable y consultas en las tres bandas de longitud.


**Dependencias:** Almacenamiento de documentos; elección de dominio.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| 1000 10000 100000 documentos | 0 | 0 | 0 |
| Consultas 1 3 y 5+ palabras | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 3.2.3: Tiempos textuales de construcción y consulta


**Requisito:** Tiempos textuales de construcción y consulta. PDF, página(s) 3, sección 2.3.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay tiempos de construcción/consulta textual.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Las métricas SQL relacionales no sustituyen ranking textual.


**Corrección:** Medir los dos costes para las tres técnicas y tamaños.


**Implementación recomendada:** Separar ingesta de construcción y consulta; guardar repeticiones y configuración del ranking.


**Validación:** Crudos con técnica/tamaño/consulta y agregaciones regenerables.


**Dependencias:** 3.2.1–3.2.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Construcción medida | 0 | 0 | 0 |
| Consulta medida | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 3.2.4: Relevancia Precision@10 y Recall@10


**Requisito:** Relevancia Precision@10 y Recall@10. PDF, página(s) 3, sección 2.3.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay juicios de relevancia ni Precision@10/Recall@10.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No se puede obtener relevancia solo de tiempos o scores propios.


**Corrección:** Definir queries con conjuntos de documentos relevantes y calcular ambas métricas.


**Implementación recomendada:** Mantener qrels independientes de TF-IDF/BM25; declarar convenciones para menos de diez resultados y consultas sin relevantes.


**Validación:** Casos manuales perfectos/parciales/nulos y agregados idénticos a un cálculo independiente.


**Dependencias:** 3.2.2 y rankings implementados.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Juicios de relevancia | 0 | 0 | 0 |
| Precision@10 | 0 | 0 | 0 |
| Recall@10 | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 3.2.5: Uso de memoria y disco textual


**Requisito:** Uso de memoria y disco textual. PDF, página(s) 3, sección 2.3.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay mediciones de memoria y espacio de índices textuales.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No existe evidencia de consumo del SPIMI o GIN.


**Corrección:** Medir RSS y disco base/índice durante construcción y búsqueda.


**Implementación recomendada:** Usar el contrato experimental común y métricas PostgreSQL explícitas.


**Validación:** Unidades y fases definidas, valores reales por técnica y tamaño.


**Dependencias:** 3.2.1–3.2.3.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Memoria medida | 0 | 0 | 0 |
| Disco medido | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 3.2.6: Presentación experimental textual


**Requisito:** Presentación experimental textual. PDF, página(s) 3, sección 2.3.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay gráficos ni tabla textual.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Faltan experimentos a los que vincular ventajas/desventajas.


**Corrección:** Generar presentación experimental de Parte 3.


**Implementación recomendada:** Mostrar tiempo, memoria, disco y relevancia por técnica, tamaño y longitud de consulta.


**Validación:** Gráficas regenerables y recomendaciones apoyadas por datos y límites de calidad.


**Dependencias:** 3.2.1–3.2.5.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Gráficas | 0 | 0 | 0 |
| Tabla de ventajas y desventajas | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



#### Etapa 3.3: SQL textual



##### Paso 3.3.1: SQL textual MATCH USING SCORE LIMIT


**Requisito:** SQL textual MATCH USING SCORE LIMIT. PDF, página(s) 3–4, sección 2.3.3.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** El parser rechaza MATCH/USING/SCORE y LIMIT; no hay ejecución de búsqueda textual.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Reconocer palabras o guardar textos no satisface los ejemplos SQL.


**Corrección:** Extender AST, binder, planner y executor con búsqueda/ranking textual.


**Implementación recomendada:** Resolver MATCH contra un campo indexado, seleccionar TF_IDF/BM25, producir SCORE y reutilizar LIMIT/TopK; devolver planes de operadores reales.


**Validación:** Ambos ejemplos del PDF, aliases de score, orden y límites; errores controlados por técnica/campo inválidos.


**Dependencias:** 3.1.1–3.1.3 y extensión general de funciones/LIMIT de 2.3.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| MATCH | 0 | 0 | 0 |
| USING TF_IDF y BM25 | 0 | 0 | 0 |
| SCORE y ordenamiento | 0 | 0 | 0 |
| LIMIT | 0 | 0 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



### Parte 4: Multimedia



#### Etapa 4.1: Extraccion y representacion



##### Paso 4.1.1: ExtractFeatures para imágenes mediante SIFT


**Requisito:** ExtractFeatures para imágenes mediante SIFT. PDF, página(s) 4, sección 2.4.1.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No existe ExtractFeatures de imágenes ni SIFT.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** El motor no carga ni transforma imágenes en descriptores.


**Corrección:** Añadir extracción de descriptores SIFT y manejo de objetos gestionados.


**Implementación recomendada:** Definir ExtractFeatures con tipo/versión de extractor, validar formatos y guardar vínculos objeto→descriptores. Aclarar si el docente permite bibliotecas auxiliares SIFT; el PDF no lo resuelve.


**Validación:** Imagen válida, uniforme, corrupta y transformada; salida finita y reproducible con parámetros fijados.


**Dependencias:** Almacenamiento de objetos y metadatos.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Función de extracción | 0 | 0 | 0 |
| Descriptores SIFT | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.1.2: ExtractFeatures para audio mediante MFCC


**Requisito:** ExtractFeatures para audio mediante MFCC. PDF, página(s) 4, sección 2.4.1.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No existe extracción MFCC ni procesamiento de audio.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No hay política de muestreo, canales o ventanas.


**Corrección:** Añadir extracción MFCC con parámetros explícitos.


**Implementación recomendada:** Normalizar sample rate/canales, segmentar ventanas y devolver matriz de descriptores finitos; tratar silencio y formatos inválidos.


**Validación:** Señal sintética, silencio, clips cortos y audio inválido; dimensión y versión del extractor consistentes.


**Dependencias:** Almacenamiento de audio; interfaz ExtractFeatures.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Función de extracción | 0 | 0 | 0 |
| Descriptores MFCC | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.1.3: Cuantización Bag of Visual Audio Words


**Requisito:** Cuantización Bag of Visual Audio Words. PDF, página(s) 4, sección 2.4.1.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay vocabulario de centroides ni asignación visual/auditiva.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Descriptores locales por sí solos no son el vector K requerido.


**Corrección:** Implementar K-Means o Tree Quantization para construir el vocabulario.


**Implementación recomendada:** Entrenar con muestra reproducible, persistir K/centroides/versión y asignar cada descriptor al mismo vocabulario en ingesta y consulta.


**Validación:** Clusters conocidos, centroides vacíos, asignaciones reproducibles y reapertura del vocabulario.


**Dependencias:** 4.1.1–4.1.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| K-Means o Tree Quantization | 0 | 0 | 0 |
| Asignación de descriptores a K centroides | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.1.4: Histogramas multimedia con TF-IDF de dimensión K


**Requisito:** Histogramas multimedia con TF-IDF de dimensión K. PDF, página(s) 4, sección 2.4.1.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay histogramas ni TF-IDF de palabras multimedia.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Los vectores de términos de Parte 3 tampoco existirían aún ni sustituyen descriptores multimedia.


**Corrección:** Construir histogramas K y aplicar TF-IDF del corpus multimedia.


**Implementación recomendada:** Compartir matemáticas cuando sean compatibles, pero mantener vocabularios y estadísticas por modalidad/versiones; persistir dimensión K.


**Validación:** Histograma manual, suma de frecuencias, pesos y dimensión; objeto sin descriptores y consulta con misma transformación.


**Dependencias:** 4.1.3.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Frecuencias por palabra | 0 | 0 | 0 |
| Pesos TF-IDF | 0 | 0 | 0 |
| Vector dimensión K | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



#### Etapa 4.2: Indices y metricas



##### Paso 4.2.1: Índice IVF


**Requisito:** Índice IVF. PDF, página(s) 4, sección 2.4.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay IVF; el Heap relacional no agrupa vectores por centroides.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No hay inverted lists ni selección de probes.


**Corrección:** Implementar IVF propio.


**Implementación recomendada:** Persistir centroids/listas con IDs estables, nprobe configurable y reranking exacto con la métrica elegida.


**Validación:** Comparación con scan vectorial exacto, nprobe total como referencia, inserción/reapertura y Recall@10.


**Dependencias:** 4.1.4; representación de vectores y métricas.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Índice propio | 0 | 0 | 0 |
| Búsqueda vectorial | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.2.2: Índice HNSW


**Requisito:** Índice HNSW. PDF, página(s) 4, sección 2.4.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay HNSW ni grafo de vecinos.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** El R-Tree 2D no equivale a HNSW para alta dimensionalidad.


**Corrección:** Implementar HNSW propio.


**Implementación recomendada:** Construir niveles, selección de vecinos y búsqueda ef acotada; persistir IDs, grafo, semilla y parámetros M/ef.


**Validación:** Invariantes de niveles/aristas, vecino exacto en corpus pequeño, ef creciente, reapertura y Recall@10.


**Dependencias:** Vectores y métricas de 4.2.3–4.2.5.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Grafo jerárquico propio | 0 | 0 | 0 |
| Búsqueda vectorial | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.2.3: Métrica vectorial Euclidiana


**Requisito:** Métrica vectorial Euclidiana. PDF, página(s) 4, sección 2.4.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay métrica Euclidiana vectorial ni interfaz sobre vectores K.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** La distancia espacial 2D no acredita una métrica vectorial multimedia ni su integración.


**Corrección:** Implementar Euclidiana sobre vectores de dimensión validada.


**Implementación recomendada:** Calcular sqrt de suma de diferencias al cuadrado; fijar orientación de ranking (distancia ascendente o similitud descendente) y rechazar dimensiones/valores inválidos.


**Validación:** Vectores de cálculo manual, identidad, cero, dimensiones diferentes, valores no finitos y rankings coherentes en IVF/HNSW.


**Dependencias:** Representación de vectores finitos de dimensión K.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Distancia alta dimensión | 0 | 0 | 0 |
| Integración con búsqueda | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.2.4: Métrica vectorial Producto Punto


**Requisito:** Métrica vectorial Producto Punto. PDF, página(s) 4, sección 2.4.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay métrica Producto Punto vectorial ni interfaz sobre vectores K.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** La distancia espacial 2D no acredita una métrica vectorial multimedia ni su integración.


**Corrección:** Implementar Producto Punto sobre vectores de dimensión validada.


**Implementación recomendada:** Calcular suma de productos componente a componente; fijar orientación de ranking (distancia ascendente o similitud descendente) y rechazar dimensiones/valores inválidos.


**Validación:** Vectores de cálculo manual, identidad, cero, dimensiones diferentes, valores no finitos y rankings coherentes en IVF/HNSW.


**Dependencias:** Representación de vectores finitos de dimensión K.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Producto punto | 0 | 0 | 0 |
| Integración con búsqueda | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.2.5: Métrica vectorial Coseno


**Requisito:** Métrica vectorial Coseno. PDF, página(s) 4, sección 2.4.2.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay métrica Coseno vectorial ni interfaz sobre vectores K.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** La distancia espacial 2D no acredita una métrica vectorial multimedia ni su integración.


**Corrección:** Implementar Coseno sobre vectores de dimensión validada.


**Implementación recomendada:** Calcular producto punto dividido por normas, con política explícita para vector cero; fijar orientación de ranking (distancia ascendente o similitud descendente) y rechazar dimensiones/valores inválidos.


**Validación:** Vectores de cálculo manual, identidad, cero, dimensiones diferentes, valores no finitos y rankings coherentes en IVF/HNSW.


**Dependencias:** Representación de vectores finitos de dimensión K.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Coseno alta dimensión | 0 | 0 | 0 |
| Integración con búsqueda | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



#### Etapa 4.3: SQL multimedia



##### Paso 4.3.1: SQL multimedia SIMILAR_TO USING WITH METRIC


**Requisito:** SQL multimedia SIMILAR_TO USING WITH METRIC. PDF, página(s) 4, sección 2.4.3.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** El parser rechaza SIMILAR_TO, score multimedia y WITH METRIC.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No se resuelve objeto de consulta ni índice/métrica.


**Corrección:** Añadir la extensión SQL multimedia completa.


**Implementación recomendada:** Extraer el vector de consulta con vocabulario/versiones del índice; resolver USING y WITH METRIC; producir SIMILARITY_SCORE con orden coherente y límites.


**Validación:** Ejemplos imagen/audio del PDF, path inválido, índice/métrica inexistentes y resultados iguales al API vectorial.


**Dependencias:** 4.1–4.2 y funciones/TopK del parser.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| SIMILAR_TO con k | 0 | 0 | 0 |
| Selección IVF HNSW | 0 | 0 | 0 |
| WITH METRIC | 0 | 0 | 0 |
| SIMILARITY_SCORE y ordenamiento | 0 | 0 | 0 |


Peso del paso: 1; 4 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



#### Etapa 4.4: Experimentos multimedia



##### Paso 4.4.1: Comparación multimedia IVF HNSW y métricas


**Requisito:** Comparación multimedia IVF HNSW y métricas. PDF, página(s) 4, sección 2.4.4.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay comparación IVF/HNSW ni Euclidiana/coseno.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No hay índices o vectores experimentales.


**Corrección:** Construir experimento cruzado de ambos índices y ambas métricas.


**Implementación recomendada:** Fijar dataset/vectores/consultas y reportar parámetros de aproximación; distinguir precisión de velocidad.


**Validación:** Cada combinación con crudos y baseline exacto bajo su propia métrica.


**Dependencias:** 4.1–4.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| IVF frente a HNSW | 0 | 0 | 0 |
| Euclidiana frente a coseno | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.4.2: Datasets multimedia y k-NN requeridos


**Requisito:** Datasets multimedia y k-NN requeridos. PDF, página(s) 4, sección 2.4.4.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No existen datasets de 1k/10k/100k objetos multimedia ni consultas k=10.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Contar descriptores como objetos inflaría el tamaño del dataset.


**Corrección:** Preparar objetos, manifiestos y consultas reproducibles.


**Implementación recomendada:** Guardar objeto_id, modalidad, origen, hash, versión de extracción y vocabulario; usar diez vecinos por objeto de consulta.


**Validación:** Conteo de objetos exacto y transformación de consulta consistente en los tres tamaños.


**Dependencias:** 4.1; selección de datasets.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| 1000 10000 100000 imágenes audios | 0 | 0 | 0 |
| k igual a 10 | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.4.3: Tiempos y memoria multimedia


**Requisito:** Tiempos y memoria multimedia. PDF, página(s) 4, sección 2.4.4.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay tiempos o memoria multimedia.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No se separan extracción, entrenamiento, construcción y búsqueda.


**Corrección:** Medir construcción del índice, consulta y uso de memoria.


**Implementación recomendada:** Registrar también fases auxiliares por separado para no atribuir extracción o K-Means a IVF/HNSW.


**Validación:** Métricas reales y agregadas desde crudos con parámetros y fases explícitos.


**Dependencias:** 4.4.1–4.4.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Tiempo construcción | 0 | 0 | 0 |
| Tiempo consulta | 0 | 0 | 0 |
| Memoria | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.4.4: Recall@10 multimedia


**Requisito:** Recall@10 multimedia. PDF, página(s) 4, sección 2.4.4.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay Recall@10 multimedia ni oracle exacto.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Scores aproximados no permiten deducir recall.


**Corrección:** Calcular vecinos exactos para cada consulta y métrica y comparar el top diez.


**Implementación recomendada:** Fijar convención de auto-coincidencia y empates; usar conjuntos de IDs de referencia independientes de IVF/HNSW.


**Validación:** Recall entre 0 y 1, casos manuales y curva frente a nprobe/ef; no usar relevancia textual como sustituto.


**Dependencias:** 4.2 y 4.4.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Oracle de vecinos | 0 | 0 | 0 |
| Recall@10 | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 4.4.5: Presentación experimental multimedia


**Requisito:** Presentación experimental multimedia. PDF, página(s) 4, sección 2.4.4.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No hay galería multimedia ni gráficas/recomendaciones.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** La galería debe mostrar casos reales, no imágenes conceptuales de resultados.


**Corrección:** Generar gráficas, galería de éxito/error y tabla comparativa.


**Implementación recomendada:** Enlazar consultas con objetos recuperados y referencia; reproducir audio o visualizar imágenes sin inventar éxito.


**Validación:** Cada caso trazable a su consulta, ranking y métrica; gráficas tiempo/tamaño y recomendaciones verificables.


**Dependencias:** 4.4.1–4.4.4.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Gráficas tiempo tamaño | 0 | 0 | 0 |
| Galería de éxito y error | 0 | 0 | 0 |
| Tabla de recomendaciones | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



### Parte 5: Aplicación



#### Etapa 5.1: Aplicacion del Anexo A



##### Paso 5.1.1: Aplicación real consume API REST o GraphQL del motor


**Requisito:** Aplicación real consume API REST o GraphQL del motor. PDF, página(s) 4–7, sección 2.5 y Anexo A.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** Existe API REST del motor y una consola administrativa, pero no una aplicación del Anexo A.


**Evidencia:** api/app.py:1; frontend/src/App.tsx:1


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** La consola SQL demuestra el motor; no constituye por sí sola una aplicación real de IA del dominio elegido.


**Corrección:** Elegir la aplicación y construir su flujo mediante el API propio.


**Implementación recomendada:** Crear un frontend/servicio de dominio que consuma endpoints del motor. Conservar FastAPI y las sesiones; evitar acceso directo a páginas/índices desde la interfaz.


**Validación:** Flujo de dominio completo con llamadas HTTP observables al motor propio y resultados reales.


**Dependencias:** Elección 5.1.4 y modalidades requeridas por esa opción.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Aplicación de dominio real | 0 | 0 | 0 |
| Consumo del API propio | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 5.1.2: Aplicación integra al menos dos tipos de datos


**Requisito:** Aplicación integra al menos dos tipos de datos. PDF, página(s) 4–7, sección 2.5 y Anexo A.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** El núcleo maneja filas y puntos por métodos distintos; ninguna aplicación pública integra dos tipos en una experiencia.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** Tener dos paquetes o tablas con coordenadas no demuestra integración multimodal de la aplicación.


**Corrección:** Integrar al menos dos modalidades en el flujo del dominio.


**Implementación recomendada:** Usar IDs y metadatos relacionales comunes y combinar búsquedas reales de las modalidades escogidas con reglas de fusión explícitas.


**Validación:** Una acción del usuario utiliza ambos tipos y el resultado permite rastrear las contribuciones de cada uno.


**Dependencias:** 5.1.4; partes funcionales de las modalidades escogidas.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Primer tipo funcional | 0 | 0 | 0 |
| Segundo tipo funcional | 0 | 0 | 0 |
| Integración en una experiencia | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 5.1.3: Interfaz de aplicación demuestra capacidades


**Requisito:** Interfaz de aplicación demuestra capacidades. PDF, página(s) 4–7, sección 2.5 y Anexo A.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** La GUI es una consola relacional; no hay chatbot, recomendaciones, timeline de audio ni reconocimiento facial.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** No existe demostración interactiva de la aplicación final.


**Corrección:** Añadir la interfaz del dominio elegido.


**Implementación recomendada:** Reutilizar componentes de sesión/error/resultados compatibles; diseñar entrada, salida y estados vacíos/error propios de la aplicación.


**Validación:** Usuario completa el caso principal del anexo sobre datos reales, con ambos tipos integrados.


**Dependencias:** 5.1.1–5.1.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Flujo de usuario del dominio | 0 | 0 | 0 |
| Resultados multimodales reales | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso 5.1.4: Una opción de aplicación del Anexo A


**Requisito:** Una opción de aplicación del Anexo A. PDF, página(s) 4–7, sección 2.5 y Anexo A.


**Estado:** ⬜ NO IMPLEMENTADO.


**Estado actual:** No se encontró una opción A/B/C/D elegida en los documentos o código de aplicación.


**Evidencia:** docs/auditoria/evidencias/inventario_codigo.json; docs/auditoria/evidencias/espacial_100k_real.json


**Evaluación:** No se encontró implementación que satisfaga este requisito en el snapshot auditado.


**Problemas:** La decisión pendiente impide fijar el backlog específico y comprobar sus componentes obligatorios.


**Corrección:** Registrar una sola opción y su contrato de aceptación.


**Implementación recomendada:** A: PDF/chunks/metadata→SPIMI→recuperación→LLM; B: catálogo, imágenes/ubicación y fusión de recomendaciones; C: MFCC y segmentos/timeline de coincidencias; D: embeddings, cámara y búsqueda con objetivo de eficiencia. No implementar las cuatro.


**Validación:** Opción documentada y todos sus componentes demostrados; lo opcional del anexo debe seguir siendo opcional.


**Dependencias:** Decisión de producto y dominio; no requiere reescribir Parte 1.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Opción elegida | 0 | 0 | 0 |
| Componentes obligatorios de esa opción | 0 | 0 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



### Entregables transversales



#### Etapa T.1: Entrega



##### Paso T.1.1: Código en repositorio GitHub o GitLab


**Requisito:** Código en repositorio GitHub o GitLab. PDF, página(s) 5, sección 3.


**Estado:** ✅ COMPLETO.


**Estado actual:** Repositorio Git local con origin GitHub y HEAD publicado en main.


**Evidencia:** docs/auditoria/evidencias/commit.txt; docs/auditoria/evidencias/remoto_verificado.txt


**Evaluación:** git ls-remote confirmó el mismo commit fabe4cc en HEAD/main remoto.


**Problemas:** El PDF y DOCX actuales son cambios locales del usuario sin commit; se preservan. El requisito de código publicado sí está satisfecho.


**Corrección:** Ninguna corrección del código publicado identificada.


**Implementación recomendada:** Mantener publicación incremental y no confundir disponibilidad remota del código con la del video o presentación.


**Validación:** Comparar SHA local y remoto, y verificar los cambios autorizados antes de futuras publicaciones.


**Dependencias:** Git y acceso remoto.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Código versionado | 1 | 1 | 0 |
| Remoto configurado | 1 | 1 | 0 |
| Publicación accesible verificada | 1 | 1 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso T.1.2: README con arquitectura y organización


**Requisito:** README con arquitectura y organización. PDF, página(s) 5, sección 3.


**Estado:** 🟡 PARCIAL.


**Estado actual:** README describe arquitectura/organización relacional; docs/spatial amplía decisiones espaciales.


**Evidencia:** README.md:527 (## Organización); docs/informe/informe_parte_01.md:41 (PageManager); PROJECT_CONTEXT.md:2616 (Stage 10 remains pending)


**Evaluación:** Dos criterios de tres satisfechos. Persisten rutas antiguas a PLAN.md/ETAPA_XX y una descripción del árbol que omite engine/database y engine/spatial.


**Problemas:** También se afirma que PageManager es el único dueño de disco, aunque temporales, undo, manifiestos y R-Tree tienen E/S propia. La coordinación mezcla cierres actuales con secciones obsoletas.


**Corrección:** Corregir rutas y estados vigentes; precisar que PageManager centraliza páginas relacionales, no toda E/S del sistema.


**Implementación recomendada:** Editar documentos de forma localizada y marcar historias como históricas. Actualizar diagrama con owner y ruta espacial; conservar decisiones válidas.


**Validación:** Enlaces locales resuelven, diagrama coincide con imports y responsabilidades y no se declaran como completos requisitos pendientes.


**Dependencias:** Hallazgos de esta auditoría; no requiere cambio de arquitectura.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Arquitectura documentada | 1 | 1 | 0 |
| Organización documentada | 1 | 1 | 0 |
| Correspondencia con código actual | 1 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 100.00 %; cumplimiento 66.67 %; pendiente 0.00 %.



##### Paso T.1.3: Manual de instalación


**Requisito:** Manual de instalación. PDF, página(s) 5, sección 3.


**Estado:** ✅ COMPLETO.


**Estado actual:** README y demo.md explican entorno, instalación de extras, carga inicial, compilación y arranque.


**Evidencia:** README.md:217 (## Requisitos e instalación); docs/demo.md:1; docs/auditoria/evidencias/preparacion_entorno.log


**Evaluación:** Instalación nueva, build y arranque reales se verificaron sobre una copia limpia. Las instrucciones de ejecutar desde raíz permiten importar api y scripts.


**Problemas:** El launcher no reinicia inmediatamente en POSIX y Ctrl+C sale anómalamente; son defectos de ejecución documentados aparte. Un wheel instala solo engine.


**Corrección:** Corregir el launcher de forma localizada. Si se ofrece distribución instalable completa, incluir api/benchmarks o mantener el requisito de clonar y ejecutar desde raíz.


**Implementación recomendada:** Conservar el procedimiento actual y fijar versiones del entorno de demostración para reproducibilidad.


**Validación:** Clon limpio, Python >=3.11, extras, npm ci/build, prepare, health, GUI y cierre/reinicio después de corregir los fallos.


**Dependencias:** Dependencias auxiliares y datasets de demostración.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Instrucciones y dependencias | 1 | 1 | 0 |
| Arranque reproducible | 1 | 1 | 0 |


Peso del paso: 1; 2 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso T.1.4: Video demo de 5 a 10 minutos


**Requisito:** Video demo de 5 a 10 minutos. PDF, página(s) 5, sección 3.


**Estado:** ⚠️ NO VERIFICADO.


**Estado actual:** Existe un guion de aproximadamente ocho minutos para Parte 1; no se encontró video ni enlace a una grabación.


**Evidencia:** docs/informe/guion_video.md:1; docs/ETAPA_10_AUDIT.md:52 (grabación a cargo del equipo)


**Evaluación:** El guion no demuestra existencia, duración ni funcionalidades de un video. Podría existir externamente; no hay evidencia disponible.


**Problemas:** No se puede acreditar este entregable ni el video final de todas las modalidades.


**Corrección:** Grabar y aportar archivo/enlace comprobable, o incorporar evidencia del video externo si ya existe.


**Implementación recomendada:** Adaptar el guion al avance y después a todas las funcionalidades finales; grabar ejecución real, con duración 5–10 minutos.


**Validación:** Abrir la grabación, verificar duración y contrastar cada capacidad mostrada con el sistema.


**Dependencias:** Funcionalidades que se demuestran; cierre final de las cinco partes.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Video disponible | 0 | 0 | 0 |
| Duración requerida | 0 | 0 | 0 |
| Funcionalidades demostradas | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 0.00 %; cumplimiento 0.00 %; pendiente 0.00 %.



##### Paso T.1.5: Informe incremental técnico


**Requisito:** Informe incremental técnico. PDF, página(s) 5, sección 3.


**Estado:** ✅ COMPLETO.


**Estado actual:** Informe Parte 1 contiene arquitectura, dominio, algoritmos y experimentos; docs/spatial registra el incremento espacial y sus límites.


**Evidencia:** docs/informe/informe_parte_01.md:1; docs/EXPERIMENTOS.md:1; docs/spatial.md:1


**Evaluación:** Hay documentación incremental real del avance actual. No se exige que describa como terminadas partes futuras todavía ausentes.


**Problemas:** La evaluación de arquitectura del informe debe corregirse según T.1.2, y el apartado experimental debe reconocer la brecha de carga mixta.


**Corrección:** Mantener el informe incremental, corregir afirmaciones concretas e incorporar resultados nuevos conforme se implementen.


**Implementación recomendada:** Enlazar capítulos por parte con evidencia de algoritmo, dominio, método, datos y limitaciones; no usar esta auditoría como evidencia de una implementación futura.


**Validación:** Cada incremento tiene explicación y resultados trazables; la entrega final cubre las cinco partes y sus experimentos reales.


**Dependencias:** Avances funcionales y experimentales; T.1.2.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Diseño arquitectónico | 1 | 1 | 0 |
| Dominio de datos | 1 | 1 | 0 |
| Algoritmos | 1 | 1 | 0 |
| Sección experimental | 1 | 1 | 0 |
| Cobertura del avance multimodal | 1 | 1 | 0 |


Peso del paso: 1; 5 criterios iguales. Cobertura 100.00 %; cumplimiento 100.00 %; pendiente 0.00 %.



##### Paso T.1.6: Presentación final de 15 minutos y 5 de preguntas


**Requisito:** Presentación final de 15 minutos y 5 de preguntas. PDF, página(s) 5, sección 3.


**Estado:** 🟡 PARCIAL.


**Estado actual:** Hay un esquema textual de presentación de Parte 1, estimado en 12–15 minutos; no hay exposición final acreditada.


**Evidencia:** docs/informe/presentacion.md:1


**Evaluación:** Existe material y planificación temporal; la exposición final de cinco partes y 5 minutos de preguntas no está verificada.


**Problemas:** Un esquema preparatorio no prueba que la presentación final se haya realizado ni que cubra todo el proyecto.


**Corrección:** Completar material de las cinco partes, ensayar 15 minutos y reservar 5 para preguntas; aportar evidencia al llegar al hito.


**Implementación recomendada:** Reutilizar el esquema y cifras válidas; añadir modalidades/aplicación y explicar limitaciones de forma fiel.


**Validación:** Ensayo cronometrado, recorrido de capacidades reales y evidencia de la exposición final según el curso.


**Dependencias:** Entrega final de las cinco partes.


| Criterio de aceptación | I | V | P |
|---|---:|---:|---:|
| Material de presentación | 1 | 1 | 0 |
| Duración prevista | 1 | 1 | 0 |
| Presentación final acreditada | 0 | 0 | 0 |


Peso del paso: 1; 3 criterios iguales. Cobertura 66.67 %; cumplimiento 66.67 %; pendiente 0.00 %.




## 9. Índice de evidencias y reproducción

| Artefacto | Contenido |
|---|---|
| enunciado.txt y pdf_sha256.txt | Extracción completa por páginas y huella del PDF oficial |
| git_status_inicial.txt, commit.txt, remotos.txt, remoto_verificado.txt | Base local, cambios del usuario y remoto verificado |
| REQUISITOS_FIJADOS.json y catalogo.py | Denominador y criterios anteriores a puntuación |
| EVALUACION.json y evaluar.py | Juicios, nueve campos y referencias resueltas contra archivos reales |
| PORCENTAJES.json y MATRIZ_REQUISITOS.csv | Cálculo exacto por etapa/parte/global y trazabilidad exportable |
| preparar_entorno.sh, preparacion_entorno.log, verificar.sh, resultados_comandos.txt | Comandos efectivos y estados de salida |
| entorno_y_limpieza.json | Versiones completas instaladas y puertos 18765–18769 sin servidor de auditoría activo al cerrar |
| pytest.log/xml y frontend_*.log | Regresión, warnings, tests/tipos/build |
| demo_threads.json, integracion_http.json/log | Hilos y servidor real, con los tres fallos sin ocultar |
| probar_navegador.py, navegador.json/png, navegador_dom.html, servidor_navegador.log | Interacción real en dos sesiones y captura |
| navegador_intento1/2/3.json, bibliotecas_navegador.log, playwright_install.log | Fallos iniciales del entorno y preparación posterior |
| probar_espacial.py, espacial_100k_real.json/log | Diferencial independiente con datos reales y ejemplos SQL rechazados |
| probar_heap_llegada.py y heap_orden_llegada.json | Reproducción mínima del defecto de llegada |
| inspeccionar.py, inventario_codigo.json, arquitectura.json | Imports, símbolos, ciclos explícitos y huellas |
| experimentos_auditados.json | 455 registros oficiales, repetición/configuración/mezclas/procedencia |
| comparador_entorno_actual.json | Docker CLI presente, daemon no disponible; no acredita PostGIS actual |
| contrastar_reportes.py, reporte_contrastado.json, reporte_regenerado/ | Correspondencia exacta de tablas y 11 gráficos |
| repeticion_1k.jsonl y repeticion_reportes.log | Ensayo actual reducido, explícitamente diagnóstico |
| COMANDOS.md | Cómo repetir en otra base temporal y recalcular la matriz |
| integridad_final.json y git_status_final.txt | Concordancia del catálogo/matriz y preservación del trabajo original |
| MANIFIESTO_SHA256.json | Huellas de artefactos de esta auditoría |

Distribución de los 2.968 tests Python aprobados, sin sumarlos al porcentaje: almacenamiento 964; índices 520; operadores 400; query 316; catálogo 207; API 155; integración 137; base 97; transacciones 91; espacial 52; database 21; benchmarks 8.

Para recalcular desde la raíz: ejecutar catalogo.py, evaluar.py y redactar.py (paths en evidencias/). Para verificar sin tocar datos existentes: seguir COMANDOS.md y elegir directorios nuevos. No incorporar estas reproducciones a los tests del proyecto; permanecen como evidencia de auditoría. El manifiesto se actualiza después de cualquier regeneración de artefactos.

La auditoría asigna evaluación trazable a todos los requisitos y una acción/aceptación a cada brecha. Declarar una funcionalidad ausente, un artefacto externo no acreditado o un ensayo no ejecutado no equivale a ejecutarlo. El cierre de esta auditoría no constituye cierre de las partes pendientes del proyecto.

