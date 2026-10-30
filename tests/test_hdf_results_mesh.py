import logging
import warnings

import numpy as np
import h5py
import pytest

from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh


MESH_NAME = "Test Mesh"
LOGGER_NAME = "ras_commander.hdf.HdfResultsMesh"
BASE_TS_PATH = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series"
)


def _create_year_3000_mesh_results_hdf(path):
    """Create a minimal future-dated plan HDF with mesh summary/results."""
    with h5py.File(path, "w") as hdf:
        plan_info = hdf.require_group("Plan Data/Plan Information")
        plan_info.attrs["Simulation Start Time"] = np.bytes_("02Jan3000 00:00:00")

        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time",
            data=np.array([0.0, 1.0, 2.0]),
        )
        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time Date Stamp (ms)",
            data=np.array([
                b"02Jan3000 00:00:00.000",
                b"03Jan3000 00:00:00.000",
                b"04Jan3000 00:00:00.000",
            ]),
        )

        attrs_dtype = np.dtype([("Name", "S64"), ("Cell Count", "i4")])
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(MESH_NAME.encode("utf-8"), 1)], dtype=attrs_dtype),
        )
        geom_group = hdf.require_group(f"Geometry/2D Flow Areas/{MESH_NAME}")
        geom_group.create_dataset("Cells Center Coordinate", data=np.array([[0.0, 0.0]]))

        mesh_group = hdf.require_group(f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}")
        _write_face_variable(mesh_group, "Water Surface", [[1.0], [2.0], [3.0]], "ft")
        _write_face_variable(mesh_group, "Face Velocity", [[0.1], [0.2], [0.3]], "ft/s")

        summary_group = hdf.require_group(
            f"Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/"
            f"2D Flow Areas/{MESH_NAME}"
        )
        summary_group.create_dataset(
            "Maximum Water Surface",
            data=np.array([[5.0], [1.0]]),
        )
        summary_group.create_dataset(
            "Maximum Face Velocity",
            data=np.array([[0.3], [2.0]]),
        )


def _write_face_variable(mesh_group, name, values, units):
    dataset = mesh_group.create_dataset(name, data=np.asarray(values, dtype=float))
    dataset.attrs["Units"] = np.bytes_(units)
    geometry = mesh_group.file.require_group(f"Geometry/2D Flow Areas/{MESH_NAME}")
    if "Faces FacePoint Indexes" not in geometry:
        geometry.create_dataset(
            "Faces FacePoint Indexes",
            data=np.zeros((dataset.shape[1], 2), dtype=int),
        )


def _create_synthetic_face_results_hdf(path):
    with h5py.File(path, "w") as hdf:
        plan_info = hdf.require_group("Plan Data/Plan Information")
        plan_info.attrs["Simulation Start Time"] = np.bytes_("01Jan2024 00:00:00")

        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time",
            data=np.array([0.0, 1.0 / 24.0, 2.0 / 24.0]),
        )
        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time Date Stamp (ms)",
            data=np.array(
                [
                    b"01Jan2024 00:00:00.000",
                    b"01Jan2024 01:00:00.000",
                    b"01Jan2024 02:00:00.000",
                ]
            ),
        )

        mesh_group = hdf.require_group(f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}")
        _write_face_variable(
            mesh_group,
            "Face Area",
            [[10.0, 20.0], [11.0, 21.0], [12.0, 22.0]],
            "ft2",
        )
        _write_face_variable(
            mesh_group,
            "Face Manning's n",
            [[0.030, 0.040], [0.031, 0.041], [0.032, 0.042]],
            "",
        )


