"""Deterministic tests for strict HEC-RAS process inspection/cancellation."""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pandas as pd
import pytest

from ras_commander import (
    PlanCancellationResult,
    PlanProcessInventory,
    RasCmdr,
    RasControl,
    RasProcessInventory,
    RasProcessQueryError,
    RasProcessRecord,
)
from ras_commander._process_inspection import (
    match_plan_processes,
    normalize_windows_path_token,
    scan_ras_processes,
)


class FakeAccessDenied(Exception):
    pass


class FakeNoSuchProcess(Exception):
    pass


class FakeProcess:
    def __init__(
        self,
        pid,
        name,
        cmdline,
        *,
        create_time=1.0,
        cwd=r"C:\Models",
        exe=None,
        survive_terminate=False,
        survive_kill=False,
        denied_fields=(),
    ):
        self.pid = pid
        self._name = name
        self._cmdline = list(cmdline)
        self._create_time = float(create_time)
        self._cwd = cwd
        self._exe = exe or rf"C:\HEC\{name}"
        self.denied_fields = set(denied_fields)
        self.survive_terminate = survive_terminate
        self.survive_kill = survive_kill
        self.running = True
        self.terminated = False
        self.killed = False
        self._children = []
        self.info = {"pid": pid}
        for field, value in {
            "name": name,
            "cmdline": list(cmdline),
            "create_time": float(create_time),
            "cwd": cwd,
            "exe": self._exe,
        }.items():
            if field not in self.denied_fields:
                self.info[field] = value

    def _read(self, field, value):
        if field in self.denied_fields:
            raise FakeAccessDenied(field)
        if not self.running:
            raise FakeNoSuchProcess(self.pid)
        return value

    def name(self):
        return self._read("name", self._name)

    def cmdline(self):
        return self._read("cmdline", list(self._cmdline))

    def create_time(self):
        return self._read("create_time", self._create_time)

    def cwd(self):
        return self._read("cwd", self._cwd)

    def exe(self):
        return self._read("exe", self._exe)

    def children(self, recursive=False):
        del recursive
        return list(self._children)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        if not self.survive_kill:
            self.running = False

    def is_running(self):
        return self.running


class FakePsutil:
    AccessDenied = FakeAccessDenied
    NoSuchProcess = FakeNoSuchProcess

    def __init__(self, processes=(), *, snapshots=None):
        self.processes = list(processes)
        self.snapshots = None if snapshots is None else list(snapshots)
        self.scan_index = 0
        self.process_iter_calls = 0

    def process_iter(self, attrs):
        self.process_iter_calls += 1
        assert attrs in (
            ["pid", "name", "create_time", "cmdline", "exe", "cwd"],
            ["pid", "name", "create_time", "cmdline"],
        )
        if self.snapshots is not None:
            index = min(self.scan_index, len(self.snapshots) - 1)
            self.scan_index += 1
            return iter(self.snapshots[index])
        return iter(process for process in self.processes if process.running)

    @staticmethod
    def wait_procs(processes, timeout):
        assert timeout > 0
        gone = []
        alive = []
        for process in processes:
            if process.killed:
                if process.survive_kill:
                    alive.append(process)
                else:
                    process.running = False
                    gone.append(process)
            elif process.terminated and not process.survive_terminate:
                process.running = False
                gone.append(process)
            else:
                alive.append(process)
        return gone, alive


class FakeRas:
    def __init__(self, root: Path):
        self.project_folder = root
        self.project_name = "Fox"
        self.prj_file = root / "Fox.prj"
        self.plan_path = root / "Fox.p01"
        self.prj_file.write_text("Proj Title=Fox\n", encoding="ascii")
        self.plan_path.write_text("Plan Title=Plan 01\n", encoding="ascii")

    @staticmethod
    def check_initialized():
        return None

    def get_plan_entries(self):
        return pd.DataFrame([{"plan_number": "01", "full_path": str(self.plan_path)}])


def _record(pid, name, command, *, cwd=r"C:\Models", created=1.0):
    return RasProcessRecord(
        pid=pid,
        create_time=created,
        name=name,
        executable_path=rf"C:\HEC\{name}",
        command_line=tuple(command),
        working_directory=cwd,
    )


def _plan_inventory(*records, complete=True):
    inventory = RasProcessInventory(
        observed_at=1.0,
        complete=complete,
        processes=tuple(records),
    )
    return match_plan_processes(
        inventory,
        plan_number="01",
        project_path=Path(r"C:\Models\Fox.prj"),
        plan_path=Path(r"C:\Models\Fox.p01"),
        tmp_hdf_path=Path(r"C:\Models\Fox.p01.tmp.hdf"),
    )


