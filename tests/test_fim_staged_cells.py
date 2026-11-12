"""Staged cell subsets: closure helper and subset profile staging."""

import json

import h5py
import numpy as np
import pytest

from ras_commander.fim import _sloping

NX, NY = 6, 4


def _grid_mesh(root):
    """Quad mesh in binary sloping layout; ghosts follow physical cells."""
    v = lambda i, j: j * (NX + 1) + i
    c = lambda i, j: j * NX + i
    face_cells, face_vertices, cell_faces = [], [], [[] for _ in range(NX * NY)]
    ghosts = NX * NY
    horizontal = {}
    vertical = {}

    def add(left, right, ends):
        nonlocal ghosts
        if right is None:
            right = ghosts
            ghosts += 1
            cell_faces.append([len(face_cells)])
        face_cells.append([left, right])
        face_vertices.append(ends)
        return len(face_cells) - 1

    for j in range(NY + 1):
        for i in range(NX):
            p, q = v(i, j), v(i + 1, j)
            horizontal[i, j] = (add(c(i, 0), None, [p, q]) if j == 0 else
                                add(c(i, NY - 1), None, [q, p]) if j == NY else
                                add(c(i, j), c(i, j - 1), [p, q]))
    for i in range(NX + 1):
        for j in range(NY):
            p, q = v(i, j), v(i, j + 1)
            vertical[i, j] = (add(c(0, j), None, [q, p]) if i == 0 else
                              add(c(NX - 1, j), None, [p, q]) if i == NX else
                              add(c(i - 1, j), c(i, j), [p, q]))
    for j in range(NY):
        for i in range(NX):
            cell_faces[c(i, j)] = [horizontal[i, j], vertical[i + 1, j],
                                   horizontal[i, j + 1], vertical[i, j]]
    vertex_faces = []
    for j in range(NY + 1):
        for i in range(NX + 1):
            ring = []
            if i < NX:
                ring.append(horizontal[i, j])
            if j < NY:
                ring.append(vertical[i, j])
            if i > 0:
                ring.append(horizontal[i - 1, j])
            if j > 0:
                ring.append(vertical[i, j - 1])
            vertex_faces.append(ring)

    def csr(rows):
        info, values = [], []
        for row in rows:
            info.append([len(values), len(row)])
            values.extend([f, -1] for f in row)
        return info, values

    arrays = {}
    for key, rows in [("cell", cell_faces), ("vertex", vertex_faces)]:
        info, values = csr(rows)
        arrays[f"{key}_info"] = info
        arrays[f"{key}_faces"] = values
    arrays["face_cells"] = face_cells
    arrays["face_vertices"] = face_vertices
    descriptors = {}
    for key, rows in arrays.items():
        np.asarray(rows, dtype="<i4").reshape(-1, 2).tofile(root / f"{key}.bin")
        descriptors[key] = dict(path=f"{key}.bin", rows=len(rows))
    header = root / "mesh-0.json"
    header.write_text(json.dumps(dict(schema="ras-commander-sloping-mesh/1", arrays=descriptors)))
    return header, cell_faces, face_cells, face_vertices, vertex_faces, ghosts


def test_closure_matches_brute_force_and_isolates_unowned_mesh(tmp_path):
    header, cell_faces, face_cells, face_vertices, vertex_faces, total = _grid_mesh(tmp_path)
    owners = [1 * NX + 2, 1 * NX + 3, 2 * NX + 2, 0]
    expected = set()
    for cell in owners:
        for face in cell_faces[cell]:
            for vertex in face_vertices[face]:
                for ring_face in vertex_faces[vertex]:
                    expected.update(face_cells[ring_face])
    subsets = _sloping.staged_cell_subsets(
        [header, header], [[0, c] for c in reversed(owners)] + [[0, owners[0]]]
    )
    assert subsets[0].dtype == np.dtype("<u4")
    assert subsets[0].tolist() == sorted(expected)
    assert len(expected) < total
    # Corner cell 0 pulls in its ghost cells; a mesh without owners stages one cell.
    assert any(c >= NX * NY for c in subsets[0])
    assert subsets[1].tolist() == [0]
    paths = _sloping.write_staged_cells(tmp_path, subsets)
    assert np.fromfile(paths[0], dtype="<u4").tolist() == sorted(expected)


