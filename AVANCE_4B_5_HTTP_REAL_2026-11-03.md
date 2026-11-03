# Bloques 4B y 5 — avance validado (2026-11-03)

## Cambios concretos de esta iteración

- `tests/text/test_4b_5_real_http_acceptance.py`: **6 pruebas nuevas** que ejecutan FastAPI `TestClient` sobre una base persistente con Heap sellado e índice SPIMI real, verificando ambos modelos BM25/TF_IDF, rutas con/sin índice, EXPLAIN, EXPLAIN ANALYZE, reapertura y resultados estables, endpoint del panel, dos peticiones concurrentes, política de escritura y la primera consulta oficial.
- `frontend/src/components/TextPanel.tsx`: la actualización de colecciones usa contador de generación para evitar respuestas HTTP obsoletas; al desmontar el componente invalida ambas familias de solicitudes; evita búsquedas vacías.
- Se preserva la implementación anterior del adaptador SQL textual, registro persistente, API de búsqueda y panel React.

## Verificación efectivamente realizada

- `python -m pytest -q tests/text --disable-warnings --maxfail=1`: **481 passed**.
- `python -m pytest -q tests/api --disable-warnings --maxfail=1`: **181 passed**.
- Total **662 pruebas** de los dos grupos, todas aprobadas.
- `npm run build`: **no pasó** porque faltan dependencias locales de Vite (`Cannot find type definition file for vite/client`). No se certifica compilación del frontend.
- Una ejecución combinada de ambos grupos superó el tiempo de espera; se ejecutaron después por separado y ambos terminaron correctamente.

## Limitaciones conocidas antes de afirmar 100 %

1. `MATCH` usa el adaptador SQL del servicio HTTP, no un operador físico integrado en el `SqlEngine` autónomo.
2. Falta instalar dependencias npm y completar build y pruebas de navegador de React.
3. No se ha ejecutado la suite total de módulos relacionales, espaciales y multimedia.
4. La demo requiere publicar una colección real; no se añade una colección ficticia.

## Reproducir

```bash
python -m pytest -q tests/text tests/api
cd frontend
npm ci
npm run build
```

**Estado: avance significativo y comprobado, NO entrega final al 100 %.**
