# Aplicación elegida: e-commerce híbrido

Decisión de implementación: 2026-10-04, tras la auditoría independiente.
Fuente: Proyecto_Final.pdf, sección 2.5 y Anexo A, opción B (páginas 4–6).
La solicitud actual autoriza completar el backend y pospone toda interfaz
gráfica. Esta elección cierra la decisión pendiente 5.1.4; no acredita todavía
la implementación de los otros requisitos de Parte 5.

## Motivo y alcance

Se adopta la opción B porque integra el catálogo relacional y el dominio de
tiendas de Lima ya implementados, y consume texto e imágenes que las Partes
3 y 4 igualmente exigen. No depende de credenciales de un LLM, hardware de
cámara o un servicio de recomendaciones externo. No se implementan las otras
tres opciones del anexo.

El backend de aplicación consumirá exclusivamente el API HTTP del motor,
sin importar sus páginas, índices o propietarios. Su futuro frontend usará
los contratos de esa aplicación. PostgreSQL queda como comparador experimental.

## Datos y relaciones

- Productos: identificador estable, nombre, precio, categoría y descripción.
- Imágenes: objeto identificado y administrado por el motor, con extracción
  SIFT, vocabulario e histogramas compatibles con sus índices multimedia.
- Descripciones: documentos identificados y recuperables mediante SPIMI,
  TF-IDF/coseno y BM25, asociados a productos mediante su identificador.
- Tiendas: identificador, nombre y coordenadas en el dominio espacial existente.
- Disponibilidad: asociación producto/tienda para vincular recomendaciones con
  tiendas reales de la base y permitir búsqueda espacial.

Los documentos y objetos que excedan el payload relacional de 4079 bytes se
guardarán en persistencia auxiliar propia. Las tablas almacenarán metadatos
y referencias estables; no se introducirán archivos multimedia en VARCHAR.

## Flujo y fusión

El cliente selecciona un producto. La aplicación consulta sus metadatos,
solicita descripciones similares y vecinos visuales al motor, y combina esos
candidatos con productos de categoría relacionada. Cada canal mantiene una
contribución explícita y normalizada; los pesos son declarados y el desempate
usa product_id. Se excluye el producto de consulta cuando corresponda.

Si se aporta ubicación, se consultan tiendas por el SQL/API espacial y se
relacionan con disponibilidad. No se simulan resultados ni se convierten
distancias ascendentes en similitudes descendentes sin una transformación
definida. El endpoint devuelve producto, score final, aportes por canal y
tiendas asociadas, para que la interfaz posterior pueda explicar el resultado.

## Aceptación del backend

1. Se cargan y reabren productos, imágenes, descripciones y tiendas con
   asociaciones válidas y formatos/versiones declarados.
2. Una petición real HTTP al backend de aplicación produce llamadas observables
   al API del motor propio para metadatos, texto, multimedia y espacial.
3. Los candidatos y scores se contrastan con cálculos de referencia pequeños;
   pesos, desempates, exclusión propia y resultados vacíos son comprobables.
4. Fallos del motor o entradas inválidas producen errores controlados; no se
   reemplazan canales faltantes por resultados hardcoded.
5. El frontend queda pendiente y no se declara Parte 5 completa solo por
   terminar estos endpoints. Los requisitos comunes 5.1.1–5.1.3 se cerrarán
   según la evidencia disponible de backend y la fase gráfica posterior.

Dependencias: SQL/API espacial; persistencia auxiliar; ranking textual;
extracción y búsqueda multimedia. Los contratos concretos se documentarán
junto a su implementación y validación; este documento no los da por existentes.
