# Auditoría de cierre de la Etapa 2

Fecha: **2026-08-31**. Alcance: páginas, registros y persistencia base de la Parte 1.

Resultado: **Etapa 2 completa**. Se cumplen los **47 criterios** de la
[Definition of Done](../ETAPA_02.md#30-stage-2-definition-of-done), además de los
contadores adoptados en 2.16. La suite completa pasa **1155 pruebas**.
**La Etapa 3 no está iniciada y la Parte 1 del proyecto sigue pendiente.**

## Evidencia por criterio

Cada fila corresponde a un criterio del checklist, en el mismo orden.

| N.º | Criterio | Evidencia revisada | Resultado |
|---|---|---|---|
| 1 | Tamaño de página explícito | [Formato v1](../PROJECT_CONTEXT.md#physical-format-v1): 4096 bytes, decisión del proyecto; [constantes y pruebas](../tests/storage/test_binary.py) | Cumple |
| 2 | Layout de página documentado | Formato v1: cabecera, directorio, zona libre y payload; [Page](../engine/storage/page.py) | Cumple |
| 3 | Layout de slots documentado | Formato v1: `<HHB`, cinco bytes, estados y entradas canónicas; [pruebas](../tests/storage/test_slot_entry.py) | Cumple |
| 4 | Codificación de registros documentada | [Codificación primitiva y de registros](../PROJECT_CONTEXT.md#primitive-and-record-encoding), tipos estrictos y esquema externo | Cumple |
| 5 | Estrategia de cabecera de archivo | Prefijo de 20 bytes `<8sIII` y páginas desde cero; [FileHeader](../engine/storage/file_header.py) | Cumple |
| 6 | Orden de bytes documentado | Little-endian explícito, tamaños sin padding nativo; [golden bytes](../tests/storage/test_binary.py) | Cumple |
| 7 | Política de estabilidad de RID | [Vida y reutilización de RID](../PROJECT_CONTEXT.md#rid-lifetime-and-space-reuse); [compactación](../tests/storage/test_page_compaction.py) y reapertura | Cumple |
| 8 | Política de NULL explícita | `None`/SQL NULL no soportado; [Record](../tests/storage/test_record.py) y [codecs](../tests/storage/test_value_codec.py) | Cumple |
| 9 | Persistencia del catálogo explícita | Catálogo en memoria y esquema aportado externamente; [pipeline](../tests/test_stage2_persistence_pipeline.py) | Cumple |
| 10 | Round-trip de cada primitivo | [ValueCodec](../tests/storage/test_value_codec.py), límites, NaN, infinitos, Unicode; [disco](../tests/storage/test_persistence.py) | Cumple |
| 11 | Framing determinista de VARCHAR | Prefijo uint32 en bytes y UTF-8 estricto; pruebas de longitudes, Unicode y bytes malformados | Cumple |
| 12 | RecordCodec serializa Record | [Pruebas de RecordCodec](../tests/storage/test_record_codec.py), tipos/cantidad y registros independientes | Cumple |
| 13 | RecordCodec reconstruye Record | Pruebas del codec y [procesos independientes](../tests/test_stage2_persistence_pipeline.py), con Schema nuevo | Cumple |
| 14 | Registros malformados rechazados | Truncamientos, bytes sobrantes, booleanos y UTF-8 inválidos; también en páginas válidas cargadas del disco | Cumple |
| 15 | PageHeader | [Pruebas](../tests/storage/test_page_header.py): campos, inmutabilidad, formato de 12 bytes y geometría | Cumple |
| 16 | SlotEntry/directorio | [Pruebas](../tests/storage/test_slot_entry.py): estados, offsets, longitudes, slot activo vacío frente a libre | Cumple |
| 17 | Página vacía | [Page](../tests/storage/test_page.py): cero slots, 4084 bytes contiguos y round-trip | Cumple |
| 18 | Inserción de tamaño variable | Page: varios payloads opacos, límites, coste del directorio y ausencia de cambios parciales | Cumple |
| 19 | Lectura por slot_id | Page: payloads exactos; distinción de slot inexistente, libre y corrupto | Cumple |
| 20 | Eliminación local | Page: estado libre, contador activo, doble eliminación y huecos sin recuperación implícita | Cumple |
| 21 | Contabilidad de espacio libre | Page y [persistencia](../tests/storage/test_persistence.py): espacio contiguo, coste de slot y directorio conservado | Cumple |
| 22 | Compactación | [Pruebas](../tests/storage/test_page_compaction.py): offsets actualizados, RIDs vivos, idempotencia, reinserción y casos después de reabrir | Cumple |
| 23 | Serialización de PAGE_SIZE exacto | Page y pruebas de cabeceras: cada frame ocupa 4096 bytes, incluidos huecos y bytes libres | Cumple |
| 24 | Deserialización completa de Page | Páginas activas, fragmentadas, todas eliminadas, compactadas y vacías, con copia independiente | Cumple |
| 25 | Invariantes de página | [Validadores](../engine/storage/binary.py): estados, contadores, límites y no solapamiento; rechazos en memoria y disco | Cumple |
| 26 | FileHeader | [Pruebas](../tests/storage/test_file_header.py): firma, versión, tamaño y uint32; formato exacto e inmutable | Cumple |
| 27 | Crear archivo | [PageManager](../tests/storage/test_page_manager.py): creación exclusiva, sin sobrescritura ni creación implícita de padres | Cumple |
| 28 | Abrir archivo | PageManager: apertura sin truncamiento, validación de cabecera y longitud, no creación implícita | Cumple |
| 29 | Asignar página | IDs consecutivos, página vacía inicializada, cabecera actualizada y tamaño correcto del archivo | Cumple |
| 30 | Escribir página | Escritura explícita de una página asignada; fallo de precondiciones no modifica el archivo | Cumple |
| 31 | Leer página | Copia independiente, geometría e identidad física comprobadas, sin caché de páginas | Cumple |
| 32 | Reescribir página | Vecinas preservadas, tamaño estable; segunda escritura confirmada en otro proceso | Cumple |
| 33 | Flush | Prueba de llamada a `os.fsync`, persistencia y contadores sin incremento por flush | Cumple |
| 34 | Close | Cierre idempotente, `with`, cierre por excepción y liberación incluso si falla flush | Cumple |
| 35 | Reapertura | Gestor nuevo recupera cabecera, páginas y registros; [persistencia](../tests/storage/test_persistence.py) | Cumple |
| 36 | Varias páginas persistentes | Cuatro páginas iniciales y quinta después de reiniciar, con slots activos/libres y páginas vacías | Cumple |
| 37 | IDs de página inválidos rechazados | [Límites de archivos](../tests/storage/test_malformed_files.py), lecturas y escrituras sin asignación ni transferencias implícitas | Cumple |
| 38 | Registros demasiado grandes rechazados | Record serializado de 4079 bytes persiste; un byte más falla sin alterar página/archivo; ASCII y Unicode | Cumple |
| 39 | Archivos malformados/truncados | Cortes en límites de estructuras; cada byte de firma; versión, tamaño y cantidad incompatibles | Cumple |
| 40 | Corrupción de slots/cabeceras | [Casos compartidos](../tests/page_corruption.py) en memoria/disco, solapamientos e identidad física incorrecta | Cumple |
| 41 | Record → bytes → Page → disco | [Pipeline](../tests/test_stage2_persistence_pipeline.py) con modelos reales y esquema externo, sin dobles de almacenamiento | Cumple |
| 42 | Disco → Page → bytes → Record | Nuevo proceso decodifica y compara valores y tipos, incluidos NaN y cero con signo | Cumple |
| 43 | Gestor nuevo recupera datos | Procesos separados para escribir, leer, reescribir y verificar el resultado final | Cumple |
| 44 | Todas las pruebas pertinentes pasan | **1155 passed**, sin omisiones, xfails ni advertencias con `-W error` | Cumple |
| 45 | Decisiones estables consolidadas | [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md): formato, operaciones, errores, contadores y límites de persistencia | Cumple |
| 46 | Documentos identifican la etapa correcta | AGENTS, PLAN, PROJECT_CONTEXT, ETAPA_02 y README indican Etapa 2 cerrada y Etapa 3 no iniciada | Cumple |
| 47 | Sin algoritmos de Etapa 3 | Inventario y revisión del código; motor sin cambios en este bloque; no Heap File, Sequential File ni selección de página libre | Cumple |

## Verificación ejecutada

Entorno: Windows, **Python 3.12.4**, **pytest 8.4.2**, instalación editable existente.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/storage/test_persistence.py tests/storage/test_malformed_files.py tests/test_stage2_persistence_pipeline.py -q -W error
.\.venv\Scripts\python.exe -m pytest tests/test_architecture.py -q -W error
.\.venv\Scripts\python.exe -m pytest -ra -W error
.\.venv\Scripts\python.exe -m compileall -q engine api tests
.\.venv\Scripts\python.exe -m pip check
git -c core.safecrlf=false diff --check
```

- Baseline del bloque: **1067 pruebas aprobadas**. Se añaden 88 casos: 13 de
  persistencia, 59 de archivos/límites, 11 de integración y 5 de arquitectura.
- Suite final: **1155 aprobadas**. Los casos de corrupción existentes se
  conservan y comparten sus datos con las pruebas de lectura desde disco.
- Arquitectura: **14 pruebas**; grafo explícito sin ciclos, dependencias
  permitidas y sin bibliotecas que sustituyan los algoritmos académicos.
- Diez primeros imports distintos en intérpretes `python -I -B`, fuera del
  repositorio, comprueban todos los módulos/exportaciones del motor. El catálogo
  sigue sin depender del almacenamiento. No se carga código de tests desde el motor.
- La revisión de imports y de operaciones de archivo confirma que el I/O físico
  de páginas y su direccionamiento permanecen en `PageManager`. Las páginas no
  conocen tipos SQL, esquemas, codecs, archivos ni organizaciones de Etapa 3.
- Dos escenarios de pipeline —fragmentado y compactado— utilizan cuatro
  procesos cada uno. Solo pasan ruta, definición externa del esquema y controles
  del escenario; no reciben los registros, páginas ni buffers originales.
- Contadores: se verifican transferencias completas reales, asignaciones,
  reinicio de sesión, lecturas corruptas y fallos/transferencias parciales en
  [test_page_manager_io.py](../tests/storage/test_page_manager_io.py). No son
  estimaciones ni contadores de fallos de caché del hardware.
- `compileall`, `pip check` y revisión de espacios: correctos. Se ejecutó el
  ejemplo completo de persistencia del README con un archivo temporal.
- Configuración/metadatos instalados: único paquete de nivel superior `engine`;
  dependencias de ejecución vacías y pytest opcional. Los helpers/datos de prueba
  permanecen en `tests/`, fuera de los paquetes seleccionados para distribución.
- Se compararon hashes SHA-256 del motor, `REQUIREMENTS.md`, `pyproject.toml` y
  la auditoría histórica de Etapa 1 con la base de este bloque: sin cambios.
  Se preservó el trabajo previo no confirmado en Git; no se crearon commits.

## Límites de la evidencia y decisiones conservadas

- Se prueba persistencia después de escritura y **cierre normal**, también
  cuando termina el proceso. No se simulan apagones ni se promete crash recovery,
  WAL, transacciones atómicas, concurrencia o durabilidad de entradas de directorio.
- El gestor admite un solo propietario/escritor por archivo. Flush/fsync no
  vuelve atómica una asignación o reescritura. Un error de escritura puede dejar
  un archivo incompleto; se cierra el handle y se propaga el error, sin reparación.
- `ValidationError`/`InvalidReferenceError` cubren bytes, geometría y referencias
  inválidas. Los errores nativos de archivo/sistema siguen siendo `OSError` y
  sus subclases. El ciclo de vida cerrado usa `RuntimeError`.
- La geometría válida no implica un Record válido: el codec valida el payload.
  No hay checksum, autodetección del esquema ni catálogo persistente. Un esquema
  equivocado pero binariamente compatible puede decodificar sin error; la prueba
  correspondiente hace explícita esa responsabilidad del llamador.
- Los RIDs vivos sobreviven a compactación. Un RID eliminado puede identificar
  otra fila después de reutilizar el slot; no se añadieron generaciones.
  Compactar nunca elimina entradas del directorio ni mueve filas entre páginas.
- Las pruebas usan archivos pequeños y datos reproducibles. No son benchmarks
  de Etapa 10, ni implementaciones de Heap File/Sequential File disfrazadas.
- No se construyó un wheel ni se hizo una reinstalación limpia. Las pruebas
  verifican la instalación editable disponible y la selección de paquetes.
- Ejecución verificada en Windows/Python 3.12.4; el análisis AST del motor usa
  la gramática Python 3.11. No se afirma ejecución en otros sistemas/versiones.

## Estado después del cierre

- Etapa 1: cierre histórico conservado en [su auditoría](ETAPA_01_AUDIT.md).
- Etapa 2: **cerrada**, tareas 2.1–2.20 y todos los criterios aplicables satisfechos.
- Etapa 3: **no iniciada**; el cierre no autoriza empezarla automáticamente.
- El siguiente paso autorizado por separado será detallar Etapa 3 y construir
  Heap File/Paged Sequential File sobre estas primitivas, sin reemplazarlas.
- No se creó `ETAPA_03.md`; no se añadieron índices físicos, SQL, transacciones,
  API, frontend, catálogo persistente, buffer pool ni recuperación ante fallos.
