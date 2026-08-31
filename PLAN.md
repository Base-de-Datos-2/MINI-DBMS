# PLAN.md

## Plan de implementación — Parte 1: Base de Datos Relacional

**Proyecto:** Minigestor de Base de Datos Multimodal  
**Curso:** Base de Datos 2 — 2026-2  
**Alcance de este plan:** Parte 1 — Base de Datos Relacional (Tablas y SQL)

---

# 1. Propósito de este documento

Este documento define el orden de trabajo recomendado para completar la Parte 1 sin romper los requisitos académicos ni acoplar prematuramente componentes de etapas futuras.

Debe leerse junto con:

- `REQUIREMENTS.md` — requisitos oficiales del proyecto;
- `PROJECT_CONTEXT.md` — decisiones técnicas y arquitectura acordada;
- `AGENTS.md` — reglas de trabajo para Codex;
- `ETAPA_01.md` — plan detallado de la primera etapa.

La Parte 1 se implementará en **10 etapas secuenciales**.

La regla principal es:

> No avanzar a la siguiente etapa si la etapa actual no tiene una implementación funcional, pruebas suficientes e integración estable con las etapas anteriores.

---

# 2. Resultado final esperado de la Parte 1

Al terminar la Parte 1, el sistema debe ser capaz de ejecutar un flujo completo similar a:

```text
Usuario
  |
  v
Frontend
  |
  v
REST API
  |
  v
SQL Parser
  |
  v
AST
  |
  v
Planner
  |
  v
Physical Plan
  |
  v
Executor
  |
  +----------------------+
  |                      |
  v                      v
Indexes              Storage Files
  |                      |
  +----------+-----------+
             |
             v
            Pages
             |
             v
            Disk
```

y soportar, como mínimo:

```sql
INSERT INTO students VALUES (...);

SELECT *
FROM students
WHERE id = 100;

SELECT *
FROM students
ORDER BY age;

SELECT career, COUNT(*)
FROM students
GROUP BY career;

DELETE FROM students
WHERE id = 100;
```

Además debe:

- almacenar datos realmente en archivos/páginas;
- implementar Heap File;
- implementar Archivo Secuencial Paginado;
- implementar B+ agrupado;
- implementar B+ no agrupado;
- implementar Extendible Hashing;
- implementar External Sorting con k-way merge;
- soportar `GROUP BY` y `JOIN` con las estrategias requeridas;
- soportar transacciones y control de concurrencia;
- incluir la demostración obligatoria con threads;
- tener los cuatro paneles del frontend;
- producir benchmarks reproducibles para 1K, 10K y 100K registros.

---

# 3. Principios de implementación

## 3.1 Implementar de abajo hacia arriba

Orden conceptual:

```text
Disk
↑
Pages
↑
Storage Files
↑
Indexes
↑
Operators
↑
Planner / Executor
↑
SQL
↑
API
↑
Frontend
```

No comenzar por el frontend.

No comenzar por SQL antes de disponer de operadores físicos funcionales.

No construir índices antes de tener un sistema de almacenamiento estable.

---

## 3.2 Una etapa debe dejar artefactos reutilizables

Cada etapa debe producir componentes que sean usados por la siguiente.

Ejemplo:

```text
ETAPA 2
Page / Record / PageManager
        |
        v
ETAPA 3
HeapFile / SequentialFile
        |
        v
ETAPA 4 y 5
B+ / ExtendibleHash
        |
        v
ETAPA 6
Operators
```

---

## 3.3 No reemplazar los algoritmos requeridos

No usar otro DBMS para simular el motor.

No delegar a pandas/SQLAlchemy/SQLite/PostgreSQL las operaciones que el proyecto pide implementar.

Las librerías solo pueden ser auxiliares.

---

## 3.4 Tests antes de integración mayor

Para cada módulo:

1. test unitario;
2. test funcional;
3. test de persistencia, cuando corresponda;
4. test de integración con la etapa anterior.

---

# 4. Resumen de las 10 etapas

| Etapa | Nombre | Resultado principal |
|---|---|---|
| 1 | Arquitectura y modelo de datos | Contratos y estructuras base |
| 2 | Páginas, registros y persistencia | Capa física confiable |
| 3 | Heap + Secuencial Paginado | Organizaciones de archivos requeridas |
| 4 | B+ Tree | Índices agrupado/no agrupado |
| 5 | Extendible Hashing | Índice hash dinámico |
| 6 | Operadores y algoritmos externos | Motor físico de consultas |
| 7 | Parser, Planner y Executor | SQL funcional |
| 8 | Transacciones y concurrencia | Acceso concurrente seguro |
| 9 | API y Frontend | Interfaz completa |
| 10 | Experimentos e integración | Comparaciones y entrega |

