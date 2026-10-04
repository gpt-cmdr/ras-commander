import json
from pathlib import Path

import numpy as np
import pytest
xr = pytest.importorskip("xarray")

from ras_commander.precip.Atlas14Grid import Atlas14Grid
from ras_commander.precip.Atlas14HyetographGrid import Atlas14HyetographGrid


OFFICIAL_TEMPORAL_CSV = (
    Path(__file__).parent / "data" / "atlas14_temporal" / "tx_3_24h_temporal.csv"
)


def _cache_official_temporal_csv(tmp_path: Path) -> Path:
    pytest.importorskip("hms_commander")
    cache_dir = tmp_path / "atlas14-cache"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / "tx_3_24h_temporal.csv").write_text(
        OFFICIAL_TEMPORAL_CSV.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return cache_dir


def _grid_kwargs(tmp_path: Path, **overrides):
    kwargs = {
        "depth_grid": np.array([[10.0, np.nan], [0.0, 17.5]]),
        "x": np.array([-95.0, -94.99]),
        "y": np.array([29.99, 29.98]),
        "source_crs": "EPSG:4269",
        "ari_years": 100,
        "storm_duration_hours": 24,
        "timestep_minutes": 30,
        "state": "tx",
        "region": 3,
        "quartile": "All Cases",
        "probability_column": "50%",
        "output_netcdf": tmp_path / "shared.nc",
        "cache_dir": _cache_official_temporal_csv(tmp_path),
        "depth_frequency_basis": "PDS",
    }
    kwargs.update(overrides)
    return kwargs


def test_generates_cf_grid_from_official_temporal_curve_and_conserves_depth(tmp_path):
    result = Atlas14HyetographGrid.generate_from_depth_grid(**_grid_kwargs(tmp_path))

    assert result == (tmp_path / "shared.nc").resolve()
    with xr.open_dataset(result, engine="scipy", decode_times=False) as ds:
        assert ds["precip_incremental"].dims == ("time", "y", "x")
        assert ds.sizes["time"] == 48
        np.testing.assert_allclose(ds["time"].values[:3], [0.5, 1.0, 1.5])
        np.testing.assert_allclose(ds["time_bounds"].values[0], [0.0, 0.5])
        np.testing.assert_allclose(ds["time_bounds"].values[-1], [23.5, 24.0])
        assert ds["time"].attrs["bounds"] == "time_bounds"
        assert ds["time"].attrs["units"] == "hours since 1970-01-01 00:00:00"
        assert ds["time"].attrs["calendar"] == "proleptic_gregorian"
        assert ds["time"].attrs["standard_name"] == "time"
        assert ds["time"].attrs["axis"] == "T"
        assert ds.attrs["time_reference_is_event_date"] == 0
        assert ds["precip_incremental"].attrs["units"] == "inches"
        assert ds["spatial_ref"].attrs["crs_wkt"].startswith("GEOGCRS")
        assert "NAD83" in ds["spatial_ref"].attrs["crs_wkt"]
        assert ds["x"].attrs["standard_name"] == "longitude"
        assert ds.attrs["depth_frequency_basis"] == "PDS"
        assert ds.attrs["areal_reduction"] == "none_applied_by_api"
        assert ds.attrs["ams_conversion"] == "none_applied_by_api"
        assert ds.attrs["spatial_resampling"] == "none"
        assert "shared temporal pattern" in ds.attrs["method_name"]
        assert ds.attrs["depth_conservation_max_error_inches"] < 1e-12
        assert "depth_source_metadata" not in ds.attrs

        np.testing.assert_allclose(ds["temporal_fraction"].sum(), 1.0, atol=1e-12)
        np.testing.assert_allclose(ds["precip_cumulative"].isel(time=-1, y=0, x=0), 10.0)
        np.testing.assert_allclose(ds["precip_cumulative"].isel(time=-1, y=1, x=0), 0.0)
        np.testing.assert_allclose(ds["precip_cumulative"].isel(time=-1, y=1, x=1), 17.5)
        assert np.isnan(ds["precip_incremental"].isel(y=0, x=1)).all()


def test_official_curve_uses_expected_24_hour_median_regression_values(tmp_path):
    output = Atlas14HyetographGrid.generate_from_depth_grid(**_grid_kwargs(
        tmp_path,
        depth_grid=np.array([[1.0, 1.0], [1.0, 1.0]]),
    ))
    with xr.open_dataset(output, engine="scipy", decode_times=False) as ds:
        fraction = ds["temporal_fraction"].values
    # These interval fractions are read from the retained NOAA TX region 3
    # 24-hour All Cases 50% CSV; they guard against changing the curve choice.
    np.testing.assert_allclose(fraction[:3], [0.013, 0.0182, 0.0215], atol=1e-12)
    np.testing.assert_allclose(fraction.sum(), 1.0, atol=1e-12)
    assert int(np.argmax(fraction)) == 6


def test_depth_source_metadata_is_strict_json_and_does_not_replace_api_metadata(tmp_path):
    output = Atlas14HyetographGrid.generate_from_depth_grid(**_grid_kwargs(
        tmp_path,
        source_metadata={"source_kind": "provided depth grid", "upstream_reduction": "unknown"},
    ))
    with xr.open_dataset(output, engine="scipy", decode_times=False) as ds:
        assert json.loads(ds.attrs["depth_source_metadata"]) == {
            "source_kind": "provided depth grid",
            "upstream_reduction": "unknown",
        }
        assert ds.attrs["areal_reduction"] == "none_applied_by_api"

    with pytest.raises(ValueError, match="JSON-serializable finite"):
        Atlas14HyetographGrid.generate_from_depth_grid(**_grid_kwargs(
            tmp_path,
            output_netcdf=tmp_path / "invalid-metadata.nc",
            source_metadata={"not_finite": float("nan")},
        ))


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ({"depth_grid": np.array([[np.inf, 1.0], [1.0, 1.0]])}, "infinite"),
        ({"depth_grid": np.array([[-0.1, 1.0], [1.0, 1.0]])}, "negative"),
        ({"depth_grid": np.array([[np.nan, np.nan], [np.nan, np.nan]])}, "no valid"),
        ({"x": np.array([0.0, 1.0, 3.0]), "depth_grid": np.ones((2, 3))}, "regularly"),
        ({"timestep_minutes": 17}, "exactly divide"),
        ({"storm_duration_hours": 24.5}, "whole number"),
        ({"storm_duration_hours": True}, "whole number"),
    ],
)
def test_rejects_invalid_grid_inputs_before_temporal_download(tmp_path, changed, message):
    kwargs = _grid_kwargs(tmp_path)
    kwargs.update(changed)
    with pytest.raises(ValueError, match=message):
        Atlas14HyetographGrid.generate_from_depth_grid(**kwargs)


