# Datos de práctica para las partes 3, 4 y 5

Desde la raíz del repositorio en PowerShell:

```powershell
$env:MINIDBMS_ACADEMIC_CORPUS = "practica"
docker compose up --build
```

Abrir http://localhost:8000. El perfil conserva las cinco pestañas. La construcción descarga y valida 25 PDF y prepara los índices de las tres colecciones ampliadas. Se necesita conexión para la primera construcción. Para volver al perfil habitual, ejecutar `Remove-Item Env:MINIDBMS_ACADEMIC_CORPUS` y reconstruir.

| Colección | Cantidad preparada |
|---|---:|
| documentos | 1.254 |
| articulos | 32 |
| productos | 1.000 |
| imagenes | 1.124 |
| canciones | 154 |
| papers | 25 |
| chunks | 1.602 en la preparación verificada |

Las 1.200 bitácoras combinan diez sedes, seis sensores y veinte días. Sirven para probar términos frecuentes y selectivos. Las 1.000 imágenes son escenas geométricas PNG con textura y los 120 WAV contienen barridos armónicos. Se generan localmente a partir del código. El perfil conserva los archivos reales y las doce consultas de la galería anterior. Los doce PDF adicionales son especificaciones RFC sobre compresión, CBOR, QUIC y HTTP. Sus URL, autores y huellas SHA-256 figuran en `PART_05/corpus_practica.json`.

Con el servidor levantado se puede verificar el perfil desde otra terminal:

```sh
python -m scripts.check_practica
```

En la pestaña textual se puede buscar «higrómetro» con BM25 y TF-IDF. En la pestaña multimedia se pueden consultar los vecinos de `foto_consulta.jpg` o `audio_query.mp3`. En recuperación académica se puede buscar «CBOR» y abrir los pasajes de RFC 8949. Las consultas y la recuperación funcionan sin una clave de generación.
