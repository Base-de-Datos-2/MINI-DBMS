"""Prepara colecciones ampliadas para las pestañas de texto y multimedia."""

import argparse
import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from api.database import Database, NewTable
from engine.catalog import DataType
from scripts.practica.multimedia import ampliar
from scripts.practica.texto import registros
from scripts.setup_multimedia import asset_sources
from scripts.setup_text import DEMO_COLLECTIONS, DEMO_DIRECTORY


def texto(destino):
    colecciones = []
    for tabla, columna, nombre in DEMO_COLLECTIONS:
        with (DEMO_DIRECTORY / nombre).open(encoding="utf-8-sig", newline="") as archivo:
            filas = [(int(r["id"]), r[columna]) for r in csv.DictReader(archivo)]
        if tabla == "documentos":
            anterior = max(i for i, _ in filas)
            filas.extend((anterior + i, contenido) for i, contenido in registros())
        esquema = NewTable(tabla, (("id", DataType.INTEGER), (columna, DataType.VARCHAR)))
        colecciones.append((esquema, filas, "id", columna))
    Database.prepare_text(destino, colecciones)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--only", nargs="+", choices=["parte3", "parte4"],
                        default=["parte3", "parte4"])
    args = parser.parse_args()
    for parte in args.only:
        destino = args.data_dir / parte
        if destino.exists() or destino.is_symlink():
            parser.error(f"El destino ya existe: {destino}")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    if "parte3" in args.only:
        texto(args.data_dir / "parte3")
    if "parte4" in args.only:
        with TemporaryDirectory() as temp:
            assets = Path(temp) / "media"
            ampliar(DEMO_DIRECTORY.parent / "multimedia_demo", assets)
            Database.prepare_multimedia(args.data_dir / "parte4", asset_sources(assets))


if __name__ == "__main__":
    main()
