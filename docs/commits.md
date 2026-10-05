# Lineamientos de Commits

## Objetivo

Mantener un historial de cambios claro, consistente y fácil de entender durante el desarrollo de MINI-DBSM.

Todos los commits del proyecto deben seguir estos lineamientos.

---

## 1. Formato del mensaje

Usar el siguiente formato:

```text
<tipo>(<alcance>): <descripción breve>
```

Donde:

- **tipo**: indica el tipo de cambio realizado.
- **alcance**: indica el módulo, servicio o componente afectado. Es opcional.
- **descripción**: explica de forma breve y clara qué se hizo.

### Reglas

- Usar letras minúsculas.
- No terminar el mensaje con punto.
- Usar verbos en imperativo, por ejemplo: `agregar`, `corregir`, `actualizar`, `separar`.
- Mantener el mensaje breve y descriptivo.
- Máximo recomendado: 72 caracteres.

---

## 2. Tipos permitidos

| Tipo | Uso |
|---|---|
| `feat` | Nueva funcionalidad |
| `fix` | Corrección de un error |
| `docs` | Cambios en documentación |
| `refactor` | Reestructuración de código sin cambiar funcionalidad |
| `test` | Creación o modificación de pruebas |
| `chore` | Tareas de mantenimiento, configuración o dependencias |

---

## 3. Alcance (`scope`)

El alcance indica el módulo, componente o parte del proyecto afectada.

Debe utilizarse cuando ayude a identificar con claridad dónde se realizó el cambio.

Ejemplos:

```text
feat(storage): agregar reutilización de espacios libres
fix(parser): corregir validación de condición where
refactor(index): separar lógica de búsqueda
test(concurrency): agregar pruebas de bloqueo
docs: actualizar readme
```

Si el cambio es general y un alcance no aporta información útil, puede omitirse:

```text
docs: actualizar documentación del proyecto
chore: actualizar dependencias
```

El alcance debe corresponder a un componente real de MINI-DBSM. No crear scopes artificiales únicamente para completar el formato.

---

## 4. Ejemplos correctos

```text
feat(usuarios): agregar búsqueda por dni
fix(api): corregir timeout de consulta
docs: actualizar readme
refactor(auth): separar lógica de validación
test(usuarios): agregar pruebas de búsqueda
chore: actualizar dependencias
```

Ejemplos aplicados a MINI-DBSM:

```text
feat(heap): agregar reutilización de espacios libres
fix(sequential): corregir inserción ordenada
feat(bplus): agregar búsqueda por rango
refactor(parser): separar análisis y ejecución sql
test(hash): agregar pruebas de división de buckets
fix(transaction): corregir liberación de bloqueos
docs: actualizar arquitectura del proyecto
```

---

## 5. Ciclo de desarrollo con buenos commits

El trabajo debe mantenerse dividido en cambios lógicos y coherentes.

Flujo recomendado:

```text
idea o tarea
    ↓
desarrollo
    ↓
commit
    ↓
historial
```

Cada commit debe representar una unidad lógica de trabajo, por ejemplo:

```text
feat(storage): implementar reutilización de espacio
fix(storage): corregir actualización de páginas libres
test(storage): agregar pruebas de reutilización
docs: actualizar documentación de almacenamiento
```

No acumular múltiples cambios no relacionados dentro de un único commit.

---

## 6. Ejemplos incorrectos

Evitar mensajes como:

```text
cambios varios
fix
update proyecto
avance
final
correcciones de errores
agregar funcionalidad nueva
```

Estos mensajes deben evitarse porque:

- No indican claramente qué se hizo.
- Dificultan entender el historial.
- Complican la revisión y el trabajo en equipo.

---

## 7. Recomendaciones clave

### Un commit representa un cambio lógico

Cada commit debe representar una única mejora, corrección o cambio coherente.

### Commits frecuentes y pequeños

Es preferible realizar commits pequeños durante el desarrollo en lugar de un único commit grande al final de una etapa.

### Mensajes claros y descriptivos

El mensaje debe permitir entender el cambio sin necesidad de inspeccionar primero todos los archivos modificados.

### Mantener un historial útil

El historial de Git debe facilitar la revisión, el mantenimiento y la comprensión de la evolución del proyecto.

---

## 8. Aplicación durante el desarrollo de MINI-DBSM

Durante la corrección e implementación del proyecto:

1. Realizar los cambios correspondientes a una unidad lógica de trabajo.
2. Verificar que el cambio realizado sea coherente y esté listo para registrarse.
3. Crear un commit siguiendo el formato definido en este documento.
4. Continuar con la siguiente unidad lógica.
5. Evitar esperar hasta el final de una etapa completa para registrar todos los cambios en un solo commit.

Cuando una etapa requiera diferentes tipos de cambios, separarlos cuando corresponda.

Ejemplo:

```text
feat(rtree): implementar búsqueda knn
fix(rtree): corregir cálculo de nodos candidatos
test(rtree): agregar pruebas de búsqueda knn
```

No utilizar un único commit genérico como:

```text
avance parte 2
```

---

## 9. Resumen rápido

Antes de crear un commit, verificar:

- El formato es `tipo(alcance): descripción`.
- El tipo describe correctamente el cambio.
- El alcance identifica un componente real cuando sea útil.
- La descripción es clara y breve.
- El mensaje está en minúsculas.
- El mensaje no termina en punto.
- La descripción utiliza un verbo en imperativo.
- El commit representa un cambio lógico y coherente.
- No se mezclan cambios no relacionados.
- Se evitan mensajes genéricos.

Un buen commit de hoy permite mantener un historial útil mañana.