def test_plan_match_accepts_windows_same_file_aliases(tmp_path):
    project = tmp_path / "Fox.prj"
    plan = tmp_path / "Fox.p01"
    project.write_text("Proj Title=Fox\n", encoding="ascii")
    plan.write_text("Plan Title=Plan 01\n", encoding="ascii")
    project_alias = tmp_path / "Fox-project-alias.prj"
    plan_alias = tmp_path / "Fox-plan-alias.p01"
    os.link(project, project_alias)
    os.link(plan, plan_alias)
    process = _record(
        10,
        "Ras.exe",
        ["Ras.exe", str(project_alias), str(plan_alias)],
        cwd=str(tmp_path),
    )
    inventory = RasProcessInventory(
        observed_at=1.0,
        complete=True,
        processes=(process,),
    )

    result = match_plan_processes(
        inventory,
        plan_number="01",
        project_path=project,
        plan_path=plan,
        tmp_hdf_path=tmp_path / "Fox.p01.tmp.hdf",
    )

    assert result.matched == (process,)


def _patch_psutil(monkeypatch, fake_psutil):
    control_module = importlib.import_module("ras_commander.RasControl")
    cmdr_module = importlib.import_module("ras_commander.RasCmdr")
    monkeypatch.setattr(control_module, "psutil", fake_psutil)
    monkeypatch.setattr(cmdr_module, "_WINDOWS_PROCESS_CONTROL", True)
    real_psutil = importlib.import_module("psutil")
    monkeypatch.setattr(real_psutil, "process_iter", fake_psutil.process_iter)
    monkeypatch.setattr(real_psutil, "wait_procs", fake_psutil.wait_procs)
    monkeypatch.setattr(real_psutil, "AccessDenied", FakeAccessDenied)
    monkeypatch.setattr(real_psutil, "NoSuchProcess", FakeNoSuchProcess)


def test_strict_inventory_includes_compute_taxonomy_and_tracking():
    expected_names = [
        "adh.exe",
        "adh_hot.exe",
        "pre_adh.exe",
        "GeomPreprocessor.exe",
        "Steady.exe",
        "Unsteady.exe",
        "Sediment.exe",
        "SIAM.exe",
        "wqnet.exe",
        "RasGeomPreprocess.exe",
        "RasSteady.exe",
        "RasUnsteady.exe",
        "RasUnsteadySediment.exe",
        "RasQuasiSediment.exe",
        "RasQuasiRVSM.exe",
        "RasWaterQuality.exe",
        "KineticsInterface.exe",
        "Kinetics_WPF_Interface.exe",
        "Ras.exe",
        "RasProcess.exe",
    ]
    compute_processes = [
        FakeProcess(pid, name, [name])
        for pid, name in enumerate(expected_names, start=10)
    ]
    unrelated = [
        FakeProcess(100, "RasMapper.exe", ["RasMapper.exe"]),
        FakeProcess(101, "RasPlotDriver.exe", ["RasPlotDriver.exe"]),
        FakeProcess(102, "RasUnsteady.exe.helper", ["RasUnsteady.exe.helper"]),
    ]

    result = scan_ras_processes(
        tracked_pids={10},
        psutil_module=FakePsutil([*compute_processes, *unrelated]),
    )

    assert result.complete is True
    assert [item.name for item in result.processes] == expected_names
    assert result.processes[0].tracked is True
    assert result.processes[1].tracked is False


@pytest.mark.parametrize(
    "engine_name",
    [
        "adh.exe",
        "adh_hot.exe",
        "pre_adh.exe",
        "GeomPreprocessor.exe",
        "Sediment.exe",
        "SIAM.exe",
        "wqnet.exe",
        "RasGeomPreprocess.exe",
        "RasUnsteadySediment.exe",
        "RasQuasiSediment.exe",
        "RasQuasiRVSM.exe",
        "RasWaterQuality.exe",
        "KineticsInterface.exe",
        "Kinetics_WPF_Interface.exe",
        "RasProcess.exe",
    ],
)
def test_plan_matcher_ignores_globally_visible_non_plan_engines(engine_name):
    process = FakeProcess(
        10,
        engine_name,
        [
            engine_name,
            r"C:\Models\Fox.prj",
            r"C:\Models\Fox.p01",
            r"C:\Models\Fox.r01",
            r"C:\Models\Fox.p01.tmp.hdf",
        ],
    )

    inventory = scan_ras_processes(
        psutil_module=FakePsutil([process]),
    )
    result = match_plan_processes(
        inventory,
        plan_number="01",
        project_path=Path(r"C:\Models\Fox.prj"),
        plan_path=Path(r"C:\Models\Fox.p01"),
        tmp_hdf_path=Path(r"C:\Models\Fox.p01.tmp.hdf"),
    )

    assert [item.name for item in inventory.processes] == [engine_name]
    assert result.matched == ()


