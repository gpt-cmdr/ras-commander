"""Shared read-only HDF opens with optional chunk-cache tuning and handle reuse.

Fresh opens use stock h5py cache settings. Opt-in reuse automatically selects
64 MiB / 10007 prime slots / w0=0.75. Explicit cache configuration also enables
tuning without reuse; MB=0/off restores stock settings. HDF5 allocates raw chunk
caches per open dataset: six live datasets can retain roughly 384 MiB. Reuse is
off by default. w0=1 prioritizes eviction of fully consumed chunks for data read
once; the lower 0.75 default suits rereads as well as partial reads.

Environment (read on access; configure_hdf_reads overrides it):
RAS_COMMANDER_HDF_CHUNK_CACHE_MB, _SLOTS, _W0; RAS_COMMANDER_HDF_HANDLE_CACHE;
RAS_COMMANDER_HDF_HANDLE_CACHE_SIZE. Invalid env values warn once per value and
fall back to the applicable default. Programmatic invalid values raise ValueError.

Do not hold reused handles or active read contexts across external writes,
replacement, deletion or compute calls. Close cached handles before any writer,
including write APIs outside RasCmdr. RasCmdr suspends reuse for the whole compute
call and closes caches again immediately before launching. Active readers close
on release; callers must finish them before execution. Dataset/group objects
must not escape their open_hdf_read context: eviction can invalidate them.

Stat invalidation occurs on the next open and cannot detect same-size edits with
preserved mtime or delayed NTFS timestamps. Concurrent external writers are not
supported. Do not inherit HDF handles across fork: close before forking and use
fresh process-local opens (or spawn workers). Existing plain h5py handles to the
same file can cause HDF5 to reuse their cache policy; close them before changing
settings. Cached entries may be evicted while active, but close only on release.
"""

from __future__ import annotations

import atexit
import os
import math
import sys
from contextlib import contextmanager
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

import h5py

from .LoggingConfig import get_logger

logger = get_logger(__name__)

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
DEFAULT_CHUNK_CACHE_W0 = 0.75
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


_warned_env = set()
_suspend_count = 0


def _bad_env(name, raw):
    key = (name, raw)
    if key not in _warned_env:
        _warned_env.add(key)
        logger.warning("Invalid %s=%r; using the default HDF read policy", name, raw)


def _resolved(key, name, convert, valid):
    value = _overrides[key]
    if value is not None:
        return value
    raw = _env(name)
    if raw is None:
        return None
    try:
        value = convert(raw)
        if not valid(value):
            raise ValueError("out of range")
        return value
    except (ValueError, TypeError, OverflowError):
        _bad_env(name, raw)
        return None


def _chunk_cache_kwargs() -> Dict[str, Any]:
    """Empty kwargs preserve stock cache policy for fresh opens."""
    nbytes = _resolved("chunk_cache_bytes", _ENV_CACHE_MB,
                       lambda raw: 0 if raw in _OFF else float(raw) * 1024 * 1024,
                       lambda v: math.isfinite(v) and 0 <= v <= sys.maxsize)
    nslots = _resolved("chunk_cache_slots", _ENV_CACHE_SLOTS, int,
                       lambda v: 1 <= v <= 2**31 - 1)
    w0 = _resolved("chunk_cache_w0", _ENV_CACHE_W0, float,
                   lambda v: math.isfinite(v) and 0 <= v <= 1)
    if nbytes == 0:
        return {}
    if nbytes is None and nslots is None and w0 is None and not _handle_cache_enabled():
        return {}
    return {"rdcc_nbytes": DEFAULT_CHUNK_CACHE_BYTES if nbytes is None else int(nbytes),
            "rdcc_nslots": DEFAULT_CHUNK_CACHE_SLOTS if nslots is None else nslots,
            "rdcc_w0": DEFAULT_CHUNK_CACHE_W0 if w0 is None else w0}


def _handle_cache_enabled() -> bool:
    enabled = _overrides["handle_cache"]
    if enabled is None:
        raw = _env(_ENV_HANDLE_CACHE)
        if raw is not None and raw not in _ON | _OFF:
            _bad_env(_ENV_HANDLE_CACHE, raw)
        enabled = raw in _ON
    return bool(enabled) and _suspend_count == 0


def _handle_cache_size() -> int:
    size = _resolved("handle_cache_size", _ENV_HANDLE_CACHE_SIZE, int,
                     lambda v: 1 <= v <= 2**31 - 1)
    return DEFAULT_HANDLE_CACHE_SIZE if size is None else size


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
                if value < 0 or value > sys.maxsize or (key in ("chunk_cache_slots", "handle_cache_size") and not 1 <= value <= 2**31 - 1):
                    raise ValueError(f"{key} must be a positive integer")
        _overrides[key] = value
    if not _handle_cache_enabled():
        close_hdf_handles()
    with _lock:
        _trim_cache()
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
    """Open ``path`` read-only with the resolved cache policy. The caller owns and closes it.

    Never returns a cached handle. Raises exactly what ``h5py.File(path, "r")`` raises.
    """
    _handle_cache_size()  # validate dormant env policy too
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
    _trim_cache()


def _trim_cache():
    """Bound cached entries even while old readers remain active."""
    while len(_handles) > _handle_cache_size():
        key = next((key for key, value in _handles.items() if not value.users), next(iter(_handles)))
        entry = _handles.pop(key)
        if entry.users:
            entry.doomed = True
        else:
            _close_entry(entry)


@contextmanager
def suspend_hdf_reuse():
    """Suspend reuse process-wide for a complete compute call, including workers."""
    global _suspend_count
    with _lock:
        _suspend_count += 1
        close_hdf_handles()
    try:
        yield
    finally:
        with _lock:
            close_hdf_handles()
            _suspend_count -= 1


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
        _trim_cache()
        return len(_handles)


atexit.register(close_hdf_handles)


class open_hdf_read:
    """Context manager: ``with open_hdf_read(path) as hdf:`` replaces ``with h5py.File(path, "r")``.

    Applies the resolved stock or explicit chunk-cache policy. With handle reuse enabled, returns a cached
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
        key = (absolute, stat.st_size, stat.st_mtime_ns, spelling, tuple(sorted(_chunk_cache_kwargs().items())))
        with _lock:
            if not _handle_cache_enabled():
                return None
            _trim_cache()
            entry = _handles.get(key)
            if entry is not None and entry.file.id.valid:
                _handles.move_to_end(key)
                entry.users += 1
                return entry
            # Drop stale or dead handles for this file before opening it again.
            for old_key in list(_handles):
                if old_key[0] == absolute and (old_key[1:3] != key[1:3] or old_key[4:] != key[4:] or old_key == key):
                    old = _handles.pop(old_key)
                    if old.users:
                        old.doomed = True
                    else:
                        _close_entry(old)
            entry = _Entry(h5py_file_read(spelling))
            entry.users = 1
            _handles[key] = entry
            _trim_cache()
            return entry
