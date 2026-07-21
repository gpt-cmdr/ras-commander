"""Profile public RasTerrain raster functions with process-tree telemetry.

Run against disposable output paths. Inputs are read-only; every output path
must be absent or an empty directory so benchmark results cannot overwrite a
curated terrain artifact.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import os
import pstats
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import h5py
import psutil

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ras_commander import GeoTiffWriteOptions  # noqa: E402
from ras_commander.terrain import RasTerrain  # noqa: E402

from benchmark_store_maps_memory import (  # noqa: E402
    ProcessTreeMonitor,
    _raster_signature,
    _storage_metadata,
)

OPERATIONS = {
    "vrt_to_tiff",
    "create_terrain_hdf",
    "create_terrain_from_rasters",
}


def _parse_threads(raw: str) -> int | str | None:
    normalized = raw.strip().upper()
    if normalized in {"NONE", "DEFAULT", "UNSET"}:
        return None
    if normalized == "ALL_CPUS":
        return normalized
    try:
        value = int(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "threads must be a positive integer, ALL_CPUS, or none"
        ) from exc
    if value < 1:
        raise argparse.ArgumentTypeError(
            "threads must be a positive integer, ALL_CPUS, or none"
        )
    return value


def _write_options_from_args(
    args: argparse.Namespace,
    overview_levels: list[int],
) -> GeoTiffWriteOptions:
    """Build the exact GDAL child settings recorded by a VRT benchmark."""

    return GeoTiffWriteOptions(
        compression=args.compression,
        create_overviews=args.overviews,
        overview_levels=tuple(overview_levels),
        gdal_num_threads=args.threads,
        gdal_cachemax_mb=args.gdal_cachemax_mb,
    )


def _hdf_dataset_signature(path: Path) -> dict[str, Any]:
    """Hash HDF dataset values incrementally without whole-file allocation."""
    digest = hashlib.sha256()
    dataset_count = 0
    total_value_bytes = 0
    with h5py.File(path, "r") as hdf_file:
        dataset_names: list[str] = []
        hdf_file.visititems(
            lambda name, obj: (
                dataset_names.append(name) if isinstance(obj, h5py.Dataset) else None
            )
        )
        for name in sorted(dataset_names):
            dataset_count += 1
            dataset = hdf_file[name]
            digest.update(name.encode("utf-8"))
            digest.update(str(dataset.shape).encode("ascii"))
            digest.update(str(dataset.dtype).encode("ascii"))
            if dataset.shape == ():
                value = dataset[()]
                payload = (
                    value.tobytes()
                    if hasattr(value, "tobytes")
                    else repr(value).encode()
                )
                digest.update(payload)
                total_value_bytes += len(payload)
                continue
            if not dataset.shape or dataset.shape[0] == 0:
                continue
            rows = max(1, min(dataset.shape[0], 1024))
            for start in range(0, dataset.shape[0], rows):
                value = dataset[start : min(start + rows, dataset.shape[0])]
                payload = value.tobytes(order="C")
                digest.update(payload)
                total_value_bytes += len(payload)
    return {
        "dataset_count": dataset_count,
        "dataset_value_bytes": total_value_bytes,
        "dataset_sha256": digest.hexdigest(),
    }


def _prepare_output(operation: str, output: Path, terrain_name: str) -> Path:
    if operation == "create_terrain_from_rasters":
        if output.exists() and any(output.iterdir()):
            raise FileExistsError(f"Output directory is not empty: {output}")
        output.mkdir(parents=True, exist_ok=True)
        return output / f"{terrain_name}.hdf"
    if output.exists():
        raise FileExistsError(f"Output file already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=sorted(OPERATIONS), required=True)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--projection", type=Path)
    parser.add_argument("--terrain-name", default="Terrain")
    parser.add_argument("--units", choices=("Feet", "Meters"), default="Feet")
    parser.add_argument(
        "--stitch",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--generate-prj",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--compression", default="LZW")
    parser.add_argument(
        "--overviews",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--overview-levels", default="2,4,8,16,32")
    parser.add_argument("--nodata-value", type=float)
    parser.add_argument("--threads", type=_parse_threads, default="ALL_CPUS")
    parser.add_argument("--gdal-cachemax-mb", type=int, default=None)
    parser.add_argument("--hecras-version", default="7.0")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--sample-interval", type=float, default=0.1)
    parser.add_argument("--label", default=None)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--python-profile-path", type=Path, default=None)
    parser.add_argument(
        "--skip-output-signature",
        action="store_true",
        help="Skip block-streamed raster/HDF content signatures.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    inputs = [Path(os.path.abspath(path)) for path in args.input]
    for input_path in inputs:
        if not input_path.exists():
            raise FileNotFoundError(f"Input does not exist: {input_path}")
    output_argument = Path(os.path.abspath(args.output))
    expected_output = _prepare_output(
        args.operation,
        output_argument,
        args.terrain_name,
    )
    report_path = Path(os.path.abspath(args.report_path))
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if args.gdal_cachemax_mb is not None and args.gdal_cachemax_mb < 1:
        raise ValueError("gdal-cachemax-mb must be positive")
    if args.gdal_cachemax_mb is not None and args.operation != "vrt_to_tiff":
        raise ValueError(
            "gdal-cachemax-mb is supported only for vrt_to_tiff; the terrain "
            "creation APIs do not expose a child GDAL cache setting"
        )
    if args.timeout < 1:
        raise ValueError("timeout must be positive")
    overview_levels = [
        int(value.strip()) for value in args.overview_levels.split(",") if value.strip()
    ]

    watch_folder = (
        output_argument
        if args.operation == "create_terrain_from_rasters"
        else output_argument.parent
    )
    monitor = ProcessTreeMonitor(
        args.sample_interval,
        watch_paths=[watch_folder],
    )
    profiler = cProfile.Profile() if args.python_profile_path else None
    status = "running"
    error: dict[str, str] | None = None
    result_path: Path | None = None
    started = time.perf_counter()
    monitor.start()
    if profiler is not None:
        profiler.enable()
    try:
        if args.operation == "vrt_to_tiff":
            if len(inputs) != 1:
                raise ValueError("vrt_to_tiff requires exactly one --input")
            result_path = RasTerrain.vrt_to_tiff(
                vrt_path=inputs[0],
                output_path=output_argument,
                nodata_value=args.nodata_value,
                hecras_version=args.hecras_version,
                write_options=_write_options_from_args(args, overview_levels),
            )
        elif args.operation == "create_terrain_hdf":
            if args.projection is None:
                raise ValueError("create_terrain_hdf requires --projection")
            result_path = RasTerrain.create_terrain_hdf(
                input_rasters=inputs,
                output_hdf=output_argument,
                projection_prj=Path(os.path.abspath(args.projection)),
                units=args.units,
                stitch=args.stitch,
                hecras_version=args.hecras_version,
                timeout_seconds=args.timeout,
                gdal_num_threads=args.threads,
            )
        else:
            result_path = RasTerrain.create_terrain_from_rasters(
                input_rasters=inputs,
                output_folder=output_argument,
                terrain_name=args.terrain_name,
                units=args.units,
                stitch=args.stitch,
                hecras_version=args.hecras_version,
                generate_prj=args.generate_prj,
                gdal_num_threads=args.threads,
            )
        status = "complete"
    except Exception as exc:  # pragma: no cover - native integration path
        status = "failed"
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        if profiler is not None:
            profiler.disable()
        monitor.stop()
    elapsed_seconds = time.perf_counter() - started

    python_profile = None
    if profiler is not None:
        profile_path = Path(os.path.abspath(args.python_profile_path))
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(profile_path)
        profile_stream = io.StringIO()
        pstats.Stats(profiler, stream=profile_stream).sort_stats(
            "cumulative"
        ).print_stats(50)
        python_profile = {
            "path": str(profile_path),
            "top_cumulative": profile_stream.getvalue(),
        }

    output_signature = None
    if (
        status == "complete"
        and result_path is not None
        and not args.skip_output_signature
    ):
        if result_path.suffix.casefold() == ".hdf":
            output_signature = _hdf_dataset_signature(result_path)
        else:
            output_signature = _raster_signature(result_path)

    report = {
        "schema": "ras-commander.raster-function-benchmark/1",
        "status": status,
        "error": error,
        "configuration": {
            "label": args.label,
            "function": f"RasTerrain.{args.operation}",
            "inputs": [str(path) for path in inputs],
            "output_argument": str(output_argument),
            "expected_output": str(expected_output),
            "projection": (
                str(Path(os.path.abspath(args.projection)))
                if args.projection is not None
                else None
            ),
            "threads": args.threads,
            "gdal_cachemax_mb": args.gdal_cachemax_mb,
            "compression": args.compression,
            "overviews": args.overviews,
            "overview_levels": overview_levels,
            "stitch": args.stitch,
            "generate_prj": args.generate_prj,
            "hecras_version": args.hecras_version,
            "logical_cpu_count": os.cpu_count(),
            "total_memory_bytes": psutil.virtual_memory().total,
            "storage": {
                "first_input": _storage_metadata(inputs[0]),
                "output": _storage_metadata(output_argument),
            },
        },
        "elapsed_seconds": round(elapsed_seconds, 3),
        "monitor": monitor.report(),
        "python_profile": python_profile,
        "result_path": str(result_path) if result_path is not None else None,
        "output_bytes": (
            result_path.stat().st_size
            if result_path is not None and result_path.exists()
            else 0
        ),
        "output_signature": output_signature,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
