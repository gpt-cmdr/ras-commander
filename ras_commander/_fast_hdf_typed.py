"""Typed native dataset routing for public HDF readers (bridge API 9).

``read(dataset, selection)`` returns exactly what ``dataset[selection]`` returns
with h5py: same dtype (compounds included), shape, values and bits. When the
dataset belongs to a family that the pinned engine reads *typed* (Wave 8 mesh
geometry and 2D line families, Wave 2 1D geometry/results/summary/structures),
the values come from that typed engine reader instead of h5py.

Backend policy follows :mod:`ras_commander.fast_hdf`:

- ``python`` (``RAS_COMMANDER_FAST_HDF=0``): h5py only.
- ``auto``: typed engine read; any engine refusal or failure falls back to the
  h5py read, so public results and exceptions stay exactly the h5py ones.
- ``rust`` (``required``): typed routes must succeed or raise ``FastHdfError``.

Datasets outside every typed family keep the established behaviour: numeric
arrays use the generic native reader (``fast_hdf.read_dataset``), compound or
string metadata without an engine raw-byte reader stays on h5py in every mode
(recorded as ``h5py-metadata``). ``trace_reads()`` records the backend that
actually served each read so qualification tests can prove execution.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
from threading import RLock

import h5py
import numpy as np

from .LoggingConfig import get_logger

logger = get_logger(__name__)

_DEFAULT_MAX_BYTES = 67108864
_TRACE: ContextVar = ContextVar("ras_commander_typed_trace", default=None)

UNSTEADY_BASE = "Results/Unsteady/Output/Output Blocks/Base Output"
STEADY_BASE = "Results/Steady/Output/Output Blocks/Base Output"
XS_RESULT_GROUPS = {
    f"{STEADY_BASE}/Steady Profiles/Cross Sections": "steady",
    f"{UNSTEADY_BASE}/Unsteady Time Series/Cross Sections": "unsteady",
}
SUMMARY_GROUP = f"{UNSTEADY_BASE}/Summary Output"
STRUCTURE_GROUPS = {
    f"{UNSTEADY_BASE}/Unsteady Time Series/Inline Structures": ("inline_structure", "unsteady"),
    f"{UNSTEADY_BASE}/Unsteady Time Series/Bridges": ("bridge", "unsteady"),
    f"{UNSTEADY_BASE}/Unsteady Time Series/Culverts": ("culvert", "unsteady"),
    f"{UNSTEADY_BASE}/Unsteady Time Series/Pumping Stations": ("pump_station", "unsteady"),
    f"{STEADY_BASE}/Steady Profiles/Lateral Structures": ("lateral_structure", "steady"),
    f"{STEADY_BASE}/Steady Profiles/Storage Areas": ("storage_area", "steady"),
}
LINE_GROUPS = {
    "Geometry/Cross Sections": ("cross_section_cut_lines", "Polyline"),
    "Geometry/River Centerlines": ("river_centerlines", "Polyline"),
    "Geometry/River Bank Lines": ("river_bank_lines", "Polyline"),
    "Geometry/River Edge Lines": ("river_edge_lines", "Polyline"),
    "Geometry/River Flow Paths": ("river_flow_paths", "Flow Path Lines"),
}
LINE_FAMILY_IN_GROUPS = {
    "Geometry/Structures": ("structure_centerlines", "Centerline"),
    "Geometry/Storage Areas": ("storage_area_polygons", "Polygon"),
}
GEOMETRY_GROUPS = {
    "Geometry/Structures": "structures",
    "Geometry/Pump Stations": "pump_stations",
    "Geometry/Storage Areas": "storage_areas",
}
FAMILIES_2D = {
    "Geometry/Boundary Condition Lines": ("boundary_conditions", "Polyline"),
    "Geometry/2D Flow Area Break Lines": ("breaklines", "Polyline"),
    "Geometry/2D Flow Area Refinement Regions": ("refinement_regions", "Polygon"),
    "Geometry/Reference Lines": ("reference_lines", "Polyline"),
    "Geometry/Land Cover (Manning's n)": ("calibration_regions", "Polygon"),
}
XS_FIELDS = {
    "Station Elevation Info": ("station_elevation", "info"),
    "Station Elevation Values": ("station_elevation", "values"),
    "Manning's n Info": ("mannings_n", "info"),
    "Manning's n Values": ("mannings_n", "values"),
    "Ineffective Info": ("ineffective_areas", "info"),
    "Ineffective Blocks": ("ineffective_areas", "values"),
    "Deck High Info": ("deck_high", "info"),
    "Deck High Values": ("deck_high", "values"),
    "Deck Low Info": ("deck_low", "info"),
    "Deck Low Values": ("deck_low", "values"),
    "Property Tables/XSEC Info": ("property_table", "info"),
    "Property Tables/XSEC Value": ("property_table", "values"),
    "Property Tables/Cell Info": ("property_cells", "info"),
    "Property Tables/Cell Value": ("property_cells", "values"),
}
MESH_FIELDS = {
    "Faces Minimum Elevation": "face_minimum_elevation",
    "Cells Center Manning's n": "cell_mannings_n",
    "FacePoints Is Perimeter": "face_point_is_perimeter",
    "Cells Center Coordinate": "cell_centers",
    "Cells Minimum Elevation": "cell_minimum_elevation",
    "FacePoints Coordinate": "face_points",
    "Faces FacePoint Indexes": "face_point_indexes",
    "Faces Cell Indexes": "face_cell_indexes",
    "Faces NormalUnitVector and Length": "face_normals_and_length",
    "Faces Perimeter Info": "face_perimeter_info",
    "Faces Perimeter Values": "face_perimeter_values",
    "Cells Face and Orientation Info": "cell_face_info",
    "Cells Face and Orientation Values": "cell_face_values",
    "Cells FacePoint Indexes": "cell_face_point_indexes",
    "Perimeter": "perimeter",
    "Faces Area Elevation Info": "face_area_elevation_info",
    "Faces Area Elevation Values": "face_area_elevation_values",
    "Cells Volume Elevation Info": "cell_volume_elevation_info",
    "Cells Volume Elevation Values": "cell_volume_elevation_values",
}


class TypedRouteError(RuntimeError):
    """A typed engine result does not reproduce the stored dataset."""


# --------------------------------------------------------------------------- trace
@contextmanager
def trace_reads():
    """Record ``{"path", "backend", "route"}`` for every read served here."""
    records = []
    token = _TRACE.set(records)
    try:
        yield records
    finally:
        _TRACE.reset(token)


def _record(path, backend, route=None):
    records = _TRACE.get()
    if records is not None:
        records.append({"path": path, "backend": backend, "route": route})


# --------------------------------------------------------------------------- cache
_cache = OrderedDict()
_cache_lock = RLock()
_CACHE_LIMIT = 16


def clear_cache(path=None):
    resolved = None if path is None else str(Path(path).resolve())
    with _cache_lock:
        for key in list(_cache):
            if resolved is None or key[0] == resolved:
                del _cache[key]


def _cached(file_path, call_key, loader):
    enabled = os.environ.get("RAS_COMMANDER_HDF_SESSION_CACHE", "1").strip().lower() not in {
        "0", "false", "off"}
    resolved = Path(file_path).resolve()
    if not enabled:
        return loader()
    stat = resolved.stat()
    key = (str(resolved), stat.st_size, stat.st_mtime_ns, call_key)
    with _cache_lock:
        for old in list(_cache):
            if old[0] == key[0] and old[1:3] != key[1:3]:
                del _cache[old]
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    value = loader()
    with _cache_lock:
        _cache[key] = value
        while len(_cache) > _CACHE_LIMIT:
            _cache.popitem(last=False)
    return value


# --------------------------------------------------------------------------- routes
def route_for(name):
    """Return the typed route for an HDF dataset path, or None."""
    path = name.strip("/")
    parent, _, leaf = path.rpartition("/")
    for group, (kind, mode) in STRUCTURE_GROUPS.items():
        if path.startswith(group + "/"):
            rest = path[len(group) + 1:]
            structure, _, relative = rest.partition("/")
            if relative:
                return ("structure_series", kind, mode, structure, relative)
            return ("structure_family", kind, mode, None, structure)
    for group, mode in XS_RESULT_GROUPS.items():
        if path.startswith(group + "/"):
            return ("xs_result", mode, path[len(group) + 1:])
    if path.startswith(SUMMARY_GROUP + "/"):
        family, _, rest = path[len(SUMMARY_GROUP) + 1:].partition("/")
        if family != "2D Flow Areas" and rest:
            return ("one_d_summary", family, rest)
        return None
    if path.startswith("Geometry/Cross Sections/"):
        rel = path[len("Geometry/Cross Sections/"):]
        if rel in XS_FIELDS:
            return ("xs_geometry",) + XS_FIELDS[rel]
    if parent in LINE_FAMILY_IN_GROUPS:
        family, prefix = LINE_FAMILY_IN_GROUPS[parent]
        if leaf in {f"{prefix} {s}" for s in ("Info", "Parts", "Points")}:
            # Packed geometry is served by the validated line family, not the raw group dump.
            return ("line_family", family, leaf)
    for group, family in GEOMETRY_GROUPS.items():
        if path.startswith(group + "/"):
            return ("geometry_group", family, path[len(group) + 1:])
    if parent in LINE_GROUPS:
        family, prefix = LINE_GROUPS[parent]
        if leaf == "Attributes" or leaf in {f"{prefix} {s}" for s in ("Info", "Parts", "Points")}:
            return ("line_family", family, leaf)
    if parent in FAMILIES_2D:
        family, prefix = FAMILIES_2D[parent]
        return ("geometry_family", family, leaf)
    if parent == "Geometry/Junctions" and leaf in {"Attributes", "Points"}:
        return ("junctions", leaf)
    if parent == "Geometry/Cross Section Interpolation Surfaces":
        return ("interpolation_surfaces", leaf)
    if path in {"Geometry/2D Flow Areas/Attributes", "Geometry/2D Flow Areas/Cell Info"}:
        return ("mesh_tables", leaf)
    if path.startswith("Geometry/2D Flow Areas/"):
        rest = path[len("Geometry/2D Flow Areas/"):]
        area, _, dataset = rest.partition("/")
        if dataset in MESH_FIELDS:
            return ("mesh_geometry", area, MESH_FIELDS[dataset])
    return None


def _compound(table, dataset):
    """Rebuild the h5py structured array from the engine's exact stored bytes."""
    dtype = dataset.dtype
    if dtype.names is None:
        raise TypedRouteError(f"{dataset.name}: engine returned a compound for a non-compound dataset")
    raw = table["raw_bytes"]
    shape = tuple(int(n) for n in table["shape"])
    if shape != dataset.shape:
        raise TypedRouteError(f"{dataset.name}: compound shape {shape} versus {dataset.shape}")
    if len(raw) != int(np.prod(shape, dtype=np.int64)) * dtype.itemsize:
        raise TypedRouteError(f"{dataset.name}: compound byte length differs from h5py itemsize")
    columns = [(c["name"], int(c["byte_offset"])) for c in table["columns"]]
    expected = [(n, int(dtype.fields[n][1])) for n in dtype.names]
    if columns != expected:
        raise TypedRouteError(f"{dataset.name}: compound member layout differs from h5py")
    return np.frombuffer(bytes(raw), dtype=dtype).reshape(shape).copy()


