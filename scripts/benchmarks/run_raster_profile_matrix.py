"""Run an explicit raster-performance matrix and summarize JSON reports.

The manifest is intentionally explicit: every function and setting combination
has a stable run id and exact arguments. This avoids silently expanding a large
Cartesian product on the Spring River pressure fixture.
"""

from __future__ import annotations

import argparse
import atexit
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = {
    "store_maps": ROOT / "scripts" / "benchmarks" / "benchmark_store_maps_memory.py",
    "terrain": ROOT / "scripts" / "benchmarks" / "benchmark_terrain_functions.py",
}
BOOLEAN_OPTION_FLAGS = {"overviews", "stitch", "generate-prj", "fix-georef"}


def _format_value(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format_map(variables)
    if isinstance(value, list):
        return [_format_value(item, variables) for item in value]
    return value


def _arguments_to_cli(arguments: dict[str, Any]) -> list[str]:
    command: list[str] = []
    for raw_name, value in arguments.items():
        name = raw_name.replace("_", "-")
        flag = f"--{name}"
        if name in BOOLEAN_OPTION_FLAGS and isinstance(value, bool):
            command.append(flag if value else f"--no-{name}")
            continue
        if isinstance(value, bool):
            if value:
                command.append(flag)
            continue
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            command.extend([flag, str(item)])
    return command


def _summary_row(
    run_id: str,
    repeat_index: int,
    runner: str,
    return_code: int,
    report: dict[str, Any] | None,
) -> dict[str, Any]:
    if report is None:
        return {
            "run_id": run_id,
            "repeat": repeat_index,
            "runner": runner,
            "status": "missing_report",
            "return_code": return_code,
        }
    configuration = report.get("configuration", {})
    monitor = report.get("monitor", {})
    project_storage = configuration.get("storage", {}).get("project", {})
    input_storage = configuration.get("storage", {}).get("first_input", {})
    output_storage = configuration.get("storage", {}).get(
        "requested_output",
        configuration.get("storage", {}).get("output", {}),
    )
    return {
        "run_id": run_id,
        "repeat": repeat_index,
        "runner": runner,
        "function": configuration.get("function"),
        "status": report.get("status"),
        "return_code": return_code,
        "elapsed_seconds": report.get("elapsed_seconds"),
        "peak_tree_rss_bytes": monitor.get("peak_tree_rss_bytes"),
        "peak_tree_private_bytes": monitor.get("peak_tree_private_bytes"),
        "minimum_available_memory_bytes": monitor.get("minimum_available_memory_bytes"),
        "cpu_seconds": monitor.get("summed_process_cpu_seconds"),
        "read_bytes": monitor.get("summed_process_read_bytes"),
        "write_bytes": monitor.get("summed_process_write_bytes"),
        "read_operations": monitor.get("summed_process_read_operations"),
        "write_operations": monitor.get("summed_process_write_operations"),
        "maximum_helpers": monitor.get("maximum_process_counts", {}).get(
            "RasStoreMapHelper.exe",
            0,
        ),
        "project_storage": project_storage.get("drive_type"),
        "input_storage": input_storage.get("drive_type"),
        "output_storage": output_storage.get("drive_type"),
        "max_workers": configuration.get("max_workers"),
        "threads": configuration.get(
            "threads",
            configuration.get(
                "gdal_num_threads_per_helper",
                configuration.get("gdal_num_threads_environment"),
            ),
        ),
        "gdal_cachemax_mb": configuration.get("gdal_cachemax_mb"),
        "maps": ",".join(configuration.get("maps", [])),
        "operation": configuration.get("function"),
        "output_bytes": report.get("output_bytes"),
        "phase_seconds": json.dumps(
            monitor.get("inferred_phase_seconds", {}),
            sort_keys=True,
        ),
    }


def _write_markdown(rows: list[dict[str, Any]], path: Path) -> None:
    columns = [
        "run_id",
        "repeat",
        "function",
        "status",
        "elapsed_seconds",
        "peak_tree_private_bytes",
        "cpu_seconds",
        "write_operations",
        "project_storage",
        "output_storage",
        "max_workers",
        "threads",
        "gdal_cachemax_mb",
    ]
    lines = [
        "# Raster profile matrix summary",
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = [str(row.get(column, "") or "") for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--rerun", action="store_true")
    return parser


def _acquire_matrix_lock(output_root: Path) -> tuple[int, Path]:
    lock_path = output_root / ".matrix-running.json"
    if lock_path.exists():
        try:
            owner = json.loads(lock_path.read_text(encoding="utf-8"))
            owner_pid = int(owner["pid"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            owner_pid = -1
        if owner_pid > 0 and psutil.pid_exists(owner_pid):
            raise RuntimeError(
                f"Another profile matrix owns {output_root} (PID {owner_pid})"
            )
        lock_path.unlink()
    descriptor = os.open(
        lock_path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
    )
    os.write(
        descriptor,
        json.dumps({"pid": os.getpid(), "output_root": str(output_root)}).encode(
            "utf-8"
        ),
    )
    return descriptor, lock_path


def _release_matrix_lock(descriptor: int, lock_path: Path) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def main() -> int:
    args = build_parser().parse_args()
    manifest_path = Path(os.path.abspath(args.manifest))
    output_root = Path(os.path.abspath(args.output_root))
    output_root.mkdir(parents=True, exist_ok=True)
    lock_descriptor, lock_path = _acquire_matrix_lock(output_root)
    atexit.register(_release_matrix_lock, lock_descriptor, lock_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "ras-commander.raster-profile-matrix/1":
        raise ValueError("Unsupported or missing matrix manifest schema")

    base_variables = {
        key: str(value) for key, value in manifest.get("variables", {}).items()
    }
    base_variables.update(
        {
            "repo_root": str(ROOT),
            "output_root": str(output_root),
        }
    )
    rows: list[dict[str, Any]] = []
    overall_status = 0

    for run in manifest.get("runs", []):
        run_id = str(run["id"])
        runner_name = str(run["runner"])
        if runner_name not in RUNNERS:
            raise ValueError(f"Unknown runner for {run_id}: {runner_name}")
        repeat_count = int(run.get("repeat", 1))
        if repeat_count < 1:
            raise ValueError(f"repeat must be positive for {run_id}")

        for repeat_index in range(1, repeat_count + 1):
            instance_id = (
                f"{run_id}_r{repeat_index:02d}" if repeat_count > 1 else run_id
            )
            run_dir = output_root / instance_id
            run_dir.mkdir(parents=True, exist_ok=True)
            variables = {
                **base_variables,
                "run_id": run_id,
                "instance_id": instance_id,
                "run_dir": str(run_dir),
                "repeat": str(repeat_index),
            }
            arguments = {
                key: _format_value(value, variables)
                for key, value in run.get("args", {}).items()
            }
            report_path = run_dir / "report.json"
            arguments["report_path"] = str(report_path)
            if run.get("python_profile", True):
                arguments["python_profile_path"] = str(run_dir / "python.pstats")

            if report_path.exists() and not args.rerun:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                rows.append(
                    _summary_row(
                        run_id,
                        repeat_index,
                        runner_name,
                        0,
                        report,
                    )
                )
                continue

            command = [
                sys.executable,
                str(RUNNERS[runner_name]),
                *_arguments_to_cli(arguments),
            ]
            (run_dir / "command.json").write_text(
                json.dumps(command, indent=2),
                encoding="utf-8",
            )
            started = time.perf_counter()
            completed = subprocess.run(
                command,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": str(ROOT)},
            )
            (run_dir / "stdout.log").write_text(
                completed.stdout or "",
                encoding="utf-8",
            )
            (run_dir / "stderr.log").write_text(
                completed.stderr or "",
                encoding="utf-8",
            )
            (run_dir / "launcher.json").write_text(
                json.dumps(
                    {
                        "return_code": completed.returncode,
                        "launcher_elapsed_seconds": round(
                            time.perf_counter() - started,
                            3,
                        ),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            report = (
                json.loads(report_path.read_text(encoding="utf-8"))
                if report_path.exists()
                else None
            )
            rows.append(
                _summary_row(
                    run_id,
                    repeat_index,
                    runner_name,
                    completed.returncode,
                    report,
                )
            )
            if completed.returncode != 0:
                overall_status = 1
                if not args.continue_on_error:
                    break
        if overall_status and not args.continue_on_error:
            break

    summary_json = {
        "schema": "ras-commander.raster-profile-matrix-summary/1",
        "manifest": str(manifest_path),
        "output_root": str(output_root),
        "runs": rows,
    }
    (output_root / "matrix_summary.json").write_text(
        json.dumps(summary_json, indent=2),
        encoding="utf-8",
    )
    if rows:
        fieldnames = sorted({key for row in rows for key in row})
        with (output_root / "matrix_summary.csv").open(
            "w",
            newline="",
            encoding="utf-8",
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    _write_markdown(rows, output_root / "matrix_summary.md")
    print(json.dumps(summary_json, indent=2))
    _release_matrix_lock(lock_descriptor, lock_path)
    atexit.unregister(_release_matrix_lock)
    return overall_status


if __name__ == "__main__":
    raise SystemExit(main())
