"""PY-ROUTE-3 review P3-B: ``stored_family_index`` failures reach refusals and the trace.

One virtual ``Variables`` dataset in a copy of the ``00-LandCover`` sidecar makes
the engine fail the whole ``land_cover`` family (and the families sharing its
inventory walk), so the index lists none of its datasets. Before PY-ROUTE-3 the
router dropped those failures and a sibling numeric compound was refused with a
bare "no typed engine route". The refusal and the trace now carry the engine's
family failure; auto still returns the exact h5py values. The source fixture is
never modified (a copy in ``tmp_path``).

Gate: ``RAS_ROUTE2_FIXTURES`` (must list ``00-LandCover``).
"""
import json
import os
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

MANIFEST = os.environ.get("RAS_ROUTE2_FIXTURES")
FIXTURES = ({f["name"]: f["path"] for f in json.loads(Path(MANIFEST).read_text())["fixtures"]}
            if MANIFEST else {})
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE2_FIXTURES to the PY-ROUTE-2 real-fixture JSON manifest")


@pytest.fixture
def virtual_sidecar(tmp_path):
    native = pytest.importorskip("ras_commander_fast_hdf")
    assert native.API_VERSION == 11
    source = FIXTURES.get("00-LandCover")
    if source is None:
        pytest.skip("00-LandCover not in manifest")
    values = tmp_path / "variables-source.h5"
    copy = tmp_path / "00-LandCover.virtual-variables.hdf"
    shutil.copyfile(source, copy)
    with h5py.File(source, "r") as f:
        data = f["Variables"][()]
        attrs = {k: f["Variables"].attrs[k] for k in f["Variables"].attrs}
    with h5py.File(values, "w") as f:
        f.create_dataset("Variables", data=data)
    with h5py.File(copy, "r+", libver=("earliest", "latest")) as f:
        del f["Variables"]
        layout = h5py.VirtualLayout(shape=data.shape, dtype=data.dtype)
        layout[:] = h5py.VirtualSource(str(values), "Variables", shape=data.shape)
        ds = f.create_virtual_dataset("Variables", layout)
        for k, v in attrs.items():
            ds.attrs[k] = v
    return native, str(copy)


def test_family_failure_is_reported_not_dropped(virtual_sidecar, monkeypatch):
    native, path = virtual_sidecar
    index = native.stored_family_index(path)
    failed = {f["owner"] for f in index["failures"]}
    assert "land_cover" in failed
    assert not [d for d in index["datasets"] if d["owner"] == "land_cover"]
    from ras_commander import fast_hdf
    fast_hdf.close_sessions()
    with h5py.File(path, "r") as f:
        expected = f["Raster Map"][()]
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
        with pytest.raises(fast_hdf.FastHdfError) as error:
            fast_hdf.read_typed(f["Raster Map"])
        message = str(error.value)
        assert "numeric compound has no typed engine route" in message
        assert "engine stored_family_index failures: " in message and "land_cover" in message
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
        with fast_hdf.trace_reads() as trace:
            actual = fast_hdf.read_typed(f["Raster Map"])
        assert actual.dtype == expected.dtype and actual.tobytes() == expected.tobytes()
        diagnostics = [r for r in trace if r["backend"] == "diagnostic"]
        assert diagnostics and "land_cover" in diagnostics[0]["detail"]
        assert [r["backend"] for r in trace if r["backend"] != "diagnostic"] == ["h5py-fallback"]
        assert np.array_equal(actual, expected)
