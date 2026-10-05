import csv
from fractions import Fraction
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
ROWS = json.loads((OUT / 'REQUISITOS_FIJADOS.json').read_text(encoding='utf-8'))
BY_ID = {row['id']: row for row in ROWS}


def ref(path, token=None):
    file = ROOT / path
    if not file.is_file():
        raise ValueError(path)
    lines = file.read_text(encoding='utf-8').splitlines()
    line = next((i for i, value in enumerate(lines, 1) if token in value), None) if token else 1
    if line is None:
        raise ValueError((path, token))
    return f'{path}:{line}' + (f' ({token})' if token else '')


def mark(identifier, state, current, evidence, evaluation, problems, correction, recommendation, validation,
         dependencies, verified=None, implemented=None, pending=None):
    row = BY_ID[identifier]
    count = len(row['criterios'])
    verified = [1] * count if verified is None and state == 'COMPLETO' else ([0] * count if verified is None else verified)
    implemented = verified.copy() if implemented is None else implemented
    pending = [0] * count if pending is None else pending
    assert len(verified) == len(implemented) == len(pending) == count, identifier
    assert all(v <= i and p <= i and v+p <= i for i, v, p in zip(implemented, verified, pending)), identifier
    row.update(estado=state, estado_actual=current, evidencia=evidence, evaluacion=evaluation,
               problemas=problems, correccion=correction, implementacion_recomendada=recommendation,
               validacion=validation, dependencias=dependencies,
               criterios_implementados=implemented, criterios_verificados=verified,
               criterios_pendientes=pending)


mark('1.1.1', 'COMPLETO', 'HeapFile codifica Record en slotted pages de 4096 bytes y mantiene metadatos persistentes.',
     [ref('engine/storage/heap_file.py','def insert('), ref('engine/storage/page_manager.py','class PageManager'), ref('tests/storage/test_heap_persistence.py')],
     'Cumple almacenamiento propio en páginas y reapertura con gestores nuevos; las pruebas de persistencia y E/S pasan.',
     'No se reprodujo un defecto del requisito. No ofrece recuperación automática ante caída, que el PDF no exige.',
     'Ninguna corrección obligatoria identificada.', 'Conservar PageManager, RecordCodec y la estructura paginada existente.',
     'Insertar múltiples páginas, cerrar, abrir y comparar filas y RIDs; ver suite estricta y persistencia en procesos independientes.', 'Codecs y PageManager.')
mark('1.1.2', 'INCORRECTO', 'Inserta sin ordenar por clave; selecciona la primera página apta mediante HeapFreeSpaceTracker.',
     [ref('engine/storage/heap_file.py','def insert('), ref('engine/storage/heap_file.py','def scan('), ref('tests/storage/test_heap_free_space.py','def test_tracker_chooses_lowest'), 'docs/auditoria/evidencias/heap_orden_llegada.json'],
     'Bajo la lectura literal de almacenamiento en orden de llegada del PDF, la carga inicial ya falla con filas variables: entrada 1,2,3; páginas/RIDs y scan 1,3,2. Dos criterios de tres están satisfechos.',
     'Las filas de 3200,3200,100 bytes colocan la tercera en el hueco nunca ocupado de la primera página. No hubo borrados; reapertura conserva el mismo orden físico. Los tests validan first-fit sin contrastar este requisito.',
     'Priorizar la última página para carga nueva y distinguir huecos reutilizados tras borrado de espacio sobrante de páginas anteriores. Documentar la compatibilidad entre llegada inicial y reutilización posterior.',
     'Cambiar solo la selección de página en HeapFile.insert y su información de reutilización; conservar tracker, codecs y RIDs existentes. Aplicar la política a nuevas inserciones sin reordenar archivos antiguos; para corregir una carga antigua usar su fuente original y reconstruir índices.',
     'Añadir regresión 3200/3200/100 sin borrados: colocación y scan físico 1,2,3 antes/después de abrir; mantener tests de reutilización real. No imponer ORDER BY a un SELECT sin orden explícito.',
     '1.1.1 y 1.1.3; revisar consumidores del tracker y adaptadores de índices. Si el docente interpreta llegada solo como ausencia de orden por clave, registrar esa aclaración y reevaluar este único criterio.',
     verified=[0,1,1], implemented=[1,1,1])
mark('1.1.3', 'COMPLETO', 'Actualiza espacio libre tras borrado; reutiliza slots, compacta cuando hace falta y reconstruye el directorio al abrir.',
     [ref('engine/storage/heap_file.py','def _rebuild_free_space('), ref('engine/storage/heap_file.py','def delete('), ref('tests/storage/test_heap_free_space.py')],
     'Las pruebas comprueban bytes recuperables y reutilización después de reapertura; los experimentos registran crecimiento real.',
     'El directorio es reconstruible en memoria; su reconstrucción lee las páginas. Es un coste de arranque, no incumplimiento.',
     'Ninguna corrección obligatoria identificada.', 'Conservar el directorio reconstruible y las invariantes de slots.',
     'Borrar registros, insertar tamaños que caben en huecos, verificar páginas no añadidas innecesariamente y repetir tras abrir.', '1.1.1.')
mark('1.1.4', 'COMPLETO', 'PagedSequentialFile busca página por clave, redistribuye/divide y desplaza el sufijo del archivo contiguo.',
     [ref('engine/storage/paged_sequential_file.py','def insert('), ref('tests/storage/test_paged_sequential_split.py'), ref('tests/storage/test_paged_sequential_binary_search.py')],
     'Inserción, orden con duplicados, divisiones y reapertura están verificados. La implementación es propia.',
     'Los desplazamientos pueden cambiar RIDs y aumentar el coste. Los adaptadores existentes reconstruyen índices para mantener corrección.',
     'No reemplazar el almacenamiento por este coste. Mejorar mantenimiento solo si la evidencia experimental justifica el cambio.',
     'Conservar la política actual; para optimización futura, publicar cambios de RID de forma explícita y actualizar todos los consumidores.',
     'Cargar orden inverso y aleatorio; forzar divisiones de dos/tres páginas y comparar scan ordenado antes y después de abrir.', '1.1.1; comparador y codecs.')
mark('1.1.5', 'COMPLETO', 'La eliminación crea tombstones, ajusta conteos y excluye filas del scan sin compactación inmediata.',
     [ref('engine/storage/paged_sequential_file.py','def delete('), ref('tests/storage/test_paged_sequential_maintenance.py')],
     'El borrado es lazy y persistente, con recuperación posterior mediante reorganización.',
     'No se reprodujo un incumplimiento del requisito.', 'Ninguna corrección obligatoria identificada.',
     'Conservar tombstones y validación de RIDs.', 'Comprobar filas excluidas, desperdicio conservado y reapertura antes de reorganizar.', '1.1.4.')
mark('1.1.6', 'COMPLETO', 'Mide desperdicio por bytes, aplica umbral y crea un reemplazo compacto validado con métricas.',
     [ref('engine/storage/paged_sequential_file.py','def should_reorganize('), ref('engine/storage/paged_sequential_file.py','def reorganize('), ref('engine/indexes/clustered_bplus.py','def reorganize('), ref('tests/storage/test_paged_sequential_maintenance.py')],
     'Hay una estrategia real de activación y reorganización. El 30% del PDF es un ejemplo, no una obligación universal.',
     'Mover registros exige reconstrucción de asociaciones. La ruta agrupada la coordina; no invocar reorganización cruda con índices activos sin mantenimiento.',
     'Ninguna corrección del algoritmo identificada; mantener las rutas públicas coordinadas.',
     'Conservar reemplazo validado y reconstrucción de índices afectados.',
     'Borrar más del umbral, reorganizar, verificar igualdad de filas, menor desperdicio, índices y reapertura.', '1.1.4, 1.1.5 y mantenimiento de índices.')
