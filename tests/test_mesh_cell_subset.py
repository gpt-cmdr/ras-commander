"""Exact topology tests on independent regular-grid native-layout geometry HDFs."""

from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS
from shapely.geometry import Polygon

from ras_commander.geom import GeomMesh
from ras_commander.geom._cell_subset import (
    _build_subset,
    _pack,
)


def grid(path: Path, n: int = 4):
    """Construct cell/face connectivity from independent CCW square polygons."""
    points = [(x, y) for y in range(n + 1) for x in range(n + 1)]
    lookup = {xy: i for i, xy in enumerate(points)}
    vertices = []
    faces = []
    pairs = []
    face_lookup = {}
    cell_faces = []
    for y in range(n):
        for x in range(n):
            cell = y * n + x
            ring = [lookup[v] for v in [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]]
            vertices.append(ring)
            row = []
            for a, b in zip(ring, ring[1:] + ring[:1]):
                key = tuple(sorted((a, b)))
                if key in face_lookup:
                    face = face_lookup[key]
                    pairs[face][1] = cell
                    row.append((face, -1))
                else:
                    face = len(faces)
                    face_lookup[key] = face
                    faces.append((a, b))
                    pairs.append([cell, -1])
                    row.append((face, 1))
            cell_faces.append(np.array(row, dtype=np.int32))
    centres = [(x + 0.5, y + 0.5) for y in range(n) for x in range(n)]
    all_vertices = [row + [-1] * 4 for row in vertices]
    for face, (a, b) in enumerate(faces):
        if pairs[face][1] == -1:
            pairs[face][1] = len(centres)
            centres.append(tuple((np.array(points[a]) + points[b]) / 2))
            cell_faces.append(np.array([[face, -1]], dtype=np.int32))
            all_vertices.append([a, b] + [-1] * 6)
    cinfo, cvals = _pack(cell_faces, 2, np.int32)
    normals = []
    for a, b in faces:
        d = np.array(points[b]) - points[a]
        normals.append([d[1], -d[0], 1.0])
    tables = {
        "Cells Center Coordinate": np.array(centres, dtype=np.float64),
        "Cells FacePoint Indexes": np.array(all_vertices, dtype=np.int32),
        "Cells Face and Orientation Info": cinfo,
        "Cells Face and Orientation Values": cvals,
        "Faces Cell Indexes": np.array(pairs, dtype=np.int32),
        "Faces FacePoint Indexes": np.array(faces, dtype=np.int32),
        "Faces NormalUnitVector and Length": np.array(normals, dtype=np.float64),
        "FacePoints Coordinate": np.array(points, dtype=np.float64),
        "Faces Perimeter Info": np.zeros((len(faces), 2), dtype=np.int32),
        "Faces Perimeter Values": np.empty((0, 2), dtype=np.float64),
        "Faces Low Elevation Centroid": np.zeros((len(faces), 2), dtype=np.float64),
        "Faces Minimum Elevation": np.zeros(len(faces), dtype=np.float32),
        "Faces Area Elevation Info": np.zeros((len(faces), 2), dtype=np.int32),
        "Faces Area Elevation Values": np.empty((0, 4), dtype=np.float32),
        "Cells Minimum Elevation": np.r_[
            np.zeros(n * n), np.full(len(centres) - n * n, np.nan)
        ].astype(np.float32),
        "Cells Surface Area": np.r_[
            np.ones(n * n), np.zeros(len(centres) - n * n)
        ].astype(np.float32),
        "Cells Center Manning's n": np.full(len(centres), 0.06, dtype=np.float32),
        "Cells Volume Elevation Info": np.zeros((len(centres), 2), dtype=np.int32),
        "Cells Volume Elevation Values": np.empty((0, 2), dtype=np.float32),
    }
    with h5py.File(path, "w") as h:
        h.attrs["File Type"] = np.bytes_("HEC-RAS Geometry")
        h.attrs["File Version"] = np.bytes_("HEC-RAS 6.6")
        h.attrs["Projection"] = np.bytes_(CRS.from_epsg(2278).to_wkt())
        h.require_group("Geometry/2D Flow Areas").create_dataset(
            "Attributes",
            data=np.array(
                [(b"Area", n * n)], dtype=[("Name", "S16"), ("Cell Count", "i4")]
            ),
        )
        g = h.create_group("Geometry/2D Flow Areas/Area")
        for key, values in tables.items():
            g.create_dataset(key, data=values)
        g.attrs["Cell Maximum Index"] = np.int32(0)
        g.attrs["Data Date"] = np.bytes_("01JAN2000 00:00:00")
        g.attrs["Cell Maximum Size"] = np.float32(1)
    return tables


