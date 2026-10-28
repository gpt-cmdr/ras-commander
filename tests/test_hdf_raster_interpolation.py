"""Raster interpolation equivalence and bounded-query regression checks."""

import importlib
import os
from pathlib import Path

import numpy as np
import pytest

scipy_interpolate = pytest.importorskip("scipy.interpolate")
from ras_commander.hdf import _raster_interpolation as raster


@pytest.mark.parametrize("method", ["linear", "nearest", "cubic"])
@pytest.mark.parametrize("block_pixels", [1, 17, 262_144])
@pytest.mark.parametrize("fill_value", [-9999.0, np.nan])
def test_blocked_interpolation_matches_griddata(method, block_pixels, fill_value, monkeypatch):
    rng = np.random.default_rng(597)
    points = rng.random((40, 2))
    values = rng.random(40)
    # Include extrapolation, a descending y axis, and a partial final block.
    grid_x = np.linspace(-0.1, 1.1, 31)
    grid_y = np.linspace(1.1, -0.1, 23)
    expected = scipy_interpolate.griddata(
        points, values, np.meshgrid(grid_x, grid_y), method=method, fill_value=fill_value,
    ).astype(np.float32)
    expected[np.isnan(expected)] = fill_value
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", block_pixels)
    actual = raster._interpolate_to_grid(points, values, grid_x, grid_y, method, fill_value)
    assert actual.dtype == np.float32
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize("method", ["linear", "nearest", "cubic"])
def test_nan_values_match_griddata(method, monkeypatch):
    points = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=float)
    values = np.array([np.nan, 1, 2, 3])
    grid = np.linspace(-0.1, 1.1, 7)
    expected = scipy_interpolate.griddata(
        points, values, np.meshgrid(grid, grid), method=method, fill_value=-9999,
    ).astype(np.float32)
    expected[np.isnan(expected)] = -9999
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 5)
    np.testing.assert_array_equal(
        raster._interpolate_to_grid(points, values, grid, grid, method, -9999), expected,
    )


def test_interpolator_built_once_and_queries_bounded_for_wide_grid(monkeypatch):
    calls, sizes = [], []
    original = scipy_interpolate.LinearNDInterpolator

    def recording_interpolator(*args, **kwargs):
        calls.append(1)
        interpolator = original(*args, **kwargs)

        def evaluate(query):
            sizes.append(len(query))
            return interpolator(query)

        return evaluate

    monkeypatch.setattr(scipy_interpolate, "LinearNDInterpolator", recording_interpolator)
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 7)
    points = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=float)
    result = raster._interpolate_to_grid(
        points, np.ones(4), np.linspace(0, 1, 31), np.linspace(1, 0, 3), "linear", -9999,
    )
    assert len(calls) == 1
    assert max(sizes) <= 7
    assert sum(sizes) == result.size == 93
    np.testing.assert_array_equal(result, np.ones((3, 31), dtype=np.float32))


def test_nearest_indices_match_whole_grid_including_ties(monkeypatch):
    from scipy.spatial import cKDTree

    points = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=float)
    grid_x, grid_y = np.linspace(-1, 2, 31), np.linspace(2, -1, 3)
    gx, gy = np.meshgrid(grid_x, grid_y)
    _, expected = cKDTree(points).query(np.column_stack((gx.ravel(), gy.ravel())))
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 7)
    np.testing.assert_array_equal(raster._nearest_grid_indices(points, grid_x, grid_y), expected)


def test_public_max_export_does_not_allocate_whole_grid_coordinates(tmp_path, monkeypatch):
    gpd = pytest.importorskip("geopandas")
    pytest.importorskip("rasterio")
    from ras_commander.hdf import HdfResultsMesh

    points = gpd.points_from_xy([0, 32, 0, 32], [0, 0, 32, 32])
    frame = gpd.GeoDataFrame({"maximum_depth": [1., 2., 3., 4.]}, geometry=points, crs="EPSG:2271")
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_depth", lambda _: frame)
    original = np.meshgrid

    def bounded_meshgrid(x, y, *args, **kwargs):
        assert len(x) * len(y) <= 7, "whole-grid coordinate allocation"
        return original(x, y, *args, **kwargs)

    monkeypatch.setattr(np, "meshgrid", bounded_meshgrid)
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 7)
    source = tmp_path / "example.p01.hdf"
    source.touch()
    HdfResultsMesh.export_max_depth_raster(source, tmp_path / "depth.tif", resolution_m=1)


