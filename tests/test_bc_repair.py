"""Opt-in repair on native-layout HDFs; no native solver qualification."""
import h5py
import numpy as np
import pytest

from ras_commander.geom import GeomBcLines
from ras_commander._bc_tie_provenance import read_receipt, ATTRIBUTE, GROUP


def case(tmp_path, *, reverse=False, dtype='f8', split=False):
    path = tmp_path / 'repair.g01.hdf'
    xy = np.array([[0, 0], [10, 0], [20, 0], [30, 0], [30, 10], [0, 10]], float)
    with h5py.File(path, 'w') as f:
        f.attrs.update({'File Type': np.bytes_('HEC-RAS Geometry'),
                        'File Version': np.bytes_('HEC-RAS 7.0.1'), 'Units System': np.bytes_('SI Units')})
        f['Geometry/2D Flow Areas/Attributes'] = np.array([(b'A', 1)], dtype=[('Name','S8'),('Cell Count','i4')])
        mesh = f.require_group('Geometry/2D Flow Areas/A')
        mesh['Perimeter'] = xy[::-1] if reverse else xy
        mesh['FacePoints Coordinate'] = xy
        mesh['Faces FacePoint Indexes'] = [[i, (i+1)%6] for i in range(6)]
        mesh['Faces Cell Indexes'] = [[0, -1]] * 6
        group = f.require_group(GROUP)
        group['Attributes'] = np.array([(b'Left', b'A', b'External'),(b'Right',b'A',b'External')],
                                      dtype=[('Name','S16'),('SA-2D','S8'),('Type','S8')])
        lines = [[[1, -1], [29, -1]], [[10, -1], [20, -1]]] if split else [[[1, -1], [15, -1]], [[15, -1], [29, -1]]]
        if reverse:
            lines = [line[::-1] for line in lines]
        group['Polyline Points'] = np.asarray(lines, dtype=dtype).reshape(-1, 2)
        group['Polyline Info'] = np.array([[0,2,0,1],[2,2,1,1]], dtype='i4')
        group['Polyline Parts'] = np.array([[0,2],[0,2]], dtype='i4')
        f['unrelated'] = [42]
    return path


TYPES = {('A','Left'): 'flow', ('A','Right'): 'normal_depth'}


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('dtype', ['f4', 'f8'])
def test_repair_and_repeat_preserve_receipt(tmp_path, reverse, dtype):
    path = case(tmp_path, reverse=reverse, dtype=dtype)
    before = path.read_bytes()
    preview = GeomBcLines.preview_external_face_repair(path, boundary_types=TYPES)
    assert path.read_bytes() == before
    assert preview['repair_audit'][0]['length_before'] == pytest.approx(14)
    assert preview['repair_audit'][0]['length_after'] == pytest.approx(8)
    with pytest.raises(ValueError, match='Conflicting'):
        GeomBcLines.write_external_faces(path, experimental=True)
    result = GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True, boundary_types=TYPES)
    assert result['backup_path'].read_bytes() == before
    with h5py.File(path) as f:
        receipt = read_receipt(f, TYPES, require_types=True)
        assert len(receipt['types']) == 2
        assert f['unrelated'][0] == 42
        assert f[f'{GROUP}/Polyline Points'].dtype == np.dtype(dtype)
        np.testing.assert_array_equal(f[f'{GROUP}/Polyline Parts'][()], [[0,2],[0,2]])
    after = path.read_bytes()
    repeat = GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True, boundary_types=TYPES)
    assert repeat['backup_path'] is None
    assert path.read_bytes() == after
    with pytest.raises(ValueError, match='contradiction'):
        GeomBcLines.preview_external_face_repair(path, boundary_types={})
    # Ordinary recovery may refresh bindings but cannot erase prior tie types.
    GeomBcLines.write_external_faces(path, experimental=True)
    with h5py.File(path) as f:
        assert read_receipt(f)['types'] == receipt['types']


def test_middle_loss_refused(tmp_path):
    path = case(tmp_path, split=True)
    before = path.read_bytes()
    types = {('A','Left'): 'normal_depth', ('A','Right'): 'flow'}
    with pytest.raises(ValueError, match='split'):
        GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True, boundary_types=types)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.bak'))