@pytest.mark.parametrize("solver_name", ["RasSteady.exe", "Steady.exe"])
def test_exact_match_recognizes_steady_run_file_without_basename_fallback(
    solver_name,
):
    exact = _record(
        10,
        solver_name,
        [solver_name, r"C:\Models\Fox.r01"],
    )
    prefix = _record(
        11,
        solver_name,
        [solver_name, r"C:\Models\Fox.r010"],
    )
    basename_elsewhere = _record(
        12,
        solver_name,
        [solver_name, "Fox.r01"],
        cwd=r"C:\Other",
    )

    result = _plan_inventory(exact, prefix, basename_elsewhere)

    assert result.matched == (exact,)


def test_strict_inventory_ignores_non_ras_windows_pid_zero():
    idle = FakeProcess(0, "System Idle Process", ["System Idle Process"])
    launcher = FakeProcess(10, "Ras.exe", ["Ras.exe"])

    result = scan_ras_processes(
        psutil_module=FakePsutil([idle, launcher]),
    )

    assert result.complete is True
    assert [item.pid for item in result.processes] == [10]
    assert result.query_errors == ()


def test_strict_inventory_reports_access_denied_and_is_incomplete():
    inaccessible = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe"],
        denied_fields={"name"},
    )

    result = scan_ras_processes(
        psutil_module=FakePsutil([inaccessible]),
    )

    assert result.processes == ()
    assert result.complete is False
    assert result.query_errors[0].pid == 10
    assert result.query_errors[0].operation == "classify_process"
    assert result.query_errors[0].exception_type == "FakeAccessDenied"
    assert result.query_errors[0].reason_code == "access_denied"


def test_strict_inventory_rejects_malformed_required_identity_metadata():
    malformed = FakeProcess(10, "Ras.exe", [])

    result = scan_ras_processes(psutil_module=FakePsutil([malformed]))

    assert result.complete is False
    assert result.processes == ()
    assert result.query_errors[0].operation == "normalize_process_metadata"
    assert result.query_errors[0].reason_code == "process_query_failed"


def test_strict_inventory_records_tracked_session_identity():
    launcher = FakeProcess(10, "Ras.exe", ["Ras.exe"])

    result = scan_ras_processes(
        tracked_sessions={(10, 1.0): "session-123"},
        psutil_module=FakePsutil([launcher]),
    )

    assert result.processes[0].tracked is True
    assert result.processes[0].session_id == "session-123"


def test_strict_inventory_does_not_track_reused_pid_identity():
    replacement = FakeProcess(10, "Ras.exe", ["Ras.exe"], create_time=2.0)

    result = scan_ras_processes(
        tracked_sessions={(10, 1.0): "old-session"},
        psutil_module=FakePsutil([replacement]),
    )

    assert result.processes[0].tracked is False
    assert result.processes[0].session_id is None


@pytest.mark.parametrize(
    ("record_type", "kwargs", "message"),
    [
        (RasProcessRecord, {"pid": 0, "create_time": 1.0, "name": "Ras.exe"}, "pid"),
        (
            RasProcessRecord,
            {"pid": 1, "create_time": float("nan"), "name": "Ras.exe"},
            "create_time",
        ),
        (
            RasProcessInventory,
            {"observed_at": float("inf")},
            "observed_at",
        ),
        (
            PlanProcessInventory,
            {
                "observed_at": 0.0,
                "plan_number": "01",
                "project_path": r"C:\Models\Fox.prj",
                "plan_path": r"C:\Models\Fox.p01",
                "tmp_hdf_path": r"C:\Models\Fox.p01.tmp.hdf",
                "complete": True,
            },
            "observed_at",
        ),
    ],
)
def test_public_process_evidence_rejects_invalid_identity_timestamps(
    record_type,
    kwargs,
    message,
):
    with pytest.raises(ValueError, match=message):
        record_type(**kwargs)


def test_exact_match_rejects_prefix_and_basename_collisions():
    exact = _record(
        10,
        "Ras.exe",
        ["Ras.exe", "Fox.prj", "Fox.p01"],
    )
    project_prefix = _record(
        11,
        "Ras.exe",
        ["Ras.exe", r"C:\Models\Fox.prj.backup", r"C:\Models\Fox.p01"],
    )
    plan_prefix = _record(
        12,
        "Ras.exe",
        ["Ras.exe", r"C:\Models\Fox.prj", r"C:\Models\Fox.p010"],
    )
    wrong_cwd = _record(
        13,
        "Ras.exe",
        ["Ras.exe", "Fox.prj", "Fox.p01"],
        cwd=r"C:\Other",
    )

    result = _plan_inventory(exact, project_prefix, plan_prefix, wrong_cwd)

    assert [item.pid for item in result.matched] == [10]
    assert result.complete is True


