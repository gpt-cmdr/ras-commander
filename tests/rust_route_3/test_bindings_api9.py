"""Bridge API 11 binding boundary for the engine API 9 additions; h5py is the oracle.

- ``typed_dataset_attributes``: every attribute of a dataset outside every read
  family (SA 2D Area Conn ``Structure Variables``, 2D boundary hydrographs) is
  rebuilt exactly by ``attribute_value``; absent datasets are Unavailable; group
  paths are refused.
- ``raw_fixed_strings``: stored bytes, padding kept; after HDF5's NULLPAD memory
  conversion they equal h5py's ``S<width>`` bytes.
- ``domain_rule`` on mesh series descriptors and on catalogue mesh-result layers.

Gate: ``RAS_ROUTE2_FIXTURES`` (BaldEagleDamBrk.p07, AustinOyster.p01 and the public
FEMA eBFE 5.0.7 plan AustinOyster.p03 must be listed; absent ones skip explicitly).
"""
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

MANIFEST = os.environ.get("RAS_ROUTE2_FIXTURES")
FIXTURES = ({f["name"]: f["path"] for f in json.loads(Path(MANIFEST).read_text())["fixtures"]}
            if MANIFEST else {})
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE2_FIXTURES to the PY-ROUTE-2 real-fixture JSON manifest")
BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


@pytest.fixture
def native():
    module = pytest.importorskip("ras_commander_fast_hdf")
    assert module.API_VERSION == 11
    assert module.capabilities()["engine_api_version"] == 10
    return module


def _fixture(name):
    if name not in FIXTURES:
        pytest.skip(f"{name} not in manifest")
    return FIXTURES[name]


def _same(actual, expected):
    assert type(actual) is type(expected)
    a, e = np.asarray(actual), np.asarray(expected)
    assert a.dtype.str == e.dtype.str and a.shape == e.shape and a.tobytes() == e.tobytes()


def _datasets(path, prefix):
    out = []
    with h5py.File(path, "r") as f:
        group = f.get(prefix)
        if isinstance(group, h5py.Group):
            group.visititems(lambda n, o: out.append(f"{prefix}/{n}") if isinstance(o, h5py.Dataset) else None)
    return out


@pytest.mark.parametrize("name,prefix", [
    ("BaldEagleDamBrk.p07", f"{BASE}/2D Flow Areas"),
    ("BaldEagleDamBrk.p07", f"{BASE}/SA 2D Area Conn"),
    ("AustinOyster.p01", f"{BASE}/2D Flow Areas"),
])
def test_typed_dataset_attributes_exact(native, name, prefix):
    from ras_commander._fast_hdf_typed import attribute_value
    path = _fixture(name)
    datasets = _datasets(path, prefix)
    assert datasets
    compared = 0
    with h5py.File(path, "r") as f:
        for ds_path in datasets:
            reported = native.typed_dataset_attributes(path, ds_path)
            assert reported["capability"]["status"] == "supported", (ds_path, reported["capability"])
            typed = {a["name"]: a for a in reported["value"]}
            attrs = f[ds_path].attrs
            assert sorted(typed) == sorted(attrs)
            for key in attrs:
                _same(attribute_value(typed[key]), attrs[key])
                compared += 1
    assert compared


def test_typed_dataset_attributes_boundaries(native):
    path = _fixture("BaldEagleDamBrk.p07")
    absent = native.typed_dataset_attributes(path, "No/Such/Dataset")
    assert absent["value"] is None and absent["capability"]["status"] == "unavailable"
    with pytest.raises(ValueError) as error:
        native.typed_dataset_attributes(path, "Geometry")
    assert error.value.engine_kind == "invalid_request"
    limited = native.typed_dataset_attributes(path, f"{BASE}/Time", 0)
    assert limited["value"] is None and limited["capability"]["code"] == "resource_limit"


def _h5py_nullpad(raw, width, padding):
    out = []
    for i in range(0, len(raw), width):
        item = raw[i:i + width]
        if padding == "space_pad":
            item = item.rstrip(b" ").ljust(width, b"\0")
        elif padding == "null_terminate":
            cut = item.find(b"\0")
            item = item if cut < 0 else item[:cut].ljust(width, b"\0")
        out.append(item)
    return b"".join(out)


@pytest.mark.parametrize("name", ["BaldEagleDamBrk.p07", "AustinOyster.p03"])
def test_raw_fixed_strings_match_h5py_bytes(native, name):
    path = _fixture(name)
    checked = 0
    with h5py.File(path, "r") as f:
        text = []
        f.visititems(lambda n, o: text.append(n) if isinstance(o, h5py.Dataset) and o.dtype.kind == "S"
                     and o.size * o.dtype.itemsize <= 1 << 20 else None)
        for ds_path in text:
            reported = native.raw_fixed_strings(path, ds_path)
            assert reported["capability"]["status"] == "supported", (ds_path, reported["capability"])
            value = reported["value"]
            ds = f[ds_path]
            assert tuple(value["shape"]) == ds.shape and value["width"] == ds.dtype.itemsize
            assert value["dataspace"] == ("scalar" if ds.shape == () else "simple")
            expected = np.ascontiguousarray(ds[()]).tobytes()
            assert _h5py_nullpad(value["raw_bytes"], value["width"], value["padding"]) == expected
            checked += 1
    assert checked


def test_raw_fixed_strings_refuses_numeric(native):
    path = _fixture("BaldEagleDamBrk.p07")
    reported = native.raw_fixed_strings(path, f"{BASE}/Time")
    assert reported["value"] is None and reported["capability"]["code"] == "encoding"


def test_domain_rule_on_series_and_catalogue(native):
    path = _fixture("AustinOyster.p03")
    mesh = native.mesh_inventory(path)[0]["mesh_name"]
    rules = {v["name"]: (v["domain"], v["domain_rule"], v["capability"]["status"])
             for v in native.mesh_series_inventory(path, mesh)["variables"]}
    assert rules["Depth"] == ("cell", "legacy_exact_name", "supported")
    assert rules["Water Surface"] == ("cell", "legacy_exact_name", "supported")
    assert rules["Face Velocity"] == ("face", "legacy_exact_name", "supported")
    assert rules["Face Shear Stress"] == ("face", "legacy_exact_name", "supported")
    layers = [l for l in native.layer_inventory(path) if l.get("domain_rule") is not None]
    assert {l["domain_rule"] for l in layers} <= {
        "stored_location", "legacy_exact_name", "labelled_summary", "legacy_row_labels",
        "boundary_columns", "unqualified"}
    austin = _fixture("AustinOyster.p01")
    mesh = native.mesh_inventory(austin)[0]["mesh_name"]
    located = [v for v in native.mesh_series_inventory(austin, mesh)["variables"]
               if v["capability"]["status"] == "supported"]
    assert located and {v["domain_rule"] for v in located} == {"stored_location"}
