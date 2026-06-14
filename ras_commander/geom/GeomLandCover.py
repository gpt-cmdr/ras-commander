"""
GeomLandCover - 2D Manning's n land cover operations

This module provides functionality for reading and modifying Manning's n
roughness values for 2D flow areas in HEC-RAS geometry files. These values
are associated with land cover classifications.

All methods are static and designed to be used without instantiation.

List of Functions:
- get_base_mannings_n() - Read base Manning's n table from geometry file
- set_base_mannings_n() - Write base Manning's n values to geometry file
- replace_base_mannings_n() - Replace or create a base Manning's n class table
- get_region_mannings_n() - Read Manning's n region overrides
- set_region_mannings_n() - Write regional Manning's n overrides
- set_mannings_region_polygons() - Write regional Manning's n polygon geometry
- override_2d_mannings_n() - EXPERIMENTAL: Override preprocessed Manning's n in geometry HDF

Example Usage:
    >>> from ras_commander import GeomLandCover, RasPlan
    >>>
    >>> # Get base Manning's n values
    >>> geom_path = RasPlan.get_geom_path("01")
    >>> mannings_df = GeomLandCover.get_base_mannings_n(geom_path)
    >>> print(mannings_df)
    >>>
    >>> # Modify and write back
    >>> mannings_df['Base Mannings n Value'] *= 1.1  # Increase by 10%
    >>> GeomLandCover.set_base_mannings_n(geom_path, mannings_df)
"""

import math
from pathlib import Path
from typing import Any, Optional, Union
import pandas as pd

from ..LoggingConfig import get_logger
from ..Decorators import log_call
from .GeomParser import GeomParser

logger = get_logger(__name__)


