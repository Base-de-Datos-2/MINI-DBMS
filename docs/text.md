# Núcleo de búsqueda textual

La Parte 3 implementa recuperación léxica con vectores dispersos de términos.
El tokenizador Unicode y los contratos/fixtures de 1A están cerrados; el corpus
real de 1B tiene aceptación PASS. El **bloque 2, núcleo SPIMI, está implementado
y verificado**. Ranking de consultas, SQL textual y su integración HTTP/UI
siguen pendientes.

`engine.text.build_spimi` construye un índice persistente desde un Heap
prestado, con presupuesto de bloques y mezcla externa por fan-in limitado.
`engine.text.TextIndex.open` abre el léxico y estadísticas; sus iteradores
leen postings por offsets con buffers acotados sobre un handle protegido por
un latch físico breve. El índice conserva frecuencias, df, normas TF-IDF,
longitudes, IDs/RIDs y hashes de filas originales, incluyendo documentos sin
tokens. No usa una base vectorial externa ni implementa embeddings.

Uso Python, formato, contrato de memoria, comandos de prueba y límites:
[cierre del bloque 2](../PART_03/BLOQUE_2.md).

El constructor requiere un directorio nuevo y una fuente sin escritores.
El Heap aún no está sellado: mantenerlo sin mutaciones es responsabilidad del
llamador hasta la fase 4A. `TextIndex.verify_storage` detecta asociaciones o
contenido distintos; no reemplaza esa futura protección persistente.

Referencias:

- [Plan de la Parte 3](../PART_03/PLAN_PARTE_03.md).
- [Contratos y fixtures](../PART_03/BLOQUE_1A.md).
- [Aceptación del corpus real](../PART_03/BLOQUE_1B.md).
- [Fórmulas de ranking](text-ranking-contract.md).
- [Contrato SQL textual, aún por implementar](text-sql-contract.md).
