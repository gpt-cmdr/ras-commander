"""Explicit sloping API adapter; no arithmetic fallback."""

from pathlib import Path
import json
import os
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import _aoi, _engine, _horizontal, _products
from ._horizontal_engine import _read_f32, _write_geometry
from ._sloping_inputs import write_binary_mesh_inputs
from .errors import FimEngineError, FimEngineNotFoundError, FimUnsupportedError


class _StreamProtocolError(FimEngineError):
    """The sloping process did not deliver a complete transport frame."""


def _read_stream_f32(*args):
    try:
        return _read_f32(*args)
    except FimEngineError as exc:
        raise _StreamProtocolError(str(exc)) from exc


def _read_stderr_tail(errors):
    """Read at most 16,000 bytes and retain the last 4,000 decoded characters."""
    errors.seek(0, os.SEEK_END)
    errors.seek(max(0, errors.tell() - 16000), os.SEEK_SET)
    return errors.read(16000).decode("utf-8", errors="replace")[-4000:]


def _capture_process_failure(process, errors, details, *, expired=None, wait_for_exit=False):
    """Capture a natural exit separately from supervisory termination."""
    timed_out = expired is not None and expired.is_set()
    observed_code = None if timed_out or process is None else process.poll()
    if observed_code is None and process is not None and wait_for_exit and not timed_out:
        try:
            observed_code = process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            pass
    cleanup_termination = process is not None and process.poll() is None
    if cleanup_termination:
        process.kill()
    cleanup_code = process.wait() if process is not None else None
    if expired is not None and expired.is_set():
        observed_code = None
    details["engine_returncode"] = observed_code
    details["engine_cleanup_termination_requested"] = cleanup_termination
    if observed_code is None and cleanup_code is not None:
        details["engine_cleanup_returncode"] = cleanup_code
    details["engine_stderr"] = _read_stderr_tail(errors)
    return observed_code


