"""
RasStruct - Operations for parsing HEC-RAS inline structures in geometry files

This module provides functionality for reading inline structure data from
HEC-RAS plain text geometry files (.g##). It handles bridges, culverts,
inline weirs, and related structure data.

All methods are static and designed to be used without instantiation.

List of Functions:

Inline Weir Operations:
- get_inline_weirs() - List all inline weirs with metadata
- get_inline_weir_profile() - Read station/elevation profile for weir crest
- get_inline_weir_gates() - Read gate parameters and opening definitions

Bridge/Culvert Operations:
- get_bridges() - List all bridges/culverts with metadata
- get_bridge_deck() - Read deck geometry (stations, elevations, lowchord)
- get_bridge_piers() - Read pier definitions (widths, elevations)
- get_bridge_abutment() - Read abutment geometry
- get_bridge_approach_sections() - Read BR U/BR D approach sections
- get_bridge_coefficients() - Read hydraulic coefficients (BR Coef, WSPro)
- get_bridge_htab() - Read hydraulic table parameters (HWMax, TWMax, MaxFlow, curves)
- get_culverts() - List all culverts at a bridge/culvert structure (detailed)
- get_all_culverts() - List all culverts across entire geometry file

Example Usage:
    >>> from ras_commander import RasStruct
    >>> from pathlib import Path
    >>>
    >>> # List all inline weirs
    >>> geom_file = Path("BaldEagle.g01")
    >>> weirs_df = RasStruct.get_inline_weirs(geom_file)
    >>> print(f"Found {len(weirs_df)} inline weirs")
    >>>
    >>> # Get weir profile for specific inline weir
    >>> profile = RasStruct.get_inline_weir_profile(
    ...     geom_file, "Bald Eagle Creek", "Reach 1", "81084.18"
    ... )
    >>> print(profile.head())
    >>>
    >>> # List all bridges
    >>> bridges_df = RasStruct.get_bridges(geom_file)
    >>> print(f"Found {len(bridges_df)} bridges")

Technical Notes:
    - Uses FORTRAN-era fixed-width format (8-char columns for numeric data)
    - Count interpretation: "#Inline Weir SE= 6" means 6 PAIRS (12 total values)
    - Bridge structures have hierarchical data (deck -> piers -> abutments)

References:
    - See research/geometry file parsing/geometry_docs/1D_geometry_structure.md
    - See research/geometry file parsing/geometry_docs/_PARSING_PATTERNS_REFERENCE.md
"""

from pathlib import Path
from typing import Union, Optional, List, Tuple, Dict, Any
import pandas as pd
import numpy as np

from .LoggingConfig import get_logger
from .Decorators import log_call
from .RasGeometryUtils import RasGeometryUtils

logger = get_logger(__name__)


