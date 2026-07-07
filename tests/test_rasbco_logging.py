import logging
from pathlib import Path

from ras_commander.RasBco import BcoMonitor


class _FakeProcess:
    def __init__(self, returncode):
        self.returncode = returncode

    def poll(self):
        return self.returncode


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == level
        and record.name == "ras_commander.RasBco"
    ]


def test_enable_detailed_logging_failure_warns_with_filename_debug_path(
    monkeypatch,
    tmp_path,
    caplog,
):
    plan_path = tmp_path / "TestProject.p07"

    def fail_read_text(*args, **kwargs):
        raise OSError("blocked")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasBco"):
        assert not BcoMonitor.enable_detailed_logging(plan_path)

    warning_messages = _messages(caplog, logging.WARNING)
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert warning_messages == [
        "Could not enable detailed logging in TestProject.p07: blocked"
    ]
    assert str(plan_path) in debug_text


def test_monitor_process_exit_success_is_debug(tmp_path, caplog):
    monitor = BcoMonitor(
        project_path=tmp_path,
        plan_number="07",
        project_name="TestProject",
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasBco"):
        assert not monitor.monitor_until_signal(_FakeProcess(returncode=0))

    info_messages = _messages(caplog, logging.INFO)
    warning_messages = _messages(caplog, logging.WARNING)
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert "Monitoring TestProject.bco07 for 'Starting Unsteady Flow Computations' signal..." in info_messages
    assert warning_messages == []
    assert "Process for plan 07 exited with code 0 while monitoring TestProject.bco07" in debug_text


def test_monitor_process_exit_failure_is_warning(tmp_path, caplog):
    monitor = BcoMonitor(
        project_path=tmp_path,
        plan_number="07",
        project_name="TestProject",
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasBco"):
        assert not monitor.monitor_until_signal(_FakeProcess(returncode=2))

    warning_messages = _messages(caplog, logging.WARNING)

    assert warning_messages == [
        "Process for plan 07 exited with code 2 while monitoring TestProject.bco07"
    ]


def test_monitor_timeout_warning_has_signal_and_debug_path(tmp_path, caplog):
    monitor = BcoMonitor(
        project_path=tmp_path,
        plan_number="07",
        project_name="TestProject",
        signal_string="Starting Unsteady Flow Computations",
        check_interval=0,
        max_wait_seconds=0,
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasBco"):
        assert not monitor.monitor_until_signal(_FakeProcess(returncode=None))

    warning_messages = _messages(caplog, logging.WARNING)
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert warning_messages == [
        "Monitoring TestProject.bco07 timed out after 0s waiting for "
        "'Starting Unsteady Flow Computations'"
    ]
    assert str(tmp_path / "TestProject.bco07") in debug_text


def test_callback_error_warns_once_then_debugs_repeats(tmp_path, caplog):
    bco_file = tmp_path / "TestProject.bco07"
    bco_file.write_text("first\nsecond\n", encoding="utf-8")
    monitor = BcoMonitor(
        project_path=tmp_path,
        plan_number="07",
        project_name="TestProject",
        message_callback=lambda line: (_ for _ in ()).throw(RuntimeError("bad callback")),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasBco"):
        assert monitor._read_and_callback_new_content() == "first\nsecond\n"

    warning_messages = _messages(caplog, logging.WARNING)
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert warning_messages == [
        "Callback error while monitoring TestProject.bco07: bad callback"
    ]
    assert "Repeated callback error while monitoring" in debug_text
    assert str(bco_file) in debug_text
