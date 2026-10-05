"""Validate local Markdown links in the current delivery documentation."""

import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    names = ("README.md", "docs/spatial.md", "docs/EXPERIMENTOS.md", "docs/EXPERIMENTOS_ESPACIALES.md",
             "docs/experimentos/README.md", "docs/experimentos/actualizados_1k_10k/resultados.md",
             "docs/implementacion/SEGUIMIENTO.md", "docs/implementacion/ESTADO_PRIMERA_ENTREGA.md", "skills/README.md")
    checked, missing = [], []
    for name in names:
        source = args.repository / name
        body = re.sub(r"```.*?```", "", source.read_text(encoding="utf-8"), flags=re.S)
        for match in re.finditer(r"\[[^\]]*\]\(([^\n)]+)\)", body):
            link = match.group(1).strip("<>").split("#", 1)[0]
            if not link or re.match(r"[a-zA-Z]+:", link):
                continue
            path = source.parent / link
            item = {"file": name, "target": link}
            checked.append(item)
            if not path.exists():
                missing.append(item)
    result = {"checked": len(checked), "missing": missing}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if missing:
        raise ValueError(f"Missing documentation targets: {missing}")
    print(f"Verified {len(checked)} local documentation links")


if __name__ == "__main__":
    main()
