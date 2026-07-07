import logging
from types import SimpleNamespace

from ras_commander.remote import Execution as remote_execution
from ras_commander.remote.Execution import ExecutionResult, compute_parallel_remote


def _fake_worker(worker_id: str, max_parallel_plans: int = 1):
    return SimpleNamespace(
        worker_id=worker_id,
        worker_type="local",
        queue_priority=0,
        max_parallel_plans=max_parallel_plans,
    )


def _fake_ras():
    return SimpleNamespace(project_folder="project")


def test_remote_execution_info_summaries_exclude_per_plan_logs(
    monkeypatch,
    caplog,
) -> None:
    def fake_execute_single_plan(**kwargs):
        return ExecutionResult(
            plan_number=kwargs["plan_number"],
            worker_id=kwargs["worker"].worker_id,
            success=True,
            execution_time=12.3,
        )

    monkeypatch.setattr(
        remote_execution,
        "_execute_single_plan",
        fake_execute_single_plan,
    )

    with caplog.at_level(logging.INFO, logger="ras_commander.remote.Execution"):
        results = compute_parallel_remote(
            ["01", "02"],
            workers=[_fake_worker("worker-a", max_parallel_plans=2)],
            ras_object=_fake_ras(),
            max_concurrent=2,
        )

    assert set(results) == {"01", "02"}
    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "Starting distributed execution of 2 plan(s) across 1 worker(s) "
        "(2 slot(s), max_concurrent=2)",
        "Distributed execution complete: 2 succeeded, 0 failed",
    ]
    assert not any("Submitting plan" in message for message in messages)
    assert not any("completed successfully" in message for message in messages)


def test_remote_execution_debug_keeps_per_plan_details(
    monkeypatch,
    caplog,
) -> None:
    def fake_execute_single_plan(**kwargs):
        return ExecutionResult(
            plan_number=kwargs["plan_number"],
            worker_id=kwargs["worker"].worker_id,
            success=True,
            execution_time=4.5,
        )

    monkeypatch.setattr(
        remote_execution,
        "_execute_single_plan",
        fake_execute_single_plan,
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.Execution"):
        compute_parallel_remote(
            "03",
            workers=[_fake_worker("worker-b")],
            ras_object=_fake_ras(),
        )

    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
    ]

    assert any("Submitting plan 03 to worker worker-b" in message for message in debug_messages)
    assert any("Plan 03 completed successfully (4.5s)" in message for message in debug_messages)


def test_remote_execution_failure_error_includes_worker_and_elapsed(
    monkeypatch,
    caplog,
) -> None:
    def fake_execute_single_plan(**kwargs):
        return ExecutionResult(
            plan_number=kwargs["plan_number"],
            worker_id=kwargs["worker"].worker_id,
            success=False,
            error_message="solver failed",
            execution_time=7.8,
        )

    monkeypatch.setattr(
        remote_execution,
        "_execute_single_plan",
        fake_execute_single_plan,
    )

    with caplog.at_level(logging.ERROR, logger="ras_commander.remote.Execution"):
        results = compute_parallel_remote(
            "04",
            workers=[_fake_worker("worker-c")],
            ras_object=_fake_ras(),
        )

    assert results["04"].success is False
    error_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.ERROR
    ]
    assert error_messages == [
        "Plan 04 failed on worker worker-c after 7.8s: solver failed"
    ]
