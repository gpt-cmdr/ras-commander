"""
Initial condition management for HEC-RAS unsteady flow files.

This module provides functions to parse, create, and update initial condition
entries in HEC-RAS unsteady flow files (.u##) using USGS gauge data.

Initial Condition Types:
- Initial Flow Loc: Set flow at 1D cross-section
- Initial Storage Elev: Set water surface elevation in storage/2D flow areas
- Initial RRR Elev: Set elevation for Rainfall-Runoff-Routing areas

Functions:
- parse_initial_conditions() - Read IC entries from unsteady file
- write_initial_conditions() - Write/update IC entries in unsteady file
- get_ic_value_from_usgs() - Retrieve IC value from USGS gauge at target time
- create_ic_line() - Format IC line string for file writing
"""

from pathlib import Path
from typing import Union, Optional, Any, Dict, List, Tuple
from datetime import datetime, timedelta
import pandas as pd

from ..LoggingConfig import get_logger
from ..Decorators import log_call


logger = get_logger(__name__)


class InitialConditions:
    """
    Static class for managing HEC-RAS initial conditions from USGS gauge data.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    @log_call
    def parse_initial_conditions(unsteady_file: Union[str, Path]) -> pd.DataFrame:
        """
        Parse initial condition entries from HEC-RAS unsteady flow file.

        Reads all three types of initial condition lines:
        - Initial Flow Loc=River,Reach,Station,Flow
        - Initial Storage Elev=AreaName,Elevation
        - Initial RRR Elev=River,Reach,Station,Elevation

        Parameters
        ----------
        unsteady_file : str or Path
            Path to HEC-RAS unsteady flow file (.u##)

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: type, river, reach, station, value, area_name
            - type: 'flow', 'storage', or 'rrr'
            - river: River name (for flow and rrr types)
            - reach: Reach name (for flow and rrr types)
            - station: River station (for flow and rrr types)
            - value: Flow value (cfs/cms) or elevation (ft/m)
            - area_name: Storage/2D area name or ID (for storage type)

        Examples
        --------
        >>> from ras_commander.usgs import InitialConditions
        >>> ic_df = InitialConditions.parse_initial_conditions('BaldEagle.u07')
        >>> print(ic_df)
           type           river        reach  station   value area_name
        0  flow  Bald Eagle Cr.  Lock Haven  137520.0   730.0      None
        1  flow  Bald Eagle Cr.  Lock Haven   81914.0  1000.0      None
        2  storage           None        None      NaN   559.7       193
        """
        unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        ic_entries = []

        try:
            with open(unsteady_path, 'r') as f:
                for line in f:
                    line = line.rstrip('\n')

                    # Parse Initial Flow Loc entries
                    if line.startswith('Initial Flow Loc='):
                        content = line.split('=', 1)[1]
                        parts = [p.strip() for p in content.split(',')]

                        if len(parts) >= 4:
                            ic_entries.append({
                                'type': 'flow',
                                'river': parts[0],
                                'reach': parts[1],
                                'station': float(parts[2]),
                                'value': float(parts[3]),
                                'area_name': None
                            })

                    # Parse Initial Storage Elev entries
                    elif line.startswith('Initial Storage Elev='):
                        content = line.split('=', 1)[1]
                        parts = [p.strip() for p in content.split(',')]

                        if len(parts) >= 2:
                            ic_entries.append({
                                'type': 'storage',
                                'river': None,
                                'reach': None,
                                'station': None,
                                'value': float(parts[1]),
                                'area_name': parts[0]
                            })

                    # Parse Initial RRR Elev entries
                    elif line.startswith('Initial RRR Elev='):
                        content = line.split('=', 1)[1]
                        parts = [p.strip() for p in content.split(',')]

                        if len(parts) >= 4:
                            ic_entries.append({
                                'type': 'rrr',
                                'river': parts[0],
                                'reach': parts[1],
                                'station': float(parts[2]),
                                'value': float(parts[3]),
                                'area_name': None
                            })

                    # Stop parsing after we reach boundary locations
                    elif line.startswith('Boundary Location='):
                        break

            logger.info(f"Parsed {len(ic_entries)} initial condition entries from {unsteady_path.name}")

        except PermissionError:
            logger.error(f"Permission denied reading unsteady file: {unsteady_path}")
            raise PermissionError(f"Permission denied reading unsteady file: {unsteady_path}")
        except Exception as e:
            logger.error(f"Error parsing initial conditions from {unsteady_path}: {str(e)}")
            raise

        return pd.DataFrame(ic_entries)

    @staticmethod
    @log_call
    def create_ic_line(
        ic_type: str,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        station: Optional[float] = None,
        value: Optional[float] = None,
        area_name: Optional[str] = None
    ) -> str:
        """
        Create a properly formatted initial condition line for HEC-RAS file.

        Parameters
        ----------
        ic_type : str
            Type of IC: 'flow', 'storage', or 'rrr'
        river : str, optional
            River name (required for 'flow' and 'rrr' types)
        reach : str, optional
            Reach name (required for 'flow' and 'rrr' types)
        station : float, optional
            River station (required for 'flow' and 'rrr' types)
        value : float, optional
            Flow (cfs/cms) or elevation (ft/m) value
        area_name : str, optional
            Storage/2D area name or ID (required for 'storage' type)

        Returns
        -------
        str
            Formatted IC line string ready to write to file

        Raises
        ------
        ValueError
            If required parameters are missing for the specified IC type

        Examples
        --------
        >>> line = InitialConditions.create_ic_line(
        ...     ic_type='flow',
        ...     river='Bald Eagle Cr.',
        ...     reach='Lock Haven',
        ...     station=137520,
        ...     value=730
        ... )
        >>> print(line)
        Initial Flow Loc=Bald Eagle Cr.  ,Lock Haven      ,137520  ,730

        >>> line = InitialConditions.create_ic_line(
        ...     ic_type='storage',
        ...     area_name='193',
        ...     value=559.7
        ... )
        >>> print(line)
        Initial Storage Elev=193             ,559.7
        """
        ic_type = ic_type.lower()

        if ic_type == 'flow':
            if river is None or reach is None or station is None or value is None:
                raise ValueError("flow IC requires river, reach, station, and value")

            # Format with fixed-width fields (17 chars for strings, variable for numbers)
            river_str = f"{river:<17}"
            reach_str = f"{reach:<17}"
            station_str = f"{station:<8.0f}"
            value_str = str(value)

            return f"Initial Flow Loc={river_str},{reach_str},{station_str},{value_str}"

        elif ic_type == 'storage':
            if area_name is None or value is None:
                raise ValueError("storage IC requires area_name and value")

            # Format with fixed-width field for area name
            area_str = f"{area_name:<17}"
            value_str = str(value)

            return f"Initial Storage Elev={area_str},{value_str}"

        elif ic_type == 'rrr':
            if river is None or reach is None or station is None or value is None:
                raise ValueError("rrr IC requires river, reach, station, and value")

            # Format with fixed-width fields
            river_str = f"{river:<17}"
            reach_str = f"{reach:<17}"
            station_str = f"{station:<8.0f}"
            value_str = str(value)

            return f"Initial RRR Elev={river_str},{reach_str},{station_str},{value_str}"

        else:
            raise ValueError(f"Unknown IC type: {ic_type}. Must be 'flow', 'storage', or 'rrr'")

    @staticmethod
    @log_call
    def write_initial_conditions(
        unsteady_file: Union[str, Path],
        ic_entries: List[Dict[str, Any]]
    ) -> None:
        """
        Write or update initial condition entries in HEC-RAS unsteady flow file.

        IC entries are inserted after file headers (Flow Title, Program Version, Use Restart)
        and before Boundary Location entries. Existing IC entries are removed and replaced.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to HEC-RAS unsteady flow file (.u##)
        ic_entries : list of dict
            List of IC entry dictionaries with keys:
            - type: 'flow', 'storage', or 'rrr'
            - river: River name (for flow/rrr)
            - reach: Reach name (for flow/rrr)
            - station: River station (for flow/rrr)
            - value: Flow or elevation value
            - area_name: Storage/2D area name (for storage)

        Returns
        -------
        None
            Modifies the unsteady file in-place

        Examples
        --------
        >>> ic_entries = [
        ...     {
        ...         'type': 'flow',
        ...         'river': 'Bald Eagle Cr.',
        ...         'reach': 'Lock Haven',
        ...         'station': 137520,
        ...         'value': 730
        ...     },
        ...     {
        ...         'type': 'storage',
        ...         'area_name': '193',
        ...         'value': 559.7
        ...     }
        ... ]
        >>> InitialConditions.write_initial_conditions('BaldEagle.u07', ic_entries)
        """
        unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        try:
            # Read existing file
            with open(unsteady_path, 'r') as f:
                lines = f.readlines()

            # Find insertion point (after headers, before Boundary Location)
            header_end_idx = None
            boundary_start_idx = None

            for i, line in enumerate(lines):
                if line.startswith('Use Restart='):
                    header_end_idx = i + 1
                elif line.startswith('Boundary Location='):
                    boundary_start_idx = i
                    break

            if header_end_idx is None:
                logger.warning("Could not find 'Use Restart=' line, inserting after Program Version")
                for i, line in enumerate(lines):
                    if line.startswith('Program Version='):
                        header_end_idx = i + 1
                        break

            if header_end_idx is None:
                logger.error("Could not find insertion point for IC entries")
                raise ValueError("Invalid unsteady file format: missing header lines")

            # Remove existing IC lines
            new_lines = []
            for i, line in enumerate(lines):
                if i < header_end_idx:
                    new_lines.append(line)
                elif not (line.startswith('Initial Flow Loc=') or
                         line.startswith('Initial Storage Elev=') or
                         line.startswith('Initial RRR Elev=')):
                    new_lines.append(line)

            # Generate new IC lines
            ic_lines = []
            for entry in ic_entries:
                ic_line = InitialConditions.create_ic_line(
                    ic_type=entry['type'],
                    river=entry.get('river'),
                    reach=entry.get('reach'),
                    station=entry.get('station'),
                    value=entry.get('value'),
                    area_name=entry.get('area_name')
                )
                ic_lines.append(ic_line + '\n')

            # Insert IC lines at correct position
            final_lines = new_lines[:header_end_idx] + ic_lines + new_lines[header_end_idx:]

            # Write modified file
            with open(unsteady_path, 'w') as f:
                f.writelines(final_lines)

            logger.info(f"Wrote {len(ic_entries)} initial condition entries to {unsteady_path.name}")

        except PermissionError:
            logger.error(f"Permission denied writing to unsteady file: {unsteady_path}")
            raise PermissionError(f"Permission denied writing to unsteady file: {unsteady_path}")
        except Exception as e:
            logger.error(f"Error writing initial conditions to {unsteady_path}: {str(e)}")
            raise

    @staticmethod
    @log_call
    def get_ic_value_from_usgs(
        site_id: str,
        target_datetime: Union[str, datetime],
        parameter: str = 'flow',
        tolerance_hours: int = 1
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Retrieve initial condition value from USGS gauge at specified time.

        Queries USGS waterdata API for the nearest value to the target datetime
        within the specified tolerance window.

        Parameters
        ----------
        site_id : str
            USGS site ID (e.g., 'USGS-01646500' or '01646500')
        target_datetime : str or datetime
            Target datetime for IC value (ISO format string or datetime object)
        parameter : str, default 'flow'
            Parameter to retrieve: 'flow' (00060) or 'stage' (00065)
        tolerance_hours : int, default 1
            Maximum time offset (hours) for nearest value search

        Returns
        -------
        tuple
            (value, metadata_dict) where:
            - value: float, the retrieved flow (cfs) or stage (ft) value
            - metadata: dict with keys:
                - actual_time: datetime of the retrieved value
                - time_offset_minutes: float, offset from target time
                - approval_status: str, data quality indicator
                - unit_of_measure: str, units of the value
                - source_url: str, USGS API URL

        Raises
        ------
        ValueError
            If no data available within tolerance window
        ImportError
            If dataretrieval package is not installed

        Examples
        --------
        >>> value, metadata = InitialConditions.get_ic_value_from_usgs(
        ...     site_id='01646500',
        ...     target_datetime='2024-06-15T00:00:00',
        ...     parameter='flow'
        ... )
        >>> print(f"Flow: {value:.1f} {metadata['unit_of_measure']}")
        Flow: 1250.0 ft3/s
        >>> print(f"Offset: {metadata['time_offset_minutes']:.1f} minutes")
        Offset: 15.0 minutes

        Notes
        -----
        Requires the 'dataretrieval' package: pip install dataretrieval
        """
        try:
            from dataretrieval import nwis
        except ImportError:
            logger.error("dataretrieval package not installed. Install with: pip install dataretrieval")
            raise ImportError("dataretrieval package required. Install with: pip install dataretrieval")

        # Parse target datetime
        if isinstance(target_datetime, str):
            target_dt = pd.to_datetime(target_datetime)
        else:
            target_dt = target_datetime

        # Create time window
        start_time = target_dt - timedelta(hours=tolerance_hours)
        end_time = target_dt + timedelta(hours=tolerance_hours)

        # Get parameter code
        param_code = '00060' if parameter.lower() == 'flow' else '00065'

        # Clean site ID (remove 'USGS-' prefix if present)
        site_id_clean = site_id.replace('USGS-', '').replace('usgs-', '')

        logger.info(f"Querying USGS site {site_id_clean} for {parameter} at {target_dt}")

        try:
            # Query USGS
            df = nwis.get_iv(
                sites=site_id_clean,
                parameterCd=param_code,
                start=start_time.strftime('%Y-%m-%d'),
                end=end_time.strftime('%Y-%m-%d')
            )

            if df[0].empty:
                raise ValueError(
                    f"No {parameter} data available for site {site_id_clean} "
                    f"between {start_time} and {end_time}"
                )

            data_df = df[0]

            # Find nearest value to target time
            # Instantaneous values have datetime index
            data_df['time_diff'] = abs(data_df.index - target_dt)
            nearest_idx = data_df['time_diff'].idxmin()
            nearest_row = data_df.loc[nearest_idx]

            # Get the value column (format: site_no_param_cd_statCd)
            value_col = [col for col in data_df.columns if col.startswith(f'{site_id_clean}_{param_code}')][0]
            value = float(nearest_row[value_col])

            # Build metadata
            metadata = {
                'actual_time': nearest_idx,
                'time_offset_minutes': nearest_row['time_diff'].total_seconds() / 60,
                'approval_status': 'Unknown',  # IV data doesn't include this
                'unit_of_measure': 'ft3/s' if parameter.lower() == 'flow' else 'ft',
                'source_url': f'https://waterdata.usgs.gov/nwis/iv?site_no={site_id_clean}'
            }

            logger.info(
                f"Retrieved {parameter} value {value:.2f} {metadata['unit_of_measure']} "
                f"with {abs(metadata['time_offset_minutes']):.1f} minute offset"
            )

            return value, metadata

        except Exception as e:
            logger.error(f"Error querying USGS site {site_id_clean}: {str(e)}")
            raise
