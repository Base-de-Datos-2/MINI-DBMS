# Parte 3 — Bloque 4A: política persistente de escritura

Fecha: 2026-10-28. **Estado: CERRADO**, con el fallo previo de sanitización
en Windows declarado en la verificación. La petición del usuario autoriza
el bloque 4A de [PLAN_PARTE_03.md](PLAN_PARTE_03.md), §5.2 y §7.
Se implementa el sello del almacenamiento y su cumplimiento en las rutas
actuales. El registro textual, parser, binder, operador SQL y EXPLAIN textual
pertenecen al bloque 4B y conservan su alcance pendiente.

## Decisión de formato y publicación

Los archivos mutables conservan exactamente el formato v1. No se migran ni
reescriben al abrir. Una publicación explícita produce:

- Header común v2 en el Heap y en todos los B+/hash secundarios enumerados.
- Metadatos organizados v2 del Heap con `collection_id` y `generation`.
- Las mismas páginas de datos, filas, RIDs, conteos, postings y scores.

El lector anterior del commit `039a063`, ejecutado en un intérprete aislado
con sus módulos originales `errors`, `storage.binary` y `storage.file_header`,
aceptó un archivo mutable real v1 y rechazó el header de un Heap sellado real:
`ValidationError: Unsupported file format version: 2`. Un motor anterior no
puede interpretar silenciosamente el archivo como mutable.

El nuevo motor rechaza discrepancias entre versión del header y descriptor
persistente. Los adaptadores B+/hash rechazan discrepancias de política con
su Heap. La verificación/búsqueda con almacenamiento sellado también exige
que colección y generación coincidan con las del TextIndex.

`engine.text.seal_text_collection` valida primero esquema, asociación de
índices, capacidad del descriptor, estructuras, TextIndex y contenido/RIDs del
Heap. Sella los secundarios primero y el Heap al final. **El llamador debe
enumerar todos los secundarios declarados**, sin omitirlos; la enumeración
desde el registro y su publicación definitiva serán responsabilidad de 4B.
Esta función no escribe `text_tables.json`.

La operación es offline: todos los owners y coordinators deben estar cerrados.
El registro de exclusión sigue su vida completa, incluyendo cierre/reapertura
internos de handles por undo. Un latch de admisión impide que un nuevo owner
entre durante toda la validación/publicación de varios archivos. No serializa
las consultas ordinarias. Los alias del mismo proceso reciben la política por
una caché de rutas canónicas; las nuevas aperturas leen el header persistente.
No se relee físicamente el header en cada escritura de una tabla mutable.

No hay operación de desellado, recuperación automática ni commit atómico de
varios archivos. Si falla una publicación, puede quedar una preparación
parcial; los estados incompatibles se rechazan al reabrir. Reconstruir en otro
directorio, nunca restaurar una imagen mutable sobre archivos sellados.
La preparación exige una fuente sin escritores. No se añade bloqueo entre
procesos ni protección frente a modificaciones externas del sistema de archivos.

## Matriz de rutas auditadas

| Ruta | Rechazo y evidencia |
|---|---|
| `HeapFile.insert/delete` | Guard antes de validar/mutar páginas o contadores; misma política al reabrir directamente o mediante QueryEnvironment |
| `PageManager.allocate_page/write_page/commit_replacement` | Guard físico protege incluso handles expuestos; ningún archivo o contador de escritura cambia por el rechazo |
| B+/hash de Heap y sus cores públicos | Guard de base y header propio en insert/delete, métodos de registros, rebuild, marca incomplete y sustitución; no se ejecuta reparación |
| `drop_catalog_index` | Comprueba política antes de unlink o unregister, cerrando el handle también al rechazar |
| `MutationService.insert/delete` | Guard anterior a callbacks o cambios en índices/Heap, fuera del manejo de reparación |
| `SqlEngine` directo | INSERT/DELETE rechazan; DELETE no crea spool para la tabla sellada |
| `SqlSession` / callbacks programáticos | Tras grants y revalidación del recurso, `prepare_write` consulta el runtime antes de flush, captura de undo o registro touched |
| `UndoStore` directo | Preflight de todos los archivos antes de copiar, limpiar sustituciones o restaurar; rechaza también una imagen anterior al sello |
| Mutaciones del owner demo | UPDATE, CREATE/DROP INDEX, DROP TABLE e importación/sustitución comprueban política antes de efectos en archivos o registro GUI |
| HTTP con `allow_writes=True` | INSERT, DELETE, UPDATE y DDL sobre la colección sellada retornan 422 `EXECUTION_REFUSED`; una tabla ordinaria acepta INSERT |
| Transacción con dos tablas | Escribe una mutable y después intenta la sellada: solo la mutable entra en captura/restauración, su cambio se revierte y la sellada conserva sus hashes |
| Reapertura del runtime y proceso nuevo | Restaura sello y secundarios; conserva filas, scores, índice/scan y rechazo de escritura |
| Owner alternativo y registro futuro | El owner con manifiesto rechaza Heaps sellados; ambos owners rechazan un registro textual reservado hasta implementar 4B |
| Integración espacial | Rechaza registrar mantenimiento espacial sobre Heap sellado; no se implementa co-publicación espacial/textual |

