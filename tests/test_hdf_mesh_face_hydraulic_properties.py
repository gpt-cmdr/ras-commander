from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.hdf import HdfMesh


def _write_face_property_hdf(path: Path) -> Path:
    mesh_name = "MainArea"
    attrs_dtype = np.dtype([("Name", "S32")])
    attrs = np.array([(mesh_name.encode("utf-8"),)], dtype=attrs_dtype)

    face_values = np.array(
        [
            [100.0, 0.0, 0.0, 0.04],
            [102.0, 20.0, 10.0, 0.04],
            [100.0, 0.0, 0.0, 0.05],
            [102.0, 8.0, 4.0, 0.05],
            [100.0, 0.0, 0.0, 0.0],
            [102.0, 10.0, 5.0, 0.0],
        ],
        dtype=np.float64,
    )
    face_info = np.array([[0, 2], [2, 2], [4, 2]], dtype=np.int32)

    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=attrs)
        mesh_group = hdf.create_group(f"Geometry/2D Flow Areas/{mesh_name}")
        mesh_group.create_dataset("Faces Area Elevation Info", data=face_info)
        mesh_group.create_dataset("Faces Area Elevation Values", data=face_values)

    return path


def _write_reference_line_hdf(path: Path) -> Path:
    with h5py.File(path, "w") as hdf:
        ref_group = hdf.create_group("Geometry/Reference Lines")

        attrs_dtype = np.dtype([
            ("Name", "S32"),
            ("SA-2D", "S32"),
            ("Type", "S16"),
        ])
        attrs = np.array(
            [
                (b"Profile A", b"MainArea", b"Reference"),
                (b"Profile B", b"OtherArea", b"Reference"),
            ],
            dtype=attrs_dtype,
        )
        ref_group.create_dataset("Attributes", data=attrs)

        internal_dtype = np.dtype([
            ("Reference Line ID", "<i4"),
            ("Face Index", "<i4"),
            ("FP Start Index", "<i4"),
            ("FP End Index", "<i4"),
            ("Station Start", "<f8"),
            ("Station End", "<f8"),
        ])
        internal_faces = np.array(
            [
                (0, 1, 10, 11, 0.0, 4.0),
                (0, 2, 11, 12, 4.0, 9.0),
                (1, 0, 20, 21, 0.0, 3.0),
            ],
            dtype=internal_dtype,
        )
        ref_group.create_dataset("Internal Faces", data=internal_faces)

        main_group = hdf.create_group("Geometry/2D Flow Areas/MainArea")
        main_group.create_dataset(
            "Faces NormalUnitVector and Length",
            data=np.array(
                [
                    [1.0, 0.0, 3.0],
                    [1.0, 0.0, 4.0],
                    [1.0, 0.0, 10.0],
                ],
                dtype=np.float64,
            ),
        )

    return path


def test_face_hydraulic_properties_scalar_stage(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    ds = HdfMesh.get_mesh_face_hydraulic_properties_at_stage(
        hdf_path, "MainArea", [0, 1], 101.0
    )

    assert ds.sizes == {"time": 1, "face_id": 2}
    assert ds.attrs["manning_conveyance_coefficient"] == pytest.approx(1.486)
    assert ds["area"].sel(face_id=0).item() == pytest.approx(10.0)
    assert ds["wetted_perimeter"].sel(face_id=0).item() == pytest.approx(5.0)
    assert ds["hydraulic_radius"].sel(face_id=0).item() == pytest.approx(2.0)

    expected_conveyance = 1.486 * 10.0 * (2.0 ** (2.0 / 3.0)) / 0.04
    assert ds["conveyance"].sel(face_id=0).item() == pytest.approx(expected_conveyance)


def test_face_hydraulic_properties_1d_per_face_and_metric(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    ds = HdfMesh.get_mesh_face_hydraulic_properties_at_stage(
        hdf_path, "MainArea", [0, 1], [101.0, 102.0], unit_system="metric"
    )

    assert ds.sizes == {"time": 1, "face_id": 2}
    assert ds.attrs["manning_conveyance_coefficient"] == pytest.approx(1.0)
    assert ds["area"].sel(face_id=0).item() == pytest.approx(10.0)
    assert ds["area"].sel(face_id=1).item() == pytest.approx(8.0)


def test_face_hydraulic_properties_2d_dry_and_invalid_n(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    ds = HdfMesh.get_mesh_face_hydraulic_properties_at_stage(
        hdf_path,
        "MainArea",
        [0, 1, 2],
        np.array([[101.0, 101.0, 101.0], [99.0, 102.0, 102.0]]),
    )

    assert ds.sizes == {"time": 2, "face_id": 3}
    assert ds["area"].sel(time=1, face_id=0).item() == pytest.approx(0.0)
    assert ds["hydraulic_radius"].sel(time=1, face_id=0).item() == pytest.approx(0.0)
    assert ds["conveyance"].sel(time=1, face_id=0).item() == pytest.approx(0.0)
    assert np.isnan(ds["conveyance"].sel(time=1, face_id=2).item())


def test_face_hydraulic_properties_rejects_wrong_1d_shape(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    with pytest.raises(ValueError, match="one value per face ID"):
        HdfMesh.get_mesh_face_hydraulic_properties_at_stage(
            hdf_path, "MainArea", [0, 1], [101.0, 102.0, 103.0]
        )


def test_reference_line_internal_faces_returns_face_chain(tmp_path):
    hdf_path = _write_reference_line_hdf(tmp_path / "ref.g01.hdf")

    df = HdfMesh.get_reference_line_internal_faces(hdf_path, mesh_name="MainArea")

    assert isinstance(df, pd.DataFrame)
    assert list(df["reference_line_id"]) == [0, 0]
    assert list(df["profile_name"]) == ["Profile A", "Profile A"]
    assert list(df["mesh_name"]) == ["MainArea", "MainArea"]
    assert list(df["face_id"]) == [1, 2]
    assert list(df["station_length"]) == pytest.approx([4.0, 5.0])
    assert list(df["face_length"]) == pytest.approx([4.0, 10.0])
    assert list(df["station_fraction"]) == pytest.approx([1.0, 0.5])


def test_reference_line_internal_faces_missing_group_is_empty(tmp_path):
    hdf_path = tmp_path / "empty.g01.hdf"
    with h5py.File(hdf_path, "w"):
        pass

    df = HdfMesh.get_reference_line_internal_faces(hdf_path)

    assert df.empty
    assert "reference_line_id" in df.columns
