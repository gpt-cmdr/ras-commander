from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ras_commander import HdfResultsPlan, RasCmdr, RasPrj, RasUtils, init_ras_project
from ras_commander.callbacks import FileLoggerCallback
from ras_commander.results.ResultsParser import ResultsParser


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = Path(
    os.environ.get("RAS_COMMANDER_EBFE_ROOT", r"H:\Testing\eBFE Model Organization")
)
DEFAULT_RIO_ROOT = (
    DEFAULT_WORKSPACE / "Organized" / "RioHondo_13060008" / "RAS Model"
)
DEFAULT_OUTPUT_DIR = (
    DEFAULT_WORKSPACE / "Validation" / "ebfe_delivery" / "steady_plan_validation"
)


def ensure_console_output_safe() -> None:
    """Avoid Windows console encoding crashes from HEC-RAS messages."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def rel_path(path: Path) -> str:
    for base in (ROOT, DEFAULT_WORKSPACE):
        try:
            return str(Path(path).relative_to(base))
        except ValueError:
            continue
    return str(path)


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "project"


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def discover_projects(root: Path, max_depth: int) -> list[dict[str, Any]]:
    if not root.exists():
        raise FileNotFoundError(f"RAS Model root not found: {root}")
    projects = RasUtils.find_valid_ras_folders(
        root,
        max_depth=max_depth,
        return_project_info=True,
    )
    return sorted(projects, key=lambda item: str(item["folder"]).lower())


def should_include_project(
    project_info: dict[str, Any],
    project_filter: str | None,
    start_after: str | None,
    state: dict[str, bool],
) -> bool:
    folder = str(project_info["folder"])
    name = str(project_info.get("project_name") or Path(folder).name)

    if start_after and not state["past_start_after"]:
        if start_after.lower() in folder.lower() or start_after.lower() in name.lower():
            state["past_start_after"] = True
        return False

    if project_filter:
        needle = project_filter.lower()
        return needle in folder.lower() or needle in name.lower()

    return True


def selected_plans(ras_obj: RasPrj, requested_plan: str | None) -> list[str]:
    plan_df = ras_obj.plan_df.copy()
    if plan_df.empty or "plan_number" not in plan_df.columns:
        return []

    plan_df["plan_number"] = plan_df["plan_number"].astype(str).str.zfill(2)
    plan_df = plan_df.sort_values("plan_number")
    if requested_plan:
        requested = str(requested_plan).zfill(2)
        return [requested] if requested in set(plan_df["plan_number"]) else []
    return list(plan_df["plan_number"])


def expected_hdf_path(ras_obj: RasPrj, plan_number: str) -> Path:
    return Path(ras_obj.project_folder) / f"{ras_obj.project_name}.p{plan_number}.hdf"


def summarize_results_row(result: Any) -> dict[str, Any] | None:
    row = getattr(result, "results_df_row", None)
    if row is None:
        return None

    summary: dict[str, Any] = {}
    for key in (
        "plan_number",
        "completed",
        "run_time",
        "runtime_complete_process_hours",
        "vol_error_percent",
        "hdf_path",
        "HDF_Results_Path",
    ):
        if key in row:
            summary[key] = json_safe(row[key])
    return summary


def run_plan(
    ras_obj: RasPrj,
    plan_number: str,
    project_log_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    plan_started = time.time()
    hdf_path = expected_hdf_path(ras_obj, plan_number)
    callback = FileLoggerCallback(project_log_dir)
    record: dict[str, Any] = {
        "plan_number": plan_number,
        "hdf_path": rel_path(hdf_path),
        "log_dir": rel_path(project_log_dir),
        "status": "pending",
    }

    try:
        result = RasCmdr.compute_plan(
            plan_number,
            ras_object=ras_obj,
            clear_geompre=args.clear_geompre,
            force_geompre=args.force_geompre,
            force_rerun=not args.no_force_rerun,
            num_cores=args.num_cores,
            skip_existing=args.skip_existing,
            verify=True,
            stream_callback=callback,
        )
        messages = HdfResultsPlan.get_compute_messages_hdf_only(hdf_path)
        parsed = ResultsParser.parse_compute_messages(messages)
        hdf_exists = hdf_path.exists()
        success = bool(result) and hdf_exists and parsed["completed"] and not parsed["has_errors"]

        record.update(
            {
                "success": success,
                "status": "passed" if success else "failed",
                "hdf_exists": hdf_exists,
                "compute_result_success": bool(result),
                "compute_messages_length": len(messages or ""),
                "compute_messages": parsed,
                "results_df_row": summarize_results_row(result),
                "elapsed_seconds": round(time.time() - plan_started, 2),
            }
        )
    except Exception as exc:
        record.update(
            {
                "success": False,
                "status": "failed",
                "error": str(exc),
                "elapsed_seconds": round(time.time() - plan_started, 2),
            }
        )
    return record


def run_project(
    index: int,
    total: int,
    project_info: dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    project_folder = Path(project_info["folder"])
    project_label = project_info.get("project_name") or project_folder.name
    print(f"[{index}/{total}] {project_label}: {rel_path(project_folder)}", flush=True)

    project_started = time.time()
    record: dict[str, Any] = {
        "project_name": project_label,
        "project_folder": rel_path(project_folder),
        "plans": [],
        "status": "pending",
    }

    try:
        ras_obj = RasPrj()
        init_ras_project(
            project_folder,
            args.ras_version,
            ras_object=ras_obj,
            load_results_summary=False,
        )

        plans = selected_plans(ras_obj, args.plan)
        record["selected_plans"] = plans
        if not plans:
            record["status"] = "failed"
            record["error"] = "No matching steady plans found."
            return record

        project_log_dir = output_dir / "logs" / safe_name(str(project_folder))
        project_log_dir.mkdir(parents=True, exist_ok=True)

        for plan_number in plans:
            plan_record = run_plan(ras_obj, plan_number, project_log_dir, args)
            record["plans"].append(plan_record)
            status = plan_record.get("status", "unknown")
            elapsed = plan_record.get("elapsed_seconds", 0)
            print(f"  plan {plan_number}: {status} in {elapsed}s", flush=True)
            if status == "failed" and args.stop_on_failure:
                break

        record["status"] = (
            "passed"
            if record["plans"] and all(plan.get("success") for plan in record["plans"])
            else "failed"
        )
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
    finally:
        record["elapsed_seconds"] = round(time.time() - project_started, 2)

    return record


def status_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def write_reports(
    records: list[dict[str, Any]],
    output_dir: Path,
    timestamp: str,
    root: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": timestamp,
        "root": rel_path(root),
        "status_counts": status_counts(records),
        "records": records,
    }

    json_path = output_dir / f"steady_plan_validation_{timestamp}.json"
    md_path = output_dir / f"steady_plan_validation_{timestamp}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return json_path, md_path


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Steady Plan Validation",
        "",
        f"Generated: `{payload['generated_at']}`",
        f"Root: `{payload['root']}`",
        "",
        "## Summary",
        "",
    ]
    for status, count in sorted(payload["status_counts"].items()):
        lines.append(f"- `{status}`: {count}")

    lines.extend(
        [
            "",
            "## Projects",
            "",
            "| Project | Status | Plans | First Error |",
            "|---|---:|---:|---|",
        ]
    )

    for record in payload["records"]:
        first_error = record.get("error", "")
        for plan in record.get("plans", []):
            parsed = plan.get("compute_messages", {})
            first_error = plan.get("error") or parsed.get("first_error_line") or first_error
            if first_error:
                break
        lines.append(
            "| `{project}` | `{status}` | {plans} | {error} |".format(
                project=record["project_folder"],
                status=record.get("status", "unknown"),
                plans=len(record.get("plans", [])),
                error=(first_error or "").replace("|", "\\|"),
            )
        )

    failed = [record for record in payload["records"] if record.get("status") == "failed"]
    if failed:
        lines.extend(["", "## Failures", ""])
        for record in failed:
            lines.append(f"### {record['project_name']}")
            if record.get("error"):
                lines.append(f"- Project error: {record['error']}")
            for plan in record.get("plans", []):
                if not plan.get("success"):
                    parsed = plan.get("compute_messages", {})
                    error = plan.get("error") or parsed.get("first_error_line") or "Unknown error"
                    lines.append(f"- Plan `{plan.get('plan_number')}`: {error}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sequentially run organized eBFE 1D steady HEC-RAS plans with "
            "ras-commander and validate detailed compute messages."
        )
    )
    parser.add_argument("--root", default=str(DEFAULT_RIO_ROOT))
    parser.add_argument("--ras-version", default="6.6")
    parser.add_argument("--max-depth", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--project-filter", default=None)
    parser.add_argument("--start-after", default=None)
    parser.add_argument("--plan", default=None, help="Run only this plan number.")
    parser.add_argument("--num-cores", type=int, default=None)
    parser.add_argument("--clear-geompre", action="store_true")
    parser.add_argument("--force-geompre", action="store_true")
    parser.add_argument(
        "--no-force-rerun",
        action="store_true",
        help="Allow ras-commander smart skipping when results are current.",
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    ensure_console_output_safe()
    args = parse_args()
    root = Path(args.root)
    output_dir = Path(args.output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    projects = discover_projects(root, args.max_depth)
    state = {"past_start_after": args.start_after is None}
    selected_projects = [
        project
        for project in projects
        if should_include_project(
            project,
            args.project_filter,
            args.start_after,
            state,
        )
    ]
    if args.limit is not None:
        selected_projects = selected_projects[: args.limit]

    print(f"Discovered {len(projects)} project(s) under {rel_path(root)}", flush=True)
    print(f"Selected {len(selected_projects)} project(s)", flush=True)

    records: list[dict[str, Any]] = []
    for index, project_info in enumerate(selected_projects, start=1):
        record = run_project(index, len(selected_projects), project_info, output_dir, args)
        records.append(record)
        write_reports(records, output_dir, timestamp, root)
        if record["status"] == "failed" and args.stop_on_failure:
            break

    json_path, md_path = write_reports(records, output_dir, timestamp, root)
    print(f"Reports written: {rel_path(json_path)} and {rel_path(md_path)}", flush=True)

    return 1 if status_counts(records).get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
