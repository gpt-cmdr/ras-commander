"""
HdfLandCover - Final Manning's N Computation from Land Cover and Calibration Regions

This module computes the resolved per-pixel or per-cell Manning's n values
accounting for all override layers:
1. Base land cover table (from land cover .hdf file)
2. Calibration region overrides (from geometry HDF)
3. Preprocessed per-cell values (from geometry HDF after preprocessing)

Two approaches are provided:
- Cell-based: Read preprocessed per-cell values from geometry HDF (fast, authoritative)
- Raster-based: Compute from source layers with full rasterization (exportable, no preprocessing needed)

All methods are static. Do not instantiate.

Platform:
    Cross-platform for HDF reading; raster export requires rasterio.

Example:
    from ras_commander.hdf import HdfLandCover

    # Read preprocessed per-cell Manning's n (what HEC-RAS uses)
    df = HdfLandCover.get_preprocessed_mannings_n("project.g01.hdf")

    # Read the calibration table (base + all region overrides)
    cal = HdfLandCover.get_mannings_calibration_table("project.g01.hdf")
"""

import logging
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import h5py
import numpy as np
import pandas as pd

from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils

logger = get_logger(__name__)


class HdfLandCover:
    """
    Final Manning's n computation from land cover, base values, and calibration regions.

    Provides two access patterns:
    - **Preprocessed cell values**: Read the exact per-cell n-values that HEC-RAS
      computed during geometry preprocessing (fast, authoritative).
    - **Raster composition**: Combine base land cover raster + calibration table +
      region polygons to produce the full-resolution Final Manning's N raster
      (exportable, enables before/after comparison).

    All methods are static - call directly without instantiation:
        HdfLandCover.get_preprocessed_mannings_n("project.g01.hdf")
    """

    # ---- Phase 1: Cell-Level Readers (preprocessed values) ----

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_preprocessed_mannings_n(
        hdf_path: Path,
        mesh_name: Optional[str] = None,
        ras_object: Any = None
    ) -> pd.DataFrame:
        """
        Read preprocessed per-cell Manning's n from geometry HDF.

        Returns the exact per-cell n-values that HEC-RAS uses in computation,
        from ``/Geometry/2D Flow Areas/{mesh}/Cells Center Manning's n``.
        These values reflect the full override chain (base + calibration regions)
        as resolved during geometry preprocessing.

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
                Resolved via @standardize_input to the geometry HDF file.
            mesh_name: Specific 2D flow area name. If None, reads all areas.
            ras_object: Optional RasPrj object for path resolution.

        Returns:
            DataFrame with columns: mesh_name, cell_id, mannings_n

        Example:
            >>> df = HdfLandCover.get_preprocessed_mannings_n("01")  # by plan number
            >>> df = HdfLandCover.get_preprocessed_mannings_n("project.g01.hdf")  # by path
        """
        results = []

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                areas_path = "Geometry/2D Flow Areas"
                if areas_path not in hdf_file:
                    logger.warning(f"No 2D Flow Areas found in {hdf_path}")
                    return pd.DataFrame(columns=['mesh_name', 'cell_id', 'mannings_n'])

                areas_group = hdf_file[areas_path]

                for area_name in areas_group:
                    # Skip datasets (Attributes, Cell Info, etc.) - only process groups (mesh perimeters)
                    if not isinstance(areas_group[area_name], h5py.Group):
                        continue
                    if mesh_name is not None and area_name != mesh_name:
                        continue

                    area = areas_group[area_name]
                    mann_path = "Cells Center Manning's n"

                    if mann_path not in area:
                        logger.debug(f"No Manning's n data for mesh '{area_name}'")
                        continue

                    n_values = area[mann_path][()]
                    n_cells = len(n_values)

                    area_df = pd.DataFrame({
                        'mesh_name': [area_name] * n_cells,
                        'cell_id': range(n_cells),
                        'mannings_n': n_values.astype(float),
                    })
                    results.append(area_df)

        except Exception as e:
            logger.error(f"Error reading preprocessed Manning's n from {hdf_path}: {e}")
            return pd.DataFrame(columns=['mesh_name', 'cell_id', 'mannings_n'])

        if not results:
            return pd.DataFrame(columns=['mesh_name', 'cell_id', 'mannings_n'])

        return pd.concat(results, ignore_index=True)

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_mannings_calibration_table(
        hdf_path: Path,
        ras_object: Any = None
    ) -> Optional[pd.DataFrame]:
        """
        Read the Manning's n calibration table from geometry HDF.

        Returns the full calibration table showing base n-values and per-region
        overrides. Each row is a land cover class, each column after the first
        two is a calibration region. Values > 0 indicate an override; 0 means
        use the base value.

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
            ras_object: Optional RasPrj object for path resolution.

        Returns:
            DataFrame with columns: Land Cover Name, Base Manning's n Value,
            plus one column per calibration region. None if not found.

        Example:
            >>> cal = HdfLandCover.get_mannings_calibration_table("01")
        """

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                table_path = "Geometry/Land Cover (Manning's n)/Calibration Table"
                if table_path not in hdf_file:
                    logger.warning(f"No Manning's n calibration table in {hdf_path}")
                    return None

                data = hdf_file[table_path][()]

                df_dict = {}
                for field_name in data.dtype.names:
                    values = data[field_name]
                    if values.dtype.kind == 'S':
                        values = [v.decode('utf-8').strip() for v in values]
                    df_dict[field_name] = values

                return pd.DataFrame(df_dict)

        except Exception as e:
            logger.error(f"Error reading calibration table from {hdf_path}: {e}")
            return None

    @staticmethod
    @log_call
    def build_landcover_depth_roughness_curves(
        landcover_hdf_path: Union[str, Path],
        depths: List[float],
        mannings_n_func: Callable[[float, float, str], float],
    ) -> pd.DataFrame:
        """
        Build depth-varying Manning's n curves from a land-cover sidecar HDF.

        Parameters
        ----------
        landcover_hdf_path : Union[str, Path]
            Path to the land-cover HDF containing ``IDs``, ``Names``, and
            ``ManningsN`` datasets.
        depths : List[float]
            Depth values used to evaluate ``mannings_n_func``.
        mannings_n_func : Callable
            Function ``(depth, base_n, class_name) -> n``.

        Returns
        -------
        pd.DataFrame
            Columns: ``pixel_value``, ``class_name``, ``depth``,
            ``base_mannings_n``, and ``mannings_n``.
        """
        landcover_hdf_path = Path(landcover_hdf_path)
        rows = []
        nodata_threshold = np.finfo(np.float32).max * 0.5

        with h5py.File(landcover_hdf_path, "r") as hdf_file:
            ids = hdf_file["IDs"][()]
            names = hdf_file["Names"][()]
            mannings_n = hdf_file["ManningsN"][()]

        for pixel_value, raw_name, base_n in zip(ids, names, mannings_n):
            class_name = str(HdfUtils.convert_ras_hdf_value(raw_name)).strip()
            base_n = float(base_n)
            if not np.isfinite(base_n) or base_n >= nodata_threshold:
                continue
            if class_name.lower() == "nodata":
                continue

            for depth in depths:
                depth = float(depth)
                rows.append(
                    {
                        "pixel_value": int(pixel_value),
                        "class_name": class_name,
                        "depth": depth,
                        "base_mannings_n": base_n,
                        "mannings_n": float(
                            mannings_n_func(depth, base_n, class_name)
                        ),
                    }
                )

        return pd.DataFrame(rows)

    # ---- Phase 2: Component Readers ----

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_mannings_region_polygons(
        hdf_path: Path,
        ras_object: Any = None
    ) -> 'gpd.GeoDataFrame':
        """
        Read Manning's n calibration region polygons from geometry HDF.

        Returns the polygon geometries used for spatial override of Manning's n
        values. Each polygon defines a calibration region that can override
        base n-values for specific land cover classes.

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
            ras_object: Optional RasPrj object for path resolution.

        Returns:
            GeoDataFrame with columns: region_id, Name, 2D_Area_Name, geometry

        Example:
            >>> regions = HdfLandCover.get_mannings_region_polygons("01")
        """
        import geopandas as gpd
        from shapely.geometry import Polygon, MultiPolygon

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                lc_path = "Geometry/Land Cover (Manning's n)"
                if lc_path not in hdf_file:
                    logger.warning(f"No Land Cover (Manning's n) group in {hdf_path}")
                    return gpd.GeoDataFrame()

                lc_group = hdf_file[lc_path]

                if ("Polygon Info" not in lc_group or
                    "Attributes" not in lc_group or
                    "Polygon Points" not in lc_group):
                    logger.warning(f"Missing polygon datasets in {lc_path}")
                    return gpd.GeoDataFrame()

                attrs = lc_group["Attributes"][()]
                names = np.vectorize(HdfUtils.convert_ras_string)(attrs["Name"])

                area_names = None
                if "2D Area Name" in attrs.dtype.names:
                    area_names = np.vectorize(HdfUtils.convert_ras_string)(attrs["2D Area Name"])

                geoms = []
                for pnt_start, pnt_cnt, part_start, part_cnt in lc_group["Polygon Info"][()]:
                    points = lc_group["Polygon Points"][()][pnt_start:pnt_start + pnt_cnt]
                    if part_cnt == 1:
                        geoms.append(Polygon(points))
                    elif "Polygon Parts" not in lc_group:
                        logger.warning("Multi-part polygon but 'Polygon Parts' dataset missing")
                        geoms.append(Polygon(points))
                    else:
                        parts = lc_group["Polygon Parts"][()][part_start:part_start + part_cnt]
                        rings = [points[ps:ps + pc] for ps, pc in parts]
                        if len(rings) == 1:
                            geoms.append(Polygon(rings[0]))
                        else:
                            # First ring is exterior, rest are holes
                            geoms.append(Polygon(rings[0], rings[1:]))

                data = {
                    "region_id": range(len(names)),
                    "Name": names,
                    "geometry": geoms,
                }
                if area_names is not None:
                    data["2D_Area_Name"] = area_names

                return gpd.GeoDataFrame(
                    data,
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file),
                )

        except Exception as e:
            logger.error(f"Error reading Manning's region polygons from {hdf_path}: {e}")
            return gpd.GeoDataFrame()

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_mannings_region_cell_mapping(
        hdf_path: Path,
        ras_object: Any = None
    ) -> Optional[pd.DataFrame]:
        """
        Read the cell-to-region mapping for Manning's n calibration regions.

        Returns which cells fall within which calibration regions, from the
        preprocessed datasets in the geometry HDF.

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
            ras_object: Optional RasPrj object for path resolution.

        Returns:
            DataFrame with columns: region_id, cell_index.
            None if datasets not found.
        """

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                cells_path = "Geometry/Land Cover (Manning's n)/Internal Cells"
                if cells_path not in hdf_file:
                    return None

                data = hdf_file[cells_path][()]
                return pd.DataFrame({
                    'region_id': data['Region ID'],
                    'cell_index': data['Cell Index'],
                })

        except Exception as e:
            logger.error(f"Error reading region cell mapping from {hdf_path}: {e}")
            return None

    @staticmethod
    @log_call
    def get_landcover_raster_map(
        landcover_hdf_path: Union[str, Path],
        ras_object: Any = None
    ) -> Optional[pd.DataFrame]:
        """
        Read the raster classification map from a land cover .hdf file.

        Returns the mapping of integer pixel values to land cover class names
        and their associated Manning's n values.

        Reads ``//Raster Map`` and ``//Variables`` from the land cover HDF.

        Args:
            landcover_hdf_path: Path to land cover HDF file
                (from rasmap_df['landcover_hdf_path'])
            ras_object: Optional RasPrj object for path resolution.

        Returns:
            DataFrame with columns: pixel_value, class_name, mannings_n.
            None if file cannot be read.

        Example:
            >>> rmap = HdfLandCover.get_landcover_raster_map("LandCover.hdf")
            >>> print(rmap[['class_name', 'mannings_n']].head())
        """
        landcover_hdf_path = Path(landcover_hdf_path)

        try:
            with h5py.File(landcover_hdf_path, 'r') as hdf_file:
                # Read raster map: pixel_value -> class_name
                # HDF path may be "Raster Map" or "//Raster Map" depending on version
                rmap_path = None
                for candidate in ["Raster Map", "//Raster Map"]:
                    if candidate in hdf_file:
                        rmap_path = candidate
                        break
                if rmap_path is None:
                    logger.warning(f"No Raster Map found in {landcover_hdf_path}")
                    return None

                rmap_data = hdf_file[rmap_path][()]
                class_names = [HdfUtils.convert_ras_string(n) for n in rmap_data['Name']]
                pixel_ids = rmap_data['ID'].tolist()

                # Read variables: class_name -> ManningsN
                vars_path = None
                for candidate in ["Variables", "//Variables"]:
                    if candidate in hdf_file:
                        vars_path = candidate
                        break
                if vars_path is None:
                    logger.warning(f"No Variables found in {landcover_hdf_path}")
                    return None

                vars_data = hdf_file[vars_path][()]
                var_names = [HdfUtils.convert_ras_string(n) for n in vars_data['Name']]

                mannings_n = {}
                if 'ManningsN' in vars_data.dtype.names:
                    for i, name in enumerate(var_names):
                        mannings_n[name] = float(vars_data['ManningsN'][i])

                # Build mapping
                rows = []
                for pid, cname in zip(pixel_ids, class_names):
                    rows.append({
                        'pixel_value': int(pid),
                        'class_name': cname,
                        'mannings_n': mannings_n.get(cname, np.nan),
                    })

                return pd.DataFrame(rows)

        except Exception as e:
            logger.error(f"Error reading land cover raster map from {landcover_hdf_path}: {e}")
            return None

    @staticmethod
    @log_call
    def get_classification_polygons(
        landcover_hdf_path: Union[str, Path],
        ras_object: Any = None,
    ) -> 'gpd.GeoDataFrame':
        """
        Read classification polygon overrides from a land-cover sidecar HDF.

        Args:
            landcover_hdf_path: Path to a land-cover HDF file.
            ras_object: Optional RasPrj object for API consistency.

        Returns:
            GeoDataFrame with ``polygon_index``, ``class_name``, and geometry.
        """
        from .. import _land_classification_helper as _lch

        return _lch.list_land_classification_polygons(landcover_hdf_path)

    @staticmethod
    def _detect_sidecar_format(
        hdf_path: Union[str, Path]
    ) -> str:
        """
        Detect land cover sidecar HDF format version.

        Returns:
            'v5' -- Has IDs, ManningsN, Names flat arrays
            'v6_0' -- Has Raster Map with ManningsN column + Variables
            'v6_modern' -- Has Raster Map + Variables, no ManningsN in Raster Map
        """
        hdf_path = Path(hdf_path)

        with h5py.File(hdf_path, 'r') as hdf_file:
            if all(key in hdf_file for key in ('IDs', 'ManningsN', 'Names')):
                return 'v5'

            raster_map_path = None
            for candidate in ['Raster Map', '//Raster Map']:
                if candidate in hdf_file:
                    raster_map_path = candidate
                    break

            if raster_map_path is not None:
                raster_map_fields = hdf_file[raster_map_path].dtype.names or ()
                if 'ManningsN' in raster_map_fields:
                    return 'v6_0'
                return 'v6_modern'

            raise ValueError(f"Unknown sidecar format: {list(hdf_file.keys())}")

    @staticmethod
    @log_call
    def set_landcover_raster_map(
        hdf_path: Union[str, Path],
        class_mapping: Dict[str, float],
        ras_object: Any = None,
    ) -> dict:
        """
        Write Manning's N values to a land cover sidecar HDF file.

        Creates a .bak backup before any modification. Validates that all
        class names in class_mapping exist in the sidecar before writing.

        Args:
            hdf_path: Path to the land cover sidecar HDF file
            class_mapping: Dict mapping class name -> Manning's N value
                Example: {"Open Water": 0.020, "Forest": 0.120}
            ras_object: Optional RasPrj object

        Returns:
            dict with keys:
                'changed': int -- number of classes modified
                'unchanged': int -- number of classes not in mapping
                'format': str -- detected format version
                'backup_path': Path -- path to .bak file
                'class_details': list of dicts with per-class info

        Raises:
            FileNotFoundError: If hdf_path doesn't exist
            ValueError: If any class name in mapping not found in sidecar
            ValueError: If unknown sidecar format detected
        """
        hdf_path = Path(hdf_path)
        if not hdf_path.exists():
            raise FileNotFoundError(f"Land cover HDF not found: {hdf_path}")

        normalized_mapping = {
            str(class_name): float(mannings_n)
            for class_name, mannings_n in class_mapping.items()
        }

        backup_path = Path(str(hdf_path) + '.bak')
        shutil.copy2(hdf_path, backup_path)
        logger.info(f"Created backup for land cover sidecar: {backup_path}")

        sidecar_format = HdfLandCover._detect_sidecar_format(hdf_path)
        class_names: List[str] = []
        current_values: List[float] = []
        variables_path = None
        raster_map_path = None
        raster_map_names: List[str] = []

        with h5py.File(hdf_path, 'r') as hdf_file:
            if sidecar_format == 'v5':
                class_names = [
                    str(HdfUtils.convert_ras_string(name)).strip()
                    for name in hdf_file['Names'][()]
                ]
                current_values = [
                    float(value) for value in hdf_file['ManningsN'][()]
                ]
            else:
                for candidate in ['Variables', '//Variables']:
                    if candidate in hdf_file:
                        variables_path = candidate
                        break
                if variables_path is None:
                    raise ValueError(
                        f"Detected {sidecar_format} sidecar without Variables "
                        f"dataset: {hdf_path}"
                    )

                variables_data = hdf_file[variables_path][()]
                variable_fields = variables_data.dtype.names or ()
                if 'Name' not in variable_fields or 'ManningsN' not in variable_fields:
                    raise ValueError(
                        f"Variables dataset missing Name or ManningsN fields: "
                        f"{variables_path}"
                    )

                class_names = [
                    str(HdfUtils.convert_ras_string(row['Name'])).strip()
                    for row in variables_data
                ]
                current_values = [
                    float(row['ManningsN']) for row in variables_data
                ]

                if sidecar_format == 'v6_0':
                    for candidate in ['Raster Map', '//Raster Map']:
                        if candidate in hdf_file:
                            raster_map_path = candidate
                            break
                    if raster_map_path is None:
                        raise ValueError(
                            f"Detected v6_0 sidecar without Raster Map dataset: "
                            f"{hdf_path}"
                        )

                    raster_map_data = hdf_file[raster_map_path][()]
                    raster_map_fields = raster_map_data.dtype.names or ()
                    if 'Name' not in raster_map_fields or 'ManningsN' not in raster_map_fields:
                        raise ValueError(
                            f"Raster Map dataset missing Name or ManningsN "
                            f"fields: {raster_map_path}"
                        )

                    raster_map_names = [
                        str(HdfUtils.convert_ras_string(row['Name'])).strip()
                        for row in raster_map_data
                    ]

        seen_names = set()
        duplicate_names = set()
        for class_name in class_names:
            if class_name in seen_names:
                duplicate_names.add(class_name)
            seen_names.add(class_name)
        if duplicate_names:
            duplicates = ', '.join(sorted(duplicate_names))
            raise ValueError(
                f"Duplicate land cover class names found in sidecar: {duplicates}"
            )

        missing_classes = sorted(
            set(normalized_mapping) - set(class_names)
        )
        if missing_classes:
            missing_str = ', '.join(missing_classes)
            raise ValueError(
                f"Class names not found in sidecar: {missing_str}"
            )

        if sidecar_format == 'v6_0':
            seen_raster_names = set()
            duplicate_raster_names = set()
            for class_name in raster_map_names:
                if class_name in seen_raster_names:
                    duplicate_raster_names.add(class_name)
                seen_raster_names.add(class_name)
            if duplicate_raster_names:
                duplicates = ', '.join(sorted(duplicate_raster_names))
                raise ValueError(
                    f"Duplicate Raster Map class names found in sidecar: "
                    f"{duplicates}"
                )

            missing_raster_map_classes = sorted(
                set(normalized_mapping) - set(raster_map_names)
            )
            if missing_raster_map_classes:
                missing_str = ', '.join(missing_raster_map_classes)
                raise ValueError(
                    f"Class names not found in Raster Map dataset: {missing_str}"
                )

        if not normalized_mapping:
            logger.debug(f"No land cover classes supplied for update in {hdf_path}")

        name_to_index = {
            class_name: idx for idx, class_name in enumerate(class_names)
        }
        changed = len(normalized_mapping)

        if normalized_mapping:
            if sidecar_format == 'v5':
                with h5py.File(hdf_path, 'r+') as hdf_file:
                    mannings = hdf_file['ManningsN'][()]
                    for class_name, new_n in normalized_mapping.items():
                        idx = name_to_index[class_name]
                        old_n = float(mannings[idx])
                        mannings[idx] = new_n
                        logger.debug(
                            f"Updated '{class_name}' in {hdf_path.name} "
                            f"(v5): {old_n} -> {new_n}"
                        )
                    hdf_file['ManningsN'][()] = mannings

            elif sidecar_format == 'v6_0':
                with h5py.File(hdf_path, 'r+') as hdf_file:
                    if variables_path is None or raster_map_path is None:
                        raise ValueError(
                            "Variables or Raster Map dataset path not resolved "
                            "for v6_0 write"
                        )

                    variables = hdf_file[variables_path]
                    raster_map = hdf_file[raster_map_path]
                    raster_map_index = {
                        class_name: idx
                        for idx, class_name in enumerate(raster_map_names)
                    }

                    for class_name, new_n in normalized_mapping.items():
                        idx = name_to_index[class_name]
                        row = variables[idx]
                        old_n = float(row['ManningsN'])
                        row['ManningsN'] = new_n
                        variables[idx] = row

                        raster_idx = raster_map_index[class_name]
                        raster_row = raster_map[raster_idx]
                        raster_row['ManningsN'] = new_n
                        raster_map[raster_idx] = raster_row

                        logger.debug(
                            f"Updated '{class_name}' in {hdf_path.name} "
                            f"(v6_0 Variables + Raster Map): {old_n} -> {new_n}"
                        )

            elif sidecar_format == 'v6_modern':
                with h5py.File(hdf_path, 'r+') as hdf_file:
                    if variables_path is None:
                        raise ValueError(
                            "Variables dataset path not resolved for v6_modern "
                            "write"
                        )

                    variables = hdf_file[variables_path]
                    for class_name, new_n in normalized_mapping.items():
                        idx = name_to_index[class_name]
                        row = variables[idx]
                        old_n = float(row['ManningsN'])
                        row['ManningsN'] = new_n
                        variables[idx] = row
                        logger.debug(
                            f"Updated '{class_name}' in {hdf_path.name} "
                            f"(v6_modern Variables): {old_n} -> {new_n}"
                        )

        class_details = []
        for class_name, old_n in zip(class_names, current_values):
            new_n = float(normalized_mapping.get(class_name, old_n))
            class_details.append({
                'class_name': class_name,
                'old_mannings_n': old_n,
                'new_mannings_n': new_n,
                'changed': class_name in normalized_mapping,
                'value_changed': (
                    class_name in normalized_mapping and
                    not np.isclose(old_n, new_n)
                ),
            })

        actually_changed = sum(1 for d in class_details if d['value_changed'])
        logger.info(
            f"Completed land cover update for {hdf_path}: "
            f"format={sidecar_format}, changed={actually_changed}, "
            f"unchanged={len(class_names) - len(normalized_mapping)}"
        )

        return {
            'changed': actually_changed,
            'unchanged': len(class_names) - len(normalized_mapping),
            'format': sidecar_format,
            'backup_path': backup_path,
            'class_details': class_details,
        }

    # ---- Phase 3: Comparison and Statistics ----

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def compare_base_vs_calibrated(
        hdf_path: Path,
        ras_object: Any = None
    ) -> Optional[pd.DataFrame]:
        """
        Compare base Manning's n vs calibrated values per land cover class per region.

        Shows the effect of calibration: which regions override which classes,
        and by how much. Only includes entries where the region has a non-zero
        override (actual calibration changes).

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
            ras_object: Optional RasPrj object for path resolution.

        Returns:
            DataFrame with columns: land_cover_class, base_n, region_name,
            calibrated_n, delta_n, pct_change.
            None if calibration table not found.

        Example:
            >>> comp = HdfLandCover.compare_base_vs_calibrated("project.g01.hdf")
            >>> biggest = comp.nlargest(5, 'pct_change')
            >>> print(biggest[['land_cover_class', 'region_name', 'base_n', 'calibrated_n', 'pct_change']])
        """
        cal_table = HdfLandCover.get_mannings_calibration_table(hdf_path)
        if cal_table is None or len(cal_table) == 0:
            return None

        lc_col = "Land Cover Name"
        base_col = "Base Manning's n Value"

        if lc_col not in cal_table.columns or base_col not in cal_table.columns:
            logger.warning("Calibration table missing expected columns")
            return None

        region_cols = [c for c in cal_table.columns if c not in (lc_col, base_col)]

        rows = []
        for _, row in cal_table.iterrows():
            class_name = row[lc_col]
            base_n = float(row[base_col])

            for region_name in region_cols:
                cal_n = float(row[region_name])
                if cal_n > 0 and cal_n != base_n:
                    delta = cal_n - base_n
                    pct = (delta / base_n * 100) if base_n > 0 else float('inf')
                    rows.append({
                        'land_cover_class': class_name,
                        'base_n': base_n,
                        'region_name': region_name,
                        'calibrated_n': cal_n,
                        'delta_n': delta,
                        'pct_change': pct,
                    })

        if not rows:
            logger.debug("No calibration overrides found (all regions use base values)")
            return pd.DataFrame(columns=[
                'land_cover_class', 'base_n', 'region_name',
                'calibrated_n', 'delta_n', 'pct_change'
            ])

        return pd.DataFrame(rows)

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_preprocessed_mannings_stats(
        hdf_path: Path,
        mesh_name: Optional[str] = None,
        ras_object: Any = None
    ) -> pd.DataFrame:
        """
        Compute statistics on preprocessed per-cell Manning's n values.

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
            mesh_name: Specific 2D flow area. If None, computes for all.
            ras_object: Optional RasPrj object.

        Returns:
            DataFrame with columns: mesh_name, n_cells, min_n, max_n,
            mean_n, median_n, std_n

        Example:
            >>> stats = HdfLandCover.get_preprocessed_mannings_stats("project.g01.hdf")
            >>> print(stats)
        """
        df = HdfLandCover.get_preprocessed_mannings_n(hdf_path, mesh_name, ras_object)

        if len(df) == 0:
            return pd.DataFrame(columns=[
                'mesh_name', 'n_cells', 'min_n', 'max_n', 'mean_n', 'median_n', 'std_n'
            ])

        stats = df.groupby('mesh_name').agg(
            n_cells=('mannings_n', 'count'),
            min_n=('mannings_n', 'min'),
            max_n=('mannings_n', 'max'),
            mean_n=('mannings_n', 'mean'),
            median_n=('mannings_n', 'median'),
            std_n=('mannings_n', 'std'),
        ).reset_index()

        return stats

    # ---- Phase 3: Raster Composition ----

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def get_landcover_association(
        hdf_path: Path,
        ras_object: Any = None
    ) -> Optional[Path]:
        """
        Get the land cover HDF path associated with a geometry.

        Reads the ``Land Cover Filename`` attribute from the geometry HDF
        and resolves it to an absolute path. This is set via RASMapper's
        "Manage Associations" menu.

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
            ras_object: Optional RasPrj object.

        Returns:
            Absolute path to the land cover HDF file, or None if not found.
        """

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                geom_group = hdf_file.get('Geometry')
                if geom_group is None:
                    return None

                lc_attr = geom_group.attrs.get('Land Cover Filename')
                if lc_attr is None:
                    return None

                if isinstance(lc_attr, bytes):
                    lc_attr = lc_attr.decode('utf-8')

                lc_path = Path(lc_attr)
                if not lc_path.is_absolute():
                    lc_path = (hdf_path.parent / lc_path).resolve()

                if lc_path.exists():
                    return lc_path
                else:
                    logger.warning(f"Land cover file not found: {lc_path}")
                    return None

        except Exception as e:
            logger.error(f"Error reading land cover association from {hdf_path}: {e}")
            return None

    @staticmethod
    @log_call
    @standardize_input(file_type='geom_hdf')
    def compute_final_mannings_raster(
        hdf_path: Path,
        landcover_hdf_path: Optional[Union[str, Path]] = None,
        output_tif_path: Optional[Union[str, Path]] = None,
        ras_object: Any = None
    ) -> Optional[np.ndarray]:
        """
        Compute final Manning's n raster accounting for base + calibration overrides.

        Combines the base land cover raster with the calibration table and
        region polygons to produce the full-resolution Final Manning's N raster.
        This replicates what RASMapper's FinalNValueLayer computes internally.

        The land cover HDF is auto-resolved from the geometry's ``Land Cover Filename``
        attribute (set via RASMapper's Manage Associations menu), or can be overridden.

        Args:
            hdf_path: Geometry HDF path, plan number ("01"), or geometry number ("g01").
            landcover_hdf_path: Path to land cover HDF file. If None (default),
                auto-resolves from the geometry HDF's association attribute.
            ras_object: Optional RasPrj object for path resolution.
            output_tif_path: If provided, writes result to GeoTIFF.

        Returns:
            2D numpy array of final Manning's n values (same shape as land cover raster).
            None if inputs cannot be resolved.

        Example:
            >>> arr = HdfLandCover.compute_final_mannings_raster("01")  # auto-resolves LC
            >>> arr = HdfLandCover.compute_final_mannings_raster(
            ...     "project.g01.hdf",
            ...     landcover_hdf_path="custom_landcover.hdf",  # override
            ...     output_tif_path="final_mannings_n.tif"
            ... )
        """
        import rasterio
        from rasterio.features import rasterize as rio_rasterize

        # Resolve land cover HDF path from geometry association if not provided
        if landcover_hdf_path is None:
            landcover_hdf_path = HdfLandCover.get_landcover_association(hdf_path)
            if landcover_hdf_path is None:
                logger.error("Cannot resolve land cover HDF path")
                return None
        landcover_hdf_path = Path(landcover_hdf_path)

        # Find sidecar TIF
        lc_tif_path = landcover_hdf_path.with_suffix('.tif')
        if not lc_tif_path.exists():
            # Try matching the naming pattern: base.classname.tif
            candidates = list(landcover_hdf_path.parent.glob(
                f"{landcover_hdf_path.stem}*.tif"
            ))
            if candidates:
                lc_tif_path = candidates[0]
            else:
                logger.error(f"Land cover TIF not found for {landcover_hdf_path}")
                return None

        logger.info(f"Reading land cover TIF: {lc_tif_path.name} ({lc_tif_path.stat().st_size / 1024 / 1024:.0f} MB)")

        # Step 1: Read the raster map (pixel_id → class_name → base_n)
        raster_map = HdfLandCover.get_landcover_raster_map(landcover_hdf_path)
        if raster_map is None or len(raster_map) == 0:
            logger.error("Cannot read land cover raster map")
            return None

        # Build pixel_value → base_n lookup
        pixel_to_base_n = {}
        pixel_to_class_name = {}
        for _, row in raster_map.iterrows():
            pv = int(row['pixel_value'])
            pixel_to_base_n[pv] = float(row['mannings_n']) if not np.isnan(row['mannings_n']) else 0.0
            pixel_to_class_name[pv] = row['class_name']

        # Step 2: Read calibration table
        cal_table = HdfLandCover.get_mannings_calibration_table(hdf_path)
        has_calibration = cal_table is not None and len(cal_table) > 0

        # Build (class_name, region_name) → override_n lookup
        cal_lookup = {}
        region_names_ordered = []
        if has_calibration:
            lc_col = "Land Cover Name"
            base_col = "Base Manning's n Value"
            region_names_ordered = [c for c in cal_table.columns if c not in (lc_col, base_col)]

            for _, row in cal_table.iterrows():
                class_name = row[lc_col]
                for i, region_name in enumerate(region_names_ordered):
                    val = float(row[region_name])
                    if val > 0:
                        cal_lookup[(class_name, i)] = val

        # Step 3: Read region polygons and prepare for rasterization
        region_shapes = []
        if has_calibration and len(region_names_ordered) > 0:
            regions_gdf = HdfLandCover.get_mannings_region_polygons(hdf_path)
            if len(regions_gdf) > 0:
                for _, rgn in regions_gdf.iterrows():
                    region_name = rgn['Name']
                    if region_name in region_names_ordered:
                        region_idx = region_names_ordered.index(region_name)
                        region_shapes.append((rgn['geometry'], region_idx + 1))  # 1-indexed

        # Step 4: Determine clip extent from 2D flow area perimeter (tight bounds)
        # The full geometry extent can be much larger than the 2D flow area
        clip_bounds = None
        try:
            with h5py.File(hdf_path, 'r') as hf:
                # Try 2D flow area perimeter first (tightest bounds)
                perim_pts_path = "Geometry/2D Flow Areas/Polygon Points"
                if perim_pts_path in hf:
                    pts = hf[perim_pts_path][()]
                    buffer = 500.0  # 500 ft buffer around perimeter
                    clip_bounds = (
                        float(pts[:, 0].min()) - buffer,
                        float(pts[:, 1].min()) - buffer,
                        float(pts[:, 0].max()) + buffer,
                        float(pts[:, 1].max()) + buffer,
                    )
                    logger.debug(f"Clipping to 2D flow area perimeter (+ {buffer:.0f} ft buffer)")
                else:
                    # Fall back to full geometry extents
                    extents = hf['Geometry'].attrs.get('Extents')
                    if extents is not None:
                        clip_bounds = (
                            float(extents[0]), float(extents[2]),
                            float(extents[1]), float(extents[3]),
                        )
                        logger.debug("Clipping to geometry extent (no 2D perimeter found)")
        except Exception as e:
            logger.debug(f"Could not read clip bounds from geometry HDF: {e}")

        # Step 5: Read land cover TIF (clipped to geometry extent) and compute
        from rasterio.windows import from_bounds

        with rasterio.open(lc_tif_path) as src:
            if clip_bounds is not None:
                # Compute the window that covers the geometry extent
                try:
                    window = from_bounds(*clip_bounds, transform=src.transform)
                    # Round to integer pixel boundaries
                    window = window.round_offsets().round_lengths()
                    lc_raster = src.read(1, window=window)
                    transform = src.window_transform(window)
                    # Build a profile for the clipped extent
                    profile = src.profile.copy()
                    profile.update(
                        width=lc_raster.shape[1],
                        height=lc_raster.shape[0],
                        transform=transform,
                    )
                except Exception as e:
                    logger.warning(f"Window clipping failed ({e}), reading full raster")
                    lc_raster = src.read(1)
                    profile = src.profile.copy()
                    transform = src.transform
            else:
                lc_raster = src.read(1)
                profile = src.profile.copy()
                transform = src.transform

            logger.debug(f"Land cover raster: {lc_raster.shape} ({lc_raster.nbytes / 1024 / 1024:.0f} MB)")

            if lc_raster.size == 0:
                logger.error("Land cover raster is empty after clipping — check clip bounds vs raster extent")
                return None

            # Rasterize calibration regions onto same grid
            if region_shapes:
                logger.debug(f"Rasterizing {len(region_shapes)} calibration regions")
                region_raster = rio_rasterize(
                    region_shapes,
                    out_shape=lc_raster.shape,
                    transform=transform,
                    fill=0,
                    dtype=np.int32
                )
            else:
                region_raster = np.zeros(lc_raster.shape, dtype=np.int32)

            # Step 6: Vectorized lookup
            max_pixel_val = max(int(lc_raster.max()) + 1, max(pixel_to_base_n.keys(), default=0) + 1)
            base_n_lut = np.zeros(max_pixel_val, dtype=np.float32)
            for pv, n in pixel_to_base_n.items():
                if 0 <= pv < max_pixel_val:
                    base_n_lut[pv] = n

            # Apply base lookup
            final_raster = base_n_lut[np.clip(lc_raster, 0, max_pixel_val - 1)]

            # Apply calibration overrides where regions exist
            if cal_lookup and region_shapes:
                for (class_name, region_idx), override_n in cal_lookup.items():
                    for pv, cn in pixel_to_class_name.items():
                        if cn == class_name and 0 <= pv < max_pixel_val:
                            mask = (lc_raster == pv) & (region_raster == (region_idx + 1))
                            if mask.any():
                                final_raster[mask] = override_n

            valid = final_raster[final_raster > 0]
            if len(valid) > 0:
                logger.info(
                    f"Final Manning's n: shape={final_raster.shape}, "
                    f"range={valid.min():.4f}-{valid.max():.4f}, mean={valid.mean():.4f}"
                )
            else:
                logger.warning("No valid Manning's n values in output")

            # Step 7: Optionally write to GeoTIFF
            if output_tif_path is not None:
                output_tif_path = Path(output_tif_path)
                output_profile = profile.copy()
                output_profile.update(
                    dtype='float32',
                    count=1,
                    nodata=-9999.0,
                    compress='deflate'
                )
                with rasterio.open(output_tif_path, 'w', **output_profile) as dst:
                    out = final_raster.copy()
                    out[out == 0] = -9999.0
                    dst.write(out, 1)
                logger.info(f"Wrote final Manning's n raster to {output_tif_path}")

        return final_raster
