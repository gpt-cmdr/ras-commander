"""
GeomCulvert - Culvert operations for HEC-RAS geometry files.

This module reads and authors culvert records in HEC-RAS plain text geometry
files (.g##), including single-barrel ``Culvert=`` records and real-world
``Multiple Barrel Culv=`` records with fixed-width barrel station pairs.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import pandas as pd

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomCulvert:
    """
    Operations for parsing and authoring HEC-RAS culverts in geometry files.

    All methods are static and designed to be used without instantiation.
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8
    VALUES_PER_LINE = 10
    DEFAULT_SEARCH_RANGE = 200
    MAX_PARSE_LINES = 200

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
    CULVERT_SHAPE_NAMES = {
        shape_name.casefold(): shape_code
        for shape_code, shape_name in CULVERT_SHAPES.items()
    }
    CULVERT_SHAPE_NAMES.update({
        shape_name.replace('-', ' ').casefold(): shape_code
        for shape_code, shape_name in CULVERT_SHAPES.items()
    })

    CULVERT_RECORD_PREFIXES = ("Culvert=", "Multiple Barrel Culv=")
    CULVERT_DETAIL_PREFIXES = (
        "Culvert Bottom n=",
        "Culvert Bottom Depth=",
        "BC Culvert Barrel=",
    )

    FIELD_ALIASES = {
        'record_type': 'RecordType',
        'recordtype': 'RecordType',
        'culvert_name': 'CulvertName',
        'name': 'CulvertName',
        'shape': 'Shape',
        'shape_code': 'Shape',
        'shapecode': 'Shape',
        'shape_name': 'ShapeName',
        'shapename': 'ShapeName',
        'span': 'Span',
        'rise': 'Rise',
        'length': 'Length',
        'mannings_n': 'ManningsN',
        'manning_n': 'ManningsN',
        'manningsn': 'ManningsN',
        'n': 'ManningsN',
        'entrance_loss': 'EntranceLoss',
        'entranceloss': 'EntranceLoss',
        'exit_loss': 'ExitLoss',
        'exitloss': 'ExitLoss',
        'inlet_type': 'InletType',
        'inlettype': 'InletType',
        'outlet_type': 'OutletType',
        'outlettype': 'OutletType',
        'upstream_invert': 'UpstreamInvert',
        'upstreaminvert': 'UpstreamInvert',
        'upstream_station': 'UpstreamStation',
        'upstreamstation': 'UpstreamStation',
        'downstream_invert': 'DownstreamInvert',
        'downstreaminvert': 'DownstreamInvert',
        'downstream_station': 'DownstreamStation',
        'downstreamstation': 'DownstreamStation',
        'num_barrels': 'NumBarrels',
        'numbarrels': 'NumBarrels',
        'barrel_stations': 'BarrelStations',
        'barrelstations': 'BarrelStations',
        'upstream_stations': 'UpstreamStations',
        'upstreamstations': 'UpstreamStations',
        'downstream_stations': 'DownstreamStations',
        'downstreamstations': 'DownstreamStations',
        'bottom_n': 'BottomN',
        'bottomn': 'BottomN',
        'bottom_depth': 'BottomDepth',
        'bottomdepth': 'BottomDepth',
        'chart_number': 'ChartNumber',
        'chartnumber': 'ChartNumber',
        'culvert_code': 'CulvertCode',
        'culvertcode': 'CulvertCode',
    }

    REQUIRED_FIELDS = (
        'Shape',
        'Span',
        'Length',
        'ManningsN',
        'EntranceLoss',
        'ExitLoss',
        'InletType',
        'OutletType',
        'UpstreamInvert',
        'DownstreamInvert',
    )

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
    def _find_structure_end(lines: List[str], bridge_idx: int) -> int:
        """Find the first line after a bridge/culvert structure block."""
        for i in range(bridge_idx + 1, min(bridge_idx + GeomCulvert.MAX_PARSE_LINES, len(lines))):
            line = lines[i]
            if (line.startswith("Type RM Length L Ch R =") or
                    line.startswith("River Reach=") or
                    line.startswith("Reach XS=")):
                return i
        return len(lines)

    @staticmethod
    def _is_missing(value: Any) -> bool:
        """Return True for values that should be treated as absent."""
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        if isinstance(value, (list, tuple, dict)):
            return False
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _parse_float(value: Any) -> Optional[float]:
        if GeomCulvert._is_missing(value):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_int(value: Any) -> Optional[int]:
        parsed = GeomCulvert._parse_float(value)
        if parsed is None:
            return None
        try:
            return int(parsed)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_text(value: Any) -> Optional[str]:
        if GeomCulvert._is_missing(value):
            return None
        return str(value).strip()

    @staticmethod
    def _shape_code(value: Any) -> Optional[int]:
        """Normalize a shape code or shape name to a HEC-RAS shape code."""
        if GeomCulvert._is_missing(value):
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if stripped.lstrip("-").isdigit():
                return int(stripped)
            return GeomCulvert.CULVERT_SHAPE_NAMES.get(stripped.casefold())
        return GeomCulvert._parse_int(value)

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format a scalar for HEC-RAS comma-separated culvert records."""
        if GeomCulvert._is_missing(value):
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return f"{value:g}"
        return str(value).strip()

    @staticmethod
    def _coerce_records(culverts: Union[pd.DataFrame, Sequence[Dict[str, Any]], Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert DataFrame, list-of-dicts, or single dict input to records."""
        if isinstance(culverts, pd.DataFrame):
            return culverts.to_dict(orient='records')
        if isinstance(culverts, dict):
            return [dict(culverts)]
        return [dict(record) for record in culverts]

    @staticmethod
    def _normalize_aliases(record: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize common snake_case/lowercase inputs to public column names."""
        normalized = {}
        for key, value in record.items():
            canonical = GeomCulvert.FIELD_ALIASES.get(str(key), None)
            if canonical is None:
                canonical = GeomCulvert.FIELD_ALIASES.get(str(key).replace(" ", "").casefold(), str(key))
            normalized[canonical] = value
        return normalized

    @staticmethod
    def _normalize_barrel_stations(record: Dict[str, Any]) -> List[Tuple[float, float]]:
        """Normalize barrel station data into upstream/downstream station pairs."""
        barrel_stations = record.get('BarrelStations')

        if not GeomCulvert._is_missing(barrel_stations):
            pairs = []
            for station_pair in barrel_stations:
                if isinstance(station_pair, dict):
                    up = station_pair.get('UpstreamStation', station_pair.get('upstream_station'))
                    dn = station_pair.get('DownstreamStation', station_pair.get('downstream_station'))
                else:
                    if len(station_pair) != 2:
                        raise ValueError("Each BarrelStations entry must contain two values")
                    up, dn = station_pair

                up_value = GeomCulvert._parse_float(up)
                dn_value = GeomCulvert._parse_float(dn)
                if up_value is None or dn_value is None:
                    raise ValueError("BarrelStations entries require upstream and downstream stations")
                pairs.append((up_value, dn_value))
            return pairs

        up_stations = record.get('UpstreamStations')
        dn_stations = record.get('DownstreamStations')
        if not GeomCulvert._is_missing(up_stations) or not GeomCulvert._is_missing(dn_stations):
            if GeomCulvert._is_missing(up_stations) or GeomCulvert._is_missing(dn_stations):
                raise ValueError("UpstreamStations and DownstreamStations must be supplied together")
            if len(up_stations) != len(dn_stations):
                raise ValueError("UpstreamStations and DownstreamStations lengths must match")
            return [
                (float(up), float(dn))
                for up, dn in zip(up_stations, dn_stations)
            ]

        up_station = GeomCulvert._parse_float(record.get('UpstreamStation'))
        dn_station = GeomCulvert._parse_float(record.get('DownstreamStation'))
        if up_station is not None and dn_station is not None:
            return [(up_station, dn_station)]
        if up_station is not None or dn_station is not None:
            raise ValueError("UpstreamStation and DownstreamStation must be supplied together")

        return []

    @staticmethod
    def _normalize_record(record: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
        """Validate and normalize a culvert record for writing."""
        record = GeomCulvert._normalize_aliases(record)

        shape = GeomCulvert._shape_code(record.get('Shape'))
        if shape is None:
            shape = GeomCulvert._shape_code(record.get('ShapeName'))
        if shape not in GeomCulvert.CULVERT_SHAPES:
            supported = ", ".join(f"{code}={name}" for code, name in GeomCulvert.CULVERT_SHAPES.items())
            raise ValueError(f"Unsupported culvert shape code/name {record.get('Shape')!r}. Supported: {supported}")

        normalized = {
            'RecordType': GeomCulvert._parse_text(record.get('RecordType')),
            'CulvertName': GeomCulvert._parse_text(record.get('CulvertName')) or f"Culvert # {index + 1}",
            'Shape': shape,
            'ShapeName': GeomCulvert.CULVERT_SHAPES[shape],
            'Span': GeomCulvert._parse_float(record.get('Span')),
            'Rise': GeomCulvert._parse_float(record.get('Rise')),
            'Length': GeomCulvert._parse_float(record.get('Length')),
            'ManningsN': GeomCulvert._parse_float(record.get('ManningsN')),
            'EntranceLoss': GeomCulvert._parse_float(record.get('EntranceLoss')),
            'ExitLoss': GeomCulvert._parse_float(record.get('ExitLoss')),
            'InletType': GeomCulvert._parse_int(record.get('InletType')),
            'OutletType': GeomCulvert._parse_int(record.get('OutletType')),
            'UpstreamInvert': GeomCulvert._parse_float(record.get('UpstreamInvert')),
            'DownstreamInvert': GeomCulvert._parse_float(record.get('DownstreamInvert')),
            'BottomN': GeomCulvert._parse_float(record.get('BottomN')),
            'BottomDepth': GeomCulvert._parse_float(record.get('BottomDepth')),
            'ChartNumber': GeomCulvert._parse_int(record.get('ChartNumber')),
            'CulvertCode': GeomCulvert._parse_int(record.get('CulvertCode')),
        }

        for field in GeomCulvert.REQUIRED_FIELDS:
            if GeomCulvert._is_missing(normalized[field]):
                raise ValueError(f"Culvert record {index} is missing required field: {field}")

        if shape != 1 and GeomCulvert._is_missing(normalized['Rise']):
            raise ValueError(f"Culvert record {index} is missing required field: Rise")

        barrel_stations = GeomCulvert._normalize_barrel_stations(record)
        num_barrels = GeomCulvert._parse_int(record.get('NumBarrels'))
        if num_barrels is None:
            num_barrels = len(barrel_stations) if barrel_stations else 1

        record_type = normalized['RecordType']
        write_multiple = (
            (record_type is not None and record_type.casefold().startswith('multiple')) or
            num_barrels > 1 or
            len(barrel_stations) > 1
        )

        if write_multiple:
            if num_barrels < 1:
                raise ValueError("NumBarrels must be at least 1")
            if len(barrel_stations) != num_barrels:
                raise ValueError(
                    f"Culvert record {index} declares NumBarrels={num_barrels} "
                    f"but provides {len(barrel_stations)} barrel station pairs"
                )
            normalized['RecordType'] = 'Multiple Barrel Culv'
        else:
            if not barrel_stations:
                raise ValueError(
                    f"Culvert record {index} requires UpstreamStation and DownstreamStation"
                )
            normalized['RecordType'] = 'Culvert'

        normalized['NumBarrels'] = num_barrels
        normalized['BarrelStations'] = barrel_stations
        normalized['UpstreamStations'] = [pair[0] for pair in barrel_stations]
        normalized['DownstreamStations'] = [pair[1] for pair in barrel_stations]
        normalized['UpstreamStation'] = barrel_stations[0][0] if barrel_stations else None
        normalized['DownstreamStation'] = barrel_stations[0][1] if barrel_stations else None

        if normalized['CulvertCode'] is None:
            normalized['CulvertCode'] = 0
        if normalized['ChartNumber'] is None:
            normalized['ChartNumber'] = 0

        return normalized

    @staticmethod
    def _parse_station_values(
        lines: List[str],
        start_idx: int,
        expected_count: int,
        section_end_idx: int,
    ) -> Tuple[List[float], int]:
        """Parse fixed-width station values following a Multiple Barrel Culv line."""
        values = []
        i = start_idx

        while len(values) < expected_count and i < section_end_idx:
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            if '=' in line:
                break

            values.extend(GeomParser.parse_fixed_width(line, GeomCulvert.FIXED_WIDTH_COLUMN))
            i += 1

            if i > start_idx + GeomCulvert.MAX_PARSE_LINES:
                logger.warning("Exceeded culvert barrel station parse limit")
                break

        return values[:expected_count], i

    @staticmethod
    def _parse_culvert_record(
        lines: List[str],
        line_idx: int,
        section_end_idx: int,
    ) -> Tuple[Dict[str, Any], int]:
        """Parse a Culvert= or Multiple Barrel Culv= record and return next index."""
        line = lines[line_idx]
        is_multiple = line.startswith("Multiple Barrel Culv=")
        keyword = "Multiple Barrel Culv" if is_multiple else "Culvert"
        value_str = GeomParser.extract_keyword_value(line, keyword)
        parts = [part.strip() for part in value_str.split(',')]

        data = {
            'RecordType': 'Multiple Barrel Culv' if is_multiple else 'Culvert',
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
            'UpstreamStations': [],
            'DownstreamStations': [],
            'BarrelStations': [],
            'ChartNumber': None,
            'CulvertCode': None,
            'BottomN': None,
            'BottomDepth': None,
            'NumBarrels': 1,
        }

        shape = GeomCulvert._parse_int(parts[0]) if len(parts) > 0 else None
        data['Shape'] = shape
        data['ShapeName'] = GeomCulvert.CULVERT_SHAPES.get(shape, f'Unknown ({shape})' if shape is not None else None)
        data['Span'] = GeomCulvert._parse_float(parts[1]) if len(parts) > 1 else None
        data['Rise'] = GeomCulvert._parse_float(parts[2]) if len(parts) > 2 else None
        data['Length'] = GeomCulvert._parse_float(parts[3]) if len(parts) > 3 else None
        data['ManningsN'] = GeomCulvert._parse_float(parts[4]) if len(parts) > 4 else None
        data['EntranceLoss'] = GeomCulvert._parse_float(parts[5]) if len(parts) > 5 else None
        data['ExitLoss'] = GeomCulvert._parse_float(parts[6]) if len(parts) > 6 else None
        data['InletType'] = GeomCulvert._parse_int(parts[7]) if len(parts) > 7 else None
        data['OutletType'] = GeomCulvert._parse_int(parts[8]) if len(parts) > 8 else None
        data['UpstreamInvert'] = GeomCulvert._parse_float(parts[9]) if len(parts) > 9 else None

        next_idx = line_idx + 1

        if is_multiple:
            data['DownstreamInvert'] = GeomCulvert._parse_float(parts[10]) if len(parts) > 10 else None
            data['NumBarrels'] = GeomCulvert._parse_int(parts[11]) if len(parts) > 11 else 1
            data['CulvertName'] = GeomCulvert._parse_text(parts[12]) if len(parts) > 12 else None
            data['CulvertCode'] = GeomCulvert._parse_int(parts[13]) if len(parts) > 13 else None
            data['ChartNumber'] = GeomCulvert._parse_int(parts[14]) if len(parts) > 14 else None

            expected_values = max(data['NumBarrels'] or 0, 0) * 2
            station_values, next_idx = GeomCulvert._parse_station_values(
                lines, next_idx, expected_values, section_end_idx
            )
            barrel_stations = [
                (station_values[i], station_values[i + 1])
                for i in range(0, len(station_values) - 1, 2)
            ]
            data['BarrelStations'] = barrel_stations
            data['UpstreamStations'] = [pair[0] for pair in barrel_stations]
            data['DownstreamStations'] = [pair[1] for pair in barrel_stations]
            if len(barrel_stations) == 1:
                data['UpstreamStation'] = barrel_stations[0][0]
                data['DownstreamStation'] = barrel_stations[0][1]
        else:
            data['UpstreamStation'] = GeomCulvert._parse_float(parts[10]) if len(parts) > 10 else None
            data['DownstreamInvert'] = GeomCulvert._parse_float(parts[11]) if len(parts) > 11 else None
            data['DownstreamStation'] = GeomCulvert._parse_float(parts[12]) if len(parts) > 12 else None
            data['CulvertName'] = GeomCulvert._parse_text(parts[13]) if len(parts) > 13 else None
            data['CulvertCode'] = GeomCulvert._parse_int(parts[14]) if len(parts) > 14 else None
            data['ChartNumber'] = GeomCulvert._parse_int(parts[15]) if len(parts) > 15 else None
            if data['UpstreamStation'] is not None and data['DownstreamStation'] is not None:
                data['BarrelStations'] = [(data['UpstreamStation'], data['DownstreamStation'])]
                data['UpstreamStations'] = [data['UpstreamStation']]
                data['DownstreamStations'] = [data['DownstreamStation']]

        while next_idx < section_end_idx:
            next_line = lines[next_idx]
            if next_line.startswith("Culvert Bottom n="):
                bottom_n = GeomParser.extract_keyword_value(next_line, "Culvert Bottom n")
                data['BottomN'] = GeomCulvert._parse_float(bottom_n)
                next_idx += 1
            elif next_line.startswith("Culvert Bottom Depth="):
                bottom_depth = GeomParser.extract_keyword_value(next_line, "Culvert Bottom Depth")
                data['BottomDepth'] = GeomCulvert._parse_float(bottom_depth)
                next_idx += 1
            elif next_line.startswith("BC Culvert Barrel="):
                barrel_val = GeomParser.extract_keyword_value(next_line, "BC Culvert Barrel")
                barrel_parts = [p.strip() for p in barrel_val.split(',')]
                if barrel_parts:
                    data['NumBarrels'] = GeomCulvert._parse_int(barrel_parts[0]) or data['NumBarrels']
                next_idx += 1
            else:
                break

        return data, next_idx

    @staticmethod
    def _find_culvert_records_range(lines: List[str], bridge_idx: int, section_end_idx: int) -> Tuple[int, int]:
        """Find the line range containing existing culvert records for replacement."""
        first_culvert = None
        i = bridge_idx + 1

        while i < section_end_idx:
            if lines[i].startswith(GeomCulvert.CULVERT_RECORD_PREFIXES):
                first_culvert = i
                break
            i += 1

        if first_culvert is None:
            for i in range(bridge_idx + 1, section_end_idx):
                if (lines[i].startswith("BC Design=") or
                        lines[i].startswith("BC HTab") or
                        lines[i].startswith("BC Use User")):
                    return i, i
            return section_end_idx, section_end_idx

        i = first_culvert
        last_idx = first_culvert
        while i < section_end_idx:
            if lines[i].startswith(GeomCulvert.CULVERT_RECORD_PREFIXES):
                _, i = GeomCulvert._parse_culvert_record(lines, i, section_end_idx)
                last_idx = i
            elif lines[i].startswith(GeomCulvert.CULVERT_DETAIL_PREFIXES):
                i += 1
                last_idx = i
            elif lines[i].strip() == "":
                i += 1
                last_idx = i
            else:
                break

        return first_culvert, last_idx

    @staticmethod
    def _format_culvert_record(record: Dict[str, Any]) -> List[str]:
        """Format a normalized culvert record into HEC-RAS geometry lines."""
        is_multiple = record['RecordType'] == 'Multiple Barrel Culv'

        if is_multiple:
            fields = [
                record['Shape'],
                record['Span'],
                record['Rise'],
                record['Length'],
                record['ManningsN'],
                record['EntranceLoss'],
                record['ExitLoss'],
                record['InletType'],
                record['OutletType'],
                record['UpstreamInvert'],
                record['DownstreamInvert'],
                record['NumBarrels'],
                record['CulvertName'],
                record['CulvertCode'],
                record['ChartNumber'],
            ]
            output = [f"Multiple Barrel Culv={','.join(GeomCulvert._format_value(v) for v in fields)}\n"]
            station_values = []
            for upstream_station, downstream_station in record['BarrelStations']:
                station_values.extend([upstream_station, downstream_station])
            output.extend(GeomParser.format_fixed_width(
                station_values,
                column_width=GeomCulvert.FIXED_WIDTH_COLUMN,
                values_per_line=GeomCulvert.VALUES_PER_LINE,
                precision=2,
            ))
        else:
            fields = [
                record['Shape'],
                record['Span'],
                record['Rise'],
                record['Length'],
                record['ManningsN'],
                record['EntranceLoss'],
                record['ExitLoss'],
                record['InletType'],
                record['OutletType'],
                record['UpstreamInvert'],
                record['UpstreamStation'],
                record['DownstreamInvert'],
                record['DownstreamStation'],
                record['CulvertName'],
                record['CulvertCode'],
                record['ChartNumber'],
            ]
            output = [f"Culvert={','.join(GeomCulvert._format_value(v) for v in fields)}\n"]

        if record['BottomN'] is not None:
            output.append(f"Culvert Bottom n={GeomCulvert._format_value(record['BottomN'])}\n")
        if record['BottomDepth'] is not None:
            output.append(f"Culvert Bottom Depth={GeomCulvert._format_value(record['BottomDepth'])}\n")

        return output

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx = GeomCulvert._find_bridge(lines, river, reach, rs)

            if bridge_idx is None:
                raise ValueError(f"Bridge/culvert not found: {river}/{reach}/RS {rs}")

            culverts = []
            section_end_idx = GeomCulvert._find_structure_end(lines, bridge_idx)

            i = bridge_idx
            while i < section_end_idx:
                line = lines[i]

                if line.startswith(GeomCulvert.CULVERT_RECORD_PREFIXES):
                    culvert_data, next_idx = GeomCulvert._parse_culvert_record(lines, i, section_end_idx)
                    culverts.append(culvert_data)
                    i = max(next_idx, i + 1)
                    continue

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
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
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

                elif line.startswith(GeomCulvert.CULVERT_RECORD_PREFIXES):
                    if river is not None and current_river != river:
                        i += 1
                        continue
                    if reach is not None and current_reach != reach:
                        i += 1
                        continue

                    section_end_idx = GeomCulvert._find_structure_end(lines, i)
                    culvert_data, next_idx = GeomCulvert._parse_culvert_record(lines, i, section_end_idx)
                    culvert_data.update({
                        'River': current_river,
                        'Reach': current_reach,
                        'RS': last_rs,
                    })
                    all_culverts.append(culvert_data)
                    i = max(next_idx, i + 1)
                    continue

                i += 1

            df = pd.DataFrame(all_culverts)
            logger.debug(f"Found {len(df)} total culverts in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading all culverts: {str(e)}")
            raise IOError(f"Failed to read all culverts: {str(e)}")

    @staticmethod
    @log_call
    def set_culverts(geom_file: Union[str, Path],
                     river: str,
                     reach: str,
                     rs: str,
                     culverts: Union[pd.DataFrame, Sequence[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
        """
        Replace all culvert records at an existing bridge/culvert structure.

        Parameters:
            geom_file: Path to geometry file (.g##)
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station for the bridge/culvert structure
            culverts: DataFrame, list of dicts, or single dict with culvert fields.
                Supported shape inputs are numeric ``Shape`` codes or ``ShapeName``.
                Multi-barrel culverts require ``NumBarrels`` and ``BarrelStations``.

        Returns:
            dict with replacement counts and backup path

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If structure is missing, shape is unsupported, or required fields are missing
            IOError: If write fails
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        raw_records = GeomCulvert._coerce_records(culverts)
        if not raw_records:
            raise ValueError("At least one culvert record is required")

        normalized_records = [
            GeomCulvert._normalize_record(record, index=i)
            for i, record in enumerate(raw_records)
        ]
        new_lines = []
        for record in normalized_records:
            new_lines.extend(GeomCulvert._format_culvert_record(record))

        backup_path = None
        try:
            backup_path = GeomParser.create_backup(geom_file)

            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            bridge_idx = GeomCulvert._find_bridge(lines, river, reach, rs)
            if bridge_idx is None:
                raise ValueError(f"Bridge/culvert not found: {river}/{reach}/RS {rs}")

            section_end_idx = GeomCulvert._find_structure_end(lines, bridge_idx)
            replace_start, replace_end = GeomCulvert._find_culvert_records_range(
                lines, bridge_idx, section_end_idx
            )

            modified_lines = lines[:replace_start] + new_lines + lines[replace_end:]

            with open(geom_file, 'w', encoding='utf-8') as f:
                f.writelines(modified_lines)

            result = {
                'culverts_written': len(normalized_records),
                'lines_replaced': replace_end - replace_start,
                'lines_inserted': len(new_lines),
                'backup_path': str(backup_path),
            }
            logger.debug(
                f"Wrote {len(normalized_records)} culvert records at {river}/{reach}/RS {rs}"
            )
            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing culverts: {str(e)}")
            if backup_path and backup_path.exists():
                import shutil
                shutil.copy2(backup_path, geom_file)
            raise IOError(f"Failed to write culverts: {str(e)}")

    @staticmethod
    @log_call
    def set_culvert(geom_file: Union[str, Path],
                    river: str,
                    reach: str,
                    rs: str,
                    culvert: Optional[Dict[str, Any]] = None,
                    culvert_index: Optional[int] = None,
                    culvert_name: Optional[str] = None,
                    **kwargs) -> Dict[str, Any]:
        """
        Update one culvert record or append a new one at a bridge/culvert structure.

        If ``culvert_index`` or ``culvert_name`` matches an existing record, that
        record is replaced. If neither selector is supplied, the record is appended.
        Keyword arguments are merged into ``culvert`` for ergonomic single-record
        authoring.
        """
        record = dict(culvert or {})
        record.update(kwargs)

        existing = GeomCulvert.get_culverts(geom_file, river, reach, rs)
        records = existing.to_dict(orient='records') if not existing.empty else []

        target_index = None
        if culvert_index is not None:
            if culvert_index < 0 or culvert_index >= len(records):
                raise ValueError(
                    f"culvert_index {culvert_index} is out of range for {len(records)} existing culverts"
                )
            target_index = culvert_index
        elif culvert_name is not None:
            for i, existing_record in enumerate(records):
                if existing_record.get('CulvertName') == culvert_name:
                    target_index = i
                    break
            if target_index is None:
                raise ValueError(f"Culvert not found by name: {culvert_name}")

        if target_index is None:
            records.append(record)
            action = 'appended'
        else:
            merged_record = dict(records[target_index])
            merged_record.update(record)
            records[target_index] = merged_record
            action = 'updated'

        result = GeomCulvert.set_culverts(geom_file, river, reach, rs, records)
        result['action'] = action
        result['culvert_index'] = target_index if target_index is not None else len(records) - 1
        return result

    @staticmethod
    @log_call
    def get_adjacent_cross_sections(geom_file: Union[str, Path],
                                    river: str,
                                    reach: str,
                                    rs: str) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Return the nearest upstream and downstream cross sections around a structure.

        The helper scans the same river/reach block and returns the immediate
        Type 1 cross sections before and after the bridge/culvert structure.
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        bridge_idx = GeomCulvert._find_bridge(lines, river, reach, rs)
        if bridge_idx is None:
            raise ValueError(f"Bridge/culvert not found: {river}/{reach}/RS {rs}")

        current_river = None
        current_reach = None
        cross_sections = []

        for i, line in enumerate(lines):
            if line.startswith("River Reach="):
                values = GeomParser.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]
            elif line.startswith("Type RM Length L Ch R ="):
                value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
                values = [v.strip() for v in value_str.split(',')]
                if len(values) > 1 and current_river == river and current_reach == reach:
                    xs_type = GeomCulvert._parse_int(values[0])
                    if xs_type == 1:
                        cross_sections.append({
                            'River': current_river,
                            'Reach': current_reach,
                            'RS': values[1],
                            'Type': xs_type,
                            'LineIndex': i,
                        })

        upstream = None
        downstream = None
        for cross_section in cross_sections:
            if cross_section['LineIndex'] < bridge_idx:
                upstream = cross_section
            elif cross_section['LineIndex'] > bridge_idx:
                downstream = cross_section
                break

        return {
            'upstream': upstream,
            'downstream': downstream,
        }

    @staticmethod
    @log_call
    def set_adjacent_ineffective_flow(geom_file: Union[str, Path],
                                      river: str,
                                      reach: str,
                                      rs: str,
                                      upstream_ineffective: Optional[Union[pd.DataFrame, Sequence[Dict[str, Any]]]] = None,
                                      downstream_ineffective: Optional[Union[pd.DataFrame, Sequence[Dict[str, Any]]]] = None,
                                      upstream_permanent_flags: Optional[List[bool]] = None,
                                      downstream_permanent_flags: Optional[List[bool]] = None,
                                      fmt_flag: int = 0) -> Dict[str, Any]:
        """
        Write ineffective-flow areas at the cross sections adjacent to a culvert.

        ``upstream_ineffective`` and ``downstream_ineffective`` use the
        ``GeomCrossSection.set_ineffective_flow`` columns:
        ``left_station``, ``right_station``, and ``elevation``.
        """
        from .GeomCrossSection import GeomCrossSection

        adjacent = GeomCulvert.get_adjacent_cross_sections(geom_file, river, reach, rs)
        result = {
            'upstream_rs': adjacent['upstream']['RS'] if adjacent['upstream'] else None,
            'downstream_rs': adjacent['downstream']['RS'] if adjacent['downstream'] else None,
            'updated': [],
        }

        if upstream_ineffective is not None:
            if adjacent['upstream'] is None:
                raise ValueError(f"No upstream cross section found for {river}/{reach}/RS {rs}")
            upstream_df = (
                upstream_ineffective
                if isinstance(upstream_ineffective, pd.DataFrame)
                else pd.DataFrame(upstream_ineffective)
            )
            GeomCrossSection.set_ineffective_flow(
                geom_file,
                river,
                reach,
                adjacent['upstream']['RS'],
                upstream_df,
                fmt_flag=fmt_flag,
                permanent_flags=upstream_permanent_flags,
            )
            result['updated'].append('upstream')

        if downstream_ineffective is not None:
            if adjacent['downstream'] is None:
                raise ValueError(f"No downstream cross section found for {river}/{reach}/RS {rs}")
            downstream_df = (
                downstream_ineffective
                if isinstance(downstream_ineffective, pd.DataFrame)
                else pd.DataFrame(downstream_ineffective)
            )
            GeomCrossSection.set_ineffective_flow(
                geom_file,
                river,
                reach,
                adjacent['downstream']['RS'],
                downstream_df,
                fmt_flag=fmt_flag,
                permanent_flags=downstream_permanent_flags,
            )
            result['updated'].append('downstream')

        return result
