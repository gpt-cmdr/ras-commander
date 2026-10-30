"""Outward text BC placement and exact native face ownership contracts."""

import hashlib

import h5py
import numpy as np
import pytest
from shapely.geometry import LineString, Polygon

from ras_commander import GeomBcLines
from ras_commander.geom._bc_outward import _mesh_fingerprints, _outward_arc


@pytest.mark.parametrize("reverse", [False, True])
def test_rectangle_and_ring_orientation(reverse):
    polygon = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    if reverse:
        polygon = Polygon(list(polygon.exterior.coords)[::-1])
    line = _outward_arc(polygon, [(10, 0.004), (90, -0.003)], 1)
    assert line.distance(polygon) == pytest.approx(1)
    assert line.hausdorff_distance(LineString([(10, -1), (90, -1)])) < 1e-9


def test_ring_seam_corner_is_outside():
    polygon = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    line = _outward_arc(polygon, [(0, 30), (0, 0), (30, 0)], 1)
    assert line.intersection(polygon).is_empty
    assert line.distance(polygon) == pytest.approx(1)
    assert (-1, -1) in line.coords


def test_global_buffer_protects_neighboring_concavity():
    polygon = Polygon(
        [(0, 0), (100, 0), (100, 100), (50, 100), (50, 1), (49, 1), (49, 100), (0, 100)]
    )
    line = _outward_arc(polygon, [(20, 0), (80, 0)], 1)
    assert line.distance(polygon) == pytest.approx(1)
    assert line.intersection(polygon).is_empty


@pytest.mark.parametrize("coordinates", [[(10, 10), (90, 10)], [(0, 0), (0, 0)]])
def test_interior_or_collapsed_line_refused(coordinates):
    with pytest.raises(ValueError):
        _outward_arc(Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]), coordinates, 1)


def _geometry(path):
    points = [(0, 0), (100, 0), (100, 100), (0, 100)]
    packed = "\n".join("".join(f"{value:16g}" for value in xy) for xy in points)
    path.write_text(
        "Geom Title=Offset test\nProgram Version=6.60\nStorage Area=Area,,\nStorage Area Surface Line=4\n"
        + packed
        + "\nStorage Area 2D Points=4\n"
        + packed
        + "\nLCMann Time=Dec/30/1899 00:00:00\n"
    )
    GeomBcLines.add_bc_lines(
        path,
        [
            {
                "name": "External",
                "storage_area": "Area",
                "coordinates": [(10, 0), (90, 0)],
            },
            {
                "name": "Internal",
                "storage_area": "Area",
                "coordinates": [(10, 20), (90, 20)],
            },
        ],
    )
    return path


def test_public_dry_run_apply_hash_guard_and_idempotence(tmp_path):
    path = _geometry(tmp_path / "test.g01")
    before = path.read_bytes()
    original_internal = GeomBcLines.get_bc_lines(path).iloc[1].to_dict()
    plan = GeomBcLines.offset_external_bc_lines(str(path), ["External"], text_only=True)
    assert path.read_bytes() == before
    assert (
        plan["dry_run"]
        and plan["geometry_sha256_before"] == hashlib.sha256(before).hexdigest()
    )
    with pytest.raises(ValueError, match="changed"):
        GeomBcLines.offset_external_bc_lines(
            path,
            ["External"],
            dry_run=False,
            expected_geometry_sha256="0" * 64,
            text_only=True,
        )
    applied = GeomBcLines.offset_external_bc_lines(
        path,
        ["External"],
        dry_run=False,
        expected_geometry_sha256=plan["geometry_sha256_before"],
        text_only=True,
    )
    assert applied["lines"][0]["minimum_outward_clearance"] == pytest.approx(1)
    assert GeomBcLines.get_bc_lines(path).iloc[0].to_dict() == original_internal
    after = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    GeomBcLines.offset_external_bc_lines(
        path, ["External"], dry_run=False, text_only=True
    )
    assert path.read_bytes() == after and path.stat().st_mtime_ns == mtime


