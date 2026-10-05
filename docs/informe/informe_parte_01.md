# Informe — Parte 1: Base de datos relacional

Minigestor de Base de Datos Multimodal · Base de Datos 2 (2026-2)

Este informe describe la Parte 1 del proyecto: un motor relacional construido
desde cero, con almacenamiento en páginas, índices propios, algoritmos
externos, un parser SQL, transacciones con control de concurrencia, una API
HTTP y una interfaz gráfica. Ninguna de estas piezas delega en un DBMS
existente ni en implementaciones de terceros de las técnicas pedidas.

Documentos complementarios:

- comparación experimental completa: [../EXPERIMENTOS.md](../EXPERIMENTOS.md);
- ajustes hechos en la etapa de experimentos a módulos anteriores:
  [ajustes_modulos_previos.md](ajustes_modulos_previos.md);
- instalación y ejecución: [../../README.md](../../README.md),
  [../demo.md](../demo.md) y [../despliegue.md](../despliegue.md);
- gramática SQL aceptada: [../sql-grammar.md](../sql-grammar.md);
- contrato de transacciones: [../transactions.md](../transactions.md).

## 1. Arquitectura

El sistema está organizado en capas. Cada capa usa solo la de abajo, y las
pruebas de arquitectura del repositorio impiden que el motor importe la API,
el frontend o librerías de base de datos.

```text
Frontend (React + TypeScript)        4 paneles: Archivos, Consulta, Resultados, Plan
        │  HTTP / JSON
API (FastAPI)                        sesiones por token, límites, serialización
        │
SqlSession / SessionCoordinator      transacciones, locks S/X, undo
        │
SqlEngine                            lexer y parser manuales → AST → binder
        │                            → planner por reglas → plan físico
Operadores físicos                   TableScan, IndexScan, Filter, Projection,
        │                            ExternalSort, ExternalHashGroup,
        │                            GraceHashJoin, NestedLoopJoin, IndexNestedLoopJoin
Índices          Almacenamiento      B+ (agrupado / no agrupado), Hash extensible
        │        │                   Heap File, Archivo Secuencial Paginado
PageManager                          dueño de la E/S paginada relacional
        │
Páginas de 4096 bytes en archivos
```

| Paquete | Responsabilidad |
|---|---|
| `engine/catalog` | Tipos (`INTEGER`, `FLOAT`, `BOOLEAN`, `VARCHAR`), esquemas, registros, metadatos de tablas e índices |
| `engine/storage` | Páginas con slots, codificación de registros, `PageManager`, Heap File y Archivo Secuencial Paginado |
| `engine/indexes` | Núcleo B+ compartido, adaptadores agrupado y no agrupado, Hash extensible |
| `engine/operators` | Operadores físicos, algoritmos externos, archivos temporales y presupuesto de memoria |
| `engine/query` | Lexer, parser, AST, binder, planner y ejecución SQL |
| `engine/maintenance` | Mantenimiento de índices en INSERT y DELETE |
| `engine/transactions` | Sesiones, transacciones, gestor de locks, undo |
| `engine/database` | Manifiesto persistente y propietario de CREATE SQL |
| `engine/spatial` | Núcleo espacial, R-Tree y su mantenimiento posterior a Parte 1 |
| `api/` | Servicio HTTP sobre el motor |
| `frontend/` | Interfaz gráfica |
| `benchmarks/` | Experimentos, separados del motor |

**Recorrido de una consulta.** El navegador envía el SQL a `POST /api/query`
con el token de su sesión. La API lo entrega a la `SqlSession` de ese cliente,
que lo analiza, toma los locks necesarios y ejecuta el plan. El parser produce
un árbol sintáctico; el binder resuelve tablas, columnas y tipos contra el
catálogo; el planner elige el camino de acceso y arma el árbol de operadores;
los operadores leen filas de los archivos e índices a través de páginas. La
respuesta incluye las filas, el plan que realmente se ejecutó y sus métricas
(páginas leídas y escritas, memoria, volcado a disco), que la interfaz muestra
en el panel de Plan.

**Decisiones de tecnología.** Python 3.11 para el motor, sin dependencias de
ejecución; parser escrito a mano (lexer y descenso recursivo, decisión del
equipo); FastAPI solo para el transporte HTTP; React, TypeScript y Vite para la
interfaz; pytest para las pruebas; matplotlib solo para los gráficos de los
experimentos.

## 2. Dominio de datos

El dominio es una universidad: estudiantes, cursos e inscripciones.

