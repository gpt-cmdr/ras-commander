"""
Class: HdfXsec

Attribution: A substantial amount of code in this file is sourced or derived 
from the https://github.com/fema-ffrd/rashdf library, 
released under MIT license and Copyright (c) 2024 fema-ffrd

This source code has been forked and modified for use in RAS Commander.

-----

All of the methods in this class are static and are designed to be used without instantiation.

Available Functions:
- get_cross_sections(): Extract cross sections from HDF geometry file
- get_xs_coords(): Extract point-level XYZ cross-section geometry
- get_river_centerlines(): Extract river centerlines from HDF geometry file
- get_river_stationing(): Calculate river stationing along centerlines
- get_river_reaches(): Return the model 1D river reach lines
- get_river_edge_lines(): Return the model river edge lines
- get_river_bank_lines(): Extract river bank lines from HDF geometry file
- get_river_flow_paths(): Extract river flow paths from HDF geometry file
- get_xs_interpolation_surface(): Extract XS interpolation surface (TIN) from HDF
- generate_river_edge_lines(): Generate edge lines from XS cut-line end points
- get_1d_footprint(): Build 1D model footprint polygon(s) from edge lines
- _interpolate_station(): Private helper method for station interpolation

All functions follow the get_ prefix convention for methods that return data.
Private helper methods use the underscore prefix convention.

Functions return pandas or GeoPandas frames containing geometry and associated
attributes for the requested feature type. All functions include proper error
handling and logging.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import h5py
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Polygon

from ..Decorators import standardize_input, log_call
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..LoggingConfig import get_logger



logger = get_logger(__name__)

class HdfXsec:
    """
    Handles cross-section and river geometry data extraction from HEC-RAS HDF files.

    This class provides static methods to extract and process:
    - Cross-section geometries and attributes
    - River centerlines and reaches
    - River edge and bank lines
    - Station-elevation profiles

    All methods are designed to return GeoDataFrames with standardized geometries 
    and attributes following the HEC-RAS data structure.

    Note:
        Requires HEC-RAS geometry HDF files with standard structure and naming conventions.
        All methods use proper error handling and logging.
    """
    CROSS_SECTION_GROUP = "Geometry/Cross Sections"
    CROSS_SECTION_REQUIRED_DATASETS = (
        f"{CROSS_SECTION_GROUP}/Polyline Info",
        f"{CROSS_SECTION_GROUP}/Polyline Parts",
        f"{CROSS_SECTION_GROUP}/Polyline Points",
        f"{CROSS_SECTION_GROUP}/Station Elevation Info",
        f"{CROSS_SECTION_GROUP}/Station Elevation Values",
        f"{CROSS_SECTION_GROUP}/Attributes",
        f"{CROSS_SECTION_GROUP}/Manning's n Info",
        f"{CROSS_SECTION_GROUP}/Manning's n Values",
    )
    CROSS_SECTION_CORE_GEOMETRY_DATASETS = (
        f"{CROSS_SECTION_GROUP}/Polyline Info",
        f"{CROSS_SECTION_GROUP}/Polyline Parts",
        f"{CROSS_SECTION_GROUP}/Polyline Points",
    )

    @staticmethod
    def _cross_section_group(hdf: h5py.File) -> h5py.Group:
        """Return the cross-section group or fail with a schema-specific error."""
        path = "/Geometry/Cross Sections"
        if path not in hdf or not isinstance(hdf[path], h5py.Group):
            raise ValueError(f"Missing cross-section group: {path}")
        return hdf[path]

    @staticmethod
    def _dataset(group: h5py.Group, name: str, *, columns: int = 0) -> np.ndarray:
        """Read one required cross-section dataset and validate its shape."""
        if name not in group or not isinstance(group[name], h5py.Dataset):
            raise ValueError(f"Missing cross-section dataset: {group.name}/{name}")
        values = group[name][()]
        if values.ndim == 0:
            raise ValueError(f"Cross-section dataset is scalar: {group.name}/{name}")
        if columns and (values.ndim != 2 or values.shape[1] < columns):
            raise ValueError(
                f"Cross-section dataset {group.name}/{name} must have at least "
                f"{columns} columns; found shape {values.shape}"
            )
        return values

    @staticmethod
    def _get_cross_section_count(hdf: h5py.File) -> int:
        """Return the XS row count for compound or legacy separated schemas.

        HEC-RAS 5.x geometry HDF files store cross-section identity and
        hydraulic attributes in separate datasets instead of the compound
        ``Attributes`` dataset used by newer releases. A legacy schema is
        recognized only when its three independent row anchors are present.
        All feature-row datasets that are present must agree on row count.
        This establishes dimensional evidence; full reader methods separately
        validate the datasets needed to extract hydraulic content.
        """
        path = "/Geometry/Cross Sections"
        if path not in hdf:
            return 0
        group = HdfXsec._cross_section_group(hdf)

        if "Attributes" in group:
            attributes = group["Attributes"]
            if not isinstance(attributes, h5py.Dataset) or len(attributes.shape) != 1:
                raise ValueError(
                    "Cross-section Attributes must be a one-dimensional dataset; "
                    f"found {getattr(attributes, 'shape', None)}"
                )
            row_count = int(attributes.shape[0])
        else:
            legacy_anchors = ("Node Names", "River Stations", "Polyline Info")
            present = [name for name in legacy_anchors if name in group]
            if not present:
                return 0
            if len(present) != len(legacy_anchors):
                missing = sorted(set(legacy_anchors) - set(present))
                raise ValueError(
                    "Incomplete legacy cross-section schema; missing row anchors: "
                    + ", ".join(missing)
                )
            row_count = int(group["Polyline Info"].shape[0])

        row_datasets = (
            "Polyline Info",
            "Station Elevation Info",
            "Manning's n Info",
            "Station Manning's n Info",
            "Ineffective Info",
            "Blocked Ineffective Info",
            "River Names",
            "Reach Names",
            "River Stations",
            "Node Names",
            "Node Descriptions",
            "Lengths",
            "Bank Stations",
            "Contr Expan Coef",
            "Hydraulic Tables Starting Elevation and Increment Size",
            "Hydraulic Tables Vertical and Horizontal Slices",
        )
        inconsistent = []
        for name in row_datasets:
            if name not in group:
                continue
            dataset = group[name]
            if not isinstance(dataset, h5py.Dataset) or not dataset.shape:
                raise ValueError(f"Unreadable cross-section dataset: {group.name}/{name}")
            rows = int(dataset.shape[0])
            if rows != row_count:
                inconsistent.append(f"{name}={rows}")

        if inconsistent:
            raise ValueError(
                f"Cross-section row count mismatch (expected {row_count}): "
                + ", ".join(inconsistent)
            )
        return row_count

    @staticmethod
    def _info_values_pair(
        group: h5py.Group,
        info_names: Tuple[str, ...],
        value_names: Tuple[str, ...],
        row_count: int,
        *,
        value_columns: int,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Select and validate a matching info/value dataset pair."""
        info_name = value_name = None
        for candidate_info, candidate_values in zip(info_names, value_names):
            if candidate_info in group or candidate_values in group:
                if candidate_info not in group or candidate_values not in group:
                    raise ValueError(
                        "Incomplete cross-section info/value dataset pair: "
                        f"{candidate_info!r} / {candidate_values!r}"
                    )
                info_name, value_name = candidate_info, candidate_values
                break
        if info_name is None:
            raise ValueError(
                "Missing cross-section info/value dataset pair: "
                f"{info_names!r} / {value_names!r}"
            )

        info = HdfXsec._dataset(group, info_name, columns=2)
        values = HdfXsec._dataset(group, value_name, columns=value_columns)
        if len(info) != row_count:
            raise ValueError(
                f"Cross-section row count mismatch (expected {row_count}): "
                f"{info_name}={len(info)}"
            )

        for row_index, (raw_start, raw_count, *_) in enumerate(info):
            start = int(raw_start)
            count = int(raw_count)
            if (
                not np.isfinite(float(raw_start))
                or not np.isfinite(float(raw_count))
                or float(raw_start) != start
                or float(raw_count) != count
            ):
                raise ValueError(
                    f"Non-integer {info_name} slice at cross-section row "
                    f"{row_index}: start={raw_start}, count={raw_count}"
                )
            if start < 0 or count < 0 or start + count > len(values):
                raise ValueError(
                    f"Invalid {info_name} slice at cross-section row {row_index}: "
                    f"start={start}, count={count}, values={len(values)}"
                )
        return info, values

    @staticmethod
    def _legacy_cross_section_attributes(
        group: h5py.Group,
        row_count: int,
    ) -> Dict[str, np.ndarray]:
        """Normalize HEC-RAS 5.x separated XS attributes by public field name."""
        column_specs = {
            "River": ("River Names", None),
            "Reach": ("Reach Names", None),
            "RS": ("River Stations", None),
            "Name": ("Node Names", None),
            "Description": ("Node Descriptions", None),
            "Len Left": ("Lengths", 0),
            "Len Channel": ("Lengths", 1),
            "Len Right": ("Lengths", 2),
            "Left Bank": ("Bank Stations", 0),
            "Right Bank": ("Bank Stations", 1),
            "Contr": ("Contr Expan Coef", 0),
            "Expan": ("Contr Expan Coef", 1),
            "HP Start Elev": (
                "Hydraulic Tables Starting Elevation and Increment Size",
                0,
            ),
            "HP Vert Incr": (
                "Hydraulic Tables Starting Elevation and Increment Size",
                1,
            ),
            "HP Count": ("Hydraulic Tables Vertical and Horizontal Slices", 0),
            "HP LOB Slices": (
                "Hydraulic Tables Vertical and Horizontal Slices",
                1,
            ),
            "HP Chan Slices": (
                "Hydraulic Tables Vertical and Horizontal Slices",
                2,
            ),
            "HP ROB Slices": (
                "Hydraulic Tables Vertical and Horizontal Slices",
                3,
            ),
        }
        attributes = {}
        for field_name, (dataset_name, column) in column_specs.items():
            values = HdfXsec._dataset(
                group,
                dataset_name,
                columns=column + 1 if column is not None else 0,
            )
            if len(values) != row_count:
                raise ValueError(
                    f"Cross-section row count mismatch (expected {row_count}): "
                    f"{dataset_name}={len(values)}"
                )
            column_values = values if column is None else values[:, column]
            if field_name.startswith("Len "):
                column_values = np.asarray(column_values, dtype=float).copy()
                column_values[column_values >= np.finfo(np.float32).max * 0.99] = np.nan
            attributes[field_name] = column_values
        return attributes

    @staticmethod
    def _attribute_columns(
        group: h5py.Group,
        row_count: int,
    ) -> Dict[str, np.ndarray]:
        """Return normalized attribute columns for either supported XS schema."""
        if "Attributes" not in group:
            return HdfXsec._legacy_cross_section_attributes(group, row_count)
        attributes = HdfXsec._dataset(group, "Attributes")
        if len(attributes) != row_count or not attributes.dtype.names:
            raise ValueError(
                "Cross-section Attributes must be a compound dataset with one row "
                "per cross section"
            )
        return {name: attributes[name] for name in attributes.dtype.names}

    @staticmethod
    def _string_values(values: np.ndarray) -> List[str]:
        """Decode fixed-width HDF strings without interpreting their contents."""
        decoded = []
        for value in values:
            if isinstance(value, (bytes, np.bytes_)):
                value = bytes(value).decode("utf-8", errors="replace")
            decoded.append(str(value).strip())
        return decoded

    @staticmethod
    def _polyline_geometries(
        group: h5py.Group,
        info_name: str,
        parts_name: str,
        points_name: str,
        *,
        expected_rows: Optional[int] = None,
    ) -> List:
        """Build validated polylines from one HEC-RAS info/parts/points trio."""
        info = HdfXsec._dataset(group, info_name, columns=4)
        parts = HdfXsec._dataset(group, parts_name, columns=2)
        points = HdfXsec._dataset(group, points_name, columns=2)
        if expected_rows is not None and len(info) != expected_rows:
            raise ValueError(
                f"Polyline row count mismatch (expected {expected_rows}): "
                f"{info_name}={len(info)}"
            )

        geometries = []
        for row_index, row in enumerate(info):
            raw_indices = row[:4]
            point_start, point_count, part_start, part_count = (
                int(value) for value in raw_indices
            )
            if any(
                not np.isfinite(float(value)) or float(value) != int(value)
                for value in raw_indices
            ):
                raise ValueError(f"Non-integer polyline index/count at row {row_index}")
            if min(point_start, point_count, part_start, part_count) < 0:
                raise ValueError(f"Negative polyline index/count at row {row_index}")
            if point_count < 2 or point_start + point_count > len(points):
                raise ValueError(
                    f"Invalid {points_name} slice at row {row_index}: "
                    f"start={point_start}, count={point_count}, points={len(points)}"
                )
            if part_count == 0 or part_start + part_count > len(parts):
                raise ValueError(
                    f"Invalid {parts_name} slice at row {row_index}: "
                    f"start={part_start}, count={part_count}, parts={len(parts)}"
                )

            feature_parts = []
            expected_offset = 0
            for part in parts[part_start : part_start + part_count]:
                raw_offset, raw_points = part[:2]
                part_offset, part_points = int(raw_offset), int(raw_points)
                if (
                    not np.isfinite(float(raw_offset))
                    or not np.isfinite(float(raw_points))
                    or float(raw_offset) != part_offset
                    or float(raw_points) != part_points
                    or part_offset != expected_offset
                    or part_points < 2
                    or part_offset + part_points > point_count
                ):
                    raise ValueError(
                        f"Invalid {parts_name} point span at row {row_index}: "
                        f"offset={part_offset}, count={part_points}"
                    )
                start = point_start + part_offset
                part_coordinates = points[start : start + part_points]
                if not np.isfinite(part_coordinates).all():
                    raise ValueError(
                        f"Polyline part at row {row_index} contains non-finite points"
                    )
                feature_parts.append(LineString(part_coordinates))
                expected_offset += part_points
            if expected_offset != point_count:
                raise ValueError(
                    f"Polyline parts account for {expected_offset} points at row "
                    f"{row_index}; declared point count is {point_count}"
                )
            geometries.append(
                feature_parts[0]
                if len(feature_parts) == 1
                else MultiLineString(feature_parts)
            )
        return geometries

    @staticmethod
    def _filename(hdf_path) -> str:
        return Path(hdf_path).name

    @staticmethod
    def _convert_hdf_value(value):
        if isinstance(value, (bytes, np.bytes_)):
            converted = HdfUtils.convert_ras_string(value)
            return converted.strip() if isinstance(converted, str) else converted
        if isinstance(value, np.str_):
            converted = HdfUtils.convert_ras_string(str(value))
            return converted.strip() if isinstance(converted, str) else converted
        if isinstance(value, np.generic):
            return value.item()
        return value

    @staticmethod
    def _datetime_value_to_str(value):
        if pd.isna(value):
            return None
        try:
            return pd.Timestamp(value).isoformat()
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _structured_array_to_dict(attrs) -> dict:
        if not getattr(attrs.dtype, "names", None):
            return {}
        return {
            name: [HdfXsec._convert_hdf_value(value) for value in attrs[name]]
            for name in attrs.dtype.names
        }

    @staticmethod
    def _alternating_bank_sides(count: int) -> List[str]:
        return ["Left" if idx % 2 == 0 else "Right" for idx in range(count)]

    @staticmethod
    def _hdf_text(value: Any) -> Optional[str]:
        """Return a stripped string for an HDF scalar, or ``None``."""
        if value is None:
            return None
        converted = HdfXsec._convert_hdf_value(value)
        text = str(converted).strip()
        return text or None

    @staticmethod
    def _explicit_vertical_metadata(hdf_file: h5py.File) -> tuple[Optional[str], Optional[str]]:
        """Read only explicitly stored vertical metadata from an HDF file."""
        unit_names = {
            "vertical units", "vertical unit", "elevation units", "elevation unit"
        }
        datum_names = {
            "vertical datum", "verticaldatum", "elevation datum", "vertical crs"
        }
        vertical_units = None
        vertical_datum = None
        objects = [hdf_file]
        geometry = hdf_file.get("Geometry")
        if geometry is not None:
            objects.append(geometry)

        for obj in objects:
            for name, value in obj.attrs.items():
                normalized = str(name).strip().lower().replace("_", " ")
                if vertical_units is None and normalized in unit_names:
                    vertical_units = HdfXsec._hdf_text(value)
                if vertical_datum is None and normalized in datum_names:
                    vertical_datum = HdfXsec._hdf_text(value)
        return vertical_units, vertical_datum

    @staticmethod
    def _crs_units(crs: Any) -> Optional[str]:
        """Return the first axis unit declared by a CRS."""
        if crs is None:
            return None
        try:
            from pyproj import CRS

            parsed = CRS.from_user_input(crs)
            if parsed.axis_info:
                return parsed.axis_info[0].unit_name or None
        except Exception as exc:
            logger.debug("Could not determine CRS units from %r: %s", crs, exc)
        return None

    @staticmethod
    def _pair_columns(values: np.ndarray, first_names: tuple[str, ...], second_names: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
        """Read the two logical columns from numeric or structured HDF arrays."""
        names = getattr(values.dtype, "names", None)
        if names:
            normalized = {name.lower(): name for name in names}
            first = next((normalized[name.lower()] for name in first_names if name.lower() in normalized), None)
            second = next((normalized[name.lower()] for name in second_names if name.lower() in normalized), None)
            if first is None or second is None:
                raise ValueError(
                    f"Could not identify pair fields in HDF dtype {names}; "
                    f"expected {first_names} and {second_names}."
                )
            return np.asarray(values[first], dtype=float), np.asarray(values[second], dtype=float)

        array = np.asarray(values)
        if array.ndim != 2 or array.shape[1] < 2:
            raise ValueError(f"Expected an Nx2 HDF array, got shape {array.shape}.")
        return np.asarray(array[:, 0], dtype=float), np.asarray(array[:, 1], dtype=float)

    @staticmethod
    def _mannings_at_stations(stations: np.ndarray, mannings: np.ndarray) -> np.ndarray:
        """Map native Manning breakpoints to station/elevation points."""
        if len(mannings) == 0:
            return np.full(len(stations), np.nan, dtype=float)
        starts, n_values = HdfXsec._pair_columns(
            mannings,
            ("Station", "Start Station"),
            ("Mann n", "n_value", "Manning's n"),
        )
        order = np.argsort(starts, kind="stable")
        starts = starts[order]
        n_values = n_values[order]
        indices = np.searchsorted(starts, stations, side="right") - 1
        indices = np.clip(indices, 0, len(starts) - 1)
        return n_values[indices]

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_xs_coords(
        hdf_path: Path,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        rs: Optional[str] = None,
        horizontal_crs: Any = None,
        vertical_units: Optional[str] = None,
        vertical_datum: Optional[str] = None,
        ras_object=None,
    ) -> pd.DataFrame:
        """Extract point-level XYZ cross-section geometry from a geometry HDF.

        This is the HDF equivalent of
        :meth:`GeomCrossSection.get_xs_coords`. Station/elevation rows are
        projected onto each stored GIS cut line, in native order, and enriched
        with Manning's n and bank metadata. Elevations are returned exactly as
        stored; this method never performs a vertical transformation.

        Parameters
        ----------
        hdf_path:
            Geometry ``.g##.hdf`` path (or a supported geometry-HDF selector).
        river, reach, rs:
            Optional exact, case-sensitive filters.
        horizontal_crs:
            Explicit CRS override. Otherwise the embedded or adjacent RASMapper
            projection is used when available.
        vertical_units, vertical_datum:
            Explicit metadata overrides. Direct HDF extraction uses only
            genuinely explicit vertical-unit metadata; generic unit-system
            flags are not treated as authoritative. A vertical datum is
            reported only when explicitly provided or stored in the HDF; it is
            never inferred from the horizontal CRS.

        Returns
        -------
        pandas.DataFrame
            One row per native station/elevation point. Stable columns include
            identifiers, native/station order, cut-line relative distance, XYZ,
            Manning's n, bank classification, CRS/units, and source provenance.
        """
        hdf_path = Path(hdf_path)
        resolved_crs = horizontal_crs or HdfBase.get_projection(hdf_path)

        with h5py.File(hdf_path, "r") as hdf_file:
            group_path = f"/{HdfXsec.CROSS_SECTION_GROUP}"
            if group_path not in hdf_file:
                raise ValueError(f"No {HdfXsec.CROSS_SECTION_GROUP} group in {hdf_path}.")

            required = HdfXsec.CROSS_SECTION_REQUIRED_DATASETS
            missing = [path for path in required if path not in hdf_file]
            if missing:
                raise ValueError(
                    f"Cross-section point extraction requires dataset(s) missing from "
                    f"{hdf_path}: {', '.join(missing)}"
                )

            xs_attrs = hdf_file[f"{group_path}/Attributes"][:]
            poly_info = hdf_file[f"{group_path}/Polyline Info"][:]
            poly_parts = hdf_file[f"{group_path}/Polyline Parts"][:]
            poly_points = hdf_file[f"{group_path}/Polyline Points"][:]
            station_info = hdf_file[f"{group_path}/Station Elevation Info"][:]
            station_values = hdf_file[f"{group_path}/Station Elevation Values"][:]
            mann_info = hdf_file[f"{group_path}/Manning's n Info"][:]
            mann_values = hdf_file[f"{group_path}/Manning's n Values"][:]

            count = len(xs_attrs)
            aligned = {
                "Polyline Info": len(poly_info),
                "Station Elevation Info": len(station_info),
                "Manning's n Info": len(mann_info),
            }
            mismatched = {name: size for name, size in aligned.items() if size != count}
            if mismatched:
                raise ValueError(
                    f"Cross-section HDF arrays are not aligned with {count} Attributes rows: "
                    f"{mismatched}."
                )

            stored_vertical_units, stored_vertical_datum = HdfXsec._explicit_vertical_metadata(hdf_file)
            resolved_vertical_units = vertical_units or stored_vertical_units
            vertical_units_source = (
                "explicit"
                if vertical_units is not None
                else "geometry_hdf_explicit"
                if stored_vertical_units is not None
                else "unknown"
            )
            resolved_vertical_datum = vertical_datum or stored_vertical_datum

            rows = []
            for xs_index in range(count):
                attr = xs_attrs[xs_index]
                river_name = HdfXsec._hdf_text(attr["River"]) or ""
                reach_name = HdfXsec._hdf_text(attr["Reach"]) or ""
                river_station = HdfXsec._hdf_text(attr["RS"]) or ""
                if river is not None and river_name != river:
                    continue
                if reach is not None and reach_name != reach:
                    continue
                if rs is not None and river_station != str(rs):
                    continue

                point_start, _, part_start, part_count = map(int, poly_info[xs_index][:4])
                cut_line_points = []
                for part in poly_parts[part_start:part_start + part_count]:
                    relative_start, part_point_count = map(int, part[:2])
                    start = point_start + relative_start
                    cut_line_points.extend(poly_points[start:start + part_point_count, :2])
                if len(cut_line_points) < 2:
                    logger.warning(
                        "Skipping %s/%s/%s in %s: cut line has fewer than two points.",
                        river_name, reach_name, river_station, hdf_path.name,
                    )
                    continue
                cut_line = LineString(cut_line_points)

                station_start, station_count = map(int, station_info[xs_index][:2])
                profile = station_values[station_start:station_start + station_count]
                stations, elevations = HdfXsec._pair_columns(
                    profile, ("Station",), ("Elevation",)
                )
                if len(stations) == 0:
                    continue

                mann_start, mann_count = map(int, mann_info[xs_index][:2])
                xs_mannings = mann_values[mann_start:mann_start + mann_count]
                point_mannings = HdfXsec._mannings_at_stations(stations, xs_mannings)

                left_bank = float(attr["Left Bank"]) if "Left Bank" in xs_attrs.dtype.names else np.nan
                right_bank = float(attr["Right Bank"]) if "Right Bank" in xs_attrs.dtype.names else np.nan
                minimum = float(np.nanmin(stations))
                maximum = float(np.nanmax(stations))
                span = maximum - minimum
                if np.isclose(span, 0.0):
                    fractions = np.full(len(stations), 0.5, dtype=float)
                else:
                    fractions = (stations - minimum) / span
                distances = fractions * float(cut_line.length)
                station_order = np.argsort(
                    np.argsort(stations, kind="stable"), kind="stable"
                )
                tolerance = max(abs(span) * 1e-9, 1e-9)

                for point_order, (station, elevation, fraction, distance, n_value) in enumerate(
                    zip(stations, elevations, fractions, distances, point_mannings)
                ):
                    point = cut_line.interpolate(float(np.clip(fraction, 0.0, 1.0)), normalized=True)
                    at_left = bool(np.isfinite(left_bank) and np.isclose(station, left_bank, rtol=0.0, atol=tolerance))
                    at_right = bool(np.isfinite(right_bank) and np.isclose(station, right_bank, rtol=0.0, atol=tolerance))
                    if np.isfinite(left_bank) and station < left_bank:
                        bank_region = "left_overbank"
                    elif np.isfinite(right_bank) and station > right_bank:
                        bank_region = "right_overbank"
                    elif np.isfinite(left_bank) and np.isfinite(right_bank):
                        bank_region = "channel"
                    else:
                        bank_region = "unknown"

                    rows.append({
                        "river": river_name,
                        "reach": reach_name,
                        "river_station": river_station,
                        "point_order": point_order,
                        "station_order": int(station_order[point_order]),
                        "station": float(station),
                        "relative_distance": float(distance),
                        "x": float(point.x),
                        "y": float(point.y),
                        "z": float(elevation),
                        "mannings_n": float(n_value) if np.isfinite(n_value) else np.nan,
                        "bank_region": bank_region,
                        "is_bank_station": at_left or at_right,
                        "bank_side": "left" if at_left else ("right" if at_right else None),
                        "left_bank_station": left_bank if np.isfinite(left_bank) else np.nan,
                        "right_bank_station": right_bank if np.isfinite(right_bank) else np.nan,
                    })

        if not rows:
            filters = {"river": river, "reach": reach, "rs": rs}
            active = {key: value for key, value in filters.items() if value is not None}
            raise ValueError(f"No cross-section points found in {hdf_path} matching {active}.")

        result = pd.DataFrame(rows)
        result["horizontal_crs"] = str(resolved_crs) if resolved_crs is not None else None
        result["horizontal_units"] = HdfXsec._crs_units(resolved_crs)
        result["vertical_units"] = resolved_vertical_units
        result["vertical_units_source"] = vertical_units_source
        result["vertical_datum"] = resolved_vertical_datum
        result["source_file"] = str(hdf_path.resolve())
        result["extraction_method"] = "geometry_hdf"
        result.attrs["native_elevations"] = True
        result.attrs["source_file"] = str(hdf_path.resolve())
        result.attrs["extraction_method"] = "geometry_hdf"
        return result

    @staticmethod
    @log_call
    def get_cross_sections(hdf_path: str, datetime_to_str: bool = True, ras_object=None) -> gpd.GeoDataFrame:
        """
        Extracts cross-section geometries and attributes from a HEC-RAS geometry HDF file.

        Parameters
        ----------
        hdf_path : str
            Path to the HEC-RAS geometry HDF file
        datetime_to_str : bool, optional
            Convert datetime objects to strings, defaults to True
        ras_object : RasPrj, optional
            RAS project object for additional context, defaults to None

        Returns
        -------
        gpd.GeoDataFrame
            Cross-section data with columns:
            - geometry: LineString - Cross-section polyline geometry
            - station_elevation: ndarray - Station-elevation profile (Nx2 array: [station, elevation])
            - mannings_n: dict - Raw Manning's n data with keys 'Station' and 'Mann n' (lists)
            - n_lob: float - Left overbank Manning's n (computed from bank stations)
            - n_channel: float - Main channel Manning's n (computed from bank stations)
            - n_rob: float - Right overbank Manning's n (computed from bank stations)
            - ineffective_blocks: list - List of dicts with keys: 'Left Sta', 'Right Sta', 'Elevation', 'Permanent'
            - River: str - River name
            - Reach: str - Reach name
            - RS: str - River station identifier
            - Name: str - Cross-section name
            - Description: str - Cross-section description
            - Len Left: float - Left overbank flow path length
            - Len Channel: float - Main channel flow path length
            - Len Right: float - Right overbank flow path length
            - Left Bank: float - Left bank station location
            - Right Bank: float - Right bank station location
            - Friction Mode: str - Friction method used
            - Contr: float - Contraction coefficient
            - Expan: float - Expansion coefficient
            - Left Levee Sta: float - Left levee station (if exists)
            - Left Levee Elev: float - Left levee elevation (if exists)
            - Right Levee Sta: float - Right levee station (if exists)
            - Right Levee Elev: float - Right levee elevation (if exists)
            - HP Count: int - Hydraulic table point count
            - HP Start Elev: float - Hydraulic table starting elevation
            - HP Vert Incr: float - Hydraulic table vertical increment
            - HP LOB Slices: int - Left overbank slices count
            - HP Chan Slices: int - Main channel slices count
            - HP ROB Slices: int - Right overbank slices count
            - Ineff Block Mode: int - Ineffective area block mode
            - Obstr Block Mode: int - Obstruction block mode
            - Default Centerline: int - Default centerline flag
            - Last Edited: str - Last edit timestamp

        Notes
        -----
        The returned GeoDataFrame includes the coordinate system from the HDF file
        when available. All byte strings are converted to regular strings.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf:
                if HdfXsec.CROSS_SECTION_GROUP not in hdf:
                    logger.debug(
                        "No Geometry/Cross Sections group in %s; returning empty GeoDataFrame.",
                        HdfXsec._filename(hdf_path),
                    )
                    return gpd.GeoDataFrame()

                missing_core = [
                    dataset
                    for dataset in HdfXsec.CROSS_SECTION_CORE_GEOMETRY_DATASETS
                    if dataset not in hdf
                ]
                if missing_core:
                    if len(missing_core) == len(
                        HdfXsec.CROSS_SECTION_CORE_GEOMETRY_DATASETS
                    ):
                        logger.debug(
                            "No cross-section geometry datasets found in %s; missing %s; "
                            "returning empty GeoDataFrame.",
                            HdfXsec._filename(hdf_path),
                            ", ".join(missing_core),
                        )
                    else:
                        logger.warning(
                            "Cross-section geometry in %s is missing required dataset(s): "
                            "%s; returning empty GeoDataFrame.",
                            HdfXsec._filename(hdf_path),
                            ", ".join(missing_core),
                        )
                    return gpd.GeoDataFrame()

                group = HdfXsec._cross_section_group(hdf)
                row_count = HdfXsec._get_cross_section_count(hdf)
                if row_count == 0:
                    return gpd.GeoDataFrame()

                geometries = HdfXsec._polyline_geometries(
                    group,
                    "Polyline Info",
                    "Polyline Parts",
                    "Polyline Points",
                    expected_rows=row_count,
                )
                station_info, station_values = HdfXsec._info_values_pair(
                    group,
                    ("Station Elevation Info",),
                    ("Station Elevation Values",),
                    row_count,
                    value_columns=2,
                )
                mann_info, mann_values = HdfXsec._info_values_pair(
                    group,
                    ("Manning's n Info", "Station Manning's n Info"),
                    ("Manning's n Values", "Station Manning's n Values"),
                    row_count,
                    value_columns=2,
                )
                attributes = HdfXsec._attribute_columns(group, row_count)

                modern_ineff = ("Ineffective Info", "Ineffective Blocks")
                legacy_ineff = (
                    "Blocked Ineffective Info",
                    "Blocked Ineffective Values",
                )
                ineff_info = ineff_values = None
                for info_name, value_name in (modern_ineff, legacy_ineff):
                    if info_name in group or value_name in group:
                        ineff_info, ineff_values = HdfXsec._info_values_pair(
                            group,
                            (info_name,),
                            (value_name,),
                            row_count,
                            value_columns=0,
                        )
                        break

                station_elevations = []
                mannings_n = []
                ineffective_blocks = []
                n_lob_list = []
                n_channel_list = []
                n_rob_list = []

                for i in range(row_count):
                    station_start, station_count = (
                        int(value) for value in station_info[i, :2]
                    )
                    station_elevations.append(
                        station_values[station_start : station_start + station_count]
                    )

                    mann_start, mann_count = (
                        int(value) for value in mann_info[i, :2]
                    )
                    mann_section = mann_values[mann_start : mann_start + mann_count]
                    mannings_n.append(
                        {
                            "Station": mann_section[:, 0].tolist(),
                            "Mann n": mann_section[:, 1].tolist(),
                        }
                    )

                    left_bank = float(attributes["Left Bank"][i])
                    right_bank = float(attributes["Right Bank"][i])
                    if mann_count == 0:
                        n_lob_val = n_channel_val = n_rob_val = np.nan
                    elif mann_count == 3:
                        n_lob_val = float(mann_section[0, 1])
                        n_channel_val = float(mann_section[1, 1])
                        n_rob_val = float(mann_section[2, 1])
                    elif mann_count == 2:
                        sta1, n1 = (float(value) for value in mann_section[0, :2])
                        sta2, n2 = (float(value) for value in mann_section[1, :2])
                        if sta1 < left_bank and sta2 >= left_bank:
                            n_lob_val, n_channel_val, n_rob_val = n1, n2, n2
                        else:
                            n_lob_val, n_channel_val, n_rob_val = n1, n1, n2
                    elif mann_count >= 4:
                        n_lob_val = n_channel_val = n_rob_val = None
                        for station, n_value in mann_section[:, :2]:
                            station, n_value = float(station), float(n_value)
                            if station < left_bank:
                                n_lob_val = n_value
                            elif station < right_bank and n_channel_val is None:
                                n_channel_val = n_value
                            elif station >= right_bank and n_rob_val is None:
                                n_rob_val = n_value
                        if n_lob_val is None:
                            n_lob_val = float(mann_section[0, 1])
                        if n_channel_val is None:
                            n_channel_val = n_lob_val
                        if n_rob_val is None:
                            n_rob_val = n_channel_val
                    else:
                        n_lob_val = n_channel_val = n_rob_val = float(
                            mann_section[0, 1]
                        )
                    n_lob_list.append(n_lob_val)
                    n_channel_list.append(n_channel_val)
                    n_rob_list.append(n_rob_val)

                    blocks_list = []
                    if ineff_info is not None and ineff_values is not None:
                        ineff_start, ineff_count = (
                            int(value) for value in ineff_info[i, :2]
                        )
                        blocks = ineff_values[ineff_start : ineff_start + ineff_count]
                        for block in blocks:
                            if blocks.dtype.names:
                                required = {"Left Sta", "Right Sta", "Elevation"}
                                if not required.issubset(blocks.dtype.names):
                                    raise ValueError(
                                        "Ineffective Blocks dataset is missing required fields"
                                    )
                                permanent = (
                                    bool(block["Permanent"])
                                    if "Permanent" in blocks.dtype.names
                                    else False
                                )
                                left_sta = block["Left Sta"]
                                right_sta = block["Right Sta"]
                                elevation = block["Elevation"]
                            else:
                                if blocks.ndim != 2 or blocks.shape[1] < 3:
                                    raise ValueError(
                                        "Blocked Ineffective Values must have at least three columns"
                                    )
                                left_sta, right_sta, elevation = block[:3]
                                permanent = False
                            blocks_list.append(
                                {
                                    "Left Sta": float(left_sta),
                                    "Right Sta": float(right_sta),
                                    "Elevation": float(elevation),
                                    "Permanent": permanent,
                                }
                            )
                    ineffective_blocks.append(blocks_list)

                data = {
                    'geometry': geometries,
                    'station_elevation': station_elevations,
                    'mannings_n': mannings_n,
                    'n_lob': n_lob_list,
                    'n_channel': n_channel_list,
                    'n_rob': n_rob_list,
                    'ineffective_blocks': ineffective_blocks,
                }
                
                field_mappings = {
                    'River': ('River', ''),
                    'Reach': ('Reach', ''),
                    'RS': ('RS', ''),
                    'Name': ('Name', ''),
                    'Description': ('Description', ''),
                    'Len Left': ('Len Left', 0.0),
                    'Len Channel': ('Len Channel', 0.0),
                    'Len Right': ('Len Right', 0.0),
                    'Left Bank': ('Left Bank', 0.0),
                    'Right Bank': ('Right Bank', 0.0),
                    'Friction Mode': ('Friction Mode', ''),
                    'Contr': ('Contr', 0.0),
                    'Expan': ('Expan', 0.0),
                    'Left Levee Sta': ('Left Levee Sta', None),
                    'Left Levee Elev': ('Left Levee Elev', None),
                    'Right Levee Sta': ('Right Levee Sta', None),
                    'Right Levee Elev': ('Right Levee Elev', None),
                    'HP Count': ('HP Count', 0),
                    'HP Start Elev': ('HP Start Elev', 0.0),
                    'HP Vert Incr': ('HP Vert Incr', 0.0),
                    'HP LOB Slices': ('HP LOB Slices', 0),
                    'HP Chan Slices': ('HP Chan Slices', 0),
                    'HP ROB Slices': ('HP ROB Slices', 0),
                    'Ineff Block Mode': ('Ineff Block Mode', 0),
                    'Obstr Block Mode': ('Obstr Block Mode', 0),
                    'Default Centerline': ('Default Centerline', 0),
                    'Last Edited': ('Last Edited', '')
                }
                
                for field_name, (attr_name, default_value) in field_mappings.items():
                    if attr_name in attributes:
                        values = np.asarray(attributes[attr_name])
                        if values.dtype.kind in {'S', 'U', 'O'}:
                            data[field_name] = HdfXsec._string_values(values)
                        else:
                            data[field_name] = values
                    else:
                        data[field_name] = [default_value] * len(geometries)
                        logger.debug(f"Field {attr_name} not found in attributes, using default value")

                projection = None
                if "Geometry" in hdf and "Projection" in hdf["Geometry"].attrs:
                    projection = HdfXsec._convert_hdf_value(
                        hdf["Geometry"].attrs["Projection"]
                    )
                if not projection:
                    projection = HdfBase.get_projection(Path(hdf_path))
                result = gpd.GeoDataFrame(data, crs=projection)
                if datetime_to_str:
                    result = HdfUtils.convert_df_datetimes_to_str(result)
                return result
                
        except Exception as e:
            logger.error(f"Error processing cross-section data from {hdf_path}: {str(e)}")
            return gpd.GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_centerlines(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Extracts river centerline geometries and attributes from HDF geometry file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file
        datetime_to_str : bool, optional
            Convert datetime objects to strings, defaults to False

        Returns
        -------
        GeoDataFrame
            River centerline data with columns:
            - geometry: LineString - River centerline geometry
            - River Name: str - Name of the river
            - Reach Name: str - Name of the reach
            - US Type: str - Upstream connection type (e.g., 'Junction', 'External')
            - US Name: str - Upstream connection name
            - DS Type: str - Downstream connection type (e.g., 'Junction', 'External')
            - DS Name: str - Downstream connection name
            - length: float - Centerline length in project coordinate units (computed)

            Note: Additional HDF attributes may be included depending on HEC-RAS version.
            Use datetime_to_str=True to convert any datetime columns to ISO format strings.

        Notes
        -----
        Returns an empty GeoDataFrame if no centerlines are found.
        All string attributes are stripped of whitespace.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Centerlines" not in hdf_file:
                    logger.debug(
                        "No Geometry/River Centerlines group in %s; returning empty GeoDataFrame.",
                        HdfXsec._filename(hdf_path),
                    )
                    return GeoDataFrame()

                centerline_data = hdf_file["Geometry/River Centerlines"]
                geoms = HdfXsec._polyline_geometries(
                    centerline_data,
                    "Polyline Info",
                    "Polyline Parts",
                    "Polyline Points",
                )
                row_count = len(geoms)

                if "Attributes" in centerline_data:
                    attrs = HdfXsec._dataset(centerline_data, "Attributes")
                    if len(attrs) != row_count or not attrs.dtype.names:
                        raise ValueError(
                            "River centerline Attributes must be a compound dataset "
                            "with one row per centerline"
                        )
                    centerline_dict = {}
                    for name in attrs.dtype.names:
                        values = attrs[name]
                        centerline_dict[name] = (
                            HdfXsec._string_values(values)
                            if values.dtype.kind in {"S", "U", "O"}
                            else values.tolist()
                        )
                else:
                    legacy_names = (
                        "River Names",
                        "Reach Names",
                        "US Junction",
                        "US SA-2D",
                        "DS Junction",
                        "DS SA-2D",
                    )
                    legacy_values = {}
                    for name in legacy_names:
                        values = HdfXsec._dataset(centerline_data, name)
                        if values.ndim != 1 or len(values) != row_count:
                            raise ValueError(
                                "River centerline row count mismatch "
                                f"(expected {row_count}): {name}={len(values)}"
                            )
                        legacy_values[name] = HdfXsec._string_values(values)

                    centerline_dict = {
                        "River Name": legacy_values["River Names"],
                        "Reach Name": legacy_values["Reach Names"],
                        "US Type": [],
                        "US Name": [],
                        "DS Type": [],
                        "DS Name": [],
                    }
                    for row_index in range(row_count):
                        for prefix in ("US", "DS"):
                            junction = legacy_values[f"{prefix} Junction"][row_index]
                            sa_2d = legacy_values[f"{prefix} SA-2D"][row_index]
                            if junction and sa_2d:
                                raise ValueError(
                                    f"River centerline row {row_index} has both "
                                    f"{prefix} Junction and {prefix} SA-2D connections"
                                )
                            if junction:
                                connection_type, connection_name = "Junction", junction
                            elif sa_2d:
                                connection_type, connection_name = "SA-2D", sa_2d
                            else:
                                connection_type, connection_name = "External", ""
                            centerline_dict[f"{prefix} Type"].append(connection_type)
                            centerline_dict[f"{prefix} Name"].append(connection_name)

                centerline_gdf = GeoDataFrame(
                    centerline_dict,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path)
                )

                # Clean up string columns
                str_columns = ['River Name', 'Reach Name', 'US Type', 
                            'US Name', 'DS Type', 'DS Name']
                for col in str_columns:
                    if col in centerline_gdf.columns:
                        centerline_gdf[col] = centerline_gdf[col].str.strip()

                # Add length calculation in project units
                if not centerline_gdf.empty:
                    centerline_gdf['length'] = centerline_gdf.geometry.length
                    
                    if datetime_to_str:
                        centerline_gdf = HdfUtils.convert_df_datetimes_to_str(
                            centerline_gdf
                        )

                logger.debug(f"Extracted {len(centerline_gdf)} river centerlines")
                return centerline_gdf

        except Exception as e:
            logger.error(f"Error reading river centerlines from {hdf_path}: {str(e)}")
            return GeoDataFrame()



    @staticmethod
    @log_call
    def get_river_stationing(centerlines_gdf: GeoDataFrame) -> GeoDataFrame:
        """
        Calculates stationing along river centerlines with interpolated points.

        Parameters
        ----------
        centerlines_gdf : GeoDataFrame
            River centerline geometries from get_river_centerlines()

        Returns
        -------
        GeoDataFrame
            Original centerlines with additional columns:
            - station_start: float - Starting station value (0.0 or total_length, depends on US/DS connections)
            - station_end: float - Ending station value (total_length or 0.0, depends on US/DS connections)
            - stations: ndarray - Array of 100 evenly-spaced station values along centerline
            - points: list - List of shapely Point geometries at each station location

            All original columns from centerlines_gdf are preserved (geometry, River Name, Reach Name, etc.).

        Notes
        -----
        Station direction (increasing/decreasing) is determined by
        upstream/downstream junction connections. Stations are calculated
        at 100 evenly spaced points along each centerline.
        """
        if centerlines_gdf.empty:
            logger.debug("Empty centerlines GeoDataFrame provided; returning unchanged.")
            return centerlines_gdf

        try:
            # Create copy to avoid modifying original
            result_gdf = centerlines_gdf.copy()
            
            # Initialize new columns
            result_gdf['station_start'] = 0.0
            result_gdf['station_end'] = 0.0
            result_gdf['stations'] = None
            result_gdf['points'] = None
            
            # Process each centerline
            for idx, row in result_gdf.iterrows():
                # Get line geometry
                line = row.geometry
                
                # Calculate length
                total_length = line.length
                
                # Generate points along the line
                distances = np.linspace(0, total_length, num=100)  # Adjust num for desired density
                points = [line.interpolate(distance) for distance in distances]
                
                # Store results
                result_gdf.at[idx, 'station_start'] = 0.0
                result_gdf.at[idx, 'station_end'] = total_length
                result_gdf.at[idx, 'stations'] = distances
                result_gdf.at[idx, 'points'] = points
                
                # Add stationing direction based on upstream/downstream info
                if row['US Type'] == 'Junction' and row['DS Type'] != 'Junction':
                    # Reverse stationing if upstream is junction
                    result_gdf.at[idx, 'station_start'] = total_length
                    result_gdf.at[idx, 'station_end'] = 0.0
                    result_gdf.at[idx, 'stations'] = total_length - distances
            
            return result_gdf

        except Exception as e:
            logger.error(f"Error calculating river stationing: {str(e)}")
            return centerlines_gdf

    @staticmethod
    def _interpolate_station(line, distance):
        """
        Interpolates a point along a line at a given distance.

        Parameters
        ----------
        line : LineString
            Shapely LineString geometry
        distance : float
            Distance along the line to interpolate

        Returns
        -------
        tuple
            (x, y) coordinates of interpolated point
        """
        if distance <= 0:
            return line.coords[0]
        elif distance >= line.length:
            return line.coords[-1]
        return line.interpolate(distance).coords[0]



    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_reaches(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Return the model 1D river reach lines.

        This method extracts river reach data from the HEC-RAS geometry HDF file,
        including attributes and geometry information.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        datetime_to_str : bool, optional
            If True, convert datetime objects to strings. Default is False.

        Returns
        -------
        GeoDataFrame
            River reach data with columns:
            - geometry: LineString - River reach line geometry
            - river_id: int - Unique identifier for each reach (0-indexed)
            - River Name: str - Name of the river
            - Reach Name: str - Name of the reach
            - US Type: str - Upstream connection type
            - US Name: str - Upstream connection name
            - DS Type: str - Downstream connection type
            - DS Name: str - Downstream connection name
            - Last Edited: datetime or str - Last edit timestamp (str if datetime_to_str=True)

            Note: Additional HDF attributes may be included depending on HEC-RAS version.
        """
        try:
            river_gdf = HdfXsec.get_river_centerlines(
                hdf_path,
                datetime_to_str=datetime_to_str,
            )
            if river_gdf.empty:
                return river_gdf
            river_gdf = river_gdf.copy()
            river_gdf.insert(0, "river_id", range(len(river_gdf)))
            return river_gdf
        except Exception as e:
            logger.error(f"Error reading river reaches from {hdf_path}: {str(e)}")
            return GeoDataFrame()


    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_edge_lines(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Return the model river edge lines.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        datetime_to_str : bool, optional
            If True, convert datetime objects to strings. Default is False.

        Returns
        -------
        GeoDataFrame
            River edge line data with columns:
            - geometry: LineString - River edge line geometry
            - edge_id: int - Unique identifier for each edge line (0-indexed)
            - bank_side: str - Bank side indicator ('Left' or 'Right')
            - length: float - Length of edge line in project coordinate units (computed)
            - Last Edited: datetime or str - Last edit timestamp (str if datetime_to_str=True, if available)

            Note: Each row represents one river bank (left or right). Additional HDF attributes
            may be included depending on HEC-RAS version.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Edge Lines" not in hdf_file:
                    logger.debug(
                        "No Geometry/River Edge Lines group in %s; returning empty GeoDataFrame.",
                        HdfXsec._filename(hdf_path),
                    )
                    return GeoDataFrame()

                edge_data = hdf_file["Geometry/River Edge Lines"]
                geoms = HdfBase.get_polylines_from_parts(
                    hdf_path,
                    "Geometry/River Edge Lines",
                    info_name="Polyline Info",
                    parts_name="Polyline Parts",
                    points_name="Polyline Points"
                )

                # Genuine HEC-RAS edge lines carry no "Attributes" dataset, so the
                # geometry count is the source of truth for edge_id/bank_side (bank
                # side alternates Left/Right per reach: RASEdgeLines' IsLeft = i % 2 == 0).
                if "Attributes" in edge_data:
                    attrs = edge_data["Attributes"][()]

                    # Create dictionary of attributes
                    edge_dict = {"edge_id": list(range(attrs.shape[0]))}
                    edge_dict.update(HdfXsec._structured_array_to_dict(attrs))
                else:
                    edge_dict = {"edge_id": list(range(len(geoms)))}
                edge_dict["bank_side"] = HdfXsec._alternating_bank_sides(len(geoms))

                # Create GeoDataFrame
                edge_gdf = GeoDataFrame(
                    edge_dict,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path)
                )

                # Convert datetime objects to strings if requested
                if datetime_to_str and 'Last Edited' in edge_gdf.columns:
                    edge_gdf["Last Edited"] = edge_gdf["Last Edited"].apply(
                        HdfXsec._datetime_value_to_str
                    )

                # Add length calculation in project units
                if not edge_gdf.empty:
                    edge_gdf['length'] = edge_gdf.geometry.length

                return edge_gdf

        except Exception as e:
            logger.error(f"Error reading river edge lines from {hdf_path}: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_bank_lines(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Extract river bank lines from HDF geometry file.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file
        datetime_to_str : bool, optional
            Convert datetime objects to strings, by default False

        Returns
        -------
        GeoDataFrame
            River bank line data with columns:
            - geometry: LineString - River bank line geometry
            - bank_id: int - Unique identifier for each bank line (0-indexed)
            - bank_side: str - Bank side indicator ('Left' or 'Right')
            - length: float - Length of the bank line in project coordinate units (computed)

            Note: Bank lines are assumed to be in pairs (left/right). If odd number of geometries
            exist, the bank_side pattern may not align perfectly.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Bank Lines" not in hdf_file:
                    logger.debug(
                        "No Geometry/River Bank Lines group in %s; returning empty GeoDataFrame.",
                        HdfXsec._filename(hdf_path),
                    )
                    return GeoDataFrame()

                bank_data = hdf_file["Geometry/River Bank Lines"]
                dataset_trios = (
                    ("Polyline Info", "Polyline Parts", "Polyline Points"),
                    ("Bank Lines Info", "Bank Lines Parts", "Bank Lines Points"),
                )
                selected = None
                for trio in dataset_trios:
                    present = [name in bank_data for name in trio]
                    if any(present):
                        if not all(present):
                            missing = [
                                name for name, exists in zip(trio, present) if not exists
                            ]
                            raise ValueError(
                                "Incomplete river bank-line polyline datasets; missing: "
                                + ", ".join(missing)
                            )
                        selected = trio
                        break
                if selected is None:
                    raise ValueError(
                        "River bank-line group contains no polyline datasets"
                    )

                geoms = HdfXsec._polyline_geometries(bank_data, *selected)

                bank_dict = {
                    "bank_id": list(range(len(geoms))),
                    "bank_side": HdfXsec._alternating_bank_sides(len(geoms)),
                }

                # Create GeoDataFrame
                bank_gdf = GeoDataFrame(
                    bank_dict,
                    geometry=geoms,
                    crs=HdfBase.get_projection(hdf_path)
                )

                # Add length calculation in project units
                if not bank_gdf.empty:
                    bank_gdf['length'] = bank_gdf.geometry.length

                return bank_gdf

        except Exception as e:
            logger.error(f"Error reading river bank lines from {hdf_path}: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_river_flow_paths(hdf_path: Path, datetime_to_str: bool = False) -> GeoDataFrame:
        """
        Return the model river flow paths (``Geometry/River Flow Paths``).

        RASMapper's *Create Flow Paths from XS Layout* artifact: the flow-path
        polylines (left overbank, channel, right overbank) that drive 1D reach
        lengths. Pure h5py read; the group must already exist. Generate it with
        ``RasGeometryCompute.generate_flow_paths()`` when absent.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        datetime_to_str : bool, optional
            Accepted for signature parity with the other river-layer readers;
            flow paths carry no timestamp attribute, so this is a no-op.

        Returns
        -------
        GeoDataFrame
            Columns ``flow_path_id`` (int), ``geometry`` (LineString), and
            ``length`` (project units). Empty GeoDataFrame when no flow paths
            are stored.
        """
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if "Geometry/River Flow Paths" not in hdf_file:
                    logger.warning("No river flow paths found in geometry file")
                    return GeoDataFrame()

            geoms = HdfBase.get_polylines_from_parts(
                hdf_path,
                "Geometry/River Flow Paths",
                info_name="Flow Path Lines Info",
                parts_name="Flow Path Lines Parts",
                points_name="Flow Path Lines Points",
            )
            if not geoms:
                return GeoDataFrame()

            flow_gdf = GeoDataFrame(
                {"flow_path_id": list(range(len(geoms)))},
                geometry=geoms,
                crs=HdfBase.get_projection(hdf_path),
            )
            flow_gdf['length'] = flow_gdf.geometry.length
            return flow_gdf

        except Exception as e:
            logger.error(f"Error reading river flow paths: {str(e)}")
            return GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_xs_interpolation_surface(hdf_path: Path) -> GeoDataFrame:
        """
        Return the cross-section interpolation surface.

        RASMapper's *Compute XS Interpolation Surface* artifact
        (``Geometry/Cross Section Interpolation Surfaces``): the triangulated
        surface HEC-RAS builds between each pair of adjacent cross sections. The
        stored TIN is returned as one dissolved polygon per XS-to-XS segment,
        tagged with the upstream/downstream cross-section ids and the stored
        area. Pure h5py read; the group must already exist. Generate it with
        ``RasGeometryCompute.generate_interpolation_surface()`` when absent.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.

        Returns
        -------
        GeoDataFrame
            One row per interpolation segment with columns ``surface_id`` (int),
            ``us_xs_id`` / ``ds_xs_id`` (int, when ``XSIDs`` present), ``area``
            (float, when ``Areas`` present), and ``geometry`` ((Multi)Polygon of
            the segment's TIN triangles). Empty GeoDataFrame when no surface is
            stored.
        """
        base = "Geometry/Cross Section Interpolation Surfaces"
        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                if base not in hdf_file:
                    logger.warning("No XS interpolation surface found in geometry file")
                    return GeoDataFrame()
                grp = hdf_file[base]
                if "TIN Info" not in grp or "TIN Points" not in grp or "TIN Triangles" not in grp:
                    logger.warning("XS interpolation surface group missing TIN datasets")
                    return GeoDataFrame()
                tin_info = grp["TIN Info"][()]
                tin_points = grp["TIN Points"][()]
                tin_tris = grp["TIN Triangles"][()]
                xsids = grp["XSIDs"][()] if "XSIDs" in grp else None
                areas = grp["Areas"][()] if "Areas" in grp else None

            from shapely.ops import unary_union

            n_pts = len(tin_points)
            n_tris = len(tin_tris)
            rows = []
            for i, (pnt_start, pnt_cnt, tri_start, tri_cnt) in enumerate(tin_info):
                try:
                    # Bounds-check the segment slices before use; a single corrupt
                    # segment must not drop the whole surface.
                    if (pnt_start < 0 or tri_start < 0
                            or pnt_start + pnt_cnt > n_pts
                            or tri_start + tri_cnt > n_tris):
                        logger.warning(
                            f"Interpolation surface segment {i}: slice out of bounds; skipping")
                        continue
                    # Triangle vertex indices are LOCAL to this segment's point slice.
                    seg_pts = tin_points[pnt_start:pnt_start + pnt_cnt][:, :2]
                    seg_tris = tin_tris[tri_start:tri_start + tri_cnt]
                    tri_polys = []
                    for a, b, c in seg_tris:
                        if not (0 <= a < pnt_cnt and 0 <= b < pnt_cnt and 0 <= c < pnt_cnt):
                            continue
                        poly = Polygon([seg_pts[a], seg_pts[b], seg_pts[c]])
                        if poly.is_valid and poly.area > 0:
                            tri_polys.append(poly)
                    if not tri_polys:
                        continue
                    geom = unary_union(tri_polys)
                    if geom is None or geom.is_empty:
                        continue
                    row = {"surface_id": i, "geometry": geom}
                    if xsids is not None and i < len(xsids):
                        row["us_xs_id"] = int(xsids[i, 0])
                        row["ds_xs_id"] = int(xsids[i, 1])
                    if areas is not None and i < len(areas):
                        row["area"] = float(areas[i])
                    rows.append(row)
                except Exception as seg_exc:
                    logger.warning(
                        f"Interpolation surface segment {i} unreadable; skipping: {seg_exc}")
                    continue

            if not rows:
                return GeoDataFrame()
            return GeoDataFrame(rows, geometry="geometry", crs=HdfBase.get_projection(hdf_path))

        except Exception as e:
            logger.error(f"Error reading XS interpolation surface: {str(e)}")
            return GeoDataFrame()

    # ------------------------------------------------------------------
    # Edge-line generation and 1D footprint polygonization
    # ------------------------------------------------------------------

    @staticmethod
    def _as_single_linestring(geometry):
        """Return a simple 2D LineString from single- or multi-part line geometry."""
        from shapely.ops import linemerge

        if geometry is None or getattr(geometry, "is_empty", True):
            return None
        if isinstance(geometry, LineString):
            return geometry if len(geometry.coords) >= 2 else None
        if isinstance(geometry, MultiLineString):
            merged = linemerge(geometry)
            if isinstance(merged, LineString):
                return merged if len(merged.coords) >= 2 else None
            if isinstance(merged, MultiLineString) and len(merged.geoms) > 0:
                longest = max(merged.geoms, key=lambda g: g.length)
                return longest if len(longest.coords) >= 2 else None
        if hasattr(geometry, "geoms"):
            parts = [
                p for p in geometry.geoms
                if isinstance(p, LineString) and len(p.coords) >= 2
            ]
            if parts:
                return max(parts, key=lambda g: g.length)
        return None

    @staticmethod
    def _cutline_interior(start_pt, end_pt, cut_lines, tolerance):
        """Interior vertices of the cut line spanning start_pt -> end_pt.

        Searches ``cut_lines`` for a cut line whose two end points match
        ``start_pt`` and ``end_pt`` (in either order) within ``tolerance``, and
        returns that cut line's interior vertices oriented start -> end. Returns
        None when no cut line matches, in which case the caller falls back to a
        straight closing chord.
        """
        from math import hypot

        def close(a, b):
            return hypot(a[0] - b[0], a[1] - b[1]) <= tolerance

        for line in cut_lines:
            cut = HdfXsec._as_single_linestring(line)
            if cut is None:
                continue
            coords = [tuple(c[:2]) for c in cut.coords]
            if len(coords) < 3:
                # Two-point cut line: the straight chord already IS the cut line.
                continue
            first, last = coords[0], coords[-1]
            if close(first, start_pt) and close(last, end_pt):
                return coords[1:-1]
            if close(last, start_pt) and close(first, end_pt):
                return list(reversed(coords[1:-1]))
        return None

    @staticmethod
    def _polygon_from_edge_pair(left_line, right_line, cut_lines=None,
                                snap_tolerance=None):
        """Close a left/right edge-line pair into a polygon.

        The ring runs along the left edge, across the downstream cross section,
        back up the reversed right edge, and across the upstream cross section.
        When ``cut_lines`` (the end cross-section cut lines for the reach) are
        supplied, each end cap follows the real cut-line geometry, including its
        interior vertices. Without them - or when an edge-line end point does not
        land on a cut-line limit (possible for HEC-RAS stored edge lines) - the
        end cap falls back to a straight chord between the edge-line end points.
        """
        left = HdfXsec._as_single_linestring(left_line)
        right = HdfXsec._as_single_linestring(right_line)
        if left is None or right is None:
            return None

        left_coords = [tuple(c[:2]) for c in left.coords]
        right_coords = [tuple(c[:2]) for c in right.coords]
        if len(left_coords) + len(right_coords) < 4:
            return None

        cut_lines = list(cut_lines) if cut_lines else []
        if cut_lines and snap_tolerance is None:
            lengths = [
                cut.length for cut in
                (HdfXsec._as_single_linestring(c) for c in cut_lines)
                if cut is not None and cut.length > 0
            ]
            # 1% of a typical cut-line width: tight enough to reject a mismatched
            # cut line, loose enough for stored edge lines with rounded coords.
            snap_tolerance = 0.01 * (sum(lengths) / len(lengths)) if lengths else 0.0

        # Downstream cap: left edge end -> right edge end.
        far_cap = HdfXsec._cutline_interior(
            left_coords[-1], right_coords[-1], cut_lines, snap_tolerance
        ) if cut_lines else None
        # Upstream cap: right edge start -> left edge start (closes the ring).
        near_cap = HdfXsec._cutline_interior(
            right_coords[0], left_coords[0], cut_lines, snap_tolerance
        ) if cut_lines else None

        coords = (
            left_coords
            + (far_cap or [])
            + list(reversed(right_coords))
            + (near_cap or [])
        )
        if len(coords) < 4:
            return None
        polygon = Polygon(coords)
        if not polygon.is_valid:
            # A bent cut line spliced into the ring can self-intersect; repair.
            polygon = polygon.buffer(0)
        if polygon is None or polygon.is_empty:
            return None
        return polygon

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def generate_river_edge_lines(hdf_path: Path, ras_object=None) -> GeoDataFrame:
        """
        Generate river edge lines from cross-section cut-line end points.

        Pure-Python equivalent of RASMapper's "Create Edge Lines at XS Limits".
        For each (River, Reach), the left end points of consecutive cross-section
        cut lines are connected into a left edge line and the right end points
        into a right edge line. HEC-RAS stores cut lines left(start) -> right(end)
        looking downstream, so ``coords[0]`` is the left limit and ``coords[-1]``
        is the right limit of each cross section.

        Use this when a geometry has no stored ``Geometry/River Edge Lines``
        (e.g. the XS interpolation surface has not been computed) or to derive a
        1D footprint boundary directly from cross sections. This is a simplified
        XS-endpoint construction; for HEC-RAS's own bank-line-anchored
        offset-curve edge lines (written to the geometry HDF with the group-level
        ``Source Data Hash``), use ``RasGeometryCompute.generate_edge_lines()``.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        ras_object : RasPrj, optional
            RAS project object for path resolution context.

        Returns
        -------
        GeoDataFrame
            Generated edge lines with columns matching ``get_river_edge_lines``:
            - edge_id : int
            - River : str
            - Reach : str
            - bank_side : str ('Left' or 'Right')
            - geometry : LineString
            - length : float (project units)
            Empty GeoDataFrame when no cross sections are available.
        """
        xs_gdf = HdfXsec.get_cross_sections(hdf_path, ras_object=ras_object)
        if xs_gdf is None or xs_gdf.empty:
            logger.warning("No cross sections found; cannot generate river edge lines")
            return GeoDataFrame()

        if not {"River", "Reach"}.issubset(xs_gdf.columns):
            logger.warning("Cross sections missing River/Reach columns; cannot group edge lines")
            return GeoDataFrame()

        rows = []
        edge_id = 0
        # Preserve reach order (HDF file order) while grouping.
        for (river, reach), group in xs_gdf.groupby(["River", "Reach"], sort=False):
            left_pts: List = []
            right_pts: List = []
            for geom in group.geometry:
                line = HdfXsec._as_single_linestring(geom)
                if line is None:
                    continue
                coords = list(line.coords)
                left_pts.append(tuple(coords[0][:2]))
                right_pts.append(tuple(coords[-1][:2]))

            for side, pts in (("Left", left_pts), ("Right", right_pts)):
                # Drop consecutive duplicate points so LineString stays valid.
                unique_pts = []
                for c in pts:
                    if not unique_pts or c != unique_pts[-1]:
                        unique_pts.append(c)
                if len(unique_pts) >= 2:
                    edge = LineString(unique_pts)
                    rows.append({
                        "edge_id": edge_id,
                        "River": river,
                        "Reach": reach,
                        "bank_side": side,
                        "geometry": edge,
                        "length": edge.length,
                    })
                    edge_id += 1

        crs = xs_gdf.crs if xs_gdf.crs is not None else HdfBase.get_projection(hdf_path)
        if not rows:
            logger.warning("Could not generate any river edge lines from cross sections")
            return GeoDataFrame()
        return GeoDataFrame(rows, geometry="geometry", crs=crs)

    @staticmethod
    def _reach_end_cutlines(hdf_path: Path, ras_object=None):
        """Map (River, Reach) -> [first cut line, last cut line] for the reach.

        These are the cross sections that close the upstream and downstream ends
        of the reach footprint ring.
        """
        xs_gdf = HdfXsec.get_cross_sections(hdf_path, ras_object=ras_object)
        if xs_gdf is None or xs_gdf.empty:
            return {}
        if not {"River", "Reach"}.issubset(xs_gdf.columns):
            return {}

        end_cutlines = {}
        for key, group in xs_gdf.groupby(["River", "Reach"], sort=False):
            geoms = [g for g in group.geometry if g is not None]
            if not geoms:
                continue
            end_cutlines[key] = [geoms[0], geoms[-1]]
        return end_cutlines

    @staticmethod
    def _reach_edge_pairs(hdf_path: Path, edge_source: str, ras_object=None):
        """Return (River, Reach, left_line, right_line, source, cut_lines) tuples.

        Labels (River/Reach) always come from the generated (XS-endpoint) edge
        lines, which are reliably grouped by reach. When stored edge lines are
        present and requested, their geometry replaces the generated geometry by
        reach order, giving HEC-RAS's own edge lines with correct reach labels.
        ``cut_lines`` carries the reach's end cross-section cut lines so the
        footprint ring can be closed on real cut-line geometry.
        """
        generated = HdfXsec.generate_river_edge_lines(hdf_path, ras_object=ras_object)
        if generated.empty:
            return []
        end_cutlines = HdfXsec._reach_end_cutlines(hdf_path, ras_object=ras_object)

        # Build ordered (river, reach) -> {Left, Right} from generated edge lines.
        gen_pairs = []
        seen = {}
        for _, row in generated.iterrows():
            key = (row["River"], row["Reach"])
            if key not in seen:
                seen[key] = {"River": row["River"], "Reach": row["Reach"],
                             "Left": None, "Right": None}
                gen_pairs.append(seen[key])
            seen[key][row["bank_side"]] = row.geometry

        use_stored = edge_source in ("stored", "auto")
        stored_lines = None
        if use_stored:
            try:
                stored = HdfXsec.get_river_edge_lines(hdf_path)
            except Exception as e:
                logger.debug(f"Could not read stored river edge lines: {e}")
                stored = GeoDataFrame()
            if stored is not None and not stored.empty and len(stored) % 2 == 0:
                # Stored edge lines come as alternating Left/Right per reach.
                stored_lines = list(stored.geometry)

        if edge_source == "stored" and stored_lines is None:
            logger.warning("No usable stored river edge lines; returning empty pairs")
            return []

        pairs = []
        for idx, gp in enumerate(gen_pairs):
            source = "generated_edge_lines"
            left = gp["Left"]
            right = gp["Right"]
            if stored_lines is not None and (2 * idx + 1) < len(stored_lines) \
                    and len(stored_lines) == 2 * len(gen_pairs):
                left = stored_lines[2 * idx]
                right = stored_lines[2 * idx + 1]
                source = "stored_edge_lines"
            if left is None or right is None:
                continue
            cut_lines = end_cutlines.get((gp["River"], gp["Reach"]), [])
            pairs.append((gp["River"], gp["Reach"], left, right, source, cut_lines))
        return pairs

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_1d_footprint(
        hdf_path: Path,
        edge_source: str = "auto",
        dissolve: bool = False,
        close_with_end_xs: bool = True,
        ras_object=None,
    ) -> GeoDataFrame:
        """
        Build the 1D model footprint polygon(s) from river edge lines.

        For each (River, Reach) the left and right edge lines are closed into a
        polygon ring: left edge, downstream cross section, reversed right edge,
        upstream cross section. The end caps follow the real cut-line geometry of
        the end cross sections, including their interior vertices, so a bent cut
        line is reproduced instead of chorded. This is the true 1D study
        footprint, not a bounding box.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        edge_source : {'auto', 'stored', 'generate'}, default 'auto'
            - 'stored'   : use ``Geometry/River Edge Lines`` only.
            - 'generate' : always generate edge lines from XS end points.
            - 'auto'     : use stored edge lines when present, otherwise generate.
        dissolve : bool, default False
            If True, dissolve the per-reach polygons into a single (multi)polygon
            row. If False, return one polygon row per (River, Reach).
        close_with_end_xs : bool, default True
            Close each ring on the end cross-section cut-line geometry. Set False
            for the legacy behavior, a straight chord between the edge-line end
            points. When an edge-line end point does not land on a cut-line limit
            (possible for stored edge lines), that end cap falls back to the
            straight chord regardless of this setting.
        ras_object : RasPrj, optional
            RAS project object for path resolution context.

        Returns
        -------
        GeoDataFrame
            Columns River, Reach, source, geometry (Polygon). When
            ``dissolve=True``, a single row with a (Multi)Polygon and
            ``source='1d_footprint'``. Empty GeoDataFrame when no 1D geometry is
            available.
        """
        if edge_source not in ("auto", "stored", "generate"):
            raise ValueError(
                f"edge_source must be 'auto', 'stored', or 'generate', got '{edge_source}'"
            )

        crs = HdfBase.get_projection(hdf_path)
        pairs = HdfXsec._reach_edge_pairs(hdf_path, edge_source, ras_object=ras_object)
        if not pairs:
            logger.warning("No 1D edge-line pairs available; returning empty footprint")
            return GeoDataFrame()

        rows = []
        for river, reach, left, right, source, cut_lines in pairs:
            polygon = HdfXsec._polygon_from_edge_pair(
                left, right,
                cut_lines=cut_lines if close_with_end_xs else None,
            )
            if polygon is None:
                logger.debug(f"Could not polygonize reach {river}/{reach}")
                continue
            rows.append({
                "River": river,
                "Reach": reach,
                "source": source,
                "geometry": polygon,
            })

        if not rows:
            logger.warning("Could not build any 1D footprint polygons")
            return GeoDataFrame()

        footprint_gdf = GeoDataFrame(rows, geometry="geometry", crs=crs)

        if dissolve:
            from shapely.ops import unary_union

            combined = unary_union(footprint_gdf.geometry.tolist())
            return GeoDataFrame(
                {"source": ["1d_footprint"]},
                geometry=[combined],
                crs=crs,
            )

        return footprint_gdf

