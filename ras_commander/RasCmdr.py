"""
RasCmdr - Execution operations for running HEC-RAS simulations

This module is part of the ras-commander library and uses a centralized logging configuration.

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs are written to both console and a rotating file handler.
- The default log file is 'ras_commander.log' in the 'logs' directory.
- The default log level is INFO.

To use logging in this module:
1. Use the @log_call decorator for automatic function call logging.
2. For additional logging, use logger.[level]() calls (e.g., logger.info(), logger.debug()).

Example:
    @log_call
    def my_function():
        
        logger.debug("Additional debug information")
        # Function logic here
        
        
-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasCmdr:
- compute_plan()
- cancel_plan()
- compute_parallel()
- compute_test_mode()
        
        
        
"""
import hashlib
import math
import ntpath
import os
import shlex
import shutil
import subprocess
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from itertools import cycle
from numbers import Number
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import pandas as pd

from .ComputeResults import (
    ComputeParallelResult,
    ComputeResult,
    PlanCancellationResult,
    PlanProcessInventory,
    RasProcessQueryError,
    RasProcessRecord,
)
from .Decorators import log_call
from .ExecutionEvidence import (
    ExecutionEvidence,
    inspect_execution_evidence as _inspect_execution_evidence,
)
from .ExecutionArtifacts import (
    PlanExecutionCleanup,
    RemovalFormat,
    ResultFormat,
    finalize_plan_execution_artifacts,
    get_plan_result_artifact_paths,
    infer_execution_result_format,
    prepare_plan_execution_artifacts,
    remove_plan_execution_artifacts as _remove_plan_execution_artifacts,
)
from .LoggingConfig import get_logger
from .RasBco import BcoMonitor
from .RasPlan import RasPlan
from .RasPrj import RasPrj, init_ras_project, ras
from .RasUtils import RasUtils

logger = get_logger(__name__)

_WINDOWS_PROCESS_CONTROL = os.name == "nt"

# Module code starts here