---

# 5. ETAPA 1 — Arquitectura y modelo de datos

Documento detallado:

> `ETAPA_01.md`

## Objetivo

Definir el esqueleto del motor antes de almacenar datos realmente.

## Componentes principales

- estructura de paquetes;
- `DataType`;
- `Column`;
- `Schema`;
- `Record`;
- `RID`;
- metadata de tablas;
- `Catalog`;
- interfaces/contratos de:
  - almacenamiento;
  - índices;
  - operadores.

## Resultado

La etapa termina cuando puede modelarse una tabla y sus registros sin depender todavía de Heap File, B+, SQL o frontend.

## Dependencias

Ninguna.

## No incluye

- páginas binarias;
- Heap File;
- índices;
- parser SQL;
- frontend.

---

# 6. ETAPA 2 — Páginas, registros y persistencia base

## Objetivo

Construir una capa física capaz de serializar datos, escribir páginas y recuperar exactamente la misma información después de cerrar y reabrir el archivo.

## 6.1 Decisiones que deben quedar explícitas

Antes o durante esta etapa deben documentarse:

- tamaño de página;
- formato de `PageHeader`;
- formato de slots;
- estrategia para registros variables;
- formato de `FileHeader`;
- endianness / formato binario;
- representación de `NULL`, si se soporta.

No asumir valores que no aparezcan en `PROJECT_CONTEXT.md`.

## 6.2 Componentes

Posible estructura:

```text
engine/storage/
├── page.py
├── page_header.py
├── serializer.py
├── file_header.py
└── page_manager.py
```

## 6.3 Funciones mínimas

### Page

Debe poder:

```text
insert serialized record
read slot
mark/remove slot
report free space
serialize page
deserialize page
```

La implementación concreta puede variar.

### PageManager

Debe poder:

```text
allocate_page()
read_page(page_id)
write_page(page)
flush()
close()
```

## 6.4 Tests obligatorios

- crear una página;
- insertar un registro;
- serializar;
- escribir en disco;
- cerrar archivo;
- reabrir;
- recuperar el mismo registro;
- manejar múltiples páginas;
- detectar acceso inválido.

## Definition of Done

- persistencia funciona;
- no depende de HeapFile;
- page I/O está encapsulado;
- tests pasan.

---

# 7. ETAPA 3 — Heap File y Archivo Secuencial Paginado

Esta etapa satisface la sección principal de gestión de archivos.

## 7A. Heap File

### Objetivo

Guardar registros en orden de llegada sobre páginas.

### Operaciones mínimas

```text
insert(record) -> RID
read(rid) -> Record
delete(rid)
scan() -> iterator
```

### Requisito clave

Debe reutilizar espacio libre.

No basta con agregar indefinidamente al final.

### Estrategia recomendada

Mantener información suficiente para localizar páginas con espacio disponible.

La estrategia puede ser:

- free list;
- free-page directory;
- free-space map simplificado;

siempre que realmente reutilice espacio.

### Tests

- insertar en una página;
- insertar hasta crear varias páginas;
- eliminar;
- volver a insertar;
- comprobar que se reutiliza el espacio;
- leer por RID;
- scan completo;
- persistencia.

## 7B. Archivo Secuencial Paginado

### Objetivo

Mantener registros ordenados por una clave.

### Operaciones mínimas

```text
insert(record)
search(key)
delete(key or rid)
scan()
reorganize()
```

### Comportamiento requerido

- inserción preserva orden;
- eliminación lazy;
- medición de desperdicio;
- reorganización.

El 30% puede utilizarse como threshold por defecto si se adopta explícitamente.

### Tests

- insertar datos en orden aleatorio;
- comprobar orden final;
- insertar entre dos claves existentes;
- lazy delete;
- calcular porcentaje desperdiciado;
- superar threshold;
- reorganizar;
- verificar que el orden se conserva.

### Definition of Done de ETAPA 3

Ambas organizaciones:

- funcionan sobre la misma capa de páginas;
- persisten en disco;
- tienen tests independientes;
- pueden compararse posteriormente mediante benchmarks.

