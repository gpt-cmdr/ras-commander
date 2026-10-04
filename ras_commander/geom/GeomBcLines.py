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

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from .._ras_text import _write_ras_text
from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .GeomParser import GeomParser
from .GeomReferenceFeatures import _format_coord_line

logger = get_logger(__name__)


_BC_NAME_KEY = "BC Line Name="
_BC_STORAGE_AREA_KEY = "BC Line Storage Area="
_BC_TEXT_POSITION_KEY = "BC Line Text Position="
_TEXT_POSITION_SENTINEL = " 1.79769313486232E+308 , 1.79769313486232E+308 "


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


def _find_bc_line_block(file_lines: List[str], name: str) -> Optional[tuple]:
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
            payload = stripped[len("Storage Area=") :]
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
        if stripped.startswith("Reference Line Name=") and first_refline_idx == -1:
            first_refline_idx = i
        if stripped.startswith("IC Point Name=") and first_ic_point_idx == -1:
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
    def replace_bc_lines(
        geom_file: str | Path,
        unsteady_files: list[str | Path],
        *,
        area_2d: str,
        lines: list[dict[str, Any]],
        ras_object: Any | None = None,
    ) -> pd.DataFrame:
        """Completely replace one area's perimeter BC lines and forcing.

        Parameters
        ----------
        geom_file : str or Path
            Explicit geometry text path in the caller's disposable clone.
        unsteady_files : list of str or Path
            Complete set of cloned unsteady files referencing this geometry.
            At least one is required. Paths must share the geometry directory.
            With ``ras_object``, completeness is checked against ``plan_df``;
            otherwise the caller is responsible for supplying the complete set.
        area_2d : str
            Exact 2D Flow Area name (maximum 16 characters).
        lines : list of dict
            Complete replacement set; an empty list clears perimeter lines.
            Each entry has ``name`` (maximum 32 characters), ``coordinates``
            (finite N-by-2 vertices), and ``bc_type``. Supported types are
            ``Normal Depth`` (``friction_slope`` required), ``Flow Hydrograph``
            (``hydrograph_df`` and ``friction_slope`` required), and
            ``Stage Hydrograph`` (``hydrograph_df`` required). Hydrograph frames
            have ``hour`` and ``value`` columns accepted by ``RasUnsteady``.
            The supplied forcing is applied to every supplied unsteady file.
        ras_object : optional
            Initialized clone project used to verify geometry/flow association
            and refresh ``boundaries_df`` after successful writes.

        Returns
        -------
        pandas.DataFrame
            One row per new line and unsteady file, with ``geom_file``,
            ``unsteady_file``, ``area_2d``, ``bc_line``, and ``bc_type`` columns.
            Empty replacements return the same empty schema. ``attrs`` includes
            ``removed_bc_lines``, ``backup_paths`` and ``boundaries_df_refreshed``.

        Raises
        ------
        FileNotFoundError
            If an explicit input file is missing.
        ValueError
            If inputs, native blocks, names, forcing or project associations
            are invalid, ambiguous, or incomplete.
        OSError
            If staging, backup creation, or replacement fails.

        Notes
        -----
        This method modifies only explicitly supplied paths; it does not clone
        projects. Other areas, 1D boundaries and area-wide rainfall are retained.
        All content is staged and validated before writes, with same-directory
        atomic replacement per file and byte-exact rollback on write exceptions.
        This is an exception-atomic transaction, not a crash-atomic multi-file
        transaction; concurrent readers/writers must be excluded by the caller.
        Existing backups are retained. Compiled HDF files are not updated: run
        native preprocessing before inspecting native face attachments.
        A post-commit metadata refresh failure is logged and returned through
        ``boundaries_df_refreshed=False``; it does not undo committed files.
        ``standardize_input`` is HDF-specific; these text paths are normalized
        explicitly and never resolved through the global project.
        """
        from ..RasPrj import RasPrj
        from ..RasUnsteady import RasUnsteady
        from ..RasUtils import RasUtils

        def clean_name(value, label, maximum):
            if not isinstance(value, str):
                raise TypeError(f"{label} must be a string")
            if not value.strip():
                raise ValueError(f"{label} must be a non-empty string")
            value = value.strip()
            if len(value) > maximum or any(c in value for c in ",\r\n"):
                raise ValueError(
                    f"{label} exceeds {maximum} characters or contains delimiters"
                )
            return value

        area_name = clean_name(area_2d, "area_2d", 16)
        geom_path = RasUtils.safe_resolve(Path(geom_file))
        if not isinstance(unsteady_files, list) or not unsteady_files:
            raise ValueError(
                "unsteady_files must be a non-empty list of explicit paths"
            )
        flow_paths = [RasUtils.safe_resolve(Path(value)) for value in unsteady_files]
        paths = [geom_path, *flow_paths]
        if len(set(paths)) != len(paths):
            raise ValueError("Geometry and unsteady paths must be distinct")
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f"Input file not found: {path}")
            if path.parent != geom_path.parent:
                raise ValueError(
                    "All input files must belong to the same cloned project directory"
                )
        if any(
            os.path.samefile(a, b) for i, a in enumerate(paths) for b in paths[i + 1 :]
        ):
            raise ValueError("Input paths must not alias the same physical file")
        if not isinstance(lines, list):
            raise TypeError("lines must be a list of replacement specifications")

        if ras_object is not None:
            ras_object.check_initialized()
            matches = ras_object.geom_df[
                ras_object.geom_df["full_path"].map(
                    lambda p: RasUtils.safe_resolve(Path(p)) == geom_path
                )
            ]
            if len(matches) != 1:
                raise ValueError(
                    "Geometry must identify exactly one entry in ras_object.geom_df"
                )
            number = str(matches.iloc[0]["geom_number"])
            plans = ras_object.plan_df
            linked = plans[plans["geometry_number"].astype(str) == number]
            expected = {
                RasUtils.safe_resolve(Path(p))
                for p in linked["Flow Path"].dropna()
                if Path(p).suffix.startswith(".u")
            }
            if set(flow_paths) != expected:
                raise ValueError(
                    "unsteady_files must contain every flow file associated with this geometry"
                )
            other = plans[plans["geometry_number"].astype(str) != number]
            if any(
                RasUtils.safe_resolve(Path(p)) in expected
                for p in other["Flow Path"].dropna()
            ):
                raise ValueError(
                    "An unsteady file is shared with another geometry; clone it first"
                )

        originals = {path: path.read_bytes() for path in paths}
        file_lines = originals[geom_path].decode("utf-8").splitlines(keepends=True)
        areas = _list_storage_areas(file_lines)
        if areas.count(area_name) != 1:
            raise ValueError(f"2D Flow Area {area_name!r} not found in geometry")
        area_start = next(
            i
            for i, line in enumerate(file_lines)
            if line.startswith("Storage Area=")
            and line.split("=", 1)[1].split(",", 1)[0].strip() == area_name
        )
        area_end = next(
            (
                i
                for i in range(area_start + 1, len(file_lines))
                if file_lines[i].startswith("Storage Area=")
            ),
            len(file_lines),
        )
        if not any(
            line.startswith("Storage Area 2D Points=")
            for line in file_lines[area_start:area_end]
        ):
            raise ValueError(f"Storage area {area_name!r} is not a 2D Flow Area")
        newline = _detect_line_ending(file_lines)
        records = []
        starts = [
            i for i, line in enumerate(file_lines) if line.startswith(_BC_NAME_KEY)
        ]
        for position, start in enumerate(starts):
            limit = (
                starts[position + 1] if position + 1 < len(starts) else len(file_lines)
            )
            end = next(
                (
                    i + 1
                    for i in range(start + 1, limit)
                    if file_lines[i].startswith(_BC_TEXT_POSITION_KEY)
                ),
                None,
            )
            if end is None:
                raise ValueError("Unterminated BC line geometry block")
            area_fields = [
                line[len(_BC_STORAGE_AREA_KEY) :].strip()
                for line in file_lines[start:end]
                if line.startswith(_BC_STORAGE_AREA_KEY)
            ]
            if len(area_fields) != 1 or not area_fields[0]:
                raise ValueError("BC line block requires exactly one storage area")
            records.append(
                (
                    file_lines[start][len(_BC_NAME_KEY) :].strip(),
                    area_fields[0],
                    start,
                    end,
                )
            )
        if len({record[0] for record in records}) != len(records):
            raise ValueError("Duplicate native BC line names are ambiguous")
        retained_names = {name for name, area, _, _ in records if area != area_name}
        removed = [name for name, area, _, _ in records if area == area_name]
        prepared = []
        for spec in lines:
            if not isinstance(spec, dict):
                raise TypeError("Each replacement specification must be a dict")
            name = clean_name(spec.get("name"), "name", 32)
            if name in retained_names or any(item[0] == name for item in prepared):
                raise ValueError(f"Duplicate or unrelated-area BC line name {name!r}")
            coords = np.asarray(spec.get("coordinates"), dtype=float)
            if (
                coords.ndim != 2
                or coords.shape[1] != 2
                or len(coords) < 2
                or not np.isfinite(coords).all()
            ):
                raise ValueError(
                    "coordinates must be a finite (N, 2) array with at least two points"
                )
            if np.linalg.norm(np.diff(coords, axis=0), axis=1).sum() == 0:
                raise ValueError("BC line geometry must have positive length")
            bc_type = spec.get("bc_type")
            if bc_type not in ("Normal Depth", "Flow Hydrograph", "Stage Hydrograph"):
                raise ValueError("Unsupported or missing bc_type")
            if (
                bc_type in ("Normal Depth", "Flow Hydrograph")
                and "friction_slope" not in spec
            ):
                raise ValueError(f"{bc_type} requires friction_slope")
            if bc_type != "Normal Depth" and not isinstance(
                spec.get("hydrograph_df"), pd.DataFrame
            ):
                raise ValueError(f"{bc_type} requires hydrograph_df")
            prepared.append((name, bc_type, coords, spec))
        for _, area, start, end in reversed(records):
            if area == area_name:
                del file_lines[start:end]
        insertion = _bc_line_insertion_index(file_lines)
        blocks = [
            line + newline
            for name, _, coords, _ in prepared
            for line in _build_bc_line_block(name, area_name, coords)
        ]
        if (
            blocks
            and insertion
            and not file_lines[insertion - 1].endswith(("\n", "\r"))
        ):
            file_lines[insertion - 1] += newline
        file_lines[insertion:insertion] = blocks

        with TemporaryDirectory(
            prefix=".bc-replacement-", dir=geom_path.parent
        ) as temporary:
            staging = Path(temporary)
            staged_geom = staging / geom_path.name
            _write_ras_text(staged_geom, "".join(file_lines), encoding="utf-8")
            payloads = []
            writer_project = RasPrj()
            for index, (name, bc_type, _, spec) in enumerate(prepared):
                # Isolate type-writer scans from unrelated boundaries and trailers.
                forcing = staging / f"forcing{index}.u01"
                _write_ras_text(
                    forcing,
                    f"Flow Title=BC replacement{newline}Program Version=6.60{newline}Use Restart=0{newline}",
                    encoding="utf-8",
                )
                selector = {
                    "area_2d": area_name,
                    "bc_line": name,
                    "ras_object": writer_project,
                }
                RasUnsteady.ensure_2d_boundary_location(
                    forcing, staged_geom, **selector
                )
                if bc_type == "Normal Depth":
                    RasUnsteady.set_normal_depth_boundary(
                        forcing, spec["friction_slope"], **selector
                    )
                else:
                    if not RasUnsteady.set_boundary_inline_hydrograph(
                        forcing, spec["hydrograph_df"], bc_type=bc_type, **selector
                    ):
                        raise ValueError(f"Could not write forcing for {name!r}")
                    if bc_type == "Flow Hydrograph":
                        RasUnsteady.set_flow_hydrograph_slope(
                            forcing, spec["friction_slope"], **selector
                        )
                authored = forcing.read_bytes().decode().splitlines(keepends=True)
                boundary = RasUnsteady._find_boundary_blocks(authored)
                if len(boundary) != 1 or boundary[0]["bc_type"] != bc_type:
                    raise ValueError(f"Forcing validation failed for {name!r}")
                payloads.extend(
                    authored[boundary[0]["start_idx"] : boundary[0]["end_idx"]]
                )
            staged = {geom_path: staged_geom}
            for path in flow_paths:
                content = originals[path].decode("utf-8").splitlines(keepends=True)
                boundaries = RasUnsteady._find_boundary_blocks(content)
                identities = [tuple(b["parts"][:8]) for b in boundaries]
                if len(set(identities)) != len(identities):
                    raise ValueError(
                        "Duplicate native boundary locations are ambiguous"
                    )
                for boundary in reversed(boundaries):
                    parts = boundary["parts"]
                    if len(parts) > 5 and parts[5] == area_name:
                        if len(parts) < 8 or any(parts[8:]) or any(parts[:3]):
                            raise ValueError("Malformed target 2D boundary location")
                        if parts[7]:
                            del content[boundary["start_idx"] : boundary["end_idx"]]
                insertion = next(
                    (
                        i
                        for i, line in enumerate(content)
                        if line.startswith("Boundary Location=")
                    ),
                    None,
                )
                if payloads and insertion is None:
                    header = [
                        i
                        for i, line in enumerate(content)
                        if line.startswith(
                            ("Flow Title=", "Program Version=", "Use Restart=")
                        )
                    ]
                    if not header:
                        raise ValueError(
                            "Cannot identify safe unsteady insertion point"
                        )
                    insertion = max(header) + 1
                if payloads:
                    flow_newline = RasUnsteady._detect_line_ending(content)
                    if insertion and not content[insertion - 1].endswith(("\n", "\r")):
                        content[insertion - 1] += flow_newline
                    content[insertion:insertion] = [
                        line.rstrip("\r\n") + flow_newline for line in payloads
                    ]
                final_boundaries = RasUnsteady._find_boundary_blocks(content)
                final_target = [
                    (block["parts"][7], block["bc_type"])
                    for block in final_boundaries
                    if len(block["parts"]) >= 8
                    and block["parts"][5] == area_name
                    and block["parts"][7]
                ]
                if sorted(final_target) != sorted(
                    (name, kind) for name, kind, _, _ in prepared
                ):
                    raise ValueError(
                        "Staged boundary references do not match replacement geometry"
                    )
                staged[path] = staging / path.name
                _write_ras_text(staged[path], "".join(content), encoding="utf-8")
            # Reject concurrent changes before backups or publishing any content.
            if any(path.read_bytes() != data for path, data in originals.items()):
                raise ValueError("Input files changed during BC replacement")
            backups = []
            for path, data in originals.items():
                backup = path.with_name(path.name + ".bak")
                counter = 1
                while backup.exists():
                    backup = path.with_name(f"{path.name}.bak.{counter}")
                    counter += 1
                with backup.open("xb") as stream:
                    stream.write(data)
                backups.append(str(backup))
            committed = []
            try:
                for path, stage in staged.items():
                    os.replace(stage, path)
                    committed.append(path)
            except BaseException:
                for index, path in enumerate(reversed(committed)):
                    restore = staging / f"rollback{index}"
                    restore.write_bytes(originals[path])
                    os.replace(restore, path)
                raise
        boundaries_df_refreshed = False
        if ras_object is not None:
            try:
                ras_object.boundaries_df = ras_object.get_boundary_conditions()
                boundaries_df_refreshed = True
            except Exception as exc:  # noqa: BLE001 -- refresh must not report failed committed edits
                logger.warning(
                    "BC replacement committed; boundaries_df refresh failed: %s", exc
                )
        result = pd.DataFrame(
            [
                {
                    "geom_file": str(geom_path),
                    "unsteady_file": str(path),
                    "area_2d": area_name,
                    "bc_line": name,
                    "bc_type": bc_type,
                }
                for path in flow_paths
                for name, bc_type, _, _ in prepared
            ],
            columns=["geom_file", "unsteady_file", "area_2d", "bc_line", "bc_type"],
        )
        result.attrs.update(
            removed_bc_lines=removed,
            backup_paths=backups,
            boundaries_df_refreshed=boundaries_df_refreshed,
        )
        logger.info(
            "Replaced %d BC lines with %d lines on %s",
            len(removed),
            len(prepared),
            area_name,
        )
        return result

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

        ```python
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
        ```

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
                raise ValueError(f"BC line {name!r}: 'storage_area' is required")
            storage_area = str(sa_raw).strip()
            if storage_area not in existing_areas:
                raise ValueError(
                    f"BC line {name!r}: storage_area {storage_area!r} not "
                    f"found in {geom_path.name}; existing areas are "
                    f"{sorted(existing_areas)}"
                )
            coords_raw = spec.get("coordinates")
            if coords_raw is None:
                raise ValueError(f"BC line {name!r}: 'coordinates' is required")
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

        backup_path = GeomParser.safe_write_geometry(
            geom_path,
            file_lines,
            create_backup=True,
        )
        logger.debug("Created backup: %s", backup_path)

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

        with open(geom_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            file_lines = f.readlines()

        hit = _find_bc_line_block(file_lines, clean_name)
        if hit is None:
            raise ValueError(f"BC line {clean_name!r} not found in {geom_path.name}")
        start, end = hit
        lines_removed = end - start
        del file_lines[start:end]

        backup_path = GeomParser.safe_write_geometry(
            geom_path,
            file_lines,
            create_backup=True,
        )
        logger.debug("Created backup: %s", backup_path)

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

        with open(geom_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            file_lines = f.readlines()
        line_ending = _detect_line_ending(file_lines)

        old_hit = _find_bc_line_block(file_lines, clean_old)
        if old_hit is None:
            raise ValueError(f"BC line {clean_old!r} not found in {geom_path.name}")
        if _find_bc_line_block(file_lines, clean_new) is not None:
            raise ValueError(
                f"BC line {clean_new!r} already exists in {geom_path.name}"
            )

        start, _end = old_hit
        # The first line of the block is `BC Line Name=<old_name padded>`.
        # Replace the whole line with the new padded name; preserve line
        # ending.
        file_lines[start] = f"{_BC_NAME_KEY}{clean_new:<40s}{line_ending}"

        backup_path = GeomParser.safe_write_geometry(
            geom_path,
            file_lines,
            create_backup=True,
        )
        logger.debug("Created backup: %s", backup_path)

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
