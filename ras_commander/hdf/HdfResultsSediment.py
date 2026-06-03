"""
Class: HdfResultsSediment

2D mobile-bed (sediment transport) results reader for HEC-RAS plan HDF files.

HEC-RAS writes per-cell mobile-bed results for 2D sediment runs under::

    Results/Unsteady/Output/Output Blocks/Sediment Bed/Unsteady Time Series/2D Flow Areas/<area>/
        Cell Bed Change                                   (n_time, n_cell)  ft
        Cell Bed Elevation                                (n_time, n_cell)  ft
        Cell Initial Bed Elevation                        (1,      n_cell)  ft
        Cell Active Layer Percentile Diameters - D10/D50/D90  (n_time, n_cell)  mm

The per-cell arrays align with the *computed* geometry's ``Cells Surface Area``
and ``Cells Center Coordinate`` (zero-area perimeter/ghost cells drop out of
volume integrals automatically).

All methods are static and follow the package conventions: ``@log_call`` for
logging and ``@standardize_input(file_type='plan_hdf')`` to accept plan numbers,
prefixed plan numbers, paths, or open HDF handles.

## Public Functions
- is_sediment_plan(): True if the plan HDF contains 2D mobile-bed results -> bool
- get_sediment_mesh_areas(): 2D areas that have Sediment Bed results -> List[str]
- get_cell_bed_change(): per-cell bed change at a time index -> GeoDataFrame
- get_cell_bed_elevation(): per-cell bed elevation at a time index -> GeoDataFrame
- get_active_layer_grain_class(): per-cell active-layer D10/D50/D90 -> GeoDataFrame
- get_bed_change_volumes(): erosion/deposition/net volume summary per area -> pd.DataFrame
- get_cell_bed_change_timeseries(): full (time, cell) bed-change series -> xr.DataArray
"""

from pathlib import Path
from typing import Any, List, Optional, Union

import numpy as np
import pandas as pd
import h5py

from .HdfBase import HdfBase
from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger

logger = get_logger(__name__)

# HDF group/dataset path fragments
_BED_BLOCK = ("Results/Unsteady/Output/Output Blocks/Sediment Bed/"
              "Unsteady Time Series/2D Flow Areas")
_SED_TS_TIME = ("Results/Unsteady/Output/Output Blocks/Sediment Transport/"
                "Unsteady Time Series/Time")
_BED_TS_TIME = ("Results/Unsteady/Output/Output Blocks/Sediment Bed/"
                "Unsteady Time Series/Time")


