"""
RasCurrency - Execution currency checking for HEC-RAS simulations

This module provides utilities for determining whether HEC-RAS plan results
are current (up-to-date) based on file modification times. This enables
smart execution skip - avoiding unnecessary re-runs when results already
exist and input files haven't changed.

Currency Logic:
- The actual configured execution engine selects HDF or legacy .O results
- Coexisting result families are never considered current; rerunning normalizes them
- Input files checked: plan file (.p##), geometry file (.g##), flow file (.u##/.f##)

All methods are static and designed to be used without instantiation.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Union
from numbers import Number

from .LoggingConfig import get_logger
from .Decorators import log_call
from .ExecutionArtifacts import (
    ResultFormat,
    get_plan_result_artifact_paths,
    resolve_plan_result_artifact,
)

logger = get_logger(__name__)


class RasCurrency:
    """
    Static class for HEC-RAS execution currency checking.

    Determines whether plan results are current based on file modification times,
    enabling smart execution skip to avoid unnecessary re-runs.

    All methods are static and designed to be used without instantiation.

    Methods:
        get_file_mtime(): Get file modification time as Unix timestamp
        get_plan_input_files(): Get paths to plan, geometry, and flow files
        get_plan_hdf_path(): Get expected path to plan HDF results file
        get_geom_hdf_path(): Get path to geometry HDF file
        get_output_file_path(): Get path to .O output file (older versions)
        check_plan_hdf_complete(): Check if plan HDF contains 'Complete Process'
        are_plan_results_current(): Main currency check for plan results
        is_geom_preprocessing_current(): Check if geometry preprocessing is current
        clear_geom_hdf(): Clear geometry HDF file to force re-preprocessing
    """

    @staticmethod
    def get_file_mtime(
        file_path: Union[str, Path],
        warn_on_error: bool = True
    ) -> Optional[float]:
        """
        Get file modification time as Unix timestamp.

        Args:
            file_path: Path to the file
            warn_on_error: Whether to emit a warning if the mtime cannot be read

        Returns:
            Unix timestamp (float) or None if file doesn't exist or error
        """
        try:
            path = Path(file_path)
            if path.exists():
                return path.stat().st_mtime
            return None
        except (PermissionError, OSError) as e:
            if warn_on_error:
                logger.warning(f"Error getting mtime for {file_path}: {e}")
            else:
                logger.debug(f"Error getting mtime for {file_path}: {e}")
            return None

    @staticmethod
    def _normalize_plan_number(plan_number: Union[str, Number, Path]) -> str:
        """
        Normalize plan number to 2-digit string format.

        Args:
            plan_number: Plan number in various formats

        Returns:
            Two-digit string (e.g., "01", "02")
        """
        if isinstance(plan_number, Path):
            # Extract plan number from path like "project.p01"
            stem = plan_number.stem
            if '.p' in stem:
                plan_num = stem.split('.p')[-1]
            else:
                plan_num = stem[-2:] if len(stem) >= 2 else stem
        elif isinstance(plan_number, Number):
            plan_num = f"{int(plan_number):02d}"
        else:
            plan_num = str(plan_number).lstrip('p').zfill(2)

        return plan_num

    @staticmethod
    @log_call
    def get_plan_input_files(plan_number: Union[str, Number, Path], ras_object) -> Dict[str, Optional[Path]]:
        """
        Get paths to plan, geometry, and flow files for a plan.

        Args:
            plan_number: Plan number (e.g., "01", 1)
            ras_object: RasPrj instance

        Returns:
            Dictionary with keys: 'plan', 'geom', 'flow' (values are Path or None)
        """
        plan_num = RasCurrency._normalize_plan_number(plan_number)

        result = {
            'plan': None,
            'geom': None,
            'flow': None
        }

        # Get plan file path from plan_df
        if hasattr(ras_object, 'plan_df') and ras_object.plan_df is not None:
            plan_df = ras_object.plan_df

            # Find matching plan row
            plan_mask = plan_df['plan_number'].astype(str).str.zfill(2) == plan_num
            if plan_mask.any():
                plan_row = plan_df[plan_mask].iloc[0]

                # Get plan file path
                if 'full_path' in plan_row.index and plan_row['full_path']:
                    result['plan'] = Path(plan_row['full_path'])

                # Get geometry file path
                if 'Geom Path' in plan_row.index and plan_row['Geom Path']:
                    result['geom'] = Path(plan_row['Geom Path'])
                elif 'geom_file' in plan_row.index and plan_row['geom_file']:
                    result['geom'] = Path(ras_object.project_folder) / plan_row['geom_file']

                # Get flow file path (unsteady or steady)
                if 'Flow Path' in plan_row.index and plan_row['Flow Path']:
                    result['flow'] = Path(plan_row['Flow Path'])
                elif 'unsteady_file' in plan_row.index and plan_row['unsteady_file']:
                    result['flow'] = Path(ras_object.project_folder) / plan_row['unsteady_file']
                elif 'steady_file' in plan_row.index and plan_row['steady_file']:
                    result['flow'] = Path(ras_object.project_folder) / plan_row['steady_file']

        return result

    @staticmethod
    def get_plan_hdf_path(plan_number: Union[str, Number], ras_object) -> Path:
        """
        Get the expected HDF results path for a plan.

        Args:
            plan_number: Plan number (e.g., "01", 1)
            ras_object: RasPrj instance

        Returns:
            Path to the expected HDF file
        """
        plan_num = RasCurrency._normalize_plan_number(plan_number)
        return Path(ras_object.project_folder) / f"{ras_object.project_name}.p{plan_num}.hdf"

    @staticmethod
    def get_geom_hdf_path(plan_number: Union[str, Number], ras_object) -> Optional[Path]:
        """
        Get path to geometry HDF file for a plan.

        Args:
            plan_number: Plan number (e.g., "01", 1)
            ras_object: RasPrj instance

        Returns:
            Path to geometry HDF file or None if not found
        """
        plan_num = RasCurrency._normalize_plan_number(plan_number)

        # Get geometry number from plan
        if hasattr(ras_object, 'plan_df') and ras_object.plan_df is not None:
            plan_df = ras_object.plan_df
            plan_mask = plan_df['plan_number'].astype(str).str.zfill(2) == plan_num

            if plan_mask.any():
                plan_row = plan_df[plan_mask].iloc[0]

                # Get geometry number
                geom_num = None
                if 'geometry_number' in plan_row.index:
                    geom_num = str(plan_row['geometry_number']).zfill(2)
                elif 'geom_file' in plan_row.index and plan_row['geom_file']:
                    # Extract from filename like "project.g01"
                    geom_file = str(plan_row['geom_file'])
                    if '.g' in geom_file:
                        geom_num = geom_file.split('.g')[-1].split('.')[0].zfill(2)

                if geom_num:
                    geom_hdf = Path(ras_object.project_folder) / f"{ras_object.project_name}.g{geom_num}.hdf"
                    return geom_hdf

        return None

    @staticmethod
    def get_output_file_path(plan_number: Union[str, Number], ras_object) -> Optional[Path]:
        """
        Get path to .O output file for older HEC-RAS versions.

        Args:
            plan_number: Plan number (e.g., "01", 1)
            ras_object: RasPrj instance

        Returns:
            Path to .O output file or None if not found
        """
        plan_num = RasCurrency._normalize_plan_number(plan_number)
        output_file = Path(ras_object.project_folder) / f"{ras_object.project_name}.O{plan_num}"

        if output_file.exists():
            return output_file
        return None

    @staticmethod
    def _get_plan_hdf_incomplete_reason(hdf_path: Path) -> Optional[str]:
        """Return None when the plan HDF is complete, otherwise a concise reason."""
        hdf_path = Path(hdf_path)

        if not hdf_path.exists():
            logger.debug(f"Plan HDF does not exist: {hdf_path}")
            return "HDF file does not exist"

        try:
            import h5py
            from .hdf.HdfResultsPlan import HdfResultsPlan
            from .results.ResultsParser import ResultsParser

            compute_msgs = HdfResultsPlan.get_compute_messages(hdf_path)
            if not compute_msgs:
                logger.debug(f"Plan HDF has no available compute messages: {hdf_path}")
                return "compute messages unavailable"

            if not ResultsParser._has_complete_process_record(compute_msgs):
                logger.debug(
                    f"Plan HDF missing 'Complete Process' in compute messages: {hdf_path}"
                )
                return "missing 'Complete Process' in compute messages"

            with h5py.File(str(hdf_path), 'r') as hdf:
                if hdf.get('Plan Data/Plan Information') is None:
                    logger.debug(
                        f"Plan HDF missing '/Plan Data/Plan Information': {hdf_path}"
                    )
                    return "missing '/Plan Data/Plan Information'"

            return None
        except Exception as e:
            logger.warning(f"Error checking completion for {hdf_path}: {e}")
            return f"completion check failed: {e}"

    @staticmethod
    def check_plan_hdf_complete(hdf_path: Path) -> bool:
        """
        Check if plan HDF represents a successful computation.

        Checks both 'Complete Process' in compute messages AND structural
        integrity (/Plan Data/Plan Information must exist). A partially
        written HDF from a failed preprocessing pass will fail this check.

        Args:
            hdf_path: Path to the plan HDF file

        Returns:
            True if HDF is structurally complete with 'Complete Process'
        """
        return RasCurrency._get_plan_hdf_incomplete_reason(hdf_path) is None

    @staticmethod
    @log_call
    def are_plan_results_current(
        plan_number: Union[str, Number, Path],
        ras_object,
        check_complete: bool = True
    ) -> Tuple[bool, str]:
        """
        Check if plan results are current (no re-run needed).

        Results are CURRENT if ALL conditions are met:
        1. The version-aware evidence resolver selects an existing result
        2. A selected HDF contains 'Complete Process' (if check_complete=True)
        3. Result mtime > Plan file (.p##) mtime
        4. Result mtime > Geometry file (.g##) mtime
        5. Result mtime > Flow file (.u##/.f##) mtime

        Args:
            plan_number: Plan number (e.g., "01", 1)
            ras_object: RasPrj instance
            check_complete: Whether to verify 'Complete Process' in HDF

        Returns:
            Tuple of (is_current: bool, reason: str)
            - is_current: True if results are current, False if execution needed
            - reason: Human-readable explanation
        """
        plan_num = RasCurrency._normalize_plan_number(plan_number)

        resolution = resolve_plan_result_artifact(
            plan_number,
            ras_object=ras_object,
        )
        if not resolution.selected_exists:
            return (
                False,
                f"Plan {plan_num} has no {resolution.selected_format} results "
                "selected by its Program Version declaration",
            )

        return RasCurrency._evaluate_result_currency(
            plan_number,
            ras_object,
            result_file=resolution.selected_path,
            result_format=resolution.selected_format,
            check_complete=check_complete,
        )

    @staticmethod
    def _are_plan_results_current_for_execution(
        plan_number: Union[str, Number, Path],
        ras_object,
        *,
        output_format: ResultFormat,
        check_complete: bool = True,
    ) -> Tuple[bool, str]:
        """Check currency against the explicitly selected execution engine.

        Unlike public evidence inspection, an execution skip must never retain
        two result families. Mixed artifacts therefore force a rerun so the
        compute path can normalize the project.
        """
        plan_num = RasCurrency._normalize_plan_number(plan_number)
        paths = get_plan_result_artifact_paths(plan_number, ras_object=ras_object)
        if paths.hdf.is_file() and paths.legacy_output.is_file():
            return (
                False,
                f"Plan {plan_num} has multiple result formats; rerun with the "
                "selected HEC-RAS version to normalize artifacts",
            )
        result_file = paths.hdf if output_format == "hdf" else paths.legacy_output
        if not result_file.is_file():
            return (
                False,
                f"Plan {plan_num} has no {output_format} results for the "
                "selected HEC-RAS execution version",
            )
        return RasCurrency._evaluate_result_currency(
            plan_number,
            ras_object,
            result_file=result_file,
            result_format=output_format,
            check_complete=check_complete,
        )

    @staticmethod
    def _evaluate_result_currency(
        plan_number: Union[str, Number, Path],
        ras_object,
        *,
        result_file: Path,
        result_format: ResultFormat,
        check_complete: bool,
    ) -> Tuple[bool, str]:
        """Compare one already-selected result artifact with plan inputs."""
        plan_num = RasCurrency._normalize_plan_number(plan_number)

        result_mtime = RasCurrency.get_file_mtime(result_file)
        if check_complete and result_format == "hdf":
            incomplete_reason = RasCurrency._get_plan_hdf_incomplete_reason(
                result_file
            )
            if incomplete_reason:
                return (
                    False,
                    f"Plan {plan_num} HDF exists but incomplete "
                    f"({incomplete_reason})",
                )

        if result_mtime is None:
            return (False, f"Plan {plan_num} cannot determine results file modification time")

        # Get input files
        input_files = RasCurrency.get_plan_input_files(plan_number, ras_object)

        # Check each input file modification time
        missing_files = []
        unreadable_files = []
        stale_files = []

        for file_type, file_path in input_files.items():
            if file_path is None:
                continue

            if not file_path.exists():
                logger.warning(
                    f"Plan {plan_num} expected {file_type} input file not found: {file_path}"
                )
                missing_files.append(f"{file_type}: {file_path.name}")
                continue

            input_mtime = RasCurrency.get_file_mtime(file_path, warn_on_error=False)
            if input_mtime is None:
                logger.warning(
                    f"Plan {plan_num} cannot get mtime for {file_type} input file "
                    f"{file_path}; assuming stale"
                )
                unreadable_files.append(f"{file_type}: {file_path.name}")
            elif input_mtime > result_mtime:
                stale_files.append(file_path.name)
                logger.debug(f"{file_path.name} is newer than results: input={input_mtime}, result={result_mtime}")

        if missing_files:
            return (False, f"Plan {plan_num} stale: missing input files: {', '.join(missing_files)}")

        if unreadable_files:
            return (False, f"Plan {plan_num} stale: unreadable input mtimes: {', '.join(unreadable_files)}")

        if stale_files:
            return (False, f"Plan {plan_num} stale: {', '.join(stale_files)} modified after results")

        return (
            True,
            f"Plan {plan_num} {result_format} results are current "
            "(newer than all inputs)",
        )

    @staticmethod
    @log_call
    def is_geom_preprocessing_current(
        plan_number: Union[str, Number, Path],
        ras_object
    ) -> Tuple[bool, str]:
        """
        Check if geometry preprocessing is current.

        Geometry preprocessing is CURRENT if:
        1. Geometry HDF (.g##.hdf) exists
        2. Geometry HDF mtime > Geometry text file (.g##) mtime

        Args:
            plan_number: Plan number (e.g., "01", 1)
            ras_object: RasPrj instance

        Returns:
            Tuple of (is_current: bool, reason: str)
        """
        plan_num = RasCurrency._normalize_plan_number(plan_number)

        # Get geometry HDF path
        geom_hdf_path = RasCurrency.get_geom_hdf_path(plan_number, ras_object)

        if geom_hdf_path is None:
            return (False, f"Plan {plan_num} geometry HDF path cannot be determined")

        if not geom_hdf_path.exists():
            return (False, f"Plan {plan_num} geometry HDF does not exist: {geom_hdf_path.name}")

        geom_hdf_mtime = RasCurrency.get_file_mtime(geom_hdf_path)
        if geom_hdf_mtime is None:
            return (False, f"Plan {plan_num} cannot determine geometry HDF modification time")

        # Get geometry text file path
        input_files = RasCurrency.get_plan_input_files(plan_number, ras_object)
        geom_path = input_files.get('geom')

        if geom_path is None or not geom_path.exists():
            # If we can't find geometry file, assume preprocessing is OK
            return (True, f"Plan {plan_num} geometry preprocessing assumed current (geometry file not found)")

        geom_mtime = RasCurrency.get_file_mtime(geom_path)
        if geom_mtime is None:
            return (False, f"Plan {plan_num} cannot determine geometry file modification time")

        if geom_mtime > geom_hdf_mtime:
            return (False, f"Plan {plan_num} geometry modified after preprocessing: {geom_path.name}")

        return (True, f"Plan {plan_num} geometry preprocessing is current")

    @staticmethod
    @log_call
    def clear_geom_hdf(plan_number: Union[str, Number, Path], ras_object) -> bool:
        """
        Clear geometry HDF file to force re-preprocessing.

        Args:
            plan_number: Plan number (e.g., "01", 1)
            ras_object: RasPrj instance

        Returns:
            True if file was deleted or didn't exist, False on error
        """
        geom_hdf_path = RasCurrency.get_geom_hdf_path(plan_number, ras_object)

        if geom_hdf_path is None:
            logger.debug(f"No geometry HDF path found for plan {plan_number}")
            return True

        if not geom_hdf_path.exists():
            logger.debug(f"Geometry HDF does not exist: {geom_hdf_path}")
            return True

        try:
            geom_hdf_path.unlink()
            logger.debug(f"Deleted geometry HDF: {geom_hdf_path}")
            return True
        except (PermissionError, OSError) as e:
            logger.error(f"Error deleting geometry HDF {geom_hdf_path}: {e}")
            return False
