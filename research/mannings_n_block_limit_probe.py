from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import pandas as pd

from ras_commander import RasCmdr, init_ras_project
from ras_commander.RasExamples import RasExamples
from ras_commander.geom.GeomCrossSection import GeomCrossSection
from ras_commander.geom.GeomParser import GeomParser


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = Path("H:/Symphony/ras-commander/CLB-663")
LOCAL_WORK_ROOT = REPO_ROOT / "working" / "CLB-663"
RUN_ROOT = LOCAL_WORK_ROOT / "mannings_n_probe_runs"
ARTIFACT_RUN_ROOT = ARTIFACT_ROOT / "mannings_n_probe_runs"
RESULTS_CSV = REPO_ROOT / "research" / "mannings_n_block_limit_results.csv"
ARTIFACT_RESULTS_CSV = ARTIFACT_ROOT / "mannings_n_block_limit_results.csv"
ARTIFACT_RESULTS_JSON = ARTIFACT_ROOT / "mannings_n_block_limit_results.json"


@dataclass(frozen=True)
class ModelConfig:
    key: str
    project_name: str
    plan_number: str
    category: str


MODELS: dict[str, ModelConfig] = {
    "chanmod": ModelConfig(
        key="chanmod",
        project_name="Example 16 - Channel Modification",
        plan_number="02",
        category="Applications Guide",
    ),
    "beaver": ModelConfig(
        key="beaver",
        project_name="Example 2 - Beaver Creek",
        plan_number="01",
        category="Applications Guide",
    ),
    "wailupe": ModelConfig(
        key="wailupe",
        project_name="Wailupe GeoRAS",
        plan_number="01",
        category="1D Steady Flow Hydraulics",
    ),
}


DEFAULT_COUNTS = [25, 30, 40, 50, 100]


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore").strip().rstrip("\x00")
    return str(value).strip()


def _safe_slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _run_suffix(model_key: str, requested_blocks: int) -> str:
    return f"clb663_{model_key}_{requested_blocks:04d}"


def _expected_run_dir(model_key: str, requested_blocks: int, run_root: Path) -> Path:
    model = MODELS[model_key]
    return run_root / f"{model.project_name}_{_run_suffix(model_key, requested_blocks)}"


def _ensure_safe_delete(path: Path, root: Path) -> None:
    path = path.resolve()
    root = root.resolve()
    if path == root:
        raise ValueError(f"Refusing to delete artifact root itself: {path}")
    if root not in path.parents:
        raise ValueError(f"Refusing to delete outside artifact root: {path}")
    if path.exists():
        shutil.rmtree(path)


def _select_target_cross_section(geom_path: Path) -> dict[str, Any]:
    xs_df = GeomCrossSection.get_cross_sections(geom_path)
    candidates: list[dict[str, Any]] = []

    for xs_index, xs_row in xs_df.iterrows():
        river = str(xs_row["River"])
        reach = str(xs_row["Reach"])
        rs = str(xs_row["RS"])
        try:
            mann_df = GeomCrossSection.get_mannings_n(geom_path, river, reach, rs)
            sta_elev = GeomCrossSection.get_station_elevation(geom_path, river, reach, rs)
        except Exception:
            continue

        station_min = float(sta_elev["Station"].min())
        station_max = float(sta_elev["Station"].max())
        width = station_max - station_min
        if width <= 0:
            continue

        candidates.append(
            {
                "xs_index": int(xs_index),
                "river": river,
                "reach": reach,
                "rs": rs,
                "existing_blocks": int(len(mann_df)),
                "station_min": station_min,
                "station_max": station_max,
                "width": width,
            }
        )

    if not candidates:
        raise RuntimeError(f"No cross section with Manning's n found in {geom_path}")

    candidates.sort(
        key=lambda item: (
            item["existing_blocks"] > 3,
            item["existing_blocks"],
            item["width"],
        ),
        reverse=True,
    )
    return candidates[0]


def _make_mannings_table(target: dict[str, Any], requested_blocks: int) -> pd.DataFrame:
    station_min = float(target["station_min"])
    station_max = float(target["station_max"])
    width = station_max - station_min
    if requested_blocks <= 0:
        raise ValueError("requested_blocks must be positive")

    step = width / requested_blocks
    stations = [station_min + i * step for i in range(requested_blocks)]
    n_values = [0.050 if i % 2 else 0.052 for i in range(requested_blocks)]
    return pd.DataFrame({"Station": stations, "n_value": n_values})


