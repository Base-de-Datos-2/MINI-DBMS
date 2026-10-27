# Demo: tablas creadas desde SQL y consultas espaciales

Esta versión conecta el DDL del motor con el registro persistente del owner de
la demo. La API acepta CREATE TABLE cuando se inicia con `--allow-writes`.
El frontend actualiza Archivos y la lista espacial después de una creación SQL.

## Iniciar una base de prueba nueva

Desde la raíz del proyecto, con las dependencias del README instaladas:

```bash
python scripts/setup_spatial.py --data-dir data/generated/demo_sql_espacial
python -m api --spatial --allow-writes --data-dir data/generated/demo_sql_espacial
```

La preparación requiere un directorio inexistente y no reemplaza una base
anterior. En otra terminal:

```bash
cd frontend
npm install
npm run dev
```

Abre http://127.0.0.1:5173. Para servir la interfaz compilada desde la API,
ejecuta `npm run build` en frontend y abre http://127.0.0.1:8000.

## Crear y consultar desde el editor

Ejecuta cada sentencia por separado; el editor acepta una sentencia por envío.
Si repetiste la demostración, usa otro nombre de tabla.

```sql
CREATE TABLE locales_demo (
  id INTEGER PRIMARY KEY,
  nombre VARCHAR(80),
  latitud FLOAT,
  longitud FLOAT
);
```

El owner crea un Heap persistente y un B+ único para la clave primaria.
Por convención, una tabla Heap con `id INTEGER`, `latitud FLOAT`, `longitud FLOAT`
y sin una columna física llamada `ubicacion` se registra automáticamente como
espacial. Esto también aplica a tablas creadas/importadas desde Archivos.
El mapeo y el R-Tree se reconstruyen/reabren con las definiciones persistentes.
Tablas con otros nombres de columnas siguen siendo relacionales; esta versión
no añade una sintaxis para configurar mapeos arbitrarios.

```sql
INSERT INTO locales_demo VALUES (1, 'Centro', -12.0464, -77.0428);
```

```sql
INSERT INTO locales_demo VALUES (2, 'Local cercano', -12.0500, -77.0400);
```

```sql
INSERT INTO locales_demo VALUES (3, 'Local distante', -12.1500, -77.1000);
```

```sql
SELECT * FROM locales_demo;
```

Radio de 1 km, distancia Haversine en metros:

```sql
SELECT * FROM locales_demo
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 1000;
```

Dos vecinos más cercanos:

```sql
SELECT * FROM locales_demo
ORDER BY distancia(ubicacion, POINT(-12.0464, -77.0428)) LIMIT 2;
```

Distancia euclidiana en el plano local:

```sql
SELECT * FROM locales_demo
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428), 'euclidean') < 1000;
```

En Mapa selecciona `locales_demo`, actualiza puntos y prueba radio y k-NN.
Para polígono, pega estos vértices (latitud, longitud):

```text
-12.0600, -77.0600
-12.0600, -77.0200
-12.0300, -77.0200
-12.0300, -77.0600
```

Las búsquedas de radio de 1 km, k=2 y este polígono devuelven IDs 1 y 2.
El polígono se consulta desde el panel espacial; no se añade SQL de polígonos.
Desactiva Usar índices para comparar con recorrido secuencial.

## Transacciones, borrado y persistencia

```sql
BEGIN TRANSACTION;
```

```sql
INSERT INTO locales_demo VALUES (4, 'Temporal', -12.0450, -77.0430);
```

```sql
ROLLBACK;
```

```sql
SELECT * FROM locales_demo WHERE id = 4;
```

El resultado debe estar vacío. Para confirmar una inserción usa
`END TRANSACTION` en lugar de `ROLLBACK`.

```sql
DELETE FROM locales_demo WHERE id = 3;
```

Detén la API con Ctrl+C y vuelve a ejecutar el mismo comando de API, con el
mismo directorio. No repitas el preparador. Las tablas, restricciones y puntos
se reabren; los IDs persistentes son 1 y 2.

## Alcance

CREATE admite INT/INTEGER, FLOAT, BOOLEAN y VARCHAR(n), y PRIMARY KEY inline.
Las longitudes VARCHAR y la unicidad se conservan al reabrir. CREATE es DDL
independiente: hazlo fuera de BEGIN/END TRANSACTION. Los nombres y tipos del
mapeo automático son los indicados arriba. Se conserva el dominio espacial
local de Lima: latitud [-12.30, -11.80], longitud [-77.25, -76.75].
No se implementan UPDATE, ALTER, DROP, CREATE INDEX, tipos POINT persistentes,
SQL estándar completo ni recuperación WAL. Es una extensión concreta de la
demo para las Partes 1 y 2.
