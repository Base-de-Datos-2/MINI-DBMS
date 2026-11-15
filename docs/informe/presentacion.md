# Esquema de la presentación final — MINI-DBMS

## Defensa de las cinco partes (15 min + 5 min de preguntas)

La [presentación PowerPoint](presentacion_final.pptx) incorpora los gráficos
originales y una captura de una respuesta real del chat. Las notas del
presentador indican qué demostrar en vivo en cada tramo.

| Tiempo | Tema | Evidencia y demostración |
| --- | --- | --- |
| 0:00–1:30 | Alcance y arquitectura | Cinco pestañas y un servidor. Explica el flujo desde React y la API hasta el parser, el motor y el disco. [Arquitectura](../../README.md#arquitectura) |
| 1:30–4:20 | Almacenamiento, SQL y concurrencia | Heap, secuencial, B+ y hash. Demuestra un plan con y sin índice, y el resultado de la prueba de hilos. [Parte 1](informe_parte_01.md) |
| 4:20–6:05 | Consultas espaciales | Ventana por radio, mapa, R-Tree y comparación con GiST. [Experimentos espaciales](../EXPERIMENTOS_ESPACIALES.md) |
| 6:05–8:05 | Búsqueda textual | SPIMI, TF-IDF/coseno, BM25 y un `MATCH` con `SCORE()`. Muestra las curvas de consultas y relevancia. [Parte 3](informe_parte_03.md) |
| 8:05–10:10 | Búsqueda multimedia | Vocabulario, TF-IDF, IVF y HNSW. Ejecuta los ejemplos de imagen y audio. Señala la comparación de Recall@10 de imágenes. [Parte 4](informe_parte_04.md) |
| 10:10–13:30 | Aplicación RAG | Presenta `papers` y `chunks`. Muestra BM25, la fila relacional y la respuesta de OpenAI con un pasaje desplegado. [Parte 5](informe_parte_05.md) · [Secuencia de demo](guion_video.md#secuencia-de-la-parte-5) |
| 13:30–15:00 | Resultados y límites | Resume qué decisiones respaldan las mediciones. Explica el límite de la coincidencia léxica y cómo el usuario verifica una cita. Muestra la evidencia tras reiniciar. [Validación RAG](../../PART_05/STAGE_06_RESULTS.md) |
| 15:00–20:00 | Preguntas | Consulta las cuatro comparaciones, el contrato HTTP y las respuestas de aceptación si se necesita el detalle. |

**Preguntas sobre el RAG**

- *¿Dónde se almacenan los metadatos?* `papers` es una tabla Heap. El
  backend consulta sus filas por SQL mediante la API y las asocia por `paper_id`.
- *¿Qué decide qué texto recibe OpenAI?* BM25 ordena los pasajes del índice
  SPIMI. El backend toma hasta tres y les asigna etiquetas según su orden.
- *¿Qué pasa si los términos coinciden y el texto carece de la respuesta?*
  El modelo puede expresar que la evidencia es insuficiente. El chat muestra
  el contexto para revisarlo. Con cero coincidencias se omite OpenAI.

## Material de apoyo de la Parte 1

El esquema ampliado de la demo relacional conserva las referencias a los
gráficos de `docs/EXPERIMENTOS.md`.

| # | Diapositiva | Contenido | Fuente |
|---|---|---|---|
| 1 | Título | Minigestor de Base de Datos Multimodal — Parte 1 relacional; integrantes | — |
| 2 | Objetivo | Motor relacional desde cero: almacenamiento, índices, SQL, transacciones, GUI, experimentos; sin DBMS por debajo | Enunciado §2.1 |
| 3 | Arquitectura | Diagrama de capas: Frontend → API → Sesión → SqlEngine → Operadores → Índices/Almacenamiento → PageManager → disco | `informe_parte_01.md` §1 |
| 4 | Dominio de datos | Universidad: students, enrollments, courses; tablas grandes con semilla; tabla de experimentos | §2 |
| 5 | Páginas y archivos | Slotted page de 4096 bytes; Heap con reutilización de espacio; Secuencial con búsqueda binaria, división, eliminación lazy y reorganización al 30 % | §3.1–3.3 |
| 6 | Índices | B+ (divisiones, fusiones, hojas enlazadas; agrupado sobre secuencial, no agrupado sobre Heap); Hash extensible (directorio, profundidad global/local, duplicación) | §3.4–3.5 |
| 7 | Algoritmos externos | ExternalSort (runs + k-way merge), ExternalHashGroup, GraceHashJoin; presupuesto de memoria y temporales | §3.6 |
| 8 | SQL | Parser manual, binder, planner por reglas, plan real con métricas | §3.7 |
| 9 | Transacciones | Locks S/X por tabla, 2PL riguroso, detección de deadlocks, rollback por imágenes; demostración con hilos (1 sin control, 2 con control) | §3.8 |
| 10 | Demo en vivo | Guion de `guion_video.md`, bloques 3, 4 y 6 | — |
| 11 | Experimentos: archivos | Gráficos de inserción y búsqueda por clave; Heap vs Secuencial | `experimentos/01`, `02`, `03`, `04` |
| 12 | Experimentos: índices | Igualdad, rangos 1 % y 10 %, ordenamiento, carga mixta | `experimentos/07`–`11` |
| 13 | Ventajas y desventajas | Tabla de la sección 5 de `EXPERIMENTOS.md` | `EXPERIMENTOS.md` §5 |
| 14 | Cuándo usar cada estructura | Conclusiones de la sección 6 | `EXPERIMENTOS.md` §6 |
| 15 | Ajustes y limitaciones | Los cuatro ajustes de la etapa 10 y por qué no cambian las técnicas; sin WAL, planner sin costos, B+ agrupado | `ajustes_modulos_previos.md`, `informe_parte_01.md` §6 |
| 16 | Cierre | Qué aprendimos; preguntas | — |

**Preguntas probables y dónde está la respuesta:**

- *¿Por qué el secuencial usa búsqueda binaria? ¿No es un índice?* No agrega
  estructura auxiliar; es el acceso natural a un archivo ordenado
  (`ajustes_modulos_previos.md`, cambio 2).
- *¿Por qué el B+ pierde en rangos amplios?* Lee un registro por RID; recorrer
  y filtrar es secuencial (`EXPERIMENTOS.md` §3).
- *¿Por qué el B+ agrupado es tan lento con inserciones?* El archivo
  secuencial mueve registros al dividir páginas y el índice se reconstruye
  (`informe_parte_01.md` §3.4).
- *¿Qué pasa si se cae el servidor?* No hay WAL; la base detecta el estado
  incompleto y se niega a abrir (`informe_parte_01.md` §6).
