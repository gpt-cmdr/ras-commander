"""Fail-closed fake-win32 tests for the authorized legacy UI fallback."""

from __future__ import annotations

import importlib
import importlib.util
import json
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

acceptance_module = importlib.import_module("ras_commander.RasAcceptanceState")
from ras_commander.RasAcceptanceState import (  # noqa: E402
    AcceptanceProbeResult,
    AcceptanceStateBundle,
    LegacyUiTransferSourceCapture,
    LegacyTcuContractEvidence,
    RasAcceptanceState,
    RasExecutableIdentity,
    RegistryValueSnapshot,
)
from ras_commander.RasDialogWatchdog import ObservedWindow  # noqa: E402


AUTHORITY = "authorized-native-terms-transfer-4821"
PROFILE_TOKEN = "disposable-wine-profile-01"
OPAQUE_STATE = "PRIVATE-OPAQUE-ACCEPTANCE-STATE"
AUTHORIZED_LEGACY_VERSIONS = (
    "4.0",
    "4.1.0",
    "5.0.3",
    "5.0.6",
    "5.0.7",
    "6.0",
)
LEGAL_BODY = " | ".join(
    (
        "HEC-RAS Terms and Conditions for Use",
        "I DO NOT agree with the above Terms and Conditions for Use",
        "I agree to the above Terms and Conditions for Use",
        "Cancel",
        "Copy Statement to the Clipboard ...",
        "Next ...",
    )
)


@dataclass
class _Control:
    hwnd: int
    control_id: int
    class_name: str
    text: str
    enabled: bool = True
    visible: bool = True
    checked: int = 0


class _FakeWin32:
    def __init__(self):
        self.controls = {
            201: _Control(
                201,
                1,
                "ThunderRT6OptionButton",
                "I DO NOT agree with the above Terms and Conditions for Use",
                checked=1,
            ),
            202: _Control(
                202,
                2,
                "ThunderRT6CommandButton",
                "",
                enabled=False,
                visible=False,
            ),
            203: _Control(203, 3, "ThunderRT6CommandButton", "Cancel"),
            204: _Control(
                204,
                4,
                "ThunderRT6OptionButton",
                "I agree to the above Terms and Conditions for Use",
            ),
            205: _Control(
                205,
                5,
                "ThunderRT6CommandButton",
                "Copy Statement to the Clipboard ...",
            ),
            206: _Control(
                206,
                6,
                "ThunderRT6CommandButton",
                "Next ...",
                enabled=False,
            ),
            207: _Control(
                207,
                7,
                "ThunderRT6TextBox",
                "HEC-RAS Terms and Conditions for Use",
            ),
        }
        self.clicks: list[int] = []
        self.next_clicked = False
        self.after_agree = None

    def EnumChildWindows(self, _parent, callback, context):
        for hwnd in tuple(self.controls):
            callback(hwnd, context)

    def GetClassName(self, hwnd):
        return self.controls[hwnd].class_name

    def GetWindowText(self, hwnd):
        return self.controls[hwnd].text

    def GetDlgCtrlID(self, hwnd):
        return self.controls[hwnd].control_id

    def IsWindowEnabled(self, hwnd):
        return self.controls[hwnd].enabled

    def IsWindowVisible(self, hwnd):
        return self.controls[hwnd].visible

    def SendMessage(self, hwnd, message, _wparam, _lparam):
        control = self.controls[hwnd]
        if message == acceptance_module._BM_GETCHECK:
            return control.checked
        assert message == acceptance_module._BM_CLICK
        self.clicks.append(hwnd)
        if control.control_id == 4:
            control.checked = 1
            self.controls[201].checked = 0
            self.controls[206].enabled = True
            if self.after_agree is not None:
                self.after_agree(self)
        elif control.control_id == 6:
            self.next_clicked = True
        return 0


def _legal_window() -> ObservedWindow:
    return ObservedWindow(
        hwnd=101,
        pid=4242,
        class_name="ThunderRT6FormDC",
        title="Terms and Conditions for Use (TCU)",
        body=LEGAL_BODY,
        owner_hwnd=99,
        enabled=True,
        legal_reason="HEC-RAS TCU",
    )


