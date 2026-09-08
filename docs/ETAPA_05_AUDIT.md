# Auditoría de cierre de la Etapa 5

Fecha: **2026-09-06**. Alcance: Extendible Hashing persistente, eliminación,
validación estructural, integración con `HeapFile`/`Catalog` e instrumentación.

Resultado: **Etapa 5 completa**. Se cumplen los **46 criterios obligatorios** de
la [Definition of Done](../ETAPA_05.md#39-definition-of-done). La suite completa
pasa **1621 pruebas con advertencias tratadas como errores**. Las Etapas 1–5
quedan cerradas y auditadas. **La Etapa 6 está planificada pero no iniciada.**

## Evidencia por criterio

Cada fila corresponde al checklist de `ETAPA_05.md`, en el mismo orden.

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 1 | Hash determinista/versionado | FNV-1a unsigned de 64 bits, versión 1, persistido en `HashFileHeader` | Cumple |
| 2 | Codificación canónica documentada/probada | Tag `DataType`, bytes B+ y cero FLOAT canónico; golden vectors | Cumple |
| 3 | Ancho y bits fijados | 64 bits y sufijo LSB persistidos | Cumple |
| 4 | Profundidades fijadas | Inicial 1; máximo persistido y acotado a 20 | Cumple |
| 5 | Directorio/bucket versionados | Codecs de página v1 con firma y padding canónico | Cumple |
| 6 | Políticas de duplicado/unicidad/borrado/colisión | Par idempotente, unicidad compartida, borrado exacto y error acotado | Cumple |
| 7 | Estado merge/shrink explícito | Ambos son opcionales y permanecen diferidos | Cumple |
| 8 | Decisiones estables promovidas | `PROJECT_CONTEXT.md` contiene el diseño final de Etapa 5 | Cumple |
| 9 | Header autocontenido para reapertura | Identidad, tipo, hash, profundidades, páginas, contadores y build state | Cumple |
| 10 | Directorio siempre mide `2^D` | Modelo, header, codec y validador lo exigen | Cumple |
| 11 | Directorio multipágina | Cadena ordenada; profundidad 10 cruza el límite físico | Cumple |
| 12 | Profundidad local persistente | Header de bucket y pruebas de split/reinicio | Cumple |
| 13 | Capacidad por bytes serializados | `HashBucket.serialized_size_for`, nunca un número fijo de objetos | Cumple |
| 14 | Páginas malformadas rechazadas | Firmas, versiones, longitudes, identidades, contadores y padding | Cumple |
| 15 | Ciclo de vida/reapertura | Create/open/flush/close y objetos nuevos probados | Cumple |
| 16 | Inserción con espacio | Reescritura exclusiva del bucket y contador global | Cumple |
| 17 | Búsqueda exacta | Una entrada de directorio, un bucket y comparación de clave completa | Cumple |
| 18 | Eliminación exacta | Solo `(clave, RID)`; ausencia usa `InvalidReferenceError` sin escrituras | Cumple |
| 19 | Split con `d < D` | Redirección de la mitad de aliases sin crecer el directorio | Cumple |
| 20 | Doubling con `d == D` | Duplicación LSB y posterior redirección | Cumple |
| 21 | Splits repetidos acotados | Plan completo en memoria y recálculo de profundidad | Cumple |
| 22 | Semántica igual a B+ | Duplicados, par idempotente y `DuplicateError` compartidos | Cumple |
| 23 | Colisiones/profundidad acotadas | `HashBucketOverflowError`/`HashDepthLimitError`, rechazo sin escritura | Cumple |
| 24 | Comparación de clave completa | El hash solo enruta; el bucket compara el valor tipado | Cumple |
| 25 | Referencias de directorio válidas | `validate_structure()` comprueba rango y tipo de página | Cumple |
| 26 | `local_depth <= global_depth` | Comprobación contextual por bucket | Cumple |
| 27 | Alias `2^(D-d)` | Conteo por bucket y patrón LSB comprobados | Cumple |
| 28 | Asociaciones en bucket compatible | Rehash completo durante validación profunda | Cumple |
| 29 | Split no pierde/duplica asociaciones | Redistribución de conjunto anterior más pendiente y pruebas exhaustivas | Cumple |
| 30 | Ninguna página referenciada se libera | No hay liberación porque merge/shrink son opcionales y diferidos | Cumple |
| 31 | Validador tras mutaciones | Pruebas deterministas, de reinicio y diferenciales | Cumple |
| 32 | Construcción desde HeapFile | Scan activo, tombstones excluidos, validación y build state | Cumple |
| 33 | Catálogo abre/reabre | Fábricas por `IndexType`, `file_path` y header físico autocontenido | Cumple |
| 34 | Mutaciones de tabla mantienen hash | `UnclusteredHashIndex` coordina insert/delete/update con rollback | Cumple |
| 35 | Movimiento RID repara asociaciones | Reconstrucción atómica desde candidato hermano validado | Cumple |
| 36 | Hash no anuncia rango/orden | Capacidades de `IndexMetadata` distinguen B+ y hash | Cumple |
| 37 | Métricas físicas/estructurales | I/O tipado real, splits, doublings, inspecciones, tamaño y build metrics | Cumple |
| 38 | Regresión Etapas 1–4 | Suite acumulada de 1621 pruebas sin fallos | Cumple |
| 39 | Unitarias de todas las piezas | Codec, header, directorio, bucket, split, búsqueda y delete | Cumple |
| 40 | Reinicios destruyen objetos | Dos reaperturas con PageManager/runtime nuevos y mutaciones intermedias | Cumple |
| 41 | Crecimiento multipágina | Directorio de 1024 entradas en dos páginas | Cumple |
| 42 | Colisiones deterministas | Hash constante, clave completa, límite y persistencia | Cumple |
| 43 | Diferencial contra oráculo | Secuencia pseudoaleatoria fija con mapa `clave -> set[RID]` | Cumple |
| 44 | Archivos malformados producen error de dominio | `ValidationError` y errores hash especializados | Cumple |
| 45 | Integración completa tras reinicio | Heap, build, mantenimiento, catálogo, reapertura y validación | Cumple |
| 46 | No se adelantó Etapa 6+ | Sin operadores concretos, SQL, transacciones, frontend ni benchmarks | Cumple |

## Arquitectura final auditada

```text
Catalog / IndexMetadata
          |
          v
build/open dispatcher
          |
          v
UnclusteredHashIndex ------> borrowed HeapFile
          |
          v
ExtendibleHashIndex
    |             |
directory pages   bucket pages
    \_____________/
           |
           v
       PageManager
```

- El núcleo persiste asociaciones completas `(clave, RID)` en un archivo propio.
- El adaptador valida que cada RID siga resolviendo la clave esperada en Heap.
- Construcción fallida conserva `build_complete=False`; reconstrucción publica
  un candidato validado mediante reemplazo atómico del archivo.
- Las fábricas genéricas despachan B+ frente a hash usando `IndexType`.
- El catálogo conserva definiciones inmutables en memoria, como en Etapa 4; el
  archivo físico conserva todo lo necesario para reiniciar sin defaults ocultos.

## Decisiones del incremento D

El contrato estable `Index.delete()` prevalece sobre el ejemplo `-> bool` de la
tarea 5.16: devuelve `None` al tener éxito y lanza `InvalidReferenceError` si el
par no existe. Un bucket vacío continúa siendo válido. Buddy merge, shrink del
directorio y liberación/reutilización asociada permanecen explícitamente
diferidos porque `ETAPA_05.md` los declara opcionales para completar la etapa.

El validador independiente revisa tamaño y cadena del directorio, propiedad de
páginas, referencias, profundidades, aliases, placement por hash, unicidad,
bytes/capacidad validados por codec, contadores persistidos y páginas huérfanas.
No modifica el estado persistente.

## Decisiones del incremento E

- `build_from_storage()` indexa únicamente filas activas y publica el build al
  final; una falla deja un archivo identificable como incompleto.
- `rebuild_from_storage()` usa un candidato hermano validado antes de reemplazar.
- `UnclusteredHashIndex` mantiene insert/delete/update; como Heap no actualiza en
  sitio, una actualización puede devolver un RID nuevo.
- Los rollbacks son best-effort; si también fallan, el índice se marca incompleto.
- `HashBuildMetrics`, `HashStructuralMetrics` y `HashMetrics` separan medición de
  construcción, eventos lógicos e I/O real por directorio/bucket.
- Los contadores son por sesión y `reset_counters()` los reinicia; una operación
  fallida conserva las lecturas físicas reales, pero un split/doubling solo se
  cuenta después de publicar su header.

## Verificación ejecutada

Entorno: Windows, **Python 3.12.6**, **pytest 8.4.2**, instalación editable local.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider `
  --basetemp tmp/stage5-closure
$hashTests = Get-ChildItem tests/indexes -Filter 'test_hash_*.py'
.\.venv\Scripts\python.exe -m pytest -q -W error $hashTests.FullName `
  tests/indexes/test_extendible_hash.py
.\.venv\Scripts\python.exe -m pytest -q -W error tests/test_architecture.py
.\.venv\Scripts\python.exe -m compileall -q engine tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Resultados de cierre:

- suite completa: **1621 aprobadas en 74.91 s**;
- pruebas específicas de hash: **77 casos recolectados**;
- arquitectura/importaciones aisladas: **19 aprobadas en 9.55 s**;
- pruebas de índices más integración B+: aprobadas durante la implementación;
- `compileall`, `pip check` y `git diff --check`: verificados al cierre.

## Límites conocidos

- Sin WAL, una falla durante una escritura multipágina no es crash-atómica.
- Un solo propietario/escritor; concurrencia y locks pertenecen a Etapa 8.
- No hay overflow pages: una colisión completa que excede un bucket falla de
  forma controlada y conserva el contenido lógico previo.
- No hay merge, shrink ni free list hash; la eliminación deja buckets vacíos.
- El catálogo global sigue en memoria; no se añadió persistencia global fuera
  del alcance arquitectónico heredado.
- No se ejecutaron benchmarks finales; pertenecen a Etapa 10.

## Estado después del cierre

- Etapas 1–5: **cerradas y auditadas**.
- Última etapa completada: **Etapa 5 — Extendible Hashing**.
- Próxima etapa: **Etapa 6 — Relational Operators and External Algorithms**,
  planificada en `ETAPA_06.md` y todavía sin implementación.
- Parte 1 continúa incompleta.
