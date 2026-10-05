# Estado del proyecto al detener esta fase

Fecha: 2026-10-04. Rama: `dev-paolo`. Alcance autorizado: terminar backend y
experimentos de Partes 1 y 2, documentar el estado y detenerse. Todo frontend
queda en pausa hasta que el usuario autorice expresamente iniciarlo.
Las Partes 3, 4 y 5 no se implementan en esta fase. El informe académico se
prepara por separado; aquí se entregan documentación técnica, datos y gráficos.

## Qué está terminado

| Parte | Estado acreditado | Pendiente para la primera entrega |
|---|---|---|
| 1: relacional | Funcionalidad implementada: almacenamiento, Heap/secuencial, B+ agrupado/no agrupado, hash extensible, algoritmos externos, SQL, transacciones, concurrencia, API y cuatro paneles existentes. Backend revalidado; experimentos reales en los tres tamaños. | No hay funcionalidad de backend pendiente. La comprobación de navegador de los paneles es histórica; la validación conjunta final se hará al autorizar frontend. |
| 2: espacial | Backend implementado: R-Tree propio, radio, k-NN y polígonos; Haversine y Euclidiana; persistencia, mantenimiento, rollback, SQL y API con sesiones. Matriz secuencial/R-Tree/GiST completa y gráficos verificados. | Mapa interactivo, controles y resaltado de resultados reales; ejecución de ejemplos SQL desde la interfaz y pruebas finales de navegador. En pausa por instrucción explícita. |
| 3: texto | No iniciada. No se está dejando una Parte 3 a medio implementar. | SPIMI, ranking, SQL/API textual y GIN corresponden a una futura autorización. |
| 4 y 5 | No implementadas; únicamente existe la decisión documental de dominio e-commerce para Parte 5. | Fuera del alcance actual. |

La Parte 2 **no está totalmente terminada** mientras falte su mapa obligatorio.
Las pruebas de backend y los experimentos no sustituyen esa funcionalidad.
La Parte 1 conserva su implementación completa y su UI existente; no se
atribuye a esta fase una nueva verificación visual que no se ejecutó.
No se usa un porcentaje arbitrario para ocultar estos límites.

## Cambios realizados después de la auditoría

- Heap: orden de llegada durante la carga inicial y reutilización de páginas
  con borrados, conservando formato, RIDs y reapertura de archivos antiguos.
- HTTP: cierre limpio por SIGINT y relanzamiento inmediato sin confundir un
  puerto en TIME_WAIT con un servidor activo. El comprobador admite backend-only.
- SQL espacial: parser propio para funciones, POINT y LIMIT; operadores reales,
  parámetros inmutables por consulta, enlace del mapeo, planes seguros de radio
  y k-NN y filtro completo cuando una poda sería incorrecta.
- API espacial: radio/k-NN/polígono con IDs, coordenadas, distancias, registros y
  estadísticas. Comparte sesiones, locks, commit, rollback, cancelación y
  reapertura; previews limitadas sin afirmar que limitan toda la memoria interna.
- Experimentos: mediciones reales GiST, oráculo independiente, código archivado,
  hashes, construcción, disco y memoria. Generación de CSV, PNG y SVG desde
  resultados verificados y protección de sus bytes frente a conversiones de Git.
- Documentación: referencias vigentes, arquitectura real, límites y procedencia
  histórica, elección documental de aplicación y estado de la fase.
- Habilidades solicitadas: `skills/gpt-taste/` y `skills/minimalist-ui/`, con
  instrucciones y salida completa. Se usó Node temporal compatible, sin cambiar
  Node global ni dependencias del frontend.

No se cambiaron archivos del frontend ni la auditoría histórica. Se preservaron
los commits y cambios del usuario. No se hizo push ni se publicaron servicios.

## Verificaciones ejecutadas

| Verificación | Resultado y alcance | Evidencia |
|---|---|---|
| Suite Python completa | 3.027 aprobadas con advertencias como errores; 137,01 s. Pruebas de storage/índices, SQL, espacial, API, propietarios, transacciones, arquitectura y benchmarks. | [cierre_backend.log](evidencias/cierre_backend.log) |
| Aceptación TCP relacional | 24/24: consultas, resultados, planes, errores, sesiones, commit, rollback y persistencia; modo backend-only. | [launcher_http.json](evidencias/launcher_http.json) |
| Aceptación TCP espacial | 18/18: ambas métricas, SQL, parámetros, polígono, error y recuperación, lector esperando lock, commit/rollback, reapertura; dos cierres SIGINT con código cero. | [espacial_servidor.json](evidencias/espacial_servidor.json) |
| Matriz espacial oficial | 5.400 tiempos; 54 configuraciones de 100 centros; resultados completos validados contra oráculo. 1.800 planes GiST ejecutados y conservados. | [verificación](../figuras/spatial/verificacion.json), [datos](../../benchmarks/results/spatial/2026-10-04/) |
| Gráficos espaciales | Cuatro figuras PNG/SVG inspeccionadas, CSV sin redondeo; hashes de fuentes, oráculos y artefactos comprobados. | [datos y reproducción](../EXPERIMENTOS_ESPACIALES.md) |
| Bytes en Git | 49 artefactos experimentales comprobados desde `git archive`; los hashes sobreviven a una clonación. | [artefactos_git.json](evidencias/artefactos_git.json) |
| Repetición relacional | 350 mediciones nuevas: 1.000/10.000, cinco repeticiones por tamaño. Conteos analíticos, contextos, unidades, hashes del código y driver correctos. Fuente de 105 mediciones históricas de 100.000 recuperada desde Git y contrastada con su hash. | [relacional_verificacion.json](evidencias/relacional_verificacion.json) |
| Gráficos relacionales nuevos | 11 PNG inspeccionados y tabla con mediana, mínimo/máximo y n=5; serie actual separada de la histórica. | [gráficos y tabla](../experimentos/actualizados_1k_10k/resultados.md), [protocolo](../experimentos/README.md) |
| Entorno y documentación | Dependencias compatibles, compileall correcto, diff sin errores con Git de Windows y enlaces locales comprobados. | [entorno_final.log](evidencias/entorno_final.log), [enlaces_finales.json](evidencias/enlaces_finales.json) |

