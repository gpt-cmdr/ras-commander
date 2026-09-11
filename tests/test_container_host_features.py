"""Host API orchestration tests, independent of hydraulic qualification."""

import hashlib
import importlib
import json
import subprocess

import pandas as pd
import pytest

from ras_commander import ContainerBatchResult, ContainerEvent, RasDocker
from ras_commander.schemas import DATAFRAME_SCHEMAS

module = importlib.import_module("ras_commander.RasDocker")


@pytest.fixture
def project(tmp_path):
    project = tmp_path / "model" / "sample.prj"
    project.parent.mkdir()
    project.write_text("Proj Title=Transport fixture\n")
    return project


def install_transport(monkeypatch, project, failed=False):
    calls = []
    def receipt_for(stage, run_id, plan, version, preparation=None):
        suffixes = ((f".p{plan}.tmp.hdf", f".b{plan}", f".x{plan}")
                    if stage == "prepare" else (f".p{plan}.hdf",))
        artifacts = []
        for suffix in suffixes:
            artifact = project.with_suffix(suffix)
            artifact.write_bytes(b"transport artifact, not a hydraulic result")
            artifacts.append({"path": artifact.name, "size_bytes": artifact.stat().st_size,
                              "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()})
        receipt = {"schema": "ras-commander-job/v1", "run_id": run_id,
                   "command": stage, "project": project.name, "plan": plan,
                   "geometry": plan, "status": "failed" if failed else "succeeded",
                   "runtime": {"kind": "wine" if stage == "prepare" else "native",
                               "hec_ras_version": version},
                   "result": ({"timed_out": False, "full_result_copied": False}
                              if stage == "prepare" else
                              {"success": not failed, "completion_verified": not failed}),
                   "artifacts": artifacts}
        if preparation is not None:
            receipt["preparation_receipt"] = preparation.relative_to(project.parent).as_posix()
        path = project.parent / ".ras-commander" / "runs" / run_id / f"{stage}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt))
        return path

    def run(command, timeout, on_line):
        calls.append(command)
        stage = command[command.index("--project") - 1]
        run_id = command[command.index("--run-id") + 1]
        plan = command[command.index("--plan") + 1]
        image = command[command.index("--project") - 2]
        version = next((v for v in ("7.0.1", "6.6", "6.5") if f"_{v}:" in image), "6.5")
        on_line("stdout", "Computing")
        on_line("stderr", "Solver progress")
        preparation = None
        if stage == "compute":
            if "--prepare-receipt" in command:
                selected = command[command.index("--prepare-receipt") + 1]
                preparation = project.parent / selected.removeprefix("/job/")
            else:
                preparation = (project.parent / ".ras-commander" / "runs"
                               / f"fixture-prepare-{plan}" / "prepare.json")
                if not preparation.exists():
                    receipt_for("prepare", f"fixture-prepare-{plan}", plan, version)
        receipt_for(stage, run_id, plan, version, preparation)
        return subprocess.CompletedProcess(command, 1 if failed else 0, "Computing\n", "Solver progress\n")
    monkeypatch.setattr(module, "run_streaming", run)
    return calls


def test_run_plan_resumes_both_stages_without_transport(monkeypatch, project):
    calls = install_transport(monkeypatch, project)
    prepared, computed = RasDocker.run_plan(project, "01", resume=True)
    assert prepared and computed and len(calls) == 2
    reused_prepared, reused_computed = RasDocker.run_plan(project, "01", resume=True)
    assert reused_prepared.resumed and reused_computed.resumed
    assert len(calls) == 2
    assert reused_prepared.receipt_path == prepared.receipt_path
    assert reused_computed.receipt_path == computed.receipt_path


class Capture:
    def __init__(self):
        self.events = []
        self.legacy = []

    def on_container_event(self, event):
        assert isinstance(event, ContainerEvent)
        self.events.append(event)

    def on_exec_message(self, plan, message):
        self.legacy.append((plan, message))

    def on_exec_complete(self, plan, success, duration):
        self.legacy.append((plan, success, duration))


@pytest.mark.parametrize("cores", [1, 2, 8])
def test_matching_solver_and_container_limits(monkeypatch, project, cores):
    calls = install_transport(monkeypatch, project)
    assert RasDocker.compute_plan(project, 1, num_cores=cores)
    command = calls[0]
    assert command[command.index("--cpus") + 1] == str(cores)
    assert command[command.index("--num-cores") + 1] == str(cores)


@pytest.mark.parametrize("failed", [False, True])
def test_live_events_and_receipt_checked_completion(monkeypatch, project, failed):
    install_transport(monkeypatch, project, failed)
    callback = Capture()
    result = RasDocker.compute_plan(project, 1, stream_callback=callback)
    assert [event.kind for event in callback.events] == ["start", "message", "message", "complete"]
    assert [event.stream for event in callback.events[1:3]] == ["stdout", "stderr"]
    assert all(event.project_path == project for event in callback.events)
    assert callback.events[-1].success is (not failed)
    assert callback.legacy[-1][1] is (not failed)
    assert result.duration_seconds >= 0


def test_callback_error_does_not_mask_success(monkeypatch, project, caplog):
    install_transport(monkeypatch, project)
    class Broken:
        def on_container_event(self, event):
            raise RuntimeError("dashboard offline")
    assert RasDocker.compute_plan(project, 1, stream_callback=Broken())
    assert "callback on_container_event failed" in caplog.text


def test_callback_interrupt_cleans_owned_container(monkeypatch, project):
    calls = install_transport(monkeypatch, project)
    cleanup = []
    monkeypatch.setattr(RasDocker, "_cleanup_owned", lambda *args: cleanup.append(args))
    class Cancel:
        def on_container_event(self, event):
            if event.kind == "message":
                raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        RasDocker.compute_plan(project, 1, stream_callback=Cancel())
    assert len(calls) == len(cleanup) == 1


def test_pipe_error_after_launch_cleans_owned_container(monkeypatch, project):
    cleanup = []
    def broken_transport(*args, **kwargs):
        error = OSError("pipe failed")
        error._ras_container_cli_started = True
        raise error
    monkeypatch.setattr(module, "run_streaming", broken_transport)
    monkeypatch.setattr(RasDocker, "_cleanup_owned", lambda *args: cleanup.append(args))
    result = RasDocker.compute_plan(project, 1)
    assert not result and "transport failed" in result.error
    assert len(cleanup) == 1


def test_resume_avoids_launch_and_reports_reuse(monkeypatch, project):
    calls = install_transport(monkeypatch, project)
    original = RasDocker.compute_plan(project, 1, resume=True)
    callback = Capture()
    reused = RasDocker.compute_plan(project, 1, resume=True, stream_callback=callback)
    assert original and reused and reused.resumed
    assert reused.returncode is None  # No process was launched.
    assert reused.receipt_path == original.receipt_path
    assert len(calls) == 1
    assert [event.kind for event in callback.events] == ["resumed"]
    assert callback.legacy == []  # Never claim a new solver execution.
    project.write_text("Proj Title=Changed model\n")
    changed = RasDocker.compute_plan(project, 1, resume=True, replace_generated=True)
    assert changed and not changed.resumed and len(calls) == 2


def test_default_does_not_snapshot_inputs(monkeypatch, project):
    install_transport(monkeypatch, project)
    monkeypatch.setattr(module, "record_resume", lambda *args: pytest.fail("resume is opt-in"))
    assert RasDocker.compute_plan(project, 1)


def test_run_batch_retains_failures_and_continues(monkeypatch, project):
    calls = install_transport(monkeypatch, project)
    jobs = [{"project_path": project, "plan_number": 1},
            {"project_path": project, "plan_number": 100},
            {"project_path": project, "plan_number": 2}]
    result = RasDocker.run_batch(jobs, stage="compute")
    assert isinstance(result, ContainerBatchResult) and not result
    assert len(calls) == 2 and len(result.results) == 3
    frame = result.summary_df
    assert frame.success.tolist() == [True, False, True]
    assert frame.job_index.tolist() == [0, 1, 2]
    assert "ValueError" in frame.iloc[1].error
    assert frame.iloc[0].compute_receipt and pd.isna(frame.iloc[1].compute_receipt)
    assert list(frame.columns) == [c["name"] for c in DATAFRAME_SCHEMAS["container_batch_summary"]["columns"]]


def test_batch_resume_summary_and_empty_schema(monkeypatch, project):
    calls = install_transport(monkeypatch, project)
    jobs = [{"project_path": project, "plan_number": 1}]
    assert RasDocker.run_batch(jobs, stage="compute", resume=True)
    reused = RasDocker.run_batch(jobs, stage="compute", resume=True)
    assert reused and reused.summary_df.status.tolist() == ["resumed"]
    assert len(calls) == 1
    assert list(RasDocker.run_batch([]).summary_df.columns) == list(reused.summary_df.columns)


def test_batch_stops_on_interrupt(monkeypatch, project):
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(args)
        raise KeyboardInterrupt
    monkeypatch.setattr(RasDocker, "compute_plan", interrupted)
    jobs = [{"project_path": project, "plan_number": 1}] * 2
    with pytest.raises(KeyboardInterrupt):
        RasDocker.run_batch(jobs, stage="compute")
    assert len(calls) == 1