def _main_window() -> ObservedWindow:
    return ObservedWindow(
        hwnd=102,
        pid=4242,
        class_name="ThunderRT6Main",
        title="RAS",
        body="",
        owner_hwnd=0,
        enabled=True,
        legal_reason=None,
    )


def _load_cli_module():
    script = Path(__file__).parent / "qualification" / "run_authorized_legacy_ui_transfer.py"
    spec = importlib.util.spec_from_file_location("authorized_ui_cli", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeWatchdog:
    """Read-only observer; deliberately exposes no start/scan/dismiss API."""

    def __init__(self, gui: _FakeWin32, *, extra_window=None):
        self.gui = gui
        self.extra_window = extra_window
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
        if self.gui.next_clicked:
            return (_main_window(),)
        windows = [_legal_window()]
        extra = (
            self.extra_window(self.gui)
            if callable(self.extra_window)
            else self.extra_window
        )
        if extra is not None:
            windows.append(extra)
        return tuple(windows)

    def terminate_process_tree(self, pid):
        self.terminated.append(pid)
        return True


class _FakeProcess:
    pid = 4242

    @staticmethod
    def poll():
        return None


def _ready_probe(identity, elapsed=45.0, observed="restart"):
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
        elapsed_seconds=elapsed,
        observed_at_utc=observed,
        main_window_signature=("ThunderRT6Main", "RAS", "0", "1"),
        topology_signatures=("4242|ThunderRT6Main|RAS|owner=0|enabled=1",),
        observed_process_ids=(4242,),
    )


def _source_bundle(gui: _FakeWin32, version="4.0"):
    source_identity = RasExecutableIdentity(
        path=rf"C:\HEC\{version}\Ras.exe",
        version=version,
        sha256="a" * 64,
        detected_version=version,
        architecture="x86",
    )
    probe = _ready_probe(source_identity, 45.0, "source-final")
    state = RegistryValueSnapshot(
        key=r"Software\VB and VBA Program Settings\source",
        name="System Statistic",
        exists=True,
        value=OPAQUE_STATE,
        registry_type=1,
    )
    original_fingerprint = "b" * 64
    (
        controls,
        control_hash,
        adapter_hash,
        full_tree_hash,
        body_hash,
    ) = acceptance_module._inspect_legacy_tcu_contract(
        _legal_window(),
        expected_next_enabled=False,
    )
    assert controls["agree"].control_id == 4
    top_hash = acceptance_module._fingerprint(
        {
            "class_name": "ThunderRT6FormDC",
            "title": "Terms and Conditions for Use (TCU)",
            "owner_present": True,
            "enabled": True,
        }
    )
    modal_hash = acceptance_module._fingerprint(
        {
            "top_signature_sha256": top_hash,
            "legal_dialog_body_sha256": body_hash,
            "control_contract_sha256": control_hash,
        }
    )
    evidence_payload = {
        "target": asdict(source_identity),
        "original_bundle_fingerprint": original_fingerprint,
        "initial_source_probe_sha256": "c" * 64,
        "final_source_probe_sha256": acceptance_module._fingerprint(asdict(probe)),
        "top_signature_sha256": top_hash,
        "legal_dialog_body_sha256": body_hash,
        "control_contract_sha256": control_hash,
        "source_adapter_contract_sha256": adapter_hash,
        "source_full_tree_contract_sha256": full_tree_hash,
        "normalized_modal_signature_sha256": modal_hash,
        "process_tree_terminated": True,
        "survivors": (),
        "automated_ui_interactions": 0,
        "observation_elapsed_seconds": 1.0,
        "observed_at_utc": "2026-07-18T00:00:00Z",
    }
    evidence = LegacyTcuContractEvidence(
        **{
            **evidence_payload,
            "target": source_identity,
            "fingerprint": acceptance_module._fingerprint(evidence_payload),
        }
    )
    bundle_payload = acceptance_module._bundle_fingerprint_payload(
        source_identity,
        state,
        probe,
        evidence,
    )
    bundle = AcceptanceStateBundle(
        identity=source_identity,
        state=state,
        source_probe=probe,
        captured_at_utc="2026-07-18T00:00:01Z",
        fingerprint=acceptance_module._fingerprint(bundle_payload),
        legacy_tcu_contract=evidence,
    )
    return bundle, acceptance_module._private_bundle_file_sha256(bundle)


