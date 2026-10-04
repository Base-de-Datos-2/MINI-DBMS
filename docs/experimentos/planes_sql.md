# Planes elegidos por el planner SQL (Tarea 10.9)

Generado por `python -m benchmarks plans`. Cada consulta se ejecutó con `EXPLAIN ANALYZE` sobre la ruta SQL completa (`api.database.Database`), con índices habilitados y deshabilitados; el tiempo es la mediana de las ejecuciones. Tamaño: 10,000 registros.

| Tabla (estructura) | Consulta | Plan con índices | ms | Plan sin índices | ms | Filas | ¿El planner eligió la opción más rápida? |
|---|---|---|---:|---|---:|---:|---|
| `t_unclustered` (unclustered_bplus) | equality_present | Projection <- Filter <- IndexScan(t_unclustered_id) | 3.22 | Projection <- Filter <- TableScan | 194.19 | 1 | sí |
| `t_unclustered` (unclustered_bplus) | equality_absent | Projection <- Filter <- IndexScan(t_unclustered_id) | 1.44 | Projection <- Filter <- TableScan | 204.35 | 0 | sí |
| `t_unclustered` (unclustered_bplus) | range 0.1% | Projection <- Filter <- IndexScan(t_unclustered_id) | 4.72 | Projection <- Filter <- TableScan | 219.44 | 10 | sí |
| `t_unclustered` (unclustered_bplus) | range 1.0% | Projection <- Filter <- IndexScan(t_unclustered_id) | 53.84 | Projection <- Filter <- TableScan | 211.27 | 100 | sí |
| `t_unclustered` (unclustered_bplus) | range 10.0% | Projection <- Filter <- IndexScan(t_unclustered_id) | 367.64 | Projection <- Filter <- TableScan | 224.26 | 1,000 | no: el recorrido es 1.6× más rápido |
| `t_unclustered` (unclustered_bplus) | ordered_retrieval | Projection <- ExternalSort <- TableScan | 1,291.09 | Projection <- ExternalSort <- TableScan | 1,150.48 | 10,000 | mismo plan |
| `t_hash` (extendible_hash) | equality_present | Projection <- Filter <- IndexScan(t_hash_id) | 0.94 | Projection <- Filter <- TableScan | 183.51 | 1 | sí |
| `t_hash` (extendible_hash) | equality_absent | Projection <- Filter <- IndexScan(t_hash_id) | 1.08 | Projection <- Filter <- TableScan | 193.01 | 0 | sí |
| `t_hash` (extendible_hash) | range 0.1% | Projection <- Filter <- TableScan | 214.23 | Projection <- Filter <- TableScan | 199.88 | 10 | mismo plan |
| `t_hash` (extendible_hash) | range 1.0% | Projection <- Filter <- TableScan | 219.54 | Projection <- Filter <- TableScan | 203.96 | 100 | mismo plan |
| `t_hash` (extendible_hash) | range 10.0% | Projection <- Filter <- TableScan | 213.06 | Projection <- Filter <- TableScan | 214.08 | 1,000 | mismo plan |
| `t_hash` (extendible_hash) | ordered_retrieval | Projection <- ExternalSort <- TableScan | 1,030.83 | Projection <- ExternalSort <- TableScan | 1,048.79 | 10,000 | mismo plan |
| `t_clustered` (clustered_bplus) | equality_present | Projection <- Filter <- IndexScan(t_clustered_id) | 1.19 | Projection <- Filter <- TableScan | 193.79 | 1 | sí |
| `t_clustered` (clustered_bplus) | equality_absent | Projection <- Filter <- IndexScan(t_clustered_id) | 2.52 | Projection <- Filter <- TableScan | 186.20 | 0 | sí |
| `t_clustered` (clustered_bplus) | range 0.1% | Projection <- Filter <- IndexScan(t_clustered_id) | 4.92 | Projection <- Filter <- TableScan | 204.93 | 10 | sí |
| `t_clustered` (clustered_bplus) | range 1.0% | Projection <- Filter <- IndexScan(t_clustered_id) | 35.66 | Projection <- Filter <- TableScan | 208.95 | 100 | sí |
| `t_clustered` (clustered_bplus) | range 10.0% | Projection <- Filter <- IndexScan(t_clustered_id) | 337.52 | Projection <- Filter <- TableScan | 215.35 | 1,000 | no: el recorrido es 1.6× más rápido |
| `t_clustered` (clustered_bplus) | ordered_retrieval | Projection <- ExternalSort <- TableScan | 1,042.31 | Projection <- ExternalSort <- TableScan | 1,066.60 | 10,000 | mismo plan |
