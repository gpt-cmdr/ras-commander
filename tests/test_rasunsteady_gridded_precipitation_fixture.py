from pathlib import Path
from types import SimpleNamespace
import uuid

import h5py
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ras_commander import RasUnsteady


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "precipitation" / "gdal_netcdf_davis"
NETCDF_FIXTURE = FIXTURE_DIR / "clb704_precip_5step.nc"
GUI_U01_FIXTURE = FIXTURE_DIR / "DavisStormSystem.gui_imported.u01"
GUI_PLAN_HDF_FIXTURE = FIXTURE_DIR / "DavisStormSystem.gui_imported.p02.precipitation.hdf"
VALUES_PATH = "Event Conditions/Meteorology/Precipitation/Imported Raster Data/Values"
VALUES_VERTICAL_PATH = "Event Conditions/Meteorology/Precipitation/Imported Raster Data/Values (Vertical)"


def _bytes_attr_to_text(value):
    if isinstance(value, np.bytes_):
        return value.tobytes().decode("utf-8")
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _assert_hdf_attr_equal(actual, expected):
    if isinstance(expected, np.ndarray):
        assert isinstance(actual, np.ndarray)
        assert actual.dtype == expected.dtype
        assert actual.shape == expected.shape
        np.testing.assert_array_equal(actual, expected)
        return

    if isinstance(expected, (bytes, np.bytes_)):
        assert isinstance(actual, (bytes, np.bytes_))
        assert _bytes_attr_to_text(actual) == _bytes_attr_to_text(expected)
        return

    if isinstance(expected, np.generic):
        assert type(actual) is type(expected)
        assert actual == expected
        return

    assert actual == expected


def _assert_dataset_matches(actual, expected):
    assert actual.shape == expected.shape
    assert actual.dtype == expected.dtype
    assert actual.chunks == expected.chunks
    assert actual.compression == expected.compression
    assert actual.compression_opts == expected.compression_opts

    expected_fill = expected.fillvalue
    actual_fill = actual.fillvalue
    expected_fill_array = np.asarray(expected_fill)
    if np.issubdtype(expected_fill_array.dtype, np.floating) and np.isnan(expected_fill_array).all():
        assert np.isnan(np.asarray(actual_fill)).all()
    else:
        assert actual_fill == expected_fill

    np.testing.assert_array_equal(actual[...], expected[...])
    assert set(actual.attrs.keys()) == set(expected.attrs.keys())
    for attr_name, expected_value in expected.attrs.items():
        _assert_hdf_attr_equal(actual.attrs[attr_name], expected_value)


def _reference_projection_wkt() -> str:
    with h5py.File(GUI_PLAN_HDF_FIXTURE, "r") as hdf:
        return _bytes_attr_to_text(hdf[VALUES_PATH].attrs["Projection"])


def _write_precip_netcdf(path: Path, values, times, crs_metadata, variable: str = "APCP_surface") -> Path:
    values = np.asarray(values, dtype=np.float32)
    y_count, x_count = values.shape[1], values.shape[2]
    ds = xr.Dataset(
        data_vars={
            variable: (
                ("time", "y", "x"),
                values,
                {"units": "mm/hr", "grid_mapping": "spatial_ref"},
            ),
            "spatial_ref": (
                (),
                np.int32(0),
                {"spatial_ref": crs_metadata, "crs_wkt": crs_metadata},
            ),
        },
        coords={
            "time": pd.to_datetime(times),
            "x": np.arange(x_count, dtype=np.float64) + 0.5,
            "y": np.arange(y_count, dtype=np.float64)[::-1] + 0.5,
        },
    )
    ds.to_netcdf(path, engine="netcdf4")
    return path


def test_clb704_netcdf_fixture_is_small():
    assert NETCDF_FIXTURE.stat().st_size < 1_000_000


def test_set_gridded_precipitation_matches_gui_imported_u01(tmp_path):
    project_dir = tmp_path
    precip_dir = project_dir / "Precipitation"
    precip_dir.mkdir()
    netcdf_path = precip_dir / NETCDF_FIXTURE.name
    netcdf_path.write_bytes(NETCDF_FIXTURE.read_bytes())

    gui_text = GUI_U01_FIXTURE.read_bytes().decode("utf-8")
    starting_text = gui_text
    starting_text = starting_text.replace("Precipitation Mode=Enable\r\n", "Precipitation Mode=Disable\r\n")
    starting_text = starting_text.replace(
        "Met BC=Precipitation|Mode=Gridded\r\n",
        "Met BC=Precipitation|Mode=None\r\n",
    )
    starting_text = starting_text.replace(
        "Met BC=Precipitation|Gridded Source=GDAL Raster File(s)\r\n",
        "Met BC=Precipitation|Gridded Source=DSS\r\n",
    )
    starting_text = starting_text.replace(
        "Met BC=Precipitation|Gridded Interpolation=Nearest\r\n",
        "Met BC=Precipitation|Gridded Interpolation=\r\n",
    )
    starting_text = starting_text.replace(
        "Met BC=Precipitation|Gridded GDAL Filename=.\\Precipitation\\clb704_precip_5step.nc\r\n",
        "",
    )
    starting_text = starting_text.replace(
        "Met BC=Precipitation|Gridded GDAL Group=APCP_surface\r\n",
        "",
    )

    unsteady_path = project_dir / "DavisStormSystem.u01"
    unsteady_path.write_bytes(starting_text.encode("utf-8"))
    ras_object = SimpleNamespace(
        project_folder=project_dir,
        project_name="DavisStormSystem",
        check_initialized=lambda: None,
    )

    RasUnsteady.set_gridded_precipitation(
        unsteady_path,
        Path("Precipitation") / NETCDF_FIXTURE.name,
        interpolation="Nearest",
        ras_object=ras_object,
    )

    assert unsteady_path.read_bytes() == GUI_U01_FIXTURE.read_bytes()


