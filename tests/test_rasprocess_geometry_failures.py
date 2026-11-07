"""Explicit native failures must override otherwise complete geometry products."""
import importlib
import subprocess
from types import SimpleNamespace

import h5py
import numpy as np
import pytest
from ras_commander import RasProcess
from test_ras_geometry_compute_unit import _write_complete_2d_geometry

module = importlib.import_module('ras_commander.RasProcess')

@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
@pytest.mark.parametrize('message', ['Geometry Writer Failed', '  LAYER=Error', 'PROGRESS=-100', 'progress=-100.0', 'Error: invalid argument'])
def test_explicit_failure_overrides_exit_zero_and_complete_tables(tmp_path, monkeypatch, stream, message):
    geometry = _write_complete_2d_geometry(tmp_path/'model.g01.hdf')
    executable = tmp_path/'RasProcess.exe'
    executable.touch()
    monkeypatch.setattr(RasProcess, 'find_rasprocess', lambda *a: executable)
    monkeypatch.setattr(module, '_is_wine_helper_runtime', lambda: False)
    output = {'stdout':'Completed Writing Geometry', 'stderr':''}
    output[stream] = message + '\nCompleted Writing Geometry\n'
    monkeypatch.setattr(RasProcess, '_run_rasprocess', lambda *a, **k: SimpleNamespace(returncode=0, **output))
    result = RasProcess.compute_geometry(geometry, ras_version='7.0')
    assert result['semantic_validation']['success']
    assert not result['success']
    assert result['failure_lines'] == [message.strip()]

@pytest.mark.parametrize('value,expected', [
    (True, True), (False, False), (np.bytes_('True'), True), (np.bytes_('False'), False),
    (' true ', True), ('FALSE', False), (1, True), (0, False),
    ('unknown', False), (2, False), (np.nan, False), (np.array([True]), False),
])
def test_completion_attribute(tmp_path, value, expected):
    geometry = _write_complete_2d_geometry(tmp_path/'model.g01.hdf')
    with h5py.File(geometry, 'a') as hdf:
        hdf['Geometry'].attrs['Complete Geometry'] = value
    evidence = RasProcess._geometry_completion_semantics(geometry)
    assert evidence['success'] is expected
    assert evidence['complete_geometry_attribute_present']


def test_absent_attribute_retains_legacy_contract(tmp_path):
    geometry = _write_complete_2d_geometry(tmp_path/'model.g01.hdf')
    evidence = RasProcess._geometry_completion_semantics(geometry)
    assert evidence['success']
    assert evidence['complete_geometry'] is None
    assert not evidence['complete_geometry_attribute_present']


def test_true_attribute_does_not_replace_product_validation(tmp_path):
    geometry = _write_complete_2d_geometry(tmp_path/'model.g01.hdf', include_face_values=False)
    with h5py.File(geometry, 'a') as hdf:
        hdf['Geometry'].attrs['Complete Geometry'] = True
    assert not RasProcess._geometry_completion_semantics(geometry)['success']


def test_benign_text_is_not_a_failure():
    assert not RasProcess._geometry_completion_failures(
        'No errors\nError count: 0\nLAYER=Error Estimates\nPROGRESS=1\nGeometry Writer FailedCount=0')

@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_wine_fallback_cannot_hide_earlier_failure_outside_tail(tmp_path, monkeypatch, stream):
    geometry = tmp_path/'model.g01.hdf'
    geometry.write_bytes(b'old')
    clock = [0.]
    process = SimpleNamespace(pid=42, returncode=None, poll=lambda: None)
    def launch(command, **kwargs):
        kwargs[stream].write('Geometry Writer Failed\n' + 'progress detail\n'*6000)
        kwargs[stream].flush()
        kwargs['stdout'].write('Completed Writing Geometry\n')
        kwargs['stdout'].flush()
        geometry.write_bytes(b'new geometry products')
        return process
    def cleanup(owned):
        owned.returncode=15
        owned.poll=lambda: 15
        return {'survivor_pids':[]}
    monkeypatch.setattr(module, 'IS_LINUX', False)
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    monkeypatch.setattr(module.time, 'monotonic', lambda:clock[0])
    monkeypatch.setattr(module.time, 'sleep', lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    monkeypatch.setattr(RasProcess, '_geometry_completion_semantics', lambda path:{'success':True})
    monkeypatch.setattr(RasProcess, '_terminate_owned_process_tree', cleanup)
    with pytest.raises(subprocess.TimeoutExpired):
        RasProcess._run_complete_geometry_supervised(tmp_path/'RasProcess.exe', ['CompleteGeometry'], geometry,
            timeout=5, working_dir=tmp_path, semantic_stable_seconds=1)
    assert clock[0]>=5
