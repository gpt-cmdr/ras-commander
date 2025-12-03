"""
GeomBridge - Bridge operations for HEC-RAS geometry files

This module provides functionality for reading bridge structure data
from HEC-RAS plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_bridges() - List all bridges with metadata
- get_deck() - Read deck geometry (stations, elevations, lowchord)
- get_piers() - Read pier definitions (widths, elevations)
- get_abutment() - Read abutment geometry
- get_approach_sections() - Read BR U/BR D approach sections
- get_coefficients() - Read hydraulic coefficients
- get_htab() - Read hydraulic table parameters

Example Usage:
    >>> from ras_commander import GeomBridge
    >>> from pathlib import Path
    >>>
    >>> # List all bridges
    >>> geom_file = Path("model.g08")
    >>> bridges_df = GeomBridge.get_bridges(geom_file)
    >>> print(f"Found {len(bridges_df)} bridges")
    >>>
    >>> # Get deck geometry
    >>> deck_df = GeomBridge.get_deck(geom_file, "River", "Reach", "25548")
    >>> print(deck_df)

Technical Notes:
    - Uses FORTRAN-era fixed-width format (8-char columns for numeric data)
    - Return types are all DataFrames (breaking change from RasStruct Dict returns)
"""

from pathlib import Path
from typing import Union, Optional, List, Dict, Any
import pandas as pd
import numpy as np

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomBridge:
    """
    Operations for parsing HEC-RAS bridges in geometry files.

    All methods are static and designed to be used without instantiation.
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8
    VALUES_PER_LINE = 10
    DEFAULT_SEARCH_RANGE = 100
    MAX_PARSE_LINES = 200

    @staticmethod
    def _find_bridge(lines: List[str], river: str, reach: str, rs: str) -> Optional[int]:
        """Find bridge/culvert section and return line index of 'Bridge Culvert-' marker."""
        current_river = None
        current_reach = None
        last_rs = None

        for i, line in enumerate(lines):
            if line.startswith("River Reach="):
                values = GeomParser.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]

            elif line.startswith("Type RM Length L Ch R ="):
                value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
                values = [v.strip() for v in value_str.split(',')]
                if len(values) > 1:
                    last_rs = values[1]

            elif line.startswith("Bridge Culvert-"):
                if (current_river == river and
                    current_reach == reach and
                    last_rs == rs):
                    logger.debug(f"Found bridge at line {i}: {river}/{reach}/RS {rs}")
                    return i

        logger.debug(f"Bridge not found: {river}/{reach}/RS {rs}")
        return None

    @staticmethod
    def _parse_bridge_header(line: str) -> Dict[str, Any]:
        """Parse 'Bridge Culvert-' header line into dict of flags."""
        value_part = line.replace("Bridge Culvert-", "").strip()
        parts = [p.strip() for p in value_part.split(',')]

        flags = {}
        flag_names = ['flag1', 'flag2', 'flag3', 'flag4', 'flag5']
        for i, name in enumerate(flag_names):
            if i < len(parts) and parts[i]:
                try:
                    flags[name] = int(parts[i])
                except ValueError:
                    flags[name] = None
            else:
                flags[name] = None

        return flags

    @staticmethod
    @log_call
    def get_bridges(geom_file: Union[str, Path],
                   river: Optional[str] = None,
                   reach: Optional[str] = None) -> pd.DataFrame:
        """
        List all bridges/culverts in geometry file with metadata.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: Optional filter by river name (case-sensitive)
            reach: Optional filter by reach name (case-sensitive)

        Returns:
            pd.DataFrame with columns:
            - River, Reach, RS: Location identifiers
            - NodeName: Bridge name/description
            - NumDecks: Number of deck spans
            - DeckWidth: Bridge deck width
            - WeirCoefficient: Weir flow coefficient
            - Skew: Bridge skew angle
            - NumPiers: Count of pier definitions
            - HasAbutment: Boolean indicating abutment presence
            - HTabHWMax: Maximum headwater elevation

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> bridges = GeomBridge.get_bridges("model.g08")
            >>> print(f"Found {len(bridges)} bridges")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            bridges = []
            current_river = None
            current_reach = None
            last_rs = None
            last_node_name = None
            last_edited = None

            i = 0
            while i < len(lines):
                line = lines[i]

                if line.startswith("River Reach="):
                    values = GeomParser.extract_comma_list(line, "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]

                elif line.startswith("Type RM Length L Ch R ="):
                    value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
                    values = [v.strip() for v in value_str.split(',')]
                    if len(values) > 1:
                        last_rs = values[1]

                elif line.startswith("Node Name="):
                    last_node_name = GeomParser.extract_keyword_value(line, "Node Name")

                elif line.startswith("Node Last Edited Time="):
                    last_edited = GeomParser.extract_keyword_value(line, "Node Last Edited Time")

                elif line.startswith("Bridge Culvert-"):
                    if river is not None and current_river != river:
                        i += 1
                        continue
                    if reach is not None and current_reach != reach:
                        i += 1
                        continue

                    bridge_flags = GeomBridge._parse_bridge_header(line)

                    bridge_data = {
                        'River': current_river,
                        'Reach': current_reach,
                        'RS': last_rs,
                        'NodeName': last_node_name,
                        'NumDecks': None,
                        'DeckWidth': None,
                        'WeirCoefficient': None,
                        'Skew': None,
                        'MaxSubmergence': None,
                        'NumPiers': 0,
                        'HasAbutment': False,
                        'HTabHWMax': None,
                        'NodeLastEdited': last_edited
                    }

                    pier_count = 0
                    for j in range(i + 1, min(i + GeomBridge.DEFAULT_SEARCH_RANGE, len(lines))):
                        search_line = lines[j]

                        if search_line.startswith("Deck Dist Width WeirC"):
                            if j + 1 < len(lines):
                                param_line = lines[j + 1]
                                parts = [p.strip() for p in param_line.split(',')]

                                if len(parts) > 0 and parts[0]:
                                    try: bridge_data['NumDecks'] = int(parts[0])
                                    except: pass
                                if len(parts) > 2 and parts[2]:
                                    try: bridge_data['DeckWidth'] = float(parts[2])
                                    except: pass
                                if len(parts) > 3 and parts[3]:
                                    try: bridge_data['WeirCoefficient'] = float(parts[3])
                                    except: pass
                                if len(parts) > 4 and parts[4]:
                                    try: bridge_data['Skew'] = float(parts[4])
                                    except: pass
                                if len(parts) > 9 and parts[9]:
                                    try: bridge_data['MaxSubmergence'] = float(parts[9])
                                    except: pass

                        elif search_line.startswith("Pier Skew, UpSta & Num"):
                            pier_count += 1

                        elif search_line.startswith("Abutment Skew #Up #Dn="):
                            bridge_data['HasAbutment'] = True

                        elif search_line.startswith("BC HTab HWMax="):
                            val = GeomParser.extract_keyword_value(search_line, "BC HTab HWMax")
                            if val:
                                try: bridge_data['HTabHWMax'] = float(val)
                                except: pass

                        elif search_line.startswith("Type RM Length L Ch R ="):
                            break

                    bridge_data['NumPiers'] = pier_count
                    bridges.append(bridge_data)
                    last_node_name = None
                    last_edited = None

                i += 1

            df = pd.DataFrame(bridges)
            logger.info(f"Found {len(df)} bridges in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridges: {str(e)}")
            raise IOError(f"Failed to read bridges: {str(e)}")

    @staticmethod
    @log_call
    def get_deck(geom_file: Union[str, Path],
                river: str,
                reach: str,
                rs: str) -> pd.DataFrame:
        """
        Extract complete deck geometry for a bridge.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            pd.DataFrame with columns:
            - Location: 'upstream' or 'downstream'
            - Station: Station values
            - Elevation: Deck elevation values
            - LowChord: Low chord elevation values

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found

        Example:
            >>> deck = GeomBridge.get_deck("model.g08", "River", "Reach", "25548")
            >>> upstream = deck[deck['Location'] == 'upstream']
            >>> print(f"Upstream deck has {len(upstream)} points")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            deck_data = []

            for j in range(bridge_idx, min(bridge_idx + GeomBridge.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                if line.startswith("Deck Dist Width WeirC"):
                    if j + 1 < len(lines):
                        param_line = lines[j + 1]
                        parts = [p.strip() for p in param_line.split(',')]

                        num_up = 0
                        num_dn = 0
                        if len(parts) > 5 and parts[5]:
                            try: num_up = int(parts[5])
                            except: pass
                        if len(parts) > 6 and parts[6]:
                            try: num_dn = int(parts[6])
                            except: pass

                        # Read upstream data
                        if num_up > 0:
                            data_start = j + 2
                            all_up_values = []

                            for k in range(data_start, min(data_start + 10, len(lines))):
                                data_line = lines[k]
                                if '=' in data_line:
                                    break
                                values = GeomParser.parse_fixed_width(data_line, 8)
                                all_up_values.extend(values)
                                if len(all_up_values) >= num_up * 3:
                                    break

                            if len(all_up_values) >= num_up * 3:
                                stations = all_up_values[:num_up]
                                elevations = all_up_values[num_up:num_up*2]
                                lowchords = all_up_values[num_up*2:num_up*3]

                                for idx in range(min(len(stations), len(elevations), len(lowchords))):
                                    deck_data.append({
                                        'Location': 'upstream',
                                        'Station': stations[idx],
                                        'Elevation': elevations[idx],
                                        'LowChord': lowchords[idx]
                                    })

                        # Read downstream data
                        if num_dn > 0 and num_up > 0:
                            expected_up_lines = (num_up * 3 + 9) // 10 + 1
                            dn_start = j + 2 + expected_up_lines

                            all_dn_values = []
                            for k in range(dn_start, min(dn_start + 10, len(lines))):
                                if k >= len(lines):
                                    break
                                data_line = lines[k]
                                if '=' in data_line or data_line.startswith("Pier"):
                                    break
                                values = GeomParser.parse_fixed_width(data_line, 8)
                                all_dn_values.extend(values)
                                if len(all_dn_values) >= num_dn * 3:
                                    break

                            if len(all_dn_values) >= num_dn * 3:
                                stations = all_dn_values[:num_dn]
                                elevations = all_dn_values[num_dn:num_dn*2]
                                lowchords = all_dn_values[num_dn*2:num_dn*3]

                                for idx in range(min(len(stations), len(elevations), len(lowchords))):
                                    deck_data.append({
                                        'Location': 'downstream',
                                        'Station': stations[idx],
                                        'Elevation': elevations[idx],
                                        'LowChord': lowchords[idx]
                                    })

                    break

            df = pd.DataFrame(deck_data)
            logger.info(f"Extracted deck geometry for {river}/{reach}/RS {rs}: {len(df)} points")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge deck: {str(e)}")
            raise IOError(f"Failed to read bridge deck: {str(e)}")

    @staticmethod
    @log_call
    def get_piers(geom_file: Union[str, Path],
                 river: str,
                 reach: str,
                 rs: str) -> pd.DataFrame:
        """
        Extract all pier definitions for a bridge.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            pd.DataFrame with columns:
            - PierIndex: Pier number (1, 2, 3...)
            - UpstreamStation, DownstreamStation: Pier locations
            - NumUpstreamPoints, NumDownstreamPoints: Point counts
            - UpstreamWidths, UpstreamElevations: Lists
            - DownstreamWidths, DownstreamElevations: Lists

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found or has no piers

        Example:
            >>> piers = GeomBridge.get_piers("model.g08", "River", "Reach", "25548")
            >>> print(f"Found {len(piers)} piers")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            piers = []
            pier_index = 0

            i = bridge_idx
            while i < min(bridge_idx + GeomBridge.DEFAULT_SEARCH_RANGE, len(lines)):
                line = lines[i]

                if line.startswith("Type RM Length L Ch R =") and i > bridge_idx + 5:
                    break

                if line.startswith("Pier Skew, UpSta & Num, DnSta & Num="):
                    pier_index += 1

                    value_str = GeomParser.extract_keyword_value(line, "Pier Skew, UpSta & Num, DnSta & Num")
                    parts = [p.strip() for p in value_str.split(',')]

                    pier_data = {
                        'PierIndex': pier_index,
                        'UpstreamStation': None,
                        'NumUpstreamPoints': 0,
                        'DownstreamStation': None,
                        'NumDownstreamPoints': 0,
                        'UpstreamWidths': [],
                        'UpstreamElevations': [],
                        'DownstreamWidths': [],
                        'DownstreamElevations': []
                    }

                    if len(parts) > 1 and parts[1]:
                        try: pier_data['UpstreamStation'] = float(parts[1])
                        except: pass
                    if len(parts) > 2 and parts[2]:
                        try: pier_data['NumUpstreamPoints'] = int(parts[2])
                        except: pass
                    if len(parts) > 3 and parts[3]:
                        try: pier_data['DownstreamStation'] = float(parts[3])
                        except: pass
                    if len(parts) > 4 and parts[4]:
                        try: pier_data['NumDownstreamPoints'] = int(parts[4])
                        except: pass

                    num_up = pier_data['NumUpstreamPoints']
                    num_dn = pier_data['NumDownstreamPoints']

                    if num_up > 0 and i + 2 < len(lines):
                        widths_line = lines[i + 1]
                        if '=' not in widths_line:
                            pier_data['UpstreamWidths'] = GeomParser.parse_fixed_width(widths_line, 8)[:num_up]

                        if i + 2 < len(lines):
                            elev_line = lines[i + 2]
                            if '=' not in elev_line:
                                pier_data['UpstreamElevations'] = GeomParser.parse_fixed_width(elev_line, 8)[:num_up]

                    if num_dn > 0 and i + 4 < len(lines):
                        widths_line = lines[i + 3]
                        if '=' not in widths_line:
                            pier_data['DownstreamWidths'] = GeomParser.parse_fixed_width(widths_line, 8)[:num_dn]

                        if i + 4 < len(lines):
                            elev_line = lines[i + 4]
                            if '=' not in elev_line:
                                pier_data['DownstreamElevations'] = GeomParser.parse_fixed_width(elev_line, 8)[:num_dn]

                    piers.append(pier_data)
                    i += 4

                i += 1

            if not piers:
                raise ValueError(f"No piers found for bridge: {river}/{reach}/RS {rs}")

            df = pd.DataFrame(piers)
            logger.info(f"Extracted {len(df)} piers for {river}/{reach}/RS {rs}")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge piers: {str(e)}")
            raise IOError(f"Failed to read bridge piers: {str(e)}")

    @staticmethod
    @log_call
    def get_abutment(geom_file: Union[str, Path],
                    river: str,
                    reach: str,
                    rs: str) -> pd.DataFrame:
        """
        Extract abutment geometry for a bridge (if present).

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            pd.DataFrame with columns:
            - Location: 'upstream' or 'downstream'
            - Station: Abutment station values
            - Parameter: Abutment parameter values

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found or has no abutment

        Example:
            >>> abutment = GeomBridge.get_abutment("model.g08", "River", "Reach", "25548")
            >>> print(f"Abutment has {len(abutment)} points")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            abutment_data = []

            for j in range(bridge_idx, min(bridge_idx + GeomBridge.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                if line.startswith("Type RM Length L Ch R =") and j > bridge_idx + 5:
                    break

                if line.startswith("Abutment Skew #Up #Dn="):
                    value_str = GeomParser.extract_keyword_value(line, "Abutment Skew #Up #Dn")
                    parts = [p.strip() for p in value_str.split(',')]

                    num_up = 0
                    num_dn = 0
                    if len(parts) > 0 and parts[0]:
                        try: num_up = int(parts[0])
                        except: pass
                    if len(parts) > 1 and parts[1]:
                        try: num_dn = int(parts[1])
                        except: pass

                    if num_up > 0 and j + 2 < len(lines):
                        sta_line = lines[j + 1]
                        if '=' not in sta_line:
                            stations = GeomParser.parse_fixed_width(sta_line, 8)[:num_up]

                        param_line = lines[j + 2]
                        if '=' not in param_line:
                            params = GeomParser.parse_fixed_width(param_line, 8)[:num_up]

                        for idx in range(min(len(stations), len(params))):
                            abutment_data.append({
                                'Location': 'upstream',
                                'Station': stations[idx],
                                'Parameter': params[idx]
                            })

                    if num_dn > 0 and j + 4 < len(lines):
                        sta_line = lines[j + 3]
                        if '=' not in sta_line:
                            stations = GeomParser.parse_fixed_width(sta_line, 8)[:num_dn]

                        param_line = lines[j + 4]
                        if '=' not in param_line:
                            params = GeomParser.parse_fixed_width(param_line, 8)[:num_dn]

                        for idx in range(min(len(stations), len(params))):
                            abutment_data.append({
                                'Location': 'downstream',
                                'Station': stations[idx],
                                'Parameter': params[idx]
                            })

                    break

            if not abutment_data:
                raise ValueError(f"No abutment found for bridge: {river}/{reach}/RS {rs}")

            df = pd.DataFrame(abutment_data)
            logger.info(f"Extracted abutment for {river}/{reach}/RS {rs}: {len(df)} points")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge abutment: {str(e)}")
            raise IOError(f"Failed to read bridge abutment: {str(e)}")

    @staticmethod
    @log_call
    def get_approach_sections(geom_file: Union[str, Path],
                             river: str,
                             reach: str,
                             rs: str) -> pd.DataFrame:
        """
        Extract BR U (upstream) and BR D (downstream) approach section geometry.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            pd.DataFrame with columns:
            - Location: 'upstream' or 'downstream'
            - DataType: 'station_elevation', 'mannings_n', or 'banks'
            - Station, Elevation, N_Value, LeftBank, RightBank: Data values

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found

        Example:
            >>> approach = GeomBridge.get_approach_sections("model.g08", "River", "Reach", "25548")
            >>> upstream_xs = approach[(approach['Location'] == 'upstream') & (approach['DataType'] == 'station_elevation')]
            >>> print(f"Upstream XS has {len(upstream_xs)} points")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            approach_data = []

            for j in range(bridge_idx, min(bridge_idx + GeomBridge.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                if line.startswith("Type RM Length L Ch R =") and j > bridge_idx + 5:
                    break

                # Upstream station/elevation
                if line.startswith("BR U #Sta/Elev="):
                    count_str = GeomParser.extract_keyword_value(line, "BR U #Sta/Elev")
                    count = int(count_str.strip())

                    values = []
                    k = j + 1
                    while len(values) < count * 2 and k < len(lines):
                        if '=' in lines[k]:
                            break
                        values.extend(GeomParser.parse_fixed_width(lines[k], 8))
                        k += 1

                    stations = values[0::2]
                    elevations = values[1::2]

                    for idx in range(min(len(stations), len(elevations))):
                        approach_data.append({
                            'Location': 'upstream',
                            'DataType': 'station_elevation',
                            'Station': stations[idx],
                            'Elevation': elevations[idx],
                            'N_Value': None,
                            'LeftBank': None,
                            'RightBank': None
                        })

                # Downstream station/elevation
                elif line.startswith("BR D #Sta/Elev="):
                    count_str = GeomParser.extract_keyword_value(line, "BR D #Sta/Elev")
                    count = int(count_str.strip())

                    values = []
                    k = j + 1
                    while len(values) < count * 2 and k < len(lines):
                        if '=' in lines[k]:
                            break
                        values.extend(GeomParser.parse_fixed_width(lines[k], 8))
                        k += 1

                    stations = values[0::2]
                    elevations = values[1::2]

                    for idx in range(min(len(stations), len(elevations))):
                        approach_data.append({
                            'Location': 'downstream',
                            'DataType': 'station_elevation',
                            'Station': stations[idx],
                            'Elevation': elevations[idx],
                            'N_Value': None,
                            'LeftBank': None,
                            'RightBank': None
                        })

                # Upstream banks
                elif line.startswith("BR U Banks="):
                    val = GeomParser.extract_keyword_value(line, "BR U Banks")
                    parts = [p.strip() for p in val.split(',')]
                    left = float(parts[0]) if len(parts) > 0 and parts[0] else None
                    right = float(parts[1]) if len(parts) > 1 and parts[1] else None
                    approach_data.append({
                        'Location': 'upstream',
                        'DataType': 'banks',
                        'Station': None,
                        'Elevation': None,
                        'N_Value': None,
                        'LeftBank': left,
                        'RightBank': right
                    })

                # Downstream banks
                elif line.startswith("BR D Banks="):
                    val = GeomParser.extract_keyword_value(line, "BR D Banks")
                    parts = [p.strip() for p in val.split(',')]
                    left = float(parts[0]) if len(parts) > 0 and parts[0] else None
                    right = float(parts[1]) if len(parts) > 1 and parts[1] else None
                    approach_data.append({
                        'Location': 'downstream',
                        'DataType': 'banks',
                        'Station': None,
                        'Elevation': None,
                        'N_Value': None,
                        'LeftBank': left,
                        'RightBank': right
                    })

            df = pd.DataFrame(approach_data)
            logger.info(f"Extracted approach sections for {river}/{reach}/RS {rs}")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading approach sections: {str(e)}")
            raise IOError(f"Failed to read approach sections: {str(e)}")

    @staticmethod
    @log_call
    def get_coefficients(geom_file: Union[str, Path],
                        river: str,
                        reach: str,
                        rs: str) -> pd.DataFrame:
        """
        Extract bridge hydraulic coefficients and parameters.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            pd.DataFrame with columns:
            - ParameterType: 'br_coef', 'wspro', or 'bc_design'
            - Index: Parameter index
            - Value: Parameter value

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found

        Example:
            >>> coef = GeomBridge.get_coefficients("model.g08", "River", "Reach", "25548")
            >>> br_coefs = coef[coef['ParameterType'] == 'br_coef']
            >>> print(br_coefs)
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            coef_data = []

            for j in range(bridge_idx, min(bridge_idx + GeomBridge.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                if line.startswith("Type RM Length L Ch R =") and j > bridge_idx + 5:
                    break

                if line.startswith("BR Coef="):
                    val = GeomParser.extract_keyword_value(line, "BR Coef")
                    parts = [p.strip() for p in val.split(',')]
                    for idx, p in enumerate(parts):
                        if p:
                            try:
                                coef_data.append({
                                    'ParameterType': 'br_coef',
                                    'Index': idx,
                                    'Value': float(p)
                                })
                            except ValueError:
                                coef_data.append({
                                    'ParameterType': 'br_coef',
                                    'Index': idx,
                                    'Value': p
                                })

                elif line.startswith("WSPro="):
                    val = GeomParser.extract_keyword_value(line, "WSPro")
                    parts = [p.strip() for p in val.split(',')]
                    for idx, p in enumerate(parts):
                        if p:
                            try:
                                coef_data.append({
                                    'ParameterType': 'wspro',
                                    'Index': idx,
                                    'Value': float(p)
                                })
                            except ValueError:
                                coef_data.append({
                                    'ParameterType': 'wspro',
                                    'Index': idx,
                                    'Value': p
                                })

                elif line.startswith("BC Design="):
                    val = GeomParser.extract_keyword_value(line, "BC Design")
                    parts = [p.strip() for p in val.split(',')]
                    for idx, p in enumerate(parts):
                        if p:
                            coef_data.append({
                                'ParameterType': 'bc_design',
                                'Index': idx,
                                'Value': p
                            })

            df = pd.DataFrame(coef_data)
            logger.info(f"Extracted coefficients for {river}/{reach}/RS {rs}")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge coefficients: {str(e)}")
            raise IOError(f"Failed to read bridge coefficients: {str(e)}")

    @staticmethod
    @log_call
    def get_htab(geom_file: Union[str, Path],
                river: str,
                reach: str,
                rs: str) -> pd.DataFrame:
        """
        Extract bridge hydraulic table (HTab) parameters.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            pd.DataFrame with columns:
            - Parameter: Parameter name (HWMax, TWMax, MaxFlow, etc.)
            - Value: Parameter value

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found

        Example:
            >>> htab = GeomBridge.get_htab("model.g08", "River", "Reach", "25548")
            >>> hw_max = htab[htab['Parameter'] == 'HWMax']['Value'].values[0]
            >>> print(f"HW Max: {hw_max}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            htab_data = []

            for j in range(bridge_idx, min(bridge_idx + GeomBridge.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                if line.startswith("Type RM Length L Ch R =") and j > bridge_idx + 5:
                    break

                if line.startswith("BC HTab HWMax="):
                    val = GeomParser.extract_keyword_value(line, "BC HTab HWMax")
                    if val:
                        try:
                            htab_data.append({'Parameter': 'HWMax', 'Value': float(val)})
                        except: pass

                elif line.startswith("BC HTab TWMax="):
                    val = GeomParser.extract_keyword_value(line, "BC HTab TWMax")
                    if val:
                        try:
                            htab_data.append({'Parameter': 'TWMax', 'Value': float(val)})
                        except: pass

                elif line.startswith("BC HTab MaxFlow="):
                    val = GeomParser.extract_keyword_value(line, "BC HTab MaxFlow")
                    if val:
                        try:
                            htab_data.append({'Parameter': 'MaxFlow', 'Value': float(val)})
                        except: pass

                elif line.startswith("BC Use User HTab Curves="):
                    val = GeomParser.extract_keyword_value(line, "BC Use User HTab Curves")
                    if val:
                        try:
                            htab_data.append({'Parameter': 'UseCurves', 'Value': int(val)})
                        except: pass

                elif line.startswith("BC User HTab FreeFlow(D)="):
                    val = GeomParser.extract_keyword_value(line, "BC User HTab FreeFlow(D)")
                    if val:
                        try:
                            htab_data.append({'Parameter': 'FreeFlowCurves', 'Value': int(val.strip())})
                        except: pass

                elif line.startswith("BC User HTab Sub Curve(D)="):
                    val = GeomParser.extract_keyword_value(line, "BC User HTab Sub Curve(D)")
                    if val:
                        try:
                            htab_data.append({'Parameter': 'SubmergedCurves', 'Value': int(val.strip())})
                        except: pass

            df = pd.DataFrame(htab_data)
            logger.info(f"Extracted HTab parameters for {river}/{reach}/RS {rs}")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge HTab: {str(e)}")
            raise IOError(f"Failed to read bridge HTab: {str(e)}")
