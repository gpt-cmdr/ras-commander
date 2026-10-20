"""Shared read-only HDF5 open helper for HEC-RAS plan and geometry HDF files.

Every read-only ``h5py.File(path, "r")`` in the HDF readers goes through
:func:`open_hdf_read` (context manager) or :func:`h5py_file_read` (caller-owned
handle). Both apply a sized HDF5 raw-data chunk cache. Write paths do not use
this module.

Why a sized chunk cache
-----------------------
HEC-RAS stores large 2D time series as one chunk per timestep holding every
cell or face (for example 1 x 352,141 float32 = 1.4 MB on JUL2020, 1 x
1,393,564 float32 = 5.6 MB of face velocity on a 586,935-cell eBFE model).
The HDF5 default cache is 1 MiB / 521 slots, which cannot hold a single such
chunk, so every partial read re-inflates every chunk it touches. The default
here is 64 MiB / 10,007 slots / ``w0=1.0``:

* 64 MiB holds at least 11 of the largest chunks seen on the five qualification
  fixtures and the 24-timestep working sets used by FIM queries. On a reused
  handle it measured 1733 -> 211 ms (JUL2020) and 432 -> 63 ms (BaldEagle p07)
  for 10 x 500 random cells x 24 steps. Holding a whole 193 x 1.4 MB dataset
  needs ~512 MiB, which is too much as a per-dataset default (the cache is
  allocated per open dataset), so that size stays opt-in.
* 10,007 is a prime well above the chunk count of any time-series dataset seen
  (865 timesteps on BaldEagle), so chunk-index hashing does not collide.
  Slots cost 8 bytes each per open dataset.
* ``w0=1.0`` is the HDF5-documented setting for read-only access: fully read
  chunks are evicted first, which keeps partially read (re-usable) chunks.

The chunk cache lives as long as the dataset handle, so it pays off within
one call (and for repeated reads of the same dataset inside that call).

Environment variables (read on every open, so they can be toggled at run time):

* ``RAS_COMMANDER_HDF_CHUNK_CACHE_MB``: chunk cache size in MiB (default 64).
  ``0`` or ``off`` restores the plain h5py defaults (no cache arguments).
* ``RAS_COMMANDER_HDF_CHUNK_CACHE_SLOTS``: slot count (default 10007).
* ``RAS_COMMANDER_HDF_CHUNK_CACHE_W0``: preemption policy 0..1 (default 1.0).

Values passed to :func:`configure_hdf_reads` take precedence over the
environment.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import h5py

__all__ = [
    "DEFAULT_CHUNK_CACHE_BYTES",
    "DEFAULT_CHUNK_CACHE_SLOTS",
    "DEFAULT_CHUNK_CACHE_W0",
    "open_hdf_read",
    "h5py_file_read",
    "configure_hdf_reads",
    "hdf_read_settings",
]

DEFAULT_CHUNK_CACHE_BYTES = 64 * 1024 * 1024
DEFAULT_CHUNK_CACHE_SLOTS = 10007
DEFAULT_CHUNK_CACHE_W0 = 1.0

_ENV_CACHE_MB = "RAS_COMMANDER_HDF_CHUNK_CACHE_MB"
_ENV_CACHE_SLOTS = "RAS_COMMANDER_HDF_CHUNK_CACHE_SLOTS"
_ENV_CACHE_W0 = "RAS_COMMANDER_HDF_CHUNK_CACHE_W0"

_OFF = {"0", "off", "false", "no", "none", "default"}

# Programmatic overrides; None means "use environment, then default".
_overrides: Dict[str, Any] = {
    "chunk_cache_bytes": None,
    "chunk_cache_slots": None,
    "chunk_cache_w0": None,
}

_UNSET = object()


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip().lower()
    return value or None


def _chunk_cache_kwargs() -> Dict[str, Any]:
    """Resolve rdcc_* keyword arguments for ``h5py.File``; empty means h5py defaults."""
    nbytes = _overrides["chunk_cache_bytes"]
    if nbytes is None:
        raw = _env(_ENV_CACHE_MB)
        if raw is None:
            nbytes = DEFAULT_CHUNK_CACHE_BYTES
        elif raw in _OFF:
            nbytes = 0
        else:
            nbytes = int(float(raw) * 1024 * 1024)
    if nbytes <= 0:
        return {}
    nslots = _overrides["chunk_cache_slots"]
    if nslots is None:
        raw = _env(_ENV_CACHE_SLOTS)
        nslots = DEFAULT_CHUNK_CACHE_SLOTS if raw is None else int(raw)
    w0 = _overrides["chunk_cache_w0"]
    if w0 is None:
        raw = _env(_ENV_CACHE_W0)
        w0 = DEFAULT_CHUNK_CACHE_W0 if raw is None else float(raw)
    return {"rdcc_nbytes": int(nbytes), "rdcc_nslots": int(nslots), "rdcc_w0": float(w0)}


def configure_hdf_reads(
    chunk_cache_bytes: Any = _UNSET,
    chunk_cache_slots: Any = _UNSET,
    chunk_cache_w0: Any = _UNSET,
) -> Dict[str, Any]:
    """Set process-wide read settings. Pass ``None`` to return a value to env/default.

    ``chunk_cache_bytes=0`` restores the plain h5py chunk cache defaults.
    Returns the resolved
    settings (see :func:`hdf_read_settings`).
    """
    updates = {
        "chunk_cache_bytes": chunk_cache_bytes,
        "chunk_cache_slots": chunk_cache_slots,
        "chunk_cache_w0": chunk_cache_w0,
    }
    for key, value in updates.items():
        if value is _UNSET:
            continue
        if value is not None:
            if key == "chunk_cache_w0":
                value = float(value)
                if not 0.0 <= value <= 1.0:
                    raise ValueError("chunk_cache_w0 must be between 0 and 1")
            else:
                value = int(value)
                if value < 0 or (key == "chunk_cache_slots" and value < 1):
                    raise ValueError(f"{key} must be a positive integer")
        _overrides[key] = value
    return hdf_read_settings()


def hdf_read_settings() -> Dict[str, Any]:
    """Return the currently resolved chunk-cache settings."""
    kwargs = _chunk_cache_kwargs()
    return {
        "chunk_cache_bytes": kwargs.get("rdcc_nbytes"),
        "chunk_cache_slots": kwargs.get("rdcc_nslots"),
        "chunk_cache_w0": kwargs.get("rdcc_w0"),
    }


def h5py_file_read(path: Any) -> h5py.File:
    """Open ``path`` read-only with the sized chunk cache. The caller owns and closes it.

    Raises exactly what ``h5py.File(path, "r")`` raises.
    """
    return h5py.File(path, "r", **_chunk_cache_kwargs())


class open_hdf_read:
    """Context manager: ``with open_hdf_read(path) as hdf:`` replaces ``with h5py.File(path, "r")``.

    Opens a fresh read-only handle with the sized chunk cache and closes it on
    exit. Raises exactly what ``h5py.File(path, "r")`` raises.
    """

    __slots__ = ("_path", "_file")

    def __init__(self, path: Any):
        self._path = path
        self._file = None

    def __enter__(self) -> h5py.File:
        self._file = h5py_file_read(self._path)
        return self._file

    def __exit__(self, exc_type, exc, tb) -> bool:
        file, self._file = self._file, None
        if file is not None:
            file.close()
        return False
