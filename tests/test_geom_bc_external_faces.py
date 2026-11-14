import h5py
import numpy as np
import pytest
from ras_commander.geom import GeomBcLines


@pytest.mark.parametrize('scale', [1, 3.280839895])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('rotation', [0, 2])
def test_compiled_binding(tmp_path, scale, reverse, rotation):
    path = tmp_path / 'mesh.hdf'
    xy = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float) * scale
    ring = np.roll(xy[::-1] if reverse else xy, rotation, axis=0)
    with h5py.File(path, 'w') as f:
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
    before = path.read_bytes()
    result = GeomBcLines.compute_external_faces(path)
    assert path.read_bytes() == before
    assert result['lengths'] == pytest.approx([10 * scale])
    rows = result['external_faces']
    assert rows['Face Index'].tolist() == [3, 0]
    assert rows['FP Start Index'].tolist() == [3, 0]
    assert rows['Station Start'] == pytest.approx(np.array([-5, 5]) * scale)
    assert rows['Station End'] == pytest.approx(np.array([5, 15]) * scale)
    with h5py.File(path, 'r+') as f:
        f['Geometry/Boundary Condition Lines/Polyline Points'][...] = 0
    with pytest.raises(ValueError, match='Degenerate'):
        GeomBcLines.compute_external_faces(path)
