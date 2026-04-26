from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ras_commander import GeomPreprocessor, RasPrj, RasUtils, init_ras_project


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = Path(
    os.environ.get("RAS_COMMANDER_EBFE_ROOT", r"H:\Testing\eBFE Model Organization")
)
DEFAULT_OUTPUT_DIR = (
    DEFAULT_WORKSPACE / "Validation" / "ebfe_delivery" / "preprocessor_validation"
)

STUDY_ROOTS = {
    "lower-colorado": DEFAULT_WORKSPACE
    / "Organized"
    / "LowerColoradoCummins_12090301"
    / "RAS Model",
    "lower-colorado-cummins": DEFAULT_WORKSPACE
    / "Organized"
    / "LowerColoradoCummins_12090301"
    / "RAS Model",
    "rio-hondo": DEFAULT_WORKSPACE / "Organized" / "RioHondo_13060008" / "RAS Model",
    "spring-creek": DEFAULT_WORKSPACE / "Organized" / "SpringCreek_12040102" / "RAS Model",
    "upper-guadalupe": DEFAULT_WORKSPACE
    / "Organized"
    / "UpperGuadalupe_12100201"
    / "RAS Model",
    "north-galveston-bay": DEFAULT_WORKSPACE
    / "Organized"
    / "NorthGalvestonBay_12040203"
    / "RAS Model",
    "lower-brazos": DEFAULT_WORKSPACE / "Organized" / "LowerBrazos_12070104" / "RAS Model",
    "amite": DEFAULT_WORKSPACE / "Organized" / "Amite_08070202" / "RAS Model",
    "tickfaw": DEFAULT_WORKSPACE / "Organized" / "Tickfaw_08070203" / "RAS Model",
    "lake-maurepas": DEFAULT_WORKSPACE / "Organized" / "LakeMaurepas_08070204" / "RAS Model",
}

STUDY_RAS_VERSIONS = {
    "lower-colorado": "6.6",
    "lower-colorado-cummins": "6.6",
    "rio-hondo": "6.6",
    "spring-creek": "5.0.7",
    "upper-guadalupe": "6.3.1",
    "north-galveston-bay": "5.0.7",
    "lower-brazos": "6.6",
    "amite": "5.0.7",
    "tickfaw": "5.0.7",
    "lake-maurepas": "5.0.7",
}


def study_label_from_root(root_path: Path) -> str:
    """Infer a stable study label for custom RAS Model roots."""
    normalized = str(root_path).replace("/", "\\").lower()
    path_labels = {
        "lowercoloradocummins_12090301": "lower-colorado",
        "riohondo_13060008": "rio-hondo",
        "springcreek_12040102": "spring-creek",
        "upperguadalupe_12100201": "upper-guadalupe",
        "northgalvestonbay_12040203": "north-galveston-bay",
        "lowerbrazos_12070104": "lower-brazos",
        "amite_08070202": "amite",
        "tickfaw_08070203": "tickfaw",
        "lakemaurepas_08070204": "lake-maurepas",
    }
    compact = normalized.replace("-", "").replace("_", "").replace(" ", "")
    for needle, label in path_labels.items():
        if needle.lower().replace("_", "") in compact:
            return label
    if root_path.name.lower() == "ras model":
        return root_path.parent.name
    return root_path.name


def rel_path(path: Path) -> str:
    for base in (ROOT, DEFAULT_WORKSPACE):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def absolute_preserve_drive(path: Path) -> Path:
    """Return an absolute path without expanding mapped drives to UNC paths."""
    return Path(os.path.abspath(path))


def normalize_path_list(paths: list[Path]) -> list[str]:
    return [rel_path(Path(path)) for path in paths]


def result_to_dict(result: Any) -> dict[str, Any]:
    payload = asdict(result)
    payload["compute_message_paths"] = normalize_path_list(
        result.compute_message_paths
    )
    payload["artifact_paths"] = normalize_path_list(result.artifact_paths)
    return payload


def get_requested_roots(args: argparse.Namespace) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    requested_studies = args.study
    if requested_studies is None:
        requested_studies = [] if args.root else ["lower-colorado", "rio-hondo"]

    for study in requested_studies:
        key = study.lower()
        if key == "all":
            for slug in (
                "lower-colorado",
                "rio-hondo",
                "spring-creek",
                "upper-guadalupe",
                "north-galveston-bay",
                "lower-brazos",
                "amite",
                "tickfaw",
                "lake-maurepas",
            ):
                roots[slug] = STUDY_ROOTS[slug]
            continue
        if key not in STUDY_ROOTS:
            raise ValueError(
                f"Unknown study '{study}'. Known studies: {', '.join(sorted(STUDY_ROOTS))}, all"
            )
        roots[key] = STUDY_ROOTS[key]

    for root in args.root or []:
        root_path = absolute_preserve_drive(Path(root))
        roots[study_label_from_root(root_path)] = root_path

    return roots