mark('1.2.1', 'COMPLETO', 'ClusteredBPlusIndex asocia un B+ persistente propio a un secuencial físicamente ordenado por la misma clave.',
     [ref('engine/indexes/clustered_bplus.py','class ClusteredBPlusIndex'), ref('engine/indexes/bplus_tree.py','def insert('), ref('tests/indexes/test_clustered_bplus.py')],
     'Cumple agrupamiento físico, búsquedas, mutación y persistencia. El PDF no exige almacenar las filas dentro de las hojas del B+.',
     'Reconstruye el índice en cada inserción; en 100k una inserción tarda 373–432 s en los resultados históricos. Las lecturas por RID tampoco agrupan páginas.',
     'Es una limitación de rendimiento, no una estructura conceptualmente inválida. Completar primero la medición de borrados; evitar reescritura sin necesidad.',
     'Mantener el adaptador. Como mejora, propagar cambios concretos de RID o agrupar mantenimiento de lotes con publicación segura.',
     'Verificar igualdad/rango contra scan, divisiones/fusiones, inserción con RIDs movidos, reorganización y reapertura.', '1.1.4 y núcleo B+ compartido.')
mark('1.2.2', 'COMPLETO', 'UnclusteredBPlusIndex conserva asociaciones clave/RID hacia Heap independiente.',
     [ref('engine/indexes/unclustered_bplus.py','class UnclusteredBPlusIndex'), ref('engine/indexes/bplus_tree.py','def range_entries('), ref('tests/indexes/test_unclustered_bplus.py'), ref('tests/indexes/test_bplus_tree_delete.py')],
     'Igualdad, rango, splits, reparación de underflow, duplicados y reapertura tienen cobertura real.',
     'Leer una página por RID penaliza rangos amplios. No significa que el índice esté incorrecto.', 'Ninguna corrección obligatoria identificada.',
     'Reutilizar el núcleo B+; una futura lectura por lotes puede agrupar RIDs por página sin perder el orden solicitado.',
     'Comparar asociaciones con un mapa independiente y resultados de rango con un scan tras operaciones aleatorias y reinicios.', '1.1.1 y núcleo B+.')
mark('1.2.3', 'COMPLETO', 'ExtendibleHashIndex tiene directorio paginado, profundidad global/local, split, duplicación y hash determinista.',
     [ref('engine/indexes/extendible_hash.py','class ExtendibleHashIndex'), ref('tests/indexes/test_hash_restart_differential.py'), ref('tests/indexes/test_hash_growth_review.py')],
     'Cumple hashing extensible propio, búsquedas, colisiones, borrado y persistencia. Merge/shrink no son obligaciones explícitas del PDF.',
     'La profundidad tiene un límite y las colisiones no separables se rechazan de forma controlada. Los límites están cubiertos.',
     'Ninguna corrección obligatoria identificada.', 'Mantener el directorio y validación existentes; no atribuirle capacidad de rango.',
     'Forzar colisiones, split con/sin doubling, borrar asociaciones exactas y comparar con diccionario tras reapertura.', '1.1.1; codec determinista de claves.')
mark('1.2.4', 'COMPLETO', 'ExternalSort genera runs paginados y realiza merge k-way con heap, varias pasadas y presupuesto explícito.',
     [ref('engine/operators/sorting.py','def _generate_runs('), ref('engine/operators/sorting.py','def _merge_rows('), ref('engine/query/planner.py','ExternalSort'), ref('tests/integration/test_stage6_differential.py','def test_external_sort_matches')],
     'ORDER BY usa el operador real desde SQL; los tests fuerzan derrame y comparan secuencias estables con sorted.',
     'El presupuesto modela objetos y buffers; no es medición RSS del proceso. No presentarlo como memoria física observada.',
     'Ninguna corrección obligatoria identificada.', 'Conservar runs y merge; usar RSS separadamente cuando un experimento pida memoria real.',
     'Presupuesto mínimo, múltiples runs y pasadas, claves repetidas, filas anchas, salida ordenada y temporales eliminados tras fallo/cierre.', 'Scans, RowLayout, temporales y ExecutionContext.')
mark('1.2.5', 'COMPLETO', 'ExternalHashGroup particiona a disco, acumula agregados y resuelve skew mediante rutas acotadas.',
     [ref('engine/operators/aggregation.py','class ExternalHashGroup'), ref('engine/operators/partitioning.py'), ref('tests/integration/test_stage6_differential.py','def test_external_grouping_matches')],
     'Cumple la alternativa de hashing externo y está conectado al planner SQL; no hace falta exigir también la alternativa por índices.',
     'El PDF no fija lista completa de agregados SQL ni semántica de NULL. El subconjunto implementado tiene límites explícitos.',
     'Ninguna corrección obligatoria identificada.', 'Mantener agregados y particionado propios; reutilizar estados mergeables.',
     'Comparar con agrupación por diccionario, incluyendo AVG ponderado, claves dominantes, vacío, duplicados y presupuestos distintos.', '1.2.4 para fallbacks que necesiten ordenar; particiones y expresión tipada.')
mark('1.2.6', 'COMPLETO', 'GraceHashJoin y rutas indexadas realizan equijoins reales; NestedLoopJoin proporciona una referencia alternativa.',
     [ref('engine/operators/join.py','class GraceHashJoin'), ref('engine/operators/index_strategies.py','class IndexNestedLoopJoin'), ref('tests/integration/test_stage6_differential.py','def test_grace_join_matches')],
     'Los resultados preservan multiplicidad y las pruebas fuerzan particiones externas y skew. Cumple la optimización requerida.',
     'Solo se soportan joins del subconjunto acordado. El PDF no exige todos los joins del estándar.', 'Ninguna corrección obligatoria identificada.',
     'Mantener GraceHashJoin y estrategia indexada elegible; no sustituirlos por operaciones de un DBMS externo.',
     'Comparar como multiconjunto contra bucles independientes, con duplicados, tablas vacías, skew y todas las rutas seleccionables.', 'Scans, particionado y acceso por igualdad.')
mark('1.3.1', 'COMPLETO', 'Lexer y parser manuales producen AST; binder resuelve catálogo; planner construye operadores propios.',
     [ref('engine/query/parser.py','class _Parser'), ref('engine/query/binder.py'), ref('engine/query/planner.py'), ref('tests/query/test_stage7_acceptance.py','def test_reproducible_selection_matrix')],
     'SELECT, proyección y condiciones soportadas se ejecutan por el motor. Errores sintácticos/semánticos se verificaron también por HTTP y navegador.',
     'LIMIT, funciones espaciales y rankings están ausentes. Es correcto para Parte 1, pero bloquea extensiones posteriores.',
     'No exigir un SQL completo; ampliar AST/binder/planner de forma localizada al implementar los requisitos posteriores.',
     'Conservar descenso recursivo y spans; incorporar nodos tipados para capacidades multimodales.',
     'Oráculos de resultados, comparaciones con/sin índices, SQL inválido, límites de parser y recuperación de la consulta siguiente.', 'Catálogo, almacenamiento y operadores.')
mark('1.3.2', 'COMPLETO', 'INSERT valida columnas y tipos, escribe una vez y mantiene índices mediante MutationService bajo sesión.',
     [ref('engine/maintenance/service.py','def insert('), ref('engine/query/executor.py','class SqlEngine'), ref('tests/query/test_executor_writes.py')],
     'Escritura real, mantenimiento y publicación/rollback están cubiertos; la API muestra resultados provisionales correctamente.',
     'La ruta cruda de SqlEngine sin coordinador tiene garantías distintas a la sesión pública. No usarla como fachada concurrente.',
     'Ninguna corrección obligatoria identificada.', 'Mantener las escrituras bajo el owner y SqlSession; reservar rutas sin coordinador para pruebas/demos controladas.',
     'Insertar tipos correctos/incorrectos, duplicados de PK, confirmar/revertir y comprobar todos los índices tras reapertura.', '1.1, 1.2 y 1.4.')