---

# 8. ETAPA 4 — B+ Tree

## Objetivo

Implementar la estructura B+ requerida y utilizarla en modo agrupado y no agrupado.

## 8.1 B+ Tree genérico

Operaciones mínimas:

```text
insert(key, value)
search(key)
range_search(low, high)
delete(key, value?)
```

Comportamientos estructurales:

- leaf split;
- internal split;
- root split;
- linked leaves;
- redistribution/merge según el algoritmo de eliminación adoptado;
- root shrink cuando corresponda.

## 8.2 B+ no agrupado

Diseño conceptual:

```text
key -> RID
```

Los registros permanecen físicamente independientes del orden del índice.

## 8.3 B+ agrupado

La organización física de datos debe reflejar el orden de la clave.

No basta con poner una bandera:

```text
clustered = True
```

sobre un índice que sigue apuntando a datos arbitrariamente desordenados.

El diseño exacto debe quedar documentado en `PROJECT_CONTEXT.md`.

## Tests

- inserciones sin split;
- leaf split;
- internal split;
- root split;
- igualdad;
- rango;
- eliminación;
- redistribución;
- merge;
- recorrido de hojas;
- casos con claves duplicadas si se permiten.

## Definition of Done

- B+ genérico estable;
- uso no agrupado funcional;
- uso agrupado funcional;
- range queries verificadas;
- persistencia definida/implementada según arquitectura.

---

# 9. ETAPA 5 — Extendible Hashing

## Objetivo

Implementar Hash Dinámico mediante Extendible Hashing.

## Componentes

```text
Directory
Global Depth
Bucket
Local Depth
```

## Operaciones mínimas

```text
insert(key, rid)
search(key)
delete(key, rid)
```

## Comportamientos obligatorios

- función hash;
- acceso por bits relevantes;
- split de bucket;
- incremento de local depth;
- doubling del directory cuando sea necesario;
- actualización correcta de punteros del directory.

La contracción del directorio puede implementarse si la arquitectura la contempla, pero no debe desplazar funcionalidades explícitamente requeridas.

## Tests

- igualdad;
- colisiones;
- bucket lleno;
- split;
- directory doubling;
- múltiples buckets compartidos;
- delete;
- persistencia si el diseño de índices es persistente en esta etapa.

## Definition of Done

El índice debe demostrar por qué es apropiado para búsquedas exactas y por qué no es la estructura elegida para rangos.

---

# 10. ETAPA 6 — Operadores relacionales y algoritmos externos

## Objetivo

Construir la ejecución física antes de conectar SQL.

## 10.1 Interfaz de operador

Recomendación conceptual:

```text
open()
next()
close()
```

o un iterador Python equivalente.

No mezclar sintaxis SQL dentro de los operadores.

## 10.2 Operadores mínimos

```text
TableScan
IndexScan
Filter
Projection
ExternalSort
Group
Join
```

## 10A. TableScan

Debe recorrer registros activos de una tabla.

Tests:

- tabla vacía;
- una página;
- múltiples páginas;
- registros eliminados.

## 10B. IndexScan

Debe recuperar registros usando B+ o Hash cuando corresponda.

Tests:

- igualdad;
- rango con B+;
- RID inválido;
- índice vacío.

## 10C. Filter

Debe evaluar condiciones soportadas por el subconjunto SQL.

Separar:

```text
expression evaluation
```

de:

```text
storage
```

## 10D. Projection

Selecciona columnas de cada fila.

## 10E. External Sort

### Algoritmo requerido

External Sorting con k-way merge.

Fase 1:

```text
input
 |
 v
memory-sized chunks
 |
 v
sort each chunk
 |
 v
sorted runs on disk
```

Fase 2:

```text
run1 --\
run2 ---\
run3 ----> k-way merge -> output
runN ---/
```

Debe existir un presupuesto de memoria configurable o una abstracción equivalente que obligue a generar múltiples runs durante pruebas.

## 10F. GROUP BY

Implementar una estrategia válida basada en:

- External Hashing;
- uso estratégico de índices;
- o combinación documentada.

No delegar a pandas.

## 10G. JOIN

Recomendado:

1. Nested Loop Join como baseline;
2. Hash Join;
3. Index-assisted join cuando sea posible.

Debe existir por lo menos una estrategia optimizada que satisfaga los requisitos del proyecto.

## Definition of Done de ETAPA 6

