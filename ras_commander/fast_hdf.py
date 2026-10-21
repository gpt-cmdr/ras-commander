"""Optional Rust numeric reads, mesh assembly, and direct PMTiles export.

Ordinary installations need no native extension. ``RAS_COMMANDER_FAST_HDF=0``
disables automatic acceleration; ``required`` proves native execution in
qualification runs. Explicit ``backend='python'`` or ``'rust'`` overrides the
environment. Metadata and unsupported HDF types continue to use h5py in auto
mode. h5py behaviour is the public contract: in auto mode any native failure
(Corrupt/checksum refusals included) falls back to the h5py read, so callers see
the h5py outcome; ``required`` raises :class:`FastHdfError` instead.
"""

from __future__ import annotations

from contextlib import nullcontext, contextmanager
from collections import OrderedDict
from threading import RLock
import atexit
import math
import importlib
import inspect
import operator
import os
from pathlib import Path
import tempfile
from typing import Mapping, Sequence

import h5py
import numpy as np

from .Decorators import log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)

__all__ = [
    "FastHdfError", "available", "close_sessions", "read_dataset", "read_datasets",
    "read_typed", "read_attrs", "read_attr", "trace_reads",
    "native_required", "reraise_required",
    "packed_meshes", "mesh_polygons", "export_pmtiles", "export_mesh_pmtiles",
]


class FastHdfError(RuntimeError):
    """The explicitly requested native operation could not be completed."""


def _mode(backend):
    if backend not in {"auto", "python", "rust"}:
        raise ValueError("backend must be 'auto', 'python', or 'rust'")
    if backend != "auto":
        return backend
    value = os.environ.get("RAS_COMMANDER_FAST_HDF", "auto").strip().lower()
    if value in {"0", "off", "false", "python"}:
        return "python"
    if value in {"required", "rust"}:
        return "rust"
    if value in {"", "auto", "1", "on", "true"}:
        return "auto"
    raise ValueError("Invalid RAS_COMMANDER_FAST_HDF value: " + repr(value))


def _threads(threads):
    if threads is None:
        return None
    if isinstance(threads, bool):
        raise ValueError("threads must be a positive integer")
    value = operator.index(threads)
    if not 1 <= value <= 1024:
        raise ValueError("threads must be between 1 and 1024")
    return value


def _native(mode):
    if mode == "python":
        return None
    try:
        module = importlib.import_module("ras_commander_fast_hdf")
    except (ImportError, OSError) as exc:
        if mode == "rust":
            raise FastHdfError("The optional ras-commander-fast-hdf extension is unavailable") from exc
        return None
    if getattr(module, "API_VERSION", None) != 11:
        if mode == "rust":
            raise FastHdfError("Incompatible ras-commander-fast-hdf API; version 11 is required")
        logger.warning("Ignoring incompatible ras-commander-fast-hdf extension")
        return None
    return module


@log_call
def available() -> bool:
    """Whether a compatible extension can be imported, independently of policy."""
    return _native("auto") is not None


# At most four mapped files. The lock also keeps eviction/close from racing a
# cached read; native sessions independently serialize close against reads.
_sessions = OrderedDict()
_sessions_lock = RLock()
_SESSION_LIMIT = 4


@log_call
def close_sessions(path=None):
    """Release cached native file mappings before replacing HDFs or running RAS.

    Omit path to close all cached files. Explicit HdfSession objects are owned
    by their caller and must be closed separately.
    """
    resolved = None if path is None else str(Path(path).resolve())
    from . import _fast_hdf_typed
    _fast_hdf_typed.clear_cache(path)
    with _sessions_lock:
        for key in list(_sessions):
            if resolved is None or key[0] == resolved:
                session, _ = _sessions.pop(key)
                session.close()


@contextmanager
def _session(module, path, threads=None):
    path = Path(path).resolve()
    enabled = os.environ.get("RAS_COMMANDER_HDF_SESSION_CACHE", "1").strip().lower() not in {"0", "false", "off"}
    if not enabled:
        close_sessions(path)
        with module.HdfSession(path, threads=threads) as session:
            yield session
        return
    with _sessions_lock:
        try:
            stat = path.stat()
        except OSError:
            close_sessions(path)
            raise
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        for old in list(_sessions):
            if old[0] == str(path) and (old != key or _sessions[old][1] != threads):
                _sessions.pop(old)[0].close()
        if key not in _sessions:
            while len(_sessions) >= _SESSION_LIMIT:
                _sessions.popitem(last=False)[1][0].close()
            _sessions[key] = (module.HdfSession(path, threads=threads), threads)
        _sessions.move_to_end(key)
        yield _sessions[key][0]


atexit.register(close_sessions)


def _unsupported(module, exc):
    classes = tuple(
        cls for name in ("UnsupportedError", "TopologyError")
        if isinstance((cls := getattr(module, name, None)), type)
    )
    return bool(classes) and isinstance(exc, classes)


def _domain_refusal(exc):
    """A typed result reader declined to qualify the layout (not a data failure).

    The engine refuses typed domains it cannot prove (for example a mesh summary
    without a stored ``Location`` attribute) but keeps the literal values readable
    through its generic reader, which is what literal-value callers need.
    """
    return getattr(exc, "engine_kind", None) == "unsupported"


def _safe_file(dataset):
    file = dataset.file
    filename = file.filename
    # Reopening must never discard dirty state or escape an in-memory file.
    return (
        file.mode == "r"
        and file.driver not in {"core", "fileobj", "family", "split", "mpio"}
        and isinstance(filename, (str, bytes))
        and Path(os.fsdecode(filename)).is_file()
        and not file.swmr_mode
        # Groups (attribute reads) have no layout of their own.
        and (isinstance(dataset, h5py.Group)
             or (not dataset.is_virtual and dataset.external is None))
    )


