"""Per-call triangulation ownership and value-isolation regressions."""

import numpy as np
import pytest

pytest.importorskip("scipy")
from ras_commander.hdf._raster_interpolation import _interpolate_to_grid


@pytest.mark.parametrize("method", ["linear", "cubic"])
def test_reused_geometry_retains_each_timestamps_values(method):
    from scipy.spatial import Delaunay

    rng = np.random.default_rng(719)
    points = rng.random((70, 2))
    geometry = Delaunay(points)
    before = geometry.points.copy(), geometry.simplices.copy()
    grid_x, grid_y = np.linspace(-.1, 1.1, 31), np.linspace(1.1, -.1, 23)
    for values in [rng.random(70), np.zeros(70), rng.random(70) * 10]:
        fresh = _interpolate_to_grid(points, values, grid_x, grid_y, method, -9999)
        reused = _interpolate_to_grid(
            points, values, grid_x, grid_y, method, -9999, triangulation=geometry,
        )
        np.testing.assert_array_equal(fresh, reused)
    np.testing.assert_array_equal(geometry.points, before[0])
    np.testing.assert_array_equal(geometry.simplices, before[1])


@pytest.mark.parametrize("method", ["linear", "cubic", "nearest"])
@pytest.mark.parametrize("timestamps", [1, 2])
def test_triangulation_owned_by_one_export_call(tmp_path, monkeypatch, method, timestamps):
    import scipy.spatial
    rasterio = pytest.importorskip("rasterio")
    from ras_commander import HdfResultsMesh
    from test_hdf_results_mesh import _create_synthetic_depth_results_hdf, MESH_NAME

    source = tmp_path / "example.p01.hdf"
    _create_synthetic_depth_results_hdf(source)
    original = scipy.spatial.Delaunay
    constructions = []

    def record(points):
        geometry = original(points)
        constructions.append(geometry)
        return geometry

    monkeypatch.setattr(scipy.spatial, "Delaunay", record)
    labels = ["01Jan2024 00:00:00", "01Jan2024 01:00:00"][:timestamps]
    for call in range(2):
        outputs = HdfResultsMesh.export_depth_rasters_at_times(
            source, labels, tmp_path / f"call-{call}", mesh_name=MESH_NAME,
            resolution=.1, method=method,
        )
        if timestamps == 2:
            with rasterio.open(outputs[labels[0]]) as first, rasterio.open(outputs[labels[1]]) as second:
                assert np.any(first.read() != second.read())
    if timestamps == 2 and method != "nearest":
        assert len(constructions) == 2
        assert constructions[0] is not constructions[1]
    else:
        # Single timestamps let SciPy construct directly; nearest uses its tree.
        assert not constructions


@pytest.mark.integration
@pytest.mark.parametrize("method", ["linear", "cubic"])
def test_real_batch_equals_individual_exports(tmp_path, method):
    import os
    from pathlib import Path
    import pandas as pd
    rasterio = pytest.importorskip("rasterio")
    from ras_commander import HdfMesh, HdfResultsMesh

    configured = os.environ.get("RAS_RASTER_TEST_HDF")
    if not configured:
        pytest.skip("Set RAS_RASTER_TEST_HDF to a public computed 2D plan HDF")
    source = Path(configured)
    mesh = HdfMesh.get_mesh_area_names(source)[0]
    view = HdfResultsMesh.get_mesh_timeseries(
        source, mesh, "Water Surface", truncate=False,
        time_selection=slice(0, 121, 60), spatial_selection=0,
    )
    stamps = [pd.Timestamp(v) for v in view.coords["time"].values]
    assert len(stamps) > 1
    batch = HdfResultsMesh.export_depth_rasters_at_times(
        source, stamps, tmp_path / "batch", mesh_name=mesh, max_dimension=150, method=method,
    )
    for i, stamp in enumerate(stamps):
        single = HdfResultsMesh.export_depth_rasters_at_times(
            source, [stamp], tmp_path / f"single-{i}", mesh_name=mesh,
            max_dimension=150, method=method,
        )
        with rasterio.open(batch[str(stamp)]) as actual, rasterio.open(single[str(stamp)]) as expected:
            np.testing.assert_array_equal(actual.read(), expected.read())
            np.testing.assert_array_equal(actual.read_masks(), expected.read_masks())
            assert actual.profile == expected.profile
            assert actual.tags() == expected.tags()