def _numeric(values, dataset):
    values = np.asarray(values)
    dtype = dataset.dtype
    if dtype.names is not None or dtype.kind not in "iuf":
        raise TypedRouteError(f"{dataset.name}: numeric engine value for non-numeric dataset")
    if values.dtype.kind != dtype.kind or values.dtype.itemsize != dtype.itemsize:
        raise TypedRouteError(f"{dataset.name}: dtype {values.dtype} versus {dtype}")
    if values.shape != dataset.shape:
        raise TypedRouteError(f"{dataset.name}: shape {values.shape} versus {dataset.shape}")
    return values.astype(dtype, copy=False)


def _budget(dataset):
    return max(_DEFAULT_MAX_BYTES, 4 * int(dataset.size) * dataset.dtype.itemsize + 4096)


def _packed_is_stored(info, rows):
    """Records 0..n-1 packed in order equal the stored Values only when contiguous."""
    info = np.asarray(info)
    if info.ndim != 2 or info.shape[1] < 2:
        return False
    starts = info[:, 0].astype(np.int64)
    counts = info[:, 1].astype(np.int64)
    expected = np.concatenate(([0], np.cumsum(counts)[:-1])) if len(counts) else counts
    return bool(np.array_equal(starts, expected)) and int(counts.sum()) == rows


