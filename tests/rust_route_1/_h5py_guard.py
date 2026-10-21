"""Independent h5py value-read interception for the required-native gate.

``fast_hdf.trace_reads()`` only sees reads that pass through the routing
wrappers, so it cannot prove that a public method never read values through
h5py directly. ``watch_h5py_reads()`` patches ``h5py.Dataset.__getitem__`` and
``h5py.Dataset.read_direct`` (``numpy.asarray(dataset)`` and the ``astype`` /
``fields`` / ``asstr`` wrappers all end in one of these) and records every value
read together with the first calling frame outside h5py.

``offending(records)`` returns the reads that required-native mode does not
allow. The documented required-mode metadata exception is:

- string, bytes and other non-numeric datasets (names, profile names, labels);
- compound tables that the routing layer serves as h5py metadata because the
  pinned engine has no exact raw reader for them (``h5py-metadata`` in the
  trace): identity and attribute tables such as XS ``River/Reach/RS`` rows;
- reads made by the test harness itself (argument discovery in ``_cases``).

Any numeric (integer/float) value read, and any compound read made directly by
library code instead of through ``fast_hdf.read_typed``, is an offender. HDF
attributes (``.attrs``) are metadata and are not dataset value reads.
"""
from contextlib import contextmanager
import os
import sys

import h5py

_H5PY_DIR = os.path.dirname(h5py.__file__)
_ROUTER = os.path.join("ras_commander", "_fast_hdf_typed.py")
_HARNESS = tuple(os.path.join("tests", suite, "_cases.py") for suite in ("rust_route_1", "rust_route_2"))


def _caller():
    frame = sys._getframe(3)
    while frame is not None and frame.f_code.co_filename.startswith(_H5PY_DIR):
        frame = frame.f_back
    if frame is None:
        return "?", "?", 0
    return frame.f_code.co_filename, frame.f_code.co_name, frame.f_lineno


def _record(records, dataset, how):
    try:
        dtype = dataset.dtype
    except Exception:  # closed handle: let h5py raise its own error
        return
    filename, function, line = _caller()
    if dtype.names is not None:
        kind = "compound"
    elif dtype.kind in "iuf":
        kind = "numeric"
    else:
        kind = "string"
    records.append({
        "path": dataset.name, "kind": kind, "how": how,
        "caller": f"{os.path.basename(filename)}:{function}:{line}",
        "via_router": filename.replace("/", os.sep).endswith(_ROUTER),
        "harness": filename.replace("/", os.sep).endswith(_HARNESS),  # either suite's cases
    })


@contextmanager
def watch_h5py_reads():
    """Record every h5py dataset value read made while the context is active."""
    records = []
    getitem = h5py.Dataset.__getitem__
    read_direct = h5py.Dataset.read_direct

    def watched_getitem(self, args, new_dtype=None):
        _record(records, self, "getitem")
        return getitem(self, args, new_dtype=new_dtype)

    def watched_read_direct(self, *args, **kwargs):
        _record(records, self, "read_direct")
        return read_direct(self, *args, **kwargs)

    h5py.Dataset.__getitem__ = watched_getitem
    h5py.Dataset.read_direct = watched_read_direct
    try:
        yield records
    finally:
        h5py.Dataset.__getitem__ = getitem
        h5py.Dataset.read_direct = read_direct


def offending(records):
    """Reads that violate the required-native value-read guarantee."""
    bad = []
    for r in records:
        if r["harness"] or r["kind"] == "string":
            continue
        if r["kind"] == "compound" and r["via_router"]:
            continue
        bad.append(r)
    return bad
