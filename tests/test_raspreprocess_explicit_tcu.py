"""TCU assent requires an explicit opt-in and exact current launch identity."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import psutil
import pytest

from ras_commander import RasPreprocess, RasTcu
from ras_commander.ComputeResults import PreprocessResult

module = importlib.import_module("ras_commander.RasPreprocess")


@pytest.fixture
def probe(monkeypatch):
    process = SimpleNamespace(pid=1234, poll=lambda: None)
    root = SimpleNamespace(pid=1234, create_time=lambda: 1000.5)
    child = SimpleNamespace(
        pid=5678, name=lambda: "Ras.exe", create_time=lambda: 1001.0,
        exe=lambda: "C:/HEC/6.0/Ras.exe", parents=lambda: [root],
    )
    root.children = lambda recursive: [child]
    monkeypatch.setattr(psutil, "Process", lambda pid: {1234: root, 5678: child}[pid])
    monkeypatch.setattr(RasPreprocess, "_detect_running_tcu_dialog", lambda _p: RasPreprocess._TCU_BLOCKING_ERROR)
    monkeypatch.setattr(module.time, "monotonic", lambda: 10.0)
    return dict(
        process=process, accept_tcu=True, launch_create_time=1000.5,
        ras_exe=Path("C:/HEC/6.0/Ras.exe"), deadline=70.0,
        receipts=[], acceptance_state={},
    )


def test_default_blocker_never_accepts_terms(probe, monkeypatch):
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("No opt-in"))
    probe["accept_tcu"] = False
    assert RasPreprocess._preprocessing_tcu_probe(**probe) == RasPreprocess._TCU_BLOCKING_ERROR
    assert probe["receipts"] == []


def test_explicit_opt_in_uses_exact_scope_and_keeps_compute_alive(probe, monkeypatch):
    calls = []

    def accept(pid, **kwargs):
        calls.append((pid, kwargs))
        assert probe["process"].poll() is None
        return {"dialog_closed": True, "actions": [{"action": "agree"}]}

    monkeypatch.setattr(RasTcu, "accept_running_terms", accept)
    monkeypatch.setattr(RasPreprocess, "_terminate_process_tree", lambda *_a: pytest.fail("Acceptance must not stop compute"))
    assert RasPreprocess._preprocessing_tcu_probe(**probe) is None
    assert calls == [(5678, {
        "expected_create_time": 1001.0, "ras_version": str(probe["ras_exe"]),
        "operator_acceptance": True, "timeout": 60.0,
    })]
    assert probe["receipts"][0]["success"] is True
    assert probe["receipts"][0]["dialog_closed"] is True
    assert probe["process"].poll() is None


def test_ambiguous_ras_descendants_refuse_assent(probe, monkeypatch):
    root = psutil.Process(1234)
    first = psutil.Process(5678)
    second = SimpleNamespace(
        pid=5679, name=first.name, create_time=first.create_time,
        exe=first.exe, parents=first.parents,
    )
    root.children = lambda recursive: [first, second]
    monkeypatch.setattr(psutil, "Process", lambda pid: {1234: root, 5678: first, 5679: second}[pid])
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("Ambiguous RAS ownership"))
    reason = RasPreprocess._preprocessing_tcu_probe(**probe)
    assert "exactly one witnessed" in reason


def test_changed_descendant_ancestry_refuses_assent(probe, monkeypatch):
    psutil.Process(5678).parents = lambda: []
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("Lost ancestry"))
    assert "ancestry changed" in RasPreprocess._preprocessing_tcu_probe(**probe)


def test_reused_launcher_refuses_assent(probe, monkeypatch):
    psutil.Process(1234).create_time = lambda: 1002.0
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("Reused root PID"))
    assert "launcher PID was reused" in RasPreprocess._preprocessing_tcu_probe(**probe)


def test_reused_descendant_refuses_assent(probe, monkeypatch):
    root = psutil.Process(1234)
    replacement = SimpleNamespace(create_time=lambda: 1002.0)
    monkeypatch.setattr(psutil, "Process", lambda pid: root if pid == 1234 else replacement)
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("Reused child PID"))
    assert "descendant PID was reused" in RasPreprocess._preprocessing_tcu_probe(**probe)


def test_different_runtime_descendant_refuses_assent(probe, monkeypatch):
    psutil.Process(5678).exe = lambda: "C:/other/Ras.exe"
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("Wrong runtime"))
    assert "exactly one witnessed" in RasPreprocess._preprocessing_tcu_probe(**probe)


def test_unreadable_descendant_refuses_assent(probe, monkeypatch):
    def denied():
        raise psutil.AccessDenied(5678)

    psutil.Process(5678).name = denied
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("Unknown child"))
    assert RasPreprocess._preprocessing_tcu_probe(**probe).startswith(RasPreprocess._TCU_BLOCKING_ERROR)


@pytest.mark.parametrize("outcome", [None, {"dialog_closed": False}, RuntimeError("PID reused")])
def test_acceptance_failure_keeps_tcu_blocking(probe, monkeypatch, outcome):
    def accept(*_args, **_kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(RasTcu, "accept_running_terms", accept)
    reason = RasPreprocess._preprocessing_tcu_probe(**probe)
    assert reason.startswith(RasPreprocess._TCU_BLOCKING_ERROR)
    assert "acceptance failed" in reason
    assert probe["receipts"][0]["success"] is False


@pytest.mark.parametrize("created", [None, 0.0, float("inf")])
def test_missing_launch_identity_never_accepts(probe, monkeypatch, created):
    probe["launch_create_time"] = created
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("No exact identity"))
    assert RasPreprocess._preprocessing_tcu_probe(**probe).startswith(RasPreprocess._TCU_BLOCKING_ERROR)
    assert probe["receipts"][0]["success"] is False


@pytest.mark.parametrize("deadline", [10.0, 5.0, float("inf")])
def test_no_unbounded_or_expired_acceptance_timeout(probe, monkeypatch, deadline):
    probe["deadline"] = deadline
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("Invalid remaining time"))
    assert RasPreprocess._preprocessing_tcu_probe(**probe).startswith(RasPreprocess._TCU_BLOCKING_ERROR)


def test_supervision_failure_is_not_an_assent_trigger(probe, monkeypatch):
    reason = RasPreprocess._TCU_SUPERVISION_ERROR
    monkeypatch.setattr(RasPreprocess, "_detect_running_tcu_dialog", lambda _p: reason)
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: pytest.fail("No proven TCU"))
    assert RasPreprocess._preprocessing_tcu_probe(**probe) == reason
    assert probe["receipts"] == []


def test_persistent_dialog_does_not_trigger_repeated_assent(probe, monkeypatch):
    calls = []
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: calls.append(True) or {"dialog_closed": True})
    assert RasPreprocess._preprocessing_tcu_probe(**probe) is None
    assert "remained after explicit acceptance" in RasPreprocess._preprocessing_tcu_probe(**probe)
    assert calls == [True]


@pytest.mark.parametrize("value", [None, 1, "yes", []])
def test_accept_tcu_requires_bool(value):
    with pytest.raises(ValueError, match="accept_tcu must be a bool"):
        RasPreprocess.preprocess_plan("01", accept_tcu=value)


@pytest.mark.parametrize("opt_in", [False, True])
def test_preprocess_captures_launch_identity_once_only_for_opt_in(tmp_path, monkeypatch, opt_in):
    events = []
    process = SimpleNamespace(pid=1234, returncode=None)
    process.poll = lambda: process.returncode
    ras = SimpleNamespace(
        project_folder=tmp_path, project_name="fixture", ras_exe_path=tmp_path / "Ras.exe",
        plan_df=pd.DataFrame([{"plan_number": "01", "Geom File": "g03"}]),
        check_initialized=lambda: None,
    )
    for filename in ["fixture.prj", "fixture.p01", "Ras.exe"]:
        (tmp_path / filename).write_text("fixture")
    monkeypatch.setattr(RasPreprocess, "_plan_precipitation_mode", lambda *_a: "none")
    monkeypatch.setattr(RasPreprocess, "_missing_land_classification_files", lambda *_a: [])
    monkeypatch.setattr(RasPreprocess, "_tcu_supervision_availability_error", lambda: None)
    monkeypatch.setattr(RasPreprocess, "_detect_running_tcu_dialog", lambda _p: RasPreprocess._TCU_BLOCKING_ERROR)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_a, **_k: events.append("launch") or process)
    root = SimpleNamespace(pid=1234, create_time=lambda: 1000.5)
    child = SimpleNamespace(
        pid=5678, name=lambda: "Ras.exe", create_time=lambda: 1001.0,
        exe=lambda: str(ras.ras_exe_path), parents=lambda: [root],
    )
    root.children = lambda recursive: [child]

    def identity(pid):
        events.append("ctime" if "monitor" not in events else f"identity:{pid}")
        return {1234: root, 5678: child}[pid]

    monkeypatch.setattr(psutil, "Process", identity)
    monkeypatch.setattr(RasTcu, "accept_running_terms", lambda *_a, **_k: events.append("accept") or {"dialog_closed": True})
    monkeypatch.setattr(RasPreprocess, "_terminate_process_tree", lambda _p: events.append("cleanup"))

    class Monitor:
        blocked_reason = None
        signal_source = None
        enable_detailed_logging = staticmethod(lambda _plan: True)

        def __init__(self, **kwargs):
            events.append("monitor")
            self.blocker = kwargs["blocking_condition"]

        def monitor_until_signal(self, _process):
            self.blocked_reason = self.blocker()
            assert "cleanup" not in events
            if opt_in:
                assert self.blocked_reason is None
                process.returncode = 1
            return False

    monkeypatch.setattr(module, "BcoMonitor", Monitor)
    result = RasPreprocess.preprocess_plan("01", ras_object=ras, clear_existing=False, accept_tcu=opt_in)
    assert result.success is False  # No real HEC-RAS process was run by this test.
    if opt_in:
        assert events[:3] == ["launch", "ctime", "monitor"]
        assert events.count("ctime") == 1
        assert result.tcu_acceptance_receipts[0]["success"] is True
        assert "cleanup" not in events
    else:
        assert "ctime" not in events and "accept" not in events
        assert result.signal_source == "blocked_legal_dialog"
        assert result.tcu_acceptance_receipts == []


def test_result_receipt_lists_are_not_shared():
    first, second = PreprocessResult(False), PreprocessResult(False)
    first.tcu_acceptance_receipts.append({"success": True})
    assert second.tcu_acceptance_receipts == []