def test_unresolved_types_and_parts_refused(tmp_path):
    path = case(tmp_path)
    with pytest.raises(ValueError, match='Unresolved'):
        GeomBcLines.preview_external_face_repair(path)
    with h5py.File(path, 'r+') as f:
        f[f'{GROUP}/Polyline Parts'][0] = [1,2]
    with pytest.raises(ValueError, match='Parts'):
        GeomBcLines.preview_external_face_repair(path, boundary_types=TYPES)


def test_stale_provenance_refused(tmp_path):
    path = case(tmp_path)
    GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True, boundary_types=TYPES)
    with h5py.File(path, 'r+') as f:
        f[f'{GROUP}/Polyline Points'][0] = [2,-1]
    with pytest.raises(ValueError, match='stale'):
        GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True, boundary_types=TYPES)


def test_both_ends_trimmed_without_type_tie(tmp_path):
    path = case(tmp_path)
    with h5py.File(path, 'r+') as f:
        g = f[GROUP]
        attrs = np.repeat(g['Attributes'][()][:1], 3)
        attrs['Name'] = [b'Left', b'Right', b'Middle']
        updates = {'Attributes': attrs,
                   'Polyline Points': np.array([[1,-1],[10,-1],[20,-1],[29,-1],[5,-1],[25,-1]], float),
                   'Polyline Info': np.array([[0,2,0,1],[2,2,1,1],[4,2,2,1]], dtype='i4'),
                   'Polyline Parts': np.array([[0,2]]*3, dtype='i4')}
        for name, data in updates.items():
            del g[name]
            g[name] = data
    result = GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True)
    assert result['repair_audit'][0]['lost_faces'] == [0, 2]
    with h5py.File(path) as f:
        np.testing.assert_array_equal(f[f'{GROUP}/Polyline Points'][4:], [[11,-1],[19,-1]])
        assert read_receipt(f)['types'] == []


@pytest.mark.parametrize('dataset', ['Polyline Points', 'Polyline Info', 'Polyline Parts'])
def test_repair_rejects_shared_storage(tmp_path, dataset):
    path = case(tmp_path)
    with h5py.File(path, 'r+') as f:
        f['alias'] = f[f'{GROUP}/{dataset}']
    before = path.read_bytes()
    with pytest.raises(ValueError, match='shared hard-linked'):
        GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True, boundary_types=TYPES)
    assert path.read_bytes() == before


def test_repair_replace_failure_preserves_original_and_backup(tmp_path, monkeypatch):
    import os
    path = case(tmp_path)
    before = path.read_bytes()
    def fail(*args):
        raise OSError('replace failed')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='replace failed'):
        GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True, boundary_types=TYPES)
    assert path.read_bytes() == before
    backups = list(tmp_path.glob('*.bak'))
    assert len(backups) == 1 and backups[0].read_bytes() == before
    assert not list(tmp_path.glob('bc-faces-*'))


@pytest.mark.parametrize('budget', [0, True, 1.5, 101])
def test_invalid_pass_budget(tmp_path, budget):
    with pytest.raises(ValueError, match='max_repair_passes'):
        GeomBcLines.preview_external_face_repair(case(tmp_path), max_repair_passes=budget)


def test_existing_forcing_refused(tmp_path):
    path = case(tmp_path)
    with h5py.File(path, 'r+') as f:
        f['Event Conditions/Unsteady/Boundary Conditions/existing'] = [1]
    before = path.read_bytes()
    with pytest.raises(ValueError, match='existing boundary forcing'):
        GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True, boundary_types=TYPES)
    assert path.read_bytes() == before


@pytest.mark.parametrize('conflict', [True, False])
def test_reversing_winner_or_uncontested_line_refused(tmp_path, conflict):
    path = case(tmp_path)
    with h5py.File(path, 'r+') as f:
        g = f[GROUP]
        del g['Polyline Points']
        g['Polyline Points'] = np.array([[1,-1],[8,-1],[3,-1],[15,-1],
                                         [15 if conflict else 21,-1],[29,-1]], float)
        g['Polyline Info'][...] = [[0,4,0,1],[4,2,1,1]]
        g['Polyline Parts'][...] = [[0,4],[0,2]]
    before = path.read_bytes()
    with pytest.raises(ValueError, match='Backwards|Discontinuous'):
        GeomBcLines.write_external_faces(path, experimental=True, repair_conflicts=True, boundary_types=TYPES)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.bak'))
