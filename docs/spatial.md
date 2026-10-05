# Parte 02: datos, motor y backend espacial

E1 prepara datos persistentes y reproducibles sobre `api.database.Database`.
E2 implementa un R-Tree propio, su referencia secuencial sobre Heap, consultas
de radio/k-NN/polígono y el ciclo de persistencia, mutación y rollback.
La etapa 5 posterior a la auditoría añade SQL y exposición HTTP.
El mapa permanece postergado para la fase final de frontend.

## Convenciones fijadas

- Dominio local de Lima: latitud [-12.30, -11.80], longitud [-77.25, -76.75].
  Se rechazan coordenadas no finitas, fuera del dominio o con ejes invertidos.
- Representación física: `id INTEGER`, `nombre VARCHAR`, `latitud FLOAT`,
  `longitud FLOAT`, en Heap con RID estable mientras la fila siga activa.
- `spatial_tables.json` registra explícitamente `ubicacion` y las columnas que
  la forman. Es metadato de coordenadas; no declara un R-Tree listo.
  El propietario valida tabla, nombres y tipos al reabrir.
- SQL POINT usa (latitud, longitud); GeoJSON/PostGIS usan (longitud, latitud).
- Haversine en metros por defecto, radio terrestre 6371008.771415059 m.
  Euclidiana usará un plano local con origen (-12.0464, -77.0428), en metros.
  Ambas métricas están implementadas. La Euclidiana aproxima la distancia
  local; Haversine usa una esfera, no un elipsoide. PostGIS quedó calibrado
  en E1.5 para comparar con la misma semántica esférica.
- Polígonos simples locales sin huecos, borde incluido. La muestra es una L
  sintética, no un límite oficial de un distrito. Empates k-NN: distancia e id.
- El registro se crea offline una sola vez. No hay edición de mapeos desde
  la API. E2 registra el archivo derivado del índice en el undo existente
  y restaura/reabre el árbol después del rollback.

## Entorno y muestra de la aplicación

Desde la raíz del repositorio, con Python 3.11 o superior:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test,api,bench]"
.\.venv\Scripts\python.exe scripts/setup_spatial.py
.\.venv\Scripts\python.exe -m api --spatial
```

`setup_spatial.py` crea `data/generated/spatial` por defecto y acepta
`--data-dir` para otro directorio nuevo: rechaza cualquier destino existente. No borra ni sustituye la demo o datos del usuario.
Carga nueve filas en cada tabla (`tiendas`, `restaurantes`) mediante el servicio
de creación de tablas existente y comprueba una reapertura con objetos nuevos.
Si se interrumpe la creación, no sirve automáticamente ese directorio como una
muestra terminada: revisarlo y usar otro directorio nuevo.

Las tablas pueden consultarse con SQL relacional desde la API y los
paneles existentes. El frontend se sirve si `frontend/dist` ya está compilado.
No se anuncian presets espaciales antes de implementar las consultas:

```sql
SELECT * FROM tiendas ORDER BY id;
```

La muestra contiene coordenadas repetidas con IDs diferentes, vecinos conocidos,
un punto en el borde, uno dentro del MBR pero fuera del polígono y uno lejano.
Los IDs esperados dentro del polígono, incluyendo el borde, son 1–6.

## Entradas experimentales reproducibles

```powershell
.\.venv\Scripts\python.exe -m benchmarks.spatial
```

Genera `data/generated/spatial_inputs` con `points_1000.csv`, `points_10000.csv`,
`points_100000.csv`, `queries.csv`, `fixture.csv` e `inputs.json`. El directorio
debe ser nuevo. La semilla predeterminada es 20261003. Los datasets grandes
incluyen el mismo prefijo de puntos de los pequeños; los 100 centros se generan
con una secuencia independiente y no dependen de N. El manifiesto guarda hashes
SHA-256, dominio, métricas y parámetros. Los CSV tienen cabecera y UTF-8.

E2 ofrece carga offline mediante el propietario, sin elevar el límite HTTP
de 10.000 filas. El índice se construye una sola vez después de cargar Heap:

```powershell
.\.venv\Scripts\python.exe scripts/setup_spatial.py --size 1000
.\.venv\Scripts\python.exe scripts/setup_spatial.py --size 10000
.\.venv\Scripts\python.exe scripts/setup_spatial.py --size 100000
```

Cada comando exige un destino nuevo: por defecto `data/generated/spatial_<N>`
con una tabla `puntos`. El dataset coincide con `point_rows(N)` del generador.
La prueba automatizada ejecutó la carga y reapertura de 1.000 filas reales;
los comandos mayores quedan disponibles para E4. La prueba de 100.000 del
árbol usa RIDs sintéticos y no prueba una carga de 100.000 filas en Heap.

## PostgreSQL/PostGIS en Docker (entorno usado en E1.5)

El usuario eligió Docker después de restablecer Docker Desktop de fábrica.
El comparador usa PostgreSQL 17.5 / PostGIS 3.5.2, contenedor
`minidbms-postgis`, volumen persistente `minidbms-spatial-e1-pgdata` y puerto
`127.0.0.1:5433`. El PostgreSQL nativo conserva su puerto 5432.
La imagen `postgis/postgis:17-3.5` está fijada al digest
`sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6`.
Fuente de la imagen: [Docker PostGIS](https://github.com/postgis/docker-postgis).

Con Docker Desktop iniciado, desde PowerShell en la raíz del repositorio:

```powershell
# Solo para crear un entorno nuevo: rechaza contenedor, volumen o credenciales existentes.
.\scripts\setup_postgis.ps1
.\.venv\Scripts\python.exe -m benchmarks.spatial.postgres --container minidbms-postgis

