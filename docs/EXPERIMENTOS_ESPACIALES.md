# Resultados experimentales espaciales

Datos y gráficos para la Parte 2, §2.2 del PDF. Este documento describe el
protocolo y los archivos técnicos; no es el informe académico, que el equipo
prepara por separado. No acredita un mapa ni una entrega completa de Parte 2.

## Archivos disponibles

- [Radio: PNG](figuras/spatial/radius.png) y [SVG](figuras/spatial/radius.svg).
- [k-NN: PNG](figuras/spatial/knn.png) y [SVG](figuras/spatial/knn.svg).
- [Construcción y espacio: PNG](figuras/spatial/recursos.png) y
  [SVG](figuras/spatial/recursos.svg).
- [Memoria: PNG](figuras/spatial/memoria.png) y [SVG](figuras/spatial/memoria.svg).
- [Tabla de consultas](figuras/spatial/consultas.csv): 54 configuraciones;
  media aritmética, mediana, mínimo, máximo y número de resultados.
- [Tabla de recursos](figuras/spatial/recursos.csv): nueve procesos medidos.
- [Verificación y hashes](figuras/spatial/verificacion.json).
- [Datos originales](../benchmarks/results/spatial/2026-10-04/): nueve JSONL,
  nueve archivos de recursos, tres oráculos, manifests y código archivado.

No se conservan en Git los archivos Heap/R-Tree temporales ni la base
PostgreSQL. Las entradas CSV se regeneran exactamente con la semilla y los
hashes guardados; el generador de gráficos comprueba esa reproducción.

## Protocolo ejecutado

La matriz contiene 1.000, 10.000 y 100.000 puntos sintéticos del dominio local
de Lima; no son tiendas reales. La semilla de datos es 20261003 y la de los
centros 20261004. Los tres métodos reciben los mismos valores, IDs y los
mismos 100 centros, independientes del tamaño del dataset. PostgreSQL verifica
todos los registros cargados contra el CSV antes de construir su GiST.

Cada método ejecuta radios estrictos de 1.000/5.000/10.000 metros y k=10/50/100.
Son 3 tamaños × 3 métodos × 6 configuraciones × 100 consultas = **5.400 tiempos**.
Cada configuración se valida primero con sus 100 consultas; después se mide
una segunda pasada y se valida nuevamente cada resultado fuera del reloj.
No se agrupan esas dos pasadas como repeticiones estadísticas del tiempo.
No hubo limpieza de caché; los resultados corresponden a consultas calientes
después de la comprobación previa. Las curvas usan la media aritmética de
los 100 tiempos de cada configuración, sin sustituirla por la mediana.

El oráculo independiente usa búsqueda exhaustiva y `atan2`, comprueba el
conjunto exacto de IDs, ausencia de duplicados, todas las distancias con
tolerancia absoluta 0,00001 m, orden k-NN y empates por ID. Los IDs se guardan
como hashes en los tiempos; los valores y la validación completa se verifican
durante la ejecución mediante el código conservado. El generador de gráficos
comprueba hashes, conteos, centros, 100 IDs de consulta distintos por grupo,
tiempos finitos y positivos y planes GiST reales. No recalcula tiempos.

La matriz usa Haversine. Ambas métricas siguen siendo funcionalidad exigida:
Euclidiana fue verificada por pruebas geométricas y servidor real. No se
presenta una segunda matriz temporal Euclidiana ni una matriz de rendimiento
de polígonos; ninguna está prescrita por el PDF. La corrección de polígonos
cóncavos, bordes y puntos que solo pertenecen al MBR tiene pruebas separadas.

## Comparador y límites de medición

PostgreSQL es exclusivamente el comparador. Se utilizó PostgreSQL 17.5 y
PostGIS 3.5.2, imagen `postgis/postgis:17-3.5` con digest
`sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6`.
El contenedor temporal no expuso puertos ni red; usó 2 GiB de límite,
`shared_buffers=128MB` y `work_mem=4MB`. El motor propio sigue usando Heap y
R-Tree implementados en el proyecto.

