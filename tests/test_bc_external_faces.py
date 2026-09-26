"""Native HEC-RAS boundary-condition external-face association tests."""

from pathlib import Path

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.hdf import HdfBndry

PARENT_GEOMETRY_HDF = Path(
    r"T:\FEMA eBFE\26-014 CWE\data_staging\austin_oyster_ebfe\organized"
    r"\AustinOyster_12040205\RAS Model\AustinOyster\Input\AustinOyster.g02.hdf"
)
CHILD_GEOMETRY_HDF = Path(
    r"C:\Users\billk_clb\Documents\Codex\models\austin-buffer-01"
    r"\Input\AustinOyster.g01.hdf"
)

EXPECTED_COLUMNS = [
    "bc_line_id",
    "bc_line_name",
    "mesh_name",
    "bc_line_type",
    "face_id",
    "fp_start_index",
    "fp_end_index",
    "station_start",
    "station_end",
]

ATTR_DTYPE = np.dtype(
    [("Name", "S32"), ("SA-2D", "S16"), ("Type", "S8"), ("Length", "<f4")]
)
EXTERNAL_FACE_DTYPE = np.dtype(
    [
        ("BC Line ID", "<i4"),
        ("Face Index", "<i4"),
        ("FP Start Index", "<i4"),
        ("FP End Index", "<i4"),
        ("Station Start", "<f4"),
        ("Station End", "<f4"),
    ]
)


def _write_geometry_hdf(
    path: Path,
    *,
    external_faces: np.ndarray | None = None,
    include_external_faces: bool = True,
) -> None:
    with h5py.File(path, "w") as hdf:
        group = hdf.require_group("Geometry/Boundary Condition Lines")
        group.create_dataset(
            "Attributes",
            data=np.array(
                [
                    (b"Upstream", b"Perimeter 1", b"External", 100.0),
                    (b"Downstream", b"Perimeter 1", b"External", 200.0),
                ],
                dtype=ATTR_DTYPE,
            ),
        )
        if include_external_faces:
            if external_faces is None:
                external_faces = np.array([], dtype=EXTERNAL_FACE_DTYPE)
            group.create_dataset("External Faces", data=external_faces)


def _write_selected_face_geometry(path: Path, *, include_perimeter: bool = True) -> None:
    """Add a small real-schema face/face-point lookup for face IDs 11 and 27."""
    with h5py.File(path, "a") as hdf:
        mesh = hdf.require_group("Geometry/2D Flow Areas/Perimeter 1")
        face_points = np.zeros((28, 2), dtype=np.int32)
        face_points[11] = [0, 1]
        face_points[27] = [1, 2]
        mesh.create_dataset("Faces FacePoint Indexes", data=face_points)
        if include_perimeter:
            perimeter_info = np.zeros((28, 2), dtype=np.int32)
            perimeter_info[11] = [0, 2]
            perimeter_info[27] = [2, 1]
            mesh.create_dataset("Faces Perimeter Info", data=perimeter_info)
            mesh.create_dataset(
                "Faces Perimeter Values",
                data=np.array(
                    [[0.5, 0.5], [1.5, 0.5], [2.5, 1.5]],
                    dtype=np.float64,
                ),
            )
        mesh.create_dataset(
            "FacePoints Coordinate",
            data=np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 3.0]], dtype=np.float64),
        )


def test_get_bc_external_faces_reads_native_association(tmp_path):
    geometry_hdf = tmp_path / "project.g01.hdf"
    rows = np.array(
        [
            (0, 11, 100, 101, -5.0, 10.0),
            (1, 27, 200, 201, 0.0, 25.5),
        ],
        dtype=EXTERNAL_FACE_DTYPE,
    )
    _write_geometry_hdf(geometry_hdf, external_faces=rows)

    result = HdfBndry.get_bc_external_faces(geometry_hdf)

    assert list(result.columns) == EXPECTED_COLUMNS
    assert result.attrs["association_status"] == "present"
    assert result.attrs["authoritative"] is True
    assert result.attrs["face_count"] == 2
    assert result.attrs["unique_face_count"] == 2
    assert result["bc_line_id"].tolist() == [0, 1]
    assert result["bc_line_name"].tolist() == ["Upstream", "Downstream"]
    assert result["mesh_name"].tolist() == ["Perimeter 1", "Perimeter 1"]
    assert result["bc_line_type"].tolist() == ["External", "External"]
    assert result["face_id"].tolist() == [11, 27]
    assert result["fp_start_index"].tolist() == [100, 200]
    assert result["fp_end_index"].tolist() == [101, 201]
    np.testing.assert_allclose(result["station_start"], [-5.0, 0.0])
    np.testing.assert_allclose(result["station_end"], [10.0, 25.5])