class GeomLandCover:
    """
    A class for 2D Manning's n land cover operations in HEC-RAS geometry files.

    All methods are static and designed to be used without instantiation.
    """

    _TABLE_END_PREFIXES = (
        'LCMann',
        'Chan Stop',
        'Geom Raster',
        'GIS ',
        'Use User',
        'User Specified',
    )

    _NAME_COLUMNS = (
        'Land Cover Name',
        'land_cover_name',
        'class_name',
        'Class Name',
        'Name',
    )

    _N_VALUE_COLUMNS = (
        'Base Mannings n Value',
        "Base Manning's n Value",
        'mannings_n',
        'ManningsN',
        'n_value',
        "Manning's n",
        'Mannings n',
    )

    _REGION_NAME_COLUMNS = (
        'Name',
        'Region Name',
        'region_name',
        'name',
    )

    _REGION_COORD_FIELD_WIDTH = 16
    _REGION_COORD_VALUES_PER_LINE = 4

    _REGION_FOLLOWING_PREFIXES = (
        'LCMann Table=',
        'LCMann Time=',
        'LCMann Region Time=',
        'Chan Stop',
        'Geom Raster',
        'GIS ',
        'Use User',
        'User Specified',
    )

    @staticmethod
    def _first_existing_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> Optional[str]:
        for candidate in candidates:
            if candidate in df.columns:
                return candidate
        return None

    @staticmethod
    def _normalize_base_table(
        mannings_data: Any,
        table_number: Optional[Union[str, int]] = None,
    ) -> tuple[str, pd.DataFrame]:
        df = pd.DataFrame(mannings_data).copy()
        if df.empty:
            raise ValueError("Manning's n table cannot be empty")

        name_col = GeomLandCover._first_existing_column(df, GeomLandCover._NAME_COLUMNS)
        value_col = GeomLandCover._first_existing_column(df, GeomLandCover._N_VALUE_COLUMNS)
        if name_col is None or value_col is None:
            raise ValueError(
                "Manning's n data must include land-cover name and n-value columns"
            )

        if table_number is None:
            if 'Table Number' in df.columns and not df['Table Number'].dropna().empty:
                table_number = str(df['Table Number'].dropna().iloc[0])
            else:
                table_number = "16"
        table_number = str(table_number)

        normalized = pd.DataFrame(
            {
                'Table Number': table_number,
                'Land Cover Name': df[name_col].astype(str).str.strip(),
                'Base Mannings n Value': pd.to_numeric(df[value_col], errors='coerce'),
            }
        )
        normalized = normalized.loc[
            (normalized['Land Cover Name'] != "")
            & normalized['Base Mannings n Value'].notna()
        ].copy()
        if normalized.empty:
            raise ValueError("Manning's n table has no writable rows")
        return table_number, normalized

    @staticmethod
    def _region_polygon_count(line: str) -> int:
        value = line.split("=", 1)[1].strip()
        return int(value.split(",", 1)[0])

    @staticmethod
    def _is_region_following_line(line: str) -> bool:
        stripped = line.strip()
        return bool(stripped) and any(
            stripped.startswith(prefix)
            for prefix in GeomLandCover._REGION_FOLLOWING_PREFIXES
        )

    @staticmethod
    def _parse_region_coord_values(line: str) -> list[float]:
        """Parse one fixed-width Manning's region polygon coordinate line."""
        stripped = line.strip()
        if not stripped:
            return []

        try:
            fixed_values = GeomParser.parse_fixed_width(
                line,
                column_width=GeomLandCover._REGION_COORD_FIELD_WIDTH,
            )
        except Exception:
            fixed_values = []

        split_values = []
        parts = stripped.split()
        if len(parts) > 1:
            try:
                split_values = [float(part) for part in parts]
            except ValueError:
                split_values = []

        return fixed_values if len(fixed_values) >= len(split_values) else split_values

    @staticmethod
    def _region_polygon_data_end(lines: list[str], polygon_idx: int) -> int:
        """Return the exclusive end index for an ``LCMann Region Polygon`` block."""
        try:
            point_count = GeomLandCover._region_polygon_count(lines[polygon_idx])
        except (IndexError, ValueError):
            return polygon_idx + 1

        required_values = point_count * 2
        values_read = 0
        idx = polygon_idx + 1

        while idx < len(lines) and values_read < required_values:
            stripped = lines[idx].strip()
            if (
                stripped.startswith("LCMann")
                or GeomLandCover._is_region_following_line(lines[idx])
            ):
                break

            values = GeomLandCover._parse_region_coord_values(lines[idx])
            if stripped and not values:
                break
            values_read += len(values)
            idx += 1

        return idx

    @staticmethod
    def _find_region_blocks(lines: list[str]) -> list[dict[str, Any]]:
        """Locate Manning's n region blocks and their optional polygon ranges."""
        starts: list[tuple[int, str]] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("LCMann Region Name="):
                starts.append((idx, stripped.split("=", 1)[1].strip()))

        blocks: list[dict[str, Any]] = []
        for pos, (start_idx, name) in enumerate(starts):
            next_region_idx = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
            end_idx = next_region_idx
            polygon_idx = None
            polygon_end_idx = None

            idx = start_idx + 1
            while idx < next_region_idx:
                stripped = lines[idx].strip()
                if stripped.startswith("LCMann Region Polygon="):
                    polygon_idx = idx
                    polygon_end_idx = GeomLandCover._region_polygon_data_end(lines, idx)
                    idx = polygon_end_idx
                    continue

                if GeomLandCover._is_region_following_line(lines[idx]):
                    end_idx = idx
                    break
                idx += 1

            blocks.append(
                {
                    "name": name,
                    "start_idx": start_idx,
                    "end_idx": end_idx,
                    "polygon_idx": polygon_idx,
                    "polygon_end_idx": polygon_end_idx,
                }
            )

        return blocks

    @staticmethod
    def _find_region_block(lines: list[str], region_name: str) -> Optional[dict[str, Any]]:
        matches = [
            block
            for block in GeomLandCover._find_region_blocks(lines)
            if block["name"] == region_name
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Multiple Manning's n region blocks named {region_name!r}; "
                "duplicate region names cannot be updated unambiguously"
            )
        return matches[0] if matches else None

    @staticmethod
    def _find_region_insert_idx(lines: list[str]) -> int:
        blocks = GeomLandCover._find_region_blocks(lines)
        if blocks:
            return blocks[-1]["end_idx"]

        table_start, table_end, _ = GeomLandCover._find_lcmann_table_bounds(lines)
        if table_start is not None and table_end is not None:
            return table_end

        for idx, line in enumerate(lines):
            if GeomLandCover._is_region_following_line(line):
                return idx
        return len(lines)

    @staticmethod
    def _max_precision_for_field(value: float, column_width: int) -> int:
        sign_chars = 1 if value < 0 else 0
        integer_digits = len(str(int(abs(value)))) if abs(value) >= 1 else 1
        max_precision = max(0, column_width - sign_chars - integer_digits - 1)

        for precision in range(max_precision, -1, -1):
            if len(f"{value:{column_width}.{precision}f}") <= column_width:
                return precision
        return 0

    @staticmethod
    def _format_region_coord_value(value: float) -> str:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"Region polygon coordinate must be finite, got {value!r}")

        column_width = GeomLandCover._REGION_COORD_FIELD_WIDTH
        precision = GeomLandCover._max_precision_for_field(value, column_width)
        formatted = f"{value:{column_width}.{precision}f}"
        if len(formatted) > column_width:
            raise ValueError(
                f"Region polygon coordinate {value!r} does not fit in "
                f"{column_width}-character HEC-RAS field"
            )
        return formatted

    @staticmethod
    def _format_region_coord_lines(coords: list[tuple[float, float]]) -> list[str]:
        flat_values: list[float] = []
        for x_coord, y_coord in coords:
            flat_values.extend([float(x_coord), float(y_coord)])

        lines = []
        values_per_line = GeomLandCover._REGION_COORD_VALUES_PER_LINE
        for idx in range(0, len(flat_values), values_per_line):
            row_values = flat_values[idx:idx + values_per_line]
            lines.append(
                "".join(
                    GeomLandCover._format_region_coord_value(value)
                    for value in row_values
                ) + "\n"
            )
        return lines

    @staticmethod
    def _polygon_coords_from_geometry(geometry: Any) -> list[tuple[float, float]]:
        from shapely.geometry import MultiPolygon, Polygon

        if geometry is None or getattr(geometry, "is_empty", False):
            raise ValueError("Region polygon geometry cannot be empty")

        if isinstance(geometry, Polygon):
            polygons = [geometry]
            close_parts = False
        elif isinstance(geometry, MultiPolygon):
            polygons = list(geometry.geoms)
            close_parts = len(polygons) > 1
        else:
            geom_type = getattr(geometry, "geom_type", type(geometry).__name__)
            raise ValueError(
                "Manning's n region geometry must be a Polygon or MultiPolygon, "
                f"got {geom_type}"
            )

        if not polygons:
            raise ValueError("Region polygon geometry cannot be empty")

        coords: list[tuple[float, float]] = []
        for polygon in polygons:
            if polygon.interiors:
                raise ValueError(
                    "Plain-text LCMann Region Polygon blocks do not encode "
                    "interior rings; provide polygons without holes"
                )

            ring = list(polygon.exterior.coords)
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            if len(ring) < 3:
                raise ValueError("Region polygon must have at least three vertices")

            coords.extend((float(x), float(y)) for x, y in ring)
            if close_parts:
                coords.append((float(ring[0][0]), float(ring[0][1])))

        return coords

    @staticmethod
    def _format_region_polygon_block(coords: list[tuple[float, float]]) -> list[str]:
        return (
            [f"LCMann Region Polygon={len(coords)}\n"]
            + GeomLandCover._format_region_coord_lines(coords)
        )

    @staticmethod
    def _format_region_table_rows(base_table: pd.DataFrame) -> list[str]:
        rows = []
        for _, row in base_table.iterrows():
            n_value = float(row['Base Mannings n Value'])
            rows.append(f"{row['Land Cover Name']},{n_value:g}\n")
        return rows

    @staticmethod
    def _ensure_region_time_line(lines: list[str], insert_idx: int) -> list[str]:
        if any(line.strip().startswith("LCMann Region Time=") for line in lines):
            return lines

        for idx, line in enumerate(lines):
            if line.strip().startswith("LCMann Time="):
                return (
                    lines[:idx + 1]
                    + ["LCMann Region Time=Dec/30/1899 00:00:00\n"]
                    + lines[idx + 1:]
                )

        for idx, line in enumerate(lines):
            if line.strip().startswith(("LCMann Table=", "LCMann Region Name=")):
                return (
                    lines[:idx]
                    + ["LCMann Region Time=Dec/30/1899 00:00:00\n"]
                    + lines[idx:]
                )

        return (
            lines[:insert_idx]
            + ["LCMann Region Time=Dec/30/1899 00:00:00\n"]
            + lines[insert_idx:]
        )

    @staticmethod
    def _update_region_time(lines: list[str]) -> list[str]:
        import datetime

        current_time = datetime.datetime.now().strftime("%b/%d/%Y %H:%M:%S")
        for idx, line in enumerate(lines):
            if line.strip().startswith("LCMann Region Time="):
                lines[idx] = f"LCMann Region Time={current_time}\n"
                break
        return lines

    @staticmethod
    def _find_lcmann_table_bounds(
        lines: list[str],
        table_number: Optional[str] = None,
    ) -> tuple[Optional[int], Optional[int], Optional[str]]:
        start_idx = None
        resolved_table_number = table_number

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("LCMann Table="):
                continue
            candidate_table_number = stripped.split("=", 1)[1].strip()
            if table_number is None or candidate_table_number == str(table_number):
                start_idx = i
                resolved_table_number = candidate_table_number
                break

        if start_idx is None:
            return None, None, resolved_table_number

        end_idx = len(lines)
        for j in range(start_idx + 1, len(lines)):
            stripped = lines[j].strip()
            if stripped and any(
                stripped.startswith(prefix)
                for prefix in GeomLandCover._TABLE_END_PREFIXES
            ):
                end_idx = j
                break
        return start_idx, end_idx, resolved_table_number

    @staticmethod
    @log_call
    def get_base_mannings_n(geom_file_path: Union[str, Path]) -> pd.DataFrame:
        """
        Reads the base Manning's n table from a HEC-RAS geometry file.

        Parameters:
            geom_file_path (Union[str, Path]): Path to the geometry file (.g##)

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Table Number (str): Manning's n table identifier
                - Land Cover Name (str): Name of the land cover type
                - Base Mannings n Value (float): Manning's n roughness coefficient

        Example:
            >>> geom_path = RasPlan.get_geom_path("01")
            >>> mannings_df = GeomLandCover.get_base_mannings_n(geom_path)
            >>> print(mannings_df)
        """
        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)

        base_table_rows = []
        table_number = None

        # Read the geometry file
        with open(geom_file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Parse the file
        reading_base_table = False
        for line in lines:
            line = line.strip()

            # Find the table number
            if line.startswith('LCMann Table='):
                table_number = line.split('=')[1]
                reading_base_table = True
                continue

            # Stop reading when we hit a line without a comma, starting with LCMann,
            # or starting with a known non-land-cover directive (e.g. Chan Stop, Geom
            # Raster, GIS, Use User, User Specified).  This prevents over-reading into
            # background raster entries that also contain commas.
            if reading_base_table:
                _stop = (
                    not ',' in line
                    or line.startswith('LCMann')
                    or line.startswith('Chan Stop')
                    or line.startswith('Geom Raster')
                    or line.startswith('GIS ')
                    or line.startswith('Use User')
                    or line.startswith('User Specified')
                )
                if _stop:
                    reading_base_table = False
                    continue

            # Parse data rows in base table
            if reading_base_table and ',' in line:
                # Check if there are multiple commas in the line
                parts = line.split(',')
                if len(parts) > 2:
                    # Handle case where land cover name contains commas
                    name = ','.join(parts[:-1])
                    value = parts[-1]
                else:
                    name, value = parts

                try:
                    base_table_rows.append([table_number, name, float(value)])
                except ValueError:
                    # Log the error and continue
                    logger.warning(f"Error parsing line: {line}")
                    continue

        # Create DataFrame
        # Note: Column uses "Mannings" (no apostrophe) for simplicity in DataFrame operations,
        # though HEC-RAS HDF files use "Manning's n" (with apostrophe) as the proper technical term.
        if base_table_rows:
            df = pd.DataFrame(base_table_rows, columns=['Table Number', 'Land Cover Name', 'Base Mannings n Value'])
            return df
        else:
            return pd.DataFrame(columns=['Table Number', 'Land Cover Name', 'Base Mannings n Value'])

    @staticmethod
    @log_call
    def set_base_mannings_n(geom_file_path: Union[str, Path], mannings_data: pd.DataFrame) -> bool:
        """
        Writes base Manning's n values to a HEC-RAS geometry file.

        Parameters:
            geom_file_path (Union[str, Path]): Path to the geometry file (.g##)
            mannings_data (pd.DataFrame): DataFrame with columns:
                - Table Number (str): Manning's n table identifier
                - Land Cover Name (str): Name of the land cover type
                - Base Mannings n Value (float): Manning's n roughness coefficient

        Returns:
            bool: True if successful

        Raises:
            ValueError: If land cover names don't match between file and DataFrame
        """
        import shutil
        import datetime

        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)

        # Create backup
        backup_path = geom_file_path.with_suffix(geom_file_path.suffix + '.bak')
        shutil.copy2(geom_file_path, backup_path)

        # Read the entire file
        with open(geom_file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Find the Manning's table section
        table_number = str(mannings_data['Table Number'].iloc[0])
        start_idx = None
        end_idx = None

        for i, line in enumerate(lines):
            if line.strip() == f"LCMann Table={table_number}":
                start_idx = i
                # Find the end of this table (next LCMann directive, a known
                # non-land-cover line, or end of file)
                for j in range(i+1, len(lines)):
                    stripped = lines[j].strip()
                    if stripped and any(stripped.startswith(p) for p in GeomLandCover._TABLE_END_PREFIXES):
                        end_idx = j
                        break
                if end_idx is None:  # If we reached the end of the file
                    end_idx = len(lines)
                break

        if start_idx is None:
            raise ValueError(f"Manning's table {table_number} not found in the geometry file")

        # Extract existing land cover names from the file
        existing_landcover = []
        for i in range(start_idx+1, end_idx):
            line = lines[i].strip()
            if ',' in line:
                parts = line.split(',')
                if len(parts) > 2:
                    # Handle case where land cover name contains commas
                    name = ','.join(parts[:-1])
                else:
                    name = parts[0]
                existing_landcover.append(name)

        # Check if all land cover names in the dataframe match the file
        df_landcover = mannings_data['Land Cover Name'].tolist()
        if set(df_landcover) != set(existing_landcover):
            missing = set(existing_landcover) - set(df_landcover)
            extra = set(df_landcover) - set(existing_landcover)
            error_msg = "Land cover names don't match between file and dataframe.\n"
            if missing:
                error_msg += f"Missing in dataframe: {missing}\n"
            if extra:
                error_msg += f"Extra in dataframe: {extra}"
            raise ValueError(error_msg)

        # Create new content for the table
        new_content = [f"LCMann Table={table_number}\n"]

        # Add base table entries
        for _, row in mannings_data.iterrows():
            new_content.append(f"{row['Land Cover Name']},{row['Base Mannings n Value']}\n")

        # Replace the section in the original file
        updated_lines = lines[:start_idx] + new_content + lines[end_idx:]

        # Update the time stamp
        current_time = datetime.datetime.now().strftime("%b/%d/%Y %H:%M:%S")
        for i, line in enumerate(updated_lines):
            if line.strip().startswith("LCMann Time="):
                updated_lines[i] = f"LCMann Time={current_time}\n"
                break

        # Write the updated file
        with open(geom_file_path, 'w', encoding='utf-8') as f:
            f.writelines(updated_lines)

        return True

    @staticmethod
    @log_call
    def replace_base_mannings_n(
        geom_file_path: Union[str, Path],
        mannings_data: Any,
        table_number: Optional[Union[str, int]] = None,
        backup: bool = True,
    ) -> bool:
        """
        Replace or create the plain-text ``LCMann Table=`` base Manning's n table.

        Unlike :meth:`set_base_mannings_n`, this authoring method allows the
        land-cover class names themselves to change. It is intended for new
        land-cover layer workflows where the sidecar HDF class list is being
        established and the geometry text file must receive the matching
        authoritative base n-values.

        Args:
            geom_file_path: Path to the HEC-RAS geometry text file (``.g##``).
            mannings_data: DataFrame-like table with land-cover names and
                n-values. Accepted name columns include ``Land Cover Name`` and
                ``class_name``; accepted n-value columns include
                ``Base Mannings n Value``, ``mannings_n``, and ``n_value``.
            table_number: Optional ``LCMann Table`` number. Defaults to the
                first table in the file, the input ``Table Number`` column, or
                ``16`` for new tables.
            backup: If True, write ``.bak`` beside the geometry file first.

        Returns:
            True if the geometry text file was updated.
        """
        import datetime
        import shutil

        geom_file_path = Path(geom_file_path)
        requested_table_number, normalized = GeomLandCover._normalize_base_table(
            mannings_data,
            table_number=table_number,
        )

        if backup:
            backup_path = geom_file_path.with_suffix(geom_file_path.suffix + '.bak')
            shutil.copy2(geom_file_path, backup_path)

        with open(geom_file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        start_idx, end_idx, existing_table_number = GeomLandCover._find_lcmann_table_bounds(
            lines,
            table_number=str(table_number) if table_number is not None else None,
        )
        # If exact table_number wasn't found but one was specified, replace ANY
        # existing LCMann Table (e.g. disabled "=0") instead of appending a duplicate.
        if start_idx is None and table_number is not None:
            start_idx, end_idx, _ = GeomLandCover._find_lcmann_table_bounds(
                lines, table_number=None,
            )
        resolved_table_number = existing_table_number or requested_table_number
        normalized['Table Number'] = str(resolved_table_number)

        new_content = [f"LCMann Table={resolved_table_number}\n"]
        for _, row in normalized.iterrows():
            n_value = float(row['Base Mannings n Value'])
            new_content.append(f"{row['Land Cover Name']},{n_value:g}\n")

        if start_idx is not None and end_idx is not None:
            updated_lines = lines[:start_idx] + new_content + lines[end_idx:]
        else:
            insert_idx = len(lines)
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith(('Chan Stop', 'Geom Raster', 'Use User', 'GIS ')):
                    insert_idx = i
                    break

            prefix_lines = []
            if not any(line.strip().startswith("LCMann Time=") for line in lines):
                prefix_lines.append("LCMann Time=Dec/30/1899 00:00:00\n")
            if not any(line.strip().startswith("LCMann Region Time=") for line in lines):
                prefix_lines.append("LCMann Region Time=Dec/30/1899 00:00:00\n")
            updated_lines = lines[:insert_idx] + prefix_lines + new_content + lines[insert_idx:]

        current_time = datetime.datetime.now().strftime("%b/%d/%Y %H:%M:%S")
        for i, line in enumerate(updated_lines):
            if line.strip().startswith("LCMann Time="):
                updated_lines[i] = f"LCMann Time={current_time}\n"
                break

        with open(geom_file_path, 'w', encoding='utf-8') as f:
            f.writelines(updated_lines)

        return True

    @staticmethod
    @log_call
    def get_region_mannings_n(geom_file_path: Union[str, Path]) -> pd.DataFrame:
        """
        Reads the Manning's n region overrides from a HEC-RAS geometry file.

        Parameters:
            geom_file_path (Union[str, Path]): Path to the geometry file (.g##)

        Returns:
            pd.DataFrame: DataFrame with columns:
                - Table Number (str): Region table identifier
                - Land Cover Name (str): Name of the land cover type
                - MainChannel (float): Manning's n value for main channel
                - Region Name (str): Name of the region

        Example:
            >>> geom_path = RasPlan.get_geom_path("01")
            >>> region_overrides_df = GeomLandCover.get_region_mannings_n(geom_path)
            >>> print(region_overrides_df)
        """
        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)

        region_rows = []
        current_region = None
        current_table = None

        # Read the geometry file
        with open(geom_file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Parse the file
        reading_region_table = False
        for line in lines:
            line = line.strip()

            # Find region name
            if line.startswith('LCMann Region Name='):
                current_region = line.split('=')[1]
                continue

            # Find region table number
            if line.startswith('LCMann Region Table='):
                current_table = line.split('=')[1]
                reading_region_table = True
                continue

            # Stop reading when we hit a line without a comma or starting with LCMann
            if reading_region_table and (not ',' in line or line.startswith('LCMann')):
                reading_region_table = False
                continue

            # Parse data rows in region table
            if reading_region_table and ',' in line and current_region is not None:
                # Check if there are multiple commas in the line
                parts = line.split(',')
                if len(parts) > 2:
                    # Handle case where land cover name contains commas
                    name = ','.join(parts[:-1])
                    value = parts[-1]
                else:
                    name, value = parts

                try:
                    region_rows.append([current_table, name, float(value), current_region])
                except ValueError:
                    # Log the error and continue
                    logger.warning(f"Error parsing line: {line}")
                    continue

        # Create DataFrame
        if region_rows:
            return pd.DataFrame(region_rows, columns=['Table Number', 'Land Cover Name', 'MainChannel', 'Region Name'])
        else:
            return pd.DataFrame(columns=['Table Number', 'Land Cover Name', 'MainChannel', 'Region Name'])

    @staticmethod
    @log_call
    def set_region_mannings_n(geom_file_path: Union[str, Path], mannings_data: pd.DataFrame) -> bool:
        """
        Writes regional Manning's n overrides to a HEC-RAS geometry file.

        Parameters:
            geom_file_path (Union[str, Path]): Path to the geometry file (.g##)
            mannings_data (pd.DataFrame): DataFrame with columns:
                - Table Number (str): Region table identifier
                - Land Cover Name (str): Name of the land cover type
                - MainChannel (float): Manning's n value
                - Region Name (str): Name of the region

        Returns:
            bool: True if successful

        Raises:
            ValueError: If region or land cover names don't match
        """
        import shutil
        import datetime

        # Convert to Path object if it's a string
        if isinstance(geom_file_path, str):
            geom_file_path = Path(geom_file_path)

        # Create backup
        backup_path = geom_file_path.with_suffix(geom_file_path.suffix + '.bak')
        shutil.copy2(geom_file_path, backup_path)

        # Read the entire file
        with open(geom_file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Group data by region
        regions = mannings_data.groupby('Region Name')

        # Find the Manning's region sections
        for region_name, region_data in regions:
            table_number = str(region_data['Table Number'].iloc[0])

            # Find the region section
            region_start_idx = None
            region_table_idx = None
            region_end_idx = None
            region_polygon_line = None

            for i, line in enumerate(lines):
                if line.strip() == f"LCMann Region Name={region_name}":
                    region_start_idx = i

                if region_start_idx is not None and line.strip() == f"LCMann Region Table={table_number}":
                    region_table_idx = i

                    # Find the end of this region (next LCMann Region or end of file)
                    for j in range(i+1, len(lines)):
                        if lines[j].strip().startswith('LCMann Region Name=') or lines[j].strip().startswith('LCMann Region Polygon='):
                            if lines[j].strip().startswith('LCMann Region Polygon='):
                                region_polygon_line = lines[j]
                            region_end_idx = j
                            break
                    if region_end_idx is None:  # If we reached the end of the file
                        region_end_idx = len(lines)
                    break

            if region_start_idx is None or region_table_idx is None:
                raise ValueError(f"Region {region_name} with table {table_number} not found in the geometry file")

            # Extract existing land cover names from the file
            existing_landcover = []
            for i in range(region_table_idx+1, region_end_idx):
                line = lines[i].strip()
                if ',' in line and not line.startswith('LCMann'):
                    parts = line.split(',')
                    if len(parts) > 2:
                        # Handle case where land cover name contains commas
                        name = ','.join(parts[:-1])
                    else:
                        name = parts[0]
                    existing_landcover.append(name)

            # Check if all land cover names in the dataframe match the file
            df_landcover = region_data['Land Cover Name'].tolist()
            if set(df_landcover) != set(existing_landcover):
                missing = set(existing_landcover) - set(df_landcover)
                extra = set(df_landcover) - set(existing_landcover)
                error_msg = f"Land cover names for region {region_name} don't match between file and dataframe.\n"
                if missing:
                    error_msg += f"Missing in dataframe: {missing}\n"
                if extra:
                    error_msg += f"Extra in dataframe: {extra}"
                raise ValueError(error_msg)

            # Create new content for the region
            new_content = [
                f"LCMann Region Name={region_name}\n",
                f"LCMann Region Table={table_number}\n"
            ]

            # Add region table entries
            for _, row in region_data.iterrows():
                new_content.append(f"{row['Land Cover Name']},{row['MainChannel']}\n")

            # Add the region polygon line if it exists
            if region_polygon_line:
                new_content.append(region_polygon_line)

            # Replace the section in the original file
            if region_polygon_line:
                # If we have a polygon line, include it in the replacement
                updated_lines = lines[:region_start_idx] + new_content + lines[region_end_idx+1:]
            else:
                # If no polygon line, just replace up to the end index
                updated_lines = lines[:region_start_idx] + new_content + lines[region_end_idx:]

            # Update the lines for the next region
            lines = updated_lines

        # Update the time stamp
        current_time = datetime.datetime.now().strftime("%b/%d/%Y %H:%M:%S")
        for i, line in enumerate(lines):
            if line.strip().startswith("LCMann Region Time="):
                lines[i] = f"LCMann Region Time={current_time}\n"
                break

        # Write the updated file
        with open(geom_file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        return True

    @staticmethod
    @log_call
    def set_mannings_region_polygons(
        geom_file: Union[str, Path],
        regions_gdf: Any,
        create_backup: bool = True,
    ) -> bool:
        """
        Write Manning's n calibration region polygon blocks to a geometry file.

        The plain-text ``.g##`` file is the durable source for Manning's n
        calibration regions. HEC-RAS regenerates the geometry HDF polygon
        datasets from these ``LCMann Region Polygon=N`` blocks during geometry
        preprocessing.

        Args:
            geom_file: Path to the HEC-RAS geometry text file (``.g##``).
            regions_gdf: GeoDataFrame-like object with ``Name`` and
                ``geometry`` columns. Geometry values must be Shapely Polygon
                or MultiPolygon objects in the project coordinate system.
                MultiPolygon exteriors are written as consecutive closed rings
                because the plain-text block has no explicit part-count table.
                Optional ``Table Number`` values are used when creating new
                region blocks.
            create_backup: If True, write ``.bak`` beside the geometry file.

        Returns:
            True if the geometry text file was updated.

        Raises:
            FileNotFoundError: If ``geom_file`` does not exist.
            ValueError: If required columns are missing, region names are
                duplicated, or polygon coordinates cannot be represented in
                HEC-RAS fixed-width format.
        """
        geom_file_path = Path(geom_file)
        if not geom_file_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file_path}")

        regions_df = pd.DataFrame(regions_gdf).copy()
        if regions_df.empty:
            raise ValueError("regions_gdf cannot be empty")

        name_col = GeomLandCover._first_existing_column(
            regions_df,
            GeomLandCover._REGION_NAME_COLUMNS,
        )
        if name_col is None or "geometry" not in regions_df.columns:
            raise ValueError("regions_gdf must include Name and geometry columns")

        base_table = GeomLandCover.get_base_mannings_n(geom_file_path)
        default_table_number = None
        if not base_table.empty:
            default_table_number = str(base_table['Table Number'].iloc[0])

        with open(geom_file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        lines = GeomLandCover._ensure_region_time_line(
            lines,
            GeomLandCover._find_region_insert_idx(lines),
        )

        seen_names: set[str] = set()
        for _, row in regions_df.iterrows():
            region_name = str(row[name_col]).strip()
            if not region_name:
                raise ValueError("Region Name values cannot be empty")
            if region_name in seen_names:
                raise ValueError(
                    f"Duplicate region name {region_name!r} in regions_gdf"
                )
            seen_names.add(region_name)

            coords = GeomLandCover._polygon_coords_from_geometry(row["geometry"])
            polygon_block = GeomLandCover._format_region_polygon_block(coords)

            existing_block = GeomLandCover._find_region_block(lines, region_name)
            if existing_block is not None:
                polygon_idx = existing_block["polygon_idx"]
                if polygon_idx is not None:
                    polygon_end_idx = existing_block["polygon_end_idx"] or polygon_idx + 1
                    lines = lines[:polygon_idx] + polygon_block + lines[polygon_end_idx:]
                else:
                    insert_idx = existing_block["end_idx"]
                    lines = lines[:insert_idx] + polygon_block + lines[insert_idx:]
                continue

            table_number = row.get('Table Number', default_table_number)
            if pd.isna(table_number):
                table_number = default_table_number
            if table_number is None:
                raise ValueError(
                    f"Cannot create region {region_name!r}: geometry file has "
                    "no base LCMann Table and regions_gdf did not provide "
                    "a Table Number"
                )
            table_number = str(table_number)

            region_base = base_table[
                base_table['Table Number'].astype(str) == table_number
            ]
            if region_base.empty:
                raise ValueError(
                    f"Cannot create region {region_name!r}: base LCMann "
                    f"Table {table_number} was not found in {geom_file_path}"
                )

            new_region_block = [
                f"LCMann Region Name={region_name}\n",
                f"LCMann Region Table={table_number}\n",
                *GeomLandCover._format_region_table_rows(region_base),
                *polygon_block,
            ]
            insert_idx = GeomLandCover._find_region_insert_idx(lines)
            lines = lines[:insert_idx] + new_region_block + lines[insert_idx:]

        lines = GeomLandCover._update_region_time(lines)
        GeomParser.safe_write_geometry(
            geom_file_path,
            lines,
            create_backup=create_backup,
        )

        logger.info(
            "Updated Manning's n region polygons in %s for %d region(s)",
            geom_file_path,
            len(regions_df),
        )
        return True

    @staticmethod
    @log_call
    def override_2d_mannings_n(
        geom_hdf_path: Union[str, Path],
        mannings_n: float,
        area_name: str = None,
    ) -> bool:
        """
        EXPERIMENTAL — Override preprocessed Manning's n in a geometry HDF.

        Writes a uniform Manning's n value directly to the preprocessed
        ``/Geometry/2D Flow Areas/{area}/Mann`` dataset. This dataset is
        normally generated by the HEC-RAS geometry preprocessor and is
        OVERWRITTEN on every preprocessing pass.

        .. warning::

            **This is NOT an officially supported HEC-RAS workflow.** The
            geometry HDF per-cell Manning's n is a *generated output* of
            preprocessing, not a durable input. Any call to ``compute_plan()``
            with ``clear_geompre=True`` or ``force_geompre=True`` will
            regenerate these values from the plain-text geometry file and the
            land cover sidecar HDF, discarding overrides written here.

        **Intended use — demonstration / research only:**

        1. Preprocess geometry first (run the plan once, or use
           ``force_geompre=True`` on a prior run).
        2. Call this function to inject override values into the HDF.
        3. Run ``compute_plan()`` with ``clear_geompre=False`` and
           ``force_geompre=False`` so the preprocessor does NOT regenerate.
        4. Values take effect for that single compute pass only.

        **For production workflows, use these durable APIs instead:**

        - ``GeomLandCover.set_base_mannings_n(geom_file, df)`` — modify the
          base calibration table in the plain-text .g## file.
        - ``GeomLandCover.set_region_mannings_n(geom_file, df)`` — modify
          region-specific overrides in the plain-text .g## file.
        - ``HdfLandCover.set_landcover_raster_map(sidecar_hdf, mapping)`` —
          modify the raster class-to-n mapping in the land cover sidecar HDF.

        All three durable methods survive geometry preprocessing because
        HEC-RAS reads FROM them to generate the per-cell values.

        Parameters:
            geom_hdf_path (Union[str, Path]): Path to the geometry HDF file (.g##.hdf)
            mannings_n (float): Manning's n roughness coefficient to set uniformly.
            area_name (str, optional): Name of specific 2D flow area to update.
                If None, updates all 2D flow areas in the file.

        Returns:
            bool: True if at least one area was updated, False if no Mann datasets found.

        Raises:
            FileNotFoundError: If the geometry HDF file does not exist.
            ValueError: If mannings_n is not a positive number.
        """
        logger.warning(
            "override_2d_mannings_n() is EXPERIMENTAL. Values written here "
            "will be overwritten by the geometry preprocessor. Use "
            "GeomLandCover.set_base_mannings_n() or "
            "HdfLandCover.set_landcover_raster_map() for durable changes."
        )
        import h5py
        import numpy as np

        geom_hdf_path = Path(geom_hdf_path)
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF file not found: {geom_hdf_path}")
        if not isinstance(mannings_n, (int, float)) or mannings_n <= 0:
            raise ValueError(f"mannings_n must be a positive number, got {mannings_n}")

        updated_count = 0
        with h5py.File(str(geom_hdf_path), "a") as hf:
            fa_group = hf.get("Geometry/2D Flow Areas")
            if fa_group is None:
                logger.warning(f"No 'Geometry/2D Flow Areas' group in {geom_hdf_path.name}")
                return False

            areas = [area_name] if area_name else list(fa_group.keys())
            for area in areas:
                mann_path = f"Geometry/2D Flow Areas/{area}/Mann"
                if mann_path in hf:
                    mann = hf[mann_path][:]
                    mann[:, 1] = mannings_n
                    hf[mann_path][:] = mann
                    updated_count += 1
                    logger.info(
                        f"Set Manning's n to {mannings_n} in {geom_hdf_path.name}/{area}"
                    )
                else:
                    logger.debug(f"No Mann dataset at {mann_path}")

        if updated_count == 0:
            logger.warning(f"No Mann datasets found in {geom_hdf_path.name}")
            return False

        logger.info(f"Updated Manning's n in {updated_count} area(s)")
        return True
