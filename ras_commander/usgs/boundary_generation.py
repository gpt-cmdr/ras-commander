"""
Boundary condition generation for HEC-RAS from USGS gauge data.

This module provides functions to generate HEC-RAS boundary condition tables
(Flow Hydrograph, Stage Hydrograph) from USGS time series data and update
unsteady flow files with the generated tables.

Functions:
- format_fixed_width_values() - Format values to HEC-RAS fixed-width format
- generate_flow_hydrograph_table() - Create Flow Hydrograph table string
- generate_stage_hydrograph_table() - Create Stage Hydrograph table string
- update_boundary_hydrograph() - Replace BC table in unsteady file
"""

from pathlib import Path
from typing import Union, List, Optional, Any
import numpy as np
import pandas as pd

from ..LoggingConfig import get_logger
from ..Decorators import log_call


logger = get_logger(__name__)


class BoundaryGenerator:
    """
    Static class for generating and updating HEC-RAS boundary condition tables
    from USGS gauge data.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    def format_fixed_width_values(
        values: Union[List[float], np.ndarray, pd.Series],
        width: int = 8,
        decimals: int = 2,
        values_per_line: int = 10
    ) -> str:
        """
        Format numeric values into HEC-RAS fixed-width table format.

        HEC-RAS uses a fixed-width format for boundary condition tables:
        - Each value occupies exactly 8 characters
        - Values are right-justified with 2 decimal places
        - 10 values per line (80 characters total)

        Parameters
        ----------
        values : list, np.ndarray, or pd.Series
            Numeric values to format
        width : int, default 8
            Character width per value (HEC-RAS standard is 8)
        decimals : int, default 2
            Number of decimal places (HEC-RAS standard is 2)
        values_per_line : int, default 10
            Number of values per line (HEC-RAS standard is 10)

        Returns
        -------
        str
            Formatted string with newlines, ready to write to file

        Examples
        --------
        >>> values = [1500.0, 1520.5, 1580.25, 1650.0]
        >>> formatted = BoundaryGenerator.format_fixed_width_values(values)
        >>> print(formatted)
         1500.00 1520.50 1580.25 1650.00

        >>> # Full hydrograph with 168 values (1 week hourly)
        >>> flows = np.linspace(100, 5000, 168)
        >>> table = BoundaryGenerator.format_fixed_width_values(flows)
        """
        # Convert to numpy array for consistent handling
        if isinstance(values, pd.Series):
            values = values.values
        elif isinstance(values, list):
            values = np.array(values)

        # Build formatted lines
        lines = []
        for i in range(0, len(values), values_per_line):
            chunk = values[i:i+values_per_line]
            # Format each value: right-justified, fixed width, fixed decimals
            line = ''.join(f'{v:>{width}.{decimals}f}' for v in chunk)
            lines.append(line)

        return '\n'.join(lines)

    @staticmethod
    @log_call
    def generate_flow_hydrograph_table(
        flow_values: Union[List[float], np.ndarray, pd.Series],
        interval: str = '1HOUR'
    ) -> str:
        """
        Generate a complete Flow Hydrograph table for HEC-RAS unsteady file.

        Creates a formatted string containing the interval, table header,
        and flow values in the fixed-width format required by HEC-RAS.

        Parameters
        ----------
        flow_values : list, np.ndarray, or pd.Series
            Flow values in cfs (or model units)
        interval : str, default '1HOUR'
            Time interval for the hydrograph. Valid values:
            '1MIN', '5MIN', '10MIN', '15MIN', '30MIN',
            '1HOUR', '2HOUR', '3HOUR', '4HOUR', '6HOUR', '8HOUR', '12HOUR', '1DAY'

        Returns
        -------
        str
            Complete Flow Hydrograph section formatted for .u## file:
            ```
            Interval=1HOUR
            Flow Hydrograph= 168
              1500.00  1520.00  1580.00  1650.00  1750.00  1890.00  2100.00  2350.00  2650.00  3000.00
              3400.00  3850.00  4350.00  4900.00  5500.00  6100.00  6700.00  7200.00  7600.00  7900.00
              ...
            ```

        Examples
        --------
        >>> import numpy as np
        >>> # Generate 7-day hourly hydrograph
        >>> flows = np.linspace(1500, 8000, 168)
        >>> table = BoundaryGenerator.generate_flow_hydrograph_table(flows, interval='1HOUR')
        >>>
        >>> # Use with USGS data
        >>> usgs_df = retrieve_flow_data('USGS-01646500', '2024-06-01', '2024-06-08')
        >>> table = BoundaryGenerator.generate_flow_hydrograph_table(
        ...     usgs_df['value'].values,
        ...     interval='15MIN'
        ... )

        Notes
        -----
        The generated table string can be directly inserted into an unsteady flow
        file or passed to update_boundary_hydrograph().
        """
        # Convert to array for length
        if isinstance(flow_values, pd.Series):
            flow_values = flow_values.values
        elif isinstance(flow_values, list):
            flow_values = np.array(flow_values)

        num_values = len(flow_values)

        # Build header
        lines = [
            f"Interval={interval}",
            f"Flow Hydrograph= {num_values}"
        ]

        # Format values using fixed-width formatter
        formatted_values = BoundaryGenerator.format_fixed_width_values(flow_values)
        lines.append(formatted_values)

        result = '\n'.join(lines)

        logger.info(f"Generated Flow Hydrograph table: {num_values} values, interval={interval}")
        logger.debug(f"Flow range: {flow_values.min():.2f} - {flow_values.max():.2f}")

        return result

    @staticmethod
    @log_call
    def generate_stage_hydrograph_table(
        stage_values: Union[List[float], np.ndarray, pd.Series],
        interval: str = '15MIN'
    ) -> str:
        """
        Generate a complete Stage Hydrograph table for HEC-RAS unsteady file.

        Creates a formatted string containing the interval, table header,
        and stage values in the fixed-width format required by HEC-RAS.

        Parameters
        ----------
        stage_values : list, np.ndarray, or pd.Series
            Stage values in feet (or model units)
        interval : str, default '15MIN'
            Time interval for the hydrograph. Valid values:
            '1MIN', '5MIN', '10MIN', '15MIN', '30MIN',
            '1HOUR', '2HOUR', '3HOUR', '4HOUR', '6HOUR', '8HOUR', '12HOUR', '1DAY'

        Returns
        -------
        str
            Complete Stage Hydrograph section formatted for .u## file:
            ```
            Interval=15MIN
            Stage Hydrograph= 672
               10.50   10.52   10.55   10.60   10.68   10.78   10.92   11.10   11.32   11.58
               ...
            ```

        Examples
        --------
        >>> # Generate stage hydrograph from USGS data
        >>> usgs_df = retrieve_stage_data('USGS-01647000', '2024-06-01', '2024-06-08')
        >>> table = BoundaryGenerator.generate_stage_hydrograph_table(
        ...     usgs_df['value'].values,
        ...     interval='15MIN'
        ... )
        >>>
        >>> # Generate from list
        >>> stages = [10.5, 10.52, 10.55, 10.60, 10.68]
        >>> table = BoundaryGenerator.generate_stage_hydrograph_table(stages, interval='1HOUR')

        Notes
        -----
        The generated table string can be directly inserted into an unsteady flow
        file or passed to update_boundary_hydrograph().
        """
        # Convert to array for length
        if isinstance(stage_values, pd.Series):
            stage_values = stage_values.values
        elif isinstance(stage_values, list):
            stage_values = np.array(stage_values)

        num_values = len(stage_values)

        # Build header
        lines = [
            f"Interval={interval}",
            f"Stage Hydrograph= {num_values}"
        ]

        # Format values using fixed-width formatter
        formatted_values = BoundaryGenerator.format_fixed_width_values(stage_values)
        lines.append(formatted_values)

        result = '\n'.join(lines)

        logger.info(f"Generated Stage Hydrograph table: {num_values} values, interval={interval}")
        logger.debug(f"Stage range: {stage_values.min():.2f} - {stage_values.max():.2f}")

        return result

    @staticmethod
    @log_call
    def update_boundary_hydrograph(
        unsteady_file: Union[str, Path],
        boundary_location: str,
        hydrograph_table: str,
        table_type: str = 'Flow Hydrograph='
    ) -> None:
        """
        Update or insert a boundary condition hydrograph table in an unsteady file.

        This function finds the specified boundary location in a .u## file and
        replaces the existing table of the specified type with new data. If the
        boundary exists but doesn't have the specified table type, it will be
        inserted.

        Parameters
        ----------
        unsteady_file : str or Path
            Path to the unsteady flow file (.u##)
        boundary_location : str
            Boundary location string to match (e.g., 'River,Reach,RS,')
            Should match the 'Boundary Location=' line format
        hydrograph_table : str
            Complete hydrograph table string (from generate_flow_hydrograph_table
            or generate_stage_hydrograph_table)
        table_type : str, default 'Flow Hydrograph='
            Type of table to replace. Options:
            'Flow Hydrograph=', 'Stage Hydrograph=', 'Lateral Inflow Hydrograph='

        Returns
        -------
        None
            Modifies the unsteady file in-place

        Raises
        ------
        FileNotFoundError
            If unsteady file does not exist
        ValueError
            If boundary location is not found in file

        Examples
        --------
        >>> # Generate new flow hydrograph from USGS data
        >>> flows = retrieve_flow_data('USGS-01646500', '2024-06-01', '2024-06-08')
        >>> table = BoundaryGenerator.generate_flow_hydrograph_table(flows['value'])
        >>>
        >>> # Update the boundary condition in the unsteady file
        >>> BoundaryGenerator.update_boundary_hydrograph(
        ...     unsteady_file="project.u01",
        ...     boundary_location="Potomac River,Upper,50000.0,",
        ...     hydrograph_table=table,
        ...     table_type='Flow Hydrograph='
        ... )

        Notes
        -----
        - The boundary_location string must exactly match the format in the file
        - Include trailing commas in boundary_location (e.g., "River,Reach,RS,")
        - Function preserves all other boundary settings (DSS links, etc.)
        - Creates backup: original file preserved as .u##.bak before modification
        """
        unsteady_path = Path(unsteady_file)

        if not unsteady_path.exists():
            logger.error(f"Unsteady flow file not found: {unsteady_path}")
            raise FileNotFoundError(f"Unsteady flow file not found: {unsteady_path}")

        # Read file
        try:
            with open(unsteady_path, 'r') as f:
                lines = f.readlines()
            logger.debug(f"Read {len(lines)} lines from {unsteady_path}")
        except PermissionError:
            logger.error(f"Permission denied reading: {unsteady_path}")
            raise

        # Find boundary location
        bc_start = None
        for i, line in enumerate(lines):
            if line.startswith('Boundary Location='):
                # Extract location string and compare
                loc_str = line.replace('Boundary Location=', '').strip()
                if boundary_location in loc_str or loc_str in boundary_location:
                    bc_start = i
                    logger.debug(f"Found boundary location at line {i+1}: {loc_str}")
                    break

        if bc_start is None:
            logger.error(f"Boundary location not found: {boundary_location}")
            raise ValueError(f"Boundary location not found: {boundary_location}")

        # Find existing table of specified type within this boundary
        table_start = None
        table_end = None
        bc_end = len(lines)  # Default to end of file

        # Find next boundary location (defines end of current boundary block)
        for i in range(bc_start + 1, len(lines)):
            if lines[i].startswith('Boundary Location='):
                bc_end = i
                break

        # Search for existing table within this boundary block
        for i in range(bc_start, bc_end):
            if lines[i].startswith(table_type):
                table_start = i
                logger.debug(f"Found existing {table_type} at line {i+1}")

                # Parse number of values to determine table extent
                try:
                    num_values = int(lines[i].split('=')[1].strip())
                    # Calculate number of data lines (10 values per line)
                    num_data_lines = (num_values + 9) // 10
                    # Table extent: header line + Interval line + data lines
                    # Find Interval= line before table header
                    interval_line = i - 1 if i > 0 and lines[i-1].startswith('Interval=') else i
                    table_end = i + 1 + num_data_lines
                    logger.debug(f"Existing table spans lines {interval_line+1} to {table_end}")
                except (ValueError, IndexError) as e:
                    logger.warning(f"Error parsing table header: {e}")
                break

        # Prepare new table lines
        new_table_lines = [line + '\n' if not line.endswith('\n') else line
                          for line in hydrograph_table.split('\n')]

        # Replace or insert table
        if table_start is not None:
            # Replace existing table
            # Remove Interval line if it exists before the table
            if table_start > 0 and lines[table_start - 1].startswith('Interval='):
                replace_start = table_start - 1
            else:
                replace_start = table_start

            new_lines = lines[:replace_start] + new_table_lines + lines[table_end:]
            logger.info(f"Replaced existing {table_type} at line {replace_start+1}")
        else:
            # Insert new table after boundary location
            # Find good insertion point (after Boundary Location and any DSS lines)
            insert_idx = bc_start + 1
            while (insert_idx < bc_end and
                   (lines[insert_idx].startswith('DSS File=') or
                    lines[insert_idx].startswith('DSS Path=') or
                    lines[insert_idx].startswith('Use DSS='))):
                insert_idx += 1

            new_lines = lines[:insert_idx] + new_table_lines + lines[insert_idx:]
            logger.info(f"Inserted new {table_type} at line {insert_idx+1}")

        # Create backup
        backup_path = Path(str(unsteady_path) + '.bak')
        try:
            with open(backup_path, 'w') as f:
                f.writelines(lines)
            logger.debug(f"Created backup: {backup_path}")
        except Exception as e:
            logger.warning(f"Could not create backup: {e}")

        # Write updated file
        try:
            with open(unsteady_path, 'w') as f:
                f.writelines(new_lines)
            logger.info(f"Successfully updated {unsteady_path}")
        except PermissionError:
            logger.error(f"Permission denied writing to: {unsteady_path}")
            raise
        except IOError as e:
            logger.error(f"Error writing to {unsteady_path}: {e}")
            raise
