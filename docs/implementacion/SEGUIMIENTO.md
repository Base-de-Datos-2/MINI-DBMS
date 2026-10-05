# Corrección e implementación del backend

Inicio: 2026-10-04. Base: auditoría independiente en
[AUDITORIA_TECNICA.md](../auditoria/AUDITORIA_TECNICA.md), sus 77 requisitos,
hallazgos H1–H8 y plan de trabajo. La auditoría permanece como fotografía
histórica; este archivo registra los cambios posteriores.

La solicitud del usuario autoriza completar las cinco partes y sus
dependencias de backend, con commits según [commits.md](../commits.md).
Reemplaza el alcance anterior limitado a Partes 1/E1/E2. Todo trabajo de
frontend está postergado: no se implementan mapas, galerías ni interfaces de
aplicación en esta fase. Sus contratos de backend sí corresponden.

## Orden derivado de la auditoría

Cambio de alcance solicitado durante la etapa 6: cerrar y verificar Partes
1 y 2 para la primera entrega, documentar el estado y detenerse. La Parte 3
no se había iniciado; no se implementarán Partes 3, 4 ni 5. El frontend
necesario para cerrar Parte 2 se hará al final de estas dos partes. Una
instrucción posterior lo deja expresamente en pausa hasta nueva autorización;
se terminará el backend y los experimentos, se documentará el estado y se
detendrá el trabajo. No se declarará Parte 2 totalmente cerrada sin su mapa.
La tabla
siguiente conserva el plan previo; sus etapas 7–14 no están autorizadas ahora.

| Etapa | Trabajo | Dependencias auditadas |
|---|---|---|
| 1 | Orden inicial del Heap y reutilización | H1; storage y consumidores de RIDs |
| 2 | Cierre y relanzamiento del servidor HTTP | H2; lifecycle del propietario |
| 3 | Referencias y arquitectura documental vigentes | H5; cambios críticos validados |
| 4 | Selección de una aplicación del Anexo A | 5.1.4; dominio e integración |
| 5 | SQL/API espacial, distancia y LIMIT | H3; núcleo espacial existente |
| 6 | Comparación scan/R-Tree/GiST | H4; datasets/preparador existentes |
| 7 | Persistencia auxiliar de documentos/objetos | H6; owner, identificadores y publicación |
| 8 | SPIMI, TF-IDF/coseno, BM25 y SQL/API textual | Parte 3; persistencia auxiliar |
| 9 | Experimentos textuales y GIN | Parte 3; ranking y relevancia independiente |
| 10 | SIFT/MFCC, vocabulario e histogramas | Parte 4; objetos, parámetros y versiones |
| 11 | Métricas, IVF/HNSW propios y SQL/API multimedia | Parte 4; vectores/identificadores |
| 12 | Experimentos multimedia | Parte 4; referencia exacta y datasets |
| 13 | Backend de aplicación multimodal elegida | Parte 5; modalidades disponibles |
| 14 | Documentación y mecanismos de entrega del backend | Entregables; avances acreditados |

Las mejoras H7/H8 se aplican cuando afectan exactitud o comparabilidad del
trabajo correspondiente. No se añaden requisitos nuevos ni refactors generales.
La interfaz gráfica y la demostración final de todas las funcionalidades
quedan pendientes de la fase de frontend.

## Etapa 1 — Orden inicial del Heap

Estado: COMPLETADA.

- Corrección H1 / requisito 1.1.2: las inserciones iniciales usan la última
  página o añaden una nueva; no vuelven a un sobrante nunca ocupado de una
  página anterior.
- Las páginas con slots borrados siguen siendo reutilizables. Ese estado se
  deriva del formato existente y se reconstruye al abrir; no hay migración
  de formato ni cambio de RIDs vivos.
- La apertura de archivos v1 antiguos conserva sus páginas y orden existente.
- Validación: 1.630 tests de almacenamiento, índices, espacial y transacciones
  aprobados con warnings como errores en una copia aislada; tres regresiones
  nuevas cubren 3200/3200/100, reutilización tras reopen y archivo v1 antiguo.
- Evidencia: [heap.log](evidencias/heap.log); comando en
  [validar_backend.sh](evidencias/validar_backend.sh).
- Unidad de commit: `fix(heap): corregir orden inicial de llegada`.
- Pendientes de esta etapa: ninguno. Las cargas antiguas no se reordenan sin
  una fuente que acredite el orden original.

