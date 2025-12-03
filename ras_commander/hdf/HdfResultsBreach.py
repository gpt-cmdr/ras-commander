"""
HdfResultsBreach: Dam breach results extraction from HEC-RAS HDF files.

This module provides methods for extracting breach results from HDF output files,
including time series data, summary statistics, and breach geometry evolution.

Architectural Note:
    - HdfResultsBreach: Breach RESULTS from HDF files (.p##.hdf)
    - RasBreach: Breach PARAMETERS from plan files (.p##)
    - HdfStruc: Structure data from HDF files (non-breach specific)

This class focuses exclusively on HDF results extraction. For reading/writing breach
parameters in plan files, use RasBreach class.

Classes:
    HdfResultsBreach: Static methods for breach results extraction

Key Methods:
    - get_structure_variables(): Extract structure flow variables (Total Flow, HW, TW)
    - get_breaching_variables(): Extract breach geometry progression
    - get_breach_timeseries(): Combined breach + structure time series (primary method)
    - get_breach_summary(): Summary statistics (peaks, timing, final geometry)

Examples:
    >>> from ras_commander import HdfResultsBreach
    >>>
    >>> # Extract complete breach time series
    >>> df = HdfResultsBreach.get_breach_timeseries("02", "Laxton_Dam")
    >>>
    >>> # Get summary statistics
    >>> summary = HdfResultsBreach.get_breach_summary("02")
    >>>
    >>> # Plot breach evolution
    >>> import matplotlib.pyplot as plt
    >>> plt.plot(df['datetime'], df['bottom_width'])
    >>> plt.ylabel('Breach Width (ft)')

Author: ras-commander development team
Date: 2025
"""

from typing import Union, Optional
from pathlib import Path
import h5py
import pandas as pd
import numpy as np

from ..Decorators import standardize_input, log_call
from .HdfBase import HdfBase
from ..LoggingConfig import get_logger
from ..RasPrj import ras

logger = get_logger(__name__)


class HdfResultsBreach:
    """
    Handles dam breach results extraction from HEC-RAS HDF files.

    This class provides comprehensive breach results extraction including:
    - Time series data (flow, water levels, breach geometry)
    - Summary statistics (peak values, timing)
    - Structure-level flow variables

    All methods are static and designed for plan-number-based access
    via the @standardize_input decorator.

    Architectural Note:
        - Use HdfResultsBreach for extracting breach RESULTS from HDF files
        - Use RasBreach for reading/writing breach PARAMETERS in plan files
        - Use HdfStruc for structure listings and metadata
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_structure_variables(hdf_path: Path, structure_name: str = None, *,
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
        >>> df = HdfResultsBreach.get_structure_variables("02")

        >>> # Get specific structure
        >>> df = HdfResultsBreach.get_structure_variables("02", "Laxton_Dam")

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
                    from .HdfStruc import HdfStruc
                    structures = HdfStruc.list_sa2d_connections(hdf_path, ras_object=ras_object)

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
    def get_breaching_variables(hdf_path: Path, structure_name: str = None, *,
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
        >>> df = HdfResultsBreach.get_breaching_variables("02", "Laxton_Dam")

        >>> # Plot breach width evolution
        >>> import matplotlib.pyplot as plt
        >>> plt.plot(df['datetime'], df['bottom_width'])
        >>> plt.ylabel('Breach Width (ft)')

        >>> # Get all breach structures
        >>> df = HdfResultsBreach.get_breaching_variables("02")

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
                from .HdfStruc import HdfStruc
                breach_info = HdfStruc.get_sa2d_breach_info(hdf_path, ras_object=ras_object)
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
    def get_breach_timeseries(hdf_path: Path, structure_name: str = None, *,
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
        >>> df = HdfResultsBreach.get_breach_timeseries("02")

        >>> # Get specific dam
        >>> df = HdfResultsBreach.get_breach_timeseries("02", "Laxton_Dam")

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
            struct_df = HdfResultsBreach.get_structure_variables(hdf_path, structure_name, ras_object=ras_object)

            # Get breaching variables (breach geometry and breach flow)
            breach_df = HdfResultsBreach.get_breaching_variables(hdf_path, structure_name, ras_object=ras_object)

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
    def get_breach_summary(hdf_path: Path, structure_name: str = None, *,
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
        >>> summary = HdfResultsBreach.get_breach_summary("02")
        >>> print(summary[['structure', 'max_total_flow', 'final_breach_width']])

        Notes
        -----
        - Returns summary even if breach didn't fully form (NaN for incomplete data)
        - Times are pandas datetime objects
        - If only 1 timestep available, "max" values are that single value
        """
        try:
            # Get full timeseries
            ts_df = HdfResultsBreach.get_breach_timeseries(hdf_path, structure_name, ras_object=ras_object)

            if ts_df.empty:
                return pd.DataFrame()

            # Get breach info
            from .HdfStruc import HdfStruc
            info_df = HdfStruc.get_sa2d_breach_info(hdf_path, ras_object=ras_object)

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
