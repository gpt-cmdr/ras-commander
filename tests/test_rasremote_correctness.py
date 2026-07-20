import importlib
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from ras_commander.RasPlan import RasPlan
from ras_commander.remote import Execution as remote_execution
from ras_commander.remote.Execution import ExecutionResult, compute_parallel_remote


psexec_module = importlib.import_module("ras_commander.remote.PsexecWorker")


class _FakeRasProject:
    def __init__(self, project_folder: Path):
        self.project_folder = project_folder
        self.project_name = "TestProject"
        self.refresh_calls = 0

    def check_initialized(self):
        return None

    def _refresh(self):
        self.refresh_calls += 1
        return None

    get_plan_entries = _refresh
    get_geom_entries = _refresh
    get_flow_entries = _refresh
    get_unsteady_entries = _refresh


def _seed_project(project_folder: Path) -> tuple[_FakeRasProject, Path]:
    project_folder.mkdir(parents=True)
    (project_folder / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    plan_path = project_folder / "TestProject.p01"
    plan_path.write_text(
        "Plan Title=Remote Test\n"
        "UNET D1 Cores= 2\n"
        "UNET D2 Cores= 2\n"
        "PS Cores= 2\n",
        encoding="utf-8",
    )
    return _FakeRasProject(project_folder), plan_path


def _run_psexec(
    monkeypatch,
    tmp_path,
    *,
    system_account=False,
    copy_geometry_outputs=True,
):
    ras_obj, source_plan = _seed_project(tmp_path / "project")
    share_path = tmp_path / "share"
    share_path.mkdir()
    worker = psexec_module.PsexecWorker(
        worker_type="psexec",
        worker_id="remote-a",
        hostname="remote-a",
        share_path=str(share_path),
        worker_folder=r"C:\RasRemote",
        ras_exe_path=r"C:\HEC-RAS\Ras.exe",
        psexec_path="PsExec.exe",
        session_id=7,
        system_account=system_account,
    )
    captured = {}
    geometry_copy_calls = []

    monkeypatch.setattr(
        psexec_module.RasCurrency,
        "get_plan_input_files",
        staticmethod(lambda plan_number, ras_obj: {"plan": source_plan}),
    )
    monkeypatch.setattr(
        psexec_module.RasCurrency,
        "get_plan_hdf_path",
        staticmethod(
            lambda plan_number, ras_obj: ras_obj.project_folder
            / f"{ras_obj.project_name}.p{plan_number}.hdf"
        ),
    )
    monkeypatch.setattr(
        psexec_module.RasCurrency,
        "check_plan_hdf_complete",
        staticmethod(lambda path: True),
    )
    monkeypatch.setattr(
        psexec_module,
        "clear_worker_plan_hdf_artifacts",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        psexec_module,
        "copy_plan_hdf_back",
        lambda *args, **kwargs: source_plan.with_suffix(".p01.hdf"),
    )
    monkeypatch.setattr(
        psexec_module,
        "copy_geometry_outputs_back",
        lambda **kwargs: geometry_copy_calls.append(kwargs),
    )

    bco_module = importlib.import_module("ras_commander.RasBco")
    monkeypatch.setattr(
        bco_module.BcoMonitor,
        "enable_detailed_logging",
        staticmethod(lambda plan_file: None),
    )

    def fake_run(command, **kwargs):
        staged_plan = next(share_path.rglob("TestProject.p01"))
        captured["command"] = command
        captured["staged_plan_text"] = staged_plan.read_text(encoding="utf-8")
        staged_plan.with_suffix(".p01.hdf").write_text("result\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(psexec_module.subprocess, "run", fake_run)

    success = psexec_module.execute_psexec_plan(
        worker=worker,
        plan_number="01",
        ras_obj=ras_obj,
        num_cores=6,
        clear_geompre=False,
        force_rerun=True,
        autoclean=False,
        copy_geometry_outputs=copy_geometry_outputs,
    )
    return success, ras_obj, source_plan, captured, geometry_copy_calls


def _fake_ras():
    return SimpleNamespace(project_folder="project")


def _fake_worker(
    worker_id,
    *,
    max_parallel_plans=1,
    cores_total=None,
    queue_priority=0,
):
    return SimpleNamespace(
        worker_id=worker_id,
        worker_type="local",
        queue_priority=queue_priority,
        max_parallel_plans=max_parallel_plans,
        cores_total=cores_total,
    )


def test_psexec_staged_core_rewrite_does_not_mutate_source(monkeypatch, tmp_path):
    success, ras_obj, source_plan, captured, geometry_copy_calls = _run_psexec(
        monkeypatch,
        tmp_path,
    )

    assert success
    assert captured["staged_plan_text"].count("Cores= 6") == 3
    assert source_plan.read_text(encoding="utf-8").count("Cores= 2") == 3
    assert ras_obj.refresh_calls == 0
    assert len(geometry_copy_calls) == 1


def test_set_num_cores_refreshes_dataframes_by_default(tmp_path):
    ras_obj, plan_path = _seed_project(tmp_path / "project")

    RasPlan.set_num_cores(plan_path, 3, ras_object=ras_obj)

    assert plan_path.read_text(encoding="utf-8").count("Cores= 3") == 3
    assert ras_obj.refresh_calls == 4


def test_set_num_cores_preserves_all_available_zero(tmp_path):
    ras_obj, plan_path = _seed_project(tmp_path / "project")

    RasPlan.set_num_cores(
        plan_path,
        0,
        ras_object=ras_obj,
        refresh_dataframes=False,
    )

    assert plan_path.read_text(encoding="utf-8").count("Cores= 0") == 3
    assert ras_obj.refresh_calls == 0


@pytest.mark.parametrize("system_account", [False, True])
def test_psexec_command_always_targets_configured_session(
    monkeypatch,
    tmp_path,
    system_account,
    caplog,
):
    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.PsexecWorker"):
        success, _, _, captured, _ = _run_psexec(
            monkeypatch,
            tmp_path,
            system_account=system_account,
        )

    assert success
    command = captured["command"]
    assert command[command.index("-i") + 1] == "7"
    assert ("-s" in command) is system_account
    assert any(
        "Executing PsExec command in session 7" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize("session_id", [0, -1, 1.5, True])
def test_psexec_rejects_invalid_session_id(session_id, tmp_path):
    with pytest.raises(ValueError, match="session_id must be a positive integer"):
        psexec_module.PsexecWorker(
            worker_type="psexec",
            hostname="remote-a",
            share_path=str(tmp_path),
            session_id=session_id,
        )


def test_geometry_copyback_can_be_disabled(monkeypatch, tmp_path):
    success, _, _, _, geometry_copy_calls = _run_psexec(
        monkeypatch,
        tmp_path,
        copy_geometry_outputs=False,
    )

    assert success
    assert geometry_copy_calls == []


def test_compute_dispatches_geometry_copyback_option(monkeypatch):
    received = []

    def fake_execute_single_plan(**kwargs):
        received.append(kwargs["copy_geometry_outputs"])
        return ExecutionResult(
            plan_number=kwargs["plan_number"],
            worker_id=kwargs["worker"].worker_id,
            success=True,
        )

    monkeypatch.setattr(remote_execution, "_execute_single_plan", fake_execute_single_plan)

    compute_parallel_remote(
        "01",
        workers=[_fake_worker("worker-a")],
        ras_object=_fake_ras(),
        copy_geometry_outputs=False,
    )

    assert received == [False]


def test_scheduler_enforces_capacity_and_reuses_faster_worker(monkeypatch):
    lock = threading.Lock()
    release_slow_worker = threading.Event()
    active = defaultdict(int)
    max_active = defaultdict(int)
    assignments = defaultdict(list)

    def fake_execute_single_plan(**kwargs):
        worker_id = kwargs["worker"].worker_id
        plan_number = kwargs["plan_number"]
        with lock:
            active[worker_id] += 1
            max_active[worker_id] = max(max_active[worker_id], active[worker_id])
            assignments[worker_id].append(plan_number)

        if worker_id == "slow":
            assert release_slow_worker.wait(timeout=2)
        else:
            time.sleep(0.01)
            if plan_number == "04":
                release_slow_worker.set()

        with lock:
            active[worker_id] -= 1
        return ExecutionResult(plan_number, worker_id, True)

    monkeypatch.setattr(remote_execution, "_execute_single_plan", fake_execute_single_plan)

    results = compute_parallel_remote(
        ["01", "02", "03", "04"],
        workers=[_fake_worker("fast"), _fake_worker("slow")],
        ras_object=_fake_ras(),
        num_cores=1,
    )

    assert all(result.success for result in results.values())
    assert max_active == {"fast": 1, "slow": 1}
    assert assignments["fast"] == ["01", "03", "04"]
    assert assignments["slow"] == ["02"]


def test_scheduler_reconciles_runtime_cores_with_worker_capacity(monkeypatch):
    lock = threading.Lock()
    two_running = threading.Event()
    active = 0
    max_active = 0

    def fake_execute_single_plan(**kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                two_running.set()

        assert two_running.wait(timeout=2)
        time.sleep(0.01)
        with lock:
            active -= 1
        return ExecutionResult(
            kwargs["plan_number"],
            kwargs["worker"].worker_id,
            True,
        )

    monkeypatch.setattr(remote_execution, "_execute_single_plan", fake_execute_single_plan)

    results = compute_parallel_remote(
        ["01", "02", "03", "04"],
        workers=[
            _fake_worker(
                "worker-a",
                max_parallel_plans=4,
                cores_total=8,
            )
        ],
        ras_object=_fake_ras(),
        num_cores=4,
    )

    assert all(result.success for result in results.values())
    assert max_active == 2


def test_watchdog_waits_for_running_task_before_return(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    output_mutated = threading.Event()

    def fake_execute_single_plan(**kwargs):
        started.set()
        assert release.wait(timeout=2)
        output_mutated.set()
        return ExecutionResult(
            kwargs["plan_number"],
            kwargs["worker"].worker_id,
            True,
        )

    def fake_wait(futures, **kwargs):
        assert started.wait(timeout=2)
        threading.Timer(0.05, release.set).start()
        return set(), set(futures)

    worker = _fake_worker("worker-a")
    worker.max_runtime_minutes = 0.001
    monotonic_values = iter([0, 901, 901, 901, 901])
    monkeypatch.setattr(remote_execution, "_execute_single_plan", fake_execute_single_plan)
    monkeypatch.setattr(remote_execution, "wait", fake_wait)
    monkeypatch.setattr(remote_execution._wtime, "monotonic", lambda: next(monotonic_values))

    results = compute_parallel_remote(
        "01",
        workers=[worker],
        ras_object=_fake_ras(),
        num_cores=1,
    )

    assert output_mutated.is_set()
    assert results["01"].success is False
    assert "fleet watchdog" in results["01"].error_message


@pytest.mark.parametrize("max_runtime_minutes", [0, -1, True, "10"])
def test_psexec_rejects_invalid_runtime(max_runtime_minutes, tmp_path):
    with pytest.raises(ValueError, match="max_runtime_minutes must be a positive number"):
        psexec_module.PsexecWorker(
            worker_type="psexec",
            hostname="remote-a",
            share_path=str(tmp_path),
            max_runtime_minutes=max_runtime_minutes,
        )


@pytest.mark.parametrize("max_runtime_minutes", [0, -1, True, "10"])
def test_compute_rejects_invalid_worker_runtime(max_runtime_minutes):
    worker = _fake_worker("worker-a")
    worker.max_runtime_minutes = max_runtime_minutes

    with pytest.raises(ValueError, match="max_runtime_minutes"):
        compute_parallel_remote(
            "01",
            workers=[worker],
            ras_object=_fake_ras(),
            num_cores=1,
        )


@pytest.mark.parametrize("num_cores", [-1, 1.5, True])
def test_set_num_cores_rejects_invalid_values(num_cores, tmp_path):
    ras_obj, plan_path = _seed_project(tmp_path / "project")

    with pytest.raises(ValueError, match="num_cores must be a nonnegative integer"):
        RasPlan.set_num_cores(plan_path, num_cores, ras_object=ras_obj)


@pytest.mark.parametrize("num_cores", [0, -1, 1.5, True])
def test_remote_num_cores_must_be_positive_integer(num_cores, tmp_path):
    ras_obj, _ = _seed_project(tmp_path / "project")

    with pytest.raises(ValueError, match="num_cores must be an integer"):
        compute_parallel_remote(
            "01",
            workers=[_fake_worker("worker-a")],
            ras_object=ras_obj,
            num_cores=num_cores,
        )

    with pytest.raises(ValueError, match="num_cores must be an integer"):
        psexec_module.execute_psexec_plan(
            worker=None,
            plan_number="01",
            ras_obj=ras_obj,
            num_cores=num_cores,
            clear_geompre=False,
        )
