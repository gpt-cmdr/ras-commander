"""
HdfStorageArea - Storage-area geometry, properties, and volume data from HEC-RAS HDF files.

This module provides a static ``HdfStorageArea`` namespace for reading storage
area polygons/properties from geometry HDF files, extracting HDF-stored
elevation-volume curves, and computing stage-storage curves from terrain.

List of Functions:
- get_storage_area_names() - List storage area names from geometry HDF
- get_storage_area_properties() - Extract attributes for a named storage area
- get_volume_elevation_curve() - Read pre-computed elevation-volume curve from HDF
- get_terrain_path_from_geom_hdf() - Resolve terrain raster path from geometry HDF
- compute_volume_below_elevation() - Compute volume below a WSE using terrain raster
- compute_stage_storage_curve() - Compute a full stage-storage curve from terrain
- get_storage_area_for_breach_structure() - Map a breach structure to its upstream SA
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import h5py
import numpy as np
import pandas as pd

from .HdfStruc import HdfStruc
from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


class HdfStorageArea:
    """
    Static helpers for HEC-RAS storage-area HDF data.

    Methods accept geometry HDF paths directly or the flexible geometry inputs
    supported by ``standardize_input(file_type="geom_hdf")``.
    """

    _STORAGE_AREA_PATH = "Geometry/Storage Areas"
    _ACRE_SQFT = 43560.0

    @staticmethod
    def _decode_hdf_value(value: Any) -> Any:
        """Decode HDF byte/scalar values into Python-native values."""
        if isinstance(value, (bytes, np.bytes_)):
            return value.decode("utf-8", errors="replace").strip()
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            value = float(value)
            return None if np.isnan(value) else value
        if isinstance(value, np.ndarray):
            return [HdfStorageArea._decode_hdf_value(item) for item in value.tolist()]
        if isinstance(value, float) and np.isnan(value):
            return None
        return value

    @staticmethod
    def _require_rasterio() -> Tuple[Any, Any]:
        """Return (rasterio, rasterio.mask.mask) or raise RuntimeError."""
        try:
            import rasterio
            from rasterio.mask import mask as rasterio_mask
        except ImportError as exc:
            raise RuntimeError(
                "rasterio is required for storage-area terrain volume calculations. "
                "Install ras-commander with the optional rasterio dependency."
            ) from exc

        return rasterio, rasterio_mask

    @staticmethod
    def _masked_terrain_array(
        src: Any, polygon: Any, rasterio_mask_fn: Any,
    ) -> Tuple[np.ndarray, Any, float]:
        """Clip terrain raster to polygon; return (data, transform, cell_area)."""
        out_image, out_transform = rasterio_mask_fn(
            src,
            [polygon.__geo_interface__],
            crop=True,
            filled=False,
        )
        terrain_data = out_image[0]
        if np.ma.isMaskedArray(terrain_data):
            terrain_data = terrain_data.astype("float64").filled(np.nan)
        else:
            terrain_data = terrain_data.astype("float64")

        if src.nodata is not None:
            terrain_data = np.where(terrain_data == src.nodata, np.nan, terrain_data)

        cell_area = abs(float(out_transform.a) * float(out_transform.e))
        return terrain_data, out_transform, cell_area

    @staticmethod
    def _extract_terrain_stats_in_polygon(
        terrain_path: Path, polygon: Any,
    ) -> Dict[str, float]:
        """Sample terrain inside and along the perimeter of a polygon."""
        rasterio, rasterio_mask_fn = HdfStorageArea._require_rasterio()

        with rasterio.open(terrain_path) as src:
            terrain_data, _, cell_area = HdfStorageArea._masked_terrain_array(
                src, polygon, rasterio_mask_fn,
            )
            interior_valid = terrain_data[~np.isnan(terrain_data)]
            if interior_valid.size == 0:
                raise ValueError("No valid terrain cells found within storage area polygon")

            perimeter_values = []
            for sample in src.sample(list(polygon.exterior.coords)):
                if len(sample) == 0:
                    continue
                value = float(sample[0])
                if src.nodata is not None and value == src.nodata:
                    continue
                if not np.isnan(value):
                    perimeter_values.append(value)

            perimeter_arr = np.asarray(perimeter_values, dtype="float64")
            if perimeter_arr.size == 0:
                perimeter_arr = interior_valid

            return {
                "min_interior": float(np.min(interior_valid)),
                "max_interior": float(np.max(interior_valid)),
                "mean_interior": float(np.mean(interior_valid)),
                "min_perimeter": float(np.min(perimeter_arr)),
                "max_perimeter": float(np.max(perimeter_arr)),
                "valid_cell_count": int(interior_valid.size),
                "cell_area": float(cell_area),
            }

    @staticmethod
    def _get_perimeter_polygon(
        hdf_path: Path, sa_name: str, *, ras_object: Any = None,
    ) -> Any:
        """Extract a single storage-area Shapely polygon, or None."""
        polygons = HdfStruc.get_storage_area_polygons(hdf_path, ras_object=ras_object)
        if polygons.empty or "Name" not in polygons.columns:
            return None

        matches = polygons[polygons["Name"].astype(str).str.strip() == str(sa_name).strip()]
        if matches.empty:
            return None

        return matches.iloc[0].geometry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    @standardize_input(file_type="geom_hdf")
    def get_storage_area_names(hdf_path: Path, *, ras_object=None) -> List[str]:
        """
        Return storage area names from a geometry HDF file.

        Parameters
        ----------
        hdf_path : Path
            Path to a HEC-RAS geometry HDF file.
        ras_object : RasPrj, optional
            RAS object for multi-project workflows.
        """
        with h5py.File(hdf_path, "r") as hdf_file:
            if HdfStorageArea._STORAGE_AREA_PATH not in hdf_file:
                return []
            sa_group = hdf_file[HdfStorageArea._STORAGE_AREA_PATH]
            if "Attributes" not in sa_group:
                return []

            attrs = sa_group["Attributes"][()]
            if not getattr(attrs.dtype, "names", None) or "Name" not in attrs.dtype.names:
                return []

            return [
                str(HdfStorageArea._decode_hdf_value(name)).strip()
                for name in attrs["Name"]
                if str(HdfStorageArea._decode_hdf_value(name)).strip()
            ]

    @staticmethod
    @log_call
    @standardize_input(file_type="geom_hdf")
    def get_storage_area_properties(
        hdf_path: Path,
        sa_name: str,
        *,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Extract attributes for a storage area from a geometry HDF file.

        The returned dictionary includes the original HDF field names and common
        snake_case aliases where the fields are present.
        """
        with h5py.File(hdf_path, "r") as hdf_file:
            if HdfStorageArea._STORAGE_AREA_PATH not in hdf_file:
                return {}

            sa_group = hdf_file[HdfStorageArea._STORAGE_AREA_PATH]
            if "Attributes" not in sa_group:
                return {}

            attrs = sa_group["Attributes"][()]
            names = attrs.dtype.names or ()
            if "Name" not in names:
                return {}

            for row in attrs:
                name = str(HdfStorageArea._decode_hdf_value(row["Name"])).strip()
                if name != str(sa_name).strip():
                    continue

                properties = {
                    field: HdfStorageArea._decode_hdf_value(row[field])
                    for field in names
                }
                for key, value in list(sa_group.attrs.items()):
                    decoded = HdfStorageArea._decode_hdf_value(value)
                    properties[f"group_attr:{key}"] = decoded
                    properties.setdefault(key, decoded)

                alias_fields = {
                    "name": ["Name"],
                    "mode": ["Mode"],
                    "avg_area": ["Avg Area"],
                    "min_elev": ["Min Elev"],
                    "elev_vol_count": ["Elev Vol Count"],
                    "glass_wall_elevation": [
                        "Glass Wall Elevation",
                        "Glass Wall Elev",
                        "Glass Wall",
                    ],
                    "initial_ws_elevation": [
                        "Initial WS Elevation",
                        "Initial WSE",
                        "Initial WSE Elevation",
                        "Initial SA Elevation",
                    ],
                }
                for alias, candidates in alias_fields.items():
                    for candidate in candidates:
                        if candidate in properties:
                            properties[alias] = properties[candidate]
                            break

                return properties

        return {}

    @staticmethod
    @log_call
    @standardize_input(file_type="geom_hdf")
    def get_volume_elevation_curve(
        hdf_path: Path,
        sa_name: str,
        *,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        Read the HEC-RAS pre-computed elevation-volume curve from a geometry HDF.

        Parameters
        ----------
        hdf_path : Path
            Path to a HEC-RAS geometry HDF file.
        sa_name : str
            Storage area name (e.g. ``"190"``).
        ras_object : RasPrj, optional
            RAS object for multi-project workflows.

        Returns
        -------
        pd.DataFrame
            Columns ``elevation`` and ``volume``.  Volume is in acre-feet as
            stored by HEC-RAS.  Returns an empty DataFrame if the storage area
            or curve data is not found.
        """
        empty = pd.DataFrame(columns=["elevation", "volume"])
        try:
            with h5py.File(hdf_path, "r") as hdf_file:
                if HdfStorageArea._STORAGE_AREA_PATH not in hdf_file:
                    return empty
                sa_group = hdf_file[HdfStorageArea._STORAGE_AREA_PATH]

                if "Attributes" not in sa_group:
                    return empty
                attrs = sa_group["Attributes"][()]
                field_names = getattr(attrs.dtype, "names", None)
                if not field_names or "Name" not in field_names:
                    return empty

                sa_index = None
                for idx, row in enumerate(attrs):
                    name = str(HdfStorageArea._decode_hdf_value(row["Name"])).strip()
                    if name == str(sa_name).strip():
                        sa_index = idx
                        break
                if sa_index is None:
                    return empty

                if "Volume Elevation Info" not in sa_group or "Volume Elevation Values" not in sa_group:
                    return empty

                info = sa_group["Volume Elevation Info"][()]
                start, count = int(info[sa_index, 0]), int(info[sa_index, 1])
                if count == 0:
                    return empty

                values = sa_group["Volume Elevation Values"][start:start + count]
                df = pd.DataFrame(
                    {"elevation": values[:, 1].astype("float64"),
                     "volume": values[:, 0].astype("float64")},
                )
                logger.debug(
                    "Read %d elevation-volume points for SA '%s' from %s",
                    len(df), sa_name, hdf_path,
                )
                return df

        except Exception as e:
            logger.error("Error reading volume-elevation curve for SA '%s': %s", sa_name, e)
            return empty

    @staticmethod
    @log_call
    @standardize_input(file_type="geom_hdf")
    def get_terrain_path_from_geom_hdf(
        hdf_path: Path,
        *,
        ras_object=None,
    ) -> Optional[Path]:
        """
        Resolve the terrain path referenced by a geometry HDF file.

        HEC-RAS stores the terrain HDF path in the ``/Geometry`` attributes.
        When a companion ``.vrt`` exists, this returns the VRT so rasterio can
        sample the underlying terrain rasters directly.
        """
        with h5py.File(hdf_path, "r") as hdf_file:
            geom_group = hdf_file.get("Geometry")
            if geom_group is None:
                return None

            terrain_raw = geom_group.attrs.get("Terrain Filename")
            if terrain_raw is None:
                terrain_raw = hdf_file.attrs.get("Terrain Filename")
            if terrain_raw is None:
                return None

        terrain_text = str(HdfStorageArea._decode_hdf_value(terrain_raw)).strip()
        if not terrain_text:
            return None

        terrain_text = terrain_text.replace("\\", "/")
        if terrain_text.startswith("./"):
            terrain_text = terrain_text[2:]
        terrain_path = Path(terrain_text)
        if not terrain_path.is_absolute():
            terrain_path = hdf_path.parent / terrain_path

        candidates: List[Path] = []
        if terrain_path.suffix.lower() == ".hdf":
            candidates.append(terrain_path.with_suffix(".vrt"))
        candidates.append(terrain_path)

        for candidate in candidates:
            if candidate.exists():
                return candidate

        logger.warning("Terrain referenced by %s was not found: %s", hdf_path, terrain_path)
        return None

    @staticmethod
    @log_call
    def compute_volume_below_elevation(
        terrain_path: Path,
        polygon: Any,
        elevation: float,
    ) -> float:
        """
        Compute volume below a water-surface elevation inside a storage polygon.

        The returned volume is in cubic project units, matching the horizontal
        and vertical units of the terrain raster.
        """
        rasterio, rasterio_mask_fn = HdfStorageArea._require_rasterio()
        terrain_path = Path(terrain_path)
        if not terrain_path.exists():
            raise FileNotFoundError(f"Terrain file not found: {terrain_path}")

        with rasterio.open(terrain_path) as src:
            terrain_data, _, cell_area = HdfStorageArea._masked_terrain_array(
                src, polygon, rasterio_mask_fn,
            )
            depths = float(elevation) - terrain_data
            valid_depths = depths[~np.isnan(depths) & (depths > 0)]
            return float(np.sum(valid_depths * cell_area))

    @staticmethod
    @log_call
    @standardize_input(file_type="geom_hdf")
    def compute_stage_storage_curve(
        hdf_path: Path,
        sa_name: str,
        elevation_interval: float = 5.0,
        min_elevation: Optional[float] = None,
        max_elevation: Optional[float] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        *,
        ras_object=None,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Compute a stage-storage curve from the storage-area terrain footprint.

        Parameters
        ----------
        hdf_path : Path
            Geometry HDF file path.
        sa_name : str
            Storage area name.
        elevation_interval : float
            Elevation step between volume samples (project vertical units).
        min_elevation, max_elevation : float, optional
            Override the automatic range derived from terrain statistics.
        progress_callback : callable, optional
            ``(current, total, message)`` progress reporter.
        ras_object : RasPrj, optional
            RAS object for multi-project workflows.

        Returns
        -------
        Tuple[pandas.DataFrame, dict]
            DataFrame columns are ``stage`` and ``storage``.  ``storage`` is in
            cubic project units.  Metadata is also copied to ``df.attrs``.
        """
        if elevation_interval <= 0:
            raise ValueError("elevation_interval must be greater than zero")

        try:
            if progress_callback:
                progress_callback(0, 100, "Reading storage area perimeter")

            polygon = HdfStorageArea._get_perimeter_polygon(
                hdf_path,
                sa_name,
                ras_object=ras_object,
            )
            if polygon is None:
                raise ValueError(f"Storage area not found in geometry HDF: {sa_name}")

            if progress_callback:
                progress_callback(10, 100, "Resolving terrain")

            terrain_path = HdfStorageArea.get_terrain_path_from_geom_hdf(
                hdf_path,
                ras_object=ras_object,
            )
            if terrain_path is None:
                raise ValueError(f"Terrain file not found from geometry HDF: {hdf_path}")

            if progress_callback:
                progress_callback(20, 100, "Extracting terrain statistics")

            stats = HdfStorageArea._extract_terrain_stats_in_polygon(terrain_path, polygon)

            if min_elevation is None:
                min_elevation = stats["min_interior"]
            if max_elevation is None:
                max_elevation = stats["max_perimeter"]
            if max_elevation < min_elevation:
                raise ValueError(
                    f"max_elevation must be >= min_elevation: {max_elevation} < {min_elevation}"
                )

            elevations = np.arange(
                float(min_elevation),
                float(max_elevation) + (float(elevation_interval) * 0.5),
                float(elevation_interval),
            )
            if elevations.size == 0:
                elevations = np.asarray([float(min_elevation)], dtype="float64")

            if progress_callback:
                progress_callback(30, 100, f"Computing {len(elevations)} volumes")

            rows = []
            total = len(elevations)
            for idx, elev in enumerate(elevations, start=1):
                volume = HdfStorageArea.compute_volume_below_elevation(
                    terrain_path,
                    polygon,
                    float(elev),
                )
                rows.append({"stage": float(elev), "storage": float(volume)})
                if progress_callback:
                    percent = 30 + int(70 * idx / max(total, 1))
                    progress_callback(percent, 100, f"Computed volume {idx}/{total}")

            df = pd.DataFrame(rows, columns=["stage", "storage"])
            metadata: Dict[str, Any] = {
                "storage_area_name": sa_name,
                "terrain_path": str(terrain_path),
                "min_terrain_elev": stats["min_interior"],
                "max_terrain_elev": stats["max_interior"],
                "mean_terrain_elev": stats["mean_interior"],
                "min_perimeter_elev": stats["min_perimeter"],
                "max_perimeter_elev": stats["max_perimeter"],
                "storage_area_acres": float(polygon.area) / HdfStorageArea._ACRE_SQFT,
                "num_elevation_points": int(len(elevations)),
                "elevation_interval": float(elevation_interval),
                "valid_cell_count": stats["valid_cell_count"],
                "cell_area": stats["cell_area"],
                "storage_units": "cubic project units",
            }
            df.attrs.update(metadata)
            df.attrs["storage_area"] = sa_name

            if progress_callback:
                progress_callback(100, 100, "Complete")

            return df, metadata

        except (FileNotFoundError, ValueError):
            raise
        except Exception as e:
            logger.error(
                "Error computing stage-storage curve for SA '%s' in %s: %s",
                sa_name, hdf_path, e,
            )
            raise IOError(f"Failed to compute stage-storage curve: {e}") from e

    @staticmethod
    @log_call
    @standardize_input(file_type="geom_hdf")
    def get_storage_area_for_breach_structure(
        hdf_path: Path,
        breach_structure_id: str,
        *,
        ras_object=None,
    ) -> Optional[str]:
        """
        Return the upstream SA/2D area associated with a structure.

        If no upstream SA/2D value exists, the downstream SA/2D field is used as
        a fallback because many lateral connections store the storage area there.
        """

        def clean(value: Any) -> str:
            decoded = HdfStorageArea._decode_hdf_value(value)
            if decoded is None:
                return ""
            return str(decoded).strip()

        def norm(value: str) -> str:
            return " ".join(value.lower().split())

        target = norm(str(breach_structure_id))
        if not target:
            return None

        with h5py.File(hdf_path, "r") as hdf_file:
            attr_path = "Geometry/Structures/Attributes"
            if attr_path not in hdf_file:
                return None

            attributes = hdf_file[attr_path][()]
            field_names = attributes.dtype.names or ()
            if not field_names:
                return None

            match_fields = [
                "Connection",
                "Groupname",
                "Node Name",
                "Description",
                "SNN ID",
            ]
            sa_fields = [
                "US SA/2D",
                "US SA/2D Area",
                "Upstream SA/2D",
                "SA Connection",
                "DS SA/2D",
                "DS SA/2D Area",
                "Downstream SA/2D",
            ]

            for row in attributes:
                candidates = [
                    clean(row[field])
                    for field in match_fields
                    if field in field_names
                ]
                if {"River", "Reach", "RS"} <= set(field_names):
                    river = clean(row["River"])
                    reach = clean(row["Reach"])
                    rs = clean(row["RS"])
                    if river or reach or rs:
                        candidates.extend(
                            [
                                f"{river}, {reach} ({rs})".strip(),
                                f"{river}/{reach}/{rs}".strip("/"),
                            ]
                        )

                normalized = [norm(candidate) for candidate in candidates if candidate]
                if target not in normalized:
                    continue

                for field in sa_fields:
                    if field not in field_names:
                        continue
                    sa_name = clean(row[field])
                    if sa_name and sa_name.lower() != "none":
                        return sa_name

        return None
