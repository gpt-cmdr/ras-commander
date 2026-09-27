from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf.HdfMesh import HdfMesh, MeshCellPolygonError


def _write_polygon_cases(path: Path) -> Path:
    points = np.array(
        [
            [0, 0], [1, 0], [1, 1], [0, 1],
            [2, 0], [3, 0], [3, 1], [2, 1],
            [4, 0], [5, 0], [4.5, 1],
            [6, 0], [7, 0], [6.5, 1],
        ],
        dtype=float,
    )
    face_indexes = np.array(
        [
            [0, 1], [1, 2], [2, 3], [3, 0],       # valid square
            [4, 5], [5, 6], [6, 7],                # open ring
            [8, 9], [9, 10], [10, 8],              # triangle one
            [11, 12], [12, 13], [13, 11],          # triangle two
        ],
        dtype=np.int32,
    )
    cell_faces = [
        [0, 1, 2, 3],
        [4, 5, 6],
        [7, 8, 9, 10, 11, 12],
        [0, 1, 99],
        [0],
    ]
    offsets = []
    values = []
    for face_ids in cell_faces:
        offsets.append([len(values), len(face_ids)])
        values.extend([face_id, 1] for face_id in face_ids)

    attributes = np.zeros(1, dtype=[("Name", "S64")])
    attributes["Name"] = b"Diagnostic Mesh"
    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()
        base = "Geometry/2D Flow Areas"
        mesh = f"{base}/Diagnostic Mesh"
        hdf_file.create_dataset(f"{base}/Attributes", data=attributes)
        hdf_file.create_dataset(f"{mesh}/Faces FacePoint Indexes", data=face_indexes)
        hdf_file.create_dataset(f"{mesh}/FacePoints Coordinate", data=points)
        hdf_file.create_dataset(
            f"{mesh}/Faces Perimeter Info",
            data=np.zeros((len(face_indexes), 2), dtype=np.int32),
        )
        hdf_file.create_dataset(
            f"{mesh}/Faces Perimeter Values",
            data=np.empty((0, 2), dtype=float),
        )
        hdf_file.create_dataset(
            f"{mesh}/Cells Face and Orientation Info",
            data=np.asarray(offsets, dtype=np.int32),
        )
        hdf_file.create_dataset(
            f"{mesh}/Cells Face and Orientation Values",
            data=np.asarray(values, dtype=np.int32),
        )
    return path


def test_mesh_cell_polygon_anomalies_are_reported_without_renumbering(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = _write_polygon_cases(tmp_path / "diagnostics.g01.hdf")

    cells = HdfMesh.get_mesh_cell_polygons(geom_hdf)
    diagnostics = cells.attrs["cell_polygon_diagnostics"]

    assert cells["cell_id"].tolist() == [0, 2]
    assert diagnostics["cell_id"].tolist() == [1, 2, 3, 4]
    assert diagnostics["reason_code"].tolist() == [
        "no_polygon",
        "multiple_polygons",
        "missing_face_reference",
        "insufficient_faces",
    ]
    assert diagnostics.loc[diagnostics.cell_id == 2, "polygon_count"].item() == 2
    assert diagnostics.loc[diagnostics.cell_id == 3, "missing_face_ids"].item() == (99,)
    assert diagnostics.loc[diagnostics.cell_id == 4, "status"].item() == "boundary_only"
    assert "reconstruction was incomplete or ambiguous" in caplog.text


def test_mesh_cell_polygon_diagnostic_method_returns_native_ids(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "diagnostics.g01.hdf")

    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(geom_hdf)

    assert diagnostics[["mesh_name", "cell_id"]].to_records(index=False).tolist() == [
        ("Diagnostic Mesh", 1),
        ("Diagnostic Mesh", 2),
        ("Diagnostic Mesh", 3),
        ("Diagnostic Mesh", 4),
    ]


def test_mesh_cell_polygon_strict_mode_rejects_any_anomaly(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "diagnostics.g01.hdf")

    with pytest.raises(MeshCellPolygonError, match="Diagnostic Mesh.*3"):
        HdfMesh.get_mesh_cell_polygons(geom_hdf, strict=True)