def test_exact_match_normalizes_solver_relative_unc_and_extended_paths():
    relative_solver = _record(
        10,
        "RasUnsteady.exe",
        ["RasUnsteady.exe", r".\Fox.p01.tmp.hdf"],
    )
    unc_solver = _record(
        11,
        "RasUnsteady.exe",
        ["RasUnsteady.exe", r"\\?\UNC\server\share\Fox.p01.tmp.hdf"],
        cwd=r"C:\Other",
    )
    unc_inventory = RasProcessInventory(
        observed_at=1.0,
        processes=(unc_solver,),
    )

    relative_result = _plan_inventory(relative_solver)
    unc_result = match_plan_processes(
        unc_inventory,
        plan_number="01",
        project_path=Path(r"\\server\share\Fox.prj"),
        plan_path=Path(r"\\server\share\Fox.p01"),
        tmp_hdf_path=Path(r"\\server\share\Fox.p01.tmp.hdf"),
    )

    assert [item.pid for item in relative_result.matched] == [10]
    assert [item.pid for item in unc_result.matched] == [11]
    assert normalize_windows_path_token(
        r"\\?\C:\Models\Fox.p01", None
    ) == normalize_windows_path_token(r"c:/models/FOX.p01", None)


def test_exact_match_supports_observed_solver_cwd_and_plan_marker_signature():
    exact = _record(
        10,
        "RasUnsteady.exe",
        ["RasUnsteady.exe", r"C:\Models\Fox.c01", "b08"],
        cwd=r"C:\Models",
    )
    wrong_plan = _record(
        11,
        "RasUnsteady.exe",
        ["RasUnsteady.exe", r"C:\Models\Fox.c01", "b09"],
        cwd=r"C:\Models",
    )
    wrong_project = _record(
        12,
        "RasUnsteady.exe",
        ["RasUnsteady.exe", r"C:\Other\Fox.c01", "b08"],
        cwd=r"C:\Other",
    )
    inventory = RasProcessInventory(
        observed_at=1.0,
        complete=True,
        processes=(exact, wrong_plan, wrong_project),
    )

    result = match_plan_processes(
        inventory,
        plan_number="08",
        project_path=Path(r"C:\Models\Fox.prj"),
        plan_path=Path(r"C:\Models\Fox.p08"),
        tmp_hdf_path=Path(r"C:\Models\Fox.p08.tmp.hdf"),
    )

    assert result.matched == (exact,)


def test_cwd_marker_match_requires_resolved_project_computation_file(tmp_path):
    project = tmp_path / "Fox.prj"
    plan = tmp_path / "Fox.p08"
    project.write_text("Proj Title=Fox\n", encoding="ascii")
    plan.write_text("Plan Title=Eight\nGeom File=g03\n", encoding="ascii")
    exact = _record(
        10,
        "RasUnsteady.exe",
        ["RasUnsteady.exe", str(tmp_path / "Fox.c03"), "b08"],
        cwd=str(tmp_path),
    )
    wrong_project_file = _record(
        11,
        "RasUnsteady.exe",
        ["RasUnsteady.exe", str(tmp_path / "Other.c03"), "b08"],
        cwd=str(tmp_path),
    )
    inventory = RasProcessInventory(
        observed_at=1.0,
        complete=True,
        processes=(exact, wrong_project_file),
    )

    result = match_plan_processes(
        inventory,
        plan_number="08",
        project_path=project,
        plan_path=plan,
        tmp_hdf_path=tmp_path / "Fox.p08.tmp.hdf",
    )

    assert result.matched == (exact,)


def test_incomplete_inventory_requires_an_explanation():
    with pytest.raises(ValueError, match="incomplete inventory requires"):
        RasProcessInventory(observed_at=1.0, complete=False)


