"""Unit-sensitive classification and compatible logged processing failures."""
import logging
import os
from pathlib import Path

import geopandas as gpd
import h5py
import pandas as pd
import pytest
from pyproj import CRS
from shapely.geometry import box

from ras_commander.hdf import HdfFluvialPluvial, HdfMesh, HdfResultsMesh

LOGGER = "ras_commander.hdf.HdfFluvialPluvial"


@pytest.fixture
def cells_and_results(tmp_path, monkeypatch):
    path = tmp_path / "units.p01.hdf"
    with h5py.File(path, "w"):
        pass
    cells = gpd.GeoDataFrame(
        {"mesh_name": ["mesh"] * 3, "cell_id": [0, 1, 2]},
        geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100), box(500, 0, 600, 100)],
        crs=2271,
    )
    results = pd.DataFrame({
        "mesh_name": ["mesh"] * 3, "cell_id": [0, 1, 2],
        "maximum_water_surface_time": pd.to_datetime(["2000-01-01", "2000-01-02", "2000-01-01"]),
    })
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda *a, **k: cells.copy())
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", lambda *a, **k: results.copy())
    return path, cells


@pytest.mark.parametrize("crs,flip", [(2271, True), (3857, False)])
def test_feet_and_metres_change_actual_classification(cells_and_results, monkeypatch, crs, flip):
    path, cells = cells_and_results
    cells = cells.set_crs(crs, allow_override=True)
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda *a, **k: cells.copy())
    out = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(str(path), min_polygon_area_acres=1)
    assert not out.empty
    assert out.crs == cells.crs
    assert {"classification", "mesh_name", "cell_id", "geometry"} <= set(out.columns)
    expected = {"fluvial": cells.geometry.iloc[0 if flip else 1],
                "pluvial": cells.geometry.iloc[1 if flip else 0],
                "ambiguous": cells.geometry.iloc[2]}
    assert set(out.classification) == set(expected)
    for row in out.itertuples():
        assert row.geometry.equals(expected[row.classification])


@pytest.mark.parametrize("crs", [None, 4326])
def test_missing_or_geographic_crs_retains_documented_warning_skip(cells_and_results, monkeypatch, caplog, crs):
    path, cells = cells_and_results
    cells = cells.set_crs(crs, allow_override=True)
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda *a, **k: cells.copy())
    raw = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path).set_index("classification")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        out = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path, min_polygon_area_acres=1)
    assert not out.empty
    assert "skipped area filter" in caplog.text
    assert out.crs == cells.crs
    assert all(row.geometry.equals(raw.loc[row.classification].geometry) for row in out.itertuples())


def test_unknown_projected_units_discards_completed_unfiltered_geometry(cells_and_results, monkeypatch, caplog):
    path, cells = cells_and_results
    unknown = CRS.from_epsg(3857).to_wkt(version="WKT1_GDAL").replace('UNIT["metre",1', 'UNIT["unknown",1')
    cells = cells.set_crs(unknown, allow_override=True)
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda *a, **k: cells.copy())
    assert not HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path).empty
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        out = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path, min_polygon_area_acres=1)
    assert isinstance(out, gpd.GeoDataFrame) and out.empty
    assert not out.attrs
    error = next(r for r in caplog.records if r.name == LOGGER and r.levelno == logging.ERROR)
    assert error.exc_info
    assert "known projected horizontal CRS units" in error.getMessage()
    assert "stage=acreage filtering" in error.getMessage()
    assert str(path) in error.getMessage()
    assert "min_polygon_area_acres=1" in error.getMessage()
    assert "Fluvial/pluvial polygons:" not in caplog.text


@pytest.mark.parametrize("threshold", [None, 1])
@pytest.mark.parametrize("stage", ["data loading", "adjacency", "dissolve"])
def test_processing_failure_returns_empty_with_context_and_traceback(cells_and_results, monkeypatch, caplog, threshold, stage):
    path, _ = cells_and_results
    def fail(*args, **kwargs):
        raise RuntimeError("controlled processing failure")
    if stage == "data loading":
        monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", fail)
    elif stage == "adjacency":
        monkeypatch.setattr(HdfFluvialPluvial, "_process_cell_adjacencies", fail)
    else:
        monkeypatch.setattr(gpd.GeoDataFrame, "dissolve", fail)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        out = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
            path, delta_t=17, temporal_tolerance_hours=2, min_polygon_area_acres=threshold)
    assert isinstance(out, gpd.GeoDataFrame) and out.empty
    assert not out.attrs
    error = next(r for r in caplog.records if r.name == LOGGER and r.levelno == logging.ERROR)
    assert error.exc_info and error.exc_info[0] is RuntimeError
    message = error.getMessage()
    for text in [str(path), "delta_t=17", "tolerance=2", f"min_polygon_area_acres={threshold}", f"stage={stage}"]:
        assert text in message
    assert "Fluvial/pluvial polygons:" not in caplog.text


def test_input_decorator_validation_still_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        HdfFluvialPluvial.generate_fluvial_pluvial_polygons(tmp_path / "missing.p01.hdf")


def test_real_single_mesh_acreage_matches_independent_unit_control(monkeypatch):
    filename = os.environ.get("RAS_FLUVIAL_REAL_HDF")
    if not filename:
        pytest.skip("Set RAS_FLUVIAL_REAL_HDF to a computed Davis result (read-only)")
    path = Path(filename)
    assert path.is_file()
    cells = HdfMesh.get_mesh_cell_polygons(path)
    results = HdfResultsMesh.get_mesh_max_ws(path)
    cells = cells[cells.mesh_name == "area2"].copy()
    results = results[results.mesh_name == "area2"].copy()
    assert len(cells) > 2000
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda *a, **k: cells.copy())
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", lambda *a, **k: results.copy())
    raw = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path)
    assert not raw.empty
    expected = raw.explode(index_parts=False, ignore_index=True)
    axis = raw.crs.coordinate_system.to_json_dict()["axis"][0]["unit"]
    factor = axis["conversion_factor"] if isinstance(axis, dict) else 1
    small = expected.geometry.area * factor ** 2 / 4046.8564224 < 5
    old = expected.classification.copy()
    expected.loc[small & (old == "fluvial"), "classification"] = "pluvial"
    expected.loc[small & (old == "pluvial"), "classification"] = "fluvial"
    assert (old != expected.classification).sum() == 3
    expected = expected.dissolve(by="classification")
    out = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path, min_polygon_area_acres=5)
    assert not out.empty and out.crs == raw.crs
    assert set(out.classification) == set(expected.index)
    assert all(row.geometry.equals(expected.loc[row.classification].geometry) for row in out.itertuples())
