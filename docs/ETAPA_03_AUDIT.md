# Auditoría de cierre de la Etapa 3

Fecha: **2026-09-02**. Alcance: Heap File y Paged Sequential File de la Parte 1.

Resultado: **Etapa 3 completa**. Se cumplen los **50 criterios** de la
[Definition of Done](../ETAPA_03.md#36-stage-3-definition-of-done). La suite
completa pasa **1284 pruebas**. **La Etapa 4 no está iniciada y la Parte 1 del
proyecto sigue pendiente.**

## Evidencia por criterio

Cada fila corresponde a un criterio del checklist, en el mismo orden.

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 1 | Definition of Done de Etapa 2 verificada | [Auditoría de Etapa 2](ETAPA_02_AUDIT.md), 47 criterios y 1155 pruebas | Cumple |
| 2 | Pruebas de Etapas 1 y 2 siguen pasando | Suite completa de 1284 pruebas sin omisiones, xfails ni advertencias | Cumple |
| 3 | Documentos identifican correctamente la Etapa 3 | AGENTS, PLAN, PROJECT_CONTEXT, README y ETAPA_03 registran este cierre | Cumple |
| 4 | Tipo de organización persistido y validado | `OrganizationType`/`OrganizationMetadata`; aperturas cruzadas Heap/Sequential rechazadas | Cumple |
| 5 | Ciclo create/open/flush/close definido | `OrganizationFile`, contextos, cierre idempotente y operaciones tras cierre | Cumple |
| 6 | Metadatos sobreviven reapertura | Esquema, contadores, clave, duplicados y umbral recuperados desde página 0 | Cumple |
| 7 | Compatibilidad de esquema/clave validada | Pruebas de apertura correcta e incompatibilidades sin mutación | Cumple |
| 8 | Offsets físicos encapsulados | Revisión AST: solo `PageManager` importa módulos de I/O crudo | Cumple |
| 9 | Heap insert devuelve RID válido | [Pruebas Heap](../tests/storage/test_heap_file.py), una y varias páginas | Cumple |
| 10 | Heap read reconstruye Record | Lecturas por RID y codec con esquema persistido, incluidos reinicios | Cumple |
| 11 | Heap delete elimina una fila activa | Slot FREE, contadores exactos y doble eliminación rechazada | Cumple |
| 12 | Heap scan visita cada fila activa una vez | Recorrido perezoso por `(page_id, slot_id)` | Cumple |
| 13 | Heap omite eliminados | Pruebas antes y después de reapertura | Cumple |
| 14 | Heap soporta múltiples páginas | Registros grandes, nuevas páginas y lectura/reinicio | Cumple |
| 15 | Heap soporta longitudes variables | Registros vacíos, pequeños, Unicode y payload máximo | Cumple |
| 16 | Heap reutiliza espacio | Reutilización de slots/huecos con compactación local | Cumple |
| 17 | Heap evita asignación innecesaria | `HeapFreeSpaceTracker`, candidato mínimo, información obsoleta verificada por Page | Cumple |
| 18 | Semántica de orden/reutilización honesta | Contexto documenta orden físico y posible reutilización de RID eliminado | Cumple |
| 19 | Tracker sobrevive o se reconstruye | Reconstrucción desde todas las páginas en cada `open` | Cumple |
| 20 | Estado Heap persiste con objetos nuevos | [Persistencia Heap](../tests/storage/test_heap_persistence.py) y escenario integral | Cumple |
| 21 | Clave secuencial persistida y validada | Columna exacta, tipo derivado del esquema y metadatos versionados | Cumple |
| 22 | Comparador y duplicados explícitos | [SequentialOrdering](../tests/storage/test_sequential_ordering.py): cuatro tipos, NaN y estabilidad | Cumple |
| 23 | Entradas arbitrarias producen scan ordenado | Inserciones desordenadas y validación no decreciente | Cumple |
| 24 | Inserción antes, después y entre claves | Casos de mínimos, máximos, intermedios y duplicados | Cumple |
| 25 | Inserción cruza páginas | Redistribución, división de dos/tres páginas y desplazamiento de sufijo | Cumple |
| 26 | Búsqueda exacta | Vacío, ausente, extremos, intermedio y todos los duplicados | Cumple |
| 27 | Eliminación diferida | `delete(rid)` persiste tombstone sin compactar ni reorganizar | Cumple |
| 28 | Scan/search excluyen eliminados | Slots FREE omitidos antes y después del reinicio | Cumple |
| 29 | Fórmula de desperdicio documentada/probada | Huecos de payload más entradas FREE sobre bytes de páginas de datos | Cumple |
| 30 | Umbral explícito | Predicado estricto `ratio > threshold`, configurable y de solo lectura | Cumple |
| 31 | Reorganización preserva activos una vez | Archivo candidato recibe el stream activo completo y valida el conteo | Cumple |
| 32 | Reorganización elimina tombstones | Metadatos eliminados en cero y razón de desperdicio final cero | Cumple |
| 33 | Orden válido después de reorganizar | Scan/duplicados validados en candidato, objeto actual y reapertura | Cumple |
| 34 | Política de RID explícita | Inserción estructural/reorganización invalidan RIDs previos sin mapa | Cumple |
| 35 | Estado secuencial persiste | Ciclo con objetos nuevos: tombstones, métrica, inserción, reorden y segunda reapertura | Cumple |
| 36 | RIDs inválidos fallan previsiblemente | Tipo, página, slot y slot eliminado diferenciados sin escrituras indebidas | Cumple |
| 37 | Organización incorrecta rechazada | Heap no abre Sequential ni viceversa | Cumple |
| 38 | Esquema/clave incompatibles rechazados | Definiciones externas y clave persistida comprobadas | Cumple |
| 39 | Registro demasiado grande rechazado | Máximo exacto aceptado y un byte adicional sin asignación/mutación | Cumple |
| 40 | Tracker obsoleto no corrompe | Referencias/capacidades se refrescan o descartan y Page decide el ajuste final | Cumple |
| 41 | Fallos de reorganización siguen la estrategia | Construcción, candidato truncado y `os.replace` fallidos conservan el original utilizable | Cumple |
| 42 | Contadores de filas/páginas/archivo consistentes | Apertura recalcula y rechaza discrepancias Heap y Sequential | Cumple |
| 43 | Ambas organizaciones usan Page/PageManager | Dependencias y pruebas de integración sobre la misma capa física | Cumple |
| 44 | Ambas usan RecordCodec | Serialización/reconstrucción común, sin codecs alternativos | Cumple |
| 45 | Ambas exponen Record/RID para índices futuros | Contrato `Storage` y scans `(RID, Record)` | Cumple |
| 46 | Contadores de E/S preservados | Transferencias reales por sesión y `ReorganizationMetrics` agregado | Cumple |
| 47 | Mismo dataset en ambas organizaciones | [Integración cruzada](../tests/integration/test_stage3_file_organizations.py), multiset activo idéntico | Cumple |
| 48 | Pruebas pertinentes pasan | **1284 passed** con `-W error`; almacenamiento, integración y arquitectura incluidos | Cumple |
| 49 | Decisiones estables consolidadas | PROJECT_CONTEXT documenta propiedad, metadatos, políticas, RIDs, reemplazo e instrumentación | Cumple |
| 50 | Sin algoritmos posteriores | Inventario/revisión: no B+, hashing extensible, SQL, transacciones, API ni frontend ejecutable | Cumple |

## Auditoría de errores y límites de 3.22

| Caso requerido | Evidencia | Resultado |
|---|---|---|
| Organización incorrecta | Apertura cruzada Heap/Sequential | Cubierto |
| Esquema o clave incompatibles | Pruebas de ciclo de vida de ambas organizaciones | Cubierto |
| RID inválido o eliminado | Tipo/página/slot/FREE en Heap y Sequential | Cubierto |
| Capacidad máxima | Payload máximo y excedido sin mutación | Cubierto |
| Tracker obsoleto | Capacidad y referencia obsoletas en Heap | Cubierto |
| Metadatos corruptos | JSON/layout/campos y discrepancias de contadores específicas | Cubierto |
| Archivo vacío y objeto cerrado | Operaciones públicas y generadores | Cubierto |
| Tipo de clave | Los cuatro `DataType` admitidos; tipos/coerciones/NaN inválidos rechazados | Cubierto |
| Conflicto de duplicados | Política única rechaza sin escritura; política por defecto conserva estabilidad | Cubierto |
| Fallo de reorganización | Construcción, validación truncada y reemplazo fallidos | Cubierto |

No existe un `DataType` adoptado que quede sin soporte secuencial. Por ello el
caso “tipo de clave no soportado” se resuelve rechazando valores/coerciones y
metadatos ajenos al enum vigente, sin inventar un quinto tipo ni una excepción.
Los errores existentes (`InvalidTypeError`, `ValidationError`, `SchemaError`,
`DuplicateError`, `InvalidReferenceError` y errores nativos de archivo) fueron
suficientes.

## Preparación para mediciones

- Inserción y búsqueda pueden cronometrarse externamente con `perf_counter`,
  rodeadas por `reset_counters()` y los contadores reales del gestor.
- `file_size` devuelve el tamaño físico validado sin fingir una transferencia de
  página.
- `reorganize()` devuelve `ReorganizationMetrics`: tiempo real, tamaños antes y
  después y E/S agregada de fuente, construcción y validación. La nueva sesión
  reabierta empieza sus contadores en cero, como prescribe `PageManager`.
- Las pruebas solo verifican disponibilidad, finitud y relación con operaciones
  reales; no contienen umbrales de rendimiento dependientes de la máquina.
- No se ejecutaron todavía los experimentos finales de 1K/10K/100K ni se
  fabricaron resultados. Esos corresponden a la Etapa 10.

## Verificación ejecutada

Entorno: Windows, **Python 3.12.4**, **pytest 8.4.2**, instalación editable existente.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/storage -q -W error
.\.venv\Scripts\python.exe -m pytest tests/integration -q -W error
.\.venv\Scripts\python.exe -m pytest tests/test_architecture.py -q -W error
.\.venv\Scripts\python.exe -m pytest -q -W error
.\.venv\Scripts\python.exe -m compileall -q engine api tests
.\.venv\Scripts\python.exe -m pip check
git -c core.safecrlf=false diff --check
```

- Baseline del bloque: **1274 pruebas aprobadas**. Se añadieron diez casos:
  cuatro de instrumentación, dos de límites/corrupción, tres de integración y
  una comprobación aislada de importación del nuevo módulo de métricas.
- Suite final: **1284 aprobadas**, sin advertencias, omisiones ni xfails.
- La revisión de arquitectura conserva el grafo sin ciclos, las dependencias
  permitidas y todo I/O crudo dentro de `PageManager`.
- `compileall`, `pip check` y la revisión del diff pasan.
- Se preservó el trabajo previo no confirmado en Git; no se crearon commits.

## Límites de la evidencia

- La persistencia probada corresponde a cierres normales. No se promete WAL,
  recuperación ante apagones, transacciones ni acceso concurrente.
- Cada archivo tiene un único propietario/escritor. La sustitución compacta usa
  un candidato validado y `os.replace` en el mismo directorio; no constituye un
  protocolo transaccional ni garantiza recuperación después de todo fallo del
  sistema operativo posterior al commit.
- Los RIDs Heap vivos conservan la política local de páginas. Los RIDs
  secuenciales pueden invalidarse al insertar estructuralmente o reorganizar;
  todavía no existen índices que deban reconstruirse.
- `ReorganizationMetrics` mide transferencias realizadas por `PageManager`, no
  fallos de caché de hardware. Los headers, seeks, flush y reemplazo de entrada
  de directorio no se cuentan como páginas.
- Las pruebas usan datos pequeños y reproducibles; confirman corrección y
  preparación para medir, no rendimiento a las escalas finales.
- El catálogo general continúa en memoria aunque cada archivo de organización
  persiste el esquema necesario para reabrirse. No se añadió descubrimiento de
  tablas, buffer pool ni checksum.
- Ejecución verificada en Windows/Python 3.12.4; no se afirma portabilidad ya
  probada a otros sistemas.

## Estado después del cierre

- Etapas 1, 2 y 3: **cerradas y auditadas**.
- Etapa 4: **no iniciada**. Requiere una solicitud explícita separada.
- Parte 1: **incompleta**; aún faltan índices, algoritmos externos, SQL,
  transacciones/concurrencia, API/frontend y experimentos finales.
- No se creó `ETAPA_04.md` ni se implementó B+ durante este cierre.
