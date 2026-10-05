import ast
from collections import Counter, defaultdict
from graphlib import TopologicalSorter
import hashlib
from importlib.util import resolve_name
import json
import math
from pathlib import Path
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def digest_at(commit):
    digest = hashlib.sha256()
    names = git('ls-tree', '-r', '--name-only', commit).decode().splitlines()
    for root in ('engine/', 'benchmarks/'):
        for path in sorted(n for n in names if n.startswith(root) and n.endswith('.py')):
            digest.update(path.encode())
            digest.update(git('show', f'{commit}:{path}'))
    return digest.hexdigest()


def main():
    inventory = []
    graph = {}
    longest = []
    external = defaultdict(set)
    for path in sorted((ROOT / 'engine').rglob('*.py')):
        parts = list(path.relative_to(ROOT).with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        module = '.'.join(parts)
        package = module if path.name == '__init__.py' else module.rpartition('.')[0]
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        imports, symbols = set(), []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(resolve_name('.' * node.level + (node.module or ''), package)
                            if node.level else node.module or '')
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(dict(name=node.name, line=node.lineno, end=node.end_lineno))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    longest.append(dict(module=module, name=node.name, line=node.lineno,
                                        lines=node.end_lineno-node.lineno+1))
        graph[module] = imports
        external[module.split('.')[1] if '.' in module else 'engine'].update(
            name.split('.')[0] for name in imports if not name.startswith('engine'))
        inventory.append(dict(path=path.relative_to(ROOT).as_posix(), module=module,
                              lines=len(source.splitlines()), symbols=symbols, imports=sorted(imports),
                              sha256_lf=hashlib.sha256(source.encode()).hexdigest()))
    engine_graph = {module: imports & graph.keys() for module, imports in graph.items()}
    try:
        ordered = list(TopologicalSorter(engine_graph).static_order())
        acyclic = len(ordered) == len(graph)
    except Exception as error:
        acyclic = False
        ordered = [repr(error)]
    forbidden = {'pandas', 'sqlalchemy', 'sqlite3', 'psycopg', 'lark', 'faiss', 'hnswlib'}
    architecture = dict(modules=len(graph), explicit_import_graph_acyclic=acyclic,
                        external_import_roots={key: sorted(value) for key, value in external.items()},
                        forbidden_imports=sorted(forbidden & set().union(*external.values())),
                        longest_functions=sorted(longest, key=lambda row: row['lines'], reverse=True)[:12],
                        topological_order=ordered)
    (OUT / 'inventario_codigo.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'arquitectura.json').write_text(json.dumps(architecture, ensure_ascii=False, indent=2), encoding='utf-8')

    files = ['part1_results.jsonl', 'part1_results_100k_files.jsonl', 'part1_results_100k_indexes.jsonl']
    rows = []
    for name in files:
        for line in (ROOT / 'benchmarks/results' / name).read_text().splitlines():
            if line.strip():
                rows.append(dict(json.loads(line), audit_file=name))
    groups = defaultdict(list)
    keys = Counter()
    problems = []
    for row in rows:
        group = tuple(row[k] for k in ['experiment', 'structure', 'operation', 'size']) + (row.get('selectivity'),)
        groups[group].append(row)
        keys[group + (row['repetition'],)] += 1
        elapsed, count = row['elapsed_seconds'], row['count']
        if elapsed is not None and (not math.isfinite(elapsed) or elapsed < 0):
            problems.append(dict(problem='invalid_time', group=group))
        expected = None if elapsed is None or not count else elapsed*1000/count
        if row['per_operation_ms'] != expected:
            problems.append(dict(problem='invalid_per_operation', group=group))
        if row['operation'].endswith(('present', 'absent')):
            expected_found = count if row['operation'].endswith('present') else 0
            if row['found'] != expected_found:
                problems.append(dict(problem='wrong_lookup_count', group=group))
    repetitions = {1000: 5, 10000: 5, 100000: 3}
    for group, items in groups.items():
        if sorted(row['repetition'] for row in items) != list(range(1, repetitions[group[3]]+1)):
            problems.append(dict(problem='missing_repetition', group=group))
    mixed = [{k: row[k] for k in ['size', 'repetition', 'structure', 'count', 'inserted', 'deleted',
                                  'elapsed_seconds', 'valid', 'completed_target']} for row in rows
             if row['operation'] == 'insert_delete_workload']
    source_versions = {}
    for commit in sorted({row['environment']['git_commit'] for row in rows} | {git('rev-parse', 'HEAD').decode().strip()}):
        source_versions[commit] = digest_at(commit)
    evidence = dict(rows=len(rows), files=files, repeated_keys=[list(key) for key, count in keys.items() if count != 1],
                    problems=problems, sizes=Counter(row['size'] for row in rows),
                    source_digests_by_commit=source_versions,
                    recorded_environments=list({json.dumps(row['environment'], sort_keys=True) for row in rows}),
                    mixed_workloads=mixed,
                    aggregates=[dict(group=list(group), n=len(items), median_seconds=statistics.median(
                        row['elapsed_seconds'] for row in items)) for group, items in groups.items()])
    (OUT / 'experimentos_auditados.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    remote = git('ls-remote', 'origin', 'HEAD', 'refs/heads/main').decode()
    (OUT / 'remoto_verificado.txt').write_text(remote, encoding='utf-8')
    print(json.dumps(dict(modules=len(graph), acyclic=acyclic, measurements=len(rows),
                         data_problems=len(problems), repeated_keys=sum(count != 1 for count in keys.values())), indent=2))


if __name__ == '__main__':
    main()
