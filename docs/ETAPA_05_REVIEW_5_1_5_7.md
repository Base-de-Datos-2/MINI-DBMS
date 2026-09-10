# Revisión y correcciones de las tareas 5.1–5.7

Fecha: **2026-09-10**. Alcance: fundamentos de Extendible Hashing de
[ETAPA_05.md](../ETAPA_05.md): inspección, decisiones, cabecera, hashing,
directorio, buckets y codecs. Es una revisión del bloque, no un nuevo cierre
formal de toda la etapa.

## Contraste por tarea

| Tarea | Resultado de la revisión | Evidencia |
|---|---|---|
| 5.1 — Inspección | Se confirmó la reutilización de contratos, claves/RID, páginas, errores, catálogo e instrumentación existentes. No faltan prerrequisitos para este bloque. | [Inspección histórica](ETAPA_05_INCREMENTOS_ABC.md), `engine/indexes/base.py`, `bplus_codec.py`, `engine/storage/page_manager.py`, adaptadores B+ y pruebas de arquitectura. |
| 5.2 — Decisiones | FNV-1a/64/v1, LSB, límites, capacidad por bytes, duplicados e interfaces coinciden con el contexto. Se hizo explícita la ocupación exacta de cada página del directorio. | [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md), `hash_binary.py`, `hash_codec.py`. |
| 5.3 — Cabecera | Corregida: rechaza cantidades de páginas incompatibles con el directorio, más buckets que entradas, payloads sobredimensionados y JSON excesivamente anidado. Conserva identidad, versiones, profundidades y estado de construcción persistidos. | `hash_header.py`, `test_hash_header.py`, nuevas regresiones. |
| 5.4 — Hashing | Implementación conservada. Se verificaron tipos estrictos, límites int64, NaN, NULL, UTF-8, ceros FLOAT, vectores FNV y repetibilidad en intérpretes nuevos con distintas semillas del hash de Python. | `hash_codec.py`, `test_hash_codec.py`, nuevas pruebas de procesos y límites. |
| 5.5 — Directorio | Corregido: concatenación y acceso puntual comprueban la misma distribución de entradas por página. Se verificaron aliases, duplicaciones, enlaces, búsquedas, reapertura y persistencia en tres páginas. | `hash_directory.py`, lectores de `extendible_hash.py`, nuevas regresiones. |
| 5.6 — Buckets | Corregido: claves y RIDs se validan antes de ordenar; entradas inválidas producen errores de dominio. Se conserva inmutabilidad, borrado exacto, idempotencia y capacidad por bytes. | `hash_bucket.py`, `test_hash_bucket.py`, pruebas aleatorias de los cuatro tipos. |
| 5.7 — Codecs | Corregido: leer un bucket no reordena silenciosamente sus bytes. Se amplió evidencia de firmas, versiones, conteos, longitudes, referencias, duplicados, padding, tipos de página y marcos físicos de 4096 bytes. | `hash_bucket.py`, `hash_directory.py`, `hash_io.py` y fixtures binarios independientes. |

Las pruebas nuevas están en
[test_hash_foundations_review.py](../tests/indexes/test_hash_foundations_review.py).

## Inspección de compatibilidad (5.1)

- `Index` mantiene el par repetido como operación idempotente y el borrado como
  `None`/`InvalidReferenceError`. Los ejemplos mutables de la guía no sustituyen
  los modelos inmutables adoptados: `set_entry`, `double`, `insert`, `delete` y
  `replace_entries` producen nuevos modelos cuando hay cambios.
- `BPlusKeyCodec` sigue imponiendo tipos exactos, int64, UTF-8 y VARCHAR de hasta
  255 bytes; `BPlusRIDCodec` codifica los dos componentes uint32 del RID común.
- `PageManager` conserva propiedad y E/S físicas; cada directorio/bucket ocupa
  un payload en slot 0 de un marco `Page` normal. No se introdujo un asignador
  alternativo ni un segundo formato de RID.
