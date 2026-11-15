# Guion del video de demostración — MINI-DBMS

## Versión final de las cinco partes (8:30)

El [video de entrega de 8:15](demo_final.mp4) usa capturas del sistema en
ejecución, gráficos de los experimentos y subtítulos. La siguiente secuencia
sirve para ensayar o grabar una versión narrada.

Prepara las cuatro demos con `python scripts/setup_all.py` y los artículos
según el [README](../../README.md#parte-5--preparación-del-corpus-académico).
Compila con `npm --prefix frontend run build` e inicia el servidor con
`python -m api --all --allow-writes`. Abre la interfaz en `127.0.0.1:8000`.
Comprueba que las cinco pestañas estén disponibles y deja a mano los gráficos
conservados. Usa un corpus preparado antes de grabar y mantén el `.env`
fuera de pantalla.

| Tiempo | Qué mostrar | Qué explicar |
| --- | --- | --- |
| 0:00–0:35 | Interfaz unificada y sus cinco pestañas | Un servidor monta una base y sesiones independientes por parte. React consume las rutas de cada pestaña. |
| 0:35–2:15 | **Relacional**. Abre `students` y `courses`. Ejecuta la igualdad por clave con y sin índices y el preset de JOIN externo. Muestra la salida de `python -m demos.transactions_demo`. | Heap y secuencial tienen organizaciones distintas. El plan refleja el acceso real. En la comparación con hilos, el resultado sin protección es 1 y con protección y en serie es 2. |
| 2:15–3:20 | **Espacial**. Ejecuta una consulta por radio y muestra los puntos en el mapa. | El R-Tree filtra candidatos y el motor aplica la distancia. Señala el gráfico de radio con R-Tree, escaneo y GiST. |
| 3:20–4:35 | **Texto**. Ejecuta un `MATCH` con BM25. Cambia a TF-IDF y muestra el orden y `SCORE()`. | SPIMI publica el índice invertido persistente. Señala la comparación con PostgreSQL del [informe textual](../EXPERIMENTOS_TEXTO.md). |
| 4:35–5:50 | **Multimedia**. Muestra el preset de imágenes HNSW y el de audio IVF. Reproduce un clip y muestra Recall@10 de imágenes. | SIFT y MFCC producen descriptores. La cuantización y TF-IDF generan los vectores que consultan los índices propios. La escala medida corresponde a imágenes. |
| 5:50–7:55 | **RAG académico**. Ejecuta la secuencia indicada debajo. | La recuperación usa BM25 de la Parte 3 y SQL para los metadatos. OpenAI redacta la respuesta y la aplicación adjunta los pasajes recuperados. |
| 7:55–8:30 | Vuelve a la vista unificada y muestra el README y los enlaces a los experimentos. | El proyecto conserva el corpus y los índices fuera de la interfaz. Los experimentos de las Partes 1–4 y la validación de la aplicación se pueden reproducir desde el repositorio. |

### Secuencia de la Parte 5

1. En **Búsqueda textual**, selecciona `chunks`, usa BM25 y busca
   `How does HNSW use a hierarchy of proximity graphs?`. Señala `chunk_id`,
   `paper_id` y los puntajes de los primeros pasajes.
2. En el editor ejecuta `SELECT paper_id, title, authors, year, abstract FROM papers WHERE paper_id = 1;`.
   Señala que el `paper_id` enlaza pasajes y metadatos.
3. En **Consulta los papers**, envía la misma pregunta. Deja visible la
   espera y abre `S1` cuando llegue la respuesta. Contrasta con el pasaje
   la afirmación de que la búsqueda comienza en la capa superior.
4. Si queda tiempo, envía `zqxacademicnonmatch2026`. La interfaz muestra
   el aviso de cero coincidencias y el flujo termina sin generación.

## Guion ampliado de la demo relacional (≈8 minutos)

Los bloques siguientes conservan la secuencia detallada de la Parte 1
para ensayos y como material de apoyo para la defensa.

### Preparación (antes de grabar)

```bash
python scripts/setup_demo.py --reset
(cd frontend && npm run build)
python -m api --allow-writes
```

- Abrir <http://127.0.0.1:8000> en **dos pestañas** (A y B).
- Tener a mano `docs/experimentos/` con los gráficos.
- Ventana del navegador a 1400 px o más, para que se vean los cuatro paneles.

### 1. Presentación (0:00–0:45)

**Pantalla:** la interfaz completa.

**Decir:** "Construimos un gestor de bases de datos relacional desde cero, en
Python: páginas en disco, Heap y archivo secuencial, índices B+ y hash
extensible, algoritmos externos, un parser SQL propio y transacciones con
locks. No usamos ningún DBMS por debajo."

### 2. Archivos e índices (0:45–1:45)

**Pantalla:** panel **Archivos**. Clic en `students`, luego en `courses`.

**Decir:** "`students` es un Heap File con un índice hash único sobre `id` y un
B+ sobre `age`. `courses` es un archivo secuencial ordenado por `code`, con un
B+ agrupado: el orden físico de las filas coincide con el del índice. Se ven
las páginas, el tamaño en disco y las entradas de cada índice."

### 3. Planes reales (1:45–3:30)

**Pantalla:** panel **Consulta**, presets en orden; después de cada uno, el
panel **Plan**.

| Preset | Qué señalar en el plan |
|---|---|
| Igualdad por clave | `IndexScan` sobre `students_id_hash`: el planner eligió el hash |
| Rango | `IndexScan` sobre el B+ `students_age_bplus` |
| Filtro y ORDER BY | `ExternalSort` para el ORDER BY |
| Igualdad por clave con **Usar índices** desmarcado | Cambia a `TableScan` y el resultado es el mismo |

**Decir:** "El plan no es un dibujo: se construye a partir de los operadores
que se ejecutaron, con sus páginas leídas y su tiempo. Si desactivamos los
índices, el motor recorre la tabla."

### 4. Algoritmos externos (3:30–4:30)

**Pantalla:** preset **JOIN + GROUP BY con disco**; en el plan, las métricas
de volcado a disco.

**Decir:** "Con 192 KiB de memoria, el join usa Grace Hash Join, el GROUP BY
usa hashing externo y el ORDER BY un sort externo con k-way merge. Aquí se ve
cuánto escribieron a disco en archivos temporales, que se borran al terminar."

### 5. Errores (4:30–5:00)

**Pantalla:** preset **Error semántico**, luego repetir un preset válido.

**Decir:** "Los errores se reportan con su línea y columna, y el motor sigue
funcionando sin reiniciar."

### 6. Transacciones y concurrencia (5:00–6:30)

**Pantalla:** pestañas A y B lado a lado.

1. A: **BEGIN**, luego `INSERT INTO enrollments VALUES (9, 'X');`
2. B: `SELECT COUNT(*) AS n FROM enrollments;` → B queda esperando:
   «Esperando lock S sobre enrollments, retenido por T…».
3. A: **END** → B recibe 5 al instante.
4. Repetir con **ROLLBACK** en A → el conteo vuelve a su valor.

**Decir:** "Cada pestaña es una sesión. La escritura de A toma un lock
exclusivo sobre la tabla hasta que confirma; la lectura de B espera. Con
ROLLBACK, el motor restaura la tabla."

### 7. Crear una tabla desde CSV (6:30–7:00)

**Pantalla:** **Nueva tabla** → importar un CSV, elegir Heap o Secuencial y un
índice → consultar la tabla nueva.

### 8. Resultados experimentales (7:00–8:00)

**Pantalla:** gráficos `01_insercion.png`, `02_busqueda_pk.png`,
`07_igualdad.png`, `09_rango_10pct.png`, `11_carga_mixta.png`.

**Decir:**
- "Con 100 000 registros, el Heap inserta 36 veces más rápido que el
  secuencial, pero el secuencial busca por clave 260 veces más rápido."
- "El hash es el mejor para igualdad; el B+ para rangos chicos. Con rangos del
  10 % conviene recorrer la tabla, y el planner por reglas no lo sabe."
- "El B+ agrupado sufre con inserciones porque se reconstruye cada vez."
- "El detalle está en `docs/EXPERIMENTOS.md`."
