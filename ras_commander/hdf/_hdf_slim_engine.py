"""Self-contained engine for lossless HEC-RAS result HDF repacking ("slim").

This file is the implementation behind :class:`ras_commander.hdf.HdfSlim`. It imports only
the standard library, h5py and numpy, so it can be copied byte for byte into a Linux job and
run there as a script. Its SHA-256 is recorded in every manifest as
``software.implementation_sha256``; ``.gitattributes`` keeps it LF on every checkout so that
digest is the same on every platform.

What a slim copy is
-------------------
The output keeps the HEC-RAS layout and every dataset path, so RAS Mapper and HDF readers
open it unchanged. It differs from the source in two ways only:

1. In each 2D flow area group under ``SERIES_ROOT`` (Base Output unsteady time series), the
   time-by-entity series that the policy does not keep are not copied. Everything else in
   the file is copied unchanged: geometry, plan and event data, summary maxima, mesh
   subgroups such as boundary-condition lines, other output blocks and all attributes.
2. Kept series are rewritten in tiles of ``time_chunk_steps`` x ``space_chunk_size`` with
   the HDF5 shuffle and deflate filters. Values are bit-identical to the source.

The source is never modified. The output is written as ``<output>.partial`` beside its
destination, verified object by object (shape, dtype, attributes, exact bytes) and only then
renamed. On any failure no output and no partial file remain.

Command line (also ``python -m ras_commander.hdf.HdfSlim``)::

    python _hdf_slim_engine.py SOURCE.hdf OUTPUT.hdf --manifest OUTPUT.hdf_slim.json
        [--preset inundation-mapping | --policy-json POLICY.json]
        [--extra-series NAME ...] [--workers N] [--no-source-hash]
    python _hdf_slim_engine.py SOURCE.hdf --dry-run [--manifest PLAN.json]

Exit codes: 0 completed; 1 failed (the manifest records ``reason_code``); 2 bad arguments,
policy or input. A manifest is written for every run that reaches argument parsing, except
when its path would alias the source, output or partial output. No values, units, CRS or
vertical datum are converted. Not hydraulic approval.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import shutil
import sys
import time
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np

SCHEMA = "ras-commander-hdf-slim/v1"
PLAN_SCHEMA = "ras-commander-hdf-slim-plan/v1"
SERIES_ROOT = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas"
TIME_PATH = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time"
VERIFICATION_METHOD = "every kept object: shape, dtype, attributes, exact bytes"
MAX_PENDING_TILES = 8  # bounds raw and compressed tile buffers independently of mesh width
SPACE_RESERVE_BYTES = 1 << 30
DEFAULT_PRESET = "inundation-mapping"

#: Named policies. ``inundation-mapping`` keeps what depth/WSE mapping and flow sampling read:
#: Water Surface and Face Flow (Face Velocity for a mesh that has no Face Flow), plus Depth
#: and the cumulative precipitation/excess depths of rain-on-grid runs whenever present.
PRESETS: dict[str, dict[str, Any]] = {
    "inundation-mapping": {
        "required": ("Water Surface", "Face Flow"),
        "keep_if_present": (
            "Cell Cumulative Precipitation Depth",
            "Cell Cumulative Excess Depth",
            "Depth",
        ),
        "fallbacks": {"Face Flow": "Face Velocity"},
    },
}

BAD_REQUEST_CODES = ("HDF_SLIM_INVALID_POLICY", "HDF_SLIM_INPUT_INVALID", "HDF_SLIM_OUTPUT_EXISTS")
REASON_CODES = (
    "HDF_SLIM_VERIFIED",
    "HDF_SLIM_REQUIRED_DATASET_MISSING",
    "HDF_SLIM_NO_2D_SERIES",
    "HDF_SLIM_VERIFY_FAILED",
    "HDF_SLIM_INSUFFICIENT_SPACE",
    "HDF_SLIM_UNSUPPORTED_LAYOUT",
    "HDF_SLIM_INVALID_POLICY",
    "HDF_SLIM_INPUT_INVALID",
    "HDF_SLIM_OUTPUT_EXISTS",
    "HDF_SLIM_IO_ERROR",
    "HDF_SLIM_UNEXPECTED_ERROR",
)
_POLICY_INPUT_KEYS = {
    "name", "required", "keep_if_present", "fallbacks", "extra_series",
    "time_chunk_steps", "space_chunk_size", "deflate_level",
}
_POLICY_DERIVED_KEYS = {"keep", "series_root"}


class HdfSlimError(Exception):
    """Failure with a stable ``HDF_SLIM_*`` reason code."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


def _names(value: Any, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"{label} must be a list of series names")
    if not all(isinstance(k, str) and k.strip() and k == k.strip() and "/" not in k for k in value):
        raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"{label} must be non-empty series names")
    if len(set(value)) != len(value):
        raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"{label} must not repeat a name")
    return tuple(value)