def _full(module, file_path, route, dataset):
    """Full stored array for one dataset from its typed engine family."""
    kind = route[0]
    budget = _budget(dataset)
    if kind == "line_family":
        _, family, leaf = route
        data = _cached(file_path, ("line", family), lambda: module.one_d_line_family(file_path, family))
        value = _value(data, dataset)
        if leaf == "Attributes":
            if value["attributes"] is None:
                raise TypedRouteError(f"{dataset.name}: engine family has no Attributes")
            return _compound(value["attributes"], dataset)
        return _numeric(value[leaf.rsplit(" ", 1)[1].lower()], dataset)
    if kind == "geometry_family":
        _, family, leaf = route
        data = _cached(file_path, ("family2d", family), lambda: module.geometry_family(file_path, family))
        value = _value(data, dataset)
        prefix = FAMILIES_2D[dataset.parent.name.strip("/")][1]
        if leaf == "Attributes":
            return _compound(value["attributes"], dataset)
        for suffix in ("Info", "Parts", "Points"):
            if leaf == f"{prefix} {suffix}":
                return _numeric(value[suffix.lower()], dataset)
        tables = dict(value["tables"])
        if leaf in tables:
            return _compound(tables[leaf], dataset)
        profiles = dict(value["terrain_profiles"])
        if leaf in profiles:
            return _numeric(profiles[leaf], dataset)
        raise TypedRouteError(f"{dataset.name}: not part of the typed {family} family")
    if kind == "xs_geometry":
        _, field, part = route
        data = _cached(file_path, ("xsgeom", field), lambda: module.read_xs_geometry(
            file_path, field, max_bytes=max(budget, _DEFAULT_MAX_BYTES * 4)))
        if part == "info":
            return _numeric(data["info"], dataset)
        stored_rows = int(dataset.shape[0]) if dataset.shape else 0
        if not _packed_is_stored(data["info"], stored_rows):
            raise TypedRouteError(f"{dataset.name}: Info ranges are not contiguous; packed values differ from storage")
        if data["values_kind"] == "compound":
            return _compound(data["values"], dataset)
        return _numeric(data["values"], dataset)
    if kind == "geometry_group":
        _, group, relative = route
        data = _cached(file_path, ("group", group), lambda: module.one_d_geometry_group(file_path, group))
        value = _value(data, dataset)
        tables = dict(value["tables"])
        arrays = dict(value["arrays"])
        if relative in tables:
            return _compound(tables[relative], dataset)
        if relative in arrays:
            return _numeric(arrays[relative], dataset)
        refused = dict(value["unsupported"])
        reason = refused.get(relative)
        raise TypedRouteError(f"{dataset.name}: not returned by the typed group reader ({reason})")
    if kind == "junctions":
        data = _cached(file_path, ("junctions",), lambda: module.river_junctions(file_path))
        value = _value(data, dataset)
        return _compound(value["attributes"], dataset) if route[1] == "Attributes" else _numeric(value["points"], dataset)
    if kind == "interpolation_surfaces":
        data = _cached(file_path, ("tin",), lambda: module.xs_interpolation_surfaces(file_path))
        value = _value(data, dataset)
        leaf = route[1]
        named = {"TIN Info": value["info"], "TIN Points": value["points"], "TIN Triangles": value["triangles"],
                 **dict(value["per_surface"])}
        if leaf not in named:
            raise TypedRouteError(f"{dataset.name}: not part of the typed interpolation surfaces")
        return _numeric(named[leaf], dataset)
    if kind == "xs_result":
        _, mode, variable = route
        rows = int(dataset.shape[0])
        out = module.read_xs_result(file_path, mode, variable, (0, rows, 1), max_bytes=budget)
        return _numeric(out["values"], dataset)
    if kind == "one_d_summary":
        _, family, name = route
        out = module.read_one_d_summary(file_path, family, name, max_bytes=budget)
        return _numeric(out["values"], dataset)
    if kind in {"structure_series", "structure_family"}:
        _, skind, mode, structure, relative = route
        if len(dataset.shape) != 2:
            raise TypedRouteError(f"{dataset.name}: typed structure series are rank two")
        values = module.read_one_d_structure_series(
            file_path, skind, mode, structure, relative, (0, int(dataset.shape[0]), 1), max_bytes=budget)
        return _numeric(values, dataset)
    if kind == "mesh_tables":
        data = _cached(file_path, ("meshtables",), lambda: module.mesh_geometry_tables(file_path))
        if route[1] == "Attributes":
            return _compound(data["attributes"], dataset)
        cell = data["cell_info"]
        if cell["value"] is None:
            raise TypedRouteError(f"{dataset.name}: {cell['capability']}")
        return _numeric(cell["value"], dataset)
    if kind == "mesh_geometry":
        _, area, field = route
        values = module.read_mesh_geometry(file_path, area, field, max_bytes=budget)
        return _numeric(values, dataset)
    raise TypedRouteError(f"unknown typed route {kind}")


