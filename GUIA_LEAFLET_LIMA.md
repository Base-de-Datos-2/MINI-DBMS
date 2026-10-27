# Demo espacial de Lima con Leaflet y OpenStreetMap

Esta versión conserva CREATE TABLE por SQL y añade calles, marcadores con
nombre/ID/coordenadas, radio, k-NN, polígonos y dibujo con clics. Las consultas
siguen usando Heap y el R-Tree propio del backend. OpenStreetMap aporta el fondo
cartográfico; sus etiquetas no se importan automáticamente a la base.

## Inicio en Windows (CMD o PowerShell)

Extrae el ZIP en una carpeta nueva. Entra en **MINI-DBMS-leaflet**: esta es la
carpeta que contiene `pyproject.toml`, `api`, `scripts` y `frontend`.
Detén cualquier servidor anterior con Ctrl+C antes de iniciar esta versión.

```cmd
cd MINI-DBMS-leaflet
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test,api,bench]"
.\.venv\Scripts\python.exe scripts/setup_lima.py --data-dir data/generated/demo_lima
.\.venv\Scripts\python.exe -m api --spatial --allow-writes --data-dir data/generated/demo_lima
```

Python 3.11+ (incluido tu Python 3.12.2) es compatible. El frontend ya está
compilado: no necesitas Node/npm para arrancar. El preparador crea una base
nueva y rechaza un directorio existente. No lo repitas al reiniciar. Para una
segunda demo independiente usa otro nombre de directorio en ambos comandos.

Abre http://127.0.0.1:8000 y recarga con Ctrl+F5 para actualizar los archivos.
Deja la terminal abierta. En Linux usa `python3 -m venv .venv` y reemplaza el
ejecutable de Windows por `.venv/bin/python`.

## Prueba con lugares identificables

En **Mapa**, selecciona `lugares_lima` y pulsa **Ver puntos**. Deben aparecer
20 marcadores alrededor de la plaza Dos de Mayo. Pulsa un marcador para ver
nombre, ID, coordenadas, categoría y URL de su nodo OpenStreetMap.

El centro exacto del nodo del monumento **Combate del Dos de Mayo** es:

- Latitud: `-12.0463851`
- Longitud: `-77.0427655`
- ID del dataset: `13`

Pruebas:

1. Radio, Haversine, centro anterior y `200` metros. El monumento debe aparecer
   entre las coincidencias. El contorno azul representa el área consultada.
2. Repite desactivando **Usar R-Tree**. Las mismas filas deben coincidir;
   el orden de una consulta sin ORDER BY puede cambiar. Los tiempos son del motor.
3. k vecinos con `k = 5`. Debe devolver cinco registros, empezando por el ID 13.
4. Polígono: pega estos vértices; debe contener los 20 puntos del extracto.

```text
-12.048, -77.045
-12.048, -77.040
-12.043, -77.040
-12.043, -77.045
```

5. Para dibujar otro polígono, activa **Dibujar vértices con clics en el mapa**,
   marca tres o más puntos y pulsa **Buscar en el mapa**. El motor cierra y
   valida el contorno; rechaza polígonos no simples. Limpiar vértices borra el
   borrador; la respuesta anterior permanece hasta enviar otra consulta.
6. Repite radio y k-NN con Euclidiana local. El contorno utiliza esa misma
   métrica; Leaflet no calcula cuáles registros coinciden.

## SQL y escrituras

Ejecuta cada sentencia por separado:

```sql
SELECT * FROM lugares_lima
WHERE distancia(ubicacion, POINT(-12.0463851, -77.0427655)) < 200;
```

```sql
SELECT * FROM lugares_lima
ORDER BY distancia(ubicacion, POINT(-12.0463851, -77.0427655))
LIMIT 5;
```

Para probar tus propios puntos sin alterar el extracto:

```sql
CREATE TABLE locales_demo (
  id INTEGER PRIMARY KEY,
  nombre VARCHAR(80),
  latitud FLOAT,
  longitud FLOAT
);
```

```sql
INSERT INTO locales_demo VALUES (1, 'Punto de prueba', -12.0464, -77.0428);
```

La tabla se registra automáticamente como espacial por la convención de columnas.
Selecciónala en el mapa. Actualizar puntos permite renovar la vista; las
escrituras desde SQL también activan la recarga. Un clic en el mapa selecciona
centro o vértice; no inserta registros.