def _int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"{label} must be an integer")
    return value


@dataclass(frozen=True)
class HdfSlimPolicy:
    """Which per-mesh time series to keep and how to store them.

    required: series every mesh must have (unless a fallback substitutes).
    keep_if_present: series kept when a mesh has them; never required.
    fallbacks: ``(required_name, substitute)`` pairs. A mesh that lacks ``required_name``
        but has ``substitute`` keeps the substitute instead.
    extra_series: additional required series, appended after ``required``.
    time_chunk_steps, space_chunk_size: tile shape (time steps x cells or faces).
    deflate_level: HDF5 deflate (gzip) level 1-9, applied after the shuffle filter.
    name: preset name, or None for a user-defined policy.
    """

    required: tuple[str, ...] = ("Water Surface",)
    keep_if_present: tuple[str, ...] = ()
    fallbacks: tuple[tuple[str, str], ...] = ()
    extra_series: tuple[str, ...] = ()
    time_chunk_steps: int = 16
    space_chunk_size: int = 16384
    deflate_level: int = 4
    name: str | None = None

    @classmethod
    def preset(cls, name: str = DEFAULT_PRESET, **overrides: Any) -> HdfSlimPolicy:
        """Return a named preset, optionally with ``extra_series`` or chunk overrides."""
        if not isinstance(name, str) or name not in PRESETS:
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"unknown preset {name!r}; known: {sorted(PRESETS)}")
        base = dict(PRESETS[name], name=name)
        base.update(overrides)
        return cls.from_dict(base)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HdfSlimPolicy:
        """Build and validate a policy from a mapping, including a manifest ``policy``.

        Input form: ``required`` excludes ``extra_series``. Manifest form (written by
        :meth:`to_dict`, recognized by its ``keep`` key): ``required`` ends with the
        ``extra_series``. ``keep`` and ``series_root`` are derived; when present they must
        match.
        """
        if not isinstance(data, Mapping):
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "policy must be an object")
        unknown = set(data) - _POLICY_INPUT_KEYS - _POLICY_DERIVED_KEYS
        if unknown:
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"unknown policy keys {sorted(unknown)}")
        fallbacks = data.get("fallbacks", {})
        if not isinstance(fallbacks, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in fallbacks.items()
        ):
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "fallbacks must map a required series to its substitute")
        name = data.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "name must be a non-empty string or null")
        extra = _names(data.get("extra_series", ()), "extra_series")
        required = _names(data.get("required", cls.required), "required")
        if "keep" in data:
            # Manifest form (to_dict): ``required`` lists required series followed by extras.
            if required[len(required) - len(extra):] != extra:
                raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "required must end with extra_series")
            required = required[: len(required) - len(extra)]
        policy = cls(
            required=required,
            keep_if_present=_names(data.get("keep_if_present", ()), "keep_if_present"),
            fallbacks=tuple(fallbacks.items()),
            extra_series=extra,
            time_chunk_steps=_int(data.get("time_chunk_steps", cls.time_chunk_steps), "time_chunk_steps"),
            space_chunk_size=_int(data.get("space_chunk_size", cls.space_chunk_size), "space_chunk_size"),
            deflate_level=_int(data.get("deflate_level", cls.deflate_level), "deflate_level"),
            name=name,
        )
        policy.validate()
        if "keep" in data and list(data["keep"]) != list(policy.keep):
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "keep does not match required/extra/keep_if_present")
        if "series_root" in data and data["series_root"] != SERIES_ROOT:
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "series_root is not the Base Output 2D series root")
        return policy

    @property
    def all_required(self) -> tuple[str, ...]:
        """Series every mesh must have: ``required`` then ``extra_series``."""
        return tuple(dict.fromkeys((*self.required, *self.extra_series)))

    @property
    def keep(self) -> tuple[str, ...]:
        """Series kept when present, in order: required, extra_series, keep_if_present."""
        return tuple(dict.fromkeys((*self.all_required, *self.keep_if_present)))

    def mesh_keep(self, group: h5py.Group) -> tuple[str, ...]:
        """Series kept for one mesh: ``keep`` plus substitutes for missing required series."""
        subs = tuple(sub for req, sub in self.fallbacks if req not in group and sub in group)
        return tuple(dict.fromkeys((*self.keep, *subs)))

    def validate(self) -> None:
        """Raise ``HdfSlimError(HDF_SLIM_INVALID_POLICY)`` for unusable settings."""
        _names(self.required, "required")
        _names(self.keep_if_present, "keep_if_present")
        _names(self.extra_series, "extra_series")
        if not self.required:
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "required must name at least one series")
        if set(self.extra_series) & (set(self.required) | set(self.keep_if_present)):
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "extra_series repeats a required or keep_if_present series")
        if set(self.required) & set(self.keep_if_present):
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "a series cannot be both required and keep_if_present")
        originals = [req for req, _ in self.fallbacks]
        subs = [sub for _, sub in self.fallbacks]
        _names(originals, "fallbacks keys")
        _names(subs, "fallbacks values")
        if not set(originals) <= set(self.all_required):
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "fallbacks may only substitute required series")
        if set(subs) & set(self.all_required):
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "a fallback substitute cannot be a required series")
        for label, value in (("time_chunk_steps", self.time_chunk_steps),
                             ("space_chunk_size", self.space_chunk_size)):
            if type(value) is not int or value < 1:
                raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"{label} must be a positive integer")
        if type(self.deflate_level) is not int or not 1 <= self.deflate_level <= 9:
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "deflate_level must be 1-9")

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready policy as recorded in manifests (round-trips through :meth:`from_dict`)."""
        return {
            "name": self.name,
            "keep": list(self.keep),
            "required": list(self.all_required),
            "keep_if_present": list(self.keep_if_present),
            "fallbacks": {req: sub for req, sub in self.fallbacks},
            "extra_series": list(self.extra_series),
            "time_chunk_steps": self.time_chunk_steps,
            "space_chunk_size": self.space_chunk_size,
            "deflate_level": self.deflate_level,
            "series_root": SERIES_ROOT,
        }


@dataclass
class SlimRecord:
    """Datasets dropped, re-chunked and copied while writing one slim file."""

    dropped: list[dict] = field(default_factory=list)
    rechunked: list[dict] = field(default_factory=list)
    copied: int = 0


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017 - engine also runs on Python < 3.11


def sha256_file(path: Path, block: int = 16 << 20) -> str:
    """SHA-256 hex digest of a file, read in 16 MiB blocks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(block), b""):
            h.update(b)
    return h.hexdigest()


