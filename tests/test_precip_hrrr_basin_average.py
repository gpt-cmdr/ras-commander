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


def _make_precip_dataset(step_minutes=(15, 30), include_valid_time=True):
    step_minutes = np.asarray(step_minutes, dtype="timedelta64[m]")
    record_count = len(step_minutes)
    precipitation = np.stack([
        np.array([[1.0 + index, 9.0], [3.0 + index, 100.0]])
        for index in range(record_count)
    ])
    coordinates = {
        "step": ("step", step_minutes),
        "time": np.datetime64("2026-07-11T12:00:00"),
        "latitude": (
            ("y", "x"),
            np.array([[1.0, 1.0], [0.0, 0.0]]),
        ),
        "longitude": (
            ("y", "x"),
            np.array([[0.0, 1.0], [0.0, 1.0]]),
        ),
    }
    if include_valid_time:
        coordinates["valid_time"] = (
            "step",
            np.datetime64("2026-07-11T12:00:00") + step_minutes,
        )

    return xr.Dataset(
        {
            "tp": xr.DataArray(
                precipitation,
                dims=("step", "y", "x"),
                coords=coordinates,
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

    with caplog.at_level("INFO"):
        df = PrecipHrrr.get_basin_average(["dummy.grib2"], geometry)

    assert df["precip_mm"].tolist() == pytest.approx([2.0, 3.0])
    assert df["cumulative_mm"].tolist() == pytest.approx([2.0, 5.0])
    assert df["forecast_hour"].tolist() == [1, 2]
    assert df["forecast_lead_hours"].tolist() == pytest.approx([0.25, 0.5])
    assert df["valid_time"].tolist() == [
        np.datetime64("2026-07-11T12:15:00"),
        np.datetime64("2026-07-11T12:30:00"),
    ]
    assert "rasterio geometry mask fallback" in caplog.text
    assert "2 records (15-minute valid-time spacing; lead 0.25-0.50 h)" in caplog.text
    assert "2 hours" not in caplog.text


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


@pytest.mark.parametrize(
    ("step_minutes", "expected_summary"),
    [
        ((60, 120), "1-hour valid-time spacing"),
        ((15, 30, 60), "mixed valid-time spacing"),
    ],
)
def test_get_basin_average_reports_source_timing(
    monkeypatch, caplog, step_minutes, expected_summary
):
    dataset = _make_precip_dataset(step_minutes=step_minutes)
    geometry = GeoJsonPolygon(bounds=(-0.5, -0.5, 0.5, 1.5))

    monkeypatch.setattr(
        PrecipHrrr,
        "extract_precipitation",
        staticmethod(lambda grib_files: dataset),
    )
    _force_missing_rasterstats(monkeypatch)

    with caplog.at_level("INFO"):
        df = PrecipHrrr.get_basin_average(["dummy.grib2"], geometry)

    assert expected_summary in caplog.text
    assert df["forecast_lead_hours"].tolist() == pytest.approx(
        np.asarray(step_minutes) / 60.0
    )


def test_get_basin_average_derives_valid_time_from_cycle_and_step(monkeypatch):
    dataset = _make_precip_dataset(include_valid_time=False)
    geometry = GeoJsonPolygon(bounds=(-0.5, -0.5, 0.5, 1.5))

    monkeypatch.setattr(
        PrecipHrrr,
        "extract_precipitation",
        staticmethod(lambda grib_files: dataset),
    )
    _force_missing_rasterstats(monkeypatch)

    df = PrecipHrrr.get_basin_average(["dummy.grib2"], geometry)

    assert df["valid_time"].tolist() == [
        np.datetime64("2026-07-11T12:15:00"),
        np.datetime64("2026-07-11T12:30:00"),
    ]


def test_get_basin_average_rejects_duplicate_valid_times(monkeypatch):
    dataset = _make_precip_dataset().assign_coords(
        valid_time=(
            "step",
            [
                np.datetime64("2026-07-11T12:15:00"),
                np.datetime64("2026-07-11T12:15:00"),
            ],
        )
    )
    geometry = GeoJsonPolygon(bounds=(-0.5, -0.5, 0.5, 1.5))
    monkeypatch.setattr(
        PrecipHrrr,
        "extract_precipitation",
        staticmethod(lambda grib_files: dataset),
    )

    with pytest.raises(ValueError, match="duplicate timestamps"):
        PrecipHrrr.get_basin_average(["dummy.grib2"], geometry)


def test_get_basin_average_rejects_nonincreasing_forecast_leads(monkeypatch):
    dataset = _make_precip_dataset(step_minutes=(15, 30, 15))
    geometry = GeoJsonPolygon(bounds=(-0.5, -0.5, 0.5, 1.5))
    monkeypatch.setattr(
        PrecipHrrr,
        "extract_precipitation",
        staticmethod(lambda grib_files: dataset),
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        PrecipHrrr.get_basin_average(["dummy.grib2"], geometry)


def test_get_basin_average_rejects_multiple_forecast_cycles(monkeypatch):
    dataset = _make_precip_dataset().assign_coords(
        time=(
            "step",
            [
                np.datetime64("2026-07-11T12:00:00"),
                np.datetime64("2026-07-11T13:00:00"),
            ],
        )
    )
    geometry = GeoJsonPolygon(bounds=(-0.5, -0.5, 0.5, 1.5))
    monkeypatch.setattr(
        PrecipHrrr,
        "extract_precipitation",
        staticmethod(lambda grib_files: dataset),
    )

    with pytest.raises(ValueError, match="one forecast cycle"):
        PrecipHrrr.get_basin_average(["dummy.grib2"], geometry)


def test_get_basin_average_rejects_inconsistent_valid_time(monkeypatch):
    dataset = _make_precip_dataset().assign_coords(
        valid_time=(
            "step",
            [
                np.datetime64("2026-07-11T12:15:00"),
                np.datetime64("2026-07-11T12:45:00"),
            ],
        )
    )
    geometry = GeoJsonPolygon(bounds=(-0.5, -0.5, 0.5, 1.5))
    monkeypatch.setattr(
        PrecipHrrr,
        "extract_precipitation",
        staticmethod(lambda grib_files: dataset),
    )

    with pytest.raises(ValueError, match="cycle time plus step"):
        PrecipHrrr.get_basin_average(["dummy.grib2"], geometry)
