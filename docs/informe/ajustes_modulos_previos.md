# Ajustes de implementación en módulos de etapas anteriores

Durante la etapa de experimentación (Etapa 10) se modificaron cuatro puntos del
código de etapas ya cerradas: la página de disco, el Paged Sequential File, el
índice B+ y el Hash extensible. Esta sección explica qué se cambió, por qué era
necesario, por qué el cambio es legítimo dentro del enunciado y cómo afecta a
los resultados.

## 1. Motivo

El enunciado pide comparar las técnicas con 1 000, 10 000 y 100 000 registros.
Antes de escribir los experimentos se midió el código tal como había quedado al
cierre de cada etapa, y aparecieron dos problemas:

1. **Inviabilidad.** Insertar 100 000 registros en el Paged Sequential File
   tomaba entre 1,5 y 3,5 horas por carga, y el costo por registro crecía con
   el archivo. Con repeticiones y tres tamaños, el experimento no cabía en un
   día de cómputo.
2. **Mediciones sesgadas.** Los perfiles mostraban que la mayor parte del
   tiempo no se iba en la técnica que se quería comparar, sino en
   verificaciones repetidas sobre datos que no habían cambiado. Con ese código,
   los experimentos habrían medido detalles de implementación y no las
   propiedades de cada estructura. Por ejemplo, un rango por B+ habría perdido
   contra un recorrido completo de la tabla.

## 2. Criterios aplicados

Cada cambio se evaluó con los mismos criterios antes de aplicarlo:

- **No reemplaza ni simplifica ninguna técnica exigida.** El Heap reutiliza el
  espacio libre; el Paged Sequential inserta manteniendo el orden, elimina de
  forma perezosa (lazy) y se reorganiza al superar el 30 % de espacio
  desperdiciado; el B+ agrupado, el B+ no agrupado y el Hash extensible siguen
  siendo implementaciones propias. El enunciado exige estas técnicas y no
  prohíbe optimizaciones internas.
- **Sin librerías externas.** Todo el código nuevo es propio, con la biblioteca
  estándar de Python.
- **Mismo comportamiento observable.** Iguales resultados de consultas, formato
  de los archivos en disco, interfaces y mensajes de error. La única diferencia
  visible es la distribución de filas en páginas del Paged Sequential (cambio 3).
- **Verificación.** Cada cambio se acompañó de pruebas nuevas, y la suite
  completa (todas las etapas, con las advertencias tratadas como errores) se
  ejecutó después de cada uno.
- **Trazabilidad.** Las mediciones con el código anterior se conservan, y el
  efecto de cada cambio se reporta con números.

## 3. Resumen

| # | Módulo (etapa) | Problema | Cambio | ¿Cambia el algoritmo? |
|---|---|---|---|---|
| 1 | Página de disco (Etapa 2) | Toda la página se volvía a validar en cada lectura; recorrer k registros costaba k² validaciones | La validación se reutiliza mientras los bytes de la página no cambian | No |
| 2 | Paged Sequential (Etapa 3) | Insertar y buscar recorrían el archivo desde el inicio: O(n) por operación, O(n²) por carga | Búsqueda binaria de la página sobre las páginas ordenadas: O(log P) | Sí: método de localización |
| 3 | Paged Sequential (Etapa 3) | Al dividir una página llena, el desborde (un registro) quedaba solo en una página nueva | División en dos mitades equilibradas; la inserción al final sigue llenando la página | Sí: política de división |
| 4 | Índices B+ y Hash (Etapas 4 y 5) | Cada nodo o bucket se decodificaba y validaba de nuevo en cada acceso, y cada fila de un rango B+ repetía un descenso completo del árbol | Reutilización de nodos y buckets no modificados; cada fila del rango se verifica contra su hoja | No |

## 4. Detalle y justificación

### Cambio 1 — Validación de páginas (Etapa 2)

**Problema.** Cada página de 4 096 bytes se validaba por completo (cabecera y
todos los slots) en cada operación: leer un registro, insertar, eliminar o
consultar la cabecera. Recorrer los k registros de una página costaba del
orden de k² validaciones. En el perfil de una inserción secuencial, más del
90 % del tiempo se iba en esa validación.

**Solución.** Cada página recuerda el contenido exacto que ya pasó la
validación y el resultado obtenido. Si los bytes actuales son idénticos, se
reutiliza el resultado; si cambió cualquier byte, aunque sea por una escritura
directa sobre el buffer, se valida de nuevo antes de usar la página.

