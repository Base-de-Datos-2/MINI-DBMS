# Interfaz de MINI-DBMS

La interfaz presenta las tablas y los datos espaciales del motor mediante
React, TypeScript y la API REST. Su alcance corresponde a las Partes 1 y 2
de [Proyecto_Final.pdf](../Proyecto_Final.pdf).

## Organización y uso

El espacio relacional conserva cuatro paneles: archivos, consulta, resultados
y plan de ejecución. La exploración espacial añade el mapa y controles para
consultar una tabla registrada mediante radio, k vecinos o polígono.

El mapa usa proyección Mercator y una rejilla de coordenadas, sin descargas
cartográficas externas. Permite desplazar, acercar, alejar y elegir centro.
El formulario acepta vértices por línea y valida el dominio antes de enviar
la consulta; el motor realiza la validación geométrica y la búsqueda.

El botón **Cargar consulta en SQL** prepara radio o k-NN en el editor y vincula
`mi_ubicacion` a esa consulta. El parámetro se muestra de forma explícita. Las
consultas de polígonos usan el endpoint tipado, no una extensión SQL inexistente.

Los esquemas, registros, resultados, planes y estadísticas proceden de la API.
La interfaz no ejecuta búsquedas locales para sustituir al R-Tree ni completa
resultados con datos inventados. Cambiar una opción modifica la siguiente
petición; no cambia retroactivamente la respuesta de una consulta anterior.

Cada pestaña abre su propia sesión. Los botones de transacción envían las
mismas sentencias que el editor. Un error se conserva junto a la consulta que
lo produjo; una sesión nueva no vuelve a ejecutar esa sentencia.

## Criterios de diseño

Las guías locales [gpt-taste](../skills/gpt-taste/SKILL.md) y
[minimalist-ui](../skills/minimalist-ui/SKILL.md) orientan la jerarquía,
distribución y estados de interacción. Se aplican al espacio de trabajo:
superficies claras, contraste legible, controles consistentes, tipografía
distinta para SQL y datos, y movimiento discreto.

Los paneles académicos y el mapa tienen prioridad sobre ejemplos de páginas
promocionales. No se añaden testimonios, fotografías de relleno o efectos de
scroll que dificulten escribir consultas. El diseño debe funcionar con
teclado, pantallas estrechas y preferencia de movimiento reducido.

## Cobertura funcional

Las páginas citadas son páginas físicas del PDF.

| Fuente | Requisito | Integración | Criterio de aceptación |
|---|---|---|---|
| Pág. 2, §2.1.5 | Tablas cargadas y estructura | Metadatos de `/api/tables` y detalle de tabla | Seleccionar una tabla muestra sus columnas, tipos, organización e índices reales |
| Pág. 2, §2.1.5 | Editor SQL | `/api/query` | Ejecutar texto libre o un ejemplo una sola vez, mediante botón o atajo |
| Pág. 2, §2.1.5 | Resultados tabulares | Filas y columnas de la respuesta SQL | Distinguir vacío, completo, limitado y error; conservar valores y orden |
| Pág. 2, §2.1.5 | Plan de ejecución | Descriptores y mediciones del motor | Mostrar accesos, índices y secuencia de operadores; identificar el alcance de mediciones parciales |
| Pág. 2, §2.1.4 | Agrupar operaciones | Sesión propia, BEGIN/END/ROLLBACK | Mantener el grupo entre peticiones; confirmar/deshacer y mostrar espera o cancelación |
| Pág. 3, §2.2.2 | Mapa interactivo de puntos | `/api/spatial/tables`, filas de la tabla y coordenadas registradas | Visualizar puntos, desplazar/ampliar y conservar el orden latitud/longitud |
| Pág. 3, §2.2.1–2.2.2 | Resaltar resultados espaciales | `/api/spatial/query` | Radio, k-NN y polígono resaltan exclusivamente las coincidencias devueltas |
| Pág. 3, §2.2.1 | Ambas métricas | Parámetro `metric` | Haversine y Euclidiana producen distancias del backend en metros |
| Pág. 3, §2.2.3 | SQL espacial | SQL y parámetros por petición | Ejecutar los ejemplos de radio y orden por `mi_ubicacion`, con plan real |
| Pág. 2, §2.1.6; pág. 3, §2.2.4 | Comparativas y gráficos | Resultados conservados en `docs/experimentos` y `docs/figuras/spatial` | Mantener enlaces legibles, unidades, tamaños y procedencia de las mediciones |

Los gráficos son entregables experimentales; el PDF no exige convertirlos
en un quinto panel relacional ni volver a medir desde el navegador.