def _read_report(path, returncode, stderr):
    """Retain early engine failures even when admission produced no report."""
    if returncode is not None and returncode != 0:
        refusal = _engine.read_refusal(path.parent, stderr)
        if refusal is not None:
            raise refusal
        raise FimEngineError(
            f"Sloping engine failed with exit {returncode}: "
            f"{stderr.strip()[-4000:] or 'no diagnostic on stderr'}"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise FimEngineError("Missing or invalid sloping engine report") from exc


def _validate_options(
    render_mode, reduce_shallow_to_horizontal, use_depth_weighted_faces
):
    if render_mode not in ("sloping", "slopingPretty"):
        raise ValueError("render_mode must be 'sloping' or 'slopingPretty'")
    if not isinstance(reduce_shallow_to_horizontal, bool) or not isinstance(
        use_depth_weighted_faces, bool
    ):
        raise ValueError("sloping option flags must be booleans")
    if render_mode == "sloping" and (
        reduce_shallow_to_horizontal or use_depth_weighted_faces
    ):
        raise ValueError("shallow and depth-weighted controls require slopingPretty")
    selected_options = dict(
        render_mode=render_mode,
        reduce_shallow_to_horizontal=reduce_shallow_to_horizontal,
        use_depth_weighted_faces=use_depth_weighted_faces,
    )
    return selected_options


def _validate_selection(profiles):
    selected = {"Max": "Max"} if profiles is None else dict(profiles)
    if not selected or any(
        not isinstance(name, str)
        or not _engine._SAFE_ID.fullmatch(name)
        or name in (".", "..")
        for name in selected
    ):
        raise ValueError(
            "profiles must map safe output names to 'Max' or nonnegative timestep indices"
        )
    if len({name.casefold() for name in selected}) != len(selected):
        raise ValueError("profile names must be unique ignoring case")
    for value in selected.values():
        if value != "Max" and (
            isinstance(value, bool)
            or not isinstance(value, (int, np.integer))
            or value < 0
        ):
            raise ValueError(
                "profile selectors must be 'Max' or nonnegative timestep indices"
            )
    return selected


def _validate_method(method, render_mode, max_inflight_profiles):
    concurrency_supported = method.get("bounded_profile_concurrency") is True
    if max_inflight_profiles > 1 and not concurrency_supported:
        raise FimEngineError(
            "engine lacks bounded sloping profile concurrency; install engine 0.6 or newer"
        )
    if method.get("method_id") != "rasmapper-plain-sloping/1" or not method.get(
        "stream_outputs"
    ):
        raise FimEngineError(
            "engine lacks rasmapper-plain-sloping/1; install a matching engine"
        )
    if render_mode == "slopingPretty" and not method.get("enhanced_options"):
        raise FimEngineError(
            "engine lacks additional sloping options; install a matching engine"
        )
    if render_mode == "slopingPretty" and not method.get("native_donation_history"):
        raise FimEngineError("Cell-face sloping requires native donation history (engine 0.8+)")
    selected_method_id = (
        method.get("enhanced_method_id")
        if render_mode == "slopingPretty"
        else method["method_id"]
    )
    return concurrency_supported, selected_method_id


def _profile_block(dataset, time_index, start, stop, remaining, cache, chunk_bytes):
    """Reuse bounded contiguous native time reads without changing row order."""
    from ..fast_hdf import read_dataset

    key = dataset.name
    saved = cache.get(key)
    if saved is not None:
        first, values = saved
        if start == 0 and stop == dataset.shape[1] and first <= time_index < first + len(values):
            return values[time_index - first]
    row_bytes = dataset.shape[1] * max(4, dataset.dtype.itemsize)
    count = chunk_bytes // row_bytes
    if start != 0 or stop != dataset.shape[1] or count < 2:
        cache.clear()
        return read_dataset(dataset, (slice(time_index, time_index + 1), slice(start, stop)), backend="rust")
    wanted = list(dict.fromkeys(remaining))
    direction = -1 if len(wanted) > 1 and wanted[1] < time_index else 1
    selected = set(wanted)
    first = last = time_index
    while last - first + 1 < count:
        adjacent = first - 1 if direction < 0 else last + 1
        if adjacent not in selected or not 0 <= adjacent < dataset.shape[0]:
            break
        first, last = min(first, adjacent), max(last, adjacent)
    cache.clear()
    if saved is not None:
        del saved, values
    values = read_dataset(dataset, (slice(first, last + 1), slice(None)), backend="rust")
    # One shared staging cache, not chunk_bytes per mesh. A multi-mesh request
    # remains bounded even when each mesh has a different source row width.
    if values.nbytes <= chunk_bytes:
        cache[key] = (first, values)
    return values[time_index - first]


STAGED_CELLS_METHOD = "ras-commander-staged-cells/1"


def _mesh_array(header_path, header, key, columns):
    descriptor = header["arrays"][key]
    rows = int(descriptor["rows"])
    path = Path(header_path).parent / descriptor["path"]
    if rows == 0:
        return np.empty((0, columns), dtype="<i4")
    return np.memmap(path, dtype="<i4", mode="r", shape=(rows, columns))


def _gather_incidence(info, values, rows):
    """Concatenate CSR rows ``rows`` of ``values`` (first column) in row order."""
    starts = np.asarray(info[rows, 0], dtype=np.int64)
    counts = np.asarray(info[rows, 1], dtype=np.int64)
    if (counts < 0).any() or (starts < 0).any() or (starts + counts > len(values)).any():
        raise ValueError("Invalid sloping incidence rows")
    total = int(counts.sum())
    if total == 0:
        return np.empty(0, dtype=np.int64)
    offsets = np.repeat(starts - np.cumsum(counts) + counts, counts)
    return np.asarray(values[offsets + np.arange(total), 0], dtype=np.int64)


def staged_cell_subsets(mesh_files, owner_cells):
    """Per mesh, the ascending global cells whose WSE can reach an owner pixel.

    Fast-Map's ``ras-commander-staged-cells/1`` closure: the endpoints of every
    owner-cell face, every face incident to those vertices, and both cells of
    each such face (ghost cells included). Fast-Map verifies the closure and
    refuses a subset that misses a cell. A mesh without owner cells stages
    cell 0 only, which rendering never reads. ``owner_cells`` holds
    ``[mesh_index, cell_id]`` pairs as in the sloping request.
    """
    owners = np.asarray(owner_cells, dtype=np.int64).reshape(-1, 2)
    subsets = []
    for index, header_path in enumerate(mesh_files):
        header = json.loads(Path(header_path).read_text(encoding="utf-8"))
        if header.get("schema") != "ras-commander-sloping-mesh/1":
            raise ValueError("Unsupported sloping mesh schema")
        cells = np.unique(owners[owners[:, 0] == index, 1])
        if cells.size == 0:
            subsets.append(np.zeros(1, dtype="<u4"))
            continue
        cell_info = _mesh_array(header_path, header, "cell_info", 2)
        if cells[0] < 0 or cells[-1] >= len(cell_info):
            raise ValueError("Owner cell outside sloping mesh")
        faces = _gather_incidence(cell_info, _mesh_array(header_path, header, "cell_faces", 2), cells)
        face_vertices = _mesh_array(header_path, header, "face_vertices", 2)
        vertices = np.unique(np.asarray(face_vertices[faces], dtype=np.int64))
        ring = _gather_incidence(
            _mesh_array(header_path, header, "vertex_info", 2),
            _mesh_array(header_path, header, "vertex_faces", 2),
            vertices,
        )
        face_cells = _mesh_array(header_path, header, "face_cells", 2)
        closure = np.unique(np.concatenate([
            cells, np.asarray(face_cells[np.unique(np.concatenate([faces, ring]))], dtype=np.int64).ravel(),
        ]))
        if closure[0] < 0 or closure[-1] >= len(cell_info) or closure[-1] >= 2**32:
            raise ValueError("Sloping face cell outside mesh")
        subsets.append(closure.astype("<u4"))
        del cell_info, face_vertices, face_cells
    return subsets


def write_staged_cells(root, subsets):
    """Write one ``<u4`` staged-cell file per mesh; returns their paths."""
    paths = []
    for index, cells in enumerate(subsets):
        path = Path(root) / f"staged-cells-{index}.bin"
        np.ascontiguousarray(cells, dtype="<u4").tofile(path)
        paths.append(str(path))
    return paths


def _stage_profiles(
    hdf, root, meshes, max_values, selected, *, deduplicate=False, max_staged_bytes=None,
    chunk_bytes=8 * 1024 * 1024, cell_subsets=None,
):
    """Stage float32 cell WSE per profile and mesh.

    With ``cell_subsets`` (ascending global cells per mesh, as from
    :func:`staged_cell_subsets`) each file holds only those cells' values in
    that order. Every complete source row is still read and checked finite.
    """
    from .. import HdfResultsMesh
    from ..fast_hdf import backend_scope
    from .RasFim import _file_identity
    import h5py
    if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes < 4:
        raise ValueError("chunk_bytes must be an integer >= 4")
    if cell_subsets is not None:
        cell_subsets = [np.asarray(c, dtype=np.int64) for c in cell_subsets]
        if len(cell_subsets) != len(meshes) or any(
            c.ndim != 1 or c.size == 0 or c[0] < 0 or c[-1] >= m["cell_count"]
            or (c.size > 1 and (np.diff(c) <= 0).any())
            for c, m in zip(cell_subsets, meshes)
        ):
            raise ValueError("cell_subsets must be ascending in-range cells, one array per mesh")
    before = _file_identity(hdf)

    staged_bytes = 0
    cached = {}
    units = []
    profile_views = {}
    blocks = {}
    all_selectors = list(selected.values())
    for profile_index, (name, selector) in enumerate(selected.items()):
        if deduplicate and selector in cached:
            units.append(dict(id=name, values_files=list(cached[selector])))
            continue
        values_files = []
        for i, mesh in enumerate(meshes):
            size = mesh["cell_count"]
            subset = None if cell_subsets is None else cell_subsets[i]
            stored = size if subset is None else len(subset)
            if max_staged_bytes is not None and staged_bytes + stored * 4 > max_staged_bytes:
                raise FimUnsupportedError("Prepared sloping inputs exceed max_prepared_mib")
            filename = f"values-{profile_index}-{i}.bin"
            destination = root / filename
            partial = destination.with_suffix(".partial")
            if selector == "Max":
                source = max_values[i]
                dataset_path = source["dataset"] if isinstance(source, dict) else None
                time_index = 0
            else:
                with backend_scope("rust"):
                    if i not in profile_views:
                        profile_views[i] = HdfResultsMesh.get_mesh_timeseries(
                            hdf,
                            mesh["mesh_name"],
                            "Water Surface",
                            truncate=False,
                            return_type="view",
                            include_ghost_cells=True,
                        )
                    view = profile_views[i].select(time=int(selector))
                    if view.shape != (1, size):
                        raise ValueError("Sloping profile source dimensions changed")
                    dataset_path = view.dataset_path
                    time_index = int(selector)
            try:
                with h5py.File(hdf, "r") as handle, partial.open("wb") as stream:
                    dataset = handle[dataset_path] if dataset_path is not None else None
                    if dataset is not None and (len(dataset.shape) != 2 or dataset.shape[1] != size):
                        raise ValueError("Sloping profile source dimensions changed")
                    source_itemsize = dataset.dtype.itemsize if dataset is not None else np.asarray(source).dtype.itemsize
                    chunk_cells = max(1, chunk_bytes // max(4, source_itemsize))
                    for start in range(0, size, chunk_cells):
                        stop = min(size, start + chunk_cells)
                        values = (
                            _profile_block(dataset, time_index, start, stop,
                                [v for v in all_selectors[profile_index:] if v != "Max"] if selector != "Max" else [0],
                                blocks, chunk_bytes)
                            if dataset is not None else source[start:stop]
                        )
                        array = np.asarray(values, dtype="<f4").reshape(-1)
                        if len(array) != stop - start or not np.isfinite(array).all():
                            raise ValueError(f"Invalid complete cell profile {name!r} for {mesh['mesh_name']!r}")
                        if subset is not None:
                            lo, hi = np.searchsorted(subset, [start, stop])
                            array = array[subset[lo:hi] - start]
                        stream.write(memoryview(np.ascontiguousarray(array)).cast("B"))
                        del values, array
                if _file_identity(hdf) != before:
                    raise FimEngineError("HDF source changed during chunked staging")
                partial.replace(destination)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
            values_files.append(filename)
            staged_bytes += stored * 4
        cached[selector] = values_files
        units.append(dict(id=name, values_files=values_files))
    return units, len(profile_views), staged_bytes


def map_profiles(
    hdf_path,
    terrain_path,
    output_folder,
    *,
    profiles=None,
    wsel_profiles=None,
    render_mode="sloping",
    reduce_shallow_to_horizontal=False,
    use_depth_weighted_faces=False,
    postprocessing_hdf=None,
    corner_elevation_source="auto",
    bbox=None,
    polygon=None,
    polygon_layer=None,
    aoi_crs=None,
    engine_path=None,
    threads=1,
    writer_threads=1,
    max_inflight_profiles=1,
    max_working_mib=1024,
    timeout=None,
    write_floodplain=False,
    template_raster=None,
    terrain_hdf=None,
    velocity=False,
    invalid_cells=None,
    terrain_crs_fnv1a64=None,
    _prepared=None,
    product_writer="rasterio",
    row_stream_rows=0,
    storage_areas=False,
    velocity_depth="rendered",
    derived_products=(),
    _reduce_max=False,
    shear_stress=False,
    shear_depth="rendered",
    final_format=None,
):
    from .. import HdfMesh
    from ..fast_hdf import backend_scope
    from .RasFim import (
        RasFim,
        MANIFEST_COLUMNS,
        _empty_row,
        _file_identity,
        _positive_int,
        _prepare_output_folder,
    )

    if product_writer not in ("rasterio", "native"):
        raise ValueError("product_writer must be rasterio or native")
    native_products = product_writer == "native"
    if (isinstance(row_stream_rows, bool) or not isinstance(row_stream_rows, int)
            or not 0 <= row_stream_rows <= 4096):
        raise ValueError("row_stream_rows must be an integer from 0 through 4096")
    if row_stream_rows and (
        not native_products or render_mode != "sloping" or velocity or storage_areas
        or _reduce_max or reduce_shallow_to_horizontal or use_depth_weighted_faces
    ):
        raise FimUnsupportedError(
            "row_stream_rows requires plain sloping with native products and "
            "no velocity, storage areas or reduction"
        )
    if native_products and (write_floodplain or template_raster is not None or velocity):
        raise FimUnsupportedError("Native products do not support templates, floodplain or velocity")
    from . import _final_format

    final_options = _final_format.normalize(final_format)
    if final_options is not None and (not native_products or _reduce_max):
        # Floodplain, template and velocity deliveries need arrays in Python and
        # are already refused for native products above.
        raise FimUnsupportedError(
            "final_format requires product_writer='native' Depth/WSE delivery; "
            "it has no Rasterio fallback"
        )
    selected_options = _validate_options(
        render_mode, reduce_shallow_to_horizontal, use_depth_weighted_faces
    )
    from . import _invalid_cells

    if _prepared is not None:
        if invalid_cells is not None and invalid_cells != _prepared._invalid_policy:
            raise ValueError(
                f"invalid_cells is fixed when the sloping model is prepared "
                f"({_prepared._invalid_policy!r}); prepare a new model to change it"
            )
        invalid_policy = _prepared._invalid_policy
        if terrain_crs_fnv1a64 is not None and terrain_crs_fnv1a64 != _prepared._terrain_crs_fnv1a64:
            raise ValueError(
                "terrain_crs_fnv1a64 is fixed when the sloping model is prepared "
                f"({_prepared._terrain_crs_fnv1a64!r}); prepare a new model to change it"
            )
    else:
        invalid_policy = _invalid_cells.validate_policy(
            _invalid_cells.DEFAULT_POLICY if invalid_cells is None else invalid_cells
        )
    started = time.perf_counter()
    preparation = {}
    phase = started
    threads = _positive_int(threads, "threads")
    writer_threads = _positive_int(writer_threads, "writer_threads")
    max_inflight_profiles = _positive_int(
        max_inflight_profiles, "max_inflight_profiles"
    )
    if max_inflight_profiles > 64:
        raise ValueError("max_inflight_profiles must be <= 64")
    if writer_threads > 64:
        raise ValueError("writer_threads must be <= 64")
    budget = _positive_int(max_working_mib, "max_working_mib")
    if threads > 64:
        raise ValueError("threads must be <= 64")
    if timeout is not None and (
        isinstance(timeout, bool) or not np.isfinite(timeout) or timeout <= 0
    ):
        raise ValueError("timeout must be positive and finite, or None")
    hdf = Path(hdf_path).resolve(strict=True)
    terrain = Path(terrain_path).resolve(strict=True)
    if not isinstance(velocity, bool):
        raise ValueError("velocity must be a boolean")
    if not isinstance(storage_areas, bool):
        raise ValueError("storage_areas must be a boolean")
    if storage_areas and _prepared is not None:
        raise FimUnsupportedError("prepared sloping models do not support storage_areas")
    if storage_areas and wsel_profiles is not None:
        raise FimUnsupportedError(
            "storage_areas reads storage-area WSE from the plan HDF; caller-supplied WSEL "
            "profiles carry none"
        )
    if storage_areas and velocity:
        raise FimUnsupportedError("velocity is not qualified with storage-area surfaces")
    from . import _velocity as _velocity_inputs

    derived_products = _velocity_inputs.validate_products(derived_products, velocity_depth)
    if (derived_products or velocity_depth != "rendered" or _reduce_max) and not velocity:
        raise ValueError("velocity_depth and derived_products require velocity=True")
    if _reduce_max and not derived_products:
        raise ValueError("the Max derived pass needs derived_products")
    from . import _shear as _shear_inputs

    if not isinstance(shear_stress, bool):
        raise ValueError("shear_stress must be a boolean")
    if shear_depth not in _shear_inputs.SHEAR_DEPTHS:
        raise ValueError(f"shear_depth must be one of {_shear_inputs.SHEAR_DEPTHS}")
    if shear_depth != "rendered" and not shear_stress:
        raise ValueError("shear_depth requires shear_stress=True")
    if shear_stress:
        if render_mode != "sloping":
            raise FimUnsupportedError(
                "shear stress is qualified on plain sloping (shear_depth='horizontal' for "
                "RAS Mapper's horizontal mode); slopingPretty is not"
            )
        if profiles is None:
            profiles = {"Max": "Max"}
        if wsel_profiles is not None or _prepared is not None:
            raise FimUnsupportedError(
                "shear stress needs the plan's stored time series; caller-supplied WSEL "
                "profiles and prepared models have none"
            )
        if len(dict(profiles)) != 1 or set(dict(profiles).values()) != {"Max"}:
            raise FimUnsupportedError(
                "shear stress is RAS Mapper's Max only: pass exactly one profile selecting 'Max'"
            )
        if storage_areas or _reduce_max or native_products or row_stream_rows or template_raster is not None:
            raise FimUnsupportedError(
                "shear stress does not support storage areas, the Max derived pass, native "
                "products, row streaming or template delivery"
            )
    scope_info = None
    if (terrain_hdf is not None or velocity) and _prepared is not None:
        raise FimUnsupportedError("prepared sloping models do not support terrain_hdf or velocity")
    if velocity:
        # slopingPretty options are checked against the engine's
        # velocity_with_faces record in _velocity.require_engine.
        if wsel_profiles is not None:
            raise FimUnsupportedError(
                "velocity needs stored face velocities; caller-supplied WSEL profiles have none"
            )
        if template_raster is not None:
            raise FimUnsupportedError("velocity products do not support template_raster delivery")
    if terrain_hdf is not None:
        if render_mode != "sloping":
            raise FimUnsupportedError(
                "terrain_hdf (top-priority source terrain) is qualified for plain sloping only"
            )
        from . import _terrain_scope

        scope_info = _terrain_scope.resolve(terrain_hdf, terrain)
    supplied = None
    if wsel_profiles is not None:
        if _prepared is not None:
            raise ValueError("Prepared profiles cannot be replaced during mapping")
        from ._supplied_wsel import snapshot
        supplied = snapshot(wsel_profiles, hdf, profiles=profiles, max_bytes=budget * (1 << 20))
    if _prepared is None:
        model_scope = RasFim.validate_2d_model(hdf)
    else:
        from copy import deepcopy

        model_scope = deepcopy(_prepared._model_scope)
    if shear_stress and model_scope.get("storage_areas"):
        raise FimUnsupportedError(
            "shear stress is not qualified for plans with storage areas "
            f"({model_scope['storage_areas']} found); use RAS Mapper for these plans"
        )
    if velocity and model_scope.get("storage_areas"):
        raise FimUnsupportedError(
            "velocity is not qualified for plans with storage areas "
            f"({model_scope['storage_areas']} found); use RAS Mapper for these plans"
        )
    if scope_info is not None and model_scope.get("storage_areas") and not storage_areas:
        raise FimUnsupportedError(
            "terrain_hdf is not qualified for plans with storage areas unless they are "
            f"mapped ({model_scope['storage_areas']} found); pass storage_areas=True or use "
            "RAS Mapper"
        )
    storage = None
    if storage_areas:
        from . import _storage_areas

        storage = _storage_areas.read(hdf)
        if storage is None:
            raise FimUnsupportedError("storage_areas=True but the plan has no storage areas")
    if supplied is not None:
        selected = supplied.selection
    elif _prepared is not None and _prepared._supplied:
        selected = dict(profiles)
    else:
        selected = _validate_selection(profiles)
    engine = (
        _engine.find_engine(engine_path) if _prepared is None else _prepared._engine
    )
    method = (
        _engine.engine_method(engine).get("sloping", {})
        if _prepared is None
        else _prepared._method
    )
    if native_products and not method.get("native_geotiff_outputs"):
        raise FimUnsupportedError("Native products require native_geotiff_outputs capability")
    if final_options is not None:
        _final_format.require_engine(method, final_options, row_stream_rows)
    if row_stream_rows:
        capability = method.get("native_row_streaming")
        if (
            not isinstance(capability, dict)
            or capability.get("control") != "row_stream_rows"
            or capability.get("render_mode") != "sloping"
            or isinstance(capability.get("max"), bool)
            or not isinstance(capability.get("max"), int)
            or row_stream_rows > capability["max"]
            or not isinstance(capability.get("products"), list)
            or not all(isinstance(p, str) for p in capability["products"])
            or not {"depth", "wse"}.issubset(capability["products"])
        ):
            raise FimUnsupportedError(
                "row_stream_rows requires a compatible native_row_streaming capability"
            )
    concurrency_supported, selected_method_id = _validate_method(
        method, render_mode, max_inflight_profiles
    )
    if use_depth_weighted_faces and not method.get("depth_weighted_faces"):
        raise FimEngineError("Depth weighting requires an engine advertising depth_weighted_faces (0.8+)")
    if scope_info is not None:
        from . import _terrain_scope

        _terrain_scope.require_engine(method, "sloping")
    if storage is not None:
        from . import _storage_areas

        _storage_areas.require_engine(method, "sloping")
    if velocity:
        _velocity_inputs.require_engine(
            method, render_mode, velocity_depth, derived_products,
            reduce_shallow_to_horizontal=reduce_shallow_to_horizontal,
            use_depth_weighted_faces=use_depth_weighted_faces,
        )
        if _reduce_max and method.get("derived_max") != "reduce_max/1":
            raise FimUnsupportedError("engine does not advertise derived_max reduce_max/1")
    if shear_stress:
        _shear_inputs.require_engine(method, shear_depth)
    gravity = (
        _velocity_inputs.gravity(hdf) if "froude" in derived_products else None
    )
    watched = {"hdf": hdf, "terrain": terrain, "engine": engine}
    if scope_info is not None:
        watched["terrain_hdf"] = scope_info["terrain_hdf"]
    if postprocessing_hdf is not None:
        watched["postprocessing_hdf"] = Path(postprocessing_hdf).resolve(strict=True)
        if (watched["postprocessing_hdf"].parent / "corner_elevation_receipt.json").exists():
            from ._corner_preparation import validate_receipt
            _, corner_sources = validate_receipt(hdf, watched["postprocessing_hdf"])
            watched.update(corner_sources)
    if _prepared is not None:
        watched.update(_prepared._watched)
    if template_raster is not None:
        template_raster = Path(template_raster).resolve(strict=True)
        watched["template_raster"] = template_raster
    if isinstance(polygon, (str, os.PathLike)):
        watched["polygon"] = Path(polygon).resolve(strict=True)
    before = {key: _file_identity(path) for key, path in watched.items()}
    preparation["preflight_seconds"] = time.perf_counter() - phase
    phase = time.perf_counter()
    if _prepared is None:
        cells, invalid_records = _invalid_cells.load_cells(
            hdf, policy=invalid_policy, threads=threads
        )
    else:
        cells, invalid_records = _prepared._cells, _prepared._invalid_records
    preparation["cell_polygon_seconds"] = time.perf_counter() - phase
    phase = time.perf_counter()
    _invalid_cells.require_cells(cells, invalid_records, invalid_policy)
    if supplied is not None:
        supplied.check_crs(cells.crs)
        # Validate complete identities even when the AOI will contain no pixels.
        # Required-native typed centres include ghosts, unlike the footprint.
        with backend_scope("rust"):
            source_cells = HdfMesh.get_mesh_cell_points(
                hdf, include_ghost_cells=True, include_geometry=False
            )
        supplied.align([dict(mesh_name=name, cell_count=len(group))
                        for name, group in source_cells.groupby("mesh_name", sort=False)])
        del source_cells
    constraint = _aoi.resolve_aoi(
        bbox=bbox,
        polygon=polygon,
        polygon_layer=polygon_layer,
        aoi_crs=aoi_crs,
        default_crs=cells.crs,
    )
    aoi_geometry = _aoi.geometry_in_crs(constraint, cells.crs) if constraint else None
    _invalid_cells.check_scope(invalid_records, invalid_policy, aoi_geometry)
    # Windowing selects output pixels; the complete mesh remains available for
    # face connectivity and corner reconstruction across an AOI boundary.
    plan = _horizontal.plan_grid(
        cells, terrain, constraint, budget, native=True,
        storage_areas=storage.polygons if storage is not None else None,
    )
    if plan.mask_geometry and method.get("aoi_mask") != "global-terrain-lattice/1":
        raise FimEngineError("Polygon masking requires Fast-Map global-terrain-lattice/1 (0.10.1+)")
    layout = None
    buffer_bytes = 0
    if template_raster is not None and all(plan.shape):
        from . import _sloping_products

        layout = _sloping_products.template_profile(template_raster, plan)
        buffer_bytes = layout["planned_buffer_bytes"]
        if plan.planned_bytes + buffer_bytes > budget * (1 << 20):
            raise FimUnsupportedError(
                "sloping template delivery exceeds planned array budget"
            )
    preparation["grid_plan_seconds"] = time.perf_counter() - phase
    phase = time.perf_counter()
    if _prepared is None:
        from . import _cell_validation

        # Reuse is keyed by the validated polygon content, never by file identity.
        preparation["cell_validation_reused"] = _cell_validation.validate(
            cells, terrain, plan, threads=threads
        )
    else:
        preparation["cell_validation_reused"] = _prepared._validate_grid(plan)
    preparation["cell_validation_seconds"] = time.perf_counter() - phase
    folder = _prepare_output_folder(output_folder)
    rows = {name: _empty_row(name, "not_run") for name in selected}
    details = dict(
        method="RAS Mapper sloping / Rust",
        method_id=selected_method_id,
        backend="rust",
        model_scope=model_scope,
        mapping_scope=(
            "physical 2D cells and storage-area level pools"
            if storage is not None
            else "physical 2D cells only; standalone storage-area surfaces excluded"
        ),
        output_grid_reference=(
            str(template_raster) if template_raster is not None else "terrain window"
        ),
        status="in_progress",
        options={
            **selected_options,
            "extra_depth_cutoff": None,
            "threads": threads,
            "writer_threads": writer_threads,
            "product_writer": product_writer,
            "row_stream_rows": row_stream_rows,
            "final_format": final_options,
            "max_inflight_profiles": max_inflight_profiles,
            "max_working_mib": budget,
            "write_floodplain": bool(write_floodplain),
        },
        source_profiles=selected,
        aoi=constraint.describe() if constraint else None,
        aoi_mask="global-terrain-lattice/1" if constraint else None,
        inputs={
            k: {"path": str(p), "size": before[k][0], "mtime_ns": before[k][1]}
            for k, p in watched.items()
        },
        qualification="scoped native 7.0.1; plain five-model physical-2D corpus (bounded eBFE); enhanced combinations on Bald Eagle bridges Max and Davis timesteps",
        invalid_cells=_invalid_cells.describe(invalid_records, invalid_policy, aoi_geometry),
    )
    if scope_info is not None:
        from . import _terrain_scope

        details["terrain_scope"] = _terrain_scope.describe(scope_info)
    if storage is not None:
        from . import _storage_areas

        details["storage_areas"] = _storage_areas.describe(storage, selected)
        details["qualification"] = (
            "scoped native 7.0.1; storage-area level pools qualified on "
            "BaldEagleCrkMulti2D storage-area plans (see storage_areas)"
        )
    if velocity:
        from . import _velocity

        details["velocity"] = {
            "method_id": _velocity.METHOD_ID,
            "max_source": "Maximum Face Velocity with Maximum Water Surface",
            "timestep_source": "Face Velocity at the stored output time",
            "face_lengths": "face polyline lengths",
            "velocity_depth": velocity_depth,
            "drawn": (
                "where the horizontal (cell-constant) depth > 0"
                if velocity_depth == "horizontal"
                else f"where the rendered {render_mode} depth > 0"
            ),
            "qualification": (
                "native HEC-RAS 7.0.1 velocity values do not depend on the render mode and are "
                "clipped by that mode's depth; BaldEagleCrkMulti2D bridges p05 Max sloping "
                "(973,902 px), slopingPretty and horizontal match in values and mask"
            ),
        }
        if render_mode == "slopingPretty":
            details["velocity"]["with_faces"] = {
                "method_id": method.get("velocity_with_faces"),
                "reduce_shallow_to_horizontal": bool(reduce_shallow_to_horizontal),
                "use_depth_weighted_faces": bool(use_depth_weighted_faces),
            }
        if derived_products:
            details["velocity"]["derived"] = {
                "method_id": _velocity.DERIVED_METHOD_ID,
                "products": list(derived_products),
                "gravity": gravity,
                "max": (
                    "pixelwise maximum over every stored output time (RAS Mapper Max)"
                    if _reduce_max
                    else None
                ),
            }
    if shear_stress:
        details["shear_stress"] = _shear_inputs.describe(
            shear_depth, render_mode, _shear_inputs.units(hdf)
        )
    supplied_source = (_prepared._info.get("profile_source") if _prepared is not None else None)
    if supplied is not None or supplied_source is not None:
        details["qualification"] = "Caller-supplied WSEL; aggregate/changed-terrain/option combinations require independent qualification."
        details["profile_source"] = supplied_source or {"kind": "caller-cell-wsel/1"}

    def manifest():
        frame = pd.DataFrame(list(rows.values()), columns=MANIFEST_COLUMNS)
        frame.attrs["performance"] = details.get("performance", {})
        frame.attrs["mapping_scope"] = details["mapping_scope"]
        frame.attrs["model_scope"] = model_scope
        if "profile_source" in details:
            frame.attrs["profile_source"] = details["profile_source"]
        if "terrain_scope" in details:
            frame.attrs["terrain_scope"] = details["terrain_scope"]
        if "velocity" in details:
            frame.attrs["velocity"] = details["velocity"]
        if "storage_areas" in details:
            frame.attrs["storage_areas"] = details["storage_areas"]
        if "max_derived" in details:
            frame.attrs["max_derived"] = details["max_derived"]
        if "shear_stress" in details:
            frame.attrs["shear_stress"] = details["shear_stress"]
        if "final_format" in details:
            frame.attrs["final_format"] = details["final_format"]
        frame.attrs["invalid_cells"] = details["invalid_cells"]
        return frame

    RasFim._write_manifest(folder, manifest(), details)
    try:
        if not all(plan.shape):
            rows = {
                name: _empty_row(name, "empty_aoi", crs=plan.crs.to_string())
                for name in selected
            }
        else:
            tick = time.perf_counter()
            identity = (
                _engine.terrain_identity(engine, terrain, cells.crs, terrain_crs_fnv1a64)
                if _prepared is None
                else _prepared._terrain_identity
            )
            details["terrain_crs_identity"] = dict(identity["crs_identity"])
            with tempfile.TemporaryDirectory(
                prefix=".sloping-", dir=folder
            ) as temporary:
                root = Path(temporary)
                if _prepared is None:
                    mesh_files, meshes, max_values = write_binary_mesh_inputs(
                        hdf,
                        root,
                        threads=threads,
                        include_max="Max" in selected.values(),
                        include_vertex_elevations=use_depth_weighted_faces,
                        postprocessing_hdf=postprocessing_hdf,
                        corner_elevation_source=corner_elevation_source,
                    )
                else:
                    mesh_files, meshes = _prepared._mesh_files, _prepared._meshes
                details["corner_elevations"] = {
                    mesh["mesh_name"]: mesh["corner_elevations"]
                    for mesh in meshes if "corner_elevations" in mesh
                }
                lookup = {mesh["mesh_name"]: i for i, mesh in enumerate(meshes)}
                addresses = [
                    [lookup[row.mesh_name], int(row.cell_id)]
                    for row in cells.iloc[plan.cell_positions].itertuples()
                ]
                _write_geometry(
                    root / "cells.wkb",
                    cells.geometry.iloc[plan.cell_positions].to_numpy(),
                )
                fields = {}
                if plan.mask_geometry:
                    _write_geometry(root / "aoi.wkb", [plan.geometry])
                    fields["aoi_file"] = "aoi.wkb"
                if supplied is not None:
                    from ._supplied_wsel import stage
                    units, _, metadata = stage(supplied, root, meshes)
                    details["profile_source"] = metadata
                    profile_view_count = 0
                elif _prepared is None:
                    units, profile_view_count, _ = _stage_profiles(
                        hdf, root, meshes, max_values, selected
                    )
                else:
                    units = [_prepared._units[name] for name in selected]
                    profile_view_count = 0
                if scope_info is not None:
                    from . import _terrain_scope

                    fields["terrain_scope"] = _terrain_scope.stage(scope_info, root)
                if velocity:
                    from . import _velocity

                    units = [dict(unit) for unit in units]
                    fields.update(
                        _velocity.stage(hdf, root, meshes, selected, units, threads=threads)
                    )
                if shear_stress:
                    shear_tick = time.perf_counter()
                    fields.update(
                        _shear_inputs.stage(hdf, root, meshes, shear_depth=shear_depth, threads=threads)
                    )
                    preparation["shear_staging_seconds"] = time.perf_counter() - shear_tick
                if storage is not None:
                    from . import _storage_areas

                    pools = _storage_areas.profile_values(hdf, storage, selected)
                    fields.update(_storage_areas.stage_polygons(storage, root))
                    units = [
                        dict(unit, storage_area_values_file=_storage_areas.stage_values(
                            root, f"p{i}", pools[unit["id"]]))
                        for i, unit in enumerate(units)
                    ]
                import rasterio

                if _prepared is None:
                    with rasterio.open(terrain) as src:
                        full_transform = list(src.transform.to_gdal())
                else:
                    full_transform = _prepared._terrain_transform
                final = None
                if final_options is not None:
                    with rasterio.open(terrain) as src:
                        final = _final_format.resolve(final_options, plan, src.width, src.height)
                    details["final_format"] = _final_format.describe(final_options, *final)
                    details["final_format"]["products"] = {}
                request = dict(
                    schema="ras-commander-sloping-request/1",
                    **(
                        {"options": {key: value for key, value in selected_options.items()
                                     if key != "use_depth_weighted_faces" or method.get("depth_weighted_faces")}}
                        if method.get("enhanced_options")
                        else {}
                    ),
                    terrain=str(terrain),
                    epsg=identity["epsg"],
                    crs_identity=identity["crs_identity"],
                    terrain_transform=full_transform,
                    window=[int(v) for v in plan.window.flatten()],
                    geometry_file="cells.wkb",
                    mesh_files=mesh_files,
                    owner_cells=addresses,
                    profiles=units,
                    threads=threads,
                    max_working_bytes=budget * (1 << 20) - buffer_bytes,
                    stream_outputs=not _reduce_max,
                    **({"geotiff_outputs": True} if native_products else {}),
                    **({"row_stream_rows": row_stream_rows} if row_stream_rows else {}),
                    **({"compression": "DEFLATE", "final_format": final[0]} if final else {}),
                    **fields,
                )
                if velocity_depth != "rendered":
                    request["velocity_depth"] = velocity_depth
                if derived_products:
                    request["derived_products"] = list(derived_products)
                if gravity is not None:
                    request["gravity"] = gravity
                if _reduce_max:
                    request["reduce_max"] = True
                if concurrency_supported:
                    request["max_inflight_profiles"] = max_inflight_profiles
                if _prepared is not None and _prepared._reuse_native:
                    if method.get("multi_window_cache"):
                        request["window_cache_bytes"] = _prepared._window_cache_bytes
                    if method.get("hydraulic_cache"):
                        request["hydraulic_cache_bytes"] = _prepared._hydraulic_cache_bytes
                (root / "request.json").write_text(
                    json.dumps(request), encoding="utf-8"
                )
                from importlib.metadata import PackageNotFoundError, version

                try:
                    hdf_version = version("ras-commander-fast-hdf")
                except PackageNotFoundError:
                    hdf_version = None
                details["performance"] = {
                    "corner_elevations": details.get("corner_elevations", {}),
                    "native_hdf": {
                        "package": "ras-commander-fast-hdf",
                        "version": hdf_version,
                        "numeric_payload_backend": "rust-required",
                    },
                    "preparation": preparation,
                    "profile_views_prepared": profile_view_count,
                    "hdf_and_staging_seconds": time.perf_counter() - tick,
                    "product_write_seconds": {},
                }
                if _prepared is not None:
                    details["performance"]["prepared_context"] = _prepared.info
                tick = time.perf_counter()
                expired = threading.Event()
                persistent = _prepared is not None and _prepared._reuse_native
                if persistent and _prepared._native_session is None:
                    from ._native_session import NativeSlopingSession
                    try:
                        _prepared._native_session = NativeSlopingSession(engine)
                    except OSError as exc:
                        details["engine_returncode"] = None
                        raise FimEngineNotFoundError(
                            f"Cannot start persistent sloping process {engine}: {exc}"
                        ) from exc
                from contextlib import nullcontext
                # Delete-on-close stderr avoids a Windows cleanup race when a
                # terminated child briefly retains its inherited file handle.
                with (nullcontext(_prepared._native_session.errors) if persistent else tempfile.TemporaryFile(mode="w+b")) as errors:
                    process = _prepared._native_session.process if persistent else None
                    try:
                        # Preserve startup stderr if a retained session is already dead.
                        if process is None or process.poll() is None:
                            errors.seek(0)
                            errors.truncate()
                        process = (_prepared._native_session.submit(root / "request.json", root / "out") if persistent else subprocess.Popen(
                            [str(engine), "sloping", str(root / "request.json"), str(root / "out")],
                            stdout=subprocess.PIPE, stderr=errors,
                        ))
                    except BaseException as failure:
                        observed_code = _capture_process_failure(process, errors, details)
                        if persistent:
                            _prepared._native_session.close()
                            _prepared._native_session = None
                        if isinstance(failure, OSError):
                            raise FimEngineNotFoundError(
                                f"Cannot execute sloping engine {engine}: {failure}"
                            ) from failure
                        if isinstance(failure, FimEngineError):
                            refusal = _engine.read_refusal(root / "out", details["engine_stderr"])
                            if refusal is not None:
                                context = (f"Sloping engine failed with exit {observed_code}: "
                                           if observed_code is not None else
                                           "Sloping command refused without an observed process exit: ")
                                raise _engine.EngineRefusal(context + str(refusal)) from failure
                            if observed_code not in (None, 0):
                                diagnostic = details["engine_stderr"].strip() or "no diagnostic on stderr"
                                raise FimEngineError(
                                    f"Sloping engine failed with exit {observed_code}: {diagnostic}; {failure}"
                                ) from failure
                        raise

                    def expire():
                        if process.poll() is None:
                            expired.set()
                            process.kill()

                    timer = (
                        threading.Timer(float(timeout), expire)
                        if timeout is not None
                        else None
                    )
                    if timer:
                        timer.daemon = True
                        timer.start()
                    try:
                        for name in ([] if _reduce_max else selected):
                            header = process.stdout.readline(65537)
                            if len(header) > 65536 or not header.endswith(b"\n"):
                                raise _StreamProtocolError(
                                    "Missing or invalid sloping stream header"
                                )
                            try:
                                unit = json.loads(header)
                            except (ValueError, UnicodeError) as exc:
                                raise _StreamProtocolError(
                                    "Invalid sloping stream header JSON"
                                ) from exc
                            if (
                                not isinstance(unit, dict)
                                or unit.get("id") != name
                                or unit.get("status") != "complete"
                                or unit.get("pixels") != int(np.prod(plan.shape))
                                or (unit.get("velocity") is True) != velocity
                                or unit.get("derived", []) != list(derived_products)
                                or (unit.get("shear_stress") is True) != shear_stress
                            ):
                                raise _StreamProtocolError(
                                    "Sloping stream profile or dimensions mismatch"
                                )
                            if native_products:
                                from ._native_products import deliver
                                write_tick = time.perf_counter() - unit["write_seconds"]
                                products = deliver(root / "out" / name, folder, name, unit, plan, final)
                                if final is not None:
                                    details["final_format"]["products"][name] = (
                                        _final_format.check_header(unit, final[0])
                                    )
                            else:
                                depth = _read_stream_f32(
                                    process.stdout, plan.shape, expired, timeout, "depth"
                                )
                                wse = _read_stream_f32(
                                    process.stdout, plan.shape, expired, timeout, "wse"
                                )
                                speed = (
                                    _read_stream_f32(process.stdout, plan.shape, expired, timeout, "velocity")
                                    if velocity
                                    else None
                                )
                                derived_arrays = [
                                    _read_stream_f32(process.stdout, plan.shape, expired, timeout, product)
                                    for product in derived_products
                                ]
                                shear = (
                                    _read_stream_f32(process.stdout, plan.shape, expired, timeout, "shear_stress")
                                    if shear_stress
                                    else None
                                )
                                result = SimpleNamespace(
                                    profile=name,
                                    depth=depth,
                                    wse=wse,
                                    transform=plan.transform,
                                    unit={"window": list(plan.window.flatten())},
                                )
                                write_tick = time.perf_counter()
                                with rasterio.Env(GDAL_NUM_THREADS=str(writer_threads)):
                                    if layout is None:
                                        products = RasFim._write_products(
                                            folder, result, plan.crs, write_floodplain
                                        )
                                    else:
                                        products = _sloping_products.write_products(
                                            folder,
                                            result,
                                            plan.crs,
                                            write_floodplain,
                                            layout,
                                        )
                                    if speed is not None:
                                        from . import _velocity

                                        speed_path = _velocity.velocity_path(folder, name)
                                        _products.write_raster(
                                            speed_path, speed, plan.transform, plan.crs
                                        )
                                        products["velocity_tif"] = str(speed_path)
                                    for product, values in zip(derived_products, derived_arrays):
                                        from . import _velocity

                                        path = _velocity.derived_path(folder, name, product)
                                        _products.write_raster(path, values, plan.transform, plan.crs)
                                        products[f"{product}_tif"] = str(path)
                                    del derived_arrays
                                    if shear is not None:
                                        path = _shear_inputs.shear_path(folder, name)
                                        _products.write_raster(path, shear, plan.transform, plan.crs)
                                        products["shear_stress_tif"] = str(path)
                                    del shear
                            rows[name].update(products)
                            details["performance"]["product_write_seconds"][name] = (
                                time.perf_counter() - write_tick
                            )
                            if not native_products:
                                del depth, wse, result, speed
                        if persistent:
                            terminal = process.stdout.readline(65537)
                            try:
                                terminal_valid = (len(terminal) <= 65536 and terminal.endswith(b"\n")
                                                  and json.loads(terminal) == {"command_status": "complete"})
                            except (ValueError, UnicodeError):
                                terminal_valid = False
                            if not terminal_valid:
                                raise _StreamProtocolError("Invalid native session completion frame")
                            if process.poll() is not None:
                                raise _StreamProtocolError("Native session exited unexpectedly")
                            # This command completed; the persistent process did not exit.
                            code = None
                            details["engine_command_status"] = "complete"
                        else:
                            if _reduce_max:
                                # File-output requests print the engine report; the
                                # report file below is authoritative.
                                process.stdout.read()
                            elif process.stdout.read(1):
                                raise _StreamProtocolError("Unexpected trailing sloping stream bytes")
                            code = process.wait()
                        if expired.is_set():
                            raise FimEngineError(
                                f"Sloping engine timed out after {timeout} seconds"
                            )
                        details["engine_returncode"] = code
                        diagnostic = _read_stderr_tail(errors)
                        report = _read_report(root / "out/report.json", code, diagnostic)
                        expected = list(selected)
                        units = (
                            report.get("profiles") if isinstance(report, dict) else None
                        )
                        if not isinstance(units, list) or any(
                            not isinstance(p, dict) for p in units
                        ):
                            raise FimEngineError("Invalid sloping report profile table")
                        reported_method = report.get("method")
                        if concurrency_supported:
                            effective = report.get("effective_inflight_profiles")
                            if (
                                type(report.get("requested_inflight_profiles"))
                                is not int
                                or report.get("requested_inflight_profiles")
                                != max_inflight_profiles
                                or isinstance(effective, bool)
                                or not isinstance(effective, int)
                                or not 1
                                <= effective
                                <= min(max_inflight_profiles, threads, len(selected))
                                or report.get("threads") != threads
                                or type(report.get("planned_bytes")) is not int
                                or not 0
                                < report["planned_bytes"]
                                <= request["max_working_bytes"]
                            ):
                                raise FimEngineError(
                                    "Invalid sloping concurrency report"
                                )
                        if (
                            code not in (None, 0)
                            or report.get("status") != "complete"
                            or not isinstance(reported_method, dict)
                            or reported_method.get("method_id") != selected_method_id
                            or reported_method.get("options")
                            != {
                                "CellRenderMode": "Sloping",
                                "CellStencilMode": (
                                    "WithFaces"
                                    if render_mode == "slopingPretty"
                                    else "JustFacepoints"
                                ),
                                "FacepointAdjustmentMode": "None",
                                "ShallowBehaviorMode": (
                                    "ReduceToHorizontal"
                                    if reduce_shallow_to_horizontal
                                    else "None"
                                ),
                                "UseDepthWeightedFaces": use_depth_weighted_faces,
                                "FaceWSMode": "Adjusted",
                            }
                            or [p.get("id") for p in units] != expected
                            or any(p.get("status") != "complete" for p in units)
                        ):
                            raise FimEngineError(
                                ("Sloping command failed: " if code is None else
                                 f"Sloping engine failed with exit {code}: ")
                                + str(report.get("error", "invalid report"))
                            )
                        if timer:
                            timer.cancel()
                            timer.join()
                        if expired.is_set():
                            raise FimEngineError(f"Sloping engine timed out after {timeout} seconds")
                        details["performance"]["engine_report"] = report
                        if shear_stress:
                            engine_shear = report.get("shear_stress")
                            if (
                                not isinstance(engine_shear, dict)
                                or not isinstance(engine_shear.get("method"), dict)
                                or engine_shear["method"].get("method_id") != _shear_inputs.METHOD_ID
                                or engine_shear.get("depth") != shear_depth
                            ):
                                raise FimEngineError("Missing or invalid shear-stress engine report")
                            details["shear_stress"]["engine"] = {
                                key: engine_shear.get(key)
                                for key in ("units", "factor", "meshes", "face_seconds")
                            }
                        if storage is not None:
                            from . import _storage_areas

                            block = _storage_areas.check_report(report, storage)
                            details["storage_areas"]["pixels"] = block["pixels"]
                        if _reduce_max:
                            maxima = report.get("max")
                            if (
                                not isinstance(maxima, dict)
                                or maxima.get("status") != "complete"
                                or maxima.get("products") != list(derived_products)
                            ):
                                raise FimEngineError("Missing or invalid Max derived report")
                            from . import _velocity

                            write_tick = time.perf_counter()
                            reduced = {}
                            for product in derived_products:
                                values = np.fromfile(
                                    root / "out" / "max" / f"{product}.bin", dtype="<f4"
                                )
                                if values.size != int(np.prod(plan.shape)):
                                    raise FimEngineError("Max derived product dimensions mismatch")
                                path = _velocity.max_derived_path(folder, product)
                                _products.write_raster(
                                    path, values.reshape(plan.shape), plan.transform, plan.crs
                                )
                                reduced[f"{product}_tif"] = str(path)
                            details["max_derived"] = {
                                "products": reduced,
                                "valid_pixels": dict(zip(derived_products, maxima.get("valid_pixels", []))),
                                "output_times": len(selected),
                            }
                            details["performance"]["product_write_seconds"]["max"] = (
                                time.perf_counter() - write_tick
                            )
                            rows = {name: _empty_row(name, "reduced") for name in selected}
                        if _prepared is not None:
                            _prepared._info["native_state_reused"] = bool(report.get("session", {}).get("geometry_reused"))
                            details["performance"]["prepared_context"] = _prepared.info
                    except BaseException as failure:
                        # EOF can precede the process-signalled exit; wait only
                        # briefly for transport failures, never for unrelated errors.
                        observed_code = _capture_process_failure(
                            process, errors, details, expired=expired,
                            wait_for_exit=isinstance(failure, _StreamProtocolError),
                        )
                        if final is not None:
                            # The temporary engine folder is gone once this unwinds.
                            details["engine_report_error"] = _final_format.report_error(root / "out")
                        if isinstance(failure, FimEngineError) and expired.is_set():
                            raise FimEngineError(
                                f"Sloping engine timed out after {timeout} seconds"
                            ) from failure
                        refusal = (
                            _engine.read_refusal(root / "out", details["engine_stderr"])
                            if isinstance(failure, FimEngineError)
                            else None
                        )
                        if refusal is not None:
                            if observed_code is not None:
                                raise _engine.EngineRefusal(
                                    f"Sloping engine failed with exit {observed_code}: {refusal}"
                                ) from failure
                            raise refusal from failure
                        if isinstance(failure, _StreamProtocolError) and observed_code not in (None, 0):
                            diagnostic = details["engine_stderr"].strip() or "no diagnostic on stderr"
                            raise FimEngineError(
                                f"Sloping engine failed with exit {observed_code}: {diagnostic}; {failure}"
                            ) from failure
                        if isinstance(failure, _StreamProtocolError):
                            raise FimEngineError(str(failure)) from failure
                        raise
                    finally:
                        if timer:
                            timer.cancel()
                            timer.join()
                        if not persistent:
                            process.stdout.close()
                        elif process.poll() is not None:
                            _prepared._native_session.close()
                            _prepared._native_session = None
                details["performance"]["engine_and_delivery_seconds"] = (
                    time.perf_counter() - tick
                )
        if _prepared is not None:
            _prepared._check_sources()
        if postprocessing_hdf is not None and (Path(postprocessing_hdf).parent / "corner_elevation_receipt.json").exists():
            from ._corner_preparation import validate_receipt
            validate_receipt(hdf, postprocessing_hdf)
        changed = [
            key for key, path in watched.items() if _file_identity(path) != before[key]
        ]
        if changed:
            raise FimEngineError(f"Inputs changed during sloping mapping: {changed}")
        details["status"] = "complete"
    except BaseException as exc:
        details["status"] = "aborted"
        surfaced = exc
        if (
            final_options is not None
            and isinstance(exc, FimEngineError)
            and _final_format.NODATA_REFUSAL
            in f"{exc} {details.get('engine_stderr', '')} {details.get('engine_report_error', '')}"
        ):
            # Never drop or alter a valid pixel to fit the nodata marker.
            surfaced = _final_format.nodata_collision_error(final_options["nodata"])
        for name in selected:
            for product in _products.product_paths(folder, name):
                product.unlink(missing_ok=True)
            if velocity:
                from . import _velocity

                _velocity.velocity_path(folder, name).unlink(missing_ok=True)
                for product in derived_products:
                    _velocity.derived_path(folder, name, product).unlink(missing_ok=True)
            if shear_stress:
                _shear_inputs.shear_path(folder, name).unlink(missing_ok=True)
            rows[name] = _empty_row(
                name, "failed", error=f"{type(surfaced).__name__}: {surfaced}"
            )
        if surfaced is not exc:
            raise surfaced from exc
        raise
    finally:
        details.setdefault("performance", {})["total_seconds"] = (
            time.perf_counter() - started
        )
        RasFim._write_manifest(folder, manifest(), details)
    return manifest()