| Tabla de la demo | Columnas | Organización | Índices | Filas |
|---|---|---|---|---:|
| `students` | id, name, career, age | Heap | Hash único en `id`; B+ en `age` | 4 |
| `enrollments` | student_id, course | Heap | — | 4 |
| `courses` | code, title, credits | Secuencial por `code` | B+ agrupado único en `code` | 16 |
| `students_big` | id, name, career, age | Heap | B+ en `age` | 1 000 |
| `enrollments_big` | id, student_id, course_code, grade | Heap | — | 3 000 |

Las tablas pequeñas tienen respuestas conocidas a mano y sirven para comprobar
la corrección. Las grandes se generan con semillas fijas y obligan a los
operadores externos a usar disco con el presupuesto de memoria de la demo
(192 KiB). Desde la interfaz también se pueden crear tablas nuevas, vacías o
importadas desde un CSV, eligiendo su organización y sus índices.

Los experimentos usan una tabla de estudiantes con `id`, `name`, `career`,
`age` y `score`, generada con semilla fija para 1 000, 10 000 y 100 000 filas,
con `id` en orden aleatorio.

Cada registro tiene un identificador físico `RID(page_id, slot_id)`, que los
índices usan para apuntar a la fila.

## 3. Algoritmos

### 3.1 Páginas y registros

Todo se guarda en páginas de 4096 bytes con el formato de *slotted page*: una
cabecera de 12 bytes, un directorio de slots de 5 bytes cada uno (posición,
longitud y estado) que crece desde el inicio, y los registros que crecen desde
el final. Eliminar un registro marca su slot como libre y deja un hueco;
compactar reacomoda los registros sin cambiar sus slots, así los RID siguen
siendo válidos. Los registros se codifican en binario: enteros de 64 bits,
flotantes IEEE-754, booleanos de un byte y texto UTF-8 con su longitud.
`PageManager` lee y escribe archivos paginados; cada uno empieza con una
cabecera que identifica el formato y el tamaño de página. Manifiestos, undo y
snapshots espaciales usan archivos auxiliares con sus propios propietarios;
sus bytes no están incluidos en los contadores de páginas del motor.

### 3.2 Heap File

Los registros se guardan en orden de llegada. Para reutilizar espacio, el
archivo mantiene en memoria un directorio "página → espacio que se puede
insertar", reconstruido al abrir junto con la disponibilidad de slots borrados.
Una inserción reutiliza una página con un slot borrado que tenga lugar; en
ausencia de ese hueco usa la última página o añade una nueva. Esa corrección
posterior a la auditoría conserva llegada durante la carga inicial, incluso
con registros de distinto tamaño, y conserva RIDs/formato existentes.
Eliminar marca el slot como libre y actualiza ese
directorio, así el espacio queda disponible para la siguiente inserción.
Buscar sin índice exige recorrer el archivo página por página.

### 3.3 Archivo Secuencial Paginado

Mantiene los registros ordenados físicamente por una clave.

- **Inserción manteniendo el orden.** La página destino se ubica con búsqueda
  binaria sobre la última clave de cada página. El registro se inserta en su
  posición dentro de la página. Si no cabe, la página se divide en dos mitades
  equilibradas por bytes y las páginas siguientes se desplazan una posición
  (el archivo es contiguo y no usa área de desborde). Si la inserción es al
  final del archivo, la página se llena por completo, así las cargas ordenadas
  generan páginas llenas.
- **Búsqueda por clave.** Búsqueda binaria de la primera página que puede
  contener la clave y lectura hacia adelante hasta encontrar una clave mayor.
- **Eliminación lazy.** Marca el slot como libre (tombstone) sin mover nada.
- **Reorganización.** El espacio desperdiciado se mide como
  `(huecos + slots libres) / (páginas × 4096)`. Cuando supera el umbral
  configurable (por defecto 30 %), `should_reorganize()` lo indica; la
  reorganización reescribe el archivo compacto en un archivo nuevo, lo valida
  y reemplaza el original.

Como las divisiones y la reorganización mueven registros, los RID del archivo
secuencial pueden cambiar; los índices sobre él se reconstruyen cuando eso
ocurre.

### 3.4 Índice B+

Un único núcleo B+ persistente sirve para los dos tipos de índice. Cada nodo
ocupa una página; las hojas guardan pares `(clave, RID)` y están enlazadas
hacia la derecha para recorrer rangos. La capacidad de cada nodo se calcula a
partir del tamaño máximo de la clave según su tipo.

- **Búsqueda.** Un descenso desde la raíz hasta la hoja y, si la clave está
  repetida, el recorrido de las hojas siguientes.
- **Rango.** Un descenso hasta el límite inferior y luego el recorrido de las
  hojas enlazadas hasta el límite superior.
- **Inserción.** Una hoja llena se divide por la mitad y copia su primera
  clave derecha al padre; un nodo interno lleno se divide promoviendo su clave
  central; si se divide la raíz, el árbol crece un nivel.