def child_text(path, bounds=(1, 1, 3, 3)):
    x0, y0, x1, y1 = bounds
    ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    path.write_text(
        "Geom Title=Child\nStorage Area=Area,0,0\nStorage Area Surface Line= 5\n"
        + "".join(f"{x:16.6f}{y:16.6f}\n" for x, y in ring)
        + "Storage Area Is2D=-1\nStorage Area 2D Points= 1\n"
        + f"{2.0:16.6f}{2.0:16.6f}\n"
        + "Storage Area 2D PointsPerimeterTime=01Jan2000 00:00:00\n"
    )


@pytest.mark.parametrize("ids", [[0], [5, 6, 9, 10], list(range(16)), [3, 7, 11, 15]])
def test_subset_retains_exact_cell_vertices_and_boundary_incidence(tmp_path, ids):
    source = tmp_path / "Parent.g01.hdf"
    original = grid(source)
    keep = np.zeros(16, dtype=bool)
    keep[ids] = True
    with h5py.File(source) as h:
        sub = _build_subset(h["Geometry/2D Flow Areas/Area"], keep)
    assert sub.n_real == len(ids)
    assert list(sub.cell_src[: sub.n_real]) == sorted(ids)
    ends = sub.tables["Faces FacePoint Indexes"]
    pairs = sub.tables["Faces Cell Indexes"]
    info = sub.tables["FacePoints Face and Orientation Info"]
    values = sub.tables["FacePoints Face and Orientation Values"]
    assert info[:, 1].sum() == len(values)
    for point, (start, count) in enumerate(info):
        row = values[start : start + count, 0]
        expected = np.flatnonzero(np.any(ends == point, axis=1))
        assert set(row) == set(expected)
        boundary = [int(f) for f in row if pairs[f, 1] >= len(ids)]
        if boundary:
            assert len(boundary) == 2
            assert ends[row[0], 0] == point and pairs[row[0], 1] >= len(ids)
            assert ends[row[-1], 1] == point and pairs[row[-1], 1] >= len(ids)
    for child, parent in enumerate(sorted(ids)):
        a = original["FacePoints Coordinate"][
            original["Cells FacePoint Indexes"][parent, :4]
        ]
        row = sub.tables["Cells FacePoint Indexes"][child]
        b = sub.tables["FacePoints Coordinate"][row[row >= 0]]
        assert Polygon(a).equals(Polygon(b))


@pytest.mark.parametrize("ids", [[0, 15], [0, 5], [i for i in range(16) if i != 5]])
def test_disconnected_hole_and_pinched_selections_block(tmp_path, ids):
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    keep = np.zeros(16, dtype=bool)
    keep[ids] = True
    with h5py.File(source) as h, pytest.raises((ValueError, KeyError)):
        _build_subset(h["Geometry/2D Flow Areas/Area"], keep)


@pytest.mark.parametrize("defect", ["duplicate", "missing", "outside"])
def test_selected_source_cell_incidence_blocks(tmp_path, defect):
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    with h5py.File(source, "r+") as h:
        g = h["Geometry/2D Flow Areas/Area"]
        row = g["Cells FacePoint Indexes"][5]
        row[:4] = {
            "duplicate": [6, 6, 12, 11],
            "missing": [-1, -1, -1, -1],
            "outside": [1000, 7, 12, 11],
        }[defect]
        g["Cells FacePoint Indexes"][5] = row
        keep = np.zeros(16, dtype=bool)
        keep[[5, 6, 9, 10]] = True
        with pytest.raises(ValueError):
            _build_subset(g, keep)
        keep[:] = False
        keep[0] = True
        assert _build_subset(g, keep).n_real == 1


