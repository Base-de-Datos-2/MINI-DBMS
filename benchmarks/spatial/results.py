"""Verify measured artifacts and generate tables and figures, without reruns."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import tarfile
from tempfile import TemporaryDirectory

from .datasets import REQUIRED_SIZES, export, query_centers
from .measurement import SETTINGS
from .validation import uses_gist


METHODS = ("scan", "rtree", "gist")
LABELS = {"scan": "Secuencial", "rtree": "R-Tree propio", "gist": "PostgreSQL GiST"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive_number(value, *, zero=False):
    return type(value) in (float, int) and math.isfinite(value) and (value >= 0 if zero else value > 0)


def summarize(rows, *, method, size, centers, references):
    groups = {(kind, value): [] for kind, value in SETTINGS}
    for row in rows:
        key = row["kind"], row["value"]
        require(key in groups, "Unexpected query setting")
        identity = row["query_id"]
        require(type(identity) is int and identity in centers, "Unexpected query identity")
        expected = references[str(identity)][f"{key[0]}:{key[1]}"]
        require(row["method"] == method and row["size"] == size and row["metric"] == "haversine",
                "Inconsistent measurement context")
        require(row["center"] == centers[identity], "Changed query coordinates")
        require(row["validated"] is True and row["result_count"] == expected["count"]
                and row["result_ids_sha256"] == expected["ids_sha256"], "Unverified or inconsistent results")
        require(positive_number(row["elapsed_seconds"]), "Invalid measured time")
        require(row["access"] == {"scan": "SpatialScan", "rtree": "RTree", "gist": "GiST"}[method],
                "Unexpected access path")
        if method == "gist":
            require(uses_gist(row["plan"]), "GiST execution evidence is missing")
            require(positive_number(row["server_seconds"], zero=True), "Invalid server time")
        groups[key].append(row)
    summaries = []
    for (kind, value), samples in groups.items():
        require(len(samples) == len(centers) and {row["query_id"] for row in samples} == set(centers),
                "Missing or duplicate query samples")
        times = [row["elapsed_seconds"] for row in samples]
        summaries.append({
            "size": size, "method": method, "metric": "haversine", "kind": kind, "value": value,
            "sample_count": len(times), "mean_ms": statistics.mean(times) * 1000,
            "median_ms": statistics.median(times) * 1000,
            "min_ms": min(times) * 1000, "max_ms": max(times) * 1000,
            "mean_result_count": statistics.mean(row["result_count"] for row in samples),
            "mean_server_ms": statistics.mean(row["server_seconds"] for row in samples) * 1000
                              if method == "gist" else None,
        })
    return summaries


def load_results(directory):
    directory = Path(directory)
    metadata = read_json(directory / "completed.json")
    initial = read_json(directory / "manifest.json")
    require({key: value for key, value in metadata.items() if key != "sizes"}
            == {key: value for key, value in initial.items() if key != "sizes"}, "Completion metadata changed")
    require(metadata["format"] == "MINIDBMS_SPATIAL_EXPERIMENTS" and metadata["version"] == 1
            and metadata["official_matrix"] is True, "Not a completed official experiment")
    require(metadata["methods"] == list(METHODS)
            and sorted(item["size"] for item in metadata["sizes"]) == list(REQUIRED_SIZES), "Incomplete matrix")
    inputs = metadata["input_manifest"]
    require(inputs["sizes"] == list(REQUIRED_SIZES) and inputs["query_count"] == 100,
            "Unexpected dataset/query counts")
    with TemporaryDirectory(prefix="minidbms-spatial-input-check-") as temporary:
        regenerated = export(Path(temporary) / "inputs", REQUIRED_SIZES, inputs["seed"])
        require(regenerated["sha256"] == inputs["sha256"], "Dataset regeneration checksum mismatch")
    snapshot = metadata["source_snapshot"]
    require(digest(directory / "source.tar.gz") == snapshot["archive_sha256"], "Source archive checksum mismatch")
    with tarfile.open(directory / "source.tar.gz", "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        require(len(members) == len(snapshot["files"]) and {member.name for member in members} == set(snapshot["files"]),
                "Source archive member mismatch")
        for member in members:
            with archive.extractfile(member) as source:
                require(hashlib.sha256(source.read()).hexdigest() == snapshot["files"][member.name],
                        "Archived source file checksum mismatch")
    centers = {identity: [latitude, longitude] for identity, latitude, longitude in query_centers(inputs["seed"])}
    summaries, resources = [], []
    for item in metadata["sizes"]:
        size = item["size"]
        oracle_path = directory / f"oracle_{size}.json"
        require(digest(oracle_path) == item["oracle_sha256"], "Oracle checksum mismatch")
        oracle = read_json(oracle_path)
        require(oracle["points_sha256"] == inputs["sha256"][f"points_{size}.csv"]
                and {identity: [lat, lon] for identity, lat, lon in oracle["centers"]} == centers,
                "Oracle input mismatch")
        for method in METHODS:
            path = directory / f"{method}_{size}.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            summaries.extend(summarize(rows, method=method, size=size, centers=centers,
                                       references=oracle["references"]))
            resource = read_json(directory / f"{method}_{size}.resources.json")
            require(resource["method"] == method and resource["size"] == size
                    and resource["query_count_per_setting"] == 100, "Resource metadata mismatch")
            for name in ("data_bytes", "peak_rss_bytes"):
                require(type(resource[name]) is int and resource[name] > 0, "Invalid resource measurement")
            require(type(resource["index_bytes"]) is int and resource["index_bytes"] >= 0,
                    "Invalid index size")
            if method == "scan":
                require(resource["build_seconds"] is None and resource["index_bytes"] == 0,
                        "Sequential scan cannot have an index build")
            else:
                require(positive_number(resource["build_seconds"]) and resource["index_bytes"] > 0,
                        "Missing index build measurement")
            resources.append(resource)
    return metadata, summaries, resources


def write_csv(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def figures(output, summaries, resources):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    lookup = {(row["size"], row["method"], row["kind"], row["value"]): row for row in summaries}
    for kind, values, title in (("radius", (1000, 5000, 10000), "Consultas por radio"),
                                ("knn", (10, 50, 100), "Vecinos más cercanos")):
        figure, axes = plt.subplots(1, 3, figsize=(14, 4.8), layout="constrained")
        for axis, value in zip(axes, values):
            for method in METHODS:
                times = [lookup[size, method, kind, value]["mean_ms"] for size in REQUIRED_SIZES]
                axis.plot(REQUIRED_SIZES, times, marker="o", label=LABELS[method])
            axis.set(xscale="log", yscale="log", xlabel="Registros", ylabel="Media de 100 consultas (ms)",
                     title=f"Radio {value / 1000:g} km" if kind == "radius" else f"k = {value}")
            axis.set_xticks(REQUIRED_SIZES, ["1.000", "10.000", "100.000"])
            axis.grid(True, which="major", alpha=.25)
        axes[0].legend(loc="best", fontsize=8)
        figure.suptitle(f"{title} · Haversine · tiempos completos de cliente")
        for suffix in ("png", "svg"):
            figure.savefig(output / f"{kind}.{suffix}", dpi=180)
        plt.close(figure)
    by_resource = {(row["size"], row["method"]): row for row in resources}
    figure, axes = plt.subplots(1, 3, figsize=(14, 4.8), layout="constrained")
    for axis, name, title, divisor, methods in (
        (axes[0], "build_seconds", "Construcción persistente del índice (s)", 1, METHODS[1:]),
        (axes[1], "index_bytes", "Archivo del índice (MiB)", 2 ** 20, METHODS[1:]),
        (axes[2], "data_bytes", "Almacenamiento de datos (MiB)", 2 ** 20, METHODS),
    ):
        for offset, method in enumerate(methods):
            positions = [index + (offset - (len(methods) - 1) / 2) * .24 for index in range(3)]
            axis.bar(positions, [by_resource[size, method][name] / divisor for size in REQUIRED_SIZES],
                     width=.22, label=LABELS[method])
        axis.set(title=title, yscale="log", xlabel="Registros")
        axis.set_xticks(range(3), ["1.000", "10.000", "100.000"])
        axis.grid(True, axis="y", alpha=.25)
        axis.legend(fontsize=8)
    figure.suptitle("Recursos medidos · carga inicial excluida del tiempo de construcción")
    for suffix in ("png", "svg"):
        figure.savefig(output / f"recursos.{suffix}", dpi=180)
    plt.close(figure)
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.8), layout="constrained")
    for axis, methods, title in ((axes[0], METHODS[:2], "Trabajador Python: imports, índice, oráculo y resultados"),
                                (axes[1], METHODS[2:], "Backend PostgreSQL: incluye mapeos compartidos")):
        for method in methods:
            axis.plot(REQUIRED_SIZES, [by_resource[size, method]["peak_rss_bytes"] / 2 ** 20
                                      for size in REQUIRED_SIZES], marker="o", label=LABELS[method])
        axis.set(xscale="log", xlabel="Registros", ylabel="Pico RSS del proceso (MiB)", title=title)
        axis.set_xticks(REQUIRED_SIZES, ["1.000", "10.000", "100.000"])
        axis.grid(True, alpha=.25)
        axis.legend(fontsize=8)
    figure.suptitle("Memoria observada · ámbitos distintos; no sumar ni equiparar procesos")
    for suffix in ("png", "svg"):
        figure.savefig(output / f"memoria.{suffix}", dpi=180)
    plt.close(figure)


def generate(directory, output):
    metadata, summaries, resources = load_results(directory)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    summaries.sort(key=lambda row: (row["size"], row["kind"], row["value"], METHODS.index(row["method"])))
    write_csv(output / "consultas.csv", summaries)
    write_csv(output / "recursos.csv", [{key: row.get(key) for key in (
        "size", "method", "build_seconds", "build_server_seconds", "data_bytes", "index_bytes",
        "primary_index_bytes", "peak_rss_bytes", "memory_scope", "build_includes",
    )} for row in resources])
    figures(output, summaries, resources)
    validation = {"run_id": metadata["run_id"], "source_commit": metadata["source_commit"],
                  "source_archive_verified": True, "datasets_regenerated_and_verified": True,
                  "configurations": len(summaries), "samples": sum(row["sample_count"] for row in summaries),
                  "gist_plans_checked": 1800,
                  "input_sha256": {path.name: digest(path) for path in sorted(Path(directory).iterdir())
                                   if path.is_file()},
                  "output_sha256": {path.name: digest(path) for path in sorted(output.iterdir())
                                    if path.is_file() and path.name != "verificacion.json"}}
    (output / "verificacion.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    return validation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    validation = generate(args.input, args.output)
    print(f"Verified {validation['samples']} measurements in {validation['configurations']} configurations")


if __name__ == "__main__":
    main()