def _install_transfer_mocks(
    monkeypatch,
    tmp_path,
    *,
    version="4.0",
    source_mutate=None,
    mutate=None,
    extra_window=None,
):
    gui = _FakeWin32()
    monkeypatch.setattr(acceptance_module, "win32gui", gui)
    if source_mutate is not None:
        source_mutate(gui)
    bundle, bundle_sha256 = _source_bundle(gui, version)
    if mutate is not None:
        mutate(gui)
    target_identity = RasExecutableIdentity(
        path=str(tmp_path / version / "Ras.exe"),
        version=version,
        sha256=bundle.identity.sha256,
        detected_version=version,
        architecture="x86",
    )
    monkeypatch.setattr(
        RasAcceptanceState,
        "executable_identity",
        lambda *_args, **_kwargs: target_identity,
    )
    monkeypatch.setattr(RasAcceptanceState, "_target_running", lambda _identity: False)
    monkeypatch.setattr(acceptance_module, "_cross_process_lock", lambda _key: nullcontext())
    watchdog = _FakeWatchdog(gui, extra_window=extra_window)
    monkeypatch.setattr(acceptance_module, "DialogWatchdog", lambda **_kwargs: watchdog)
    monkeypatch.setattr(acceptance_module.subprocess, "Popen", lambda *_a, **_k: _FakeProcess())
    monkeypatch.setattr(
        acceptance_module,
        "psutil",
        SimpleNamespace(pid_exists=lambda _pid: False),
    )
    quiet_calls = []

    def quiet(_identity, seconds, **_kwargs):
        quiet_calls.append(seconds)
        return seconds

    monkeypatch.setattr(acceptance_module, "_verify_target_quiet_period", quiet)
    probes = [
        _ready_probe(target_identity, 45.0, "restart-1"),
        _ready_probe(target_identity, 45.0, "restart-2"),
    ]
    monkeypatch.setattr(RasAcceptanceState, "probe", lambda *_a, **_k: probes.pop(0))
    return gui, bundle, bundle_sha256, watchdog, quiet_calls


def _run(tmp_path, bundle, bundle_sha256, version="4.0"):
    return RasAcceptanceState.run_authorized_legacy_ui_transfer(
        tmp_path / version / "Ras.exe",
        expected_version=version,
        source_bundle=bundle,
        source_bundle_file_sha256=bundle_sha256,
        destination_is_disposable=True,
        authorization_reference=AUTHORITY,
        profile_instance_token=PROFILE_TOKEN,
        session_timeout_seconds=0.05,
        legal_observation_seconds=0.0001,
        control_transition_timeout_seconds=0.01,
        main_ready_seconds=0.0001,
        restart_timeout_seconds=45.0,
        restart_ready_seconds=20.0,
        poll_interval_seconds=0.0001,
    )


def test_hidden_disabled_id2_empty_caption_is_adapter_hashed(monkeypatch):
    gui = _FakeWin32()
    monkeypatch.setattr(acceptance_module, "win32gui", gui)

    (
        _controls,
        semantic_hash,
        empty_caption_adapter_hash,
        empty_caption_full_tree_hash,
        body_hash,
    ) = (
        acceptance_module._inspect_legacy_tcu_contract(
            _legal_window(),
            expected_next_enabled=False,
        )
    )

    gui.controls[202].text = "OK"
    (
        _controls,
        changed_semantic_hash,
        changed_adapter_hash,
        changed_full_tree_hash,
        changed_body_hash,
    ) = acceptance_module._inspect_legacy_tcu_contract(
            _legal_window(),
            expected_next_enabled=False,
        )

    assert semantic_hash == changed_semantic_hash
    assert body_hash == changed_body_hash
    assert empty_caption_adapter_hash != changed_adapter_hash
    assert empty_caption_full_tree_hash != changed_full_tree_hash


