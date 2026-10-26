"""Public methods qualified by ROUTE-EXTENTS, keyed ``Class.method[variant]``.

Each entry maps to a callable taking the fixture path. Element arguments (mesh,
query point, reference line, timestamp, raster resolution) are derived from the
file with h5py inside this module, identically in every mode; the h5py guard
treats reads made from this module as harness reads.

File products (GeoJSON, GeoTIFF, product packages) are written to a fresh
temporary folder and returned as comparable content: parsed JSON, and for
rasters the band arrays, transform, CRS WKT, nodata, dtypes, tags and overview
levels (not file bytes). Product-package checksums of raster/PNG assets are
replaced by their decoded content for the same reason.
"""
import json
import shutil
import tempfile
from pathlib import Path

import h5py
import numpy as np
import pytest

TS = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
# Products and rasters render whole-model grids; the h5py-mode run alone takes
# minutes on the three fixtures above this size. Bounded like route-1.
HEAVY_BYTES = 100_000_000


def _hdf():
    from ras_commander import hdf
    return hdf


def _fresh(path):
    """Drop HdfResultsQuery's per-path caches so every mode reads the file itself."""
    import sys
    module = sys.modules.get("ras_commander.hdf.HdfResultsQuery")
    if module is not None:
        module._kdtree_cache.clear()
        module._topology_cache.clear()
    return Path(path)


def _bounded(path):
    if Path(path).stat().st_size > HEAVY_BYTES:
        pytest.skip("whole-model raster/product rendering bounded to fixtures < 100 MB")


def _mesh_first(path):
    with h5py.File(path, "r") as f:
        key = "Geometry/2D Flow Areas/Attributes"
        if key not in f or not len(f[key]):
            return "__absent__"
        return f[key][()]["Name"][0].decode().strip()


def _cell_points(path, count=3):
    """Physical cell centers of the first mesh: first, middle and last physical cell."""
    mesh = _mesh_first(path)
    with h5py.File(path, "r") as f:
        key = f"Geometry/2D Flow Areas/{mesh}/Cells Center Coordinate"
        if key not in f:
            return np.array([[0.0, 0.0]] * count)
        rows = f["Geometry/2D Flow Areas/Attributes"][()]
        physical = int(rows["Cell Count"][0]) if "Cell Count" in rows.dtype.names else len(f[key])
        centers = f[key][()][:physical]
    picks = np.linspace(0, len(centers) - 1, count).astype(int)
    return np.asarray(centers[picks], dtype=float)


def _reference_line(path):
    with h5py.File(path, "r") as f:
        key = "Geometry/Reference Lines/Attributes"
        if key not in f or not len(f[key]):
            return "__absent__"
        return f[key][()]["Name"][0].decode().strip()


def _middle_stamp(path):
    with h5py.File(path, "r") as f:
        for name in ("Time Date Stamp", "Time Date Stamp (ms)"):
            key = f"{TS}/{name}"
            if key in f and len(f[key]):
                return f[key][len(f[key]) // 2].decode().strip()[:18]
    return "01JAN2000 00:00:00"


def _resolution(path, cells=300.0):
    """Cell size giving about ``cells`` raster columns over the first mesh."""
    with h5py.File(path, "r") as f:
        key = f"Geometry/2D Flow Areas/{_mesh_first(path)}/Cells Center Coordinate"
        if key not in f:
            return 3.0
        span = float(np.nanmax(np.ptp(f[key][()], axis=0)))
    return max(span / cells, 1.0)


def _raster(path):
    import rasterio
    with rasterio.open(path) as src:
        return {
            "array": src.read(),
            "transform": tuple(float(v) for v in src.transform),
            "crs": src.crs.to_wkt() if src.crs else None,
            "nodata": src.nodata,
            "dtypes": list(src.dtypes),
            "shape": [src.count, src.height, src.width],
            "tags": src.tags(),
            "overviews": [src.overviews(i) for i in range(1, src.count + 1)],
        }


def _png(path):
    import rasterio
    with rasterio.open(path) as src:
        return {"array": src.read(), "shape": [src.count, src.height, src.width]}


def _content(path):
    path = Path(path)
    if path.suffix == ".tif":
        return _raster(path)
    if path.suffix == ".png":
        return _png(path)
    if path.suffix in {".json", ".geojson"}:
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix == ".parquet":
        import pandas as pd
        return pd.read_parquet(path)
    return path.read_bytes()


class _Scratch:
    def __enter__(self):
        self.path = Path(tempfile.mkdtemp(prefix="route-extents-"))
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)


# ------------------------------------------------------------------ HdfProject
def _extent_geojson(path):
    with _Scratch() as tmp:
        out = _hdf().HdfProject.export_extent_geojson(Path(path), tmp / "extent.geojson", buffer_percent=0.0)
        return {"name": Path(out).name, "content": _content(out)}


