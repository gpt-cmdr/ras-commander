"""
GeomReferenceFeatures: Insert reference lines and reference points into
HEC-RAS plain text geometry files (.g##).

Reference lines act as virtual cross sections in 2D models, enabling
integrated flow extraction for calibration against streamflow gauges.
Reference points provide WSE/depth extraction at specific cell locations.

Format discovered from BayouConway production model (2026-04-08):
  Reference Line: keyword-value pairs + fixed-width coordinate block
  Reference Point: stored as IC Points with "Reference Point" name prefix

All methods are static. Do not instantiate.
"""

from pathlib import Path
from typing import List, Optional, Union
import logging
import shutil

import numpy as np

from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


def _format_coord_line(values: List[float], width: int = 16) -> str:
    """Format coordinate values into fixed-width fields, 4 values per line."""
    parts = []
    for v in values:
        s = f"{v:.10g}"
        parts.append(s.rjust(width))
    return "".join(parts)


def _build_reference_line_block(
    name: str,
    storage_area: str,
    coordinates: np.ndarray,
) -> List[str]:
    """
    Build a reference line plain text block.

    Format (from BayouConway production model):
        Reference Line Name=<name padded to 40>
        Reference Line Storage Area=<SA padded to 16>
        Reference Line Start Position= X , Y
        Reference Line Middle Position= Xmid , Ymid
        Reference Line End Position= X , Y
        Reference Line Arc= N
        <fixed-width coordinates, 2 x,y pairs per line>
        Reference Line Text Position= 1.79769313486232E+308 , 1.79769313486232E+308
    """
    coords = np.asarray(coordinates, dtype=np.float64)
    n_pts = len(coords)

    x_start, y_start = coords[0]
    x_end, y_end = coords[-1]
    mid_idx = n_pts // 2
    x_mid, y_mid = coords[mid_idx]

    lines = []
    lines.append(f"Reference Line Name={name:<40s}")
    lines.append(f"Reference Line Storage Area={storage_area:<16s}")
    lines.append(
        f"Reference Line Start Position= {x_start} , {y_start} "
    )
    lines.append(
        f"Reference Line Middle Position= {x_mid} , {y_mid} "
    )
    lines.append(
        f"Reference Line End Position= {x_end} , {y_end} "
    )
    lines.append(f"Reference Line Arc= {n_pts} ")

    # Coordinate block: 4 values per line (x1,y1,x2,y2), 16 chars each
    flat_values = coords.flatten().tolist()
    values_per_line = 4  # 2 x,y pairs
    for i in range(0, len(flat_values), values_per_line):
        chunk = flat_values[i : i + values_per_line]
        lines.append(_format_coord_line(chunk))

    lines.append(
        "Reference Line Text Position="
        " 1.79769313486232E+308 , 1.79769313486232E+308 "
    )

    return lines


def _build_ic_point_block(name: str, x: float, y: float) -> List[str]:
    """
    Build a reference point (IC Point) plain text block.

    Format:
        IC Point Name=<name padded to 40>
        IC Point Position=X,Y
    """
    return [
        f"IC Point Name={name:<40s}",
        f"IC Point Position={x},{y}",
    ]