@pytest.mark.parametrize(
    "mutate",
    [
        lambda gui: setattr(gui.controls[202], "visible", True),
        lambda gui: setattr(gui.controls[202], "enabled", True),
    ],
)
def test_visible_or_enabled_adapter_extra_fails_with_hashed_diagnostics(
    monkeypatch,
    mutate,
):
    gui = _FakeWin32()
    gui.controls[202].text = "SECRET EXTRA CONTROL"
    mutate(gui)
    monkeypatch.setattr(acceptance_module, "win32gui", gui)

    with pytest.raises(RuntimeError, match="hashed_control_signatures") as excinfo:
        acceptance_module._inspect_legacy_tcu_contract(
            _legal_window(),
            expected_next_enabled=False,
        )

    assert "SECRET EXTRA CONTROL" not in str(excinfo.value)


@pytest.mark.parametrize("version", AUTHORIZED_LEGACY_VERSIONS)
def test_exact_contract_sends_only_agree_and_next_then_verifies_restarts(
    monkeypatch,
    tmp_path,
    version,
):
    gui, bundle, bundle_sha256, watchdog, quiet_calls = _install_transfer_mocks(
        monkeypatch,
        tmp_path,
        version=version,
    )

    receipt = _run(tmp_path, bundle, bundle_sha256, version)

    assert receipt.passed is True
    assert gui.clicks == [204, 206]
    assert receipt.automated_ui_interactions == 2
    assert receipt.source_modal_signature_sha256 == receipt.target_modal_signature_sha256
    assert receipt.process_tree_terminated is True
    assert receipt.survivors == ()
    assert len(receipt.restart_probes) == 2
    assert quiet_calls == [45.0, 45.0]
    assert watchdog.terminated == [4242]
    serialized = json.dumps(asdict(receipt), sort_keys=True)
    assert AUTHORITY not in serialized
    assert PROFILE_TOKEN not in serialized
    assert LEGAL_BODY not in serialized
    assert OPAQUE_STATE not in serialized


def test_inert_hidden_adapter_difference_is_separately_receipt_bound(
    monkeypatch,
    tmp_path,
):
    gui, bundle, bundle_sha256, _watchdog, _quiet = _install_transfer_mocks(
        monkeypatch,
        tmp_path,
        mutate=lambda fake_gui: setattr(fake_gui.controls[202], "text", "OK"),
    )

    receipt = _run(tmp_path, bundle, bundle_sha256)

    assert receipt.passed
    assert gui.clicks == [204, 206]
    assert (
        receipt.source_adapter_contract_sha256
        != receipt.target_adapter_contract_sha256
    )
    assert (
        receipt.source_full_tree_contract_sha256
        != receipt.target_full_tree_contract_sha256
    )


def test_native_absent_wine_hidden_disabled_adapter_extra_is_allowed(
    monkeypatch,
    tmp_path,
):
    hidden = _Control(
        202,
        2,
        "ThunderRT6CommandButton",
        "",
        enabled=False,
        visible=False,
    )
    gui, bundle, bundle_sha256, _watchdog, _quiet = _install_transfer_mocks(
        monkeypatch,
        tmp_path,
        source_mutate=lambda fake_gui: fake_gui.controls.pop(202),
        mutate=lambda fake_gui: fake_gui.controls.__setitem__(202, hidden),
    )

    receipt = _run(tmp_path, bundle, bundle_sha256)

    assert receipt.passed
    assert gui.clicks == [204, 206]
    assert (
        receipt.source_adapter_contract_sha256
        != receipt.target_adapter_contract_sha256
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda gui: setattr(gui.controls[204], "text", "I agree"),
        lambda gui: setattr(gui.controls[206], "enabled", True),
        lambda gui: setattr(gui.controls[204], "checked", 1),
        lambda gui: setattr(gui.controls[205], "class_name", "Button"),
    ],
)
def test_contract_mismatch_sends_zero_input_and_terminates(
    monkeypatch,
    tmp_path,
    mutate,
):
    gui, bundle, bundle_sha256, watchdog, _quiet = _install_transfer_mocks(
        monkeypatch,
        tmp_path,
        mutate=mutate,
    )

    with pytest.raises((RuntimeError, ValueError)):
        _run(tmp_path, bundle, bundle_sha256)

    assert gui.clicks == []
    assert watchdog.terminated == [4242]


