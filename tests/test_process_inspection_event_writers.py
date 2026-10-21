"""Only complete fixed-position event writer signatures bind to one plan."""
from dataclasses import replace
from pathlib import Path

import pytest

from ras_commander.ComputeResults import RasProcessInventory, RasProcessRecord
from ras_commander._process_inspection import match_plan_processes

TMP = 'C:/Models/Dam.p06.tmp.hdf'
EXE = 'C:/HEC/6.2/RasProcess.exe'


def _match(command, **kwargs):
    record = RasProcessRecord(
        pid=42, create_time=1000.0, name='RasProcess.exe',
        executable_path=EXE, working_directory='C:/Models',
        command_line=tuple(command),
    )
    record = replace(record, **kwargs)
    inventory = RasProcessInventory(observed_at=1001.0, complete=True, processes=(record,), query_errors=())
    return match_plan_processes(
        inventory, plan_number='06', project_path=Path('C:/Models/Dam.prj'),
        plan_path=Path('C:/Models/Dam.p06'), tmp_hdf_path=Path(TMP),
    )


@pytest.mark.parametrize('action', ['CompletePreProcess', 'CompleteEventConditions'])
@pytest.mark.parametrize('tail', [[], ['Units=US Customary'], ['Units=US', 'Customary']])
def test_exact_observed_writer_signature_is_matched(action, tail):
    result = _match([EXE, action, TMP, *tail])
    assert result.complete is True
    assert [p.pid for p in result.matched] == [42]
    # A recognized writer remains active; it is never a quiescent inventory.
    assert result.matched[0].create_time == 1000.0


@pytest.mark.parametrize('command', [
    [EXE, 'GenerateMesh', TMP],
    [EXE, TMP, 'CompleteEventConditions'],
    [EXE, 'CompleteEventConditions', TMP, 'extra'],
    [EXE, 'CompleteEventConditions', TMP, 'Units=SI'],
    [EXE, 'CompleteEventConditions', TMP, 'Units=US Customary', 'extra'],
    [EXE, 'CompleteEventConditions', TMP, 'Units=US', 'Customary', 'extra'],
    [EXE, 'CompleteEventConditions', TMP, TMP],
    [EXE, 'CompleteEventConditions', 'C:/Models/Dam.p06', TMP],
    ['C:/Other/RasProcess.exe', 'CompleteEventConditions', TMP],
    ['C:/HEC/6.2/Other.exe', 'CompleteEventConditions', TMP],
])
def test_exact_artifact_with_unproven_signature_still_blocks_inventory(command):
    result = _match(command)
    assert result.complete is False and result.matched == ()
    assert result.query_errors[0].reason_code == 'plan_process_signature_unsupported'


def test_writer_for_different_exact_plan_is_not_selected():
    result = _match([EXE, 'CompleteEventConditions', 'C:/Models/Dam.p07.tmp.hdf'])
    assert result.complete is True and result.matched == ()


def test_similar_basename_is_never_sufficient():
    result = _match([EXE, 'CompleteEventConditions', 'C:/Other/Dam.p06.tmp.hdf'])
    assert result.complete is True and result.matched == ()


def test_relative_executable_and_target_require_exact_cwd_binding():
    result = _match(['RasProcess.exe', 'CompleteEventConditions', TMP], working_directory='C:/HEC/6.2')
    assert result.complete is True and len(result.matched) == 1


def test_missing_executable_metadata_still_requires_rasprocess_name_in_command():
    result = _match(['C:/Other/Other.exe', 'CompleteEventConditions', TMP], executable_path=None)
    assert result.complete is False and result.matched == ()


def test_unknown_engine_does_not_inherit_event_writer_signature():
    result = _match([EXE, 'CompleteEventConditions', TMP], name='RasGeomPreprocess.exe')
    assert result.complete is False and result.matched == ()
