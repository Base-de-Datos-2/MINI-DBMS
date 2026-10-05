import hashlib
import json
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent
AUDIT = EVIDENCE.parent
ROWS = json.loads((EVIDENCE / 'EVALUACION.json').read_text(encoding='utf-8'))
TOTALS = json.loads((EVIDENCE / 'PORCENTAJES.json').read_text(encoding='utf-8'))
STATUS = {
    'COMPLETO': '\u2705 COMPLETO',
    'PARCIAL': '\U0001f7e1 PARCIAL',
    'INCORRECTO': '\u274c INCORRECTO',
    'NO IMPLEMENTADO': '\u2b1c NO IMPLEMENTADO',
    'NO VERIFICADO': '\u26a0\ufe0f NO VERIFICADO',
}
PARTS = {'1': 'Relacional', '2': 'Espacial', '3': 'Texto', '4': 'Multimedia', '5': 'Aplicaci\u00f3n', 'T': 'Entregables transversales'}
STAGES = {
    '1.1': 'Archivos', '1.2': 'Indices y algoritmos externos', '1.3': 'SQL',
    '1.4': 'Transacciones y concurrencia', '1.5': 'Cuatro paneles', '1.6': 'Experimentos',
    '2.1': 'Nucleo espacial', '2.2': 'Mapa', '2.3': 'SQL espacial', '2.4': 'Experimentos espaciales',
    '3.1': 'Indice y ranking', '3.2': 'Experimentos textuales', '3.3': 'SQL textual',
    '4.1': 'Extraccion y representacion', '4.2': 'Indices y metricas', '4.3': 'SQL multimedia', '4.4': 'Experimentos multimedia',
    '5.1': 'Aplicacion del Anexo A', 'T.1': 'Entrega',
}


def table_stats(groups, labels):
    lines = ['| Bloque | Requisitos | Cobertura implementada | Cumplimiento verificado | Pendiente de validaci\u00f3n |',
             '|---|---:|---:|---:|---:|']
    for key, values in groups.items():
        lines.append('| ' + labels[key] + ' | ' + str(values['requisitos']) + ' | ' +
                     ' | '.join(f"{values[name + '_porcentaje']:.2f} %" for name in ['implementado', 'verificado', 'pendiente']) + ' |')
    return '\n'.join(lines)