def test_target_initial_disagree_state_must_match_pinned_source(
    monkeypatch,
    tmp_path,
):
    gui, bundle, bundle_sha256, watchdog, _quiet = _install_transfer_mocks(
        monkeypatch,
        tmp_path,
        mutate=lambda fake_gui: setattr(
            fake_gui.controls[201],
            "checked",
            0,
        ),
    )

    with pytest.raises(RuntimeError, match="pinned exact-source evidence"):
        _run(tmp_path, bundle, bundle_sha256)

    assert gui.clicks == []
    assert watchdog.terminated == [4242]


def test_unknown_window_alongside_tcu_sends_zero_input(monkeypatch, tmp_path):
    unknown = ObservedWindow(
        999,
        4242,
        "MysteryModal",
        "Unexpected",
        "SECRET",
        101,
        True,
        None,
    )
    gui, bundle, bundle_sha256, watchdog, _quiet = _install_transfer_mocks(
        monkeypatch,
        tmp_path,
        extra_window=unknown,
    )

    with pytest.raises(RuntimeError, match="Unknown window"):
        _run(tmp_path, bundle, bundle_sha256)

    assert gui.clicks == []
    assert watchdog.terminated == [4242]


def test_post_agree_wrong_option_state_never_clicks_next(monkeypatch, tmp_path):
    gui, bundle, bundle_sha256, watchdog, _quiet = _install_transfer_mocks(
        monkeypatch,
        tmp_path,
    )

    def select_disagree(fake_gui):
        fake_gui.controls[204].checked = 0
        fake_gui.controls[201].checked = 1

    gui.after_agree = select_disagree

    with pytest.raises(RuntimeError, match="Agree selection"):
        _run(tmp_path, bundle, bundle_sha256)

    assert gui.clicks == [204]
    assert watchdog.terminated == [4242]


def test_unknown_window_after_agree_never_clicks_next(monkeypatch, tmp_path):
    unknown = ObservedWindow(
        999,
        4242,
        "MysteryModal",
        "Unexpected",
        "SECRET",
        101,
        True,
        None,
    )
    gui, bundle, bundle_sha256, watchdog, _quiet = _install_transfer_mocks(
        monkeypatch,
        tmp_path,
        extra_window=lambda fake_gui: unknown if fake_gui.clicks else None,
    )

    with pytest.raises(RuntimeError, match="Unknown window appeared after Agree"):
        _run(tmp_path, bundle, bundle_sha256)

    assert gui.clicks == [204]
    assert watchdog.terminated == [4242]


