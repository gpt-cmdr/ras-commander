"""Build a self-contained HTML decision report from raster benchmark JSON.

The report intentionally distinguishes three layers of evidence:

* isolated copied-TiffAssist writer measurements;
* paired real StoreMap measurements; and
* full large-watershed process-tree profiles.

No plotting dependency or web connection is required. Charts are accessible inline
SVG, and the normalized numbers are written beside the HTML as JSON.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

MIB = 1024 * 1024
COLORS = ("#0b6e69", "#d97706", "#2563eb", "#9333ea", "#dc2626")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _median(values: Iterable[float | int | None]) -> float | None:
    valid = [float(value) for value in values if value is not None]
    return statistics.median(valid) if valid else None


def _format(value: float | None, digits: int = 1) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{value:,.{digits}f}"


def _batch_label(batch_bytes: int) -> str:
    if batch_bytes < MIB:
        return f"{batch_bytes // 1024} KiB"
    return f"{batch_bytes / MIB:g} MiB"


def _svg_line_chart(
    title: str,
    x_labels: Sequence[str],
    series: Sequence[tuple[str, Sequence[float | None]]],
    *,
    y_label: str,
    width: int = 820,
    height: int = 320,
) -> str:
    """Render a compact accessible line chart with an explicit table fallback."""

    left, right, top, bottom = 72, 20, 42, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [float(v) for _, items in series for v in items if v is not None]
    y_max = max(values, default=1.0)
    y_min = min(0.0, min(values, default=0.0))
    if math.isclose(y_max, y_min):
        y_max = y_min + 1.0

    def x(index: int) -> float:
        return left + (plot_w * index / max(1, len(x_labels) - 1))

    def y(value: float) -> float:
        return top + plot_h * (y_max - value) / (y_max - y_min)

    chart_id = "chart-" + "".join(
        character for character in title.casefold() if character.isalnum()
    )
    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-labelledby="{chart_id}-title">',
        f'<title id="{chart_id}-title">{html.escape(title)}</title>',
        f'<text x="{left}" y="24" class="chart-title">{html.escape(title)}</text>',
    ]
    for tick in range(5):
        value = y_min + (y_max - y_min) * tick / 4
        py = y(value)
        parts.extend(
            (
                f'<line x1="{left}" x2="{width-right}" y1="{py:.1f}" '
                f'y2="{py:.1f}" class="grid"/>',
                f'<text x="{left-10}" y="{py+4:.1f}" text-anchor="end" '
                f'class="tick">{html.escape(_format(value, 1))}</text>',
            )
        )
    label_step = max(1, math.ceil(len(x_labels) / 10))
    for index, label in enumerate(x_labels):
        if index % label_step and index != len(x_labels) - 1:
            continue
        px = x(index)
        parts.append(
            f'<text x="{px:.1f}" y="{height-38}" text-anchor="middle" '
            f'class="tick">{html.escape(label)}</text>'
        )
    parts.append(
        f'<text transform="translate(18 {top + plot_h / 2:.1f}) rotate(-90)" '
        f'text-anchor="middle" class="axis-label">{html.escape(y_label)}</text>'
    )
    for series_index, (name, items) in enumerate(series):
        color = COLORS[series_index % len(COLORS)]
        points = [
            f"{x(index):.1f},{y(float(value)):.1f}"
            for index, value in enumerate(items)
            if value is not None
        ]
        if points:
            parts.append(
                f'<polyline points="{" ".join(points)}" fill="none" '
                f'stroke="{color}" stroke-width="3"/>'
            )
        for index, value in enumerate(items):
            if value is None:
                continue
            parts.append(
                f'<circle cx="{x(index):.1f}" cy="{y(float(value)):.1f}" r="4" '
                f'fill="{color}"><title>{html.escape(name)}: '
                f"{html.escape(_format(float(value), 2))}</title></circle>"
            )
        legend_x = left + series_index * 185
        parts.extend(
            (
                f'<line x1="{legend_x}" x2="{legend_x+24}" y1="{height-14}" '
                f'y2="{height-14}" stroke="{color}" stroke-width="4"/>',
                f'<text x="{legend_x+31}" y="{height-10}" class="tick">'
                f"{html.escape(name)}</text>",
            )
        )
    parts.append("</svg>")
    return "".join(parts)


def _svg_horizontal_bars(
    title: str,
    rows: Sequence[tuple[str, float]],
    *,
    x_label: str,
    width: int = 820,
) -> str:
    height = max(240, 92 + len(rows) * 44)
    left, right, top, bottom = 190, 30, 46, 44
    plot_w = width - left - right
    minimum = min(0.0, min((value for _, value in rows), default=0.0))
    maximum = max(0.0, max((value for _, value in rows), default=1.0))
    span = maximum - minimum or 1.0
    zero_x = left + plot_w * (0 - minimum) / span
    chart_id = "chart-" + "".join(
        character for character in title.casefold() if character.isalnum()
    )
    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-labelledby="{chart_id}-title">',
        f'<title id="{chart_id}-title">{html.escape(title)}</title>',
        f'<text x="{left}" y="25" class="chart-title">{html.escape(title)}</text>',
        f'<line x1="{zero_x:.1f}" x2="{zero_x:.1f}" y1="{top-8}" '
        f'y2="{height-bottom}" stroke="#7a8c89" stroke-width="1"/>',
    ]
    for index, (label, value) in enumerate(rows):
        y = top + index * 44
        value_x = left + plot_w * (value - minimum) / span
        bar_x = min(zero_x, value_x)
        bar = abs(value_x - zero_x)
        if value >= 0 and value_x > width - right - 52:
            label_x = value_x - 7
            anchor = "end"
        else:
            label_x = value_x + 7
            anchor = "start"
        parts.extend(
            (
                f'<text x="{left-12}" y="{y+20}" text-anchor="end" class="tick">'
                f"{html.escape(label)}</text>",
                f'<rect x="{bar_x:.1f}" y="{y}" width="{bar:.1f}" height="27" rx="4" '
                f'fill="{COLORS[index % len(COLORS)]}"/>',
                f'<text x="{label_x:.1f}" y="{y+19}" text-anchor="{anchor}" '
                f'class="bar-label">{html.escape(_format(value, 2))}</text>',
            )
        )
    parts.append(
        f'<text x="{left + plot_w/2:.1f}" y="{height-10}" text-anchor="middle" '
        f'class="axis-label">{html.escape(x_label)}</text></svg>'
    )
    return "".join(parts)


@dataclass(frozen=True)
class ReportInputs:
    synthetic: tuple[Path, ...]
    store_map_batch: tuple[Path, ...]
    spring: Path | None
    storage: tuple[Path, ...]
    profile_matrices: tuple[Path, ...] = ()
    writer_scaling: tuple[Path, ...] = ()


def _collect_synthetic(paths: Sequence[Path]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for path in paths:
        report = _read(path)
        if not report.get("schema", "").startswith(
            "ras-commander.native-tiff-synthetic-benchmark/"
        ):
            raise ValueError(f"Not a synthetic TIFF benchmark: {path}")
        for run in report["runs"]:
            settings = run.get("settings", {})
            if not run["id"].startswith("patched_serial_"):
                continue
            if int(settings.get("RASCOMMANDER_TIFF_PIPELINE_WORKERS", 0)) < 1:
                continue
            grouped.setdefault(
                int(settings["RASCOMMANDER_TIFF_BATCH_BYTES"]), []
            ).append(run)
    rows = []
    for batch_bytes, runs in sorted(grouped.items()):
        wall = [float(run["execution"]["wall_seconds"]) for run in runs]
        rows.append(
            {
                "batch_bytes": batch_bytes,
                "batch_label": _batch_label(batch_bytes),
                "samples": len(runs),
                "wall_median_seconds": statistics.median(wall),
                "wall_min_seconds": min(wall),
                "wall_max_seconds": max(wall),
                "wall_stdev_seconds": statistics.stdev(wall) if len(wall) > 1 else 0,
                "peak_rss_median_mib": _median(
                    run["execution"].get("peak_rss_bytes", 0) / MIB for run in runs
                ),
                "effective_cpus_median": _median(
                    run["execution"].get("effective_logical_cpus") for run in runs
                ),
                "process_write_operations_median": _median(
                    run["execution"].get("process_io", {}).get("write_operations")
                    for run in runs
                ),
                "process_mean_write_kib_median": (
                    _median(
                        run["execution"].get("process_io", {}).get("mean_write_bytes")
                        for run in runs
                    )
                    or 0
                )
                / 1024,
                "all_equivalent": all(
                    run.get("equivalence", {}).get("equivalent") is True for run in runs
                ),
            }
        )
    return rows


def _collect_store_map_batch(paths: Sequence[Path]) -> list[dict[str, Any]]:
    grouped: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for path in paths:
        report = _read(path)
        if not report.get("schema", "").startswith(
            "ras-commander.native-tiff-store-map-benchmark/"
        ):
            raise ValueError(f"Not a StoreMap TIFF benchmark: {path}")
        original = next(run for run in report["runs"] if run["id"] == "original")
        for patched in report["runs"]:
            if not patched["id"].startswith("patched_serial_"):
                continue
            settings = patched.get("settings", {})
            if int(settings.get("RASCOMMANDER_TIFF_PIPELINE_WORKERS", 0)) < 1:
                continue
            grouped.setdefault(
                int(settings["RASCOMMANDER_TIFF_BATCH_BYTES"]), []
            ).append((original, patched))
    rows = []
    for batch_bytes, pairs in sorted(grouped.items()):
        speedups = []
        for original, patched in pairs:
            original_seconds = float(original["execution"]["wall_seconds"])
            patched_seconds = float(patched["execution"]["wall_seconds"])
            speedups.append(
                100 * (original_seconds - patched_seconds) / original_seconds
            )
        rows.append(
            {
                "batch_bytes": batch_bytes,
                "batch_label": _batch_label(batch_bytes),
                "pairs": len(pairs),
                "paired_speedup_median_percent": statistics.median(speedups),
                "paired_speedup_min_percent": min(speedups),
                "paired_speedup_max_percent": max(speedups),
                "patched_wall_median_seconds": _median(
                    pair[1]["execution"]["wall_seconds"] for pair in pairs
                ),
                "peak_private_median_mib": _median(
                    pair[1]["execution"].get("peak_private_bytes", 0) / MIB
                    for pair in pairs
                ),
                "process_write_iops_median": _median(
                    pair[1]["execution"].get("process_io", {}).get("write_iops")
                    for pair in pairs
                ),
                "tiff_write_calls_median": _median(
                    (pair[1].get("tiff_io") or {}).get("underlying_write_calls")
                    for pair in pairs
                ),
                "all_equivalent": all(
                    pair[1].get("equivalence", {}).get("equivalent") is True
                    and pair[1].get("result_hdf_preserved") is True
                    for pair in pairs
                ),
            }
        )
    return rows


def _collect_spring(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    report = _read(path)
    original = next(run for run in report["runs"] if run["id"] == "original")
    candidates = [
        run
        for run in report["runs"]
        if int(run.get("settings", {}).get("RASCOMMANDER_TIFF_PIPELINE_WORKERS", 0)) > 1
    ]
    patched = min(candidates, key=lambda run: run["execution"]["wall_seconds"])
    original_seconds = float(original["execution"]["wall_seconds"])
    patched_seconds = float(patched["execution"]["wall_seconds"])
    phases = []
    for name, metrics in original.get("phase_profile", {}).items():
        phases.append(
            {
                "name": name,
                "elapsed_seconds": metrics.get("elapsed_seconds", 0),
                "effective_cpus": metrics.get("average_tree_cpu_percent", 0) / 100,
                "read_mib_s": metrics.get("average_read_mib_per_second", 0),
                "write_mib_s": metrics.get("average_write_mib_per_second", 0),
                "read_iops": metrics.get("average_read_iops", 0),
                "write_iops": metrics.get("average_write_iops", 0),
                "peak_private_mib": metrics.get("peak_tree_private_mb"),
            }
        )
    samples = original.get("resource_samples", [])
    if len(samples) > 240:
        step = math.ceil(len(samples) / 240)
        samples = samples[::step]
    return {
        "source": str(path),
        "original_seconds": original_seconds,
        "patched_id": patched["id"],
        "patched_seconds": patched_seconds,
        "speedup_percent": 100
        * (original_seconds - patched_seconds)
        / original_seconds,
        "original_effective_cpus": original["execution"].get("effective_logical_cpus"),
        "patched_effective_cpus": patched["execution"].get("effective_logical_cpus"),
        "original_peak_private_mib": original["execution"].get("peak_private_bytes", 0)
        / MIB,
        "patched_peak_private_mib": patched["execution"].get("peak_private_bytes", 0)
        / MIB,
        "all_equivalent": report.get("all_semantically_equivalent") is True,
        "phases": phases,
        "samples": samples,
    }


def _collect_storage(paths: Sequence[Path]) -> list[dict[str, Any]]:
    reports = []
    for path in paths:
        report = _read(path)
        if report.get("schema") != "ras-commander.storage-io-benchmark/1":
            raise ValueError(f"Not a storage benchmark: {path}")
        reports.append(
            {
                "label": report["label"],
                "source": str(path),
                "results": report["results"],
                "buffering": report.get("buffering"),
                "flush_semantics": report.get("flush_semantics"),
            }
        )
    return reports


def _collect_writer_scaling(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """Aggregate isolated copied-writer worker sweeps."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        report = _read(path)
        if not report.get("schema", "").startswith(
            "ras-commander.native-tiff-synthetic-benchmark/"
        ):
            raise ValueError(f"Not a synthetic TIFF benchmark: {path}")
        for run in report["runs"]:
            if run["id"] == "original":
                grouped.setdefault("installed", []).append(run)
                continue
            settings = run.get("settings", {})
            workers = settings.get("RASCOMMANDER_TIFF_PIPELINE_WORKERS")
            if not run["id"].startswith("patched_serial_") or workers is None:
                continue
            worker_count = int(workers)
            if worker_count < 1:
                continue
            grouped.setdefault(str(worker_count), []).append(run)

    if not grouped or "installed" not in grouped:
        return []
    baseline_seconds = _median(
        run["execution"]["wall_seconds"] for run in grouped["installed"]
    )
    if baseline_seconds is None:
        return []
    rows = []
    ordered = [
        "installed",
        *sorted((key for key in grouped if key != "installed"), key=int),
    ]
    for key in ordered:
        runs = grouped[key]
        wall_seconds = _median(run["execution"]["wall_seconds"] for run in runs)
        if wall_seconds is None:
            continue
        rows.append(
            {
                "workers": 0 if key == "installed" else int(key),
                "label": "Installed writer" if key == "installed" else f"{key} workers",
                "samples": len(runs),
                "wall_median_seconds": wall_seconds,
                "speedup_percent": 100
                * (baseline_seconds - wall_seconds)
                / baseline_seconds,
                "speedup_factor": baseline_seconds / wall_seconds,
                "effective_cpus_median": _median(
                    run["execution"].get("effective_logical_cpus") for run in runs
                ),
                "peak_rss_median_mib": _median(
                    run["execution"].get("peak_rss_bytes", 0) / MIB for run in runs
                ),
                "all_equivalent": all(
                    run["id"] == "original"
                    or run.get("equivalence", {}).get("equivalent") is True
                    for run in runs
                ),
            }
        )
    return rows


