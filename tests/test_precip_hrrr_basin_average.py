import builtins
import sys
import types

import numpy as np
import pytest

xr = pytest.importorskip("xarray")
rasterio = pytest.importorskip("rasterio")
from rasterio import features as rio_features

from ras_commander.precip import PrecipHrrr


class GeoJsonPolygon:
    def __init__(self, bounds):
        self.bounds = bounds
        west, south, east, north = bounds
        self.__geo_interface__ = {
            "type": "Polygon",
            "coordinates": [[
                (west, south),
                (east, south),
                (east, north),
                (west, north),
                (west, south),
            ]],
        }


def _make_precip_dataset():
    return xr.Dataset(
        {
            "tp": xr.DataArray(
                np.array(
                    [
                        [[1.0, 9.0], [3.0, 100.0]],
                        [[2.0, 10.0], [4.0, 200.0]],
                    ]
                ),
                dims=("step", "y", "x"),
                coords={
                    "step": [0, 1],
                    "latitude": (
                        ("y", "x"),
                        np.array([[1.0, 1.0], [0.0, 0.0]]),
                    ),
                    "longitude": (
                        ("y", "x"),
                        np.array([[0.0, 1.0], [0.0, 1.0]]),
                    ),
                },
            )
        }
    )


def _force_missing_rasterstats(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "rasterstats":
            raise ImportError("forced missing rasterstats")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_extract_precipitation_clips_2d_lat_lon_bounds(monkeypatch, tmp_path):
    files = []
    for name in ["a.grib2", "b.grib2"]:
        grib_file = tmp_path / name
        grib_file.write_text("dummy", encoding="utf-8")
        files.append(grib_file)

    lat_grid = np.array([[1.0, 1.0], [0.0, 0.0]])
    lon_grid = np.array([[0.0, 1.0], [0.0, 1.0]])
    datasets = [
        xr.Dataset(
            {
                "tp": xr.DataArray(
                    np.array([[1.0, 11.0], [21.0, 31.0]]),
                    dims=("y", "x"),
                    coords={
                        "latitude": (("y", "x"), lat_grid),
                        "longitude": (("y", "x"), lon_grid),
                    },
                )
            },
            coords={"step": 1},
        ),
        xr.Dataset(
            {
                "tp": xr.DataArray(
                    np.array([[2.0, 12.0], [22.0, 32.0]]),
                    dims=("y", "x"),
                    coords={
                        "latitude": (("y", "x"), lat_grid),
                        "longitude": (("y", "x"), lon_grid),
                    },
                )
            },
            coords={"step": 2},
        ),
    ]

    monkeypatch.setattr(
        xr,
        "open_dataset",
        lambda *args, **kwargs: datasets.pop(0),
    )
    monkeypatch.setitem(sys.modules, "cfgrib", types.ModuleType("cfgrib"))

    clipped = PrecipHrrr.extract_precipitation(
        grib_files=files,
        bounds=(-0.5, -0.5, 0.5, 1.5),
    )

    assert clipped["tp"].shape == (2, 2, 1)
    assert clipped["tp"].isel(step=0).values[:, 0].tolist() == pytest.approx(
        [1.0, 21.0]
    )
    assert clipped["tp"].isel(step=1).values[:, 0].tolist() == pytest.approx(
        [2.0, 22.0]
    )


def test_get_basin_average_uses_exact_mask_when_rasterstats_missing(
    monkeypatch, caplog
):
    dataset = _make_precip_dataset()
    geometry = GeoJsonPolygon(bounds=(-0.5, -0.5, 0.5, 1.5))

    monkeypatch.setattr(
        PrecipHrrr,
        "extract_precipitation",
        staticmethod(lambda grib_files: dataset),
    )
    _force_missing_rasterstats(monkeypatch)

    with caplog.at_level("WARNING"):
        df = PrecipHrrr.get_basin_average(["dummy.grib2"], geometry)

    assert df["precip_mm"].tolist() == pytest.approx([2.0, 3.0])
    assert df["cumulative_mm"].tolist() == pytest.approx([2.0, 5.0])
    assert "rasterio geometry mask fallback" in caplog.text


def test_get_basin_average_uses_bbox_mean_when_exact_mask_unavailable(
    monkeypatch, caplog
):
    dataset = _make_precip_dataset()
    geometry = GeoJsonPolygon(bounds=(-0.5, -0.5, 0.5, 1.5))

    monkeypatch.setattr(
        PrecipHrrr,
        "extract_precipitation",
        staticmethod(lambda grib_files: dataset),
    )
    monkeypatch.setattr(
        rio_features,
        "geometry_mask",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mask failed")),
    )
    _force_missing_rasterstats(monkeypatch)

    with caplog.at_level("WARNING"):
        df = PrecipHrrr.get_basin_average(["dummy.grib2"], geometry)

    assert df["precip_mm"].tolist() == pytest.approx([2.0, 3.0])
    assert "watershed bounding box average" in caplog.text