def test_public_inventory_types_are_frozen_and_json_safe():
    mutable_command = ["Ras.exe"]
    process = RasProcessRecord(
        pid=10,
        create_time=1.0,
        name="Ras.exe",
        command_line=mutable_command,
    )
    query_error = RasProcessQueryError(
        pid=10,
        operation="query_cwd",
        reason_code="access_denied",
        exception_type="AccessDenied",
        detail="denied",
    )
    inventory = RasProcessInventory(
        observed_at=12.5,
        complete=False,
        processes=[process],
        query_errors=[query_error],
    )
    cancellation = PlanCancellationResult(
        plan_number="01",
        project_path=r"C:\Models\Fox.prj",
        plan_path=r"C:\Models\Fox.p01",
        tmp_hdf_path=r"C:\Models\Fox.p01.tmp.hdf",
        cancellation_attempted=True,
        pre_scan_complete=True,
        post_scan_complete=True,
        matched=(process,),
        stopped=(process,),
        quiescence_confirmed=True,
    )

    with pytest.raises(FrozenInstanceError):
        process.pid = 20
    with pytest.raises(TypeError, match="tri-state"):
        bool(cancellation)
    with pytest.raises(TypeError, match="truth-value"):
        bool(process)
    with pytest.raises(TypeError, match="completeness"):
        bool(inventory)
    with pytest.raises(TypeError, match="truth-value"):
        bool(query_error)
    mutable_command.append("mutated")
    assert process.command_line == ("Ras.exe",)
    assert isinstance(inventory.processes, tuple)
    assert isinstance(inventory.query_errors, tuple)
    payload = cancellation.to_dict()
    payload["matched"][0]["pid"] = 999
    assert cancellation.matched[0].pid == 10
    assert json.loads(json.dumps(inventory.to_dict()))["complete"] is False
    assert (
        json.loads(json.dumps(cancellation.to_dict()))["quiescence_confirmed"] is True
    )
    assert list(process.to_dict()) == [
        "pid",
        "create_time",
        "name",
        "executable_path",
        "command_line",
        "working_directory",
        "tracked",
        "session_id",
    ]
    assert list(inventory.to_dict()) == [
        "observed_at",
        "complete",
        "processes",
        "query_errors",
    ]
    assert list(query_error.to_dict()) == [
        "pid",
        "operation",
        "reason_code",
        "exception_type",
        "detail",
    ]
    assert list(cancellation.to_dict()) == [
        "plan_number",
        "project_path",
        "plan_path",
        "tmp_hdf_path",
        "cancellation_attempted",
        "pre_scan_complete",
        "post_scan_complete",
        "matched",
        "stopped",
        "survivors",
        "query_errors",
        "quiescence_confirmed",
        "started_at",
        "finished_at",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pid", True),
        ("pid", 0),
        ("pid", "10"),
        ("create_time", True),
        ("create_time", 0.0),
        ("create_time", float("nan")),
        ("create_time", float("inf")),
        ("tracked", 1),
        ("tracked", "false"),
        ("name", "   "),
        ("executable_path", ""),
        ("working_directory", "   "),
        ("session_id", ""),
        ("command_line", ["Ras.exe", 1]),
    ],
)
def test_process_record_rejects_coerced_or_non_json_safe_fields(field, value):
    kwargs = {
        "pid": 10,
        "create_time": 1.0,
        "name": "Ras.exe",
        "command_line": ["Ras.exe"],
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=field):
        RasProcessRecord(**kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pid", True),
        ("pid", 0),
        ("operation", " "),
        ("reason_code", ""),
        ("exception_type", 7),
        ("detail", object()),
    ],
)
def test_query_error_rejects_invalid_identity_and_text(field, value):
    kwargs = {
        "pid": 10,
        "operation": "query_cwd",
        "reason_code": "access_denied",
        "exception_type": "AccessDenied",
        "detail": "denied",
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=field):
        RasProcessQueryError(**kwargs)


def test_process_inventory_requires_typed_finite_consistent_evidence():
    process = _record(10, "Ras.exe", ["Ras.exe"])
    error = RasProcessQueryError(
        pid=10,
        operation="query_cwd",
        reason_code="access_denied",
        exception_type="AccessDenied",
        detail="denied",
    )

    for observed_at in (True, 0.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="observed_at"):
            RasProcessInventory(observed_at=observed_at)
    for complete in (0, 1, "true", None):
        with pytest.raises(ValueError, match="complete"):
            RasProcessInventory(observed_at=1.0, complete=complete)
    with pytest.raises(ValueError, match="processes"):
        RasProcessInventory(observed_at=1.0, processes=[process.to_dict()])
    with pytest.raises(ValueError, match="query_errors"):
        RasProcessInventory(
            observed_at=1.0,
            complete=False,
            query_errors=[error.to_dict()],
        )
    with pytest.raises(ValueError, match="complete inventory"):
        RasProcessInventory(observed_at=1.0, query_errors=[error])
    with pytest.raises(ValueError, match="incomplete inventory requires"):
        RasProcessInventory(observed_at=1.0, complete=False)
    with pytest.raises(ValueError, match="duplicate"):
        RasProcessInventory(observed_at=1.0, processes=[process, process])