def _numeric(dataset):
    dtype = dataset.dtype
    return (dtype.kind in "iuf" and dtype.itemsize in {1, 2, 4, 8}
            and dtype.fields is None and h5py.check_enum_dtype(dtype) is None)


def _selection(shape, selection):
    """Normalize simple slices, preserving the h5py integer-axis contract."""
    if selection is None or selection is Ellipsis or (isinstance(selection, tuple) and not selection):
        return None, ()
    keys = list(selection if isinstance(selection, tuple) else (selection,))
    ellipses = [i for i, value in enumerate(keys) if value is Ellipsis]
    if len(ellipses) > 1:
        raise ValueError("Only one ellipsis is supported")
    if ellipses:
        i = ellipses[0]
        keys[i:i + 1] = [slice(None)] * (len(shape) - len(keys) + 1)
    keys += [slice(None)] * (len(shape) - len(keys))
    if len(keys) != len(shape):
        raise NotImplementedError("Native selection requires one basic index per dimension")
    slices, squeeze = [], []
    for axis, (key, size) in enumerate(zip(keys, shape)):
        if isinstance(key, slice):
            start, stop, step = key.indices(size)
            if step <= 0:
                raise NotImplementedError("Native slices require positive steps")
            slices.append((start, max(start, stop), step))
        elif isinstance(key, (int, np.integer)) and not isinstance(key, (bool, np.bool_)):
            index = int(key)
            index = index + size if index < 0 else index
            if index < 0 or index >= size:
                raise IndexError("HDF index is outside the dataset")
            slices.append((index, index + 1, 1))
            squeeze.append(axis)
        else:
            raise NotImplementedError("Native selection supports only integers and slices")
    return slices, tuple(squeeze)


def _checked_array(result, dtype, expected_shape):
    result = np.asarray(result)
    # Reject a broken binding instead of quietly converting a different type.
    if result.dtype.kind != dtype.kind or result.dtype.itemsize != dtype.itemsize:
        raise FastHdfError(f"Native dtype mismatch: {result.dtype} versus {dtype}")
    if result.shape != expected_shape:
        raise FastHdfError(f"Native shape mismatch: {result.shape} versus {expected_shape}")
    return result.astype(dtype, copy=False)


@log_call
def read_dataset(dataset: h5py.Dataset, selection=None, *, backend="auto", threads=None):
    """Read numeric values without changing dtype, shape, or integer indexing.

    The result is the literal stored selection, exactly ``dataset[selection]``.
    Canonical 2D mesh results use the typed engine reader; when that reader
    refuses to qualify a domain (for example a summary or series without a
    stored ``Location`` attribute) the exact literal values come from the
    generic native reader instead, because this function promises no domain.
    Auto mode uses h5py for unsupported types, layouts, advanced indexing and
    any native failure (Corrupt included), so the public outcome is h5py's.
    Rust mode raises :class:`FastHdfError` instead, allowing tests to assert
    actual native execution.
    """
    if not isinstance(dataset, h5py.Dataset):
        raise TypeError("dataset must be an open h5py.Dataset")
    from ._fast_hdf_typed import _record
    mode, threads = _mode(backend), _threads(threads)
    module = _native(mode)
    key = () if selection is None else selection
    if module is None:
        _record(dataset.name, "h5py")
        return dataset[key]
    if not _safe_file(dataset) or not _numeric(dataset) or dataset.shape is None:
        if mode == "rust":
            raise FastHdfError(f"Dataset cannot be safely read by Rust: {dataset.name}")
        logger.debug("h5py fallback for unsupported dataset %s", dataset.name)
        _record(dataset.name, "h5py-fallback", "unsupported-dataset")
        return dataset[key]
    try:
        slices, squeeze = _selection(dataset.shape, selection)
    except NotImplementedError as exc:
        if mode == "rust":
            raise FastHdfError(str(exc)) from exc
        _record(dataset.name, "h5py-fallback", "advanced-selection")
        return dataset[key]
    expected = dataset.shape if slices is None else tuple(len(range(*item)) for item in slices)
    route = ("mesh_result" if dataset.name.startswith(
        "/Results/Unsteady/Output/Output Blocks/Base Output/") and "/2D Flow Areas/" in dataset.name
        else "generic")
    try:
        with _session(module, os.fsdecode(dataset.file.filename), threads) as session:
            try:
                values = _read_fim_result(session, dataset, slices, threads)
                served = ("native-typed", "mesh_result") if values is not None else ("native-generic", None)
            except Exception as exc:
                if not _domain_refusal(exc):
                    raise
                # Typed domain unqualified: the literal generic read is exact.
                logger.debug("literal generic read for %s: %s", dataset.name, exc)
                values, served = None, ("native-generic", "mesh_result-literal")
            if values is None:
                values = session.read_numeric(dataset.name, selection=slices)
    except Exception as exc:
        if mode == "auto":
            # h5py is the public contract: any native failure, Corrupt included.
            logger.debug("h5py fallback for %s: %s", dataset.name, exc)
            _record(dataset.name, "h5py-fallback", route)
            return dataset[key]
        raise FastHdfError(f"Native read failed for {dataset.name}: {exc}") from exc
    _record(dataset.name, *served)
    values = _checked_array(values, dataset.dtype, expected)
    if squeeze:
        values = np.squeeze(values, axis=squeeze)
    # h5py returns a NumPy scalar for a scalar dataset/full integer indexing.
    return values[()] if values.ndim == 0 else values


