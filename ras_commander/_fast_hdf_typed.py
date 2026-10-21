"""Typed native dataset routing for public HDF readers (bridge API 10).

``read(dataset, selection)`` returns exactly what ``dataset[selection]`` returns
with h5py: same dtype (compounds included), shape, values and bits. When the
dataset belongs to a family that the pinned engine reads *typed* (Wave 8 mesh
geometry and 2D line families, Wave 2 1D geometry/results/summary/structures),
the values come from that typed engine reader instead of h5py. Wave 3 stored
families (pipes, reference lines/points, breach, plan metadata tables, land
cover/infiltration sidecars, terrain, sediment, encroachments, Event
Conditions, steady output, non-Base output blocks) are found through the
engine's ``stored_family_index``: supported numeric, compound and byte-bitfield
datasets are read with ``read_family_dataset``/``read_output_block``. Datasets
the engine lists but does not qualify (for example pipe summaries without a
stored ``Location``) keep their exact literal values through the generic reader.

Backend policy follows :mod:`ras_commander.fast_hdf`:

- ``python`` (``RAS_COMMANDER_FAST_HDF=0``): h5py only.
- ``auto``: typed engine read; any engine refusal or failure falls back to the
  h5py read, so public results and exceptions stay exactly the h5py ones.
- ``rust`` (``required``): typed routes must succeed or raise ``FastHdfError``.

Datasets outside every typed family use the generic native reader
(``fast_hdf.read_dataset``); in auto mode any native failure there (including
Corrupt/checksum refusals) also falls back to h5py. Text datasets and text-only
compound identity tables stay on h5py in every mode (recorded as
``h5py-metadata``): this is the documented required-mode metadata exception. A
compound with any numeric member and no typed route is value data: auto reads it
with h5py (``h5py-fallback``/``untyped-compound``) and required mode refuses.

Selections are validated with h5py's own selector before any native read, so an
invalid selection raises h5py's exact exception in every mode. Basic selections
and single increasing integer vectors are served natively; field names, boolean
masks, non-integer vectors (an empty list included) and scalar-dataspace
indexing are left to h5py (refused in required mode).

``trace_reads()`` records the backend that served each read made *through these
wrappers*. It is not a complete I/O audit: reads a caller makes directly with
h5py are invisible to it (the route-1 gate intercepts h5py separately).
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
    if parent == "Geometry/Reference Points" and leaf in {"Attributes", "Points"}:
        return ("reference_point_geometry", leaf)
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
    values = np.frombuffer(bytes(raw), dtype=dtype).reshape(shape).copy()
    for column in table["columns"]:
        _h5py_fixed_text(values, column, dataset)
    return values


def _h5py_fixed_text(values, column, dataset):
    """Apply HDF5's fixed-string conversion that h5py's NULLPAD memory type triggers.

    h5py reads fixed strings as NumPy ``S`` (HDF5 NULLPAD). A stored NULLPAD member is
    copied unchanged. A NULLTERM member is cut at its first NUL and a SPACEPAD member
    loses its trailing spaces; the rest of the field is zero-filled, exactly as
    HDF5's string conversion does. The engine returns the stored bytes, so the same
    rule is applied here from the engine's member padding evidence.
    """
    kind = column.get("attribute_type") or {}
    if kind.get("kind") != "fixed_string":
        return
    name = column["name"]
    field = values.dtype.fields[name][0]
    if field.kind != "S" or field.itemsize != int(kind["width"]):
        raise TypedRouteError(f"{dataset.name}: member {name} is not a fixed string of the stored width")
    padding = kind.get("padding")
    if padding == "null_pad":
        return
    if padding not in {"null_terminate", "space_pad"}:
        raise TypedRouteError(f"{dataset.name}: member {name} has unproven string padding {padding}")
    raw = np.frombuffer(values[name].tobytes(), dtype=np.uint8).reshape(-1, field.itemsize).copy()
    for row in raw:
        data = row.tobytes()
        if padding == "space_pad":
            size = len(data.rstrip(b" "))
        else:
            cut = data.find(b"\0")
            size = len(data) if cut < 0 else cut
        row[size:] = 0
    values[name] = raw.view(field).reshape(values[name].shape)


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
    if kind == "reference_point_geometry":
        if not hasattr(module, "reference_point_geometry"):
            raise TypedRouteError(f"{dataset.name}: extension lacks reference_point_geometry")
        data = _cached(file_path, ("refpoints",), lambda: module.reference_point_geometry(file_path))
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
        # Cached so element-wise public readers index one native array.
        values = _cached(file_path, ("meshgeom", area, field),
                         lambda: module.read_mesh_geometry(file_path, area, field, max_bytes=budget))
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
        # Listed but unqualified (e.g. Pipe Networks summaries) is not membership:
        # the literal values then come from the generic reader.
        return any(v["family"] == family and v["name"] == name
                   and v["capability"]["status"] == "supported" for v in inv["variables"])
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


# ------------------------------------------------------------------ Wave 3 stored families
STORED_STORAGE = {"numeric", "compound", "bitfield_bytes"}
OUTPUT_BLOCKS = "Results/Unsteady/Output/Output Blocks/"


def _stored_index(module, file_path):
    """Per-file map ``path -> row`` over every Wave 3 read family and non-Base output block.

    The engine inventories decide membership and qualification; rows carry storage,
    shape, dtype and capability. Read families take precedence over output blocks.
    """
    def load():
        index = module.stored_family_index(file_path)
        rows = {}
        for row in index["datasets"]:
            current = rows.get(row["path"])
            if current is None or (current["owner"].startswith("output_block:")
                                   and not row["owner"].startswith("output_block:")):
                rows[row["path"]] = row
        return rows
    return _cached(file_path, ("stored_family_index",), load)


def _stored_route(module, dataset):
    """``("stored_family", owner, path, storage)`` for a supported Wave 3 stored dataset.

    Datasets the engine lists but refuses to qualify (for example pipe summaries
    without a stored ``Location`` attribute) return ``None``: their literal values
    are then served by the generic native reader. Strings are never routed here
    (decoded engine text cannot prove h5py's exact fixed-length bytes).
    """
    from . import fast_hdf

    if not fast_hdf._safe_file(dataset):
        return None
    path = dataset.name.strip("/")
    row = _stored_index(module, os.fsdecode(dataset.file.filename)).get(path)
    if row is None or row["status"] != "supported" or row["storage"] not in STORED_STORAGE:
        return None
    return ("stored_family", row["owner"], path, row["storage"])


def _stored_read(module, file_path, route, dataset, key):
    """Exact ``dataset[key]`` from the engine's stored family/output-block reader."""
    from . import fast_hdf

    _, owner, path, storage = route
    budget = _budget(dataset)
    slices = squeeze = None
    if storage == "numeric":
        try:
            empty = isinstance(key, tuple) and len(key) == 0
            slices, squeeze = fast_hdf._selection(dataset.shape, None if empty else key)
        except (NotImplementedError, IndexError, ValueError):
            slices = None
    native_slices = None if slices is None else [tuple(int(v) for v in s) for s in slices]
    if owner.startswith("output_block:"):
        block = owner.split(":", 1)[1]
        prefix = f"{OUTPUT_BLOCKS}{block}/"
        if not path.startswith(prefix):
            raise TypedRouteError(f"{dataset.name}: outside output block {block}")
        out = module.read_output_block(file_path, block, path[len(prefix):], native_slices,
                                       max_bytes=budget)
    else:
        out = module.read_family_dataset(file_path, owner, path, native_slices,
                                         metadata_max_bytes=budget, max_bytes=budget)
    if out["storage"] != storage:
        raise TypedRouteError(f"{dataset.name}: engine storage {out['storage']} versus index {storage}")
    if storage == "compound":
        return _compound(out["values"], dataset)[key].copy()
    if storage == "bitfield_bytes":
        dtype = dataset.dtype
        if dtype.names is not None or dtype.kind != "u" or dtype.itemsize != 1:
            raise TypedRouteError(f"{dataset.name}: bitfield bytes for h5py dtype {dtype}")
        shape = tuple(int(n) for n in out["shape"])
        if shape != dataset.shape or len(out["raw_bytes"]) != int(np.prod(shape, dtype=np.int64)):
            raise TypedRouteError(f"{dataset.name}: bitfield shape {shape} versus {dataset.shape}")
        return np.frombuffer(bytes(out["raw_bytes"]), dtype=dtype).reshape(shape)[key].copy()
    values = np.asarray(out["values"])
    if slices is None:
        return _numeric(values, dataset)[key].copy()
    dtype = dataset.dtype
    if values.dtype.kind != dtype.kind or values.dtype.itemsize != dtype.itemsize:
        raise TypedRouteError(f"{dataset.name}: dtype {values.dtype} versus {dtype}")
    expected = tuple(len(range(*s)) for s in slices)
    if values.shape != expected:
        raise TypedRouteError(f"{dataset.name}: shape {values.shape} versus {expected}")
    values = values.astype(dtype, copy=False)
    if squeeze:
        values = np.squeeze(values, axis=squeeze)
    return values[()] if values.ndim == 0 else values


# ------------------------------------------------------------------ attributes
def _typed_attributes(module, obj):
    """Engine typed attributes of a group, or of a dataset in a Wave 3 family."""
    file_path = os.fsdecode(obj.file.filename)
    name = obj.name
    if isinstance(obj, h5py.Group):
        return _cached(file_path, ("group_attrs", name),
                       lambda: {a["name"]: a for a in module.typed_group_attributes(file_path, name)})
    path = name.strip("/")
    row = _stored_index(module, file_path).get(path)
    if row is None:
        return None
    if row["owner"].startswith("output_block:"):
        blocks = _cached(file_path, ("output_block_inventory",),
                         lambda: module.output_block_inventory(file_path))
        datasets = [d for b in blocks for d in b["datasets"]]
    else:
        inventory = _cached(file_path, ("family_inventory", row["owner"]),
                            lambda: module.read_family_inventory(file_path, row["owner"]))
        datasets = inventory["datasets"]
    for dataset in datasets:
        if dataset["path"] == path:
            return {a["name"]: a for a in dataset["attributes"]}
    return None


def read_attrs(obj, *, backend="auto"):
    """``{name: obj.attrs[name]}`` in h5py's key order, values from the engine.

    Attribute names and their order come from h5py (a key walk, no value read);
    each value is rebuilt from the engine's typed attribute by
    :func:`attribute_value`. Groups use ``typed_group_attributes``; datasets use
    their Wave 3 family inventory or non-Base output-block descriptor. A dataset outside every family has no engine
    attribute reader: its attributes stay on h5py in every mode (the documented
    metadata exception, traced ``h5py-metadata``/``attrs``). For a value the engine
    cannot reproduce exactly, auto reads that attribute with h5py and required
    mode raises ``FastHdfError``.
    """
    from . import fast_hdf

    if not isinstance(obj, (h5py.Group, h5py.Dataset)):
        raise TypeError("obj must be an open h5py.Group or h5py.Dataset")
    mode = fast_hdf._mode(backend)
    module = fast_hdf._native(mode)
    names = list(obj.attrs)
    if module is None:
        _record(obj.name, "h5py", "attrs")
        return {k: obj.attrs[k] for k in names}
    try:
        typed = (_typed_attributes(module, obj) if fast_hdf._safe_file(obj) else None)
    except Exception as exc:
        if mode == "rust":
            raise fast_hdf.FastHdfError(f"Typed attributes failed for {obj.name}: {exc}") from exc
        _record(obj.name, "h5py-fallback", "attrs")
        return {k: obj.attrs[k] for k in names}
    if typed is None:
        _record(obj.name, "h5py-metadata", "attrs")
        return {k: obj.attrs[k] for k in names}
    out = {}
    fallback = False
    for key in names:
        try:
            if key not in typed:
                raise TypedRouteError(f"attribute {key!r} missing from the engine reader")
            out[key] = attribute_value(typed[key])
        except TypedRouteError as exc:
            if mode == "rust":
                raise fast_hdf.FastHdfError(f"{obj.name}: {exc}") from exc
            out[key] = obj.attrs[key]
            fallback = True
    _record(obj.name, "h5py-fallback" if fallback else "native-typed", "attrs")
    return out


def attribute_value(typed):
    """Exact ``obj.attrs[name]`` value from one engine typed attribute.

    Reproduces h5py 3 semantics from the stored bytes and declared type: numeric
    attributes become a NumPy scalar (scalar dataspace) or array in the stored
    dtype and byte order; fixed-length strings become ``numpy.bytes_`` (or an
    ``S{width}`` array) after HDF5's conversion into h5py's NULLPAD memory type
    (NULLTERM: cut at the first NUL; SPACEPAD: trailing spaces removed; NULLPAD:
    unchanged), with NumPy's trailing-NUL stripping. Any other class (variable-
    length, compound, bitfield, enum, references) or an unsupported/corrupt value
    raises :class:`TypedRouteError`, so the caller falls back or refuses.
    """
    if typed.get("capability", {}).get("status") != "supported":
        raise TypedRouteError(f"attribute {typed.get('name')!r}: {typed.get('capability')}")
    kind = typed["attribute_type"]
    shape = tuple(int(n) for n in typed["shape"])
    raw = bytes(typed["raw_bytes"])
    count = int(np.prod(shape, dtype=np.int64)) if shape else 1
    if kind["kind"] in {"integer", "float"}:
        order = {"little": "<", "big": ">"}.get(kind.get("byte_order"))
        if order is None:
            raise TypedRouteError(f"attribute {typed['name']!r}: byte order {kind.get('byte_order')}")
        code = "f" if kind["kind"] == "float" else ("i" if kind["signed"] else "u")
        dtype = np.dtype(f"{order}{code}{int(kind['bytes'])}")
        if len(raw) != count * dtype.itemsize:
            raise TypedRouteError(f"attribute {typed['name']!r}: {len(raw)} bytes for {count} x {dtype}")
        values = np.frombuffer(raw, dtype=dtype).copy()
        return values[0] if not shape else values.reshape(shape)
    if kind["kind"] == "fixed_string":
        width = int(kind["width"])
        padding = kind.get("padding")
        if padding not in {"null_terminate", "null_pad", "space_pad"} or len(raw) != count * width:
            raise TypedRouteError(f"attribute {typed['name']!r}: unproven fixed string layout")
        items = []
        for i in range(count):
            data = raw[i * width:(i + 1) * width]
            if padding == "space_pad":
                data = data.rstrip(b" ")
            elif padding == "null_terminate":
                cut = data.find(bytes(1))
                data = data if cut < 0 else data[:cut]
            items.append(data)
        values = np.array(items, dtype=f"S{max(width, 1)}")
        # h5py returns arr[()] of an S{width} array: same scalar construction.
        return values.reshape(())[()] if not shape else values.reshape(shape)
    raise TypedRouteError(f"attribute {typed['name']!r}: {kind['kind']} attributes are not reproduced")


def _has_numeric_field(dtype):
    """Whether a compound dtype has any member that is not fixed or vlen text."""
    for name in dtype.names:
        field = dtype.fields[name][0]
        if field.names is not None:
            if _has_numeric_field(field):
                return True
        elif field.subdtype is not None:
            base = field.subdtype[0]
            if base.kind not in "SU" and h5py.check_string_dtype(base) is None:
                return True
        elif field.kind not in "SU" and h5py.check_string_dtype(field) is None:
            return True
    return False


def _value(reported, dataset):
    if reported.get("value") is None:
        raise TypedRouteError(f"{dataset.name}: typed family {reported.get('capability')}")
    return reported["value"]


def _selection_shape(dataset, key):
    """Validate ``key`` with h5py's own selector (no value I/O); return its shape.

    Invalid selections raise h5py's exact exception (type and message) in every
    backend mode, e.g. ``ValueError: Step must be >= 1`` for a negative step.
    Valid basic selections and single increasing integer vectors are served by
    NumPy indexing of the full stored array and return the h5py result shape.
    ``None`` marks selections left to h5py (field names, boolean masks,
    non-integer vectors such as an empty list, indexing a scalar dataspace): a refusal in required
    mode and an h5py read in auto mode.
    """
    args = key if isinstance(key, tuple) else (key,)
    if dataset.shape is None or any(isinstance(a, (str, bytes)) for a in args):
        return None
    if dataset.shape == () and not (args == () or (len(args) == 1 and args[0] is Ellipsis)):
        return None
    for arg in args:
        if isinstance(arg, (list, np.ndarray)) and np.asarray(arg).dtype.kind not in "iu":
            return None
    return h5py_selection_shape(dataset, args)


def h5py_selection_shape(dataset, args):
    """Result shape of ``dataset[args]`` per h5py's own selector, without I/O.

    The single place that touches private h5py API: ``h5py._hl.selections.select
    (shape, args, dataset).array_shape``, verified on h5py 3.14 (the version this
    branch is qualified with; the module has had this form throughout h5py 3.x).
    Invalid selections raise h5py's own exception. If a future h5py moves or
    changes it, this returns ``None``: the selection is then left to h5py (an h5py
    read in auto mode, a refusal in required mode), never guessed natively.
    """
    try:
        from h5py._hl import selections
        select = selections.select
    except (ImportError, AttributeError):  # pragma: no cover - h5py layout change
        logger.debug("h5py selection helper unavailable; selection left to h5py")
        return None
    selection = select(dataset.shape, args, dataset)
    shape = getattr(selection, "array_shape", None)
    return None if shape is None else tuple(shape)


def _fancy(key):
    args = key if isinstance(key, tuple) else (key,)
    return any(isinstance(a, (list, np.ndarray)) for a in args)


def _generic(dataset, selection, key, shape, backend, mode):
    """Numeric dataset outside every typed family: generic native reader."""
    from . import fast_hdf

    try:
        if shape is not None and _fancy(key):
            # h5py point selections (validated increasing vectors) equal NumPy
            # indexing of the full stored array.
            values = np.asarray(fast_hdf.read_dataset(dataset, None, backend=backend))[key]
            return values.copy()
        # read_dataset records the backend that served it (typed mesh results,
        # generic native, or its own h5py fallback for unsupported layouts).
        return fast_hdf.read_dataset(dataset, selection, backend=backend)
    except fast_hdf.FastHdfError as exc:
        if mode == "rust":
            raise
        # Auto keeps the h5py public outcome for every native failure, including
        # Corrupt/checksum refusals, exactly like the typed routes.
        logger.debug("h5py fallback for generic %s: %s", dataset.name, exc)
        _record(dataset.name, "h5py-fallback", "generic")
        return dataset[key]


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
    shape = _selection_shape(dataset, key)
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
    if route is None and not metadata and hasattr(module, "stored_family_index"):
        try:
            route = _stored_route(module, dataset)
        except Exception as exc:
            if mode == "rust":
                raise fast_hdf.FastHdfError(f"Stored family index failed for {dataset.name}: {exc}") from exc
            logger.debug("h5py fallback for stored family index %s: %s", dataset.name, exc)
            _record(dataset.name, "h5py-fallback", "stored_family")
            return dataset[key]
    if route is None:
        if fast_hdf._numeric(dataset) and dataset.shape is not None:
            return _generic(dataset, selection, key, shape, backend, mode)
        if dtype.names is not None and _has_numeric_field(dtype):
            # A compound with numeric members is value data, not metadata: without
            # a typed engine route required mode refuses instead of reading h5py.
            if mode == "rust":
                raise fast_hdf.FastHdfError(
                    f"{dataset.name}: numeric compound has no typed engine route")
            _record(dataset.name, "h5py-fallback", "untyped-compound")
            return dataset[key]
        _record(dataset.name, "h5py-metadata")
        return dataset[key]
    try:
        if not fast_hdf._safe_file(dataset):
            raise TypedRouteError(f"{dataset.name}: file cannot be reopened safely by the engine")
        if shape is None:
            raise TypedRouteError(f"{dataset.name}: selection {key!r} is left to h5py")
        import os as _os
        file_path = _os.fsdecode(dataset.file.filename)
        if route[0] == "stored_family":
            values = _stored_read(module, file_path, route, dataset, key)
        else:
            values = _full(module, file_path, route, dataset)[key]
        if np.shape(values) != shape:
            raise TypedRouteError(f"{dataset.name}: selection shape {np.shape(values)} versus h5py {shape}")
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