def _member(module, file_path, route):
    """Whether the typed family inventory declares this dataset (identity tables excluded)."""
    kind = route[0]
    if kind == "xs_result":
        _, mode, variable = route
        inv = _cached(file_path, ("xsinv", mode), lambda: module.xs_result_inventory(file_path, mode))
        return any(v["name"] == variable for v in inv["variables"])
    if kind == "one_d_summary":
        _, family, name = route
        inv = _cached(file_path, ("suminv",), lambda: module.one_d_summary_inventory(file_path))
        return any(v["family"] == family and v["name"] == name for v in inv["variables"])
    if kind in {"structure_series", "structure_family"}:
        _, skind, mode, structure, relative = route
        inv = _cached(file_path, ("structinv", skind, mode),
                      lambda: module.one_d_structure_inventory(file_path, skind, mode))
        if structure is None:
            return any(s["relative"] == relative for s in inv["family_series"])
        for s in inv["structures"]:
            if s["name"] == structure:
                return any(x["relative"] == relative for x in s["series"])
        return False
    if kind == "geometry_family":
        family = route[1]
        data = _cached(file_path, ("family2d", family), lambda: module.geometry_family(file_path, family))
        # A canonically absent family (e.g. land-cover tables without calibration
        # polygons) has no typed reader; its tables stay h5py metadata.
        return data["capability"]["status"] != "unavailable"
    return True


