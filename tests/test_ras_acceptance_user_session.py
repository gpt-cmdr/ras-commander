"""Unit-only coverage for zero-automation user-driven TCU acceptance."""

from __future__ import annotations

import importlib
import importlib.util
import json
from contextlib import nullcontext
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

acceptance_module = importlib.import_module("ras_commander.RasAcceptanceState")
from ras_commander.RasAcceptanceState import (  # noqa: E402
    AcceptanceProbeResult,
    RasAcceptanceState,
)
from ras_commander.RasDialogWatchdog import ObservedWindow  # noqa: E402


SOURCE_EVIDENCE = "a" * 64
AUTHORIZATION = "approved-change-record-4821"
PROFILE_TOKEN = "disposable-prefix-instance-d1f7"
LEGAL_BODY = (
    "HEC-RAS Terms and Conditions for Use | "
    "I agree to the above Terms and Conditions for Use | Cancel | Next"
)


def _fake_executable(tmp_path: Path, version: str = "4.0") -> Path:
    folder = tmp_path / version
    folder.mkdir(parents=True, exist_ok=True)
    executable = folder / "Ras.exe"
    executable.write_bytes(f"ras-{version}".encode())
    return executable


def _legal_window(pid: int = 4242) -> ObservedWindow:
    return ObservedWindow(
        hwnd=101,
        pid=pid,
        class_name="ThunderRT6FormDC",
        title="Please read the following TCU carefully",
        body=LEGAL_BODY,
        owner_hwnd=0,
        enabled=True,
        legal_reason="HEC-RAS TCU",
    )


def _main_window(pid: int = 4242, *, enabled: bool = True) -> ObservedWindow:
    return ObservedWindow(
        hwnd=102,
        pid=pid,
        class_name="ThunderRT6Main",
        title="RAS",
        body="",
        owner_hwnd=0,
        enabled=enabled,
        legal_reason=None,
    )


def _owned_tcu_companion(pid: int = 4242) -> ObservedWindow:
    return ObservedWindow(
        hwnd=103,
        pid=pid,
        class_name="ThunderRT6FormDC",
        title="HEC-RAS 4.0",
        body="",
        owner_hwnd=101,
        enabled=False,
        legal_reason=None,
    )


class _FakeProcess:
    def __init__(self, *, pid=4242, poll_values=None):
        self.pid = pid
        self._poll_values = list(poll_values or [])

    def poll(self):
        if self._poll_values:
            return self._poll_values.pop(0)
        return None


class _ReadOnlyWatchdog:
    """Deliberately has no start/scan/dismiss method."""

    def __init__(self, windows, *, terminate=True, observe_error=None):
        self._windows = list(windows)
        self._last = self._windows[-1] if self._windows else ()
        self._terminate = terminate
        self._observe_error = observe_error
        self.dismissed = []
        self.blocked = []
        self.supervision_error = None
        self.registered = []
        self.terminated = []

    def require_available(self):
        return None

    def add_pid(self, pid):
        self.registered.append(pid)

    def scoped_pids(self):
        return set(self.registered)

    def observe_windows(self):
        if self._observe_error is not None:
            raise self._observe_error
        if self._windows:
            self._last = self._windows.pop(0)
        return tuple(self._last)

    def terminate_process_tree(self, pid):
        self.terminated.append(pid)
        return self._terminate


def _ready_probe(identity, timeout_seconds: float, observed_at="2026-07-18T00:00:00Z"):
    return AcceptanceProbeResult(
        identity=identity,
        status="ready",
        started=True,
        visible_window_seen=True,
        visible_titles=("RAS",),
        blocked_reason=None,
        blocked_titles=(),
        interactions=0,
        process_tree_terminated=True,
        survivors=(),
        elapsed_seconds=timeout_seconds,
        observed_at_utc=observed_at,
        main_window_signature=("ThunderRT6Main", "RAS", "0", "1"),
        topology_signatures=("5001|ThunderRT6Main|RAS|owner=0|enabled=1",),
        observed_process_ids=(5001,),
    )


