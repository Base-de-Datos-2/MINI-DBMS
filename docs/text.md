# Núcleo de búsqueda textual

La Parte 3 implementa recuperación léxica con vectores dispersos de términos.
El tokenizador Unicode y los contratos/fixtures de 1A están cerrados; el corpus
real de 1B tiene aceptación PASS. Los **bloques 2 (SPIMI), 3 (ranking Python)
y 4A (sellado persistente) están implementados y verificados**. SQL textual,
registro textual e integración en el owner/HTTP/UI siguen pendientes.

`engine.text.build_spimi` construye un índice persistente desde un Heap
prestado, con presupuesto de bloques y mezcla externa por fan-in limitado.
`engine.text.TextIndex.open` abre el léxico y estadísticas; sus iteradores
leen postings por offsets con buffers acotados sobre un handle protegido por
un latch físico breve. El índice conserva frecuencias, df, normas TF-IDF,
longitudes, IDs/RIDs y hashes de filas originales, incluyendo documentos sin
tokens. No usa una base vectorial externa ni implementa embeddings.

Uso Python, formato, contrato de memoria, comandos de prueba y límites:
[cierre del bloque 2](../PART_03/BLOQUE_2.md).

`engine.text.search_text` calcula TF-IDF/coseno o BM25 sobre ese mismo índice.
Con `use_indexes=False` recorre el Heap real y conserva las mismas estadísticas
y fórmulas. Devuelve hits inmutables con ID, score y RID, más contadores de
trabajo y estimados de memoria separados del presupuesto de sort.

```python
from engine.text import search_text

result = search_text(index, "base de datos", model="BM25", limit=10)
# index es un TextIndex abierto y la colección debe permanecer sin cambios.
for hit in result.hits:
    print(hit.doc_id, hit.score, hit.rid)
```

Los órdenes admitidos son `score_desc` (predeterminado), `score_asc`, `id_asc`
e `id_desc`. Solo score descendente con LIMIT usa un heap de tamaño k; las
otras rutas usan ExternalSort antes de limitar. El acumulador de candidatos
continúa siendo O(C). Uso, pruebas y límites: [bloque 3](../PART_03/BLOQUE_3.md).

El constructor requiere un directorio nuevo y una fuente sin escritores.
Durante construcción, mantener el Heap sin mutaciones es responsabilidad del
llamador. Después de validar, cerrar todos los owners/coordinators y publicar
el sello del motor sobre los handles de preparación abiertos offline:

```python
from engine.text import seal_text_collection

# Enumerar TODOS los B+/hash secundarios declarados de esta colección.
seal_text_collection(heap, index, secondary_indexes=secondary_indexes)
assert heap.read_only
```

El sello v2 conserva filas/RIDs y asocia colección/generación del índice.
Las escrituras se rechazan incluso por handles directos y antes de capturar
undo en sesiones. Las tablas v1 continúan mutables. Reabrir conserva la política;
no existe operación de desellado. La publicación requiere una fuente exclusiva,
no es atómica ante caídas y un fallo parcial exige reconstruir en otro directorio.
El registro y script de preparación del owner corresponden al bloque 4B.
Matriz de rutas, compatibilidad y pruebas: [bloque 4A](../PART_03/BLOQUE_4A.md).

Referencias:

- [Plan de la Parte 3](../PART_03/PLAN_PARTE_03.md).
- [Contratos y fixtures](../PART_03/BLOQUE_1A.md).
- [Aceptación del corpus real](../PART_03/BLOQUE_1B.md).
- [Fórmulas de ranking](text-ranking-contract.md).
- [Contrato SQL textual, aún por implementar](text-sql-contract.md).
