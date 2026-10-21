"""Ring contract for ``HdfMesh.get_mesh_cell_polygons``.

Decision under test: the Python output is the contract and the native engine
must reproduce it byte-for-byte.

    Exterior ring = clockwise.  Begin at the start point of the cell's first
    listed face (``Cells Face and Orientation Values[start, 0]``), traversed in
    the cell's clockwise direction: B->A when the orientation value is +1 (cell
    left of A->B), A->B when it is -1.  Walk the remaining faces around the
    cell including each face's ``Faces Perimeter Values`` in traversal order.
    Drop consecutive duplicate coordinates and close the ring.

The numpy recomputation below reads only the HDF topology arrays, so it pins the
rule independently of GEOS ``polygonize``.  Real fixtures are read-only and
HEC-RAS is never run.  Set ``RAS_FLUVIAL_FIXTURE_DIRS`` (``os.pathsep``-separated
directories) to make ``<fixture>.hdf`` files discoverable.  Native assertions
skip when ``ras_commander_fast_hdf`` is not installed.
"""
from __future__ import annotations

import collections
import importlib.util
import inspect
import os
from pathlib import Path

import h5py
import numpy as np
import pytest
import shapely

from ras_commander.hdf import HdfMesh

_CACHE = Path.home() / ".cache" / "ras-fast-hdf-validation-fixtures"
_SCRATCH = "C:/Users/jacob/scratch/ras-native-successor"
_KNOWN_PATHS = {
    "BaldEagleDamBrk.p07": [_CACHE / "BaldEagleDamBrk.p07.hdf", f"{_SCRATCH}/structures-fixtures/BaldEagleDamBrk.p07.hdf"],
    "Muncie.g02": [f"{_SCRATCH}/wave2-fixtures/Muncie/Muncie.g02.hdf"],
    "DavisStormSystem.p02": [
        "H:/CLB-Repos/ras-commander/working/c05_preparation_2026-08-22/real_fixtures/DavisStormSystem.p02.hdf",
    ],
    "AustinOyster.p01": ["C:/GH/rc-wt-956/working/austin_bayou_firehose/working_model/Input/AustinOyster.p01.hdf"],
    "JUL2020_D100RAS.p04": [f"{_SCRATCH}/structures-fixtures/JUL2020_D100RAS.p04.hdf"],
    "Homewood.p02": ["D:/RAS_Agent_Scratch/Homewood_Demo/HECRAS/Homewood.p02.hdf"],
    "BaldEagleDamBrk.refpts.701.p03": [f"{_SCRATCH}/refpoint-fixtures/BaldEagleDamBrk.refpts.701.p03.hdf"],
}
FIXTURES = list(_KNOWN_PATHS)


def _resolve(name: str) -> Path | None:
    for candidate in _KNOWN_PATHS[name]:
        if Path(candidate).is_file():
            return Path(candidate)
    for directory in filter(None, os.environ.get("RAS_FLUVIAL_FIXTURE_DIRS", "").split(os.pathsep)):
        hits = sorted(Path(directory).rglob(f"{name}.hdf"))
        if hits:
            return hits[0]
    return None


_POLYGONS: dict = {}


def _fixture(name: str) -> Path:
    path = _resolve(name)
    if path is None:
        pytest.skip(f"fixture {name}.hdf not found (set RAS_FLUVIAL_FIXTURE_DIRS)")
    return path


def _python_polygons(name: str):
    if name not in _POLYGONS:
        path = _fixture(name)
        kwargs = {"backend": "python"} if "backend" in inspect.signature(HdfMesh.get_mesh_cell_polygons).parameters else {}
        gdf = HdfMesh.get_mesh_cell_polygons(path, **kwargs)
        assert len(gdf), f"{name}: no polygons"
        _POLYGONS[name] = (path, gdf)
    return _POLYGONS[name]


