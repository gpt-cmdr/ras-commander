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

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Union

from numbers import Number

from .ComputeResults import PreprocessResult
from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasBco import BcoMonitor
from .RasPlan import RasPlan
from .RasPrj import ras

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
        )

        signal_detected = monitor.monitor_until_signal(process)

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