mark('1.3.3', 'COMPLETO', 'DELETE descubre RIDs en un spool acotado antes de escribir y coordina borrado y reparación de índices.',
     [ref('engine/maintenance/service.py','class DeleteTargetSpool'), ref('engine/maintenance/service.py','def delete('), ref('tests/query/test_mutation_maintenance.py')],
     'Los targets exactos evitan invalidación del scan durante mutación; las sesiones añaden undo y aislamiento.',
     'La compensación aislada del servicio conserva prefijos en fallos ordinarios; no equivale al rollback coordinado. El sistema documenta ambas rutas.',
     'Ninguna corrección obligatoria identificada.', 'Conservar discovery cerrado y verificación RID/registro; ejecutar públicamente mediante sesiones.',
     'Borrado selectivo/no coincidente, fallos inyectados y rollback; comparar almacenamiento e índices y comprobar limpieza del spool.', '1.3.1 y mantenimiento de índices/transacciones.')
mark('1.4.1', 'COMPLETO', 'BEGIN/END agrupan sentencias en SqlSession; END publica commit y ROLLBACK restaura imágenes físicas.',
     [ref('engine/transactions/session.py','class SqlSession'), ref('engine/transactions/completion.py'), ref('tests/transactions/test_sql_integration.py')],
     'Agrupación entre peticiones reales y aislamiento por token fueron corroborados por HTTP y Chromium.',
     'No hay WAL ni recuperación automática de crash. Se detecta estado no limpio; el PDF no obliga a esos mecanismos.',
     'Ninguna corrección obligatoria identificada.', 'Conservar owner, locks y before-images; declarar los límites de fallo.',
     'BEGIN con varias mutaciones, END, otra sesión observando, rollback y reapertura conservando solo lo confirmado.', '1.3 y gestor de transacciones.')
mark('1.4.2', 'COMPLETO', 'Locks S/X por tabla, cola FIFO, wait-for graph, víctima de deadlock y latches físicos.',
     [ref('engine/transactions/locks.py','class LockManager'), ref('tests/transactions/test_locks.py'), ref('tests/transactions/test_controlled_evidence.py')],
     'Múltiples sesiones comparten el owner; los lectores/writers en conflicto esperan en el gestor, sin serializar todas las peticiones HTTP.',
     'Los locks y el lease son de un solo proceso. Ejecutar varios workers sobre la misma base queda fuera del contrato actual.',
     'Mantener un worker por base. Un bloqueo entre procesos sería una ampliación de despliegue, no requisito del PDF.',
     'Conservar locks del motor y cancelar/abortar mediante el ciclo de vida existente.',
     'Lectores compatibles, escritor excluyente, deadlock, timeout, cancelación y liberación solo después del estado terminal.', '1.4.1; owner único por proceso.')
mark('1.4.3', 'COMPLETO', 'La demo ejecuta la misma operación de incremento sin protección, protegida y en serie usando threads.',
     [ref('demos/transactions_demo.py'), ref('tests/transactions/test_controlled_evidence.py'), 'docs/auditoria/evidencias/demo_threads.json'],
     'Se ejecutó nuevamente: resultado sin protección 1, protegido 2 y referencia serial 2; evidencia de intentos y conflictos real.',
     'El adaptador inseguro está deliberadamente fuera del motor productivo.', 'Ninguna corrección obligatoria identificada.',
     'Preservar el calendario determinista y explicar qué protección se omite en la demostración.',
     'Dos operaciones terminadas, race visible y resultado protegido idéntico al serial; ejecución con warnings como errores.', '1.4.1 y 1.4.2.')

for identifier, current, sources, evaluation, problems, recommendation, validation in [
    ('1.5.1', 'FilesPanel muestra tablas, columnas, tipos, organización e índices desde /api/tables.',
     [ref('frontend/src/components/FilesPanel.tsx'), ref('api/database.py','def describe_table(')],
     'Tablas y estructura se observaron en Chromium real. Cuenta datos físicos y advierte sobre valores provisionales.',
     'Otra pestaña puede mantener conteos antiguos hasta refrescar; no afecta los resultados SQL ni la estructura mostrada.',
     'Como mejora, refrescar metadatos al volver a enfocar o después de detectar una nueva versión; conservar la advertencia de provisionalidad.',
     'Cargar GUI, seleccionar tabla y contrastar esquema con /api/tables; verificar refresco entre pestañas al corregir esa mejora.'),
    ('1.5.2', 'QueryPanel ofrece textarea SQL, presets y controles que envían opciones reales al motor.',
     [ref('frontend/src/components/QueryPanel.tsx'), ref('frontend/src/api.ts','runQuery')],
     'Editor, envío, errores con línea/columna y recuperación pasaron en navegador.', 'No se reprodujo un defecto del requisito.',
     'Conservar API y gating de solicitudes; ampliar presets solo cuando existan consultas multimodales reales.',
     'Enviar SELECT válido/inválido y comprobar que cada envío se ejecuta una vez.'),
    ('1.5.3', 'ResultsPanel renderiza filas reales y distingue comandos, explicaciones, vacío y previews parciales.',
     [ref('frontend/src/components/ResultsPanel.tsx'), ref('api/serialization.py')],
     'Las filas del navegador coinciden con el JSON y los casos HTTP; rollback mostró resultado vacío correcto.',
     'Las previews tienen límite de filas/bytes; el panel lo declara. No equivale a materializar todo el resultado.',
     'Conservar límites y estados de completitud; añadir vistas especializadas cuando se implementen nuevos tipos.',
     'Comparar celdas con resultados del motor, vacío, error y respuesta truncada.'),
    ('1.5.4', 'PlanPanel distingue plan preparado y observado, muestra árbol de operadores, índices y métricas reales.',
     [ref('frontend/src/components/PlanPanel.tsx'), ref('api/serialization.py','def runtime_json(')],
     'Activar/desactivar índices cambió IndexScan a TableScan sin alterar filas; ORDER BY mostró ExternalSort.',
     'Las métricas de preview pueden ser parciales y el panel lo indica; la memoria reservada es un modelo de ejecución.',
     'Conservar serialización de descriptores reales; para nuevas modalidades crear operadores/reportes reales antes de añadir etiquetas UI.',
     'Contrastar el árbol con el runtime, índices abiertos y orden de ejecución; verificar EXPLAIN sin confundirlo con ejecución.')]:
    mark(identifier, 'COMPLETO', current, sources + ['docs/auditoria/evidencias/navegador.json'], evaluation,
         problems, 'No se identificó una corrección obligatoria del requisito; las mejoras se priorizan aparte.',
         recommendation, validation, 'API, serialización y SqlEngine/SqlSession.')

mark('1.6.1', 'COMPLETO', 'Hay 143 mediciones de archivos: 55 por tamaño 1k/10k y 33 en 100k, con cargas, búsquedas, disco y reorganización.',
     [ref('benchmarks/file_organization.py','def run('), ref('docs/EXPERIMENTOS.md','## 2.'), 'benchmarks/results/part1_results*.jsonl', 'docs/auditoria/evidencias/experimentos_auditados.json'],
     'Datos y repeticiones requeridos presentes; las tablas se regeneraron desde los JSONL. El harness se repitió a 1k como diagnóstico.',
     'No se volvieron a ejecutar todas las corridas. Las de 1k/10k registran working tree sucio; su snapshot exacto no queda identificado solo por el commit.',
     'Guardar un snapshot o manifiesto por archivo para futuras mediciones; conservar los resultados originales y su procedencia.',
     'Reutilizar datos reproducibles y el harness. Registrar fsync/caché y entorno explícitos; no mezclar la repetición diagnóstica con resultados oficiales.',
     'Cobertura de operaciones y tamaños, búsquedas con conteos esperados, repetición selectiva y tablas idénticas a las publicadas.', '1.1 y harness de medición propio.')
