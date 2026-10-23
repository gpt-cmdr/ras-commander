"""Current canonical geometry links replace stale selected-area caches only."""

import h5py
import numpy as np
import pytest

from ras_commander import RasMap


@pytest.fixture
def carrier(tmp_path):
    path = tmp_path / "Model.g02.hdf"
    for name in ("Terrain", "LandCover"):
        (tmp_path / f"{name}.hdf").write_bytes(b"associated input identity")
    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Terrain Filename"] = np.bytes_(b"Terrain.hdf")
        geometry.attrs["Terrain Layername"] = np.bytes_(b"ChildTerrain")
        geometry.attrs["Land Cover Filename"] = np.bytes_(b"LandCover.hdf")
        geometry.create_dataset(
            "Land Cover (Manning's n)/Calibration Table", data=[0.02, 0.04]
        )
        for name in ("Selected", "Other"):
            area = geometry.create_group("2D Flow Areas/" + name)
            area.attrs["Terrain Filename"] = np.bytes_(b"missing/ParentTerrain.hdf")
            area.attrs["Land Cover Filename"] = np.bytes_(
                b"missing/ParentLandCover.hdf"
            )
            area.attrs["Land Cover Layername"] = np.bytes_(b"StaleLayer")
            area.attrs["Percent Impervious Filename"] = np.bytes_(b"area-only.hdf")
            area.create_dataset("Cells Center Coordinate", data=[[1.0, 2.0]])
    return path


def test_selected_cache_sync_preserves_other_mesh_and_calibration(carrier):
    original = carrier.read_bytes()
    plan = RasMap.plan_geometry_area_association_sync(carrier, ["Selected"])
    assert carrier.read_bytes() == original
    assert len(plan["changes"]) == 4
    receipt = RasMap.apply_geometry_area_association_sync(plan)
    assert receipt["status"] == "applied"
    assert carrier.with_suffix(".hdf.bak").read_bytes() == original
    with h5py.File(carrier, "r") as hdf:
        area = hdf["Geometry/2D Flow Areas/Selected"]
        assert area.attrs["Terrain Filename"] == b"Terrain.hdf"
        assert area.attrs["Terrain Layername"] == b"ChildTerrain"
        assert area.attrs["Land Cover Filename"] == b"LandCover.hdf"
        assert "Land Cover Layername" not in area.attrs
        assert area.attrs["Percent Impervious Filename"] == b"area-only.hdf"
        assert (
            hdf["Geometry/2D Flow Areas/Other"].attrs["Terrain Filename"]
            == b"missing/ParentTerrain.hdf"
        )
        np.testing.assert_array_equal(area["Cells Center Coordinate"], [[1, 2]])
        np.testing.assert_array_equal(
            hdf["Geometry/Land Cover (Manning's n)/Calibration Table"], [0.02, 0.04]
        )
    again = RasMap.plan_geometry_area_association_sync(carrier, ["Selected"])
    before = carrier.read_bytes()
    assert not again["changes"]
    assert RasMap.apply_geometry_area_association_sync(again)["status"] == "unchanged"
    assert carrier.read_bytes() == before


def test_missing_current_input_and_stale_plan_do_not_mutate(carrier):
    original = carrier.read_bytes()
    plan = RasMap.plan_geometry_area_association_sync(carrier, ["Selected"])
    with h5py.File(carrier, "r+") as hdf:
        hdf["Geometry"].attrs["Terrain Filename"] = np.bytes_(b"missing-current.hdf")
    changed = carrier.read_bytes()
    with pytest.raises(
        FileNotFoundError, match="Current geometry association is missing"
    ):
        RasMap.plan_geometry_area_association_sync(carrier, ["Selected"])
    assert carrier.read_bytes() == changed
    carrier.write_bytes(original)
    with h5py.File(carrier, "r+") as hdf:
        hdf.attrs["new metadata"] = 1
    changed = carrier.read_bytes()
    with pytest.raises(RuntimeError, match="changed after planning"):
        RasMap.apply_geometry_area_association_sync(plan)
    assert carrier.read_bytes() == changed


@pytest.mark.parametrize(
    "family", ["Infiltration", "Sediment Bed Material", "Percent Impervious"]
)
def test_other_declared_canonical_families_are_synchronized(carrier, family):
    sidecar = carrier.parent / "Classification.hdf"
    sidecar.write_bytes(b"current classification")
    with h5py.File(carrier, "r+") as hdf:
        geometry = hdf["Geometry"]
        geometry.attrs[family + " Filename"] = np.bytes_(b"Classification.hdf")
        geometry.attrs[family + " Layername"] = np.bytes_(b"CurrentLayer")
        area = geometry["2D Flow Areas/Selected"]
        area.attrs[family + " Filename"] = np.bytes_(b"missing-parent.hdf")
        area.attrs[family + " Layername"] = np.bytes_(b"OldLayer")
    plan = RasMap.plan_geometry_area_association_sync(carrier, ["Selected"])
    assert RasMap.apply_geometry_area_association_sync(plan)["status"] == "applied"
    with h5py.File(carrier, "r") as hdf:
        area = hdf["Geometry/2D Flow Areas/Selected"]
        assert area.attrs[family + " Filename"] == b"Classification.hdf"
        assert area.attrs[family + " Layername"] == b"CurrentLayer"


@pytest.mark.parametrize(
    "names", [[], "Selected", ["Selected", "Selected"], ["Missing"]]
)
def test_invalid_mesh_selection_does_not_mutate(carrier, names):
    before = carrier.read_bytes()
    with pytest.raises(ValueError):
        RasMap.plan_geometry_area_association_sync(carrier, names)
    assert carrier.read_bytes() == before


@pytest.mark.parametrize("suffix", ["p01", "u01", "o01"])
def test_uncomputed_plan_result_carrier_is_not_geometry(carrier, suffix):
    other = carrier.with_name(f"Model.{suffix}.hdf")
    other.write_bytes(carrier.read_bytes())
    before = other.read_bytes()
    with pytest.raises(ValueError, match="geometry-only"):
        RasMap.plan_geometry_area_association_sync(other)
    assert other.read_bytes() == before


def test_event_conditions_in_geometry_filename_are_rejected(carrier):
    with h5py.File(carrier, "r+") as hdf:
        hdf.create_group("Event Conditions")
    with pytest.raises(ValueError, match="geometry-only"):
        RasMap.plan_geometry_area_association_sync(carrier)
