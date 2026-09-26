"""Diagnostic contract tests, not hydraulic solver qualification.

Numerical rows below isolate threshold boundaries; actual Example 6 input/HDF
inspection is recorded separately in the R05 triage evidence.
"""
import ast
import inspect
import re
from pathlib import Path

import h5py
import pandas as pd
import pytest

from ras_commander import HdfResultsPlan
from ras_commander.check import RasCheck
from ras_commander.check.check_floodways import CheckFloodways
from ras_commander.check.messages import get_message_template, get_help_text
from ras_commander.check.thresholds import get_default_thresholds


@pytest.fixture
def empty_hdf(tmp_path):
    path = tmp_path / "empty.hdf"
    with h5py.File(path, "w"):
        pass
    return path


def profiles(surcharge):
    return pd.DataFrame([
        dict(profile="Base", river="River", reach="Reach", node_id="5.0", wsel=100.0, flow=14000.0),
        dict(profile="Floodway", river="River", reach="Reach", node_id="5.0", wsel=100.0 + surcharge, flow=14000.0),
    ])


@pytest.mark.parametrize("surcharge, expected", [
    (1.02, {"FW_SC_01": "ERROR"}),
    (1.004, {"FW_SC_01": "ERROR", "FW_SC_04": "INFO"}),
    (0.995, {"FW_SC_04": "INFO"}),
    (-0.02, {"FW_SC_02": "WARNING"}),
    (-0.006, {}),
    (0.004, {"FW_SC_03": "INFO"}),
    (0.02, {}),
])
def test_public_surcharge_messages_and_rendering(monkeypatch, empty_hdf, surcharge, expected):
    monkeypatch.setattr(HdfResultsPlan, "get_steady_results", lambda _: profiles(surcharge))
    result = RasCheck.check_floodways(empty_hdf, empty_hdf, "Base", "Floodway", surcharge=1.0)
    messages = [m for m in result.messages if m.message_id.startswith("FW_SC_")]
    assert {m.message_id: m.severity.value for m in messages} == expected
    assert len(result.floodway_summary) == 1
    for message in messages:
        assert "{station}" not in message.message
        assert "5.0" in message.message
        assert "{" not in message.message


@pytest.mark.parametrize("method", [1, 4, 5])
def test_method_specific_boundary_message_does_not_invent_targets(monkeypatch, empty_hdf, method):
    # Inject parsed metadata solely to exercise a currently unqualified branch.
    encroachments = pd.DataFrame([dict(
        river="River", reach="Reach", station="5.0", encr_method=method,
        encr_sta_l=20.0, encr_sta_r=80.0,
    )])
    monkeypatch.setattr(CheckFloodways, "_get_encroachment_stations", lambda *args: encroachments)
    messages = CheckFloodways._check_floodway_starting_wse(
        empty_hdf, profiles(1.0), empty_hdf, "Base", "Floodway", get_default_thresholds(),
    )
    message = next(m for m in messages if m.message_id == f"FW_SW_02M{method}")
    assert message.severity.value == "WARNING"
    assert "{" not in message.message
    assert "width reduction" not in message.message.lower()
    assert "50%" not in message.message
    if method == 5:
        assert "maximum energy change" in message.message
    if method == 4:
        assert "iterates to achieve" not in get_help_text(message.message_id)


def test_missing_parameters_are_unknown(empty_hdf):
    assert CheckFloodways._get_encroachment_parameters(empty_hdf, "Floodway") is None


@pytest.mark.parametrize("method, expected_id", [(1, "FW_EM_01"), (5, "FW_EM_05")])
def test_method_notice_is_informational(monkeypatch, empty_hdf, method, expected_id):
    monkeypatch.setattr(CheckFloodways, "_get_encroachment_stations", lambda *args: pd.DataFrame([
        dict(river="River", reach="Reach", station="5.0", encr_method=method, encr_sta_l=20, encr_sta_r=80)
    ]))
    messages = CheckFloodways._check_floodway_encroachment_methods(
        empty_hdf, empty_hdf, "Floodway", get_default_thresholds(),
    )
    message = next(m for m in messages if m.message_id == expected_id)
    assert message.severity.value == "INFO"
    assert "{" not in message.message
    assert "with target 1.00" not in message.message
    assert not any(m.message_id == "FW_EM_08" for m in messages)


def test_documented_ids_and_severities_match_public_helpers():
    # Scope explicitly excludes the extended structure helper not called by the
    # public entry point; do not turn template existence into coverage claims.
    source = ast.parse(inspect.getsource(CheckFloodways))
    implemented = {}
    for function in source.body[0].body:
        if not isinstance(function, ast.FunctionDef) or function.name == "_check_structure_floodway":
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "CheckMessage":
                continue
            keywords = {item.arg: item.value for item in node.keywords}
            message_id = ast.literal_eval(keywords["message_id"])
            severity = keywords["severity"].attr
            implemented[message_id] = severity
            assert get_message_template(message_id) != message_id
    guide = Path(__file__).parents[1] / "docs/user-guide/quality-assurance/floodway-check.md"
    documented = dict(re.findall(r"^\| (FW_[A-Z0-9_]+) \| (ERROR|WARNING|INFO) \|", guide.read_text(encoding="utf-8"), re.M))
    assert documented == implemented
