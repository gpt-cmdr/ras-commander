"""
GeomCulvert - Culvert operations for HEC-RAS geometry files

This module provides functionality for reading culvert structure data
from HEC-RAS plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_culverts() - List all culverts at a bridge/culvert structure
- get_all() - List all culverts across entire geometry file

Example Usage:
    >>> from ras_commander import GeomCulvert
    >>> from pathlib import Path
    >>>
    >>> # List all culverts at a specific structure
    >>> geom_file = Path("model.g08")
    >>> culverts_df = GeomCulvert.get_culverts(geom_file, "River", "Reach", "23367")
    >>> print(f"Found {len(culverts_df)} culverts")
    >>>
    >>> # List all culverts in geometry file
    >>> all_culverts = GeomCulvert.get_all(geom_file)
    >>> print(all_culverts.groupby('ShapeName').size())

Technical Notes:
    - Culvert shape codes: 1=Circular, 2=Box, 3=Pipe Arch, 4=Ellipse, 5=Arch,
      6=Semi-Circle, 7=Low Profile Arch, 8=High Profile Arch, 9=Con Span
"""

from pathlib import Path
from typing import Union, Optional, List
import pandas as pd

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomCulvert:
    """
    Operations for parsing HEC-RAS culverts in geometry files.

    All methods are static and designed to be used without instantiation.
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8
    DEFAULT_SEARCH_RANGE = 200

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
    def _find_bridge(lines: List[str], river: str, reach: str, rs: str) -> Optional[int]:
        """Find bridge/culvert section and return line index."""
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
                    return i

        return None

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
            >>> culverts = GeomCulvert.get_culverts(
            ...     "model.g08", "River", "Reach", "23367"
            ... )
            >>> print(f"Found {len(culverts)} culverts")
            >>> print(culverts[['CulvertName', 'ShapeName', 'Span', 'Rise', 'Length']])
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r') as f:
                lines = f.readlines()

            bridge_idx = GeomCulvert._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge/culvert not found: {river}/{reach}/RS {rs}")

            culverts = []

            i = bridge_idx
            while i < min(bridge_idx + GeomCulvert.DEFAULT_SEARCH_RANGE * 2, len(lines)):
                line = lines[i]

                if line.startswith("Type RM Length L Ch R =") and i > bridge_idx + 5:
                    break

                if line.startswith("Culvert="):
                    val = GeomParser.extract_keyword_value(line, "Culvert")
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

                    if len(parts) > 0 and parts[0]:
                        try:
                            shape = int(parts[0])
                            culvert_data['Shape'] = shape
                            culvert_data['ShapeName'] = GeomCulvert.CULVERT_SHAPES.get(shape, f'Unknown ({shape})')
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

                    # Look for additional culvert parameters
                    for k in range(i + 1, min(i + 5, len(lines))):
                        next_line = lines[k]

                        if next_line.startswith("BC Culvert Barrel="):
                            barrel_val = GeomParser.extract_keyword_value(next_line, "BC Culvert Barrel")
                            barrel_parts = [p.strip() for p in barrel_val.split(',')]
                            if len(barrel_parts) > 0 and barrel_parts[0]:
                                try: culvert_data['NumBarrels'] = int(barrel_parts[0])
                                except: pass

                        elif next_line.startswith("Culvert Bottom n="):
                            bottom_n = GeomParser.extract_keyword_value(next_line, "Culvert Bottom n")
                            if bottom_n:
                                try: culvert_data['BottomN'] = float(bottom_n)
                                except: pass

                        elif next_line.startswith("Culvert="):
                            break

                    culverts.append(culvert_data)

                i += 1

            if not culverts:
                logger.debug(f"No culverts found at {river}/{reach}/RS {rs}")
                return pd.DataFrame()

            df = pd.DataFrame(culverts)
            logger.debug(f"Found {len(df)} culverts at {river}/{reach}/RS {rs}")
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
    def get_all(geom_file: Union[str, Path],
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
            >>> all_culverts = GeomCulvert.get_all("model.g08")
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

                elif line.startswith("Culvert="):
                    if river is not None and current_river != river:
                        i += 1
                        continue
                    if reach is not None and current_reach != reach:
                        i += 1
                        continue

                    val = GeomParser.extract_keyword_value(line, "Culvert")
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

                    if len(parts) > 0 and parts[0]:
                        try:
                            shape = int(parts[0])
                            culvert_data['Shape'] = shape
                            culvert_data['ShapeName'] = GeomCulvert.CULVERT_SHAPES.get(shape, f'Unknown ({shape})')
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
            logger.debug(f"Found {len(df)} total culverts in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading all culverts: {str(e)}")
            raise IOError(f"Failed to read all culverts: {str(e)}")
