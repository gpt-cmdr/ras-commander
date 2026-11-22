"""Small format controls for native coefficient row keys, not producer qualification."""

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf import HdfStruc


def _write_geometry(path, keys, key_dtype="i4", types=(b"Bridge", b"Bridge", b"Bridge")):
    """Three distinguishable rows, reversed sparse coefficients, table sentinels."""
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Projection"] = CRS.from_epsg(2278).to_wkt()
        group = hdf.create_group("Geometry/Structures")
        group.create_dataset("Attributes", data=np.array(
            [(types[i], b"River", b"Reach", str(i).encode()) for i in range(3)],
            dtype=[("Type", "S16"), ("River", "S16"), ("Reach", "S16"), ("RS", "S16")],
        ))
        group.create_dataset("Centerline Info", data=[[0, 2], [2, 2], [4, 2]])
        group.create_dataset("Centerline Points", data=[
            [0., 0.], [1., 0.], [10., 0.], [11., 0.], [20., 0.], [21., 0.],
        ])
        group.create_dataset("Bridge Coefficient Attributes", data=np.array(
            [(key, 200. + i, 900. + i) for i, key in enumerate(keys)],
            dtype=[("Structure ID", key_dtype), ("Coef A", "f8"), ("Coef B", "f8")],
        ))
        group.create_dataset("Table Info", data=np.array(
            [(701,), (702,), (703,)], dtype=[("Table Sentinel", "i4")],
        ))
    return path


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("as_string", [False, True])
def test_native_zero_key_sparse_join_preserves_all_row_alignment(tmp_path, as_string):
    path = _write_geometry(tmp_path / "native.g01.hdf", [2, 0])
    result = HdfStruc.get_structures(str(path) if as_string else path)
    assert result["Structure ID"].tolist() == [1, 2, 3]
    assert result["RS"].tolist() == ["0", "1", "2"]
    assert result.index.tolist() == [0, 1, 2]
    assert result["Table Sentinel"].tolist() == [701, 702, 703]
    np.testing.assert_allclose(result["Coef A"], [201., np.nan, 200.], equal_nan=True)
    np.testing.assert_allclose(result["Coef B"], [901., np.nan, 900.], equal_nan=True)
    assert [list(line.coords) for line in result.geometry] == [
        [(0., 0.), (1., 0.)], [(10., 0.), (11., 0.)], [(20., 0.), (21., 0.)],
    ]
    assert result.crs.to_epsg() == 2278


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("keys,key_dtype", [
    ([0, 0], "i4"),       # duplicate would multiply the native row
    ([0.5], "f8"),       # fractional key
    ([0.0], "f8"),       # even integral-valued floats are not native integer keys
    ([-1], "i4"),
    ([3], "i4"),          # exactly at the exclusive upper bound
], ids=["duplicate", "fractional", "float-dtype", "negative", "out-of-range"])
def test_invalid_native_coefficient_keys_raise_without_modifying_source(tmp_path, keys, key_dtype):
    path = _write_geometry(tmp_path / "invalid.g01.hdf", keys, key_dtype)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Invalid native Structure ID"):
        HdfStruc.get_structures(path)
    assert path.read_bytes() == before


@pytest.mark.synthetic_hdf_layout
def test_multiple_opening_coefficient_sets_join_first_and_list_all(tmp_path):
    """HEC-RAS stores one set per bridge opening of a Multiple Opening structure;
    openings without their own set use the first. Row 0 here has two sets."""
    path = _write_geometry(
        tmp_path / "multiple_opening.g01.hdf", [0, 0, 2],
        types=(b"Multiple Opening", b"Bridge", b"Bridge"),
    )
    before = path.read_bytes()
    result = HdfStruc.get_structures(path)
    assert result["Structure ID"].tolist() == [1, 2, 3]
    assert result["Table Sentinel"].tolist() == [701, 702, 703]
    np.testing.assert_allclose(result["Coef A"], [200., np.nan, 202.], equal_nan=True)

    sets = HdfStruc.get_bridge_coefficients(path)
    assert sets["Structure ID"].tolist() == [1, 1, 3]
    assert sets["Native Structure ID"].tolist() == [0, 0, 2]
    assert sets["Coefficient Set"].tolist() == [1, 2, 1]
    assert sets["Type"].tolist() == ["Multiple Opening", "Multiple Opening", "Bridge"]
    np.testing.assert_allclose(sets["Coef A"], [200., 201., 202.])
    assert path.read_bytes() == before


@pytest.mark.synthetic_hdf_layout
def test_repeated_coefficient_key_on_a_single_bridge_still_raises(tmp_path):
    path = _write_geometry(
        tmp_path / "repeat.g01.hdf", [1, 1],
        types=(b"Multiple Opening", b"Bridge", b"Bridge"),
    )
    with pytest.raises(ValueError, match="only a Multiple Opening structure"):
        HdfStruc.get_structures(path)
    with pytest.raises(ValueError, match="only a Multiple Opening structure"):
        HdfStruc.get_bridge_coefficients(path)


@pytest.mark.synthetic_hdf_layout
def test_bridge_coefficients_absent_returns_empty(tmp_path):
    path = tmp_path / "none.g01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Geometry/Structures").create_dataset("Attributes", data=np.array(
            [(b"Bridge",)], dtype=[("Type", "S16")]))
    assert HdfStruc.get_bridge_coefficients(path).empty
