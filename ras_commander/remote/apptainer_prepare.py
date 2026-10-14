"""In-container Wine preprocessing step for ``RasApptainer.render_prepare_job``.

The Linux ``prepare`` command runs inside a Wine executor SIF (see
``containers/hecras-wine-executor``). It copies the image's baked Wine prefix
into the step-private ``/tmp`` bind, preloads the image's CPU-numbering shim,
and re-launches this module under Windows Python as ``windows-worker``. The
worker calls the public preprocessing API (``RasPreprocess.preprocess_plan``)
on the staged project, producing ``<project>.p##.tmp.hdf``, ``.b##`` and
``.x##`` for the native Linux solver.

The Linux side writes ``prepare_receipt.json``. It records computational and
file evidence only; it is not a statement that a model is hydraulically valid.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Optional, Sequence

PREPARE_RECEIPT_SCHEMA = "ras-commander-apptainer-prepare-receipt/v1"
_PLAN = re.compile(r"[0-9]{2}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _windows_worker(
    project: str, plan: str, ras_executable: str, num_cores: int, timeout: int, result: Path
) -> int:
    """Prepare one plan with the public API under Windows Python (Wine)."""
    payload: dict[str, Any] = {"success": False, "plan": plan, "num_cores": num_cores}
    try:
        from ras_commander import (
            GeomPreprocessor,
            RasPlan,
            RasPreprocess,
            RasPrj,
            init_ras_project,
        )

        ras_object = RasPrj()
        init_ras_project(
            project,
            ras_version=ras_executable,
            ras_object=ras_object,
            load_results_summary=False,
            load_hdf_metadata=False,
            hide_intro=True,
            accept_tcu=True,
        )
        plan_path = RasPlan.get_plan_path(plan, ras_object=ras_object)
        if plan_path is None:
            raise RuntimeError(f"Plan {plan} is not in the project")
        RasPlan.set_num_cores(
            plan_path, num_cores, ras_object=ras_object, refresh_dataframes=False
        )
        RasPlan.set_2d_flow_options(
            plan_path, cores=num_cores, include_default=True, ras_object=ras_object
        )
        GeomPreprocessor.clear_geompre_files(plan_path, ras_object=ras_object)
        RasPlan.update_run_flags(
            plan_path, geometry_preprocessor=True, ras_object=ras_object
        )
        outcome = RasPreprocess.preprocess_plan(
            plan,
            ras_object=ras_object,
            max_wait=timeout,
            clear_existing=True,
            fix_line_endings=True,
        )
        payload.update(
            {
                "success": bool(outcome),
                "geometry": outcome.geometry_number,
                "elapsed_seconds": outcome.elapsed_seconds,
                "signal_source": outcome.signal_source,
                "timed_out": outcome.timed_out,
                "error": outcome.error,
            }
        )
    except Exception as exc:
        payload["error"] = f"{type(exc).__name__}: {exc}"
    _write_json(result, payload)
    return 0 if payload["success"] else 1


def _expected_artifacts(project_file: Path, plan: str, computed_geometry: bool = False) -> list[Path]:
    """Solver inputs preparation must produce; ``.c##`` for releases before 6.3.1."""
    from ..RasApptainer import _plan_geometry_token

    stem = project_file.stem
    folder = project_file.parent
    xtoken = _plan_geometry_token(folder, stem, plan)
    artifacts = [
        folder / f"{stem}.p{plan}.tmp.hdf",
        folder / f"{stem}.b{plan}",
        folder / f"{stem}.{xtoken}",
    ]
    if computed_geometry:
        artifacts.append(folder / f"{stem}.c{xtoken[1:]}")
    return artifacts


