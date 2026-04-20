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
from pathlib import Path
from typing import List, Union

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from ..RasPrj import ras
from ..RasUtils import RasUtils

logger = get_logger(__name__)


class GeomPreprocessor:
    """
    A class for managing HEC-RAS geometry preprocessor files.

    All methods are static and designed to be used without instantiation.
    """

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

        Limitations/Future Work:
        - This function only deletes the geometry preprocessor file.
        - It does not clear the IB tables.
        - It also does not clear geometry preprocessor tables from the geometry HDF.
        - All of these features will need to be added to reliably remove geometry preprocessor
          files for 1D and 2D projects.

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

        def clear_single_file(plan_file: Union[str, Path], ras_obj) -> None:
            plan_path = Path(plan_file)
            for geom_preprocessor_file in _resolve_geompre_candidates(plan_path, ras_obj):
                if not geom_preprocessor_file.exists():
                    continue
                try:
                    geom_preprocessor_file.unlink()
                    logger.info(f"Deleted geometry preprocessor file: {geom_preprocessor_file}")
                    return
                except PermissionError:
                    logger.error(f"Permission denied: Unable to delete geometry preprocessor file: {geom_preprocessor_file}")
                    raise PermissionError(f"Unable to delete geometry preprocessor file: {geom_preprocessor_file}. Permission denied.")
                except OSError as e:
                    logger.error(f"Error deleting geometry preprocessor file: {geom_preprocessor_file}. {str(e)}")
                    raise OSError(f"Error deleting geometry preprocessor file: {geom_preprocessor_file}. {str(e)}")

            logger.warning(f"No geometry preprocessor file found for: {plan_file}")

        if plan_files is None:
            logger.info("Clearing all geometry preprocessor files in the project directory.")
            plan_files_to_clear = list(ras_obj.project_folder.glob(r'*.p*'))
        elif isinstance(plan_files, (str, Path)):
            plan_files_to_clear = [plan_files]
            logger.info(f"Clearing geometry preprocessor file for single plan: {plan_files}")
        elif isinstance(plan_files, list):
            plan_files_to_clear = plan_files
            logger.info(f"Clearing geometry preprocessor files for multiple plans: {plan_files}")
        else:
            logger.error("Invalid input type for plan_files.")
            raise ValueError("Invalid input. Please provide a string, Path, list of paths, or None.")

        for plan_file in plan_files_to_clear:
            clear_single_file(plan_file, ras_obj)

        try:
            ras_obj.geom_df = ras_obj.get_geom_entries()
            logger.info("Geometry dataframe updated successfully.")
        except Exception as e:
            logger.error(f"Failed to update geometry dataframe: {str(e)}")
            raise