`geography(Point,4326)` conserva longitud/latitud en PostGIS; el contrato
propio recibe latitud/longitud. `ST_DWithin(...,false)` es el filtro inclusivo
de candidatos, seguido de `ST_Distance(...,false) < radio` para el radio
estricto. El k-NN usa `<->` y un desempate por ID. La distancia esférica de
PostGIS se calibró contra el radio declarado del motor. Véanse
[ST_DWithin](https://postgis.net/docs/ST_DWithin.html) y
[operador k-NN](https://postgis.net/docs/geometry_distance_knn.html).

Se desactivaron `enable_seqscan`, `enable_bitmapscan`, paralelismo y JIT para
medir específicamente GiST. Cada consulta previa ejecutó
`EXPLAIN (ANALYZE, TIMING OFF, BUFFERS, FORMAT JSON)` y acreditó el índice
`points_location_gist`: **1.800 planes ejecutados**, conservados en los JSONL.
Los tiempos posteriores no incluyen EXPLAIN. Los planes corresponden al mismo
SQL, datos y estadísticas del contexto inmutable, no a otra consulta de ejemplo.
[EXPLAIN de PostgreSQL](https://www.postgresql.org/docs/17/sql-explain.html).

El tiempo de cliente mide resolución completa de resultados, proyección a
ID/distancia y serialización/decodificación. En PostgreSQL incluye el transporte
local de `psql`/Docker; `mean_server_ms` registra separadamente su reloj del
servidor. No se compara un tiempo interno PostgreSQL con un tiempo completo
Python sin advertir esa diferencia. No se incluyen SQL/API HTTP ni renderizado
del mapa en esta matriz: mide las estructuras utilizadas por el motor.

Construcción se mide separada de cargar los puntos: R-Tree incluye leer Heap,
construir, serializar y hacer fsync; GiST incluye CREATE INDEX persistente y
su transporte. No hay tiempo de construir índice para búsqueda secuencial.
El espacio usa tamaños reales de archivos y relaciones; el índice primario
PostgreSQL se registra aparte. `data_bytes` en PostgreSQL incluye su columna
geográfica adicional y estructuras de la relación, a diferencia del Heap.

La memoria es `/proc/<pid>/status:VmHWM`, el máximo observado por el kernel
durante toda la vida de un proceso independiente por método/tamaño, leído al
final; no es muestreo de asignaciones Python. Los trabajadores propios incluyen
imports, oráculo, validación, buffers de resultados y construcción. El backend
PostgreSQL incluye mapeos compartidos, pero excluye Docker, `psql` y otros
procesos del servidor. Los dos ámbitos se grafican por separado: no son el
consumo total del sistema ni un coste incremental exclusivo del índice.

Una sola matriz no acredita estabilidad entre ejecuciones, intervalos de
confianza ni rendimiento en otras máquinas/distribuciones. Los percentiles o
repeticiones adicionales no se inventan. El manifest registra Python 3.11.9,
WSL2 x86-64 y 24 CPU lógicas; cada trabajador es secuencial. La matriz comenzó
el 2026-10-04 en hora local (2026-10-05 UTC).

## Lectura de los resultados

Para 100.000 puntos, las medias completas de cliente en milisegundos son:

| Consulta | Secuencial | R-Tree propio | PostgreSQL GiST |
|---|---:|---:|---:|
| Radio 1 km | 1055,219 | 21,237 | 1,369 |
| Radio 5 km | 1059,970 | 345,604 | 6,899 |
| Radio 10 km | 1079,312 | 1252,702 | 21,808 |
| k=10 | 1101,233 | 6,724 | 0,947 |
| k=50 | 1110,973 | 14,266 | 1,193 |
| k=100 | 1128,657 | 22,467 | 1,261 |

No todos los radios favorecen al R-Tree. A 100.000 puntos y 10 km, su resolución
por RIDs y materialización de unos 9.116 hits por centro cuesta más que el
recorrido del Heap. Es una limitación de rendimiento demostrada, sin error
de resultados ni justificación para ocultar mediciones. k-NN y radios pequeños
sí evitan gran parte del recorrido. El núcleo Haversine usa una cota
conservadora de latitud: garantiza resultados pero reduce la poda.

| Método | Ventaja observada | Coste o limitación |
|---|---|---|
| Secuencial | Sin índice ni construcción; recorrido simple | Escala aproximadamente con N; consulta completa en cada búsqueda |
| R-Tree propio | Poda real y menor tiempo para k-NN/radios pequeños | Árbol residente en memoria; muchos hits exigen lecturas por RID; radio amplio puede ser más lento |
| GiST comparador | Menores tiempos en esta matriz de 100.000 | DBMS externo optimizado; ámbito de memoria y representación distintos; solo es comparador |

En 100.000 puntos, R-Tree construyó en 10,818 s y ocupó 4.888.031 bytes de
índice; GiST construyó en 0,259 s de cliente (0,251 s internos) y ocupó
7.315.456 bytes, más 2.260.992 bytes del índice primario. Los CSV conservan
todos los valores sin redondear. No se sustituyen por extrapolaciones.

## Reproducción

Desde un entorno con el proyecto instalado y sus dependencias existentes:

```bash
# Regenerar gráficos y tablas sin servidor ni repetir mediciones:
python -m benchmarks.spatial results --input benchmarks/results/spatial/2026-10-04 --output docs/figuras/spatial

# Repetir la matriz en un directorio NUEVO, con un comparador ya preparado:
python -m benchmarks.spatial run --output /tmp/nueva-matriz-espacial --container <contenedor-postgis> --source-commit <commit-real>
```

El usuario prepara el contenedor comparador con PostgreSQL/PostGIS y la base
`minidbms_bench`; también puede indicar `--database`. El harness crea un
schema exclusivo por tamaño, lo elimina al finalizar y rechaza reutilizar
directorios. No se permite apuntar las pruebas a bases del usuario.
El comando real de esta ejecución está en
[validar_experimento_espacial.sh](implementacion/evidencias/validar_experimento_espacial.sh)
y el [log completo](implementacion/evidencias/espacial_experimento_oficial.log).

El código medido es el commit `14f94f0e14e58d86cfe92c05adf72b9b70de8cd6`,
con una copia exacta `source.tar.gz` y hashes de cada archivo; el archivado evita
atribuir a ese commit cambios posteriores. Los gráficos tienen su propia
verificación de entradas/salidas y se generan con `benchmarks/spatial/results.py`.
