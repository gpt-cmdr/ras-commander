"""Read-only native 7.0.1 raster controls, independent of nearest-cell queries.

RAS_STORED_MAP_FIXTURE_ROOT points to externally retained project/rasters.
These tests never compute a model, invoke mapping helpers or modify fixtures.
"""

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
rasterio = pytest.importorskip("rasterio")

from ras_commander import HdfUtils


pytestmark = [pytest.mark.integration, pytest.mark.offline_evidence]
MANIFEST = json.loads((Path(__file__).parent / "data/stored_maps_native_manifest.json").read_text(encoding="utf-8"))
FILES = {entry["key"]: entry for entry in MANIFEST["files"]}
SERIES = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


@pytest.fixture(scope="module")
def fixture_root():
    configured = os.environ.get("RAS_STORED_MAP_FIXTURE_ROOT")
    if not configured:
        pytest.skip("Set RAS_STORED_MAP_FIXTURE_ROOT to retained native raster controls")
    root = Path(configured)
    assert root.is_dir(), f"Configured fixture directory unavailable: {root}"
    return root


@pytest.mark.parametrize("entry", MANIFEST["files"], ids=lambda entry: entry["key"])
def test_native_raster_fixture_identity(fixture_root, entry):
    path = fixture_root / entry["path"]
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    assert before[0] == entry["bytes"]
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    assert digest.hexdigest() == entry["sha256"], f"Changed native fixture: {entry['path']}"
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before


@pytest.fixture(scope="module")
def rasters(fixture_root):
    arrays = {}
    grid = None
    paths = []
    for key, entry in FILES.items():
        if key in ("result", "rasmap"):
            continue
        path = fixture_root / entry["path"]
        paths.append((path, path.stat().st_size, path.stat().st_mtime_ns))
        with rasterio.open(path) as source:
            current_grid = (source.shape, source.transform)
            if grid is None:
                grid, crs = current_grid, source.crs
            assert current_grid == grid
            assert HdfUtils.crs_equivalent(source.crs, crs)
            assert source.nodata == -9999
            arrays[key] = source.read(1, masked=True)
    assert grid[0] == (1064, 2763)
    # Output registration matches the exact registered single-raster terrain,
    # including origin, pixel dimensions, row/column support and equivalent CRS.
    yield arrays
    for path, size, mtime in paths:
        assert (path.stat().st_size, path.stat().st_mtime_ns) == (size, mtime)


def _assert_initial_dry(fixture_root):
    with h5py.File(fixture_root / FILES["result"]["path"], "r") as hdf:
        assert "7.0.1" in hdf.attrs["File Version"].decode("utf-8")
        assert hdf.attrs["Units System"].decode("utf-8") == "US Customary"
        minimum = hdf["Geometry/2D Flow Areas/DebrisFlowArea/Cells Minimum Elevation"][:]
        initial = hdf[f"{SERIES}/2D Flow Areas/DebrisFlowArea/Water Surface"][0]
        finite = np.isfinite(minimum)
        assert np.count_nonzero(finite) == 10201
        # All physical cells start at minimum elevation; ghost minima are NaN.
        np.testing.assert_array_equal(initial[finite], minimum[finite])
        stamps = [value.decode("utf-8") for value in hdf[f"{SERIES}/Time Date Stamp"][:]]
        assert stamps == [f"01JAN2000 00:{minute:02d}:00" for minute in (0, 5, 10, 15, 20)]


def test_initial_missing_rasters_have_independent_all_dry_hdf_control(fixture_root):
    _assert_initial_dry(fixture_root)


@pytest.fixture(scope="module")
def wet_samples(rasters, fixture_root):
    # The initial output produced no raster. Its dry state is independently
    # established from every physical cell, even when running selected tests.
    _assert_initial_dry(fixture_root)
    wet = np.stack([np.zeros(rasters["terrain"].shape, dtype=bool)] + [
        np.ma.filled(rasters[f"time_{index:02d}_depth"] > .5, False)
        for index in range(1, 5)
    ])
    assert np.count_nonzero(wet.any(axis=0)) == 21292
    return wet


@pytest.mark.parametrize("index", range(1, 5))
def test_rendered_wse_depth_match_registered_terrain_pixels(rasters, index):
    depth = rasters[f"time_{index:02d}_depth"]
    wse = rasters[f"time_{index:02d}_wse"]
    np.testing.assert_array_equal(np.ma.getmaskarray(depth), np.ma.getmaskarray(wse))
    valid = ~np.ma.getmaskarray(depth)
    assert np.all(~np.ma.getmaskarray(rasters["terrain"])[valid])
    np.testing.assert_array_equal(wse.data[valid] - depth.data[valid], rasters["terrain"].data[valid])


@pytest.mark.parametrize("product", ["arrival_time", "duration", "percent_inundated"])
def test_native_adr_mask_retains_never_wet_or_unmapped_nodata(rasters, wet_samples, product):
    actual = rasters[f"adr_{product}"]
    np.testing.assert_array_equal(~np.ma.getmaskarray(actual), wet_samples.any(axis=0))
    assert np.all(actual.data[np.ma.getmaskarray(actual)] == -9999)


def test_native_percent_uses_five_stored_samples(rasters, wet_samples):
    actual = rasters["adr_percent_inundated"]
    valid = ~np.ma.getmaskarray(actual)
    expected = wet_samples.sum(axis=0) * (100.0 / 5)
    np.testing.assert_array_equal(actual.data[valid], expected[valid])
    assert set(actual.compressed()) == {20, 40, 60, 80}


def test_native_arrival_uses_first_wet_stored_time(rasters, wet_samples):
    actual = rasters["adr_arrival_time"]
    valid = ~np.ma.getmaskarray(actual)
    expected = wet_samples.argmax(axis=0) * (5.0 / 60)
    np.testing.assert_allclose(actual.data[valid], expected[valid], rtol=0, atol=1e-6)


def test_native_duration_matches_observed_single_wet_period_support(rasters, wet_samples):
    actual = rasters["adr_duration"]
    valid = ~np.ma.getmaskarray(actual)
    first = wet_samples.argmax(axis=0)
    last = 4 - wet_samples[::-1].argmax(axis=0)
    expected = (last - first) * (5.0 / 60)
    np.testing.assert_allclose(actual.data[valid], expected[valid], rtol=0, atol=1e-6)
    # Three pixels wet only at minute 15 are dry at the final sample. Their
    # duration is zero; this control does not infer arbitrary recession rules.
    isolated = (~wet_samples[[0, 1, 2, 4]].any(axis=0)) & wet_samples[3]
    assert np.count_nonzero(isolated) == 3
    np.testing.assert_array_equal(actual.data[isolated], np.zeros(3))