def test_plan_inventory_requires_typed_paths_flags_and_nested_records():
    process = _record(10, "Ras.exe", ["Ras.exe"])
    error = RasProcessQueryError(
        pid=None,
        operation="enumerate_processes",
        reason_code="process_query_failed",
        exception_type="OSError",
        detail="failed",
    )
    base = {
        "observed_at": 1.0,
        "plan_number": "01",
        "project_path": r"C:\Models\Fox.prj",
        "plan_path": r"C:\Models\Fox.p01",
        "tmp_hdf_path": r"C:\Models\Fox.p01.tmp.hdf",
        "complete": True,
    }

    for field, value in (
        ("observed_at", True),
        ("plan_number", " "),
        ("project_path", ""),
        ("plan_path", 1),
        ("tmp_hdf_path", " "),
        ("complete", 1),
        ("matched", [process.to_dict()]),
        ("query_errors", [error.to_dict()]),
    ):
        kwargs = {**base, field: value}
        if field == "query_errors":
            kwargs["complete"] = False
        with pytest.raises(ValueError, match=field):
            PlanProcessInventory(**kwargs)
    with pytest.raises(ValueError, match="complete plan inventory"):
        PlanProcessInventory(**base, query_errors=[error])
    with pytest.raises(ValueError, match="incomplete plan inventory requires"):
        PlanProcessInventory(**{**base, "complete": False})


def test_plan_cancellation_rejects_coercion_and_contradictory_safety_claims():
    matched = _record(10, "Ras.exe", ["Ras.exe"])
    survivor = _record(11, "RasUnsteady.exe", ["RasUnsteady.exe"])
    error = RasProcessQueryError(
        pid=10,
        operation="query_process_children",
        reason_code="access_denied",
        exception_type="AccessDenied",
        detail="denied",
    )
    base = {
        "plan_number": "01",
        "project_path": r"C:\Models\Fox.prj",
        "plan_path": r"C:\Models\Fox.p01",
        "tmp_hdf_path": r"C:\Models\Fox.p01.tmp.hdf",
        "cancellation_attempted": True,
        "pre_scan_complete": True,
        "post_scan_complete": True,
        "matched": (matched,),
        "stopped": (matched,),
        "quiescence_confirmed": True,
    }

    for field in (
        "cancellation_attempted",
        "pre_scan_complete",
        "post_scan_complete",
    ):
        with pytest.raises(ValueError, match=field):
            PlanCancellationResult(**{**base, field: 1})
    for value in (0, 1, "true", "false"):
        with pytest.raises(ValueError, match="quiescence_confirmed"):
            PlanCancellationResult(**{**base, "quiescence_confirmed": value})
    with pytest.raises(ValueError, match="initial match"):
        PlanCancellationResult(
            **{
                **base,
                "matched": (),
                "stopped": (),
                "cancellation_attempted": True,
            }
        )
    with pytest.raises(ValueError, match="confirmed quiescence"):
        PlanCancellationResult(**{**base, "post_scan_complete": False})
    with pytest.raises(ValueError, match="incomplete cancellation scans"):
        PlanCancellationResult(
            **{
                **base,
                "post_scan_complete": False,
                "quiescence_confirmed": None,
            }
        )
    with pytest.raises(ValueError, match="confirmed quiescence"):
        PlanCancellationResult(**{**base, "query_errors": (error,)})
    with pytest.raises(ValueError, match="confirmed quiescence"):
        PlanCancellationResult(**{**base, "stopped": ()})
    with pytest.raises(ValueError, match="known non-quiescence"):
        PlanCancellationResult(
            **{**base, "stopped": (), "quiescence_confirmed": False}
        )
    with pytest.raises(ValueError, match="stopped and survivors"):
        PlanCancellationResult(
            **{
                **base,
                "survivors": (matched,),
                "quiescence_confirmed": False,
            }
        )
    with pytest.raises(ValueError, match="indeterminate quiescence"):
        PlanCancellationResult(**{**base, "quiescence_confirmed": None})

    uncertain = PlanCancellationResult(
        **{
            **base,
            "stopped": (matched,),
            "query_errors": (error,),
            "quiescence_confirmed": None,
        }
    )
    known_survivor = PlanCancellationResult(
        **{
            **base,
            "stopped": (),
            "survivors": (survivor,),
            "quiescence_confirmed": False,
        }
    )
    assert uncertain.quiescence_confirmed is None
    assert known_survivor.survivors == (survivor,)

    with pytest.raises(ValueError, match="both be set"):
        PlanCancellationResult(**{**base, "started_at": 1.0})
    with pytest.raises(ValueError, match="cannot precede"):
        PlanCancellationResult(
            **{**base, "started_at": 2.0, "finished_at": 1.0}
        )


def test_process_types_are_exported_from_top_level_package():
    package = importlib.import_module("ras_commander")

    for name in (
        "RasProcessRecord",
        "RasProcessQueryError",
        "RasProcessInventory",
        "PlanProcessInventory",
        "PlanCancellationResult",
    ):
        assert getattr(package, name).__name__ == name
        assert name in package.__all__