## Plan de integración

| Etapa | Trabajo | Dependencia | Validación |
|---|---|---|---|
| 1 | Reutilizar el cliente HTTP, sesiones y cuatro paneles; mejorar organización, legibilidad y estados | Contratos relacionales existentes | Pruebas de estados, comprobación de tipos y compilación |
| 2 | Exponer/consumir metadatos espaciales, conservar el orden de ejes y obtener puntos reales | Tabla con mapeo espacial registrado | Contrato HTTP, tabla vacía y errores controlados |
| 3 | Integrar mapa, radio, k-NN, polígono y ambas métricas | Cliente tipado y metadatos espaciales | Comparar resultados del navegador con la respuesta real; límites y resultados vacíos |
| 4 | Conectar ejemplos SQL espaciales y parámetros de ubicación por consulta | Motor SQL y sesión del editor | Ejemplos del PDF, planes e independencia de parámetros |
| 5 | Comprobar escritorio, móvil, teclado, errores y transacciones; consolidar la guía | Etapas anteriores | Servidor y navegador reales, regresión, enlaces y compilación final |

## Convenciones espaciales

- SQL y HTTP reciben `[latitud, longitud]`; un proveedor cartográfico puede
  utilizar el orden contrario y debe adaptarse en su frontera.
- Dominio: latitud `[-12.30, -11.80]`, longitud `[-77.25, -76.75]`.
- Radio y distancias: metros. Euclidiana utiliza un plano local; Haversine
  utiliza distancia sobre una esfera.
- Polígonos: simples, sin huecos, con borde incluido. Los datos de demostración
  y sus zonas son sintéticos.
- Los puntos con coordenadas iguales pueden representar filas distintas.
  Su identidad no debe perderse al mostrarlos o seleccionar resultados.
- La vista de filas es limitada. Los contadores deben distinguir el total
  conocido, los puntos visibles y las coincidencias devueltas.

## Verificación

Desde `frontend/`:

```bash
npm test
npm run typecheck
npm run build
```

La validación funcional requiere además el servidor real y un navegador:
consulta relacional, plan con/sin índice, error y recuperación, selección de
tabla, búsquedas espaciales con ambas métricas, polígono, parámetros SQL,
transacciones y distribución en pantalla estrecha.

## Estado de la entrega

La interfaz relacional y espacial está integrada con el motor existente.
Se verificaron los cuatro paneles, resultados y planes reales, sesiones,
consultas espaciales y distribución de escritorio y móvil con Chromium.
No se implementaron las Partes 3, 4 y 5. Los gráficos experimentales existentes
permanecen enlazados desde el README; no se repitieron sus mediciones.

Validación realizada el 4 de octubre de 2026, usando bases nuevas independientes:

- Regresión Python completa: 3 032 pruebas aprobadas con advertencias como errores
  (`python -m pytest -q -W error`), incluyendo la instalación editable actual.
- Frontend: 43 pruebas aprobadas; TypeScript y compilación Vite aprobados.
- API, protección de evidencias e importaciones aisladas: 38 pruebas aprobadas.
- Servidor TCP espacial: 18 comprobaciones aprobadas, incluidas ambas métricas,
  resultados diferenciales, espera de locks, commit, rollback y reapertura.
- Chromium relacional: 11 comprobaciones aprobadas, incluidos planes con/sin
  índices, errores, dos pestañas concurrentes, commit y rollback.
- Chromium espacial: 24 comprobaciones aprobadas, incluidos puntos persistidos,
  radio con ambas métricas, k-NN con empates, polígono, SQL parametrizado,
  resultados vacíos, total SQL desconocido, errores y recuperación, teclado
  y ausencia de desbordamiento en 1500 × 1000
  y 390 × 844 píxeles. Sin errores JavaScript.

Capturas de la interfaz verificada:
[escritorio](figuras/frontend/escritorio.png) y
[móvil](figuras/frontend/movil.png).

El mapa es una visualización geográfica sin capa de calles. Los resultados y
puntos se limitan a las filas recibidas: no representan necesariamente todos
los registros. SQL conserva como desconocido un total que el motor no calculó.
La consulta espacial tipada entrega su total conocido y limita su presentación.

Las verificaciones actuales utilizan datos sintéticos de demostración; no
acreditan rendimiento de la interfaz sobre 100 000 puntos visibles a la vez.
No quedan pendientes funcionales identificados en estos flujos. El siguiente
punto de continuación es preparar la demostración con los conjuntos de entrega;
las siguientes partes requieren una autorización independiente.
