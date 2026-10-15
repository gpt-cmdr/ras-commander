"""HEC-RAS 5.x writes volume accounting as summary attributes, not a group."""

from pathlib import Path

import h5py
import pytest

from ras_commander.remote import PortableExecution

from test_portable_execution_any_plan import _flow_text, _plan_text


def _ras5_hdf(path: Path, **overrides) -> Path:
    """Attributes as HEC-RAS 5.0.7 writes them (Muncie 2D, scaled to the firehose)."""
    attributes = {
        "Vol Accounting": b"Volume Accounting in Acre Feet",
        "Vol Accounting 2D Bdry": 0.0,
        "Vol Accounting Cell End": 15.15,
        "Vol Accounting Cell Start": 6.887,
        "Vol Accounting DS Outflow": 0.0,
        "Vol Accounting Error": 1.231e-7,
        "Vol Accounting Error Percentage": 8.127e-7,
        "Vol Accounting Groundwater": 0.0,
        "Vol Accounting LS, Pump Div": 0.0,
        "Vol Accounting Lat Hydro": 0.0,
        "Vol Accounting US Inflow": 8.264,
        "Solution": b"Unsteady Finished Successfully",
    }
    attributes.update(overrides)
    with h5py.File(path, "w") as handle:
        group = handle.create_group("Results/Unsteady/Summary")
        for key, value in attributes.items():
            if value is not None:
                group.attrs[key] = value
    return path


def _files(tmp_path: Path, **overrides):
    flow = tmp_path / "m.u01"
    flow.write_text(_flow_text())
    plan = tmp_path / "m.p01"
    plan.write_text(_plan_text())
    return _ras5_hdf(tmp_path / "m.p01.hdf", **overrides), flow, plan


def test_ras5_accounting_validates_and_reconciles_the_inflow(tmp_path):
    summary = PortableExecution.validate_unsteady_results(*_files(tmp_path))

    assert summary["passed"], summary["reason_codes"]
    assert summary["volume_accounting_layout"] == "hec-ras-5-summary-attributes"
    assert summary["volume_units"] == "Acre Feet"
    assert summary["boundary_inflow_volume"] == pytest.approx(8.264)
    assert summary["inflow_reconciliation"]["status"] == "passed"


def test_ras5_lateral_inflow_counts_toward_the_reported_inflow(tmp_path):
    summary = PortableExecution.validate_unsteady_results(*_files(
        tmp_path, **{"Vol Accounting US Inflow": 5.0, "Vol Accounting Lat Hydro": 3.264}))

    assert summary["boundary_inflow_volume"] == pytest.approx(8.264)
    assert summary["inflow_reconciliation"]["status"] == "passed"


def test_ras5_volume_error_limit_applies(tmp_path):
    summary = PortableExecution.validate_unsteady_results(*_files(
        tmp_path, **{"Vol Accounting Error Percentage": 2.5}))

    assert summary["reason_codes"] == ["UNSTEADY_VOLUME_ERROR_EXCEEDED"]


def test_ras5_net_exchange_terms_leave_the_inflow_undeterminable(tmp_path):
    summary = PortableExecution.validate_unsteady_results(*_files(
        tmp_path, **{"Vol Accounting 2D Bdry": -1.5}))

    assert summary["passed"], summary["reason_codes"]
    reconciliation = summary["inflow_reconciliation"]
    assert reconciliation["status"] == "not_applicable"
    assert "UNSTEADY_INFLOW_NET_EXCHANGE_TERMS" in reconciliation["reasons"]


def test_ras5_accounting_with_a_missing_attribute_fails_closed(tmp_path):
    summary = PortableExecution.validate_unsteady_results(*_files(
        tmp_path, **{"Vol Accounting Error Percentage": None}))

    assert summary["reason_codes"] == ["UNSTEADY_VOLUME_ACCOUNTING_MISSING"]
