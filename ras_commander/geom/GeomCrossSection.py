"""
GeomCrossSection - 1D Cross section operations for HEC-RAS geometry files

This module provides comprehensive functionality for reading and modifying
HEC-RAS 1D cross section data in plain text geometry files (.g##).

All methods are static and designed to be used without instantiation.

List of Functions:
- get_cross_sections() - Extract all cross section metadata
- get_station_elevation() - Read station/elevation pairs for a cross section
- set_station_elevation() - Write station/elevation with automatic bank interpolation
- get_bank_stations() - Read left and right bank station locations
- set_bank_stations() - Write left and right bank station locations
- get_expansion_contraction() - Read expansion and contraction coefficients
- set_expansion_contraction() - Write expansion and contraction coefficients
- get_blocked_obstructions() - Read blocked obstruction triplets
- set_blocked_obstructions() - Write blocked obstruction triplets
- validate_blocked_obstructions_hdf() - Cross-check text obstruction blocks against HDF flags
- interpolate_station_elevation() - Interpolate between two station/elevation profiles
- interpolate_cross_section() - Read two cross sections and interpolate a reviewable profile
- get_mannings_n() - Read Manning's roughness values with LOB/Channel/ROB classification
- get_levees() - Read left/right levee station-elevation points
- set_levees() - Write left/right levee station-elevation points
- get_ineffective_flow() - Read ineffective flow area triplets (left_sta, right_sta, elevation)
- set_ineffective_flow() - Write corrected ineffective flow area data
- set_mannings_n() - Write Manning's n breakpoints (station, n_value triplets)
- get_xs_coords() - Extract XYZ coordinates combining cut line geometry with station/elevation data

Example Usage:
    >>> from ras_commander import GeomCrossSection
    >>> from pathlib import Path
    >>>
    >>> # List all cross sections
    >>> geom_file = Path("BaldEagle.g01")
    >>> xs_df = GeomCrossSection.get_cross_sections(geom_file)
    >>> print(f"Found {len(xs_df)} cross sections")
    >>>
    >>> # Get station/elevation for specific XS
    >>> sta_elev = GeomCrossSection.get_station_elevation(
    ...     geom_file, "Bald Eagle Creek", "Reach 1", "138154.4"
    ... )
    >>> print(sta_elev.head())
    >>>
    >>> # Modify and write back
    >>> sta_elev['Elevation'] += 1.0  # Raise XS by 1 foot
    >>> GeomCrossSection.set_station_elevation(
    ...     geom_file, "Bald Eagle Creek", "Reach 1", "138154.4", sta_elev
    ... )

Technical Notes:
    - Uses FORTRAN-era fixed-width format (8-char columns for numeric data)
    - Count interpretation: "#Sta/Elev= 40" means 40 PAIRS (80 total values)
    - Always creates .bak backup before modification
"""

