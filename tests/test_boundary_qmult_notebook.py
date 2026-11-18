"""Failure injection against notebook 312's actual computational gates (not hydraulic validation)."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

NB = json.loads((Path(__file__).parents[1] / 'examples/312_boundary_df_qmult_dss_paths.ipynb').read_text(encoding='utf-8'))


def source(index):
    return ''.join(NB['cells'][index]['source'])


def gates():
    tree = ast.parse(source(29))
    functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[])
    scope = {'np': np}
    exec(compile(functions, '<312 gates>', 'exec'), scope)
    return scope


@pytest.mark.parametrize('actual', [[], [1], [1, 3], [1, np.nan]])
def test_readback_rejects_incomplete_changed_or_nonfinite_values(actual):
    with pytest.raises(AssertionError):
        gates()['_require_values'](actual, [1, 2])


def test_setter_and_readback_positive_and_negative():
    scope = gates()
    scope['_require_setter'](True)
    scope['_require_values']([1, 2], [1, 2])
    with pytest.raises(AssertionError):
        scope['_require_setter'](False)


def dataset(xs=('a', 'b')):
    return xr.Dataset({'Water_Surface': (('time', 'cross_section'), np.ones((2, len(xs))))}, coords={'time': [0, 1], 'cross_section': list(xs)})


@pytest.mark.parametrize('case', ['mismatch', 'empty', 'missing', 'nonfinite'])
def test_exact_results_failure(case):
    left, right = dataset(), dataset()
    if case == 'mismatch':
        right = dataset(('a', 'c'))
    elif case == 'empty':
        left = right = dataset(())
    elif case == 'missing':
        right = right.drop_vars('Water_Surface')
    else:
        right['Water_Surface'][0, 0] = np.nan
    with pytest.raises((AssertionError, ValueError)):
        gates()['_exact_results'](left, right, ['Water_Surface'])


def test_exact_results_positive():
    gates()['_exact_results'](dataset(), dataset(), ['Water_Surface'])


@pytest.mark.parametrize('index,scope', [
    (33, dict(all_match=False, coords_ok=True, dss_roundtrip_ok=True)),
    (33, dict(all_match=True, coords_ok=True, dss_roundtrip_ok=False)),
    (36, dict(all_lower=False, coords_ok=True)),
    (36, dict(all_lower=True, coords_ok=False)),
])
def test_actual_final_verdict_requires_success(index, scope):
    checks = [n for n in ast.parse(source(index)).body if isinstance(n, ast.Assert)]
    with pytest.raises(AssertionError):
        exec(compile(ast.Module(body=checks, type_ignores=[]), '<312 verdict>', 'exec'), scope)


@pytest.mark.parametrize('value', [None, 1.0, 0.0])
def test_actual_qmult_readback_gate(value):
    check = next(n for n in ast.parse(source(35)).body if isinstance(n, ast.Assert))
    with pytest.raises((AssertionError, TypeError)):
        exec(compile(ast.Module(body=[check], type_ignores=[]), '<312 QMult>', 'exec'), dict(qm_val=value, QMULT_VALUE=0.5))

@pytest.mark.parametrize('change', ['shift', 'count', 'none'])
def test_actual_dss_timestamp_gate(change):
    tree = ast.parse(source(30))
    transition = next(n for n in tree.body if isinstance(n, ast.Try))
    check = next(n for n in transition.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == 'assert_index_equal')
    index = pd.date_range('1900-01-01', periods=2, freq='h')
    if change == 'shift':
        index += pd.Timedelta(hours=1)
    elif change == 'count':
        index = index[:1]
    scope = dict(pd=pd, dss_df=pd.DataFrame(index=index), original_values=[1, 2])
    code = compile(ast.Module(body=[check], type_ignores=[]), '<312 time gate>', 'exec')
    if change == 'none':
        exec(code, scope)
    else:
        with pytest.raises(AssertionError):
            exec(code, scope)

@pytest.mark.parametrize('fault', ['write', 'to_dss', 'to_inline', 'readback', 'none'])
def test_actual_transition_control_flow(tmp_path, fault):
    """Run the unmodified cell with controlled I/O, retaining all production gates."""
    state = {'dss': False, 'values': np.array([1., 2.]), 'cleanup': 0}
    location = dict(river='White', reach='Muncie', station='15696.24')

    def inline(*args, **kwargs):
        if state['dss']:
            return pd.DataFrame(columns=[*location, 'values'])
        return pd.DataFrame([{**location, 'values': state['values']}])

    def to_dss(**kwargs):
        state['dss'] = True
        return fault != 'to_dss'

    def to_inline(**kwargs):
        state['cleanup'] += 1
        state['dss'] = False
        state['values'] = kwargs['hydrograph_df']['value'].to_numpy()
        return fault != 'to_inline'

    def write(**kwargs):
        if fault == 'write':
            raise RuntimeError('injected DSS write failure')

    def read(*args):
        values = [1., 3.] if fault == 'readback' else [1., 2.]
        return pd.DataFrame({'value': values}, index=pd.date_range('1900-01-01', periods=2, freq='h'))

    def project(*args):
        row = {'unsteady_number': '01', 'river_reach_name': 'White', 'river_station': 'Muncie',
               'storage_area_name': '15696.24', 'Use DSS': str(state['dss']),
               'DSS File': '.\\Muncie_Flows.dss', 'DSS Path': '//MUNCIE INFLOW/FLOW/01JAN1900/1HOUR/RUN:BASELINE/'}
        return SimpleNamespace(unsteady_df=pd.DataFrame({'full_path': ['test.u01']}), boundaries_df=pd.DataFrame([row]))

    import ras_commander
    from unittest.mock import patch
    dss = SimpleNamespace(write_timeseries=write, get_file_version=lambda *a: 7, read_timeseries=read)
    scope = gates()
    scope.update(pd=pd, Path=Path, init_ras_project=project, roundtrip_path=tmp_path, RAS_VERSION='7.0',
                 original_values=np.array([1., 2.]), inline_bcs=inline(),
                 RasUnsteady=SimpleNamespace(set_boundary_dss_link=to_dss, set_boundary_inline_hydrograph=to_inline,
                                             get_inline_hydrograph_boundaries=inline),
                 river=location['river'], reach=location['reach'], station_loc=location['station'])
    with patch.object(ras_commander, 'RasDss', dss):
        if fault == 'none':
            exec(compile(source(30), '<312 actual transition>', 'exec'), scope)
            assert scope['dss_roundtrip_ok']
        else:
            with pytest.raises((AssertionError, RuntimeError)):
                exec(compile(source(30), '<312 actual transition>', 'exec'), scope)
            assert not scope['dss_roundtrip_ok']
            assert state['cleanup'] > 0

@pytest.mark.parametrize('index,ras_name', [(29, 'ras_baseline'), (32, 'ras_roundtrip'), (35, 'ras_qmult')])
def test_actual_compute_gate_rejects_false(index, ras_name):
    check = next(n for n in ast.parse(source(index)).body if isinstance(n, ast.Assert)
                 and isinstance(n.test, ast.Call) and isinstance(n.test.func, ast.Attribute)
                 and n.test.func.attr == 'compute_plan')
    scope = {ras_name: object(), 'RasCmdr': SimpleNamespace(compute_plan=lambda *a, **k: False)}
    with pytest.raises(AssertionError, match='compute failed'):
        exec(compile(ast.Module(body=[check], type_ignores=[]), '<312 compute gate>', 'exec'), scope)
