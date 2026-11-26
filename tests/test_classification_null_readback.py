"""Regression coverage for native DataRow null parameter readback."""
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from ras_commander import _landcover_native as native


@pytest.mark.parametrize(
    'requested,saved,accepted',
    [(-9999.0, None, True), (77.0, None, False),
     (-9999.0, 0.0, False), (-9999.0, -9999.0, True)],
)
def test_null_readback_only_matches_explicit_unset(
    tmp_path, monkeypatch, requested, saved, accepted,
):
    path = tmp_path / 'Infiltration.hdf'
    path.write_bytes(b'original')

    class Row(dict):
        def __getitem__(self, column):
            if isinstance(column, int):
                column = ['Name', 'Curve Number'][column]
            return super().__getitem__(column)

        def IsNull(self, column):
            return self[column] is None

    class Columns:
        Count = 2

        def __getitem__(self, index):
            return SimpleNamespace(ColumnName=['Name', 'Curve Number'][index])

    tables = [
        SimpleNamespace(Columns=Columns(), Rows=[Row(Name='A', **{'Curve Number': 75.0})]),
        SimpleNamespace(Columns=Columns(), Rows=[Row(Name='A', **{'Curve Number': saved})]),
    ]

    class Layer:
        Classification = object()
        Parameters = object()

        def TryAssigningNewParamtersUsingTable(self, table, apply):
            path.write_bytes(b'native save')
            return True

    class LandCoverLayer:
        LandCoverType = SimpleNamespace(InfiltrationSCSCurveNumber=object())

        @staticmethod
        def TryLoadLayer(*args):
            return True, Layer(), ''

        @staticmethod
        def GetClassificationVariablesAsDataTable(*args):
            return tables.pop(0)

    monkeypatch.setattr(native, 'find_hecras_install', lambda version: tmp_path)
    monkeypatch.setattr(native, 'load_clr', lambda install: None)
    monkeypatch.setitem(sys.modules, 'RasMapperLib', SimpleNamespace(LandCoverLayer=LandCoverLayer))
    updates = pd.DataFrame({'Name': ['A'], 'Curve Number': [requested]})
    if accepted:
        result = native.set_classification_parameters(
            path, updates, layer_type='infiltration_scs', hecras_version='7.0.1',
        )
        assert result['Curve Number'].iloc[0] == requested
        assert path.read_bytes() == b'native save'
    else:
        with pytest.raises(RuntimeError, match='did not persist'):
            native.set_classification_parameters(
                path, updates, layer_type='infiltration_scs', hecras_version='7.0.1',
            )
        assert path.read_bytes() == b'original'
