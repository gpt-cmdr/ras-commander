"""
GeomLandCover - 2D Manning's n land cover operations

This module provides functionality for reading and modifying Manning's n
roughness values for 2D flow areas in HEC-RAS geometry files. These values
are associated with land cover classifications.

All methods are static and designed to be used without instantiation.

List of Functions:
- get_base_mannings_n() - Read base Manning's n table from geometry file
- set_base_mannings_n() - Write base Manning's n values to geometry file
- get_region_mannings_n() - Read Manning's n region overrides
- set_region_mannings_n() - Write regional Manning's n overrides

Example Usage:
    >>> from ras_commander import GeomLandCover, RasPlan
    >>>
    >>> # Get base Manning's n values
    >>> geom_path = RasPlan.get_geom_path("01")
    >>> mannings_df = GeomLandCover.get_base_mannings_n(geom_path)
    >>> print(mannings_df)
    >>>
    >>> # Modify and write back
    >>> mannings_df['Base Mannings n Value'] *= 1.1  # Increase by 10%
    >>> GeomLandCover.set_base_mannings_n(geom_path, mannings_df)
"""

from pathlib import Path
from typing import Union
import pandas as pd

from ..LoggingConfig import get_logger
from ..Decorators import log_call

logger = get_logger(__name__)


class GeomLandCover:
    """
    A class for 2D Manning's n land cover operations in HEC-RAS geometry files.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    @log_call
    def get_base_mannings_n(geom_file_path: Union[str, Path]) -> pd.DataFrame:
        """
        Reads the base Manning's n table from a HEC-RAS geometry file.

        Parameters:
            geom_file_path (Union[str, Path]): Path to the geometry file (.g##)

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Table Number (str): Manning's n table identifier
                - Land Cover Name (str): Name of the land cover type
                - Base Mannings n Value (float): Manning's n roughness coefficient

        Example:
            >>> geom_path = RasPlan.get_geom_path("01")
            >>> mannings_df = GeomLandCover.get_base_mannings_n(geom_path)
            >>> print(mannings_df)
        """
        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)

        base_table_rows = []
        table_number = None

        # Read the geometry file
        with open(geom_file_path, 'r') as f:
            lines = f.readlines()

        # Parse the file
        reading_base_table = False
        for line in lines:
            line = line.strip()

            # Find the table number
            if line.startswith('LCMann Table='):
                table_number = line.split('=')[1]
                reading_base_table = True
                continue

            # Stop reading when we hit a line without a comma or starting with LCMann
            if reading_base_table and (not ',' in line or line.startswith('LCMann')):
                reading_base_table = False
                continue

            # Parse data rows in base table
            if reading_base_table and ',' in line:
                # Check if there are multiple commas in the line
                parts = line.split(',')
                if len(parts) > 2:
                    # Handle case where land cover name contains commas
                    name = ','.join(parts[:-1])
                    value = parts[-1]
                else:
                    name, value = parts

                try:
                    base_table_rows.append([table_number, name, float(value)])
                except ValueError:
                    # Log the error and continue
                    logger.warning(f"Error parsing line: {line}")
                    continue

        # Create DataFrame
        # Note: Column uses "Mannings" (no apostrophe) for simplicity in DataFrame operations,
        # though HEC-RAS HDF files use "Manning's n" (with apostrophe) as the proper technical term.
        if base_table_rows:
            df = pd.DataFrame(base_table_rows, columns=['Table Number', 'Land Cover Name', 'Base Mannings n Value'])
            return df
        else:
            return pd.DataFrame(columns=['Table Number', 'Land Cover Name', 'Base Mannings n Value'])

    @staticmethod
    @log_call
    def set_base_mannings_n(geom_file_path: Union[str, Path], mannings_data: pd.DataFrame) -> bool:
        """
        Writes base Manning's n values to a HEC-RAS geometry file.

        Parameters:
            geom_file_path (Union[str, Path]): Path to the geometry file (.g##)
            mannings_data (pd.DataFrame): DataFrame with columns:
                - Table Number (str): Manning's n table identifier
                - Land Cover Name (str): Name of the land cover type
                - Base Mannings n Value (float): Manning's n roughness coefficient

        Returns:
            bool: True if successful

        Raises:
            ValueError: If land cover names don't match between file and DataFrame
        """
        import shutil
        import datetime

        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)

        # Create backup
        backup_path = geom_file_path.with_suffix(geom_file_path.suffix + '.bak')
        shutil.copy2(geom_file_path, backup_path)

        # Read the entire file
        with open(geom_file_path, 'r') as f:
            lines = f.readlines()

        # Find the Manning's table section
        table_number = str(mannings_data['Table Number'].iloc[0])
        start_idx = None
        end_idx = None

        for i, line in enumerate(lines):
            if line.strip() == f"LCMann Table={table_number}":
                start_idx = i
                # Find the end of this table (next LCMann directive or end of file)
                for j in range(i+1, len(lines)):
                    if lines[j].strip().startswith('LCMann'):
                        end_idx = j
                        break
                if end_idx is None:  # If we reached the end of the file
                    end_idx = len(lines)
                break

        if start_idx is None:
            raise ValueError(f"Manning's table {table_number} not found in the geometry file")

        # Extract existing land cover names from the file
        existing_landcover = []
        for i in range(start_idx+1, end_idx):
            line = lines[i].strip()
            if ',' in line:
                parts = line.split(',')
                if len(parts) > 2:
                    # Handle case where land cover name contains commas
                    name = ','.join(parts[:-1])
                else:
                    name = parts[0]
                existing_landcover.append(name)

        # Check if all land cover names in the dataframe match the file
        df_landcover = mannings_data['Land Cover Name'].tolist()
        if set(df_landcover) != set(existing_landcover):
            missing = set(existing_landcover) - set(df_landcover)
            extra = set(df_landcover) - set(existing_landcover)
            error_msg = "Land cover names don't match between file and dataframe.\n"
            if missing:
                error_msg += f"Missing in dataframe: {missing}\n"
            if extra:
                error_msg += f"Extra in dataframe: {extra}"
            raise ValueError(error_msg)

        # Create new content for the table
        new_content = [f"LCMann Table={table_number}\n"]

        # Add base table entries
        for _, row in mannings_data.iterrows():
            new_content.append(f"{row['Land Cover Name']},{row['Base Mannings n Value']}\n")

        # Replace the section in the original file
        updated_lines = lines[:start_idx] + new_content + lines[end_idx:]

        # Update the time stamp
        current_time = datetime.datetime.now().strftime("%b/%d/%Y %H:%M:%S")
        for i, line in enumerate(updated_lines):
            if line.strip().startswith("LCMann Time="):
                updated_lines[i] = f"LCMann Time={current_time}\n"
                break

        # Write the updated file
        with open(geom_file_path, 'w') as f:
            f.writelines(updated_lines)

        return True

    @staticmethod
    @log_call
    def get_region_mannings_n(geom_file_path: Union[str, Path]) -> pd.DataFrame:
        """
        Reads the Manning's n region overrides from a HEC-RAS geometry file.

        Parameters:
            geom_file_path (Union[str, Path]): Path to the geometry file (.g##)

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Table Number (str): Region table identifier
                - Land Cover Name (str): Name of the land cover type
                - MainChannel (float): Manning's n value for main channel
                - Region Name (str): Name of the region

        Example:
            >>> geom_path = RasPlan.get_geom_path("01")
            >>> region_overrides_df = GeomLandCover.get_region_mannings_n(geom_path)
            >>> print(region_overrides_df)
        """
        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)

        region_rows = []
        current_region = None
        current_table = None

        # Read the geometry file
        with open(geom_file_path, 'r') as f:
            lines = f.readlines()

        # Parse the file
        reading_region_table = False
        for line in lines:
            line = line.strip()

            # Find region name
            if line.startswith('LCMann Region Name='):
                current_region = line.split('=')[1]
                continue

            # Find region table number
            if line.startswith('LCMann Region Table='):
                current_table = line.split('=')[1]
                reading_region_table = True
                continue

            # Stop reading when we hit a line without a comma or starting with LCMann
            if reading_region_table and (not ',' in line or line.startswith('LCMann')):
                reading_region_table = False
                continue

            # Parse data rows in region table
            if reading_region_table and ',' in line and current_region is not None:
                # Check if there are multiple commas in the line
                parts = line.split(',')
                if len(parts) > 2:
                    # Handle case where land cover name contains commas
                    name = ','.join(parts[:-1])
                    value = parts[-1]
                else:
                    name, value = parts

                try:
                    region_rows.append([current_table, name, float(value), current_region])
                except ValueError:
                    # Log the error and continue
                    logger.warning(f"Error parsing line: {line}")
                    continue

        # Create DataFrame
        if region_rows:
            return pd.DataFrame(region_rows, columns=['Table Number', 'Land Cover Name', 'MainChannel', 'Region Name'])
        else:
            return pd.DataFrame(columns=['Table Number', 'Land Cover Name', 'MainChannel', 'Region Name'])

    @staticmethod
    @log_call
    def set_region_mannings_n(geom_file_path: Union[str, Path], mannings_data: pd.DataFrame) -> bool:
        """
        Writes regional Manning's n overrides to a HEC-RAS geometry file.

        Parameters:
            geom_file_path (Union[str, Path]): Path to the geometry file (.g##)
            mannings_data (pd.DataFrame): DataFrame with columns:
                - Table Number (str): Region table identifier
                - Land Cover Name (str): Name of the land cover type
                - MainChannel (float): Manning's n value
                - Region Name (str): Name of the region

        Returns:
            bool: True if successful

        Raises:
            ValueError: If region or land cover names don't match
        """
        import shutil
        import datetime

        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)

        # Create backup
        backup_path = geom_file_path.with_suffix(geom_file_path.suffix + '.bak')
        shutil.copy2(geom_file_path, backup_path)

        # Read the entire file
        with open(geom_file_path, 'r') as f:
            lines = f.readlines()

        # Group data by region
        regions = mannings_data.groupby('Region Name')

        # Find the Manning's region sections
        for region_name, region_data in regions:
            table_number = str(region_data['Table Number'].iloc[0])

            # Find the region section
            region_start_idx = None
            region_table_idx = None
            region_end_idx = None
            region_polygon_line = None

            for i, line in enumerate(lines):
                if line.strip() == f"LCMann Region Name={region_name}":
                    region_start_idx = i

                if region_start_idx is not None and line.strip() == f"LCMann Region Table={table_number}":
                    region_table_idx = i

                    # Find the end of this region (next LCMann Region or end of file)
                    for j in range(i+1, len(lines)):
                        if lines[j].strip().startswith('LCMann Region Name=') or lines[j].strip().startswith('LCMann Region Polygon='):
                            if lines[j].strip().startswith('LCMann Region Polygon='):
                                region_polygon_line = lines[j]
                            region_end_idx = j
                            break
                    if region_end_idx is None:  # If we reached the end of the file
                        region_end_idx = len(lines)
                    break

            if region_start_idx is None or region_table_idx is None:
                raise ValueError(f"Region {region_name} with table {table_number} not found in the geometry file")

            # Extract existing land cover names from the file
            existing_landcover = []
            for i in range(region_table_idx+1, region_end_idx):
                line = lines[i].strip()
                if ',' in line and not line.startswith('LCMann'):
                    parts = line.split(',')
                    if len(parts) > 2:
                        # Handle case where land cover name contains commas
                        name = ','.join(parts[:-1])
                    else:
                        name = parts[0]
                    existing_landcover.append(name)

            # Check if all land cover names in the dataframe match the file
            df_landcover = region_data['Land Cover Name'].tolist()
            if set(df_landcover) != set(existing_landcover):
                missing = set(existing_landcover) - set(df_landcover)
                extra = set(df_landcover) - set(existing_landcover)
                error_msg = f"Land cover names for region {region_name} don't match between file and dataframe.\n"
                if missing:
                    error_msg += f"Missing in dataframe: {missing}\n"
                if extra:
                    error_msg += f"Extra in dataframe: {extra}"
                raise ValueError(error_msg)

            # Create new content for the region
            new_content = [
                f"LCMann Region Name={region_name}\n",
                f"LCMann Region Table={table_number}\n"
            ]

            # Add region table entries
            for _, row in region_data.iterrows():
                new_content.append(f"{row['Land Cover Name']},{row['MainChannel']}\n")

            # Add the region polygon line if it exists
            if region_polygon_line:
                new_content.append(region_polygon_line)

            # Replace the section in the original file
            if region_polygon_line:
                # If we have a polygon line, include it in the replacement
                updated_lines = lines[:region_start_idx] + new_content + lines[region_end_idx+1:]
            else:
                # If no polygon line, just replace up to the end index
                updated_lines = lines[:region_start_idx] + new_content + lines[region_end_idx:]

            # Update the lines for the next region
            lines = updated_lines

        # Update the time stamp
        current_time = datetime.datetime.now().strftime("%b/%d/%Y %H:%M:%S")
        for i, line in enumerate(lines):
            if line.strip().startswith("LCMann Region Time="):
                lines[i] = f"LCMann Region Time={current_time}\n"
                break

        # Write the updated file
        with open(geom_file_path, 'w') as f:
            f.writelines(lines)

        return True
