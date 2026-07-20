import logging
from pathlib import Path
import re

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pyproj import Transformer
from shapely.geometry import box

from ras_commander import RasUnsteady
from ras_commander.precip import AbmHyetographGrid, Atlas14Grid


ABM_LOGGER = "ras_commander.precip.AbmHyetographGrid"
ATLAS_LOGGER = "ras_commander.precip.Atlas14Grid"
VALUES_PATH = (
    "Event Conditions/Meteorology/Precipitation/"
    "Imported Raster Data/Values"
)


def _write_abm_source(
    path: Path,
    *,
    units: str = "inches",
    time_units: str = "hours",
) -> Path:
    increments = np.array(
        [
            [
                [0.10, 0.12, 0.14],
                [0.16, 0.18, 0.20],
                [0.22, 0.24, 0.26],
            ],
            [
                [0.30, 0.32, 0.34],
                [0.36, 0.38, 0.40],
                [0.42, 0.44, 0.46],
            ],
            [
                [0.20, 0.22, 0.24],
                [0.26, 0.28, 0.30],
                [0.32, 0.34, 0.36],
            ],
        ],
        dtype=np.float32,
    )
    ds = xr.Dataset(
        data_vars={
            "precip_incremental": (
                ("time", "lat", "lon"),
                increments,
                {"units": units, "cell_methods": "time: sum"},
            ),
            "precip_cumulative": (
                ("time", "lat", "lon"),
                np.cumsum(increments, axis=0),
                {"units": units},
            ),
        },
        coords={
            "time": ("time", [0.0, 0.25, 0.5], {"units": time_units}),
            "lat": ("lat", [40.00, 40.01, 40.02]),
            "lon": ("lon", [-77.02, -77.01, -77.00]),
        },
    )
    ds.to_netcdf(path, engine="netcdf4")
    return path


def test_to_ras_netcdf_writes_absolute_projected_rate_grid(tmp_path, caplog):
    source = _write_abm_source(tmp_path / "abm.nc")
    output = tmp_path / "forcing.nc"

    with caplog.at_level(logging.DEBUG, logger=ABM_LOGGER):
        result = AbmHyetographGrid.to_ras_netcdf(
            source,
            output,
            start_time="2018-09-09 00:00:00",
        )

    assert result == output.resolve()
    with xr.open_dataset(result) as ds:
        forcing = ds["APCP_surface"]
        assert forcing.dims == ("time", "y", "x")
        assert forcing.sizes["time"] == 4
        assert pd.to_datetime(forcing.time.values).tolist() == [
            pd.Timestamp("2018-09-09 00:00:00"),
            pd.Timestamp("2018-09-09 00:15:00"),
            pd.Timestamp("2018-09-09 00:30:00"),
            pd.Timestamp("2018-09-09 00:45:00"),
        ]
        np.testing.assert_allclose(
            forcing.isel(time=0).values[np.isfinite(forcing.isel(time=0).values)],
            0.0,
        )
        assert forcing.attrs["units"] == "mm/hr"
        assert forcing.attrs["grid_mapping"] == "spatial_ref"
        assert "spatial_ref" in ds.variables
        assert "Albers" in ds["spatial_ref"].attrs["crs_wkt"]
        assert ds.attrs["target_crs"] == "EPSG:5070"
        assert ds.attrs["storm_end"] == "2018-09-09T00:45:00"
        assert ds.attrs["forcing_end"] == "2018-09-09T00:45:00"
        assert ds.attrs["zero_tail_frames"] == 0
        assert ds.attrs["zero_tail_hours"] == 0.0
        assert ds.attrs["depth_conservation_max_error_mm"] <= 1e-4
        assert 0.0 < ds.attrs["valid_coverage_fraction"] <= 1.0

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == ABM_LOGGER and record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == ABM_LOGGER and record.levelno == logging.DEBUG
    ]
    assert any("Prepared HEC-RAS Atlas 14 forcing forcing.nc" in msg for msg in info_messages)
    assert any("0 zero-tail frames (0 hr)" in msg for msg in info_messages)
    assert all(str(tmp_path) not in msg for msg in info_messages)
    assert any(str(output.resolve()) in msg for msg in debug_messages)


