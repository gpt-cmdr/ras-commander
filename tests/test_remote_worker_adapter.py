import inspect
import importlib
from pathlib import Path

import pytest

from ras_commander.remote.Execution import _execute_single_plan
from ras_commander.remote.LocalWorker import LocalWorker
from ras_commander.remote.RasWorker import (
    RasWorker,
    WorkerExecutionOutcome,
    WorkerExecutionRequest,
    init_ras_worker,
)


class FakeRasProject:
    def __init__(self, project_folder: Path):
        self.project_folder = Path(project_folder)
        self.project_name = "TestProject"


class RecordingWorker(RasWorker):
    def __init__(self):
        super().__init__(worker_type="recording", worker_id="recording-1")
        self.request = None

    def execute_plan(self, request):
        self.request = request
        return WorkerExecutionOutcome(success=True, hdf_path="result.hdf")


def test_execute_single_plan_calls_worker_execute_plan(tmp_path):
    worker = RecordingWorker()
    ras_object = FakeRasProject(tmp_path)

    result = _execute_single_plan(
        worker=worker,
        plan_number="01",
        ras_object=ras_object,
        num_cores=2,
        clear_geompre=True,
        force_geompre=True,
        force_rerun=True,
        sub_worker_id=3,
        autoclean=False,
    )

    assert result.success is True
    assert result.hdf_path == "result.hdf"
    assert isinstance(worker.request, WorkerExecutionRequest)
    assert worker.request.plan_number == "01"
    assert worker.request.num_cores == 2
    assert worker.request.clear_geompre is True
    assert worker.request.force_geompre is True
    assert worker.request.force_rerun is True
    assert worker.request.sub_worker_id == 3
    assert worker.request.autoclean is False


def test_base_worker_execute_plan_reports_unimplemented(tmp_path):
    worker = RasWorker(worker_type="ssh", worker_id="ssh-1")
    ras_object = FakeRasProject(tmp_path)

    result = _execute_single_plan(
        worker=worker,
        plan_number="01",
        ras_object=ras_object,
        num_cores=4,
        clear_geompre=False,
        force_geompre=False,
        force_rerun=False,
        sub_worker_id=1,
    )

    assert result.success is False
    assert "not implemented" in result.error_message


def test_local_worker_execute_plan_delegates_to_legacy_function(monkeypatch, tmp_path):
    ras_object = FakeRasProject(tmp_path)
    (tmp_path / "TestProject.p01.hdf").write_text("", encoding="utf-8")
    worker = LocalWorker(worker_type="local", worker_folder=str(tmp_path / "workers"))
    calls = {}

    def fake_execute_local_plan(**kwargs):
        calls.update(kwargs)
        return True

    local_worker_module = importlib.import_module("ras_commander.remote.LocalWorker")
    monkeypatch.setattr(local_worker_module, "execute_local_plan", fake_execute_local_plan)

    outcome = worker.execute_plan(
        WorkerExecutionRequest(
            plan_number="01",
            ras_object=ras_object,
            num_cores=2,
            clear_geompre=True,
            force_geompre=True,
            force_rerun=True,
            sub_worker_id=2,
            autoclean=False,
        )
    )

    assert outcome.success is True
    assert outcome.hdf_path == str(tmp_path / "TestProject.p01.hdf")
    assert calls["worker"] is worker
    assert calls["ras_obj"] is ras_object
    assert calls["force_geompre"] is True
    assert calls["force_rerun"] is True


def test_init_ras_worker_local_and_invalid_type(tmp_path):
    worker = init_ras_worker("local", worker_folder=str(tmp_path / "workers"))

    assert isinstance(worker, LocalWorker)
    assert Path(worker.worker_folder).exists()

    with pytest.raises(ValueError):
        init_ras_worker("unknown")


def test_docker_legacy_function_accepts_force_flags():
    from ras_commander.remote.DockerWorker import execute_docker_plan

    signature = inspect.signature(execute_docker_plan)

    assert "force_geompre" in signature.parameters
    assert "force_rerun" in signature.parameters
