# Revisión y correcciones de las tareas 5.22–5.27

Fecha: **2026-09-10**. Alcance: construcción desde Heap, consistencia,
catálogo, instrumentación, integración diferencial y documentación.
Se preservan los cambios de los tres bloques de revisión anteriores.

## Criterios de aceptación

| Tarea | Resultado y evidencia |
|---|---|
| 5.22 — Construcción | Cumple tras añadir `flush()` antes del retorno/publicación. Scan activo excluye tombstones; fuente multipágina, claves variables, duplicados y unicidad; fallo de build/flush no publica metadatos nuevos. Todos los RID activos se recuperan después de reabrir. |
| 5.23 — Consistencia | Cumple dentro del contrato de mantenimiento por adaptador. Se corrige invalidación tras rollback fallido de inserción y se preservan todos los errores si la propia invalidación falla. Tanto búsqueda de RID como de registros comprueban Heap; apertura del adaptador valida cobertura. Insert/delete/update, recuperación por rebuild y reapertura probados. |
| 5.24 — Catálogo | Cumple con el catálogo en memoria adoptado, no con un catálogo global persistente nuevo. Definiciones nuevas se registran después de build validado/sincronizado; se recrean Catalog/Schema/IndexMetadata para reabrir. Validaciones previas, despacho B+/hash, publicación fallida, identidad física y eliminación fallida preservando metadata están cubiertos. |
| 5.25 — Métricas y errores | Cumple con ámbitos explícitos. Contadores físicos y tipados de creación/corrupción corregidos en 5.16–5.21; aquí se comprueban snapshots, reset, apertura y fallos. El tiempo de construcción incluye flush. Se reutilizan errores existentes y `BaseExceptionGroup`; no se añade jerarquía nueva. |
| 5.26 — Integración | Cumple tras ampliar el diferencial: oráculo completo y validador después de cada operación de la secuencia pequeña. Nuevo flujo Heap/build/mutación/Catalog/reapertura/rebuild en modalidades única y no única, con directorio multipágina y comparación de todos los RID activos. |
| 5.27 — Documentación | Cumple. Decisiones, uso y limitaciones consolidados en contexto/README; coordinación y matriz de auditoría corregidas a los 47 criterios reales. La Etapa 6 sigue sin iniciar. Suite completa aprobada. |

## Defectos corregidos

- `build_from_storage()` publicaba `build_complete=True` sin sincronizar antes
  de devolver el runtime. Ahora hace flush; si falla intenta invalidar y cerrar.
  `build_and_register_catalog_hash()` no llega a publicar esa definición.
- El rollback fallido de `insert_record()` no marcaba el índice incompleto.
  Delete/update sí intentaban marcarlo, pero un error de la marca ocultaba los
  errores previos. Un helper común conserva todos los errores, sincroniza la
  marca o cierra si no puede, y agrupa también interrupciones (`BaseException`).
- Un adaptador incompleto seguía permitiendo búsquedas/mutaciones. Ahora las
  rechaza explícitamente, pero permite inspeccionar y reconstruir.
- `search()` del adaptador delegaba directamente al núcleo y devolvía un RID
  reciclado por Heap aunque su clave actual fuera distinta. Ahora usa la misma
  resolución comprobada de `search_records()`. Abrir el adaptador además
  verifica cobertura completa: un hash internamente válido puede no coincidir
  con la tabla, por ejemplo si no se pudo escribir la marca de invalidez.
- El diferencial anterior validaba cada 30 pasos y comparaba solamente la clave
  tocada. Ahora valida y compara las 25 claves del oráculo en cada paso.
- README aún decía que no había eliminación de metadatos, y los documentos de
  coordinación repetían 46 criterios: se concilian con las 47 filas reales.

Código: [unclustered_hash.py](../engine/indexes/unclustered_hash.py),
[extendible_hash.py](../engine/indexes/extendible_hash.py).
Pruebas: [test_hash_final_review.py](../tests/indexes/test_hash_final_review.py),
[test_hash_restart_differential.py](../tests/indexes/test_hash_restart_differential.py),
además de la integración existente y los tres bloques anteriores.

## Recuperación y responsabilidades

1. Crear una tabla/Heap y registrar `TableMetadata`. Para una definición nueva,
   usar `build_and_register_catalog_hash`; el helper `build_catalog_hash` sirve
   para una **definición previamente registrada**, no para publicar un runtime
   incompleto como si estuviera disponible.
