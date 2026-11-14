import h5py
import numpy as np
import pytest
from ras_commander.geom import GeomBcLines


def make_mesh(tmp_path, scale=1, reverse=False, rotation=0):
    path = tmp_path / 'mesh.g01.hdf'
    xy = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float) * scale
    ring = np.roll(xy[::-1] if reverse else xy, rotation, axis=0)
    with h5py.File(path, 'w') as f:
        f.attrs['File Type'] = np.bytes_('HEC-RAS Geometry')
        f.attrs['File Version'] = np.bytes_('HEC-RAS 7.0.1 June 2026')
        f.attrs['Units System'] = np.bytes_('SI Units')
        f['unrelated'] = [42]
        areas = f.create_group('Geometry/2D Flow Areas')
        areas['Attributes'] = np.array([(b'A', 1)], dtype=[('Name', 'S16'), ('Cell Count', 'i4')])
        mesh = areas.create_group('A')
        mesh['Perimeter'] = ring
        mesh['Faces Cell Indexes'] = [[0, -1], [0, 1], [0, -1], [0, 1]]
        mesh['Faces FacePoint Indexes'] = [[0, 1], [1, 2], [2, 3], [3, 0]]
        mesh['FacePoints Coordinate'] = xy
        bc = f.create_group('Geometry/Boundary Condition Lines')
        bc['Attributes'] = np.array([(b'In', b'A', b'External')], dtype=[('Name', 'S32'), ('SA-2D', 'S16'), ('Type', 'S8')])
        bc['Polyline Info'] = [[0, 3, 0, 1]]
        bc['Polyline Points'] = np.array([[0, 5], [0, 0], [5, 0]]) * scale
    return path


@pytest.mark.parametrize('scale', [1, 3.280839895])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('rotation', [0, 2])
def test_compiled_binding(tmp_path, scale, reverse, rotation):
    path = make_mesh(tmp_path, scale, reverse, rotation)
    before = path.read_bytes()
    result = GeomBcLines.compute_external_faces(path)
    assert path.read_bytes() == before
    assert result['lengths'] == pytest.approx([10 * scale])
    rows = result['external_faces']
    assert rows['Face Index'].tolist() == [3, 0]
    assert rows['FP Start Index'].tolist() == [3, 0]
    assert rows['Station Start'].to_numpy() == pytest.approx(np.array([-5, 5]) * scale)
    assert rows['Station End'].to_numpy() == pytest.approx(np.array([5, 15]) * scale)
    with h5py.File(path, 'r+') as f:
        f['Geometry/Boundary Condition Lines/Polyline Points'][...] = 0
    with pytest.raises(ValueError, match='Degenerate'):
        GeomBcLines.compute_external_faces(path)


@pytest.mark.parametrize('units', ['SI Units', 'US Customary'])
def test_write_preserves_backup_and_unrelated_content(tmp_path, units):
    path = make_mesh(tmp_path)
    with h5py.File(path, 'r+') as f:
        f.attrs['Units System'] = np.bytes_(units)
        f['Geometry/Boundary Condition Lines/Attributes'].attrs['Custom'] = 'retained'
    before = path.read_bytes()
    result = GeomBcLines.write_external_faces(path, experimental=True)
    assert result['backup_path'].read_bytes() == before
    with h5py.File(path) as f:
        bc = f['Geometry/Boundary Condition Lines']
        assert bc['Attributes']['Length'].tolist() == [10.]
        assert bc['Attributes']['Name'].tolist() == [b'In']
        assert bc['Attributes'].attrs['Custom'] == 'retained'
        assert f['unrelated'][()].tolist() == [42]
        assert bc['External Faces'].dtype['Station Start'] == np.dtype('<f4')
        np.testing.assert_array_equal(bc['External Faces']['Face Index'], [3, 0])
    # Repeating the operation retains another distinct backup.
    again = GeomBcLines.write_external_faces(path, experimental=True)
    assert again['backup_path'] != result['backup_path']
    assert result['backup_path'].read_bytes() == before


@pytest.mark.parametrize('bad', ['version', 'results', 'units', 'faces', 'degenerate', 'multipart', 'unknown_area'])
def test_write_rejects_before_mutation(tmp_path, bad):
    path = make_mesh(tmp_path)
    with h5py.File(path, 'r+') as f:
        if bad in ('version', 'results', 'units'):
            key, value = {'version': ('File Version', 'HEC-RAS 6.6'),
                          'results': ('File Type', 'HEC-RAS Results'),
                          'units': ('Units System', 'unknown')}[bad]
            f.attrs[key] = np.bytes_(value)
        elif bad == 'faces':
            f['Geometry/2D Flow Areas/A/Faces FacePoint Indexes'][0] = [99, 1]
        elif bad == 'degenerate':
            f['Geometry/Boundary Condition Lines/Polyline Points'][...] = 0
        elif bad == 'multipart':
            f['Geometry/Boundary Condition Lines/Polyline Info'][0] = [0, 3, 0, 2]
        else:
            ds = f['Geometry/Boundary Condition Lines/Attributes']
            rows = ds[()]
            rows['SA-2D'] = b'Unknown'
            ds[...] = rows
    before = path.read_bytes()
    with pytest.raises(ValueError):
        GeomBcLines.write_external_faces(path, experimental=True)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.bak'))
    assert not list(tmp_path.glob('bc-faces-*'))


