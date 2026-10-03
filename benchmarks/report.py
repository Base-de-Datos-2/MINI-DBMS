"""Task 10.10: charts and summary tables generated only from raw results.

Every figure and table value is the median of the repetitions recorded in the
results file, with the minimum and maximum shown as a range. Nothing is
interpolated: a size without measurements is simply absent.

Charts follow one visual system: up to three series per chart in fixed hue
order (blue, orange, aqua), 2 px lines with distinct marker shapes, direct
labels at the line ends plus a legend, hairline solid gridlines, log-log axes
because sizes grow tenfold. The tables carry every plotted value.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from .harness import read_results


SERIES_COLORS = ("#2a78d6", "#eb6834", "#1baf7a")
SERIES_MARKERS = ("o", "s", "^")
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"

LABELS = {
    "heap": "Heap File",
    "sequential": "Paged Sequential",
    "clustered_bplus": "B+ agrupado",
    "unclustered_bplus": "B+ no agrupado",
    "extendible_hash": "Hash extensible",
}
INDEX_ORDER = ("clustered_bplus", "unclustered_bplus", "extendible_hash")


Key = tuple[str, str, str, int, Any]


def aggregate(rows: list[dict[str, Any]], metric: str) -> dict[Key, tuple[float, float, float, int]]:
    """Median, min, max and repetition count of ``metric`` per measurement key."""

    grouped: dict[Key, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(metric)
        if value is None:
            continue
        key = (row["experiment"], row["structure"], row["operation"], row["size"],
               row.get("selectivity"))
        grouped[key].append(float(value))
    return {
        key: (median(values), min(values), max(values), len(values))
        for key, values in grouped.items()
    }


def _series(stats, experiment, structure, operation, selectivity=None):
    points = sorted(
        (key[3], value) for key, value in stats.items()
        if key[:3] == (experiment, structure, operation) and key[4] == selectivity
    )
    return [size for size, _ in points], [value for _, value in points]


def _format(value: float, unit: str) -> str:
    if unit == "KiB":
        return f"{value / 1024:,.1f}"
    if unit == "s":
        return f"{value:,.3f}" if value < 10 else f"{value:,.1f}"
    if unit == "ms":
        return f"{value:,.3f}" if value < 10 else f"{value:,.1f}"
    return f"{value:,.3f}" if value < 1 else f"{value:,.1f}"


def _scale(value: float, unit: str) -> float:
    return value / 1024 if unit == "KiB" else value


def line_chart(path: Path, title: str, unit_label: str, unit: str, series) -> bool:
    """One log-log chart; ``series`` is a list of (label, sizes, stats)."""

    series = [item for item in series if item[1]]
    if not series:
        return False
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.ticker import FuncFormatter, NullFormatter, NullLocator

    figure, axis = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    figure.patch.set_facecolor(SURFACE)
    axis.set_facecolor(SURFACE)
    for position, (label, sizes, stats) in enumerate(series):
        color = SERIES_COLORS[position]
        medians = [_scale(item[0], unit) for item in stats]
        lows = [m - _scale(item[1], unit) for m, item in zip(medians, stats)]
        highs = [_scale(item[2], unit) - m for m, item in zip(medians, stats)]
        axis.errorbar(
            sizes, medians, yerr=[lows, highs], color=color, linewidth=2,
            marker=SERIES_MARKERS[position], markersize=8, markeredgecolor=SURFACE,
            markeredgewidth=2, capsize=0, elinewidth=1, label=label,
            solid_joinstyle="round", solid_capstyle="round",
        )
        axis.annotate(
            label, (sizes[-1], medians[-1]), xytext=(8, 0), textcoords="offset points",
            va="center", fontsize=8, color=TEXT_PRIMARY,
        )
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlabel("Registros", color=TEXT_SECONDARY)
    axis.set_ylabel(unit_label, color=TEXT_SECONDARY)
    axis.set_title(title, loc="left", color=TEXT_PRIMARY, fontsize=11)
    axis.grid(True, which="major", color=GRID, linewidth=0.8, linestyle="-")
    axis.tick_params(colors=TEXT_SECONDARY, labelsize=8)
    for spine in axis.spines.values():
        spine.set_color(GRID)
    all_sizes = sorted({size for _, sizes, _ in series for size in sizes})
    axis.set_xticks(all_sizes, [f"{size:,}" for size in all_sizes])
    axis.xaxis.set_minor_locator(NullLocator())
    axis.xaxis.set_minor_formatter(NullFormatter())
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.10g}"))
    axis.yaxis.set_minor_formatter(NullFormatter())
    axis.set_xlim(all_sizes[0] / 1.6, all_sizes[-1] * 4.5)
    if len(series) > 1:
        axis.legend(frameon=False, fontsize=8, labelcolor=TEXT_PRIMARY,
                    loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=len(series))
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, facecolor=SURFACE)
    plt.close(figure)
    return True


# (file name, title, unit label, unit, metric, experiment, operation, selectivity, structures)
FIGURES = [
    ("01_insercion.png", "Inserción de todos los registros", "segundos (total)", "s",
     "elapsed_seconds", "file_organization", None, None,
     [("Heap File", "heap", "load"),
      ("Paged Sequential (orden aleatorio)", "sequential", "load"),
      ("Paged Sequential (orden ascendente)", "sequential", "load_ascending")]),
    ("02_busqueda_pk.png", "Búsqueda por clave primaria (claves presentes)", "ms por búsqueda", "ms",
     "per_operation_ms", "file_organization", None, None,
     [("Heap File (recorrido)", "heap", "pk_search_present"),
      ("Paged Sequential (búsqueda binaria de página)", "sequential", "pk_search_present")]),
    ("03_espacio_archivos.png", "Espacio en disco tras la carga", "KiB", "KiB",
     "file_bytes", "file_organization", None, None,
     [("Heap File", "heap", "load"),
      ("Paged Sequential (orden aleatorio)", "sequential", "load"),
      ("Paged Sequential (orden ascendente)", "sequential", "load_ascending")]),
    ("04_reorganizacion.png", "Reorganización del Paged Sequential tras borrar 40 %", "segundos", "s",
     "elapsed_seconds", "file_organization", None, None,
     [("Paged Sequential", "sequential", "reorganize")]),
    ("05_construccion_indices.png", "Construcción del índice", "segundos", "s",
     "elapsed_seconds", "indexes", "build", None, None),
    ("06_espacio_indices.png", "Espacio adicional del índice", "KiB", "KiB",
     "index_bytes", "indexes", "build", None, None),
    ("07_igualdad.png", "Búsqueda por igualdad (claves presentes)", "ms por búsqueda", "ms",
     "per_operation_ms", "indexes", "equality_present", None, None),
    ("08_rango_1pct.png", "Búsqueda por rango, selectividad 1 %", "ms por consulta", "ms",
     "per_operation_ms", "indexes", "range", 0.01, None),
    ("09_rango_10pct.png", "Búsqueda por rango, selectividad 10 %", "ms por consulta", "ms",
     "per_operation_ms", "indexes", "range", 0.10, None),
    ("10_ordenamiento.png", "Recuperación ordenada de toda la tabla", "segundos", "s",
     "elapsed_seconds", "indexes", "ordered_retrieval", None, None),
    ("11_carga_mixta.png", "Inserciones y eliminaciones frecuentes", "operaciones por segundo", "ops",
     "operations_per_second", "indexes", "insert_delete_workload", None, None),
]


def render(results: list[Path], output: Path) -> list[Path]:
    rows = [row for path in results for row in read_results(path)]
    written = []
    tables = ["# Resultados de la Etapa 10", "",
              "Mediana de las repeticiones, con [mínimo – máximo]. Generado por "
              "`python -m benchmarks report` a partir de: "
              + ", ".join(f"`{path.as_posix()}`" for path in results) + ".", ""]
    for name, title, unit_label, unit, metric, experiment, operation, selectivity, structures in FIGURES:
        stats = aggregate(rows, metric)
        if structures is None:
            structures = [(LABELS[structure], structure, operation) for structure in INDEX_ORDER]
        series = []
        for label, structure, op in structures:
            sizes, values = _series(stats, experiment, structure, op, selectivity)
            series.append((label, sizes, values))
        if line_chart(output / name, title, unit_label, unit, series):
            written.append(output / name)
        sizes = sorted({size for _, item_sizes, _ in series for size in item_sizes})
        if not sizes:
            continue
        tables += [f"## {title}", "", f"![{title}]({name})", "",
                   f"| Estructura | " + " | ".join(f"{size:,} ({unit_label})" for size in sizes) + " |",
                   "|---|" + "---:|" * len(sizes)]
        for label, item_sizes, values in series:
            cells = []
            for size in sizes:
                if size in item_sizes:
                    m, lo, hi, n = values[item_sizes.index(size)]
                    cells.append(f"{_format(m, unit)} [{_format(lo, unit)} – {_format(hi, unit)}] (n={n})")
                else:
                    cells.append("—")
            tables.append(f"| {label} | " + " | ".join(cells) + " |")
        tables.append("")
    output.mkdir(parents=True, exist_ok=True)
    summary = output / "resultados.md"
    summary.write_text("\n".join(tables) + "\n", encoding="utf-8")
    written.append(summary)
    return written
