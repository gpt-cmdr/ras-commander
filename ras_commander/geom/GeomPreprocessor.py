"""
GeomPreprocessor - Geometry preprocessor file operations

This module provides functionality for managing HEC-RAS geometry preprocessor
files. Geometry preprocessor files contain computed hydraulic properties
derived from the geometry.

All methods are static and designed to be used without instantiation.

List of Functions:
- clear_geompre_files() - Clear geometry preprocessor files for plan files

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
import subprocess
import time
from pathlib import Path
from typing import Any, List, Optional, Union

from ..ComputeResults import GeometryPreprocessResult
from ..LoggingConfig import get_logger
from ..Decorators import log_call
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

        .. note::
           This method is designed for **pre-flight geometry validation**,
           particularly for Linux/headless execution environments where the
           HEC-RAS GUI is unavailable.  It launches ``Ras.exe``, monitors
           compute messages for the start of flow computations, then
           terminates early — it is **not** a general-purpose geometry
           preprocessor suitable for notebooks or interactive workflows.

           For general-purpose geometry preprocessing (e.g. resampling
           land-cover overrides), use ``RasCmdr.compute_plan()`` with the
           plan temporarily configured to force preprocessing
           (``Run HTab=-1``) and skip unsteady/post-processing/mapping
           (``Run UNet=0``, ``Run PostProcess=0``, ``Run RASMapper=0``),
           combined with ``clear_geompre=True``.

        This method uses the ras-commander execution flow rather than invoking
        the standalone ``RasGeomPreprocess.exe`` directly:

        1. Initialize/validate the ras project and target plan.
        2. Enable detailed logging in the plan file.
        3. Optionally force geometry preprocessing via plan flags.
        4. Launch ``Ras.exe -c <project.prj> <plan.p##>``.
        5. Monitor detailed compute messages for the start of hydraulic
           computations, then terminate early when possible.
        6. Parse ``.bco##``, detailed compute messages, and
           ``.data_errors.txt``/``.data_warnings.txt`` for blocking errors.

        Args:
            plan_number: Plan number or path to a plan file.
            ras_object: Optional RasPrj instance. If None, uses the global ras.
            max_wait: Maximum seconds to wait for preprocessing.
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
            flow_start_signals: Optional message strings that indicate geometry
                preprocessing has finished and flow computation is starting.

        Returns:
            GeometryPreprocessResult: Bool-compatible validation result.
        """
        start_time = time.time()
        ras_obj = ras_object or ras

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
                plan_path.read_text(encoding="utf-8", errors="ignore")
                if restore_plan_settings
                else None
            )

            process = None
            child_monitor = {
                "saw_child": False,
                "timed_out": False,
                "tmp_hdf_path": None,
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

                command_text = (
                    f'"{ras_exe_path}" -c "{prj_file}" "{plan_path}"'
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
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if _watchdog:
                    _watchdog.add_pid(process.pid)

                geom_only_artifacts = None
                if geometry_only:
                    geom_only_artifacts = [
                        project_folder / f"{project_name}.c{geometry_number}",
                        project_folder / f"{project_name}.g{geometry_number}.hdf",
                        project_folder / f"{project_name}.x{geometry_number}",
                    ]

                monitor_result = GeomPreprocessor._monitor_compute_messages(
                    process=process,
                    message_paths=message_paths,
                    start_time=start_time,
                    max_wait=max_wait,
                    signals=flow_start_signals
                    or GEOMETRY_PREPROCESSOR_FLOW_START_SIGNALS,
                    geometry_only_artifacts=geom_only_artifacts,
                )

                timed_out = monitor_result["timed_out"]
                signal_detected = monitor_result["signal_detected"]

                if signal_detected and process.poll() is None:
                    logger.debug(
                        "Geometry preprocessing signal detected; terminating flow "
                        "computation before full plan execution."
                    )
                    GeomPreprocessor._terminate_process_tree(process)
                elif timed_out and process.poll() is None:
                    logger.error("Geometry preprocessing timed out; terminating HEC-RAS.")
                    GeomPreprocessor._terminate_process_tree(process)
                else:
                    child_monitor = GeomPreprocessor._wait_for_preprocess_child(
                        tmp_hdf_path=tmp_hdf_path,
                        start_time=start_time,
                        max_wait=max_wait,
                    )
                    if child_monitor["timed_out"] and process.poll() is None:
                        GeomPreprocessor._terminate_process_tree(process)

                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        GeomPreprocessor._terminate_process_tree(process)
            finally:
                if _watchdog:
                    _watchdog.stop()
                if restore_plan_settings and original_plan_text is not None:
                    GeomPreprocessor._restore_plan_file(plan_path, original_plan_text)

            if process is None:
                raise RuntimeError("HEC-RAS process was not started")

            try:
                stdout, stderr = process.communicate(timeout=2)
            except Exception:
                stdout, stderr = b"", b""

            if stdout:
                logger.debug(stdout.decode("utf-8", errors="replace"))
            if stderr:
                logger.debug(stderr.decode("utf-8", errors="replace"))

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
            if process.returncode not in (0, None) and not signal_detected:
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
        """Return the flow type recorded in plan_df when available."""
        try:
            if getattr(ras_obj, "plan_df", None) is None or ras_obj.plan_df.empty:
                return "Unknown"
            matching = ras_obj.plan_df[
                ras_obj.plan_df["plan_number"].apply(RasUtils.normalize_ras_number)
                == plan_num
            ]
            if matching.empty:
                return "Unknown"
            if "flow_type" in matching.columns:
                return str(matching.iloc[0].get("flow_type") or "Unknown")
            if "unsteady_number" in matching.columns:
                return "Unsteady" if matching.iloc[0].get("unsteady_number") else "Steady"
        except Exception:
            return "Unknown"
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
        plan_path.write_text("".join(updated), encoding="utf-8")

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
        plan_path.write_text("".join(restored), encoding="utf-8")

    @staticmethod
    def _restore_plan_file(plan_path: Path, original_text: str) -> None:
        """Restore the plan file exactly after temporary validation edits."""
        try:
            plan_path.write_text(original_text, encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Could not restore plan file {plan_path}: {exc}")

    @staticmethod
    def _monitor_compute_messages(
        process: subprocess.Popen,
        message_paths: List[Path],
        start_time: float,
        max_wait: int,
        signals: List[str],
        geometry_only_artifacts: Optional[List[Path]] = None,
    ) -> dict:
        """Poll compute-message files until a flow-start signal, exit, or timeout.

        When *geometry_only_artifacts* is provided (geometry_only mode), the
        loop also checks whether preprocessing artifacts have been freshly
        written and stabilized.  Because ``Run UNet=0`` prevents any
        flow-start signal from appearing, artifact stability is the only
        reliable completion indicator in geometry-only mode.
        """
        positions = {path: 0 for path in message_paths}
        signal_detected = None
        signal_patterns = [(signal, signal.lower()) for signal in signals]

        _ARTIFACT_GRACE = 15
        _ARTIFACT_STABLE = 10

        while time.time() - start_time < max_wait:
            for path in message_paths:
                if not path.exists():
                    continue
                try:
                    if path.stat().st_mtime < start_time - 1:
                        continue
                    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                        handle.seek(positions.get(path, 0))
                        chunk = handle.read()
                        positions[path] = handle.tell()
                except OSError:
                    continue

                lower_chunk = chunk.lower()
                for signal, lower_signal in signal_patterns:
                    if lower_signal in lower_chunk:
                        signal_detected = signal
                        return {
                            "signal_detected": signal_detected,
                            "timed_out": False,
                        }

            if (
                geometry_only_artifacts is not None
                and (time.time() - start_time) > _ARTIFACT_GRACE
            ):
                fresh = []
                for artifact in geometry_only_artifacts:
                    try:
                        if (
                            artifact.exists()
                            and artifact.stat().st_size > 0
                            and artifact.stat().st_mtime >= start_time - 1
                        ):
                            fresh.append(artifact)
                    except OSError:
                        pass
                if fresh:
                    try:
                        latest_mtime = max(a.stat().st_mtime for a in fresh)
                        if time.time() - latest_mtime >= _ARTIFACT_STABLE:
                            signal_detected = (
                                "Geometry preprocessing artifacts stable "
                                "(geometry_only mode)"
                            )
                            return {
                                "signal_detected": signal_detected,
                                "timed_out": False,
                            }
                    except OSError:
                        pass

            if process.poll() is not None:
                return {"signal_detected": signal_detected, "timed_out": False}

            time.sleep(0.5)

        return {"signal_detected": signal_detected, "timed_out": True}

    @staticmethod
    def _wait_for_preprocess_child(
        tmp_hdf_path: Path,
        start_time: float,
        max_wait: int,
    ) -> dict[str, Any]:
        """
        Wait for orphaned RasProcess.exe CompletePreProcess work to finish.

        Some HEC-RAS versions return from ``Ras.exe -c`` before the spawned
        ``RasProcess.exe CompletePreProcess`` process finishes writing the
        plan ``*.tmp.hdf``. Without this guard, validation can report failure
        while the geometry preprocessor is still actively running.
        """
        deadline = start_time + max_wait
        saw_child = False
        last_size = None
        stable_since = None
        grace_deadline = min(deadline, time.time() + 5)

        while time.time() < deadline:
            child_pids = GeomPreprocessor._ras_processes_using_path(tmp_hdf_path)
            if child_pids:
                saw_child = True

            tmp_is_fresh = GeomPreprocessor._path_is_fresh(tmp_hdf_path, start_time)
            if not child_pids:
                if not tmp_is_fresh:
                    if not saw_child and time.time() < grace_deadline:
                        time.sleep(1)
                        continue
                    break

                try:
                    current_size = tmp_hdf_path.stat().st_size
                except OSError:
                    break

                if current_size == last_size:
                    stable_since = stable_since or time.time()
                    if time.time() - stable_since >= 2:
                        break
                else:
                    last_size = current_size
                    stable_since = time.time()

            time.sleep(1)

        return {
            "saw_child": saw_child,
            "timed_out": time.time() >= deadline,
            "tmp_hdf_path": tmp_hdf_path
            if GeomPreprocessor._path_is_fresh(tmp_hdf_path, start_time)
            else None,
        }

    @staticmethod
    def _ras_processes_using_path(path: Path) -> List[int]:
        """Return RAS process IDs with command lines referencing a path."""
        try:
            import psutil
        except Exception:
            return []

        path_text = str(path).casefold()
        path_posix = path.as_posix().casefold()
        file_name = path.name.casefold()
        pids = []

        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                info = process.info
                name = str(info.get("name") or "").casefold()
                cmdline = " ".join(str(part) for part in info.get("cmdline") or [])
                command = cmdline.casefold()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

            if "ras" not in name and "ras" not in command:
                continue
            if (
                path_text in command
                or path_posix in command
                or ("completepreprocess" in command and file_name in command)
            ):
                pids.append(int(info["pid"]))

        return pids

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> None:
        """Terminate a process and its children."""
        try:
            import psutil

            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            parent.kill()
            process.wait(timeout=10)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=10)
            except Exception:
                pass

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

    # Geometry-preprocessor datasets written INTO the .g##.hdf during
    # preprocessing. Deleting these (while preserving the base mesh topology and
    # the land-cover association) forces HEC-RAS to re-derive per-cell Manning's
    # n from the current land-cover source on the next compute.
    _GEOMPRE_HDF_ABSOLUTE_PATHS = (
        "Geometry/GeomPreprocess",
        "Geometry/Cross Sections/Property Tables",
        "Geometry/Cross Sections/Flow Distribution",
        "Geometry/Boundary Condition Lines/External Faces",
        "Geometry/Storage Areas/Polygon Area",
        "Geometry/Land Cover (Manning's n)/External Faces",
        "Geometry/Land Cover (Manning's n)/Internal Cells",
        "Geometry/Land Cover (Manning's n)/Internal Faces",
    )
    # Per-2D-flow-area preprocessor property tables (deleted under each area group).
    _GEOMPRE_HDF_AREA_DATASETS = (
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

    @staticmethod
    @log_call
    def clear_geompre_hdf(geom_hdf_path: Union[str, Path]) -> List[str]:
        """
        Delete geometry-preprocessor datasets from a ``.g##.hdf`` in place.

        Removes the cached preprocessor output (the ``Geometry/GeomPreprocess``
        group, the 2D cell/face property tables including ``Cells Center
        Manning's n``, the land-cover per-cell/face assignments, and the 1D
        cross-section property tables) while PRESERVING the base mesh topology
        and the land-cover association (``Calibration Table``, ``Polygon
        Points``). On the next compute, HEC-RAS re-derives per-cell Manning's n
        from the current land-cover source, so edits to the sidecar ``Variables``
        or the plain-text ``LCMann Table`` actually propagate to the solver.

        This is the missing piece for 2D land-cover preprocessing: ``.c##``
        files do not hold the 2D per-cell n (it lives in the ``.g##.hdf``).
        ``force_geompre`` uses this same in-place clearing and preserves the
        land-cover association. It additionally bypasses the smart results skip
        and requests an immediate ``RasProcess.exe CompleteGeometry`` rebuild,
        which is useful when only a sidecar changed and the ``.g##`` mtime did not.

        Args:
            geom_hdf_path: Path to a geometry HDF (``<project>.g##.hdf``).

        Returns:
            List[str]: HDF paths that were deleted (empty if none/no file).
        """
        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            return []
        try:
            import h5py
        except ImportError:
            logger.warning(
                "h5py not available; cannot clear in-HDF geometry preprocessing "
                f"for {geom_hdf_path.name}"
            )
            return []

        deleted: List[str] = []
        with h5py.File(geom_hdf_path, "a") as hdf:
            for path in GeomPreprocessor._GEOMPRE_HDF_ABSOLUTE_PATHS:
                if path in hdf:
                    del hdf[path]
                    deleted.append(path)
            areas_group = "Geometry/2D Flow Areas"
            if areas_group in hdf:
                for area_name in list(hdf[areas_group].keys()):
                    area_obj = hdf[areas_group][area_name]
                    if not isinstance(area_obj, h5py.Group):
                        continue
                    for dataset in GeomPreprocessor._GEOMPRE_HDF_AREA_DATASETS:
                        full = f"{areas_group}/{area_name}/{dataset}"
                        if full in hdf:
                            del hdf[full]
                            deleted.append(full)

        if deleted:
            logger.info(
                f"Cleared {len(deleted)} geometry-preprocessor path(s) from "
                f"{geom_hdf_path.name}"
            )
        return deleted

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

        This deletes the `.c##` geometry preprocessor file AND clears the geometry-preprocessor
        tables baked into the `.g##.hdf` (incl. the 2D per-cell `Cells Center Manning's n` and
        property tables) in place via `clear_geompre_hdf()`, while preserving the mesh topology and
        the land-cover association. This ensures a 2D roughness / geometry edit actually propagates
        (the `.c##` file alone does not hold the per-cell n, so clearing it is not sufficient).

        Limitations/Future Work:
        - It does not clear the IB (internal boundary) tables.

        Parameters:
            plan_files (Union[str, Path, List[Union[str, Path]]], optional):
                Full path(s) to the HEC-RAS plan file(s) (.p*).
                If None, clears all plan files in the project directory.
            ras_object: An optional RAS object instance.

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

        def _resolve_geom_hdf(plan_path: Path, ras_obj) -> Optional[Path]:
            """Resolve the geometry HDF (<project>.g##.hdf) for a plan."""
            plan_match = re.search(r"\.p(\d+)$", plan_path.name, re.IGNORECASE)
            plan_number = RasUtils.normalize_ras_number(plan_match.group(1)) if plan_match else None
            geom_number = None
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
            if geom_number is None:
                return None
            return plan_path.with_name(f"{plan_path.stem}.g{geom_number}.hdf")

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

            # Also clear the geometry-preprocessor tables baked into the .g##.hdf
            # (notably the 2D per-cell "Cells Center Manning's n" + property
            # tables). The .c## file does NOT hold these, so without this step a
            # 2D roughness/geometry edit silently fails to propagate because the
            # cached per-cell n is reused. Base mesh + land-cover association are
            # preserved, so HEC-RAS re-derives per-cell n on the next compute.
            geom_hdf = _resolve_geom_hdf(plan_path, ras_obj)
            if geom_hdf is not None and geom_hdf.exists():
                if GeomPreprocessor.clear_geompre_hdf(geom_hdf):
                    cleared_any = True

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
