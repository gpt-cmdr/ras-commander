"""Pin the documented fluvial/pluvial seeding, tie and shared-edge rules.

Order invariance itself is covered by test_fluvial_pluvial_order_invariance.py.
These tests pin the rules the fix chose: a cell in competing boundary pairs is
seeded ``ambiguous``; equal times seed nothing; every shared piece is kept
(MultiLineString when not contiguous); with stored topology, boundary lines
are the stored faces. Synthetic controls use an HDF without mesh topology,
which exercises the order-invariant shared-ring-segment fallback. The
topology check is opt-in: set ``RAS_FLUVIAL_REAL_HDF`` to a computed,
read-only DavisStormSystem p02 plan HDF.
"""
import inspect
import os
from pathlib import Path

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import LineString, MultiLineString, Polygon, box

from ras_commander.hdf import HdfFluvialPluvial, HdfMesh, HdfResultsMesh

T0 = pd.Timestamp("2000-01-01")

# These tests pin the reference implementation. Where the public methods take
# ``engine=`` (default "auto", which may run the native kernels), select it.
REFERENCE = ({"engine": "h5py"} if "engine" in inspect.signature(
    HdfFluvialPluvial.generate_fluvial_pluvial_polygons).parameters else {})


@pytest.fixture
def empty_hdf(tmp_path):
    path = tmp_path / "synthetic.p01.hdf"
    with h5py.File(path, "w"):
        pass
    return path


def _patch(monkeypatch, cells, results):
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda *a, **k: cells.copy())
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", lambda *a, **k: results.copy())


def _row(n_cells, hours, mesh="mesh", crs=2271):
    cells = gpd.GeoDataFrame(
        {"mesh_name": [mesh] * n_cells, "cell_id": list(range(n_cells))},
        geometry=[box(100 * i, 0, 100 * (i + 1), 100) for i in range(n_cells)], crs=crs)
    results = pd.DataFrame({
        "mesh_name": [mesh] * n_cells, "cell_id": list(range(n_cells)),
        "maximum_water_surface_time": [T0 + pd.Timedelta(hours=h) for h in hours]})
    return cells, results


def _classes(out):
    return {(row.mesh_name, row.classification): row.geometry for row in out.itertuples()}


def _variants(cells):
    rotated = []
    for g in cells.geometry:
        c = list(g.exterior.coords)[:-1]
        rotated.append(Polygon(c[2:] + c[:2]))
    return {
        "rows_reversed": cells.iloc[::-1].reset_index(drop=True),
        "rows_shuffled": cells.sample(frac=1.0, random_state=3).reset_index(drop=True),
        "rings_reversed": cells.assign(geometry=shapely.reverse(cells.geometry.values)),
        "rings_rotated": cells.assign(geometry=rotated),
    }


def _assert_identical(ref, other):
    a, b = _classes(ref), _classes(other)
    assert set(a) == set(b)
    for key in a:
        assert a[key].equals(b[key]), key
        assert a[key].area == b[key].area, key
    assert list(ref.cell_id) == list(other.cell_id)


def _assert_same_lines(ref, other):
    norm = lambda gdf: sorted((shapely.normalize(g) for g in gdf.geometry), key=lambda g: g.wkb)
    a, b = norm(ref), norm(other)
    assert len(a) == len(b)
    assert all(x.equals_exact(y, 0.0) for x, y in zip(a, b))


def test_cell_in_competing_pairs_is_seeded_ambiguous(empty_hdf, monkeypatch):
    # Cell 1 peaks 2 h after cell 0 (fluvial evidence) and 2 h before cell 2
    # (pluvial evidence). The documented rule seeds it ambiguous, whatever the order.
    cells, results = _row(3, [0, 2, 4])
    for frame in [cells] + list(_variants(cells).values()):
        _patch(monkeypatch, frame, results)
        out = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
            empty_hdf, delta_t=1, temporal_tolerance_hours=0.5, **REFERENCE)
        classes = _classes(out)
        assert classes[("mesh", "pluvial")].equals(cells.geometry[0])
        assert classes[("mesh", "ambiguous")].equals(cells.geometry[1])
        assert classes[("mesh", "fluvial")].equals(cells.geometry[2])


def test_seed_rule_is_independent_of_pair_order():
    times = {("m", i): T0 + pd.Timedelta(hours=h) for i, h in enumerate([0, 2, 4, 9])}
    pairs = [(("m", 0), ("m", 1)), (("m", 1), ("m", 2)), (("m", 2), ("m", 3))]
    expected = {("m", 0): "pluvial", ("m", 1): "ambiguous", ("m", 2): "ambiguous", ("m", 3): "fluvial"}
    assert HdfFluvialPluvial._seed_classifications(pairs, times) == expected
    assert HdfFluvialPluvial._seed_classifications(pairs[::-1], times) == expected


