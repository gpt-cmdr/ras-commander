"""Native policy regressions; real-model conformance is qualification.py."""
from functools import wraps

import numpy as np
import pytest


@pytest.fixture
def native():
    import ras_commander_fast_hdf as module
    assert module.API_VERSION == 1
    return module


def topology(invalid=False):
    points = [[0, 0], [1, 0], [1, 1], [0, 1]]
    if invalid:
        points = [[0, 0], [1, 1], [0, 1], [1, 0]]
    return [np.array(points, dtype='f8'), np.array([[0, 1], [1, 2], [2, 3], [3, 0]], dtype='i8'),
            np.zeros((4, 2), dtype='i8'), np.empty((0, 2), dtype='f8'),
            np.array([[0, 4]], dtype='i8'), np.array([[0, 1], [1, -1], [2, 1], [3, -1]], dtype='i8')]


def test_legacy_shape_and_thread_determinism(native):
    args = topology()
    saved = [a.copy() for a in args]
    assert len(native.assemble_cells(*args)) == 3
    for threads in (1, 2, 4):
        coordinates, offsets, ids, diagnostics = native.assemble_cells(
            *args, threads=threads, strict=False, return_diagnostics=True)
        np.testing.assert_array_equal(ids, [0])
        np.testing.assert_array_equal(offsets, [0, 5])
        assert diagnostics == []
        for actual, original in zip(args, saved):
            np.testing.assert_array_equal(actual, original)


def test_all_invalid_and_strict_failure(native):
    args = topology(invalid=True)
    for threads in (1, 2, 4):
        coordinates, offsets, ids, diagnostics = native.assemble_cells(
            *args, threads=threads, strict=False, return_diagnostics=True)
        assert coordinates.shape == (0, 2) and len(ids) == 0
        np.testing.assert_array_equal(offsets, [0])
        assert len(diagnostics) == 1 and diagnostics[0][0] == 0
        assert diagnostics[0][1] and 'intersection' in diagnostics[0][2]
    for kwargs in ({}, {'strict': True}):
        with pytest.raises(native.TopologyError, match='cell 0'):
            native.assemble_cells(*args, **kwargs)


@pytest.mark.parametrize('damage', ['offset', 'count', 'face', 'endpoint', 'perimeter', 'nan', 'columns'])
def test_corruption_is_always_fatal_even_after_invalid_ring(native, damage):
    args = topology(invalid=True)
    # Put a corrupt late record after geometry that non-strict may omit.
    args[4] = np.array([[0, 4], [0, 4]], dtype='i8')
    if damage == 'offset':
        args[4][1, 0] = np.iinfo('i8').max
    elif damage == 'count':
        args[4][1, 1] = -1
    elif damage == 'face':
        args[5] = np.concatenate([args[5], [[99, 1]]])
        args[4][1] = [4, 1]
    elif damage == 'endpoint':
        args[1][3, 1] = 99
    elif damage == 'perimeter':
        args[2][3] = [0, 1]
    elif damage == 'nan':
        args[0][0, 0] = np.nan
    else:
        args[4] = args[4][:, :1].copy()
    with pytest.raises(native.TopologyError):
        native.assemble_cells(*args, strict=False, return_diagnostics=True)


def test_empty_and_ghosts(native):
    args = topology()
    args[4] = np.empty((0, 2), dtype='i8')
    assert native.assemble_cells(*args, strict=False, return_diagnostics=True)[2].size == 0
    args[4] = np.array([[0, 0], [0, 1], [0, 4]], dtype='i8')
    result = native.assemble_cells(*args, strict=False, return_diagnostics=True)
    np.testing.assert_array_equal(result[2], [2])
    # Ghosts/empty records are expected non-polygons, never invalid rings.
    assert result[3] == []


def test_curved_reversed_faces_preserve_samples(native):
    args = topology()
    args[1][0] = [1, 0]
    args[2][0] = [0, 1]
    args[3] = np.array([[0.5, -0.2]], dtype='f8')
    coords, offsets, ids = native.assemble_cells(*args)
    assert any(np.array_equal(p, [0.5, -0.2]) for p in coords)
    assert len(coords) == 6 and ids.tolist() == [0]


def test_disconnected_topology_remains_fatal(native):
    args = topology()
    args[5][3, 0] = 2
    with pytest.raises(native.TopologyError):
        native.assemble_cells(*args, strict=False)


