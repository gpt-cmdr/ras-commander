"""Adapter for ras-commander's default HDF engine, the native (Rust) extension.

The ``ras-commander-fast-hdf`` extension is a core dependency on the platforms
with published wheels (CPython on Windows x64, Linux x64 and macOS arm64). This
module routes the ``Hdf*`` classes' value reads through it and provides native
mesh assembly and direct PMTiles export. h5py is the reference implementation
and the public contract: in the default ``auto`` mode any native failure
(Corrupt/checksum refusals included) falls back to the h5py read, so callers see
the h5py outcome. Metadata and unsupported HDF types use h5py. Where the
extension is not installed or has an incompatible ``API_VERSION``, every read
uses h5py.

``RAS_COMMANDER_FAST_HDF=h5py`` (legacy ``0``) turns the native engine off;
``native`` (legacy ``required``) raises :class:`FastHdfError` instead of falling
back, which proves native execution in qualification runs. Explicit
``backend='python'`` or ``'rust'`` overrides the environment.

Public surface: ``__all__`` lists the supported names (``available``,
``close_sessions``, ``FastHdfError``, ``FastHdfPanicError``, ``mesh_polygons``,
``packed_meshes`` and the ``export_*`` functions). Everything else here, in
particular ``read_typed``/``read_attrs``/``read_attr``/``read_dataset(s)``,
``mesh_series_domain``, ``trace_reads``, ``native_required``,
``reraise_required``, ``backend_scope`` and ``release_native_sessions`` (use
``close_sessions(path)``), is internal adapter plumbing for the ``Hdf*``
classes and the qualification suites; it may change without notice.

Environment: ``RAS_COMMANDER_FAST_HDF`` (backend policy; an unrecognised value
is ``auto`` with one logged warning) and ``RAS_COMMANDER_HDF_SESSION_CACHE``
(native session policy). See ``docs/api/hdf.md``, "Native Rust HDF engine", and
``docs/native-engine.md``.
"""

from __future__ import annotations

from contextlib import nullcontext, contextmanager
from collections import OrderedDict
from contextvars import ContextVar
from threading import RLock
import atexit
import math
import importlib
import inspect
import operator
import os
from pathlib import Path
import stat as stat_module
import tempfile
from typing import Mapping, Sequence

import h5py
import numpy as np

from . import _native_scope
from ._native_scope import one_read as _one_read
from .Decorators import log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)

__all__ = [
    "FastHdfError", "FastHdfPanicError", "available", "close_sessions",
    "packed_meshes", "mesh_polygons", "export_pmtiles", "export_mesh_pmtiles",
    "export_arrow", "export_arrow_pmtiles",
]


class FastHdfError(RuntimeError):
    """The explicitly requested native operation could not be completed."""


class FastHdfPanicError(FastHdfError):
    """A Rust panic inside the native extension: an engine bug, not bad input.

    The extension contains panics at every Python entry point and raises this
    class while ``ras_commander.fast_hdf`` is imported (the standalone module
    raises its own ``NativePanicError(RuntimeError)``). Unlike PyO3's
    ``PanicException`` it is an ``Exception``, so ``auto`` mode falls back to
    h5py and ``rust`` mode reports it as a :class:`FastHdfError`. A panic does
    not poison a cached session; later reads and ``close()`` keep working.
    """


_warned_modes = set()
# Explicit backend of the enclosing public call; see ``backend_scope``.
_BACKEND_SCOPE = ContextVar("ras_commander_fast_hdf_backend", default=None)


# Public vocabulary (``engine=`` and RAS_COMMANDER_FAST_HDF): auto | h5py | native.
# Internal policy names: auto | python | rust. Legacy spellings stay accepted.
_BACKEND_ALIASES = {"auto": "auto", "h5py": "python", "python": "python",
                    "native": "rust", "rust": "rust"}


def _normalize_backend(backend):
    """Internal policy name for a public ``engine``/``backend`` value."""
    try:
        return _BACKEND_ALIASES[backend]
    except (KeyError, TypeError):
        raise ValueError("engine must be 'auto', 'h5py', or 'native'") from None


@contextmanager
def backend_scope(backend):
    """Make nested default-``auto`` reads follow an explicit ``backend`` for one call.

    A public reader that takes ``backend`` applies it to its own algorithm, but
    its nested readers (``read_typed``, other public calls) default to ``auto``
    and would otherwise resolve ``RAS_COMMANDER_FAST_HDF``. Inside this scope
    an explicit ``"python"`` keeps every nested read on h5py and ``"rust"``
    requires native for every nested read; ``"auto"`` leaves the environment
    policy unchanged. The scope is per context (thread/task), not global.
    """
    backend = _normalize_backend(backend)
    if backend == "auto":
        yield
        return
    token = _BACKEND_SCOPE.set(backend)
    try:
        yield
    finally:
        _BACKEND_SCOPE.reset(token)



# Functions whose native read path has not yet been exercised by the release test
# corpus (no fixture carries their data). In auto mode they run entirely on h5py;
# an explicit ``native`` engine (or RAS_COMMANDER_FAST_HDF=native) still runs them
# natively. Remove the decorator once a fixture proves the function identical.
UNQUALIFIED_NATIVE = set()


def h5py_until_qualified(func):
    """Run ``func`` on h5py in auto mode until the test corpus qualifies its native path."""
    import functools
    UNQUALIFIED_NATIVE.add(f"{func.__module__}.{func.__qualname__}")

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if _mode("auto") == "auto":
            with backend_scope("h5py"):
                return func(*args, **kwargs)
        return func(*args, **kwargs)

    wrapper.__native_qualified__ = False
    return wrapper

