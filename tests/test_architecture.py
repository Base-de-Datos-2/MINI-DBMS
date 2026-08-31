"""Stage 1 audit: dependency direction, cycles and fresh installed imports.

Only these inspection tests read source files/start interpreters. They are
separate from the no-file-I/O model/contract integration scenarios.
"""

import ast
from graphlib import TopologicalSorter
from importlib.util import resolve_name
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def engine_sources():
    sources = {}
    for path in sorted((ROOT / "engine").rglob("*.py")):
        parts = list(path.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 11))
        sources[module] = (path, tree)
    return sources


def imported_modules(module, path, tree):
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                name = resolve_name("." * node.level + name, package)
            yield name


def test_engine_dependencies_follow_layer_boundaries_and_use_only_allowed_libraries():
    allowed_layers = {
        "engine": {"errors", "catalog", "storage", "indexes", "operators", "query", "transactions"},
        "errors": set(),
        "catalog": {"errors", "catalog"},
        "storage": {"errors", "catalog", "storage"},
        "indexes": {"errors", "storage", "indexes"},
        "operators": {"errors", "catalog", "storage", "indexes", "operators"},
        "query": {"errors", "catalog", "storage", "indexes", "operators", "query", "transactions"},
        "transactions": {"errors", "catalog", "storage", "indexes", "transactions"},
    }
    for module, (path, tree) in engine_sources().items():
        layer = module.split(".")[1] if "." in module else "engine"
        for imported in imported_modules(module, path, tree):
            root = imported.split(".")[0]
            assert root not in {"api", "frontend", "tests", "pytest", "sqlite3"}, (module, imported)
            if root == "engine":
                target = imported.split(".")[1] if "." in imported else "engine"
                assert target in allowed_layers[layer], (module, imported)
            else:
                assert root in sys.stdlib_module_names, (module, imported)


def test_engine_explicit_module_dependency_graph_has_no_cycles():
    sources = engine_sources()
    graph = {
        module: set(imported_modules(module, path, tree)) & sources.keys()
        for module, (path, tree) in sources.items()
    }
    assert set(TopologicalSorter(graph).static_order()) == sources.keys()


def test_page_layer_does_not_import_records_codecs_or_catalog():
    sources = engine_sources()
    allowed = {
        "engine.storage.binary": {"engine.errors"},
        "engine.storage.slot_entry": {"engine.errors", "engine.storage.binary"},
        "engine.storage.page_header": {"engine.errors", "engine.storage.binary"},
        "engine.storage.page": {
            "engine.errors", "engine.storage.binary", "engine.storage.page_header",
            "engine.storage.slot_entry",
        },
    }
    for module, expected in allowed.items():
        path, tree = sources[module]
        engine_imports = {
            imported for imported in imported_modules(module, path, tree)
            if imported == "engine" or imported.startswith("engine.")
        }
        assert engine_imports == expected, (module, engine_imports)


@pytest.mark.parametrize(
    "first_module",
    ["engine.errors", "engine.catalog.schema", "engine.catalog",
     "engine.storage", "engine.indexes", "engine.operators"],
)
def test_public_imports_work_from_fresh_isolated_interpreters(first_module, tmp_path):
    # -I removes cwd/PYTHONPATH influence: the README's editable installation
    # must work from outside the repository, without pytest preloading modules.
    modules = list(reversed(engine_sources()))
    forbidden = ["tests", "pytest", "api", "frontend", "engine.query", "engine.transactions"]
    if first_module in {"engine.errors", "engine.catalog", "engine.catalog.schema"}:
        forbidden += ["engine.storage", "engine.indexes", "engine.operators"]
    elif first_module == "engine.storage":
        forbidden += ["engine.indexes", "engine.operators"]
    elif first_module == "engine.indexes":
        forbidden += ["engine.operators"]
    if first_module == "engine.errors":
        forbidden += ["engine.catalog"]
    script = f"""
import importlib
from pathlib import Path
import sys

root = Path({str(ROOT)!r}).resolve()
importlib.import_module({first_module!r})
for prefix in {forbidden!r}:
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
for name in {modules!r}:
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
    for symbol in getattr(module, '__all__', ()):
        value = getattr(module, symbol)
        assert getattr(importlib.import_module(value.__module__), symbol) is value
assert not any(name == 'tests' or name.startswith('tests.') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script], cwd=tmp_path,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
