"""ras-commander without the optional extension: Python paths work, required rejects.

Run in a clean environment where ras-commander is installed without
ras-commander-fast-hdf and ``RAS_DIST_EXPECT_NO_EXTENSION=1``. Set
``RAS_DIST_FIXTURES`` to exercise a real computed HDF through the Python path.
"""

import importlib.util
import os
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RAS_DIST_EXPECT_NO_EXTENSION") != "1",
                                reason="RAS_DIST_EXPECT_NO_EXTENSION=1 not set")
FIXTURE = (Path(os.environ["RAS_DIST_FIXTURES"]) / "BaldEagleDamBrk.p18.hdf"
           if os.environ.get("RAS_DIST_FIXTURES") else None)


def test_extension_absent_and_import_is_normal():
    assert importlib.util.find_spec("ras_commander_fast_hdf") is None
    import ras_commander
    from ras_commander import fast_hdf
    assert "site-packages" in Path(ras_commander.__file__).resolve().parts
    assert fast_hdf.available() is False


def test_required_native_rejects(monkeypatch):
    from ras_commander import fast_hdf
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with pytest.raises(fast_hdf.FastHdfError, match="unavailable"):
        fast_hdf._native(fast_hdf._mode("auto"))
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF")
    with pytest.raises(fast_hdf.FastHdfError, match="unavailable"):
        fast_hdf._native(fast_hdf._mode("rust"))


def test_python_paths_on_real_fixture(monkeypatch):
    if FIXTURE is None or not FIXTURE.is_file():
        pytest.skip("real fixture unavailable")
    import h5py
    from ras_commander import fast_hdf
    with h5py.File(FIXTURE, "r") as hdf:
        key = "/Geometry/2D Flow Areas/" + next(
            k for k, obj in hdf["Geometry/2D Flow Areas"].items()
            if isinstance(obj, h5py.Group) and "FacePoints Coordinate" in obj
        ) + "/FacePoints Coordinate"
        oracle = hdf[key][()]
    for backend in ("auto", "python"):
        assert np.array_equal(fast_hdf.read_datasets(FIXTURE, [key], backend=backend)[key], oracle)
    with pytest.raises(fast_hdf.FastHdfError):
        fast_hdf.read_datasets(FIXTURE, [key], backend="rust")
    mesh = fast_hdf.mesh_polygons(FIXTURE)  # auto falls back to the Python polygonizer
    assert len(mesh) == 4425 and mesh.crs is not None
    with pytest.raises(fast_hdf.FastHdfError):
        fast_hdf.mesh_polygons(FIXTURE, backend="rust")
