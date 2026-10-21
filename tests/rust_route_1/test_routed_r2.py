"""PY-ROUTE-1 review fixes (r2) on physically damaged *copies* of real fixtures.

- Generic route, Fletcher32 checksum damage: a numeric dataset outside every
  typed family (``FacePoints Face and Orientation Info``) is rewritten with its
  exact real values in Fletcher32 chunks, required-native is shown to read the
  clean copy, then one stored checksum byte is flipped. Auto must return the
  h5py public outcome (``get_mesh_sloped_topology`` returns ``{}``); required
  native must raise ``FastHdfError``.
- Steady results with the same damage: auto reproduces the h5py ``RuntimeError``;
  required native surfaces ``FastHdfError`` instead of the generic wrapper.
- Virtual dataset: FacePoint coordinates replaced by an equivalent HDF virtual
  dataset. Required native must refuse instead of reading them through h5py.
- Selection contract: ``read_typed`` raises h5py's own selection errors in every
  mode and serves valid basic/vector selections natively with identical bytes.

Gate: ``RAS_ROUTE1_FIXTURES`` (same manifest as the equivalence suite).
"""
import json
import os
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from ._exact import assert_identical
from ._h5py_guard import offending, watch_h5py_reads

MANIFEST = os.environ.get("RAS_ROUTE1_FIXTURES")
FIXTURES = {f["name"]: f["path"] for f in json.loads(Path(MANIFEST).read_text())["fixtures"]} if MANIFEST else {}
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE1_FIXTURES to the PY-ROUTE-1 real-fixture JSON manifest")


def _fixture(name):
    pytest.importorskip("ras_commander_fast_hdf")
    if name not in FIXTURES:
        pytest.skip(f"fixture {name} not in manifest")
    return Path(FIXTURES[name])


def _outcome(monkeypatch, mode, call):
    from ras_commander import fast_hdf
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    fast_hdf.close_sessions()
    try:
        with watch_h5py_reads() as direct, fast_hdf.trace_reads() as trace:
            try:
                return ("ok", call()), list(trace), list(direct)
            except Exception as exc:
                return ("raise", type(exc), str(exc)), list(trace), list(direct)
    finally:
        fast_hdf.close_sessions()


def _same(a, b, label):
    assert a[0] == b[0], f"{label}: {a[:3]} vs {b[:3]}"
    if a[0] == "ok":
        assert_identical(a[1], b[1], label)
    else:
        assert a[1] is b[1] and a[2] == b[2], f"{label}: {a} vs {b}"


def _fletcher32_copy(source, copy, key, chunks):
    """Recreate ``key`` with its exact values in Fletcher32 chunks; return the
    file offset of the last stored byte of the first chunk (its checksum)."""
    shutil.copyfile(source, copy)
    with h5py.File(copy, "r+") as f:
        values = f[key][()]
        attrs = dict(f[key].attrs)
        del f[key]
        d = f.create_dataset(key, data=values, chunks=chunks(values), fletcher32=True)
        for k, v in attrs.items():
            d.attrs[k] = v
        info = d.id.get_chunk_info_by_coord((0,) * values.ndim)
        return int(info.byte_offset) + int(info.size) - 1


def _flip(path, offset):
    with open(path, "r+b") as fh:
        fh.seek(offset)
        byte = fh.read(1)
        fh.seek(offset)
        fh.write(bytes([byte[0] ^ 1]))


def test_generic_route_checksum_damage(tmp_path, monkeypatch):
    from ras_commander import fast_hdf, hdf
    source = _fixture("AustinOyster.p01")
    copy = tmp_path / "checksum.p01.hdf"
    key = "Geometry/2D Flow Areas/Perimeter 1/FacePoints Face and Orientation Info"
    offset = _fletcher32_copy(source, copy, key, lambda v: (min(128, len(v)), v.shape[1]))
    call = lambda: hdf.HdfMesh.get_mesh_sloped_topology(copy, "Perimeter 1")

    clean, clean_trace, _ = _outcome(monkeypatch, "required", call)
    assert clean[0] == "ok" and clean[1], "required native must read the clean Fletcher32 copy"
    generic = [r for r in clean_trace if r["path"] == "/" + key]
    assert generic and all(r["backend"] == "native-generic" for r in generic), generic

    _flip(copy, offset)
    py, _, _ = _outcome(monkeypatch, "0", call)
    auto, auto_trace, _ = _outcome(monkeypatch, "auto", call)
    req, _, _ = _outcome(monkeypatch, "required", call)
    assert py == ("ok", {}) or (py[0] == "ok" and py[1] == {}), py[:3]
    _same(py, auto, "auto keeps the h5py outcome on generic-route corruption")
    assert {"path": "/" + key, "backend": "h5py-fallback", "route": "generic"} in auto_trace
    assert req[0] == "raise" and req[1] is fast_hdf.FastHdfError and "checksum" in req[2].lower(), req