class RasCmdr:
    """
    Static class for HEC-RAS plan execution operations.

    All methods are static and designed to be used without instantiation.

    Methods:
        compute_plan(): Execute a single HEC-RAS plan
        compute_parallel(): Execute multiple plans in parallel using worker folders
        compute_test_mode(): Execute multiple plans sequentially in a test folder
    """

    @staticmethod
    def _resolve_executable_provenance(
        executable: Union[str, Path],
    ) -> tuple[Path, str]:
        """Resolve and hash the exact executable selected for a plan run."""
        candidate = Path(executable).expanduser()
        if not candidate.is_absolute():
            resolved_command = shutil.which(str(candidate))
            if resolved_command is None:
                raise FileNotFoundError(
                    f"HEC-RAS executable could not be resolved: {executable}"
                )
            candidate = Path(resolved_command)
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            raise FileNotFoundError(f"HEC-RAS executable is not a file: {resolved}")
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return resolved, digest.hexdigest()

    @staticmethod
    def _launcher_create_time(pid: int) -> float:
        """Capture PID-reuse-resistant launcher identity immediately after launch."""
        import psutil

        return float(psutil.Process(pid).create_time())

    @staticmethod
    def _get_hdf_path(plan_number: Union[str, Number], ras_object: 'RasPrj') -> Path:
        """
        Get the expected HDF results path for a plan.

        Args:
            plan_number: Plan number (e.g., "01", 1)
            ras_object: RasPrj instance

        Returns:
            Path to the expected HDF file
        """
        plan_num_str = RasUtils.normalize_ras_number(plan_number)

        return Path(ras_object.project_folder) / f"{ras_object.project_name}.p{plan_num_str}.hdf"

    @staticmethod
    @log_call
    def inspect_execution_evidence(
        plan_number: Union[str, Number, Path],
        *,
        ras_object=None,
        result_modified_after: Optional[datetime] = None,
        hash_files: bool = False,
    ) -> ExecutionEvidence:
        """Inspect existing execution evidence without running HEC-RAS or COM.

        The returned record keeps filesystem, HDF, stored-message, process,
        and COM observations distinct.  It derives mechanical completion only;
        parsed errors and warnings remain independent health observations and
        hydraulic acceptance is deliberately outside this contract.

        Args:
            plan_number: Plan number or an existing ``.p##`` plan path.
            ras_object: Explicit initialized :class:`RasPrj`. Uses the package
                global project only when omitted.
            result_modified_after: Optional timezone-aware filesystem
                timestamp threshold. This is not a full RAS input-currency
                check.
            hash_files: Stream-hash inspected source artifacts for provenance.

        Returns:
            Immutable :class:`ExecutionEvidence` with a fixed observation
            registry and JSON-serializable ``to_dict()`` representation.

        Notes:
            This method is read-only. It does not execute or preprocess a plan,
            launch a COM controller, or evaluate hydraulic acceptability.
        """
        return _inspect_execution_evidence(
            plan_number,
            ras_object=ras_object,
            result_modified_after=result_modified_after,
            hash_files=hash_files,
        )

    @staticmethod
    @log_call
    def remove_plan_execution_artifacts(
        plan_number: Union[str, Number, Path],
        *,
        result_format: RemovalFormat,
        include_message_sidecars: bool = False,
        ras_object=None,
    ) -> PlanExecutionCleanup:
        """Permanently remove exact result artifacts owned by one plan.

        Args:
            plan_number: Plan number or existing ``.p##`` plan path.
            result_format: Required selection: ``"hdf"``, ``"legacy"``, or
                ``"both"``. This names the result family to remove.
            include_message_sidecars: Also remove the plan's exact
                ``.comp_msgs.txt``, ``.computeMsgs.txt``, and ``.bco##`` files.
            ras_object: Explicit initialized :class:`RasPrj`. Uses the package
                global project only when omitted.

        Returns:
            Immutable :class:`PlanExecutionCleanup` listing removed and
            already-missing paths.

        Warning:
            Removal is permanent. Geometry HDF, DSS, terrain, and Linux
            ``.tmp.hdf`` preprocessing files are never included.
        """
        return _remove_plan_execution_artifacts(
            plan_number,
            result_format=result_format,
            include_message_sidecars=include_message_sidecars,
            ras_object=ras_object,
        )

    @staticmethod
    def _plan_entries_with_expected_hdf_paths(
        plan_entries: Optional[pd.DataFrame],
        project_folder: Union[str, Path],
        project_name: str,
        plan_numbers: List[Union[str, Number]],
    ) -> pd.DataFrame:
        """
        Return plan metadata with expected HDF paths without rereading the .prj.
        """
        normalized_plan_numbers = [
            RasUtils.normalize_ras_number(plan_number)
            for plan_number in plan_numbers
        ]
        project_folder = Path(project_folder)

        if plan_entries is None or plan_entries.empty:
            cached_plan_entries = pd.DataFrame(
                {"plan_number": normalized_plan_numbers}
            )
        else:
            cached_plan_entries = plan_entries.copy()

        if "plan_number" not in cached_plan_entries.columns:
            cached_plan_entries["plan_number"] = normalized_plan_numbers[:len(
                cached_plan_entries
            )]

        cached_plan_entries["plan_number"] = cached_plan_entries[
            "plan_number"
        ].map(RasUtils.normalize_ras_number)

        for column_name in ("HDF_Results_Path", "full_path"):
            if column_name not in cached_plan_entries.columns:
                cached_plan_entries[column_name] = None

        missing_plan_numbers = [
            plan_number
            for plan_number in normalized_plan_numbers
            if plan_number not in set(cached_plan_entries["plan_number"])
        ]
        if missing_plan_numbers:
            cached_plan_entries = pd.concat(
                [
                    cached_plan_entries,
                    pd.DataFrame(
                        {"plan_number": missing_plan_numbers}
                    ),
                ],
                ignore_index=True,
            )

        for plan_number in normalized_plan_numbers:
            plan_mask = cached_plan_entries["plan_number"] == plan_number
            expected_plan_path = project_folder / f"{project_name}.p{plan_number}"
            expected_hdf_path = Path(f"{expected_plan_path}.hdf")
            cached_plan_entries.loc[
                plan_mask, "full_path"
            ] = str(expected_plan_path)
            cached_plan_entries.loc[
                plan_mask, "HDF_Results_Path"
            ] = str(expected_hdf_path)

        return cached_plan_entries

    @staticmethod
    def _update_results_from_cached_plan_entries(
        ras_object: 'RasPrj',
        plan_numbers: List[Union[str, Number]],
        project_folder: Union[str, Path, None] = None,
        project_name: Optional[str] = None,
        plan_entries: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        Update results_df using cached plan metadata when the .prj is unavailable.
        """
        normalized_plan_numbers = [
            RasUtils.normalize_ras_number(plan_number)
            for plan_number in plan_numbers
        ]
        project_folder = Path(project_folder or ras_object.project_folder)
        project_name = project_name or ras_object.project_name
        cached_plan_entries = (
            plan_entries
            if plan_entries is not None
            else getattr(ras_object, "plan_df", None)
        )

        ras_object.plan_df = RasCmdr._plan_entries_with_expected_hdf_paths(
            cached_plan_entries,
            project_folder,
            project_name,
            normalized_plan_numbers,
        )
        return ras_object.update_results_df(
            plan_numbers=normalized_plan_numbers
        )

    @staticmethod
    def _normalize_requested_plan_numbers(
        plan_number: Union[str, Number, List[Union[str, Number]], None]
    ) -> Optional[List[str]]:
        """
        Normalize user-supplied plan selectors to two-digit plan numbers.
        """
        if plan_number is None:
            return None

        if isinstance(plan_number, (str, Number)):
            requested_plan_numbers = [plan_number]
        else:
            requested_plan_numbers = list(plan_number)

        return [
            RasUtils.normalize_ras_number(requested_plan)
            for requested_plan in requested_plan_numbers
        ]

    @staticmethod
    def _filter_plan_entries(
        plan_entries: pd.DataFrame,
        plan_number: Union[str, Number, List[Union[str, Number]], None]
    ) -> pd.DataFrame:
        """
        Filter plan entries using normalized two-digit plan numbers.
        """
        if plan_number is None:
            return plan_entries

        requested_plan_numbers = RasCmdr._normalize_requested_plan_numbers(
            plan_number
        )
        filtered_plan_entries = plan_entries[
            plan_entries["plan_number"].isin(requested_plan_numbers)
        ].copy()
        available_plan_numbers = set(filtered_plan_entries["plan_number"])
        missing_plan_numbers = [
            requested_plan
            for requested_plan in requested_plan_numbers
            if requested_plan not in available_plan_numbers
        ]

        if missing_plan_numbers:
            logger.warning(
                "Requested plan numbers not found in plan_df after "
                f"normalization: {missing_plan_numbers}"
            )

        filtered_plan_list = list(filtered_plan_entries["plan_number"])
        if len(filtered_plan_list) > 10:
            logger.info(
                "Filtered plans to execute: %s plan(s) (%s ... %s)",
                len(filtered_plan_list),
                ", ".join(map(str, filtered_plan_list[:5])),
                ", ".join(map(str, filtered_plan_list[-3:])),
            )
            logger.debug("Full filtered plan list: %s", filtered_plan_list)
        else:
            logger.info("Filtered plans to execute: %s", filtered_plan_list)
        return filtered_plan_entries

    @staticmethod
    def _get_plan_geometry_number(
        plan_entries: pd.DataFrame,
        plan_number: Union[str, Number]
    ) -> Optional[str]:
        """
        Resolve the geometry number associated with a plan entry.
        """
        normalized_plan_number = RasUtils.normalize_ras_number(plan_number)
        matching_rows = plan_entries[
            plan_entries["plan_number"] == normalized_plan_number
        ]
        if matching_rows.empty:
            return None

        plan_row = matching_rows.iloc[0]
        for column_name in ("geometry_number", "Geom File"):
            value = plan_row.get(column_name)
            if pd.isna(value):
                continue

            digits = "".join(ch for ch in str(value) if ch.isdigit())
            if digits:
                return digits.zfill(2)

        return None

    @staticmethod
    def _get_worker_plan_artifacts(
        worker_folder: Path,
        project_name: str,
        plan_number: str,
        geometry_number: Optional[str] = None
    ) -> List[Path]:
        """
        Collect plan-owned worker artifacts that are safe to consolidate.
        """
        artifact_patterns = [
            f"{project_name}.p{plan_number}",
            f"{project_name}.p{plan_number}.*",
            f"{project_name}.bco{plan_number}",
            f"{project_name}.O{plan_number}",
            f"{project_name}.c{plan_number}",
        ]
        if geometry_number:
            artifact_patterns.append(f"{project_name}.g{geometry_number}.hdf")

        artifact_paths = {}
        for pattern in artifact_patterns:
            for artifact_path in worker_folder.glob(pattern):
                if artifact_path.is_file():
                    artifact_paths[artifact_path.name] = artifact_path

        return [artifact_paths[name] for name in sorted(artifact_paths)]

    @staticmethod
    def _log_execution_results(execution_results: Dict[str, bool]) -> None:
        """
        Log a concise execution summary with per-plan detail at DEBUG.
        """
        if not execution_results:
            logger.info("Execution results: no plans executed")
            return

        successful_plans = [
            str(plan_num)
            for plan_num, success in execution_results.items()
            if success
        ]
        failed_plans = [
            str(plan_num)
            for plan_num, success in execution_results.items()
            if not success
        ]
        total_plans = len(execution_results)

        logger.info(
            "Execution results: %s/%s plan(s) successful",
            len(successful_plans),
            total_plans,
        )
        for plan_num in successful_plans:
            logger.debug("Plan %s: Successful", plan_num)
        if failed_plans:
            logger.warning("Failed plan(s): %s", ", ".join(failed_plans))
            for plan_num in failed_plans:
                logger.debug("Plan %s: Failed", plan_num)

    @staticmethod
    def _copy_worker_artifact(source_path: Path, dest_path: Path) -> bool:
        """
        Atomically replace a destination with a validated worker artifact.

        Copied-folder timestamps are not execution provenance. Once the caller
        has established that a worker plan succeeded, its artifact must win
        regardless of the destination mtime.
        """
        if not source_path.exists() or not source_path.is_file():
            return False
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = dest_path.with_name(
            f".{dest_path.name}.{uuid.uuid4().hex}.ras-commander.tmp"
        )
        try:
            shutil.copy2(source_path, temp_path)
            os.replace(temp_path, dest_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return True

    @staticmethod
    def _artifact_sha256(path: Path) -> str:
        """Hash one staged/published artifact for transaction verification."""
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _publish_plan_artifacts_transaction(
        plan_number: str,
        *,
        source_primary: Path,
        source_sidecars: List[Path],
        geometry_source: Optional[Path],
        output_format: ResultFormat,
        ras_object: 'RasPrj',
        destination_folder: Union[str, Path],
        project_name: str,
    ) -> tuple[bool, Dict[str, Any]]:
        """Publish one plan's same-run evidence as a recoverable transaction."""
        destination = Path(destination_folder).resolve(strict=False)
        normalized_plan = RasUtils.normalize_ras_number(plan_number)
        # Keep the hidden transaction path short enough for non-long-path
        # Windows installations. The destination promotion lock serializes
        # callers, and 64 random bits still make stale-name collision remote.
        token = uuid.uuid4().hex[:16]
        transaction_path = destination / (
            f".rcp-{normalized_plan}-{token}"
        )
        stage_folder = transaction_path / "s"
        backup_folder = transaction_path / "b"
        failed_new_folder = transaction_path / "f"
        transaction_created = False
        failure_stage = "destination_promotion_staging"
        committed_paths: List[Path] = []
        mutated_paths: set[Path] = set()
        rollback_errors: List[Dict[str, Any]] = []
        current_source_path: Optional[Path] = None
        current_destination_path: Optional[Path] = None

        destination_paths = get_plan_result_artifact_paths(
            normalized_plan,
            project_folder=destination,
            project_name=project_name,
        )
        primary_destination = (
            destination_paths.hdf
            if output_format == "hdf"
            else destination_paths.legacy_output
        )
        opposing_destination = (
            destination_paths.legacy_output
            if output_format == "hdf"
            else destination_paths.hdf
        )
        known_sidecars = {
            path.name: path for path in destination_paths.message_sidecars
        }

        source_primary = Path(source_primary)
        if not source_primary.is_file():
            failure_detail = (
                f"Expected {output_format} primary result is missing: "
                f"{source_primary}"
            )
            return False, {
                "failure_stage": "destination_promotion_missing_result",
                "failure_detail": failure_detail,
                "exception_type": "FileNotFoundError",
                "source_path": str(source_primary),
                "destination_path": str(primary_destination),
                "transaction_path": None,
                "retained_transaction_path": None,
                "copied_destination_paths": [],
                "rollback_attempted": False,
                "rollback_confirmed": True,
                "rollback_errors": [],
                "partial_promotion_possible": False,
            }

        publication_entries: List[Dict[str, Any]] = []
        for source in source_sidecars:
            destination_sidecar = known_sidecars.get(source.name)
            if destination_sidecar is None:
                return False, {
                    "failure_stage": "destination_promotion_selection",
                    "failure_detail": (
                        "Worker message sidecar is not in the exact plan "
                        f"allowlist: {source}"
                    ),
                    "exception_type": "ValueError",
                    "source_path": str(source),
                    "destination_path": None,
                    "transaction_path": None,
                    "retained_transaction_path": None,
                    "copied_destination_paths": [],
                    "rollback_attempted": False,
                    "rollback_confirmed": True,
                    "rollback_errors": [],
                    "partial_promotion_possible": False,
                }
            publication_entries.append(
                {
                    "role": "message_sidecar",
                    "source": Path(source),
                    "destination": destination_sidecar,
                }
            )
        if geometry_source is not None:
            geometry_source = Path(geometry_source)
            publication_entries.append(
                {
                    "role": "geometry",
                    "source": geometry_source,
                    "destination": destination / geometry_source.name,
                }
            )
        publication_entries.append(
            {
                "role": "primary",
                "source": source_primary,
                "destination": primary_destination,
            }
        )

        destination_names = [
            entry["destination"].name for entry in publication_entries
        ]
        if len(destination_names) != len(set(destination_names)):
            return False, {
                "failure_stage": "destination_promotion_selection",
                "failure_detail": "Duplicate publication destination selected",
                "exception_type": "ValueError",
                "source_path": None,
                "destination_path": None,
                "transaction_path": None,
                "retained_transaction_path": None,
                "copied_destination_paths": [],
                "rollback_attempted": False,
                "rollback_confirmed": True,
                "rollback_errors": [],
                "partial_promotion_possible": False,
            }

        quarantine_targets = [
            destination_paths.hdf,
            destination_paths.legacy_output,
            *destination_paths.message_sidecars,
        ]
        if geometry_source is not None:
            quarantine_targets.append(destination / geometry_source.name)
        quarantine_targets = list(dict.fromkeys(quarantine_targets))
        prior_state: Dict[Path, Dict[str, Any]] = {}
        backup_paths: Dict[Path, Path] = {}
        staged_paths: Dict[Path, Path] = {}

        def rollback_destination() -> bool:
            if not mutated_paths:
                return True
            try:
                failed_new_folder.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                rollback_errors.append(
                    {
                        "path": str(failed_new_folder),
                        "exception_type": type(exc).__name__,
                        "detail": str(exc),
                    }
                )
                return False

            # First remove every newly published artifact from recognized
            # destination names. Never restore an old primary while any fresh
            # sidecar might remain visible.
            for index, target in enumerate(quarantine_targets):
                if target not in mutated_paths or not target.exists():
                    continue
                try:
                    failed_path = (
                        failed_new_folder / f"{index:02d}-{target.name}"
                    )
                    os.replace(target, failed_path)
                    if target.exists() or not failed_path.is_file():
                        raise RuntimeError(
                            f"Could not quarantine failed publication: {target}"
                        )
                except Exception as exc:
                    rollback_errors.append(
                        {
                            "path": str(target),
                            "exception_type": type(exc).__name__,
                            "detail": str(exc),
                        }
                    )
            if rollback_errors:
                return False

            # Restore both primary families first, then supporting evidence.
            # If either group cannot be restored completely, re-quarantine
            # everything restored so far. This prevents one primary from
            # becoming readable with ambiguous or partial sidecars.
            primary_targets = {
                destination_paths.hdf,
                destination_paths.legacy_output,
            }
            restoration_groups = (
                [
                    target
                    for target in quarantine_targets
                    if (
                        target in mutated_paths
                        and target in primary_targets
                    )
                ],
                [
                    target
                    for target in quarantine_targets
                    if (
                        target in mutated_paths
                        and target not in primary_targets
                    )
                ],
            )
            restored_targets: List[Path] = []

            def requarantine_restored_targets() -> None:
                for target in reversed(restored_targets):
                    backup_path = backup_paths.get(target)
                    try:
                        if backup_path is None:
                            raise FileNotFoundError(
                                f"Backup path unavailable for {target}"
                            )
                        if not target.is_file():
                            raise FileNotFoundError(
                                "Restored artifact disappeared before "
                                f"re-quarantine: {target}"
                            )
                        os.replace(target, backup_path)
                        if target.exists() or not backup_path.is_file():
                            raise RuntimeError(
                                "Could not re-quarantine restored artifact: "
                                f"{target}"
                            )
                    except Exception as exc:
                        rollback_errors.append(
                            {
                                "path": str(target),
                                "exception_type": type(exc).__name__,
                                "detail": str(exc),
                            }
                        )

            for targets in restoration_groups:
                for target in targets:
                    original = prior_state[target]
                    backup_path = backup_paths.get(target)
                    try:
                        if original["existed"]:
                            if (
                                backup_path is None
                                or not backup_path.is_file()
                            ):
                                raise FileNotFoundError(
                                    "Original backup unavailable for "
                                    f"{target}"
                                )
                            os.replace(backup_path, target)
                            restored_targets.append(target)
                            if (
                                not target.is_file()
                                or RasCmdr._artifact_sha256(target)
                                != original["sha256"]
                            ):
                                raise RuntimeError(
                                    "Restored artifact verification failed: "
                                    f"{target}"
                                )
                        elif target.exists():
                            raise RuntimeError(
                                "Originally absent artifact is visible: "
                                f"{target}"
                            )
                    except Exception as exc:
                        rollback_errors.append(
                            {
                                "path": str(target),
                                "exception_type": type(exc).__name__,
                                "detail": str(exc),
                            }
                        )
                if rollback_errors:
                    requarantine_restored_targets()
                    return False

            for target, original in prior_state.items():
                if original["existed"]:
                    if (
                        not target.is_file()
                        or RasCmdr._artifact_sha256(target)
                        != original["sha256"]
                    ):
                        rollback_errors.append(
                            {
                                "path": str(target),
                                "exception_type": "RuntimeError",
                                "detail": (
                                    "Final restored-state verification failed"
                                ),
                            }
                        )
                elif target.exists():
                    rollback_errors.append(
                        {
                            "path": str(target),
                            "exception_type": "RuntimeError",
                            "detail": (
                                "Originally absent artifact is visible after "
                                "rollback"
                            ),
                        }
                    )
            return not rollback_errors

        try:
            destination.mkdir(parents=True, exist_ok=True)
            for target in quarantine_targets:
                if target.parent.resolve(strict=False) != destination:
                    raise ValueError(
                        f"Promotion artifact escapes destination: {target}"
                    )
                if target.exists() and not target.is_file():
                    raise IsADirectoryError(
                        f"Promotion artifact is not a file: {target}"
                    )
                prior_state[target] = {
                    "existed": target.is_file(),
                    "sha256": (
                        RasCmdr._artifact_sha256(target)
                        if target.is_file()
                        else None
                    ),
                }

            transaction_path.mkdir(parents=False, exist_ok=False)
            transaction_created = True
            stage_folder.mkdir()
            backup_folder.mkdir()

            for index, entry in enumerate(publication_entries):
                source = entry["source"]
                current_source_path = source
                current_destination_path = entry["destination"]
                if not source.is_file():
                    raise FileNotFoundError(
                        f"Selected publication source is missing: {source}"
                    )
                before = source.stat()
                before_hash = RasCmdr._artifact_sha256(source)
                stage_path = stage_folder / f"{index:02d}"
                copied = RasCmdr._copy_worker_artifact(source, stage_path)
                if not copied:
                    raise RuntimeError(
                        "Artifact staging copy returned False for "
                        f"{source} -> {stage_path}"
                    )
                after = source.stat()
                after_hash = RasCmdr._artifact_sha256(source)
                if (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before_hash,
                ) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after_hash,
                ):
                    raise RuntimeError(
                        f"Publication source changed while staging: {source}"
                    )
                if RasCmdr._artifact_sha256(stage_path) != before_hash:
                    raise RuntimeError(
                        f"Staged artifact hash mismatch: {source}"
                    )
                entry["sha256"] = before_hash
                entry["stage_path"] = stage_path
                staged_paths[entry["destination"]] = stage_path

            failure_stage = "destination_promotion_quarantine"
            current_source_path = None
            for index, target in enumerate(quarantine_targets):
                current_destination_path = target
                if not prior_state[target]["existed"]:
                    continue
                backup_path = backup_folder / f"{index:02d}-{target.name}"
                backup_paths[target] = backup_path
                os.replace(target, backup_path)
                mutated_paths.add(target)
                if target.exists() or not backup_path.is_file():
                    raise RuntimeError(
                        f"Could not prove artifact quarantine: {target}"
                    )
                if (
                    RasCmdr._artifact_sha256(backup_path)
                    != prior_state[target]["sha256"]
                ):
                    raise RuntimeError(
                        f"Quarantined artifact hash mismatch: {target}"
                    )

            failure_stage = "destination_promotion_commit"
            for entry in publication_entries:
                target = entry["destination"]
                stage_path = entry["stage_path"]
                current_source_path = entry["source"]
                current_destination_path = target
                mutated_paths.add(target)
                os.replace(stage_path, target)
                committed_paths.append(target)
                if not target.is_file():
                    raise FileNotFoundError(
                        f"Committed artifact is missing: {target}"
                    )
                if RasCmdr._artifact_sha256(target) != entry["sha256"]:
                    raise RuntimeError(
                        f"Committed artifact hash mismatch: {target}"
                    )

            failure_stage = "destination_promotion_finalization"
            current_source_path = None
            current_destination_path = opposing_destination
            mutated_paths.add(opposing_destination)
            finalize_plan_execution_artifacts(
                normalized_plan,
                output_format=output_format,
                ras_object=ras_object,
                project_folder=destination,
                project_name=project_name,
            )

            failure_stage = "destination_promotion_verification"
            for entry in publication_entries:
                target = entry["destination"]
                if (
                    not target.is_file()
                    or RasCmdr._artifact_sha256(target) != entry["sha256"]
                ):
                    raise RuntimeError(
                        f"Published artifact verification failed: {target}"
                    )
            source_sidecar_names = {
                source.name for source in source_sidecars
            }
            for sidecar in destination_paths.message_sidecars:
                if sidecar.name not in source_sidecar_names and sidecar.exists():
                    raise RuntimeError(
                        f"Stale message sidecar remains visible: {sidecar}"
                    )
            if opposing_destination.exists():
                raise RuntimeError(
                    "Opposing result remains visible after finalization: "
                    f"{opposing_destination}"
                )

            try:
                shutil.rmtree(transaction_path)
            except OSError as exc:
                logger.warning(
                    "Plan %s promotion committed, but transaction cleanup "
                    "failed at %s: %s",
                    normalized_plan,
                    transaction_path,
                    exc,
                )
            return True, {
                "failure_stage": None,
                "failure_detail": None,
                "exception_type": None,
                "source_path": None,
                "destination_path": None,
                "transaction_path": str(transaction_path),
                "retained_transaction_path": (
                    str(transaction_path)
                    if transaction_path.exists()
                    else None
                ),
                "copied_destination_paths": [
                    str(path) for path in committed_paths
                ],
                "rollback_attempted": False,
                "rollback_confirmed": None,
                "rollback_errors": [],
                "partial_promotion_possible": False,
            }
        except Exception as exc:
            rollback_attempted = bool(mutated_paths)
            rollback_confirmed = rollback_destination()
            if rollback_confirmed and transaction_created:
                try:
                    shutil.rmtree(transaction_path)
                except OSError as cleanup_exc:
                    rollback_errors.append(
                        {
                            "path": str(transaction_path),
                            "exception_type": type(cleanup_exc).__name__,
                            "detail": str(cleanup_exc),
                        }
                    )
            retained_transaction_path = (
                str(transaction_path)
                if transaction_path.exists()
                else None
            )
            artifact_manifest = [
                {
                    "role": entry["role"],
                    "source_path": str(entry["source"]),
                    "destination_path": str(entry["destination"]),
                    "staged_path": (
                        str(entry["stage_path"])
                        if "stage_path" in entry
                        else None
                    ),
                }
                for entry in publication_entries
            ]
            quarantine_manifest = [
                {
                    "destination_path": str(target),
                    "prior_existed": prior_state.get(target, {}).get(
                        "existed"
                    ),
                    "prior_sha256": prior_state.get(target, {}).get(
                        "sha256"
                    ),
                    "backup_path": (
                        str(backup_paths[target])
                        if target in backup_paths
                        else None
                    ),
                }
                for target in quarantine_targets
            ]
            return False, {
                "failure_stage": failure_stage,
                "failure_detail": f"{type(exc).__name__}: {exc}",
                "exception_type": type(exc).__name__,
                "source_path": (
                    str(current_source_path)
                    if current_source_path is not None
                    else None
                ),
                "destination_path": (
                    str(current_destination_path)
                    if current_destination_path is not None
                    else None
                ),
                "transaction_path": (
                    str(transaction_path) if transaction_created else None
                ),
                "retained_transaction_path": retained_transaction_path,
                "copied_destination_paths": [
                    str(path) for path in committed_paths
                ],
                "staged_paths_remaining": [
                    str(path)
                    for path in staged_paths.values()
                    if path.exists()
                ],
                "backup_paths_remaining": [
                    str(path)
                    for path in backup_paths.values()
                    if path.exists()
                ],
                "failed_new_paths_remaining": [
                    str(path)
                    for path in failed_new_folder.glob("*")
                    if path.is_file()
                ] if failed_new_folder.is_dir() else [],
                "artifact_manifest": artifact_manifest,
                "quarantine_manifest": quarantine_manifest,
                "rollback_attempted": rollback_attempted,
                "rollback_confirmed": rollback_confirmed,
                "rollback_errors": rollback_errors,
                "partial_promotion_possible": not rollback_confirmed,
            }

    @staticmethod
    def _destination_promotion_process_gate(
        plan_numbers: List[str],
        *,
        project_folder: Union[str, Path],
        project_name: str,
    ) -> tuple[bool, Dict[str, Any]]:
        """Prove exact-plan destination quiescence before batch promotion.

        A single strict host snapshot is matched against every plan that would
        be promoted.  Reusing one snapshot makes this a batch gate: no plan is
        copied when any destination plan is occupied or when process inventory
        is incomplete.  The returned evidence is detached and JSON-safe so a
        refused promotion can be retained in ``execution_details_by_plan``.
        """
        from ._process_inspection import match_plan_processes, scan_ras_processes

        normalized_plans = sorted(
            {
                RasUtils.normalize_ras_number(plan_number)
                for plan_number in plan_numbers
            }
        )
        destination = Path(project_folder).resolve(strict=False)
        project_path = (
            destination / f"{project_name}.prj"
        ).resolve(strict=False)
        resolution_errors = []
        if not project_path.is_file():
            resolution_errors.append(
                {
                    "plan_number": None,
                    "path": str(project_path),
                    "reason": "destination project file is missing",
                }
            )

        try:
            import psutil

            inventory = scan_ras_processes(psutil_module=psutil)
        except Exception as exc:
            evidence = {
                "complete": False,
                "quiescence_confirmed": None,
                "destination_folder": str(destination),
                "project_path": str(project_path),
                "plan_inventories": {},
                "blocked_plan_numbers": [],
                "global_processes": [],
                "query_errors": [
                    {
                        "pid": None,
                        "operation": "scan_destination_processes",
                        "reason_code": "process_query_failed",
                        "exception_type": type(exc).__name__,
                        "detail": str(exc),
                    }
                ],
                "resolution_errors": resolution_errors,
            }
            return False, evidence

        plan_inventories = {}
        blocked_plan_numbers = []
        plan_inventories_complete = True
        aggregated_query_errors = [
            error.to_dict() for error in inventory.query_errors
        ]
        for plan_number in normalized_plans:
            plan_path = (
                destination / f"{project_name}.p{plan_number}"
            ).resolve(strict=False)
            tmp_hdf_path = (
                destination / f"{project_name}.p{plan_number}.tmp.hdf"
            ).resolve(strict=False)
            if not plan_path.is_file():
                resolution_errors.append(
                    {
                        "plan_number": plan_number,
                        "path": str(plan_path),
                        "reason": "destination plan file is missing",
                    }
                )
            try:
                plan_inventory = match_plan_processes(
                    inventory,
                    plan_number=plan_number,
                    project_path=project_path,
                    plan_path=plan_path,
                    tmp_hdf_path=tmp_hdf_path,
                )
            except Exception as exc:
                match_error = RasProcessQueryError(
                    pid=None,
                    operation="match_destination_plan_processes",
                    reason_code="process_query_failed",
                    exception_type=type(exc).__name__,
                    detail=str(exc),
                )
                plan_inventory = PlanProcessInventory(
                    observed_at=inventory.observed_at,
                    plan_number=plan_number,
                    project_path=str(project_path),
                    plan_path=str(plan_path),
                    tmp_hdf_path=str(tmp_hdf_path),
                    complete=False,
                    query_errors=(match_error,),
                )
            plan_inventories[plan_number] = plan_inventory.to_dict()
            plan_inventories_complete = bool(
                plan_inventories_complete and plan_inventory.complete
            )
            for error in plan_inventory.query_errors:
                serialized_error = error.to_dict()
                if serialized_error not in aggregated_query_errors:
                    aggregated_query_errors.append(serialized_error)
            if plan_inventory.matched:
                blocked_plan_numbers.append(plan_number)

        complete = bool(
            inventory.complete
            and plan_inventories_complete
            and not resolution_errors
        )
        global_processes = [
            process.to_dict() for process in inventory.processes
        ]
        if global_processes:
            quiescence_confirmed: Optional[bool] = False
        elif complete:
            quiescence_confirmed = True
        else:
            quiescence_confirmed = None
        evidence = {
            "complete": complete,
            "quiescence_confirmed": quiescence_confirmed,
            "destination_folder": str(destination),
            "project_path": str(project_path),
            "plan_inventories": plan_inventories,
            "blocked_plan_numbers": blocked_plan_numbers,
            "global_processes": global_processes,
            "query_errors": aggregated_query_errors,
            "resolution_errors": resolution_errors,
        }
        return quiescence_confirmed is True, evidence

    @staticmethod
    def _acquire_destination_promotion_lock(
        *,
        project_folder: Union[str, Path],
        project_name: str,
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Acquire one cooperative exact-create lock for shared promotion."""
        destination = Path(project_folder).resolve(strict=False)
        lock_path = destination / (
            f".{project_name}.ras-commander-promotion.lock"
        )
        token = uuid.uuid4().hex
        owner_pid = os.getpid()
        created_at = time.time()
        payload = (
            "ras_commander_destination_promotion_lock_v1\n"
            f"token={token}\n"
            f"pid={owner_pid}\n"
            f"created_at={created_at:.9f}\n"
        ).encode("ascii")
        flags = (
            os.O_CREAT
            | os.O_EXCL
            | os.O_RDWR
            | getattr(os, "O_BINARY", 0)
        )
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except FileExistsError:
            try:
                existing_owner = lock_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[:4096]
            except OSError as exc:
                existing_owner = f"<unreadable: {type(exc).__name__}: {exc}>"
            return None, {
                "acquired": False,
                "lock_path": str(lock_path),
                "owner_token": None,
                "owner_pid": None,
                "created_at": None,
                "reason_code": "lock_exists",
                "reason": "destination promotion lock already exists",
                "existing_owner": existing_owner,
            }
        except OSError as exc:
            return None, {
                "acquired": False,
                "lock_path": str(lock_path),
                "owner_token": None,
                "owner_pid": None,
                "created_at": None,
                "reason_code": "lock_creation_failed",
                "reason": f"lock creation failed: {type(exc).__name__}: {exc}",
                "existing_owner": None,
            }
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        except Exception as exc:
            os.close(descriptor)
            removed = False
            try:
                if lock_path.read_bytes() == payload:
                    lock_path.unlink()
                    removed = True
            except OSError:
                pass
            return None, {
                "acquired": False,
                "lock_path": str(lock_path),
                "owner_token": token,
                "owner_pid": owner_pid,
                "created_at": created_at,
                "reason_code": "lock_initialization_failed",
                "reason": (
                    "lock initialization failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                "existing_owner": None,
                "partial_lock_removed": removed,
            }
        lease = {
            "descriptor": descriptor,
            "path": lock_path,
            "token": token,
            "payload": payload,
        }
        return lease, {
            "acquired": True,
            "lock_path": str(lock_path),
            "owner_token": token,
            "owner_pid": owner_pid,
            "created_at": created_at,
            "reason_code": None,
            "reason": None,
            "existing_owner": None,
        }

    @staticmethod
    def _release_destination_promotion_lock(
        lease: Dict[str, Any],
    ) -> bool:
        """Remove only the still-identical lock owned by ``lease``."""
        descriptor = lease["descriptor"]
        lock_path = Path(lease["path"])
        expected_payload = lease["payload"]
        owned = False
        descriptor_identity = None
        try:
            descriptor_stat = os.fstat(descriptor)
            path_stat = lock_path.stat()
            same_identity = (
                descriptor_stat.st_dev == path_stat.st_dev
                and descriptor_stat.st_ino == path_stat.st_ino
            )
            os.lseek(descriptor, 0, os.SEEK_SET)
            observed_payload = os.read(
                descriptor,
                len(expected_payload) + 1,
            )
            owned = bool(
                same_identity and observed_payload == expected_payload
            )
            descriptor_identity = (
                descriptor_stat.st_dev,
                descriptor_stat.st_ino,
            )
        except OSError:
            owned = False
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
            lease["descriptor"] = -1
        if not owned or descriptor_identity is None:
            return False
        try:
            current_stat = lock_path.stat()
            current_identity = (
                current_stat.st_dev,
                current_stat.st_ino,
            )
            if current_identity != descriptor_identity:
                return False
            if lock_path.read_bytes() != expected_payload:
                return False
            lock_path.unlink()
        except OSError:
            return False
        return True

    @staticmethod
    def _verify_legacy_result(
        plan_number: Union[str, Number],
        ras_object: 'RasPrj',
        *,
        check_errors: bool = True,
        modified_after: Optional[float] = None,
        project_folder: Optional[Union[str, Path]] = None,
        project_name: Optional[str] = None,
    ) -> bool:
        """Verify a legacy run from a fresh ``.O##`` and exact completion record."""
        paths = get_plan_result_artifact_paths(
            plan_number,
            ras_object=ras_object,
            project_folder=project_folder,
            project_name=project_name,
        )
        output_path = paths.legacy_output
        if not output_path.is_file():
            logger.debug("Legacy result file does not exist: %s", output_path)
            return False
        if (
            modified_after is not None
            and output_path.stat().st_mtime < float(modified_after) - 2.0
        ):
            logger.debug(
                "Verification rejected stale legacy result %s",
                output_path.name,
            )
            return False
        from .results.ResultsParser import ResultsParser

        selected_message: Optional[str] = None
        selected_path: Optional[Path] = None
        for message_path in paths.message_sidecars:
            if not message_path.is_file():
                continue
            try:
                before = message_path.stat()
                raw = message_path.read_bytes()
                after = message_path.stat()
                if (before.st_size, before.st_mtime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    logger.warning(
                        "Legacy messages changed while reading: %s",
                        message_path,
                    )
                    return False
                if raw.startswith(b"\xef\xbb\xbf"):
                    selected_message = raw.decode("utf-8-sig", errors="replace")
                else:
                    try:
                        selected_message = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        selected_message = raw.decode("cp1252")
                selected_path = message_path
                break
            except OSError as exc:
                logger.warning(
                    "Could not inspect legacy messages %s: %s",
                    message_path,
                    exc,
                )
                return False
        if selected_message is None or not ResultsParser._has_complete_process_record(
            selected_message
        ):
            logger.warning(
                "Legacy verification requires an exact Complete Process "
                "record in a stored message sidecar for plan %s",
                paths.plan_number,
            )
            return False
        parsed = ResultsParser.parse_compute_messages(selected_message)
        if check_errors and parsed["has_errors"]:
            logger.warning("Verification found errors in %s", selected_path.name)
            return False
        return True

    @staticmethod
    def _verify_result(
        plan_number: Union[str, Number],
        ras_object: 'RasPrj',
        *,
        output_format: ResultFormat,
        check_errors: bool = True,
        modified_after: Optional[float] = None,
    ) -> bool:
        """Verify the result family produced by the selected execution engine."""
        if output_format == "legacy":
            return RasCmdr._verify_legacy_result(
                plan_number,
                ras_object,
                check_errors=check_errors,
                modified_after=modified_after,
            )
        return RasCmdr._verify_completion(
            RasCmdr._get_hdf_path(plan_number, ras_object),
            check_errors=check_errors,
            modified_after=modified_after,
        )

    @staticmethod
    def _verify_completion(
        hdf_path: Path,
        check_errors: bool = True,
        modified_after: Optional[float] = None,
    ) -> bool:
        """
        Verify that a HEC-RAS computation completed successfully (HDF-only).

        Checks three conditions:
        1. 'Complete Process' present in compute messages
        2. '/Plan Data/Plan Information' HDF group exists (structural integrity)
        3. No error patterns in compute messages (when check_errors=True)

        Args:
            hdf_path: Path to plan HDF file
            check_errors: If True, also fail verification if errors detected
                         in compute messages (default: True)
            modified_after: Optional execution start timestamp. When provided,
                reject an otherwise valid HDF whose modification time predates
                this execution. This prevents a failed forced rerun from being
                credited with a copied or stale successful result.

        Returns:
            bool: True if verification passed
        """
        if not hdf_path.exists():
            logger.debug(f"HDF file does not exist: {hdf_path}")
            return False

        if modified_after is not None:
            # A two-second tolerance accommodates filesystems with coarse
            # timestamp resolution while still excluding pre-existing HDFs.
            if hdf_path.stat().st_mtime < float(modified_after) - 2.0:
                logger.debug(
                    "Verification rejected stale HDF %s (modified before this run)",
                    hdf_path.name,
                )
                return False

        try:
            import h5py
            from .hdf.HdfResultsPlan import HdfResultsPlan

            compute_msgs = HdfResultsPlan.get_compute_messages_hdf_only(hdf_path)

            from .results.ResultsParser import ResultsParser

            if not compute_msgs or not ResultsParser._has_complete_process_record(
                compute_msgs
            ):
                logger.debug(f"Verification failed: 'Complete Process' not found in {hdf_path.name}")
                return False

            # Structural check: /Plan Data/Plan Information must exist
            with h5py.File(str(hdf_path), 'r') as hdf:
                if hdf.get('Plan Data/Plan Information') is None:
                    logger.warning(f"Verification failed: '/Plan Data/Plan Information' missing in {hdf_path.name} (partial HDF)")
                    return False

            if check_errors:
                parsed = ResultsParser.parse_compute_messages(compute_msgs)
                if parsed['has_errors']:
                    logger.warning(f"Verification failed: {parsed['error_count']} errors found in {hdf_path.name}")
                    return False

            logger.debug(f"Verification passed for {hdf_path.name}")
            return True
        except Exception as e:
            logger.warning(f"Error verifying completion for {hdf_path}: {e}")
            return False

    @staticmethod
    def _rasunsteady_process_running_for_tmp_hdf(
        tmp_hdf_path: Path,
    ) -> Optional[bool]:
        """Return solver state: running, stopped, or unknown on query failure."""
        if os.name != "nt":
            return False

        try:
            import psutil

            processes = psutil.process_iter(
                ["pid", "name", "cmdline", "cwd"]
            )
            return RasCmdr._rasunsteady_processes_reference_tmp_hdf(
                tmp_hdf_path,
                processes,
            )
        except Exception as exc:
            logger.debug(
                "Could not query RasUnsteady process state for %s: %s",
                tmp_hdf_path.name,
                exc,
            )
            return None

    @staticmethod
    def _rasunsteady_processes_reference_tmp_hdf(
        tmp_hdf_path: Path,
        processes,
    ) -> Optional[bool]:
        """Match a solver to one tmp HDF without wildcard path comparison.

        ``psutil`` supplies already-tokenized command lines and process working
        directories. File-identity comparison therefore handles mapped/UNC,
        short/long, and symlink spellings when both paths are accessible. Any
        relevant access, parsing, or identity uncertainty returns ``None`` so
        callers cannot mistake an unproven nonmatch for solver quiescence.
        """
        import psutil

        from ._process_inspection import (
            _same_windows_path,
            normalize_windows_path_token,
        )

        target_path = Path(tmp_hdf_path)
        target_text = os.path.normcase(os.path.abspath(str(target_path)))
        target_cwd = normalize_windows_path_token(
            str(target_path.parent),
            cwd=None,
        )
        target_name = target_path.name.casefold()
        plan_marker = None
        marker_index = target_name.rfind(".p")
        marker_suffix = ".tmp.hdf"
        if marker_index >= 0 and target_name.endswith(marker_suffix):
            plan_token = target_name[
                marker_index + 2 : -len(marker_suffix)
            ]
            if plan_token.isdigit():
                plan_marker = f"b{plan_token.zfill(2)}"
        uncertain = False

        try:
            for process in processes:
                try:
                    info = process.info
                    raw_name = info.get("name")
                    name = str(raw_name or "").casefold()
                    cmdline = info.get("cmdline")
                    if name != "rasunsteady.exe" and not raw_name:
                        if not isinstance(cmdline, (list, tuple)) or not cmdline:
                            uncertain = True
                            continue
                        raw_executable = cmdline[0]
                        if not isinstance(raw_executable, (str, os.PathLike)):
                            uncertain = True
                            continue
                        executable = os.fspath(raw_executable).strip()
                        if (
                            len(executable) >= 2
                            and executable[0] == '"'
                            and executable[-1] == '"'
                        ):
                            executable = executable[1:-1]
                        if not executable:
                            uncertain = True
                            continue
                        # RasUnsteady is Windows-only. Use Windows basename
                        # rules even when this helper is exercised by tests on
                        # another host OS.
                        name = ntpath.basename(executable).casefold()
                    if name != "rasunsteady.exe":
                        continue

                    if not isinstance(cmdline, (list, tuple)) or not cmdline:
                        uncertain = True
                        continue

                    cwd = info.get("cwd")
                    found_tmp_argument = False
                    process_uncertain = False
                    normalized_arguments = []

                    for raw_argument in cmdline:
                        if not isinstance(raw_argument, (str, os.PathLike)):
                            process_uncertain = True
                            continue
                        argument = os.fspath(raw_argument).strip()
                        if (
                            len(argument) >= 2
                            and argument[0] == '"'
                            and argument[-1] == '"'
                        ):
                            argument = argument[1:-1]
                        normalized_arguments.append(argument.casefold())
                        if not argument.casefold().endswith(".tmp.hdf"):
                            continue

                        found_tmp_argument = True
                        candidate = Path(argument)
                        if not candidate.is_absolute():
                            if not cwd:
                                process_uncertain = True
                                continue
                            candidate = Path(cwd) / candidate

                        candidate_text = os.path.normcase(
                            os.path.abspath(str(candidate))
                        )
                        if candidate_text == target_text:
                            return True

                        try:
                            if os.path.samefile(candidate, target_path):
                                return True
                        except (OSError, ValueError, TypeError):
                            # A path alias may be equivalent even when one
                            # spelling cannot currently be opened. That is not
                            # evidence that the solver is unrelated.
                            process_uncertain = True

                    process_cwd = (
                        normalize_windows_path_token(str(cwd), cwd=None)
                        if cwd
                        else ""
                    )
                    has_batch_marker = any(
                        value.startswith("b") and value[1:].isdigit()
                        for value in normalized_arguments
                    )
                    if (
                        plan_marker is not None
                        and _same_windows_path(process_cwd, target_cwd)
                        and plan_marker in normalized_arguments
                    ):
                        return True

                    # A complete cwd+bNN signature for another plan/project is
                    # a proven nonmatch. Missing identity fields remain
                    # uncertain and therefore cannot establish quiescence.
                    if (
                        process_uncertain
                        or (
                            not found_tmp_argument
                            and not (process_cwd and has_batch_marker)
                        )
                    ):
                        uncertain = True
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    # A process that vanished during enumeration is stopped.
                    continue
                except (psutil.AccessDenied, OSError, ValueError, TypeError):
                    uncertain = True
        except Exception as exc:
            logger.debug(
                "RasUnsteady process enumeration became uncertain for %s: %s",
                target_path.name,
                exc,
            )
            return None

        return None if uncertain else False

    @staticmethod
    def _terminate_launched_process_tree(process: subprocess.Popen) -> None:
        """Stop a launched command and its descendants before final cleanup."""
        try:
            import psutil

            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            _gone, alive = psutil.wait_procs(children, timeout=10)
            if alive:
                raise RuntimeError(
                    "HEC-RAS child processes did not terminate: "
                    f"{[child.pid for child in alive]}"
                )
            try:
                parent.kill()
            except psutil.NoSuchProcess:
                pass
            process.wait(timeout=10)
            if process.poll() is None:
                raise RuntimeError("HEC-RAS launcher did not terminate")
        except Exception as exc:
            logger.warning(
                "Could not terminate the complete HEC-RAS process tree (%s); "
                "falling back to the launcher process",
                exc,
            )
            try:
                process.kill()
                process.wait(timeout=10)
            except Exception as fallback_exc:
                raise RuntimeError(
                    "Could not confirm HEC-RAS process termination"
                ) from fallback_exc
            raise RuntimeError(
                "HEC-RAS launcher stopped, but descendant termination could "
                "not be confirmed"
            ) from exc

    @staticmethod
    def _wait_for_async_plan_completion(
        plan_number: Union[str, Number],
        ras_object: 'RasPrj',
        check_errors: bool = True,
        poll_interval: float = 5.0,
        timeout_seconds: float = 7200.0,
        modified_after: Optional[float] = None,
    ) -> Optional[bool]:
        """
        Wait for a solver child process that outlives ``Ras.exe -c``.

        HEC-RAS 7 can return from the command launcher before the child
        ``RasUnsteady.exe`` process has finished writing ``.p##.tmp.hdf``.
        Returning before that child exits lets parallel workers reuse the same
        folder early and can create false failure logs.  This helper only waits
        when there is concrete evidence of an active or partial async solve.

        Returns
        -------
        True
            Final plan HDF verified.
        False
            An async solve was observed, but no verified final HDF appeared.
        None
            No async solve evidence was present; callers should keep their
            normal success/failure behavior.
        """
        plan_num = RasUtils.normalize_ras_number(plan_number)
        hdf_path = RasCmdr._get_hdf_path(plan_num, ras_object)
        tmp_hdf_path = (
            Path(ras_object.project_folder)
            / f"{ras_object.project_name}.p{plan_num}.tmp.hdf"
        )

        verified = RasCmdr._verify_completion(
            hdf_path,
            check_errors=check_errors,
            modified_after=modified_after,
        )
        active = RasCmdr._rasunsteady_process_running_for_tmp_hdf(tmp_hdf_path)
        partial_exists = tmp_hdf_path.exists()
        if verified and active is False and not partial_exists:
            return True
        if active is False and not partial_exists:
            return None
        if active is None and not partial_exists:
            return False

        logger.debug(
            "Waiting for RasUnsteady to finish plan %s after Ras.exe returned",
            plan_num,
        )
        deadline = time.time() + timeout_seconds
        observed_async = True

        while time.time() < deadline:
            verified = RasCmdr._verify_completion(
                hdf_path,
                check_errors=check_errors,
                modified_after=modified_after,
            )
            active = RasCmdr._rasunsteady_process_running_for_tmp_hdf(tmp_hdf_path)
            partial_exists = tmp_hdf_path.exists()
            if verified and active is False and not partial_exists:
                return True
            if active is False and not partial_exists:
                return False
            if active is None and not partial_exists:
                return False

            if active is False and partial_exists:
                # Give HEC-RAS a short grace window to rename/close files after
                # the solver process exits, then verify one final time.
                time.sleep(min(poll_interval, 2.0))
                verified = RasCmdr._verify_completion(
                    hdf_path,
                    check_errors=check_errors,
                    modified_after=modified_after,
                )
                active = RasCmdr._rasunsteady_process_running_for_tmp_hdf(
                    tmp_hdf_path
                )
                partial_exists = tmp_hdf_path.exists()
                if verified and active is False and not partial_exists:
                    return True
                if active is False:
                    return False

            time.sleep(poll_interval)

        logger.warning(
            "Timed out waiting for RasUnsteady to finish plan %s after %.0f seconds",
            plan_num,
            timeout_seconds,
        )
        return False if observed_async else None

    @staticmethod
    def _confirm_plan_solver_quiescence(
        plan_number: Union[str, Number],
        ras_object: 'RasPrj',
    ) -> bool:
        """Prove exact-plan launcher/solver absence with strict inventory."""
        try:
            inventory = RasCmdr.inspect_plan_processes(
                plan_number,
                ras_object=ras_object,
            )
        except Exception as exc:
            logger.warning(
                "Could not inspect exact-plan processes for plan %s: %s",
                plan_number,
                exc,
            )
            return False
        if not inventory.complete:
            logger.warning(
                "Exact-plan process inventory is incomplete for plan %s",
                plan_number,
            )
            return False
        if inventory.matched:
            logger.warning(
                "Exact-plan HEC-RAS process still active for plan %s: %s",
                plan_number,
                [process.pid for process in inventory.matched],
            )
            return False
        plan_num = RasUtils.normalize_ras_number(plan_number)
        tmp_hdf_path = (
            Path(ras_object.project_folder)
            / f"{ras_object.project_name}.p{plan_num}.tmp.hdf"
        )
        if tmp_hdf_path.exists():
            logger.warning(
                "Temporary result HDF remains for plan %s after launcher exit",
                plan_number,
            )
            return False
        return True

    @staticmethod
    @log_call
    def inspect_plan_processes(
        plan_number: Union[str, Number],
        ras_object=None,
    ) -> PlanProcessInventory:
        """Return strict process evidence narrowed to one project plan.

        Matching uses complete command-line tokens after Windows path
        normalization. A launcher must contain the exact project and plan
        paths. A steady solver must contain the exact project ``.rNN`` run
        file. An unsteady solver must contain either the exact plan
        ``.tmp.hdf`` path or the exact project working directory plus complete
        ``bNN`` plan token used by native unsteady launches. When the plan's
        geometry reference is readable, that form must also contain the exact
        project ``.cNN`` computation-file path. Basenames and substrings are
        never sufficient. The host-wide inventory also covers
        exact legacy and modern compute/preprocess names whose plan-specific
        command signature is not established.
        """
        import psutil

        from ._process_inspection import (
            match_plan_processes,
            scan_ras_processes,
        )

        ras_obj = ras_object if ras_object is not None else ras
        ras_obj.check_initialized()
        plan_num, project_path, plan_path, tmp_hdf_path = (
            RasCmdr._resolve_plan_process_paths(plan_number, ras_obj)
        )
        inventory = scan_ras_processes(psutil_module=psutil)
        return match_plan_processes(
            inventory,
            plan_number=plan_num,
            project_path=project_path,
            plan_path=plan_path,
            tmp_hdf_path=tmp_hdf_path,
        )

    @staticmethod
    def _resolve_plan_process_paths(
        plan_number: Union[str, Number],
        ras_object,
    ):
        """Resolve canonical process-matching paths for one plan."""
        plan_num = RasUtils.normalize_ras_number(plan_number)
        project_path = Path(ras_object.prj_file).resolve(strict=False)
        resolved_plan_path = RasPlan.get_plan_path(plan_num, ras_object)
        if resolved_plan_path is None:
            raise FileNotFoundError(f"Plan file not found: {plan_num}")
        plan_path = Path(resolved_plan_path).resolve(strict=False)
        tmp_hdf_path = (
            Path(ras_object.project_folder)
            / f"{ras_object.project_name}.p{plan_num}.tmp.hdf"
        ).resolve(strict=False)
        return plan_num, project_path, plan_path, tmp_hdf_path

    @staticmethod
    def _process_error(
        process: Any,
        operation: str,
        error: BaseException,
    ) -> RasProcessQueryError:
        """Create JSON-safe cancellation query evidence."""
        pid = getattr(process, "pid", None)
        try:
            normalized_pid = None if pid is None else int(pid)
        except (TypeError, ValueError):
            normalized_pid = None
        exception_type = type(error).__name__
        normalized_type = exception_type.casefold()
        if "accessdenied" in normalized_type:
            reason_code = "access_denied"
        elif "nosuchprocess" in normalized_type:
            reason_code = "process_exited_during_operation"
        else:
            reason_code = "process_operation_failed"
        return RasProcessQueryError(
            pid=normalized_pid,
            operation=operation,
            reason_code=reason_code,
            exception_type=exception_type,
            detail=str(error),
        )

    @staticmethod
    def _record_process_for_cancellation(
        process: Any,
        *,
        tracked: bool = False,
    ) -> RasProcessRecord:
        """Capture a child process using the same strong identity contract."""
        info = getattr(process, "info", {})

        def read(field: str):
            if isinstance(info, dict) and info.get(field) is not None:
                return info[field]
            if field == "pid":
                return process.pid
            return getattr(process, field)()

        pid = int(read("pid"))
        create_time = float(read("create_time"))
        name = str(read("name")).strip()
        raw_command_line = read("cmdline")
        if pid <= 0:
            raise ValueError("process pid must be positive")
        if not 0 < create_time < float("inf"):
            raise ValueError("process create_time must be finite and positive")
        if not name:
            raise ValueError("process name is empty")
        if not isinstance(raw_command_line, (list, tuple)) or not raw_command_line:
            raise ValueError("process command line is missing or malformed")
        exe = read("exe")
        cwd = read("cwd")
        return RasProcessRecord(
            pid=pid,
            create_time=create_time,
            name=name,
            executable_path=None if exe is None else str(exe),
            command_line=tuple(str(token) for token in raw_command_line),
            working_directory=None if cwd is None else str(cwd),
            tracked=tracked,
            session_id=None,
        )

    @staticmethod
    def _same_process_identity(process: Any, record: RasProcessRecord) -> bool:
        """Return false when the captured process exited or its PID was reused."""
        # Do not reuse ``process.info`` here: it is the cached snapshot that
        # created ``record`` and therefore cannot detect later PID reuse.
        current = process.create_time()
        return float(current) == record.create_time

    @staticmethod
    @log_call
    def cancel_plan_exact(
        plan_number: Union[str, Number],
        ras_object=None,
        timeout_seconds: float = 10.0,
    ) -> PlanCancellationResult:
        """Stop only one exact plan process tree and prove final quiescence.

        The result is deliberately tri-state: ``quiescence_confirmed=True``
        proves all matched identities stopped and a complete final scan found
        no exact plan process; ``False`` reports a known survivor; ``None``
        reports query uncertainty. The structured result cannot be coerced to
        bool. ``cancellation_attempted`` records whether a terminate or kill
        method was invoked; ``matched_count`` records initial exact matches.
        """
        if not _WINDOWS_PROCESS_CONTROL:
            raise NotImplementedError(
                "RasCmdr.cancel_plan_exact() currently supports Windows "
                "HEC-RAS process trees only."
            )

        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise ValueError("timeout_seconds must be a positive number of seconds")
        timeout_value = float(timeout_seconds)
        if not math.isfinite(timeout_value) or timeout_value <= 0:
            raise ValueError(
                "timeout_seconds must be a positive finite number of seconds"
            )
        cancellation_started_at = time.time()

        import psutil

        from ._process_inspection import (
            _scan_ras_process_handles,
            match_plan_processes,
        )

        ras_obj = ras_object if ras_object is not None else ras
        ras_obj.check_initialized()
        plan_num, project_path, plan_path, tmp_hdf_path = (
            RasCmdr._resolve_plan_process_paths(plan_number, ras_obj)
        )
        initial_scan = _scan_ras_process_handles(psutil_module=psutil)
        initial_plan = match_plan_processes(
            initial_scan.inventory,
            plan_number=plan_num,
            project_path=project_path,
            plan_path=plan_path,
            tmp_hdf_path=tmp_hdf_path,
        )
        matched = initial_plan.matched
        errors = list(initial_plan.query_errors)
        if not initial_plan.complete:
            if not errors:
                errors.append(
                    RasProcessQueryError(
                        pid=None,
                        operation="match_initial_plan_processes",
                        reason_code="incomplete_plan_inventory",
                        exception_type="IncompletePlanProcessInventory",
                        detail=(
                            "The initial exact-plan process inventory was "
                            "incomplete"
                        ),
                    )
                )
            logger.warning(
                "Refusing to signal plan %s because its initial exact-plan "
                "process inventory is incomplete",
                plan_num,
            )
            return PlanCancellationResult(
                plan_number=plan_num,
                project_path=str(project_path),
                plan_path=str(plan_path),
                tmp_hdf_path=str(tmp_hdf_path),
                cancellation_attempted=False,
                pre_scan_complete=False,
                post_scan_complete=False,
                matched=matched,
                query_errors=tuple(errors),
                quiescence_confirmed=None,
                started_at=cancellation_started_at,
                finished_at=time.time(),
            )

        target_records = {record.identity: record for record in matched}
        target_handles = {
            identity: initial_scan.handles[identity]
            for identity in target_records
            if identity in initial_scan.handles
        }
        child_query_uncertain = False
        for root in matched:
            process = target_handles.get(root.identity)
            if process is None:
                child_query_uncertain = True
                errors.append(
                    RasProcessQueryError(
                        pid=root.pid,
                        operation="resolve_process_handle",
                        reason_code="process_handle_missing",
                        exception_type="ProcessHandleMissing",
                        detail="No process handle was retained for captured identity",
                    )
                )
                continue
            try:
                children = process.children(recursive=True)
            except Exception as error:
                child_query_uncertain = True
                errors.append(
                    RasCmdr._process_error(
                        process,
                        "query_process_children",
                        error,
                    )
                )
                continue
            for child in children:
                try:
                    record = RasCmdr._record_process_for_cancellation(child)
                except Exception as error:
                    child_query_uncertain = True
                    errors.append(
                        RasCmdr._process_error(
                            child,
                            "query_child_identity",
                            error,
                        )
                    )
                    continue
                target_records[record.identity] = record
                target_handles[record.identity] = child

        termination_requested = []
        kill_requested = []
        stopped = []
        known_survivors = []
        signalled = []
        cancellation_attempted = False

        # Children are returned before their root after reversal, minimizing
        # the chance that a launcher loses track of a still-running solver.
        ordered_targets = list(target_records.values())
        for record in reversed(ordered_targets):
            process = target_handles.get(record.identity)
            if process is None:
                continue
            try:
                if not RasCmdr._same_process_identity(process, record):
                    stopped.append(record)
                    continue
                cancellation_attempted = True
                process.terminate()
                termination_requested.append(record)
                signalled.append(process)
            except psutil.NoSuchProcess:
                stopped.append(record)
            except Exception as error:
                errors.append(
                    RasCmdr._process_error(
                        process,
                        "terminate_process",
                        error,
                    )
                )

        alive = []
        if signalled:
            try:
                _, alive = psutil.wait_procs(
                    signalled,
                    timeout=timeout_value,
                )
            except Exception as error:
                child_query_uncertain = True
                errors.append(
                    RasCmdr._process_error(
                        signalled[0],
                        "wait_after_terminate",
                        error,
                    )
                )
                alive = list(signalled)

        record_by_identity = target_records
        for process in alive:
            candidates = [
                record
                for identity, record in record_by_identity.items()
                if identity[0] == getattr(process, "pid", None)
            ]
            if not candidates:
                continue
            record = candidates[0]
            try:
                if not RasCmdr._same_process_identity(process, record):
                    stopped.append(record)
                    continue
                cancellation_attempted = True
                process.kill()
                kill_requested.append(record)
            except psutil.NoSuchProcess:
                stopped.append(record)
            except Exception as error:
                errors.append(
                    RasCmdr._process_error(
                        process,
                        "kill_process",
                        error,
                    )
                )

        if kill_requested:
            killed_handles = [
                target_handles[item.identity] for item in kill_requested
            ]
            try:
                psutil.wait_procs(killed_handles, timeout=3.0)
            except Exception as error:
                child_query_uncertain = True
                errors.append(
                    RasCmdr._process_error(
                        killed_handles[0],
                        "wait_after_kill",
                        error,
                    )
                )

        survivor_identities = {item.identity for item in known_survivors}
        stopped_identities = {item.identity for item in stopped}
        for identity, record in target_records.items():
            if identity in survivor_identities or identity in stopped_identities:
                continue
            process = target_handles.get(identity)
            if process is None:
                continue
            try:
                if not RasCmdr._same_process_identity(process, record):
                    stopped.append(record)
                    stopped_identities.add(identity)
                    continue
                is_running = getattr(process, "is_running", None)
                if is_running is None:
                    child_query_uncertain = True
                    errors.append(
                        RasProcessQueryError(
                            pid=record.pid,
                            operation="verify_process_stopped",
                            reason_code="process_status_unavailable",
                            exception_type="ProcessStatusUnavailable",
                            detail="Process handle has no is_running() method",
                        )
                    )
                elif bool(is_running()):
                    known_survivors.append(record)
                    survivor_identities.add(identity)
                else:
                    stopped.append(record)
                    stopped_identities.add(identity)
            except psutil.NoSuchProcess:
                stopped.append(record)
                stopped_identities.add(identity)
            except Exception as error:
                child_query_uncertain = True
                errors.append(
                    RasCmdr._process_error(
                        process,
                        "verify_process_stopped",
                        error,
                    )
                )

        final_scan = _scan_ras_process_handles(psutil_module=psutil)
        final_plan = match_plan_processes(
            final_scan.inventory,
            plan_number=plan_num,
            project_path=project_path,
            plan_path=plan_path,
            tmp_hdf_path=tmp_hdf_path,
        )
        errors.extend(final_plan.query_errors)

        final_matches = final_plan.matched
        all_survivors = {
            item.identity: item for item in (*known_survivors, *final_matches)
        }
        if all_survivors:
            quiescence_confirmed: Optional[bool] = False
        elif (
            not initial_plan.complete
            or not final_plan.complete
            or child_query_uncertain
            or errors
        ):
            quiescence_confirmed = None
        else:
            quiescence_confirmed = True

        result = PlanCancellationResult(
            plan_number=plan_num,
            project_path=str(project_path),
            plan_path=str(plan_path),
            tmp_hdf_path=str(tmp_hdf_path),
            cancellation_attempted=cancellation_attempted,
            pre_scan_complete=initial_plan.complete,
            post_scan_complete=final_plan.complete,
            matched=matched,
            stopped=tuple(
                sorted(
                    {item.identity: item for item in stopped}.values(),
                    key=lambda item: item.identity,
                )
            ),
            survivors=tuple(
                sorted(all_survivors.values(), key=lambda item: item.identity)
            ),
            query_errors=tuple(errors),
            quiescence_confirmed=quiescence_confirmed,
            started_at=cancellation_started_at,
            finished_at=time.time(),
        )
        if result.quiescence_confirmed is True:
            logger.info(
                "Confirmed HEC-RAS process quiescence for plan %s "
                "(%s exact match(es))",
                plan_num,
                result.matched_count,
            )
        elif result.quiescence_confirmed is False:
            logger.warning(
                "HEC-RAS process survivor(s) remain for plan %s: %s",
                plan_num,
                [item.pid for item in result.survivors],
            )
        else:
            logger.warning(
                "Could not prove HEC-RAS process quiescence for plan %s",
                plan_num,
            )
        return result

    @staticmethod
    @log_call
    def cancel_plan(
        plan_number: Union[str, Number],
        ras_object=None,
        timeout_seconds: float = 10.0,
    ) -> bool:
        """Stop only the active Windows process tree for one project plan.

        Process matching is deliberately strict: a ``Ras.exe`` launcher must
        contain both the initialized project path and resolved plan path. A
        steady solver must contain the exact project ``.rNN`` file. An
        unsteady solver must contain either the exact plan ``.tmp.hdf`` path or
        the jointly exact project directory, ``.cNN`` computation file, and
        complete ``bNN`` plan marker used by native launches. Unrelated RAS
        sessions are never selected by executable name alone.

        Args:
            plan_number: Plan number to cancel (for example, ``"01"``).
            ras_object: Initialized :class:`RasPrj` object. Uses the global
                project when omitted.
            timeout_seconds: Grace period before force-killing only the already
                matched processes.

        Returns:
            ``True`` when a matching process tree was found and stopped;
            ``False`` when no matching active process existed.
        """
        try:
            legacy_timeout = max(0.1, float(timeout_seconds))
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be numeric") from exc
        if not math.isfinite(legacy_timeout):
            raise ValueError("timeout_seconds must be finite")

        result = RasCmdr.cancel_plan_exact(
            plan_number,
            ras_object=ras_object,
            timeout_seconds=legacy_timeout,
        )
        return result.matched_count > 0 and result.quiescence_confirmed is True
    
    @staticmethod
    @log_call
    def compute_plan(
        plan_number: Union[str, Number, Path],
        dest_folder=None,
        ras_object=None,
        clear_geompre=False,
        force_geompre: bool = False,
        force_rerun: bool = False,
        num_cores=None,
        overwrite_dest=False,
        skip_existing: bool = False,
        verify: bool = False,
        stream_callback: Optional[Callable] = None,
        use_optimal_hdf_settings: bool = False,
        hdf_settings_profile: str = "balanced",
        hdf_additional_variables: Optional[List[str]] = None,
        hdf_output_variables: Optional[List[str]] = None,
        hdf_output_options: Optional[Dict[str, Any]] = None,
        hdf_output_profile: Optional[str] = None,
        dialog_watchdog: bool = True,
    ) -> 'ComputeResult':
        """
        Execute a single HEC-RAS plan in a specified location.

        This function runs a HEC-RAS plan by launching the HEC-RAS executable through command line,
        allowing for destination folder specification, core count control, and geometry preprocessor management.

        Args:
            plan_number (Union[str, Number, Path]): The plan number to execute (e.g., "01", 1, 1.0) or the full path to the plan file.
                Recommended to use two-digit strings for plan numbers for consistency (e.g., "01" instead of 1).
            dest_folder (str, Path, optional): Name of the folder or full path for computation.
                If a string is provided, it will be created in the same parent directory as the project folder.
                If a full path is provided, it will be used as is.
                If None, computation occurs in the original project folder, modifying the original project.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
                Useful when working with multiple projects simultaneously.
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files (.c## files). Defaults to False.
                Set to True when geometry has been modified to force recomputation of preprocessor files.
            force_geompre (bool, optional): Force full geometry reprocessing. Defaults to False.
                Clears .c## files and requests native complete-geometry processing via
                RasProcess.exe before running the plan. The geometry HDF is preserved:
                ras-commander does not selectively delete solver-owned datasets, and the
                land-cover and terrain associations remain intact.
                Implies force_rerun: the currency check compares only .p##/.g##/.u## mtimes against
                the results HDF, so it cannot detect changes to land-cover sidecars. Skipping
                would silently drop the reprocessing request. The RasProcess.exe request is
                best effort; if unavailable, the plan still runs after .c## clearing.
            force_rerun (bool, optional): Force execution even if results are current. Defaults to False.
                When False (default), checks file modification times and skips if results are current.
                When True, always executes regardless of result currency.
            num_cores (int, optional): Number of cores to use for the plan execution.
                If None, the current setting in the plan file is not changed.
                Generally, 2-4 cores provides good performance for most models.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists. Defaults to False.
                Set to True to replace an existing destination folder with the same name.
            skip_existing (bool, optional): If True, skip computation when the
                selected engine's sole result family already verifies. Modern
                HDF uses ``Complete Process``; legacy execution requires its
                ``.O##`` output and checks available messages for errors.
                Defaults to False.
                Useful for resuming interrupted batch runs or incremental workflows.
            verify (bool, optional): If True, verify the selected result family
                after execution. Defaults to False.
                Returns False if verification fails even if subprocess returned success.
            stream_callback (Callable, optional): Callback object for real-time execution progress monitoring.
                Must implement ExecutionCallback protocol methods (all methods optional):
                - on_prep_start(plan_number): Called before geometry preprocessing
                - on_prep_complete(plan_number): Called after preprocessing
                - on_exec_start(plan_number, command): Called when HEC-RAS subprocess starts
                - on_exec_message(plan_number, message): Called for each .bco file message (real-time)
                - on_exec_complete(plan_number, success, duration): Called when execution finishes
                - on_verify_result(plan_number, verified): Called after verification (if verify=True)
                IMPORTANT: Must be thread-safe when used with compute_parallel().
                See ras_commander.callbacks for example implementations.
            use_optimal_hdf_settings (bool, optional): If True, apply ras-commander's
                recommended HDF write settings to the plan before currency checks and execution.
                Defaults to False.
            hdf_settings_profile (str, optional): HDF settings profile to apply when
                use_optimal_hdf_settings=True. Options are "balanced", "speed", "size",
                and "nas". Defaults to "balanced".
            hdf_additional_variables (List[str], optional): Additional HDF output variables
                to enable when use_optimal_hdf_settings=True.
            hdf_output_variables (List[str], optional): Additional HDF output variables
                to enable before execution.
            hdf_output_options (Dict[str, Any], optional): Explicit HDF output options
                passed to ``RasPlan.set_hdf_output_options()`` before execution.
            hdf_output_profile (str, optional): Named HDF output profile to apply before
                execution. Equivalent to ``use_optimal_hdf_settings=True`` with a profile.
        Returns:
            ComputeResult: Result object with ``success`` bool and ``results_df_row`` (pd.Series or None).
                Backward compatible with bool: ``if RasCmdr.compute_plan("01"):`` still works.
                Access execution metrics via ``result.results_df_row`` (e.g., runtime, volume accounting).
                ``results_df_row`` is None when dest_folder is used, execution fails, or extraction errors.
                When skip_existing=True and results exist, returns ComputeResult(success=True).
                ``completion_verified`` is None unless ``verify=True``.
                ``execution_details`` is always JSON-safe and distinguishes
                selected executable identity, calculation attempts, launcher
                PID/create-time identity, solver quiescence, and result-family
                finalization. Calculated success requires every terminal gate.

        Raises:
            ValueError: If the specified dest_folder already exists and is not empty, and overwrite_dest is False.
            FileNotFoundError: If the plan file or project file cannot be found.
            PermissionError: If there are issues accessing or writing to the destination folder.
            subprocess.CalledProcessError: If the HEC-RAS execution fails.

        Examples:
            # Run a plan in the original project folder
            RasCmdr.compute_plan("01")

            # Run a plan in a separate folder
            RasCmdr.compute_plan("01", dest_folder="computation_folder")

            # Run a plan with a specific number of cores
            RasCmdr.compute_plan("01", num_cores=4)

            # Run a plan in a specific folder, overwriting if it exists
            RasCmdr.compute_plan("01", dest_folder="computation_folder", overwrite_dest=True)

            # Skip computation if results already exist
            RasCmdr.compute_plan("01", skip_existing=True)

            # Run with verification of successful completion
            RasCmdr.compute_plan("01", verify=True)

            # Run with real-time progress monitoring
            from ras_commander.callbacks import ConsoleCallback
            callback = ConsoleCallback()
            RasCmdr.compute_plan("01", stream_callback=callback)

            # Run with recommended HDF write parameters
            RasCmdr.compute_plan("01", use_optimal_hdf_settings=True)

            # Run a plan in a specific folder with multiple options
            RasCmdr.compute_plan(
                "01",
                dest_folder="computation_folder",
                num_cores=2,
                clear_geompre=True,
                overwrite_dest=True,
                verify=True
            )

        Notes:
            - For executing multiple plans, consider using compute_parallel() or compute_test_mode().
            - Setting num_cores appropriately is important for performance:
              * 1-2 cores: Highest efficiency per core, good for small models
              * 3-8 cores: Good balance for most models
              * >8 cores: May have diminishing returns due to overhead
            - This function updates the RAS object's dataframes (plan_df, geom_df, etc.) after execution.
            - When skip_existing=True with dest_folder, the check happens AFTER copying to destination.
            - Verification is version-aware: modern plans inspect HDF completion;
              legacy plans require a fresh ``.O##`` and inspect available stored
              messages for errors.
            - Actual runs permanently remove the opposing result family and
              stale compute-message sidecars before launch, then remove any
              opposing result recreated by HEC-RAS after completion. Skipped
              runs do not mutate execution artifacts.
        """
        _success = False
        _results_df_row = None
        _ras_obj = None
        _did_execute = False  # Track if we actually ran HEC-RAS (vs skip/early exit)
        _execution_quiesced = False
        _execution_result_format = None
        _result_artifacts_finalized = False
        _watchdog = None
        _execution_details: Dict[str, Any] = {
            "execution_api": "ras_cmdr",
            "engine_kind": "executable",
            "selected_result_format": None,
            "calculation_attempted": False,
            "solver_quiescence_confirmed": None,
            "result_artifacts_finalized": False,
            "actual_engine_provenance_confirmed": False,
            "selected_executable_path": None,
            "selected_executable_sha256": None,
            "launcher_pid": None,
            "launcher_create_time": None,
        }
        try:
            ras_obj = ras_object if ras_object is not None else ras
            _ras_obj = ras_obj
            logger.debug(f"Using ras_object with project folder: {ras_obj.project_folder}")
            ras_obj.check_initialized()

            if dest_folder is not None:
                dest_folder = Path(ras_obj.project_folder).parent / dest_folder if isinstance(dest_folder, str) else Path(dest_folder)

                if dest_folder.resolve() == Path(ras_obj.project_folder).resolve():
                    logger.info("Destination folder matches the active project folder; executing in place.")
                    dest_folder = None
                    compute_ras = ras_obj
                    compute_prj_path = ras_obj.prj_file
                else:
                    if dest_folder.exists():
                        if overwrite_dest:
                            if not RasUtils.remove_with_retry(dest_folder, ras_object=ras_obj):
                                raise PermissionError(f"Unable to remove destination folder: {dest_folder}")
                            logger.info("Destination folder exists; overwriting as requested: %s", dest_folder.name)
                            logger.debug(f"Overwriting destination folder: {dest_folder}")
                        elif any(dest_folder.iterdir()):
                            error_msg = f"Destination folder '{dest_folder}' exists and is not empty. Use overwrite_dest=True to overwrite."
                            logger.error(error_msg)
                            raise ValueError(error_msg)

                    dest_folder.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(ras_obj.project_folder, dest_folder, dirs_exist_ok=True, ignore=RasUtils.ignore_windows_reserved)
                    logger.info("Copied project folder to destination: %s", dest_folder.name)
                    logger.debug(f"Copied project folder to destination path: {dest_folder}")

                    compute_ras = RasPrj()
                    compute_ras.initialize(dest_folder, ras_obj.ras_exe_path)
                    compute_prj_path = compute_ras.prj_file
            if dest_folder is None:
                compute_ras = ras_obj
                compute_prj_path = ras_obj.prj_file

            # Determine the plan path
            compute_plan_path = Path(plan_number) if isinstance(plan_number, (str, Path)) and Path(plan_number).is_file() else RasPlan.get_plan_path(plan_number, compute_ras)

            if not compute_prj_path or not compute_plan_path:
                logger.error(f"Could not find project file or plan file for plan {plan_number}")
                _success = False
                return ComputeResult(
                    success=False,
                    results_df_row=None,
                    execution_details=dict(_execution_details),
                )

            # Resolve the actual selected engine before making any skip or
            # cleanup decision. An unresolved version fails closed and leaves
            # both result families untouched.
            _execution_result_format = infer_execution_result_format(compute_ras)
            _execution_details["selected_result_format"] = (
                _execution_result_format
            )

            # Skip existing check - runs regardless of force_rerun (for resume capability)
            if skip_existing:
                artifact_paths = get_plan_result_artifact_paths(
                    plan_number, ras_object=compute_ras
                )
                mixed_results = (
                    artifact_paths.hdf.is_file()
                    and artifact_paths.legacy_output.is_file()
                )
                if mixed_results:
                    logger.warning(
                        "Plan %s has both HDF and legacy results; "
                        "skip_existing will rerun it with the selected HEC-RAS "
                        "version and normalize its result artifacts.",
                        plan_number,
                    )
                elif RasCmdr._verify_result(
                    plan_number,
                    compute_ras,
                    output_format=_execution_result_format,
                    check_errors=False,
                ):
                    logger.info(
                        "Skipping plan %s: verified %s results already exist",
                        plan_number,
                        _execution_result_format,
                    )
                    _success = True
                    return ComputeResult(
                        success=True,
                        results_df_row=None,
                        completion_verified=True if verify else None,
                        execution_details=dict(_execution_details),
                    )

            # Smart skip: check file modification times (unless force_rerun or skip_existing)
            # Note: Smart skip is bypassed when skip_existing=True since that provides explicit skip logic
            # force_geompre also bypasses the skip: currency only
            # compares .p##/.g##/.u## mtimes against the results HDF, so it cannot
            # see sidecar-only changes. Skipping would silently drop the native
            # reprocessing request and return success.
            if not force_rerun and not skip_existing and not force_geompre:
                from .RasCurrency import RasCurrency
                is_current, reason = (
                    RasCurrency._are_plan_results_current_for_execution(
                        plan_number,
                        compute_ras,
                        output_format=_execution_result_format,
                    )
                )
                if is_current:
                    logger.info(f"Skipping plan {plan_number}: {reason}")
                    _success = True
                    return ComputeResult(
                        success=True,
                        results_df_row=None,
                        completion_verified=True if verify else None,
                        execution_details=dict(_execution_details),
                    )
                else:
                    logger.debug(f"Plan {plan_number} needs execution: {reason}")

            # Plan-file execution settings are mutations. Apply them only
            # after every skip path has committed to an actual run.
            if use_optimal_hdf_settings or hdf_output_profile:
                profile_to_apply = hdf_output_profile or hdf_settings_profile
                variables_to_apply = hdf_additional_variables or hdf_output_variables
                hdf_settings_success = RasPlan.use_optimal_hdf_settings(
                    compute_plan_path,
                    profile=profile_to_apply,
                    additional_variables=variables_to_apply,
                    ras_object=compute_ras
                )
                if hdf_settings_success:
                    logger.info(
                        f"Applied '{profile_to_apply}' HDF settings profile "
                        f"to plan: {compute_plan_path.name}"
                    )
                else:
                    logger.warning(
                        f"Could not apply '{profile_to_apply}' HDF settings profile "
                        f"to plan: {compute_plan_path.name}"
                    )

            if hdf_output_options:
                hdf_options_success = RasPlan.set_hdf_output_options(
                    compute_plan_path,
                    ras_object=compute_ras,
                    **hdf_output_options
                )
                if not hdf_options_success:
                    logger.warning(f"Could not apply explicit HDF output options to {compute_plan_path.name}")

            if hdf_output_variables and not (use_optimal_hdf_settings or hdf_output_profile):
                RasPlan.set_hdf_output_variables(
                    compute_plan_path,
                    hdf_output_variables,
                    enabled=True,
                    ras_object=compute_ras
                )

            # Always enable Write Detailed= 1 to ensure .computeMsgs.txt is written
            # This is critical for results_df fallback on pre-6.4 HEC-RAS versions
            BcoMonitor.enable_detailed_logging(compute_plan_path)
            logger.debug(f"Enabled Write Detailed= 1 for plan {plan_number}")

            # Enable .bco monitoring if callback provided
            bco_monitor = None
            if stream_callback:
                # Create monitor with callback wrapper
                bco_monitor = BcoMonitor(
                    project_path=Path(compute_ras.project_folder),
                    plan_number=RasUtils.normalize_ras_number(plan_number),
                    project_name=compute_ras.project_name,
                    message_callback=lambda msg: (
                        stream_callback.on_exec_message(str(plan_number), msg)
                        if hasattr(stream_callback, 'on_exec_message') else None
                    )
                )
                logger.debug(f"BcoMonitor initialized for plan {plan_number}")

            # Callback: preprocessing start
            if stream_callback and hasattr(stream_callback, 'on_prep_start'):
                stream_callback.on_prep_start(str(plan_number))

            # Handle geometry preprocessor clearing
            if force_geompre:
                # Preserve the geometry HDF and its associations. Clear only .c##
                # files, then ask HEC-RAS to perform complete geometry processing.
                from .RasCurrency import RasCurrency
                from .geom import GeomPreprocessor
                try:
                    geom_hdf_path = RasCurrency.get_geom_hdf_path(plan_number, compute_ras)
                    GeomPreprocessor.clear_geompre_files(compute_plan_path, ras_object=compute_ras)
                    logger.debug(f"Force-cleared .c## geometry preprocessor files for plan: {plan_number}")

                    # Best effort: RasProcess.exe may be absent, or CompleteGeometry
                    # may differ on other HEC-RAS versions. The plan run still
                    # proceeds after .c## clearing if this native request is unavailable.
                    if geom_hdf_path is not None and Path(geom_hdf_path).exists():
                        try:
                            from .RasProcess import RasProcess
                            RasProcess.compute_geometry(
                                geom_hdf_path, ras_object=compute_ras
                            )
                        except Exception as e:
                            logger.debug(
                                f"RasProcess geometry rebuild unavailable for plan {plan_number} "
                                f"({e}); continuing with the plan run."
                            )
                except Exception as e:
                    logger.error(f"Error force-clearing geometry preprocessor files for plan {plan_number}: {str(e)}")
            elif clear_geompre:
                # Original behavior - only clear .c## files
                from .geom import GeomPreprocessor
                try:
                    GeomPreprocessor.clear_geompre_files(compute_plan_path, ras_object=compute_ras)
                    logger.debug(f"Cleared geometry preprocessor files for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error clearing geometry preprocessor files for plan {plan_number}: {str(e)}")

            # Set the number of cores if specified
            if num_cores is not None:
                try:
                    RasPlan.set_num_cores(compute_plan_path, num_cores=num_cores, ras_object=compute_ras)
                    logger.debug(f"Set number of cores to {num_cores} for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error setting number of cores for plan {plan_number}: {str(e)}")

            # Callback: preprocessing complete
            if stream_callback and hasattr(stream_callback, 'on_prep_complete'):
                stream_callback.on_prep_complete(str(plan_number))

            # Prepare a display-only command for callbacks. The executable is
            # resolved and hashed again immediately before result cleanup and
            # launch, and execution always uses the exact argv with no shell.
            _callback_executable, _ = RasCmdr._resolve_executable_provenance(
                compute_ras.ras_exe_path
            )
            command_argv = [
                str(_callback_executable),
                "-c",
                str(Path(compute_prj_path).resolve()),
                str(Path(compute_plan_path).resolve()),
            ]
            cmd = subprocess.list2cmdline(command_argv)
            logger.debug("Running Ras.exe with -c command line flag for plan %s", plan_number)
            logger.debug(f"Running command: {cmd}")

            # Per-plan stdio log. HEC-RAS stdout/stderr are redirected to this file
            # rather than a PIPE to avoid an inherited-pipe deadlock (CLB-880): with
            # shell=True the pipe's write handle is inherited by the whole
            # cmd.exe -> Ras.exe -> RasUnsteady.exe tree, and the parent blocks on
            # pipe EOF until EVERY descendant closes it. If a solver grandchild
            # lingers past compute completion (intermittent, and far more likely
            # under CPU contention) the read end never reaches EOF and the call
            # hangs forever. HEC-RAS emits no compute messages to stdio -- they go
            # to .bco##/.computeMsgs.txt, which the library already parses -- so a
            # file loses no diagnostics while removing the EOF dependency entirely.
            _run_log_path = (
                Path(compute_ras.project_folder)
                / f"_compute_p{RasUtils.normalize_ras_number(plan_number)}.log"
            )

            # Callback: execution start
            if stream_callback and hasattr(stream_callback, 'on_exec_start'):
                stream_callback.on_exec_start(str(plan_number), cmd)

            # Execute the HEC-RAS command
            start_time = time.time()
            try:
                if dialog_watchdog:
                    from .RasDialogWatchdog import DialogWatchdog
                    _watchdog = DialogWatchdog()
                    _watchdog.start()

                # Both callback and non-callback runs use one exact launch
                # path. This avoids cmd.exe identity ambiguity and keeps the
                # recorded launcher PID tied to the selected Ras.exe bytes.
                with open(
                    _run_log_path,
                    "w",
                    encoding="utf-8",
                    errors="ignore",
                ) as _run_log_fh:
                    selected_executable, executable_sha256 = (
                        RasCmdr._resolve_executable_provenance(
                            compute_ras.ras_exe_path
                        )
                    )
                    command_argv = [
                        str(selected_executable),
                        "-c",
                        str(Path(compute_prj_path).resolve()),
                        str(Path(compute_plan_path).resolve()),
                    ]
                    _execution_details.update(
                        {
                            "selected_executable_path": str(selected_executable),
                            "selected_executable_sha256": executable_sha256,
                        }
                    )

                    # The plan's previous launcher/solver tree must be proved
                    # absent before result-family cleanup. A stale exact-plan
                    # process could otherwise keep writing the files this run
                    # is about to remove or replace.
                    pre_run_inventory = RasCmdr.inspect_plan_processes(
                        plan_number,
                        ras_object=compute_ras,
                    )
                    if not pre_run_inventory.complete:
                        raise RuntimeError(
                            "Exact-plan process inventory was incomplete before "
                            "execution; result artifacts were preserved"
                        )
                    if pre_run_inventory.matched:
                        raise RuntimeError(
                            "An exact-plan HEC-RAS process was already active "
                            "before execution; result artifacts were preserved"
                        )

                    # Destructive result-family cleanup is coupled to this
                    # exact, freshly proven launch attempt.
                    prepare_plan_execution_artifacts(
                        plan_number,
                        output_format=_execution_result_format,
                        ras_object=compute_ras,
                    )
                    _did_execute = True
                    _execution_details["calculation_attempted"] = True
                    process = subprocess.Popen(
                        command_argv,
                        stdout=_run_log_fh,
                        stderr=subprocess.STDOUT,
                        cwd=str(compute_ras.project_folder),
                        shell=False,
                    )
                    try:
                        launcher_pid = process.pid
                        if (
                            not isinstance(launcher_pid, int)
                            or isinstance(launcher_pid, bool)
                            or launcher_pid <= 0
                        ):
                            raise ValueError(
                                "launcher PID must be a positive integer"
                            )
                        launcher_create_time = RasCmdr._launcher_create_time(
                            launcher_pid
                        )
                        if (
                            isinstance(launcher_create_time, bool)
                            or not isinstance(launcher_create_time, (int, float))
                            or not math.isfinite(float(launcher_create_time))
                            or float(launcher_create_time) <= 0
                        ):
                            raise ValueError(
                                "launcher create_time must be finite and positive"
                            )
                        _execution_details["launcher_pid"] = launcher_pid
                        _execution_details["launcher_create_time"] = float(
                            launcher_create_time
                        )
                        _execution_details[
                            "actual_engine_provenance_confirmed"
                        ] = True
                    except Exception as provenance_error:
                        logger.error(
                            "Could not capture launcher PID/create-time identity "
                            "for plan %s: %s",
                            plan_number,
                            provenance_error,
                        )

                    try:
                        if _watchdog:
                            _watchdog.add_pid(process.pid)

                        if stream_callback and bco_monitor:
                            # Monitor .bco messages while the exact process is
                            # active; the same process wait path is used below.
                            bco_monitor.monitor_until_signal(process)

                        return_code = process.wait()
                    except BaseException:
                        if process.poll() is None:
                            try:
                                RasCmdr._terminate_launched_process_tree(process)
                            except Exception as termination_error:
                                logger.critical(
                                    "Could not confirm termination of plan %s "
                                    "after callback failure: %s",
                                    plan_number,
                                    termination_error,
                                )
                            else:
                                _execution_quiesced = True
                        elif _execution_result_format == "hdf":
                            # The Ras.exe launcher may have exited while a
                            # RasUnsteady child still owns the tmp HDF.
                            _async_wait_result = RasCmdr._wait_for_async_plan_completion(
                                plan_number,
                                compute_ras,
                                check_errors=False,
                                modified_after=start_time,
                            )
                            _execution_quiesced = (
                                RasCmdr._confirm_plan_solver_quiescence(
                                    plan_number,
                                    compute_ras,
                                )
                            )
                        else:
                            _execution_quiesced = (
                                RasCmdr._confirm_plan_solver_quiescence(
                                    plan_number,
                                    compute_ras,
                                )
                            )
                        raise

                if return_code != 0:
                    raise subprocess.CalledProcessError(
                        return_code,
                        command_argv,
                    )

                end_time = time.time()
                run_time = end_time - start_time
                logger.debug(
                    f"HEC-RAS execution completed for plan {plan_number} "
                    f"in {run_time:.2f} seconds"
                )

                async_verified = (
                    RasCmdr._wait_for_async_plan_completion(
                        plan_number,
                        compute_ras,
                        check_errors=verify,
                        modified_after=start_time,
                    )
                    if _execution_result_format == "hdf"
                    else None
                )
                if _execution_result_format == "hdf":
                    _execution_quiesced = (
                        RasCmdr._confirm_plan_solver_quiescence(
                            plan_number,
                            compute_ras,
                        )
                    )
                else:
                    _execution_quiesced = (
                        RasCmdr._confirm_plan_solver_quiescence(
                            plan_number,
                            compute_ras,
                        )
                    )
                if async_verified is True:
                    logger.debug(
                        "Verified final HDF for plan %s after Ras.exe returned",
                        plan_number,
                    )
                    if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                        stream_callback.on_exec_complete(str(plan_number), True, run_time)
                    if verify and stream_callback and hasattr(stream_callback, 'on_verify_result'):
                        stream_callback.on_verify_result(str(plan_number), True)
                    _success = True
                elif async_verified is False and verify:
                    logger.error(
                        "Verification failed for plan %s after Ras.exe returned. "
                        "See: https://rascommander.info/ras/user-guide/plan-execution/",
                        plan_number,
                    )
                    _success = False
                    if stream_callback and hasattr(stream_callback, 'on_verify_result'):
                        stream_callback.on_verify_result(str(plan_number), False)
                else:
                    # Callback: execution complete
                    if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                        stream_callback.on_exec_complete(str(plan_number), True, run_time)

                    # Verify completion if requested
                    if verify:
                        verified = (
                            async_verified is True
                            or RasCmdr._verify_result(
                                plan_number,
                                compute_ras,
                                output_format=_execution_result_format,
                                modified_after=start_time,
                            )
                        )

                        # Callback: verification result
                        if stream_callback and hasattr(stream_callback, 'on_verify_result'):
                            stream_callback.on_verify_result(str(plan_number), verified)

                        if verified:
                            logger.debug(f"Verification passed for plan {plan_number}")
                            _success = True
                        else:
                            logger.error(
                                f"Verification failed for plan {plan_number}: no complete, current {_execution_result_format} result was found. "
                                f"See: https://rascommander.info/ras/user-guide/plan-execution/"
                            )
                            _success = False
                    else:
                        _success = True

            except subprocess.CalledProcessError as e:
                end_time = time.time()
                run_time = end_time - start_time
                async_verified = (
                    RasCmdr._wait_for_async_plan_completion(
                        plan_number,
                        compute_ras,
                        check_errors=True,
                        modified_after=start_time,
                    )
                    if _execution_result_format == "hdf"
                    else None
                )
                if _execution_result_format == "hdf":
                    _execution_quiesced = (
                        RasCmdr._confirm_plan_solver_quiescence(
                            plan_number,
                            compute_ras,
                        )
                    )
                else:
                    _execution_quiesced = (
                        RasCmdr._confirm_plan_solver_quiescence(
                            plan_number,
                            compute_ras,
                        )
                    )
                if async_verified is True:
                    logger.info(
                        "Ras.exe returned exit code %s for plan %s, but the final HDF verified after solver completion",
                        e.returncode,
                        plan_number,
                    )
                    if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                        stream_callback.on_exec_complete(str(plan_number), True, run_time)
                    _success = True
                else:
                    logger.error(f"Error running plan: {plan_number} (exit code {e.returncode})")
                    logger.info(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")

                    # stdout/stderr were redirected to a file (no PIPE), so e.output is
                    # None; surface the tail of the run log for context. The substantive
                    # compute messages are read from the .bco/.computeMsgs files below.
                    try:
                        if _run_log_path.exists():
                            _log_text = _run_log_path.read_text(encoding="utf-8", errors="ignore").strip()
                            if _log_text:
                                logger.error(f"HEC-RAS console output ({_run_log_path.name}):\n{_log_text[-2000:]}")
                    except Exception as _log_err:
                        logger.debug(f"Could not read run log {_run_log_path}: {_log_err}")

                    # Read compute message files (.bco## for 5.x, .computeMsgs.txt/.comp_msgs.txt for 6.x+)
                    plan_num_str = RasUtils.normalize_ras_number(plan_number)
                    try:
                        bco_path = Path(compute_ras.project_folder) / f"{compute_ras.project_name}.bco{plan_num_str}"
                        if bco_path.exists():
                            bco_content = bco_path.read_text(encoding='utf-8', errors='ignore')
                            if bco_content.strip():
                                logger.error(f"Compute messages from {bco_path.name}:\n{bco_content}")
                            else:
                                logger.debug(f"BCO file {bco_path.name} exists but is empty")
                    except Exception as bco_err:
                        logger.debug(f"Could not read .bco file: {bco_err}")

                    try:
                        for suffix in [f".p{plan_num_str}.computeMsgs.txt", f".p{plan_num_str}.comp_msgs.txt"]:
                            msg_path = Path(compute_ras.project_folder) / f"{compute_ras.project_name}{suffix}"
                            if msg_path.exists():
                                msg_content = msg_path.read_text(encoding='utf-8', errors='ignore')
                                if msg_content.strip():
                                    logger.error(f"Compute messages from {msg_path.name}:\n{msg_content}")
                                break
                    except Exception as msg_err:
                        logger.debug(f"Could not read compute messages file: {msg_err}")

                    # Callback: execution complete (failure case)
                    if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                        stream_callback.on_exec_complete(str(plan_number), False, run_time)

                    _success = False
        except Exception as e:
            logger.critical(f"Error in compute_plan: {str(e)}")
            _success = False
        finally:
            if _watchdog:
                _watchdog.stop()

            if (
                _did_execute
                and _execution_quiesced
                and _execution_result_format is not None
                and 'compute_ras' in locals()
            ):
                try:
                    # Modern HEC-RAS 1D engines recreate .O## after writing the
                    # HDF. Final cleanup is therefore required in addition to
                    # the pre-run stale-artifact cleanup.
                    finalize_plan_execution_artifacts(
                        plan_number,
                        output_format=_execution_result_format,
                        ras_object=compute_ras,
                    )
                    _result_artifacts_finalized = True
                except Exception as cleanup_error:
                    logger.error(
                        "Could not normalize result artifacts after plan %s: %s",
                        plan_number,
                        cleanup_error,
                    )
                    _success = False
            elif _did_execute and not _execution_quiesced:
                logger.critical(
                    "Skipped final result normalization for plan %s because "
                    "solver termination could not be confirmed; opposing "
                    "artifacts were left visible rather than racing an active run.",
                    plan_number,
                )
                _success = False

            _execution_details.update(
                {
                    "selected_result_format": _execution_result_format,
                    "calculation_attempted": _did_execute,
                    "solver_quiescence_confirmed": (
                        bool(_execution_quiesced) if _did_execute else None
                    ),
                    "result_artifacts_finalized": (
                        _result_artifacts_finalized
                    ),
                }
            )
            if _did_execute and not all(
                (
                    _execution_details[
                        "actual_engine_provenance_confirmed"
                    ] is True,
                    _execution_quiesced,
                    _result_artifacts_finalized,
                )
            ):
                logger.error(
                    "Plan %s did not prove all execution provenance and "
                    "terminal-safety gates",
                    plan_number,
                )
                _success = False

            # Update the RAS object's dataframes ONLY if executing in original folder
            # When dest_folder is used, the original project is unchanged
            if _ras_obj and dest_folder is None:
                try:
                    _ras_obj.plan_df = _ras_obj.get_plan_entries()
                    _ras_obj.geom_df = _ras_obj.get_geom_entries()
                    _ras_obj.flow_df = _ras_obj.get_flow_entries()
                    _ras_obj.unsteady_df = _ras_obj.get_unsteady_entries()
                    if _did_execute:
                        normalized_plan_number = RasUtils.normalize_ras_number(
                            plan_number
                        )
                        _ras_obj.update_results_df(
                            plan_numbers=[normalized_plan_number]
                        )
                        # Capture results_df row for the executed plan
                        try:
                            plan_num_str = normalized_plan_number
                            mask = _ras_obj.results_df['plan_number'] == plan_num_str
                            if mask.any():
                                _results_df_row = _ras_obj.results_df[mask].iloc[0].copy()
                        except Exception as e:
                            logger.debug(f"Could not extract results_df_row: {e}")
                except Exception as e_refresh:
                    logger.warning(f"Error refreshing DataFrames after compute_plan: {e_refresh}")
                    if _did_execute:
                        try:
                            normalized_plan_number = RasUtils.normalize_ras_number(
                                plan_number
                            )
                            RasCmdr._update_results_from_cached_plan_entries(
                                _ras_obj,
                                [normalized_plan_number],
                            )
                            mask = (
                                _ras_obj.results_df["plan_number"]
                                == normalized_plan_number
                            )
                            if mask.any():
                                _results_df_row = (
                                    _ras_obj.results_df[mask].iloc[0].copy()
                                )
                        except Exception as e_results:
                            logger.warning(
                                "Could not summarize plan %s after refresh "
                                "failure: %s",
                                plan_number,
                                e_results,
                            )

        return ComputeResult(
            success=_success,
            results_df_row=_results_df_row,
            completion_verified=bool(_success) if verify else None,
            execution_details=dict(_execution_details),
        )



    @staticmethod
    @log_call
    def compute_parallel(
        plan_number: Union[str, Number, List[Union[str, Number]], None] = None,
        max_workers: int = 2,
        num_cores: int = 2,
        clear_geompre: bool = False,
        force_geompre: bool = False,
        force_rerun: bool = False,
        ras_object: Optional['RasPrj'] = None,
        dest_folder: Union[str, Path, None] = None,
        overwrite_dest: bool = False,
        skip_existing: bool = False,
        verify: bool = False
    ) -> 'ComputeParallelResult':
        """
        Execute multiple HEC-RAS plans in parallel using multiple worker instances.

        This method creates separate worker folders for each parallel process, runs plans
        in those folders, and then consolidates results to a final destination folder.
        It's ideal for running independent plans simultaneously to make better use of system resources.

        Destination publication is fail closed. A cooperative destination
        lock and complete, globally empty HEC-RAS process inventory are
        required for the whole promotion batch. Each successful plan is then
        published as a recoverable transaction: every source is first copied
        and verified under a hidden destination stage, existing recognized
        result/message/geometry artifacts are quarantined, and the same-run
        set is committed before finalization. A provable failure restores the
        exact prior destination state; otherwise the transaction backups and
        worker folder are retained and later publication is refused. The
        corresponding paths and failure evidence are available in
        ``execution_details_by_plan``.

        Args:
            plan_number (Union[str, List[str], None]): Plan number(s) to compute.
                If None, all plans in the project are computed.
                If string, only that plan will be computed.
                If list, all specified plans will be computed.
                Recommended to use two-digit strings for plan numbers for consistency (e.g., "01" instead of 1).
            max_workers (int): Maximum number of parallel workers (separate HEC-RAS instances).
                Each worker gets a separate folder with a copy of the project.
                Optimal value depends on CPU cores and memory available.
                A good starting point is: max_workers = floor(physical_cores / num_cores).
            num_cores (int): Number of cores to use per plan computation.
                Controls computational resources allocated to each individual HEC-RAS instance.
                For parallel execution, 2-4 cores per worker often provides the best balance.
            clear_geompre (bool): Whether to clear geometry preprocessor files (.c## files) before computation.
                Set to True when geometry has been modified to force recomputation.
            force_geompre (bool): Force full geometry reprocessing. Defaults to False.
                Clears the cached preprocessor tables inside each plan's .g##.hdf (in place,
                preserving the land cover / terrain association) and the .c## files, then
                rebuilds the tables via RasProcess.exe. Best effort: if RasProcess.exe is
                unavailable the cleared tables are re-derived by the solver during the run.
                Implies force_rerun for each plan, since the currency check cannot detect changes
                to the cached .g##.hdf or to the land cover sidecars that feed it.
            force_rerun (bool): Force execution even if results are current. Defaults to False.
                When False (default), checks file modification times and skips if results are current.
            ras_object (Optional[RasPrj]): RAS project object. If None, uses global 'ras' instance.
                Useful when working with multiple projects simultaneously.
            dest_folder (Union[str, Path, None]): Destination folder for computed results.
                If None, results are consolidated back to the original project folder.
                If string, creates folder in the project's parent directory.
                If Path, uses the exact path provided.
            overwrite_dest (bool): Whether to overwrite existing destination folder.
                Set to True to replace an existing destination folder with the same name.
            skip_existing (bool): If True, skip computation for plans whose
                selected engine result family already verifies. Defaults to False.
                Skipped plans are marked as successful (True) in results. Checked on source folder.
            verify (bool): If True, verify each selected result family after
                execution. Defaults to False.
                Plans that fail verification are marked False in results.

        Returns:
            ComputeParallelResult: Result object backward compatible with Dict[str, bool].
                ``execution_results``: Dict of plan numbers to success booleans.
                ``results_df``: DataFrame with results_df rows for executed plans.
                ``execution_details_by_plan``: JSON-safe execution details
                keyed by plan number, or an empty object when unavailable.
                Existing code like ``for plan, ok in results.items():`` still works.
                When skip_existing=True, skipped plans return True.
                When verify=True, plans failing verification return False.

        Raises:
            ValueError: If the destination folder already exists, is not empty, and overwrite_dest is False.
            FileNotFoundError: If project files cannot be found.
            PermissionError: If there are issues accessing or writing to folders.
            RuntimeError: If worker initialization fails.

        Examples:
            # Run all plans in parallel with default settings
            RasCmdr.compute_parallel()

            # Run all plans with 4 workers, 2 cores per worker
            RasCmdr.compute_parallel(max_workers=4, num_cores=2)

            # Run specific plans in parallel
            RasCmdr.compute_parallel(plan_number=["01", "03"], max_workers=2)

            # Resume interrupted parallel run - skip already completed plans
            RasCmdr.compute_parallel(skip_existing=True)

            # Run with verification of successful completion
            RasCmdr.compute_parallel(verify=True)

            # Run all plans with dynamic worker allocation based on system resources
            import psutil
            physical_cores = psutil.cpu_count(logical=False)
            cores_per_worker = 2
            max_workers = max(1, physical_cores // cores_per_worker)
            RasCmdr.compute_parallel(max_workers=max_workers, num_cores=cores_per_worker)

            # Run all plans in a specific destination folder
            RasCmdr.compute_parallel(dest_folder="parallel_results", overwrite_dest=True)

        Notes:
            - Worker Assignment: Plans are assigned to workers in a round-robin fashion.
              For example, with 3 workers and 5 plans, assignment would be:
              Worker 1: Plans 1 & 4, Worker 2: Plans 2 & 5, Worker 3: Plan 3.

            - Resource Management: Each HEC-RAS instance (worker) typically requires:
              * 2-4 GB of RAM
              * 2-4 cores for optimal performance

            - When to use parallel vs. sequential:
              * Parallel: For independent plans, faster overall completion
              * Sequential: For dependent plans, consistent resource usage, easier debugging

            - The function creates worker folders during execution and consolidates results
              to the destination folder upon completion.

            - Promotion is an all-or-none safety gate for the successful
              candidate plans. Before copying any plan or shared geometry
              artifact, ras-commander holds a cooperative destination lock and
              requires a complete, globally empty strict HEC-RAS process
              inventory. A refusal marks every candidate unsuccessful and
              retains each computed worker folder; its exact recovery path and
              gate evidence are recorded in ``execution_details_by_plan``.
              The lock coordinates ras-commander promotions, but an external
              GUI or process can still start after the inventory snapshot. Do
              not run HEC-RAS manually against the destination during
              promotion.

            - Missing worker results, rejected/failed artifact copies, and
              finalization errors also retain the affected worker folder and
              mark unpromoted plans unsuccessful with exact failure evidence.
              Supporting artifacts are copied before the primary result. If a
              later step fails, ``promotion_failure`` records whether partial
              promotion is possible and lists every copied destination path.

            - This function updates the RAS object's dataframes (plan_df, geom_df, etc.) after execution.

            - skip_existing checks the SOURCE folder before creating workers. Plans with existing
              results are not assigned to workers at all.

            - verify is passed through to compute_plan() for each worker execution.
        """
        execution_results: Dict[str, bool] = {}
        execution_details_by_plan: Dict[str, Dict[str, Any]] = {}
        filtered_plan_numbers: List[str] = []
        promotion_lock_lease: Optional[Dict[str, Any]] = None

        try:
            ras_obj = ras_object or ras
            ras_obj.check_initialized()
            execution_result_format = infer_execution_result_format(ras_obj)

            project_folder = Path(ras_obj.project_folder)

            if dest_folder is not None:
                dest_folder_path = Path(dest_folder)
                if dest_folder_path.exists():
                    if overwrite_dest:
                        if not RasUtils.remove_with_retry(dest_folder_path, ras_object=None):
                            raise PermissionError(f"Unable to remove destination folder: {dest_folder_path}")
                        logger.info("Destination folder exists; overwriting as requested: %s", dest_folder_path.name)
                        logger.debug(f"Overwriting destination folder: {dest_folder_path}")
                    elif any(dest_folder_path.iterdir()):
                        error_msg = f"Destination folder '{dest_folder_path}' exists and is not empty. Use overwrite_dest=True to overwrite."
                        logger.error(error_msg)
                        raise ValueError(error_msg)
                dest_folder_path.mkdir(parents=True, exist_ok=True)
                shutil.copytree(project_folder, dest_folder_path, dirs_exist_ok=True, ignore=RasUtils.ignore_windows_reserved)
                logger.info("Copied project folder to destination: %s", dest_folder_path.name)
                logger.debug(f"Copied project folder to destination path: {dest_folder_path}")
                project_folder = dest_folder_path

            # Store filtered plan numbers separately to ensure only these are executed
            filtered_plan_entries = RasCmdr._filter_plan_entries(
                ras_obj.plan_df,
                plan_number
            )
            filtered_plan_numbers = list(filtered_plan_entries["plan_number"])

            # Filter out plans with existing results if skip_existing is True
            if skip_existing:
                plans_to_skip = []
                plans_to_compute = []
                for plan_num in filtered_plan_numbers:
                    artifact_paths = get_plan_result_artifact_paths(
                        plan_num,
                        ras_object=ras_obj,
                    )
                    mixed_results = (
                        artifact_paths.hdf.is_file()
                        and artifact_paths.legacy_output.is_file()
                    )
                    if not mixed_results and RasCmdr._verify_result(
                        plan_num,
                        ras_obj,
                        output_format=execution_result_format,
                        check_errors=False,
                    ):
                        plans_to_skip.append(plan_num)
                        execution_results[plan_num] = True  # Mark as successful (results exist)
                        execution_details_by_plan[plan_num] = {
                            "execution_api": "ras_cmdr",
                            "engine_kind": "executable",
                            "selected_result_format": execution_result_format,
                            "calculation_attempted": False,
                            "solver_quiescence_confirmed": None,
                            "result_artifacts_finalized": False,
                            "actual_engine_provenance_confirmed": False,
                            "selected_executable_path": None,
                            "selected_executable_sha256": None,
                            "launcher_pid": None,
                            "launcher_create_time": None,
                        }
                    else:
                        if mixed_results:
                            logger.warning(
                                "Plan %s has both HDF and legacy results; "
                                "parallel skip_existing will rerun it to "
                                "normalize artifacts.",
                                plan_num,
                            )
                        plans_to_compute.append(plan_num)
                if plans_to_skip:
                    logger.info(f"Skipping {len(plans_to_skip)} plans with existing results: {plans_to_skip}")
                filtered_plan_numbers = plans_to_compute

            num_plans = len(filtered_plan_numbers)

            # If all plans were skipped, return early
            if num_plans == 0:
                if execution_results:
                    logger.info("All plans skipped (existing results found). No computation needed.")
                else:
                    logger.warning("No plans matched the requested plan filter. No computation needed.")
                # Try to populate results_df from existing results
                _results_df = pd.DataFrame()
                try:
                    if hasattr(ras_obj, 'results_df') and ras_obj.results_df is not None:
                        mask = ras_obj.results_df['plan_number'].isin(list(execution_results.keys()))
                        if mask.any():
                            _results_df = ras_obj.results_df[mask].copy()
                except Exception:
                    pass
                return ComputeParallelResult(
                    execution_results=execution_results,
                    results_df=_results_df,
                    execution_details_by_plan=execution_details_by_plan,
                )

            max_workers = min(max_workers, num_plans)
            logger.info(f"Adjusted max_workers to {max_workers} based on the number of plans to compute: {num_plans}")

            worker_ras_objects = {}
            worker_plan_numbers: Dict[int, List[str]] = defaultdict(list)
            for worker_id in range(1, max_workers + 1):
                worker_folder = project_folder.parent / f"{project_folder.name} [Worker {worker_id}]"
                if worker_folder.exists():
                    if not RasUtils.remove_with_retry(worker_folder, ras_object=None):
                        raise PermissionError(f"Unable to remove existing worker folder: {worker_folder}")
                    logger.debug(f"Removed existing worker folder: {worker_folder}")
                shutil.copytree(project_folder, worker_folder, ignore=RasUtils.ignore_windows_reserved)
                logger.debug(f"Created worker folder {worker_id}: {worker_folder}")

                try:
                    worker_ras = RasPrj()
                    worker_ras_object = init_ras_project(
                        ras_project_folder=worker_folder,
                        ras_version=ras_obj.ras_exe_path,
                        ras_object=worker_ras,
                        hide_intro=True,
                    )
                    worker_ras_objects[worker_id] = worker_ras_object
                except Exception as e:
                    logger.critical(f"Failed to initialize RAS project for worker {worker_id}: {str(e)}")
                    worker_ras_objects[worker_id] = None
            logger.info(f"Prepared {max_workers} worker folder(s) for parallel execution")

            # Explicitly use the filtered plan numbers for assignments
            worker_cycle = cycle(range(1, max_workers + 1))
            plan_assignments = [(next(worker_cycle), plan_num) for plan_num in filtered_plan_numbers]
            for worker_id, plan_num in plan_assignments:
                worker_plan_numbers[worker_id].append(plan_num)

            # These plans are now known to execute. Remove both copied final
            # result families and stale messages inside the disposable worker
            # folders so a zero-exit/no-output run cannot promote source data
            # as a fresh worker result. Preserve .tmp.hdf preprocessing input.
            for worker_id, plan_num in plan_assignments:
                worker_ras = worker_ras_objects[worker_id]
                if worker_ras is None:
                    continue
                _remove_plan_execution_artifacts(
                    plan_num,
                    result_format="both",
                    include_message_sidecars=True,
                    ras_object=worker_ras,
                )

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit futures and track which plan each future represents
                future_to_plan = {}
                for worker_id, plan_num in plan_assignments:
                    future = executor.submit(
                        RasCmdr.compute_plan,
                        plan_num,
                        ras_object=worker_ras_objects[worker_id],
                        clear_geompre=clear_geompre,
                        force_geompre=force_geompre,
                        force_rerun=True,  # Always force execution in workers - plans passed skip_existing filter
                        num_cores=num_cores,
                        verify=verify
                    )
                    future_to_plan[future] = (worker_id, plan_num)

                # Process futures as they complete (not in submission order)
                for future in as_completed(future_to_plan.keys()):
                    worker_id, plan_num = future_to_plan[future]
                    try:
                        compute_result = future.result()
                        # Extract bool from ComputeResult for execution_results dict
                        execution_results[plan_num] = bool(compute_result)
                        details = getattr(compute_result, "execution_details", None)
                        execution_details_by_plan[plan_num] = (
                            dict(details) if isinstance(details, dict) else {}
                        )
                        if compute_result:
                            logger.debug(f"Plan {plan_num} executed in worker {worker_id}: Successful")
                        else:
                            logger.warning(f"Plan {plan_num} executed in worker {worker_id}: Failed")
                    except Exception as e:
                        execution_results[plan_num] = False
                        execution_details_by_plan[plan_num] = {}
                        logger.error(f"Plan {plan_num} failed in worker {worker_id}: {str(e)}")

            # Consolidate results: use dest_folder if provided, otherwise back to original folder
            # This eliminates the [Computed] folder anti-pattern - results go directly to original project
            if dest_folder is not None:
                final_dest_folder = dest_folder_path
                final_dest_folder.mkdir(parents=True, exist_ok=True)
                logger.info(
                    "Consolidating worker artifacts to destination folder: %s",
                    final_dest_folder.name,
                )
                logger.debug(f"Consolidating worker artifacts to destination path: {final_dest_folder}")
            else:
                final_dest_folder = project_folder
                logger.info(
                    "Consolidating worker artifacts back to original project folder: %s",
                    final_dest_folder.name,
                )
                logger.debug(f"Consolidating worker artifacts back to original project path: {final_dest_folder}")

            consolidated_artifact_count = 0
            promoted_geometry_numbers: set[str] = set()
            promoted_plan_numbers: set[str] = set()
            promotion_candidates = sorted(
                {
                    plan_num
                    for _, plan_num in plan_assignments
                    if execution_results.get(plan_num, False)
                }
            )
            promotion_allowed = True
            promotion_gate_evidence: Dict[str, Any] = {}
            promotion_lock_evidence: Dict[str, Any] = {}
            if promotion_candidates:
                (
                    promotion_lock_lease,
                    promotion_lock_evidence,
                ) = RasCmdr._acquire_destination_promotion_lock(
                    project_folder=final_dest_folder,
                    project_name=ras_obj.project_name,
                )
                if promotion_lock_lease is None:
                    promotion_allowed = False
                    promotion_gate_evidence = {
                        "complete": False,
                        "quiescence_confirmed": None,
                        "destination_folder": str(final_dest_folder),
                        "project_path": str(
                            final_dest_folder / f"{ras_obj.project_name}.prj"
                        ),
                        "plan_inventories": {},
                        "blocked_plan_numbers": [],
                        "global_processes": [],
                        "query_errors": [],
                        "resolution_errors": [],
                        "promotion_lock": promotion_lock_evidence,
                    }
                else:
                    (
                        promotion_allowed,
                        promotion_gate_evidence,
                    ) = RasCmdr._destination_promotion_process_gate(
                        promotion_candidates,
                        project_folder=final_dest_folder,
                        project_name=ras_obj.project_name,
                    )
                    promotion_gate_evidence["promotion_lock"] = (
                        promotion_lock_evidence
                    )
            if not promotion_allowed:
                retained_worker_folders = {
                    plan_num: str(
                        Path(worker_ras_objects[worker_id].project_folder)
                    )
                    for worker_id, plan_num in plan_assignments
                    if worker_ras_objects.get(worker_id) is not None
                }
                promotion_candidate_set = set(promotion_candidates)
                for plan_num, retained_folder in (
                    retained_worker_folders.items()
                ):
                    details = dict(
                        execution_details_by_plan.get(plan_num, {})
                    )
                    details["retained_worker_folder"] = retained_folder
                    if plan_num in promotion_candidate_set:
                        execution_results[plan_num] = False
                        details["failure_stage"] = (
                            "destination_promotion_process_gate"
                        )
                        details["destination_promotion_process_gate"] = (
                            promotion_gate_evidence
                        )
                    execution_details_by_plan[plan_num] = details
                logger.error(
                    "Refused the entire worker-result promotion because "
                    "destination exact-plan quiescence was not proved: %s",
                    promotion_gate_evidence,
                )
            promotion_integrity_lost = False
            promotion_integrity_failure: Dict[str, Any] = {}
            for worker_id, worker_ras in worker_ras_objects.items():
                if worker_ras is None:
                    continue
                worker_folder = Path(worker_ras.project_folder)
                assigned_plan_numbers = worker_plan_numbers.get(worker_id, [])
                retained_worker_folder = str(
                    worker_folder.resolve(strict=False)
                )
                worker_must_be_retained = not promotion_allowed
                current_plan_number: Optional[str] = None
                current_failure_stage = "destination_promotion_preparation"
                current_source_path: Optional[Path] = None
                current_destination_path: Optional[Path] = None
                copied_destinations_by_plan: Dict[str, List[str]] = {
                    plan_num: [] for plan_num in assigned_plan_numbers
                }
                try:
                    # First, close any open resources in the worker RAS object
                    worker_ras.close() if hasattr(worker_ras, 'close') else None
                    
                    # Add a small delay to ensure file handles are released
                    time.sleep(1)

                    if not promotion_allowed:
                        logger.warning(
                            "Retained computed worker folder after promotion "
                            "refusal: %s",
                            worker_folder,
                        )
                        continue
                    if promotion_integrity_lost:
                        worker_must_be_retained = True
                        failure_detail = (
                            "A prior plan promotion could not prove exact "
                            "destination rollback; refusing later publication"
                        )
                        for plan_num in assigned_plan_numbers:
                            if (
                                execution_results.get(plan_num, False)
                                and plan_num not in promoted_plan_numbers
                            ):
                                execution_results[plan_num] = False
                                details = dict(
                                    execution_details_by_plan.get(
                                        plan_num,
                                        {},
                                    )
                                )
                                details.update(
                                    {
                                        "failure_stage": (
                                            "destination_promotion_aborted_unrestored"
                                        ),
                                        "failure_detail": failure_detail,
                                        "promotion_failure": (
                                            promotion_integrity_failure
                                        ),
                                    }
                                )
                                execution_details_by_plan[plan_num] = details
                        continue

                    # Move files with retry mechanism
                    max_retries = 3
                    for retry in range(max_retries):
                        try:
                            for plan_num in assigned_plan_numbers:
                                if (
                                    not execution_results.get(plan_num, False)
                                    or plan_num in promoted_plan_numbers
                                ):
                                    continue
                                current_plan_number = plan_num
                                current_failure_stage = (
                                    "destination_promotion_inventory"
                                )
                                current_source_path = None
                                current_destination_path = None
                                artifact_paths = get_plan_result_artifact_paths(
                                    plan_num,
                                    ras_object=worker_ras,
                                )
                                primary_result = (
                                    artifact_paths.hdf
                                    if execution_result_format == "hdf"
                                    else artifact_paths.legacy_output
                                )
                                source_sidecars = [
                                    path
                                    for path in artifact_paths.message_sidecars
                                    if path.is_file()
                                ]
                                geometry_number = RasCmdr._get_plan_geometry_number(
                                    filtered_plan_entries,
                                    plan_num
                                )
                                promote_geometry = bool(
                                    geometry_number
                                    and geometry_number
                                    not in promoted_geometry_numbers
                                )
                                geometry_source = None
                                if promote_geometry:
                                    geometry_hdf = (
                                        worker_folder
                                        / f"{worker_ras.project_name}.g"
                                        f"{geometry_number}.hdf"
                                    )
                                    if geometry_hdf.is_file():
                                        geometry_source = geometry_hdf
                                (
                                    promotion_succeeded,
                                    promotion_evidence,
                                ) = RasCmdr._publish_plan_artifacts_transaction(
                                    plan_num,
                                    source_primary=primary_result,
                                    source_sidecars=source_sidecars,
                                    geometry_source=geometry_source,
                                    output_format=execution_result_format,
                                    ras_object=ras_obj,
                                    destination_folder=final_dest_folder,
                                    project_name=worker_ras.project_name,
                                )
                                if not promotion_succeeded:
                                    execution_results[plan_num] = False
                                    worker_must_be_retained = True
                                    details = dict(
                                        execution_details_by_plan.get(
                                            plan_num,
                                            {},
                                        )
                                    )
                                    details.update(
                                        {
                                            "failure_stage": (
                                                promotion_evidence[
                                                    "failure_stage"
                                                ]
                                            ),
                                            "failure_detail": (
                                                promotion_evidence[
                                                    "failure_detail"
                                                ]
                                            ),
                                            "retained_worker_folder": (
                                                retained_worker_folder
                                            ),
                                            "promotion_failure": (
                                                promotion_evidence
                                            ),
                                        }
                                    )
                                    execution_details_by_plan[plan_num] = (
                                        details
                                    )
                                    if not promotion_evidence.get(
                                        "rollback_confirmed",
                                        False,
                                    ):
                                        promotion_integrity_lost = True
                                        promotion_integrity_failure = (
                                            promotion_evidence
                                        )
                                        break
                                    continue
                                copied_destinations_by_plan[plan_num] = list(
                                    promotion_evidence[
                                        "copied_destination_paths"
                                    ]
                                )
                                consolidated_artifact_count += len(
                                    copied_destinations_by_plan[plan_num]
                                )
                                if geometry_source is not None:
                                    promoted_geometry_numbers.add(
                                        geometry_number
                                    )
                                promoted_plan_numbers.add(plan_num)

                            if promotion_integrity_lost:
                                worker_must_be_retained = True
                                failure_detail = (
                                    "A plan promotion could not prove exact "
                                    "destination rollback; refusing later "
                                    "publication"
                                )
                                for plan_num in assigned_plan_numbers:
                                    if (
                                        execution_results.get(plan_num, False)
                                        and plan_num
                                        not in promoted_plan_numbers
                                    ):
                                        execution_results[plan_num] = False
                                        details = dict(
                                            execution_details_by_plan.get(
                                                plan_num,
                                                {},
                                            )
                                        )
                                        details.update(
                                            {
                                                "failure_stage": (
                                                    "destination_promotion_aborted_unrestored"
                                                ),
                                                "failure_detail": (
                                                    failure_detail
                                                ),
                                                "retained_worker_folder": (
                                                    retained_worker_folder
                                                ),
                                                "promotion_failure": (
                                                    promotion_integrity_failure
                                                ),
                                            }
                                        )
                                        execution_details_by_plan[
                                            plan_num
                                        ] = details
                             
                            # Add another small delay before removal
                            time.sleep(1)

                            if worker_must_be_retained:
                                logger.warning(
                                    "Retained worker folder after a plan "
                                    "promotion failure: %s",
                                    worker_folder,
                                )
                                break

                            # Try to remove the worker folder
                            current_failure_stage = "worker_folder_cleanup"
                            current_plan_number = None
                            if worker_folder.exists():
                                if not RasUtils.remove_with_retry(worker_folder, ras_object=None):
                                    raise PermissionError(f"Unable to remove worker folder: {worker_folder}")
                            break  # If successful, break the retry loop
                            
                        except PermissionError as pe:
                            if retry == max_retries - 1:  # If this was the last retry
                                logger.error(f"Failed to move/remove files after {max_retries} attempts: {str(pe)}")
                                raise
                            time.sleep(2 ** retry)  # Exponential backoff
                            continue
                            
                except Exception as e:
                    worker_must_be_retained = True
                    failure_detail = f"{type(e).__name__}: {e}"
                    for plan_num in assigned_plan_numbers:
                        details = dict(
                            execution_details_by_plan.get(plan_num, {})
                        )
                        details["retained_worker_folder"] = (
                            retained_worker_folder
                        )
                        if (
                            execution_results.get(plan_num, False)
                            and plan_num not in promoted_plan_numbers
                        ):
                            execution_results[plan_num] = False
                            plan_failure_stage = (
                                current_failure_stage
                                if plan_num == current_plan_number
                                else "destination_promotion_aborted"
                            )
                            details.update(
                                {
                                    "failure_stage": plan_failure_stage,
                                    "failure_detail": failure_detail,
                                    "promotion_failure": {
                                        "exception_type": type(e).__name__,
                                        "detail": failure_detail,
                                        "source_path": (
                                            str(current_source_path)
                                            if plan_num
                                            == current_plan_number
                                            and current_source_path is not None
                                            else None
                                        ),
                                        "destination_path": (
                                            str(current_destination_path)
                                            if plan_num
                                            == current_plan_number
                                            and current_destination_path
                                            is not None
                                            else None
                                        ),
                                        "copied_destination_paths": list(
                                            copied_destinations_by_plan.get(
                                                plan_num,
                                                [],
                                            )
                                        ),
                                        "partial_promotion_possible": bool(
                                            copied_destinations_by_plan.get(
                                                plan_num,
                                                [],
                                            )
                                        ),
                                    },
                                }
                            )
                        elif current_failure_stage == "worker_folder_cleanup":
                            details["worker_cleanup_failure"] = {
                                "exception_type": type(e).__name__,
                                "detail": failure_detail,
                            }
                        execution_details_by_plan[plan_num] = details
                    logger.error(f"Error moving results from {worker_folder} to {final_dest_folder}: {str(e)}")
                finally:
                    if worker_must_be_retained:
                        for plan_num in assigned_plan_numbers:
                            details = dict(
                                execution_details_by_plan.get(plan_num, {})
                            )
                            details["retained_worker_folder"] = (
                                retained_worker_folder
                            )
                            execution_details_by_plan[plan_num] = details

            if promotion_lock_lease is not None:
                if not RasCmdr._release_destination_promotion_lock(
                    promotion_lock_lease
                ):
                    logger.warning(
                        "Did not remove destination promotion lock because "
                        "ownership could not be reverified: %s",
                        promotion_lock_evidence.get("lock_path"),
                    )
                promotion_lock_lease = None

            logger.info(
                "Consolidated %s worker artifact(s) to %s",
                consolidated_artifact_count,
                final_dest_folder.name
            )
            logger.debug(f"Consolidated worker artifacts to destination path: {final_dest_folder}")

            # When dest_folder is used, re-initialize ras_obj from dest_folder
            # This ensures results_df reflects results in the destination folder
            if dest_folder is not None:
                try:
                    ras_obj.initialize(final_dest_folder, ras_obj.ras_exe_path)
                    logger.info("Re-initialized ras_object from destination folder: %s", final_dest_folder.name)
                    logger.debug(f"Re-initialized ras_object from destination path: {final_dest_folder}")
                except Exception as e:
                    logger.critical(f"Failed to re-initialize ras_object from destination folder: {str(e)}")

            RasCmdr._log_execution_results(execution_results)

            ras_obj = ras_object or ras
            try:
                ras_obj.plan_df = ras_obj.get_plan_entries()
                ras_obj.geom_df = ras_obj.get_geom_entries()
                ras_obj.flow_df = ras_obj.get_flow_entries()
                ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
                ras_obj.update_results_df(plan_numbers=list(execution_results.keys()))
            except Exception as e_refresh:
                logger.warning(
                    "Error refreshing DataFrames after compute_parallel: %s. "
                    "Using cached plan metadata and expected result paths.",
                    e_refresh,
                )
                try:
                    RasCmdr._update_results_from_cached_plan_entries(
                        ras_obj,
                        list(execution_results.keys()),
                        project_folder=final_dest_folder,
                        project_name=ras_obj.project_name,
                        plan_entries=filtered_plan_entries,
                    )
                except Exception as e_results:
                    logger.error(
                        "Could not summarize parallel results after refresh "
                        "failure: %s",
                        e_results,
                    )

            # Extract results_df rows for executed plans
            _results_df = pd.DataFrame()
            try:
                plan_nums = list(execution_results.keys())
                if hasattr(ras_obj, 'results_df') and ras_obj.results_df is not None and len(ras_obj.results_df) > 0:
                    mask = ras_obj.results_df['plan_number'].isin(plan_nums)
                    if mask.any():
                        _results_df = ras_obj.results_df[mask].copy()
            except Exception as e:
                logger.debug(f"Could not extract results_df for parallel plans: {e}")

            for plan_num in execution_results:
                execution_details_by_plan.setdefault(plan_num, {})
            return ComputeParallelResult(
                execution_results=execution_results,
                results_df=_results_df,
                execution_details_by_plan=execution_details_by_plan,
            )

        except Exception as e:
            logger.critical(f"Error in compute_parallel: {str(e)}")
            for plan_num in filtered_plan_numbers:
                execution_results.setdefault(plan_num, False)
                execution_details_by_plan.setdefault(plan_num, {})
            return ComputeParallelResult(
                execution_results=execution_results,
                execution_details_by_plan=execution_details_by_plan,
            )
        finally:
            if promotion_lock_lease is not None:
                if not RasCmdr._release_destination_promotion_lock(
                    promotion_lock_lease
                ):
                    logger.warning(
                        "Preserved destination promotion lock after ownership "
                        "verification failed: %s",
                        promotion_lock_lease.get("path"),
                    )

    @staticmethod
    @log_call
    def compute_test_mode(
        plan_number: Union[str, Number, List[Union[str, Number]], None] = None,
        dest_folder_suffix="[Test]",
        clear_geompre=False,
        force_geompre: bool = False,
        force_rerun: bool = False,
        num_cores=None,
        ras_object=None,
        overwrite_dest=False,
        skip_existing: bool = False,
        verify: bool = False
    ) -> 'ComputeParallelResult':
        """
        Execute HEC-RAS plans sequentially in a separate test folder.

        This function creates a separate test folder, copies the project there, and executes
        the specified plans in sequential order. It's useful for batch processing plans that
        need to be run in a specific order or when you want to ensure consistent resource usage.

        Result publication uses the same fail-closed global process gate,
        cooperative destination lock, and per-plan staged transaction as
        ``compute_parallel``. On refusal or failure, the fresh test folder is
        retained and its exact recovery path is recorded in
        ``execution_details_by_plan``. If exact destination rollback cannot be
        proved, later plan publication is refused and the hidden transaction
        backups remain available for recovery.

        Args:
            plan_number (Union[str, Number, List[Union[str, Number]], None], optional): Plan number or list of plan numbers to execute (e.g., "01", 1, 1.0, or ["01", 2]).
                If None, all plans will be executed. Default is None.
                Recommended to use two-digit strings for plan numbers for consistency (e.g., "01" instead of 1).
            dest_folder_suffix (str, optional): Suffix to append to the test folder name.
                Defaults to "[Test]".
                The test folder is always created in the project folder's parent directory.
            clear_geompre (bool, optional): Whether to clear geometry preprocessor files (.c## files).
                Defaults to False.
                Set to True when geometry has been modified to force recomputation.
            force_geompre (bool, optional): Force full geometry reprocessing. Defaults to False.
                Clears the cached preprocessor tables inside each plan's .g##.hdf (in place,
                preserving the land cover / terrain association) and the .c## files, then
                rebuilds the tables via RasProcess.exe. Best effort: if RasProcess.exe is
                unavailable the cleared tables are re-derived by the solver during the run.
                Implies force_rerun for each plan, since the currency check cannot detect changes
                to the cached .g##.hdf or to the land cover sidecars that feed it.
            force_rerun (bool, optional): Force execution even if results are current. Defaults to False.
                When False (default), checks file modification times and skips if results are current.
            num_cores (int, optional): Number of cores to use for each plan.
                If None, the current setting in the plan file is not changed. Default is None.
                For sequential execution, 4-8 cores often provides good performance.
            ras_object (RasPrj, optional): Specific RAS object to use. If None, uses the global ras instance.
                Useful when working with multiple projects simultaneously.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists.
                Defaults to False.
                Set to True to replace an existing test folder with the same name.
            skip_existing (bool, optional): If True, skip plans whose selected
                engine result family already verifies. Defaults to False.
                Skipped plans are marked as successful (True) in results. Check happens in test folder.
            verify (bool, optional): If True, verify each selected result family
                after execution. Defaults to False.
                Plans that fail verification are marked False in results.

        Returns:
            ComputeParallelResult: Result object backward compatible with Dict[str, bool].
                ``execution_results``: Dict of plan numbers to success booleans.
                ``results_df``: DataFrame with results_df rows for executed plans.
                ``execution_details_by_plan``: JSON-safe execution details
                keyed by plan number, or an empty object when unavailable.
                Existing code like ``for plan, ok in results.items():`` still works.
                When skip_existing=True, skipped plans return True.
                When verify=True, plans failing verification return False.

        Raises:
            ValueError: If the destination folder already exists, is not empty, and overwrite_dest is False.
            FileNotFoundError: If project files cannot be found.
            PermissionError: If there are issues accessing or writing to folders.

        Examples:
            # Run all plans sequentially
            RasCmdr.compute_test_mode()

            # Run a specific plan
            RasCmdr.compute_test_mode(plan_number="01")

            # Run multiple specific plans
            RasCmdr.compute_test_mode(plan_number=["01", "03", "05"])

            # Run plans with a custom folder suffix
            RasCmdr.compute_test_mode(dest_folder_suffix="[SequentialRun]")

            # Run plans with a specific number of cores
            RasCmdr.compute_test_mode(num_cores=4)

            # Resume interrupted test run - skip completed plans
            RasCmdr.compute_test_mode(skip_existing=True)

            # Run with verification of successful completion
            RasCmdr.compute_test_mode(verify=True)

            # Run specific plans with multiple options
            RasCmdr.compute_test_mode(
                plan_number=["01", "02"],
                dest_folder_suffix="[SpecificSequential]",
                clear_geompre=True,
                num_cores=6,
                overwrite_dest=True,
                verify=True
            )

        Notes:
            - This function was created to replicate the original HEC-RAS command line -test flag,
              which does not work in recent versions of HEC-RAS.

            - Key differences from other compute functions:
              * compute_plan: Runs a single plan, with option for destination folder
              * compute_parallel: Runs multiple plans simultaneously in worker folders
              * compute_test_mode: Runs multiple plans sequentially in a single test folder

            - Use cases:
              * Running plans in a specific order
              * Ensuring consistent resource usage
              * Easier debugging (one plan at a time)
              * Isolated test environment

            - Performance considerations:
              * Sequential execution is generally slower overall than parallel execution
              * Each plan gets consistent resource usage
              * Execution time scales linearly with the number of plans

            - Promotion is all-or-none for the successful candidate plans.
              Before copying any plan or shared geometry artifact,
              ras-commander holds a cooperative destination lock and requires
              a complete, globally empty strict HEC-RAS process inventory. A
              refusal marks every candidate unsuccessful and retains the test
              folder; its exact recovery path and gate evidence are recorded
              in ``execution_details_by_plan``. The lock coordinates
              ras-commander promotions, but cannot close the race with a
              manually launched HEC-RAS GUI/process after the process scan.

            - Missing results, rejected/failed copies, and finalization errors
              retain the test folder and record its exact path plus structured
              failure evidence. Supporting artifacts are copied before the
              primary result; any already copied paths are reported when a
              later failure makes partial promotion possible.

            - This function updates the RAS object's dataframes (plan_df, geom_df, etc.) after execution.

            - skip_existing checks the TEST folder after copying. This allows resuming interrupted test runs.

            - verify is passed through to compute_plan() for each plan execution.
        """
        promotion_lock_lease: Optional[Dict[str, Any]] = None
        try:
            ras_obj = ras_object or ras
            ras_obj.check_initialized()
            
            logger.info("Starting the compute_test_mode...")
               
            project_folder = Path(ras_obj.project_folder)

            if not project_folder.exists():
                logger.error(f"Project folder '{project_folder}' does not exist.")
                return ComputeParallelResult()

            compute_folder = project_folder.parent / f"{project_folder.name} {dest_folder_suffix}"
            logger.info("Creating test folder: %s", compute_folder.name)
            logger.debug(f"Creating test folder path: {compute_folder}")

            if compute_folder.exists():
                if overwrite_dest:
                    shutil.rmtree(compute_folder)
                    logger.info("Compute folder exists; overwriting as requested: %s", compute_folder.name)
                    logger.debug(f"Overwriting compute folder: {compute_folder}")
                elif any(compute_folder.iterdir()):
                    error_msg = (
                        f"Compute folder '{compute_folder}' exists and is not empty. "
                        "Use overwrite_dest=True to overwrite."
                    )
                    logger.error(error_msg)
                    raise ValueError(error_msg)

            try:
                shutil.copytree(project_folder, compute_folder, ignore=RasUtils.ignore_windows_reserved)
                logger.info("Copied project folder to compute folder: %s", compute_folder.name)
                logger.debug(f"Copied project folder to compute folder path: {compute_folder}")
            except Exception as e:
                logger.critical(f"Error occurred while copying project folder: {str(e)}")
                return ComputeParallelResult()

            try:
                compute_ras = RasPrj()
                compute_ras.initialize(compute_folder, ras_obj.ras_exe_path)
                compute_prj_path = compute_ras.prj_file
                execution_result_format = infer_execution_result_format(
                    compute_ras
                )
                logger.info("Initialized RAS project in compute folder: %s", compute_folder.name)
                logger.debug(f"Initialized RAS project file in compute folder: {compute_prj_path}")
            except Exception as e:
                logger.critical(f"Error initializing RAS project in compute folder: {str(e)}")
                return ComputeParallelResult()

            if not compute_prj_path:
                logger.error("Project file not found.")
                return ComputeParallelResult()

            logger.debug("Getting plan entries...")
            try:
                ras_compute_plan_entries = compute_ras.plan_df
                logger.debug("Retrieved plan entries successfully.")
            except Exception as e:
                logger.critical(f"Error retrieving plan entries: {str(e)}")
                return ComputeParallelResult()

            ras_compute_plan_entries = RasCmdr._filter_plan_entries(
                ras_compute_plan_entries,
                plan_number
            )

            execution_results = {}
            execution_details_by_plan: Dict[str, Dict[str, Any]] = {}
            logger.info("Running selected plans sequentially...")
            for _, plan in ras_compute_plan_entries.iterrows():
                current_plan_number = plan["plan_number"]
                artifact_paths = get_plan_result_artifact_paths(
                    current_plan_number,
                    ras_object=compute_ras,
                )
                mixed_results = (
                    artifact_paths.hdf.is_file()
                    and artifact_paths.legacy_output.is_file()
                )
                verified_skip = (
                    skip_existing
                    and not mixed_results
                    and RasCmdr._verify_result(
                        current_plan_number,
                        compute_ras,
                        output_format=execution_result_format,
                        check_errors=False,
                    )
                )
                if not verified_skip:
                    _remove_plan_execution_artifacts(
                        current_plan_number,
                        result_format="both",
                        include_message_sidecars=True,
                        ras_object=compute_ras,
                    )
                start_time = time.time()
                try:
                    compute_result = RasCmdr.compute_plan(
                        current_plan_number,
                        ras_object=compute_ras,
                        clear_geompre=clear_geompre,
                        force_geompre=force_geompre,
                        force_rerun=True,  # Always force execution in test folder - bypass broken smart skip from copytree timestamp preservation
                        num_cores=num_cores,
                        skip_existing=skip_existing,  # Still respected (skip_existing check happens before force_rerun check)
                        verify=verify
                    )
                    # Extract bool from ComputeResult for execution_results dict
                    execution_results[current_plan_number] = bool(compute_result)
                    details = getattr(compute_result, "execution_details", None)
                    execution_details_by_plan[current_plan_number] = (
                        dict(details) if isinstance(details, dict) else {}
                    )
                    if compute_result:
                        logger.debug(f"Successfully computed plan {current_plan_number}")
                    else:
                        logger.error(f"Failed to compute plan {current_plan_number}")
                except Exception as e:
                    execution_results[current_plan_number] = False
                    execution_details_by_plan[current_plan_number] = {}
                    logger.error(f"Error computing plan {current_plan_number}: {str(e)}")
                finally:
                    end_time = time.time()
                    run_time = end_time - start_time
                    logger.debug(f"Total run time for plan {current_plan_number}: {run_time:.2f} seconds")

            logger.info("All selected plans have been executed.")

            # Promote only artifacts owned by plans that actually succeeded.
            # The previous broad *.hdf copy could publish unrelated or stale
            # results from the copied test project.
            logger.info(
                "Consolidating successful plan artifacts from test folder "
                "back to original project folder"
            )
            logger.debug(
                "Consolidating plan artifacts from %s back to %s",
                compute_folder,
                project_folder,
            )
            artifact_files_copied = 0
            promotion_candidates = sorted(
                plan_number
                for plan_number, succeeded in execution_results.items()
                if succeeded
            )
            promotion_allowed = True
            promotion_gate_evidence: Dict[str, Any] = {}
            promotion_lock_evidence: Dict[str, Any] = {}
            if promotion_candidates:
                (
                    promotion_lock_lease,
                    promotion_lock_evidence,
                ) = RasCmdr._acquire_destination_promotion_lock(
                    project_folder=project_folder,
                    project_name=ras_obj.project_name,
                )
                if promotion_lock_lease is None:
                    promotion_allowed = False
                    promotion_gate_evidence = {
                        "complete": False,
                        "quiescence_confirmed": None,
                        "destination_folder": str(project_folder),
                        "project_path": str(
                            project_folder / f"{ras_obj.project_name}.prj"
                        ),
                        "plan_inventories": {},
                        "blocked_plan_numbers": [],
                        "global_processes": [],
                        "query_errors": [],
                        "resolution_errors": [],
                        "promotion_lock": promotion_lock_evidence,
                    }
                else:
                    (
                        promotion_allowed,
                        promotion_gate_evidence,
                    ) = RasCmdr._destination_promotion_process_gate(
                        promotion_candidates,
                        project_folder=project_folder,
                        project_name=ras_obj.project_name,
                    )
                    promotion_gate_evidence["promotion_lock"] = (
                        promotion_lock_evidence
                    )
            retained_test_folder = str(
                compute_folder.resolve(strict=False)
            )
            retain_test_folder = not promotion_allowed
            if not promotion_allowed:
                promotion_candidate_set = set(promotion_candidates)
                for current_plan_number in execution_results:
                    details = dict(
                        execution_details_by_plan.get(
                            current_plan_number,
                            {},
                        )
                    )
                    details["retained_test_folder"] = retained_test_folder
                    if current_plan_number in promotion_candidate_set:
                        execution_results[current_plan_number] = False
                        details["failure_stage"] = (
                            "destination_promotion_process_gate"
                        )
                        details["destination_promotion_process_gate"] = (
                            promotion_gate_evidence
                        )
                    execution_details_by_plan[current_plan_number] = details
                logger.error(
                    "Refused the entire test-mode result promotion because "
                    "destination exact-plan quiescence was not proved: %s",
                    promotion_gate_evidence,
                )
            promotion_integrity_lost = False
            promotion_integrity_failure: Dict[str, Any] = {}
            promoted_geometry_numbers: set[str] = set()
            for current_plan_number, succeeded in execution_results.items():
                if not succeeded:
                    continue
                if promotion_integrity_lost:
                    execution_results[current_plan_number] = False
                    retain_test_folder = True
                    failure_detail = (
                        "A prior plan promotion could not prove exact "
                        "destination rollback; refusing later publication"
                    )
                    details = dict(
                        execution_details_by_plan.get(
                            current_plan_number,
                            {},
                        )
                    )
                    details.update(
                        {
                            "failure_stage": (
                                "destination_promotion_aborted_unrestored"
                            ),
                            "failure_detail": failure_detail,
                            "retained_test_folder": retained_test_folder,
                            "promotion_failure": (
                                promotion_integrity_failure
                            ),
                        }
                    )
                    execution_details_by_plan[
                        current_plan_number
                    ] = details
                    continue

                try:
                    artifact_paths = get_plan_result_artifact_paths(
                        current_plan_number,
                        ras_object=compute_ras,
                    )
                    primary_result = (
                        artifact_paths.hdf
                        if execution_result_format == "hdf"
                        else artifact_paths.legacy_output
                    )
                    source_sidecars = [
                        path
                        for path in artifact_paths.message_sidecars
                        if path.is_file()
                    ]
                    geometry_number = RasCmdr._get_plan_geometry_number(
                        ras_compute_plan_entries,
                        current_plan_number,
                    )
                    geometry_source = None
                    if (
                        geometry_number
                        and geometry_number not in promoted_geometry_numbers
                    ):
                        geometry_hdf = (
                            compute_folder
                            / f"{compute_ras.project_name}.g"
                            f"{geometry_number}.hdf"
                        )
                        if geometry_hdf.is_file():
                            geometry_source = geometry_hdf
                    (
                        promotion_succeeded,
                        promotion_evidence,
                    ) = RasCmdr._publish_plan_artifacts_transaction(
                        current_plan_number,
                        source_primary=primary_result,
                        source_sidecars=source_sidecars,
                        geometry_source=geometry_source,
                        output_format=execution_result_format,
                        ras_object=ras_obj,
                        destination_folder=project_folder,
                        project_name=compute_ras.project_name,
                    )
                except Exception as exc:
                    promotion_succeeded = False
                    promotion_evidence = {
                        "failure_stage": (
                            "destination_promotion_inventory"
                        ),
                        "failure_detail": f"{type(exc).__name__}: {exc}",
                        "exception_type": type(exc).__name__,
                        "source_path": None,
                        "destination_path": None,
                        "transaction_path": None,
                        "retained_transaction_path": None,
                        "copied_destination_paths": [],
                        "rollback_attempted": False,
                        "rollback_confirmed": True,
                        "rollback_errors": [],
                        "partial_promotion_possible": False,
                    }
                if not promotion_succeeded:
                    execution_results[current_plan_number] = False
                    retain_test_folder = True
                    details = dict(
                        execution_details_by_plan.get(
                            current_plan_number,
                            {},
                        )
                    )
                    details.update(
                        {
                            "failure_stage": promotion_evidence[
                                "failure_stage"
                            ],
                            "failure_detail": promotion_evidence[
                                "failure_detail"
                            ],
                            "retained_test_folder": retained_test_folder,
                            "promotion_failure": promotion_evidence,
                        }
                    )
                    execution_details_by_plan[
                        current_plan_number
                    ] = details
                    if not promotion_evidence.get(
                        "rollback_confirmed",
                        False,
                    ):
                        promotion_integrity_lost = True
                        promotion_integrity_failure = promotion_evidence
                    logger.error(
                        "Failed to promote plan %s artifacts: %s",
                        current_plan_number,
                        promotion_evidence["failure_detail"],
                    )
                    continue
                artifact_files_copied += len(
                    promotion_evidence["copied_destination_paths"]
                )
                if geometry_source is not None:
                    promoted_geometry_numbers.add(geometry_number)

            if promotion_lock_lease is not None:
                if not RasCmdr._release_destination_promotion_lock(
                    promotion_lock_lease
                ):
                    logger.warning(
                        "Did not remove destination promotion lock because "
                        "ownership could not be reverified: %s",
                        promotion_lock_evidence.get("lock_path"),
                    )
                promotion_lock_lease = None

            logger.info(
                "Consolidated %s plan artifact file(s) to the original project",
                artifact_files_copied,
            )

            # A refused promotion retains the only freshly computed copy for
            # explicit user recovery/review.
            if not retain_test_folder:
                try:
                    shutil.rmtree(compute_folder)
                    logger.info("Removed test folder: %s", compute_folder.name)
                    logger.debug(f"Removed test folder path: {compute_folder}")
                except Exception as e:
                    logger.warning(f"Failed to remove test folder {compute_folder}: {str(e)}")
            else:
                logger.warning(
                    "Retained computed test folder after promotion refusal "
                    "or failure: %s",
                    compute_folder,
                )

            logger.info("compute_test_mode completed.")

            RasCmdr._log_execution_results(execution_results)

            # Refresh DataFrames from original folder - HDF files are now there
            ras_obj.plan_df = ras_obj.get_plan_entries()
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            if execution_result_format == "hdf":
                ras_obj.update_results_df(
                    plan_numbers=list(execution_results.keys())
                )

            # Extract results_df rows for executed plans
            _results_df = pd.DataFrame()
            try:
                plan_nums = list(execution_results.keys())
                if hasattr(ras_obj, 'results_df') and ras_obj.results_df is not None and len(ras_obj.results_df) > 0:
                    mask = ras_obj.results_df['plan_number'].isin(plan_nums)
                    if mask.any():
                        _results_df = ras_obj.results_df[mask].copy()
            except Exception as e:
                logger.debug(f"Could not extract results_df for test mode plans: {e}")

            for current_plan_number in execution_results:
                execution_details_by_plan.setdefault(current_plan_number, {})
            return ComputeParallelResult(
                execution_results=execution_results,
                results_df=_results_df,
                execution_details_by_plan=execution_details_by_plan,
            )

        except Exception as e:
            logger.critical(f"Error in compute_test_mode: {str(e)}")
            return ComputeParallelResult()
        finally:
            if promotion_lock_lease is not None:
                if not RasCmdr._release_destination_promotion_lock(
                    promotion_lock_lease
                ):
                    logger.warning(
                        "Preserved destination promotion lock after ownership "
                        "verification failed: %s",
                        promotion_lock_lease.get("path"),
                    )

    @staticmethod
    @log_call
    def compute_plan_linux(
        plan_number: Union[str, Number],
        ras_exe_dir: Union[str, Path],
        ras_object=None,
        timeout_sec: int = 14400,
        dos2unix: bool = True,
        num_cores: int = None,
        retry: bool = True,
        retry_delay_sec: int = 30,
    ) -> 'ComputeResult':
        """
        Execute a HEC-RAS plan using the native Linux RasUnsteady binary.

        Attribution: Execution pattern derived from ras-agent
        (https://github.com/gheistand/ras-agent) by Glenn Heistand / CHAMP —
        Illinois State Water Survey. See runner.py:run_job() for the original
        Linux RasUnsteady invocation pattern (subprocess, LD_LIBRARY_PATH,
        .tmp.hdf preparation, retry logic).

        This is Phase 2 of a two-phase Linux execution workflow:

        **Phase 1 (Windows)**: Preprocess the plan on Windows to generate
        .tmp.hdf, .b##, and .x## files. Use ``RasPreprocess.preprocess_plan()``
        to automate this step, or manually run HEC-RAS on Windows and kill
        after "Starting Unsteady Flow Computations" appears in the .bco log.

        **Phase 2 (Linux — this method)**: Execute the preprocessed plan
        using the native RasUnsteady binary.

        Prerequisites (must exist in project folder before calling):
            - {project}.p{plan_num}.tmp.hdf — preprocessed plan HDF
            - {project}.b{plan_num} — boundary conditions file
            - {project}.x{geom_num} — cross-section preprocessor file
            - {project}.c{geom_num} — computed-geometry file (5.0.7 layout only)

        Supported native Linux install layouts (auto-detected from ``ras_exe_dir``):

        * **canonical (6.3.1-7.0)** — ``RasUnsteady`` at the install root with a
          sibling ``libs/`` tree (``libs/``, ``libs/mkl/``, ``libs/rhel_8/``).
          Invoked as ``RasUnsteady {proj}.p{plan}.tmp.hdf x{geom}``.
        * **bin_ras (5.0.7)** — ``bin_ras/rasUnsteady64`` with libraries colocated
          in ``bin_ras/`` (no ``libs/`` tree). Invoked as
          ``rasUnsteady64 {proj}.c{geom} b{plan}`` and additionally requires the
          ``.c{geom}`` computed-geometry file. (CLB-886)

        Detection and binary resolution mirror
        :meth:`RasUtils._scan_native_linux_ras` (root ``RasUnsteady`` →
        ``bin_ras/{rasUnsteady64,RasUnsteady,rasUnsteady}``).

        The Linux RasUnsteady binary uses Fortran I/O conventions that require
        files to be accessible with a base name of "io" (e.g., io.b, io.X).
        This method creates temporary symlinks to satisfy this requirement.

        On a Windows host, the WSL adapter fails before solver launch unless
        Bash, ``setsid --wait``, ``/proc`` identity, durable sync, and process-
        group signalling are available. It atomically acquires a per-plan
        lease, launches the solver as a session/process-group leader, and
        publishes the lease token, its Linux PID, ``/proc`` start time, and
        process-group ID before ``exec``. Timeout or Python interruption starts
        a separate WSL recovery command that revalidates that exact identity
        before TERM/KILL and then proves the group empty. Opposing result
        families are deliberately not precleaned or finalized until
        quiescence is positive.
        Uncertain recovery preserves all outputs and the lease so a duplicate
        execution fails closed.

        Args:
            plan_number (Union[str, Number]): Plan number to execute (e.g., "01").
            ras_exe_dir (Union[str, Path]): HEC-RAS Linux install directory. For the
                canonical layout this holds ``RasUnsteady`` + ``libs/``; for the
                5.0.7 layout it holds ``bin_ras/rasUnsteady64`` + its libraries.
            ras_object: Optional RAS project object. If None, uses global ras.
            timeout_sec (int): Maximum execution time in seconds (default 14400 = 4 hours).
            dos2unix (bool): Convert CRLF→LF in text files before execution (default True).
            num_cores (int, optional): Number of cores. If specified, updates plan file.
            retry (bool): Retry once on failure after retry_delay_sec (default True).
            retry_delay_sec (int): Seconds to wait before retry (default 30).

        Returns:
            ComputeResult: Result object with success bool and results_df_row.

        Raises:
            FileNotFoundError: If RasUnsteady binary, .tmp.hdf, .b, or .x files not found.

        Example:
            >>> # Phase 1: Preprocess on Windows (generates .tmp.hdf, .b, .x)
            >>> # Phase 2: Execute on Linux
            >>> from ras_commander import init_ras_project, RasCmdr
            >>> init_ras_project("/home/user/model")
            >>> result = RasCmdr.compute_plan_linux(
            ...     "01", ras_exe_dir="/opt/hecras/6.7-beta5"
            ... )
        """
        ras_obj = ras_object if ras_object is not None else ras
        ras_obj.check_initialized()

        plan_num_str = RasUtils.normalize_ras_number(plan_number)

        ras_exe_dir_raw = str(ras_exe_dir)
        ras_exe_dir_posix = ras_exe_dir_raw.replace("\\", "/").rstrip("/")
        run_via_wsl = os.name == "nt" and ras_exe_dir_posix.startswith("/mnt/")

        if run_via_wsl:
            ras_exe = f"{ras_exe_dir_posix}/RasUnsteady"
            # WSL supports the canonical 6.x/7.x layout. Keep the same adapter
            # shape used by native Linux so prerequisite checks below do not
            # depend on which host launches RasUnsteady.
            layout = {
                "ras_exe": ras_exe,
                "needs_c_file": False,
                "lib_dirs": [],
                "label": "canonical (WSL)",
            }
            probe = subprocess.run(
                ["wsl", "test", "-x", ras_exe],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if probe.returncode != 0:
                raise FileNotFoundError(
                    f"RasUnsteady binary not found or not executable in WSL at {ras_exe}. "
                    "Ensure HEC-RAS Linux binaries are installed and WSL can access them."
                )
        else:
            ras_exe_dir = Path(ras_exe_dir)
            layout = RasCmdr._resolve_linux_layout(ras_exe_dir)
            ras_exe = layout["ras_exe"]
            if not ras_exe.exists():
                raise FileNotFoundError(
                    f"Linux RasUnsteady binary not found under {ras_exe_dir} "
                    f"(looked for {ras_exe}). Ensure HEC-RAS Linux binaries are installed."
                )

        project_dir = Path(ras_obj.project_folder)
        project_name = ras_obj.project_name

        # Determine geometry number from plan file
        plan_path = RasPlan.get_plan_path(plan_num_str, ras_obj)
        # Resolve the geometry number from the plan file. Fail fast rather than
        # silently defaulting to "01" — running an unknown/wrong geometry would
        # produce results for the wrong model (CLB-884).
        geom_num = None
        try:
            plan_text = Path(plan_path).read_text(errors='replace')
            for line in plan_text.splitlines():
                if line.startswith("Geom File="):
                    geom_ref = line.split("=", 1)[1].strip()
                    # Extract number: "g04" → "04"
                    import re
                    m = re.search(r'(\d+)', geom_ref)
                    if m:
                        geom_num = m.group(1)
                    break
        except Exception as e:
            raise RuntimeError(
                f"Could not read the geometry reference from plan file {plan_path}: {e}. "
                f"Refusing to run Linux compute without a resolved geometry."
            )
        if geom_num is None:
            raise RuntimeError(
                f"Could not resolve a geometry number from plan file {plan_path} "
                f"(no parseable 'Geom File=' entry). Refusing to fall back to a default "
                f"geometry for Linux compute — that could silently run the wrong geometry."
            )

        # Verify prerequisite files exist
        tmp_hdf = project_dir / f"{project_name}.p{plan_num_str}.tmp.hdf"
        b_file = project_dir / f"{project_name}.b{plan_num_str}"
        x_file = project_dir / f"{project_name}.x{geom_num}"
        # 5.0.7 (bin_ras/rasUnsteady64) additionally consumes the computed-geometry
        # ".c{geom}" binary file and is invoked as `rasUnsteady64 {proj}.c{geom} b{plan}`
        # rather than the 6.x/7.0 `RasUnsteady {tmp.hdf} x{geom}` convention (CLB-886).
        c_file = project_dir / f"{project_name}.c{geom_num}"

        missing = []
        if not tmp_hdf.exists():
            missing.append(f".p{plan_num_str}.tmp.hdf")
        if not b_file.exists():
            missing.append(f".b{plan_num_str}")
        if not x_file.exists():
            missing.append(f".x{geom_num}")
        if layout["needs_c_file"] and not c_file.exists():
            missing.append(f".c{geom_num}")

        if missing:
            raise FileNotFoundError(
                f"Missing prerequisite files for Linux execution ({layout['label']} layout): "
                f"{', '.join(missing)}. "
                f"Run RasPreprocess.preprocess_plan() on Windows first (Phase 1). "
                f"See examples/510_linux_execution.ipynb for the complete workflow."
            )

        # Set num_cores if specified
        if num_cores is not None:
            try:
                RasPlan.set_num_cores(plan_path, num_cores=num_cores, ras_object=ras_obj)
                logger.info(f"Set number of cores to {num_cores} for plan: {plan_num_str}")
            except Exception as e:
                logger.error(f"Error setting number of cores: {e}")

        if run_via_wsl:
            return RasCmdr._compute_plan_linux_via_wsl(
                ras_exe=str(ras_exe),
                ras_exe_dir=ras_exe_dir_posix,
                plan_number=plan_num_str,
                geom_num=geom_num,
                project_dir=project_dir,
                project_name=project_name,
                tmp_hdf=tmp_hdf,
                timeout_sec=timeout_sec,
                dos2unix=dos2unix,
                retry=retry,
                retry_delay_sec=retry_delay_sec,
                ras_obj=ras_obj,
            )

        # Build LD_LIBRARY_PATH — auto-detect library locations per layout:
        #   5.0.7:     libs live alongside the binary in bin_ras/
        #   6.3.1-6.5: libs/, libs/mkl/
        #   6.6-6.7:   libs/, libs/mkl/, libs/rhel_8/
        ld_path = RasCmdr._build_linux_ld_path(ras_exe_dir, layout)
        logger.info("Configured Linux library path for RasUnsteady")
        logger.debug(f"LD_LIBRARY_PATH: {ld_path}")

        # dos2unix text files
        if dos2unix:
            try:
                count = RasUtils.dos2unix(project_dir)
                logger.debug(f"dos2unix converted {count} files")
            except Exception as e:
                logger.warning(f"dos2unix failed: {e}")

        # Create Fortran io.* symlinks
        # RasUnsteady uses Fortran I/O that expects files named io.b, io.X, io.g, etc.
        io_links = []

        def _create_io_link(source: Path, io_name: str):
            """Create io.* symlink and track for cleanup."""
            link_path = project_dir / io_name
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(source.name)
            io_links.append(link_path)

        try:
            _create_io_link(b_file, "io.b")
            _create_io_link(x_file, "io.X")
            _create_io_link(x_file, "io.x")
            # Symlink all project files to io.* equivalents
            for f in project_dir.iterdir():
                if f.name.startswith(project_name + ".") and not f.name.startswith("io."):
                    suffix = f.name[len(project_name) + 1:]  # everything after "ProjectName."
                    io_name = f"io.{suffix}"
                    io_path = project_dir / io_name
                    if not io_path.exists() and not io_path.is_symlink():
                        _create_io_link(f, io_name)
            logger.debug(f"Created {len(io_links)} io.* symlinks")
        except OSError as e:
            logger.warning(f"Could not create io.* symlinks (may not be needed): {e}")

        max_attempts = 2 if retry else 1
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Linux execution attempt {attempt}/{max_attempts} for plan {plan_num_str}")

            # Remove any leftover io.tmp.hdf from previous run
            io_tmp_hdf = project_dir / "io.tmp.hdf"
            if io_tmp_hdf.exists():
                io_tmp_hdf.unlink()

            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = ld_path

            log_path = project_dir / f"compute_linux_{plan_num_str}.log"
            success = False
            err_msg = ""
            attempt_launched = False
            proc = None

            try:
                start_time = time.time()
                # Argument convention differs by layout (CLB-886):
                #   5.0.7:    rasUnsteady64 {proj}.c{geom} b{plan}   (cwd-relative basenames)
                #   6.x/7.0:  RasUnsteady   {proj}.p{plan}.tmp.hdf x{geom}
                if layout["needs_c_file"]:
                    ras_args = [c_file.name, f"b{plan_num_str}"]
                else:
                    ras_args = [str(tmp_hdf), f"x{geom_num}"]
                with open(log_path, "w") as log_fh:
                    # Reassert modern result ownership immediately before
                    # every solver attempt, after log creation succeeds.
                    prepare_plan_execution_artifacts(
                        plan_num_str,
                        output_format="hdf",
                        ras_object=ras_obj,
                    )
                    proc = subprocess.Popen(
                        [str(ras_exe), *ras_args],
                        stdout=log_fh,
                        stderr=subprocess.STDOUT,
                        env=env,
                        cwd=str(project_dir),
                    )
                    attempt_launched = True
                try:
                    rc = proc.wait(timeout=timeout_sec)
                    end_time = time.time()
                    run_time = end_time - start_time
                    if rc == 0:
                        # RasUnsteady can exit 0 even when the solve failed in-band
                        # (e.g. "Unsteady flow encountered an error"). Validate the
                        # solver log and result HDF before declaring success so a bad
                        # result HDF is never promoted .tmp.hdf -> .hdf (CLB-882).
                        ok, reason = RasCmdr._validate_linux_solve(
                            log_path, tmp_hdf, plan_num_str
                        )
                        if ok:
                            success = True
                            logger.info(
                                f"RasUnsteady completed for plan {plan_num_str} "
                                f"in {run_time:.1f}s (exit code 0, validated)"
                            )
                        else:
                            success = False
                            err_msg = (
                                f"RasUnsteady exited 0 but the solve did not produce a "
                                f"valid result: {reason}"
                            )
                            logger.error(f"Plan {plan_num_str}: {err_msg}")
                    else:
                        try:
                            tail = log_path.read_text(errors='replace')[-500:]
                        except OSError:
                            tail = "(log unreadable)"
                        err_msg = f"RasUnsteady exited with code {rc}. Log tail: {tail}"
                        logger.error(f"Plan {plan_num_str}: {err_msg}")
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    err_msg = f"Timeout after {timeout_sec}s"
                    logger.error(f"Plan {plan_num_str}: {err_msg}")
            except FileNotFoundError:
                raise RuntimeError(
                    f"RasUnsteady binary not found at {ras_exe}."
                )
            finally:
                if attempt_launched:
                    if proc is not None and proc.poll() is None:
                        proc.kill()
                        proc.wait()
                    finalize_plan_execution_artifacts(
                        plan_num_str,
                        output_format="hdf",
                        ras_object=ras_obj,
                    )

            if success:
                # Move results from .tmp.hdf → .hdf
                if tmp_hdf.exists():
                    plan_hdf = RasCmdr._get_hdf_path(plan_num_str, ras_obj)
                    shutil.move(str(tmp_hdf), str(plan_hdf))
                    logger.debug(f"Renamed {tmp_hdf.name} → {plan_hdf.name}")

                # Clean up io.* symlinks
                for link in io_links:
                    try:
                        if link.is_symlink():
                            link.unlink()
                    except OSError:
                        pass

                # Refresh DataFrames
                try:
                    ras_obj.plan_df = ras_obj.get_plan_entries()
                    ras_obj.update_results_df(plan_numbers=[plan_num_str])
                    mask = ras_obj.results_df['plan_number'] == plan_num_str
                    results_row = ras_obj.results_df[mask].iloc[0].copy() if mask.any() else None
                except Exception as e:
                    logger.debug(f"Could not extract results_df_row: {e}")
                    results_row = None

                return ComputeResult(success=True, results_df_row=results_row)
            else:
                if attempt < max_attempts:
                    logger.info(f"Retrying in {retry_delay_sec}s...")
                    time.sleep(retry_delay_sec)
                    continue

                # Clean up io.* symlinks on final failure
                for link in io_links:
                    try:
                        if link.is_symlink():
                            link.unlink()
                    except OSError:
                        pass

                return ComputeResult(success=False, results_df_row=None)

    @staticmethod
    def _resolve_linux_layout(ras_exe_dir: Path) -> dict:
        """Detect the HEC-RAS Linux install layout and return its execution adapter (CLB-886).

        Two native layouts are supported:

        * **canonical (6.3.1-7.0)** — ``RasUnsteady`` at the install root, with a
          sibling ``libs/`` (plus ``libs/mkl/``, ``libs/rhel_8/``). Invoked as
          ``RasUnsteady {proj}.p{plan}.tmp.hdf x{geom}``.
        * **bin_ras (5.0.7)** — ``bin_ras/rasUnsteady64`` with the shared libraries
          alongside the binary in ``bin_ras/`` (no ``libs/`` tree). Invoked as
          ``rasUnsteady64 {proj}.c{geom} b{plan}`` and additionally requires the
          computed-geometry ``.c{geom}`` file.

        Resolution prefers a root ``RasUnsteady`` (canonical) and otherwise falls
        back to ``bin_ras/rasUnsteady64`` / ``bin_ras/RasUnsteady`` — mirroring the
        binary names :meth:`RasUtils._scan_native_linux_ras` recognizes.

        Returns:
            dict: ``ras_exe`` (Path), ``needs_c_file`` (bool), ``lib_dirs``
            (list[Path] explicit lib dirs, or ``[]`` to auto-detect ``libs/``),
            and ``label`` (str).
        """
        ras_exe_dir = Path(ras_exe_dir)
        # Canonical layout: RasUnsteady at the install root.
        root_exe = ras_exe_dir / "RasUnsteady"
        if root_exe.exists():
            return {
                "ras_exe": root_exe,
                "needs_c_file": False,
                "lib_dirs": [],          # auto-detect libs/ tree
                "label": "canonical",
            }
        # bin_ras layout (5.0.7): rasUnsteady64 (or RasUnsteady) under bin_ras/,
        # libraries colocated in the same bin_ras/ directory.
        bin_ras = ras_exe_dir / "bin_ras"
        for binname in ("rasUnsteady64", "RasUnsteady", "rasUnsteady"):
            cand = bin_ras / binname
            if cand.exists():
                return {
                    "ras_exe": cand,
                    "needs_c_file": True,
                    "lib_dirs": [bin_ras],
                    "label": "bin_ras (5.0.7)",
                }
        # Nothing matched — return the canonical guess so the caller raises a
        # clear FileNotFoundError pointing at the expected location.
        return {
            "ras_exe": root_exe,
            "needs_c_file": False,
            "lib_dirs": [],
            "label": "canonical",
        }

    @staticmethod
    def _build_linux_ld_path(ras_exe_dir: Path, layout: dict) -> str:
        """Build LD_LIBRARY_PATH for a Linux RasUnsteady run, per layout (CLB-886)."""
        ras_exe_dir = Path(ras_exe_dir)
        ld_path_parts = []
        # Explicit lib dirs (e.g. 5.0.7 bin_ras/) take precedence.
        for d in layout.get("lib_dirs") or []:
            if Path(d).exists():
                ld_path_parts.append(str(d))
        if ld_path_parts:
            return ":".join(ld_path_parts)
        # Canonical: auto-detect a libs/ tree next to the binary.
        lib_base = ras_exe_dir / "libs"
        if not lib_base.exists():
            lib_base = ras_exe_dir.parent / "libs"
        if lib_base.exists():
            ld_path_parts.append(str(lib_base))
            for subdir in sorted(lib_base.iterdir()):
                if subdir.is_dir():
                    ld_path_parts.append(str(subdir))
                    logger.debug(f"Added library path: {subdir}")
        else:
            logger.warning(f"No libs/ directory found near {ras_exe_dir}")
            ld_path_parts.append(str(ras_exe_dir))
        return ":".join(ld_path_parts)

    @staticmethod
    def _validate_linux_solve(log_path, result_hdf, plan_num_str: str):
        """Validate a Linux RasUnsteady solve beyond exit-code 0 (CLB-882).

        RasUnsteady can exit 0 even when the unsteady solve failed in-band
        (convergence failure, "encountered an error", etc.), leaving an
        unpopulated result HDF. This scans the solver log for error markers and
        confirms the result HDF actually contains an Unsteady results group
        (not just the skeleton groups carried over from Phase-1 preprocessing).

        Returns:
            tuple[bool, str]: ``(ok, reason)`` — ``ok`` is False with a
            human-readable reason when the solve did not produce a valid result.
        """
        error_markers = [
            "encountered an error",
            "did not complete",
            "failed to converge",
            "computations were stopped",
            "fatal error",
        ]
        try:
            log_text = Path(log_path).read_text(errors="replace")
        except OSError:
            return False, "solver log unreadable"
        low = log_text.lower()
        for marker in error_markers:
            if marker in low:
                return False, f"solver log reports failure ('{marker}')"
        try:
            import h5py
            with h5py.File(str(result_hdf), "r") as hf:
                results = hf.get("Results")
                if results is None:
                    return False, "result HDF missing /Results group"
                if results.get("Unsteady") is None:
                    return False, "result HDF missing /Results/Unsteady group"
        except Exception as e:
            return False, f"result HDF unreadable or invalid: {e}"
        return True, "ok"

    @staticmethod
    @log_call
    def preprocess_geometry_linux(
        plan_number: Union[str, Number],
        ras_exe_dir: Union[str, Path],
        ras_object=None,
        timeout_sec: int = 7200,
        dos2unix: bool = True,
    ) -> 'ComputeResult':
        """Run the native Linux ``RasGeomPreprocess`` geometry preprocessor (CLB-885).

        This regenerates the geometry preprocessor tables (1D cross-section
        property tables and 2D cell/face HTab property tables) inside an
        existing ``{project}.p{plan}.tmp.hdf``, headlessly on Linux — mirroring
        :meth:`compute_plan_linux` (LD_LIBRARY_PATH auto-detect, dos2unix,
        output validation).

        **Scope / honest limitation:** the native ``RasGeomPreprocess`` binary
        operates *in place* on an existing ``.tmp.hdf`` that already contains the
        raw ``/Geometry`` group. It does **not** build the ``.tmp.hdf`` skeleton
        (nor the ``.b##``/``.x##`` files) from raw ``.prj``/``.g##``/``.u##``
        text — that initial assembly is still the Windows Phase-1 step. Use this
        to (re)compute geometry HTab tables on Linux after a geometry-only change,
        or to refresh ``/Geometry/GeomPreprocess`` before
        :meth:`compute_plan_linux` without round-tripping to Windows.

        Args:
            plan_number: Plan number whose ``.tmp.hdf`` to preprocess (e.g. "04").
            ras_exe_dir: Directory containing the ``RasGeomPreprocess`` binary and
                sibling ``libs/`` directory (e.g. ``/opt/hecras/6.6``).
            ras_object: Optional RAS project object. If None, uses global ``ras``.
            timeout_sec: Maximum preprocessing time in seconds (default 7200).
            dos2unix: Convert CRLF->LF in text files first (default True).

        Returns:
            ComputeResult: ``success`` True when the preprocessor finished and the
            ``.tmp.hdf`` contains a populated ``/Geometry/GeomPreprocess`` group.

        Raises:
            FileNotFoundError: If the ``RasGeomPreprocess`` binary or the
                ``.tmp.hdf``/``.x##`` prerequisites are missing.
        """
        ras_obj = ras_object if ras_object is not None else ras
        ras_obj.check_initialized()

        plan_num_str = RasUtils.normalize_ras_number(plan_number)

        ras_exe_dir = Path(str(ras_exe_dir).replace("\\", "/").rstrip("/"))
        geom_exe = ras_exe_dir / "RasGeomPreprocess"
        if not geom_exe.exists():
            raise FileNotFoundError(
                f"RasGeomPreprocess binary not found at {geom_exe}. "
                "Native Linux geometry preprocessing requires HEC-RAS 6.x Linux "
                "binaries (RasGeomPreprocess is bundled alongside RasUnsteady)."
            )

        project_dir = Path(ras_obj.project_folder)
        project_name = ras_obj.project_name

        # Resolve geometry number from the plan file (mirror compute_plan_linux).
        geom_num = "01"
        try:
            plan_path = RasPlan.get_plan_path(plan_num_str, ras_obj)
            if plan_path is None:
                raise ValueError(
                    f"Could not resolve plan path for plan {plan_num_str}; "
                    "ensure the project is initialized and the plan exists."
                )
            plan_text = Path(plan_path).read_text(errors="replace")
            for line in plan_text.splitlines():
                if line.startswith("Geom File="):
                    import re as _re
                    m = _re.search(r"(\d+)", line.split("=", 1)[1])
                    if m:
                        geom_num = m.group(1)
                    break
        except Exception as e:
            logger.warning(f"Could not read geom number from plan file: {e}")

        tmp_hdf = project_dir / f"{project_name}.p{plan_num_str}.tmp.hdf"
        x_file = project_dir / f"{project_name}.x{geom_num}"
        missing = []
        if not tmp_hdf.exists():
            missing.append(f".p{plan_num_str}.tmp.hdf")
        if not x_file.exists():
            missing.append(f".x{geom_num}")
        if missing:
            raise FileNotFoundError(
                f"Missing prerequisites for Linux geometry preprocessing: "
                f"{', '.join(missing)}. The .tmp.hdf (with raw /Geometry) and .x## "
                f"must already exist (Windows Phase-1 builds these). "
                f"See examples/510_linux_execution.ipynb."
            )

        # Build LD_LIBRARY_PATH — auto-detect library subdirectories (mirror compute_plan_linux).
        lib_base = ras_exe_dir / "libs"
        if not lib_base.exists():
            lib_base = ras_exe_dir.parent / "libs"
        ld_path_parts = []
        if lib_base.exists():
            ld_path_parts.append(str(lib_base))
            for subdir in sorted(lib_base.iterdir()):
                if subdir.is_dir():
                    ld_path_parts.append(str(subdir))
        else:
            logger.warning(f"No libs/ directory found near {ras_exe_dir}")
            ld_path_parts.append(str(ras_exe_dir))
        ld_path = ":".join(ld_path_parts)
        logger.info(f"LD_LIBRARY_PATH: {ld_path}")

        if dos2unix:
            try:
                RasUtils.dos2unix(project_dir)
            except Exception as e:
                logger.warning(f"dos2unix failed: {e}")

        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = ld_path

        log_path = project_dir / f"geompre_linux_{plan_num_str}.log"
        try:
            start_time = time.time()
            with open(log_path, "w") as log_fh:
                proc = subprocess.Popen(
                    [str(geom_exe), str(tmp_hdf), f"x{geom_num}"],
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=str(project_dir),
                )
            try:
                rc = proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                logger.error(f"Plan {plan_num_str}: geometry preprocessing timed out after {timeout_sec}s")
                return ComputeResult(success=False, results_df_row=None)
            run_time = time.time() - start_time
        except FileNotFoundError:
            raise RuntimeError(f"RasGeomPreprocess binary not found at {geom_exe}.")

        if rc != 0:
            try:
                tail = log_path.read_text(errors="replace")[-500:]
            except OSError:
                tail = "(log unreadable)"
            logger.error(
                f"Plan {plan_num_str}: RasGeomPreprocess exited with code {rc}. Log tail: {tail}"
            )
            return ComputeResult(success=False, results_df_row=None)

        ok, reason = RasCmdr._validate_geom_preprocess(log_path, tmp_hdf)
        if ok:
            logger.info(
                f"RasGeomPreprocess completed for plan {plan_num_str} "
                f"in {run_time:.1f}s (exit code 0, validated)"
            )
            return ComputeResult(success=True, results_df_row=None)
        logger.error(
            f"Plan {plan_num_str}: RasGeomPreprocess exited 0 but did not produce "
            f"a valid geometry preprocess result: {reason}"
        )
        return ComputeResult(success=False, results_df_row=None)

    @staticmethod
    def _validate_geom_preprocess(log_path, tmp_hdf):
        """Validate a Linux RasGeomPreprocess run beyond exit-code 0 (CLB-885).

        RasGeomPreprocess can exit 0 even when it failed in-band. This scans the
        log for error markers and confirms the .tmp.hdf gained a populated
        ``/Geometry/GeomPreprocess`` group (the 1D/2D hydraulic property tables
        the unsteady solver consumes).

        Returns:
            tuple[bool, str]: ``(ok, reason)``.
        """
        error_markers = [
            "encountered an error",
            "fatal error",
            "must be closed if it is being used",
            "hdf_error",
        ]
        try:
            log_low = Path(log_path).read_text(errors="replace").lower()
        except OSError:
            return False, "geompre log unreadable"
        for marker in error_markers:
            if marker in log_low:
                return False, f"geompre log reports failure ('{marker}')"
        # The "Finished Processing Geometry" banner is the success signal.
        if "finished processing geometry" not in log_low:
            return False, "geompre log missing 'Finished Processing Geometry' banner"
        try:
            import h5py
            with h5py.File(str(tmp_hdf), "r") as hf:
                geom = hf.get("Geometry")
                if geom is None:
                    return False, "tmp.hdf missing /Geometry group"
                gp = geom.get("GeomPreprocess")
                if gp is None or len(list(gp.keys())) == 0:
                    return False, "tmp.hdf missing/empty /Geometry/GeomPreprocess group"
        except Exception as e:
            return False, f"tmp.hdf unreadable or invalid: {e}"
        return True, "ok"

    @staticmethod
    def _windows_path_to_wsl(path: Union[str, Path]) -> str:
        """Translate a Windows path to its WSL path using the active distro."""
        path_arg = str(path).replace("\\", "/")
        proc = subprocess.run(
            ["wsl", "wslpath", "-a", path_arg],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"wslpath failed for {path}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout.strip()

    @staticmethod
    def _parse_wsl_solver_exit_proof(stdout: str) -> Dict[str, Any]:
        """Parse the shell's exact Linux solver process-group exit receipt."""
        marker = "__RAS_COMMANDER_WSL_EXIT_PROOF__"
        proof_line = None
        for line in str(stdout).splitlines():
            if line.startswith(f"{marker} "):
                proof_line = line
        if proof_line is None:
            return {
                "quiescence_confirmed": None,
                "solver_pid": None,
                "start_time_ticks": None,
                "process_group_id": None,
                "reported_returncode": None,
            }

        try:
            fields = dict(
                token.split("=", 1)
                for token in proof_line[len(marker) + 1 :].split()
            )
            solver_pid = int(fields["pid"])
            start_time_ticks = int(fields["start"])
            process_group_id = int(fields["pgid"])
            reported_returncode = int(fields["rc"])
            quiescent_value = fields["quiescent"]
            if (
                solver_pid <= 0
                or start_time_ticks <= 0
                or process_group_id != solver_pid
            ):
                raise ValueError("invalid solver process-group identity")
            if not 0 <= reported_returncode <= 255:
                raise ValueError("invalid shell return code")
            if quiescent_value not in {"0", "1"}:
                raise ValueError("invalid quiescence value")
        except (KeyError, TypeError, ValueError):
            return {
                "quiescence_confirmed": None,
                "solver_pid": None,
                "start_time_ticks": None,
                "process_group_id": None,
                "reported_returncode": None,
            }
        return {
            "quiescence_confirmed": quiescent_value == "1",
            "solver_pid": solver_pid,
            "start_time_ticks": start_time_ticks,
            "process_group_id": process_group_id,
            "reported_returncode": reported_returncode,
        }

    @staticmethod
    def _read_wsl_supervision_identity(
        state_path: Union[str, Path],
        *,
        expected_owner_token: Optional[str] = None,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Read one atomically published Linux ``/proc`` identity receipt."""
        path = Path(state_path)
        try:
            before = path.stat()
            text = path.read_text(encoding="ascii")
            after = path.stat()
        except OSError as exc:
            return None, f"{type(exc).__name__}: {exc}"
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            return None, "supervision identity changed while reading"
        try:
            (
                schema,
                token_field,
                pid_field,
                start_field,
                pgid_field,
            ) = text.strip().split()
            if schema != "ras_commander_wsl_identity_v2":
                raise ValueError("unsupported supervision identity schema")
            if not token_field.startswith("token="):
                raise ValueError("missing owner token field")
            owner_token = token_field.removeprefix("token=")
            if uuid.UUID(owner_token).hex != owner_token:
                raise ValueError("invalid owner token")
            if (
                expected_owner_token is not None
                and owner_token != expected_owner_token
            ):
                raise ValueError("supervision identity owner token mismatch")
            solver_pid = int(pid_field.removeprefix("pid="))
            start_time_ticks = int(start_field.removeprefix("start="))
            process_group_id = int(pgid_field.removeprefix("pgid="))
            if not pid_field.startswith("pid="):
                raise ValueError("missing pid field")
            if not start_field.startswith("start="):
                raise ValueError("missing start field")
            if not pgid_field.startswith("pgid="):
                raise ValueError("missing pgid field")
            if (
                solver_pid <= 0
                or start_time_ticks <= 0
                or process_group_id != solver_pid
            ):
                raise ValueError("invalid exact Linux process identity")
        except (TypeError, ValueError) as exc:
            return None, str(exc)
        return {
            "owner_token": owner_token,
            "solver_pid": solver_pid,
            "start_time_ticks": start_time_ticks,
            "process_group_id": process_group_id,
        }, None

    @staticmethod
    def _wsl_supervision_preflight() -> tuple[bool, Dict[str, Any]]:
        """Prove WSL exposes every primitive required for exact supervision."""
        script = (
            "command -v bash >/dev/null 2>&1 && "
            "command -v setsid >/dev/null 2>&1 && "
            "setsid --help 2>&1 | grep -q -- '--wait' && "
            "command -v cat >/dev/null 2>&1 && "
            "command -v sync >/dev/null 2>&1 && "
            "type kill >/dev/null 2>&1 && "
            "[ -r /proc/self/stat ]"
        )
        try:
            result = subprocess.run(
                ["wsl", "bash", "-lc", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
        except Exception as exc:
            return False, {
                "complete": False,
                "available": False,
                "returncode": None,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        available = result.returncode == 0
        detail = (result.stderr or result.stdout or "").strip()
        return available, {
            "complete": True,
            "available": available,
            "returncode": result.returncode,
            "detail": detail[:1000] or None,
        }

    @staticmethod
    def _recover_wsl_solver_identity(
        identity: Dict[str, int],
    ) -> Dict[str, Any]:
        """Revalidate and quiesce only one exact Linux solver process group."""
        solver_pid = int(identity["solver_pid"])
        start_time_ticks = int(identity["start_time_ticks"])
        process_group_id = int(identity["process_group_id"])
        script = fr"""
set +e
expected_pid={solver_pid}
expected_start={start_time_ticks}
expected_pgid={process_group_id}
term_sent=0
kill_sent=0
read_exact_identity() {{
    [ -r "/proc/$expected_pid/stat" ] || return 1
    stat_text=$(cat "/proc/$expected_pid/stat") || return 2
    stat_tail="${{stat_text##*) }}"
    set -- $stat_tail
    actual_pgid=$3
    actual_start=${{20}}
    case "$actual_pgid:$actual_start" in
        *[!0-9:]*) return 2 ;;
    esac
    [ "$actual_pgid" = "$expected_pgid" ] && [ "$actual_start" = "$expected_start" ] || return 3
    return 0
}}
group_exists() {{
    kill -0 -- "-$expected_pgid" 2>/dev/null
}}
read_exact_identity
identity_rc=$?
if [ "$identity_rc" -eq 0 ]; then
    if kill -TERM -- "-$expected_pgid" 2>/dev/null; then
        term_sent=1
    elif group_exists; then
        status=uncertain
    else
        status=quiescent
    fi
    if [ -z "$status" ]; then
        for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
            group_exists || {{ status=quiescent; break; }}
            sleep 0.1
        done
    fi
    if [ -z "$status" ]; then
        if kill -KILL -- "-$expected_pgid" 2>/dev/null; then
            kill_sent=1
        elif group_exists; then
            status=uncertain
        else
            status=quiescent
        fi
    fi
    if [ -z "$status" ]; then
        for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
            group_exists || {{ status=quiescent; break; }}
            sleep 0.1
        done
    fi
    [ -n "$status" ] || status=survivor
elif [ "$identity_rc" -eq 1 ]; then
    if group_exists; then
        status=identity_unavailable
    else
        status=quiescent
    fi
elif [ "$identity_rc" -eq 3 ]; then
    status=identity_mismatch
else
    status=uncertain
fi
printf '__RAS_COMMANDER_WSL_RECOVERY__ status=%s term=%s kill=%s pid=%s start=%s pgid=%s\n' "$status" "$term_sent" "$kill_sent" "$expected_pid" "$expected_start" "$expected_pgid"
"""
        try:
            result = subprocess.run(
                ["wsl", "bash", "-lc", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
        except Exception as exc:
            return {
                "attempted": True,
                "status": "uncertain",
                "quiescence_confirmed": None,
                "term_sent": False,
                "kill_sent": False,
                "solver_pid": solver_pid,
                "start_time_ticks": start_time_ticks,
                "process_group_id": process_group_id,
                "returncode": None,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        marker = "__RAS_COMMANDER_WSL_RECOVERY__"
        receipt_line = next(
            (
                line
                for line in reversed(result.stdout.splitlines())
                if line.startswith(f"{marker} ")
            ),
            None,
        )
        try:
            if result.returncode != 0 or receipt_line is None:
                raise ValueError("recovery receipt missing or command failed")
            fields = dict(
                token.split("=", 1)
                for token in receipt_line[len(marker) + 1 :].split()
            )
            status = fields["status"]
            term_sent = fields["term"] == "1"
            kill_sent = fields["kill"] == "1"
            if fields["term"] not in {"0", "1"}:
                raise ValueError("invalid TERM receipt")
            if fields["kill"] not in {"0", "1"}:
                raise ValueError("invalid KILL receipt")
            if int(fields["pid"]) != solver_pid:
                raise ValueError("recovery pid mismatch")
            if int(fields["start"]) != start_time_ticks:
                raise ValueError("recovery start-time mismatch")
            if int(fields["pgid"]) != process_group_id:
                raise ValueError("recovery process-group mismatch")
            if status not in {
                "quiescent",
                "survivor",
                "identity_mismatch",
                "identity_unavailable",
                "uncertain",
            }:
                raise ValueError("invalid recovery status")
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "attempted": True,
                "status": "uncertain",
                "quiescence_confirmed": None,
                "term_sent": False,
                "kill_sent": False,
                "solver_pid": solver_pid,
                "start_time_ticks": start_time_ticks,
                "process_group_id": process_group_id,
                "returncode": result.returncode,
                "detail": str(exc),
            }
        quiescence_confirmed = (
            True
            if status == "quiescent"
            else False
            if status == "survivor"
            else None
        )
        return {
            "attempted": True,
            "status": status,
            "quiescence_confirmed": quiescence_confirmed,
            "term_sent": term_sent,
            "kill_sent": kill_sent,
            "solver_pid": solver_pid,
            "start_time_ticks": start_time_ticks,
            "process_group_id": process_group_id,
            "returncode": result.returncode,
            "detail": None,
        }

    @staticmethod
    def _clear_wsl_supervision_state(
        state_path: Union[str, Path],
        identity: Dict[str, Any],
    ) -> bool:
        """Remove only a supervision record that still names ``identity``."""
        observed, _ = RasCmdr._read_wsl_supervision_identity(state_path)
        if observed != identity:
            return False
        try:
            Path(state_path).unlink()
        except OSError:
            return False
        return True

    @staticmethod
    def _acquire_wsl_plan_lease(
        state_path: Union[str, Path],
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Atomically reserve one plan's stable WSL supervision identity."""
        lease_path = Path(f"{state_path}.lease")
        token = uuid.uuid4().hex
        owner_pid = os.getpid()
        created_at = time.time()
        payload = (
            "ras_commander_wsl_plan_lease_v1\n"
            f"token={token}\n"
            f"pid={owner_pid}\n"
            f"created_at={created_at:.9f}\n"
        ).encode("ascii")
        try:
            descriptor = os.open(
                lease_path,
                os.O_CREAT
                | os.O_EXCL
                | os.O_RDWR
                | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except FileExistsError:
            try:
                existing_owner = lease_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[:4096]
            except OSError as exc:
                existing_owner = f"<unreadable: {type(exc).__name__}: {exc}>"
            return None, {
                "acquired": False,
                "lease_path": str(lease_path),
                "owner_token": None,
                "owner_pid": None,
                "created_at": None,
                "reason_code": "lease_exists",
                "reason": "WSL plan supervision lease already exists",
                "existing_owner": existing_owner,
            }
        except OSError as exc:
            return None, {
                "acquired": False,
                "lease_path": str(lease_path),
                "owner_token": None,
                "owner_pid": None,
                "created_at": None,
                "reason_code": "lease_creation_failed",
                "reason": f"lease creation failed: {type(exc).__name__}: {exc}",
                "existing_owner": None,
            }
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        except Exception as exc:
            os.close(descriptor)
            removed = False
            try:
                if lease_path.read_bytes() == payload:
                    lease_path.unlink()
                    removed = True
            except OSError:
                pass
            return None, {
                "acquired": False,
                "lease_path": str(lease_path),
                "owner_token": token,
                "owner_pid": owner_pid,
                "created_at": created_at,
                "reason_code": "lease_initialization_failed",
                "reason": (
                    "lease initialization failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                "existing_owner": None,
                "partial_lease_removed": removed,
            }
        lease = {
            "descriptor": descriptor,
            "path": lease_path,
            "token": token,
            "payload": payload,
        }
        return lease, {
            "acquired": True,
            "lease_path": str(lease_path),
            "owner_token": token,
            "owner_pid": owner_pid,
            "created_at": created_at,
            "reason_code": None,
            "reason": None,
            "existing_owner": None,
        }

    @staticmethod
    def _retain_wsl_plan_lease(lease: Dict[str, Any]) -> None:
        """Close our handle while deliberately retaining a fail-closed lease."""
        descriptor = lease.get("descriptor")
        if isinstance(descriptor, int) and descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        lease["descriptor"] = -1

    @staticmethod
    def _recover_wsl_from_state(
        state_path: Union[str, Path],
        *,
        expected_owner_token: str,
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, Any], bool]:
        """Recover an interrupted WSL run from its durable exact identity."""
        identity, identity_error = RasCmdr._read_wsl_supervision_identity(
            state_path,
            expected_owner_token=expected_owner_token,
        )
        if identity is None:
            return None, {
                "attempted": False,
                "status": "identity_unavailable",
                "quiescence_confirmed": None,
                "term_sent": False,
                "kill_sent": False,
                "solver_pid": None,
                "start_time_ticks": None,
                "process_group_id": None,
                "returncode": None,
                "detail": identity_error,
            }, False
        recovery = RasCmdr._recover_wsl_solver_identity(identity)
        state_cleared = False
        if recovery["quiescence_confirmed"] is True:
            state_cleared = RasCmdr._clear_wsl_supervision_state(
                state_path,
                identity,
            )
        return identity, recovery, state_cleared

    @staticmethod
    def _compute_plan_linux_via_wsl(
        ras_exe: str,
        ras_exe_dir: str,
        plan_number: str,
        geom_num: str,
        project_dir: Path,
        project_name: str,
        tmp_hdf: Path,
        timeout_sec: int,
        dos2unix: bool,
        retry: bool,
        retry_delay_sec: int,
        ras_obj,
    ) -> 'ComputeResult':
        """Run native Linux RasUnsteady from a Windows Python session via WSL."""
        state_path = project_dir / (
            f".{project_name}.p{plan_number}.ras-commander-wsl.identity"
        )
        initial_execution_details: Dict[str, Any] = {
            "execution_api": "ras_cmdr",
            "engine_kind": "native_linux_wsl",
            "selected_result_format": "hdf",
            "calculation_attempted": False,
            "solver_quiescence_confirmed": None,
            "result_artifacts_finalized": False,
            "selected_executable_path": ras_exe,
            "wsl_launcher_pid": None,
            "linux_solver_pid": None,
            "linux_solver_start_time_ticks": None,
            "linux_process_group_id": None,
            "linux_reported_returncode": None,
            "wsl_supervision_state_path": str(state_path),
            "wsl_supervision_lease": None,
            "wsl_supervision_lease_released": False,
            "wsl_supervision_preflight": None,
            "wsl_supervision_recovery": None,
        }
        wsl_plan_lease, lease_evidence = RasCmdr._acquire_wsl_plan_lease(
            state_path
        )
        initial_execution_details["wsl_supervision_lease"] = lease_evidence
        if wsl_plan_lease is None:
            initial_execution_details["failure_stage"] = (
                "wsl_supervision_lease"
            )
            initial_execution_details["duplicate_execution_blocked"] = bool(
                lease_evidence.get("reason_code") == "lease_exists"
            )
            if initial_execution_details["duplicate_execution_blocked"]:
                logger.error(
                    "Plan %s: refusing duplicate WSL execution because its "
                    "supervision lease is held: %s",
                    plan_number,
                    lease_evidence["lease_path"],
                )
            else:
                logger.error(
                    "Plan %s: refusing WSL execution because its supervision "
                    "lease could not be acquired: %s",
                    plan_number,
                    lease_evidence.get("reason"),
                )
            return ComputeResult(
                success=False,
                results_df_row=None,
                execution_details=initial_execution_details,
            )
        if state_path.exists():
            RasCmdr._retain_wsl_plan_lease(wsl_plan_lease)
            initial_execution_details["failure_stage"] = (
                "existing_wsl_supervision_state"
            )
            initial_execution_details["duplicate_execution_blocked"] = True
            logger.error(
                "Plan %s: refusing duplicate WSL execution because durable "
                "supervision state still exists: %s",
                plan_number,
                state_path,
            )
            return ComputeResult(
                success=False,
                results_df_row=None,
                execution_details=initial_execution_details,
            )

        preflight_ok, preflight_evidence = (
            RasCmdr._wsl_supervision_preflight()
        )
        initial_execution_details["wsl_supervision_preflight"] = (
            preflight_evidence
        )
        if not preflight_ok:
            initial_execution_details[
                "wsl_supervision_lease_released"
            ] = RasCmdr._release_destination_promotion_lock(wsl_plan_lease)
            initial_execution_details["failure_stage"] = (
                "wsl_supervision_preflight"
            )
            logger.error(
                "Plan %s: exact WSL supervision capabilities are unavailable; "
                "the solver was not launched",
                plan_number,
            )
            return ComputeResult(
                success=False,
                results_df_row=None,
                execution_details=initial_execution_details,
            )

        try:
            project_dir_wsl = RasCmdr._windows_path_to_wsl(project_dir)
            tmp_hdf_wsl = RasCmdr._windows_path_to_wsl(tmp_hdf)
            log_path = project_dir / f"compute_linux_{plan_number}.log"
            log_path_wsl = RasCmdr._windows_path_to_wsl(log_path)
        except BaseException:
            RasCmdr._release_destination_promotion_lock(wsl_plan_lease)
            raise

        if dos2unix:
            try:
                count = RasUtils.dos2unix(project_dir)
                logger.debug(f"dos2unix converted {count} files")
            except Exception as e:
                logger.warning(f"dos2unix failed before WSL execution: {e}")

        project_q = shlex.quote(project_dir_wsl)
        project_name_q = shlex.quote(project_name)
        ras_exe_q = shlex.quote(ras_exe)
        ras_exe_dir_q = shlex.quote(ras_exe_dir)
        tmp_hdf_q = shlex.quote(tmp_hdf_wsl)
        log_path_q = shlex.quote(log_path_wsl)
        geom_arg_q = shlex.quote(f"x{geom_num}")
        state_file_q = shlex.quote(state_path.name)
        lease_token_q = shlex.quote(str(wsl_plan_lease["token"]))

        cleanup_script = (
            f"cd {project_q} && "
            "find . -maxdepth 1 -type l -name 'io.*' -delete"
        )

        script = fr"""
set -e
cd {project_q}
find . -maxdepth 1 -type l -name 'io.*' -delete
link_or_copy() {{
    ln -sfn "$1" "$2" 2>/dev/null || cp -f "$1" "$2"
}}
prefix={project_name_q}.
link_or_copy {shlex.quote(f'{project_name}.b{plan_number}')} io.b
link_or_copy {shlex.quote(f'{project_name}.x{geom_num}')} io.X
link_or_copy {shlex.quote(f'{project_name}.x{geom_num}')} io.x
for f in {project_name_q}.*; do
    [ -e "$f" ] || continue
    suffix="${{f#$prefix}}"
    [ -e "io.$suffix" ] || link_or_copy "$f" "io.$suffix"
done
lib_base=""
if [ -d {ras_exe_dir_q}/libs ]; then
    lib_base={ras_exe_dir_q}/libs
elif [ -d "$(dirname {ras_exe_dir_q})/libs" ]; then
    lib_base="$(dirname {ras_exe_dir_q})/libs"
fi
if [ -n "$lib_base" ]; then
    ld_path="$lib_base"
    for d in "$lib_base"/*; do
        if [ -d "$d" ]; then
            ld_path="$ld_path:$d"
        fi
    done
else
    ld_path={ras_exe_dir_q}
fi
set +e
state_file={state_file_q}
owner_token={lease_token_q}
setsid --wait bash -c 'state_file=$1; owner_token=$2; shift 2; command_args=("$@"); stat_text=$(cat /proc/$$/stat) || exit 125; stat_tail="${{stat_text##*) }}"; set -- $stat_tail; solver_pgid=$3; solver_start=${{20}}; [ "$solver_pgid" = "$$" ] || exit 125; set -o noclobber; printf "ras_commander_wsl_identity_v2 token=%s pid=%s start=%s pgid=%s\n" "$owner_token" "$$" "$solver_start" "$solver_pgid" > "$state_file" || exit 125; sync "$state_file" || exit 125; exec env "${{command_args[@]}}"' ras-commander-wsl "$state_file" "$owner_token" "LD_LIBRARY_PATH=$ld_path" {ras_exe_q} {tmp_hdf_q} {geom_arg_q} > {log_path_q} 2>&1 &
wrapper_pid=$!
wait "$wrapper_pid"
solver_rc=$?
solver_pid=""
solver_start=""
solver_pgid=""
state_owner_token=""
if IFS=' ' read -r schema token_field pid_field start_field pgid_field < "$state_file"; then
    state_owner_token="${{token_field#token=}}"
    solver_pid="${{pid_field#pid=}}"
    solver_start="${{start_field#start=}}"
    solver_pgid="${{pgid_field#pgid=}}"
fi
case "$solver_pid:$solver_start:$solver_pgid" in
    *[!0-9:]*) solver_pid="" ;;
esac
if [ "$state_owner_token" = "$owner_token" ] && [ -n "$solver_pid" ] && [ "$solver_pid" = "$solver_pgid" ]; then
    if kill -0 -- "-$solver_pgid" 2>/dev/null; then
        group_quiescent=0
    else
        group_quiescent=1
    fi
    printf '__RAS_COMMANDER_WSL_EXIT_PROOF__ pid=%s start=%s pgid=%s rc=%s quiescent=%s\n' "$solver_pid" "$solver_start" "$solver_pgid" "$solver_rc" "$group_quiescent"
else
    printf '__RAS_COMMANDER_WSL_EXIT_PROOF__ invalid_identity=1 rc=%s\n' "$solver_rc"
fi
exit "$solver_rc"
"""

        max_attempts = 2 if retry else 1
        last_execution_details: Dict[str, Any] = {}

        def settle_plan_lease(*, release: bool) -> bool:
            if release:
                return RasCmdr._release_destination_promotion_lock(
                    wsl_plan_lease
                )
            RasCmdr._retain_wsl_plan_lease(wsl_plan_lease)
            return False

        for attempt in range(1, max_attempts + 1):
            logger.info(
                f"WSL Linux execution attempt {attempt}/{max_attempts} for plan {plan_number}"
            )

            # Remove any leftover io.tmp.hdf from previous run
            io_tmp_hdf = project_dir / "io.tmp.hdf"
            if io_tmp_hdf.exists():
                io_tmp_hdf.unlink()

            proc = None
            launcher_pid = None
            try:
                proc = subprocess.Popen(
                    ["wsl", "bash", "-lc", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
                launcher_pid = getattr(proc, "pid", None)
                if (
                    isinstance(launcher_pid, bool)
                    or not isinstance(launcher_pid, int)
                    or launcher_pid <= 0
                ):
                    launcher_pid = None
                stdout, stderr = proc.communicate(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.communicate(timeout=5)
                except BaseException:
                    pass
                identity, recovery, state_cleared = (
                    RasCmdr._recover_wsl_from_state(
                        state_path,
                        expected_owner_token=wsl_plan_lease["token"],
                    )
                )
                last_execution_details = dict(initial_execution_details)
                last_execution_details.update(
                    {
                        "calculation_attempted": proc is not None,
                        "solver_quiescence_confirmed": recovery[
                            "quiescence_confirmed"
                        ],
                        "wsl_launcher_pid": launcher_pid,
                        "linux_solver_pid": (
                            None
                            if identity is None
                            else identity["solver_pid"]
                        ),
                        "linux_solver_start_time_ticks": (
                            None
                            if identity is None
                            else identity["start_time_ticks"]
                        ),
                        "linux_process_group_id": (
                            None
                            if identity is None
                            else identity["process_group_id"]
                        ),
                        "wsl_supervision_recovery": recovery,
                        "wsl_supervision_state_cleared": state_cleared,
                        "failure_stage": "solver_timeout",
                    }
                )
                last_execution_details["wsl_supervision_lease_released"] = (
                    settle_plan_lease(
                        release=bool(
                            recovery["quiescence_confirmed"] is True
                            and state_cleared
                        )
                    )
                )
                logger.error(
                    "Plan %s: WSL RasUnsteady timed out after %ss; exact "
                    "recovery status=%s",
                    plan_number,
                    timeout_sec,
                    recovery["status"],
                )
                return ComputeResult(
                    success=False,
                    results_df_row=None,
                    execution_details=last_execution_details,
                )
            except BaseException as exc:
                if proc is not None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        proc.communicate(timeout=5)
                    except BaseException:
                        pass
                identity, recovery, state_cleared = (
                    RasCmdr._recover_wsl_from_state(
                        state_path,
                        expected_owner_token=wsl_plan_lease["token"],
                    )
                )
                interrupted_details = dict(initial_execution_details)
                interrupted_details.update(
                    {
                        "calculation_attempted": proc is not None,
                        "solver_quiescence_confirmed": recovery[
                            "quiescence_confirmed"
                        ],
                        "wsl_launcher_pid": launcher_pid,
                        "linux_solver_pid": (
                            None
                            if identity is None
                            else identity["solver_pid"]
                        ),
                        "linux_solver_start_time_ticks": (
                            None
                            if identity is None
                            else identity["start_time_ticks"]
                        ),
                        "linux_process_group_id": (
                            None
                            if identity is None
                            else identity["process_group_id"]
                        ),
                        "wsl_supervision_recovery": recovery,
                        "wsl_supervision_state_cleared": state_cleared,
                        "failure_stage": "solver_interrupted",
                    }
                )
                interrupted_details["wsl_supervision_lease_released"] = (
                    settle_plan_lease(
                        release=bool(
                            recovery["quiescence_confirmed"] is True
                            and state_cleared
                        )
                    )
                )
                try:
                    setattr(exc, "execution_details", interrupted_details)
                except Exception:
                    pass
                raise
            else:
                rc = proc.returncode
            proof = RasCmdr._parse_wsl_solver_exit_proof(stdout)
            identity, identity_error = (
                RasCmdr._read_wsl_supervision_identity(
                    state_path,
                    expected_owner_token=wsl_plan_lease["token"],
                )
            )
            proof_matches_identity = bool(
                identity is not None
                and proof["solver_pid"] == identity["solver_pid"]
                and proof["start_time_ticks"]
                == identity["start_time_ticks"]
                and proof["process_group_id"]
                == identity["process_group_id"]
                and proof["reported_returncode"] == rc
                and proof["quiescence_confirmed"] is True
            )
            recovery: Optional[Dict[str, Any]] = None
            state_cleared = False
            if proof_matches_identity:
                state_cleared = RasCmdr._clear_wsl_supervision_state(
                    state_path,
                    identity,
                )
                quiescence_confirmed: Optional[bool] = True
            else:
                identity, recovery, state_cleared = (
                    RasCmdr._recover_wsl_from_state(
                        state_path,
                        expected_owner_token=wsl_plan_lease["token"],
                    )
                )
                quiescence_confirmed = recovery[
                    "quiescence_confirmed"
                ]
            last_execution_details = dict(initial_execution_details)
            last_execution_details.update(
                {
                    "calculation_attempted": True,
                    "solver_quiescence_confirmed": quiescence_confirmed,
                    "wsl_launcher_pid": launcher_pid,
                    "linux_solver_pid": (
                        proof["solver_pid"]
                        if identity is None
                        else identity["solver_pid"]
                    ),
                    "linux_solver_start_time_ticks": (
                        proof["start_time_ticks"]
                        if identity is None
                        else identity["start_time_ticks"]
                    ),
                    "linux_process_group_id": (
                        proof["process_group_id"]
                        if identity is None
                        else identity["process_group_id"]
                    ),
                    "linux_reported_returncode": proof[
                        "reported_returncode"
                    ],
                    "wsl_exit_proof": proof,
                    "wsl_supervision_identity_error": identity_error,
                    "wsl_supervision_recovery": recovery,
                    "wsl_supervision_state_cleared": state_cleared,
                }
            )
            if quiescence_confirmed is not True:
                last_execution_details["failure_stage"] = (
                    "solver_quiescence"
                )
                logger.error(
                    "Plan %s: WSL solver process-group exit was not proved; "
                    "preserving all visible result families and refusing "
                    "validation, promotion, finalization, and retry",
                    plan_number,
                )
                last_execution_details[
                    "wsl_supervision_lease_released"
                ] = settle_plan_lease(release=False)
                return ComputeResult(
                    success=False,
                    results_df_row=None,
                    execution_details=last_execution_details,
                )
            if not state_cleared:
                last_execution_details["failure_stage"] = (
                    "wsl_supervision_state_release"
                )
                last_execution_details[
                    "wsl_supervision_lease_released"
                ] = settle_plan_lease(release=False)
                logger.error(
                    "Plan %s: solver quiescence was proved but its owned "
                    "supervision state could not be cleared; refusing "
                    "finalization and retaining the duplicate-run lease",
                    plan_number,
                )
                return ComputeResult(
                    success=False,
                    results_df_row=None,
                    execution_details=last_execution_details,
                )

            # The Linux shell waited for the exact solver process and proved
            # its process group empty. Only this positive receipt authorizes
            # removal of an opposing result recreated by HEC-RAS.
            try:
                finalize_plan_execution_artifacts(
                    plan_number,
                    output_format="hdf",
                    ras_object=ras_obj,
                )
            except Exception:
                last_execution_details["failure_stage"] = (
                    "result_artifact_finalization"
                )
                last_execution_details[
                    "wsl_supervision_lease_released"
                ] = settle_plan_lease(release=True)
                raise
            last_execution_details["result_artifacts_finalized"] = True

            if rc == 0:
                ok, reason = RasCmdr._validate_linux_solve(
                    log_path,
                    tmp_hdf,
                    plan_number,
                )
                if ok:
                    subprocess.run(
                        ["wsl", "bash", "-lc", cleanup_script],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    plan_hdf = RasCmdr._get_hdf_path(plan_number, ras_obj)
                    shutil.move(str(tmp_hdf), str(plan_hdf))
                    logger.debug(
                        f"Renamed {tmp_hdf.name} -> {plan_hdf.name}"
                    )

                    try:
                        ras_obj.plan_df = ras_obj.get_plan_entries()
                        ras_obj.update_results_df(plan_numbers=[plan_number])
                        mask = ras_obj.results_df['plan_number'] == plan_number
                        results_row = (
                            ras_obj.results_df[mask].iloc[0].copy()
                            if mask.any()
                            else None
                        )
                    except Exception as e:
                        logger.debug(
                            f"Could not extract results_df_row: {e}"
                        )
                        results_row = None

                    return ComputeResult(
                        success=True,
                        results_df_row=results_row,
                        execution_details={
                            **last_execution_details,
                            "wsl_supervision_lease_released": (
                                settle_plan_lease(release=True)
                            ),
                        },
                    )

                logger.error(
                    f"Plan {plan_number}: WSL RasUnsteady exited 0 but the "
                    f"solve did not produce a valid result: {reason}"
                )
            else:
                try:
                    tail = (
                        log_path.read_text(errors='replace')[-800:]
                        if log_path.exists()
                        else ""
                    )
                except OSError:
                    tail = "(log unreadable)"
                logger.error(
                    f"Plan {plan_number}: WSL RasUnsteady exited with code "
                    f"{rc}. stdout={stdout.strip()} stderr={stderr.strip()} "
                    f"log tail={tail}"
                )

            if attempt < max_attempts:
                logger.info(f"Retrying in {retry_delay_sec}s...")
                time.sleep(retry_delay_sec)

        subprocess.run(
            ["wsl", "bash", "-lc", cleanup_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return ComputeResult(
            success=False,
            results_df_row=None,
            execution_details={
                **last_execution_details,
                "wsl_supervision_lease_released": settle_plan_lease(
                    release=True
                ),
            },
        )
