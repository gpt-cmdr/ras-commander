from pathlib import Path
import logging

import h5py
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander.hdf import HdfLandCover, HdfMesh


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
        mesh_group.create_dataset(
            "Faces NormalUnitVector and Length",
            data=np.array(
                [
                    [1.0, 0.0, 12.0],
                    [1.0, 0.0, 6.0],
                    [1.0, 0.0, 5.0],
                ],
                dtype=np.float64,
            ),
        )
        mesh_group.create_dataset(
            "Faces FacePoint Indexes",
            data=np.array([[0, 1], [1, 2], [2, 3]], dtype=np.int32),
        )
        mesh_group.create_dataset(
            "FacePoints Coordinate",
            data=np.array(
                [
                    [0.25, 1.5],
                    [1.75, 1.5],
                    [2.75, 1.5],
                    [3.75, 1.5],
                ],
                dtype=np.float64,
            ),
        )
        mesh_group.create_dataset(
            "Faces Perimeter Info",
            data=np.array([[0, 0], [0, 0], [0, 0]], dtype=np.int32),
        )
        mesh_group.create_dataset(
            "Faces Perimeter Values",
            data=np.empty((0, 2), dtype=np.float64),
        )

    return path


def _write_chunked_face_property_hdf(path: Path) -> Path:
    mesh_name = "MainArea"
    attrs_dtype = np.dtype([("Name", "S32")])
    attrs = np.array([(mesh_name.encode("utf-8"),)], dtype=attrs_dtype)

    face_values = np.array(
        [
            [100.0, 0.0, 0.0, 0.04],
            [101.0, 5.0, 2.5, 0.04],
            [102.0, 10.0, 5.0, 0.04],
            [103.0, 15.0, 7.5, 0.04],
            [100.0, 0.0, 0.0, 0.05],
            [101.0, 4.0, 2.0, 0.05],
            [102.0, 8.0, 4.0, 0.05],
            [103.0, 12.0, 6.0, 0.05],
            [100.0, 0.0, 0.0, 0.06],
            [101.0, 6.0, 3.0, 0.06],
            [102.0, 12.0, 6.0, 0.06],
            [103.0, 18.0, 9.0, 0.06],
        ],
        dtype=np.float64,
    )
    face_info = np.array([[0, 4], [4, 4], [8, 4]], dtype=np.int32)

    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=attrs)
        mesh_group = hdf.create_group(f"Geometry/2D Flow Areas/{mesh_name}")
        mesh_group.create_dataset(
            "Faces Area Elevation Info",
            data=face_info,
            chunks=(1024, 2),
            maxshape=(None, 2),
        )
        mesh_group.create_dataset(
            "Faces Area Elevation Values",
            data=face_values,
            chunks=(12, 4),
        )

    return path


def _write_landcover_sidecar(path: Path) -> Path:
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("IDs", data=np.array([0, 1, 2], dtype=np.int32))
        hdf.create_dataset(
            "Names",
            data=np.array([b"NoData", b"Grass", b"Forest"], dtype="S32"),
        )
        hdf.create_dataset(
            "ManningsN",
            data=np.array([np.finfo(np.float32).max, 0.10, 0.20], dtype=np.float64),
        )
    return path


def _write_landcover_tif(path: Path) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="int16",
        transform=from_origin(0.0, 2.0, 1.0, 1.0),
        nodata=0,
    ) as dst:
        dst.write(np.array([[1, 2], [1, 2]], dtype=np.int16), 1)
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


def test_face_hydraulic_properties_warns_for_above_table_stage(tmp_path, caplog):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    with caplog.at_level(logging.WARNING, logger="ras_commander.hdf.HdfMesh"):
        ds = HdfMesh.get_mesh_face_hydraulic_properties_at_stage(
            hdf_path,
            "MainArea",
            [0, 1],
            np.array([[101.0, 103.0], [103.5, 102.0]]),
        )

    assert ds.attrs["above_table_stage_count"] == 2
    assert ds.attrs["above_table_face_count"] == 2
    assert ds.attrs["above_table_max_excess"] == pytest.approx(1.5)
    assert ds["area"].sel(time=1, face_id=0).item() == pytest.approx(20.0)
    assert ds["area"].sel(time=0, face_id=1).item() == pytest.approx(8.0)
    assert "Water-surface stages exceed the highest face property table elevation" in caplog.text
    assert "Values above the table are clipped" in caplog.text