def test_stage_profiles_writes_subset_values_and_checks_complete_rows(tmp_path):
    hdf = tmp_path / "plan.hdf"
    with h5py.File(hdf, "w") as handle:
        handle["x"] = np.zeros(1)
    values = np.arange(10, dtype="<f4") * 1.5
    meshes = [dict(mesh_name="A", cell_count=10)]
    subset = np.array([1, 4, 5, 9])
    units, _, staged = _sloping._stage_profiles(
        hdf, tmp_path, meshes, [values], {"Max": "Max"}, chunk_bytes=12,
        cell_subsets=[subset], max_staged_bytes=16,
    )
    written = np.fromfile(tmp_path / units[0]["values_files"][0], dtype="<f4")
    assert written.tobytes() == values[subset].tobytes()
    assert staged == 16
    with pytest.raises(Exception, match="max_prepared_mib"):
        _sloping._stage_profiles(hdf, tmp_path / "x", meshes, [values], {"Max": "Max"},
                                 cell_subsets=[subset], max_staged_bytes=15)
    bad = values.copy()
    bad[7] = np.nan  # outside the subset: the complete row is still validated
    (tmp_path / "bad").mkdir()
    with pytest.raises(ValueError, match="Invalid complete cell profile"):
        _sloping._stage_profiles(hdf, tmp_path / "bad", meshes, [bad], {"Max": "Max"},
                                 cell_subsets=[subset])
    for invalid in ([np.array([3, 3])], [np.array([10])], [np.array([], dtype=int)], []):
        with pytest.raises(ValueError, match="cell_subsets"):
            _sloping._stage_profiles(hdf, tmp_path, meshes, [values], {"Max": "Max"},
                                     cell_subsets=invalid)


def test_capability_helper_names_the_one_contract():
    capable = {"depth_groups": {"staged_cells": _sloping.STAGED_CELLS_METHOD},
               "sloping": {"staged_cells": _sloping.STAGED_CELLS_METHOD},
               "sloping_native_grid": {"staged_cells": _sloping.STAGED_CELLS_METHOD}}
    assert _sloping.staged_cells_supported(capable)
    assert _sloping.staged_cells_supported(capable, "sloping")
    assert not _sloping.staged_cells_supported(capable, "sloping_native_grid")
    assert not _sloping.staged_cells_supported({"depth_groups": {}})
    assert not _sloping.staged_cells_supported({"depth_groups": {"staged_cells": "other/1"}})
    assert not _sloping.staged_cells_supported(None)


@pytest.mark.parametrize("chunk_bytes", [4 * 7, 8 * 1024 * 1024])
def test_stage_profiles_from_hdf_rows_writes_exact_subset_bytes(tmp_path, monkeypatch, chunk_bytes):
    """Stored timesteps through the native HDF reader, subset slices crossing chunks."""
    pytest.importorskip("ras_commander_fast_hdf")
    from types import SimpleNamespace

    from ras_commander import HdfResultsMesh

    cells, times = 53, 9
    data = (np.arange(times * cells, dtype="<f4").reshape(times, cells) * 0.25 + 100).astype("<f4")
    hdf = tmp_path / "plan.hdf"
    with h5py.File(hdf, "w") as handle:
        handle.create_dataset("R/WS", data=data, chunks=(1, cells), compression="gzip",
                              compression_opts=4)

    class View:
        def select(self, time):
            return SimpleNamespace(shape=(1, cells), dataset_path="R/WS")

    monkeypatch.setattr(HdfResultsMesh, "get_mesh_timeseries", lambda *a, **k: View())
    meshes = [dict(mesh_name="A", cell_count=cells)]
    subset = np.array([0, 3, 6, 7, 13, 14, 20, 27, 34, 40, 41, 52])
    selected = {"s0": 2, "s1": 3, "s2": 4, "s3": 8, "s4": 3}
    full_root, sub_root = tmp_path / "full", tmp_path / "sub"
    full_root.mkdir()
    sub_root.mkdir()
    full, _, full_bytes = _sloping._stage_profiles(hdf, full_root, meshes, [None], selected,
                                                   deduplicate=True, chunk_bytes=chunk_bytes)
    sub, _, sub_bytes = _sloping._stage_profiles(hdf, sub_root, meshes, [None], selected,
                                                 deduplicate=True, chunk_bytes=chunk_bytes,
                                                 cell_subsets=[subset])
    assert [u["id"] for u in sub] == [u["id"] for u in full] == list(selected)
    assert full_bytes == 4 * cells * 4 and sub_bytes == 4 * len(subset) * 4
    for unit, (name, time) in zip(sub, selected.items(), strict=True):
        written = (sub_root / unit["values_files"][0]).read_bytes()
        assert written == data[time, subset].tobytes(), name
        complete = np.fromfile(full_root / next(u for u in full if u["id"] == name)["values_files"][0],
                               dtype="<f4")
        assert written == complete[subset].tobytes()


def _full_mesh(root):
    """The topology of :func:`_grid_mesh` plus coordinates, minima and polylines."""
    header, cell_faces, face_cells, face_vertices, _, total = _grid_mesh(root)
    physical = NX * NY
    vertices = np.array([[i * 4.0, j * 4.0] for j in range(NY + 1) for i in range(NX + 1)])
    centers = np.zeros((total, 2))
    for k in range(physical):
        i, j = k % NX, k // NX
        centers[k] = [i * 4.0 + 2, j * 4.0 + 2]
    for g in range(physical, total):
        f = cell_faces[g][0]
        a, b = vertices[face_vertices[f][0]], vertices[face_vertices[f][1]]
        mid = (a + b) / 2
        centers[g] = 2 * mid - centers[face_cells[f][0]]
    terrain = lambda x, y: 0.1 * x + 0.05 * y
    minima = np.array([terrain(*centers[k]) - 0.6 for k in range(physical)], dtype="<f4")
    face_minima = np.array([minima[a] + 0.1 for a, _ in face_cells], dtype="<f4")
    arrays = json.loads(header.read_text())["arrays"]

    def put(key, values, dtype, columns):
        array = np.ascontiguousarray(values, dtype=dtype).reshape(-1, columns)
        array.tofile(root / f"{key}.bin")
        arrays[key] = dict(path=f"{key}.bin", rows=len(array))

    put("centers", centers, "<f8", 2)
    put("cell_minimum", minima, "<f4", 1)
    put("face_info", np.zeros((len(face_cells), 2)), "<i4", 2)
    put("face_points", np.empty((0, 2)), "<f8", 2)
    put("face_minimum", face_minima, "<f4", 1)
    put("vertices", vertices, "<f8", 2)
    header.write_text(json.dumps(dict(schema="ras-commander-sloping-mesh/1", arrays=arrays)))
    return header, total, terrain