def write_hdf(path, corrupt_late=False):
    import h5py
    from pyproj import CRS
    args = topology(invalid=True)
    if corrupt_late:
        args[4] = np.array([[0, 4], [99999, 4]], dtype='i8')
    names = ('FacePoints Coordinate', 'Faces FacePoint Indexes', 'Faces Perimeter Info',
             'Faces Perimeter Values', 'Cells Face and Orientation Info',
             'Cells Face and Orientation Values')
    with h5py.File(path, 'w') as hdf:
        hdf.attrs['Projection'] = CRS.from_epsg(26915).to_wkt()
        attributes = np.zeros(1, dtype=[('Name', 'S64')])
        attributes['Name'] = b'Native Quarantine'
        hdf['Geometry/2D Flow Areas/Attributes'] = attributes
        for name, values in zip(names, args):
            hdf[f'Geometry/2D Flow Areas/Native Quarantine/{name}'] = values
    return path


@pytest.mark.parametrize('backend', ['rust', 'auto'])
def test_adapter_all_invalid_diagnostics_and_strict_identity(native, tmp_path, monkeypatch, backend):
    from ras_commander.hdf.HdfMesh import HdfMesh, MeshCellPolygonError
    import shapely.ops
    def forbidden(*args, **kwargs):
        raise AssertionError('native operation fell back to Python polygonize')
    monkeypatch.setattr(shapely.ops, 'polygonize', forbidden)
    calls = []
    original = native.assemble_cells
    @wraps(original)
    def counted(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(native, 'assemble_cells', counted)
    path = write_hdf(tmp_path / 'invalid.g01.hdf')
    result = HdfMesh.get_mesh_cell_polygons(path, backend=backend, strict=False)
    assert result.empty and calls and calls[-1]['strict'] is False
    diagnostics = result.attrs['cell_polygon_diagnostics']
    assert len(diagnostics) == 1
    record = diagnostics[0]
    assert (record['mesh_name'], record['cell_id'], record['status']) == ('Native Quarantine', 0, 'omitted')
    assert record['reason_code'] == 'no_polygon'
    # The Python reference schema exactly (main #572 parity contract): the native
    # failure kind is logged, not added to the record.
    assert set(record) == {'mesh_name', 'cell_id', 'face_count', 'polygon_count', 'status',
                           'reason_code', 'face_ids', 'missing_face_ids'}
    assert record['face_ids'] == (0, 1, 2, 3)
    with pytest.raises(MeshCellPolygonError, match='Native Quarantine.*cell 0'):
        HdfMesh.get_mesh_cell_polygons(path, backend=backend, strict=True)


@pytest.mark.parametrize('backend', ['rust', 'auto'])
@pytest.mark.parametrize('strict', [False, True])
def test_adapter_late_corruption_never_falls_back(native, tmp_path, monkeypatch, backend, strict):
    from ras_commander.hdf.HdfMesh import HdfMesh, MeshCellPolygonError
    from ras_commander.fast_hdf import FastHdfError
    import shapely.ops
    def forbidden(*args, **kwargs):
        raise AssertionError('corruption fell back to Python polygonize')
    monkeypatch.setattr(shapely.ops, 'polygonize', forbidden)
    path = write_hdf(tmp_path / 'corrupt.g01.hdf', corrupt_late=True)
    with pytest.raises((FastHdfError, MeshCellPolygonError), match='cell 1'):
        HdfMesh.get_mesh_cell_polygons(path, backend=backend, strict=strict)


@pytest.mark.parametrize('backend', ['rust', 'auto'])
def test_old_api1_capability_gate_prevents_native_policy_claim(native, tmp_path, monkeypatch, backend):
    from ras_commander.hdf.HdfMesh import HdfMesh
    from ras_commander.fast_hdf import FastHdfError
    path = write_hdf(tmp_path / 'old-api.g01.hdf')
    reference = HdfMesh.get_mesh_cell_polygons(path, backend='python', strict=False)
    assert reference.empty
    calls = []
    def legacy_assemble(face_points, face_endpoints, face_perimeter_info,
                        face_perimeter_values, cell_face_info, cell_face_values, threads=None):
        calls.append(True)
        raise AssertionError('old API1 binding must be rejected before assembly')
    monkeypatch.setattr(native, 'assemble_cells', legacy_assemble)
    assert native.API_VERSION == 1
    if backend == 'rust':
        with pytest.raises(FastHdfError, match='quarantine.*rebuild'):
            HdfMesh.get_mesh_cell_polygons(path, backend='rust', strict=False)
    else:
        actual = HdfMesh.get_mesh_cell_polygons(path, backend='auto', strict=False)
        assert actual.empty and actual.attrs == reference.attrs
    assert not calls
