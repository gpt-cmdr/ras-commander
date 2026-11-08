"""Read-only dimensional evidence and unchanged strict 2D mapping admission."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json

import h5py
import numpy as np
import pytest

from ras_commander.fim import FimModelScope, FimUnsupportedError, RasFim
from ras_commander.fim import _engine


def scene(tmp_path, *, mesh=False, xs=False, rivers=False, storage=False):
    path = tmp_path / 'model.p01.hdf'
    with h5py.File(path, 'w') as source:
        if mesh:
            source.create_dataset('Geometry/2D Flow Areas/surface/Cells Center Coordinate', shape=(2, 2), dtype='f8')
        if xs:
            source.create_dataset('Geometry/Cross Sections/Attributes', shape=(3,), dtype=[('RS', 'S16')])
        if rivers:
            source.create_dataset('Geometry/River Centerlines/Attributes', shape=(1,), dtype=[('Reach', 'S16')])
        if storage:
            source.create_dataset('Geometry/Storage Areas/Attributes', data=np.array([(b'Pool',)], dtype=[('Name', 'S16')]))
    return path


@pytest.mark.parametrize(('options', 'dimension', 'methods'), [
    ({'mesh': True}, '2d', ('horizontal', 'sloping')),
    ({'xs': True, 'rivers': True}, '1d', ('one_d_clipped_diagnostic',)),
    ({'xs': True, 'mesh': True}, 'mixed_1d_2d', ('coupled_diagnostic',)),
    ({'xs': True, 'mesh': True, 'storage': True}, 'mixed_1d_2d', ('coupled_storage_diagnostic',)),
    ({'storage': True}, 'storage_only', ('storage',)),
])
def test_all_dimensions_and_candidate_methods(tmp_path, monkeypatch, options, dimension, methods):
    path = scene(tmp_path, **options)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(_engine, 'find_engine', lambda *a, **k: pytest.fail('scope inspection must not resolve an engine'))
    result = RasFim.inspect_model_scope(path)
    assert isinstance(result, FimModelScope)
    assert result.dimension == dimension and result.methods == methods
    assert result.cross_section_count == (3 if options.get('xs') else 0)
    assert result.reach_count == (1 if options.get('rivers') else 0)
    assert result.mesh_names == (('surface',) if options.get('mesh') else ())
    assert result.storage_area_names == (('Pool',) if options.get('storage') else ())
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.loads(json.dumps(result.to_dict()))['dimension'] == dimension
    if dimension == '2d':
        legacy = RasFim.validate_2d_model(path)
        assert legacy['dimension'] == '2D-only'
        assert legacy['mesh_names'] == ['surface']
        assert legacy['storage_areas'] == 0
    else:
        with pytest.raises(FimUnsupportedError, match='2D-only'):
            RasFim.validate_2d_model(path)


def test_scope_is_frozen_and_to_dict_is_detached(tmp_path):
    scope = RasFim.inspect_model_scope(scene(tmp_path, mesh=True, storage=True))
    with pytest.raises(FrozenInstanceError):
        scope.dimension = '1d'
    duplicate = replace(scope, mesh_names=['surface'])
    assert duplicate.mesh_names == ('surface',)
    data = scope.to_dict()
    data['mesh_names'].append('invented')
    data['storage_area_names'].clear()
    data['methods'].append('invented')
    assert scope.mesh_names == ('surface',)
    assert scope.storage_area_names == ('Pool',)
    assert scope.methods == ('horizontal', 'sloping')
    assert data['hdf_path'] == str(scope.hdf_path)


def test_metadata_inspection_never_reads_geometry_payloads(tmp_path, monkeypatch):
    path = scene(tmp_path, mesh=True, xs=True, rivers=True, storage=True)
    with h5py.File(path, 'a') as source:
        source.create_dataset('Geometry/Cross Sections/Polyline Points', shape=(100, 2), dtype='f8')
        source.create_dataset('Geometry/2D Flow Areas/Attributes', data=np.array([(b'surface', 2)], dtype=[('Name', 'S16'), ('Cell Count', 'i4')]))
    original = h5py.Dataset.__getitem__
    def read(dataset, key):
        if dataset.name.endswith(('Cells Center Coordinate', 'Polyline Points')) or '/Cross Sections/' in dataset.name or '/River Centerlines/' in dataset.name:
            pytest.fail('geometry arrays read during dimensional inspection')
        return original(dataset, key)
    monkeypatch.setattr(h5py.Dataset, '__getitem__', read)
    result = RasFim.inspect_model_scope(path)
    assert result.dimension == 'mixed_1d_2d'
    assert result.cross_section_count == 3


@pytest.mark.parametrize('declaration', ['River Reach=Main,Reach', 'Reach=Legacy', 'River Reach=broken', 'Type RM Length L Ch R=1,10,2,2,2'])
def test_text_evidence_cannot_bypass_mixed_guard(tmp_path, declaration):
    path = scene(tmp_path, mesh=True)
    geometry = tmp_path / 'model.g01'
    geometry.write_text('Geom Title=Scope\n' + declaration + '\n', encoding='utf-8')
    with h5py.File(path, 'a') as source:
        source.require_group('Plan Data/Plan Information').attrs['Geometry Filename'] = geometry.name
    scope = RasFim.inspect_model_scope(path)
    assert scope.dimension == 'mixed_1d_2d' and scope.cross_section_count == 0
    assert scope.geometry_path == geometry.resolve()
    assert scope.text_reaches + scope.text_1d_nodes == 1
    with pytest.raises(FimUnsupportedError, match='Selecting a 2D mesh does not bypass'):
        RasFim.validate_2d_model(path)


def test_orphaned_polyline_refuses_without_inventing_feature_count(tmp_path):
    path = scene(tmp_path, mesh=True)
    with h5py.File(path, 'a') as source:
        source.create_dataset('Geometry/Cross Sections/Polyline Points', shape=(4, 2), dtype='f8')
    with pytest.raises(FimUnsupportedError, match='orphaned polyline geometry'):
        RasFim.inspect_model_scope(path)
    with pytest.raises(FimUnsupportedError, match='2D-only'):
        RasFim.validate_2d_model(path)


def test_pipe_and_bridge_hydraulic_tables_are_not_river_geometry(tmp_path):
    path = scene(tmp_path, mesh=True)
    with h5py.File(path, 'a') as source:
        source.create_dataset('Geometry/Cross Sections/Property Tables/XSEC Info', shape=(6, 3), dtype='i4')
        source.create_dataset('Geometry/Pipe Conduits/Attributes', data=[1, 2])
    assert RasFim.inspect_model_scope(path).dimension == '2d'
    assert RasFim.validate_2d_model(path)['cross_section_records'] == 0


@pytest.mark.parametrize('case', ['empty', 'zero_centers', 'zero_physical', 'bad_centers', 'scalar_identity', 'bad_group', 'bad_storage', 'duplicate_storage', 'bad_cell_count', 'missing_count_row', 'orphan_count_row', 'bad_count_table'])
def test_missing_or_malformed_geometry_refuses(tmp_path, case):
    path = scene(tmp_path)
    with h5py.File(path, 'a') as source:
        if case == 'zero_centers':
            source.create_dataset('Geometry/2D Flow Areas/surface/Cells Center Coordinate', shape=(0, 2), dtype='f8')
        elif case in ('zero_physical', 'bad_cell_count'):
            source.create_dataset('Geometry/2D Flow Areas/surface/Cells Center Coordinate', shape=(2, 2), dtype='f8')
            source.create_dataset('Geometry/2D Flow Areas/Attributes', data=np.array([(b'surface', 0 if case == 'zero_physical' else 3)], dtype=[('Name', 'S16'), ('Cell Count', 'i4')]))
        elif case == 'bad_centers':
            source.create_dataset('Geometry/2D Flow Areas/surface/Cells Center Coordinate', data=[1, 2])
        elif case == 'scalar_identity':
            source.create_dataset('Geometry/Cross Sections/Attributes', data=1)
        elif case == 'bad_group':
            source.create_dataset('Geometry/River Centerlines', data=[1])
        elif case == 'bad_storage':
            source.create_dataset('Geometry/Storage Areas/Attributes', data=[1])
        elif case == 'duplicate_storage':
            source.create_dataset('Geometry/Storage Areas/Attributes', data=np.array([(b'Pool',), (b'Pool',)], dtype=[('Name', 'S16')]))
        elif case in ('missing_count_row', 'orphan_count_row', 'bad_count_table'):
            source.create_dataset('Geometry/2D Flow Areas/surface/Cells Center Coordinate', shape=(2, 2), dtype='f8')
            if case == 'bad_count_table':
                source.create_dataset('Geometry/2D Flow Areas/Attributes', data=[1, 2])
            else:
                rows = [] if case == 'missing_count_row' else [(b'surface', 2), (b'other', 1)]
                source.create_dataset('Geometry/2D Flow Areas/Attributes', data=np.array(rows, dtype=[('Name', 'S16'), ('Cell Count', 'i4')]))
    with pytest.raises(FimUnsupportedError):
        RasFim.inspect_model_scope(path)
    with pytest.raises(FimUnsupportedError, match='2D-only'):
        RasFim.validate_2d_model(path)


def test_geometry_hdf_detects_adjacent_text_and_explicit_override(tmp_path):
    path = scene(tmp_path, mesh=True)
    target = path.with_name('model.g01.hdf')
    path.rename(target)
    target.with_suffix('').write_text('Reach=Adjacent\n', encoding='utf-8')
    assert RasFim.inspect_model_scope(target).dimension == 'mixed_1d_2d'
    empty = tmp_path / 'explicit.g02'
    empty.write_text('Geom Title=2D\n', encoding='utf-8')
    scope = RasFim.inspect_model_scope(target, geom_path=empty)
    assert scope.dimension == '2d' and scope.geometry_path == empty.resolve()


@pytest.mark.parametrize('name', [b'\xff', 12])
def test_malformed_storage_names_raise_typed_scope_error(tmp_path, name):
    path = scene(tmp_path, mesh=True)
    with h5py.File(path, 'a') as source:
        dtype = [('Name', 'S16' if isinstance(name, bytes) else 'i4')]
        source.create_dataset('Geometry/Storage Areas/Attributes', data=np.array([(name,)], dtype=dtype))
    with pytest.raises(FimUnsupportedError, match='name'):
        RasFim.inspect_model_scope(path)