INTRO = '''# Auditor\u00eda t\u00e9cnica independiente de MINI-DBSM

Fecha: 2026-10-04. Fuente acad\u00e9mica: [Proyecto_Final.pdf](../../Proyecto_Final.pdf), siete p\u00e1ginas. Base inspeccionada: commit 841977a36c4e88e412f263bd1b83347ad0eb7e1b. Alcance: las cinco partes y los entregables, aunque la implementaci\u00f3n activa se concentre en las Partes 1 y 2.

## 1. Dictamen

El proyecto tiene un motor relacional propio, integrado y extensamente probado. No alcanza todav\u00eda la entrega multimodal completa. El cumplimiento verificado es **48,48 % global** y **46,48 % funcional**; la cobertura implementada es 49,35 % y 46,95 %, respectivamente. Estos porcentajes corresponden a requisitos at\u00f3micos de esta auditor\u00eda, no a una calificaci\u00f3n oficial ni a una estimaci\u00f3n de horas restantes.

La Parte 1 alcanza **98,77 %**: 26 requisitos completos y uno incorrecto bajo la lectura literal de orden de llegada del Heap. La reproducci\u00f3n usa tres inserciones sin borrados y obtiene orden f\u00edsico 1,3,2. La suite existente no detecta este caso. No se observ\u00f3 p\u00e9rdida de filas ni incoherencia de \u00edndices en las verificaciones ejecutadas.

La Parte 2 alcanza **42,22 %**. R-Tree, radio, k-NN, pol\u00edgonos y ambas distancias funcionan en el dominio geogr\u00e1fico declarado. Una prueba adicional con 100.000 filas reales aprob\u00f3 38/38 comprobaciones, incluida reapertura. Faltan SQL espacial, mapa y la comparaci\u00f3n experimental completa con GiST. Las Partes 3, 4 y 5 tienen **0 %**: se comprob\u00f3 ausencia de implementaci\u00f3n, no simplemente ausencia de tests.

Se reprodujeron los tres fallos del comprobador HTTP: dos terminaciones con estado -2 tras Ctrl+C y una demora de 62 segundos para que la comprobaci\u00f3n de puerto permita relanzar. Son defectos operativos del lanzador; commit, rollback, bloqueos y reapertura funcional aprobaron. Se propone corregirlos sin modificar el ciclo de transacciones.

La arquitectura permite continuar de forma localizada. No hay motivo acreditado para sustituir el almacenamiento, el B+ o el parser por una biblioteca o DBMS externo. PostgreSQL aparece solamente como comparador exigido para los experimentos futuros.

## 2. Fuente, alcance e interpretaciones

El PDF define todas las obligaciones. REQUIREMENTS.md, AGENTS.md, planes, comentarios, auditor\u00edas de etapas y experimentos anteriores se usaron como referencias contrastables; no incorporan requisitos acad\u00e9micos nuevos. Esta elecci\u00f3n sigue la instrucci\u00f3n expresa del usuario, aunque AGENTS.md coloque REQUIREMENTS.md antes del PDF. No se modific\u00f3 ninguno de esos documentos.

El cat\u00e1logo [REQUISITOS_FIJADOS.json](evidencias/REQUISITOS_FIJADOS.json) contiene **77 requisitos y 220 criterios**. Se fij\u00f3 antes de asignar puntuaciones. Parte \u2192 Etapa \u2192 Paso organiza la auditor\u00eda; las etapas son agrupaciones, no obligaciones adicionales. Los criterios de persistencia, exactitud o integraci\u00f3n son comprobaciones operativas del requisito correspondiente, no funcionalidades extra.

Decisiones de lectura que afectan la evaluaci\u00f3n:

- Heap: el PDF pide almacenar en orden de llegada y reutilizar espacio. Se comprueba llegada en una carga inicial sin borrados, evitando imponer orden a SELECT sin ORDER BY o exigir simult\u00e1neamente orden f\u00edsico cronol\u00f3gico despu\u00e9s de reutilizar huecos. Si el docente aclara que llegada significa exclusivamente ausencia de ordenamiento por clave, cambia un solo criterio: +0,43 puntos globales y +1,23 puntos de Parte 1. Hasta entonces se conserva la lectura literal y la evidencia contraria.
- El 30 % de desperdicio es un ejemplo. No se convierte en umbral obligatorio.
- GROUP BY y JOIN pueden usar hashing externo **o** uso estrat\u00e9gico de \u00edndices. No se exigen ambas alternativas por duplicado.
- El parser puede ser limitado. No se exigen todo SQL, NULL general, UPDATE, MVCC, WAL, recuperaci\u00f3n autom\u00e1tica tras crash ni optimizador por costes. ROLLBACK se verifica como funcionalidad implementada, sin a\u00f1adir un requisito at\u00f3mico extra.
- El PDF prescribe 1.000/10.000/100.000 para archivos de Parte 1. El p\u00e1rrafo de \u00edndices pide comparaci\u00f3n y carga frecuente, pero no repite expresamente esos tama\u00f1os. La carga agrupada incompleta en 100k limita las conclusiones de ese tama\u00f1o; no invalida el requisito m\u00ednimo satisfecho en tama\u00f1os menores.
- Parte 2 exige ambas distancias y consultas geogr\u00e1ficas, pero no cobertura mundial, un R-Tree paginado ni una proyecci\u00f3n geod\u00e9sica concreta. Se explicita el dominio local implementado y sus unidades.
- Parte 4 exige SIFT para im\u00e1genes y MFCC para audio, IVF y HNSW, y las tres m\u00e9tricas. K-Means **o** Tree Quantization es una alternativa. No se exige duplicar las dos cuantizaciones.
- El Anexo A exige escoger **una** aplicaci\u00f3n. No hay elecci\u00f3n acreditada; se eval\u00faan los requisitos comunes y se registra esa decisi\u00f3n pendiente. No se exige implementar las cuatro opciones. Los embeddings opcionales de RAG o los embeddings preentrenados de reconocimiento facial no reemplazan las obligaciones separadas de Parte 4.
- El empleo futuro de bibliotecas para SIFT/MFCC debe respetar la implementaci\u00f3n educativa. El PDF no define expresamente hasta qu\u00e9 nivel se permite delegar esa extracci\u00f3n; dejar constancia de la decisi\u00f3n antes de adoptar una dependencia que sustituya el algoritmo. No afecta ninguna implementaci\u00f3n actual.

El calendario del PDF es una referencia de entregas, no otro denominador de funcionalidades. El informe incremental se eval\u00faa para las partes ya desarrolladas; el video y la exposici\u00f3n final no se dan por realizados a partir de sus guiones.

## 3. Entorno y verificaci\u00f3n ejecutada

El remoto origin es https://github.com/Base-de-Datos-2/MINI-DBMS. La consulta remota de HEAD/main coincidi\u00f3 con el commit local indicado. Al comenzar hab\u00eda un DOCX versionado eliminado y dos archivos no versionados: Proyecto_Final.docx y Proyecto_Final.pdf. Se preservaron. No se alter\u00f3 c\u00f3digo, tests existentes, planes ni documentaci\u00f3n anterior.

La regresi\u00f3n se ejecut\u00f3 sobre una copia de git archive del commit en WSL Ubuntu, en /local-user/.cache/minidbms-audit-20261004/source, con bases separadas para HTTP, navegador y espacial. Los archivos de pytest, compilaci\u00f3n y dependencias quedaron en esa copia y su entorno aislado. La reproducci\u00f3n del Heap tambi\u00e9n se ejecut\u00f3 en Windows con un TemporaryDirectory. No se us\u00f3 la base demo del usuario.

Entorno efectivo: Python 3.11.9; pytest 8.4.2; FastAPI 0.142.2; Starlette 1.7.0; Uvicorn 0.54.0; httpx2 2.13.1; AnyIO 4.14.2; Matplotlib 3.11.2; Playwright 1.63.0; Node 18.20.5; npm 10.8.2. El lock de frontend fija Vite 6.4.3 y Vitest 3.2.7. La instalaci\u00f3n sigui\u00f3 pyproject.toml y package-lock.json. Las dependencias del navegador ausentes se extrajeron en un directorio privado; no se instal\u00f3 software global.

| Verificaci\u00f3n actual | Resultado | Evidencia |
|---|---|---|
| Python, suite completa, warnings como errores | 2.968 aprobadas; 0 fallos, 0 omitidas; 136,49 s | pytest.log y pytest.xml |
| Comprobaci\u00f3n de tipos de frontend | Aprobada | frontend_typecheck.log |
| Tests de frontend | 32/32 | frontend_tests.log |
| Compilaci\u00f3n de frontend | Aprobada | frontend_build.log |
| Demo real de hilos | Sin protecci\u00f3n: 1; protegido: 2; serial: 2 | demo_threads.json |
| Servidor HTTP, sesiones y reinicio | 22/25; los tres fallos son operativos y se detallan abajo | integracion_http.json y .log |
| Chromium real, dos p\u00e1ginas/sesiones | 11/11; sin errores JS | navegador.json, navegador.png y navegador_dom.html |
| Espacial con Heap real de 100.000 filas | 38/38, incluida reapertura | espacial_100k_real.json y .log |
| Heap con filas de tama\u00f1o variable | Defecto reproducido antes/despu\u00e9s de abrir | heap_orden_llegada.json |
| Reconstrucci\u00f3n de tablas y gr\u00e1ficos de experimentos | Tablas id\u00e9nticas, 111 l\u00edneas; 11 PNG generados | reporte_contrastado.json y reporte_regenerado/ |
| Repetici\u00f3n diagn\u00f3stica del benchmark actual, 1k | 35 mediciones; no reemplaza los ensayos oficiales | repeticion_1k.jsonl |
| Imports expl\u00edcitos de engine, AST | 102 m\u00f3dulos, grafo ac\u00edclico; sin biblioteca sustitutiva | arquitectura.json e inventario_codigo.json |

Las pruebas HTTP comprobaron consultas indexadas y scan con iguales resultados y planes diferentes; ORDER/GROUP/JOIN reales; errores sint\u00e1cticos y sem\u00e1nticos con recuperaci\u00f3n; importaci\u00f3n de 500 filas a Heap y secuencial; \u00edndices B+/hash; dos sesiones con espera de 1,5 s; commit, rollback y reapertura con solo cambios confirmados. Chromium comprob\u00f3 esos flujos visibles, el estado de bloqueo y los cuatro paneles. La captura se inspeccion\u00f3 visualmente: resultados, esquema y plan legibles sin superposiciones.

Las 38 comprobaciones espaciales incluyen 36 combinaciones de tres centros, dos m\u00e9tricas, radios 1/5/10 km y k 10/50/100, m\u00e1s pol\u00edgono y reapertura. La referencia exhaustiva usa matem\u00e1tica independiente: Haversine mediante \u00e1ngulo de vectores unitarios (atan2 de producto cruzado/producto punto), proyecci\u00f3n euclidiana reimplementada y un pol\u00edgono c\u00f3ncavo con prueba propia de pertenencia. El R-Tree qued\u00f3 con altura 5, 9.738 nodos y 8.874 hojas. Este ensayo funcional **no es** la comparaci\u00f3n de 100 consultas promedio contra GiST exigida por el PDF.

Los ejemplos espaciales, textuales y multimedia del PDF se probaron por el parser p\u00fablico. Seis consultas fueron rechazadas: no existen sus funciones/operadores; LIMIT est\u00e1 reconocido como no soportado. La variante SELECT *, SCORE tambi\u00e9n necesita ampliar la lista de proyecci\u00f3n. No se otorg\u00f3 cr\u00e9dito por palabras presentes solamente en planes.

### 3.1 Qu\u00e9 prueban los tests y qu\u00e9 omiten

La suite tiene or\u00e1culos independientes para sorting (sorted), agrupaci\u00f3n (diccionario), joins (bucles/multiconjuntos, preservando duplicados), B+/hash (mapas y comparaci\u00f3n tras reapertura) y almacenamiento (filas/RIDs/conteos/archivos). Las pruebas de operadores y SQL fuerzan presupuestos peque\u00f1os, runs, particiones y fallos con limpieza. Las pruebas de transacciones usan schedules controlados, eventos y conflictos reales; una demo observacional por s\u00ed sola no reemplaza esos tests.

Se revisaron divisiones internas/de hoja/ra\u00edz, reutilizaci\u00f3n, borrado, reorganizaci\u00f3n, cambios de RID, duplicados, colisiones, procesamiento externo, fallos inyectados y reapertura. Los detalles y archivos de cobertura por requisito est\u00e1n en la secci\u00f3n 8. Los tests no solo importan clases: comparan resultados, asociaciones y estados persistentes.

Persisten l\u00edmites del alcance de los or\u00e1culos:

- HeapFreeSpaceTracker tiene un test que exige elegir la p\u00e1gina apta de menor identificador. Confirma la implementaci\u00f3n, pero no la contrasta con llegada de filas de tama\u00f1os diferentes. El nuevo caso demuestra esa omisi\u00f3n.
- Algunas referencias espaciales de la suite comparten distance/geometry con el \u00edndice: pueden coincidir ante un mismo error matem\u00e1tico. La referencia independiente adicional reduce ese riesgo; no prueba geometr\u00eda mundial fuera del dominio admitido.
- Vitest valida principalmente helpers/contratos. No acredita por s\u00ed solo el render completo, foco, bloqueo entre pesta\u00f1as o comunicaci\u00f3n HTTP. La prueba actual de navegador complementa ese hueco.
- Las pruebas del lanzador no cubren de extremo a extremo SIGINT y puerto en TIME_WAIT. Su aprobaci\u00f3n no invalida los tres fallos reales observados.
- Los tests de benchmarks son peque\u00f1os y comprueban formatos/rutas. No acreditan que una carga de 100k contenga borrados ni que varias estructuras reciban el mismo n\u00famero de mutaciones.
- La inspecci\u00f3n AST detecta ciclos de imports expl\u00edcitos, no todos los ciclos posibles de objetos en ejecuci\u00f3n. Las pruebas de integraci\u00f3n comprueban el ensamblaje actual.

### 3.2 Evidencia hist\u00f3rica, repetici\u00f3n y ausencia de comprobaci\u00f3n

Los conteos y tiempos publicados de auditor\u00edas anteriores son hist\u00f3ricos. No sustituyen los resultados actuales de esta auditor\u00eda. Los 455 registros JSONL oficiales de Parte 1 s\u00ed se inspeccionaron: 143 de archivos y 312 de \u00edndices. Hay 175 registros de 1k, 175 de 10k y 105 de 100k, con cinco repeticiones en los dos primeros tama\u00f1os y tres en el mayor. Se revisaron unidades en segundos/bytes, semillas, consultas/selectividades, configuraci\u00f3n, tiempos finitos, n\u00fameros de operaciones y correspondencia con tablas/gr\u00e1ficos.

La huella de c\u00f3digo registrada para 100k, 1697f753539b46be8e89bdf73f3b82ad4a209d84d13973d9c0f7ee5c52c28dab, coincide con los blobs engine/benchmarks del commit 075eae correspondiente, usando el mismo orden de hashing del harness. La huella del HEAD actual es d74b979ff2bc31415202f5246dfc34a878118bf5fa95cd0ae2cadcd819376378. Esto permite distinguir revisiones diferentes en vez de atribuir todos los ensayos al HEAD actual.

Los ensayos 1k/10k registran commit d191e7c y \u00e1rbol dirty, con una huella propia. El commit solo no permite reconstruir ese \u00e1rbol no versionado; falta su snapshot exacto. Es una limitaci\u00f3n de procedencia/reproducibilidad, **no prueba de fabricaci\u00f3n**. Las medidas siguen siendo evidencia hist\u00f3rica registrada, con esa salvedad. Las afirmaciones causales sobre diferencias entre tama\u00f1os deben reconocer cambios de versi\u00f3n y de configuraci\u00f3n.

En carga mixta, B+ agrupado hizo 35\u201337 operaciones por repetici\u00f3n a 1k y tres a 10k (dos inserciones/una eliminaci\u00f3n). A 100k realiz\u00f3 **una inserci\u00f3n y cero eliminaciones** por repetici\u00f3n, en 373\u2013432 s. Hash/no agrupado hicieron 200 operaciones (100/100). El presupuesto de 60 s se comprueba entre operaciones y no puede interrumpir una inserci\u00f3n larga. Por tanto, ops/s describe trabajo y mezcla diferentes: a 100k no es evidencia de eliminaci\u00f3n frecuente del agrupado. El m\u00ednimo de comparaci\u00f3n de \u00edndices existe en los tama\u00f1os menores; se clasifica la ampliaci\u00f3n como mejora experimental, sin inventar un requisito para los tres tama\u00f1os.

Se regeneraron las tablas desde los JSONL oficiales y se verific\u00f3 igualdad exacta. Se inspeccion\u00f3 el gr\u00e1fico de carga mixta; necesita una nota expl\u00edcita de mezcla/n\u00famero de operaciones en 100k. La repetici\u00f3n nueva 1k usa el c\u00f3digo actual, una repetici\u00f3n y presupuesto corto. Coincidi\u00f3 temporalmente con el ensayo espacial, por lo que se utiliza solo como prueba diagn\u00f3stica de rutas y formatos; no se compara su latencia con resultados oficiales ni se calculan intervalos de confianza.

No se ejecutaron comparaciones PostgreSQL/GiST/GIN ni benchmarks completos de Partes 2\u20134. S\u00ed existe preparaci\u00f3n espacial: benchmarks/spatial/postgres.py genera/importa datos, crea GiST y registra EXPLAIN; spatial_e1_setup.json y sus logs son hist\u00f3ricos. No hay un harness de comparaci\u00f3n completa con 100 consultas por caso, ni comparadores textuales/multimedia. La consulta actual docker ps fall\u00f3 por daemon no disponible; no se pudo contrastar el contenedor hist\u00f3rico ni acreditar PostGIS actual. Falta esa evidencia; no se sustituy\u00f3 por resultados de otra base. Tampoco se acreditaron un video existente fuera del repositorio, la selecci\u00f3n de Anexo A o la exposici\u00f3n final. Los intentos de Chromium fallidos por bibliotecas del entorno quedaron registrados antes de resolverlos; no se consideran defectos del producto.

## 4. Porcentajes reproducibles

Cada requisito tiene peso 1. Sus n criterios reciben peso 1/n. Para un bloque con R requisitos:

~~~text
Cobertura implementada = 100/R * sum_i(sum_j I_ij / n_i)
Cumplimiento verificado = 100/R * sum_i(sum_j V_ij / n_i)
Pendiente de validacion = 100/R * sum_i(sum_j P_ij / n_i)
~~~

I vale 1 cuando existe implementaci\u00f3n real, aunque sea defectuosa; V vale 1 cuando se acredita conformidad; P vale 1 cuando existe implementaci\u00f3n pero no est\u00e1 acreditada su conformidad. Se cumple V+P <= I. Un criterio defectuoso tiene I=1,V=0,P=0. Un artefacto externo de existencia desconocida tiene I=V=P=0 y estado NO VERIFICADO: P no mide toda incertidumbre posible, solo implementaci\u00f3n existente pendiente de validaci\u00f3n.

No se asigna 50 % autom\u00e1tico a PARCIAL. El CSV guarda los criterios, sus tres listas de 0/1 y los nueve campos de cada paso. evaluar.py usa Fraction; PORCENTAJES.json conserva numeradores equivalentes exactos. El proyecto pesa 77 requisitos y el subtotal funcional 71. Los tests adicionales no ampl\u00edan denominadores.

Estados: COMPLETO requiere todos los criterios satisfechos; PARCIAL conserva una parte acreditada; INCORRECTO tiene una implementaci\u00f3n con incumplimiento demostrado; NO IMPLEMENTADO requiere ausencia comprobada; NO VERIFICADO conserva incertidumbre. Los estados son una s\u00edntesis; el c\u00e1lculo siempre usa criterios.
'''