def _read_fim_result(module, dataset, slices, threads):
    """Dispatch bounded Base Output reads; other layouts retain numeric reads."""
    # Explicit thread controls still belong to the generic reader. Typed readers
    # use the engine's session defaults and its fixed 64 MiB output budget.
    if not dataset.shape or threads is not None:
        return None
    parts = dataset.name.strip("/").split("/")
    prefix = ["Results", "Unsteady", "Output", "Output Blocks", "Base Output"]
    if parts[:5] != prefix or len(parts) not in {9, 10}:
        return None
    shape = dataset.shape if slices is None else tuple(len(range(*s)) for s in slices)
    if math.prod(shape) * dataset.dtype.itemsize + shape[-1] * 8 > 67108864:
        return None
    block, family, area = parts[5:8]
    if family != "2D Flow Areas":
        return None
    if block == "Summary Output" and len(parts) == 9 and slices is None:
        return module.read_mesh_summary_values(area, parts[8])
    if block != "Unsteady Time Series" or len(dataset.shape) != 2:
        return None
    rows, columns = slices or [(0, n, 1) for n in dataset.shape]
    elements = None if columns == (0, dataset.shape[1], 1) else np.arange(*columns, dtype=np.uint64)
    if len(parts) == 9:
        return module.read_mesh_series(area, parts[8], rows, elements)["values"]
    if parts[8] == "Boundary Conditions":
        return module.read_mesh_boundary_series(area, parts[9], rows, elements)["values"]
    return None


def read_typed(dataset: h5py.Dataset, selection=None, *, backend="auto"):
    """Read exactly like ``dataset[selection]``, served by typed engine families.

    Wave 8 / Wave 2 typed families (mesh geometry, 2D line families, 1D
    geometry, XS results, 1D summaries, 1D structures) supply the values; other
    numeric datasets use :func:`read_dataset`; compound/string metadata without
    an engine raw reader stays on h5py. Auto falls back to h5py on any engine
    refusal; ``rust`` raises :class:`FastHdfError`. See ``_fast_hdf_typed``.
    """
    from . import _fast_hdf_typed
    return _fast_hdf_typed.read(dataset, selection, backend=backend)


def read_attrs(obj, *, backend="auto") -> dict:
    """Return ``{name: obj.attrs[name]}`` exactly as h5py, values from the engine.

    Groups use the engine's typed group attributes and datasets its typed dataset
    attributes (every dataset, inside or outside the engine read families). NULL
    dataspaces become ``h5py.Empty`` and bitfields unsigned integers, as h5py.
    Auto falls back to h5py per attribute when the engine cannot reproduce a value
    exactly (or for a virtual/external dataset); ``rust`` raises
    :class:`FastHdfError`. See ``_fast_hdf_typed.read_attrs``.
    """
    from . import _fast_hdf_typed
    return _fast_hdf_typed.read_attrs(obj, backend=backend)


_NO_DEFAULT = object()


def read_attr(obj, name, default=_NO_DEFAULT, *, backend="auto"):
    """Exactly ``obj.attrs[name]``, or ``obj.attrs.get(name, default)`` when a default is given.

    Only the requested attribute is rebuilt from the engine, so an attribute the
    engine cannot reproduce does not refuse its siblings. Same backend policy as
    :func:`read_attrs`. See ``_fast_hdf_typed.read_attr``.
    """
    from . import _fast_hdf_typed
    if default is _NO_DEFAULT:
        return _fast_hdf_typed.read_attr(obj, name, backend=backend)
    return _fast_hdf_typed.read_attr(obj, name, default, backend=backend)


def native_required() -> bool:
    """Whether ``RAS_COMMANDER_FAST_HDF`` currently selects required-native mode."""
    try:
        return _mode("auto") == "rust"
    except ValueError:
        return False


def reraise_required(exc: BaseException, backend: str = "auto") -> None:
    """Re-raise ``exc`` when it is a native refusal in required-native mode.

    Public readers keep their established h5py failure policy (empty result,
    logged error or wrapped exception) in python and auto modes. Required-native
    mode must surface :class:`FastHdfError` unchanged instead, so their broad
    ``except Exception`` handlers call this first.

    Required mode is either an explicit ``backend="rust"`` passed by a reader
    that takes a backend argument, or, with the default ``backend="auto"``,
    ``RAS_COMMANDER_FAST_HDF=required``. ``backend="python"`` never re-raises.
    """
    if not isinstance(exc, FastHdfError):
        return
    if backend == "rust" or (backend == "auto" and native_required()):
        raise exc


def trace_reads():
    """Context manager recording which backend served each ``read_typed`` call."""
    from . import _fast_hdf_typed
    return _fast_hdf_typed.trace_reads()


