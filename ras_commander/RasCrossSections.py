"""Unified point-level cross-section extraction for text and HDF geometry."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class VerticalTransform:
    """Explicit, auditable three-dimensional coordinate transformation.

    Supply an exact PROJ ``pipeline`` or both ``source_crs`` and ``target_crs``.
    CRS-to-CRS mode requires full 3D or compound CRS definitions when a vertical
    datum change is intended. Every point is transformed with its own X, Y, and
    Z coordinate; no representative model centroid is used.

    The source/target vertical datum and unit labels are required independently
    of the CRS definitions so exported provenance remains understandable without
    interpreting WKT.
    """

    source_vertical_datum: str
    target_vertical_datum: str
    source_vertical_units: str
    target_vertical_units: str
    pipeline: str | None = None
    source_crs: Any = None
    target_crs: Any = None
    allow_ballpark: bool = False

    def __post_init__(self) -> None:
        labels = {
            "source_vertical_datum": self.source_vertical_datum,
            "target_vertical_datum": self.target_vertical_datum,
            "source_vertical_units": self.source_vertical_units,
            "target_vertical_units": self.target_vertical_units,
        }
        missing = [name for name, value in labels.items() if not str(value or "").strip()]
        if missing:
            raise ValueError(f"VerticalTransform requires non-empty {', '.join(missing)}.")
        if not self.pipeline and (self.source_crs is None or self.target_crs is None):
            raise ValueError(
                "VerticalTransform requires an exact PROJ pipeline or both "
                "source_crs and target_crs."
            )

    @staticmethod
    def _crs_wkt(value: Any) -> str | None:
        if value is None:
            return None
        from pyproj import CRS

        return CRS.from_user_input(value).to_wkt("WKT2_2019")

    def apply(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Apply the configured operation to every row and return provenance."""
        import pyproj
        from pyproj import CRS, Transformer

        if self.pipeline:
            transformer = Transformer.from_pipeline(self.pipeline)
            mode = "proj_pipeline"
        else:
            transformer = Transformer.from_crs(
                self.source_crs,
                self.target_crs,
                always_xy=True,
                allow_ballpark=self.allow_ballpark,
                only_best=True,
            )
            mode = "crs_to_crs"

        x, y, z = transformer.transform(
            frame["x"].to_numpy(dtype=float),
            frame["y"].to_numpy(dtype=float),
            frame["z"].to_numpy(dtype=float),
            errcheck=True,
        )
        transformed = frame.copy()
        transformed["x"] = np.asarray(x, dtype=float)
        transformed["y"] = np.asarray(y, dtype=float)
        transformed["z"] = np.asarray(z, dtype=float)
        if not np.isfinite(transformed[["x", "y", "z"]].to_numpy(dtype=float)).all():
            raise ValueError("Vertical transformation produced non-finite coordinates.")

        operation = transformer
        try:
            operation = transformer.get_last_used_operation()
        except (AttributeError, pyproj.exceptions.ProjError) as exc:
            logger.debug("Resolved PROJ operation details are unavailable: %s", exc)

        if self.target_crs is not None:
            target = CRS.from_user_input(self.target_crs)
            transformed["horizontal_crs"] = target.to_string()
            transformed["horizontal_units"] = RasCrossSections._crs_units(target)

        provenance = {
            "schema_version": 1,
            "applied": True,
            "coordinate_strategy": "per_point_xyz",
            "mode": mode,
            "always_xy": True,
            "allow_ballpark": bool(self.allow_ballpark),
            "source_vertical_datum": self.source_vertical_datum,
            "target_vertical_datum": self.target_vertical_datum,
            "source_vertical_units": self.source_vertical_units,
            "target_vertical_units": self.target_vertical_units,
            "source_crs_wkt": self._crs_wkt(self.source_crs),
            "target_crs_wkt": self._crs_wkt(self.target_crs),
            "requested_pipeline": self.pipeline,
            "operation_definition": getattr(operation, "definition", None),
            "operation_description": getattr(operation, "description", None),
            "operation_accuracy": getattr(operation, "accuracy", None),
            "pyproj_version": pyproj.__version__,
            "proj_version": pyproj.proj_version_str,
        }
        transformed["vertical_units"] = self.target_vertical_units
        transformed["vertical_datum"] = self.target_vertical_datum
        return transformed, provenance


@dataclass(frozen=True)
class _ProjectContext:
    model_id: str
    folder: Path
    project_file: Path
    ras_object: Any
    horizontal_crs: Any
    model_units: str | None


