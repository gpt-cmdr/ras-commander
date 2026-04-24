"""
GeomStorage - Storage area operations for HEC-RAS geometry files

This module provides functionality for reading and writing storage area data
in HEC-RAS plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_storage_areas() - List all storage areas with metadata
- get_elevation_volume() - Read elevation-volume curve for a storage area
- set_elevation_volume() - Write elevation-volume curve to a storage area
- get_storage_area_polygons() - Extract storage area polygon perimeter geometry
- set_2d_flow_area_perimeter() - Create/update 2D flow area perimeter geometry
- get_2d_flow_area_settings() - Read 2D flow area cell/face property settings
- set_2d_flow_area_settings() - Write 2D flow area cell/face property settings
- set_breaklines() - Write breakline blocks into a 2D flow area geometry file

Example Usage:
    >>> from ras_commander import GeomStorage
    >>> from pathlib import Path
    >>>
    >>> # List all storage areas
    >>> geom_file = Path("model.g01")
    >>> storage_df = GeomStorage.get_storage_areas(geom_file)
    >>> print(f"Found {len(storage_df)} storage areas")
    >>>
    >>> # Get elevation-volume curve
    >>> elev_vol = GeomStorage.get_elevation_volume(geom_file, "Reservoir Pool 1")
    >>> print(elev_vol)
    >>>
    >>> # Write modified curve back to file
    >>> GeomStorage.set_elevation_volume(
    ...     geom_file, "Reservoir Pool 1",
    ...     elevations=[1200.0, 1210.0, 1220.0],
    ...     volumes=[0.0, 500.0, 1500.0]
    ... )
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Union, Optional, List, Sequence
import pandas as pd

if TYPE_CHECKING:
    from geopandas import GeoDataFrame

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomStorage:
    """
    Operations for parsing HEC-RAS storage areas in geometry files.

    All methods are static and designed to be used without instantiation.
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8      # Character width for numeric data in geometry files
    VALUES_PER_LINE = 10        # Number of values per line in fixed-width format
    SURFACE_LINE_COLUMN = 16
    SURFACE_LINE_VALUES_PER_LINE = 2
    SURFACE_LINE_PRECISION = 7

    DEFAULT_2D_POINT_GENERATION_DATA = ",,,"

    _INVALID_NAME_CHARS = set(',=') | {chr(c) for c in range(0, 32)} | {chr(127)}

    # Plain text keywords for 2D flow area settings
    _SETTINGS_KEYWORDS = {
        'Storage Area Mannings': 'mannings_n',
        '2D Cell Volume Filter Tolerance': 'cell_vol_tol',
        '2D Cell Minimum Area Fraction': 'cell_min_area_fraction',
        '2D Face Profile Filter Tolerance': 'face_profile_tol',
        '2D Face Area Elevation Profile Filter Tolerance': 'face_area_tol',
        '2D Face Area Elevation Conveyance Ratio': 'face_conv_ratio',
        '2D Face Area Laminar Depth': 'laminar_depth',
        '2D Face Min Length Ratio': 'min_face_length_ratio',
    }

    # Boolean keywords: present with =-1 means True, absent means False
    _BOOLEAN_KEYWORDS = {
        '2D Multiple Face Mann n': 'spatially_varied_mann_on_faces',
        '2D Composite LC': 'composite_classification',
    }

    _DEFAULT_2D_SETTINGS = {
        'mannings_n': 0.04,
        'spatially_varied_mann_on_faces': False,
        'composite_classification': False,
        'cell_vol_tol': 0.01,
        'cell_min_area_fraction': 0.01,
        'face_profile_tol': 0.01,
        'face_area_tol': 0.01,
        'face_conv_ratio': 0.02,
        'laminar_depth': 0.2,
        'min_face_length_ratio': float('nan'),
        'point_generation_data': DEFAULT_2D_POINT_GENERATION_DATA,
    }

    @staticmethod
    def _extract_storage_area_name(line: str) -> str:
        """Return the storage area name from a Storage Area= header line."""
        value_str = GeomParser.extract_keyword_value(line, "Storage Area")
        parts = [p.strip() for p in value_str.split(',')]
        return parts[0] if parts else value_str

    @staticmethod
    def _extract_storage_area_header(line: str) -> dict:
        """Parse name and centroid coordinates from a Storage Area= header line."""
        value_str = GeomParser.extract_keyword_value(line, "Storage Area")
        parts = [p.strip() for p in value_str.split(',')]
        result = {
            'name': parts[0] if parts else value_str,
            'centroid_x': None,
            'centroid_y': None,
        }

        try:
            result['centroid_x'] = float(parts[1]) if len(parts) > 1 else None
            result['centroid_y'] = float(parts[2]) if len(parts) > 2 else None
        except ValueError:
            result['centroid_x'] = None
            result['centroid_y'] = None

        return result

    @staticmethod
    def _validate_flow_area_name(name: str) -> None:
        """Reject names containing characters that corrupt the .g## header format."""
        bad = GeomStorage._INVALID_NAME_CHARS.intersection(name)
        if bad:
            raise ValueError(
                f"flow_area_name contains invalid characters {bad!r}: {name!r}"
            )

    _BLOCK_TERMINATORS = (
        "Storage Area=",
        "River Reach=",
        "BreakLine Name=",
        "Connection=",
        "BC Line Name=",
        "LCMann Time=",
        "Chan Stop Cuts=",
    )

    @staticmethod
    def _iter_storage_area_blocks(lines: List[str]):
        """Yield (start_idx, end_idx, block_lines) for each storage area block."""
        i = 0
        while i < len(lines):
            if lines[i].startswith("Storage Area="):
                start_idx = i
                end_idx = i + 1
                while end_idx < len(lines):
                    if any(
                        lines[end_idx].startswith(term)
                        for term in GeomStorage._BLOCK_TERMINATORS
                    ):
                        break
                    end_idx += 1
                yield start_idx, end_idx, lines[start_idx:end_idx]
                i = end_idx
                continue
            i += 1

    @staticmethod
    def _find_storage_area_block(lines: List[str], storage_name: str):
        """Return (start_idx, end_idx, block_lines) for a named storage area."""
        for start_idx, end_idx, block_lines in GeomStorage._iter_storage_area_blocks(lines):
            if GeomStorage._extract_storage_area_name(block_lines[0]) == storage_name:
                return start_idx, end_idx, block_lines
        return None

    @staticmethod
    def _find_section_end(block_lines: List[str], keyword_idx: int) -> int:
        """Return the exclusive end index for a fixed-width data section."""
        end_idx = keyword_idx + 1
        while end_idx < len(block_lines):
            if '=' in block_lines[end_idx]:
                break
            end_idx += 1
        return end_idx

    @staticmethod
    def _inspect_storage_area_block(block_lines: List[str]) -> dict:
        """Collect key indices and parsed settings for a storage area block."""
        info = {
            'header': GeomStorage._extract_storage_area_header(block_lines[0]),
            'surface_line_idx': None,
            'surface_line_end': None,
            'type_line_idx': None,
            'area_line_idx': None,
            'min_elev_line_idx': None,
            'is2d_line_idx': None,
            'point_generation_idx': None,
            'point_generation_data': None,
            'points_idx': None,
            'points_end': None,
            'points_time_idx': None,
            'settings_start': None,
            'settings_end': None,
            'is_2d': False,
            'settings': dict(GeomStorage._DEFAULT_2D_SETTINGS),
        }
        info['settings']['point_generation_data'] = None

        for idx, line in enumerate(block_lines):
            if line.startswith("Storage Area Surface Line="):
                info['surface_line_idx'] = idx
                info['surface_line_end'] = GeomStorage._find_section_end(block_lines, idx)
            elif line.startswith("Storage Area Type="):
                info['type_line_idx'] = idx
            elif line.startswith("Storage Area Area="):
                info['area_line_idx'] = idx
            elif line.startswith("Storage Area Min Elev="):
                info['min_elev_line_idx'] = idx
            elif line.startswith("Storage Area Is2D="):
                info['is2d_line_idx'] = idx
                is2d_str = GeomParser.extract_keyword_value(line, "Storage Area Is2D")
                try:
                    info['is_2d'] = int(is2d_str.strip()) == -1
                except ValueError:
                    info['is_2d'] = False
            elif line.startswith("Storage Area Point Generation Data="):
                info['point_generation_idx'] = idx
                info['point_generation_data'] = GeomParser.extract_keyword_value(
                    line, "Storage Area Point Generation Data"
                )
                info['settings']['point_generation_data'] = info['point_generation_data']
            elif line.startswith("Storage Area 2D Points="):
                info['points_idx'] = idx
                info['points_end'] = GeomStorage._find_section_end(block_lines, idx)
            elif line.startswith("Storage Area 2D PointsPerimeterTime="):
                info['points_time_idx'] = idx
            else:
                matched_setting = False
                for keyword, column in GeomStorage._SETTINGS_KEYWORDS.items():
                    if line.startswith(keyword + '='):
                        val_str = GeomParser.extract_keyword_value(line, keyword)
                        try:
                            info['settings'][column] = float(val_str.strip())
                        except ValueError:
                            pass
                        matched_setting = True
                        break

                if matched_setting:
                    continue

                for keyword, column in GeomStorage._BOOLEAN_KEYWORDS.items():
                    if line.startswith(keyword + '='):
                        val_str = GeomParser.extract_keyword_value(line, keyword)
                        try:
                            info['settings'][column] = int(val_str.strip()) == -1
                        except ValueError:
                            pass
                        break

        setting_prefixes = tuple(
            f"{keyword}=" for keyword in (
                list(GeomStorage._SETTINGS_KEYWORDS.keys()) +
                list(GeomStorage._BOOLEAN_KEYWORDS.keys())
            )
        )

        for idx, line in enumerate(block_lines):
            if line.startswith(setting_prefixes):
                info['settings_start'] = idx
                break

        if info['settings_start'] is not None:
            end_idx = info['settings_start']
            while end_idx < len(block_lines):
                stripped = block_lines[end_idx].strip()
                if not stripped:
                    break
                if block_lines[end_idx].startswith(setting_prefixes):
                    end_idx += 1
                    continue
                break
            info['settings_end'] = end_idx

        return info

    @staticmethod
    def _format_storage_area_header(
        name: str,
        centroid_x: float,
        centroid_y: float,
        raw_header_line: Optional[str] = None,
    ) -> str:
        """Format a Storage Area= header line with centroid coordinates.

        When raw_header_line is provided, preserves the original header text
        verbatim (keeping original centroid formatting and name padding).
        """
        if raw_header_line is not None:
            return raw_header_line if raw_header_line.endswith('\n') else raw_header_line + '\n'
        return f"Storage Area={name},{centroid_x:.7f},{centroid_y:.7f}\n"

    @staticmethod
    def _max_precision_for_field(value: float, column_width: int) -> int:
        """Compute the max decimal places that fit a value in a fixed-width field.

        Uses a fit loop: starts from an arithmetic estimate and decrements
        until the formatted string actually fits, handling rounding carry
        (e.g. 99.9999… rounding to 100).
        """
        sign_chars = 1 if value < 0 else 0
        integer_part = int(abs(value))
        int_digits = max(1, len(str(integer_part)))
        overhead = sign_chars + int_digits + 1
        prec = max(0, column_width - overhead)

        while prec > 0:
            formatted = f"{value:{column_width}.{prec}f}"
            if len(formatted) <= column_width:
                return prec
            prec -= 1

        return 0

    @staticmethod
    def _format_surface_line_lines(coords: List[tuple[float, float]]) -> List[str]:
        """Format perimeter XY pairs in HEC-RAS fixed-width surface line form.

        Uses adaptive precision: each value gets the maximum decimal places
        that fit within the 16-character field width, preserving more
        significant digits than a fixed 7-decimal approach.
        """
        col_w = GeomStorage.SURFACE_LINE_COLUMN
        vpl = GeomStorage.SURFACE_LINE_VALUES_PER_LINE
        lines = []
        flat_values = []
        for x_coord, y_coord in coords:
            flat_values.extend([x_coord, y_coord])

        for i in range(0, len(flat_values), vpl):
            row_values = flat_values[i:i + vpl]
            parts = []
            for val in row_values:
                prec = GeomStorage._max_precision_for_field(val, col_w)
                parts.append(f"{val:{col_w}.{prec}f}")
            lines.append("".join(parts) + "\n")

        return lines

    @staticmethod
    def _current_timestamp() -> str:
        """Return a HEC-RAS style timestamp string for perimeter edits."""
        return datetime.now().strftime("%d%b%Y %H:%M:%S")

    @staticmethod
    def _normalize_perimeter_coords(
        coordinates: Optional[Sequence[Sequence[float]]] = None,
        geometry=None,
    ) -> List[tuple[float, float]]:
        """Normalize coordinate or shapely polygon input into a closed XY ring."""
        if coordinates is None and geometry is None:
            raise ValueError("Provide polygon coordinates or a shapely geometry")
        if coordinates is not None and geometry is not None:
            raise ValueError("Provide either coordinates or geometry, not both")

        if geometry is not None:
            geom_type = getattr(geometry, "geom_type", None)
            if geom_type == "Polygon":
                raw_coords = list(geometry.exterior.coords)
            elif geom_type == "LinearRing":
                raw_coords = list(geometry.coords)
            else:
                raise ValueError(
                    f"Unsupported geometry type for 2D flow area perimeter: {geom_type}"
                )
        else:
            raw_coords = list(coordinates)

        normalized = []
        for pair in raw_coords:
            if len(pair) < 2:
                raise ValueError("Each perimeter coordinate must contain at least x and y values")
            normalized.append((float(pair[0]), float(pair[1])))

        if len(normalized) < 3:
            raise ValueError("At least three perimeter vertices are required")

        if normalized[0] != normalized[-1]:
            normalized.append(normalized[0])

        unique_vertices = {(x_coord, y_coord) for x_coord, y_coord in normalized[:-1]}
        if len(unique_vertices) < 3:
            raise ValueError("2D flow area perimeter must contain at least three unique vertices")

        return normalized

    @staticmethod
    def _polygon_centroid(coords: List[tuple[float, float]]) -> tuple[float, float]:
        """Compute polygon centroid from a closed XY ring."""
        if coords[0] != coords[-1]:
            raise ValueError("Polygon centroid requires a closed coordinate ring")

        twice_area = 0.0
        centroid_x = 0.0
        centroid_y = 0.0

        for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
            cross = x0 * y1 - x1 * y0
            twice_area += cross
            centroid_x += (x0 + x1) * cross
            centroid_y += (y0 + y1) * cross

        if abs(twice_area) < 1e-12:
            xs = [x_coord for x_coord, _ in coords[:-1]]
            ys = [y_coord for _, y_coord in coords[:-1]]
            return sum(xs) / len(xs), sum(ys) / len(ys)

        area = twice_area / 2.0
        return centroid_x / (6.0 * area), centroid_y / (6.0 * area)

    @staticmethod
    def _format_scalar_value(value) -> str:
        """Format numeric/text values for keyword lines without forcing decimals."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "-1" if value else "0"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return f"{value:g}"
        return str(value).strip()

    @staticmethod
    def _normalize_point_generation_data(point_generation_data) -> Optional[str]:
        """Normalize point-generation settings to the 4-field raw HEC-RAS string."""
        if point_generation_data is None:
            return None

        if isinstance(point_generation_data, str):
            parts = [part.strip() for part in point_generation_data.split(',')]
        elif isinstance(point_generation_data, Sequence):
            parts = [
                "" if value is None else GeomStorage._format_scalar_value(value)
                for value in point_generation_data
            ]
        else:
            raise TypeError(
                "point_generation_data must be a comma-delimited string or a sequence"
            )

        if len(parts) > 4:
            raise ValueError("point_generation_data may contain at most four values")

        parts.extend([""] * (4 - len(parts)))
        return ",".join(parts[:4])

    @staticmethod
    def _build_2d_settings_lines(settings: dict) -> List[str]:
        """Render settings dict values into canonical 2D flow area keyword lines."""
        lines = []

        for keyword, column in GeomStorage._SETTINGS_KEYWORDS.items():
            value = settings.get(column)
            if value is None or pd.isna(value):
                continue
            lines.append(f"{keyword}={GeomStorage._format_scalar_value(value)}\n")

        for keyword, column in GeomStorage._BOOLEAN_KEYWORDS.items():
            if settings.get(column):
                lines.append(f"{keyword}=-1\n")

        return lines

    @staticmethod
    def _extract_block_keyword_value(
        block_lines: List[str],
        line_idx: Optional[int],
        keyword: str,
        default: str = "",
    ) -> str:
        """Read a keyword value from a block line when present."""
        if line_idx is None:
            return default
        value = GeomParser.extract_keyword_value(block_lines[line_idx], keyword)
        return value if value != "" else default

    @staticmethod
    def _parse_surface_line_coords(block_lines: List[str], info: dict) -> List[tuple[float, float]]:
        """Parse Storage Area Surface Line XY rows from a storage area block."""
        if info['surface_line_idx'] is None or info['surface_line_end'] is None:
            raise ValueError("Storage area block is missing a surface line section")

        values = []
        for line in block_lines[info['surface_line_idx'] + 1:info['surface_line_end']]:
            values.extend(
                GeomParser.parse_fixed_width(line, GeomStorage.SURFACE_LINE_COLUMN)
            )

        if len(values) % 2 != 0:
            raise ValueError("Surface line section contains an odd number of coordinate values")

        coords = []
        for idx in range(0, len(values), 2):
            coords.append((values[idx], values[idx + 1]))

        if len(coords) < 3:
            raise ValueError("Surface line section must contain at least three vertices")

        return coords

    @staticmethod
    def _storage_area_tail_start(info: dict, block_length: int) -> int:
        """Return the first line after the managed 2D flow area section."""
        if info['settings_end'] is not None:
            return info['settings_end']

        candidates = [
            info['points_time_idx'] + 1 if info['points_time_idx'] is not None else None,
            info['points_end'],
            info['points_idx'] + 1 if info['points_idx'] is not None else None,
            info['point_generation_idx'] + 1 if info['point_generation_idx'] is not None else None,
            info['is2d_line_idx'] + 1 if info['is2d_line_idx'] is not None else None,
            info['min_elev_line_idx'] + 1 if info['min_elev_line_idx'] is not None else None,
            info['area_line_idx'] + 1 if info['area_line_idx'] is not None else None,
            info['type_line_idx'] + 1 if info['type_line_idx'] is not None else None,
            info['surface_line_end'],
            info['surface_line_idx'] + 1 if info['surface_line_idx'] is not None else None,
        ]

        valid = [candidate for candidate in candidates if candidate is not None]
        if not valid:
            return min(block_length, 1)

        return min(block_length, max(valid))

    @staticmethod
    def _storage_area_insert_index(lines: List[str]) -> int:
        """Choose an insertion point for a new storage area block."""
        last_storage_end = None
        for _, end_idx, _ in GeomStorage._iter_storage_area_blocks(lines):
            last_storage_end = end_idx

        if last_storage_end is not None:
            return last_storage_end

        for idx, line in enumerate(lines):
            if line.startswith("River Reach="):
                return idx

        return len(lines)

    @staticmethod
    def _build_2d_flow_area_block(
        flow_area_name: str,
        coords: List[tuple[float, float]],
        settings: dict,
        *,
        centroid_x: float,
        centroid_y: float,
        raw_header_line: Optional[str] = None,
        type_value: str = "0",
        area_value: str = "",
        min_elev_value: str = "",
        prefix_lines: Optional[List[str]] = None,
        tail_lines: Optional[List[str]] = None,
        existing_points_lines: Optional[List[str]] = None,
        existing_points_time_line: Optional[str] = None,
    ) -> List[str]:
        """Build a canonical storage-area-backed 2D flow area block.

        When existing_points_lines and existing_points_time_line are provided
        (unchanged-perimeter path), the mesh data and timestamp are preserved.
        """
        normalized_settings = dict(GeomStorage._DEFAULT_2D_SETTINGS)
        normalized_settings.update(settings)

        point_generation_data = GeomStorage._normalize_point_generation_data(
            normalized_settings.get('point_generation_data')
        )
        if point_generation_data is None:
            point_generation_data = GeomStorage.DEFAULT_2D_POINT_GENERATION_DATA
        normalized_settings['point_generation_data'] = point_generation_data

        block_lines = [
            GeomStorage._format_storage_area_header(
                flow_area_name, centroid_x, centroid_y,
                raw_header_line=raw_header_line,
            ),
        ]
        if prefix_lines:
            block_lines.extend(prefix_lines)

        block_lines.append(f"Storage Area Surface Line= {len(coords)}\n")
        block_lines.extend(GeomStorage._format_surface_line_lines(coords))
        block_lines.append(f"Storage Area Type= {type_value or '0'}\n")
        block_lines.append(
            f"Storage Area Area={area_value}\n" if area_value else "Storage Area Area=\n"
        )
        block_lines.append(
            f"Storage Area Min Elev={min_elev_value}\n"
            if min_elev_value else
            "Storage Area Min Elev=\n"
        )
        block_lines.append("Storage Area Is2D=-1\n")
        block_lines.append(f"Storage Area Point Generation Data={point_generation_data}\n")

        if existing_points_lines is not None:
            block_lines.extend(existing_points_lines)
        else:
            block_lines.append("Storage Area 2D Points= 0\n")

        if existing_points_time_line is not None:
            time_line = existing_points_time_line
            if not time_line.endswith('\n'):
                time_line += '\n'
            block_lines.append(time_line)
        else:
            block_lines.append(
                f"Storage Area 2D PointsPerimeterTime={GeomStorage._current_timestamp()}\n"
            )

        block_lines.extend(GeomStorage._build_2d_settings_lines(normalized_settings))

        if tail_lines:
            if tail_lines[0].strip():
                block_lines.append("\n")
            block_lines.extend(tail_lines)
        else:
            block_lines.append("\n")

        return block_lines

    @staticmethod
    @log_call
    def get_storage_areas(geom_file: Union[str, Path],
                         exclude_2d: bool = True) -> pd.DataFrame:
        """
        Extract storage area metadata from geometry file.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            exclude_2d (bool): If True, exclude 2D flow areas (default True).
                2D flow areas are identified by having "Storage Area Is2D=" set to -1.

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Name (str): Storage area name
                - NumPoints (int): Number of elevation-volume points
                - MinElev (float): Minimum elevation in storage curve (if available)
                - MaxElev (float): Maximum elevation in storage curve (if available)
                - Is2D (bool): Whether this is a 2D flow area

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> # Get only traditional storage areas (exclude 2D)
            >>> storage_df = GeomStorage.get_storage_areas("model.g01", exclude_2d=True)
            >>> print(f"Found {len(storage_df)} storage areas")
            >>>
            >>> # Get all storage areas including 2D flow areas
            >>> all_storage = GeomStorage.get_storage_areas("model.g01", exclude_2d=False)
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            storage_areas = []
            i = 0

            while i < len(lines):
                line = lines[i]

                # Find Storage Area definition
                if line.startswith("Storage Area="):
                    value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                    # Storage Area format: Name,X,Y - extract just the name
                    parts = [p.strip() for p in value_str.split(',')]
                    sa_name = parts[0] if parts else value_str

                    # Look for elevation-volume count and 2D flag
                    num_points = 0
                    min_elev = None
                    max_elev = None
                    is_2d = False

                    # Search until next storage area (surface line data can span many lines)
                    for j in range(i+1, len(lines)):
                        # Stop at next storage area or section
                        if lines[j].startswith("Storage Area=") or lines[j].startswith("River Reach="):
                            break

                        # Check if this is a 2D flow area
                        if lines[j].startswith("Storage Area Is2D="):
                            is2d_str = GeomParser.extract_keyword_value(lines[j], "Storage Area Is2D")
                            try:
                                is_2d = int(is2d_str.strip()) == -1
                            except ValueError:
                                pass

                        # Check for elevation-volume data (two keyword variants exist)
                        elev_vol_keyword = None
                        if lines[j].startswith("Storage Area Elev Volume="):
                            elev_vol_keyword = "Storage Area Elev Volume"
                        elif lines[j].startswith("Storage Area Vol Elev="):
                            elev_vol_keyword = "Storage Area Vol Elev"

                        if elev_vol_keyword:
                            count_str = GeomParser.extract_keyword_value(lines[j], elev_vol_keyword)
                            try:
                                num_points = int(count_str.strip())
                            except ValueError:
                                pass

                            # Parse first and last elevation values
                            if num_points > 0:
                                values = []
                                k = j + 1
                                total_needed = num_points * 2
                                while len(values) < total_needed and k < len(lines):
                                    if '=' in lines[k]:
                                        break
                                    parsed = GeomParser.parse_fixed_width(lines[k], GeomStorage.FIXED_WIDTH_COLUMN)
                                    values.extend(parsed)
                                    k += 1

                                if len(values) >= 2:
                                    # Elevations are at even indices (0, 2, 4, ...)
                                    elevations = values[0::2]
                                    if elevations:
                                        min_elev = elevations[0]
                                        max_elev = elevations[-1] if len(elevations) > 1 else elevations[0]

                    storage_areas.append({
                        'Name': sa_name,
                        'NumPoints': num_points,
                        'MinElev': min_elev,
                        'MaxElev': max_elev,
                        'Is2D': is_2d
                    })

                i += 1

            df = pd.DataFrame(storage_areas)

            # Filter out 2D flow areas if requested
            if exclude_2d and not df.empty and 'Is2D' in df.columns:
                original_count = len(df)
                df = df[~df['Is2D']].reset_index(drop=True)
                if original_count != len(df):
                    logger.debug(f"Excluded {original_count - len(df)} 2D flow areas")

            logger.debug(f"Found {len(df)} storage areas in {geom_file.name}")
            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading storage areas: {str(e)}")
            raise IOError(f"Failed to read storage areas: {str(e)}")

    @staticmethod
    @log_call
    def get_elevation_volume(geom_file: Union[str, Path],
                            storage_name: str) -> pd.DataFrame:
        """
        Extract elevation-volume curve for a storage area.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            storage_name (str): Storage area name (case-sensitive)

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Elevation (float): Storage elevation (ft or m)
                - Volume (float): Storage volume at elevation (acre-ft or m³)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If storage area not found

        Example:
            >>> elev_vol = GeomStorage.get_elevation_volume("model.g01", "Reservoir Pool 1")
            >>> print(f"Storage curve has {len(elev_vol)} points")
            >>> print(f"Elevation range: {elev_vol['Elevation'].min():.1f} to {elev_vol['Elevation'].max():.1f}")
            >>> print(f"Max volume: {elev_vol['Volume'].max():,.0f} acre-ft")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the storage area
            sa_idx = None
            for i, line in enumerate(lines):
                if line.startswith("Storage Area="):
                    value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                    # Storage Area format: Name,X,Y - extract just the name
                    parts = [p.strip() for p in value_str.split(',')]
                    sa_name = parts[0] if parts else value_str
                    if sa_name == storage_name:
                        sa_idx = i
                        break

            if sa_idx is None:
                raise ValueError(f"Storage area not found: {storage_name}")

            # Find elevation-volume data (two keyword variants exist)
            # Search until next storage area (surface line data can span many lines)
            for j in range(sa_idx+1, len(lines)):
                # Stop at next storage area
                if lines[j].startswith("Storage Area="):
                    break

                elev_vol_keyword = None
                if lines[j].startswith("Storage Area Elev Volume="):
                    elev_vol_keyword = "Storage Area Elev Volume"
                elif lines[j].startswith("Storage Area Vol Elev="):
                    elev_vol_keyword = "Storage Area Vol Elev"

                if elev_vol_keyword:
                    count_str = GeomParser.extract_keyword_value(lines[j], elev_vol_keyword)
                    count = int(count_str.strip())

                    # Parse elevation-volume pairs
                    total_values = count * 2
                    values = []
                    k = j + 1
                    while len(values) < total_values and k < len(lines):
                        if '=' in lines[k]:
                            break
                        parsed = GeomParser.parse_fixed_width(lines[k], GeomStorage.FIXED_WIDTH_COLUMN)
                        values.extend(parsed)
                        k += 1

                    # Split into elevations and volumes
                    elevations = values[0::2]
                    volumes = values[1::2]

                    df = pd.DataFrame({
                        'Elevation': elevations[:count],
                        'Volume': volumes[:count]
                    })

                    logger.info(f"Extracted {len(df)} elevation-volume points for {storage_name}")
                    return df

            raise ValueError(f"Elevation-volume data not found for {storage_name}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading elevation-volume: {str(e)}")
            raise IOError(f"Failed to read elevation-volume: {str(e)}")

    @staticmethod
    @log_call
    def set_elevation_volume(geom_file: Union[str, Path],
                            storage_name: str,
                            elevations: List[float],
                            volumes: List[float],
                            create_backup: bool = True) -> Path:
        """
        Write elevation-volume curve for a storage area to geometry file.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            storage_name (str): Storage area name (case-sensitive, must exist)
            elevations (List[float]): List of elevation values (must be ascending)
            volumes (List[float]): List of volume values (same length as elevations)
            create_backup (bool): If True, create .bak backup before modification (default True)

        Returns:
            Path: Path to backup file if created, or geometry file path if no backup

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If storage area not found, or if elevations/volumes invalid

        Example:
            >>> # Modify an existing storage curve
            >>> backup = GeomStorage.set_elevation_volume(
            ...     "model.g01", "Reservoir Pool 1",
            ...     elevations=[1200.0, 1210.0, 1220.0, 1230.0],
            ...     volumes=[0.0, 500.0, 1500.0, 3500.0]
            ... )
            >>> print(f"Backup created: {backup}")

            >>> # Modify without backup (not recommended)
            >>> GeomStorage.set_elevation_volume(
            ...     "model.g01", "Reservoir Pool 1",
            ...     elevations=[1200.0, 1220.0],
            ...     volumes=[0.0, 1000.0],
            ...     create_backup=False
            ... )

        Notes:
            - Elevations must be in ascending order
            - Lengths of elevations and volumes must match
            - Creates .bak backup by default (strongly recommended)
            - Supports both "Storage Area Elev Volume=" and "Storage Area Vol Elev=" keywords
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Validate inputs
        if len(elevations) != len(volumes):
            raise ValueError(
                f"Elevations and volumes must have same length: "
                f"{len(elevations)} != {len(volumes)}"
            )

        if len(elevations) < 2:
            raise ValueError("At least 2 elevation-volume points are required")

        # Check elevations are ascending
        for i in range(1, len(elevations)):
            if elevations[i] <= elevations[i-1]:
                raise ValueError(
                    f"Elevations must be strictly ascending: "
                    f"{elevations[i-1]} >= {elevations[i]} at index {i}"
                )

        # Create backup if requested
        backup_path = None
        if create_backup:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the storage area
            sa_idx = None
            for i, line in enumerate(lines):
                if line.startswith("Storage Area="):
                    value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                    # Storage Area format: Name,X,Y - extract just the name
                    parts = [p.strip() for p in value_str.split(',')]
                    sa_name = parts[0] if parts else value_str
                    if sa_name == storage_name:
                        sa_idx = i
                        break

            if sa_idx is None:
                raise ValueError(f"Storage area not found: {storage_name}")

            # Find the elevation-volume data line and data extent
            elev_vol_line_idx = None
            data_start_idx = None
            data_end_idx = None
            elev_vol_keyword = None

            # Search until next storage area (surface line data can span many lines)
            for j in range(sa_idx + 1, len(lines)):
                # Stop at next storage area
                if lines[j].startswith("Storage Area="):
                    break

                # Check for elevation-volume keyword line
                if lines[j].startswith("Storage Area Elev Volume="):
                    elev_vol_keyword = "Storage Area Elev Volume"
                    elev_vol_line_idx = j
                    data_start_idx = j + 1
                elif lines[j].startswith("Storage Area Vol Elev="):
                    elev_vol_keyword = "Storage Area Vol Elev"
                    elev_vol_line_idx = j
                    data_start_idx = j + 1

                if elev_vol_line_idx is not None and data_start_idx is not None:
                    # Find end of data (next keyword line or next storage area)
                    for k in range(data_start_idx, len(lines)):
                        if '=' in lines[k]:
                            data_end_idx = k
                            break
                    if data_end_idx is None:
                        data_end_idx = len(lines)
                    break

            if elev_vol_line_idx is None:
                raise ValueError(f"Elevation-volume data not found for {storage_name}")

            # Format new data
            # Interleave elevations and volumes: elev1, vol1, elev2, vol2, ...
            interleaved = []
            for elev, vol in zip(elevations, volumes):
                interleaved.append(elev)
                interleaved.append(vol)

            # Format as fixed-width lines
            new_data_lines = GeomParser.format_fixed_width(
                interleaved,
                column_width=GeomStorage.FIXED_WIDTH_COLUMN,
                values_per_line=GeomStorage.VALUES_PER_LINE,
                precision=2
            )

            # Create new keyword line with updated count
            new_keyword_line = f"{elev_vol_keyword}= {len(elevations)} \n"

            # Build modified file content
            new_lines = (
                lines[:elev_vol_line_idx] +
                [new_keyword_line] +
                new_data_lines +
                lines[data_end_idx:]
            )

            # Write modified file
            with open(geom_file, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            logger.info(
                f"Updated elevation-volume curve for {storage_name}: "
                f"{len(elevations)} points"
            )

            return backup_path if backup_path else geom_file

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing elevation-volume: {str(e)}")
            raise IOError(f"Failed to write elevation-volume: {str(e)}")

    @staticmethod
    @log_call
    def get_storage_area_polygons(
        geom_file: Union[str, Path],
        exclude_2d: bool = True
    ) -> "GeoDataFrame":
        """
        Extract storage area polygon perimeter geometry from plain text geometry file.

        Parses the ``Storage Area Surface Line= N`` block to build a Shapely
        Polygon from the N 16-char fixed-width XY pairs that follow it.

        Parameters:
            geom_file: Path to .g## geometry file
            exclude_2d: If True, exclude 2D flow areas identified by
                ``Storage Area Is2D= -1`` (default True)

        Returns:
            GeoDataFrame with columns:
                - Name (str): Storage area name
                - geometry (Polygon): Perimeter polygon in project CRS
                - centroid_x (float): SA centroid X coordinate
                - centroid_y (float): SA centroid Y coordinate
                - is_2d (bool): Whether this is a 2D flow area

        Raises:
            FileNotFoundError: If geometry file doesn't exist

        Example:
            >>> sa_polygons = GeomStorage.get_storage_area_polygons("model.g01")
            >>> print(f"Found {len(sa_polygons)} storage area polygons")
            >>> for _, row in sa_polygons.iterrows():
            ...     coords = list(row.geometry.exterior.coords)
            ...     print(f"  {row['Name']}: {len(coords)-1} vertices")
        """
        import geopandas as gpd
        from shapely.geometry import Polygon as ShapelyPolygon

        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        def _parse_surface_line_coords(lines, start_idx, count):
            """Parse N XY pairs from Storage Area Surface Line data."""
            vertices = []
            for k in range(start_idx, start_idx + count):
                if k >= len(lines):
                    break
                line = lines[k].rstrip('\n')
                # Primary: 16-char fixed-width (standard HEC-RAS format, no separator)
                try:
                    x = float(line[0:16])
                    y = float(line[16:32])
                except (ValueError, IndexError):
                    # Fallback: space-separated (rare variant)
                    parts = line.split()
                    if len(parts) >= 2:
                        x, y = float(parts[0]), float(parts[1])
                    else:
                        continue  # skip malformed line
                vertices.append((x, y))
            return vertices

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            records = []
            i = 0
            while i < len(lines):
                line = lines[i]

                if line.startswith("Storage Area="):
                    value_str = GeomParser.extract_keyword_value(line, "Storage Area")
                    # Format: Name,centroid_X,centroid_Y
                    parts = [p.strip() for p in value_str.split(',')]
                    sa_name = parts[0] if parts else value_str
                    try:
                        centroid_x = float(parts[1]) if len(parts) > 1 else None
                        centroid_y = float(parts[2]) if len(parts) > 2 else None
                    except ValueError:
                        centroid_x = None
                        centroid_y = None

                    # Scan entire SA block FIRST to record both Surface Line index
                    # and Is2D flag before processing any coordinates.
                    # Is2D= may appear AFTER Surface Line= in the file.
                    surface_line_idx = None
                    surface_line_count = 0
                    is_2d = False

                    for j in range(i + 1, len(lines)):
                        if (lines[j].startswith("Storage Area=") or
                                lines[j].startswith("River Reach=")):
                            break
                        if lines[j].startswith("Storage Area Surface Line="):
                            try:
                                count_str = GeomParser.extract_keyword_value(
                                    lines[j], "Storage Area Surface Line"
                                )
                                surface_line_count = int(count_str.strip())
                                surface_line_idx = j + 1
                            except ValueError:
                                pass
                        if lines[j].startswith("Storage Area Is2D="):
                            try:
                                is2d_str = GeomParser.extract_keyword_value(
                                    lines[j], "Storage Area Is2D"
                                )
                                is_2d = int(is2d_str.strip()) == -1
                            except ValueError:
                                pass

                    # Now parse coordinates if we found a surface line
                    polygon = None
                    if surface_line_idx is not None and surface_line_count > 0:
                        vertices = _parse_surface_line_coords(
                            lines, surface_line_idx, surface_line_count
                        )
                        if len(vertices) >= 3:
                            try:
                                polygon = ShapelyPolygon(vertices)
                            except Exception as poly_err:
                                logger.warning(
                                    f"Could not create polygon for '{sa_name}': {poly_err}"
                                )

                    records.append({
                        'Name': sa_name,
                        'geometry': polygon,
                        'centroid_x': centroid_x,
                        'centroid_y': centroid_y,
                        'is_2d': is_2d,
                    })

                i += 1

            if not records:
                return gpd.GeoDataFrame(
                    columns=['Name', 'geometry', 'centroid_x', 'centroid_y', 'is_2d'],
                    geometry='geometry'
                )

            gdf = gpd.GeoDataFrame(records, geometry='geometry')

            if exclude_2d and not gdf.empty:
                original_count = len(gdf)
                gdf = gdf[~gdf['is_2d']].reset_index(drop=True)
                if original_count != len(gdf):
                    logger.debug(f"Excluded {original_count - len(gdf)} 2D flow areas")

            # Drop entries without valid polygon geometry
            valid_mask = gdf['geometry'].notna()
            if not valid_mask.all():
                dropped = (~valid_mask).sum()
                logger.warning(
                    f"Dropped {dropped} storage areas with no polygon geometry"
                )
                gdf = gdf[valid_mask].reset_index(drop=True)

            logger.debug(f"Found {len(gdf)} storage area polygons in {geom_file.name}")
            return gdf

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error reading storage area polygons: {str(e)}")
            raise IOError(f"Failed to read storage area polygons: {str(e)}")

    @staticmethod
    @log_call
    def get_2d_flow_area_settings(geom_file: Union[str, Path]) -> pd.DataFrame:
        """Read 2D flow area settings from storage-area-backed .g## blocks."""
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        records = []
        for _, _, block_lines in GeomStorage._iter_storage_area_blocks(lines):
            info = GeomStorage._inspect_storage_area_block(block_lines)
            if not info['is_2d']:
                continue

            settings = dict(info['settings'])
            if settings.get('point_generation_data') is None:
                settings['point_generation_data'] = (
                    info['point_generation_data'] or
                    GeomStorage.DEFAULT_2D_POINT_GENERATION_DATA
                )

            records.append({
                'name': info['header']['name'],
                **settings,
            })

        columns = [
            'name',
            'mannings_n',
            'spatially_varied_mann_on_faces',
            'composite_classification',
            'cell_vol_tol',
            'cell_min_area_fraction',
            'face_profile_tol',
            'face_area_tol',
            'face_conv_ratio',
            'laminar_depth',
            'min_face_length_ratio',
            'point_generation_data',
        ]

        df = pd.DataFrame(records, columns=columns)
        logger.debug(f"Found {len(df)} 2D flow area settings in {geom_file.name}")
        return df

    @staticmethod
    def _coords_match(coords_a: List[tuple[float, float]], coords_b: List[tuple[float, float]]) -> bool:
        """Return True if two closed coordinate rings are identical within float tolerance."""
        if len(coords_a) != len(coords_b):
            return False
        return all(
            abs(ax - bx) < 1e-6 and abs(ay - by) < 1e-6
            for (ax, ay), (bx, by) in zip(coords_a, coords_b)
        )

    @staticmethod
    @log_call
    def set_2d_flow_area_perimeter(
        geom_file: Union[str, Path],
        flow_area_name: str,
        coordinates: Optional[Sequence[Sequence[float]]] = None,
        geometry=None,
        point_generation_data: Optional[Union[str, Sequence[Optional[float]]]] = None,
        recompute_centroid: bool = False,
        create_backup: bool = True,
    ) -> Path:
        """Create or update a storage-area-backed 2D flow area perimeter in .g## text.

        Args:
            recompute_centroid: When updating an existing block, recompute the
                header centroid from the polygon. Default False preserves the
                original header coordinates.
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        GeomStorage._validate_flow_area_name(flow_area_name)

        coords = GeomStorage._normalize_perimeter_coords(
            coordinates=coordinates,
            geometry=geometry,
        )
        centroid_x, centroid_y = GeomStorage._polygon_centroid(coords)
        normalized_point_generation_data = GeomStorage._normalize_point_generation_data(
            point_generation_data
        )

        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        backup_path = None
        if create_backup:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

        existing_block = GeomStorage._find_storage_area_block(lines, flow_area_name)

        if existing_block is None:
            settings = dict(GeomStorage._DEFAULT_2D_SETTINGS)
            settings['point_generation_data'] = (
                normalized_point_generation_data or
                GeomStorage.DEFAULT_2D_POINT_GENERATION_DATA
            )
            new_block_lines = GeomStorage._build_2d_flow_area_block(
                flow_area_name,
                coords,
                settings,
                centroid_x=centroid_x,
                centroid_y=centroid_y,
            )
            insert_idx = GeomStorage._storage_area_insert_index(lines)
            new_lines = lines[:insert_idx] + new_block_lines + lines[insert_idx:]
        else:
            start_idx, end_idx, block_lines = existing_block
            info = GeomStorage._inspect_storage_area_block(block_lines)

            if info['is2d_line_idx'] is not None and not info['is_2d']:
                raise ValueError(
                    f"Existing storage area '{flow_area_name}' is not marked as a 2D flow area"
                )

            # Check if perimeter is unchanged — preserve mesh data if so
            perimeter_changed = True
            existing_points_lines = None
            existing_points_time_line = None
            try:
                existing_coords = GeomStorage._parse_surface_line_coords(block_lines, info)
                if GeomStorage._coords_match(coords, existing_coords):
                    perimeter_changed = False
            except ValueError:
                pass

            if not perimeter_changed:
                if info['points_idx'] is not None:
                    pts_end = info.get('points_end') or (info['points_idx'] + 1)
                    existing_points_lines = block_lines[info['points_idx']:pts_end]
                if info['points_time_idx'] is not None:
                    existing_points_time_line = block_lines[info['points_time_idx']]

            settings = dict(info['settings'])
            settings['point_generation_data'] = (
                normalized_point_generation_data or
                info['point_generation_data'] or
                settings.get('point_generation_data') or
                GeomStorage.DEFAULT_2D_POINT_GENERATION_DATA
            )

            managed_indices = [
                idx for idx in [
                    info['surface_line_idx'],
                    info['type_line_idx'],
                    info['area_line_idx'],
                    info['min_elev_line_idx'],
                    info['is2d_line_idx'],
                    info['point_generation_idx'],
                    info['points_idx'],
                    info['points_time_idx'],
                    info['settings_start'],
                ]
                if idx is not None
            ]
            prefix_end = min(managed_indices) if managed_indices else len(block_lines)
            prefix_lines = block_lines[1:prefix_end]
            tail_start = GeomStorage._storage_area_tail_start(info, len(block_lines))
            tail_lines = block_lines[tail_start:]

            raw_header = None if recompute_centroid else block_lines[0]
            header_cx = centroid_x if recompute_centroid else info['header'].get('centroid_x', centroid_x)
            header_cy = centroid_y if recompute_centroid else info['header'].get('centroid_y', centroid_y)

            new_block_lines = GeomStorage._build_2d_flow_area_block(
                flow_area_name,
                coords,
                settings,
                centroid_x=header_cx,
                centroid_y=header_cy,
                raw_header_line=raw_header,
                type_value=GeomStorage._extract_block_keyword_value(
                    block_lines, info['type_line_idx'], "Storage Area Type", "0"
                ),
                area_value=GeomStorage._extract_block_keyword_value(
                    block_lines, info['area_line_idx'], "Storage Area Area", ""
                ),
                min_elev_value=GeomStorage._extract_block_keyword_value(
                    block_lines, info['min_elev_line_idx'], "Storage Area Min Elev", ""
                ),
                prefix_lines=prefix_lines,
                tail_lines=tail_lines,
                existing_points_lines=existing_points_lines,
                existing_points_time_line=existing_points_time_line,
            )
            new_lines = lines[:start_idx] + new_block_lines + lines[end_idx:]

        with open(geom_file, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        logger.info(
            f"Upserted 2D flow area perimeter for {flow_area_name}: "
            f"{len(coords) - 1} unique edges"
        )
        return backup_path if backup_path else geom_file

    @staticmethod
    @log_call
    def set_2d_flow_area_settings(
        geom_file: Union[str, Path],
        flow_area_name: str,
        spatially_varied_mann_on_faces: Optional[bool] = None,
        composite_classification: Optional[bool] = None,
        mannings_n: Optional[float] = None,
        cell_vol_tol: Optional[float] = None,
        cell_min_area_fraction: Optional[float] = None,
        face_profile_tol: Optional[float] = None,
        face_area_tol: Optional[float] = None,
        face_conv_ratio: Optional[float] = None,
        laminar_depth: Optional[float] = None,
        min_face_length_ratio: Optional[float] = None,
        point_generation_data: Optional[Union[str, Sequence[Optional[float]]]] = None,
        create_backup: bool = True,
    ) -> Path:
        """Update 2D flow area text settings without making HDF the edit target."""
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        GeomStorage._validate_flow_area_name(flow_area_name)

        updates = {
            'spatially_varied_mann_on_faces': spatially_varied_mann_on_faces,
            'composite_classification': composite_classification,
            'mannings_n': mannings_n,
            'cell_vol_tol': cell_vol_tol,
            'cell_min_area_fraction': cell_min_area_fraction,
            'face_profile_tol': face_profile_tol,
            'face_area_tol': face_area_tol,
            'face_conv_ratio': face_conv_ratio,
            'laminar_depth': laminar_depth,
            'min_face_length_ratio': min_face_length_ratio,
            'point_generation_data': point_generation_data,
        }

        if all(value is None for value in updates.values()):
            logger.info("No 2D flow area settings changes requested")
            return geom_file

        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        existing_block = GeomStorage._find_storage_area_block(lines, flow_area_name)
        if existing_block is None:
            raise ValueError(f"Flow area not found: {flow_area_name}")

        start_idx, end_idx, block_lines = existing_block
        info = GeomStorage._inspect_storage_area_block(block_lines)
        if not info['is_2d']:
            raise ValueError(f"'{flow_area_name}' is not a 2D flow area")

        normalized_settings = dict(info['settings'])
        for key, value in updates.items():
            if value is None:
                continue
            if key == 'point_generation_data':
                normalized_settings[key] = GeomStorage._normalize_point_generation_data(value)
            else:
                normalized_settings[key] = value

        if normalized_settings.get('point_generation_data') is None:
            normalized_settings['point_generation_data'] = (
                info['point_generation_data'] or
                GeomStorage.DEFAULT_2D_POINT_GENERATION_DATA
            )

        updated_block_lines = list(block_lines)

        point_generation_line = (
            "Storage Area Point Generation Data="
            f"{normalized_settings['point_generation_data']}\n"
        )
        if info['point_generation_idx'] is not None:
            updated_block_lines[info['point_generation_idx']] = point_generation_line
        else:
            point_insert_candidates = [
                info['points_idx'],
                info['points_time_idx'],
                info['settings_start'],
                info['is2d_line_idx'] + 1 if info['is2d_line_idx'] is not None else None,
                info['min_elev_line_idx'] + 1 if info['min_elev_line_idx'] is not None else None,
                info['area_line_idx'] + 1 if info['area_line_idx'] is not None else None,
                info['type_line_idx'] + 1 if info['type_line_idx'] is not None else None,
                len(updated_block_lines),
            ]
            point_insert_idx = min(
                candidate for candidate in point_insert_candidates if candidate is not None
            )
            updated_block_lines.insert(point_insert_idx, point_generation_line)

        updated_info = GeomStorage._inspect_storage_area_block(updated_block_lines)
        settings_lines = GeomStorage._build_2d_settings_lines(normalized_settings)

        if updated_info['settings_start'] is not None:
            updated_block_lines = (
                updated_block_lines[:updated_info['settings_start']] +
                settings_lines +
                updated_block_lines[updated_info['settings_end']:]
            )
        else:
            settings_insert_idx = GeomStorage._storage_area_tail_start(
                updated_info,
                len(updated_block_lines),
            )
            updated_block_lines = (
                updated_block_lines[:settings_insert_idx] +
                settings_lines +
                updated_block_lines[settings_insert_idx:]
            )

        backup_path = None
        if create_backup:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

        new_lines = lines[:start_idx] + updated_block_lines + lines[end_idx:]
        with open(geom_file, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        logger.info(f"Updated 2D flow area settings for {flow_area_name}")
        return backup_path if backup_path else geom_file

    BREAKLINE_VALUES_PER_LINE = 4

    @staticmethod
    def _format_breakline_coord_lines(coords: List[tuple]) -> List[str]:
        """Format polyline XY pairs for BreakLine Polyline blocks.

        Uses 16-char right-justified fields with 4 values per line
        (2 coordinate pairs per line), matching HEC-RAS breakline format.
        """
        col_w = GeomStorage.SURFACE_LINE_COLUMN
        vpl = GeomStorage.BREAKLINE_VALUES_PER_LINE
        lines = []
        flat_values = []
        for x_coord, y_coord in coords:
            flat_values.extend([x_coord, y_coord])

        for i in range(0, len(flat_values), vpl):
            row_values = flat_values[i:i + vpl]
            parts = []
            for val in row_values:
                prec = GeomStorage._max_precision_for_field(val, col_w)
                parts.append(f"{val:{col_w}.{prec}f}")
            lines.append("".join(parts) + "\n")

        return lines

    @staticmethod
    def _format_breakline_block(
        name: str,
        coords: List[tuple],
        cell_size_near: Optional[float] = None,
        cell_size_far: Optional[float] = None,
    ) -> List[str]:
        """Build a complete breakline text block as a list of lines."""
        block = [f"BreakLine Name={name}\n"]
        block.append(
            f"BreakLine CellSize Min={cell_size_near}\n"
            if cell_size_near is not None
            else "BreakLine CellSize Min=\n"
        )
        block.append(
            f"BreakLine CellSize Max={cell_size_far}\n"
            if cell_size_far is not None
            else "BreakLine CellSize Max=\n"
        )
        block.append("BreakLine Near Repeats=0\n")
        block.append("BreakLine Protection Radius=0\n")
        block.append(f"BreakLine Polyline= {len(coords)} \n")
        block.extend(GeomStorage._format_breakline_coord_lines(coords))
        return block

    @staticmethod
    @log_call
    def set_breaklines(
        geom_file: Union[str, Path],
        flow_area_name: str,
        breaklines: List[dict],
        create_backup: bool = True,
    ) -> Path:
        """Write breakline blocks into a .g## for a 2D flow area.

        Each dict in *breaklines* must have:
            name (str): breakline display name (unpadded).
            coords (list[tuple[float,float]]): polyline vertices.
            cell_size_near (float|None): BreakLine CellSize Min value.
            cell_size_far (float|None): BreakLine CellSize Max value.

        Breaklines are inserted after the storage-area block for
        *flow_area_name* and before BC Line / Connection / LCMann blocks.
        Any existing breakline blocks are preserved (new ones are appended).

        Returns the backup path if *create_backup* is True, else *geom_file*.
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        GeomStorage._validate_flow_area_name(flow_area_name)

        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        existing_block = GeomStorage._find_storage_area_block(lines, flow_area_name)
        if existing_block is None:
            raise ValueError(f"Flow area not found: {flow_area_name}")

        _, end_idx, _ = existing_block

        insert_idx = end_idx
        for i in range(end_idx, len(lines)):
            line = lines[i]
            if any(line.startswith(t) for t in (
                "BC Line Name=", "Connection=", "LCMann Time=",
                "Storage Area=", "River Reach=",
            )):
                insert_idx = i
                break
            if line.startswith("BreakLine Name="):
                insert_idx = i
                break
        else:
            insert_idx = len(lines)

        new_blocks = []
        for bl in breaklines:
            new_blocks.extend(GeomStorage._format_breakline_block(
                name=bl["name"],
                coords=bl["coords"],
                cell_size_near=bl.get("cell_size_near"),
                cell_size_far=bl.get("cell_size_far"),
            ))

        backup_path = None
        if create_backup:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

        new_lines = lines[:insert_idx] + new_blocks + lines[insert_idx:]
        with open(geom_file, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        logger.info(
            "Inserted %d breaklines for %s into %s",
            len(breaklines), flow_area_name, geom_file.name,
        )
        return backup_path if backup_path else geom_file