def _mode(backend):
    """Resolve the backend policy: "python", "auto" or "rust" (required).

    An unrecognised ``RAS_COMMANDER_FAST_HDF`` value must never change what a
    read returns, so it is treated as ``auto`` after one logged warning per
    value. (Raising here would be swallowed by the readers' broad handlers and
    turn into empty results.) Only an invalid explicit ``backend`` argument,
    a programming error, raises.
    """
    backend = _normalize_backend(backend)
    if backend != "auto":
        return backend
    scoped = _BACKEND_SCOPE.get()
    if scoped is not None:
        return scoped
    value = os.environ.get("RAS_COMMANDER_FAST_HDF", "auto").strip().lower()
    if value in {"h5py", "0", "off", "false", "python"}:
        return "python"
    if value in {"native", "required", "rust"}:
        return "rust"
    if value not in {"", "auto", "1", "on", "true"} and value not in _warned_modes:
        _warned_modes.add(value)
        logger.warning(
            "Ignoring unrecognised RAS_COMMANDER_FAST_HDF=%r; using 'auto'. "
            "Valid values: auto (default), h5py, native "
            "(legacy aliases: 0/off/false/python, required/rust).", value)
    return "auto"


def _threads(threads):
    if threads is None:
        return None
    if isinstance(threads, bool):
        raise ValueError("threads must be a positive integer")
    value = operator.index(threads)
    if not 1 <= value <= 1024:
        raise ValueError("threads must be between 1 and 1024")
    return value


# Outcome of the extension import, cached for the process so a missing or
# incompatible extension costs nothing on the (often hot-loop) routed reads:
# (module or None, failure message, import exception).
_native_state = None


def _load_native():
    global _native_state
    if _native_state is None:
        try:
            module = importlib.import_module("ras_commander_fast_hdf")
        except (ImportError, OSError) as exc:
            _native_state = (None, "The ras-commander-fast-hdf extension is unavailable", exc)
        else:
            if getattr(module, "API_VERSION", None) != 11:
                logger.warning("Ignoring incompatible ras-commander-fast-hdf extension")
                _native_state = (None, "Incompatible ras-commander-fast-hdf API; version 11 is required", None)
            else:
                _native_state = (module, None, None)
    return _native_state


def _native(mode):
    if mode == "python":
        return None
    module, failure, exc = _load_native()
    if module is None and mode == "rust":
        raise FastHdfError(failure) from exc
    return module


def _reset_native():
    """Forget the cached import outcome (tests; or after installing the extension)."""
    global _native_state
    _native_state = None


@log_call
def available() -> bool:
    """Whether a compatible extension can be imported, independently of policy."""
    return _native("auto") is not None


# At most four open files. The lock also keeps eviction/close from racing a
# cached read; native sessions independently serialize close against reads.
# A session opened inside a public call is "scoped": it is shared by every read
# of that call and closed when the outermost public call returns (see
# ``_native_scope``), so no HDF stays open - and undeletable on Windows - after a
# public method has returned. A read outside any public call (direct use of this
# module, or a generator such as ``iter_mesh_timeseries`` resumed after its
# public call returned) uses its own session and closes it when the read ends.
# Only RAS_COMMANDER_HDF_SESSION_CACHE=persist keeps sessions cached until
# ``close_sessions()``.
_sessions = OrderedDict()
_sessions_lock = RLock()
_SESSION_LIMIT = 4
_scoped_keys = set()


def _release_scoped_sessions():
    """Close the sessions opened inside public calls (the typed-result cache stays)."""
    with _sessions_lock:
        for key in list(_scoped_keys):
            entry = _sessions.pop(key, None)
            if entry is not None:
                try:
                    entry[0].close()
                except Exception as exc:  # a failing close must not mask the call's outcome
                    logger.debug("Closing native session %s failed: %s", key[0], exc)
        _scoped_keys.clear()


@log_call
def close_sessions(path=None):
    """Release cached native file mappings before replacing HDFs or running RAS.

    Omit path to close all cached files. Explicit HdfSession objects are owned
    by their caller and must be closed separately.
    """
    resolved = None if path is None else _comparable(Path(path).resolve())
    # A file closed here may be replaced next (writers call this first): forget
    # the stats remembered for the current adapter read.
    _forget_stats()
    from . import _fast_hdf_typed
    _fast_hdf_typed.clear_cache(path)
    with _sessions_lock:
        for key in list(_sessions):
            if resolved is None or _comparable(key[0]) == resolved:
                session, _ = _sessions.pop(key)
                _scoped_keys.discard(key)
                session.close()


def release_native_sessions(*paths):
    """Close cached native sessions on ``paths`` before they are replaced, moved or renamed.

    A session opened inside a public call stays mapped until the outermost call
    returns, and Windows refuses to replace or rename a mapped file - or a folder
    that contains one. Writers call this immediately before ``os.replace``/
    ``shutil.move`` on both source and destination; code that renames, moves or
    removes a project folder passes the folder, which releases every session of a
    file inside it. Their typed-result cache entries are dropped too. Paths
    without a cached session (including non-HDF files) only clear that cache.
    Released files are reopened by the next read; values do not change.
    """
    for path in paths:
        if path is None:
            continue
        if Path(path).is_dir():
            _release_tree(path)
        else:
            close_sessions(path)


def _comparable(path):
    """``path`` (a resolved path string) without a Windows extended-length prefix,
    case-normalised, so ``\\\\?\\D:\\x`` and ``D:\\x`` compare equal."""
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(text)


def _release_tree(root):
    """Close the cached sessions and typed results of every file under ``root``."""
    prefix = _comparable(Path(root).resolve()).rstrip("\\/") + os.sep
    _forget_stats()
    from . import _fast_hdf_typed
    _fast_hdf_typed.clear_cache_under(root)
    with _sessions_lock:
        for key in list(_sessions):
            if _comparable(key[0]).startswith(prefix):
                session, _ = _sessions.pop(key)
                _scoped_keys.discard(key)
                session.close()


def _resolved(path):
    """``str(Path(path).resolve())``, remembered for the rest of the public call.

    Resolving a path on Windows opens the file to ask for its final name, and the
    typed readers resolve the same HDF path several times per read. How a path
    string resolves cannot change during one public call (a relative path is
    keyed with the working directory), so inside a call it is resolved once.
    File identity checks (size, mtime) are still made on every lookup.
    """
    raw = os.fspath(path)
    memo = _native_scope.memo()
    if memo is None:
        return str(Path(raw).resolve())
    key = ("resolve", raw) if os.path.isabs(raw) else ("resolve", os.getcwd(), raw)
    resolved = memo.get(key)
    if resolved is None:
        resolved = memo[key] = str(Path(raw).resolve())
    return resolved


