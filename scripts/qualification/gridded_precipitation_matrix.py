"""Qualify gridded-precipitation execution across installed HEC-RAS versions.

The harness deliberately uses ras-commander's public APIs for every HEC-RAS
operation.  It stages one independent project copy per executable, shortens the
selected plan to a deterministic wet interval, executes the plan, and records
both input materialization and final hydraulic/rainfall evidence.

Example::

    python -m scripts.qualification.gridded_precipitation_matrix \
        --source-project C:/models/BaldEagleCrkMulti2D/BaldEagleDamBrk.prj \
        --plan 06 --start 2018-09-09T18:00 --end 2018-09-09T19:20 \
        --workspace working/gridded-precip-matrix \
        --executable 6.6="C:/Program Files (x86)/HEC/HEC-RAS/6.6/Ras.exe" \
        --report working/gridded-precip-matrix/report.json

Large staged projects and result HDFs belong under ``working/``.  Only compact
JSON reports should be promoted into reviewable evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from ras_commander import (
    RasCmdr,
    RasPlan,
    RasPreprocess,
    RasPrj,
    RasTcu,
    init_ras_project,
)


PRECIPITATION_GROUP = "Event Conditions/Meteorology/Precipitation"
CUMULATIVE_PRECIPITATION = (
    "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
    "2D Flow Areas/{area}/Cell Cumulative Precipitation Depth"
)
WATER_SURFACE = (
    "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
    "2D Flow Areas/{area}/Water Surface"
)
COMPUTE_MESSAGES = "Results/Summary/Compute Messages (text)"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return _decode(value.item())
    if isinstance(value, np.ndarray):
        return [_decode(item) for item in value.tolist()]
    return value


def _array_summary(dataset: h5py.Dataset) -> dict[str, Any]:
    values = np.asarray(dataset[...])
    summary: dict[str, Any] = {
        "shape": list(values.shape),
        "dtype": str(values.dtype),
    }
    if values.size and np.issubdtype(values.dtype, np.number):
        finite = values[np.isfinite(values)]
        if finite.size:
            summary.update(
                minimum=float(finite.min()),
                maximum=float(finite.max()),
                nonzero=int(np.count_nonzero(finite)),
            )
    elif values.size <= 500:
        summary["values"] = _decode(values)
    return summary


def _find_2d_areas(hdf: h5py.File) -> list[str]:
    root = hdf.get(
        "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
        "2D Flow Areas"
    )
    return sorted(root.keys()) if isinstance(root, h5py.Group) else []


def _inspect_hdf(hdf_path: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "path": str(hdf_path),
        "exists": hdf_path.is_file(),
    }
    if not hdf_path.is_file():
        return evidence

    evidence.update(size_bytes=hdf_path.stat().st_size, sha256=_sha256(hdf_path))
    with h5py.File(hdf_path, "r") as hdf:
        precipitation = hdf.get(PRECIPITATION_GROUP)
        if isinstance(precipitation, h5py.Group):
            evidence["precipitation"] = {
                "attributes": {
                    str(key): _decode(value)
                    for key, value in precipitation.attrs.items()
                },
                "timestamps": _array_summary(precipitation["Timestamp"]),
                "values": _array_summary(precipitation["Values"]),
            }

        area_evidence: dict[str, Any] = {}
        for area in _find_2d_areas(hdf):
            record: dict[str, Any] = {}
            cumulative_path = CUMULATIVE_PRECIPITATION.format(area=area)
            water_surface_path = WATER_SURFACE.format(area=area)
            if cumulative_path in hdf:
                record["cumulative_precipitation"] = _array_summary(
                    hdf[cumulative_path]
                )
            if water_surface_path in hdf:
                record["water_surface"] = _array_summary(hdf[water_surface_path])
            area_evidence[area] = record
        evidence["2d_flow_areas"] = area_evidence

        if COMPUTE_MESSAGES in hdf:
            raw = _decode(hdf[COMPUTE_MESSAGES][0])
            text = str(raw)
            significant = [
                line.strip()
                for line in text.splitlines()
                if any(
                    token in line.casefold()
                    for token in (
                        "processing precipitation",
                        "finished processing precipitation",
                        "performing unsteady flow simulation",
                        "finished unsteady flow simulation",
                        "complete process",
                        "fatal",
                    )
                )
            ]
            evidence["compute_messages"] = {
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "significant_lines": significant,
                "complete_process": "Complete Process" in text,
                "finished_unsteady": "Finished Unsteady Flow Simulation" in text,
                "fatal": bool(re.search(r"(?im)^\s*fatal\b", text)),
            }
    return evidence


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _stage_project(source_project: Path, workspace: Path, label: str) -> Path:
    stage = workspace / label
    if stage.exists():
        raise FileExistsError(
            f"Stage already exists: {stage}. Choose a fresh workspace or remove it explicitly."
        )
    shutil.copytree(source_project.parent, stage)
    return stage / source_project.name


@contextmanager
def _qualification_wmic_shim(enabled: bool):
    """Provide the read-only CPU queries required by early HEC-RAS 6.x.

    This is deliberately a qualification-harness option, not a claim about the
    library's supported version guard.  It permits a second run that isolates
    precipitation behavior after an unmodified run proves a missing-WMIC
    failure.  The shim is process-local and the caller's PATH is restored.
    """
    if not enabled:
        yield None
        return

    previous_path = os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="ras_qualification_wmic_") as raw:
        shim = Path(raw)
        (shim / "wmic.cmd").write_text(
            "@echo off\n"
            'if /I not "%~1"=="CPU" exit /b 1\n'
            'if /I not "%~2"=="get" exit /b 1\n'
            'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass '
            '-File "%~dp0wmic.ps1" "%~3"\n'
            "exit /b %ERRORLEVEL%\n",
            encoding="ascii",
        )
        (shim / "wmic.ps1").write_text(
            "param([string]$Property)\n"
            "$names = @{\n"
            "  'numberofcores' = 'NumberOfCores'\n"
            "  'numberoflogicalprocessors' = 'NumberOfLogicalProcessors'\n"
            "  'socketdesignation' = 'SocketDesignation'\n"
            "  'deviceid' = 'DeviceID'\n"
            "  'name' = 'Name'\n"
            "}\n"
            "$canonical = $names[$Property.ToLowerInvariant()]\n"
            "if (-not $canonical) { exit 1 }\n"
            "$processors = @(Get-CimInstance -ClassName Win32_Processor "
            "-ErrorAction Stop)\n"
            "if (-not $processors) { exit 1 }\n"
            "Write-Output $canonical\n"
            "foreach ($processor in $processors) {\n"
            "  $value = $processor.$canonical\n"
            "  if ($null -ne $value) { Write-Output ([string]$value) }\n"
            "}\n",
            encoding="ascii",
        )
        os.environ["PATH"] = f"{shim}{os.pathsep}{previous_path}"
        try:
            yield shim
        finally:
            os.environ["PATH"] = previous_path


def qualify(
    *,
    label: str,
    executable: Path,
    source_project: Path,
    plan_number: str,
    start: datetime,
    end: datetime,
    workspace: Path,
    max_runtime: float,
    num_cores: int,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "label": label,
        "executable": str(executable),
        "executable_exists": executable.is_file(),
        "executable_sha256": _sha256(executable) if executable.is_file() else None,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
    }
    if not executable.is_file():
        record.update(status="not_run", reason="executable_missing")
        return record

    tcu = RasTcu.status(ras_version=str(executable))
    record["tcu"] = _json_safe(tcu)
    if not bool(tcu):
        record.update(status="not_run", reason="tcu_acceptance_not_confirmed")
        return record

    staged_project = _stage_project(source_project, workspace, label)
    record["staged_project"] = str(staged_project)
    ras = init_ras_project(
        staged_project,
        str(executable),
        ras_object=RasPrj(),
        load_results_summary=False,
        hide_intro=True,
    )
    RasPlan.update_simulation_date(
        plan_number,
        start,
        end,
        ras_object=ras,
    )

    preprocess = RasPreprocess.preprocess_plan(
        plan_number,
        ras_object=ras,
        max_wait=max_runtime,
        clear_existing=True,
    )
    record["preprocess"] = _json_safe(preprocess)
    tmp_hdf_path = Path(
        getattr(preprocess, "tmp_hdf_path", None)
        or staged_project.with_suffix(f".p{plan_number}.tmp.hdf")
    )
    record["temporary_hdf"] = _inspect_hdf(tmp_hdf_path)
    if not bool(preprocess):
        record["status"] = "preprocess_failed"
        return record

    result = RasCmdr.compute_plan(
        plan_number,
        ras_object=ras,
        force_rerun=True,
        num_cores=num_cores,
        verify=True,
        max_runtime=max_runtime,
    )
    record["compute"] = {
        "success": bool(result),
        "completion_verified": getattr(result, "completion_verified", None),
        "error": getattr(result, "error", None),
        "execution_details": _json_safe(
            getattr(result, "execution_details", None)
        ),
    }
    hdf_path = staged_project.with_suffix(f".p{plan_number}.hdf")
    record["final_hdf"] = _inspect_hdf(hdf_path)
    record["status"] = "executed" if bool(result) else "failed"
    return record


def _parse_executable(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Expected LABEL=PATH")
    label, raw_path = value.split("=", 1)
    if not label.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("Expected non-empty LABEL=PATH")
    return label.strip(), Path(raw_path.strip()).expanduser().resolve()


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Expected ISO-8601 local model time, got {value!r}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--plan", default="01")
    parser.add_argument("--start", type=_parse_datetime, required=True)
    parser.add_argument("--end", type=_parse_datetime, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--executable",
        type=_parse_executable,
        action="append",
        required=True,
        metavar="LABEL=PATH",
    )
    parser.add_argument("--max-runtime", type=float, default=300.0)
    parser.add_argument("--num-cores", type=int, default=2)
    parser.add_argument(
        "--supply-wmic-shim",
        action="store_true",
        help=(
            "Supply a process-local, read-only CIM replacement for legacy "
            "'wmic CPU get' queries. Use only after an unmodified run records "
            "the missing-WMIC failure."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source_project = args.source_project.expanduser().resolve()
    if not source_project.is_file():
        raise FileNotFoundError(source_project)
    if args.end <= args.start:
        raise ValueError("--end must be later than --start")

    workspace = args.workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    report_path = args.report.expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    with _qualification_wmic_shim(args.supply_wmic_shim) as wmic_shim:
        for label, executable in args.executable:
            try:
                record = qualify(
                    label=label,
                    executable=executable,
                    source_project=source_project,
                    plan_number=str(args.plan).zfill(2),
                    start=args.start,
                    end=args.end,
                    workspace=workspace,
                    max_runtime=args.max_runtime,
                    num_cores=args.num_cores,
                )
                record["qualification_wmic_shim"] = (
                    "process_local_cim" if wmic_shim else None
                )
            except Exception as exc:  # preserve later cohort execution and the evidence
                record = {
                    "label": label,
                    "executable": str(executable),
                    "status": "harness_error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "qualification_wmic_shim": (
                        "process_local_cim" if wmic_shim else None
                    ),
                }
            records.append(record)
            report_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_project": str(source_project),
                        "plan_number": str(args.plan).zfill(2),
                        "records": records,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    return 0 if all(item["status"] == "executed" for item in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
