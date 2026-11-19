"""Verifica el perfil de práctica por las mismas rutas HTTP del frontend."""

import argparse
import json
from urllib.request import Request, urlopen

from scripts.check_extended_demo import check


def verificar(base):
    check(base)

    def filas(parte, sql):
        peticion = Request(f"{base}/parte{parte}/api/query", data=json.dumps(
            {"sql": sql, "max_rows": 10}).encode(), headers={"Content-Type": "application/json"})
        with urlopen(peticion, timeout=60) as respuesta:
            return json.load(respuesta)["rows"]

    for ranking in ("BM25", "TF_IDF"):
        documentos = filas(3, "SELECT id FROM documentos WHERE MATCH(contenido, "
                           f"'higrómetro') USING {ranking} LIMIT 5;")
        if len(documentos) != 5 or any(r[0] <= 54 for r in documentos):
            raise ValueError(f"Documentos de práctica ausentes con {ranking}: {documentos}")
        pasajes = filas(5, "SELECT paper_id FROM chunks WHERE MATCH(content, "
                        f"'CBOR') USING {ranking} LIMIT 5;")
        if [17] not in pasajes:
            raise ValueError(f"RFC 8949 ausente con {ranking}: {pasajes}")
    for tabla, clave, ultimo in (("imagenes", "escena_0999.png", 1124),
                                  ("canciones", "barrido_119.wav", 154)):
        if filas(4, f"SELECT media_key FROM {tabla} WHERE id = {ultimo};") != [[clave]]:
            raise ValueError(f"Falta {clave} en {tabla}")
        with urlopen(f"{base}/parte4/api/multimedia/{tabla}/media/{clave}", timeout=10) as respuesta:
            if respuesta.read(4) != (b"RIFF" if tabla == "canciones" else b"\x89PNG"):
                raise ValueError(f"Contenido incorrecto para {clave}")
    print("Perfil de práctica verificado.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    verificar(parser.parse_args().base_url.rstrip("/"))