def test_source_capture_verifies_restoring_zero_input_chain(monkeypatch, tmp_path):
    identity = RasExecutableIdentity(
        path=str(tmp_path / "4.0" / "Ras.exe"),
        version="4.0",
        sha256="a" * 64,
        detected_version="4.0",
        architecture="x86",
    )
    initial_probe = _ready_probe(identity, 20.0, "source-initial")
    final_probe = _ready_probe(identity, 20.0, "source-final")
    state = RegistryValueSnapshot(
        key=r"Software\VB and VBA Program Settings\source",
        name="System Statistic",
        exists=True,
        value=OPAQUE_STATE,
        registry_type=1,
    )
    original = AcceptanceStateBundle(
        identity=identity,
        state=state,
        source_probe=initial_probe,
        captured_at_utc="source-capture",
        fingerprint=acceptance_module._fingerprint(
            acceptance_module._bundle_fingerprint_payload(
                identity,
                state,
                initial_probe,
            )
        ),
    )
    missing = RegistryValueSnapshot(state.key, state.name, False, None, None)
    observation = acceptance_module._LegacyTcuObservation(
        top_signature_sha256="1" * 64,
        legal_dialog_body_sha256="2" * 64,
        control_contract_sha256="3" * 64,
        adapter_contract_sha256="5" * 64,
        full_tree_contract_sha256="6" * 64,
        normalized_modal_signature_sha256="4" * 64,
        observed_process_ids=(4242,),
        process_tree_terminated=True,
        survivors=(),
        automated_ui_interactions=0,
        elapsed_seconds=1.0,
        observed_at_utc="source-tcu",
    )
    probes = [initial_probe, final_probe]
    monkeypatch.setattr(
        RasAcceptanceState,
        "executable_identity",
        lambda *_a, **_k: identity,
    )
    monkeypatch.setattr(RasAcceptanceState, "_target_running", lambda _identity: False)
    monkeypatch.setattr(RasAcceptanceState, "probe", lambda *_a, **_k: probes.pop(0))
    monkeypatch.setattr(
        RasAcceptanceState,
        "capture",
        lambda *_a, **_k: original,
    )
    monkeypatch.setattr(
        RasAcceptanceState,
        "temporary_system_statistic",
        lambda *_a, **_k: nullcontext((state, missing)),
    )
    monkeypatch.setattr(
        acceptance_module,
        "_observe_exact_legacy_tcu_without_input",
        lambda *_a, **_k: observation,
    )
    backend = SimpleNamespace(snapshot=lambda _key: state)

    result = RasAcceptanceState.capture_authorized_legacy_ui_transfer_source(
        identity.path,
        expected_version="4.0",
        probe_timeout_seconds=20.0,
        probe_ready_seconds=5.0,
        legal_timeout_seconds=1.0,
        legal_observation_seconds=0.01,
        registry=backend,
    )

    assert result.passed is True
    assert result.original_bundle == original
    assert result.extended_bundle.state == state
    assert result.extended_bundle.source_probe == final_probe
    assert result.contract_evidence.automated_ui_interactions == 0
    assert result.contract_evidence.original_bundle_fingerprint == original.fingerprint
    assert probes == []


def test_source_contract_failure_restores_exact_original_state(monkeypatch, tmp_path):
    identity = RasExecutableIdentity(
        path=str(tmp_path / "4.0" / "Ras.exe"),
        version="4.0",
        sha256="a" * 64,
        detected_version="4.0",
        architecture="x86",
    )
    initial_probe = _ready_probe(identity, 20.0, "source-initial")
    state = RegistryValueSnapshot(
        key=r"Software\VB and VBA Program Settings\source",
        name="System Statistic",
        exists=True,
        value=OPAQUE_STATE,
        registry_type=1,
    )
    missing = RegistryValueSnapshot(state.key, state.name, False, None, None)
    original = AcceptanceStateBundle(
        identity=identity,
        state=state,
        source_probe=initial_probe,
        captured_at_utc="source-capture",
        fingerprint=acceptance_module._fingerprint(
            acceptance_module._bundle_fingerprint_payload(
                identity,
                state,
                initial_probe,
            )
        ),
    )

    class Backend:
        def __init__(self, initial):
            self.current = initial

        def snapshot(self, _key):
            return self.current

        def delete_value(self, _key):
            self.current = missing

        def restore_value(self, before, _created):
            self.current = before

    backend = Backend(state)
    monkeypatch.setattr(
        RasAcceptanceState,
        "executable_identity",
        lambda *_a, **_k: identity,
    )
    monkeypatch.setattr(RasAcceptanceState, "_target_running", lambda _identity: False)
    monkeypatch.setattr(
        RasAcceptanceState,
        "probe",
        lambda *_a, **_k: initial_probe,
    )
    monkeypatch.setattr(
        RasAcceptanceState,
        "capture",
        lambda *_a, **_k: original,
    )

    def fail_observation(*_args, **_kwargs):
        assert backend.current == missing
        raise RuntimeError("initial legacy TCU contract mismatch")

    monkeypatch.setattr(
        acceptance_module,
        "_observe_exact_legacy_tcu_without_input",
        fail_observation,
    )

    with pytest.raises(RuntimeError, match="contract mismatch"):
        RasAcceptanceState.capture_authorized_legacy_ui_transfer_source(
            identity.path,
            expected_version="4.0",
            probe_timeout_seconds=20.0,
            probe_ready_seconds=5.0,
            legal_timeout_seconds=1.0,
            legal_observation_seconds=0.01,
            registry=backend,
        )

    assert backend.current == state