def implementation_sha256() -> str:
    """SHA-256 of this engine file, recorded as ``software.implementation_sha256``."""
    return sha256_file(Path(__file__))


def default_workers() -> int:
    """CPUs available to this process (Slurm/cgroup affinity aware), capped at 8."""
    try:
        n = len(os.sched_getaffinity(0))
    except AttributeError:  # not on Linux
        n = os.cpu_count() or 1
    return max(1, min(8, n))


def _is_mesh_series_group(name: str) -> bool:
    parent, _, mesh = name.rpartition("/")
    return parent == SERIES_ROOT and bool(mesh)


def _time_steps(group: h5py.Group) -> int:
    """Rows of the series time axis for one mesh group.

    The Base Output ``Time`` table defines the axis; without it, the mesh's
    ``Water Surface`` rows do. When both exist they must agree.
    """
    ws = group.get("Water Surface")
    ws_rows = int(ws.shape[0]) if isinstance(ws, h5py.Dataset) and ws.ndim == 2 else None
    t = group.file.get(TIME_PATH)
    if isinstance(t, h5py.Dataset) and t.ndim == 1:
        if ws_rows is not None and ws_rows != t.shape[0]:
            raise HdfSlimError(
                "HDF_SLIM_UNSUPPORTED_LAYOUT",
                f"{group.name}: Water Surface has {ws_rows} rows but the Time table has {t.shape[0]}",
            )
        return int(t.shape[0])
    if ws_rows is not None:
        return ws_rows
    raise HdfSlimError(
        "HDF_SLIM_UNSUPPORTED_LAYOUT",
        f"{group.name}: no Water Surface series or Time table to define the time axis",
    )


def _check_series(group: h5py.Group, name: str, nt: int) -> None:
    """Raise unless ``group[name]`` is a non-empty numeric time-by-entity series on the axis."""
    obj = group[name]
    if (
        not isinstance(obj, h5py.Dataset)
        or obj.ndim != 2
        or obj.dtype.kind not in "fiu"
        or obj.shape[0] != nt
        or nt < 1
        or obj.shape[1] < 1
    ):
        shape = getattr(obj, "shape", None)
        dtype = getattr(obj, "dtype", None)
        raise HdfSlimError(
            "HDF_SLIM_UNSUPPORTED_LAYOUT",
            f"{group.name}/{name}: kept series must be numeric, non-empty and time-by-entity "
            f"with {nt} time steps; got {shape} {dtype}",
        )


def _copy_attrs(src: Any, dst: Any) -> None:
    for k, v in src.attrs.items():
        dst.attrs.create(k, v, dtype=src.attrs.get_id(k).dtype)


def _shuffle(block: np.ndarray) -> bytes:
    """HDF5 shuffle filter: byte planes of the chunk's elements, in storage order."""
    return np.ascontiguousarray(block).view(np.uint8).reshape(-1, block.dtype.itemsize).T.tobytes()


def _filters(ds: h5py.Dataset) -> list[str]:
    out = []
    if ds.shuffle:
        out.append("shuffle")
    if ds.compression:
        out.append(f"{ds.compression}:{ds.compression_opts}")
    return out


