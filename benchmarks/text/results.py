"""Verify Part 3 raw results, then write summary tables and the four figures.

Nothing is re-measured here. Incomplete, duplicated or semantically failed
artifacts raise ValueError instead of producing a table or a graph.

    python -m benchmarks.text.results --input benchmarks/results/text/<run> \
        --output docs/figuras/text
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import statistics

from .experiment import METHODS, REPETITIONS, SIZES
from .metrics import mean

GROUPS = ("1", "3", "5plus")
GROUP_LABELS = {"1": "1 palabra", "3": "3 palabras", "5plus": "5+ palabras", "all": "Todas"}
LABELS = {"tfidf": "MINI-DBMS TF-IDF/coseno", "bm25": "MINI-DBMS BM25",
          "postgres": "PostgreSQL FTS + GIN + ts_rank", "spimi": "MINI-DBMS SPIMI (compartido)"}
# Validated categorical slots (light surface); fixed per entity, never by rank.
COLORS = {"tfidf": "#2a78d6", "bm25": "#eb6834", "postgres": "#1baf7a", "spimi": "#6250d6"}
MARKERS = {"tfidf": "o", "bm25": "s", "postgres": "^", "spimi": "D"}
STAGE_COLORS = ("#86b6ef", "#3987e5", "#1c5cab", "#0d366b")  # blue ramp, ordinal stages
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value, *, positive=True):
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def load_queries(directory: Path, size: int, query_ids: set[int]) -> list[dict]:
    rows = [json.loads(line) for line in (directory / f"queries_{size}.jsonl").read_text(encoding="utf-8").splitlines()]
    seen = set()
    for row in rows:
        key = (row["method"], row["query_id"], row["repetition"])
        require(key not in seen, f"Duplicate measurement {key} at N={size}")
        seen.add(key)
        require(row["size"] == size and row["method"] in METHODS and row["query_id"] in query_ids,
                f"Unexpected measurement row at N={size}: {key}")
        require(finite(row["elapsed_seconds"]), f"Invalid elapsed time {key}")
        require(row["method"] != "postgres" or finite(row["server_seconds"]), f"Missing server time {key}")
        require(0 <= row["precision_at_10"] <= 1, f"Invalid precision {key}")
    expected = {(method, query_id, repetition) for method in METHODS for query_id in query_ids
                for repetition in range(REPETITIONS)}
    require(seen == expected, f"Incomplete query matrix at N={size}: {len(seen)} of {len(expected)}")
    return rows


def summarize(directory: Path) -> dict:
    environment = read_json(directory / "environment.json")
    require(environment.get("format") == "MINIDBMS_TEXT_EXPERIMENT", "Not a text experiment directory")
    summary = {"environment": environment, "sizes": {}}
    for size in SIZES:
        semantics = read_json(directory / f"semantics_{size}.json")
        require(semantics["lexemes"]["equal"] and semantics["all_match_sets_equal"]
                and semantics["all_index_equals_scan"], f"Semantic verification failed at N={size}")
        query_ids = {entry["query_id"] for entry in semantics["queries"]}
        require(len(query_ids) == environment["query_count"], "Query set mismatch")
        rows = load_queries(directory, size, query_ids)
        groups_of = {row["query_id"]: row["group"] for row in rows}
        timing, relevance = {}, {}
        for method in METHODS:
            for group in (*GROUPS, "all"):
                selected = [row for row in rows if row["method"] == method
                            and (group == "all" or row["group"] == group)]
                milliseconds = [row["elapsed_seconds"] * 1000 for row in selected]
                server = [row["server_seconds"] * 1000 for row in selected if row["server_seconds"] is not None]
                first = [row for row in selected if row["repetition"] == 0]
                timing[f"{method}:{group}"] = {
                    "samples": len(milliseconds), "mean_ms": statistics.fmean(milliseconds),
                    "median_ms": statistics.median(milliseconds),
                    "min_ms": min(milliseconds), "max_ms": max(milliseconds),
                    "mean_server_ms": statistics.fmean(server) if server else None}
                relevance[f"{method}:{group}"] = {
                    "queries": len(first),
                    "precision_at_10": mean(row["precision_at_10"] for row in first),
                    "recall_at_10": mean(row["recall_at_10"] for row in first),
                    "recall_not_evaluable": sum(row["recall_at_10"] is None for row in first)}
        per_query = defaultdict(dict)
        for row in rows:
            if row["repetition"] == 0:
                per_query[row["query_id"]][row["method"]] = {
                    "precision_at_10": row["precision_at_10"], "recall_at_10": row["recall_at_10"],
                    "top10": [identity for identity, _ in row["top10"]]}
        plans = read_json(directory / f"plans_{size}.json")
        engine = read_json(directory / f"build_engine_{size}.json")
        postgres = read_json(directory / f"build_postgres_{size}.json")
        resources = read_json(directory / f"query_resources_{size}.json")
        summary["sizes"][str(size)] = {
            "timing": timing, "relevance": relevance,
            "per_query": {str(key): {"group": groups_of[key], **value} for key, value in sorted(per_query.items())},
            "postgres_plans": {"uses_gin": sum(plan["uses_gin"] for plan in plans),
                               "sequential_scan": sum("Seq Scan" in plan["node_types"] for plan in plans),
                               "total": len(plans)},
            "build": {"engine": engine, "postgres": postgres}, "query_resources": resources,
            "semantics": {"postgres_matches": sum(q["postgres_matches"] for q in semantics["queries"]),
                          "lexemes": semantics["lexemes"]["postgres"]}}
    return summary


def engine_stages(build: dict) -> dict:
    elapsed = build["elapsed_seconds"]
    stages = elapsed["spimi_stages"]
    return {"Recorrido, tokenización, acumulación y validación": elapsed["spimi_scan_tokenize_accumulate_and_validate"],
            "Volcado de bloques": stages.get("write_blocks", 0.0),
            "Mezcla k-way": stages.get("merge_runs", 0.0),
            "Postings, léxico, estadísticas y normas": stages.get("write_postings_lexicon_statistics_norms", 0.0)}


def write_tables(summary: dict, output: Path):
    with (output / "tiempos_consulta.csv").open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(["documentos", "metodo", "longitud", "muestras", "media_ms", "mediana_ms",
                         "min_ms", "max_ms", "media_servidor_ms"])
        for size in SIZES:
            for key, value in summary["sizes"][str(size)]["timing"].items():
                method, group = key.split(":")
                writer.writerow([size, method, group, value["samples"], f"{value['mean_ms']:.4f}",
                                 f"{value['median_ms']:.4f}", f"{value['min_ms']:.4f}", f"{value['max_ms']:.4f}",
                                 "" if value["mean_server_ms"] is None else f"{value['mean_server_ms']:.4f}"])
    with (output / "relevancia.csv").open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(["documentos", "metodo", "longitud", "consultas", "precision_at_10", "recall_at_10"])
        for size in SIZES:
            for key, value in summary["sizes"][str(size)]["relevance"].items():
                method, group = key.split(":")
                writer.writerow([size, method, group, value["queries"], f"{value['precision_at_10']:.4f}",
                                 f"{value['recall_at_10']:.4f}"])
    with (output / "construccion_y_recursos.csv").open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(["documentos", "spimi_s", "pg_tsvector_s", "pg_gin_s", "pg_construccion_s",
                         "heap_bytes", "indice_spimi_bytes", "spimi_temporal_max_bytes", "pg_tabla_bytes",
                         "pg_gin_bytes", "pg_pk_bytes", "rss_pico_spimi_bytes", "rss_pico_consulta_python_bytes",
                         "rss_pico_backend_pg_construccion_bytes", "rss_pico_backend_pg_consulta_bytes"])
        for size in SIZES:
            entry = summary["sizes"][str(size)]
            engine, postgres = entry["build"]["engine"], entry["build"]["postgres"]
            writer.writerow([size, f"{engine['construction_seconds']:.4f}",
                             f"{postgres['stages']['tsvector_conversion']['elapsed_seconds']:.4f}",
                             f"{postgres['stages']['gin_index']['elapsed_seconds']:.4f}",
                             f"{postgres['construction_seconds']:.4f}", engine["disk"]["heap_bytes"],
                             engine["disk"]["index_total_bytes"], engine["disk"]["spimi_temporary_peak_bytes"],
                             postgres["sizes"]["table_with_toast_bytes"], postgres["sizes"]["gin_bytes"],
                             postgres["sizes"]["primary_key_bytes"], engine["memory"]["rss_peak_during_spimi_bytes"],
                             entry["query_resources"]["python_worker"]["peak_bytes"],
                             peak(postgres["backend_status_end"]),
                             entry["query_resources"]["postgres_backend"]["peak_bytes"]])


def peak(status: str) -> int:
    line = next(line for line in status.splitlines() if line.startswith("VmHWM:"))
    return int(line.split()[1]) * 1024


# --------------------------------------------------------------------------- figures

def styled(axes, title, ylabel, xlabel="Documentos"):
    axes.set_title(title, color=INK, fontsize=11, loc="left")
    axes.set_ylabel(ylabel, color=MUTED)
    if xlabel:
        axes.set_xlabel(xlabel, color=MUTED)
    axes.grid(True, color=GRID, linewidth=0.8)
    axes.set_axisbelow(True)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(MUTED)
    axes.tick_params(colors=MUTED)


def size_axis(axes):
    axes.set_xscale("log")
    axes.set_xticks(SIZES)
    axes.set_xticklabels([f"{size:,}".replace(",", " ") for size in SIZES])
    axes.minorticks_off()


def figures(summary: dict, output: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker  # noqa: F401  (minor-tick locator)
    plt.rcParams.update({"font.size": 9, "figure.facecolor": "white", "axes.facecolor": "white"})
    sizes = [str(size) for size in SIZES]

    # 1. Construction time and SPIMI breakdown.
    figure, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1, 1.25]})
    engine = [summary["sizes"][s]["build"]["engine"]["construction_seconds"] for s in sizes]
    postgres = [summary["sizes"][s]["build"]["postgres"]["construction_seconds"] for s in sizes]
    for key, values in (("spimi", engine), ("postgres", postgres)):
        label = LABELS[key] if key == "spimi" else "PostgreSQL tsvector + GIN"
        left.plot(SIZES, values, color=COLORS[key], marker=MARKERS[key], linewidth=2, markersize=8, label=label)
        left.annotate(f"{values[-1]:.2f} s", (SIZES[-1], values[-1]), textcoords="offset points",
                      xytext=(-6, 8), ha="right", color=INK, fontsize=8)
    left.set_yscale("log")
    size_axis(left)
    styled(left, "Construcción del índice", "Segundos (escala log)")
    left.legend(frameon=False, fontsize=8)
    stages = [engine_stages(summary["sizes"][s]["build"]["engine"]) for s in sizes]
    names = list(stages[0])
    bottom = [0.0] * len(sizes)
    for color, name in zip(STAGE_COLORS, names):
        shares = [100 * stage[name] / sum(stage.values()) for stage in stages]
        right.barh([f"{int(s):,}".replace(",", " ") for s in sizes], shares, left=bottom, color=color,
                   edgecolor="white", linewidth=2, label=name, height=0.55)
        bottom = [b + v for b, v in zip(bottom, shares)]
    styled(right, "Desglose de SPIMI (compartido por TF-IDF y BM25)", "Documentos", "% del tiempo de SPIMI")
    right.set_xlim(0, 100)
    right.legend(frameon=False, fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2)
    figure.tight_layout()
    figure.savefig(output / "construccion.png", dpi=160)
    plt.close(figure)

    # 2. Query time by query length.
    figure, panels = plt.subplots(1, 3, figsize=(12, 3.9), sharey=True)
    for axes, group in zip(panels, GROUPS):
        for method in METHODS:
            values = [summary["sizes"][s]["timing"][f"{method}:{group}"]["mean_ms"] for s in sizes]
            axes.plot(SIZES, values, color=COLORS[method], marker=MARKERS[method], linewidth=2,
                      markersize=8, label=LABELS[method])
        axes.set_yscale("log")
        axes.set_yticks([1, 2, 5, 10, 20, 50])
        axes.set_yticklabels(["1", "2", "5", "10", "20", "50"])
        axes.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
        size_axis(axes)
        styled(axes, f"Consultas de {GROUP_LABELS[group]}", "ms por consulta (media, log)" if group == "1" else "")
    panels[0].legend(frameon=False, fontsize=8)
    figure.tight_layout()
    figure.savefig(output / "consultas.png", dpi=160)
    plt.close(figure)

    # 3. Relevance.
    figure, panels = plt.subplots(1, 2, figsize=(11, 3.9), sharey=True)
    width = 0.26
    for axes, metric, title in zip(panels, ("precision_at_10", "recall_at_10"), ("Precision@10", "Recall@10")):
        for offset, method in enumerate(METHODS):
            values = [summary["sizes"][s]["relevance"][f"{method}:all"][metric] for s in sizes]
            positions = [index + (offset - 1) * width for index in range(len(sizes))]
            axes.bar(positions, values, width=width - 0.03, color=COLORS[method], label=LABELS[method])
            for x, value in zip(positions, values):
                axes.annotate(f"{value:.2f}", (x, value), textcoords="offset points", xytext=(0, 2),
                              ha="center", fontsize=7, color=INK)
        axes.set_xticks(range(len(sizes)))
        axes.set_xticklabels([f"{int(s):,}".replace(",", " ") for s in sizes])
        axes.set_ylim(0, 1)
        styled(axes, f"{title} (media de 30 consultas)", "Valor" if metric == "precision_at_10" else "")
    panels[0].legend(frameon=False, fontsize=8, loc="upper right")
    figure.tight_layout()
    figure.savefig(output / "relevancia.png", dpi=160)
    plt.close(figure)

    # 4. Disk and memory, with their scopes separated.
    figure, (disk, memory) = plt.subplots(1, 2, figsize=(11.5, 4.2))
    mib = 1024 * 1024
    series = [
        ("Heap MINI-DBMS", COLORS["spimi"], None,
         [summary["sizes"][s]["build"]["engine"]["disk"]["heap_bytes"] / mib for s in sizes]),
        ("Índice SPIMI", COLORS["spimi"], "///",
         [summary["sizes"][s]["build"]["engine"]["disk"]["index_total_bytes"] / mib for s in sizes]),
        ("Tabla PG (texto + tsvector)", COLORS["postgres"], None,
         [summary["sizes"][s]["build"]["postgres"]["sizes"]["table_with_toast_bytes"] / mib for s in sizes]),
        ("Índice GIN", COLORS["postgres"], "///",
         [summary["sizes"][s]["build"]["postgres"]["sizes"]["gin_bytes"] / mib for s in sizes]),
    ]
    width = 0.2
    for offset, (label, color, hatch, values) in enumerate(series):
        positions = [index + (offset - 1.5) * width for index in range(len(sizes))]
        disk.bar(positions, values, width=width - 0.02, color="white" if hatch else color,
                 edgecolor=color, hatch=hatch, linewidth=1.5, label=label)
    disk.set_yscale("log")
    disk.set_xticks(range(len(sizes)))
    disk.set_xticklabels([f"{int(s):,}".replace(",", " ") for s in sizes])
    styled(disk, "Espacio en disco", "MiB (escala log)")
    disk.legend(frameon=False, fontsize=7.5)
    series = [
        ("Python: pico durante SPIMI", COLORS["spimi"], None,
         [summary["sizes"][s]["build"]["engine"]["memory"]["rss_peak_during_spimi_bytes"] / mib for s in sizes]),
        ("Python: pico en consultas cronometradas", COLORS["spimi"], "///",
         [summary["sizes"][s]["query_resources"]["python_worker"]["peak_bytes"] / mib for s in sizes]),
        ("Backend PG: pico al construir", COLORS["postgres"], None,
         [peak(summary["sizes"][s]["build"]["postgres"]["backend_status_end"]) / mib for s in sizes]),
        ("Backend PG: pico en consultas cronometradas", COLORS["postgres"], "///",
         [summary["sizes"][s]["query_resources"]["postgres_backend"]["peak_bytes"] / mib for s in sizes]),
    ]
    for offset, (label, color, hatch, values) in enumerate(series):
        positions = [index + (offset - 1.5) * width for index in range(len(sizes))]
        memory.bar(positions, values, width=width - 0.02, color="white" if hatch else color,
                   edgecolor=color, hatch=hatch, linewidth=1.5, label=label)
    memory.set_xticks(range(len(sizes)))
    memory.set_xticklabels([f"{int(s):,}".replace(",", " ") for s in sizes])
    styled(memory, "Memoria: pico RSS por proceso (ámbitos distintos)", "MiB")
    memory.legend(frameon=False, fontsize=7.5, loc="upper left")
    figure.tight_layout()
    figure.savefig(output / "recursos.png", dpi=160)
    plt.close(figure)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = summarize(args.input)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "resumen.json").write_text(json.dumps(summary["sizes"], ensure_ascii=False, indent=1,
                                                         sort_keys=True) + "\n", encoding="utf-8")
    write_tables(summary, args.output)
    figures(summary, args.output)
    print(f"Tables and figures written to {args.output}")


if __name__ == "__main__":
    main()
