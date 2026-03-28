from pathlib import Path

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin

from ras_commander import RasProcess


def _write_test_raster(
    path: Path,
    transform,
    crs=None,
) -> None:
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 2,
        "count": 1,
        "dtype": "float32",
        "transform": transform,
        "nodata": -9999.0,
    }
    if crs is not None:
        profile["crs"] = crs

    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float32"), 1)


def test_fix_georeferencing_uses_terrain_crs_when_prj_is_missing(tmp_path):
    terrain_path = tmp_path / "terrain.tif"
    output_path = tmp_path / "output.tif"

    terrain_transform = from_origin(2915865.0, 14061429.0, 10.0, 10.0)
    output_transform = from_origin(500.0, 1500.0, 5.0, 5.0)

    _write_test_raster(terrain_path, terrain_transform, crs="EPSG:2278")
    _write_test_raster(output_path, output_transform)

    assert RasProcess._fix_georeferencing(output_path, None, terrain_path)

    with rasterio.open(output_path) as fixed:
        assert fixed.crs is not None
        assert fixed.crs.to_epsg() == 2278
        assert fixed.transform == terrain_transform
