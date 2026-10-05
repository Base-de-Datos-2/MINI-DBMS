import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess

EVIDENCE = Path(__file__).resolve().parent
ROOT = EVIDENCE.parents[2]
AUDIT = EVIDENCE.parent


def main():
    catalog = json.loads((EVIDENCE / 'REQUISITOS_FIJADOS.json').read_text(encoding='utf-8'))
    evaluated = json.loads((EVIDENCE / 'EVALUACION.json').read_text(encoding='utf-8'))
    totals = json.loads((EVIDENCE / 'PORCENTAJES.json').read_text(encoding='utf-8'))
    with (AUDIT / 'MATRIZ_REQUISITOS.csv').open(encoding='utf-8-sig', newline='') as stream:
        matrix = list(csv.DictReader(stream))
    report = (AUDIT / 'AUDITORIA_TECNICA.md').read_text(encoding='utf-8')
    assert len(catalog) == len(evaluated) == len(matrix) == 77
    assert sum(len(row['criterios']) for row in catalog) == 220
    assert len({row['id'] for row in catalog}) == 77
    nine = ['requisito', 'estado_actual', 'evidencia', 'evaluacion', 'problemas', 'correccion',
            'implementacion_recomendada', 'validacion', 'dependencias']
    checked_references = 0
    for frozen, row, exported in zip(catalog, evaluated, matrix):
        assert all(frozen[key] == row[key] for key in frozen)
        assert exported['id'] == row['id']
        assert all(row[key] and exported[key] for key in nine)
        assert report.count('##### Paso ' + row['id'] + ':') == 1
        for field in ['evidencia', 'criterios', 'criterios_implementados', 'criterios_verificados', 'criterios_pendientes']:
            assert json.loads(exported[field]) == row[field]
        for field in nine:
            if not isinstance(row[field], list):
                assert exported[field] == row[field]
        for key, field in [('implementado', 'criterios_implementados'), ('verificado', 'criterios_verificados'), ('pendiente', 'criterios_pendientes')]:
            assert len(row[field]) == len(row['criterios'])
            assert all(value in (0, 1) for value in row[field])
            assert abs(float(exported['avance_' + key]) - sum(row[field]) * 100 / len(row['criterios'])) < 1e-7
        for imp, verified, pending in zip(row['criterios_implementados'], row['criterios_verificados'], row['criterios_pendientes']):
            assert verified + pending <= imp
        for reference in row['evidencia']:
            match = re.match(r'([^:]+):(\d+)', reference)
            if match:
                path, line = match.group(1), int(match.group(2))
                text = (ROOT / path).read_text(encoding='utf-8').splitlines()
                assert 1 <= line <= len(text), reference
                checked_references += 1
            elif reference.startswith('docs/auditoria/'):
                assert (ROOT / reference).exists(), reference
    groups = [(evaluated, totals['global_']), ([r for r in evaluated if r['parte'] != 'T'], totals['funcional'])]
    groups += [([r for r in evaluated if r['parte'] == part], value) for part, value in totals['partes'].items()]
    groups += [([r for r in evaluated if r['parte'] + '.' + r['etapa'] == stage], value) for stage, value in totals['etapas'].items()]
    for rows, values in groups:
        assert values['requisitos'] == len(rows)
        for key, field in [('implementado', 'criterios_implementados'), ('verificado', 'criterios_verificados'), ('pendiente', 'criterios_pendientes')]:
            value = sum((Fraction(sum(row[field]), len(row['criterios'])) for row in rows), Fraction())
            assert str(value) == values[key + '_equivalentes']
            assert abs(float(value * 100 / len(rows)) - values[key + '_porcentaje']) < 1e-10
    initial = (EVIDENCE / 'git_status_inicial.txt').read_text(encoding='utf-8-sig').splitlines()
    current = subprocess.check_output(['git', 'status', '--short'], cwd=ROOT).decode('utf-8').splitlines()
    normalize = lambda lines: [line for line in lines if line and not line.endswith('docs/auditoria/')]
    assert normalize(initial) == normalize(current), (initial, current)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    assert commit == (EVIDENCE / 'commit.txt').read_text(encoding='utf-8-sig').strip()
    pdf_sha = hashlib.sha256((ROOT / 'Proyecto_Final.pdf').read_bytes()).hexdigest()
    assert pdf_sha.upper() in (EVIDENCE / 'pdf_sha256.txt').read_text(encoding='utf-8-sig')
    (EVIDENCE / 'git_status_final.txt').write_text('\n'.join(current) + '\n', encoding='utf-8')
    result = dict(requirements=77, criteria=220, nine_fields_complete=True, matrix_matches_evaluation=True,
                  percentages_recomputed=True, report_steps=77, checked_file_line_references=checked_references,
                  commit_unchanged=commit, initial_user_changes_preserved=True, pdf_unchanged_sha256=pdf_sha)
    (EVIDENCE / 'integridad_final.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = {path.relative_to(AUDIT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(AUDIT.rglob('*')) if path.is_file()
                and path.name != 'MANIFIESTO_SHA256.json' and '__pycache__' not in path.parts}
    (EVIDENCE / 'MANIFIESTO_SHA256.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
