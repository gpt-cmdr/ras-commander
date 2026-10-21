"""Independent h5py value-read interception for the required-native gate.

``fast_hdf.trace_reads()`` only sees reads that pass through the routing
wrappers, so it cannot prove that a public method never read values through
h5py directly. ``watch_h5py_reads()`` patches ``h5py.Dataset.__getitem__`` and
``h5py.Dataset.read_direct`` (``numpy.asarray(dataset)`` and the ``astype`` /
``fields`` / ``asstr`` wrappers all end in one of these) and records every value
read together with the first calling frame outside h5py.

PY-ROUTE-3 (review P2-2) extends the watch to attribute values:
``h5py.AttributeManager.__getitem__`` is the single high-level attribute value
read (``attrs[name]``, ``attrs.get``, ``attrs.items()``/``values()``, ``dict(attrs)``
and iteration of the item/value views all end there). Key walks, ``in`` checks,
``len`` and ``get_id(name).dtype``/``shape`` read no value and are not recorded.

``offending(records)`` returns the reads that required-native mode does not
allow. The documented required-mode metadata exception is:

- fixed or variable-length text datasets (names, profile names, labels);
- compound tables whose every member is text (identity tables such as XS
  ``River/Reach/RS`` rows), served as ``h5py-metadata`` by the router;
- reads made by the test harness itself (argument discovery in ``_cases``, and in the
  ROUTE-NONHDF ``tests/rust_route_nonhdf/_cases_*.py`` modules).

Any numeric value read (integer, float, bool, complex, enum, vlen numeric), any
compound with a numeric member, and any opaque/unknown class is an offender,
whether or not it came through the router (review-r2 P2-A).

Attribute value reads through h5py are offenders whatever their class, numeric
*and* text (the engine types attributes exactly; ``fast_hdf.read_attrs`` /
``read_attr`` serve them natively). The only allowances are explicit and narrow:
reads by the test harness, and the classes listed in ``ATTRIBUTE_ALLOWED_KINDS``.
"""
from contextlib import contextmanager
import os
import sys

import h5py

_H5PY_DIR = os.path.dirname(h5py.__file__)
# collections.abc Mapping.get/views call AttributeManager.__getitem__ on behalf of the caller
# (the module is frozen in CPython 3.11+, so its code objects report "<frozen _collections_abc>").
_ABC_FILES = {"<frozen _collections_abc>",
              os.path.normcase(os.path.abspath(__import__("_collections_abc").__file__))}
# Attribute classes that may be read through h5py in required mode, each with its reason.
ATTRIBUTE_ALLOWED_KINDS = {}
_ROUTER = os.path.join("ras_commander", "_fast_hdf_typed.py")
_HARNESS = tuple(os.path.join("tests", suite, "_cases.py") for suite in ("rust_route_1", "rust_route_2"))
# ROUTE-NONHDF: the non-Hdf* suite keeps one case module per module group (_cases_<group>.py).
_HARNESS_PREFIX = os.path.join("tests", "rust_route_nonhdf", "_cases")


def _is_harness(filename):
    filename = filename.replace("/", os.sep)
    return filename.endswith(_HARNESS) or (
        _HARNESS_PREFIX in filename and filename.endswith(".py"))


def _caller():
    frame = sys._getframe(3)
    while frame is not None and (frame.f_code.co_filename.startswith(_H5PY_DIR)
                                 or frame.f_code.co_filename in _ABC_FILES
                                 or os.path.normcase(frame.f_code.co_filename) in _ABC_FILES):
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
        "harness": _is_harness(filename),  # any suite's case modules
    })


def attribute_kind(attrs, name):
    """Class of one stored attribute, from its type and dataspace (no value read).

    ``classify`` of the stored dtype, refined for text into ``string-fixed`` /
    ``string-vlen``; a NULL dataspace (h5py ``Empty``) is ``null:<class>``.
    """
    attr = attrs.get_id(name)
    dtype = attr.dtype
    kind = classify(dtype)
    if kind == "string":
        kind = "string-vlen" if h5py.check_vlen_dtype(dtype) is not None else "string-fixed"
    if attr.get_space().get_simple_extent_type() == h5py.h5s.NULL:
        kind = f"null:{kind}"
    return kind


def _record_attr(records, attrs, name):
    try:
        if name not in attrs:
            return  # h5py raises its own KeyError; nothing is read
        kind = attribute_kind(attrs, name)
        owner = h5py.h5i.get_name(attrs._id)
        owner = owner.decode("utf-8", "replace") if isinstance(owner, bytes) else str(owner)
    except Exception:  # closed handle: let h5py raise its own error
        return
    filename, function, line = _caller()
    records.append({
        "path": f"{owner}@{name}", "kind": kind, "how": "attribute", "target": "attribute",
        "caller": f"{os.path.basename(filename)}:{function}:{line}",
        "via_router": filename.replace("/", os.sep).endswith(_ROUTER),
        "harness": _is_harness(filename),
    })


@contextmanager
def watch_h5py_reads():
    """Record every h5py dataset and attribute value read made while the context is active."""
    records = []
    getitem = h5py.Dataset.__getitem__
    read_direct = h5py.Dataset.read_direct
    attr_getitem = h5py.AttributeManager.__getitem__

    def watched_getitem(self, args, new_dtype=None):
        _record(records, self, "getitem")
        return getitem(self, args, new_dtype=new_dtype)

    def watched_read_direct(self, *args, **kwargs):
        _record(records, self, "read_direct")
        return read_direct(self, *args, **kwargs)

    def watched_attr_getitem(self, name):
        _record_attr(records, self, name)
        return attr_getitem(self, name)

    h5py.Dataset.__getitem__ = watched_getitem
    h5py.Dataset.read_direct = watched_read_direct
    h5py.AttributeManager.__getitem__ = watched_attr_getitem
    try:
        yield records
    finally:
        h5py.Dataset.__getitem__ = getitem
        h5py.Dataset.read_direct = read_direct
        h5py.AttributeManager.__getitem__ = attr_getitem


def offending(records):
    """Reads that violate the required-native value-read guarantee.

    Datasets (review-r2 P2-A): harness reads, text datasets and text-only compound
    identity tables are allowed; any numeric value, any compound with a numeric
    member and any opaque/unknown class read through h5py is an offender, whoever
    made the read. Attributes (PY-ROUTE-3): every value read through h5py is an
    offender except harness reads and ``ATTRIBUTE_ALLOWED_KINDS``.
    """
    out = []
    for r in records:
        if r["harness"]:
            continue
        if r.get("target") == "attribute":
            if r["kind"] not in ATTRIBUTE_ALLOWED_KINDS:
                out.append(r)
        elif r["kind"] not in {"string", "compound-text"}:
            out.append(r)
    return out
