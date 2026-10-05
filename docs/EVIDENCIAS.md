# Rutas y metadatos de las evidencias

Las evidencias usan rutas genéricas para facilitar su lectura en otros entornos.
La normalización de rutas y metadatos no constituye una nueva ejecución de las
pruebas. Las mediciones conservan sus fechas y las fuentes se identifican por
hashes de contenido. Los TAR no incluyen campos de propietario del entorno.

Los scripts calculan la raíz desde su ubicación. Para usar entornos propios,
configurar `MINIDBMS_REPOSITORY`, `MINIDBMS_IMPLEMENTATION_DIR`,
`MINIDBMS_AUDIT_DIR`, `MINIDBMS_PYTHON` y, cuando corresponda,
`MINIDBMS_UV` o `MINIDBMS_SPATIAL_RESULTS`. Las rutas locales se configuran
fuera del repositorio. Antes de publicar nuevos logs:

```sh
python scripts/sanitize_evidence.py ruta/al/log ruta/al/resultado.json
```

No versionar rutas de perfiles, nombres de cuentas locales, credenciales ni
directorios personales. Revisar también metadatos y archivos comprimidos.
El empaquetado experimental elimina los campos de propietario automáticamente.

Los manifiestos permiten comprobar las fuentes, resultados y figuras de cada
experimento. Sus referencias Git deben corresponder a fuentes recuperables;
actualizar los identificadores no implica repetir las mediciones.
