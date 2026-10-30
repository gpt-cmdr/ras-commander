"""``estimate_final_mannings_raster`` treats stored no-data Manning's n as no data.

Legacy land-cover layers store a ``NoData`` class (and, in combined layers,
every class) with Manning's n = float32 max; current layers use -9999. Neither
is a roughness value: those pixels must come out as no data (0 in the returned
array, the -9999 nodata value in the written GeoTIFF), like unmapped pixels.
"""
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander import fast_hdf
from ras_commander.hdf.HdfLandCover import HdfLandCover

F32_MAX = float(np.finfo(np.float32).max)


def _project(tmp_path, nodata_n):
    pixels = np.array([[0, 1, 1, 0], [1, 1, 2, 2], [0, 2, 2, 1], [1, 1, 1, 1]], dtype="u1")
    tif = tmp_path / "LandCover.tif"
    with rasterio.open(tif, "w", driver="GTiff", height=4, width=4, count=1, dtype="uint8",
                       crs="EPSG:2965", transform=from_origin(1000.0, 2000.0, 10.0, 10.0)) as dst:
        dst.write(pixels, 1)
    lc = tmp_path / "LandCover.hdf"
    with h5py.File(lc, "w") as h:
        h["IDs"] = np.array([0, 1, 2], dtype="u1")
        h["Names"] = np.array([b"NoData", b"Grass", b"Forest"], dtype="S28")
        h["ManningsN"] = np.array([nodata_n, 0.035, 0.1], dtype="f4")
    geom = tmp_path / "Plan.g01.hdf"
    with h5py.File(geom, "w") as h:
        g = h.create_group("Geometry")
        g.attrs["Extents"] = np.array([1000.0, 1040.0, 1960.0, 2000.0])  # xmin, xmax, ymin, ymax
    return geom, lc, pixels


@pytest.mark.parametrize("nodata_n", [F32_MAX, -9999.0], ids=["legacy-f32max", "current-9999"])
def test_no_data_class_is_no_data_not_a_roughness(tmp_path, nodata_n):
    geom, lc, pixels = _project(tmp_path, nodata_n)
    out_tif = tmp_path / "final.tif"
    result = HdfLandCover.estimate_final_mannings_raster(geom, landcover_hdf_path=lc, output_tif_path=out_tif)
    assert result is not None
    expected = np.where(pixels == 1, np.float32(0.035), np.where(pixels == 2, np.float32(0.1), np.float32(0)))
    assert result.dtype == np.float32
    assert result.tobytes() == expected.astype(np.float32).tobytes()
    with rasterio.open(out_tif) as src:
        written = src.read(1)
        assert src.nodata == -9999.0
    assert (written[pixels == 0] == -9999.0).all()


def test_layer_without_any_roughness_gives_only_no_data(tmp_path):
    geom, lc, pixels = _project(tmp_path, F32_MAX)
    with h5py.File(lc, "a") as h:
        h["ManningsN"][...] = np.float32(F32_MAX)
    result = HdfLandCover.estimate_final_mannings_raster(geom, landcover_hdf_path=lc)
    assert result is not None and not result.any()


def _legacy_projects():
    manifest = os.environ.get("RAS_ROUTE2_FIXTURES")
    if not manifest:
        return []
    out = []
    for p in json.loads(Path(manifest).read_text()).get("projects", []):
        lc = p.get("landcover")
        if lc and Path(lc).exists():
            with h5py.File(lc, "r") as h:
                if "Raster Map" not in h and "ManningsN" in h:
                    out.append(pytest.param(p["geom"], lc, id=p["name"]))
    return out


@pytest.mark.parametrize("geom,lc", _legacy_projects() or [pytest.param(None, None, marks=pytest.mark.skip(
    reason="Set RAS_ROUTE2_FIXTURES to a manifest whose projects use legacy land-cover layers"))])
def test_real_legacy_projects_never_output_the_sentinel(geom, lc):
    for backend in ("h5py", "native"):
        with fast_hdf.backend_scope(backend):
            result = HdfLandCover.estimate_final_mannings_raster(geom, landcover_hdf_path=lc)
        assert result is not None
        assert np.isfinite(result).all()
        assert result.max() < 1.0e30 and result.min() >= 0.0