def _rechunk(src: h5py.Dataset, parent: h5py.Group, name: str, policy: HdfSlimPolicy, pool) -> dict:
    """Write src into parent[name] as shuffle+deflate tiles (direct chunk writes, parallel zlib)."""
    if src.ndim != 2 or src.dtype.kind not in "fiu":
        raise HdfSlimError(
            "HDF_SLIM_UNSUPPORTED_LAYOUT",
            f"{src.name}: expected a 2D numeric series, got {src.shape} {src.dtype}",
        )
    nt, ne = src.shape
    if nt < 1 or ne < 1:
        raise HdfSlimError("HDF_SLIM_UNSUPPORTED_LAYOUT", f"{src.name}: empty series {src.shape}")
    tc, ec = min(policy.time_chunk_steps, nt), min(policy.space_chunk_size, ne)
    dst = parent.create_dataset(
        name,
        shape=src.shape,
        dtype=src.dtype,
        chunks=(tc, ec),
        shuffle=True,
        compression="gzip",
        compression_opts=policy.deflate_level,
        maxshape=src.maxshape,
        fillvalue=src.fillvalue,
    )
    _copy_attrs(src, dst)
    level = policy.deflate_level

    def encode(tile: np.ndarray) -> bytes:
        return zlib.compress(_shuffle(tile), level)

    stored = 0
    for t0 in range(0, nt, tc):
        for batch_start in range(0, ne, ec * MAX_PENDING_TILES):
            tiles = []
            for e0 in range(batch_start, min(ne, batch_start + ec * MAX_PENDING_TILES), ec):
                tile = src[t0 : min(nt, t0 + tc), e0 : min(ne, e0 + ec)]
                if tile.shape != (tc, ec):  # HDF5 edge chunks still have full chunk dimensions
                    padded = np.full((tc, ec), src.fillvalue, dtype=src.dtype)
                    padded[: tile.shape[0], : tile.shape[1]] = tile
                    tile = padded
                tiles.append(((t0, e0), tile))
            encoded = list(pool.map(encode, [tile for _, tile in tiles]))
            for (offset, _), payload in zip(tiles, encoded):
                dst.id.write_direct_chunk(offset, payload, filter_mask=0)
                stored += len(payload)
    return {
        "path": src.name,
        "shape": list(src.shape),
        "dtype": str(src.dtype),
        "source_chunks": list(src.chunks or []),
        "source_filters": _filters(src),
        "source_stored_bytes": int(src.id.get_storage_size()),
        "chunks": [tc, ec],
        "filters": ["shuffle", f"deflate:{level}"],
        "stored_bytes": stored,
    }


def _classify(sg: h5py.Group, policy: HdfSlimPolicy):
    """Yield (key, obj, action) for one group; action is group, drop, rechunk or copy."""
    mesh_series = _is_mesh_series_group(sg.name.lstrip("/"))
    nt = _time_steps(sg) if mesh_series else None
    keep = policy.mesh_keep(sg) if mesh_series else ()
    for key in sg:
        link = sg.get(key, getlink=True)
        if isinstance(link, (h5py.SoftLink, h5py.ExternalLink)):
            raise HdfSlimError("HDF_SLIM_UNSUPPORTED_LAYOUT", f"{sg.name}/{key}: links unsupported")
        obj = sg[key]
        if h5py.h5o.get_info(obj.id).rc > 1:
            raise HdfSlimError("HDF_SLIM_UNSUPPORTED_LAYOUT", f"{sg.name}/{key}: hard-linked objects unsupported")
        series = mesh_series and isinstance(obj, h5py.Dataset) and obj.ndim == 2
        series = series and obj.shape[0] == nt
        if isinstance(obj, h5py.Group):
            yield key, obj, "group"
        elif series and key not in keep:
            yield key, obj, "drop"
        elif series:
            yield key, obj, "rechunk"
        else:
            yield key, obj, "copy"


def _copy_tree(src: h5py.File, dst: h5py.File, policy: HdfSlimPolicy, pool, rec: SlimRecord) -> None:
    _copy_attrs(src, dst)

    def walk(sg: h5py.Group, dg: h5py.Group) -> None:
        for key, obj, action in _classify(sg, policy):
            if action == "group":
                ng = dg.create_group(key)
                _copy_attrs(obj, ng)
                walk(obj, ng)
            elif action == "drop":
                rec.dropped.append(
                    {
                        "path": obj.name,
                        "shape": list(obj.shape),
                        "dtype": str(obj.dtype),
                        "stored_bytes": int(obj.id.get_storage_size()),
                    }
                )
            elif action == "rechunk":
                rec.rechunked.append(_rechunk(obj, dg, key, policy, pool))
            else:
                sg.copy(obj, dg, name=key)  # same dtype, layout, filters and attributes
                rec.copied += 1

    walk(src, dst)


