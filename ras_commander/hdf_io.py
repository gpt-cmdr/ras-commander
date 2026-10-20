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

The chunk cache only lives as long as the dataset and file handle, so a fresh
open per call gains little across calls. Optional handle reuse keeps a small
LRU of read-only handles keyed by (absolute path, size, mtime_ns, spelling).

Handle reuse is OFF by default. A cached read-only handle (verified on
Windows, h5py 3.14 / HDF5 1.14.6):

* makes any in-process ``h5py.File(path, "r+")`` or ``"a"`` fail with
  ``OSError: file is already open for read-only``; and
* blocks ``os.replace`` onto and ``os.remove`` of the file (WinError 5 / 32),
  so HEC-RAS or RasProcess cannot rewrite the plan HDF.

Enable it with ``RAS_COMMANDER_HDF_HANDLE_CACHE=1`` or
``configure_hdf_reads(handle_cache=True)``, and call :func:`close_hdf_handles`
before writing or replacing an HDF from the same process. ``RasCmdr``
execution entry points call it automatically before a plan runs.

Environment variables (read on every open, so they can be toggled at run time):

* ``RAS_COMMANDER_HDF_CHUNK_CACHE_MB``: chunk cache size in MiB (default 64).
  ``0`` or ``off`` restores the plain h5py defaults (no cache arguments).
* ``RAS_COMMANDER_HDF_CHUNK_CACHE_SLOTS``: slot count (default 10007).
* ``RAS_COMMANDER_HDF_CHUNK_CACHE_W0``: preemption policy 0..1 (default 1.0).
* ``RAS_COMMANDER_HDF_HANDLE_CACHE``: ``1``/``on`` enables handle reuse.
* ``RAS_COMMANDER_HDF_HANDLE_CACHE_SIZE``: maximum cached handles (default 4).

