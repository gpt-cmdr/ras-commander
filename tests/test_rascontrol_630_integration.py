"""Opt-in real HEC-RAS 6.3.0.2 Controller qualification."""

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from ras_commander import RasControl, RasPrj, init_ras_project
from ras_commander.RasControl import _active_sessions


pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_ras,
    pytest.mark.destructive_copy,
]


@pytest.mark.skipif(sys.platform != "win32", reason="HECRASController requires Windows")
def test_real_ras630_blocking_compute_on_disposable_fixture(tmp_path):
    """Compute an immutable fixture copy and emit a machine-readable receipt."""
    source_value = os.environ.get("RASCOMMANDER_RAS630_FIXTURE")
    if not source_value:
        pytest.skip("set RASCOMMANDER_RAS630_FIXTURE to an immutable steady project")

    source = Path(source_value)
    exe = Path(
        os.environ.get(
            "RASCOMMANDER_RAS630_EXE",
            r"C:\Program Files (x86)\HEC\HEC-RAS\6.3\Ras.exe",
        )
    )
    if not source.is_dir() or not exe.is_file():
        pytest.skip("configured HEC-RAS 6.3.0.2 executable or fixture is unavailable")

    project_dir = tmp_path / source.name
    shutil.copytree(source, project_dir)
    plan_number = os.environ.get("RASCOMMANDER_RAS630_PLAN", "01").zfill(2)
    plan_hdf_suffix = f".p{plan_number}.hdf"
    messages_suffix = f".p{plan_number}.computemsgs.txt"
    for path in project_dir.iterdir():
        lowered = path.name.lower()
        if lowered.endswith((plan_hdf_suffix, messages_suffix)):
            path.unlink()

    ras_pids_before = set(
        RasControl.list_processes(show_all=True)["pid"].astype(int).tolist()
    )
    project = RasPrj()
    init_ras_project(
        project_dir,
        str(exe),
        ras_object=project,
        load_results_summary=False,
        hide_intro=True,
        accept_tcu=False,
        load_hdf_metadata=False,
    )

    started = time.perf_counter()
    result = RasControl.run_plan(
        plan_number,
        ras_object=project,
        force_recompute=True,
        blocking=True,
        controller_version="6.3.0.2",
        use_watchdog=False,
        strict_close=True,
        refresh_results=False,
    )
    wall_seconds = time.perf_counter() - started

    plan_hdfs = [
        path
        for path in project_dir.iterdir()
        if path.name.lower().endswith(plan_hdf_suffix)
    ]
    compute_messages = [
        path
        for path in project_dir.iterdir()
        if path.name.lower().endswith(messages_suffix)
    ]
    assert result.success is True
    assert any("Computations Completed" in message for message in result.messages)
    assert len(plan_hdfs) == 1
    assert len(compute_messages) == 1
    sidecar_text = (
        compute_messages[0].read_text(encoding="utf-8", errors="replace").casefold()
    )
    assert any(
        signal in sidecar_text
        for signal in ("computations completed", "complete process")
    )

    import h5py

    with h5py.File(plan_hdfs[0], "r") as handle:
        assert (
            len(
                handle[
                    "Results/Steady/Output/Output Blocks/Base Output/"
                    "Steady Profiles/Profile Names"
                ]
            )
            > 0
        )
        assert (
            len(handle["Results/Steady/Output/Geometry Info/Cross Section Attributes"])
            > 0
        )
    assert result.execution_details["controller_progid"] == ("RAS630.HECRASController")
    assert result.execution_details["compute_mode"] == "blocking"
    assert result.execution_details["watchdog_started"] is False
    ras_pids_after = set(
        RasControl.list_processes(show_all=True)["pid"].astype(int).tolist()
    )
    new_ras_pids = sorted(ras_pids_after - ras_pids_before)
    assert new_ras_pids == []
    assert not any(
        session.project_path == str(project.prj_file)
        for session in _active_sessions.values()
    )

    receipt = {
        "success": result.success,
        "messages": result.messages,
        "execution_details": result.execution_details,
        "wall_seconds": wall_seconds,
        "result_hdf": plan_hdfs[0].name,
        "compute_messages": compute_messages[0].name,
        "ras_pids_before": sorted(ras_pids_before),
        "ras_pids_after": sorted(ras_pids_after),
        "new_ras_pids_after": new_ras_pids,
    }
    print("RASCONTROL_630_INTEGRATION=" + json.dumps(receipt, sort_keys=True))
