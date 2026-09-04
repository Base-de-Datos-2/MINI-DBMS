# Auditoría de cierre de la Etapa 4

Fecha: **2026-09-03**. Alcance: B+ Tree persistente genérico, adaptadores
clustered/unclustered e integración con las organizaciones de archivo de la
Parte 1.

Resultado: **Etapa 4 completa**. Se cumplen los **59 criterios** de la
[Definition of Done](../ETAPA_04.md#43-stage-4-definition-of-done). La suite
completa pasa **1544 pruebas con las advertencias tratadas como errores**.
Las Etapas 1–4 quedan cerradas y auditadas. **La Etapa 5 no se inició y la
Parte 1 continúa incompleta.**

## Evidencia por criterio

Cada fila corresponde a un criterio del checklist, en el mismo orden.

| N.º | Criterio | Evidencia revisada | Resultado |
|---:|---|---|---|
| 1 | Definition of Done de Etapa 3 verificada | [Auditoría de Etapa 3](ETAPA_03_AUDIT.md), 50 criterios y 1284 pruebas | Cumple |
| 2 | Pruebas de Etapas 1–3 siguen pasando | Suite acumulada de 1544 pruebas sin fallos, advertencias, omisiones ni xfails | Cumple |
| 3 | Documentos identifican correctamente la Etapa 4 | AGENTS, PLAN, PROJECT_CONTEXT, README y ETAPA_04 registran el cierre | Cumple |
| 4 | Cabecera/metadatos persistidos y validados | `BPlusFileHeader`, `BPlusHeaderPageIO` y [pruebas de cabecera](../tests/indexes/test_bplus_header.py) | Cumple |
| 5 | Hojas e internos tienen formato determinista | `BPlusNodeCodec` y golden bytes/corrupción en [pruebas de nodos](../tests/indexes/test_bplus_node.py) | Cumple |
| 6 | Cada nodo ocupa exactamente `PAGE_SIZE` | `BPlusNodePageIO` enmarca un único payload en `Page`; [pruebas de E/S](../tests/indexes/test_bplus_node_io.py) | Cumple |
| 7 | Raíz y altura sobreviven reapertura | Cabecera persistente y [pruebas de reinicio](../tests/indexes/test_bplus_tree_restart.py) | Cumple |
| 8 | Codificación de claves/RID determinista | `BPlusKeyCodec`, `BPlusRIDCodec` y [pruebas de codec](../tests/indexes/test_bplus_codec.py) | Cumple |
| 9 | Capacidad y ocupación mínima explícitas | Cálculo por tipo/tamaño físico en `bplus_binary.py`; validaciones de nodo | Cumple |
| 10 | Política de reutilización explícita | Lista LIFO persistente de `BPlusFreeNode` y consumo antes de asignar páginas | Cumple |
| 11 | Descenso usa una convención de separadores | Separadores right-min y lower-bound sensible a duplicados | Cumple |
| 12 | Búsqueda exacta vacía, de una hoja y multinivel | [Pruebas de búsqueda](../tests/indexes/test_bplus_tree_search.py) | Cumple |
| 13 | Enlaces de hojas persistidos | `next_leaf_page_id` serializado y reconstruido | Cumple |
| 14 | Rangos recorren hojas en orden | Un descenso inicial y cadena forward en [pruebas de rango](../tests/indexes/test_bplus_tree_range.py) | Cumple |
| 15 | Límites y duplicados de rango documentados | Extremos abiertos/cerrados, ausentes e iguales cubiertos | Cumple |
| 16 | Inserción sin división | Escritura de hoja y publicación del contador probadas | Cumple |
| 17 | División de hoja | Redistribución completa y ocupación válida en [pruebas de inserción](../tests/indexes/test_bplus_tree_insert.py) | Cumple |
| 18 | Separador de hoja correcto | Primera clave de la hoja derecha copiada al padre | Cumple |
| 19 | Inserción interna | Conserva `children = keys + 1` | Cumple |
| 20 | División interna | Promueve y retira el separador medio, sin duplicar hijos | Cumple |
| 21 | Propagación multinivel | Ruta de ancestros recorrida hasta encontrar capacidad o crear raíz | Cumple |
| 22 | División de raíz | Nueva raíz y aumento único/persistente de altura | Cumple |
| 23 | Inserción desordenada conserva invariantes | Casos deterministas y validación global posterior | Cumple |
| 24 | Eliminación exacta | Se elimina solo `(clave, RID)`; ausencia produce `InvalidReferenceError` | Cumple |
| 25 | Redistribución de hojas por ambos lados | Donante izquierdo preferido y derecho alternativo en [pruebas de eliminación](../tests/indexes/test_bplus_tree_delete.py) | Cumple |
| 26 | Fusión de hojas repara enlaces/separadores | Hermanos, padre, cadena forward y página liberada comprobados | Cumple |
| 27 | Redistribución interna | Rotación de separadores right-min desde ambos lados | Cumple |
| 28 | Fusión interna y underflow en cascada | Reparación propagada hacia la raíz | Cumple |
| 29 | Contracción de raíz | Hijo único promovido y raíz anterior liberada | Cumple |
| 30 | Eliminación total vuelve al árbol vacío | Raíz/primera hoja nulas, altura/entradas cero | Cumple |
| 31 | Páginas liberadas siguen la política | Lista libre acíclica persistente y reutilización tras reinicio | Cumple |
| 32 | Validador comprueba invariantes globales | `validate_structure()` y [pruebas del validador](../tests/indexes/test_bplus_tree_validator.py) | Cumple |
| 33 | Todas las hojas quedan a igual profundidad | Verificación DFS del validador | Cumple |
| 34 | Entradas alcanzables aparecen exactamente una vez | Grafo sin ciclos/compartición, cadena y contador global comparados | Cumple |
| 35 | Reapertura usa objetos nuevos | Gestores, árboles y cabeceras reconstruidos en pruebas de reinicio | Cumple |
| 36 | Mutaciones complejas continúan tras reapertura | Buscar, insertar, dividir, borrar, fusionar y contraer después de reiniciar | Cumple |
| 37 | Estado malformado falla previsiblemente | Firma/versión, nodos, referencias, enlaces, orden, ocupación y free list corruptos | Cumple |
| 38 | Unclustered usa `clave -> RID Heap` | `UnclusteredBPlusIndex` resuelve asociaciones en `HeapFile` | Cumple |
| 39 | Orden físico Heap independiente | [Pruebas unclustered](../tests/indexes/test_unclustered_bplus.py) comparan scan Heap y rango B+ | Cumple |
| 40 | Unclustered resuelve igualdad/rango | RIDs se convierten en registros activos y se valida la clave | Cumple |
| 41 | Mantenimiento insert/delete unclustered | Inserción con rollback best-effort; asociación removida antes de liberar el slot | Cumple |
| 42 | Varios unclustered son posibles | Dos archivos B+ sobre columnas distintas comparten un Heap prestado | Cumple |
| 43 | Unclustered persiste/reabre | Heap e índice se reabren con objetos nuevos | Cumple |
| 44 | Clustered usa registros físicamente ordenados | `ClusteredBPlusIndex` exige `PagedSequentialFile` | Cumple |
| 45 | Clave clustered coincide con orden físico | Columna, tipo y política de duplicados validados antes de usar el adaptador | Cumple |
| 46 | Máximo un clustered por tabla | `Catalog.register_index()` rechaza una segunda definición | Cumple |
| 47 | Clustered resuelve igualdad/rango | [Pruebas clustered](../tests/indexes/test_clustered_bplus.py) validan registros activos ordenados | Cumple |
| 48 | Inserción ordenada/eliminación diferida coordinadas | Inserción reconstruye asociaciones; eliminación quita el índice antes del tombstone | Cumple |
| 49 | Reorganización/RIDs reconstruyen el índice | Marcador incompleto, candidato validado y rebuild total | Cumple |
| 50 | Clustered persiste/reabre | Almacenamiento e índice recuperados con objetos nuevos | Cumple |
| 51 | Un núcleo sirve ambas modalidades | Ambos adaptadores poseen un `BPlusTree`; no duplican el algoritmo | Cumple |
| 52 | Ambos respetan `OrderedIndex` | Implementan `insert`, `search`, `delete` y `range_search` | Cumple |
| 53 | Catálogo distingue modalidades | `IndexMetadata` incluye `clustered`, `unique`, `file_path`; fábricas separan metadatos/runtime | Cumple |
| 54 | Contadores reales de E/S permanecen correctos | Transferencias provienen de `PageManager`; eventos lógicos usan `BPlusStructuralMetrics` | Cumple |
| 55 | Mismo dataset produce resultados equivalentes | [Integración de Etapa 4](../tests/integration/test_stage4_bplus.py) | Cumple |
| 56 | Estrés fuerza crecimiento/reducción multinivel | 145 registros `VARCHAR`, altura ≥3, borrados/fusiones y reinicio | Cumple |
| 57 | Todas las pruebas pertinentes pasan | **1544 passed** con `-W error` | Cumple |
| 58 | Decisiones estables consolidadas | PROJECT_CONTEXT documenta formato, algoritmos, adaptadores, fallos e instrumentación | Cumple |
| 59 | No se implementó Etapa 5+ | Inventario: no hay hashing extensible, buffer pool, WAL, SQL ni operadores adelantados | Cumple |

## Arquitectura final auditada

```text
Catalog (metadatos inmutables)
          |
          v
build/open factory
          |
          +-------------------------------+
          |                               |
          v                               v
UnclusteredBPlusIndex              ClusteredBPlusIndex
          |                               |
          v                               v
      BPlusTree                        BPlusTree
          |                               |
          v                               v
      HeapFile                   PagedSequentialFile
          \_______________________________/
                          |
                          v
                    PageManager
```

- El núcleo B+ persiste asociaciones `(clave, RID)` en archivos independientes.
- El adaptador unclustered conserva el orden físico independiente del Heap.
- El adaptador clustered exige que la clave coincida con el orden físico del
  archivo secuencial.
- El catálogo mantiene definiciones; no es propietario de objetos abiertos.
- Toda E/S física continúa encapsulada por `PageManager`.

## Consistencia y límites de fallo

No existe una transacción atómica que abarque el archivo de datos y el archivo
de índice en esta etapa.

- Unclustered inserta primero en Heap y después en B+; si el segundo paso falla,
  intenta eliminar el registro. Para borrar, retira primero la asociación y
  después libera el slot, restaurando la asociación si el segundo paso falla.
- La inserción y reorganización de `PagedSequentialFile` pueden cambiar muchos
  RIDs. El adaptador clustered persiste `build_complete=False` antes de esa
  mutación y reconstruye el índice completo desde un candidato hermano
  validado. Un fallo deja el índice deliberadamente bloqueado para reapertura
  hasta reconstruirlo.
- `os.replace` protege la publicación normal del candidato, pero no equivale a
  WAL, two-phase commit ni recuperación frente a cualquier corte del proceso o
  fallo posterior del sistema operativo.
- `flush()`/`close()` sincronizan los archivos que cada objeto posee; no hacen
  atómico el par almacenamiento/índice.
- La concurrencia, los locks y la coordinación transaccional se mantienen para
  etapas posteriores.

## Instrumentación

- `PageManager` conserva contadores reales de páginas leídas, escritas y
  asignadas por sesión.
- `BPlusBuildMetrics` registra tiempo, E/S, entradas y tamaño de una construcción
  o reconstrucción.
- `BPlusStructuralMetrics` registra divisiones, redistribuciones, fusiones y
  cambios de raíz. Es información de sesión y vuelve a cero al reabrir.
- `ClusteredReorganizationMetrics` separa la medición de reorganización física
  y la reconstrucción obligatoria del índice.
- No se ejecutaron ni inventaron benchmarks finales de 1K/10K/100K; pertenecen
  a la Etapa 10.

## Verificación ejecutada

Entorno: Windows NT 10.0.26200.0, **Python 3.12.4**, **pytest 8.4.2**,
instalación editable existente.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -W error
.\.venv\Scripts\python.exe -m compileall -q engine tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q -W error tests/test_architecture.py
git diff --check
```

Resultados:

- suite completa: **1544 aprobadas en 32.80 s**;
- arquitectura/importaciones aisladas: **19 aprobadas en 3.52 s**;
- `compileall`: correcto;
- `pip check`: `No broken requirements found`;
- `git diff --check`: código de salida cero; los avisos informativos de futura
  conversión LF/CRLF en Windows no representan whitespace inválido;
- archivos `*.replacement` residuales: **0**;
- archivos inesperados dentro de `data/`: **0**.

La inspección contó 17 módulos de pruebas de índices y 186 funciones de prueba
relacionadas directamente con índices, catálogo, integración B+ y arquitectura.
La suite total es acumulativa e incluye todas las regresiones de Etapas 1–3.

## Límites de la evidencia

- Se verifican cierres normales y fallos inyectados concretos, no recuperación
  completa frente a pérdida de energía en cualquier instrucción.
- Cada archivo continúa con un único propietario/escritor; no hay buffer pool,
  latches ni mutación concurrente del árbol.
- Un adaptador no descubre automáticamente otros índices de la misma tabla. El
  futuro ejecutor deberá coordinar todos los índices aplicables.
- Los RIDs son físicos y relativos a su archivo. Los RIDs secuenciales pueden
  quedar obsoletos después de movimiento y se reparan reconstruyendo.
- El catálogo continúa en memoria; `file_path` identifica el índice, pero no hay
  persistencia global del catálogo.
- La construcción es incremental, no un bulk loader bottom-up optimizado.
- Las pruebas demuestran corrección y preparación para medir, no rendimiento a
  las escalas finales ni portabilidad ya ejecutada fuera de Windows.

## Estado después del cierre

- Etapas 1, 2, 3 y 4: **cerradas y auditadas**.
- Última etapa completada: **Etapa 4 — B+ Tree**.
- Próxima etapa planificada: **Etapa 5 — Extendible Hashing**, todavía no
  iniciada y sin `ETAPA_05.md`.
- Parte 1: **incompleta**; faltan hashing extensible, algoritmos externos, SQL,
  transacciones/concurrencia, API/frontend y experimentos finales.
- Se preservó el trabajo previo del repositorio y no se creó ningún commit.
