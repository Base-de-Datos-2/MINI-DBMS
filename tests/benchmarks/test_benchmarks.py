"""Stage 10 Task 10.4: datasets, raw-result recording and experiment smoke runs."""

import ast
from pathlib import Path

from benchmarks import file_organization, indexes
from benchmarks.datasets import SCHEMA, generate, seed_for, write_csv
from benchmarks.harness import ResultWriter, read_results


def test_datasets_are_reproducible_unique_and_in_random_key_order():
    first, again = generate(500), generate(500)

    assert first == again
    keys = [row[0] for row in first]
    assert sorted(keys) == list(range(1, 501))
    assert keys != sorted(keys)
    assert generate(500, seed=seed_for(500) + 1) != first
    assert all(len(row) == len(SCHEMA.columns) for row in first)


def test_csv_export_has_the_schema_header(tmp_path):
    path = write_csv(generate(3), tmp_path / "rows.csv")

    assert path.read_text(encoding="utf-8").splitlines()[0] == "id,name,career,age,score"


def test_writer_records_configuration_environment_and_derived_rate(tmp_path):
    writer = ResultWriter(tmp_path / "r.jsonl", "run", config={"sizes": [10]})
    writer.record(experiment="e", structure="s", operation="o", size=10,
                  repetition=1, elapsed_seconds=0.5, count=4, file_bytes=8)

    [row] = read_results(tmp_path / "r.jsonl")
    assert row["per_operation_ms"] == 125.0
    assert row["file_bytes"] == 8
    assert row["config"] == {"sizes": [10]}
    assert {"python", "git_commit", "cpu_count", "source_sha256"} <= set(row["environment"])
    assert len(row["environment"]["source_sha256"]) == 64


def test_file_organization_smoke_run_records_every_required_measure(tmp_path):
    writer = ResultWriter(tmp_path / "files.jsonl", "smoke", config={})
    file_organization.run(80, 1, writer, tmp_path / "work", present_keys=10, absent_keys=5)

    rows = read_results(tmp_path / "files.jsonl")
    measured = {(row["structure"], row["operation"]) for row in rows}
    assert {
        ("heap", "load"), ("heap", "pk_search_present"), ("heap", "pk_search_absent"),
        ("heap", "reinsert_after_delete"), ("sequential", "load"),
        ("sequential", "load_ascending"), ("sequential", "pk_search_present"),
        ("sequential", "reorganize"),
    } <= measured
    by_key = {(row["structure"], row["operation"]): row for row in rows}
    assert by_key[("heap", "pk_search_present")]["found"] == 10
    assert by_key[("sequential", "pk_search_absent")]["found"] == 0
    assert by_key[("sequential", "reorganize")]["wasted_space_ratio"] == 0.0
    assert not any((tmp_path / "work").iterdir())  # per-run files are removed


def test_index_smoke_run_measures_all_three_structures(tmp_path):
    writer = ResultWriter(tmp_path / "idx.jsonl", "smoke", config={})
    indexes.run(60, 1, writer, tmp_path / "work", present_keys=10, absent_keys=5,
                ranges_per_selectivity=2, workload_operations=6,
                workload_budget_seconds=30)

    rows = read_results(tmp_path / "idx.jsonl")
    for structure in (indexes.CLUSTERED, indexes.UNCLUSTERED, indexes.HASH):
        operations = {row["operation"] for row in rows if row["structure"] == structure}
        assert {"build", "equality_present", "equality_absent", "range",
                "ordered_retrieval", "insert_delete_workload"} <= operations
    workloads = [row for row in rows if row["operation"] == "insert_delete_workload"]
    assert all(row["valid"] and row["count"] == 6 for row in workloads)
    sorted_hash = next(row for row in rows if row["structure"] == indexes.HASH
                       and row["operation"] == "ordered_retrieval")
    assert "ExternalSort" in sorted_hash["access"] and sorted_hash["count"] == 60


def test_benchmark_code_never_lives_in_or_is_imported_by_the_engine():
    engine = Path(__file__).resolve().parents[2] / "engine"
    for path in engine.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("benchmarks"), path
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("benchmarks") for alias in node.names), path


def test_report_uses_medians_and_ranges_from_raw_rows(tmp_path):
    # Synthetic test rows only: the report must aggregate whatever it is given.
    writer = ResultWriter(tmp_path / "raw.jsonl", "test", config={})
    for size, values in ((1_000, (1.0, 2.0, 9.0)), (10_000, (10.0, 20.0, 30.0))):
        for repetition, value in enumerate(values, 1):
            writer.record(experiment="file_organization", structure="heap", operation="load",
                          size=size, repetition=repetition, elapsed_seconds=value, count=size)
    from benchmarks.report import render

    written = render([tmp_path / "raw.jsonl"], tmp_path / "out")

    assert (tmp_path / "out" / "01_insercion.png").stat().st_size > 0
    table = (tmp_path / "out" / "resultados.md").read_text(encoding="utf-8")
    assert "| Heap File | 2.000 [1.000 – 9.000] (n=3) | 20.0 [10.0 – 30.0] (n=3) |" in table
    assert "Paged Sequential (orden aleatorio) | — | — |" in table
    assert len(written) == 2  # one chart with data plus the summary
