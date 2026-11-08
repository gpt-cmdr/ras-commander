"""Coupled capability, prepared selection and real HDF axis contracts.

These use synthetic HDF metadata and local inert engine files. No native engine
or solver runs, and no numerical qualification follows from these tests.
"""
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from ras_commander import HdfMesh, HdfResultsMesh
from ras_commander.fim import FimEngineError, FimUnsupportedError, RasFim
from ras_commander.fim import _coupled, _engine
from test_fim_coupled import _prep_environment, files, one_d_files  # noqa: F401

BASE = 'Results/Unsteady/Output/Output Blocks/Base Output/'
SERIES = BASE + 'Unsteady Time Series/'
XS_MAX = BASE + 'Summary Output/Cross Sections/Maximum Water Surface'
MESH_MAX = BASE + 'Summary Output/2D Flow Areas/mesh/Maximum Water Surface'


def capabilities():
    methods = {}
    for key, method, schema in (
        ('one_d_clipped_diagnostic', _coupled.XS_METHOD_ID, _coupled.XS_SCHEMA),
        ('sloping', _coupled.TWO_D_METHOD, _coupled.TWO_D_SCHEMA),
        ('coupled_diagnostic', _coupled.METHOD_ID, _coupled.REQUEST_SCHEMA),
    ):
        methods[key] = SimpleNamespace(method_id=method, request_schemas=(schema,), flags={})
    methods['sloping'].flags['export_physical_ownership'] = True
    return SimpleNamespace(methods=methods, raw_record={'engine': {'version': 'test'}})


@pytest.mark.parametrize('key', ['one_d_clipped_diagnostic', 'sloping', 'coupled_diagnostic'])
@pytest.mark.parametrize('failure', ['missing', 'method', 'schema'])
def test_real_engine_contract_rejects_missing_or_mismatched_components(tmp_path, monkeypatch, key, failure):
    engine = tmp_path/'engine.exe'
    engine.write_bytes(b'inert artifact')
    caps = capabilities()
    if failure == 'missing':
        del caps.methods[key]
    elif failure == 'method':
        caps.methods[key].method_id = 'different-method/1'
    else:
        caps.methods[key].request_schemas = ('different-schema/1',)
    monkeypatch.setattr(_engine, 'find_engine', lambda _: engine)
    monkeypatch.setattr(RasFim, 'get_capabilities', lambda _: caps)
    with pytest.raises(FimUnsupportedError, match='component contract: '+key):
        _coupled._require_engine(engine)


@pytest.mark.parametrize('flag', [None, False, 1, 'true'])
def test_real_engine_contract_requires_boolean_physical_ownership_capability(tmp_path, monkeypatch, flag):
    engine = tmp_path/'engine.exe'
    engine.write_bytes(b'inert artifact')
    caps = capabilities()
    if flag is None:
        caps.methods['sloping'].flags.clear()
    else:
        caps.methods['sloping'].flags['export_physical_ownership'] = flag
    monkeypatch.setattr(_engine, 'find_engine', lambda _: engine)
    monkeypatch.setattr(RasFim, 'get_capabilities', lambda _: caps)
    with pytest.raises(FimUnsupportedError, match='export_physical_ownership'):
        _coupled._require_engine(engine)


def test_real_engine_contract_rejects_artifact_changed_during_discovery(tmp_path, monkeypatch):
    engine = tmp_path/'engine.exe'
    engine.write_bytes(b'first artifact')
    monkeypatch.setattr(_engine, 'find_engine', lambda _: engine)
    def discover(_):
        engine.write_bytes(b'replaced artifact')
        return capabilities()
    monkeypatch.setattr(RasFim, 'get_capabilities', discover)
    with pytest.raises(FimEngineError, match='changed during capability discovery'):
        _coupled._require_engine(engine)


def test_real_engine_contract_accepts_exact_advertised_components_without_execution(tmp_path, monkeypatch):
    engine = tmp_path/'engine.exe'
    engine.write_bytes(b'inert artifact')
    caps = capabilities()
    monkeypatch.setattr(_engine, 'find_engine', lambda _: engine)
    monkeypatch.setattr(RasFim, 'get_capabilities', lambda _: caps)
    monkeypatch.setattr(_engine, 'run_engine', lambda *a, **k: pytest.fail('contract discovery executed a process'))
    assert _coupled._require_engine(engine) == (engine, caps)


