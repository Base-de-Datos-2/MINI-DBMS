"""Download pinned PDFs and build a fresh academic demo database."""

import argparse
import json
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from scripts.setup_academic import main as prepare


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=("base", "extended"), default="base")
    parser.add_argument("--data-dir", type=Path, default=Path("data/generated/todas/parte5"))
    args = parser.parse_args(argv)
    if args.data_dir.exists():
        parser.error(f"Use a new data directory: {args.data_dir}")

    source = Path(__file__).resolve().parents[1] / "PART_05"
    entries = json.loads((source / "corpus.json").read_text(encoding="utf-8"))
    if args.corpus == "extended":
        entries.extend(json.loads((source / "corpus_extra.json").read_text(encoding="utf-8")))

    with TemporaryDirectory(prefix="minidbms-papers-") as directory:
        staging = Path(directory)
        manifest = staging / "manifest.json"
        manifest.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        for entry in entries:
            print(f"Downloading {entry['pdf']}", flush=True)
            with urlopen(entry["source_url"], timeout=60) as response:
                with (staging / entry["pdf"]).open("xb") as output:
                    copyfileobj(response, output)
        return prepare(["--manifest", str(manifest), "--pdf-dir", directory,
                        "--data-dir", str(args.data_dir)])


if __name__ == "__main__":
    raise SystemExit(main())