@dataclass(frozen=True)
class _GeometryContext:
    geometry_id: str
    geometry_title: str | None
    text_path: Path | None
    hdf_path: Path | None
    direct_source: str | None


class RasCrossSections:
    """Common, static API for point-level HEC-RAS cross-section exports."""

    POINT_COLUMNS = (
        "model_id",
        "geometry_id",
        "geometry_title",
        "reach_id",
        "xs_id",
        "river",
        "reach",
        "river_station",
        "point_order",
        "station_order",
        "station",
        "relative_distance",
        "x",
        "y",
        "z",
        "mannings_n",
        "bank_region",
        "is_bank_station",
        "bank_side",
        "left_bank_station",
        "right_bank_station",
        "horizontal_crs",
        "horizontal_units",
        "vertical_units",
        "vertical_datum",
        "source_file",
        "extraction_method",
        "vertical_transform_applied",
        "vertical_transform_provenance",
    )

    @staticmethod
    def _decode_project_units(project_file: Path) -> str | None:
        from .RasPrj import RasPrj

        return RasPrj.get_project_units(project_file)

    @staticmethod
    def _project_context(project: Any) -> _ProjectContext:
        if hasattr(project, "project_folder") and hasattr(project, "project_name"):
            folder = Path(project.project_folder)
            project_file = Path(getattr(project, "prj_file", folder / f"{project.project_name}.prj"))
            return _ProjectContext(
                model_id=str(project.project_name),
                folder=folder,
                project_file=project_file,
                ras_object=project,
                horizontal_crs=getattr(project, "project_crs", None),
                model_units=RasCrossSections._decode_project_units(project_file),
            )

        path = Path(project)
        if path.is_file():
            if path.suffix.lower() != ".prj":
                raise ValueError(f"Project path must be a HEC-RAS .prj file or folder: {path}")
            project_file = path
            folder = path.parent
        elif path.is_dir():
            candidates = sorted(path.glob("*.prj"))
            matching = [candidate for candidate in candidates if candidate.stem == path.name]
            if len(matching) == 1:
                project_file = matching[0]
            elif len(candidates) == 1:
                project_file = candidates[0]
            else:
                raise ValueError(
                    f"Expected one HEC-RAS project file in {path}; found "
                    f"{[candidate.name for candidate in candidates]}."
                )
            folder = path
        else:
            raise FileNotFoundError(f"HEC-RAS project not found: {project}")

        return _ProjectContext(
            model_id=project_file.stem,
            folder=folder,
            project_file=project_file,
            ras_object=None,
            horizontal_crs=None,
            model_units=RasCrossSections._decode_project_units(project_file),
        )

    @staticmethod
    def _geometry_number(path_or_name: Any) -> str | None:
        match = re.search(r"\.g(\d{1,2})(?:\.hdf)?$", str(path_or_name), re.IGNORECASE)
        if match:
            return match.group(1).zfill(2)
        match = re.fullmatch(r"[gG]?(\d{1,2})", str(path_or_name).strip())
        return match.group(1).zfill(2) if match else None

    @staticmethod
    def _geometry_title(path: Path | None) -> str | None:
        if path is None or not path.is_file():
            return None
        try:
            with open(path, encoding="utf-8", errors="replace") as stream:
                for _ in range(20):
                    line = stream.readline()
                    if not line:
                        break
                    if line.startswith("Geom Title="):
                        return line.split("=", 1)[1].strip() or None
        except OSError:
            return None
        return None

    @staticmethod
    def _geometry_context(context: _ProjectContext, geometry: Any) -> _GeometryContext:
        candidate = Path(geometry) if isinstance(geometry, (str, Path)) else None
        if candidate is not None and candidate.is_file():
            candidate = candidate.resolve()
            is_hdf = candidate.name.lower().endswith(".hdf")
            text_path = candidate.with_suffix("") if is_hdf else candidate
            hdf_path = candidate if is_hdf else Path(f"{candidate}.hdf")
            return _GeometryContext(
                geometry_id=RasCrossSections._geometry_number(candidate) or candidate.stem,
                geometry_title=RasCrossSections._geometry_title(text_path),
                text_path=text_path if text_path.is_file() else None,
                hdf_path=hdf_path if hdf_path.is_file() else None,
                direct_source="hdf" if is_hdf else "text",
            )

        selector = str(geometry).strip()
        number = RasCrossSections._geometry_number(selector)
        ras_object = context.ras_object
        if ras_object is not None:
            geom_df = getattr(ras_object, "geom_df", None)
            if geom_df is not None and not geom_df.empty:
                matches = pd.Series(False, index=geom_df.index)
                if number is not None and "geom_number" in geom_df:
                    matches |= geom_df["geom_number"].astype(str).str.zfill(2).eq(number)
                for column in ("geom_file", "geom_title", "full_path", "hdf_path"):
                    if column in geom_df:
                        values = geom_df[column].fillna("").astype(str)
                        matches |= values.eq(selector) | values.map(lambda value: Path(value).name).eq(selector)
                rows = geom_df[matches]
                if len(rows) > 1:
                    raise ValueError(f"Geometry selector is ambiguous in geom_df: {geometry}")
                if len(rows) == 1:
                    row = rows.iloc[0]
                    text = Path(str(row["full_path"])) if pd.notna(row.get("full_path")) else None
                    hdf = Path(str(row["hdf_path"])) if pd.notna(row.get("hdf_path")) else None
                    return _GeometryContext(
                        geometry_id=str(row.get("geom_number") or number or selector).zfill(2),
                        geometry_title=row.get("geom_title") if pd.notna(row.get("geom_title")) else RasCrossSections._geometry_title(text),
                        text_path=text if text is not None and text.is_file() else None,
                        hdf_path=hdf if hdf is not None and hdf.is_file() else None,
                        direct_source=None,
                    )

        text_candidates = sorted(
            path for path in context.folder.glob("*.g[0-9][0-9]") if path.is_file()
        )
        if number is not None:
            text = next(
                (path for path in text_candidates if RasCrossSections._geometry_number(path) == number),
                context.folder / f"{context.model_id}.g{number}",
            )
            hdf = Path(f"{text}.hdf")
            if not text.is_file() and not hdf.is_file():
                hdf_matches = [
                    path for path in context.folder.glob("*.g[0-9][0-9].hdf")
                    if RasCrossSections._geometry_number(path) == number
                ]
                hdf = hdf_matches[0] if len(hdf_matches) == 1 else hdf
            if text.is_file() or hdf.is_file():
                return _GeometryContext(
                    geometry_id=number,
                    geometry_title=RasCrossSections._geometry_title(text),
                    text_path=text if text.is_file() else None,
                    hdf_path=hdf if hdf.is_file() else None,
                    direct_source=None,
                )

        title_matches = [path for path in text_candidates if RasCrossSections._geometry_title(path) == selector]
        if len(title_matches) == 1:
            text = title_matches[0]
            hdf = Path(f"{text}.hdf")
            return _GeometryContext(
                geometry_id=RasCrossSections._geometry_number(text) or selector,
                geometry_title=selector,
                text_path=text,
                hdf_path=hdf if hdf.is_file() else None,
                direct_source=None,
            )
        raise FileNotFoundError(f"Geometry not found for selector {geometry!r} in {context.folder}.")

    @staticmethod
    def _crs_units(crs: Any) -> str | None:
        if crs is None:
            return None
        try:
            from pyproj import CRS

            parsed = CRS.from_user_input(crs)
            return parsed.axis_info[0].unit_name if parsed.axis_info else None
        except (TypeError, ValueError) as exc:
            logger.debug("Could not determine CRS units from %r: %s", crs, exc)
            return None

    @staticmethod
    def _point_mannings(stations: np.ndarray, breakpoints: pd.DataFrame) -> np.ndarray:
        if breakpoints.empty:
            return np.full(len(stations), np.nan, dtype=float)
        starts = breakpoints["Station"].to_numpy(dtype=float)
        values = breakpoints["n_value"].to_numpy(dtype=float)
        order = np.argsort(starts, kind="stable")
        starts = starts[order]
        values = values[order]
        indices = np.clip(np.searchsorted(starts, stations, side="right") - 1, 0, len(starts) - 1)
        return values[indices]

    @staticmethod
    def _text_points(
        path: Path,
        *,
        river: str | None,
        reach: str | None,
        river_station: str | None,
        horizontal_crs: Any,
        horizontal_units: str | None,
        vertical_units: str | None,
        vertical_datum: str | None,
        ras_object: Any,
    ) -> pd.DataFrame:
        from .geom.GeomCrossSection import GeomCrossSection
        from .geom.GeomParser import GeomParser

        points = GeomCrossSection.get_xs_coords(
            path, river=river, reach=reach, rs=river_station, ras_object=ras_object
        ).rename(columns={"RS": "river_station"})
        cut_lines = GeomParser.get_xs_cut_lines(path, ras_object=ras_object)
        cut_line_lookup = {
            (str(row["river"]), str(row["reach"]), str(row["station"])): row["geometry"]
            for _, row in cut_lines.iterrows()
        }

        enriched = []
        for (river_name, reach_name, rs), group in points.groupby(
            ["river", "reach", "river_station"], sort=False
        ):
            group = group.copy().reset_index(drop=True)
            stations = group["station"].to_numpy(dtype=float)
            minimum = float(np.nanmin(stations))
            maximum = float(np.nanmax(stations))
            span = maximum - minimum
            fractions = np.full(len(group), 0.5) if np.isclose(span, 0.0) else (stations - minimum) / span
            cut_line = cut_line_lookup.get((str(river_name), str(reach_name), str(rs)))
            length = float(cut_line.length) if cut_line is not None else float(
                np.hypot(np.diff(group["x"]), np.diff(group["y"])).sum()
            )
            group["point_order"] = np.arange(len(group), dtype=int)
            group["station_order"] = np.argsort(
                np.argsort(stations, kind="stable"), kind="stable"
            )
            group["relative_distance"] = fractions * length

            banks = GeomCrossSection.get_bank_stations(path, str(river_name), str(reach_name), str(rs))
            left_bank, right_bank = banks if banks is not None else (np.nan, np.nan)
            mannings = GeomCrossSection.get_mannings_n(
                path, str(river_name), str(reach_name), str(rs)
            )
            group["mannings_n"] = RasCrossSections._point_mannings(stations, mannings)
            tolerance = max(abs(span) * 1e-9, 1e-9)
            at_left = np.isfinite(left_bank) & np.isclose(stations, left_bank, rtol=0.0, atol=tolerance)
            at_right = np.isfinite(right_bank) & np.isclose(stations, right_bank, rtol=0.0, atol=tolerance)
            group["bank_region"] = np.where(
                np.isfinite(left_bank) & (stations < left_bank),
                "left_overbank",
                np.where(
                    np.isfinite(right_bank) & (stations > right_bank),
                    "right_overbank",
                    "channel" if np.isfinite(left_bank) and np.isfinite(right_bank) else "unknown",
                ),
            )
            group["is_bank_station"] = at_left | at_right
            group["bank_side"] = np.where(at_left, "left", np.where(at_right, "right", None))
            group["left_bank_station"] = left_bank
            group["right_bank_station"] = right_bank
            enriched.append(group)

        result = pd.concat(enriched, ignore_index=True)
        result["horizontal_crs"] = str(horizontal_crs) if horizontal_crs is not None else None
        result["horizontal_units"] = horizontal_units
        result["vertical_units"] = vertical_units
        result["vertical_datum"] = vertical_datum
        result["source_file"] = str(path.resolve())
        result["extraction_method"] = "text_geometry"
        return result

    @staticmethod
    def _units_key(value: Any) -> str:
        normalized = str(value or "").strip().lower().replace("_", " ")
        aliases = {
            "feet": "ft", "foot": "ft", "international foot": "ft",
            "meters": "m", "meter": "m", "metres": "m", "metre": "m",
            "us survey foot": "us survey ft", "us-ft": "us survey ft",
        }
        return aliases.get(normalized, normalized)

    @staticmethod
    def _validate_transform_source(frame: pd.DataFrame, transform: VerticalTransform) -> None:
        units = next((value for value in frame["vertical_units"] if pd.notna(value)), None)
        if units is not None and RasCrossSections._units_key(units) != RasCrossSections._units_key(transform.source_vertical_units):
            raise ValueError(
                f"VerticalTransform source units {transform.source_vertical_units!r} do not "
                f"match extracted vertical units {units!r}."
            )
        datum = next((value for value in frame["vertical_datum"] if pd.notna(value)), None)
        if datum is not None and str(datum).strip().casefold() != transform.source_vertical_datum.strip().casefold():
            raise ValueError(
                f"VerticalTransform source datum {transform.source_vertical_datum!r} does not "
                f"match extracted vertical datum {datum!r}."
            )

    @staticmethod
    @log_call
    def get_points(
        project: Any,
        geometry: str | int | Path,
        *,
        source: str = "auto",
        river: str | None = None,
        reach: str | None = None,
        river_station: str | None = None,
        horizontal_crs: Any = None,
        vertical_units: str | None = None,
        vertical_datum: str | None = None,
        vertical_transform: VerticalTransform | None = None,
    ) -> pd.DataFrame:
        """Return a unified, provenance-rich cross-section point table.

        ``project`` accepts a :class:`RasPrj`, project folder, or project
        ``.prj`` path. ``geometry`` accepts a geometry number, title, text path,
        or geometry-HDF path. In ``source='auto'`` mode an explicit path keeps
        its source type; a project geometry selector prefers an available HDF
        and otherwise uses the text geometry.

        Native elevations are preserved by default. A vertical transformation
        occurs only when ``vertical_transform`` is supplied, and its complete
        per-point operation provenance is repeated in the export-safe
        ``vertical_transform_provenance`` column and stored in ``DataFrame.attrs``.
        """
        source = str(source).strip().lower()
        if source not in {"auto", "hdf", "text"}:
            raise ValueError("source must be one of 'auto', 'hdf', or 'text'.")

        project_context = RasCrossSections._project_context(project)
        geometry_context = RasCrossSections._geometry_context(project_context, geometry)
        if source == "auto":
            selected = geometry_context.direct_source or (
                "hdf" if geometry_context.hdf_path is not None else "text"
            )
        else:
            selected = source

        resolved_horizontal_crs = horizontal_crs or project_context.horizontal_crs
        resolved_vertical_units = vertical_units or project_context.model_units
        if selected == "hdf":
            if geometry_context.hdf_path is None:
                raise FileNotFoundError(f"Geometry HDF is unavailable for {geometry!r}.")
            from .hdf.HdfXsec import HdfXsec

            frame = HdfXsec.get_xs_coords(
                geometry_context.hdf_path,
                river=river,
                reach=reach,
                rs=river_station,
                horizontal_crs=resolved_horizontal_crs,
                vertical_units=vertical_units,
                vertical_datum=vertical_datum,
                ras_object=project_context.ras_object,
            )
            if frame["vertical_units"].isna().all() and project_context.model_units:
                frame["vertical_units"] = project_context.model_units
        else:
            if geometry_context.text_path is None:
                raise FileNotFoundError(f"Text geometry is unavailable for {geometry!r}.")
            if resolved_horizontal_crs is None:
                from .hdf.HdfBase import HdfBase

                resolved_horizontal_crs = HdfBase.get_projection(geometry_context.text_path)
            frame = RasCrossSections._text_points(
                geometry_context.text_path,
                river=river,
                reach=reach,
                river_station=river_station,
                horizontal_crs=resolved_horizontal_crs,
                horizontal_units=RasCrossSections._crs_units(resolved_horizontal_crs) or project_context.model_units,
                vertical_units=resolved_vertical_units,
                vertical_datum=vertical_datum,
                ras_object=project_context.ras_object,
            )

        frame.insert(0, "model_id", project_context.model_id)
        frame.insert(1, "geometry_id", geometry_context.geometry_id)
        frame.insert(2, "geometry_title", geometry_context.geometry_title)
        frame.insert(3, "reach_id", frame["river"].astype(str) + "|" + frame["reach"].astype(str))
        frame.insert(
            4,
            "xs_id",
            frame["river"].astype(str)
            + "|"
            + frame["reach"].astype(str)
            + "|"
            + frame["river_station"].astype(str),
        )

        if vertical_transform is None:
            transform_provenance = {
                "schema_version": 1,
                "applied": False,
                "coordinate_strategy": "native_z_preserved",
                "source_vertical_units": next(
                    (value for value in frame["vertical_units"] if pd.notna(value)), None
                ),
                "source_vertical_datum": next(
                    (value for value in frame["vertical_datum"] if pd.notna(value)), None
                ),
            }
        else:
            RasCrossSections._validate_transform_source(frame, vertical_transform)
            frame, transform_provenance = vertical_transform.apply(frame)

        provenance_json = json.dumps(transform_provenance, sort_keys=True, separators=(",", ":"))
        frame["vertical_transform_applied"] = bool(transform_provenance["applied"])
        frame["vertical_transform_provenance"] = provenance_json
        frame = frame.loc[:, RasCrossSections.POINT_COLUMNS]
        frame.attrs["schema"] = "ras_commander.cross_section_points.v1"
        frame.attrs["provenance"] = {
            "source_file": str(frame["source_file"].iloc[0]),
            "extraction_method": str(frame["extraction_method"].iloc[0]),
            "native_elevations": vertical_transform is None,
            "vertical_transform": transform_provenance,
        }
        return frame


__all__ = ["RasCrossSections", "VerticalTransform"]