@pytest.mark.parametrize("distance", [0, -1, float("nan"), float("inf"), True])
def test_invalid_distance_no_write(tmp_path, distance):
    path = _geometry(tmp_path / "test.g01")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        GeomBcLines.offset_external_bc_lines(
            path, ["External"], distance, dry_run=False
        )
    assert path.read_bytes() == before


def _hdf(path):
    with h5py.File(path, "w") as handle:
        bc = handle.require_group("Geometry/Boundary Condition Lines")
        bc.create_dataset(
            "Attributes",
            data=np.array(
                [(b"External", b"Area", b"External", 10.0)],
                dtype=[
                    ("Name", "S32"),
                    ("SA-2D", "S16"),
                    ("Type", "S8"),
                    ("Length", "f4"),
                ],
            ),
        )
        bc.create_dataset(
            "External Faces",
            data=np.array(
                [(0, 4), (0, 5)], dtype=[("BC Line ID", "i4"), ("Face Index", "i4")]
            ),
        )
        handle.create_dataset(
            "Geometry/2D Flow Areas/Area/FacePoints Coordinate",
            data=np.array([[0.0, np.nan], [10.0, 20.0]]),
        )
    return path


@pytest.mark.synthetic_hdf_layout
def test_exact_faces_and_mesh_nan_bytes(tmp_path):
    path = _hdf(tmp_path / "test.g01.hdf")
    fingerprints = _mesh_fingerprints(path)
    assert GeomBcLines.validate_external_bc_face_sets(
        path,
        {"External": [5, 4]},
        expected_mesh_fingerprints=fingerprints,
        expected_bc_areas={"External": "Area"},
    )["valid"]
    for expected in (
        {"External": [4]},
        {"External": [4, 5, 6]},
        {"Other": [4]},
        {"External": []},
    ):
        with pytest.raises(ValueError):
            GeomBcLines.validate_external_bc_face_sets(
                path, expected, expected_bc_areas={name: "Area" for name in expected}
            )
    with h5py.File(path, "a") as handle:
        handle["Geometry/2D Flow Areas/Area/FacePoints Coordinate"][0, 0] = 1
    with pytest.raises(ValueError, match="mesh_changed=True"):
        GeomBcLines.validate_external_bc_face_sets(
            path,
            {"External": [4, 5]},
            expected_mesh_fingerprints=fingerprints,
            expected_bc_areas={"External": "Area"},
        )


@pytest.mark.synthetic_hdf_layout
def test_internal_type_is_not_accepted_as_external(tmp_path):
    path = _hdf(tmp_path / "test.g01.hdf")
    with h5py.File(path, "a") as handle:
        attributes = handle["Geometry/Boundary Condition Lines/Attributes"][()]
        attributes["Type"] = b"Internal"
        handle["Geometry/Boundary Condition Lines/Attributes"][...] = attributes
    with pytest.raises(ValueError, match="MISMATCH"):
        GeomBcLines.validate_external_bc_face_sets(
            path, {"External": [4, 5]}, expected_bc_areas={"External": "Area"}
        )


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("values", [[4.1, 5.9], [True, 5], [4, 4]])
def test_invalid_native_face_ids_refused(tmp_path, values):
    path = _hdf(tmp_path / "test.g01.hdf")
    with pytest.raises(ValueError):
        GeomBcLines.validate_external_bc_face_sets(
            path, {"External": values}, expected_bc_areas={"External": "Area"}
        )


@pytest.mark.synthetic_hdf_layout
def test_native_area_change_and_incomplete_capture_refused(tmp_path):
    path = _geometry(tmp_path / "test.g01")
    _hdf(path.with_suffix(".g01.hdf"))
    with pytest.raises(ValueError):
        GeomBcLines.offset_external_bc_lines(path, ["Internal"], dry_run=False)
    planned = GeomBcLines.offset_external_bc_lines(path, ["External"])
    assert planned["native_guard"]["bc_areas"] == {"External": "Area"}
    with pytest.raises(ValueError, match="wrong native area"):
        GeomBcLines.validate_external_bc_face_sets(
            path.with_suffix(".g01.hdf"),
            {"External": [4, 5]},
            expected_bc_areas={"External": "Other"},
        )