@pytest.mark.parametrize("version", ["6.1", "6.7 Beta 5", "7.0"])
def test_rejects_newer_and_beta_builds_before_identity_or_launch(
    monkeypatch,
    version,
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

    with pytest.raises(ValueError, match="limited to exact stable builds"):
        RasAcceptanceState.run_authorized_legacy_ui_transfer(
            r"C:\HEC\Ras.exe",
            expected_version=version,
            source_bundle=SimpleNamespace(),
            source_bundle_file_sha256="a" * 64,
            destination_is_disposable=True,
            authorization_reference=AUTHORITY,
            profile_instance_token=PROFILE_TOKEN,
        )

    assert identity_calls == []
    assert launch_calls == []


@pytest.mark.parametrize("version", ["6.1", "6.7 Beta 5", "7.0", "7.0.1"])
def test_source_capture_rejects_newer_and_beta_builds_before_launch(
    monkeypatch,
    version,
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

    with pytest.raises(ValueError, match="limited to exact stable"):
        RasAcceptanceState.capture_authorized_legacy_ui_transfer_source(
            r"C:\HEC\Ras.exe",
            expected_version=version,
        )

    assert identity_calls == []
    assert launch_calls == []


def test_transfer_cli_calls_only_public_api_and_writes_hash_only_receipt(
    monkeypatch,
    tmp_path,
):
    module = _load_cli_module()

    private = tmp_path.parent / f"{tmp_path.name}-private"
    private.mkdir()
    gui = _FakeWin32()
    monkeypatch.setattr(acceptance_module, "win32gui", gui)
    bundle, bundle_sha256 = _source_bundle(gui)
    bundle_payload = {
        "schema_version": 1,
        "kind": "private_exact_version_acceptance_bundle",
        "bundle": asdict(bundle),
    }
    bundle_path = private / "source.json"
    bundle_path.write_bytes(module._canonical_bytes(bundle_payload))
    assert module._sha256(bundle_path.read_bytes()) == bundle_sha256
    authority_path = private / "authority.txt"
    authority_path.write_text(AUTHORITY, encoding="utf-8")
    profile_path = private / "profile.txt"
    profile_path.write_text(PROFILE_TOKEN, encoding="utf-8")
    output = private / "receipt.json"

    @dataclass
    class DummyReceipt:
        fingerprint: str = "f" * 64
        authorization_reference_sha256: str = "d" * 64
        profile_instance_token_sha256: str = "e" * 64
        automated_ui_interactions: int = 2

        @property
        def passed(self):
            return True

    calls = []

    def public_api(*args, **kwargs):
        calls.append((args, kwargs))
        return DummyReceipt()

    monkeypatch.setattr(
        module.RasAcceptanceState,
        "run_authorized_legacy_ui_transfer",
        public_api,
    )
    result = module.main(
        [
            "transfer",
            "--ras-executable",
            str(private / "Ras.exe"),
            "--expected-version",
            "4.0",
            "--source-bundle",
            str(bundle_path),
            "--source-bundle-sha256",
            bundle_sha256,
            "--authorization-reference-file",
            str(authority_path),
            "--profile-instance-token-file",
            str(profile_path),
            "--destination-is-disposable",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert len(calls) == 1
    assert calls[0][1]["destination_is_disposable"] is True
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["passed"] is True
    assert payload["report_sha256"]
    assert AUTHORITY not in text
    assert PROFILE_TOKEN not in text
    assert OPAQUE_STATE not in text


def test_capture_cli_calls_only_public_api_and_separates_private_state(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = _load_cli_module()
    private = tmp_path.parent / f"{tmp_path.name}-capture-private"
    private.mkdir()
    gui = _FakeWin32()
    monkeypatch.setattr(acceptance_module, "win32gui", gui)
    extended, _bundle_sha256 = _source_bundle(gui)
    original_payload = acceptance_module._bundle_fingerprint_payload(
        extended.identity,
        extended.state,
        extended.source_probe,
    )
    original = AcceptanceStateBundle(
        identity=extended.identity,
        state=extended.state,
        source_probe=extended.source_probe,
        captured_at_utc="original",
        fingerprint=acceptance_module._fingerprint(original_payload),
    )
    result = LegacyUiTransferSourceCapture(
        original_bundle=original,
        extended_bundle=extended,
        contract_evidence=extended.legacy_tcu_contract,
    )
    assert result.passed
    calls = []

    def public_api(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(
        module.RasAcceptanceState,
        "capture_authorized_legacy_ui_transfer_source",
        public_api,
    )
    original_path = private / "original.json"
    extended_path = private / "extended.json"
    receipt_path = private / "receipt.json"

    status = module.main(
        [
            "capture-source",
            "--ras-executable",
            str(private / "Ras.exe"),
            "--expected-version",
            "4.0",
            "--output-original-bundle",
            str(original_path),
            "--output-extended-bundle",
            str(extended_path),
            "--output-receipt",
            str(receipt_path),
            "--private-output-authorized",
        ]
    )

    assert status == 0
    assert len(calls) == 1
    assert OPAQUE_STATE in original_path.read_text(encoding="utf-8")
    assert OPAQUE_STATE in extended_path.read_text(encoding="utf-8")
    receipt_text = receipt_path.read_text(encoding="utf-8")
    console_text = capsys.readouterr().out
    assert OPAQUE_STATE not in receipt_text
    assert OPAQUE_STATE not in console_text
    assert AUTHORITY not in receipt_text
    assert PROFILE_TOKEN not in receipt_text


@pytest.mark.parametrize("command", ["capture-source", "transfer"])
def test_cli_refuses_existing_output_before_public_launch(
    monkeypatch,
    tmp_path,
    command,
):
    module = _load_cli_module()
    private = tmp_path.parent / f"{tmp_path.name}-{command}-existing"
    private.mkdir()
    existing = private / "existing.json"
    existing.write_text("already here", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        module.RasAcceptanceState,
        "capture_authorized_legacy_ui_transfer_source",
        lambda *_a, **_k: calls.append("capture"),
    )
    monkeypatch.setattr(
        module.RasAcceptanceState,
        "run_authorized_legacy_ui_transfer",
        lambda *_a, **_k: calls.append("transfer"),
    )

    if command == "capture-source":
        argv = [
            command,
            "--ras-executable",
            str(private / "Ras.exe"),
            "--expected-version",
            "4.0",
            "--output-original-bundle",
            str(existing),
            "--output-extended-bundle",
            str(private / "extended.json"),
            "--output-receipt",
            str(private / "receipt.json"),
            "--private-output-authorized",
        ]
    else:
        argv = [
            command,
            "--ras-executable",
            str(private / "Ras.exe"),
            "--expected-version",
            "4.0",
            "--source-bundle",
            str(private / "source.json"),
            "--source-bundle-sha256",
            "a" * 64,
            "--authorization-reference-file",
            str(private / "authority.txt"),
            "--profile-instance-token-file",
            str(private / "profile.txt"),
            "--destination-is-disposable",
            "--output",
            str(existing),
        ]

    with pytest.raises(FileExistsError, match="overwrite"):
        module.main(argv)

    assert calls == []
    assert existing.read_text(encoding="utf-8") == "already here"
