"""Bounded writes, exact pixel values, and partial-write cleanup."""

import numpy as np
import pytest

pytest.importorskip("scipy")
from ras_commander.hdf import _raster_interpolation as raster


@pytest.mark.parametrize("method", ["linear", "cubic", "nearest"])
@pytest.mark.parametrize("cols", [3, 19])
def test_windows_cover_each_pixel_once_with_matching_values(monkeypatch, method, cols):
    rng = np.random.default_rng(720)
    points, values = rng.random((40, 2)), rng.random(40)
    x, y = np.linspace(-.1, 1.1, cols), np.linspace(1.1, -.1, 13)
    mask = rng.random((len(y), len(x))) > .3
    expected = raster._interpolate_to_grid(points, values, x, y, method, -9999)
    expected[~mask] = -9999
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 7)

    class Writer:
        result = np.empty(expected.shape, dtype=np.float32)
        coverage = np.zeros(expected.shape, dtype=int)

        def write(self, block, band, *, window):
            assert block.dtype == np.float32
            assert block.size <= 7
            assert band == 1
            (row, endrow), (col, endcol) = window
            self.result[row:endrow, col:endcol] = block
            self.coverage[row:endrow, col:endcol] += 1

    writer = Writer()
    raster._write_interpolated_raster(
        writer, x, y, raster._build_interpolator(points, values, method, -9999),
        -9999, mesh_mask=mask,
    )
    np.testing.assert_array_equal(writer.result, expected)
    np.testing.assert_array_equal(writer.coverage, 1)


def test_nearest_window_mask_does_not_change_source_values(monkeypatch):
    values = np.arange(9, dtype=np.float32)
    indices = np.arange(35) % 9
    x, y = np.arange(7), np.arange(5)
    mask = np.ones((5, 7), dtype=bool)
    mask[:, 2] = False
    before = values.copy(), indices.copy()
    result = np.empty((5, 7), dtype=np.float32)

    class Writer:
        def write(self, block, band, *, window):
            (r, er), (c, ec) = window
            result[r:er, c:ec] = block

    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 3)
    raster._write_interpolated_raster(
        Writer(), x, y, None, np.nan, mesh_mask=mask,
        nearest_values=values, nearest_indices=indices,
    )
    expected = values[indices].reshape(5, 7)
    expected[~mask] = np.nan
    np.testing.assert_array_equal(result, expected)
    np.testing.assert_array_equal(values, before[0])
    np.testing.assert_array_equal(indices, before[1])


def test_public_export_writes_bounded_windows(tmp_path, monkeypatch):
    import h5py
    rasterio = pytest.importorskip("rasterio")
    gpd = pytest.importorskip("geopandas")
    from ras_commander import HdfResultsMesh

    frame = gpd.GeoDataFrame(
        {"maximum_depth": [1., 2., 3., 4.]},
        geometry=gpd.points_from_xy([0, 32, 0, 32], [0, 0, 32, 32]), crs="EPSG:2271",
    )
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_depth", lambda _: frame)
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 7)
    original = rasterio.open
    sizes = []

    class Writer:
        def __init__(self, writer):
            self.writer = writer

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.writer.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.writer, name)

        def write(self, block, band, **kwargs):
            sizes.append(block.size)
            assert block.size <= 7
            assert "window" in kwargs
            return self.writer.write(block, band, **kwargs)

    monkeypatch.setattr(rasterio, "open", lambda *a, **kw: Writer(original(*a, **kw)))
    source = tmp_path / "example.p01.hdf"
    with h5py.File(source, "w"):
        pass
    HdfResultsMesh.export_max_depth_raster(source, tmp_path / "depth.tif", resolution_m=1)
    assert sum(sizes) == 33 * 33
    assert len(sizes) > 1


def test_owned_temporary_removed_after_partial_write(tmp_path, monkeypatch):
    import tempfile
    import h5py
    rasterio = pytest.importorskip("rasterio")
    gpd = pytest.importorskip("geopandas")
    from ras_commander import HdfResultsMesh

    frame = gpd.GeoDataFrame(
        {"maximum_depth": [1., 2., 3., 4.]},
        geometry=gpd.points_from_xy([0, 32, 0, 32], [0, 0, 32, 32]), crs="EPSG:2271",
    )
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_depth", lambda _: frame)
    monkeypatch.setattr(raster, "_QUERY_BLOCK_PIXELS", 7)
    original_temp, original_open = tempfile.NamedTemporaryFile, rasterio.open
    from pathlib import Path
    paths, writers, writes = [], [], []

    def allocate(**kwargs):
        file = original_temp(dir=tmp_path, **kwargs)
        paths.append(Path(file.name))
        return file

    class Writer:
        def __init__(self, writer):
            self.writer = writer
            writers.append(writer)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.writer.__exit__(*args)

        def write(self, block, band, **kwargs):
            writes.append(1)
            if len(writes) == 2:
                raise RuntimeError("injected failure after one successful window")
            return self.writer.write(block, band, **kwargs)

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", allocate)
    monkeypatch.setattr(rasterio, "open", lambda *a, **kw: Writer(original_open(*a, **kw)))
    source = tmp_path / "example.p01.hdf"
    with h5py.File(source, "w"):
        pass
    with pytest.raises(RuntimeError, match="after one successful window"):
        HdfResultsMesh.export_max_depth_raster(source, resolution_m=1)
    assert len(writes) == 2
    assert len(paths) == 1 and not paths[0].exists()
    assert all(writer.closed for writer in writers)