def test_rascontrol_inspect_processes_and_legacy_dataframe_contract(monkeypatch):
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", r"C:\Models\Fox.prj"],
        create_time=1.0,
    )
    solver = FakeProcess(11, "RasUnsteady.exe", ["RasUnsteady.exe"])
    fake = FakePsutil([launcher, solver])
    _patch_psutil(monkeypatch, fake)

    strict = RasControl.inspect_processes()
    legacy = RasControl.list_processes(show_all=True)

    assert [item.name for item in strict.processes] == [
        "Ras.exe",
        "RasUnsteady.exe",
    ]
    assert list(legacy.columns) == [
        "pid",
        "tracked",
        "project",
        "age_sec",
        "status",
    ]
    assert legacy["pid"].tolist() == [10]


def test_cancel_exact_terminates_tree_and_leaves_unrelated_process(
    monkeypatch, tmp_path
):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
    )
    solver = FakeProcess(
        11,
        "RasUnsteady.exe",
        ["RasUnsteady.exe", str(tmp_path / "Fox.p01.tmp.hdf")],
        cwd=str(tmp_path),
    )
    child = FakeProcess(12, "RasPlotDriver.exe", ["RasPlotDriver.exe"])
    launcher._children = [solver, child]
    unrelated = FakeProcess(
        20,
        "Ras.exe",
        ["Ras.exe", str(tmp_path / "Fox2.prj"), str(tmp_path / "Fox2.p01")],
        cwd=str(tmp_path),
    )
    fake = FakePsutil([launcher, solver, child, unrelated])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert result.cancellation_attempted is True
    assert result.quiescence_confirmed is True
    assert [item.pid for item in result.matched] == [10, 11]
    assert {item.pid for item in result.stopped} == {10, 11, 12}
    assert unrelated.terminated is False
    assert unrelated.killed is False
    assert RasCmdr.cancel_plan("01", ras_object=ras_obj) is False


def test_cancel_exact_escalates_to_kill_and_reports_survivor(monkeypatch, tmp_path):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
        survive_terminate=True,
        survive_kill=True,
    )
    fake = FakePsutil([launcher])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert result.cancellation_attempted is True
    assert launcher.terminated is True
    assert launcher.killed is True
    assert result.quiescence_confirmed is False
    assert [item.pid for item in result.survivors] == [10]


def test_cancel_exact_escalates_to_kill_and_confirms_stop(monkeypatch, tmp_path):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
        survive_terminate=True,
        survive_kill=False,
    )
    fake = FakePsutil([launcher])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert result.cancellation_attempted is True
    assert launcher.terminated is True
    assert launcher.killed is True
    assert result.quiescence_confirmed is True
    assert [item.pid for item in result.stopped] == [10]
    assert result.survivors == ()


def test_cancel_exact_records_access_denied_without_signalling_unknown(
    monkeypatch, tmp_path
):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
    )

    def deny_terminate():
        raise FakeAccessDenied("terminate")

    launcher.terminate = deny_terminate
    fake = FakePsutil([launcher])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert result.cancellation_attempted is True
    assert result.quiescence_confirmed is False
    assert result.query_errors[-1].operation == "terminate_process"
    assert [item.pid for item in result.survivors] == [10]


@pytest.mark.parametrize("operation", ["terminate", "kill"])
def test_cancel_exact_operation_error_then_natural_exit_remains_uncertain(
    monkeypatch,
    tmp_path,
    operation,
):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
        survive_terminate=operation == "kill",
    )

    def fail_after_exit():
        launcher.running = False
        raise FakeAccessDenied(operation)

    if operation == "terminate":
        launcher.terminate = fail_after_exit
    else:
        launcher.kill = fail_after_exit
    fake = FakePsutil([launcher])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert result.cancellation_attempted is True
    assert result.quiescence_confirmed is None
    assert result.survivors == ()
    assert [item.pid for item in result.stopped] == [10]
    assert result.query_errors[-1].operation == f"{operation}_process"


def test_cancel_exact_post_scan_uncertainty_is_not_clean_absence(monkeypatch, tmp_path):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
    )
    inaccessible = FakeProcess(
        20,
        "Ras.exe",
        ["Ras.exe"],
        denied_fields={"name"},
    )
    fake = FakePsutil(snapshots=[[launcher], [inaccessible]])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert result.post_scan_complete is False
    assert result.quiescence_confirmed is None
    assert any(item.operation == "classify_process" for item in result.query_errors)