Las pruebas comparan SHA-256 de archivos completos, filas/RIDs y resultados,
y espían flush, capture, restore, callbacks y reparación. También inyectan
fallos en validación, capacidad de metadatos y publicación de Heap/secundarios.
La prueba de carrera detiene la publicación después de escribir página cero
y comprueba que un nuevo owner espere hasta completar el header y el sello.

## Uso acotado

```python
from engine.text import seal_text_collection, search_text

# Heap, TextIndex y todos sus secundarios abiertos offline tras cerrar el owner.
descriptor = seal_text_collection(heap, index, secondary_indexes=all_indexes)
assert heap.read_only
result = search_text(index, "base datos", model="BM25", storage=heap, limit=10)
```

`HeapFile.seal` es la primitiva de almacenamiento; el helper valida la
colección completa enumerada. El owner demo puede leer Heaps GUI preparados
con secundarios coherentes, pero todavía no posee lectores textuales ni
registra consultas MATCH. La asociación automática índice/tabla será 4B.
Una llamada Python a búsqueda sin `storage` sigue dependiendo de esa
asociación por el llamador, como en el bloque 3.

## Verificación reproducible

La verificación focalizada final aprobó **96 pruebas en 85.75 segundos**, con
advertencias como errores. Incluye **57 casos nuevos de sellado**, las pruebas
de undo/completion y los controles de arquitectura. No sumar sus resultados
a los de la regresión completa: son ejecuciones que se solapan.

Código y pruebas: commit **075e8bc**.

```powershell
New-Item -ItemType Directory -Force tmp | Out-Null
$env:TEMP = (Resolve-Path tmp).Path
$env:TMP = $env:TEMP
python -m pytest -q -W error -p no:cacheprovider --tb=short `
  --basetemp tmp/part03_4a_target `
  tests/text/test_sealing.py tests/transactions/test_undo_completion.py `
  tests/test_architecture.py

python -m pytest -q -W error -p no:cacheprovider --tb=short `
  --basetemp tmp/part03_4a_all
```

Usar un basetemp nuevo al repetir. TEMP/TMP se ajustan solo para el proceso
de validación. La prueba HTTP usa TestClient sobre el servicio real ASGI;
no se atribuye una verificación de navegador, UI ni servidor TCP a este bloque.

La regresión completa terminó con **3474 aprobadas, 4 omitidas y 1 fallo en
1391.61 segundos** (3479 casos recolectados). Las 96 focalizadas están incluidas;
no se suman al total. No se observaron fallos atribuibles a 4A. Resultado,
comando, hashes, scores y runtime se registran en el
[recibo de cierre](../docs/implementacion/evidencias/text_block4a_closure.json).
El fallo `test_sanitize_preserves_json_values_and_removes_local_paths` es
previo: el sanitizador de `039a063` reproduce en Windows la sustitución
`/workspace/mini-dbms\\output.json`, mientras el test espera el separador `/`.
El script y esa prueba permanecen sin cambios. El nombre local sí se elimina;
este bloque no altera ni relaja esa aserción. No se afirma suite completa verde.

## Cambios en módulos de etapas cerradas

| Módulos | Motivo y compatibilidad |
|---|---|
| storage/binary, file_header, organization, page_manager, Heap, contrato Storage y errores | Versionado optativo y guards; v1 sigue predeterminado, sin cambios de layout de páginas/RID |
| B+/hash y adaptadores, index_catalog | Cerrar rutas de mantenimiento, handles y borrado de archivos; algoritmos y formato lógico de índices conservados |
| maintenance/service y query/executor | Guard anterior a efectos, sin ampliar gramática ni semántica SQL |
| transactions/completion, runtime, undo, ownership, session | Rechazo antes de undo y exclusión de publicación durante el ciclo del owner/coordinator |
| api/database y engine/database/owner | Guards de mutaciones actuales y rechazo de recursos textuales que todavía no administran |
| spatial/index | No admitir mantenimiento mutable sobre una base sellada |
| Tests anteriores de header/undo y arquitectura | Versión desconocida pasa de 2 a 3; preflight físico de 20 bytes separado de los chunks de undo; dependencia text→indexes para publicación |

Se conserva la aceptación ESCI/100k de 1B; no se repitieron esos experimentos,
la matriz PostgreSQL GIN, ni benchmarks de rendimiento. El siguiente bloque
pendiente es **4B: integración del owner y SQL textual**.
