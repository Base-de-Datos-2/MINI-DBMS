# Revisión y correcciones de las tareas 5.16–5.21

Fecha: **2026-09-10**. Alcance: eliminación, propiedad/asignación de páginas,
funciones opcionales, validación independiente y reinicio según
[ETAPA_05.md](../ETAPA_05.md). Se conservan las correcciones de los bloques
[5.1–5.7](ETAPA_05_REVIEW_5_1_5_7.md) y
[5.8–5.15](ETAPA_05_REVIEW_5_8_5_15.md), el formato v1 y los límites sin WAL.

## Resultado por tarea

| Tarea | Resultado | Evidencia revisada o añadida |
|---|---|---|
| 5.16 — Eliminación | Cumple tras correcciones. | Se elimina únicamente el par solicitado; otros RIDs y aliases siguen accesibles; un par ausente no escribe. Se comprueba profundidad local frente a global y se valida el contador siguiente antes de escribir. Pruebas de bucket dividido, último RID, doble eliminación y reapertura. |
| 5.17 — Asignación y propiedad | Cumple bajo la política append-only adoptada, tras corregir contadores. | Todas las asignaciones pasan por `PageManager`; firmas distinguen tipos; el crecimiento continúa después de reiniciar. No se libera ningún bucket referenciado, ni existe un asignador privado volátil. Se preservan los eventos tipados de creación y las lecturas físicas de páginas corruptas. |
| 5.18 — Buddy merge | Criterio satisfecho mediante aplazamiento explícito; no implementado. | El plan permite implementarlo y validarlo por completo o documentar su aplazamiento. Borrar incluso todas las asociaciones conserva buckets, profundidades y aliases; el contador de fusiones/liberaciones sigue en cero. |
| 5.19 — Directory shrink | Opcional y explícitamente aplazado; no implementado. | La eliminación no reduce profundidad, directorio ni tamaño físico. Se verifica persistencia de esa topología vacía y reutilización de capacidad tras reabrir. |
| 5.20 — Validador independiente | Cumple tras correcciones. | Revalida cabecera en memoria y compara con página 0 releída; corrupción independiente de aliases, profundidades, referencias, enlaces, ubicación, unicidad, contadores, tipo y páginas huérfanas. Diagnósticos contextualizados y ausencia de escrituras; no usa búsquedas puntuales. |
| 5.21 — Reinicio real | Cumple con cobertura ampliada. | Tres procesos independientes crean/dividen/duplican, reabren/eliminan/continúan creciendo y vuelven a abrir/verificar. Directorio multipágina, 70 asociaciones finales y validación tras cada mutación de ese escenario; se conserva cobertura previa de vacío, duplicados, unicidad y colisiones. |

La reutilización de **capacidad dentro de un bucket vivo** no equivale a
liberar/reasignar páginas. Las pruebas condicionales de merge, shrink y free-list
no se presentan como implementadas. La política estable de `PROJECT_CONTEXT.md`
permite esas funciones diferidas y asignaciones append-only.

El ejemplo `delete(...) -> bool` de 5.16 no sustituye el contrato compartido:
se conserva `None` al eliminar e `InvalidReferenceError` si no existe el par,
como requieren `Index`, las pruebas anteriores y el contexto arquitectónico.

## Defectos corregidos

1. **Borrado con profundidad corrupta:** `delete()` leía directamente el bucket
   sin relacionar profundidad local y global. Ahora reutiliza
   `_read_routed_bucket()`, sin inspeccionar buckets ajenos ni añadir lecturas.
2. **Borrado parcial por contador inválido:** con contador global cero y una
   asociación presente, el bucket se escribía antes de que la nueva cabecera
   rechazara el valor negativo. Ahora se valida esa cabecera antes de escribir.
   La regresión verifica conservación byte a byte y del par afectado.
3. **Cabecera invisible para el validador:** éste sólo consultaba su copia
   activa, por lo que ignoraba una página 0 alterada durante la sesión. Ahora
   relee la página, revalida el descriptor activo y exige igualdad; se cubren
   tanto una cabecera válida pero distinta como una firma corrupta, con ambos
   valores de `deep`.
4. **Eventos tipados de creación perdidos:** `create()` construía adaptadores
   nuevos y descartaba los que habían asignado/escrito las páginas iniciales.
   Se conservan los adaptadores usados, resolviendo también el hallazgo de E/S
   tipada de creación antes asociado a 5.25.
5. **Lecturas físicas corruptas subcontadas:** cuando `PageManager` leía una
   página completa y rechazaba su envoltura externa, los adaptadores no sumaban
   esa transferencia. Ahora toman el incremento físico real, también en caso
   de excepción; accesos rechazados antes de leer permanecen en cero.

Además, el validador agrupa aliases en una sola pasada, evitando recorrer
`2^D` entradas por cada bucket. Los errores añaden referencias a página y,
para ubicación/unicidad, a entrada. Una prueba bloquea explícitamente las
búsquedas puntuales y verifica una lectura por página propia, sin escrituras.

Código afectado:
[extendible_hash.py](../engine/indexes/extendible_hash.py) y
[hash_io.py](../engine/indexes/hash_io.py).
Pruebas nuevas:
[test_hash_integrity_review.py](../tests/indexes/test_hash_integrity_review.py).

## Evidencia de ejecución

Línea base heredada: **1716 pruebas aprobadas**. Antes de corregir el núcleo,
la tanda inicial reprodujo **8 fallos y 18 aprobaciones**. Tras corregirlos,
las pruebas nuevas junto con eliminación, integración y ambos bloques de
revisión anteriores pasaron **138 pruebas**. La ampliación de contadores
reprodujo otros **2 fallos y 3 aprobaciones** antes de corregir `hash_io.py`.
La tanda nueva definitiva incorpora **31 casos**.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q engine tests
git diff --check
```

- Suite completa: **1747 aprobadas en 93,96 s**, con advertencias tratadas como
  errores, sin omisiones ni xfails. Incluye los 31 casos nuevos, los bloques
  anteriores y las pruebas existentes de arquitectura/importaciones.
- `compileall` y `git diff --check`: correctos.

Resultado: **los criterios obligatorios de 5.16–5.21 se cumplen tras las
correcciones**, bajo las políticas arquitectónicas adoptadas. Los criterios
opcionales de 5.18 y 5.19 se satisfacen mediante su aplazamiento explícito,
no mediante una implementación de merge/shrink.

## Límites y continuidad

La comprobación previa a `delete()` evita el defecto de validación reproducido,
pero no proporciona atomicidad entre la escritura del bucket y la cabecera.
Sin WAL, un fallo físico intermedio puede exigir detección y reconstrucción;
no se afirma rollback general ante cortes de energía ni coordinación concurrente.
La validación no repara archivos y `deep=False` omite ubicación/unicidad de
claves; apertura y validación predeterminada usan comprobación profunda.

El reinicio de tres procesos fuerza un hash controlado exclusivamente en las
pruebas para provocar crecimiento multipágina con pocos registros; cada proceso
lo instala independientemente. La función persistente de producción permanece
FNV-1a, cubierta además por los vectores y pruebas de reinicio existentes.

Esta revisión determina los criterios de **5.16–5.21**, no recertifica el cierre
global ni inicia la Etapa 6. Siguen pendientes los hallazgos del adaptador en
5.23 (rollback Heap/índice), del diferencial general en 5.26 (validación después
de cada mutación) y del cierre/trazabilidad en 5.27 (47 criterios reales frente
a 46 filas históricas). El desfase de contadores de creación queda resuelto
en este bloque porque 5.17 exige contabilizar asignaciones y escrituras reales.