def write_report():
    sections = [INTRO, table_stats(TOTALS['partes'], {k: ('Parte ' + k + ': ' + v) if k != 'T' else v for k, v in PARTS.items()}),
                '\n### 4.1 Subtotal y global\n',
                table_stats({'funcional': TOTALS['funcional'], 'global': TOTALS['global_']},
                            {'funcional': 'Subtotal funcional (Partes 1\u20135)', 'global': 'Proyecto con entregables'}),
                '\n### 4.2 Por etapa de auditor\u00eda\n', table_stats(TOTALS['etapas'], {key: key + ': ' + value for key, value in STAGES.items()})]
    sections.append('''

El global verificado es (112/3)/77 = 48,484848... %. Son 35 pasos completos, tres parciales, uno incorrecto, 37 no implementados y uno no verificado. La cobertura es 38/77. El pendiente implementado sin validar es 0 % en esta fotograf\u00eda: los criterios existentes pudieron comprobarse o demostrar su defecto. Eso no afirma certeza sobre entregables externos. Un video conforme y la acreditaci\u00f3n final de la exposici\u00f3n sumar\u00edan como m\u00e1ximo 1,73 puntos globales; actualmente no se contabilizan. Los porcentajes deben recalcularse si aparece nueva evidencia o una aclaraci\u00f3n docente.

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

La flecha program\u00e1tica espacial no representa una ruta SQL ni un endpoint de consultas espaciales existente. Ese ensamblaje todav\u00eda falta.

| Responsabilidad | Implementaci\u00f3n y resultado | Implicaci\u00f3n |
|---|---|---|
| Frontend/API | React consume contratos; FastAPI delega al motor. El navegador comprob\u00f3 planes reales. | Reutilizar API y componentes para las extensiones. |
| SQL | Lexer/parser escritos a mano; AST y binding separados; planner selecciona scan, B+/hash y operadores externos. | Agregar funciones tipadas y acceso multimodal en estas capas, sin ejecutar consultas en el parser. |
| Operadores | ExternalSort, ExternalHashGroup, GraceHashJoin y rutas indexadas propios; presupuestos, temporales y cierre. | Reutilizar ExecutionContext, layouts y lifecycle. Los presupuestos no son RSS medido. |
| Almacenamiento/\u00edndices | Slotted pages de 4096 bytes, secuencial, B+ compartido, hash persistente. Mutaciones coordinan cambios de RID/rebuild. | Evitar reorganizaci\u00f3n cruda con \u00edndices activos. Mantener sus adaptadores. |
| Transacciones | S/X locks, latches, sesiones, undo f\u00edsico acotado, publicaci\u00f3n y cancelaci\u00f3n. | Funciona entre sesiones del mismo propietario/proceso. Una instancia/worker por base. |
| Espacial | RTree propio con split cuadr\u00e1tico, MBR, radio, best-first k-NN y pol\u00edgono exacto; snapshot checksum/fsync/replace. | El \u00e1rbol reside en RAM; guardar todo tras mutaci\u00f3n y reconstruir tras borrado tiene coste. No se exige paginaci\u00f3n espacial por el PDF. |
| Composici\u00f3n | engine.database.Database y api.database.Database comparten piezas, pero ensamblan manifest/CREATE y definiciones demo/importaci\u00f3n/espacial de formas diferentes. | Duplicaci\u00f3n parcial del ownership. Antes de ampliar, reutilizar/extraer servicios concretos; no sustituir una clase sin revisar consumidores. |

Referencias principales: engine/transactions/session.py:280 y :851 (SqlSession y run_programmatic_read); engine/database/owner.py:51; api/database.py:185; engine/query/environment.py:44; engine/spatial/rtree.py:80, :212 y :282; engine/spatial/index.py:78. La matriz aporta s\u00edmbolos y l\u00edneas espec\u00edficas de cada operaci\u00f3n. inventario_codigo.json conserva todos los s\u00edmbolos, imports y huellas inspeccionados.

El n\u00facleo no importa un DBMS/ORM ni bibliotecas sustitutivas de B+, hash, joins o sorting. El grafo de imports expl\u00edcitos es ac\u00edclico. No se encontr\u00f3 dependencia de storage hacia frontend. PageManager no representa toda la E/S del proceso: manifests, snapshots espaciales y temporales tambi\u00e9n usan archivos. No presentar sus contadores como disco total.

Hay funciones largas (SqlSession.execute, 272 l\u00edneas; lexer, 182; una ruta de executor, 161). Su tama\u00f1o es una observaci\u00f3n de mantenibilidad, no un defecto demostrado. La extracci\u00f3n futura debe seguir cambios concretos y tests de comportamiento; una reescritura general no est\u00e1 justificada.

El codec relacional admite INTEGER, FLOAT, BOOLEAN y VARCHAR. El payload m\u00e1ximo de una fila es **4079 bytes** (engine/storage/binary.py:41), incluidos los campos codificados. No insertar PDFs, descriptores ni vectores grandes como cadenas improvisadas. La extensi\u00f3n recomendada es identificar documentos/objetos en tablas y almacenar contenido/vectores en archivos auxiliares propios con formato, checksum y referencia estables. Integrar alta/baja/publicaci\u00f3n con el mismo propietario y mantenimiento; prever undo o una pol\u00edtica expl\u00edcita de objetos inmutables. No crear motores paralelos ni cambiar el codec existente sin necesidad.

El dominio espacial publicado es Lima: latitud [-12.30,-11.80], longitud [-77.25,-76.75], origen (-12.0464,-77.0428). Euclidiana usa una proyecci\u00f3n plana fija en metros y Haversine radio 6371008,771415059 m. El l\u00edmite inferior de MBR Haversine utiliza solo latitud: es seguro, pero puede descartar pocos candidatos. En las consultas de la prueba se examinaron 3.287\u201339.134 candidatos Haversine y 70\u201313.119 euclidianos. Son conteos descriptivos, no una comparaci\u00f3n de latencia ni prueba de optimalidad.

Undo tiene l\u00edmites de 1 GiB por transacci\u00f3n y 2 GiB total; bloques de 1 MiB. No hay WAL, recuperaci\u00f3n autom\u00e1tica, locks entre procesos ni commit crash-at\u00f3mico de varios archivos. Son l\u00edmites declarados fuera del PDF actual. Reapertura limpia aprobada no equivale a resistencia a cortes de energ\u00eda. El frontend/API validado se ejecuta desde la ra\u00edz del repositorio, como prescribe el manual; no se acredita un paquete redistribuible autosuficiente del API.

## 6. Hallazgos y acciones de aceptaci\u00f3n

Se distinguen **defectos demostrados**, **brechas obligatorias**, **limitaciones** y **riesgos futuros**. Los dos primeros bloques fijan el trabajo necesario. Las mejoras no se convierten en obligaciones acad\u00e9micas.

### H1. CR\u00cdTICA: llegada inicial del Heap

Tipo: defecto demostrado bajo lectura literal del PDF, p. 1 \u00a72.1.1. Impacto: el almacenamiento inicial no cumple la pol\u00edtica de llegada; no cambia la validez de SELECT sin ORDER BY y no se observ\u00f3 p\u00e9rdida de datos.

Reproducci\u00f3n: esquema id INTEGER/value VARCHAR; insertar id 1 y 2 con textos de 3200 caracteres, luego id 3 con 100. RIDs: (1,0),(2,0),(1,1). Scan: [1,3,2] antes y despu\u00e9s de abrir, sin borrados. Evidencia: heap_orden_llegada.json y probar_heap_llegada.py. Componentes: HeapFile.insert/scan y HeapFreeSpaceTracker; tests/storage/test_heap_free_space.py exige first-fit de menor p\u00e1gina.

Correcci\u00f3n localizada: priorizar la p\u00e1gina final para filas nuevas; distinguir huecos liberados por borrado de sobrantes nunca ocupados en p\u00e1ginas antiguas. Conservar codecs y RIDs. Revisar consumidores del tracker y mantenimiento de \u00edndices. No reordenar archivos existentes ni inferir cronolog\u00eda a partir de una clave cualquiera. Si se migra una carga antigua, recargar desde su fuente con orden original y reconstruir todos los \u00edndices.

Aceptaci\u00f3n: regresi\u00f3n variable 3200/3200/100 produce colocaci\u00f3n y scan 1,2,3 tras reapertura; los casos de borrado/reutilizaci\u00f3n siguen aprobando; B+/hash siguen coherentes. Si existe aclaraci\u00f3n docente compatible con first-fit, registrarla y reevaluar el criterio en vez de introducir un cambio innecesario.

### H2. CR\u00cdTICA operativa: salida y relanzamiento HTTP

Tipo: tres fallos reales del comprobador; no una inferencia del n\u00famero de tests. Evidencia: integracion_http.json, dos salidas -2 y puerto no disponible para la sonda durante 62 s. navegador.json confirma salida -2 con todos los flujos de UI aprobados. Componentes: api/__main__.py:56 (sonda bind de puerto), main:64 y lifecycle de Uvicorn; scripts/integration_check.py:305. La limpieza de servidor/base lleg\u00f3 a finalizar; fall\u00f3 el estado de salida esperado.

Correcci\u00f3n localizada: manejar KeyboardInterrupt en el punto de entrada despu\u00e9s de finalizar correctamente el cierre, conservando excepciones reales de cleanup. Ajustar la sonda al comportamiento del servidor en POSIX, usando reutilizaci\u00f3n de direcci\u00f3n para TIME_WAIT cuando corresponda y verificando un listener activo. No trasladar sin evaluaci\u00f3n esa opci\u00f3n a Windows, donde pueden cambiar las condiciones de ocupaci\u00f3n/compartici\u00f3n del puerto. No desactivar la protecci\u00f3n contra otro servidor real.

Dependencias: ciclo de cierre/lease de base, plataforma del socket y CLI. Aceptaci\u00f3n: dos ciclos reales arrancar\u2013consultar\u2013SIGINT\u2013relanzar inmediatamente terminan con estado 0 sin traceback; un puerto con listener activo sigue rechazado; 25/25 del comprobador y navegador pasan; datos confirmados conservados, provisionales ausentes. No ampliar el admission guard de sesiones: los locks actuales ya coordinan sus conflictos.

### H3. IMPORTANTE: interfaz p\u00fablica espacial pendiente

Tipo: brecha obligatoria, no defecto del R-Tree. El n\u00facleo existe pero no tiene SQL espacial ni mapa. Componentes: lexer/parser/AST/binder/planner, QueryEnvironment, propietario API, contratos y frontend. Evidencia: filas 2.2 y 2.3 de la matriz, rechazo de ejemplos en espacial_100k_real.json e inventario de funciones.

Correcci\u00f3n: agregar POINT/distancia tipadas, acceso espacial con filtro geom\u00e9trico residual exacto, orden por distancia y LIMIT real; reutilizar SpatialIndex y run_programmatic_read con locks/owner adecuados. Mostrar en el plan la ruta efectivamente usada. Agregar mapa de puntos y resultados resaltados con contratos del API. No ejecutar el R-Tree directamente desde React.

Dependencias: n\u00facleo existente, binding de ubicaci\u00f3n/columnas y contrato de resultado. Aceptaci\u00f3n: ejemplos del PDF por API/UI, igualdad contra scan, ambas m\u00e9tricas, radio exacto y orden/k correctos con empates; errores recuperables; sesiones aisladas; reapertura; selecci\u00f3n espacial visible en mapa y plan.

### H4. IMPORTANTE: comparaci\u00f3n espacial ausente

Tipo: brecha obligatoria. Tener 100k puntos y diferencial correcto no satisface tiempos promedio de 100 consultas, GiST, memoria/disco y presentaci\u00f3n. Componentes: benchmarks nuevos separados del motor y docs experimentales. Dependencias: n\u00facleo; no requiere terminar el mapa para empezar a medir.

Correcci\u00f3n: scan/R-Tree/GiST con datos id\u00e9nticos, 1k/10k/100k, radios 1/5/10 km, k 10/50/100 y 100 consultas equivalentes. Definir unidades, proyecci\u00f3n, tratamiento de bordes/empates y sem\u00e1ntica geod\u00e9sica equivalente en PostgreSQL. Si una funci\u00f3n de PostGIS usa elipsoide, no compararla como si fuera la esfera implementada sin ajustar o explicar diferencias. Acreditar el uso real de GiST con EXPLAIN, no solo CREATE INDEX.

Aceptaci\u00f3n: resultados diferenciales id\u00e9nticos dentro de tolerancia definida; configuraci\u00f3n/versi\u00f3n/semillas/consultas archivadas; construcci\u00f3n, tiempos, memoria y bytes medidos; gr\u00e1ficas y tabla trazables a datos crudos. PostgreSQL permanece exclusivamente como comparador.

### H5. IMPORTANTE: documentaci\u00f3n y entregables desalineados

Tipo: obligaci\u00f3n parcialmente satisfecha y evidencia externa faltante. README contiene arquitectura/organizaci\u00f3n, pero enlaces antiguos a planes/etapas en ra\u00edz y omisiones de engine/database/espacial. PROJECT_CONTEXT.md conserva una frase de Stage 10 pendiente (l\u00ednea 2616) junto a cierre reciente. No se encontr\u00f3 video ni enlace a un video; guion no acredita duraci\u00f3n/funcionalidades. Hay material de exposici\u00f3n, no prueba de exposici\u00f3n final 15+5.

Correcci\u00f3n futura: actualizar solo referencias/estado que se contradicen, diagrama de propietarios y l\u00edmites de persistencia; conectar README con rutas reales de PART_01 y PART_02. Conservar historial de cierres, explicitando qu\u00e9 fue revalidado. Producir o localizar video 5\u201310 min cuando est\u00e9 el alcance final, y preparar/verificar exposici\u00f3n 15+5. No modificar esos archivos durante esta auditor\u00eda.

Aceptaci\u00f3n: enlaces locales resuelven, instrucciones funcionan en entorno limpio, esquema representa componentes reales; video accesible y duraci\u00f3n comprobada con demostraciones de todas las partes; presentaci\u00f3n cubre el proyecto y reserva preguntas. Dependencias: cierre funcional de las partes para la entrega final.

### H6. IMPORTANTE: texto, multimedia y aplicaci\u00f3n a\u00fan no implementados

Tipo: ausencias comprobadas, detalladas en los 29 pasos de Partes 3\u20135. No se atribuye al motor relacional una obligaci\u00f3n de contener texto/multimedia antes de la solicitud de implementaci\u00f3n; esta auditor\u00eda eval\u00faa la entrega completa autorizada.

Correcci\u00f3n: construir persistencia auxiliar de documentos/objetos e identificadores; SPIMI con spill/merge propio, TF-IDF/coseno y BM25; SQL textual y GIN experimental; SIFT/MFCC, cuantizaci\u00f3n permitida, histogramas TF-IDF, IVF/HNSW propios y m\u00e9tricas; SQL multimedia y experimentos/galer\u00eda. Elegir una opci\u00f3n del anexo e integrar dos tipos de datos mediante el API. No implementar cuatro aplicaciones ni sustituir los \u00edndices por PostgreSQL.

Dependencias y pruebas de aceptaci\u00f3n individuales: secci\u00f3n 8. Las interfaces de identificadores/publicaci\u00f3n deben resolverse antes de duplicar almacenamiento. La aplicaci\u00f3n puede desarrollarse incrementalmente al disponer de sus modalidades.

### H7. MEJORA: fuerza de las conclusiones experimentales de Parte 1

Tipo: limitaci\u00f3n, no nueva obligaci\u00f3n. Evidencia: 455 medidas, snapshots de c\u00f3digo distintos y carga mixta desigual. Corregir la interpretaci\u00f3n de gr\u00e1ficas; el grouped 100k no demuestra borrados frecuentes. El presupuesto entre operaciones no es timeout estricto.

Mejora localizada: registrar snapshot exacto del \u00e1rbol medido, incluida suciedad; separar costes de inserci\u00f3n y borrado; ejecutar un prefijo fijo compartido de mutaciones o presentar expl\u00edcitamente mezclas y cantidades diferentes; registrar cumplimiento/rebase del presupuesto. Si se repite 100k, obtener al menos un borrado real del agrupado sin usarlo para fingir una mezcla extensa. No prometer una duraci\u00f3n m\u00e1xima que una operaci\u00f3n indivisible puede exceder.

Aceptaci\u00f3n: reconstrucci\u00f3n exacta de c\u00f3digo/consulta/configuraci\u00f3n; conteos por tipo de mutaci\u00f3n visibles junto a ops/s; notas causales de cambio de versi\u00f3n; tablas/gr\u00e1ficas regenerables. Componentes: harness/reporte y documentaci\u00f3n, sin sustituci\u00f3n de estructuras. Optimizaci\u00f3n del agrupado solo despu\u00e9s de medir y revisar todos los consumidores de RID.

### H8. MEJORAS de mantenibilidad y rendimiento, con alcance limitado

Riesgos futuros: duplicaci\u00f3n de propietarios al integrar nuevas modalidades; funciones largas; archivos auxiliares fuera del contador de PageManager; snapshots espaciales completos y rebuild en borrados; l\u00edmite Haversine poco selectivo; lecturas individuales por RID en B+; panel de archivos que puede quedar desactualizado tras cambios de otra pesta\u00f1a hasta recargar.

No se demostr\u00f3 incorrecci\u00f3n por estas observaciones. Mantenerlas como mejoras. Extraer servicios compartidos concretos, reforzar m\u00e9tricas de E/S/RSS y refresh de UI cuando sus consumidores lo requieran. Aceptaci\u00f3n: mismo contrato p\u00fablico/resultados y regresi\u00f3n relevante aprobada; mejora medida con workload equivalente. No emprender migraci\u00f3n del motor completo sin un problema y un plan de compatibilidad acreditados.

## 7. Siguiente plan de trabajo

Este plan define correcciones recomendadas; no las implementa ni altera los planes anteriores. Cada paso remite a aceptaci\u00f3n concreta de la secci\u00f3n 6 o de la matriz.

| Orden | Prioridad | Acci\u00f3n localizada | Dependencias | Cierre comprobable |
|---:|---|---|---|---|
| 1 | CR\u00cdTICA | Resolver llegada inicial del Heap o acreditar aclaraci\u00f3n docente | H1; tracker/RIDs | Criterio 1.1.2 y reutilizaci\u00f3n/reapertura |
| 2 | CR\u00cdTICA operativa | SIGINT y relanzamiento de puerto | H2; lifecycle CLI | 25/25 HTTP, salida 0, relanzamiento y listener protegido |
| 3 | IMPORTANTE | Corregir referencias/estados documentales actuales | H5; arquitectura inspeccionada | README enlaza rutas reales y no afirma funciones ausentes |
| 4 | IMPORTANTE | Elegir una opci\u00f3n de Anexo A y fijar dominio | Paso 5.1.4 | Decisi\u00f3n acreditada, requisitos condicionales de una sola opci\u00f3n |
| 5 | IMPORTANTE | Spatial SQL, POINT/distancia, orden y LIMIT | H3; n\u00facleo espacial, binder/planner/owner | Pasos 2.3.1\u20132 y diferencial por API |
| 6 | IMPORTANTE | Mapa interactivo y resultados resaltados | Contrato espacial/API | Pasos 2.2.1\u20132 en navegador real |
| 7 | IMPORTANTE | Harness scan/R-Tree/GiST y resultados completos | H4; puede avanzar antes del mapa | Pasos 2.4.1\u20135; 100 consultas y matriz prescrita |
| 8 | IMPORTANTE | Identificadores/documentos/objetos auxiliares propios | Owner/undo/manifest; dominio elegido | Alta/baja/reapertura/fallo sin objetos o referencias hu\u00e9rfanos |
| 9 | IMPORTANTE | SPIMI, TF-IDF/coseno, BM25 y SQL textual | Persistencia de documentos; parser/LIMIT | Pasos 3.1 y 3.3 con referencia independiente |
| 10 | IMPORTANTE | GIN, relevancia etiquetada y experimentos textuales | Ranking propio/dataset/qrels | Pasos 3.2; Precision@10/Recall@10 reproducibles |
| 11 | IMPORTANTE | SIFT/MFCC, vocabulario e histogramas TF-IDF | Objetos/dominio/decisi\u00f3n de dependencias | Pasos 4.1 con artefactos y semillas verificables |
| 12 | IMPORTANTE | M\u00e9tricas, IVF/HNSW propios y SQL multimedia | Vectores/IDs/LIMIT/planner | Pasos 4.2\u20134.3, diferencial exacto y Recall@10 |
| 13 | IMPORTANTE | Experimentos multimedia y galeria | Datos/\u00edndices; consulta exacta | Pasos 4.4, casos reales de \u00e9xito/error |
| 14 | IMPORTANTE | Aplicaci\u00f3n real con API y dos modalidades | Opci\u00f3n elegida/modalidades disponibles | Pasos 5.1; flujo completo de esa opci\u00f3n |
| 15 | IMPORTANTE | Consolidar informe, video y presentaci\u00f3n | Alcance funcional final | T.1, video 5\u201310 y exposici\u00f3n 15+5 |
| 16 | MEJORA | Mejorar comparabilidad/snapshot de Parte 1 | H7 | Mezcla visible y datos crudos regenerables |
| 17 | MEJORA | Optimizar costes y extraer duplicaci\u00f3n concreta | H8; mediciones/consumidores | Contratos conservados y beneficio medido |

No todas las filas son estrictamente secuenciales: los experimentos espaciales pueden avanzar con el acceso program\u00e1tico; la app puede consumir modalidades ya terminadas. Las dependencias protegen integraci\u00f3n y persistencia, sin imponer una reescritura preventiva.

## 8. Evaluaci\u00f3n completa: Parte \u2192 Etapa \u2192 Paso

Todos los pasos contienen los nueve campos solicitados. Las tablas de criterios exponen el c\u00e1lculo: I = implementado, V = conforme verificado, P = implementado pendiente de validar. Un 0 en V no significa por s\u00ed solo ausencia: consultar el estado y los problemas. Los paths de c\u00f3digo son relativos a la ra\u00edz del repositorio y las l\u00edneas pertenecen al commit/base inspeccionados.
''')
    previous_part = previous_stage = None
    fields = [('estado_actual', 'Estado actual'), ('evidencia', 'Evidencia'), ('evaluacion', 'Evaluaci\u00f3n'),
              ('problemas', 'Problemas'), ('correccion', 'Correcci\u00f3n'),
              ('implementacion_recomendada', 'Implementaci\u00f3n recomendada'), ('validacion', 'Validaci\u00f3n'), ('dependencias', 'Dependencias')]
    for row in ROWS:
        part, stage = row['parte'], row['parte'] + '.' + row['etapa']
        if part != previous_part:
            sections.append('\n### ' + ('Parte ' + part + ': ' if part != 'T' else '') + PARTS[part] + '\n')
            previous_part = part
        if stage != previous_stage:
            sections.append('\n#### Etapa ' + stage + ': ' + STAGES[stage] + '\n')
            previous_stage = stage
        sections.append('\n##### Paso ' + row['id'] + ': ' + row['requisito'] + '\n')
        sections.append('**Requisito:** ' + row['requisito'] + '. PDF, p\u00e1gina(s) ' + str(row['pagina']) + ', secci\u00f3n ' + row['seccion'] + '.\n')
        sections.append('**Estado:** ' + STATUS[row['estado']] + '.\n')
        for key, label in fields:
            value = row[key]
            if isinstance(value, list):
                value = '; '.join(value)
            sections.append('**' + label + ':** ' + value + '\n')
        criteria_table = ['| Criterio de aceptaci\u00f3n | I | V | P |', '|---|---:|---:|---:|']
        for criterion, imp, verified, pending in zip(row['criterios'], row['criterios_implementados'], row['criterios_verificados'], row['criterios_pendientes']):
            criteria_table.append('| ' + criterion.replace('|', '\\|') + f' | {imp} | {verified} | {pending} |')
        sections.append('\n'.join(criteria_table))
        count = len(row['criterios'])
        sections.append('\nPeso del paso: 1; ' + str(count) + ' criterios iguales. Cobertura ' +
                        f"{100 * sum(row['criterios_implementados']) / count:.2f} %; cumplimiento {100 * sum(row['criterios_verificados']) / count:.2f} %; pendiente {100 * sum(row['criterios_pendientes']) / count:.2f} %.\n")
    sections.append('''

## 9. \u00cdndice de evidencias y reproducci\u00f3n

| Artefacto | Contenido |
|---|---|
| enunciado.txt y pdf_sha256.txt | Extracci\u00f3n completa por p\u00e1ginas y huella del PDF oficial |
| git_status_inicial.txt, commit.txt, remotos.txt, remoto_verificado.txt | Base local, cambios del usuario y remoto verificado |
| REQUISITOS_FIJADOS.json y catalogo.py | Denominador y criterios anteriores a puntuaci\u00f3n |
| EVALUACION.json y evaluar.py | Juicios, nueve campos y referencias resueltas contra archivos reales |
| PORCENTAJES.json y MATRIZ_REQUISITOS.csv | C\u00e1lculo exacto por etapa/parte/global y trazabilidad exportable |
| preparar_entorno.sh, preparacion_entorno.log, verificar.sh, resultados_comandos.txt | Comandos efectivos y estados de salida |
| entorno_y_limpieza.json | Versiones completas instaladas y puertos 18765\u201318769 sin servidor de auditor\u00eda activo al cerrar |
| pytest.log/xml y frontend_*.log | Regresi\u00f3n, warnings, tests/tipos/build |
| demo_threads.json, integracion_http.json/log | Hilos y servidor real, con los tres fallos sin ocultar |
| probar_navegador.py, navegador.json/png, navegador_dom.html, servidor_navegador.log | Interacci\u00f3n real en dos sesiones y captura |
| navegador_intento1/2/3.json, bibliotecas_navegador.log, playwright_install.log | Fallos iniciales del entorno y preparaci\u00f3n posterior |
| probar_espacial.py, espacial_100k_real.json/log | Diferencial independiente con datos reales y ejemplos SQL rechazados |
| probar_heap_llegada.py y heap_orden_llegada.json | Reproducci\u00f3n m\u00ednima del defecto de llegada |
| inspeccionar.py, inventario_codigo.json, arquitectura.json | Imports, s\u00edmbolos, ciclos expl\u00edcitos y huellas |
| experimentos_auditados.json | 455 registros oficiales, repetici\u00f3n/configuraci\u00f3n/mezclas/procedencia |
| comparador_entorno_actual.json | Docker CLI presente, daemon no disponible; no acredita PostGIS actual |
| contrastar_reportes.py, reporte_contrastado.json, reporte_regenerado/ | Correspondencia exacta de tablas y 11 gr\u00e1ficos |
| repeticion_1k.jsonl y repeticion_reportes.log | Ensayo actual reducido, expl\u00edcitamente diagn\u00f3stico |
| COMANDOS.md | C\u00f3mo repetir en otra base temporal y recalcular la matriz |
| integridad_final.json y git_status_final.txt | Concordancia del cat\u00e1logo/matriz y preservaci\u00f3n del trabajo original |
| MANIFIESTO_SHA256.json | Huellas de artefactos de esta auditor\u00eda |

Distribuci\u00f3n de los 2.968 tests Python aprobados, sin sumarlos al porcentaje: almacenamiento 964; \u00edndices 520; operadores 400; query 316; cat\u00e1logo 207; API 155; integraci\u00f3n 137; base 97; transacciones 91; espacial 52; database 21; benchmarks 8.

Para recalcular desde la ra\u00edz: ejecutar catalogo.py, evaluar.py y redactar.py (paths en evidencias/). Para verificar sin tocar datos existentes: seguir COMANDOS.md y elegir directorios nuevos. No incorporar estas reproducciones a los tests del proyecto; permanecen como evidencia de auditor\u00eda. El manifiesto se actualiza despu\u00e9s de cualquier regeneraci\u00f3n de artefactos.

La auditor\u00eda asigna evaluaci\u00f3n trazable a todos los requisitos y una acci\u00f3n/aceptaci\u00f3n a cada brecha. Declarar una funcionalidad ausente, un artefacto externo no acreditado o un ensayo no ejecutado no equivale a ejecutarlo. El cierre de esta auditor\u00eda no constituye cierre de las partes pendientes del proyecto.
''')
    (AUDIT / 'AUDITORIA_TECNICA.md').write_text('\n\n'.join(sections) + '\n', encoding='utf-8')


if __name__ == '__main__':
    write_report()
    print('Informe generado: 77 pasos y porcentajes de la matriz.')