@log_call
def read_datasets(hdf_path, dataset_paths: Sequence[str], *, backend="auto", threads=None):
    """Read multiple datasets with one native file handle; retain h5py metadata.

    In auto mode mixed numeric/compound/string batches are supported: eligible
    numeric arrays use Rust and remaining datasets use h5py. Duplicate paths
    produce one dictionary entry, in first-occurrence order.
    """
    mode, threads = _mode(backend), _threads(threads)
    module = _native(mode)
    paths = list(dict.fromkeys(dataset_paths))
    context = nullcontext(hdf_path) if isinstance(hdf_path, h5py.File) else h5py.File(Path(hdf_path), "r")
    with context as hdf:
        datasets = {path: hdf[path] for path in paths}
        if any(not isinstance(ds, h5py.Dataset) for ds in datasets.values()):
            raise TypeError("Every requested HDF path must identify a dataset")
        eligible = [path for path, ds in datasets.items()
                    if module is not None and _safe_file(ds) and _numeric(ds) and ds.shape is not None]
        if mode == "rust" and len(eligible) != len(paths):
            raise FastHdfError("Batch contains a dataset unsupported by the Rust backend")
        native_values = {}
        if eligible:
            try:
                with _session(module, os.fsdecode(hdf.filename), threads) as session:
                    # Canonical per-area BC series share qualification/time work in one call.
                    groups = {}
                    generic = []
                    for path in eligible:
                        ds = datasets[path]
                        parts = ds.name.strip("/").split("/")
                        if (threads is None and len(parts) == 10 and parts[:5] ==
                                ["Results", "Unsteady", "Output", "Output Blocks", "Base Output"]
                                and parts[5:7] == ["Unsteady Time Series", "2D Flow Areas"]
                                and parts[8] == "Boundary Conditions" and len(ds.shape) == 2):
                            groups.setdefault((parts[7], ds.shape[0]), []).append((path, parts[9]))
                        else:
                            generic.append(path)
                    # Keep the generic reader's unbounded full-read contract for
                    # batches exceeding the typed result API's output budget.
                    for key, requests in list(groups.items()):
                        size = sum(datasets[path].size * datasets[path].dtype.itemsize
                                   + datasets[path].shape[-1] * 8 for path, _ in requests)
                        if size > 67108864:
                            generic.extend(path for path, _ in requests)
                            del groups[key]
                    native_values = session.read_numeric_batch(generic) if generic else {}
                    for (area, rows), requests in groups.items():
                        try:
                            values = session.read_mesh_boundary_batch(
                                area, (0, rows, 1), [name for _, name in requests])
                        except Exception as exc:
                            # Typed domain refusals keep exact literal generic reads in
                            # every mode; auto also does so for other qualification
                            # refusals, but never hides host failures.
                            if not _domain_refusal(exc) and (
                                    mode != "auto" or getattr(exc, "engine_kind", None) not in {
                                    "corrupt", "not_found", "invalid_request",
                                    "structural_topology", "invalid_geometry"}):
                                raise
                            native_values.update(session.read_numeric_batch(
                                [path for path, _ in requests]))
                        else:
                            for path, name in requests:
                                native_values[path] = values[name]["values"]
            except Exception as exc:
                if mode != "auto":
                    raise FastHdfError(f"Native batch read failed for {hdf.filename}: {exc}") from exc
                # Isolate failing datasets without disabling the whole batch;
                # read_dataset gives each one the h5py outcome on native failure.
                logger.debug("Native batch needs per-dataset fallback: %s", exc)
                return {path: read_dataset(ds, backend=backend, threads=threads)
                        for path, ds in datasets.items()}
        result = {}
        for path, ds in datasets.items():
            if path in eligible:
                if path not in native_values:
                    raise FastHdfError(f"Native batch omitted {path}")
                values = _checked_array(native_values[path], ds.dtype, ds.shape)
                result[path] = values[()] if values.ndim == 0 else values
            else:
                result[path] = ds[()]
        return result


_MESH_ARRAYS = (
    "FacePoints Coordinate", "Faces FacePoint Indexes", "Faces Perimeter Info",
    "Faces Perimeter Values", "Cells Face and Orientation Info",
    "Cells Face and Orientation Values",
)


def _assemble(hdf, mesh_name, module, backend, threads, *, diagnostics=False, strict=True):
    paths = [f"Geometry/2D Flow Areas/{mesh_name}/{name}" for name in _MESH_ARRAYS]
    arrays = read_datasets(hdf, paths, backend=backend, threads=threads)
    args = []
    for index, path in enumerate(paths):
        values = np.asarray(arrays[path])
        if index not in {0, 3}:
            if values.dtype.kind not in "iu":
                raise ValueError(f"Connectivity must contain integers: {path}")
            if values.dtype.kind == "u" and values.size and values.max() > np.iinfo(np.int64).max:
                raise ValueError(f"Connectivity exceeds int64: {path}")
        args.append(np.ascontiguousarray(values, dtype=np.float64 if index in {0, 3} else np.int64))
    if diagnostics:
        # Check the policy-capable binding
        # signature before requesting it: compatible wheels remain usable for packed
        # extraction, but cannot claim this policy. Auto may use Python;
        # required native reports an explicit rebuild requirement.
        try:
            parameters = inspect.signature(module.assemble_cells).parameters
        except (TypeError, ValueError):
            parameters = {}
        if not {"strict", "return_diagnostics"}.issubset(parameters):
            raise module.UnsupportedError(
                "Native mesh quarantine requires assemble_cells strict and "
                "return_diagnostics support; rebuild the optional extension")
        coordinates, offsets, cell_ids, invalid = module.assemble_cells(
            *args, threads=threads, strict=strict, return_diagnostics=True)
    else:
        coordinates, offsets, cell_ids = module.assemble_cells(*args, threads=threads)
    result = {"coordinates": coordinates, "offsets": offsets, "cell_ids": cell_ids}
    if diagnostics:
        records = []
        invalid = {int(d["cell_id"]): (d["kind"], d["message"]) for d in invalid}
        missing = np.ones(len(args[4]), dtype=bool)
        missing[cell_ids] = False
        for cell_id in np.flatnonzero(missing):
            start, length = map(int, args[4][cell_id, :2])
            records.append({
                "mesh_name": mesh_name, "cell_id": int(cell_id),
                "face_count": length, "polygon_count": 0,
                "status": "omitted" if cell_id in invalid or length == 0 else "boundary_only",
                "reason_code": "no_polygon" if cell_id in invalid else (
                    "zero_faces" if length == 0 else "insufficient_faces"),
                "face_ids": tuple(map(int, args[5][start:start + length, 0])),
                "missing_face_ids": (),
            })
            if cell_id in invalid:
                records[-1]["native_reason_code"] = invalid[cell_id][0]
                records[-1]["reason"] = invalid[cell_id][1]
        result["diagnostics"] = records
    return result