def planned(tmp_path):
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    target = tmp_path / "Child.g02"
    child_text(target)
    grid(Path(str(target) + ".hdf"))
    before = {p: p.read_bytes() for p in (source, target, Path(str(target) + ".hdf"))}
    plan = GeomMesh.plan_cell_subset(source, target, [10, 5, 9, 6], "Area")
    assert plan.parent_cell_ids == (5, 6, 9, 10)
    assert all(p.read_bytes() == raw for p, raw in before.items())
    return plan, source, target


def test_public_plan_is_read_only_and_deterministic(tmp_path):
    plan, source, target = planned(tmp_path)
    assert plan == GeomMesh.plan_cell_subset(
        str(source), str(target), (5, 6, 9, 10), "Area"
    )
    assert plan.to_dict()["native_completion"] == "not_run"
    assert plan.face_count == 12 and plan.facepoint_count == 9


def test_plan_rejects_additional_text_2d_area(tmp_path):
    from ras_commander.geom import GeomStorage

    _, source, target = planned(tmp_path)
    GeomStorage.set_2d_flow_area_perimeter(
        target, "Another", coordinates=[(0, 0), (1, 0), (1, 1), (0, 0)]
    )
    with pytest.raises(ValueError, match="exactly the named child"):
        GeomMesh.plan_cell_subset(source, target, [5, 6, 9, 10], "Area")


@pytest.mark.parametrize("ids", [[], [5, 5], [-1], [16], [5.0], [True]])
def test_invalid_physical_selection_is_rejected(tmp_path, ids):
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    target = tmp_path / "Child.g02"
    child_text(target)
    grid(Path(str(target) + ".hdf"))
    with pytest.raises(ValueError):
        GeomMesh.plan_cell_subset(source, target, ids, "Area")


@pytest.mark.parametrize("changed", ["source", "text", "hdf"])
def test_apply_rejects_changed_inputs_before_native_access(tmp_path, changed):
    plan, source, target = planned(tmp_path)
    path = {"source": source, "text": target, "hdf": Path(str(target) + ".hdf")}[
        changed
    ]
    with path.open("ab") as f:
        f.write(b"changed")
    current = {p: p.read_bytes() for p in (source, target, Path(str(target) + ".hdf"))}
    with pytest.raises(RuntimeError, match="changed after planning"):
        GeomMesh.apply_cell_subset(plan)
    assert all(p.read_bytes() == raw for p, raw in current.items())


def test_completed_native_geometry_target_can_be_replanned(tmp_path):
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    target = tmp_path / "Child.g02"
    child_text(target)
    hdf = Path(str(target) + ".hdf")
    grid(hdf)
    with h5py.File(hdf, "r+") as handle:
        # Ras.exe can stamp a .g##.hdf this way after native completion.
        handle.attrs["File Type"] = np.bytes_("HEC-RAS Results")
        assert list(handle) == ["Geometry"]
    plan = GeomMesh.plan_cell_subset(source, target, [5, 6, 9, 10], "Area")
    assert plan.parent_cell_ids == (5, 6, 9, 10)


@pytest.mark.parametrize("root", ["Results", "Event Conditions", "Plan Data"])
def test_results_stamped_target_with_non_geometry_data_is_rejected(tmp_path, root):
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    target = tmp_path / "Child.g02"
    child_text(target)
    hdf = Path(str(target) + ".hdf")
    grid(hdf)
    with h5py.File(hdf, "r+") as handle:
        handle.attrs["File Type"] = np.bytes_("HEC-RAS Results")
        handle.create_group(root)
    with pytest.raises(ValueError, match="target.*geometry-only"):
        GeomMesh.plan_cell_subset(source, target, [5, 6, 9, 10], "Area")


