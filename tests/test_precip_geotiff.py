from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

h5py = pytest.importorskip("h5py")
rasterio = pytest.importorskip("rasterio")
from rasterio.transform import Affine, from_origin  # noqa: E402 - optional dependency checked above

from ras_commander import RasUnsteady  # noqa: E402
from ras_commander.precip import RasPrecipGrid  # noqa: E402


def test_invalid_interpolation_fails_before_raster_io_or_cache(tmp_path):
    unsteady = tmp_path / "GeoTiffRain.u01"
    unsteady.write_text("Flow Title=Rain\nProgram Version=6.60\n")
    before = unsteady.read_bytes()
    with pytest.raises(ValueError, match="interpolation"):
        RasUnsteady.set_gridded_precipitation_geotiff(
            unsteady, tmp_path / "nonexistent.tif", timestamps=["2024-01-01"],
            units="mm", value_type="amount", interpolation="Kriging",
            ras_object=_dummy_project(tmp_path),
        )
    assert unsteady.read_bytes() == before
    assert list(tmp_path.iterdir()) == [unsteady]


def _write_tiff(
    path: Path,
    values: np.ndarray,
    *,
    transform: Affine = from_origin(100.0, 200.0, 10.0, 10.0),
    crs: str = "EPSG:5070",
    nodata: float | None = None,
    units: str | None = None,
) -> Path:
    data = np.asarray(values, dtype=np.float32)
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[2],
        height=data.shape[1],
        count=data.shape[0],
        dtype="float32",
        transform=transform,
        crs=crs,
        nodata=nodata,
    ) as dataset:
        dataset.write(data)
        if units:
            for band in dataset.indexes:
                dataset.update_tags(band, units=units)
    return path


def _dummy_project(folder: Path, version: str = "6.6") -> SimpleNamespace:
    project = SimpleNamespace(
        project_folder=folder,
        project_name="GeoTiffRain",
        ras_version=version,
    )
    project.check_initialized = lambda: None
    return project


def test_multiband_geotiff_normalizes_to_cumulative_north_up_cube(tmp_path):
    values = np.array(
        [
            [[1, 2, 3], [4, 5, 6]],
            [[2, 0, 1], [0, 3, 1]],
            [[0, 1, 0], [2, 0, 4]],
        ],
        dtype=np.float32,
    )
    source = _write_tiff(tmp_path / "rain.tif", values, units="mm")

    cube = RasPrecipGrid.from_geotiff(
        source,
        timestamps=pd.date_range("2024-01-01 00:00", periods=3, freq="15min"),
        units="mm",
        value_type="amount",
        first_timestep_hours=0.25,
    )

    assert cube.values.shape == (4, 2, 3)
    np.testing.assert_array_equal(cube.values[0], 0.0)
    np.testing.assert_array_equal(cube.values[1], values[0])
    np.testing.assert_array_equal(cube.values[-1], values.sum(axis=0))
    assert cube.timestamps[0] == pd.Timestamp("2023-12-31 23:45")
    assert tuple(cube.x) == (105.0, 115.0, 125.0)
    assert tuple(cube.y) == (195.0, 185.0)


def test_geotiff_sequence_uses_explicit_order_not_filename_sort(tmp_path):
    first = _write_tiff(tmp_path / "z-last-name.tif", np.array([[1, 2], [3, 4]]))
    second = _write_tiff(tmp_path / "a-first-name.tif", np.array([[5, 6], [7, 8]]))

    cube = RasPrecipGrid.from_geotiff(
        [first, second],
        timestamps=["2024-01-01 01:00", "2024-01-01 02:00"],
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
    )

    np.testing.assert_array_equal(cube.values[1], [[1, 2], [3, 4]])
    np.testing.assert_array_equal(cube.values[2], [[6, 8], [10, 12]])


def test_geotiff_nodata_requires_explicit_zero_policy(tmp_path):
    source = _write_tiff(
        tmp_path / "nodata.tif",
        np.array([[1.0, -9999.0], [2.0, 3.0]]),
        nodata=-9999.0,
    )
    kwargs = dict(
        timestamps=["2024-01-01 01:00"],
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
    )

    with pytest.raises(ValueError, match="NoData pixels"):
        RasPrecipGrid.from_geotiff(source, **kwargs)

    cube = RasPrecipGrid.from_geotiff(source, nodata_policy="zero", **kwargs)
    assert cube.nodata_count == 1
    assert cube.values[-1, 0, 1] == 0.0