# ------------------------------------------------------------------ HdfResultsQuery
def _query_point(path, variable, time_index=-1):
    x, y = _cell_points(path, 3)[1]
    return _hdf().HdfResultsQuery.query_point(_fresh(path), float(x), float(y), variable=variable,
                                              time_index=time_index)


def _query_points(path, variable, time_index=-1):
    return _hdf().HdfResultsQuery.query_points(_fresh(path), _cell_points(path, 3), variable=variable,
                                               time_index=time_index)


def _query_profile(path, variable, time_index=-1):
    (x1, y1), _, (x2, y2) = _cell_points(path, 3)
    return _hdf().HdfResultsQuery.query_profile(_fresh(path), float(x1), float(y1), float(x2), float(y2),
                                                variable=variable, n_points=25, time_index=time_index)


def _transverse(path, time_index=-1):
    x, y = _cell_points(path, 3)[1]
    return _hdf().HdfResultsQuery.query_transverse_profile(_fresh(path), float(x), float(y),
                                                           time_index=time_index, max_steps=10)


# ------------------------------------------------------------------ HdfResultsMesh
def _iter_series(path, var):
    batches = _hdf().HdfResultsMesh.iter_mesh_timeseries(
        Path(path), _mesh_first(path), var, time_selection=slice(0, 12), batch_size=5)
    return list(batches)


def _max_depth_raster(path):
    _bounded(path)
    with _Scratch() as tmp:
        out = _hdf().HdfResultsMesh.export_max_depth_raster(
            Path(path), tmp / "max-depth.tif", resolution_m=_resolution(path))
        return {"name": Path(out).name, "raster": _raster(out)}


def _depth_rasters(path, method="nearest"):
    _bounded(path)
    stamp = _middle_stamp(path)
    with _Scratch() as tmp:
        outputs = _hdf().HdfResultsMesh.export_depth_rasters_at_times(
            Path(path), [stamp], tmp, mesh_name=_mesh_first(path), max_dimension=150, method=method)
        return {label: {"name": Path(out).name, "raster": _raster(out)} for label, out in outputs.items()}


# ------------------------------------------------------------------ HdfResultsProducts
_CHECKSUMMED = {"maximum-wse", "maximum-depth", "maximum-velocity", "preview"}


def _products(path):
    _bounded(path)
    with _Scratch() as tmp:
        manifest = _hdf().HdfResultsProducts.export(Path(path), tmp / "package", max_dimension=128)
        package = tmp / "package"
        files = {p.name: _content(p) for p in sorted(package.iterdir())}
        manifest = json.loads(json.dumps(manifest))
        for key, asset in manifest["assets"].items():
            if key in _CHECKSUMMED:
                # Rendered rasters compare by decoded content, not file bytes.
                asset.pop("sha256", None)
                asset.pop("size_bytes", None)
        files.pop("hydraulic-products.json", None)
        return {"manifest": manifest, "files": files}


def _hdf_attrs(path, attr_path):
    return _hdf().HdfBase.get_attrs(Path(path), attr_path)


