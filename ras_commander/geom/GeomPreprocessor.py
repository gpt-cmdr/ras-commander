"""
GeomPreprocessor - Geometry preprocessor file operations

This module provides functionality for managing HEC-RAS geometry preprocessor
files. Geometry preprocessor files contain computed hydraulic properties
derived from the geometry.

All methods are static and designed to be used without instantiation.

List of Functions:
- run_geometry_preprocessor() - Execute the native geometry preprocessor
- clear_geompre_files() - Clear geometry preprocessor files for plan files
- invalidate_legacy_geometry_hdf_preprocessor_cache() - Backup-first,
  explicitly acknowledged recovery for exact HEC-RAS 5.x/6.x schemas
- clear_geompre_hdf() - Deprecated compatibility wrapper for guarded recovery

Example Usage:
    >>> from ras_commander import GeomPreprocessor, RasPlan
    >>>
    >>> # Clone a plan and geometry
    >>> new_plan_number = RasPlan.clone_plan("01")
    >>> new_geom_number = RasPlan.clone_geom("01")
    >>>
    >>> # Set the new geometry for the cloned plan
    >>> RasPlan.set_geom(new_plan_number, new_geom_number)
    >>> plan_path = RasPlan.get_plan_path(new_plan_number)
    >>>
    >>> # Clear geometry preprocessor files to ensure clean results
    >>> GeomPreprocessor.clear_geompre_files(plan_path)
"""

import re
import shutil
import subprocess
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any, List, Optional, Union

from .._ras_text import _write_ras_text
from ..ComputeResults import GeometryPreprocessResult
from ..Decorators import log_call
from ..LoggingConfig import get_logger
from ..RasBco import BcoMonitor
from ..RasPlan import RasPlan
from ..RasPrj import ras
from ..RasUtils import RasUtils
from ..results.ResultsParser import ResultsParser

logger = get_logger(__name__)


GEOMETRY_PREPROCESSOR_FLOW_START_SIGNALS = [
    "Starting Steady Flow Computations",
    "Steady Flow Simulation Version",
    "Starting Unsteady Flow Computations",
    "Unsteady Flow Computations",
    "Quasi-Unsteady Flow Computations",
    "Sediment Computations",
]

GEOMETRY_PREPROCESSOR_BLOCKING_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bDSS path needs correction\b",
        r"\bterrain\b.*\b(not found|missing|unable|cannot|failed)\b",
        r"\bland\s+cover\b.*\b(not found|missing|unable|cannot|failed)\b",
        r"\bprojection\b.*\b(not found|missing|unable|cannot|failed)\b",
        r"\b(could not find|file not found|not found|missing file)\b",
        r"\b(unable|cannot)\s+(open|read|load)\b",
        r"\bfatal\b",
    ]
]

GEOMETRY_PREPROCESSOR_GEOMETRY_ONLY_RUN_FLAGS = {
    "Run UNet": "0",
    "Run PostProcess": "0",
    "Run RASMapper": "0",
    "Run Sediment": "0",
    "Run WQNet": "0",
}


