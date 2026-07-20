"""
RasPreprocess - Windows preprocessing for Linux HEC-RAS execution.

This module provides a public API for Phase 1 (Windows preprocessing) of the
two-phase Linux execution workflow. It automates running HEC-RAS on Windows
with early termination to generate the prerequisite files needed by the Linux
RasUnsteady binary.

Attribution: Core preprocessing logic (BCO monitoring, process tree termination)
derived from TECH WARMS Dam Break Dashboard by CLB Engineering Corporation.
Adapted to ras-commander static class conventions.

Windows preprocessing is required for ALL HEC-RAS Linux versions (6.3.1+).
The Linux binaries cannot produce the .tmp.hdf or .b## files needed to begin
execution. This module automates the Windows-side preprocessing step.

Classes:
    RasPreprocess - Static class for Windows preprocessing operations.
"""

import hashlib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Union

from numbers import Number

from .ComputeResults import GeometryPreprocessResult, PreprocessResult
from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasBco import BcoMonitor
from .RasPlan import RasPlan
from .RasPrj import ras
from ._legal_dialogs import (
    TCU_BLOCKING_ERROR,
    TCU_DIALOG_TITLE,
    legal_dialog_blocking_reason,
)

logger = get_logger(__name__)


class RasPreprocess:
    """
    Static class for Windows preprocessing of HEC-RAS plans for Linux execution.

    Automates Phase 1 of the two-phase Linux execution workflow:
    1. Launches HEC-RAS on Windows
    2. Monitors the .bco log for "Starting Unsteady Flow Computations"
    3. Terminates HEC-RAS at that point (preprocessing complete)
    4. Verifies .tmp.hdf, .b##, .x## files were generated

    All methods are static — do not instantiate this class.

    Example:
        >>> from ras_commander import RasPreprocess, init_ras_project
        >>> init_ras_project("/path/to/project", "7.0")
        >>> result = RasPreprocess.preprocess_plan("01")
        >>> if result:
        ...     print(f"Ready for Linux in {result.elapsed_seconds:.1f}s")
    """

    _TCU_DIALOG_TITLE = TCU_DIALOG_TITLE
    _TCU_BLOCKING_ERROR = TCU_BLOCKING_ERROR
    _TCU_SUPERVISION_ERROR = (
        "HEC-RAS legal-dialog supervision could not establish the launched "
        "process tree. ras-commander refused to continue without a scoped "
        "first-run TCU check."
    )

    @staticmethod
    @log_call
    def preprocess_plan(
        plan_number: Union[str, Number],
        ras_object=None,
        max_wait: int = 300,
        clear_existing: bool = True,
        fix_line_endings: bool = True,
    ) -> PreprocessResult:
        """
        Preprocess a plan on Windows for Linux execution.

        Runs HEC-RAS with early termination to generate .tmp.hdf, .b##, and .x##
        files required by the Linux RasUnsteady binary. The process is killed when
        the .bco log indicates preprocessing is complete ("Starting Unsteady Flow
        Computations" signal).

        Args:
            plan_number: Plan number to preprocess (e.g., "01", 1).
            ras_object: Optional RasPrj instance. If None, uses global ras.
            max_wait: Maximum seconds to wait for preprocessing (default 300).
            clear_existing: Delete stale preprocessing files before running (default True).
            fix_line_endings: Convert .x file CRLF to LF for Linux (default True).

        Returns:
            PreprocessResult: Result with success flag, file paths, and timing.
                Bool-compatible: ``if preprocess_plan("01"):`` works.

        Raises:
            No exceptions raised — errors are captured in PreprocessResult.error.

        Example:
            >>> result = RasPreprocess.preprocess_plan("01")
            >>> if result:
            ...     print(f"tmp.hdf: {result.tmp_hdf_path}")
            ...     print(f".b file: {result.b_file_path}")
            ...     print(f".x file: {result.x_file_path}")
        """
        start_time = time.time()
        ras_obj = ras_object if ras_object is not None else ras

        # Normalize plan number
        if isinstance(plan_number, Number):
            plan_num = f"{int(plan_number):02d}"
        else:
            plan_num = str(plan_number).zfill(2)

        try:
            ras_obj.check_initialized()
        except Exception as e:
            return PreprocessResult(
                success=False, plan_number=plan_num,
                error=f"Project not initialized: {e}",
                elapsed_seconds=time.time() - start_time,
            )

        project_folder = Path(ras_obj.project_folder)
        project_name = ras_obj.project_name

        # Get geometry number from plan_df (DataFrame-first), fallback to file parsing
        geometry_number = None
        try:
            plan_row = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == plan_num]
            if not plan_row.empty and 'Geom File' in plan_row.columns:
                geom_ref = str(plan_row['Geom File'].iloc[0])
                m = re.search(r'(\d+)', geom_ref)
                if m:
                    geometry_number = m.group(1)
        except Exception:
            pass

        if geometry_number is None:
            plan_path = RasPlan.get_plan_path(plan_num, ras_obj)
            if plan_path:
                geometry_number = RasPreprocess._extract_geometry_number(Path(plan_path))
            if geometry_number is None:
                return PreprocessResult(
                    success=False, plan_number=plan_num,
                    error=f"Could not determine geometry number for plan {plan_num}",
                    elapsed_seconds=time.time() - start_time,
                )

        logger.debug(f"Plan {plan_num} uses geometry g{geometry_number}")

        # Build file paths
        tmp_hdf = project_folder / f"{project_name}.p{plan_num}.tmp.hdf"
        hdf_file = project_folder / f"{project_name}.p{plan_num}.hdf"
        b_file = project_folder / f"{project_name}.b{plan_num}"
        x_file = project_folder / f"{project_name}.x{geometry_number}"
        plan_file = project_folder / f"{project_name}.p{plan_num}"
        prj_file = project_folder / f"{project_name}.prj"

        # Validate plan file exists
        if not plan_file.exists():
            return PreprocessResult(
                success=False, plan_number=plan_num,
                geometry_number=geometry_number,
                error=f"Plan file not found: {plan_file}",
                elapsed_seconds=time.time() - start_time,
            )

        # Validate project file exists
        if not prj_file.exists():
            return PreprocessResult(
                success=False, plan_number=plan_num,
                geometry_number=geometry_number,
                error=f"Project file not found: {prj_file}",
                elapsed_seconds=time.time() - start_time,
            )

        # Get HEC-RAS executable
        ras_exe = ras_obj.ras_exe_path
        if not ras_exe or not Path(ras_exe).exists():
            return PreprocessResult(
                success=False, plan_number=plan_num,
                geometry_number=geometry_number,
                error=f"HEC-RAS executable not found: {ras_exe}",
                elapsed_seconds=time.time() - start_time,
            )

        supervision_error = RasPreprocess._tcu_supervision_availability_error()
        if supervision_error:
            return PreprocessResult(
                success=False,
                plan_number=plan_num,
                geometry_number=geometry_number,
                error=supervision_error,
                elapsed_seconds=time.time() - start_time,
            )

        # Clear existing preprocessing files
        if clear_existing:
            RasPreprocess._clear_preprocessing_files(
                project_folder, project_name, plan_num, geometry_number
            )

        # Enable detailed logging to create .bco file
        BcoMonitor.enable_detailed_logging(plan_file)

        # Build command: RAS.exe -c project.prj plan.p##
        cmd = f'"{ras_exe}" -c "{prj_file}" "{plan_file}"'
        logger.info("Starting HEC-RAS preprocessing for plan %s", plan_num)
        logger.debug(f"Command: {cmd}")

        # Launch HEC-RAS
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(project_folder),
            shell=True,
        )

        # Monitor .bco file for preprocessing completion signal
        monitor = BcoMonitor(
            project_path=project_folder,
            plan_number=plan_num,
            project_name=project_name,
            signal_string="Starting Unsteady Flow Computations",
            max_wait_seconds=max_wait,
            blocking_condition=lambda: (
                RasPreprocess._detect_first_run_tcu_dialog(process.pid)
            ),
        )

        signal_detected = monitor.monitor_until_signal(process)

        # A first-run legal-assent dialog is a deterministic blocker, not a
        # compute timeout.  Stop the isolated process and report it explicitly;
        # never click or otherwise accept the terms programmatically.
        if monitor.blocked_reason:
            if process.poll() is None:
                RasPreprocess._terminate_process_tree(process)
            return PreprocessResult(
                success=False,
                plan_number=plan_num,
                geometry_number=geometry_number,
                error=monitor.blocked_reason,
                elapsed_seconds=time.time() - start_time,
            )

        # Terminate process tree
        if process.poll() is None:
            logger.debug("Preprocessing signal detected; terminating HEC-RAS")
            RasPreprocess._terminate_process_tree(process)
        elif signal_detected:
            logger.debug("Preprocessing complete; HEC-RAS process already exited")
        else:
            logger.warning(f"Process exited with code {process.returncode} before signal detected")

        # If process completed fully and .hdf exists but no .tmp.hdf, copy it
        if not tmp_hdf.exists() and hdf_file.exists() and hdf_file.stat().st_size > 0:
            logger.warning(
                "Full simulation completed before early termination; copying %s to %s",
                hdf_file.name,
                tmp_hdf.name,
            )
            shutil.copy2(hdf_file, tmp_hdf)

        # Verify all three prerequisite files exist and are non-empty
        missing = []
        if not tmp_hdf.exists() or tmp_hdf.stat().st_size == 0:
            missing.append(f".p{plan_num}.tmp.hdf")
        if not b_file.exists() or b_file.stat().st_size == 0:
            missing.append(f".b{plan_num}")
        if not x_file.exists() or x_file.stat().st_size == 0:
            missing.append(f".x{geometry_number}")

        if missing:
            return PreprocessResult(
                success=False, plan_number=plan_num,
                geometry_number=geometry_number,
                error=f"Preprocessing did not generate: {', '.join(missing)}",
                elapsed_seconds=time.time() - start_time,
            )

        # Fix line endings on .x file for Linux compatibility
        if fix_line_endings:
            RasPreprocess._fix_x_file_line_endings(x_file)

        elapsed = time.time() - start_time
        logger.info(
            "Preprocessing complete for plan %s in %.1fs: tmp.hdf=%.1fMB, b=%.0fKB, x=%.0fKB",
            plan_num,
            elapsed,
            tmp_hdf.stat().st_size / 1024 / 1024,
            b_file.stat().st_size / 1024,
            x_file.stat().st_size / 1024,
        )
        logger.debug(
            "Generated preprocessing files for plan %s: tmp_hdf=%s, b_file=%s, x_file=%s",
            plan_num,
            tmp_hdf,
            b_file,
            x_file,
        )

        return PreprocessResult(
            success=True,
            plan_number=plan_num,
            geometry_number=geometry_number,
            tmp_hdf_path=tmp_hdf,
            b_file_path=b_file,
            x_file_path=x_file,
            elapsed_seconds=elapsed,
        )

    @staticmethod
    @log_call
    def run_ras_geom_preprocess(
        plan_number: Union[str, Number],
        ras_object=None,
        input_hdf_path: Optional[Union[str, Path]] = None,
        x_file_path: Optional[Union[str, Path]] = None,
        executable_path: Optional[Union[str, Path]] = None,
        timeout: int = 300,
        require_hdf_change: bool = False,
    ) -> GeometryPreprocessResult:
        """Run the vendor ``RasGeomPreprocess`` executable for one staged plan.

        ``preprocess_plan`` creates the plan ``*.tmp.hdf`` and geometry ``.x##``
        inputs needed by the standalone geometry preprocessor.  This method runs
        the separately shipped HEC-RAS executable on those inputs using an
        argument vector (never a shell command), applies a bounded timeout, and
        records before/after HDF fingerprints.  It is intended to be called from
        Windows Python, including Windows Python hosted by Wine.

        Args:
            plan_number: Plan number (for example ``"06"``).
            ras_object: Initialized :class:`RasPrj`; defaults to the global project.
            input_hdf_path: Optional explicit plan ``*.tmp.hdf`` input.
            x_file_path: Optional explicit project ``.x##`` file.
            executable_path: Optional explicit ``RasGeomPreprocess.exe`` path.
                By default it is resolved beside ``Ras.exe`` under ``x64``.
            timeout: Maximum execution time in seconds.
            require_hdf_change: Require the input HDF fingerprint to change.
                Keep False for idempotent production reruns; qualification of a
                freshly generated input should set this to True.

        Returns:
            GeometryPreprocessResult: Bool-compatible execution evidence.
        """
        start_time = time.time()
        ras_obj = ras_object if ras_object is not None else ras

        if isinstance(plan_number, Number):
            plan_num = f"{int(plan_number):02d}"
        else:
            plan_num = str(plan_number).zfill(2)

        try:
            ras_obj.check_initialized()
        except Exception as exc:
            return GeometryPreprocessResult(
                success=False,
                plan_number=plan_num,
                error=f"Project not initialized: {exc}",
                elapsed_seconds=time.time() - start_time,
            )

        project_folder = Path(ras_obj.project_folder)
        project_name = ras_obj.project_name
        plan_path = project_folder / f"{project_name}.p{plan_num}"
        geometry_number = None
        try:
            plan_row = ras_obj.plan_df[ras_obj.plan_df["plan_number"] == plan_num]
            if not plan_row.empty and "Geom File" in plan_row.columns:
                match = re.search(r"(\d+)", str(plan_row["Geom File"].iloc[0]))
                if match:
                    geometry_number = match.group(1)
        except Exception:
            pass
        if geometry_number is None and plan_path.is_file():
            geometry_number = RasPreprocess._extract_geometry_number(plan_path)
        if geometry_number is None:
            return GeometryPreprocessResult(
                success=False,
                plan_number=plan_num,
                error=f"Could not determine geometry number for plan {plan_num}",
                elapsed_seconds=time.time() - start_time,
            )

        input_hdf = (
            Path(input_hdf_path)
            if input_hdf_path is not None
            else project_folder / f"{project_name}.p{plan_num}.tmp.hdf"
        )
        x_file = (
            Path(x_file_path)
            if x_file_path is not None
            else project_folder / f"{project_name}.x{geometry_number}"
        )
        if executable_path is None:
            ras_exe_path = Path(str(getattr(ras_obj, "ras_exe_path", "")))
            executable = ras_exe_path.parent / "x64" / "RasGeomPreprocess.exe"
        else:
            executable = Path(executable_path)

        missing = [
            str(path)
            for path in (executable, input_hdf, x_file)
            if not path.is_file() or path.stat().st_size == 0
        ]
        if missing:
            return GeometryPreprocessResult(
                success=False,
                plan_number=plan_num,
                geometry_number=geometry_number,
                executable_path=executable,
                input_hdf_path=input_hdf,
                x_file_path=x_file,
                error="Missing or empty geometry-preprocessor input: " + ", ".join(missing),
                elapsed_seconds=time.time() - start_time,
            )

        expected_x_name = f"{project_name}.x{geometry_number}".casefold()
        try:
            same_parent = x_file.parent.resolve() == input_hdf.parent.resolve()
        except OSError:
            same_parent = x_file.parent.absolute() == input_hdf.parent.absolute()
        if not same_parent or x_file.name.casefold() != expected_x_name:
            return GeometryPreprocessResult(
                success=False,
                plan_number=plan_num,
                geometry_number=geometry_number,
                executable_path=executable,
                input_hdf_path=input_hdf,
                x_file_path=x_file,
                error=(
                    "RasGeomPreprocess requires the project execution file "
                    f"{project_name}.x{geometry_number} beside the input HDF"
                ),
                elapsed_seconds=time.time() - start_time,
            )

        executable_sha256 = RasPreprocess._file_sha256(executable)
        before_sha256 = RasPreprocess._file_sha256(input_hdf)
        command = [str(executable), str(input_hdf), f"x{geometry_number}"]
        command_text = subprocess.list2cmdline(command)
        process = None
        stdout = ""
        stderr = ""
        timed_out = False
        launch_error = None

        try:
            process = subprocess.Popen(
                command,
                cwd=str(input_hdf.parent),
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                stdout, stderr = process.communicate(timeout=int(timeout))
            except subprocess.TimeoutExpired:
                timed_out = True
                RasPreprocess._terminate_process_tree(process)
                try:
                    stdout, stderr = process.communicate(timeout=2)
                except Exception:
                    stdout, stderr = "", ""
        except OSError as exc:
            launch_error = str(exc)

        after_sha256 = (
            RasPreprocess._file_sha256(input_hdf)
            if input_hdf.is_file() and input_hdf.stat().st_size > 0
            else None
        )
        output_changed = bool(
            before_sha256 and after_sha256 and before_sha256 != after_sha256
        )
        return_code = process.returncode if process is not None else None

        hdf_readable = False
        geometry_group_present = False
        hdf_error = None
        if after_sha256 is not None:
            try:
                import h5py

                with h5py.File(input_hdf, "r") as handle:
                    hdf_readable = True
                    geometry_group_present = "Geometry" in handle
            except Exception as exc:
                hdf_error = str(exc)

        errors = []
        if launch_error:
            errors.append(f"Could not launch RasGeomPreprocess: {launch_error}")
        if timed_out:
            errors.append(f"RasGeomPreprocess timed out after {int(timeout)} seconds")
        if return_code is None:
            errors.append("RasGeomPreprocess did not report a final return code")
        elif return_code != 0:
            errors.append(f"RasGeomPreprocess exited with code {return_code}")
        if after_sha256 is None:
            errors.append("RasGeomPreprocess did not leave a non-empty input HDF")
        elif not hdf_readable:
            errors.append(f"RasGeomPreprocess output HDF is unreadable: {hdf_error}")
        elif not geometry_group_present:
            errors.append("RasGeomPreprocess output HDF has no Geometry group")
        if require_hdf_change and not output_changed:
            errors.append("RasGeomPreprocess did not change the input HDF fingerprint")

        combined_output = "\n".join(item for item in (stdout, stderr) if item)
        first_error_line = next(
            (
                line.strip()[:500]
                for line in combined_output.splitlines()
                if re.search(r"\b(error|fatal)\b", line, flags=re.IGNORECASE)
                and not re.search(r"\b0\s+errors?\b", line, flags=re.IGNORECASE)
            ),
            None,
        )
        if first_error_line:
            errors.append(f"RasGeomPreprocess reported an error: {first_error_line}")
        success = not errors
        return GeometryPreprocessResult(
            success=success,
            plan_number=plan_num,
            geometry_number=geometry_number,
            elapsed_seconds=time.time() - start_time,
            command=command_text,
            return_code=return_code,
            executable_path=executable,
            executable_sha256=executable_sha256,
            input_hdf_path=input_hdf,
            x_file_path=x_file,
            input_hdf_sha256_before=before_sha256,
            input_hdf_sha256_after=after_sha256,
            output_changed=output_changed,
            hdf_readable=hdf_readable,
            geometry_group_present=geometry_group_present,
            timed_out=timed_out,
            stdout=stdout or "",
            stderr=stderr or "",
            artifact_paths=[input_hdf, x_file],
            error_count=len(errors),
            first_error_line=first_error_line,
            error="; ".join(errors) if errors else None,
        )

    @staticmethod
    @log_call
    def verify_preprocessing(
        plan_number: Union[str, Number],
        ras_object=None,
    ) -> bool:
        """
        Check if prerequisite files for Linux execution exist.

        Verifies that .tmp.hdf, .b##, and .x## files exist and are non-empty.
        Useful before calling ``RasCmdr.compute_plan_linux()``.

        Args:
            plan_number: Plan number to check (e.g., "01", 1).
            ras_object: Optional RasPrj instance. If None, uses global ras.

        Returns:
            bool: True if all three files exist and are non-empty.

        Example:
            >>> if RasPreprocess.verify_preprocessing("01"):
            ...     RasCmdr.compute_plan_linux("01", ras_exe_dir="/opt/hecras/6.6")
            ... else:
            ...     RasPreprocess.preprocess_plan("01")
        """
        ras_obj = ras_object if ras_object is not None else ras

        if isinstance(plan_number, Number):
            plan_num = f"{int(plan_number):02d}"
        else:
            plan_num = str(plan_number).zfill(2)

        try:
            ras_obj.check_initialized()
        except Exception:
            return False

        project_folder = Path(ras_obj.project_folder)
        project_name = ras_obj.project_name

        # Determine geometry number
        geometry_number = None
        try:
            plan_row = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == plan_num]
            if not plan_row.empty and 'Geom File' in plan_row.columns:
                geom_ref = str(plan_row['Geom File'].iloc[0])
                m = re.search(r'(\d+)', geom_ref)
                if m:
                    geometry_number = m.group(1)
        except Exception:
            pass

        if geometry_number is None:
            plan_path = RasPlan.get_plan_path(plan_num, ras_obj)
            if plan_path:
                geometry_number = RasPreprocess._extract_geometry_number(Path(plan_path))
            if geometry_number is None:
                return False

        tmp_hdf = project_folder / f"{project_name}.p{plan_num}.tmp.hdf"
        b_file = project_folder / f"{project_name}.b{plan_num}"
        x_file = project_folder / f"{project_name}.x{geometry_number}"

        for f in [tmp_hdf, b_file, x_file]:
            if not f.exists() or f.stat().st_size == 0:
                logger.debug(f"Missing or empty: {f.name}")
                return False

        logger.debug("All preprocessing files verified for plan %s", plan_num)
        return True

    @staticmethod
    def _extract_geometry_number(plan_path: Path) -> Optional[str]:
        """
        Extract geometry number from a plan file.

        Parses the ``Geom File=g##`` line in a HEC-RAS plan file.

        Args:
            plan_path: Path to the plan file (.p##).

        Returns:
            Geometry number as string (e.g., "04"), or None if not found.
        """
        try:
            content = plan_path.read_text(encoding='utf-8', errors='ignore')
            for line in content.splitlines():
                if line.strip().startswith("Geom File="):
                    geom_ref = line.split('=', 1)[1].strip()
                    m = re.search(r'(\d+)', geom_ref)
                    if m:
                        return m.group(1)
        except Exception as e:
            logger.debug(f"Could not read geometry number from {plan_path}: {e}")
        return None

    @staticmethod
    def _file_sha256(path: Path) -> str:
        """Return a streaming SHA-256 digest for a preprocessing artifact."""
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _detect_first_run_tcu_dialog(root_pid: Optional[int] = None) -> Optional[str]:
        """Return a diagnostic for a TCU modal in one launched process tree."""
        try:
            titles = RasPreprocess._get_visible_window_titles(root_pid=root_pid)
        except Exception as exc:
            return f"{RasPreprocess._TCU_SUPERVISION_ERROR} Detail: {exc}"
        for title in titles:
            reason = legal_dialog_blocking_reason(title=title)
            if reason:
                return reason
        return None

    @staticmethod
    def _tcu_supervision_availability_error() -> Optional[str]:
        """Return a prelaunch diagnostic when scoped TCU detection is unavailable."""
        if os.name != "nt":
            return (
                f"{RasPreprocess._TCU_SUPERVISION_ERROR} "
                "A Windows-hosted Python process is required for this Ras.exe path."
            )
        try:
            import psutil  # noqa: F401
        except Exception as exc:
            return (
                f"{RasPreprocess._TCU_SUPERVISION_ERROR} "
                f"psutil is unavailable: {exc}"
            )
        return None

    @staticmethod
    def _get_visible_window_titles(
        root_pid: Optional[int] = None,
    ) -> List[str]:
        """Enumerate visible titles, optionally scoped to one process tree."""
        if os.name != "nt":
            return []

        try:
            import ctypes
            from ctypes import wintypes

            allowed_pids = None
            if root_pid is not None:
                allowed_pids = {int(root_pid)}
                try:
                    import psutil

                    root = psutil.Process(int(root_pid))
                    allowed_pids.update(
                        child.pid for child in root.children(recursive=True)
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "Could not enumerate descendants for TCU window scope "
                        f"PID {root_pid}: {exc}"
                    ) from exc

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            enum_windows_proc = ctypes.WINFUNCTYPE(
                wintypes.BOOL,
                wintypes.HWND,
                wintypes.LPARAM,
            )
            user32.EnumWindows.argtypes = [enum_windows_proc, wintypes.LPARAM]
            user32.EnumWindows.restype = wintypes.BOOL
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [
                wintypes.HWND,
                wintypes.LPWSTR,
                ctypes.c_int,
            ]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD

            titles: List[str] = []

            @enum_windows_proc
            def collect_title(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                if allowed_pids is not None:
                    window_pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(
                        hwnd,
                        ctypes.byref(window_pid),
                    )
                    if int(window_pid.value) not in allowed_pids:
                        return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buffer = ctypes.create_unicode_buffer(length + 1)
                if user32.GetWindowTextW(hwnd, buffer, length + 1):
                    title = buffer.value.strip()
                    if title:
                        titles.append(title)
                return True

            user32.EnumWindows(collect_title, 0)
            return titles
        except Exception as exc:
            if root_pid is not None:
                raise RuntimeError(
                    f"Could not enumerate scoped visible window titles: {exc}"
                ) from exc
            logger.debug(f"Could not enumerate visible window titles: {exc}")
            return []

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> None:
        """
        Kill a process and all its children.

        Uses psutil for reliable process tree termination. Falls back to
        process.kill() if psutil is unavailable or fails.

        Args:
            process: Running subprocess to terminate.
        """
        try:
            import psutil
            parent = psutil.Process(process.pid)
            children = parent.children(recursive=True)

            # Kill children first, then parent
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass

            parent.kill()
            process.wait(timeout=10)
            logger.debug("HEC-RAS process tree terminated")
        except Exception as e:
            logger.warning(f"psutil termination failed ({e}), falling back to process.kill()")
            try:
                process.kill()
                process.wait(timeout=10)
            except Exception:
                pass

    @staticmethod
    def _clear_preprocessing_files(
        project_folder: Path,
        project_name: str,
        plan_num: str,
        geom_num: str,
    ) -> None:
        """
        Delete stale preprocessing files to force regeneration.

        Removes .tmp.hdf, .hdf, .b##, .x##, and .bco## files.

        Args:
            project_folder: Path to the project folder.
            project_name: Project name (without extension).
            plan_num: Plan number (e.g., "01").
            geom_num: Geometry number (e.g., "04").
        """
        patterns = [
            f"{project_name}.p{plan_num}.hdf",
            f"{project_name}.p{plan_num}.tmp.hdf",
            f"{project_name}.b{plan_num}",
            f"{project_name}.x{geom_num}",
            f"{project_name}.bco{plan_num}",
        ]
        for pattern in patterns:
            target = project_folder / pattern
            if target.exists():
                try:
                    target.unlink()
                    logger.debug(f"Deleted: {target.name}")
                except Exception as e:
                    logger.warning(f"Could not delete {target.name}: {e}")

    @staticmethod
    def _fix_x_file_line_endings(x_file_path: Path) -> None:
        """
        Convert CRLF to LF in the .x## file for Linux compatibility.

        Only modifies the .x file — other project files are handled by
        ``RasCmdr.compute_plan_linux()`` via dos2unix.

        Args:
            x_file_path: Path to the .x## file.
        """
        try:
            content = x_file_path.read_bytes()
            if b'\r\n' in content:
                fixed = content.replace(b'\r\n', b'\n')
                x_file_path.write_bytes(fixed)
                logger.debug(f"Fixed CRLF→LF in {x_file_path.name}")
        except Exception as e:
            logger.warning(f"Could not fix line endings in {x_file_path.name}: {e}")
