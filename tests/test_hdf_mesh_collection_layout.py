"""Regression coverage for HEC-RAS 6.2/6.3 collection-level mesh layouts."""

from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf import HdfMesh, HdfProject


def _attributes(*names: str) -> np.ndarray:
    dtype = np.dtype([("Name", "S64")])
    return np.array([(name.encode("utf-8"),) for name in names], dtype=dtype)


def _write_collection_hdf(
    path: Path,
    *,
    names=("Legacy Mesh",),
    info=None,
    parts=None,
    points=None,
    include_collection_cells: bool = True,
) -> Path:
    if points is None:
        points = np.array(
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            dtype=float,
        )
    if info is None:
        info = np.array([[0, len(points), 0, 1]], dtype=np.int32)
    if parts is None:
        parts = np.array([[0, len(points)]], dtype=np.int32)

    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["File Version"] = "HEC-RAS 6.3 August 2022"
        hdf_file.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()
        geometry = hdf_file.create_group("Geometry")
        geometry.attrs["Geometry Version"] = "1.0.18"
        geometry.attrs["Complete Geometry"] = True
        group = geometry.create_group("2D Flow Areas")
        group.create_dataset("Attributes", data=_attributes(*names))
        group.create_dataset("Polygon Info", data=np.asarray(info))
        group.create_dataset("Polygon Parts", data=np.asarray(parts))
        group.create_dataset("Polygon Points", data=np.asarray(points))
        if include_collection_cells:
            group.create_dataset("Cell Info", data=np.array([[0, 1]], dtype=np.int32))
            group.create_dataset("Cell Points", data=np.array([[5.0, 5.0]]))
    return path


def test_collection_perimeter_recovers_extent_and_reports_missing_topology(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = _write_collection_hdf(tmp_path / "legacy.g01.hdf")

    areas = HdfMesh.get_mesh_areas(geom_hdf)
    diagnostic = HdfMesh.diagnose_mesh_layout(
        geom_hdf, program_version="6.20"
    )
    extent, bounds = HdfProject.get_project_extent(
        geom_hdf,
        include_1d=False,
        include_storage=False,
        buffer_percent=0,
        fallback_to_plaintext=False,
    )

    assert areas["mesh_name"].tolist() == ["Legacy Mesh"]
    assert areas.geometry.iloc[0].area == pytest.approx(100.0)
    assert not extent.empty
    assert bounds == pytest.approx((0.0, 0.0, 10.0, 10.0))
    row = diagnostic.iloc[0]
    assert row["hdf_file_version"] == "HEC-RAS 6.3 August 2022"
    assert row["geometry_version"] == "1.0.18"
    assert bool(row["complete_geometry"]) is True
    assert row["program_version"] == "6.20"
    assert row["layout"] == "collection_fallback"
    assert row["perimeter_status"] == "collection_fallback"
    assert row["face_topology_status"] == "not_present"
    assert row["cell_polygons_status"] == "not_present"
    assert "Cell Info" in row["cell_centers_paths"]
    assert row["compatibility_warning"]
    assert "omits named-area face topology" in caplog.text


def test_collection_multipart_perimeter_preserves_disconnected_parts(tmp_path: Path):
    first = np.array([[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], dtype=float)
    second = np.array([[10, 0], [12, 0], [12, 2], [10, 2], [10, 0]], dtype=float)
    points = np.vstack([first, second])
    geom_hdf = _write_collection_hdf(
        tmp_path / "multipart.g01.hdf",
        info=np.array([[0, 10, 0, 2]], dtype=np.int32),
        parts=np.array([[0, 5], [5, 5]], dtype=np.int32),
        points=points,
    )

    areas = HdfMesh.get_mesh_areas(geom_hdf)

    geometry = areas.geometry.iloc[0]
    assert geometry.geom_type == "MultiPolygon"
    assert len(geometry.geoms) == 2
    assert geometry.area == pytest.approx(20.0)


@pytest.mark.parametrize(
    "case",
    [
        "out_of_range",
        "overlapping_area_slices",
        "bad_part_count",
        "non_finite",
        "unclosed_ring",
    ],
)
def test_malformed_collection_layout_fails_safely(tmp_path: Path, case: str):
    names = ("Legacy Mesh",)
    points = np.array(
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], dtype=float
    )
    info = np.array([[0, 5, 0, 1]], dtype=np.int32)
    parts = np.array([[0, 5]], dtype=np.int32)
    if case == "out_of_range":
        info[0, 1] = 50
    elif case == "overlapping_area_slices":
        names = ("One", "Two")
        points = np.vstack([points, points + 20])
        info = np.array([[0, 5, 0, 1], [4, 5, 1, 1]], dtype=np.int32)
        parts = np.array([[0, 5], [4, 5]], dtype=np.int32)
    elif case == "bad_part_count":
        info[0, 3] = 2
    elif case == "non_finite":
        points[2, 0] = np.nan
    elif case == "unclosed_ring":
        points[-1] = [1, 1]

    geom_hdf = _write_collection_hdf(
        tmp_path / f"{case}.g01.hdf",
        names=names,
        info=info,
        parts=parts,
        points=points,
    )

    areas = HdfMesh.get_mesh_areas(geom_hdf)
    diagnostic = HdfMesh.diagnose_mesh_layout(geom_hdf)

    assert areas.empty
    assert set(diagnostic["layout"]) == {"malformed"}
    assert set(diagnostic["perimeter_status"]) == {"malformed"}
    assert diagnostic["reason_codes"].str.contains("collection_perimeter").all()


def test_collection_cell_points_are_not_promoted_to_faces_or_polygons(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = _write_collection_hdf(tmp_path / "no_topology.g01.hdf")

    faces = HdfMesh.get_mesh_cell_faces(geom_hdf)
    cells = HdfMesh.get_mesh_cell_polygons(geom_hdf)

    assert faces.empty
    assert cells.empty
    assert "will not be promoted to faces" in caplog.text
    assert "will not be promoted to polygon topology" in caplog.text


def test_standard_named_perimeter_schema_is_preserved(tmp_path: Path):
    geom_hdf = tmp_path / "modern.g01.hdf"
    perimeter = np.array(
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], dtype=float
    )
    with h5py.File(geom_hdf, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Attributes", data=_attributes("Modern Mesh")
        )
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Modern Mesh/Perimeter", data=perimeter
        )

    areas = HdfMesh.get_mesh_areas(geom_hdf)
    diagnostic = HdfMesh.diagnose_mesh_layout(geom_hdf)

    assert list(areas.columns) == ["mesh_name", "geometry"]
    assert areas["mesh_name"].tolist() == ["Modern Mesh"]
    assert areas.geometry.iloc[0].area == pytest.approx(100.0)
    assert diagnostic.iloc[0]["perimeter_status"] == "standard"
    assert diagnostic.iloc[0]["layout"] == "standard"