def _create_synthetic_depth_results_hdf(path):
    with h5py.File(path, "w") as hdf:
        plan_info = hdf.require_group("Plan Data/Plan Information")
        plan_info.attrs["Simulation Start Time"] = np.bytes_("01Jan2024 00:00:00")

        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time",
            data=np.array([0.0, 1.0 / 24.0]),
        )
        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time Date Stamp (ms)",
            data=np.array(
                [
                    b"01Jan2024 00:00:00.000",
                    b"01Jan2024 01:00:00.000",
                ]
            ),
        )

        attrs_dtype = np.dtype([("Name", "S64")])
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(MESH_NAME.encode("utf-8"),)], dtype=attrs_dtype),
        )
        geom_group = hdf.require_group(f"Geometry/2D Flow Areas/{MESH_NAME}")
        geom_group.create_dataset(
            "Perimeter",
            data=np.array(
                [
                    [0.0, 0.0],
                    [2.0, 0.0],
                    [2.0, 2.0],
                    [0.0, 2.0],
                ],
                dtype=float,
            ),
        )
        geom_group.create_dataset(
            "Cells Center Coordinate",
            data=np.array(
                [
                    [0.5, 0.5],
                    [1.5, 0.5],
                    [0.5, 1.5],
                    [1.5, 1.5],
                ],
                dtype=float,
            ),
        )
        geom_group.create_dataset(
            "Cells Minimum Elevation",
            data=np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32),
        )

        mesh_group = hdf.require_group(f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}")
        _write_face_variable(
            mesh_group,
            "Water Surface",
            [
                [1.0, 1.0, 1.0, 1.0],
                [2.0, 2.0, 5.0, 7.0],
            ],
            "ft",
        )


@pytest.mark.synthetic_hdf_layout
def test_get_mesh_faces_timeseries_returns_optional_face_outputs(tmp_path):
    hdf_path = tmp_path / "synthetic.p01.hdf"
    _create_synthetic_face_results_hdf(hdf_path)

    result = HdfResultsMesh.get_mesh_faces_timeseries(hdf_path, MESH_NAME)

    assert "face_area" in result.data_vars
    assert "face_mannings_n" in result.data_vars
    assert "face_velocity" not in result.data_vars
    assert result["face_area"].dims == ("time", "face_id")
    np.testing.assert_allclose(
        result["face_area"].values,
        np.array([[10.0, 20.0], [11.0, 21.0], [12.0, 22.0]]),
    )
    np.testing.assert_allclose(
        result["face_mannings_n"].values,
        np.array([[0.030, 0.040], [0.031, 0.041], [0.032, 0.042]]),
    )


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("year", [2020, 1500, 3000])
def test_future_dated_mesh_summary_and_timeseries_are_supported(tmp_path, year):
    hdf_path = tmp_path / "year-3000.p01.hdf"
    _create_year_3000_mesh_results_hdf(hdf_path)
    with h5py.File(hdf_path, "a") as hdf:
        hdf["Plan Data/Plan Information"].attrs["Simulation Start Time"] = np.bytes_(f"02Jan{year} 00:00:00")
        hdf[f"{BASE_TS_PATH}/Time Date Stamp (ms)"][...] = np.array([
            f"{day:02d}Jan{year} 00:00:00.000".encode() for day in [2, 3, 4]
        ])

    ws = HdfResultsMesh.get_mesh_max_ws(hdf_path)
    face_v = HdfResultsMesh.get_mesh_max_face_v(hdf_path)
    timeseries = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        truncate=False,
        time_selection=slice(1, 2),
    )
    face_timeseries = HdfResultsMesh.get_mesh_faces_timeseries(
        hdf_path,
        MESH_NAME,
        truncate=False,
    )
    cell_timeseries = HdfResultsMesh.get_mesh_cells_timeseries(
        hdf_path,
        mesh_names=MESH_NAME,
        var="Water Surface",
        truncate=False,
    )

    lazy_timeseries = HdfResultsMesh.get_mesh_timeseries(
        hdf_path, MESH_NAME, "Water Surface", truncate=False,
        return_type="view", time_selection=slice(1, 2),
    ).to_xarray()

    expected_year = year
    assert ws["maximum_water_surface_time"].iloc[0].year == expected_year
    assert face_v["maximum_face_velocity_time"].iloc[0].year == expected_year
    assert timeseries.sizes["time"] == 1
    timestamp_year = lambda values: int(
        values[0].astype("datetime64[Y]").astype(int) + 1970
    )
    assert timestamp_year(timeseries.coords["time"].values) == expected_year
    np.testing.assert_allclose(timeseries.values, [[2.0]])
    np.testing.assert_array_equal(lazy_timeseries.coords["time"].values, timeseries.coords["time"].values)
    for result in [timeseries, lazy_timeseries, face_timeseries, cell_timeseries[MESH_NAME]]:
        assert result.coords["time"].dtype.kind == "M"
        if year != 2020:
            assert result.coords["time"].dtype == np.dtype("datetime64[us]")
    assert timestamp_year(face_timeseries.coords["time"].values) == expected_year
    assert timestamp_year(cell_timeseries[MESH_NAME].coords["time"].values) == expected_year


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("year", [2024, 3000])
@pytest.mark.parametrize("use_stamps", [True, False])
def test_export_depth_rasters_at_times_computes_depth_from_wse(tmp_path, year, use_stamps):
    import rasterio

    hdf_path = tmp_path / "synthetic.p01.hdf"
    _create_synthetic_depth_results_hdf(hdf_path)
    with h5py.File(hdf_path, "a") as hdf:
        hdf["Plan Data/Plan Information"].attrs["Simulation Start Time"] = np.bytes_(f"01Jan{year} 00:00:00")
        if use_stamps:
            hdf[f"{BASE_TS_PATH}/Time Date Stamp (ms)"][...] = np.array([
                f"01Jan{year} {hour:02d}:00:00.000".encode() for hour in [0, 1]
            ])
        else:
            del hdf[f"{BASE_TS_PATH}/Time Date Stamp (ms)"]

    result = HdfResultsMesh.export_depth_rasters_at_times(
        hdf_path,
        [f"01Jan{year} 01:00:00"],
        tmp_path / "rasters",
        mesh_name=MESH_NAME,
        resolution=1.0,
    )

    raster_path = result[f"01Jan{year} 01:00:00"]
    assert raster_path.exists()
    with rasterio.open(raster_path) as src:
        data = src.read(1)
        assert src.nodata == -9999.0
        assert src.tags()["mesh_name"] == MESH_NAME

    np.testing.assert_allclose(
        data,
        np.array(
            [
                [3.0, 4.0],
                [2.0, 1.0],
            ],
            dtype=np.float32,
        ),
    )