def prepare(files, tmp_path, monkeypatch):
    engine = _prep_environment(tmp_path, monkeypatch)
    model = RasFim.prepare_coupled_model(*files, tmp_path/'prepared',
        profiles={'first': 0, 'second': 1}, allow_unqualified=True, max_working_mib=64)
    monkeypatch.setattr(_coupled, '_require_engine', lambda _: (engine.resolve(), capabilities()))
    monkeypatch.setattr(_engine, 'terrain_identity', lambda *a, **k:
        {'epsg': 6588, 'crs_identity': {'kind': 'epsg'}})
    monkeypatch.setattr(_engine, 'run_engine', lambda *a, **k: pytest.fail('contract refusal executed a process'))
    return model, engine


def test_prepared_mapping_default_gate_precedes_engine_lookup_or_outputs(files, tmp_path, monkeypatch):
    prepared, _ = prepare(files, tmp_path, monkeypatch)
    monkeypatch.setattr(_coupled, '_require_engine', lambda *a, **k: pytest.fail('engine lookup before default gate'))
    with pytest.raises(FimUnsupportedError, match='unqualified'):
        prepared.map_profiles(tmp_path/'products')
    assert not (tmp_path/'products').exists()


@pytest.mark.parametrize(('profiles', 'error', 'message'), [
    (['missing'], ValueError, 'not prepared'),
    (['first', 'first'], ValueError, 'unique prepared names'),
    ([], ValueError, 'unique prepared names'),
    ({'new-name': 0}, TypeError, 'names, not selectors'),
    ([0], ValueError, 'unique prepared names'),
])
def test_prepared_mapping_rejects_unknown_duplicate_or_selector_profiles(files, tmp_path, monkeypatch, profiles, error, message):
    prepared, _ = prepare(files, tmp_path, monkeypatch)
    with pytest.raises(error, match=message):
        prepared.map_profiles(tmp_path/'products', profiles=profiles, allow_unqualified=True)
    assert not (tmp_path/'products').exists()


def test_prepared_mapping_rejects_changed_engine_hash(files, tmp_path, monkeypatch):
    prepared, engine = prepare(files, tmp_path, monkeypatch)
    engine.write_bytes(b'changed after preparation')
    with pytest.raises(FimUnsupportedError, match='changed'):
        prepared.map_profiles(tmp_path/'products', allow_unqualified=True)
    assert not (tmp_path/'products').exists()


def test_prepared_mapping_rejects_different_engine_path_even_with_same_bytes(files, tmp_path, monkeypatch):
    prepared, engine = prepare(files, tmp_path, monkeypatch)
    alternate = tmp_path/'other-engine.exe'
    alternate.write_bytes(engine.read_bytes())
    monkeypatch.setattr(_coupled, '_require_engine', lambda _: (alternate.resolve(), capabilities()))
    with pytest.raises(FimUnsupportedError, match='differs from the prepared engine'):
        prepared.map_profiles(tmp_path/'products', allow_unqualified=True)
    assert not (tmp_path/'products').exists()


@pytest.mark.parametrize('options', [
    {'threads': 65}, {'timeout': 0}, {'timeout': -1}, {'timeout': float('nan')},
    {'timeout': float('inf')}, {'timeout': True},
])
def test_mapping_resource_validation_precedes_engine_or_outputs(tmp_path, monkeypatch, options):
    monkeypatch.setattr(_coupled, '_require_engine', lambda *a, **k: pytest.fail('engine lookup before option refusal'))
    with pytest.raises(ValueError, match='threads|timeout'):
        RasFim.map_coupled_profiles('missing.hdf', 'missing.tif', tmp_path/'products',
                                    allow_unqualified=True, **options)
    assert not (tmp_path/'products').exists()