def test_write_requires_optin_and_closed_handles(tmp_path):
    path = make_mesh(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='experimental=True'):
        GeomBcLines.write_external_faces(path)
    with h5py.File(path):
        with pytest.raises(RuntimeError, match='GEOMETRY_HDF_OPEN'):
            GeomBcLines.write_external_faces(path, experimental=True)
    assert path.read_bytes() == before


def test_atomic_replace_failure_retains_original(tmp_path, monkeypatch):
    path = make_mesh(tmp_path)
    before = path.read_bytes()
    def fail(*args):
        raise OSError('injected replace failure')
    monkeypatch.setattr('os.replace', fail)
    with pytest.raises(OSError, match='injected'):
        GeomBcLines.write_external_faces(path, experimental=True)
    assert path.read_bytes() == before
    assert len(list(tmp_path.glob('*.bak'))) == 1
    assert not list(tmp_path.glob('bc-faces-*'))


@pytest.mark.parametrize('scale', [1., 3.280839895])
@pytest.mark.parametrize('reverse', [False, True])
def test_zero_touch_and_tiny_positive_overlap(tmp_path, scale, reverse):
    path = make_mesh(tmp_path, scale=scale)
    with h5py.File(path, 'r+') as f:
        ds = f['Geometry/Boundary Condition Lines/Polyline Points']
        # End exactly at the corner; the next face only touches the boundary.
        points = np.array([[0., 5.], [0., 2.5], [0., 0.]]) * scale
        ds[...] = points[::-1] if reverse else points
    result = GeomBcLines.compute_external_faces(path)
    assert result['external_faces']['Face Index'].tolist() == [3]
    with h5py.File(path, 'r+') as f:
        points[-1] = [1e-5 * scale, 0.]
        f['Geometry/Boundary Condition Lines/Polyline Points'][...] = points[::-1] if reverse else points
    result = GeomBcLines.compute_external_faces(path)
    assert result['external_faces']['Face Index'].tolist() == ([0, 3] if reverse else [3, 0])


def test_no_perimeter_faces_rejected(tmp_path):
    path = make_mesh(tmp_path)
    with h5py.File(path, 'r+') as f:
        f['Geometry/2D Flow Areas/A/Faces Cell Indexes'][...] = 0
    with pytest.raises(ValueError, match='no overlapping'):
        GeomBcLines.compute_external_faces(path)


def test_multiple_area_indexes_remain_local(tmp_path):
    path = make_mesh(tmp_path)
    with h5py.File(path, 'r+') as f:
        areas = f['Geometry/2D Flow Areas']
        areas.copy('A', 'B')
        records = np.repeat(areas['Attributes'][()], 2)
        records['Name'][1] = b'B'
        del areas['Attributes']
        areas['Attributes'] = records
        bc = f['Geometry/Boundary Condition Lines']
        records = np.repeat(bc['Attributes'][()], 2)
        records['SA-2D'][1] = b'B'
        del bc['Attributes']
        bc['Attributes'] = records
        info = np.repeat(bc['Polyline Info'][()], 2, axis=0)
        del bc['Polyline Info']
        bc['Polyline Info'] = info
    result = GeomBcLines.write_external_faces(path, experimental=True)
    assert result['lengths'].tolist() == [10., 10.]
    assert result['external_faces']['BC Line ID'].tolist() == [0, 0, 1, 1]
    assert result['external_faces']['Face Index'].tolist() == [3, 0, 3, 0]