def test_to_ras_netcdf_extends_zero_rates_through_aligned_end(tmp_path):
    source = _write_abm_source(tmp_path / "abm.nc")
    output = AbmHyetographGrid.to_ras_netcdf(
        source,
        tmp_path / "forcing.nc",
        start_time="2018-09-09 00:00:00",
        end_time="2018-09-09 01:30:00",
    )

    with xr.open_dataset(output) as ds:
        forcing = ds["APCP_surface"]
        assert pd.to_datetime(forcing.time.values).tolist() == [
            pd.Timestamp("2018-09-09 00:00:00"),
            pd.Timestamp("2018-09-09 00:15:00"),
            pd.Timestamp("2018-09-09 00:30:00"),
            pd.Timestamp("2018-09-09 00:45:00"),
            pd.Timestamp("2018-09-09 01:00:00"),
            pd.Timestamp("2018-09-09 01:15:00"),
            pd.Timestamp("2018-09-09 01:30:00"),
        ]
        tail = forcing.isel(time=slice(4, None)).values
        np.testing.assert_allclose(tail[np.isfinite(tail)], 0.0)

        storm_total = forcing.isel(time=slice(1, 4)).sum("time", skipna=False)
        forcing_total = forcing.isel(time=slice(1, None)).sum(
            "time",
            skipna=False,
        )
        xr.testing.assert_allclose(forcing_total, storm_total)

        assert ds.attrs["storm_end"] == "2018-09-09T00:45:00"
        assert ds.attrs["forcing_end"] == "2018-09-09T01:30:00"
        assert ds.attrs["zero_tail_frames"] == 3
        assert ds.attrs["zero_tail_hours"] == 0.75


def test_to_ras_netcdf_imports_with_exact_hdf_depth_and_times(tmp_path):
    source = _write_abm_source(tmp_path / "abm.nc")
    output = AbmHyetographGrid.to_ras_netcdf(
        source,
        tmp_path / "forcing.nc",
        start_time="2018-09-09 00:00:00",
        end_time="2018-09-09 01:30:00",
    )
    hdf_path = tmp_path / "example.u01.hdf"
    with h5py.File(hdf_path, "w"):
        pass

    RasUnsteady._update_precipitation_hdf(
        hdf_path=hdf_path,
        netcdf_path=output,
        netcdf_rel_path=".\\P\\forcing.nc",
        interpolation="Bilinear",
        dataset_name="APCP_surface",
    )

    with xr.open_dataset(output) as ds:
        expected_total_mm = float(
            (ds["APCP_surface"].isel(time=slice(1, None)).sum("time") * 0.25)
            .max(skipna=True)
            .item()
        )

    with h5py.File(hdf_path, "r") as hdf:
        values = hdf[VALUES_PATH]
        assert values.shape[0] == 7
        np.testing.assert_allclose(values[0], 0.0)
        assert values.attrs["Times"].tolist() == [
            b"2018-09-09 00:00:00",
            b"2018-09-09 00:15:00",
            b"2018-09-09 00:30:00",
            b"2018-09-09 00:45:00",
            b"2018-09-09 01:00:00",
            b"2018-09-09 01:15:00",
            b"2018-09-09 01:30:00",
        ]
        assert values.attrs["Units"] == b"mm"
        assert float(np.nanmax(values[-1])) == pytest.approx(
            expected_total_mm,
            rel=1e-6,
        )
        np.testing.assert_allclose(
            values[4:],
            np.broadcast_to(values[3], values[4:].shape),
        )
        np.testing.assert_allclose(np.diff(values[3:], axis=0), 0.0)


def test_to_ras_netcdf_covers_inner_project_footprint(tmp_path):
    source = _write_abm_source(tmp_path / "abm.nc")
    output = AbmHyetographGrid.to_ras_netcdf(
        source,
        tmp_path / "forcing.nc",
        start_time="2018-09-09 00:00:00",
    )
    project_points_lonlat = [
        (-77.012, 40.004),
        (-77.008, 40.004),
        (-77.012, 40.006),
        (-77.008, 40.006),
        (-77.010, 40.005),
    ]
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    project_x, project_y = transformer.transform(
        [point[0] for point in project_points_lonlat],
        [point[1] for point in project_points_lonlat],
    )

    with xr.open_dataset(output) as ds:
        sampled = ds["APCP_surface"].isel(time=1).sel(
            x=xr.DataArray(project_x, dims="point"),
            y=xr.DataArray(project_y, dims="point"),
            method="nearest",
        )
        assert np.isfinite(sampled.values).all()
        assert (sampled.values > 0.0).all()