Values passed to :func:`configure_hdf_reads` take precedence over the
environment.
"""

from __future__ import annotations

import atexit
import os
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

import h5py

__all__ = [
    "DEFAULT_CHUNK_CACHE_BYTES",
    "DEFAULT_CHUNK_CACHE_SLOTS",
    "DEFAULT_CHUNK_CACHE_W0",
    "DEFAULT_HANDLE_CACHE_SIZE",
    "open_hdf_read",
    "h5py_file_read",
    "close_hdf_handles",
    "configure_hdf_reads",
    "hdf_read_settings",
    "cached_hdf_handle_count",
]

DEFAULT_CHUNK_CACHE_BYTES = 64 * 1024 * 1024
DEFAULT_CHUNK_CACHE_SLOTS = 10007
DEFAULT_CHUNK_CACHE_W0 = 1.0
DEFAULT_HANDLE_CACHE_SIZE = 4

_ENV_CACHE_MB = "RAS_COMMANDER_HDF_CHUNK_CACHE_MB"
_ENV_CACHE_SLOTS = "RAS_COMMANDER_HDF_CHUNK_CACHE_SLOTS"
_ENV_CACHE_W0 = "RAS_COMMANDER_HDF_CHUNK_CACHE_W0"
_ENV_HANDLE_CACHE = "RAS_COMMANDER_HDF_HANDLE_CACHE"
_ENV_HANDLE_CACHE_SIZE = "RAS_COMMANDER_HDF_HANDLE_CACHE_SIZE"

_OFF = {"0", "off", "false", "no", "none", "default"}
_ON = {"1", "on", "true", "yes"}

# Programmatic overrides; None means "use environment, then default".
_overrides: Dict[str, Any] = {
    "chunk_cache_bytes": None,
    "chunk_cache_slots": None,
    "chunk_cache_w0": None,
    "handle_cache": None,
    "handle_cache_size": None,
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


def _handle_cache_enabled() -> bool:
    enabled = _overrides["handle_cache"]
    if enabled is not None:
        return bool(enabled)
    return _env(_ENV_HANDLE_CACHE) in _ON


def _handle_cache_size() -> int:
    size = _overrides["handle_cache_size"]
    if size is None:
        raw = _env(_ENV_HANDLE_CACHE_SIZE)
        size = DEFAULT_HANDLE_CACHE_SIZE if raw is None else int(raw)
    return max(1, int(size))


def configure_hdf_reads(
    chunk_cache_bytes: Any = _UNSET,
    chunk_cache_slots: Any = _UNSET,
    chunk_cache_w0: Any = _UNSET,
    handle_cache: Any = _UNSET,
    handle_cache_size: Any = _UNSET,
) -> Dict[str, Any]:
    """Set process-wide read settings. Pass ``None`` to return a value to env/default.

    ``chunk_cache_bytes=0`` restores the plain h5py chunk cache defaults.
    Disabling ``handle_cache`` closes any cached handles. Returns the resolved
    settings (see :func:`hdf_read_settings`).
    """
    updates = {
        "chunk_cache_bytes": chunk_cache_bytes,
        "chunk_cache_slots": chunk_cache_slots,
        "chunk_cache_w0": chunk_cache_w0,
        "handle_cache": handle_cache,
        "handle_cache_size": handle_cache_size,
    }
    for key, value in updates.items():
        if value is _UNSET:
            continue
        if value is not None:
            if key == "handle_cache":
                value = bool(value)
            elif key == "chunk_cache_w0":
                value = float(value)
                if not 0.0 <= value <= 1.0:
                    raise ValueError("chunk_cache_w0 must be between 0 and 1")
            else:
                value = int(value)
                if value < 0 or (key in ("chunk_cache_slots", "handle_cache_size") and value < 1):
                    raise ValueError(f"{key} must be a positive integer")
        _overrides[key] = value
    if not _handle_cache_enabled():
        close_hdf_handles()
    return hdf_read_settings()


def hdf_read_settings() -> Dict[str, Any]:
    """Return the currently resolved chunk-cache and handle-reuse settings."""
    kwargs = _chunk_cache_kwargs()
    return {
        "chunk_cache_bytes": kwargs.get("rdcc_nbytes"),
        "chunk_cache_slots": kwargs.get("rdcc_nslots"),
        "chunk_cache_w0": kwargs.get("rdcc_w0"),
        "handle_cache": _handle_cache_enabled(),
        "handle_cache_size": _handle_cache_size(),
    }


def h5py_file_read(path: Any) -> h5py.File:
    """Open ``path`` read-only with the sized chunk cache. The caller owns and closes it.

    Never returns a cached handle. Raises exactly what ``h5py.File(path, "r")`` raises.
    """
    return h5py.File(path, "r", **_chunk_cache_kwargs())


class _Entry:
    __slots__ = ("file", "users", "doomed")

    def __init__(self, file: h5py.File):
        self.file = file
        self.users = 0
        self.doomed = False


_lock = threading.RLock()
_handles: "OrderedDict[tuple, _Entry]" = OrderedDict()


def _abs_key(path: Any) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _close_entry(entry: _Entry) -> None:
    try:
        if entry.file.id.valid:
            entry.file.close()
    except Exception:  # pragma: no cover - closing a dead handle
        pass


def _release(entry: _Entry) -> None:
    """Drop one user of ``entry``; must be called with ``_lock`` held."""
    entry.users -= 1
    if entry.users <= 0:
        entry.users = 0
        if entry.doomed:
            _close_entry(entry)


def close_hdf_handles(path: Any = None) -> int:
    """Close cached read-only handles (all, or those for ``path``).

    Call before writing, replacing, or deleting an HDF from this process, or
    before HEC-RAS rewrites it. Handles currently in use by another thread are
    removed from the cache and closed as soon as that read finishes. Returns
    the number of cache entries removed. Caller-owned handles are not touched.
    """
    target = None if path is None else _abs_key(path)
    removed = 0
    with _lock:
        for key in list(_handles):
            if target is not None and key[0] != target:
                continue
            entry = _handles.pop(key)
            removed += 1
            if entry.users:
                entry.doomed = True
            else:
                _close_entry(entry)
    return removed


def cached_hdf_handle_count() -> int:
    """Number of read-only handles currently held by the reuse cache."""
    with _lock:
        return len(_handles)


atexit.register(close_hdf_handles)


class open_hdf_read:
    """Context manager: ``with open_hdf_read(path) as hdf:`` replaces ``with h5py.File(path, "r")``.

    Applies the sized chunk cache. With handle reuse enabled, returns a cached
    handle (re-opened when the file's size or mtime changes) and leaves it open
    on exit; otherwise opens a fresh handle and closes it on exit. Raises
    exactly what ``h5py.File(path, "r")`` raises.
    """

    __slots__ = ("_path", "_file", "_entry")

    def __init__(self, path: Any):
        self._path = path
        self._file = None
        self._entry = None

    def __enter__(self) -> h5py.File:
        path = self._path
        if _handle_cache_enabled() and isinstance(path, (str, os.PathLike)):
            entry = self._acquire_cached(path)
            if entry is not None:
                self._entry = entry
                return entry.file
        self._file = h5py_file_read(path)
        return self._file

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._entry is not None:
            entry, self._entry = self._entry, None
            with _lock:
                _release(entry)
                if not entry.file.id.valid:
                    # The caller closed the shared handle; forget it.
                    for key, value in list(_handles.items()):
                        if value is entry:
                            _handles.pop(key)
        elif self._file is not None:
            file, self._file = self._file, None
            file.close()
        return False

    @staticmethod
    def _acquire_cached(path: Any) -> Optional[_Entry]:
        spelling = os.fspath(path)
        if isinstance(spelling, bytes):
            return None
        absolute = _abs_key(spelling)
        try:
            stat = os.stat(spelling)
        except OSError:
            close_hdf_handles(spelling)
            return None  # let h5py raise its native error
        key = (absolute, stat.st_size, stat.st_mtime_ns, spelling)
        with _lock:
            entry = _handles.get(key)
            if entry is not None and entry.file.id.valid:
                _handles.move_to_end(key)
                entry.users += 1
                return entry
            # Drop stale or dead handles for this file before opening it again.
            for old_key in list(_handles):
                if old_key[0] == absolute and (old_key[1:3] != key[1:3] or old_key == key):
                    old = _handles.pop(old_key)
                    if old.users:
                        old.doomed = True
                    else:
                        _close_entry(old)
            entry = _Entry(h5py_file_read(spelling))
            entry.users = 1
            _handles[key] = entry
            limit = _handle_cache_size()
            if len(_handles) > limit:
                for old_key in list(_handles):
                    if len(_handles) <= limit:
                        break
                    old = _handles[old_key]
                    if old is entry or old.users:
                        continue
                    _handles.pop(old_key)
                    _close_entry(old)
            return entry