@pytest.mark.integration
def test_public_701_upper_area_reference(tmp_path):
    """Compare unchanged native BC rows using a matching public perimeter source."""
    import importlib
    import os
    from pathlib import Path
    import shutil
    from ras_commander import init_ras_project

    project = os.environ.get('RAS_BC_PUBLIC_EXAMPLE')
    if not project:
        pytest.skip('Set RAS_BC_PUBLIC_EXAMPLE to extracted BaldEagleCrkMulti2D 7.0 examples')
    ras = init_ras_project(project, '7.0.1', load_results_summary=False, hide_intro=True)
    source = ras.geom_df.loc[ras.geom_df.geom_number == '11', 'hdf_path'].iloc[0]
    helper = importlib.import_module('ras_commander.geom.GeomMesh')._hdf_flow_area_perimeter
    perimeter = helper(source, 'Upper 2D Area')
    target = tmp_path / 'reference.hdf'
    shutil.copy2(Path(__file__).parent / 'fixtures/bc_conflicts/BaldEagleDamBrk.p18.bclines.hdf', target)
    with h5py.File(target, 'r+') as f, h5py.File(source) as original:
        area_path = 'Geometry/2D Flow Areas/Upper 2D Area'
        for dataset in ('Cells Center Coordinate', 'FacePoints Coordinate', 'Faces FacePoint Indexes'):
            np.testing.assert_array_equal(f[f'{area_path}/{dataset}'][()], original[f'{area_path}/{dataset}'][()])
        f[f'{area_path}/Perimeter'] = perimeter
        areas = f['Geometry/2D Flow Areas']
        attrs = areas['Attributes'][()]
        del areas['Attributes']
        areas['Attributes'] = attrs[attrs['Name'] == b'Upper 2D Area']
        bc = f['Geometry/Boundary Condition Lines']
        attrs = bc['Attributes'][()]
        selected = np.flatnonzero(attrs['SA-2D'] == b'Upper 2D Area')
        native = bc['External Faces'][()]
        native = native[native['BC Line ID'] == selected[0]]
        native['BC Line ID'] = 0
        info = bc['Polyline Info'][()][selected]
        del bc['Attributes'], bc['Polyline Info']
        bc['Attributes'] = attrs[selected]
        bc['Polyline Info'] = info
    result = GeomBcLines.compute_external_faces(target)
    assert len(result['external_faces']) == len(native) == 6
    for name in native.dtype.names[:4]:
        np.testing.assert_array_equal(result['external_faces'][name], native[name])
    for name in native.dtype.names[4:]:
        np.testing.assert_allclose(result['external_faces'][name], native[name], atol=3e-4, rtol=0)
    np.testing.assert_allclose(result['lengths'], attrs['Length'][selected], atol=3e-4, rtol=0)


@pytest.mark.parametrize('separate_portions', [False, True])
def test_two_boundaries_cannot_claim_same_area_face(tmp_path, separate_portions):
    path = make_mesh(tmp_path)
    with h5py.File(path, 'r+') as f:
        bc = f['Geometry/Boundary Condition Lines']
        attrs = np.repeat(bc['Attributes'][()], 2)
        attrs['Name'][1] = b'Other'
        del bc['Attributes']
        bc['Attributes'] = attrs
        del bc['Polyline Info']
        bc['Polyline Info'] = [[0, 2, 0, 1], [2, 2, 0, 1]]
        del bc['Polyline Points']
        bc['Polyline Points'] = ([[0, 1], [0, 3], [0, 6], [0, 8]] if separate_portions
                                 else [[0, 1], [0, 6], [0, 3], [0, 8]])
    before = path.read_bytes()
    for operation in (GeomBcLines.compute_external_faces,
                      lambda p: GeomBcLines.write_external_faces(p, experimental=True)):
        with pytest.raises(ValueError, match='Conflicting BC face ownership'):
            operation(path)
        assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.bak'))
    assert not list(tmp_path.glob('bc-faces-*'))


@pytest.mark.parametrize('scale', [1., 3.280839895])
def test_island_boundary_faces_are_not_projected_onto_outer_ring(tmp_path, scale):
    path = make_mesh(tmp_path, scale=scale)
    with h5py.File(path, 'r+') as f:
        mesh = f['Geometry/2D Flow Areas/A']
        for name, extra in (
            ('FacePoints Coordinate', np.array([[1, 2], [1, 4]]) * scale),
            ('Faces FacePoint Indexes', [[4, 5]]),
            ('Faces Cell Indexes', [[0, -1]]),
        ):
            data = np.concatenate((mesh[name][()], extra))
            del mesh[name]
            mesh[name] = data
    result = GeomBcLines.compute_external_faces(path)
    assert result['external_faces']['Face Index'].tolist() == [3, 0]


def test_float32_face_points_preserve_outer_boundary_candidates(tmp_path):
    path = make_mesh(tmp_path)
    with h5py.File(path, 'r+') as f:
        for group, name in (
            ('Geometry/2D Flow Areas/A', 'Perimeter'),
            ('Geometry/2D Flow Areas/A', 'FacePoints Coordinate'),
            ('Geometry/Boundary Condition Lines', 'Polyline Points'),
        ):
            parent = f[group]
            data = parent[name][()] + 1000000.03
            if name == 'FacePoints Coordinate':
                data = data.astype('float32')
            del parent[name]
            parent[name] = data
    result = GeomBcLines.compute_external_faces(path)
    assert result['external_faces']['Face Index'].tolist() == [3, 0]
