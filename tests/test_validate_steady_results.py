"""Tests for validate_steady_results.

The first two tests are ported from the c05a-mesh-depth portable execution
contract tests (tests/test_portable_execution_contract.py). The remaining tests
cover fail-closed paths and the call shape used by fim-commander's local plan
execution backend.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ras_commander.remote import PortableExecution


def _patch_sources(monkeypatch, authored, profile_names, rows):
    monkeypatch.setattr(
        PortableExecution.RasSteady, "read_flow_file", lambda path: authored
    )
    monkeypatch.setattr(
        PortableExecution.HdfResultsPlan,
        "get_steady_profile_names",
        lambda path: profile_names,
    )
    monkeypatch.setattr(
        PortableExecution.HdfResultsPlan,
        "get_steady_results",
        lambda path: rows,
    )


def _two_profile_case():
    authored = {
        "profile_names": ["PF 1", "PF 2"],
        "flow_changes": [
            {"river": "River", "reach": "Reach", "station": "1000", "flows": [100, 200]},
            {"river": "River", "reach": "Reach", "station": "500", "flows": [150, 250]},
        ],
    }
    rows = pd.DataFrame(
        [
            {"river": "River", "reach": "Reach", "node_id": "900", "profile": "PF 1", "flow": 100.005, "wsel": 11.0},
            {"river": "River", "reach": "Reach", "node_id": "400", "profile": "PF 1", "flow": 150.0, "wsel": 12.0},
            {"river": "River", "reach": "Reach", "node_id": "900", "profile": "PF 2", "flow": 200.0, "wsel": 13.0},
            {"river": "River", "reach": "Reach", "node_id": "400", "profile": "PF 2", "flow": 250.0, "wsel": 14.0},
        ]
    )
    return authored, rows


def test_validate_steady_results_compares_effective_flow_schedule(monkeypatch):
    authored, rows = _two_profile_case()
    _patch_sources(monkeypatch, authored, ["PF 1", "PF 2"], rows)

    validation = PortableExecution.validate_steady_results("result.hdf", "flow.f01")

    assert validation["passed"]
    assert validation["reason_codes"] == []
    assert validation["flow_rows_compared"] == 4
    assert validation["flow_mismatch_count"] == 0
    assert validation["max_absolute_flow_mismatch"] == pytest.approx(0.005)


def test_validate_steady_results_fails_closed_on_mismatch_and_nonfinite(monkeypatch):
    authored = {
        "profile_names": ["PF 1"],
        "flow_changes": [
            {"river": "River", "reach": "Reach", "station": "1000", "flows": [100]}
        ],
    }
    rows = pd.DataFrame(
        [
            {"river": "River", "reach": "Reach", "node_id": "900", "profile": "PF 1", "flow": 120.0, "wsel": 11.0},
            {"river": "Other", "reach": "Reach", "node_id": "900", "profile": "PF 1", "flow": 100.0, "wsel": float("nan")},
        ]
    )
    _patch_sources(monkeypatch, authored, ["PF 1"], rows)

    validation = PortableExecution.validate_steady_results("result.hdf", "flow.f01")

    assert not validation["passed"]
    assert "STEADY_NONFINITE_WSEL" in validation["reason_codes"]
    assert "STEADY_FLOW_SCHEDULE_UNMATCHED" in validation["reason_codes"]
    assert "STEADY_FLOW_SCHEDULE_MISMATCH" in validation["reason_codes"]


def test_validate_steady_results_reports_unreadable_inputs(tmp_path):
    validation = PortableExecution.validate_steady_results(
        tmp_path / "missing.p01.hdf", tmp_path / "missing.f01"
    )

    assert validation["passed"] is False
    assert validation["reason_codes"] == ["STEADY_RESULTS_UNREADABLE"]
    assert "error" in validation


def test_validate_steady_results_reports_profile_and_column_problems(monkeypatch):
    authored, _ = _two_profile_case()
    rows = pd.DataFrame([{"river": "River", "reach": "Reach", "profile": "PF 1"}])
    _patch_sources(monkeypatch, authored, ["PF 1"], rows)

    validation = PortableExecution.validate_steady_results("result.hdf", "flow.f01")

    assert validation["passed"] is False
    assert "STEADY_PROFILE_MISMATCH" in validation["reason_codes"]
    assert "STEADY_RESULT_COLUMNS_MISSING" in validation["reason_codes"]
    assert validation["missing_columns"] == ["flow", "node_id", "wsel"]


def test_validate_steady_results_tolerance_is_configurable(monkeypatch):
    authored, rows = _two_profile_case()
    _patch_sources(monkeypatch, authored, ["PF 1", "PF 2"], rows)

    validation = PortableExecution.validate_steady_results(
        "result.hdf", "flow.f01", absolute_tolerance=0.001
    )

    assert validation["passed"] is False
    assert validation["reason_codes"] == ["STEADY_FLOW_SCHEDULE_MISMATCH"]
    assert validation["flow_mismatch_count"] == 1


def test_fim_commander_local_plan_backend_call_shape(monkeypatch, tmp_path):
    """Mirror fim_commander.execution.local_plan's import list and call."""
    from ras_commander import (  # noqa: F401 - the backend's exact import list
        HdfResultsPlan,
        RasCmdr,
        RasPrj,
        RasTcu,
        ResultsParser,
        init_ras_project,
        validate_steady_results,
    )
    import ras_commander
    from ras_commander.remote import validate_steady_results as remote_export

    assert validate_steady_results is PortableExecution.validate_steady_results
    assert remote_export is PortableExecution.validate_steady_results
    assert "validate_steady_results" in ras_commander.__all__
    assert "RasQualification" in ras_commander.__all__

    authored, rows = _two_profile_case()
    _patch_sources(monkeypatch, authored, ["PF 1", "PF 2"], rows)
    hdf_path = tmp_path / "Model.p01.hdf"
    runtime_flow_path = tmp_path / "Model.f01"

    result_validation = validate_steady_results(hdf_path, runtime_flow_path)

    assert isinstance(result_validation.get("passed"), bool)
    assert result_validation["passed"] is True
    assert isinstance(result_validation.get("reason_codes"), list)
