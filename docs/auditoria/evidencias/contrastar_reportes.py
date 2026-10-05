import argparse
import json
from pathlib import Path

from benchmarks.report import render


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    paths = [Path('benchmarks/results') / name for name in
             ['part1_results.jsonl', 'part1_results_100k_files.jsonl', 'part1_results_100k_indexes.jsonl']]
    generated = render(paths, args.evidence / 'reporte_regenerado')
    stored = Path('docs/experimentos/resultados.md').read_text(encoding='utf-8')
    fresh = generated[-1].read_text(encoding='utf-8')
    document = dict(tables_identical=stored == fresh, generated_files=len(generated),
                    images=sum(path.suffix == '.png' for path in generated),
                    stored_table_lines=len(stored.splitlines()), regenerated_table_lines=len(fresh.splitlines()))
    (args.evidence / 'reporte_contrastado.json').write_text(json.dumps(document, indent=2), encoding='utf-8')
    print(json.dumps(document, indent=2))


if __name__ == '__main__':
    main()
