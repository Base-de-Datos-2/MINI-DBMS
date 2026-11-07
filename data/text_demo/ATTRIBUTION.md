# Part 3 demo texts

`scripts/setup_text.py` publishes these three collections when no `--csv` is
given. They are a demonstration, not experimental evidence; the measured
results are in [docs/EXPERIMENTOS_TEXTO.md](../../docs/EXPERIMENTOS_TEXTO.md).

| File | Table.column | Rows | Origin |
|---|---|---:|---|
| `productos.csv` | `productos.titulo` | 1,000 | Real product titles from the Amazon Shopping Queries Dataset (ESCI) |
| `documentos.csv` | `documentos.contenido` | 36 | Short Spanish sentences written for the demo about the course topics |
| `articulos.csv` | `articulos.texto` | 20 | Short English sentences written for the demo about machine learning and databases |

`documentos` and `articulos` keep the table and column names of the two SQL
examples in the assignment (§2.3), and their first rows are the original demo
rows.

## productos.csv

- Source: Amazon Shopping Queries Dataset (ESCI), `large_version`, split
  `test`, locale `us`, revision `7916cdf6ab75a462e77f20ab40428a10923998d5`
  (<https://github.com/amazon-science/esci-data>), license Apache-2.0.
- Selection: exactly the 1,000-document subset of the Part 3 experiment
  (seed 20261024; `accepted_v1/1000/documents.jsonl`, SHA-256
  `e941efa679907a6f9590ac4376278daf8d679410cb3b1b1bbc0ce308f225427e`), in the
  same order.
- Changes: the experiment's 64-bit document ids are renumbered 1–1,000; the
  `asin` column keeps each product's original identifier. Titles are
  unchanged.