@pytest.fixture
def alignment_file(tmp_path, monkeypatch):
    path = tmp_path/'alignment.hdf'
    with h5py.File(path, 'w') as source:
        source.create_dataset(SERIES+'Time Date Stamp', data=np.array([
            b'01JAN2000 00:00:00', b'01JAN2000 01:00:00', b'01JAN2000 02:00:00']))
        source.create_dataset(SERIES+'Cross Sections/Water Surface', shape=(3, 2), dtype='f4')
        source.create_dataset(SERIES+'2D Flow Areas/mesh/Water Surface', shape=(3, 4), dtype='f4')
    monkeypatch.setattr(HdfMesh, 'get_mesh_area_names', lambda _: ['mesh'])
    monkeypatch.setattr(HdfResultsMesh, 'get_mesh_timeseries', lambda *a, **k:
        SimpleNamespace(dataset_path='/'+SERIES+'2D Flow Areas/mesh/Water Surface'))
    return path


def test_real_alignment_saved_indices_preserve_identity_order_and_need_no_max_summary(alignment_file):
    result = _coupled._alignment(alignment_file, [2, 0, 2])
    assert result['selected'] == ['01JAN2000 02:00:00', '01JAN2000 00:00:00', '01JAN2000 02:00:00']
    assert result['components']['xs']['shape'] == [3, 2]
    assert result['components']['mesh']['shape'] == [3, 4]
    assert 'maximum' not in result['components']['xs']


@pytest.mark.parametrize('xs_shape', [(2,), (1, 2), (2, 2)])
def test_real_alignment_explicit_max_binds_complete_native_summary_axes(alignment_file, xs_shape):
    with h5py.File(alignment_file, 'a') as source:
        source.create_dataset(XS_MAX, shape=xs_shape, dtype='f4')
        # Two rows: native mesh maxima plus per-cell time-of-maximum metadata.
        source.create_dataset(MESH_MAX, shape=(2, 4), dtype='f4')
    result = _coupled._alignment(alignment_file, ['Max', 1])
    assert result['selected'] == ['Max', '01JAN2000 01:00:00']
    assert result['components']['xs']['maximum']['shape'] == list(xs_shape)
    assert result['components']['mesh']['maximum']['shape'] == [2, 4]
    assert result['components']['xs']['maximum']['dataset'].lstrip('/') == XS_MAX
    assert result['components']['mesh']['maximum']['dataset'].lstrip('/') == MESH_MAX


@pytest.mark.parametrize('case', ['missing_xs', 'missing_mesh', 'xs_columns', 'xs_empty', 'mesh_columns', 'mesh_rows'])
def test_real_alignment_max_refuses_absent_or_misaligned_summary(alignment_file, case):
    with h5py.File(alignment_file, 'a') as source:
        if case != 'missing_xs':
            source.create_dataset(XS_MAX, shape=(0, 2) if case == 'xs_empty' else (1, 3) if case == 'xs_columns' else (1, 2), dtype='f4')
        if case != 'missing_mesh':
            source.create_dataset(MESH_MAX, shape=(1, 4) if case == 'mesh_rows' else (2, 3) if case == 'mesh_columns' else (2, 4), dtype='f4')
    with pytest.raises(FimUnsupportedError, match='Max|maximum|summary'):
        _coupled._alignment(alignment_file, ['Max'])


@pytest.mark.parametrize('case', ['steady', 'missing_axis', 'duplicate_axis', 'mesh_rows', 'other_output_block'])
def test_real_alignment_refuses_ambiguous_or_mismatched_time_axes(alignment_file, monkeypatch, case):
    with h5py.File(alignment_file, 'a') as source:
        if case == 'steady':
            source.create_group('Results/Steady')
        elif case == 'missing_axis':
            del source[SERIES+'Time Date Stamp']
        elif case == 'duplicate_axis':
            source[SERIES+'Time Date Stamp'][1] = source[SERIES+'Time Date Stamp'][0]
        elif case == 'mesh_rows':
            del source[SERIES+'2D Flow Areas/mesh/Water Surface']
            source.create_dataset(SERIES+'2D Flow Areas/mesh/Water Surface', shape=(2, 4), dtype='f4')
        else:
            other = 'Results/Unsteady/Output/Output Blocks/Other Output/Unsteady Time Series/2D Flow Areas/mesh/Water Surface'
            source.create_dataset(other, shape=(3, 4), dtype='f4')
            monkeypatch.setattr(HdfResultsMesh, 'get_mesh_timeseries', lambda *a, **k: SimpleNamespace(dataset_path=other))
    with pytest.raises(FimUnsupportedError):
        _coupled._alignment(alignment_file, [1])