CASES = {
    # HdfProject
    "HdfProject.get_project_extent[footprint]": lambda p: _hdf().HdfProject.get_project_extent(Path(p), buffer_percent=0.0),
    "HdfProject.get_project_extent[footprint-buffered]": lambda p: _hdf().HdfProject.get_project_extent(Path(p)),
    "HdfProject.get_project_extent[bbox]": lambda p: _hdf().HdfProject.get_project_extent(Path(p), geometry_type="bbox"),
    "HdfProject.get_project_extent[hdf-only]": lambda p: _hdf().HdfProject.get_project_extent(
        Path(p), buffer_percent=0.0, fallback_to_plaintext=False),
    "HdfProject.get_project_bounds_latlon": lambda p: _hdf().HdfProject.get_project_bounds_latlon(Path(p)),
    "HdfProject.get_project_crs": lambda p: _hdf().HdfProject.get_project_crs(Path(p)),
    "HdfProject.export_extent_geojson": _extent_geojson,
    # HdfResultsQuery
    "HdfResultsQuery.query_point[wse]": lambda p: _query_point(p, "wse"),
    "HdfResultsQuery.query_point[depth-max]": lambda p: _query_point(p, "depth", "max"),
    "HdfResultsQuery.query_point[velocity]": lambda p: _query_point(p, "velocity"),
    "HdfResultsQuery.query_points[depth]": lambda p: _query_points(p, "depth"),
    "HdfResultsQuery.query_points[velocity-max]": lambda p: _query_points(p, "velocity", "max"),
    "HdfResultsQuery.query_profile[wse]": lambda p: _query_profile(p, "wse"),
    "HdfResultsQuery.query_profile[depth-0]": lambda p: _query_profile(p, "depth", 0),
    "HdfResultsQuery.query_transverse_profile": _transverse,
    "HdfResultsQuery.flood_extent": lambda p: _hdf().HdfResultsQuery.flood_extent(_fresh(p)),
    "HdfResultsQuery.flood_extent[max]": lambda p: _hdf().HdfResultsQuery.flood_extent(_fresh(p), time_index="max"),
    "HdfResultsQuery.result_statistics[depth]": lambda p: _hdf().HdfResultsQuery.result_statistics(_fresh(p)),
    "HdfResultsQuery.result_statistics[wse-max]": lambda p: _hdf().HdfResultsQuery.result_statistics(
        _fresh(p), variable="wse", time_index="max", wet_only=False),
    # HdfResultsMesh
    "HdfResultsMesh.iter_mesh_timeseries[Water Surface]": lambda p: _iter_series(p, "Water Surface"),
    "HdfResultsMesh.iter_mesh_timeseries[Face Velocity]": lambda p: _iter_series(p, "Face Velocity"),
    "HdfResultsMesh.get_profile_line_flow_timeseries_legacy": lambda p: _hdf().HdfResultsMesh.get_profile_line_flow_timeseries_legacy(
        Path(p), _reference_line(p)),
    "HdfResultsMesh.get_profile_line_flow_timeseries_legacy[signed]": lambda p: _hdf().HdfResultsMesh.get_profile_line_flow_timeseries_legacy(
        Path(p), _reference_line(p), direction="signed", truncate=True),
    "HdfResultsMesh.get_mesh_max_depth": lambda p: _hdf().HdfResultsMesh.get_mesh_max_depth(Path(p)),
    "HdfResultsMesh.get_mesh_max_depth[ghosts]": lambda p: _hdf().HdfResultsMesh.get_mesh_max_depth(Path(p), include_ghost_cells=True),
    "HdfResultsMesh.get_mesh_max_depth[table]": lambda p: _hdf().HdfResultsMesh.get_mesh_max_depth(Path(p), include_geometry=False),
    "HdfResultsMesh.get_mesh_max_depth[ghosts,table]": lambda p: _hdf().HdfResultsMesh.get_mesh_max_depth(Path(p), include_ghost_cells=True, include_geometry=False),
    "HdfResultsMesh.export_max_depth_raster": _max_depth_raster,
    "HdfResultsMesh.export_depth_rasters_at_times": _depth_rasters,
    "HdfResultsMesh.export_depth_rasters_at_times[linear]": lambda p: _depth_rasters(p, "linear"),
    # HdfResultsProducts
    "HdfResultsProducts.export": _products,
    # HdfBase
    "HdfBase.get_projection": lambda p: _hdf().HdfBase.get_projection(Path(p)),
    "HdfBase.get_result_unit_metadata": lambda p: _hdf().HdfBase.get_result_unit_metadata(Path(p)),
    "HdfBase.get_result_unit_metadata[lenient]": lambda p: _hdf().HdfBase.get_result_unit_metadata(Path(p), strict=False),
    "HdfBase.get_attrs[root]": lambda p: _hdf_attrs(p, "/"),
    "HdfBase.get_attrs[Geometry]": lambda p: _hdf_attrs(p, "Geometry"),
    "HdfBase.get_attrs[Plan Information]": lambda p: _hdf_attrs(p, "Plan Data/Plan Information"),
    "HdfBase.get_attrs[2D Attributes]": lambda p: _hdf_attrs(p, "Geometry/2D Flow Areas/Attributes"),
    # HdfUtils
    "HdfUtils.read_crs_evidence": lambda p: _hdf().HdfUtils.read_crs_evidence(Path(p)),
    "HdfUtils.collect_hdf_crs_evidence": lambda p: _hdf().HdfUtils.collect_hdf_crs_evidence(Path(p)),
    # Text datasets (engine raw_fixed_strings)
    "HdfResultsPlan.get_compute_messages": lambda p: _hdf().HdfResultsPlan.get_compute_messages(Path(p)),
    "HdfResultsPlan.get_compute_messages_hdf_only": lambda p: _hdf().HdfResultsPlan.get_compute_messages_hdf_only(Path(p)),
    "HdfResultsPlan.get_steady_profile_names": lambda p: _hdf().HdfResultsPlan.get_steady_profile_names(Path(p)),
    "HdfPlan.get_plan_timestamps_list": lambda p: _hdf().HdfPlan.get_plan_timestamps_list(Path(p)),
    "HdfBase.get_unsteady_timestamps": lambda p: _hdf().HdfBase.get_unsteady_timestamps(Path(p)),
    "HdfBase.get_simulation_start_time": lambda p: _hdf().HdfBase.get_simulation_start_time(Path(p)),
}
