"""Static 2D mesh corner ground elevations (``HdfMesh.get_mesh_corner_elevations``).

RASMapper's depth-weighted sloping interpolation uses one terrain elevation per mesh
corner (face point). These are static terrain values, distinct from corner water
surfaces, face water surfaces and node velocities. HEC-RAS stores them in two layouts:

- ``geometry``: ``Geometry/2D Flow Areas/<mesh>/FacePoints Elevation`` in a geometry or
  plan HDF, written by 2D hydraulic-table preprocessing;
- ``mapping_cache``: ``Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/
  2D Flow Areas/<mesh>/Processed Data/Profile (Horizontal)/FacePoint Elevation`` in the
  result's ``PostProcessing.hdf``, written by RASMapper.

This module only reads. It never interpolates, reorders or replaces values, never
chooses silently between disagreeing sources, and never generates elevations (that
needs the native terrain and belongs to a separate preparation step). Both backends
apply the same validation: the native engine (``ras_commander_fast_hdf``) reads through
its ``mesh_corner_elevations`` entry point, and the explicit h5py reader is the
reference and the ``auto`` fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as _dt
import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import h5py
import numpy as np

from ..LoggingConfig import get_logger

logger = get_logger(__name__)

GEOMETRY = "geometry"
MAPPING_CACHE = "mapping_cache"
SOURCES = ("auto", GEOMETRY, MAPPING_CACHE)

GEOMETRY_ROOT = "Geometry/2D Flow Areas"
GEOMETRY_DATASET = "FacePoints Elevation"
CORNER_COORDINATES = "FacePoints Coordinate"
CACHE_ROOT = "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas"
CACHE_DATASET = "Processed Data/Profile (Horizontal)/FacePoint Elevation"

# Terrain metadata reported as provenance when present (never required).
_GEOMETRY_TERRAIN_ATTRS = ("Terrain Filename", "Terrain Layername", "Terrain File Date", "Geometry Time")
_MESH_TERRAIN_ATTRS = ("Terrain Filename", "Terrain File Date", "Property Tables Last Computed", "Data Date")
_CACHE_TERRAIN_ATTRS = ("Terrain Filename", "Terrain File Date")


class CornerElevationError(ValueError):
    """Corner elevations are not usable: missing, invalid, conflicting or stale.

    ``status`` is the :class:`MeshCornerElevations` status that caused it.
    """

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class CornerElevationCheck:
    """One staleness or agreement check: ``status`` is passed, failed or not_checked."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class CornerElevationSource:
    """Provenance of one candidate array.

    ``status``: ``ok`` (read and validated), ``missing`` (dataset or mesh absent) or
    ``invalid`` (present but not one float32 value per corner). ``attributes`` are the
    dataset's attributes exactly as h5py returns them. ``terrain`` holds the terrain
    metadata the file stores for this mesh (see :func:`get_mesh_corner_elevations`).
    ``sha256`` is the hash of the little-endian float32 bytes.
    """

    layout: str
    file: str
    dataset: str
    status: str
    detail: Optional[str]
    corner_count: int
    attributes: Mapping[str, Any]
    terrain: Mapping[str, Any]
    sha256: Optional[str]
    values: Optional[np.ndarray] = field(default=None, repr=False, compare=False)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "layout": self.layout, "file": self.file, "dataset": self.dataset,
            "status": self.status, "detail": self.detail, "corner_count": self.corner_count,
            "attributes": dict(self.attributes), "terrain": dict(self.terrain),
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class MeshCornerElevations:
    """Corner ground elevations of one mesh and how they were chosen.

    ``status``: ``ok``, ``missing``, ``invalid``, ``conflict`` or ``stale``. ``values`` is a
    read-only float32 array in ``FacePoints Coordinate`` row order when ``status`` is
    ``ok`` and ``None`` otherwise. ``source`` is the candidate the values come from;
    ``candidates`` lists every source consulted; ``checks`` are the cache staleness and
    source agreement checks; ``reason`` explains any status other than ``ok``.
    """

    mesh_name: str
    status: str
    corner_count: int
    values: Optional[np.ndarray] = field(repr=False, compare=False)
    source: Optional[CornerElevationSource]
    candidates: Tuple[CornerElevationSource, ...]
    checks: Tuple[CornerElevationCheck, ...]
    reason: Optional[str]

    def require(self) -> np.ndarray:
        """The values, or :class:`CornerElevationError` naming why they are unusable."""
        if self.status != "ok":
            raise CornerElevationError(
                f"Corner elevations of mesh {self.mesh_name!r} are {self.status}: {self.reason}",
                self.status)
        return self.values

    def as_dict(self) -> Dict[str, Any]:
        """Plain-data form (values included) for logging, JSON and exact comparison."""
        return {
            "mesh_name": self.mesh_name, "status": self.status,
            "corner_count": self.corner_count, "values": self.values,
            "source": None if self.source is None else self.source.as_dict(),
            "candidates": [c.as_dict() for c in self.candidates],
            "checks": [(c.name, c.status, c.detail) for c in self.checks],
            "reason": self.reason,
        }


