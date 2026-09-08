from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ras_commander import (
    HdfResultsPlan,
    RasCmdr,
    RasEbfeModels,
    RasPlan,
    RasPrj,
    RasUtils,
    init_ras_project,
)
from ras_commander.callbacks import FileLoggerCallback
from ras_commander.results.ResultsParser import ResultsParser
from ras_commander.sources.base import ModelMetadata, ModelType


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EBFE_ROOT = Path(
    os.environ.get("RAS_COMMANDER_EBFE_ROOT", r"H:\Testing\eBFE")
)
DEFAULT_LEGACY_WORKSPACE = Path(r"H:\Testing\eBFE Model Organization")
DEFAULT_RIO_ROOT = (
    DEFAULT_LEGACY_WORKSPACE / "Organized" / "RioHondo_13060008" / "RAS Model"
)
DEFAULT_OUTPUT_DIR = (
    DEFAULT_LEGACY_WORKSPACE
    / "Validation"
    / "ebfe_delivery"
    / "steady_plan_validation"
)


def ensure_console_output_safe() -> None:
    """Avoid Windows console encoding crashes from HEC-RAS messages."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def rel_path(path: Path) -> str:
    for base in (ROOT, DEFAULT_EBFE_ROOT, DEFAULT_LEGACY_WORKSPACE):
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


def discover_projects(
    root: Path,
    max_depth: int,
    include_nested_projects: bool = False,
) -> list[dict[str, Any]]:
    if not root.exists():
        raise FileNotFoundError(f"RAS Model root not found: {root}")
    projects = RasUtils.find_valid_ras_folders(
        root,
        max_depth=max_depth,
        return_project_info=True,
        include_nested_projects=include_nested_projects,
    )
    return sorted(projects, key=lambda item: str(item["folder"]).lower())


def resolve_study_paths(
    study: str,
    workspace: Path | None,
    timestamp: str,
    output_dir: Path | None,
    run_root: Path | None,
    in_place: bool,
) -> tuple[Path, Path | None, Path]:
    """Resolve organized, run, and report roots from an eBFE study key."""
    metadata = RasEbfeModels.get_model_metadata(study)
    study_workspace = Path(workspace) if workspace is not None else DEFAULT_EBFE_ROOT
    if study_workspace.name != metadata.location:
        study_workspace = study_workspace / metadata.location

    source_root = (
        study_workspace
        / "organized"
        / metadata.name
        / "RAS Model"
    )
    resolved_run_root = None
    if not in_place:
        resolved_run_root = (
            Path(run_root)
            if run_root is not None
            else study_workspace / "runs" / timestamp
        )
    resolved_output_dir = (
        Path(output_dir)
        if output_dir is not None
        else study_workspace / "reports" / "steady_plan_validation" / timestamp
    )
    return source_root, resolved_run_root, resolved_output_dir


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


def apply_study_defaults(
    args: argparse.Namespace,
    metadata: ModelMetadata,
) -> bool:
    """Validate a steady study and apply only its catalogued run defaults."""
    if metadata.model_type != ModelType.STEADY_1D:
        raise ValueError(
            f"Study {metadata.source_id} is {metadata.model_type.value}; "
            "this runner accepts only STEADY_1D studies."
        )

    if args.plan is None and metadata.extra.get("plan_number") is not None:
        args.plan = str(metadata.extra["plan_number"])
    use_catalog_profile_counts = (
        args.expected_profiles is None
        and metadata.extra.get("profiles_per_plan") is not None
    )
    if use_catalog_profile_counts:
        args.expected_profiles = int(metadata.extra["profiles_per_plan"])
        args.expected_profile_exceptions = dict(
            metadata.extra.get("profiles_per_plan_exceptions", {})
        )
    else:
        args.expected_profile_exceptions = {}
    if (
        args.plan_timeout_seconds is None
        and metadata.extra.get("plan_timeout_seconds") is not None
    ):
        args.plan_timeout_seconds = float(
            metadata.extra["plan_timeout_seconds"]
        )
    return args.include_nested_projects or bool(
        metadata.extra.get("nested_project_count")
    )


def expected_profiles_for_project(
    args: argparse.Namespace,
    project_info: dict[str, Any],
) -> int | None:
    """Return the explicit or catalogued profile count for one project."""
    source_folder = Path(
        project_info.get("source_folder", project_info["folder"])
    )
    project_key = f"{source_folder.parent.name}/{source_folder.name}"
    exceptions = getattr(args, "expected_profile_exceptions", {})
    return exceptions.get(project_key, args.expected_profiles)


def expected_hdf_path(ras_obj: RasPrj, plan_number: str) -> Path:
    plan_df = ras_obj.plan_df.copy()
    plan_numbers = plan_df["plan_number"].astype(str).str.zfill(2)
    matches = plan_df.loc[plan_numbers == str(plan_number).zfill(2)]
    if matches.empty:
        raise ValueError(f"Plan {plan_number} was not found in plan_df.")

    row = matches.iloc[0]
    hdf_path = row.get("HDF_Results_Path")
    if hdf_path:
        return Path(str(hdf_path))
    plan_path = row.get("full_path")
    if not plan_path:
        raise ValueError(
            f"Plan {plan_number} has neither HDF_Results_Path nor full_path."
        )
    return Path(f"{plan_path}.hdf")


def steady_profile_count(ras_obj: RasPrj, plan_number: str) -> int | None:
    """Read Number of Profiles from the flow file referenced by plan_df."""
    plan_df = ras_obj.plan_df.copy()
    plan_numbers = plan_df["plan_number"].astype(str).str.zfill(2)
    matches = plan_df.loc[plan_numbers == str(plan_number).zfill(2)]
    if matches.empty:
        return None
    flow_path = matches.iloc[0].get("Flow Path")
    if not flow_path:
        return None
    for line in Path(str(flow_path)).read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        if line.strip().lower().startswith("number of profiles="):
            return int(line.split("=", 1)[1].strip())
    return None


def stage_project(
    project_info: dict[str, Any],
    index: int,
    run_root: Path | None,
) -> dict[str, Any]:
    """Copy one project into a short isolated run folder."""
    if run_root is None:
        return dict(project_info)

    source_folder = Path(project_info["folder"])
    river_name = source_folder.parent.name
    project_name = str(project_info.get("project_name") or source_folder.name)
    destination = run_root / (
        f"{index:04d}_{safe_name(river_name)}_{safe_name(project_name)}"
    )
    if destination.exists():
        raise FileExistsError(
            f"Run folder already exists: {destination}. Use a new --run-root."
        )
    destination.mkdir(parents=True)

    for source_item in source_folder.iterdir():
        destination_item = destination / source_item.name
        if source_item.is_file():
            shutil.copy2(source_item, destination_item)
        elif not any(source_item.rglob("*.prj")):
            shutil.copytree(source_item, destination_item)

    staged = dict(project_info)
    staged["source_folder"] = source_folder
    staged["folder"] = destination
    staged["prj_file"] = destination / Path(project_info["prj_file"]).name
    return staged


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
        profile_count = steady_profile_count(ras_obj, plan_number)
        record["profile_count"] = profile_count
        if (
            args.expected_profiles is not None
            and profile_count != args.expected_profiles
        ):
            raise ValueError(
                f"Expected {args.expected_profiles} steady profiles, "
                f"found {profile_count}."
            )
        RasPlan.update_run_flags(
            plan_number,
            geometry_preprocessor=True,
            post_processor=True,
            ras_object=ras_obj,
        )
        timeout_state: dict[str, Any] = {
            "triggered": False,
            "cancelled": False,
            "error": None,
        }

        def cancel_timed_out_plan() -> None:
            timeout_state["triggered"] = True
            try:
                timeout_state["cancelled"] = RasCmdr.cancel_plan(
                    plan_number,
                    ras_object=ras_obj,
                )
            except Exception as exc:
                timeout_state["error"] = str(exc)

        timeout_timer = None
        if args.plan_timeout_seconds is not None:
            timeout_timer = threading.Timer(
                float(args.plan_timeout_seconds),
                cancel_timed_out_plan,
            )
            timeout_timer.daemon = True
            timeout_timer.start()

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
        finally:
            if timeout_timer is not None:
                timeout_timer.cancel()

        if timeout_state["triggered"]:
            record["timed_out"] = True
            record["timeout_cancelled"] = timeout_state["cancelled"]
            if timeout_state["error"]:
                record["timeout_cancel_error"] = timeout_state["error"]
            raise TimeoutError(
                f"Plan exceeded {args.plan_timeout_seconds:g} seconds; "
                "ras-commander cancellation was "
                f"{'successful' if timeout_state['cancelled'] else 'not confirmed'}."
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
        "source_folder": rel_path(
            Path(project_info.get("source_folder", project_folder))
        ),
        "plans": [],
        "status": "pending",
    }
    project_args = argparse.Namespace(**vars(args))
    project_args.expected_profiles = expected_profiles_for_project(
        args,
        project_info,
    )
    record["expected_profiles"] = project_args.expected_profiles

    try:
        ras_obj = RasPrj()
        init_ras_project(
            project_folder,
            args.ras_version,
            ras_object=ras_obj,
            load_results_summary=False,
            hide_intro=True,
        )

        plans = selected_plans(ras_obj, args.plan)
        record["selected_plans"] = plans
        if not plans:
            record["status"] = "failed"
            record["error"] = "No matching steady plans found."
            return record

        project_log_dir = output_dir / "logs" / (
            f"{index:04d}_{safe_name(str(project_label))}"
        )
        project_log_dir.mkdir(parents=True, exist_ok=True)

        for plan_number in plans:
            plan_record = run_plan(
                ras_obj,
                plan_number,
                project_log_dir,
                project_args,
            )
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
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--study", default=None, help="eBFE slug, alias, or HUC8.")
    source.add_argument("--root", default=None, help="Explicit organized RAS Model root.")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Study workspace; defaults to RAS_COMMANDER_EBFE_ROOT/<HUC8>.",
    )
    parser.add_argument("--run-root", default=None)
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Compute in the organized source folders instead of isolated run copies.",
    )
    parser.add_argument("--ras-version", default="6.6")
    parser.add_argument("--max-depth", type=int, default=10)
    parser.add_argument("--include-nested-projects", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--project-filter", default=None)
    parser.add_argument("--start-after", default=None)
    parser.add_argument(
        "--plan",
        default=None,
        help="Run exactly this plan number; study metadata may provide a default.",
    )
    parser.add_argument(
        "--expected-profiles",
        type=int,
        default=None,
        help="Required steady profile count; study metadata may provide a default.",
    )
    parser.add_argument("--num-cores", type=int, default=None)
    parser.add_argument(
        "--plan-timeout-seconds",
        type=float,
        default=None,
        help=(
            "Cancel an owned plan process after this many seconds; study "
            "metadata may provide a default. Legacy --root runs have no default."
        ),
    )
    parser.add_argument("--clear-geompre", action="store_true")
    parser.add_argument("--force-geompre", action="store_true")
    parser.add_argument(
        "--no-force-rerun",
        action="store_true",
        help="Allow ras-commander smart skipping when results are current.",
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


def main() -> int:
    ensure_console_output_safe()
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.study:
        metadata = RasEbfeModels.get_model_metadata(args.study)
        include_nested_projects = apply_study_defaults(args, metadata)
        root, run_root, output_dir = resolve_study_paths(
            args.study,
            Path(args.workspace) if args.workspace else None,
            timestamp,
            Path(args.output_dir) if args.output_dir else None,
            Path(args.run_root) if args.run_root else None,
            args.in_place,
        )
    else:
        root = Path(args.root or DEFAULT_RIO_ROOT)
        output_dir = Path(args.output_dir or DEFAULT_OUTPUT_DIR)
        run_root = None if args.in_place else Path(
            args.run_root
            or DEFAULT_LEGACY_WORKSPACE / "runs" / "steady_plan_validation" / timestamp
        )
        include_nested_projects = args.include_nested_projects

    projects = discover_projects(
        root,
        args.max_depth,
        include_nested_projects=include_nested_projects,
    )
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
    if run_root is not None:
        print(f"Run copies: {rel_path(run_root)}", flush=True)

    records: list[dict[str, Any]] = []
    for index, project_info in enumerate(selected_projects, start=1):
        try:
            run_project_info = stage_project(project_info, index, run_root)
            record = run_project(
                index,
                len(selected_projects),
                run_project_info,
                output_dir,
                args,
            )
        except Exception as exc:
            record = {
                "project_name": project_info.get("project_name"),
                "project_folder": rel_path(Path(project_info["folder"])),
                "source_folder": rel_path(Path(project_info["folder"])),
                "plans": [],
                "status": "failed",
                "error": str(exc),
            }
        records.append(record)
        if (
            index % max(args.checkpoint_every, 1) == 0
            or record["status"] == "failed"
        ):
            write_reports(records, output_dir, timestamp, root)
        if record["status"] == "failed" and args.stop_on_failure:
            break

    json_path, md_path = write_reports(records, output_dir, timestamp, root)
    print(f"Reports written: {rel_path(json_path)} and {rel_path(md_path)}", flush=True)

    return 1 if status_counts(records).get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