mark('1.6.2', 'COMPLETO', 'Hay 312 mediciones de índices; igualdad, rango, orden, construcción y disco están registrados para las tres estructuras.',
     [ref('benchmarks/indexes.py','while done < workload_operations'), ref('docs/EXPERIMENTOS.md','**Agrupado frente a no agrupado.**'), 'docs/auditoria/evidencias/experimentos_auditados.json'],
     'La comparación mínima del PDF está cubierta: a 1k el agrupado sí realiza 17–18 borrados y 18–19 inserciones por repetición. La matriz ampliada a 100k no demuestra borrados frecuentes: inserted=1, deleted=0.',
     'El límite de 60 s se evalúa entre operaciones; una inserción duró 373–432 s. A 10k solo hubo un borrado por repetición. La tasa mide workloads distintos.',
     'Como mejora de la comparación ampliada, medir INSERT y DELETE por separado y completar un prefijo mixto común; etiquetar corridas censuradas y operaciones completadas.',
     'Conservar harness e índices. Añadir una medición explícita de borrado agrupado, o un lote mixto mínimo completo, aceptando y reportando su coste sin timeout ficticio.',
     'Las corridas 1k acreditan ambas mutaciones; al ampliar la evaluación a 100k completar borrados y validar filas/índices al final. No extrapolar el dato faltante. El PDF no fija explícitamente tamaños para este subexperimento de índices.',
     '1.2.1–1.2.3; no requiere reescribir el B+ antes de medir.')
mark('1.6.3', 'COMPLETO', 'Existen once PNG y tablas generadas por benchmarks.report.',
     [ref('benchmarks/report.py','def render('), ref('docs/experimentos/resultados.md'), 'docs/auditoria/evidencias/reporte_contrastado.json'],
     'La regeneración con los tres JSONL oficiales produce tablas textualmente idénticas y once gráficos.',
     'El comando sin --results toma solo el archivo de 1k/10k; para reproducir todo deben pasarse los tres archivos. La gráfica de carga mixta hereda su limitación.',
     'Documentar el comando completo o ajustar el default en una corrección futura; revisar la leyenda de la carga mixta.',
     'Conservar generación desde datos crudos; no dibujar mediciones inexistentes.',
     'Regenerar y comparar tablas; inspeccionar etiquetas, unidades, series de 100k y notas de censura.', '1.6.1 y 1.6.2.')
mark('1.6.4', 'COMPLETO', 'EXPERIMENTOS contiene ventajas y desventajas de Heap, secuencial, ambos B+ y hash.',
     [ref('docs/EXPERIMENTOS.md','## 5.')], 'La tabla requerida existe y coincide con comportamiento y cifras observadas.',
     'El agrupado se describe con throughput de una sola inserción a 100k. Mantener explícito ese alcance al comparar mantenimiento.',
     'Ajustar esa celda tras completar 1.6.2.', 'Conservar recomendaciones específicas de esta implementación y sus limitaciones.',
     'Cada ventaja/desventaja debe enlazar a un comportamiento probado o medición concreta, distinguiendo inferencias.', '1.6.1 y 1.6.2.')
mark('1.6.5', 'COMPLETO', 'Hay conclusiones por organización e índice, con cifras y límites de selectividad.',
     [ref('docs/EXPERIMENTOS.md','## 6.')], 'Las recomendaciones están respaldadas por búsquedas, carga, espacio y rangos medidos.',
     'Tres tamaños no demuestran complejidad asintótica; la atribución del coste de hash a splits no fue aislada. El cruce 4–5% se reconoce como estimación.',
     'Reformular O(1) como comportamiento observado/expectativa bajo supuestos y la atribución causal como hipótesis; no añadir mediciones inventadas.',
     'Separar conclusiones empíricas, complejidad teórica y estimaciones; conservar las recomendaciones útiles.',
     'Trazar cada cifra a la mediana y cada afirmación causal a evidencia o etiqueta de inferencia.', '1.6.1–1.6.4.')

for identifier, current, sources, evaluation, problems, recommendation, validation in [
    ('2.1.1', 'RTree implementa nodos/MBR, quadratic split, elección de subárbol y persistencia JSON versionada con checksum.',
     [ref('engine/spatial/rtree.py','class RTree'), ref('engine/spatial/rtree.py','def _split('), ref('engine/spatial/index.py','class SpatialIndex')],
     'Es un R-Tree propio multinivel, asociado a RIDs del Heap y validado estructuralmente; el PDF no exige R-Tree paginado.',
     'El árbol completo vive en RAM; INSERT guarda todo el JSON y DELETE reconstruye todo el árbol. No confundir persistencia con paginación externa.',
     'Reutilizar el núcleo; medir memoria y mantenimiento antes de considerar nodos paginados o actualización incremental.',
     'Inserciones con varios niveles, ocupación, MBR, cobertura de RIDs, duplicados y reapertura; prueba actual sobre Heap de 100k.'),
    ('2.1.2', 'radius usa bounds conservadores y una comprobación exacta de distancia; existe SpatialScan independiente del traversal.',
     [ref('engine/spatial/rtree.py','def radius('), ref('engine/spatial/index.py','def scan_radius(')],
     'Resultados indexados y scan coinciden; se comprobó además contra un cálculo matemático independiente con Heap real.',
     'La cota Haversine solo usa latitud: es segura, pero puede podar poco en distribuciones de latitud similar.',
     'Conservar el residual exacto. Mejorar la cota únicamente con una prueba de que nunca excede la distancia mínima real.',
     'Radios 0/1/5/10 km, límites incluidos/excluidos, centros en los bordes y consultas dentro del dominio admitido.'),
    ('2.1.3', 'knn hace best-first sobre MBR y heap acotado de candidatos; ordena por distancia e ID.',
     [ref('engine/spatial/rtree.py','def knn('), ref('engine/spatial/index.py','def scan_knn(')],
     'k, empates, duplicados y k mayor que N tienen pruebas; el probe 100k comprueba k=10/50/100 con referencia independiente.',
     'El resultado materializa hasta k filas y no tiene presupuesto de consultas espaciales equivalente al pipeline relacional.',
     'Conservar ranking estable; al exponer por HTTP imponer límites de salida y definir un operador TopK con métricas reales.',
     'Comparar IDs y orden con ordenamiento exhaustivo, k=0/1/N/N+1, empates y ambas métricas.'),
    ('2.1.4', 'El índice filtra MBR y Polygon.contains aplica predicado exacto, con borde incluido y polígonos simples cóncavos.',
     [ref('engine/spatial/geometry.py','class Polygon'), ref('engine/spatial/rtree.py','def polygon(')],
     'Cumple intersección de puntos con polígonos. El PDF no exige polígonos con agujeros o geometrías arbitrarias.',
     'El dominio es local y la convención del borde debe conservarse al conectar SQL, mapa y GiST.',
     'Reutilizar Polygon y MBR; validar datos y revelar la convención de borde en la interfaz.',
     'Puntos interiores, exteriores dentro del MBR, vértices, aristas, concavidad, inversión de orientación y polígonos inválidos.'),
    ('2.1.5', 'Distancia planar en metros mediante proyección local fija alrededor de Lima.',
     [ref('engine/spatial/geometry.py','def local_xy('), ref('engine/spatial/geometry.py','def distance('), ref('engine/spatial/metadata.py','ORIGIN =')],
     'Implementa Euclidiana en un plano declarado, no sobre grados sin conversión. Las pruebas comprueban unidades y ranking diferente de Haversine.',
     'Solo se admiten coordenadas del dominio local fijado. El PDF no impone cobertura mundial; debe mostrarse ese límite.',
     'Mantener proyección y unidades; al ampliar dominio, introducir una convención/proyección explícita y una nueva versión compatible.',
     'Casos analíticos norte/este, identidad, simetría y comparación con cálculo planar independiente.'),
    ('2.1.6', 'distance implementa Haversine esférica en metros con radio medio WGS84 declarado.',
     [ref('engine/spatial/geometry.py','def distance('), ref('engine/spatial/metadata.py','EARTH_RADIUS_METRES =')],
     'La fórmula, unidad y uso en consultas son correctos en el dominio; el probe utiliza ángulo entre vectores unitarios como referencia distinta.',
     'El comparador PostgreSQL debe usar esfera, radio compatible y residual exacto; el modo spheroid por defecto no sería equivalente.',
     'Conservar Haversine y hacer explícito use_spheroid=false en futuras mediciones GiST.',
     'Distancia cero, norte/este, equivalencia con referencia esférica y orden en radio/k-NN.')]:
    mark(identifier, 'COMPLETO', current, sources + [ref('tests/spatial/test_e2_engine.py'), 'docs/auditoria/evidencias/espacial_100k_real.json'],
         evaluation, problems, 'Ninguna corrección obligatoria del algoritmo identificada; atender los límites señalados al integrarlo.',
         recommendation, validation, 'Heap estable, SpatialMapping y owner/sesiones para consultas públicas.')

