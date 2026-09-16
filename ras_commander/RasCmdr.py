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
- compute_parallel()
- compute_test_mode()
        
        
        
"""
import os
import subprocess
import shutil
import shlex
from collections import defaultdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from .RasPrj import ras, RasPrj, init_ras_project, get_ras_exe
from .RasPlan import RasPlan
from .RasGeo import RasGeo
from .RasUtils import RasUtils
import logging
import time
import queue
from threading import Thread, Lock
from typing import Union, List, Optional, Dict, Any
from pathlib import Path
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Thread
from itertools import cycle
from ras_commander.RasPrj import RasPrj  # Ensure RasPrj is imported
from threading import Lock, Thread, current_thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from typing import Union, List, Optional, Dict, Any
from numbers import Number
from .LoggingConfig import get_logger
from .Decorators import log_call
from .RasBco import BcoMonitor
from .ComputeResults import ComputeResult, ComputeParallelResult
import pandas as pd
from typing import Callable, Mapping

logger = get_logger(__name__)

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
    def _prepare_linux_unsteady_input(tmp_hdf: Union[str, Path]) -> Dict[str, Any]:
        """Remove stale solver results from a preprocessed Linux input HDF."""
        import h5py

        path = Path(tmp_hdf)
        with h5py.File(path, "r+") as hdf:
            results_present_before = "Results" in hdf
            if results_present_before:
                del hdf["Results"]
                hdf.flush()
            results_present_after = "Results" in hdf
        return {
            "path": str(path),
            "results_group_present_before": results_present_before,
            "results_group_present_after": results_present_after,
            "results_group_removed": bool(
                results_present_before and not results_present_after
            ),
        }

    @staticmethod
    def _inspect_linux_unsteady_completion(
        tmp_hdf: Union[str, Path],
        log_path: Union[str, Path],
    ) -> Dict[str, Any]:
        """Require native-Linux log and HDF content before accepting exit zero."""
        import h5py

        hdf_path = Path(tmp_hdf)
        solver_log = Path(log_path)
        text = solver_log.read_text(errors="replace") if solver_log.exists() else ""
        fatal_signatures = tuple(
            signature
            for signature in (
                "HDF_ERROR",
                "Segmentation fault",
                "forrtl: severe",
                "The output must not already exist",
            )
            if signature.casefold() in text.casefold()
        )
        completion_signal = "Finished Unsteady Flow Simulation"
        completion_signal_present = completion_signal in text
        results_unsteady_present = False
        hdf_error = None
        try:
            with h5py.File(hdf_path, "r") as hdf:
                results_unsteady_present = "Results/Unsteady" in hdf
        except (OSError, ValueError) as exc:
            hdf_error = str(exc)
        return {
            "completion_signal": completion_signal,
            "completion_signal_present": completion_signal_present,
            "results_unsteady_present": results_unsteady_present,
            "fatal_signatures": list(fatal_signatures),
            "hdf_error": hdf_error,
            "passed": bool(
                completion_signal_present
                and results_unsteady_present
                and not fatal_signatures
                and hdf_error is None
            ),
        }

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

        logger.info(
            "Filtered plans to execute: "
            f"{list(filtered_plan_entries['plan_number'])}"
        )
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
    def _copy_worker_artifact(source_path: Path, dest_path: Path) -> bool:
        """
        Copy a worker artifact unless the destination is already newer.
        """
        if not source_path.exists() or not source_path.is_file():
            return False

        if dest_path.exists():
            source_stat = source_path.stat()
            dest_stat = dest_path.stat()

            if dest_stat.st_mtime > source_stat.st_mtime:
                logger.debug(
                    "Skipping older worker artifact %s because destination %s is newer",
                    source_path,
                    dest_path,
                )
                return False

            if (
                dest_stat.st_mtime == source_stat.st_mtime
                and dest_stat.st_size == source_stat.st_size
            ):
                logger.debug(
                    "Skipping unchanged worker artifact %s",
                    source_path,
                )
                return False

            dest_path.unlink()

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)
        return True

    @staticmethod
    def _verify_completion(hdf_path: Path, check_errors: bool = True) -> bool:
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

        Returns:
            bool: True if verification passed
        """
        if not hdf_path.exists():
            logger.debug(f"HDF file does not exist: {hdf_path}")
            return False

        try:
            import h5py
            from .hdf.HdfResultsPlan import HdfResultsPlan

            compute_msgs = HdfResultsPlan.get_compute_messages_hdf_only(hdf_path)

            if not compute_msgs or 'Complete Process' not in compute_msgs:
                logger.debug(f"Verification failed: 'Complete Process' not found in {hdf_path.name}")
                return False

            # Structural check: /Plan Data/Plan Information must exist
            with h5py.File(str(hdf_path), 'r') as hdf:
                if hdf.get('Plan Data/Plan Information') is None:
                    logger.warning(f"Verification failed: '/Plan Data/Plan Information' missing in {hdf_path.name} (partial HDF)")
                    return False

            if check_errors:
                from .results.ResultsParser import ResultsParser
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
    def _kill_process_tree(pid: int) -> None:
        """
        Forcibly terminate a process and all of its descendants.

        Used to enforce ``timeout_sec`` on Windows, where ``shell=True`` spawns
        ``cmd.exe`` -> ``Ras.exe`` -> ``RasUnsteady.exe``. ``taskkill /T`` walks
        the tree from the given PID, so only THIS run's processes are killed
        (safe when other workers are computing in parallel). Falls back to a
        plain ``psutil``/``os`` kill on non-Windows platforms.
        """
        import sys as _sys
        try:
            if _sys.platform.startswith("win"):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=120,
                )
            else:
                import signal as _signal
                os.killpg(os.getpgid(pid), _signal.SIGKILL)
        except Exception as _e:
            logger.warning(f"Failed to kill process tree for PID {pid}: {_e}")

    @staticmethod
    def _communicate_with_watchdog(
        process: subprocess.Popen,
        watchdog,
        timeout_sec: Optional[int],
        plan_number,
    ):
        """Drain a process while polling modal supervision and wall timeout."""
        deadline = (
            time.monotonic() + timeout_sec if timeout_sec is not None else None
        )
        while True:
            blocked_reason = watchdog.blocked_reason if watchdog else None
            if blocked_reason:
                RasCmdr._kill_process_tree(process.pid)
                try:
                    process.communicate(timeout=5)
                except Exception:
                    pass
                raise RuntimeError(blocked_reason)

            wait_slice = 0.25
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    RasCmdr._kill_process_tree(process.pid)
                    try:
                        process.communicate(timeout=5)
                    except Exception:
                        pass
                    blocked_reason = watchdog.blocked_reason if watchdog else None
                    if blocked_reason:
                        raise RuntimeError(blocked_reason)
                    raise RuntimeError(
                        f"Plan {plan_number}: HEC-RAS execution exceeded "
                        f"timeout_sec={timeout_sec}s; process tree killed"
                    )
                wait_slice = min(wait_slice, remaining)

            try:
                return process.communicate(timeout=wait_slice)
            except subprocess.TimeoutExpired:
                continue

    @staticmethod
    def _compute_process_cwd(project_folder, ras_exe_path) -> str:
        """Return a CreateProcess-safe working directory for a computation.

        Windows accepts extended-length (``\\\\?\\``) paths for most file I/O,
        but ``CreateProcess``/Wine can reject such a path when it is supplied as
        the child working directory (``WinError 123``).  The project and plan
        remain explicit command-line arguments, so the HEC-RAS installation
        directory is a safe working directory for this narrow case.
        """
        project_text = str(project_folder)
        if project_text.startswith("\\\\?\\") or len(project_text) >= 260:
            return str(Path(ras_exe_path).parent)
        return project_text

    @staticmethod
    def _compute_process_invocation(ras_exe_path, project_path, plan_path):
        """Build an invocation that does not route long paths through cmd.exe."""
        original_project_text = str(project_path)
        original_plan_text = str(plan_path)
        project_text = RasCmdr._windows_product_path(project_path)
        plan_text = RasCmdr._windows_product_path(plan_path)
        if (
            original_project_text.startswith("\\\\?\\")
            or original_plan_text.startswith("\\\\?\\")
            or max(len(original_project_text), len(original_plan_text)) >= 260
        ):
            return [str(ras_exe_path), "-c", project_text, plan_text], False
        return (
            f'"{ras_exe_path}" -c "{project_text}" "{plan_text}"',
            True,
        )

    @staticmethod
    def _windows_product_path(path) -> str:
        """Return a short Windows alias for a long existing product input.

        Python file I/O can use extended-length paths, while legacy Windows
        products may reject the ``\\\\?\\`` form.  ``GetShortPathNameW`` keeps
        the artifact in place and supplies the compatible alias expected by
        those products.  If the platform cannot supply an alias, the original
        path is returned so the caller receives the vendor failure unchanged.
        """
        text = str(path)
        if os.name != "nt" or (
            not text.startswith("\\\\?\\") and len(text) < 260
        ):
            return text
        try:
            import ctypes

            function = ctypes.windll.kernel32.GetShortPathNameW
            required = int(function(text, None, 0))
            if required <= 0:
                return text
            buffer = ctypes.create_unicode_buffer(required)
            written = int(function(text, buffer, required))
            if written <= 0 or written >= required or not buffer.value:
                return text
            return buffer.value
        except (AttributeError, OSError, ValueError):
            return text

    @staticmethod
    def _define_windows_project_drive(project_folder):
        """Map a free drive letter to a project folder for legacy products."""
        if os.name != "nt":
            return None
        text = str(project_folder)
        if text.startswith("\\\\?\\UNC\\"):
            target = "\\??\\UNC\\" + text[8:]
        elif text.startswith("\\\\?\\"):
            target = "\\??\\" + text[4:]
        else:
            target = "\\??\\" + text
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            logical_drives = int(kernel32.GetLogicalDrives())
            for letter in "QPONMLKJIHGFED":
                bit = 1 << (ord(letter) - ord("A"))
                if logical_drives & bit:
                    continue
                device = f"{letter}:"
                if kernel32.DefineDosDeviceW(0x00000001, device, target):
                    logger.info(
                        "Mapped a temporary Windows drive for long-path "
                        "HEC-RAS product execution"
                    )
                    return {
                        "kind": "drive",
                        "device": device,
                        "target": target,
                    }
        except (AttributeError, OSError, ValueError):
            return None
        return None

    @staticmethod
    def _remove_windows_project_drive(mapping) -> None:
        if not mapping or os.name != "nt":
            return
        if mapping.get("kind") == "symlink":
            alias = Path(mapping["path"])
            try:
                alias.unlink(missing_ok=True)
                try:
                    alias.parent.rmdir()
                except OSError:
                    pass
            except OSError:
                logger.warning("Could not remove temporary long-path symlink")
            return
        try:
            import ctypes

            removed = ctypes.windll.kernel32.DefineDosDeviceW(
                0x00000001 | 0x00000002 | 0x00000004,
                mapping["device"],
                mapping["target"],
            )
            if not removed:
                ctypes.windll.kernel32.DefineDosDeviceW(
                    0x00000002,
                    mapping["device"],
                    None,
                )
        except (AttributeError, OSError, ValueError):
            logger.warning("Could not remove temporary long-path drive mapping")

    @staticmethod
    def _define_windows_project_symlink(project_folder):
        """Create a short directory alias when a drive mapping is unavailable."""
        if os.name != "nt":
            return None
        base = Path(r"C:\ras-qualification-links")
        alias = base / f"rasq-{os.getpid()}-{time.time_ns()}"
        try:
            base.mkdir(parents=True, exist_ok=True)
            os.symlink(
                str(project_folder),
                str(alias),
                target_is_directory=True,
            )
            if alias.is_dir():
                logger.info(
                    "Created a temporary Windows directory alias for long-path "
                    "HEC-RAS product execution"
                )
                return {"kind": "symlink", "path": str(alias)}
        except OSError:
            pass
        try:
            alias.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    @staticmethod
    def _prepare_windows_product_paths(project_folder, project_path, plan_path):
        """Return HEC-RAS-compatible paths plus any drive mapping to clean up."""
        project_text = str(project_path)
        plan_text = str(plan_path)
        project_alias = RasCmdr._windows_product_path(project_path)
        plan_alias = RasCmdr._windows_product_path(plan_path)
        aliases_usable = all(
            not value.startswith("\\\\?\\") and len(value) < 260
            for value in (project_alias, plan_alias)
        )
        originals_long = any(
            value.startswith("\\\\?\\") or len(value) >= 260
            for value in (project_text, plan_text)
        )
        if not originals_long or aliases_usable:
            return project_alias, plan_alias, None

        configured_drive = os.environ.get(
            "RAS_COMMANDER_LONG_PATH_ROOT_DRIVE", ""
        ).strip().rstrip("\\")
        configured_root = os.environ.get(
            "RAS_COMMANDER_LONG_PATH_ROOT", ""
        ).strip().rstrip("\\")
        folder_text = str(project_folder)
        if folder_text.startswith("\\\\?\\"):
            folder_text = folder_text[4:]
        if configured_drive and configured_root:
            root_casefold = configured_root.casefold()
            folder_casefold = folder_text.casefold()
            if folder_casefold == root_casefold:
                relative_folder = ""
            elif folder_casefold.startswith(root_casefold + "\\"):
                relative_folder = folder_text[len(configured_root) + 1 :]
            else:
                relative_folder = None
            if relative_folder is not None:
                alias_root = configured_drive + "\\"
                if relative_folder:
                    alias_root += relative_folder.rstrip("\\") + "\\"
                mapped_project = alias_root + Path(project_text).name
                mapped_plan = alias_root + Path(plan_text).name
                if (
                    len(mapped_project) < 260
                    and len(mapped_plan) < 260
                    and Path(mapped_project).is_file()
                    and Path(mapped_plan).is_file()
                ):
                    logger.info(
                        "Using the isolated Wine long-path drive for HEC-RAS "
                        "product execution"
                    )
                    return mapped_project, mapped_plan, None

        mapping = RasCmdr._define_windows_project_drive(project_folder)
        if mapping:
            root = mapping["device"] + "\\"
            mapped_project = root + Path(project_text).name
            mapped_plan = root + Path(plan_text).name
        else:
            mapped_project = mapped_plan = ""
        if mapping and (
            not Path(mapped_project).is_file() or not Path(mapped_plan).is_file()
        ):
            RasCmdr._remove_windows_project_drive(mapping)
            mapping = None

        if not mapping:
            mapping = RasCmdr._define_windows_project_symlink(project_folder)
            if mapping:
                root = mapping["path"] + "\\"
                mapped_project = root + Path(project_text).name
                mapped_plan = root + Path(plan_text).name

        if not mapping or (
            not Path(mapped_project).is_file() or not Path(mapped_plan).is_file()
        ):
            RasCmdr._remove_windows_project_drive(mapping)
            raise RuntimeError(
                "Temporary Windows path alias did not resolve the long-path "
                "HEC-RAS project and plan files"
            )
        return mapped_project, mapped_plan, mapping

    @staticmethod
    def _create_long_path_execution_shadow(project_folder, ras_exe_path):
        """Clone a long Windows project to a short, task-private execution path."""
        source = Path(project_folder)
        source_text = str(source)
        if os.name != "nt" or not (
            source_text.startswith("\\\\?\\") or len(source_text) >= 260
        ):
            return None, None
        root = Path(r"C:\ras-qualification-execution")
        shadow_parent = root / f"rasq-{os.getpid()}-{time.time_ns()}"
        shadow = shadow_parent / source.name

        def ignore_runtime_files(_directory, names):
            ignored = set(RasUtils.ignore_windows_reserved(_directory, names))
            if ".ras-commander-project.lock" in names:
                ignored.add(".ras-commander-project.lock")
            return sorted(ignored)

        shadow_parent.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source, shadow, ignore=ignore_runtime_files)
        compute_ras = RasPrj()
        compute_ras.initialize(shadow, ras_exe_path)
        details = {
            "mode": "long_path_execution_shadow",
            "source_project_folder": source_text,
            "source_path_length": len(source_text),
            "shadow_project_folder": str(shadow),
            "shadow_path_length": len(str(shadow)),
            "initial_file_count": sum(1 for path in shadow.rglob("*") if path.is_file()),
            "synchronized": False,
            "shadow_removed": False,
        }
        logger.info(
            "Created a task-private short execution shadow for a long-path "
            "HEC-RAS project"
        )
        return compute_ras, details

    @staticmethod
    def _synchronize_long_path_execution_shadow(details) -> Dict[str, Any]:
        """Copy shadow outputs back to the accepted long-path project and remove it."""
        if not details:
            return {}
        source = Path(details["source_project_folder"])
        shadow = Path(details["shadow_project_folder"])
        copied = 0
        if shadow.is_dir():
            for path in sorted(shadow.rglob("*")):
                relative = path.relative_to(shadow)
                if relative.name == ".ras-commander-project.lock":
                    continue
                destination = RasUtils.windows_extended_path(source / relative)
                if path.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif path.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)
                    copied += 1
        shadow_parent = shadow.parent
        removal_error = None
        for delay in (0.0, 0.5, 1.0, 2.0, 4.0, 8.0):
            if not shadow_parent.exists():
                break
            if delay:
                time.sleep(delay)
            try:
                shutil.rmtree(shadow_parent)
                removal_error = None
                break
            except OSError as exc:
                removal_error = exc
                try:
                    import gc

                    gc.collect()
                except Exception:
                    pass
        if shadow_parent.exists() and removal_error is not None:
            raise removal_error
        details.update(
            {
                "synchronized": True,
                "synchronized_file_count": copied,
                "shadow_removed": not shadow_parent.exists(),
            }
        )
        logger.info(
            "Synchronized HEC-RAS outputs to the long-path project and removed "
            "its execution shadow"
        )
        return details

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
        timeout_sec: Optional[int] = None,
        process_environment: Optional[Mapping[str, Any]] = None,
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
            force_geompre (bool, optional): Force full geometry reprocessing (clears both .g##.hdf AND .c## files).
                Defaults to False. Use when geometry HDF needs complete regeneration.
            force_rerun (bool, optional): Force execution even if results are current. Defaults to False.
                When False (default), checks file modification times and skips if results are current.
                When True, always executes regardless of result currency.
            num_cores (int, optional): Number of cores to use for the plan execution.
                If None, the current setting in the plan file is not changed.
                Generally, 2-4 cores provides good performance for most models.
            overwrite_dest (bool, optional): If True, overwrite the destination folder if it exists. Defaults to False.
                Set to True to replace an existing destination folder with the same name.
            skip_existing (bool, optional): If True, skip computation if HDF results file already exists
                and contains 'Complete Process' in compute messages. Defaults to False.
                Useful for resuming interrupted batch runs or incremental workflows.
            verify (bool, optional): If True, verify computation completed successfully by checking
                for 'Complete Process' in compute messages after execution. Defaults to False.
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
            process_environment (Mapping[str, Any], optional): Environment variables
                merged into the child HEC-RAS process only. This is intended for
                controlled runtime compatibility settings such as OpenMP behavior;
                the parent Python environment is not mutated.

        Returns:
            ComputeResult: Result object with ``success`` bool,
                ``results_df_row`` (pd.Series or None), and an optional
                structured ``error`` diagnostic.
                Backward compatible with bool: ``if RasCmdr.compute_plan("01"):`` still works.
                Access execution metrics via ``result.results_df_row`` (e.g., runtime, volume accounting).
                ``results_df_row`` is None when dest_folder is used, execution fails, or extraction errors.
                When skip_existing=True and results exist, returns ComputeResult(success=True).

        Failure handling:
            Operational failures are returned as ``ComputeResult(success=False,
            error=...)``. ``BaseException`` subclasses such as
            ``KeyboardInterrupt`` still propagate after cleanup.

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
            - The verify parameter checks for 'Complete Process' in HDF compute messages.
        """
        _success = False
        _results_df_row = None
        _error = None
        _ras_obj = None
        _did_execute = False  # Track if we actually ran HEC-RAS (vs skip/early exit)
        _watchdog = None
        _product_drive_mapping = None
        _long_path_shadow = None
        _execution_details: Dict[str, Any] = {}
        try:
            ras_obj = ras_object if ras_object is not None else ras
            _ras_obj = ras_obj
            logger.info(f"Using ras_object with project folder: {ras_obj.project_folder}")
            ras_obj.check_initialized()

            if dest_folder is not None:
                dest_folder = Path(ras_obj.project_folder).parent / dest_folder if isinstance(dest_folder, str) else Path(dest_folder)

                if dest_folder.exists():
                    if overwrite_dest:
                        shutil.rmtree(dest_folder)
                        logger.info(f"Destination folder '{dest_folder}' exists. Overwriting as per overwrite_dest=True.")
                    elif any(dest_folder.iterdir()):
                        error_msg = f"Destination folder '{dest_folder}' exists and is not empty. Use overwrite_dest=True to overwrite."
                        logger.error(error_msg)
                        raise ValueError(error_msg)

                dest_folder.mkdir(parents=True, exist_ok=True)
                shutil.copytree(ras_obj.project_folder, dest_folder, dirs_exist_ok=True, ignore=RasUtils.ignore_windows_reserved)
                logger.info(f"Copied project folder to destination: {dest_folder}")

                compute_ras = RasPrj()
                compute_ras.initialize(dest_folder, ras_obj.ras_exe_path)
                compute_prj_path = compute_ras.prj_file
            else:
                compute_ras = ras_obj
                compute_prj_path = ras_obj.prj_file

            if dest_folder is None:
                shadow_ras, _long_path_shadow = (
                    RasCmdr._create_long_path_execution_shadow(
                        compute_ras.project_folder,
                        compute_ras.ras_exe_path,
                    )
                )
                if shadow_ras is not None:
                    compute_ras = shadow_ras
                    compute_prj_path = compute_ras.prj_file
                    _execution_details.update(_long_path_shadow)

            # Determine the plan path
            compute_plan_path = Path(plan_number) if isinstance(plan_number, (str, Path)) and Path(plan_number).is_file() else RasPlan.get_plan_path(plan_number, compute_ras)

            if not compute_prj_path or not compute_plan_path:
                _error = f"Could not find project file or plan file for plan {plan_number}"
                logger.error(_error)
                _success = False
                return ComputeResult(
                    success=False,
                    results_df_row=None,
                    error=_error,
                )

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

            # Skip existing check - runs regardless of force_rerun (for resume capability)
            if skip_existing:
                hdf_path = RasCmdr._get_hdf_path(plan_number, compute_ras)
                if RasCmdr._verify_completion(hdf_path, check_errors=False):
                    logger.info(f"Skipping plan {plan_number}: HDF results already exist with 'Complete Process'")
                    _success = True
                    return ComputeResult(success=True, results_df_row=None)

            # Smart skip: check file modification times (unless force_rerun or skip_existing)
            # Note: Smart skip is bypassed when skip_existing=True since that provides explicit skip logic
            if not force_rerun and not skip_existing:
                from .RasCurrency import RasCurrency
                is_current, reason = RasCurrency.are_plan_results_current(plan_number, compute_ras)
                if is_current:
                    logger.info(f"Skipping plan {plan_number}: {reason}")
                    _success = True
                    return ComputeResult(success=True, results_df_row=None)
                else:
                    logger.debug(f"Plan {plan_number} needs execution: {reason}")

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
                # Force full geometry reprocessing (clears both .g##.hdf AND .c## files)
                from .RasCurrency import RasCurrency
                try:
                    RasCurrency.clear_geom_hdf(plan_number, compute_ras)
                    RasGeo.clear_geompre_files(compute_plan_path, ras_object=compute_ras)
                    logger.info(f"Force-cleared all geometry preprocessor files for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error force-clearing geometry preprocessor files for plan {plan_number}: {str(e)}")
            elif clear_geompre:
                # Original behavior - only clear .c## files
                try:
                    RasGeo.clear_geompre_files(compute_plan_path, ras_object=compute_ras)
                    logger.info(f"Cleared geometry preprocessor files for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error clearing geometry preprocessor files for plan {plan_number}: {str(e)}")

            # Set the number of cores if specified
            if num_cores is not None:
                try:
                    RasPlan.set_num_cores(compute_plan_path, num_cores=num_cores, ras_object=compute_ras)
                    logger.info(f"Set number of cores to {num_cores} for plan: {plan_number}")
                except Exception as e:
                    logger.error(f"Error setting number of cores for plan {plan_number}: {str(e)}")

            # Callback: preprocessing complete
            if stream_callback and hasattr(stream_callback, 'on_prep_complete'):
                stream_callback.on_prep_complete(str(plan_number))

            # Prepare the command for HEC-RAS execution
            cmd = f'"{compute_ras.ras_exe_path}" -c "{compute_prj_path}" "{compute_plan_path}"'
            product_prj_path, product_plan_path, _product_drive_mapping = (
                RasCmdr._prepare_windows_product_paths(
                    compute_ras.project_folder,
                    compute_prj_path,
                    compute_plan_path,
                )
            )
            process_command, process_shell = RasCmdr._compute_process_invocation(
                compute_ras.ras_exe_path,
                product_prj_path,
                product_plan_path,
            )
            process_cwd = RasCmdr._compute_process_cwd(
                compute_ras.project_folder,
                compute_ras.ras_exe_path,
            )
            if _product_drive_mapping:
                if _product_drive_mapping.get("kind") == "drive":
                    process_cwd = _product_drive_mapping["device"] + "\\"
                else:
                    process_cwd = _product_drive_mapping["path"]
            elif str(product_prj_path) != str(compute_prj_path):
                process_cwd = str(Path(product_prj_path).parent)
            logger.info("Running HEC-RAS from the Command Line:")
            logger.info(f"Running command: {cmd}")

            # Callback: execution start
            if stream_callback and hasattr(stream_callback, 'on_exec_start'):
                stream_callback.on_exec_start(str(plan_number), cmd)

            # Execute the HEC-RAS command
            start_time = time.time()
            try:
                child_environment = None
                if process_environment is not None:
                    if not isinstance(process_environment, Mapping):
                        raise TypeError("process_environment must be a mapping")
                    child_environment = os.environ.copy()
                    for key, value in process_environment.items():
                        key_text = str(key).strip()
                        if not key_text or "=" in key_text or "\x00" in key_text:
                            raise ValueError(
                                f"Invalid process environment variable name: {key!r}"
                            )
                        value_text = str(value)
                        if "\x00" in value_text:
                            raise ValueError(
                                f"Invalid NUL in process environment variable {key_text!r}"
                            )
                        child_environment[key_text] = value_text
                if dialog_watchdog:
                    from .RasDialogWatchdog import DialogWatchdog
                    _watchdog = DialogWatchdog()
                    _watchdog.require_available()

                # Choose execution method based on whether callback is provided
                if stream_callback and bco_monitor:
                    # Use Popen for real-time monitoring
                    process = subprocess.Popen(
                        process_command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=process_cwd,
                        shell=process_shell,
                        env=child_environment,
                    )
                    _did_execute = True
                    if _watchdog:
                        _watchdog.add_pid(process.pid)
                        try:
                            _watchdog.start()
                        except Exception:
                            RasCmdr._kill_process_tree(process.pid)
                            raise

                    # Monitor .bco file until process completes
                    # (BcoMonitor will call on_exec_message callback as messages appear)
                    if _watchdog:
                        bco_monitor.blocking_condition = (
                            lambda: _watchdog.blocked_reason
                        )
                    bco_monitor.monitor_until_signal(process)

                    RasCmdr._communicate_with_watchdog(
                        process,
                        _watchdog,
                        timeout_sec,
                        plan_number,
                    )
                    return_code = process.returncode

                    if _watchdog and _watchdog.blocked_reason:
                        raise RuntimeError(_watchdog.blocked_reason)

                    # Check if subprocess succeeded
                    if return_code != 0:
                        raise subprocess.CalledProcessError(return_code, cmd)

                else:
                    # Retain the launcher PID so modal supervision is scoped to
                    # this run's process tree. Communication is polled in short
                    # intervals even without a wall timeout so a structured
                    # watchdog block cannot hang indefinitely.
                    _proc = subprocess.Popen(
                        process_command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        cwd=process_cwd,
                        shell=process_shell,
                        text=True,
                        env=child_environment,
                    )
                    _did_execute = True
                    if _watchdog:
                        _watchdog.add_pid(_proc.pid)
                        try:
                            _watchdog.start()
                        except Exception:
                            RasCmdr._kill_process_tree(_proc.pid)
                            raise
                    _out, _err = RasCmdr._communicate_with_watchdog(
                        _proc,
                        _watchdog,
                        timeout_sec,
                        plan_number,
                    )
                    if _watchdog and _watchdog.blocked_reason:
                        raise RuntimeError(_watchdog.blocked_reason)
                    if _proc.returncode != 0:
                        raise subprocess.CalledProcessError(
                            _proc.returncode,
                            cmd,
                            _out,
                            _err,
                        )

                end_time = time.time()
                run_time = end_time - start_time
                logger.info(f"HEC-RAS execution completed for plan: {plan_number}")
                logger.info(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")

                # Callback: execution complete
                if stream_callback and hasattr(stream_callback, 'on_exec_complete'):
                    stream_callback.on_exec_complete(str(plan_number), True, run_time)

                # Verify completion if requested
                if verify:
                    hdf_path = RasCmdr._get_hdf_path(plan_number, compute_ras)
                    verified = RasCmdr._verify_completion(hdf_path)

                    # Callback: verification result
                    if stream_callback and hasattr(stream_callback, 'on_verify_result'):
                        stream_callback.on_verify_result(str(plan_number), verified)

                    if verified:
                        logger.info(f"Verification passed for plan {plan_number}")
                        _success = True
                    else:
                        _error = (
                            f"Verification failed for plan {plan_number}: 'Complete Process' not found in compute messages. "
                            f"See: https://ras-commander.readthedocs.io/user-guide/plan-execution/"
                        )
                        logger.error(_error)
                        _success = False
                else:
                    _success = True

            except subprocess.CalledProcessError as e:
                end_time = time.time()
                run_time = end_time - start_time
                logger.error(f"Error running plan: {plan_number}")
                logger.error(f"Error message: {e.output}")
                _error = str(e)
                logger.info(f"Total run time for plan {plan_number}: {run_time:.2f} seconds")

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
            _error = str(e)
            _success = False
        finally:
            if _watchdog:
                _watchdog.stop()
            RasCmdr._remove_windows_project_drive(_product_drive_mapping)
            if _long_path_shadow:
                try:
                    _execution_details.update(
                        RasCmdr._synchronize_long_path_execution_shadow(
                            _long_path_shadow
                        )
                    )
                except Exception as shadow_error:
                    _success = False
                    _error = (
                        "Long-path execution completed but synchronization "
                        f"failed: {shadow_error}"
                    )
                    logger.error(_error)

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

        return ComputeResult(
            success=_success,
            results_df_row=_results_df_row,
            error=_error,
            execution_details=_execution_details,
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
        verify: bool = False,
        timeout_sec: Optional[int] = None
    ) -> 'ComputeParallelResult':
        """
        Execute multiple HEC-RAS plans in parallel using multiple worker instances.

        This method creates separate worker folders for each parallel process, runs plans
        in those folders, and then consolidates results to a final destination folder.
        It's ideal for running independent plans simultaneously to make better use of system resources.

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
            force_geompre (bool): Force full geometry reprocessing (clears both .g##.hdf AND .c## files).
                Defaults to False. Use when geometry HDF needs complete regeneration.
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
            skip_existing (bool): If True, skip computation for plans that already have HDF results
                with 'Complete Process' in compute messages. Defaults to False.
                Skipped plans are marked as successful (True) in results. Checked on source folder.
            verify (bool): If True, verify each plan completed successfully by checking
                for 'Complete Process' in compute messages. Defaults to False.
                Plans that fail verification are marked False in results.

        Returns:
            ComputeParallelResult: Result object backward compatible with Dict[str, bool].
                ``execution_results``: Dict of plan numbers to success booleans.
                ``results_df``: DataFrame with results_df rows for executed plans.
                ``errors``: Per-plan structured diagnostics for failures.
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

            - This function updates the RAS object's dataframes (plan_df, geom_df, etc.) after execution.

            - skip_existing checks the SOURCE folder before creating workers. Plans with existing
              results are not assigned to workers at all.

            - verify is passed through to compute_plan() for each worker execution.
        """
        try:
            ras_obj = ras_object or ras
            ras_obj.check_initialized()

            project_folder = Path(ras_obj.project_folder)

            if dest_folder is not None:
                dest_folder_path = Path(dest_folder)
                if dest_folder_path.exists():
                    if overwrite_dest:
                        shutil.rmtree(dest_folder_path)
                        logger.info(f"Destination folder '{dest_folder_path}' exists. Overwriting as per overwrite_dest=True.")
                    elif any(dest_folder_path.iterdir()):
                        error_msg = f"Destination folder '{dest_folder_path}' exists and is not empty. Use overwrite_dest=True to overwrite."
                        logger.error(error_msg)
                        raise ValueError(error_msg)
                dest_folder_path.mkdir(parents=True, exist_ok=True)
                shutil.copytree(project_folder, dest_folder_path, dirs_exist_ok=True, ignore=RasUtils.ignore_windows_reserved)
                logger.info(f"Copied project folder to destination: {dest_folder_path}")
                project_folder = dest_folder_path

            # Store filtered plan numbers separately to ensure only these are executed
            filtered_plan_entries = RasCmdr._filter_plan_entries(
                ras_obj.plan_df,
                plan_number
            )
            filtered_plan_numbers = list(filtered_plan_entries["plan_number"])

            # Initialize execution_results dict
            execution_results: Dict[str, bool] = {}
            execution_errors: Dict[str, str] = {}

            # Filter out plans with existing results if skip_existing is True
            if skip_existing:
                plans_to_skip = []
                plans_to_compute = []
                for plan_num in filtered_plan_numbers:
                    hdf_path = RasCmdr._get_hdf_path(plan_num, ras_obj)
                    if RasCmdr._verify_completion(hdf_path, check_errors=False):
                        plans_to_skip.append(plan_num)
                        execution_results[plan_num] = True  # Mark as successful (results exist)
                    else:
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
                    errors=execution_errors,
                )

            max_workers = min(max_workers, num_plans)
            logger.info(f"Adjusted max_workers to {max_workers} based on the number of plans to compute: {num_plans}")

            worker_ras_objects = {}
            worker_plan_numbers: Dict[int, List[str]] = defaultdict(list)
            for worker_id in range(1, max_workers + 1):
                worker_folder = project_folder.parent / f"{project_folder.name} [Worker {worker_id}]"
                if worker_folder.exists():
                    shutil.rmtree(worker_folder)
                    logger.info(f"Removed existing worker folder: {worker_folder}")
                shutil.copytree(project_folder, worker_folder, ignore=RasUtils.ignore_windows_reserved)
                logger.info(f"Created worker folder: {worker_folder}")

                try:
                    worker_ras = RasPrj()
                    worker_ras_object = init_ras_project(
                        ras_project_folder=worker_folder,
                        ras_version=ras_obj.ras_exe_path,
                        ras_object=worker_ras
                    )
                    worker_ras_objects[worker_id] = worker_ras_object
                except Exception as e:
                    logger.critical(f"Failed to initialize RAS project for worker {worker_id}: {str(e)}")
                    worker_ras_objects[worker_id] = None

            # Explicitly use the filtered plan numbers for assignments
            worker_cycle = cycle(range(1, max_workers + 1))
            plan_assignments = [(next(worker_cycle), plan_num) for plan_num in filtered_plan_numbers]
            for worker_id, plan_num in plan_assignments:
                worker_plan_numbers[worker_id].append(plan_num)

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
                        verify=verify,
                        timeout_sec=timeout_sec,
                    )
                    future_to_plan[future] = (worker_id, plan_num)

                # Process futures as they complete (not in submission order)
                for future in as_completed(future_to_plan.keys()):
                    worker_id, plan_num = future_to_plan[future]
                    try:
                        compute_result = future.result()
                        # Extract bool from ComputeResult for execution_results dict
                        execution_results[plan_num] = bool(compute_result)
                        if not compute_result and compute_result.error:
                            execution_errors[plan_num] = compute_result.error
                        logger.info(f"Plan {plan_num} executed in worker {worker_id}: {'Successful' if compute_result else 'Failed'}")
                    except Exception as e:
                        execution_results[plan_num] = False
                        execution_errors[plan_num] = str(e)
                        logger.error(f"Plan {plan_num} failed in worker {worker_id}: {str(e)}")

            # Consolidate results: use dest_folder if provided, otherwise back to original folder
            # This eliminates the [Computed] folder anti-pattern - results go directly to original project
            if dest_folder is not None:
                final_dest_folder = dest_folder_path
                final_dest_folder.mkdir(parents=True, exist_ok=True)
                logger.info(f"Consolidating results to destination folder: {final_dest_folder}")
            else:
                final_dest_folder = project_folder
                logger.info(f"Consolidating results back to original project folder: {final_dest_folder}")

            consolidated_artifact_count = 0
            for worker_id, worker_ras in worker_ras_objects.items():
                if worker_ras is None:
                    continue
                worker_folder = Path(worker_ras.project_folder)
                assigned_plan_numbers = worker_plan_numbers.get(worker_id, [])
                try:
                    # First, close any open resources in the worker RAS object
                    worker_ras.close() if hasattr(worker_ras, 'close') else None
                    
                    # Add a small delay to ensure file handles are released
                    time.sleep(1)
                    
                    # Move files with retry mechanism
                    max_retries = 3
                    for retry in range(max_retries):
                        try:
                            for plan_num in assigned_plan_numbers:
                                geometry_number = RasCmdr._get_plan_geometry_number(
                                    filtered_plan_entries,
                                    plan_num
                                )
                                plan_artifacts = RasCmdr._get_worker_plan_artifacts(
                                    worker_folder=worker_folder,
                                    project_name=worker_ras.project_name,
                                    plan_number=plan_num,
                                    geometry_number=geometry_number
                                )
                                for artifact_path in plan_artifacts:
                                    dest_path = final_dest_folder / artifact_path.name
                                    if RasCmdr._copy_worker_artifact(
                                        artifact_path,
                                        dest_path
                                    ):
                                        consolidated_artifact_count += 1
                             
                            # Add another small delay before removal
                            time.sleep(1)
                            
                            # Try to remove the worker folder
                            if worker_folder.exists():
                                shutil.rmtree(worker_folder)
                            break  # If successful, break the retry loop
                            
                        except PermissionError as pe:
                            if retry == max_retries - 1:  # If this was the last retry
                                logger.error(f"Failed to move/remove files after {max_retries} attempts: {str(pe)}")
                                raise
                            time.sleep(2 ** retry)  # Exponential backoff
                            continue
                            
                except Exception as e:
                    logger.error(f"Error moving results from {worker_folder} to {final_dest_folder}: {str(e)}")

            logger.info(
                "Consolidated %s worker artifact(s) to %s",
                consolidated_artifact_count,
                final_dest_folder
            )

            # When dest_folder is used, re-initialize ras_obj from dest_folder
            # This ensures results_df reflects results in the destination folder
            if dest_folder is not None:
                try:
                    ras_obj.initialize(final_dest_folder, ras_obj.ras_exe_path)
                    logger.info(f"Re-initialized ras_object from destination folder: {final_dest_folder}")
                except Exception as e:
                    logger.critical(f"Failed to re-initialize ras_object from destination folder: {str(e)}")

            logger.info("\nExecution Results:")
            for plan_num, success in execution_results.items():
                status = 'Successful' if success else 'Failed'
                logger.info(f"Plan {plan_num}: {status}")

            ras_obj = ras_object or ras
            ras_obj.plan_df = ras_obj.get_plan_entries()
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            ras_obj.update_results_df(plan_numbers=list(execution_results.keys()))

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

            return ComputeParallelResult(
                execution_results=execution_results,
                results_df=_results_df,
                errors=execution_errors,
            )

        except Exception as e:
            logger.critical(f"Error in compute_parallel: {str(e)}")
            return ComputeParallelResult()

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
            force_geompre (bool, optional): Force full geometry reprocessing (clears both .g##.hdf AND .c## files).
                Defaults to False. Use when geometry HDF needs complete regeneration.
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
            skip_existing (bool, optional): If True, skip computation for plans that already have HDF results
                with 'Complete Process' in compute messages. Defaults to False.
                Skipped plans are marked as successful (True) in results. Check happens in test folder.
            verify (bool, optional): If True, verify each plan completed successfully by checking
                for 'Complete Process' in compute messages. Defaults to False.
                Plans that fail verification are marked False in results.

        Returns:
            ComputeParallelResult: Result object backward compatible with Dict[str, bool].
                ``execution_results``: Dict of plan numbers to success booleans.
                ``results_df``: DataFrame with results_df rows for executed plans.
                ``errors``: Per-plan structured diagnostics for failures.
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

            - This function updates the RAS object's dataframes (plan_df, geom_df, etc.) after execution.

            - skip_existing checks the TEST folder after copying. This allows resuming interrupted test runs.

            - verify is passed through to compute_plan() for each plan execution.
        """
        try:
            ras_obj = ras_object or ras
            ras_obj.check_initialized()
            
            logger.info("Starting the compute_test_mode...")
               
            project_folder = Path(ras_obj.project_folder)

            if not project_folder.exists():
                logger.error(f"Project folder '{project_folder}' does not exist.")
                return ComputeParallelResult()

            compute_folder = project_folder.parent / f"{project_folder.name} {dest_folder_suffix}"
            logger.info(f"Creating the test folder: {compute_folder}...")

            if compute_folder.exists():
                if overwrite_dest:
                    shutil.rmtree(compute_folder)
                    logger.info(f"Compute folder '{compute_folder}' exists. Overwriting as per overwrite_dest=True.")
                elif any(compute_folder.iterdir()):
                    error_msg = (
                        f"Compute folder '{compute_folder}' exists and is not empty. "
                        "Use overwrite_dest=True to overwrite."
                    )
                    logger.error(error_msg)
                    raise ValueError(error_msg)

            try:
                shutil.copytree(project_folder, compute_folder, ignore=RasUtils.ignore_windows_reserved)
                logger.info(f"Copied project folder to compute folder: {compute_folder}")
            except Exception as e:
                logger.critical(f"Error occurred while copying project folder: {str(e)}")
                return ComputeParallelResult()

            try:
                compute_ras = RasPrj()
                compute_ras.initialize(compute_folder, ras_obj.ras_exe_path)
                compute_prj_path = compute_ras.prj_file
                logger.info(f"Initialized RAS project in compute folder: {compute_prj_path}")
            except Exception as e:
                logger.critical(f"Error initializing RAS project in compute folder: {str(e)}")
                return ComputeParallelResult()

            if not compute_prj_path:
                logger.error("Project file not found.")
                return ComputeParallelResult()

            logger.info("Getting plan entries...")
            try:
                ras_compute_plan_entries = compute_ras.plan_df
                logger.info("Retrieved plan entries successfully.")
            except Exception as e:
                logger.critical(f"Error retrieving plan entries: {str(e)}")
                return ComputeParallelResult()

            ras_compute_plan_entries = RasCmdr._filter_plan_entries(
                ras_compute_plan_entries,
                plan_number
            )

            execution_results = {}
            execution_errors = {}
            logger.info("Running selected plans sequentially...")
            for _, plan in ras_compute_plan_entries.iterrows():
                current_plan_number = plan["plan_number"]
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
                    if not compute_result and compute_result.error:
                        execution_errors[current_plan_number] = compute_result.error
                    if compute_result:
                        logger.info(f"Successfully computed plan {current_plan_number}")
                    else:
                        logger.error(f"Failed to compute plan {current_plan_number}")
                except Exception as e:
                    execution_results[current_plan_number] = False
                    execution_errors[current_plan_number] = str(e)
                    logger.error(f"Error computing plan {current_plan_number}: {str(e)}")
                finally:
                    end_time = time.time()
                    run_time = end_time - start_time
                    logger.info(f"Total run time for plan {current_plan_number}: {run_time:.2f} seconds")

            logger.info("All selected plans have been executed.")

            # Consolidate HDF results back to original project folder
            # This eliminates the [Test] folder anti-pattern - results go to original project
            logger.info(f"Consolidating HDF results from {compute_folder} back to original project folder...")
            hdf_files_copied = 0
            for hdf_file in compute_folder.glob("*.hdf"):
                dest_path = project_folder / hdf_file.name
                try:
                    if dest_path.exists():
                        dest_path.unlink()
                    shutil.copy2(hdf_file, dest_path)
                    hdf_files_copied += 1
                    logger.debug(f"Copied {hdf_file.name} to original project folder")
                except Exception as e:
                    logger.error(f"Failed to copy {hdf_file.name}: {str(e)}")

            logger.info(f"Consolidated {hdf_files_copied} HDF file(s) to original project folder")

            # Clean up test folder
            try:
                shutil.rmtree(compute_folder)
                logger.info(f"Removed test folder: {compute_folder}")
            except Exception as e:
                logger.warning(f"Failed to remove test folder {compute_folder}: {str(e)}")

            logger.info("compute_test_mode completed.")

            logger.info("\nExecution Results:")
            for plan_num, success in execution_results.items():
                status = 'Successful' if success else 'Failed'
                logger.info(f"Plan {plan_num}: {status}")

            # Refresh DataFrames from original folder - HDF files are now there
            ras_obj.plan_df = ras_obj.get_plan_entries()
            ras_obj.geom_df = ras_obj.get_geom_entries()
            ras_obj.flow_df = ras_obj.get_flow_entries()
            ras_obj.unsteady_df = ras_obj.get_unsteady_entries()
            ras_obj.update_results_df(plan_numbers=list(execution_results.keys()))

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

            return ComputeParallelResult(
                execution_results=execution_results,
                results_df=_results_df,
                errors=execution_errors,
            )

        except Exception as e:
            logger.critical(f"Error in compute_test_mode: {str(e)}")
            return ComputeParallelResult()

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
        process_environment: Optional[Mapping[str, Any]] = None,
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

        Compatible with HEC-RAS Linux compute packages through 7.0.1.
        Auto-detects library subdirectory layout (libs/, libs/mkl/, libs/rhel_8/).

        The Linux RasUnsteady binary uses Fortran I/O conventions that require
        files to be accessible with a base name of "io" (e.g., io.b, io.X).
        This method creates temporary symlinks to satisfy this requirement.

        Args:
            plan_number (Union[str, Number]): Plan number to execute (e.g., "01").
            ras_exe_dir (Union[str, Path]): Directory containing the RasUnsteady
                binary and sibling libs/ directory.
            ras_object: Optional RAS project object. If None, uses global ras.
            timeout_sec (int): Maximum execution time in seconds (default 14400 = 4 hours).
            dos2unix (bool): Convert CRLF→LF in text files before execution (default True).
            num_cores (int, optional): Number of cores. If specified, updates plan file.
            retry (bool): Retry once on failure after retry_delay_sec (default True).
            retry_delay_sec (int): Seconds to wait before retry (default 30).
            process_environment (Mapping[str, Any], optional): Environment
                variables merged into the native solver process. ``LD_LIBRARY_PATH``
                remains controlled by the selected HEC-RAS engine package.

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
            ras_exe = ras_exe_dir / "RasUnsteady"
            if not ras_exe.exists():
                raise FileNotFoundError(
                    f"RasUnsteady binary not found at {ras_exe}. "
                    "Ensure HEC-RAS Linux binaries are installed."
                )

        project_dir = Path(ras_obj.project_folder)
        project_name = ras_obj.project_name

        # Determine geometry number from plan file
        plan_path = RasPlan.get_plan_path(plan_num_str, ras_obj)
        geom_num = "01"  # default
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
            logger.warning(f"Could not read geom number from plan file: {e}")

        # Verify prerequisite files exist
        tmp_hdf = project_dir / f"{project_name}.p{plan_num_str}.tmp.hdf"
        b_file = project_dir / f"{project_name}.b{plan_num_str}"
        x_file = project_dir / f"{project_name}.x{geom_num}"

        missing = []
        if not tmp_hdf.exists():
            missing.append(f".p{plan_num_str}.tmp.hdf")
        if not b_file.exists():
            missing.append(f".b{plan_num_str}")
        if not x_file.exists():
            missing.append(f".x{geom_num}")

        if missing:
            raise FileNotFoundError(
                f"Missing prerequisite files for Linux execution: {', '.join(missing)}. "
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

        # Build LD_LIBRARY_PATH — auto-detect library subdirectories
        # HEC-RAS Linux versions have varying layouts:
        #   6.3.1-6.5: libs/, libs/mkl/
        #   6.6-7.0.1: libs/, libs/mkl/, libs/rhel_8/
        lib_base = ras_exe_dir / "libs"
        if not lib_base.exists():
            lib_base = ras_exe_dir.parent / "libs"
        ld_path_parts = []
        if lib_base.exists():
            ld_path_parts.append(str(lib_base))
            for subdir in sorted(lib_base.iterdir()):
                if subdir.is_dir():
                    ld_path_parts.append(str(subdir))
                    logger.debug(f"Added library path: {subdir}")
        else:
            logger.warning(f"No libs/ directory found near {ras_exe_dir}")
            ld_path_parts.append(str(ras_exe_dir))
        ld_path = ":".join(ld_path_parts)
        logger.info(f"LD_LIBRARY_PATH: {ld_path}")

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

            input_preparation = RasCmdr._prepare_linux_unsteady_input(tmp_hdf)
            logger.info(
                "Prepared native-Linux input %s (stale Results removed=%s)",
                tmp_hdf,
                input_preparation["results_group_removed"],
            )

            # Remove any leftover io.tmp.hdf from previous run
            io_tmp_hdf = project_dir / "io.tmp.hdf"
            if io_tmp_hdf.exists():
                io_tmp_hdf.unlink()

            env = os.environ.copy()
            if process_environment is not None:
                if not isinstance(process_environment, Mapping):
                    raise TypeError("process_environment must be a mapping")
                for key, value in process_environment.items():
                    key_text = str(key).strip()
                    if not key_text or "=" in key_text or "\x00" in key_text:
                        raise ValueError(
                            f"Invalid process environment variable name: {key!r}"
                        )
                    value_text = str(value)
                    if "\x00" in value_text:
                        raise ValueError(
                            f"Invalid NUL in process environment variable {key_text!r}"
                        )
                    env[key_text] = value_text
            env["LD_LIBRARY_PATH"] = ld_path

            log_path = project_dir / f"compute_linux_{plan_num_str}.log"
            success = False
            err_msg = ""

            try:
                start_time = time.time()
                with open(log_path, "w") as log_fh:
                    proc = subprocess.Popen(
                        [str(ras_exe), str(tmp_hdf), f"x{geom_num}"],
                        stdout=log_fh,
                        stderr=subprocess.STDOUT,
                        env=env,
                        cwd=str(project_dir),
                    )
                try:
                    rc = proc.wait(timeout=timeout_sec)
                    end_time = time.time()
                    run_time = end_time - start_time
                    if rc == 0:
                        completion = RasCmdr._inspect_linux_unsteady_completion(
                            tmp_hdf,
                            log_path,
                        )
                        success = completion["passed"] is True
                        if success:
                            logger.info(
                                f"RasUnsteady completed for plan {plan_num_str} "
                                f"in {run_time:.1f}s (exit code 0)"
                            )
                        else:
                            err_msg = (
                                "RasUnsteady exited with code 0 but failed content "
                                f"verification: {completion}"
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

                return ComputeResult(
                    success=True,
                    results_df_row=results_row,
                    execution_details={
                        "linux_input_preparation": input_preparation,
                        "linux_completion": completion,
                        "solver_log": str(log_path),
                    },
                )
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
        project_dir_wsl = RasCmdr._windows_path_to_wsl(project_dir)
        tmp_hdf_wsl = RasCmdr._windows_path_to_wsl(tmp_hdf)
        log_path = project_dir / f"compute_linux_{plan_number}.log"
        log_path_wsl = RasCmdr._windows_path_to_wsl(log_path)

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

        cleanup_script = (
            f"cd {project_q} && "
            "find . -maxdepth 1 -type l -name 'io.*' -delete"
        )

        script = fr"""
set -e
cd {project_q}
find . -maxdepth 1 -type l -name 'io.*' -delete
link_or_copy() {{
    ln -sfn "\$1" "\$2" 2>/dev/null || cp -f "\$1" "\$2"
}}
prefix={project_name_q}.
link_or_copy {shlex.quote(f'{project_name}.b{plan_number}')} io.b
link_or_copy {shlex.quote(f'{project_name}.x{geom_num}')} io.X
link_or_copy {shlex.quote(f'{project_name}.x{geom_num}')} io.x
for f in {project_name_q}.*; do
    [ -e "\$f" ] || continue
    suffix="\${{f#\$prefix}}"
    [ -e "io.\$suffix" ] || link_or_copy "\$f" "io.\$suffix"
done
lib_base=""
if [ -d {ras_exe_dir_q}/libs ]; then
    lib_base={ras_exe_dir_q}/libs
elif [ -d "\$(dirname {ras_exe_dir_q})/libs" ]; then
    lib_base="\$(dirname {ras_exe_dir_q})/libs"
fi
if [ -n "\$lib_base" ]; then
    ld_path="\$lib_base"
    for d in "\$lib_base"/*; do
        if [ -d "\$d" ]; then
            ld_path="\$ld_path:\$d"
        fi
    done
else
    ld_path={ras_exe_dir_q}
fi
LD_LIBRARY_PATH="\$ld_path" {ras_exe_q} {tmp_hdf_q} {geom_arg_q} > {log_path_q} 2>&1
"""

        max_attempts = 2 if retry else 1
        for attempt in range(1, max_attempts + 1):
            logger.info(
                f"WSL Linux execution attempt {attempt}/{max_attempts} for plan {plan_number}"
            )

            # Remove any leftover io.tmp.hdf from previous run
            io_tmp_hdf = project_dir / "io.tmp.hdf"
            if io_tmp_hdf.exists():
                io_tmp_hdf.unlink()

            proc = subprocess.Popen(
                ["wsl", "bash", "-lc", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                logger.error(f"Plan {plan_number}: WSL RasUnsteady timeout after {timeout_sec}s")
                stdout, stderr = "", f"Timeout after {timeout_sec}s"
                rc = -1
            else:
                rc = proc.returncode

            if rc == 0:
                subprocess.run(
                    ["wsl", "bash", "-lc", cleanup_script],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                if tmp_hdf.exists():
                    plan_hdf = RasCmdr._get_hdf_path(plan_number, ras_obj)
                    shutil.move(str(tmp_hdf), str(plan_hdf))
                    logger.debug(f"Renamed {tmp_hdf.name} -> {plan_hdf.name}")

                try:
                    ras_obj.plan_df = ras_obj.get_plan_entries()
                    ras_obj.update_results_df(plan_numbers=[plan_number])
                    mask = ras_obj.results_df['plan_number'] == plan_number
                    results_row = ras_obj.results_df[mask].iloc[0].copy() if mask.any() else None
                except Exception as e:
                    logger.debug(f"Could not extract results_df_row: {e}")
                    results_row = None

                return ComputeResult(success=True, results_df_row=results_row)

            try:
                tail = log_path.read_text(errors='replace')[-800:] if log_path.exists() else ""
            except OSError:
                tail = "(log unreadable)"
            logger.error(
                f"Plan {plan_number}: WSL RasUnsteady exited with code {rc}. "
                f"stdout={stdout.strip()} stderr={stderr.strip()} log tail={tail}"
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
        return ComputeResult(success=False, results_df_row=None)
