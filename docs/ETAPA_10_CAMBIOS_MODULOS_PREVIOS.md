# Etapa 10 — cambios a módulos de etapas anteriores

Registro de cada modificación que la Etapa 10 hizo en código de etapas ya
cerradas: qué cambió, por qué, a qué afecta y con qué evidencia. Cada cambio
fue aprobado por el usuario antes de aplicarse, después de verificar en
`Proyecto_Final (3).docx` que el enunciado lo permite. La versión redactada para
el informe está en `docs/informe/ajustes_modulos_previos.md`.

**Regla común a todos los cambios.** Ninguno modifica un algoritmo exigido por
el enunciado, un formato en disco, una API pública ni un contrato de error.
Los cuatro atacan el mismo problema: el costo estaba dominado por
**revalidaciones repetidas** o por **recorridos lineales evitables**, no por la
técnica que el experimento debe comparar. Sin ellos, las cargas de 100 000
registros tardaban horas y las conclusiones habrían medido artefactos de
implementación.

**Lo que sí cambia para el informe.** Los tiempos absolutos de todas las
estructuras son menores que antes. Las corridas con el código anterior se
conservan en `benchmarks/results/archive/part1_before_10_2d.jsonl` (5
repeticiones de 1 000 y 10 000 registros, commit `0deafe3` con cambios sin
commit, `source_sha256` `c5686b16…`) como evidencia del efecto. Las corridas
oficiales del informe son las posteriores a todos los cambios. No existe una
corrida oficial anterior a 10.2–10.2c porque con ese código no terminaba en un
tiempo razonable: su efecto se documenta con mediciones puntuales.

## Resumen

| Tarea | Etapa / módulo | Archivo | Qué cambió | Efecto en el comportamiento |
|---|---|---|---|---|
| 10.2 | 2 — página | `engine/storage/page.py` | Reutiliza la validación completa de la página mientras sus bytes no cambian | Ninguno: cada estado se valida una vez antes de usarse, incluso si el buffer se altera por fuera |
| 10.2b | 3 — Paged Sequential | `engine/storage/paged_sequential_file.py` | Búsqueda binaria de la página destino en `insert` y `search` | Mismo resultado de inserción y búsqueda; el orden global se valida al abrir y en cada `scan`, ya no en cada inserción |
| 10.2c | 3 — Paged Sequential | `engine/storage/paged_sequential_file.py` | División equilibrada de una página llena; la inserción al final sigue llenando completo | Distinta distribución física de filas en páginas (los RID ya eran inestables por diseño); orden, eliminación lazy, tombstones y reorganización intactos |
| 10.2d | 4 — B+ | `engine/indexes/bplus_io.py`, `bplus_tree.py`, `clustered_bplus.py`, `unclustered_bplus.py` | Reutiliza nodos decodificados mientras su página no cambia; los rangos verifican cada fila contra su entrada de hoja | Ninguno: un RID obsoleto o una clave fuera del rango siguen provocando el mismo error |
| 10.2d (ext.) | 5 — Hash extensible | `engine/indexes/hash_io.py` | Reutiliza buckets y páginas de directorio decodificados mientras su página no cambia | Ninguno |

## 10.2 — Validación de páginas (Etapa 2)

**Antes.** `Page._inspect` deserializaba y validaba la cabecera y **todos** los
slots en cada llamada, y `read`, `insert`, `delete`, `header` y `slots` lo
llamaban siempre. Recorrer los k registros de una página costaba O(k²)
validaciones. El perfil de una inserción secuencial atribuía más del 90 % del
tiempo a `_inspect`, `SlotEntry.deserialize` y `validate_page_layout`.

**Después.** Cada `Page` guarda los bytes exactos y el resultado del último
estado que pasó la validación, y los reutiliza solo si el buffer actual es
idéntico byte a byte. Cualquier cambio, incluso uno hecho directamente sobre el
buffer privado, se vuelve a validar antes de exponer o mutar nada.

**Por qué.** La validación es una función pura de los 4096 bytes; repetirla
sobre el mismo estado no aporta seguridad y hacía impracticables las cargas.

**Afecta a.** Todo lo que lee páginas: Heap, Paged Sequential, índices,
catálogo y operadores. Solo en tiempo de CPU.

| Evidencia | Antes | Después |
|---|---:|---:|
| Inserción en Heap, 5 000 filas | ~3,0 ms/fila | ~0,33 ms/fila |
| Suite estricta completa | 2889 en 276,8 s | 2889 en 138,6 s |

Pruebas: `tests/storage/test_page.py::test_full_validation_runs_once_per_buffer_state`
y `::test_in_place_buffer_changes_are_validated_again_after_caching`; las
pruebas de corrupción existentes siguen pasando.

