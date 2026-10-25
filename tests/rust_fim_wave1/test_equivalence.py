"""Real-file exactness gates; RAS_FIM_WAVE1_FIXTURES is a probe JSON manifest."""
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

MANIFEST = os.environ.get('RAS_FIM_WAVE1_FIXTURES')
FIXTURES = json.loads(Path(MANIFEST).read_text()) if MANIFEST else []
pytestmark = pytest.mark.skipif(not MANIFEST, reason='Set RAS_FIM_WAVE1_FIXTURES to the real-file probe JSON manifest')


def exact(a, b):
    assert a.dtype == b.dtype
    assert a.shape == b.shape
    assert a.tobytes() == b.tobytes()


@pytest.mark.parametrize('fixture', FIXTURES, ids=[Path(f['path']).name for f in FIXTURES])
def test_typed_reads(fixture):
    native = pytest.importorskip('ras_commander_fast_hdf')
    assert native.API_VERSION == 11
    path = fixture['path']
    with h5py.File(path, 'r') as f:
        for mesh in native.mesh_inventory(path):
            area = mesh['mesh_name']
            for invname, readname in [('mesh_summary_inventory', 'read_mesh_summary'), ('mesh_series_inventory', 'read_mesh_series'), ('mesh_boundary_inventory', 'read_mesh_boundary_series')]:
                inv = getattr(native, invname)(path, area)
                for v in inv['variables']:
                    if v['capability']['status'] != 'supported':
                        continue
                    ds = f[v['path']]
                    elements = [min(2, ds.shape[-1]-1), 0, 0]
                    if invname == 'mesh_summary_inventory':
                        out = getattr(native, readname)(path, area, v['name'], elements)['values']
                        expected = ds[()][..., elements]
                    else:
                        rows = (0, min(ds.shape[0], 24), 2)
                        out = getattr(native, readname)(path, area, v['name'], rows, elements)['values']
                        expected = ds[0:rows[1]:2, :][..., elements]
                    exact(out, expected)
            for field, dataset in [('cell_centers','Cells Center Coordinate'),('cell_minimum_elevation','Cells Minimum Elevation'),('face_points','FacePoints Coordinate'),('face_point_indexes','Faces FacePoint Indexes'),('face_cell_indexes','Faces Cell Indexes'),('face_normals_and_length','Faces NormalUnitVector and Length'),('face_area_elevation_info','Faces Area Elevation Info'),('face_area_elevation_values','Faces Area Elevation Values'),('cell_face_info','Cells Face and Orientation Info'),('cell_face_values','Cells Face and Orientation Values'),('face_perimeter_info','Faces Perimeter Info'),('face_perimeter_values','Faces Perimeter Values')]:
                key = f'Geometry/2D Flow Areas/{area}/{dataset}'
                if key in f:
                    n = min(len(f[key]), 32)
                    exact(native.read_mesh_geometry(path, area, field, (0,n,1)), f[key][:n])
            assert native.compare_mesh_identity(path,path,area)['first_mismatch'] is None
        for family, prefix in [('boundary_conditions','Geometry/Boundary Condition Lines/Polyline'),('breaklines','Geometry/2D Flow Area Break Lines/Polyline'),('refinement_regions','Geometry/2D Flow Area Refinement Regions/Polygon'),('reference_lines','Geometry/Reference Lines/Polyline')]:
            r = native.geometry_family(path,family)
            if r['capability']['status'] == 'supported':
                for k in ['info','parts','points']:
                    exact(r['value'][k],f[prefix+' '+k.title()][()])
        summary = native.run_summary(path)
        if summary['capability']['status'] == 'supported':
            for group in summary['value']:
                assert {a['name'] for a in group['attributes']} == set(f[group['path']].attrs)
        assert native.layer_inventory(path)


def assert_metadata(a, b):
    assert type(a) is type(b)
    if isinstance(a, dict):
        assert list(a) == list(b)
        for key in a:
            assert_metadata(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert_metadata(x, y)
    elif isinstance(a, (float, np.floating, np.ndarray)):
        exact(np.asarray(a), np.asarray(b))
    else:
        assert a == b


METHODS = [('HdfResultsMesh','get_mesh_max_ws'),('HdfMesh','get_mesh_areas'),('HdfMesh','get_mesh_cell_points'),('HdfMesh','get_mesh_cell_faces'),('HdfBndry','get_breaklines'),('HdfBndry','get_refinement_regions')]


@pytest.mark.parametrize('fixture', FIXTURES, ids=[Path(f['path']).name for f in FIXTURES])
@pytest.mark.parametrize('owner,method', METHODS)
def test_public_exact(fixture, owner, method, monkeypatch):
    import ras_commander as ras
    fn = getattr(getattr(ras, owner), method)
    monkeypatch.setenv('RAS_COMMANDER_FAST_HDF','0')
    expected = fn(fixture['path'])
    monkeypatch.setenv('RAS_COMMANDER_FAST_HDF','required')
    actual = fn(fixture['path'])
    pd.testing.assert_frame_equal(actual,expected,check_exact=True)
    if 'geometry' in actual:
        assert actual.crs == expected.crs
        assert actual.geometry.to_wkb().tolist() == expected.geometry.to_wkb().tolist()
    assert_metadata(actual.attrs, expected.attrs)

@pytest.mark.parametrize('fixture', FIXTURES, ids=[Path(f['path']).name for f in FIXTURES])
def test_extrema_and_budget(fixture):
    native = pytest.importorskip('ras_commander_fast_hdf')
    path = fixture['path']
    with h5py.File(path,'r') as f:
        area=native.mesh_inventory(path)[0]['mesh_name']
        ds=f[f'Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas/{area}/Water Surface']
        end=min(len(ds),5)
        expected=ds[:end,:3]
        caps={v['name']:v['capability'] for v in native.mesh_series_inventory(path,area)['variables']}
        # Engine API 9 (7d89bbb): 5.0.7 series without a stored Location attribute are
        # domain-qualified by the absent-Location legacy exact-name rule (API 8 refused them).
        assert caps['Water Surface']['status']=='supported'
        r=native.reduce_mesh_series(path,area,'Water Surface',(0,end,1),[0,1,2])
        indexes=np.stack([expected.argmin(axis=0),expected.argmax(axis=0)])
        values=np.take_along_axis(expected,indexes,axis=0)
        exact(r['values'],values)
        np.testing.assert_array_equal(np.asarray(r['time_indices']).reshape(2,3),indexes)
        with pytest.raises(ValueError) as error:
            native.read_mesh_series(path,area,'Water Surface',(0,end,1),[0,1,2],max_bytes=1)
        assert error.value.engine_kind=='invalid_request'
        assert error.value.engine_code=='resource_limit'
