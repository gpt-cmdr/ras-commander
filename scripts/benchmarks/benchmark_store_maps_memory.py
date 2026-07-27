"""Benchmark RASMapper Stored Maps with process-tree memory instrumentation.

This is an opt-in integration benchmark for real, computed HEC-RAS projects.
It does not download data or modify the source project intentionally; callers
should point it at a disposable project copy and a fresh output directory.
"""

from __future__ import annotations

import argparse
import cProfile
import ctypes
import hashlib
import io
import json
import os
import pstats
import sys
import threading
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

import psutil
import rasterio

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ras_commander import (  # noqa: E402
    RasMap,
    RasProcess,
    StoreMapPerformanceOptions,
    init_ras_project,
)

MAP_FLAGS = {"wse", "depth", "velocity"}
OPERATIONS = {"store_maps", "store_maps_at_timesteps", "store_all_maps"}


def _sha256(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _raster_signature(path: Path) -> dict[str, Any]:
    """Hash decoded raster values block by block without whole-grid allocation."""
    digest = hashlib.sha256()
    with rasterio.Env(GDAL_CACHEMAX=64):
        with rasterio.open(path) as src:
            for band_index in range(1, src.count + 1):
                for _, window in src.block_windows(band_index):
                    digest.update(
                        src.read(band_index, window=window).tobytes(order="C")
                    )
            return {
                "pixel_sha256": digest.hexdigest(),
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "dtypes": list(src.dtypes),
                "crs": str(src.crs) if src.crs is not None else None,
                "transform": list(src.transform)[:6],
                "nodata": src.nodata,
            }


def _file_record(
    path: Path,
    root: Path,
    include_raster_signature: bool,
) -> dict[str, Any]:
    stat = path.stat()
    record = {
        "path": str(path.relative_to(root)),
        "bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }
    if include_raster_signature and path.suffix.casefold() in {".tif", ".tiff"}:
        record["raster"] = _raster_signature(path)
    return record


def _serialize_paths(value: Any) -> Any:
    if isinstance(value, Path):
        return str(Path(os.path.abspath(value)))
    if isinstance(value, dict):
        return {key: _serialize_paths(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_paths(item) for item in value]
    return value


def _preservation_state(paths: list[Path], include_hash: bool) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for path in paths:
        stat = path.stat()
        record: dict[str, Any] = {
            "bytes": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
        }
        if include_hash:
            record["sha256"] = _sha256(path)
        state[str(path)] = record
    return state


class ProcessTreeMonitor:
    """Sample the benchmark process and every descendant without retaining PII."""

    def __init__(
        self,
        interval_seconds: float = 0.1,
        watch_paths: list[Path] | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.watch_paths = [Path(path) for path in (watch_paths or [])]
        self.root = psutil.Process()
        root_io = self.root.io_counters()
        root_cpu = self.root.cpu_times()
        self._root_io_baseline = (
            root_io.read_bytes,
            root_io.write_bytes,
            root_io.read_count,
            root_io.write_count,
        )
        self._root_cpu_baseline = root_cpu.user + root_cpu.system
        self.started = time.perf_counter()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.peak_tree_rss_bytes = 0
        self.peak_tree_private_bytes = 0
        self.minimum_available_memory_bytes = psutil.virtual_memory().available
        self.maximum_threads = 0
        self.maximum_process_counts: dict[str, int] = defaultdict(int)
        self.processes: dict[int, dict[str, Any]] = {}
        self.timeline: list[dict[str, Any]] = []
        self._last_timeline_second = -1

    def _watched_file_snapshot(self) -> tuple[int, int]:
        """Return direct-child raster/HDF sizes without recursive enumeration.

        The benchmark passes each directory that can receive output explicitly.
        Recursively scanning a mapped SMB path on every sample can itself block
        for seconds and distort the operation being measured.
        """
        file_count = 0
        total_bytes = 0
        for watch_path in self.watch_paths:
            try:
                if not watch_path.is_dir():
                    continue
                with os.scandir(watch_path) as candidates:
                    for entry in candidates:
                        if not entry.is_file() or Path(
                            entry.name
                        ).suffix.casefold() not in {
                            ".tif",
                            ".tiff",
                            ".vrt",
                            ".hdf",
                        }:
                            continue
                        stat = entry.stat()
                        file_count += 1
                        total_bytes += stat.st_size
            except (FileNotFoundError, NotADirectoryError, OSError):
                continue
        return file_count, total_bytes

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, self.interval_seconds * 4))
        self._sample()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def _sample(self) -> None:
        try:
            processes = [self.root, *self.root.children(recursive=True)]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            processes = [self.root]

        tree_rss = 0
        tree_private = 0
        tree_threads = 0
        active_names: dict[str, int] = defaultdict(int)
        for process in processes:
            try:
                with process.oneshot():
                    name = process.name()
                    memory = process.memory_info()
                    io = process.io_counters()
                    cpu = process.cpu_times()
                    threads = process.num_threads()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue

            tree_rss += memory.rss
            private_bytes = getattr(memory, "private", memory.rss)
            tree_private += private_bytes
            tree_threads += threads
            active_names[name] += 1
            record = self.processes.setdefault(
                process.pid,
                {
                    "pid": process.pid,
                    "name": name,
                    "peak_rss_bytes": 0,
                    "peak_private_bytes": 0,
                    "maximum_threads": 0,
                    "read_bytes": 0,
                    "write_bytes": 0,
                    "read_operations": 0,
                    "write_operations": 0,
                    "cpu_seconds": 0.0,
                    "baseline_read_bytes": (
                        self._root_io_baseline[0] if process.pid == self.root.pid else 0
                    ),
                    "baseline_write_bytes": (
                        self._root_io_baseline[1] if process.pid == self.root.pid else 0
                    ),
                    "baseline_read_operations": (
                        self._root_io_baseline[2] if process.pid == self.root.pid else 0
                    ),
                    "baseline_write_operations": (
                        self._root_io_baseline[3] if process.pid == self.root.pid else 0
                    ),
                    "baseline_cpu_seconds": (
                        self._root_cpu_baseline if process.pid == self.root.pid else 0.0
                    ),
                },
            )
            record["peak_rss_bytes"] = max(record["peak_rss_bytes"], memory.rss)
            record["peak_private_bytes"] = max(
                record["peak_private_bytes"], private_bytes
            )
            record["maximum_threads"] = max(record["maximum_threads"], threads)
            record["read_bytes"] = max(
                record["read_bytes"],
                io.read_bytes - record["baseline_read_bytes"],
            )
            record["write_bytes"] = max(
                record["write_bytes"],
                io.write_bytes - record["baseline_write_bytes"],
            )
            record["read_operations"] = max(
                record["read_operations"],
                io.read_count - record["baseline_read_operations"],
            )
            record["write_operations"] = max(
                record["write_operations"],
                io.write_count - record["baseline_write_operations"],
            )
            record["cpu_seconds"] = max(
                record["cpu_seconds"],
                cpu.user + cpu.system - record["baseline_cpu_seconds"],
            )

        available = psutil.virtual_memory().available
        self.peak_tree_rss_bytes = max(self.peak_tree_rss_bytes, tree_rss)
        self.peak_tree_private_bytes = max(self.peak_tree_private_bytes, tree_private)
        self.minimum_available_memory_bytes = min(
            self.minimum_available_memory_bytes, available
        )
        self.maximum_threads = max(self.maximum_threads, tree_threads)
        for name, count in active_names.items():
            self.maximum_process_counts[name] = max(
                self.maximum_process_counts[name], count
            )

        elapsed = time.perf_counter() - self.started
        elapsed_second = int(elapsed)
        if elapsed_second != self._last_timeline_second:
            self._last_timeline_second = elapsed_second
            cumulative_read_bytes = sum(
                record["read_bytes"] for record in self.processes.values()
            )
            cumulative_write_bytes = sum(
                record["write_bytes"] for record in self.processes.values()
            )
            cumulative_read_operations = sum(
                record["read_operations"] for record in self.processes.values()
            )
            cumulative_write_operations = sum(
                record["write_operations"] for record in self.processes.values()
            )
            watched_file_count, watched_output_bytes = self._watched_file_snapshot()
            self.timeline.append(
                {
                    "elapsed_seconds": round(elapsed, 3),
                    "tree_rss_bytes": tree_rss,
                    "tree_private_bytes": tree_private,
                    "available_memory_bytes": available,
                    "tree_threads": tree_threads,
                    "cumulative_read_bytes": cumulative_read_bytes,
                    "cumulative_write_bytes": cumulative_write_bytes,
                    "cumulative_read_operations": cumulative_read_operations,
                    "cumulative_write_operations": cumulative_write_operations,
                    "watched_file_count": watched_file_count,
                    "watched_output_bytes": watched_output_bytes,
                    "process_counts": dict(sorted(active_names.items())),
                }
            )

    def _phase_summary(self) -> dict[str, float]:
        phase_seconds: dict[str, float] = defaultdict(float)
        if len(self.timeline) < 2:
            return {}
        previous_output_bytes = self.timeline[0].get("watched_output_bytes", 0)
        for previous, current in zip(self.timeline, self.timeline[1:]):
            seconds = max(
                0.0,
                current["elapsed_seconds"] - previous["elapsed_seconds"],
            )
            process_counts = current.get("process_counts", {})
            output_bytes = current.get("watched_output_bytes", 0)
            output_growing = output_bytes > previous_output_bytes
            if process_counts.get("gdaladdo.exe", 0):
                phase = "gdal_overviews"
            elif process_counts.get("gdal_translate.exe", 0):
                phase = "gdal_translate"
            elif process_counts.get("RasProcess.exe", 0):
                phase = "terrain_native"
            elif process_counts.get("RasStoreMapHelper.exe", 0):
                phase = (
                    "store_map_output_growing"
                    if output_growing
                    else "store_map_compute_or_histogram"
                )
            else:
                phase = "python_or_idle"
            phase_seconds[phase] += seconds
            previous_output_bytes = output_bytes
        return {key: round(value, 3) for key, value in sorted(phase_seconds.items())}

    def report(self) -> dict[str, Any]:
        processes = sorted(
            self.processes.values(),
            key=lambda item: (-item["peak_rss_bytes"], item["pid"]),
        )
        public_processes = [
            {
                key: value
                for key, value in process.items()
                if not key.startswith("baseline_")
            }
            for process in processes
        ]
        for process in public_processes:
            read_operations = process["read_operations"]
            write_operations = process["write_operations"]
            process["mean_read_size_bytes"] = (
                process["read_bytes"] / read_operations if read_operations else None
            )
            process["mean_write_size_bytes"] = (
                process["write_bytes"] / write_operations if write_operations else None
            )
        return {
            "sample_interval_seconds": self.interval_seconds,
            "peak_tree_rss_bytes": self.peak_tree_rss_bytes,
            "peak_tree_private_bytes": self.peak_tree_private_bytes,
            "minimum_available_memory_bytes": self.minimum_available_memory_bytes,
            "maximum_tree_threads": self.maximum_threads,
            "maximum_process_counts": dict(sorted(self.maximum_process_counts.items())),
            "observed_processes": public_processes,
            "summed_process_read_bytes": sum(item["read_bytes"] for item in processes),
            "summed_process_write_bytes": sum(
                item["write_bytes"] for item in processes
            ),
            "summed_process_read_operations": sum(
                item["read_operations"] for item in processes
            ),
            "summed_process_write_operations": sum(
                item["write_operations"] for item in processes
            ),
            "summed_process_cpu_seconds": round(
                sum(item["cpu_seconds"] for item in processes), 3
            ),
            "inferred_phase_seconds": self._phase_summary(),
            "timeline": self.timeline,
        }


def _storage_metadata(path: Path) -> dict[str, Any]:
    """Describe a benchmark path without resolving mapped drives to UNC."""
    absolute = Path(os.path.abspath(path))
    anchor = absolute.anchor
    drive_type = "unknown"
    drive_type_code = None
    if os.name == "nt" and anchor:
        try:
            drive_type_code = int(ctypes.windll.kernel32.GetDriveTypeW(anchor))
            drive_type = {
                0: "unknown",
                1: "invalid",
                2: "removable",
                3: "fixed",
                4: "network",
                5: "optical",
                6: "ramdisk",
            }.get(drive_type_code, "unknown")
        except (AttributeError, OSError, TypeError):
            pass
    usage = None
    usage_target = anchor or str(absolute)
    try:
        disk_usage = psutil.disk_usage(usage_target)
        usage = {
            "total_bytes": disk_usage.total,
            "free_bytes": disk_usage.free,
            "percent_used": disk_usage.percent,
        }
    except OSError:
        pass
    return {
        "path": str(absolute),
        "anchor": anchor,
        "drive_type": drive_type,
        "drive_type_code": drive_type_code,
        "disk_usage": usage,
    }


def _set_optional_environment(name: str, value: str | None) -> str | None:
    previous = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    return previous


def _restore_environment(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def _parse_maps(raw: str) -> list[str]:
    maps = [item.strip().casefold() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(maps) - MAP_FLAGS)
    if unknown:
        raise argparse.ArgumentTypeError(
            f"Unsupported map type(s): {', '.join(unknown)}; choose from "
            f"{', '.join(sorted(MAP_FLAGS))}"
        )
    if not maps:
        raise argparse.ArgumentTypeError("At least one map type is required")
    return maps


def _parse_max_workers(raw: str) -> int | None:
    if raw.strip().casefold() == "auto":
        return None
    try:
        workers = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "max workers must be a positive integer or 'auto'"
        ) from exc
    if workers < 1:
        raise argparse.ArgumentTypeError(
            "max workers must be a positive integer or 'auto'"
        )
    return workers


def _parse_gdal_threads(raw: str) -> str | None:
    normalized = raw.strip().upper()
    if normalized in {"NONE", "DEFAULT", "UNSET"}:
        return None
    if normalized == "ALL_CPUS":
        return normalized
    if normalized.isdigit() and int(normalized) > 0:
        return normalized
    raise argparse.ArgumentTypeError(
        "GDAL threads must be a positive integer, ALL_CPUS, or none"
    )


def _performance_options_from_args(
    args: argparse.Namespace,
) -> StoreMapPerformanceOptions:
    """Build the exact child-process policy recorded by this benchmark run."""

    return StoreMapPerformanceOptions(
        max_workers=args.max_workers,
        minimum_worker_memory_mb=args.memory_per_worker_mb,
        reserve_memory_mb=args.reserve_memory_mb,
        gdal_num_threads_per_helper=args.gdal_num_threads,
        gdal_cachemax_mb=args.gdal_cachemax_mb,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=sorted(OPERATIONS), default="store_maps")
    parser.add_argument("--project-folder", type=Path, required=True)
    parser.add_argument("--plan-number", default="02")
    parser.add_argument("--map-profile", default="Max")
    parser.add_argument("--timestep", action="append", default=None)
    parser.add_argument("--max-timesteps", type=int, default=None)
    parser.add_argument("--ras-version", default="7.0")
    parser.add_argument("--maps", type=_parse_maps, default=_parse_maps("depth"))
    parser.add_argument(
        "--max-workers",
        type=_parse_max_workers,
        default=1,
        help="Worker cap or 'auto' for CPU- and memory-bounded selection.",
    )
    parser.add_argument("--memory-per-worker-mb", type=int, default=600)
    parser.add_argument("--reserve-memory-mb", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--sample-interval", type=float, default=0.1)
    parser.add_argument(
        "--fix-georef",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--label", default=None)
    parser.add_argument("--gdal-cachemax-mb", type=int, default=None)
    parser.add_argument("--gdal-num-threads", type=_parse_gdal_threads, default=None)
    parser.add_argument("--python-profile-path", type=Path, default=None)
    parser.add_argument(
        "--skip-hdf-hash",
        action="store_true",
        help="Use size/mtime preservation checks without hashing the plan HDF.",
    )
    parser.add_argument(
        "--skip-raster-signatures",
        action="store_true",
        help="Skip block-streamed decoded-pixel hashes for generated TIFFs.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    # Preserve mapped drive letters. Path.resolve() converts H: to a UNC path on
    # this workstation, while native HEC-RAS mapping libraries are more reliable
    # with the drive mapping visible to the interactive session.
    project_folder = Path(os.path.abspath(args.project_folder))
    output_path = Path(os.path.abspath(args.output_path))
    report_path = Path(os.path.abspath(args.report_path))
    if args.gdal_cachemax_mb is not None and args.gdal_cachemax_mb < 1:
        raise ValueError("gdal-cachemax-mb must be positive")
    if args.sample_interval <= 0:
        raise ValueError("sample-interval must be positive")
    performance_options = _performance_options_from_args(args)
    if output_path.exists() and any(output_path.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_path}")
    output_path.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    ras = init_ras_project(project_folder, args.ras_version)
    project_file = project_folder / f"{ras.project_name}.prj"
    if not project_file.exists():
        raise FileNotFoundError(f"Project file not found: {project_file}")
    plan_number = str(args.plan_number).zfill(2)
    plan_rows = ras.plan_df.loc[ras.plan_df["plan_number"] == plan_number]
    if len(plan_rows) != 1:
        raise ValueError(f"Plan {plan_number} did not resolve uniquely")
    plan_hdf = Path(plan_rows.iloc[0]["HDF_Results_Path"])
    rasmap_path = RasMap.get_rasmap_path(ras)
    if rasmap_path is None:
        raise FileNotFoundError("Project has no RASMapper file")
    rasmap_path = Path(rasmap_path)

    preserved_paths = [rasmap_path, plan_hdf]
    if args.operation == "store_all_maps":
        preserved_paths = [
            rasmap_path,
            *sorted(
                path
                for path in project_folder.glob(f"{ras.project_name}.p*.hdf")
                if path.is_file()
            ),
        ]
    before = _preservation_state(
        preserved_paths,
        include_hash=not args.skip_hdf_hash,
    )
    if args.skip_hdf_hash:
        before[str(rasmap_path)]["sha256"] = _sha256(rasmap_path)

    plan_short_id = RasProcess._get_plan_short_id(plan_hdf)
    watched_paths = [output_path]
    if plan_short_id:
        watched_paths.append(project_folder / plan_short_id)
    monitor = ProcessTreeMonitor(args.sample_interval, watch_paths=watched_paths)
    started = time.perf_counter()
    status = "running"
    generated: dict[str, Any] = {}
    error: dict[str, str] | None = None
    profiler = cProfile.Profile() if args.python_profile_path else None
    monitor.start()
    if profiler is not None:
        profiler.enable()
    try:
        shared_arguments = {
            "output_path": output_path,
            "wse": "wse" in args.maps,
            "depth": "depth" in args.maps,
            "velocity": "velocity" in args.maps,
            "fix_georef": args.fix_georef,
            "ras_object": ras,
            "ras_version": args.ras_version,
            "timeout": args.timeout,
            "performance": performance_options,
        }
        if args.operation == "store_maps":
            generated = RasProcess.store_maps(
                plan_number=plan_number,
                profile=args.map_profile,
                clear_existing=True,
                **shared_arguments,
            )
        elif args.operation == "store_maps_at_timesteps":
            generated = RasProcess.store_maps_at_timesteps(
                plan_number=plan_number,
                timesteps=args.timestep,
                max_timesteps=args.max_timesteps,
                clear_existing=True,
                **shared_arguments,
            )
        else:
            generated = RasMap.store_all_maps(
                mode="all_plans",
                profile=args.map_profile,
                clear_existing=True,
                **shared_arguments,
            )
            if not generated["success"]:
                failed_plans = {
                    key: value
                    for key, value in generated["plans"].items()
                    if not value.get("success")
                }
                raise RuntimeError(f"store_all_maps failures: {failed_plans}")
        status = "complete"
    except Exception as exc:  # pragma: no cover - real native integration path
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

    after = _preservation_state(
        preserved_paths,
        include_hash=not args.skip_hdf_hash,
    )
    if args.skip_hdf_hash:
        after[str(rasmap_path)]["sha256"] = _sha256(rasmap_path)

    output_files = sorted(path for path in output_path.rglob("*") if path.is_file())
    report = {
        "schema": "ras-commander.store-maps-memory-benchmark/1",
        "status": status,
        "error": error,
        "configuration": {
            "label": args.label,
            "function": f"RasProcess.{args.operation}",
            "project_folder": str(project_folder),
            "project_file": str(project_file),
            "plan_number": plan_number,
            "map_profile": args.map_profile,
            "timesteps": args.timestep,
            "max_timesteps": args.max_timesteps,
            "ras_version": args.ras_version,
            "ras_exe_path": str(ras.ras_exe_path),
            "maps": args.maps,
            "max_workers": args.max_workers,
            "memory_per_worker_mb": args.memory_per_worker_mb,
            "reserve_memory_mb": args.reserve_memory_mb,
            "fix_georef": args.fix_georef,
            "gdal_cachemax_mb": args.gdal_cachemax_mb,
            "gdal_num_threads_per_helper": args.gdal_num_threads,
            "performance_options": performance_options.to_dict(),
            "timeout_seconds": args.timeout,
            "logical_cpu_count": os.cpu_count(),
            "total_memory_bytes": psutil.virtual_memory().total,
            "storage": {
                "project": _storage_metadata(project_folder),
                "requested_output": _storage_metadata(output_path),
            },
        },
        "elapsed_seconds": round(elapsed_seconds, 3),
        "monitor": monitor.report(),
        "python_profile": python_profile,
        "generated": _serialize_paths(generated),
        "outputs": [
            _file_record(
                path,
                output_path,
                include_raster_signature=not args.skip_raster_signatures,
            )
            for path in output_files
        ],
        "output_bytes": sum(path.stat().st_size for path in output_files),
        "project_preservation": {
            "before": before,
            "after": after,
            "rasmap_unchanged": before[str(rasmap_path)] == after[str(rasmap_path)],
            "plan_hdf_unchanged": before == after,
        },
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