def _prepare(
    project_file: Path,
    plan: str,
    num_cores: int,
    timeout: int,
    ras_executable: str,
    request_sha256: str,
    receipt_path: Path,
    computed_geometry: bool = False,
) -> int:
    """Run Windows preprocessing under a task-private Wine prefix and record it."""
    from . import execute_request as wine

    started = _utc_now()
    t0 = time.monotonic()
    receipt: dict[str, Any] = {
        "schema": PREPARE_RECEIPT_SCHEMA,
        "request_sha256": request_sha256,
        "project": project_file.name,
        "plan": plan,
        "num_cores": num_cores,
        "ras_executable": ras_executable,
        "status": "failed",
        "reason_code": "PREPARE_FAILED",
        "detail": "",
        "worker": None,
        "cpu_shim": None,
        "outputs": {},
        "started_at": started,
    }
    task_root: Optional[Path] = None
    environment: dict[str, str] = {}
    tools: dict[str, str] = {}
    try:
        seed_value = os.environ.get(wine._WINE_PREFIX_SEED, "")
        windows_python = os.environ.get(wine._WINE_PYTHON, "")
        seed = Path(seed_value)
        if not seed_value or not seed.is_absolute() or not seed.is_dir():
            raise RuntimeError(f"{wine._WINE_PREFIX_SEED} must name the image's Wine prefix")
        if not wine._is_absolute_windows_executable(windows_python):
            raise RuntimeError(f"{wine._WINE_PYTHON} must be an absolute Windows .exe path")
        if not wine._is_absolute_windows_executable(ras_executable):
            raise ValueError("ras_executable must be an absolute Windows .exe path")
        cpu_shim = wine._wine_cpu_shim()
        tools = {
            name: wine._required_tool(name)
            for name in ("wine", "wineserver", "xvfb-run")
        }
        task_root = Path(tempfile.mkdtemp(prefix="ras-prepare-", dir=tempfile.gettempdir()))
        prefix = task_root / "prefix"
        shutil.copytree(seed.resolve(), prefix, symlinks=True)
        environment = dict(os.environ)
        environment.update(
            {
                "WINEPREFIX": str(prefix),
                "WINEARCH": os.environ.get(wine._WINE_ARCH, "win64"),
                "WINEDEBUG": "-all",
            }
        )
        environment["WINEDLLOVERRIDES"] = wine._disable_wine_debugger(
            environment.get("WINEDLLOVERRIDES", "")
        )
        if cpu_shim is not None:
            preload = environment.get("LD_PRELOAD", "").strip()
            environment["LD_PRELOAD"] = f"{cpu_shim} {preload}".strip()
            receipt["cpu_shim"] = {"path": str(cpu_shim), "sha256": _sha256(cpu_shim)}
        result_path = task_root / "worker_result.json"
        root_drive = prefix / "dosdevices" / "z:"
        if not (root_drive.is_symlink() and root_drive.resolve() == Path("/")):
            raise RuntimeError("Wine prefix seed must map Z: to the POSIX root")

        def windows(path: Path) -> str:
            return str(PureWindowsPath("Z:/") / path.resolve().relative_to("/").as_posix())

        command = [
            *wine._xvfb_command(tools["xvfb-run"]), tools["wine"], windows_python,
            "-m", "ras_commander.remote.apptainer_prepare", "windows-worker",
            "--project", windows(project_file),
            "--plan", plan,
            "--ras-executable", ras_executable,
            "--num-cores", str(num_cores),
            "--timeout", str(timeout),
            "--result", windows(result_path),
        ]
        print("ras-commander prepare: starting Wine preprocessing", flush=True)
        completed = subprocess.run(
            command, check=False, shell=False, env=environment, timeout=timeout + 300
        )
        worker = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
        receipt["worker"] = worker
        artifacts = _expected_artifacts(project_file, plan, computed_geometry)
        missing = [path.name for path in artifacts if not path.is_file() or path.stat().st_size == 0]
        if completed.returncode != 0 or not worker or not worker.get("success"):
            receipt["detail"] = (worker or {}).get("error") or f"Wine worker exited {completed.returncode}"
        elif missing:
            receipt["reason_code"] = "PREPARE_ARTIFACTS_MISSING"
            receipt["detail"] = f"missing or empty: {missing}"
        else:
            from ..RasApptainer import check_solver_ready

            problems = check_solver_ready(artifacts[0])
            if problems:
                receipt["reason_code"] = "PREPARE_NOT_SOLVER_READY"
                receipt["detail"] = "; ".join(problems)
            else:
                receipt["status"] = "succeeded"
                receipt["reason_code"] = "COMPLETED"
        receipt["outputs"] = {
            path.name: {"sha256": _sha256(path), "size_bytes": path.stat().st_size}
            for path in _expected_artifacts(project_file, plan, computed_geometry)
            if path.is_file()
        }
    except subprocess.TimeoutExpired:
        receipt["reason_code"] = "PREPARE_TIMEOUT"
        receipt["detail"] = f"Wine preprocessing exceeded {timeout + 300} seconds"
    except Exception as exc:
        receipt["detail"] = f"{type(exc).__name__}: {exc}"
    finally:
        if task_root is not None:
            try:
                if "wineserver" in tools and environment:
                    wine._shutdown_wineserver(tools["wineserver"], environment)
            except Exception as exc:  # cleanup evidence; never masks the result
                receipt["detail"] = (receipt["detail"] + f"; wineserver: {exc}").lstrip("; ")
            shutil.rmtree(task_root, ignore_errors=True)
    receipt["finished_at"] = _utc_now()
    receipt["elapsed_seconds"] = round(time.monotonic() - t0, 3)
    _write_json(receipt_path, receipt)
    return 0 if receipt["status"] == "succeeded" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ras-commander-apptainer-prepare")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Linux side: run Wine preprocessing")
    prepare.add_argument("--project", type=Path, required=True)
    prepare.add_argument("--receipt", type=Path, required=True)
    prepare.add_argument("--request-sha256", required=True)
    prepare.add_argument("--require-computed-geometry", action="store_true",
                         help="also require the .c## computed geometry (HEC-RAS before 6.3.1)")
    worker = commands.add_parser("windows-worker", help="Windows Python side (internal)")
    worker.add_argument("--project", required=True)
    worker.add_argument("--result", type=Path, required=True)
    for sub in (prepare, worker):
        sub.add_argument("--plan", required=True)
        sub.add_argument("--ras-executable", required=True)
        sub.add_argument("--num-cores", type=int, required=True)
        sub.add_argument("--timeout", type=int, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not _PLAN.fullmatch(args.plan) or not 1 <= args.num_cores <= 256 or args.timeout < 1:
        print("invalid --plan, --num-cores or --timeout", file=sys.stderr)
        return 2
    if args.command == "windows-worker":
        return _windows_worker(
            args.project, args.plan, args.ras_executable, args.num_cores, args.timeout, args.result
        )
    if not _SHA256.fullmatch(args.request_sha256):
        print("--request-sha256 must be a lowercase SHA-256", file=sys.stderr)
        return 2
    project = args.project.resolve()
    if project.suffix.lower() != ".prj" or not project.is_file():
        print("--project must name the staged .prj file", file=sys.stderr)
        return 2
    return _prepare(
        project, args.plan, args.num_cores, args.timeout, args.ras_executable,
        args.request_sha256, args.receipt, args.require_computed_geometry,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