def test_cancel_exact_initial_scan_uncertainty_prevents_quiescence_claim(
    monkeypatch, tmp_path
):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
    )
    inaccessible = FakeProcess(
        20,
        "Ras.exe",
        ["Ras.exe"],
        denied_fields={"name"},
    )
    fake = FakePsutil(snapshots=[[launcher, inaccessible], []])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert result.pre_scan_complete is False
    assert result.post_scan_complete is True
    assert result.survivors == ()
    assert result.quiescence_confirmed is None


def test_cancel_exact_child_query_uncertainty_prevents_quiescence_claim(
    monkeypatch,
    tmp_path,
):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
    )

    def deny_children(recursive=False):
        del recursive
        raise FakeAccessDenied("children")

    launcher.children = deny_children
    fake = FakePsutil([launcher])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert launcher.terminated is True
    assert result.post_scan_complete is True
    assert result.quiescence_confirmed is None
    assert result.query_errors[-1].operation == "query_process_children"
    assert result.query_errors[-1].reason_code == "access_denied"


def test_cancel_exact_does_not_signal_reused_pid(monkeypatch, tmp_path):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
        create_time=1.0,
    )
    replacement = FakeProcess(
        10,
        "notepad.exe",
        ["notepad.exe"],
        create_time=2.0,
    )

    def replace_on_children(recursive=False):
        del recursive
        launcher._create_time = 2.0
        return []

    launcher.children = replace_on_children
    fake = FakePsutil(snapshots=[[launcher], [replacement]])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert result.matched_count == 1
    assert result.cancellation_attempted is False
    assert result.quiescence_confirmed is True
    assert launcher.terminated is False
    assert replacement.terminated is False
    assert [item.pid for item in result.stopped] == [10]


def test_cancel_wrapper_true_only_for_matched_confirmed_quiescence(
    monkeypatch, tmp_path
):
    ras_obj = FakeRas(tmp_path)
    launcher = FakeProcess(
        10,
        "Ras.exe",
        ["Ras.exe", str(ras_obj.prj_file), str(ras_obj.plan_path)],
        cwd=str(tmp_path),
    )
    fake = FakePsutil([launcher])
    _patch_psutil(monkeypatch, fake)

    assert RasCmdr.cancel_plan("01", ras_object=ras_obj) is True


@pytest.mark.parametrize(
    ("timeout_seconds", "expected"),
    [("10", 10.0), (True, 1.0), (False, 0.1), (0, 0.1), (-1, 0.1)],
)
def test_cancel_wrapper_preserves_legacy_timeout_coercion(
    monkeypatch,
    timeout_seconds,
    expected,
):
    captured = {}

    def exact(plan_number, *, ras_object, timeout_seconds):
        captured.update(
            plan_number=plan_number,
            ras_object=ras_object,
            timeout_seconds=timeout_seconds,
        )
        return PlanCancellationResult(
            plan_number="01",
            project_path=r"C:\Models\Fox.prj",
            plan_path=r"C:\Models\Fox.p01",
            tmp_hdf_path=r"C:\Models\Fox.p01.tmp.hdf",
            cancellation_attempted=False,
            pre_scan_complete=True,
            post_scan_complete=True,
            quiescence_confirmed=True,
        )

    monkeypatch.setattr(RasCmdr, "cancel_plan_exact", staticmethod(exact))
    marker = object()

    assert (
        RasCmdr.cancel_plan(
            "01",
            ras_object=marker,
            timeout_seconds=timeout_seconds,
        )
        is False
    )
    assert captured == {
        "plan_number": "01",
        "ras_object": marker,
        "timeout_seconds": expected,
    }


def test_cancel_exact_clean_absence_is_quiescent_but_wrapper_is_false(
    monkeypatch, tmp_path
):
    ras_obj = FakeRas(tmp_path)
    fake = FakePsutil([])
    _patch_psutil(monkeypatch, fake)

    result = RasCmdr.cancel_plan_exact("01", ras_object=ras_obj)

    assert result.matched_count == 0
    assert result.cancellation_attempted is False
    assert result.quiescence_confirmed is True
    assert RasCmdr.cancel_plan("01", ras_object=ras_obj) is False


@pytest.mark.parametrize(
    "timeout_seconds",
    [True, False, 0, -1, float("nan"), float("inf"), "10"],
)
def test_cancel_exact_rejects_invalid_timeout_without_process_scan(
    monkeypatch,
    tmp_path,
    timeout_seconds,
):
    ras_obj = FakeRas(tmp_path)
    fake = FakePsutil([])
    _patch_psutil(monkeypatch, fake)

    with pytest.raises(ValueError, match="timeout_seconds"):
        RasCmdr.cancel_plan_exact(
            "01",
            ras_object=ras_obj,
            timeout_seconds=timeout_seconds,
        )

    assert fake.process_iter_calls == 0