- **Eliminación.** Si un nodo queda por debajo de la mitad, pide una entrada a
  un hermano (primero el izquierdo) o se fusiona con él; si la raíz queda con
  un solo hijo, el árbol baja un nivel. Las páginas liberadas se reutilizan.
- **No agrupado.** El árbol indexa un Heap File: el orden de las filas es
  independiente del índice, y cada resultado se obtiene leyendo su registro por
  RID.
- **Agrupado.** El árbol indexa un Archivo Secuencial ordenado por la misma
  clave, así el orden físico de las filas coincide con el del índice. Como el
  archivo secuencial puede mover registros al insertar, el índice se
  reconstruye después de cada inserción.

### 3.5 Hash extensible

- La clave se convierte en un hash FNV-1a de 64 bits, y se usan sus bits menos
  significativos.
- El **directorio** tiene `2^profundidad_global` entradas, cada una apuntando a
  un **bucket** (una página). Varios índices del directorio pueden apuntar al
  mismo bucket; cada bucket guarda su **profundidad local**.
- **Búsqueda.** Se calcula `hash & (2^global − 1)`, se lee esa entrada del
  directorio y exactamente un bucket.
- **Inserción con bucket lleno.** Si la profundidad local es menor que la
  global, el bucket se divide en dos según un bit más del hash y se redirigen
  las entradas del directorio que le correspondían. Si es igual, primero se
  **duplica el directorio** (profundidad global + 1) y luego se divide. La
  profundidad global máxima es 20.
- **Eliminación.** Quita el par exacto; los buckets vacíos se conservan (la
  fusión de buckets y la reducción del directorio son opcionales y no se
  implementaron).
- El hash solo sirve para igualdad: no conserva el orden de las claves.

### 3.6 Algoritmos externos

Todos los operadores trabajan con un presupuesto de memoria contabilizado.
Cuando los datos no caben, escriben archivos temporales en páginas y los
borran al terminar.

- **ORDER BY — `ExternalSort` (k-way merge).** Lee filas mientras caben en el
  presupuesto, ordena ese bloque en memoria y lo escribe como una *run*.
  Después mezcla hasta `k` runs a la vez con un heap (k limitado por la memoria
  y por los archivos abiertos, por defecto hasta 8), en varias pasadas si hace
  falta, y la última mezcla se entrega en streaming.
- **GROUP BY — `ExternalHashGroup` (hashing externo).** Particiona las filas
  por la clave de agrupación (8 particiones por defecto) y agrega cada
  partición en memoria. Una partición que no cabe se vuelve a particionar con
  otra semilla, hasta 4 niveles; si aun así no cabe, se ordena y se agrupan las
  claves consecutivas. Funciones: `COUNT`, `SUM`, `MIN`, `MAX`, `AVG`.
- **JOIN — `GraceHashJoin` (hashing externo).** Particiona las dos tablas con la
  misma función; en cada par de particiones construye una tabla hash con la
  más pequeña y recorre la otra. Un par demasiado grande se reparticiona; si no
  se puede separar, usa un nested loop por bloques.
- **Uso estratégico de índices.** `IndexNestedLoopJoin` busca cada fila de la
  tabla externa en un índice de igualdad de la interna, cuando existe.
  `NestedLoopJoin` queda como referencia de corrección.

### 3.7 SQL

- **Lexer y parser escritos a mano**, por descenso recursivo. Reportan errores
  con línea y columna. Sentencias: `SELECT` (con `WHERE`, `JOIN`, `GROUP BY`,
  `ORDER BY`), `INSERT`, `DELETE`, `CREATE TABLE` limitado, `EXPLAIN`,
  `EXPLAIN ANALYZE`, y `BEGIN TRANSACTION` / `END TRANSACTION` / `ROLLBACK`.
- **Binder.** Valida tablas, columnas y tipos contra el catálogo antes de
  ejecutar nada.
- **Planner por reglas.** Si hay un índice de igualdad compatible lo usa; si
  no, un B+ para rangos; si no, un recorrido completo. `ORDER BY` siempre usa
  `ExternalSort`, `GROUP BY` usa `ExternalHashGroup` y los joins usan
  `GraceHashJoin`, o `IndexNestedLoopJoin` cuando hay un índice adecuado. El
  planner no estima costos.
- **Plan real.** El plan que se muestra se construye a partir de los
  operadores que se ejecutaron, con sus contadores reales.
- **Escrituras.** INSERT y DELETE validan antes de escribir y mantienen todos
  los índices de la tabla.

### 3.8 Transacciones y concurrencia

- Cada cliente tiene su propia sesión. `BEGIN TRANSACTION` abre un grupo,
  `END TRANSACTION` lo confirma y `ROLLBACK` lo descarta; una sentencia suelta
  es una transacción implícita.