- Las referencias a filas son físicas. El adaptador B+ sobre Heap conserva esa
  separación; el clustered sobre Sequential reconstruye tras movimientos de
  RID. No se añadieron identidades históricas ni garantías transaccionales.
- El catálogo sigue siendo un registro en memoria y los archivos de índice
  guardan sus metadatos de reapertura. Esta interpretación respeta el contexto
  estable; el enunciado de persistencia del catálogo en el checklist global
  necesita aclaración cuando se revise el bloque 5.22–5.27.
- La nota original de 5.1 registraba 17 fallos del intérprete sin instalación
  editable. La línea base obtenida durante la revisión previa, con el entorno
  `.venv` correcto, fue **1621 pruebas aprobadas en 62,65 s**, con advertencias
  como errores. No se reproduce aquel problema de entorno.

## Defectos reproducidos y correcciones

Un directorio de 1024 entradas repartido en **1014 + 10** pasaba el validador y
la reapertura, aunque el acceso puntual esperaba **1015 + 9**. Una clave
existente devolvía una búsqueda vacía. Ahora `validate_position()` exige el
número exacto de entradas de cada ordinal y la condición terminal del enlace.
Se llama tanto al leer el directorio completo como al buscar una entrada.
La regresión exige rechazo antes y después del cierre, sin escrituras durante
la validación. Las búsquedas también comprueban los enlaces visibles de su
ruta; la validación global continúa siendo responsable de recorrer toda ella.

La cabecera aceptaba dos páginas para un directorio de dos entradas, una sola
para 1024 entradas y más buckets que referencias. Ahora contrasta esos campos
antes de exponer el archivo. La validación de páginas huérfanas y ownership
permanece en el validador global.

El constructor de buckets podía comparar dos objetos RID inválidos y producir
un `TypeError` nativo. Validarlos primero recupera la excepción de dominio
prevista. El decoder también aceptaba asociaciones persistidas fuera de orden
y las ordenaba silenciosamente; ahora exige reconstrucción binaria exacta.

Antes de aplicar las correcciones, la primera tanda nueva produjo **9 fallos
y 47 aprobaciones**. Después, esa tanda junto con las pruebas existentes de
formatos, crecimiento y validador produjo **121 aprobaciones**. Se añadieron
además pruebas de persistencia del directorio en tres páginas y corrupción de
asociaciones duplicadas/booleanos.

## Compatibilidad del formato

No cambia la versión 1 ni ningún byte producido por los escritores válidos
existentes. El directorio ya se escribía con páginas intermedias completas y
los buckets ya se ordenaban antes de persistirlos. Se rechazan representaciones
incompatibles que antes podían aceptarse o repararse silenciosamente.

La etiqueta de tipo y normalización de `-0.0` pertenecen a la entrada de la
función hash. El bucket conserva los bytes escalares de B+, incluido el signo
del cero; no se ha introducido una conversión del formato persistente.

## Validación final

Comandos utilizados con el intérprete local Python 3.12.4:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q engine tests
git diff --check
```

- Suite completa: **1683 aprobadas en 84,90 s**, con advertencias como errores,
  sin omisiones ni xfails; incluye las **62 pruebas nuevas** de esta revisión y
  las comprobaciones de arquitectura/importaciones existentes.
- `compileall`: correcto.
- `git diff --check`: correcto; Git solo informa de normalización LF/CRLF.

Resultado del bloque: **5.1–5.7 revisadas, corregidas donde correspondía y
verificadas**. No hay fallos de regresión en la suite configurada.

## Pendientes fuera de este bloque

- 5.23: marcar incompleto el índice cuando falla el rollback de inserción Heap.
- 5.25: conservar los contadores tipados de E/S de la creación inicial.
- 5.26: validar cada mutación en la prueba diferencial pequeña y ampliar
  cobertura de los bloques siguientes.
- 5.27/cierre: reconciliar los **47 criterios** reales con las **46 filas** de
  la auditoría histórica y actualizar el estado global una vez revisado el resto.

La ausencia de WAL, atomicidad entre archivos, merge y shrink sigue siendo una
limitación explícita del diseño; esta revisión no incorpora esas funciones.