@log_call
def packed_meshes(hdf_path, *, mesh_names=None, backend="auto", threads=None):
    """Return native packed polygon buffers keyed by mesh name.

    Each entry contains coordinates (N, 2), ring offsets (C+1), and original
    cell IDs (C). Unsupported topology raises; no ring or cell is invented.
    This task API requires the optional extension, including in auto mode.
    """
    from .hdf.HdfMesh import HdfMesh
    mode, threads = _mode(backend), _threads(threads)
    module = _native(mode)
    if module is None:
        raise FastHdfError("Packed mesh extraction requires the enabled Rust extension")
    context = nullcontext(hdf_path) if isinstance(hdf_path, h5py.File) else h5py.File(Path(hdf_path), "r")
    with context as hdf:
        names = HdfMesh.get_mesh_area_names(hdf.filename)
        if mesh_names is not None:
            requested = [mesh_names] if isinstance(mesh_names, str) else list(mesh_names)
            missing = set(requested) - set(names)
            if missing:
                raise ValueError(f"Unknown mesh areas: {sorted(missing)}")
            names = list(dict.fromkeys(requested))
        try:
            return {name: _assemble(hdf, name, module, backend, threads) for name in names}
        except Exception as exc:
            if isinstance(exc, FastHdfError):
                raise
            raise FastHdfError(f"Native mesh assembly failed for {hdf.filename}: {exc}") from exc


def _try_mesh_polygons(hdf_path, *, backend="auto", threads=None, strict=None):
    """Internal compatibility hook; None means use the original polygonizer."""
    mode, threads = _mode(backend), _threads(threads)
    module = _native(mode)
    if module is None:
        return None
    from geopandas import GeoDataFrame
    import shapely
    from .hdf.HdfBase import HdfBase
    from .hdf.HdfMesh import HdfMesh
    names, ids, geometries, diagnostics = [], [], [], []
    with h5py.File(hdf_path, "r") as hdf:
        mesh_names = HdfMesh.get_mesh_area_names(hdf_path)
        if not mesh_names:
            return GeoDataFrame()
        for name in mesh_names:
            try:
                if not all(f"Geometry/2D Flow Areas/{name}/{key}" in hdf for key in _MESH_ARRAYS):
                    raise module.UnsupportedError("Incomplete native mesh layout")
                packed = _assemble(hdf, name, module, backend, threads,
                                   diagnostics=strict is not None, strict=strict is not False)
            except Exception as exc:
                if (mode == "auto" and _unsupported(module, exc)
                        and not hasattr(exc, "mesh_structure_error")):
                    logger.debug("Legacy polygon fallback for %s/%s: %s", hdf_path, name, exc)
                    return None
                if strict and isinstance(exc, module.TopologyError):
                    from .hdf.HdfMesh import MeshCellPolygonError
                    raise MeshCellPolygonError(f"Native polygon assembly failed for {name}: {exc}") from exc
                if isinstance(exc, FastHdfError):
                    raise
                raise FastHdfError(f"Native polygon assembly failed for {name}: {exc}") from exc
            count = len(packed["cell_ids"])
            diagnostics.extend(packed.get("diagnostics", ()))
            if count:
                polygons = shapely.from_ragged_array(
                    shapely.GeometryType.POLYGON, packed["coordinates"],
                    (packed["offsets"], np.arange(count + 1, dtype=np.int64)),
                )
                valid = shapely.is_valid(polygons)
                if not np.all(valid):
                    bad_ids = np.asarray(packed["cell_ids"])[~valid]
                    message = f"Native polygon geometry is invalid for {name}, cell IDs {bad_ids[:10].tolist()}"
                    if mode == "auto":
                        logger.debug("%s; using Python polygon diagnostics", message)
                        return None
                    if strict:
                        from .hdf.HdfMesh import MeshCellPolygonError
                        raise MeshCellPolygonError(message)
                    raise FastHdfError(message)
                names.extend([name] * count)
                ids.append(packed["cell_ids"])
                geometries.append(polygons)
        if not names and strict is None:
            return GeoDataFrame()
        result = GeoDataFrame({"mesh_name": names, "cell_id": np.concatenate(ids) if ids else [],
                               "geometry": np.concatenate(geometries) if geometries else []},
                              geometry="geometry", crs=HdfBase.get_projection(hdf))
        if strict is not None:
            result.attrs["cell_polygon_diagnostics"] = tuple(diagnostics)
            omitted = [record for record in diagnostics if record["status"] == "omitted"]
            if omitted:
                from collections import Counter
                counts = Counter(record["mesh_name"] for record in omitted)
                summary = ", ".join(f"{name!r}: {counts[name]}" for name in sorted(counts))
                message = ("Mesh cell polygon reconstruction was incomplete or ambiguous "
                           f"({summary}). Inspect diagnose_mesh_cell_polygons(); native "
                           "cell IDs remain authoritative.")
                if strict:
                    from .hdf.HdfMesh import MeshCellPolygonError
                    raise MeshCellPolygonError(message)
                logger.warning(message)
        return result


@log_call
def mesh_polygons(hdf_path, *, backend="auto", threads=None, strict=False):
    """Extract the established mesh GeoDataFrame, with explicit backend control."""
    from .hdf.HdfMesh import HdfMesh
    return HdfMesh.get_mesh_cell_polygons(hdf_path, backend=backend, threads=threads, strict=strict)


