"""ROUTE-NONHDF cases: unsteady/precipitation, encroachment, breakout, Modified Puls,
eBFE audits and the RAS Mapper profile interop read helpers (group ``flow``).

Arguments (mesh names, sample points, child boundaries) are derived from the fixture
here with h5py (harness reads, exempt from the gate), identically in every mode.
"""
import importlib
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from ._case import Case

_PLAN_2D = frozenset({"plan"})
_GEOM_PLAN = frozenset({"plan", "geom"})


def _mesh_first(path):
    with h5py.File(path, "r") as f:
        key = "Geometry/2D Flow Areas/Attributes"
        if key not in f:
            return None
        rows = f[key][()]
    names = [r["Name"].decode(errors="replace").strip() for r in rows]
    return next((n for n in names if n), None)


def _centers(path, mesh):
    with h5py.File(path, "r") as f:
        key = f"Geometry/2D Flow Areas/{mesh}/Cells Center Coordinate"
        return f[key][()] if key in f else None


def _require_mesh(path):
    mesh = _mesh_first(path)
    if mesh is None or _centers(path, mesh) is None:
        pytest.skip("fixture has no 2D flow area cell centers")
    return mesh


def _child_box(path, mesh):
    from shapely.geometry import box
    centers = _centers(path, mesh)
    x0, y0 = centers.min(axis=0)
    x1, y1 = centers.max(axis=0)
    spacing = float(np.sqrt(max((x1 - x0) * (y1 - y0), 1.0) / max(len(centers), 1)))
    cx, cy = (float(v) for v in centers[len(centers) // 2])
    half = 4.0 * spacing
    return box(cx - half, cy - half, cx + half, cy + half)


# ----------------------------------------------------------------- parent_display (#543)
def _applied_forcing(p):
    from ras_commander.parent_display import probe_applied_forcing
    return probe_applied_forcing(Path(p))


def _geometry_features(p):
    from ras_commander.parent_display import probe_geometry_features
    return probe_geometry_features(Path(p))


# ----------------------------------------------------------------- _native_precip
def _inspect_precipitation(p):
    from ras_commander._native_precip import inspect_precipitation
    return inspect_precipitation(Path(p))


# ----------------------------------------------------------------- dotnet interop
def _interop():
    from ras_commander.dotnet import _profile_interop
    return _profile_interop


def _nearest_face_ids(p):
    mesh = _require_mesh(p)
    centers = _centers(p, mesh)
    picks = centers[np.linspace(0, len(centers) - 1, 5).astype(int)]
    names = np.array([mesh] * len(picks), dtype=object)
    return _interop()._nearest_face_ids(Path(p), picks[:, 0].copy(), picks[:, 1].copy(), names)


def _profile_times(p):
    context = SimpleNamespace(plan_hdf_path=Path(p), results=None)
    return _interop()._profile_times(context)


# ----------------------------------------------------------------- RasBreakout2D
def _select_faces(p):
    from ras_commander.RasBreakout2D import RasBreakout2D
    mesh = _require_mesh(p)
    return RasBreakout2D.select_parent_boundary_faces(Path(p), mesh, _child_box(p, mesh))


def _boundary_flow(prefer_native):
    def call(p):
        module = importlib.import_module("ras_commander.RasBreakout2D")
        mesh = _require_mesh(p)
        with h5py.File(p, "r") as f:
            if f"Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{mesh}" not in f:
                pytest.skip("fixture has no 2D mesh time series")
        try:
            faces = module.RasBreakout2D.select_parent_boundary_faces(Path(p), mesh, _child_box(p, mesh))
        except ValueError as exc:
            pytest.skip(f"no boundary faces for the derived child box: {exc}")
        return module._read_boundary_face_flow(Path(p), Path(p), mesh, faces, prefer_native=prefer_native)
    return call


# ----------------------------------------------------------------- RasEncroachments
def _feature_table(kind):
    def call(p):
        module = importlib.import_module("ras_commander.RasEncroachments")
        group = module._REGIONS_GROUP if kind == "regions" else module._ZONES_GROUP
        return module._read_feature_table(Path(p), group, kind)
    return call


def _encroachment_settings(p):
    from ras_commander.RasEncroachments import RasEncroachments
    plan_text = Path(p[:-4])
    if not plan_text.is_file():
        pytest.skip("plan text file absent next to the plan HDF (public method resolves it)")
    return RasEncroachments.get_2d_encroachment_plan_settings(plan_text, prefer_results_hdf=True)


# ----------------------------------------------------------------- RasModPuls
def _storage_outflow(p):
    from shapely.geometry import LineString
    from ras_commander.RasModPuls import RasModPuls
    mesh = _require_mesh(p)
    centers = _centers(p, mesh)
    x0, y0 = centers.min(axis=0)
    x1, y1 = centers.max(axis=0)
    xm = float((x0 + x1) / 2)
    line = LineString([(xm, float(y0)), (xm, float(y1))])
    return RasModPuls.extract_storage_outflow(Path(p), line, "", flow_area_name=mesh,
                                              distance_threshold=1e9)


# ----------------------------------------------------------------- RasUnsteady
def _ic_entries(p):
    from ras_commander.RasUnsteady import RasUnsteady
    return RasUnsteady._read_output_profile_ic_entries(Path(p), -1, True, True)


def _precip_attrs(p):
    from ras_commander.RasUnsteady import RasUnsteady
    config = {}
    RasUnsteady._read_hdf_precip_attrs(config, Path(p[:-4]))
    return config


def _preflight_ratio(p):
    from ras_commander.RasUnsteady import RasUnsteady
    return RasUnsteady._preflight_precipitation_ratio(Path(p[:-4]), None, None)


# ----------------------------------------------------------------- eBFE
def _medina_associations(p):
    from ras_commander.sources.federal import ebfe_medina
    spec = {"geometry_hdf": Path(p).name, "terrain_hdf": None}
    return ebfe_medina._association_paths_are_valid(Path(p).parent, spec)


CASES = {
    "_native_precip.inspect_precipitation": Case(
        _inspect_precipitation, kinds={"plan", "unsteady"}, max_mb=100,
        note="block digest of every 2D result series; h5py mode alone takes minutes on larger plans"),
    "_profile_interop._uses_si_units": Case(lambda p: _interop()._uses_si_units(Path(p)), kinds=_GEOM_PLAN),
    "_profile_interop._smallest_mesh_face_length": Case(
        lambda p: _interop()._smallest_mesh_face_length(Path(p)), kinds=_GEOM_PLAN),
    "_profile_interop._mesh_names_from_hdf": Case(
        lambda p: _interop()._mesh_names_from_hdf(Path(p)), kinds=_GEOM_PLAN),
    "_profile_interop._nearest_face_ids": Case(_nearest_face_ids, kinds=_GEOM_PLAN,
                                               helper="RasProfileInterop map-points renderers"),
    "_profile_interop._profile_times": Case(_profile_times, kinds=_PLAN_2D,
                                            helper="RasProfileInterop profile renderers"),
    "RasBreakout2D.select_parent_boundary_faces": Case(_select_faces, kinds=_GEOM_PLAN, max_mb=100,
                                                       note="face geometry construction"),
    "RasBreakout2D._read_boundary_face_flow[native]": Case(
        _boundary_flow(True), kinds=_PLAN_2D, max_mb=100,
        helper="RasBreakout2D.review_parent_boundary_flux (needs a Breakout2DPreflight)"),
    "RasBreakout2D._read_boundary_face_flow[reconstructed]": Case(
        _boundary_flow(False), kinds=_PLAN_2D, max_mb=100,
        helper="RasBreakout2D.review_parent_boundary_flux (needs a Breakout2DPreflight)"),
    "RasEncroachments._read_feature_table[regions]": Case(
        _feature_table("regions"), kinds=_GEOM_PLAN,
        helper="RasEncroachments.list_2d_encroachment_regions (needs a plan text file)"),
    "RasEncroachments._read_feature_table[zones]": Case(
        _feature_table("zones"), kinds=_GEOM_PLAN,
        helper="RasEncroachments.list_2d_encroachment_zones (needs a plan text file)"),
    "RasEncroachments.get_2d_encroachment_plan_settings": Case(_encroachment_settings, kinds=_PLAN_2D),
    "RasModPuls.extract_storage_outflow": Case(_storage_outflow, kinds=_PLAN_2D, max_mb=100,
                                               note="mesh cell faces construction"),
    "RasUnsteady._read_output_profile_ic_entries": Case(
        _ic_entries, kinds=_PLAN_2D,
        helper="RasUnsteady.set_ic_from_output_profile (writes the .u## file)"),
    "RasUnsteady._read_hdf_precip_attrs": Case(_precip_attrs, kinds={"plan", "unsteady"},
                                               helper="RasUnsteady.get_precipitation_config"),
    "RasUnsteady._preflight_precipitation_ratio": Case(
        _preflight_ratio, kinds={"plan", "unsteady"},
        helper="RasUnsteady gridded precipitation writers (preflight before mutation)"),
    "ebfe_medina._association_paths_are_valid": Case(_medina_associations, kinds=_GEOM_PLAN,
                                                     helper="ebfe_medina.medina_is_reusable"),
    "parent_display.probe_applied_forcing": Case(_applied_forcing, kinds=_PLAN_2D),
    "parent_display.probe_geometry_features": Case(_geometry_features, kinds=_GEOM_PLAN),
}