**Justificación.** La validación depende solo de los bytes de la página:
repetirla sobre el mismo contenido da siempre el mismo resultado y no agrega
seguridad. La detección de páginas corruptas se mantiene intacta y sus pruebas
siguen pasando.

**Efecto.** Afecta a todo lo que lee páginas (archivos, índices, catálogo y
operadores), solo en tiempo de CPU.

| Medición | Antes | Después |
|---|---:|---:|
| Inserción en Heap File (5 000 registros) | ~3,0 ms/registro | ~0,33 ms/registro |
| Construcción de B+ no agrupado / Hash (5 000 registros) | ~4,3 / ~4,6 ms/registro | ~3,2 / ~3,9 ms/registro |
| Suite completa de pruebas | 276,8 s | 138,6 s |

### Cambio 2 — Localización de la página en el Paged Sequential (Etapa 3)

**Problema.** Para insertar un registro, el archivo leía las páginas desde la
primera y comparaba cada registro hasta encontrar una clave mayor. La búsqueda
por clave hacía lo mismo. Cada operación era O(n) y una carga completa,
O(n²): el costo por registro pasaba de 17 a 63 ms mientras el archivo crecía de
2 000 a 8 000 registros. Extrapolado, una carga de 100 000 registros tomaba
entre 5 y 11 horas.

**Solución.** Como las páginas están ordenadas por la clave, la página destino
se ubica con búsqueda binaria sobre la última clave de cada página. Solo se
decodifica un registro (el último) de O(log P) páginas, donde P es la cantidad
de páginas. Las páginas vaciadas por eliminaciones lazy se saltan sin romper la
búsqueda. La página elegida es exactamente la misma que con el recorrido
lineal, y los duplicados se siguen rechazando.

**Justificación.** La razón de ser de un archivo secuencial es mantener los
datos ordenados para poder ubicarlos sin recorrerlos; la búsqueda binaria
sobre bloques ordenados es el método de acceso clásico de esta organización.
No es un índice: no agrega ninguna estructura auxiliar y trabaja directamente
sobre las páginas de datos. La inserción sigue preservando el orden, como pide
el enunciado.

**Efecto.** Afecta a la inserción y la búsqueda en el Paged Sequential y, por
lo tanto, al B+ agrupado, a las tablas secuenciales creadas desde la interfaz
y a los INSERT por SQL. Antes, cada inserción verificaba de paso el orden de
todo el archivo; ahora esa verificación se hace al abrir el archivo y en cada
recorrido completo.

| Medición (20 000 registros, orden ascendente) | Antes | Después |
|---|---:|---:|
| Costo por registro mientras crece el archivo | 17 → 63 ms (creciente) | 9,5 → 9,8 ms (constante) |
| Búsqueda por clave primaria | O(n) | 2,5 ms |

En las corridas oficiales, la búsqueda por clave en el Paged Sequential tarda
0,9 ms con 1 000 registros y 1,2 ms con 10 000. El crecimiento es casi plano,
como corresponde a O(log P).

### Cambio 3 — División de páginas llenas en el Paged Sequential (Etapa 3)

**Problema.** Cuando una inserción no cabía en su página, la primera página
resultante se llenaba al máximo y el desborde, normalmente un solo registro,
quedaba solo en una página nueva. Con claves en orden aleatorio, las páginas
quedaban con ~5 registros en promedio, contra 86 en una carga ordenada. Como el
archivo es contiguo, cada división desplaza todas las páginas siguientes, y ese
costo crecía con el número de páginas.

**Solución.** Se mantiene la cantidad mínima de páginas, pero los registros se
reparten entre ellas según sus bytes: una división en dos deja dos mitades
equilibradas. Cuando la inserción ocurre al final de la última página, se
conserva el llenado completo, para que las cargas en orden ascendente sigan
generando páginas llenas.

**Justificación.** Dividir una página llena en dos mitades es la política
estándar de los archivos y árboles paginados (la misma que usa un B+). Llenar
por completo las páginas al insertar al final es la regla habitual para claves
crecientes. El orden, la eliminación lazy, los registros marcados como
borrados, la reorganización al 30 % y el formato del archivo no cambian.