@pytest.mark.parametrize("kwargs", [{"text_only": "False"}, {"dry_run": "False"}])
def test_boolean_modes_fail_closed(tmp_path, kwargs):
    path = _geometry(tmp_path / "test.g01")
    with pytest.raises(ValueError, match="booleans"):
        GeomBcLines.offset_external_bc_lines(path, ["External"], **kwargs)


def test_empty_mesh_fingerprints_fail_closed(tmp_path):
    path = _hdf(tmp_path / "test.g01.hdf")
    with pytest.raises(ValueError, match="must not be empty"):
        GeomBcLines.validate_external_bc_face_sets(
            path,
            {"External": [4, 5]},
            expected_bc_areas={"External": "Area"},
            expected_mesh_fingerprints={},
        )


@pytest.mark.synthetic_hdf_layout
def test_failed_readback_restores_bytes_mtime_and_keeps_backup(tmp_path, monkeypatch):
    path = _geometry(tmp_path / "test.g01")
    hdf = _hdf(path.with_suffix(".g01.hdf"))
    original, original_hdf, stat = path.read_bytes(), hdf.read_bytes(), path.stat()
    real = GeomBcLines.get_bc_lines
    calls = 0

    def bad_readback(geom_file):
        nonlocal calls
        calls += 1
        result = real(geom_file)
        if calls >= 2:
            result.loc[result.name.eq("External"), "coordinates"] = result.loc[
                result.name.eq("External"), "coordinates"
            ].apply(lambda _: [(10, 0), (90, 0)])
        return result

    monkeypatch.setattr(GeomBcLines, "get_bc_lines", staticmethod(bad_readback))
    with pytest.raises(ValueError, match="clearance"):
        GeomBcLines.offset_external_bc_lines(path, ["External"], dry_run=False)
    assert path.read_bytes() == original and path.stat().st_mtime_ns == stat.st_mtime_ns
    assert hdf.read_bytes() == original_hdf
    assert list(tmp_path.glob("test.g01.bak*"))


@pytest.mark.synthetic_hdf_layout(
    "Internal",
)
@pytest.mark.parametrize("condition", ["Internal", "missing"])
def test_perimeter_line_requires_complete_external_native_evidence(tmp_path, condition):
    path = _geometry(tmp_path / "test.g01")
    hdf = _hdf(path.with_suffix(".g01.hdf"))
    with h5py.File(hdf, "a") as handle:
        if condition == "Internal":
            attrs = handle["Geometry/Boundary Condition Lines/Attributes"][()]
            attrs["Type"] = b"Internal"
            handle["Geometry/Boundary Condition Lines/Attributes"][...] = attrs
        else:
            del handle["Geometry/Boundary Condition Lines/External Faces"]
    before, hdf_before, stat = path.read_bytes(), hdf.read_bytes(), path.stat()
    with pytest.raises(ValueError, match="complete matching"):
        GeomBcLines.offset_external_bc_lines(path, ["External"], dry_run=False)
    assert path.read_bytes() == before and path.stat().st_mtime_ns == stat.st_mtime_ns
    assert hdf.read_bytes() == hdf_before


@pytest.mark.synthetic_hdf_layout
def test_real_native_area_reassignment_is_refused(tmp_path):
    path = _hdf(tmp_path / "test.g01.hdf")
    with h5py.File(path, "a") as handle:
        handle.create_dataset(
            "Geometry/2D Flow Areas/Other/FacePoints Coordinate",
            data=np.array([[1.0, 2.0]]),
        )
    fingerprints = _mesh_fingerprints(path)
    with h5py.File(path, "a") as handle:
        attrs = handle["Geometry/Boundary Condition Lines/Attributes"][()]
        attrs["SA-2D"] = b"Other"
        handle["Geometry/Boundary Condition Lines/Attributes"][...] = attrs
    with pytest.raises(ValueError, match="wrong native area"):
        GeomBcLines.validate_external_bc_face_sets(
            path,
            {"External": [4, 5]},
            expected_bc_areas={"External": "Area"},
            expected_mesh_fingerprints=fingerprints,
        )