@pytest.mark.parametrize(
    "transform, message",
    [
        (Affine(10, 1, 100, 0, -10, 200), "rotated or sheared"),
        (Affine(10, 0, 100, 0, 10, 200), "north-up"),
        (Affine(10, 0, 100, 0, -20, 200), "square"),
    ],
)
def test_geotiff_rejects_unsupported_grid_geometry(tmp_path, transform, message):
    source = _write_tiff(tmp_path / "grid.tif", np.ones((2, 2)), transform=transform)

    with pytest.raises(ValueError, match=message):
        RasPrecipGrid.from_geotiff(
            source,
            timestamps=["2024-01-01 01:00"],
            units="mm",
            value_type="amount",
            first_timestep_hours=1.0,
        )


def test_geotiff_cache_is_content_addressed_validated_and_reused(tmp_path):
    source = _write_tiff(tmp_path / "rain.tif", np.ones((2, 2)))
    cube = RasPrecipGrid.from_geotiff(
        source,
        timestamps=["2024-01-01 01:00"],
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
    )
    destination = tmp_path / "cache" / "rain.nc"

    first = RasPrecipGrid.to_ras_netcdf(cube, destination)
    second = RasPrecipGrid.to_ras_netcdf(cube, destination)

    assert first.reused is False
    assert second.reused is True
    assert destination.is_file()
    assert not list(destination.parent.glob("*.partial.nc"))

    # Independent GDAL reader: x/y coordinates can hide malformed GeoTransform
    # metadata from our native HDF writer, so verify the exported raster itself.
    with rasterio.open(f'NETCDF:"{destination}":precipitation') as reopened:
        assert reopened.transform == cube.transform
        assert reopened.crs == rasterio.crs.CRS.from_wkt(cube.crs_wkt)
        assert reopened.bounds == rasterio.transform.array_bounds(2, 2, cube.transform)
        np.testing.assert_array_equal(reopened.read(reopened.count), cube.values[-1])


def test_semantic_hash_and_default_cache_survive_source_relocation(tmp_path):
    first = _write_tiff(tmp_path / "first-name.tif", np.ones((2, 2)))
    second = tmp_path / "moved-and-renamed.tif"
    shutil.copyfile(first, second)
    kwargs = dict(
        timestamps=["2024-01-01 01:00"],
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
    )

    first_cube = RasPrecipGrid.from_geotiff(first, **kwargs)
    second_cube = RasPrecipGrid.from_geotiff(second, **kwargs)

    assert first_cube.content_hash == second_cube.content_hash
    assert RasPrecipGrid.default_cache_path(
        first_cube, tmp_path
    ) == RasPrecipGrid.default_cache_path(second_cube, tmp_path)


@pytest.mark.parametrize("tamper", ["value", "x", "crs", "units"])
def test_tampered_cache_is_rebuilt_instead_of_reused(tmp_path, tamper):
    import xarray as xr

    source = _write_tiff(tmp_path / "rain.tif", np.ones((2, 2)))
    cube = RasPrecipGrid.from_geotiff(
        source,
        timestamps=["2024-01-01 01:00"],
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
    )
    destination = tmp_path / "cache.nc"
    RasPrecipGrid.to_ras_netcdf(cube, destination)

    dataset = None
    selected_engine = None
    for engine in ("h5netcdf", "scipy"):
        try:
            dataset = xr.load_dataset(destination, engine=engine)
            selected_engine = engine
            break
        except Exception:
            continue
    assert dataset is not None and selected_engine is not None
    if tamper == "value":
        dataset["precipitation"].values[-1, 0, 0] = 999.0
    elif tamper == "x":
        tampered_x = dataset["x"].values.copy()
        tampered_x[0] += 1.0
        dataset = dataset.assign_coords(x=tampered_x)
    elif tamper == "crs":
        dataset["spatial_ref"].attrs["crs_wkt"] = "tampered"
    else:
        dataset["precipitation"].attrs["units"] = "in"
    destination.unlink()
    dataset.to_netcdf(destination, engine=selected_engine)
    dataset.close()

    rebuilt = RasPrecipGrid.to_ras_netcdf(cube, destination)

    assert rebuilt.reused is False
    assert RasPrecipGrid._valid_cached_netcdf(destination, cube)


