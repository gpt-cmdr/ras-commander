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
- set_connection_profile() - Write dam/weir crest profile for connection
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
from typing import Union, Optional, List, Dict, Any, Tuple
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

    CONNECTION_HEADER_KEYWORDS = ("Connection", "SA/2D Area Conn")
    CONNECTION_HEADER_PREFIXES = tuple(f"{keyword}=" for keyword in CONNECTION_HEADER_KEYWORDS)
    CONNECTION_PROFILE_KEYWORDS = ("Conn Weir SE", "#Conn Weir Sta/Elev")
    CONNECTION_BLOCK_TERMINATORS = (
        "Connection=",
        "SA/2D Area Conn=",
        "Storage Area=",
        "River Reach=",
        "Junct Name=",
        "Lat Struct=",
        "Weir Embankment=",
        "Pump Station=",
        "BC Line Name=",
        "LCMann Time=",
        "Chan Stop Cuts=",
        "Observed WS=",
    )

    @staticmethod
    def _is_connection_header(line: str) -> bool:
        """Return True when *line* starts a SA/2D connection block."""
        return line.startswith(GeomLateral.CONNECTION_HEADER_PREFIXES)

    @staticmethod
    def _connection_keyword(line: str) -> Optional[str]:
        """Return the connection header keyword used by *line*."""
        for keyword in GeomLateral.CONNECTION_HEADER_KEYWORDS:
            if line.startswith(f"{keyword}="):
                return keyword
        return None

    @staticmethod
    def _extract_connection_header(line: str) -> Dict[str, Any]:
        """Parse a connection header line into name and optional centroid fields."""
        keyword = GeomLateral._connection_keyword(line)
        if keyword is None:
            return {
                'Header': None,
                'Name': "",
                'RawName': "",
                'CenterX': None,
                'CenterY': None,
            }

        value_str = GeomParser.extract_keyword_value(line, keyword)
        parts = value_str.split(',')
        raw_name = parts[0] if parts else value_str

        data = {
            'Header': keyword,
            'Name': raw_name.strip(),
            'RawName': raw_name,
            'CenterX': None,
            'CenterY': None,
        }

        if len(parts) > 1 and parts[1].strip():
            try:
                data['CenterX'] = float(parts[1].strip())
            except ValueError:
                pass

        if len(parts) > 2 and parts[2].strip():
            try:
                data['CenterY'] = float(parts[2].strip())
            except ValueError:
                pass

        return data

    @staticmethod
    def _is_connection_block_terminator(line: str) -> bool:
        """Return True when *line* starts a new top-level geometry block."""
        return line.startswith(GeomLateral.CONNECTION_BLOCK_TERMINATORS)

    @staticmethod
    def _iter_connection_blocks(lines: List[str]):
        """Yield (start_idx, end_idx, block_lines, header_data) for connection blocks."""
        i = 0
        while i < len(lines):
            if GeomLateral._is_connection_header(lines[i]):
                start_idx = i
                header_data = GeomLateral._extract_connection_header(lines[i])
                end_idx = i + 1

                while end_idx < len(lines):
                    if GeomLateral._is_connection_block_terminator(lines[end_idx]):
                        break
                    end_idx += 1

                yield start_idx, end_idx, lines[start_idx:end_idx], header_data
                i = end_idx
                continue

            i += 1

    @staticmethod
    def _find_connection_block(lines: List[str], connection_name: str):
        """Return the connection block matching a stripped or raw connection name."""
        for start_idx, end_idx, block_lines, header_data in GeomLateral._iter_connection_blocks(lines):
            if (
                header_data['Name'] == connection_name
                or header_data['RawName'] == connection_name
                or header_data['RawName'].strip() == connection_name.strip()
            ):
                return start_idx, end_idx, block_lines, header_data
        return None

    @staticmethod
    def _find_connection_profile_marker(block_lines: List[str]) -> Optional[Tuple[int, str, int]]:
        """Return (local index, keyword, point count) for a connection crest profile."""
        for idx, line in enumerate(block_lines):
            for keyword in GeomLateral.CONNECTION_PROFILE_KEYWORDS:
                if line.startswith(f"{keyword}="):
                    count_str = GeomParser.extract_keyword_value(line, keyword)
                    try:
                        return idx, keyword, int(count_str.strip())
                    except ValueError:
                        return idx, keyword, 0
        return None

    @staticmethod
    def _parse_paired_data(lines: List[str], start_idx: int, count: int) -> pd.DataFrame:
        """Parse station/elevation fixed-width pairs from *lines*."""
        total_values = count * 2
        values = []
        i = start_idx

        while len(values) < total_values and i < len(lines):
            if '=' in lines[i]:
                break
            parsed = GeomParser.parse_fixed_width(lines[i], GeomLateral.FIXED_WIDTH_COLUMN)
            values.extend(parsed)
            i += 1

        stations = values[0::2]
        elevations = values[1::2]

        return pd.DataFrame({
            'Station': stations[:count],
            'Elevation': elevations[:count],
        })

    @staticmethod
    def _storage_area_type_map(lines: List[str]) -> Dict[str, bool]:
        """Map storage-area names to True when the area is a 2D flow area."""
        area_types = {}
        i = 0

        while i < len(lines):
            line = lines[i]
            if not line.startswith("Storage Area="):
                i += 1
                continue

            value_str = GeomParser.extract_keyword_value(line, "Storage Area")
            parts = [p.strip() for p in value_str.split(',')]
            area_name = parts[0] if parts else value_str.strip()
            is_2d = False

            j = i + 1
            while j < len(lines):
                if lines[j].startswith(("Storage Area=", "Connection=", "SA/2D Area Conn=", "River Reach=")):
                    break
                if lines[j].startswith("Storage Area Is2D="):
                    is2d_str = GeomParser.extract_keyword_value(lines[j], "Storage Area Is2D")
                    try:
                        is_2d = int(is2d_str.strip()) == -1
                    except ValueError:
                        is_2d = False
                j += 1

            area_types[area_name] = is_2d
            i = j

        return area_types

    @staticmethod
    def _classify_connection(
        from_area: Optional[str],
        to_area: Optional[str],
        area_types: Dict[str, bool],
        fallback: str = "Unknown",
    ) -> str:
        """Classify a connection as SA/2D when storage-area metadata is available."""
        if not from_area or not to_area:
            return fallback

        def label(area_name: str) -> Optional[str]:
            key = area_name.strip()
            if key in area_types:
                return "2D" if area_types[key] else "SA"
            return None

        from_label = label(from_area)
        to_label = label(to_area)
        if from_label and to_label:
            return f"{from_label} to {to_label}"

        return fallback

    @staticmethod
    def _parse_optional_int(value: str) -> Optional[int]:
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_optional_float(value: str) -> Optional[float]:
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return None

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            connections = []
            area_types = GeomLateral._storage_area_type_map(lines)

            for start_idx, end_idx, block_lines, header_data in GeomLateral._iter_connection_blocks(lines):
                from_area = None
                to_area = None
                conn_type = "Unknown"
                routing_type = None
                line_points = None
                has_gate = False
                has_culvert = False

                for block_line in block_lines[1:]:
                    if block_line.startswith("From Storage Area="):
                        from_area = GeomParser.extract_keyword_value(block_line, "From Storage Area").strip()
                    elif block_line.startswith("To Storage Area="):
                        to_area = GeomParser.extract_keyword_value(block_line, "To Storage Area").strip()
                    elif block_line.startswith("From 2D Area="):
                        from_area = GeomParser.extract_keyword_value(block_line, "From 2D Area").strip()
                        conn_type = "2D to SA" if to_area else "2D to 2D"
                    elif block_line.startswith("To 2D Area="):
                        to_area = GeomParser.extract_keyword_value(block_line, "To 2D Area").strip()
                        if from_area:
                            conn_type = "SA to 2D"
                    elif block_line.startswith("Connection Up SA="):
                        from_area = GeomParser.extract_keyword_value(block_line, "Connection Up SA").strip()
                    elif block_line.startswith("Connection Dn SA="):
                        to_area = GeomParser.extract_keyword_value(block_line, "Connection Dn SA").strip()
                    elif block_line.startswith("Conn Routing Type="):
                        routing_type = GeomLateral._parse_optional_int(
                            GeomParser.extract_keyword_value(block_line, "Conn Routing Type")
                        )
                    elif block_line.startswith("Connection Line="):
                        line_points = GeomLateral._parse_optional_int(
                            GeomParser.extract_keyword_value(block_line, "Connection Line")
                        )
                    elif block_line.startswith("Conn Gate Name"):
                        has_gate = True
                    elif block_line.startswith(("Connection Culv=", "Conn Culv")):
                        has_culvert = True

                marker = GeomLateral._find_connection_profile_marker(block_lines)
                num_points = marker[2] if marker else 0

                if from_area and to_area:
                    conn_type = GeomLateral._classify_connection(
                        from_area,
                        to_area,
                        area_types,
                        fallback="SA/2D Connection" if header_data['Header'] == "Connection" else conn_type,
                    )
                    if conn_type == "Unknown":
                        conn_type = "SA to SA"

                connections.append({
                    'Name': header_data['Name'],
                    'Type': conn_type,
                    'From': from_area,
                    'To': to_area,
                    'NumPoints': num_points,
                    'Header': header_data['Header'],
                    'RawName': header_data['RawName'],
                    'CenterX': header_data['CenterX'],
                    'CenterY': header_data['CenterY'],
                    'LinePoints': line_points,
                    'RoutingType': routing_type,
                    'HasGate': has_gate,
                    'HasCulvert': has_culvert,
                    'StartLine': start_idx + 1,
                    'EndLine': end_idx,
                })

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            block = GeomLateral._find_connection_block(lines, connection_name)
            if block is None:
                raise ValueError(f"Connection not found: {connection_name}")

            _, _, block_lines, _ = block
            marker = GeomLateral._find_connection_profile_marker(block_lines)
            if marker is None:
                raise ValueError(f"Weir profile not found for connection {connection_name}")

            marker_idx, _, count = marker
            df = GeomLateral._parse_paired_data(block_lines, marker_idx + 1, count)

            logger.info(f"Extracted {len(df)} weir profile points for connection {connection_name}")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading connection profile: {str(e)}")
            raise IOError(f"Failed to read connection profile: {str(e)}")

    @staticmethod
    @log_call
    def set_connection_profile(
        geom_file: Union[str, Path],
        connection_name: str,
        sta_elev_df: pd.DataFrame,
        create_backup: bool = True,
    ) -> Optional[Path]:
        """
        Write the dam/weir crest station-elevation profile for a connection.

        Supports both modern ``Connection=`` blocks with ``Conn Weir SE=``
        records and legacy ``SA/2D Area Conn=`` blocks with
        ``#Conn Weir Sta/Elev=`` records.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            sta_elev_df: DataFrame with Station and Elevation columns
            create_backup: Create a .bak backup before writing (default True)

        Returns:
            Optional[Path]: Backup path when create_backup=True, else None

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If the connection/profile or required columns are missing
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not {'Station', 'Elevation'}.issubset(sta_elev_df.columns):
            raise ValueError("sta_elev_df must contain Station and Elevation columns")
        if sta_elev_df.empty:
            raise ValueError("sta_elev_df must contain at least one station/elevation row")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            block = GeomLateral._find_connection_block(lines, connection_name)
            if block is None:
                raise ValueError(f"Connection not found: {connection_name}")

            start_idx, end_idx, block_lines, _ = block
            marker = GeomLateral._find_connection_profile_marker(block_lines)
            if marker is None:
                raise ValueError(f"Weir profile not found for connection {connection_name}")

            marker_idx, keyword, _ = marker
            profile_idx = start_idx + marker_idx
            data_start = profile_idx + 1
            data_end = data_start
            while data_end < end_idx and '=' not in lines[data_end]:
                data_end += 1

            values = []
            for _, row in sta_elev_df.iterrows():
                values.extend([float(row['Station']), float(row['Elevation'])])

            new_data_lines = GeomParser.format_fixed_width(
                values,
                column_width=GeomLateral.FIXED_WIDTH_COLUMN,
                values_per_line=GeomLateral.VALUES_PER_LINE,
                precision=3,
            )

            line_ending = '\n' if lines[profile_idx].endswith('\n') else ''
            if keyword == "Conn Weir SE":
                lines[profile_idx] = f"Conn Weir SE= {len(sta_elev_df)} {line_ending}"
            else:
                lines[profile_idx] = f"#Conn Weir Sta/Elev= {len(sta_elev_df)}{line_ending}"

            lines[data_start:data_end] = new_data_lines
            return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing connection profile: {str(e)}")
            raise IOError(f"Failed to write connection profile: {str(e)}")

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            block = GeomLateral._find_connection_block(lines, connection_name)
            if block is None:
                raise ValueError(f"Connection not found: {connection_name}")

            _, _, block_lines, _ = block
            gates = []
            i = 1
            while i < len(block_lines):
                line = block_lines[i]

                if line.startswith("Conn Gate Name"):
                    if i + 1 < len(block_lines):
                        gate_line = block_lines[i + 1]
                        parts = [p.strip() for p in gate_line.split(',')]

                        gate_data = {
                            'GateName': parts[0] if len(parts) > 0 else None,
                            'Width': GeomLateral._parse_optional_float(parts[1]) if len(parts) > 1 else None,
                            'Height': GeomLateral._parse_optional_float(parts[2]) if len(parts) > 2 else None,
                            'InvertElevation': GeomLateral._parse_optional_float(parts[3]) if len(parts) > 3 else None,
                            'GateCoefficient': GeomLateral._parse_optional_float(parts[4]) if len(parts) > 4 else None,
                            'ExpansionTop': GeomLateral._parse_optional_float(parts[5]) if len(parts) > 5 else None,
                            'ExpansionOrifice': GeomLateral._parse_optional_float(parts[6]) if len(parts) > 6 else None,
                            'ExpansionHydraulic': GeomLateral._parse_optional_float(parts[7]) if len(parts) > 7 else None,
                            'GateType': GeomLateral._parse_optional_float(parts[8]) if len(parts) > 8 else None,
                            'WeirCoefficient': GeomLateral._parse_optional_float(parts[9]) if len(parts) > 9 else None,
                            'IsOgee': GeomLateral._parse_optional_int(parts[10]) if len(parts) > 10 else None,
                            'SpillwayHeight': GeomLateral._parse_optional_float(parts[11]) if len(parts) > 11 else None,
                            'DesignHead': GeomLateral._parse_optional_float(parts[12]) if len(parts) > 12 else None,
                            'NumOpenings': GeomLateral._parse_optional_int(parts[13]) if len(parts) > 13 else 0,
                            'OpeningStations': [],
                        }

                        num_openings = gate_data['NumOpenings'] or 0
                        station_idx = i + 2
                        opening_stations = []
                        while (
                            num_openings > 0
                            and len(opening_stations) < num_openings
                            and station_idx < len(block_lines)
                            and '=' not in block_lines[station_idx]
                        ):
                            opening_stations.extend(
                                GeomParser.parse_fixed_width(
                                    block_lines[station_idx],
                                    GeomLateral.FIXED_WIDTH_COLUMN,
                                )
                            )
                            station_idx += 1
                        gate_data['OpeningStations'] = opening_stations[:num_openings]

                        gates.append(gate_data)
                        i = station_idx
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
