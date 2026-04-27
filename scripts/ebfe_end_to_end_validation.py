from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WORKSPACE = Path(
    os.environ.get("RAS_COMMANDER_EBFE_ROOT", r"H:\Testing\eBFE Model Organization")
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ras_commander.sources.federal import RasEbfeModels

import ebfe_delivery_audit as delivery_audit
import ebfe_geometry_preprocessor_batch as preprocessor_batch


DEFAULT_MODELS = [
    "rio-hondo",
    "lower-colorado-cummins",
    "spring-creek",
    "north-galveston-bay",
    "upper-guadalupe",
    "eleven-point",
    "amite",
    "tickfaw",
    "lake-maurepas",
    "lower-brazos",
]


def rel_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def absolute_preserve_drive(path: Path) -> Path:
    """Return an absolute path without expanding mapped drives to UNC paths."""
    return Path(os.path.abspath(path))


def model_metadata(model_key: str) -> dict[str, Any]:
    key = RasEbfeModels.normalize_model_key(model_key)
    return dict(RasEbfeModels._MODEL_REGISTRY[key])


def requested_model_keys(args: argparse.Namespace) -> list[str]:
    requested = args.models or DEFAULT_MODELS
    if len(requested) == 1 and requested[0].lower() == "all":
        requested = list(RasEbfeModels._MODEL_REGISTRY)
    return [RasEbfeModels.normalize_model_key(item) for item in requested]


def organizer_kwargs(model_key: str, args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}

    if model_key in {
        "spring-creek",
        "north-galveston-bay",
        "upper-guadalupe",
        "eleven-point",
        "lower-brazos",
        "amite",
        "tickfaw",
        "lake-maurepas",
    }:
        kwargs["validate_dss"] = args.validate_dss

    if model_key == "north-galveston-bay":
        kwargs["extract_ras_nested"] = not args.no_extract_ras_nested

    if model_key == "lower-colorado-cummins" and args.lower_colorado_sample:
        kwargs["river"] = "Rabbs Creek-Colorado River"
        kwargs["reach"] = "SHILOH BRANCH"
        kwargs["validate"] = args.validate_init

    if model_key == "rio-hondo":
        kwargs["validate"] = args.validate_init

    if model_key == "lower-brazos":
        kwargs["download_components"] = args.download_lower_brazos_components
        if args.lower_brazos_components:
            kwargs["components"] = args.lower_brazos_components

    if model_key == "amite":
        kwargs["skip_output"] = args.skip_amite_output

    return kwargs


def organized_path_for_model(model_key: str, output_root: Path) -> Path:
    metadata = model_metadata(model_key)
    return output_root / str(metadata["output_name"])


def ras_version_for_model(model_key: str, args: argparse.Namespace) -> str:
    if args.ras_version:
        return args.ras_version
    metadata = model_metadata(model_key)
    return str(metadata["ras_version"])


def organize_models(
    model_keys: list[str],
    args: argparse.Namespace,
) -> dict[str, Path]:
    organized: dict[str, Path] = {}
    for model_key in model_keys:
        output_path = organized_path_for_model(model_key, args.output_root)
        if args.skip_organize:
            organized[model_key] = output_path
            print(f"Skipping organization for {model_key}: {rel_path(output_path)}")
            continue

        print(f"\n=== Organizing {model_key} ===")
        organized[model_key] = RasEbfeModels.organize_model(
            model_key,
            download_root=args.download_root,
            output_root=args.output_root,
            **organizer_kwargs(model_key, args),
        )
    return organized


def make_preprocessor_args(
    args: argparse.Namespace,
    ras_version: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        ras_version=ras_version,
        plan_strategy=args.plan_strategy,
        plan=args.plan,
        dry_run=args.dry_run_preprocessor,
        max_wait=args.max_wait,
        no_force=args.no_force,
        clear_geompre=args.clear_geompre,
        stop_on_failure=args.stop_on_failure,
        project_filter=args.project_filter,
        start_after=args.start_after,
    )


def select_projects(
    projects: list[dict[str, Any]],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    state = {"past_start_after": args.start_after is None}
    selected = [
        project
        for project in projects
        if preprocessor_batch.should_include_project(
            project,
            args.project_filter,
            args.start_after,
            state,
        )
    ]
    if args.limit is not None:
        selected = selected[: args.limit]
    return selected


def run_preprocessor(
    model_keys: list[str],
    organized_paths: dict[str, Path],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], Path | None, Path | None]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.report_root / "preprocessor_validation"
    records: list[dict[str, Any]] = []
    roots: dict[str, Path] = {}

    for model_key in model_keys:
        ras_root = organized_paths[model_key] / "RAS Model"
        roots[model_key] = ras_root
        projects = preprocessor_batch.discover_projects(ras_root, args.max_depth)
        selected = select_projects(projects, args)
        print(
            f"{model_key}: discovered {len(projects)} project(s), "
            f"selected {len(selected)} under {rel_path(ras_root)}"
        )

        if not selected:
            continue

        pp_args = make_preprocessor_args(
            args,
            ras_version_for_model(model_key, args),
        )
        for index, project_info in enumerate(selected, start=1):
            folder = Path(project_info["folder"])
            print(f"[{index}/{len(selected)}] {model_key}: {rel_path(folder)}")
            record = preprocessor_batch.run_project(model_key, project_info, pp_args)
            records.append(record)
            preprocessor_batch.write_reports(records, output_dir, timestamp, roots)
            if record["status"] == "failed" and args.stop_on_failure:
                json_path, md_path = preprocessor_batch.write_reports(
                    records,
                    output_dir,
                    timestamp,
                    roots,
                )
                return records, json_path, md_path

    if not records:
        return records, None, None

    json_path, md_path = preprocessor_batch.write_reports(
        records,
        output_dir,
        timestamp,
        roots,
    )
    return records, json_path, md_path


def audit_models(
    model_keys: list[str],
    organized_paths: dict[str, Path],
    args: argparse.Namespace,
) -> tuple[Path, Path]:
    studies = []
    for model_key in model_keys:
        study_root = organized_paths[model_key]
        if not study_root.exists():
            continue
        study_area = str(model_metadata(model_key)["study_area"])
        studies.append(delivery_audit.audit_organized_study(study_area, study_root))

    report_paths = sorted(
        (args.report_root / "preprocessor_validation").glob(
            "geometry_preprocessor_validation_*.json"
        )
    )
    delivery_audit.apply_preprocessor_records(studies, report_paths)

    args.report_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = args.report_root / f"e2e_delivery_audit_{timestamp}.md"
    json_path = args.report_root / f"e2e_delivery_audit_{timestamp}.json"

    md_path.write_text(
        delivery_audit.build_summary_markdown(studies),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps([asdict(study) for study in studies], indent=2),
        encoding="utf-8",
    )
    return md_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end eBFE validation: download/cache, extract, organize, "
            "audit paths, and optionally run ras-commander geometry "
            "preprocessor validation."
        )
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help=(
            "Models to process. Use slugs such as spring-creek, "
            "north-galveston-bay, upper-guadalupe, rio-hondo, "
            "lower-colorado-cummins, eleven-point, lower-brazos, "
            "amite, tickfaw, lake-maurepas, or all."
        ),
    )
    parser.add_argument(
        "--download-root",
        type=Path,
        default=DEFAULT_WORKSPACE / "Downloads",
        help="Base folder for raw downloads and extracted source archives.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_WORKSPACE / "Organized",
        help="Base folder for organized delivery folders.",
    )
    parser.add_argument(
        "--report-root",
        type=Path,
        default=DEFAULT_WORKSPACE / "Validation" / "ebfe_delivery",
        help="Base folder for audit and preprocessor reports.",
    )
    parser.add_argument("--skip-organize", action="store_true")
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--run-preprocessor", action="store_true")
    parser.add_argument("--dry-run-preprocessor", action="store_true")
    parser.add_argument("--validate-dss", action="store_true")
    parser.add_argument("--validate-init", action="store_true")
    parser.add_argument("--no-extract-ras-nested", action="store_true")
    parser.add_argument("--download-lower-brazos-components", action="store_true")
    parser.add_argument("--lower-brazos-components", nargs="+", default=None)
    parser.set_defaults(skip_amite_output=True)
    parser.add_argument(
        "--download-amite-output",
        action="store_false",
        dest="skip_amite_output",
        help="Download Amite output zips instead of the lighter input-only set.",
    )
    parser.add_argument(
        "--full-lower-colorado",
        action="store_false",
        dest="lower_colorado_sample",
        help="Organize all Lower Colorado reaches instead of the demo reach.",
    )
    parser.add_argument(
        "--ras-version",
        default=None,
        help="Override HEC-RAS version or Ras.exe path for all preprocessor runs.",
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
    parser.add_argument(
        "--plan",
        default=None,
        help=(
            "Optional plan number override. Omit to select one valid plan per "
            "unique geometry."
        ),
    )
    parser.add_argument("--no-force", action="store_true")
    parser.add_argument("--clear-geompre", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.verbose:
        logging.disable(logging.INFO)

    args.download_root = absolute_preserve_drive(args.download_root)
    args.output_root = absolute_preserve_drive(args.output_root)
    args.report_root = absolute_preserve_drive(args.report_root)

    model_keys = requested_model_keys(args)
    print("Models:", ", ".join(model_keys))
    print(f"Download root: {rel_path(args.download_root)}")
    print(f"Output root: {rel_path(args.output_root)}")
    print(f"Report root: {rel_path(args.report_root)}")

    organized = organize_models(model_keys, args)

    records: list[dict[str, Any]] = []
    json_report = None
    md_report = None
    if args.run_preprocessor or args.dry_run_preprocessor:
        records, json_report, md_report = run_preprocessor(model_keys, organized, args)
        if json_report and md_report:
            print(
                "Preprocessor reports: "
                f"{rel_path(json_report)} and {rel_path(md_report)}"
            )
        else:
            print("Preprocessor validation produced no project records.")
    else:
        print("Preprocessor validation skipped. Pass --run-preprocessor to execute it.")

    if not args.skip_audit:
        md_audit, json_audit = audit_models(model_keys, organized, args)
        print(f"Audit reports: {rel_path(md_audit)} and {rel_path(json_audit)}")

    failed = [record for record in records if record.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
