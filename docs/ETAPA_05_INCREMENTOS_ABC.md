# Implementación de la Etapa 5 — Incrementos A, B y C

Fecha: **2026-09-06**. Registro histórico de las tareas 5.1–5.15 de
`ETAPA_05.md`. La implementación continuó con D/E y el cierre definitivo está
en [la auditoría de la Etapa 5](ETAPA_05_AUDIT.md).

## Inspección inicial (tarea 5.1)

Componentes reutilizados:

- `Index` para el contrato público `insert/search/delete`;
- `BPlusKeyCodec` y `BPlusRIDCodec` para bytes canónicos y RIDs uint32;
- `Page`, `PageManager`, `FileHeader` y sus contadores físicos;
- `DataType`, errores compartidos y política de duplicados/unicidad;
- patrón B+ de cabecera JSON en página 0 y páginas tipadas estrictas;
- ciclo create/open/flush/close y publicación de datos antes de cabecera.

Extensiones necesarias:

- formato y cabecera del índice hash;
- FNV-1a determinista y extracción LSB;
- directorio lógico y codec encadenado multipágina;
- bucket de una página con capacidad por bytes;
- fachada persistente con búsqueda, inserción y crecimiento dinámico;
- errores acotados para profundidad y colisiones inseparables.

No se detectaron conflictos de formato entre requisitos, contexto, plan, código
y la guía. El ejemplo posterior `delete() -> bool` sí difiere del contrato
estable `Index`; D preserva `None`/`InvalidReferenceError`. `PageManager` no
libera páginas hash porque merge/shrink son opcionales y quedaron diferidos. El
catálogo global continúa en memoria, como ya estaba documentado.

La línea base disponible en el intérprete Anaconda, sin instalación editable,
fue **1527 pruebas aprobadas y 17 fallos de entorno**: los fallos usan `python
-I` y no pueden importar `engine` porque ese intérprete no tiene instalado el
proyecto. La auditoría cerrada de Etapa 4 registra 1544/1544 con su entorno
editable original.

## Decisiones persistentes (tarea 5.2)

| Decisión | Valor adoptado |
|---|---|
| Hash | FNV-1a 64-bit, versión 1 |
| Claves | etiqueta de tipo + bytes escalares de `BPlusKeyCodec`; cero FLOAT canónico |
| Bits | sufijo LSB |
| Profundidad inicial | 1 por defecto |
| Profundidad máxima | persistida, máximo 20 en formato v1 |
| Directorio | referencias uint32 en páginas enlazadas |
| Bucket | una página con profundidad local y pares completos |
| Capacidad | bytes serializados exactos |
| Duplicados | permitidos por defecto; par idéntico idempotente |
| Unicidad | segundo RID para la misma clave rechazado |
| Colisión inseparable | error controlado, sin overflow pages |
| Borrado | exacto `(clave, RID)`; implementado en Incremento D |
| Merge/shrink | opcionales y diferidos |
| Publicación | buckets, directorio y cabecera |
| Corrupción | codecs estrictos y error de validación controlado |

La descripción completa se promovió a `PROJECT_CONTEXT.md`.

## Incremento A — formatos

Se implementaron:

- constantes/versiones binarias;
- `HashFileHeader` canónico y autocontenido;
- `HashCodec` con vectores dorados;
- `HashDirectory`, `HashDirectoryPage` y codec estricto;
- `HashBucket` y codec de asociaciones variables;
- E/S de las tres clases de página exclusivamente mediante `PageManager`.

## Incremento B — índice persistente básico

Se implementaron:

- create/open/flush/close/context manager;
- topología inicial válida y reapertura con objetos nuevos;
- búsqueda exacta con una ruta de directorio y un bucket;
- inserción sin cambio de topología;
- idempotencia del par repetido y rechazo de clave duplicada en índice único.

## Incremento C — crecimiento dinámico

Se implementaron:

- split cuando `local_depth < global_depth`;
- duplicación LSB cuando ambas profundidades son iguales;
- splits repetidos recalculando la profundidad;
- directorio de 1024 entradas repartido en dos páginas;
- planificación previa sin escrituras para profundidad agotada o hash completo
  inseparable;
- comparación de clave completa aun bajo hash deliberadamente constante;
- persistencia y reapertura después de crecimiento.

## Validación

Pruebas nuevas: **58 aprobadas**.

```text
$hashTests = Get-ChildItem tests/indexes -Filter 'test_hash_*.py'
pytest -q -W error $hashTests.FullName tests/indexes/test_extendible_hash.py
```

Regresión de índices e integración B+: **337 aprobadas**.

```text
pytest -q -W error tests/indexes tests/integration/test_stage4_bplus.py
```

Suite completa en el intérprete disponible: **1585 aprobadas, 17 fallos de
entorno preexistentes** por la instalación editable ausente en subprocesos
aislados. No apareció ningún fallo funcional nuevo de almacenamiento, B+ o hash.

## Continuación

Los incrementos D/E añadieron eliminación exacta, validador público,
construcción/reconstrucción desde Heap, mantenimiento, catálogo, métricas,
reinicios y pruebas diferenciales. Buddy merge y shrink continúan diferidos por
ser opcionales. La evidencia vigente está en `docs/ETAPA_05_AUDIT.md`.