@pytest.mark.synthetic_hdf_layout
def test_get_mesh_faces_timeseries_can_preserve_full_time_axis(tmp_path):
    hdf_path = tmp_path / "synthetic.p01.hdf"
    _create_synthetic_face_results_hdf(hdf_path)

    with h5py.File(hdf_path, "a") as hdf:
        del hdf[f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}/Face Area"]
        dataset = hdf.create_dataset(
            f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}/Face Area",
            data=np.array([[0.0, 0.0], [10.0, 20.0], [0.0, 0.0]]),
        )
        dataset.attrs["Units"] = "ft2"

    result = HdfResultsMesh.get_mesh_faces_timeseries(
        hdf_path,
        MESH_NAME,
        truncate=False,
    )

    assert result.sizes["time"] == 3
    assert result["face_area"].attrs["units"] == "ft2"
    np.testing.assert_allclose(
        result["face_area"].values,
        np.array([[0.0, 0.0], [10.0, 20.0], [0.0, 0.0]]),
    )


@pytest.mark.synthetic_hdf_layout
def test_get_mesh_faces_timeseries_merges_mixed_time_axes_without_future_warning(
    tmp_path,
):
    hdf_path = tmp_path / "synthetic.p01.hdf"
    _create_synthetic_face_results_hdf(hdf_path)

    with h5py.File(hdf_path, "a") as hdf:
        del hdf[f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}/Face Area"]
        dataset = hdf.create_dataset(
            f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}/Face Area",
            data=np.array([[0.0, 0.0], [10.0, 20.0], [0.0, 0.0]]),
        )
        dataset.attrs["Units"] = np.bytes_("ft2")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = HdfResultsMesh.get_mesh_faces_timeseries(
            hdf_path,
            MESH_NAME,
            truncate=True,
        )

    assert not [
        warning
        for warning in caught
        if issubclass(warning.category, FutureWarning)
        and "default value for join" in str(warning.message)
    ]
    assert result.sizes["time"] == 3
    np.testing.assert_allclose(
        result["face_area"].values[:, 0],
        np.array([np.nan, 10.0, np.nan]),
    )