# ------------------------------------------------------------------ helpers
def _plain(value):
    """Attribute value as plain Python (bytes decoded as text, numpy scalars unwrapped)."""
    if isinstance(value, (bytes, np.bytes_)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        return tuple(_plain(v) for v in value.tolist()) if value.dtype.kind in "SO" else tuple(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def _attrs(obj, backend, names=None):
    from .. import fast_hdf
    raw = fast_hdf.read_attrs(obj, backend=backend)
    return {k: _plain(v) for k, v in raw.items() if names is None or k in names}


def _sha(values):
    return hashlib.sha256(np.ascontiguousarray(values, dtype="<f4").tobytes()).hexdigest()


def _readonly(values):
    values = np.ascontiguousarray(values, dtype="<f4")
    values.flags.writeable = False
    return values


def _corner_count(hdf, mesh):
    coordinates = hdf.get(f"{GEOMETRY_ROOT}/{mesh}/{CORNER_COORDINATES}")
    if not isinstance(coordinates, h5py.Dataset):
        raise ValueError(f"Mesh {mesh!r} has no {CORNER_COORDINATES} in {hdf.filename}")
    shape = coordinates.shape
    if len(shape) != 2 or shape[1] != 2:
        raise ValueError(f"{CORNER_COORDINATES} of mesh {mesh!r} has shape {shape}, not (corners, 2)")
    return int(shape[0])


def _mesh_names(hdf):
    from .HdfMesh import HdfMesh
    return [name for name in HdfMesh.get_mesh_area_names(Path(hdf.filename))
            if isinstance(hdf.get(f"{GEOMETRY_ROOT}/{name}"), h5py.Group)]


def _validate(values_or_dataset_shape, dtype, count, where):
    """None when one float32 value per corner, else the defect."""
    shape = values_or_dataset_shape
    if dtype is None or np.dtype(dtype).kind != "f" or np.dtype(dtype).itemsize != 4:
        return f"{where} is stored as {dtype}, not float32"
    if len(shape) != 1:
        return f"{where} has shape {shape}, not one value per corner"
    if shape[0] != count:
        return f"{where} stores {shape[0]} corner elevations for {count} corners"
    return None


def _read_h5py(path, dataset_path, count, backend):
    """Reference read: ``(status, detail, values, attributes)``."""
    from .. import _fast_hdf_typed
    with h5py.File(path, "r") as f:
        ds = f.get(dataset_path)
        if ds is None:
            return "missing", f"{dataset_path} is absent", None, {}
        if not isinstance(ds, h5py.Dataset):
            return "invalid", f"{dataset_path} is not a dataset", None, {}
        defect = _validate(ds.shape, ds.dtype, count, dataset_path)
        attributes = _attrs(ds, backend)
        if defect:
            return "invalid", defect, None, attributes
        values = ds[()]
        _fast_hdf_typed._record(dataset_path, "h5py", "mesh_corner_elevations")
        # A float32 of either byte order keeps every bit in little-endian order.
        return "ok", None, values.astype("<f4", copy=False), attributes


def _read_native(module, path, dataset_path, mesh, layout, count, backend):
    """Native read: the same tuple, or ``None`` when the engine refused (caller decides)."""
    from .. import fast_hdf, _fast_hdf_typed
    # The whole array plus room for its attributes; the engine refuses anything larger.
    budget = count * 4 + (1 << 20)
    out = fast_hdf.typed_call(module, path, "mesh_corner_elevations", mesh, layout,
                              expected_corners=count, max_bytes=budget)
    capability = out["capability"]
    if capability["status"] == "unavailable":
        return "missing", f"{dataset_path} is absent", None, {}
    if capability["status"] != "supported":
        return None, capability, None, None
    value = out["value"]
    values = np.asarray(value["values"])
    if values.dtype != np.dtype("<f4") or values.shape != (count,):
        raise fast_hdf.FastHdfError(
            f"{dataset_path}: engine returned {values.dtype}{values.shape} for {count} corners")
    with h5py.File(path, "r") as f:
        attributes = _attrs(f[dataset_path], backend)
    _fast_hdf_typed._record(dataset_path, "native-typed", "mesh_corner_elevations")
    return "ok", None, values, attributes


def _read(path, dataset_path, mesh, layout, count, engine):
    """``(status, detail, values, attributes)`` under the ``engine`` backend policy."""
    from .. import fast_hdf
    mode = fast_hdf._mode(engine)
    module = fast_hdf._native(mode)
    if module is not None and not hasattr(module, "mesh_corner_elevations"):
        if mode == "rust":
            raise fast_hdf.FastHdfError(
                "The installed ras-commander-fast-hdf has no mesh_corner_elevations reader")
        module = None
    if module is None:
        return _read_h5py(path, dataset_path, count, "h5py" if mode == "python" else engine)
    try:
        result = _read_native(module, path, dataset_path, mesh, layout, count, engine)
    except Exception as exc:
        if mode == "rust":
            if isinstance(exc, fast_hdf.FastHdfError):
                raise
            raise fast_hdf.FastHdfError(f"Native corner elevation read failed for {dataset_path}: {exc}") from exc
        logger.debug("h5py fallback for corner elevations %s: %s", dataset_path, exc)
        result = None
    if result is None or result[0] is None:
        if mode == "rust":
            capability = result[1] if result else {}
            raise fast_hdf.FastHdfError(
                f"{dataset_path}: native corner elevations refused "
                f"({capability.get('status')}/{capability.get('code')}): {capability.get('reason')}")
        from .. import _fast_hdf_typed
        _fast_hdf_typed._record(dataset_path, "h5py-fallback", "mesh_corner_elevations")
        return _read_h5py(path, dataset_path, count, "h5py")
    return result


def _source(layout, path, dataset_path, count, read, terrain):
    status, detail, values, attributes = read
    return CornerElevationSource(
        layout=layout, file=str(path), dataset=dataset_path, status=status, detail=detail,
        corner_count=count, attributes=attributes or {}, terrain=terrain,
        sha256=None if values is None else _sha(values),
        values=None if values is None else _readonly(values))


def _resolve(text, base):
    """A stored Windows-style relative terrain path resolved against ``base``."""
    if not isinstance(text, str) or not text.strip():
        return None
    candidate = Path(text.replace("\\", os.sep))
    if not candidate.is_absolute():
        candidate = Path(base) / candidate
    return os.path.normcase(os.path.normpath(str(candidate)))


def _file_date(path):
    """A file's modification time in HEC-RAS's ``DDMONYYYY HH:MM:SS`` local form."""
    stamp = _dt.datetime.fromtimestamp(os.path.getmtime(path))
    return stamp.strftime("%d%b%Y %H:%M:%S").upper()


def _staleness(cache, hdf_path, geometry_terrain):
    """Checks that a cache still describes the mesh and terrain of ``hdf_path``.

    A cache dataset existing proves nothing on its own, so each piece of stored
    evidence is compared. ``failed`` makes the cache stale; ``not_checked`` means the
    evidence is not stored and is reported, not assumed.
    """
    checks = [CornerElevationCheck(
        "corner_count", "passed",
        f"{cache.corner_count} values for the {cache.corner_count} corners of {Path(hdf_path).name}")]
    terrain = cache.terrain
    mesh_terrain = geometry_terrain.get("mesh", {})
    plan_terrain = geometry_terrain.get("geometry", {})
    cache_file = _resolve(terrain.get("Terrain Filename"), Path(cache.file).parent)
    plan_file = _resolve(mesh_terrain.get("Terrain Filename") or plan_terrain.get("Terrain Filename"),
                         Path(hdf_path).parent)
    if cache_file is None or plan_file is None:
        checks.append(CornerElevationCheck(
            "terrain_file", "not_checked", "the cache or the geometry stores no Terrain Filename"))
    else:
        same = cache_file == plan_file
        checks.append(CornerElevationCheck(
            "terrain_file", "passed" if same else "failed",
            f"cache terrain {cache_file}" + (" is" if same else " differs from") + f" geometry terrain {plan_file}"))
    cache_date = terrain.get("Terrain File Date")
    mesh_date = mesh_terrain.get("Terrain File Date")
    if not isinstance(cache_date, str) or not isinstance(mesh_date, str):
        checks.append(CornerElevationCheck(
            "terrain_date", "not_checked", "the cache or the mesh stores no Terrain File Date"))
    else:
        same = cache_date.strip().upper() == mesh_date.strip().upper()
        checks.append(CornerElevationCheck(
            "terrain_date", "passed" if same else "failed",
            f"cache terrain date {cache_date}" + (" equals" if same else " differs from")
            + f" the date the mesh was preprocessed against ({mesh_date})"))
    if not isinstance(cache_date, str) or cache_file is None or not os.path.isfile(cache_file):
        checks.append(CornerElevationCheck(
            "terrain_current", "not_checked", "the cache's terrain file is not available to compare"))
    else:
        current = _file_date(cache_file)
        same = current == cache_date.strip().upper()
        checks.append(CornerElevationCheck(
            "terrain_current", "passed" if same else "failed",
            f"terrain file modified {current}" + (", as recorded" if same else f", cache recorded {cache_date}")))
    cache_time, hdf_time = os.path.getmtime(cache.file), os.path.getmtime(hdf_path)
    checks.append(CornerElevationCheck(
        "cache_after_hdf", "passed" if cache_time >= hdf_time else "failed",
        f"{Path(cache.file).name} was " + ("written after" if cache_time >= hdf_time else "written before")
        + f" {Path(hdf_path).name} was last modified"))
    return checks


def _result(mesh, count, status, source, candidates, checks, reason):
    return MeshCornerElevations(
        mesh_name=mesh, status=status, corner_count=count,
        values=None if source is None or status != "ok" else source.values,
        source=source if status == "ok" else None,
        candidates=tuple(candidates), checks=tuple(checks), reason=reason)


def _select(mesh, count, source, geometry, cache, checks):
    """Deterministic selection; see :func:`get_mesh_corner_elevations`."""
    candidates = [c for c in (geometry, cache) if c is not None]
    stale = [c for c in checks if c.status == "failed" and c.name != "agreement"]
    for c in candidates:
        if c.status == "invalid":
            return _result(mesh, count, "invalid", None, candidates, checks, f"{c.layout}: {c.detail}")
    if geometry is not None and cache is not None and geometry.status == cache.status == "ok":
        if geometry.sha256 != cache.sha256 or geometry.values.tobytes() != cache.values.tobytes():
            return _result(mesh, count, "conflict", None, candidates, checks,
                           f"geometry {geometry.file} and mapping cache {cache.file} store different values")
        return _result(mesh, count, "ok", geometry, candidates, checks, None)
    if geometry is not None and geometry.status == "ok":
        return _result(mesh, count, "ok", geometry, candidates, checks, None)
    if cache is not None and cache.status == "ok":
        if stale:
            return _result(mesh, count, "stale", None, candidates, checks,
                           "mapping cache may be stale: " + "; ".join(c.detail for c in stale))
        return _result(mesh, count, "ok", cache, candidates, checks, None)
    where = " or ".join(f"{c.layout} ({c.dataset} in {c.file})" for c in candidates)
    return _result(mesh, count, "missing", None, candidates, checks,
                   f"no stored corner elevations: {where}")


def get_mesh_corner_elevations(hdf_path, mesh_name=None, *, postprocessing_hdf=None,
                               source="auto", engine="auto"):
    """Read stored 2D mesh corner ground elevations with provenance (read-only).

    See :meth:`ras_commander.hdf.HdfMesh.get_mesh_corner_elevations`.
    """
    from .. import fast_hdf
    fast_hdf._normalize_backend(engine)
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    if source == GEOMETRY and postprocessing_hdf is not None:
        raise ValueError("source='geometry' reads only hdf_path; omit postprocessing_hdf "
                         "or use source='auto' to check it against the geometry")
    if source == MAPPING_CACHE and postprocessing_hdf is None:
        raise ValueError("source='mapping_cache' needs postprocessing_hdf (the result's PostProcessing.hdf)")
    hdf_path = Path(hdf_path).resolve(strict=True)
    cache_path = None if postprocessing_hdf is None else Path(postprocessing_hdf).resolve(strict=True)
    if cache_path is not None and cache_path == hdf_path:
        raise ValueError("postprocessing_hdf must be a different file from hdf_path")
    with fast_hdf.backend_scope(engine), h5py.File(hdf_path, "r") as hdf:
        names = _mesh_names(hdf)
        if mesh_name is not None:
            if mesh_name not in names:
                raise ValueError(f"Mesh {mesh_name!r} is not a 2D flow area of {hdf_path.name}: {names}")
            names = [mesh_name]
        geometry_attrs = _attrs(hdf["Geometry"], engine, _GEOMETRY_TERRAIN_ATTRS) if "Geometry" in hdf else {}
        plan = []
        for mesh in names:
            mesh_attrs = _attrs(hdf[f"{GEOMETRY_ROOT}/{mesh}"], engine, _MESH_TERRAIN_ATTRS)
            plan.append((mesh, _corner_count(hdf, mesh), {"geometry": geometry_attrs, "mesh": mesh_attrs}))
    results = {}
    with fast_hdf.backend_scope(engine):
        for mesh, count, terrain in plan:
            geometry = cache = None
            if source in ("auto", GEOMETRY):
                path = f"{GEOMETRY_ROOT}/{mesh}/{GEOMETRY_DATASET}"
                geometry = _source(GEOMETRY, hdf_path, path, count,
                                   _read(str(hdf_path), path, mesh, GEOMETRY, count, engine), terrain)
            checks = []
            if cache_path is not None:
                path = f"{CACHE_ROOT}/{mesh}/{CACHE_DATASET}"
                read = _read(str(cache_path), path, mesh, MAPPING_CACHE, count, engine)
                cache_terrain = {k: v for k, v in (read[3] or {}).items() if k in _CACHE_TERRAIN_ATTRS}
                cache = _source(MAPPING_CACHE, cache_path, path, count, read, cache_terrain)
                if cache.status == "ok":
                    checks = _staleness(cache, hdf_path, terrain)
                    if geometry is not None and geometry.status == "ok":
                        same = geometry.values.tobytes() == cache.values.tobytes()
                        checks.append(CornerElevationCheck(
                            "agreement", "passed" if same else "failed",
                            "geometry and mapping cache store bit-identical values" if same
                            else "geometry and mapping cache store different values"))
            results[mesh] = _select(mesh, count, source, geometry, cache, checks)
    return results[mesh_name] if mesh_name is not None else results
