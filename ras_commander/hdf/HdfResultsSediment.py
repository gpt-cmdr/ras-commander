"""
Class: HdfResultsSediment

2D mobile-bed (sediment transport) results reader for HEC-RAS plan HDF files.

HEC-RAS writes per-cell mobile-bed results for 2D sediment runs under::

    Results/Unsteady/Output/Output Blocks/Sediment Bed/Unsteady Time Series/2D Flow Areas/<area>/
        Cell Bed Change                                   (n_time, n_cell)  ft or m
        Cell Bed Elevation                                (n_time, n_cell)  ft or m
        Cell Initial Bed Elevation                        (1,      n_cell)  ft or m
        Cell Active Layer Percentile Diameters - D10/D50/D90  (n_time, n_cell)  mm

Length datasets are in the model length unit (see ``get_cell_bed_change``);
active-layer diameters are always mm, checked against each dataset's own
``Units`` attribute.

The per-cell arrays align with the *computed* geometry's ``Cells Surface Area``
and ``Cells Center Coordinate``. Results cover the physical cells only: the
ghost cells HEC-RAS lists after them (IDs at or above the area's
``Attributes`` ``Cell Count``) are dropped.

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
from typing import Any, List, Optional

import numpy as np
import pandas as pd
import h5py

from .HdfBase import HdfBase
from .HdfMesh import HdfMesh
from .HdfUtils import HdfUtils
from ..Decorators import log_call, standardize_input
from ..LoggingConfig import get_logger
from ..fast_hdf import read_attr, read_typed

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
    def _project_file(hdf_path: Path, ras_object: Optional[Any]) -> Optional[Path]:
        """Return the ``.prj`` of the project that owns ``hdf_path``, if known.

        An explicit ``ras_object`` supplies its project file. Otherwise the
        initialized global ``ras`` is used only when its plan DataFrame
        identifies the HDF as a result file. Sharing a folder is insufficient.
        No folder is searched for ``.prj`` files.
        """
        project = ras_object
        if project is None:
            from ..RasPrj import ras as project
            if not getattr(project, "initialized", False):
                return None
            plans = getattr(project, "plan_df", None)
            if not isinstance(plans, pd.DataFrame):
                return None
            owned_paths = []
            for column in ("HDF_Results_Path", "full_path"):
                for value in plans.get(column, []):
                    if isinstance(value, (str, Path)) and str(value).strip():
                        candidate = Path(value)
                        if column == "full_path":
                            candidate = Path(str(candidate) + ".hdf")
                        owned_paths.append(candidate)
            try:
                belongs_to_project = any(
                    Path(hdf_path).resolve() == candidate.resolve()
                    for candidate in owned_paths
                )
            except (OSError, ValueError):
                return None
            if not belongs_to_project:
                return None
        prj_file = getattr(project, "prj_file", None)
        return Path(prj_file) if prj_file else None

    @staticmethod
    def _length_unit(f: h5py.File, *, unit_system: Optional[str] = None,
                     project_file: Optional[Path] = None,
                     strict: bool = True) -> Optional[str]:
        """Return the resolved model length unit (``ft``/``m``).

        Precedence: ``unit_system`` override, then the project ``.prj``
        marker, then the embedded result-HDF metadata (see
        :meth:`HdfBase.get_result_unit_metadata`). With ``strict=False`` an
        unresolvable unit system returns None and logs a warning.
        """
        metadata = HdfBase._result_unit_metadata_from_file(
            f,
            source_file=Path(f.filename),
            strict=strict,
            unit_system=unit_system,
            project_file=project_file,
        )
        if metadata["status"] != "resolved":
            logger.warning(
                "Model length unit unresolved for %s: %s",
                Path(f.filename).name, "; ".join(metadata["contradictions"]))
            return None
        return str(metadata["length_units"])

    @staticmethod
    def _require_mm_units(dataset: h5py.Dataset, name: str, area: str) -> None:
        """Validate a grain-diameter dataset against its own ``Units`` label.

        HEC-RAS stores active-layer diameters in mm in SI and US Customary
        projects alike, so the model unit system is not consulted. A label
        other than ``mm`` raises; an unlabelled dataset keeps the mm
        convention with a warning.
        """
        if "Units" not in dataset.attrs:
            logger.warning(
                "Dataset '%s' in area '%s' has no Units attribute; assuming mm.",
                name, area)
            return
        units = HdfBase._decode_unit_attribute(read_attr(dataset, "Units"))
        if units != "mm":
            raise ValueError(
                f"Dataset '{name}' in area '{area}' has Units={units!r}; "
                "active-layer grain diameters must be labelled 'mm'.")

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
                t = read_typed(f[path], slice(None))
                if len(t) == n:
                    return t
        return np.arange(n, dtype=float)

    @staticmethod
    def _cell_geometry(f: h5py.File, area: str):
        """Return (surface_area, cell_centers, crs) for a 2D area from the plan HDF."""
        base = f"Geometry/2D Flow Areas/{area}"
        sa = read_typed(f[f"{base}/Cells Surface Area"], slice(None))
        cc = read_typed(f[f"{base}/Cells Center Coordinate"], slice(None))
        crs = HdfBase.get_projection(f)
        return sa, cc, crs

    @staticmethod
    def _read_cell_dataset(hdf_path, area, dataset, time_index, *,
                           unit_system=None, project_file=None,
                           grain_diameter=False, typed=False):
        """Read one Sediment Bed per-cell dataset and aligned geometry (numpy only).

        Returns a dict with ``area`` (resolved name), ``values`` (per-cell at the
        requested time), ``surface_area``, ``centers``, ``crs``, and ``length_unit``
        (ft/m). No GeoPandas dependency -- callers build the GeoDataFrame so the
        heavy import stays at each public-method boundary.

        ``grain_diameter=True`` validates the dataset's own ``mm`` label and
        does not block on the model unit system (``length_unit`` may be None).

        ``typed=True`` serves the typed tables: ``values``/``surface_area``
        keep their stored dtypes (no float64 cast), and the cell centers and
        CRS are not read (``centers``/``crs`` are None). Validation and its
        messages are unchanged; the center count comes from the stored shape.
        """
        with h5py.File(hdf_path, 'r') as f:
            area = HdfResultsSediment._resolve_area(f, area)
            ds_path = f"{_BED_BLOCK}/{area}/{dataset}"
            if ds_path not in f:
                raise ValueError(f"Dataset '{dataset}' not found for area '{area}'.")
            arr = f[ds_path]
            if grain_diameter:
                HdfResultsSediment._require_mm_units(arr, dataset, area)
            row = HdfResultsSediment._select_time_row(arr, time_index, dataset, area)
            if typed:
                base = f"Geometry/2D Flow Areas/{area}"
                sa = read_typed(f[f"{base}/Cells Surface Area"], slice(None))
                cc, crs = None, None
                center_count = len(f[f"{base}/Cells Center Coordinate"])
            else:
                sa, cc, crs = HdfResultsSediment._cell_geometry(f, area)
                center_count = len(cc)
            length_unit = HdfResultsSediment._length_unit(
                f, unit_system=unit_system, project_file=project_file,
                strict=not grain_diameter)
            physical_count = HdfMesh._physical_cell_counts(f).get(area)

        values = np.asarray(row) if typed else np.asarray(row, dtype=float)
        sa = np.asarray(sa) if typed else np.asarray(sa, dtype=float)
        # Per-cell results must align 1:1 with the geometry cells; a mismatch
        # would otherwise yield silently truncated (wrong) values/volumes.
        if not (len(values) == len(sa) == center_count):
            raise ValueError(
                f"Cell array length mismatch in area '{area}': {dataset}={len(values)}, "
                f"Cells Surface Area={len(sa)}, Cells Center Coordinate={center_count}.")
        if physical_count is not None:
            # Ghost cells follow the physical cells and carry no solution.
            values, sa = values[:physical_count], sa[:physical_count]
            if cc is not None:
                cc = cc[:physical_count]
        return {
            "area": area,
            "values": values,
            "surface_area": sa,
            "centers": cc,
            "crs": crs,
            "length_unit": length_unit,
        }

    @staticmethod
    def _select_time_row(arr, time_index, dataset, area):
        """Select a single per-cell row from a Sediment Bed dataset.

        Handles the normal ``(n_time, n_cell)`` layout and a 1-D ``(n_cell,)``
        single-snapshot layout; raises a clear error on any other rank.
        """
        if arr.ndim == 2:
            return read_typed(arr, time_index)
        if arr.ndim == 1:
            return read_typed(arr, slice(None))
        raise ValueError(
            f"Unexpected rank {arr.ndim} for dataset '{dataset}' in area '{area}' "
            "(expected (n_time, n_cell) or (n_cell,)).")

    @staticmethod
    def _build_cell_gdf(GeoDataFrame, Point, data, value_col, units):
        """Assemble the per-cell GeoDataFrame from a ``_read_cell_dataset`` dict.

        GeoDataFrame/Point are passed in so the lazy GeoPandas/Shapely imports
        live at the public-method boundary (matching the rest of the hdf package).
        """
        centers = data["centers"]
        gdf = GeoDataFrame(
            {
                "mesh_name": data["area"],
                "cell_id": np.arange(len(data["values"])),
                value_col: data["values"],
                "surface_area": data["surface_area"],
                "geometry": [Point(x, y) for x, y in centers],
            },
            geometry="geometry",
            crs=data["crs"],
        )
        gdf.attrs.update({"units": units, "length_unit": data["length_unit"]})
        return gdf

    @staticmethod
    def _build_cell_table(data, value_col, units):
        """Typed per-cell table: the GeoDataFrame columns without ``geometry``.

        ``mesh_name`` is pandas ``str``/``string``, ``cell_id`` is ``int64``, and the
        value and ``surface_area`` columns keep their stored dtypes.
        """
        values = data["values"]
        table = pd.DataFrame({
            "mesh_name": HdfUtils._text_array([data["area"]] * len(values)),
            "cell_id": np.arange(len(values), dtype=np.int64),
            value_col: values,
            "surface_area": data["surface_area"],
        })
        table.attrs.update({"units": units, "length_unit": data["length_unit"]})
        return table

    @staticmethod
    def _cell_result(hdf_path, mesh_name, dataset, time_index, value_col, units,
                     include_geometry, **read_kwargs):
        """Read one per-cell dataset as the GeoDataFrame or the typed table."""
        if include_geometry:
            from geopandas import GeoDataFrame
            from shapely.geometry import Point
        data = HdfResultsSediment._read_cell_dataset(
            hdf_path, mesh_name, dataset, time_index,
            typed=not include_geometry, **read_kwargs)
        units = data["length_unit"] if units is None else units
        if not include_geometry:
            return HdfResultsSediment._build_cell_table(data, value_col, units)
        return HdfResultsSediment._build_cell_gdf(
            GeoDataFrame, Point, data, value_col, units)

    # ------------------------------------------------------------------ #
    # Per-cell spatial results
    # ------------------------------------------------------------------ #
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_cell_bed_change(hdf_path: Path, mesh_name: Optional[str] = None,
                            time_index: int = -1, ras_object: Optional[Any] = None,
                            unit_system: Optional[str] = None, *,
                            include_geometry: bool = True):
        """
        Return per-cell bed change at a time index as a GeoDataFrame.

        Columns: ``mesh_name, cell_id, bed_change, surface_area, geometry``.
        ``bed_change`` is in the model length unit (ft or m; see
        ``gdf.attrs['length_unit']``). Negative = scour, positive = deposition.
        ``time_index`` indexes the sediment output series (default -1 = final).

        The length unit comes from ``unit_system`` (``"SI"`` or
        ``"US Customary"``) when given, else from the project ``.prj`` marker
        when the project is known (``ras_object``, or the initialized global
        project that contains the HDF), else from the embedded HDF metadata
        (see :meth:`HdfBase.get_result_unit_metadata`). Unresolvable or
        contradictory units raise ``ValueError``.

        ``include_geometry=False`` (keyword-only) returns a DataFrame with the
        same rows, order, values and ``attrs`` but no ``geometry`` column and
        no GeoPandas/Shapely dependency: ``mesh_name`` (pandas ``str``/``string``),
        ``cell_id`` (``int64``), and ``bed_change``/``surface_area`` in their
        stored dtypes (the GeoDataFrame casts them to ``float64``).
        """
        return HdfResultsSediment._cell_result(
            hdf_path, mesh_name, "Cell Bed Change", time_index, "bed_change", None,
            include_geometry, unit_system=unit_system,
            project_file=HdfResultsSediment._project_file(hdf_path, ras_object))

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_cell_bed_elevation(hdf_path: Path, mesh_name: Optional[str] = None,
                               time_index: int = -1, ras_object: Optional[Any] = None,
                               unit_system: Optional[str] = None, *,
                               include_geometry: bool = True):
        """
        Return per-cell bed elevation at a time index as a GeoDataFrame.

        Columns: ``mesh_name, cell_id, bed_elevation, surface_area, geometry``
        (``bed_elevation`` in the model length unit; see ``gdf.attrs['length_unit']``).
        The length unit resolves as in :meth:`get_cell_bed_change`
        (``unit_system`` override, project ``.prj``, embedded metadata).
        ``include_geometry=False`` returns the typed table described in
        :meth:`get_cell_bed_change`.
        """
        return HdfResultsSediment._cell_result(
            hdf_path, mesh_name, "Cell Bed Elevation", time_index, "bed_elevation", None,
            include_geometry, unit_system=unit_system,
            project_file=HdfResultsSediment._project_file(hdf_path, ras_object))

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_active_layer_grain_class(hdf_path: Path, percentile: str = "D50",
                                     mesh_name: Optional[str] = None, time_index: int = -1,
                                     ras_object: Optional[Any] = None,
                                     unit_system: Optional[str] = None, *,
                                     include_geometry: bool = True):
        """
        Return per-cell active-layer grain diameter (mm) at a time index.

        HEC-RAS stores these diameters in mm in SI and US Customary projects
        alike. The reader validates the dataset's own ``Units`` attribute and
        raises if it is not ``mm``; an unlabelled dataset is read as mm with a
        warning. The model unit system is not needed for the diameters, so
        unresolvable or contradictory model units no longer block this reader.

        Args:
            percentile (str): One of ``"D10"``, ``"D50"``, ``"D90"`` (case-insensitive).
            mesh_name (Optional[str]): 2D area name; defaults to the sole sediment area.
            time_index (int): Sediment output time index (default -1 = final).
            ras_object (Optional[RasPrj]): Project whose ``.prj`` marker sets
                ``attrs['length_unit']``.
            unit_system (Optional[str]): ``"SI"`` or ``"US Customary"`` override
                for ``attrs['length_unit']``.
            include_geometry (bool): Keyword-only. Default True returns the
                GeoDataFrame below. False returns the typed table described in
                :meth:`get_cell_bed_change` (``d<NN>_mm`` in its stored dtype).

        Returns:
            GeoDataFrame: Columns ``mesh_name, cell_id, d<NN>_mm, surface_area, geometry``.
                ``attrs['units']`` is ``"mm"``. ``attrs['length_unit']`` is the
                resolved model length unit, or None (with a logged warning) when
                it cannot be resolved.
        """
        pct = percentile.upper()
        if pct not in ("D10", "D50", "D90"):
            raise ValueError(f"percentile must be D10, D50, or D90 (got '{percentile}').")
        dataset = f"Cell Active Layer Percentile Diameters - {pct}"
        return HdfResultsSediment._cell_result(
            hdf_path, mesh_name, dataset, time_index, f"{pct.lower()}_mm", "mm",
            include_geometry, unit_system=unit_system,
            project_file=HdfResultsSediment._project_file(hdf_path, ras_object),
            grain_diameter=True)

    # ------------------------------------------------------------------ #
    # Volume summary
    # ------------------------------------------------------------------ #
    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_bed_change_volumes(hdf_path: Path, mesh_name: Optional[str] = None,
                               time_index: int = -1, ras_object: Optional[Any] = None,
                               unit_system: Optional[str] = None) -> pd.DataFrame:
        """
        Summarize bed-change volumes per 2D sediment area at a time index.

        Integrates ``Cell Bed Change`` against ``Cells Surface Area`` over the
        physical cells (ghost cells are dropped). One row per area with columns:
        ``mesh_name, length_unit, n_cells, net_bed_volume, erosion_volume,
        deposition_volume, max_scour, max_deposition``.

        Volumes are in native cubic length units (ft^3 or m^3, per
        ``length_unit``); ``max_scour``/``max_deposition`` are in the native
        length unit. Negative values indicate net scour. Callers convert to
        ac-ft / cubic yards only when ``length_unit == 'ft'``. The length unit
        resolves as in :meth:`get_cell_bed_change`.
        """
        project_file = HdfResultsSediment._project_file(hdf_path, ras_object)
        cols = ["mesh_name", "length_unit", "n_cells", "net_bed_volume",
                "erosion_volume", "deposition_volume", "max_scour", "max_deposition"]
        with h5py.File(hdf_path, 'r') as f:
            grp = f.get(_BED_BLOCK)
            if grp is None:
                return pd.DataFrame(columns=cols)
            # An explicit mesh_name is validated (raises on a bad name); otherwise
            # summarize every sediment area. _resolve_area is called again inside
            # _read_cell_dataset for the actual read.
            if mesh_name is not None:
                areas = [HdfResultsSediment._resolve_area(f, mesh_name)]
            else:
                areas = list(grp.keys())

        rows = []
        for area in areas:
            # Reuse the shared reader: ndim handling + strict length validation.
            data = HdfResultsSediment._read_cell_dataset(
                hdf_path, area, "Cell Bed Change", time_index,
                unit_system=unit_system, project_file=project_file)
            bc, sa = data["values"], data["surface_area"]
            vol = bc * sa  # native^3 per cell
            wet = sa > 0   # exclude zero-area perimeter/ghost cells
            bc_wet = bc[wet]
            rows.append({
                "mesh_name": area,
                "length_unit": data["length_unit"],
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
                                       ras_object: Optional[Any] = None,
                                       unit_system: Optional[str] = None):
        """
        Return the full (time, cell) bed-change series as an xarray.DataArray.

        Dimensions ``(time, cell_id)``; ``time`` is the model output time vector
        (days). Units are the model length unit (ft or m; see ``da.attrs['units']``),
        resolved as in :meth:`get_cell_bed_change`; negative = scour.
        """
        import xarray as xr

        project_file = HdfResultsSediment._project_file(hdf_path, ras_object)
        with h5py.File(hdf_path, 'r') as f:
            area = HdfResultsSediment._resolve_area(f, mesh_name)
            bc = read_typed(f[f"{_BED_BLOCK}/{area}/Cell Bed Change"], slice(None))
            length_unit = HdfResultsSediment._length_unit(
                f, unit_system=unit_system, project_file=project_file)
            # Tolerate a 1-D single-snapshot dataset by promoting to (1, n_cell).
            if bc.ndim == 1:
                bc = bc[np.newaxis, :]
            elif bc.ndim != 2:
                raise ValueError(
                    f"Unexpected rank {bc.ndim} for 'Cell Bed Change' in area '{area}'.")
            t = HdfResultsSediment._read_time_vector(f, bc.shape[0])
            physical_count = HdfMesh._physical_cell_counts(f).get(area)
        if physical_count is not None:
            bc = bc[:, :physical_count]  # drop ghost cells after the physical cells
        da = xr.DataArray(
            bc,
            dims=("time", "cell_id"),
            coords={"time": t, "cell_id": np.arange(bc.shape[1])},
            name="bed_change",
        )
        da.attrs.update({"units": length_unit, "mesh_name": area,
                         "description": "Cumulative bed change (negative = scour)"})
        return da
