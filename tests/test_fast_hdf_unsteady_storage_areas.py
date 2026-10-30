"""Unsteady storage-area time series through the engine's identity-checked reader.

The engine serves unsteady storage areas through ``structure_inventory`` /
``read_structure_series`` (not the ``one_d`` structure family used for steady
storage areas). The typed router uses that inventory for membership and reads
the full stored series from it; any selection is then taken from those values.
"""

import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import _fast_hdf_typed as typed
from ras_commander import fast_hdf

FIXTURE = Path(__file__).parent / "rust_engine_bridge" / "fixtures" / "structures" / "good.h5"
GROUP = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Storage Areas"
DATASETS = [
    "Flow",
    "Water Surface",
    "Pool1/Connections to Storage Area",
    "Pool1/Storage Area Variables",
    "Pool2/Storage Area Variables",
]


def test_route_for_unsteady_storage_areas():
    assert typed.route_for(f"/{GROUP}/Pool1/Storage Area Variables") == (
        "unsteady_structure_series", "storage_area", "Pool1", "Storage Area Variables")
    assert typed.route_for(f"/{GROUP}/Water Surface") == (
        "unsteady_structure_series", "storage_area", None, "Water Surface")
    steady = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Storage Areas/Pool1/Flow"
    assert typed.route_for(steady)[:3] == ("structure_series", "storage_area", "steady")


@pytest.fixture
def plan(tmp_path, monkeypatch):
    pytest.importorskip("ras_commander_fast_hdf")
    path = tmp_path / "plan.hdf"
    shutil.copyfile(FIXTURE, path)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    fast_hdf.close_sessions()
    typed.clear_cache()
    yield path
    fast_hdf.close_sessions()
    typed.clear_cache()


@pytest.mark.parametrize("cache", ["0", "persist"])
@pytest.mark.parametrize("name", DATASETS)
def test_required_reads_unsteady_storage_area_series_exactly(plan, monkeypatch, cache, name):
    monkeypatch.setenv("RAS_COMMANDER_HDF_SESSION_CACHE", cache)
    with h5py.File(plan, "r") as hdf, fast_hdf.trace_reads() as trace:
        dataset = hdf[f"{GROUP}/{name}"]
        expected = dataset[()]
        values = fast_hdf.read_typed(dataset)
        rows = fast_hdf.read_typed(dataset, (slice(1, None, 2), slice(None)))
    assert values.dtype == expected.dtype and values.shape == expected.shape
    assert values.tobytes() == expected.tobytes()
    assert np.array_equal(rows, expected[1::2, :])
    backends = {(r["backend"], r["route"]) for r in trace if r["path"] == f"/{GROUP}/{name}"}
    assert backends == {("native-typed", "unsteady_structure_series")}


def test_inventory_contradicting_the_time_axis_is_refused(plan, monkeypatch):
    # A series whose rows contradict the time axis makes the inventory corrupt:
    # required mode refuses, auto mode reads the stored values with h5py.
    with h5py.File(plan, "a") as hdf:
        hdf[f"{GROUP}/Pool1/Short"] = np.zeros((3, 2), dtype="f4")
    name = f"{GROUP}/Pool1/Storage Area Variables"
    with h5py.File(plan, "r") as hdf:
        with pytest.raises(fast_hdf.FastHdfError, match="Typed inventory failed"):
            fast_hdf.read_typed(hdf[name])
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    typed.clear_cache()
    with h5py.File(plan, "r") as hdf, fast_hdf.trace_reads() as trace:
        values = fast_hdf.read_typed(hdf[name])
        assert values.tobytes() == hdf[name][()].tobytes()
    assert ("h5py-fallback", "unsteady_structure_series") in {
        (r["backend"], r["route"]) for r in trace if r["path"] == "/" + name}