def test_natively_compiled_source_with_only_geometry_is_accepted(tmp_path):
    # Ras.exe geometry completion stamps a compiled parent .g##.hdf "HEC-RAS Results"
    # although its sole root group is Geometry.
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    target = tmp_path / "Child.g02"
    child_text(target)
    grid(Path(str(target) + ".hdf"))
    with h5py.File(source, "r+") as handle:
        handle.attrs["File Type"] = np.bytes_("HEC-RAS Results")
    plan = GeomMesh.plan_cell_subset(source, target, [5, 6, 9, 10], "Area")
    assert list(plan.parent_cell_ids) == [5, 6, 9, 10]


@pytest.mark.parametrize("extra_group", ["Plan Data", "Event Conditions"])
def test_results_stamped_source_with_plan_content_is_rejected(tmp_path, extra_group):
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    target = tmp_path / "Child.g02"
    child_text(target)
    grid(Path(str(target) + ".hdf"))
    with h5py.File(source, "r+") as handle:
        handle.attrs["File Type"] = np.bytes_("HEC-RAS Results")
        handle.create_group(extra_group)
    with pytest.raises(ValueError, match="source.*geometry-only"):
        GeomMesh.plan_cell_subset(source, target, [5, 6, 9, 10], "Area")


def test_results_source_and_crs_mismatch_block(tmp_path):
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    target = tmp_path / "Child.g02"
    child_text(target)
    hdf = Path(str(target) + ".hdf")
    grid(hdf)
    with h5py.File(source, "r+") as h:
        h.create_group("Results")
    with pytest.raises(ValueError, match="geometry-only"):
        GeomMesh.plan_cell_subset(source, target, [5, 6, 9, 10], "Area")
    with h5py.File(source, "r+") as h:
        del h["Results"]
    with h5py.File(hdf, "r+") as h:
        h.attrs["Projection"] = np.bytes_(CRS.from_epsg(3857).to_wkt().encode("utf-8"))
    with pytest.raises(ValueError, match="CRS differ"):
        GeomMesh.plan_cell_subset(source, target, [5, 6, 9, 10], "Area")


def test_child_crs_can_resolve_from_matching_rasmap_projection(tmp_path):
    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    target = tmp_path / "Child.g02"
    child_text(target)
    hdf = Path(str(target) + ".hdf")
    grid(hdf)
    with h5py.File(hdf, "r+") as h:
        del h.attrs["Projection"]
    (tmp_path / "Projection.prj").write_text(CRS.from_epsg(2278).to_wkt())
    (tmp_path / "Child.rasmap").write_text(
        '<RASMapper><RASProjectionFilename Filename="Projection.prj" /></RASMapper>'
    )
    plan = GeomMesh.plan_cell_subset(source, target, [5, 6, 9, 10], "Area")
    assert CRS.from_wkt(plan.crs_wkt).equals(CRS.from_epsg(2278))
    with h5py.File(hdf) as h:
        assert "Projection" not in h.attrs


def test_staged_associations_keep_original_resolution_and_spelling(tmp_path):
    from ras_commander.geom._cell_subset import (
        _relocate_associations,
        _restore_associations,
    )

    root = tmp_path / "model"
    root.mkdir()
    inputs = root / "Input"
    inputs.mkdir()
    land = root / "Land Cover"
    land.mkdir()
    sidecar = land / "LandCover.hdf"
    sidecar.write_bytes(b"classification fixture")
    original = inputs / "Child.g02.hdf"
    grid(original)
    stage = inputs / "temporary"
    stage.mkdir()
    staged = stage / original.name
    staged.write_bytes(original.read_bytes())
    value = np.bytes_(r"..\Land Cover\LandCover.hdf")
    with h5py.File(staged, "r+") as h:
        h["Geometry"].attrs["Land Cover Filename"] = value
    saved = _relocate_associations(staged, original)
    with h5py.File(staged) as h:
        assert Path(h["Geometry"].attrs["Land Cover Filename"].decode()) == sidecar
    _restore_associations(staged, saved)
    with h5py.File(staged) as h:
        assert h["Geometry"].attrs["Land Cover Filename"] == value


