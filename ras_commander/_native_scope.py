"""Public-call scope for cached native HDF sessions.

A cached ``ras_commander_fast_hdf.HdfSession`` keeps its HDF open. On Windows an
open file cannot be renamed, deleted or replaced (network shares are stricter
still), and main never left a file open after a public call returned. The
``log_call`` and ``standardize_input`` decorators therefore wrap every public
call in a scope: sessions opened inside it are shared by all the reads of that
call (which is where the speed-up comes from) and are closed when the
outermost public call returns, on success or on error.

This module has no package imports so the decorators can use it cheaply.
Direct use of the low-level ``fast_hdf`` readers outside a public call keeps
the session cache until ``fast_hdf.close_sessions()``.
"""
import threading

_local = threading.local()
_state = {"dirty": False, "release": None}


def enter():
    """Open a (possibly nested) scope and return the previous depth."""
    depth = getattr(_local, "depth", 0)
    _local.depth = depth + 1
    return depth


def leave(depth):
    """Close a scope; the outermost one releases sessions opened since."""
    _local.depth = depth
    if depth == 0 and _state["dirty"]:
        _state["dirty"] = False
        release = _state["release"]
        if release is not None:
            release()


def active():
    """Whether the calling thread is inside a public-call scope."""
    return getattr(_local, "depth", 0) > 0


def sessions_opened(release):
    """Record that a cached session exists; ``release`` closes them."""
    _state["dirty"] = True
    _state["release"] = release