def _collect_profile_parallelism(paths: Sequence[Path]) -> dict[str, Any]:
    """Derive like-for-like parallelism comparisons from profile matrices."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        report = _read(path)
        if report.get("schema") != "ras-commander.raster-profile-matrix-summary/1":
            raise ValueError(f"Not a raster profile matrix: {path}")
        for run in report["runs"]:
            if run.get("status") == "complete":
                grouped.setdefault(run["run_id"], []).append(run)

    def summarize(run_id: str) -> dict[str, Any] | None:
        runs = grouped.get(run_id)
        if not runs:
            return None
        return {
            "elapsed_seconds": _median(run.get("elapsed_seconds") for run in runs),
            "peak_private_mib": _median(
                run.get("peak_tree_private_bytes", 0) / MIB for run in runs
            ),
            "effective_cpus": _median(
                (
                    run.get("cpu_seconds", 0) / run["elapsed_seconds"]
                    if run.get("elapsed_seconds")
                    else None
                )
                for run in runs
            ),
            "maximum_helpers": _median(run.get("maximum_helpers") for run in runs),
            "minimum_available_mib": _median(
                run.get("minimum_available_memory_bytes", 0) / MIB for run in runs
            ),
            "samples": len(runs),
        }

    definitions = (
        (
            "Three map products",
            "Local",
            "store_all3_serial_local",
            "store_all3_auto_local",
            "Independent map processes",
        ),
        (
            "Three map products",
            "SMB",
            "store_all3_serial_network",
            "store_all3_auto_network",
            "Independent map processes",
        ),
        (
            "Three map products (2 workers)",
            "Local",
            "store_all3_serial_local",
            "store_all3_workers2_local",
            "Two independent map processes",
        ),
        (
            "Three map products (2 workers)",
            "SMB",
            "store_all3_serial_network",
            "store_all3_workers2_network",
            "Two independent map processes",
        ),
        (
            "VRT plus overviews",
            "Local",
            "vrt_lzw_threads1_overviews_local",
            "vrt_lzw_allcpus_overviews_local",
            "GDAL translate threads",
        ),
        (
            "VRT plus overviews",
            "SMB",
            "vrt_lzw_threads1_overviews_network",
            "vrt_lzw_allcpus_overviews_network",
            "GDAL translate threads",
        ),
        (
            "Terrain HDF",
            "Local",
            "terrain_hdf_threads1_local",
            "terrain_hdf_allcpus_local",
            "GDAL thread setting",
        ),
        (
            "Terrain HDF",
            "SMB",
            "terrain_hdf_threads1_network",
            "terrain_hdf_allcpus_network",
            "GDAL thread setting",
        ),
    )
    comparisons = []
    for workload, storage, baseline_id, parallel_id, mechanism in definitions:
        baseline = summarize(baseline_id)
        parallel = summarize(parallel_id)
        if not baseline or not parallel:
            continue
        baseline_seconds = baseline["elapsed_seconds"]
        parallel_seconds = parallel["elapsed_seconds"]
        if baseline_seconds is None or parallel_seconds is None:
            continue
        comparisons.append(
            {
                "workload": workload,
                "storage": storage,
                "mechanism": mechanism,
                "baseline_seconds": baseline_seconds,
                "parallel_seconds": parallel_seconds,
                "seconds_saved": baseline_seconds - parallel_seconds,
                "speedup_percent": 100
                * (baseline_seconds - parallel_seconds)
                / baseline_seconds,
                "speedup_factor": baseline_seconds / parallel_seconds,
                "baseline_peak_private_mib": baseline["peak_private_mib"],
                "parallel_peak_private_mib": parallel["peak_private_mib"],
                "baseline_effective_cpus": baseline["effective_cpus"],
                "parallel_effective_cpus": parallel["effective_cpus"],
                "parallel_helpers": parallel["maximum_helpers"],
                "baseline_samples": baseline["samples"],
                "parallel_samples": parallel["samples"],
            }
        )

    spring_runs = []
    for storage, run_id in (
        ("Local", "spring_all3_auto_local"),
        ("SMB", "spring_all3_auto_network"),
    ):
        summary = summarize(run_id)
        if summary:
            spring_runs.append({"storage": storage, **summary})
    return {"comparisons": comparisons, "spring_auto_runs": spring_runs}


def normalize(inputs: ReportInputs) -> dict[str, Any]:
    return {
        "schema": "ras-commander.raster-performance-decision-report/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_batch": _collect_synthetic(inputs.synthetic),
        "store_map_batch": _collect_store_map_batch(inputs.store_map_batch),
        "spring_river": _collect_spring(inputs.spring),
        "storage": _collect_storage(inputs.storage),
        "parallelism": _collect_profile_parallelism(inputs.profile_matrices),
        "writer_scaling": _collect_writer_scaling(inputs.writer_scaling),
        "sources": [
            str(path)
            for path in (
                *inputs.synthetic,
                *inputs.store_map_batch,
                *((inputs.spring,) if inputs.spring else ()),
                *inputs.storage,
                *inputs.profile_matrices,
                *inputs.writer_scaling,
            )
        ],
    }


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    heading = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{item}</td>" for item in row) + "</tr>" for row in rows
    )
    return f"<div class='table-scroll'><table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table></div>"


def _source_link(source: str, output: Path) -> str:
    path = Path(source).resolve()
    try:
        target = path.relative_to(output.parent.resolve()).as_posix()
    except ValueError:
        target = path.as_uri()
    return f'<a href="{html.escape(target, quote=True)}">{html.escape(path.name)}</a>'


def render_html(data: dict[str, Any], output: Path) -> str:
    synthetic = data["synthetic_batch"]
    real = data["store_map_batch"]
    spring = data["spring_river"]
    storage = data["storage"]
    parallelism = data.get("parallelism", {})
    comparisons = parallelism.get("comparisons", [])
    writer_scaling = data.get("writer_scaling", [])
    best = min(synthetic, key=lambda row: row["wall_median_seconds"])
    above = [row for row in synthetic if row["batch_bytes"] > best["batch_bytes"]]
    largest = max(synthetic, key=lambda row: row["batch_bytes"])
    larger_penalty = (
        100
        * (
            min(row["wall_median_seconds"] for row in above)
            - best["wall_median_seconds"]
        )
        / best["wall_median_seconds"]
        if above
        else 0
    )
    largest_memory_delta = (largest["peak_rss_median_mib"] or 0) - (
        best["peak_rss_median_mib"] or 0
    )
    all_equivalent = all(row["all_equivalent"] for row in (*synthetic, *real))
    if spring:
        all_equivalent = all_equivalent and spring["all_equivalent"]
    if writer_scaling:
        all_equivalent = all_equivalent and all(
            row["all_equivalent"] for row in writer_scaling
        )

    comparison_lookup = {(row["workload"], row["storage"]): row for row in comparisons}
    map_local = comparison_lookup.get(("Three map products", "Local"))
    map_smb = comparison_lookup.get(("Three map products", "SMB"))
    map_two_local = comparison_lookup.get(("Three map products (2 workers)", "Local"))
    map_two_smb = comparison_lookup.get(("Three map products (2 workers)", "SMB"))
    writer_eight = next((row for row in writer_scaling if row["workers"] == 8), None)

    scaling_rows = [
        (
            f"{row['workload']} · {row['storage']}",
            row["speedup_percent"],
        )
        for row in comparisons
    ]
    if writer_eight:
        scaling_rows.append(
            ("Isolated TIFF writer · 8 workers", writer_eight["speedup_percent"])
        )
    if spring:
        scaling_rows.append(
            ("Spring one-map pipeline · 8 workers", spring["speedup_percent"])
        )
    parallel_chart = (
        _svg_horizontal_bars(
            "Observed benefit from additional parallelism",
            scaling_rows,
            x_label="elapsed-time reduction percent; higher is better",
        )
        if scaling_rows
        else ""
    )

    batch_chart = _svg_line_chart(
        "Encoded TIFF batching: latency",
        [row["batch_label"] for row in synthetic],
        [("Median wall seconds", [row["wall_median_seconds"] for row in synthetic])],
        y_label="seconds (lower is better)",
    )
    batch_memory_chart = _svg_line_chart(
        "Encoded TIFF batching: memory and write operations",
        [row["batch_label"] for row in synthetic],
        (
            ("Peak RSS MiB", [row["peak_rss_median_mib"] for row in synthetic]),
            (
                "Process writes",
                [row["process_write_operations_median"] for row in synthetic],
            ),
        ),
        y_label="MiB or operations",
    )
    real_chart = _svg_horizontal_bars(
        "Paired real StoreMap speedup",
        [(row["batch_label"], row["paired_speedup_median_percent"]) for row in real],
        x_label="paired speedup percent; negative is slower",
    )
    charts = [parallel_chart, batch_chart, batch_memory_chart, real_chart]

    spring_section = ""
    if spring:
        phase_rows = sorted(
            spring["phases"], key=lambda item: item["elapsed_seconds"], reverse=True
        )
        phase_chart = _svg_horizontal_bars(
            "Spring River stage duration",
            [(row["name"], row["elapsed_seconds"]) for row in phase_rows],
            x_label="seconds",
        )
        charts.append(phase_chart)
        samples = spring["samples"]
        if samples:
            timeline = _svg_line_chart(
                "Spring River resource timeline",
                [f"{sample.get('elapsed_seconds', 0):.0f}s" for sample in samples],
                (
                    (
                        "Effective CPUs",
                        [sample.get("tree_cpu_percent", 0) / 100 for sample in samples],
                    ),
                    (
                        "Private GiB",
                        [sample.get("tree_private_mb", 0) / 1024 for sample in samples],
                    ),
                    (
                        "Write MiB/s",
                        [sample.get("write_mib_per_second", 0) for sample in samples],
                    ),
                ),
                y_label="CPUs, GiB, or MiB/s",
            )
            charts.append(timeline)
        phase_table = _table(
            (
                "Inferred stage",
                "Time (s)",
                "Effective CPUs",
                "Read MiB/s",
                "Write MiB/s",
                "Write IOPS",
                "Peak private MiB",
            ),
            [
                (
                    html.escape(row["name"]),
                    _format(row["elapsed_seconds"], 2),
                    _format(row["effective_cpus"], 2),
                    _format(row["read_mib_s"], 2),
                    _format(row["write_mib_s"], 2),
                    _format(row["write_iops"], 1),
                    _format(row["peak_private_mib"], 0),
                )
                for row in phase_rows
            ],
        )
        peak_worker_gib = (
            max(spring["original_peak_private_mib"], spring["patched_peak_private_mib"])
            / 1024
        )
        reserve_gib = 8.0
        memory_rows = [
            (
                str(workers),
                _format(workers * peak_worker_gib, 1),
                _format(reserve_gib + workers * peak_worker_gib, 1),
            )
            for workers in (1, 2, 3)
        ]
        spring_auto_rows = [
            (
                row["storage"],
                _format(row["elapsed_seconds"], 1),
                _format(row["maximum_helpers"], 0),
                _format((row["peak_private_mib"] or 0) / 1024, 1),
                _format((row["minimum_available_mib"] or 0) / 1024, 1),
            )
            for row in parallelism.get("spring_auto_runs", [])
        ]
        spring_projection_rows = []
        for row in parallelism.get("spring_auto_runs", []):
            factor_rows = (
                (2, map_two_local, reserve_gib + 2 * peak_worker_gib),
                (3, map_local, reserve_gib + 3 * peak_worker_gib),
            )
            if row["storage"] == "SMB":
                factor_rows = (
                    (2, map_two_smb, reserve_gib + 2 * peak_worker_gib),
                    (3, map_smb, reserve_gib + 3 * peak_worker_gib),
                )
            for workers, factor_row, memory_budget in factor_rows:
                if not factor_row or row["elapsed_seconds"] is None:
                    continue
                projected_seconds = (
                    row["elapsed_seconds"] / factor_row["speedup_factor"]
                )
                spring_projection_rows.append(
                    (
                        row["storage"],
                        str(workers),
                        _format(factor_row["speedup_factor"], 2),
                        _format(row["elapsed_seconds"], 1),
                        _format(projected_seconds, 1),
                        _format(row["elapsed_seconds"] - projected_seconds, 1),
                        _format(memory_budget, 1),
                    )
                )
        spring_section = f"""
        <section id="spring"><h2>Large-watershed reality check: Spring River</h2>
        <div class="callout"><strong>{spring['speedup_percent']:.1f}% end-to-end speedup</strong>
        for the best tested copied writer ({html.escape(spring['patched_id'])}):
        {spring['original_seconds']:.1f}s to {spring['patched_seconds']:.1f}s. Peak private memory
        was {spring['original_peak_private_mib']/1024:.1f} to {spring['patched_peak_private_mib']/1024:.1f} GiB.</div>
        {phase_chart}
        {timeline if samples else ''}
        {phase_table}
        <h3>Memory gate for map-level parallelism</h3>
        <p>Extra RAM can admit multiple independent map helpers; it does not make one Spring map scale across
        those helpers. Using the observed {peak_worker_gib:.1f} GiB peak as a conservative per-helper planning
        value and retaining an 8 GiB reserve gives this admission budget:</p>
        {_table(('Concurrent map helpers','Helper private GiB','Available-memory budget GiB'), memory_rows)}
        {(_table(('Observed auto run','Elapsed s','Maximum helpers','Peak private GiB','Minimum free GiB'), spring_auto_rows) if spring_auto_rows else '')}
        {('<h3>Spring three-product planning scenarios</h3>' + _table(('Target','Helpers','Transferred factor','Observed serial s','Scenario s','Potential seconds saved','Memory budget GiB'), spring_projection_rows) if spring_projection_rows else '')}
        <p class="note">Scenario times transfer the measured Bald Eagle two- or three-helper factor to the
        observed Spring three-product serial run. They show the size of the opportunity to test on a high-memory
        machine; they are not measured Spring parallel results or a performance guarantee.</p>
        <p class="note">The admission budget is a planning estimate, not a benchmarked Spring scaling claim.
        Shared state and product-specific memory can change the actual requirement. Profile one product first,
        then set the reserve and per-worker estimate from that result.</p>
        <p class="note">CPU is normalized as 1.0 per fully occupied logical core. Process I/O counters include cached I/O;
        host-disk counters are machine-wide. Stage labels are inferred from child processes and output growth.</p>
        </section>"""

    storage_section = ""
    if storage:
        blocks = sorted(
            {item["block_bytes"] for report in storage for item in report["results"]}
        )
        lookup = {
            report["label"]: {
                item["block_bytes"]: item["write_mib_per_second"]
                for item in report["results"]
            }
            for report in storage
        }
        storage_chart = _svg_line_chart(
            "Storage request size throughput",
            [_batch_label(block) for block in blocks],
            [
                (label, [values.get(block) for block in blocks])
                for label, values in lookup.items()
            ],
            y_label="write MiB/s",
        )
        charts.append(storage_chart)
        storage_section = f"""
        <section id="storage"><h2>Storage profiling</h2>{storage_chart}
        <div class="callout"><strong>Do test larger raw writes on SMB.</strong> Raw sequential throughput can keep
        improving through 8 MiB even when TIFF wall time does not, because TIFF metadata seeks cap the effective
        contiguous commit. Storage results use the Windows filesystem cache and one final fsync.</div></section>"""

    synthetic_rows = [
        (
            row["batch_label"],
            str(row["samples"]),
            _format(row["wall_median_seconds"], 3),
            f"{_format(row['wall_min_seconds'], 3)}–{_format(row['wall_max_seconds'], 3)}",
            _format(row["effective_cpus_median"], 2),
            _format(row["peak_rss_median_mib"], 1),
            _format(row["process_write_operations_median"], 0),
            _format(row["process_mean_write_kib_median"], 1),
            "yes" if row["all_equivalent"] else "NO",
        )
        for row in synthetic
    ]
    real_rows = [
        (
            row["batch_label"],
            str(row["pairs"]),
            _format(row["paired_speedup_median_percent"], 1),
            f"{_format(row['paired_speedup_min_percent'], 1)}–{_format(row['paired_speedup_max_percent'], 1)}",
            _format(row["patched_wall_median_seconds"], 3),
            _format(row["tiff_write_calls_median"], 0),
            _format(row["peak_private_median_mib"], 0),
            "yes" if row["all_equivalent"] else "NO",
        )
        for row in real
    ]
    parallel_rows = [
        (
            row["workload"],
            row["storage"],
            html.escape(row["mechanism"]),
            f"{_format(row['baseline_seconds'], 3)} → {_format(row['parallel_seconds'], 3)}",
            _format(row["seconds_saved"], 3),
            _format(row["speedup_percent"], 1),
            _format(row["speedup_factor"], 2),
            f"{_format(row['baseline_peak_private_mib'], 0)} → {_format(row['parallel_peak_private_mib'], 0)}",
        )
        for row in comparisons
    ]
    writer_rows = [
        (
            row["label"],
            str(row["samples"]),
            _format(row["wall_median_seconds"], 3),
            _format(row["speedup_percent"], 1),
            _format(row["speedup_factor"], 2),
            _format(row["effective_cpus_median"], 2),
            _format(row["peak_rss_median_mib"], 1),
        )
        for row in writer_scaling
    ]
    source_links = " · ".join(
        _source_link(source, output) for source in data["sources"]
    )
    report_data_link = html.escape(output.with_suffix(".data.json").name)
    if map_local and map_smb and spring:
        verdict = (
            "Additional parallelization is worthwhile when work can be split into independent map products: "
            f"three-map elapsed time fell {map_local['speedup_percent']:.1f}% locally and "
            f"{map_smb['speedup_percent']:.1f}% on SMB. This gain is not SMB-specific. By contrast, "
            f"parallelizing the internal TIFF consumer changed the full Spring one-map pipeline by only "
            f"{spring['speedup_percent']:.1f}%. SMB is primarily more sensitive to write-request size, not "
            "uniquely more responsive to CPU parallelism."
        )
        decision_cards = f"""<div class="cards">
        <div class="card"><strong>{map_local['speedup_percent']:.1f}% faster</strong>three products, local</div>
        <div class="card"><strong>{map_smb['speedup_percent']:.1f}% faster</strong>three products, SMB</div>
        <div class="card"><strong>{spring['speedup_percent']:.1f}% faster</strong>one large Spring map, TIFF workers</div>
        <div class="card"><strong>{_batch_label(best['batch_bytes'])}</strong>best isolated TIFF batch</div></div>"""
    else:
        verdict = (
            f"Use {_batch_label(best['batch_bytes'])} as the current tuning candidate, retain the full "
            "64 KiB–64 MiB range for machine-specific profiling, and do not assume larger is faster. "
            f"The fastest larger setting was {larger_penalty:.1f}% slower while "
            f"the 64 MiB request added {largest_memory_delta:.1f} MiB of writer RSS."
        )
        decision_cards = f"""<div class="cards"><div class="card"><strong>{html.escape(best['batch_label'])}</strong>fastest isolated median</div>
        <div class="card"><strong>{best['wall_median_seconds']:.3f}s</strong>writer median, n={best['samples']}</div>
        <div class="card"><strong>{best['effective_cpus_median']:.2f} cores</strong>effective copied-writer CPU</div>
        <div class="card"><strong>{best['peak_rss_median_mib']:.1f} MiB</strong>copied-writer peak RSS</div></div>"""
    parallel_section = ""
    if parallel_rows or writer_rows:
        parallel_section = f"""<section id="parallelism"><h2>Can additional parallelism produce meaningful speedup?</h2>
        <div class="callout"><strong>Yes at map and GDAL-translate boundaries; no evidence yet for one
        producer-paced large StoreMap.</strong> Local versus SMB changes absolute runtime, but the controlled
        three-product parallel speedup was essentially the same on both targets.</div>
        {parallel_chart}
        {(_table(('Workload','Target','Parallel boundary','Serial → parallel s','Seconds saved','Faster %','Factor','Peak private MiB'), parallel_rows) if parallel_rows else '')}
        <p class="note">These are like-for-like observed comparisons, not projections. The three-map cases
        launch independent WSE, Depth, and Velocity helpers. The VRT cases thread GDAL translation, while the
        later overview stage remains mostly single-core. Terrain HDF did not respond materially to the thread setting.</p>
        {('<h3>Why the internal writer result is not the application result</h3>' + _table(('Writer case','n','Median s','Faster vs installed %','Factor','Effective CPUs','Peak RSS MiB'), writer_rows) if writer_rows else '')}
        <p class="note">The isolated TIFF writer has all tiles ready and therefore exposes Deflate parallelism.
        Spring River fed tiles over roughly 84 seconds, so those workers usually waited for upstream terrain/HDF/map-value production.</p>
        </section>"""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RAS raster performance decision report</title>
<style>
:root{{--ink:#152329;--muted:#52666c;--paper:#f5f7f6;--card:#fff;--teal:#0b6e69;--amber:#d97706;--line:#d5dfdc}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
header{{background:linear-gradient(125deg,#073c3a,#0b6e69);color:white;padding:42px max(24px,calc((100% - 1180px)/2)) 36px}}
header h1{{font-size:clamp(2rem,4vw,3.2rem);line-height:1.05;margin:0 0 10px}} header p{{max-width:850px;margin:0;color:#d8f4ef}}
main{{max-width:1180px;margin:auto;padding:26px 22px 70px}} section{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px;margin:20px 0;box-shadow:0 4px 16px #183b3510}}
h2{{margin-top:0;font-size:1.55rem}} h3{{margin-bottom:7px}} .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:18px 0}}
.card{{border-left:5px solid var(--teal);background:#f7fbfa;padding:15px 16px;border-radius:8px}} .card strong{{display:block;font-size:1.35rem}}
.callout{{background:#fff8e8;border-left:5px solid var(--amber);padding:16px 18px;border-radius:8px;margin:16px 0}} .status{{display:inline-block;padding:5px 10px;border-radius:20px;background:#dff5ef;color:#07534f;font-weight:700}}
.chart{{width:100%;height:auto;margin:10px 0 20px;background:#fbfcfc;border:1px solid var(--line);border-radius:10px}} .chart-title{{font-size:17px;font-weight:700;fill:var(--ink)}} .tick{{font-size:11px;fill:var(--muted)}} .axis-label{{font-size:12px;fill:var(--muted)}} .bar-label{{font-size:12px;font-weight:700;fill:var(--ink)}} .grid{{stroke:#dce6e3;stroke-width:1}}
.table-scroll{{overflow-x:auto}} table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}} th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}} th:first-child,td:first-child{{text-align:left}} th{{background:#eef4f2;font-size:.86rem}} .note{{color:var(--muted);font-size:.9rem}} code{{background:#edf2f1;padding:2px 5px;border-radius:4px}} a{{color:#075f5a}}
@media print{{body{{background:white}} section{{break-inside:avoid;box-shadow:none}} header{{padding:24px}}}}
</style></head><body>
<header><h1>RAS raster performance decision report</h1><p>Measured CPU, memory, storage, IOPS, and encoded-TIFF batching evidence. Generated {html.escape(data['generated_at'])}.</p></header>
<main><section id="decision"><span class="status">{'Semantic checks passed' if all_equivalent else 'Equivalence failure detected'}</span>
<h2>Actionable decision</h2><p>{html.escape(verdict)}</p>
{decision_cards}
<ol><li>Prefer map-level process parallelism when generating two or more independent products and the memory estimator admits the workers.</li>
<li>Use GDAL threads for VRT translation, but expect the overview and terrain-HDF stages to retain mostly serial limits.</li>
<li>Treat TIFF batching as an SMB/request-efficiency control, not as proof that another CPU worker will reduce full-pipeline time.</li>
<li>Keep native behavior as the safe default; enable copied-assembly experiments only for the pinned HEC-RAS build after equivalence testing.</li></ol></section>
{parallel_section}
<section id="batch"><h2>How large should encoded TIFF commits be?</h2>{batch_chart}{batch_memory_chart}
{_table(('Batch','n','Median s','Range s','Effective CPUs','Peak RSS MiB','Process writes','Mean write KiB','Equivalent'), synthetic_rows)}
<p class="note">The fastest larger setting was {larger_penalty:.1f}% slower than {_batch_label(best['batch_bytes'])};
the 64 MiB request added {largest_memory_delta:.1f} MiB of writer RSS. The encoded stream still has ordered TIFF
directory/offset updates. A requested 64 MiB batch is an upper bound, not a promise that 64 MiB of contiguous
encoded data exists before a seek forces a flush.</p></section>
<section id="real"><h2>Does it move a real StoreMap?</h2>{real_chart}
{_table(('Batch','pairs','Median speedup %','Range %','Patched median s','TIFF writes','Peak private MiB','Equivalent'), real_rows)}
<p class="note">Each speedup is paired with the original assembly in the same run directory. The small fixture remains noisy; use the range to avoid over-reading a 1–3% median.</p></section>
{spring_section}{storage_section}
<section id="evidence"><h2>Evidence and reproducibility</h2><p><a href="{report_data_link}">Normalized report data</a></p><p class="note">{source_links}</p></section>
</main></body></html>"""


def write_report(inputs: ReportInputs, output: Path) -> tuple[Path, Path]:
    data = normalize(inputs)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    data_path = output.with_suffix(".data.json")
    data_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output.write_text(render_html(data, output), encoding="utf-8")
    return output, data_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="append", type=Path, required=True)
    parser.add_argument("--store-map-batch", action="append", type=Path, required=True)
    parser.add_argument("--spring", type=Path)
    parser.add_argument("--storage", action="append", type=Path, default=[])
    parser.add_argument("--profile-matrix", action="append", type=Path, default=[])
    parser.add_argument("--writer-scaling", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    html_path, data_path = write_report(
        ReportInputs(
            synthetic=tuple(args.synthetic),
            store_map_batch=tuple(args.store_map_batch),
            spring=args.spring,
            storage=tuple(args.storage),
            profile_matrices=tuple(args.profile_matrix),
            writer_scaling=tuple(args.writer_scaling),
        ),
        args.output,
    )
    print(json.dumps({"html": str(html_path), "data": str(data_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