BEGIN TRANSACTION, END TRANSACTION y ROLLBACK conservan el funcionamiento de
la demo anterior. CREATE TABLE se ejecuta fuera de una transacción explícita.
UPDATE, ALTER, DROP y CREATE INDEX no forman parte de este subconjunto SQL.

Para comprobar persistencia: detén con Ctrl+C y repite únicamente el comando
`python -m api` con el mismo directorio. No ejecutes nuevamente setup_lima.py.

## Datos, límites y conexión

`data/lima/lugares_lima.csv` contiene 20 nodos con nombres y coordenadas copiados
de la API de OpenStreetMap el 13/10/2026. `fuente.json` registra consulta,
selección, licencia ODbL y atribución. Es un extracto pequeño del centro de
Lima, no un inventario completo; la existencia en OSM no acredita horarios ni
operación actual de los establecimientos. Las tablas tiendas/restaurantes del
preparador original siguen siendo fixtures sintéticos y se identifican aparte.

Dominio admitido: latitud [-12.30, -11.80], longitud [-77.25, -76.75]. SQL,
HTTP y Leaflet reciben latitud primero. La vista previa y las respuestas se
limitan a 500 puntos; los contadores indican las filas recibidas.

Las calles requieren acceso a `https://tile.openstreetmap.org`. Si falla la
conexión se muestra un aviso y un botón para reintentar. Los puntos y consultas
siguen funcionando. No se descarga el mapa para uso offline ni se precargan
ciudades; se conserva la atribución visible y el navegador gestiona la caché.

## Desarrollo

Desde frontend: `npm ci`, `npm test`, `npm run build`. El build comprueba
TypeScript y actualiza frontend/dist, que sirve el backend. No hace falta una
clave de Google Maps. El código principal está en SpatialPanel.tsx y LeafletMap.tsx.

Para repetir la prueba funcional en Chromium, después de instalar las
herramientas de desarrollo en frontend, ejecuta `npx playwright install chromium`
y `npm run test:browser`. El script utiliza una base temporal nueva; no modifica
tu directorio de datos. Consulta docs/VERIFICACION_LEAFLET.md para resultados
y límites de la comprobación cartográfica en el entorno de pruebas.


## 11. Comandos SQL adicionales (versión extendida)

La API de la demo permite ejecutar estas sentencias en el editor SQL con el servidor iniciado mediante `--allow-writes`. Ejecuta una sentencia por envío. Se aplican a tablas creadas mediante SQL o el panel Archivos cuando así se indica.

### Crear un índice B+ no agrupado

```sql
CREATE INDEX idx_lugares_categoria ON lugares_lima (categoria);
```

Para exigir valores únicos en la columna, usa `CREATE UNIQUE INDEX`. La construcción se valida con los datos existentes y el índice se guarda en el registro persistente de la tabla.

### Actualizar filas

```sql
UPDATE lugares_lima
SET categoria = 'Museo actualizado'
WHERE id = 2;
```

También se aceptan varias asignaciones separadas por comas, valores literales o referencias a columnas, y los predicados soportados por el subconjunto SQL actual. Los índices ordinarios y el R-Tree se reconstruyen después de la actualización para mantener sus asociaciones. Se rechazan cambios que violen un índice único o la validación espacial.

### Eliminar un índice

```sql
DROP INDEX idx_lugares_categoria;
```

No se permite eliminar por SQL el índice que garantiza una clave primaria.

### Eliminar una tabla creada por SQL

```sql
DROP TABLE locales_demo;
```

El comando elimina la definición registrada, sus índices y los archivos que pertenecen a esa tabla. Por seguridad, `DROP TABLE` por SQL está limitado a tablas creadas dinámicamente; las tablas declaradas por el código de la demo no se eliminan.

### Límites importantes

- Estas operaciones se ejecutan como operaciones independientes y no se admiten dentro de una transacción explícita `BEGIN TRANSACTION` / `END TRANSACTION`.
- `CREATE INDEX` crea índices B+ no agrupados; no se ha añadido la cláusula `USING` para elegir otro tipo.
- `UPDATE` no admite expresiones aritméticas (`columna = columna + 1`) ni `NULL`.
- Estas extensiones se exponen mediante la API HTTP usada por el frontend. La API serializa las operaciones y persiste las definiciones; el `SqlEngine` de bajo nivel sigue rechazando estas familias si se invoca directamente fuera de ese adaptador.