def _fake_native_runtime(monkeypatch, tmp_path):
    import importlib
    from types import SimpleNamespace

    import ras_commander._gdal_runtime as gdal
    import ras_commander._landcover_native as native

    monkeypatch.setattr(
        importlib.import_module("ras_commander.RasPrj"),
        "ras",
        SimpleNamespace(initialized=False),
    )

    monkeypatch.setattr(native, "find_hecras_install", lambda version: tmp_path)
    (tmp_path / "Ras.exe").write_bytes(b"fake native executable for failure injection")
    (tmp_path / "RasMapperLib.dll").write_bytes(
        b"fake native library for failure injection"
    )
    monkeypatch.setattr(gdal, "configure_rasmapper_gdal_bridge", lambda install: None)


def test_runtime_resolution_preserves_custom_project_install(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import ras_commander._landcover_native as native
    from ras_commander.geom._cell_subset import _resolve_subset_install

    custom = tmp_path / "custom-runtime"
    custom.mkdir()
    for name in ("Ras.exe", "RasMapperLib.dll"):
        (custom / name).write_bytes(b"runtime fixture")
    ras = SimpleNamespace(ras_exe_path=custom / "Ras.exe")
    monkeypatch.setattr(
        native,
        "find_hecras_install",
        lambda version: pytest.fail("must retain explicit project runtime"),
    )
    assert _resolve_subset_install("6.6", None, ras) == custom
    assert _resolve_subset_install("6.6", custom, ras) == custom
    with pytest.raises(ValueError, match="conflicts"):
        _resolve_subset_install("6.6", tmp_path / "another-install", ras)


def test_native_serialization_failure_preserves_both_owned_inputs(
    tmp_path, monkeypatch
):
    import subprocess
    from types import SimpleNamespace

    plan, source, target = planned(tmp_path)
    paths = (source, target, Path(str(target) + ".hdf"))
    original = {p: p.read_bytes() for p in paths}
    _fake_native_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stderr="injected native failure", stdout=""
        ),
    )
    with pytest.raises(RuntimeError, match="injected native failure"):
        GeomMesh.apply_cell_subset(plan)
    assert all(p.read_bytes() == raw for p, raw in original.items())
    assert not list(tmp_path.glob(".ras-cell-subset-*"))


def test_second_pair_replacement_failure_restores_exact_original_bytes(
    tmp_path, monkeypatch
):
    import json
    import os
    import subprocess
    from types import SimpleNamespace

    plan, source, target = planned(tmp_path)
    original = {p: p.read_bytes() for p in (source, target, Path(str(target) + ".hdf"))}
    _fake_native_runtime(monkeypatch, tmp_path)

    def worker(argv, **kwargs):
        Path(argv[-1]).write_text(json.dumps({"mesh_state": "Complete"}))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(subprocess, "run", worker)
    replace = os.replace

    def fail_second(src, dst):
        if Path(dst) == target:
            raise OSError("injected second replacement failure")
        return replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_second)
    with pytest.raises(OSError, match="injected second replacement"):
        GeomMesh.apply_cell_subset(plan)
    assert all(p.read_bytes() == raw for p, raw in original.items())
    assert len(list(tmp_path.glob("*.cell-subset-*.bak"))) == 2


def written_subset(tmp_path):
    from ras_commander.geom._cell_subset import _selection, _write_subset

    plan, source, target = planned(tmp_path)
    with h5py.File(source) as h:
        _, subset = _selection(h["Geometry/2D Flow Areas/Area"], plan.parent_cell_ids)
    hdf = Path(str(target) + ".hdf")
    _write_subset(source, hdf, "Area", subset, plan.crs_wkt)
    return plan, hdf, subset