def _install_session_mocks(
    monkeypatch,
    tmp_path,
    *,
    version="4.0",
    windows=None,
    terminate=True,
    observe_error=None,
    process=None,
    survivor=False,
    probes=None,
):
    executable = _fake_executable(tmp_path, version)
    identity = RasAcceptanceState.executable_identity(
        executable,
        expected_version=version,
        verify_executable_version=False,
    )
    monkeypatch.setattr(
        RasAcceptanceState,
        "executable_identity",
        lambda *_args, **_kwargs: identity,
    )
    monkeypatch.setattr(RasAcceptanceState, "_target_running", lambda _identity: False)
    monkeypatch.setattr(
        acceptance_module,
        "_cross_process_lock",
        lambda _key: nullcontext(),
    )
    watchdog = _ReadOnlyWatchdog(
        windows
        or [
            (_legal_window(),),
            (_legal_window(),),
            (_main_window(enabled=False),),
            (_main_window(),),
            (_main_window(),),
            (_main_window(),),
        ],
        terminate=terminate,
        observe_error=observe_error,
    )
    monkeypatch.setattr(
        acceptance_module,
        "DialogWatchdog",
        lambda **_kwargs: watchdog,
    )
    process = process or _FakeProcess()
    popen_calls = []

    def popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return process

    monkeypatch.setattr(acceptance_module.subprocess, "Popen", popen)
    monkeypatch.setattr(
        acceptance_module,
        "psutil",
        SimpleNamespace(pid_exists=lambda _pid: survivor),
    )
    probe_results = list(
        probes
        or [
            _ready_probe(identity, 0.01, "restart-1"),
            _ready_probe(identity, 0.01, "restart-2"),
        ]
    )
    probe_calls = []

    def probe(*args, **kwargs):
        probe_calls.append((args, kwargs))
        return probe_results.pop(0)

    monkeypatch.setattr(RasAcceptanceState, "probe", probe)
    return executable, identity, watchdog, popen_calls, probe_calls


def _run(executable, **kwargs):
    parameters = dict(
        expected_version=executable.parent.name,
        source_evidence_sha256=SOURCE_EVIDENCE,
        destination_is_disposable=True,
        authorization_reference=AUTHORIZATION,
        profile_instance_token=PROFILE_TOKEN,
        session_timeout_seconds=1.0,
        legal_observation_seconds=0.02,
        main_ready_seconds=0.02,
        restart_timeout_seconds=0.01,
        restart_ready_seconds=0.005,
        poll_interval_seconds=0.05,
    )
    parameters.update(kwargs)
    return RasAcceptanceState.run_user_driven_acceptance(executable, **parameters)


def test_user_session_observes_tcu_without_automation_and_verifies_two_restarts(
    monkeypatch,
    tmp_path,
):
    executable, identity, watchdog, popen_calls, probe_calls = _install_session_mocks(
        monkeypatch,
        tmp_path,
    )
    signals = []

    receipt = _run(executable, status_callback=signals.append)

    assert receipt.passed is True
    assert receipt.target == identity
    assert receipt.source_evidence_sha256 == SOURCE_EVIDENCE
    assert receipt.destination_is_disposable is True
    assert receipt.automated_ui_interactions == 0
    assert receipt.process_tree_terminated is True
    assert receipt.survivors == ()
    assert len(receipt.restart_probes) == 2
    assert signals == ["AWAITING_USER"]
    assert len(popen_calls) == 1
    assert popen_calls[0][0] == [identity.path]
    assert len(probe_calls) == 2
    assert watchdog.terminated == [4242]
    serialized = json.dumps(asdict(receipt), sort_keys=True)
    assert AUTHORIZATION not in serialized
    assert PROFILE_TOKEN not in serialized
    assert LEGAL_BODY not in serialized
    assert receipt.authorization_reference_sha256 != AUTHORIZATION
    assert receipt.profile_instance_token_sha256 != PROFILE_TOKEN
    assert receipt.legal_dialog_body_sha256


def test_user_session_has_no_executable_version_verification_escape_hatch(
    monkeypatch,
    tmp_path,
):
    executable, identity, _watchdog, _popen, _probes = _install_session_mocks(
        monkeypatch,
        tmp_path,
    )
    calls = []

    def identity_check(*_args, **kwargs):
        calls.append(kwargs)
        return identity

    monkeypatch.setattr(RasAcceptanceState, "executable_identity", identity_check)

    receipt = _run(executable)

    assert receipt.passed is True
    assert calls == [
        {
            "expected_version": "4.0",
            "verify_executable_version": True,
        }
    ]


def test_transient_enabled_main_before_tcu_is_normal_startup_not_acceptance(
    monkeypatch,
    tmp_path,
):
    windows = [
        (_main_window(),),
        (_legal_window(),),
        (_legal_window(),),
        (_main_window(enabled=False),),
        (_main_window(),),
        (_main_window(),),
        (_main_window(),),
    ]
    executable, _identity, _watchdog, _popen, probe_calls = _install_session_mocks(
        monkeypatch,
        tmp_path,
        windows=windows,
    )

    receipt = _run(executable)

    assert receipt.passed is True
    assert len(probe_calls) == 2