def test_cache_policy_refresh_error_and_extension_contract(tmp_path):
    source = _write_tiff(tmp_path / "rain.tif", np.ones((2, 2)))
    cube = RasPrecipGrid.from_geotiff(
        source,
        timestamps=["2024-01-01 01:00"],
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
    )
    destination = tmp_path / "cache.nc4"
    RasPrecipGrid.to_ras_netcdf(cube, destination)

    refreshed = RasPrecipGrid.to_ras_netcdf(
        cube, destination, cache_policy="refresh"
    )
    assert refreshed.reused is False
    with pytest.raises(FileExistsError):
        RasPrecipGrid.to_ras_netcdf(cube, destination, cache_policy="error")
    with pytest.raises(ValueError, match=".nc or .nc4"):
        RasPrecipGrid.to_ras_netcdf(cube, tmp_path / "cache.dat")


def test_direct_geotiff_api_writes_durable_netcdf_and_native_hdf(tmp_path):
    source = _write_tiff(
        tmp_path / "rain.tif",
        np.array([[[1, 2], [3, 4]], [[2, 2], [2, 2]]], dtype=np.float32),
        units="mm",
    )
    unsteady = tmp_path / "GeoTiffRain.u01"
    unsteady.write_text(
        "Flow Title=GeoTIFF rain\n"
        "Program Version=6.60\n"
        "Precipitation Mode=Disable\n",
        encoding="ascii",
    )

    result = RasUnsteady.set_gridded_precipitation_geotiff(
        unsteady,
        source,
        timestamps=["2024-01-01 01:00", "2024-01-01 02:00"],
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
        ras_object=_dummy_project(tmp_path),
    )

    assert result.cache_path.is_file()
    assert result.cache_path.suffix == ".nc"
    assert result.shape == (3, 2, 2)
    text = unsteady.read_text(encoding="utf-8")
    assert "Gridded Source=GDAL Raster File(s)" in text
    assert "Gridded GDAL Group=precipitation" in text
    assert ".nc" in text
    assert ".tif" not in text

    with h5py.File(Path(str(unsteady) + ".hdf"), "r") as hdf:
        values = hdf[
            "Event Conditions/Meteorology/Precipitation/Imported Raster Data/Values"
        ][...]
        np.testing.assert_array_equal(values[-1].reshape(2, 2), [[3, 4], [5, 6]])


@pytest.mark.parametrize(
    "version, ratio, message",
    [
        ("5.0.7", 1.0, "uniform-per-area"),
        ("6.1", 1.25, "does not apply the optional precipitation ratio"),
    ],
)
def test_direct_geotiff_api_rejects_version_limit_before_cache(
    tmp_path, version, ratio, message
):
    source = _write_tiff(tmp_path / "rain.tif", np.ones((2, 2)))
    unsteady = tmp_path / "GeoTiffRain.u01"
    unsteady.write_text(
        f"Flow Title=GeoTIFF rain\nProgram Version={version}\n",
        encoding="ascii",
    )

    with pytest.raises(ValueError, match=message):
        RasUnsteady.set_gridded_precipitation_geotiff(
            unsteady,
            source,
            timestamps=["2024-01-01 01:00"],
            units="mm",
            value_type="amount",
            first_timestep_hours=1.0,
            ratio=ratio,
            ras_object=_dummy_project(tmp_path, version),
        )

    assert not (tmp_path / "Precipitation").exists()
    assert not Path(str(unsteady) + ".hdf").exists()


def test_hec_ras_61_rejects_retained_ineffective_ratio_before_cache(tmp_path):
    source = _write_tiff(tmp_path / "rain.tif", np.ones((2, 2)))
    unsteady = tmp_path / "GeoTiffRain.u01"
    unsteady.write_text(
        "Flow Title=GeoTIFF rain\n"
        "Program Version=6.10\n"
        "Met BC=Precipitation|Ratio=1.25\n",
        encoding="ascii",
    )

    with pytest.raises(ValueError, match="does not apply that ratio"):
        RasUnsteady.set_gridded_precipitation_geotiff(
            unsteady,
            source,
            timestamps=["2024-01-01 01:00"],
            units="mm",
            value_type="amount",
            first_timestep_hours=1.0,
            ratio=None,
            ras_object=_dummy_project(tmp_path, "6.1"),
        )

    assert not (tmp_path / "Precipitation").exists()


def test_geotiff_requires_first_interval_for_nonzero_first_frame(tmp_path):
    source = _write_tiff(tmp_path / "rain.tif", np.ones((2, 2)))

    with pytest.raises(ValueError, match="first_timestep_hours is required"):
        RasPrecipGrid.from_geotiff(
            source,
            timestamps=["2024-01-01 01:00"],
            units="mm",
            value_type="amount",
        )