class HdfResultsSediment:
    """Static reader for 2D mobile-bed (sediment) plan-HDF results."""

    @staticmethod
    def _length_unit(f: h5py.File) -> str:
        """Return 'm' (SI) or 'ft' (US Customary) for the model, from HDF attrs.

        Mirrors the unit detection in HdfResultsQuery: SI when the geometry
        'SI Units' attr is truthy OR the root 'Units System' starts with 'si'.
        """
        def _dec(v):
            return v.decode("utf-8", "ignore") if isinstance(v, (bytes, np.bytes_)) else v
        raw_unit_system = _dec(f.attrs.get("Units System"))
        raw_si = None
        g = f.get("Geometry")
        if g is not None:
            raw_si = _dec(g.attrs.get("SI Units"))
        unit_text = str(raw_unit_system or "").strip().lower()
        si = (str(raw_si).strip().lower() in {"true", "1", "yes", "si"}
              or unit_text.startswith("si"))
        return "m" if si else "ft"

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def is_sediment_plan(hdf_path: Path, ras_object: Optional[Any] = None) -> bool:
        """
        Return True if the plan HDF contains 2D mobile-bed (Sediment Bed) results.

        Args:
            hdf_path (Union[str, Number, Path]): Plan number, prefixed plan number,
                path to the plan HDF, or open HDF handle.
            ras_object (Optional[RasPrj]): RAS project object for multi-project workflows.

        Returns:
            bool: True if the plan contains 2D mobile-bed results.
        """
        try:
            with h5py.File(hdf_path, 'r') as f:
                grp = f.get(_BED_BLOCK)
                return grp is not None and len(grp.keys()) > 0
        except Exception as e:
            logger.error(f"Error checking sediment results in {hdf_path}: {e}")
            return False

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_sediment_mesh_areas(hdf_path: Path, ras_object: Optional[Any] = None) -> List[str]:
        """
        Return the 2D flow area names that have Sediment Bed results.

        Returns an empty list if the plan has no 2D mobile-bed results.
        """
        try:
            with h5py.File(hdf_path, 'r') as f:
                grp = f.get(_BED_BLOCK)
                if grp is None:
                    return []
                # h5py >= 3 yields str group keys
                return [str(k) for k in grp.keys()]
        except Exception as e:
            logger.error(f"Error reading sediment mesh areas from {hdf_path}: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_area(f: h5py.File, mesh_name: Optional[str]) -> str:
        """Resolve a single sediment 2D area name, defaulting when unambiguous."""
        grp = f.get(_BED_BLOCK)
        if grp is None or len(grp.keys()) == 0:
            raise ValueError("Plan HDF has no Sediment Bed results (not a 2D sediment plan).")
        areas = list(grp.keys())
        if mesh_name is None:
            if len(areas) == 1:
                return areas[0]
            raise ValueError(
                f"Multiple sediment 2D areas {areas}; pass mesh_name to select one."
            )
        if mesh_name not in areas:
            raise ValueError(f"Sediment 2D area '{mesh_name}' not found. Available: {areas}")
        return mesh_name

    @staticmethod
    def _read_time_vector(f: h5py.File, n: int) -> np.ndarray:
        """Best-effort sediment output time vector (model time units, days)."""
        for path in (_BED_TS_TIME, _SED_TS_TIME):
            if path in f:
                t = f[path][:]
                if len(t) == n:
                    return t
        return np.arange(n, dtype=float)

    @staticmethod
    def _cell_geometry(f: h5py.File, area: str):
        """Return (surface_area, cell_centers, crs) for a 2D area from the plan HDF."""
        base = f"Geometry/2D Flow Areas/{area}"
        sa = f[f"{base}/Cells Surface Area"][:]
        cc = f[f"{base}/Cells Center Coordinate"][:]
        crs = HdfBase.get_projection(f)
        return sa, cc, crs

    @staticmethod
    def _cell_dataset_to_gdf(hdf_path, area, dataset, value_col, time_index, units):
        """Build a per-cell GeoDataFrame for one Sediment Bed dataset at a time index.

        ``units`` may be the literal string ``"length"`` to resolve to the model
        length unit (ft/m); otherwise it is used verbatim (e.g. ``"mm"``).
        Geometry is in the model length unit; the ``surface_area`` column is in
        length-unit^2.
        """
        from geopandas import GeoDataFrame
        from shapely.geometry import Point

        with h5py.File(hdf_path, 'r') as f:
            area = HdfResultsSediment._resolve_area(f, area)
            ds_path = f"{_BED_BLOCK}/{area}/{dataset}"
            if ds_path not in f:
                raise ValueError(f"Dataset '{dataset}' not found for area '{area}'.")
            arr = f[ds_path]
            row = arr[time_index] if arr.ndim == 2 else arr[0]
            sa, cc, crs = HdfResultsSediment._cell_geometry(f, area)
            length_unit = HdfResultsSediment._length_unit(f)

        value_units = length_unit if units == "length" else units
        n = min(len(row), len(sa), len(cc))
        gdf = GeoDataFrame(
            {
                "mesh_name": area,
                "cell_id": np.arange(n),
                value_col: np.asarray(row[:n], dtype=float),
                "surface_area": np.asarray(sa[:n], dtype=float),
                "geometry": [Point(x, y) for x, y in cc[:n]],
            },
            geometry="geometry",
            crs=crs,
        )
        gdf.attrs.update({"units": value_units, "length_unit": length_unit})
        return gdf

    # ------------------------------------------------------------------ #
    # Per-cell spatial results
    # ------------------------------------------------------------------ #
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_cell_bed_change(hdf_path: Path, mesh_name: Optional[str] = None,
                            time_index: int = -1, ras_object: Optional[Any] = None):
        """
        Return per-cell bed change (ft) at a time index as a GeoDataFrame.

        Columns: ``mesh_name, cell_id, bed_change, surface_area, geometry``.
        ``bed_change`` is in the model length unit (ft or m; see
        ``gdf.attrs['length_unit']``). Negative = scour, positive = deposition.
        ``time_index`` indexes the sediment output series (default -1 = final).
        """
        return HdfResultsSediment._cell_dataset_to_gdf(
            hdf_path, mesh_name, "Cell Bed Change", "bed_change", time_index, "length")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_cell_bed_elevation(hdf_path: Path, mesh_name: Optional[str] = None,
                               time_index: int = -1, ras_object: Optional[Any] = None):
        """
        Return per-cell bed elevation (ft) at a time index as a GeoDataFrame.

        Columns: ``mesh_name, cell_id, bed_elevation, surface_area, geometry``
        (``bed_elevation`` in the model length unit; see ``gdf.attrs['length_unit']``).
        """
        return HdfResultsSediment._cell_dataset_to_gdf(
            hdf_path, mesh_name, "Cell Bed Elevation", "bed_elevation", time_index, "length")

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_active_layer_grain_class(hdf_path: Path, percentile: str = "D50",
                                     mesh_name: Optional[str] = None, time_index: int = -1,
                                     ras_object: Optional[Any] = None):
        """
        Return per-cell active-layer grain diameter (mm) at a time index.

        Args:
            percentile (str): One of ``"D10"``, ``"D50"``, ``"D90"`` (case-insensitive).
            mesh_name (Optional[str]): 2D area name; defaults to the sole sediment area.
            time_index (int): Sediment output time index (default -1 = final).

        Returns:
            GeoDataFrame: Columns ``mesh_name, cell_id, d<NN>_mm, surface_area, geometry``
            (grain diameters are always mm regardless of the model unit system).
        """
        pct = percentile.upper()
        if pct not in ("D10", "D50", "D90"):
            raise ValueError(f"percentile must be D10, D50, or D90 (got '{percentile}').")
        dataset = f"Cell Active Layer Percentile Diameters - {pct}"
        return HdfResultsSediment._cell_dataset_to_gdf(
            hdf_path, mesh_name, dataset, f"{pct.lower()}_mm", time_index, "mm")

    # ------------------------------------------------------------------ #
    # Volume summary
    # ------------------------------------------------------------------ #
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_bed_change_volumes(hdf_path: Path, mesh_name: Optional[str] = None,
                               time_index: int = -1, ras_object: Optional[Any] = None) -> pd.DataFrame:
        """
        Summarize bed-change volumes per 2D sediment area at a time index.

        Integrates ``Cell Bed Change`` against ``Cells Surface Area`` (zero-area
        ghost cells drop out). One row per area with columns:
        ``mesh_name, length_unit, n_cells, net_bed_volume, erosion_volume,
        deposition_volume, max_scour, max_deposition``.

        Volumes are in native cubic length units (ft^3 or m^3, per
        ``length_unit``); ``max_scour``/``max_deposition`` are in the native
        length unit. Negative values indicate net scour. Callers convert to
        ac-ft / cubic yards only when ``length_unit == 'ft'``.
        """
        cols = ["mesh_name", "length_unit", "n_cells", "net_bed_volume",
                "erosion_volume", "deposition_volume", "max_scour", "max_deposition"]
        rows = []
        with h5py.File(hdf_path, 'r') as f:
            grp = f.get(_BED_BLOCK)
            if grp is None:
                return pd.DataFrame(columns=cols)
            length_unit = HdfResultsSediment._length_unit(f)
            areas = [mesh_name] if mesh_name is not None else list(grp.keys())
            for area in areas:
                ds_path = f"{_BED_BLOCK}/{area}/Cell Bed Change"
                if ds_path not in f:
                    continue
                bc = f[ds_path][time_index]
                sa, _, _ = HdfResultsSediment._cell_geometry(f, area)
                n = min(len(bc), len(sa))
                bc = np.asarray(bc[:n], dtype=float)
                sa = np.asarray(sa[:n], dtype=float)
                vol = bc * sa  # native^3 per cell
                wet = sa > 0  # exclude zero-area perimeter/ghost cells
                bc_wet = bc[wet]
                rows.append({
                    "mesh_name": area,
                    "length_unit": length_unit,
                    "n_cells": int(wet.sum()),
                    "net_bed_volume": float(np.nansum(vol)),
                    "erosion_volume": float(np.nansum(vol[vol < 0])),
                    "deposition_volume": float(np.nansum(vol[vol > 0])),
                    "max_scour": float(np.nanmin(bc_wet)) if bc_wet.size else np.nan,
                    "max_deposition": float(np.nanmax(bc_wet)) if bc_wet.size else np.nan,
                })
        return pd.DataFrame(rows, columns=cols)

    # ------------------------------------------------------------------ #
    # Time series
    # ------------------------------------------------------------------ #
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_cell_bed_change_timeseries(hdf_path: Path, mesh_name: Optional[str] = None,
                                       ras_object: Optional[Any] = None):
        """
        Return the full (time, cell) bed-change series as an xarray.DataArray.

        Dimensions ``(time, cell_id)``; ``time`` is the model output time vector
        (days). Units are the model length unit (ft or m; see ``da.attrs['units']``);
        negative = scour.
        """
        import xarray as xr

        with h5py.File(hdf_path, 'r') as f:
            area = HdfResultsSediment._resolve_area(f, mesh_name)
            bc = f[f"{_BED_BLOCK}/{area}/Cell Bed Change"][:]
            t = HdfResultsSediment._read_time_vector(f, bc.shape[0])
            length_unit = HdfResultsSediment._length_unit(f)
        da = xr.DataArray(
            bc,
            dims=("time", "cell_id"),
            coords={"time": t, "cell_id": np.arange(bc.shape[1])},
            name="bed_change",
        )
        da.attrs.update({"units": length_unit, "mesh_name": area,
                         "description": "Cumulative bed change (negative = scour)"})
        return da
