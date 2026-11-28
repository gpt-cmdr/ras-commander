"""Real-HEC-RAS regressions: a zero launcher exit is not proof that a run finished.

A HEC-RAS 7.0.1 run once exited 0 after its solver stopped 2.4 h into a 48 h
window. The plan HDF it left was truncated, yet ``RasCmdr.compute_plan``
returned success because, without ``verify=True``, it trusted the exit code.

These tests run the Muncie example (plan 01, 1D unsteady, 24 h window)
through ``RasCmdr.compute_plan`` and derive the failure cases from that real
plan HDF: a truncated copy, and a copy whose declared window extends past the
stored output. HEC-RAS runs only through RAS Commander, in a disposable copy.
"""

import shutil
from datetime import timedelta
from pathlib import Path

import h5py
import pytest

from ras_commander import RasCmdr, RasPrj, RasTcu, init_ras_project
from ras_commander.RasExamples import RasExamples
from ras_commander.hdf.HdfUtils import HdfUtils


pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_ras,
    pytest.mark.destructive_copy,
]

RAS_VERSION = "6.6"
PLAN = "01"


def _require_engine():
    status = RasTcu.status(ras_version=RAS_VERSION)
    if not status.accepted:
        pytest.skip(f"HEC-RAS {RAS_VERSION} not available: {status.reason}")


def _project(suffix):
    _require_engine()
    path = RasExamples.extract_project("Muncie", suffix=suffix)
    ras = RasPrj()
    init_ras_project(path, RAS_VERSION, ras_object=ras)
    return ras


def _text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _plan_hdf(ras):
    return Path(ras.project_folder) / f"{ras.project_name}.p{PLAN}.hdf"


@pytest.fixture(scope="module")
def completed_run():
    """One real Muncie plan 01 run; returns (ComputeResult, plan HDF path)."""
    ras = _project("incomplete_result_complete")
    result = RasCmdr.compute_plan(
        PLAN, ras_object=ras, force_rerun=True, num_cores=1
    )
    hdf = _plan_hdf(ras)
    if not hdf.is_file():
        pytest.skip(f"HEC-RAS {RAS_VERSION} wrote no plan HDF: {result!r}")
    return result, hdf


def test_complete_real_run_passes_the_completion_gate(completed_run):
    result, hdf = completed_run

    assert result.success is True, result.failure_reason
    evidence = result.execution_details["completion_evidence"]
    assert evidence["complete"] is True
    assert evidence["hdf_readable"] is True
    assert evidence["complete_process_record"] is True
    window = evidence["simulation_window"]
    assert window["window_complete"] is True
    assert window["observed_end"] == window["declared_end"]
    assert RasCmdr._verify_completion(hdf) is True


def test_truncated_copy_of_real_plan_hdf_is_incomplete(completed_run, tmp_path):
    _, hdf = completed_run
    copy = Path(shutil.copy2(hdf, tmp_path / hdf.name))
    with open(copy, "r+b") as stream:
        stream.truncate(int(copy.stat().st_size * 0.9))

    evidence = RasCmdr._inspect_hdf_completion_evidence(copy)

    assert evidence["complete"] is False
    assert evidence["failure_reason"] == "result_hdf_unreadable"
    assert evidence["hdf_readable"] is False
    assert "truncated" in evidence["hdf_open_error"]
    assert RasCmdr._verify_completion(copy) is False


def test_real_plan_hdf_with_unreached_window_end_is_incomplete(
    completed_run, tmp_path
):
    """Stored output that stops 24 h before the declared end is a short run."""
    _, hdf = completed_run
    copy = Path(shutil.copy2(hdf, tmp_path / hdf.name))
    with h5py.File(copy, "r+") as plan:
        info = plan["Plan Data/Plan Information"]
        start = HdfUtils.parse_ras_datetime(_text(info.attrs["Simulation Start Time"]))
        end = HdfUtils.parse_ras_datetime(_text(info.attrs["Simulation End Time"]))
        later = (end + timedelta(hours=24)).strftime("%d%b%Y %H:%M:%S")
        info.attrs["Simulation End Time"] = later
        if "Time Window" in info.attrs:
            info.attrs["Time Window"] = (
                f"{start:%d%b%Y %H:%M:%S} to {later}"
            )

    evidence = RasCmdr._inspect_hdf_completion_evidence(copy)

    assert evidence["complete"] is False
    assert evidence["failure_reason"] == "simulation_window_incomplete"
    window = evidence["simulation_window"]
    assert window["window_complete"] is False
    assert window["shortfall_seconds"] == pytest.approx(24 * 3600)
    assert RasCmdr._verify_completion(copy) is False


def test_compute_plan_reports_failure_when_real_run_leaves_truncated_hdf(
    monkeypatch,
):
    """End to end: HEC-RAS exits 0, then the plan HDF on disk is truncated.

    The truncation is applied after the real solver has stopped and before
    ``compute_plan`` judges the result, reproducing what the crashed run left.
    Before the fix this returned success.
    """
    ras = _project("incomplete_result_truncated")
    hdf = _plan_hdf(ras)
    confirm = RasCmdr._confirm_plan_solver_quiescence

    def confirm_then_truncate(plan_number, ras_object):
        quiesced = confirm(plan_number, ras_object)
        if quiesced and hdf.is_file():
            with open(hdf, "r+b") as stream:
                stream.truncate(int(hdf.stat().st_size * 0.9))
        return quiesced

    monkeypatch.setattr(
        RasCmdr,
        "_confirm_plan_solver_quiescence",
        staticmethod(confirm_then_truncate),
    )

    result = RasCmdr.compute_plan(
        PLAN, ras_object=ras, force_rerun=True, num_cores=1
    )

    details = result.execution_details
    if details["launcher_returncode"] != 0:
        pytest.skip(f"HEC-RAS launcher did not exit 0: {result!r}")
    assert result.success is False
    assert details["failure_stage"] == "result_completion"
    assert details["failure_type"] == "IncompletePlanResultError"
    assert details["completion_evidence"]["failure_reason"] == (
        "result_hdf_unreadable"
    )
    assert "truncated" in result.failure_reason