mark('2.2.1', 'NO IMPLEMENTADO', 'La GUI actual contiene cuatro paneles relacionales; no hay componente ni dependencia de mapa.',
     [ref('frontend/src/App.tsx'), ref('frontend/package.json'), 'docs/auditoria/evidencias/navegador.png'],
     'Los puntos almacenados no se pueden visualizar en un mapa interactivo.', 'Existe preparación espacial en backend, pero no visualización espacial.',
     'Añadir un panel de mapa conectado a datos reales del motor.',
     'Usar una biblioteca de mapa como transporte visual, con latitud/longitud explícitas, navegación y carga acotada de puntos.',
     'Abrir una tabla espacial y ver sus posiciones reales; pan/zoom no deben alterar identidades ni invertir ejes.', '2.3 y una ruta HTTP espacial.')
mark('2.2.2', 'NO IMPLEMENTADO', 'No hay selección ni resaltado espacial en frontend.',
     [ref('frontend/src/App.tsx'), 'docs/auditoria/evidencias/inventario_codigo.json'],
     'La salida espacial tipada existe, pero ningún flujo GUI la consume.', 'No se demuestra rango, k-NN o polígono sobre mapa.',
     'Conectar resultados con marcadores resaltados y selección por ID.',
     'Mantener una capa de puntos base y una capa de resultados; mostrar centro/radio o polígono y lista de distancias concordante.',
     'IDs del mapa, tabla y respuesta del motor idénticos; limpiar resaltado anterior ante vacío/error y conservar orden k-NN.', '2.2.1, 2.3 y serialización espacial.')
mark('2.3.1', 'NO IMPLEMENTADO', 'SqlSession admite consultas relacionales; el parser rechaza distancia/POINT. El owner tiene spatial_radius programático.',
     [ref('engine/query/parser.py','_AGGREGATE_FUNCTIONS'), ref('api/database.py','def spatial_radius('), 'docs/auditoria/evidencias/espacial_100k_real.json'],
     'Un método Python no satisface la extensión SQL requerida.', 'Faltan nodos AST, binding de ubicación, planificación espacial y ejecución SQL; tampoco hay endpoint espacial público.',
     'Extender la cadena parser→AST→binder→planner→executor con consultas por distancia.',
     'Añadir POINT(lat,lon), expresión de distancia y un operador SpatialScan/SpatialIndexScan que reutilice SpatialIndex bajo los locks de sesión; conservar residual estricto <.',
     'Ejecutar el ejemplo del PDF sobre tiendas, comparar índice y scan, ambas métricas, borde, errores de ejes/unidades y plan observado.', '2.1; integración del owner y metadatos espaciales con QueryEnvironment.')
mark('2.3.2', 'NO IMPLEMENTADO', 'ORDER BY solo acepta expresiones del subconjunto relacional y LIMIT está explícitamente fuera de él.',
     [ref('engine/query/parser.py','_UNSUPPORTED_TRAILING_KEYWORDS'), ref('api/database.py','def spatial_knn('), 'docs/auditoria/evidencias/espacial_100k_real.json'],
     'El ejemplo k-NN SQL no se puede ejecutar; el núcleo k-NN correcto no completa esta interfaz.',
     'Falta resolver mi_ubicacion o un centro literal, expresión de distancia y límite de resultados.',
     'Añadir LIMIT entero no negativo y reconocimiento de ORDER BY distancia para la ruta k-NN.',
     'Resolver centros mediante parámetros explícitos o POINT; seleccionar un operador TopK espacial y devolver distancia/IDs ordenados sin ordenar toda la tabla innecesariamente.',
     'Ejemplo funcional con k=10, límites 0/N/N+1, empates estables, métrica elegida y plan que identifique el acceso real.', '2.3.1; AST/binding de funciones y contrato de resultados.')
mark('2.4.1', 'NO IMPLEMENTADO', 'Hay scan, R-Tree y SQL de preparación GiST, además de logs históricos de setup PostGIS.',
     [ref('benchmarks/spatial/postgres.py','def setup_sql('), ref('benchmarks/spatial/__main__.py','def main('), ref('benchmarks/results/spatial_e1_setup.json'), 'docs/auditoria/evidencias/comparador_entorno_actual.json'],
     'No hay un harness que mida y compare las tres técnicas. EXPLAIN de preparación no equivale al experimento requerido.',
     'No existen mediciones comparativas completas ni validación cruzada de las 100 consultas. Docker CLI está instalado, pero docker ps falla porque no está disponible el daemon; el contenedor histórico no pudo consultarse. Disponibilidad actual de PostGIS: NO VERIFICADA.',
     'Implementar adapters de medición secuencial/R-Tree/GiST sobre los mismos CSV y centros.',
     'Reutilizar datasets y setup; registrar plans GiST y equivalencia exacta de IDs. Evitar que PostgreSQL participe como almacenamiento del motor propio.',
     'Cada combinación debe producir resultados equivalentes y filas de medición con técnica, tamaño, consulta, configuración y unidades.', '2.1 y comparador PostgreSQL preparado; 2.3 no bloquea benchmarks directos.')
mark('2.4.2', 'PARCIAL', 'El generador exporta 1k/10k/100k y 100 centros; el manifiesto enumera radios y k requeridos.',
     [ref('benchmarks/spatial/datasets.py','def export('), ref('tests/spatial/test_e1_inputs.py')],
     'Se acredita preparación de los tres tamaños; no ejecución del experimento completo con las familias de radio y k.',
     'El probe de auditoría 100k es funcional, con tres centros; no reemplaza las 100 consultas ni la comparación de técnicas.',
     'Ejecutar la matriz radio=1000/5000/10000 m, k=10/50/100 y N=1000/10000/100000.',
     'Consumir los CSV/manifiesto compartidos y 100 centros por combinación; conservar hashes y separar warmup de medición.',
     'Cobertura automática de tamaños, familias y parámetros; archivos sin huecos, IDs correctos y semillas reproducibles.', '2.4.1.',
     verified=[0,0,1], implemented=[0,0,1])
mark('2.4.3', 'NO IMPLEMENTADO', 'No hay tiempos completos de construcción y promedio de 100 consultas para las tres técnicas.',
     [ref('benchmarks/spatial/__main__.py'), ref('benchmarks/spatial/postgres.py')],
     'El setup y los smoke tests no satisfacen las mediciones solicitadas.', 'Faltan crudos por consulta y agregación comparable.',
     'Medir construcción y consultas con límites temporales claros.',
     'Excluir generación/importación cuando se mida construcción del índice; explicitar el tratamiento de carga de datos para cada técnica y medir consultas equivalentes.',
     'Promedio calculable desde 100 tiempos crudos por caso, con resultados correctos y repeticiones/entorno declarados.', '2.4.1–2.4.2.')
mark('2.4.4', 'NO IMPLEMENTADO', 'Se conocen archivos del R-Tree/Heap, pero no existe una medición experimental de memoria y disco espacial.',
     [ref('engine/spatial/rtree.py','def save('), ref('engine/operators/context.py','ROW_OVERHEAD_BYTES =')],
     'Contadores de candidatos o memoria reservada relacional no son RSS ni espacio del comparador.',
     'El árbol es residente y JSON puede aumentar el pico durante guardado; PostgreSQL requiere métricas específicas de sus relaciones.',
     'Añadir memoria real y tamaños base/índice para cada técnica.',
     'Medir RSS pico por proceso/subproceso, bytes de archivos propios y pg_relation_size/pg_total_relation_size; declarar métricas no comparables directamente.',
     'Resultados con unidades y alcance, baseline de proceso y ausencia de ceros ficticios o estimaciones presentadas como mediciones.', '2.4.1 y política experimental común.')
