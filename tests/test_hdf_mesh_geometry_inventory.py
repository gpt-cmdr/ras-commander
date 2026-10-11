"""Exact-byte and bounded-read contracts; no native engine is executed."""

import hashlib

import h5py
import numpy as np
import pytest

from ras_commander import HdfMesh
from ras_commander.schemas import DATAFRAME_SCHEMAS

BASE = "Geometry/2D Flow Areas"


def fixture_hdf(path, values, *, compression=None):
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group(BASE)
        group.create_dataset(
            "area/Cells Center Coordinate", data=values, compression=compression
        )
    return path


def test_read_slabs_really_remain_inside_declared_budget(tmp_path, monkeypatch):
    values = np.arange(90, dtype="<i4").reshape(30, 3)
    path = fixture_hdf(tmp_path / "bounded.hdf", values, compression="gzip")
    observed = []
    original = h5py.Dataset.__getitem__

    def checked_read(dataset, selection):
        result = original(dataset, selection)
        observed.append(result.nbytes)
        return result

    monkeypatch.setattr(h5py.Dataset, "__getitem__", checked_read)
    result = HdfMesh.get_mesh_geometry_inventory(path, max_chunk_bytes=25)
    assert observed and max(observed) <= 25 and sum(observed) == values.nbytes
    assert result.iloc[0].sha256 == hashlib.sha256(values.tobytes()).hexdigest()


def test_enum_meaning_is_part_of_dtype_identity(tmp_path):
    paths = [tmp_path / "first.hdf", tmp_path / "second.hdf"]
    for path, meanings in zip(paths, ({"dry": 0, "wet": 1}, {"dry": 1, "wet": 0})):
        with h5py.File(path, "w") as hdf:
            hdf.create_dataset(
                BASE + "/enum",
                data=np.array([0, 1], dtype="<i4"),
                dtype=h5py.enum_dtype(meanings, basetype="<i4"),
            )
    first, second = [HdfMesh.get_mesh_geometry_inventory(p).iloc[0] for p in paths]
    assert first.sha256 == second.sha256 and first["dtype"] != second["dtype"]


def test_storage_layout_does_not_change_native_array_identity(tmp_path):
    values = np.arange(84, dtype="<f8").reshape(42, 2)
    first = fixture_hdf(tmp_path / "before.g01.hdf", values)
    second = fixture_hdf(tmp_path / "after.p01.hdf", values, compression="gzip")
    before = hashlib.sha256(first.read_bytes()).hexdigest()
    a = HdfMesh.get_mesh_geometry_inventory(str(first), max_chunk_bytes=32)
    b = HdfMesh.get_mesh_geometry_inventory(second, max_chunk_bytes=48)
    assert a.to_dict("records") == b.to_dict("records")
    assert a.iloc[0].sha256 == hashlib.sha256(values.tobytes()).hexdigest()
    assert a.iloc[0]["bytes"] == values.nbytes
    assert a.iloc[0]["shape"] == values.shape
    assert hashlib.sha256(first.read_bytes()).hexdigest() == before
    columns = [
        v["name"] for v in DATAFRAME_SCHEMAS["mesh_geometry_inventory"]["columns"]
    ]
    assert a.columns.tolist() == columns


def test_signed_zero_and_nan_payloads_are_not_float_equality(tmp_path):
    values = np.array([0, 0x8000000000000000, 0x7FF8000000000001], dtype="<u8").view(
        "<f8"
    )
    first = fixture_hdf(tmp_path / "before.hdf", values)
    values[1] = 0.0
    second = fixture_hdf(tmp_path / "after.hdf", values)
    assert (
        HdfMesh.get_mesh_geometry_inventory(first).iloc[0].sha256
        != HdfMesh.get_mesh_geometry_inventory(second).iloc[0].sha256
    )


def test_shape_and_dtype_prevent_same_byte_false_equivalence(tmp_path):
    a = fixture_hdf(tmp_path / "a.hdf", np.arange(8, dtype="<i4").reshape(4, 2))
    b = fixture_hdf(tmp_path / "b.hdf", np.arange(8, dtype="<i4").reshape(2, 4))
    c = fixture_hdf(
        tmp_path / "c.hdf", np.arange(8, dtype="<i4").view("<f4").reshape(4, 2)
    )
    records = [HdfMesh.get_mesh_geometry_inventory(p).iloc[0] for p in (a, b, c)]
    assert len({r.sha256 for r in records}) == 1
    assert records[0]["shape"] != records[1]["shape"]
    assert records[0]["dtype"] != records[2]["dtype"]


def test_scalar_preserves_declared_native_byte_order(tmp_path):
    values = np.array(0x01020304, dtype=">i4")
    path = fixture_hdf(tmp_path / "big-endian-scalar.hdf", values)
    row = HdfMesh.get_mesh_geometry_inventory(path).iloc[0]
    assert row["shape"] == () and row["bytes"] == 4
    assert row.sha256 == hashlib.sha256(b"\x01\x02\x03\x04").hexdigest()
    assert ">i4" in row["dtype"]


