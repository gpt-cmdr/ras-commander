"""
RasTerrain - HEC-RAS Terrain Creation and Manipulation

This module provides static methods for creating HEC-RAS terrain files from
input rasters using the RasProcess.exe CreateTerrain command and GDAL tools
bundled with HEC-RAS.

Summary:
    Provides terrain creation capabilities without requiring external GDAL
    installations - uses the GDAL tools bundled with HEC-RAS for maximum
    compatibility with HEC-RAS terrain formats.

Key Functions:
    create_terrain_hdf():
        Creates HEC-RAS terrain HDF from input rasters using RasProcess.exe.
        This is the primary terrain creation method, verified working with
        HEC-RAS 6.6.

    vrt_to_tiff():
        Converts VRT (Virtual Raster) mosaics to single optimized TIFF files
        using HEC-RAS bundled GDAL tools.

    _get_hecras_path():
        Locates HEC-RAS installation directory for a given version.

    _get_hecras_gdal_path():
        Locates GDAL tools within HEC-RAS installation.

    _generate_prj_from_raster():
        Generates ESRI PRJ file from raster's coordinate reference system.

Platform:
    Windows only (HEC-RAS is a Windows application)

Requirements:
    - HEC-RAS 6.3+ installed
    - Windows OS

Example:
    from ras_commander.terrain import RasTerrain
    from pathlib import Path

    # Create terrain HDF
    terrain = RasTerrain.create_terrain_hdf(
        input_rasters=[Path("terrain.tif")],
        output_hdf=Path("Terrain/MyTerrain.hdf"),
        projection_prj=Path("Terrain/Projection.prj"),
        units="Feet",
        hecras_version="7.0"
    )

See Also:
    - feature_dev_notes/HEC-RAS_Terrain_CLI/CLAUDE.md for design documentation
    - feature_dev_notes/HEC-RAS_Terrain_CLI/test_rasprocess_createterrain.py
"""

import logging
import math
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Import decorator from parent package
from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