mark('2.4.5', 'NO IMPLEMENTADO', 'No hay gráficos ni tabla experimental espacial derivados de una matriz completa.',
     [ref('docs/spatial.md'), ref('benchmarks/report.py')],
     'La presentación relacional no satisface la comparación espacial.', 'Faltan datos base, gráficos y recomendaciones espaciales medidos.',
     'Generar gráficos y tabla desde los nuevos crudos.', 'Reutilizar el estilo del reporte relacional con series secuencial/R-Tree/GiST y notas sobre memoria, disco y equivalencia.',
     'Cada cifra trazable a mediciones; gráficas por tamaño/radio/k y tabla de cuándo usar cada técnica.', '2.4.1–2.4.4.')

ABSENCE = ['docs/auditoria/evidencias/inventario_codigo.json', 'docs/auditoria/evidencias/espacial_100k_real.json']


def missing(identifier, current, problems, correction, recommendation, validation, dependencies, evidence=None):
    mark(identifier, 'NO IMPLEMENTADO', current, ABSENCE if evidence is None else evidence,
         'No se encontró implementación que satisfaga este requisito en el snapshot auditado.',
         problems, correction, recommendation, validation, dependencies)


missing('3.1.1', 'Solo existe almacenamiento de VARCHAR relacional; no hay índice invertido ni SPIMI.',
        'Un campo de texto y un B+ sobre cadenas no indexan términos ni postings; documentos largos pueden exceder una página.',
        'Añadir almacenamiento gestionado de documentos e índice SPIMI propio.',
        'Definir doc_id estable, tokenización reproducible y bloques acotados término→postings; persistir bloques y fusionarlos por término conservando tf y estadísticas.',
        'Oracle de postings en corpus pequeño, documentos repetidos/vacíos, Unicode, bloques externos forzados y reapertura.',
        'IDs/catálogo, owner/auxiliares, almacenamiento de texto fuera de filas de una sola página.')
missing('3.1.2', 'La presencia de VARCHAR no incluye TF-IDF ni vectores sparse de términos.',
        'No hay estadísticas tf/df ni normalización de documentos/consulta.', 'Implementar ranking TF-IDF + coseno.',
        'Obtener df y N del índice SPIMI, definir fórmula/normalización explícitas y acumular productos por postings; ordenar scores con tie-break por doc_id.',
        'Corpus con puntuaciones calculadas manualmente, consulta sin términos, términos repetidos y rankings estables tras reabrir.', '3.1.1.')
missing('3.1.3', 'No se encontró BM25 en engine ni en rutas API.', 'Faltan longitud de documentos, promedio y cálculo de score.',
        'Implementar BM25 sobre los mismos postings.', 'Persistir document length y avgdl; definir k1/b configurables y reutilizar las estadísticas del corpus sin duplicar el índice.',
        'Scores de referencia, documentos de longitudes distintas, consulta vacía/OOV y orden descendente estable.', '3.1.1.')
missing('3.2.1', 'No hay harness TF-IDF/BM25/GIN.', 'PostGIS espacial no es un comparador GIN textual.',
        'Construir adapters para las tres técnicas con el mismo corpus y consultas.',
        'Configurar explícitamente tokenización y ranking PostgreSQL; documentar diferencias en stemming/stopwords en vez de atribuirlas al índice.',
        'Mismos IDs/corpus, consultas registradas y tres resultados comparables por caso.', '3.1.1–3.1.3; PostgreSQL como comparador.')
missing('3.2.2', 'No se encontró corpus textual ni consultas de 1, 3 y 5+ palabras.', 'No hay datos reproducibles para evaluar la Parte 3.',
        'Preparar corpus de 1k/10k/100k documentos y consultas estratificadas por longitud.',
        'Guardar origen, hashes, doc_ids y consultas compartidas; evitar que una partición de texto cuente como documentos independientes sin explicarlo.',
        'Conteos exactos, texto recuperable y consultas en las tres bandas de longitud.', 'Almacenamiento de documentos; elección de dominio.')
missing('3.2.3', 'No hay tiempos de construcción/consulta textual.', 'Las métricas SQL relacionales no sustituyen ranking textual.',
        'Medir los dos costes para las tres técnicas y tamaños.', 'Separar ingesta de construcción y consulta; guardar repeticiones y configuración del ranking.',
        'Crudos con técnica/tamaño/consulta y agregaciones regenerables.', '3.2.1–3.2.2.')
missing('3.2.4', 'No hay juicios de relevancia ni Precision@10/Recall@10.', 'No se puede obtener relevancia solo de tiempos o scores propios.',
        'Definir queries con conjuntos de documentos relevantes y calcular ambas métricas.',
        'Mantener qrels independientes de TF-IDF/BM25; declarar convenciones para menos de diez resultados y consultas sin relevantes.',
        'Casos manuales perfectos/parciales/nulos y agregados idénticos a un cálculo independiente.', '3.2.2 y rankings implementados.')
missing('3.2.5', 'No hay mediciones de memoria y espacio de índices textuales.', 'No existe evidencia de consumo del SPIMI o GIN.',
        'Medir RSS y disco base/índice durante construcción y búsqueda.', 'Usar el contrato experimental común y métricas PostgreSQL explícitas.',
        'Unidades y fases definidas, valores reales por técnica y tamaño.', '3.2.1–3.2.3.')
missing('3.2.6', 'No hay gráficos ni tabla textual.', 'Faltan experimentos a los que vincular ventajas/desventajas.',
        'Generar presentación experimental de Parte 3.', 'Mostrar tiempo, memoria, disco y relevancia por técnica, tamaño y longitud de consulta.',
        'Gráficas regenerables y recomendaciones apoyadas por datos y límites de calidad.', '3.2.1–3.2.5.')
missing('3.3.1', 'El parser rechaza MATCH/USING/SCORE y LIMIT; no hay ejecución de búsqueda textual.',
        'Reconocer palabras o guardar textos no satisface los ejemplos SQL.', 'Extender AST, binder, planner y executor con búsqueda/ranking textual.',
        'Resolver MATCH contra un campo indexado, seleccionar TF_IDF/BM25, producir SCORE y reutilizar LIMIT/TopK; devolver planes de operadores reales.',
        'Ambos ejemplos del PDF, aliases de score, orden y límites; errores controlados por técnica/campo inválidos.', '3.1.1–3.1.3 y extensión general de funciones/LIMIT de 2.3.')

missing('4.1.1', 'No existe ExtractFeatures de imágenes ni SIFT.', 'El motor no carga ni transforma imágenes en descriptores.',
        'Añadir extracción de descriptores SIFT y manejo de objetos gestionados.',
        'Definir ExtractFeatures con tipo/versión de extractor, validar formatos y guardar vínculos objeto→descriptores. Aclarar si el docente permite bibliotecas auxiliares SIFT; el PDF no lo resuelve.',
        'Imagen válida, uniforme, corrupta y transformada; salida finita y reproducible con parámetros fijados.', 'Almacenamiento de objetos y metadatos.')
missing('4.1.2', 'No existe extracción MFCC ni procesamiento de audio.', 'No hay política de muestreo, canales o ventanas.',
        'Añadir extracción MFCC con parámetros explícitos.', 'Normalizar sample rate/canales, segmentar ventanas y devolver matriz de descriptores finitos; tratar silencio y formatos inválidos.',
        'Señal sintética, silencio, clips cortos y audio inválido; dimensión y versión del extractor consistentes.', 'Almacenamiento de audio; interfaz ExtractFeatures.')
missing('4.1.3', 'No hay vocabulario de centroides ni asignación visual/auditiva.', 'Descriptores locales por sí solos no son el vector K requerido.',
        'Implementar K-Means o Tree Quantization para construir el vocabulario.',
        'Entrenar con muestra reproducible, persistir K/centroides/versión y asignar cada descriptor al mismo vocabulario en ingesta y consulta.',
        'Clusters conocidos, centroides vacíos, asignaciones reproducibles y reapertura del vocabulario.', '4.1.1–4.1.2.')
