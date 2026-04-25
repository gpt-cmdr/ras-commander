import numpy as np
import h5py

from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh


MESH_NAME = "Test Mesh"
BASE_TS_PATH = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series"
)


def _write_face_variable(mesh_group, name, values, units):
    dataset = mesh_group.create_dataset(name, data=np.asarray(values, dtype=float))
    dataset.attrs["Units"] = np.bytes_(units)


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