- **Locks por tabla**, compartidos (S) para leer y exclusivos (X) para
  escribir, retenidos hasta el final de la transacción (2PL riguroso). Las
  esperas son en orden de llegada, con mejora de S a X, tiempo límite y
  cancelación.
- **Deadlocks.** Un grafo de espera detecta los ciclos; la transacción que pide
  el lock es la víctima y se aborta.
- **Rollback.** Antes de la primera escritura en una tabla se guarda una
  imagen de sus archivos; abortar restaura esa imagen.
- **Demostración con hilos** (`demos/transactions_demo.py`). Dos transacciones
  sin control de concurrencia pierden una actualización (resultado 1); con
  control, el deadlock se resuelve abortando y reintentando a la víctima, y el
  resultado es correcto (2), igual que en la ejecución en serie.

### 3.9 API e interfaz

La API FastAPI expone el catálogo, la ejecución de consultas, la creación de
tablas (incluida la importación CSV) y el manejo de sesiones con un token
opaco por pestaña. El modo por defecto es de solo lectura; `--allow-writes`
habilita escrituras, creación de tablas y transacciones. La interfaz tiene
cuatro paneles: **Archivos** (tablas, organización, columnas e índices),
**Consulta** (editor con presets, opción de usar o no índices y estrategia de
join), **Resultados** y **Plan de ejecución** (el árbol real con métricas).

## 4. Sección experimental

La comparación completa, con método, tablas, gráficos y conclusiones, está en
[../EXPERIMENTOS.md](../EXPERIMENTOS.md). En resumen, con 100 000 registros:

| Pregunta | Resultado medido |
|---|---|
| ¿Heap o Secuencial para insertar? | Heap: 36 s; Secuencial: 672 s (llegada ordenada) a 1 289 s (aleatoria) |
| ¿Heap o Secuencial para buscar por clave? | Secuencial: 1,6 ms; Heap: 431 ms |
| ¿Qué índice para igualdad? | Hash: 0,59 ms; B+: 1,6–2,7 ms |
| ¿Qué índice para rangos? | B+ (0,1 %: 22–29 ms frente a 860 ms recorriendo); desde ~4–5 % de la tabla conviene recorrer |
| ¿Qué índice con muchas inserciones y eliminaciones? | Hash (234 ops/s) o B+ no agrupado (220 ops/s); el B+ agrupado se reconstruye en cada inserción (0,002 ops/s) |

Antes de medir se corrigieron cuatro costos de implementación en módulos
anteriores, sin cambiar las técnicas exigidas; están documentados con su
justificación en [ajustes_modulos_previos.md](ajustes_modulos_previos.md).

## 5. Desarrollo incremental

La Parte 1 se construyó en diez etapas. Cada una se cerró con sus pruebas
pasando y una auditoría en `docs/`.

| Etapa | Contenido | Cierre | Pruebas al cierre |
|---|---|---|---:|
| 1 | Modelo de datos: tipos, esquemas, registros, RID, catálogo, contratos | 2026-08-31 | — |
| 2 | Páginas, codificación de registros, `PageManager`, persistencia | 2026-08-31 | 1 155 |
| 3 | Heap File y Archivo Secuencial Paginado | 2026-09-02 | 1 284 |
| 4 | Núcleo B+, índices agrupado y no agrupado | 2026-09-03 | 1 544 |
| 5 | Hash extensible | 2026-09-06 | 1 621 (1 772 tras revisión) |
| 6 | Operadores físicos y algoritmos externos | 2026-09-11 | 2 252 (2 295 tras revisión) |
| 7 | Motor SQL; extensión CREATE / EXPLAIN | 2026-09-18 / 09-20 | 2 556 / 2 742 |
| 8 | Transacciones y concurrencia | 2026-09-24 | 2 831 |
| 9 | API y frontend con sesiones | 2026-10-01 | 2 889 |
| 10 | Experimentos, integración y entrega | 2026-10-04 | 2 968 |

Las pruebas al cierre de la Etapa 10 incluyen las de la Parte 2 (motor
espacial), que se desarrolló en paralelo.

## 6. Limitaciones

- **Sin recuperación ante caídas.** No hay WAL: el rollback funciona mientras
  el proceso sigue vivo, pero una caída a mitad de una escritura de varios
  archivos no se recupera automáticamente; la base se niega a abrir y pide
  inspección.
- **Un solo proceso** puede abrir un directorio de datos.
- **Planner sin costos.** En rangos amplios usa el B+ aunque recorrer sea más
  rápido.
- **B+ agrupado** se reconstruye en cada inserción.
- **SQL acotado.** Sin `NULL`, `UPDATE`, subconsultas ni varias sentencias por
  llamada.
- **Hash sin fusión** de buckets ni reducción del directorio.
