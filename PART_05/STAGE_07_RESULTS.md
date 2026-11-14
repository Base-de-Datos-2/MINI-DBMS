# Parte 5 — Entrega y reproducción

La aplicación y el material de entrega se verificaron localmente en
`parte5-fase4-en_adelante`. Quedan pendientes la reproducción independiente
por un compañero y la integración de los commits según el flujo acordado.
La [revisión del responsable de la fase 4](STAGE_04_RESULTS.md#revisión-del-responsable-y-traspaso-a-la-fase-5)
sigue pendiente de aceptación formal.

## Material de entrega

| Entregable | Contenido |
| --- | --- |
| [Manual](../README.md#parte-5--preparación-del-corpus-académico) | Descarga de las versiones fijadas, preparación y verificación del corpus, configuración privada, compilación y arranque unificado. |
| [Informe incremental](../docs/informe/informe_parte_05.md) | Diseño de las dos tablas, publicación SPIMI, recuperación REST, selección de pasajes y límites de las respuestas. |
| [Video de demostración](../docs/informe/demo_final.mp4) | 8:15. Montaje de capturas reales con subtítulos en español. Muestra búsqueda relacional con y sin índice, la prueba de hilos, consultas espacial, textual y multimedia, y recuperación, metadatos y respuesta generada del RAG. |
| [Presentación](../docs/informe/presentacion_final.pptx) | 11 diapositivas, con notas para 15 minutos de defensa y 5 de preguntas. Incluye el flujo de Parte 5 y una respuesta real con el pasaje abierto. |
| [Contexto de arquitectura](../PROJECT_CONTEXT.md#part-5-academic-preparation-stage-2) | Decisiones de preparación, recuperación, generación y chat. |

El video y la presentación reutilizan los resultados de las Partes 1–4.
La Parte 5 se verificó con el corpus fijado y preguntas de aceptación.
[Mediciones conservadas](../README.md#experimentos-y-gráficos) · [Validación de la fase 6](STAGE_06_RESULTS.md)

## Reproducción local registrada

Se prepararon las demos de las Partes 1–4 y un corpus académico desde los
diez PDF fijados en un directorio vacío. La verificación devolvió `PASS`,
10 papers y 393 pasajes de 249 a 254 palabras. El índice nuevo tiene
generación `06b7c2cb3ca943ee96426bd273ac733b`. La huella lógica
`640e6f06612e1d005de3cbd43fad81828c3ffbd1b99ead854e69688ef8842d36`
coincide con la preparación aceptada.

El servidor unificado abrió las cinco partes y sirvió la compilación de
producción. Pasó el chequeo controlado de Chrome 157.0.8103.52. El ensayo
real del manual con `gpt-6-luna` respondió la pregunta de HNSW con los
pasajes `1`, `3` y `5` del paper 1. El ID de solicitud fue
`0d403900dea746e8bede76aeaa6980b0`. La captura que aparece en el video y
la presentación se obtuvo en una consulta real desde el navegador, con ID
`b67cb8f79ceb46999841a08e5c10d6fc`.

La demo de concurrencia devolvió `1` en la ejecución sin protección y `2`
con locks y en serie. La primera ejecución dentro del aislamiento del agente
encontró archivos temporales bloqueados. La repetición con el mismo comando
fuera de ese aislamiento produjo los resultados incluidos en el video.

## Reproducción independiente pendiente

Un integrante del equipo puede seguir el manual en su propia máquina y
compartir tres resultados técnicos para el acta de entrega.

1. Resultado de `setup_academic.py --verify-only` sobre una preparación
   nueva, con cantidades y huella lógica.
2. Resultado de la pregunta `How does HNSW use a hierarchy of proximity graphs?`
   en **RAG académico**, acompañado del ID de solicitud y los IDs de los
   pasajes mostrados.
3. Fecha, iniciales y cualquier diferencia de configuración o resultado.

La clave y los archivos locales de configuración permanecen en el equipo
que realiza cada prueba.
