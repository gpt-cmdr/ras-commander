"""Optional Rust numeric reads, mesh assembly, and direct PMTiles export.

Ordinary installations need no native extension. ``RAS_COMMANDER_FAST_HDF=0``
disables automatic acceleration; ``required`` proves native execution in
qualification runs. Explicit ``backend='python'`` or ``'rust'`` overrides the
environment. Metadata and unsupported HDF types continue to use h5py in auto
mode. Native exceptions are never converted to successful empty results.
"""

from __future__ import annotations

from contextlib import nullcontext
import importlib
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
    "FastHdfError", "available", "read_dataset", "read_datasets",
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
    if getattr(module, "API_VERSION", None) != 1:
        if mode == "rust":
            raise FastHdfError("Incompatible ras-commander-fast-hdf API; version 1 is required")
        logger.warning("Ignoring incompatible ras-commander-fast-hdf extension")
        return None
    return module


@log_call
def available() -> bool:
    """Whether a compatible extension can be imported, independently of policy."""
    return _native("auto") is not None


def _unsupported(module, exc):
    classes = tuple(
        cls for name in ("UnsupportedError", "TopologyError")
        if isinstance((cls := getattr(module, name, None)), type)
    )
    return bool(classes) and isinstance(exc, classes)


def _safe_file(dataset):
    file = dataset.file
    # Reopening must never discard dirty state or escape an in-memory file.
    return (
        file.mode == "r"
        and file.driver not in {"core", "fileobj", "family", "split", "mpio"}
        and isinstance(file.filename, (str, bytes))
        and Path(os.fsdecode(file.filename)).is_file()
        and not file.swmr_mode
        and not dataset.is_virtual
        and dataset.external is None
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

    Auto mode uses h5py for unsupported types, layouts, and advanced indexing.
    Rust mode raises instead, allowing tests to assert actual native execution.
    """
    if not isinstance(dataset, h5py.Dataset):
        raise TypeError("dataset must be an open h5py.Dataset")
    mode, threads = _mode(backend), _threads(threads)
    module = _native(mode)
    key = () if selection is None else selection
    if module is None:
        return dataset[key]
    if not _safe_file(dataset) or not _numeric(dataset) or dataset.shape is None:
        if mode == "rust":
            raise FastHdfError(f"Dataset cannot be safely read by Rust: {dataset.name}")
        logger.debug("h5py fallback for unsupported dataset %s", dataset.name)
        return dataset[key]
    try:
        slices, squeeze = _selection(dataset.shape, selection)
    except NotImplementedError as exc:
        if mode == "rust":
            raise FastHdfError(str(exc)) from exc
        return dataset[key]
    expected = dataset.shape if slices is None else tuple(len(range(*item)) for item in slices)
    try:
        values = module.read_numeric(os.fsdecode(dataset.file.filename), dataset.name,
                                     selection=slices, threads=threads)
    except Exception as exc:
        if mode == "auto" and _unsupported(module, exc):
            logger.debug("h5py fallback for %s: %s", dataset.name, exc)
            return dataset[key]
        raise FastHdfError(f"Native read failed for {dataset.name}: {exc}") from exc
    values = _checked_array(values, dataset.dtype, expected)
    if squeeze:
        values = np.squeeze(values, axis=squeeze)
    # h5py returns a NumPy scalar for a scalar dataset/full integer indexing.
    return values[()] if values.ndim == 0 else values


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
                native_values = module.read_numeric_batch(os.fsdecode(hdf.filename), eligible, threads=threads)
            except Exception as exc:
                if mode != "auto" or not _unsupported(module, exc):
                    raise FastHdfError(f"Native batch read failed for {hdf.filename}: {exc}") from exc
                # Isolate unsupported datasets without disabling the whole batch.
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


def _assemble(hdf, mesh_name, module, backend, threads, *, diagnostics=False):
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
    if diagnostics and np.any(args[4][:, 1] == 2):
        raise module.UnsupportedError("Two-face diagnostic records require the Python polygonizer")
    coordinates, offsets, cell_ids = module.assemble_cells(*args, threads=threads)
    result = {"coordinates": coordinates, "offsets": offsets, "cell_ids": cell_ids}
    if diagnostics:
        if np.any(args[4][cell_ids, 1] < 3):
            raise module.UnsupportedError("Closed boundary-only records require the Python polygonizer")
        records = []
        for cell_id in np.flatnonzero(args[4][:, 1] < 3):
            start, length = map(int, args[4][cell_id, :2])
            records.append({
                "mesh_name": mesh_name, "cell_id": int(cell_id),
                "face_count": length, "polygon_count": 0,
                "status": "omitted" if length == 0 else "boundary_only",
                "reason_code": "zero_faces" if length == 0 else "insufficient_faces",
                "face_ids": tuple(map(int, args[5][start:start + length, 0])),
                "missing_face_ids": (),
            })
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
                packed = _assemble(hdf, name, module, backend, threads, diagnostics=strict is not None)
            except Exception as exc:
                if mode == "auto" and _unsupported(module, exc):
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
    Geometry buffers describe one closed exterior ring per feature.
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
        offsets, ids = np.asarray(layer["offsets"]), np.asarray(layer["cell_ids"])
        if offsets.dtype.kind not in "iu" or ids.dtype.kind not in "iu":
            raise ValueError("Offsets and feature IDs must be integers")
        if coords.ndim != 2 or coords.shape[1] != 2 or not np.isfinite(coords).all():
            raise ValueError("Coordinates must be a finite N by 2 array")
        if offsets.ndim != 1 or ids.ndim != 1 or len(offsets) != len(ids) + 1:
            raise ValueError("Offsets must contain one more entry than feature IDs")
        if len(offsets) == 0 or offsets[0] != 0 or offsets[-1] != len(coords) or np.any(offsets[1:] < offsets[:-1]):
            raise ValueError("Offsets must span the coordinate array monotonically")
        if np.any(ids < 0) or len(np.unique(ids)) != len(ids):
            raise ValueError("Feature IDs must be nonnegative and unique within a layer")
        for values in (offsets, ids):
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
                         "offsets": np.ascontiguousarray(offsets, dtype=np.int64),
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