Commit de etapa 1: b40f6c0.

## Etapa 2 — Cierre y relanzamiento HTTP

Estado: COMPLETADA.

- Corrección H2: la sonda POSIX usa la política de reutilización de Uvicorn
  para TIME_WAIT y continúa rechazando un listener activo. Windows conserva
  su política exclusiva de bind sin introducir SO_REUSEADDR.
- El entrypoint admite KeyboardInterrupt después del cierre de Uvicorn,
  ejecuta siempre service.close y conserva errores reales del cierre.
- El comprobador admite `--backend-only`: omite solo el chequeo de assets
  compilados; no altera su comportamiento completo predeterminado.
- Validación: 96 tests de launcher/transacciones; 24/24 casos HTTP reales de
  backend; dos SIGINT terminan con estado 0, sin traceback y espera de puerto
  de 0 s; commit, rollback e índices sobreviven a reapertura correctamente.
- Regresión completa: 2.973 tests aprobados con warnings como errores,
  134,06 s. El intento anterior tenía 18 fallos de resolución del editable
  histórico en procesos `-I`; se preservó ese diagnóstico y se corrigió el
  entorno con una instalación editable independiente, sin modificar tests
  para esconderlo. No se realizó trabajo de frontend.
- Evidencias: launcher.log, launcher_http.json/log, regresion_critica.log,
  regresion_entorno_previo.log y versiones en entorno_pruebas.txt.
- Unidad de commit: `fix(api): corregir cierre y relanzamiento del servidor`.
- Pendientes de esta etapa: ninguno.

Commit de etapa 2: f961608.

## Etapa 3 — Coherencia documental

Estado: COMPLETADA para la documentación vigente del backend.

- H5/T.1.2: rutas de planes y etapas resuelven bajo PART_01; organización y
  responsabilidades incluyen ambos propietarios de base y el núcleo espacial.
- Se corrigió la frase de Stage 10 pendiente y se distinguieron cierres
  históricos, evaluación independiente y avance actual.
- REQUIREMENTS transcribe las Partes 3–5 y precisa la exposición 15+5 según el
  PDF. AGENTS/PROJECT_CONTEXT reflejan la autorización actual y frontend
  postergado, sin reemplazar algoritmos correctos ni cambiar planes históricos.
- PageManager se describe como propietario de E/S paginada, sin atribuirle
  manifests, undo o snapshots espaciales. Informe/README describen la política
  de Heap corregida.
- H7: el documento experimental precisa la mezcla agrupada 100k (una
  inserción, cero borrados y operación mayor a 60 s), la revisión de presupuesto
  entre operaciones y la procedencia de revisiones/árbol dirty. No altera ni
  inventa resultados históricos.
- Validación: 108 enlaces locales comprobados, todos existentes; git diff
  --check. La regresión del código ya está acreditada en etapa 2; estos cambios
  son documentales y no requieren repetirla.
- Evidencia: documentacion.json.
- Unidad de commit: `docs: corregir referencias y arquitectura vigentes`.
- Pendientes finales: video, presentación y documentación de partes futuras
  permanecen explícitamente pendientes; no se consideran implementados.

Commit de etapa 3: 4097c72.

## Etapa 4 — Aplicación y dominio

Estado: COMPLETADA como decisión de implementación.

- Se eligió Anexo A, opción B, e-commerce híbrido. No se implementarán las
  otras opciones. Reutiliza metadatos y tiendas locales y las modalidades
  textual/visual igualmente exigidas por el proyecto.
- docs/aplicacion.md fija identificadores, asociaciones, consumo exclusivo
  del API propio, fusión explicable, dependencias y aceptación del backend.
- Esta decisión resuelve 5.1.4; no da por existentes una aplicación, sus
  endpoints ni su frontend.
- Validación: contraste de componentes con el PDF, páginas 4–6; coherencia
  con payload de 4079 bytes, dominio espacial y dependencias de la auditoría.
- Unidad de commit: `docs: definir aplicación híbrida de e-commerce`.
- Pendientes de esta etapa: ninguno; implementación corresponde a etapa 13.

Siguiente: etapa 5, SQL y API espacial; mapa postergado.

Commit de etapa 4: 1ca615d.

## Etapa 5 — SQL y API espacial

Estado: COMPLETADA para el backend autorizado.

