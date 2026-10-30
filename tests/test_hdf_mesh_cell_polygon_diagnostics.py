"""Reference diagnostic contracts plus explicit native and inspection policies."""
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from pyproj import CRS

from ras_commander.hdf.HdfMesh import HdfMesh, MeshCellPolygonError


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("points", [
    [[0, 0], [1, 1], [0, 1], [1, 0]],
    [[0, 0], [1, 0], [2, 0], [3, 0]],
])
def test_native_invalid_closed_ring_keeps_strict_diagnostics(tmp_path, points):
    pytest.importorskip("ras_commander_fast_hdf")
    path = _write_polygon_cases(tmp_path / "invalid-closed.g01.hdf")
    base = "Geometry/2D Flow Areas/Diagnostic Mesh/"
    with h5py.File(path, "a") as hdf:
        hdf[base + "FacePoints Coordinate"][:4] = points
        del hdf[base + "Cells Face and Orientation Info"]
        hdf[base + "Cells Face and Orientation Info"] = np.array([[0, 4]], dtype=np.int32)
        # This case isolates geometric invalidity. Remove unreferenced rows
        # containing another case's corrupt face reference.
        values = hdf[base + "Cells Face and Orientation Values"][:4]
        del hdf[base + "Cells Face and Orientation Values"]
        hdf[base + "Cells Face and Orientation Values"] = values
    reference = HdfMesh.get_mesh_cell_polygons(path, engine="h5py", diagnostics=True)
    automatic = HdfMesh.get_mesh_cell_polygons(path, engine="auto", diagnostics=True)
    assert automatic.empty and reference.empty
    expected = reference.attrs["cell_polygon_diagnostics"]
    actual = automatic.attrs["cell_polygon_diagnostics"]
    assert len(actual) == len(expected) > 0
    # Native geometry reason codes may be more specific, but identity, status
    # and counts retain the reference contract.
    fields = ("mesh_name", "cell_id", "status", "face_count", "polygon_count")
    assert [tuple(row[key] for key in fields) for row in actual] == [
        tuple(row[key] for key in fields) for row in expected
    ]
    assert all(row["reason_code"] for row in actual)
    with pytest.raises(MeshCellPolygonError):
        HdfMesh.get_mesh_cell_polygons(path, engine="auto", strict=True)
    with pytest.raises(MeshCellPolygonError):
        HdfMesh.get_mesh_cell_polygons(path, engine="native", strict=True)


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

    cells = HdfMesh.get_mesh_cell_polygons(geom_hdf, engine="h5py")
    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(geom_hdf, engine="h5py")

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


def test_mesh_cell_polygon_attrs_do_not_break_concat(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "diagnostics.g01.hdf")
    cells = HdfMesh.get_mesh_cell_polygons(geom_hdf, engine="h5py")

    combined = pd.concat([cells, cells], ignore_index=True)

    assert combined["cell_id"].tolist() == [0, 2, 0, 2]


def test_clean_mesh_cell_polygon_attrs_do_not_break_concat(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "clean.g01.hdf")
    info_path = (
        "Geometry/2D Flow Areas/Diagnostic Mesh/"
        "Cells Face and Orientation Info"
    )
    values_path = (
        "Geometry/2D Flow Areas/Diagnostic Mesh/"
        "Cells Face and Orientation Values"
    )
    with h5py.File(geom_hdf, "a") as hdf_file:
        del hdf_file[info_path]
        del hdf_file[values_path]
        hdf_file.create_dataset(info_path, data=np.array([[0, 4]], dtype=np.int32))
        hdf_file.create_dataset(
            values_path,
            data=np.array([[0, 1], [1, 1], [2, 1], [3, 1]], dtype=np.int32),
        )

    cells = HdfMesh.get_mesh_cell_polygons(geom_hdf, engine="h5py", diagnostics=True)
    assert cells.attrs["cell_polygon_diagnostics"] == ()
    assert pd.concat([cells, cells], ignore_index=True)["cell_id"].tolist() == [0, 0]


