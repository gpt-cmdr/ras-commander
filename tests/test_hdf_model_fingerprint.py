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



def test_dataset_receipts_localize_exact_center_and_face_changes(tmp_path):
    path = tmp_path / "components.g01.hdf"
    root = "/Geometry/2D Flow Areas/Mesh"
    centers = root + "/Cells Center Coordinate"
    faces = root + "/Faces Cell Indexes"
    properties = root + "/Faces Area Elevation Values"
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(centers, data=np.array([[1.0, 2.0], [3.0, 4.0]]))
        hdf.create_dataset(faces, data=np.array([[0, -1], [0, 1]], dtype="i4"))
        hdf.create_dataset(properties, data=np.array([[0.0, 0.25]]))
    before_bytes = path.read_bytes()
    before = HdfBase.fingerprint_model_inputs(path)
    assert path.read_bytes() == before_bytes

    with h5py.File(path, "r+") as hdf:
        hdf[centers][0, 0] = np.nextafter(1.0, 2.0)
    after_center = HdfBase.fingerprint_model_inputs(path)
    changed = {
        name for name, record in before["datasets"].items()
        if record != after_center["datasets"][name]
    }
    assert changed == {centers}

    with h5py.File(path, "r+") as hdf:
        hdf[faces][0, 1] = -2
    after_face = HdfBase.fingerprint_model_inputs(path)
    changed = {
        name for name, record in after_center["datasets"].items()
        if record != after_face["datasets"][name]
    }
    assert changed == {faces}
    assert after_face["datasets"][properties] == before["datasets"][properties]


def test_dtype_and_shape_are_part_of_dataset_receipt_identity(tmp_path):
    path = tmp_path / "identity.hdf"
    name = "/Geometry/Values"
    records = []
    for values in (
        np.zeros(4, dtype="i4"),
        np.zeros(4, dtype="f4"),
        np.zeros((2, 2), dtype="f4"),
    ):
        with h5py.File(path, "w") as hdf:
            hdf.create_dataset(name, data=values)
        records.append(HdfBase.fingerprint_model_inputs(path)["datasets"][name])
    # These arrays have equal raw bytes; compare complete receipt identities.
    assert records[0]["dtype"] != records[1]["dtype"]
    assert records[1]["shape"] != records[2]["shape"]
    assert records[0] != records[1] != records[2]


def test_missing_selected_topology_is_reported_separately_from_empty(tmp_path):
    path = tmp_path / "missing.hdf"
    root = "/Geometry/2D Flow Areas/Mesh"
    with h5py.File(path, "w") as hdf:
        hdf.create_group(root)
    empty = HdfBase.fingerprint_model_inputs(path, groups=(root,))
    assert empty["groups"] == {root: {"attributes": {}}}
    assert empty["datasets"] == {}
    assert empty["missing_groups"] == []
    with h5py.File(path, "r+") as hdf:
        del hdf[root]
    missing = HdfBase.fingerprint_model_inputs(path, groups=(root,))
    assert missing["groups"] == {}
    assert missing["datasets"] == {}
    assert missing["missing_groups"] == [root]
