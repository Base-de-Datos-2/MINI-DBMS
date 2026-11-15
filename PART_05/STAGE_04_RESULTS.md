# Parte 5 — Resultados de la fase 4

- Estado general `PENDING_HUMAN`. Queda la revisión de las respuestas y sus fuentes por JPCP según H3–H6.
- Estado técnico `PASS`. Verificación del 2026-11-14.
- Base `8bca0ff3a4a2c238d63da4d98bcaf358eace8e07`. Implementación verificada `6aca2297892f87b41ff525d21d7cc219f0ed073c` en `parte5-fase4-en_adelante`.
- Windows, CPython 3.12.6, Unicode 15.0.0, OpenAI 3.48.0, python-dotenv 1.2.4, pypdf 7.0.0, httpx2 2.13.1, FastAPI 0.142.2, Uvicorn 0.54.0 y pytest 8.4.2.
- Raíz unificada `data/generated/todas`, base académica `data/generated/todas/parte5`, REST interno `http://127.0.0.1:8000/parte5`.

## Endpoint y configuración

`POST /parte5/api/rag/ask` valida `{"question":"…"}` y recupera hasta tres
pasajes con BM25 mediante `POST /parte5/api/text/query`. Obtiene los metadatos
de cada paper distinto mediante `POST /parte5/api/query`. Tras cerrar el
cliente de recuperación, solicita una respuesta a `gpt-6-luna` mediante la
API Responses y adjunta los mismos pasajes y metadatos recuperados. El
adaptador usa `store=False`, 45 segundos de timeout y cero reintentos.

El arranque carga el `.env` privado de la raíz y da precedencia a las variables
del proceso. El diagnóstico reportó `CONFIGURED`. La autenticación y el
acceso al modelo se comprobaron con las dos solicitudes reales descritas
abajo. Los archivos locales `.env` y `.env.example` quedaron fuera de los
commits. `pip check` informó `No broken requirements found.`