class GeomReferenceFeatures:
    """Insert reference lines and reference points into .g## geometry files."""

    @staticmethod
    @log_call
    def add_reference_lines(
        geom_file: Union[str, Path],
        lines: List[dict],
        storage_area: str,
    ) -> int:
        """
        Insert reference lines into a plain text geometry file.

        Reference lines are inserted after BC Lines and before IC Points
        or LCMann sections. They persist through HEC-RAS recomputation
        because HEC-RAS reads them from the plain text file during
        geometry preprocessing.

        Args:
            geom_file: Path to geometry file (.g##)
            lines: List of dicts with:
                - 'name': str -- unique reference line name
                - 'coordinates': list of (x,y) tuples or array (N,2)
            storage_area: Name of the 2D flow area (e.g., 'BaldEagleCr')

        Returns:
            int: Number of reference lines inserted

        Example:
            >>> GeomReferenceFeatures.add_reference_lines(
            ...     "model.g01",
            ...     lines=[
            ...         {"name": "Gauge_01", "coordinates": [(1000, 2000), (1100, 2000)]},
            ...     ],
            ...     storage_area="MyMesh",
            ... )
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not lines:
            raise ValueError("lines must contain at least one reference line")

        # Create backup
        backup_path = Path(str(geom_file) + ".bak")
        shutil.copy2(geom_file, backup_path)
        logger.info(f"Created backup: {backup_path.name}")

        # Read file with CRLF preservation
        with open(geom_file, "r", encoding="utf-8", errors="ignore", newline="") as f:
            file_lines = f.readlines()

        # Build reference line blocks
        new_blocks = []
        for item in lines:
            name = str(item["name"]).strip()
            coords = np.asarray(item["coordinates"], dtype=np.float64)
            if coords.ndim != 2 or coords.shape[1] != 2 or len(coords) < 2:
                raise ValueError(
                    f"Reference line '{name}' needs at least 2 points as (N,2) array"
                )
            block = _build_reference_line_block(name, storage_area, coords)
            new_blocks.extend(block)

        # Find insertion point: after last BC Line block, before IC Points or LCMann
        insert_idx = len(file_lines)  # default: end of file

        last_bc_line_idx = -1
        first_ic_point_idx = -1
        first_lcmann_idx = -1
        first_existing_refline_idx = -1

        for i, line in enumerate(file_lines):
            stripped = line.rstrip("\r\n")
            if stripped.startswith("BC Line Text Position="):
                last_bc_line_idx = i
            if stripped.startswith("IC Point Name=") and first_ic_point_idx == -1:
                first_ic_point_idx = i
            if stripped.startswith("LCMann ") and first_lcmann_idx == -1:
                first_lcmann_idx = i
            if stripped.startswith("Reference Line Name=") and first_existing_refline_idx == -1:
                first_existing_refline_idx = i

        # Priority: insert at existing ref line location, or after BC lines,
        # or before IC points, or before LCMann
        if first_existing_refline_idx >= 0:
            insert_idx = first_existing_refline_idx
        elif last_bc_line_idx >= 0:
            insert_idx = last_bc_line_idx + 1
        elif first_ic_point_idx >= 0:
            insert_idx = first_ic_point_idx
        elif first_lcmann_idx >= 0:
            insert_idx = first_lcmann_idx

        # Detect line ending from file
        line_ending = "\r\n" if file_lines and "\r\n" in file_lines[0] else "\n"

        # Insert
        insert_lines = [block_line + line_ending for block_line in new_blocks]
        file_lines[insert_idx:insert_idx] = insert_lines

        # Write back
        with open(geom_file, "w", encoding="utf-8", newline="") as f:
            f.writelines(file_lines)

        logger.info(
            f"Inserted {len(lines)} reference line(s) into {geom_file.name} "
            f"(storage area: {storage_area}) at line {insert_idx + 1}"
        )
        return len(lines)

    @staticmethod
    @log_call
    def add_reference_points(
        geom_file: Union[str, Path],
        points: List[dict],
    ) -> int:
        """
        Insert reference points into a plain text geometry file.

        Reference points are stored as IC Points with names starting with
        "Reference Point". They are inserted in the IC Point section.

        Args:
            geom_file: Path to geometry file (.g##)
            points: List of dicts with:
                - 'name': str -- unique name (will be prefixed with
                  "Reference Point " if not already)
                - 'x': float -- X coordinate
                - 'y': float -- Y coordinate

        Returns:
            int: Number of reference points inserted

        Example:
            >>> GeomReferenceFeatures.add_reference_points(
            ...     "model.g01",
            ...     points=[
            ...         {"name": "Gauge_01", "x": 1685000, "y": 145000},
            ...     ],
            ... )
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not points:
            raise ValueError("points must contain at least one reference point")

        # Create backup
        backup_path = Path(str(geom_file) + ".bak")
        if not backup_path.exists():
            shutil.copy2(geom_file, backup_path)
            logger.info(f"Created backup: {backup_path.name}")

        with open(geom_file, "r", encoding="utf-8", errors="ignore", newline="") as f:
            file_lines = f.readlines()

        # Build IC Point blocks
        new_blocks = []
        for item in points:
            name = str(item["name"]).strip()
            if not name.startswith("Reference Point"):
                name = f"Reference Point {name}"
            x = float(item["x"])
            y = float(item["y"])
            block = _build_ic_point_block(name, x, y)
            new_blocks.extend(block)

        # Find insertion point: at existing IC Points or before LCMann
        insert_idx = len(file_lines)
        first_ic_point_idx = -1
        first_lcmann_idx = -1

        for i, line in enumerate(file_lines):
            stripped = line.rstrip("\r\n")
            if stripped.startswith("IC Point Name=") and first_ic_point_idx == -1:
                first_ic_point_idx = i
            if stripped.startswith("LCMann ") and first_lcmann_idx == -1:
                first_lcmann_idx = i

        if first_ic_point_idx >= 0:
            insert_idx = first_ic_point_idx
        elif first_lcmann_idx >= 0:
            insert_idx = first_lcmann_idx

        line_ending = "\r\n" if file_lines and "\r\n" in file_lines[0] else "\n"
        insert_lines = [block_line + line_ending for block_line in new_blocks]
        file_lines[insert_idx:insert_idx] = insert_lines

        with open(geom_file, "w", encoding="utf-8", newline="") as f:
            f.writelines(file_lines)

        logger.info(
            f"Inserted {len(points)} reference point(s) into {geom_file.name} "
            f"at line {insert_idx + 1}"
        )
        return len(points)

    @staticmethod
    @log_call
    def get_reference_lines(
        geom_file: Union[str, Path],
    ) -> List[dict]:
        """
        Read reference lines from a plain text geometry file.

        Returns:
            List of dicts with 'name', 'storage_area', 'coordinates' keys.
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        with open(geom_file, "r", encoding="utf-8", errors="ignore") as f:
            file_lines = f.readlines()

        results = []
        i = 0
        while i < len(file_lines):
            line = file_lines[i].rstrip("\r\n")
            if line.startswith("Reference Line Name="):
                name = line.split("=", 1)[1].strip()
                storage_area = ""
                n_pts = 0

                # Read subsequent keywords
                j = i + 1
                while j < len(file_lines):
                    sub = file_lines[j].rstrip("\r\n")
                    if sub.startswith("Reference Line Storage Area="):
                        storage_area = sub.split("=", 1)[1].strip()
                    elif sub.startswith("Reference Line Arc="):
                        n_pts = int(sub.split("=", 1)[1].strip())
                        break
                    j += 1

                # Read coordinate block
                coords = []
                k = j + 1
                while len(coords) < n_pts and k < len(file_lines):
                    coord_line = file_lines[k].rstrip("\r\n")
                    if coord_line.startswith("Reference Line"):
                        break
                    # Parse 16-char fixed-width fields
                    vals = []
                    for start in range(0, len(coord_line), 16):
                        chunk = coord_line[start : start + 16].strip()
                        if chunk:
                            try:
                                vals.append(float(chunk))
                            except ValueError:
                                break
                    for vi in range(0, len(vals) - 1, 2):
                        coords.append((vals[vi], vals[vi + 1]))
                    k += 1

                results.append({
                    "name": name,
                    "storage_area": storage_area,
                    "coordinates": coords,
                })
                i = k
            else:
                i += 1

        return results

    @staticmethod
    @log_call
    def get_reference_points(
        geom_file: Union[str, Path],
    ) -> List[dict]:
        """
        Read reference points (IC Points with "Reference Point" names)
        from a plain text geometry file.

        Returns:
            List of dicts with 'name', 'x', 'y' keys.
        """
        geom_file = Path(geom_file)
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        with open(geom_file, "r", encoding="utf-8", errors="ignore") as f:
            file_lines = f.readlines()

        results = []
        i = 0
        while i < len(file_lines):
            line = file_lines[i].rstrip("\r\n")
            if line.startswith("IC Point Name=") and "Reference Point" in line:
                name = line.split("=", 1)[1].strip()
                if i + 1 < len(file_lines):
                    pos_line = file_lines[i + 1].rstrip("\r\n")
                    if pos_line.startswith("IC Point Position="):
                        xy = pos_line.split("=", 1)[1]
                        parts = xy.split(",")
                        if len(parts) >= 2:
                            results.append({
                                "name": name,
                                "x": float(parts[0]),
                                "y": float(parts[1]),
                            })
                i += 2
            else:
                i += 1

        return results
