"""
GeomInlineWeir - Inline weir operations for HEC-RAS geometry files

This module provides functionality for reading inline weir structure data
from HEC-RAS plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_weirs() - List all inline weirs with metadata
- get_profile() - Read station/elevation profile for weir crest
- get_gates() - Read gate parameters and opening definitions

Example Usage:
    >>> from ras_commander import GeomInlineWeir
    >>> from pathlib import Path
    >>>
    >>> # List all inline weirs
    >>> geom_file = Path("BaldEagle.g01")
    >>> weirs_df = GeomInlineWeir.get_weirs(geom_file)
    >>> print(f"Found {len(weirs_df)} inline weirs")
    >>>
    >>> # Get weir profile for specific inline weir
    >>> profile = GeomInlineWeir.get_profile(
    ...     geom_file, "Bald Eagle Creek", "Reach 1", "81084.18"
    ... )
    >>> print(profile.head())

Technical Notes:
    - Uses FORTRAN-era fixed-width format (8-char columns for numeric data)
    - Count interpretation: "#Inline Weir SE= 6" means 6 PAIRS (12 total values)
"""

from pathlib import Path
from typing import Union, Optional, List
import pandas as pd

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomInlineWeir:
    """
    Operations for parsing HEC-RAS inline weirs in geometry files.

    All methods are static and designed to be used without instantiation.
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8      # Character width for numeric data in geometry files
    VALUES_PER_LINE = 10        # Number of values per line in fixed-width format
    DEFAULT_SEARCH_RANGE = 100  # Lines to search for keywords after structure header

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
        """
        current_river = None
        current_reach = None
        last_rs = None

        for i, line in enumerate(lines):
            # Track current river/reach
            if line.startswith("River Reach="):
                values = GeomParser.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]

            # Track most recent Type RM Length line (contains RS)
            elif line.startswith("Type RM Length L Ch R ="):
                value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
                values = [v.strip() for v in value_str.split(',')]
                if len(values) > 1:
                    last_rs = values[1]  # RS is second value

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
    def _parse_paired_data(lines: List[str], start_idx: int, num_pairs: int,
                          col1_name: str, col2_name: str) -> pd.DataFrame:
        """Parse fixed-width paired data into DataFrame."""
        total_values = num_pairs * 2
        values = []

        i = start_idx
        while len(values) < total_values and i < len(lines):
            line = lines[i]
            if '=' in line and not line.strip().startswith('-'):
                break
            parsed = GeomParser.parse_fixed_width(line, GeomInlineWeir.FIXED_WIDTH_COLUMN)
            values.extend(parsed)
            i += 1

        col1_data = []
        col2_data = []
        for j in range(0, min(len(values), total_values), 2):
            if j + 1 < len(values):
                col1_data.append(values[j])
                col2_data.append(values[j + 1])

        return pd.DataFrame({col1_name: col1_data, col2_name: col2_data})

    @staticmethod
    @log_call
    def get_weirs(geom_file: Union[str, Path],
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
            >>> weirs = GeomInlineWeir.get_weirs("BaldEagle.g01")
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
                    values = GeomParser.extract_comma_list(line, "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]

                # Track RS from Type line
                elif line.startswith("Type RM Length L Ch R ="):
                    value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
                    values = [v.strip() for v in value_str.split(',')]
                    if len(values) > 1:
                        last_rs = values[1]

                # Track node name
                elif line.startswith("Node Name="):
                    last_node_name = GeomParser.extract_keyword_value(line, "Node Name")

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
                    pilot_flow_str = GeomParser.extract_keyword_value(line, "IW Pilot Flow")
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
                            if j + 1 < len(lines):
                                param_line = lines[j + 1]
                                parts = [p.strip() for p in param_line.split(',')]

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
                            if j + 1 < len(lines):
                                gate_line = lines[j + 1]
                                parts = [p.strip() for p in gate_line.split(',')]
                                if len(parts) > 13 and parts[13]:
                                    try:
                                        weir_data['NumOpenings'] = int(parts[13])
                                    except:
                                        pass

                        # Stop at next structure
                        elif search_line.startswith("Type RM Length L Ch R ="):
                            break

                    inline_weirs.append(weir_data)
                    last_node_name = None

                i += 1

            df = pd.DataFrame(inline_weirs)
            logger.debug(f"Found {len(df)} inline weirs in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading inline weirs: {str(e)}")
            raise IOError(f"Failed to read inline weirs: {str(e)}")

    @staticmethod
    @log_call
    def get_profile(geom_file: Union[str, Path],
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
            >>> profile = GeomInlineWeir.get_profile(
            ...     "BaldEagle.g01", "Bald Eagle Creek", "Reach 1", "81084.18"
            ... )
            >>> print(f"Profile has {len(profile)} points")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            weir_idx = GeomInlineWeir._find_inline_weir(lines, river, reach, rs)

            if weir_idx is None:
                raise ValueError(f"Inline weir not found: {river}/{reach}/RS {rs}")

            for j in range(weir_idx, min(weir_idx + GeomInlineWeir.DEFAULT_SEARCH_RANGE, len(lines))):
                line = lines[j]

                if line.startswith("#Inline Weir SE="):
                    count_str = GeomParser.extract_keyword_value(line, "#Inline Weir SE")
                    count = int(count_str.strip())

                    df = GeomInlineWeir._parse_paired_data(
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
    def get_gates(geom_file: Union[str, Path],
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
            >>> gates = GeomInlineWeir.get_gates(
            ...     "BaldEagle.g01", "Bald Eagle Creek", "Reach 1", "81084.18"
            ... )
            >>> print(f"Found {len(gates)} gates")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            weir_idx = GeomInlineWeir._find_inline_weir(lines, river, reach, rs)

            if weir_idx is None:
                raise ValueError(f"Inline weir not found: {river}/{reach}/RS {rs}")

            gates = []

            i = weir_idx
            while i < min(weir_idx + GeomInlineWeir.DEFAULT_SEARCH_RANGE, len(lines)):
                line = lines[i]

                if line.startswith("Type RM Length L Ch R =") and i > weir_idx + 5:
                    break

                if line.startswith("IW Gate Name Wd,"):
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

                        num_openings = gate_data['NumOpenings']
                        if num_openings > 0 and i + 2 < len(lines):
                            station_line = lines[i + 2]
                            if '=' not in station_line:
                                stations = GeomParser.parse_fixed_width(station_line, 8)
                                gate_data['OpeningStations'] = stations[:num_openings]

                        gates.append(gate_data)
                        i += 2

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