def _require_series(src: h5py.File, policy: HdfSlimPolicy) -> list[str]:
    """Return mesh names; raise unless every mesh has every required series (or its fallback)."""
    if SERIES_ROOT not in src:
        raise HdfSlimError("HDF_SLIM_NO_2D_SERIES", f"{SERIES_ROOT} absent; not a 2D unsteady result")
    meshes = [m for m in src[SERIES_ROOT] if isinstance(src[SERIES_ROOT][m], h5py.Group)]
    if not meshes:
        raise HdfSlimError("HDF_SLIM_NO_2D_SERIES", "no 2D flow areas in the time series")
    fallbacks = dict(policy.fallbacks)
    for m in meshes:
        group = src[SERIES_ROOT][m]
        for k in policy.all_required:
            if k in group:
                continue
            sub = fallbacks.get(k)
            if sub is not None and sub in group:
                nt = _time_steps(group)
                obj = group[sub]
                if (
                    not isinstance(obj, h5py.Dataset)
                    or obj.ndim != 2
                    or obj.dtype.kind not in "fiu"
                    or obj.shape[0] != nt
                    or obj.shape[1] < 1
                ):
                    raise HdfSlimError(
                        "HDF_SLIM_UNSUPPORTED_LAYOUT",
                        f"{m}: {sub} must be a numeric time-by-entity series matching the time axis",
                    )
                continue  # the substitute is kept instead
            raise HdfSlimError(
                "HDF_SLIM_REQUIRED_DATASET_MISSING",
                f"{m}: {k} missing (enable it in the plan outputs)",
            )
        nt = _time_steps(group)
        for k in policy.mesh_keep(group):
            if k in group:
                _check_series(group, k, nt)
    return meshes


