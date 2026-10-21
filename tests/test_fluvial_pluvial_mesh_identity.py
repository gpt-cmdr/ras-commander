"""Mesh identity regressions on real read-only results and small edge controls."""
from collections import defaultdict
from itertools import combinations
import logging
import os
from pathlib import Path

import geopandas as gpd
import h5py
import pandas as pd
import pytest
from shapely.geometry import box

from ras_commander.hdf import HdfFluvialPluvial, HdfMesh, HdfResultsMesh

LOGGER = "ras_commander.hdf.HdfFluvialPluvial"


@pytest.mark.parametrize("method,kwargs", [
    ("generate_fluvial_pluvial_polygons", {}),
    ("generate_fluvial_pluvial_polygons", {"min_polygon_area_acres": 1}),
    ("calculate_fluvial_pluvial_boundary", {"min_line_length": 3}),
])
def test_processing_failure_is_logged_empty_not_raised(tmp_path, monkeypatch, caplog, method, kwargs):
    path = tmp_path / "failure.p01.hdf"
    with h5py.File(path, "w"):
        pass
    def fail(*args, **kwargs):
        raise RuntimeError("controlled mesh read failure")
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", fail)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        out = getattr(HdfFluvialPluvial, method)(path, delta_t=17, **kwargs)
    assert isinstance(out, gpd.GeoDataFrame) and out.empty
    assert not out.attrs
    error = next(r for r in caplog.records if r.name == LOGGER and r.levelno == logging.ERROR)
    assert error.exc_info and error.exc_info[0] is RuntimeError
    for text in [str(path), "delta_t=17", "stage=data loading"]:
        assert text in error.getMessage()
    for key, value in kwargs.items():
        assert f"{key}={value}" in error.getMessage()
    assert not any(r.levelno == logging.INFO and "Fluvial/pluvial" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("method", ["generate_fluvial_pluvial_polygons", "calculate_fluvial_pluvial_boundary"])
def test_decorator_validation_still_raises(tmp_path, method):
    with pytest.raises(FileNotFoundError):
        getattr(HdfFluvialPluvial, method)(tmp_path / "missing.p01.hdf")


def test_coincident_mesh_coordinates_do_not_create_cross_mesh_adjacency():
    cells = gpd.GeoDataFrame(
        {"mesh_name": ["A", "A", "B", "B"], "cell_id": [0, 1, 0, 1]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)] * 2, crs=3857)
    adjacency, _ = HdfFluvialPluvial._process_cell_adjacencies(cells)
    assert set(adjacency) == {("A", 0), ("A", 1), ("B", 0), ("B", 1)}
    for key, neighbors in adjacency.items():
        assert neighbors == [(key[0], 1 - key[1])]


@pytest.fixture(scope="module")
def real_davis():
    filename = os.environ.get("RAS_FLUVIAL_REAL_HDF")
    if not filename:
        pytest.skip("Set RAS_FLUVIAL_REAL_HDF to a computed Davis result (read-only)")
    path = Path(filename)
    assert path.is_file()
    cells = HdfMesh.get_mesh_cell_polygons(path)
    results = HdfResultsMesh.get_mesh_max_ws(path)
    assert len(cells) == 2716
    assert set(cells.mesh_name) == {"DS Channel", "area2"}
    assert cells.cell_id.duplicated().any()
    assert not cells.duplicated(["mesh_name", "cell_id"]).any()
    return path, cells, results


@pytest.mark.parametrize("threshold", [None, 0])
def test_full_davis_is_nonempty_complete_and_equals_separate_meshes(real_davis, monkeypatch, caplog, threshold):
    path, cells, results = real_davis
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        combined = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path, min_polygon_area_acres=threshold)
    assert not combined.empty, "An empty failure return is not successful Davis validation"
    assert combined.crs == cells.crs
    assert set(combined.mesh_name) == set(cells.mesh_name)
    assert not combined.duplicated(["mesh_name", "classification"]).any()
    assert len(combined) == 4
    assert set(combined[combined.mesh_name == "area2"].classification) == {"fluvial", "pluvial", "ambiguous"}
    for mesh_name in sorted(cells.mesh_name.unique()):
        local_cells = cells[cells.mesh_name == mesh_name].copy()
        local_results = results[results.mesh_name == mesh_name].copy()
        with monkeypatch.context() as patch:
            patch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda *a, **k: local_cells.copy())
            patch.setattr(HdfResultsMesh, "get_mesh_max_ws", lambda *a, **k: local_results.copy())
            separate = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path, min_polygon_area_acres=threshold)
        assert not separate.empty
        actual = combined[combined.mesh_name == mesh_name].set_index("classification")
        assert set(actual.index) == set(separate.classification)
        assert actual.geometry.union_all().equals(local_cells.geometry.union_all())
        for row in separate.itertuples():
            assert row.geometry.equals(actual.loc[row.classification].geometry)
    assert not [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.ERROR]


@pytest.mark.parametrize("delta_t,expected_count", [(12, 36), (0.1, 2179)])
def test_real_boundary_matches_independent_shared_edge_time_oracle(real_davis, delta_t, expected_count, caplog):
    path, cells, results = real_davis
    times = results.set_index(["mesh_name", "cell_id"])["maximum_water_surface_time"].map(pd.Timestamp).to_dict()
    edges = defaultdict(set)
    for row in cells.itertuples():
        coords = list(row.geometry.exterior.coords)
        for a, b in zip(coords, coords[1:]):
            key = (row.mesh_name, tuple(sorted((tuple(round(x, 8) for x in a), tuple(round(x, 8) for x in b)))))
            edges[key].add((row.mesh_name, row.cell_id))
    expected = []
    for (_, edge), identities in edges.items():
        for a, b in combinations(identities, 2):
            if pd.notna(times[a]) and pd.notna(times[b]) and abs((times[a] - times[b]).total_seconds()) >= delta_t * 3600:
                expected.append(edge)
    assert len(expected) == expected_count
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        actual = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(path, delta_t=delta_t)
    assert not actual.empty and len(actual) == expected_count
    assert actual.crs == cells.crs
    # Lines now carry exact stored face coordinates; the oracle rounds to 8 dp.
    rounded = [tuple(sorted(tuple(round(x, 8) for x in c) for c in g.coords)) for g in actual.geometry]
    assert sorted(rounded) == sorted(expected)
    assert not [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.ERROR]
