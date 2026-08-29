"""Opt-in real-runtime qualification for native RAS Mapper terrain export.

Run with ``RAS_COMMANDER_RUN_TERRAIN_EXPORT_QUALIFICATION=1``. Fixture paths
may be overridden with the environment variables used below.
"""

from __future__ import annotations

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


def _assert_result(result, factor):
    assert result, result.error
    assert result.downsample_factor == factor
    assert result.validation["driver"] == "GTiff"
    assert result.validation["data_type"] == "Float32"
    assert result.validation["band_count"] == 1
    assert result.validation["crs_present"] is True
    assert result.validation["sidecars"] == []
    assert result.receipt_path.is_file()


@pytest.mark.parametrize(
    ("version", "expected_min_delta"),
    [("6.4.1", -26.90625), ("6.5", -26.90625), ("6.6", -27.0625)],
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


@pytest.mark.parametrize("version", ["6.4.1", "6.5", "6.6"])
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


@pytest.mark.skipif(platform.system() != "Linux", reason="Wine qualification")
def test_hecras_66_wine_matches_native_muncie_semantics(tmp_path):
    """The host must be configured with a task-copyable HEC-RAS 6.6 prefix."""
    assert MUNCIE_PROJECT.is_file()
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