def _read_plain_mann_count(geom_path: Path, target: dict[str, Any]) -> int | None:
    lines = geom_path.read_text(encoding="utf-8", errors="replace").splitlines(True)
    xs_idx = GeomCrossSection._find_cross_section(
        lines,
        target["river"],
        target["reach"],
        target["rs"],
    )
    if xs_idx is None:
        return None
    end_idx = GeomCrossSection._find_xs_section_end(lines, xs_idx)
    for line in lines[xs_idx:end_idx]:
        if line.startswith("#Mann="):
            value = GeomParser.extract_keyword_value(line, "#Mann")
            return int(value.split(",")[0].strip())
    return None


def _read_hdf_mann_count(geom_hdf: Path, target: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "geometry_hdf_exists": geom_hdf.exists(),
        "accepted_blocks": None,
        "hdf_xs_index": None,
        "hdf_values_shape": None,
        "hdf_error": "",
    }
    if not geom_hdf.exists():
        return result

    try:
        with h5py.File(geom_hdf, "r") as hdf:
            info = hdf["/Geometry/Cross Sections/Manning's n Info"][:]
            values = hdf["/Geometry/Cross Sections/Manning's n Values"][:]
            attrs = hdf["/Geometry/Cross Sections/Attributes"][:]

            hdf_index = None
            for idx, row in enumerate(attrs):
                if (
                    _decode(row["River"]) == target["river"]
                    and _decode(row["Reach"]) == target["reach"]
                    and _decode(row["RS"]) == target["rs"]
                ):
                    hdf_index = idx
                    break

            if hdf_index is None and target["xs_index"] < len(info):
                hdf_index = int(target["xs_index"])

            if hdf_index is None:
                result["hdf_error"] = "target_cross_section_not_found"
                return result

            start = int(info[hdf_index][0])
            count = int(info[hdf_index][1])
            section = values[start : start + count]
            result.update(
                {
                    "accepted_blocks": count,
                    "hdf_xs_index": hdf_index,
                    "hdf_values_shape": list(section.shape),
                }
            )
    except Exception as exc:
        result["hdf_error"] = str(exc)

    return result


def _read_compute_message_status(plan_hdf: Path) -> dict[str, Any]:
    result = {
        "plan_hdf_exists": plan_hdf.exists(),
        "compute_messages_complete": False,
        "compute_message_excerpt": "",
    }
    if not plan_hdf.exists():
        return result
    try:
        with h5py.File(plan_hdf, "r") as hdf:
            path = "Results/Summary/Compute Messages (text)"
            if path not in hdf:
                return result
            data = hdf[path][()]
            if isinstance(data, bytes):
                text = data.decode("utf-8", errors="ignore")
            elif len(data) > 0 and isinstance(data[0], bytes):
                text = data[0].decode("utf-8", errors="ignore")
            else:
                text = str(data)
            result["compute_messages_complete"] = "Complete Process" in text
            result["compute_message_excerpt"] = text[:500].replace("\r", " ").replace("\n", " ")
    except Exception as exc:
        result["compute_message_excerpt"] = f"compute_message_read_error: {exc}"
    return result