def test_steady_wse_checksum_damage(tmp_path, monkeypatch):
    from ras_commander import fast_hdf, hdf
    source = _fixture("Baxter.p01")
    copy = tmp_path / "steady-checksum.p01.hdf"
    key = ("Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/"
           "Cross Sections/Water Surface")
    offset = _fletcher32_copy(source, copy, key, lambda v: v.shape)
    call = lambda: hdf.HdfResultsPlan.get_steady_wse(copy)
    clean, _, _ = _outcome(monkeypatch, "required", call)
    assert clean[0] == "ok", clean[:3]
    _flip(copy, offset)
    py, _, _ = _outcome(monkeypatch, "0", call)
    auto, _, _ = _outcome(monkeypatch, "auto", call)
    req, _, _ = _outcome(monkeypatch, "required", call)
    assert py[0] == "raise" and py[1] is RuntimeError, py
    _same(py, auto, "auto keeps the h5py RuntimeError")
    assert req[0] == "raise" and req[1] is fast_hdf.FastHdfError, req


def test_virtual_coordinates_refused_in_required(tmp_path, monkeypatch):
    from ras_commander import fast_hdf, hdf
    source = _fixture("AustinOyster.p01")
    copy = tmp_path / "virtual.p01.hdf"
    shutil.copyfile(source, copy)
    key = "Geometry/2D Flow Areas/Perimeter 1/FacePoints Coordinate"
    with h5py.File(copy, "r+") as f:
        values = f[key][()]
        f.create_dataset("Review Original Coordinates", data=values)
        del f[key]
        layout = h5py.VirtualLayout(shape=values.shape, dtype=values.dtype)
        layout[:] = h5py.VirtualSource(str(copy), "Review Original Coordinates", shape=values.shape)
        f.create_virtual_dataset(key, layout)
    call = lambda: hdf.HdfBndry.get_bc_external_faces(
        copy, include_geometry=True, on_duplicate_ownership="report")
    py, _, _ = _outcome(monkeypatch, "0", call)
    auto, _, _ = _outcome(monkeypatch, "auto", call)
    req, _, direct = _outcome(monkeypatch, "required", call)
    _same(py, auto, "auto keeps the h5py result for virtual coordinates")
    assert py[0] == "ok" and len(py[1]) > 0
    assert req[0] == "raise" and req[1] is fast_hdf.FastHdfError, req[:3]
    assert not offending(direct), offending(direct)


SELECTIONS = [
    ("full", ()),
    ("rows", slice(0, 3)),
    ("negative_start", slice(-3, None)),
    ("empty_slice", slice(5, 2)),
    ("row_column", (slice(0, 3), 1)),
    ("int_row", 2),
    ("negative_int", -1),
    ("ellipsis_column", (Ellipsis, 0)),
    ("vector", np.array([0, 2, 5])),
    ("vector_list", [1, 4]),
    ("empty_vector", np.array([], dtype=np.int64)),
    ("vector_column", (np.array([0, 2]), 1)),
    # h5py rejects these before reading; every mode must raise the same error.
    ("negative_step", slice(None, None, -1)),
    ("zero_step", slice(None, None, 0)),
    ("out_of_bounds", 999999999),
    ("negative_out_of_bounds", -999999999),
    ("unsorted_vector", np.array([3, 1])),
    ("repeated_vector", np.array([1, 1])),
    ("vector_out_of_range", np.array([0, 999999999])),
    ("new_axis", (None, slice(None))),
    ("two_vectors", (np.array([0, 1]), np.array([0, 1]))),
]
# Valid selections h5py serves that the native router leaves to h5py (refusal in
# required mode): boolean masks, field names, non-integer vectors.
LEFT_TO_H5PY = [("field", "nonexistent"), ("empty_list", [])]


@pytest.mark.parametrize("dataset", [
    "Geometry/2D Flow Areas/Perimeter 1/Cells Center Coordinate",                 # typed mesh geometry
    "Geometry/2D Flow Areas/Perimeter 1/FacePoints Face and Orientation Info",    # generic numeric
])
@pytest.mark.parametrize("label,key", SELECTIONS, ids=[s[0] for s in SELECTIONS])
def test_read_typed_selection_contract(dataset, label, key, monkeypatch):
    from ras_commander import fast_hdf
    source = _fixture("AustinOyster.p01")
    with h5py.File(source, "r") as f:
        ds = f[dataset]
        call = lambda: fast_hdf.read_typed(ds, key)
        py, _, _ = _outcome(monkeypatch, "0", call)
        auto, _, _ = _outcome(monkeypatch, "auto", call)
        req, req_trace, req_direct = _outcome(monkeypatch, "required", call)
    _same(py, auto, label)
    _same(py, req, label)
    if py[0] == "ok":
        assert req_trace and all(r["backend"] in {"native-typed", "native-generic"} for r in req_trace), req_trace
        assert not offending(req_direct), offending(req_direct)


@pytest.mark.parametrize("label,key", LEFT_TO_H5PY, ids=[s[0] for s in LEFT_TO_H5PY])
def test_read_typed_selection_left_to_h5py(label, key, monkeypatch):
    from ras_commander import fast_hdf
    source = _fixture("AustinOyster.p01")
    with h5py.File(source, "r") as f:
        ds = f["Geometry/2D Flow Areas/Perimeter 1/Cells Center Coordinate"]
        call = lambda: fast_hdf.read_typed(ds, key)
        py, _, _ = _outcome(monkeypatch, "0", call)
        auto, _, _ = _outcome(monkeypatch, "auto", call)
        req, _, _ = _outcome(monkeypatch, "required", call)
    _same(py, auto, label)
    assert req[0] == "raise" and req[1] is fast_hdf.FastHdfError, req[:3]