# --------------------------------------------------------------------------- #
# numpy reference implementation of the ring contract (HDF arrays only)
# --------------------------------------------------------------------------- #
class _Mesh:
    def __init__(self, group: h5py.Group):
        self.cinfo = group["Cells Face and Orientation Info"][()]
        self.cvals = group["Cells Face and Orientation Values"][()]
        self.ends = group["Faces FacePoint Indexes"][()]
        self.pinfo = group["Faces Perimeter Info"][()]
        self.pvals = group["Faces Perimeter Values"][()][:, :2]
        self.fpc = group["FacePoints Coordinate"][()][:, :2]

    def faces(self, cell: int) -> list[int]:
        start, count = (int(v) for v in self.cinfo[cell, :2])
        return [int(f) for f in self.cvals[start:start + count, 0]]

    def orientation0(self, cell: int) -> int:
        return int(self.cvals[int(self.cinfo[cell, 0]), 1])

    def ring(self, cell: int) -> np.ndarray:
        faces = self.faces(cell)
        adj = collections.defaultdict(list)
        for i, f in enumerate(faces):
            adj[int(self.ends[f][0])].append(i)
            adj[int(self.ends[f][1])].append(i)
        f0 = faces[0]
        # +1: cell is LEFT of A->B, so clockwise is B->A; -1: cell is RIGHT, A->B is clockwise.
        point = int(self.ends[f0][1] if self.orientation0(cell) == 1 else self.ends[f0][0])
        visited = [False] * len(faces)
        ring = [tuple(self.fpc[point])]
        for _ in faces:
            i = next(i for i in adj[point] if not visited[i])
            visited[i] = True
            f = faces[i]
            s, n = (int(v) for v in self.pinfo[f])
            segment = [tuple(p) for p in self.pvals[s:s + n]]
            reverse = int(self.ends[f][1]) == point
            ring += segment[::-1] if reverse else segment
            point = int(self.ends[f][0] if reverse else self.ends[f][1])
            ring.append(tuple(self.fpc[point]))
        ring = [p for k, p in enumerate(ring) if k == 0 or p != ring[k - 1]]
        return np.array(ring)


def _expected_rings(path: Path, cells) -> list[np.ndarray]:
    meshes: dict[str, _Mesh] = {}
    out = []
    with h5py.File(path, "r") as hdf:
        for mesh, cell in zip(cells.mesh_name, cells.cell_id):
            if mesh not in meshes:
                meshes[mesh] = _Mesh(hdf[f"Geometry/2D Flow Areas/{mesh}"])
            out.append(meshes[mesh].ring(int(cell)))
    return out


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", FIXTURES)
def test_every_ring_equals_numpy_recomputation_from_hdf_arrays(name):
    """The documented closed-form rule reproduces backend='python' byte-exactly for every cell."""
    path, gdf = _python_polygons(name)
    expected = _expected_rings(path, gdf)
    mismatches = [
        (m, int(c)) for m, c, g, e in zip(gdf.mesh_name, gdf.cell_id, gdf.geometry, expected)
        if not np.array_equal(np.asarray(g.exterior.coords)[:, :2], e)
    ]
    assert not mismatches, f"{name}: {len(mismatches)} of {len(gdf)} rings differ from the rule, e.g. {mismatches[:5]}"


@pytest.mark.parametrize("name", FIXTURES)
def test_all_exterior_rings_are_clockwise(name):
    _, gdf = _python_polygons(name)
    ccw = shapely.is_ccw(shapely.get_exterior_ring(gdf.geometry.values))
    assert not ccw.any(), f"{name}: {int(ccw.sum())} of {len(gdf)} exterior rings are CCW"
    assert not shapely.get_num_interior_rings(gdf.geometry.values).any(), f"{name}: unexpected interior rings"


@pytest.mark.parametrize("name", FIXTURES)
def test_ring_starts_at_the_first_listed_face_in_the_clockwise_direction(name):
    """Start vertex = B end of face 0 when orientation is +1 (cell left of A->B), else the A end."""
    path, gdf = _python_polygons(name)
    meshes: dict[str, _Mesh] = {}
    wrong = []
    with h5py.File(path, "r") as hdf:
        for mesh, cell, geom in zip(gdf.mesh_name, gdf.cell_id, gdf.geometry):
            if mesh not in meshes:
                meshes[mesh] = _Mesh(hdf[f"Geometry/2D Flow Areas/{mesh}"])
            m = meshes[mesh]
            f0 = m.faces(int(cell))[0]
            end = m.ends[f0][1] if m.orientation0(int(cell)) == 1 else m.ends[f0][0]
            if tuple(np.asarray(geom.exterior.coords)[0, :2]) != tuple(m.fpc[end]):
                wrong.append((mesh, int(cell)))
    assert not wrong, f"{name}: {len(wrong)} rings start away from the first listed face, e.g. {wrong[:5]}"