- LIMIT es un operador real después del pipeline relacional y admite cero;
  el parser propio reconoce funciones espaciales y selecciones mixtas con *.
- Binder y planner resuelven el mapeo registrado, calculan FLOAT ocultos,
  mantienen completos los candidatos bajo filtros/OR/NOT y usan radio/k-NN
  R-Tree cuando es seguro. Ambas métricas producen metros, con empates por id.
- El registro espacial toma prestados objetos del propietario. El rollback
  sustituye sus asociaciones y las consultas preparadas se enlazan de nuevo.
- Los parámetros POINT son copias inmutables por consulta, sin interpolación
  SQL. El API SQL existente recibe parámetros y muestra planes medidos.
- POST /api/spatial/query expone radio, k-NN y polígonos con registros,
  coordenadas, distancias, estadísticas y límites de filas/bytes. Comparte
  sesiones, espera en locks, commit, rollback y cancelación del propietario.
- Validación: 3.009 tests Python con advertencias como errores, 135,63 s;
  18/18 comprobaciones con servidor TCP real, dos cierres con código cero,
  reapertura inmediata y persistencia. Oráculos geométricos independientes,
  parámetros aislados, límites, candidatos residuales y errores controlados.
- Evidencias: regresion_espacial.log, espacial_servidor.json/.log;
  scripts/espacial de validación reproducibles y pruebas del proyecto.
- Commits: d20add0 (base SQL); segunda unidad integra motor/API y documentación.
- Limitaciones declaradas: JOIN/GROUP BY con funciones espaciales no forman
  parte del SQL limitado; radio/polígono materializan los hits en el núcleo
  existente. El límite de respuesta no se presenta como límite de memoria.
- Pendientes de frontend: mapa, controles y visualización de resultados.

Siguiente: etapa 6, matriz experimental scan/R-Tree/GiST.

## Etapa 6 — Experimentos espaciales y gráficos

Estado: COMPLETADA para algoritmos, mediciones y artefactos técnicos.

- Matriz oficial: 1.000/10.000/100.000 puntos; radio 1/5/10 km y k=10/50/100;
  secuencial sobre Heap, R-Tree propio y PostgreSQL GiST; 100 centros idénticos
  por configuración. 54 configuraciones, 5.400 tiempos reales y 5.400
  consultas previas verificadas contra un oráculo exhaustivo independiente.
- 1.800 planes EXPLAIN ANALYZE acreditaron GiST; no se incluyeron en el reloj.
  Se registraron también tiempo interno PostgreSQL, construcción persistente,
  bytes de datos/índice y pico RSS de procesos aislados, con ámbitos explícitos.
- Fuente medida: commit 14f94f0 y archivo source.tar.gz con hashes de todos
  sus archivos. Datos originales en benchmarks/results/spatial/2026-10-04.
- Generador reproducible de gráficos/CSV: rechaza muestras incompletas,
  duplicadas, centros/resultados alterados, tiempos inválidos y planes sin
  GiST. Comprueba la regeneración de CSV, los oráculos y el código archivado.
- Cuatro figuras en PNG/SVG, tablas de consultas/recursos y hashes en
  docs/figuras/spatial. Se inspeccionaron las imágenes: etiquetas legibles,
  unidades explícitas, sin solapamientos; memoria con ámbitos separados.
- Validación final: 3.027 tests Python aprobados con warnings como errores,
  137,01 s; incluye 10 nuevas pruebas contra corrupción de resultados.
  Evidencia: cierre_backend.log, espacial_graficos.log, verificacion.json.
- Documentación: docs/EXPERIMENTOS_ESPACIALES.md, README y docs/spatial.md.
  El informe académico se omite por petición del usuario; lo prepara el equipo.
- Limitación demostrada: radio 10 km a 100.000 puntos tiene media R-Tree
  1252,702 ms frente a 1079,312 ms secuencial. No se oculta ni se describe como
  fallo de exactitud; el coste de resolver muchos RIDs y la poda conservadora
  se mantienen como mejoras de rendimiento, no bloquean resultados correctos.
- PostgreSQL se usó exclusivamente como comparador en un contenedor temporal
  sin puertos/red. Sus schemas propios quedaron eliminados al terminar.
- No se modificó frontend ni se implementaron Partes 3, 4 o 5.

Siguiente autorizado: cerrar la trazabilidad pendiente de las mediciones
relacionales y documentar el punto de parada. Mapa/frontend permanecen en pausa.