Una consulta física puede construirse manualmente, sin SQL, por ejemplo:

```text
Projection(name)
  |
Filter(age > 20)
  |
TableScan(students)
```

y ejecutarse correctamente.

---

# 11. ETAPA 7 — SQL Parser, Planner y Executor

## Objetivo

Transformar SQL en los operadores físicos de la Etapa 6.

## 11.1 Grammar

Soportar solamente el subconjunto requerido.

No implementar un estándar SQL completo.

## 11.2 AST

Crear nodos semánticos independientes del parser concreto.

Ejemplo:

```text
SelectStatement
├── columns
├── table
├── where
├── order_by
└── group_by
```

## 11.3 Planner

Inicialmente puede ser rule-based.

Ejemplos:

```text
WHERE pk = value + hash index
    -> Hash IndexScan

WHERE indexed_key BETWEEN a AND b + B+
    -> B+ RangeScan

sin índice útil
    -> TableScan + Filter
```

## 11.4 Executor

Debe ejecutar el physical plan real.

El plan expuesto al frontend debe representar exactamente esos operadores.

## SQL mínimo a probar

```sql
INSERT INTO ...
VALUES (...);
```

```sql
SELECT *
FROM ...;
```

```sql
SELECT *
FROM ...
WHERE ...;
```

```sql
SELECT ...
FROM ...
ORDER BY ...;
```

```sql
SELECT ...
FROM ...
GROUP BY ...;
```

```sql
DELETE FROM ...
WHERE ...;
```

Además deben existir los JOIN necesarios para demostrar el operador requerido.

## Definition of Done

- parser produce AST;
- planner produce physical plan;
- executor produce resultados;
- índices reales pueden ser elegidos;
- plan de ejecución refleja el camino real.

---

# 12. ETAPA 8 — Transacciones y concurrencia

## Objetivo

Permitir acceso concurrente seguro.

## 12.1 Transaction Manager

Conceptualmente:

```text
Transaction
├── id
├── state
└── held locks / metadata
```

Estados mínimos posibles:

```text
ACTIVE
COMMITTED
ABORTED
```

## 12.2 Lock Manager

Estrategia recomendada:

```text
Shared Lock (S)
Exclusive Lock (X)
```

Compatibilidad:

| | S | X |
|---|---:|---:|
| S | sí | no |
| X | no | no |

Una variante simplificada de Strict 2PL es válida si se adopta oficialmente en el contexto.

## 12.3 Sintaxis requerida

```text
BEGIN TRANSACTION
END TRANSACTION
```

La semántica exacta debe documentarse.

## 12.4 Demostración obligatoria

Crear un test/demo con threads que muestre:

### Escenario inseguro

```text
T1 y T2
leen/modifican el mismo dato
sin protección
-> resultado incorrecto
```

### Escenario protegido

```text
T1 adquiere lock
T2 espera
T1 termina
T2 continúa
-> resultado correcto
```

## Tests

- lectores concurrentes;
- lector vs escritor;
- escritores concurrentes;
- liberación de locks;
- transacción completa;
- demo reproducible.

## Definition of Done

La race condition y su solución pueden demostrarse de forma repetible.

---

# 13. ETAPA 9 — API y Frontend

## Objetivo

Construir la interfaz gráfica obligatoria sin romper la separación de capas.

## 13.1 API

La API envuelve al motor.

No implementa storage ni índices.

Ejemplos conceptuales:

```text
GET  /tables
GET  /tables/{name}
POST /query
```

La ejecución puede retornar:

```json
{
  "columns": [],
  "rows": [],
  "execution_plan": {},
  "metrics": {}
}
```

El contrato exacto debe definirse cuando se implemente.

## 13.2 Frontend

Tecnología recomendada:

```text
React
TypeScript
Vite
```

### Panel 1 — Archivos

Debe mostrar:

- tablas;
- columnas;
- tipos;
- metadata útil.

### Panel 2 — Consultas

Debe incluir:

- editor SQL;
- botón ejecutar;
- feedback de errores.

### Panel 3 — Resultados

Debe mostrar filas y columnas.

### Panel 4 — Plan de Ejecución

Debe visualizar:

- operadores;
- orden;
- índice usado;
- acceso físico relevante.

No fabricar un plan decorativo.

## Definition of Done

Puede ejecutarse una consulta desde la interfaz y observar:

```text
consulta
resultado
plan real
```

---

