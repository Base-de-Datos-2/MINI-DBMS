# Integración Leaflet + OpenStreetMap — verificación del 13/10/2026

## Cambio y alcance

La copia de la demo con CREATE TABLE SQL conserva el motor propio y añade
Leaflet 1.9.4, cartografía OpenStreetMap por HTTPS, marcadores con nombres y
registros, áreas de consulta, escala métrica, ajuste de vista y dibujo de
vértices. Las búsquedas se ejecutan mediante los endpoints y SQL existentes.
No se sustituyen Heap, R-Tree, parser, executor ni transacciones por Leaflet.

Se conserva la precisión del centro: después de enviar la consulta ya no se
redondean las coordenadas a seis decimales. Esto evita que una repetición
con otra estrategia modifique ligeramente la ubicación consultada.
Los textos de los popups se insertan mediante textContent, nunca como HTML
proveniente de los registros. Los IDs se conservan como número o cadena.

El script setup_lima.py prepara exclusivamente una base nueva, con las tablas
sintéticas existentes y una tabla lugares_lima de 20 nodos OSM identificados.
El CSV y su procedencia/licencia están en data/lima. No es un inventario de Lima.

## Resultados actuales

| Comprobación | Resultado |
|---|---|
| Python global, instalación editable de esta copia, advertencias como errores | 3.039 aprobadas |
| API/componentes espaciales seleccionados | 243 aprobadas |
| Preparación de Lima, reapertura y rechazo de sobrescritura | 2 aprobadas, incluidas en la suite global |
| Frontend Vitest | 43 aprobadas |
| TypeScript y Vite | Aprobados |
| Integración espacial sobre TCP, con cierre y reapertura | 18 comprobaciones aprobadas |
| Chromium con servidor real y base temporal | 37 comprobaciones aprobadas |

Las 37 comprobaciones de navegador incluyen popups, conservación de centro,
radio Haversine y Euclidiana con R-Tree/scan, k-NN, polígono con ambas estrategias,
vértices por clic, error de dominio, SQL parametrizado, CREATE TABLE, INSERT,
ROLLBACK, DELETE, renovación del mapa, móvil 390 × 844 y fallo de cartografía.
No se registraron errores JavaScript. En consultas sin orden explícito se
comparan registros normalizados por ID, no un orden que la consulta no garantiza.
Resumen: [leaflet-browser-results.json](leaflet-browser-results.json).

## Reproducción

Desde la raíz, con dependencias Python instaladas:

```bash
python -m pytest -q -W error
python scripts/spatial_integration_check.py --data-dir data/generated/http_check_nuevo --report http-check.json
```

Desde frontend:

```bash
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:browser
```

El navegador usa por defecto la Python del entorno .venv de la raíz. Puede
configurarse PYTHON_EXECUTABLE con otra instalación. BROWSER_EXECUTABLE_PATH
permite indicar un Chromium ya instalado. El script crea un directorio temporal,
prepara una base nueva, inicia y detiene su propio servidor y guarda el reporte
allí; no utiliza la base del usuario. TEST_PORT permite cambiar el puerto 18821.

## Cartografía y límites de la evidencia

El Chromium de este entorno no confía en el certificado del proxy de salida.
Para inspeccionar las calles se utilizó una adaptación **exclusiva del test**:
las peticiones de imágenes del navegador se descargaron con Python/urllib,
que valida TLS con los certificados del entorno, conservando User-Agent y
Referer del navegador. Se inspeccionaron teselas reales de OpenStreetMap y su
alineación con los marcadores. Esa adaptación no forma parte de la aplicación
ni desactiva la validación TLS. El test reproducible de frontend mantiene las
peticiones directas del navegador y verifica que un fallo del proveedor se
informa sin impedir las consultas del backend.

La cartografía depende de Internet y de la disponibilidad del proveedor. Se
mantiene atribución visible, HTTPS, caché normal del navegador y descarga solo
para la vista activa. No hay precarga masiva ni modo offline de cartografía.
La prueba no acredita que el proveedor externo vaya a estar siempre disponible.

Esta verificación corresponde a los flujos descritos y al subconjunto SQL
existente; no afirma ausencia absoluta de errores, SQL completo ni nuevas
mediciones de rendimiento. Los experimentos históricos conservan su alcance.