missing('4.1.4', 'No hay histogramas ni TF-IDF de palabras multimedia.', 'Los vectores de términos de Parte 3 tampoco existirían aún ni sustituyen descriptores multimedia.',
        'Construir histogramas K y aplicar TF-IDF del corpus multimedia.', 'Compartir matemáticas cuando sean compatibles, pero mantener vocabularios y estadísticas por modalidad/versiones; persistir dimensión K.',
        'Histograma manual, suma de frecuencias, pesos y dimensión; objeto sin descriptores y consulta con misma transformación.', '4.1.3.')
missing('4.2.1', 'No hay IVF; el Heap relacional no agrupa vectores por centroides.', 'No hay inverted lists ni selección de probes.',
        'Implementar IVF propio.', 'Persistir centroids/listas con IDs estables, nprobe configurable y reranking exacto con la métrica elegida.',
        'Comparación con scan vectorial exacto, nprobe total como referencia, inserción/reapertura y Recall@10.', '4.1.4; representación de vectores y métricas.')
missing('4.2.2', 'No hay HNSW ni grafo de vecinos.', 'El R-Tree 2D no equivale a HNSW para alta dimensionalidad.',
        'Implementar HNSW propio.', 'Construir niveles, selección de vecinos y búsqueda ef acotada; persistir IDs, grafo, semilla y parámetros M/ef.',
        'Invariantes de niveles/aristas, vecino exacto en corpus pequeño, ef creciente, reapertura y Recall@10.', 'Vectores y métricas de 4.2.3–4.2.5.')
for identifier, name, algorithm in [
    ('4.2.3', 'Euclidiana', 'sqrt de suma de diferencias al cuadrado'),
    ('4.2.4', 'Producto Punto', 'suma de productos componente a componente'),
    ('4.2.5', 'Coseno', 'producto punto dividido por normas, con política explícita para vector cero')]:
    missing(identifier, f'No hay métrica {name} vectorial ni interfaz sobre vectores K.',
            'La distancia espacial 2D no acredita una métrica vectorial multimedia ni su integración.',
            f'Implementar {name} sobre vectores de dimensión validada.',
            f'Calcular {algorithm}; fijar orientación de ranking (distancia ascendente o similitud descendente) y rechazar dimensiones/valores inválidos.',
            'Vectores de cálculo manual, identidad, cero, dimensiones diferentes, valores no finitos y rankings coherentes en IVF/HNSW.',
            'Representación de vectores finitos de dimensión K.')
missing('4.3.1', 'El parser rechaza SIMILAR_TO, score multimedia y WITH METRIC.', 'No se resuelve objeto de consulta ni índice/métrica.',
        'Añadir la extensión SQL multimedia completa.',
        'Extraer el vector de consulta con vocabulario/versiones del índice; resolver USING y WITH METRIC; producir SIMILARITY_SCORE con orden coherente y límites.',
        'Ejemplos imagen/audio del PDF, path inválido, índice/métrica inexistentes y resultados iguales al API vectorial.', '4.1–4.2 y funciones/TopK del parser.')
missing('4.4.1', 'No hay comparación IVF/HNSW ni Euclidiana/coseno.', 'No hay índices o vectores experimentales.',
        'Construir experimento cruzado de ambos índices y ambas métricas.', 'Fijar dataset/vectores/consultas y reportar parámetros de aproximación; distinguir precisión de velocidad.',
        'Cada combinación con crudos y baseline exacto bajo su propia métrica.', '4.1–4.2.')
missing('4.4.2', 'No existen datasets de 1k/10k/100k objetos multimedia ni consultas k=10.', 'Contar descriptores como objetos inflaría el tamaño del dataset.',
        'Preparar objetos, manifiestos y consultas reproducibles.', 'Guardar objeto_id, modalidad, origen, hash, versión de extracción y vocabulario; usar diez vecinos por objeto de consulta.',
        'Conteo de objetos exacto y transformación de consulta consistente en los tres tamaños.', '4.1; selección de datasets.')
missing('4.4.3', 'No hay tiempos o memoria multimedia.', 'No se separan extracción, entrenamiento, construcción y búsqueda.',
        'Medir construcción del índice, consulta y uso de memoria.', 'Registrar también fases auxiliares por separado para no atribuir extracción o K-Means a IVF/HNSW.',
        'Métricas reales y agregadas desde crudos con parámetros y fases explícitos.', '4.4.1–4.4.2.')
missing('4.4.4', 'No hay Recall@10 multimedia ni oracle exacto.', 'Scores aproximados no permiten deducir recall.',
        'Calcular vecinos exactos para cada consulta y métrica y comparar el top diez.',
        'Fijar convención de auto-coincidencia y empates; usar conjuntos de IDs de referencia independientes de IVF/HNSW.',
        'Recall entre 0 y 1, casos manuales y curva frente a nprobe/ef; no usar relevancia textual como sustituto.', '4.2 y 4.4.2.')
missing('4.4.5', 'No hay galería multimedia ni gráficas/recomendaciones.', 'La galería debe mostrar casos reales, no imágenes conceptuales de resultados.',
        'Generar gráficas, galería de éxito/error y tabla comparativa.', 'Enlazar consultas con objetos recuperados y referencia; reproducir audio o visualizar imágenes sin inventar éxito.',
        'Cada caso trazable a su consulta, ranking y métrica; gráficas tiempo/tamaño y recomendaciones verificables.', '4.4.1–4.4.4.')

missing('5.1.1', 'Existe API REST del motor y una consola administrativa, pero no una aplicación del Anexo A.',
        'La consola SQL demuestra el motor; no constituye por sí sola una aplicación real de IA del dominio elegido.',
        'Elegir la aplicación y construir su flujo mediante el API propio.',
        'Crear un frontend/servicio de dominio que consuma endpoints del motor. Conservar FastAPI y las sesiones; evitar acceso directo a páginas/índices desde la interfaz.',
        'Flujo de dominio completo con llamadas HTTP observables al motor propio y resultados reales.', 'Elección 5.1.4 y modalidades requeridas por esa opción.',
        evidence=[ref('api/app.py'), ref('frontend/src/App.tsx')])
missing('5.1.2', 'El núcleo maneja filas y puntos por métodos distintos; ninguna aplicación pública integra dos tipos en una experiencia.',
        'Tener dos paquetes o tablas con coordenadas no demuestra integración multimodal de la aplicación.',
        'Integrar al menos dos modalidades en el flujo del dominio.',
        'Usar IDs y metadatos relacionales comunes y combinar búsquedas reales de las modalidades escogidas con reglas de fusión explícitas.',
        'Una acción del usuario utiliza ambos tipos y el resultado permite rastrear las contribuciones de cada uno.', '5.1.4; partes funcionales de las modalidades escogidas.')
missing('5.1.3', 'La GUI es una consola relacional; no hay chatbot, recomendaciones, timeline de audio ni reconocimiento facial.',
        'No existe demostración interactiva de la aplicación final.', 'Añadir la interfaz del dominio elegido.',
        'Reutilizar componentes de sesión/error/resultados compatibles; diseñar entrada, salida y estados vacíos/error propios de la aplicación.',
        'Usuario completa el caso principal del anexo sobre datos reales, con ambos tipos integrados.', '5.1.1–5.1.2.')
missing('5.1.4', 'No se encontró una opción A/B/C/D elegida en los documentos o código de aplicación.',
        'La decisión pendiente impide fijar el backlog específico y comprobar sus componentes obligatorios.',
        'Registrar una sola opción y su contrato de aceptación.',
        'A: PDF/chunks/metadata→SPIMI→recuperación→LLM; B: catálogo, imágenes/ubicación y fusión de recomendaciones; C: MFCC y segmentos/timeline de coincidencias; D: embeddings, cámara y búsqueda con objetivo de eficiencia. No implementar las cuatro.',
        'Opción documentada y todos sus componentes demostrados; lo opcional del anexo debe seguir siendo opcional.', 'Decisión de producto y dominio; no requiere reescribir Parte 1.')