@pytest.mark.parametrize(
    "changed", ["facepoints", "endpoints", "cell_pairs", "face_count"]
)
def test_post_preprocess_validation_blocks_silent_remesh_with_same_seeds_and_perimeter(
    tmp_path, changed
):
    plan, path, _ = written_subset(tmp_path)
    assert GeomMesh.validate_cell_subset(plan)["topology_exact"]
    with h5py.File(path, "r+") as h:
        area = h["Geometry/2D Flow Areas/Area"]
        seeds = area["Cells Center Coordinate"][()].copy()
        perimeter = area["Perimeter"][()].copy()
        if changed == "facepoints":
            area["FacePoints Coordinate"][0, 0] += 1e-8
        elif changed == "endpoints":
            area["Faces FacePoint Indexes"][0, 0] = area["Faces FacePoint Indexes"][
                0, 1
            ]
        elif changed == "cell_pairs":
            area["Faces Cell Indexes"][0, 0] = 1
        else:
            values = area["Faces FacePoint Indexes"][()][:-1]
            del area["Faces FacePoint Indexes"]
            area.create_dataset("Faces FacePoint Indexes", data=values)
        assert np.array_equal(seeds, area["Cells Center Coordinate"][()])
        assert np.array_equal(perimeter, area["Perimeter"][()])
    with pytest.raises(RuntimeError, match="changed"):
        GeomMesh.validate_cell_subset(plan)


@pytest.mark.parametrize(
    "changed", ["boundary_order", "cell_incidence", "cell_orientation"]
)
def test_native_save_validation_requires_order_and_reciprocal_cell_faces(
    tmp_path, changed
):
    from ras_commander.geom._cell_subset import _validate_incidence

    _, path, subset = written_subset(tmp_path)
    with h5py.File(path, "r+") as h:
        area = h["Geometry/2D Flow Areas/Area"]
        if changed == "boundary_order":
            info = area["FacePoints Face and Orientation Info"][()]
            point = int(np.flatnonzero(area["FacePoints Is Perimeter"][()] == -1)[0])
            start, count = info[point]
            values = area["FacePoints Face and Orientation Values"]
            values[start : start + count] = values[start : start + count][::-1]
        elif changed == "cell_incidence":
            area["Cells Face and Orientation Values"][0, 0] = (
                len(area["Faces Cell Indexes"]) - 1
            )
        else:
            area["Cells Face and Orientation Values"][0, 1] *= -1
        with pytest.raises(RuntimeError, match="outgoing-first|reciprocal"):
            _validate_incidence(h, "Area", subset)


def test_single_normals_and_curved_face_values_survive_swapped_boundary(tmp_path):
    from ras_commander.geom._cell_subset import _ragged, _write_subset

    source = tmp_path / "Parent.g01.hdf"
    grid(source)
    with h5py.File(source, "r+") as h:
        g = h["Geometry/2D Flow Areas/Area"]
        normals = g["Faces NormalUnitVector and Length"][()].astype("float32")
        del g["Faces NormalUnitVector and Length"]
        g.create_dataset("Faces NormalUnitVector and Length", data=normals)
        pairs = g["Faces Cell Indexes"][()]
        face = int(np.flatnonzero((pairs[:, 0] == 5) & (pairs[:, 1] == 6))[0])
        counts = np.zeros(len(pairs), dtype="int32")
        counts[face] = 2
        g["Faces Perimeter Info"][...] = np.column_stack(
            (np.cumsum(counts) - counts, counts)
        )
        del g["Faces Perimeter Values"]
        values = np.array([[2.1, 1.3], [1.9, 1.7]], dtype="float64")
        g.create_dataset("Faces Perimeter Values", data=values)
        keep = np.zeros(16, dtype=bool)
        keep[6] = True
        sub = _build_subset(g, keep)
    child_face = int(np.flatnonzero(sub.face_src == face)[0])
    assert sub.face_swap[child_face]
    assert sub.tables["Faces NormalUnitVector and Length"].dtype == np.dtype("float32")
    assert np.array_equal(
        sub.tables["Faces NormalUnitVector and Length"][child_face, :2],
        -normals[face, :2],
    )
    assert np.array_equal(
        _ragged(
            sub.tables["Faces Perimeter Info"],
            sub.tables["Faces Perimeter Values"],
            child_face,
        ),
        values[::-1],
    )
    target = tmp_path / "Child.g02.hdf"
    grid(target)
    _write_subset(source, target, "Area", sub, CRS.from_epsg(2278).to_wkt())
    with h5py.File(target) as h:
        g = h["Geometry/2D Flow Areas/Area"]
        assert g["Faces NormalUnitVector and Length"].dtype == np.dtype("float32")
        assert np.array_equal(g["Faces Perimeter Values"][()], values[::-1])