class RasStruct:
    """
    Operations for parsing HEC-RAS inline structures in geometry files.

    All methods are static and designed to be used without instantiation.

    Supported structure types:
    - Inline Weirs (with optional gates)
    - Bridges and Culverts (with deck, piers, abutments)
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8      # Character width for numeric data in geometry files
    VALUES_PER_LINE = 10        # Number of values per line in fixed-width format

    # Parsing constants
    DEFAULT_SEARCH_RANGE = 100  # Lines to search for keywords after structure header
    MAX_PARSE_LINES = 200       # Safety limit on lines to parse for data blocks

    # ========== PRIVATE HELPER METHODS ==========

    @staticmethod
    def _find_inline_weir(lines: List[str], river: str, reach: str, rs: str) -> Optional[int]:
        """
        Find inline weir section and return line index of 'IW Pilot Flow=' marker.

        Args:
            lines: File lines (from readlines())
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string, e.g., "81084.18")

        Returns:
            Line index where "IW Pilot Flow=" appears for matching inline weir,
            or None if not found

        Example:
            >>> with open(geom_file, 'r') as f:
            ...     lines = f.readlines()
            >>> idx = RasStruct._find_inline_weir(lines, "Bald Eagle", "Loc Hav", "81084.18")
            >>> if idx:
            ...     # Process inline weir block starting at lines[idx]
        """
        current_river = None
        current_reach = None
        last_rs = None
        last_type_line_idx = None

        for i, line in enumerate(lines):
            # Track current river/reach
            if line.startswith("River Reach="):
                values = RasGeometryUtils.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]

            # Track most recent Type RM Length line (contains RS)
            elif line.startswith("Type RM Length L Ch R ="):
                value_str = RasGeometryUtils.extract_keyword_value(line, "Type RM Length L Ch R")
                values = [v.strip() for v in value_str.split(',')]
                if len(values) > 1:
                    last_rs = values[1]  # RS is second value
                    last_type_line_idx = i

            # Find IW Pilot Flow marker (start of inline weir)
            elif line.startswith("IW Pilot Flow="):
                if (current_river == river and
                    current_reach == reach and
                    last_rs == rs):
                    logger.debug(f"Found inline weir at line {i}: {river}/{reach}/RS {rs}")
                    return i

        logger.debug(f"Inline weir not found: {river}/{reach}/RS {rs}")
        return None

    @staticmethod
    def _find_bridge(lines: List[str], river: str, reach: str, rs: str) -> Optional[int]:
        """
        Find bridge/culvert section and return line index of 'Bridge Culvert-' marker.

        Args:
            lines: File lines (from readlines())
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            Line index where "Bridge Culvert-" appears for matching bridge,
            or None if not found
        """
        current_river = None
        current_reach = None
        last_rs = None

        for i, line in enumerate(lines):
            # Track current river/reach
            if line.startswith("River Reach="):
                values = RasGeometryUtils.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]

            # Track Type RM Length (RS is second value, type 3 = bridge)
            elif line.startswith("Type RM Length L Ch R ="):
                value_str = RasGeometryUtils.extract_keyword_value(line, "Type RM Length L Ch R")
                values = [v.strip() for v in value_str.split(',')]
                if len(values) > 1:
                    last_rs = values[1]

            # Find Bridge Culvert marker
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
        """
        Parse 'Bridge Culvert-' header line into dict of flags.

        Args:
            line: Line starting with "Bridge Culvert-"

        Returns:
            Dict with keys: flag1, flag2, flag3, flag4, flag5

        Example:
            >>> line = "Bridge Culvert--1,0,-1,-1, 0"
            >>> flags = RasStruct._parse_bridge_header(line)
            >>> print(flags)
            {'flag1': -1, 'flag2': 0, 'flag3': -1, 'flag4': -1, 'flag5': 0}
        """
        # Extract values after "Bridge Culvert-"
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
    def _parse_paired_data(lines: List[str], start_idx: int, num_pairs: int,
                          col1_name: str, col2_name: str,
                          column_width: int = 8) -> pd.DataFrame:
        """
        Parse fixed-width paired data into DataFrame.

        Args:
            lines: File lines
            start_idx: Index of first data line
            num_pairs: Number of pairs to read
            col1_name: Name for first column (e.g., 'Station')
            col2_name: Name for second column (e.g., 'Elevation')
            column_width: Width of each column (default 8)

        Returns:
            DataFrame with two columns
        """
        total_values = num_pairs * 2
        values = []

        i = start_idx
        while len(values) < total_values and i < len(lines):
            line = lines[i]
            # Stop if we hit a keyword line
            if '=' in line and not line.strip().startswith('-'):
                break

            parsed = RasGeometryUtils.parse_fixed_width(line, column_width)
            values.extend(parsed)
            i += 1

        # Reshape into pairs
        col1_data = []
        col2_data = []
        for j in range(0, min(len(values), total_values), 2):
            if j + 1 < len(values):
                col1_data.append(values[j])
                col2_data.append(values[j + 1])

        return pd.DataFrame({col1_name: col1_data, col2_name: col2_data})

    # ========== INLINE WEIR METHODS ==========

    @staticmethod
    @log_call
    def get_inline_weirs(geom_file: Union[str, Path],
                        river: Optional[str] = None,
                        reach: Optional[str] = None) -> pd.DataFrame:
        """
        List all inline weirs in geometry file with metadata.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: Optional filter by river name (case-sensitive)
            reach: Optional filter by reach name (case-sensitive)

        Returns:
            pd.DataFrame with columns:
            - River, Reach, RS: Location identifiers
            - NodeName: Descriptive name (if available)
            - PilotFlow: Pilot flow flag (0/1)
            - Distance, Width, Coefficient, Skew: Weir parameters
            - MaxSubmergence, MinElevation, IsOgee: Additional parameters
            - SpillwayHeight, DesignHead: Design parameters
            - HasGate: Boolean indicating if gates are present
            - NumOpenings: Number of gate openings (if gates present)

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> weirs = RasStruct.get_inline_weirs("BaldEagle.g01")
            >>> print(f"Found {len(weirs)} inline weirs")
            >>> print(weirs[['River', 'Reach', 'RS', 'Coefficient']])
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            inline_weirs = []
            current_river = None
            current_reach = None
            last_rs = None
            last_node_name = None

            i = 0
            while i < len(lines):
                line = lines[i]

                # Track current river/reach
                if line.startswith("River Reach="):
                    values = RasGeometryUtils.extract_comma_list(line, "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]

                # Track RS from Type line
                elif line.startswith("Type RM Length L Ch R ="):
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Type RM Length L Ch R")
                    values = [v.strip() for v in value_str.split(',')]
                    if len(values) > 1:
                        last_rs = values[1]

                # Track node name
                elif line.startswith("Node Name="):
                    last_node_name = RasGeometryUtils.extract_keyword_value(line, "Node Name")

                # Found inline weir
                elif line.startswith("IW Pilot Flow="):
                    # Apply filters
                    if river is not None and current_river != river:
                        i += 1
                        continue
                    if reach is not None and current_reach != reach:
                        i += 1
                        continue

                    # Extract pilot flow
                    pilot_flow_str = RasGeometryUtils.extract_keyword_value(line, "IW Pilot Flow")
                    pilot_flow = int(pilot_flow_str.strip()) if pilot_flow_str.strip() else 0

                    weir_data = {
                        'River': current_river,
                        'Reach': current_reach,
                        'RS': last_rs,
                        'NodeName': last_node_name,
                        'PilotFlow': pilot_flow,
                        'Distance': None,
                        'Width': None,
                        'Coefficient': None,
                        'Skew': None,
                        'MaxSubmergence': None,
                        'MinElevation': None,
                        'IsOgee': None,
                        'SpillwayHeight': None,
                        'DesignHead': None,
                        'HasGate': False,
                        'NumOpenings': 0
                    }

                    # Search for weir parameters in next ~50 lines
                    for j in range(i + 1, min(i + 50, len(lines))):
                        search_line = lines[j]

                        # Parse weir parameters (line after header)
                        if search_line.startswith("IW Dist,WD,Coef,"):
                            # Next line has the values
                            if j + 1 < len(lines):
                                param_line = lines[j + 1]
                                parts = [p.strip() for p in param_line.split(',')]

                                # Extract each parameter
                                if len(parts) > 0 and parts[0]:
                                    try: weir_data['Distance'] = float(parts[0])
                                    except: pass
                                if len(parts) > 1 and parts[1]:
                                    try: weir_data['Width'] = float(parts[1])
                                    except: pass
                                if len(parts) > 2 and parts[2]:
                                    try: weir_data['Coefficient'] = float(parts[2])
                                    except: pass
                                if len(parts) > 3 and parts[3]:
                                    try: weir_data['Skew'] = float(parts[3])
                                    except: pass
                                if len(parts) > 4 and parts[4]:
                                    try: weir_data['MaxSubmergence'] = float(parts[4])
                                    except: pass
                                if len(parts) > 5 and parts[5]:
                                    try: weir_data['MinElevation'] = float(parts[5])
                                    except: pass
                                if len(parts) > 6 and parts[6]:
                                    try: weir_data['IsOgee'] = int(parts[6])
                                    except: pass
                                if len(parts) > 7 and parts[7]:
                                    try: weir_data['SpillwayHeight'] = float(parts[7])
                                    except: pass
                                if len(parts) > 8 and parts[8]:
                                    try: weir_data['DesignHead'] = float(parts[8])
                                    except: pass

                        # Check for gate presence
                        elif search_line.startswith("IW Gate Name Wd,"):
                            weir_data['HasGate'] = True
                            # Next line has gate data with NumOpenings
                            if j + 1 < len(lines):
                                gate_line = lines[j + 1]
                                parts = [p.strip() for p in gate_line.split(',')]
                                # NumOpenings is at position 13
                                if len(parts) > 13 and parts[13]:
                                    try:
                                        weir_data['NumOpenings'] = int(parts[13])
                                    except:
                                        pass

                        # Stop at next structure
                        elif search_line.startswith("Type RM Length L Ch R ="):
                            break

                    inline_weirs.append(weir_data)
                    last_node_name = None  # Reset for next structure

                i += 1

            df = pd.DataFrame(inline_weirs)
            logger.info(f"Found {len(df)} inline weirs in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading inline weirs: {str(e)}")
            raise IOError(f"Failed to read inline weirs: {str(e)}")

    @staticmethod
    @log_call
    def get_inline_weir_profile(geom_file: Union[str, Path],
                                river: str,
                                reach: str,
                                rs: str) -> pd.DataFrame:
        """
        Extract weir crest station/elevation profile for an inline weir.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            pd.DataFrame with columns:
            - Station: Station values along weir crest
            - Elevation: Elevation values at each station

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If inline weir not found

        Example:
            >>> profile = RasStruct.get_inline_weir_profile(
            ...     "BaldEagle.g01", "Bald Eagle Creek", "Reach 1", "81084.18"
            ... )
            >>> print(f"Profile has {len(profile)} points")
            >>> print(profile)
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find inline weir
            weir_idx = RasStruct._find_inline_weir(lines, river, reach, rs)

            if weir_idx is None:
                raise ValueError(f"Inline weir not found: {river}/{reach}/RS {rs}")

            # Search for #Inline Weir SE= line
            for j in range(weir_idx, min(weir_idx + RasStruct.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                if line.startswith("#Inline Weir SE="):
                    # Extract count
                    count_str = RasGeometryUtils.extract_keyword_value(line, "#Inline Weir SE")
                    count = int(count_str.strip())

                    # Parse paired data (station/elevation)
                    df = RasStruct._parse_paired_data(
                        lines, j + 1, count, 'Station', 'Elevation'
                    )

                    logger.info(f"Extracted {len(df)} profile points for {river}/{reach}/RS {rs}")
                    return df

            raise ValueError(f"#Inline Weir SE= not found for {river}/{reach}/RS {rs}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading inline weir profile: {str(e)}")
            raise IOError(f"Failed to read inline weir profile: {str(e)}")

    @staticmethod
    @log_call
    def get_inline_weir_gates(geom_file: Union[str, Path],
                              river: str,
                              reach: str,
                              rs: str) -> pd.DataFrame:
        """
        Extract gate parameters and opening definitions for an inline weir.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            pd.DataFrame with columns:
            - GateName: Gate identifier (e.g., "Gate #1")
            - Width, Height, InvertElevation: Gate dimensions
            - GateCoefficient: Flow coefficient
            - ExpansionTop, ExpansionOrifice, ExpansionHydraulic: Expansion coefficients
            - GateType: Gate type code
            - WeirCoefficient, IsOgee: Weir parameters
            - SpillwayHeight, DesignHead: Design parameters
            - NumOpenings: Number of gate openings
            - OpeningStations: List of station values for each opening

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If inline weir not found or has no gates

        Example:
            >>> gates = RasStruct.get_inline_weir_gates(
            ...     "BaldEagle.g01", "Bald Eagle Creek", "Reach 1", "81084.18"
            ... )
            >>> print(f"Found {len(gates)} gates")
            >>> print(gates[['GateName', 'Width', 'Height', 'NumOpenings']])
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find inline weir
            weir_idx = RasStruct._find_inline_weir(lines, river, reach, rs)

            if weir_idx is None:
                raise ValueError(f"Inline weir not found: {river}/{reach}/RS {rs}")

            gates = []

            # Search for gate definitions
            i = weir_idx
            while i < min(weir_idx + RasStruct.DEFAULT_SEARCH_RANGE, len(lines)):
                line = lines[i]

                # Stop at next structure
                if line.startswith("Type RM Length L Ch R =") and i > weir_idx + 5:
                    break

                # Found gate header
                if line.startswith("IW Gate Name Wd,"):
                    # Next line has gate data
                    if i + 1 < len(lines):
                        gate_line = lines[i + 1]
                        parts = [p.strip() for p in gate_line.split(',')]

                        gate_data = {
                            'GateName': parts[0] if len(parts) > 0 else None,
                            'Width': None,
                            'Height': None,
                            'InvertElevation': None,
                            'GateCoefficient': None,
                            'ExpansionTop': None,
                            'ExpansionOrifice': None,
                            'ExpansionHydraulic': None,
                            'GateType': None,
                            'WeirCoefficient': None,
                            'IsOgee': None,
                            'SpillwayHeight': None,
                            'DesignHead': None,
                            'NumOpenings': 0,
                            'OpeningStations': []
                        }

                        # Parse numeric parameters
                        if len(parts) > 1 and parts[1]:
                            try: gate_data['Width'] = float(parts[1])
                            except: pass
                        if len(parts) > 2 and parts[2]:
                            try: gate_data['Height'] = float(parts[2])
                            except: pass
                        if len(parts) > 3 and parts[3]:
                            try: gate_data['InvertElevation'] = float(parts[3])
                            except: pass
                        if len(parts) > 4 and parts[4]:
                            try: gate_data['GateCoefficient'] = float(parts[4])
                            except: pass
                        if len(parts) > 5 and parts[5]:
                            try: gate_data['ExpansionTop'] = float(parts[5])
                            except: pass
                        if len(parts) > 6 and parts[6]:
                            try: gate_data['ExpansionOrifice'] = float(parts[6])
                            except: pass
                        if len(parts) > 7 and parts[7]:
                            try: gate_data['ExpansionHydraulic'] = float(parts[7])
                            except: pass
                        if len(parts) > 8 and parts[8]:
                            try: gate_data['GateType'] = float(parts[8])
                            except: pass
                        if len(parts) > 9 and parts[9]:
                            try: gate_data['WeirCoefficient'] = float(parts[9])
                            except: pass
                        if len(parts) > 10 and parts[10]:
                            try: gate_data['IsOgee'] = int(parts[10])
                            except: pass
                        if len(parts) > 11 and parts[11]:
                            try: gate_data['SpillwayHeight'] = float(parts[11])
                            except: pass
                        if len(parts) > 12 and parts[12]:
                            try: gate_data['DesignHead'] = float(parts[12])
                            except: pass
                        if len(parts) > 13 and parts[13]:
                            try: gate_data['NumOpenings'] = int(parts[13])
                            except: pass

                        # Parse opening stations from next line (if NumOpenings > 0)
                        num_openings = gate_data['NumOpenings']
                        if num_openings > 0 and i + 2 < len(lines):
                            station_line = lines[i + 2]
                            # Only parse if it looks like fixed-width data (not a keyword)
                            if '=' not in station_line:
                                stations = RasGeometryUtils.parse_fixed_width(station_line, 8)
                                gate_data['OpeningStations'] = stations[:num_openings]

                        gates.append(gate_data)
                        i += 2  # Skip past gate data line

                i += 1

            if not gates:
                raise ValueError(f"No gates found for inline weir: {river}/{reach}/RS {rs}")

            df = pd.DataFrame(gates)
            logger.info(f"Extracted {len(df)} gates for {river}/{reach}/RS {rs}")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading inline weir gates: {str(e)}")
            raise IOError(f"Failed to read inline weir gates: {str(e)}")

    # ========== BRIDGE/CULVERT METHODS ==========

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
            - BridgeFlags: Dict of flags from Bridge Culvert- header
            - NumDecks: Number of deck spans
            - DeckWidth: Bridge deck width
            - WeirCoefficient: Weir flow coefficient
            - Skew: Bridge skew angle
            - MaxSubmergence: Maximum submergence factor
            - IsOgee: Ogee type flag
            - NumPiers: Count of pier definitions
            - HasAbutment: Boolean indicating abutment presence
            - HTabHWMax: Maximum headwater elevation
            - NodeLastEdited: Timestamp of last modification

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> bridges = RasStruct.get_bridges("A100_00_00.g08")
            >>> print(f"Found {len(bridges)} bridges")
            >>> print(bridges[['River', 'Reach', 'RS', 'NodeName']])
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

                # Track current river/reach
                if line.startswith("River Reach="):
                    values = RasGeometryUtils.extract_comma_list(line, "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]

                # Track RS from Type line
                elif line.startswith("Type RM Length L Ch R ="):
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Type RM Length L Ch R")
                    values = [v.strip() for v in value_str.split(',')]
                    if len(values) > 1:
                        last_rs = values[1]

                # Track node name
                elif line.startswith("Node Name="):
                    last_node_name = RasGeometryUtils.extract_keyword_value(line, "Node Name")

                # Track last edited time
                elif line.startswith("Node Last Edited Time="):
                    last_edited = RasGeometryUtils.extract_keyword_value(line, "Node Last Edited Time")

                # Found bridge/culvert
                elif line.startswith("Bridge Culvert-"):
                    # Apply filters
                    if river is not None and current_river != river:
                        i += 1
                        continue
                    if reach is not None and current_reach != reach:
                        i += 1
                        continue

                    # Parse bridge header flags
                    bridge_flags = RasStruct._parse_bridge_header(line)

                    bridge_data = {
                        'River': current_river,
                        'Reach': current_reach,
                        'RS': last_rs,
                        'NodeName': last_node_name,
                        'BridgeFlags': bridge_flags,
                        'NumDecks': None,
                        'DeckWidth': None,
                        'WeirCoefficient': None,
                        'Skew': None,
                        'MaxSubmergence': None,
                        'IsOgee': None,
                        'NumPiers': 0,
                        'HasAbutment': False,
                        'HTabHWMax': None,
                        'NodeLastEdited': last_edited
                    }

                    # Search for deck parameters and count piers
                    pier_count = 0
                    for j in range(i + 1, min(i + RasStruct.DEFAULT_SEARCH_RANGE, len(lines))):
                        search_line = lines[j]

                        # Parse deck parameters
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
                                if len(parts) > 10 and parts[10]:
                                    try: bridge_data['IsOgee'] = int(parts[10])
                                    except: pass

                        # Count piers
                        elif search_line.startswith("Pier Skew, UpSta & Num"):
                            pier_count += 1

                        # Check for abutment
                        elif search_line.startswith("Abutment Skew #Up #Dn="):
                            bridge_data['HasAbutment'] = True

                        # Get HTab max
                        elif search_line.startswith("BC HTab HWMax="):
                            val = RasGeometryUtils.extract_keyword_value(search_line, "BC HTab HWMax")
                            if val:
                                try: bridge_data['HTabHWMax'] = float(val)
                                except: pass

                        # Stop at next structure
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
    def get_bridge_deck(geom_file: Union[str, Path],
                       river: str,
                       reach: str,
                       rs: str) -> Dict[str, Any]:
        """
        Extract complete deck geometry for a bridge.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            Dict with keys:
            - parameters: Dict of deck parameters (NumDecks, Distance, Width,
              WeirCoef, Skew, NumUp, NumDn, MaxSubmergence, IsOgee)
            - upstream_stations: List of upstream station values
            - upstream_elevations: List of upstream elevation values
            - upstream_lowchord: List of upstream low chord values
            - downstream_stations: List of downstream station values
            - downstream_elevations: List of downstream elevation values
            - downstream_lowchord: List of downstream low chord values

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found

        Example:
            >>> deck = RasStruct.get_bridge_deck(
            ...     "A100_00_00.g08", "River Name", "Reach Name", "25548"
            ... )
            >>> print(f"NumUp: {deck['parameters']['NumUp']}")
            >>> print(f"Upstream stations: {len(deck['upstream_stations'])}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find bridge
            bridge_idx = RasStruct._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            result = {
                'parameters': {},
                'upstream_stations': [],
                'upstream_elevations': [],
                'upstream_lowchord': [],
                'downstream_stations': [],
                'downstream_elevations': [],
                'downstream_lowchord': []
            }

            # Search for deck data
            for j in range(bridge_idx, min(bridge_idx + RasStruct.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                if line.startswith("Deck Dist Width WeirC"):
                    # Next line has parameters
                    if j + 1 < len(lines):
                        param_line = lines[j + 1]
                        parts = [p.strip() for p in param_line.split(',')]

                        params = result['parameters']
                        if len(parts) > 0 and parts[0]:
                            try: params['NumDecks'] = int(parts[0])
                            except: pass
                        if len(parts) > 1 and parts[1]:
                            try: params['Distance'] = float(parts[1])
                            except: pass
                        if len(parts) > 2 and parts[2]:
                            try: params['Width'] = float(parts[2])
                            except: pass
                        if len(parts) > 3 and parts[3]:
                            try: params['WeirCoef'] = float(parts[3])
                            except: pass
                        if len(parts) > 4 and parts[4]:
                            try: params['Skew'] = float(parts[4])
                            except: pass
                        if len(parts) > 5 and parts[5]:
                            try: params['NumUp'] = int(parts[5])
                            except: pass
                        if len(parts) > 6 and parts[6]:
                            try: params['NumDn'] = int(parts[6])
                            except: pass
                        if len(parts) > 9 and parts[9]:
                            try: params['MaxSubmergence'] = float(parts[9])
                            except: pass
                        if len(parts) > 10 and parts[10]:
                            try: params['IsOgee'] = int(parts[10])
                            except: pass

                        # Parse deck data rows
                        num_up = params.get('NumUp', 0)
                        num_dn = params.get('NumDn', 0)

                        if num_up > 0:
                            # Read upstream data (3 rows: stations, elevations, lowchord)
                            data_start = j + 2
                            all_up_values = []

                            for k in range(data_start, min(data_start + 10, len(lines))):
                                data_line = lines[k]
                                if '=' in data_line:
                                    break
                                values = RasGeometryUtils.parse_fixed_width(data_line, 8)
                                all_up_values.extend(values)
                                if len(all_up_values) >= num_up * 3:
                                    break

                            # Split into stations, elevations, lowchord
                            if len(all_up_values) >= num_up:
                                result['upstream_stations'] = all_up_values[:num_up]
                            if len(all_up_values) >= num_up * 2:
                                result['upstream_elevations'] = all_up_values[num_up:num_up*2]
                            if len(all_up_values) >= num_up * 3:
                                result['upstream_lowchord'] = all_up_values[num_up*2:num_up*3]

                        # Read downstream data similarly (after upstream)
                        if num_dn > 0 and num_up > 0:
                            # Find where downstream data starts
                            expected_up_lines = (num_up * 3 + 9) // 10 + 1
                            dn_start = j + 2 + expected_up_lines

                            all_dn_values = []
                            for k in range(dn_start, min(dn_start + 10, len(lines))):
                                if k >= len(lines):
                                    break
                                data_line = lines[k]
                                if '=' in data_line or data_line.startswith("Pier"):
                                    break
                                values = RasGeometryUtils.parse_fixed_width(data_line, 8)
                                all_dn_values.extend(values)
                                if len(all_dn_values) >= num_dn * 3:
                                    break

                            if len(all_dn_values) >= num_dn:
                                result['downstream_stations'] = all_dn_values[:num_dn]
                            if len(all_dn_values) >= num_dn * 2:
                                result['downstream_elevations'] = all_dn_values[num_dn:num_dn*2]
                            if len(all_dn_values) >= num_dn * 3:
                                result['downstream_lowchord'] = all_dn_values[num_dn*2:num_dn*3]

                    break  # Found deck data

            logger.info(f"Extracted deck geometry for {river}/{reach}/RS {rs}")
            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge deck: {str(e)}")
            raise IOError(f"Failed to read bridge deck: {str(e)}")

    @staticmethod
    @log_call
    def get_bridge_piers(geom_file: Union[str, Path],
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
            - UpstreamStation: Upstream pier station
            - NumUpstreamPoints: Number of upstream width/elevation points
            - DownstreamStation: Downstream pier station
            - NumDownstreamPoints: Number of downstream points
            - SkewParam1, SkewParam2, SkewParam3: Skew parameters
            - UpstreamWidths: List of upstream pier widths
            - UpstreamElevations: List of upstream elevations
            - DownstreamWidths: List of downstream pier widths
            - DownstreamElevations: List of downstream elevations

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found or has no piers

        Example:
            >>> piers = RasStruct.get_bridge_piers(
            ...     "A100_00_00.g08", "River Name", "Reach Name", "25548"
            ... )
            >>> print(f"Found {len(piers)} piers")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find bridge
            bridge_idx = RasStruct._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            piers = []
            pier_index = 0

            i = bridge_idx
            while i < min(bridge_idx + RasStruct.DEFAULT_SEARCH_RANGE, len(lines)):
                line = lines[i]

                # Stop at next structure
                if line.startswith("Type RM Length L Ch R =") and i > bridge_idx + 5:
                    break

                # Found pier definition
                if line.startswith("Pier Skew, UpSta & Num, DnSta & Num="):
                    pier_index += 1

                    # Parse header
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Pier Skew, UpSta & Num, DnSta & Num")
                    parts = [p.strip() for p in value_str.split(',')]

                    pier_data = {
                        'PierIndex': pier_index,
                        'UpstreamStation': None,
                        'NumUpstreamPoints': 0,
                        'DownstreamStation': None,
                        'NumDownstreamPoints': 0,
                        'SkewParam1': None,
                        'SkewParam2': None,
                        'SkewParam3': None,
                        'UpstreamWidths': [],
                        'UpstreamElevations': [],
                        'DownstreamWidths': [],
                        'DownstreamElevations': []
                    }

                    # Parse header values
                    # Format: Skew(often empty), UpSta, NumUp, DnSta, NumDn, Param1, Param2, Param3, blank, blank
                    # Note: First field (skew) is often empty, so actual data starts at index 1
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
                    if len(parts) > 5 and parts[5]:
                        try: pier_data['SkewParam1'] = int(parts[5])
                        except: pass
                    if len(parts) > 6 and parts[6]:
                        try: pier_data['SkewParam2'] = int(parts[6])
                        except: pass
                    if len(parts) > 7 and parts[7]:
                        try: pier_data['SkewParam3'] = int(parts[7])
                        except: pass

                    # Parse pier width/elevation data (4 rows: up_widths, up_elev, dn_widths, dn_elev)
                    num_up = pier_data['NumUpstreamPoints']
                    num_dn = pier_data['NumDownstreamPoints']

                    if num_up > 0 and i + 2 < len(lines):
                        # Upstream widths
                        widths_line = lines[i + 1]
                        if '=' not in widths_line:
                            pier_data['UpstreamWidths'] = RasGeometryUtils.parse_fixed_width(widths_line, 8)[:num_up]

                        # Upstream elevations
                        if i + 2 < len(lines):
                            elev_line = lines[i + 2]
                            if '=' not in elev_line:
                                pier_data['UpstreamElevations'] = RasGeometryUtils.parse_fixed_width(elev_line, 8)[:num_up]

                    if num_dn > 0 and i + 4 < len(lines):
                        # Downstream widths
                        widths_line = lines[i + 3]
                        if '=' not in widths_line:
                            pier_data['DownstreamWidths'] = RasGeometryUtils.parse_fixed_width(widths_line, 8)[:num_dn]

                        # Downstream elevations
                        if i + 4 < len(lines):
                            elev_line = lines[i + 4]
                            if '=' not in elev_line:
                                pier_data['DownstreamElevations'] = RasGeometryUtils.parse_fixed_width(elev_line, 8)[:num_dn]

                    piers.append(pier_data)
                    i += 4  # Skip pier data rows

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
    def get_bridge_abutment(geom_file: Union[str, Path],
                           river: str,
                           reach: str,
                           rs: str) -> Dict[str, Any]:
        """
        Extract abutment geometry for a bridge (if present).

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            Dict with keys:
            - num_upstream: Number of upstream abutment points
            - num_downstream: Number of downstream abutment points
            - upstream_stations: List of upstream station values
            - upstream_params: List of upstream parameter values
            - downstream_stations: List of downstream station values
            - downstream_params: List of downstream parameter values

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found or has no abutment

        Example:
            >>> abutment = RasStruct.get_bridge_abutment(
            ...     "A100_00_00.g08", "River Name", "Reach Name", "25548"
            ... )
            >>> print(f"Upstream points: {abutment['num_upstream']}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find bridge
            bridge_idx = RasStruct._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            result = {
                'num_upstream': 0,
                'num_downstream': 0,
                'upstream_stations': [],
                'upstream_params': [],
                'downstream_stations': [],
                'downstream_params': []
            }

            # Search for abutment definition
            for j in range(bridge_idx, min(bridge_idx + RasStruct.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                # Stop at next structure
                if line.startswith("Type RM Length L Ch R =") and j > bridge_idx + 5:
                    break

                if line.startswith("Abutment Skew #Up #Dn="):
                    # Parse header
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Abutment Skew #Up #Dn")
                    parts = [p.strip() for p in value_str.split(',')]

                    if len(parts) > 0 and parts[0]:
                        try: result['num_upstream'] = int(parts[0])
                        except: pass
                    if len(parts) > 1 and parts[1]:
                        try: result['num_downstream'] = int(parts[1])
                        except: pass

                    num_up = result['num_upstream']
                    num_dn = result['num_downstream']

                    # Parse data rows
                    if num_up > 0 and j + 2 < len(lines):
                        # Upstream stations
                        sta_line = lines[j + 1]
                        if '=' not in sta_line:
                            result['upstream_stations'] = RasGeometryUtils.parse_fixed_width(sta_line, 8)[:num_up]

                        # Upstream params
                        param_line = lines[j + 2]
                        if '=' not in param_line:
                            result['upstream_params'] = RasGeometryUtils.parse_fixed_width(param_line, 8)[:num_up]

                    if num_dn > 0 and j + 4 < len(lines):
                        # Downstream stations
                        sta_line = lines[j + 3]
                        if '=' not in sta_line:
                            result['downstream_stations'] = RasGeometryUtils.parse_fixed_width(sta_line, 8)[:num_dn]

                        # Downstream params
                        param_line = lines[j + 4]
                        if '=' not in param_line:
                            result['downstream_params'] = RasGeometryUtils.parse_fixed_width(param_line, 8)[:num_dn]

                    logger.info(f"Extracted abutment for {river}/{reach}/RS {rs}")
                    return result

            raise ValueError(f"No abutment found for bridge: {river}/{reach}/RS {rs}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge abutment: {str(e)}")
            raise IOError(f"Failed to read bridge abutment: {str(e)}")

    @staticmethod
    @log_call
    def get_bridge_approach_sections(geom_file: Union[str, Path],
                                    river: str,
                                    reach: str,
                                    rs: str) -> Dict[str, Any]:
        """
        Extract BR U (upstream) and BR D (downstream) approach section geometry.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            Dict with keys:
            - upstream: Dict with:
              - station_elevation: DataFrame with Station, Elevation columns
              - mannings_n: DataFrame with Station, N_Value, Flag columns
              - banks: Tuple (left_bank, right_bank) or (None, None)
            - downstream: Dict with same structure

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found

        Example:
            >>> approach = RasStruct.get_bridge_approach_sections(
            ...     "A100_00_00.g08", "River Name", "Reach Name", "25548"
            ... )
            >>> print(f"Upstream XS has {len(approach['upstream']['station_elevation'])} points")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find bridge
            bridge_idx = RasStruct._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            result = {
                'upstream': {
                    'station_elevation': pd.DataFrame(),
                    'mannings_n': pd.DataFrame(),
                    'banks': (None, None)
                },
                'downstream': {
                    'station_elevation': pd.DataFrame(),
                    'mannings_n': pd.DataFrame(),
                    'banks': (None, None)
                }
            }

            # Search for BR U and BR D sections
            for j in range(bridge_idx, min(bridge_idx + RasStruct.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                # Stop at next structure
                if line.startswith("Type RM Length L Ch R =") and j > bridge_idx + 5:
                    break

                # Upstream station/elevation
                if line.startswith("BR U #Sta/Elev="):
                    count_str = RasGeometryUtils.extract_keyword_value(line, "BR U #Sta/Elev")
                    count = int(count_str.strip())
                    result['upstream']['station_elevation'] = RasStruct._parse_paired_data(
                        lines, j + 1, count, 'Station', 'Elevation'
                    )

                # Upstream Manning's n
                elif line.startswith("BR U #Mann="):
                    count_str = line.split('=')[1].split(',')[0].strip()
                    count = int(count_str)
                    # Manning's format: station, n_value, flag (triplets)
                    total_values = count * 3
                    values = []
                    k = j + 1
                    while len(values) < total_values and k < len(lines):
                        data_line = lines[k]
                        if '=' in data_line:
                            break
                        values.extend(RasGeometryUtils.parse_fixed_width(data_line, 8))
                        k += 1

                    mann_data = []
                    for m in range(0, min(len(values), total_values), 3):
                        if m + 2 < len(values):
                            mann_data.append({
                                'Station': values[m],
                                'N_Value': values[m + 1],
                                'Flag': values[m + 2]
                            })
                    result['upstream']['mannings_n'] = pd.DataFrame(mann_data)

                # Upstream banks
                elif line.startswith("BR U Banks="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BR U Banks")
                    parts = [p.strip() for p in val.split(',')]
                    left = float(parts[0]) if len(parts) > 0 and parts[0] else None
                    right = float(parts[1]) if len(parts) > 1 and parts[1] else None
                    result['upstream']['banks'] = (left, right)

                # Downstream station/elevation
                elif line.startswith("BR D #Sta/Elev="):
                    count_str = RasGeometryUtils.extract_keyword_value(line, "BR D #Sta/Elev")
                    count = int(count_str.strip())
                    result['downstream']['station_elevation'] = RasStruct._parse_paired_data(
                        lines, j + 1, count, 'Station', 'Elevation'
                    )

                # Downstream Manning's n
                elif line.startswith("BR D #Mann="):
                    count_str = line.split('=')[1].split(',')[0].strip()
                    count = int(count_str)
                    total_values = count * 3
                    values = []
                    k = j + 1
                    while len(values) < total_values and k < len(lines):
                        data_line = lines[k]
                        if '=' in data_line:
                            break
                        values.extend(RasGeometryUtils.parse_fixed_width(data_line, 8))
                        k += 1

                    mann_data = []
                    for m in range(0, min(len(values), total_values), 3):
                        if m + 2 < len(values):
                            mann_data.append({
                                'Station': values[m],
                                'N_Value': values[m + 1],
                                'Flag': values[m + 2]
                            })
                    result['downstream']['mannings_n'] = pd.DataFrame(mann_data)

                # Downstream banks
                elif line.startswith("BR D Banks="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BR D Banks")
                    parts = [p.strip() for p in val.split(',')]
                    left = float(parts[0]) if len(parts) > 0 and parts[0] else None
                    right = float(parts[1]) if len(parts) > 1 and parts[1] else None
                    result['downstream']['banks'] = (left, right)

            logger.info(f"Extracted approach sections for {river}/{reach}/RS {rs}")
            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading approach sections: {str(e)}")
            raise IOError(f"Failed to read approach sections: {str(e)}")

    @staticmethod
    @log_call
    def get_bridge_coefficients(geom_file: Union[str, Path],
                               river: str,
                               reach: str,
                               rs: str) -> Dict[str, Any]:
        """
        Extract bridge hydraulic coefficients and HTab parameters.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            Dict with keys:
            - br_coef: List of BR Coef values
            - wspro: List of WSPro parameters
            - bc_design: Dict of BC Design parameters
            - htab: Dict with HWMax, TWMax, MaxFlow, UseCurves, etc.

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found

        Example:
            >>> coef = RasStruct.get_bridge_coefficients(
            ...     "A100_00_00.g08", "River Name", "Reach Name", "25548"
            ... )
            >>> print(f"HW Max: {coef['htab'].get('HWMax')}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find bridge
            bridge_idx = RasStruct._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            result = {
                'br_coef': [],
                'wspro': [],
                'bc_design': {},
                'htab': {}
            }

            # Search for coefficient definitions
            for j in range(bridge_idx, min(bridge_idx + RasStruct.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                # Stop at next structure
                if line.startswith("Type RM Length L Ch R =") and j > bridge_idx + 5:
                    break

                # BR Coef
                if line.startswith("BR Coef="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BR Coef")
                    parts = [p.strip() for p in val.split(',')]
                    for p in parts:
                        if p:
                            try:
                                result['br_coef'].append(float(p))
                            except:
                                result['br_coef'].append(p)

                # WSPro
                elif line.startswith("WSPro="):
                    val = RasGeometryUtils.extract_keyword_value(line, "WSPro")
                    parts = [p.strip() for p in val.split(',')]
                    for p in parts:
                        if p:
                            try:
                                result['wspro'].append(float(p))
                            except:
                                result['wspro'].append(p)

                # BC Design
                elif line.startswith("BC Design="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC Design")
                    parts = [p.strip() for p in val.split(',')]
                    result['bc_design']['raw'] = parts

                # HTab parameters
                elif line.startswith("BC HTab HWMax="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC HTab HWMax")
                    if val:
                        try: result['htab']['HWMax'] = float(val)
                        except: pass

                elif line.startswith("BC HTab TWMax="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC HTab TWMax")
                    if val:
                        try: result['htab']['TWMax'] = float(val)
                        except: pass

                elif line.startswith("BC HTab MaxFlow="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC HTab MaxFlow")
                    if val:
                        try: result['htab']['MaxFlow'] = float(val)
                        except: pass

                elif line.startswith("BC Use User HTab Curves="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC Use User HTab Curves")
                    if val:
                        try: result['htab']['UseCurves'] = int(val)
                        except: pass

            logger.info(f"Extracted coefficients for {river}/{reach}/RS {rs}")
            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge coefficients: {str(e)}")
            raise IOError(f"Failed to read bridge coefficients: {str(e)}")

    @staticmethod
    @log_call
    def get_bridge_htab(geom_file: Union[str, Path],
                       river: str,
                       reach: str,
                       rs: str) -> Dict[str, Any]:
        """
        Extract bridge hydraulic table (HTab) parameters.

        HTab parameters define the range and resolution of pre-computed
        hydraulic tables used for bridge hydraulic calculations.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            Dict with keys:
            - HWMax: Maximum headwater elevation for table
            - TWMax: Maximum tailwater elevation for table
            - MaxFlow: Maximum flow for table
            - UseCurves: Flag indicating user-defined curves (0=no, 1=yes)
            - FreeFlowCurves: Number of free-flow rating curves
            - SubmergedCurves: Number of submerged rating curves
            - FreeFlowData: List of free-flow curve data (if present)
            - SubmergedData: List of submerged curve data (if present)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge not found

        Example:
            >>> htab = RasStruct.get_bridge_htab(
            ...     "A100_00_00.g08", "River Name", "Reach Name", "25548"
            ... )
            >>> print(f"HW Max: {htab['HWMax']}")
            >>> print(f"TW Max: {htab['TWMax']}")
            >>> print(f"Max Flow: {htab['MaxFlow']}")

        Notes:
            HTab parameters control how HEC-RAS pre-computes hydraulic
            relationships for the bridge. Larger ranges require more
            computation but allow modeling of more extreme events.
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find bridge
            bridge_idx = RasStruct._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            result = {
                'HWMax': None,
                'TWMax': None,
                'MaxFlow': None,
                'UseCurves': 0,
                'FreeFlowCurves': 0,
                'SubmergedCurves': 0,
                'FreeFlowData': [],
                'SubmergedData': []
            }

            # Search for HTab parameters
            i = bridge_idx
            while i < min(bridge_idx + RasStruct.DEFAULT_SEARCH_RANGE, len(lines)):
                line = lines[i]

                # Stop at next structure
                if line.startswith("Type RM Length L Ch R =") and i > bridge_idx + 5:
                    break

                # HW Max
                if line.startswith("BC HTab HWMax="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC HTab HWMax")
                    if val:
                        try: result['HWMax'] = float(val)
                        except: pass

                # TW Max
                elif line.startswith("BC HTab TWMax="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC HTab TWMax")
                    if val:
                        try: result['TWMax'] = float(val)
                        except: pass

                # Max Flow
                elif line.startswith("BC HTab MaxFlow="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC HTab MaxFlow")
                    if val:
                        try: result['MaxFlow'] = float(val)
                        except: pass

                # Use User Curves flag
                elif line.startswith("BC Use User HTab Curves="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC Use User HTab Curves")
                    if val:
                        try: result['UseCurves'] = int(val)
                        except: pass

                # Free Flow curves
                elif line.startswith("BC User HTab FreeFlow(D)="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC User HTab FreeFlow(D)")
                    if val:
                        try:
                            num_curves = int(val.strip())
                            result['FreeFlowCurves'] = num_curves
                            # Parse curve data if present
                            if num_curves > 0 and i + 1 < len(lines):
                                curve_data = []
                                k = i + 1
                                while k < len(lines) and not lines[k].strip().startswith("BC"):
                                    if '=' in lines[k]:
                                        break
                                    values = RasGeometryUtils.parse_fixed_width(lines[k], 8)
                                    curve_data.extend(values)
                                    k += 1
                                result['FreeFlowData'] = curve_data
                        except:
                            pass

                # Submerged curves
                elif line.startswith("BC User HTab Sub Curve(D)="):
                    val = RasGeometryUtils.extract_keyword_value(line, "BC User HTab Sub Curve(D)")
                    if val:
                        try:
                            num_curves = int(val.strip())
                            result['SubmergedCurves'] = num_curves
                            # Parse curve data if present
                            if num_curves > 0 and i + 1 < len(lines):
                                curve_data = []
                                k = i + 1
                                while k < len(lines) and not lines[k].strip().startswith("BC"):
                                    if '=' in lines[k]:
                                        break
                                    values = RasGeometryUtils.parse_fixed_width(lines[k], 8)
                                    curve_data.extend(values)
                                    k += 1
                                result['SubmergedData'] = curve_data
                        except:
                            pass

                i += 1

            logger.info(f"Extracted HTab parameters for {river}/{reach}/RS {rs}")
            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge HTab: {str(e)}")
            raise IOError(f"Failed to read bridge HTab: {str(e)}")

    # ========== CULVERT METHODS ==========

    # Culvert shape codes
    CULVERT_SHAPES = {
        1: 'Circular',
        2: 'Box',
        3: 'Pipe Arch',
        4: 'Ellipse',
        5: 'Arch',
        6: 'Semi-Circle',
        7: 'Low Profile Arch',
        8: 'High Profile Arch',
        9: 'Con Span'
    }

    @staticmethod
    @log_call
    def get_culverts(geom_file: Union[str, Path],
                    river: str,
                    reach: str,
                    rs: str) -> pd.DataFrame:
        """
        List all culverts at a bridge/culvert structure.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)

        Returns:
            pd.DataFrame with columns:
            - CulvertName: Culvert identifier (e.g., "Culvert #1")
            - Shape: Shape code (1=Circular, 2=Box, etc.)
            - ShapeName: Human-readable shape name
            - Span: Width/diameter (feet or meters)
            - Rise: Height (feet or meters)
            - Length: Culvert length
            - ManningsN: Manning's roughness coefficient
            - EntranceLoss: Entrance loss coefficient (Ke)
            - ExitLoss: Exit loss coefficient
            - InletType: Inlet control type code
            - OutletType: Outlet control type code
            - UpstreamInvert: Upstream invert elevation
            - UpstreamStation: Upstream station location
            - DownstreamInvert: Downstream invert elevation
            - DownstreamStation: Downstream station location
            - ChartNumber: Inlet control chart number
            - BottomN: Bottom Manning's n (if different)
            - NumBarrels: Number of barrels

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge/culvert structure not found

        Example:
            >>> culverts = RasStruct.get_culverts(
            ...     "A100_00_00.g08", "A120-00-00", "A120-00-00_0008", "23367"
            ... )
            >>> print(f"Found {len(culverts)} culverts")
            >>> print(culverts[['CulvertName', 'ShapeName', 'Span', 'Rise', 'Length']])

        Notes:
            Culvert shape codes:
            1=Circular, 2=Box, 3=Pipe Arch, 4=Ellipse, 5=Arch,
            6=Semi-Circle, 7=Low Profile Arch, 8=High Profile Arch, 9=Con Span
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            # Find bridge/culvert structure
            bridge_idx = RasStruct._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge/culvert not found: {river}/{reach}/RS {rs}")

            culverts = []

            # Search for culvert definitions
            i = bridge_idx
            while i < min(bridge_idx + RasStruct.DEFAULT_SEARCH_RANGE * 2, len(lines)):
                line = lines[i]

                # Stop at next structure
                if line.startswith("Type RM Length L Ch R =") and i > bridge_idx + 5:
                    break

                # Found culvert definition
                if line.startswith("Culvert="):
                    val = RasGeometryUtils.extract_keyword_value(line, "Culvert")
                    parts = [p.strip() for p in val.split(',')]

                    culvert_data = {
                        'CulvertName': None,
                        'Shape': None,
                        'ShapeName': None,
                        'Span': None,
                        'Rise': None,
                        'Length': None,
                        'ManningsN': None,
                        'EntranceLoss': None,
                        'ExitLoss': None,
                        'InletType': None,
                        'OutletType': None,
                        'UpstreamInvert': None,
                        'UpstreamStation': None,
                        'DownstreamInvert': None,
                        'DownstreamStation': None,
                        'ChartNumber': None,
                        'BottomN': None,
                        'NumBarrels': 1
                    }

                    # Parse culvert parameters
                    # Format: shape,span,rise,length,n,Ke,Kx?,inlet,outlet,us_inv,us_sta,ds_inv,ds_sta,name,flag,chart
                    if len(parts) > 0 and parts[0]:
                        try:
                            shape = int(parts[0])
                            culvert_data['Shape'] = shape
                            culvert_data['ShapeName'] = RasStruct.CULVERT_SHAPES.get(shape, f'Unknown ({shape})')
                        except: pass
                    if len(parts) > 1 and parts[1]:
                        try: culvert_data['Span'] = float(parts[1])
                        except: pass
                    if len(parts) > 2 and parts[2]:
                        try: culvert_data['Rise'] = float(parts[2])
                        except: pass
                    if len(parts) > 3 and parts[3]:
                        try: culvert_data['Length'] = float(parts[3])
                        except: pass
                    if len(parts) > 4 and parts[4]:
                        try: culvert_data['ManningsN'] = float(parts[4])
                        except: pass
                    if len(parts) > 5 and parts[5]:
                        try: culvert_data['EntranceLoss'] = float(parts[5])
                        except: pass
                    if len(parts) > 6 and parts[6]:
                        try: culvert_data['ExitLoss'] = float(parts[6])
                        except: pass
                    if len(parts) > 7 and parts[7]:
                        try: culvert_data['InletType'] = int(parts[7])
                        except: pass
                    if len(parts) > 8 and parts[8]:
                        try: culvert_data['OutletType'] = int(parts[8])
                        except: pass
                    if len(parts) > 9 and parts[9]:
                        try: culvert_data['UpstreamInvert'] = float(parts[9])
                        except: pass
                    if len(parts) > 10 and parts[10]:
                        try: culvert_data['UpstreamStation'] = float(parts[10])
                        except: pass
                    if len(parts) > 11 and parts[11]:
                        try: culvert_data['DownstreamInvert'] = float(parts[11])
                        except: pass
                    if len(parts) > 12 and parts[12]:
                        try: culvert_data['DownstreamStation'] = float(parts[12])
                        except: pass
                    if len(parts) > 13 and parts[13]:
                        culvert_data['CulvertName'] = parts[13].strip()
                    if len(parts) > 15 and parts[15]:
                        try: culvert_data['ChartNumber'] = int(parts[15])
                        except: pass

                    # Look for additional culvert parameters in following lines
                    for k in range(i + 1, min(i + 5, len(lines))):
                        next_line = lines[k]

                        if next_line.startswith("BC Culvert Barrel="):
                            barrel_val = RasGeometryUtils.extract_keyword_value(next_line, "BC Culvert Barrel")
                            barrel_parts = [p.strip() for p in barrel_val.split(',')]
                            if len(barrel_parts) > 0 and barrel_parts[0]:
                                try: culvert_data['NumBarrels'] = int(barrel_parts[0])
                                except: pass

                        elif next_line.startswith("Culvert Bottom n="):
                            bottom_n = RasGeometryUtils.extract_keyword_value(next_line, "Culvert Bottom n")
                            if bottom_n:
                                try: culvert_data['BottomN'] = float(bottom_n)
                                except: pass

                        elif next_line.startswith("Culvert="):
                            break  # Next culvert

                    culverts.append(culvert_data)

                i += 1

            if not culverts:
                logger.info(f"No culverts found at {river}/{reach}/RS {rs}")
                return pd.DataFrame()

            df = pd.DataFrame(culverts)
            logger.info(f"Found {len(df)} culverts at {river}/{reach}/RS {rs}")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading culverts: {str(e)}")
            raise IOError(f"Failed to read culverts: {str(e)}")

    @staticmethod
    @log_call
    def get_all_culverts(geom_file: Union[str, Path],
                        river: Optional[str] = None,
                        reach: Optional[str] = None) -> pd.DataFrame:
        """
        List all culverts in geometry file across all bridge/culvert structures.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: Optional filter by river name (case-sensitive)
            reach: Optional filter by reach name (case-sensitive)

        Returns:
            pd.DataFrame with all culvert data plus River, Reach, RS columns

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> all_culverts = RasStruct.get_all_culverts("A100_00_00.g08")
            >>> print(f"Found {len(all_culverts)} total culverts")
            >>> # Group by shape
            >>> print(all_culverts.groupby('ShapeName').size())
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            all_culverts = []
            current_river = None
            current_reach = None
            last_rs = None

            i = 0
            while i < len(lines):
                line = lines[i]

                # Track current river/reach
                if line.startswith("River Reach="):
                    values = RasGeometryUtils.extract_comma_list(line, "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]

                # Track RS from Type line
                elif line.startswith("Type RM Length L Ch R ="):
                    value_str = RasGeometryUtils.extract_keyword_value(line, "Type RM Length L Ch R")
                    values = [v.strip() for v in value_str.split(',')]
                    if len(values) > 1:
                        last_rs = values[1]

                # Found culvert definition
                elif line.startswith("Culvert="):
                    # Apply filters
                    if river is not None and current_river != river:
                        i += 1
                        continue
                    if reach is not None and current_reach != reach:
                        i += 1
                        continue

                    val = RasGeometryUtils.extract_keyword_value(line, "Culvert")
                    parts = [p.strip() for p in val.split(',')]

                    culvert_data = {
                        'River': current_river,
                        'Reach': current_reach,
                        'RS': last_rs,
                        'CulvertName': None,
                        'Shape': None,
                        'ShapeName': None,
                        'Span': None,
                        'Rise': None,
                        'Length': None,
                        'ManningsN': None,
                        'EntranceLoss': None,
                        'UpstreamInvert': None,
                        'DownstreamInvert': None
                    }

                    # Parse key parameters
                    if len(parts) > 0 and parts[0]:
                        try:
                            shape = int(parts[0])
                            culvert_data['Shape'] = shape
                            culvert_data['ShapeName'] = RasStruct.CULVERT_SHAPES.get(shape, f'Unknown ({shape})')
                        except: pass
                    if len(parts) > 1 and parts[1]:
                        try: culvert_data['Span'] = float(parts[1])
                        except: pass
                    if len(parts) > 2 and parts[2]:
                        try: culvert_data['Rise'] = float(parts[2])
                        except: pass
                    if len(parts) > 3 and parts[3]:
                        try: culvert_data['Length'] = float(parts[3])
                        except: pass
                    if len(parts) > 4 and parts[4]:
                        try: culvert_data['ManningsN'] = float(parts[4])
                        except: pass
                    if len(parts) > 5 and parts[5]:
                        try: culvert_data['EntranceLoss'] = float(parts[5])
                        except: pass
                    if len(parts) > 9 and parts[9]:
                        try: culvert_data['UpstreamInvert'] = float(parts[9])
                        except: pass
                    if len(parts) > 11 and parts[11]:
                        try: culvert_data['DownstreamInvert'] = float(parts[11])
                        except: pass
                    if len(parts) > 13 and parts[13]:
                        culvert_data['CulvertName'] = parts[13].strip()

                    all_culverts.append(culvert_data)

                i += 1

            df = pd.DataFrame(all_culverts)
            logger.info(f"Found {len(df)} total culverts in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading all culverts: {str(e)}")
            raise IOError(f"Failed to read all culverts: {str(e)}")
