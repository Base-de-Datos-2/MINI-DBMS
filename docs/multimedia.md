# Parte 4: búsqueda multimedia (imágenes y audio)

Guía de uso. El diseño y sus reglas están en
[multimedia-contract.md](multimedia-contract.md); la evidencia de cada fase,
en `PART_04/BLOQUE_*.md`; los resultados experimentales, en
[EXPERIMENTOS_MULTIMEDIA.md](EXPERIMENTOS_MULTIMEDIA.md).

## Qué hace

Dado un archivo de consulta (una foto o un audio registrado), devuelve los k
objetos más parecidos de una colección:

```sql
SELECT * FROM imagenes
WHERE SIMILAR_TO('foto_consulta.jpg', k=10)
USING HNSW WITH METRIC=cosine;

SELECT nombre, artista, SIMILARITY_SCORE() AS score
FROM canciones
WHERE SIMILAR_TO('audio_query.mp3', k=5)
USING IVF WITH METRIC=euclidean
ORDER BY score DESC;
```

1. **Características:** SIFT para imágenes (OpenCV) y MFCC para audio
   (librosa). Cada objeto produce muchos descriptores locales.
2. **Bolsa de palabras:** un vocabulario K-Means (K = 256 visuales, 64 de
   audio) convierte cada descriptor en una "palabra"; el histograma de
   palabras con pesos TF-IDF es el vector del objeto.
3. **Índices propios:** IVF (listas invertidas con nuestro K-Means) y HNSW
   (grafo jerárquico); además la búsqueda exacta `VectorScan`.
4. **Métricas:** euclidiana, producto punto y coseno. `SIMILARITY_SCORE()`
   siempre es "mayor es mejor"; con euclidiana vale −distancia.

## Instalación

Además de lo indicado en el README, la Parte 4 necesita el extra
`multimedia` (numpy, OpenCV, soundfile y librosa, que trae scikit-learn):

```bash
.venv/bin/python -m pip install -e ".[test,api,bench,multimedia]"
```

`ffmpeg` solo hace falta para regenerar los archivos de prueba o recortar
audio. Los servidores de las Partes 1–3 no cargan estas librerías.

## Preparar y abrir

Con el servidor detenido:

```bash
# Demo real: 120 fotos de COCO y 30 canciones de FMA incluidas en el repositorio
python scripts/setup_multimedia.py --assets data/multimedia_demo

# Alternativa mínima con archivos sintéticos de prueba
python scripts/setup_multimedia.py --data-dir data/generated/multimedia_fx

python -m api --multimedia            # abre data/generated/multimedia
```

La preparación crea un directorio **nuevo**: extrae características, entrena
el vocabulario, construye vectores, IVF y un grafo HNSW por métrica, sella la
tabla y publica `multimedia_tables.json`. Al reabrir no se entrena ni se
reconstruye nada. Las colecciones son de solo lectura, incluso con
`--allow-writes`: para cambiarlas se prepara otro directorio.

## Usar la interfaz

- **Ejemplos SQL** trae los dos ejemplos del enunciado, una variante que
  muestra un reproductor por canción, el cambio a IVF, la métrica euclidiana y
  `EXPLAIN ANALYZE`.
- **Resultados** muestra miniaturas o reproductores de audio cuando el plan es
  una búsqueda vectorial real, la consulta usada y qué significa el score.
- **Usar índices** desmarcado ejecuta `VectorScan` (exacto) para comparar.
- **Plan de ejecución** muestra `VectorIndexScan` o `VectorScan`, el método
  pedido y el ejecutado, la métrica, k, los vectores evaluados, `nprobe` o
  `ef_search`, y los milisegundos de extracción y de búsqueda.
- **Archivos** lista los índices `IVF (métricas)` y `HNSW (métrica)` con su
  tamaño.

Los nombres de la consulta son archivos registrados de la colección (por
ejemplo `foto_consulta.jpg`, `consulta_000000xxxxxx.jpg`,
`audio_query.mp3`, `consulta_xxxxxx.mp3`), nunca rutas. `GET
/api/multimedia/tables` los lista.

## API

| Método y ruta | Uso |
|---|---|
| `POST /api/query` | SQL, incluido `SIMILAR_TO` |
| `GET /api/multimedia/tables` | Colecciones: modalidad, columna de archivo, tamaño, dimensión, índices y consultas registradas |
| `GET /api/multimedia/{tabla}/media/{archivo}` | Sirve solo archivos registrados de esa colección; lo demás responde 404 |

## Reglas del SQL

- `SIMILAR_TO` es toda la condición WHERE; una sola tabla.
- `USING IVF|HNSW WITH METRIC=euclidean|dot|cosine` es obligatorio.
- Orden: ninguno, o `score DESC` con desempate opcional `id ASC`.
- `LIMIT` se aplica después de elegir los k mejores: salen `min(k, LIMIT, N)`.
- Se rechazan con error claro: otros órdenes, filtros extra, JOIN, GROUP BY,
  agregados, archivos de otra modalidad y métodos o métricas sin índice.

## Reproducir el experimento

El corpus grande no está en el repositorio (unos 6 GB); se descarga y se mide
localmente:

```bash
python -m benchmarks.multimedia.coco                 # 100 080 imágenes, ~6 GB
python -m benchmarks.multimedia.features vocabulary  # vocabulario sobre 1 000
python -m benchmarks.multimedia.features counts      # SIFT + palabras de todas
python -m benchmarks.multimedia.experiment run       # construcción y consultas
python -m benchmarks.multimedia.results --input benchmarks/results/multimedia/<fecha>
```

`python -m benchmarks.multimedia.fma` y `python -m
benchmarks.multimedia.demo_assets` regeneran el audio y la demo.