@pytest.mark.synthetic_hdf_layout
def test_get_mesh_cells_timeseries_treats_new_outputs_as_face_indexed(tmp_path):
    hdf_path = tmp_path / "synthetic.p01.hdf"
    _create_synthetic_face_results_hdf(hdf_path)

    result = HdfResultsMesh.get_mesh_cells_timeseries(
        hdf_path,
        mesh_names=MESH_NAME,
        var="Face Manning's n",
    )

    assert MESH_NAME in result
    assert result[MESH_NAME]["Face Manning's n"].dims == ("time", "face_id")


@pytest.mark.synthetic_hdf_layout
def test_get_mesh_cells_timeseries_aggregate_missing_outputs_are_debug_only(
    tmp_path,
    caplog,
):
    hdf_path = tmp_path / "synthetic.p01.hdf"
    _create_synthetic_face_results_hdf(hdf_path)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        result = HdfResultsMesh.get_mesh_cells_timeseries(
            hdf_path,
            mesh_names=MESH_NAME,
        )

    assert MESH_NAME in result
    assert "Face Area" in result[MESH_NAME].data_vars
    assert "Face Manning's n" in result[MESH_NAME].data_vars

    hdf_result_records = [
        record for record in caplog.records if record.name == LOGGER_NAME
    ]
    warning_messages = [
        record.getMessage()
        for record in hdf_result_records
        if record.levelno >= logging.WARNING
    ]
    assert not any("not found in the HDF file" in msg for msg in warning_messages)

    debug_messages = [
        record.getMessage()
        for record in hdf_result_records
        if record.levelno == logging.DEBUG
    ]
    summary_messages = [
        msg for msg in debug_messages
        if "time-series probe found" in msg
    ]
    assert len(summary_messages) == 1
    assert "skipped" in summary_messages[0]
    assert "Face Area" in summary_messages[0]


def test_get_mesh_cells_timeseries_explicit_missing_output_logs_error(
    tmp_path,
    caplog,
):
    hdf_path = tmp_path / "synthetic.p01.hdf"
    _create_synthetic_face_results_hdf(hdf_path)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        result = HdfResultsMesh.get_mesh_cells_timeseries(
            hdf_path,
            mesh_names=MESH_NAME,
            var="Depth",
        )

    assert result == {}
    error_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    ]
    assert any(
        "Requested mesh time-series variable 'Depth' was not found" in msg
        for msg in error_messages
    )
    assert any(
        "No valid data variables found" in msg
        for msg in error_messages
    )


@pytest.mark.synthetic_hdf_layout
def test_get_mesh_cells_timeseries_truncate_uses_time_axis(tmp_path):
    hdf_path = tmp_path / "synthetic.p01.hdf"
    _create_synthetic_face_results_hdf(hdf_path)

    with h5py.File(hdf_path, "a") as hdf:
        del hdf[f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}/Face Area"]
        dataset = hdf.create_dataset(
            f"{BASE_TS_PATH}/2D Flow Areas/{MESH_NAME}/Face Area",
            data=np.array([[0.0, 0.0], [10.0, 20.0], [0.0, 0.0]]),
        )
        dataset.attrs["Units"] = np.bytes_("ft2")

    result = HdfResultsMesh.get_mesh_cells_timeseries(
        hdf_path,
        mesh_names=MESH_NAME,
        var="Face Area",
        truncate=True,
    )

    face_area = result[MESH_NAME]["Face Area"]
    assert face_area.dims == ("time", "face_id")
    assert face_area.shape == (1, 2)
    np.testing.assert_allclose(face_area.values, np.array([[10.0, 20.0]]))