from pathlib import Path
from numbers import Number
from typing import Union, Optional, List, Tuple, Any
import pandas as pd
import numpy as np
import math

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomCrossSection:
    """
    Operations for parsing and modifying HEC-RAS 1D cross sections.

    All methods are static and designed to be used without instantiation.
    """

    # HEC-RAS format constants
    FIXED_WIDTH_COLUMN = 8      # Character width for numeric data in geometry files
    VALUES_PER_LINE = 10        # Number of values per line in fixed-width format
    BLOCKED_OBSTRUCTION_VALUES_PER_LINE = 9  # 3 obstructions x 3 values
    MAX_XS_POINTS = 500         # HEC-RAS computational limit on cross section points

    # Parsing constants
    MAX_PARSE_LINES = 100       # Safety limit on lines to parse for data blocks
    BLOCKED_OBSTRUCTION_KEYWORD = "#Block Obstruct="
    BLOCKED_OBSTRUCTION_COLUMNS = ["xs_id", "start_sta", "end_sta", "elevation"]
    BLOCKED_OBSTRUCTION_TERMINATORS = (
        "Bank Sta=",
        "#XS Ineff=",
        "#Mann=",
        "XS Rating Curve=",
        "XS HTab",
        "Exp/Cntr=",
    )

    # ========== PRIVATE HELPER METHODS ==========

    @staticmethod
    def _find_cross_section(lines: List[str], river: str, reach: str, rs: str) -> Optional[int]:
        """
        Find cross section in geometry file and return starting line index.

        Args:
            lines: File lines (from readlines())
            river: River name (case-sensitive)
            reach: Reach name (case-sensitive)
            rs: River station (as string, e.g., "138154.4")

        Returns:
            Line index where "Type RM Length L Ch R =" for matching XS starts,
            or None if not found
        """
        current_river = None
        current_reach = None

        for i, line in enumerate(lines):
            # Track current river/reach
            if line.startswith("River Reach="):
                values = GeomParser.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]

            # Find matching cross section
            elif line.startswith("Type RM Length L Ch R ="):
                value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
                values = [v.strip() for v in value_str.split(',')]

                if len(values) > 1:
                    # Format: Type, RS, Length_L, Length_Ch, Length_R
                    xs_rs = values[1]  # RS is second value

                    if (current_river == river and
                        current_reach == reach and
                        xs_rs == rs):
                        logger.debug(f"Found XS at line {i}: {river}/{reach}/RS {rs}")
                        return i

        logger.debug(f"XS not found: {river}/{reach}/RS {rs}")
        return None

    @staticmethod
    def _find_xs_section_end(lines: List[str], xs_idx: int) -> int:
        """
        Find the end of the current cross section block in geometry file lines.

        A cross section block ends at the FIRST occurrence (after xs_idx) of:
        - "Type RM Length L Ch R =" (next XS header)
        - "River Reach=" (new river/reach)
        - End of file

        Args:
            lines: File lines (from readlines())
            xs_idx: Starting index of the current XS (Type RM Length L Ch R = line)

        Returns:
            Line index of the first line PAST the current XS section
            (i.e., the start of the next section, or len(lines) if at end)
        """
        for i in range(xs_idx + 1, len(lines)):
            line = lines[i]
            if line.startswith("Type RM Length L Ch R ="):
                return i
            if line.startswith("River Reach="):
                return i
        return len(lines)

    @staticmethod
    def _read_bank_stations(lines: List[str], start_idx: int) -> Optional[Tuple[float, float]]:
        """
        Read bank stations from XS block starting at start_idx.

        Args:
            lines: File lines (from readlines())
            start_idx: Index to start searching (typically from _find_cross_section)

        Returns:
            (left_bank, right_bank) tuple or None if no banks defined
        """
        section_end = GeomCrossSection._find_xs_section_end(lines, start_idx)

        for k in range(start_idx, section_end):
            if lines[k].startswith("Bank Sta="):
                bank_str = GeomParser.extract_keyword_value(lines[k], "Bank Sta")
                bank_values = [v.strip() for v in bank_str.split(',')]
                if len(bank_values) >= 2:
                    left_bank = float(bank_values[0])
                    right_bank = float(bank_values[1])
                    logger.debug(f"Read bank stations: {left_bank}, {right_bank}")
                    return (left_bank, right_bank)

        return None

    @staticmethod
    def _parse_data_block(lines: List[str], start_idx: int, expected_count: int,
                         column_width: Optional[int] = None,
                         max_lines: Optional[int] = None) -> List[float]:
        """
        Parse fixed-width numeric data block following a count keyword.

        Args:
            lines: File lines (from readlines())
            start_idx: Index to start parsing (typically count_line + 1)
            expected_count: Number of values to read
            column_width: Character width of each column (default: FIXED_WIDTH_COLUMN)
            max_lines: Safety limit on lines to read (default: MAX_PARSE_LINES)

        Returns:
            List of parsed float values
        """
        if column_width is None:
            column_width = GeomCrossSection.FIXED_WIDTH_COLUMN
        if max_lines is None:
            max_lines = GeomCrossSection.MAX_PARSE_LINES

        values = []
        line_idx = start_idx

        while len(values) < expected_count and line_idx < len(lines):
            # Stop if hit next keyword
            if lines[line_idx].strip() and lines[line_idx].strip()[0].isupper():
                if '=' in lines[line_idx]:
                    break

            parsed = GeomParser.parse_fixed_width(lines[line_idx], column_width=column_width)
            values.extend(parsed)
            line_idx += 1

            # Safety check
            if line_idx > start_idx + max_lines:
                logger.warning(f"Exceeded max lines ({max_lines}) while parsing data block")
                break

        return values

    @staticmethod
    def _parse_paired_data(lines: List[str], start_idx: int, count: int,
                          col1_name: str = 'Station',
                          col2_name: str = 'Elevation') -> pd.DataFrame:
        """
        Parse paired data (station/elevation, elevation/volume, etc.) into DataFrame.

        Args:
            lines: File lines (from readlines())
            start_idx: Index to start parsing (typically count_line + 1)
            count: Number of PAIRS (not total values)
            col1_name: Name for first column (default: 'Station')
            col2_name: Name for second column (default: 'Elevation')

        Returns:
            DataFrame with two columns
        """
        total_values = count * 2
        values = GeomCrossSection._parse_data_block(lines, start_idx, total_values)

        if len(values) != total_values:
            logger.warning(f"Expected {total_values} values, got {len(values)}")

        # Split into pairs
        col1_data = values[0::2]  # Every other value starting at 0
        col2_data = values[1::2]  # Every other value starting at 1

        return pd.DataFrame({col1_name: col1_data, col2_name: col2_data})

    @staticmethod
    def _interpolate_at_banks(sta_elev_df: pd.DataFrame,
                             bank_left: Optional[float] = None,
                             bank_right: Optional[float] = None,
                             tolerance: float = 0.005) -> pd.DataFrame:
        """
        Interpolate elevation at bank stations and insert into station/elevation data.

        HEC-RAS REQUIRES that bank station values appear as exact points in the
        station/elevation data. This method ensures banks are interpolated and inserted.

        If an existing station is within tolerance of a bank station, its station
        value is snapped to the exact bank value (avoiding near-duplicate points).
        Otherwise, a new point is interpolated and inserted.

        Args:
            sta_elev_df: Station/elevation data
            bank_left: Left bank station
            bank_right: Right bank station
            tolerance: Snap tolerance for matching existing stations (default 0.005)

        Returns:
            Modified DataFrame with banks interpolated and inserted
        """
        result_df = sta_elev_df.copy()
        result_df['Station'] = pd.to_numeric(result_df['Station'], errors='raise')
        result_df['Elevation'] = pd.to_numeric(result_df['Elevation'], errors='raise')
        result_df = result_df.sort_values('Station').reset_index(drop=True)

        if result_df['Station'].duplicated().any():
            raise ValueError("Station values must be unique")

        for bank_sta, label in [(bank_left, "left"), (bank_right, "right")]:
            if bank_sta is None:
                continue

            bank_sta = float(bank_sta)
            stations = result_df['Station'].values
            min_station = float(stations[0])
            max_station = float(stations[-1])

            if bank_sta < min_station - tolerance or bank_sta > max_station + tolerance:
                raise ValueError(
                    f"{label.title()} bank station ({bank_sta}) must be within "
                    f"station/elevation range {min_station:g} to {max_station:g}"
                )

            # Check for near-match within tolerance
            diffs = np.abs(stations - bank_sta)
            min_idx = np.argmin(diffs)

            if diffs[min_idx] <= tolerance:
                # Snap existing station to exact bank value
                old_sta = stations[min_idx]
                result_df.iloc[min_idx, result_df.columns.get_loc('Station')] = bank_sta
                logger.debug(
                    f"Snapped {label} bank station {old_sta} -> {bank_sta} "
                    f"(diff={diffs[min_idx]:.6f})"
                )
            else:
                # Interpolate elevation at bank station and insert new point
                elevations = result_df['Elevation'].values
                bank_elev = np.interp(bank_sta, stations, elevations)

                new_row = pd.DataFrame({'Station': [bank_sta], 'Elevation': [bank_elev]})
                result_df = pd.concat([result_df, new_row], ignore_index=True)
                result_df = result_df.sort_values('Station').reset_index(drop=True)

                logger.debug(
                    f"Interpolated {label} bank at station {bank_sta:.2f}, "
                    f"elevation {bank_elev:.2f}"
                )

        return result_df

    @staticmethod
    def _format_numeric(value: float) -> str:
        """Format a geometry-line scalar compactly without losing useful precision."""
        value = float(value)
        if value.is_integer():
            return str(int(value))
        return f"{value:g}"

    @staticmethod
    def _format_numeric_like(value: float, original: str, min_decimals: int = 0) -> str:
        """Format a scalar using the decimal precision of an existing value string."""
        original = original.strip()
        if '.' in original:
            decimals = max(len(original.split('.', 1)[1]), int(min_decimals))
            return f"{float(value):.{decimals}f}"
        return GeomCrossSection._format_numeric(value)

    @staticmethod
    def _decimal_places_for_value(value: float) -> int:
        """Return decimal places needed by the compact formatter for a scalar."""
        text = GeomCrossSection._format_numeric(value)
        if 'e' in text.lower():
            text = f"{float(value):.12f}".rstrip('0').rstrip('.')
        if '.' not in text:
            return 0
        return len(text.split('.', 1)[1].rstrip('0'))

    @staticmethod
    def _find_keyword_index(lines: List[str], start_idx: int, keyword: str) -> Optional[int]:
        """Find a keyword line inside one cross-section block."""
        section_end = GeomCrossSection._find_xs_section_end(lines, start_idx)
        for idx in range(start_idx, section_end):
            if lines[idx].startswith(keyword):
                return idx
        return None

    @staticmethod
    def _resolve_geom_text_path(
        geom_number: Union[str, Number, Path],
        ras_object=None,
    ) -> Path:
        """Resolve a geometry number or direct path to a ``.g##`` text file."""
        candidate = None
        if isinstance(geom_number, Path):
            candidate = geom_number
        elif isinstance(geom_number, str):
            candidate = Path(geom_number)

        if candidate is not None and candidate.is_file():
            return candidate

        try:
            from ..RasPlan import RasPlan
            resolved = RasPlan.get_geom_path(geom_number, ras_object=ras_object)
            if resolved is not None and Path(resolved).is_file():
                return Path(resolved)
        except Exception as exc:
            logger.debug(f"Could not resolve geometry input via RasPlan: {exc}")

        raise FileNotFoundError(f"Geometry file not found for: {geom_number}")

    @staticmethod
    def _make_xs_id(river: str, reach: str, rs: str) -> str:
        """Build the stable cross-section identifier returned by obstruction APIs."""
        return f"{str(river).strip()}|{str(reach).strip()}|{str(rs).strip()}"

    @staticmethod
    def _resolve_xs_identifier(xs_id: Any, xs_df: pd.DataFrame) -> Tuple[str, str, str]:
        """
        Resolve a public ``xs_id`` value to ``(river, reach, rs)``.

        Accepts the ``xs_id`` string returned by ``get_blocked_obstructions()``,
        a plain RS string when unique in the geometry, a tuple/list
        ``(river, reach, rs)``, or a mapping/Series with River/Reach/RS fields.
        """
        if isinstance(xs_id, pd.Series):
            xs_id = xs_id.to_dict()

        if isinstance(xs_id, dict):
            if "xs_id" in xs_id:
                return GeomCrossSection._resolve_xs_identifier(xs_id["xs_id"], xs_df)
            river = xs_id.get("River", xs_id.get("river"))
            reach = xs_id.get("Reach", xs_id.get("reach"))
            rs = xs_id.get("RS", xs_id.get("rs", xs_id.get("station")))
            if river is not None and reach is not None and rs is not None:
                return str(river), str(reach), str(rs)

        if isinstance(xs_id, (tuple, list)) and len(xs_id) == 3:
            river, reach, rs = xs_id
            return str(river), str(reach), str(rs)

        xs_text = str(xs_id).strip()
        if "|" in xs_text:
            parts = [part.strip() for part in xs_text.split("|")]
            if len(parts) == 3 and all(parts):
                return parts[0], parts[1], parts[2]

        if xs_df.empty:
            raise ValueError(f"Cross section not found: {xs_id}")

        matches = xs_df[xs_df["RS"].astype(str).str.strip() == xs_text]
        if matches.empty:
            raise ValueError(f"Cross section not found: {xs_id}")
        if len(matches) > 1:
            raise ValueError(
                f"Cross section RS '{xs_text}' is not unique; pass the xs_id "
                "returned by get_blocked_obstructions() or a (river, reach, rs) tuple"
            )

        row = matches.iloc[0]
        return str(row["River"]), str(row["Reach"]), str(row["RS"])

    @staticmethod
    def _find_blocked_obstruction_block(
        lines: List[str],
        xs_idx: int,
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Find a ``#Block Obstruct=`` block inside one cross section.

        Returns ``(header_idx, data_start, data_end, count)`` where ``data_end``
        is the first line after the fixed-width obstruction data.
        """
        section_end = GeomCrossSection._find_xs_section_end(lines, xs_idx)

        for idx in range(xs_idx, section_end):
            if not lines[idx].strip().startswith(GeomCrossSection.BLOCKED_OBSTRUCTION_KEYWORD):
                continue

            value_str = GeomParser.extract_keyword_value(lines[idx], "#Block Obstruct")
            try:
                count = int(str(value_str).split(",", 1)[0].strip())
            except ValueError as exc:
                raise ValueError(f"Invalid #Block Obstruct count at line {idx + 1}") from exc

            data_start = idx + 1
            data_end = section_end
            for data_idx in range(data_start, section_end):
                stripped = lines[data_idx].strip()
                if stripped.startswith(GeomCrossSection.BLOCKED_OBSTRUCTION_TERMINATORS):
                    data_end = data_idx
                    break
                if stripped.startswith("Type RM Length L Ch R =") or stripped.startswith("River Reach="):
                    data_end = data_idx
                    break

            return idx, data_start, data_end, count

        return None

    @staticmethod
    def _blocked_obstruction_insert_index(lines: List[str], xs_idx: int) -> int:
        """Choose a safe insertion point for a new blocked-obstruction block."""
        section_end = GeomCrossSection._find_xs_section_end(lines, xs_idx)
        for idx in range(xs_idx, section_end):
            if lines[idx].strip().startswith(GeomCrossSection.BLOCKED_OBSTRUCTION_TERMINATORS):
                return idx
        return section_end

    @staticmethod
    def _format_blocked_obstruction_value(value: float) -> str:
        """Format one blocked-obstruction scalar into an 8-character field."""
        text = f"{float(value):.2f}"
        if len(text) > GeomCrossSection.FIXED_WIDTH_COLUMN:
            return "*" * GeomCrossSection.FIXED_WIDTH_COLUMN
        return text.rjust(GeomCrossSection.FIXED_WIDTH_COLUMN)

    @staticmethod
    def _normalize_blocked_obstructions(obstructions: Any) -> List[Any]:
        """Normalize obstruction-like input to ``BlockedObstruction`` objects."""
        from ..fixit.obstructions import BlockedObstruction

        if obstructions is None:
            return []

        normalized = []

        if isinstance(obstructions, pd.DataFrame):
            column_map = {
                "start_sta": "start_sta",
                "Start Sta": "start_sta",
                "start_station": "start_sta",
                "left_station": "start_sta",
                "end_sta": "end_sta",
                "End Sta": "end_sta",
                "end_station": "end_sta",
                "right_station": "end_sta",
                "elevation": "elevation",
                "Elevation": "elevation",
            }
            renamed = obstructions.rename(
                columns={col: column_map[col] for col in obstructions.columns if col in column_map}
            )
            required = {"start_sta", "end_sta", "elevation"}
            missing = required - set(renamed.columns)
            if missing:
                raise ValueError(
                    "obstructions DataFrame must contain start_sta, end_sta, "
                    f"and elevation columns; missing {sorted(missing)}"
                )

            for _, row in renamed.iterrows():
                normalized.append(
                    BlockedObstruction(
                        start_sta=float(row["start_sta"]),
                        end_sta=float(row["end_sta"]),
                        elevation=float(row["elevation"]),
                    )
                )
            return normalized

        if isinstance(obstructions, BlockedObstruction):
            return [obstructions]

        if isinstance(obstructions, dict):
            obstructions = [obstructions]

        elif all(
            hasattr(obstructions, attr)
            for attr in ("start_sta", "end_sta", "elevation")
        ):
            obstructions = [obstructions]

        for obs in obstructions:
            if isinstance(obs, BlockedObstruction):
                normalized.append(obs)
            elif isinstance(obs, dict):
                normalized.append(
                    BlockedObstruction(
                        start_sta=float(obs.get("start_sta", obs.get("left_station"))),
                        end_sta=float(obs.get("end_sta", obs.get("right_station"))),
                        elevation=float(obs["elevation"]),
                    )
                )
            elif all(hasattr(obs, attr) for attr in ("start_sta", "end_sta", "elevation")):
                normalized.append(
                    BlockedObstruction(
                        start_sta=float(obs.start_sta),
                        end_sta=float(obs.end_sta),
                        elevation=float(obs.elevation),
                    )
                )
            else:
                start_sta, end_sta, elevation = obs
                normalized.append(
                    BlockedObstruction(
                        start_sta=float(start_sta),
                        end_sta=float(end_sta),
                        elevation=float(elevation),
                    )
                )

        return normalized

    @staticmethod
    def _insert_xs_keyword_line(lines: List[str],
                                xs_idx: int,
                                new_line: str,
                                prefer_after: Optional[List[str]] = None,
                                prefer_before: Optional[List[str]] = None) -> int:
        """
        Insert a cross-section keyword line without splitting fixed-width data blocks.

        The caller can prefer inserting after simple one-line keywords or before
        count/data keywords. If no anchor is found, the line is appended to the
        end of the cross-section block.
        """
        section_end = GeomCrossSection._find_xs_section_end(lines, xs_idx)

        if prefer_after:
            for keyword in prefer_after:
                for idx in range(xs_idx, section_end):
                    if lines[idx].startswith(keyword):
                        lines.insert(idx + 1, new_line)
                        return idx + 1

        if prefer_before:
            for keyword in prefer_before:
                for idx in range(xs_idx, section_end):
                    if lines[idx].startswith(keyword):
                        lines.insert(idx, new_line)
                        return idx

        lines.insert(section_end, new_line)
        return section_end

    @staticmethod
    def _bank_station_line(bank_left: float,
                           bank_right: float,
                           existing_line: Optional[str] = None) -> str:
        """Build a Bank Sta= line, preserving existing precision when available."""
        if existing_line:
            existing = GeomParser.extract_keyword_value(existing_line, "Bank Sta")
            existing_vals = [v.strip() for v in existing.split(',')]
            if len(existing_vals) >= 2:
                left = GeomCrossSection._format_numeric_like(bank_left, existing_vals[0])
                right = GeomCrossSection._format_numeric_like(bank_right, existing_vals[1])
                return f"Bank Sta={left},{right}\n"

        return (
            f"Bank Sta={GeomCrossSection._format_numeric(bank_left)},"
            f"{GeomCrossSection._format_numeric(bank_right)}\n"
        )

    @staticmethod
    def _exp_cntr_line(expansion: float,
                       contraction: float,
                       existing_line: Optional[str] = None) -> str:
        """Build an Exp/Cntr= line, preserving existing precision when available."""
        if existing_line:
            existing = GeomParser.extract_keyword_value(existing_line, "Exp/Cntr")
            existing_vals = [v.strip() for v in existing.split(',')]
            if len(existing_vals) >= 2:
                exp = GeomCrossSection._format_numeric_like(
                    expansion,
                    existing_vals[0],
                    min_decimals=GeomCrossSection._decimal_places_for_value(expansion)
                )
                cntr = GeomCrossSection._format_numeric_like(
                    contraction,
                    existing_vals[1],
                    min_decimals=GeomCrossSection._decimal_places_for_value(contraction)
                )
                return f"Exp/Cntr={exp},{cntr}\n"

        return (
            f"Exp/Cntr={GeomCrossSection._format_numeric(expansion)},"
            f"{GeomCrossSection._format_numeric(contraction)}\n"
        )


    @staticmethod
    def _is_missing_number(value) -> bool:
        """Return True for scalar missing numeric inputs."""
        if value is None:
            return True
        try:
            return bool(pd.isna(value))
        except TypeError:
            return False

    @staticmethod
    def _parse_levee_line(line: str) -> Tuple[float, float, float, float]:
        """
        Parse a HEC-RAS cross-section Levee= line.

        The observed XS format is:
        ``Levee=<left_flag>,<left_sta>,<left_elev>,<right_flag>,<right_sta>,<right_elev>,,``.
        A flag of ``-1`` means active; ``0`` or blank means the side is absent.
        """
        value_str = GeomParser.extract_keyword_value(line, "Levee")
        values = [v.strip() for v in value_str.split(',')]
        values.extend([''] * (8 - len(values)))

        def parse_side(flag_idx: int, sta_idx: int, elev_idx: int) -> Tuple[float, float]:
            flag = values[flag_idx]
            if not flag or flag == '0':
                return (math.nan, math.nan)

            station = values[sta_idx]
            elevation = values[elev_idx]
            if not station:
                return (math.nan, math.nan)

            return (float(station), float(elevation) if elevation else math.nan)

        left_station, left_elevation = parse_side(0, 1, 2)
        right_station, right_elevation = parse_side(3, 4, 5)
        return left_station, left_elevation, right_station, right_elevation

    @staticmethod
    def _levee_line(left_station: Optional[float] = None,
                    left_elevation: Optional[float] = None,
                    right_station: Optional[float] = None,
                    right_elevation: Optional[float] = None,
                    existing_line: Optional[str] = None) -> str:
        """Build a Levee= line, preserving existing numeric precision when possible."""
        existing_vals = []
        if existing_line:
            existing = GeomParser.extract_keyword_value(existing_line, "Levee")
            existing_vals = [v.strip() for v in existing.split(',')]
        existing_vals.extend([''] * (8 - len(existing_vals)))

        def format_value(value: float, original: str) -> str:
            min_decimals = GeomCrossSection._decimal_places_for_value(float(value))
            if original:
                return GeomCrossSection._format_numeric_like(
                    value,
                    original,
                    min_decimals=min_decimals
                )
            return GeomCrossSection._format_numeric(value)

        def side_tokens(station, elevation, sta_idx: int, elev_idx: int) -> List[str]:
            station_missing = GeomCrossSection._is_missing_number(station)
            elevation_missing = GeomCrossSection._is_missing_number(elevation)
            if station_missing and elevation_missing:
                return ['0', '', '']
            if station_missing:
                raise ValueError("Levee elevation requires a station")
            sta_str = format_value(float(station), existing_vals[sta_idx])
            elev_str = format_value(float(elevation), existing_vals[elev_idx]) if not elevation_missing else ''
            return ['-1', sta_str, elev_str]

        values = (
            side_tokens(left_station, left_elevation, 1, 2)
            + side_tokens(right_station, right_elevation, 4, 5)
            + ['', '']
        )
        return f"Levee={','.join(values)}\n"

    @staticmethod
    def _find_mann_block_end(lines: List[str], xs_idx: int) -> Optional[int]:
        """Return the insertion index immediately after the #Mann= data block."""
        section_end = GeomCrossSection._find_xs_section_end(lines, xs_idx)

        for idx in range(xs_idx, section_end):
            if lines[idx].startswith("#Mann="):
                value_str = GeomParser.extract_keyword_value(lines[idx], "#Mann")
                parts = [p.strip() for p in value_str.split(',')]
                count = int(parts[0]) if parts and parts[0] else 0
                total_values = count * 3
                data_lines = math.ceil(total_values / GeomCrossSection.VALUES_PER_LINE)
                return min(idx + 1 + data_lines, section_end)

        return None

    @staticmethod
    def _prepare_station_elevation_df(sta_elev_df: pd.DataFrame,
                                      label: str = "sta_elev_df") -> pd.DataFrame:
        """Validate and normalize station/elevation input for interpolation."""
        if not isinstance(sta_elev_df, pd.DataFrame):
            raise ValueError(f"{label} must be a pandas DataFrame")
        if 'Station' not in sta_elev_df.columns or 'Elevation' not in sta_elev_df.columns:
            raise ValueError(f"{label} must have 'Station' and 'Elevation' columns")
        if len(sta_elev_df) < 2:
            raise ValueError(f"{label} must contain at least two points")

        df = sta_elev_df[['Station', 'Elevation']].copy()
        df['Station'] = pd.to_numeric(df['Station'], errors='raise')
        df['Elevation'] = pd.to_numeric(df['Elevation'], errors='raise')
        df = df.sort_values('Station').reset_index(drop=True)

        if df['Station'].duplicated().any():
            raise ValueError(f"{label} contains duplicate Station values")
        if float(df['Station'].iloc[0]) == float(df['Station'].iloc[-1]):
            raise ValueError(f"{label} station range must be greater than zero")

        return df

    @staticmethod
    def _station_fractions(stations: np.ndarray) -> np.ndarray:
        """Map station values to normalized lateral fractions from 0 to 1."""
        station_min = float(stations[0])
        station_max = float(stations[-1])
        return (stations - station_min) / (station_max - station_min)

    # ========== PUBLIC API METHODS ==========

    @staticmethod
    @log_call
    def get_cross_sections(geom_file: Union[str, Path],
                          river: Optional[str] = None,
                          reach: Optional[str] = None) -> pd.DataFrame:
        """
        Extract cross section metadata from geometry file.

        Parses all cross sections and returns their metadata including
        river, reach, river station, type, and reach lengths.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (Optional[str]): Filter by specific river name. If None, returns all rivers.
            reach (Optional[str]): Filter by specific reach name. If None, returns all reaches.
                                  Note: If reach is specified, river must also be specified.

        Returns:
            pd.DataFrame: DataFrame with columns:
                - River (str): River name
                - Reach (str): Reach name
                - RS (str): River station
                - Type (int): Cross section type (1=natural, etc.)
                - Length_Left (float): Left overbank length to next XS
                - Length_Channel (float): Channel length to next XS
                - Length_Right (float): Right overbank length to next XS
                - NodeName (str): Node name (if specified)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If reach specified without river

        Example:
            >>> # Get all cross sections
            >>> xs_df = GeomCrossSection.get_cross_sections("BaldEagle.g01")
            >>> print(f"Total XS: {len(xs_df)}")
            >>>
            >>> # Filter by river
            >>> xs_df = GeomCrossSection.get_cross_sections("BaldEagle.g01", river="Bald Eagle Creek")
            >>>
            >>> # Filter by river and reach
            >>> xs_df = GeomCrossSection.get_cross_sections("BaldEagle.g01",
            ...                                        river="Bald Eagle Creek",
            ...                                        reach="Reach 1")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if reach is not None and river is None:
            raise ValueError("If reach is specified, river must also be specified")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            cross_sections = []
            current_river = None
            current_reach = None

            i = 0
            while i < len(lines):
                line = lines[i].strip()

                # Track current river/reach
                if line.startswith("River Reach="):
                    values = GeomParser.extract_comma_list(lines[i], "River Reach")
                    if len(values) >= 2:
                        current_river = values[0]
                        current_reach = values[1]
                        logger.debug(f"Parsing {current_river} / {current_reach}")

                # Parse cross section metadata
                elif line.startswith("Type RM Length L Ch R ="):
                    if current_river is None or current_reach is None:
                        logger.warning(f"Found XS without river/reach at line {i}")
                        i += 1
                        continue

                    # Parse the metadata line
                    # Format: "Type RM Length L Ch R = TYPE, RS, Length_L, Length_Ch, Length_R"
                    value_str = GeomParser.extract_keyword_value(lines[i], "Type RM Length L Ch R")
                    values = [v.strip() for v in value_str.split(',')]

                    if len(values) >= 4:
                        xs_type_code = int(values[0]) if values[0] else 1
                        rs = values[1]  # RS is second value, not first
                        try:
                            node_name = ""

                            # Look ahead for Node Name
                            j = i + 1
                            while j < len(lines) and j < i + 10:  # Look ahead max 10 lines
                                next_line = lines[j].strip()
                                if next_line.startswith("Node Name="):
                                    node_name = GeomParser.extract_keyword_value(lines[j], "Node Name")
                                if next_line.startswith("Type RM Length") or next_line.startswith("River Reach="):
                                    break
                                j += 1

                            # Use the type code we already extracted
                            xs_type = xs_type_code

                            # Lengths are values[2], values[3], values[4]
                            length_left = float(values[2]) if len(values) > 2 and values[2] else 0.0
                            length_channel = float(values[3]) if len(values) > 3 and values[3] else 0.0
                            length_right = float(values[4]) if len(values) > 4 and values[4] else 0.0

                            # Apply filters
                            if river is not None and current_river != river:
                                i += 1
                                continue
                            if reach is not None and current_reach != reach:
                                i += 1
                                continue

                            cross_sections.append({
                                'River': current_river,
                                'Reach': current_reach,
                                'RS': rs,
                                'Type': xs_type,
                                'Length_Left': length_left,
                                'Length_Channel': length_channel,
                                'Length_Right': length_right,
                                'NodeName': node_name
                            })

                        except (ValueError, IndexError) as e:
                            logger.warning(f"Error parsing XS at line {i}: {e}")

                i += 1

            df = pd.DataFrame(cross_sections)
            logger.debug(f"Extracted {len(df)} cross sections from {geom_file.name}")

            if river is not None:
                logger.debug(f"Filtered to river '{river}': {len(df)} cross sections")
            if reach is not None:
                logger.debug(f"Filtered to reach '{reach}': {len(df)} cross sections")

            return df

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error extracting cross sections: {str(e)}")
            raise IOError(f"Failed to extract cross sections: {str(e)}")

    @staticmethod
    @log_call
    def parse_blocked_obstructions(data_lines: List[str], expected_count: int) -> List[Any]:
        """
        Parse blocked obstruction fixed-width data into obstruction objects.

        ``#Block Obstruct=`` data is stored in 8-character columns as
        ``start_sta, end_sta, elevation`` triplets, with up to three
        obstructions per line.

        Parameters:
            data_lines: Fixed-width data lines following ``#Block Obstruct=``.
            expected_count: Obstruction count declared in the header.

        Returns:
            List of ``BlockedObstruction`` objects.
        """
        from ..fixit.obstructions import BlockedObstruction

        expected_count = int(expected_count)
        if expected_count <= 0:
            return []

        values = []
        for line in data_lines:
            for idx in range(0, len(line.rstrip("\n\r")), GeomCrossSection.FIXED_WIDTH_COLUMN):
                token = line[idx:idx + GeomCrossSection.FIXED_WIDTH_COLUMN].strip()
                if not token:
                    continue
                try:
                    values.append(float(token))
                except ValueError:
                    logger.debug(f"Skipping non-numeric blocked obstruction token: {token!r}")

        parsed_count = len(values) // 3
        if parsed_count < expected_count:
            logger.warning(
                f"Expected {expected_count} blocked obstructions, parsed {parsed_count}"
            )
        elif parsed_count > expected_count:
            logger.debug(
                f"Parsed {parsed_count} blocked obstruction triplets; using header count "
                f"{expected_count}"
            )

        obstructions = []
        for idx in range(min(parsed_count, expected_count)):
            value_idx = idx * 3
            obstructions.append(
                BlockedObstruction(
                    start_sta=values[value_idx],
                    end_sta=values[value_idx + 1],
                    elevation=values[value_idx + 2],
                )
            )

        return obstructions

    @staticmethod
    @log_call
    def format_blocked_obstructions(obstructions: Any) -> List[str]:
        """
        Format blocked obstructions for a HEC-RAS geometry text file.

        Values are written as 8-character fixed-width fields with 9 values per
        line, matching three ``start_sta, end_sta, elevation`` triplets per
        line. Lines include trailing newlines and are ready for ``writelines``.
        """
        normalized = GeomCrossSection._normalize_blocked_obstructions(obstructions)

        values = []
        for obs in normalized:
            values.extend([obs.start_sta, obs.end_sta, obs.elevation])

        lines = []
        for idx in range(0, len(values), GeomCrossSection.BLOCKED_OBSTRUCTION_VALUES_PER_LINE):
            row_values = values[idx:idx + GeomCrossSection.BLOCKED_OBSTRUCTION_VALUES_PER_LINE]
            line = "".join(
                GeomCrossSection._format_blocked_obstruction_value(value)
                for value in row_values
            )
            lines.append(line + "\n")

        return lines

    @staticmethod
    @log_call
    def get_blocked_obstructions(
        geom_number: Union[str, Number, Path],
        xs_id: Optional[Any] = None,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        Read blocked obstruction triplets from one or all cross sections.

        Parameters:
            geom_number: Geometry number (``"01"`` or ``1``) or direct path to
                a ``.g##`` text geometry file.
            xs_id: Optional cross-section identifier. Accepts the ``xs_id``
                returned by this method, a unique RS string, ``(river, reach,
                rs)``, or a mapping with River/Reach/RS fields.
            ras_object: Optional ``RasPrj`` instance for geometry-number
                resolution.

        Returns:
            DataFrame with at least ``xs_id``, ``start_sta``, ``end_sta``, and
            ``elevation`` columns. River, Reach, RS, and obstruction_index are
            included for review and unambiguous round trips.
        """
        geom_file = GeomCrossSection._resolve_geom_text_path(
            geom_number,
            ras_object=ras_object,
        )

        with open(geom_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        xs_df = GeomCrossSection.get_cross_sections(geom_file)
        if xs_id is not None:
            river, reach, rs = GeomCrossSection._resolve_xs_identifier(xs_id, xs_df)
            xs_df = xs_df[
                (xs_df["River"].astype(str) == river)
                & (xs_df["Reach"].astype(str) == reach)
                & (xs_df["RS"].astype(str) == rs)
            ]

        rows = []
        for _, xs_row in xs_df.iterrows():
            river = str(xs_row["River"])
            reach = str(xs_row["Reach"])
            rs = str(xs_row["RS"])
            section_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)
            if section_idx is None:
                continue

            block = GeomCrossSection._find_blocked_obstruction_block(lines, section_idx)
            if block is None:
                continue

            _, data_start, data_end, count = block
            data_lines = [line for line in lines[data_start:data_end] if line.strip()]
            obstructions = GeomCrossSection.parse_blocked_obstructions(data_lines, count)
            current_xs_id = GeomCrossSection._make_xs_id(river, reach, rs)

            for obs_idx, obs in enumerate(obstructions):
                rows.append({
                    "xs_id": current_xs_id,
                    "River": river,
                    "Reach": reach,
                    "RS": rs,
                    "obstruction_index": obs_idx,
                    "start_sta": obs.start_sta,
                    "end_sta": obs.end_sta,
                    "elevation": obs.elevation,
                })

        columns = [
            "xs_id",
            "River",
            "Reach",
            "RS",
            "obstruction_index",
            "start_sta",
            "end_sta",
            "elevation",
        ]
        return pd.DataFrame(rows, columns=columns)

    @staticmethod
    @log_call
    def set_blocked_obstructions(
        geom_number: Union[str, Number, Path],
        xs_id: Any,
        obstructions: Any,
        create_backup: bool = True,
        ras_object=None,
    ) -> Optional[Path]:
        """
        Write blocked obstruction triplets to a cross section.

        Parameters:
            geom_number: Geometry number (``"01"`` or ``1``) or direct path to
                a ``.g##`` text geometry file.
            xs_id: Cross-section identifier from ``get_blocked_obstructions()``,
                a unique RS string, ``(river, reach, rs)``, or a mapping with
                River/Reach/RS fields.
            obstructions: DataFrame/list containing ``start_sta``, ``end_sta``,
                and ``elevation`` values, or ``BlockedObstruction`` objects.
            create_backup: Whether to create a ``.bak`` backup before writing.
            ras_object: Optional ``RasPrj`` instance for geometry-number
                resolution.

        Returns:
            Optional backup path if ``create_backup=True`` and the file changed.
        """
        geom_file = GeomCrossSection._resolve_geom_text_path(
            geom_number,
            ras_object=ras_object,
        )
        normalized = GeomCrossSection._normalize_blocked_obstructions(obstructions)

        with open(geom_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        xs_df = GeomCrossSection.get_cross_sections(geom_file)
        river, reach, rs = GeomCrossSection._resolve_xs_identifier(xs_id, xs_df)
        xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)
        if xs_idx is None:
            raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

        block = GeomCrossSection._find_blocked_obstruction_block(lines, xs_idx)
        new_count = len(normalized)

        if block is None and new_count == 0:
            logger.info(
                f"No blocked obstruction block to clear for {river}/{reach}/RS {rs}"
            )
            return None

        modified_lines = lines.copy()
        if block is not None:
            header_idx, _, data_end, _ = block
            if new_count == 0:
                modified_lines = modified_lines[:header_idx] + modified_lines[data_end:]
            else:
                new_lines = (
                    [f"#Block Obstruct= {new_count}\n"]
                    + GeomCrossSection.format_blocked_obstructions(normalized)
                )
                modified_lines = (
                    modified_lines[:header_idx]
                    + new_lines
                    + modified_lines[data_end:]
                )
        else:
            insert_idx = GeomCrossSection._blocked_obstruction_insert_index(
                modified_lines,
                xs_idx,
            )
            new_lines = (
                [f"#Block Obstruct= {new_count}\n"]
                + GeomCrossSection.format_blocked_obstructions(normalized)
            )
            modified_lines = (
                modified_lines[:insert_idx]
                + new_lines
                + modified_lines[insert_idx:]
            )

        backup_path = GeomParser.safe_write_geometry(
            geom_file,
            modified_lines,
            create_backup=create_backup,
        )

        logger.info(
            f"Updated blocked obstructions for {river}/{reach}/RS {rs}: "
            f"{new_count} obstructions written"
        )
        return backup_path

    @staticmethod
    @log_call
    def validate_blocked_obstructions_hdf(
        geom_number: Union[str, Number, Path],
        hdf_path: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        Cross-check text ``#Block Obstruct=`` data against HDF block-mode flags.

        The geometry HDF exposes ``Obstr Block Mode`` as a cross-section
        attribute. That flag does not contain the obstruction triplets, so this
        validation compares per-cross-section text obstruction presence/count
        with whether the HDF flag indicates blocked-obstruction mode.

        Parameters:
            geom_number: Geometry number or direct ``.g##`` text path.
            hdf_path: Optional explicit geometry HDF path. If omitted,
                ``<geom_file>.hdf`` is used.
            ras_object: Optional ``RasPrj`` instance for geometry-number
                resolution.

        Returns:
            DataFrame with one row per text geometry cross section and a
            ``matches_hdf`` boolean.
        """
        geom_file = GeomCrossSection._resolve_geom_text_path(
            geom_number,
            ras_object=ras_object,
        )
        if hdf_path is None:
            hdf_file = Path(str(geom_file) + ".hdf")
        else:
            hdf_file = Path(hdf_path)
        if not hdf_file.exists():
            raise FileNotFoundError(f"Geometry HDF file not found: {hdf_file}")

        xs_df = GeomCrossSection.get_cross_sections(geom_file)
        validation = xs_df[["River", "Reach", "RS"]].copy()
        validation["xs_id"] = validation.apply(
            lambda row: GeomCrossSection._make_xs_id(row["River"], row["Reach"], row["RS"]),
            axis=1,
        )

        obs_df = GeomCrossSection.get_blocked_obstructions(
            geom_file,
            ras_object=ras_object,
        )
        counts = (
            obs_df.groupby("xs_id")
            .size()
            .rename("text_obstruction_count")
            .reset_index()
        )
        validation = validation.merge(
            counts,
            on="xs_id",
            how="left",
        )
        validation["text_obstruction_count"] = (
            validation["text_obstruction_count"].fillna(0).astype(int)
        )
        validation["text_has_blocked_obstructions"] = (
            validation["text_obstruction_count"] > 0
        )

        from ..hdf.HdfXsec import HdfXsec
        hdf_df = HdfXsec.get_cross_sections(hdf_file, ras_object=ras_object)
        if hdf_df.empty:
            validation["hdf_obstr_block_mode"] = pd.NA
            validation["hdf_has_blocked_obstructions"] = pd.NA
            validation["matches_hdf"] = False
            return validation[
                [
                    "xs_id",
                    "River",
                    "Reach",
                    "RS",
                    "text_obstruction_count",
                    "text_has_blocked_obstructions",
                    "hdf_obstr_block_mode",
                    "hdf_has_blocked_obstructions",
                    "matches_hdf",
                ]
            ]

        hdf_validation = hdf_df[["River", "Reach", "RS", "Obstr Block Mode"]].copy()
        hdf_validation["xs_id"] = hdf_validation.apply(
            lambda row: GeomCrossSection._make_xs_id(row["River"], row["Reach"], row["RS"]),
            axis=1,
        )
        hdf_validation = hdf_validation[["xs_id", "Obstr Block Mode"]].rename(
            columns={"Obstr Block Mode": "hdf_obstr_block_mode"}
        )

        validation = validation.merge(hdf_validation, on="xs_id", how="left")
        validation["hdf_has_blocked_obstructions"] = (
            validation["hdf_obstr_block_mode"].fillna(0).astype(float) != 0
        )
        validation["matches_hdf"] = (
            validation["text_has_blocked_obstructions"]
            == validation["hdf_has_blocked_obstructions"]
        )

        return validation[
            [
                "xs_id",
                "River",
                "Reach",
                "RS",
                "text_obstruction_count",
                "text_has_blocked_obstructions",
                "hdf_obstr_block_mode",
                "hdf_has_blocked_obstructions",
                "matches_hdf",
            ]
        ]

    @staticmethod
    @log_call
    def get_station_elevation(geom_file: Union[str, Path],
                             river: str,
                             reach: str,
                             rs: str) -> pd.DataFrame:
        """
        Extract station/elevation pairs for a cross section.

        Reads the cross section geometry data from the plain text geometry file.
        Uses fixed-width parsing (8-character columns) following FORTRAN conventions.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name (case-sensitive)
            reach (str): Reach name (case-sensitive)
            rs (str): River station (as string, e.g., "138154.4")

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Station (float): Station along cross section (ft or m)
                - Elevation (float): Ground elevation at station (ft or m)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If cross section not found

        Example:
            >>> sta_elev = GeomCrossSection.get_station_elevation(
            ...     "BaldEagle.g01", "Bald Eagle Creek", "Reach 1", "138154.4"
            ... )
            >>> print(f"XS has {len(sta_elev)} points")
            >>> print(f"Station range: {sta_elev['Station'].min():.1f} to {sta_elev['Station'].max():.1f}")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(
                    f"Cross section not found: {river}/{reach}/RS {rs} in {geom_file.name}"
                )

            # Find #Sta/Elev= line within XS section
            for j in range(xs_idx, GeomCrossSection._find_xs_section_end(lines, xs_idx)):
                if lines[j].startswith("#Sta/Elev="):
                    # Extract count
                    count_str = GeomParser.extract_keyword_value(lines[j], "#Sta/Elev")
                    count = int(count_str.strip())

                    logger.debug(f"#Sta/Elev= {count} (means {count} pairs)")

                    # Parse paired data using helper
                    df = GeomCrossSection._parse_paired_data(
                        lines, j + 1, count, 'Station', 'Elevation'
                    )

                    logger.info(
                        f"Extracted {len(df)} station/elevation pairs for "
                        f"{river}/{reach}/RS {rs}"
                    )

                    return df

            # If we get here, #Sta/Elev not found for this XS
            raise ValueError(
                f"#Sta/Elev data not found for {river}/{reach}/RS {rs}"
            )

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading station/elevation: {str(e)}")
            raise IOError(f"Failed to read station/elevation: {str(e)}")

    @staticmethod
    @log_call
    def set_station_elevation(geom_file: Union[str, Path],
                             river: str,
                             reach: str,
                             rs: str,
                             sta_elev_df: pd.DataFrame,
                             bank_left: Optional[float] = None,
                             bank_right: Optional[float] = None,
                             create_backup: bool = True) -> Optional[Path]:
        """
        Write station/elevation pairs to a cross section with automatic bank interpolation.

        Modifies the geometry file in-place, replacing the station/elevation data and
        optionally updating bank stations. Creates a .bak backup automatically.

        CRITICAL REQUIREMENTS (HEC-RAS compatibility):
        - Bank stations MUST appear as exact points in station/elevation data
        - This method automatically interpolates elevations at bank locations
        - Existing points within 0.005 units of a bank station are snapped to
          the exact bank value rather than inserting a near-duplicate point
        - Maximum 500 points per cross section (HEC-RAS hard limit)

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station
            sta_elev_df (pd.DataFrame): DataFrame with 'Station' and 'Elevation' columns
            bank_left (Optional[float]): Left bank station. If provided, updates bank in file.
                                         If None, reads existing banks and interpolates them.
            bank_right (Optional[float]): Right bank station. If provided, updates bank in file.
            create_backup (bool): Whether to create a .bak backup before modification (default True).

        Returns:
            Optional[Path]: Backup path if create_backup=True, otherwise None.

        Raises:
            FileNotFoundError: If geometry file does not exist
            ValueError: If cross section not found, DataFrame invalid, or >500 points
            IOError: If file write fails

        Example:
            >>> # Simple elevation modification (banks auto-interpolated)
            >>> sta_elev = GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)
            >>> sta_elev['Elevation'] += 1.0
            >>> GeomCrossSection.set_station_elevation(geom_file, river, reach, rs, sta_elev)
            >>>
            >>> # Modify geometry AND change bank stations
            >>> GeomCrossSection.set_station_elevation(geom_file, river, reach, rs, sta_elev,
            ...                                   bank_left=200.0, bank_right=400.0)
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Validate DataFrame
        if not isinstance(sta_elev_df, pd.DataFrame):
            raise ValueError("sta_elev_df must be a pandas DataFrame")

        if 'Station' not in sta_elev_df.columns or 'Elevation' not in sta_elev_df.columns:
            raise ValueError("DataFrame must have 'Station' and 'Elevation' columns")

        if len(sta_elev_df) == 0:
            raise ValueError("DataFrame cannot be empty")

        # Validate initial point count (before interpolation)
        if len(sta_elev_df) > GeomCrossSection.MAX_XS_POINTS:
            raise ValueError(
                f"Cross section has {len(sta_elev_df)} points, exceeds HEC-RAS "
                f"limit of {GeomCrossSection.MAX_XS_POINTS} points.\n"
                f"Reduce point count by decimating or simplifying the cross section geometry."
            )

        backup_path = None

        try:
            # Create backup
            if create_backup:
                backup_path = GeomParser.create_backup(geom_file)
                logger.info(f"Created backup: {backup_path}")

            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the cross section using helper
            i = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if i is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            modified_lines = lines.copy()

            # Read existing bank stations if not provided (using helper)
            existing_banks = None
            if bank_left is None or bank_right is None:
                existing_banks = GeomCrossSection._read_bank_stations(lines, i)

            # Use provided banks or existing banks
            if existing_banks:
                existing_bank_left, existing_bank_right = existing_banks
            else:
                existing_bank_left = existing_bank_right = None

            final_bank_left = bank_left if bank_left is not None else existing_bank_left
            final_bank_right = bank_right if bank_right is not None else existing_bank_right

            if (bank_left is not None or bank_right is not None) and (
                final_bank_left is None or final_bank_right is None
            ):
                raise ValueError(
                    "Both bank_left and bank_right are required when no existing "
                    "Bank Sta= line supplies the missing value"
                )

            if final_bank_left is not None and final_bank_right is not None:
                if final_bank_left >= final_bank_right:
                    raise ValueError(
                        f"Left bank ({final_bank_left}) must be < right bank ({final_bank_right})"
                    )

            # Interpolate at bank stations (HEC-RAS requirement)
            sta_elev_with_banks = GeomCrossSection._interpolate_at_banks(
                sta_elev_df, final_bank_left, final_bank_right
            )

            # Validate point count AFTER interpolation (HEC-RAS limit)
            if len(sta_elev_with_banks) > GeomCrossSection.MAX_XS_POINTS:
                raise ValueError(
                    f"Cross section would have {len(sta_elev_with_banks)} points after bank interpolation, "
                    f"exceeds HEC-RAS limit of {GeomCrossSection.MAX_XS_POINTS} points.\n"
                    f"Original points: {len(sta_elev_df)}, added by interpolation: "
                    f"{len(sta_elev_with_banks) - len(sta_elev_df)}.\n"
                    f"Reduce point count before writing."
                )

            # Validate stations are in ascending order
            if not sta_elev_with_banks['Station'].is_monotonic_increasing:
                raise ValueError("Stations must be in ascending order")

            logger.info(
                f"Prepared geometry: {len(sta_elev_with_banks)} points "
                f"(original: {len(sta_elev_df)}, interpolated: "
                f"{len(sta_elev_with_banks) - len(sta_elev_df)})"
            )

            # Find #Sta/Elev= line
            for j in range(i, GeomCrossSection._find_xs_section_end(lines, i)):
                if lines[j].startswith("#Sta/Elev="):
                    # Extract old count
                    old_count_str = GeomParser.extract_keyword_value(lines[j], "#Sta/Elev")
                    old_count = int(old_count_str.strip())
                    old_total_values = GeomParser.interpret_count("#Sta/Elev", old_count)

                    # Calculate old data line count
                    old_data_lines = (
                        old_total_values + GeomCrossSection.VALUES_PER_LINE - 1
                    ) // GeomCrossSection.VALUES_PER_LINE

                    # Prepare new data (using bank-interpolated DataFrame)
                    new_count = len(sta_elev_with_banks)

                    # Interleave station and elevation
                    new_values = []
                    for _, row in sta_elev_with_banks.iterrows():
                        new_values.append(row['Station'])
                        new_values.append(row['Elevation'])

                    # Format new data lines using constants
                    new_data_lines = GeomParser.format_fixed_width(
                        new_values,
                        column_width=GeomCrossSection.FIXED_WIDTH_COLUMN,
                        values_per_line=GeomCrossSection.VALUES_PER_LINE,
                        precision=2
                    )

                    # Replace count and data lines as one block so longer
                    # rewrites do not overwrite following geometry keywords.
                    data_start = j + 1
                    data_end = data_start + old_data_lines
                    modified_lines = (
                        modified_lines[:j]
                        + [f"#Sta/Elev= {new_count}\n"]
                        + new_data_lines
                        + modified_lines[data_end:]
                    )

                    # Update or insert Bank Sta= line when caller supplied bank values
                    if bank_left is not None or bank_right is not None:
                        # Find Bank Sta= line in the modified lines
                        bank_sta_updated = False
                        for k in range(i, GeomCrossSection._find_xs_section_end(modified_lines, i)):
                            if modified_lines[k].startswith("Bank Sta="):
                                modified_lines[k] = GeomCrossSection._bank_station_line(
                                    final_bank_left, final_bank_right, modified_lines[k]
                                )
                                bank_sta_updated = True
                                logger.debug(
                                    f"Updated Bank Sta= line: {final_bank_left:g},{final_bank_right:g}"
                                )
                                break

                        if not bank_sta_updated:
                            GeomCrossSection._insert_xs_keyword_line(
                                modified_lines,
                                i,
                                GeomCrossSection._bank_station_line(final_bank_left, final_bank_right),
                                prefer_before=["#Sta/Elev=", "#Mann="]
                            )
                            logger.debug(
                                f"Inserted Bank Sta= line: {final_bank_left:g},{final_bank_right:g}"
                            )

                    # Write modified file
                    with open(geom_file, 'w', encoding='utf-8') as f:
                        f.writelines(modified_lines)

                    logger.info(
                        f"Updated station/elevation for {river}/{reach}/RS {rs}: "
                        f"{new_count} pairs written"
                    )

                    if bank_left is not None and bank_right is not None:
                        logger.info(f"Updated bank stations: {bank_left:g}, {bank_right:g}")

                    return backup_path

            raise ValueError(
                f"#Sta/Elev data not found for {river}/{reach}/RS {rs}"
            )

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing station/elevation: {str(e)}")
            # Attempt to restore from backup if write failed
            if backup_path and backup_path.exists():
                logger.info(f"Restoring from backup: {backup_path}")
                import shutil
                shutil.copy2(backup_path, geom_file)
            raise IOError(f"Failed to write station/elevation: {str(e)}")

    @staticmethod
    @log_call
    def set_bank_stations(geom_file: Union[str, Path],
                          river: str,
                          reach: str,
                          rs: str,
                          bank_left: float,
                          bank_right: float,
                          create_backup: bool = True) -> Optional[Path]:
        """
        Set left and right bank stations for a cross section.

        Updates or inserts the ``Bank Sta=`` line and rewrites the
        ``#Sta/Elev`` block so both bank stations are exact station/elevation
        points, as required by HEC-RAS. Missing bank points are linearly
        interpolated from the existing station/elevation profile.

        Parameters:
            geom_file: Path to HEC-RAS geometry file
            river: River name
            reach: Reach name
            rs: River station
            bank_left: Left bank station
            bank_right: Right bank station
            create_backup: Whether to create a .bak backup before modification (default True)

        Returns:
            Optional[Path]: Backup path if create_backup=True, otherwise None.

        Raises:
            FileNotFoundError: If geometry file does not exist
            ValueError: If cross section not found, bank stations are invalid,
                        or bank interpolation would exceed the point limit
            IOError: If file write fails
        """
        if bank_left >= bank_right:
            raise ValueError(f"Left bank ({bank_left}) must be < right bank ({bank_right})")

        sta_elev_df = GeomCrossSection.get_station_elevation(
            geom_file, river, reach, rs
        )

        return GeomCrossSection.set_station_elevation(
            geom_file,
            river,
            reach,
            rs,
            sta_elev_df,
            bank_left=bank_left,
            bank_right=bank_right,
            create_backup=create_backup
        )

    @staticmethod
    @log_call
    def get_bank_stations(geom_file: Union[str, Path],
                         river: str,
                         reach: str,
                         rs: str) -> Optional[Tuple[float, float]]:
        """
        Extract left and right bank station locations for a cross section.

        Bank stations define the boundary between overbank areas and the main channel,
        used for subsection conveyance calculations.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station

        Returns:
            Optional[Tuple[float, float]]: (left_bank, right_bank) or None if no banks defined

        Example:
            >>> banks = GeomCrossSection.get_bank_stations("BaldEagle.g01", "Bald Eagle", "Loc Hav", "138154.4")
            >>> if banks:
            ...     left, right = banks
            ...     print(f"Bank stations: Left={left}, Right={right}")
            ...     print(f"Main channel width: {right - left} ft")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            # Read bank stations using helper
            banks = GeomCrossSection._read_bank_stations(lines, xs_idx)

            if banks:
                left_bank, right_bank = banks
                logger.info(f"Extracted bank stations for {river}/{reach}/RS {rs}: {left_bank}, {right_bank}")
                return banks
            else:
                logger.info(f"No bank stations found for {river}/{reach}/RS {rs}")
                return None

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading bank stations: {str(e)}")
            raise IOError(f"Failed to read bank stations: {str(e)}")

    @staticmethod
    @log_call
    def get_expansion_contraction(geom_file: Union[str, Path],
                                  river: str,
                                  reach: str,
                                  rs: str) -> Tuple[float, float]:
        """
        Extract expansion and contraction coefficients for a cross section.

        These coefficients account for energy losses due to flow expansion
        (downstream) and contraction (upstream) at cross sections.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station

        Returns:
            Tuple[float, float]: (expansion, contraction) coefficients

        Example:
            >>> exp, cntr = GeomCrossSection.get_expansion_contraction(
            ...     "BaldEagle.g01", "Bald Eagle", "Loc Hav", "138154.4"
            ... )
            >>> print(f"Expansion: {exp}, Contraction: {cntr}")
            >>> # Typical values: expansion=0.3, contraction=0.1
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            # Find Exp/Cntr= line within XS section
            for j in range(xs_idx, GeomCrossSection._find_xs_section_end(lines, xs_idx)):
                if lines[j].startswith("Exp/Cntr="):
                    exp_cntr_str = GeomParser.extract_keyword_value(lines[j], "Exp/Cntr")
                    values = [v.strip() for v in exp_cntr_str.split(',')]

                    if len(values) >= 2:
                        expansion = float(values[0])
                        contraction = float(values[1])

                        logger.info(
                            f"Extracted expansion/contraction for {river}/{reach}/RS {rs}: "
                            f"{expansion}, {contraction}"
                        )
                        return (expansion, contraction)

            # XS found but no Exp/Cntr= (use defaults)
            logger.info(f"No Exp/Cntr found for {river}/{reach}/RS {rs}, using defaults")
            return (0.3, 0.1)  # HEC-RAS defaults

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading expansion/contraction: {str(e)}")
            raise IOError(f"Failed to read expansion/contraction: {str(e)}")

    @staticmethod
    @log_call
    def set_expansion_contraction(geom_file: Union[str, Path],
                                  river: str,
                                  reach: str,
                                  rs: str,
                                  expansion: float,
                                  contraction: float,
                                  create_backup: bool = True) -> Optional[Path]:
        """
        Set expansion and contraction coefficients for a cross section.

        Updates an existing ``Exp/Cntr=`` line or inserts one into the target
        cross-section block. Creates a ``.bak`` backup before modifying by
        default.

        Parameters:
            geom_file: Path to HEC-RAS geometry file
            river: River name
            reach: Reach name
            rs: River station
            expansion: Expansion coefficient
            contraction: Contraction coefficient
            create_backup: Whether to create a .bak backup before modification (default True)

        Returns:
            Optional[Path]: Backup path if create_backup=True, otherwise None.

        Raises:
            FileNotFoundError: If geometry file does not exist
            ValueError: If cross section not found or coefficients are invalid
            IOError: If file write fails
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        expansion = float(expansion)
        contraction = float(contraction)
        if expansion < 0 or contraction < 0:
            raise ValueError("Expansion and contraction coefficients must be non-negative")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)
            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            modified_lines = lines.copy()
            exp_idx = GeomCrossSection._find_keyword_index(modified_lines, xs_idx, "Exp/Cntr=")

            if exp_idx is not None:
                modified_lines[exp_idx] = GeomCrossSection._exp_cntr_line(
                    expansion, contraction, modified_lines[exp_idx]
                )
            else:
                GeomCrossSection._insert_xs_keyword_line(
                    modified_lines,
                    xs_idx,
                    GeomCrossSection._exp_cntr_line(expansion, contraction),
                    prefer_after=["Bank Sta="],
                    prefer_before=["#Sta/Elev=", "#Mann="]
                )

            backup_path = GeomParser.safe_write_geometry(
                geom_file,
                modified_lines,
                create_backup=create_backup
            )

            logger.info(
                f"Updated expansion/contraction for {river}/{reach}/RS {rs}: "
                f"{expansion:g}, {contraction:g}"
            )
            return backup_path

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing expansion/contraction: {str(e)}")
            raise IOError(f"Failed to write expansion/contraction: {str(e)}")

    @staticmethod
    @log_call
    def get_levees(geom_number: Union[str, Path],
                   river: Optional[str] = None,
                   reach: Optional[str] = None,
                   rs: Optional[str] = None,
                   xs_id: Optional[str] = None,
                   ras_object=None) -> pd.DataFrame:
        """
        Read left and right levee station-elevation points from cross sections.

        Cross-section levees are stored in plain-text geometry files as a
        single ``Levee=`` line with left and right triplets:
        ``flag, station, elevation``. Active sides use flag ``-1``; inactive
        sides use flag ``0`` and blank station/elevation fields.

        Parameters:
            geom_number: Geometry number or direct path to a .g## text file
            river: Optional river filter
            reach: Optional reach filter. If supplied, ``river`` is required.
            rs: Optional river-station filter. If supplied, ``river`` and
                ``reach`` are required.
            xs_id: Optional exact ID from the returned ``xs_id`` column.
            ras_object: Optional RasPrj instance for API consistency (unused)

        Returns:
            pd.DataFrame: Columns ``xs_id``, ``left_station``,
            ``left_elevation``, ``right_station``, ``right_elevation``.
            Matching cross sections without levees are included with NaN values.
        """
        geom_file = GeomCrossSection._resolve_geom_text_path(geom_number, ras_object=ras_object)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")
        if reach is not None and river is None:
            raise ValueError("If reach is specified, river must also be specified")
        if rs is not None and (river is None or reach is None):
            raise ValueError("If rs is specified, river and reach must also be specified")

        columns = [
            'xs_id',
            'River',
            'Reach',
            'RS',
            'left_station',
            'left_elevation',
            'right_station',
            'right_elevation'
        ]

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            rows = []
            current_river = None
            current_reach = None

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
                    if len(values) < 2 or current_river is None or current_reach is None:
                        i += 1
                        continue

                    current_rs = values[1]
                    current_xs_id = GeomCrossSection._make_xs_id(
                        current_river,
                        current_reach,
                        current_rs
                    )

                    if river is not None and current_river != river:
                        i += 1
                        continue
                    if reach is not None and current_reach != reach:
                        i += 1
                        continue
                    if rs is not None and current_rs != rs:
                        i += 1
                        continue
                    if xs_id is not None and current_xs_id != xs_id:
                        i += 1
                        continue

                    levee_values = (math.nan, math.nan, math.nan, math.nan)
                    section_end = GeomCrossSection._find_xs_section_end(lines, i)
                    for j in range(i, section_end):
                        if lines[j].startswith("Levee="):
                            levee_values = GeomCrossSection._parse_levee_line(lines[j])
                            break

                    rows.append({
                        'xs_id': current_xs_id,
                        'River': current_river,
                        'Reach': current_reach,
                        'RS': current_rs,
                        'left_station': levee_values[0],
                        'left_elevation': levee_values[1],
                        'right_station': levee_values[2],
                        'right_elevation': levee_values[3],
                    })

                    i = section_end
                    continue

                i += 1

            df = pd.DataFrame(rows, columns=columns)
            logger.info(f"Read levee data for {len(df)} cross sections from {geom_file}")
            return df

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading levees: {str(e)}")
            raise IOError(f"Failed to read levees: {str(e)}")

    @staticmethod
    @log_call
    def set_levees(geom_number: Union[str, Path],
                   xs_id: Optional[str] = None,
                   left_station: Optional[float] = None,
                   left_elevation: Optional[float] = None,
                   right_station: Optional[float] = None,
                   right_elevation: Optional[float] = None,
                   *,
                   river: Optional[str] = None,
                   reach: Optional[str] = None,
                   rs: Optional[str] = None,
                   create_backup: bool = True,
                   ras_object=None) -> Optional[Path]:
        """
        Write left and right levee station-elevation points for a cross section.

        Updates an existing ``Levee=`` line or inserts one immediately after the
        target cross section's ``#Mann=`` data block. Pass station/elevation
        together for each side; omit both values for a side to write it as
        inactive.

        Parameters:
            geom_number: Geometry number or direct path to a .g## text file
            xs_id: Cross-section ID emitted by ``get_levees()``. Optional if
                ``river``, ``reach``, and ``rs`` are provided.
            left_station: Optional left levee station
            left_elevation: Optional left levee elevation
            right_station: Optional right levee station
            right_elevation: Optional right levee elevation
            river: Optional target river, used with ``reach`` and ``rs``
            reach: Optional target reach
            rs: Optional target river station
            create_backup: Whether to create a .bak backup before modification
            ras_object: Optional RasPrj instance for API consistency (unused)

        Returns:
            Optional[Path]: Backup path if ``create_backup=True``, otherwise None.
        """
        geom_file = GeomCrossSection._resolve_geom_text_path(geom_number, ras_object=ras_object)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")
        if xs_id is None and (river is None or reach is None or rs is None):
            raise ValueError("Provide xs_id or all of river, reach, and rs")
        if xs_id is not None and any(v is not None for v in (river, reach, rs)):
            raise ValueError("Provide either xs_id or river/reach/rs, not both")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            xs_df = GeomCrossSection.get_cross_sections(geom_file)
            if xs_id is not None:
                target_river, target_reach, target_rs = GeomCrossSection._resolve_xs_identifier(xs_id, xs_df)
            else:
                target_river, target_reach, target_rs = river, reach, rs

            xs_idx = GeomCrossSection._find_cross_section(lines, target_river, target_reach, target_rs)
            if xs_idx is None:
                raise ValueError(f"Cross section not found: {target_river}/{target_reach}/RS {target_rs}")

            modified_lines = lines.copy()
            levee_idx = GeomCrossSection._find_keyword_index(modified_lines, xs_idx, "Levee=")
            new_line = GeomCrossSection._levee_line(
                left_station=left_station,
                left_elevation=left_elevation,
                right_station=right_station,
                right_elevation=right_elevation,
                existing_line=modified_lines[levee_idx] if levee_idx is not None else None
            )

            if levee_idx is not None:
                modified_lines[levee_idx] = new_line
            else:
                insert_idx = GeomCrossSection._find_mann_block_end(modified_lines, xs_idx)
                if insert_idx is not None:
                    modified_lines.insert(insert_idx, new_line)
                else:
                    GeomCrossSection._insert_xs_keyword_line(
                        modified_lines,
                        xs_idx,
                        new_line,
                        prefer_before=[
                            "#XS Ineff=",
                            "#Block Obstruct=",
                            "Bank Sta=",
                            "XS Rating Curve=",
                            "XS HTab Starting El and Incr=",
                            "XS HTab Horizontal Distribution=",
                            "Exp/Cntr="
                        ]
                    )

            backup_path = GeomParser.safe_write_geometry(
                geom_file,
                modified_lines,
                create_backup=create_backup
            )

            logger.info(
                f"Updated levees for {target_river}/{target_reach}/RS {target_rs}"
            )
            return backup_path

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing levees: {str(e)}")
            raise IOError(f"Failed to write levees: {str(e)}")

    @staticmethod
    @log_call
    def interpolate_station_elevation(upstream_df: pd.DataFrame,
                                      downstream_df: pd.DataFrame,
                                      ratio: float = 0.5,
                                      bank_left: Optional[float] = None,
                                      bank_right: Optional[float] = None,
                                      max_points: int = MAX_XS_POINTS) -> pd.DataFrame:
        """
        Interpolate a reviewable station/elevation profile between two cross sections.

        The interpolation uses normalized lateral position so source cross
        sections can have different station ranges and point spacing. The
        returned DataFrame includes source station/elevation columns for review
        and enforces the HEC-RAS cross-section point limit.

        Parameters:
            upstream_df: Upstream station/elevation DataFrame
            downstream_df: Downstream station/elevation DataFrame
            ratio: Fraction from upstream to downstream (0=upstream, 1=downstream)
            bank_left: Optional left bank station to insert exactly
            bank_right: Optional right bank station to insert exactly
            max_points: Maximum output points, default HEC-RAS limit of 500

        Returns:
            pd.DataFrame: Reviewable interpolated profile with columns:
                Station, Elevation, UpstreamStation, UpstreamElevation,
                DownstreamStation, DownstreamElevation, InterpolationRatio,
                SourceFraction, Source, IsBankPoint
        """
        ratio = float(ratio)
        if ratio < 0.0 or ratio > 1.0:
            raise ValueError("ratio must be between 0 and 1")
        if bank_left is not None and bank_right is not None and bank_left >= bank_right:
            raise ValueError(f"Left bank ({bank_left}) must be < right bank ({bank_right})")

        max_points = int(max_points)
        if max_points < 2:
            raise ValueError("max_points must be at least 2")
        if max_points > GeomCrossSection.MAX_XS_POINTS:
            raise ValueError(
                f"max_points ({max_points}) exceeds HEC-RAS limit of "
                f"{GeomCrossSection.MAX_XS_POINTS}"
            )

        upstream = GeomCrossSection._prepare_station_elevation_df(upstream_df, "upstream_df")
        downstream = GeomCrossSection._prepare_station_elevation_df(downstream_df, "downstream_df")

        bank_values = []
        for bank in (bank_left, bank_right):
            if bank is not None and not any(
                np.isclose(float(bank), existing, atol=0.005)
                for existing in bank_values
            ):
                bank_values.append(float(bank))

        base_limit = max_points - len(bank_values)
        if base_limit < 2:
            raise ValueError("max_points is too small for endpoint and bank-point requirements")

        up_station = upstream['Station'].to_numpy(dtype=float)
        up_elevation = upstream['Elevation'].to_numpy(dtype=float)
        dn_station = downstream['Station'].to_numpy(dtype=float)
        dn_elevation = downstream['Elevation'].to_numpy(dtype=float)
        up_fraction = GeomCrossSection._station_fractions(up_station)
        dn_fraction = GeomCrossSection._station_fractions(dn_station)

        raw_fractions = np.unique(
            np.concatenate((
                np.array([0.0, 1.0]),
                np.round(up_fraction, 12),
                np.round(dn_fraction, 12)
            ))
        )
        raw_fractions.sort()

        if len(raw_fractions) > base_limit:
            source_fractions = np.linspace(0.0, 1.0, base_limit)
            source_labels = ["resampled"] * len(source_fractions)
        else:
            source_fractions = raw_fractions
            up_set = {round(float(v), 12) for v in up_fraction}
            dn_set = {round(float(v), 12) for v in dn_fraction}
            source_labels = []
            for value in source_fractions:
                rounded = round(float(value), 12)
                in_upstream = rounded in up_set
                in_downstream = rounded in dn_set
                if in_upstream and in_downstream:
                    source_labels.append("both")
                elif in_upstream:
                    source_labels.append("upstream")
                elif in_downstream:
                    source_labels.append("downstream")
                else:
                    source_labels.append("resampled")

        interp_up_station = np.interp(source_fractions, up_fraction, up_station)
        interp_up_elevation = np.interp(source_fractions, up_fraction, up_elevation)
        interp_dn_station = np.interp(source_fractions, dn_fraction, dn_station)
        interp_dn_elevation = np.interp(source_fractions, dn_fraction, dn_elevation)

        stations = interp_up_station + ratio * (interp_dn_station - interp_up_station)
        elevations = interp_up_elevation + ratio * (interp_dn_elevation - interp_up_elevation)

        result = pd.DataFrame({
            'Station': stations,
            'Elevation': elevations,
            'UpstreamStation': interp_up_station,
            'UpstreamElevation': interp_up_elevation,
            'DownstreamStation': interp_dn_station,
            'DownstreamElevation': interp_dn_elevation,
            'InterpolationRatio': ratio,
            'SourceFraction': source_fractions,
            'Source': source_labels,
            'IsBankPoint': False
        })

        result = result.sort_values('Station').reset_index(drop=True)

        for bank_sta, label in ((bank_left, "left"), (bank_right, "right")):
            if bank_sta is None:
                continue

            bank_sta = float(bank_sta)
            stations_array = result['Station'].to_numpy(dtype=float)
            min_station = float(stations_array[0])
            max_station = float(stations_array[-1])
            if bank_sta < min_station - 0.005 or bank_sta > max_station + 0.005:
                raise ValueError(
                    f"{label.title()} bank station ({bank_sta}) must be within "
                    f"interpolated station range {min_station:g} to {max_station:g}"
                )

            diffs = np.abs(stations_array - bank_sta)
            nearest_idx = int(np.argmin(diffs))
            if diffs[nearest_idx] <= 0.005:
                result.loc[nearest_idx, 'Station'] = bank_sta
                result.loc[nearest_idx, 'IsBankPoint'] = True
                continue

            numeric_columns = [
                'Elevation',
                'UpstreamStation',
                'UpstreamElevation',
                'DownstreamStation',
                'DownstreamElevation',
                'SourceFraction'
            ]
            new_row = {
                'Station': bank_sta,
                'InterpolationRatio': ratio,
                'Source': 'bank',
                'IsBankPoint': True
            }
            for column in numeric_columns:
                new_row[column] = float(np.interp(
                    bank_sta,
                    result['Station'].to_numpy(dtype=float),
                    result[column].to_numpy(dtype=float)
                ))

            result = pd.concat([result, pd.DataFrame([new_row])], ignore_index=True)
            result = result.sort_values('Station').reset_index(drop=True)

        if len(result) > max_points:
            raise ValueError(
                f"Interpolated cross section has {len(result)} points, exceeds "
                f"HEC-RAS limit of {max_points}"
            )

        return result

    @staticmethod
    @log_call
    def interpolate_cross_section(geom_file: Union[str, Path],
                                  river: str,
                                  reach: str,
                                  upstream_rs: str,
                                  downstream_rs: str,
                                  ratio: float = 0.5,
                                  bank_left: Optional[float] = None,
                                  bank_right: Optional[float] = None,
                                  max_points: int = MAX_XS_POINTS,
                                  interpolated_rs: Optional[str] = None) -> pd.DataFrame:
        """
        Read two cross sections from a geometry file and interpolate a reviewable profile.

        If bank stations are not supplied, this helper linearly interpolates
        them from the source cross sections when both source sections define
        bank stations.
        """
        ratio = float(ratio)

        upstream = GeomCrossSection.get_station_elevation(
            geom_file, river, reach, upstream_rs
        )
        downstream = GeomCrossSection.get_station_elevation(
            geom_file, river, reach, downstream_rs
        )

        final_bank_left = bank_left
        final_bank_right = bank_right
        upstream_banks = GeomCrossSection.get_bank_stations(
            geom_file, river, reach, upstream_rs
        )
        downstream_banks = GeomCrossSection.get_bank_stations(
            geom_file, river, reach, downstream_rs
        )

        if upstream_banks and downstream_banks:
            if final_bank_left is None:
                final_bank_left = (
                    upstream_banks[0] + ratio * (downstream_banks[0] - upstream_banks[0])
                )
            if final_bank_right is None:
                final_bank_right = (
                    upstream_banks[1] + ratio * (downstream_banks[1] - upstream_banks[1])
                )

        result = GeomCrossSection.interpolate_station_elevation(
            upstream,
            downstream,
            ratio=ratio,
            bank_left=final_bank_left,
            bank_right=final_bank_right,
            max_points=max_points
        )

        result['River'] = river
        result['Reach'] = reach
        result['UpstreamRS'] = upstream_rs
        result['DownstreamRS'] = downstream_rs
        if interpolated_rs is not None:
            result['InterpolatedRS'] = interpolated_rs
        if final_bank_left is not None:
            result['BankLeft'] = final_bank_left
        if final_bank_right is not None:
            result['BankRight'] = final_bank_right

        return result

    @staticmethod
    @log_call
    def get_mannings_n(geom_file: Union[str, Path],
                      river: str,
                      reach: str,
                      rs: str) -> pd.DataFrame:
        """
        Extract Manning's n roughness values for a cross section.

        Manning's n values define channel roughness and are organized by subsections
        (Left Overbank, Main Channel, Right Overbank) based on bank station locations.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file
            river (str): River name
            reach (str): Reach name
            rs (str): River station

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Station (float): Station where this Manning's n value starts
                - n_value (float): Manning's roughness coefficient
                - Subsection (str): 'LOB' (Left Overbank), 'Channel', or 'ROB' (Right Overbank)

        Example:
            >>> mann = GeomCrossSection.get_mannings_n("BaldEagle.g01", "Bald Eagle", "Loc Hav", "138154.4")
            >>> print(mann)
               Station  n_value Subsection
            0      0.0     0.06        LOB
            1    190.0     0.04    Channel
            2    375.0     0.10        ROB
            >>>
            >>> # Calculate average channel Manning's n
            >>> channel_n = mann[mann['Subsection'] == 'Channel']['n_value'].mean()
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            # Get bank stations using helper (for subsection classification)
            banks = GeomCrossSection._read_bank_stations(lines, xs_idx)
            bank_left = bank_right = None
            if banks:
                bank_left, bank_right = banks

            # Find #Mann= line within XS section
            for j in range(xs_idx, GeomCrossSection._find_xs_section_end(lines, xs_idx)):
                if lines[j].startswith("#Mann="):
                    # Extract count
                    mann_str = GeomParser.extract_keyword_value(lines[j], "#Mann")
                    count_values = [v.strip() for v in mann_str.split(',')]

                    num_segments = int(count_values[0]) if count_values[0] else 0
                    format_flag = int(count_values[1]) if len(count_values) > 1 and count_values[1] else 0

                    logger.debug(f"Manning's n: {num_segments} segments, format={format_flag}")

                    # Calculate total values to read (triplets)
                    total_values = num_segments * 3

                    # Parse Manning's n data using helper (note: max_lines=20 for Manning's n)
                    values = GeomCrossSection._parse_data_block(
                        lines, j + 1, total_values,
                        column_width=GeomCrossSection.FIXED_WIDTH_COLUMN,
                        max_lines=20
                    )

                    # Convert triplets to DataFrame
                    segments = []
                    for seg_idx in range(0, len(values), 3):
                        if seg_idx + 2 < len(values):
                            station = values[seg_idx]
                            n_value = values[seg_idx + 1]
                            # values[seg_idx + 2] is always 0, ignore

                            # Classify subsection based on bank stations
                            if bank_left is not None and bank_right is not None:
                                if station < bank_left:
                                    subsection = 'LOB'
                                elif station < bank_right:
                                    subsection = 'Channel'
                                else:
                                    subsection = 'ROB'
                            else:
                                subsection = 'Unknown'

                            segments.append({
                                'Station': station,
                                'n_value': n_value,
                                'Subsection': subsection
                            })

                    df = pd.DataFrame(segments)

                    logger.info(
                        f"Extracted {len(df)} Manning's n segments for {river}/{reach}/RS {rs}"
                    )

                    return df

            # XS found but no Manning's n
            raise ValueError(f"No Manning's n data found for {river}/{reach}/RS {rs}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading Manning's n: {str(e)}")
            raise IOError(f"Failed to read Manning's n: {str(e)}")

    @staticmethod
    @log_call
    def get_ineffective_flow(geom_file: Union[str, Path],
                             river: str,
                             reach: str,
                             rs: str) -> Tuple[Optional[pd.DataFrame], Optional[int], Optional[List[bool]]]:
        """
        Read ineffective flow area data for a cross section.

        Parses the ``#XS Ineff= N , F`` block, which contains N triplets of
        (left_station, right_station, elevation) followed by a ``Permanent Ineff=``
        boolean line.

        Parameters:
            geom_file: Path to HEC-RAS geometry file
            river: River name
            reach: Reach name
            rs: River station

        Returns:
            Tuple of:
                - DataFrame with columns left_station, right_station, elevation
                  (or None if no ineffective areas defined)
                - format_flag (int, 0 or -1)
                - permanent_flags (list of bool, one per pair)

        Example:
            >>> df, fmt, flags = GeomCrossSection.get_ineffective_flow(
            ...     "model.g01", "Hunting Bayou", "Mainstem", "65919"
            ... )
            >>> if df is not None:
            ...     bad = df[df['right_station'] == 0]
            ...     print(f"Found {len(bad)} pairs with right_station=0")
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)
            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            end_idx = GeomCrossSection._find_xs_section_end(lines, xs_idx)

            for j in range(xs_idx, end_idx):
                if lines[j].startswith('#XS Ineff='):
                    # Parse header: "#XS Ineff= N , F"
                    value_str = GeomParser.extract_keyword_value(lines[j], '#XS Ineff')
                    parts = [p.strip() for p in value_str.split(',')]
                    count = int(parts[0])
                    fmt_flag = int(parts[1]) if len(parts) > 1 else 0

                    # Parse N*3 values (N triplets of left_sta, right_sta, elevation)
                    total_values = count * 3
                    values = GeomCrossSection._parse_data_block(lines, j + 1, total_values)

                    if len(values) < total_values:
                        logger.warning(
                            f"Expected {total_values} ineff values, got {len(values)} "
                            f"for {river}/{reach}/RS {rs}"
                        )

                    df = pd.DataFrame({
                        'left_station': values[0::3],
                        'right_station': values[1::3],
                        'elevation': values[2::3]
                    })

                    # Read Permanent Ineff= boolean flags
                    permanent_flags = [False] * count
                    for k in range(j + 1, end_idx):
                        if lines[k].startswith('Permanent Ineff='):
                            if k + 1 < end_idx:
                                flag_line = lines[k + 1].rstrip('\n')
                                flags = []
                                for m in range(0, len(flag_line), 8):
                                    token = flag_line[m:m + 8].strip()
                                    if token in ('T', 'F'):
                                        flags.append(token == 'T')
                                if flags:
                                    permanent_flags = flags
                            break

                    logger.info(
                        f"Read {count} ineffective flow pairs for {river}/{reach}/RS {rs}"
                    )
                    return df, fmt_flag, permanent_flags

            # No #XS Ineff= found
            return None, None, None

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading ineffective flow: {str(e)}")
            raise IOError(f"Failed to read ineffective flow: {str(e)}")

    @staticmethod
    @log_call
    def set_ineffective_flow(geom_file: Union[str, Path],
                             river: str,
                             reach: str,
                             rs: str,
                             ineff_df: pd.DataFrame,
                             fmt_flag: int = 0,
                             permanent_flags: Optional[List[bool]] = None) -> None:
        """
        Write ineffective flow area data to a cross section.

        Replaces the ``#XS Ineff=`` data block in the geometry file. The count
        in the ``#XS Ineff=`` header is updated to match the length of
        ``ineff_df``. Creates a ``.bak`` backup before modifying.

        Parameters:
            geom_file: Path to HEC-RAS geometry file
            river: River name
            reach: Reach name
            rs: River station
            ineff_df: DataFrame with columns left_station, right_station, elevation
            fmt_flag: Format flag written to header (0 or -1). Preserves original if None.
            permanent_flags: List of bool for each pair (default all False)

        Raises:
            FileNotFoundError: If geometry file not found
            ValueError: If cross section or ineff block not found

        Example:
            >>> df, fmt, flags = GeomCrossSection.get_ineffective_flow(
            ...     "model.g01", "Hunting Bayou", "Mainstem", "65919"
            ... )
            >>> # Fix right_station=0 -> rightmost station
            >>> sta_elev = GeomCrossSection.get_station_elevation(
            ...     "model.g01", "Hunting Bayou", "Mainstem", "65919"
            ... )
            >>> rightmost = sta_elev['Station'].max()
            >>> df.loc[df['right_station'] == 0, 'right_station'] = rightmost
            >>> GeomCrossSection.set_ineffective_flow(
            ...     "model.g01", "Hunting Bayou", "Mainstem", "65919", df, fmt, flags
            ... )
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        count = len(ineff_df)
        if permanent_flags is None:
            permanent_flags = [False] * count

        try:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)
            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            end_idx = GeomCrossSection._find_xs_section_end(lines, xs_idx)

            for j in range(xs_idx, end_idx):
                if lines[j].startswith('#XS Ineff='):
                    # Get existing header to preserve count/flag info
                    value_str = GeomParser.extract_keyword_value(lines[j], '#XS Ineff')
                    parts = [p.strip() for p in value_str.split(',')]
                    old_count = int(parts[0])
                    orig_fmt_flag = int(parts[1]) if len(parts) > 1 else 0

                    # Use provided fmt_flag (or preserve original)
                    write_fmt_flag = fmt_flag if fmt_flag is not None else orig_fmt_flag

                    # Calculate old and new data line counts
                    old_data_lines = math.ceil(old_count * 3 / GeomCrossSection.VALUES_PER_LINE)

                    # Build new value list: left_sta, right_sta, elev per row
                    new_values = []
                    for _, row in ineff_df.iterrows():
                        new_values.extend([
                            row['left_station'],
                            row['right_station'],
                            row['elevation']
                        ])

                    new_data_lines = GeomParser.format_fixed_width(
                        new_values,
                        column_width=GeomCrossSection.FIXED_WIDTH_COLUMN,
                        values_per_line=GeomCrossSection.VALUES_PER_LINE,
                        precision=2
                    )

                    # Format Permanent Ineff= boolean line (8-char per flag)
                    perm_str = ''.join(
                        f"{'       T' if p else '       F'}" for p in permanent_flags
                    ) + '\n'

                    modified_lines = lines.copy()

                    # Update header line
                    modified_lines[j] = f"#XS Ineff= {count} ,{write_fmt_flag} \n"

                    # Mark old data lines for deletion
                    for k in range(old_data_lines):
                        if j + 1 + k < len(modified_lines):
                            modified_lines[j + 1 + k] = None

                    # Insert new data lines
                    for k, data_line in enumerate(new_data_lines):
                        if j + 1 + k < len(modified_lines):
                            modified_lines[j + 1 + k] = data_line
                        else:
                            modified_lines.append(data_line)

                    # Clean up None entries
                    modified_lines = [ln for ln in modified_lines if ln is not None]

                    # Update Permanent Ineff= data line
                    end_idx2 = GeomCrossSection._find_xs_section_end(modified_lines, xs_idx)
                    for k in range(xs_idx, end_idx2):
                        if modified_lines[k].startswith('Permanent Ineff='):
                            if k + 1 < end_idx2:
                                modified_lines[k + 1] = perm_str
                            break

                    with open(geom_file, 'w', encoding='utf-8') as f:
                        f.writelines(modified_lines)

                    logger.info(
                        f"Updated ineffective flow for {river}/{reach}/RS {rs}: "
                        f"{count} pairs written"
                    )
                    return

            raise ValueError(f"#XS Ineff block not found for {river}/{reach}/RS {rs}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing ineffective flow: {str(e)}")
            raise IOError(f"Failed to write ineffective flow: {str(e)}")

    @staticmethod
    @log_call
    def set_mannings_n(geom_file: Union[str, Path],
                       river: str,
                       reach: str,
                       rs: str,
                       mann_df: pd.DataFrame,
                       format_flag: int = 0,
                       change_flag: int = 0) -> None:
        """
        Write Manning's n data to a cross section.

        Replaces the ``#Mann=`` data block in the geometry file with new
        breakpoint data. Creates a ``.bak`` backup before modifying.

        Parameters:
            geom_file: Path to HEC-RAS geometry file
            river: River name
            reach: Reach name
            rs: River station
            mann_df: DataFrame with 'Station' and 'n_value' columns.
                     Rows define LOB/MC/ROB breakpoints in ascending station order.
            format_flag: Format flag for ``#Mann=`` header (0 or -1)
            change_flag: Change flag for ``#Mann=`` header

        Raises:
            FileNotFoundError: If geometry file not found
            ValueError: If cross section or ``#Mann=`` block not found

        Example:
            >>> import pandas as pd
            >>> mann = pd.DataFrame({
            ...     'Station': [18340.0, 19992.13, 20110.0],
            ...     'n_value': [0.08, 0.05, 0.08]
            ... })
            >>> GeomCrossSection.set_mannings_n(
            ...     "model.g01", "Hunting Bayou", "Mainstem", "65919", mann
            ... )
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        count = len(mann_df)

        try:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)
            if xs_idx is None:
                raise ValueError(f"Cross section not found: {river}/{reach}/RS {rs}")

            end_idx = GeomCrossSection._find_xs_section_end(lines, xs_idx)

            for j in range(xs_idx, end_idx):
                if lines[j].startswith('#Mann='):
                    # Parse existing header to get old count
                    value_str = GeomParser.extract_keyword_value(lines[j], '#Mann')
                    parts = [p.strip() for p in value_str.split(',')]
                    old_count = int(parts[0]) if parts[0] else 0

                    # Calculate old data line count
                    old_total = old_count * 3
                    old_data_lines = math.ceil(old_total / GeomCrossSection.VALUES_PER_LINE) if old_total > 0 else 0

                    # Build new value list: station, n_value, change_flag per row
                    new_values = []
                    for _, row in mann_df.iterrows():
                        new_values.extend([row['Station'], row['n_value'], 0.0])

                    new_data_lines = GeomParser.format_fixed_width(
                        new_values,
                        column_width=GeomCrossSection.FIXED_WIDTH_COLUMN,
                        values_per_line=GeomCrossSection.VALUES_PER_LINE,
                        precision=2
                    )

                    modified_lines = lines.copy()

                    # Update header
                    modified_lines[j] = f"#Mann= {count} ,{format_flag} ,{change_flag} \n"

                    # Mark old data lines for deletion
                    for k in range(old_data_lines):
                        if j + 1 + k < len(modified_lines):
                            modified_lines[j + 1 + k] = None

                    # Insert new data lines
                    for k, data_line in enumerate(new_data_lines):
                        if j + 1 + k < len(modified_lines):
                            modified_lines[j + 1 + k] = data_line
                        else:
                            modified_lines.append(data_line)

                    # Clean up None entries
                    modified_lines = [ln for ln in modified_lines if ln is not None]

                    with open(geom_file, 'w', encoding='utf-8') as f:
                        f.writelines(modified_lines)

                    logger.info(
                        f"Updated Manning's n for {river}/{reach}/RS {rs}: "
                        f"{count} breakpoints written"
                    )
                    return

            raise ValueError(f"#Mann= block not found for {river}/{reach}/RS {rs}")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing Manning's n: {str(e)}")
            raise IOError(f"Failed to write Manning's n: {str(e)}")

    @staticmethod
    @log_call
    def get_xs_coords(geom_file: Union[str, Path],
                     river: Optional[str] = None,
                     reach: Optional[str] = None,
                     rs: Optional[str] = None,
                     ras_object=None) -> pd.DataFrame:
        """
        Extract XYZ coordinates for cross sections from plain text geometry file.

        Combines GIS cut line geometry with station-elevation data to produce
        3D point coordinates along each cross section. This is the plain text
        equivalent of HdfXsec.get_cross_sections() for extracting XYZ points
        without requiring geometry HDF files.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            river (Optional[str]): Filter by specific river name. If None, returns all rivers.
            reach (Optional[str]): Filter by specific reach name. If None, returns all reaches.
            rs (Optional[str]): Filter by specific river station. If None, returns all stations.
            ras_object: Optional RasPrj instance for multi-project workflows (unused, for API consistency)

        Returns:
            pd.DataFrame: DataFrame with columns:
                - river (str): River name
                - reach (str): Reach name
                - RS (str): River station
                - station (float): Station along cross section (from left bank)
                - x (float): X coordinate
                - y (float): Y coordinate
                - z (float): Elevation

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ImportError: If geopandas or shapely are not installed
            ValueError: If no cross sections found matching filters

        Example:
            >>> # Extract XYZ for all cross sections
            >>> xyz = GeomCrossSection.get_xs_coords("model.g01")
            >>> print(f"Extracted {len(xyz)} total points")
            >>>
            >>> # Filter by river/reach
            >>> xyz_reach = GeomCrossSection.get_xs_coords("model.g01", river="Main River", reach="Upper")
            >>>
            >>> # Export to shapefile (LineStrings)
            >>> import geopandas as gpd
            >>> from shapely.geometry import LineString
            >>> xs_lines = []
            >>> for (r, rc, rs), group in xyz.groupby(['river', 'reach', 'RS']):
            ...     coords = list(zip(group['x'], group['y'], group['z']))
            ...     xs_lines.append({'river': r, 'reach': rc, 'RS': rs, 'geometry': LineString(coords)})
            >>> gdf = gpd.GeoDataFrame(xs_lines, crs="EPSG:26915")
            >>> gdf.to_file("cross_sections.shp")
        """
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        logger.info(f"Extracting XYZ coordinates from: {geom_file}")

        # Get GIS cut line geometries
        try:
            from shapely.geometry import LineString
        except ImportError:
            raise ImportError(
                "shapely is required for get_xs_coords(). "
                "Install with: pip install shapely"
            )

        cut_lines = GeomParser.get_xs_cut_lines(geom_file, ras_object=ras_object)

        if len(cut_lines) == 0:
            raise ValueError(f"No cross sections with GIS cut lines found in {geom_file}")

        # Apply filters
        if river:
            cut_lines = cut_lines[cut_lines['river'] == river]
        if reach:
            cut_lines = cut_lines[cut_lines['reach'] == reach]
        if rs:
            cut_lines = cut_lines[cut_lines['station'] == rs]

        if len(cut_lines) == 0:
            filter_desc = []
            if river:
                filter_desc.append(f"river='{river}'")
            if reach:
                filter_desc.append(f"reach='{reach}'")
            if rs:
                filter_desc.append(f"RS='{rs}'")
            raise ValueError(f"No cross sections found matching: {', '.join(filter_desc)}")

        logger.info(f"Processing {len(cut_lines)} cross sections")

        all_coords = []

        for idx, xs_row in cut_lines.iterrows():
            # Get station-elevation data
            try:
                sta_elev = GeomCrossSection.get_station_elevation(
                    geom_file,
                    xs_row['river'],
                    xs_row['reach'],
                    xs_row['station']
                )
            except ValueError as e:
                logger.warning(
                    f"Could not get station/elevation for "
                    f"{xs_row['river']}/{xs_row['reach']}/{xs_row['station']}: {e}"
                )
                continue

            if len(sta_elev) == 0:
                logger.warning(
                    f"Empty station/elevation data for "
                    f"{xs_row['river']}/{xs_row['reach']}/{xs_row['station']}"
                )
                continue

            # Get cut line geometry
            cut_line = xs_row['geometry']

            # Interpolate XY coordinates along cut line
            # Assumes stations increase from left to right (0 to max)
            max_station = sta_elev['Station'].max()
            min_station = sta_elev['Station'].min()

            # Handle edge case where all stations are the same
            if max_station == min_station:
                logger.warning(
                    f"All stations equal for {xs_row['river']}/{xs_row['reach']}/{xs_row['station']}, "
                    f"using cut line midpoint"
                )
                mid_pt = cut_line.interpolate(0.5, normalized=True)
                for _, pt in sta_elev.iterrows():
                    all_coords.append({
                        'river': xs_row['river'],
                        'reach': xs_row['reach'],
                        'RS': xs_row['station'],  # River Station (from cut_lines 'station' column)
                        'station': pt['Station'],  # Station along cross section (from sta/elev data)
                        'x': mid_pt.x,
                        'y': mid_pt.y,
                        'z': pt['Elevation']
                    })
                continue

            # Interpolate each point along the cut line
            for _, pt in sta_elev.iterrows():
                station = pt['Station']
                elevation = pt['Elevation']

                # Normalize station to [0, 1] range
                # Assumes cut line goes from left (station=min) to right (station=max)
                normalized_pos = (station - min_station) / (max_station - min_station)

                # Interpolate point along cut line
                interp_point = cut_line.interpolate(normalized_pos, normalized=True)

                all_coords.append({
                    'river': xs_row['river'],
                    'reach': xs_row['reach'],
                    'RS': xs_row['station'],  # River Station (from cut_lines 'station' column)
                    'station': station,  # Station along cross section (from sta/elev data)
                    'x': interp_point.x,
                    'y': interp_point.y,
                    'z': elevation
                })

        logger.info(f"Extracted {len(all_coords)} XYZ points from {len(cut_lines)} cross sections")

        return pd.DataFrame(all_coords)

    @staticmethod
    @log_call
    def get_xs_htab_params(geom_file: Union[str, Path],
                           river: str,
                           reach: str,
                           rs: str) -> dict:
        """
        Read cross section HTAB (hydraulic table) parameters from geometry file.

        HTAB parameters control how HEC-RAS pre-computes hydraulic properties
        (area, conveyance, storage) as a function of elevation. These tables are
        used during unsteady flow simulations for fast lookup via interpolation.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            river (str): River name (case-sensitive)
            reach (str): Reach name (case-sensitive)
            rs (str): River station (as string, e.g., "5280")

        Returns:
            dict with keys:
                - 'starting_el' (float or None): Starting elevation for HTAB
                - 'increment' (float or None): Elevation increment between points
                - 'num_points' (int or None): Number of points in HTAB
                - 'invert' (float): Lowest elevation in cross section
                - 'top' (float): Highest elevation in cross section
                - 'has_htab_lines' (bool): True if explicit HTAB lines found in file

        Notes:
            - Handles two geometry file formats:
              1. Combined format: "XS HTab Starting El and Incr=val1,val2, val3"
              2. Separate format: "HTAB Starting El and Incr=" and "HTAB Number of Points="
            - If HTAB lines are not present, starting_el/increment/num_points will be None
              (HEC-RAS uses defaults: starting=invert+0.5-1.0, increment=1.0, points~20)
            - invert/top are always computed from station-elevation data

        Example:
            >>> params = GeomCrossSection.get_xs_htab_params(
            ...     "Muncie.g01", "White", "Muncie", "15696.24"
            ... )
            >>> print(f"Starting El: {params['starting_el']}")
            >>> print(f"Increment: {params['increment']}")
            >>> print(f"Num Points: {params['num_points']}")
            >>> print(f"Invert: {params['invert']}, Top: {params['top']}")
            >>> if not params['has_htab_lines']:
            ...     print("No HTAB lines - using HEC-RAS defaults")
        """
        import re
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Regex patterns for both HTAB formats
        # Format 1 (combined): XS HTab Starting El and Incr=937.99,0.5, 100
        XS_HTAB_COMBINED_PATTERN = re.compile(
            r'^XS HTab Starting El and Incr=\s*([\d.+-]+)\s*,\s*([\d.+-]+)\s*,\s*(\d+)\s*$'
        )

        # Format 2 (separate lines):
        # HTAB Starting El and Incr=     580.0,      0.5
        # HTAB Number of Points= 100
        HTAB_START_PATTERN = re.compile(
            r'^HTAB Starting El and Incr=\s*([\d.+-]+)\s*,\s*([\d.+-]+)\s*$'
        )
        HTAB_POINTS_PATTERN = re.compile(
            r'^HTAB Number of Points=\s*(\d+)\s*$'
        )

        try:
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the cross section using helper
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(
                    f"Cross section not found: {river}/{reach}/RS {rs} in {geom_file.name}"
                )

            # Initialize result dict
            params = {
                'starting_el': None,
                'increment': None,
                'num_points': None,
                'invert': None,
                'top': None,
                'has_htab_lines': False
            }

            # Search forward from XS start
            # Need extended range because "XS HTab" combined format appears AFTER
            # station-elevation data, which can be 100+ lines for large XS
            max_search_range = 200  # Extended range for combined HTAB format
            for i in range(xs_idx, min(xs_idx + max_search_range, len(lines))):
                line = lines[i].rstrip('\n\r')

                # Stop at next XS or structure
                if line.startswith("River Reach=") and i > xs_idx + 5:
                    break
                if line.startswith("Type RM Length L Ch R =") and i > xs_idx + 5:
                    break

                # Try Format 1: Combined line (XS HTab Starting El and Incr=val1,val2, val3)
                match = XS_HTAB_COMBINED_PATTERN.match(line)
                if match:
                    params['starting_el'] = float(match.group(1))
                    params['increment'] = float(match.group(2))
                    params['num_points'] = int(match.group(3))
                    params['has_htab_lines'] = True
                    logger.debug(
                        f"Found combined HTAB format at line {i}: "
                        f"starting_el={params['starting_el']}, "
                        f"increment={params['increment']}, "
                        f"num_points={params['num_points']}"
                    )
                    continue

                # Try Format 2a: HTAB Starting El and Incr
                match = HTAB_START_PATTERN.match(line)
                if match:
                    params['starting_el'] = float(match.group(1))
                    params['increment'] = float(match.group(2))
                    params['has_htab_lines'] = True
                    logger.debug(
                        f"Found separate HTAB starting el at line {i}: "
                        f"starting_el={params['starting_el']}, increment={params['increment']}"
                    )
                    continue

                # Try Format 2b: HTAB Number of Points
                match = HTAB_POINTS_PATTERN.match(line)
                if match:
                    params['num_points'] = int(match.group(1))
                    params['has_htab_lines'] = True
                    logger.debug(f"Found separate HTAB num points at line {i}: {params['num_points']}")

            # Get invert/top from station-elevation data
            try:
                sta_elev_df = GeomCrossSection.get_station_elevation(
                    geom_file, river, reach, rs
                )
                if sta_elev_df is not None and len(sta_elev_df) > 0:
                    params['invert'] = float(sta_elev_df['Elevation'].min())
                    params['top'] = float(sta_elev_df['Elevation'].max())
                    logger.debug(f"Computed invert={params['invert']}, top={params['top']}")
            except Exception as e:
                logger.warning(f"Could not extract station-elevation data: {e}")
                # Continue without invert/top - they'll remain None

            logger.info(
                f"Extracted HTAB params for {river}/{reach}/RS {rs}: "
                f"has_htab_lines={params['has_htab_lines']}, "
                f"starting_el={params['starting_el']}, "
                f"increment={params['increment']}, "
                f"num_points={params['num_points']}"
            )

            return params

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error reading XS HTAB params: {str(e)}")
            raise IOError(f"Failed to read XS HTAB params: {str(e)}")

    @staticmethod
    @log_call
    def set_xs_htab_params(geom_file: Union[str, Path],
                           river: str,
                           reach: str,
                           rs: str,
                           starting_el: Optional[Union[float, str]] = None,
                           increment: Optional[float] = None,
                           num_points: Optional[int] = None) -> None:
        """
        Set cross section HTAB (hydraulic table) parameters in geometry file.

        This method modifies the HTAB parameters for a specific cross section,
        either replacing existing values or inserting new HTAB lines if they
        don't exist.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            river (str): River name (case-sensitive)
            reach (str): Reach name (case-sensitive)
            rs (str): River station (as string, e.g., "5280")
            starting_el (Optional[Union[float, str]]): Starting elevation:
                - float: Use this elevation value
                - 'invert': Copy the cross section's minimum elevation
                - None: No change (keep existing or HEC-RAS default)
            increment (Optional[float]): Elevation increment (0.1-2.0 typical)
                - None: No change (keep existing or HEC-RAS default)
            num_points (Optional[int]): Number of points (20-500)
                - None: No change (keep existing or HEC-RAS default)

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If cross section not found, or parameters invalid
            IOError: If file write fails

        Notes:
            - Only specified parameters are modified
            - If HTAB lines don't exist in the file, they are inserted
            - Geometry file is modified in-place with backup (.bak) created
            - HTAB lines are inserted after "Type RM Length" line, before
              "XS GIS Cut Line" or "#Sta/Elev"

        File Format:
            HTAB Starting El and Incr=     580.0,      0.1
            HTAB Number of Points= 500

        Example:
            >>> # Set optimal HTAB for single XS
            >>> GeomCrossSection.set_xs_htab_params(
            ...     "model.g01", "River", "Reach", "5280",
            ...     starting_el=580.0, increment=0.1, num_points=500
            ... )

            >>> # Copy invert as starting elevation
            >>> GeomCrossSection.set_xs_htab_params(
            ...     "model.g01", "River", "Reach", "5280",
            ...     starting_el='invert', increment=0.1, num_points=500
            ... )

            >>> # Only update increment (keep other values)
            >>> GeomCrossSection.set_xs_htab_params(
            ...     "model.g01", "River", "Reach", "5280",
            ...     increment=0.2
            ... )

        See Also:
            - get_xs_htab_params(): Read current HTAB parameters
            - GeomHtabUtils.validate_xs_htab_params(): Validate parameters
            - GeomHtabUtils.calculate_optimal_xs_htab(): Calculate optimal values
        """
        from .GeomHtabUtils import GeomHtabUtils

        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Get current HTAB params (for defaults and validation)
        current_params = GeomCrossSection.get_xs_htab_params(
            geom_file, river, reach, rs
        )

        # Handle 'invert' as starting_el
        final_starting_el = None
        xs_invert = current_params.get('invert')

        if starting_el is not None:
            if isinstance(starting_el, str) and starting_el.lower() == 'invert':
                if xs_invert is not None:
                    # Round invert UP to 0.01 ft precision to ensure starting_el >= invert
                    final_starting_el = math.ceil(xs_invert * 100) / 100
                    logger.info(
                        f"Using invert elevation as starting_el: {final_starting_el} "
                        f"(rounded up from {xs_invert})"
                    )
                else:
                    raise ValueError(
                        f"Cannot use 'invert' as starting_el: invert elevation "
                        f"not available for {river}/{reach}/RS {rs}"
                    )
            else:
                final_starting_el = float(starting_el)
                # Auto-fix: If starting_el < invert, round up to ensure >= invert
                if xs_invert is not None and final_starting_el < xs_invert:
                    corrected_el = math.ceil(xs_invert * 100) / 100
                    logger.info(
                        f"HTAB starting_el ({final_starting_el}) adjusted to {corrected_el} "
                        f"(>= invert {xs_invert}) for {river}/{reach}/RS {rs}"
                    )
                    final_starting_el = corrected_el

        final_increment = increment
        final_num_points = num_points

        # If no parameters specified, nothing to do
        if final_starting_el is None and final_increment is None and final_num_points is None:
            logger.warning(
                f"No HTAB parameters specified for {river}/{reach}/RS {rs}. "
                "Geometry file unchanged."
            )
            return

        # Build final parameters dict for validation
        # Use current values for any unspecified parameters
        params_to_write = {
            'starting_el': final_starting_el if final_starting_el is not None else current_params.get('starting_el'),
            'increment': final_increment if final_increment is not None else current_params.get('increment'),
            'num_points': final_num_points if final_num_points is not None else current_params.get('num_points')
        }

        # Check if we have enough to write
        # We need at least starting_el and increment for the first line
        # and num_points for the second line
        write_start_incr = params_to_write['starting_el'] is not None and params_to_write['increment'] is not None
        write_num_points = params_to_write['num_points'] is not None

        if not write_start_incr and not write_num_points:
            logger.warning(
                f"Insufficient parameters to write HTAB for {river}/{reach}/RS {rs}. "
                "Need at least (starting_el + increment) or num_points."
            )
            return

        # Validate parameters if we have a complete set
        if all(v is not None for v in params_to_write.values()):
            # Use xs_invert already retrieved above, default to 0 if still None
            validation_invert = xs_invert if xs_invert is not None else 0
            xs_top = current_params.get('top', validation_invert + 100)

            errors, warnings = GeomHtabUtils.validate_xs_htab_params(
                params_to_write, validation_invert, xs_top
            )

            if errors:
                raise ValueError(
                    f"Invalid HTAB parameters for {river}/{reach}/RS {rs}: "
                    f"{'; '.join(errors)}"
                )

            for warning in warnings:
                logger.warning(f"HTAB validation warning: {warning}")

        try:
            # Create backup
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Find the cross section
            xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)

            if xs_idx is None:
                raise ValueError(
                    f"Cross section not found: {river}/{reach}/RS {rs} in {geom_file.name}"
                )

            # Find existing HTAB lines and insertion point
            # HEC-RAS has TWO possible HTAB formats:
            # 1. Separate format (early in XS block): "HTAB Starting El and Incr=" + "HTAB Number of Points="
            # 2. Combined format (later in XS block): "XS HTab Starting El and Incr=val1,val2, val3"
            htab_start_idx = None       # Line index of "HTAB Starting El and Incr="
            htab_points_idx = None      # Line index of "HTAB Number of Points="
            xs_htab_combined_idx = None # Line index of "XS HTab Starting El and Incr=" (combined format)
            insert_idx = None           # Where to insert if not found

            # Extended search range - XS blocks can be 100+ lines with station/elevation data
            max_search_range = 200

            for i in range(xs_idx, min(xs_idx + max_search_range, len(lines))):
                line = lines[i]

                # Track "Type RM Length" as potential insertion point (insert after it)
                if line.startswith("Type RM Length") and i == xs_idx:
                    insert_idx = i + 1

                # Check for existing HTAB lines - separate format (near top of XS)
                if line.startswith("HTAB Starting El and Incr="):
                    htab_start_idx = i
                    # Also note where to insert num_points if needed
                    if insert_idx is None:
                        insert_idx = i + 1
                elif line.startswith("HTAB Number of Points="):
                    htab_points_idx = i

                # Check for combined format (later in XS, after bank stations)
                if line.startswith("XS HTab Starting El and Incr="):
                    xs_htab_combined_idx = i

                # Track insertion point - should be after Type RM Length, before XS GIS Cut Line
                if line.startswith("XS GIS Cut Line") or line.startswith("#Sta/Elev"):
                    if insert_idx is None:
                        insert_idx = i

                # Stop at next XS or river reach
                if line.startswith("River Reach=") and i > xs_idx + 5:
                    break
                if line.startswith("Type RM Length L Ch R =") and i > xs_idx + 5:
                    break

            # Build the HTAB lines to write
            modified_lines = lines.copy()

            # If combined format exists, we need to update it (it takes precedence in HEC-RAS)
            if xs_htab_combined_idx is not None:
                # Update the combined format line
                combined_line = f"XS HTab Starting El and Incr={params_to_write['starting_el']},{params_to_write['increment']}, {params_to_write['num_points']} \n"
                modified_lines[xs_htab_combined_idx] = combined_line
                logger.debug(f"Updated combined format XS HTab at line {xs_htab_combined_idx}")

                # If separate format lines also exist, update them for consistency
                if write_start_incr and htab_start_idx is not None:
                    htab_start_line = f"HTAB Starting El and Incr={params_to_write['starting_el']:10.1f},{params_to_write['increment']:10.4f}\n"
                    modified_lines[htab_start_idx] = htab_start_line
                    logger.debug(f"Also updated separate format HTAB at line {htab_start_idx}")

                if write_num_points and htab_points_idx is not None:
                    htab_points_line = f"HTAB Number of Points= {params_to_write['num_points']}\n"
                    modified_lines[htab_points_idx] = htab_points_line
                    logger.debug(f"Also updated separate format HTAB points at line {htab_points_idx}")
            else:
                # No combined format - use separate format
                # Handle "HTAB Starting El and Incr=" line
                if write_start_incr:
                    htab_start_line = f"HTAB Starting El and Incr={params_to_write['starting_el']:10.1f},{params_to_write['increment']:10.4f}\n"

                    if htab_start_idx is not None:
                        # Replace existing line
                        modified_lines[htab_start_idx] = htab_start_line
                        logger.debug(f"Replaced HTAB Starting El and Incr at line {htab_start_idx}")
                    else:
                        # Insert new line
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_start_line)
                            # Adjust indices if we inserted before other HTAB line
                            if htab_points_idx is not None and htab_points_idx >= insert_idx:
                                htab_points_idx += 1
                            insert_idx += 1  # Move insertion point for next line
                            logger.debug(f"Inserted HTAB Starting El and Incr at line {insert_idx - 1}")
                        else:
                            raise ValueError(
                                f"Could not find insertion point for HTAB lines in {river}/{reach}/RS {rs}"
                            )

                # Handle "HTAB Number of Points=" line
                if write_num_points:
                    htab_points_line = f"HTAB Number of Points= {params_to_write['num_points']}\n"

                    if htab_points_idx is not None:
                        # Replace existing line
                        modified_lines[htab_points_idx] = htab_points_line
                        logger.debug(f"Replaced HTAB Number of Points at line {htab_points_idx}")
                    else:
                        # Insert new line (after HTAB Starting El and Incr if we just inserted it)
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_points_line)
                            logger.debug(f"Inserted HTAB Number of Points at line {insert_idx}")
                        else:
                            raise ValueError(
                                f"Could not find insertion point for HTAB lines in {river}/{reach}/RS {rs}"
                            )

            # Write modified file
            with open(geom_file, 'w', encoding='utf-8') as f:
                f.writelines(modified_lines)

            logger.info(
                f"Updated HTAB params for {river}/{reach}/RS {rs}: "
                f"starting_el={params_to_write.get('starting_el')}, "
                f"increment={params_to_write.get('increment')}, "
                f"num_points={params_to_write.get('num_points')}"
            )

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error writing XS HTAB params: {str(e)}")
            # Attempt to restore from backup if write failed
            if backup_path and backup_path.exists():
                logger.info(f"Restoring from backup: {backup_path}")
                import shutil
                shutil.copy2(backup_path, geom_file)
            raise IOError(f"Failed to write XS HTAB params: {str(e)}")

    @staticmethod
    @log_call
    def set_all_xs_htab_params(geom_file: Union[str, Path],
                                starting_el: Union[float, str] = 'invert',
                                increment: float = 0.1,
                                num_points: int = 500,
                                create_backup: bool = True) -> dict:
        """
        Set HTAB parameters for ALL cross sections in geometry file.

        This method efficiently updates HTAB parameters for every cross section
        in a single file read/write cycle. It's optimized for batch operations
        on geometry files with many cross sections.

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            starting_el (Union[float, str]): Starting elevation for all XS:
                - float: Use this elevation for all cross sections
                - 'invert': Copy each XS's invert (minimum elevation) - RECOMMENDED
            increment (float): Elevation increment for all XS (default 0.1)
                              Typical values: 0.1-0.2 ft for fine resolution
            num_points (int): Number of points for all XS (default 500)
                             HEC-RAS maximum is 500
            create_backup (bool): Create .bak file before modifying (default True)

        Returns:
            dict: Summary of modifications with keys:
                - 'modified' (int): Number of cross sections successfully modified
                - 'skipped' (int): Number of cross sections skipped (no valid data)
                - 'backup' (Path or None): Path to backup file, or None if no backup
                - 'xs_details' (List[dict]): Per-XS details with river/reach/rs/starting_el

        Raises:
            FileNotFoundError: If geometry file doesn't exist
            ValueError: If invalid parameters (increment <= 0, num_points out of range)
            IOError: If file write fails

        Notes:
            - Processes all cross sections in a SINGLE file read/write cycle
            - Much more efficient than calling set_xs_htab_params() in a loop
            - When starting_el='invert', each XS gets its own invert elevation
            - Uses safe_write_geometry() for atomic write with backup
            - Handles both HTAB formats: separate lines and combined "XS HTab" format

        Performance:
            - Target: <5 seconds for 100 cross sections
            - Single file read, single file write

        Example:
            >>> # Set optimal HTAB for all XS (recommended settings)
            >>> result = GeomCrossSection.set_all_xs_htab_params(
            ...     "model.g01",
            ...     starting_el='invert',  # Copy each XS's invert
            ...     increment=0.1,
            ...     num_points=500
            ... )
            >>> print(f"Modified {result['modified']} cross sections")
            >>> print(f"Backup at: {result['backup']}")

            >>> # Set fixed starting elevation for all XS
            >>> result = GeomCrossSection.set_all_xs_htab_params(
            ...     "model.g01",
            ...     starting_el=580.0,  # Same starting el for all
            ...     increment=0.2,
            ...     num_points=250
            ... )

        See Also:
            - set_xs_htab_params(): Set HTAB for single XS
            - get_xs_htab_params(): Read current HTAB parameters
            - get_cross_sections(): List all XS in geometry file
        """
        import re
        import time

        start_time = time.time()
        geom_file = Path(geom_file)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        # Validate parameters
        if increment <= 0:
            raise ValueError(f"increment ({increment}) must be positive")

        if num_points < 20:
            raise ValueError(f"num_points ({num_points}) must be >= 20 (HEC-RAS minimum)")

        if num_points > 500:
            raise ValueError(f"num_points ({num_points}) must be <= 500 (HEC-RAS maximum)")

        # Regex patterns for both HTAB formats
        # Format 1 (combined): XS HTab Starting El and Incr=937.99,0.5, 100
        XS_HTAB_COMBINED_PATTERN = re.compile(
            r'^XS HTab Starting El and Incr=\s*([\d.+-]+)\s*,\s*([\d.+-]+)\s*,\s*(\d+)\s*$'
        )

        # Format 2 (separate lines):
        # HTAB Starting El and Incr=     580.0,      0.5
        # HTAB Number of Points= 100
        HTAB_START_PATTERN = re.compile(
            r'^HTAB Starting El and Incr='
        )
        HTAB_POINTS_PATTERN = re.compile(
            r'^HTAB Number of Points='
        )

        # XS identifier pattern
        STA_ELEV_PATTERN = re.compile(r'^#Sta/Elev=\s*(\d+)')

        try:
            # Step 1: Read entire file ONCE
            with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            logger.debug(f"Read {len(lines)} lines from {geom_file.name}")

            # Step 2: Get all cross sections using existing method
            xs_df = GeomCrossSection.get_cross_sections(geom_file)
            # Filter to Type 1 (real cross sections) only - excludes lateral
            # structures (Type 6), bridges, culverts, etc. which lack #Sta/Elev data
            if 'Type' in xs_df.columns:
                xs_df = xs_df[xs_df['Type'] == 1].reset_index(drop=True)
            logger.debug(f"Found {len(xs_df)} cross sections in geometry file")

            if len(xs_df) == 0:
                logger.warning(f"No cross sections found in {geom_file.name}")
                return {
                    'modified': 0,
                    'skipped': 0,
                    'backup': None,
                    'xs_details': []
                }

            # Step 3: Build index of XS locations and compute inverts
            # This avoids re-reading the file for each XS
            xs_info = []
            for _, row in xs_df.iterrows():
                river = row['River']
                reach = row['Reach']
                rs = row['RS']

                # Find XS start index
                xs_idx = GeomCrossSection._find_cross_section(lines, river, reach, rs)
                if xs_idx is None:
                    logger.warning(f"Could not find XS {river}/{reach}/RS {rs} in lines")
                    continue

                # Get station-elevation data to compute invert
                invert = None
                top = None
                for j in range(xs_idx, GeomCrossSection._find_xs_section_end(lines, xs_idx)):
                    match = STA_ELEV_PATTERN.match(lines[j])
                    if match:
                        count = int(match.group(1))
                        # Parse station-elevation data
                        sta_elev_df = GeomCrossSection._parse_paired_data(
                            lines, j + 1, count, 'Station', 'Elevation'
                        )
                        if len(sta_elev_df) > 0:
                            invert = float(sta_elev_df['Elevation'].min())
                            top = float(sta_elev_df['Elevation'].max())
                        break

                xs_info.append({
                    'river': river,
                    'reach': reach,
                    'rs': rs,
                    'line_idx': xs_idx,
                    'invert': invert,
                    'top': top
                })

            logger.info(f"Indexed {len(xs_info)} cross sections with location data")

            # Step 4: Process all XS and modify lines in place
            modified_count = 0
            skipped_count = 0
            xs_details = []
            modified_lines = lines.copy()

            # Track line offset due to insertions
            line_offset = 0

            for xs in xs_info:
                river = xs['river']
                reach = xs['reach']
                rs = xs['rs']
                xs_idx = xs['line_idx'] + line_offset
                xs_invert = xs['invert']
                xs_top = xs['top']

                # Determine starting elevation for this XS
                if isinstance(starting_el, str) and starting_el.lower() == 'invert':
                    if xs_invert is None:
                        logger.warning(
                            f"Cannot use 'invert' for {river}/{reach}/RS {rs}: "
                            "invert not available. Skipping."
                        )
                        skipped_count += 1
                        continue
                    # Round invert UP to 0.01 ft precision to ensure starting_el >= invert
                    final_starting_el = math.ceil(xs_invert * 100) / 100
                else:
                    final_starting_el = float(starting_el)
                    # Auto-fix: If starting_el < invert, round up to ensure >= invert
                    if xs_invert is not None and final_starting_el < xs_invert:
                        corrected_el = math.ceil(xs_invert * 100) / 100
                        logger.info(
                            f"HTAB starting_el ({final_starting_el}) adjusted to {corrected_el} "
                            f"(>= invert {xs_invert}) for {river}/{reach}/RS {rs}"
                        )
                        final_starting_el = corrected_el

                # Find HTAB lines for this XS
                htab_start_idx = None
                htab_points_idx = None
                xs_htab_combined_idx = None
                insert_idx = None

                # Extended search range
                max_search = min(xs_idx + 200, len(modified_lines))

                for i in range(xs_idx, max_search):
                    line = modified_lines[i]

                    # Track insertion point after "Type RM Length"
                    if line.startswith("Type RM Length") and i == xs_idx:
                        insert_idx = i + 1

                    # Check for existing HTAB lines
                    if HTAB_START_PATTERN.match(line):
                        htab_start_idx = i
                        if insert_idx is None:
                            insert_idx = i + 1

                    if HTAB_POINTS_PATTERN.match(line):
                        htab_points_idx = i

                    if XS_HTAB_COMBINED_PATTERN.match(line):
                        xs_htab_combined_idx = i

                    # Track insertion point before XS GIS Cut Line
                    if line.startswith("XS GIS Cut Line") or line.startswith("#Sta/Elev"):
                        if insert_idx is None:
                            insert_idx = i

                    # Stop at next XS
                    if line.startswith("River Reach=") and i > xs_idx + 5:
                        break
                    if line.startswith("Type RM Length L Ch R =") and i > xs_idx + 5:
                        break

                # Build HTAB lines to write
                htab_start_line = f"HTAB Starting El and Incr={final_starting_el:10.1f},{increment:10.4f}\n"
                htab_points_line = f"HTAB Number of Points= {num_points}\n"

                lines_added = 0

                # Handle combined format (takes precedence)
                if xs_htab_combined_idx is not None:
                    combined_line = f"XS HTab Starting El and Incr={final_starting_el},{increment}, {num_points} \n"
                    modified_lines[xs_htab_combined_idx] = combined_line

                    # Also update separate format if exists
                    if htab_start_idx is not None:
                        modified_lines[htab_start_idx] = htab_start_line
                    if htab_points_idx is not None:
                        modified_lines[htab_points_idx] = htab_points_line

                else:
                    # Use separate format
                    # Handle HTAB Starting El and Incr
                    if htab_start_idx is not None:
                        modified_lines[htab_start_idx] = htab_start_line
                    else:
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_start_line)
                            lines_added += 1
                            # Adjust indices for subsequent operations
                            if htab_points_idx is not None and htab_points_idx >= insert_idx:
                                htab_points_idx += 1
                            insert_idx += 1
                        else:
                            logger.warning(f"Could not find insertion point for {river}/{reach}/RS {rs}")
                            skipped_count += 1
                            continue

                    # Handle HTAB Number of Points
                    if htab_points_idx is not None:
                        modified_lines[htab_points_idx] = htab_points_line
                    else:
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_points_line)
                            lines_added += 1

                # Update line offset for subsequent XS
                line_offset += lines_added

                modified_count += 1
                xs_details.append({
                    'river': river,
                    'reach': reach,
                    'rs': rs,
                    'starting_el': final_starting_el,
                    'increment': increment,
                    'num_points': num_points
                })

            # Step 5: Write file ONCE using safe_write_geometry
            if modified_count > 0:
                backup_path = GeomParser.safe_write_geometry(
                    geom_file,
                    modified_lines,
                    create_backup=create_backup
                )
            else:
                backup_path = None
                logger.warning("No cross sections modified - file unchanged")

            elapsed_time = time.time() - start_time

            result = {
                'modified': modified_count,
                'skipped': skipped_count,
                'backup': backup_path,
                'xs_details': xs_details
            }

            logger.info(
                f"set_all_xs_htab_params complete: {modified_count} modified, "
                f"{skipped_count} skipped, {elapsed_time:.2f} seconds"
            )

            return result

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error in set_all_xs_htab_params: {str(e)}")
            raise IOError(f"Failed to set all XS HTAB params: {str(e)}")

    @staticmethod
    @log_call
    def optimize_xs_htab_from_results(
        geom_file: Union[str, Path],
        hdf_results_path: Union[str, Path],
        safety_factor: float = 1.3,
        increment: float = 0.1,
        num_points: int = 500,
        create_backup: bool = True
    ) -> dict:
        """
        Optimize cross section HTAB parameters based on existing HEC-RAS results.

        This method reads maximum water surface elevations from HDF results,
        computes optimal HTAB parameters for each cross section using appropriate
        safety factors, and writes the optimized parameters to the geometry file.

        Algorithm:
            1. Get all cross sections from geometry file
            2. Extract maximum WSE for each cross section from HDF results
            3. For each cross section:
               a. Get invert elevation from geometry
               b. Look up max WSE from HDF results
               c. Use GeomHtabUtils.calculate_optimal_xs_htab() to compute parameters
               d. Collect modification for batch write
            4. Write all modifications to geometry file (single write operation)
            5. Return summary statistics

        Parameters:
            geom_file (Union[str, Path]): Path to geometry file (.g##)
            hdf_results_path (Union[str, Path]): Path to plan HDF file with results
            safety_factor (float): Multiplier on max depth to provide buffer (default 1.3 = 30%)
                                   Recommended: 1.2-1.5 for typical floods, 2.0 for dam break
            increment (float): Maximum elevation increment in feet (default 0.1)
                              Smaller increments give more accurate interpolation
            num_points (int): Maximum number of points (default 500, HEC-RAS limit)
            create_backup (bool): Whether to create a .bak backup before modification (default True).
                                  Set to False when called from an orchestrator that manages its own backup.

        Returns:
            dict: Summary statistics with keys:
                - 'modified_count' (int): Number of cross sections modified
                - 'total_xs_count' (int): Total number of cross sections in geometry
                - 'skipped_count' (int): Number of XS skipped (no results or errors)
                - 'backup_path' (Path): Path to geometry backup file
                - 'min_increment' (float): Minimum increment used
                - 'max_increment' (float): Maximum increment used
                - 'avg_increment' (float): Average increment used
                - 'modifications' (List[dict]): Details of each modification

        Raises:
            FileNotFoundError: If geometry file or HDF file doesn't exist
            ValueError: If safety_factor < 1.0 or other invalid parameters
            IOError: If file read/write fails

        Example:
            >>> from ras_commander import RasExamples, init_ras_project, RasCmdr
            >>> from ras_commander.geom import GeomCrossSection
            >>>
            >>> # Extract and run example project
            >>> path = RasExamples.extract_project("Muncie", suffix="htab_opt")
            >>> init_ras_project(path, "7.0")
            >>> RasCmdr.compute_plan("01")  # Run to get results
            >>>
            >>> # Optimize HTAB from results
            >>> summary = GeomCrossSection.optimize_xs_htab_from_results(
            ...     path / "Muncie.g01",
            ...     path / "Muncie.p01.hdf",
            ...     safety_factor=1.3,
            ...     increment=0.1,
            ...     num_points=500
            ... )
            >>> print(f"Modified {summary['modified_count']} of {summary['total_xs_count']} XS")
            >>> print(f"Increment range: {summary['min_increment']:.2f} - {summary['max_increment']:.2f}")

        Notes:
            - Creates a single backup before any modifications
            - Cross sections without matching HDF results are skipped
            - Modifications are batched to minimize file I/O
            - Safety factor is applied to depth range (max_wse - invert), not absolute elevation

        See Also:
            - GeomHtabUtils.calculate_optimal_xs_htab(): Core calculation algorithm
            - set_xs_htab_params(): Write HTAB parameters for single XS
            - get_xs_htab_params(): Read current HTAB parameters
        """
        import re
        import time
        from .GeomHtabUtils import GeomHtabUtils
        from ..hdf.HdfResultsXsec import HdfResultsXsec

        start_time = time.time()
        geom_file = Path(geom_file)
        hdf_results_path = Path(hdf_results_path)

        # Validate inputs
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not hdf_results_path.exists():
            raise FileNotFoundError(f"HDF results file not found: {hdf_results_path}")

        if safety_factor < 1.0:
            raise ValueError(f"safety_factor ({safety_factor}) must be >= 1.0")

        if num_points < GeomHtabUtils.MIN_XS_POINTS or num_points > GeomHtabUtils.MAX_XS_POINTS:
            raise ValueError(
                f"num_points ({num_points}) must be between {GeomHtabUtils.MIN_XS_POINTS} "
                f"and {GeomHtabUtils.MAX_XS_POINTS}"
            )

        if increment <= 0:
            raise ValueError(f"increment ({increment}) must be positive")

        logger.info(
            f"Optimizing XS HTAB from results: geom={geom_file.name}, "
            f"hdf={hdf_results_path.name}, safety={safety_factor}, "
            f"increment={increment}, num_points={num_points}"
        )

        # Step 1: Get all cross sections from geometry file
        xs_df = GeomCrossSection.get_cross_sections(geom_file)
        # Filter to Type 1 (real cross sections) only - excludes lateral
        # structures (Type 6), bridges, culverts, etc. which lack #Sta/Elev data
        if 'Type' in xs_df.columns:
            xs_df = xs_df[xs_df['Type'] == 1].reset_index(drop=True)
        total_xs_count = len(xs_df)

        if total_xs_count == 0:
            logger.warning(f"No cross sections found in {geom_file.name}")
            return {
                'modified_count': 0,
                'total_xs_count': 0,
                'skipped_count': 0,
                'backup_path': None,
                'min_increment': increment,
                'max_increment': increment,
                'avg_increment': increment,
                'modifications': []
            }

        logger.debug(f"Found {total_xs_count} cross sections in geometry file")

        # Step 2: Extract maximum WSE from HDF results
        try:
            xsec_results = HdfResultsXsec.get_xsec_timeseries(hdf_results_path)

            # Build lookup dictionary with multiple key formats
            # The HDF results use format: "River Reach RS" in cross_section names
            # Plus River/Reach/Station as separate coordinate arrays
            max_wse_lookup = {}

            if 'Maximum_Water_Surface' in xsec_results.coords:
                xs_names = xsec_results.coords['cross_section'].values
                rivers = xsec_results.coords['River'].values
                reaches = xsec_results.coords['Reach'].values
                stations = xsec_results.coords['Station'].values
                max_wses = xsec_results.coords['Maximum_Water_Surface'].values

                for idx in range(len(xs_names)):
                    max_wse = float(max_wses[idx])

                    # Store by cross_section name (full string)
                    xs_name = str(xs_names[idx])
                    max_wse_lookup[xs_name] = max_wse

                    # Store by (River, Reach, Station) tuple
                    river = str(rivers[idx])
                    reach = str(reaches[idx])
                    station = str(stations[idx])
                    key = (river, reach, station)
                    max_wse_lookup[key] = max_wse

            logger.info(f"Extracted max WSE for {len(max_wse_lookup) // 2} cross sections from HDF")

        except Exception as e:
            logger.error(f"Failed to extract cross section results from HDF: {e}")
            raise IOError(f"Failed to read HDF results: {e}")

        # Step 3: Read geometry file once and prepare for modifications
        with open(geom_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Regex patterns for HTAB lines
        HTAB_START_PATTERN = re.compile(r'^HTAB Starting El and Incr=')
        HTAB_POINTS_PATTERN = re.compile(r'^HTAB Number of Points=')
        XS_HTAB_COMBINED_PATTERN = re.compile(
            r'^XS HTab Starting El and Incr=\s*([\d.+-]+)\s*,\s*([\d.+-]+)\s*,\s*(\d+)\s*$'
        )
        STA_ELEV_PATTERN = re.compile(r'^#Sta/Elev=\s*(\d+)')

        # Step 4: Create backup ONCE before any modifications (if requested)
        backup_path = None
        if create_backup:
            backup_path = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {backup_path}")

        # Step 5: Calculate optimal parameters for each XS and collect modifications
        modifications = []
        skipped_count = 0
        increments_used = []
        modified_lines = lines.copy()
        line_offset = 0

        for _, xs_row in xs_df.iterrows():
            river = xs_row['River']
            reach = xs_row['Reach']
            rs = xs_row['RS']

            # Try multiple lookup key formats
            max_wse = None

            # Try (River, Reach, RS) tuple
            lookup_key = (river, reach, rs)
            max_wse = max_wse_lookup.get(lookup_key)

            if max_wse is None:
                # Try alternate lookup with various string formats
                for key, value in max_wse_lookup.items():
                    if isinstance(key, str):
                        # Key might be "River Reach RS" or other format
                        if river in key and reach in key and rs in key:
                            max_wse = value
                            break

            if max_wse is None:
                logger.debug(f"No HDF results for XS {river}/{reach}/RS {rs}, skipping")
                skipped_count += 1
                continue

            # Find XS in lines and get invert
            xs_idx = GeomCrossSection._find_cross_section(modified_lines, river, reach, rs)
            if xs_idx is None:
                logger.warning(f"XS {river}/{reach}/RS {rs} not found in geometry file, skipping")
                skipped_count += 1
                continue

            # Adjust for any previously inserted lines
            xs_idx_adjusted = xs_idx

            # Get invert from station-elevation data
            invert = None
            for j in range(xs_idx_adjusted, GeomCrossSection._find_xs_section_end(modified_lines, xs_idx_adjusted)):
                match = STA_ELEV_PATTERN.match(modified_lines[j])
                if match:
                    count = int(match.group(1))
                    sta_elev_df = GeomCrossSection._parse_paired_data(
                        modified_lines, j + 1, count, 'Station', 'Elevation'
                    )
                    if len(sta_elev_df) > 0:
                        invert = float(sta_elev_df['Elevation'].min())
                    break

            if invert is None:
                logger.warning(f"Could not determine invert for {river}/{reach}/RS {rs}, skipping")
                skipped_count += 1
                continue

            # Validate max_wse > invert
            if max_wse <= invert:
                logger.warning(
                    f"Max WSE ({max_wse}) <= invert ({invert}) for {river}/{reach}/RS {rs}, skipping"
                )
                skipped_count += 1
                continue

            # Calculate optimal HTAB parameters
            try:
                optimal_params = GeomHtabUtils.calculate_optimal_xs_htab(
                    invert=invert,
                    max_wse=max_wse,
                    safety_factor=safety_factor,
                    target_increment=increment,
                    max_points=num_points
                )

                final_starting_el = optimal_params['starting_el']
                final_increment = optimal_params['increment']
                final_num_points = optimal_params['num_points']

                # Find and update HTAB lines for this XS
                htab_start_idx = None
                htab_points_idx = None
                xs_htab_combined_idx = None
                insert_idx = None

                max_search = min(xs_idx_adjusted + 200, len(modified_lines))

                for i in range(xs_idx_adjusted, max_search):
                    line = modified_lines[i]

                    if line.startswith("Type RM Length") and i == xs_idx_adjusted:
                        insert_idx = i + 1

                    if HTAB_START_PATTERN.match(line):
                        htab_start_idx = i
                        if insert_idx is None:
                            insert_idx = i + 1

                    if HTAB_POINTS_PATTERN.match(line):
                        htab_points_idx = i

                    if XS_HTAB_COMBINED_PATTERN.match(line):
                        xs_htab_combined_idx = i

                    if line.startswith("XS GIS Cut Line") or line.startswith("#Sta/Elev"):
                        if insert_idx is None:
                            insert_idx = i

                    if line.startswith("River Reach=") and i > xs_idx_adjusted + 5:
                        break
                    if line.startswith("Type RM Length L Ch R =") and i > xs_idx_adjusted + 5:
                        break

                # Build HTAB lines
                htab_start_line = f"HTAB Starting El and Incr={final_starting_el:10.1f},{final_increment:10.4f}\n"
                htab_points_line = f"HTAB Number of Points= {final_num_points}\n"

                lines_added = 0

                # Handle combined format
                if xs_htab_combined_idx is not None:
                    combined_line = f"XS HTab Starting El and Incr={final_starting_el},{final_increment}, {final_num_points} \n"
                    modified_lines[xs_htab_combined_idx] = combined_line

                    if htab_start_idx is not None:
                        modified_lines[htab_start_idx] = htab_start_line
                    if htab_points_idx is not None:
                        modified_lines[htab_points_idx] = htab_points_line

                else:
                    # Use separate format
                    if htab_start_idx is not None:
                        modified_lines[htab_start_idx] = htab_start_line
                    else:
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_start_line)
                            lines_added += 1
                            if htab_points_idx is not None and htab_points_idx >= insert_idx:
                                htab_points_idx += 1
                            insert_idx += 1

                    if htab_points_idx is not None:
                        modified_lines[htab_points_idx] = htab_points_line
                    else:
                        if insert_idx is not None:
                            modified_lines.insert(insert_idx, htab_points_line)
                            lines_added += 1

                line_offset += lines_added

                modifications.append({
                    'river': river,
                    'reach': reach,
                    'rs': rs,
                    'invert': invert,
                    'max_wse': max_wse,
                    'starting_el': final_starting_el,
                    'increment': final_increment,
                    'num_points': final_num_points,
                    'actual_max_el': optimal_params['actual_max_el'],
                    'target_max_el': optimal_params['target_max_el']
                })

                increments_used.append(final_increment)

            except Exception as e:
                logger.warning(f"Error calculating optimal params for {river}/{reach}/RS {rs}: {e}")
                skipped_count += 1
                continue

        logger.info(
            f"Calculated optimal HTAB for {len(modifications)} cross sections, "
            f"skipped {skipped_count}"
        )

        # Step 6: Write all modifications to geometry file
        if modifications:
            try:
                with open(geom_file, 'w', encoding='utf-8') as f:
                    f.writelines(modified_lines)

                logger.info(f"Wrote {len(modifications)} HTAB modifications to {geom_file.name}")

            except Exception as e:
                logger.error(f"Error writing modifications: {e}")
                # Restore from backup
                if backup_path and backup_path.exists():
                    import shutil
                    logger.info(f"Restoring from backup: {backup_path}")
                    shutil.copy2(backup_path, geom_file)
                raise IOError(f"Failed to write HTAB modifications: {e}")

        # Calculate summary statistics
        if increments_used:
            min_increment = min(increments_used)
            max_increment = max(increments_used)
            avg_increment = sum(increments_used) / len(increments_used)
        else:
            min_increment = max_increment = avg_increment = increment

        elapsed_time = time.time() - start_time

        summary = {
            'modified_count': len(modifications),
            'total_xs_count': total_xs_count,
            'skipped_count': skipped_count,
            'backup_path': backup_path,
            'min_increment': round(min_increment, 4),
            'max_increment': round(max_increment, 4),
            'avg_increment': round(avg_increment, 4),
            'modifications': modifications,
            'elapsed_time': round(elapsed_time, 2)
        }

        logger.info(
            f"HTAB optimization complete: {summary['modified_count']} of {summary['total_xs_count']} "
            f"XS modified, increment range {summary['min_increment']}-{summary['max_increment']}, "
            f"{elapsed_time:.2f} seconds"
        )

        return summary