def test_get_bc_external_faces_builds_only_selected_native_segments(tmp_path):
    geometry_hdf = tmp_path / "project_with_geometry.g01.hdf"
    rows = np.array(
        [
            (0, 11, 0, 1, -5.0, 10.0),
            (1, 27, 1, 2, 0.0, 25.5),
        ],
        dtype=EXTERNAL_FACE_DTYPE,
    )
    _write_geometry_hdf(geometry_hdf, external_faces=rows)
    _write_selected_face_geometry(geometry_hdf)

    result = HdfBndry.get_bc_external_faces(
        geometry_hdf,
        include_geometry=True,
    )

    assert isinstance(result, gpd.GeoDataFrame)
    assert result.attrs["association_status"] == "present"
    assert result.attrs["geometry_source"] == "face_endpoints_and_perimeter_values"
    assert result.attrs["curved_face_count"] == 2
    assert result.attrs["perimeter_value_count"] == 3
    assert result.geometry.iloc[0].wkt == "LINESTRING (0 0, 0.5 0.5, 1.5 0.5, 2 0)"
    assert result.geometry.iloc[1].wkt == "LINESTRING (2 0, 2.5 1.5, 2 3)"
    np.testing.assert_allclose(
        result.geometry.length,
        [np.sqrt(0.5) * 2 + 1.0, np.sqrt(2.5) * 2],
    )


def test_get_bc_external_faces_reverses_full_native_face_geometry(tmp_path):
    geometry_hdf = tmp_path / "reversed_geometry.g01.hdf"
    rows = np.array(
        [(0, 11, 1, 0, -5.0, 10.0)],
        dtype=EXTERNAL_FACE_DTYPE,
    )
    _write_geometry_hdf(geometry_hdf, external_faces=rows)
    _write_selected_face_geometry(geometry_hdf)

    result = HdfBndry.get_bc_external_faces(geometry_hdf, include_geometry=True)

    assert result.geometry.iloc[0].wkt == "LINESTRING (2 0, 1.5 0.5, 0.5 0.5, 0 0)"


def test_get_bc_external_faces_reports_endpoint_only_fallback(tmp_path):
    geometry_hdf = tmp_path / "endpoint_only_geometry.g01.hdf"
    rows = np.array(
        [(0, 11, 0, 1, -5.0, 10.0)],
        dtype=EXTERNAL_FACE_DTYPE,
    )
    _write_geometry_hdf(geometry_hdf, external_faces=rows)
    _write_selected_face_geometry(geometry_hdf, include_perimeter=False)

    result = HdfBndry.get_bc_external_faces(geometry_hdf, include_geometry=True)

    assert result.attrs["geometry_source"] == "face_endpoints_only"
    assert result.attrs["curved_face_count"] == 0
    assert result.attrs["perimeter_value_count"] == 0
    assert result.geometry.iloc[0].wkt == "LINESTRING (0 0, 2 0)"


def test_get_bc_external_faces_uses_native_endpoints_for_stale_face_id(
    tmp_path,
    caplog,
):
    """HEC-RAS may retain a stale face ID but write valid external endpoints."""
    geometry_hdf = tmp_path / "stale_face_id.g01.hdf"
    rows = np.array(
        [(0, 11, 1, 2, 0.0, 3.0)],
        dtype=EXTERNAL_FACE_DTYPE,
    )
    _write_geometry_hdf(geometry_hdf, external_faces=rows)
    _write_selected_face_geometry(geometry_hdf)

    result = HdfBndry.get_bc_external_faces(geometry_hdf, include_geometry=True)

    assert result.attrs["geometry_source"] == (
        "external_face_endpoints+face_endpoints_and_perimeter_values"
    )
    assert result.attrs["topology_match_count"] == 0
    assert result.attrs["topology_mismatch_count"] == 1
    assert result.attrs["curved_face_count"] == 1
    assert result.geometry.iloc[0].wkt == "LINESTRING (2 0, 2 3)"
    assert "Using native External Faces endpoints for 1 of 1 BC faces" in caplog.text


