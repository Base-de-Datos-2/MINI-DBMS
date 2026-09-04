# Inspección previa de la Etapa 4 — tarea 4.1

Fecha: **2026-09-03**. Alcance: contratos y persistencia terminados en las
Etapas 1–3 que condicionan el B+ Tree. Esta inspección fue de solo lectura; la
línea base se comprobó antes de implementar 4.2–4.5.

## Resultado de la línea base

```text
.\.venv\Scripts\python.exe -m pytest -q -W error
1284 passed in 14.59s
```

La Etapa 3 conserva sus 50 criterios satisfechos. No había nodos, cabecera,
codec, archivo ni implementación física B+; `engine/indexes/base.py` contenía
únicamente `Index` y `OrderedIndex`.

## APIs reutilizables de las Etapas 1–3

- `Index.insert(key, rid)`, `search(key)` y `delete(key, rid)` definen pares
  clave/RID; repetir el mismo par es idempotente y una clave puede asociar
  varios RIDs.
- `OrderedIndex.range_search()` define extremos opcionales, banderas de
  inclusión, orden ascendente, rechazo de rangos invertidos y rechazo de NaN.
- `RID(page_id, slot_id)` es inmutable, ordenable y no negativo. Sus límites
  binarios corresponden al codec físico, no al objeto lógico.
- `HeapFile` implementa inserción, lectura, eliminación y recorrido perezoso
  `(RID, Record)`. La compactación local conserva los RIDs vivos; un slot
  eliminado puede reutilizar su antiguo RID para otro registro.
- `PagedSequentialFile` persiste esquema y clave, permite duplicados estables,
  expone recorrido `(RID, Record)`, búsqueda exacta, eliminación diferida y
  reorganización explícita.
- `RecordCodec` y los codecs de valores proporcionan la representación física
  ya adoptada para los cuatro `DataType`.
- `PageManager` puede poseer un archivo de índice separado y encapsula toda la
  asignación, lectura, escritura, sincronización y reapertura. Sus contadores
  miden transferencias reales por sesión.
- `Page` permite reservar la página física 0 para un descriptor en el slot 0 y
  almacenar un payload binario de hasta `MAX_RECORD_SIZE` en cada página de
  nodo.
- `IndexMetadata` representa nombre, tabla, columna, tipo y modalidad
  clustered. `Catalog` ya limita una definición clustered por tabla, pero
  continúa siendo no persistente.

## Respuestas a las preguntas de 4.1

| Pregunta | Resultado |
|---|---|
| ¿Qué retorna `Index.search()`? | Un generador cerrable de RIDs, vacío cuando no hay coincidencias. |
| ¿Los recorridos exponen `(RID, Record)`? | Sí, tanto Heap como Sequential. |
| ¿Puede el índice usar un archivo/gestor separado? | Sí. Cada `PageManager` posee una ruta y un handle independientes. |
| ¿Cómo se reutilizan páginas libres? | `PageManager` solo agrega páginas; el B+ debe mantener su propia lista libre persistente. |
| ¿Sequential puede mover registros? | Sí. Una inserción estructural puede reconstruir la página objetivo y desplazar el sufijo. |
| ¿Qué produce la reorganización? | `ReorganizationMetrics`; no produce remapeo y todos los RIDs secuenciales anteriores quedan invalidados. |
| ¿Cómo representa `IndexMetadata` la clave? | Como un único nombre exacto de columna; el tipo se deriva del esquema. |

## Conflictos y riesgos encontrados

- `PLAN.md` y la sección de estado de `PROJECT_CONTEXT.md` conservaban
  referencias antiguas a la Etapa 2/3, aunque sus párrafos finales sí
  registraban el cierre de la Etapa 3. Deben identificar la Etapa 4 como activa.
- Una asociación de índice obsoleta puede apuntar a un RID Heap reutilizado.
  La coordinación futura deberá retirar el índice antes de eliminar la fila.
- Sequential no ofrece mapa de RIDs. Un índice clustered dependiente debe
  reconstruirse después de inserciones que muevan registros y después de la
  reorganización.
- `PageManager` no libera páginas. La lista libre de nodos pertenece al formato
  B+, sin modificar la capa de páginas.
- No hay WAL, bloqueo ni atomicidad entre archivo de datos e índice. La Etapa 4
  solo puede ofrecer orden de escrituras, validación y reconstrucción.

## Extensiones mínimas requeridas

1. Metadatos persistentes B+ en la página 0 de un archivo propio.
2. Codec de claves y RID con límites físicos explícitos.
3. Modelos puros de hoja e interno con capacidades derivadas de página.
4. Codec de nodo y adaptador de E/S sobre `PageManager` en la tarea 4.6.
5. Núcleo persistente común antes de los adaptadores Heap/Sequential.
6. Dependencia permitida `indexes -> catalog` exclusivamente para `DataType`;
   no se introduce la dependencia inversa ni un ciclo.

## Secuencia recomendada confirmada

La secuencia segura sigue `ETAPA_04.md`: decisiones → cabecera → codecs →
modelo de nodos → serialización/E/S → ciclo del árbol → descenso y consultas →
mutaciones/balanceo → persistencia → adaptadores e integración. No debe empezar
Extendible Hashing, SQL ni operadores durante esta etapa.