def test_active_global_runtime_is_preserved_without_explicit_project(
    tmp_path, monkeypatch
):
    import importlib
    from types import SimpleNamespace

    import ras_commander._landcover_native as native
    from ras_commander.geom._cell_subset import _resolve_subset_install

    for name in ("Ras.exe", "RasMapperLib.dll"):
        (tmp_path / name).write_bytes(b"runtime fixture")
    active = SimpleNamespace(initialized=True, ras_exe_path=tmp_path / "Ras.exe")
    monkeypatch.setattr(importlib.import_module("ras_commander.RasPrj"), "ras", active)
    monkeypatch.setattr(
        native,
        "find_hecras_install",
        lambda version: pytest.fail("active runtime must not be rediscovered"),
    )
    assert _resolve_subset_install("6.6", None, None) == tmp_path
    with pytest.raises(ValueError, match="conflicts"):
        _resolve_subset_install("6.6", tmp_path / "other", None)


def test_worker_timeout_uses_caller_limit_and_preserves_owned_pair(
    tmp_path, monkeypatch
):
    import subprocess

    plan, source, target = planned(tmp_path)
    before = {p: p.read_bytes() for p in (source, target, Path(str(target) + ".hdf"))}
    _fake_native_runtime(monkeypatch, tmp_path)

    def timeout(argv, **kwargs):
        assert kwargs["timeout"] == 71
        raise subprocess.TimeoutExpired(argv, 71)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="exceeded 71 seconds") as error:
        GeomMesh.apply_cell_subset(plan, timeout=71)
    assert isinstance(error.value.__cause__, subprocess.TimeoutExpired)
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize(
    "name",
    [
        "Cells FacePoint Indexes",
        "FacePoints Cell Index Values",
        "Faces NormalUnitVector and Length",
    ],
)
def test_validation_blocks_corrupt_remaining_native_connectivity_or_normal_tables(
    tmp_path, name
):
    plan, path, _ = written_subset(tmp_path)
    with h5py.File(path, "r+") as h:
        dataset = h["Geometry/2D Flow Areas/Area/" + name]
        if dataset.ndim == 1:
            dataset[0] = 999999
        else:
            dataset[0, 0] = 999999
    with pytest.raises(RuntimeError):
        GeomMesh.validate_cell_subset(plan)


def test_cell_vertex_membership_alone_does_not_accept_crossed_order(tmp_path):
    plan, path, _ = written_subset(tmp_path)
    with h5py.File(path, "r+") as h:
        cells = h["Geometry/2D Flow Areas/Area/Cells FacePoint Indexes"]
        row = cells[0]
        row[[1, 2]] = row[[2, 1]]
        cells[0] = row
    with pytest.raises(RuntimeError, match="vertex order"):
        GeomMesh.validate_cell_subset(plan)


def test_validation_rejects_child_bytes_changed_after_array_read(tmp_path, monkeypatch):
    from ras_commander.geom import _cell_subset as module

    plan, path, _ = written_subset(tmp_path)
    original = module._sha256
    seen = 0

    def race(value):
        nonlocal seen
        if Path(value) == path:
            seen += 1
            if seen == 2:
                with path.open("ab") as stream:
                    stream.write(b"concurrent edit")
        return original(value)

    monkeypatch.setattr(module, "_sha256", race)
    with pytest.raises(RuntimeError, match="child changed during validation"):
        GeomMesh.validate_cell_subset(plan)
