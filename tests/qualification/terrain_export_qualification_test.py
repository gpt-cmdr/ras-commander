"""Opt-in real-runtime qualification for native RAS Mapper terrain export.

Run with ``RAS_COMMANDER_RUN_TERRAIN_EXPORT_QUALIFICATION=1``. Fixture paths
may be overridden with the environment variables used below. Exact-input
Windows/Wine pixel parity is additionally enabled by setting all three of
``RAS_COMMANDER_TERRAIN_PARITY_PROJECT``,
``RAS_COMMANDER_TERRAIN_PARITY_WINDOWS_OFF``, and
``RAS_COMMANDER_TERRAIN_PARITY_WINDOWS_ON``.
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path

import numpy as np
import pytest

from ras_commander import RasTerrain


pytestmark = [pytest.mark.integration, pytest.mark.qualification_critical]

if os.environ.get("RAS_COMMANDER_RUN_TERRAIN_EXPORT_QUALIFICATION") != "1":
    pytest.skip("native terrain export qualification is opt-in", allow_module_level=True)

rasterio = pytest.importorskip("rasterio")

UPGU3_PROJECT = Path(os.environ.get(
    "RAS_COMMANDER_UPGU3_PROJECT",
    r"H:\Testing\eBFE Model Organization\Organized\UpperGuadalupe_12100201\RAS Model\UPGU3\UPGU3.prj",
))
MUNCIE_PROJECT = Path(os.environ.get(
    "RAS_COMMANDER_MUNCIE_PROJECT",
    r"H:\CLB-Repos\ras-commander\example_projects\Muncie\Muncie.prj",
))
BALD_EAGLE_PROJECT = Path(os.environ.get(
    "RAS_COMMANDER_BALD_EAGLE_PROJECT",
    r"H:\CLB-Repos\ras-commander\example_projects\BaldEagleCrkMulti2D\BaldEagleDamBrk.prj",
))
UPGU3_WINDOW = (
    1996495.92929205,
    13858745.25719928,
    1996712.46429205,
    13859060.217199279,
)
MUNCIE_WINDOW = (
    404147.258781418,
    1801881.85296284,
    404307.258781418,
    1802111.85296284,
)
BALD_EAGLE_WINDOW = (
    2041660.41918676,
    347030.9951331958,
    2044060.41918676,
    349430.9951331958,
)


def _assert_result(result, factor):
    assert result, result.error
    assert result.downsample_factor == factor
    assert result.validation["driver"] == "GTiff"
    assert result.validation["data_type"] == "Float32"
    assert result.validation["band_count"] == 1
    assert result.validation["crs_present"] is True
    assert result.validation["sidecars"] == []
    assert result.receipt_path.is_file()


def _optional_exact_parity_paths() -> tuple[Path, Path, Path]:
    variable_names = (
        "RAS_COMMANDER_TERRAIN_PARITY_PROJECT",
        "RAS_COMMANDER_TERRAIN_PARITY_WINDOWS_OFF",
        "RAS_COMMANDER_TERRAIN_PARITY_WINDOWS_ON",
    )
    configured = [os.environ.get(name) for name in variable_names]
    if not any(configured):
        pytest.skip("exact Windows-reference terrain parity paths are not configured")
    missing_variables = [
        name for name, value in zip(variable_names, configured) if not value
    ]
    if missing_variables:
        pytest.fail(
            "exact terrain parity requires all reference paths; missing "
            + ", ".join(missing_variables)
        )
    paths = tuple(Path(value) for value in configured)
    missing_paths = [str(path) for path in paths if not path.is_file()]
    if missing_paths:
        pytest.fail(
            "exact terrain parity paths do not exist: " + ", ".join(missing_paths)
        )
    return paths


def _read_raster_for_parity(path: Path) -> tuple[np.ma.MaskedArray, dict]:
    with rasterio.open(path) as dataset:
        values = dataset.read(1, masked=True)
        metadata = {
            "shape": (dataset.height, dataset.width),
            "transform": dataset.transform,
            "bounds": dataset.bounds,
            "crs": dataset.crs,
            "nodata": dataset.nodata,
            "dtype": dataset.dtypes,
        }
    return values, metadata


@pytest.mark.parametrize(
    ("version", "expected_min_delta"),
    [
        ("6.4.1", -26.90625),
        ("6.5", -26.90625),
        ("6.6", -27.0625),
        ("7.0.1", -27.0625),
    ],
)
@pytest.mark.skipif(platform.system() != "Windows", reason="native Windows qualification")
def test_supported_versions_upgu3_modification_aware_2x_and_4x(
    tmp_path, version, expected_min_delta
):
    assert UPGU3_PROJECT.is_file()
    common = dict(
        ras_project_path=UPGU3_PROJECT,
        terrain_name="Terrain",
        extent=UPGU3_WINDOW,
        hecras_version=version,
        timeout_seconds=300,
    )
    off = RasTerrain.export_rasmapper_terrain(
        output_tif=tmp_path / "upgu3-2x-off.tif",
        downsample_factor=2,
        rasterize_modifications=False,
        **common,
    )
    on = RasTerrain.export_rasmapper_terrain(
        output_tif=tmp_path / "upgu3-2x-on.tif",
        downsample_factor=2,
        rasterize_modifications=True,
        **common,
    )
    four = RasTerrain.export_rasmapper_terrain(
        output_tif=tmp_path / "upgu3-4x-on.tif",
        downsample_factor=4,
        rasterize_modifications=True,
        **common,
    )
    _assert_result(off, 2)
    _assert_result(on, 2)
    _assert_result(four, 4)
    assert (off.validation["columns"], off.validation["rows"]) == (33, 48)
    assert (four.validation["columns"], four.validation["rows"]) == (17, 24)

    with rasterio.open(off.output_path) as off_ds, rasterio.open(on.output_path) as on_ds:
        off_values = off_ds.read(1)
        on_values = on_ds.read(1)
        valid = (off_values != off_ds.nodata) & (on_values != on_ds.nodata)
    changed = valid & ~np.isclose(off_values, on_values, atol=1e-6, rtol=0)
    unchanged = valid & ~changed
    deltas = on_values[changed] - off_values[changed]
    assert changed.sum() == 73
    assert unchanged.sum() == 1511
    assert np.all(deltas < 0)
    assert deltas.min() == pytest.approx(expected_min_delta)
    assert np.allclose(on_values[:8, :8], off_values[:8, :8])


@pytest.mark.parametrize("version", ["6.4.1", "6.5", "6.6", "7.0.1"])
@pytest.mark.skipif(platform.system() != "Windows", reason="native Windows qualification")
def test_supported_versions_multi_source_stitched_export(tmp_path, version):
    assert MUNCIE_PROJECT.is_file()
    common = dict(
        ras_project_path=MUNCIE_PROJECT,
        terrain_name="TerrainWithChannel",
        extent=MUNCIE_WINDOW,
        downsample_factor=2,
        rasterize_modifications=True,
        timeout_seconds=180,
    )
    result = RasTerrain.export_rasmapper_terrain(
        output_tif=tmp_path / f"muncie-{version}.tif",
        hecras_version=version,
        **common,
    )
    _assert_result(result, 2)
    assert (result.validation["columns"], result.validation["rows"]) == (16, 23)
    assert len(result.source_inventory.index) == 2
    assert result.source_inventory["intersects_output"].all()
    assert result.source_inventory["authoritative_grid"].sum() == 1
    assert result.validation["checksum"] == 4221


@pytest.mark.skipif(platform.system() != "Windows", reason="native Windows qualification")
def test_hecras_66_mixed_noninteger_source_resolutions_export_to_one_tiff(tmp_path):
    """RAS Mapper owns consolidation at the explicit selected output cell size."""
    assert BALD_EAGLE_PROJECT.is_file()
    result = RasTerrain.export_rasmapper_terrain(
        ras_project_path=BALD_EAGLE_PROJECT,
        output_tif=tmp_path / "bald-eagle-terrain50-mixed-2x.tif",
        terrain_name="Terrain50",
        extent=BALD_EAGLE_WINDOW,
        downsample_factor=2,
        rasterize_modifications=False,
        hecras_version="6.6",
        timeout_seconds=180,
    )
    _assert_result(result, 2)
    assert (result.validation["columns"], result.validation["rows"]) == (61, 61)
    assert result.native_cell_size == 20.0
    assert result.output_cell_size == 40.0
    assert len(result.source_inventory.index) == 2
    assert result.source_inventory["intersects_output"].all()
    assert result.source_inventory["authoritative_grid"].tolist() == [False, True]
    source_cells = result.source_inventory["cell_sizes"].map(lambda cells: cells[0])
    assert source_cells.tolist() == pytest.approx([36.504512049933, 20.0])

    receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert receipt["native_helper"]["resample_to_one_rfi"] is True
    assert receipt["native_helper"]["resample_method"] == "near"
    assert receipt["result"]["output_cell_size"] == 40.0


@pytest.mark.skipif(platform.system() != "Linux", reason="Wine qualification")
def test_hecras_66_wine_matches_native_muncie_semantics(tmp_path):
    """The host must be configured with a task-copyable HEC-RAS 6.6 prefix."""
    if not MUNCIE_PROJECT.is_file():
        pytest.skip("Wine Muncie fixture is not configured")
    result = RasTerrain.export_rasmapper_terrain(
        MUNCIE_PROJECT,
        tmp_path / "muncie-wine-66.tif",
        terrain_name="TerrainWithChannel",
        extent=MUNCIE_WINDOW,
        downsample_factor=2,
        rasterize_modifications=True,
        hecras_version="6.6",
        timeout_seconds=300,
    )
    _assert_result(result, 2)
    assert (result.validation["columns"], result.validation["rows"]) == (16, 23)
    assert result.validation["checksum"] == 4221
    assert len(result.source_inventory.index) == 2


@pytest.mark.skipif(platform.system() != "Linux", reason="Wine qualification")
def test_hecras_66_wine_mixed_noninteger_sources_export_to_one_tiff(tmp_path):
    """RAS Mapper consolidates mixed source grids under the configured Wine runtime."""
    if not BALD_EAGLE_PROJECT.is_file():
        pytest.skip("Wine Bald Eagle fixture is not configured")
    result = RasTerrain.export_rasmapper_terrain(
        BALD_EAGLE_PROJECT,
        tmp_path / "bald-eagle-terrain50-mixed-wine-2x.tif",
        terrain_name="Terrain50",
        extent=BALD_EAGLE_WINDOW,
        downsample_factor=2,
        rasterize_modifications=False,
        hecras_version="6.6",
        timeout_seconds=300,
    )
    _assert_result(result, 2)
    assert (result.validation["columns"], result.validation["rows"]) == (61, 61)
    assert result.native_cell_size == 20.0
    assert result.output_cell_size == 40.0
    assert len(result.source_inventory.index) == 2
    assert result.source_inventory["intersects_output"].all()
    assert result.source_inventory["authoritative_grid"].tolist() == [False, True]
    source_cells = result.source_inventory["cell_sizes"].map(lambda cells: cells[0])
    assert source_cells.tolist() == pytest.approx([36.504512049933, 20.0])

    receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert receipt["native_helper"]["resample_to_one_rfi"] is True
    assert receipt["native_helper"]["resample_method"] == "near"
    assert receipt["native_helper"]["rasterize_modifications"] is False
    assert len(receipt["native_helper"]["new_rfis"]) == 1


@pytest.mark.skipif(platform.system() != "Linux", reason="Wine qualification")
def test_hecras_66_wine_exact_windows_reference_off_on_pixel_parity(tmp_path):
    """Compare Wine output to native Windows for one exact modified project copy."""
    project, windows_off, windows_on = _optional_exact_parity_paths()
    results = {}
    for label, enabled in (("off", False), ("on", True)):
        result = RasTerrain.export_rasmapper_terrain(
            project,
            tmp_path / f"terrain50-exact-{label}-wine-2x.tif",
            terrain_name="Terrain50",
            extent=BALD_EAGLE_WINDOW,
            downsample_factor=2,
            rasterize_modifications=enabled,
            hecras_version="6.6",
            timeout_seconds=300,
        )
        _assert_result(result, 2)
        assert (result.validation["columns"], result.validation["rows"]) == (61, 61)
        assert result.source_inventory["authoritative_grid"].tolist() == [False, True]
        receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
        assert receipt["native_helper"]["resample_to_one_rfi"] is True
        assert receipt["native_helper"]["resample_method"] == "near"
        assert receipt["native_helper"]["rasterize_modifications"] is enabled
        assert len(receipt["native_helper"]["new_rfis"]) == 1
        results[label] = result

    wine_off, wine_off_metadata = _read_raster_for_parity(results["off"].output_path)
    wine_on, wine_on_metadata = _read_raster_for_parity(results["on"].output_path)
    reference_off, reference_off_metadata = _read_raster_for_parity(windows_off)
    reference_on, reference_on_metadata = _read_raster_for_parity(windows_on)

    assert wine_off_metadata == reference_off_metadata
    assert wine_on_metadata == reference_on_metadata
    np.testing.assert_array_equal(
        np.ma.getmaskarray(wine_off), np.ma.getmaskarray(reference_off)
    )
    np.testing.assert_array_equal(
        np.ma.getmaskarray(wine_on), np.ma.getmaskarray(reference_on)
    )
    np.testing.assert_array_equal(wine_off.data, reference_off.data)
    np.testing.assert_array_equal(wine_on.data, reference_on.data)

    wine_valid = ~np.ma.getmaskarray(wine_off) & ~np.ma.getmaskarray(wine_on)
    reference_valid = ~np.ma.getmaskarray(reference_off) & ~np.ma.getmaskarray(
        reference_on
    )
    wine_delta = np.where(wine_valid, wine_on.data - wine_off.data, 0.0)
    reference_delta = np.where(
        reference_valid, reference_on.data - reference_off.data, 0.0
    )
    np.testing.assert_array_equal(wine_valid, reference_valid)
    np.testing.assert_array_equal(wine_delta, reference_delta)
    np.testing.assert_array_equal(wine_delta > 0.01, reference_delta > 0.01)
    assert np.any(wine_delta > 0.01)
