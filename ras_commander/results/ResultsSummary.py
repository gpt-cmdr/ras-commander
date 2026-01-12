"""
ResultsSummary - Generate lightweight plan results summaries from HDF files.

This module extracts summary information from HEC-RAS HDF result files
without loading heavy geospatial data like mesh cells or cross sections.

Extending results_df:
    To add new columns to results_df:
    1. Add column to summarize_plan() initial result dict
    2. Add extraction logic (if from HDF)
    3. Update get_summary_columns() list
    4. If from plan_df: Add to plan_entries dict in RasPrj.update_results_df()
    5. If from plan_df: Add to plan_meta dict in summarize_plans()
    6. Update example notebook 150_results_dataframe.ipynb
    7. Run .claude/scripts/update_results_df_columns.py if needed

    For HDF attribute mappings, use explicit dictionaries (like VOL_COLUMN_MAP)
    rather than dynamic sanitization for maintainability and clarity.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from datetime import datetime
import logging
import pandas as pd

from ..LoggingConfig import log_call, get_logger

logger = get_logger(__name__)


class ResultsSummary:
    """
    Generate lightweight plan results summaries from HDF files.

    This is a static class - do not instantiate.

    The summary includes:
    - Completion status and error detection
    - Runtime performance metrics
    - Volume accounting (unsteady only)
    - Steady/unsteady metadata

    Example:
        >>> from ras_commander.results import ResultsSummary
        >>> summary = ResultsSummary.summarize_plan(
        ...     Path("project.p01.hdf"),
        ...     {'plan_number': '01', 'plan_title': 'Base', 'flow_type': 'Unsteady'}
        ... )
        >>> print(summary['completed'], summary['runtime_complete_process_hours'])
    """

    @staticmethod
    @log_call
    def summarize_plan(
        hdf_path: Union[str, Path],
        plan_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate comprehensive results summary for a single plan.

        Extracts lightweight summary data from HDF file including
        compute messages, runtime data, and volume accounting.
        All HDF operations are wrapped in try/except for graceful
        degradation - missing data results in None values.

        Args:
            hdf_path: Path to plan HDF file
            plan_meta: Dict with keys:
                - plan_number (str): Plan identifier (e.g., "01")
                - plan_title (str): Plan title from plan file
                - flow_type (str): "Steady" or "Unsteady"

        Returns:
            dict: Flattened summary with prefixed keys:
                - plan_number, plan_title, flow_type (from plan_meta)
                - hdf_path, hdf_exists, hdf_file_modified, ras_version (file info)
                - completed, has_errors, has_warnings, error_count,
                  warning_count, first_error_line (from compute messages)
                - runtime_* (runtime data) - always present, None if unavailable
                - vol_* (volume accounting, unsteady only) - explicit mapping

        Schema Consistency:
            Core columns (plan_number through runtime_*) are ALWAYS initialized with
            default values (False, 0, None) before any HDF extraction. This
            ensures that accessing these columns will never raise KeyError,
            even if HDF data is unavailable.

            Volume columns (vol_*) use explicit mapping from HDF attribute names
            to standardized column names. Use get_summary_columns() for standard
            column ordering.
        """
        # Late imports to avoid circular dependencies
        from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan
        from ras_commander.results.ResultsParser import ResultsParser

        hdf_path = Path(hdf_path)

        # Initialize result with plan metadata
        result = {
            'plan_number': plan_meta.get('plan_number'),
            'plan_title': plan_meta.get('plan_title'),
            'flow_type': plan_meta.get('flow_type'),
            'hdf_path': str(hdf_path),
            'hdf_exists': False,
            'hdf_file_modified': None,
            'ras_version': plan_meta.get('Program Version'),
        }

        # Initialize completion/health fields with defaults
        result.update({
            'completed': False,
            'has_errors': False,
            'has_warnings': False,
            'error_count': 0,
            'warning_count': 0,
            'first_error_line': None,
        })

        # Initialize runtime fields with None (ensures consistent schema)
        result.update({
            'runtime_simulation_start': None,
            'runtime_simulation_end': None,
            'runtime_simulation_hours': None,
            'runtime_complete_process_hours': None,
            'runtime_unsteady_compute_hours': None,
            'runtime_complete_process_speed': None,
        })

        # Determine flow_type for later use
        flow_type = plan_meta.get('flow_type', '').lower()

        # Check if HDF exists
        if not hdf_path.exists():
            logger.debug(f"HDF file does not exist: {hdf_path}")
            return result

        result['hdf_exists'] = True
        result['hdf_file_modified'] = datetime.fromtimestamp(hdf_path.stat().st_mtime)

        # Extract compute messages and parse
        try:
            messages = HdfResultsPlan.get_compute_messages_hdf_only(hdf_path)
            if messages:
                parsed = ResultsParser.parse_compute_messages(messages)
                result.update(parsed)
        except Exception as e:
            logger.debug(f"Error extracting compute messages: {e}")

        # Extract runtime data
        try:
            runtime_df = HdfResultsPlan.get_runtime_data(hdf_path)
            if runtime_df is not None and len(runtime_df) > 0:
                runtime_row = runtime_df.iloc[0]
                # Flatten with runtime_ prefix
                result['runtime_simulation_start'] = runtime_row.get('Simulation Start Time')
                result['runtime_simulation_end'] = runtime_row.get('Simulation End Time')
                result['runtime_simulation_hours'] = runtime_row.get('Simulation Time (hr)')
                result['runtime_complete_process_hours'] = runtime_row.get('Complete Process (hr)')
                result['runtime_unsteady_compute_hours'] = runtime_row.get('Unsteady Flow Computations (hr)')
                result['runtime_complete_process_speed'] = runtime_row.get('Complete Process Speed (hr/hr)')
        except Exception as e:
            logger.debug(f"Error extracting runtime data: {e}")

        # Extract volume accounting (unsteady only) with explicit column mapping
        if flow_type == 'unsteady':
            # Volume column mapping (HDF attribute name -> results_df column name)
            VOL_COLUMN_MAP = {
                'Error': 'vol_error',
                'Vol Accounting in': 'vol_accounting_units',
                'Error Percent': 'vol_error_percent',
                'Total Boundary Flux of Water In': 'vol_flux_in',
                'Total Boundary Flux of Water Out': 'vol_flux_out',
                'Volume Starting': 'vol_starting',
                'Volume Ending': 'vol_ending',
            }

            try:
                vol_df = HdfResultsPlan.get_volume_accounting(hdf_path)
                if vol_df is not None and len(vol_df) > 0:
                    vol_row = vol_df.iloc[0]
                    # Map HDF columns to standardized column names
                    for hdf_col, result_col in VOL_COLUMN_MAP.items():
                        if hdf_col in vol_df.columns:
                            result[result_col] = vol_row.get(hdf_col)
            except Exception as e:
                logger.debug(f"Error extracting volume accounting: {e}")

        return result

    @staticmethod
    @log_call
    def summarize_plans(
        plan_entries: List[Dict[str, Any]],
        project_folder: Optional[Path] = None
    ) -> pd.DataFrame:
        """
        Generate results summary for multiple plans.

        Args:
            plan_entries: List of dicts with plan metadata (from plan_df.to_dict('records'))
                Each dict should have keys: plan_number, Plan Title (or plan_title),
                flow_type (or Flow File to detect type), and optionally HDF_Results_Path
            project_folder: Project folder path for resolving HDF paths when not provided
                in plan_entries. If None, HDF_Results_Path must be in each entry.

        Returns:
            pd.DataFrame: Results summary with one row per plan

        Example:
            >>> from ras_commander import init_ras_project, ras
            >>> from ras_commander.results import ResultsSummary
            >>> init_ras_project("/path/to/project", "6.6")
            >>> # Use plan_df directly
            >>> plan_entries = ras.plan_df.to_dict('records')
            >>> summary_df = ResultsSummary.summarize_plans(plan_entries, ras.project_folder)
            >>> print(summary_df[['plan_number', 'completed', 'has_errors']])
        """
        summaries = []

        for entry in plan_entries:
            plan_number = entry.get('plan_number')

            # Normalize plan_title from different possible column names
            plan_title = entry.get('plan_title') or entry.get('Plan Title') or entry.get('plan_shortid')

            # Determine flow type - check for direct value or infer from flow file
            flow_type = entry.get('flow_type')
            if not flow_type:
                # Try to infer from unsteady_number presence
                if entry.get('unsteady_number'):
                    flow_type = 'Unsteady'
                elif entry.get('Flow File'):
                    # Check if it references .f## (steady) or .u## (unsteady)
                    flow_file = str(entry.get('Flow File', ''))
                    if '.u' in flow_file.lower():
                        flow_type = 'Unsteady'
                    else:
                        flow_type = 'Steady'
                else:
                    flow_type = 'Unknown'

            # Build plan_meta dict
            plan_meta = {
                'plan_number': plan_number,
                'plan_title': plan_title,
                'flow_type': flow_type,
                'Program Version': entry.get('Program Version')
            }

            # Resolve HDF path
            hdf_path = entry.get('HDF_Results_Path')
            if hdf_path:
                hdf_path = Path(hdf_path)
            elif project_folder:
                # Construct expected path if not provided
                project_folder = Path(project_folder)
                # Find .prj file to get project name
                prj_files = list(project_folder.glob("*.prj"))
                if prj_files:
                    project_name = prj_files[0].stem
                else:
                    project_name = project_folder.name
                hdf_path = project_folder / f"{project_name}.p{plan_number}.hdf"
            else:
                # No HDF path available - create entry with defaults
                logger.warning(f"No HDF path for plan {plan_number} and no project_folder provided")
                hdf_path = Path(f"unknown.p{plan_number}.hdf")

            summary = ResultsSummary.summarize_plan(hdf_path, plan_meta)
            summaries.append(summary)

        if not summaries:
            return pd.DataFrame()

        # Create DataFrame and ensure consistent schema across all rows
        # This is important because vol_* columns are dynamic (depend on HDF content)
        # Some plans may have volume accounting data, others may not
        df = pd.DataFrame(summaries)

        # Get the union of all columns that appear in any row
        # This ensures all rows have the same columns (fill missing with None)
        # pandas.DataFrame handles this automatically, but we ensure explicit None
        # for any columns that were not set
        return df

    @staticmethod
    def get_summary_columns() -> List[str]:
        """
        Return the standard column ordering for summary DataFrames.

        Use this to ensure consistent column ordering when concatenating
        or comparing summary DataFrames.

        Returns:
            List[str]: Ordered list of column names

        Notes:
            Static columns (always present with None if no data):
                - Identity: plan_number through ras_version
                - Completion/health: completed through first_error_line
                - Runtime: runtime_* columns

            Volume columns (unsteady only):
                - vol_* columns with explicit names from VOL_COLUMN_MAP

            Use df.reindex(columns=get_summary_columns()) to reorder,
            adding missing columns as NaN.
        """
        return [
            # Identity columns (always present)
            'plan_number',
            'plan_title',
            'flow_type',
            'hdf_path',
            'hdf_exists',
            'hdf_file_modified',
            'ras_version',
            # Completion/health (always present)
            'completed',
            'has_errors',
            'has_warnings',
            'error_count',
            'warning_count',
            'first_error_line',
            # Runtime (always present, may be None)
            'runtime_simulation_start',
            'runtime_simulation_end',
            'runtime_simulation_hours',
            'runtime_complete_process_hours',
            'runtime_unsteady_compute_hours',
            'runtime_complete_process_speed',
            # Volume accounting (unsteady only)
            'vol_error',
            'vol_accounting_units',
            'vol_error_percent',
            'vol_flux_in',
            'vol_flux_out',
            'vol_starting',
            'vol_ending',
        ]
