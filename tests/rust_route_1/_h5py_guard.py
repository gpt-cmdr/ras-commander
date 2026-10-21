"""Independent h5py value-read interception for the required-native gate.

``fast_hdf.trace_reads()`` only sees reads that pass through the routing
wrappers, so it cannot prove that a public method never read values through
h5py directly. ``watch_h5py_reads()`` patches ``h5py.Dataset.__getitem__`` and
``h5py.Dataset.read_direct`` (``numpy.asarray(dataset)`` and the ``astype`` /
``fields`` / ``asstr`` wrappers all end in one of these) and records every value
read together with the first calling frame outside h5py.

``offending(records)`` returns the reads that required-native mode does not
allow. The documented required-mode metadata exception is:

- fixed or variable-length text datasets (names, profile names, labels);
- compound tables whose every member is text (identity tables such as XS
  ``River/Reach/RS`` rows), served as ``h5py-metadata`` by the router;
- reads made by the test harness itself (argument discovery in ``_cases``).

Any numeric value read (integer, float, bool, complex, enum, vlen numeric), any
compound with a numeric member, and any opaque/unknown class is an offender,
whether or not it came through the router (review-r2 P2-A). HDF
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


def _is_text(dtype):
    return dtype.kind in "SU" or h5py.check_string_dtype(dtype) is not None


def classify(dtype):
    """Explicit dtype class of a dataset value read (review-r2 P3-A).

    ``string``: fixed or variable-length text. ``compound-text``: a compound whose
    every member (recursively, arrays included) is text, i.e. an identity table.
    ``compound-numeric``: any other compound. ``numeric``: integer, float, bool,
    complex and enum values, and variable-length sequences of them. ``other``:
    opaque, reference and any unrecognized class. Only the first two are metadata.
    """
    if dtype.names is not None:
        for name in dtype.names:
            field = dtype.fields[name][0]
            base = field.subdtype[0] if field.subdtype is not None else field
            if classify(base) not in {"string", "compound-text"}:
                return "compound-numeric"
        return "compound-text"
    if _is_text(dtype):
        return "string"
    if dtype.kind in "iufbc" or h5py.check_enum_dtype(dtype) is not None:
        return "numeric"
    vlen = h5py.check_vlen_dtype(dtype)
    if vlen is not None:
        return "string" if _is_text(vlen) else "numeric"
    return "other"


def _record(records, dataset, how):
    try:
        dtype = dataset.dtype
    except Exception:  # closed handle: let h5py raise its own error
        return
    filename, function, line = _caller()
    kind = classify(dtype)
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
    """Reads that violate the required-native value-read guarantee.

    Allowed (review-r2 P2-A): harness reads, text datasets and text-only compound
    identity tables. Any numeric value, any compound with a numeric member and any
    opaque/unknown class read through h5py is an offender, whoever made the read.
    """
    return [r for r in records
            if not r["harness"] and r["kind"] not in {"string", "compound-text"}]