# Cada N se prepara en una base nueva; nunca se reemplazan esquemas existentes.
docker exec minidbms-postgis createdb -w -U postgres minidbms_spatial_10000
.\.venv\Scripts\python.exe -m benchmarks.spatial.postgres --container minidbms-postgis --size 10000 --database minidbms_spatial_10000
docker exec minidbms-postgis createdb -w -U postgres minidbms_spatial_100000
.\.venv\Scripts\python.exe -m benchmarks.spatial.postgres --container minidbms-postgis --size 100000 --database minidbms_spatial_100000
```

El script genera una contraseña aleatoria y la guarda únicamente en
`data/generated/postgres_e1/postgres.env`, ignorado por Git. No la muestra ni
la recibe por chat. La conexión del preparador utiliza el socket Unix interno
del contenedor y su autenticación local existente; no requiere `pgpass.conf`
de Windows. `--host` y `--port` solo corresponden al modo nativo.
Para conexiones desde Windows al puerto 5433, configure sus credenciales
locales por separado; el pgpass del PostgreSQL nativo no se reutiliza por defecto.

Antes de contactar Docker se verifican los hashes de los CSV. Se copian a un
directorio temporal exclusivo del contenedor y se eliminan esas dos copias al
terminar, incluso si psql falla. El contenedor y el volumen se conservan.
Para volver a iniciar el entorno ya creado: `docker start minidbms-postgis`.

Evidencia de preparación: `benchmarks/results/spatial_e1_setup.json` y
`benchmarks/results/logs/spatial-e1-postgres-{1000,10000,100000}.log`.
Se verificaron todos los valores de los 111.000 puntos y los centros
contra los CSV después de reiniciar el contenedor, con cero errores de
ejes. El radio esférico real difiere del adoptado en menos de 1e-6 m.
Los EXPLAIN son diagnósticos de preparación, no mediciones oficiales de E4.
El radio y el k-NN usan GiST sin forzar el planner. La comparación completa
contra el R-Tree y la matriz experimental quedan para E2/E4.

## PostgreSQL nativo con pgpass (alternativa)

PostgreSQL es únicamente el comparador externo. Se usa `psql -X -w` y no se
reciben contraseñas como argumentos. En Windows configure
`%APPDATA%/postgresql/pgpass.conf` fuera del repositorio, con el formato
`host:puerto:base:usuario:contraseña`, o use `PGPASSFILE`.

Compruebe la autenticación y PostGIS con sus herramientas locales:

```powershell
psql -X -w -h localhost -U postgres -d postgres -c "SELECT name, default_version FROM pg_available_extensions WHERE name='postgis';"
createdb -w -h localhost -U postgres minidbms_spatial
.\.venv\Scripts\python.exe -m benchmarks.spatial.postgres
```

Si las herramientas no están en PATH, use su ruta instalada; el preparador
acepta `--psql`, `--host`, `--port`, `--user` y `--database`.
PostGIS debe estar disponible previamente para `CREATE EXTENSION`.

El preparador verifica hashes y crea el esquema separado
`minidbms_spatial_bench`, carga un CSV, construye GiST y muestra conteos,
versiones, radio esférico real y planes de radio/k-NN. Rechaza un esquema ya
existente; no ejecuta DROP. Para otra N use otra base de comparación nueva.
La preparación no sustituye las mediciones de E4: falta separar carga,
construcción y consultas temporizadas, recorrer toda la matriz y validar
identidades/distancias con el motor propio. Inspeccione el método realmente
usado en EXPLAIN; una elección secuencial del planner no es evidencia de GiST.

Puede producir el SQL sin conectarse:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.spatial.postgres --sql-output data/generated/spatial_inputs/postgres_1000.sql
```