def test_face_hydraulic_properties_above_table_face_count_is_unique(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    ds = HdfMesh.get_mesh_face_hydraulic_properties_at_stage(
        hdf_path,
        "MainArea",
        [0, 0],
        np.array([[103.0, 103.5]]),
    )

    assert ds.attrs["above_table_stage_count"] == 2
    assert ds.attrs["above_table_face_count"] == 1


def test_face_hydraulic_properties_rejects_wrong_1d_shape(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    with pytest.raises(ValueError, match="one value per face ID"):
        HdfMesh.get_mesh_face_hydraulic_properties_at_stage(
            hdf_path, "MainArea", [0, 1], [101.0, 102.0, 103.0]
        )


def test_extend_face_property_tables_uses_face_length_above_terrain(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    rows_added = HdfMesh.extend_face_property_tables(
        hdf_path,
        "MainArea",
        extension_elevation=103.0,
        elevation_step=0.5,
        face_ids=[0],
        mannings_n_func=lambda depth, base_n: base_n + 0.001 * depth,
        pin_tables=False,
    )

    assert rows_added == {0: 2}
    tables = HdfMesh.get_mesh_face_property_tables(hdf_path)["MainArea"]
    face0 = tables[tables["Face ID"] == 0].tail(2)
    assert list(face0["Area"]) == pytest.approx([26.0, 32.0])
    assert list(face0["Wetted Perimeter"]) == pytest.approx([10.0, 10.0])
    assert list(face0["Manning's n"]) == pytest.approx([0.0425, 0.043])


def test_extend_face_property_tables_reaches_partial_final_step(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    rows_added = HdfMesh.extend_face_property_tables(
        hdf_path,
        "MainArea",
        extension_elevation=102.3,
        elevation_step=0.5,
        face_ids=[0],
        mannings_n_func=lambda depth, base_n: base_n,
        pin_tables=False,
    )

    assert rows_added == {0: 1}
    tables = HdfMesh.get_mesh_face_property_tables(hdf_path)["MainArea"]
    face0_last = tables[tables["Face ID"] == 0].iloc[-1]
    assert face0_last["Elevation"] == pytest.approx(102.3)
    assert face0_last["Area"] == pytest.approx(23.6)
    assert face0_last["Wetted Perimeter"] == pytest.approx(10.0)


def test_extend_face_property_tables_rejects_nonpositive_step(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")

    with pytest.raises(ValueError, match="elevation_step"):
        HdfMesh.extend_face_property_tables(
            hdf_path,
            "MainArea",
            extension_elevation=103.0,
            elevation_step=0.0,
            face_ids=[0],
            mannings_n_func=lambda depth, base_n: base_n,
            pin_tables=False,
        )


def test_set_mesh_face_property_tables_clamps_chunks_for_smaller_tables(tmp_path):
    hdf_path = _write_chunked_face_property_hdf(tmp_path / "chunked.g01.hdf")
    replacement = pd.DataFrame(
        {
            "Elevation": [100.0],
            "Area": [0.0],
            "Wetted Perimeter": [0.0],
            "Manning's n": [0.035],
        }
    )

    HdfMesh.set_mesh_face_property_tables(
        hdf_path,
        "MainArea",
        {0: replacement},
        pin_tables=False,
    )

    with h5py.File(hdf_path, "r") as hdf:
        info = hdf["Geometry/2D Flow Areas/MainArea/Faces Area Elevation Info"]
        values = hdf["Geometry/2D Flow Areas/MainArea/Faces Area Elevation Values"]

        assert info.shape == (3, 2)
        assert info.chunks == (3, 2)
        assert values.shape == (9, 4)
        assert values.chunks == (9, 4)
        assert np.all(np.asarray(info.chunks) <= np.asarray(info.shape))
        assert np.all(np.asarray(values.chunks) <= np.asarray(values.shape))


def test_build_landcover_depth_roughness_curves_reads_v5_sidecar(tmp_path):
    landcover_hdf = _write_landcover_sidecar(tmp_path / "landcover.hdf")

    curves = HdfLandCover.build_landcover_depth_roughness_curves(
        landcover_hdf,
        depths=[0.0, 2.0],
        mannings_n_func=lambda depth, base_n, class_name: base_n + 0.01 * depth,
    )

    assert set(curves["class_name"]) == {"Grass", "Forest"}
    assert set(curves["pixel_value"]) == {1, 2}
    assert len(curves) == 4
    grass = curves[curves["class_name"] == "Grass"].sort_values("depth")
    assert list(grass["mannings_n"]) == pytest.approx([0.10, 0.12])


def test_recompute_face_mannings_n_from_landcover_curves(tmp_path):
    hdf_path = _write_face_property_hdf(tmp_path / "mesh.g01.hdf")
    landcover_hdf = _write_landcover_sidecar(tmp_path / "landcover.hdf")
    _write_landcover_tif(landcover_hdf.with_suffix(".tif"))
    curves = HdfLandCover.build_landcover_depth_roughness_curves(
        landcover_hdf,
        depths=[0.0, 2.0],
        mannings_n_func=lambda depth, base_n, class_name: base_n + 0.01 * depth,
    )

    modified_count = HdfMesh.recompute_face_mannings_n_from_landcover_curves(
        hdf_path,
        "MainArea",
        curves,
        landcover_hdf_path=landcover_hdf,
        face_ids=[0],
        sample_spacing=10.0,
        pin_tables=False,
    )

    assert modified_count == 1
    tables = HdfMesh.get_mesh_face_property_tables(hdf_path)["MainArea"]
    face0 = tables[tables["Face ID"] == 0].sort_values("Elevation")
    expected_depth0 = ((0.10 ** 1.5 + 0.20 ** 1.5) / 2.0) ** (2.0 / 3.0)
    expected_depth2 = ((0.12 ** 1.5 + 0.22 ** 1.5) / 2.0) ** (2.0 / 3.0)
    assert list(face0["Manning's n"]) == pytest.approx([expected_depth0, expected_depth2])
    assert list(face0["Area"]) == pytest.approx([0.0, 20.0])
    assert list(face0["Wetted Perimeter"]) == pytest.approx([0.0, 10.0])


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
