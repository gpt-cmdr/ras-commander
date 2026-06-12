"""Model geometry reprojection helpers for HEC-RAS text geometry files.

HEC-RAS stores authored model geometry in plain-text ``.g##`` files and
compiled geometry in derived ``.g##.hdf`` files.  This module transforms the
plain-text coordinates and reports compiled geometry, terrain, and raster
artifacts that must be rebuilt or reprojected outside this writer.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from ..RasUtils import RasUtils
from .GeomParser import GeomParser
from .GeomStorage import GeomStorage

logger = get_logger(__name__)


PathLike = Union[str, Path]
Coordinate = Tuple[float, float]


_COORD_BLOCKS = {
    "Reach XY": {"values_per_line": 4, "stat": "reach_xy"},
    "XS GIS Cut Line": {"values_per_line": 4, "stat": "xs_gis_cut_lines"},
    "Storage Area Surface Line": {
        "values_per_line": 2,
        "stat": "storage_area_surface_lines",
    },
    "Storage Area 2D Points": {
        "values_per_line": 4,
        "stat": "storage_area_2d_points",
    },
    "BreakLine Polyline": {"values_per_line": 4, "stat": "breakline_polylines"},
    "Connection Line": {"values_per_line": 4, "stat": "connection_lines"},
}

_ARC_BLOCKS = {
    "BC Line Arc": {"values_per_line": 4, "stat": "bc_line_arcs"},
    "Reference Line Arc": {"values_per_line": 4, "stat": "reference_line_arcs"},
}

_POSITION_KEYWORDS = (
    "BC Line Start Position",
    "BC Line Middle Position",
    "BC Line End Position",
    "Reference Line Start Position",
    "Reference Line Middle Position",
    "Reference Line End Position",
    "IC Point Position",
)

_TEXT_POSITION_SENTINEL = 1.0e300
_GEOM_FILE_PATTERN = re.compile(r"^Geom File=(g\d{1,3})\s*$", re.IGNORECASE)


class GeomProjection:
    """Reproject HEC-RAS model geometry coordinates.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    @log_call
    def reproject_geometry(
        geom_file: PathLike,
        source_crs: Any,
        destination_crs: Any,
        output_geom: Optional[PathLike] = None,
        *,
        allow_datum_shift: bool = False,
        overwrite: bool = False,
        create_backup: bool = False,
    ) -> Dict[str, Any]:
        """Transform coordinates in one HEC-RAS plain-text geometry file.

        The default writes a copied geometry next to the source file using a
        ``_reprojected`` suffix.  Passing ``output_geom=geom_file`` updates that
        file in place, which is intended for already-copied project folders.

        Args:
            geom_file: Source ``.g##`` geometry text file.
            source_crs: Source CRS as a ``pyproj.CRS`` input, ESRI ``.prj`` path,
                or WKT text.
            destination_crs: Destination CRS as a ``pyproj.CRS`` input, ESRI
                ``.prj`` path, or WKT text.
            output_geom: Optional output ``.g##`` path.  Defaults to a copied
                sibling named ``*_reprojected.g##``.
            allow_datum_shift: HEC-RAS cannot reproduce datum transformations.
                By default, transformations between different geodetic datums
                raise ``ValueError``.  Set True only when the caller has made a
                project-specific engineering decision to allow the pyproj datum
                operation.
            overwrite: Allow replacing an existing ``output_geom``.
            create_backup: Create ``.bak`` before an in-place write.

        Returns:
            Dictionary with source/output paths, CRS metadata, transformation
            counts, and post-conversion QA findings.
        """
        geom_path = Path(geom_file)
        if not geom_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_path}")
        if geom_path.suffix.lower() == ".hdf":
            raise ValueError(
                "GeomProjection.reproject_geometry() operates on plain-text "
                ".g## files, not compiled .g##.hdf files."
            )

        src_crs = GeomProjection._crs_from_input(source_crs)
        dst_crs = GeomProjection._crs_from_input(destination_crs)
        datum_report = GeomProjection._validate_datum_compatibility(
            src_crs,
            dst_crs,
            allow_datum_shift=allow_datum_shift,
        )

        out_path = (
            Path(output_geom)
            if output_geom is not None
            else geom_path.with_name(
                f"{geom_path.stem}_reprojected{geom_path.suffix}"
            )
        )
        same_file = RasUtils.safe_resolve(out_path) == RasUtils.safe_resolve(geom_path)
        if out_path.exists() and not same_file and not overwrite:
            raise FileExistsError(
                f"Output geometry already exists: {out_path}. "
                "Pass overwrite=True to replace it."
            )
        if same_file and create_backup:
            GeomParser.create_backup(geom_path)

        from pyproj import Transformer

        transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
        lines = geom_path.read_text(encoding="utf-8", errors="replace").splitlines(
            keepends=True
        )
        transformed_lines, stats = GeomProjection._transform_geometry_lines(
            lines,
            transformer,
        )
        out_path.write_text("".join(transformed_lines), encoding="utf-8")

        qa = GeomProjection._qa_geometry_lines(transformed_lines)
        result = {
            "source_geometry": str(geom_path),
            "output_geometry": str(out_path),
            "source_crs": GeomProjection._crs_label(src_crs),
            "destination_crs": GeomProjection._crs_label(dst_crs),
            "datum": datum_report,
            "transformed": stats,
            "qa": qa,
        }
        logger.info(
            "Reprojected geometry %s -> %s (%s coordinate sections)",
            geom_path,
            out_path,
            sum(value for key, value in stats.items() if key.endswith("_points")),
        )
        return result

    @staticmethod
    @log_call
    def reproject_model_geometry(
        project_path: PathLike,
        source_crs: Any,
        destination_crs: Any,
        dest_folder: Optional[PathLike] = None,
        *,
        geometry_files: Optional[Sequence[PathLike]] = None,
        projection_filename: Optional[str] = None,
        allow_datum_shift: bool = False,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Copy a HEC-RAS project and reproject its plain-text geometries.

        This method preserves the source project by default.  It copies the
        project folder, transforms ``.g##`` text geometry coordinates in the
        copied folder, writes a destination ESRI projection file, updates copied
        ``.rasmap`` projection references, and reports terrain/compiled-geometry
        rebuild requirements.

        Args:
            project_path: Project folder, ``.prj`` file, or ``.rasmap`` file.
            source_crs: Source CRS as a ``pyproj.CRS`` input, ESRI ``.prj`` path,
                or WKT text.
            destination_crs: Destination CRS as a ``pyproj.CRS`` input, ESRI
                ``.prj`` path, or WKT text.
            dest_folder: Destination project folder.  Defaults to a sibling
                folder named ``<project>_reprojected``.
            geometry_files: Optional geometry filenames/paths to transform.
                Relative names are resolved in the copied project folder.
                Defaults to ``Geom File=`` entries in the copied project file,
                with a ``*.g##`` fallback.
            projection_filename: Optional destination ``.prj`` filename under
                the copied project's ``Projection`` folder.
            allow_datum_shift: See :meth:`reproject_geometry`.
            overwrite: Allow replacing an existing ``dest_folder``.

        Returns:
            Dictionary with copied project path, projection update details,
            per-geometry transformation results, terrain requirements, and
            compiled geometry rebuild notes.
        """
        src_project = GeomProjection._resolve_project_folder(project_path)
        if not src_project.exists():
            raise FileNotFoundError(f"Project folder not found: {src_project}")

        src_crs = GeomProjection._crs_from_input(source_crs)
        dst_crs = GeomProjection._crs_from_input(destination_crs)
        datum_report = GeomProjection._validate_datum_compatibility(
            src_crs,
            dst_crs,
            allow_datum_shift=allow_datum_shift,
        )

        dest_project = (
            Path(dest_folder)
            if dest_folder is not None
            else src_project.with_name(f"{src_project.name}_reprojected")
        )
        GeomProjection._validate_destination_project(src_project, dest_project)
        if dest_project.exists():
            if not overwrite:
                raise FileExistsError(
                    f"Destination project folder already exists: {dest_project}. "
                    "Pass overwrite=True to replace it."
                )
            shutil.rmtree(dest_project)
        shutil.copytree(src_project, dest_project)

        project_name = GeomProjection._project_name(dest_project)
        projection_path = GeomProjection._write_destination_projection(
            dest_project,
            project_name,
            dst_crs,
            projection_filename=projection_filename,
        )
        rasmap_updates = GeomProjection._update_rasmap_projection_references(
            dest_project,
            projection_path,
        )

        geom_paths = GeomProjection._resolve_geometry_paths(
            dest_project,
            geometry_files,
        )
        geometry_results = []
        for geom_path in geom_paths:
            geometry_results.append(
                GeomProjection.reproject_geometry(
                    geom_path,
                    src_crs,
                    dst_crs,
                    output_geom=geom_path,
                    allow_datum_shift=True,
                    overwrite=True,
                    create_backup=False,
                )
            )

        terrain_requirements = GeomProjection._inspect_terrain_requirements(
            dest_project,
            dst_crs,
        )
        compiled_geometry = GeomProjection._inspect_compiled_geometry_hdfs(geom_paths)

        return {
            "source_project_folder": str(src_project),
            "destination_project_folder": str(dest_project),
            "source_crs": GeomProjection._crs_label(src_crs),
            "destination_crs": GeomProjection._crs_label(dst_crs),
            "datum": datum_report,
            "projection_file": str(projection_path),
            "rasmap_updates": rasmap_updates,
            "geometry_results": geometry_results,
            "terrain_requirements": terrain_requirements,
            "compiled_geometry": compiled_geometry,
            "limitations": [
                "Compiled .g##.hdf geometry is not transformed; run geometry "
                "preprocessing after review.",
                "Terrain, raster, land-cover, infiltration, and sediment HDF "
                "coordinates are not reprojected by this API.",
                "Datum transformations are rejected unless allow_datum_shift=True.",
            ],
        }

    @staticmethod
    def _crs_from_input(value: Any) -> Any:
        """Create ``pyproj.CRS`` from pyproj input, WKT, or .prj path."""
        try:
            from pyproj import CRS
        except ImportError as exc:
            raise ImportError(
                "pyproj is required for geometry reprojection. Install pyproj "
                "or a ras-commander extra that includes it."
            ) from exc

        if isinstance(value, CRS):
            return value

        if isinstance(value, Path):
            if value.exists():
                return CRS.from_wkt(value.read_text(encoding="utf-8", errors="replace"))
            return CRS.from_user_input(str(value))

        if isinstance(value, str):
            text = value.strip()
            path_candidate = GeomProjection._existing_path_from_string(text)
            if path_candidate is not None:
                return CRS.from_wkt(
                    path_candidate.read_text(encoding="utf-8", errors="replace")
                )
            if text.upper().startswith(
                ("PROJCS[", "GEOGCS[", "PROJCRS[", "GEODCRS[", "VERTCRS[")
            ):
                return CRS.from_wkt(text)
            return CRS.from_user_input(value)

        return CRS.from_user_input(value)

    @staticmethod
    def _existing_path_from_string(text: str) -> Optional[Path]:
        try:
            candidate = Path(text)
            if candidate.exists() and candidate.suffix.lower() == ".prj":
                return candidate
        except (OSError, ValueError):
            return None
        return None

    @staticmethod
    def _validate_datum_compatibility(
        source_crs: Any,
        destination_crs: Any,
        *,
        allow_datum_shift: bool,
    ) -> Dict[str, Any]:
        source_datum = GeomProjection._datum_label(source_crs)
        destination_datum = GeomProjection._datum_label(destination_crs)
        same_datum = GeomProjection._same_horizontal_datum(
            source_crs,
            destination_crs,
        )
        report = {
            "source": source_datum,
            "destination": destination_datum,
            "same_horizontal_datum": same_datum,
            "datum_shift_allowed": bool(allow_datum_shift),
        }
        if not same_datum and not allow_datum_shift:
            raise ValueError(
                "Refusing geometry reprojection that requires a datum shift. "
                "HEC-RAS cannot reproduce datum transformations during project "
                f"projection changes. Source datum: {source_datum!r}; "
                f"destination datum: {destination_datum!r}. Pass "
                "allow_datum_shift=True only after explicit engineering review."
            )
        return report

    @staticmethod
    def _same_horizontal_datum(source_crs: Any, destination_crs: Any) -> bool:
        source_geodetic = getattr(source_crs, "geodetic_crs", None) or source_crs
        destination_geodetic = (
            getattr(destination_crs, "geodetic_crs", None) or destination_crs
        )
        try:
            if source_geodetic.is_exact_same(destination_geodetic):
                return True
        except AttributeError:
            pass
        return GeomProjection._normalize_label(
            GeomProjection._datum_label(source_crs)
        ) == GeomProjection._normalize_label(GeomProjection._datum_label(destination_crs))

    @staticmethod
    def _datum_label(crs: Any) -> str:
        geodetic = getattr(crs, "geodetic_crs", None) or crs
        datum = getattr(geodetic, "datum", None)
        if datum is not None and getattr(datum, "name", None):
            return datum.name
        return getattr(geodetic, "name", str(geodetic))

    @staticmethod
    def _normalize_label(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value).lower())

    @staticmethod
    def _crs_label(crs: Any) -> str:
        try:
            authority = crs.to_authority()
            if authority:
                return f"{authority[0]}:{authority[1]}"
        except Exception:
            pass
        return crs.name

    @staticmethod
    def _transform_geometry_lines(lines: List[str], transformer: Any):
        stats = {
            "reach_xy_sections": 0,
            "reach_xy_points": 0,
            "xs_gis_cut_lines_sections": 0,
            "xs_gis_cut_lines_points": 0,
            "storage_area_headers": 0,
            "storage_area_surface_lines_sections": 0,
            "storage_area_surface_lines_points": 0,
            "storage_area_2d_points_sections": 0,
            "storage_area_2d_points_points": 0,
            "breakline_polylines_sections": 0,
            "breakline_polylines_points": 0,
            "connection_lines_sections": 0,
            "connection_lines_points": 0,
            "bc_line_arcs_sections": 0,
            "bc_line_arcs_points": 0,
            "reference_line_arcs_sections": 0,
            "reference_line_arcs_points": 0,
            "position_lines": 0,
        }
        output: List[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()

            storage_header = GeomProjection._transform_storage_area_header(
                line,
                transformer,
            )
            if storage_header is not None:
                output.append(storage_header)
                stats["storage_area_headers"] += 1
                i += 1
                continue

            matched_block = False
            for keyword, config in _COORD_BLOCKS.items():
                if stripped.startswith(f"{keyword}="):
                    count = GeomProjection._extract_count(line, keyword)
                    output.append(line)
                    transformed, next_i = GeomProjection._transform_coord_block(
                        lines,
                        i + 1,
                        count,
                        values_per_line=config["values_per_line"],
                        transformer=transformer,
                        section_name=keyword,
                    )
                    output.extend(transformed)
                    stats[f"{config['stat']}_sections"] += 1
                    stats[f"{config['stat']}_points"] += count
                    i = next_i
                    matched_block = True
                    break
            if matched_block:
                continue

            for keyword, config in _ARC_BLOCKS.items():
                if stripped.startswith(f"{keyword}="):
                    count = GeomProjection._extract_count(line, keyword)
                    output.append(line)
                    transformed, next_i = GeomProjection._transform_coord_block(
                        lines,
                        i + 1,
                        count,
                        values_per_line=config["values_per_line"],
                        transformer=transformer,
                        section_name=keyword,
                    )
                    output.extend(transformed)
                    stats[f"{config['stat']}_sections"] += 1
                    stats[f"{config['stat']}_points"] += count
                    i = next_i
                    matched_block = True
                    break
            if matched_block:
                continue

            transformed_position = GeomProjection._transform_position_line(
                line,
                transformer,
            )
            if transformed_position is not None:
                output.append(transformed_position)
                stats["position_lines"] += 1
            else:
                output.append(line)
            i += 1

        return output, stats

    @staticmethod
    def _extract_count(line: str, keyword: str) -> int:
        value = GeomParser.extract_keyword_value(line, keyword)
        match = re.search(r"-?\d+", value)
        if not match:
            raise ValueError(f"Could not parse point count for {keyword!r}: {line!r}")
        count = int(match.group(0))
        if count < 0:
            raise ValueError(f"Negative point count for {keyword!r}: {line!r}")
        return count

    @staticmethod
    def _transform_coord_block(
        lines: List[str],
        start_index: int,
        count: int,
        *,
        values_per_line: int,
        transformer: Any,
        section_name: str,
    ) -> Tuple[List[str], int]:
        if count == 0:
            return [], start_index

        total_values = count * 2
        data_lines: List[str] = []
        idx = start_index
        values: List[float] = []
        while idx < len(lines) and len(values) < total_values:
            candidate = lines[idx]
            stripped = candidate.strip()
            if not stripped:
                break
            if "=" in stripped:
                break
            data_lines.append(candidate)
            values = GeomProjection._parse_coord_values(data_lines, total_values)
            idx += 1

        if len(values) < total_values:
            raise ValueError(
                f"Partial {section_name} coordinate block: expected {count} "
                f"points ({total_values} values), found {len(values)} values."
            )

        transformed_coords = [
            GeomProjection._transform_point(transformer, values[j], values[j + 1])
            for j in range(0, total_values, 2)
        ]
        line_ending = GeomProjection._line_ending(data_lines[0] if data_lines else "")
        return (
            GeomProjection._format_coord_rows(
                transformed_coords,
                values_per_line=values_per_line,
                line_ending=line_ending,
            ),
            idx,
        )

    @staticmethod
    def _parse_coord_values(data_lines: List[str], total_values: int) -> List[float]:
        fixed_width_values: List[float] = []
        split_values: List[float] = []
        for raw_line in data_lines:
            fixed_width_values.extend(
                GeomParser.parse_fixed_width(raw_line, column_width=16)
            )
            for token in raw_line.replace(",", " ").split():
                try:
                    split_values.append(float(token))
                except ValueError:
                    break

        if len(fixed_width_values) > len(split_values):
            values = fixed_width_values
        else:
            values = split_values
        return values[:total_values]

    @staticmethod
    def _transform_point(transformer: Any, x_coord: float, y_coord: float) -> Coordinate:
        if not (math.isfinite(x_coord) and math.isfinite(y_coord)):
            raise ValueError(f"Coordinate values must be finite: {x_coord}, {y_coord}")
        x_new, y_new = transformer.transform(float(x_coord), float(y_coord))
        if not (math.isfinite(x_new) and math.isfinite(y_new)):
            raise ValueError(
                "Coordinate transformation produced non-finite values: "
                f"{x_coord}, {y_coord} -> {x_new}, {y_new}"
            )
        return float(x_new), float(y_new)

    @staticmethod
    def _format_coord_rows(
        coords: Iterable[Coordinate],
        *,
        values_per_line: int,
        line_ending: str,
    ) -> List[str]:
        flat_values: List[float] = []
        for x_coord, y_coord in coords:
            flat_values.extend([x_coord, y_coord])

        rows = []
        for i in range(0, len(flat_values), values_per_line):
            row_values = flat_values[i:i + values_per_line]
            rows.append(
                "".join(GeomProjection._format_coord_value(value) for value in row_values)
                + line_ending
            )
        return rows

    @staticmethod
    def _format_coord_value(value: float, column_width: int = 16) -> str:
        precision = GeomProjection._max_precision_for_field(value, column_width)
        return f"{value:{column_width}.{precision}f}"

    @staticmethod
    def _max_precision_for_field(value: float, column_width: int) -> int:
        sign_chars = 1 if value < 0 else 0
        integer_part = int(abs(value))
        int_digits = max(1, len(str(integer_part)))
        overhead = sign_chars + int_digits + 1
        precision = max(0, column_width - overhead)
        while precision > 0:
            if len(f"{value:{column_width}.{precision}f}") <= column_width:
                return precision
            precision -= 1
        return 0

    @staticmethod
    def _format_free_value(value: float) -> str:
        return f"{value:.15g}"

    @staticmethod
    def _line_ending(line: str) -> str:
        return "\r\n" if line.endswith("\r\n") else "\n"

    @staticmethod
    def _transform_storage_area_header(line: str, transformer: Any) -> Optional[str]:
        stripped = line.lstrip()
        if not stripped.startswith("Storage Area="):
            return None
        value = GeomParser.extract_keyword_value(line, "Storage Area")
        parts = [part.strip() for part in value.split(",")]
        if len(parts) < 3:
            return None
        try:
            x_coord = float(parts[1])
            y_coord = float(parts[2])
        except ValueError:
            return None
        if GeomProjection._is_text_position_sentinel(x_coord, y_coord):
            return None
        x_new, y_new = GeomProjection._transform_point(transformer, x_coord, y_coord)
        eol = GeomProjection._line_ending(line)
        indent = line[: len(line) - len(stripped)]
        return f"{indent}Storage Area={parts[0]},{x_new:.7f},{y_new:.7f}{eol}"

    @staticmethod
    def _transform_position_line(line: str, transformer: Any) -> Optional[str]:
        stripped = line.lstrip()
        for keyword in _POSITION_KEYWORDS:
            if not stripped.startswith(f"{keyword}="):
                continue
            value = GeomParser.extract_keyword_value(line, keyword)
            parts = [part for part in re.split(r"\s*,\s*", value.strip()) if part != ""]
            if len(parts) < 2:
                return None
            try:
                x_coord = float(parts[0])
                y_coord = float(parts[1])
            except ValueError:
                return None
            if GeomProjection._is_text_position_sentinel(x_coord, y_coord):
                return None
            x_new, y_new = GeomProjection._transform_point(
                transformer,
                x_coord,
                y_coord,
            )
            eol = GeomProjection._line_ending(line)
            indent = line[: len(line) - len(stripped)]
            return (
                f"{indent}{keyword}= {GeomProjection._format_free_value(x_new)} , "
                f"{GeomProjection._format_free_value(y_new)} {eol}"
            )
        return None

    @staticmethod
    def _is_text_position_sentinel(x_coord: float, y_coord: float) -> bool:
        return abs(x_coord) >= _TEXT_POSITION_SENTINEL or abs(y_coord) >= _TEXT_POSITION_SENTINEL

    @staticmethod
    def _resolve_project_folder(project_path: PathLike) -> Path:
        if hasattr(project_path, "project_folder"):
            return RasUtils.safe_resolve(Path(project_path.project_folder))

        path = Path(project_path)
        if path.is_dir():
            return RasUtils.safe_resolve(path)
        if path.suffix.lower() in {".prj", ".rasmap"}:
            return RasUtils.safe_resolve(path.parent)
        raise ValueError(
            "project_path must be a project folder, .prj file, .rasmap file, "
            "or RasPrj-like object with project_folder."
        )

    @staticmethod
    def _validate_destination_project(src_project: Path, dest_project: Path) -> None:
        """Reject destination folders that would overwrite or nest in the source."""
        src_resolved = RasUtils.safe_resolve(src_project)
        dest_resolved = RasUtils.safe_resolve(dest_project)
        if dest_resolved == src_resolved:
            raise ValueError(
                "dest_folder must be different from the source project folder. "
                "GeomProjection.reproject_model_geometry() copies the project "
                "before transforming geometry."
            )
        try:
            dest_resolved.relative_to(src_resolved)
        except ValueError:
            return
        raise ValueError(
            "dest_folder must not be inside the source project folder. Choose a "
            "sibling or separate working directory for the copied project."
        )

    @staticmethod
    def _project_name(project_folder: Path) -> str:
        for prj_path in sorted(project_folder.glob("*.prj")):
            try:
                for line in prj_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines():
                    if line.startswith("Proj Title="):
                        return prj_path.stem
            except OSError:
                continue
        return project_folder.name

    @staticmethod
    def _write_destination_projection(
        project_folder: Path,
        project_name: str,
        destination_crs: Any,
        *,
        projection_filename: Optional[str],
    ) -> Path:
        projection_dir = project_folder / "Projection"
        projection_dir.mkdir(parents=True, exist_ok=True)
        filename = projection_filename or f"{project_name}_Projection.prj"
        if not filename.lower().endswith(".prj"):
            filename = f"{filename}.prj"
        projection_path = projection_dir / filename
        projection_path.write_text(
            destination_crs.to_wkt(version="WKT1_ESRI"),
            encoding="utf-8",
        )
        return projection_path

    @staticmethod
    def _update_rasmap_projection_references(
        project_folder: Path,
        projection_path: Path,
    ) -> List[Dict[str, Any]]:
        rasmap_paths = sorted(project_folder.glob("*.rasmap"))
        updates: List[Dict[str, Any]] = []
        for rasmap_path in rasmap_paths:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
            projection_elem = root.find(".//RASProjectionFilename")
            previous = None
            if projection_elem is None:
                projection_elem = ET.Element("RASProjectionFilename")
                root.insert(0, projection_elem)
            else:
                previous = projection_elem.get("Filename")
            new_ref = GeomProjection._format_rasmap_relative_path(
                rasmap_path.parent,
                projection_path,
            )
            projection_elem.set("Filename", new_ref)
            projection_elem.text = None
            tree.write(rasmap_path, encoding="utf-8", xml_declaration=False)
            updates.append(
                {
                    "rasmap_path": str(rasmap_path),
                    "previous_projection": previous,
                    "new_projection": new_ref,
                }
            )
        return updates

    @staticmethod
    def _format_rasmap_relative_path(base_folder: Path, target_path: Path) -> str:
        target = RasUtils.safe_resolve(target_path)
        base = RasUtils.safe_resolve(base_folder)
        try:
            rel = os.path.relpath(target, base)
        except ValueError:
            return str(target).replace("/", "\\")
        rel = rel.replace("/", "\\")
        if rel.startswith("..\\") or rel == "..":
            return rel
        return f".\\{rel}"

    @staticmethod
    def _resolve_geometry_paths(
        project_folder: Path,
        geometry_files: Optional[Sequence[PathLike]],
    ) -> List[Path]:
        if geometry_files is not None:
            paths = []
            for item in geometry_files:
                candidate = Path(item)
                if not candidate.is_absolute():
                    candidate = project_folder / candidate
                if not candidate.exists():
                    raise FileNotFoundError(f"Geometry file not found: {candidate}")
                paths.append(candidate)
            return paths

        geom_ids: List[str] = []
        for prj_path in sorted(project_folder.glob("*.prj")):
            for line in prj_path.read_text(encoding="utf-8", errors="replace").splitlines():
                match = _GEOM_FILE_PATTERN.match(line.strip())
                if match:
                    geom_id = match.group(1).lower()
                    if geom_id not in geom_ids:
                        geom_ids.append(geom_id)

        if geom_ids:
            project_name = GeomProjection._project_name(project_folder)
            return [
                project_folder / f"{project_name}.{geom_id}"
                for geom_id in geom_ids
                if (project_folder / f"{project_name}.{geom_id}").exists()
            ]

        return sorted(
            path
            for path in project_folder.glob("*.g[0-9][0-9]*")
            if not path.name.lower().endswith(".hdf")
        )

    @staticmethod
    def _qa_geometry_lines(lines: List[str]) -> Dict[str, Any]:
        storage_records = []
        duplicate_perimeters = []
        invalid_perimeters = []
        for _, _, block_lines in GeomStorage._iter_storage_area_blocks(lines):
            info = GeomStorage._inspect_storage_area_block(block_lines)
            name = info["header"]["name"]
            if info["surface_line_idx"] is None:
                continue
            try:
                coords = GeomStorage._parse_surface_line_coords(block_lines, info)
            except ValueError as exc:
                invalid_perimeters.append({"name": name, "reason": str(exc)})
                continue
            duplicates = GeomProjection._duplicate_vertices(coords)
            if duplicates:
                duplicate_perimeters.append(
                    {"name": name, "duplicate_vertices": duplicates}
                )
            if len(coords) < 4 or coords[0] != coords[-1]:
                invalid_perimeters.append(
                    {
                        "name": name,
                        "reason": "Perimeter is not a closed ring with at least three edges.",
                    }
                )
            storage_records.append(
                {
                    "name": name,
                    "is_2d": info["is_2d"],
                    "point_count": len(coords),
                    "has_duplicate_vertices": bool(duplicates),
                }
            )

        breakline_records = GeomProjection._qa_breaklines(lines)
        xs_sections = sum(1 for line in lines if line.lstrip().startswith("XS GIS Cut Line="))

        return {
            "cross_sections": {
                "xs_gis_cut_line_count": xs_sections,
            },
            "storage_areas": {
                "count": len(storage_records),
                "records": storage_records,
                "duplicate_perimeter_points": duplicate_perimeters,
                "invalid_perimeters": invalid_perimeters,
            },
            "breaklines": {
                "count": len(breakline_records),
                "records": breakline_records,
                "invalid": [
                    record for record in breakline_records if not record["is_valid"]
                ],
            },
        }

    @staticmethod
    def _duplicate_vertices(coords: Sequence[Coordinate]) -> List[Dict[str, Any]]:
        seen: Dict[Tuple[float, float], int] = {}
        duplicates: List[Dict[str, Any]] = []
        core = list(coords[:-1]) if len(coords) > 1 and coords[0] == coords[-1] else list(coords)
        for index, (x_coord, y_coord) in enumerate(core):
            key = (round(x_coord, 6), round(y_coord, 6))
            if key in seen:
                duplicates.append(
                    {
                        "first_index": seen[key],
                        "duplicate_index": index,
                        "x": x_coord,
                        "y": y_coord,
                    }
                )
            else:
                seen[key] = index
        return duplicates

    @staticmethod
    def _qa_breaklines(lines: List[str]) -> List[Dict[str, Any]]:
        records = []
        i = 0
        current_name = None
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("BreakLine Name="):
                current_name = GeomParser.extract_keyword_value(lines[i], "BreakLine Name")
            elif stripped.startswith("BreakLine Polyline="):
                count = GeomProjection._extract_count(lines[i], "BreakLine Polyline")
                values, next_i = GeomProjection._read_coord_block_values(
                    lines,
                    i + 1,
                    count,
                )
                points = len(values) // 2
                records.append(
                    {
                        "name": current_name or "",
                        "point_count": points,
                        "declared_point_count": count,
                        "is_valid": points == count and count >= 2,
                    }
                )
                i = next_i
                continue
            i += 1
        return records

    @staticmethod
    def _read_coord_block_values(
        lines: List[str],
        start_index: int,
        count: int,
    ) -> Tuple[List[float], int]:
        total_values = count * 2
        data_lines: List[str] = []
        idx = start_index
        values: List[float] = []
        while idx < len(lines) and len(values) < total_values:
            stripped = lines[idx].strip()
            if not stripped or "=" in stripped:
                break
            data_lines.append(lines[idx])
            values = GeomProjection._parse_coord_values(data_lines, total_values)
            idx += 1
        return values, idx

    @staticmethod
    def _inspect_terrain_requirements(
        project_folder: Path,
        destination_crs: Any,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for rasmap_path in sorted(project_folder.glob("*.rasmap")):
            try:
                root = ET.parse(rasmap_path).getroot()
            except ET.ParseError as exc:
                records.append(
                    {
                        "rasmap_path": str(rasmap_path),
                        "error": f"Could not parse rasmap XML: {exc}",
                        "requires_reprojection": True,
                    }
                )
                continue
            for layer in root.findall(".//Terrains/Layer"):
                filename = layer.get("Filename")
                terrain_path = GeomProjection._resolve_rasmap_file_reference(
                    rasmap_path.parent,
                    filename,
                )
                actual_crs = GeomProjection._read_asset_crs(terrain_path)
                crs_matches = (
                    actual_crs is not None
                    and GeomProjection._crs_equivalent(actual_crs, destination_crs)
                )
                records.append(
                    {
                        "rasmap_path": str(rasmap_path),
                        "terrain_name": layer.get("Name", ""),
                        "terrain_filename": filename,
                        "terrain_path": str(terrain_path) if terrain_path else None,
                        "terrain_exists": bool(terrain_path and terrain_path.exists()),
                        "terrain_crs": (
                            GeomProjection._crs_label(actual_crs)
                            if actual_crs is not None
                            else None
                        ),
                        "destination_crs": GeomProjection._crs_label(destination_crs),
                        "requires_reprojection": not crs_matches,
                        "requirement": (
                            "Terrain CRS does not match destination CRS; rebuild "
                            "or reproject terrain before hydraulic validation."
                            if not crs_matches
                            else "Terrain CRS already matches destination CRS."
                        ),
                    }
                )
        return records

    @staticmethod
    def _resolve_rasmap_file_reference(
        base_folder: Path,
        filename: Optional[str],
    ) -> Optional[Path]:
        if not filename:
            return None
        expanded = os.path.expandvars(filename).replace("/", "\\")
        windows_path = PureWindowsPath(expanded)
        if windows_path.is_absolute():
            return RasUtils.safe_resolve(Path(str(windows_path)))
        if expanded.startswith(".\\") or expanded.startswith("./"):
            expanded = expanded[2:]
        return RasUtils.safe_resolve(base_folder / Path(*PureWindowsPath(expanded).parts))

    @staticmethod
    def _read_asset_crs(path: Optional[Path]) -> Optional[Any]:
        if path is None or not path.exists():
            return None
        try:
            from ..hdf.HdfBase import HdfBase

            projection = HdfBase.get_projection(path)
            if projection:
                return GeomProjection._crs_from_input(projection)
        except Exception:
            pass

        if path.suffix.lower() in {".tif", ".tiff"}:
            try:
                import rasterio

                with rasterio.open(path) as dataset:
                    if dataset.crs:
                        return GeomProjection._crs_from_input(dataset.crs)
            except Exception:
                return None
        return None

    @staticmethod
    def _crs_equivalent(left_crs: Any, right_crs: Any) -> bool:
        try:
            return bool(left_crs.equals(right_crs))
        except Exception:
            return GeomProjection._crs_label(left_crs) == GeomProjection._crs_label(right_crs)

    @staticmethod
    def _inspect_compiled_geometry_hdfs(geom_paths: Sequence[Path]) -> List[Dict[str, Any]]:
        records = []
        for geom_path in geom_paths:
            hdf_path = Path(str(geom_path) + ".hdf")
            record = {
                "geometry_file": str(geom_path),
                "compiled_hdf_path": str(hdf_path),
                "compiled_hdf_exists": hdf_path.exists(),
                "geometry_preprocess_required": True,
                "refinement_region_count": None,
                "refinement_region_integrity": {
                    "checked": False,
                    "is_valid": None,
                    "issues": [],
                },
                "refinement_region_requirement": (
                    "Compiled refinement regions are not transformed by "
                    "GeomProjection; rebuild geometry preprocessing after "
                    "reviewing text geometry."
                ),
            }
            if hdf_path.exists():
                try:
                    import h5py

                    with h5py.File(hdf_path, "r") as hdf:
                        rr_attrs = hdf.get(
                            "Geometry/2D Flow Area Refinement Regions/Attributes"
                        )
                        if rr_attrs is not None:
                            record["refinement_region_count"] = int(len(rr_attrs))
                        record["refinement_region_integrity"] = (
                            GeomProjection._inspect_refinement_region_integrity(hdf)
                        )
                except Exception as exc:
                    record["compiled_hdf_warning"] = str(exc)
            records.append(record)
        return records

    @staticmethod
    def _inspect_refinement_region_integrity(hdf: Any) -> Dict[str, Any]:
        group_path = "Geometry/2D Flow Area Refinement Regions"
        group = hdf.get(group_path)
        if group is None:
            return {
                "checked": True,
                "is_valid": True,
                "issues": [],
                "dataset_names": [],
            }

        required = ("Attributes", "Polygon Info", "Polygon Parts", "Polygon Points")
        dataset_names = sorted(group.keys())
        issues = [
            f"Missing refinement region dataset: {name}"
            for name in required
            if name not in group
        ]
        if issues:
            return {
                "checked": True,
                "is_valid": False,
                "issues": issues,
                "dataset_names": dataset_names,
            }

        attrs = group["Attributes"]
        polygon_info = group["Polygon Info"]
        polygon_parts = group["Polygon Parts"]
        polygon_points = group["Polygon Points"]

        region_count = int(len(attrs))
        if len(polygon_info) != region_count:
            issues.append(
                "Refinement region Attributes and Polygon Info row counts differ: "
                f"{region_count} != {len(polygon_info)}"
            )
        if len(getattr(polygon_info, "shape", ())) != 2 or polygon_info.shape[1] < 4:
            issues.append("Refinement region Polygon Info must be an Nx4 dataset.")
        if len(getattr(polygon_points, "shape", ())) != 2 or polygon_points.shape[1] != 2:
            issues.append("Refinement region Polygon Points must be an Nx2 dataset.")
        if len(getattr(polygon_parts, "shape", ())) != 2 or polygon_parts.shape[1] != 2:
            issues.append("Refinement region Polygon Parts must be an Nx2 dataset.")

        if not issues:
            points = polygon_points[:]
            parts = polygon_parts[:]
            for region_index, row in enumerate(polygon_info[:]):
                pnt_start, pnt_count, part_start, part_count = [
                    int(value) for value in row[:4]
                ]
                if pnt_count < 4:
                    issues.append(
                        f"Refinement region {region_index} has fewer than four "
                        "polygon points."
                    )
                    continue
                if pnt_start < 0 or pnt_start + pnt_count > len(points):
                    issues.append(
                        f"Refinement region {region_index} polygon point range "
                        "is outside Polygon Points."
                    )
                    continue
                if part_start < 0 or part_start + part_count > len(parts):
                    issues.append(
                        f"Refinement region {region_index} polygon part range "
                        "is outside Polygon Parts."
                    )
                ring = points[pnt_start:pnt_start + pnt_count]
                if len(ring) >= 2 and not (
                    math.isclose(float(ring[0][0]), float(ring[-1][0]), abs_tol=1e-6)
                    and math.isclose(float(ring[0][1]), float(ring[-1][1]), abs_tol=1e-6)
                ):
                    issues.append(
                        f"Refinement region {region_index} polygon is not closed."
                    )

        return {
            "checked": True,
            "is_valid": not issues,
            "issues": issues,
            "dataset_names": dataset_names,
        }