def _stat(path):
    """``os.stat(path)``, remembered until the current adapter-level read returns.

    The size and modification time of an HDF are the identity of its cached
    session and typed results, and one read (``read_typed``, ``read_attrs``,
    ``typed_call``, ``read_dataset``, ...) looks them up several times. Within
    one such read only ras-commander's adapter and the engine run, so nothing
    can rewrite the file and it is stat-ed once. Between reads, even inside one
    public call, every lookup stats the file again: ras-commander's own
    workflows rewrite an HDF in the middle of a public call (in place with
    h5py, or through HEC-RAS / RAS Mapper in another process), and the next
    read must see the new file. Failures are not remembered, and
    :func:`close_sessions` / :func:`release_native_sessions` forget the stats.
    """
    raw = os.fspath(path)
    memo = _native_scope.read_stats()
    if memo is None:
        return os.stat(raw)
    key = (raw,) if os.path.isabs(raw) else (os.getcwd(), raw)
    result = memo.get(key)
    if result is None:
        result = memo[key] = os.stat(raw)
    return result


def _forget_stats():
    memo = _native_scope.read_stats()
    if memo:
        memo.clear()


def _is_file(path):
    """``Path(path).is_file()`` through :func:`_stat`."""
    try:
        return stat_module.S_ISREG(_stat(path).st_mode)
    except (OSError, ValueError):
        return False


def _session_cache_setting():
    return os.environ.get("RAS_COMMANDER_HDF_SESSION_CACHE", "1").strip().lower()


def _typed_source(module, path):
    """Context yielding what a path-based typed engine call should read from.

    Inside a public call (or with ``RAS_COMMANDER_HDF_SESSION_CACHE=persist``),
    an extension that advertises ``SESSION_SOURCES`` reads through the call's
    cached :class:`HdfSession`: the file is mapped once and the engine's
    session-local metadata proofs are shared by all reads of the call instead of
    being repeated by every small read. The values are the same either way.
    Otherwise (session cache off, no public call, older extension) the path
    itself is passed and the engine opens the file for that one call, as before.

    The cache lock is held only while the session is looked up or opened, not
    during the read, so typed reads of different files in different threads stay
    parallel. A session closed by another thread in between (eviction, or another
    public call returning) is detected by the caller (:func:`typed_call`), which
    then repeats the read by path.
    """
    if getattr(module, "SESSION_SOURCES", False) is not True:
        return path
    setting = _session_cache_setting()
    if setting in {"0", "false", "off"} or (setting != "persist" and not _native_scope.active()):
        return path
    with _session(module, path, None, any_threads=True) as session:
        return session


@_one_read
def typed_call(module, path, name, *args, **kwargs):
    """Call the path-based engine entry point ``name`` on ``path`` (see :func:`_typed_source`)."""
    source = _typed_source(module, path)
    function = getattr(module, name)
    if source is path:
        return function(path, *args, **kwargs)
    try:
        return function(source, *args, **kwargs)
    except ValueError:
        if not getattr(source, "closed", False):
            raise
        # Closed by another thread after the lookup: the same read by path.
        return function(path, *args, **kwargs)


@contextmanager
def _session(module, path, threads=None, *, any_threads=False):
    """Cached native session for ``path`` (see the module notes above).

    ``any_threads`` reuses a cached session of the same file whatever its thread
    count (typed reads do not depend on it) instead of reopening the file.
    """
    path = Path(_resolved(path))
    setting = _session_cache_setting()
    enabled = setting not in {"0", "false", "off"}
    if not enabled:
        close_sessions(path)
        with module.HdfSession(path, threads=threads) as session:
            yield session
        return
    if setting != "persist" and not _native_scope.active():
        # Outside a public call nothing may stay open: Windows (and network
        # shares) refuse to rename, delete or replace an open HDF.
        with module.HdfSession(path, threads=threads) as session:
            yield session
        return
    with _sessions_lock:
        try:
            stat = _stat(path)
        except OSError:
            close_sessions(path)
            raise
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        for old in list(_sessions):
            if old[0] == str(path) and (old != key or (
                    not any_threads and _sessions[old][1] != threads)):
                _scoped_keys.discard(old)
                _sessions.pop(old)[0].close()
        if key not in _sessions:
            while len(_sessions) >= _SESSION_LIMIT:
                evicted = _sessions.popitem(last=False)
                _scoped_keys.discard(evicted[0])
                evicted[1][0].close()
            _sessions[key] = (module.HdfSession(path, threads=threads), threads)
            if setting != "persist":
                _scoped_keys.add(key)
                _native_scope.sessions_opened(_release_scoped_sessions)
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


