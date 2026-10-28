"""A06: bulk boundary logs, with explicit hot-accessor exceptions."""
import ast
import inspect
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ras_commander.fast_text import GeometryTextIndex

ROOT = Path(__file__).resolve().parents[2]


def test_hot_accessors_are_explicit_and_stateful():
    # These accesses run per geometry node inside already-logged bulk APIs.
    assert 'lightweight state accessors' in GeometryTextIndex.__doc__
    index = GeometryTextIndex(None, 'sha', None, None,
        pd.DataFrame({'River': ['R'], 'Reach': ['A'], 'RS': ['1']}),
        pd.DataFrame(), pd.DataFrame(), 0,
        {'station_elevation': {'status': [1], 'offsets': [0, 2],
                               'values': np.array([[0., 1.], [2., 3.]])},
         'mannings_n': {'status': [0]},
         'bank_stations': {'status': [1], 'values': [[0.5, 1.5]]}})
    assert index.find_node('R', 'A', '1') == 0
    assert index.find_node('R', 'A', 'missing') is None
    np.testing.assert_array_equal(index.station_elevation(0), [[0., 1.], [2., 3.]])
    assert index.mannings_n(0) is None and index.bank_stations(0) == (0.5, 1.5)
    for name in ('find_node', 'station_elevation', 'mannings_n', 'bank_stations'):
        assert not hasattr(getattr(GeometryTextIndex, name), '__wrapped__')


def test_analysis_bulk_boundary_keeps_signature_and_logs_once(caplog):
    from ras_commander.hdf.HdfFluvialNative import Analysis, NATIVE_CALLS

    class NativeSnapshot:
        def qualifying_edges(self, delta):
            assert delta == 100
            return [(0, 1)]

    analysis = Analysis()
    analysis.native = NativeSnapshot()
    before = NATIVE_CALLS['NativeAnalysis.qualifying_edges']
    assert str(inspect.signature(analysis.qualifying_edges)) == '(delta_t_ms)'
    with caplog.at_level(logging.DEBUG, logger=Analysis.__module__):
        assert analysis.qualifying_edges(100) == [(0, 1)]
    assert NATIVE_CALLS['NativeAnalysis.qualifying_edges'] == before + 1
    messages = [r.getMessage() for r in caplog.records if r.name == Analysis.__module__]
    assert len(messages) == 2 and all('qualifying_edges' in m for m in messages)
    assert not any('(0, 1)' in m for m in messages)


def test_scalar_time_conversion_is_hot_exception_and_keeps_policy():
    from ras_commander.hdf.HdfFluvialNative import integer_milliseconds
    import pytest
    assert 'per-cell loops' in integer_milliseconds.__doc__
    assert not hasattr(integer_milliseconds, '__wrapped__')
    assert integer_milliseconds(pd.Timestamp('3000-01-01T00:00:00.001')) == (32503680000001, True)
    assert integer_milliseconds(pd.NaT) == (0, False)
    with pytest.raises(ValueError, match='timezone-naive'):
        integer_milliseconds(pd.Timestamp('2020-01-01', tz='UTC'))
    with pytest.raises(ValueError, match='sub-millisecond'):
        integer_milliseconds(pd.Timestamp('2020-01-01T00:00:00.000000001'))


def test_six_audited_helpers_have_explicit_boundary_decisions():
    text = ast.parse((ROOT / 'ras_commander/fast_text.py').read_text(encoding='utf-8'))
    cls = next(n for n in text.body if isinstance(n, ast.ClassDef) and n.name == 'GeometryTextIndex')
    assert 'not decorated' in ast.get_docstring(cls)
    fluvial = ast.parse((ROOT / 'ras_commander/hdf/HdfFluvialNative.py').read_text(encoding='utf-8'))
    scalar = next(n for n in fluvial.body if isinstance(n, ast.FunctionDef) and n.name == 'integer_milliseconds')
    assert 'intentionally no' in ast.get_docstring(scalar)
    cls = next(n for n in fluvial.body if isinstance(n, ast.ClassDef) and n.name == 'Analysis')
    bulk = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'qualifying_edges')
    assert [ast.unparse(d) for d in bulk.decorator_list] == ['log_call']