def discover_projects(root: Path, max_depth: int) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    projects = RasUtils.find_valid_ras_folders(
        root,
        max_depth=max_depth,
        return_project_info=True,
    )
    return sorted(projects, key=lambda item: str(item["folder"]).lower())


def plan_geometry_key(row: Any) -> str:
    for column_name in ("geometry_number", "Geom File"):
        if column_name in row and row[column_name] is not None:
            digits = "".join(ch for ch in str(row[column_name]) if ch.isdigit())
            if digits:
                return digits.zfill(2)
    return "unknown"


def select_plans(
    ras_obj: RasPrj,
    plan_strategy: str,
    requested_plan: str | None,
) -> list[str]:
    if requested_plan:
        return [str(requested_plan).zfill(2)]

    plan_df = ras_obj.plan_df.copy()
    if plan_df.empty or "plan_number" not in plan_df.columns:
        return []

    plan_df["plan_number"] = plan_df["plan_number"].astype(str).str.zfill(2)
    if "full_path" in plan_df.columns:
        plan_df = plan_df[
            plan_df["full_path"].apply(lambda value: bool(value) and Path(str(value)).exists())
        ]
    if "Geom Path" in plan_df.columns:
        plan_df = plan_df[
            plan_df["Geom Path"].apply(lambda value: bool(value) and Path(str(value)).exists())
        ]
    if "Flow Path" in plan_df.columns:
        plan_df = plan_df[
            plan_df["Flow Path"].apply(lambda value: bool(value) and Path(str(value)).exists())
        ]
    if plan_df.empty:
        return []

    plan_df = plan_df.sort_values("plan_number")
    if "HDF_Results_Path" in plan_df.columns:
        plan_df["_has_existing_hdf"] = plan_df["HDF_Results_Path"].apply(
            lambda value: bool(value) and Path(str(value)).exists()
        )
        plan_df = plan_df.sort_values(
            ["_has_existing_hdf", "plan_number"],
            ascending=[True, True],
        )

    if plan_strategy == "all-plans":
        return list(plan_df["plan_number"])

    selected = []
    seen_geometries = set()
    for _, row in plan_df.iterrows():
        geom_key = plan_geometry_key(row)
        if geom_key in seen_geometries:
            continue
        selected.append(str(row["plan_number"]).zfill(2))
        seen_geometries.add(geom_key)
    return selected


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