def _fallbacks_applied(src: h5py.File, policy: HdfSlimPolicy, meshes: Sequence[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for m in meshes:
        group = src[SERIES_ROOT][m]
        used = {req: sub for req, sub in policy.fallbacks if req not in group and sub in group}
        if used:
            out[m] = used
    return out


def _copied_stored_bytes(src: h5py.File, policy: HdfSlimPolicy) -> int:
    """Stored bytes of every dataset copied unchanged (everything not dropped or re-chunked)."""
    total = 0

    def walk(group: h5py.Group) -> None:
        nonlocal total
        for _, obj, action in _classify(group, policy):
            if action == "group":
                walk(obj)
            elif action == "copy":
                total += int(obj.id.get_storage_size())

    walk(src)
    return total


def _retained_raw_bytes(src: h5py.File, policy: HdfSlimPolicy, meshes: Sequence[str]) -> int:
    return sum(
        src[SERIES_ROOT][mesh][name].nbytes
        for mesh in meshes
        for name in policy.mesh_keep(src[SERIES_ROOT][mesh])
        if name in src[SERIES_ROOT][mesh]
    )


def _open_source(source: Path) -> h5py.File:
    try:
        return h5py.File(source, "r")
    except OSError as exc:
        raise HdfSlimError("HDF_SLIM_INPUT_INVALID", f"{source.name}: not a readable HDF5 file ({exc})") from exc


def plan(source: Path, policy: HdfSlimPolicy | None = None) -> dict:
    """Report what a slim of ``source`` would keep and drop, without writing anything.

    Read-only: inspects metadata and storage sizes only, never series values. Raises
    ``HdfSlimError`` exactly where :func:`slim` would before writing (policy, input, layout,
    missing required series). The compressed output size depends on the data and is not
    estimated; ``kept_series_raw_bytes`` is the scratch space a slim needs (plus 1 GiB).
    """
    policy = policy or HdfSlimPolicy.preset()
    policy.validate()
    source = Path(source)
    if not source.is_file():
        raise HdfSlimError("HDF_SLIM_INPUT_INVALID", f"source not found: {source.name}")
    with _open_source(source) as src:
        meshes = _require_series(src, policy)
        kept: list[dict] = []
        dropped: list[dict] = []
        other = 0

        def walk(sg: h5py.Group) -> None:
            nonlocal other
            for _, obj, action in _classify(sg, policy):
                if action == "group":
                    walk(obj)
                    continue
                row = {"path": obj.name, "shape": list(obj.shape), "dtype": str(obj.dtype),
                           "stored_bytes": int(obj.id.get_storage_size())}
                if action == "drop":
                    dropped.append(row)
                elif action == "rechunk":
                    if obj.ndim != 2 or obj.dtype.kind not in "fiu":
                        raise HdfSlimError(
                            "HDF_SLIM_UNSUPPORTED_LAYOUT",
                            f"{obj.name}: expected a 2D numeric series, got {obj.shape} {obj.dtype}",
                        )
                    kept.append(dict(row, raw_bytes=int(obj.nbytes)))
                else:
                    other += row["stored_bytes"]

        walk(src)
        raw = _retained_raw_bytes(src, policy, meshes)
        return {
            "schema": PLAN_SCHEMA,
            "source": {"name": source.name, "bytes": source.stat().st_size},
            "policy": policy.to_dict(),
            "meshes": meshes,
            "fallbacks_applied": _fallbacks_applied(src, policy, meshes),
            "applied_keep": {
                m: sorted(r["path"] for r in kept if r["path"].startswith(f"/{SERIES_ROOT}/{m}/"))
                for m in meshes
            },
            "kept": kept,
            "dropped": dropped,
            "kept_series_raw_bytes": raw,
            "kept_series_source_stored_bytes": sum(r["stored_bytes"] for r in kept),
            "dropped_stored_bytes": sum(r["stored_bytes"] for r in dropped),
            "other_stored_bytes": other,
            "required_free_bytes": raw + other + SPACE_RESERVE_BYTES,
        }


def retained_raw_bytes(source: Path, policy: HdfSlimPolicy | None = None) -> int:
    """Raw (uncompressed) bytes of the series a slim would keep; for scratch admission."""
    return plan(source, policy)["kept_series_raw_bytes"]


def _same_attrs(a: Any, b: Any) -> bool:
    if set(a.attrs) != set(b.attrs):
        return False
    for k in a.attrs:
        if a.attrs.get_id(k).dtype != b.attrs.get_id(k).dtype:
            return False
        x, y = np.asarray(a.attrs[k]), np.asarray(b.attrs[k])
        if x.shape != y.shape:
            return False
        if x.dtype.kind == "O":
            if x.ravel().tolist() != y.ravel().tolist():
                return False
        elif x.tobytes() != y.tobytes():  # exact bits, NaN-safe
            return False
    return True


def _same_value(x: Any, y: Any) -> bool:
    """Exact equality for one element of an object/vlen/compound dataset (NaN-safe)."""
    if isinstance(x, tuple) or isinstance(y, tuple):  # compound row
        return (isinstance(x, tuple) and isinstance(y, tuple) and len(x) == len(y)
                and all(_same_value(u, v) for u, v in zip(x, y)))
    if isinstance(x, np.ndarray) or isinstance(y, np.ndarray):  # vlen numeric
        x, y = np.asarray(x), np.asarray(y)
        return x.dtype == y.dtype and x.shape == y.shape and x.tobytes() == y.tobytes()
    if isinstance(x, float) and isinstance(y, float):
        return np.float64(x).tobytes() == np.float64(y).tobytes()
    return type(x) is type(y) and x == y


def _same_layout(a: h5py.Dataset, b: h5py.Dataset) -> bool:
    """Fill value and maximum shape, which the copy promises to preserve."""
    if a.maxshape != b.maxshape:
        return False
    fa, fb = a.fillvalue, b.fillvalue
    if a.dtype.hasobject:
        return _same_value(fa, fb) or (fa in (None, b"", "") and fb in (None, b"", ""))
    return np.asarray(fa, dtype=a.dtype).tobytes() == np.asarray(fb, dtype=b.dtype).tobytes()


def _same_data(a: h5py.Dataset, b: h5py.Dataset, rows: int) -> bool:
    if a.shape != b.shape or a.dtype != b.dtype:
        return False
    if a.dtype.hasobject:  # variable-length members: compare values, not object pointers
        if a.shape == ():
            return _same_value(a[()], b[()])
        for i in range(0, a.shape[0], max(1, rows)):
            x, y = a[i : i + rows], b[i : i + rows]
            if not all(_same_value(u, v) for u, v in zip(np.ravel(x).tolist(), np.ravel(y).tolist())):
                return False
        return True
    if a.shape == () or a.size == 0:
        return np.array_equal(np.asarray(a[()]).tobytes(), np.asarray(b[()]).tobytes())
    for i in range(0, a.shape[0], rows):
        x, y = a[i : i + rows], b[i : i + rows]
        if np.ascontiguousarray(x).tobytes() != np.ascontiguousarray(y).tobytes():
            return False
    return True


def verify(source: Path, output: Path, dropped_paths: Sequence[str]) -> dict:
    """Check every non-dropped source object exists in ``output`` with equal attributes and bytes.

    Also checks that dropped datasets are absent and that ``output`` has no extra objects.
    Read-only. Returns ``{objects_checked, problems (first 50), problem_count}``.
    """
    dropped = set(dropped_paths)
    checked, problems = 0, []
    with h5py.File(source, "r") as s, h5py.File(output, "r") as o:
        if not _same_attrs(s, o):
            problems.append("/: attributes differ")

        def visit(name, obj):
            nonlocal checked
            path = "/" + name
            if path in dropped:
                if path in o:
                    problems.append(f"{path}: dropped dataset present")
                return
            if path not in o:
                problems.append(f"{path}: missing")
                return
            other = o[path]
            if isinstance(obj, h5py.Group) != isinstance(other, h5py.Group):
                problems.append(f"{path}: object type differs")
            elif not _same_attrs(obj, other):
                problems.append(f"{path}: attributes differ")
            elif isinstance(obj, h5py.Dataset):
                row_bytes = obj.dtype.itemsize * int(np.prod(obj.shape[1:], dtype=np.int64))
                if not _same_layout(obj, other):
                    problems.append(f"{path}: fill value or maximum shape differs")
                elif not _same_data(obj, other, max(1, (64 << 20) // max(1, row_bytes))):
                    problems.append(f"{path}: data differ")
            checked += 1

        s.visititems(visit)
        extra: list[str] = []
        o.visit(lambda n: extra.append(n) if ("/" + n) not in s else None)
        problems += [f"/{n}: not in source" for n in extra]
    return {"objects_checked": checked, "problems": problems[:50], "problem_count": len(problems)}


def slim(
    source: Path,
    output: Path,
    policy: HdfSlimPolicy | None = None,
    *,
    workers: int | None = None,
    hash_source: bool = True,
) -> dict:
    """Write a verified slim copy of ``source`` to ``output``; return the manifest dict.

    Writes ``<output>.partial`` beside ``output`` and renames it only after verification.
    Raises ``HdfSlimError`` on failure; neither ``output`` nor the partial file remains.
    ``hash_source=False`` leaves ``source.sha256`` as None and records
    ``source.sha256_verified: false`` for callers that hash the source themselves.
    """
    policy = policy or HdfSlimPolicy.preset()
    policy.validate()
    source, output = Path(source), Path(output)
    if not source.is_file():
        raise HdfSlimError("HDF_SLIM_INPUT_INVALID", f"source not found: {source.name}")
    if output.exists():
        raise HdfSlimError("HDF_SLIM_OUTPUT_EXISTS", f"output exists: {output.name}")
    tmp = output.with_name(output.name + ".partial")
    if tmp.exists():
        raise HdfSlimError("HDF_SLIM_OUTPUT_EXISTS", f"stale partial output: {tmp.name}")
    if not output.parent.is_dir():
        raise HdfSlimError("HDF_SLIM_INPUT_INVALID", f"output folder not found: {output.parent.name}")
    if workers is not None and (type(workers) is not int or workers < 1):
        raise HdfSlimError("HDF_SLIM_INPUT_INVALID", "workers must be a positive integer")
    workers = workers or default_workers()
    started, clock = _stamp(), time.monotonic()
    rec = SlimRecord()
    try:
        with _open_source(source) as src:
            meshes = _require_series(src, policy)
            kept_raw = _retained_raw_bytes(src, policy, meshes)
            copied = _copied_stored_bytes(src, policy)
            applied_fallbacks = _fallbacks_applied(src, policy, meshes)
            free = shutil.disk_usage(output.parent).free
            if free < kept_raw + copied + SPACE_RESERVE_BYTES:
                raise HdfSlimError(
                    "HDF_SLIM_INSUFFICIENT_SPACE",
                    f"{free} bytes free < {kept_raw} raw kept + {copied} copied bytes + 1 GiB",
                )
            with concurrent.futures.ThreadPoolExecutor(workers) as pool, h5py.File(
                tmp, "w", libver="earliest"
            ) as dst:
                _copy_tree(src, dst, policy, pool, rec)
        write_s = time.monotonic() - clock
        result = verify(source, tmp, [d["path"] for d in rec.dropped])
        verify_s = time.monotonic() - clock - write_s
        if result["problem_count"]:
            raise HdfSlimError("HDF_SLIM_VERIFY_FAILED", "; ".join(result["problems"][:5]))
        source_sha = sha256_file(source) if hash_source else None
        os.replace(tmp, output)
        source_bytes, output_bytes = source.stat().st_size, output.stat().st_size
        output_sha = sha256_file(output)
    except HdfSlimError:
        tmp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise HdfSlimError("HDF_SLIM_IO_ERROR", str(exc)) from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return {
        "schema": SCHEMA,
        "status": "completed",
        "reason_code": "HDF_SLIM_VERIFIED",
        "hydraulic_approval": "not_approved",
        "started_at": started,
        "finished_at": _stamp(),
        "write_seconds": round(write_s, 1),
        "verify_seconds": round(verify_s, 1),
        # sha256_verified: this call hashed the source itself; false when the caller did.
        "source": {
            "name": source.name,
            "bytes": source_bytes,
            "sha256": source_sha,
            "sha256_verified": bool(hash_source),
        },
        "output": {"name": output.name, "bytes": output_bytes, "sha256": output_sha},
        "size_ratio": round(output_bytes / source_bytes, 4),
        "policy": policy.to_dict(),
        "meshes": meshes,
        "fallbacks_applied": applied_fallbacks,
        "dropped": rec.dropped,
        "rechunked": rec.rechunked,
        "copied_datasets": rec.copied,
        "verification": dict(method=VERIFICATION_METHOD, **result),
        "software": {
            "python": platform.python_version(),
            "h5py": h5py.__version__,
            "hdf5": h5py.version.hdf5_version,
            "numpy": np.__version__,
            "implementation_sha256": implementation_sha256(),
        },
        "workers": workers,
    }


def failure_manifest(reason_code: str, message: str, source: Path, output: Path | None) -> dict:
    """Manifest recorded when a slim did not complete (file names only, no paths)."""
    return {
        "schema": SCHEMA,
        "status": "failed",
        "reason_code": reason_code,
        "message": message,
        "hydraulic_approval": "not_approved",
        "source": {"name": Path(source).name},
        "output": {"name": Path(output).name} if output is not None else None,
        "finished_at": _stamp(),
    }


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Indented, key-sorted UTF-8 JSON without NaN, LF line endings."""
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")


def manifest_aliases(manifest: Path, protected: Sequence[Path]) -> bool:
    """True when ``manifest`` is, or hard-links to, one of the ``protected`` paths."""
    for path in protected:
        if manifest.resolve() == path.resolve():
            return True
        if manifest.exists() and path.exists() and manifest.samefile(path):  # hard links
            return True
    return False


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Losslessly repack a HEC-RAS 2D result HDF, keeping selected time series."
    )
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path, nargs="?", help="slim HDF to write (omit with --dry-run)")
    p.add_argument("--manifest", type=Path, help="manifest JSON (required unless --dry-run)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--preset", default=None, help=f"named policy (default {DEFAULT_PRESET})")
    group.add_argument("--policy-json", type=Path, help="policy object as written in a manifest")
    p.add_argument("--extra-series", action="append", default=[],
                   help="additional required per-mesh series (repeatable)")
    p.add_argument("--time-chunk-steps", type=int)
    p.add_argument("--space-chunk-size", type=int)
    p.add_argument("--deflate-level", type=int)
    p.add_argument("--workers", type=int, default=None, help="default: available CPUs, max 8")
    p.add_argument("--no-source-hash", action="store_true", help="caller already hashed source")
    p.add_argument("--dry-run", action="store_true", help="report the plan; write no HDF")
    return p


def _cli_policy(a: argparse.Namespace) -> HdfSlimPolicy:
    overrides: dict[str, Any] = {}
    for key in ("time_chunk_steps", "space_chunk_size", "deflate_level"):
        if getattr(a, key) is not None:
            overrides[key] = getattr(a, key)
    if a.policy_json is not None:
        try:
            data = json.loads(a.policy_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", f"policy JSON unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "policy must be an object")
        if a.extra_series or overrides:
            raise HdfSlimError("HDF_SLIM_INVALID_POLICY", "--policy-json cannot be combined with policy options")
        return HdfSlimPolicy.from_dict(data)
    if a.extra_series:
        overrides["extra_series"] = tuple(a.extra_series)
    return HdfSlimPolicy.preset(a.preset or DEFAULT_PRESET, **overrides)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the exit code (0 completed, 1 failed, 2 bad input)."""
    a = _parser().parse_args(argv)
    if not a.dry_run and (a.output is None or a.manifest is None):
        print("error: HDF_SLIM_INPUT_INVALID: OUTPUT and --manifest are required", file=sys.stderr)
        return 2
    if a.manifest is not None:
        protected = [a.source]
        if a.output is not None:
            protected += [a.output, a.output.with_name(a.output.name + ".partial")]
        if manifest_aliases(a.manifest, protected):
            # A diagnostic manifest written here would destroy the protected file.
            print("error: HDF_SLIM_INPUT_INVALID: manifest aliases a protected HDF path", file=sys.stderr)
            return 2
    failure = None
    try:
        policy = _cli_policy(a)
        if a.dry_run:
            manifest = plan(a.source, policy)
        else:
            manifest = slim(a.source, a.output, policy, workers=a.workers,
                            hash_source=not a.no_source_hash)
        code = 0
    except HdfSlimError as exc:
        failure = (exc.reason_code, str(exc))
        code = 2 if exc.reason_code in BAD_REQUEST_CODES else 1
    except Exception as exc:  # noqa: BLE001 - unexpected errors still leave a manifest
        failure = ("HDF_SLIM_UNEXPECTED_ERROR", f"{type(exc).__name__}: {exc}")
        code = 1
    if failure:
        manifest = failure_manifest(failure[0], failure[1], a.source, a.output)
        print(f"error: {failure[0]}: {failure[1]}", file=sys.stderr)
    if a.manifest is not None:
        try:
            write_manifest(a.manifest, manifest)
        except OSError as exc:
            print(f"error: HDF_SLIM_IO_ERROR: manifest not written: {exc}", file=sys.stderr)
            return 1
    if a.dry_run and not failure and a.manifest is None:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(json.dumps({k: manifest.get(k) for k in ("status", "reason_code", "size_ratio")}))
    return code


if __name__ == "__main__":
    sys.exit(main())