class GeomPreprocessor:
    """
    A class for managing HEC-RAS geometry preprocessor files.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    @log_call
    def run_geometry_preprocessor(
        plan_number: Union[str, int, float, Path],
        ras_object=None,
        max_wait: int = 600,
        force: bool = True,
        clear_messages: bool = True,
        clear_geompre: bool = False,
        geometry_only: bool = True,
        restore_plan_settings: bool = True,
        flow_start_signals: Optional[List[str]] = None,
        dialog_watchdog: bool = True,
    ) -> GeometryPreprocessResult:
        """
        Run HEC-RAS geometry preprocessing and review detailed compute messages.

        Launches the selected engine on the caller's writable project copy and
        waits for normal launcher and preprocessing-child exit. Compute messages
        are diagnostic signals, never permission to terminate a successful run.
        A timeout terminates owned work and returns failure. HDF inspection occurs
        only before launch and after process completion; all handles opened by
        this method are closed before engine execution.

        Existing geometry objects and attribute names must survive compilation.
        Missing objects fail the operation even when mesh topology is populated.
        Values may change through native recomputation; inventory preservation
        does not establish hydraulic acceptance. This method emits a result and
        captured stdout, modifies native artifacts in the project copy, and
        restores temporary plan flags when requested. It changes no CRS or units.

        Args:
            plan_number: Plan number or path to a plan file.
            ras_object (RasPrj, optional): Optional RasPrj instance. If None, uses the global ras.
            max_wait: Positive time budget in seconds, including setup and all
                observed native children. Expiry returns a failed result.
            force: If True, set ``Run HTab=-1`` and
                ``UNET Use Existing IB Tables=-1`` before running.
            clear_messages: Delete stale compute-message files before running.
            clear_geompre: Delete stale ``.c##`` files before running.
            geometry_only: If True, temporarily disables unsteady flow,
                post-processing, RAS Mapper, sediment, and water-quality run
                flags where those plan settings exist. This keeps validation
                focused on geometry preprocessing.
            restore_plan_settings: Restore original ``Run HTab`` and
                related run flag values after the run.
            flow_start_signals: Optional diagnostic message strings. Detection
                does not shorten the normal-exit wait.
            dialog_watchdog: Monitor and dismiss recognized native dialogs.

        Returns:
            GeometryPreprocessResult: Bool-compatible validation result.
        """
        start_time = time.time()
        ras_obj = ras_object or ras
        stdio = None
        if max_wait <= 0:
            return GeometryPreprocessResult(
                success=False,
                error="GEOMETRY_PREPROCESS_INVALID_TIMEOUT: max_wait must be positive",
            )

        try:
            ras_obj.check_initialized()
        except Exception as exc:
            return GeometryPreprocessResult(
                success=False,
                error=f"Project not initialized: {exc}",
                elapsed_seconds=time.time() - start_time,
            )

        try:
            plan_path = GeomPreprocessor._resolve_plan_path(plan_number, ras_obj)
            plan_num = GeomPreprocessor._extract_plan_number(plan_path)
            geometry_number = GeomPreprocessor._resolve_geometry_number(
                plan_path, plan_num, ras_obj
            )
            flow_type = GeomPreprocessor._resolve_flow_type(plan_num, ras_obj)

            project_folder = Path(ras_obj.project_folder)
            project_name = ras_obj.project_name
            prj_file = Path(ras_obj.prj_file)
            ras_exe_path = Path(ras_obj.ras_exe_path)

            if not plan_path.exists():
                return GeometryPreprocessResult(
                    success=False,
                    plan_number=plan_num,
                    geometry_number=geometry_number,
                    flow_type=flow_type,
                    error=f"Plan file not found: {plan_path}",
                    elapsed_seconds=time.time() - start_time,
                )

            if not prj_file.exists():
                return GeometryPreprocessResult(
                    success=False,
                    plan_number=plan_num,
                    geometry_number=geometry_number,
                    flow_type=flow_type,
                    error=f"Project file not found: {prj_file}",
                    elapsed_seconds=time.time() - start_time,
                )

            if not ras_exe_path.exists():
                return GeometryPreprocessResult(
                    success=False,
                    plan_number=plan_num,
                    geometry_number=geometry_number,
                    flow_type=flow_type,
                    error=f"HEC-RAS executable not found: {ras_exe_path}",
                    elapsed_seconds=time.time() - start_time,
                )

            message_paths = GeomPreprocessor._compute_message_paths(
                project_folder, project_name, plan_num
            )
            hdf_message_path = project_folder / f"{project_name}.p{plan_num}.hdf"
            tmp_hdf_path = project_folder / f"{project_name}.p{plan_num}.tmp.hdf"

            if clear_messages:
                GeomPreprocessor._delete_files(message_paths)
                GeomPreprocessor._delete_files([tmp_hdf_path])

            if clear_geompre:
                GeomPreprocessor.clear_geompre_files(plan_path, ras_object=ras_obj)

            original_plan_text = (
                plan_path.read_bytes()
                if restore_plan_settings
                else None
            )

            geometry_hdf_path = (
                project_folder / f"{project_name}.g{geometry_number}.hdf"
            )
            GeomPreprocessor._require_closed_geometry_hdf(geometry_hdf_path)
            expected_inventory = GeomPreprocessor._geometry_hdf_inventory(
                geometry_hdf_path
            )
            process = None
            _watchdog = None
            stdio = tempfile.TemporaryFile()  # noqa: SIM115 - closed by the outer finally
            child_monitor = {
                "saw_child": False,
                "timed_out": False,
                "tmp_hdf_path": None,
                "errors": [],
            }

            try:
                BcoMonitor.enable_detailed_logging(plan_path)

                if force:
                    RasPlan.set_geom_preprocessor(
                        plan_path,
                        run_htab=-1,
                        use_ib_tables=-1,
                        ras_object=ras_obj,
                    )

                if geometry_only:
                    GeomPreprocessor._set_plan_run_flags(
                        plan_path,
                        GEOMETRY_PREPROCESSOR_GEOMETRY_ONLY_RUN_FLAGS,
                    )

                from ..RasCmdr import RasCmdr

                command_text = RasCmdr._build_compute_command(
                    ras_obj, prj_file, plan_path
                )
                logger.debug("Running HEC-RAS geometry preprocessor validation:")
                logger.debug(command_text)

                _watchdog = None
                if dialog_watchdog:
                    from ..RasDialogWatchdog import DialogWatchdog
                    _watchdog = DialogWatchdog()
                    _watchdog.start()

                process = subprocess.Popen(
                    command_text,
                    cwd=str(project_folder),
                    executable=str(ras_exe_path),
                    shell=False,
                    stdout=stdio,
                    stderr=subprocess.STDOUT,
                )
                if _watchdog:
                    _watchdog.add_pid(process.pid)

                monitor_result = GeomPreprocessor._monitor_compute_messages(
                    process=process,
                    message_paths=message_paths,
                    start_time=start_time,
                    max_wait=max_wait,
                    signals=flow_start_signals
                    or GEOMETRY_PREPROCESSOR_FLOW_START_SIGNALS,
                )

                timed_out = monitor_result["timed_out"]
                signal_detected = monitor_result["signal_detected"]

                lifecycle_errors = monitor_result.get("errors", [])
                if timed_out or lifecycle_errors:
                    logger.error("Geometry preprocessing timed out; terminating HEC-RAS.")
                    lifecycle_errors.extend(GeomPreprocessor._terminate_process_tree(process) or [])
                    child_monitor = GeomPreprocessor._wait_for_preprocess_child(
                        tmp_hdf_path=tmp_hdf_path,
                        start_time=start_time,
                        max_wait=0,
                        tracked_children=monitor_result.get("children", ()),
                    )
                else:
                    process.wait()
                    child_monitor = GeomPreprocessor._wait_for_preprocess_child(
                        tmp_hdf_path=tmp_hdf_path,
                        start_time=start_time,
                        max_wait=max_wait,
                        tracked_children=monitor_result.get("children", ()),
                    )
            except BaseException:
                if process is not None and process.poll() is None:
                    GeomPreprocessor._terminate_process_tree(process)
                raise
            finally:
                try:
                    if _watchdog:
                        _watchdog.stop()
                finally:
                    if restore_plan_settings and original_plan_text is not None:
                        GeomPreprocessor._restore_plan_file(plan_path, original_plan_text)

            if process is None:
                raise RuntimeError("HEC-RAS process was not started")

            stdio.seek(0)
            stdout = stdio.read().decode("utf-8", errors="replace")
            stdio.close()
            if stdout:
                logger.debug(stdout)

            if timed_out or child_monitor["timed_out"]:
                return GeometryPreprocessResult(
                    success=False,
                    plan_number=plan_num,
                    geometry_number=geometry_number,
                    flow_type=flow_type,
                    elapsed_seconds=time.time() - start_time,
                    command=command_text,
                    return_code=process.returncode,
                    timed_out=True,
                    stdout=stdout,
                    signal_detected=signal_detected,
                    error=f"GEOMETRY_PREPROCESS_TIMEOUT: timed out after {max_wait} seconds"
                    + ("; " + "; ".join(lifecycle_errors + child_monitor.get("errors", []))
                       if lifecycle_errors or child_monitor.get("errors") else ""),
                )

            if lifecycle_errors or child_monitor.get("errors"):
                return GeometryPreprocessResult(
                    success=False,
                    plan_number=plan_num,
                    geometry_number=geometry_number,
                    flow_type=flow_type,
                    elapsed_seconds=time.time() - start_time,
                    command=command_text,
                    return_code=process.returncode,
                    error="GEOMETRY_PROCESS_COMPLETION_UNVERIFIED: "
                    + "; ".join(lifecycle_errors + child_monitor.get("errors", [])),
                )

            existing_message_paths, messages = (
                GeomPreprocessor._read_compute_messages(
                    message_paths,
                    hdf_message_path=hdf_message_path,
                    modified_after=start_time,
                )
            )
            artifact_paths = GeomPreprocessor._preprocessor_artifacts(
                project_folder,
                project_name,
                plan_num,
                geometry_number,
                tmp_hdf_path=tmp_hdf_path,
                modified_after=start_time,
            )

            parsed = ResultsParser.parse_compute_messages(messages)
            blocking_lines = GeomPreprocessor._find_blocking_message_lines(messages)

            errors = []
            if timed_out:
                errors.append(f"Timed out after {max_wait} seconds")
            if child_monitor["timed_out"]:
                errors.append(
                    f"Timed out after {max_wait} seconds waiting for RasProcess.exe"
                )
            if process.returncode != 0:
                errors.append(f"HEC-RAS exited with code {process.returncode}")
            if parsed["has_errors"]:
                errors.append(parsed["first_error_line"] or "Compute messages contain errors")
            if blocking_lines:
                errors.append(blocking_lines[0])
            if not artifact_paths:
                errors.append(
                    "No geometry preprocessor artifacts found "
                    f"(.c{geometry_number}, .g{geometry_number}.hdf, .x{geometry_number}, or .b{plan_num})"
                )
            missing_inventory = []
            if not timed_out and not child_monitor["timed_out"]:
                actual_inventory = GeomPreprocessor._geometry_hdf_inventory(
                    geometry_hdf_path
                )
                missing_inventory = GeomPreprocessor._missing_geometry_inventory(
                    expected_inventory, actual_inventory
                )
                if missing_inventory:
                    errors.append("GEOMETRY_INVENTORY_LOST: " + "; ".join(missing_inventory))
            geometry_hdf_ready, geometry_hdf_reason = (
                GeomPreprocessor._geometry_hdf_readiness(
                    geometry_hdf_path,
                    flow_type=flow_type,
                )
            )
            if geometry_only and not geometry_hdf_ready:
                errors.append(
                    "Geometry HDF is not semantically ready: "
                    f"{geometry_hdf_reason}"
                )
            if not existing_message_paths and not (geometry_only and artifact_paths):
                errors.append("No compute messages were produced")

            elapsed = time.time() - start_time
            return GeometryPreprocessResult(
                success=not errors,
                plan_number=plan_num,
                geometry_number=geometry_number,
                flow_type=flow_type,
                elapsed_seconds=elapsed,
                command=command_text,
                return_code=process.returncode,
                timed_out=timed_out or child_monitor["timed_out"],
                stdout=stdout,
                missing_geometry_inventory=missing_inventory,
                signal_detected=signal_detected,
                compute_message_paths=existing_message_paths,
                artifact_paths=artifact_paths,
                error_count=parsed["error_count"] + len(blocking_lines),
                warning_count=parsed["warning_count"],
                first_error_line=parsed["first_error_line"]
                or (blocking_lines[0] if blocking_lines else None),
                error="; ".join(errors) if errors else None,
            )

        except Exception as exc:
            logger.exception("Geometry preprocessor validation failed")
            return GeometryPreprocessResult(
                success=False,
                error=str(exc),
                elapsed_seconds=time.time() - start_time,
            )
        finally:
            if stdio is not None:
                stdio.close()

    @staticmethod
    def _resolve_plan_path(
        plan_number: Union[str, int, float, Path],
        ras_obj,
    ) -> Path:
        """Resolve a plan selector to a plan path."""
        if isinstance(plan_number, Path) and plan_number.exists():
            return plan_number
        if isinstance(plan_number, str):
            candidate = Path(plan_number)
            if candidate.exists():
                return candidate
        plan_path = RasPlan.get_plan_path(plan_number, ras_obj)
        if plan_path is None:
            raise FileNotFoundError(f"Plan not found: {plan_number}")
        return Path(plan_path)

    @staticmethod
    def _extract_plan_number(plan_path: Path) -> str:
        """Extract a two-digit plan number from a .p## path."""
        match = re.search(r"\.p(\d+)$", plan_path.name, re.IGNORECASE)
        if not match:
            raise ValueError(f"Could not determine plan number from {plan_path}")
        return RasUtils.normalize_ras_number(match.group(1))

    @staticmethod
    def _resolve_geometry_number(plan_path: Path, plan_num: str, ras_obj) -> str:
        """Resolve the geometry number used by a plan."""
        try:
            if getattr(ras_obj, "plan_df", None) is not None and not ras_obj.plan_df.empty:
                matching = ras_obj.plan_df[
                    ras_obj.plan_df["plan_number"].apply(RasUtils.normalize_ras_number)
                    == plan_num
                ]
                if not matching.empty:
                    for column_name in ("geometry_number", "Geom File"):
                        value = matching.iloc[0].get(column_name)
                        if value is None:
                            continue
                        digits = "".join(ch for ch in str(value) if ch.isdigit())
                        if digits:
                            return RasUtils.normalize_ras_number(digits)
        except Exception:
            pass

        content = plan_path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            if line.strip().startswith("Geom File="):
                digits = "".join(ch for ch in line.split("=", 1)[1] if ch.isdigit())
                if digits:
                    return RasUtils.normalize_ras_number(digits)
        raise ValueError(f"Could not determine geometry number for {plan_path}")

    @staticmethod
    def _resolve_flow_type(plan_num: str, ras_obj) -> str:
        """Return the canonical steady, unsteady, or quasi-unsteady type."""
        try:
            from ..RasPlan import RasPlan

            return RasPlan.get_plan_flow_type(plan_num, ras_obj)
        except Exception:
            return "Unknown"

    @staticmethod
    def _compute_message_paths(
        project_folder: Path,
        project_name: str,
        plan_num: str,
    ) -> List[Path]:
        """Return all detailed compute-message paths ras-commander should inspect."""
        return [
            project_folder / f"{project_name}.bco{plan_num}",
            project_folder / f"{project_name}.p{plan_num}.comp_msgs.txt",
            project_folder / f"{project_name}.p{plan_num}.computeMsgs.txt",
            project_folder / f"{project_name}.p{plan_num}.data_errors.txt",
            project_folder / f"{project_name}.p{plan_num}.data_warnings.txt",
        ]

    @staticmethod
    def _delete_files(paths: List[Path]) -> None:
        """Delete stale files if present."""
        for path in paths:
            if path.exists():
                try:
                    path.unlink()
                except OSError as exc:
                    logger.warning(f"Could not delete stale file {path}: {exc}")

    @staticmethod
    def _read_plan_preprocessor_settings(plan_path: Path) -> dict:
        """Read plan preprocessor flags so temporary force settings can be restored."""
        settings = {}
        content = plan_path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            stripped = line.lstrip()
            for key in (
                "Run HTab",
                "UNET Use Existing IB Tables",
                "Run UNet",
                "Run PostProcess",
                "Run RASMapper",
                "Run Sediment",
                "Run WQNet",
            ):
                if stripped.startswith(f"{key}="):
                    settings[key] = stripped.split("=", 1)[1].strip()
        return settings

    @staticmethod
    def _set_plan_run_flags(plan_path: Path, settings: dict[str, str]) -> None:
        """Temporarily set optional plan run flags when they exist."""
        lines = plan_path.read_text(encoding="utf-8", errors="ignore").splitlines(
            keepends=True
        )
        updated = []
        for line in lines:
            stripped = line.lstrip()
            replacement = None
            for key, value in settings.items():
                if stripped.startswith(f"{key}="):
                    prefix = line[: len(line) - len(stripped)]
                    replacement = f"{prefix}{key}= {value} \n"
                    break
            updated.append(replacement if replacement is not None else line)
        _write_ras_text(plan_path, "".join(updated), encoding="utf-8")

    @staticmethod
    def _restore_plan_preprocessor_settings(plan_path: Path, settings: dict) -> None:
        """Restore selected plan preprocessor flags."""
        if not settings:
            return
        lines = plan_path.read_text(encoding="utf-8", errors="ignore").splitlines(
            keepends=True
        )
        restored = []
        for line in lines:
            stripped = line.lstrip()
            replacement = None
            for key, value in settings.items():
                if stripped.startswith(f"{key}="):
                    prefix = line[: len(line) - len(stripped)]
                    replacement = f"{prefix}{key}= {value}\n"
                    break
            restored.append(replacement if replacement is not None else line)
        _write_ras_text(plan_path, "".join(restored), encoding="utf-8")

    @staticmethod
    def _restore_plan_file(plan_path: Path, original_text: bytes) -> None:
        """Restore the plan file exactly after temporary validation edits."""
        try:
            plan_path.write_bytes(original_text)
        except OSError as exc:
            raise RuntimeError(f"GEOMETRY_PLAN_RESTORE_FAILED: {exc}") from exc

    @staticmethod
    def _monitor_compute_messages(
        process: subprocess.Popen,
        message_paths: List[Path],
        start_time: float,
        max_wait: int,
        signals: List[str],
    ) -> dict:
        """Wait for normal exit, retaining message signals as diagnostics.

        Never inspect the geometry HDF while the engine may own it. Quiet file
        statistics and nonempty topology cannot establish flush/close completion.
        """
        positions = {path: 0 for path in message_paths}
        signal_detected = None
        deadline = time.monotonic() + max(0, max_wait - (time.time() - start_time))
        children = {}
        import psutil

        try:
            parent = psutil.Process(process.pid)
        except psutil.NoSuchProcess:
            return {"signal_detected": None, "timed_out": False, "children": (),
                    "errors": [] if process.poll() is not None else
                    ["launcher disappeared before its exit was observed"]}
        while process.poll() is None:
            if time.monotonic() >= deadline:
                return {"signal_detected": signal_detected, "timed_out": True,
                        "children": tuple(children.values()), "errors": []}
            try:
                for child in parent.children(recursive=True):
                    try:
                        # Desktop, console and plot-display helpers may remain
                        # alive under Wine after all geometry writers exit.
                        # Unknown children still require a confirmed exit.
                        if GeomPreprocessor._is_wine_display_child(child):
                            continue
                        if not child.is_running():
                            continue
                        identity = (child.pid, child.create_time())
                        if identity not in children:
                            children[identity] = GeomPreprocessor._watch_preprocess_child(child, deadline)
                    except psutil.NoSuchProcess:
                        continue
            except psutil.NoSuchProcess:
                if process.poll() is None:
                    return {"signal_detected": signal_detected, "timed_out": False,
                            "children": tuple(children.values()),
                            "errors": ["launcher disappeared before its exit was observed"]}
            except psutil.Error as exc:
                return {"signal_detected": signal_detected, "timed_out": False,
                        "children": tuple(children.values()), "errors": [str(exc)]}
            for path in message_paths:
                try:
                    if path.stat().st_mtime < start_time - 1:
                        continue
                    with path.open("r", encoding="utf-8", errors="ignore") as handle:
                        handle.seek(positions[path])
                        chunk = handle.read()
                        positions[path] = handle.tell()
                    for signal in signals:
                        if signal.lower() in chunk.lower():
                            signal_detected = signal
                except OSError:
                    continue
            time.sleep(0.5)
        return {"signal_detected": signal_detected, "timed_out": False,
                "children": tuple(children.values()), "errors": []}

    @staticmethod
    def _is_wine_display_child(child: Any) -> bool:
        """Identify Wine display processes by their exact non-file invocation."""
        from .._native_helper import _is_wine_helper_runtime

        if not _is_wine_helper_runtime():
            return False
        name = child.name().casefold()
        if name not in {"explorer.exe", "conhost.exe", "rasplotdriver.exe"}:
            return False
        arguments = child.cmdline()[1:]
        if name == "explorer.exe":
            return arguments == ["/desktop"]
        if name == "rasplotdriver.exe":
            return len(arguments) == 1 and arguments[0].isdigit()
        return (
            len(arguments) == 3 and arguments[0] == "--server"
            and re.fullmatch(r"0x[0-9a-fA-F]+", arguments[1]) is not None
            and arguments[2:] == ["--headless"]
        )

    @staticmethod
    def _require_closed_geometry_hdf(path: Path) -> None:
        """Reject caller-owned h5py file handles rather than closing them silently."""
        import h5py

        resolved = path.resolve()
        for file_id in h5py.h5f.get_obj_ids(types=h5py.h5f.OBJ_FILE):
            filename = h5py.h5f.get_name(file_id).decode("utf-8")
            if Path(filename).resolve() == resolved:
                raise RuntimeError(
                    "GEOMETRY_HDF_OPEN: close the geometry HDF handle before preprocessing"
                )

    @staticmethod
    def _geometry_hdf_inventory(path: Path) -> dict:
        """Snapshot object kinds and attribute names, closing the file on return."""
        import h5py

        if not path.exists():
            return {}
        result = {}
        with h5py.File(path, "r") as handle:
            def capture(name, obj):
                result[name] = {
                    "kind": "dataset" if isinstance(obj, h5py.Dataset) else "group",
                    "attributes": tuple(sorted(obj.attrs)),
                }
            capture("/", handle)
            handle.visititems(capture)
        return result

    @staticmethod
    def _missing_geometry_inventory(expected: dict, actual: dict) -> list[str]:
        """List missing objects, changed kinds, and lost attribute names."""
        missing = []
        for name, spec in expected.items():
            if name not in actual or spec["kind"] != actual[name]["kind"]:
                missing.append(name)
                continue
            missing.extend(
                f"{name}@{attribute}"
                for attribute in spec["attributes"]
                if attribute not in actual[name]["attributes"]
            )
        return sorted(missing)

    @staticmethod
    def _geometry_hdf_readiness(
        geometry_hdf_path: Path,
        flow_type: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Return whether a compiled geometry HDF contains usable geometry.

        HEC-RAS creates a small HDF placeholder containing only an empty
        ``/Geometry`` group before it imports the text geometry.  File
        existence, non-zero size, and a quiet modification time therefore do
        not prove preprocessing is complete.

        For a classified 2D plan, require at least one flow area with non-empty
        cell and face topology.  For other plan types, require a recognized,
        non-empty geometry feature collection.  The check is read-only and
        returns a diagnostic instead of raising while HEC-RAS still owns the
        file.
        """
        path = Path(geometry_hdf_path)
        if not path.is_file():
            return False, f"missing file: {path}"
        try:
            if path.stat().st_size <= 0:
                return False, f"empty file: {path}"
        except OSError as exc:
            return False, f"could not stat {path}: {exc}"

        try:
            import h5py

            with h5py.File(path, "r") as hdf:
                if not hdf.attrs.get("File Type"):
                    return False, "root File Type attribute is absent"
                if "Geometry" not in hdf:
                    return False, "/Geometry group is absent"

                normalized_flow_type = str(flow_type or "").casefold()
                if "2d" in normalized_flow_type:
                    collection_path = "Geometry/2D Flow Areas"
                    if collection_path not in hdf:
                        return False, "/Geometry/2D Flow Areas is absent"
                    collection = hdf[collection_path]
                    attributes = collection.get("Attributes")
                    if attributes is None or attributes.shape[0] == 0:
                        return False, "2D Flow Areas/Attributes is empty"

                    ready_areas = []
                    for name, item in collection.items():
                        if name == "Attributes" or not isinstance(item, h5py.Group):
                            continue
                        cells = item.get("Cells Center Coordinate")
                        faces = item.get("Faces FacePoint Indexes")
                        if (
                            cells is not None
                            and faces is not None
                            and cells.shape[0] > 0
                            and faces.shape[0] > 0
                        ):
                            ready_areas.append(name)
                    if not ready_areas:
                        return False, "no 2D flow area has non-empty cell/face topology"
                    return True, f"2D geometry ready: {', '.join(ready_areas)}"

                collection_paths = (
                    "Geometry/Cross Sections/Attributes",
                    "Geometry/River Centerlines/Attributes",
                    "Geometry/Storage Areas/Attributes",
                    "Geometry/Structures/Attributes",
                    "Geometry/SA 2D Area Conn/Attributes",
                    "Geometry/2D Flow Areas/Attributes",
                )
                populated = []
                for collection_path in collection_paths:
                    dataset = hdf.get(collection_path)
                    if dataset is not None and getattr(dataset, "shape", (0,))[0] > 0:
                        populated.append(collection_path)
                if not populated:
                    return False, "no recognized geometry feature collection is populated"
                return True, f"geometry ready: {', '.join(populated)}"
        except Exception as exc:
            return False, f"could not inspect geometry HDF: {type(exc).__name__}: {exc}"

    @staticmethod
    def _wait_for_preprocess_child(
        tmp_hdf_path: Path,
        start_time: float,
        max_wait: int,
        tracked_children: tuple = (),
    ) -> dict[str, Any]:
        """Wait for tracked and exact-path preprocessing children; never infer file quietness."""
        import psutil

        deadline = time.monotonic() + max(0, max_wait - (time.time() - start_time))
        children = {tuple(record["identity"]): record for record in tracked_children}
        errors = []
        timed_out = False
        exit_codes = {}
        try:
            while True:
                for pid in GeomPreprocessor._ras_processes_using_path(tmp_hdf_path):
                    try:
                        child = psutil.Process(pid)
                        identity = (pid, child.create_time())
                        if identity not in children:
                            children[identity] = GeomPreprocessor._watch_preprocess_child(child, deadline)
                    except psutil.NoSuchProcess:
                        continue
                active = []
                for identity, record in children.items():
                    if identity in exit_codes:
                        continue
                    if not record["finished"]:
                        active.append(record["process"])
                        continue
                    code = record["exit_code"]
                    exit_codes[identity] = code
                    timed_out = timed_out or record.get("timed_out", False)
                    if record["error"]:
                        errors.append(record["error"])
                    elif code != 0:
                        errors.append(f"preprocessing child {identity[0]} exit status {code!r}")
                if not active:
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                time.sleep(0.5)
        except (psutil.Error, RuntimeError) as exc:
            errors.append(str(exc))
        if timed_out or errors:
            for identity, record in children.items():
                child = record["process"]
                try:
                    if child.is_running() and child.create_time() == identity[1]:
                        child.kill()
                        child.wait(timeout=10)
                except psutil.NoSuchProcess:
                    pass
                except psutil.Error as exc:
                    errors.append(f"owned child cleanup failed: {exc}")
        return {
            "saw_child": bool(children), "timed_out": timed_out,
            "tmp_hdf_path": tmp_hdf_path, "errors": errors,
        }

    @staticmethod
    def _watch_preprocess_child(child: Any, deadline: float) -> dict:
        """Begin an owned-process wait while the native exit handle is available."""
        import threading

        import psutil

        record = {
            "identity": (child.pid, child.create_time()), "process": child,
            "finished": False, "exit_code": None, "error": None, "timed_out": False,
        }
        def wait():
            try:
                record["exit_code"] = child.wait(timeout=max(0, deadline - time.monotonic()))
            except psutil.TimeoutExpired as exc:
                record["timed_out"] = True
                record["error"] = "preprocessing child timed out: " + str(exc)
            except psutil.Error as exc:
                record["error"] = "preprocessing child wait failed: " + str(exc)
            finally:
                record["finished"] = True
        threading.Thread(target=wait, daemon=True).start()
        return record

    @staticmethod
    def _ras_processes_using_path(path: Path) -> List[int]:
        """Find exact-path native preprocessing processes; unknown inspection fails."""
        import ntpath

        import psutil

        def normalize(value):
            return ntpath.normcase(ntpath.normpath(str(value).strip('"')))

        target = normalize(path)
        pids = []
        for process in psutil.process_iter():
            try:
                name = process.name().casefold()
                if name not in ("rasprocess.exe", "rasgeompreprocess.exe"):
                    continue
                tokens = process.cmdline()
                if any(normalize(token) == target for token in tokens):
                    pids.append(process.pid)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except psutil.AccessDenied as exc:
                raise RuntimeError("GEOMETRY_PROCESS_INSPECTION_FAILED: " + str(exc)) from exc
        return pids

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> list[str]:
        """Cancel owned work after failure, retaining inspection and cleanup errors."""
        import psutil
        errors = []
        children = []
        try:
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            pass
        except psutil.Error as exc:
            errors.append(f"owned tree inspection failed: {exc}")
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                errors.append(f"owned child cleanup failed: {exc}")
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"owned launcher cleanup failed: {exc}")
        for child in children:
            try:
                child.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                errors.append(f"owned child reap failed: {exc}")
        return errors

    @staticmethod
    def _read_compute_messages(
        message_paths: List[Path],
        hdf_message_path: Optional[Path] = None,
        modified_after: Optional[float] = None,
    ) -> tuple[List[Path], str]:
        """Read available compute-message files."""
        existing_paths = []
        chunks = []
        for path in message_paths:
            if not path.exists() or path.stat().st_size == 0:
                continue
            if not GeomPreprocessor._path_is_fresh(path, modified_after):
                continue
            existing_paths.append(path)
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError as exc:
                logger.warning(f"Could not read compute messages from {path}: {exc}")

        if (
            hdf_message_path
            and hdf_message_path.exists()
            and hdf_message_path.stat().st_size > 0
            and GeomPreprocessor._path_is_fresh(hdf_message_path, modified_after)
        ):
            try:
                from ..hdf.HdfResultsPlan import HdfResultsPlan

                hdf_messages = HdfResultsPlan.get_compute_messages_hdf_only(
                    hdf_message_path
                )
                if hdf_messages:
                    existing_paths.append(hdf_message_path)
                    chunks.append(hdf_messages)
            except Exception as exc:
                logger.debug(
                    f"Could not read HDF compute messages from {hdf_message_path}: {exc}"
                )
        return existing_paths, "\n".join(chunks)

    @staticmethod
    def _preprocessor_artifacts(
        project_folder: Path,
        project_name: str,
        plan_num: str,
        geometry_number: str,
        tmp_hdf_path: Optional[Path] = None,
        modified_after: Optional[float] = None,
    ) -> List[Path]:
        """Collect non-empty artifacts that prove geometry preprocessing ran."""
        candidates = [
            project_folder / f"{project_name}.c{geometry_number}",
            project_folder / f"{project_name}.g{geometry_number}.hdf",
            project_folder / f"{project_name}.x{geometry_number}",
            project_folder / f"{project_name}.b{plan_num}",
        ]
        if tmp_hdf_path is not None:
            candidates.append(tmp_hdf_path)
        return [
            path
            for path in candidates
            if path.exists()
            and path.is_file()
            and path.stat().st_size > 0
            and GeomPreprocessor._path_is_fresh(path, modified_after)
        ]

    @staticmethod
    def _path_is_fresh(path: Path, modified_after: Optional[float]) -> bool:
        """Return True when a path is absent from staleness checks or recently written."""
        if modified_after is None:
            return True
        try:
            return path.exists() and path.stat().st_mtime >= modified_after - 1
        except OSError:
            return False

    @staticmethod
    def _find_blocking_message_lines(messages: str) -> List[str]:
        """Find message lines that indicate broken project assembly."""
        blocking_lines = []
        for line in messages.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if any(pattern.search(stripped) for pattern in GEOMETRY_PREPROCESSOR_BLOCKING_PATTERNS):
                # Avoid common non-blocking metric text.
                if re.search(r"volume\s+accounting\s+error", stripped, re.IGNORECASE):
                    continue
                blocking_lines.append(stripped[:300])
        return blocking_lines

    # Solver-owned datasets removed by the legacy selective-invalidation
    # recovery. This list is intentionally closed: an unfamiliar schema must
    # be handled by native HEC-RAS recomputation, not broader deletion.
    _LEGACY_GEOMPRE_HDF_ABSOLUTE_PATHS = (
        "Geometry/GeomPreprocess",
        "Geometry/Cross Sections/Property Tables",
        "Geometry/Cross Sections/Flow Distribution",
        "Geometry/Boundary Condition Lines/External Faces",
        "Geometry/Storage Areas/Polygon Area",
        "Geometry/Land Cover (Manning's n)/External Faces",
        "Geometry/Land Cover (Manning's n)/Internal Cells",
        "Geometry/Land Cover (Manning's n)/Internal Faces",
    )
    _LEGACY_GEOMPRE_HDF_AREA_DATASETS = (
        "Cells Center Manning's n",
        "Cells Minimum Elevation",
        "Cells Surface Area",
        "Cells Volume Elevation Info",
        "Cells Volume Elevation Values",
        "Faces Area Elevation Info",
        "Faces Area Elevation Values",
        "Faces Low Elevation Centroid",
        "Faces Minimum Elevation",
    )
    _LEGACY_GEOMPRE_HDF_AREA_DATASET_PAIRS = (
        ("Cells Volume Elevation Info", "Cells Volume Elevation Values"),
        ("Faces Area Elevation Info", "Faces Area Elevation Values"),
    )
    _LEGACY_GEOMETRY_HDF_PATTERN = re.compile(
        r"\.g\d+\.hdf$",
        re.IGNORECASE,
    )
    _LEGACY_HECRAS_VERSION_PATTERN = re.compile(
        r"^HEC-RAS\s+(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _decode_hdf_attribute(value: Any) -> str:
        """Decode a scalar HDF attribute for strict role/version checks."""
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").strip("\x00")
        if hasattr(value, "decode"):
            return value.decode("utf-8", errors="replace").strip("\x00")
        return str(value).strip("\x00")

    @staticmethod
    def _legacy_recovery_backup_path(
        geom_hdf_path: Path,
        backup_path: Optional[Union[str, Path]],
    ) -> Path:
        """Resolve a non-overwriting backup path for legacy recovery."""
        if backup_path is None:
            backup_path = geom_hdf_path.with_name(
                f"{geom_hdf_path.stem}.legacy-recovery.bak.hdf"
            )
        resolved = Path(backup_path)
        if resolved.resolve(strict=False) == geom_hdf_path.resolve(strict=False):
            raise ValueError("backup_path must differ from geom_hdf_path.")
        if not resolved.parent.exists():
            raise FileNotFoundError(
                f"Backup directory does not exist: {resolved.parent}"
            )
        if resolved.exists():
            raise FileExistsError(
                f"Legacy recovery backup already exists: {resolved}. "
                "Provide a new backup_path rather than overwriting it."
            )
        return resolved

    @staticmethod
    def _validate_legacy_geometry_hdf_recovery(
        hdf: Any,
        geom_hdf_path: Path,
        expected_file_version: str,
    ) -> List[str]:
        """Validate the known HEC-RAS 5/6 geometry-HDF recovery schema."""
        import h5py

        if not GeomPreprocessor._LEGACY_GEOMETRY_HDF_PATTERN.search(
            geom_hdf_path.name
        ):
            raise ValueError(
                "Legacy recovery accepts only geometry HDF filenames matching "
                "'*.g##.hdf'."
            )

        file_type = GeomPreprocessor._decode_hdf_attribute(
            hdf.attrs.get("File Type")
        )
        file_version = GeomPreprocessor._decode_hdf_attribute(
            hdf.attrs.get("File Version")
        )
        if file_type != "HEC-RAS Geometry":
            raise ValueError(
                "Legacy recovery requires root File Type='HEC-RAS Geometry'; "
                f"observed {file_type!r}."
            )
        if file_version != expected_file_version:
            raise ValueError(
                "Legacy recovery file-version guard failed: expected "
                f"{expected_file_version!r}, observed {file_version!r}."
            )
        version_match = GeomPreprocessor._LEGACY_HECRAS_VERSION_PATTERN.match(
            file_version
        )
        if version_match is None or int(version_match.group("major")) not in {5, 6}:
            raise ValueError(
                "Selective geometry-HDF invalidation is restricted to legacy "
                "HEC-RAS 5.x/6.x artifacts. Use native recomputation for "
                f"{file_version!r}."
            )
        if "Geometry" not in hdf or not isinstance(hdf["Geometry"], h5py.Group):
            raise ValueError("Geometry HDF is missing the /Geometry group.")

        targets: List[str] = []
        for path in GeomPreprocessor._LEGACY_GEOMPRE_HDF_ABSOLUTE_PATHS:
            if path in hdf:
                targets.append(path)

        areas_path = "Geometry/2D Flow Areas"
        if areas_path in hdf:
            areas = hdf[areas_path]
            if not isinstance(areas, h5py.Group):
                raise ValueError(f"{areas_path!r} is not an HDF group.")
            for area_name, area in areas.items():
                if not isinstance(area, h5py.Group):
                    continue
                for left, right in (
                    GeomPreprocessor._LEGACY_GEOMPRE_HDF_AREA_DATASET_PAIRS
                ):
                    if (left in area) != (right in area):
                        raise ValueError(
                            f"Mesh {area_name!r} has an incomplete legacy "
                            f"property-table pair: {left!r}/{right!r}."
                        )
                for dataset_name in (
                    GeomPreprocessor._LEGACY_GEOMPRE_HDF_AREA_DATASETS
                ):
                    if dataset_name not in area:
                        continue
                    if not isinstance(area[dataset_name], h5py.Dataset):
                        raise ValueError(
                            f"Expected dataset at {areas_path}/{area_name}/"
                            f"{dataset_name}."
                        )
                    targets.append(
                        f"{areas_path}/{area_name}/{dataset_name}"
                    )
        return targets

    @staticmethod
    @log_call
    def invalidate_legacy_geometry_hdf_preprocessor_cache(
        geom_hdf_path: Union[str, Path],
        *,
        expected_file_version: str,
        acknowledge_legacy_recovery: bool = False,
        backup_path: Optional[Union[str, Path]] = None,
    ) -> List[str]:
        """Selectively invalidate a known HEC-RAS 5/6 geometry-HDF cache.

        This is an opt-in recovery utility for legacy projects where native
        property-table recomputation is unavailable or has already failed. It
        is not the normal preprocessing path. Prefer
        ``RasMap.recompute_property_tables()`` or a completed native plan
        recompute.

        The method accepts only ``*.g##.hdf`` files whose root attributes are
        exactly ``File Type='HEC-RAS Geometry'`` and the caller-supplied
        ``expected_file_version``. HEC-RAS 7.x and unfamiliar schemas fail
        closed. A non-overwriting full-file backup is created before any
        dataset is removed.

        ``force_geompre`` does not call this recovery utility. It preserves the
        geometry HDF, bypasses the smart results skip, clears ``.c##`` files,
        and requests native complete-geometry processing instead.

        Args:
            geom_hdf_path: Existing HEC-RAS geometry HDF.
            expected_file_version: Exact root ``File Version`` attribute,
                including the release month/year text.
            acknowledge_legacy_recovery: Must be explicitly ``True``.
            backup_path: Optional backup destination. By default, writes
                ``<stem>.legacy-recovery.bak.hdf`` beside the source and
                refuses to overwrite an existing backup.

        Returns:
            HDF paths removed from the source file. An already-invalidated,
            otherwise valid file returns an empty list without creating a
            backup.
        """
        if not acknowledge_legacy_recovery:
            raise RuntimeError(
                "Legacy geometry-HDF invalidation requires "
                "acknowledge_legacy_recovery=True. Prefer native "
                "RasMap.recompute_property_tables() or plan recomputation."
            )
        if not expected_file_version:
            raise ValueError("expected_file_version must be provided exactly.")

        import h5py

        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            raise FileNotFoundError(geom_hdf_path)
        if not geom_hdf_path.is_file():
            raise ValueError(f"Geometry HDF path is not a file: {geom_hdf_path}")

        with h5py.File(geom_hdf_path, "r") as hdf:
            targets = GeomPreprocessor._validate_legacy_geometry_hdf_recovery(
                hdf,
                geom_hdf_path,
                expected_file_version,
            )
        if not targets:
            logger.info(
                "No recognized legacy preprocessor datasets remain in %s",
                geom_hdf_path.name,
            )
            return []

        resolved_backup = GeomPreprocessor._legacy_recovery_backup_path(
            geom_hdf_path,
            backup_path,
        )
        shutil.copy2(geom_hdf_path, resolved_backup)

        try:
            with h5py.File(geom_hdf_path, "r+") as hdf:
                for path in targets:
                    if path in hdf:
                        del hdf[path]
            with h5py.File(geom_hdf_path, "r") as hdf:
                remaining = [path for path in targets if path in hdf]
                GeomPreprocessor._validate_legacy_geometry_hdf_recovery(
                    hdf,
                    geom_hdf_path,
                    expected_file_version,
                )
            if remaining:
                raise RuntimeError(
                    "Legacy invalidation readback found undeleted paths: "
                    + ", ".join(remaining)
                )
        except Exception as exc:
            raise RuntimeError(
                "Legacy geometry-HDF invalidation failed. The original backup "
                f"is available at {resolved_backup}: {exc}"
            ) from exc

        logger.warning(
            "Legacy recovery removed %d solver-owned path(s) from %s; "
            "backup=%s",
            len(targets),
            geom_hdf_path.name,
            resolved_backup,
        )
        return targets

    @staticmethod
    @log_call
    def clear_geompre_hdf(
        geom_hdf_path: Union[str, Path],
        *,
        expected_file_version: Optional[str] = None,
        acknowledge_legacy_recovery: bool = False,
        backup_path: Optional[Union[str, Path]] = None,
    ) -> List[str]:
        """Deprecated compatibility wrapper for guarded legacy recovery.

        Prefer native ``RasMap.recompute_property_tables()`` or plan
        recomputation. To intentionally retain the historical selective
        invalidation behavior, callers must provide the exact file version and
        set ``acknowledge_legacy_recovery=True``.
        """
        warnings.warn(
            "GeomPreprocessor.clear_geompre_hdf() is deprecated. Prefer "
            "RasMap.recompute_property_tables() or a native plan recompute; "
            "for legacy recovery use "
            "invalidate_legacy_geometry_hdf_preprocessor_cache(). The "
            "compatibility name is retained through v1.1.x and will be "
            "removed no earlier than v1.2.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        if not acknowledge_legacy_recovery:
            raise RuntimeError(
                "clear_geompre_hdf() no longer mutates silently. Pass "
                "acknowledge_legacy_recovery=True and expected_file_version, "
                "or use native HEC-RAS recomputation."
            )
        if not expected_file_version:
            raise ValueError("expected_file_version must be provided exactly.")
        return GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache(
            geom_hdf_path,
            expected_file_version=expected_file_version,
            acknowledge_legacy_recovery=True,
            backup_path=backup_path,
        )

    @staticmethod
    @log_call
    def clear_geompre_files(
        plan_files: Union[str, Path, List[Union[str, Path]]] = None,
        ras_object=None
    ) -> None:
        """
        Clear HEC-RAS geometry preprocessor files for specified plan files.

        Geometry preprocessor files (.c* extension) contain computed hydraulic properties derived
        from the geometry. These should be cleared when the geometry changes to ensure that
        HEC-RAS recomputes all hydraulic tables with updated geometry information.

        This deletes the `.c##` geometry-preprocessor file only. It deliberately
        does not mutate the `.g##.hdf`; use a native HEC-RAS geometry or plan
        computation to refresh solver-owned HDF datasets.

        Limitations/Future Work:
        - It does not clear the IB (internal boundary) tables.

        Parameters:
            plan_files (Union[str, Path, List[Union[str, Path]]], optional):
                Full path(s) to the HEC-RAS plan file(s) (.p*).
                If None, clears all plan files in the project directory.
            ras_object (RasPrj, optional): An optional RAS object instance.

        Returns:
            None: The function deletes files and updates the ras object's geometry dataframe

        Example:
            >>> # Clone a plan and geometry
            >>> new_plan_number = RasPlan.clone_plan("01")
            >>> new_geom_number = RasPlan.clone_geom("01")
            >>>
            >>> # Set the new geometry for the cloned plan
            >>> RasPlan.set_geom(new_plan_number, new_geom_number)
            >>> plan_path = RasPlan.get_plan_path(new_plan_number)
            >>>
            >>> # Clear geometry preprocessor files to ensure clean results
            >>> GeomPreprocessor.clear_geompre_files(plan_path)
            >>> print(f"Cleared geometry preprocessor files for plan {new_plan_number}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        def _resolve_geompre_candidates(plan_path: Path, ras_obj) -> List[Path]:
            """Resolve likely .c## files from plan metadata, then fall back to plan suffix."""
            candidates = []
            plan_match = re.search(r"\.p(\d+)$", plan_path.name, re.IGNORECASE)
            plan_number = RasUtils.normalize_ras_number(plan_match.group(1)) if plan_match else None

            if (
                plan_number is not None
                and getattr(ras_obj, "plan_df", None) is not None
                and not ras_obj.plan_df.empty
                and "plan_number" in ras_obj.plan_df.columns
                and "geometry_number" in ras_obj.plan_df.columns
            ):
                normalized_plan_numbers = ras_obj.plan_df["plan_number"].apply(RasUtils.normalize_ras_number)
                matching = ras_obj.plan_df[normalized_plan_numbers == plan_number]
                if not matching.empty:
                    geom_number = RasUtils.normalize_ras_number(matching.iloc[0]["geometry_number"])
                    if geom_number is not None:
                        candidates.append(plan_path.with_suffix(f".c{geom_number}"))

            geom_preprocessor_suffix = '.c' + ''.join(plan_path.suffixes[1:]) if plan_path.suffixes else '.c'
            candidates.append(plan_path.with_suffix(geom_preprocessor_suffix))

            unique_candidates = []
            seen = set()
            for candidate in candidates:
                candidate_str = str(candidate)
                if candidate_str not in seen:
                    unique_candidates.append(candidate)
                    seen.add(candidate_str)
            return unique_candidates

        def clear_single_file(plan_file: Union[str, Path], ras_obj) -> None:
            plan_path = Path(plan_file)
            cleared_any = False
            for geom_preprocessor_file in _resolve_geompre_candidates(plan_path, ras_obj):
                if not geom_preprocessor_file.exists():
                    continue
                try:
                    geom_preprocessor_file.unlink()
                    logger.debug(f"Deleted geometry preprocessor file: {geom_preprocessor_file}")
                    cleared_any = True
                    break
                except PermissionError:
                    logger.error(f"Permission denied: Unable to delete geometry preprocessor file: {geom_preprocessor_file}")
                    raise PermissionError(f"Unable to delete geometry preprocessor file: {geom_preprocessor_file}. Permission denied.")
                except OSError as e:
                    logger.error(f"Error deleting geometry preprocessor file: {geom_preprocessor_file}. {str(e)}")
                    raise OSError(f"Error deleting geometry preprocessor file: {geom_preprocessor_file}. {str(e)}")

            if not cleared_any:
                logger.debug("No geometry preprocessor artifacts found for plan: %s", plan_path.name)

        if plan_files is None:
            logger.info("Clearing all geometry preprocessor files in the project directory.")
            plan_files_to_clear = list(ras_obj.project_folder.glob(r'*.p*'))
        elif isinstance(plan_files, (str, Path)):
            plan_files_to_clear = [plan_files]
            logger.debug(
                "Clearing geometry preprocessor file for single plan: %s",
                Path(plan_files).name,
            )
            logger.debug(f"Clearing geometry preprocessor file for single plan path: {plan_files}")
        elif isinstance(plan_files, list):
            plan_files_to_clear = plan_files
            plan_file_names = [Path(plan_file).name for plan_file in plan_files]
            logger.debug(
                "Clearing geometry preprocessor files for multiple plans: %s",
                plan_file_names,
            )
            logger.debug(f"Clearing geometry preprocessor files for multiple plan paths: {plan_files}")
        else:
            logger.error("Invalid input type for plan_files.")
            raise ValueError("Invalid input. Please provide a string, Path, list of paths, or None.")

        for plan_file in plan_files_to_clear:
            clear_single_file(plan_file, ras_obj)

        try:
            ras_obj.geom_df = ras_obj.get_geom_entries()
            logger.debug("Geometry dataframe updated successfully.")
        except Exception as e:
            logger.error(f"Failed to update geometry dataframe: {str(e)}")
            raise
