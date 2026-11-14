# Parte 5. Chat académico con documentos PDF

La aplicación permite preguntar por trabajos de recuperación de información
y consultar el pasaje que respalda cada respuesta. Integra texto indexado y
metadatos relacionales mediante la API REST de MINI-DBMS. El servidor
unificado presenta la aplicación en la pestaña **RAG académico**.

## Corpus y almacenamiento

El [manifiesto del corpus](../../PART_05/corpus.json) registra diez artículos,
sus versiones de arXiv, sus hashes SHA-256 y sus metadatos. `pypdf` extrae el
texto en orden de página. El preparador normaliza espacios y reparte cada
paper en pasajes equilibrados cerca de 250 palabras. Verifica el intervalo de
200 a 500 palabras y el tamaño de la fila serializada, incluida la metadata
de la fila. La preparación publicada produjo 393 pasajes de 249 a 254
palabras. La fila de pasaje más grande ocupó 2395 de los 4079 bytes admitidos.
[Preparación y resultados](../../PART_05/STAGE_02_RESULTS.md)

| Tabla Heap | Campos | Uso |
| --- | --- | --- |
| `papers` | `paper_id`, `authors`, `year`, `title`, `abstract` | Metadatos bibliográficos que consulta el motor SQL. |
| `chunks` | `chunk_id`, `paper_id`, `position`, `content` | Texto de los pasajes. `paper_id` identifica el artículo y `position` conserva el orden dentro de él. |

El preparador verifica la asociación entre las tablas y los IDs de los
pasajes. Reutiliza la publicación de la Parte 3 para construir SPIMI sobre
`chunks.content`, sellar la colección y registrar el índice persistente.
Cada arranque abre la base publicada en modo de solo lectura.

## Consulta y generación

1. React envía la pregunta a `POST /parte5/api/rag/ask`, dentro del prefijo
   REST de la Parte 5.
2. El backend consulta `POST /parte5/api/text/query` con BM25 y un máximo de
   tres resultados. El motor usa el índice invertido SPIMI y devuelve los
   pasajes en orden de puntaje.
3. El backend obtiene los metadatos con `POST /parte5/api/query`. Ejecuta
   una consulta SQL por `paper_id` distinto y asocia cada fila al pasaje
   correspondiente. Asigna `S1`, `S2` y `S3` en orden de recuperación.
4. Si recuperó pasajes, el backend envía la pregunta, los textos y sus
   etiquetas a OpenAI Responses. El modelo devuelve el texto de la
   respuesta. La aplicación adjunta las fuentes consultadas y comprueba
   que las etiquetas citadas correspondan a pasajes entregados.
5. El chat muestra la respuesta y las fuentes desplegables con título,
   autores, año y texto. Si la recuperación queda vacía, muestra
   `no_context`. Si falla el proveedor, muestra el error y permite reenviar
   la pregunta.

La clave se lee en el servidor y el navegador envía solo la pregunta.
[Contrato de la API](../../PART_05/CONTRACT_P5.md#chat-application)

## Validación y límites

La revisión de aceptación contrastó cuatro respuestas académicas con los
pasajes recuperados. Las dos preguntas ajenas al corpus recibieron una
respuesta de evidencia insuficiente. Una consulta sin coincidencias omitió
la generación. Tras reiniciar se conservaron la huella lógica, la generación
del índice y el orden de los resultados BM25 de las siete preguntas.
[Resultados y respuestas completas](../../PART_05/STAGE_06_RESULTS.md)

BM25 ordena coincidencias de términos. Un pasaje puede tener puntaje alto y
carecer del dato que la pregunta pide. Las etiquetas permiten localizar la
fuente. El respaldo de cada afirmación se comprueba leyendo el pasaje. La
base se prepara fuera de línea con un corpus fijo, y el historial del chat
dura hasta que se recarga la página. La generación requiere acceso al modelo
configurado. [Manual de preparación y uso](../../README.md#parte-5--preparación-del-corpus-académico)
