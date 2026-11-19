"""Extend a staged copy of the real media collections."""

import json
from shutil import copytree

from .audio import escribir_audio
from .imagenes import imagen


def ampliar(origen, destino):
    copytree(origen, destino)
    archivo = destino / "collections.json"
    manifest = json.loads(archivo.read_text(encoding="utf-8"))
    for coleccion in manifest["collections"]:
        filas = coleccion["rows"]
        siguiente = max(fila[0] for fila in filas) + 1
        carpeta = destino / coleccion["media_directory"]
        if coleccion["modality"] == "image":
            for i in range(1000):
                nombre = f"escena_{i:04d}.png"
                (carpeta / nombre).write_bytes(imagen(i))
                filas.append([siguiente + i, f"Escena sintética {i}", nombre])
        elif coleccion["modality"] == "audio":
            for i in range(120):
                nombre = f"barrido_{i:03d}.wav"
                escribir_audio(carpeta / nombre, i)
                filas.append([siguiente + i, f"Barrido {i}", "Sintético", nombre])
    archivo.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
