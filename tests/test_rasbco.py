import os
import time
from pathlib import Path

from ras_commander.RasBco import BcoMonitor


class _RunningProcess:
    returncode = None

    def poll(self):
        return None


def test_monitor_returns_immediately_with_blocked_reason(tmp_path: Path):
    monitor = BcoMonitor(
        project_path=tmp_path,
        plan_number="01",
        project_name="fixture",
        check_interval=0,
        max_wait_seconds=10,
        blocking_condition=lambda: "known modal is blocking execution",
    )

    assert monitor.monitor_until_signal(_RunningProcess()) is False
    assert monitor.blocked_reason == "known modal is blocking execution"


def test_monitor_ignores_probe_failure_and_can_detect_signal(tmp_path: Path):
    bco_path = tmp_path / "fixture.bco01"
    bco_path.write_text("Starting Unsteady Flow Computations\n", encoding="utf-8")
    future = time.time() + 5
    os.utime(bco_path, (future, future))

    def broken_probe():
        raise RuntimeError("probe unavailable")

    monitor = BcoMonitor(
        project_path=tmp_path,
        plan_number="01",
        project_name="fixture",
        check_interval=0.01,
        max_wait_seconds=1,
        blocking_condition=broken_probe,
    )
    assert monitor.monitor_until_signal(_RunningProcess()) is True
    assert monitor.blocked_reason is None