El entorno efectivo es Python 3.11.9 en un venv temporal independiente, WSL2,
con dependencias existentes; no se alteró el venv roto del usuario. El verificador
de dependencias usa `uv pip check`: este venv no tiene módulo pip y no se
interpreta su ausencia como fallo de las dependencias. Los scripts reproducibles
están en [evidencias](evidencias/). No se ejecutó build, typecheck ni pruebas de
navegador de frontend en esta fase; las evidencias anteriores siguen fechadas
como históricas en la auditoría y cierres originales.

## Límites que deben conservarse al presentar resultados

- La matriz espacial mide estructuras y consumo completo de resultados,
  excluye SQL/HTTP y renderizado. PostgreSQL es exclusivamente un comparador.
- RSS Python y backend PostgreSQL tienen ámbitos distintos; no equivalen al
  consumo total de sus sistemas. Los gráficos los separan explícitamente.
- Con 100.000 puntos y radio 10 km, R-Tree propio fue más lento que secuencial;
  la exactitud se conserva. Una sola matriz no acredita estabilidad estadística
  entre corridas. Ambos hechos están documentados, sin maquillar las curvas.
- El R-Tree es residente y persistido como snapshot; no se afirma un R-Tree
  paginado ni WAL/recuperación automática. Se preservan los límites previos de
  commit de múltiples archivos, procesos independientes y dominio geométrico local.
- Las mediciones relacionales de 100.000 son históricas y tienen fuente
  recuperable; no se convierten en tiempos de la versión actual por reetiquetarlas.
- La carga mixta agrupada se truncó por presupuesto: 51 operaciones a 1.000
  y 5 a 10.000 en las corridas nuevas; las otras estructuras completaron 200.
  Los 100.000 históricos solo demuestran una inserción agrupada. Ese ensayo
  ampliado no prueba borrados frecuentes; se conserva como limitación, no como
  una obligación nueva ni como una corrida uniforme. La comparación mínima
  del PDF sí tiene ambas mutaciones frecuentes en 1.000.
- El equipo prepara el informe académico. Video/presentación final del proyecto
  no se declaran grabados ni realizados por tener guiones o documentos previos.

## Punto exacto de continuación

Esperar la autorización del usuario para frontend. Al llegar:

1. Leer `skills/gpt-taste/SKILL.md`, `skills/minimalist-ui/SKILL.md`,
   `docs/spatial.md` y el estado actual del repositorio. Conservar los cuatro
   paneles académicos y la integración mediante API propia.
2. Integrar el mapa, centro/radio/k/polígono, ambas métricas y resaltado por
   IDs reales. Exponer claramente previews y resultados truncados; no generar
   puntos o planes ficticios ni sustituir los algoritmos del motor.
3. Ejecutar los dos ejemplos SQL del PDF desde la interfaz, incluidas las
   coordenadas por consulta, y verificar correspondencia de filas/mapa.
4. Pruebas frontend, TypeScript, compilación y servidor/navegador reales para
   Partes 1 y 2; sesiones, errores, commit/rollback y reapertura. Repetir solo los
   checks de backend afectados por cambios reales de integración.
5. Documentar el cierre conjunto. No iniciar Partes 3–5 sin nueva instrucción.

El objetivo más amplio de completar todas las partes no se marca logrado.
La detención de esta fase responde a la instrucción del usuario.

## Registro de cambios de esta fase

Los commits de corrección e integración son b40f6c0 (Heap), f961608 (HTTP),
4097c72 (documentación), 1ca615d (decisión de aplicación), d20add0 y b2e60e8
(SQL/API espacial), 14f94f0 (harness GiST), 83b93a9 (gráficos espaciales) y
5483f0c/e3cc558 (preservación de bytes/hashes). Las habilidades y pausa de
frontend están en e0cc7ef. Los commits posteriores registran los datos
relacionales nuevos y este cierre; los cierres de etapas anteriores y los
checkpoints del usuario se conservan sin reescribirlos. La repetición relacional
y sus figuras quedaron en 7c00da5.