def test_to_ras_netcdf_accepts_atlas_float32_coordinate_quantization(tmp_path):
    source = _write_abm_source(tmp_path / "abm.nc")
    with xr.open_dataset(
        source,
        engine="netcdf4",
        decode_timedelta=False,
    ) as original:
        quantized = original.load()
    quantized = quantized.assign_coords(
        lat=[40.0000000, 40.0083313, 40.0166664],
        lon=[-77.0166664, -77.0083313, -77.0000000],
    )
    quantized.to_netcdf(source, mode="w", engine="netcdf4")

    output = AbmHyetographGrid.to_ras_netcdf(
        source,
        tmp_path / "forcing.nc",
        start_time="2018-09-09 00:00:00",
    )

    assert output.exists()


@pytest.mark.parametrize("time_units", ["h", "hour", "hours", "hr", "hrs"])
def test_to_ras_netcdf_accepts_hour_unit_spellings(tmp_path, time_units):
    source = _write_abm_source(
        tmp_path / "abm.nc",
        time_units=time_units,
    )

    output = AbmHyetographGrid.to_ras_netcdf(
        source,
        tmp_path / "forcing.nc",
        start_time="2018-09-09 00:00:00",
    )

    assert output.exists()


@pytest.mark.parametrize(
    ("invalid_case", "message"),
    [
        ("units", "units must be inches"),
        ("time_units", "time coordinate units must be hours"),
        ("non_numeric_time", "numeric relative-hour values"),
        ("irregular_time", "strictly increasing and regular"),
        ("irregular_lat", "lat coordinate must be regularly spaced"),
        ("irregular_lon", "lon coordinate must be regularly spaced"),
        ("latitude_range", "latitude values must be within"),
        ("longitude_range", "longitude values must be within"),
        ("negative", "negative precipitation"),
    ],
)
def test_to_ras_netcdf_rejects_invalid_source(tmp_path, invalid_case, message):
    source = _write_abm_source(tmp_path / "abm.nc")
    with xr.open_dataset(
        source,
        engine="netcdf4",
        decode_timedelta=False,
    ) as original:
        changed = original.load()
    if invalid_case == "units":
        changed["precip_incremental"].attrs["units"] = "mm"
    elif invalid_case == "time_units":
        changed["time"].attrs["units"] = "minutes"
    elif invalid_case == "non_numeric_time":
        changed = changed.assign_coords(time=["zero", "quarter", "half"])
        changed["time"].attrs["units"] = "hours"
    elif invalid_case == "irregular_time":
        changed = changed.assign_coords(time=[0.0, 0.25, 0.75])
        changed["time"].attrs["units"] = "hours"
    elif invalid_case == "irregular_lat":
        changed = changed.assign_coords(lat=[40.00, 40.01, 40.03])
    elif invalid_case == "irregular_lon":
        changed = changed.assign_coords(lon=[-77.02, -77.015, -77.00])
    elif invalid_case == "latitude_range":
        changed = changed.assign_coords(lat=[89.00, 90.00, 91.00])
    elif invalid_case == "longitude_range":
        changed = changed.assign_coords(lon=[-181.00, -180.00, -179.00])
    else:
        changed["precip_incremental"].values[0, 0, 0] = -0.1
    changed.to_netcdf(source, mode="w", engine="netcdf4")

    with pytest.raises(ValueError, match=message):
        AbmHyetographGrid.to_ras_netcdf(
            source,
            tmp_path / "forcing.nc",
            start_time="2018-09-09 00:00:00",
        )


