"""API re-audit contract regressions: stored Location (P2-5) and single-attribute reads (P2-6).

P2-5: the stored ``Location`` rule (main's) decides a mesh series domain even
when the native engine qualifies one, so an invalid or contradictory Location is
refused (or resolved) exactly as on main; required mode raises FastHdfError on
an engine/Location contradiction.

P2-6: readers that need one attribute read only that attribute, so an
unreadable sibling attribute cannot fail a read that main completed. The
unreadable sibling is simulated by making h5py raise for one attribute name.
"""
import h5py
import numpy as np
import pytest

from ras_commander.fast_hdf import FastHdfError
from ras_commander.hdf.HdfLandCover import HdfLandCover
from ras_commander.hdf.HdfPlan import HdfPlan
from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh
from ras_commander.hdf.HdfStorageArea import HdfStorageArea

MODES = ["0", "auto"]

# --- P2-5 ---------------------------------------------------------------------------

BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
AREA = "Area"
SERIES = f"{BASE}/2D Flow Areas/{AREA}"


@pytest.fixture
def series(tmp_path):
    path = tmp_path / "schema.p01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.require_group("Plan Data/Plan Information").attrs["Simulation Start Time"] = "01Jan2024 00:00:00"
        hdf.create_dataset(f"{BASE}/Time", data=np.arange(3) / 24.0)
        hdf.create_dataset(
            f"{BASE}/Time Date Stamp (ms)",
            data=np.array([f"01Jan2024 0{hour}:00:00.000".encode() for hour in range(3)]))
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(AREA.encode(), 2)], dtype=[("Name", "S16"), ("Cell Count", "i4")]))
        hdf.create_dataset(f"Geometry/2D Flow Areas/{AREA}/Cells Center Coordinate", data=np.zeros((4, 2)))
        hdf.create_dataset(f"Geometry/2D Flow Areas/{AREA}/Faces FacePoint Indexes",
                           data=np.zeros((4, 2), dtype=int))
        hdf.require_group(SERIES).create_dataset(
            "Water Surface", data=np.arange(12, dtype=np.float32).reshape(3, 4))
    return path


def _engine_says(monkeypatch, id_dim):
    domain = {"id_dim": id_dim, "domain": id_dim.split("_")[0], "domain_rule": "stored_location",
              "capability": "qualified"}
    monkeypatch.setattr(HdfResultsMesh, "_native_series_domain", staticmethod(lambda dataset: dict(domain)))


def _location(path, value):
    with h5py.File(path, "r+") as hdf:
        # Fixed-length text, as HEC-RAS stores it.
        hdf[f"{SERIES}/Water Surface"].attrs["Location"] = np.bytes_(value) if isinstance(value, bytes) else value


def _read(path):
    return HdfResultsMesh.get_mesh_timeseries(path, AREA, "Water Surface", truncate=False,
                                              include_ghost_cells=True)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("location", [b"", b"Unknown", 1, [b"Cells", b"Cells"], b"\xff"])
def test_invalid_location_refused_although_engine_qualifies_a_domain(series, monkeypatch, mode, location):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    _location(series, location)
    _engine_says(monkeypatch, "cell_id")
    with pytest.raises(ValueError, match="Location"):
        _read(series)


@pytest.mark.parametrize("mode", MODES)
def test_stored_location_wins_over_a_contradicting_engine_domain(series, monkeypatch, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    _location(series, b"Faces")
    _engine_says(monkeypatch, "cell_id")
    assert _read(series).dims == ("time", "face_id")


def test_required_mode_reports_an_engine_location_contradiction(series, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    _location(series, b"Faces")
    _engine_says(monkeypatch, "cell_id")
    with pytest.raises(FastHdfError, match="contradicts the stored"):
        _read(series)


# --- P2-6 ---------------------------------------------------------------------------

UNREADABLE = "Unreadable Sibling"


@pytest.fixture
def unreadable_sibling(monkeypatch):
    original = h5py.AttributeManager.__getitem__

    def getitem(self, name):
        if name == UNREADABLE:
            raise OSError("Unable to read attribute (simulated undecodable sibling)")
        return original(self, name)
    monkeypatch.setattr(h5py.AttributeManager, "__getitem__", getitem)


def _attrs(path, group, **values):
    with h5py.File(path, "a") as hdf:
        target = hdf.require_group(group) if group else hdf
        for name, value in values.items():
            target.attrs[name] = value
        target.attrs[UNREADABLE] = 1


@pytest.mark.parametrize("mode", MODES)
def test_plan_end_time_ignores_unreadable_sibling(tmp_path, monkeypatch, unreadable_sibling, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    path = tmp_path / "plan.p01.hdf"
    _attrs(path, "Plan Data/Plan Information", **{"Simulation End Time": np.bytes_(b"02Jan2024 06:00:00")})
    assert str(HdfPlan.get_plan_end_time(path)) == "2024-01-02 06:00:00"


@pytest.mark.parametrize("mode", MODES)
def test_plan_program_version_ignores_unreadable_sibling(tmp_path, monkeypatch, unreadable_sibling, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    path = tmp_path / "plan.p01.hdf"
    _attrs(path, "Plan Data/Plan Information", **{"Program Version": np.bytes_(b"6.6")})
    with h5py.File(path, "r") as hdf:
        assert HdfPlan._get_plan_hdf_program_version(hdf) == "6.6"


@pytest.mark.parametrize("mode", MODES)
def test_starting_wse_method_ignores_unreadable_sibling(tmp_path, monkeypatch, unreadable_sibling, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    path = tmp_path / "plan.p01.hdf"
    _attrs(path, "Plan Data/Plan Parameters", **{
        "Initial Condition Method": np.bytes_(b"Normal Depth"), "Normal Depth Slope": 0.001})
    _attrs(path, "Plan Data/Plan Information", **{"Flow Regime": np.bytes_(b"Subcritical")})
    result = HdfPlan.get_starting_wse_method(path)
    assert result["method"] == "Normal Depth"
    assert result["slope"] == pytest.approx(0.001)


@pytest.mark.parametrize("mode", MODES)
def test_starting_wse_regime_ignores_unreadable_sibling(tmp_path, monkeypatch, unreadable_sibling, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    path = tmp_path / "plan.p01.hdf"
    _attrs(path, "Plan Data/Plan Information", **{"Flow Regime": np.bytes_(b"Subcritical")})
    result = HdfPlan.get_starting_wse_method(path)
    assert result["regime"] == "Subcritical" and result["method"] == "Unknown"


@pytest.mark.parametrize("mode", MODES)
def test_terrain_path_ignores_unreadable_sibling(tmp_path, monkeypatch, unreadable_sibling, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    path = tmp_path / "model.g01.hdf"
    terrain = tmp_path / "Terrain" / "Terrain.hdf"
    terrain.parent.mkdir()
    terrain.write_bytes(b"")
    _attrs(path, "Geometry", **{"Terrain Filename": np.bytes_(b".\\Terrain\\Terrain.hdf")})
    assert HdfStorageArea.get_terrain_path_from_geom_hdf(path) == terrain


@pytest.mark.parametrize("mode", MODES)
def test_landcover_association_ignores_unreadable_sibling(tmp_path, monkeypatch, unreadable_sibling, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    path = tmp_path / "model.g01.hdf"
    landcover = tmp_path / "LandCover.hdf"
    landcover.write_bytes(b"")
    _attrs(path, "Geometry", **{"Land Cover Filename": np.bytes_(b"LandCover.hdf")})
    assert HdfLandCover.get_landcover_association(path) == landcover.resolve()
