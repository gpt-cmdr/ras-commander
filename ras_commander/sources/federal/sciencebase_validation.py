"""Promotion validation for local USGS ScienceBase HEC-RAS archives."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Optional, Union

import pandas as pd

from ras_commander import get_logger, log_call
from ras_commander.RasCmdr import RasCmdr
from ras_commander.RasMap import RasMap
from ras_commander.RasPrj import RasPrj, init_ras_project
from ras_commander.RasUnsteady import RasUnsteady
from ras_commander.RasUtils import RasUtils
from ras_commander.callbacks import FileLoggerCallback
from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan
from ras_commander.results.ResultsParser import ResultsParser

logger = get_logger(__name__)


class ScienceBaseValidation:
    """Inspect and execute candidate ScienceBase archives before promotion."""

    REPORT_FILENAME = "ras_commander_sciencebase_validation.json"

    @staticmethod
    def _has_value(value: Any) -> bool:
        if value is None:
            return False
        try:
            if pd.isna(value):
                return False
        except (TypeError, ValueError):
            pass
        return bool(str(value).strip())

    @staticmethod
    def _is_enabled(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "-1", "yes"}

    @staticmethod
    def _lexical_absolute(path: Union[str, Path]) -> Path:
        """Return an absolute normalized path without probing the filesystem."""
        return Path(os.path.abspath(Path(path)))

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            ScienceBaseValidation._lexical_absolute(path).relative_to(
                ScienceBaseValidation._lexical_absolute(root)
            )
            return True
        except ValueError:
            return False

    @staticmethod
    def _major_version(ras_version: Union[str, Path]) -> int:
        """Return the leading HEC-RAS major version number."""
        match = re.search(r"\d+", str(ras_version))
        if match is None:
            raise ValueError(f"Cannot determine HEC-RAS version from {ras_version!r}.")
        return int(match.group())

    @staticmethod
    def _write_report(report: dict[str, Any], output_dir: Path) -> None:
        """Write the completed validation report beside the computed project."""
        report_path = output_dir / ScienceBaseValidation.REPORT_FILENAME
        report_path.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("ScienceBase validation report written: %s", report_path.name)
        logger.debug("ScienceBase validation report path: %s", report_path)

    @staticmethod
    def _run_modern_compute(
        project_file: Path,
        ras_version: Union[str, Path],
        plan_number: str,
        output_dir: Path,
        num_cores: int,
    ) -> tuple[bool, dict[str, Any]]:
        """Execute and verify one HEC-RAS 6.x+ plan through ``RasCmdr``."""
        ras_obj = RasPrj()
        init_ras_project(
            project_file,
            ras_version,
            ras_object=ras_obj,
            load_results_summary=False,
            hide_intro=True,
        )
        callback_dir = output_dir.parent / f"{output_dir.name}_logs"
        if callback_dir.exists() and any(callback_dir.iterdir()):
            raise FileExistsError(
                "ScienceBase validation requires a new or empty log directory: "
                f"{callback_dir}"
            )
        result = RasCmdr.compute_plan(
            plan_number,
            dest_folder=output_dir,
            ras_object=ras_obj,
            force_rerun=True,
            num_cores=num_cores,
            verify=True,
            stream_callback=FileLoggerCallback(callback_dir),
        )

        run_obj = RasPrj()
        init_ras_project(
            output_dir,
            ras_version,
            ras_object=run_obj,
            hide_intro=True,
        )
        plan_rows = run_obj.plan_df.loc[
            run_obj.plan_df["plan_number"] == plan_number
        ]
        if len(plan_rows) != 1:
            raise RuntimeError(
                "ScienceBase validation output did not contain exactly one "
                f"plan {plan_number}; found {len(plan_rows)}."
            )
        plan_row = plan_rows.iloc[0]
        result_hdf = Path(plan_row["HDF_Results_Path"])
        messages = ""
        if result_hdf.is_file():
            messages = HdfResultsPlan.get_compute_messages(
                result_hdf,
                ras_object=run_obj,
            )
        else:
            plan_file = Path(plan_row["full_path"])
            message_candidates = (
                Path(str(plan_file) + ".computeMsgs.txt"),
                Path(str(plan_file) + ".comp_msgs.txt"),
                output_dir / f"{run_obj.project_name}.bco{plan_number}",
            )
            for candidate in message_candidates:
                if candidate.is_file():
                    messages = candidate.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    if messages.strip():
                        break
        parsed = ResultsParser.parse_compute_messages(messages)
        runtime = (
            HdfResultsPlan.get_runtime_data(result_hdf, ras_object=run_obj)
            if result_hdf.is_file()
            else None
        )
        compute_verified = (
            bool(result)
            and result_hdf.is_file()
            and ResultsParser.is_successful_completion(messages)
        )
        return compute_verified, {
            **parsed,
            "execution_backend": "RasCmdr",
            "result_hdf": str(result_hdf),
            "result_hdf_exists": result_hdf.is_file(),
            "message_line_count": len(str(messages).splitlines()),
            "runtime": runtime.to_dict(orient="records") if runtime is not None else None,
        }

    @staticmethod
    def _run_legacy_compute(
        project_file: Path,
        source_root: Path,
        ras_version: Union[str, Path],
        plan_number: str,
        output_dir: Path,
        timeout_seconds: int,
    ) -> tuple[bool, dict[str, Any]]:
        """Execute a legacy plan in a bounded ``RasControl`` worker process."""
        from ras_commander.RasControl import RasControl

        relative_project = ScienceBaseValidation._lexical_absolute(
            project_file
        ).relative_to(
            ScienceBaseValidation._lexical_absolute(source_root)
        )
        shutil.copytree(source_root, output_dir, dirs_exist_ok=True)
        copied_project = output_dir / relative_project

        run_obj = RasPrj()
        init_ras_project(
            copied_project,
            ras_version,
            ras_object=run_obj,
            load_results_summary=False,
            hide_intro=True,
        )
        worker_result_path = output_dir / ".sciencebase_legacy_worker.json"
        worker_started_at = time.time()
        command = [
            sys.executable,
            "-m",
            "ras_commander.sources.federal.sciencebase_legacy_worker",
            str(copied_project),
            str(ras_version),
            plan_number,
            str(worker_result_path),
        ]
        worker_timed_out = False
        worker_stdout = ""
        worker_stderr = ""
        worker_returncode: Optional[int] = None
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            worker_returncode = completed.returncode
            worker_stdout = completed.stdout
            worker_stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            worker_timed_out = True
            worker_stdout = (exc.stdout or "").decode(errors="replace") if isinstance(
                exc.stdout, bytes
            ) else (exc.stdout or "")
            worker_stderr = (exc.stderr or "").decode(errors="replace") if isinstance(
                exc.stderr, bytes
            ) else (exc.stderr or "")
            # The worker watchdog owns cleanup of any RAS process after its
            # parent is terminated by subprocess.run().
            try:
                # RasControl's interactive cleanup text can contain Unicode
                # symbols that a detached Windows cp1252 console cannot encode.
                with redirect_stdout(StringIO()):
                    RasControl.cleanup_orphans(interactive=False)
            except Exception as cleanup_error:
                logger.warning(
                    "Legacy worker cleanup check failed after timeout: %s",
                    cleanup_error,
                )

        worker_payload: dict[str, Any] = {}
        if worker_result_path.exists():
            worker_payload = json.loads(worker_result_path.read_text(encoding="utf-8"))
        messages = RasControl.get_comp_msgs(plan_number, ras_object=run_obj)
        controller_messages = list(worker_payload.get("controller_messages", []))
        completion_text = "\n".join([*controller_messages, messages]).lower()
        plan_file = copied_project.parent / f"{copied_project.stem}.p{plan_number}"
        message_candidates = (
            Path(str(plan_file) + ".comp_msgs.txt"),
            Path(str(plan_file) + ".computeMsgs.txt"),
            copied_project.parent / f"{copied_project.stem}.bco{plan_number}",
        )
        fresh_message_file = any(
            path.exists() and path.stat().st_mtime >= worker_started_at - 1.0
            for path in message_candidates
        )
        worker_success = bool(worker_payload.get("success"))
        compute_verified = fresh_message_file and (worker_success or worker_timed_out) and (
            "complete process" in completion_text
            or "computations completed" in completion_text
        )

        plan_row = run_obj.plan_df.loc[
            run_obj.plan_df["plan_number"] == plan_number
        ].iloc[0]
        if ScienceBaseValidation._has_value(plan_row.get("unsteady_number")):
            result_type = "unsteady"
        else:
            result_type = "steady"

        parsed = ResultsParser.parse_compute_messages(messages)
        return compute_verified, {
            **parsed,
            "execution_backend": "RasControl",
            "controller_messages": controller_messages,
            "message_line_count": len(str(messages).splitlines()),
            "result_type": result_type,
            "fresh_message_file": fresh_message_file,
            "worker_success": worker_success,
            "worker_timed_out_after_compute": worker_timed_out,
            "worker_returncode": worker_returncode,
            "worker_stdout_tail": worker_stdout[-2000:],
            "worker_stderr_tail": worker_stderr[-2000:],
        }

    @staticmethod
    def _add_dependency_issue(
        issues: list[dict[str, str]],
        *,
        kind: str,
        raw_path: Any,
        resolved_path: Optional[Any],
        owner: Any,
        project_root: Path,
    ) -> None:
        """Validate one required external dependency and its portability."""
        owner_path = Path(owner)
        raw_text = str(raw_path).strip() if raw_path is not None else ""
        if not raw_text:
            issues.append(
                {
                    "code": "missing_reference",
                    "kind": kind,
                    "owner": str(owner_path),
                    "path": "",
                }
            )
            return

        raw = Path(raw_text)
        resolved = ScienceBaseValidation._lexical_absolute(
            Path(resolved_path)
            if ScienceBaseValidation._has_value(resolved_path)
            else raw if raw.is_absolute() else owner_path.parent / raw
        )

        if raw.is_absolute():
            issues.append(
                {
                    "code": "absolute_reference",
                    "kind": kind,
                    "owner": str(owner_path),
                    "path": raw_text,
                }
            )
        if not ScienceBaseValidation._is_within(resolved, project_root):
            issues.append(
                {
                    "code": "external_reference",
                    "kind": kind,
                    "owner": str(owner_path),
                    "path": str(resolved),
                }
            )
        if not resolved.exists():
            issues.append(
                {
                    "code": "missing_path",
                    "kind": kind,
                    "owner": str(owner_path),
                    "path": str(resolved),
                }
            )

    @staticmethod
    def _inspect_dataframe_paths(
        ras_obj: RasPrj,
        issues: list[dict[str, str]],
        project_root: Path,
    ) -> tuple[list[str], dict[str, int]]:
        """Inspect component paths from initialized project DataFrames."""
        component_frames = {
            "plan": ras_obj.plan_df,
            "geometry": ras_obj.geom_df,
            "steady_flow": ras_obj.flow_df,
            "unsteady_flow": ras_obj.unsteady_df,
        }
        component_counts: dict[str, int] = {}

        for kind, frame in component_frames.items():
            frame = frame if frame is not None else pd.DataFrame()
            component_counts[kind] = len(frame)
            if frame.empty or "full_path" not in frame.columns:
                continue
            for _, row in frame.iterrows():
                path_value = row.get("full_path")
                if not ScienceBaseValidation._has_value(path_value):
                    issues.append(
                        {"code": "missing_reference", "kind": kind, "owner": "", "path": ""}
                    )
                elif not Path(path_value).exists():
                    issues.append(
                        {
                            "code": "missing_path",
                            "kind": kind,
                            "owner": str(path_value),
                            "path": str(path_value),
                        }
                    )
                elif not ScienceBaseValidation._is_within(
                    Path(path_value),
                    project_root,
                ):
                    issues.append(
                        {
                            "code": "external_reference",
                            "kind": kind,
                            "owner": str(path_value),
                            "path": str(
                                ScienceBaseValidation._lexical_absolute(path_value)
                            ),
                        }
                    )

        runnable_plans: list[str] = []
        for _, row in ras_obj.plan_df.iterrows():
            plan_number = str(row.get("plan_number", ""))
            plan_issues = []
            for reference_column, path_column, kind in (
                ("Geom File", "Geom Path", "plan_geometry"),
                ("Flow File", "Flow Path", "plan_flow"),
            ):
                if not ScienceBaseValidation._has_value(row.get(reference_column)):
                    continue
                path_value = row.get(path_column)
                if not ScienceBaseValidation._has_value(path_value):
                    plan_issues.append(
                        {
                            "code": "missing_reference",
                            "kind": kind,
                            "owner": str(row.get("full_path", "")),
                            "path": "",
                        }
                    )
                elif not Path(path_value).exists():
                    plan_issues.append(
                        {
                            "code": "missing_path",
                            "kind": kind,
                            "owner": str(row.get("full_path", "")),
                            "path": str(path_value),
                        }
                    )
            issues.extend(plan_issues)
            plan_path = row.get("full_path")
            if (
                ScienceBaseValidation._has_value(plan_path)
                and Path(plan_path).exists()
                and not plan_issues
            ):
                runnable_plans.append(plan_number)

        return runnable_plans, component_counts

    @staticmethod
    def _inspect_unsteady_dependencies(
        ras_obj: RasPrj,
        issues: list[dict[str, str]],
        project_root: Path,
    ) -> None:
        """Inspect DSS, restart, prior-WS, and gridded-met dependencies."""
        boundaries = ras_obj.boundaries_df
        if boundaries is not None and not boundaries.empty:
            for _, row in boundaries.iterrows():
                if not ScienceBaseValidation._is_enabled(row.get("Use DSS")):
                    continue
                ScienceBaseValidation._add_dependency_issue(
                    issues,
                    kind="boundary_dss",
                    raw_path=row.get("DSS File"),
                    resolved_path=None,
                    owner=row.get("full_path", ras_obj.prj_file),
                    project_root=project_root,
                )

        unsteady = ras_obj.unsteady_df
        if unsteady is None or unsteady.empty:
            return

        for _, row in unsteady.iterrows():
            unsteady_path = Path(row["full_path"])
            restart = RasUnsteady.get_restart_settings(
                unsteady_path,
                ras_object=ras_obj,
            )
            if restart.get("use_restart"):
                ScienceBaseValidation._add_dependency_issue(
                    issues,
                    kind="restart_file",
                    raw_path=restart.get("restart_filename"),
                    resolved_path=None,
                    owner=unsteady_path,
                    project_root=project_root,
                )

            prior_ws = RasUnsteady.get_prior_ws_filename(
                unsteady_path,
                ras_object=ras_obj,
            )
            if prior_ws.get("prior_ws_filename"):
                ScienceBaseValidation._add_dependency_issue(
                    issues,
                    kind="prior_ws_file",
                    raw_path=prior_ws["prior_ws_filename"],
                    resolved_path=None,
                    owner=unsteady_path,
                    project_root=project_root,
                )

            precipitation = RasUnsteady.get_met_precipitation_config(
                unsteady_path,
                ras_object=ras_obj,
            )
            if not precipitation.get("enabled") or precipitation.get("mode") != "Gridded":
                continue
            if precipitation.get("source") == "DSS":
                ScienceBaseValidation._add_dependency_issue(
                    issues,
                    kind="gridded_precipitation_dss",
                    raw_path=precipitation.get("dss_filename"),
                    resolved_path=None,
                    owner=unsteady_path,
                    project_root=project_root,
                )
            elif precipitation.get("source") == "GDAL Raster File(s)":
                raw_path = precipitation.get("gdal_filename") or precipitation.get("gdal_folder")
                ScienceBaseValidation._add_dependency_issue(
                    issues,
                    kind="gridded_precipitation_gdal",
                    raw_path=raw_path,
                    resolved_path=None,
                    owner=unsteady_path,
                    project_root=project_root,
                )

    @staticmethod
    def _inspect_rasmap_dependencies(
        ras_obj: RasPrj,
        issues: list[dict[str, str]],
        project_root: Path,
    ) -> None:
        """Inspect terrain and land-classification references via RasMap APIs."""
        for kind, layers in (
            (
                "terrain",
                RasMap.list_terrain_layers(ras_obj.prj_file, ras_object=ras_obj),
            ),
            (
                "land_classification",
                RasMap.list_land_classification_layers(
                    ras_obj.prj_file,
                    ras_object=ras_obj,
                ),
            ),
        ):
            if layers is None or layers.empty:
                continue
            for _, row in layers.iterrows():
                ScienceBaseValidation._add_dependency_issue(
                    issues,
                    kind=kind,
                    raw_path=row.get("filename"),
                    resolved_path=row.get("resolved_path"),
                    owner=ras_obj.prj_file,
                    project_root=project_root,
                )

        rasmap_df = ras_obj.rasmap_df
        if rasmap_df is None or rasmap_df.empty:
            return
        projection_path = rasmap_df.iloc[0].get("projection_path")
        if ScienceBaseValidation._has_value(projection_path):
            resolved = ScienceBaseValidation._lexical_absolute(projection_path)
            if not resolved.exists():
                issues.append(
                    {
                        "code": "missing_path",
                        "kind": "projection",
                        "owner": str(ras_obj.prj_file),
                        "path": str(resolved),
                    }
                )
            if not ScienceBaseValidation._is_within(resolved, project_root):
                issues.append(
                    {
                        "code": "external_reference",
                        "kind": "projection",
                        "owner": str(ras_obj.prj_file),
                        "path": str(resolved),
                    }
                )

    @staticmethod
    @log_call
    def inspect_project(
        project_file: Union[str, Path],
        ras_version: Union[str, Path],
        *,
        model_slug: Optional[str] = None,
        archive_root: Optional[Union[str, Path]] = None,
    ) -> dict[str, Any]:
        """Inspect all execution dependencies without running HEC-RAS."""
        project_file = Path(project_file)
        project_root = (
            Path(archive_root)
            if archive_root is not None
            else project_file.parent
        )
        project_root = ScienceBaseValidation._lexical_absolute(project_root)
        ras_obj = RasPrj()
        init_ras_project(
            project_file,
            ras_version,
            ras_object=ras_obj,
            load_results_summary=False,
            hide_intro=True,
        )

        issues: list[dict[str, str]] = []
        runnable_plans, component_counts = ScienceBaseValidation._inspect_dataframe_paths(
            ras_obj,
            issues,
            project_root,
        )
        ScienceBaseValidation._inspect_unsteady_dependencies(
            ras_obj,
            issues,
            project_root,
        )
        ScienceBaseValidation._inspect_rasmap_dependencies(
            ras_obj,
            issues,
            project_root,
        )

        return {
            "schema_version": 1,
            "model_slug": model_slug,
            "project_file": str(project_file),
            "archive_root": str(project_root),
            "ras_version": str(ras_version),
            "inspected_at": datetime.now(timezone.utc).isoformat(),
            "paths_validated": not issues,
            "status": "passed" if not issues else "failed",
            "component_counts": component_counts,
            "runnable_plans": runnable_plans,
            "issues": issues,
        }

    @staticmethod
    @log_call
    def inspect_archive(
        archive_root: Union[str, Path],
        ras_version: Union[str, Path],
        *,
        model_slug: Optional[str] = None,
        max_depth: int = 15,
        report_path: Optional[Union[str, Path]] = None,
    ) -> dict[str, Any]:
        """Discover and path-audit every runnable HEC-RAS project in an archive."""
        archive_root = Path(archive_root)
        discovered = RasUtils.find_valid_ras_folders(
            archive_root,
            max_depth=max_depth,
            return_project_info=True,
        )
        project_reports: list[dict[str, Any]] = []
        aggregate_counts = {
            "plan": 0,
            "geometry": 0,
            "steady_flow": 0,
            "unsteady_flow": 0,
        }

        for project in discovered:
            project_file = Path(project["prj_file"])
            try:
                project_report = ScienceBaseValidation.inspect_project(
                    project_file,
                    ras_version,
                    model_slug=model_slug,
                    archive_root=archive_root,
                )
            except Exception as exc:
                project_report = {
                    "schema_version": 1,
                    "model_slug": model_slug,
                    "project_file": str(project_file),
                    "archive_root": str(archive_root),
                    "ras_version": str(ras_version),
                    "inspected_at": datetime.now(timezone.utc).isoformat(),
                    "paths_validated": False,
                    "status": "failed",
                    "component_counts": {
                        "plan": int(project.get("plan_count", 0)),
                        "geometry": 0,
                        "steady_flow": 0,
                        "unsteady_flow": 0,
                    },
                    "runnable_plans": [],
                    "issues": [
                        {
                            "code": "project_initialization_failed",
                            "kind": "project",
                            "owner": str(project_file),
                            "path": str(exc),
                        }
                    ],
                }
            project_reports.append(project_report)
            for component, count in project_report["component_counts"].items():
                aggregate_counts[component] = (
                    aggregate_counts.get(component, 0) + int(count)
                )

        all_issues = [
            {"project_file": report["project_file"], **issue}
            for report in project_reports
            for issue in report["issues"]
        ]
        if not project_reports:
            status = "no_projects"
        elif all(report["paths_validated"] for report in project_reports):
            status = "passed"
        else:
            status = "failed"

        archive_report = {
            "schema_version": 1,
            "model_slug": model_slug,
            "archive_root": str(archive_root),
            "ras_version": str(ras_version),
            "inspected_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "paths_validated": status == "passed",
            "project_count": len(project_reports),
            "component_counts": aggregate_counts,
            "issue_count": len(all_issues),
            "issues": all_issues,
            "projects": project_reports,
        }
        if report_path is not None:
            report_path = Path(report_path)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(archive_report, indent=2, default=str),
                encoding="utf-8",
            )
        return archive_report

    @staticmethod
    @log_call
    def run_verified_compute(
        project_file: Union[str, Path],
        ras_version: Union[str, Path],
        plan_number: str,
        output_dir: Union[str, Path],
        *,
        model_slug: Optional[str] = None,
        archive_root: Optional[Union[str, Path]] = None,
        num_cores: int = 4,
        legacy_timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        """Run a fresh representative plan and write an auditable report."""
        project_file = Path(project_file)
        source_root = (
            Path(archive_root)
            if archive_root is not None
            else project_file.parent
        )
        # Preserve mapped-drive spelling for HEC-RAS. Path.resolve() converts
        # mapped Windows drives to UNC paths, which legacy HEC-RAS COM may hang
        # while opening even though the same project works from the mapped path.
        output_dir = Path(output_dir)
        if ScienceBaseValidation._is_within(output_dir, source_root):
            raise ValueError(
                "ScienceBase validation output must be outside the source "
                f"archive: {output_dir}"
            )
        if output_dir.exists():
            if not output_dir.is_dir():
                raise NotADirectoryError(
                    f"ScienceBase validation output is not a directory: {output_dir}"
                )
            if any(output_dir.iterdir()):
                raise FileExistsError(
                    "ScienceBase validation requires a new or empty isolated "
                    f"output directory: {output_dir}"
                )

        inspection = ScienceBaseValidation.inspect_project(
            project_file,
            ras_version,
            model_slug=model_slug,
            archive_root=archive_root,
        )
        plan_number = str(plan_number).zfill(2)

        report: dict[str, Any] = {
            **inspection,
            "validated_plan": plan_number,
            "validation_output": str(output_dir),
            "compute_verified": False,
            "compute": None,
        }
        if not inspection["paths_validated"]:
            report["status"] = "blocked"
            output_dir.mkdir(parents=True, exist_ok=True)
            ScienceBaseValidation._write_report(report, output_dir)
            return report
        if plan_number not in inspection["runnable_plans"]:
            report["status"] = "blocked"
            report["issues"].append(
                {
                    "code": "plan_not_runnable",
                    "kind": "plan",
                    "owner": str(project_file),
                    "path": plan_number,
                }
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            ScienceBaseValidation._write_report(report, output_dir)
            return report

        if ScienceBaseValidation._major_version(ras_version) < 6:
            compute_verified, compute = ScienceBaseValidation._run_legacy_compute(
                project_file,
                source_root,
                ras_version,
                plan_number,
                output_dir,
                legacy_timeout_seconds,
            )
        else:
            compute_verified, compute = ScienceBaseValidation._run_modern_compute(
                project_file,
                ras_version,
                plan_number,
                output_dir,
                num_cores,
            )
        report["compute_verified"] = compute_verified
        report["status"] = "validated" if compute_verified else "failed"
        report["compute"] = compute
        ScienceBaseValidation._write_report(report, output_dir)
        return report


__all__ = ["ScienceBaseValidation"]