def run_project(
    study: str,
    project_info: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    project_folder = Path(project_info["folder"])
    project_record: dict[str, Any] = {
        "study": study,
        "project_name": project_info.get("project_name") or project_folder.name,
        "project_folder": rel_path(project_folder),
        "plans": [],
        "status": "pending",
    }

    try:
        ras_obj = RasPrj()
        ras_version = args.ras_version or STUDY_RAS_VERSIONS.get(study, "6.6")
        init_ras_project(
            project_folder,
            ras_version,
            ras_object=ras_obj,
            load_results_summary=False,
        )

        selected_plans = select_plans(ras_obj, args.plan_strategy, args.plan)
        project_record["selected_plans"] = selected_plans
        project_record["plan_count"] = len(ras_obj.plan_df)

        if args.dry_run:
            project_record["status"] = "dry_run"
            return project_record

        project_success = True
        for plan_number in selected_plans:
            result = GeomPreprocessor.run_geometry_preprocessor(
                plan_number,
                ras_object=ras_obj,
                max_wait=args.max_wait,
                force=not args.no_force,
                clear_messages=True,
                clear_geompre=args.clear_geompre,
                restore_plan_settings=True,
            )
            plan_payload = result_to_dict(result)
            project_record["plans"].append(plan_payload)

            if result.success:
                print(
                    f"PASS {study}: {project_folder.name} plan {plan_number} "
                    f"geom {result.geometry_number} ({result.elapsed_seconds:.1f}s)"
                )
            else:
                project_success = False
                print(
                    f"FAIL {study}: {project_folder.name} plan {plan_number} "
                    f"geom {result.geometry_number}: {result.error}"
                )
                if args.stop_on_failure:
                    break

        project_record["status"] = "passed" if project_success else "failed"
        return project_record

    except Exception as exc:
        project_record["status"] = "failed"
        project_record["error"] = str(exc)
        print(f"FAIL {study}: {project_folder.name}: {exc}")
        return project_record


def status_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        status = record.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def write_reports(
    records: list[dict[str, Any]],
    output_dir: Path,
    timestamp: str,
    roots: dict[str, Path],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"geometry_preprocessor_validation_{timestamp}.json"
    md_path = output_dir / f"geometry_preprocessor_validation_{timestamp}.md"

    payload = {
        "generated_at": timestamp,
        "records": records,
        "status_counts": status_counts(records),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")

    for study, root in roots.items():
        study_records = [record for record in records if record["study"] == study]
        if not study_records:
            continue
        study_dir = root.parent if root.name.lower() == "ras model" else root
        agent_dir = study_dir / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "validation_report.md").write_text(
            render_markdown(
                {
                    "generated_at": timestamp,
                    "records": study_records,
                    "status_counts": status_counts(study_records),
                },
                title=f"{study} Geometry Preprocessor Validation",
            ),
            encoding="utf-8",
        )

    return json_path, md_path


def render_markdown(payload: dict[str, Any], title: str = "Geometry Preprocessor Validation") -> str:
    counts = payload["status_counts"]
    lines = [
        f"# {title}",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Summary",
        "",
    ]
    for status in sorted(counts):
        lines.append(f"- `{status}`: {counts[status]}")

    lines.extend(
        [
            "",
            "## Projects",
            "",
            "| Study | Project | Status | Plans | First Error |",
            "|---|---|---:|---:|---|",
        ]
    )

    for record in payload["records"]:
        first_error = record.get("error", "")
        for plan in record.get("plans", []):
            if plan.get("error"):
                first_error = plan["error"]
                break
        plan_count = len(record.get("plans", [])) or len(record.get("selected_plans", []))
        lines.append(
            "| {study} | `{project}` | `{status}` | {plans} | {error} |".format(
                study=record["study"],
                project=record["project_folder"],
                status=record.get("status", "unknown"),
                plans=plan_count,
                error=(first_error or "").replace("|", "\\|"),
            )
        )

    failed = [
        record for record in payload["records"] if record.get("status") == "failed"
    ]
    if failed:
        lines.extend(["", "## Failures", ""])
        for record in failed:
            lines.append(f"### {record['study']} - {record['project_folder']}")
            if record.get("error"):
                lines.append(f"- Project error: {record['error']}")
            for plan in record.get("plans", []):
                if not plan.get("success"):
                    lines.append(
                        "- Plan `{plan}` geometry `{geom}`: {error}".format(
                            plan=plan.get("plan_number"),
                            geom=plan.get("geometry_number"),
                            error=plan.get("error"),
                        )
                    )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sequentially validate eBFE HEC-RAS projects by running the "
            "ras-commander geometry preprocessor workflow and reviewing "
            "detailed compute messages."
        )
    )
    parser.add_argument(
        "--study",
        nargs="+",
        default=None,
        help=(
            "Study slug(s) to run: lower-colorado, rio-hondo, spring-creek, "
            "upper-guadalupe, north-galveston-bay, lower-brazos, amite, "
            "tickfaw, lake-maurepas, all."
            " If omitted with --root, only the custom root(s) are scanned."
        ),
    )
    parser.add_argument(
        "--root",
        action="append",
        help="Additional custom RAS Model root to scan. May be repeated.",
    )
    parser.add_argument(
        "--ras-version",
        default=None,
        help=(
            "HEC-RAS version or explicit Ras.exe path passed to "
            "init_ras_project(). Defaults to the known version for each study."
        ),
    )
    parser.add_argument("--max-depth", type=int, default=10)
    parser.add_argument("--max-wait", type=int, default=7200)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--project-filter", default=None)
    parser.add_argument("--start-after", default=None)
    parser.add_argument(
        "--plan-strategy",
        choices=["one-per-geometry", "all-plans"],
        default="one-per-geometry",
    )
    parser.add_argument("--plan", default=None, help="Run only this plan number in each project.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-force", action="store_true", help="Do not set Run HTab=-1 before running.")
    parser.add_argument("--clear-geompre", action="store_true", help="Delete stale .c## files first.")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.verbose:
        logging.disable(logging.INFO)

    roots = get_requested_roots(args)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    records: list[dict[str, Any]] = []

    for study, root in roots.items():
        projects = discover_projects(root, args.max_depth)
        print(f"{study}: discovered {len(projects)} project(s) under {rel_path(root)}")

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

        for index, project_info in enumerate(selected_projects, start=1):
            folder = Path(project_info["folder"])
            print(f"[{index}/{len(selected_projects)}] {study}: {rel_path(folder)}")
            record = run_project(study, project_info, args)
            records.append(record)
            write_reports(records, output_dir, timestamp, roots)
            if record["status"] == "failed" and args.stop_on_failure:
                json_path, md_path = write_reports(records, output_dir, timestamp, roots)
                print(f"Reports written: {rel_path(json_path)} and {rel_path(md_path)}")
                return 1

    json_path, md_path = write_reports(records, output_dir, timestamp, roots)
    print(f"Reports written: {rel_path(json_path)} and {rel_path(md_path)}")

    counts = status_counts(records)
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