## 10.2b — Ubicación de la página destino (Etapa 3)

**Antes.** `_find_insertion_target` leía las páginas desde la primera y
decodificaba y comparaba **cada registro** hasta encontrar una clave mayor;
`search(key)` hacía lo mismo. Cada inserción era O(n) y una carga, O(n²):
17 → 63 ms/fila mientras el archivo crecía de 2 000 a 8 000 filas.

**Después.** Una búsqueda binaria sobre "la mayor clave guardada en la página i
o antes" (monótona aunque haya páginas vaciadas por eliminaciones) decodifica
solo la última clave de O(log P) páginas. La página destino es la misma que
antes: la primera con una clave mayor, o la última. El rechazo de duplicados
revisa la página destino y la página no vacía anterior.

**Por qué.** Las páginas ya están ordenadas: la búsqueda binaria es la técnica
natural de un archivo secuencial y no agrega ninguna estructura auxiliar
(sigue sin ser un índice). El recorrido lineal en cada inserción era además una
verificación del orden global, que se conserva al abrir el archivo y en cada
`scan` completo.

**Afecta a.** `PagedSequentialFile.insert` y `search`, y por lo tanto al B+
agrupado, a la creación de tablas secuenciales desde la GUI y a los INSERT
sobre tablas secuenciales.

| Evidencia (20 000 filas, orden ascendente) | Antes | Después |
|---|---:|---:|
| Costo por fila mientras crece el archivo | 17 → 63 ms (creciente) | 9,5 → 9,8 ms (plano) |
| Búsqueda por clave | O(n) | 2,5 ms |

Pruebas: `tests/storage/test_paged_sequential_binary_search.py` (7 pruebas:
comparación con un modelo ordenado bajo inserciones aleatorias, duplicados y
eliminaciones que vacían páginas; cota de páginas leídas).

## 10.2c — División de páginas llenas (Etapa 3)

**Antes.** Al dividir una página llena, `_partition_items` llenaba la primera
página al máximo y dejaba el desborde (normalmente **un solo registro**) en una
página nueva. Con claves aleatorias quedaban ~5 filas por página, y cada
división desplazaba todas las páginas siguientes (el archivo es contiguo).

**Después.** Se mantiene la cantidad mínima de páginas del llenado codicioso,
pero los registros se reparten entre ellas según sus bytes acumulados (mitades
equilibradas en una división en dos). Una inserción al final de la última
página conserva el llenado completo (regla del extremo derecho), así las cargas
ascendentes siguen compactas.

**Por qué.** Es la política estándar de división y evita el crecimiento
super-lineal en cargas aleatorias. El desplazamiento contiguo de páginas sigue
existiendo porque es parte del diseño del archivo, y el informe lo reporta.

**Afecta a.** La distribución física de las filas en páginas tras una división
(los RID del archivo secuencial ya eran inestables por diseño, documentado en
la Etapa 3) y, por lo tanto, el espacio en disco de cargas aleatorias.

| Evidencia (20 000 filas, orden aleatorio) | Antes | Después |
|---|---:|---:|
| Costo por fila en bloques de 5 000 | 8,8 / 16,2 / 31,6 / 51,7 ms | 11,5 / 12,2 / 12,2 / 13,4 ms |
| Páginas de datos | 4 149 | 333 |

Pruebas: `tests/storage/test_paged_sequential_split.py` (3 pruebas).

## 10.2d — Revalidación en el B+ (Etapa 4) y en el Hash (Etapa 5)

**Antes.**

1. Cada lectura de un nodo B+ decodificaba y validaba **todas** sus claves y
   RID (≈3 ms por nodo; 144 240 validaciones para leer 204 nodos en un rango de
   100 filas).
2. `range_records` (B+ agrupado y no agrupado) hacía una búsqueda exacta
   completa `tree.search(key)` **por cada fila** devuelta, para comprobar que
   el RID no estuviera obsoleto: un rango de k filas costaba k descensos.
3. El Hash extensible decodificaba y validaba cada bucket y página de
   directorio en cada búsqueda (mismo patrón que el punto 1).

**Después.**

1. `BPlusNodePageIO` reutiliza el nodo decodificado mientras los bytes de su
   página no cambian (hasta 1 024 nodos por archivo abierto). La página se
   sigue leyendo y validando en cada acceso: los contadores de E/S y la
   detección de corrupción no cambian.
2. `BPlusTree.range_entries` entrega pares (clave de hoja, RID) y
   `range_search` es un envoltorio sobre ese método. `range_records` comprueba
   que el registro leído conserve la clave de la entrada de hoja de la que
   salió. Es la misma garantía que antes —la asociación (clave, RID) existe en
   el árbol y coincide con el registro— sin un segundo descenso.
