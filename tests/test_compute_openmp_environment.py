"""Process-local Intel OpenMP compatibility without host environment changes."""
import inspect
import os
import pytest
from ras_commander import RasCmdr


def test_default_preserves_existing_environment():
    existing = {'PATH': 'private-wmic', 'KMP_AFFINITY': 'compact'}
    assert RasCmdr._openmp_subprocess_env(existing, False) is existing
    assert RasCmdr._openmp_subprocess_env(None, False) is None


def test_override_copies_and_preserves_wmic_path():
    existing = {'PATH': 'private-wmic', 'kmp_affinity': 'compact', 'OMP_NUM_THREADS': '1'}
    result = RasCmdr._openmp_subprocess_env(existing, True)
    assert result == {'PATH': 'private-wmic', 'OMP_NUM_THREADS': '1', 'KMP_AFFINITY': 'disabled'}
    assert existing['kmp_affinity'] == 'compact'


def test_inherited_environment_is_not_mutated(monkeypatch):
    monkeypatch.setenv('KMP_AFFINITY', 'compact')
    result = RasCmdr._openmp_subprocess_env(None, True)
    assert result['KMP_AFFINITY'] == 'disabled'
    assert os.environ['KMP_AFFINITY'] == 'compact'
    assert result['PATH'] == os.environ['PATH']


@pytest.mark.parametrize('invalid', [None, 0, 1, 'disabled', [], {}])
def test_rejects_non_bool_before_project_access(invalid):
    with pytest.raises(TypeError, match='disable_omp_affinity'):
        RasCmdr.compute_plan('01', disable_omp_affinity=invalid)
    with pytest.raises(TypeError, match='disable_omp_affinity'):
        RasCmdr._openmp_subprocess_env(None, invalid)


def test_launch_uses_merged_environment_and_records_override():
    source = inspect.getsource(RasCmdr.compute_plan)
    assert '_compute_env = RasCmdr._openmp_subprocess_env(' in source
    assert 'env=_compute_env' in source
    assert '"openmp_environment_overrides"' in source
    assert inspect.signature(RasCmdr.compute_plan).parameters['disable_omp_affinity'].default is False
