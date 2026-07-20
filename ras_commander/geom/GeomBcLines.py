"""
GeomBcLines: Author 2D boundary condition (BC) line geometry in HEC-RAS
plain text geometry files (.g##).

BC lines define where flow enters or leaves a 2D Flow Area on its
perimeter. Tutorials 2, 4, and 11 in HEC-RAS's "2D Unsteady Flow"
training set require authoring BC lines before any flow data
(Flow Hydrograph, Normal Depth, Stage Hydrograph, etc.) can be
attached to a boundary by name.

This module operates on the .g## TEXT file, which is the source of
truth for geometry authoring. After writing, the user must run HEC-RAS
geometry preprocessing (or launch HEC-RAS) for the new BC lines to
appear in the compiled `.g##.hdf` and become visible to
`HdfBndry.get_bc_lines()`. The companion `External Faces` HDF dataset
is computed by HEC-RAS preprocessing — it cannot be authored here.

Format conventions observed in real HEC-RAS output (Chippewa_2D,
BaldEagleCrkMulti2D, Weise_2D):

    BC Line Name=<name padded to 40 chars>
    BC Line Storage Area=<2D Flow Area name padded to 16 chars>
    BC Line Start Position= X , Y
    BC Line Middle Position= Xmid , Ymid
    BC Line End Position= X , Y
    BC Line Arc= N
    <fixed-width 16-char coordinate fields, 4 values per line>
    BC Line Text Position= 1.79769313486232E+308 , 1.79769313486232E+308

This format is structurally identical to Reference Line blocks.
Insertion site: after any existing BC Line blocks (so all BC lines
group together), or before the first of `Reference Line Name=` /
`IC Point Name=` / `LCMann ` if no BC lines exist yet.

All methods are static. Do not instantiate.

See Also
--------
ras_commander.RasUnsteady.set_normal_depth_boundary : Attach a Normal
    Depth boundary condition to an authored BC line (CLB-310).
ras_commander.RasUnsteady.set_flow_hydrograph_slope : Set the
    Flow Hydrograph energy-grade slope on an authored BC line
    (CLB-311).
ras_commander.geom.GeomReferenceFeatures.add_reference_lines : Sibling
    writer for Reference Lines (identical text format).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .GeomReferenceFeatures import _format_coord_line

logger = get_logger(__name__)


_BC_NAME_KEY = "BC Line Name="
_BC_STORAGE_AREA_KEY = "BC Line Storage Area="
_BC_TEXT_POSITION_KEY = "BC Line Text Position="
_TEXT_POSITION_SENTINEL = (
    " 1.79769313486232E+308 , 1.79769313486232E+308 "
)


def _build_bc_line_block(
    name: str,
    storage_area: str,
    coordinates: np.ndarray,
) -> List[str]:
    """Build a BC line plain-text block matching HEC-RAS-emitted output."""
    coords = np.asarray(coordinates, dtype=np.float64)
    n_pts = len(coords)
    x_start, y_start = coords[0]
    x_end, y_end = coords[-1]
    mid_idx = n_pts // 2
    x_mid, y_mid = coords[mid_idx]

    block: List[str] = []
    block.append(f"{_BC_NAME_KEY}{name:<40s}")
    block.append(f"{_BC_STORAGE_AREA_KEY}{storage_area:<16s}")
    block.append(f"BC Line Start Position= {x_start} , {y_start} ")
    block.append(f"BC Line Middle Position= {x_mid} , {y_mid} ")
    block.append(f"BC Line End Position= {x_end} , {y_end} ")
    block.append(f"BC Line Arc= {n_pts} ")

    # Coordinate block: 4 values per line (x1,y1,x2,y2), 16-char fields.
    flat_values = coords.flatten().tolist()
    for i in range(0, len(flat_values), 4):
        block.append(_format_coord_line(flat_values[i : i + 4]))

    block.append(f"{_BC_TEXT_POSITION_KEY}{_TEXT_POSITION_SENTINEL}")
    return block


def _detect_line_ending(file_lines: List[str]) -> str:
    return "\r\n" if file_lines and file_lines[0].endswith("\r\n") else "\n"


def _find_bc_line_block(
    file_lines: List[str], name: str
) -> Optional[tuple]:
    """Locate an existing BC line block by name. Returns (start_idx, end_idx)
    where end_idx is exclusive (one past the last line of the block — i.e.,
    the line after `BC Line Text Position=`)."""
    target = f"{_BC_NAME_KEY}{name}"
    for i, line in enumerate(file_lines):
        stripped = line.rstrip("\r\n")
        if not stripped.startswith(_BC_NAME_KEY):
            continue
        # Right-pad whitespace-tolerant match: HEC-RAS pads names to 40 chars.
        if stripped.rstrip() != target.rstrip():
            continue
        # Walk until we hit the closing `BC Line Text Position=` line.
        for j in range(i + 1, len(file_lines)):
            if file_lines[j].lstrip().startswith(_BC_TEXT_POSITION_KEY):
                return i, j + 1
        # Block was unterminated — defensive: stop at next BC Line Name= or end.
        for j in range(i + 1, len(file_lines)):
            if file_lines[j].lstrip().startswith(_BC_NAME_KEY):
                return i, j
        return i, len(file_lines)
    return None


def _list_storage_areas(file_lines: List[str]) -> List[str]:
    """Return the set of `Storage Area=` names present in the geometry."""
    areas: List[str] = []
    for line in file_lines:
        stripped = line.rstrip("\r\n")
        if stripped.startswith("Storage Area="):
            # Format: `Storage Area=<name padded to 16>,,` — take field[0] of
            # the comma split, strip the keyword and trailing whitespace.
            payload = stripped[len("Storage Area="):]
            name_field = payload.split(",", 1)[0].strip()
            if name_field:
                areas.append(name_field)
    return areas


def _bc_line_insertion_index(file_lines: List[str]) -> int:
    """Pick the canonical insertion site for a fresh BC Line block.

    Priority (matches the layout HEC-RAS emits):
      1. After the last existing `BC Line Text Position=` (group all BC
         lines together).
      2. Else before the first `Reference Line Name=` (BC lines come
         before reference lines in the file order).
      3. Else before the first `IC Point Name=`.
      4. Else before the first `LCMann ` line.
      5. Else end of file.
    """
    last_bc_text_idx = -1
    first_refline_idx = -1
    first_ic_point_idx = -1
    first_lcmann_idx = -1
    for i, line in enumerate(file_lines):
        stripped = line.rstrip("\r\n")
        if stripped.startswith(_BC_TEXT_POSITION_KEY):
            last_bc_text_idx = i
        if (
            stripped.startswith("Reference Line Name=")
            and first_refline_idx == -1
        ):
            first_refline_idx = i
        if (
            stripped.startswith("IC Point Name=")
            and first_ic_point_idx == -1
        ):
            first_ic_point_idx = i
        if stripped.startswith("LCMann ") and first_lcmann_idx == -1:
            first_lcmann_idx = i
    if last_bc_text_idx >= 0:
        return last_bc_text_idx + 1
    for candidate in (first_refline_idx, first_ic_point_idx, first_lcmann_idx):
        if candidate >= 0:
            return candidate
    return len(file_lines)


class GeomBcLines:
    """Public API for authoring 2D BC line geometry in `.g##` text files."""

    @staticmethod
    @log_call
    def get_bc_lines(geom_file: Union[str, Path]) -> List[Dict[str, Any]]:
        """Read 2D BC line definitions from a geometry text file.

        Returns one dictionary per block with ``name``, ``storage_area``,
        ``coordinates``, and ``coordinate_count``.  This reader makes the
        geometry-to-unsteady association contract independently verifiable
        before a boundary type is written to the unsteady-flow file.
        """
        geom_path = Path(geom_file)
        if not geom_path.is_file():
            raise FileNotFoundError(f"Geometry file not found: {geom_path}")

        with open(geom_path, "r", encoding="utf-8", errors="ignore", newline="") as stream:
            file_lines = stream.readlines()

        results: List[Dict[str, Any]] = []
        index = 0
        while index < len(file_lines):
            line = file_lines[index].rstrip("\r\n")
            if not line.startswith(_BC_NAME_KEY):
                index += 1
                continue

            name = line[len(_BC_NAME_KEY):].strip()
            storage_area = ""
            point_count = 0
            arc_index: Optional[int] = None
            cursor = index + 1
            while cursor < len(file_lines):
                candidate = file_lines[cursor].rstrip("\r\n")
                if candidate.startswith(_BC_NAME_KEY):
                    break
                if candidate.startswith(_BC_STORAGE_AREA_KEY):
                    storage_area = candidate[len(_BC_STORAGE_AREA_KEY):].strip()
                elif candidate.startswith("BC Line Arc="):
                    try:
                        point_count = int(candidate.split("=", 1)[1].strip())
                    except ValueError as exc:
                        raise ValueError(
                            f"Invalid BC Line Arc count for {name!r} in {geom_path.name}"
                        ) from exc
                    arc_index = cursor
                    break
                cursor += 1

            if arc_index is None or point_count < 2:
                raise ValueError(
                    f"BC line {name!r} in {geom_path.name} has no valid coordinate count"
                )

            coordinates: List[tuple] = []
            cursor = arc_index + 1
            while cursor < len(file_lines) and len(coordinates) < point_count:
                coordinate_line = file_lines[cursor].rstrip("\r\n")
                if coordinate_line.startswith(_BC_TEXT_POSITION_KEY):
                    break
                values: List[float] = []
                for start in range(0, len(coordinate_line), 16):
                    field = coordinate_line[start : start + 16].strip()
                    if not field:
                        continue
                    try:
                        values.append(float(field))
                    except ValueError as exc:
                        raise ValueError(
                            f"Invalid coordinate field {field!r} for BC line {name!r}"
                        ) from exc
                for value_index in range(0, len(values) - 1, 2):
                    coordinates.append(
                        (values[value_index], values[value_index + 1])
                    )
                cursor += 1

            coordinates = coordinates[:point_count]
            if len(coordinates) != point_count:
                raise ValueError(
                    f"BC line {name!r} declares {point_count} points but contains "
                    f"{len(coordinates)} in {geom_path.name}"
                )
            results.append(
                {
                    "name": name,
                    "storage_area": storage_area,
                    "coordinates": coordinates,
                    "coordinate_count": point_count,
                }
            )
            index = cursor

        return results

    @staticmethod
    @log_call
    def add_bc_lines(
        geom_file: Union[str, Path],
        lines: List[Dict[str, Any]],
        replace_existing: bool = False,
    ) -> Dict[str, Any]:
        """
        Insert one or more 2D BC line blocks into a geometry text file.

        Parameters
        ----------
        geom_file : str or Path
            Path to the HEC-RAS plain text geometry file (.g##).
        lines : list of dict
            Each dict describes one BC line and must contain:

            - ``name`` (str): the BC line name. Used by the
              `BC Line Name=` keyword and by `RasUnsteady` boundary
              setters to attach BC types. Must be unique within the
              file unless ``replace_existing=True``.
            - ``storage_area`` (str): the 2D Flow Area name this BC
              line attaches to. Must match an existing
              `Storage Area=<name>` block in the file.
            - ``coordinates`` (sequence of (x, y) or ``(N, 2)`` array):
              endpoint and intermediate vertices of the BC line in the
              project's native CRS. At least two points required.

        replace_existing : bool, default False
            When ``False`` (the default), inserting a BC line whose name
            already exists in the file raises ``ValueError``. When
            ``True``, the existing block is removed before the new one
            is inserted (upsert semantics).

        Returns
        -------
        Dict[str, Any]
            Reviewable metadata with keys:

            - ``geom_file`` (str): absolute path written
            - ``inserted`` (List[str]): names that were newly added
            - ``replaced`` (List[str]): names whose blocks were
              overwritten (only populated when ``replace_existing=True``)
            - ``insert_index`` (int): line index (0-based) where the new
              blocks were placed
            - ``backup_path`` (str): absolute path of the `.bak` backup

        Raises
        ------
        FileNotFoundError
            If ``geom_file`` does not exist.
        ValueError
            If ``lines`` is empty; if a line dict is missing required
            keys; if coordinates is malformed; if a referenced
            ``storage_area`` does not exist as a `Storage Area=` block
            in the file; or if a name already exists in the file and
            ``replace_existing`` is False.

        Examples
        --------
        Add a downstream Normal Depth BC line to the `Perimeter 1` 2D
        Flow Area in a Chippewa-style geometry, then attach Normal
        Depth in the unsteady file via `set_normal_depth_boundary`:

        >>> from ras_commander import GeomBcLines, RasUnsteady
        >>> result = GeomBcLines.add_bc_lines(
        ...     "project.g01",
        ...     lines=[{
        ...         "name": "DSNormalDepth",
        ...         "storage_area": "Perimeter 1",
        ...         "coordinates": [(1027205.96, 7858200.24),
        ...                          (1025994.94, 7858316.68)],
        ...     }],
        ... )
        >>> result["inserted"]
        ['DSNormalDepth']
        >>> # ... after running HEC-RAS geometry preprocessing ...
        >>> RasUnsteady.set_normal_depth_boundary(
        ...     "project.u01",
        ...     friction_slope=0.0003,
        ...     area_2d="Perimeter 1",
        ...     bc_line="DSNormalDepth",
        ... )

        See Also
        --------
        delete_bc_line, rename_bc_line :
            Companion writers for the `update`, `delete`, and `rename`
            verbs in CLB-309's API surface.
        ras_commander.geom.GeomReferenceFeatures.add_reference_lines :
            Sibling writer with identical text-format conventions.
        """
        geom_path = Path(geom_file)
        if not geom_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_path}")

        if not lines:
            raise ValueError("lines must contain at least one BC line spec")

        # Backup
        backup_path = Path(str(geom_path) + ".bak")
        shutil.copy2(geom_path, backup_path)
        logger.debug(f"Created backup: {backup_path}")

        with open(geom_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            file_lines = f.readlines()
        line_ending = _detect_line_ending(file_lines)

        # Validate inputs and pre-compute blocks before mutating.
        existing_areas = set(_list_storage_areas(file_lines))
        prepared: List[tuple] = []  # (name, storage_area, block_lines)
        for spec in lines:
            if not isinstance(spec, dict):
                raise ValueError("each entry in `lines` must be a dict")
            name_raw = spec.get("name")
            if not name_raw:
                raise ValueError("each line dict must have a 'name' key")
            name = str(name_raw).strip()
            sa_raw = spec.get("storage_area")
            if not sa_raw:
                raise ValueError(
                    f"BC line {name!r}: 'storage_area' is required"
                )
            storage_area = str(sa_raw).strip()
            if storage_area not in existing_areas:
                raise ValueError(
                    f"BC line {name!r}: storage_area {storage_area!r} not "
                    f"found in {geom_path.name}; existing areas are "
                    f"{sorted(existing_areas)}"
                )
            coords_raw = spec.get("coordinates")
            if coords_raw is None:
                raise ValueError(
                    f"BC line {name!r}: 'coordinates' is required"
                )
            coords = np.asarray(coords_raw, dtype=np.float64)
            if coords.ndim != 2 or coords.shape[1] != 2 or len(coords) < 2:
                raise ValueError(
                    f"BC line {name!r}: coordinates must be an (N, 2) "
                    f"array with at least 2 points"
                )
            block = _build_bc_line_block(name, storage_area, coords)
            prepared.append((name, storage_area, block))

        # Detect duplicate names within the call.
        seen: set = set()
        for name, _, _ in prepared:
            if name in seen:
                raise ValueError(
                    f"BC line name {name!r} appears more than once in `lines`"
                )
            seen.add(name)

        # Detect collisions with existing blocks; remove them up-front when
        # replace_existing=True so the insertion index is computed against
        # the post-removal file.
        replaced: List[str] = []
        if replace_existing:
            # Remove in descending index order to preserve earlier indices.
            removals: List[tuple] = []
            for name, _, _ in prepared:
                hit = _find_bc_line_block(file_lines, name)
                if hit is not None:
                    removals.append((name, hit))
            for name, (start, end) in sorted(
                removals, key=lambda r: r[1][0], reverse=True
            ):
                del file_lines[start:end]
                replaced.append(name)
        else:
            for name, _, _ in prepared:
                if _find_bc_line_block(file_lines, name) is not None:
                    raise ValueError(
                        f"BC line {name!r} already exists in {geom_path.name}; "
                        f"pass replace_existing=True to overwrite"
                    )

        insert_idx = _bc_line_insertion_index(file_lines)

        new_text_lines: List[str] = []
        for name, storage_area, block in prepared:
            for block_line in block:
                new_text_lines.append(block_line + line_ending)

        file_lines[insert_idx:insert_idx] = new_text_lines

        with open(geom_path, "w", encoding="utf-8", newline="") as f:
            f.writelines(file_lines)

        inserted = [name for name, _, _ in prepared if name not in replaced]
        logger.info(
            "Added %d BC line(s) to %s (replaced=%d)",
            len(prepared),
            geom_path.name,
            len(replaced),
        )
        logger.debug(
            "Inserted BC line block(s) at line index %d in %s",
            insert_idx,
            geom_path,
        )
        return {
            "geom_file": str(geom_path),
            "inserted": inserted,
            "replaced": replaced,
            "insert_index": insert_idx,
            "backup_path": str(backup_path),
        }

    @staticmethod
    @log_call
    def delete_bc_line(
        geom_file: Union[str, Path],
        name: str,
    ) -> Dict[str, Any]:
        """
        Remove a BC line block by name.

        Parameters
        ----------
        geom_file : str or Path
            Path to the .g## geometry file.
        name : str
            BC Line name to remove. Whitespace-padding on the matching
            line is tolerated.

        Returns
        -------
        Dict[str, Any]
            Keys: ``geom_file``, ``deleted`` (bool), ``name``,
            ``backup_path``, ``lines_removed`` (int).

        Raises
        ------
        FileNotFoundError
            If ``geom_file`` does not exist.
        ValueError
            If no BC line with the given name is present.
        """
        geom_path = Path(geom_file)
        if not geom_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_path}")

        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("name is required")

        backup_path = Path(str(geom_path) + ".bak")
        shutil.copy2(geom_path, backup_path)

        with open(geom_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            file_lines = f.readlines()

        hit = _find_bc_line_block(file_lines, clean_name)
        if hit is None:
            raise ValueError(
                f"BC line {clean_name!r} not found in {geom_path.name}"
            )
        start, end = hit
        lines_removed = end - start
        del file_lines[start:end]

        with open(geom_path, "w", encoding="utf-8", newline="") as f:
            f.writelines(file_lines)

        logger.info(
            "Deleted BC line %s from %s (%d lines)",
            clean_name,
            geom_path.name,
            lines_removed,
        )
        return {
            "geom_file": str(geom_path),
            "deleted": True,
            "name": clean_name,
            "backup_path": str(backup_path),
            "lines_removed": lines_removed,
        }

    @staticmethod
    @log_call
    def rename_bc_line(
        geom_file: Union[str, Path],
        old_name: str,
        new_name: str,
    ) -> Dict[str, Any]:
        """
        Rename a BC line in place, preserving its geometry, storage_area
        association, and position in the file.

        Parameters
        ----------
        geom_file : str or Path
            Path to the .g## geometry file.
        old_name, new_name : str
            Current and desired BC Line name.

        Returns
        -------
        Dict[str, Any]
            Keys: ``geom_file``, ``old_name``, ``new_name``,
            ``backup_path``.

        Raises
        ------
        FileNotFoundError
            If ``geom_file`` does not exist.
        ValueError
            If ``old_name`` does not exist; if ``new_name`` already
            exists; if either name is empty.
        """
        geom_path = Path(geom_file)
        if not geom_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_path}")

        clean_old = (old_name or "").strip()
        clean_new = (new_name or "").strip()
        if not clean_old or not clean_new:
            raise ValueError("old_name and new_name are required")
        if clean_old == clean_new:
            raise ValueError("old_name and new_name are identical")

        backup_path = Path(str(geom_path) + ".bak")
        shutil.copy2(geom_path, backup_path)

        with open(geom_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            file_lines = f.readlines()
        line_ending = _detect_line_ending(file_lines)

        old_hit = _find_bc_line_block(file_lines, clean_old)
        if old_hit is None:
            raise ValueError(
                f"BC line {clean_old!r} not found in {geom_path.name}"
            )
        if _find_bc_line_block(file_lines, clean_new) is not None:
            raise ValueError(
                f"BC line {clean_new!r} already exists in {geom_path.name}"
            )

        start, _end = old_hit
        # The first line of the block is `BC Line Name=<old_name padded>`.
        # Replace the whole line with the new padded name; preserve line
        # ending.
        file_lines[start] = f"{_BC_NAME_KEY}{clean_new:<40s}{line_ending}"

        with open(geom_path, "w", encoding="utf-8", newline="") as f:
            f.writelines(file_lines)

        logger.info(
            "Renamed BC line %s -> %s in %s",
            clean_old,
            clean_new,
            geom_path.name,
        )
        return {
            "geom_file": str(geom_path),
            "old_name": clean_old,
            "new_name": clean_new,
            "backup_path": str(backup_path),
        }