def _property_values(values, count, name):
    # Object dtype prevents a mixed [1, 'unknown'] column silently converting
    # the numeric value to a string on its way to the MVT property encoder.
    values = np.asarray(values, dtype=object)
    if values.ndim != 1 or len(values) != count:
        raise ValueError(f"Property {name!r} must have one value per feature")
    result = values.tolist()
    for index, value in enumerate(result):
        if value is None or isinstance(value, (str, bool, int)):
            continue
        if isinstance(value, float):
            if not np.isfinite(value):
                result[index] = None
            continue
        raise TypeError(f"Property {name!r} contains a non-scalar value")
    return result


@log_call
def export_pmtiles(output_path, layers: Mapping, *, source_crs="EPSG:4326",
                   min_zoom=0, max_zoom=12, backend="auto", threads=None):
    """Atomically export packed polygon layers through pyproj and freestiler.

    ``layers`` maps source-layer names to coordinates, offsets, cell_ids and
    optional property columns. Properties are aligned with the supplied IDs.
    Each layer may override ``source_crs``. No feature-dropping is requested.
    Legacy ``offsets`` describes one closed exterior ring per feature.
    For holes/multipart, replace it with ``ring_offsets`` (coordinate spans),
    ``polygon_offsets`` (ring spans: exterior first, then holes), and
    ``feature_offsets`` (polygon spans). All are integer arrays starting at zero
    with terminal sentinels. Components must be nonempty; an empty layer uses
    [0] at each level. IDs/properties remain per feature. Coordinates must
    describe valid polygons; ring winding is handled by freestiler.
    """
    from pyproj import CRS, Transformer
    mode, threads = _mode(backend), _threads(threads)
    module = _native(mode)
    if module is None:
        raise FastHdfError("Direct PMTiles export requires the enabled Rust extension")
    if isinstance(min_zoom, bool) or isinstance(max_zoom, bool):
        raise ValueError("Zoom levels must be integers")
    min_zoom, max_zoom = operator.index(min_zoom), operator.index(max_zoom)
    if not 0 <= min_zoom <= max_zoom <= 22:
        raise ValueError("Require 0 <= min_zoom <= max_zoom <= 22")
    prepared = []
    for name, layer in layers.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Source layer names must be non-empty strings")
        coords = np.ascontiguousarray(layer["coordinates"], dtype=np.float64)
        ids = np.asarray(layer["cell_ids"])
        if ids.dtype.kind not in "iu" or ids.ndim != 1:
            raise ValueError("Feature IDs must be a one-dimensional integer array")
        if coords.ndim != 2 or coords.shape[1] != 2 or not np.isfinite(coords).all():
            raise ValueError("Coordinates must be a finite N by 2 array")
        nested_keys = ("ring_offsets", "polygon_offsets", "feature_offsets")
        nested = any(key in layer for key in nested_keys)
        if nested and ("offsets" in layer or not all(key in layer for key in nested_keys)):
            raise ValueError("Use offsets or all three nested offset arrays, not both")
        packed_offsets = {}
        children = len(coords)
        for key in nested_keys if nested else ("offsets",):
            offsets = np.asarray(layer[key])
            if offsets.dtype.kind not in "iu" or offsets.ndim != 1:
                raise ValueError(f"{key} must be a one-dimensional integer array")
            if (not len(offsets) or offsets[0] != 0 or offsets[-1] != children
                    or np.any(offsets[1:] <= offsets[:-1])):
                raise ValueError(f"{key} must span all children strictly monotonically from zero")
            if offsets.max() > np.iinfo(np.int64).max:
                raise ValueError("Packed indices exceed int64")
            packed_offsets[key] = np.ascontiguousarray(offsets, dtype=np.int64)
            children = len(offsets) - 1
        if children != len(ids):
            raise ValueError("Feature offsets differ from ID count")
        if np.any(ids < 0) or len(np.unique(ids)) != len(ids):
            raise ValueError("Feature IDs must be nonnegative and unique within a layer")
        for values in (ids,):
            if values.size and values.max() > np.iinfo(np.int64).max:
                raise ValueError("Packed indices exceed int64")
        columns = {key: _property_values(value, len(ids), key)
                   for key, value in layer.get("properties", {}).items()}
        if any(not isinstance(key, str) for key in columns):
            raise TypeError("Property names must be strings")
        if not len(ids):
            continue
        crs_value = layer.get("source_crs", source_crs)
        if crs_value is None:
            raise ValueError("A source CRS is required for PMTiles export")
        transformer = Transformer.from_crs(CRS.from_user_input(crs_value), "EPSG:4326", always_xy=True)
        longitude, latitude = transformer.transform(coords[:, 0], coords[:, 1], errcheck=True)
        coords = np.ascontiguousarray(np.column_stack((longitude, latitude)))
        if not np.isfinite(coords).all() or np.any(np.abs(coords[:, 0]) > 180) or np.any(np.abs(coords[:, 1]) > 85.0511287798066):
            raise ValueError("Transformed coordinates are outside the Web Mercator domain")
        prepared.append({"name": name, "coordinates": coords,
                         **packed_offsets,
                         "cell_ids": np.ascontiguousarray(ids, dtype=np.int64),
                         "properties": columns})
    if not prepared:
        raise ValueError("A PMTiles archive requires at least one non-empty layer")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output.stem}-", suffix=".pmtiles", dir=output.parent)
    os.close(descriptor)
    staged = Path(temporary)
    try:
        module.write_pmtiles(prepared, str(staged), min_zoom, max_zoom, threads=threads)
        if not staged.is_file() or staged.stat().st_size < 127:
            raise FastHdfError("Native tiler did not produce a PMTiles archive")
        staged.replace(output)
    except Exception as exc:
        if isinstance(exc, FastHdfError):
            raise
        raise FastHdfError(f"Native PMTiles export failed: {exc}") from exc
    finally:
        staged.unlink(missing_ok=True)
    return output


