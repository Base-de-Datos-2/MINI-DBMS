"""Tables, figures and gallery for the Part 4 experiment.

    python -m benchmarks.multimedia.results --input benchmarks/results/multimedia/<date> \
        --output docs/figuras/multimedia

Refuses incomplete matrices (every size x config x repetition x query must be
present). Colours follow the validated palette used in Part 3: IVF #2a78d6,
HNSW #eb6834, exact VectorScan reference in neutral grey; metrics are panels.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics

import numpy as np

from .experiment import CONFIGS, K, REPETITIONS, SIZES

COLORS = {"ivf": "#2a78d6", "hnsw": "#eb6834", "exact": "#8a8a8a"}
LABELS = {"ivf": "IVF", "hnsw": "HNSW"}
METRICS = ("euclidean", "cosine")


def load(directory: Path) -> dict:
    data = {"environment": json.loads((directory / "environment.json").read_text()), "build": {}, "exact": {},
            "queries": {}, "prepare": {}}
    for size in SIZES:
        data["prepare"][size] = json.loads((directory / f"prepare_{size}.json").read_text())
        data["exact"][size] = json.loads((directory / f"exact_{size}.json").read_text())
        # Exact top-10 reference ids/scores (copied from the work directory).
        data["exact"][size].update(json.loads((directory / f"exact_top10_{size}.json").read_text()))
        for config in CONFIGS:
            data["build"][(size, config)] = json.loads((directory / f"build_{size}_{config}.json").read_text())
            for repetition in range(REPETITIONS):
                path = directory / f"query_{size}_{config}_r{repetition}.json"
                if not path.exists():
                    raise SystemExit(f"Incomplete matrix: {path.name} is missing")
                result = json.loads(path.read_text())
                if len(result["rows"]) != 30 or len({row["query"] for row in result["rows"]}) != 30:
                    raise SystemExit(f"{path.name} does not hold the 30 distinct queries")
                data["queries"][(size, config, repetition)] = result
    return data


def summarize(data: dict) -> dict:
    summary = {}
    for size in SIZES:
        for config in CONFIGS:
            rows = [row for r in range(REPETITIONS) for row in data["queries"][(size, config, r)]["rows"]]
            seconds = [row["seconds"] for row in rows]
            recalls = [row["recall"] for row in data["queries"][(size, config, 0)]["rows"]]
            stable = all(data["queries"][(size, config, 0)]["rows"][i]["ids"] ==
                         data["queries"][(size, config, r)]["rows"][i]["ids"]
                         for r in range(REPETITIONS) for i in range(30))
            build = data["build"][(size, config)]
            query_runs = [data["queries"][(size, config, r)] for r in range(REPETITIONS)]
            summary[(size, config)] = {
                "size": size, "config": config,
                "build_seconds": build["seconds"], "build_peak_mib": build["memory_peak"]["peak_mib"],
                "index_bytes": build["index_bytes"],
                "query_mean_ms": 1000 * statistics.fmean(seconds),
                "query_median_ms": 1000 * statistics.median(seconds),
                "query_min_ms": 1000 * min(seconds), "query_max_ms": 1000 * max(seconds),
                "recall_mean": statistics.fmean(recalls), "recall_min": min(recalls),
                "queries_with_perfect_recall": sum(r == 1.0 for r in recalls),
                "evaluated_mean": statistics.fmean(row["evaluated"] for row in rows),
                "loaded_rss_mib": max(q["memory_loaded"]["rss_mib"] for q in query_runs),
                "query_peak_mib": max(q["memory_query_peak"]["peak_mib"] for q in query_runs),
                "deterministic_across_repetitions": stable,
                "timed_searches": len(seconds)}
    return summary


def write_tables(data: dict, summary: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    fields = list(next(iter(summary.values())).keys())
    with open(output / "resumen_multimedia.csv", "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for key in sorted(summary, key=lambda k: (k[0], CONFIGS.index(k[1]))):
            writer.writerow({k: round(v, 6) if isinstance(v, float) else v for k, v in summary[key].items()})
    with open(output / "consultas_multimedia.csv", "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["modality", "size", "query", "index", "metric", "repetition", "k", "search_parameter",
                         "seconds", "recall_at_10", "evaluated", "status"])
        for (size, config, repetition), result in sorted(data["queries"].items(),
                                                         key=lambda item: (item[0][0], item[0][1], item[0][2])):
            method, metric = config.split("-")
            for row in result["rows"]:
                parameter = (f"nprobe={row['details'].get('nprobe_requested')}" if method == "ivf"
                             else f"ef={row['details'].get('ef_search')}")
                writer.writerow(["image", size, row["query"], method.upper(), metric, repetition, K, parameter,
                                 f"{row['seconds']:.9f}", row["recall"], row["evaluated"],
                                 "shortfall" if row["details"].get("shortfall") else "ok"])
    with open(output / "construccion_multimedia.csv", "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["size", "config", "seconds", "peak_rss_mib", "index_bytes", "parameters"])
        for (size, config), build in sorted(data["build"].items(), key=lambda item: (item[0][0], item[0][1])):
            writer.writerow([size, config, f"{build['seconds']:.6f}", f"{build['memory_peak']['peak_mib']:.1f}",
                             build["index_bytes"], json.dumps(build["parameters"], sort_keys=True)])


def figures(data: dict, summary: dict, output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.8})

    def panels(value, ylabel, title, filename, log=True, exact=None):
        figure, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
        for axis, metric in zip(axes, METRICS):
            for method in ("ivf", "hnsw"):
                values = [value(summary[(n, f"{method}-{metric}")]) for n in SIZES]
                axis.plot(SIZES, values, marker="o", markersize=8, linewidth=2, color=COLORS[method],
                          label=LABELS[method])
            if exact is not None:
                axis.plot(SIZES, [exact(n, metric) for n in SIZES], linestyle="--", marker="s", markersize=6,
                          linewidth=1.5, color=COLORS["exact"], label="VectorScan (exacto)")
            axis.set_xscale("log")
            if log:
                axis.set_yscale("log")
            axis.set_xticks(SIZES, ["1 000", "10 000", "100 000"])
            axis.set_title("Euclidiana" if metric == "euclidean" else "Coseno")
            axis.set_xlabel("Imágenes en la colección (N)")
        axes[0].set_ylabel(ylabel)
        axes[1].legend(frameon=False)
        figure.suptitle(title)
        figure.tight_layout()
        figure.savefig(output / filename, dpi=150)
        plt.close(figure)

    panels(lambda s: s["build_seconds"], "Segundos", "Construcción del índice (vectores ya preparados)",
           "construccion.png")
    panels(lambda s: s["query_mean_ms"], "Milisegundos por consulta (media)", "Tiempo de consulta k=10",
           "consultas.png",
           exact=lambda n, m: 1000 * data["exact"][n]["vectorscan"][m]["mean_seconds"])
    panels(lambda s: s["recall_mean"], "Recall@10 medio", "Precisión respecto de la búsqueda exacta",
           "recall.png", log=False)

    figure, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    labels = [c.replace("-euclidean", "\neuclidiana").replace("-cosine", "\ncoseno").upper().replace(
        "EUCLIDIANA", "euclidiana").replace("COSENO", "coseno") for c in CONFIGS]
    positions = np.arange(len(CONFIGS))
    colors = [COLORS[c.split("-")[0]] for c in CONFIGS]
    largest = SIZES[-1]
    axes[0].bar(positions, [summary[(largest, c)]["index_bytes"] / 2**20 for c in CONFIGS], color=colors,
                edgecolor="white", linewidth=2)
    axes[0].set_ylabel("MiB en disco")
    axes[0].set_title(f"Tamaño del índice (N = {largest:,})".replace(",", " "))
    axes[1].bar(positions - 0.2, [summary[(largest, c)]["build_peak_mib"] for c in CONFIGS], width=0.38,
                color=colors, edgecolor="white", linewidth=2, label="pico al construir")
    axes[1].bar(positions + 0.2, [summary[(largest, c)]["query_peak_mib"] for c in CONFIGS], width=0.38,
                color=colors, edgecolor="white", linewidth=2, hatch="//", alpha=0.7, label="pico al consultar")
    axes[1].set_ylabel("MiB (pico de RSS del proceso)")
    axes[1].set_title("Memoria")
    axes[1].legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    for axis in axes:
        axis.set_xticks(positions, labels)
    figure.tight_layout()
    figure.savefig(output / "memoria.png", dpi=150)
    plt.close(figure)


def gallery(data: dict, output: Path, images: Path) -> dict:
    """Success/error gallery at N=100,000 with HNSW + cosine against the exact top-5."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    size, config = SIZES[-1], "hnsw-cosine"
    rows = data["queries"][(size, config, 0)]["rows"]
    exact = data["exact"][size]["top10"]["cosine"]
    exact_by_query = dict(zip(data["exact"][size]["queries"], exact))
    best = max(rows, key=lambda row: exact_by_query[row["query"]][0][1])
    worst = min(rows, key=lambda row: (row["recall"], -exact_by_query[row["query"]][0][1]))
    # (b) the index returns exactly the exact neighbours, yet they may look
    # unrelated: a representation limit; (a) the index misses exact neighbours.
    cases = [("(b) HNSW = exacto; ¿se parecen?", best), ("(a) Fallo del índice: menor recall", worst)]
    figure, axes = plt.subplots(2 * len(cases), 6, figsize=(13, 4.6 * len(cases)))
    for block, (title, row) in enumerate(cases):
        truth = [object_id for object_id, _ in exact_by_query[row["query"]]][:5]
        for line, (label, ids) in enumerate((("HNSW", row["ids"][:5]), ("Exacto", truth))):
            axis_row = axes[2 * block + line]
            first = Image.open(images / f"{row['query']:012d}.jpg")
            axis_row[0].imshow(first)
            axis_row[0].set_title(f"{title}\nconsulta {row['query']}" if line == 0 else "consulta", fontsize=8)
            for column, object_id in enumerate(ids, 1):
                axis_row[column].imshow(Image.open(images / f"{object_id:012d}.jpg"))
                marker = "" if object_id in truth else " ✗"
                axis_row[column].set_title(f"{label} #{column}: {object_id}{marker}", fontsize=8)
            for axis in axis_row:
                axis.axis("off")
    figure.tight_layout()
    figure.savefig(output / "galeria.png", dpi=110)
    plt.close(figure)
    return {"size": size, "config": config,
            "cases": [{"title": title, "query": row["query"], "recall": row["recall"],
                       "hnsw_top5": row["ids"][:5],
                       "exact_top5": [i for i, _ in exact_by_query[row["query"]]][:5],
                       "exact_top1_cosine": exact_by_query[row["query"]][0][1]} for title, row in cases]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/figuras/multimedia"))
    parser.add_argument("--images", type=Path, default=Path("data/generated/multimedia/coco/images"))
    args = parser.parse_args(argv)
    data = load(args.input)
    summary = summarize(data)
    write_tables(data, summary, args.output)
    figures(data, summary, args.output)
    cases = gallery(data, args.output, args.images)
    payload = {"summary": [summary[k] for k in sorted(summary, key=lambda k: (k[0], CONFIGS.index(k[1])))],
               "vectorscan": {str(n): data["exact"][n]["vectorscan"] for n in SIZES},
               "prepare": {str(n): data["prepare"][n] for n in SIZES}, "gallery": cases}
    (args.output / "resumen_multimedia.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps([{k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()
                       if k in ("size", "config", "build_seconds", "query_mean_ms", "recall_mean")}
                      for s in payload["summary"]]), flush=True)


if __name__ == "__main__":
    main()
