# Comparación experimental — Parte 1

Esta sección responde a la comparación experimental del enunciado (§2.1.6):
Heap File frente a Archivo Secuencial Paginado, e índice B+ agrupado frente a
B+ no agrupado y Hash extensible, con 1 000, 10 000 y 100 000 registros. Todos
los valores salen de corridas reales; las tablas completas con mínimo y máximo
están en [experimentos/resultados.md](experimentos/resultados.md) y los
gráficos en [experimentos/](experimentos/).

## 1. Método

**Datos.** Una tabla de estudiantes con esquema `id INTEGER` (clave única),
`name VARCHAR`, `career VARCHAR`, `age INTEGER`, `score INTEGER`. Para cada
tamaño N, `id` es una permutación aleatoria de 1..N generada con la semilla
`20 261 000 + N`; ese es el orden de llegada en todas las cargas. Los mismos
registros alimentan todas las estructuras, y la generación nunca está dentro
de una medición.

**Medición.** Tiempo de reloj con `time.perf_counter`, sobre las clases de
almacenamiento e índices que usa el planner. Cada medición construye sus
archivos en un directorio temporal propio y lo borra al terminar; en el
experimento de índices, cada estructura trabaja sobre su propia copia del
archivo base. Los archivos se acaban de escribir, así que la caché de páginas
del sistema operativo está caliente.

**Repeticiones.** 5 para 1 000 y 10 000 registros, 3 para 100 000. Se reporta
la mediana; el rango [mínimo – máximo] está en las tablas completas. Las
búsquedas promedian además 100 a 200 consultas dentro de cada repetición.

**Operaciones.**

| Experimento | Operaciones |
|---|---|
| Organización de archivos | carga completa (el secuencial también en orden ascendente); 100 búsquedas por clave presente y 20 ausentes; espacio en disco; eliminación lazy del 40 % de las filas; tiempo de `reorganize()`; reinserción en el Heap para ver la reutilización de espacio |
| Índices | construcción y espacio adicional; 200 búsquedas por igualdad presentes y 50 ausentes; 10 rangos de selectividad 0,1 %, 1 % y 10 %; recuperación ordenada de toda la tabla; carga mixta de inserciones y eliminaciones (200 operaciones o 60 s, lo que ocurra primero) seguida de una validación completa de la estructura |

El B+ agrupado indexa un Archivo Secuencial ordenado por `id`; el B+ no
agrupado y el Hash indexan un Heap File. El Hash no tiene orden: sus rangos
miden lo que el motor hace sin índice ordenado (recorrer el Heap y filtrar) y
su recuperación ordenada mide `SELECT ... ORDER BY` del motor SQL, que usa
`ExternalSort`.

**Entorno.** Linux (WSL2) x86-64, 8 CPU, 7 GiB de RAM, Python 3.11.9, una sola
máquina para los tres tamaños. Las corridas de 100 000 registros ejecutaron
los dos experimentos en paralelo, cada uno en un proceso de un solo hilo, con
núcleos libres y sin otra carga. Cada fila de resultados guarda la
configuración, el commit y un SHA-256 de todo el código del motor y de los
experimentos.

**Ajustes previos.** Antes de medir se corrigieron cuatro costos de
implementación en módulos de etapas anteriores (validación repetida de
páginas, búsqueda lineal y política de división en el secuencial, decodificación
repetida en B+ y Hash). No cambian ninguna técnica exigida; la justificación y
el efecto de cada uno están en
[informe/ajustes_modulos_previos.md](informe/ajustes_modulos_previos.md).

**Reproducción.**

```bash
python -m benchmarks run --experiment all --sizes 1000 10000 --repetitions 5
python -m benchmarks run --experiment files --sizes 100000 --repetitions 3
python -m benchmarks run --experiment indexes --sizes 100000 --repetitions 3
python -m benchmarks plans --size 10000          # planes SQL (sección 4)
python -m benchmarks report --results <archivos .jsonl>   # gráficos y tablas
```

Resultados oficiales: `benchmarks/results/part1_results.jsonl` (1 000 y
10 000), `part1_results_100k_files.jsonl`, `part1_results_100k_indexes.jsonl`
y `part1_sql_plans.jsonl`.

## 2. Heap File frente a Archivo Secuencial Paginado

