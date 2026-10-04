# Guion del video de demostración — Parte 1 (≈8 minutos)

Para quien graba. Cada bloque dice qué mostrar en pantalla y qué decir. Los
tiempos suman unos 8 minutos; el enunciado pide entre 5 y 10.

## Preparación (antes de grabar)

```bash
python scripts/setup_demo.py --reset
(cd frontend && npm run build)
python -m api --allow-writes
```

- Abrir <http://127.0.0.1:8000> en **dos pestañas** (A y B).
- Tener a mano `docs/experimentos/` con los gráficos.
- Ventana del navegador a 1400 px o más, para que se vean los cuatro paneles.

## 1. Presentación (0:00–0:45)

**Pantalla:** la interfaz completa.

**Decir:** "Construimos un gestor de bases de datos relacional desde cero, en
Python: páginas en disco, Heap y archivo secuencial, índices B+ y hash
extensible, algoritmos externos, un parser SQL propio y transacciones con
locks. No usamos ningún DBMS por debajo."

## 2. Archivos e índices (0:45–1:45)

**Pantalla:** panel **Archivos**. Clic en `students`, luego en `courses`.

**Decir:** "`students` es un Heap File con un índice hash único sobre `id` y un
B+ sobre `age`. `courses` es un archivo secuencial ordenado por `code`, con un
B+ agrupado: el orden físico de las filas coincide con el del índice. Se ven
las páginas, el tamaño en disco y las entradas de cada índice."

## 3. Planes reales (1:45–3:30)

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

## 4. Algoritmos externos (3:30–4:30)

**Pantalla:** preset **JOIN + GROUP BY con disco**; en el plan, las métricas
de volcado a disco.

**Decir:** "Con 192 KiB de memoria, el join usa Grace Hash Join, el GROUP BY
usa hashing externo y el ORDER BY un sort externo con k-way merge. Aquí se ve
cuánto escribieron a disco en archivos temporales, que se borran al terminar."

## 5. Errores (4:30–5:00)

**Pantalla:** preset **Error semántico**, luego repetir un preset válido.

**Decir:** "Los errores se reportan con su línea y columna, y el motor sigue
funcionando sin reiniciar."

## 6. Transacciones y concurrencia (5:00–6:30)

**Pantalla:** pestañas A y B lado a lado.

1. A: **BEGIN**, luego `INSERT INTO enrollments VALUES (9, 'X');`
2. B: `SELECT COUNT(*) AS n FROM enrollments;` → B queda esperando:
   «Esperando lock S sobre enrollments, retenido por T…».
3. A: **END** → B recibe 5 al instante.
4. Repetir con **ROLLBACK** en A → el conteo vuelve a su valor.

**Decir:** "Cada pestaña es una sesión. La escritura de A toma un lock
exclusivo sobre la tabla hasta que confirma; la lectura de B espera. Con
ROLLBACK, el motor restaura la tabla."

## 7. Crear una tabla desde CSV (6:30–7:00)

**Pantalla:** **Nueva tabla** → importar un CSV, elegir Heap o Secuencial y un
índice → consultar la tabla nueva.

## 8. Resultados experimentales (7:00–8:00)

**Pantalla:** gráficos `01_insercion.png`, `02_busqueda_pk.png`,
`07_igualdad.png`, `09_rango_10pct.png`, `11_carga_mixta.png`.

**Decir:**
- "Con 100 000 registros, el Heap inserta 36 veces más rápido que el
  secuencial, pero el secuencial busca por clave 260 veces más rápido."
- "El hash es el mejor para igualdad; el B+ para rangos chicos. Con rangos del
  10 % conviene recorrer la tabla, y el planner por reglas no lo sabe."
- "El B+ agrupado sufre con inserciones porque se reconstruye cada vez."
- "El detalle está en `docs/EXPERIMENTOS.md`."