La respuesta exitosa contiene `status`, `answer` y `sources`. Los errores usan
el código y el identificador de solicitud del [contrato HTTP](CONTRACT_P5.md#chat-application).
Las pruebas cubren entrada inválida (`422`), cuerpo demasiado grande (`413`),
motor no disponible (`503`), respuesta inválida del motor (`502`), generación
sin clave (`503`), fallo del proveedor (`502`) y tiempo de espera (`504`).

## Pregunta sobre HNSW

> How does HNSW use a hierarchy of proximity graphs?

Respuesta textual devuelta, con estado `answered`.

> HNSW builds a multi-layer hierarchy of proximity graphs, with each layer covering a nested subset of the stored elements. An element’s highest layer is chosen randomly, with the probability of appearing at higher layers decreasing exponentially. Links at different layers correspond to different distance scales. Search begins at the upper layer and uses those longer-range connections to navigate toward promising regions, then proceeds through lower layers for finer-grained search [S1]. This hierarchical, scale-separated routing is described as improving performance over a single NSW graph and enabling logarithmic complexity scaling [S1][S2].

Las tres fuentes pertenecen al paper 1, *Efficient and robust approximate
nearest neighbor search using Hierarchical Navigable Small World graphs*, de
Yu. A. Malkov y D. A. Yashunin (2018 en el manifiesto). Los puntajes BM25 se
redondean a seis decimales. Las citas textuales son fragmentos del texto que
recibió el modelo. [PDF fijado en el corpus](https://arxiv.org/pdf/1603.09320v4)

| Fuente | Chunk · posición | BM25 | Contenido recuperado |
| --- | --- | ---: | --- |
| `S1` | 1 · 1 | 17.626160 | El resumen describe grafos sobre subconjuntos anidados, el sorteo de la capa máxima con distribución de decaimiento exponencial y los enlaces por escala de distancia. También indica “Starting search from the upper layer together with utilizing the scale separation”. [Pág. 1](https://arxiv.org/pdf/1603.09320v4#page=1) |
| `S2` | 3 · 3 | 12.267421 | La introducción señala la selección del nodo de entrada y la separación de los enlaces por escala. Atribuye a HNSW “a much better logarithmic complexity scaling”. [Pág. 1](https://arxiv.org/pdf/1603.09320v4#page=1) |
| `S3` | 5 · 5 | 10.361060 | El trabajo relacionado describe el recorrido voraz y el crecimiento del número de saltos en NSW. El modelo recibió este pasaje y citó `S1` y `S2` en su respuesta. [Pág. 2](https://arxiv.org/pdf/1603.09320v4#page=2) |

`S1` respalda directamente la jerarquía, la distribución, las escalas y el
inicio en la capa superior. El descenso para refinar la búsqueda es una
inferencia de la descripción por escalas en `S1`. Ese pasaje no describe
explícitamente la transición entre capas. La última frase atribuye a los
autores el mejor escalamiento descrito en `S1` y `S2`. Los IDs y el orden
coinciden con la verificación de la fase 3.

## Contexto irrelevante, cero coincidencias y entrada inválida

> How do I change the oil in a 2015 Toyota Corolla?

Respuesta textual devuelta, con estado `answered`.

> The supplied evidence is insufficient. The passages discuss information retrieval and vector-quantization research, not oil changes for a 2015 Toyota Corolla [S1][S2][S3].

| Fuente | Chunk · paper · posición | BM25 | Contenido recuperado |
| --- | --- | ---: | --- |
| `S1` | 143 · 4 · 24 | 10.927899 | *The Faiss library* (2024). Describe rotaciones de vectores, PCA y cuantización. [PDF](https://arxiv.org/pdf/2401.08281v1) |
| `S2` | 362 · 9 · 34 | 7.576596 | *Approximate Nearest Neighbor Negative Contrastive Learning for Dense Text Retrieval* (2020). Presenta ejemplos de ranking y casos de error de recuperación. [PDF](https://arxiv.org/pdf/2007.00808v1) |
| `S3` | 325 · 8 · 50 | 7.373409 | *BEIR: A Heterogenous Benchmark for Zero-shot Evaluation of Information Retrieval Models* (2021). Muestra ejemplos de distintas colecciones del benchmark. [PDF](https://arxiv.org/pdf/2104.08663v1) |

Los títulos, autores completos y años de los cuatro papers se pueden
contrastar por ID con el [manifiesto del corpus](corpus.json). Los comandos de
reproducción imprimen los pasajes completos desde el motor, sin llamar a
OpenAI.

| Entrada | Resultado observado | Solicitud | Tiempo HTTP |
| --- | --- | --- | ---: |
| `zqxacademicnonmatch2026` | `200`, `no_context`, `No relevant passages were found in the selected papers.`, `sources: []`. Sin llamada al proveedor. | `77259f33622943b6a463908a511f9bbb` | 0.231 s |
| Tres espacios | `422`, `INVALID_REQUEST`. La validación terminó antes de consultar el motor o al proveedor. | `c87e763effc5450c9ce6d04586e034fb` | 0.014 s |

## Solicitudes reales al proveedor

Las dos respuestas generadas tuvieron HTTP `200`. El modelo solicitado y
devuelto fue `gpt-6-luna` en ambas. Los tiempos y tokens corresponden a esta
ejecución.

| Pregunta | ID HTTP | ID de respuesta de OpenAI | Tiempo HTTP / proveedor | Tokens entrada / salida |
| --- | --- | --- | ---: | ---: |
| HNSW | `b2b1768b78d4473bbacdc18b4829461b` | `resp_0aad46d6d8dcf1ca016af83230c27887d1946057d87f89b1a6` | 6.017 / 4.073 s | 1 301 / 119 |
| Toyota Corolla | `54516a48fdbb4e22886200b24089f677` | `resp_03785a897b48b16c016af83233ec7887d1b78629cd2a8801aa` | 1.839 / 1.770 s | 1 473 / 42 |

## Pruebas automatizadas e integración HTTP

La regresión indicada por A6.2 dio **219 aprobadas y 2 omitidas en 88.06 s**
con advertencias tratadas como errores. Las dos omisiones en Windows
corresponden a pruebas POSIX de reutilización de sockets y `SIGINT` en el
lanzador. Las pruebas usan un proveedor simulado y credenciales ficticias.

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -B -X utf8 -m pytest -q -rs -W error -p no:cacheprovider --basetemp tmp/p5_stage4_full_focused tests/part5 tests/api/test_unified.py tests/api/test_launcher.py tests/api/test_http.py tests/api/test_sessions.py tests/api/test_database.py tests/text/test_text_http_integration.py tests/text/test_4b_5_real_http_acceptance.py tests/test_architecture.py
& $P5Python -B -X utf8 -m pip check
git diff --check
```

Una prueba inicia Uvicorn en un puerto real con datos Heap y SPIMI, realiza
la recuperación por el mismo puerto y retiene la generación simulada. El
servidor responde a `/parte5/api/health` mientras esa generación espera.
La prueba también comprueba la identidad de los pasajes que recibe el
generador y devuelve el endpoint, y el cierre del servidor y sus propietarios.

## Reinicio y aislamiento de las partes

Un proceso nuevo cargó el mismo `.env` sin volver a ingresar la clave. Tras
reiniciar, la consulta sin coincidencias devolvió `no_context` con la Parte 5
en solo lectura. La verificación del corpus tras el cierre confirmó `PASS`.

| Indicador del corpus local | Valor conservado |
| --- | --- |
| Contenido | 10 papers y 393 pasajes |
| Generación SPIMI | `dc7a8acb4c4c43e5a7ff2e5bb23de040` |
| SHA-256 lógico | `640e6f06612e1d005de3cbd43fad81828c3ffbd1b99ead854e69688ef8842d36` |

El SHA-256 coincide con la fase 3. La preparación local de esta máquina
publicó una generación propia antes de la prueba, que se conservó durante
el reinicio. En un segundo servidor aislado, las cinco partes dieron HTTP
`200` en sus rutas de salud sin clave de OpenAI. Se usaron las demos de las
Partes 1–3, las muestras multimedia de prueba para la Parte 4 y una copia
del corpus académico para la Parte 5. La ruta RAG dio `404` en las Partes
1–4. En la Parte 5 dio `503 RAG_NOT_CONFIGURED` con pasajes recuperados y
`200 no_context` sin pasajes.

## Reproducción

Con el entorno, el corpus y el `.env` local configurados según el
[README](../README.md#parte-5--generación-de-respuestas-con-fuentes), inicia
el servidor. El comando de diagnóstico solo muestra presencia de la clave.

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 -m api.academic_config
& $P5Python -X utf8 -m api --all --data-dir data/generated/todas --host 127.0.0.1 --port 8000
```

Desde otra terminal, recupera el texto completo de las fuentes de las dos
preguntas sin llamar al proveedor. Para reproducir la respuesta generada,
usa el `POST` del README. Cada pregunta con pasajes y una clave configurada
puede generar un cargo.

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
$base = "http://127.0.0.1:8000/parte5"
& $P5Python -X utf8 scripts/check_academic_retrieval.py --base-url $base --question "How does HNSW use a hierarchy of proximity graphs?"
& $P5Python -X utf8 scripts/check_academic_retrieval.py --base-url $base --question "How do I change the oil in a 2015 Toyota Corolla?"
```

Con el servidor detenido, comprueba la huella del corpus.

```powershell
& $P5Python -X utf8 scripts/setup_academic.py --verify-only --data-dir data/generated/todas/parte5
```

## Revisión del responsable y traspaso a la fase 5

La revisión H3–H6 requiere que JPCP contraste las afirmaciones de HNSW con los
pasajes, confirme la respuesta de evidencia insuficiente y revise los
resultados técnicos registrados aquí. La validación de citas comprueba que
las etiquetas identifican pasajes entregados. Su respaldo semántico se
evalúa leyendo esos pasajes. La aceptación de contenido queda pendiente.

El panel de la fase 5 puede enviar `{question}` al endpoint relativo de la
Parte 5. Durante la llamada debe mostrar el estado de espera. Al recibir
`answered`, presenta `answer` y los registros de `sources` como texto, incluso
si la respuesta indica que la evidencia es insuficiente. `no_context`
representa una búsqueda vacía. Los errores HTTP usan `error.code`,
`error.message` y `error.request_id`. El servidor sigue resolviendo la
configuración y el acceso al proveedor. El panel dedicado queda para la
fase 5.