def test_40_tcu_phase_allows_exact_disabled_owned_hecras_companion(
    monkeypatch,
    tmp_path,
):
    tcu_topology = (
        _main_window(),
        _owned_tcu_companion(),
        _legal_window(),
    )
    windows = [
        tcu_topology,
        tcu_topology,
        (_main_window(),),
        (_main_window(),),
        (_main_window(),),
    ]
    executable, _identity, _watchdog, _popen, probe_calls = _install_session_mocks(
        monkeypatch,
        tmp_path,
        windows=windows,
    )

    receipt = _run(executable)

    assert receipt.passed is True
    assert len(probe_calls) == 2


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"authorization_reference": "  "}, "authorization-reference"),
        ({"source_evidence_sha256": "ABC"}, "64 lowercase hexadecimal"),
        ({"destination_is_disposable": False}, "explicitly disposable"),
        ({"profile_instance_token": ""}, "profile-instance-token"),
    ],
)
def test_user_session_rejects_invalid_authority_before_identity_or_launch(
    monkeypatch,
    overrides,
    message,
):
    identity_calls = []
    launch_calls = []
    monkeypatch.setattr(
        RasAcceptanceState,
        "executable_identity",
        lambda *_a, **_k: identity_calls.append(True),
    )
    monkeypatch.setattr(
        acceptance_module.subprocess,
        "Popen",
        lambda *_a, **_k: launch_calls.append(True),
    )
    parameters = dict(
        expected_version="4.0",
        source_evidence_sha256=SOURCE_EVIDENCE,
        destination_is_disposable=True,
        authorization_reference=AUTHORIZATION,
        profile_instance_token=PROFILE_TOKEN,
    )
    parameters.update(overrides)

    with pytest.raises(ValueError, match=message):
        RasAcceptanceState.run_user_driven_acceptance(
            r"C:\HEC-RAS\4.0\Ras.exe",
            **parameters,
        )

    assert identity_calls == []
    assert launch_calls == []


@pytest.mark.parametrize("beta_reference", [None, "", AUTHORIZATION])
def test_beta_session_requires_distinct_beta_authorization_before_launch(
    monkeypatch,
    tmp_path,
    beta_reference,
):
    executable = _fake_executable(tmp_path, "6.7 Beta 5")
    identity = RasAcceptanceState.executable_identity(
        executable,
        expected_version="6.7 Beta 5",
        verify_executable_version=False,
    )
    monkeypatch.setattr(
        RasAcceptanceState,
        "executable_identity",
        lambda *_a, **_k: identity,
    )
    launch_calls = []
    monkeypatch.setattr(
        acceptance_module.subprocess,
        "Popen",
        lambda *_a, **_k: launch_calls.append(True),
    )

    with pytest.raises(ValueError, match="beta authorization"):
        RasAcceptanceState.run_user_driven_acceptance(
            executable,
            expected_version="6.7 Beta 5",
            source_evidence_sha256=SOURCE_EVIDENCE,
            destination_is_disposable=True,
            authorization_reference=AUTHORIZATION,
            beta_authorization_reference=beta_reference,
            profile_instance_token=PROFILE_TOKEN,
        )

    assert launch_calls == []


@pytest.mark.parametrize(
    ("windows", "process", "observe_error", "message"),
    [
        ([(_main_window(),)], None, None, "before the required live TCU"),
        (
            [
                (
                    ObservedWindow(
                        301,
                        4242,
                        "ThunderRT6FormDC",
                        "Unexpected prompt",
                        "Continue?",
                        0,
                        True,
                        None,
                    ),
                )
            ],
            None,
            None,
            "unrecognized visible window",
        ),
        ([], None, RuntimeError("enumeration denied"), "inspection failed"),
        ([], _FakeProcess(poll_values=[1]), None, "exited before"),
    ],
)
def test_user_session_fails_closed_and_terminates_on_initial_supervision_errors(
    monkeypatch,
    tmp_path,
    windows,
    process,
    observe_error,
    message,
):
    executable, _identity, watchdog, _popen, probe_calls = _install_session_mocks(
        monkeypatch,
        tmp_path,
        windows=windows,
        process=process,
        observe_error=observe_error,
    )

    with pytest.raises(RuntimeError, match=message):
        _run(executable)

    assert watchdog.terminated == [4242]
    assert probe_calls == []


