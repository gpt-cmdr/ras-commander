"""
GeomLateral - Lateral structures and SA/2D connections for HEC-RAS geometry files

This module provides functionality for reading lateral weir structures and
storage area / 2D area connections from HEC-RAS plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_lateral_structures() - List all lateral weir structures
- get_weir_profile() - Read station/elevation profile for lateral weir
- get_connections() - List all SA/2D area connections
- get_connection_profile() - Read dam/weir crest profile for connection
- get_connection_gates() - Read gate definitions for connection

Example Usage:
    >>> from ras_commander import GeomLateral
    >>> from pathlib import Path
    >>>
    >>> # List all lateral structures
    >>> geom_file = Path("model.g01")
    >>> laterals_df = GeomLateral.get_lateral_structures(geom_file)
    >>> print(f"Found {len(laterals_df)} lateral structures")
    >>>
    >>> # List SA/2D connections
    >>> connections_df = GeomLateral.get_connections(geom_file)
    >>> print(connections_df)
"""

from pathlib import Path
from typing import Union, Optional, List, Dict, Any
import pandas as pd

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomLateral:
    """
    Operations for lateral structures and SA/2D connections in geometry files.

    All methods are static and designed to be used without instantiation.
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8      # Character width for numeric data in geometry files
    VALUES_PER_LINE = 10        # Number of values per line in fixed-width format
    DEFAULT_SEARCH_RANGE = 100  # Lines to search for keywords after structure header

    @staticmethod
    @log_call
    def get_lateral_structures(geom_file: Union[str, Path],
                               river: Optional[str] = None) -> pd.DataFrame:
        """
        Extract lateral weir structure metadata from geometry file.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (Optional[str]): Filter by specific river name

        Returns:
            pd.DataFrame: DataFrame with columns:
                - River (str): River name
                - Reach (str): Reach name
                - Name (str): Lateral weir name
                - StartRS (str): Starting river station
                - EndRS (str): Ending river station
                - NumPoints (int): Number of station/elevation points

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> laterals = GeomLateral.get_lateral_structures("model.g01")
            >>> for _, row in laterals.iterrows():
            ...     print(f"Lateral: {row['Name']} from RS {row['StartRS']} to {row['EndRS']}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            laterals = []
            current_river = None
            current_reach = None
            i = 0

            while i < len(lines):
                line = lines[i]

                # Track current river/reach
                if line.startswith("River Reach="):
                    values = GeomParser.extract_comma_list(line, "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]

                # Find lateral weir definition
                elif line.startswith("Lat Struct="):
                    if river is not None and current_river != river:
                        i += 1
                        continue

                    lat_values = GeomParser.extract_comma_list(line, "Lat Struct")
                    lat_name = lat_values[0] if lat_values else ""

                    # Look for additional data
                    start_rs = None
                    end_rs = None
                    num_points = 0

                    for j in range(i+1, min(i+30, len(lines))):
                        if lines[j].startswith("Lat Struct RS="):
                            rs_values = GeomParser.extract_comma_list(lines[j], "Lat Struct RS")
                            if len(rs_values) >= 2:
                                start_rs = rs_values[0]
                                end_rs = rs_values[1]

                        elif lines[j].startswith("#Lat Struct Sta/Elev="):
                            count_str = GeomParser.extract_keyword_value(lines[j], "#Lat Struct Sta/Elev")
                            try:
                                num_points = int(count_str.strip())
                            except ValueError:
                                pass
                            break

                        # Stop at next structure
                        if lines[j].startswith("Lat Struct=") or lines[j].startswith("River Reach="):
                            break

                    laterals.append({
                        'River': current_river,
                        'Reach': current_reach,
                        'Name': lat_name,
                        'StartRS': start_rs,
                        'EndRS': end_rs,
                        'NumPoints': num_points
                    })

                i += 1

            df = pd.DataFrame(laterals)
            logger.debug(f"Found {len(df)} lateral structures in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading lateral structures: {str(e)}")
            raise IOError(f"Failed to read lateral structures: {str(e)}")

    @staticmethod
    @log_call
    def get_weir_profile(geom_file: Union[str, Path],
                        lateral_name: str) -> pd.DataFrame:
        """
        Extract station/elevation profile for a lateral weir.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            lateral_name (str): Lateral weir name

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Station (float): Station along weir
                - Elevation (float): Weir crest elevation

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If lateral weir not found

        Example:
            >>> profile = GeomLateral.get_weir_profile("model.g01", "Spillway")
            >>> print(f"Weir profile has {len(profile)} points")
            >>> print(f"Crest elevation range: {profile['Elevation'].min():.1f} to {profile['Elevation'].max():.1f}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the lateral weir
            lat_idx = None
            for i, line in enumerate(lines):
                if line.startswith("Lat Struct="):
                    lat_values = GeomParser.extract_comma_list(line, "Lat Struct")
                    if lat_values and lat_values[0] == lateral_name:
                        lat_idx = i
                        break

            if lat_idx is None:
                raise ValueError(f"Lateral weir not found: {lateral_name}")

            # Find station/elevation data
            for j in range(lat_idx+1, min(lat_idx+GeomLateral.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("#Lat Struct Sta/Elev="):
                    count_str = GeomParser.extract_keyword_value(lines[j], "#Lat Struct Sta/Elev")
                    count = int(count_str.strip())

                    # Parse paired data
                    total_values = count * 2
                    values = []
                    k = j + 1
                    while len(values) < total_values and k < len(lines):
                        if '=' in lines[k]:
                            break
                        parsed = GeomParser.parse_fixed_width(lines[k], GeomLateral.FIXED_WIDTH_COLUMN)
                        values.extend(parsed)
                        k += 1

                    # Split into stations and elevations
                    stations = values[0::2]
                    elevations = values[1::2]

                    df = pd.DataFrame({
                        'Station': stations[:count],
                        'Elevation': elevations[:count]
                    })

                    logger.info(f"Extracted {len(df)} profile points for lateral {lateral_name}")
                    return df

                # Stop at next structure
                if lines[j].startswith("Lat Struct="):
                    break

            raise ValueError(f"Station/elevation data not found for lateral {lateral_name}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading lateral weir profile: {str(e)}")
            raise IOError(f"Failed to read lateral weir profile: {str(e)}")

    @staticmethod
    @log_call
    def get_connections(geom_file: Union[str, Path]) -> pd.DataFrame:
        """
        Extract SA/2D area connection metadata from geometry file.

        Connections include storage area to storage area connections, storage area
        to 2D flow area connections, and 2D to 2D flow area connections.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Name (str): Connection name
                - Type (str): Connection type (SA to SA, SA to 2D, etc.)
                - From (str): Upstream area name
                - To (str): Downstream area name
                - NumPoints (int): Number of station/elevation points in weir profile

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> connections = GeomLateral.get_connections("model.g01")
            >>> print(f"Found {len(connections)} connections")
            >>> for _, row in connections.iterrows():
            ...     print(f"{row['Name']}: {row['From']} -> {row['To']}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            connections = []
            i = 0

            while i < len(lines):
                line = lines[i]

                # Find SA/2D Connection definition
                if line.startswith("SA/2D Area Conn="):
                    conn_values = GeomParser.extract_comma_list(line, "SA/2D Area Conn")
                    conn_name = conn_values[0] if conn_values else ""

                    # Parse connection parameters
                    from_area = None
                    to_area = None
                    conn_type = "Unknown"
                    num_points = 0

                    for j in range(i+1, min(i+50, len(lines))):
                        if lines[j].startswith("From Storage Area="):
                            from_area = GeomParser.extract_keyword_value(lines[j], "From Storage Area")
                        elif lines[j].startswith("To Storage Area="):
                            to_area = GeomParser.extract_keyword_value(lines[j], "To Storage Area")
                        elif lines[j].startswith("From 2D Area="):
                            from_area = GeomParser.extract_keyword_value(lines[j], "From 2D Area")
                            conn_type = "2D to SA" if to_area else "2D to 2D"
                        elif lines[j].startswith("To 2D Area="):
                            to_area = GeomParser.extract_keyword_value(lines[j], "To 2D Area")
                            conn_type = "SA to 2D" if from_area and "2D" not in str(from_area) else conn_type
                        elif lines[j].startswith("#Conn Weir Sta/Elev="):
                            count_str = GeomParser.extract_keyword_value(lines[j], "#Conn Weir Sta/Elev")
                            try:
                                num_points = int(count_str.strip())
                            except ValueError:
                                pass
                            break

                        # Stop at next structure
                        if lines[j].startswith("SA/2D Area Conn=") or lines[j].startswith("Storage Area="):
                            break

                    # Determine type
                    if from_area and to_area:
                        if "2D" in conn_type:
                            pass  # Already set
                        else:
                            conn_type = "SA to SA"

                    connections.append({
                        'Name': conn_name,
                        'Type': conn_type,
                        'From': from_area,
                        'To': to_area,
                        'NumPoints': num_points
                    })

                i += 1

            df = pd.DataFrame(connections)
            logger.debug(f"Found {len(df)} SA/2D connections in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading connections: {str(e)}")
            raise IOError(f"Failed to read connections: {str(e)}")

    @staticmethod
    @log_call
    def get_connection_profile(geom_file: Union[str, Path],
                              connection_name: str) -> pd.DataFrame:
        """
        Extract dam/weir crest profile for a SA/2D connection.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            connection_name (str): Connection name

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Station (float): Station along weir
                - Elevation (float): Weir crest elevation

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection not found

        Example:
            >>> profile = GeomLateral.get_connection_profile("model.g01", "Dam Embankment")
            >>> print(f"Weir crest has {len(profile)} points")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the connection
            conn_idx = None
            for i, line in enumerate(lines):
                if line.startswith("SA/2D Area Conn="):
                    conn_values = GeomParser.extract_comma_list(line, "SA/2D Area Conn")
                    if conn_values and conn_values[0] == connection_name:
                        conn_idx = i
                        break

            if conn_idx is None:
                raise ValueError(f"Connection not found: {connection_name}")

            # Find weir profile data
            for j in range(conn_idx+1, min(conn_idx+GeomLateral.DEFAULT_SEARCH_RANGE, len(lines))):
                if lines[j].startswith("#Conn Weir Sta/Elev="):
                    count_str = GeomParser.extract_keyword_value(lines[j], "#Conn Weir Sta/Elev")
                    count = int(count_str.strip())

                    # Parse paired data
                    total_values = count * 2
                    values = []
                    k = j + 1
                    while len(values) < total_values and k < len(lines):
                        if '=' in lines[k]:
                            break
                        parsed = GeomParser.parse_fixed_width(lines[k], GeomLateral.FIXED_WIDTH_COLUMN)
                        values.extend(parsed)
                        k += 1

                    # Split into stations and elevations
                    stations = values[0::2]
                    elevations = values[1::2]

                    df = pd.DataFrame({
                        'Station': stations[:count],
                        'Elevation': elevations[:count]
                    })

                    logger.info(f"Extracted {len(df)} weir profile points for connection {connection_name}")
                    return df

                # Stop at next structure
                if lines[j].startswith("SA/2D Area Conn="):
                    break

            raise ValueError(f"Weir profile not found for connection {connection_name}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading connection profile: {str(e)}")
            raise IOError(f"Failed to read connection profile: {str(e)}")

    @staticmethod
    @log_call
    def get_connection_gates(geom_file: Union[str, Path],
                            connection_name: str) -> pd.DataFrame:
        """
        Extract gate definitions for a SA/2D connection.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            connection_name (str): Connection name

        Returns:
            pd.DataFrame: DataFrame with gate parameters including:
                - GateName, Width, Height, InvertElevation, etc.

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection not found or has no gates

        Example:
            >>> gates = GeomLateral.get_connection_gates("model.g01", "Dam Outlet")
            >>> print(f"Found {len(gates)} gates")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find the connection
            conn_idx = None
            for i, line in enumerate(lines):
                if line.startswith("SA/2D Area Conn="):
                    conn_values = GeomParser.extract_comma_list(line, "SA/2D Area Conn")
                    if conn_values and conn_values[0] == connection_name:
                        conn_idx = i
                        break

            if conn_idx is None:
                raise ValueError(f"Connection not found: {connection_name}")

            # Find gate definitions
            gates = []
            i = conn_idx + 1
            while i < min(conn_idx + GeomLateral.DEFAULT_SEARCH_RANGE, len(lines)):
                line = lines[i]

                # Stop at next structure
                if line.startswith("SA/2D Area Conn=") or line.startswith("Storage Area="):
                    break

                # Found gate header (simplified parsing - actual format varies)
                if line.startswith("Conn Gate Name"):
                    if i + 1 < len(lines):
                        gate_line = lines[i + 1]
                        parts = [p.strip() for p in gate_line.split(',')]

                        gate_data = {
                            'GateName': parts[0] if len(parts) > 0 else None,
                            'Width': float(parts[1]) if len(parts) > 1 and parts[1] else None,
                            'Height': float(parts[2]) if len(parts) > 2 and parts[2] else None,
                            'InvertElevation': float(parts[3]) if len(parts) > 3 and parts[3] else None,
                        }
                        gates.append(gate_data)
                        i += 2
                        continue

                i += 1

            if not gates:
                raise ValueError(f"No gates found for connection {connection_name}")

            df = pd.DataFrame(gates)
            logger.info(f"Extracted {len(df)} gates for connection {connection_name}")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading connection gates: {str(e)}")
            raise IOError(f"Failed to read connection gates: {str(e)}")