def test_mesh_cell_polygon_partial_layout_reports_read_error(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "partial.g01.hdf")
    with h5py.File(geom_hdf, "a") as hdf_file:
        del hdf_file[
            "Geometry/2D Flow Areas/Diagnostic Mesh/"
            "Cells Face and Orientation Values"
        ]

    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(geom_hdf, engine="h5py")

    assert diagnostics["status"].tolist() == ["read_error"]
    assert diagnostics["reason_code"].tolist() == ["_MeshLayoutError"]
    with pytest.raises(MeshCellPolygonError, match="partial"):
        HdfMesh.get_mesh_cell_polygons(geom_hdf, strict=True, engine="h5py")


def test_zero_face_cell_is_not_classified_as_boundary_only(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "zero-face.g01.hdf")
    info_path = (
        "Geometry/2D Flow Areas/Diagnostic Mesh/"
        "Cells Face and Orientation Info"
    )
    with h5py.File(geom_hdf, "a") as hdf_file:
        info = hdf_file[info_path][()]
        del hdf_file[info_path]
        info[4, 1] = 0
        hdf_file.create_dataset(info_path, data=info)

    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(geom_hdf, engine="h5py")
    row = diagnostics.loc[diagnostics.cell_id == 4].iloc[0]

    assert row["status"] == "omitted"
    assert row["reason_code"] == "zero_faces"


@pytest.mark.parametrize("start,length", [(-1, 1), (999, 1), (0, -1), (16, 2)])
def test_invalid_face_spans_are_reported(tmp_path: Path, start: int, length: int):
    geom_hdf = _write_polygon_cases(tmp_path / f"invalid-{start}-{length}.g01.hdf")
    info_path = (
        "Geometry/2D Flow Areas/Diagnostic Mesh/"
        "Cells Face and Orientation Info"
    )
    with h5py.File(geom_hdf, "a") as hdf_file:
        info = hdf_file[info_path][()]
        del hdf_file[info_path]
        info[4] = [start, length]
        hdf_file.create_dataset(info_path, data=info)

    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(geom_hdf, engine="h5py")
    row = diagnostics.loc[diagnostics.cell_id == 4].iloc[0]
    assert row["status"] == "omitted"
    assert row["reason_code"] == "invalid_face_span"


def test_missing_named_area_topology_is_explicit(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "no-topology.g01.hdf")
    with h5py.File(geom_hdf, "a") as hdf_file:
        del hdf_file[
            "Geometry/2D Flow Areas/Diagnostic Mesh/"
            "Cells Face and Orientation Info"
        ]
        del hdf_file[
            "Geometry/2D Flow Areas/Diagnostic Mesh/"
            "Cells Face and Orientation Values"
        ]

    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(geom_hdf, engine="h5py")

    assert diagnostics["status"].tolist() == ["not_present"]
    assert diagnostics["reason_code"].tolist() == ["cell_topology_not_present"]


def test_mesh_cell_polygon_diagnostic_method_returns_native_ids(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "diagnostics.g01.hdf")

    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(geom_hdf, engine="h5py")

    assert diagnostics[["mesh_name", "cell_id"]].to_records(index=False).tolist() == [
        ("Diagnostic Mesh", 1),
        ("Diagnostic Mesh", 2),
        ("Diagnostic Mesh", 3),
        ("Diagnostic Mesh", 4),
    ]


def test_mesh_cell_polygon_strict_mode_rejects_any_anomaly(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "diagnostics.g01.hdf")

    with pytest.raises(MeshCellPolygonError, match="Diagnostic Mesh.*3"):
        HdfMesh.get_mesh_cell_polygons(geom_hdf, strict=True, engine="h5py")


