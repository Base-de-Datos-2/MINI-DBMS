"""Create or reset the dedicated Stage 9 demonstration database.

Run it while the API server is stopped:

    python scripts/setup_demo.py            # create data/generated/demo
    python scripts/setup_demo.py --reset    # delete and recreate it

Only a directory this script created, identified by its marker file, can be
reset. The normal project data directory is never touched.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
from time import perf_counter

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from api.database import Database  # noqa: E402
from api.demo import (  # noqa: E402
    DEMO_MARKER,
    DEMO_MEMORY_BUDGET_BYTES,
    demo_database,
)

DEFAULT_DIRECTORY = REPOSITORY / "data" / "generated" / "demo"


def prepare(directory: Path, *, reset: bool, definition=None) -> None:
    """Create the demo files in ``directory``, optionally replacing them.

    ``definition`` defaults to the presentation database; tests pass a smaller
    one so the same safety rules are exercised quickly.
    """

    marker = directory / DEMO_MARKER
    if directory.exists() and any(directory.iterdir()):
        if not reset:
            raise SystemExit(
                f"{directory} ya existe. Usa --reset para recrearlo "
                "(con el servidor detenido)."
            )
        if not marker.is_file():
            raise SystemExit(
                f"{directory} no tiene el marcador {DEMO_MARKER}; por seguridad "
                "solo se resetea un directorio creado por este script."
            )
        shutil.rmtree(directory)

    directory.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    database = Database.create(
        definition if definition is not None else demo_database(),
        directory,
        memory_budget_bytes=DEMO_MEMORY_BUDGET_BYTES,
    )
    try:
        summaries = [database.describe_table(name) for name in database.table_names()]
    finally:
        database.close()
    marker.write_text("MINI-DBMS Stage 9 demonstration data\n", encoding="utf-8")
    print(f"Base de demo creada en {directory} ({perf_counter() - started:.1f} s):")
    for summary in summaries:
        indexes = ", ".join(index.name for index in summary.indexes) or "sin índices"
        print(f"  {summary.name:16} {summary.row_count:5} filas  ({indexes})")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument(
        "--reset", action="store_true",
        help="borra y recrea un directorio de demo existente",
    )
    args = parser.parse_args(argv)
    prepare(args.data_dir.resolve(), reset=args.reset)


if __name__ == "__main__":
    main()