@log_call
def export_mesh_pmtiles(hdf_path, output_path, *, mesh_names=None, properties=None,
                        layer_name="mesh_cells", source_crs=None, min_zoom=0,
                        max_zoom=12, backend="auto", threads=None):
    """Write selected HDF meshes as one layer without per-cell Python geometry.

    ``properties`` maps mesh name -> column name -> source-cell-indexed array.
    Original ``mesh_name``/``cell_id`` properties are always retained; native
    feature IDs are sequential and unique across the selected meshes. Ghost
    result columns may exist, but only constructed cell IDs are exported.
    """
    source_path = Path(os.fsdecode(hdf_path.filename)) if isinstance(hdf_path, h5py.File) else Path(hdf_path)
    destination = Path(output_path)
    if (source_path.resolve() == destination.resolve()
            or (destination.exists() and source_path.exists()
                and os.path.samefile(source_path, destination))):
        raise ValueError("PMTiles output must not overwrite the source HDF file")
    from .hdf.HdfBase import HdfBase
    meshes = packed_meshes(hdf_path, mesh_names=mesh_names, backend=backend, threads=threads)
    properties = {} if properties is None else properties
    unknown = set(properties) - set(meshes)
    if unknown:
        raise ValueError(f"Properties reference unselected meshes: {sorted(unknown)}")
    if source_crs is None:
        context = nullcontext(hdf_path) if isinstance(hdf_path, h5py.File) else h5py.File(Path(hdf_path), "r")
        with context as hdf:
            source_crs = HdfBase.get_projection(hdf)
    if source_crs is None:
        raise ValueError("HDF has no projection; supply source_crs explicitly")
    property_names = list(dict.fromkeys(key for columns in properties.values() for key in columns))
    if set(property_names) & {"mesh_name", "cell_id"}:
        raise ValueError("mesh_name and cell_id are reserved source identity properties")
    columns = {key: [] for key in ["mesh_name", "cell_id", *property_names]}
    coordinates, offsets, cursor = [], [0], 0
    for name, packed in meshes.items():
        ids = np.asarray(packed["cell_ids"])
        count = len(ids)
        if not count:
            continue
        coordinates.append(packed["coordinates"])
        offsets.extend((np.asarray(packed["offsets"])[1:] + cursor).tolist())
        cursor += len(packed["coordinates"])
        columns["mesh_name"].extend([name] * count)
        columns["cell_id"].extend(ids.tolist())
        for key in property_names:
            if key not in properties.get(name, {}):
                columns[key].extend([None] * count)
                continue
            values = np.asarray(properties[name][key], dtype=object)
            if values.ndim != 1 or len(values) <= int(ids.max()):
                raise ValueError(f"Property {name}/{key} does not cover every source cell ID")
            columns[key].extend(_property_values(values[ids], count, key))
    if not coordinates:
        raise ValueError("No mesh cell polygons are available for export")
    count = len(columns["cell_id"])
    layer = {"coordinates": np.concatenate(coordinates), "offsets": np.asarray(offsets, dtype=np.int64),
             "cell_ids": np.arange(count, dtype=np.int64), "properties": columns}
    return export_pmtiles(output_path, {layer_name: layer}, source_crs=source_crs,
                          min_zoom=min_zoom, max_zoom=max_zoom, backend=backend, threads=threads)


@log_call
def export_arrow(output, batches, *, source_crs, format, max_batch_rows=65536):
    """Export a typed Arrow table/reader through optional native source writers.

    Required columns: nonnullable mesh_name:string and cell_id:int64, and
    geometry:binary (XY OGC WKB). Attributes: int64/uint64/float64/bool/string/
    binary/timestamp[ms]. Nulls are explicit. CRS is required and compared with
    existing GeoArrow metadata. GeoJSON is transformed using pyproj always_xy;
    large integer attributes become decimal strings, times remain integer ms.
    Existing outputs reject. IPC staging adds disk I/O; Rust callers can feed
    RecordBatch iterators directly. No implicit Python fallback.
    """
    return _export_arrow_transport(output, batches, source_crs=source_crs,
                                   format=format, max_batch_rows=max_batch_rows)


@log_call
def export_arrow_pmtiles(output, batches, *, source_crs, min_zoom=0, max_zoom=12,
                         max_batch_rows=65536, layer_name="features", threads=None,
                         timestamp_ms=False, reuse_from=None):
    """Export an Arrow/WKB rendering bundle using freestiler and reversible IDs.

    Output is a new directory containing tiles.pmtiles, identities.arrow and
    manifest.json. Existing bundles reject. Reuse a previous bundle to retain
    its composite identity mapping. Timestamps reject unless timestamp_ms=True;
    UInt64 must fit signed int64, binary properties reject. No custom tile repair.
    """
    import json
    for value in (min_zoom, max_zoom, max_batch_rows):
        if isinstance(value, bool):
            raise ValueError("zoom/batch limits must be integers")
    if not isinstance(timestamp_ms, bool):
        raise TypeError("timestamp_ms must be bool")
    options = dict(layer=layer_name, min_zoom=operator.index(min_zoom),
        max_zoom=operator.index(max_zoom), max_batch_rows=operator.index(max_batch_rows),
        timestamp_ms=timestamp_ms, reuse_from=None if reuse_from is None else str(Path(reuse_from)))
    return _export_arrow_transport(output, batches, source_crs=source_crs,
        format="pmtiles", max_batch_rows=max_batch_rows,
        pmtiles_options=(json.dumps(options), _threads(threads)))