def test_geotiff_rejects_decreasing_cumulative_values(tmp_path):
    source = _write_tiff(
        tmp_path / "rain.tif",
        np.array([np.full((2, 2), 2.0), np.full((2, 2), 1.0)]),
    )

    with pytest.raises(ValueError, match="must not decrease"):
        RasPrecipGrid.from_geotiff(
            source,
            timestamps=["2024-01-01 01:00", "2024-01-01 02:00"],
            units="mm",
            value_type="cumulative",
        )


def test_grib_facade_uses_same_explicit_semantic_normalization(tmp_path):
    # This deterministic GDAL-raster test covers adapter semantics only. The
    # opt-in qualification test downloads and reads a real NOAA HRRR GRIB2.
    source = _write_tiff(
        tmp_path / "forecast.grib2",
        np.array([[[1, 0], [0, 2]], [[2, 1], [1, 0]]], dtype=np.float32),
        units="mm",
    )

    cube = RasPrecipGrid.from_grib(
        source,
        timestamps=["2024-01-01 01:00", "2024-01-01 02:00"],
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
    )

    assert cube.values.shape == (3, 2, 2)
    np.testing.assert_array_equal(cube.values[-1], [[3, 1], [1, 2]])


def test_multiband_raster_sequence_accepts_explicit_per_file_band_selection(tmp_path):
    first = _write_tiff(
        tmp_path / "first.grib2",
        np.array([np.ones((2, 2)), np.full((2, 2), 2.0)]),
    )
    second = _write_tiff(
        tmp_path / "second.grib2",
        np.array([np.full((2, 2), 3.0), np.full((2, 2), 4.0)]),
    )

    cube = RasPrecipGrid.from_grib(
        [first, second],
        timestamps=["2024-01-01 01:00", "2024-01-01 02:00"],
        units="mm",
        value_type="amount",
        first_timestep_hours=1.0,
        bands=[[2], [1]],
    )

    assert cube.selected_bands == ((2,), (1,))
    np.testing.assert_array_equal(cube.values[-1], np.full((2, 2), 5.0))


@pytest.mark.parametrize(
    "rate_units",
    [
        "in/hr",
        "inchesperhour",
        "iph",
        "inches/hour",
        "mm/hr",
        "millimeterperhour",
        "mmph",
        "mm h^-1",
    ],
)
def test_declared_rate_units_cannot_be_labeled_as_interval_amount(
    tmp_path, rate_units
):
    source = _write_tiff(
        tmp_path / "rate.tif",
        np.ones((2, 2)),
        units=rate_units,
    )

    with pytest.raises(ValueError, match="declares rate units"):
        RasPrecipGrid.from_geotiff(
            source,
            timestamps=["2024-01-01 01:00"],
            units="mm",
            value_type="amount",
            first_timestep_hours=1.0,
        )


def test_grib_unit_metadata_is_used_for_temporal_validation(tmp_path):
    source = _write_tiff(tmp_path / "forecast.grib2", np.ones((2, 2)))
    with rasterio.open(source, "r+") as dataset:
        dataset.update_tags(1, GRIB_UNIT="mmph")

    with pytest.raises(ValueError, match="declares rate units"):
        RasPrecipGrid.from_grib(
            source,
            timestamps=["2024-01-01 01:00"],
            units="mm",
            value_type="amount",
            first_timestep_hours=1.0,
        )


def test_hourly_rate_metadata_accepts_rate_semantics(tmp_path):
    source = _write_tiff(
        tmp_path / "rate.tif", np.ones((2, 2)), units="mmph"
    )

    cube = RasPrecipGrid.from_geotiff(
        source,
        timestamps=["2024-01-01 01:00"],
        units="mm",
        value_type="rate",
        first_timestep_hours=1.0,
    )

    np.testing.assert_array_equal(cube.values[-1], np.ones((2, 2)))


def test_non_hourly_rate_metadata_requires_explicit_conversion(tmp_path):
    source = _write_tiff(
        tmp_path / "rate.tif", np.ones((2, 2)), units="mm/s"
    )

    with pytest.raises(ValueError, match="non-hourly rate units"):
        RasPrecipGrid.from_geotiff(
            source,
            timestamps=["2024-01-01 01:00"],
            units="mm",
            value_type="rate",
            first_timestep_hours=1.0,
        )