| Medida (mediana) | Estructura | 1 000 | 10 000 | 100 000 |
|---|---|---:|---:|---:|
| Carga completa | Heap | 0,33 s | 3,45 s | 36,0 s |
| | Secuencial, orden aleatorio | 8,1 s | 93,9 s | 1 289 s |
| | Secuencial, orden ascendente | 5,5 s | 61,7 s | 672 s |
| Búsqueda por clave presente | Heap | 4,1 ms | 41,5 ms | 431 ms |
| | Secuencial | 0,82 ms | 1,20 ms | 1,65 ms |
| Búsqueda por clave ausente | Heap | 8,3 ms | 84,3 ms | 871 ms |
| | Secuencial | 0,43 ms | 0,87 ms | 1,16 ms |
| Espacio tras la carga | Heap | 56 KiB | 512 KiB | 5 080 KiB |
| | Secuencial, orden aleatorio | 76 KiB | 716 KiB | 7 328 KiB |
| | Secuencial, orden ascendente | 56 KiB | 512 KiB | 5 084 KiB |
| Reorganización tras borrar 40 % | Secuencial | 0,07 s | 0,70 s | 7,2 s |

Gráficos: [inserción](experimentos/01_insercion.png),
[búsqueda por clave](experimentos/02_busqueda_pk.png),
[espacio](experimentos/03_espacio_archivos.png),
[reorganización](experimentos/04_reorganizacion.png).

**Inserción.** El Heap agrega al final de la última página con espacio:
~0,35 ms por registro en los tres tamaños, es decir, crecimiento lineal. El
secuencial tiene que mantener el orden: ubica la página por búsqueda binaria,
inserta en su posición y, si la página está llena, la divide y desplaza las
páginas siguientes (el archivo es contiguo). Con orden aleatorio cuesta 36
veces más que el Heap con 100 000 registros, y el costo por registro sube con
el tamaño (8,1 → 9,4 → 12,9 ms) por ese desplazamiento. Con datos que llegan
ordenados cada registro va al final, sin divisiones intermedias: la carga
tarda la mitad.

**Búsqueda por clave primaria.** El Heap no tiene orden: recorre el archivo
hasta encontrar la clave (la mitad en promedio) o hasta el final si no existe;
por eso la clave ausente cuesta el doble y ambas crecen 10 veces por cada
tamaño. El secuencial hace búsqueda binaria sobre sus páginas y casi no crece:
con 100 000 registros es 260 veces más rápido para claves presentes y 750
veces para ausentes.

**Espacio.** Cargado en orden aleatorio, el secuencial ocupa un 44 % más que el
Heap, porque cada división deja dos páginas a medio llenar. Cargado en orden
ascendente ocupa lo mismo que el Heap (páginas llenas).

**Eliminación y reorganización.** Borrar el 40 % de las filas es lazy en el
secuencial (marca el slot como libre) y deja un desperdicio medido de 27,5 % a
28,3 % del espacio de sus páginas: la fórmula divide los huecos por el total
de bytes de las páginas, incluido el espacio que nunca se usó, así que no
llega al 30 % aunque se haya borrado el 40 % de las filas. La reorganización
es una operación explícita del archivo; el experimento la invoca para medir su
costo. Reescribe el archivo compacto en tiempo lineal (7,2 s con 100 000
registros) y lo reduce de 7 328 KiB a 3 052 KiB, porque además de quitar los
huecos de lo borrado vuelve a llenar las páginas que la carga aleatoria había
dejado a medias (1 831 → 762 páginas).

**Reutilización de espacio en el Heap.** Tras borrar el 40 % de las filas y
volver a insertar la misma cantidad, el archivo no crece con 1 000 registros
y crece apenas un 1,2 % con 100 000 (5 080 → 5 140 KiB): las inserciones
ocupan los huecos libres antes de pedir páginas nuevas.

## 3. B+ agrupado frente a B+ no agrupado y Hash extensible

| Medida (mediana) | Estructura | 1 000 | 10 000 | 100 000 |
|---|---|---:|---:|---:|
| Construcción del índice | B+ agrupado | 3,4 s | 36,8 s | 404 s |
| | B+ no agrupado | 3,1 s | 33,1 s | 403 s |
| | Hash extensible | 3,7 s | 42,4 s | 483 s |
| Espacio adicional | B+ agrupado | 36 KiB | 320 KiB | 3 172 KiB |
| | B+ no agrupado | 32 KiB | 256 KiB | 2 220 KiB |
| | Hash extensible | 40 KiB | 264 KiB | 2 056 KiB |
| Igualdad, clave presente | B+ agrupado | 0,64 ms | 0,93 ms | 1,63 ms |
| | B+ no agrupado | 0,68 ms | 0,99 ms | 2,75 ms |
| | Hash extensible | 0,42 ms | 0,51 ms | 0,59 ms |
| Rango 0,1 % | B+ agrupado | 0,60 ms | 2,2 ms | 21,7 ms |
| | B+ no agrupado | 0,64 ms | 2,4 ms | 29,0 ms |
| | Hash (recorre el Heap) | 8,4 ms | 83 ms | 873 ms |
| Rango 1 % | B+ agrupado | 2,2 ms | 17,7 ms | 193 ms |
| | B+ no agrupado | 2,1 ms | 18,7 ms | 189 ms |
| | Hash (recorre el Heap) | 8,7 ms | 84,7 ms | 870 ms |
| Rango 10 % | B+ agrupado | 17,6 ms | 177 ms | 1 848 ms |
| | B+ no agrupado | 17,7 ms | 178 ms | 1 879 ms |
| | Hash (recorre el Heap) | 8,5 ms | 85,6 ms | 860 ms |
| Recuperación ordenada completa | B+ agrupado | 0,17 s | 1,70 s | 17,0 s |
| | B+ no agrupado | 0,16 s | 1,67 s | 17,3 s |
| | Hash + `ExternalSort` | 0,06 s | 0,75 s | 8,9 s |
| Inserciones/eliminaciones | B+ agrupado | 0,58 ops/s | 0,041 ops/s | 0,002 ops/s |
| | B+ no agrupado | 208 ops/s | 237 ops/s | 220 ops/s |
| | Hash extensible | 255 ops/s | 242 ops/s | 234 ops/s |

