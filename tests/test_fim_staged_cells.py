"""Staged cell subsets: closure helper and subset profile staging."""

import json

import h5py
import numpy as np
import pytest

from ras_commander.fim import _sloping

NX, NY = 6, 4


def _grid_mesh(root):
    """Quad mesh in binary sloping layout; ghosts follow physical cells."""
    v = lambda i, j: j * (NX + 1) + i  # noqa: E731
    c = lambda i, j: j * NX + i  # noqa: E731
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
