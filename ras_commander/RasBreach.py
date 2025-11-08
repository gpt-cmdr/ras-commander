"""
RasBreach: Dam breach parameter modification and results extraction for HEC-RAS.

This module provides methods for both:
1. Reading/writing breach parameters in plan files (.p##)
2. Extracting breach results from HDF output files

The class follows ras-commander conventions with static methods, decorators for
plan-number-based access, and standardized return types (pandas DataFrames).

Classes:
    RasBreach: Static methods for breach operations

Key HDF Extraction Methods:
    - list_breach_structures_hdf(): List breach structures in HDF results
    - get_breach_timeseries(): Extract HW, TW, Flow time series
    - get_breaching_variables(): Extract breach geometry progression
    - get_breach_summary(): Extract peak values and timing
    - get_structure_variables(): Extract structure-level flow data

Key Plan File Methods:
    - list_breach_structures_plan(): List breach structures in plan file
    - read_breach_block(): Parse breach parameters from plan
    - update_breach_block(): Modify breach parameters in plan

Author: ras-commander development team
Date: 2025
"""

from typing import Dict, List, Union, Optional, Tuple
from pathlib import Path
import h5py
import pandas as pd
import numpy as np
from datetime import datetime
import re
from dataclasses import dataclass

from .Decorators import standardize_input, log_call
from .HdfUtils import HdfUtils
from .HdfBase import HdfBase
from .LoggingConfig import get_logger
from .RasPrj import ras

logger = get_logger(__name__)