def test_equal_times_with_zero_delta_t_seed_nothing(empty_hdf, monkeypatch):
    cells, results = _row(2, [3, 3])
    _patch(monkeypatch, cells, results)
    out = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(empty_hdf, delta_t=0, **REFERENCE)
    assert set(out.classification) == {"ambiguous"}
    lines = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(empty_hdf, delta_t=0, **REFERENCE)
    assert len(lines) == 1


def test_curved_shared_face_keeps_every_segment(empty_hdf, monkeypatch):
    shared = [(100, 0), (110, 30), (90, 60), (100, 100)]
    left = Polygon([(0, 0)] + shared + [(0, 100)])
    right = Polygon([(200, 0), (200, 100)] + shared[::-1])
    cells = gpd.GeoDataFrame({"mesh_name": ["m", "m"], "cell_id": [0, 1]}, geometry=[left, right], crs=2271)
    results = pd.DataFrame({"mesh_name": ["m", "m"], "cell_id": [0, 1],
                            "maximum_water_surface_time": [T0, T0 + pd.Timedelta(hours=5)]})
    expected = LineString(shared)
    for frame in [cells] + list(_variants(cells).values()):
        _patch(monkeypatch, frame, results)
        lines = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(empty_hdf, delta_t=1, **REFERENCE)
        assert len(lines) == 1
        assert lines.geometry.iloc[0].equals(expected)
        assert lines.geometry.iloc[0].length == pytest.approx(expected.length)


def test_noncontiguous_shared_pieces_are_all_kept():
    pieces = [((0.0, 0.0), (1.0, 0.0)), ((5.0, 0.0), (6.0, 0.0))]
    merged = HdfFluvialPluvial._merge_shared_pieces(pieces[::-1])
    assert isinstance(merged, MultiLineString)
    assert merged.equals(MultiLineString([list(p) for p in pieces]))


def test_synthetic_grid_is_order_invariant(empty_hdf, monkeypatch):
    rng = np.random.default_rng(11)
    n = 12
    geoms, ids, hours = [], [], []
    for j in range(n):
        for i in range(n):
            geoms.append(box(i, j, i + 1, j + 1))
            ids.append(j * n + i)
            hours.append(float(rng.choice([0, 1, 2, 6, 7, 8, 14])))
    cells = gpd.GeoDataFrame({"mesh_name": "m", "cell_id": ids}, geometry=geoms, crs=2271)
    results = pd.DataFrame({"mesh_name": "m", "cell_id": ids,
                            "maximum_water_surface_time": [T0 + pd.Timedelta(hours=h) for h in hours]})
    for delta_t in (1, 4):
        _patch(monkeypatch, cells, results)
        ref = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(empty_hdf, delta_t=delta_t, **REFERENCE)
        ref_lines = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(empty_hdf, delta_t=delta_t, **REFERENCE)
        assert not ref.empty and not ref_lines.empty
        for frame in _variants(cells).values():
            _patch(monkeypatch, frame, results)
            _assert_identical(ref, HdfFluvialPluvial.generate_fluvial_pluvial_polygons(empty_hdf, delta_t=delta_t, **REFERENCE))
            _assert_same_lines(ref_lines, HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(empty_hdf, delta_t=delta_t, **REFERENCE))


def _real(env):
    filename = os.environ.get(env)
    if not filename:
        pytest.skip(f"Set {env} to a computed plan HDF (read-only)")
    path = Path(filename)
    assert path.is_file()
    return path, HdfMesh.get_mesh_cell_polygons(path), HdfResultsMesh.get_mesh_max_ws(path)


def test_real_topology_boundary_lines_are_stored_faces():
    path, cells, results = _real("RAS_FLUVIAL_REAL_HDF")
    faces = HdfMesh.get_mesh_cell_faces(path)
    stored = {(m, int(f)): g for m, f, g in zip(faces.mesh_name, faces.face_id, faces.geometry)}
    present = set(zip(cells.mesh_name, cells.cell_id))
    times = results.set_index(["mesh_name", "cell_id"])["maximum_water_surface_time"].map(pd.Timestamp).to_dict()
    expected = {}
    with h5py.File(path, "r") as hdf:
        for mesh in sorted(cells.mesh_name.unique()):
            face_cells = hdf[f"Geometry/2D Flow Areas/{mesh}/Faces Cell Indexes"][()]
            for face_id, (a, b) in enumerate(face_cells[:, :2].tolist()):
                ka, kb = (mesh, a), (mesh, b)
                if a == b or ka not in present or kb not in present:
                    continue
                if abs((times[ka] - times[kb]).total_seconds()) >= 12 * 3600:
                    expected.setdefault(tuple(sorted((ka, kb))), []).append(stored[(mesh, face_id)])
    lines = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(path, delta_t=12, **REFERENCE)
    assert len(lines) == len(expected) > 0
    for line, (_, pieces) in zip(lines.geometry, sorted(expected.items())):
        assert line.equals(shapely.union_all(pieces))