def test_user_session_rejects_generic_legal_dialog_without_exact_tcu_body(
    monkeypatch,
    tmp_path,
):
    generic = ObservedWindow(
        305,
        4242,
        "#32770",
        "License Agreement",
        "Read this license agreement",
        0,
        True,
        "legal",
    )
    executable, _identity, watchdog, _popen, probe_calls = _install_session_mocks(
        monkeypatch,
        tmp_path,
        windows=[(generic,)],
    )

    with pytest.raises(RuntimeError, match="did not match the required HEC-RAS TCU"):
        _run(executable)

    assert watchdog.terminated == [4242]
    assert probe_calls == []


def test_unknown_window_error_contains_only_sanitized_topology(
    monkeypatch,
    tmp_path,
):
    unknown = ObservedWindow(
        306,
        4242,
        "MysteryWindow",
        "Unexpected title",
        "SECRET CONTROL BODY",
        101,
        False,
        None,
    )
    executable, _identity, _watchdog, _popen, _probes = _install_session_mocks(
        monkeypatch,
        tmp_path,
        windows=[(unknown,)],
    )

    with pytest.raises(RuntimeError) as captured:
        _run(executable)

    message = str(captured.value)
    assert "MysteryWindow" in message
    assert "Unexpected title" in message
    assert "101" in message
    assert "SECRET CONTROL BODY" not in message


@pytest.mark.parametrize(
    ("terminate", "survivor"),
    [(False, False), (True, True)],
)
def test_user_session_requires_verified_termination_before_restarts(
    monkeypatch,
    tmp_path,
    terminate,
    survivor,
):
    executable, _identity, watchdog, _popen, probe_calls = _install_session_mocks(
        monkeypatch,
        tmp_path,
        terminate=terminate,
        survivor=survivor,
    )

    with pytest.raises(RuntimeError, match="termination could not be verified"):
        _run(executable)

    assert watchdog.terminated == [4242]
    assert probe_calls == []


def test_user_session_rejects_failed_second_full_duration_restart(
    monkeypatch,
    tmp_path,
):
    executable = _fake_executable(tmp_path)
    identity = RasAcceptanceState.executable_identity(
        executable,
        expected_version="4.0",
        verify_executable_version=False,
    )
    good = _ready_probe(identity, 0.01, "restart-1")
    short = replace(
        _ready_probe(identity, 0.01, "restart-2"),
        elapsed_seconds=0.009,
    )
    executable, _identity, _watchdog, _popen, probe_calls = _install_session_mocks(
        monkeypatch,
        tmp_path,
        probes=[good, short],
    )

    with pytest.raises(RuntimeError, match="restart 2 did not produce strict"):
        _run(executable)

    assert len(probe_calls) == 2


def test_qualification_cli_launches_only_through_public_api_and_writes_hash_receipt(
    monkeypatch,
    tmp_path,
    capsys,
):
    script = (
        Path(__file__).parent
        / "qualification"
        / "run_user_acceptance_session.py"
    )
    spec = importlib.util.spec_from_file_location("user_acceptance_cli", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    @dataclass
    class DummyReceipt:
        authorization_reference_sha256: str = "b" * 64
        profile_instance_token_sha256: str = "c" * 64
        legal_dialog_body_sha256: str = "d" * 64

        @property
        def passed(self):
            return True

    calls = []

    def public_api(*args, **kwargs):
        calls.append((args, kwargs))
        kwargs["status_callback"]("AWAITING_USER")
        return DummyReceipt()

    monkeypatch.setattr(
        module.RasAcceptanceState,
        "run_user_driven_acceptance",
        public_api,
    )
    output = tmp_path / "receipt.json"
    result = module.main(
        [
            "--ras-executable",
            str(tmp_path / "Ras.exe"),
            "--expected-version",
            "4.0",
            "--source-evidence-sha256",
            SOURCE_EVIDENCE,
            "--destination-is-disposable",
            "--authorization-reference",
            AUTHORIZATION,
            "--profile-instance-token",
            PROFILE_TOKEN,
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert len(calls) == 1
    assert calls[0][1]["destination_is_disposable"] is True
    stdout = capsys.readouterr().out
    assert stdout.count("AWAITING_USER") == 1
    payload_text = output.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    assert payload["passed"] is True
    assert AUTHORIZATION not in payload_text
    assert PROFILE_TOKEN not in payload_text