Gráficos: [construcción](experimentos/05_construccion_indices.png),
[espacio](experimentos/06_espacio_indices.png),
[igualdad](experimentos/07_igualdad.png),
[rango 1 %](experimentos/08_rango_1pct.png),
[rango 10 %](experimentos/09_rango_10pct.png),
[ordenamiento](experimentos/10_ordenamiento.png),
[carga mixta](experimentos/11_carga_mixta.png).

**Construcción y espacio.** Los tres índices se construyen en tiempo
aproximadamente lineal, ~4 ms por registro; el Hash es un 20 % más lento, atribuible a
las divisiones de buckets y duplicaciones del directorio durante la carga. Con 100 000
registros el Hash es el más compacto (2 056 KiB, 40 % del Heap) y el B+
agrupado el más grande (3 172 KiB).

**Igualdad.** El Hash va directo al bucket y su costo casi no cambia con el
tamaño (0,42 → 0,59 ms): es O(1). El B+ desciende desde la raíz y crece
lentamente con la altura del árbol (O(log n)). Con 100 000 registros el Hash
es 2,8 veces más rápido que el B+ agrupado y 4,7 veces más que el no agrupado.
Las claves ausentes son todavía más baratas en el Hash (0,44 ms).

**Rangos.** El Hash no puede responder rangos: dispersa las claves, así que el
motor recorre el Heap entero (~860 ms con 100 000 registros, igual para
cualquier selectividad). El B+ baja una vez a la primera hoja y recorre las
hojas enlazadas, con un costo proporcional a las filas devueltas (~0,19 ms por
fila con 100 000 registros, porque lee cada registro por su RID). Por eso:

- con selectividad 0,1 % el B+ es 30 a 40 veces más rápido;
- con 1 %, unas 4,5 veces más rápido;
- con 10 %, recorrer la tabla es 2,2 veces más rápido que usar el B+.

El punto de cruce está entre 1 % y 10 %. Interpolando linealmente los costos
medidos, ronda el 4–5 % de la tabla con 100 000 registros (estimación, no
medición directa).

**Recuperación ordenada.** Recorrer todas las hojas del B+ y leer cada
registro por su RID (17 s) es más lento que recorrer el Heap y ordenar con
`ExternalSort` (8,9 s): leer 100 000 registros uno por uno cuesta más que un
recorrido secuencial seguido de un ordenamiento externo.

**Agrupado frente a no agrupado.** En lecturas se comportan casi igual: en
esta implementación los dos obtienen cada fila leyendo su registro por RID, y
el agrupado no aprovecha que esas filas estén contiguas para leer páginas
completas. La diferencia aparece al escribir: el Archivo Secuencial puede mover
registros cuando divide una página, así que el B+ agrupado se reconstruye
completo después de cada inserción. Procesa 35, 3 y 1 operación dentro del
presupuesto de 60 s, contra ~230 operaciones por segundo del no agrupado y del
Hash, que solo actualizan una entrada. Con 100 000 registros completó una
operación por repetición; la tasa reportada se calcula sobre esa única
operación.

Tras cada carga mixta, los tres índices pasaron la validación completa de su
estructura con el número exacto de entradas esperado.

## 4. Confirmación desde SQL

Los experimentos anteriores llaman a las estructuras directamente. Para
comprobar que el motor SQL toma el mismo camino, se ejecutaron las mismas
consultas con `EXPLAIN ANALYZE` sobre la ruta completa del servidor
(`api.database.Database`), con 10 000 registros, con índices habilitados y
deshabilitados. Detalle: [experimentos/planes_sql.md](experimentos/planes_sql.md).

