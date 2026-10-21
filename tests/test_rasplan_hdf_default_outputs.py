"""Default 2D results remain accepted through additional-output authoring APIs."""

import ast
import json
import logging
from pathlib import Path

import pytest

from ras_commander import RasPlan


class _Context:
    def check_initialized(self):
        pass


def _plan(tmp_path):
    path = tmp_path / 'Project.p01'
    path.write_text('Plan Title=Defaults\nProgram Version=6.60\nCalibration Method=0\n')
    assert RasPlan.apply_hdf_output_profile(path, ras_object=_Context())
    return path


def _enable(path, method, labels):
    context = _Context()
    if method == 'add':
        return all(RasPlan.add_hdf_output_variable(path, label, ras_object=context) for label in labels)
    if method == 'enable':
        return all(RasPlan.enable_hdf_output_variable(path, label, ras_object=context) for label in labels)
    if method == 'set_one':
        return all(RasPlan.set_hdf_output_variable(path, label, ras_object=context) for label in labels)
    if method == 'set_many':
        return RasPlan.set_hdf_output_variables(path, labels, ras_object=context)
    if method == 'profile':
        return RasPlan.apply_hdf_output_profile(path, additional_variables=labels, ras_object=context)
    if method == 'optimal':
        return RasPlan.use_optimal_hdf_settings(path, additional_variables=labels, ras_object=context)
    raise AssertionError(method)


@pytest.mark.parametrize('default', ['Water Surface', 'Face Velocity'])
@pytest.mark.parametrize('method', ['add', 'enable', 'set_one', 'set_many', 'profile', 'optimal'])
@pytest.mark.parametrize('existing', [False, True])
def test_default_requests_are_noops(tmp_path, caplog, default, method, existing):
    path = _plan(tmp_path)
    if existing:
        with path.open('a') as file:
            file.write(f'HDF Additional Output Variable={default}\n')
    before = path.read_bytes()
    with caplog.at_level(logging.INFO, logger='ras_commander.RasPlan'):
        assert _enable(path, method, [default])
    assert path.read_bytes() == before
    assert default not in RasPlan.list_available_hdf_output_variables()
    assert any(record.levelno == logging.INFO and default in record.getMessage()
               and 'always written' in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize('method', ['set_many', 'profile', 'optimal'])
def test_unknown_after_defaults_still_rejects_without_writes(tmp_path, method):
    path = _plan(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='Unknown HDF output variable'):
        _enable(path, method, ['Water Surface', 'Face Velocity', 'Unknown Variable'])
    assert path.read_bytes() == before


@pytest.mark.parametrize('notebook,index,variable', [
    ('412_2d_detail_face_data_extraction.ipynb', 63, 'reference_line_output_variables'),
    ('728_extend_gridded_dss_forcing_window.ipynb', 13, None),
    ('914_historical_event_validation.ipynb', 13, None),
    ('916_hrrr_precipitation_forecast.ipynb', 15, 'hdf_output_variables'),
    ('917_mrms_precipitation_qpe.ipynb', 8, 'hdf_output_variables'),
    ('926_wpc_qpf_precipitation_forecast.ipynb', 15, 'hdf_output_variables'),
])
def test_notebook_authoring_requests(tmp_path, notebook, index, variable):
    source = Path(__file__).resolve().parents[1] / 'examples' / notebook
    cell = json.loads(source.read_text(encoding='utf-8'))['cells'][index]
    tree = ast.parse(''.join(cell['source']))
    if variable:
        value = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets))
    else:
        value = next(node.value for node in ast.walk(tree)
                     if isinstance(node, ast.keyword) and node.arg == 'hdf_output_variables')
    labels = ast.literal_eval(value)
    path = _plan(tmp_path)
    method = 'add' if notebook.startswith('412') else 'optimal'
    optional = [label for label in labels if label not in {'Water Surface', 'Face Velocity'}]
    assert _enable(path, method, optional)
    before = path.read_bytes()
    assert _enable(path, method, labels)
    assert path.read_bytes() == before
    assert RasPlan.get_hdf_output_variables(path, ras_object=_Context()) == optional