def test_public_timestep_export_uses_bounded_queries(tmp_path, monkeypatch):
    pytest.importorskip("rasterio")
    # Use the existing synthetic HDF fixture to exercise the real export path.
    from test_hdf_results_mesh import _create_synthetic_depth_results_hdf, MESH_NAME
    from ras_commander.hdf import HdfResultsMesh

    source = tmp_path / "example.p01.hdf"
    _create_synthetic_depth_results_hdf(source)
    original = np.meshgrid

    def bounded_meshgrid(x, y, *args, **kwargs):
        assert len(x) * len(y) <= 7, "whole-grid coordinate allocation"
        return original(x, y, *args, **kwargs)

    monkeypatch.setattr(np, "meshgrid", bounded_meshgrid)
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 7)
    HdfResultsMesh.export_depth_rasters_at_times(
        source, ["01Jan2024 01:00:00"], tmp_path / "rasters", mesh_name=MESH_NAME, resolution=0.1,
    )


@pytest.mark.integration
@pytest.mark.parametrize("method", ["linear", "nearest", "cubic"])
@pytest.mark.parametrize("export_kind", ["max", "timestep"])
def test_real_exports_equal_whole_grid_reference(tmp_path, monkeypatch, method, export_kind):
    rasterio = pytest.importorskip("rasterio")
    from scipy.spatial import cKDTree
    from ras_commander import HdfMesh, HdfResultsMesh

    configured = os.environ.get("RAS_RASTER_TEST_HDF")
    if not configured:
        pytest.skip("Set RAS_RASTER_TEST_HDF to a public computed 2D plan HDF")
    source = Path(configured)
    mesh = HdfMesh.get_mesh_area_names(source)[0]
    centers = HdfMesh.get_mesh_cell_points(source, include_geometry=False)
    resolution = max(np.ptp(centers["x"]), np.ptp(centers["y"])) / 150
    stamp = HdfResultsMesh.get_mesh_timeseries(
        source, mesh, "Water Surface", time_selection=0, spatial_selection=0,
    ).coords["time"].values[0]
    import pandas as pd

    label = pd.Timestamp(stamp)

    def export(folder):
        if export_kind == "max":
            return HdfResultsMesh.export_max_depth_raster(
                source, folder / "depth.tif", resolution_m=resolution, method=method,
            )
        return HdfResultsMesh.export_depth_rasters_at_times(
            source, [label], folder, mesh_name=mesh, resolution=resolution, method=method,
        )[str(label)]

    def whole_grid(points, values, grid_x, grid_y, method, fill_value):
        result = scipy_interpolate.griddata(
            points, values, np.meshgrid(grid_x, grid_y), method=method, fill_value=fill_value,
        ).astype(np.float32)
        result[np.isnan(result)] = fill_value
        return result

    def whole_nearest(points, grid_x, grid_y):
        gx, gy = np.meshgrid(grid_x, grid_y)
        return cKDTree(points).query(np.column_stack((gx.ravel(), gy.ravel())))[1]

    module = importlib.import_module("ras_commander.hdf.HdfResultsMesh")
    with monkeypatch.context() as reference:
        reference.setattr(module, "_interpolate_to_grid", whole_grid)
        reference.setattr(module, "_nearest_grid_indices", whole_nearest)
        expected_path = export(tmp_path / "reference")
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 113)
    actual_path = export(tmp_path / "blocked")
    with rasterio.open(expected_path) as expected, rasterio.open(actual_path) as actual:
        np.testing.assert_array_equal(actual.read(), expected.read())
        np.testing.assert_array_equal(actual.read_masks(), expected.read_masks())
        assert actual.profile == expected.profile
        assert actual.tags() == expected.tags()
        assert actual.overviews(1) == expected.overviews(1)