@pytest.mark.parametrize("name", FIXTURES)
def test_cell_set_is_exactly_cells_with_three_or_more_faces_minus_diagnosed(name):
    path, gdf = _python_polygons(name)
    diagnostics = gdf.attrs.get("cell_polygon_diagnostics", ())
    omitted = {(d["mesh_name"], d["cell_id"]) for d in diagnostics if d["status"] in ("omitted",)}
    expected = set()
    with h5py.File(path, "r") as hdf:
        for mesh in sorted(set(gdf.mesh_name)):
            info = hdf[f"Geometry/2D Flow Areas/{mesh}/Cells Face and Orientation Info"][()]
            expected |= {(mesh, i) for i, count in enumerate(info[:, 1]) if int(count) >= 3}
    got = set(zip(gdf.mesh_name, (int(c) for c in gdf.cell_id)))
    assert got == expected - omitted, (
        f"{name}: only-in-output={sorted(got - (expected - omitted))[:5]} "
        f"missing={sorted((expected - omitted) - got)[:5]}"
    )
    for d in diagnostics:  # <3 faces are reported, never silently dropped
        if d["status"] == "boundary_only":
            assert (d["mesh_name"], d["cell_id"]) not in got


@pytest.mark.parametrize("name", FIXTURES)
def test_curved_perimeter_vertices_are_kept_in_the_ring(name):
    """Faces Perimeter Values (curved perimeter faces) must appear in the ring, in traversal order."""
    path, gdf = _python_polygons(name)
    curved = 0
    with h5py.File(path, "r") as hdf:
        meshes: dict[str, _Mesh] = {}
        for mesh, cell, geom in zip(gdf.mesh_name, gdf.cell_id, gdf.geometry):
            if mesh not in meshes:
                meshes[mesh] = _Mesh(hdf[f"Geometry/2D Flow Areas/{mesh}"])
            m = meshes[mesh]
            n_perimeter = sum(int(m.pinfo[f][1]) for f in m.faces(int(cell)))
            if n_perimeter:
                curved += 1
                ring = {tuple(p) for p in np.asarray(geom.exterior.coords)[:, :2]}
                assert all(tuple(p) in ring for f in m.faces(int(cell))
                           for p in m.pvals[int(m.pinfo[f][0]):int(m.pinfo[f][0]) + int(m.pinfo[f][1])])
    if curved == 0:
        pytest.skip(f"{name}: no cell has curved-perimeter faces")


# --------------------------------------------------------------------------- #
# Native engine must reproduce the Python contract exactly
# --------------------------------------------------------------------------- #
def _native_unavailable_reason() -> str | None:
    if importlib.util.find_spec("ras_commander_fast_hdf") is None:
        return "ras_commander_fast_hdf is not installed"
    if "backend" not in inspect.signature(HdfMesh.get_mesh_cell_polygons).parameters:
        return "HdfMesh.get_mesh_cell_polygons has no backend= switch on this checkout"
    return None


@pytest.fixture(params=FIXTURES)
def native_and_python(request):
    reason = _native_unavailable_reason()
    if reason:
        pytest.skip(reason)
    path, py = _python_polygons(request.param)
    native = HdfMesh.get_mesh_cell_polygons(path, backend="native")
    return request.param, path, py, native


def test_native_rings_are_byte_identical_to_python(native_and_python):
    name, _, py, native = native_and_python
    assert shapely.to_wkb(native.geometry.values).tolist() == shapely.to_wkb(py.geometry.values).tolist(), name


def test_native_rings_are_clockwise_and_match_numpy_rule(native_and_python):
    name, path, _, native = native_and_python
    assert not shapely.is_ccw(shapely.get_exterior_ring(native.geometry.values)).any(), name
    expected = _expected_rings(path, native)
    bad = [i for i, (g, e) in enumerate(zip(native.geometry, expected))
           if not np.array_equal(np.asarray(g.exterior.coords)[:, :2], e)]
    assert not bad, f"{name}: {len(bad)} native rings differ from the rule"


def test_native_cell_sets_and_diagnostics_equal_python(native_and_python):
    name, _, py, native = native_and_python
    assert list(zip(native.mesh_name, native.cell_id)) == list(zip(py.mesh_name, py.cell_id)), name
    assert native.attrs.get("cell_polygon_diagnostics") == py.attrs.get("cell_polygon_diagnostics"), name