def test_fixed_compound_scalar_and_empty_dataset_are_inventoried(tmp_path):
    path = tmp_path / "compound.hdf"
    values = np.array([(b"area", 4)], dtype=[("Name", "S8"), ("Cell Count", "<i4")])
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group(BASE)
        group.create_dataset("Attributes", data=values)
        group.create_dataset("scalar", data=np.array(7, dtype="<i4"))
        group.create_dataset("empty", shape=(0, 2), dtype="<f8")
    rows = HdfMesh.get_mesh_geometry_inventory(path).set_index("dataset_path")
    assert (
        rows.loc[BASE + "/Attributes", "sha256"]
        == hashlib.sha256(values.tobytes()).hexdigest()
    )
    assert rows.loc[BASE + "/scalar", "shape"] == ()
    assert rows.loc[BASE + "/empty", "sha256"] == hashlib.sha256(b"").hexdigest()
    assert rows.loc[BASE + "/empty", "bytes"] == 0


def test_result_additions_can_be_excluded_using_complete_reference_paths(tmp_path):
    first = fixture_hdf(tmp_path / "before.hdf", np.arange(4, dtype="<i4"))
    second = fixture_hdf(tmp_path / "after.hdf", np.arange(4, dtype="<i4"))
    with h5py.File(second, "a") as hdf:
        hdf.create_dataset(
            BASE + "/area/Cells Volume Elevation Info", data=np.arange(2)
        )
    reference = HdfMesh.get_mesh_geometry_inventory(first)
    candidate = HdfMesh.get_mesh_geometry_inventory(
        second, dataset_paths=reference.dataset_path.tolist()
    )
    assert candidate.to_dict("records") == reference.to_dict("records")
    assert len(HdfMesh.get_mesh_geometry_inventory(second)) == 2


@pytest.mark.parametrize(
    "selected",
    [
        [],
        [BASE + "/absent"],
        ["/outside"],
        [1],
        "Attributes",
        [BASE + "/area/Cells Center Coordinate"] * 2,
    ],
)
def test_unsafe_or_incomplete_requested_path_inventory_fails(tmp_path, selected):
    path = fixture_hdf(tmp_path / "model.hdf", np.arange(4))
    with pytest.raises(ValueError):
        HdfMesh.get_mesh_geometry_inventory(path, dataset_paths=selected)


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_budget_fails(tmp_path, budget):
    path = fixture_hdf(tmp_path / "model.hdf", np.arange(4))
    with pytest.raises(ValueError, match="positive integer"):
        HdfMesh.get_mesh_geometry_inventory(path, max_chunk_bytes=budget)


def test_indivisible_native_row_cannot_exceed_read_budget(tmp_path):
    path = fixture_hdf(tmp_path / "model.hdf", np.arange(4, dtype="<f8").reshape(2, 2))
    with pytest.raises(ValueError, match="row exceeds"):
        HdfMesh.get_mesh_geometry_inventory(path, max_chunk_bytes=15)


def test_variable_width_native_bytes_are_not_silently_accepted(tmp_path):
    path = tmp_path / "variable.hdf"
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group(BASE)
        group.create_dataset("variable", data=["text"], dtype=h5py.string_dtype())
    with pytest.raises(ValueError, match="fixed-width"):
        HdfMesh.get_mesh_geometry_inventory(path)


@pytest.mark.parametrize("link_kind", ["soft", "external", "cycle", "base"])
def test_links_cannot_escape_or_hide_native_dataset_inventory(tmp_path, link_kind):
    path = tmp_path / "linked.hdf"
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group(BASE)
        group.create_dataset("values", data=[1])
        if link_kind == "soft":
            group["alias"] = h5py.SoftLink(BASE + "/values")
        elif link_kind == "external":
            group["alias"] = h5py.ExternalLink("missing-parent-result.hdf", "/Geometry")
        elif link_kind == "cycle":
            group["alias"] = group
        else:
            del hdf["Geometry"]
            hdf["Geometry"] = h5py.ExternalLink(
                "missing-parent-result.hdf", "/Geometry"
            )
    with pytest.raises(ValueError, match="link"):
        HdfMesh.get_mesh_geometry_inventory(path)


@pytest.mark.parametrize("empty_group", [True, False])
def test_missing_native_inventory_cannot_vacuously_pass(tmp_path, empty_group):
    path = tmp_path / "empty.hdf"
    with h5py.File(path, "w") as hdf:
        if empty_group:
            hdf.create_group(BASE)
    with pytest.raises(ValueError):
        HdfMesh.get_mesh_geometry_inventory(path)