3. `HashBucketPageIO` y `HashDirectoryPageIO` aplican la misma reutilización
   que el punto 1. Se extendió al Hash, que el usuario no había mencionado
   explícitamente, para que la comparación B+ contra Hash no quedara sesgada:
   corregir solo el B+ habría favorecido artificialmente al B+.

**Por qué.** Con el código anterior, un rango por B+ y la recuperación ordenada
completa perdían contra un recorrido del Heap entero por la revalidación por
fila, no por el algoritmo del árbol. El informe habría concluido lo contrario
de lo que muestra un B+ correctamente implementado.

**Afecta a.** Toda búsqueda, rango, inserción y eliminación en índices B+ y
Hash, incluidos el planner (`IndexScan`, `IndexNestedLoopJoin`) y el
mantenimiento de índices en INSERT/DELETE. Solo en tiempo de CPU; los mensajes
de error de RID obsoleto se conservan.

Corridas oficiales con 10 000 filas, mediana de 5 repeticiones. "Antes" es
`benchmarks/results/archive/part1_before_10_2d.jsonl` (ya con 10.2, 10.2b y
10.2c); "después" es la corrida `official-1k-10k` en
`benchmarks/results/part1_results.jsonl`. Misma máquina, mismos datos y misma
semilla; solo cambia 10.2d.

| Operación (10 000 filas) | Antes | Después | Efecto |
|---|---:|---:|---|
| Igualdad, B+ no agrupado | 2,31 ms | 0,99 ms | 2,3× más rápido |
| Igualdad, B+ agrupado | 2,03 ms | 0,93 ms | 2,2× |
| Igualdad, Hash | 2,29 ms | 0,51 ms | 4,5× |
| Rango 1 %, B+ no agrupado | 231 ms | 18,7 ms | 12× |
| Rango 10 %, B+ no agrupado | 2 268 ms | 178 ms | 13× |
| Rango 10 %, Hash (recorrido del Heap + filtro) | 88 ms | 86 ms | sin cambio (no usa el índice) |
| Recuperación ordenada, B+ no agrupado | 22,7 s | 1,67 s | 14× |
| Recuperación ordenada, B+ agrupado | 20,1 s | 1,70 s | 12× |
| Recuperación ordenada, Hash (`ExternalSort`) | 0,76 s | 0,75 s | sin cambio |
| Carga mixta, B+ no agrupado | 162 ops/s | 237 ops/s | 1,5× |
| Carga mixta, Hash | 171 ops/s | 242 ops/s | 1,4× |
| Carga mixta, B+ agrupado | 0,038 ops/s | 0,041 ops/s | sin cambio (domina la reconstrucción) |
| Construcción, B+ no agrupado / Hash | 36,2 s / 43,5 s | 33,1 s / 42,4 s | casi sin cambio |

Lo que **no** cambió es igual de informativo: las operaciones que no pasan por
el índice (recorrido del Heap, `ExternalSort`) quedan iguales, lo que confirma
que la diferencia viene del cambio y no de la máquina. La conclusión del
informe sí cambia: antes un rango del 1 % por B+ perdía contra el recorrido
completo (231 ms frente a 88 ms); ahora gana (19 ms frente a 85 ms). El rango
del 10 % y la recuperación ordenada completa siguen perdiendo contra recorrer y
ordenar, ahora por el costo real de leer un registro por RID.

Pruebas: `tests/indexes/test_bplus_validation_reuse.py` (RID obsoleto en un
rango sigue rechazado; `range_entries`; reutilización e invalidación de nodos)
y `tests/indexes/test_hash_validation_reuse.py`.

## Verificación conjunta

| Punto | Suite estricta completa |
|---|---|
| Antes de la Etapa 10 (cierre de la Etapa 9) | 2889 aprobadas en 276,8 s |
| Tras 10.2 | 2889 aprobadas en 138,6 s |
| Tras 10.2b | 2898 aprobadas |
| Tras 10.2c | 2901 aprobadas |
| Tras 10.2d (con benchmarks y Hash) | 2912 aprobadas en 186,3 s |

## Comportamientos que el informe debe explicar (no se cambiaron)

- El B+ **agrupado** reconstruye el índice completo después de cada inserción,
  porque el archivo secuencial puede mover RID. Por eso procesa muy pocas
  inserciones/eliminaciones por segundo (0,041 ops/s con 10 000 filas en la
  corrida oficial).
- Una división de página en el Paged Sequential desplaza las páginas
  siguientes (archivo contiguo, sin área de overflow).
- La reapertura de un índice Hash verifica su cobertura fila por fila
  (≈2 ms por fila), lo que alarga el arranque con tablas grandes.
