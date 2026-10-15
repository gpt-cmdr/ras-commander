"""Stable compiled-input receipts and external-storage refusal."""

import h5py
import numpy as np
import pytest
from ras_commander import HdfBase


def test_hashes_ignore_compound_padding_and_block_size(tmp_path):
    path = tmp_path / "input.hdf"
    dtype = np.dtype(
        {
            "names": ["x", "label"],
            "formats": ["f8", "S4"],
            "offsets": [0, 16],
            "itemsize": 32,
        }
    )
    values = np.zeros(100, dtype=dtype)
    values["x"] = np.arange(100)
    values["label"] = b"test"
    with h5py.File(path, "w") as h:
        h.create_dataset("Geometry/Table", data=values)
        h.create_dataset("Geometry/Scalar", data=42)
        h.create_dataset("Geometry/Empty", shape=(0,), dtype="f4")
        h["Geometry"].attrs["units"] = np.bytes_("feet")
    small = HdfBase.fingerprint_model_inputs(str(path), block_bytes=1024)
    large = HdfBase.fingerprint_model_inputs(path, block_bytes=65536)
    assert small == large
    assert small["datasets"]["/Geometry/Scalar"]["shape"] == []
    assert small["missing_groups"] == ["/Plan Data"]


def test_string_record_boundaries_affect_hash(tmp_path):
    hashes = []
    for index, values in enumerate([["ab", "c"], ["a", "bc"]]):
        p = tmp_path / f"{index}.hdf"
        with h5py.File(p, "w") as h:
            h.create_dataset("Geometry/Names", data=values, dtype=h5py.string_dtype())
        hashes.append(
            HdfBase.fingerprint_model_inputs(p)["datasets"]["/Geometry/Names"]["sha256"]
        )
    assert hashes[0] != hashes[1]


@pytest.mark.parametrize("kind", ["external", "soft", "cycle", "virtual"])
def test_refuses_nonlocal_or_cyclic_storage(tmp_path, kind):
    p = tmp_path / "input.hdf"
    with h5py.File(p, "w") as h:
        g = h.create_group("Geometry")
        if kind == "external":
            g["other"] = h5py.ExternalLink("forbidden.hdf", "/data")
        elif kind == "soft":
            g["other"] = h5py.SoftLink("/Geometry")
        elif kind == "cycle":
            g["other"] = g
        else:
            layout = h5py.VirtualLayout(shape=(1,), dtype="f8")
            layout[:] = h5py.VirtualSource("forbidden.hdf", "/data", shape=(1,))
            g.create_virtual_dataset("other", layout)
    with pytest.raises(ValueError, match="refuses"):
        HdfBase.fingerprint_model_inputs(p)


@pytest.mark.parametrize("groups", [(), ("Geometry", "Geometry/x"), "Geometry", ("",)])
def test_rejects_invalid_group_selection(tmp_path, groups):
    with pytest.raises(ValueError, match="groups"):
        HdfBase.fingerprint_model_inputs(tmp_path / "missing", groups=groups)


def test_retains_legitimate_hard_link_alias(tmp_path):
    p = tmp_path / "input.hdf"
    with h5py.File(p, "w") as h:
        source = h.create_dataset("Geometry/A", data=[1.0, 2.0])
        h["Geometry/B"] = source
    result = HdfBase.fingerprint_model_inputs(p)
    assert result["aliases"] == {"/Geometry/B": "/Geometry/A"}
    assert set(result["datasets"]) == {"/Geometry/A"}


def test_nested_selection_refuses_external_ancestor_before_lookup(tmp_path):
    p = tmp_path / "input.hdf"
    with h5py.File(p, "w") as h:
        h["Geometry"] = h5py.ExternalLink("forbidden.hdf", "/Geometry")
    with pytest.raises(ValueError, match="refuses non-hard"):
        HdfBase.fingerprint_model_inputs(p, groups=("Geometry/Cells",))