mark('T.1.1', 'COMPLETO', 'Repositorio Git local con origin GitHub y HEAD publicado en main.',
     ['docs/auditoria/evidencias/commit.txt', 'docs/auditoria/evidencias/remoto_verificado.txt'],
     'git ls-remote confirmó el mismo commit 841977a en HEAD/main remoto.',
     'El PDF y DOCX actuales son cambios locales del usuario sin commit; se preservan. El requisito de código publicado sí está satisfecho.',
     'Ninguna corrección del código publicado identificada.', 'Mantener publicación incremental y no confundir disponibilidad remota del código con la del video o presentación.',
     'Comparar SHA local y remoto, y verificar los cambios autorizados antes de futuras publicaciones.', 'Git y acceso remoto.')
mark('T.1.2', 'PARCIAL', 'README describe arquitectura/organización relacional; docs/spatial amplía decisiones espaciales.',
     [ref('README.md','## Organización'), ref('docs/informe/informe_parte_01.md','PageManager'), ref('PROJECT_CONTEXT.md','Stage 10 remains pending')],
     'Dos criterios de tres satisfechos. Persisten rutas antiguas a PLAN.md/ETAPA_XX y una descripción del árbol que omite engine/database y engine/spatial.',
     'También se afirma que PageManager es el único dueño de disco, aunque temporales, undo, manifiestos y R-Tree tienen E/S propia. La coordinación mezcla cierres actuales con secciones obsoletas.',
     'Corregir rutas y estados vigentes; precisar que PageManager centraliza páginas relacionales, no toda E/S del sistema.',
     'Editar documentos de forma localizada y marcar historias como históricas. Actualizar diagrama con owner y ruta espacial; conservar decisiones válidas.',
     'Enlaces locales resuelven, diagrama coincide con imports y responsabilidades y no se declaran como completos requisitos pendientes.',
     'Hallazgos de esta auditoría; no requiere cambio de arquitectura.', verified=[1,1,0], implemented=[1,1,1])
mark('T.1.3', 'COMPLETO', 'README y demo.md explican entorno, instalación de extras, carga inicial, compilación y arranque.',
     [ref('README.md','## Requisitos e instalación'), ref('docs/demo.md'), 'docs/auditoria/evidencias/preparacion_entorno.log'],
     'Instalación nueva, build y arranque reales se verificaron sobre una copia limpia. Las instrucciones de ejecutar desde raíz permiten importar api y scripts.',
     'El launcher no reinicia inmediatamente en POSIX y Ctrl+C sale anómalamente; son defectos de ejecución documentados aparte. Un wheel instala solo engine.',
     'Corregir el launcher de forma localizada. Si se ofrece distribución instalable completa, incluir api/benchmarks o mantener el requisito de clonar y ejecutar desde raíz.',
     'Conservar el procedimiento actual y fijar versiones del entorno de demostración para reproducibilidad.',
     'Clon limpio, Python >=3.11, extras, npm ci/build, prepare, health, GUI y cierre/reinicio después de corregir los fallos.', 'Dependencias auxiliares y datasets de demostración.')
mark('T.1.4', 'NO VERIFICADO', 'Existe un guion de aproximadamente ocho minutos para Parte 1; no se encontró video ni enlace a una grabación.',
     [ref('docs/informe/guion_video.md'), ref('docs/ETAPA_10_AUDIT.md','grabación a cargo del equipo')],
     'El guion no demuestra existencia, duración ni funcionalidades de un video. Podría existir externamente; no hay evidencia disponible.',
     'No se puede acreditar este entregable ni el video final de todas las modalidades.',
     'Grabar y aportar archivo/enlace comprobable, o incorporar evidencia del video externo si ya existe.',
     'Adaptar el guion al avance y después a todas las funcionalidades finales; grabar ejecución real, con duración 5–10 minutos.',
     'Abrir la grabación, verificar duración y contrastar cada capacidad mostrada con el sistema.', 'Funcionalidades que se demuestran; cierre final de las cinco partes.')
mark('T.1.5', 'COMPLETO', 'Informe Parte 1 contiene arquitectura, dominio, algoritmos y experimentos; docs/spatial registra el incremento espacial y sus límites.',
     [ref('docs/informe/informe_parte_01.md'), ref('docs/EXPERIMENTOS.md'), ref('docs/spatial.md')],
     'Hay documentación incremental real del avance actual. No se exige que describa como terminadas partes futuras todavía ausentes.',
     'La evaluación de arquitectura del informe debe corregirse según T.1.2, y el apartado experimental debe reconocer la brecha de carga mixta.',
     'Mantener el informe incremental, corregir afirmaciones concretas e incorporar resultados nuevos conforme se implementen.',
     'Enlazar capítulos por parte con evidencia de algoritmo, dominio, método, datos y limitaciones; no usar esta auditoría como evidencia de una implementación futura.',
     'Cada incremento tiene explicación y resultados trazables; la entrega final cubre las cinco partes y sus experimentos reales.', 'Avances funcionales y experimentales; T.1.2.')
mark('T.1.6', 'PARCIAL', 'Hay un esquema textual de presentación de Parte 1, estimado en 12–15 minutos; no hay exposición final acreditada.',
     [ref('docs/informe/presentacion.md')],
     'Existe material y planificación temporal; la exposición final de cinco partes y 5 minutos de preguntas no está verificada.',
     'Un esquema preparatorio no prueba que la presentación final se haya realizado ni que cubra todo el proyecto.',
     'Completar material de las cinco partes, ensayar 15 minutos y reservar 5 para preguntas; aportar evidencia al llegar al hito.',
     'Reutilizar el esquema y cifras válidas; añadir modalidades/aplicación y explicar limitaciones de forma fiel.',
     'Ensayo cronometrado, recorrido de capacidades reales y evidencia de la exposición final según el curso.', 'Entrega final de las cinco partes.',
     verified=[1,1,0], implemented=[1,1,0])


def summary(rows):
    result = {'requisitos': len(rows)}
    for key, field in [('implementado', 'criterios_implementados'), ('verificado', 'criterios_verificados'), ('pendiente', 'criterios_pendientes')]:
        value = sum((Fraction(sum(row[field]), len(row['criterios'])) for row in rows), Fraction())
        result[key + '_equivalentes'] = str(value)
        result[key + '_porcentaje'] = float(value * 100 / len(rows))
    result['estados'] = {state: sum(row['estado'] == state for row in rows) for state in
                        ['COMPLETO', 'PARCIAL', 'INCORRECTO', 'NO IMPLEMENTADO', 'NO VERIFICADO']}
    return result


def main():
    assert all('estado' in row for row in ROWS)
    (OUT / 'EVALUACION.json').write_text(json.dumps(ROWS, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    columns = ['id','parte','etapa','pagina','seccion','requisito','estado','estado_actual','evidencia','evaluacion',
               'problemas','correccion','implementacion_recomendada','validacion','dependencias','criterios',
               'criterios_implementados','criterios_verificados','criterios_pendientes','avance_implementado','avance_verificado','avance_pendiente']
    with (OUT.parent / 'MATRIZ_REQUISITOS.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in ROWS:
            output = {key: row[key] for key in columns if key in row}
            for key in ['evidencia','criterios','criterios_implementados','criterios_verificados','criterios_pendientes']:
                output[key] = json.dumps(output[key], ensure_ascii=False)
            for key, field in [('implementado','criterios_implementados'), ('verificado','criterios_verificados'), ('pendiente','criterios_pendientes')]:
                output['avance_' + key] = f'{sum(row[field])/len(row[field])*100:.8f}'
            writer.writerow(output)
    totals = dict(global_=summary(ROWS), funcional=summary([row for row in ROWS if row['parte'] != 'T']),
                  partes={part: summary([row for row in ROWS if row['parte'] == part]) for part in ['1','2','3','4','5','T']},
                  etapas={f'{part}.{stage}': summary([row for row in ROWS if row['parte'] == part and row['etapa'] == stage])
                          for part, stage in sorted({(row['parte'], row['etapa']) for row in ROWS})})
    (OUT / 'PORCENTAJES.json').write_text(json.dumps(totals, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(totals['partes'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