def test_generate_selects_exact_requested_ari_and_not_nearest(monkeypatch, tmp_path):
    monkeypatch.setattr(
        Atlas14Grid,
        "get_pfe_for_bounds",
        lambda **_kwargs: {
            "ari": np.array([50, 100, 200]),
            "lat": np.array([29.0, 29.1]),
            "lon": np.array([-95.1, -95.0]),
            "pfe_24hr": np.stack(
                [np.full((2, 2), 5.0), np.full((2, 2), 10.0), np.full((2, 2), 15.0)],
                axis=-1,
            ),
        },
    )
    monkeypatch.setattr(
        Atlas14HyetographGrid,
        "_shared_fraction",
        lambda **_kwargs: (np.array([0.5, 0.5]), {"source_url": "test://curve"}),
    )
    output = Atlas14HyetographGrid.generate(
        (-95.1, 29.0, -95.0, 29.1),
        100,
        24,
        720,
        state="tx",
        region=3,
        quartile="All Cases",
        probability_column="50%",
        output_netcdf=tmp_path / "exact.nc",
    )
    with xr.open_dataset(output, engine="scipy", decode_times=False) as ds:
        np.testing.assert_allclose(ds["storm_total"], 10.0)

    with pytest.raises(ValueError, match="not an exact"):
        Atlas14HyetographGrid.generate(
            (-95.1, 29.0, -95.0, 29.1),
            101,
            24,
            720,
            state="tx",
            region=3,
            quartile="All Cases",
            probability_column="50%",
            output_netcdf=tmp_path / "not-exact.nc",
        )


def test_asc_wrapper_scales_crops_and_preserves_nodata(monkeypatch, tmp_path):
    pytest.importorskip("rasterio")
    asc_path = tmp_path / "depth.asc"
    asc_path.write_text(
        "ncols 3\n"
        "nrows 2\n"
        "xllcorner -95.0\n"
        "yllcorner 29.0\n"
        "cellsize 0.01\n"
        "NODATA_value -9999\n"
        "10000 11000 -9999\n"
        "12000 13000 14000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        Atlas14HyetographGrid,
        "_shared_fraction",
        lambda **_kwargs: (np.array([1.0]), {"source_url": "test://curve"}),
    )
    output = Atlas14HyetographGrid.generate_from_asc_file(
        asc_path,
        scale_factor=0.001,
        source_crs="EPSG:4269",
        ari_years=100,
        storm_duration_hours=24,
        timestep_minutes=1440,
        state="tx",
        region=3,
        quartile="All Cases",
        probability_column="50%",
        output_netcdf=tmp_path / "from-asc.nc",
        bounds=(-95.0, 29.0, -94.97, 29.02),
    )
    with xr.open_dataset(output, engine="scipy", decode_times=False) as ds:
        assert ds.sizes["x"] == 3
        assert ds.sizes["y"] == 2
        np.testing.assert_allclose(ds["storm_total"].isel(y=0, x=0), 10.0)
        assert np.isnan(ds["storm_total"].isel(y=0, x=2))
        metadata = json.loads(ds.attrs["depth_source_metadata"])
        assert metadata["source_filename"] == "depth.asc"
        assert metadata["scale_factor_to_inches"] == 0.001
        assert metadata["source_crs"] == "EPSG:4269"

    with pytest.raises(ValueError, match="must differ"):
        Atlas14HyetographGrid.generate_from_asc_file(
            asc_path,
            scale_factor=0.001,
            source_crs="EPSG:4269",
            ari_years=100,
            storm_duration_hours=24,
            timestep_minutes=1440,
            state="tx",
            region=3,
            quartile="All Cases",
            probability_column="50%",
            output_netcdf=asc_path,
        )


