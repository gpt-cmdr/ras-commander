"""Opt-in public model/installed-engine qualification; never execute HEC-RAS."""

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def case():
    filename = os.environ.get("RAS_COMMANDER_SUPPLIED_WSEL_CASE")
    if not filename:
        pytest.skip("Set RAS_COMMANDER_SUPPLIED_WSEL_CASE to a computed public 2D model")
    return json.loads(Path(filename).read_text(encoding="utf-8"))


def test_complete_masks_and_float32_bits_match_selectors_and_prepared_snapshot(case, tmp_path):
    from scripts.benchmarks.fim_supplied_wsel_compare import qualify
    receipt = qualify(case, tmp_path / "qualify")
    assert receipt["status"] == "complete"


def test_invalid_missing_row_rejects_even_for_empty_aoi(case, tmp_path):
    from ras_commander import RasFim
    from scripts.benchmarks.fim_supplied_wsel_compare import selector_table
    table = selector_table(case["hdf"], case["profiles"]).iloc[:-1]
    with pytest.raises(ValueError, match="physical and ghost"):
        RasFim.map_sloping_profiles(case["hdf"], case["terrain"], tmp_path / "invalid",
            wsel_profiles=table, engine_path=case.get("engine"), bbox=(0, 0, 1, 1))
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("kind", ["bbox", "polygon"])
def test_masked_supplied_profiles_match_selectors(case, tmp_path, kind):
    from shapely.geometry import Polygon
    from ras_commander import HdfMesh, RasFim
    from scripts.benchmarks.fim_supplied_wsel_compare import selector_table, compare_products

    table = selector_table(case["hdf"], case["profiles"]).sample(frac=1, random_state=331)
    cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True, engine="native")
    x0, y0, x1, y1 = cells.total_bounds
    if kind == "bbox":
        mask = dict(bbox=(x0, y0, (x0 + x1) / 2, y1))
    else:
        mask = dict(polygon=Polygon([(x0, y0), (x1, y0), (x1, y1)]), aoi_crs=cells.crs)
    options = dict(engine_path=case.get("engine"), threads=4,
        max_working_mib=case.get("max_working_mib", 2048), **mask)
    supplied = RasFim.map_sloping_profiles(case["hdf"], case["terrain"], tmp_path / "supplied",
        wsel_profiles=table, max_inflight_profiles=2, **options)
    selected = RasFim.map_sloping_profiles(case["hdf"], case["terrain"], tmp_path / "selector",
        profiles=case["profiles"], **options)
    compare_products(supplied, selected)


def test_nan_dry_marker_and_independent_terrain(case, tmp_path):
    import numpy as np
    import rasterio
    from ras_commander import RasFim
    from scripts.benchmarks.fim_supplied_wsel_compare import selector_table, compare_products, sha256

    table = selector_table(case["hdf"], case["profiles"])
    options = dict(engine_path=case.get("engine"), threads=4,
        max_working_mib=case.get("max_working_mib", 2048))
    # Explicit dry is independent of source-selector sentinels. Mix dry and wet
    # source cells so the result must retain both valid pixels and nodata.
    dry = table.copy(deep=True)
    dry.loc[dry.cell_id % 3 == 0, list(case["profiles"])] = np.nan
    marker = dry.fillna(np.finfo(np.float32).min)
    actual = RasFim.map_sloping_profiles(case["hdf"], case["terrain"], tmp_path / "nan",
        wsel_profiles=dry, **options)
    expected = RasFim.map_sloping_profiles(case["hdf"], case["terrain"], tmp_path / "marker",
        wsel_profiles=marker, **options)
    compare_products(actual, expected)
    assert actual.depth_finite_pixels.sum() > 0

    # Change only a task-owned terrain copy, never hydraulic results. Select a
    # genuinely wet pixel and preserve source grid/CRS/nodata/storage metadata.
    original = RasFim.map_sloping_profiles(case["hdf"], case["terrain"], tmp_path / "original",
        profiles=case["profiles"], **options)
    original_hash = sha256(case["terrain"])
    with rasterio.open(original.iloc[0].depth_tif) as source:
        depths = source.read(1, masked=True)
        rows, cols = np.where((~np.ma.getmaskarray(depths)) & (depths.data > 2))
        assert len(rows), "Qualification fixture needs a depth > 2 model elevation units"
        point = source.xy(int(rows[0]), int(cols[0]))
    changed = tmp_path / "changed-terrain.tif"
    with rasterio.open(case["terrain"]) as source:
        values, metadata = source.read(1), source.profile
        row, col = source.index(*point)
        values[row, col] += np.float32(1)
        with rasterio.open(changed, "w", **metadata) as target:
            target.write(values, 1)
    selected = RasFim.map_sloping_profiles(case["hdf"], changed, tmp_path / "changed-selector",
        profiles=case["profiles"], **options)
    supplied = RasFim.map_sloping_profiles(case["hdf"], changed, tmp_path / "changed-supplied",
        wsel_profiles=table, **options)
    compare_products(supplied, selected)
    with rasterio.open(selected.iloc[0].depth_tif) as source:
        new_depth = source.sample([point], masked=True).__next__()[0]
    assert not np.ma.is_masked(new_depth)
    assert new_depth != depths.data[rows[0], cols[0]]
    assert sha256(case["terrain"]) == original_hash
