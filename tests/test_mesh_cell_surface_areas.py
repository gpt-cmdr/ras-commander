"""Native area values retain precision and native IDs, including ghost rows."""

import hashlib

import h5py
import numpy as np
import pytest

from ras_commander import HdfMesh


def fixture(path, values):
    with h5py.File(path, "w") as h:
        g = h.create_group("Geometry/2D Flow Areas")
        g.create_dataset(
            "Attributes", data=np.array([(b"Area",)], dtype=[("Name", "S16")])
        )
        g.create_dataset("Area/Cells Surface Area", data=values)


@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_native_surface_areas_preserve_precision_and_source(tmp_path, dtype):
    p = tmp_path / "A.g01.hdf"
    fixture(p, np.array([12.5, 3.25, 0], dtype=dtype))
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    result = HdfMesh.get_mesh_cell_surface_areas(str(p))
    assert result.cell_id.tolist() == [0, 1, 2]
    assert result.surface_area.dtype == np.dtype(dtype)
    assert result.surface_area.tolist() == [12.5, 3.25, 0]
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "values", [[np.nan], [-1], [[1.0, 2.0]], np.array([1], dtype="int32")]
)
def test_invalid_native_surface_area_fails_closed(tmp_path, values):
    p = tmp_path / "A.g01.hdf"
    fixture(p, np.asarray(values))
    with pytest.raises(ValueError, match="Invalid native cell surface areas"):
        HdfMesh.get_mesh_cell_surface_areas(p)
