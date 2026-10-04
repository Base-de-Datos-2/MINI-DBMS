# Esquema de la presentación final — Parte 1

Para el equipo que presenta. Una diapositiva por fila; unos 12–15 minutos con
la demo en vivo. Las cifras salen de `docs/EXPERIMENTOS.md`.

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
