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
    _VOLUME_ELEVATION_INFO = "Volume Elevation Info"
    _VOLUME_ELEVATION_VALUES = "Volume Elevation Values"
    _ACRE_SQFT = 43560.0
    _ACRE_SQM = 4046.8564224

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
    def _compute_volume_below_elevation_from_terrain(
        terrain_path: Path,
        polygon: Any,
        elevation: float,
    ) -> float:
        """Compute storage volume without public API logging around each sample."""
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
    def _log_missing_volume_elevation_curve(
        hdf_path: Path,
        sa_name: str,
        reason: str,
    ) -> None:
        info_path = (
            f"{HdfStorageArea._STORAGE_AREA_PATH}/"
            f"{HdfStorageArea._VOLUME_ELEVATION_INFO}"
        )
        values_path = (
            f"{HdfStorageArea._STORAGE_AREA_PATH}/"
            f"{HdfStorageArea._VOLUME_ELEVATION_VALUES}"
        )
        logger.error(
            "Volume-elevation curve data unavailable for storage area '%s' "
            "in %s (%s). These datasets are created by the HEC-RAS geometry "
            "preprocessor; run the geometry preprocessor first if you need "
            "this curve. Required HDF datasets: '%s' and '%s'.",
            sa_name,
            hdf_path.name,
            reason,
            info_path,
            values_path,
        )
        logger.debug(
            "Volume-elevation curve request failed for storage area '%s' in %s",
            sa_name,
            hdf_path,
        )

    @staticmethod
    def _get_storage_unit_conversion(hdf_path: Path) -> Dict[str, Any]:
        """Return metadata for converting terrain-integrated volume to storage units."""
        hdf_path = Path(hdf_path)
        units_system_raw = None
        si_units_raw = None

        try:
            with h5py.File(hdf_path, "r") as hdf_file:
                units_system_raw = hdf_file.attrs.get("Units System")
                geom_group = hdf_file.get("Geometry")
                if geom_group is not None:
                    si_units_raw = geom_group.attrs.get("SI Units")
        except Exception as exc:
            logger.debug(
                "Unable to read storage unit metadata from %s: %s",
                hdf_path,
                exc,
            )

        units_system_text = str(
            HdfStorageArea._decode_hdf_value(units_system_raw) or ""
        ).strip()
        si_units_text = str(
            HdfStorageArea._decode_hdf_value(si_units_raw) or ""
        ).strip().lower()
        units_system_key = units_system_text.lower()

        if si_units_text in {"false", "0", "no"}:
            return {
                "units_system": "US Customary",
                "storage_units": "acre-ft",
                "raw_storage_units": "cubic ft",
                "storage_conversion_factor": 1.0 / HdfStorageArea._ACRE_SQFT,
                "area_units": "sq ft",
                "area_to_acres_factor": 1.0 / HdfStorageArea._ACRE_SQFT,
            }

        if si_units_text in {"true", "1", "yes"}:
            return {
                "units_system": "SI",
                "storage_units": "m^3",
                "raw_storage_units": "m^3",
                "storage_conversion_factor": 1.0,
                "area_units": "m^2",
                "area_to_acres_factor": 1.0 / HdfStorageArea._ACRE_SQM,
            }

        if units_system_key in {"us customary", "customary", "english"}:
            return {
                "units_system": "US Customary",
                "storage_units": "acre-ft",
                "raw_storage_units": "cubic ft",
                "storage_conversion_factor": 1.0 / HdfStorageArea._ACRE_SQFT,
                "area_units": "sq ft",
                "area_to_acres_factor": 1.0 / HdfStorageArea._ACRE_SQFT,
            }

        if units_system_key in {"si", "metric"}:
            return {
                "units_system": "SI",
                "storage_units": "m^3",
                "raw_storage_units": "m^3",
                "storage_conversion_factor": 1.0,
                "area_units": "m^2",
                "area_to_acres_factor": 1.0 / HdfStorageArea._ACRE_SQM,
            }

        return {
            "units_system": "unknown",
            "storage_units": "cubic project units",
            "raw_storage_units": "cubic project units",
            "storage_conversion_factor": 1.0,
            "area_units": "square project units",
            "area_to_acres_factor": None,
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
                logger.debug(
                    "Storage areas group '%s' not found in %s.",
                    HdfStorageArea._STORAGE_AREA_PATH,
                    hdf_path.name,
                )
                return []
            sa_group = hdf_file[HdfStorageArea._STORAGE_AREA_PATH]
            if "Attributes" not in sa_group:
                logger.debug(
                    "Storage area attributes not found in %s (%s).",
                    hdf_path.name,
                    HdfStorageArea._STORAGE_AREA_PATH,
                )
                return []

            attrs = sa_group["Attributes"][()]
            if not getattr(attrs.dtype, "names", None) or "Name" not in attrs.dtype.names:
                logger.debug(
                    "Storage area attributes in %s do not include a Name field.",
                    hdf_path.name,
                )
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
                logger.debug(
                    "Storage areas group '%s' not found in %s.",
                    HdfStorageArea._STORAGE_AREA_PATH,
                    hdf_path.name,
                )
                return {}

            sa_group = hdf_file[HdfStorageArea._STORAGE_AREA_PATH]
            if "Attributes" not in sa_group:
                logger.debug(
                    "Storage area attributes not found in %s (%s).",
                    hdf_path.name,
                    HdfStorageArea._STORAGE_AREA_PATH,
                )
                return {}

            attrs = sa_group["Attributes"][()]
            names = attrs.dtype.names or ()
            if "Name" not in names:
                logger.debug(
                    "Storage area attributes in %s do not include a Name field.",
                    hdf_path.name,
                )
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

        logger.debug(
            "Storage area '%s' not found in %s.",
            sa_name,
            hdf_path.name,
        )
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
                    logger.debug(
                        "Storage areas group '%s' not found in %s.",
                        HdfStorageArea._STORAGE_AREA_PATH,
                        hdf_path.name,
                    )
                    return empty
                sa_group = hdf_file[HdfStorageArea._STORAGE_AREA_PATH]

                if "Attributes" not in sa_group:
                    logger.debug(
                        "Storage area attributes not found in %s (%s).",
                        hdf_path.name,
                        HdfStorageArea._STORAGE_AREA_PATH,
                    )
                    return empty
                attrs = sa_group["Attributes"][()]
                field_names = getattr(attrs.dtype, "names", None)
                if not field_names or "Name" not in field_names:
                    logger.debug(
                        "Storage area attributes in %s do not include a Name field.",
                        hdf_path.name,
                    )
                    return empty

                sa_index = None
                for idx, row in enumerate(attrs):
                    name = str(HdfStorageArea._decode_hdf_value(row["Name"])).strip()
                    if name == str(sa_name).strip():
                        sa_index = idx
                        break
                if sa_index is None:
                    logger.debug(
                        "Storage area '%s' not found in %s.",
                        sa_name,
                        hdf_path.name,
                    )
                    return empty

                if (
                    HdfStorageArea._VOLUME_ELEVATION_INFO not in sa_group
                    or HdfStorageArea._VOLUME_ELEVATION_VALUES not in sa_group
                ):
                    missing = [
                        dataset
                        for dataset in (
                            HdfStorageArea._VOLUME_ELEVATION_INFO,
                            HdfStorageArea._VOLUME_ELEVATION_VALUES,
                        )
                        if dataset not in sa_group
                    ]
                    HdfStorageArea._log_missing_volume_elevation_curve(
                        hdf_path,
                        sa_name,
                        "missing " + ", ".join(missing),
                    )
                    return empty

                info = sa_group[HdfStorageArea._VOLUME_ELEVATION_INFO][()]
                start, count = int(info[sa_index, 0]), int(info[sa_index, 1])
                if count == 0:
                    HdfStorageArea._log_missing_volume_elevation_curve(
                        hdf_path,
                        sa_name,
                        "zero points",
                    )
                    return empty

                values = sa_group[HdfStorageArea._VOLUME_ELEVATION_VALUES][
                    start:start + count
                ]
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
            logger.error(
                "Error reading volume-elevation curve for SA '%s' from %s "
                "(%s): %s",
                sa_name,
                hdf_path,
                HdfStorageArea._STORAGE_AREA_PATH,
                e,
            )
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
                logger.debug("Geometry group not found in %s.", hdf_path.name)
                return None

            terrain_raw = geom_group.attrs.get("Terrain Filename")
            if terrain_raw is None:
                terrain_raw = hdf_file.attrs.get("Terrain Filename")
            if terrain_raw is None:
                logger.debug("Terrain Filename attribute not found in %s.", hdf_path.name)
                return None

        terrain_text = str(HdfStorageArea._decode_hdf_value(terrain_raw)).strip()
        if not terrain_text:
            logger.debug("Terrain Filename attribute is empty in %s.", hdf_path.name)
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

        logger.debug(
            "Terrain referenced by %s was not found. Checked candidate path(s): %s",
            hdf_path.name,
            ", ".join(str(candidate) for candidate in candidates),
        )
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
        return HdfStorageArea._compute_volume_below_elevation_from_terrain(
            terrain_path,
            polygon,
            elevation,
        )

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
            acre-feet for US Customary projects, cubic meters for SI projects,
            or cubic project units when the HDF unit system is unknown.
            Metadata is also copied to ``df.attrs``.
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
                raise ValueError(
                    "Terrain file referenced by "
                    f"{hdf_path.name} for storage area '{sa_name}' was not found."
                )

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

            unit_info = HdfStorageArea._get_storage_unit_conversion(hdf_path)
            storage_conversion_factor = float(unit_info["storage_conversion_factor"])

            rows = []
            total = len(elevations)
            for idx, elev in enumerate(elevations, start=1):
                raw_volume = HdfStorageArea._compute_volume_below_elevation_from_terrain(
                    terrain_path,
                    polygon,
                    float(elev),
                )
                rows.append(
                    {
                        "stage": float(elev),
                        "storage": float(raw_volume) * storage_conversion_factor,
                    }
                )
                if progress_callback:
                    percent = 30 + int(70 * idx / max(total, 1))
                    progress_callback(percent, 100, f"Computed volume {idx}/{total}")

            df = pd.DataFrame(rows, columns=["stage", "storage"])
            area_to_acres_factor = unit_info["area_to_acres_factor"]
            storage_area = float(polygon.area)
            metadata: Dict[str, Any] = {
                "storage_area_name": sa_name,
                "terrain_path": str(terrain_path),
                "min_terrain_elev": stats["min_interior"],
                "max_terrain_elev": stats["max_interior"],
                "mean_terrain_elev": stats["mean_interior"],
                "min_perimeter_elev": stats["min_perimeter"],
                "max_perimeter_elev": stats["max_perimeter"],
                "storage_area_area": storage_area,
                "storage_area_area_units": unit_info["area_units"],
                "storage_area_acres": (
                    storage_area * float(area_to_acres_factor)
                    if area_to_acres_factor is not None
                    else None
                ),
                "num_elevation_points": int(len(elevations)),
                "elevation_interval": float(elevation_interval),
                "valid_cell_count": stats["valid_cell_count"],
                "cell_area": stats["cell_area"],
            }
            metadata.update(unit_info)
            df.attrs.update(metadata)
            df.attrs["storage_area"] = sa_name

            if progress_callback:
                progress_callback(100, 100, "Complete")

            return df, metadata

        except (FileNotFoundError, ValueError):
            raise
        except Exception as e:
            logger.debug(
                "Error computing stage-storage curve for SA '%s' in %s: %s",
                sa_name, hdf_path, e, exc_info=True,
            )
            raise IOError(
                f"Failed to compute stage-storage curve for storage area "
                f"'{sa_name}' in {hdf_path.name}: {e}"
            ) from e

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
