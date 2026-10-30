"""Unsteady starting conditions: initialization decides ``method``; boundaries are checked one by one.

HEC-RAS starts an unsteady run either from a restart (initial conditions) file or
from initial flows whose water surfaces it computes by a steady backwater pass
(then the warm-up). The computed plan HDF records which in
``Event Conditions/Unsteady/Initial Conditions@Startup Mode`` ("Computed" in every
public corpus plan; "Restart File" with ``Restart Filename`` in a restart plan).
Downstream boundaries are reported separately in ``boundaries``.

``CheckProfiles`` reaches its starting-condition block only when steady results
exist, so its public path is exercised here with ``get_steady_results`` replaced,
as in ``test_floodway_diagnostic_contract.py``.
"""
import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import HdfResultsPlan
from ras_commander.check.check_profiles import CheckProfiles
from ras_commander.hdf.HdfPlan import HdfPlan

BC = "Event Conditions/Unsteady/Boundary Conditions"
IC = "Event Conditions/Unsteady/Initial Conditions"


def _plan(path, *, startup=None, restart=None, normal=(), flow_hydrograph=True, warmup=None):
    with h5py.File(path, "w") as hdf:
        hdf.require_group("Results/Unsteady")
        ic = hdf.require_group(IC)
        if startup is not None:
            ic.attrs["Startup Mode"] = np.bytes_(startup)
        if restart is not None:
            ic.attrs["Restart Filename"] = np.bytes_(restart)
        if warmup is not None:
            hdf.require_group("Plan Data/Plan Parameters").attrs["1D-2D Number of Warmup Steps"] = np.int32(warmup)
        if flow_hydrograph:
            hdf.create_dataset(f"{BC}/Flow Hydrographs/River: R  Reach: A  RS: 9.0",
                               data=np.zeros((3, 2), dtype="f4"))
        hdf.require_group(BC)
        for reach, rs, slope in normal:
            ds = hdf.create_dataset(f"{BC}/Normal Depths/River: R  Reach: {reach}  RS: {rs}",
                                    data=np.array([slope], dtype="f4"))
            for name, value in (("River", "R"), ("Reach", reach), ("RS", rs)):
                ds.attrs[name] = np.bytes_(value)
    return path


@pytest.fixture
def steady_results(monkeypatch):
    # One profile per section: no profile-ordering comparison runs, only the
    # starting-condition block is exercised.
    frame = pd.DataFrame([
        dict(profile=p, river="R", reach="A", node_id=rs, wsel=100.0, flow=100.0)
        for p, rs in (("PF 1", "1.0"), ("PF 2", "2.0"))])
    monkeypatch.setattr(HdfResultsPlan, "get_steady_results", lambda _: frame)


def _ic_messages(path):
    result = CheckProfiles.check_profiles(path, ["PF 1", "PF 2"])
    return [m for m in result.messages if m.message_id.startswith("PF_IC")]


# ------------------------------------------------------------------ defect 1
def test_restart_plan_method_is_the_restart_file_not_the_outlet(tmp_path):
    path = _plan(tmp_path / "p.p02.hdf", startup="Restart File",
                 restart="p.p01.01JAN2026 2400.rst", normal=[("A", "1.0", 0.001)])
    result = HdfPlan.get_starting_wse_method(path)
    assert result["method"] == "Restart File"
    assert result["restart_file"] == "p.p01.01JAN2026 2400.rst"
    assert "slope" not in result
    assert [b["type"] for b in result["boundaries"]] == ["Normal Depth"]


def test_computed_plan_with_only_flow_hydrographs_is_known(tmp_path, steady_results):
    path = _plan(tmp_path / "p.p01.hdf", startup="Computed", warmup=20)
    result = HdfPlan.get_starting_wse_method(path)
    assert result["method"] == "Computed"
    assert result["boundaries"] == []
    assert result["warmup_steps"] == 20
    assert [m.message_id for m in _ic_messages(path)] == []


def test_missing_startup_mode_is_unknown_and_reported(tmp_path, steady_results):
    path = _plan(tmp_path / "p.p01.hdf", normal=[("A", "1.0", 0.001)])
    result = HdfPlan.get_starting_wse_method(path)
    assert result["method"] == "Unknown"
    assert "Startup Mode" in result["note"]
    assert [m.message_id for m in _ic_messages(path)] == ["PF_IC_00"]


# ------------------------------------------------------------------ defect 2
def test_each_normal_depth_boundary_slope_is_screened(tmp_path, steady_results):
    path = _plan(tmp_path / "p.p01.hdf", startup="Computed",
                 normal=[("A", "1.0", 0.001), ("B", "2.0", 0.000001)])
    messages = _ic_messages(path)
    assert [(m.message_id, m.river, m.reach, m.station) for m in messages] == [
        ("PF_IC_02", "R", "B", "2.0")]
    assert "River: R  Reach: B  RS: 2.0" in messages[0].message
    assert messages[0].value == pytest.approx(float(np.float32(0.000001)))


def test_restart_plan_still_screens_its_boundaries(tmp_path, steady_results):
    path = _plan(tmp_path / "p.p02.hdf", startup="Restart File", restart="x.rst",
                 normal=[("A", "1.0", 0.5)])
    assert [m.message_id for m in _ic_messages(path)] == ["PF_IC_02"]
