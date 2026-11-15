"""Fetch the pinned papers and build the academic demo in the Docker image."""

import json
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from scripts.setup_academic import main


if __name__ == "__main__":
    manifest = Path("PART_05/corpus.json")
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    with TemporaryDirectory(prefix="minidbms-papers-") as directory:
        for entry in entries:
            print(f"Downloading {entry['pdf']}", flush=True)
            with urlopen(entry["source_url"], timeout=60) as response:
                with (Path(directory) / entry["pdf"]).open("wb") as output:
                    copyfileobj(response, output)
        raise SystemExit(main([
            "--manifest", str(manifest), "--pdf-dir", directory,
            "--data-dir", "data/generated/todas/parte5",
        ]))