Se usa el modo esférico `false` de
[ST_DWithin](https://postgis.net/docs/ST_DWithin.html) y el residual estricto
`ST_Distance(..., false) < radio`. El orden k-NN usa
[geography <->](https://postgis.net/docs/geometry_distance_knn.html).
El subconjunto de puntos empatados del comparador se validará según el criterio
del plan, sin asumir que su orden coincide con el desempate por ID del motor.

## Parte 01 pendiente

El commit de inicio es `e0ad051a2ed25b095e5d666bcc7e93dc6452430f`.
**Actualización 2026-10-04:** la Etapa 10 y la Parte 01 están cerradas
([auditoría](ETAPA_10_AUDIT.md)). Los resultados oficiales de 100.000 filas son
las corridas WSL de la Etapa 10, en la misma máquina que 1.000/10.000; las
corridas Windows descritas abajo solo sirven como evidencia complementaria.
El texto que sigue conserva el registro original de E1.5.
Los comandos existentes permanecen separados de Parte 02:

```powershell
.\.venv\Scripts\python.exe -m benchmarks run --experiment files --sizes 100000 --repetitions 3
.\.venv\Scripts\python.exe -m benchmarks run --experiment indexes --sizes 100000 --repetitions 3
.\.venv\Scripts\python.exe -m benchmarks report
```

Estos comandos son el trabajo restante de Etapa 10/E4, no pruebas rápidas de E1.
E1.5 inicia las corridas de 100.000 en procesos separados, con tres repeticiones
y un núcleo por proceso. Sus resultados Windows se guardan por separado de
la evidencia histórica WSL/Linux: `part1_results_100k_windows_files.jsonl` y
`part1_results_100k_windows_indexes.jsonl`. No se deben mezclar sus tiempos con
los resultados históricos para inferir escalabilidad entre N.
Cada fila registra entorno, configuración, commit y digest de las fuentes.
Estar iniciadas no significa que las corridas hayan terminado ni cierra Etapa 10.
Los experimentos de Parte 01 y Parte 02 conservan datos y resultados separados.
Antes de modificar las fuentes para E2 se conservó su snapshot en
`data/generated/postgres_e1/part1_source_snapshot`, con el digest de lanzamiento
`4905f38e904ea3a545c45dce04f92b96c3e2d413081e2473eda5f38bcaea9450`.
Las corridas ya iniciadas usan los módulos originales cargados en sus procesos.

## Verificación E1

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -W error tests/spatial tests/api tests/benchmarks tests/transactions tests/database
```

Incluye reproducción de los datos, ejes/dominio inválidos, reapertura con
mapeo, referencias de metadatos inválidas, coordenadas duplicadas con RIDs
distintos, entradas del comparador alteradas y regresión de API/persistencia.
Resultado ejecutado: **296 pruebas aprobadas en 125.96 s** el 2026-10-03,
con advertencias como errores. No se ejecutó la suite completa.
Consulte el progreso y los resultados efectivamente ejecutados en
`PART_02/PLAN_PARTE_02.md`.


## Consultas del motor E2

Ejemplo Python sobre la muestra preparada (desde la raíz del proyecto):

```python
from pathlib import Path
from api.database import Database
from scripts.setup_spatial import SPATIAL_DATABASE
from engine.spatial import Metric, Point, Polygon
from benchmarks.spatial.datasets import FIXTURE_POLYGON

center = Point(-12.0464, -77.0428)  # latitud, longitud
polygon = Polygon(tuple(Point(*pair) for pair in FIXTURE_POLYGON))
with Database.open(SPATIAL_DATABASE, Path("data/generated/spatial")) as db:
    radius = db.spatial_radius("tiendas", center, 5000)
    nearest = db.spatial_knn("restaurantes", center, 10, metric=Metric.EUCLIDEAN)
    inside = db.spatial_polygon("tiendas", polygon)
    baseline = db.spatial_knn("restaurantes", center, 10,
                              metric=Metric.EUCLIDEAN, use_index=False)
    assert nearest.hits == baseline.hits
    print([(hit.identity, hit.distance_metres, hit.rid) for hit in nearest.hits])
    print(nearest.stats)
```

Los resultados contienen ID, Point, RID, Record leído del Heap y distancia
en metros (sin distancia para polígono). El radio usa `<` por defecto;
`inclusive=True` selecciona `<=`. Se acepta radio cero, k=0 y k>N. Radio y
polígono ordenan por ID; k-NN ordena por distancia e ID. El polígono incluye
el borde, admite concavidad y rechaza autointersecciones/área degenerada.
La orientación usa tolerancia proporcional al segmento y a los ULP de las
coordenadas; polígonos válidos pequeños conservan su interior.

Estos métodos admiten `session=sesion` de `db.open_session()`, usan los locks
S existentes y responden a cancelación. Sin sesión explícita usan la sesión
predeterminada. No acceda directamente al árbol cacheado desde el frontend.
Las expresiones POINT/distancia y LIMIT también están disponibles en SELECT
y EXPLAIN mediante el backend descrito a continuación.

## SQL y API espacial

```sql
SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;

SELECT id, distancia(ubicacion, POINT(-12.0464, -77.0428), 'euclidean') AS metros
FROM tiendas ORDER BY metros LIMIT 10;
```

Ambas distancias producen metros; la métrica por defecto es `haversine`.
`DISTANCE` es un alias de `distancia`. Se aceptan ubicaciones calificadas por
alias, límites cero, límites superiores al número de filas y radio inclusivo
con `<=`. POINT requiere dos literales numéricos dentro del dominio local.
`LIMIT` también funciona en consultas relacionales, después de filtro,
agrupación, ordenamiento y proyección.

Para el ejemplo parametrizado del PDF, `POST /api/query` acepta:

```json
{
  "sql": "SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10",
  "parameters": {"mi_ubicacion": [-12.0464, -77.0428]},
  "use_indexes": true
}
```

En Python, use `engine.execute(sql, parameters={"mi_ubicacion": [-12.0464,
-77.0428]})` o `session.prepare` con el mismo argumento. Cada consulta
preparada conserva una copia inmutable; ninguna sesión hereda parámetros de
otra. Un parámetro ausente genera un diagnóstico SQL controlado. Un error de
ejecución dentro de un grupo aborta y restaura sus escrituras, como antes.

El plan muestra `SpatialIndexScan` para radio y k-NN elegibles, y `SpatialScan`
con `use_indexes=false`. Los nodos `Compute`, `Filter`, `ExternalSort`,
`Projection` y `Limit` corresponden a operadores ejecutados. No se limita el
vecindario antes de filtrar: con predicados adicionales, el orden por distancia
usa candidatos completos y aplica LIMIT al final. OR/NOT no autorizan poda de
radio; AND sí, conservando el filtro completo. Empates por distancia usan id.
JOIN y GROUP BY con expresiones espaciales quedan fuera de este SQL limitado;
sus variantes relacionales anteriores siguen disponibles.

`POST /api/spatial/query` proporciona el contrato geométrico para el futuro
mapa, con `X-Session-Token` opcional:

```json
{"table":"tiendas","kind":"radius","center":[-12.0464,-77.0428],"radius":5000,"metric":"haversine"}
{"table":"tiendas","kind":"knn","center":[-12.0464,-77.0428],"k":10,"metric":"euclidean"}
{"table":"tiendas","kind":"polygon","vertices":[[-12.05,-77.05],[-12.05,-77.03],[-12.03,-77.03],[-12.03,-77.05]]}
```

Las respuestas incluyen `matches` con id, coordenadas, distancia y registro;
`total_rows`, `returned_rows`, `truncated` y estadísticas reales de búsqueda.
`max_rows` limita la vista a 500 filas como máximo; el límite de bytes también
se aplica sin recortar valores. `use_indexes=false` selecciona el recorrido
exhaustivo. Los polígonos incluyen el borde y conservan la semántica E2.
Las lecturas usan los locks existentes y esperan por escritores sin retener
el guard global de solicitudes sin sesión. El núcleo E2 materializa los hits
de radio/polígono; el límite HTTP acota la respuesta, no esa materialización.

La comprobación reproducible `scripts/spatial_integration_check.py` usa un
directorio nuevo, servidor TCP separado, ambas métricas, consultas SQL y
polígonos, errores, sesiones concurrentes, commit, rollback y reapertura.
No abre ni valida frontend. Sus resultados actuales se guardan en
`docs/implementacion/evidencias/espacial_servidor.json`.

## Experimentos completos y frontend pendiente

La comparación oficial ya incluye Heap secuencial, R-Tree propio y PostgreSQL
GiST en 1.000/10.000/100.000 puntos, radios 1/5/10 km y k=10/50/100, con
100 consultas por configuración. Hay 5.400 mediciones, promedios aritméticos,
construcción, espacio y memoria; los resultados coinciden con el oráculo
independiente y los planes del comparador acreditan GiST. Consulte
[datos, gráficos y reproducción](EXPERIMENTOS_ESPACIALES.md).

No se ha implementado ni comprobado el mapa. El usuario pausó todo frontend
hasta una nueva autorización. El backend SQL/HTTP y las mediciones están
disponibles, pero esto no equivale a cerrar la Parte 2 completa. El informe
académico se realiza por separado; no se generó uno en esta fase.

## R-Tree y ciclo de vida E2

- Árbol propio en memoria; capacidad 16, mínimo 8 entradas por nodo no raíz.
  El núcleo permite capacidades 4–64 y mínimo `capacity // 2`.
  Elige subárbol por ampliación/área, divide con semillas cuadráticas,
  propaga splits y crece la raíz. Valida ocupación, cobertura exacta del
  padre, profundidad uniforme, recuentos e IDs/RIDs únicos.
- MBR en grados para organización y polígonos. La poda Euclidiana usa metros
  del plano fijo; Haversine usa el hueco de latitud `R * delta_phi`, con
  margen numérico conservador. Ignorar longitud reduce la poda pero mantiene
  respuestas correctas. k-NN usa cola de prioridad y conserva k candidatos;
  explora cotas iguales para respetar empates por ID.
- `stats.access` distingue `RTree` de `SpatialScan`. `visited_nodes`,
  `candidates` y `base_records_read` cuentan trabajo real. La referencia
  secuencial lee Heap; el árbol resuelve únicamente sus resultados por RID.
- Archivo `__spatial_<tabla>.rtree`, JSON `MINIDBMS_RTREE` v1, SHA-256,
  convenciones y mapeo. Save valida y publica mediante archivo temporal,
  flush/fsync y reemplazo atómico. No es un índice paginado ni implementa WAL.
  Al abrir, construye una vez si falta el archivo; si existe corrupto o no
  coincide con Heap, rechaza la apertura. No oculta corrupción reconstruyendo.
- INSERT relacional valida dominio/ID antes de escribir y mantiene el árbol.
  DELETE reconstruye una vez por sentencia con filas afectadas. El archivo
  participa como recurso auxiliar en el undo existente; rollback restaura
  archivos y sustituye los objetos cacheados usando el nuevo Heap abierto.
  Se mantienen los límites existentes ante caídas y commits de varios archivos.

## Verificación E2

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -W error tests/spatial tests/api tests/transactions tests/database tests/benchmarks
.\.venv\Scripts\python.exe -m pytest -q -W error tests
```

Las pruebas cubren referencias geométricas, métricas distintas, límites,
vacíos, duplicados, árbol multinivel, guardado atómico fallido, corrupción,
reapertura, datos reales, INSERT/DELETE, rollback, locks y cancelación.
También prueban carga offline de 1.000 filas con una sola construcción.

La comprobación independiente de 100.000 puntos produjo altura 5 y 9.738
nodos; guardado y reapertura preservaron sus asociaciones. Coincidieron
36 consultas de radio/k-NN contra recorrido exhaustivo (ambas métricas,
tres centros, radios 1/5/10 km y k=10/50/100), con poda real en cada caso,
y el polígono concavo también coincidió. Evidencia:
`benchmarks/results/spatial_e2_100k_smoke.json`. Usa RIDs sintéticos; no es
la integración Heap de 100.000 ni la matriz oficial E4. Su tiempo diagnóstico
se obtuvo mientras corrían los experimentos de Parte 01.

Las muestras reales `tiendas`/`restaurantes` conservan sus nueve filas y
coinciden con Heap en ambas métricas y polígono después de reabrir:
`benchmarks/results/spatial_e2_owner_smoke.json`. Esta comprobación también
revalidó el polígono sobre el árbol de 100.000 con la geometría final.
La suite completa ejecutó **2.964 casos en 2035.07 s**: pasaron
**2.963** y falló la lista arquitectónica que aún no reconocía `spatial`.
Se actualizó esa regla con dependencias explícitas y se añadieron tres
importaciones aisladas del motor espacial. La revisión final pasó **22 pruebas
de arquitectura en 66.32 s**. No cambió ningún código
del motor después de la suite completa: las dos ejecuciones verifican
**2,967 casos finales distintos**, incluyendo toda la Parte 01 y
el polígono pequeño. No se afirma haber repetido la suite completa tras un
cambio exclusivo en la auditoría. Ambas ejecuciones usaron advertencias como
errores. Las 325 pruebas enfocadas previas pasaron en 126.12 s.
El `.venv` local apuntaba a un Python ausente; se conservó sin cambios y se
usó un entorno temporal Python 3.12.14 con las dependencias existentes,
pytest 8.4.2 y resolución del paquete para subprocesos aislados. Para ejecutar
los comandos publicados, use un venv funcional e instale el proyecto editable.
Evidencia: `benchmarks/results/spatial_e2_verification.json`,
`benchmarks/results/logs/spatial-e2-tests.log` y
`benchmarks/results/logs/spatial-e2-architecture.log`.