def test_update_precipitation_hdf_matches_gui_imported_plan_payload(tmp_path, monkeypatch):
    output_hdf = tmp_path / "DavisStormSystem.u01.hdf"
    with h5py.File(output_hdf, "w"):
        pass

    with h5py.File(GUI_PLAN_HDF_FIXTURE, "r") as reference:
        reference_guid = _bytes_attr_to_text(reference[VALUES_PATH].attrs["GUID"])

    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(reference_guid))

    RasUnsteady._update_precipitation_hdf(
        hdf_path=output_hdf,
        netcdf_path=NETCDF_FIXTURE,
        netcdf_rel_path=".\\Precipitation\\clb704_precip_5step.nc",
        interpolation="Nearest",
    )

    with h5py.File(output_hdf, "r") as actual, h5py.File(GUI_PLAN_HDF_FIXTURE, "r") as expected:
        expected_paths = []
        expected.visit(expected_paths.append)
        actual_paths = []
        actual.visit(actual_paths.append)
        assert set(expected_paths).issubset(actual_paths)

        _assert_dataset_matches(
            actual["Event Conditions/Meteorology/Attributes"],
            expected["Event Conditions/Meteorology/Attributes"],
        )

        actual_precip = actual["Event Conditions/Meteorology/Precipitation"]
        expected_precip = expected["Event Conditions/Meteorology/Precipitation"]
        for attr_name, expected_value in expected_precip.attrs.items():
            _assert_hdf_attr_equal(actual_precip.attrs[attr_name], expected_value)
        assert actual_precip.attrs["Enabled"] == np.uint8(1)

        actual_raster = actual["Event Conditions/Meteorology/Precipitation/Imported Raster Data"]
        expected_raster = expected["Event Conditions/Meteorology/Precipitation/Imported Raster Data"]
        assert dict(actual_raster.attrs) == dict(expected_raster.attrs)

        _assert_dataset_matches(actual[VALUES_PATH], expected[VALUES_PATH])
        _assert_dataset_matches(actual[VALUES_VERTICAL_PATH], expected[VALUES_VERTICAL_PATH])

        values = actual[VALUES_PATH]
        assert values.dtype == np.dtype("float32")
        assert values.shape == (5, 6)
        assert values.attrs["Times"].dtype == np.dtype("S19")
        np.testing.assert_array_equal(values[0], np.zeros(6, dtype=np.float32))


def test_update_precipitation_hdf_scales_instantaneous_rates_by_interval_hours(tmp_path):
    netcdf_path = _write_precip_netcdf(
        tmp_path / "quarter_hour.nc",
        values=[
            [[99.0, 99.0]],
            [[4.0, 8.0]],
            [[2.0, 4.0]],
        ],
        times=[
            "2020-01-01 00:00:00",
            "2020-01-01 00:15:00",
            "2020-01-01 00:45:00",
        ],
        crs_metadata=_reference_projection_wkt(),
    )
    output_hdf = tmp_path / "quarter_hour.u01.hdf"
    with h5py.File(output_hdf, "w"):
        pass

    RasUnsteady._update_precipitation_hdf(
        hdf_path=output_hdf,
        netcdf_path=netcdf_path,
        netcdf_rel_path=".\\Precipitation\\quarter_hour.nc",
        interpolation="Nearest",
    )

    with h5py.File(output_hdf, "r") as hdf:
        np.testing.assert_allclose(
            hdf[VALUES_PATH][...],
            np.array(
                [
                    [0.0, 0.0],
                    [1.0, 2.0],
                    [2.0, 4.0],
                ],
                dtype=np.float32,
            ),
        )


def test_update_precipitation_hdf_uses_netcdf_crs_metadata(tmp_path):
    pyproj = pytest.importorskip("pyproj")
    web_mercator_wkt = pyproj.CRS.from_epsg(3857).to_wkt(version="WKT1_GDAL")
    netcdf_path = _write_precip_netcdf(
        tmp_path / "web_mercator.nc",
        values=[
            [[0.0]],
            [[1.0]],
        ],
        times=[
            "2020-01-01 00:00:00",
            "2020-01-01 01:00:00",
        ],
        crs_metadata=web_mercator_wkt,
    )
    output_hdf = tmp_path / "web_mercator.u01.hdf"
    with h5py.File(output_hdf, "w"):
        pass

    RasUnsteady._update_precipitation_hdf(
        hdf_path=output_hdf,
        netcdf_path=netcdf_path,
        netcdf_rel_path=".\\Precipitation\\web_mercator.nc",
        interpolation="Nearest",
    )

    with h5py.File(output_hdf, "r") as hdf:
        projection = _bytes_attr_to_text(hdf[VALUES_PATH].attrs["Projection"])
        assert 'PROJCS["WGS 84 / Pseudo-Mercator"' in projection
        assert "Conus Albers" not in projection