def test_auto_diagnosis_of_corruption_is_the_reference_diagnosis(tmp_path, monkeypatch):
    pytest.importorskip("ras_commander_fast_hdf")
    from ras_commander.fast_hdf import FastHdfError
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    path = _write_polygon_cases(tmp_path / "inspect-corrupt.g01.hdf")
    # Required native execution refuses corrupt topology ...
    with pytest.raises(FastHdfError):
        HdfMesh.get_mesh_cell_polygons(path, engine="native")
    # ... while auto mode is the reference behaviour, with no native-only attrs.
    reference = HdfMesh.diagnose_mesh_cell_polygons(path, engine="h5py")
    diagnostics = HdfMesh.diagnose_mesh_cell_polygons(path)
    pd.testing.assert_frame_equal(diagnostics, reference)
    assert diagnostics.attrs == reference.attrs == {}
    assert diagnostics.loc[diagnostics.cell_id == 3, "missing_face_ids"].item() == (99,)


@pytest.mark.parametrize("required", ["explicit", "environment"])
def test_required_native_diagnosis_never_falls_back(tmp_path, monkeypatch, required):
    pytest.importorskip("ras_commander_fast_hdf")
    from ras_commander.fast_hdf import FastHdfError
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required" if required == "environment" else "auto")
    path = _write_polygon_cases(tmp_path / "required-corrupt.g01.hdf")
    calls = []
    original = HdfMesh.get_mesh_cell_polygons
    def recorded(*args, **kwargs):
        calls.append(kwargs.get("engine", "auto"))
        return original(*args, **kwargs)
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", staticmethod(recorded))
    engine = "native" if required == "explicit" else "auto"
    with pytest.raises(FastHdfError):
        HdfMesh.diagnose_mesh_cell_polygons(path, engine=engine)
    assert calls == [engine]


def test_cell_polygon_diagnostics_attr_is_opt_in(tmp_path: Path):
    geom_hdf = _write_polygon_cases(tmp_path / "opt-in.g01.hdf")
    default = HdfMesh.get_mesh_cell_polygons(geom_hdf, engine="h5py")
    attached = HdfMesh.get_mesh_cell_polygons(geom_hdf, engine="h5py", diagnostics=True)
    assert "cell_polygon_diagnostics" not in default.attrs
    assert [row["cell_id"] for row in attached.attrs["cell_polygon_diagnostics"]] == [1, 2, 3, 4]
    # The flag only controls the attr: the polygons are identical either way.
    assert default["cell_id"].tolist() == attached["cell_id"].tolist() == [0, 2]
    assert all(a.equals(b) for a, b in zip(default.geometry, attached.geometry))
    # diagnose_mesh_cell_polygons enables diagnostics itself.
    assert HdfMesh.diagnose_mesh_cell_polygons(geom_hdf, engine="h5py")["cell_id"].tolist() == [1, 2, 3, 4]


def test_cell_polygon_diagnostics_attr_is_opt_in_for_auto(tmp_path: Path, monkeypatch):
    # Auto policy: synthetic files store a vlen Projection that forced native refuses.
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    geom_hdf = _write_polygon_cases(tmp_path / "opt-in-clean.g01.hdf")
    base = "Geometry/2D Flow Areas/Diagnostic Mesh/"
    with h5py.File(geom_hdf, "a") as hdf_file:
        del hdf_file[base + "Cells Face and Orientation Info"]
        del hdf_file[base + "Cells Face and Orientation Values"]
        hdf_file[base + "Cells Face and Orientation Info"] = np.array([[0, 4]], dtype=np.int32)
        hdf_file[base + "Cells Face and Orientation Values"] = np.array(
            [[0, 1], [1, 1], [2, 1], [3, 1]], dtype=np.int32)
    default = HdfMesh.get_mesh_cell_polygons(geom_hdf)
    attached = HdfMesh.get_mesh_cell_polygons(geom_hdf, diagnostics=True)
    assert "cell_polygon_diagnostics" not in default.attrs
    assert attached.attrs["cell_polygon_diagnostics"] == ()
    assert default["cell_id"].tolist() == attached["cell_id"].tolist() == [0]