def test_to_ras_netcdf_rejects_ambiguous_output_configuration(tmp_path):
    source = _write_abm_source(tmp_path / "abm.nc")

    with pytest.raises(ValueError, match="must differ"):
        AbmHyetographGrid.to_ras_netcdf(
            source,
            source,
            start_time="2018-09-09 00:00:00",
        )
    with pytest.raises(ValueError, match="timezone-naive"):
        AbmHyetographGrid.to_ras_netcdf(
            source,
            tmp_path / "forcing.nc",
            start_time="2018-09-09 00:00:00+00:00",
        )
    with pytest.raises(ValueError, match="projected"):
        AbmHyetographGrid.to_ras_netcdf(
            source,
            tmp_path / "forcing.nc",
            start_time="2018-09-09 00:00:00",
            target_crs="EPSG:4326",
        )
    with pytest.raises(ValueError, match="timezone-naive"):
        AbmHyetographGrid.to_ras_netcdf(
            source,
            tmp_path / "forcing.nc",
            start_time="2018-09-09 00:00:00",
            end_time="2018-09-09 01:30:00+00:00",
        )
    with pytest.raises(ValueError, match="on or after the natural storm end"):
        AbmHyetographGrid.to_ras_netcdf(
            source,
            tmp_path / "forcing.nc",
            start_time="2018-09-09 00:00:00",
            end_time="2018-09-09 00:30:00",
        )
    with pytest.raises(ValueError, match="align with the source timestep"):
        AbmHyetographGrid.to_ras_netcdf(
            source,
            tmp_path / "forcing.nc",
            start_time="2018-09-09 00:00:00",
            end_time="2018-09-09 00:50:00",
        )


def test_atlas14_extent_logs_filename_at_info_and_path_at_debug(
    tmp_path,
    monkeypatch,
    caplog,
):
    geom_hdf = tmp_path / "nested" / "Project.g09.hdf"
    geom_hdf.parent.mkdir()
    geom_hdf.touch()
    mesh = gpd.GeoDataFrame(
        {"mesh_name": ["BaldEagleCr"]},
        geometry=[box(-77.75, 40.96, -77.33, 41.18)],
        crs="EPSG:4326",
    )

    from ras_commander.hdf import HdfMesh

    monkeypatch.setattr(HdfMesh, "get_mesh_areas", lambda *_args, **_kwargs: mesh)
    monkeypatch.setattr(
        Atlas14Grid,
        "get_pfe_for_bounds",
        lambda **kwargs: {"bounds": kwargs["bounds"]},
    )

    with caplog.at_level(logging.DEBUG, logger=ATLAS_LOGGER):
        Atlas14Grid.get_pfe_from_project(geom_hdf, buffer_percent=0.0)

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == ATLAS_LOGGER and record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == ATLAS_LOGGER and record.levelno == logging.DEBUG
    ]
    assert any(
        "Extracting Atlas 14 extent from Project.g09.hdf using 2d_flow_area" in msg
        for msg in info_messages
    )
    assert all(str(tmp_path) not in msg for msg in info_messages)
    assert any(str(geom_hdf.resolve()) in msg for msg in debug_messages)


def test_atlas14_subset_log_reports_payload_without_rounded_reduction(
    monkeypatch,
    caplog,
):
    lat = np.array([40.0, 40.01])
    lon = np.array([-77.02, -77.01, -77.00])
    ari = np.array(Atlas14Grid.AVAILABLE_RETURN_PERIODS)
    varname = Atlas14Grid._duration_to_varname(24)

    class _RemoteFile:
        def __enter__(self):
            return {varname: np.full((2, 3, 9), 100, dtype=np.int16)}

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(Atlas14Grid, "_load_coordinates", lambda: (lat, lon, ari))
    monkeypatch.setattr(
        Atlas14Grid,
        "_get_spatial_indices",
        lambda _bounds: (np.array([0, 1]), np.array([0, 1, 2])),
    )
    monkeypatch.setattr(Atlas14Grid, "_get_remote_file", lambda: _RemoteFile())

    with caplog.at_level(logging.INFO, logger=ATLAS_LOGGER):
        Atlas14Grid.get_pfe_for_bounds(
            bounds=(-77.02, 40.0, -77.0, 40.01),
            durations=[24],
            return_periods=[100],
        )

    subset_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == ATLAS_LOGGER and "Atlas 14 subset:" in record.getMessage()
    ]
    assert len(subset_messages) == 1
    message = subset_messages[0]
    assert "estimated full-grid payload" in message
    assert "2x3 cells" in message
    assert "% of full grid" in message
    assert "reduction" not in message.lower()
    percent_match = re.search(r"([0-9.eE+-]+)% of full grid", message)
    assert percent_match is not None
    assert float(percent_match.group(1)) > 0.0
    assert "0.0000% of full grid" not in message