def test_get_bc_external_faces_distinguishes_absent_from_empty(tmp_path):
    absent_hdf = tmp_path / "absent.g01.hdf"
    empty_hdf = tmp_path / "empty.g01.hdf"
    _write_geometry_hdf(absent_hdf, include_external_faces=False)
    _write_geometry_hdf(empty_hdf)

    absent = HdfBndry.get_bc_external_faces(absent_hdf)
    empty = HdfBndry.get_bc_external_faces(empty_hdf)

    assert list(absent.columns) == EXPECTED_COLUMNS
    assert list(empty.columns) == EXPECTED_COLUMNS
    assert absent.empty and empty.empty
    assert absent.attrs["association_status"] == "absent"
    assert absent.attrs["dataset_present"] is False
    assert absent.attrs["authoritative"] is False
    assert empty.attrs["association_status"] == "empty"
    assert empty.attrs["dataset_present"] is True
    assert empty.attrs["authoritative"] is True

    absent_geometry = HdfBndry.get_bc_external_faces(
        absent_hdf,
        include_geometry=True,
    )
    empty_geometry = HdfBndry.get_bc_external_faces(
        empty_hdf,
        include_geometry=True,
    )
    assert isinstance(absent_geometry, gpd.GeoDataFrame)
    assert isinstance(empty_geometry, gpd.GeoDataFrame)
    assert absent_geometry.attrs["association_status"] == "absent"
    assert empty_geometry.attrs["association_status"] == "empty"


def test_get_bc_external_faces_rejects_duplicate_face_ownership(tmp_path):
    geometry_hdf = tmp_path / "duplicates.g01.hdf"
    rows = np.array(
        [
            (0, 11, 100, 101, 0.0, 10.0),
            (1, 11, 200, 201, 0.0, 10.0),
        ],
        dtype=EXTERNAL_FACE_DTYPE,
    )
    _write_geometry_hdf(geometry_hdf, external_faces=rows)

    with pytest.raises(ValueError, match="unique face ownership"):
        HdfBndry.get_bc_external_faces(geometry_hdf)


def test_get_bc_external_faces_can_report_duplicate_face_ownership(tmp_path):
    geometry_hdf = tmp_path / "duplicate_diagnostics.g01.hdf"
    rows = np.array(
        [
            (0, 11, 0, 1, 0.0, 10.0),
            (1, 11, 1, 0, 3.0, 13.0),
        ],
        dtype=EXTERNAL_FACE_DTYPE,
    )
    _write_geometry_hdf(geometry_hdf, external_faces=rows)
    _write_selected_face_geometry(geometry_hdf)

    result = HdfBndry.get_bc_external_faces(
        geometry_hdf,
        include_geometry=True,
        validate_unique_faces=False,
    )

    assert len(result) == 2
    assert result.attrs["face_ownership_unique"] is False
    assert result.attrs["duplicate_face_count"] == 1
    assert result.attrs["duplicate_face_row_count"] == 2
    assert result.attrs["unique_face_count"] == 1
    assert result["bc_line_name"].tolist() == ["Upstream", "Downstream"]
    assert result["face_id"].tolist() == [11, 11]
    assert result["station_start"].tolist() == [0.0, 3.0]
    assert list(result.geometry.iloc[0].coords) == list(
        reversed(result.geometry.iloc[1].coords)
    )


def test_get_bc_external_faces_rejects_unknown_bc_id(tmp_path):
    geometry_hdf = tmp_path / "invalid_bc.g01.hdf"
    rows = np.array(
        [(2, 11, 100, 101, 0.0, 10.0)],
        dtype=EXTERNAL_FACE_DTYPE,
    )
    _write_geometry_hdf(geometry_hdf, external_faces=rows)

    with pytest.raises(ValueError, match="outside Attributes"):
        HdfBndry.get_bc_external_faces(geometry_hdf)