def _value(reported, dataset):
    if reported.get("value") is None:
        raise TypedRouteError(f"{dataset.name}: typed family {reported.get('capability')}")
    return reported["value"]


def _basic(selection):
    if selection is None or selection is Ellipsis or selection == ():
        return True
    keys = selection if isinstance(selection, tuple) else (selection,)
    for key in keys:
        if key is Ellipsis or isinstance(key, slice):
            continue
        if isinstance(key, (int, np.integer)) and not isinstance(key, (bool, np.bool_)):
            continue
        return False
    return True


def read(dataset, selection=None, *, backend="auto"):
    """Read like ``dataset[selection]``; typed engine families serve the values."""
    from . import fast_hdf

    if not isinstance(dataset, h5py.Dataset):
        raise TypeError("dataset must be an open h5py.Dataset")
    key = () if selection is None else selection
    mode = fast_hdf._mode(backend)
    module = fast_hdf._native(mode)
    if module is None:
        _record(dataset.name, "h5py")
        return dataset[key]
    dtype = dataset.dtype
    metadata = dtype.names is None and (dtype.kind not in "iuf" or h5py.check_vlen_dtype(dtype) is not None)
    route = None if metadata or not hasattr(module, "read_xs_geometry") else route_for(dataset.name)
    if route is not None and route[0] in {"xs_result", "one_d_summary", "structure_series",
                                         "structure_family", "geometry_family"}:
        try:
            import os as _os
            if not _member(module, _os.fsdecode(dataset.file.filename), route):
                route = None
        except Exception as exc:
            if mode == "rust":
                raise fast_hdf.FastHdfError(f"Typed inventory failed for {dataset.name}: {exc}") from exc
            logger.debug("h5py fallback for typed inventory %s: %s", dataset.name, exc)
            _record(dataset.name, "h5py-fallback", route[0])
            return dataset[key]
    if route is None:
        if fast_hdf._numeric(dataset) and dataset.shape is not None:
            # read_dataset records the backend that served it (typed mesh
            # results, generic native, or h5py fallback).
            return fast_hdf.read_dataset(dataset, selection, backend=backend)
        _record(dataset.name, "h5py-metadata")
        return dataset[key]
    try:
        if not fast_hdf._safe_file(dataset):
            raise TypedRouteError(f"{dataset.name}: file cannot be reopened safely by the engine")
        if not _basic(selection):
            raise TypedRouteError(f"{dataset.name}: typed routes accept only basic selections")
        import os as _os
        file_path = _os.fsdecode(dataset.file.filename)
        full = _full(module, file_path, route, dataset)
        values = full[key]
        values = values.copy() if hasattr(values, "copy") else values
    except Exception as exc:
        if mode == "rust":
            if isinstance(exc, fast_hdf.FastHdfError):
                raise
            raise fast_hdf.FastHdfError(f"Typed native read failed for {dataset.name}: {exc}") from exc
        logger.debug("h5py fallback for typed %s: %s", dataset.name, exc)
        _record(dataset.name, "h5py-fallback", route[0])
        return dataset[key]
    _record(dataset.name, "native-typed", route[0])
    return values
