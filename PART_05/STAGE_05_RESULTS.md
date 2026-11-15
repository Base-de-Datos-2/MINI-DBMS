# Parte 5 — Resultados de la fase 5

- Estado técnico `PASS` en la rama `parte5-fase4-en_adelante`.
- Base de la fase `92a42a7`. La revisión de contenido H3–H6 de la fase 4 sigue registrada en su [informe](STAGE_04_RESULTS.md).

## Interfaz

La pestaña **Parte 5 · RAG académico** muestra el chat encima de los
controles existentes de SQL y búsqueda textual. Envía únicamente la
pregunta a `POST /parte5/api/rag/ask` mediante el cliente de la pestaña.
Cada pregunta es independiente. El panel impide envíos duplicados mientras
espera y conserva las respuestas de esta visita al cambiar de pestaña.

Una respuesta `answered` muestra el texto del modelo y permite abrir cada
fuente con su título, autores, año y pasaje completo. Así se presenta
también una respuesta de evidencia insuficiente. Si no hubo coincidencias,
el chat muestra un aviso específico. En caso de fallo, conserva la pregunta
para volver a enviarla y muestra el identificador de solicitud si existe.

## Verificación en navegador

El servidor unificado sirvió el frontend compilado en `127.0.0.1:8000`.
Se usó una copia local del corpus verificado de 10 papers y 393 pasajes,
junto con la demo de la Parte 3. Chrome 157.0.8103.52 verificó el flujo con
dos respuestas reales de `gpt-6-luna` y una consulta sin coincidencias.

| Pregunta | Resultado observado en el chat | ID de solicitud |
| --- | --- | --- |
| `How does HNSW use a hierarchy of proximity graphs?` | La respuesta describió la jerarquía, las escalas de distancia y el inicio en la capa superior. La UI mostró los pasajes `1`, `3` y `5` con sus metadatos. | `c2f051edf7dc4475bc731884fcb23712` |
| `How do I change the oil in a 2015 Toyota Corolla?` | El modelo indicó que la evidencia era insuficiente. La UI mostró los tres pasajes recuperados (`143`, `362` y `325`). | `8590fe260b8d46b68317ae1ff6bfaeb9` |
| `zqxacademicnonmatch2026` | `no_context` con el aviso en español y sin lista de fuentes. | — |

El texto y los metadatos que se vieron en el navegador coincidieron con el
JSON del endpoint. La ejecución controlada cubrió el bloqueo de envíos,
la conservación del historial y del editor SQL de la Parte 3 al cambiar
de pestaña, la apertura de fuentes con teclado, el escape de HTML en
respuestas y pasajes y el estado de timeout `504`. El panel no desbordó
horizontalmente a 390 px de ancho.

La verificación del corpus después de detener el servidor dio `PASS` y
confirmó la misma generación SPIMI y huella lógica de la fase 4.

Pasaron las 53 pruebas de frontend (`npm test`) y la compilación de
producción (`npm run build`). Se comprobó que la clave configurada no
aparecía en los tres archivos generados en `frontend/dist`. Las solicitudes
del navegador tampoco llevaban credenciales del proveedor ni sesión SQL.

## Reproducción

Prepara los datos académicos y la configuración local según el
[README](../README.md#parte-5--generación-de-respuestas-con-fuentes). Con
la Parte 5 preparada, agrega la demo textual al mismo directorio y levanta
el servidor unificado desde la raíz.

```powershell
python -X utf8 scripts/setup_all.py --only parte3
python -X utf8 -m api --all --data-dir data/generated/todas --host 127.0.0.1 --port 8000
```

En `frontend/`, instala las dependencias y compila. Ejecuta la prueba
controlada con un Chromium de Playwright instalado o establece
`BROWSER_EXECUTABLE_PATH` al ejecutable local de Chrome o Edge.

```powershell
npm ci
npm run build
npm test
npm run test:browser:academic
```

Para repetir la comprobación con el proveedor real y la clave local,
ejecuta `npm run test:browser:academic -- --live`. Esa variante envía dos
consultas de generación. La prueba controlada puede ejecutarse sin clave.