def _read_data_errors(project_path: Path) -> str:
    parts: list[str] = []
    for path in sorted(project_path.glob("*.data_errors.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception as exc:
            text = f"read_error: {exc}"
        if text:
            parts.append(f"{path.name}: {text}")
    return "\n".join(parts)


def _is_limit_error(text: str) -> bool:
    lowered = text.lower()
    return "limit of 20 per cross section" in lowered or "limit of 20" in lowered


def _classify_behavior(row: dict[str, Any]) -> str:
    if _is_limit_error(str(row.get("data_errors", ""))):
        return "limit_error"
    if row.get("status") == "timeout":
        return "timeout"
    if row.get("status") != "completed":
        return "probe_error"
    if not row.get("ras_compute_success"):
        return "ras_compute_failed"
    accepted = row.get("accepted_blocks")
    requested = row.get("requested_blocks")
    if accepted is None:
        return "no_geometry_hdf"
    if accepted == requested:
        return "accepted_preserved"
    if accepted < requested:
        return "truncated"
    return "unexpected_hdf_count"


def run_worker(model_key: str, requested_blocks: int, run_root: Path) -> dict[str, Any]:
    model = MODELS[model_key]
    start = time.time()
    run_root.mkdir(parents=True, exist_ok=True)

    print(f"WORKER extract model={model_key} requested={requested_blocks}", flush=True)
    project_path = RasExamples.extract_project(
        model.project_name,
        output_path=run_root,
        suffix=_run_suffix(model.key, requested_blocks),
    )
    print(f"WORKER extracted project_path={project_path}", flush=True)

    row: dict[str, Any] = {
        "model_key": model.key,
        "project": model.project_name,
        "category": model.category,
        "plan_number": model.plan_number,
        "requested_blocks": requested_blocks,
        "run_dir": str(project_path),
        "status": "completed",
        "error": "",
    }

    try:
        print("WORKER init_ras_project", flush=True)
        ras_obj = init_ras_project(project_path, "6.6", load_results_summary=False)
        plan_rows = ras_obj.plan_df[ras_obj.plan_df["plan_number"].eq(model.plan_number)]
        if plan_rows.empty:
            raise RuntimeError(f"Plan {model.plan_number} not found in {project_path}")
        plan_row = plan_rows.iloc[0]
        geom_path = Path(plan_row["Geom Path"])
        geometry_number = str(plan_row["geometry_number"]).zfill(2)
        print(f"WORKER selected geometry={geom_path.name}", flush=True)
        target = _select_target_cross_section(geom_path)
        mann_df = _make_mannings_table(target, requested_blocks)

        print(
            "WORKER set_mannings_n "
            f"river={target['river']} reach={target['reach']} rs={target['rs']}",
            flush=True,
        )
        GeomCrossSection.set_mannings_n(
            geom_path,
            target["river"],
            target["reach"],
            target["rs"],
            mann_df,
            format_flag=-1,
            change_flag=0,
        )
        plain_count = _read_plain_mann_count(geom_path, target)

        print("WORKER compute_plan", flush=True)
        compute_result = RasCmdr.compute_plan(
            model.plan_number,
            ras_object=ras_obj,
            force_geompre=True,
            force_rerun=True,
            verify=False,
            num_cores=2,
        )

        geom_hdf = Path(f"{geom_path}.hdf")
        plan_hdf = project_path / f"{ras_obj.project_name}.p{model.plan_number}.hdf"
        hdf_result = _read_hdf_mann_count(geom_hdf, target)
        compute_status = _read_compute_message_status(plan_hdf)
        data_errors = _read_data_errors(project_path)

        row.update(
            {
                "ras_version": "6.6",
                "ras_compute_success": bool(compute_result),
                "project_name": ras_obj.project_name,
                "geometry_number": geometry_number,
                "geometry_file": geom_path.name,
                "geometry_hdf": str(geom_hdf),
                "plan_hdf": str(plan_hdf),
                "target_river": target["river"],
                "target_reach": target["reach"],
                "target_rs": target["rs"],
                "target_existing_blocks": target["existing_blocks"],
                "target_station_min": target["station_min"],
                "target_station_max": target["station_max"],
                "plain_geometry_blocks": plain_count,
                **hdf_result,
                **compute_status,
                "data_errors": data_errors,
            }
        )
    except Exception as exc:
        row.update({"status": "error", "error": str(exc)})

    row["elapsed_seconds"] = round(time.time() - start, 2)
    row["ras_behavior"] = _classify_behavior(row)
    result_path = Path(row["run_dir"]) / "clb663_probe_result.json"
    try:
        result_path.write_text(json.dumps(row, indent=2), encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(row, sort_keys=True))
    return row


def _artifact_run_dir(row: dict[str, Any]) -> str:
    run_dir = row.get("run_dir")
    if not run_dir:
        return ""
    return str(ARTIFACT_RUN_ROOT / Path(str(run_dir)).name)


def _mirror_run_outputs(run_root: Path) -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    _ensure_safe_delete(ARTIFACT_RUN_ROOT, ARTIFACT_ROOT)
    if run_root.exists():
        shutil.copytree(run_root, ARTIFACT_RUN_ROOT)


def _inspect_incomplete_run(
    model_key: str,
    requested_blocks: int,
    run_root: Path,
    status: str,
    error: str,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    model = MODELS[model_key]
    project_path = _expected_run_dir(model_key, requested_blocks, run_root)
    row: dict[str, Any] = {
        "model_key": model_key,
        "project": model.project_name,
        "category": model.category,
        "plan_number": model.plan_number,
        "requested_blocks": requested_blocks,
        "accepted_blocks": None,
        "status": status,
        "ras_compute_success": False,
        "error": error,
        "run_dir": str(project_path),
        "stdout_tail": stdout[-2000:],
        "stderr_tail": stderr[-2000:],
    }

    try:
        if not project_path.exists():
            matches = list(run_root.glob(f"{model.project_name}_*{requested_blocks:04d}"))
            if matches:
                project_path = matches[0]
                row["run_dir"] = str(project_path)
        if project_path.exists():
            ras_obj = init_ras_project(project_path, "6.6", load_results_summary=False)
            plan_rows = ras_obj.plan_df[ras_obj.plan_df["plan_number"].eq(model.plan_number)]
            if not plan_rows.empty:
                plan_row = plan_rows.iloc[0]
                geom_path = Path(plan_row["Geom Path"])
                target = _select_target_cross_section(geom_path)
                geom_hdf = Path(f"{geom_path}.hdf")
                plan_hdf = project_path / f"{ras_obj.project_name}.p{model.plan_number}.hdf"
                row.update(
                    {
                        "ras_version": "6.6",
                        "project_name": ras_obj.project_name,
                        "geometry_number": str(plan_row["geometry_number"]).zfill(2),
                        "geometry_file": geom_path.name,
                        "geometry_hdf": str(geom_hdf),
                        "plan_hdf": str(plan_hdf),
                        "target_river": target["river"],
                        "target_reach": target["reach"],
                        "target_rs": target["rs"],
                        "target_existing_blocks": target["existing_blocks"],
                        "target_station_min": target["station_min"],
                        "target_station_max": target["station_max"],
                        "plain_geometry_blocks": _read_plain_mann_count(geom_path, target),
                        **_read_hdf_mann_count(geom_hdf, target),
                        **_read_compute_message_status(plan_hdf),
                    }
                )
            row["data_errors"] = _read_data_errors(project_path)
    except Exception as exc:
        row["inspection_error"] = str(exc)

    row["ras_behavior"] = _classify_behavior(row)
    return row


def _run_worker_subprocess(
    model_key: str,
    requested_blocks: int,
    run_root: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    run_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--model",
        model_key,
        "--requested-blocks",
        str(requested_blocks),
        "--run-root",
        str(run_root),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    expected_run_dir = _expected_run_dir(model_key, requested_blocks, run_root)
    stdout_log = run_root / f"worker_{model_key}_{requested_blocks:04d}.stdout.log"
    stderr_log = run_root / f"worker_{model_key}_{requested_blocks:04d}.stderr.log"

    start = time.time()
    with stdout_log.open("w", encoding="utf-8", errors="replace") as stdout_f, stderr_log.open(
        "w",
        encoding="utf-8",
        errors="replace",
    ) as stderr_f:
        proc = subprocess.Popen(
            cmd,
            stdout=stdout_f,
            stderr=stderr_f,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            creationflags=creationflags,
        )
        status_override = None
        error_override = ""
        while proc.poll() is None:
            elapsed = time.time() - start
            data_errors = _read_data_errors(expected_run_dir) if expected_run_dir.exists() else ""
            if _is_limit_error(data_errors):
                status_override = "data_error"
                error_override = "HEC-RAS data_errors reported Manning's n limit"
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                break
            if elapsed >= timeout_seconds:
                status_override = "timeout"
                error_override = f"timeout after {timeout_seconds}s"
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                break
            time.sleep(1)

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            proc.wait(timeout=30)

    stdout = stdout_log.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_log.read_text(encoding="utf-8", errors="replace")
    if status_override:
        row = _inspect_incomplete_run(
            model_key,
            requested_blocks,
            run_root,
            status_override,
            error_override,
            stdout=stdout,
            stderr=stderr,
        )
        row["elapsed_seconds"] = round(time.time() - start, 2)
        row["worker_stdout_log"] = str(stdout_log)
        row["worker_stderr_log"] = str(stderr_log)
        return row

    parsed = None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    if parsed is None:
        parsed = {
            "model_key": model_key,
            "project": MODELS[model_key].project_name,
            "category": MODELS[model_key].category,
            "plan_number": MODELS[model_key].plan_number,
            "requested_blocks": requested_blocks,
            "accepted_blocks": None,
            "status": "worker_parse_failed",
            "ras_compute_success": False,
            "ras_behavior": "probe_error",
            "error": f"exit={proc.returncode}; no JSON result parsed",
        }
    parsed["worker_exit_code"] = proc.returncode
    parsed["stdout_tail"] = stdout[-2000:]
    parsed["stderr_tail"] = stderr[-2000:]
    parsed["worker_stdout_log"] = str(stdout_log)
    parsed["worker_stderr_log"] = str(stderr_log)
    return parsed


def _write_results(rows: list[dict[str, Any]]) -> None:
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "model_key",
        "project",
        "category",
        "plan_number",
        "ras_version",
        "requested_blocks",
        "accepted_blocks",
        "ras_behavior",
        "ras_compute_success",
        "compute_messages_complete",
        "plain_geometry_blocks",
        "geometry_hdf_exists",
        "hdf_values_shape",
        "data_errors",
        "target_river",
        "target_reach",
        "target_rs",
        "target_existing_blocks",
        "geometry_file",
        "geometry_hdf",
        "plan_hdf",
        "run_dir",
        "artifact_run_dir",
        "elapsed_seconds",
        "status",
        "error",
    ]

    for path in (RESULTS_CSV, ARTIFACT_RESULTS_CSV):
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    ARTIFACT_RESULTS_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def run_orchestrator(
    model_keys: list[str],
    counts: list[int],
    timeout_seconds: int,
    clean: bool,
) -> list[dict[str, Any]]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    if clean:
        LOCAL_WORK_ROOT.mkdir(parents=True, exist_ok=True)
        _ensure_safe_delete(RUN_ROOT, LOCAL_WORK_ROOT)
        _ensure_safe_delete(ARTIFACT_RUN_ROOT, ARTIFACT_ROOT)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)

    RasExamples.get_example_projects("6.6")
    rows: list[dict[str, Any]] = []
    for model_key in model_keys:
        for requested_blocks in counts:
            print(f"RUN model={model_key} requested_blocks={requested_blocks}", flush=True)
            row = _run_worker_subprocess(
                model_key,
                requested_blocks,
                RUN_ROOT,
                timeout_seconds,
            )
            row["ras_behavior"] = _classify_behavior(row)
            row["artifact_run_dir"] = _artifact_run_dir(row)
            rows.append(row)
            print(
                "RESULT "
                f"model={model_key} requested={requested_blocks} "
                f"accepted={row.get('accepted_blocks')} "
                f"behavior={row.get('ras_behavior')} "
                f"elapsed={row.get('elapsed_seconds')}",
                flush=True,
            )

    _mirror_run_outputs(RUN_ROOT)
    _write_results(rows)
    print(f"Wrote {RESULTS_CSV}")
    print(f"Wrote {ARTIFACT_RESULTS_CSV}")
    print(f"Wrote {ARTIFACT_RESULTS_JSON}")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--model", choices=sorted(MODELS), help="Model key")
    parser.add_argument("--requested-blocks", type=int, help="Requested Manning's n block count")
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=sorted(MODELS),
        default=sorted(MODELS),
        help="Model keys to run in orchestrator mode",
    )
    parser.add_argument(
        "--counts",
        nargs="+",
        type=int,
        default=DEFAULT_COUNTS,
        help="Requested block counts to test",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--no-clean", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker:
        if not args.model or args.requested_blocks is None:
            raise SystemExit("--worker requires --model and --requested-blocks")
        run_worker(args.model, args.requested_blocks, args.run_root)
    else:
        run_orchestrator(
            args.models,
            args.counts,
            args.timeout_seconds,
            clean=not args.no_clean,
        )


if __name__ == "__main__":
    main()