| Consulta | B+ no agrupado / B+ agrupado | Hash extensible |
|---|---|---|
| `WHERE id = k` | `IndexScan` (1–3 ms frente a ~190 ms recorriendo) | `IndexScan` (~1 ms) |
| `WHERE id BETWEEN` 0,1 % y 1 % | `IndexScan` (5–54 ms frente a ~210 ms) | `TableScan` (no hay índice ordenado) |
| `WHERE id BETWEEN` 10 % | `IndexScan` (~340–370 ms), aunque `TableScan` tarda ~220 ms | `TableScan` |
| `ORDER BY id` | `ExternalSort` sobre `TableScan` | `ExternalSort` sobre `TableScan` |

El planner elige el camino por reglas, sin estimar costos: si hay un índice
compatible lo usa, con prioridad para la igualdad exacta. Por eso en un rango
del 10 % usa el B+ aunque recorrer sea 1,6 veces más rápido, lo que coincide
con el cruce medido en la sección 3. `ORDER BY` siempre se resuelve con
`ExternalSort`, como pide el enunciado, aunque exista un B+ sobre la columna.

## 5. Ventajas y desventajas

| Estructura | Ventajas (medidas) | Desventajas (medidas) |
|---|---|---|
| Heap File | Inserción más rápida (~0,35 ms por registro, lineal); el menor espacio; reutiliza los huecos de lo borrado | Búsqueda por clave lineal (431 ms con 100 000 registros); sin orden: rangos y `ORDER BY` necesitan recorrido completo y ordenamiento |
| Archivo Secuencial Paginado | Búsqueda por clave casi constante (1,6 ms con 100 000, 260× más rápida que el Heap); datos ordenados para recorridos ordenados | Inserción 18× (ascendente) a 36× (aleatoria) más lenta que el Heap y creciente con el tamaño; 44 % más espacio con llegada aleatoria hasta reorganizar |
| B+ agrupado | Rangos selectivos rápidos (21,7 ms al 0,1 % con 100 000); igualdad O(log n) | Se reconstruye en cada inserción (0,002 ops/s con 100 000); el índice más grande; en esta implementación no lee las filas contiguas en bloque |
| B+ no agrupado | Rangos selectivos rápidos sobre un Heap; mantenimiento barato (~220 ops/s) | Lee cada fila por RID: con rangos amplios (10 %) o recuperación completa pierde contra recorrer la tabla y ordenar |
| Hash extensible | Igualdad más rápida y constante (0,59 ms con 100 000); mantenimiento más rápido (~234 ops/s); el índice más pequeño | No sirve para rangos ni orden (cae a recorrido completo: ~860 ms); construcción un 20 % más lenta |

## 6. Conclusiones: cuándo usar cada estructura

- **Heap File** cuando predominan las inserciones y las consultas recorren la
  tabla completa o usan un índice secundario. Es la organización más barata
  de mantener y de almacenar.
- **Archivo Secuencial Paginado** cuando la tabla se consulta mucho por clave
  o en orden y se modifica poco, o cuando los datos llegan ya ordenados (la
  carga ascendente tarda la mitad y no desperdicia espacio). Conviene
  reorganizarlo después de cargas aleatorias o de muchas eliminaciones.
- **B+ agrupado** para tablas casi estáticas consultadas por rangos de la
  clave de orden. Con inserciones frecuentes es inviable en esta
  implementación, porque cada inserción reconstruye el índice.
- **B+ no agrupado** para rangos selectivos (hasta alrededor del 1–4 % de la
  tabla) sobre una tabla que también recibe escrituras. Para rangos amplios o
  para devolver toda la tabla ordenada es mejor recorrer y usar
  `ExternalSort`.
- **Hash extensible** para búsquedas por igualdad exacta y cargas con muchas
  inserciones y eliminaciones. No debe elegirse si la columna se consulta por
  rangos o se ordena.

## 7. Limitaciones

- **Una sola máquina y caché caliente.** Los archivos se acaban de escribir y
  la caché del sistema operativo los mantiene en memoria; con disco frío las
  estructuras que leen registro por registro (B+ por RID) perderían más.
- **Python.** Los tiempos absolutos reflejan un intérprete; las comparaciones
  entre estructuras y su crecimiento con N son lo que se debe leer.
- **Carga mixta del B+ agrupado.** El presupuesto de 60 s limitó la muestra a
  35, 3 y 1 operación; la tasa es correcta, pero se basa en pocas operaciones.
- **100 000 registros en paralelo.** Los dos experimentos de 100 000 corrieron
  a la vez en núcleos distintos. Comparten memoria y disco, aunque cada uno usó
  un solo núcleo y la máquina tenía 8.
- **Punto de cruce de rangos.** El 4–5 % es una interpolación entre las
  selectividades medidas (1 % y 10 %), no una medición.
- **Planner por reglas.** Sin modelo de costos, el motor no puede evitar el B+
  en rangos amplios; es una decisión de alcance (el plan de la etapa excluye
  un optimizador por costos), no un error de medición.
