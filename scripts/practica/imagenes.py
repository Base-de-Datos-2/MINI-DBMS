"""Generate textured grayscale scenes with corners for SIFT."""

import struct
import zlib
from random import Random


def imagen(indice):
    rng = Random(indice)
    lado = 128
    pixels = [bytearray([35] * lado) for _ in range(lado)]
    for _ in range(42):
        x, y = rng.randrange(110), rng.randrange(110)
        ancho, alto = rng.randint(5, 18), rng.randint(5, 18)
        color = rng.randint(65, 250)
        for fila in pixels[y:y + alto]:
            fila[x:x + ancho] = bytes([color]) * ancho

    def bloque(tipo, datos):
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos)))

    header = struct.pack(">2I5B", lado, lado, 8, 0, 0, 0, 0)
    filas = b"".join(b"\0" + fila for fila in pixels)
    return (b"\x89PNG\r\n\x1a\n" + bloque(b"IHDR", header)
            + bloque(b"IDAT", zlib.compress(filas)) + bloque(b"IEND", b""))
