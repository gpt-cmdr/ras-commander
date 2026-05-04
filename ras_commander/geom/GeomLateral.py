"""
GeomLateral - Lateral structures and SA/2D connections for HEC-RAS geometry files

This module provides functionality for reading lateral weir structures and
storage area / 2D area connections from HEC-RAS plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_lateral_structures() - List all lateral weir structures
- get_weir_profile() - Read station/elevation profile for lateral weir
- get_connections() - List all SA/2D area connections
- get_connection_line_coords() - Read polyline XY coords for connection
- get_connection_profile() - Read dam/weir crest profile for connection
- set_connection_profile() - Write dam/weir crest profile for connection
- set_connection() - Create or replace a SA/2D connection block
- get_connection_gates() - Read gate definitions for connection
- set_connection_gates() - Write gate definitions for connection
- delete_connection() - Remove a connection block
- set_connection_profile_from_terrain() - Sample terrain and write profile
- get_bridge_data() - Read all bridge sub-records for a connection
- get_bridge_deck() - Read deck geometry for bridge connection
- get_bridge_piers() - Read pier definitions for bridge connection
- get_bridge_xs() - Read bridge cross-section
- get_bridge_approach_xs() - Read approach cross-section
- set_bridge_deck() - Write deck geometry for bridge connection
- set_bridge_piers() - Write pier definitions for bridge connection
- set_bridge_xs() - Write bridge cross-section
- set_bridge_approach_xs() - Write approach cross-section
- set_bridge_coefficients() - Write bridge hydraulic coefficients

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
from .GeomStorage import GeomStorage

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

    CONN_LINE_COLUMN = 16
    CONN_LINE_VALUES_PER_LINE = 4

    @staticmethod
    def _polyline_centroid(coords: List[Tuple[float, float]]) -> Tuple[float, float]:
        """Return the average XY of a polyline for the connection header."""
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    @staticmethod
    def _pad_name(name: str, width: int = 16) -> str:
        """Left-justify *name* and pad or truncate to *width* characters."""
        return name.ljust(width)[:width]

    @staticmethod
    def _connection_insert_index(lines: List[str]) -> int:
        """Return the line index where a new connection block should be inserted.

        Inserts after the last existing connection block, or before the first
        ``BC Line Name=`` block.  Falls back to end-of-file.
        """
        last_conn_end = None
        for start_idx, end_idx, _, _ in GeomLateral._iter_connection_blocks(lines):
            last_conn_end = end_idx

        if last_conn_end is not None:
            return last_conn_end

        for i, line in enumerate(lines):
            if line.startswith("BC Line Name="):
                return i

        return len(lines)

    @staticmethod
    def _build_connection_block(
        name: str,
        coords: List[Tuple[float, float]],
        upstream: str,
        downstream: str,
        *,
        routing_type: int = 1,
        weir_width: float = 100.0,
        weir_coef: float = 3.0,
        overflow_method_2d: bool = True,
    ) -> List[str]:
        """Assemble a complete modern ``Connection=`` block as a list of lines."""
        cx, cy = GeomLateral._polyline_centroid(coords)
        up_padded = GeomLateral._pad_name(upstream)
        dn_padded = GeomLateral._pad_name(downstream)

        lines: List[str] = []
        lines.append(f"Connection={GeomLateral._pad_name(name)},{cx},{cy}\n")
        lines.append("Connection Desc=\n")
        lines.append(f"Connection Line={len(coords)}\n")
        lines.extend(GeomStorage._format_breakline_coord_lines(coords))
        lines.append(f"Connection Up SA={up_padded}\n")
        lines.append(f"Connection Dn SA={dn_padded}\n")
        lines.append(f"Conn Routing Type= {routing_type} \n")
        lines.append("Conn Use RC Family=False\n")
        lines.append(f"Conn OverFlow Method 2D={'True' if overflow_method_2d else 'False'}\n")
        lines.append(f"Conn Weir WD={weir_width}\n")
        lines.append(f"Conn Weir Coef={weir_coef}\n")
        # Default 2-point flat weir profile at elevation 0
        lines.append("Conn Weir SE= 2 \n")
        lines.append(
            GeomParser.format_fixed_width(
                [0.0, 0.0, 1.0, 0.0],
                column_width=GeomLateral.FIXED_WIDTH_COLUMN,
                values_per_line=GeomLateral.VALUES_PER_LINE,
                precision=3,
            )[0]
        )
        lines.append("Conn Outlet Rating Curve= 0 ,False,,\n")
        return lines

    @staticmethod
    def _format_gate_block(gates) -> List[str]:
        """Format gate definitions as HEC-RAS connection gate lines.

        *gates* may be a DataFrame or list of dicts with keys:
        GateName, Width, Height, InvertElevation, GateCoefficient, NumOpenings,
        OpeningStations.
        """
        if isinstance(gates, pd.DataFrame):
            gate_rows = gates.to_dict('records')
        else:
            gate_rows = list(gates)

        lines: List[str] = []
        for g in gate_rows:
            name = g.get('GateName', 'Gate')
            width = g.get('Width', 1.0)
            height = g.get('Height', 1.0)
            invert = g.get('InvertElevation', 0.0)
            coef = g.get('GateCoefficient', 0.65)
            num_openings = int(g.get('NumOpenings', 1))
            stations = g.get('OpeningStations', [])

            lines.append(
                "Conn Gate Name Wd,H,Inv,GCoef,Exp_T,Exp_O,Exp_H,Type,WCoef,Is_Ogee,SpillHt,DesHd,#Openings\n"
            )
            lines.append(
                f"{name},{width},{height},{invert},{coef},0,1,0.5, 0 ,3, 0 ,,, {num_openings} ,0,0.8, 0 ,{coef},,0,0,0, 0 \n"
            )
            if stations:
                station_lines = GeomParser.format_fixed_width(
                    [float(s) for s in stations],
                    column_width=GeomLateral.FIXED_WIDTH_COLUMN,
                    values_per_line=GeomLateral.VALUES_PER_LINE,
                )
                lines.extend(station_lines)
            for idx in range(num_openings):
                lines.append(f"Conn Gate Opening={idx + 1},Opening #{idx + 1},0\n")
            lines.append("\n")

        return lines

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
                - Conn Routing Type (int): Routing method from the geometry file.
                  1 = standard connection (weir/weir-with-gates).
                  32 = bridge connection with full hydraulic sub-records
                  (deck, bridge opening cross-sections, piers, approach
                  cross-sections, and hydraulic coefficients in ``Conn BR:``
                  blocks).
                - HasGate (bool): Whether the connection has gate definitions
                - HasCulvert (bool): Whether the connection has culvert definitions

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> connections = GeomLateral.get_connections("model.g01")
            >>> bridges = connections[connections["Conn Routing Type"] == 32]
            >>> print(f"Found {len(bridges)} bridge connections")
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
                    'Conn Routing Type': routing_type,
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
    def get_connection_line_coords(
        geom_file: Union[str, Path],
        connection_name: str,
    ) -> pd.DataFrame:
        """
        Extract the polyline XY coordinates of a SA/2D connection line.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name

        Returns:
            pd.DataFrame: DataFrame with columns X, Y

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection not found or has no line coordinates
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

            start_idx, end_idx, block_lines, _ = block

            line_idx = None
            num_points = 0
            for bi, bline in enumerate(block_lines):
                if bline.startswith("Connection Line="):
                    num_points = GeomLateral._parse_optional_int(
                        GeomParser.extract_keyword_value(bline, "Connection Line")
                    ) or 0
                    line_idx = bi
                    break

            if line_idx is None or num_points == 0:
                raise ValueError(f"No connection line data for {connection_name}")

            total_values = num_points * 2
            values_fw: List[float] = []
            values_ws: List[float] = []
            data_start = line_idx + 1

            i = data_start
            while len(values_fw) < total_values and i < len(block_lines):
                if '=' in block_lines[i]:
                    break
                raw = block_lines[i].rstrip('\n')
                for j in range(0, len(raw), GeomLateral.CONN_LINE_COLUMN):
                    chunk = raw[j:j + GeomLateral.CONN_LINE_COLUMN].strip()
                    if chunk:
                        try:
                            values_fw.append(float(chunk))
                        except ValueError:
                            pass
                parts = raw.split()
                for p in parts:
                    try:
                        values_ws.append(float(p))
                    except ValueError:
                        pass
                i += 1

            values = values_fw if len(values_fw) >= len(values_ws) else values_ws

            xs = values[0::2]
            ys = values[1::2]

            return pd.DataFrame({'X': xs[:num_points], 'Y': ys[:num_points]})

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading connection line coords: {str(e)}")
            raise IOError(f"Failed to read connection line coords: {str(e)}")

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
    def set_connection(
        geom_file: Union[str, Path],
        connection_name: str,
        coordinates: List[Tuple[float, float]],
        upstream_area: str,
        downstream_area: str,
        *,
        routing_type: int = 1,
        weir_width: float = 100.0,
        weir_coef: float = 3.0,
        overflow_method_2d: bool = True,
        create_backup: bool = True,
    ) -> Optional[Path]:
        """
        Create or replace a SA/2D connection block in a geometry file.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            coordinates: List of (x, y) tuples defining the connection line
            upstream_area: Upstream storage/2D area name
            downstream_area: Downstream storage/2D area name
            routing_type: Routing type (1 = 2D structure, default)
            weir_width: Weir width in model units (default 100)
            weir_coef: Weir discharge coefficient (default 3.0)
            overflow_method_2d: Use 2D overflow method (default True)
            create_backup: Create .bak backup before writing (default True)

        Returns:
            Optional[Path]: Backup path when create_backup=True, else None

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If coordinates are empty
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")
        if not coordinates or len(coordinates) < 2:
            raise ValueError("coordinates must contain at least 2 (x, y) points")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            new_block = GeomLateral._build_connection_block(
                connection_name,
                coordinates,
                upstream_area,
                downstream_area,
                routing_type=routing_type,
                weir_width=weir_width,
                weir_coef=weir_coef,
                overflow_method_2d=overflow_method_2d,
            )

            existing = GeomLateral._find_connection_block(lines, connection_name)
            if existing is not None:
                start_idx, end_idx, _, _ = existing
                lines[start_idx:end_idx] = new_block
            else:
                insert_at = GeomLateral._connection_insert_index(lines)
                lines[insert_at:insert_at] = new_block

            return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing connection: {str(e)}")
            raise IOError(f"Failed to write connection: {str(e)}")

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

    @staticmethod
    @log_call
    def set_connection_gates(
        geom_file: Union[str, Path],
        connection_name: str,
        gates,
        create_backup: bool = True,
    ) -> Optional[Path]:
        """
        Write gate definitions into an existing connection block.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name (must already exist)
            gates: DataFrame or list of dicts with gate parameters:
                GateName, Width, Height, InvertElevation, GateCoefficient,
                NumOpenings, OpeningStations
            create_backup: Create .bak backup before writing (default True)

        Returns:
            Optional[Path]: Backup path when create_backup=True, else None

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection not found or gates are empty
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

            start_idx, end_idx, block_lines, _ = block

            gate_start = None
            gate_end = None
            for bi, bline in enumerate(block_lines):
                if bline.startswith("Conn Gate Name"):
                    if gate_start is None:
                        gate_start = bi
                elif bline.startswith("Conn Outlet Rating Curve="):
                    gate_end = bi
                    break

            new_gate_lines = GeomLateral._format_gate_block(gates)

            if gate_start is not None:
                abs_gate_start = start_idx + gate_start
                abs_gate_end = start_idx + (gate_end if gate_end is not None else len(block_lines))
                lines[abs_gate_start:abs_gate_end] = new_gate_lines
            else:
                insert_before = None
                for bi, bline in enumerate(block_lines):
                    if bline.startswith("Conn Outlet Rating Curve="):
                        insert_before = start_idx + bi
                        break
                if insert_before is None:
                    insert_before = end_idx
                lines[insert_before:insert_before] = new_gate_lines

            return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing connection gates: {str(e)}")
            raise IOError(f"Failed to write connection gates: {str(e)}")

    @staticmethod
    @log_call
    def delete_connection(
        geom_file: Union[str, Path],
        connection_name: str,
        create_backup: bool = True,
    ) -> Optional[Path]:
        """
        Remove a connection block entirely from a geometry file.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name to delete
            create_backup: Create .bak backup before writing (default True)

        Returns:
            Optional[Path]: Backup path when create_backup=True, else None

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection not found
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

            start_idx, end_idx, _, _ = block
            del lines[start_idx:end_idx]

            return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting connection: {str(e)}")
            raise IOError(f"Failed to delete connection: {str(e)}")

    @staticmethod
    @log_call
    def set_connection_profile_from_terrain(
        geom_file: Union[str, Path],
        connection_name: str,
        rasmap_path: Union[str, Path],
        geom_hdf_path: Union[str, Path],
        *,
        create_backup: bool = True,
    ) -> pd.DataFrame:
        """
        Sample terrain along the connection line and write as weir crest profile.

        Chains ``get_connection_line_coords()`` ->
        ``RasTerrainMod.get_terrain_profile()`` ->
        ``set_connection_profile()``.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            rasmap_path: Path to .rasmap file (for terrain layer discovery)
            geom_hdf_path: Path to geometry HDF file
            create_backup: Create .bak backup before writing (default True)

        Returns:
            pd.DataFrame: The sampled terrain profile (Station, Elevation)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection not found or has no line data
        """
        from ..RasTerrainMod import RasTerrainMod

        coords_df = GeomLateral.get_connection_line_coords(geom_file, connection_name)
        coords = list(zip(coords_df['X'].tolist(), coords_df['Y'].tolist()))

        profile_df = RasTerrainMod.get_terrain_profile(
            rasmap_path,
            geom_hdf_path,
            coords,
        )

        GeomLateral.set_connection_profile(
            geom_file,
            connection_name,
            profile_df,
            create_backup=create_backup,
        )

        return profile_df

    # ------------------------------------------------------------------
    # Bridge connection sub-record helpers (Conn BR:)
    # ------------------------------------------------------------------

    @staticmethod
    def _find_bridge_subrecord_range(block_lines: List[str]) -> Optional[Tuple[int, int]]:
        """Return (start, end) local indices for Conn BR: sub-records in a block."""
        start = None
        end = None
        for i, line in enumerate(block_lines):
            if line.startswith("Conn BR:"):
                if start is None:
                    start = i
                end = i + 1
                while end < len(block_lines) and not block_lines[end].startswith(("Conn BR:", "Connection=", "SA/2D Area Conn=", "Storage Area=")):
                    if '=' in block_lines[end]:
                        break
                    end += 1
        if start is None:
            return None
        return start, end

    @staticmethod
    def _parse_conn_br_deck(block_lines: List[str], start_idx: int) -> Tuple[Dict[str, Any], int]:
        """Parse Conn BR: Deck header and endpoint data. Returns (deck_dict, next_idx)."""
        i = start_idx
        deck: Dict[str, Any] = {
            'Distance': 0.0, 'Width': 0.0, 'WeirCoef': 0.0, 'Skew': 0.0,
            'NumUp': 0, 'NumDn': 0, 'MinLoCord': None, 'MaxHiCord': None,
            'MaxSubmerge': 0.0, 'IsOgee': 0,
        }

        if i >= len(block_lines) or not block_lines[i].startswith("Conn BR: Deck"):
            return deck, i

        i += 1
        if i < len(block_lines):
            parts = [p.strip() for p in block_lines[i].split(',')]
            if len(parts) > 0 and parts[0]: deck['Distance'] = GeomLateral._parse_optional_float(parts[0]) or 0.0
            if len(parts) > 1 and parts[1]: deck['Width'] = GeomLateral._parse_optional_float(parts[1]) or 0.0
            if len(parts) > 2 and parts[2]: deck['WeirCoef'] = GeomLateral._parse_optional_float(parts[2]) or 0.0
            if len(parts) > 3 and parts[3]: deck['Skew'] = GeomLateral._parse_optional_float(parts[3]) or 0.0
            if len(parts) > 4: deck['NumUp'] = GeomLateral._parse_optional_int(parts[4]) or 0
            if len(parts) > 5: deck['NumDn'] = GeomLateral._parse_optional_int(parts[5]) or 0
            if len(parts) > 8 and parts[8]: deck['MaxSubmerge'] = GeomLateral._parse_optional_float(parts[8]) or 0.0
            if len(parts) > 9: deck['IsOgee'] = GeomLateral._parse_optional_int(parts[9]) or 0
            i += 1

        num_up = deck['NumUp']
        num_dn = deck['NumDn']
        total_deck_values = (num_up + num_dn) * 3
        deck_values: List[float] = []

        while len(deck_values) < total_deck_values and i < len(block_lines):
            if block_lines[i].startswith("Conn BR:") or '=' in block_lines[i]:
                break
            deck_values.extend(GeomParser.parse_fixed_width(block_lines[i], GeomLateral.FIXED_WIDTH_COLUMN))
            i += 1

        up_vals = deck_values[:num_up * 3]
        dn_vals = deck_values[num_up * 3:(num_up + num_dn) * 3]

        up_data = []
        if num_up > 0 and len(up_vals) >= num_up * 3:
            for j in range(num_up):
                up_data.append({'Location': 'upstream', 'Station': up_vals[j],
                                'Elevation': up_vals[num_up + j], 'LowChord': up_vals[num_up * 2 + j]})

        dn_data = []
        if num_dn > 0 and len(dn_vals) >= num_dn * 3:
            for j in range(num_dn):
                dn_data.append({'Location': 'downstream', 'Station': dn_vals[j],
                                'Elevation': dn_vals[num_dn + j], 'LowChord': dn_vals[num_dn * 2 + j]})

        deck['Points'] = up_data + dn_data
        return deck, i

    @staticmethod
    def _parse_conn_br_xs(block_lines: List[str], start_idx: int, prefix: str, side: int) -> Tuple[Dict[str, Any], int]:
        """Parse a Conn BR: BR SE= or XS SE= record with bank stations and Manning's n."""
        keyword = f"Conn BR: {prefix} SE={side},"
        xs_data: Dict[str, Any] = {'Side': side, 'Prefix': prefix, 'NumPoints': 0,
                                    'Stations': [], 'Elevations': [],
                                    'BankStationLeft': None, 'BankStationRight': None,
                                    'ManningsN': []}
        i = start_idx

        if i >= len(block_lines) or not block_lines[i].startswith(keyword):
            return xs_data, i

        count_str = block_lines[i][len(keyword):].strip()
        num_points = GeomLateral._parse_optional_int(count_str) or 0
        xs_data['NumPoints'] = num_points
        i += 1

        if num_points > 0:
            total_values = num_points * 2
            values: List[float] = []
            while len(values) < total_values and i < len(block_lines):
                if block_lines[i].startswith("Conn BR:") or '=' in block_lines[i]:
                    break
                values.extend(GeomParser.parse_fixed_width(block_lines[i], GeomLateral.FIXED_WIDTH_COLUMN))
                i += 1
            xs_data['Stations'] = values[0::2][:num_points]
            xs_data['Elevations'] = values[1::2][:num_points]

        bank_keyword = f"Conn BR: {prefix} Bank Stations={side},"
        if i < len(block_lines) and block_lines[i].startswith(bank_keyword):
            bank_parts = block_lines[i][len(bank_keyword):].split(',')
            if len(bank_parts) >= 1:
                xs_data['BankStationLeft'] = GeomLateral._parse_optional_float(bank_parts[0])
            if len(bank_parts) >= 2:
                xs_data['BankStationRight'] = GeomLateral._parse_optional_float(bank_parts[1])
            i += 1

        mann_keyword = f"Conn BR: {prefix} Mann={side},"
        if i < len(block_lines) and block_lines[i].startswith(mann_keyword):
            mann_count_str = block_lines[i][len(mann_keyword):].strip()
            mann_count = GeomLateral._parse_optional_int(mann_count_str) or 0
            i += 1
            mann_values: List[float] = []
            while len(mann_values) < mann_count * 2 and i < len(block_lines):
                if block_lines[i].startswith("Conn BR:") or '=' in block_lines[i]:
                    break
                mann_values.extend(GeomParser.parse_fixed_width(block_lines[i], GeomLateral.FIXED_WIDTH_COLUMN))
                i += 1
            xs_data['ManningsN'] = list(zip(mann_values[0::2], mann_values[1::2]))

        return xs_data, i

    @staticmethod
    def _parse_conn_br_piers(block_lines: List[str], start_idx: int) -> Tuple[List[Dict[str, Any]], int]:
        """Parse all consecutive Conn BR: Pier records. Returns (pier_list, next_idx)."""
        piers: List[Dict[str, Any]] = []
        i = start_idx
        pier_keyword = "Conn BR: Pier Skew, UpSta & Num, DnSta & Num="

        while i < len(block_lines) and block_lines[i].startswith(pier_keyword):
            value_str = block_lines[i][len(pier_keyword):].strip()
            parts = [p.strip() for p in value_str.split(',')]

            pier: Dict[str, Any] = {
                'PierIndex': len(piers) + 1,
                'Skew': GeomLateral._parse_optional_float(parts[0]) if len(parts) > 0 else None,
                'UpstreamStation': GeomLateral._parse_optional_float(parts[1]) if len(parts) > 1 else None,
                'NumUpstreamPoints': GeomLateral._parse_optional_int(parts[2]) if len(parts) > 2 else 0,
                'DownstreamStation': GeomLateral._parse_optional_float(parts[3]) if len(parts) > 3 else None,
                'NumDownstreamPoints': GeomLateral._parse_optional_int(parts[4]) if len(parts) > 4 else 0,
                'UpstreamWidths': [], 'UpstreamElevations': [],
                'DownstreamWidths': [], 'DownstreamElevations': [],
            }
            i += 1
            num_up = pier['NumUpstreamPoints'] or 0
            num_dn = pier['NumDownstreamPoints'] or 0

            if num_up > 0 and i + 1 < len(block_lines):
                if '=' not in block_lines[i]:
                    pier['UpstreamWidths'] = GeomParser.parse_fixed_width(block_lines[i], GeomLateral.FIXED_WIDTH_COLUMN)[:num_up]
                    i += 1
                if i < len(block_lines) and '=' not in block_lines[i]:
                    pier['UpstreamElevations'] = GeomParser.parse_fixed_width(block_lines[i], GeomLateral.FIXED_WIDTH_COLUMN)[:num_up]
                    i += 1

            if num_dn > 0 and i + 1 < len(block_lines):
                if '=' not in block_lines[i]:
                    pier['DownstreamWidths'] = GeomParser.parse_fixed_width(block_lines[i], GeomLateral.FIXED_WIDTH_COLUMN)[:num_dn]
                    i += 1
                if i < len(block_lines) and '=' not in block_lines[i]:
                    pier['DownstreamElevations'] = GeomParser.parse_fixed_width(block_lines[i], GeomLateral.FIXED_WIDTH_COLUMN)[:num_dn]
                    i += 1

            piers.append(pier)

        return piers, i

    @staticmethod
    def _parse_bridge_subrecords(block_lines: List[str]) -> Dict[str, Any]:
        """Parse all Conn BR: sub-records in a connection block into a structured dict."""
        result: Dict[str, Any] = {
            'bridge_params': None,
            'deck': None,
            'bridge_xs': [None, None],
            'piers': [],
            'coefficients': None,
            'approach_xs': [None, None],
        }

        br_range = GeomLateral._find_bridge_subrecord_range(block_lines)
        if br_range is None:
            return result

        i = br_range[0]

        if i < len(block_lines) and block_lines[i].startswith("Conn BR: Bridge="):
            param_str = block_lines[i][len("Conn BR: Bridge="):].strip()
            result['bridge_params'] = [p.strip() for p in param_str.split(',')]
            i += 1

        if i < len(block_lines) and block_lines[i].startswith("Conn BR: Deck"):
            result['deck'], i = GeomLateral._parse_conn_br_deck(block_lines, i)

        for side in (1, 2):
            keyword = f"Conn BR: BR SE={side},"
            if i < len(block_lines) and block_lines[i].startswith(keyword):
                xs_data, i = GeomLateral._parse_conn_br_xs(block_lines, i, "BR", side)
                result['bridge_xs'][side - 1] = xs_data

        if i < len(block_lines) and block_lines[i].startswith("Conn BR: Pier Skew"):
            result['piers'], i = GeomLateral._parse_conn_br_piers(block_lines, i)

        if i < len(block_lines) and block_lines[i].startswith("Conn BR: BR Coef="):
            coef_str = block_lines[i][len("Conn BR: BR Coef="):].strip()
            result['coefficients'] = [p.strip() for p in coef_str.split(',')]
            i += 1

        for side in (1, 2):
            keyword = f"Conn BR: XS SE={side},"
            if i < len(block_lines) and block_lines[i].startswith(keyword):
                xs_data, i = GeomLateral._parse_conn_br_xs(block_lines, i, "XS", side)
                result['approach_xs'][side - 1] = xs_data

        return result

    # ------------------------------------------------------------------
    # Bridge connection public read methods
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def get_bridge_data(
        geom_file: Union[str, Path],
        connection_name: str,
    ) -> Dict[str, Any]:
        """
        Extract all bridge sub-record data for a connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name

        Returns:
            dict with keys: bridge_params, deck, bridge_xs, piers, coefficients, approach_xs

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection not found or has no bridge sub-records
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
            data = GeomLateral._parse_bridge_subrecords(block_lines)

            if data['bridge_params'] is None:
                raise ValueError(f"No bridge sub-records for connection {connection_name}")

            return data

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge data: {str(e)}")
            raise IOError(f"Failed to read bridge data: {str(e)}")

    @staticmethod
    @log_call
    def get_bridge_deck(
        geom_file: Union[str, Path],
        connection_name: str,
    ) -> pd.DataFrame:
        """
        Extract deck geometry for a bridge connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name

        Returns:
            pd.DataFrame with columns: Location, Station, Elevation, LowChord

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection or deck not found
        """
        data = GeomLateral.get_bridge_data(geom_file, connection_name)
        deck = data.get('deck')
        if deck is None or not deck.get('Points'):
            raise ValueError(f"No deck data for connection {connection_name}")

        return pd.DataFrame(deck['Points'])

    @staticmethod
    @log_call
    def get_bridge_piers(
        geom_file: Union[str, Path],
        connection_name: str,
    ) -> pd.DataFrame:
        """
        Extract pier definitions for a bridge connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name

        Returns:
            pd.DataFrame with columns: PierIndex, Skew, UpstreamStation,
            NumUpstreamPoints, DownstreamStation, NumDownstreamPoints,
            UpstreamWidths, UpstreamElevations, DownstreamWidths, DownstreamElevations

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection not found or has no piers
        """
        data = GeomLateral.get_bridge_data(geom_file, connection_name)
        piers = data.get('piers', [])
        if not piers:
            raise ValueError(f"No piers found for connection {connection_name}")

        return pd.DataFrame(piers)

    @staticmethod
    @log_call
    def get_bridge_xs(
        geom_file: Union[str, Path],
        connection_name: str,
        side: int = 1,
    ) -> pd.DataFrame:
        """
        Extract bridge cross-section for a connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            side: 1 for upstream, 2 for downstream

        Returns:
            pd.DataFrame with columns: Station, Elevation

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection or cross-section not found
        """
        data = GeomLateral.get_bridge_data(geom_file, connection_name)
        xs = data['bridge_xs'][side - 1]
        if xs is None or xs['NumPoints'] == 0:
            raise ValueError(f"No bridge XS (side {side}) for connection {connection_name}")

        return pd.DataFrame({'Station': xs['Stations'], 'Elevation': xs['Elevations']})

    @staticmethod
    @log_call
    def get_bridge_approach_xs(
        geom_file: Union[str, Path],
        connection_name: str,
        side: int = 1,
    ) -> pd.DataFrame:
        """
        Extract approach cross-section for a bridge connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            side: 1 for upstream, 2 for downstream

        Returns:
            pd.DataFrame with columns: Station, Elevation

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If connection or approach XS not found
        """
        data = GeomLateral.get_bridge_data(geom_file, connection_name)
        xs = data['approach_xs'][side - 1]
        if xs is None or xs['NumPoints'] == 0:
            raise ValueError(f"No approach XS (side {side}) for connection {connection_name}")

        return pd.DataFrame({'Station': xs['Stations'], 'Elevation': xs['Elevations']})

    # ------------------------------------------------------------------
    # Bridge sub-record formatters
    # ------------------------------------------------------------------

    @staticmethod
    def _format_conn_br_deck(deck: Dict[str, Any]) -> List[str]:
        """Format deck definition as Conn BR: lines."""
        lines: List[str] = []
        lines.append("Conn BR: Deck Dist Width WeirC Skew NumUp NumDn MinLoCord MaxHiCord MaxSubmerge Is_Ogee\n")
        num_up = deck.get('NumUp', 0)
        num_dn = deck.get('NumDn', 0)
        min_lo = deck.get('MinLoCord') or ''
        max_hi = deck.get('MaxHiCord') or ''
        lines.append(
            f"{deck.get('Distance', 0)},{deck.get('Width', 0)},{deck.get('WeirCoef', 0)},"
            f"{deck.get('Skew', 0)}, {num_up}, {num_dn}, {min_lo}, {max_hi}, "
            f"{deck.get('MaxSubmerge', 0.98)}, {deck.get('IsOgee', 0)}, 0,0,,\n"
        )

        points = deck.get('Points', [])
        up_pts = [p for p in points if p['Location'] == 'upstream']
        dn_pts = [p for p in points if p['Location'] == 'downstream']

        for group in (up_pts, dn_pts):
            if group:
                stations = [p['Station'] for p in group]
                elevations = [p['Elevation'] for p in group]
                lowchords = [p['LowChord'] for p in group]
                lines.extend(GeomParser.format_fixed_width(stations, GeomLateral.FIXED_WIDTH_COLUMN, GeomLateral.VALUES_PER_LINE))
                lines.extend(GeomParser.format_fixed_width(elevations, GeomLateral.FIXED_WIDTH_COLUMN, GeomLateral.VALUES_PER_LINE))
                lines.extend(GeomParser.format_fixed_width(lowchords, GeomLateral.FIXED_WIDTH_COLUMN, GeomLateral.VALUES_PER_LINE))

        return lines

    @staticmethod
    def _format_conn_br_xs(xs_data: Dict[str, Any], prefix: str) -> List[str]:
        """Format a bridge or approach cross-section (BR or XS) as Conn BR: lines."""
        side = xs_data.get('Side', 1)
        num_points = xs_data.get('NumPoints', 0)
        lines: List[str] = []

        lines.append(f"Conn BR: {prefix} SE={side},{num_points}\n")
        if num_points > 0:
            values = []
            for s, e in zip(xs_data.get('Stations', []), xs_data.get('Elevations', [])):
                values.extend([s, e])
            lines.extend(GeomParser.format_fixed_width(values, GeomLateral.FIXED_WIDTH_COLUMN, GeomLateral.VALUES_PER_LINE))

        left = xs_data.get('BankStationLeft')
        right = xs_data.get('BankStationRight')
        left_str = '' if left is None else str(left)
        right_str = '' if right is None else str(right)
        lines.append(f"Conn BR: {prefix} Bank Stations={side},{left_str},{right_str}\n")

        mann_n = xs_data.get('ManningsN', [])
        lines.append(f"Conn BR: {prefix} Mann={side},{len(mann_n)}\n")
        if mann_n:
            mann_values = []
            for station, n_val in mann_n:
                mann_values.extend([station, n_val])
            lines.extend(GeomParser.format_fixed_width(mann_values, GeomLateral.FIXED_WIDTH_COLUMN, GeomLateral.VALUES_PER_LINE, precision=3))

        return lines

    @staticmethod
    def _format_conn_br_piers(piers: List[Dict[str, Any]]) -> List[str]:
        """Format pier records as Conn BR: lines."""
        lines: List[str] = []
        for p in piers:
            skew = p.get('Skew')
            skew_str = '' if skew is None else str(skew)
            up_sta = p.get('UpstreamStation', 0)
            num_up = p.get('NumUpstreamPoints', 0)
            dn_sta = p.get('DownstreamStation', 0)
            num_dn = p.get('NumDownstreamPoints', 0)
            lines.append(
                f"Conn BR: Pier Skew, UpSta & Num, DnSta & Num="
                f"  ,{up_sta}, {num_up} ,{dn_sta}, {num_dn} , 0 , 0 , 0 ,,\n"
            )
            if num_up > 0:
                lines.extend(GeomParser.format_fixed_width(
                    p.get('UpstreamWidths', []), GeomLateral.FIXED_WIDTH_COLUMN, GeomLateral.VALUES_PER_LINE))
                lines.extend(GeomParser.format_fixed_width(
                    p.get('UpstreamElevations', []), GeomLateral.FIXED_WIDTH_COLUMN, GeomLateral.VALUES_PER_LINE))
            if num_dn > 0:
                lines.extend(GeomParser.format_fixed_width(
                    p.get('DownstreamWidths', []), GeomLateral.FIXED_WIDTH_COLUMN, GeomLateral.VALUES_PER_LINE))
                lines.extend(GeomParser.format_fixed_width(
                    p.get('DownstreamElevations', []), GeomLateral.FIXED_WIDTH_COLUMN, GeomLateral.VALUES_PER_LINE))
        return lines

    @staticmethod
    def _format_bridge_subrecords(bridge_data: Dict[str, Any]) -> List[str]:
        """Format a complete set of Conn BR: sub-records."""
        lines: List[str] = []

        params = bridge_data.get('bridge_params', ['-1', '0', '-1', '-1', '0'])
        lines.append(f"Conn BR: Bridge={','.join(str(p) for p in params)}\n")

        deck = bridge_data.get('deck')
        if deck is not None:
            lines.extend(GeomLateral._format_conn_br_deck(deck))
        else:
            lines.append("Conn BR: Deck Dist Width WeirC Skew NumUp NumDn MinLoCord MaxHiCord MaxSubmerge Is_Ogee\n")
            lines.append("0,0,0,0, 0, 0, , , 0.98, 0, 0,0,,\n")

        for side_idx in range(2):
            xs = bridge_data.get('bridge_xs', [None, None])[side_idx]
            if xs is not None:
                lines.extend(GeomLateral._format_conn_br_xs(xs, "BR"))
            else:
                side = side_idx + 1
                lines.append(f"Conn BR: BR SE={side},0\n")
                lines.append(f"Conn BR: BR Bank Stations={side},,\n")
                lines.append(f"Conn BR: BR Mann={side},0\n")

        piers = bridge_data.get('piers', [])
        if piers:
            lines.extend(GeomLateral._format_conn_br_piers(piers))

        coefs = bridge_data.get('coefficients', ['-1', '0', '0', '', '', '0.8', '0', '', '0', ''])
        lines.append(f"Conn BR: BR Coef={','.join(str(c) for c in coefs)}\n")

        for side_idx in range(2):
            xs = bridge_data.get('approach_xs', [None, None])[side_idx]
            if xs is not None:
                lines.extend(GeomLateral._format_conn_br_xs(xs, "XS"))
            else:
                side = side_idx + 1
                lines.append(f"Conn BR: XS SE={side},0\n")
                lines.append(f"Conn BR: XS Bank Stations={side},,\n")
                lines.append(f"Conn BR: XS Mann={side},0\n")

        return lines

    @staticmethod
    def _build_empty_bridge_skeleton() -> List[str]:
        """Generate the minimal empty Conn BR: skeleton."""
        return GeomLateral._format_bridge_subrecords({})

    # ------------------------------------------------------------------
    # Bridge connection public write methods
    # ------------------------------------------------------------------

    @staticmethod
    def _replace_bridge_subrecords(
        geom_file: Path,
        connection_name: str,
        new_bridge_lines: List[str],
        create_backup: bool = True,
    ) -> Optional[Path]:
        """Replace bridge sub-records in an existing connection block."""
        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        block = GeomLateral._find_connection_block(lines, connection_name)
        if block is None:
            raise ValueError(f"Connection not found: {connection_name}")

        start_idx, end_idx, block_lines, _ = block
        br_range = GeomLateral._find_bridge_subrecord_range(block_lines)

        if br_range is not None:
            abs_start = start_idx + br_range[0]
            abs_end = start_idx + br_range[1]
            lines[abs_start:abs_end] = new_bridge_lines
        else:
            lines[end_idx:end_idx] = new_bridge_lines

        return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

    @staticmethod
    @log_call
    def set_bridge_deck(
        geom_file: Union[str, Path],
        connection_name: str,
        deck_df: pd.DataFrame,
        *,
        deck_distance: float = 50.0,
        weir_coef: float = 2.6,
        create_backup: bool = True,
    ) -> Optional[Path]:
        """
        Write deck geometry for a bridge connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            deck_df: DataFrame with columns Location, Station, Elevation, LowChord
            deck_distance: Distance between upstream and downstream faces
            weir_coef: Weir discharge coefficient for deck overflow
            create_backup: Create .bak backup before writing (default True)

        Returns:
            Optional[Path]: Backup path when create_backup=True, else None
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            data = GeomLateral.get_bridge_data(geom_file, connection_name)
            up_pts = deck_df[deck_df['Location'] == 'upstream'].to_dict('records')
            dn_pts = deck_df[deck_df['Location'] == 'downstream'].to_dict('records')

            data['deck'] = {
                'Distance': deck_distance,
                'Width': data['deck']['Width'] if data['deck'] else 0.0,
                'WeirCoef': weir_coef,
                'Skew': data['deck']['Skew'] if data['deck'] else 0.0,
                'NumUp': len(up_pts),
                'NumDn': len(dn_pts),
                'MaxSubmerge': data['deck']['MaxSubmerge'] if data['deck'] else 0.98,
                'IsOgee': data['deck']['IsOgee'] if data['deck'] else 0,
                'Points': up_pts + dn_pts,
            }

            new_lines = GeomLateral._format_bridge_subrecords(data)
            return GeomLateral._replace_bridge_subrecords(geom_file, connection_name, new_lines, create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge deck: {str(e)}")
            raise IOError(f"Failed to write bridge deck: {str(e)}")

    @staticmethod
    @log_call
    def set_bridge_piers(
        geom_file: Union[str, Path],
        connection_name: str,
        piers,
        *,
        create_backup: bool = True,
    ) -> Optional[Path]:
        """
        Write pier definitions for a bridge connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            piers: DataFrame or list of dicts with pier data
            create_backup: Create .bak backup before writing (default True)

        Returns:
            Optional[Path]: Backup path when create_backup=True, else None
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            if isinstance(piers, pd.DataFrame):
                pier_list = piers.to_dict('records')
            else:
                pier_list = list(piers)

            data = GeomLateral.get_bridge_data(geom_file, connection_name)
            data['piers'] = pier_list

            new_lines = GeomLateral._format_bridge_subrecords(data)
            return GeomLateral._replace_bridge_subrecords(geom_file, connection_name, new_lines, create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge piers: {str(e)}")
            raise IOError(f"Failed to write bridge piers: {str(e)}")

    @staticmethod
    @log_call
    def set_bridge_xs(
        geom_file: Union[str, Path],
        connection_name: str,
        sta_elev_df: pd.DataFrame,
        side: int = 1,
        *,
        bank_stations: Optional[Tuple[float, float]] = None,
        mannings_n: Optional[List[Tuple[float, float]]] = None,
        create_backup: bool = True,
    ) -> Optional[Path]:
        """
        Write bridge cross-section for a connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            sta_elev_df: DataFrame with Station and Elevation columns
            side: 1 for upstream, 2 for downstream
            bank_stations: (left, right) bank station tuple
            mannings_n: List of (station, n_value) tuples
            create_backup: Create .bak backup before writing (default True)

        Returns:
            Optional[Path]: Backup path when create_backup=True, else None
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            data = GeomLateral.get_bridge_data(geom_file, connection_name)

            xs_data = {
                'Side': side,
                'Prefix': 'BR',
                'NumPoints': len(sta_elev_df),
                'Stations': sta_elev_df['Station'].tolist(),
                'Elevations': sta_elev_df['Elevation'].tolist(),
                'BankStationLeft': bank_stations[0] if bank_stations else (
                    data['bridge_xs'][side - 1]['BankStationLeft'] if data['bridge_xs'][side - 1] else None),
                'BankStationRight': bank_stations[1] if bank_stations else (
                    data['bridge_xs'][side - 1]['BankStationRight'] if data['bridge_xs'][side - 1] else None),
                'ManningsN': mannings_n if mannings_n is not None else (
                    data['bridge_xs'][side - 1]['ManningsN'] if data['bridge_xs'][side - 1] else []),
            }
            data['bridge_xs'][side - 1] = xs_data

            new_lines = GeomLateral._format_bridge_subrecords(data)
            return GeomLateral._replace_bridge_subrecords(geom_file, connection_name, new_lines, create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge XS: {str(e)}")
            raise IOError(f"Failed to write bridge XS: {str(e)}")

    @staticmethod
    @log_call
    def set_bridge_approach_xs(
        geom_file: Union[str, Path],
        connection_name: str,
        sta_elev_df: pd.DataFrame,
        side: int = 1,
        *,
        bank_stations: Optional[Tuple[float, float]] = None,
        mannings_n: Optional[List[Tuple[float, float]]] = None,
        create_backup: bool = True,
    ) -> Optional[Path]:
        """
        Write approach cross-section for a bridge connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            sta_elev_df: DataFrame with Station and Elevation columns
            side: 1 for upstream, 2 for downstream
            bank_stations: (left, right) bank station tuple
            mannings_n: List of (station, n_value) tuples
            create_backup: Create .bak backup before writing (default True)

        Returns:
            Optional[Path]: Backup path when create_backup=True, else None
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            data = GeomLateral.get_bridge_data(geom_file, connection_name)

            xs_data = {
                'Side': side,
                'Prefix': 'XS',
                'NumPoints': len(sta_elev_df),
                'Stations': sta_elev_df['Station'].tolist(),
                'Elevations': sta_elev_df['Elevation'].tolist(),
                'BankStationLeft': bank_stations[0] if bank_stations else (
                    data['approach_xs'][side - 1]['BankStationLeft'] if data['approach_xs'][side - 1] else None),
                'BankStationRight': bank_stations[1] if bank_stations else (
                    data['approach_xs'][side - 1]['BankStationRight'] if data['approach_xs'][side - 1] else None),
                'ManningsN': mannings_n if mannings_n is not None else (
                    data['approach_xs'][side - 1]['ManningsN'] if data['approach_xs'][side - 1] else []),
            }
            data['approach_xs'][side - 1] = xs_data

            new_lines = GeomLateral._format_bridge_subrecords(data)
            return GeomLateral._replace_bridge_subrecords(geom_file, connection_name, new_lines, create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge approach XS: {str(e)}")
            raise IOError(f"Failed to write bridge approach XS: {str(e)}")

    @staticmethod
    @log_call
    def set_bridge_coefficients(
        geom_file: Union[str, Path],
        connection_name: str,
        coefficients: List[str],
        *,
        create_backup: bool = True,
    ) -> Optional[Path]:
        """
        Write bridge hydraulic coefficients for a connection.

        Parameters:
            geom_file: Path to geometry file
            connection_name: Connection name
            coefficients: List of coefficient strings matching Conn BR: BR Coef= format
            create_backup: Create .bak backup before writing (default True)

        Returns:
            Optional[Path]: Backup path when create_backup=True, else None
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            data = GeomLateral.get_bridge_data(geom_file, connection_name)
            data['coefficients'] = coefficients

            new_lines = GeomLateral._format_bridge_subrecords(data)
            return GeomLateral._replace_bridge_subrecords(geom_file, connection_name, new_lines, create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge coefficients: {str(e)}")
            raise IOError(f"Failed to write bridge coefficients: {str(e)}")
