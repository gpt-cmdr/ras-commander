"""
RasCurrency - Execution currency checking for HEC-RAS simulations

This module provides utilities for determining whether HEC-RAS plan results
are current (up-to-date) based on file modification times. This enables
smart execution skip - avoiding unnecessary re-runs when results already
exist and input files haven't changed.

Currency Logic:
- Results are CURRENT if plan HDF exists AND is newer than all input files
- Input files checked: plan file (.p##), geometry file (.g##), flow file (.u##/.f##)
- For older HEC-RAS versions (no HDF): uses .O output file instead

All methods are static and designed to be used without instantiation.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Union
from numbers import Number

from .LoggingConfig import get_logger
from .Decorators import log_call

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
    def get_file_mtime(file_path: Union[str, Path]) -> Optional[float]:
        """
        Get file modification time as Unix timestamp.

        Args:
            file_path: Path to the file

        Returns:
            Unix timestamp (float) or None if file doesn't exist or error
        """
        try:
            path = Path(file_path)
            if path.exists():
                return path.stat().st_mtime
            return None
        except (PermissionError, OSError) as e:
            logger.warning(f"Error getting mtime for {file_path}: {e}")
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
    def check_plan_hdf_complete(hdf_path: Path) -> bool:
        """
        Check if plan HDF contains 'Complete Process' in compute messages.

        Args:
            hdf_path: Path to the plan HDF file

        Returns:
            True if 'Complete Process' found, False otherwise
        """
        if not hdf_path.exists():
            return False

        try:
            # Late import to avoid circular dependency
            from .hdf.HdfResultsPlan import HdfResultsPlan

            compute_msgs = HdfResultsPlan.get_compute_messages(hdf_path)
            if compute_msgs and 'Complete Process' in compute_msgs:
                return True
            return False
        except Exception as e:
            logger.warning(f"Error checking completion for {hdf_path}: {e}")
            return False

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
        1. Plan HDF exists (or .O file for older versions)
        2. HDF contains 'Complete Process' (if check_complete=True)
        3. HDF mtime > Plan file (.p##) mtime
        4. HDF mtime > Geometry file (.g##) mtime
        5. HDF mtime > Flow file (.u##/.f##) mtime

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

        # Check for HDF file first
        hdf_path = RasCurrency.get_plan_hdf_path(plan_number, ras_object)
        output_path = None
        result_mtime = None

        if hdf_path.exists():
            result_mtime = RasCurrency.get_file_mtime(hdf_path)
            result_file = hdf_path

            # Check for Complete Process
            if check_complete and not RasCurrency.check_plan_hdf_complete(hdf_path):
                return (False, f"Plan {plan_num} HDF exists but incomplete (no 'Complete Process')")
        else:
            # Try .O file for older versions
            output_path = RasCurrency.get_output_file_path(plan_number, ras_object)
            if output_path and output_path.exists():
                result_mtime = RasCurrency.get_file_mtime(output_path)
                result_file = output_path
            else:
                return (False, f"Plan {plan_num} has no results (HDF or .O file not found)")

        if result_mtime is None:
            return (False, f"Plan {plan_num} cannot determine results file modification time")

        # Get input files
        input_files = RasCurrency.get_plan_input_files(plan_number, ras_object)

        # Check each input file modification time
        stale_files = []

        for file_type, file_path in input_files.items():
            if file_path is None:
                continue

            if not file_path.exists():
                logger.debug(f"Input file not found: {file_path}")
                continue

            input_mtime = RasCurrency.get_file_mtime(file_path)
            if input_mtime is None:
                logger.warning(f"Cannot get mtime for {file_path}, assuming stale")
                stale_files.append(file_path.name)
            elif input_mtime > result_mtime:
                stale_files.append(file_path.name)
                logger.debug(f"{file_path.name} is newer than results: input={input_mtime}, result={result_mtime}")

        if stale_files:
            return (False, f"Plan {plan_num} stale: {', '.join(stale_files)} modified after results")

        return (True, f"Plan {plan_num} results are current (newer than all inputs)")

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
            logger.info(f"Deleted geometry HDF: {geom_hdf_path}")
            return True
        except (PermissionError, OSError) as e:
            logger.error(f"Error deleting geometry HDF {geom_hdf_path}: {e}")
            return False