# 14. ETAPA 10 — Experimentos, integración y entrega

## Objetivo

Demostrar experimentalmente el comportamiento de las estructuras.

## 14.1 Generador de datasets

Debe ser reproducible.

Tamaños:

```text
1,000
10,000
100,000
```

Idealmente usar una seed fija cuando exista aleatoriedad.

## 14.2 Comparación de archivos

Comparar:

```text
Heap File
vs
Paged Sequential File
```

Medir:

- tiempo de inserción;
- búsqueda por PK;
- espacio en disco;
- tiempo de reorganización.

## 14.3 Comparación de índices

Comparar:

```text
B+ clustered
B+ unclustered
Extendible Hashing
```

Pruebas:

- igualdad;
- rango;
- ordenamiento.

Medir:

- construcción;
- consulta;
- espacio adicional;
- inserciones/eliminaciones frecuentes.

## 14.4 Metodología

Para evitar benchmarks engañosos:

- mismo hardware;
- mismos datasets;
- misma semilla;
- repetir consultas;
- registrar configuración;
- evitar mezclar generación del dataset con tiempo de consulta;
- documentar warm-up/caché si afecta los resultados.

## 14.5 Presentación

Generar:

- CSV/JSON de resultados crudos;
- gráficas;
- tabla comparativa;
- conclusiones.

No escribir primero la conclusión y luego buscar números que la confirmen.

## 14.6 Integración final

Probar:

```text
Frontend
  ↓
API
  ↓
SQL Engine
  ↓
Operators
  ↓
Indexes / Files
  ↓
Pages
  ↓
Disk
```

También probar:

- reinicio;
- datos persistentes;
- creación/carga de tablas;
- errores SQL;
- concurrencia;
- benchmark scripts.

---

# 15. Dependencias entre etapas

```text
ETAPA 1
Arquitectura
    |
    v
ETAPA 2
Pages / Persistence
    |
    v
ETAPA 3
Heap / Sequential
    |
    +----------------+
    |                |
    v                v
ETAPA 4          ETAPA 5
B+               Hash
    |                |
    +-------+--------+
            |
            v
         ETAPA 6
         Operators
            |
            v
         ETAPA 7
        SQL Engine
            |
            v
         ETAPA 8
       Transactions
            |
            v
         ETAPA 9
       API / Frontend
            |
            v
         ETAPA 10
       Experiments
```

Etapas 4 y 5 pueden desarrollarse en paralelo si la Etapa 3 está estable y las interfaces fueron definidas correctamente.

---

# 16. Política de commits recomendada

Ejemplos:

```text
docs: add stage 1 architecture plan
feat(catalog): add schema and column metadata
feat(storage): add RID abstraction
test(catalog): add schema validation tests
feat(storage): add page serialization
feat(heap): implement free-space reuse
feat(bplus): support leaf splitting
fix(hash): update directory refs after bucket split
```

Evitar commits gigantes como:

```text
finish database
```

---

# 17. Política de trabajo con Codex

Para cada etapa:

## Paso 1 — Inspección

Pedir:

```text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md and the current stage file.
Inspect the repository.
Do not modify code.
Report what already exists and what is missing for this stage.
```

## Paso 2 — Implementación pequeña

Solicitar un subconjunto:

```text
Implement only task X.Y from the current stage.
Add the required tests.
Do not implement future-stage functionality.
```

## Paso 3 — Validación

Pedir:

```text
Run the relevant tests.
Explain any failures.
Do not change unrelated code.
```

## Paso 4 — Contexto

Actualizar `PROJECT_CONTEXT.md` cuando se toma una decisión estable.

---

# 18. Criterio global de finalización de la Parte 1

La Parte 1 solo se considera terminada cuando:

```text
[ ] ETAPA 1 completa
[ ] ETAPA 2 completa
[ ] ETAPA 3 completa
[ ] ETAPA 4 completa
[ ] ETAPA 5 completa
[ ] ETAPA 6 completa
[ ] ETAPA 7 completa
[ ] ETAPA 8 completa
[ ] ETAPA 9 completa
[ ] ETAPA 10 completa
```

y el checklist de `REQUIREMENTS.md` está completamente satisfecho.

---

# 19. Estado actual

Estado inicial recomendado:

```text
Current stage: ETAPA 1
Next document: ETAPA_01.md
```

No asumir que el repositorio está vacío.

Codex debe inspeccionarlo antes de crear archivos o modificar código.