@pytest.mark.skipif(
    not PARENT_GEOMETRY_HDF.is_file(),
    reason="Austin Oyster parent geometry HDF is not mounted",
)
def test_real_austin_parent_external_faces_are_authoritative_and_unique():
    result = HdfBndry.get_bc_external_faces(PARENT_GEOMETRY_HDF)

    assert result.attrs["association_status"] == "present"
    assert len(result) == 9957
    assert result["face_id"].nunique() == 9957
    assert result["bc_line_id"].min() == 0
    assert result["bc_line_id"].max() == 59
    assert result["bc_line_name"].nunique() == 60
    assert result["mesh_name"].unique().tolist() == ["Perimeter 1"]
    assert result["bc_line_type"].unique().tolist() == ["External"]
    first = result.iloc[0]
    assert first["bc_line_id"] == 0
    assert first["bc_line_name"] == "Freeport Harbor"
    assert first["face_id"] == 1251365
    assert first["fp_start_index"] == 592283
    assert first["fp_end_index"] == 2060612
    assert first["station_start"] == pytest.approx(-23.54696846)
    assert first["station_end"] == pytest.approx(0.0)


@pytest.mark.skipif(
    not PARENT_GEOMETRY_HDF.is_file(),
    reason="Austin Oyster parent geometry HDF is not mounted",
)
def test_real_austin_parent_external_face_geometry_is_native():
    result = HdfBndry.get_bc_external_faces(
        PARENT_GEOMETRY_HDF,
        include_geometry=True,
    )

    assert isinstance(result, gpd.GeoDataFrame)
    assert result.crs is not None
    assert len(result) == 9957
    assert result.attrs["geometry_source"] == "face_endpoints_and_perimeter_values"
    assert result.attrs["curved_face_count"] == 2342
    assert result.attrs["perimeter_value_count"] == 3761
    assert result.geometry.notna().all()
    assert (~result.geometry.is_empty).all()
    assert (result.geometry.length > 0).all()
    station_spans = result["station_end"] - result["station_start"]
    assert np.max(np.abs(result.geometry.length - station_spans)) < 0.01
    first_coordinates = list(result.geometry.iloc[0].coords)
    np.testing.assert_allclose(
        first_coordinates,
        [
            [3127696.408696536, 13521683.3100226],
            [3127703.6214652, 13521660.8949462],
        ],
    )
    curved_bc_40 = result.loc[result["face_id"] == 3821327].iloc[0]
    np.testing.assert_allclose(
        list(curved_bc_40.geometry.coords),
        [
            [2956024.481520735, 13800134.5531734],
            [2956026.20023761, 13800132.8539874],
            [2956059.109459712, 13800070.499671834],
        ],
    )


@pytest.mark.skipif(
    not CHILD_GEOMETRY_HDF.is_file(),
    reason="Austin Oyster child geometry HDF is not available",
)
def test_real_austin_child_reports_native_dataset_state():
    try:
        result = HdfBndry.get_bc_external_faces(
            CHILD_GEOMETRY_HDF,
            validate_unique_faces=False,
        )
        with h5py.File(CHILD_GEOMETRY_HDF, "r") as hdf:
            dataset_path = "Geometry/Boundary Condition Lines/External Faces"
            if dataset_path in hdf:
                expected_count = len(hdf[dataset_path])
                expected_status = "present" if expected_count else "empty"
            else:
                expected_count = 0
                expected_status = "absent"
    except OSError as exc:
        pytest.skip(f"Austin Oyster child geometry HDF is actively locked: {exc}")

    assert result.attrs["association_status"] == expected_status
    assert len(result) == expected_count
    if expected_status == "present":
        assert result["bc_line_id"].between(0, 59).all()
        duplicate_rows = result.duplicated(["mesh_name", "face_id"], keep=False)
        duplicate_keys = result.loc[
            duplicate_rows,
            ["mesh_name", "face_id"],
        ].drop_duplicates()
        assert result.attrs["duplicate_face_count"] == len(duplicate_keys)
        assert result.attrs["duplicate_face_row_count"] == duplicate_rows.sum()
    else:
        assert result.empty


def test_get_bc_external_faces_returns_dataframe_not_geodataframe(tmp_path):
    geometry_hdf = tmp_path / "plain_dataframe.g01.hdf"
    _write_geometry_hdf(geometry_hdf)

    result = HdfBndry.get_bc_external_faces(geometry_hdf)

    assert type(result) is pd.DataFrame