2. Mantener las filas mediante el adaptador y usar el RID devuelto por update.
   Cerrar el adaptador no cierra el Heap prestado. La aplicación debe coordinar
   los demás índices de esa tabla; no existe mantenimiento automático múltiple.
3. Si falla el rollback, inspeccionar el grupo de errores. Una instancia abierta
   marcada incompleta permite `rebuild()`. Si se cerró o la marca no permite
   abrir, reconstruir un índice nuevo desde un Heap válido y registrar esa
   nueva definición solo tras éxito. Resolver primero violaciones de unicidad.
4. Reabrir con Heap/Catalog/metadata nuevos. El header del índice contiene sus
   parámetros persistentes; el catálogo en memoria se reconstruye por la
   aplicación. Ejecutar `validate_structure()` para comprobar también cobertura.

El RID sigue siendo `(page_id, slot_id)` sin generación. Verificar clave actual
detecta un slot reciclado para **otra clave**, no la identidad histórica de una
fila nueva que use exactamente el mismo RID y clave. Cambios directos al Heap
exigen reconstruir antes de consultar; no se promete detección ABA, remapeo
automático ni notificaciones de mutación. Heap no ofrece reorganización global
con remaps; reconstruir contra una fuente explícita cubre cambios externos.

La frase de la Definition of Done sobre persistencia del Catalog se interpreta
según la decisión estable: persistencia del descriptor físico y reapertura
mediante definiciones reconstruidas, **no serialización del registro global**.
No se modifica esa arquitectura ni se añade un requisito académico nuevo.

## Significado de las mediciones

- Contadores de `PageManager`: transferencias completas de páginas, no accesos
  a caché, escrituras parciales fallidas, cabecera física de archivo o fsync.
- Contadores tipados: payloads de directorio/bucket; la inicialización de una
  página asignada se ve en el agregado, no se duplica como escritura tipada.
- Eventos estructurales: splits/doublings publicados, no planes rechazados.
- `reset_counters()` reinicia contadores, no estructura ni el snapshot de build.
- `HashBuildMetrics`: coste hasta retornar el constructor, incluido su flush;
  se pierde al reabrir. No incluye validaciones posteriores de la aplicación.
- `rebuild()` devuelve la medición de construcción del candidato, no la suma
  de validación adicional, cierre, reemplazo y reapertura. El gestor reemplazado
  inicia otra sesión física; los eventos estructurales comienzan con los del
  candidato. Medir toda la reconstrucción requiere temporizar la llamada.
- Consultas del adaptador añaden lecturas reales en Heap; para comparar B+ y
  hash se debe medir la misma capa y separar validación/build de la consulta.

No se presentan números de benchmark ni afirmaciones de rendimiento. La E/S
sin WAL sigue sin atomicidad entre archivos o páginas. Si el sistema operativo
rechaza también invalidación/cierre, no hay garantía de que la marca llegue al
disco: el fallo se reporta, no se simula una recuperación exitosa.

## Verificación

Línea base: **1747 pruebas** del bloque anterior. La primera tanda reprodujo
**9 fallos, 5 aprobaciones y 1 error de teardown**; este último provino de un
runtime devuelto inesperadamente antes de la corrección del flush, que la
prueba negativa todavía no cerraba. Las pruebas de rollback que fallaban antes
de su cierre también emitieron avisos de recursos en esa ejecución inicial.
Después de corregir, la tanda con integración/diferencial pasó **26 pruebas**.
La tanda nueva definitiva contiene **25 pruebas**, todas aprobadas.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q engine tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

- Suite final: **1772 aprobadas en 125,99 s**, con advertencias como errores,
  sin omisiones ni xfails; incluye arquitectura/importaciones y regresiones.
- `compileall`, `pip check` y `git diff --check`: correctos.

Resultado: **5.22–5.27 cumplen sus criterios bajo las decisiones y límites
explicados arriba**. Los cuatro bloques de revisión quedan completos; la
[auditoría](ETAPA_05_AUDIT.md) concilia los 47 criterios y conserva por separado
la ejecución histórica. No se implementó Etapa 6 ni funcionalidad opcional.

Los casos nuevos añaden fallos de rollback/marca, RID reciclado, publicación y
flush, validaciones del catálogo, fallo de drop, rollback exitoso, reconstrucción
de un runtime incompleto, conservación del original ante rebuild fallido y
ámbitos de métricas. La integración nueva recrea todos los componentes cuatro
veces por modalidad y valida cada mutación; el hash controlado es solo de prueba.