class RasTerrain:
    """
    Static class for HEC-RAS terrain creation and manipulation.

    All methods are static and designed to be called directly without
    instantiation, following the ras-commander coding pattern.

    Primary Methods:
        compute_bank_lines(): Generate bank lines from XS bank stations
        compute_xs_interpolation_surface(): Build Delaunay TIN from XS data
        create_terrain_hdf(): Create HEC-RAS terrain HDF from input rasters
        vrt_to_tiff(): Convert VRT mosaic to single optimized TIFF

    Helper Methods:
        _get_hecras_path(): Find HEC-RAS installation directory
        _get_hecras_gdal_path(): Find GDAL tools in HEC-RAS installation
        _generate_prj_from_raster(): Create ESRI PRJ file from raster CRS

    Usage:
        from ras_commander.terrain import RasTerrain
        from pathlib import Path

        # Create terrain from TIFF
        RasTerrain.create_terrain_hdf(
            input_rasters=[Path("dem.tif")],
            output_hdf=Path("Terrain/Terrain.hdf"),
            projection_prj=Path("Terrain/Projection.prj")
        )
    """

    # Standard HEC-RAS installation paths
    _HECRAS_BASE_PATHS = [
        Path("C:/Program Files (x86)/HEC/HEC-RAS"),
        Path("C:/Program Files/HEC/HEC-RAS"),
    ]

    @staticmethod
    def _empty_bank_lines_gdf(crs=None):
        """Return an empty bank-lines GeoDataFrame with the public schema."""
        try:
            import geopandas as gpd
        except ImportError:
            raise ImportError(
                "geopandas is required for compute_bank_lines(). "
                "Install with: pip install geopandas"
            )

        columns = [
            "river",
            "reach",
            "bank_side",
            "xs_count",
            "rs_values",
            "geometry",
            "length",
        ]
        gdf = gpd.GeoDataFrame(columns=columns, geometry="geometry")
        if crs is not None:
            gdf = gdf.set_crs(crs, allow_override=True)
        return gdf

    @staticmethod
    def _bank_point_from_stationed_xy(xs_coords, bank_station):
        """
        Interpolate a bank point from GeomCrossSection.get_xs_coords() output.
        """
        try:
            import pandas as pd
            from shapely.geometry import Point
        except ImportError:
            raise ImportError(
                "pandas and shapely are required for compute_bank_lines(). "
                "Install with: pip install pandas shapely"
            )

        if bank_station is None or pd.isna(bank_station):
            return None

        group = xs_coords.sort_values("station")
        if group.empty:
            return None

        station = float(bank_station)
        stations = group["station"].astype(float)
        min_station = float(stations.min())
        max_station = float(stations.max())
        tolerance = 1e-8

        if station < min_station - tolerance or station > max_station + tolerance:
            logger.warning(
                "Bank station %.3f is outside station range %.3f-%.3f; skipping",
                station,
                min_station,
                max_station,
            )
            return None

        exact = group[(stations - station).abs() <= tolerance]
        if not exact.empty:
            row = exact.iloc[0]
            return Point(float(row["x"]), float(row["y"]))

        before = group[stations < station]
        after = group[stations > station]
        if before.empty or after.empty:
            return None

        left = before.iloc[-1]
        right = after.iloc[0]
        left_station = float(left["station"])
        right_station = float(right["station"])
        if right_station == left_station:
            return Point(float(left["x"]), float(left["y"]))

        fraction = (station - left_station) / (right_station - left_station)
        x = float(left["x"]) + fraction * (float(right["x"]) - float(left["x"]))
        y = float(left["y"]) + fraction * (float(right["y"]) - float(left["y"]))
        return Point(x, y)

    @staticmethod
    def _bank_point_from_xs_geometry(xs_geometry, station_elevation, bank_station):
        """
        Interpolate a bank point along an HDF cross-section LineString.
        """
        try:
            import numpy as np
            import pandas as pd
        except ImportError:
            raise ImportError(
                "numpy and pandas are required for compute_bank_lines(). "
                "Install with: pip install numpy pandas"
            )

        if bank_station is None or pd.isna(bank_station):
            return None
        if xs_geometry is None or xs_geometry.is_empty:
            return None

        stations = np.asarray(station_elevation, dtype=float)
        if stations.ndim != 2 or stations.shape[1] < 1 or stations.shape[0] == 0:
            return None

        station_values = stations[:, 0]
        min_station = float(np.nanmin(station_values))
        max_station = float(np.nanmax(station_values))
        station = float(bank_station)
        tolerance = 1e-8

        if station < min_station - tolerance or station > max_station + tolerance:
            logger.warning(
                "Bank station %.3f is outside station range %.3f-%.3f; skipping",
                station,
                min_station,
                max_station,
            )
            return None

        if max_station == min_station:
            return xs_geometry.interpolate(0.5, normalized=True)

        fraction = (station - min_station) / (max_station - min_station)
        fraction = min(1.0, max(0.0, fraction))
        return xs_geometry.interpolate(fraction, normalized=True)

    @staticmethod
    def _build_bank_lines_gdf(bank_points, crs=None):
        """Build the public bank-line GeoDataFrame from ordered bank points."""
        try:
            import geopandas as gpd
            from shapely.geometry import LineString
        except ImportError:
            raise ImportError(
                "geopandas and shapely are required for compute_bank_lines(). "
                "Install with: pip install geopandas shapely"
            )

        records = []
        groups = {}
        for point_record in bank_points:
            key = (
                point_record["river"],
                point_record["reach"],
                point_record["bank_side"],
            )
            groups.setdefault(key, []).append(point_record)

        for (river, reach, bank_side), points in groups.items():
            if len(points) < 2:
                logger.warning(
                    "Skipping %s/%s %s bank line with fewer than two points",
                    river,
                    reach,
                    bank_side,
                )
                continue

            line = LineString([
                point_record["geometry"].coords[0]
                for point_record in points
            ])
            records.append({
                "river": river,
                "reach": reach,
                "bank_side": bank_side,
                "xs_count": len(points),
                "rs_values": [point_record["rs"] for point_record in points],
                "geometry": line,
                "length": line.length,
            })

        if not records:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)

    @staticmethod
    def _compute_bank_lines_from_text(geom_path: Path, crs=None, ras_object=None):
        """Compute bank lines from a plain-text HEC-RAS geometry file."""
        from ..geom.GeomCrossSection import GeomCrossSection

        xs_df = GeomCrossSection.get_cross_sections(geom_path)
        if xs_df.empty:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        if "Type" in xs_df.columns:
            xs_df = xs_df[xs_df["Type"] == 1].reset_index(drop=True)
        if xs_df.empty:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        try:
            xs_coords = GeomCrossSection.get_xs_coords(
                geom_path,
                ras_object=ras_object,
            )
        except ValueError:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        if xs_coords.empty:
            return RasTerrain._empty_bank_lines_gdf(crs=crs)

        coord_groups = {
            (river, reach, rs): group
            for (river, reach, rs), group in xs_coords.groupby(["river", "reach", "RS"])
        }

        bank_points = []
        for _, row in xs_df.iterrows():
            river = row["River"]
            reach = row["Reach"]
            rs = str(row["RS"])
            coords = coord_groups.get((river, reach, rs))
            if coords is None or coords.empty:
                logger.warning(
                    "No XS coordinates found for %s/%s/RS %s",
                    river,
                    reach,
                    rs,
                )
                continue

            banks = GeomCrossSection.get_bank_stations(geom_path, river, reach, rs)
            if banks is None:
                logger.warning(
                    "No bank stations found for %s/%s/RS %s",
                    river,
                    reach,
                    rs,
                )
                continue

            left_bank, right_bank = banks
            for bank_side, bank_station in (
                ("Left", left_bank),
                ("Right", right_bank),
            ):
                point = RasTerrain._bank_point_from_stationed_xy(coords, bank_station)
                if point is None:
                    continue
                bank_points.append({
                    "river": river,
                    "reach": reach,
                    "bank_side": bank_side,
                    "rs": rs,
                    "geometry": point,
                })

        return RasTerrain._build_bank_lines_gdf(bank_points, crs=crs)

    @staticmethod
    def _compute_bank_lines_from_hdf(geom_path: Path, crs=None, ras_object=None):
        """Compute bank lines from a compiled HEC-RAS geometry HDF file."""
        from ..hdf.HdfXsec import HdfXsec

        xs_gdf = HdfXsec.get_cross_sections(
            str(geom_path),
            ras_object=ras_object,
        )
        result_crs = crs if crs is not None else getattr(xs_gdf, "crs", None)
        if xs_gdf.empty:
            return RasTerrain._empty_bank_lines_gdf(crs=result_crs)

        bank_points = []
        for _, row in xs_gdf.iterrows():
            river = row.get("River", "")
            reach = row.get("Reach", "")
            rs = str(row.get("RS", ""))
            station_elevation = row.get("station_elevation")

            for bank_side, column in (
                ("Left", "Left Bank"),
                ("Right", "Right Bank"),
            ):
                point = RasTerrain._bank_point_from_xs_geometry(
                    row.geometry,
                    station_elevation,
                    row.get(column),
                )
                if point is None:
                    continue
                bank_points.append({
                    "river": river,
                    "reach": reach,
                    "bank_side": bank_side,
                    "rs": rs,
                    "geometry": point,
                })

        return RasTerrain._build_bank_lines_gdf(bank_points, crs=result_crs)

    @staticmethod
    @log_call
    def compute_bank_lines(
        geom_path: Union[str, Path],
        *,
        crs=None,
        ras_object=None,
    ):
        """
        Generate bank-line geometry from cross-section bank stations.

        This is a non-mutating API equivalent to RASMapper's
        Bank Lines layer -> Compute Bank Lines from XS Bank Stations workflow.
        It reads existing cross-section bank station metadata and returns
        reviewable line geometry without modifying `.rasmap`, text geometry,
        or compiled geometry HDF bank-line layers.

        Parameters:
            geom_path (Union[str, Path]): Path to a plain-text `.g##` geometry
                file or compiled `.g##.hdf` geometry HDF file.
            crs: Optional CRS to assign to the returned GeoDataFrame. If omitted
                and an HDF input exposes a CRS, that CRS is preserved.
            ras_object: Optional RasPrj instance for multi-project workflows.

        Returns:
            geopandas.GeoDataFrame: Bank lines with columns:
                - river (str): River name
                - reach (str): Reach name
                - bank_side (str): "Left" or "Right"
                - xs_count (int): Number of cross sections used
                - rs_values (list[str]): River stations used in line order
                - geometry (LineString): Generated bank line
                - length (float): Line length in project coordinate units

        Raises:
            FileNotFoundError: If geom_path does not exist.
            ImportError: If geopandas, shapely, pandas, or numpy are unavailable.
        """
        geom_path = Path(geom_path)
        if not geom_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_path}")

        if geom_path.suffix.lower() == ".hdf":
            return RasTerrain._compute_bank_lines_from_hdf(
                geom_path,
                crs=crs,
                ras_object=ras_object,
            )

        return RasTerrain._compute_bank_lines_from_text(
            geom_path,
            crs=crs,
            ras_object=ras_object,
        )

    # ------------------------------------------------------------------
    # XS Interpolation Surface helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Convert HEC-RAS numeric values to finite floats when possible."""
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", errors="ignore").strip()
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _as_linestring(geometry):
        """Return a LineString from single or multipart line geometry."""
        from shapely.geometry import LineString, MultiLineString
        from shapely.ops import linemerge

        if geometry is None or geometry.is_empty:
            return None
        if isinstance(geometry, LineString):
            return geometry if len(geometry.coords) >= 2 else None
        if isinstance(geometry, MultiLineString):
            merged = linemerge(geometry)
            if isinstance(merged, LineString):
                return merged if len(merged.coords) >= 2 else None
            if isinstance(merged, MultiLineString) and len(merged.geoms) > 0:
                longest = max(merged.geoms, key=lambda geom: geom.length)
                return longest if len(longest.coords) >= 2 else None
        if hasattr(geometry, "geoms"):
            line_parts = [
                part for part in geometry.geoms
                if isinstance(part, LineString) and len(part.coords) >= 2
            ]
            if line_parts:
                return max(line_parts, key=lambda geom: geom.length)
        return None

    @staticmethod
    def _point_along_xs(line, station: float, min_station: float, max_station: float):
        """Project a cross-section station onto a GIS cut line."""
        if max_station == min_station:
            normalized = 0.5
        else:
            normalized = (station - min_station) / (max_station - min_station)
        normalized = max(0.0, min(1.0, float(normalized)))
        return line.interpolate(normalized, normalized=True)

    @staticmethod
    def _station_elevation_array(station_elevation: Any):
        import numpy as np

        values = np.asarray(station_elevation, dtype=float)
        if values.ndim != 2 or values.shape[1] < 2:
            raise ValueError("Station/elevation data must be an Nx2 array")
        values = values[:, :2]
        finite = np.isfinite(values[:, 0]) & np.isfinite(values[:, 1])
        values = values[finite]
        if len(values) == 0:
            return values
        order = np.argsort(values[:, 0])
        return values[order]

    @staticmethod
    def _add_bank_station_points(
        station_elevation,
        left_bank: Optional[float],
        right_bank: Optional[float],
    ):
        """Ensure left/right bank stations are present for channel clipping."""
        import numpy as np

        values = RasTerrain._station_elevation_array(station_elevation)
        if len(values) == 0:
            return values

        stations = values[:, 0]
        elevations = values[:, 1]
        min_station = float(stations.min())
        max_station = float(stations.max())
        additions = []

        for bank_station in (left_bank, right_bank):
            if bank_station is None:
                continue
            if bank_station < min_station or bank_station > max_station:
                continue
            if np.any(np.isclose(stations, bank_station, atol=0.005)):
                continue
            bank_elevation = float(np.interp(bank_station, stations, elevations))
            additions.append([float(bank_station), bank_elevation])

        if additions:
            values = np.vstack([values, np.asarray(additions, dtype=float)])
            values = values[np.argsort(values[:, 0])]

        return values

    @staticmethod
    def _build_xs_point_records(
        *,
        line,
        station_elevation,
        river: str,
        reach: str,
        rs: str,
        xs_order: int,
        left_bank: Optional[float],
        right_bank: Optional[float],
        channel_only: bool,
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], Dict[str, Any]]:
        """Create interpolation point records and bank/end-point metadata for one XS."""
        values = RasTerrain._add_bank_station_points(
            station_elevation,
            left_bank,
            right_bank,
        )
        if len(values) == 0:
            return [], None, {}

        min_station = float(values[:, 0].min())
        max_station = float(values[:, 0].max())
        valid_banks = (
            left_bank is not None
            and right_bank is not None
            and left_bank < right_bank
        )

        records: List[Dict[str, Any]] = []
        for station, elevation in values:
            station = float(station)
            elevation = float(elevation)
            if channel_only and valid_banks:
                if station < left_bank or station > right_bank:
                    continue
            point = RasTerrain._point_along_xs(
                line,
                station,
                min_station,
                max_station,
            )
            records.append(
                {
                    "River": river,
                    "Reach": reach,
                    "RS": rs,
                    "xs_order": xs_order,
                    "station": station,
                    "elevation": elevation,
                    "geometry": point,
                }
            )

        bank_info = None
        if valid_banks:
            left_point = RasTerrain._point_along_xs(
                line,
                float(left_bank),
                min_station,
                max_station,
            )
            right_point = RasTerrain._point_along_xs(
                line,
                float(right_bank),
                min_station,
                max_station,
            )
            bank_info = {
                "River": river,
                "Reach": reach,
                "RS": rs,
                "xs_order": xs_order,
                "left_bank": float(left_bank),
                "right_bank": float(right_bank),
                "left_point": left_point,
                "right_point": right_point,
            }

        left_extent = RasTerrain._point_along_xs(
            line,
            min_station,
            min_station,
            max_station,
        )
        right_extent = RasTerrain._point_along_xs(
            line,
            max_station,
            min_station,
            max_station,
        )
        edge_info = {
            "River": river,
            "Reach": reach,
            "RS": rs,
            "xs_order": xs_order,
            "left_point": left_extent,
            "right_point": right_extent,
        }

        return records, bank_info, edge_info

    @staticmethod
    def _set_gdf_crs(gdf, crs):
        if gdf is None or getattr(gdf, "empty", True) or crs is None:
            return gdf
        if getattr(gdf, "crs", None) is None:
            return gdf.set_crs(crs, allow_override=True)
        return gdf

    @staticmethod
    def _resolve_xs_surface_crs(geom_path: Path, crs=None):
        if crs is not None:
            return crs

        hdf_path = geom_path if geom_path.suffix.lower() == ".hdf" else Path(f"{geom_path}.hdf")
        if hdf_path.exists():
            try:
                from ..hdf import HdfBase

                resolved = HdfBase.get_projection(hdf_path)
                if resolved:
                    return resolved
            except Exception as e:
                logger.debug(f"Could not resolve CRS from {hdf_path}: {e}")

        return None

    @staticmethod
    def _bank_lines_from_bank_points(bank_infos: List[Dict[str, Any]], crs=None):
        import geopandas as gpd
        from shapely.geometry import LineString

        if not bank_infos:
            return gpd.GeoDataFrame(
                columns=["River", "Reach", "bank_side", "source", "geometry"],
                geometry="geometry",
                crs=crs,
            )

        rows = []
        key_order = []
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for bank_info in bank_infos:
            key = (bank_info["River"], bank_info["Reach"])
            if key not in grouped:
                key_order.append(key)
                grouped[key] = []
            grouped[key].append(bank_info)

        for river, reach in key_order:
            group = sorted(grouped[(river, reach)], key=lambda item: item["xs_order"])
            for side, point_key in (("Left", "left_point"), ("Right", "right_point")):
                points = [item[point_key] for item in group if item.get(point_key) is not None]
                coords = [(pt.x, pt.y) for pt in points]
                unique_coords = []
                for coord in coords:
                    if not unique_coords or coord != unique_coords[-1]:
                        unique_coords.append(coord)
                if len(unique_coords) >= 2:
                    rows.append(
                        {
                            "River": river,
                            "Reach": reach,
                            "bank_side": side,
                            "source": "xs_bank_stations",
                            "geometry": LineString(unique_coords),
                        }
                    )

        return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)

    @staticmethod
    def _polygon_parts(geometry):
        from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

        if geometry is None or geometry.is_empty:
            return []
        if isinstance(geometry, Polygon):
            return [geometry]
        if isinstance(geometry, MultiPolygon):
            return list(geometry.geoms)
        if isinstance(geometry, GeometryCollection):
            parts = []
            for part in geometry.geoms:
                parts.extend(RasTerrain._polygon_parts(part))
            return parts
        return []

    @staticmethod
    def _polygon_from_two_lines(left_line, right_line):
        from shapely.geometry import Polygon

        left = RasTerrain._as_linestring(left_line)
        right = RasTerrain._as_linestring(right_line)
        if left is None or right is None:
            return None
        coords = list(left.coords) + list(reversed(right.coords))
        if len(coords) < 4:
            return None
        polygon = Polygon(coords)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty:
            return None
        return polygon

    @staticmethod
    def _footprint_from_bank_lines(bank_lines_gdf, crs=None):
        import geopandas as gpd

        if bank_lines_gdf is None or bank_lines_gdf.empty:
            return gpd.GeoDataFrame(
                columns=["source", "geometry"],
                geometry="geometry",
                crs=crs,
            )

        polygons = []
        if {"River", "Reach", "bank_side"}.issubset(bank_lines_gdf.columns):
            for (river, reach), group in bank_lines_gdf.groupby(["River", "Reach"], dropna=False):
                left_lines = group[group["bank_side"].astype(str).str.lower() == "left"]
                right_lines = group[group["bank_side"].astype(str).str.lower() == "right"]
                for idx in range(min(len(left_lines), len(right_lines))):
                    polygon = RasTerrain._polygon_from_two_lines(
                        left_lines.iloc[idx].geometry,
                        right_lines.iloc[idx].geometry,
                    )
                    if polygon is not None:
                        polygons.append(
                            {
                                "River": river,
                                "Reach": reach,
                                "source": "bank_lines",
                                "geometry": polygon,
                            }
                        )
        else:
            rows = list(bank_lines_gdf.itertuples())
            for idx in range(0, len(rows) - 1, 2):
                polygon = RasTerrain._polygon_from_two_lines(
                    rows[idx].geometry,
                    rows[idx + 1].geometry,
                )
                if polygon is not None:
                    polygons.append(
                        {
                            "source": "bank_lines",
                            "geometry": polygon,
                        }
                    )

        return gpd.GeoDataFrame(polygons, geometry="geometry", crs=crs)

    @staticmethod
    def _footprint_from_xs_edges(edge_infos: List[Dict[str, Any]], crs=None):
        import geopandas as gpd
        from shapely.geometry import Polygon

        if not edge_infos:
            return gpd.GeoDataFrame(
                columns=["River", "Reach", "source", "geometry"],
                geometry="geometry",
                crs=crs,
            )

        rows = []
        key_order = []
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for edge_info in edge_infos:
            key = (edge_info["River"], edge_info["Reach"])
            if key not in grouped:
                key_order.append(key)
                grouped[key] = []
            grouped[key].append(edge_info)

        for river, reach in key_order:
            group = sorted(grouped[(river, reach)], key=lambda item: item["xs_order"])
            left_points = [item["left_point"] for item in group if item.get("left_point") is not None]
            right_points = [item["right_point"] for item in group if item.get("right_point") is not None]
            if len(left_points) < 2 or len(right_points) < 2:
                continue
            coords = (
                [(pt.x, pt.y) for pt in left_points]
                + [(pt.x, pt.y) for pt in reversed(right_points)]
            )
            if len(coords) < 4:
                continue
            polygon = Polygon(coords)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if not polygon.is_empty:
                rows.append(
                    {
                        "River": river,
                        "Reach": reach,
                        "source": "xs_extents",
                        "geometry": polygon,
                    }
                )

        return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)

    @staticmethod
    def _geo_union(gdf):
        if hasattr(gdf.geometry, "union_all"):
            return gdf.geometry.union_all()
        return gdf.geometry.unary_union

    @staticmethod
    def _unique_interpolation_points(points_gdf):
        import numpy as np

        x = points_gdf.geometry.x.to_numpy(dtype=float)
        y = points_gdf.geometry.y.to_numpy(dtype=float)
        z = points_gdf["elevation"].to_numpy(dtype=float)
        finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
        coords = np.column_stack([x[finite], y[finite]])
        values = z[finite]
        if len(coords) == 0:
            return coords, values

        rounded = np.round(coords, decimals=8)
        unique_xy, inverse = np.unique(rounded, axis=0, return_inverse=True)
        unique_coords = np.zeros((len(unique_xy), 2), dtype=float)
        unique_values = np.zeros(len(unique_xy), dtype=float)
        for idx in range(len(unique_xy)):
            mask = inverse == idx
            unique_coords[idx] = coords[mask].mean(axis=0)
            unique_values[idx] = values[mask].mean()
        return unique_coords, unique_values

    @staticmethod
    def _compute_tin_triangles(points_gdf, footprint_gdf, crs=None):
        import geopandas as gpd
        import numpy as np
        from scipy.spatial import Delaunay, QhullError
        from shapely.geometry import Polygon

        coords, elevations = RasTerrain._unique_interpolation_points(points_gdf)
        if len(coords) < 3:
            raise ValueError("At least three unique interpolation points are required")

        try:
            delaunay = Delaunay(coords)
        except QhullError as e:
            raise ValueError(f"Could not build XS interpolation TIN: {e}") from e

        footprint = RasTerrain._geo_union(footprint_gdf)
        rows = []
        for tri_id, simplex in enumerate(delaunay.simplices):
            tri_coords = coords[simplex]
            triangle = Polygon(tri_coords)
            if triangle.is_empty or triangle.area <= 0:
                continue
            clipped = triangle.intersection(footprint)
            for part_id, part in enumerate(RasTerrain._polygon_parts(clipped)):
                if part.area <= 0:
                    continue
                tri_z = elevations[simplex]
                rows.append(
                    {
                        "tri_id": int(tri_id),
                        "part_id": int(part_id),
                        "z_min": float(np.min(tri_z)),
                        "z_mean": float(np.mean(tri_z)),
                        "z_max": float(np.max(tri_z)),
                        "geometry": part,
                    }
                )

        if not rows:
            raise ValueError("TIN triangles did not overlap the interpolation footprint")

        return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)

    @staticmethod
    def _contains_footprint_xy(footprint, xx, yy, transform=None):
        import numpy as np

        try:
            from rasterio.features import geometry_mask

            return geometry_mask(
                [footprint],
                out_shape=xx.shape,
                transform=transform,
                invert=True,
                all_touched=True,
            )
        except (ImportError, AttributeError):
            pass

        try:
            from shapely import contains_xy

            return contains_xy(footprint, xx, yy)
        except (ImportError, AttributeError):
            pass

        try:
            from shapely.vectorized import contains

            return contains(footprint, xx, yy)
        except (ImportError, AttributeError):
            pass

        from shapely.geometry import Point
        from shapely.prepared import prep

        prepared = prep(footprint)
        flat_mask = np.asarray(
            [
                prepared.covers(Point(float(x), float(y)))
                for x, y in zip(xx.ravel(), yy.ravel())
            ],
            dtype=bool,
        )
        return flat_mask.reshape(xx.shape)

    @staticmethod
    def _build_raster_surface(
        points_gdf,
        footprint_gdf,
        raster_cell_size: float,
        crs=None,
        nodata: float = -9999.0,
        output_raster: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        import numpy as np
        from scipy.interpolate import LinearNDInterpolator

        if raster_cell_size is None or raster_cell_size <= 0:
            raise ValueError("raster_cell_size must be positive when raster output is requested")

        coords, elevations = RasTerrain._unique_interpolation_points(points_gdf)
        if len(coords) < 3:
            raise ValueError("At least three unique interpolation points are required")

        footprint = RasTerrain._geo_union(footprint_gdf)
        minx, miny, maxx, maxy = footprint.bounds
        width = int(math.ceil((maxx - minx) / raster_cell_size))
        height = int(math.ceil((maxy - miny) / raster_cell_size))
        if width <= 0 or height <= 0:
            raise ValueError("Interpolation footprint has invalid raster bounds")

        try:
            from rasterio.transform import from_origin

            transform = from_origin(minx, maxy, raster_cell_size, raster_cell_size)
        except ImportError:
            transform = (minx, raster_cell_size, 0.0, maxy, 0.0, -raster_cell_size)

        x_coords = minx + (np.arange(width) + 0.5) * raster_cell_size
        y_coords = maxy - (np.arange(height) + 0.5) * raster_cell_size
        xx, yy = np.meshgrid(x_coords, y_coords)

        interpolator = LinearNDInterpolator(coords, elevations, fill_value=np.nan)
        interpolated = interpolator(xx, yy)
        inside = RasTerrain._contains_footprint_xy(footprint, xx, yy, transform)
        valid = inside & np.isfinite(interpolated)

        array = np.full((height, width), nodata, dtype=np.float32)
        array[valid] = interpolated[valid].astype(np.float32)

        if output_raster is not None:
            try:
                import rasterio
            except ImportError as e:
                raise ImportError(
                    "rasterio is required to write output_raster. "
                    "Install ras-commander with the notebooks or all extra."
                ) from e

            output_raster = Path(output_raster)
            output_raster.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(
                output_raster,
                "w",
                driver="GTiff",
                height=height,
                width=width,
                count=1,
                dtype="float32",
                crs=crs,
                transform=transform,
                nodata=nodata,
                compress="lzw",
                tiled=True,
            ) as dst:
                dst.write(array, 1)

        return {
            "array": array,
            "transform": transform,
            "crs": crs,
            "nodata": nodata,
            "cell_size": raster_cell_size,
            "bounds": (minx, miny, maxx, maxy),
            "valid_cell_count": int(valid.sum()),
            "path": Path(output_raster) if output_raster is not None else None,
        }

    @staticmethod
    def _serializable_gdf(gdf):
        import numpy as np

        safe = gdf.copy()
        for column in safe.columns:
            if column == safe.geometry.name:
                continue
            if safe[column].dtype == object:
                safe[column] = safe[column].map(
                    lambda value: value.decode("utf-8", errors="ignore")
                    if isinstance(value, (bytes, bytearray))
                    else (
                        str(value)
                        if isinstance(value, (dict, list, tuple, np.ndarray))
                        else value
                    )
                )
        return safe

    @staticmethod
    def _write_xs_surface_gpkg(output_gpkg: Union[str, Path], layers: Dict[str, Any]) -> Path:
        output_gpkg = Path(output_gpkg)
        output_gpkg.parent.mkdir(parents=True, exist_ok=True)
        if output_gpkg.exists():
            output_gpkg.unlink()

        wrote_layer = False
        for layer_name, gdf in layers.items():
            if gdf is None or getattr(gdf, "empty", True):
                continue
            RasTerrain._serializable_gdf(gdf).to_file(
                output_gpkg,
                layer=layer_name,
                driver="GPKG",
            )
            wrote_layer = True

        if not wrote_layer:
            raise ValueError("No non-empty XS interpolation layers were available to write")

        return output_gpkg

    @staticmethod
    def _load_hdf_xs_surface_inputs(geom_path: Path, crs, channel_only: bool, ras_object=None):
        import geopandas as gpd

        from ..hdf import HdfXsec

        xs_gdf = HdfXsec.get_cross_sections(str(geom_path), ras_object=ras_object)
        if xs_gdf is None or xs_gdf.empty:
            raise ValueError(f"No cross sections found in geometry HDF: {geom_path}")
        xs_gdf = RasTerrain._set_gdf_crs(xs_gdf, crs)

        try:
            centerlines_gdf = HdfXsec.get_river_centerlines(geom_path)
            centerlines_gdf = RasTerrain._set_gdf_crs(centerlines_gdf, crs)
        except Exception as e:
            logger.warning(f"Could not read river centerlines from {geom_path}: {e}")
            centerlines_gdf = gpd.GeoDataFrame(geometry=[], crs=crs)

        try:
            bank_lines_gdf = HdfXsec.get_river_bank_lines(geom_path)
            bank_lines_gdf = RasTerrain._set_gdf_crs(bank_lines_gdf, crs)
            if bank_lines_gdf is not None and not bank_lines_gdf.empty:
                bank_lines_gdf = bank_lines_gdf.copy()
                bank_lines_gdf["source"] = "hdf_bank_lines"
        except Exception as e:
            logger.warning(f"Could not read river bank lines from {geom_path}: {e}")
            bank_lines_gdf = gpd.GeoDataFrame(geometry=[], crs=crs)

        point_records: List[Dict[str, Any]] = []
        bank_infos: List[Dict[str, Any]] = []
        edge_infos: List[Dict[str, Any]] = []

        for xs_order, (_, row) in enumerate(xs_gdf.iterrows()):
            line = RasTerrain._as_linestring(row.geometry)
            if line is None:
                continue
            left_bank = RasTerrain._safe_float(row.get("Left Bank"))
            right_bank = RasTerrain._safe_float(row.get("Right Bank"))
            try:
                records, bank_info, edge_info = RasTerrain._build_xs_point_records(
                    line=line,
                    station_elevation=row.get("station_elevation"),
                    river=str(row.get("River", "")),
                    reach=str(row.get("Reach", "")),
                    rs=str(row.get("RS", "")),
                    xs_order=xs_order,
                    left_bank=left_bank,
                    right_bank=right_bank,
                    channel_only=channel_only,
                )
            except Exception as e:
                logger.warning(f"Skipping HDF cross section {row.get('RS', xs_order)}: {e}")
                continue
            point_records.extend(records)
            if bank_info:
                bank_infos.append(bank_info)
            if edge_info:
                edge_infos.append(edge_info)

        return xs_gdf, centerlines_gdf, bank_lines_gdf, point_records, bank_infos, edge_infos

    @staticmethod
    def _load_plain_xs_surface_inputs(geom_path: Path, crs, channel_only: bool):
        import geopandas as gpd
        import numpy as np

        from ..geom import GeomCrossSection, GeomParser

        xs_df = GeomCrossSection.get_cross_sections(geom_path)
        if xs_df.empty:
            raise ValueError(f"No cross sections found in geometry file: {geom_path}")
        if "Type" in xs_df.columns:
            xs_df = xs_df[xs_df["Type"] == 1].reset_index(drop=True)
        if xs_df.empty:
            raise ValueError(f"No Type 1 cross sections found in geometry file: {geom_path}")

        cut_lines_gdf = GeomParser.get_xs_cut_lines(geom_path)
        cut_lines_gdf = RasTerrain._set_gdf_crs(cut_lines_gdf, crs)
        if cut_lines_gdf.empty:
            raise ValueError(f"No XS GIS cut lines found in geometry file: {geom_path}")

        try:
            centerlines_gdf = GeomParser.get_river_centerlines(geom_path)
            centerlines_gdf = RasTerrain._set_gdf_crs(centerlines_gdf, crs)
        except Exception as e:
            logger.warning(f"Could not read river centerlines from {geom_path}: {e}")
            centerlines_gdf = gpd.GeoDataFrame(geometry=[], crs=crs)

        point_records: List[Dict[str, Any]] = []
        bank_infos: List[Dict[str, Any]] = []
        edge_infos: List[Dict[str, Any]] = []
        xs_records: List[Dict[str, Any]] = []

        for xs_order, (_, row) in enumerate(xs_df.iterrows()):
            river = str(row["River"])
            reach = str(row["Reach"])
            rs = str(row["RS"])
            matches = cut_lines_gdf[
                (cut_lines_gdf["river"] == river)
                & (cut_lines_gdf["reach"] == reach)
                & (cut_lines_gdf["station"] == rs)
            ]
            if matches.empty:
                logger.warning(f"No XS GIS cut line found for {river}/{reach}/RS {rs}")
                continue
            line = RasTerrain._as_linestring(matches.iloc[0].geometry)
            if line is None:
                continue

            try:
                sta_elev_df = GeomCrossSection.get_station_elevation(
                    geom_path,
                    river,
                    reach,
                    rs,
                )
            except ValueError as e:
                logger.warning(f"Skipping cross section {river}/{reach}/RS {rs}: {e}")
                continue

            banks = GeomCrossSection.get_bank_stations(geom_path, river, reach, rs)
            left_bank = RasTerrain._safe_float(banks[0]) if banks else None
            right_bank = RasTerrain._safe_float(banks[1]) if banks else None
            station_elevation = sta_elev_df[["Station", "Elevation"]].to_numpy(dtype=float)

            records, bank_info, edge_info = RasTerrain._build_xs_point_records(
                line=line,
                station_elevation=station_elevation,
                river=river,
                reach=reach,
                rs=rs,
                xs_order=xs_order,
                left_bank=left_bank,
                right_bank=right_bank,
                channel_only=channel_only,
            )
            point_records.extend(records)
            if bank_info:
                bank_infos.append(bank_info)
            if edge_info:
                edge_infos.append(edge_info)

            xs_record = row.to_dict()
            xs_record.update(
                {
                    "xs_order": int(xs_order),
                    "point_count": int(len(station_elevation)),
                    "Left Bank": left_bank if left_bank is not None else np.nan,
                    "Right Bank": right_bank if right_bank is not None else np.nan,
                    "geometry": line,
                }
            )
            xs_records.append(xs_record)

        cross_sections_gdf = gpd.GeoDataFrame(xs_records, geometry="geometry", crs=crs)
        bank_lines_gdf = gpd.GeoDataFrame(geometry=[], crs=crs)
        return cross_sections_gdf, centerlines_gdf, bank_lines_gdf, point_records, bank_infos, edge_infos

    # ------------------------------------------------------------------
    # XS Interpolation Surface public API
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def compute_xs_interpolation_surface(
        geom_path: Union[str, Path],
        output_gpkg: Optional[Union[str, Path]] = None,
        output_raster: Optional[Union[str, Path]] = None,
        raster_cell_size: Optional[float] = None,
        crs: Optional[Union[str, int]] = None,
        channel_only: bool = True,
        nodata: float = -9999.0,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Compute a cross-section interpolation surface for channel bathymetry.

        This is the ras-commander API equivalent of the RASMapper workflow:
        Cross Sections -> Interpolation Surface -> Compute XS Interpolation
        Surface. It reads cross-section cut lines, station/elevation points,
        bank stations, river centerlines, and bank lines through existing HDF
        or plain-text geometry APIs, then returns reviewable GeoDataFrames and
        optionally persists review layers and a GeoTIFF raster.

        Args:
            geom_path: Geometry HDF path (``*.g##.hdf``) or plain geometry path
                (``*.g##``).
            output_gpkg: Optional GeoPackage path for review layers.
            output_raster: Optional GeoTIFF path for rasterized interpolation.
            raster_cell_size: Cell size in project units. Required when
                ``output_raster`` is provided. If provided without
                ``output_raster``, an in-memory raster array is returned.
            crs: Optional CRS override. Plain geometry files otherwise try to
                resolve CRS from the sibling geometry HDF/RASMapper projection.
            channel_only: If True, clip/interpolate between left and right
                bank stations or RAS bank lines. If False, use full XS extents.
            nodata: NoData value for raster output.
            ras_object: Optional RasPrj instance for project context.

        Returns:
            dict: Contains ``points``, ``triangles``, ``channel_polygon``,
            ``cross_sections``, ``bank_lines``, ``river_centerlines``,
            ``metadata``, and optional ``raster`` entries.
        """
        import geopandas as gpd

        geom_path = Path(geom_path)
        if not geom_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_path}")
        if output_raster is not None and raster_cell_size is None:
            raise ValueError("raster_cell_size is required when output_raster is provided")
        if raster_cell_size is not None and raster_cell_size <= 0:
            raise ValueError(f"raster_cell_size must be positive, got: {raster_cell_size}")

        resolved_crs = RasTerrain._resolve_xs_surface_crs(geom_path, crs)
        is_hdf = geom_path.suffix.lower() == ".hdf"

        if is_hdf:
            (
                cross_sections_gdf,
                centerlines_gdf,
                hdf_bank_lines_gdf,
                point_records,
                bank_infos,
                edge_infos,
            ) = RasTerrain._load_hdf_xs_surface_inputs(
                geom_path,
                resolved_crs,
                channel_only,
                ras_object=ras_object,
            )
            source_type = "geometry_hdf"
        else:
            (
                cross_sections_gdf,
                centerlines_gdf,
                hdf_bank_lines_gdf,
                point_records,
                bank_infos,
                edge_infos,
            ) = RasTerrain._load_plain_xs_surface_inputs(
                geom_path,
                resolved_crs,
                channel_only,
            )
            source_type = "plain_geometry"

        if not point_records:
            raise ValueError(f"No interpolation points could be built from {geom_path}")

        points_gdf = gpd.GeoDataFrame(point_records, geometry="geometry", crs=resolved_crs)
        if points_gdf.empty:
            raise ValueError(f"No interpolation points could be built from {geom_path}")

        derived_bank_lines_gdf = RasTerrain._bank_lines_from_bank_points(
            bank_infos,
            crs=resolved_crs,
        )

        bank_line_source = "none"
        if channel_only:
            bank_lines_gdf = hdf_bank_lines_gdf
            footprint_gdf = RasTerrain._footprint_from_bank_lines(
                bank_lines_gdf,
                crs=resolved_crs,
            )
            if footprint_gdf.empty:
                bank_lines_gdf = derived_bank_lines_gdf
                footprint_gdf = RasTerrain._footprint_from_bank_lines(
                    bank_lines_gdf,
                    crs=resolved_crs,
                )
                bank_line_source = "xs_bank_stations" if not footprint_gdf.empty else "none"
            else:
                bank_line_source = "hdf_bank_lines"

            if footprint_gdf.empty:
                raise ValueError(
                    "Could not build a channel interpolation footprint from bank "
                    "lines or XS bank stations. Use channel_only=False to build "
                    "a full-cross-section interpolation footprint."
                )
            footprint_source = "channel_banks"
        else:
            bank_lines_gdf = (
                hdf_bank_lines_gdf
                if hdf_bank_lines_gdf is not None and not hdf_bank_lines_gdf.empty
                else derived_bank_lines_gdf
            )
            if bank_lines_gdf is not None and not bank_lines_gdf.empty:
                bank_line_source = str(bank_lines_gdf.iloc[0].get("source", "bank_lines"))
            footprint_gdf = RasTerrain._footprint_from_xs_edges(edge_infos, crs=resolved_crs)
            if footprint_gdf.empty:
                raise ValueError("Could not build a full-cross-section interpolation footprint")
            footprint_source = "xs_extents"

        triangles_gdf = RasTerrain._compute_tin_triangles(
            points_gdf,
            footprint_gdf,
            crs=resolved_crs,
        )

        raster = None
        if raster_cell_size is not None:
            raster = RasTerrain._build_raster_surface(
                points_gdf,
                footprint_gdf,
                raster_cell_size,
                crs=resolved_crs,
                nodata=nodata,
                output_raster=output_raster,
            )

        metadata = {
            "geom_path": str(geom_path),
            "source_type": source_type,
            "channel_only": bool(channel_only),
            "crs": str(resolved_crs) if resolved_crs is not None else None,
            "cross_section_count": int(len(cross_sections_gdf)),
            "interpolation_point_count": int(len(points_gdf)),
            "triangle_count": int(len(triangles_gdf)),
            "bank_line_count": int(len(bank_lines_gdf)) if bank_lines_gdf is not None else 0,
            "bank_line_source": bank_line_source,
            "footprint_source": footprint_source,
            "output_gpkg": str(output_gpkg) if output_gpkg is not None else None,
            "output_raster": str(output_raster) if output_raster is not None else None,
        }
        if raster is not None:
            metadata.update(
                {
                    "raster_shape": tuple(int(value) for value in raster["array"].shape),
                    "raster_cell_size": float(raster_cell_size),
                    "raster_valid_cell_count": int(raster["valid_cell_count"]),
                }
            )

        if output_gpkg is not None:
            RasTerrain._write_xs_surface_gpkg(
                output_gpkg,
                {
                    "xs_interpolation_triangles": triangles_gdf,
                    "xs_interpolation_points": points_gdf,
                    "channel_polygon": footprint_gdf,
                    "cross_sections": cross_sections_gdf,
                    "bank_lines": bank_lines_gdf,
                    "river_centerlines": centerlines_gdf,
                },
            )

        logger.info(
            "Computed XS interpolation surface from %s: %s cross sections, "
            "%s points, %s triangles",
            geom_path.name,
            metadata["cross_section_count"],
            metadata["interpolation_point_count"],
            metadata["triangle_count"],
        )

        return {
            "points": points_gdf,
            "triangles": triangles_gdf,
            "channel_polygon": footprint_gdf,
            "cross_sections": cross_sections_gdf,
            "bank_lines": bank_lines_gdf,
            "river_centerlines": centerlines_gdf,
            "metadata": metadata,
            "raster": raster,
        }

    # ------------------------------------------------------------------
    # Terrain creation (RasProcess.exe)
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def _get_hecras_path(version: str = "7.0") -> Path:
        """
        Get path to HEC-RAS installation directory.

        Searches standard installation locations for the specified HEC-RAS
        version and verifies that RasProcess.exe exists.

        Args:
            version: HEC-RAS version string (e.g., "7.0", "6.5", "6.3").
                     Defaults to "7.0".

        Returns:
            Path: Path to HEC-RAS installation directory containing
                  RasProcess.exe.

        Raises:
            FileNotFoundError: If HEC-RAS installation not found for the
                               specified version.

        Example:
            >>> hecras_path = RasTerrain._get_hecras_path("7.0")
            >>> print(hecras_path)
            C:\\Program Files (x86)\\HEC\\HEC-RAS\\7.0
        """
        for base_path in RasTerrain._HECRAS_BASE_PATHS:
            hecras_path = base_path / version
            rasprocess = hecras_path / "RasProcess.exe"

            if rasprocess.exists():
                logger.debug(f"Found HEC-RAS {version} at {hecras_path}")
                return hecras_path

        # Try with minor version variations
        version_parts = version.split(".")
        if len(version_parts) == 2:
            major, minor = version_parts
            # Try checking for point releases (e.g., 6.6.1)
            for base_path in RasTerrain._HECRAS_BASE_PATHS:
                parent = base_path
                if parent.exists():
                    for subdir in parent.iterdir():
                        if subdir.is_dir() and subdir.name.startswith(f"{major}.{minor}"):
                            rasprocess = subdir / "RasProcess.exe"
                            if rasprocess.exists():
                                logger.debug(f"Found HEC-RAS at {subdir}")
                                return subdir

        raise FileNotFoundError(
            f"HEC-RAS {version} installation not found. "
            f"Searched in: {[str(p) for p in RasTerrain._HECRAS_BASE_PATHS]}. "
            f"Ensure HEC-RAS {version} is installed and RasProcess.exe exists."
        )

    @staticmethod
    @log_call
    def _get_hecras_gdal_path(version: str = "7.0") -> Path:
        """
        Get path to GDAL tools in HEC-RAS installation.

        HEC-RAS bundles GDAL tools that are optimized for HEC-RAS terrain
        formats. This method locates the GDAL bin64 directory.

        Args:
            version: HEC-RAS version string (e.g., "7.0"). Defaults to "7.0".

        Returns:
            Path: Path to GDAL bin64 directory containing gdal_translate.exe,
                  gdaladdo.exe, and other GDAL utilities.

        Raises:
            FileNotFoundError: If HEC-RAS installation or GDAL tools not found.

        Example:
            >>> gdal_path = RasTerrain._get_hecras_gdal_path("7.0")
            >>> print(gdal_path)
            C:\\Program Files (x86)\\HEC\\HEC-RAS\\6.6\\GDAL\\bin64
        """
        hecras_path = RasTerrain._get_hecras_path(version)

        # Check for GDAL in different possible locations
        gdal_paths = [
            hecras_path / "GDAL" / "bin64",
            hecras_path / "GDAL" / "bin",
            hecras_path / "gdal" / "bin64",
            hecras_path / "gdal" / "bin",
        ]

        for gdal_path in gdal_paths:
            if gdal_path.exists():
                # Verify key GDAL tools exist
                gdal_translate = gdal_path / "gdal_translate.exe"
                if gdal_translate.exists():
                    logger.debug(f"Found HEC-RAS GDAL tools at {gdal_path}")
                    return gdal_path

        raise FileNotFoundError(
            f"HEC-RAS GDAL tools not found in {hecras_path}. "
            f"Expected GDAL\\bin64\\gdal_translate.exe to exist."
        )

    @staticmethod
    def _get_hecras_gdal_path_from_install(hecras_path: Path) -> Path:
        """Return the bundled GDAL executable folder for a HEC-RAS install."""
        gdal_paths = [
            hecras_path / "GDAL" / "bin64",
            hecras_path / "GDAL" / "bin",
            hecras_path / "gdal" / "bin64",
            hecras_path / "gdal" / "bin",
        ]

        for gdal_path in gdal_paths:
            if (gdal_path / "gdal_translate.exe").exists():
                return gdal_path

        raise FileNotFoundError(
            f"HEC-RAS GDAL tools not found in {hecras_path}. "
            f"Expected GDAL\\bin64\\gdal_translate.exe to exist."
        )

    @staticmethod
    def _is_conflicting_gdal_path(path_value: str, hecras_path: Path) -> bool:
        """Identify PATH entries likely to inject non-HEC GDAL/PROJ DLLs."""
        if not path_value:
            return False

        try:
            candidate = Path(path_value).resolve()
            hecras_resolved = hecras_path.resolve()
            if candidate == hecras_resolved or hecras_resolved in candidate.parents:
                return False
        except (OSError, RuntimeError, ValueError):
            pass

        normalized = path_value.replace("/", "\\").lower()
        conflict_tokens = (
            "rasterio",
            "rasterio.libs",
            "pyproj",
            "pyproj.libs",
            "fiona",
            "fiona.libs",
            "pyogrio",
            "pyogrio.libs",
            "\\osgeo4w",
            "\\qgis",
            "\\gdal\\",
            "program files\\gdal",
        )
        return any(token in normalized for token in conflict_tokens)

    @staticmethod
    def _build_hecras_terrain_env(hecras_path: Path) -> Dict[str, str]:
        """
        Build a subprocess environment isolated to HEC-RAS's bundled GDAL.

        Python GIS packages and system GDAL installs commonly set GDAL/PROJ
        variables or PATH entries that can be inherited by RasProcess.exe.
        CreateTerrain is sensitive to that mismatch, so terrain creation gets
        a child-only environment with HEC-RAS paths first and external GDAL/PROJ
        configuration removed.
        """
        env = os.environ.copy()

        for key in (
            "GDAL_DATA",
            "GDAL_DRIVER_PATH",
            "GDAL_SKIP",
            "PROJ_DATA",
            "PROJ_LIB",
            "PROJ_NETWORK",
        ):
            env.pop(key, None)

        gdal_path = RasTerrain._get_hecras_gdal_path_from_install(hecras_path)
        preferred_paths = [str(hecras_path), str(gdal_path)]

        raw_path = env.get("PATH", "")
        inherited_paths = [
            path_entry
            for path_entry in raw_path.split(os.pathsep)
            if path_entry
            and path_entry not in preferred_paths
            and not RasTerrain._is_conflicting_gdal_path(path_entry, hecras_path)
        ]
        env["PATH"] = os.pathsep.join(preferred_paths + inherited_paths)

        return env

    @staticmethod
    def _format_rasprocess_failure(
        result: subprocess.CompletedProcess,
        output_hdf: Path,
    ) -> str:
        """Create a concise diagnostic string for RasProcess failures."""
        details = [
            f"Terrain creation failed for {output_hdf}.",
            f"Return code: {result.returncode}.",
        ]
        if result.stderr:
            details.append(f"STDERR: {result.stderr.strip()}")
        if result.stdout:
            details.append(f"STDOUT: {result.stdout.strip()}")
        return " ".join(details)

    @staticmethod
    def _validate_terrain_hdf(output_hdf: Path) -> Dict[str, Any]:
        """
        Validate that CreateTerrain produced a usable, non-stub terrain HDF.

        A failed CreateTerrain run can leave a tiny HDF5 file with only an empty
        /Terrain group. That file is syntactically valid HDF5 but unusable by
        the geometry preprocessor, so existence alone is not enough.
        """
        try:
            import h5py
        except ImportError as exc:
            raise RuntimeError(
                "h5py is required to validate HEC-RAS terrain HDF output."
            ) from exc

        try:
            with h5py.File(output_hdf, "r") as hdf:
                if "Terrain" not in hdf:
                    raise RuntimeError(
                        f"Terrain HDF is missing the required /Terrain group: "
                        f"{output_hdf}"
                    )

                groups: List[str] = []
                datasets: List[str] = []

                def collect(name, obj):
                    if isinstance(obj, h5py.Dataset):
                        datasets.append(name)
                    elif isinstance(obj, h5py.Group):
                        groups.append(name)

                hdf["Terrain"].visititems(collect)

        except OSError as exc:
            raise RuntimeError(
                f"Terrain creation produced an unreadable HDF file: {output_hdf}"
            ) from exc

        if not datasets:
            file_size = output_hdf.stat().st_size
            group_summary = ", ".join(groups[:10]) if groups else "<none>"
            raise RuntimeError(
                f"Terrain creation produced a stub HDF with no datasets under "
                f"/Terrain: {output_hdf} ({file_size:,} bytes). "
                f"Terrain groups found: {group_summary}. This usually indicates "
                "RasProcess.exe failed during final terrain HDF assembly."
            )

        return {
            "groups": len(groups),
            "datasets": len(datasets),
            "sample_datasets": datasets[:5],
        }

    @staticmethod
    @log_call
    def _generate_prj_from_raster(
        raster_path: Union[str, Path],
        output_prj: Union[str, Path]
    ) -> Path:
        """
        Generate ESRI PRJ file from raster's coordinate reference system.

        Reads the CRS from the input raster and writes it as an ESRI-format
        projection file (.prj) suitable for use with RasProcess.exe.

        Args:
            raster_path: Path to input raster file (GeoTIFF, etc.).
            output_prj: Path for output ESRI PRJ file.

        Returns:
            Path: Path to created PRJ file.

        Raises:
            ImportError: If rasterio is not installed.
            ValueError: If raster has no CRS defined.
            FileNotFoundError: If raster file not found.

        Example:
            >>> prj_file = RasTerrain._generate_prj_from_raster(
            ...     "dem.tif",
            ...     "Projection.prj"
            ... )
        """
        raster_path = Path(raster_path)
        output_prj = Path(output_prj)

        if not raster_path.exists():
            raise FileNotFoundError(f"Raster file not found: {raster_path}")

        try:
            import rasterio
        except ImportError:
            raise ImportError(
                "rasterio is required for automatic PRJ generation. "
                "Install with: pip install rasterio\n"
                "Alternatively, provide an existing ESRI PRJ file."
            )

        with rasterio.open(raster_path) as src:
            if src.crs is None:
                raise ValueError(
                    f"Raster has no CRS defined: {raster_path}. "
                    f"Cannot generate projection file."
                )

            # Get WKT in ESRI format
            try:
                # pyproj 3.x approach
                from pyproj import CRS
                crs = CRS.from_wkt(src.crs.to_wkt())
                prj_wkt = crs.to_wkt("WKT1_ESRI")
            except (ImportError, AttributeError):
                # Fallback: use rasterio's WKT (may not be ESRI format)
                prj_wkt = src.crs.to_wkt()
                logger.warning(
                    "pyproj not available for ESRI WKT conversion. "
                    "Using standard WKT format."
                )

        # Ensure parent directory exists
        output_prj.parent.mkdir(parents=True, exist_ok=True)

        # Write PRJ file
        output_prj.write_text(prj_wkt, encoding='utf-8')
        logger.info(f"Created projection file: {output_prj}")

        return output_prj

    @staticmethod
    @log_call
    def create_terrain_hdf(
        input_rasters: List[Union[str, Path]],
        output_hdf: Union[str, Path],
        projection_prj: Union[str, Path],
        units: str = "Feet",
        stitch: bool = True,
        hecras_version: str = "7.0",
        timeout_seconds: int = 600,
    ) -> Path:
        """
        Create HEC-RAS terrain HDF from input rasters using RasProcess.exe.

        This method uses the verified RasProcess.exe CreateTerrain command
        to create a terrain HDF file compatible with HEC-RAS. The created
        terrain includes:
        - Multi-resolution pyramid levels (7 levels, 0-6)
        - TIN stitching for seamless multi-source terrain
        - Tile-based storage optimized for HEC-RAS rendering

        Args:
            input_rasters: List of input raster file paths (GeoTIFF, FLT, etc.).
                          Files are processed in priority order - first file
                          has highest priority in overlapping areas.
            output_hdf: Path for output terrain HDF file. Parent directory
                       will be created if it doesn't exist.
            projection_prj: Path to ESRI PRJ file defining the coordinate
                           reference system. Must be an existing file.
            units: Vertical data units. Options: "Feet" or "Meters".
                   Defaults to "Feet".
            stitch: Enable terrain stitching for multi-source terrains.
                   Defaults to True.
            hecras_version: HEC-RAS version to use for RasProcess.exe.
                           Defaults to "7.0".
            timeout_seconds: Maximum time to wait for RasProcess.exe to
                            finish terrain creation. Defaults to 600
                            seconds (10 minutes).

        Returns:
            Path: Path to created terrain HDF file.

        Raises:
            FileNotFoundError: If HEC-RAS installation, input rasters, or
                              PRJ file not found.
            ValueError: If units is not "Feet" or "Meters".
            RuntimeError: If terrain creation fails.

        Example:
            >>> from pathlib import Path
            >>> terrain = RasTerrain.create_terrain_hdf(
            ...     input_rasters=[Path("Terrain/dem.tif")],
            ...     output_hdf=Path("Terrain/Terrain.hdf"),
            ...     projection_prj=Path("Terrain/Projection.prj"),
            ...     units="Feet",
            ...     stitch=True,
            ...     hecras_version="7.0",
            ...     timeout_seconds=1800,
            ... )
            >>> print(f"Terrain created: {terrain}")

        Notes:
            - The RasProcess.exe command requires all paths to be quoted
              due to spaces in "Program Files".
            - Input rasters are processed in order - first raster has
              priority in overlapping areas.
            - The output folder will be created automatically if it doesn't
              exist.
            - Verified working with HEC-RAS 6.6 (tested 2025-12-25).
        """
        # Convert to Path objects. Resolve to ABSOLUTE paths: RasProcess.exe runs with
        # cwd=hecras_path (so HEC's bundled GDAL/PROJ resolve correctly), which means any
        # relative prj/out/input paths would be looked up under the HEC-RAS install dir and
        # fail ("PRJ File ... does not exist"). Absolutizing here keeps cwd harmless.
        output_hdf = Path(output_hdf).resolve()
        projection_prj = Path(projection_prj).resolve()
        input_rasters = [Path(r).resolve() for r in input_rasters]

        # Validate units
        if units not in ("Feet", "Meters"):
            raise ValueError(
                f"Units must be 'Feet' or 'Meters', got: '{units}'"
            )
        if timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be positive, got: {timeout_seconds}"
            )

        # Validate input files exist
        for raster in input_rasters:
            if not raster.exists():
                raise FileNotFoundError(f"Input raster not found: {raster}")

        # Validate PRJ file exists
        if not projection_prj.exists():
            raise FileNotFoundError(
                f"Projection PRJ file not found: {projection_prj}. "
                f"Use _generate_prj_from_raster() to create one from a raster."
            )

        # Get HEC-RAS path
        hecras_path = RasTerrain._get_hecras_path(hecras_version)
        rasprocess = hecras_path / "RasProcess.exe"

        # Ensure output directory exists
        output_hdf.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing output if present
        if output_hdf.exists():
            output_hdf.unlink()
            logger.info(f"Removed existing terrain HDF: {output_hdf}")

        # Build command arguments. Passing a list handles spaces in paths
        # without involving the shell.
        stitch_str = "true" if stitch else "false"

        cmd = [
            str(rasprocess),
            "CreateTerrain",
            f"units={units}",
            f"stitch={stitch_str}",
            f"prj={projection_prj}",
            f"out={output_hdf}",
        ] + [str(raster) for raster in input_rasters]
        env = RasTerrain._build_hecras_terrain_env(hecras_path)

        logger.info(f"Executing terrain creation command...")
        logger.debug(f"Command: {subprocess.list2cmdline(cmd)}")

        # Execute command
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=str(hecras_path),
                env=env,
            )

            logger.debug(f"Return code: {result.returncode}")

            if result.stdout:
                logger.debug(f"STDOUT: {result.stdout}")

            if result.stderr:
                logger.warning(f"STDERR: {result.stderr}")

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Terrain creation timed out after {timeout_seconds} seconds. "
                "This may indicate very large input files or system issues."
            )
        except Exception as e:
            raise RuntimeError(f"Failed to execute RasProcess.exe: {e}")

        if result.returncode != 0:
            raise RuntimeError(
                RasTerrain._format_rasprocess_failure(result, output_hdf)
            )

        # Verify output was created
        if not output_hdf.exists():
            raise RuntimeError(
                f"Terrain creation failed - output HDF not created: {output_hdf}."
                f" {RasTerrain._format_rasprocess_failure(result, output_hdf)}"
            )

        validation = RasTerrain._validate_terrain_hdf(output_hdf)

        # Log success
        file_size = output_hdf.stat().st_size
        logger.info(
            f"Terrain HDF created successfully: {output_hdf} "
            f"({file_size:,} bytes, {file_size/1024/1024:.2f} MB, "
            f"{validation['datasets']} datasets)"
        )

        return output_hdf

    @staticmethod
    @log_call
    def vrt_to_tiff(
        vrt_path: Union[str, Path],
        output_path: Union[str, Path],
        compression: str = "LZW",
        create_overviews: bool = True,
        overview_levels: Optional[List[int]] = None,
        nodata_value: Optional[float] = None,
        hecras_version: str = "7.0"
    ) -> Path:
        """
        Convert VRT (Virtual Raster) to single optimized TIFF.

        Uses GDAL tools bundled with HEC-RAS installation to convert a VRT
        mosaic to a single GeoTIFF file. Optionally adds pyramid overviews
        for faster rendering in HEC-RAS.

        Args:
            vrt_path: Path to input VRT file.
            output_path: Path for output TIFF file.
            compression: Compression algorithm for output TIFF.
                        Options: "LZW", "DEFLATE", "ZSTD", "NONE".
                        Defaults to "LZW".
            create_overviews: Add pyramid overviews for faster rendering.
                             Defaults to True.
            overview_levels: Custom overview levels (e.g., [2, 4, 8, 16, 32]).
                            Defaults to [2, 4, 8, 16, 32] if None.
            nodata_value: NoData value for output raster. If None, uses
                         source NoData value.
            hecras_version: HEC-RAS version for GDAL tools path.
                           Defaults to "7.0".

        Returns:
            Path: Path to created TIFF file.

        Raises:
            FileNotFoundError: If VRT file or HEC-RAS GDAL tools not found.
            RuntimeError: If conversion fails.

        Example:
            >>> output = RasTerrain.vrt_to_tiff(
            ...     vrt_path="terrain/combined.vrt",
            ...     output_path="terrain/combined.tif",
            ...     compression="LZW",
            ...     create_overviews=True
            ... )
        """
        vrt_path = Path(vrt_path)
        output_path = Path(output_path)

        if not vrt_path.exists():
            raise FileNotFoundError(f"VRT file not found: {vrt_path}")

        # Set default overview levels
        if overview_levels is None:
            overview_levels = [2, 4, 8, 16, 32]

        # Get GDAL tools path
        gdal_path = RasTerrain._get_hecras_gdal_path(hecras_version)
        gdal_translate = gdal_path / "gdal_translate.exe"
        gdaladdo = gdal_path / "gdaladdo.exe"

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build gdal_translate command
        cmd = [
            str(gdal_translate),
            "-of", "GTiff",
            "-co", f"COMPRESS={compression}",
            "-co", "TILED=YES",
            "-co", "BIGTIFF=IF_SAFER",
        ]

        if nodata_value is not None:
            cmd.extend(["-a_nodata", str(nodata_value)])

        cmd.extend([str(vrt_path), str(output_path)])

        logger.info(f"Converting VRT to TIFF: {vrt_path} -> {output_path}")
        logger.debug(f"Command: {' '.join(cmd)}")

        # Execute gdal_translate
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800  # 30 minute timeout for large files
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"gdal_translate failed with code {result.returncode}. "
                    f"STDERR: {result.stderr}"
                )

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "VRT to TIFF conversion timed out. "
                "Consider processing smaller areas."
            )
        except Exception as e:
            if "RuntimeError" in str(type(e)):
                raise
            raise RuntimeError(f"Failed to execute gdal_translate: {e}")

        # Verify output was created
        if not output_path.exists():
            raise RuntimeError(
                f"TIFF creation failed - output file not created: {output_path}"
            )

        logger.info(f"TIFF created: {output_path}")

        # Add overviews if requested
        if create_overviews:
            logger.info(f"Adding pyramid overviews: {overview_levels}")

            cmd = [
                str(gdaladdo),
                "-r", "average",
                str(output_path)
            ] + [str(level) for level in overview_levels]

            logger.debug(f"Command: {' '.join(cmd)}")

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minute timeout for overviews
                )

                if result.returncode != 0:
                    logger.warning(
                        f"gdaladdo failed with code {result.returncode}. "
                        f"STDERR: {result.stderr}. Continuing without overviews."
                    )
                else:
                    logger.info("Pyramid overviews added successfully")

            except subprocess.TimeoutExpired:
                logger.warning(
                    "Overview creation timed out. Continuing without overviews."
                )
            except Exception as e:
                logger.warning(f"Failed to add overviews: {e}")

        # Log final file info
        file_size = output_path.stat().st_size
        logger.info(
            f"VRT to TIFF conversion complete: {output_path} "
            f"({file_size:,} bytes, {file_size/1024/1024:.2f} MB)"
        )

        return output_path

    @staticmethod
    @log_call
    def create_terrain_from_rasters(
        input_rasters: List[Union[str, Path]],
        output_folder: Union[str, Path],
        terrain_name: str = "Terrain",
        units: str = "Feet",
        stitch: bool = True,
        hecras_version: str = "7.0",
        generate_prj: bool = True
    ) -> Path:
        """
        Create HEC-RAS terrain from input rasters with automatic PRJ generation.

        This is a convenience method that combines PRJ generation and terrain
        creation. It automatically generates the projection file from the first
        input raster's CRS.

        Args:
            input_rasters: List of input raster file paths.
            output_folder: Folder for terrain output (HDF + PRJ files).
            terrain_name: Base name for terrain files (e.g., "Terrain" creates
                         Terrain.hdf). Defaults to "Terrain".
            units: Vertical data units ("Feet" or "Meters").
            stitch: Enable terrain stitching. Defaults to True.
            hecras_version: HEC-RAS version. Defaults to "7.0".
            generate_prj: Auto-generate PRJ from first raster. If False,
                         expects Projection.prj to exist in output_folder.

        Returns:
            Path: Path to created terrain HDF file.

        Raises:
            FileNotFoundError: If input rasters not found.
            ImportError: If rasterio not available for PRJ generation.
            RuntimeError: If terrain creation fails.

        Example:
            >>> terrain = RasTerrain.create_terrain_from_rasters(
            ...     input_rasters=["lidar_dem.tif", "bathymetry.tif"],
            ...     output_folder="Terrain",
            ...     terrain_name="Terrain50",
            ...     units="Feet"
            ... )
        """
        output_folder = Path(output_folder)
        input_rasters = [Path(r) for r in input_rasters]

        # Validate input files exist
        for raster in input_rasters:
            if not raster.exists():
                raise FileNotFoundError(f"Input raster not found: {raster}")

        # Ensure output folder exists
        output_folder.mkdir(parents=True, exist_ok=True)

        # Define output paths
        output_hdf = output_folder / f"{terrain_name}.hdf"
        projection_prj = output_folder / "Projection.prj"

        # Generate PRJ if requested and not already present
        if generate_prj and not projection_prj.exists():
            logger.debug(f"Generating projection file from: {input_rasters[0]}")
            RasTerrain._generate_prj_from_raster(
                input_rasters[0],
                projection_prj
            )
        elif not projection_prj.exists():
            raise FileNotFoundError(
                f"Projection file not found and generate_prj=False: {projection_prj}"
            )

        # Create terrain HDF
        return RasTerrain.create_terrain_hdf(
            input_rasters=input_rasters,
            output_hdf=output_hdf,
            projection_prj=projection_prj,
            units=units,
            stitch=stitch,
            hecras_version=hecras_version
        )

    @staticmethod
    def get_available_versions() -> List[str]:
        """
        Get list of installed HEC-RAS versions with terrain creation support.

        Scans standard HEC-RAS installation directories for versions that
        have RasProcess.exe available.

        Returns:
            List[str]: List of version strings (e.g., ["7.0", "6.5"]).
                      Empty list if no compatible versions found.

        Example:
            >>> versions = RasTerrain.get_available_versions()
            >>> print(versions)
            ['6.6', '6.5', '6.4', '6.3']
        """
        versions = []

        for base_path in RasTerrain._HECRAS_BASE_PATHS:
            if not base_path.exists():
                continue

            for subdir in base_path.iterdir():
                if not subdir.is_dir():
                    continue

                rasprocess = subdir / "RasProcess.exe"
                if rasprocess.exists():
                    versions.append(subdir.name)

        # Sort versions in descending order
        versions.sort(reverse=True)

        return versions
