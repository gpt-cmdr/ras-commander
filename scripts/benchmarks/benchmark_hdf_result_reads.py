"""Benchmark direct, bounded, and optional eager HDF result reads.

The source HDF is opened read-only. Each measurement runs in a fresh child
process so peak RSS is attributable and one eager scenario cannot retain memory
for another. The first pass is a cold-cache candidate only; this script does
not flush the operating-system file cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import h5py
import numpy as np
import psutil

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _measure_peak(operation):
    process = psutil.Process()
    stop = threading.Event()
    peak = process.memory_info().rss

    def monitor() -> None:
        nonlocal peak
        while not stop.wait(0.005):
            peak = max(peak, process.memory_info().rss)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    baseline = process.memory_info().rss
    started = time.perf_counter()
    try:
        values = np.asarray(operation())
    finally:
        elapsed = time.perf_counter() - started
        stop.set()
        thread.join()
    peak = max(peak, process.memory_info().rss)
    digest = hashlib.sha256(values.tobytes()).hexdigest()
    return {
        "elapsed_seconds": elapsed,
        "rss_baseline_bytes": baseline,
        "rss_peak_bytes": peak,
        "rss_peak_delta_bytes": max(0, peak - baseline),
        "shape": list(values.shape),
        "dtype": str(values.dtype),
        "sha256": digest,
    }


def _run_worker(args) -> int:
    from ras_commander import HdfResultsMesh

    dataset_path = HdfResultsMesh._get_mesh_timeseries_output_path(
        args.mesh_name,
        args.variable,
    )

    if args.scenario == "view_create":
        def operation():
            view = HdfResultsMesh.get_mesh_timeseries(
                args.hdf_path,
                args.mesh_name,
                args.variable,
                truncate=False,
                return_type="view",
            )
            return np.asarray(view.shape, dtype=np.int64)
    elif args.scenario == "direct_slice":
        def operation():
            return HdfResultsMesh.get_mesh_timeseries(
                args.hdf_path,
                args.mesh_name,
                args.variable,
                truncate=False,
                time_selection=args.time_index,
            ).values
    elif args.scenario == "bounded_max":
        def operation():
            view = HdfResultsMesh.get_mesh_timeseries(
                args.hdf_path,
                args.mesh_name,
                args.variable,
                truncate=False,
                return_type="view",
            )
            return view.reduce(
                "max",
                max_chunk_bytes=args.max_chunk_mib * 1024 * 1024,
            ).values
    elif args.scenario == "eager_slice":
        def operation():
            with h5py.File(args.hdf_path, "r") as hdf_file:
                return hdf_file[dataset_path][:][args.time_index]
    elif args.scenario == "eager_api_truncate":
        def operation():
            return HdfResultsMesh.get_mesh_timeseries(
                args.hdf_path,
                args.mesh_name,
                args.variable,
                truncate=True,
            ).values
    elif args.scenario == "eager_max":
        def operation():
            with h5py.File(args.hdf_path, "r") as hdf_file:
                values = np.asarray(hdf_file[dataset_path][:])
            values[~np.isfinite(values)] = np.nan
            return np.fmax.reduce(values, axis=0)
    else:  # pragma: no cover - argparse constrains the value
        raise ValueError(args.scenario)

    result = _measure_peak(operation)
    result["scenario"] = args.scenario
    print(json.dumps(result, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hdf_path", type=Path)
    parser.add_argument("mesh_name")
    parser.add_argument("variable")
    parser.add_argument("--time-index", type=int, default=0)
    parser.add_argument("--max-chunk-mib", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--include-eager", action="store_true")
    parser.add_argument("--report-path", type=Path)
    parser.add_argument(
        "--worker",
        dest="scenario",
        choices=(
            "view_create",
            "direct_slice",
            "bounded_max",
            "eager_slice",
            "eager_api_truncate",
            "eager_max",
        ),
        help=argparse.SUPPRESS,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.scenario:
        return _run_worker(args)
    if not args.hdf_path.is_file():
        raise FileNotFoundError(args.hdf_path)
    if args.repeats < 1:
        raise ValueError("repeats must be positive")
    if args.max_chunk_mib < 1:
        raise ValueError("max_chunk_mib must be positive")

    scenarios = ["view_create", "direct_slice", "bounded_max"]
    if args.include_eager:
        scenarios.extend(["eager_slice", "eager_api_truncate", "eager_max"])
    rows = []
    for scenario in scenarios:
        for repeat in range(args.repeats):
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                str(args.hdf_path.resolve()),
                args.mesh_name,
                args.variable,
                "--time-index",
                str(args.time_index),
                "--max-chunk-mib",
                str(args.max_chunk_mib),
                "--worker",
                scenario,
            ]
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
            row = json.loads(completed.stdout.strip().splitlines()[-1])
            row["repeat"] = repeat + 1
            row["cache_label"] = "cold_candidate" if repeat == 0 else "warm"
            rows.append(row)

    report = {
        "hdf_path": str(args.hdf_path.resolve()),
        "mesh_name": args.mesh_name,
        "variable": args.variable,
        "time_index": args.time_index,
        "max_chunk_mib": args.max_chunk_mib,
        "cache_note": (
            "cold_candidate does not flush the operating-system file cache"
        ),
        "measurements": rows,
    }
    payload = json.dumps(report, indent=2, sort_keys=True)
    print(payload)
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
