"""NOAA ASCII units and QC regressions using real Houston PFDS grid cells."""
from pathlib import Path

import numpy as np
import pytest

xr = pytest.importorskip("xarray")
from ras_commander.precip import AbmHyetographGrid


DATA = Path(__file__).parent / "data" / "atlas14_houston"
DURATIONS = {"05m": 5/60, "10m": 10/60, "15m": .25, "30m": .5,
             "60m": 1, "02h": 2, "03h": 3, "06h": 6, "12h": 12, "24h": 24}


@pytest.fixture
def generated(tmp_path):
    return AbmHyetographGrid.generate_from_asc_files(
        {duration: DATA / f"houston_{label}.asc" for label, duration in DURATIONS.items()},
        ari_years=100, storm_duration_hours=24, timestep_minutes=6,
        output_netcdf=tmp_path / "houston.nc",
    )


def test_noaa_default_units_and_independent_total(generated):
    raw = np.loadtxt(DATA / "houston_24h.asc", skiprows=6)
    with xr.open_dataset(generated, decode_timedelta=False) as ds:
        assert ds.attrs['temporal_method'] == 'alternating_block'
        assert ds.attrs['spatial_method'] == 'per_cell_depth_duration_curve'
        assert ds.attrs['areal_reduction'] == 'none_applied_by_api'
        assert ds.attrs['block_order'] == 'descending_increment_depth_left_first'
        np.testing.assert_allclose(ds.precip_incremental.sum("time"), raw / 1000,
                                   rtol=1e-6)
        lat, lon = float(ds.lat[0]), float(ds.lon[0])
    qc = AbmHyetographGrid.verify_pixel(generated, lat, lon, expected_depth_inches=16.905)
    assert qc["passed"]
    assert qc["validation_scope"] == "independent_total_and_internal_consistency"
    assert qc["reference_source"] == "expected_depth_inches"


@pytest.mark.parametrize("factor", [.001, .01, 1.0])
def test_explicit_scale_override(factor):
    data, lat, lon, nodata = AbmHyetographGrid._load_asc_file(
        DATA / "houston_24h.asc", scale_factor=factor)
    assert data[0, 0] == pytest.approx(16905 * factor)
    assert nodata == pytest.approx(-9 * factor)
    assert lat[0] > lat[-1] and lon[0] < lon[-1]


@pytest.mark.parametrize("factor", [0, -1, np.nan, np.inf])
def test_invalid_scale(factor):
    with pytest.raises(ValueError, match="scale_factor"):
        AbmHyetographGrid._load_asc_file(DATA / "houston_24h.asc", scale_factor=factor)


def _series_file(tmp_path, increments, cumulative=None, units="inches"):
    increments = np.asarray(increments, dtype=float)
    cumulative = np.cumsum(increments) if cumulative is None else np.asarray(cumulative)
    ds = xr.Dataset(
        {"precip_incremental": (("time", "lat", "lon"), increments[:, None, None], {"units": units}),
         "precip_cumulative": (("time", "lat", "lon"), cumulative[:, None, None], {"units": units})},
        coords={"time": np.arange(len(increments)), "lat": [29.75], "lon": [-95.45]},
    )
    path = tmp_path / "series.nc"
    ds.to_netcdf(path)
    return path


@pytest.mark.parametrize("increments,cumulative", [
    ([np.nan, np.nan], None), ([1, np.nan], None), ([1, np.inf], None),
    ([-1, 2], None), ([1, 2], [1, np.nan]), ([1, 2], [1, -3]),
    ([], []), ([1, 2], [1, 0]), ([1, 2], [2, 3]),
])
def test_invalid_or_inconsistent_series_fails(tmp_path, increments, cumulative):
    path = _series_file(tmp_path, increments, cumulative)
    qc = AbmHyetographGrid.verify_pixel(path, 29.75, -95.45)
    assert not qc["passed"]
    assert qc["failure_reasons"]


def test_common_scale_error_requires_independent_reference(tmp_path):
    path = _series_file(tmp_path, [50, 119.05])
    internal = AbmHyetographGrid.verify_pixel(path, 29.75, -95.45)
    assert internal["passed"]
    assert internal["validation_scope"] == "internal_consistency_only"
    independent = AbmHyetographGrid.verify_pixel(
        path, 29.75, -95.45, expected_depth_inches=16.905)
    assert not independent["passed"]
    assert independent["error_pct"] == pytest.approx(900)


@pytest.mark.parametrize("increments,expected,passed", [([0, 0], 0, True),
    ([0, 1], 0, False), ([0, 0], 1, False)])
def test_zero_reference(tmp_path, increments, expected, passed):
    qc = AbmHyetographGrid.verify_pixel(_series_file(tmp_path, increments), 29.75, -95.45,
                                       expected_depth_inches=expected)
    assert qc["passed"] is passed


@pytest.mark.parametrize("kwargs", [{"tolerance_pct": -1}, {"tolerance_pct": np.nan},
    {"tolerance_pct": np.inf}, {"expected_depth_inches": -1},
    {"expected_depth_inches": np.nan}, {"expected_depth_inches": np.inf}])
def test_invalid_qc_arguments(tmp_path, kwargs):
    with pytest.raises(ValueError):
        AbmHyetographGrid.verify_pixel(tmp_path / "unused.nc", 29.75, -95.45, **kwargs)


def test_wrong_units_fail(tmp_path):
    qc = AbmHyetographGrid.verify_pixel(_series_file(tmp_path, [1, 2], units="mm"), 29.75, -95.45)
    assert not qc["passed"]
    assert "inches" in qc["failure_reasons"][0]


def test_ascii_nodata_survives_scaling_and_fails_qc(tmp_path):
    # NOAA's raw -9 sentinel must remain missing after the 0.001 conversion.
    files = {}
    for duration in (12, 24):
        lines = (DATA / f"houston_{duration}h.asc").read_text().splitlines()
        cells = lines[6].split()
        cells[0] = "-9"
        lines[6] = " ".join(cells)
        asc = tmp_path / f"nodata_{duration}h.asc"
        asc.write_text("\n".join(lines) + "\n")
        files[duration] = asc
    output = AbmHyetographGrid.generate_from_asc_files(
        files, 100, 24, output_netcdf=tmp_path / "nodata.nc")
    with xr.open_dataset(output, decode_timedelta=False) as ds:
        lat, lon = float(ds.lat[0]), float(ds.lon[0])
        assert np.all(np.isnan(ds.precip_incremental[:, 0, 0]))
    qc = AbmHyetographGrid.verify_pixel(output, lat, lon)
    assert not qc["passed"]
    assert np.isnan(qc["pixel_total_in"])