def _export_arrow_transport(output, batches, *, source_crs, format,
                            max_batch_rows, pmtiles_options=None):
    import json
    import pyarrow as pa
    from pyproj import CRS, Transformer
    import shapely

    if format == "pmtiles" and pmtiles_options is None:
        raise ValueError("Use export_arrow_pmtiles for typed PMTiles bundles")
    native = _native("rust")
    method = "export_pmtiles_ipc_file" if format == "pmtiles" else "export_ipc_file"
    if not hasattr(native, method):
        raise FastHdfError("Native extension was built without export writers")
    output = Path(output)
    if source_crs is None:
        raise ValueError("source_crs is required")
    if isinstance(max_batch_rows, bool) or operator.index(max_batch_rows) <= 0:
        raise ValueError("max_batch_rows must be positive")
    max_batch_rows = operator.index(max_batch_rows)
    crs = CRS(source_crs)
    if isinstance(batches, pa.Table):
        reader = batches.to_reader(max_chunksize=max_batch_rows)
    elif isinstance(batches, pa.RecordBatchReader):
        reader = batches
    else:
        raise TypeError("batches must be a pyarrow Table or RecordBatchReader")
    schema = reader.schema
    index = schema.get_field_index("geometry")
    if index < 0 or schema.field(index).type != pa.binary():
        raise ValueError("geometry must be binary XY WKB")
    old_metadata = schema.field(index).metadata or {}
    if b"ARROW:extension:metadata" in old_metadata:
        old_crs = json.loads(old_metadata[b"ARROW:extension:metadata"]).get("crs")
        if old_crs is None or not crs.equals(CRS(old_crs), ignore_axis_order=True):
            raise ValueError("conflicting or missing GeoArrow CRS")
    geographic = format in {"geojson", "jsonl", "pmtiles"}
    target = CRS(4326) if geographic else crs
    transformer = Transformer.from_crs(crs, target, always_xy=True) if geographic else None
    evidence = dict(wkt=target.to_wkt(), projjson=target.to_json_dict(),
        units=target.axis_info[0].unit_name, axis_order="xy", resolved=True,
        geographic_wgs84=target.equals(CRS(4326), ignore_axis_order=True))
    old_contract = (schema.metadata or {}).get(b"ras:export:v1")
    if old_contract:
        old = json.loads(old_contract)
        if (not old.get("resolved") or old.get("axis_order") != "xy"
                or not crs.equals(CRS(old["wkt"]), ignore_axis_order=True)
                or not crs.equals(CRS(old["projjson"]), ignore_axis_order=True)):
            raise ValueError("conflicting source CRS contract")
    geometry_metadata = dict(old_metadata)
    extension_metadata = json.loads(geometry_metadata.get(b"ARROW:extension:metadata", b"{}"))
    extension_metadata.update(crs=target.to_json_dict(), crs_type="projjson")
    geometry_metadata.update({b"ARROW:extension:name": b"geoarrow.wkb",
        b"ARROW:extension:metadata": json.dumps(extension_metadata).encode()})
    field = schema.field(index).with_metadata(geometry_metadata)
    metadata = dict(schema.metadata or {})
    metadata[b"ras:export:v1"] = json.dumps(evidence).encode()
    if format == "pmtiles":
        metadata[b"ras:pmtiles:source_crs"] = json.dumps(dict(wkt=crs.to_wkt(),
            projjson=crs.to_json_dict(), units=crs.axis_info[0].unit_name,
            axis_order="xy", resolved=True)).encode()
    output_schema = schema.set(index, field).with_metadata(metadata)
    # Native contract validation remains authoritative for all scalar types,
    # dimensions, identity, domain, size and geometry structural checks.
    with tempfile.TemporaryDirectory(prefix="ras-export-", dir=output.parent) as folder:
        ipc = Path(folder)/"input.arrow"
        with pa.OSFile(str(ipc), "wb") as sink, pa.ipc.new_file(sink, output_schema) as writer:
            for batch in reader:
                if batch.schema != schema:
                    raise ValueError("batch schema mismatch")
                if batch.num_rows > max_batch_rows:
                    raise ValueError("batch exceeds max_batch_rows")
                columns = list(batch.columns)
                if geographic:
                    # Validate original bytes before Shapely can strip EWKB SRIDs
                    # or trailing data. Borrow Arrow buffers for one native call.
                    values = columns[index]
                    validity, offsets, data = values.buffers()
                    native.validate_export_wkb(
                        np.frombuffer(offsets, dtype=np.int32),
                        np.frombuffer(data if data is not None else b"", dtype=np.uint8),
                        None if validity is None else np.frombuffer(validity, dtype=np.uint8),
                        values.offset, len(values))
                    geometries = shapely.from_wkb(values.to_numpy(zero_copy_only=False))
                    if np.any(shapely.has_z(geometries)) or np.any(shapely.has_m(geometries)):
                        raise ValueError("explicit XY conversion required for Z/M")
                    geometries = shapely.transform(geometries, transformer.transform, interleaved=False)
                    geometries = shapely.orient_polygons(geometries, exterior_cw=False)
                    columns[index] = pa.array(shapely.to_wkb(geometries, flavor="iso"), type=pa.binary())
                writer.write_batch(pa.RecordBatch.from_arrays(columns, schema=output_schema))
        if format == "pmtiles":
            options, threads = pmtiles_options
            return json.loads(native.export_pmtiles_ipc_file(ipc, output, options, threads=threads))
        return json.loads(native.export_ipc_file(ipc, output, format, max_batch_rows))


__all__.append("export_arrow")

__all__.append("export_arrow_pmtiles")
