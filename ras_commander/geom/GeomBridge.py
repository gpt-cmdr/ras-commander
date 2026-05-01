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
- get_hydraulic_methods() - Read bridge low-flow/high-flow method selections
- set_hydraulic_methods() - Set bridge low-flow/high-flow method selections
- get_htab() - Read hydraulic table parameters (returns DataFrame)
- get_htab_dict() - Read hydraulic table parameters (returns dict with invert)
- set_deck() - Create/replace bridge deck, high chord, and low chord blocks
- set_piers() - Create/replace/remove bridge pier blocks
- set_abutments() - Create/replace/remove bridge abutment blocks
- set_approach_sections() - Create/replace/remove BR U/BR D approach blocks
- set_coefficients() - Create/replace BR Coef, WSPro, and BC Design lines

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

    LOW_FLOW_METHOD_CODES = {
        'energy': 0,
        'momentum': 1,
        'yarnell': 2,
        'wspro': 3,
    }
    LOW_FLOW_METHOD_NAMES = {value: key for key, value in LOW_FLOW_METHOD_CODES.items()}
    HIGH_FLOW_METHODS = {'energy', 'pressure_weir'}

    BR_COEF_FIELD_NAMES = {
        0: 'use_energy',
        1: 'use_momentum',
        2: 'use_yarnell',
        3: 'yarnell_k',
        4: 'use_wspro',
        6: 'submerged_inlet_cd',
        7: 'submerged_inlet_outlet_cd',
        8: 'use_high_standard_step',
        9: 'momentum_cd',
        10: 'low_flow_method_code',
        11: 'low_chord_weir_check',
    }

    WSPRO_FIELD_NAMES = {
        0: 'left_top_elevation',
        1: 'right_top_elevation',
        2: 'left_toe_elevation',
        3: 'right_toe_elevation',
        4: 'abutment_type',
        5: 'abutment_slope',
        6: 'bridge_opening_width',
        7: 'centroid_station',
        8: 'wing_wall_type',
        9: 'wing_wall_width',
        10: 'wing_wall_angle',
        11: 'wing_wall_radius',
        12: 'guide_bank_type',
        13: 'guide_bank_length',
        14: 'guide_bank_offset',
        15: 'guide_bank_angle',
        16: 'piers_continuous',
        17: 'friction_slope_geometric_mean',
        18: 'use_tables',
        19: 'use_ce_approach',
        20: 'use_ce_guide_banks',
        21: 'use_ce_upstream_xs',
        22: 'use_ce_upstream_bridge',
        23: 'use_ce_downstream_bridge',
    }
    WSPRO_BOOLEAN_FIELDS = set(range(16, 24))

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
    def _find_structure(lines: List[str], river: str, reach: str, rs: str) -> Optional[Dict[str, Any]]:
        """
        Find any internal structure section and return its structure metadata.

        Returns:
            Structure dict from _find_all_structures() or None if not found.
        """
        rs = str(rs)

        for structure in GeomBridge._find_all_structures(lines):
            if (structure['river'] == river and
                    structure['reach'] == reach and
                    str(structure['rs']) == rs):
                return structure

        logger.debug(f"Structure not found: {river}/{reach}/RS {rs}")
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
    def _split_line_ending(line: str) -> tuple:
        """Split a text line into body and original line ending."""
        if line.endswith('\r\n'):
            return line[:-2], '\r\n'
        if line.endswith('\n'):
            return line[:-1], '\n'
        if line.endswith('\r'):
            return line[:-1], '\r'
        return line, ''

    @staticmethod
    def _split_comma_fields_from_line(line: str, prefix: str) -> List[str]:
        """Return comma fields after a HEC-RAS keyword while preserving field padding."""
        body, _ = GeomBridge._split_line_ending(line)
        return body[len(prefix):].split(',')

    @staticmethod
    def _parse_float_field(field: str) -> Optional[float]:
        stripped = field.strip()
        if not stripped:
            return None
        try:
            return float(stripped)

        except ValueError:
            return None

    @staticmethod
    def _is_missing(value: Any) -> bool:
        """Return True for None/NaN values without treating lists as ambiguous."""
        if value is None:
            return True
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _format_csv_value(value: Any, precision: int = 6) -> str:
        """Format a scalar for HEC-RAS comma-delimited geometry records."""
        if GeomBridge._is_missing(value):
            return ""

        if isinstance(value, (np.integer, int)):
            return str(int(value))

        if isinstance(value, (np.floating, float)):
            value = float(value)
            if np.isnan(value):
                return ""
            if value.is_integer():
                return str(int(value))
            return f"{value:.{precision}f}".rstrip('0').rstrip('.')

        try:
            float_value = float(value)
            if float_value.is_integer():
                return str(int(float_value))
            return f"{float_value:.{precision}f}".rstrip('0').rstrip('.')
        except (TypeError, ValueError):
            return str(value).strip()

    @staticmethod
    def _format_csv_line(keyword: str, values: List[Any]) -> str:
        """Format a keyword=value1,value2,... geometry record."""
        return f"{keyword}={','.join(GeomBridge._format_csv_value(v) for v in values)}\n"

    @staticmethod
    def _parse_csv_values(line: str) -> List[str]:
        """Parse raw comma-delimited values from a HEC-RAS geometry record."""
        value = line.split('=', 1)[1] if '=' in line else line
        return [part.strip() for part in value.rstrip('\n\r').split(',')]

    @staticmethod
    def _parse_optional_float(value: Any) -> Optional[float]:
        """Parse optional numeric values from geometry CSV fields."""
        if GeomBridge._is_missing(value):
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_int_field(field: str) -> Optional[int]:
        value = GeomBridge._parse_float_field(field)
        if value is None:
            return None
        return int(value)

    @staticmethod
    def _parse_bool_field(field: str) -> Optional[bool]:
        value = GeomBridge._parse_float_field(field)
        if value is None:
            return None
        return value != 0

    @staticmethod
    def _format_scalar_field(value: Any) -> str:
        if isinstance(value, bool):
            return '-1' if value else '0'
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    @staticmethod
    def _format_bool_field(value: bool, existing_field: str = '') -> str:
        if value:
            existing = existing_field.strip()
            if existing and existing not in {'0', '0.0'}:
                return existing
            return '-1'
        return '0'

    @staticmethod
    def _set_comma_field(fields: List[str], index: int, value: Any) -> None:
        """Set one comma field, preserving its surrounding whitespace when present."""
        while len(fields) <= index:
            fields.append('')

        old_field = fields[index]
        new_value = GeomBridge._format_scalar_field(value)
        if old_field.strip():
            leading_count = len(old_field) - len(old_field.lstrip())
            trailing_count = len(old_field) - len(old_field.rstrip())
            leading = old_field[:leading_count]
            trailing = old_field[len(old_field) - trailing_count:] if trailing_count else ''
            fields[index] = f"{leading}{new_value}{trailing}"
        else:
            fields[index] = new_value

    @staticmethod
    def _default_br_coef_fields() -> List[str]:
        """Return a conservative default BR Coef field list for structures missing the line."""
        return ['-1 ', ' 0 ', ' 0 ', '', ' 0 ', '', '', '0.8', '0', '', '0', '']

    @staticmethod
    def _format_comma_line(prefix: str, fields: List[str], line_ending: str = '\n') -> str:
        return f"{prefix}{','.join(fields)}{line_ending}"

    @staticmethod
    def _find_bridge_method_lines(
        lines: List[str],
        bridge_idx: int,
        struct_end_idx: int,
        opening_index: int = 0
    ) -> Dict[str, Optional[int]]:
        """Find BR Coef and matching WSPro records for one bridge opening."""
        if opening_index < 0:
            raise ValueError("opening_index must be >= 0")

        br_coef_indices = []
        wspro_indices = []

        for i in range(bridge_idx, struct_end_idx):
            line = lines[i]
            if line.startswith("BR Coef="):
                br_coef_indices.append(i)
            elif line.startswith("WSPro="):
                wspro_indices.append(i)

        br_coef_idx = br_coef_indices[opening_index] if opening_index < len(br_coef_indices) else None
        wspro_idx = None

        if br_coef_idx is not None:
            next_br_coef_idx = (
                br_coef_indices[opening_index + 1]
                if opening_index + 1 < len(br_coef_indices)
                else struct_end_idx
            )
            for idx in wspro_indices:
                if br_coef_idx < idx < next_br_coef_idx:
                    wspro_idx = idx
                    break
        elif opening_index < len(wspro_indices):
            wspro_idx = wspro_indices[opening_index]

        return {
            'br_coef_idx': br_coef_idx,
            'wspro_idx': wspro_idx,
            'br_coef_count': len(br_coef_indices),
            'wspro_count': len(wspro_indices),
        }

    @staticmethod
    def _find_br_coef_insert_idx(lines: List[str], bridge_idx: int, struct_end_idx: int) -> int:
        """Choose a stable insertion point for a missing BR Coef record."""
        for i in range(bridge_idx + 1, struct_end_idx):
            if (lines[i].startswith("WSPro=") or
                    lines[i].startswith("BC Design=") or
                    lines[i].startswith("BC HTab")):
                return i
        return struct_end_idx

    @staticmethod
    def _find_bridge_deck_line(lines: List[str], bridge_idx: int, struct_end_idx: int) -> Optional[int]:
        """Find the data line following the bridge Deck Dist Width WeirC header."""
        for i in range(bridge_idx + 1, struct_end_idx - 1):
            if lines[i].startswith("Deck Dist Width WeirC"):
                return i + 1
        return None

    @staticmethod
    def _parse_wspro_fields(fields: List[str]) -> Dict[str, Any]:
        wspro = {}
        for idx, name in GeomBridge.WSPRO_FIELD_NAMES.items():
            if idx >= len(fields):
                wspro[name] = None
                continue
            if idx in GeomBridge.WSPRO_BOOLEAN_FIELDS:
                wspro[name] = GeomBridge._parse_bool_field(fields[idx])
            else:
                value = GeomBridge._parse_float_field(fields[idx])
                wspro[name] = value if value is not None else None
        return wspro

    @staticmethod
    def _parse_br_coef_fields(fields: List[str]) -> Dict[str, Any]:
        method_code = GeomBridge._parse_int_field(fields[10]) if len(fields) > 10 else None
        high_standard_step = (
            GeomBridge._parse_bool_field(fields[8]) if len(fields) > 8 else None
        )

        coefficients = {
            'momentum_cd': GeomBridge._parse_float_field(fields[9]) if len(fields) > 9 else None,
            'yarnell_k': GeomBridge._parse_float_field(fields[3]) if len(fields) > 3 else None,
            'submerged_inlet_cd': GeomBridge._parse_float_field(fields[6]) if len(fields) > 6 else None,
            'submerged_inlet_outlet_cd': (
                GeomBridge._parse_float_field(fields[7]) if len(fields) > 7 else None
            ),
            'low_chord_weir_check': GeomBridge._parse_float_field(fields[11]) if len(fields) > 11 else None,
        }

        enabled = {
            'energy': GeomBridge._parse_bool_field(fields[0]) if len(fields) > 0 else None,
            'momentum': GeomBridge._parse_bool_field(fields[1]) if len(fields) > 1 else None,
            'yarnell': GeomBridge._parse_bool_field(fields[2]) if len(fields) > 2 else None,
            'wspro': GeomBridge._parse_bool_field(fields[4]) if len(fields) > 4 else None,
        }

        return {
            'low_flow_method_code': method_code,
            'low_flow_method': GeomBridge.LOW_FLOW_METHOD_NAMES.get(method_code),
            'high_flow_method': (
                'energy' if high_standard_step else 'pressure_weir'
                if high_standard_step is not None else None
            ),
            'use_high_standard_step': high_standard_step,
            'enabled_low_flow_methods': enabled,
            'coefficients': coefficients,
        }

    @staticmethod
    def _parse_bridge_deck_fields(fields: List[str]) -> Dict[str, Any]:
        """Parse common bridge deck fields from the Deck Dist Width WeirC record."""
        return {
            'deck_distance': GeomBridge._parse_float_field(fields[0]) if len(fields) > 0 else None,
            'deck_width': GeomBridge._parse_float_field(fields[1]) if len(fields) > 1 else None,
            'weir_coefficient': GeomBridge._parse_float_field(fields[2]) if len(fields) > 2 else None,
            'skew': GeomBridge._parse_float_field(fields[3]) if len(fields) > 3 else None,
            'max_submergence': GeomBridge._parse_float_field(fields[8]) if len(fields) > 8 else None,
            'is_ogee': GeomBridge._parse_bool_field(fields[9]) if len(fields) > 9 else None,
        }

    @staticmethod
    def _normalize_hydraulic_method(method: Optional[str], accepted: set, field_name: str) -> Optional[str]:
        if method is None:
            return None
        normalized = method.strip().lower().replace('-', '_').replace(' ', '_')
        if normalized not in accepted:
            accepted_values = ', '.join(sorted(accepted))
            raise ValueError(f"{field_name} must be one of: {accepted_values}")
        return normalized

    @staticmethod
    def _validate_hydraulic_method_selection(
        low_flow_method: Optional[str],
        high_flow_method: Optional[str],
        enabled: Dict[str, Optional[bool]],
        wspro_idx: Optional[int],
        require_selected_enabled: bool = True,
    ) -> None:
        if (require_selected_enabled and
                low_flow_method is not None and
                enabled.get(low_flow_method) is False):
            raise ValueError(
                f"selected low_flow_method '{low_flow_method}' cannot be disabled"
            )
        if low_flow_method == 'wspro' and wspro_idx is None:
            raise ValueError("low_flow_method 'wspro' requires an existing WSPro= record")
        if high_flow_method is not None and high_flow_method not in GeomBridge.HIGH_FLOW_METHODS:
            accepted_values = ', '.join(sorted(GeomBridge.HIGH_FLOW_METHODS))
            raise ValueError(f"high_flow_method must be one of: {accepted_values}")

    @staticmethod
    def _parse_optional_int(value: Any) -> Optional[int]:
        """Parse optional integer values from geometry CSV fields."""
        parsed = GeomBridge._parse_optional_float(value)
        if parsed is None:
            return None
        return int(parsed)

    @staticmethod
    def _listify(value: Any) -> List[Any]:
        """Return a plain list from list-like DataFrame cells or scalar values."""
        if GeomBridge._is_missing(value):
            return []
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, (list, tuple, pd.Series)):
            return list(value)
        return [value]

    @staticmethod
    def _read_fixed_width_values(lines: List[str], start_idx: int, count: int) -> tuple:
        """
        Read a fixed-width numeric vector and return (values, next_line_idx).

        Bridge deck, pier, and abutment sub-blocks store each station/elevation
        vector independently. Counts therefore describe one vector, not paired
        station/elevation rows.
        """
        values = []
        idx = start_idx

        while len(values) < count and idx < len(lines):
            if '=' in lines[idx]:
                break
            values.extend(GeomParser.parse_fixed_width(lines[idx], GeomBridge.FIXED_WIDTH_COLUMN))
            idx += 1

        if len(values) < count:
            raise ValueError(f"Expected {count} fixed-width values, found {len(values)}")

        return values[:count], idx

    @staticmethod
    def _format_fixed_width_values(values: List[Any], precision: int = 2) -> List[str]:
        """Format a single numeric vector as HEC-RAS fixed-width data lines."""
        numeric_values = [float(value) for value in values]
        return GeomParser.format_fixed_width(
            numeric_values,
            column_width=GeomBridge.FIXED_WIDTH_COLUMN,
            values_per_line=GeomBridge.VALUES_PER_LINE,
            precision=precision
        )

    @staticmethod
    def _find_section_end(lines: List[str], section_start_idx: int) -> int:
        """Find the first line after a Type RM geometry section."""
        for i in range(section_start_idx + 1, len(lines)):
            line = lines[i]
            if (line.startswith("Type RM Length L Ch R =") or
                    line.startswith("River Reach=") or
                    line.startswith("Reach XS=")):
                return i
        return len(lines)

    @staticmethod
    def _find_station_section(lines: List[str], river: str, reach: str, rs: str) -> Optional[Dict[str, Any]]:
        """Find an existing geometry station section by river/reach/RS."""
        current_river = None
        current_reach = None
        rs = str(rs)

        for i, line in enumerate(lines):
            if line.startswith("River Reach="):
                values = GeomParser.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]

            elif line.startswith("Type RM Length L Ch R ="):
                value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
                values = [v.strip() for v in value_str.split(',')]
                if len(values) > 1 and current_river == river and current_reach == reach and values[1] == rs:
                    return {
                        'river': current_river,
                        'reach': current_reach,
                        'rs': values[1],
                        'type_idx': i,
                        'end_idx': GeomBridge._find_section_end(lines, i),
                        'type_code': GeomBridge._parse_optional_int(values[0])
                    }

        return None

    @staticmethod
    def _format_bridge_header(bridge_flags: Optional[List[Any]] = None) -> str:
        """Format the Bridge Culvert marker line."""
        flags = bridge_flags if bridge_flags is not None else [-1, 0, -1, -1, 0]
        return f"Bridge Culvert-{','.join(GeomBridge._format_csv_value(flag) for flag in flags)} \n"

    @staticmethod
    def _set_station_type(lines: List[str], type_idx: int, type_code: int = 3) -> None:
        """Update the section type code on a Type RM Length line in-place."""
        line = lines[type_idx]
        if '=' not in line:
            return

        ending = '\n' if line.endswith('\n') else ''
        body = line.rstrip('\n\r')
        prefix, value = body.split('=', 1)
        parts = value.split(',')
        if not parts:
            return
        parts[0] = f" {type_code} "
        lines[type_idx] = f"{prefix}={','.join(parts)}{ending}"

    @staticmethod
    def _bridge_insert_index_for_station(lines: List[str], station: Dict[str, Any]) -> int:
        """Choose where to insert a missing Bridge Culvert block in a station section."""
        insert_idx = station['type_idx'] + 1
        in_description = False

        for idx in range(station['type_idx'] + 1, station['end_idx']):
            line = lines[idx]
            stripped = line.strip()

            if line.startswith("BEGIN DESCRIPTION:"):
                in_description = True
                insert_idx = idx + 1
                continue

            if in_description:
                insert_idx = idx + 1
                if line.startswith("END DESCRIPTION:"):
                    in_description = False
                continue

            if (line.startswith("Node Name=") or
                    line.startswith("Node Photo=") or
                    line.startswith("Node Last Edited Time=") or
                    stripped == ""):
                insert_idx = idx + 1
                continue

            break

        return insert_idx

    @staticmethod
    def _ensure_bridge_block(lines: List[str],
                             river: str,
                             reach: str,
                             rs: str,
                             bridge_flags: Optional[List[Any]] = None) -> tuple:
        """
        Ensure a Bridge Culvert marker exists and return (lines, marker_idx, created).

        If the bridge marker is missing but the river/reach/station exists, the
        station is converted to type 3 and a bridge marker is inserted after the
        station metadata.
        """
        bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)
        if bridge_idx is not None:
            return lines, bridge_idx, False

        station = GeomBridge._find_station_section(lines, river, reach, rs)
        if station is None:
            raise ValueError(f"Station not found: {river}/{reach}/RS {rs}")

        modified_lines = lines.copy()
        GeomBridge._set_station_type(modified_lines, station['type_idx'], type_code=3)
        insert_idx = GeomBridge._bridge_insert_index_for_station(station=station, lines=modified_lines)
        modified_lines[insert_idx:insert_idx] = [GeomBridge._format_bridge_header(bridge_flags)]

        return modified_lines, insert_idx, True

    @staticmethod
    def _get_bridge_range(lines: List[str], river: str, reach: str, rs: str) -> tuple:
        """Return (marker_idx, end_idx) for an existing bridge block."""
        bridge_idx = GeomBridge._find_bridge(lines, river, reach, str(rs))
        if bridge_idx is None:
            raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")
        return bridge_idx, GeomBridge._find_structure_end(lines, bridge_idx)

    @staticmethod
    def _find_deck_block_range(lines: List[str], bridge_idx: int, bridge_end_idx: int) -> tuple:
        """Return (start, end) for the deck block or (None, None)."""
        for idx in range(bridge_idx, bridge_end_idx):
            if lines[idx].startswith("Deck Dist Width WeirC"):
                if idx + 1 >= bridge_end_idx:
                    return idx, idx + 1

                parts = GeomBridge._parse_csv_values(lines[idx + 1])
                num_up = GeomBridge._parse_optional_int(parts[4]) if len(parts) > 4 else 0
                num_dn = GeomBridge._parse_optional_int(parts[5]) if len(parts) > 5 else 0
                num_up = num_up or 0
                num_dn = num_dn or 0

                end_idx = idx + 2
                try:
                    for count in (num_up, num_up, num_up, num_dn, num_dn, num_dn):
                        if count > 0:
                            _, end_idx = GeomBridge._read_fixed_width_values(lines, end_idx, count)
                except ValueError:
                    end_idx = idx + 2
                    while end_idx < bridge_end_idx and '=' not in lines[end_idx]:
                        end_idx += 1

                return idx, end_idx

        return None, None

    @staticmethod
    def _find_pier_block_ranges(lines: List[str], bridge_idx: int, bridge_end_idx: int) -> List[tuple]:
        """Return ranges for all pier blocks in a bridge."""
        ranges = []
        idx = bridge_idx

        while idx < bridge_end_idx:
            if not lines[idx].startswith("Pier Skew, UpSta & Num, DnSta & Num="):
                idx += 1
                continue

            parts = GeomBridge._parse_csv_values(lines[idx])
            num_up = GeomBridge._parse_optional_int(parts[2]) if len(parts) > 2 else 0
            num_dn = GeomBridge._parse_optional_int(parts[4]) if len(parts) > 4 else 0
            num_up = num_up or 0
            num_dn = num_dn or 0

            end_idx = idx + 1
            try:
                for count in (num_up, num_up, num_dn, num_dn):
                    if count > 0:
                        _, end_idx = GeomBridge._read_fixed_width_values(lines, end_idx, count)
            except ValueError:
                end_idx = idx + 1
                while end_idx < bridge_end_idx and '=' not in lines[end_idx]:
                    end_idx += 1

            ranges.append((idx, end_idx))
            idx = end_idx

        return ranges

    @staticmethod
    def _find_abutment_block_ranges(lines: List[str], bridge_idx: int, bridge_end_idx: int) -> List[tuple]:
        """Return ranges for all abutment blocks in a bridge."""
        ranges = []
        idx = bridge_idx

        while idx < bridge_end_idx:
            if not lines[idx].startswith("Abutment Skew #Up #Dn="):
                idx += 1
                continue

            parts = GeomBridge._parse_csv_values(lines[idx])
            num_up = GeomBridge._parse_optional_int(parts[1]) if len(parts) > 1 else 0
            num_dn = GeomBridge._parse_optional_int(parts[2]) if len(parts) > 2 else 0
            num_up = num_up or 0
            num_dn = num_dn or 0

            end_idx = idx + 1
            try:
                for count in (num_up, num_up, num_dn, num_dn):
                    if count > 0:
                        _, end_idx = GeomBridge._read_fixed_width_values(lines, end_idx, count)
            except ValueError:
                end_idx = idx + 1
                while end_idx < bridge_end_idx and '=' not in lines[end_idx]:
                    end_idx += 1

            ranges.append((idx, end_idx))
            idx = end_idx

        return ranges

    @staticmethod
    def _find_approach_block_ranges(lines: List[str], bridge_idx: int, bridge_end_idx: int) -> List[tuple]:
        """Return ranges for embedded BR U/BR D approach section blocks."""
        ranges = []
        idx = bridge_idx

        while idx < bridge_end_idx:
            if not (lines[idx].startswith("BR U ") or lines[idx].startswith("BR D ")):
                idx += 1
                continue

            end_idx = idx + 1
            if "#Sta/Elev=" in lines[idx]:
                count = GeomBridge._parse_optional_int(lines[idx].split('=', 1)[1])
                if count:
                    try:
                        _, end_idx = GeomBridge._read_fixed_width_values(lines, idx + 1, count * 2)
                    except ValueError:
                        end_idx = idx + 1
            elif "#Mann=" in lines[idx]:
                values = GeomBridge._parse_csv_values(lines[idx])
                count = GeomBridge._parse_optional_int(values[0]) if values else 0
                if count:
                    try:
                        _, end_idx = GeomBridge._read_fixed_width_values(lines, idx + 1, count * 3)
                    except ValueError:
                        end_idx = idx + 1
            elif "#XS Ineff=" in lines[idx]:
                end_idx = idx + 1
                while end_idx < bridge_end_idx and '=' not in lines[end_idx]:
                    end_idx += 1

            ranges.append((idx, end_idx))
            idx = end_idx

        return ranges

    @staticmethod
    def _remove_ranges(lines: List[str], ranges: List[tuple]) -> List[str]:
        """Remove ranges from a line list, processing from bottom to top."""
        modified = lines.copy()
        for start_idx, end_idx in sorted(ranges, reverse=True):
            del modified[start_idx:end_idx]
        return modified

    @staticmethod
    def _insert_index_for_bridge_section(lines: List[str],
                                         bridge_idx: int,
                                         bridge_end_idx: int,
                                         section: str) -> int:
        """Find the insertion index for a bridge sub-section using canonical order."""
        section_order = {
            'deck': 0,
            'piers': 1,
            'abutments': 2,
            'approach': 3,
            'coefficients': 4,
            'htab': 5,
        }
        prefixes = [
            ('deck', ("Deck Dist Width WeirC",)),
            ('piers', ("Pier Skew, UpSta & Num, DnSta & Num=",)),
            ('abutments', ("Abutment Skew #Up #Dn=",)),
            ('approach', ("BR U ", "BR D ")),
            ('coefficients', ("BR Coef=", "WSPro=", "BC Design=")),
            ('htab', ("BC HTab ", "BC Use User HTab Curves=", "BC User HTab ")),
        ]
        target_order = section_order[section]

        for idx in range(bridge_idx + 1, bridge_end_idx):
            for name, section_prefixes in prefixes:
                if section_order[name] > target_order and lines[idx].startswith(section_prefixes):
                    return idx

        return bridge_end_idx

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
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
                        'NumUpstreamDeckPoints': None,
                        'NumDownstreamDeckPoints': None,
                        'DeckDistance': None,
                        'DeckWidth': None,
                        'WeirCoefficient': None,
                        'Skew': None,
                        'MaxSubmergence': None,
                        'NumPiers': 0,
                        'HasAbutment': False,
                        'HTabHWMax': None,
                        'NodeLastEdited': last_edited
                    }

                    bridge_end_idx = GeomBridge._find_structure_end(lines, i)
                    deck_start, _ = GeomBridge._find_deck_block_range(lines, i, bridge_end_idx)
                    if deck_start is not None and deck_start + 1 < bridge_end_idx:
                        parts = GeomBridge._parse_csv_values(lines[deck_start + 1])

                        if len(parts) > 0:
                            bridge_data['DeckDistance'] = GeomBridge._parse_optional_float(parts[0])
                        if len(parts) > 1:
                            bridge_data['DeckWidth'] = GeomBridge._parse_optional_float(parts[1])
                        if len(parts) > 2:
                            bridge_data['WeirCoefficient'] = GeomBridge._parse_optional_float(parts[2])
                        if len(parts) > 3:
                            bridge_data['Skew'] = GeomBridge._parse_optional_float(parts[3])
                        if len(parts) > 4:
                            bridge_data['NumUpstreamDeckPoints'] = GeomBridge._parse_optional_int(parts[4])
                        if len(parts) > 5:
                            bridge_data['NumDownstreamDeckPoints'] = GeomBridge._parse_optional_int(parts[5])
                        if len(parts) > 8:
                            bridge_data['MaxSubmergence'] = GeomBridge._parse_optional_float(parts[8])

                        bridge_data['NumDecks'] = (
                            bridge_data['NumUpstreamDeckPoints'] or
                            bridge_data['NumDownstreamDeckPoints']
                        )

                    bridge_data['NumPiers'] = len(GeomBridge._find_pier_block_ranges(lines, i, bridge_end_idx))
                    bridge_data['HasAbutment'] = bool(GeomBridge._find_abutment_block_ranges(lines, i, bridge_end_idx))

                    for j in range(i + 1, bridge_end_idx):
                        search_line = lines[j]

                        if search_line.startswith("BC HTab HWMax="):
                            val = GeomParser.extract_keyword_value(search_line, "BC HTab HWMax")
                            if val:
                                try: bridge_data['HTabHWMax'] = float(val)
                                except: pass

                    bridges.append(bridge_data)
                    last_node_name = None
                    last_edited = None

                i += 1

            df = pd.DataFrame(bridges)
            logger.debug(f"Found {len(df)} bridges in {geom_file.name}")
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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            deck_data = []
            bridge_end_idx = GeomBridge._find_structure_end(lines, bridge_idx)
            deck_start, _ = GeomBridge._find_deck_block_range(lines, bridge_idx, bridge_end_idx)

            if deck_start is None or deck_start + 1 >= bridge_end_idx:
                df = pd.DataFrame(deck_data)
                logger.info(f"No deck geometry found for {river}/{reach}/RS {rs}")
                return df

            parts = GeomBridge._parse_csv_values(lines[deck_start + 1])
            num_up = GeomBridge._parse_optional_int(parts[4]) if len(parts) > 4 else 0
            num_dn = GeomBridge._parse_optional_int(parts[5]) if len(parts) > 5 else 0
            num_up = num_up or 0
            num_dn = num_dn or 0

            data_idx = deck_start + 2

            if num_up > 0:
                stations, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_up)
                elevations, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_up)
                lowchords, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_up)

                for idx in range(min(len(stations), len(elevations), len(lowchords))):
                    deck_data.append({
                        'Location': 'upstream',
                        'Station': stations[idx],
                        'Elevation': elevations[idx],
                        'LowChord': lowchords[idx]
                    })

            if num_dn > 0:
                stations, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_dn)
                elevations, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_dn)
                lowchords, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_dn)

                for idx in range(min(len(stations), len(elevations), len(lowchords))):
                    deck_data.append({
                        'Location': 'downstream',
                        'Station': stations[idx],
                        'Elevation': elevations[idx],
                        'LowChord': lowchords[idx]
                    })

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            piers = []
            pier_index = 0
            bridge_end_idx = GeomBridge._find_structure_end(lines, bridge_idx)
            pier_ranges = GeomBridge._find_pier_block_ranges(lines, bridge_idx, bridge_end_idx)

            for pier_start, _ in pier_ranges:
                pier_index += 1
                line = lines[pier_start]
                parts = GeomBridge._parse_csv_values(line)

                pier_data = {
                    'PierIndex': pier_index,
                    'Skew': GeomBridge._parse_optional_float(parts[0]) if len(parts) > 0 else None,
                    'UpstreamStation': GeomBridge._parse_optional_float(parts[1]) if len(parts) > 1 else None,
                    'NumUpstreamPoints': GeomBridge._parse_optional_int(parts[2]) if len(parts) > 2 else 0,
                    'DownstreamStation': GeomBridge._parse_optional_float(parts[3]) if len(parts) > 3 else None,
                    'NumDownstreamPoints': GeomBridge._parse_optional_int(parts[4]) if len(parts) > 4 else 0,
                    'UpstreamWidths': [],
                    'UpstreamElevations': [],
                    'DownstreamWidths': [],
                    'DownstreamElevations': []
                }

                num_up = pier_data['NumUpstreamPoints'] or 0
                num_dn = pier_data['NumDownstreamPoints'] or 0
                data_idx = pier_start + 1

                if num_up > 0:
                    pier_data['UpstreamWidths'], data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_up)
                    pier_data['UpstreamElevations'], data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_up)

                if num_dn > 0:
                    pier_data['DownstreamWidths'], data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_dn)
                    pier_data['DownstreamElevations'], data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_dn)

                piers.append(pier_data)

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            abutment_data = []
            bridge_end_idx = GeomBridge._find_structure_end(lines, bridge_idx)
            abutment_ranges = GeomBridge._find_abutment_block_ranges(lines, bridge_idx, bridge_end_idx)

            for abutment_index, (abutment_start, _) in enumerate(abutment_ranges, start=1):
                line = lines[abutment_start]
                parts = GeomBridge._parse_csv_values(line)

                skew = GeomBridge._parse_optional_float(parts[0]) if len(parts) > 0 else None
                num_up = GeomBridge._parse_optional_int(parts[1]) if len(parts) > 1 else 0
                num_dn = GeomBridge._parse_optional_int(parts[2]) if len(parts) > 2 else 0
                num_up = num_up or 0
                num_dn = num_dn or 0
                data_idx = abutment_start + 1

                if num_up > 0:
                    stations, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_up)
                    params, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_up)

                    for idx in range(min(len(stations), len(params))):
                        abutment_data.append({
                            'AbutmentIndex': abutment_index,
                            'Skew': skew,
                            'Location': 'upstream',
                            'Station': stations[idx],
                            'Parameter': params[idx]
                        })

                if num_dn > 0:
                    stations, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_dn)
                    params, data_idx = GeomBridge._read_fixed_width_values(lines, data_idx, num_dn)

                    for idx in range(min(len(stations), len(params))):
                        abutment_data.append({
                            'AbutmentIndex': abutment_index,
                            'Skew': skew,
                            'Location': 'downstream',
                            'Station': stations[idx],
                            'Parameter': params[idx]
                        })

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            approach_data = []
            bridge_end_idx = GeomBridge._find_structure_end(lines, bridge_idx)

            for j in range(bridge_idx, bridge_end_idx):
                line = lines[j]

                # Upstream station/elevation
                if line.startswith("BR U #Sta/Elev="):
                    count_str = GeomParser.extract_keyword_value(line, "BR U #Sta/Elev")
                    count = int(count_str.strip())

                    values, _ = GeomBridge._read_fixed_width_values(lines, j + 1, count * 2)

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

                    values, _ = GeomBridge._read_fixed_width_values(lines, j + 1, count * 2)

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            coef_data = []
            bridge_end_idx = GeomBridge._find_structure_end(lines, bridge_idx)

            for j in range(bridge_idx, bridge_end_idx):
                line = lines[j]

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
    def get_hydraulic_methods(geom_file: Union[str, Path],
                              river: str,
                              reach: str,
                              rs: str,
                              opening_index: int = 0) -> Dict[str, Any]:
        """
        Read bridge hydraulic method selections from geometry text records.

        This parser reads the bridge ``Bridge Culvert-`` marker, deck/weir
        coefficient record, and the selected opening's ``BR Coef=`` and
        ``WSPro=`` records. The ``BR Coef=`` record stores the selected
        low-flow method code and high-flow method flag used by the Bridge
        Modeling Approach editor.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)
            opening_index: Zero-based bridge opening/coefficient record index
                when a bridge has multiple ``BR Coef=`` records (default 0)

        Returns:
            dict with keys:
            - low_flow_method: one of ``energy``, ``momentum``, ``yarnell``,
              ``wspro`` or None if no method code is present
            - high_flow_method: ``energy`` or ``pressure_weir`` when available
            - enabled_low_flow_methods: per-method compute flags from BR Coef
            - coefficients: Momentum, Yarnell, pressure-flow, deck/weir, and
              audit values
            - deck: parsed values from the ``Deck Dist Width WeirC`` record
            - wspro: named WSPRO fields, or None if no WSPro record exists
            - raw: original method records and comma fields for audit

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge or opening is not found
            IOError: If file read fails

        Example:
            >>> methods = GeomBridge.get_hydraulic_methods(
            ...     "model.g01", "Beaver Creek", "Kentwood", "5.4"
            ... )
            >>> methods["low_flow_method"]
            'momentum'
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)
            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            struct_end_idx = GeomBridge._find_structure_end(lines, bridge_idx)
            method_lines = GeomBridge._find_bridge_method_lines(
                lines, bridge_idx, struct_end_idx, opening_index
            )

            br_coef_idx = method_lines['br_coef_idx']
            wspro_idx = method_lines['wspro_idx']

            if br_coef_idx is None:
                if method_lines['br_coef_count'] == 0:
                    raise ValueError(
                        f"BR Coef= record not found for bridge {river}/{reach}/RS {rs}"
                    )
                raise ValueError(
                    f"BR Coef= opening_index {opening_index} not found for "
                    f"{river}/{reach}/RS {rs}; found {method_lines['br_coef_count']}"
                )

            br_coef_fields = GeomBridge._split_comma_fields_from_line(
                lines[br_coef_idx], "BR Coef="
            )
            parsed = GeomBridge._parse_br_coef_fields(br_coef_fields)

            wspro_fields = None
            wspro = None
            if wspro_idx is not None:
                wspro_fields = GeomBridge._split_comma_fields_from_line(
                    lines[wspro_idx], "WSPro="
                )
                wspro = GeomBridge._parse_wspro_fields(wspro_fields)

            bridge_culvert_fields = GeomBridge._split_comma_fields_from_line(
                lines[bridge_idx], "Bridge Culvert-"
            )
            deck_idx = GeomBridge._find_bridge_deck_line(lines, bridge_idx, struct_end_idx)
            deck_fields = None
            deck = None
            if deck_idx is not None:
                deck_body, _ = GeomBridge._split_line_ending(lines[deck_idx])
                deck_fields = deck_body.split(',')
                deck = GeomBridge._parse_bridge_deck_fields(deck_fields)
                parsed['coefficients']['weir_coefficient'] = deck['weir_coefficient']
            else:
                parsed['coefficients']['weir_coefficient'] = None

            result = {
                'river': river,
                'reach': reach,
                'rs': str(rs),
                'opening_index': opening_index,
                'low_flow_method': parsed['low_flow_method'],
                'low_flow_method_code': parsed['low_flow_method_code'],
                'high_flow_method': parsed['high_flow_method'],
                'use_high_standard_step': parsed['use_high_standard_step'],
                'enabled_low_flow_methods': parsed['enabled_low_flow_methods'],
                'coefficients': parsed['coefficients'],
                'deck': deck,
                'wspro': wspro,
                'raw': {
                    'bridge_culvert_line': lines[bridge_idx].rstrip('\r\n'),
                    'bridge_culvert_fields': [field.strip() for field in bridge_culvert_fields],
                    'bridge_culvert_flags': GeomBridge._parse_bridge_header(lines[bridge_idx]),
                    'br_coef_line': lines[br_coef_idx].rstrip('\r\n'),
                    'br_coef_fields': [field.strip() for field in br_coef_fields],
                    'deck_line': lines[deck_idx].rstrip('\r\n') if deck_idx is not None else None,
                    'deck_fields': (
                        [field.strip() for field in deck_fields]
                        if deck_fields is not None else None
                    ),
                    'wspro_line': lines[wspro_idx].rstrip('\r\n') if wspro_idx is not None else None,
                    'wspro_fields': (
                        [field.strip() for field in wspro_fields]
                        if wspro_fields is not None else None
                    ),
                },
            }

            logger.info(
                f"Read bridge hydraulic methods for {river}/{reach}/RS {rs}: "
                f"low={result['low_flow_method']}, high={result['high_flow_method']}"
            )
            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bridge hydraulic methods: {str(e)}")
            raise IOError(f"Failed to read bridge hydraulic methods: {str(e)}")

    @staticmethod
    @log_call
    def set_hydraulic_methods(geom_file: Union[str, Path],
                              river: str,
                              reach: str,
                              rs: str,
                              low_flow_method: Optional[str] = None,
                              high_flow_method: Optional[str] = None,
                              use_energy: Optional[bool] = None,
                              use_momentum: Optional[bool] = None,
                              use_yarnell: Optional[bool] = None,
                              use_wspro: Optional[bool] = None,
                              momentum_cd: Optional[float] = None,
                              yarnell_k: Optional[float] = None,
                              pressure_flow_submerged_inlet_cd: Optional[float] = None,
                              pressure_flow_submerged_inlet_outlet_cd: Optional[float] = None,
                              weir_coefficient: Optional[float] = None,
                              opening_index: int = 0,
                              create_backup: bool = True,
                              validate: bool = True) -> Dict[str, Any]:
        """
        Set bridge low-flow/high-flow hydraulic method selections.

        Accepted ``low_flow_method`` values are ``energy``, ``momentum``,
        ``yarnell``, and ``wspro``. Accepted ``high_flow_method`` values are
        ``energy`` and ``pressure_weir``. Momentum and Yarnell selections
        require an existing or supplied coefficient. Existing comma-field
        spacing is preserved for updated ``BR Coef=`` and deck/weir fields,
        and a ``.bak`` backup is created by default before writing.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)
            low_flow_method: Optional low-flow method selection
            high_flow_method: Optional high-flow method selection
            use_energy: Optional compute flag for the energy method
            use_momentum: Optional compute flag for the momentum method
            use_yarnell: Optional compute flag for the Yarnell method
            use_wspro: Optional compute flag for the WSPRO method
            momentum_cd: Optional momentum drag coefficient
            yarnell_k: Optional Yarnell pier coefficient
            pressure_flow_submerged_inlet_cd: Optional pressure-flow Cd
            pressure_flow_submerged_inlet_outlet_cd: Optional pressure-flow Cd
            weir_coefficient: Optional bridge deck/weir coefficient from the
                ``Deck Dist Width WeirC`` record
            opening_index: Zero-based bridge opening/coefficient record index
            create_backup: Create ``.bak`` backup before writing (default True)
            validate: Validate method names and unsupported combinations

        Returns:
            dict with before/after method dictionaries, changed line text, and
            backup path.

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If bridge, method value, or combination is invalid
            IOError: If file write fails

        Example:
            >>> GeomBridge.set_hydraulic_methods(
            ...     "model.g01", "Beaver Creek", "Kentwood", "5.4",
            ...     low_flow_method="yarnell",
            ...     high_flow_method="energy",
            ...     yarnell_k=1.05
            ... )
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        normalized_low = GeomBridge._normalize_hydraulic_method(
            low_flow_method,
            set(GeomBridge.LOW_FLOW_METHOD_CODES),
            'low_flow_method'
        )
        normalized_high = GeomBridge._normalize_hydraulic_method(
            high_flow_method,
            GeomBridge.HIGH_FLOW_METHODS,
            'high_flow_method'
        )

        if all(value is None for value in [
            normalized_low,
            normalized_high,
            use_energy,
            use_momentum,
            use_yarnell,
            use_wspro,
            momentum_cd,
            yarnell_k,
            pressure_flow_submerged_inlet_cd,
            pressure_flow_submerged_inlet_outlet_cd,
            weir_coefficient,
        ]):
            raise ValueError("At least one hydraulic method or coefficient must be specified")

        if validate and weir_coefficient is not None and float(weir_coefficient) <= 0:
            raise ValueError("weir_coefficient must be positive")

        backup_path = None
        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx = GeomBridge._find_bridge(lines, river, reach, rs)
            if bridge_idx is None:
                raise ValueError(f"Bridge not found: {river}/{reach}/RS {rs}")

            struct_end_idx = GeomBridge._find_structure_end(lines, bridge_idx)
            method_lines = GeomBridge._find_bridge_method_lines(
                lines, bridge_idx, struct_end_idx, opening_index
            )
            br_coef_idx = method_lines['br_coef_idx']
            wspro_idx = method_lines['wspro_idx']
            deck_idx = GeomBridge._find_bridge_deck_line(lines, bridge_idx, struct_end_idx)
            if weir_coefficient is not None and deck_idx is None:
                raise ValueError(
                    f"Deck Dist Width WeirC record not found for bridge {river}/{reach}/RS {rs}"
                )

            if br_coef_idx is None and method_lines['br_coef_count'] > 0:
                raise ValueError(
                    f"BR Coef= opening_index {opening_index} not found for "
                    f"{river}/{reach}/RS {rs}; found {method_lines['br_coef_count']}"
                )

            inserted_br_coef = False
            if br_coef_idx is None:
                line_ending = '\n'
                if bridge_idx < len(lines):
                    _, line_ending = GeomBridge._split_line_ending(lines[bridge_idx])
                    line_ending = line_ending or '\n'
                br_coef_fields = GeomBridge._default_br_coef_fields()
                insert_idx = GeomBridge._find_br_coef_insert_idx(lines, bridge_idx, struct_end_idx)
                lines.insert(
                    insert_idx,
                    GeomBridge._format_comma_line("BR Coef=", br_coef_fields, line_ending)
                )
                br_coef_idx = insert_idx
                inserted_br_coef = True
                if wspro_idx is not None and wspro_idx >= insert_idx:
                    wspro_idx += 1
            else:
                br_coef_fields = GeomBridge._split_comma_fields_from_line(
                    lines[br_coef_idx], "BR Coef="
                )

            before_line = lines[br_coef_idx].rstrip('\r\n')
            current = GeomBridge._parse_br_coef_fields(br_coef_fields)
            before = None if inserted_br_coef else GeomBridge.get_hydraulic_methods(
                geom_file, river, reach, rs, opening_index=opening_index
            )

            if validate and normalized_low == 'momentum':
                effective_momentum_cd = (
                    momentum_cd
                    if momentum_cd is not None
                    else current['coefficients']['momentum_cd']
                )
                if effective_momentum_cd is None:
                    raise ValueError(
                        "low_flow_method 'momentum' requires momentum_cd when no "
                        "existing momentum Cd is set"
                    )

            if validate and normalized_low == 'yarnell':
                effective_yarnell_k = (
                    yarnell_k
                    if yarnell_k is not None
                    else current['coefficients']['yarnell_k']
                )
                if effective_yarnell_k is None:
                    raise ValueError(
                        "low_flow_method 'yarnell' requires yarnell_k when no "
                        "existing Yarnell K is set"
                    )

            explicit_enabled = {
                'energy': use_energy,
                'momentum': use_momentum,
                'yarnell': use_yarnell,
                'wspro': use_wspro,
            }
            enabled = dict(current['enabled_low_flow_methods'])

            for method_name, flag_value in explicit_enabled.items():
                if flag_value is not None:
                    enabled[method_name] = bool(flag_value)

            if normalized_low is not None:
                if explicit_enabled.get(normalized_low) is False:
                    raise ValueError(
                        f"selected low_flow_method '{normalized_low}' cannot be disabled"
                    )
                enabled[normalized_low] = True

            method_to_validate = normalized_low or current['low_flow_method']
            require_selected_enabled = (
                normalized_low is not None or
                (method_to_validate is not None and explicit_enabled.get(method_to_validate) is False)
            )
            if validate:
                GeomBridge._validate_hydraulic_method_selection(
                    method_to_validate,
                    normalized_high,
                    enabled,
                    wspro_idx,
                    require_selected_enabled=require_selected_enabled,
                )

            flag_fields = {
                'energy': 0,
                'momentum': 1,
                'yarnell': 2,
                'wspro': 4,
            }
            for method_name, field_idx in flag_fields.items():
                if explicit_enabled.get(method_name) is not None or normalized_low == method_name:
                    existing = br_coef_fields[field_idx] if field_idx < len(br_coef_fields) else ''
                    GeomBridge._set_comma_field(
                        br_coef_fields,
                        field_idx,
                        GeomBridge._format_bool_field(bool(enabled[method_name]), existing)
                    )

            if normalized_low is not None:
                GeomBridge._set_comma_field(
                    br_coef_fields,
                    10,
                    GeomBridge.LOW_FLOW_METHOD_CODES[normalized_low]
                )

            if normalized_high is not None:
                high_standard_step = normalized_high == 'energy'
                existing = br_coef_fields[8] if len(br_coef_fields) > 8 else ''
                GeomBridge._set_comma_field(
                    br_coef_fields,
                    8,
                    GeomBridge._format_bool_field(high_standard_step, existing)
                )

            if momentum_cd is not None:
                GeomBridge._set_comma_field(br_coef_fields, 9, float(momentum_cd))

            if yarnell_k is not None:
                GeomBridge._set_comma_field(br_coef_fields, 3, float(yarnell_k))

            if pressure_flow_submerged_inlet_cd is not None:
                GeomBridge._set_comma_field(
                    br_coef_fields, 6, float(pressure_flow_submerged_inlet_cd)
                )

            if pressure_flow_submerged_inlet_outlet_cd is not None:
                GeomBridge._set_comma_field(
                    br_coef_fields, 7, float(pressure_flow_submerged_inlet_outlet_cd)
                )

            body, line_ending = GeomBridge._split_line_ending(lines[br_coef_idx])
            line_ending = line_ending or '\n'
            lines[br_coef_idx] = GeomBridge._format_comma_line(
                "BR Coef=", br_coef_fields, line_ending
            )
            after_line = lines[br_coef_idx].rstrip('\r\n')
            deck_line_before = None
            deck_line_after = None

            if weir_coefficient is not None and deck_idx is not None:
                deck_body, deck_line_ending = GeomBridge._split_line_ending(lines[deck_idx])
                deck_line_ending = deck_line_ending or '\n'
                deck_fields = deck_body.split(',')
                deck_line_before = lines[deck_idx].rstrip('\r\n')
                GeomBridge._set_comma_field(deck_fields, 2, float(weir_coefficient))
                lines[deck_idx] = f"{','.join(deck_fields)}{deck_line_ending}"
                deck_line_after = lines[deck_idx].rstrip('\r\n')

            if create_backup:
                backup_path = GeomParser.create_backup(geom_file)
                logger.info(f"Created backup: {backup_path}")

            with open(geom_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            after = GeomBridge.get_hydraulic_methods(
                geom_file, river, reach, rs, opening_index=opening_index
            )

            result = {
                'river': river,
                'reach': reach,
                'rs': str(rs),
                'opening_index': opening_index,
                'low_flow_method': after['low_flow_method'],
                'high_flow_method': after['high_flow_method'],
                'inserted_br_coef': inserted_br_coef,
                'br_coef_before': before_line,
                'br_coef_after': after_line,
                'deck_line_before': deck_line_before,
                'deck_line_after': deck_line_after,
                'backup_path': str(backup_path) if backup_path else None,
                'before': before,
                'after': after,
            }

            logger.info(
                f"Set bridge hydraulic methods for {river}/{reach}/RS {rs}: "
                f"low={result['low_flow_method']}, high={result['high_flow_method']}"
            )
            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge hydraulic methods: {str(e)}")
            if backup_path and backup_path.exists():
                logger.info(f"Restoring from backup: {backup_path}")
                import shutil
                shutil.copy2(backup_path, geom_file)
            raise IOError(f"Failed to write bridge hydraulic methods: {str(e)}")

    @staticmethod
    @log_call
    def get_htab(geom_file: Union[str, Path],
                river: str,
                reach: str,
                rs: str) -> pd.DataFrame:
        """
        Extract structure hydraulic table (HTab) parameters.

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
            ValueError: If structure not found

        Example:
            >>> htab = GeomBridge.get_htab("model.g08", "River", "Reach", "25548")
            >>> hw_max = htab[htab['Parameter'] == 'HWMax']['Value'].values[0]
            >>> print(f"HW Max: {hw_max}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            structure = GeomBridge._find_structure(lines, river, reach, rs)

            if structure is None:
                raise ValueError(f"Structure not found: {river}/{reach}/RS {rs}")

            structure_idx = structure['marker_idx']
            structure_end_idx = GeomBridge._find_structure_end(lines, structure_idx)

            htab_data = []

            for j in range(structure_idx, structure_end_idx):
                line = lines[j]

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

                elif line.startswith("BC User HTab Pts/SubCrv(D)="):
                    val = GeomParser.extract_keyword_value(line, "BC User HTab Pts/SubCrv(D)")
                    if val:
                        try:
                            htab_data.append({'Parameter': 'PointsPerSubmergedCurve', 'Value': int(val.strip())})
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

    @staticmethod
    @log_call
    def get_htab_dict(geom_file: Union[str, Path],
                      river: str,
                      reach: str,
                      rs: str,
                      include_invert: bool = True) -> Dict[str, Any]:
        """
        Extract structure hydraulic table (HTab) parameters as a dictionary.

        This method provides a more convenient dictionary interface compared to
        get_htab() which returns a DataFrame. It also optionally includes the
        structure invert elevation extracted from bridge deck geometry.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string)
            include_invert: If True, extract invert from deck geometry (default: True)

        Returns:
            dict with keys:
            - hw_max: Maximum headwater elevation (float or None)
            - tw_max: Maximum tailwater elevation (float or None)
            - max_flow: Maximum flow through structure (float or None)
            - use_user_curves: Flag for user curves (-1 = enabled, 0 = defaults, None if missing)
            - free_flow_points: Number of points on free flow curve (int or None)
            - submerged_curves: Number of submerged rating curves (int or None)
            - points_per_curve: Points per submerged curve (int or None)
            - invert: Minimum low chord elevation from deck (float or None, only if include_invert=True)
            - has_htab_lines: True if any BC HTab lines were found

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If structure not found

        Example:
            >>> htab = GeomBridge.get_htab_dict("model.g08", "River", "Reach", "25548")
            >>> print(f"HW Max: {htab['hw_max']}, Max Flow: {htab['max_flow']}")
            >>> if htab['invert']:
            ...     print(f"Invert: {htab['invert']}")

        Notes:
            - Returns None for missing parameters (doesn't raise errors)
            - The 'invert' key contains the minimum LowChord value from deck geometry
            - This can be used to calculate optimal HWMax with safety factors:
              optimal_hw_max = invert + (max_observed_depth * safety_factor)
        """
        geom_file = Path(geom_file)

        # Initialize result dictionary with None values
        result = {
            'hw_max': None,
            'tw_max': None,
            'max_flow': None,
            'use_user_curves': None,
            'free_flow_points': None,
            'submerged_curves': None,
            'points_per_curve': None,
            'invert': None,
            'has_htab_lines': False
        }

        # Get HTAB DataFrame from existing method
        htab_df = GeomBridge.get_htab(geom_file, river, reach, rs)

        # Map DataFrame parameters to dict keys
        param_mapping = {
            'HWMax': 'hw_max',
            'TWMax': 'tw_max',
            'MaxFlow': 'max_flow',
            'UseCurves': 'use_user_curves',
            'FreeFlowCurves': 'free_flow_points',
            'SubmergedCurves': 'submerged_curves',
            'PointsPerSubmergedCurve': 'points_per_curve'
        }

        # Convert DataFrame to dict
        if len(htab_df) > 0:
            result['has_htab_lines'] = True
            for _, row in htab_df.iterrows():
                param_name = row['Parameter']
                if param_name in param_mapping:
                    dict_key = param_mapping[param_name]
                    value = row['Value']
                    # Convert to appropriate type
                    if dict_key in ['hw_max', 'tw_max', 'max_flow']:
                        result[dict_key] = float(value) if value is not None else None
                    elif dict_key == 'use_user_curves':
                        result[dict_key] = int(value) if value is not None else None
                    else:
                        result[dict_key] = int(value) if value is not None else None

        # Optionally extract invert from deck geometry
        if include_invert:
            try:
                deck_df = GeomBridge.get_deck(geom_file, river, reach, rs)
                if len(deck_df) > 0 and 'LowChord' in deck_df.columns:
                    # Filter out placeholder values (often 0 or very low values)
                    # Real low chord values should be reasonable elevations
                    valid_lowchords = deck_df['LowChord'].dropna()
                    if len(valid_lowchords) > 0:
                        # Get minimum non-placeholder low chord
                        # Note: Some HEC-RAS files use 0 or very low values as placeholders
                        min_lowchord = valid_lowchords.min()
                        # Also get max to help identify real vs placeholder values
                        max_lowchord = valid_lowchords.max()
                        # If all values are 0 or very small, it might be placeholder data
                        if max_lowchord > 0:
                            result['invert'] = float(min_lowchord)
            except Exception as e:
                # If deck extraction fails, just leave invert as None
                logger.debug(f"Could not extract invert from deck geometry: {e}")

        logger.info(f"Extracted HTab dict for {river}/{reach}/RS {rs}: "
                   f"hw_max={result['hw_max']}, max_flow={result['max_flow']}, "
                   f"invert={result['invert']}")

        return result

    @staticmethod
    def _find_structure_end(lines: List[str], struct_start_idx: int) -> int:
        """
        Find the end of a structure block (before the next structure or XS).

        Parameters:
            lines: List of file lines
            struct_start_idx: Index where structure (Bridge Culvert-) starts

        Returns:
            int: Index of first line AFTER the structure block
        """
        # Search to the next geometry section. Large bridge blocks can contain
        # many pier/abutment records, so do not impose a fixed line-count limit.
        for i in range(struct_start_idx + 1, len(lines)):
            line = lines[i]
            # These markers indicate start of next element
            if (line.startswith("Type RM Length L Ch R =") or
                line.startswith("River Reach=") or
                line.startswith("Reach XS=")):
                return i
        # If not found, return end of file
        return len(lines)

    @staticmethod
    def _find_htab_lines_range(lines: List[str], struct_start_idx: int, struct_end_idx: int) -> tuple:
        """
        Find range of existing HTAB lines within a structure block.

        Parameters:
            lines: List of file lines
            struct_start_idx: Index where structure starts
            struct_end_idx: Index where structure ends (exclusive)

        Returns:
            tuple: (first_htab_idx, last_htab_idx) or (None, None) if no HTAB lines exist
        """
        first_htab_idx = None
        last_htab_idx = None

        htab_prefixes = [
            "BC HTab HWMax=",
            "BC HTab TWMax=",
            "BC HTab MaxFlow=",
            "BC Use User HTab Curves=",
            "BC User HTab FreeFlow(D)=",
            "BC User HTab Sub Curve(D)=",
            "BC User HTab Pts/SubCrv(D)="
        ]

        for i in range(struct_start_idx, struct_end_idx):
            line = lines[i]
            for prefix in htab_prefixes:
                if line.startswith(prefix):
                    if first_htab_idx is None:
                        first_htab_idx = i
                    last_htab_idx = i
                    break

        return (first_htab_idx, last_htab_idx)

    @staticmethod
    def _format_htab_lines(hw_max: float = None,
                           tw_max: float = None,
                           max_flow: float = None,
                           use_user_curves: int = -1,
                           free_flow_points: int = None,
                           submerged_curves: int = None,
                           points_per_curve: int = None) -> List[str]:
        """
        Format HTAB parameter lines for writing to geometry file.

        Parameters:
            hw_max: Maximum headwater elevation
            tw_max: Maximum tailwater elevation (optional)
            max_flow: Maximum flow through structure
            use_user_curves: Flag (-1 = use user settings, 0 = defaults)
            free_flow_points: Number of points on free flow curve
            submerged_curves: Number of submerged rating curves
            points_per_curve: Points per submerged curve

        Returns:
            List[str]: Formatted HTAB lines with newlines
        """
        htab_lines = []

        # Format elevation/flow values with fixed format per spec
        if hw_max is not None:
            htab_lines.append(f"BC HTab HWMax=  {hw_max:.1f}\n")
        if tw_max is not None:
            htab_lines.append(f"BC HTab TWMax=  {tw_max:.1f}\n")
        if max_flow is not None:
            htab_lines.append(f"BC HTab MaxFlow= {max_flow:.1f}\n")

        # Use user curves flag (always write if any curve params specified)
        if (use_user_curves is not None or
            free_flow_points is not None or
            submerged_curves is not None or
            points_per_curve is not None):
            flag = use_user_curves if use_user_curves is not None else -1
            htab_lines.append(f"BC Use User HTab Curves= {flag}\n")

        # Curve point counts
        if free_flow_points is not None:
            htab_lines.append(f"BC User HTab FreeFlow(D)= {free_flow_points}\n")
        if submerged_curves is not None:
            htab_lines.append(f"BC User HTab Sub Curve(D)= {submerged_curves}\n")
        if points_per_curve is not None:
            htab_lines.append(f"BC User HTab Pts/SubCrv(D)= {points_per_curve}\n")

        return htab_lines

    @staticmethod
    def _format_deck_block_lines(deck_df: pd.DataFrame,
                                 distance: float,
                                 width: float,
                                 weir_coefficient: float = 2.6,
                                 skew: float = 0.0,
                                 min_low_chord: Optional[float] = None,
                                 max_high_chord: Optional[float] = None,
                                 max_submergence: float = 0.95,
                                 is_ogee: int = 0,
                                 extra_parameters: Optional[List[Any]] = None) -> List[str]:
        """Format a complete Deck Dist Width WeirC block."""
        required = {'Location', 'Station', 'Elevation', 'LowChord'}
        if not required.issubset(deck_df.columns):
            raise ValueError("deck_df must contain Location, Station, Elevation, and LowChord columns")

        upstream = deck_df[deck_df['Location'].astype(str).str.lower().isin(['upstream', 'up', 'u'])]
        downstream = deck_df[deck_df['Location'].astype(str).str.lower().isin(['downstream', 'down', 'dn', 'd'])]

        if upstream.empty and downstream.empty:
            raise ValueError("deck_df must contain at least one upstream or downstream deck row")

        extras = extra_parameters if extra_parameters is not None else [0, 0, "", ""]
        params = [
            distance,
            width,
            weir_coefficient,
            skew,
            len(upstream),
            len(downstream),
            min_low_chord,
            max_high_chord,
            max_submergence,
            is_ogee,
            *extras
        ]

        block_lines = [
            "Deck Dist Width WeirC Skew NumUp NumDn MinLoCord MaxHiCord MaxSubmerge Is_Ogee\n",
            f"{','.join(GeomBridge._format_csv_value(value) for value in params)}\n",
        ]

        for face_df in (upstream, downstream):
            if face_df.empty:
                continue
            for column in ('Station', 'Elevation', 'LowChord'):
                block_lines.extend(
                    GeomBridge._format_fixed_width_values(face_df[column].tolist(), precision=2)
                )

        return block_lines

    @staticmethod
    @log_call
    def set_deck(geom_file: Union[str, Path],
                 river: str,
                 reach: str,
                 rs: str,
                 deck_df: pd.DataFrame,
                 distance: Optional[float] = None,
                 width: Optional[float] = None,
                 weir_coefficient: Optional[float] = None,
                 skew: Optional[float] = None,
                 min_low_chord: Optional[float] = None,
                 max_high_chord: Optional[float] = None,
                 max_submergence: Optional[float] = None,
                 is_ogee: Optional[int] = None,
                 bridge_flags: Optional[List[Any]] = None,
                 extra_parameters: Optional[List[Any]] = None,
                 create_backup: bool = True) -> Optional[Path]:
        """
        Create or replace bridge deck/roadway high chord and low chord geometry.

        If the bridge marker is missing but the river/reach/station exists, this
        method creates the ``Bridge Culvert-`` block at that station before
        writing the deck block.
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")
        if not isinstance(deck_df, pd.DataFrame):
            raise ValueError("deck_df must be a pandas DataFrame")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            lines, bridge_idx, _ = GeomBridge._ensure_bridge_block(
                lines, river, reach, str(rs), bridge_flags=bridge_flags
            )
            bridge_end_idx = GeomBridge._find_structure_end(lines, bridge_idx)
            deck_start, deck_end = GeomBridge._find_deck_block_range(lines, bridge_idx, bridge_end_idx)

            existing_parts = []
            if deck_start is not None and deck_start + 1 < bridge_end_idx:
                existing_parts = GeomBridge._parse_csv_values(lines[deck_start + 1])

            def existing_float(index: int, default: Optional[float] = None) -> Optional[float]:
                if len(existing_parts) <= index:
                    return default
                parsed = GeomBridge._parse_optional_float(existing_parts[index])
                return parsed if parsed is not None else default

            def existing_int(index: int, default: Optional[int] = None) -> Optional[int]:
                if len(existing_parts) <= index:
                    return default
                parsed = GeomBridge._parse_optional_int(existing_parts[index])
                return parsed if parsed is not None else default

            resolved_distance = distance if distance is not None else existing_float(0)
            resolved_width = width if width is not None else existing_float(1)
            if resolved_distance is None:
                raise ValueError("distance is required when creating a new deck block")
            if resolved_width is None:
                raise ValueError("width is required when creating a new deck block")

            if deck_start is None and min_low_chord is None and 'LowChord' in deck_df.columns:
                min_low_chord = float(deck_df['LowChord'].min())

            new_deck_lines = GeomBridge._format_deck_block_lines(
                deck_df=deck_df,
                distance=resolved_distance,
                width=resolved_width,
                weir_coefficient=weir_coefficient if weir_coefficient is not None else existing_float(2, 2.6),
                skew=skew if skew is not None else existing_float(3, 0.0),
                min_low_chord=min_low_chord if min_low_chord is not None else existing_float(6),
                max_high_chord=max_high_chord if max_high_chord is not None else existing_float(7),
                max_submergence=max_submergence if max_submergence is not None else existing_float(8, 0.95),
                is_ogee=is_ogee if is_ogee is not None else existing_int(9, 0),
                extra_parameters=extra_parameters if extra_parameters is not None else existing_parts[10:] if len(existing_parts) > 10 else None,
            )

            if deck_start is not None:
                lines[deck_start:deck_end] = new_deck_lines
            else:
                insert_idx = GeomBridge._insert_index_for_bridge_section(
                    lines, bridge_idx, bridge_end_idx, 'deck'
                )
                lines[insert_idx:insert_idx] = new_deck_lines

            return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge deck: {str(e)}")
            raise IOError(f"Failed to write bridge deck: {str(e)}")

    @staticmethod
    def _normalize_pier_records(piers: Union[pd.DataFrame, List[Dict[str, Any]], None]) -> List[Dict[str, Any]]:
        """Normalize pier setter input into records with list-valued vectors."""
        if piers is None:
            return []
        if isinstance(piers, pd.DataFrame):
            df = piers.copy()
        elif isinstance(piers, (list, tuple)):
            df = pd.DataFrame(piers)
        else:
            raise ValueError("piers must be a pandas DataFrame, list of dicts, or None")

        if df.empty:
            return []

        records = []
        for _, row in df.iterrows():
            up_widths = GeomBridge._listify(row.get('UpstreamWidths'))
            up_elevs = GeomBridge._listify(row.get('UpstreamElevations'))
            dn_widths = GeomBridge._listify(row.get('DownstreamWidths'))
            dn_elevs = GeomBridge._listify(row.get('DownstreamElevations'))

            if len(up_widths) != len(up_elevs):
                raise ValueError("UpstreamWidths and UpstreamElevations must have the same length")
            if len(dn_widths) != len(dn_elevs):
                raise ValueError("DownstreamWidths and DownstreamElevations must have the same length")
            if up_widths and GeomBridge._is_missing(row.get('UpstreamStation')):
                raise ValueError("UpstreamStation is required for upstream pier points")
            if dn_widths and GeomBridge._is_missing(row.get('DownstreamStation')):
                raise ValueError("DownstreamStation is required for downstream pier points")

            records.append({
                'Skew': row.get('Skew'),
                'UpstreamStation': row.get('UpstreamStation'),
                'DownstreamStation': row.get('DownstreamStation'),
                'UpstreamWidths': up_widths,
                'UpstreamElevations': up_elevs,
                'DownstreamWidths': dn_widths,
                'DownstreamElevations': dn_elevs,
                'ExtraParameters': GeomBridge._listify(row.get('ExtraParameters')) or [0, 0, 0, "", ""],
            })

        return records

    @staticmethod
    def _format_pier_block_lines(pier_records: List[Dict[str, Any]]) -> List[str]:
        """Format pier records as HEC-RAS bridge pier blocks."""
        block_lines = []
        for record in pier_records:
            up_widths = record['UpstreamWidths']
            up_elevs = record['UpstreamElevations']
            dn_widths = record['DownstreamWidths']
            dn_elevs = record['DownstreamElevations']
            header_values = [
                record.get('Skew'),
                record.get('UpstreamStation'),
                len(up_widths),
                record.get('DownstreamStation'),
                len(dn_widths),
                *record.get('ExtraParameters', [0, 0, 0, "", ""]),
            ]
            block_lines.append(GeomBridge._format_csv_line(
                "Pier Skew, UpSta & Num, DnSta & Num", header_values
            ))

            for values in (up_widths, up_elevs, dn_widths, dn_elevs):
                if values:
                    block_lines.extend(GeomBridge._format_fixed_width_values(values, precision=2))

        return block_lines

    @staticmethod
    @log_call
    def set_piers(geom_file: Union[str, Path],
                  river: str,
                  reach: str,
                  rs: str,
                  piers: Union[pd.DataFrame, List[Dict[str, Any]], None],
                  create_backup: bool = True) -> Optional[Path]:
        """Create, replace, or remove bridge pier blocks."""
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            pier_records = GeomBridge._normalize_pier_records(piers)
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx, bridge_end_idx = GeomBridge._get_bridge_range(lines, river, reach, str(rs))
            ranges = GeomBridge._find_pier_block_ranges(lines, bridge_idx, bridge_end_idx)
            lines = GeomBridge._remove_ranges(lines, ranges)

            bridge_idx, bridge_end_idx = GeomBridge._get_bridge_range(lines, river, reach, str(rs))
            new_lines = GeomBridge._format_pier_block_lines(pier_records)
            if new_lines:
                insert_idx = GeomBridge._insert_index_for_bridge_section(
                    lines, bridge_idx, bridge_end_idx, 'piers'
                )
                lines[insert_idx:insert_idx] = new_lines

            return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge piers: {str(e)}")
            raise IOError(f"Failed to write bridge piers: {str(e)}")

    @staticmethod
    def _normalize_abutment_records(abutments: Union[pd.DataFrame, List[Dict[str, Any]], None]) -> List[Dict[str, Any]]:
        """Normalize abutment setter input into one record per abutment block."""
        if abutments is None:
            return []
        if isinstance(abutments, pd.DataFrame):
            df = abutments.copy()
        elif isinstance(abutments, (list, tuple)):
            df = pd.DataFrame(abutments)
        else:
            raise ValueError("abutments must be a pandas DataFrame, list of dicts, or None")

        if df.empty:
            return []

        if {'Location', 'Station', 'Parameter'}.issubset(df.columns):
            if 'AbutmentIndex' not in df.columns:
                df['AbutmentIndex'] = 1
            records = []
            for _, group in df.groupby('AbutmentIndex', sort=True):
                upstream = group[group['Location'].astype(str).str.lower().isin(['upstream', 'up', 'u'])]
                downstream = group[group['Location'].astype(str).str.lower().isin(['downstream', 'down', 'dn', 'd'])]
                records.append({
                    'Skew': group['Skew'].dropna().iloc[0] if 'Skew' in group.columns and not group['Skew'].dropna().empty else None,
                    'UpstreamStations': upstream['Station'].tolist(),
                    'UpstreamParameters': upstream['Parameter'].tolist(),
                    'DownstreamStations': downstream['Station'].tolist(),
                    'DownstreamParameters': downstream['Parameter'].tolist(),
                })
            return records

        records = []
        for _, row in df.iterrows():
            up_stations = GeomBridge._listify(row.get('UpstreamStations'))
            up_params = GeomBridge._listify(row.get('UpstreamParameters'))
            dn_stations = GeomBridge._listify(row.get('DownstreamStations'))
            dn_params = GeomBridge._listify(row.get('DownstreamParameters'))

            if len(up_stations) != len(up_params):
                raise ValueError("UpstreamStations and UpstreamParameters must have the same length")
            if len(dn_stations) != len(dn_params):
                raise ValueError("DownstreamStations and DownstreamParameters must have the same length")

            records.append({
                'Skew': row.get('Skew'),
                'UpstreamStations': up_stations,
                'UpstreamParameters': up_params,
                'DownstreamStations': dn_stations,
                'DownstreamParameters': dn_params,
            })

        return records

    @staticmethod
    def _format_abutment_block_lines(abutment_records: List[Dict[str, Any]]) -> List[str]:
        """Format abutment records as HEC-RAS abutment blocks."""
        block_lines = []
        for record in abutment_records:
            up_stations = record['UpstreamStations']
            up_params = record['UpstreamParameters']
            dn_stations = record['DownstreamStations']
            dn_params = record['DownstreamParameters']
            block_lines.append(GeomBridge._format_csv_line(
                "Abutment Skew #Up #Dn",
                [record.get('Skew'), len(up_stations), len(dn_stations)]
            ))

            for values in (up_stations, up_params, dn_stations, dn_params):
                if values:
                    block_lines.extend(GeomBridge._format_fixed_width_values(values, precision=2))

        return block_lines

    @staticmethod
    @log_call
    def set_abutments(geom_file: Union[str, Path],
                      river: str,
                      reach: str,
                      rs: str,
                      abutments: Union[pd.DataFrame, List[Dict[str, Any]], None],
                      create_backup: bool = True) -> Optional[Path]:
        """Create, replace, or remove bridge abutment blocks."""
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            abutment_records = GeomBridge._normalize_abutment_records(abutments)
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx, bridge_end_idx = GeomBridge._get_bridge_range(lines, river, reach, str(rs))
            ranges = GeomBridge._find_abutment_block_ranges(lines, bridge_idx, bridge_end_idx)
            lines = GeomBridge._remove_ranges(lines, ranges)

            bridge_idx, bridge_end_idx = GeomBridge._get_bridge_range(lines, river, reach, str(rs))
            new_lines = GeomBridge._format_abutment_block_lines(abutment_records)
            if new_lines:
                insert_idx = GeomBridge._insert_index_for_bridge_section(
                    lines, bridge_idx, bridge_end_idx, 'abutments'
                )
                lines[insert_idx:insert_idx] = new_lines

            return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge abutments: {str(e)}")
            raise IOError(f"Failed to write bridge abutments: {str(e)}")

    @staticmethod
    def _format_approach_section_lines(approach_df: Optional[pd.DataFrame],
                                       upstream_banks: Optional[List[float]] = None,
                                       downstream_banks: Optional[List[float]] = None) -> List[str]:
        """Format embedded BR U/BR D approach section lines."""
        block_lines = []
        if approach_df is None:
            approach_df = pd.DataFrame()
        if not isinstance(approach_df, pd.DataFrame):
            raise ValueError("approach_df must be a pandas DataFrame or None")

        for location, prefix, banks in (
            ('upstream', 'BR U', upstream_banks),
            ('downstream', 'BR D', downstream_banks),
        ):
            loc_df = approach_df[
                approach_df.get('Location', pd.Series(dtype=object)).astype(str).str.lower().isin(
                    [location, location[:2], location[0]]
                )
            ] if not approach_df.empty and 'Location' in approach_df.columns else pd.DataFrame()

            if not loc_df.empty:
                se_df = loc_df[
                    loc_df.get('DataType', pd.Series(dtype=object)).astype(str).str.lower().eq('station_elevation')
                ] if 'DataType' in loc_df.columns else loc_df
                if not se_df.empty:
                    if not {'Station', 'Elevation'}.issubset(se_df.columns):
                        raise ValueError("station_elevation approach rows require Station and Elevation columns")
                    values = []
                    for _, row in se_df.iterrows():
                        values.extend([row['Station'], row['Elevation']])
                    block_lines.append(f"{prefix} #Sta/Elev= {len(se_df)}\n")
                    block_lines.extend(GeomBridge._format_fixed_width_values(values, precision=2))

                bank_df = loc_df[
                    loc_df.get('DataType', pd.Series(dtype=object)).astype(str).str.lower().eq('banks')
                ] if 'DataType' in loc_df.columns else pd.DataFrame()
                if banks is None and not bank_df.empty:
                    first = bank_df.iloc[0]
                    if 'LeftBank' in bank_df.columns and 'RightBank' in bank_df.columns:
                        banks = [first['LeftBank'], first['RightBank']]

            if banks is not None:
                if len(banks) != 2:
                    raise ValueError("Approach banks must contain [left_bank, right_bank]")
                block_lines.append(GeomBridge._format_csv_line(f"{prefix} Banks", list(banks)))

        return block_lines

    @staticmethod
    @log_call
    def set_approach_sections(geom_file: Union[str, Path],
                              river: str,
                              reach: str,
                              rs: str,
                              approach_df: Optional[pd.DataFrame] = None,
                              upstream_banks: Optional[List[float]] = None,
                              downstream_banks: Optional[List[float]] = None,
                              create_backup: bool = True) -> Optional[Path]:
        """Create, replace, or remove embedded BR U/BR D approach section blocks."""
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            new_lines = GeomBridge._format_approach_section_lines(
                approach_df,
                upstream_banks=upstream_banks,
                downstream_banks=downstream_banks,
            )
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx, bridge_end_idx = GeomBridge._get_bridge_range(lines, river, reach, str(rs))
            ranges = GeomBridge._find_approach_block_ranges(lines, bridge_idx, bridge_end_idx)
            lines = GeomBridge._remove_ranges(lines, ranges)

            bridge_idx, bridge_end_idx = GeomBridge._get_bridge_range(lines, river, reach, str(rs))
            if new_lines:
                insert_idx = GeomBridge._insert_index_for_bridge_section(
                    lines, bridge_idx, bridge_end_idx, 'approach'
                )
                lines[insert_idx:insert_idx] = new_lines

            return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge approach sections: {str(e)}")
            raise IOError(f"Failed to write bridge approach sections: {str(e)}")

    @staticmethod
    def _prepare_coefficient_values(existing: Optional[List[Any]], provided: Any) -> Optional[List[Any]]:
        """Prepare a full coefficient vector from full or sparse user input."""
        if provided is None:
            return existing

        if isinstance(provided, pd.DataFrame):
            if not {'Index', 'Value'}.issubset(provided.columns):
                raise ValueError("Coefficient DataFrame input requires Index and Value columns")
            provided = dict(zip(provided['Index'], provided['Value']))

        if isinstance(provided, dict):
            values = list(existing or [])
            if provided:
                max_idx = max(int(idx) for idx in provided)
                while len(values) <= max_idx:
                    values.append("")
                for idx, value in provided.items():
                    values[int(idx)] = value
            return values

        if isinstance(provided, (list, tuple, np.ndarray, pd.Series)):
            values = list(provided)
            return values if values else None

        return [provided]

    @staticmethod
    @log_call
    def set_coefficients(geom_file: Union[str, Path],
                         river: str,
                         reach: str,
                         rs: str,
                         br_coef: Any = None,
                         wspro: Any = None,
                         bc_design: Any = None,
                         create_backup: bool = True) -> Optional[Path]:
        """
        Create or replace bridge coefficient lines.

        ``br_coef``, ``wspro``, and ``bc_design`` accept full lists or sparse
        ``{index: value}`` dictionaries. Sparse updates are merged into the
        existing line before writing.
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")
        if br_coef is None and wspro is None and bc_design is None:
            raise ValueError("At least one of br_coef, wspro, or bc_design must be provided")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx, bridge_end_idx = GeomBridge._get_bridge_range(lines, river, reach, str(rs))
            existing = {'br_coef': None, 'wspro': None, 'bc_design': None}
            coefficient_ranges = []

            for idx in range(bridge_idx, bridge_end_idx):
                if lines[idx].startswith("BR Coef="):
                    existing['br_coef'] = GeomBridge._parse_csv_values(lines[idx])
                    coefficient_ranges.append((idx, idx + 1))
                elif lines[idx].startswith("WSPro="):
                    existing['wspro'] = GeomBridge._parse_csv_values(lines[idx])
                    coefficient_ranges.append((idx, idx + 1))
                elif lines[idx].startswith("BC Design="):
                    existing['bc_design'] = GeomBridge._parse_csv_values(lines[idx])
                    coefficient_ranges.append((idx, idx + 1))

            final_values = {
                'BR Coef': GeomBridge._prepare_coefficient_values(existing['br_coef'], br_coef),
                'WSPro': GeomBridge._prepare_coefficient_values(existing['wspro'], wspro),
                'BC Design': GeomBridge._prepare_coefficient_values(existing['bc_design'], bc_design),
            }

            lines = GeomBridge._remove_ranges(lines, coefficient_ranges)
            bridge_idx, bridge_end_idx = GeomBridge._get_bridge_range(lines, river, reach, str(rs))

            new_lines = [
                GeomBridge._format_csv_line(keyword, values)
                for keyword, values in final_values.items()
                if values is not None
            ]

            if new_lines:
                insert_idx = GeomBridge._insert_index_for_bridge_section(
                    lines, bridge_idx, bridge_end_idx, 'coefficients'
                )
                lines[insert_idx:insert_idx] = new_lines

            return GeomParser.safe_write_geometry(geom_file, lines, create_backup=create_backup)

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing bridge coefficients: {str(e)}")
            raise IOError(f"Failed to write bridge coefficients: {str(e)}")

    @staticmethod
    @log_call
    def set_htab(geom_file: Union[str, Path],
                 river: str,
                 reach: str,
                 rs: str,
                 hw_max: Optional[float] = None,
                 tw_max: Optional[float] = None,
                 max_flow: Optional[float] = None,
                 use_user_curves: int = -1,
                 free_flow_points: Optional[int] = None,
                 submerged_curves: Optional[int] = None,
                 points_per_curve: Optional[int] = None,
                 validate: bool = True) -> Dict[str, Any]:
        """
        Set structure HTAB parameters in geometry file.

        Modifies the geometry file in-place, inserting or replacing HTAB parameter
        lines for a bridge, culvert, or inline weir structure. Creates a .bak backup
        automatically before modification.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station of structure (as string)
            hw_max: Maximum headwater elevation
            tw_max: Maximum tailwater elevation (optional)
            max_flow: Maximum flow through structure
            use_user_curves: -1 to enable custom settings, 0 for defaults
            free_flow_points: Number of points on free flow curve (optimal 100)
            submerged_curves: Number of submerged rating curves (optimal 60)
            points_per_curve: Points per submerged curve (optimal 50)
            validate: If True, validate parameters before writing (default: True)

        Returns:
            dict: Parameters that were written, with keys:
                - 'hw_max', 'tw_max', 'max_flow': Elevation/flow values (or None)
                - 'use_user_curves', 'free_flow_points', etc.: Curve settings
                - 'lines_replaced': Number of existing HTAB lines replaced
                - 'lines_inserted': Number of new HTAB lines inserted
                - 'backup_path': Path to backup file

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If structure not found or validation fails
            IOError: If file write fails

        Notes:
            - Only specified (non-None) parameters are written
            - If HTAB lines don't exist, they are inserted after structure geometry
            - If HTAB lines exist, they are replaced entirely
            - Works for bridges, culverts, inline weirs (all use same HTAB format)
            - Automatically creates .bak backup before modification
            - If write fails, attempts to restore from backup

        Example:
            >>> GeomBridge.set_htab(
            ...     "model.g01", "River", "Reach", "5280",
            ...     hw_max=620.0, max_flow=75000.0,
            ...     free_flow_points=100, submerged_curves=60,
            ...     points_per_curve=50
            ... )

        See Also:
            - get_htab(): Read structure HTAB parameters as DataFrame
            - get_htab_dict(): Read structure HTAB parameters as dict
            - GeomHtabUtils.calculate_optimal_structure_htab(): Calculate optimal values
            - GeomHtabUtils.validate_structure_htab_params(): Validate parameters
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Check that at least one parameter is specified
        if all(p is None for p in [hw_max, tw_max, max_flow, free_flow_points,
                                    submerged_curves, points_per_curve]):
            raise ValueError(
                "At least one HTAB parameter must be specified. "
                "Provide hw_max, tw_max, max_flow, or curve point counts."
            )

        # Validate parameters if requested
        if validate:
            # Get current HTAB to use as expected values for validation
            current_htab = GeomBridge.get_htab_dict(geom_file, river, reach, rs)

            # Build params dict for validation
            params_to_validate = {
                'hw_max': hw_max,
                'max_flow': max_flow,
                'free_flow_points': free_flow_points,
                'submerged_curves': submerged_curves,
                'points_per_curve': points_per_curve
            }

            # Only validate if we have expected values
            if current_htab.get('invert') is not None:
                from .GeomHtabUtils import GeomHtabUtils

                # Use current or provided values for validation
                expected_hw = hw_max if hw_max is not None else (current_htab.get('hw_max') or 0)
                expected_flow = max_flow if max_flow is not None else (current_htab.get('max_flow') or 0)

                if expected_hw > 0 or expected_flow > 0:
                    errors, warnings = GeomHtabUtils.validate_structure_htab_params(
                        params_to_validate,
                        struct_invert=current_htab['invert'],
                        max_expected_hw=expected_hw,
                        max_expected_flow=expected_flow
                    )

                    if errors:
                        error_msg = "; ".join(errors)
                        raise ValueError(f"HTAB parameter validation failed: {error_msg}")

                    if warnings:
                        for warning in warnings:
                            logger.warning(f"HTAB validation warning: {warning}")

        backup_path = None
        try:
            # Create backup
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

            # Read file
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find structure
            structure = GeomBridge._find_structure(lines, river, reach, rs)
            if structure is None:
                raise ValueError(f"Structure not found: {river}/{reach}/RS {rs}")
            struct_idx = structure['marker_idx']

            # Find structure end
            struct_end_idx = GeomBridge._find_structure_end(lines, struct_idx)

            # Find existing HTAB lines
            first_htab, last_htab = GeomBridge._find_htab_lines_range(lines, struct_idx, struct_end_idx)

            # Format new HTAB lines
            new_htab_lines = GeomBridge._format_htab_lines(
                hw_max=hw_max,
                tw_max=tw_max,
                max_flow=max_flow,
                use_user_curves=use_user_curves,
                free_flow_points=free_flow_points,
                submerged_curves=submerged_curves,
                points_per_curve=points_per_curve
            )

            lines_replaced = 0
            lines_inserted = 0

            if first_htab is not None:
                # Replace existing HTAB lines
                lines_replaced = last_htab - first_htab + 1
                lines = lines[:first_htab] + new_htab_lines + lines[last_htab + 1:]
                lines_inserted = len(new_htab_lines)
                logger.info(
                    f"Replaced {lines_replaced} existing HTAB lines with {lines_inserted} new lines"
                )
            else:
                # Insert new HTAB lines before structure end
                # Find good insertion point (after structure data, before next element)
                insert_idx = struct_end_idx
                lines = lines[:insert_idx] + new_htab_lines + lines[insert_idx:]
                lines_inserted = len(new_htab_lines)
                logger.info(f"Inserted {lines_inserted} new HTAB lines at line {insert_idx}")

            # Write modified file
            with open(geom_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            logger.info(f"Successfully wrote HTAB parameters for {river}/{reach}/RS {rs}")

            # Return summary of what was written
            result = {
                'hw_max': hw_max,
                'tw_max': tw_max,
                'max_flow': max_flow,
                'use_user_curves': use_user_curves if any([
                    free_flow_points, submerged_curves, points_per_curve
                ]) else None,
                'free_flow_points': free_flow_points,
                'submerged_curves': submerged_curves,
                'points_per_curve': points_per_curve,
                'lines_replaced': lines_replaced,
                'lines_inserted': lines_inserted,
                'backup_path': str(backup_path)
            }

            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing HTAB parameters: {str(e)}")
            # Attempt to restore from backup if write failed
            if backup_path and backup_path.exists():
                logger.info(f"Restoring from backup: {backup_path}")
                import shutil
                shutil.copy2(backup_path, geom_file)
            raise IOError(f"Failed to write HTAB parameters: {str(e)}")

    @staticmethod
    def _find_all_structures(lines: List[str]) -> List[Dict[str, Any]]:
        """
        Find all bridge/culvert structures and inline weirs in geometry file.

        Parameters:
            lines: List of file lines

        Returns:
            List of dicts with keys:
                - 'type': 'bridge' or 'inline_weir'
                - 'river': River name
                - 'reach': Reach name
                - 'rs': River station
                - 'start_idx': Line index where structure block starts
                - 'marker_idx': Line index of Bridge Culvert- or IW Pilot Flow= marker
        """
        structures = []
        current_river = None
        current_reach = None
        last_rs = None
        last_type_idx = None

        for i, line in enumerate(lines):
            # Track current river/reach
            if line.startswith("River Reach="):
                values = GeomParser.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]

            # Track RS and structure type
            elif line.startswith("Type RM Length L Ch R ="):
                value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
                values = [v.strip() for v in value_str.split(',')]
                if len(values) > 1:
                    last_rs = values[1]
                    last_type_idx = i

            # Found bridge/culvert structure
            elif line.startswith("Bridge Culvert-"):
                if current_river and current_reach and last_rs:
                    structures.append({
                        'type': 'bridge',
                        'river': current_river,
                        'reach': current_reach,
                        'rs': last_rs,
                        'start_idx': last_type_idx,
                        'marker_idx': i
                    })
                    logger.debug(
                        f"Found bridge/culvert: {current_river}/{current_reach}/RS {last_rs} at line {i}"
                    )

            # Found inline weir
            elif line.startswith("IW Pilot Flow="):
                if current_river and current_reach and last_rs:
                    structures.append({
                        'type': 'inline_weir',
                        'river': current_river,
                        'reach': current_reach,
                        'rs': last_rs,
                        'start_idx': last_type_idx,
                        'marker_idx': i
                    })
                    logger.debug(
                        f"Found inline weir: {current_river}/{current_reach}/RS {last_rs} at line {i}"
                    )

        return structures

    @staticmethod
    def _get_existing_htab_values(lines: List[str], struct_start_idx: int, struct_end_idx: int) -> Dict[str, Any]:
        """
        Extract existing HTAB values from a structure block.

        Parameters:
            lines: File lines
            struct_start_idx: Index where structure starts
            struct_end_idx: Index where structure ends (exclusive)

        Returns:
            dict with existing values: hw_max, tw_max, max_flow (may be None if not present)
        """
        existing = {
            'hw_max': None,
            'tw_max': None,
            'max_flow': None
        }

        for i in range(struct_start_idx, struct_end_idx):
            line = lines[i]

            if line.startswith("BC HTab HWMax="):
                val = GeomParser.extract_keyword_value(line, "BC HTab HWMax")
                if val:
                    try:
                        existing['hw_max'] = float(val)
                    except ValueError:
                        pass

            elif line.startswith("BC HTab TWMax="):
                val = GeomParser.extract_keyword_value(line, "BC HTab TWMax")
                if val:
                    try:
                        existing['tw_max'] = float(val)
                    except ValueError:
                        pass

            elif line.startswith("BC HTab MaxFlow="):
                val = GeomParser.extract_keyword_value(line, "BC HTab MaxFlow")
                if val:
                    try:
                        existing['max_flow'] = float(val)
                    except ValueError:
                        pass

        return existing

    @staticmethod
    @log_call
    def set_all_structures_htab(geom_file: Union[str, Path],
                                 hw_max_multiplier: Optional[float] = None,
                                 max_flow_multiplier: Optional[float] = None,
                                 free_flow_points: int = 100,
                                 submerged_curves: int = 60,
                                 points_per_curve: int = 50,
                                 create_backup: bool = True) -> Dict[str, Any]:
        """
        Set HTAB parameters for ALL structures (bridges, culverts, inline weirs) in geometry file.

        This method processes all hydraulic structures in a single file read/write cycle
        for efficiency. It can apply multipliers to existing HWMax/MaxFlow values and
        always sets curve point counts to the specified values for optimal resolution.

        Parameters:
            geom_file: Path to geometry file (.g##)
            hw_max_multiplier: Optional multiplier for existing HWMax values.
                              If provided, new_hw_max = existing_hw_max * multiplier.
                              If None, HWMax is not modified (existing value kept).
            max_flow_multiplier: Optional multiplier for existing MaxFlow values.
                                If provided, new_max_flow = existing_max_flow * multiplier.
                                If None, MaxFlow is not modified (existing value kept).
            free_flow_points: Number of points on free flow curve (default 100, optimal 100).
                             Applied to all structures.
            submerged_curves: Number of submerged rating curves (default 60, optimal 60).
                             Applied to all structures.
            points_per_curve: Points per submerged curve (default 50, optimal 50).
                             Applied to all structures.
            create_backup: If True (default), create .bak backup before modification.

        Returns:
            dict: Summary of modifications with keys:
                - 'bridges': Number of bridge/culvert structures modified
                - 'inline_weirs': Number of inline weirs modified
                - 'total': Total structures modified
                - 'structures_detail': List of dicts with per-structure details
                - 'backup': Path to backup file (or None if create_backup=False)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            IOError: If file write fails

        Notes:
            - If multipliers are provided, existing HTAB values are scaled
            - If multipliers are None, only curve point counts are updated
            - Structures without existing HTAB lines get new lines inserted
            - Structures with existing HTAB lines have values replaced
            - Uses single file read/write cycle for efficiency (faster than calling
              set_htab() for each structure individually)

        Example:
            >>> # Double existing HWMax/MaxFlow values and set optimal curve points
            >>> result = GeomBridge.set_all_structures_htab(
            ...     "model.g01",
            ...     hw_max_multiplier=2.0,
            ...     max_flow_multiplier=2.0,
            ...     free_flow_points=100,
            ...     submerged_curves=60,
            ...     points_per_curve=50
            ... )
            >>> print(f"Modified {result['total']} structures")
            >>> print(f"Bridges: {result['bridges']}, Inline weirs: {result['inline_weirs']}")

            >>> # Update curve points only (don't change HWMax/MaxFlow)
            >>> result = GeomBridge.set_all_structures_htab(
            ...     "model.g01",
            ...     free_flow_points=100,
            ...     submerged_curves=60,
            ...     points_per_curve=50
            ... )

        See Also:
            - set_htab(): Set HTAB for single structure
            - get_bridges(): List all bridges in file
            - GeomInlineWeir.get_weirs(): List all inline weirs in file
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Validate curve point counts (clamp to valid ranges using GeomHtabUtils constants)
        from .GeomHtabUtils import GeomHtabUtils
        free_flow_points = max(GeomHtabUtils.MIN_FREE_FLOW_POINTS, min(free_flow_points, GeomHtabUtils.MAX_FREE_FLOW_POINTS))
        submerged_curves = max(GeomHtabUtils.MIN_SUBMERGED_CURVES, min(submerged_curves, GeomHtabUtils.MAX_SUBMERGED_CURVES))
        points_per_curve = max(GeomHtabUtils.MIN_POINTS_PER_CURVE, min(points_per_curve, GeomHtabUtils.MAX_POINTS_PER_CURVE))

        backup_path = None
        try:
            # Create backup if requested
            if create_backup:
                backup_path = GeomParser.create_backup(geom_file)
                logger.info(f"Created backup: {backup_path}")

            # Read file once
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find all structures
            structures = GeomBridge._find_all_structures(lines)

            if not structures:
                logger.info(f"No structures found in {geom_file.name}")
                return {
                    'bridges': 0,
                    'inline_weirs': 0,
                    'total': 0,
                    'structures_detail': [],
                    'backup': str(backup_path) if backup_path else None
                }

            logger.debug(f"Found {len(structures)} structures in {geom_file.name}")

            # Process structures in reverse order to preserve line indices
            # (modifications at higher indices don't affect lower indices)
            structures_sorted = sorted(structures, key=lambda s: s['marker_idx'], reverse=True)

            structures_detail = []
            bridges_modified = 0
            inline_weirs_modified = 0

            for struct in structures_sorted:
                struct_type = struct['type']
                river = struct['river']
                reach = struct['reach']
                rs = struct['rs']
                marker_idx = struct['marker_idx']

                # Find structure end
                struct_end_idx = GeomBridge._find_structure_end(lines, marker_idx)

                # Get existing HTAB values
                existing = GeomBridge._get_existing_htab_values(lines, marker_idx, struct_end_idx)

                # Calculate new values based on multipliers
                new_hw_max = None
                new_max_flow = None

                if hw_max_multiplier is not None and existing['hw_max'] is not None:
                    new_hw_max = existing['hw_max'] * hw_max_multiplier
                elif existing['hw_max'] is not None:
                    # Keep existing value if no multiplier
                    new_hw_max = existing['hw_max']

                if max_flow_multiplier is not None and existing['max_flow'] is not None:
                    new_max_flow = existing['max_flow'] * max_flow_multiplier
                elif existing['max_flow'] is not None:
                    # Keep existing value if no multiplier
                    new_max_flow = existing['max_flow']

                # Keep existing tw_max if present
                new_tw_max = existing['tw_max']

                # Find existing HTAB lines range
                first_htab, last_htab = GeomBridge._find_htab_lines_range(lines, marker_idx, struct_end_idx)

                # Format new HTAB lines
                new_htab_lines = GeomBridge._format_htab_lines(
                    hw_max=new_hw_max,
                    tw_max=new_tw_max,
                    max_flow=new_max_flow,
                    use_user_curves=-1,
                    free_flow_points=free_flow_points,
                    submerged_curves=submerged_curves,
                    points_per_curve=points_per_curve
                )

                # Track what changed
                detail = {
                    'type': struct_type,
                    'river': river,
                    'reach': reach,
                    'rs': rs,
                    'existing_hw_max': existing['hw_max'],
                    'existing_max_flow': existing['max_flow'],
                    'new_hw_max': new_hw_max,
                    'new_max_flow': new_max_flow,
                    'free_flow_points': free_flow_points,
                    'submerged_curves': submerged_curves,
                    'points_per_curve': points_per_curve
                }

                if first_htab is not None:
                    # Replace existing HTAB lines
                    lines = lines[:first_htab] + new_htab_lines + lines[last_htab + 1:]
                    detail['action'] = 'replaced'
                else:
                    # Insert new HTAB lines before structure end
                    lines = lines[:struct_end_idx] + new_htab_lines + lines[struct_end_idx:]
                    detail['action'] = 'inserted'

                structures_detail.append(detail)

                if struct_type == 'bridge':
                    bridges_modified += 1
                else:
                    inline_weirs_modified += 1

                logger.debug(
                    f"{detail['action'].capitalize()} HTAB for {struct_type} "
                    f"{river}/{reach}/RS {rs}: HWMax={new_hw_max}, MaxFlow={new_max_flow}"
                )

            # Write modified file once
            with open(geom_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            total_modified = bridges_modified + inline_weirs_modified
            logger.info(
                f"Successfully modified HTAB for {total_modified} structures "
                f"({bridges_modified} bridges/culverts, {inline_weirs_modified} inline weirs)"
            )

            result = {
                'bridges': bridges_modified,
                'inline_weirs': inline_weirs_modified,
                'total': total_modified,
                'structures_detail': structures_detail,
                'backup': str(backup_path) if backup_path else None
            }

            return result

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error in set_all_structures_htab: {str(e)}")
            # Attempt to restore from backup if write failed
            if backup_path and backup_path.exists():
                logger.info(f"Restoring from backup: {backup_path}")
                import shutil
                shutil.copy2(backup_path, geom_file)
            raise IOError(f"Failed to modify structure HTAB parameters: {str(e)}")

    @staticmethod
    @log_call
    def optimize_htab_from_results(
        geom_file: Union[str, Path],
        river: str,
        reach: str,
        rs: str,
        hdf_results_path: Union[str, Path],
        hw_safety_factor: float = 2.0,
        flow_safety_factor: float = 2.0,
        tw_safety_factor: float = 2.0,
        free_flow_points: int = 100,
        submerged_curves: int = 60,
        points_per_curve: int = 50,
        validate: bool = True,
        ras_object=None
    ) -> Dict[str, Any]:
        """
        Optimize structure HTAB parameters based on existing HDF results.

        This method extracts maximum headwater, tailwater, and flow values from
        a completed HEC-RAS simulation, applies safety factors, and writes
        optimal HTAB parameters to the geometry file.

        Algorithm:
            1. Extract max headwater from HDF results at structure location
            2. Extract max tailwater from HDF results at structure location
            3. Extract max flow from HDF results at structure location
            4. Get structure invert from deck geometry
            5. Calculate optimal values using GeomHtabUtils.calculate_optimal_structure_htab():
               - hw_max = invert + (max_hw - invert) * hw_safety_factor
               - tw_max = invert + (max_tw - invert) * tw_safety_factor
               - max_flow = max_flow * flow_safety_factor
            6. Set all curve point counts to optimal for best resolution
            7. Write parameters to geometry file

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station of structure (as string)
            hdf_results_path: Path to plan HDF file with results
            hw_safety_factor: Multiplier for headwater range above invert (default 2.0 = 100%)
                             Safety is applied to range, not absolute value.
            flow_safety_factor: Multiplier for maximum flow (default 2.0 = 100%)
            tw_safety_factor: Multiplier for tailwater range above invert (default 2.0 = 100%)
            free_flow_points: Points on free flow curve (default 100, optimal 100)
            submerged_curves: Number of submerged curves (default 60, optimal 60)
            points_per_curve: Points per submerged curve (default 50, optimal 50)
            validate: If True, validate parameters before writing (default: True)
            ras_object: RasPrj object for multi-project workflows

        Returns:
            dict: Parameters applied with keys:
                - 'hw_max': Calculated max headwater
                - 'tw_max': Calculated max tailwater
                - 'max_flow': Calculated max flow
                - 'struct_invert': Structure invert elevation
                - 'max_hw_from_results': Max HW observed in results
                - 'max_tw_from_results': Max TW observed in results
                - 'max_flow_from_results': Max flow observed in results
                - 'free_flow_points', 'submerged_curves', 'points_per_curve': Curve settings
                - 'hw_source', 'tw_source', 'flow_source': Source locations for data
                - 'backup_path': Path to backup file

        Raises:
            FileNotFoundError: If geometry or HDF file doesn't exist
            ValueError: If structure not found or no results available
            IOError: If file write fails

        Example:
            >>> # Run simulation first, then optimize HTAB based on results
            >>> params = GeomBridge.optimize_htab_from_results(
            ...     "model.g01", "White River", "Muncie", "5600",
            ...     "model.p01.hdf",
            ...     hw_safety_factor=2.0,
            ...     flow_safety_factor=2.0
            ... )
            >>> print(f"Optimized HWMax: {params['hw_max']:.2f}")
            >>> print(f"Based on max HW: {params['max_hw_from_results']:.2f}")

        Notes:
            - Requires a completed simulation with results in HDF file
            - Safety factors are applied to the RANGE above invert, not absolute values
            - For bridges: BR U section provides headwater, BR D provides tailwater
            - If tailwater not found separately, uses headwater value as conservative estimate
            - Creates .bak backup before modification

        See Also:
            - set_htab(): Direct HTAB parameter setting
            - GeomHtabUtils.calculate_optimal_structure_htab(): Parameter calculation
            - HdfStruc1D.get_structure_max_values(): HDF result extraction
        """
        from ..hdf import HdfStruc1D
        from .GeomHtabUtils import GeomHtabUtils

        geom_file = Path(geom_file)
        hdf_results_path = Path(hdf_results_path)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not hdf_results_path.exists():
            raise FileNotFoundError(f"HDF results file not found: {hdf_results_path}")

        # Step 1: Get structure invert from deck geometry
        htab_dict = GeomBridge.get_htab_dict(geom_file, river, reach, rs, include_invert=True)
        struct_invert = htab_dict.get('invert')

        if struct_invert is None:
            raise ValueError(
                f"Could not determine structure invert for {river}/{reach}/RS {rs}. "
                "Ensure the structure has deck geometry defined."
            )

        # Step 2: Extract max values from HDF results
        max_values = HdfStruc1D.get_structure_max_values(
            hdf_results_path, river, reach, rs, ras_object=ras_object
        )

        if not max_values.get('found'):
            raise ValueError(
                f"No results found for structure {river}/{reach}/RS {rs} in {hdf_results_path}. "
                "Ensure the simulation has completed and the structure is included in output."
            )

        max_hw = max_values.get('max_hw')
        max_tw = max_values.get('max_tw')
        max_flow = max_values.get('max_flow')

        if max_hw is None:
            raise ValueError(
                f"Could not extract max headwater for structure {river}/{reach}/RS {rs}. "
                f"Sources checked: {max_values.get('hw_source', 'unknown')}"
            )

        if max_flow is None:
            raise ValueError(
                f"Could not extract max flow for structure {river}/{reach}/RS {rs}. "
                f"Sources checked: {max_values.get('flow_source', 'unknown')}"
            )

        # Use headwater as tailwater estimate if not found
        if max_tw is None:
            max_tw = max_hw
            logger.info(f"Using headwater ({max_hw:.2f}) as tailwater estimate")

        # Step 3: Calculate optimal HTAB parameters
        optimal_params = GeomHtabUtils.calculate_optimal_structure_htab(
            struct_invert=struct_invert,
            max_hw=max_hw,
            max_tw=max_tw,
            max_flow=max_flow,
            hw_safety=hw_safety_factor,
            flow_safety=flow_safety_factor,
            tw_safety=tw_safety_factor,
            free_flow_points=free_flow_points,
            submerged_curves=submerged_curves,
            points_per_curve=points_per_curve
        )

        logger.info(
            f"Calculated optimal HTAB for {river}/{reach}/RS {rs}: "
            f"HW from {max_hw:.1f} to {optimal_params['hw_max']:.1f}, "
            f"Flow from {max_flow:.0f} to {optimal_params['max_flow']:.0f}"
        )

        # Step 4: Write parameters to geometry file
        write_result = GeomBridge.set_htab(
            geom_file=geom_file,
            river=river,
            reach=reach,
            rs=rs,
            hw_max=optimal_params['hw_max'],
            tw_max=optimal_params['tw_max'],
            max_flow=optimal_params['max_flow'],
            use_user_curves=optimal_params['use_user_curves'],
            free_flow_points=optimal_params['free_flow_points'],
            submerged_curves=optimal_params['submerged_curves'],
            points_per_curve=optimal_params['points_per_curve'],
            validate=validate
        )

        # Build comprehensive result
        result = {
            # Calculated values
            'hw_max': optimal_params['hw_max'],
            'tw_max': optimal_params['tw_max'],
            'max_flow': optimal_params['max_flow'],

            # Reference values from results
            'struct_invert': struct_invert,
            'max_hw_from_results': max_hw,
            'max_tw_from_results': max_tw,
            'max_flow_from_results': max_flow,

            # Curve settings
            'free_flow_points': optimal_params['free_flow_points'],
            'submerged_curves': optimal_params['submerged_curves'],
            'points_per_curve': optimal_params['points_per_curve'],

            # Safety factors used
            'hw_safety_factor': hw_safety_factor,
            'flow_safety_factor': flow_safety_factor,
            'tw_safety_factor': tw_safety_factor,

            # Source information
            'hw_source': max_values.get('hw_source'),
            'tw_source': max_values.get('tw_source'),
            'flow_source': max_values.get('flow_source'),

            # Backup info
            'backup_path': write_result.get('backup_path')
        }

        logger.info(
            f"Successfully optimized HTAB for {river}/{reach}/RS {rs}: "
            f"HWMax={result['hw_max']:.1f}, TWMax={result['tw_max']:.1f}, "
            f"MaxFlow={result['max_flow']:.0f}"
        )

        return result

    @staticmethod
    @log_call
    def optimize_all_structures_from_results(
        geom_file: Union[str, Path],
        hdf_results_path: Union[str, Path],
        hw_safety_factor: float = 2.0,
        flow_safety_factor: float = 2.0,
        tw_safety_factor: float = 2.0,
        free_flow_points: int = 100,
        submerged_curves: int = 60,
        points_per_curve: int = 50,
        create_backup: bool = True,
        ras_object=None
    ) -> Dict[str, Any]:
        """
        Optimize HTAB parameters for ALL structures in geometry file based on results.

        This method finds all structures (bridges, culverts, inline weirs) in the
        geometry file, extracts their maximum values from HDF results, and writes
        optimal HTAB parameters for each.

        Parameters:
            geom_file: Path to geometry file (.g##)
            hdf_results_path: Path to plan HDF file with results
            hw_safety_factor: Multiplier for headwater range (default 2.0 = 100% safety)
            flow_safety_factor: Multiplier for flow (default 2.0 = 100% safety)
            tw_safety_factor: Multiplier for tailwater range (default 2.0 = 100% safety)
            free_flow_points: Points on free flow curve (optimal 100)
            submerged_curves: Number of submerged curves (optimal 60)
            points_per_curve: Points per submerged curve (optimal 50)
            create_backup: Whether to create a .bak backup before modification (default True).
                          Set to False when called from an orchestrator that manages its own backup.
            ras_object: RasPrj object for multi-project workflows

        Returns:
            dict: Summary with keys:
                - 'optimized': Number of structures successfully optimized
                - 'failed': Number of structures that couldn't be optimized
                - 'total': Total structures found
                - 'details': List of per-structure results
                - 'errors': List of error messages for failed structures
                - 'backup_path': Path to geometry backup (or None if create_backup=False)

        Raises:
            FileNotFoundError: If geometry or HDF file doesn't exist
            IOError: If file write fails

        Example:
            >>> # Optimize all structures after running simulation
            >>> result = GeomBridge.optimize_all_structures_from_results(
            ...     "model.g01", "model.p01.hdf",
            ...     hw_safety_factor=2.0, flow_safety_factor=2.0
            ... )
            >>> print(f"Optimized {result['optimized']} of {result['total']} structures")
            >>> if result['failed'] > 0:
            ...     print(f"Failed: {result['errors']}")

        Notes:
            - Processes all structures found in geometry file
            - Creates single backup before any modifications
            - Continues processing if individual structures fail
            - Reports detailed results for each structure

        See Also:
            - optimize_htab_from_results(): Optimize single structure
            - get_bridges(): List all bridges in file
        """
        geom_file = Path(geom_file)
        hdf_results_path = Path(hdf_results_path)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not hdf_results_path.exists():
            raise FileNotFoundError(f"HDF results file not found: {hdf_results_path}")

        # Create single backup (if requested)
        backup_path = None
        if create_backup:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

        # Read file and find all structures
        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        structures = GeomBridge._find_all_structures(lines)

        if not structures:
            logger.info(f"No structures found in {geom_file.name}")
            return {
                'optimized': 0,
                'failed': 0,
                'total': 0,
                'details': [],
                'errors': [],
                'backup_path': str(backup_path) if backup_path else None
            }

        logger.debug(f"Found {len(structures)} structures to optimize")

        details = []
        errors = []
        optimized_count = 0
        failed_count = 0

        for struct in structures:
            river = struct['river']
            reach = struct['reach']
            rs = struct['rs']
            struct_type = struct['type']

            try:
                # Optimize this structure
                result = GeomBridge.optimize_htab_from_results(
                    geom_file=geom_file,
                    river=river,
                    reach=reach,
                    rs=rs,
                    hdf_results_path=hdf_results_path,
                    hw_safety_factor=hw_safety_factor,
                    flow_safety_factor=flow_safety_factor,
                    tw_safety_factor=tw_safety_factor,
                    free_flow_points=free_flow_points,
                    submerged_curves=submerged_curves,
                    points_per_curve=points_per_curve,
                    validate=False,  # Skip validation for batch (faster)
                    ras_object=ras_object
                )

                result['struct_type'] = struct_type
                result['river'] = river
                result['reach'] = reach
                result['rs'] = rs
                result['status'] = 'optimized'
                details.append(result)
                optimized_count += 1

                logger.debug(
                    f"Optimized {struct_type} {river}/{reach}/RS {rs}: "
                    f"HWMax={result['hw_max']:.1f}, MaxFlow={result['max_flow']:.0f}"
                )

            except Exception as e:
                error_msg = f"{struct_type} {river}/{reach}/RS {rs}: {str(e)}"
                errors.append(error_msg)
                details.append({
                    'struct_type': struct_type,
                    'river': river,
                    'reach': reach,
                    'rs': rs,
                    'status': 'failed',
                    'error': str(e)
                })
                failed_count += 1
                logger.warning(f"Failed to optimize {error_msg}")

        summary = {
            'optimized': optimized_count,
            'failed': failed_count,
            'total': len(structures),
            'details': details,
            'errors': errors,
            'backup_path': str(backup_path) if backup_path else None
        }

        logger.info(
            f"Structure HTAB optimization complete: "
            f"{optimized_count} optimized, {failed_count} failed of {len(structures)} total"
        )

        return summary