def _engine_with_staged_cells():
    import os
    import subprocess

    from ras_commander.fim import RasFim

    try:
        engine = os.environ.get("RAS_COMMANDER_FIM_ENGINE") or RasFim.get_engine_info()["engine_path"]
        method = json.loads(subprocess.run([engine, "method"], capture_output=True, check=True).stdout)
    except Exception as exc:  # noqa: BLE001 - engine-gated test
        pytest.skip(f"Fast-Map engine unavailable: {exc}")
    if not _sloping.staged_cells_supported(method, "sloping"):
        pytest.skip("engine lacks ras-commander-staged-cells/1")
    return engine


@pytest.mark.parametrize("owner_box", [(0, 2, 0, 2), (2, 5, 1, 3)], ids=["perimeter", "interior"])
def test_engine_renders_commander_subset_with_complete_mesh_bits(tmp_path, owner_box):
    import subprocess

    import rasterio
    from affine import Affine
    from shapely.geometry import box

    from ras_commander.fim._horizontal_engine import _write_geometry

    engine = _engine_with_staged_cells()
    header, total, terrain = _full_mesh(tmp_path)
    width, height = NX * 4, NY * 4
    with rasterio.open(tmp_path / "terrain.tif", "w", driver="GTiff", width=width, height=height,
                       count=1, dtype="float32", nodata=-9999, crs="EPSG:3857",
                       transform=Affine(1, 0, 0, 0, -1, height)) as ds:
        ys, xs = np.mgrid[0:height, 0:width]
        ds.write(terrain(xs + 0.5, height - ys - 0.5).astype("float32"), 1)
    i0, i1, j0, j1 = owner_box
    owners = [j * NX + i for j in range(j0, j1) for i in range(i0, i1)]
    _write_geometry(tmp_path / "owners.wkb",
                    [box(i * 4.0, j * 4.0, i * 4.0 + 4, j * 4.0 + 4) for j in range(j0, j1)
                     for i in range(i0, i1)])
    minima = np.fromfile(tmp_path / "cell_minimum.bin", dtype="<f4")
    physical = NX * NY
    wse = np.concatenate([minima + 1.0 + 0.4 * np.sin(np.arange(physical)),
                          np.zeros(total - physical, dtype="<f4")]).astype("<f4")
    face_cells = np.fromfile(tmp_path / "face_cells.bin", dtype="<i4").reshape(-1, 2)
    for f, (a, g) in enumerate(face_cells):
        if g >= physical:
            wse[g] = wse[a]
    hdf = tmp_path / "plan.hdf"
    with h5py.File(hdf, "w") as handle:
        handle["x"] = np.zeros(1)
    meshes = [dict(mesh_name="A", cell_count=total)]
    subsets = _sloping.staged_cell_subsets([header], [[0, c] for c in owners])
    assert (subsets[0] >= physical).any() == (owner_box[0] == 0)
    outputs = {}
    for name, cells in [("full", None), ("staged", subsets)]:
        root = tmp_path / name
        root.mkdir()
        units, _, _ = _sloping._stage_profiles(hdf, root, meshes, [wse], {"p": "Max"},
                                               cell_subsets=cells)
        request = dict(
            schema="ras-commander-sloping-request/1", terrain=str(tmp_path / "terrain.tif"),
            epsg=3857, crs_identity=dict(kind="epsg"), terrain_transform=[0, 1, 0, height, 0, -1],
            window=[0, 0, width, height], geometry_file=str(tmp_path / "owners.wkb"),
            mesh_files=[str(header)], owner_cells=[[0, c] for c in owners],
            profiles=[dict(id="p", values_files=[str(root / units[0]["values_files"][0])])],
            threads=2, max_working_bytes=512 << 20, window_cache_bytes=0,
        )
        if cells is not None:
            request["staged_cells_files"] = _sloping.write_staged_cells(root, cells)
        (root / "request.json").write_text(json.dumps(request))
        subprocess.run([engine, "sloping", str(root / "request.json"), str(root / "out")],
                       check=True, capture_output=True)
        outputs[name] = [(root / "out" / "p" / f).read_bytes() for f in ("depth.bin", "wse.bin")]
    depth = np.frombuffer(outputs["full"][0], dtype="<f4")
    assert ((depth > 0) & (depth < 1e4)).any()
    assert outputs["full"] == outputs["staged"]