class RasBreach:
    """
    Handles dam breach parameter modification and results extraction.

    This class provides comprehensive breach functionality including:
    - HDF results extraction (time series, geometry evolution, summaries)
    - Plan file parameter reading and modification
    - Breach activation status and metadata

    All methods are static and designed for plan-number-based or path-based access
    via the @standardize_input decorator.

    Examples:
        >>> # Extract breach time series by plan number
        >>> breach_df = RasBreach.get_breach_timeseries("02")

        >>> # Get specific structure
        >>> breach_df = RasBreach.get_breach_timeseries("02", "Laxton_Dam")

        >>> # List all breach structures
        >>> structures = RasBreach.list_breach_structures_hdf("02")
    """

    # ==========================================================================
    # HDF RESULTS EXTRACTION METHODS
    # ==========================================================================

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def list_breach_structures_hdf(hdf_path: Path, ras_object=None) -> List[str]:
        """
        List all SA/2D Area Connection structures with breach results in HDF file.

        This includes both actual breach structures and regular SA/2D connections.
        To identify which have breach capability, use get_breach_info().

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        List[str]
            Names of all SA/2D Area Connection structures with time series results.
            Returns empty list if no SA/2D connections found.

        Examples
        --------
        >>> structures = RasBreach.list_breach_structures_hdf("02")
        >>> print(structures)
        ['Laxton_Dam', 'PineCreek#1_Dam', 'US_2DArea_Res2']

        Notes
        -----
        - Not all structures returned have breach capability
        - Use get_breach_info() to determine which have "Breaching Variables"
        - Empty list returned if no SA/2D connections in results
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/SA 2D Area Conn"

                if base_path not in hdf_file:
                    logger.warning(f"No SA 2D Area Conn data found in {hdf_path.name}")
                    return []

                # List all groups (structure names) under SA 2D Area Conn
                structures = list(hdf_file[base_path].keys())
                logger.info(f"Found {len(structures)} SA/2D connection structures: {structures}")
                return structures

        except Exception as e:
            logger.error(f"Error listing breach structures: {e}")
            return []

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_breach_info(hdf_path: Path, ras_object=None) -> pd.DataFrame:
        """
        Get information about which structures have breach capability.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        pd.DataFrame
            DataFrame with columns:
            - structure: Structure name
            - has_breach: Boolean, True if "Breaching Variables" dataset exists
            - breach_at_time: Time of breach initiation (if available)
            - breach_at_date: Date/time of breach (if available)
            - centerline_breach: Centerline station for breach (if available)

        Examples
        --------
        >>> info = RasBreach.get_breach_info("02")
        >>> breach_dams = info[info['has_breach']]['structure'].tolist()
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                structures = RasBreach.list_breach_structures_hdf(hdf_path, ras_object=ras_object)

                if not structures:
                    return pd.DataFrame()

                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/SA 2D Area Conn"

                info_list = []
                for struct_name in structures:
                    struct_path = f"{base_path}/{struct_name}"
                    breach_var_path = f"{struct_path}/Breaching Variables"

                    info = {'structure': struct_name}

                    # Check if breach variables exist
                    if breach_var_path in hdf_file:
                        info['has_breach'] = True

                        # Extract breach metadata from attributes
                        breach_dataset = hdf_file[breach_var_path]
                        if 'Breach at' in breach_dataset.attrs:
                            breach_at = breach_dataset.attrs['Breach at']
                            info['breach_at_date'] = breach_at.decode('utf-8') if isinstance(breach_at, bytes) else breach_at
                        else:
                            info['breach_at_date'] = None

                        if 'Breach at Time (Days)' in breach_dataset.attrs:
                            info['breach_at_time'] = float(breach_dataset.attrs['Breach at Time (Days)'])
                        else:
                            info['breach_at_time'] = None

                        if 'Centerline Breach' in breach_dataset.attrs:
                            info['centerline_breach'] = float(breach_dataset.attrs['Centerline Breach'])
                        else:
                            info['centerline_breach'] = None
                    else:
                        info['has_breach'] = False
                        info['breach_at_date'] = None
                        info['breach_at_time'] = None
                        info['centerline_breach'] = None

                    info_list.append(info)

                return pd.DataFrame(info_list)

        except Exception as e:
            logger.error(f"Error getting breach info: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_structure_variables(hdf_path: Path, structure_name: str = None,
                                ras_object=None) -> pd.DataFrame:
        """
        Extract structure-level flow variables (Total Flow, Weir Flow, HW, TW).

        This is the primary time series for overall structure performance.
        Available for all SA/2D connections (with or without breach).

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        structure_name : str, optional
            Specific structure name. If None, returns all structures.
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        pd.DataFrame
            Time series data with columns:
            - datetime: Timestamp
            - structure: Structure name (if multiple structures)
            - total_flow: Total flow through structure (cfs or m³/s)
            - weir_flow: Flow over weir (cfs or m³/s)
            - hw: Headwater elevation at representative station (ft or m)
            - tw: Tailwater elevation at representative station (ft or m)

        Examples
        --------
        >>> # Get all structures
        >>> df = RasBreach.get_structure_variables("02")

        >>> # Get specific structure
        >>> df = RasBreach.get_structure_variables("02", "Laxton_Dam")

        >>> # Plot flow hydrograph
        >>> import matplotlib.pyplot as plt
        >>> plt.plot(df['datetime'], df['total_flow'])
        >>> plt.ylabel('Flow (cfs)')

        Notes
        -----
        - HW and TW are at representative stations defined in structure attributes
        - For breach structures, use get_breaching_variables() for breach-specific data
        - Units depend on project unit system (US Customary or SI)
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
                sa_conn_path = f"{base_path}/SA 2D Area Conn"

                if sa_conn_path not in hdf_file:
                    logger.warning(f"No SA 2D Area Conn data in {hdf_path.name}")
                    return pd.DataFrame()

                # Get timestamps
                time_stamps = HdfBase.get_unsteady_timestamps(hdf_file)

                # Get structure names
                if structure_name:
                    structures = [structure_name]
                else:
                    structures = RasBreach.list_breach_structures_hdf(hdf_path, ras_object=ras_object)

                # Extract data for each structure
                data_list = []
                for struct in structures:
                    struct_path = f"{sa_conn_path}/{struct}"
                    var_path = f"{struct_path}/Structure Variables"

                    if var_path not in hdf_file:
                        logger.warning(f"Structure Variables not found for {struct}")
                        continue

                    # Extract dataset
                    dataset = hdf_file[var_path][:]  # shape: (n_timesteps, 4)

                    # Get variable names and units from attributes
                    if 'Variable_Unit' in hdf_file[var_path].attrs:
                        var_unit = hdf_file[var_path].attrs['Variable_Unit']
                        # var_unit is array of [name, unit] pairs

                    # Create DataFrame for this structure
                    struct_data = pd.DataFrame({
                        'datetime': time_stamps,
                        'total_flow': dataset[:, 0],
                        'weir_flow': dataset[:, 1],
                        'hw': dataset[:, 2],
                        'tw': dataset[:, 3]
                    })

                    if len(structures) > 1:
                        struct_data.insert(1, 'structure', struct)

                    data_list.append(struct_data)

                # Combine all structures
                if data_list:
                    result_df = pd.concat(data_list, ignore_index=True)
                    logger.info(f"Extracted {len(time_stamps)} timesteps for {len(structures)} structure(s)")
                    return result_df
                else:
                    return pd.DataFrame()

        except Exception as e:
            logger.error(f"Error extracting structure variables: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_breaching_variables(hdf_path: Path, structure_name: str = None,
                               ras_object=None) -> pd.DataFrame:
        """
        Extract breach-specific geometry progression and flow data.

        Only available for structures with breach capability. This dataset shows
        how the breach evolves over time (width, depth, flow, etc.).

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        structure_name : str, optional
            Specific structure name. If None, returns all breach structures.
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        pd.DataFrame
            Breach progression data with columns:
            - datetime: Timestamp
            - structure: Structure name (if multiple structures)
            - hw: Headwater stage at breach (ft or m)
            - tw: Tailwater stage at breach (ft or m)
            - bottom_width: Current breach bottom width (ft or m)
            - bottom_elevation: Current breach bottom elevation (ft or m)
            - left_slope: Left side slope (feet/feet or m/m)
            - right_slope: Right side slope (feet/feet or m/m)
            - breach_flow: Flow through breach opening (cfs or m³/s)
            - breach_velocity: Average velocity through breach (ft/s or m/s)
            - breach_flow_area: Flow area of breach (ft² or m²)

        Examples
        --------
        >>> # Get breach progression for specific dam
        >>> df = RasBreach.get_breaching_variables("02", "Laxton_Dam")

        >>> # Plot breach width evolution
        >>> import matplotlib.pyplot as plt
        >>> plt.plot(df['datetime'], df['bottom_width'])
        >>> plt.ylabel('Breach Width (ft)')

        >>> # Get all breach structures
        >>> df = RasBreach.get_breaching_variables("02")

        Notes
        -----
        - Returns empty DataFrame if structure has no breach capability
        - NaN values indicate breach not yet formed at that timestep
        - Units depend on project unit system
        - For total structure flow, use get_structure_variables()

        Raises
        ------
        ValueError
            If specified structure_name doesn't exist in HDF
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
                sa_conn_path = f"{base_path}/SA 2D Area Conn"

                if sa_conn_path not in hdf_file:
                    logger.warning(f"No SA 2D Area Conn data in {hdf_path.name}")
                    return pd.DataFrame()

                # Get timestamps
                time_stamps = HdfBase.get_unsteady_timestamps(hdf_file)

                # Get structure names with breach capability
                breach_info = RasBreach.get_breach_info(hdf_path, ras_object=ras_object)
                available_breach_structures = breach_info[breach_info['has_breach']]['structure'].tolist()

                if not available_breach_structures:
                    logger.warning("No breach structures found in HDF file")
                    return pd.DataFrame()

                # Determine structures to extract
                if structure_name:
                    if structure_name not in available_breach_structures:
                        raise ValueError(f"Structure '{structure_name}' does not have breach capability. "
                                       f"Available breach structures: {available_breach_structures}")
                    structures = [structure_name]
                else:
                    structures = available_breach_structures

                # Extract data for each structure
                data_list = []
                for struct in structures:
                    breach_var_path = f"{sa_conn_path}/{struct}/Breaching Variables"

                    # Extract dataset
                    dataset = hdf_file[breach_var_path][:]  # shape: (n_timesteps, 9)

                    # Get variable names and units from attributes
                    var_unit = hdf_file[breach_var_path].attrs['Variable_Unit']
                    # var_unit[0] = [b'Stage HW', b'ft'], etc.

                    # Create DataFrame for this structure
                    struct_data = pd.DataFrame({
                        'datetime': time_stamps,
                        'hw': dataset[:, 0],
                        'tw': dataset[:, 1],
                        'bottom_width': dataset[:, 2],
                        'bottom_elevation': dataset[:, 3],
                        'left_slope': dataset[:, 4],
                        'right_slope': dataset[:, 5],
                        'breach_flow': dataset[:, 6],
                        'breach_velocity': dataset[:, 7],
                        'breach_flow_area': dataset[:, 8]
                    })

                    if len(structures) > 1:
                        struct_data.insert(1, 'structure', struct)

                    data_list.append(struct_data)

                # Combine all structures
                if data_list:
                    result_df = pd.concat(data_list, ignore_index=True)
                    logger.info(f"Extracted breach variables for {len(structures)} structure(s), "
                              f"{len(time_stamps)} timesteps")
                    return result_df
                else:
                    return pd.DataFrame()

        except Exception as e:
            logger.error(f"Error extracting breaching variables: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_breach_timeseries(hdf_path: Path, structure_name: str = None,
                             ras_object=None) -> pd.DataFrame:
        """
        Extract combined breach and structure time series (primary user function).

        This is a convenience function that combines data from both:
        - Structure Variables (total flow, weir flow)
        - Breaching Variables (breach geometry and breach-specific flow)

        Provides a complete picture of dam breach behavior over time.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        structure_name : str, optional
            Specific structure name. If None, returns all breach structures.
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        pd.DataFrame
            Combined time series with columns:
            - datetime: Timestamp
            - structure: Structure name (if multiple structures)
            - total_flow: Total flow through structure (cfs)
            - weir_flow: Flow over remaining weir (cfs)
            - breach_flow: Flow through breach opening (cfs)
            - hw: Headwater elevation (ft)
            - tw: Tailwater elevation (ft)
            - bottom_width: Breach width (ft)
            - bottom_elevation: Breach bottom elevation (ft)
            - left_slope: Left side slope
            - right_slope: Right side slope
            - breach_velocity: Breach velocity (ft/s)
            - breach_flow_area: Breach flow area (ft²)

        Examples
        --------
        >>> # Extract all breach data for plan 02
        >>> df = RasBreach.get_breach_timeseries("02")

        >>> # Get specific dam
        >>> df = RasBreach.get_breach_timeseries("02", "Laxton_Dam")

        >>> # Visualize
        >>> import matplotlib.pyplot as plt
        >>> fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        >>>
        >>> # Flow hydrograph
        >>> ax1.plot(df['datetime'], df['total_flow'], label='Total Flow')
        >>> ax1.plot(df['datetime'], df['breach_flow'], label='Breach Flow')
        >>> ax1.set_ylabel('Flow (cfs)')
        >>> ax1.legend()
        >>>
        >>> # Breach width evolution
        >>> ax2.plot(df['datetime'], df['bottom_width'])
        >>> ax2.set_ylabel('Breach Width (ft)')
        >>> ax2.set_xlabel('Time')
        >>> plt.tight_layout()

        Notes
        -----
        - Only returns structures with breach capability
        - For non-breach SA/2D connections, use get_structure_variables()
        - NaN values in breach columns indicate breach not yet formed

        See Also
        --------
        get_structure_variables : Structure-level data only
        get_breaching_variables : Breach-specific data only
        """
        try:
            # Get structure variables (total flow, weir flow, hw, tw)
            struct_df = RasBreach.get_structure_variables(hdf_path, structure_name, ras_object=ras_object)

            # Get breaching variables (breach geometry and breach flow)
            breach_df = RasBreach.get_breaching_variables(hdf_path, structure_name, ras_object=ras_object)

            if struct_df.empty:
                logger.warning("No structure data available")
                return pd.DataFrame()

            if breach_df.empty:
                logger.warning("No breach data available, returning structure data only")
                return struct_df

            # Determine merge columns
            merge_cols = ['datetime']
            if 'structure' in struct_df.columns and 'structure' in breach_df.columns:
                merge_cols.append('structure')

            # Merge the two dataframes
            combined_df = pd.merge(
                struct_df,
                breach_df[['datetime', 'structure', 'bottom_width', 'bottom_elevation',
                          'left_slope', 'right_slope', 'breach_flow', 'breach_velocity',
                          'breach_flow_area']] if 'structure' in breach_df.columns
                        else breach_df[['datetime', 'bottom_width', 'bottom_elevation',
                                       'left_slope', 'right_slope', 'breach_flow',
                                       'breach_velocity', 'breach_flow_area']],
                on=merge_cols,
                how='left'  # Keep all structure timesteps, even if no breach data
            )

            # Reorder columns for better user experience
            col_order = ['datetime']
            if 'structure' in combined_df.columns:
                col_order.append('structure')
            col_order.extend(['total_flow', 'weir_flow', 'breach_flow', 'hw', 'tw',
                            'bottom_width', 'bottom_elevation', 'left_slope', 'right_slope',
                            'breach_velocity', 'breach_flow_area'])

            combined_df = combined_df[col_order]

            logger.info(f"Created combined breach timeseries with {len(combined_df)} rows")
            return combined_df

        except Exception as e:
            logger.error(f"Error creating combined breach timeseries: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_breach_summary(hdf_path: Path, structure_name: str = None,
                          ras_object=None) -> pd.DataFrame:
        """
        Extract breach summary statistics (peak values, timing, final geometry).

        Provides quick overview of breach performance without full time series.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        structure_name : str, optional
            Specific structure. If None, returns all breach structures.
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        pd.DataFrame
            Summary statistics with columns:
            - structure: Structure name
            - breach_initiated: Boolean, True if breach formed
            - breach_at_time: Time of breach initiation (days)
            - breach_at_date: Date/time of breach
            - max_total_flow: Maximum total flow (cfs)
            - max_total_flow_time: Time of max total flow
            - max_breach_flow: Maximum breach flow (cfs)
            - max_breach_flow_time: Time of max breach flow
            - final_breach_width: Final breach width (ft)
            - final_breach_depth: Final breach depth (ft)
            - max_hw: Maximum headwater elevation (ft)
            - max_tw: Maximum tailwater elevation (ft)

        Examples
        --------
        >>> summary = RasBreach.get_breach_summary("02")
        >>> print(summary[['structure', 'max_total_flow', 'final_breach_width']])

        Notes
        -----
        - Returns summary even if breach didn't fully form (NaN for incomplete data)
        - Times are pandas datetime objects
        - If only 1 timestep available, "max" values are that single value
        """
        try:
            # Get full timeseries
            ts_df = RasBreach.get_breach_timeseries(hdf_path, structure_name, ras_object=ras_object)

            if ts_df.empty:
                return pd.DataFrame()

            # Get breach info
            info_df = RasBreach.get_breach_info(hdf_path, ras_object=ras_object)

            # Determine grouping
            if 'structure' in ts_df.columns:
                structures = ts_df['structure'].unique()
            else:
                # Single structure, create pseudo-structure column
                structures = [structure_name] if structure_name else ['Unknown']
                ts_df['structure'] = structures[0]

            summary_list = []
            for struct in structures:
                struct_ts = ts_df[ts_df['structure'] == struct].copy()
                struct_info = info_df[info_df['structure'] == struct].iloc[0] if len(info_df) > 0 else {}

                # Calculate summary stats
                summary = {
                    'structure': struct,
                    'breach_initiated': struct_info.get('has_breach', False),
                    'breach_at_time': struct_info.get('breach_at_time', None),
                    'breach_at_date': struct_info.get('breach_at_date', None),
                }

                # Max flows and timing
                if 'total_flow' in struct_ts.columns:
                    max_total_idx = struct_ts['total_flow'].idxmax()
                    summary['max_total_flow'] = struct_ts.loc[max_total_idx, 'total_flow']
                    summary['max_total_flow_time'] = struct_ts.loc[max_total_idx, 'datetime']

                if 'breach_flow' in struct_ts.columns:
                    # Filter out NaN values
                    valid_breach = struct_ts[struct_ts['breach_flow'].notna()]
                    if len(valid_breach) > 0:
                        max_breach_idx = valid_breach['breach_flow'].idxmax()
                        summary['max_breach_flow'] = valid_breach.loc[max_breach_idx, 'breach_flow']
                        summary['max_breach_flow_time'] = valid_breach.loc[max_breach_idx, 'datetime']
                    else:
                        summary['max_breach_flow'] = np.nan
                        summary['max_breach_flow_time'] = None

                # Final breach geometry (last non-NaN value)
                if 'bottom_width' in struct_ts.columns:
                    valid_width = struct_ts[struct_ts['bottom_width'].notna()]
                    summary['final_breach_width'] = valid_width['bottom_width'].iloc[-1] if len(valid_width) > 0 else np.nan

                if 'bottom_elevation' in struct_ts.columns:
                    valid_elev = struct_ts[struct_ts['bottom_elevation'].notna()]
                    if len(valid_elev) > 0:
                        final_bottom = valid_elev['bottom_elevation'].iloc[-1]
                        # Calculate depth if we have HW
                        if 'hw' in struct_ts.columns:
                            final_hw = struct_ts['hw'].iloc[-1]
                            summary['final_breach_depth'] = final_hw - final_bottom
                        else:
                            summary['final_breach_depth'] = np.nan
                    else:
                        summary['final_breach_depth'] = np.nan

                # Max water levels
                if 'hw' in struct_ts.columns:
                    summary['max_hw'] = struct_ts['hw'].max()
                if 'tw' in struct_ts.columns:
                    summary['max_tw'] = struct_ts['tw'].max()

                summary_list.append(summary)

            result_df = pd.DataFrame(summary_list)
            logger.info(f"Generated breach summary for {len(structures)} structure(s)")
            return result_df

        except Exception as e:
            logger.error(f"Error generating breach summary: {e}")
            raise

    # ==========================================================================
    # PLAN FILE PARAMETER METHODS
    # ==========================================================================

    @dataclass
    class BreachLocation:
        """Represents the structured data encoded in the `Breach Loc` line."""
        river: str
        reach: str
        station: str
        is_active: bool
        structure: str

        @classmethod
        def from_value(cls, value: str) -> "RasBreach.BreachLocation":
            parts = value.split(",")
            if len(parts) < 5:
                raise ValueError(f"Unexpected Breach Loc format: '{value}'")
            river = parts[0].strip()
            reach = parts[1].strip()
            station = parts[2].strip()
            flag = parts[3].strip()
            structure = ",".join(parts[4:]).strip()
            return cls(
                river=river,
                reach=reach,
                station=station,
                is_active=flag.strip().lower() in {"true", "1", "yes"},
                structure=structure,
            )

    @dataclass
    class BreachBlock:
        """Structured representation of a breach block within a plan file."""
        start_index: int
        end_index: int
        order: List[Tuple[str, str]]
        values: Dict[str, str]
        table_rows: Dict[str, List[List[float]]]
        table_row_lengths: Dict[str, List[int]]

        # Numeric table keys
        NUMERIC_TABLE_KEYS = {
            "Breach Progression",
            "Simplified Physical Breach Downcutting",
            "Simplified Physical Breach Widening",
        }
        DEFAULT_VALUES_PER_ROW = 10
        FIXED_WIDTH = 8

        @property
        def location(self) -> "RasBreach.BreachLocation":
            return RasBreach.BreachLocation.from_value(self.values["Breach Loc"])

        @property
        def structure_name(self) -> str:
            return self.location.structure.strip()

        @property
        def is_active(self) -> bool:
            return self.location.is_active

        def to_dict(self) -> Dict:
            """Convert breach block to dictionary for easy inspection."""
            return {
                'structure_name': self.structure_name,
                'is_active': self.is_active,
                'river': self.location.river,
                'reach': self.location.reach,
                'station': self.location.station,
                'values': self.values.copy(),
                'table_rows': self.table_rows.copy(),
            }

        def to_lines(self) -> List[str]:
            """Serialize breach block back to plan file format."""
            lines: List[str] = []
            for kind, key in self.order:
                if kind == "line":
                    lines.append(f"{key}={self.values[key]}")
                elif kind == "table":
                    rows = self.table_rows.get(key, [])
                    if rows:
                        lines.extend(RasBreach._format_numeric_rows(rows, width=self.FIXED_WIDTH))
                elif kind == "blank":
                    lines.append("")
                elif kind == "literal":
                    lines.append(key)
            return lines

    @staticmethod
    @log_call
    @standardize_input(file_type='plan')
    def list_breach_structures_plan(plan_path: Path, ras_object=None) -> List[Dict]:
        """
        List all breach structures defined in plan file.

        Parameters
        ----------
        plan_path : Path
            Path to HEC-RAS plan file or plan number
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        List[Dict]
            List of dictionaries containing breach location information:
            - structure: Structure name
            - river: River name
            - reach: Reach name
            - station: River station
            - is_active: Boolean, True if breach is active

        Examples
        --------
        >>> structures = RasBreach.list_breach_structures_plan("02")
        >>> for struct in structures:
        ...     print(f"{struct['structure']}: Active={struct['is_active']}")

        Notes
        -----
        - Returns breach structures regardless of activation status
        - Use is_active field to filter for active breaches only
        """
        try:
            blocks = RasBreach._read_breach_blocks_internal(plan_path)
            locations = []
            for block in blocks:
                loc = block.location
                locations.append({
                    'structure': loc.structure,
                    'river': loc.river,
                    'reach': loc.reach,
                    'station': loc.station,
                    'is_active': loc.is_active
                })
            logger.info(f"Found {len(locations)} breach structures in {plan_path.name}")
            return locations
        except Exception as e:
            logger.error(f"Error listing breach structures: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan')
    def read_breach_block(plan_path: Path, structure_name: str, ras_object=None) -> Dict:
        """
        Read breach parameters for specified structure from plan file.

        Parameters
        ----------
        plan_path : Path
            Path to HEC-RAS plan file or plan number
        structure_name : str
            Name of breach structure to read
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        Dict
            Dictionary containing all breach parameters:
            - structure_name: Structure name
            - is_active: Boolean, breach activation status
            - river, reach, station: Location information
            - values: Dict of all breach parameter values
            - table_rows: Dict of numeric tables (progression, downcutting, etc.)

        Examples
        --------
        >>> breach_data = RasBreach.read_breach_block("02", "Laxton_Dam")
        >>> print(f"Active: {breach_data['is_active']}")
        >>> print(f"Method: {breach_data['values']['Breach Method']}")

        Raises
        ------
        ValueError
            If specified structure not found in plan file

        Notes
        -----
        - Use to_dict() method of BreachBlock for structured access
        - All values returned as strings; parse as needed
        """
        try:
            blocks = RasBreach._read_breach_blocks_internal(plan_path)
            block = RasBreach._find_block_by_structure(blocks, structure_name)

            if block is None:
                raise ValueError(f"Structure '{structure_name}' not found in {plan_path.name}")

            logger.info(f"Read breach block for {structure_name} from {plan_path.name}")
            return block.to_dict()

        except Exception as e:
            logger.error(f"Error reading breach block: {e}")
            raise

    @staticmethod
    @log_call
    @standardize_input(file_type='plan')
    def update_breach_block(
        plan_path: Path,
        structure_name: str,
        *,
        is_active: bool = None,
        method: int = None,
        geom_values: List = None,
        start_values: List = None,
        progression_mode: int = None,
        progression_pairs: List[Tuple[float, float]] = None,
        downcutting_pairs: List[Tuple[float, float]] = None,
        widening_pairs: List[Tuple[float, float]] = None,
        calculator_data: List = None,
        create_backup: bool = True,
        ras_object=None
    ) -> Dict:
        """
        Update breach parameters for specified structure in plan file.

        **CRITICAL**: Creates backup before modification. Uses CRLF line endings for HEC-RAS compatibility.

        Parameters
        ----------
        plan_path : Path
            Path to HEC-RAS plan file or plan number
        structure_name : str
            Name of breach structure to update
        is_active : bool, optional
            Set breach activation status (True/False)
        method : int, optional
            Breach calculation method (0-7)
        geom_values : List, optional
            Breach geometry values: [center_station, final_width, final_elev,
            left_slope, right_slope, weir_coef, formation_time]
        start_values : List, optional
            Breach starting conditions
        progression_mode : int, optional
            Progression mode (0=Linear, 1=Non-linear)
        progression_pairs : List[Tuple[float, float]], optional
            Time/breach fraction pairs for non-linear progression
        downcutting_pairs : List[Tuple[float, float]], optional
            Time/elevation pairs for physical breach downcutting
        widening_pairs : List[Tuple[float, float]], optional
            Time/width pairs for physical breach widening
        calculator_data : List, optional
            Breach calculator heuristic inputs
        create_backup : bool, default True
            Create backup file before modification
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        Dict
            Updated breach block as dictionary

        Examples
        --------
        >>> # Activate breach
        >>> RasBreach.update_breach_block("02", "Laxton_Dam", is_active=True)

        >>> # Set breach geometry
        >>> geom = [150, 100, 1400, 1, 1, 2.6, 0.5]  # center, width, elev, slopes, coef, time
        >>> RasBreach.update_breach_block("02", "Laxton_Dam", geom_values=geom)

        >>> # Set non-linear progression
        >>> progression = [(0, 0), (0.5, 0.3), (1.0, 1.0)]  # time, fraction pairs
        >>> RasBreach.update_breach_block("02", "Laxton_Dam",
        ...                               progression_mode=1,
        ...                               progression_pairs=progression)

        Raises
        ------
        ValueError
            If structure not found in plan file
        RuntimeError
            If CRLF line endings not preserved (HEC-RAS incompatibility)

        Warnings
        --------
        - Modifies plan file in-place
        - Backup created in same directory with timestamp
        - HEC-RAS must be closed before modification
        - Validates CRLF line endings after write

        Notes
        -----
        Based on TNTech Dam Breach Dashboard breach_io.py implementation.
        Adapted to ras-commander conventions with decorators and plan-number support.
        """
        try:
            # Read all breach blocks
            lines = plan_path.read_text().splitlines()
            blocks = RasBreach._parse_breach_blocks(lines)
            block = RasBreach._find_block_by_structure(blocks, structure_name)

            if block is None:
                raise ValueError(f"Structure '{structure_name}' not found in {plan_path.name}")

            # Apply updates
            if is_active is not None:
                RasBreach._set_activation(block, is_active)
            if method is not None:
                block.values["Breach Method"] = f" {int(method)}"
            if geom_values is not None:
                block.values["Breach Geom"] = RasBreach._format_csv(geom_values)
            if start_values is not None:
                block.values["Breach Start"] = RasBreach._format_csv(start_values)
            if progression_mode is not None or progression_pairs is not None:
                mode = progression_mode if progression_mode is not None else int(block.values["Breach Progression"].strip())
                RasBreach._set_progression(block, mode, progression_pairs)
            if downcutting_pairs is not None:
                RasBreach._set_table_pairs(block, "Simplified Physical Breach Downcutting", downcutting_pairs)
            if widening_pairs is not None:
                RasBreach._set_table_pairs(block, "Simplified Physical Breach Widening", widening_pairs)
            if calculator_data is not None:
                block.values["Breach Calculator Data"] = RasBreach._format_csv(calculator_data)

            # Replace block lines in file
            new_block_lines = block.to_lines()
            lines[block.start_index:block.end_index] = new_block_lines
            block.end_index = block.start_index + len(new_block_lines)

            # Create backup
            if create_backup:
                RasBreach._create_backup(plan_path)

            # Write with CRLF line endings (CRITICAL for HEC-RAS)
            if lines and not lines[-1].endswith("\n"):
                output = "\r\n".join(lines) + "\r\n"
            else:
                output = "\r\n".join(lines)

            # Use open() with newline='' to preserve CRLF
            with open(plan_path, 'w', encoding='utf-8', newline='') as f:
                f.write(output)

            # Validate CRLF preservation
            if not RasBreach._validate_crlf(plan_path):
                raise RuntimeError(
                    f"CRITICAL: Failed to preserve CRLF line endings in {plan_path}. "
                    "HEC-RAS will not be able to open this project."
                )

            logger.info(f"Updated breach block for {structure_name} in {plan_path.name}")
            return block.to_dict()

        except Exception as e:
            logger.error(f"Error updating breach block: {e}")
            raise

    # ==========================================================================
    # INTERNAL HELPER METHODS
    # ==========================================================================

    @staticmethod
    def _read_breach_blocks_internal(plan_path: Path) -> List["RasBreach.BreachBlock"]:
        """Internal method to read and parse breach blocks from plan file."""
        lines = plan_path.read_text().splitlines()
        return RasBreach._parse_breach_blocks(lines)

    @staticmethod
    def _parse_breach_blocks(lines: List[str]) -> List["RasBreach.BreachBlock"]:
        """Parse all breach blocks from plan file lines."""
        blocks: List[RasBreach.BreachBlock] = []
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            if line.startswith("Breach Loc="):
                start_idx = idx
                block_lines = [line]
                idx += 1
                while idx < len(lines):
                    candidate = lines[idx]
                    if candidate.startswith("Breach Loc=") and block_lines:
                        break
                    block_lines.append(candidate)
                    idx += 1
                end_idx = start_idx + len(block_lines)
                block = RasBreach._parse_block(block_lines, start_idx, end_idx)
                blocks.append(block)
            else:
                idx += 1
        return blocks

    @staticmethod
    def _parse_block(block_lines: List[str], start_index: int, end_index: int) -> "RasBreach.BreachBlock":
        """Parse single breach block from lines."""
        values: Dict[str, str] = {}
        table_rows: Dict[str, List[List[float]]] = {}
        order: List[Tuple[str, str]] = []
        current_table_key: Optional[str] = None

        for line in block_lines:
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.rstrip()
                values[key] = value
                order.append(("line", key))
                if key in RasBreach.BreachBlock.NUMERIC_TABLE_KEYS:
                    order.append(("table", key))
                    current_table_key = key
                    table_rows.setdefault(key, [])
                else:
                    current_table_key = None
            else:
                if current_table_key:
                    stripped = line.strip()
                    if stripped:
                        numeric_row = [float(part) for part in stripped.split()]
                        table_rows.setdefault(current_table_key, []).append(numeric_row)
                else:
                    if line.strip() == "":
                        order.append(("blank", ""))
                    else:
                        order.append(("literal", line))

        table_row_lengths = {key: [len(row) for row in rows] for key, rows in table_rows.items()}
        return RasBreach.BreachBlock(
            start_index=start_index,
            end_index=end_index,
            order=order,
            values=values,
            table_rows=table_rows,
            table_row_lengths=table_row_lengths,
        )

    @staticmethod
    def _find_block_by_structure(blocks: List["RasBreach.BreachBlock"], structure_name: str) -> Optional["RasBreach.BreachBlock"]:
        """Find breach block by structure name (case-insensitive)."""
        target = structure_name.strip().lower()
        for block in blocks:
            if block.structure_name.lower() == target:
                return block
        return None

    @staticmethod
    def _set_activation(block: "RasBreach.BreachBlock", is_active: bool) -> None:
        """Set breach activation status."""
        loc = block.location
        loc.is_active = bool(is_active)
        river = (loc.river or "").rjust(16)
        reach = (loc.reach or "").rjust(16)
        station = (loc.station or "").rjust(8)
        flag = "True" if loc.is_active else "False"
        structure = (loc.structure or "").ljust(16)
        block.values["Breach Loc"] = f"{river},{reach},{station},{flag},{structure}"

    @staticmethod
    def _set_progression(block: "RasBreach.BreachBlock", mode: int, pairs: Optional[List[Tuple[float, float]]]) -> None:
        """Set breach progression mode and pairs."""
        block.values["Breach Progression"] = f" {int(mode)}"
        if pairs is not None:
            flat_values: List[float] = []
            for pair in pairs:
                if len(pair) != 2:
                    raise ValueError("Progression pairs must contain exactly two values")
                flat_values.extend([float(pair[0]), float(pair[1])])
            RasBreach._set_table_values(block, "Breach Progression", flat_values)

    @staticmethod
    def _set_table_pairs(block: "RasBreach.BreachBlock", key: str, pairs: List[Tuple[float, float]]) -> None:
        """Set table values from time/value pairs."""
        flat_values: List[float] = []
        for pair in pairs:
            if len(pair) != 2:
                raise ValueError(f"{key} pairs must contain exactly two values")
            flat_values.extend([float(pair[0]), float(pair[1])])
        RasBreach._set_table_values(block, key, flat_values)

    @staticmethod
    def _set_table_values(block: "RasBreach.BreachBlock", key: str, values: List[float]) -> None:
        """Set numeric table values for breach block."""
        lengths = block.table_row_lengths.get(key)
        if lengths and sum(lengths) == len(values):
            rows: List[List[float]] = []
            index = 0
            for length in lengths:
                rows.append(list(values[index:index + length]))
                index += length
        else:
            rows = []
            chunk = RasBreach.BreachBlock.DEFAULT_VALUES_PER_ROW
            for index in range(0, len(values), chunk):
                rows.append(list(values[index:index + chunk]))

        block.table_rows[key] = rows
        block.table_row_lengths[key] = [len(row) for row in rows]

    @staticmethod
    def _format_numeric_rows(rows: List[List[float]], width: int) -> List[str]:
        """Format numeric table rows for plan file."""
        formatted: List[str] = []
        for row in rows:
            formatted.append("".join(RasBreach._format_numeric_value(value, width=width) for value in row))
        return formatted

    @staticmethod
    def _format_numeric_value(value: float, width: int) -> str:
        """Format single numeric value with fixed width."""
        numeric = float(value)
        if numeric == 0:
            text = "0"
        elif abs(numeric) >= 10000 or (0 < abs(numeric) < 1e-4):
            text = f"{numeric:.3e}"
        else:
            text = f"{numeric:.6g}"
        if len(text) > width:
            text = f"{numeric:.6e}"
        if len(text) > width:
            text = text[:width]
        return text.rjust(width)

    @staticmethod
    def _format_csv(values: List) -> str:
        """Format values as comma-separated string."""
        formatted: List[str] = []
        for item in values:
            if item is None:
                formatted.append("")
            elif isinstance(item, bool):
                formatted.append("True" if item else "False")
            elif isinstance(item, (int, float)):
                formatted.append(str(item))
            else:
                formatted.append(str(item))
        return ",".join(formatted)

    @staticmethod
    def _create_backup(plan_path: Path) -> None:
        """Create timestamped backup of plan file."""
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = plan_path.parent / f"{plan_path.stem}_backup_{timestamp}{plan_path.suffix}"
        backup_path.write_text(plan_path.read_text())
        logger.info(f"Created backup: {backup_path.name}")

    @staticmethod
    def _validate_crlf(plan_path: Path) -> bool:
        """Validate that file has CRLF line endings."""
        content = plan_path.read_bytes()
        # Check if file contains \r\n (CRLF)
        return b'\r\n' in content