**Efecto.** Cambia la distribución física de los registros en páginas después
de una división. Los RID del Paged Sequential ya podían cambiar por diseño
desde la Etapa 3, porque el archivo se mantiene ordenado. Con claves
aleatorias, las páginas quedan entre medio llenas y llenas; por eso el archivo
ocupa más que un Heap, y la reorganización recupera ese espacio. Los
experimentos lo reportan.

| Medición (20 000 registros, orden aleatorio) | Antes | Después |
|---|---:|---:|
| Costo por registro en bloques de 5 000 | 8,8 / 16,2 / 31,6 / 51,7 ms | 11,5 / 12,2 / 12,2 / 13,4 ms |
| Páginas de datos | 4 149 | 333 |

### Cambio 4 — Revalidación en los índices B+ (Etapa 4) y Hash (Etapa 5)

**Problema.** Se detectó en las primeras corridas oficiales con 1 000
registros:

1. Cada lectura de un nodo B+ decodificaba y validaba todas sus claves y RID,
   incluso si el nodo no había cambiado. Leer los 204 nodos de un rango de
   100 filas implicaba 144 240 validaciones de claves.
2. El recorrido de un rango B+ (agrupado y no agrupado) repetía una búsqueda
   exacta completa en el árbol **por cada fila** devuelta, para comprobar que
   el RID no estuviera obsoleto: un rango de k filas costaba k descensos.
3. El Hash extensible decodificaba y validaba cada bucket y cada página del
   directorio en cada búsqueda, igual que el punto 1.

**Solución.**

1. Los nodos B+ ya decodificados se reutilizan mientras los bytes de su página
   no cambian (hasta 1 024 nodos por índice abierto). La página se sigue
   leyendo y validando en cada acceso, así que los contadores de lecturas y la
   detección de corrupción se mantienen.
2. El recorrido del rango entrega cada RID junto con la clave de la hoja de la
   que salió, y se comprueba que el registro leído tenga esa misma clave. Es la
   misma garantía de antes, sin repetir el descenso.
3. El Hash recibe la misma reutilización que el punto 1.

**Justificación.** El algoritmo del B+ es un descenso desde la raíz y un
recorrido por las hojas enlazadas; el descenso repetido por fila era una
verificación defensiva, no parte del algoritmo. La verificación sigue
existiendo y un RID obsoleto sigue produciendo el mismo error. El cambio se
aplicó también al Hash para no sesgar la comparación: corregir solo el B+ lo
habría favorecido artificialmente frente al Hash.

**Efecto.** Afecta a toda búsqueda, rango, inserción y eliminación en los
índices B+ y Hash, incluidos los planes del planner que usan índices y el
mantenimiento de índices en INSERT y DELETE, solo en tiempo de CPU.

Este cambio sí tiene una comparación oficial: los mismos experimentos, con los
mismos datos y en la misma máquina, antes y después. Los valores son la mediana
de 5 repeticiones con 10 000 registros:

| Operación | Antes | Después | Mejora |
|---|---:|---:|---:|
| Igualdad, B+ no agrupado | 2,31 ms | 0,99 ms | 2,3× |
| Igualdad, B+ agrupado | 2,03 ms | 0,93 ms | 2,2× |
| Igualdad, Hash extensible | 2,29 ms | 0,51 ms | 4,5× |
| Rango 1 %, B+ no agrupado | 231 ms | 18,7 ms | 12× |
| Rango 10 %, B+ no agrupado | 2 268 ms | 178 ms | 13× |
| Recuperación ordenada, B+ no agrupado | 22,7 s | 1,67 s | 14× |
| Recuperación ordenada, B+ agrupado | 20,1 s | 1,70 s | 12× |
| Inserciones y eliminaciones, B+ no agrupado | 162 ops/s | 237 ops/s | 1,5× |
| Inserciones y eliminaciones, Hash extensible | 171 ops/s | 242 ops/s | 1,4× |
| *Control:* rango por recorrido del Heap (sin índice) | 88 ms | 86 ms | sin cambio |
| *Control:* ordenamiento con `ExternalSort` (sin índice) | 0,76 s | 0,75 s | sin cambio |

Las filas de control no usan índices y no cambiaron. Eso confirma que la
diferencia se debe al cambio y no a variaciones de la máquina.

## 5. Efecto en las conclusiones

Los tiempos absolutos de todas las estructuras bajaron, pero lo importante es
que las comparaciones ahora miden las técnicas:

- **Rangos.** Antes del cambio 4, un rango del 1 % por B+ perdía contra
  recorrer toda la tabla (231 ms frente a 88 ms con 10 000 registros); ahora
  gana (19 ms frente a 85 ms). Un rango del 10 % sigue perdiendo (178 ms frente
  a 86 ms), por el costo real de leer un registro por cada RID. Ese punto de
  cruce es una conclusión válida del experimento.
- **Recuperación ordenada.** El B+ sigue siendo más lento (1,7 s) que recorrer
  el Heap y ordenar con `ExternalSort` (0,75 s), por la misma razón. Antes la
  diferencia era de 30 veces y estaba dominada por la revalidación; ahora es
  de 2 veces y refleja el costo de acceso.
- **Paged Sequential.** Sin los cambios 2 y 3, el experimento con 100 000
  registros no habría podido ejecutarse con repeticiones. Ahora la carga crece
  casi linealmente: con orden aleatorio, 8,1 ms por registro con 1 000
  registros y 9,4 ms con 10 000.

No existe una corrida oficial completa con el código anterior a los cambios 1
a 3, precisamente porque no terminaba en un tiempo razonable; su efecto se
documenta con las mediciones puntuales de las tablas anteriores.

## 6. Comportamientos que no se cambiaron

Estas características se mantuvieron porque forman parte del diseño de cada
estructura, y se reportan en los resultados en lugar de corregirse:

- **B+ agrupado bajo inserciones frecuentes.** El índice se reconstruye
  completo después de cada inserción, porque el Paged Sequential puede mover
  los registros de lugar. Por eso procesa muy pocas operaciones por segundo
  (0,041 ops/s con 10 000 registros, frente a ~240 del B+ no agrupado y del
  Hash). Esta es la desventaja típica de un índice agrupado sobre un archivo
  ordenado.
- **Desplazamiento de páginas en el Paged Sequential.** El archivo es contiguo
  y no tiene área de desborde, así que una división desplaza las páginas
  siguientes. El costo crece con el archivo y explica el leve aumento del costo
  por registro.
- **Reapertura del Hash extensible.** Al abrir un índice Hash se verifica que
  cubra cada registro de la tabla (~2 ms por registro), lo que alarga el
  arranque con tablas grandes.

## 7. Verificación

| Momento | Suite completa de pruebas |
|---|---|
| Cierre de la etapa anterior (punto de partida) | 2 889 aprobadas |
| Después del cambio 1 | 2 889 aprobadas |
| Después del cambio 2 | 2 898 aprobadas |
| Después del cambio 3 | 2 901 aprobadas |
| Después del cambio 4 y del código de experimentos | 2 912 aprobadas |

Las pruebas nuevas cubren los puntos sensibles de cada cambio:

- **Cambio 1:** una página modificada directamente en memoria se vuelve a
  validar.
- **Cambio 2:** el archivo se compara contra un modelo ordenado bajo
  inserciones aleatorias, duplicados y eliminaciones que vacían páginas
  enteras, y se acota la cantidad de páginas leídas.
- **Cambio 3:** las divisiones quedan equilibradas y las cargas ascendentes
  siguen llenando las páginas.
- **Cambio 4:** un RID obsoleto dentro de un rango sigue siendo rechazado, y un
  nodo modificado se decodifica de nuevo.

## Anexo — Ubicación en el código

| Cambio | Archivos | Pruebas |
|---|---|---|
| 1 | `engine/storage/page.py` | `tests/storage/test_page.py` |
| 2 | `engine/storage/paged_sequential_file.py` | `tests/storage/test_paged_sequential_binary_search.py` |
| 3 | `engine/storage/paged_sequential_file.py` | `tests/storage/test_paged_sequential_split.py` |
| 4 | `engine/indexes/bplus_io.py`, `bplus_tree.py`, `clustered_bplus.py`, `unclustered_bplus.py`, `hash_io.py` | `tests/indexes/test_bplus_validation_reuse.py`, `tests/indexes/test_hash_validation_reuse.py` |

Mediciones anteriores al cambio 4: `benchmarks/results/archive/part1_before_10_2d.jsonl`.
Mediciones oficiales: `benchmarks/results/part1_results.jsonl`. Registro
interno detallado: `docs/ETAPA_10_CAMBIOS_MODULOS_PREVIOS.md`.
