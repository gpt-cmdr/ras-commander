"""Scoped raw storage rings, with an independent pixel-centre parity check."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import h5py
import numpy as np
import pytest
import shapely

from ras_commander.fim import FimUnsupportedError
from ras_commander.fim import _storage_areas as storage

BOWTIE = [(0., 0.), (4., 4.), (0., 4.), (4., 0.), (0., 0.)]
ASYMMETRIC = [(0., 0.), (4., 4.), (0., 3.), (3., 0.), (0., 0.)]


def model(tmp_path, rings, *, info=None):
    path = tmp_path / 'storage.hdf'
    points = [point for ring in rings for point in ring]
    parts = []
    offset = 0
    for ring in rings:
        parts.append([offset, len(ring)])
        offset += len(ring)
    with h5py.File(path, 'w') as source:
        group = source.create_group('Geometry/Storage Areas')
        group.create_dataset('Attributes', data=np.array([(b'Pool',)], dtype=[('Name', 'S16')]))
        group.create_dataset('Polygon Info', data=info or [[0, len(points), 0, len(rings)]])
        group.create_dataset('Polygon Parts', data=parts)
        group.create_dataset('Polygon Points', data=np.array(points, dtype='f8').reshape(-1, 2))
    return path


def test_zero_area_bowtie_requires_explicit_policy_and_preserves_wkb(tmp_path):
    path = model(tmp_path, [BOWTIE])
    with pytest.raises(FimUnsupportedError, match='not a valid polygon'):
        storage.read(path)
    original = shapely.Polygon(BOWTIE)
    areas = storage.read(path, geometry_policy=storage.NATIVE_EVEN_ODD)
    assert areas.names == ('Pool',)
    assert areas.polygons[0].wkb == original.wkb
    assert list(areas.polygons[0].exterior.coords) == BOWTIE
    assert not areas.polygons.flags.writeable
    metadata = storage.geometry_metadata(areas)
    assert metadata['policy'] == 'native_even_odd'
    assert metadata['fill_rule'] == 'even-odd'
    record, = metadata['preserved_invalid']
    assert record['native_signed_area'] == 0
    assert record['winding'] == 'zero'
    assert record['validity_reason'].startswith('Self-intersection[')
    assert record['raw_wkb_sha256'] == record['staged_wkb_sha256'] == hashlib.sha256(original.wkb).hexdigest()
    assert record['coordinates_preserved']
    # Reading and staging do not mutate either the caller's ring or source bytes.
    before = path.read_bytes()
    storage.stage_polygons(areas, tmp_path)
    assert path.read_bytes() == before
    blob = (tmp_path / 'storage_areas.wkb').read_bytes()
    assert blob.endswith(original.wkb)
    assert BOWTIE == [(0., 0.), (4., 4.), (0., 4.), (4., 0.), (0., 0.)]


def test_negative_invalid_and_invalid_holes_remain_refused(tmp_path):
    polygon = shapely.Polygon(ASYMMETRIC)
    area = storage._native_signed_area([list(polygon.exterior.coords)])
    assert area != 0
    negative = ASYMMETRIC if area < 0 else list(reversed(ASYMMETRIC))
    path = model(tmp_path, [negative])
    with pytest.raises(FimUnsupportedError, match='not a valid polygon'):
        storage.read(path, geometry_policy=storage.NATIVE_EVEN_ODD)
    positive = list(reversed(negative))
    path = model(tmp_path, [positive])
    assert storage.geometry_metadata(storage.read(path, geometry_policy=storage.NATIVE_EVEN_ODD))['preserved_invalid'][0]['native_signed_area'] > 0
    path = model(tmp_path, [BOWTIE, [(1., 1.), (1.2, 1.), (1., 1.2), (1., 1.)]])
    with pytest.raises(FimUnsupportedError, match='not a valid polygon'):
        storage.read(path, geometry_policy=storage.NATIVE_EVEN_ODD)


@pytest.mark.parametrize('kind', ['nonfinite', 'empty', 'range', 'too_short_closed', 'part_range'])
def test_structural_admission_remains(tmp_path, kind):
    ring = list(BOWTIE)
    info = None
    if kind == 'nonfinite':
        ring[1] = (float('nan'), 4.)
    elif kind == 'empty':
        ring = []
    elif kind == 'range':
        info = [[1, 100, 0, 1]]
    elif kind == 'too_short_closed':
        ring = [(0., 0.), (1., 1.), (0., 0.)]
    elif kind == 'part_range':
        info = [[0, 5, 0, 3]]
    path = model(tmp_path, [ring], info=info)
    with pytest.raises(FimUnsupportedError):
        storage.read(path, geometry_policy=storage.NATIVE_EVEN_ODD)


def test_unknown_policy_refuses_before_file_read(tmp_path):
    with pytest.raises(ValueError, match='policy'):
        storage.read(tmp_path / 'absent.hdf', geometry_policy='repair')


def test_installed_storage_owners_match_even_odd_away_from_boundaries(tmp_path):
    engine = os.environ.get('RAS_COMMANDER_STORAGE_ENGINE')
    if not engine:
        pytest.skip('set RAS_COMMANDER_STORAGE_ENGINE to exercise installed storage CLI')
    path = model(tmp_path, [BOWTIE])
    areas = storage.read(path, geometry_policy=storage.NATIVE_EVEN_ODD)
    storage.stage_polygons(areas, tmp_path)
    np.array([10.], dtype='<f4').tofile(tmp_path / 'levels.bin')
    np.zeros((4, 4), dtype='<f4').tofile(tmp_path / 'terrain.bin')
    # Noninteger origin offsets keep every centre away from vertices/crossing/edges.
    gt = [.13, 1., 0., 4.21, 0., -1.]
    expected = []
    for row in range(4):
        y = gt[3] + (row + .5) * gt[5]
        for col in range(4):
            x = gt[0] + col + .5
            intersections = sorted(a[0] + (y-a[1]) * (b[0]-a[0]) / (b[1]-a[1])
                                   for a, b in zip(BOWTIE, BOWTIE[1:])
                                   if min(a[1], b[1]) < y < max(a[1], b[1]))
            assert all(abs(x-value) > 1e-8 for value in intersections)
            expected.append(sum(value > x for value in intersections) % 2)
    request = {'schema': 'fast-map-storage/1', 'storage_areas_file': 'storage_areas.wkb',
               'storage_area_count': 1, 'levels_file': 'levels.bin', 'terrain_file': 'terrain.bin',
               'width': 4, 'height': 4, 'geo_transform': gt, 'max_working_bytes': 16*1024**2,
               'threads': 1}
    request_file = tmp_path / 'request.json'
    request_file.write_text(json.dumps(request))
    proc = subprocess.run([engine, 'storage', str(request_file), str(tmp_path / 'out')],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    np.testing.assert_array_equal(np.fromfile(tmp_path / 'out/owners.bin', dtype='<u4'), expected)