def _safe_file(dataset, file=None):
    """Whether the engine may reopen ``dataset``'s file (``file`` is ``dataset.file`` when given)."""
    file = dataset.file if file is None else file
    filename = file.filename
    # Reopening must never discard dirty state or escape an in-memory file.
    return (
        file.mode == "r"
        and file.driver not in {"core", "fileobj", "family", "split", "mpio"}
        and isinstance(filename, (str, bytes))
        and _is_file(os.fsdecode(filename))
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


# ------------------------------------------------------------- chunked reads
# The engine refuses any single numeric read whose decoded values exceed its
# DEFAULT_READ_MAX_BYTES (2 GiB) before allocating, so a crafted file cannot make
# it reserve memory the file does not hold. Larger reads are served here as a
# loop of bounded hyperslab reads into one NumPy-allocated output, after the
# declared size has been checked against the storage the file really holds
# (``_implausible``). Tests shrink both budgets through monkeypatch.
_NATIVE_CALL_BUDGET = 2 * 1024 ** 3
_CHUNKED_BLOCK_BYTES = 256 * 1024 ** 2
# Worst-case decoded/stored size ratio of each filter the engine decodes. A
# filter without a finite bound (scale-offset with zero bits, szip, unknown
# plugins) makes a declared size unprovable, so such datasets are refused here.
_FILTER_EXPANSION = {
    h5py.h5z.FILTER_DEFLATE: 1100,   # deflate cannot exceed about 1032:1
    h5py.h5z.FILTER_SHUFFLE: 1,
    h5py.h5z.FILTER_FLETCHER32: 1,
    h5py.h5z.FILTER_NBIT: 64,        # at least one stored bit per 64-bit value
    32004: 256,                      # LZ4: at most 255:1
}


def _over_budget(shape, dtype):
    """Whether one engine call could not return ``shape`` values of ``dtype``."""
    return math.prod(shape) * dtype.itemsize > _NATIVE_CALL_BUDGET


def _implausible(dataset):
    """Why the declared size of ``dataset`` is not backed by its file, or ``None``.

    Policy (applied only to reads above the per-call budget, before allocating):
    contiguous storage must be allocated and lie inside the file; chunked
    storage must be no larger than the file, its stored chunks must decode to
    no more than ``stored bytes x worst-case filter expansion``, and the
    remainder served from the fill value (unallocated chunks) may not exceed
    the per-call budget. Anything else stays an engine refusal: auto mode then
    returns h5py's outcome and required mode raises :class:`FastHdfError`.
    """
    itemsize = dataset.dtype.itemsize
    declared = math.prod(dataset.shape) * itemsize
    file_size = os.path.getsize(os.fsdecode(dataset.file.filename))
    dsid = dataset.id
    dcpl = dsid.get_create_plist()
    layout = dcpl.get_layout()
    if layout == h5py.h5d.COMPACT:
        return None  # bounded by the 64 KiB object header limit
    if layout == h5py.h5d.CONTIGUOUS:
        offset = dsid.get_offset()
        if offset is None:
            return f"declares {declared} bytes of contiguous storage that is not allocated"
        if offset + declared > file_size:
            return (f"declares {declared} contiguous bytes at offset {offset} "
                    f"in a {file_size} byte file")
        return None
    if layout != h5py.h5d.CHUNKED or not dataset.chunks:
        return f"storage layout {layout} is not provable"
    stored = dsid.get_storage_size()
    if stored > file_size:
        return f"reports {stored} stored bytes in a {file_size} byte file"
    expansion = 1
    for index in range(dcpl.get_nfilters()):
        code = dcpl.get_filter(index)[0]
        if code not in _FILTER_EXPANSION:
            return f"filter {code} has no bounded expansion"
        expansion *= _FILTER_EXPANSION[code]
    allocated = dsid.get_num_chunks()
    backed = allocated * math.prod(dataset.chunks) * itemsize
    if backed > stored * expansion:
        return (f"{allocated} stored chunks would decode to {backed} bytes from "
                f"{stored} stored bytes")
    unbacked = declared - min(declared, backed)
    if unbacked > _NATIVE_CALL_BUDGET:
        return (f"{unbacked} of {declared} declared bytes have no stored chunks "
                f"(fill-only beyond the {_NATIVE_CALL_BUDGET} byte budget)")
    return None


def _block_plan(dataset, slices, block_bytes):
    """``(source selection, output index)`` blocks covering ``slices``.

    Blocks split the first axis whose trailing slab fits ``block_bytes``; outer
    axes are walked one index at a time. With unit steps, block edges fall on
    the stored chunk grid of the split axis so no chunk is decoded twice, and a
    block grows to one whole chunk band when the band fits the per-call budget.
    """
    sel = slices or [(0, n, 1) for n in dataset.shape]
    counts = [len(range(*s)) for s in sel]
    itemsize = dataset.dtype.itemsize
    tails = [itemsize * math.prod(counts[k + 1:]) for k in range(len(counts))]
    axis = next(k for k, tail in enumerate(tails) if tail <= block_bytes)
    count, (start, _, step) = counts[axis], sel[axis]
    rows = max(1, min(count, block_bytes // tails[axis]))
    chunk = dataset.chunks[axis] if dataset.chunks else 1
    aligned = False
    if step == 1 and chunk > 1:
        if rows >= chunk:
            rows -= rows % chunk
        elif chunk * tails[axis] <= _NATIVE_CALL_BUDGET:
            rows = chunk
        aligned = rows % chunk == 0
    if aligned:
        first = (start // rows + 1) * rows - start
        edges = [0, *range(first, count, rows), count] if first < count else [0, count]
    else:
        edges = [*range(0, count, rows), count]
    trailing_src = [tuple(s) for s in sel[axis + 1:]]
    trailing_dst = [slice(None)] * len(trailing_src)
    for outer in np.ndindex(*counts[:axis]):
        outer_src = [(s0 + i * st, s0 + i * st + 1, 1) for i, (s0, _, st) in zip(outer, sel)]
        outer_dst = [slice(i, i + 1) for i in outer]
        for a, b in zip(edges, edges[1:]):
            src = (*outer_src, (start + a * step, start + (b - 1) * step + 1, step), *trailing_src)
            yield list(src), (*outer_dst, slice(a, b), *trailing_dst)


def _read_chunked(session, dataset, slices, expected):
    """Exact ``dataset[slices]`` above the per-call budget, as bounded native reads.

    Returns ``(values, blocks)``. The output is allocated by NumPy in the
    dataset's own dtype (byte order included), so an allocation failure is a
    Python ``MemoryError`` and never a native abort.
    """
    reason = _implausible(dataset)
    if reason is not None:
        raise FastHdfError(f"{dataset.name}: implausible declared size: {reason}")
    out, blocks = None, 0
    for src, dst in _block_plan(dataset, slices, _CHUNKED_BLOCK_BYTES):
        part = np.asarray(session.read_numeric(dataset.name, selection=src))
        if out is None:
            # Allocate only once the engine has accepted the dataset's encoding.
            out = np.empty(expected, dtype=dataset.dtype)
        target = out[dst]
        if (part.dtype.kind != out.dtype.kind or part.dtype.itemsize != out.dtype.itemsize
                or part.shape != target.shape):
            raise FastHdfError(
                f"Native block mismatch for {dataset.name}: {part.dtype}{part.shape} "
                f"versus {out.dtype}{target.shape}")
        target[...] = part
        blocks += 1
    return out, blocks


@_one_read
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
    file = dataset.file
    if not _safe_file(dataset, file) or not _numeric(dataset) or dataset.shape is None:
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
    if mode == "auto" and dataset.chunks is None and _over_budget(expected, dataset.dtype):
        # Contiguous storage above one engine call: h5py copies it straight from
        # the file, 4-5x faster than bounded native blocks once the file is
        # cached (PERF_CHUNKED_READS.md), with the same values. Required mode
        # keeps the native chunked path.
        _record(dataset.name, "h5py", "contiguous-direct")
        return dataset[key]
    route = ("mesh_result" if dataset.name.startswith(
        "/Results/Unsteady/Output/Output Blocks/Base Output/") and "/2D Flow Areas/" in dataset.name
        else "generic")
    try:
        with _session(module, os.fsdecode(file.filename), threads) as session:
            try:
                values = _read_fim_result(session, dataset, slices, threads)
                served = ("native-typed", "mesh_result") if values is not None else ("native-generic", None)
            except Exception as exc:
                if not _domain_refusal(exc):
                    raise
                # Typed domain unqualified: the literal generic read is exact.
                logger.debug("literal generic read for %s: %s", dataset.name, exc)
                values, served = None, ("native-generic", "mesh_result-literal")
            if values is None and _over_budget(expected, dataset.dtype):
                # Above one engine call's budget: bounded blocks into one array.
                values, blocks = _read_chunked(session, dataset, slices, expected)
                served = ("native-generic", "chunked", f"{blocks} bounded blocks")
            elif values is None:
                values = session.read_numeric(dataset.name, selection=slices)
        # A binding that returns the wrong dtype/shape is a native failure too.
        values = _checked_array(values, dataset.dtype, expected)
    except Exception as exc:
        if mode == "auto":
            # h5py is the public contract: any native failure, Corrupt included.
            logger.debug("h5py fallback for %s: %s", dataset.name, exc)
            _record(dataset.name, "h5py-fallback", route)
            return dataset[key]
        raise FastHdfError(f"Native read failed for {dataset.name}: {exc}") from exc
    _record(dataset.name, *served)
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


def mesh_series_domain(dataset: h5py.Dataset, *, backend="auto"):
    """Engine-typed element domain and ``domain_rule`` of a Base Output 2D mesh series.

    ``{"id_dim", "domain", "domain_rule", "capability"}``; ``None`` in python mode
    (and in auto mode on an engine failure). See ``_fast_hdf_typed.mesh_series_domain``.
    """
    from . import _fast_hdf_typed
    return _fast_hdf_typed.mesh_series_domain(dataset, backend=backend)


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
    backend = _normalize_backend(backend)
    if backend == "rust" or (backend == "auto" and native_required()):
        raise exc


def trace_reads():
    """Context manager recording which backend served each ``read_typed`` call."""
    from . import _fast_hdf_typed
    return _fast_hdf_typed.trace_reads()


@_one_read
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
                    # One engine batch shares the per-call budget: split the
                    # generic paths into batches within it, and serve a dataset
                    # above it on its own as bounded chunked reads.
                    native_values, batch, batch_bytes = {}, [], 0
                    for path in generic:
                        ds = datasets[path]
                        size = ds.size * ds.dtype.itemsize
                        if _over_budget(ds.shape, ds.dtype):
                            if mode == "auto" and ds.chunks is None:
                                # Contiguous above the budget: h5py direct (see read_dataset).
                                native_values[path] = ds[()]
                            else:
                                native_values[path] = _read_chunked(session, ds, None, ds.shape)[0]
                            continue
                        if batch and batch_bytes + size > _NATIVE_CALL_BUDGET:
                            native_values.update(session.read_numeric_batch(batch))
                            batch, batch_bytes = [], 0
                        batch.append(path)
                        batch_bytes += size
                    if batch:
                        native_values.update(session.read_numeric_batch(batch))
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
                try:
                    if path not in native_values:
                        raise FastHdfError(f"Native batch omitted {path}")
                    values = _checked_array(native_values[path], ds.dtype, ds.shape)
                except FastHdfError:
                    if mode != "auto":
                        raise
                    # Auto: a broken binding result for one dataset gets h5py's outcome.
                    result[path] = ds[()]
                    continue
                result[path] = values[()] if values.ndim == 0 else values
            else:
                result[path] = ds[()]
        return result


_MESH_ARRAYS = (
    "FacePoints Coordinate", "Faces FacePoint Indexes", "Faces Perimeter Info",
    "Faces Perimeter Values", "Cells Face and Orientation Info",
    "Cells Face and Orientation Values",
)


def _reference_missing_cell(args, start, length, invalid):
    """The Python reference's record kind for a cell native did not assemble.

    ``"boundary_only"``, ``"zero_faces"`` or ``"no_polygon"`` when the
    reference provably produces that record (and no polygon) for the cell;
    ``None`` when it would not (it would report another reason or return a
    polygon), so the native diagnostics cannot be returned in auto mode.
    """
    from shapely.geometry import LineString
    from shapely.ops import polygonize
    points, face_points, perimeter_info, perimeter_values, _, values = args
    if start < 0 or length < 0 or start + length > len(values):
        return None
    if length == 0:
        return None if invalid else "zero_faces"
    face_ids = [int(face) for face in values[start:start + length, 0]]
    if any(not 0 <= face < len(face_points) for face in face_ids):
        return None
    if length < 3:
        return None if invalid else "boundary_only"
    lines = []
    for face in face_ids:
        a, b = map(int, face_points[face, :2])
        offset, count = map(int, perimeter_info[face, :2])
        if not (0 <= a < len(points) and 0 <= b < len(points)) or (
                count > 0 and (offset < 0 or offset + count > len(perimeter_values))):
            return None
        coords = [points[a]]
        if count > 0:
            coords.extend(perimeter_values[offset:offset + count])
        coords.append(points[b])
        lines.append(LineString(coords))
    return "no_polygon" if not list(polygonize(lines)) else None


def _assemble(hdf, mesh_name, module, backend, threads, *, diagnostics=False, strict=True,
              reference_diagnostics=False):
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
        # ``reference_diagnostics`` (auto mode) proves every record equal to the
        # Python reference's, or marks the result not provable so that auto
        # mode uses the Python polygonizer (see _native_mesh_polygons):
        # - an assembled cell with fewer than three faces is never a polygon in
        #   the reference: not provable;
        # - a missing one- or two-face cell is the reference's boundary_only /
        #   insufficient_faces record, and a missing zero-face cell its omitted /
        #   zero_faces record, when the face span and face IDs are in range (so
        #   the reference finds no invalid_face_span/missing_face_reference);
        # - a missing cell with three or more faces is polygonized exactly as
        #   the reference does (faces rebuilt as get_mesh_cell_faces builds
        #   them, shapely.ops.polygonize): no polygon gives the reference's
        #   omitted/no_polygon record; one or more polygons (a cell the
        #   reference returns, possibly ambiguous/multiple_polygons) is not
        #   provable. A valid assembled ring uses every face of its cell once,
        #   so the reference polygonizes it as exactly one polygon.
        provable = True
        if reference_diagnostics:
            lengths = np.asarray(args[4][:, 1], dtype=np.int64)
            provable = not bool((lengths[np.asarray(cell_ids, dtype=np.int64)] < 3).any())
        for cell_id in np.flatnonzero(missing):
            start, length = map(int, args[4][cell_id, :2])
            reference_omitted = False
            if reference_diagnostics and provable:
                verdict = _reference_missing_cell(args, start, length, cell_id in invalid)
                if verdict is None:
                    provable = False
                reference_omitted = verdict == "no_polygon"
            records.append({
                "mesh_name": mesh_name, "cell_id": int(cell_id),
                "face_count": length, "polygon_count": 0,
                "status": "omitted" if (cell_id in invalid or length == 0
                                        or reference_omitted) else "boundary_only",
                "reason_code": "no_polygon" if (cell_id in invalid or reference_omitted) else (
                    "zero_faces" if length == 0 else "insufficient_faces"),
                "face_ids": tuple(map(int, args[5][start:start + length, 0])),
                "missing_face_ids": (),
            })
            if cell_id in invalid:
                # Records keep the Python reference schema exactly, so auto mode
                # returns the same diagnostics as h5py; the native detail is logged.
                logger.debug("Native mesh %r cell %d omitted (%s): %s", mesh_name,
                             int(cell_id), invalid[cell_id][0], invalid[cell_id][1])
        result["diagnostics"] = records
        result["diagnostics_provable"] = provable
    return result


@log_call
@_one_read
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


@_one_read
def mesh_face_lines(hdf_path, mesh_name, *, backend="auto"):
    """Native packed face polylines of one mesh, or ``None`` to build them in Python.

    Returns ``(coordinates, offsets)`` as :func:`HdfMesh._packed_face_lines`
    does: float64 ``(N, 2)`` coordinates and int64 offsets, face ``i`` being
    ``coordinates[offsets[i]:offsets[i + 1]]``. The engine builds them only for
    layouts proven identical to the Python per-face loop and refuses the rest.
    ``None`` (build in Python) with h5py, with an extension that predates
    ``HdfSession.read_mesh_face_lines`` (the face tables are then still read
    natively), and in ``auto`` mode on any native refusal or failure. ``native``
    mode raises :class:`FastHdfError` on a refusal.
    """
    mode = _mode(backend)
    module = _native(mode)
    if module is None or not hasattr(getattr(module, "HdfSession", None), "read_mesh_face_lines"):
        return None
    try:
        with _session(module, hdf_path, None, any_threads=True) as session:
            packed = session.read_mesh_face_lines(mesh_name)
        coordinates = np.asarray(packed["coordinates"])
        offsets = np.asarray(packed["offsets"])
        face_ids = np.asarray(packed["face_ids"])
        count = len(face_ids)
        if (coordinates.dtype != np.float64 or coordinates.ndim != 2 or coordinates.shape[1] != 2
                or offsets.dtype != np.int64 or offsets.shape != (count + 1,)
                or offsets[0] != 0 or offsets[-1] != len(coordinates)
                or (np.diff(offsets) < 2).any()
                or not np.array_equal(face_ids, np.arange(count))):
            raise FastHdfError("Native face lines are not a packed line buffer in face order")
    except Exception as exc:
        if mode != "auto":
            if isinstance(exc, FastHdfError):
                raise
            raise FastHdfError(f"Native face lines failed for {hdf_path} mesh {mesh_name!r}: {exc}") from exc
        logger.debug("Python face lines for %s/%s after native refusal: %s", hdf_path, mesh_name, exc)
        return None
    return coordinates, offsets


def _try_mesh_polygons(hdf_path, *, backend="auto", threads=None, strict=None):
    """Internal compatibility hook; None means use the original polygonizer.

    In auto mode *any* native failure returns None, so the Python polygonizer
    produces the result (or the exception) the library has always produced.
    Explicit ``rust`` and required mode raise instead.
    """
    mode, threads = _mode(backend), _threads(threads)
    module = _native(mode)
    if module is None:
        return None
    try:
        return _native_mesh_polygons(module, mode, hdf_path, backend, threads, strict)
    except Exception as exc:
        if mode != "auto":
            raise
        logger.debug("Python polygonizer after native mesh polygon failure in %s: %s", hdf_path, exc)
        return None


_PARALLEL_POLYGONS = 50_000


def _polygons_and_validity(coordinates, offsets, count, threads):
    """Single-ring polygons from packed buffers, and ``shapely.is_valid`` of each.

    Large meshes are split into contiguous cell ranges built and checked on
    worker threads (Shapely releases the GIL); every polygon and flag is the
    one the single vectorized call gives, in the same order.
    """
    import shapely

    def build(start, stop):
        rings = np.asarray(offsets[start:stop + 1], dtype=np.int64)
        polygons = shapely.from_ragged_array(
            shapely.GeometryType.POLYGON, coordinates[rings[0]:rings[-1]],
            (rings - rings[0], np.arange(stop - start + 1, dtype=np.int64)),
        )
        return polygons, shapely.is_valid(polygons)

    workers = min(threads or os.cpu_count() or 1, 8)
    if count < _PARALLEL_POLYGONS or workers < 2:
        return build(0, count)
    from concurrent.futures import ThreadPoolExecutor
    bounds = np.linspace(0, count, workers * 4 + 1).astype(np.int64)
    with ThreadPoolExecutor(workers) as pool:
        parts = list(pool.map(build, bounds[:-1], bounds[1:]))
    return (np.concatenate([part[0] for part in parts]),
            np.concatenate([part[1] for part in parts]))


def _native_mesh_polygons(module, mode, hdf_path, backend, threads, strict):
    from geopandas import GeoDataFrame
    from .hdf.HdfBase import HdfBase
    from .hdf.HdfMesh import HdfMesh
    from .hdf.HdfUtils import HdfUtils
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
                                   diagnostics=strict is not None, strict=strict is not False,
                                   reference_diagnostics=mode == "auto")
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
            if mode == "auto" and not packed.get("diagnostics_provable", True):
                # Auto mode must return the reference diagnostics, status labels
                # and warnings exactly (main's behaviour); use the Python polygonizer.
                logger.debug("Python polygon diagnostics for %s/%s: native records are "
                             "not proven equal to the reference", hdf_path, name)
                return None
            count = len(packed["cell_ids"])
            diagnostics.extend(packed.get("diagnostics", ()))
            if count:
                polygons, valid = _polygons_and_validity(
                    packed["coordinates"], packed["offsets"], count, threads)
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
                names.append(HdfUtils._repeat_text(name, count))
                ids.append(packed["cell_ids"])
                geometries.append(polygons)
        if not names and strict is None:
            return GeoDataFrame()
        projection = HdfBase.get_projection(hdf)
        result = GeoDataFrame({"mesh_name": np.concatenate(names) if names else [],
                               "cell_id": np.concatenate(ids) if ids else [],
                               "geometry": np.concatenate(geometries) if geometries else []},
                              geometry="geometry",
                              crs=HdfUtils._to_crs(projection) if projection else projection)
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
                # The reference's warning, from the reference's logger.
                from .hdf.HdfMesh import logger as mesh_logger
                mesh_logger.warning(message)
        return result


@log_call
@_one_read
def mesh_polygons(hdf_path, *, backend="auto", threads=None, strict=False, diagnostics=False):
    """Extract the established mesh GeoDataFrame, with explicit backend control.

    ``backend`` takes the public engine values (``auto``/``h5py``/``native``);
    see :meth:`HdfMesh.get_mesh_cell_polygons` for ``diagnostics``.
    """
    from .hdf.HdfMesh import HdfMesh
    return HdfMesh.get_mesh_cell_polygons(hdf_path, engine=backend, threads=threads,
                                          strict=strict, diagnostics=diagnostics)


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


# NumPy dtypes ``write_pmtiles`` reads without a Python object per value
# (ras-commander-fast-hdf PR #37). Narrower integer and float dtypes widen
# exactly to one of these first.
_COLUMNAR_DTYPES = frozenset(np.dtype(code) for code in ("f8", "f4", "i8", "i4", "u8", "u4", "?"))
_COLUMNAR_WIDEN = {"i": np.dtype("i4"), "u": np.dtype("u4"), "f": np.dtype("f4")}
_COLUMNAR_SUPPORT = {}
_COLUMNAR_LOCK = RLock()


def _supports_columnar_properties(module) -> bool:
    """Whether this engine's ``write_pmtiles`` takes columnar property forms.

    Detected by capability, not by version: engines without it parse every
    property column as a Python list and reject a NumPy column with
    ``TypeError``. The probe is an empty layer carrying one column of each
    form (array, ``(values, valid)`` pair, categorical dict). A columnar
    engine parses all three and then refuses the featureless layer with
    ``ValueError`` before any output is opened. Cached per ``write_pmtiles``.
    """
    write = getattr(module, "write_pmtiles", None)
    if write is None:
        return False
    with _COLUMNAR_LOCK:
        try:
            return _COLUMNAR_SUPPORT[write]
        except (KeyError, TypeError):
            pass
        empty = np.zeros(0, dtype=np.float64)
        layer = {"name": "probe", "coordinates": np.zeros((0, 2), dtype=np.float64),
                 "offsets": np.zeros(1, dtype=np.int64), "cell_ids": np.zeros(0, dtype=np.int64),
                 "properties": {"array": empty, "masked": (empty, np.zeros(0, dtype=bool)),
                                "categorical": {"codes": np.zeros(0, dtype=np.int64),
                                                "categories": []}}}
        with tempfile.TemporaryDirectory(prefix="ras-commander-pmtiles-probe-") as folder:
            try:
                write([layer], str(Path(folder) / "probe.pmtiles"), 0, 0, threads=1)
                supported = False
            except ValueError as exc:
                supported = "nonempty layer" in str(exc)
            except Exception:  # noqa: BLE001 - any other refusal means list-only
                supported = False
        try:
            _COLUMNAR_SUPPORT[write] = supported
        except TypeError:
            pass
        logger.debug("write_pmtiles columnar properties: %s", supported)
        return supported


def _columnar_array(values):
    """Return ``values`` as an array ``write_pmtiles`` reads natively, or None.

    Only typed NumPy arrays qualify; lists and object arrays keep the list form,
    whose per-value scalar rules (for example ``[1, "a"]``) must not change.
    Widening (int8 -> int32, float16 -> float32) and byte-order normalisation
    are exact, so the tiles equal those of the list form.
    """
    if not isinstance(values, np.ndarray) or values.ndim != 1:
        return None
    dtype = values.dtype
    if dtype.kind in _COLUMNAR_WIDEN and dtype.itemsize < 4:
        dtype = _COLUMNAR_WIDEN[dtype.kind]
    elif not dtype.isnative:
        dtype = dtype.newbyteorder("=")
    if dtype not in _COLUMNAR_DTYPES:
        return None
    return np.ascontiguousarray(values, dtype=dtype)


def _categorical_column(values):
    """A one-dimensional NumPy unicode array as ``{"codes", "categories"}``, or None."""
    if not isinstance(values, np.ndarray) or values.ndim != 1 or values.dtype.kind != "U":
        return None
    categories, codes = np.unique(values, return_inverse=True)
    return {"codes": np.ascontiguousarray(codes.reshape(-1), dtype=np.int64),
            "categories": [str(value) for value in categories]}


def _pmtiles_column(value, count, name, module):
    """Prepare one property column in the cheapest form the engine accepts.

    Accepted inputs: a sequence of scalars (list form), a typed 1-D NumPy
    array, a ``(values, valid)`` pair (``False`` meaning null) or a
    ``{"codes", "categories"}`` dict (code ``-1`` meaning null). Columnar
    inputs are passed through when the engine supports them and converted to
    the equivalent list otherwise; both give byte-identical archives.
    """
    if isinstance(value, tuple):
        if len(value) != 2:
            raise ValueError(f"Property {name!r}: a masked column is a (values, valid) pair")
        values, valid = _columnar_array(value[0]), value[1]
        if values is None:
            raise ValueError(f"Property {name!r}: masked values must be a typed 1-D NumPy array")
        if not isinstance(valid, np.ndarray) or valid.dtype != np.bool_ or valid.shape != values.shape:
            raise ValueError(f"Property {name!r}: the validity mask must be a bool array of the same length")
        if len(values) != count:
            raise ValueError(f"Property {name!r} must have one value per feature")
        if _supports_columnar_properties(module):
            return values, np.ascontiguousarray(valid)
        result = _property_values(values, count, name)
        return [item if ok else None for item, ok in zip(result, valid.tolist())]
    if isinstance(value, Mapping):
        if set(value) != {"codes", "categories"}:
            raise ValueError(f"Property {name!r}: a categorical column has exactly 'codes' and 'categories'")
        codes = np.asarray(value["codes"])
        categories = list(value["categories"])
        if codes.ndim != 1 or codes.dtype.kind not in "iu" or len(codes) != count:
            raise ValueError(f"Property {name!r}: categorical codes must be one integer per feature")
        if not all(isinstance(item, str) for item in categories):
            raise TypeError(f"Property {name!r}: categories must be strings")
        if len(codes) and (codes.min() < -1 or codes.max() >= len(categories)):
            raise ValueError(f"Property {name!r}: categorical code out of range")
        if _supports_columnar_properties(module):
            return {"codes": np.ascontiguousarray(codes, dtype=np.int64), "categories": categories}
        return [None if code < 0 else categories[code] for code in codes.tolist()]
    native = _columnar_array(value)
    if native is None:
        native = _categorical_column(value)
    if native is not None:
        length = len(native["codes"]) if isinstance(native, dict) else len(native)
        if length != count:
            raise ValueError(f"Property {name!r} must have one value per feature")
        if _supports_columnar_properties(module):
            return native
    return _property_values(value, count, name)


@log_call
def export_pmtiles(output_path, layers: Mapping, *, source_crs="EPSG:4326",
                   min_zoom=0, max_zoom=12, backend="auto", threads=None):
    """Atomically export packed polygon layers through pyproj and freestiler.

    ``layers`` maps source-layer names to coordinates, offsets, cell_ids and
    optional property columns. Properties are aligned with the supplied IDs.
    A property column is a sequence of scalars, a typed 1-D NumPy array, a
    ``(values, valid)`` pair (``False`` meaning null) or a
    ``{"codes": int array, "categories": [str, ...]}`` dict (``-1`` null).
    Engines that read columns natively (detected by capability) receive the
    arrays without a Python object per value; others receive the equivalent
    lists. Both give byte-identical archives.
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
        columns = {key: _pmtiles_column(value, len(ids), key, module)
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


def _mesh_property_column(parts, counts, key):
    """Concatenate one property across meshes; ``None`` parts are missing (null).

    Typed parts sharing one native dtype become an array, or a
    ``(values, valid)`` pair when some mesh lacks the column. Anything else
    (object, string or mixed dtypes) keeps the per-value list form, so the
    scalar type of every value is exactly what it was.
    """
    present = [part for part in parts if part is not None]
    dtypes = {part.dtype for part in present}
    if len(dtypes) == 1 and _columnar_array(present[0][:0]) is not None:
        dtype = dtypes.pop()
        values = np.concatenate([np.zeros(count, dtype=dtype) if part is None else part
                                 for part, count in zip(parts, counts)])
        if len(present) == len(parts):
            return values
        valid = np.concatenate([np.full(count, part is not None) for part, count in zip(parts, counts)])
        return values, valid
    column = []
    for part, count in zip(parts, counts):
        column.extend([None] * count if part is None else _property_values(part, count, key))
    return column


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
    # Columns are built as arrays: mesh_name as a categorical, typed result
    # columns gathered by cell ID (masked where a mesh lacks the column).
    # export_pmtiles passes them to an engine that reads columns natively and
    # converts them to the equivalent lists for one that does not.
    names, counts, id_parts, offset_parts = [], [], [], [np.zeros(1, dtype=np.int64)]
    parts = {key: [] for key in property_names}
    coordinates, cursor = [], 0
    for name, packed in meshes.items():
        ids = np.asarray(packed["cell_ids"])
        count = len(ids)
        if not count:
            continue
        coordinates.append(packed["coordinates"])
        offset_parts.append(np.asarray(packed["offsets"], dtype=np.int64)[1:] + cursor)
        cursor += len(packed["coordinates"])
        names.append(name)
        counts.append(count)
        id_parts.append(ids)
        for key in property_names:
            if key not in properties.get(name, {}):
                parts[key].append(None)
                continue
            source = properties[name][key]
            values = source if isinstance(source, np.ndarray) else np.asarray(source, dtype=object)
            if values.ndim != 1 or len(values) <= int(ids.max()):
                raise ValueError(f"Property {name}/{key} does not cover every source cell ID")
            parts[key].append(values[ids])
    if not coordinates:
        raise ValueError("No mesh cell polygons are available for export")
    columns = {"mesh_name": {"codes": np.repeat(np.arange(len(names), dtype=np.int64), counts),
                             "categories": names},
               "cell_id": np.concatenate(id_parts)}
    for key in property_names:
        columns[key] = _mesh_property_column(parts[key], counts, key)
    count = sum(counts)
    layer = {"coordinates": np.concatenate(coordinates), "offsets": np.concatenate(offset_parts),
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