def test_asc_wrapper_rejects_conflicting_embedded_crs(monkeypatch, tmp_path):
    pytest.importorskip("rasterio")
    pyproj = pytest.importorskip("pyproj")
    asc_path = tmp_path / "depth.asc"
    asc_path.write_text(
        "ncols 2\nnrows 2\nxllcorner -95\nyllcorner 29\ncellsize 0.01\n"
        "NODATA_value -9999\n10000 10000\n10000 10000\n",
        encoding="utf-8",
    )
    asc_path.with_suffix(".prj").write_text(
        pyproj.CRS("EPSG:4326").to_wkt(), encoding="utf-8"
    )
    monkeypatch.setattr(
        Atlas14HyetographGrid,
        "_shared_fraction",
        lambda **_kwargs: (np.array([1.0]), {"source_url": "test://curve"}),
    )
    with pytest.raises(ValueError, match="does not match"):
        Atlas14HyetographGrid.generate_from_asc_file(
            asc_path,
            scale_factor=0.001,
            source_crs="EPSG:4269",
            ari_years=100,
            storm_duration_hours=24,
            timestep_minutes=1440,
            state="tx",
            region=3,
            quartile="All Cases",
            probability_column="50%",
            output_netcdf=tmp_path / "mismatch.nc",
        )


def test_rejects_geocentric_crs_and_marks_us_survey_foot_coordinates(monkeypatch, tmp_path):
    monkeypatch.setattr(
        Atlas14HyetographGrid,
        "_shared_fraction",
        lambda **_kwargs: (np.array([1.0]), {"source_url": "test://curve"}),
    )
    base = _grid_kwargs(
        tmp_path,
        output_netcdf=tmp_path / "feet.nc",
        source_crs="EPSG:2278",
        x=np.array([3_100_000.0, 3_101_000.0]),
        y=np.array([13_700_000.0, 13_701_000.0]),
        timestep_minutes=1440,
    )
    output = Atlas14HyetographGrid.generate_from_depth_grid(**base)
    with xr.open_dataset(output, engine="scipy", decode_times=False) as ds:
        assert ds["x"].attrs["units"] == "US_survey_foot"
        assert ds["x"].attrs["unit_conversion_to_meters"] == pytest.approx(1200.0 / 3937.0)
        assert ds["time"].values[0] == pytest.approx(24.0)
        assert ds["precip_incremental"].sizes["time"] == 1

    with pytest.raises(ValueError, match="geographic or projected"):
        Atlas14HyetographGrid.generate_from_depth_grid(**_grid_kwargs(
            tmp_path,
            output_netcdf=tmp_path / "geocentric.nc",
            source_crs="EPSG:4978",
        ))


def test_refuses_existing_output_without_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr(
        Atlas14HyetographGrid,
        "_shared_fraction",
        lambda **_kwargs: (np.array([1.0]), {"source_url": "test://curve"}),
    )
    kwargs = _grid_kwargs(tmp_path, timestep_minutes=1440)
    Atlas14HyetographGrid.generate_from_depth_grid(**kwargs)
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        Atlas14HyetographGrid.generate_from_depth_grid(**kwargs)


def test_rejects_nonconserving_temporal_fraction(monkeypatch, tmp_path):
    monkeypatch.setattr(
        Atlas14HyetographGrid,
        "_shared_fraction",
        lambda **_kwargs: (np.array([0.5, 0.6]), {"source_url": "test://curve"}),
    )
    with pytest.raises(ValueError, match="failed depth conservation"):
        Atlas14HyetographGrid.generate_from_depth_grid(**_grid_kwargs(
            tmp_path,
            timestep_minutes=720,
            output_netcdf=tmp_path / "nonconserving.nc",
        ))
