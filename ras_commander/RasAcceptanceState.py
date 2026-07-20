r"""Capture, diagnose, and provision HEC-RAS acceptance-state sentinels.

HEC-RAS stores legacy per-user application settings below
``HKCU\Software\VB and VBA Program Settings``.  This module treats the
``Projects\System Statistic`` value as opaque state: it may be captured and
relocated only through an audited, fail-closed diagnostic. Legal-assent input
is prohibited except in the explicitly authorized, exact-contract legacy UI
transfer method for the six allowlisted 4.0--6.0 builds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

try:
    import psutil
except ImportError:  # pragma: no cover - enforced by probe()
    psutil = None

try:
    import winreg
except ImportError:  # pragma: no cover - Windows/Wine-only state operations
    winreg = None

try:
    import win32gui
except ImportError:  # pragma: no cover - Windows/Wine-only UI transfer
    win32gui = None

from .LoggingConfig import get_logger
from .Decorators import log_call
from .RasDialogWatchdog import DialogWatchdog, ObservedWindow
from .RasUtils import RasUtils
from ._legal_dialogs import legal_dialog_blocking_reason

logger = get_logger(__name__)

_REGISTRY_ROOT = r"Software\VB and VBA Program Settings"
_REGISTRY_SECTION = "Projects"
_VALUE_NAME = "System Statistic"
_MISSING = object()
_BM_GETCHECK = 0x00F0
_BM_CLICK = 0x00F5
_AUTHORIZED_LEGACY_UI_VERSIONS = frozenset(
    {"4.0", "4.1.0", "5.0.3", "5.0.6", "5.0.7", "6.0"}
)
_LEGACY_TCU_CLASS = "ThunderRT6FormDC"
_LEGACY_TCU_TITLE = "Terms and Conditions for Use (TCU)"
_LEGACY_OPTION_CLASS = "ThunderRT6OptionButton"
_LEGACY_BUTTON_CLASS = "ThunderRT6CommandButton"
_LEGACY_TEXTBOX_CLASS = "ThunderRT6TextBox"
_LEGACY_AGREE_TEXT = "I agree to the above Terms and Conditions for Use"
_LEGACY_DISAGREE_TEXT = (
    "I DO NOT agree with the above Terms and Conditions for Use"
)
_LEGACY_NEXT_TEXT = "Next ..."
_LEGACY_CANCEL_TEXT = "Cancel"
_LEGACY_COPY_TEXT = "Copy Statement to the Clipboard ..."
_LEGACY_PRE_RESTART_QUIET_SECONDS = 45.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _opaque_token_sha256(label: str, value: str, *, strip: bool = True) -> str:
    """Hash a required opaque token without retaining its raw value."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a nonempty string")
    normalized = value.strip() if strip else value
    if not normalized.strip():
        raise ValueError(f"{label} must be a nonempty string")
    domain = f"ras-commander:{label}:v1\0".encode("utf-8")
    return hashlib.sha256(domain + normalized.encode("utf-8")).hexdigest()


def _is_sha256(value: Optional[str]) -> bool:
    return bool(value and re.fullmatch(r"[0-9a-f]{64}", value))


def _normalize_vb6_control_text(value: str) -> str:
    """Normalize only whitespace and case for an exact VB6 caption match."""
    return " ".join(str(value).split()).casefold()


def _private_bundle_file_sha256(bundle: "AcceptanceStateBundle") -> str:
    """Reconstruct the canonical private-bundle bytes and hash them."""
    payload = {
        "schema_version": 1,
        "kind": "private_exact_version_acceptance_bundle",
        "bundle": asdict(bundle),
    }
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class _LegacyTcuControl:
    hwnd: int
    control_id: int
    class_name: str
    text: str
    enabled: bool
    visible: bool
    check_state: Optional[int]


@dataclass(frozen=True)
class _LegacyTcuObservation:
    top_signature_sha256: str
    legal_dialog_body_sha256: str
    control_contract_sha256: str
    adapter_contract_sha256: str
    full_tree_contract_sha256: str
    normalized_modal_signature_sha256: str
    observed_process_ids: Tuple[int, ...]
    process_tree_terminated: bool
    survivors: Tuple[int, ...]
    automated_ui_interactions: int
    elapsed_seconds: float
    observed_at_utc: str


def _enumerate_legacy_tcu_controls(hwnd: int) -> Tuple[_LegacyTcuControl, ...]:
    """Read the complete VB6 TCU child-control tree without sending input."""
    if win32gui is None:
        raise RuntimeError("Authorized legacy UI transfer requires pywin32")
    controls: List[_LegacyTcuControl] = []
    errors: List[str] = []

    def _child_callback(child, _context):
        try:
            class_name = str(win32gui.GetClassName(child))
            check_state: Optional[int] = None
            if class_name == _LEGACY_OPTION_CLASS:
                check_state = int(
                    win32gui.SendMessage(child, _BM_GETCHECK, 0, 0)
                )
            controls.append(
                _LegacyTcuControl(
                    hwnd=int(child),
                    control_id=int(win32gui.GetDlgCtrlID(child)),
                    class_name=class_name,
                    text=str(win32gui.GetWindowText(child)),
                    enabled=bool(win32gui.IsWindowEnabled(child)),
                    visible=bool(win32gui.IsWindowVisible(child)),
                    check_state=check_state,
                )
            )
        except Exception as exc:
            errors.append(
                f"child hwnd={child}: {type(exc).__name__}: {exc}"
            )
        return True

    try:
        win32gui.EnumChildWindows(hwnd, _child_callback, None)
    except Exception as exc:
        raise RuntimeError(
            "Legacy TCU child-control enumeration failed"
        ) from exc
    if errors:
        raise RuntimeError(
            "Legacy TCU child-control inspection failed: " + "; ".join(errors)
        )
    return tuple(controls)


def _inspect_legacy_tcu_contract(
    window: ObservedWindow,
    *,
    expected_next_enabled: Optional[bool],
    expected_hwnds: Optional[Dict[str, int]] = None,
) -> Tuple[Dict[str, _LegacyTcuControl], str, str, str, str]:
    """Validate the exact observed VB6 legal dialog before any click."""
    if (
        window.class_name != _LEGACY_TCU_CLASS
        or window.title != _LEGACY_TCU_TITLE
        or not window.enabled
        or not window.owner_hwnd
        or not window.legal_reason
    ):
        raise RuntimeError("The live legal dialog did not match the exact VB6 top-level contract")

    normalized_body = _normalize_vb6_control_text(window.body)
    required_body_markers = (
        _normalize_vb6_control_text("Terms and Conditions for Use"),
        _normalize_vb6_control_text(_LEGACY_AGREE_TEXT),
        _normalize_vb6_control_text(_LEGACY_DISAGREE_TEXT),
    )
    if not window.body.strip() or any(
        marker not in normalized_body for marker in required_body_markers
    ):
        raise RuntimeError("The live legal body did not match the exact legacy TCU markers")

    controls = _enumerate_legacy_tcu_controls(window.hwnd)

    def _safe_signatures() -> Tuple[Tuple[int, str], ...]:
        return tuple(
            sorted(
                (
                    control.control_id,
                    _fingerprint(
                        {
                            "control_id": control.control_id,
                            "class_name": control.class_name,
                            "normalized_caption": _normalize_vb6_control_text(
                                control.text
                            ),
                            "enabled": control.enabled,
                            "visible": control.visible,
                            "check_state": control.check_state,
                        }
                    ),
                )
                for control in controls
            )
        )

    def _contract_error(message: str) -> RuntimeError:
        return RuntimeError(
            f"{message}; hashed_control_signatures={_safe_signatures()!r}"
        )

    def _canonical_control(
        role: str,
        control: _LegacyTcuControl,
    ) -> Tuple[object, ...]:
        return (
            role,
            control.control_id,
            control.class_name,
            (
                "normalized-vb6-caption-v1",
                _normalize_vb6_control_text(control.text),
            ),
            control.enabled,
            control.visible,
            control.check_state,
        )

    expected_roles = {
        "agree": (4, _LEGACY_OPTION_CLASS, _LEGACY_AGREE_TEXT),
        "disagree": (1, _LEGACY_OPTION_CLASS, _LEGACY_DISAGREE_TEXT),
        "next": (6, _LEGACY_BUTTON_CLASS, _LEGACY_NEXT_TEXT),
        "cancel": (3, _LEGACY_BUTTON_CLASS, _LEGACY_CANCEL_TEXT),
        "copy": (5, _LEGACY_BUTTON_CLASS, _LEGACY_COPY_TEXT),
    }
    matched: Dict[str, _LegacyTcuControl] = {}
    matched_hwnds: set[int] = set()
    for role, (expected_id, expected_class, expected_text) in expected_roles.items():
        candidates = tuple(
            control
            for control in controls
            if control.control_id == expected_id
            and control.class_name == expected_class
            and _normalize_vb6_control_text(control.text)
            == _normalize_vb6_control_text(expected_text)
        )
        if len(candidates) != 1:
            raise _contract_error(
                f"The legacy TCU {role} control was absent or ambiguous"
            )
        matched[role] = candidates[0]
        matched_hwnds.add(candidates[0].hwnd)

    textboxes = tuple(
        control
        for control in controls
        if control.class_name == _LEGACY_TEXTBOX_CLASS
        and control.control_id == 7
    )
    if len(textboxes) != 1:
        raise _contract_error(
            "The legacy TCU legal textbox was absent or ambiguous"
        )
    matched["legal_textbox"] = textboxes[0]
    matched_hwnds.add(textboxes[0].hwnd)

    adapter_controls = tuple(
        control for control in controls if control.hwnd not in matched_hwnds
    )
    invalid_adapter_controls = tuple(
        control
        for control in adapter_controls
        if control.visible
        or control.enabled
        or (
            control.class_name == _LEGACY_OPTION_CLASS
            and control.check_state != 0
        )
    )
    if invalid_adapter_controls:
        raise _contract_error(
            "The legacy TCU contained an unknown visible, enabled, or interactive extra control"
        )

    if not all(matched[role].visible and matched[role].enabled for role in (
        "agree",
        "disagree",
        "cancel",
        "copy",
    )):
        raise _contract_error(
            "A required legacy TCU option/button was hidden or disabled"
        )
    option_states = (
        matched["agree"].check_state,
        matched["disagree"].check_state,
    )
    if any(state not in (0, 1) for state in option_states):
        raise _contract_error("The legacy TCU option selection state was invalid")
    if expected_next_enabled is False and matched["agree"].check_state != 0:
        raise _contract_error(
            "The initial legacy TCU Agree option was not unchecked"
        )
    if expected_next_enabled is True and option_states != (1, 0):
        raise _contract_error(
            "The legacy TCU Agree selection was not exactly checked/unchecked"
        )
    if not matched["next"].visible:
        raise _contract_error("The exact legacy TCU Next control was not visible")
    if expected_next_enabled is not None and (
        matched["next"].enabled is not expected_next_enabled
    ):
        state = "enabled" if expected_next_enabled else "disabled"
        raise _contract_error(
            f"The exact legacy TCU Next control was not {state}"
        )
    if not matched["legal_textbox"].visible:
        raise _contract_error(
            "The exact legacy TCU legal textbox was not visible"
        )

    handles = {role: control.hwnd for role, control in matched.items()}
    if expected_hwnds is not None and handles != expected_hwnds:
        raise _contract_error(
            "The legacy TCU semantic control handles changed after validation"
        )

    semantic_controls = tuple(
        sorted(
            _canonical_control(role, control)
            for role, control in matched.items()
        )
    )
    adapter_controls_payload = tuple(
        sorted(
            _canonical_control("adapter_extra", control)
            for control in adapter_controls
        )
    )
    semantic_payload = {
        "top_class": window.class_name,
        "top_title": window.title,
        "top_owner_present": bool(window.owner_hwnd),
        "semantic_controls": semantic_controls,
    }
    adapter_payload = {
        "top_class": window.class_name,
        "top_title": window.title,
        "adapter_controls": adapter_controls_payload,
    }
    full_tree_payload = {
        "semantic_contract": semantic_controls,
        "adapter_contract": adapter_controls_payload,
    }
    return (
        matched,
        _fingerprint(semantic_payload),
        _fingerprint(adapter_payload),
        _fingerprint(full_tree_payload),
        _opaque_token_sha256(
            "legal-dialog-body",
            _normalize_vb6_control_text(window.body),
            strip=False,
        ),
    )


def _verify_target_quiet_period(
    identity: "RasExecutableIdentity",
    seconds: float,
    *,
    poll_interval_seconds: float,
) -> float:
    """Require the exact target to remain absent for a full cooldown period."""
    started = time.monotonic()
    deadline = started + seconds
    while time.monotonic() < deadline:
        if RasAcceptanceState._target_running(identity):
            raise RuntimeError(
                "The target restarted during the required pre-restart quiet period"
            )
        remaining = deadline - time.monotonic()
        time.sleep(min(poll_interval_seconds, max(remaining, 0.001)))
    elapsed = time.monotonic() - started
    if elapsed < seconds:
        raise RuntimeError("The pre-restart quiet period was shorter than required")
    return elapsed


def _observe_exact_legacy_tcu_without_input(
    identity: "RasExecutableIdentity",
    *,
    timeout_seconds: float,
    stable_observation_seconds: float,
    poll_interval_seconds: float,
) -> _LegacyTcuObservation:
    """Launch through the public caller and pin one exact TCU with zero input."""
    watchdog = DialogWatchdog(poll_interval=poll_interval_seconds)
    watchdog.require_available()
    if psutil is None:
        raise RuntimeError("psutil is required for verified TCU observation")

    started_at = time.monotonic()
    process: Optional[subprocess.Popen] = None
    observed_pids: set[int] = set()
    candidate: Optional[Tuple[str, ...]] = None
    candidate_since: Optional[float] = None
    final_hashes: Optional[Tuple[str, str, str, str, str, str]] = None
    termination_verified = False
    survivors: Tuple[int, ...] = ()
    observation_error: Optional[BaseException] = None
    title_markers = ("hec-ras", "river analysis system")

    try:
        process = subprocess.Popen(
            [identity.path],
            cwd=str(Path(identity.path).parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        observed_pids.add(process.pid)
        watchdog.add_pid(process.pid)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("HEC-RAS exited before exact TCU observation")
            if watchdog.supervision_error or watchdog.blocked or watchdog.dismissed:
                raise RuntimeError("Exact TCU observation lost zero-input supervision")
            observed_pids.update(watchdog.scoped_pids())
            windows = watchdog.observe_windows()
            legal_windows = tuple(window for window in windows if window.legal_reason)
            if len(legal_windows) > 1:
                raise RuntimeError("Multiple legal windows made TCU observation ambiguous")
            if not legal_windows:
                unknown = tuple(
                    window
                    for window in windows
                    if not _is_acceptance_main_shell(window, title_markers)
                    and not _is_acceptance_companion_window(window)
                )
                if unknown:
                    raise RuntimeError(
                        "Unknown window before exact TCU observation; signatures="
                        f"{_sanitized_window_signatures(unknown)!r}"
                    )
                candidate = None
                candidate_since = None
                time.sleep(poll_interval_seconds)
                continue

            tcu = legal_windows[0]
            unknown_alongside = tuple(
                window
                for window in windows
                if window.hwnd != tcu.hwnd
                and not _is_acceptance_main_shell(window, title_markers)
                and not _is_tcu_phase_companion_window(window)
                and not _is_acceptance_companion_window(window)
            )
            if unknown_alongside:
                raise RuntimeError(
                    "Unknown window alongside exact TCU; signatures="
                    f"{_sanitized_window_signatures(unknown_alongside)!r}"
                )
            (
                _controls,
                control_hash,
                adapter_hash,
                full_tree_hash,
                body_hash,
            ) = _inspect_legacy_tcu_contract(
                tcu,
                expected_next_enabled=False,
            )
            top_hash = _fingerprint(
                {
                    "class_name": tcu.class_name,
                    "title": tcu.title,
                    "owner_present": bool(tcu.owner_hwnd),
                    "enabled": tcu.enabled,
                }
            )
            modal_hash = _fingerprint(
                {
                    "top_signature_sha256": top_hash,
                    "legal_dialog_body_sha256": body_hash,
                    "control_contract_sha256": control_hash,
                }
            )
            current = (
                top_hash,
                body_hash,
                control_hash,
                adapter_hash,
                full_tree_hash,
                modal_hash,
            )
            if current != candidate:
                candidate = current
                candidate_since = time.monotonic()
            elif (
                candidate_since is not None
                and time.monotonic() - candidate_since
                >= stable_observation_seconds
            ):
                final_hashes = current
                break
            time.sleep(poll_interval_seconds)
        else:
            raise TimeoutError("Timed out waiting for stable exact legacy TCU")
    except BaseException as exc:
        observation_error = exc
    finally:
        if process is not None:
            try:
                observed_pids.update(watchdog.scoped_pids())
            except Exception as exc:
                observation_error = observation_error or RuntimeError(
                    "Final source TCU process enumeration failed"
                )
                if observation_error.__cause__ is None:
                    observation_error.__cause__ = exc
            try:
                termination_verified = watchdog.terminate_process_tree(process.pid)
            except Exception as exc:
                termination_verified = False
                observation_error = observation_error or RuntimeError(
                    "Source TCU process-tree termination failed"
                )
                if observation_error.__cause__ is None:
                    observation_error.__cause__ = exc

    remaining: List[int] = []
    for pid in sorted(observed_pids):
        try:
            if psutil.pid_exists(pid):
                remaining.append(pid)
        except Exception:
            remaining.append(pid)
    survivors = tuple(remaining)
    if not termination_verified or survivors:
        raise RuntimeError(
            "Source TCU process-tree termination could not be verified"
        ) from observation_error
    if observation_error is not None:
        raise observation_error.with_traceback(observation_error.__traceback__)
    if final_hashes is None:
        raise RuntimeError("Exact legacy TCU evidence was not captured")
    if watchdog.dismissed or watchdog.blocked or watchdog.supervision_error:
        raise RuntimeError("Source TCU observation did not remain zero-input")
    (
        top_hash,
        body_hash,
        control_hash,
        adapter_hash,
        full_tree_hash,
        modal_hash,
    ) = final_hashes
    return _LegacyTcuObservation(
        top_signature_sha256=top_hash,
        legal_dialog_body_sha256=body_hash,
        control_contract_sha256=control_hash,
        adapter_contract_sha256=adapter_hash,
        full_tree_contract_sha256=full_tree_hash,
        normalized_modal_signature_sha256=modal_hash,
        observed_process_ids=tuple(sorted(observed_pids)),
        process_tree_terminated=termination_verified,
        survivors=survivors,
        automated_ui_interactions=0,
        elapsed_seconds=time.monotonic() - started_at,
        observed_at_utc=_utc_now(),
    )


def _version_matches(expected: str, detected: str) -> bool:
    expected_normalized = RasUtils.normalize_ras_version(expected)
    detected_normalized = RasUtils.normalize_ras_version(detected)
    if "beta" in expected_normalized.casefold():
        expected_base = expected_normalized.casefold().split("beta", 1)[0].strip()
        return detected_normalized.casefold() == expected_base
    return detected_normalized == expected_normalized


def _bundle_fingerprint_payload(
    identity: "RasExecutableIdentity",
    state: "RegistryValueSnapshot",
    source_probe: Optional["AcceptanceProbeResult"],
    legacy_tcu_contract: Optional["LegacyTcuContractEvidence"] = None,
) -> dict:
    payload = {
        "identity": asdict(identity),
        "state": asdict(state),
        "source_probe": asdict(source_probe) if source_probe is not None else None,
    }
    if legacy_tcu_contract is not None:
        payload["legacy_tcu_contract"] = asdict(legacy_tcu_contract)
    return payload


def _is_acceptance_main_window(
    window: ObservedWindow,
    title_markers: Sequence[str],
) -> bool:
    """Return True only for the main-window signature proven by the matrix."""
    return (
        window.class_name.casefold() == "thunderrt6main"
        and window.owner_hwnd == 0
        and window.enabled
        and (
            window.title.strip().casefold() == "ras"
            or any(marker in window.title.casefold() for marker in title_markers)
        )
    )


def _is_acceptance_companion_window(window: ObservedWindow) -> bool:
    """Allow only startup companion signatures observed across 4.x--7.x.

    These windows are part of a normal idle HEC-RAS startup. Legal-dialog
    classification runs first, so a TCU form can never be allowlisted here.
    """
    class_name = window.class_name.casefold()
    title = window.title.strip().casefold()
    return bool(
        window.enabled
        and (
            (
                class_name == "thunderrt6main"
                and not title
                and window.owner_hwnd == 0
            )
            or (
                bool(window.owner_hwnd)
                and (
                    (
                        class_name == "thunderrt6formdc"
                        and title.startswith("hec-ras ")
                    )
                    or (
                        class_name.startswith("hwndwrapper[rasplotdriver.exe;;")
                        and title == "time series"
                    )
                )
            )
        )
    )


def _is_acceptance_main_shell(
    window: ObservedWindow,
    title_markers: Sequence[str],
) -> bool:
    """Recognize the exact main-window shell, including its disabled state."""
    title = window.title.strip().casefold()
    return bool(
        window.class_name.casefold() == "thunderrt6main"
        and window.owner_hwnd == 0
        and (
            not title
            or title == "ras"
            or any(marker in title for marker in title_markers)
        )
    )


def _is_tcu_phase_companion_window(window: ObservedWindow) -> bool:
    """Allow the observed owned 4.x TCU companion shell while assent is open."""
    return bool(
        window.class_name.casefold() == "thunderrt6formdc"
        and bool(window.owner_hwnd)
        and window.title.strip().casefold().startswith("hec-ras ")
    )


def _is_actual_hecras_tcu_window(window: ObservedWindow) -> bool:
    """Require live HEC-RAS TCU text, not merely a generic legal-dialog label."""
    combined = f"{window.title} {window.body}".casefold()
    return bool(
        window.legal_reason
        and window.body.strip()
        and (
            "terms and conditions for use" in combined
            or "terms and conditions of use" in combined
        )
    )


def _observed_window_signature(window: ObservedWindow) -> Tuple[str, ...]:
    return (
        window.class_name,
        window.title,
        str(window.owner_hwnd),
        str(int(window.enabled)),
    )


def _sanitized_window_signatures(
    windows: Sequence[ObservedWindow],
) -> Tuple[Tuple[str, ...], ...]:
    """Return class/title/owner/enabled diagnostics without body/control text."""
    return tuple(_observed_window_signature(window) for window in windows)


def _strict_restart_probe_verified(
    probe: "AcceptanceProbeResult",
    identity: "RasExecutableIdentity",
    *,
    timeout_seconds: float,
    title_markers: Sequence[str],
) -> bool:
    """Validate the evidence expected from an ordinary full-duration probe."""
    signature = probe.main_window_signature
    if len(signature) != 4:
        return False
    class_name, title, owner_hwnd, enabled = signature
    exact_main = ObservedWindow(
        hwnd=0,
        pid=0,
        class_name=class_name,
        title=title,
        body="",
        owner_hwnd=int(owner_hwnd) if owner_hwnd.lstrip("-").isdigit() else -1,
        enabled=enabled == "1",
        legal_reason=None,
    )
    return bool(
        probe.identity == identity
        and probe.no_modal_verified
        and probe.elapsed_seconds >= timeout_seconds
        and _is_acceptance_main_window(exact_main, title_markers)
        and probe.topology_signatures
        and probe.observed_process_ids
    )


def _acceptance_window_partition(
    windows: Sequence[ObservedWindow],
    title_markers: Sequence[str],
) -> Tuple[Tuple[ObservedWindow, ...], Tuple[ObservedWindow, ...]]:
    """Return recognized main windows and unrecognized visible windows."""
    main_windows = tuple(
        window
        for window in windows
        if _is_acceptance_main_window(window, title_markers)
    )
    accepted_hwnds = {window.hwnd for window in main_windows}
    accepted_hwnds.update(
        window.hwnd
        for window in windows
        if _is_acceptance_companion_window(window)
    )
    unknown_windows = tuple(
        window for window in windows if window.hwnd not in accepted_hwnds
    )
    return main_windows, unknown_windows


def _application_root(projects_key: str) -> str:
    suffix = f"\\{_REGISTRY_SECTION}"
    if not projects_key.casefold().endswith(suffix.casefold()):
        raise ValueError(f"Unexpected acceptance-state key: {projects_key}")
    return projects_key[: -len(suffix)]


def _subtree_fingerprint(snapshot) -> Optional[str]:
    if snapshot is None:
        return None
    return _fingerprint({"registry_subtree": snapshot})


@contextmanager
def _cross_process_lock(key: str, timeout_seconds: float = 30.0):
    """Acquire a profile-local OS file lock for one exact registry key."""
    if os.name != "nt":
        yield
        return
    import msvcrt

    lock_name = hashlib.sha256(key.casefold().encode("utf-8")).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"ras-acceptance-{lock_name}.lock"
    with lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out acquiring acceptance-state lock for {key}"
                    )
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


@dataclass(frozen=True)
class RasExecutableIdentity:
    """Identity of the exact executable used by a probe or state bundle."""

    path: str
    version: str
    sha256: str
    detected_version: Optional[str] = None
    file_version: Optional[str] = None
    product_version: Optional[str] = None
    architecture: Optional[str] = None


@dataclass(frozen=True)
class RegistryValueSnapshot:
    """Exact snapshot of one registry value."""

    key: str
    name: str
    exists: bool
    value: Optional[str]
    registry_type: Optional[int]


@dataclass(frozen=True)
class AcceptanceProbeResult:
    """Fail-closed outcome of a short HEC-RAS GUI startup probe."""

    identity: RasExecutableIdentity
    status: str
    started: bool
    visible_window_seen: bool
    visible_titles: Tuple[str, ...]
    blocked_reason: Optional[str]
    blocked_titles: Tuple[str, ...]
    interactions: int
    process_tree_terminated: bool
    survivors: Tuple[int, ...]
    elapsed_seconds: float
    observed_at_utc: str
    main_window_signature: Tuple[str, ...] = ()
    topology_signatures: Tuple[str, ...] = ()
    observed_process_ids: Tuple[int, ...] = ()

    @property
    def no_modal_verified(self) -> bool:
        return (
            self.status == "ready"
            and self.started
            and self.visible_window_seen
            and self.interactions == 0
            and self.process_tree_terminated
            and not self.survivors
            and self.blocked_reason is None
            and not self.blocked_titles
        )


@dataclass(frozen=True)
class LegacyTcuContractEvidence:
    """Hash-only exact-source evidence for the legacy VB6 TCU contract."""

    target: RasExecutableIdentity
    original_bundle_fingerprint: str
    initial_source_probe_sha256: str
    final_source_probe_sha256: str
    top_signature_sha256: str
    legal_dialog_body_sha256: str
    control_contract_sha256: str
    source_adapter_contract_sha256: str
    source_full_tree_contract_sha256: str
    normalized_modal_signature_sha256: str
    process_tree_terminated: bool
    survivors: Tuple[int, ...]
    automated_ui_interactions: int
    observation_elapsed_seconds: float
    observed_at_utc: str
    fingerprint: str

    @property
    def passed(self) -> bool:
        return bool(
            self.target.version in _AUTHORIZED_LEGACY_UI_VERSIONS
            and all(
                _is_sha256(value)
                for value in (
                    self.original_bundle_fingerprint,
                    self.initial_source_probe_sha256,
                    self.final_source_probe_sha256,
                    self.top_signature_sha256,
                    self.legal_dialog_body_sha256,
                    self.control_contract_sha256,
                    self.source_adapter_contract_sha256,
                    self.source_full_tree_contract_sha256,
                    self.normalized_modal_signature_sha256,
                    self.fingerprint,
                )
            )
            and self.process_tree_terminated
            and not self.survivors
            and self.automated_ui_interactions == 0
            and self.observation_elapsed_seconds > 0
        )


@dataclass(frozen=True)
class AcceptanceStateBundle:
    """Captured opaque sentinel plus optional source no-modal proof."""

    identity: RasExecutableIdentity
    state: RegistryValueSnapshot
    source_probe: Optional[AcceptanceProbeResult]
    captured_at_utc: str
    fingerprint: str
    legacy_tcu_contract: Optional[LegacyTcuContractEvidence] = None

    @property
    def no_modal_verified(self) -> bool:
        return bool(self.source_probe and self.source_probe.no_modal_verified)


@dataclass(frozen=True)
class LegacyUiTransferSourceCapture:
    """Original and extended private bundles from a safe source capture."""

    original_bundle: AcceptanceStateBundle
    extended_bundle: AcceptanceStateBundle
    contract_evidence: LegacyTcuContractEvidence

    @property
    def passed(self) -> bool:
        return bool(
            self.original_bundle.no_modal_verified
            and self.extended_bundle.no_modal_verified
            and self.contract_evidence.passed
            and self.extended_bundle.legacy_tcu_contract
            == self.contract_evidence
        )


@dataclass(frozen=True)
class AcceptanceDiagnosticReceipt:
    """Receipt for a restoring candidate-state diagnostic."""

    target: RasExecutableIdentity
    source_version: str
    transition: Tuple[str, str]
    candidate_value: str
    candidate_registry_type: int
    candidate_fingerprint: str
    before: RegistryValueSnapshot
    applied: RegistryValueSnapshot
    restored: RegistryValueSnapshot
    probe: AcceptanceProbeResult
    registry_restored: bool
    passed: bool
    diagnostic_label: str
    created_at_utc: str
    after_probe: Optional[RegistryValueSnapshot] = None
    candidate_stayed_exact: bool = False
    application_subtree_before_fingerprint: Optional[str] = None
    application_subtree_after_probe_fingerprint: Optional[str] = None
    application_subtree_restored_fingerprint: Optional[str] = None
    candidate_origin: str = "captured_verified"
    source_bundle_fingerprint: Optional[str] = None
    clean_application_subtree_for_probe: bool = False


@dataclass(frozen=True)
class AcceptanceProvisionReceipt:
    """Receipt for an explicitly authorized write into a disposable target."""

    target: RasExecutableIdentity
    key: str
    value_name: str
    value: str
    registry_type: int
    diagnostic_fingerprint: str
    authorization_reference: str
    dry_run: bool
    written: bool
    created_at_utc: str
    application_subtree_replaced: bool = False


@dataclass(frozen=True)
class UserDrivenAcceptanceReceipt:
    """Hash-only receipt for one human-completed HEC-RAS TCU session."""

    target: RasExecutableIdentity
    status: str
    destination_is_disposable: bool
    source_evidence_sha256: str
    authorization_reference_sha256: str
    beta_authorization_reference_sha256: Optional[str]
    profile_instance_token_sha256: str
    legal_dialog_body_sha256: str
    legal_dialog_signature: Tuple[str, ...]
    main_window_signature: Tuple[str, ...]
    observed_process_ids: Tuple[int, ...]
    process_tree_terminated: bool
    survivors: Tuple[int, ...]
    automated_ui_interactions: int
    initial_session_elapsed_seconds: float
    restart_timeout_seconds: float
    restart_ready_seconds: float
    restart_probes: Tuple[AcceptanceProbeResult, ...]
    created_at_utc: str
    fingerprint: str

    @property
    def passed(self) -> bool:
        beta_target = "beta" in self.target.version.casefold()
        return bool(
            self.status == "accepted_and_restarts_verified"
            and self.destination_is_disposable
            and _is_sha256(self.source_evidence_sha256)
            and _is_sha256(self.authorization_reference_sha256)
            and _is_sha256(self.profile_instance_token_sha256)
            and _is_sha256(self.legal_dialog_body_sha256)
            and (
                _is_sha256(self.beta_authorization_reference_sha256)
                if beta_target
                else self.beta_authorization_reference_sha256 is None
            )
            and bool(self.legal_dialog_signature)
            and bool(self.main_window_signature)
            and _is_sha256(self.fingerprint)
            and self.process_tree_terminated
            and not self.survivors
            and self.automated_ui_interactions == 0
            and len(self.restart_probes) == 2
            and all(
                _strict_restart_probe_verified(
                    probe,
                    self.target,
                    timeout_seconds=self.restart_timeout_seconds,
                    title_markers=("hec-ras", "river analysis system"),
                )
                for probe in self.restart_probes
            )
        )


@dataclass(frozen=True)
class AuthorizedLegacyUiTransferReceipt:
    """Hash-only receipt for the six-build authorized VB6 UI fallback."""

    target: RasExecutableIdentity
    status: str
    destination_is_disposable: bool
    source_bundle_file_sha256: str
    source_bundle_fingerprint: str
    source_modal_signature_sha256: str
    target_modal_signature_sha256: str
    authorization_reference_sha256: str
    profile_instance_token_sha256: str
    legal_dialog_body_sha256: str
    control_contract_sha256: str
    source_adapter_contract_sha256: str
    target_adapter_contract_sha256: str
    source_full_tree_contract_sha256: str
    target_full_tree_contract_sha256: str
    main_window_signature: Tuple[str, ...]
    observed_process_ids: Tuple[int, ...]
    process_tree_terminated: bool
    survivors: Tuple[int, ...]
    automated_ui_interactions: int
    initial_session_elapsed_seconds: float
    pre_restart_quiet_seconds: float
    pre_restart_quiet_observations: Tuple[float, ...]
    restart_timeout_seconds: float
    restart_ready_seconds: float
    restart_probes: Tuple[AcceptanceProbeResult, ...]
    created_at_utc: str
    fingerprint: str

    @property
    def passed(self) -> bool:
        return bool(
            self.status == "authorized_ui_transfer_and_restarts_verified"
            and self.target.version in _AUTHORIZED_LEGACY_UI_VERSIONS
            and self.destination_is_disposable
            and all(
                _is_sha256(value)
                for value in (
                    self.source_bundle_file_sha256,
                    self.source_bundle_fingerprint,
                    self.source_modal_signature_sha256,
                    self.target_modal_signature_sha256,
                    self.authorization_reference_sha256,
                    self.profile_instance_token_sha256,
                    self.legal_dialog_body_sha256,
                    self.control_contract_sha256,
                    self.source_adapter_contract_sha256,
                    self.target_adapter_contract_sha256,
                    self.source_full_tree_contract_sha256,
                    self.target_full_tree_contract_sha256,
                    self.fingerprint,
                )
            )
            and self.source_modal_signature_sha256
            == self.target_modal_signature_sha256
            and self.process_tree_terminated
            and not self.survivors
            and self.automated_ui_interactions == 2
            and self.pre_restart_quiet_seconds
            >= _LEGACY_PRE_RESTART_QUIET_SECONDS
            and len(self.pre_restart_quiet_observations) == 2
            and all(
                elapsed >= self.pre_restart_quiet_seconds
                for elapsed in self.pre_restart_quiet_observations
            )
            and len(self.restart_probes) == 2
            and all(
                _strict_restart_probe_verified(
                    probe,
                    self.target,
                    timeout_seconds=self.restart_timeout_seconds,
                    title_markers=("hec-ras", "river analysis system"),
                )
                for probe in self.restart_probes
            )
        )


class _WinRegistryBackend:
    """Minimal allowlisted registry backend used by the public API."""

    def __init__(self) -> None:
        if winreg is None:
            raise RuntimeError("Acceptance-state registry operations require Windows/Wine")
        self._view = getattr(winreg, "KEY_WOW64_32KEY", 0)

    @staticmethod
    def _prefixes(subkey: str) -> List[str]:
        parts = subkey.split("\\")
        return ["\\".join(parts[:index]) for index in range(1, len(parts) + 1)]

    def key_exists(self, subkey: str) -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_READ | self._view,
            ):
                return True
        except FileNotFoundError:
            return False

    def snapshot(self, subkey: str) -> RegistryValueSnapshot:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_READ | self._view,
            ) as key:
                value, registry_type = winreg.QueryValueEx(key, _VALUE_NAME)
        except FileNotFoundError:
            return RegistryValueSnapshot(subkey, _VALUE_NAME, False, None, None)
        return RegistryValueSnapshot(
            subkey,
            _VALUE_NAME,
            True,
            str(value),
            int(registry_type),
        )

    def key_values(self, subkey: str) -> Dict[str, Tuple[object, int]]:
        values: Dict[str, Tuple[object, int]] = {}
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_READ | self._view,
            ) as key:
                count = winreg.QueryInfoKey(key)[1]
                for index in range(count):
                    name, value, registry_type = winreg.EnumValue(key, index)
                    values[name] = (value, registry_type)
        except FileNotFoundError:
            pass
        return values

    def subtree_snapshot(
        self,
        subkey: str,
    ) -> Dict[str, Dict[str, Tuple[object, int]]]:
        """Return an exact in-memory snapshot of one application subtree."""
        if not self.key_exists(subkey):
            return {}
        snapshot: Dict[str, Dict[str, Tuple[object, int]]] = {}

        def walk(current: str, relative: str) -> None:
            snapshot[relative] = self.key_values(current)
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                current,
                0,
                winreg.KEY_READ | self._view,
            ) as key:
                count = winreg.QueryInfoKey(key)[0]
                children = [winreg.EnumKey(key, index) for index in range(count)]
            for child in children:
                child_relative = child if not relative else f"{relative}\\{child}"
                walk(f"{current}\\{child}", child_relative)

        walk(subkey, "")
        return snapshot

    def _delete_tree(self, subkey: str) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_READ | winreg.KEY_WRITE | self._view,
            ) as key:
                children = [
                    winreg.EnumKey(key, index)
                    for index in range(winreg.QueryInfoKey(key)[0])
                ]
        except FileNotFoundError:
            return
        for child in children:
            self._delete_tree(f"{subkey}\\{child}")
        delete_key_ex = getattr(winreg, "DeleteKeyEx", None)
        if delete_key_ex:
            delete_key_ex(winreg.HKEY_CURRENT_USER, subkey, self._view, 0)
        else:  # pragma: no cover - old Python fallback
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)

    def restore_subtree(
        self,
        subkey: str,
        snapshot: Dict[str, Dict[str, Tuple[object, int]]],
    ) -> None:
        """Replace one application subtree with an exact prior snapshot."""
        self._delete_tree(subkey)
        for relative in sorted(snapshot, key=lambda item: (item.count("\\"), item)):
            current = subkey if not relative else f"{subkey}\\{relative}"
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                current,
                0,
                winreg.KEY_WRITE | self._view,
            ) as key:
                for name, (value, registry_type) in snapshot[relative].items():
                    winreg.SetValueEx(key, name, 0, registry_type, value)

    def set_value(self, subkey: str, value: str, registry_type: int) -> List[str]:
        if registry_type != winreg.REG_SZ:
            raise ValueError("System Statistic must preserve its observed REG_SZ type")
        created: List[str] = []
        for prefix in self._prefixes(subkey):
            if self.key_exists(prefix):
                continue
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                prefix,
                0,
                winreg.KEY_WRITE | self._view,
            ):
                pass
            created.append(prefix)
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_SET_VALUE | self._view,
        ) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, registry_type, value)
        return created

    def delete_value(self, subkey: str) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_SET_VALUE | self._view,
            ) as key:
                winreg.DeleteValue(key, _VALUE_NAME)
        except FileNotFoundError:
            pass

    def restore_value(
        self,
        snapshot: RegistryValueSnapshot,
        created_prefixes: Sequence[str],
    ) -> None:
        if snapshot.exists:
            self.set_value(
                snapshot.key,
                snapshot.value or "",
                int(snapshot.registry_type),
            )
        else:
            self.delete_value(snapshot.key)

        for prefix in reversed(created_prefixes):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    prefix,
                    0,
                    winreg.KEY_READ | self._view,
                ) as key:
                    subkeys, values, _modified = winreg.QueryInfoKey(key)
                if subkeys or values:
                    continue
                delete_key_ex = getattr(winreg, "DeleteKeyEx", None)
                if delete_key_ex:
                    delete_key_ex(
                        winreg.HKEY_CURRENT_USER,
                        prefix,
                        self._view,
                        0,
                    )
                else:  # pragma: no cover - old Python fallback
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, prefix)
            except FileNotFoundError:
                pass


class RasAcceptanceState:
    """Static namespace for HEC-RAS acceptance-state qualification."""

    _locks: Dict[str, threading.RLock] = {}
    _locks_guard = threading.Lock()

    @staticmethod
    @log_call
    def executable_identity(
        ras_executable: str | Path,
        *,
        expected_version: Optional[str] = None,
        verify_executable_version: bool = True,
    ) -> RasExecutableIdentity:
        path = Path(ras_executable).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"HEC-RAS executable not found: {path}")
        metadata = RasUtils.get_executable_version(path)
        detected = metadata.get("normalized_version")
        version = expected_version or detected or path.parent.name
        if verify_executable_version:
            if not metadata.get("valid_pe") or not detected:
                raise ValueError(
                    f"Could not verify HEC-RAS PE/version metadata for {path}: "
                    f"{metadata.get('error') or metadata!r}"
                )
            if expected_version and not _version_matches(expected_version, detected):
                raise ValueError(
                    f"HEC-RAS executable version mismatch: expected "
                    f"{expected_version!r}, detected {detected!r} at {path}"
                )
            if (
                expected_version
                and "beta" in expected_version.casefold()
                and path.parent.name.strip().casefold()
                != RasUtils.normalize_ras_version(expected_version).strip().casefold()
            ):
                raise ValueError(
                    "The PE metadata does not encode the HEC-RAS beta qualifier; "
                    "the exact beta name must match the installation directory "
                    f"({expected_version!r} != {path.parent.name!r})"
                )
        return RasExecutableIdentity(
            path=str(path),
            version=str(version),
            sha256=_sha256_file(path),
            detected_version=detected,
            file_version=metadata.get("file_version"),
            product_version=metadata.get("product_version"),
            architecture=metadata.get("architecture"),
        )

    @staticmethod
    @log_call
    def application_name_for_version(version: str) -> str:
        """Return the observed VB application-name segment for a release."""
        major_text = version.strip().split(".", 1)[0]
        if not major_text.isdigit():
            raise ValueError(f"HEC-RAS version must begin with a numeric major: {version!r}")
        major = int(major_text)
        return "ras" if major <= 4 else "ras.exe"

    @staticmethod
    @log_call
    def registry_subkey(
        ras_executable: str | Path,
        *,
        expected_version: Optional[str] = None,
        application_name: Optional[str] = None,
    ) -> str:
        """Build the exact install-path-scoped VB Projects registry key."""
        raw = str(ras_executable)
        win_path = PureWindowsPath(raw)
        if not win_path.drive:
            raise ValueError(
                "A Windows path (for example C:\\Program Files\\...\\Ras.exe) "
                "is required to derive HEC-RAS VB application state"
            )
        version = expected_version or win_path.parent.name
        app_name = application_name or RasAcceptanceState.application_name_for_version(
            version
        )
        return "\\".join(
            (_REGISTRY_ROOT, str(win_path.parent), app_name, _REGISTRY_SECTION)
        )

    @staticmethod
    @log_call
    def capture(
        ras_executable: str | Path,
        *,
        expected_version: Optional[str] = None,
        source_probe: Optional[AcceptanceProbeResult] = None,
        verify_executable_version: bool = True,
        registry=None,
    ) -> AcceptanceStateBundle:
        """Capture the exact opaque System Statistic value for one release."""
        identity = RasAcceptanceState.executable_identity(
            ras_executable,
            expected_version=expected_version,
            verify_executable_version=verify_executable_version,
        )
        key = RasAcceptanceState.registry_subkey(
            identity.path,
            expected_version=identity.version,
        )
        backend = registry or _WinRegistryBackend()
        state = backend.snapshot(key)
        if not state.exists:
            raise FileNotFoundError(f"No captured acceptance-state sentinel at {key}")
        if winreg is not None and state.registry_type != winreg.REG_SZ:
            raise ValueError("System Statistic exists but is not REG_SZ")
        if source_probe and source_probe.identity != identity:
            raise ValueError("Source probe executable identity does not match capture")
        payload = _bundle_fingerprint_payload(identity, state, source_probe)
        return AcceptanceStateBundle(
            identity,
            state,
            source_probe,
            _utc_now(),
            _fingerprint(payload),
        )

    @staticmethod
    @log_call
    def capture_authorized_legacy_ui_transfer_source(
        ras_executable: str | Path,
        *,
        expected_version: str,
        probe_timeout_seconds: float = 45.0,
        probe_ready_seconds: float = 20.0,
        legal_timeout_seconds: float = 20.0,
        legal_observation_seconds: float = 0.5,
        poll_interval_seconds: float = 0.05,
        registry=None,
    ) -> LegacyUiTransferSourceCapture:
        """Capture a verified source bundle plus exact hash-only VB6 contract.

        This method is limited to the six installed stable 4.0--6.0 builds.
        It verifies an already accepted source, captures the original opaque
        item, removes only that item in a restoring transaction, observes the
        exact TCU/control tree with zero input, verifies restoration, and then
        repeats the accepted-source probe. No artifact is returned unless the
        complete chain succeeds.
        """
        if expected_version not in _AUTHORIZED_LEGACY_UI_VERSIONS:
            raise ValueError(
                "Authorized legacy UI source capture is limited to exact stable "
                "builds 4.0, 4.1.0, 5.0.3, 5.0.6, 5.0.7, and 6.0"
            )
        numeric = {
            "probe_timeout_seconds": probe_timeout_seconds,
            "probe_ready_seconds": probe_ready_seconds,
            "legal_timeout_seconds": legal_timeout_seconds,
            "legal_observation_seconds": legal_observation_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        }
        if any(value <= 0 for value in numeric.values()):
            raise ValueError("All source-capture timing values must be positive")
        if probe_timeout_seconds < 20.0:
            raise ValueError("Source probes must run for at least 20 seconds")
        if probe_timeout_seconds < probe_ready_seconds:
            raise ValueError(
                "probe_timeout_seconds must be at least probe_ready_seconds"
            )
        if legal_timeout_seconds < legal_observation_seconds:
            raise ValueError(
                "legal_timeout_seconds must cover the stable observation interval"
            )

        identity = RasAcceptanceState.executable_identity(
            ras_executable,
            expected_version=expected_version,
            verify_executable_version=True,
        )
        if RasAcceptanceState._target_running(identity):
            raise RuntimeError("Refusing source capture while the target is running")
        title_markers = ("hec-ras", "river analysis system")
        initial_probe = RasAcceptanceState.probe(
            identity.path,
            expected_version=identity.version,
            timeout_seconds=probe_timeout_seconds,
            ready_seconds=probe_ready_seconds,
            verify_executable_version=True,
        )
        if not _strict_restart_probe_verified(
            initial_probe,
            identity,
            timeout_seconds=probe_timeout_seconds,
            title_markers=title_markers,
        ):
            raise RuntimeError("Initial accepted-source probe did not pass safely")

        backend = registry or _WinRegistryBackend()
        original_bundle = RasAcceptanceState.capture(
            identity.path,
            expected_version=identity.version,
            source_probe=initial_probe,
            verify_executable_version=True,
            registry=backend,
        )
        if (
            not original_bundle.state.exists
            or original_bundle.state.value is None
            or not original_bundle.state.value
            or original_bundle.state.registry_type is None
        ):
            raise RuntimeError("Accepted source bundle lacks exact opaque state")

        with RasAcceptanceState.temporary_system_statistic(
            identity.path,
            None,
            expected_version=identity.version,
            diagnostic_label="authorized-legacy-ui-source-tcu-observation",
            verify_executable_version=True,
            replace_application_subtree=False,
            registry=backend,
        ) as (before, applied):
            if before != original_bundle.state or applied.exists:
                raise RuntimeError(
                    "Source acceptance item was not removed exactly for observation"
                )
            observation = _observe_exact_legacy_tcu_without_input(
                identity,
                timeout_seconds=legal_timeout_seconds,
                stable_observation_seconds=legal_observation_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )

        key = RasAcceptanceState.registry_subkey(
            identity.path,
            expected_version=identity.version,
        )
        restored_state = backend.snapshot(key)
        if restored_state != original_bundle.state:
            raise RuntimeError("Source acceptance item was not restored exactly")

        final_probe = RasAcceptanceState.probe(
            identity.path,
            expected_version=identity.version,
            timeout_seconds=probe_timeout_seconds,
            ready_seconds=probe_ready_seconds,
            verify_executable_version=True,
        )
        if not _strict_restart_probe_verified(
            final_probe,
            identity,
            timeout_seconds=probe_timeout_seconds,
            title_markers=title_markers,
        ):
            raise RuntimeError("Final restored-source probe did not pass safely")

        evidence_payload = {
            "target": asdict(identity),
            "original_bundle_fingerprint": original_bundle.fingerprint,
            "initial_source_probe_sha256": _fingerprint(asdict(initial_probe)),
            "final_source_probe_sha256": _fingerprint(asdict(final_probe)),
            "top_signature_sha256": observation.top_signature_sha256,
            "legal_dialog_body_sha256": observation.legal_dialog_body_sha256,
            "control_contract_sha256": observation.control_contract_sha256,
            "source_adapter_contract_sha256": (
                observation.adapter_contract_sha256
            ),
            "source_full_tree_contract_sha256": (
                observation.full_tree_contract_sha256
            ),
            "normalized_modal_signature_sha256": (
                observation.normalized_modal_signature_sha256
            ),
            "process_tree_terminated": observation.process_tree_terminated,
            "survivors": observation.survivors,
            "automated_ui_interactions": observation.automated_ui_interactions,
            "observation_elapsed_seconds": observation.elapsed_seconds,
            "observed_at_utc": observation.observed_at_utc,
        }
        evidence = LegacyTcuContractEvidence(
            target=identity,
            original_bundle_fingerprint=original_bundle.fingerprint,
            initial_source_probe_sha256=evidence_payload[
                "initial_source_probe_sha256"
            ],
            final_source_probe_sha256=evidence_payload["final_source_probe_sha256"],
            top_signature_sha256=observation.top_signature_sha256,
            legal_dialog_body_sha256=observation.legal_dialog_body_sha256,
            control_contract_sha256=observation.control_contract_sha256,
            source_adapter_contract_sha256=(
                observation.adapter_contract_sha256
            ),
            source_full_tree_contract_sha256=(
                observation.full_tree_contract_sha256
            ),
            normalized_modal_signature_sha256=(
                observation.normalized_modal_signature_sha256
            ),
            process_tree_terminated=observation.process_tree_terminated,
            survivors=observation.survivors,
            automated_ui_interactions=observation.automated_ui_interactions,
            observation_elapsed_seconds=observation.elapsed_seconds,
            observed_at_utc=observation.observed_at_utc,
            fingerprint=_fingerprint(evidence_payload),
        )
        if not evidence.passed:
            raise RuntimeError("Source legacy TCU evidence did not pass")
        extended_payload = _bundle_fingerprint_payload(
            identity,
            restored_state,
            final_probe,
            evidence,
        )
        extended_bundle = AcceptanceStateBundle(
            identity=identity,
            state=restored_state,
            source_probe=final_probe,
            captured_at_utc=_utc_now(),
            fingerprint=_fingerprint(extended_payload),
            legacy_tcu_contract=evidence,
        )
        result = LegacyUiTransferSourceCapture(
            original_bundle=original_bundle,
            extended_bundle=extended_bundle,
            contract_evidence=evidence,
        )
        if not result.passed:
            raise RuntimeError("Authorized legacy UI source capture failed closed")
        return result

    @staticmethod
    def _target_running(identity: RasExecutableIdentity) -> bool:
        if psutil is None:
            raise RuntimeError(
                "psutil is required to prove that the target executable is not "
                "already running"
            )
        target = str(Path(identity.path)).casefold()
        for process in psutil.process_iter(["exe"]):
            try:
                executable = process.info.get("exe")
                if executable and str(Path(executable)).casefold() == target:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    @staticmethod
    @log_call
    def probe(
        ras_executable: str | Path,
        *,
        expected_version: Optional[str] = None,
        timeout_seconds: float = 15.0,
        ready_seconds: float = 2.0,
        startup_args: Sequence[str] = (),
        verify_executable_version: bool = True,
        main_window_title_markers: Sequence[str] = (
            "hec-ras",
            "river analysis system",
        ),
    ) -> AcceptanceProbeResult:
        """Start HEC-RAS briefly and prove ready/no-modal or fail closed.

        This is the only launch path used by acceptance-state qualification. It
        supplies no informational-dialog allowlist, never clicks or closes a
        dialog, and terminates the registered process tree in every outcome.
        """
        started_at = time.monotonic()
        identity = RasAcceptanceState.executable_identity(
            ras_executable,
            expected_version=expected_version,
            verify_executable_version=verify_executable_version,
        )
        if RasAcceptanceState._target_running(identity):
            raise RuntimeError(
                f"Refusing probe while target is already running: {identity.path}"
            )

        if timeout_seconds <= 0 or ready_seconds <= 0:
            raise ValueError("timeout_seconds and ready_seconds must be positive")
        if timeout_seconds < ready_seconds:
            raise ValueError("timeout_seconds must be at least ready_seconds")
        normalized_main_markers = tuple(
            marker.strip().casefold()
            for marker in main_window_title_markers
            if marker and marker.strip()
        )
        if not normalized_main_markers:
            raise ValueError("At least one main-window title marker is required")

        watchdog = DialogWatchdog(poll_interval=0.1, safe_dialog_titles=set())
        watchdog.require_available()
        process: Optional[subprocess.Popen] = None
        started = False
        visible_seen = False
        visible_titles: set[str] = set()
        topology_signatures: set[str] = set()
        observed_pids: set[int] = set()
        qualifying_since: Optional[float] = None
        qualifying_signature: Optional[Tuple[str, ...]] = None
        main_window_signature: Tuple[str, ...] = ()
        stable_main_seen = False
        current_main_stable = False
        local_blocked_reason: Optional[str] = None
        local_blocked_titles: List[str] = []
        local_supervision_error: Optional[str] = None
        termination_verified = False
        status = "launch_failed"

        try:
            command = [identity.path, *[str(arg) for arg in startup_args]]
            process = subprocess.Popen(
                command,
                cwd=str(Path(identity.path).parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            started = True
            observed_pids.add(process.pid)
            watchdog.add_pid(process.pid)
            watchdog.start()

            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                if watchdog.blocked_reason:
                    break
                if process.poll() is not None:
                    break
                try:
                    observed_pids.update(watchdog.scoped_pids())
                    windows = watchdog.observe_windows()
                except Exception as exc:
                    local_supervision_error = (
                        "Acceptance probe window inspection failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    status = "supervision_failed"
                    break

                if windows:
                    visible_seen = True
                    visible_titles.update(
                        window.title for window in windows if window.title.strip()
                    )
                    for window in windows:
                        topology_signatures.add(
                            "|".join(
                                (
                                    str(window.pid),
                                    window.class_name,
                                    window.title,
                                    f"owner={window.owner_hwnd}",
                                    f"enabled={int(window.enabled)}",
                                )
                            )
                        )

                    legal_windows = [window for window in windows if window.legal_reason]
                    if legal_windows:
                        status = "legal_modal"
                        local_blocked_reason = legal_windows[0].legal_reason
                        local_blocked_titles.extend(
                            window.title for window in legal_windows
                        )
                        break

                    main_windows, unknown_windows = _acceptance_window_partition(
                        windows,
                        normalized_main_markers,
                    )
                    if unknown_windows:
                        status = "unknown_modal"
                        local_blocked_reason = (
                            "HEC-RAS displayed an unrecognized visible top-level "
                            "window during acceptance qualification. No control "
                            "was used."
                        )
                        local_blocked_titles.extend(
                            window.title for window in unknown_windows
                        )
                        break
                    if stable_main_seen and (
                        len(main_windows) != 1
                        or any(
                            not window.enabled
                            for window in windows
                            if window.owner_hwnd == 0
                        )
                    ):
                        status = "unknown_modal"
                        local_blocked_reason = (
                            "The HEC-RAS main-window state became ambiguous or "
                            "disabled after it stabilized. No control was used."
                        )
                        local_blocked_titles.extend(
                            window.title for window in windows
                        )
                        break

                    if len(main_windows) == 1:
                        window = main_windows[0]
                        topology = tuple(
                            "|".join(
                                (
                                    str(item.pid),
                                    item.class_name,
                                    item.title,
                                    str(item.owner_hwnd),
                                    str(int(item.enabled)),
                                )
                            )
                            for item in windows
                        )
                        signature = (
                            window.class_name,
                            window.title,
                            str(window.owner_hwnd),
                            str(int(window.enabled)),
                            *topology,
                        )
                        if stable_main_seen and signature != qualifying_signature:
                            status = "unknown_modal"
                            local_blocked_reason = (
                                "Visible HEC-RAS window topology changed after "
                                "the main window stabilized. No control was used."
                            )
                            local_blocked_titles.extend(
                                item.title for item in windows
                            )
                            break
                        if signature != qualifying_signature:
                            qualifying_signature = signature
                            qualifying_since = time.monotonic()
                            current_main_stable = False
                        elif (
                            qualifying_since is not None
                            and time.monotonic() - qualifying_since >= ready_seconds
                        ):
                            stable_main_seen = True
                            current_main_stable = True
                            main_window_signature = (
                                window.class_name,
                                window.title,
                                str(window.owner_hwnd),
                                str(int(window.enabled)),
                            )
                    else:
                        qualifying_since = None
                        qualifying_signature = None
                        current_main_stable = False
                else:
                    qualifying_since = None
                    qualifying_signature = None
                    current_main_stable = False
                time.sleep(0.05)

            if watchdog.supervision_error:
                status = "supervision_failed"
            elif watchdog.blocked:
                first_reason = watchdog.blocked[0].reason
                status = (
                    "legal_modal"
                    if legal_dialog_blocking_reason(
                        title=watchdog.blocked[0].title,
                        body=watchdog.blocked[0].body,
                    )
                    else "unknown_modal"
                )
                if not first_reason:
                    status = "unknown_modal"
            elif status in {"legal_modal", "unknown_modal", "supervision_failed"}:
                pass
            elif process.poll() is not None:
                status = "launch_failed"
            elif current_main_stable:
                # Qualification intentionally observes the complete interval.
                # An exact, unowned, enabled main-window topology must remain
                # stable while modal supervision is active for the whole
                # interval. An early splash is never sufficient.
                status = "ready"
            else:
                status = "timeout"
        finally:
            # Stop/join the background monitor, then perform one final
            # synchronous scan before terminating the process tree. Status is
            # re-evaluated below so a late modal or scan failure cannot coexist
            # with a successful receipt.
            watchdog.stop()
            if process is not None:
                try:
                    observed_pids.update(watchdog.scoped_pids())
                    watchdog.scan_once()
                except Exception as exc:
                    local_supervision_error = (
                        "Acceptance probe final window inspection failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
                termination_verified = watchdog.terminate_process_tree(process.pid)

        survivors: Tuple[int, ...] = ()
        if observed_pids and psutil is not None:
            remaining: List[int] = []
            for pid in sorted(observed_pids):
                try:
                    if psutil.pid_exists(pid):
                        remaining.append(pid)
                except Exception:
                    remaining.append(pid)
            survivors = tuple(remaining)

        blocked = watchdog.blocked
        if blocked:
            status = (
                "legal_modal"
                if legal_dialog_blocking_reason(
                    title=blocked[0].title,
                    body=blocked[0].body,
                )
                else "unknown_modal"
            )
        elif local_supervision_error or watchdog.supervision_error:
            status = "supervision_failed"
        if not termination_verified or survivors:
            status = "termination_failed"

        blocked_reason = (
            (watchdog.blocked_reason or local_blocked_reason)
            if blocked
            else (
                local_supervision_error
                or watchdog.supervision_error
                or local_blocked_reason
            )
        )
        blocked_titles = tuple(
            dict.fromkeys(
                [*local_blocked_titles, *(record.title for record in blocked)]
            )
        )
        return AcceptanceProbeResult(
            identity=identity,
            status=status,
            started=started,
            visible_window_seen=visible_seen,
            visible_titles=tuple(sorted(visible_titles)),
            blocked_reason=blocked_reason,
            blocked_titles=blocked_titles,
            interactions=len(watchdog.dismissed),
            process_tree_terminated=termination_verified,
            survivors=survivors,
            elapsed_seconds=time.monotonic() - started_at,
            observed_at_utc=_utc_now(),
            main_window_signature=main_window_signature,
            topology_signatures=tuple(sorted(topology_signatures)),
            observed_process_ids=tuple(sorted(observed_pids)),
        )

    @staticmethod
    @log_call
    def run_user_driven_acceptance(
        ras_executable: str | Path,
        *,
        expected_version: str,
        source_evidence_sha256: str,
        destination_is_disposable: bool,
        authorization_reference: str,
        profile_instance_token: str,
        beta_authorization_reference: Optional[str] = None,
        session_timeout_seconds: float = 600.0,
        legal_observation_seconds: float = 0.25,
        main_ready_seconds: float = 2.0,
        restart_timeout_seconds: float = 15.0,
        restart_ready_seconds: float = 2.0,
        poll_interval_seconds: float = 0.05,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> UserDrivenAcceptanceReceipt:
        """Supervise one normal, out-of-band human TCU acceptance session.

        The API launches HEC-RAS and observes its process-scoped windows, but
        sends no window messages, mouse events, or keyboard events. It first
        requires a stable live HEC-RAS Terms and Conditions for Use dialog,
        emits ``AWAITING_USER`` through the optional notification callback,
        and waits for a human to complete the dialog normally. The resulting
        exact main window must stabilize before the process tree is terminated
        and two ordinary full-duration :meth:`probe` restarts are verified.

        Authorization references, the legal-dialog body, and the caller's
        profile-instance token are retained only as domain-separated SHA-256
        hashes. This method never reads or returns the opaque registry value.
        A beta installation requires a distinct, explicit beta authorization.
        """
        if not isinstance(expected_version, str) or not expected_version.strip():
            raise ValueError("expected_version must be a nonempty exact release label")
        expected_version = expected_version.strip()
        if not isinstance(source_evidence_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}",
            source_evidence_sha256,
        ):
            raise ValueError(
                "source_evidence_sha256 must be exactly 64 lowercase hexadecimal "
                "characters"
            )
        if destination_is_disposable is not True:
            raise ValueError(
                "User-driven acceptance is limited to an explicitly disposable "
                "profile destination"
            )
        authorization_hash = _opaque_token_sha256(
            "authorization-reference",
            authorization_reference,
        )
        profile_instance_hash = _opaque_token_sha256(
            "profile-instance-token",
            profile_instance_token,
        )

        numeric_parameters = {
            "session_timeout_seconds": session_timeout_seconds,
            "legal_observation_seconds": legal_observation_seconds,
            "main_ready_seconds": main_ready_seconds,
            "restart_timeout_seconds": restart_timeout_seconds,
            "restart_ready_seconds": restart_ready_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        }
        if any(value <= 0 for value in numeric_parameters.values()):
            raise ValueError("All user-acceptance timing values must be positive")
        if session_timeout_seconds < legal_observation_seconds + main_ready_seconds:
            raise ValueError(
                "session_timeout_seconds is too short for dialog and main-window "
                "stability intervals"
            )
        if restart_timeout_seconds < restart_ready_seconds:
            raise ValueError(
                "restart_timeout_seconds must be at least restart_ready_seconds"
            )

        identity = RasAcceptanceState.executable_identity(
            ras_executable,
            expected_version=expected_version,
            verify_executable_version=True,
        )
        install_label = PureWindowsPath(identity.path).parent.name
        expected_is_beta = "beta" in expected_version.casefold()
        install_is_beta = "beta" in install_label.casefold()
        if install_is_beta and not expected_is_beta:
            raise ValueError(
                "A beta installation requires its exact beta label in "
                "expected_version"
            )
        beta_authorization_hash: Optional[str] = None
        if expected_is_beta or install_is_beta:
            if (
                not isinstance(beta_authorization_reference, str)
                or not beta_authorization_reference.strip()
            ):
                raise ValueError(
                    "A nonempty beta authorization reference is required"
                )
            if beta_authorization_reference.strip() == authorization_reference.strip():
                raise ValueError(
                    "Beta acceptance requires a distinct beta authorization reference"
                )
            beta_authorization_hash = _opaque_token_sha256(
                "beta-authorization-reference",
                beta_authorization_reference,
            )

        normalized_main_markers = ("hec-ras", "river analysis system")
        session_lock_key = "|".join(
            (
                "user-driven-acceptance-v1",
                identity.path.casefold(),
                identity.sha256,
                profile_instance_hash,
            )
        )
        lock = RasAcceptanceState._lock_for(session_lock_key)

        with lock, _cross_process_lock(session_lock_key):
            if RasAcceptanceState._target_running(identity):
                raise RuntimeError(
                    "Refusing user-driven acceptance while the target is already "
                    f"running: {identity.path}"
                )

            watchdog = DialogWatchdog(poll_interval=poll_interval_seconds)
            watchdog.require_available()
            if psutil is None:
                raise RuntimeError(
                    "psutil is required for verified user-session termination"
                )

            started_at = time.monotonic()
            process: Optional[subprocess.Popen] = None
            observed_pids: set[int] = set()
            legal_candidate: Optional[Tuple[str, ...]] = None
            legal_candidate_since: Optional[float] = None
            legal_dialog_signature: Tuple[str, ...] = ()
            legal_dialog_body_sha256 = ""
            legal_observed = False
            notification_emitted = False
            main_candidate: Optional[Tuple[str, ...]] = None
            main_candidate_since: Optional[float] = None
            main_window_signature: Tuple[str, ...] = ()
            completed_main_topology: Optional[Tuple[str, ...]] = None
            process_tree_terminated = False
            survivors: Tuple[int, ...] = ()
            session_error: Optional[BaseException] = None

            try:
                process = subprocess.Popen(
                    [identity.path],
                    cwd=str(Path(identity.path).parent),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
                observed_pids.add(process.pid)
                watchdog.add_pid(process.pid)
                deadline = time.monotonic() + session_timeout_seconds

                while time.monotonic() < deadline:
                    if watchdog.supervision_error:
                        raise RuntimeError(
                            "User-acceptance window supervision failed: "
                            f"{watchdog.supervision_error}"
                        )
                    if watchdog.blocked or watchdog.dismissed:
                        raise RuntimeError(
                            "User-acceptance supervision recorded an unexpected "
                            "dialog action"
                        )
                    if process.poll() is not None:
                        raise RuntimeError(
                            "HEC-RAS exited before the user-acceptance session "
                            "reached a stable main window"
                        )
                    try:
                        observed_pids.update(watchdog.scoped_pids())
                        windows = watchdog.observe_windows()
                    except Exception as exc:
                        raise RuntimeError(
                            "User-acceptance window inspection failed"
                        ) from exc

                    actual_tcu = tuple(
                        window
                        for window in windows
                        if _is_actual_hecras_tcu_window(window)
                    )
                    other_legal = tuple(
                        window
                        for window in windows
                        if window.legal_reason
                        and not _is_actual_hecras_tcu_window(window)
                    )
                    if other_legal:
                        raise RuntimeError(
                            "A legal dialog was visible but did not match the "
                            "required HEC-RAS TCU contract"
                        )
                    if len(actual_tcu) > 1:
                        raise RuntimeError(
                            "Multiple HEC-RAS TCU windows made the session ambiguous"
                        )

                    if actual_tcu:
                        tcu = actual_tcu[0]
                        unknown_alongside_tcu = tuple(
                            window
                            for window in windows
                            if window.hwnd != tcu.hwnd
                            and not _is_acceptance_main_shell(
                                window,
                                normalized_main_markers,
                            )
                            and not _is_tcu_phase_companion_window(window)
                            and not _is_acceptance_companion_window(window)
                        )
                        if unknown_alongside_tcu:
                            raise RuntimeError(
                                "An unrecognized visible window appeared alongside "
                                "the HEC-RAS TCU dialog; sanitized signatures="
                                f"{_sanitized_window_signatures(unknown_alongside_tcu)!r}"
                            )
                        body_hash = _opaque_token_sha256(
                            "legal-dialog-body",
                            tcu.body,
                            strip=False,
                        )
                        candidate = (*_observed_window_signature(tcu), body_hash)
                        if legal_observed:
                            if candidate != (*legal_dialog_signature, legal_dialog_body_sha256):
                                raise RuntimeError(
                                    "The observed HEC-RAS TCU contract changed before "
                                    "human completion"
                                )
                        elif candidate != legal_candidate:
                            legal_candidate = candidate
                            legal_candidate_since = time.monotonic()
                        elif (
                            legal_candidate_since is not None
                            and time.monotonic() - legal_candidate_since
                            >= legal_observation_seconds
                        ):
                            legal_dialog_signature = _observed_window_signature(tcu)
                            legal_dialog_body_sha256 = body_hash
                            legal_observed = True
                            if status_callback is not None and not notification_emitted:
                                status_callback("AWAITING_USER")
                            notification_emitted = True
                            logger.info(
                                "Verified the live HEC-RAS TCU dialog; waiting for "
                                "out-of-band human completion"
                            )
                        main_candidate = None
                        main_candidate_since = None
                        time.sleep(poll_interval_seconds)
                        continue

                    if not legal_observed:
                        enabled_main_windows = tuple(
                            window
                            for window in windows
                            if _is_acceptance_main_window(
                                window,
                                normalized_main_markers,
                            )
                        )
                        unknown_before_tcu = tuple(
                            window
                            for window in windows
                            if not _is_acceptance_companion_window(window)
                            and not _is_acceptance_main_shell(
                                window,
                                normalized_main_markers,
                            )
                        )
                        if unknown_before_tcu:
                            raise RuntimeError(
                                "An unrecognized visible window appeared before the "
                                "required HEC-RAS TCU dialog; sanitized signatures="
                                f"{_sanitized_window_signatures(unknown_before_tcu)!r}"
                            )
                        if len(enabled_main_windows) > 1:
                            raise RuntimeError(
                                "Multiple HEC-RAS main windows appeared before the "
                                "required live TCU dialog"
                            )
                        if len(enabled_main_windows) == 1:
                            window = enabled_main_windows[0]
                            topology = tuple(
                                "|".join(
                                    (
                                        str(item.pid),
                                        item.class_name,
                                        item.title,
                                        str(item.owner_hwnd),
                                        str(int(item.enabled)),
                                    )
                                )
                                for item in windows
                            )
                            candidate = (
                                *_observed_window_signature(window),
                                *topology,
                            )
                            if candidate != main_candidate:
                                main_candidate = candidate
                                main_candidate_since = time.monotonic()
                            elif (
                                main_candidate_since is not None
                                and time.monotonic() - main_candidate_since
                                >= main_ready_seconds
                            ):
                                raise RuntimeError(
                                    "HEC-RAS reached a stable main window before the "
                                    "required live TCU dialog was observed"
                                )
                        else:
                            main_candidate = None
                            main_candidate_since = None
                        legal_candidate = None
                        legal_candidate_since = None
                        time.sleep(poll_interval_seconds)
                        continue

                    main_windows, unknown_windows = _acceptance_window_partition(
                        windows,
                        normalized_main_markers,
                    )
                    unknown_windows = tuple(
                        window
                        for window in unknown_windows
                        if not (
                            _is_acceptance_main_shell(
                                window,
                                normalized_main_markers,
                            )
                            and not window.enabled
                        )
                    )
                    if unknown_windows:
                        raise RuntimeError(
                            "An unrecognized visible window appeared after human "
                            "TCU completion; sanitized signatures="
                            f"{_sanitized_window_signatures(unknown_windows)!r}"
                        )
                    if len(main_windows) > 1:
                        raise RuntimeError(
                            "Multiple HEC-RAS main windows made the session ambiguous"
                        )
                    if len(main_windows) == 1:
                        window = main_windows[0]
                        topology = tuple(
                            "|".join(
                                (
                                    str(item.pid),
                                    item.class_name,
                                    item.title,
                                    str(item.owner_hwnd),
                                    str(int(item.enabled)),
                                )
                            )
                            for item in windows
                        )
                        candidate = (*_observed_window_signature(window), *topology)
                        if candidate != main_candidate:
                            main_candidate = candidate
                            main_candidate_since = time.monotonic()
                        elif (
                            main_candidate_since is not None
                            and time.monotonic() - main_candidate_since
                            >= main_ready_seconds
                        ):
                            main_window_signature = _observed_window_signature(window)
                            completed_main_topology = candidate
                            break
                    else:
                        main_candidate = None
                        main_candidate_since = None
                    time.sleep(poll_interval_seconds)
                else:
                    phase = (
                        "human completion and stable main window"
                        if legal_observed
                        else "initial HEC-RAS TCU observation"
                    )
                    raise TimeoutError(
                        f"Timed out waiting for {phase}"
                    )

                if process.poll() is not None:
                    raise RuntimeError(
                        "HEC-RAS exited before final main-window verification"
                    )
                try:
                    observed_pids.update(watchdog.scoped_pids())
                    final_windows = watchdog.observe_windows()
                except Exception as exc:
                    raise RuntimeError(
                        "Final user-acceptance window inspection failed"
                    ) from exc
                final_main, final_unknown = _acceptance_window_partition(
                    final_windows,
                    normalized_main_markers,
                )
                if len(final_main) != 1 or final_unknown:
                    raise RuntimeError(
                        "The exact HEC-RAS main window did not survive final "
                        "verification; sanitized signatures="
                        f"{_sanitized_window_signatures(final_windows)!r}"
                    )
                final_topology = (
                    *_observed_window_signature(final_main[0]),
                    *tuple(
                        "|".join(
                            (
                                str(item.pid),
                                item.class_name,
                                item.title,
                                str(item.owner_hwnd),
                                str(int(item.enabled)),
                            )
                        )
                        for item in final_windows
                    ),
                )
                if final_topology != completed_main_topology:
                    raise RuntimeError(
                        "The HEC-RAS main-window topology changed during final "
                        "verification"
                    )
            except BaseException as exc:
                session_error = exc
            finally:
                if process is not None:
                    try:
                        observed_pids.update(watchdog.scoped_pids())
                    except Exception as exc:
                        session_error = session_error or RuntimeError(
                            "Final process-tree enumeration failed"
                        )
                        if session_error.__cause__ is None:
                            session_error.__cause__ = exc
                    try:
                        process_tree_terminated = watchdog.terminate_process_tree(
                            process.pid
                        )
                    except Exception as exc:
                        process_tree_terminated = False
                        session_error = session_error or RuntimeError(
                            "User-acceptance process-tree termination failed"
                        )
                        if session_error.__cause__ is None:
                            session_error.__cause__ = exc

            if process is not None:
                remaining: List[int] = []
                for pid in sorted(observed_pids):
                    try:
                        if psutil.pid_exists(pid):
                            remaining.append(pid)
                    except Exception:
                        remaining.append(pid)
                survivors = tuple(remaining)
                if not process_tree_terminated or survivors:
                    raise RuntimeError(
                        "User-acceptance process-tree termination could not be "
                        "verified"
                    ) from session_error
            if session_error is not None:
                raise session_error.with_traceback(session_error.__traceback__)
            if not legal_observed or not legal_dialog_signature:
                raise RuntimeError(
                    "The required live HEC-RAS TCU dialog was not observed"
                )
            if not main_window_signature:
                raise RuntimeError(
                    "The exact HEC-RAS main window was not verified"
                )
            if watchdog.dismissed or watchdog.blocked or watchdog.supervision_error:
                raise RuntimeError(
                    "User-acceptance supervision did not remain zero-interaction"
                )

            restart_probes: List[AcceptanceProbeResult] = []
            for restart_number in (1, 2):
                try:
                    restart = RasAcceptanceState.probe(
                        identity.path,
                        expected_version=identity.version,
                        timeout_seconds=restart_timeout_seconds,
                        ready_seconds=restart_ready_seconds,
                        verify_executable_version=True,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"HEC-RAS verification restart {restart_number} failed"
                    ) from exc
                restart_probes.append(restart)
                if not _strict_restart_probe_verified(
                    restart,
                    identity,
                    timeout_seconds=restart_timeout_seconds,
                    title_markers=normalized_main_markers,
                ):
                    raise RuntimeError(
                        f"HEC-RAS verification restart {restart_number} did not "
                        "produce strict full-duration zero-interaction evidence"
                    )

            created_at = _utc_now()
            receipt_payload = {
                "target": asdict(identity),
                "status": "accepted_and_restarts_verified",
                "destination_is_disposable": destination_is_disposable,
                "source_evidence_sha256": source_evidence_sha256,
                "authorization_reference_sha256": authorization_hash,
                "beta_authorization_reference_sha256": beta_authorization_hash,
                "profile_instance_token_sha256": profile_instance_hash,
                "legal_dialog_body_sha256": legal_dialog_body_sha256,
                "legal_dialog_signature": legal_dialog_signature,
                "main_window_signature": main_window_signature,
                "observed_process_ids": tuple(sorted(observed_pids)),
                "process_tree_terminated": process_tree_terminated,
                "survivors": survivors,
                "automated_ui_interactions": 0,
                "initial_session_elapsed_seconds": time.monotonic() - started_at,
                "restart_timeout_seconds": restart_timeout_seconds,
                "restart_ready_seconds": restart_ready_seconds,
                "restart_probes": tuple(asdict(item) for item in restart_probes),
                "created_at_utc": created_at,
            }
            return UserDrivenAcceptanceReceipt(
                target=identity,
                status="accepted_and_restarts_verified",
                destination_is_disposable=destination_is_disposable,
                source_evidence_sha256=source_evidence_sha256,
                authorization_reference_sha256=authorization_hash,
                beta_authorization_reference_sha256=beta_authorization_hash,
                profile_instance_token_sha256=profile_instance_hash,
                legal_dialog_body_sha256=legal_dialog_body_sha256,
                legal_dialog_signature=legal_dialog_signature,
                main_window_signature=main_window_signature,
                observed_process_ids=tuple(sorted(observed_pids)),
                process_tree_terminated=process_tree_terminated,
                survivors=survivors,
                automated_ui_interactions=0,
                initial_session_elapsed_seconds=receipt_payload[
                    "initial_session_elapsed_seconds"
                ],
                restart_timeout_seconds=restart_timeout_seconds,
                restart_ready_seconds=restart_ready_seconds,
                restart_probes=tuple(restart_probes),
                created_at_utc=created_at,
                fingerprint=_fingerprint(receipt_payload),
            )

    @staticmethod
    @log_call
    def run_authorized_legacy_ui_transfer(
        ras_executable: str | Path,
        *,
        expected_version: str,
        source_bundle: AcceptanceStateBundle,
        source_bundle_file_sha256: str,
        destination_is_disposable: bool,
        authorization_reference: str,
        profile_instance_token: str,
        session_timeout_seconds: float = 60.0,
        legal_observation_seconds: float = 0.5,
        control_transition_timeout_seconds: float = 5.0,
        main_ready_seconds: float = 3.0,
        restart_timeout_seconds: float = 45.0,
        restart_ready_seconds: float = 20.0,
        poll_interval_seconds: float = 0.05,
    ) -> AuthorizedLegacyUiTransferReceipt:
        """Apply the exact two-click authorized legacy VB6 TCU fallback.

        The method is limited to stable HEC-RAS 4.0, 4.1.0, 5.0.3, 5.0.6,
        5.0.7, and 6.0. It accepts only a pinned private source bundle whose
        accepted source and zero-input TCU contract were verified against the
        same exact executable hash. Before sending input, the target dialog
        must match that normalized source signature and the complete known
        semantic VB6 control contract. Hidden, disabled adapter extras are
        separately pinned in source/target full-tree hashes. Any preflight
        ambiguity or mismatch sends zero input and terminates the owned process
        tree.

        The only input messages are ``BM_CLICK`` to the exact Agree option and,
        after Next becomes enabled, ``BM_CLICK`` to the exact Next button. The
        method then verifies termination, requires a 45-second target-quiet
        interval before each of two independent full-duration restart probes,
        and returns a hash-only receipt.
        """
        if expected_version not in _AUTHORIZED_LEGACY_UI_VERSIONS:
            raise ValueError(
                "Authorized legacy UI transfer is limited to exact stable builds "
                "4.0, 4.1.0, 5.0.3, 5.0.6, 5.0.7, and 6.0"
            )
        if destination_is_disposable is not True:
            raise ValueError(
                "Authorized legacy UI transfer requires a disposable destination"
            )
        if not _is_sha256(source_bundle_file_sha256):
            raise ValueError(
                "source_bundle_file_sha256 must be 64 lowercase hexadecimal characters"
            )
        authorization_hash = _opaque_token_sha256(
            "authorization-reference",
            authorization_reference,
        )
        profile_instance_hash = _opaque_token_sha256(
            "profile-instance-token",
            profile_instance_token,
        )
        numeric = {
            "session_timeout_seconds": session_timeout_seconds,
            "legal_observation_seconds": legal_observation_seconds,
            "control_transition_timeout_seconds": (
                control_transition_timeout_seconds
            ),
            "main_ready_seconds": main_ready_seconds,
            "restart_timeout_seconds": restart_timeout_seconds,
            "restart_ready_seconds": restart_ready_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        }
        if any(value <= 0 for value in numeric.values()):
            raise ValueError("All authorized UI transfer timing values must be positive")
        if restart_timeout_seconds < 45.0:
            raise ValueError("Authorized UI restart probes must run at least 45 seconds")
        if restart_timeout_seconds < restart_ready_seconds:
            raise ValueError(
                "restart_timeout_seconds must be at least restart_ready_seconds"
            )
        if session_timeout_seconds < (
            legal_observation_seconds
            + control_transition_timeout_seconds
            + main_ready_seconds
        ):
            raise ValueError("session_timeout_seconds is too short for UI verification")
        if not isinstance(source_bundle, AcceptanceStateBundle):
            raise ValueError("source_bundle must be an AcceptanceStateBundle")

        evidence = source_bundle.legacy_tcu_contract
        if evidence is None or not evidence.passed:
            raise ValueError(
                "source_bundle lacks passed hash-only legacy TCU contract evidence"
            )
        expected_bundle_fingerprint = _fingerprint(
            _bundle_fingerprint_payload(
                source_bundle.identity,
                source_bundle.state,
                source_bundle.source_probe,
                evidence,
            )
        )
        if source_bundle.fingerprint != expected_bundle_fingerprint:
            raise ValueError("source_bundle fingerprint does not match its content")
        if _private_bundle_file_sha256(source_bundle) != source_bundle_file_sha256:
            raise ValueError("Pinned source-bundle file hash does not match")
        if (
            evidence.target != source_bundle.identity
            or evidence.final_source_probe_sha256
            != _fingerprint(asdict(source_bundle.source_probe))
            or evidence.fingerprint
            != _fingerprint(
                {
                    key: value
                    for key, value in asdict(evidence).items()
                    if key != "fingerprint"
                }
            )
        ):
            raise ValueError("source_bundle contract evidence is not internally bound")
        if (
            not source_bundle.no_modal_verified
            or source_bundle.source_probe is None
            or source_bundle.source_probe.identity != source_bundle.identity
            or source_bundle.source_probe.elapsed_seconds < 20.0
            or not source_bundle.state.exists
            or source_bundle.state.value is None
            or not source_bundle.state.value
            or source_bundle.state.registry_type is None
        ):
            raise ValueError("source_bundle lacks a safe captured_verified source")

        identity = RasAcceptanceState.executable_identity(
            ras_executable,
            expected_version=expected_version,
            verify_executable_version=True,
        )
        if (
            source_bundle.identity.version != expected_version
            or evidence.target.version != expected_version
            or source_bundle.identity.sha256 != identity.sha256
            or evidence.target.sha256 != identity.sha256
        ):
            raise ValueError(
                "Source and destination must have the same exact version and executable hash"
            )
        if (
            source_bundle.identity.architecture
            and identity.architecture
            and source_bundle.identity.architecture != identity.architecture
        ):
            raise ValueError("Source and destination executable architectures differ")
        if win32gui is None:
            raise RuntimeError("Authorized legacy UI transfer requires pywin32")

        title_markers = ("hec-ras", "river analysis system")
        session_lock_key = "|".join(
            (
                "authorized-legacy-ui-transfer-v1",
                identity.path.casefold(),
                identity.sha256,
                profile_instance_hash,
            )
        )
        lock = RasAcceptanceState._lock_for(session_lock_key)
        with lock, _cross_process_lock(session_lock_key):
            if RasAcceptanceState._target_running(identity):
                raise RuntimeError("Refusing UI transfer while target is running")
            watchdog = DialogWatchdog(poll_interval=poll_interval_seconds)
            watchdog.require_available()
            if psutil is None:
                raise RuntimeError("psutil is required for verified UI transfer")

            started_at = time.monotonic()
            process: Optional[subprocess.Popen] = None
            observed_pids: set[int] = set()
            preflight_candidate: Optional[Tuple[str, ...]] = None
            preflight_since: Optional[float] = None
            initial_handles: Optional[Dict[str, int]] = None
            target_body_hash = ""
            target_control_hash = ""
            target_adapter_hash = ""
            target_full_tree_hash = ""
            target_modal_hash = ""
            interactions = 0
            main_candidate: Optional[Tuple[str, ...]] = None
            main_candidate_since: Optional[float] = None
            main_window_signature: Tuple[str, ...] = ()
            completed_main_topology: Optional[Tuple[str, ...]] = None
            process_tree_terminated = False
            survivors: Tuple[int, ...] = ()
            session_error: Optional[BaseException] = None

            try:
                process = subprocess.Popen(
                    [identity.path],
                    cwd=str(Path(identity.path).parent),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
                observed_pids.add(process.pid)
                watchdog.add_pid(process.pid)
                deadline = time.monotonic() + session_timeout_seconds

                while time.monotonic() < deadline and interactions == 0:
                    if process.poll() is not None:
                        raise RuntimeError("HEC-RAS exited before exact UI preflight")
                    if watchdog.supervision_error or watchdog.blocked or watchdog.dismissed:
                        raise RuntimeError("UI preflight lost zero-input supervision")
                    observed_pids.update(watchdog.scoped_pids())
                    windows = watchdog.observe_windows()
                    legal_windows = tuple(
                        window for window in windows if window.legal_reason
                    )
                    if len(legal_windows) != 1:
                        if len(legal_windows) > 1:
                            raise RuntimeError("Multiple legal windows made UI preflight ambiguous")
                        unknown = tuple(
                            window
                            for window in windows
                            if not _is_acceptance_main_shell(window, title_markers)
                            and not _is_acceptance_companion_window(window)
                        )
                        if unknown:
                            raise RuntimeError(
                                "Unknown window before UI preflight; signatures="
                                f"{_sanitized_window_signatures(unknown)!r}"
                            )
                        preflight_candidate = None
                        preflight_since = None
                        time.sleep(poll_interval_seconds)
                        continue

                    tcu = legal_windows[0]
                    unknown_alongside = tuple(
                        window
                        for window in windows
                        if window.hwnd != tcu.hwnd
                        and not _is_acceptance_main_shell(window, title_markers)
                        and not _is_tcu_phase_companion_window(window)
                        and not _is_acceptance_companion_window(window)
                    )
                    if unknown_alongside:
                        raise RuntimeError(
                            "Unknown window alongside UI preflight; signatures="
                            f"{_sanitized_window_signatures(unknown_alongside)!r}"
                        )
                    (
                        controls,
                        control_hash,
                        adapter_hash,
                        full_tree_hash,
                        body_hash,
                    ) = _inspect_legacy_tcu_contract(
                        tcu,
                        expected_next_enabled=False,
                    )
                    top_hash = _fingerprint(
                        {
                            "class_name": tcu.class_name,
                            "title": tcu.title,
                            "owner_present": bool(tcu.owner_hwnd),
                            "enabled": tcu.enabled,
                        }
                    )
                    modal_hash = _fingerprint(
                        {
                            "top_signature_sha256": top_hash,
                            "legal_dialog_body_sha256": body_hash,
                            "control_contract_sha256": control_hash,
                        }
                    )
                    if (
                        top_hash != evidence.top_signature_sha256
                        or body_hash != evidence.legal_dialog_body_sha256
                        or control_hash != evidence.control_contract_sha256
                        or modal_hash != evidence.normalized_modal_signature_sha256
                    ):
                        raise RuntimeError(
                            "Target legacy TCU did not match pinned exact-source evidence"
                        )
                    handles = {role: control.hwnd for role, control in controls.items()}
                    current = (
                        top_hash,
                        body_hash,
                        control_hash,
                        adapter_hash,
                        full_tree_hash,
                        modal_hash,
                        *(
                            f"{role}:{hwnd}"
                            for role, hwnd in sorted(handles.items())
                        ),
                    )
                    if current != preflight_candidate:
                        preflight_candidate = current
                        preflight_since = time.monotonic()
                    elif (
                        preflight_since is not None
                        and time.monotonic() - preflight_since
                        >= legal_observation_seconds
                    ):
                        initial_handles = handles
                        target_body_hash = body_hash
                        target_control_hash = control_hash
                        target_adapter_hash = adapter_hash
                        target_full_tree_hash = full_tree_hash
                        target_modal_hash = modal_hash
                        win32gui.SendMessage(
                            controls["agree"].hwnd,
                            _BM_CLICK,
                            0,
                            0,
                        )
                        interactions = 1
                        break
                    time.sleep(poll_interval_seconds)
                if interactions != 1 or initial_handles is None:
                    raise TimeoutError("Timed out before authorized Agree input")

                transition_deadline = time.monotonic() + control_transition_timeout_seconds
                next_control: Optional[_LegacyTcuControl] = None
                while time.monotonic() < transition_deadline:
                    if process.poll() is not None:
                        raise RuntimeError("HEC-RAS exited after authorized Agree input")
                    windows = watchdog.observe_windows()
                    legal_windows = tuple(
                        window for window in windows if window.legal_reason
                    )
                    if len(legal_windows) != 1:
                        raise RuntimeError(
                            "The exact TCU disappeared or became ambiguous after Agree"
                        )
                    unknown_after_agree = tuple(
                        window
                        for window in windows
                        if window.hwnd != legal_windows[0].hwnd
                        and not _is_acceptance_main_shell(window, title_markers)
                        and not _is_tcu_phase_companion_window(window)
                        and not _is_acceptance_companion_window(window)
                    )
                    if unknown_after_agree:
                        raise RuntimeError(
                            "Unknown window appeared after Agree; signatures="
                            f"{_sanitized_window_signatures(unknown_after_agree)!r}"
                        )
                    (
                        controls,
                        _post_hash,
                        post_adapter_hash,
                        _post_full_tree_hash,
                        _post_body,
                    ) = _inspect_legacy_tcu_contract(
                        legal_windows[0],
                        expected_next_enabled=None,
                        expected_hwnds=initial_handles,
                    )
                    if post_adapter_hash != target_adapter_hash:
                        raise RuntimeError(
                            "The target adapter control set changed after Agree"
                        )
                    next_control = controls["next"]
                    if next_control.enabled:
                        agree_state = controls["agree"].check_state
                        disagree_state = controls["disagree"].check_state
                        if (agree_state, disagree_state) != (1, 0):
                            raise RuntimeError(
                                "Agree selection could not be verified exactly"
                            )
                        break
                    time.sleep(poll_interval_seconds)
                else:
                    raise TimeoutError("Next did not become enabled after exact Agree")
                if next_control is None or not next_control.enabled:
                    raise RuntimeError("Exact Next control was not enabled")

                final_windows = watchdog.observe_windows()
                final_legal = tuple(
                    window for window in final_windows if window.legal_reason
                )
                if len(final_legal) != 1:
                    raise RuntimeError("Exact TCU was not stable before Next input")
                unknown_before_next = tuple(
                    window
                    for window in final_windows
                    if window.hwnd != final_legal[0].hwnd
                    and not _is_acceptance_main_shell(window, title_markers)
                    and not _is_tcu_phase_companion_window(window)
                    and not _is_acceptance_companion_window(window)
                )
                if unknown_before_next:
                    raise RuntimeError(
                        "Unknown window appeared before Next; signatures="
                        f"{_sanitized_window_signatures(unknown_before_next)!r}"
                    )
                (
                    final_controls,
                    _final_hash,
                    final_adapter_hash,
                    _final_full_tree_hash,
                    _final_body,
                ) = (
                    _inspect_legacy_tcu_contract(
                        final_legal[0],
                        expected_next_enabled=True,
                        expected_hwnds=initial_handles,
                    )
                )
                if final_adapter_hash != target_adapter_hash:
                    raise RuntimeError(
                        "The target adapter control set changed before Next"
                    )
                win32gui.SendMessage(
                    final_controls["next"].hwnd,
                    _BM_CLICK,
                    0,
                    0,
                )
                interactions = 2

                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("HEC-RAS exited before stable main window")
                    observed_pids.update(watchdog.scoped_pids())
                    windows = watchdog.observe_windows()
                    if any(window.legal_reason for window in windows):
                        raise RuntimeError("A legal dialog remained after exact Next")
                    main_windows, unknown_windows = _acceptance_window_partition(
                        windows,
                        title_markers,
                    )
                    unknown_windows = tuple(
                        window
                        for window in unknown_windows
                        if not (
                            _is_acceptance_main_shell(window, title_markers)
                            and not window.enabled
                        )
                    )
                    if unknown_windows:
                        raise RuntimeError(
                            "Unknown window after exact Next; signatures="
                            f"{_sanitized_window_signatures(unknown_windows)!r}"
                        )
                    if len(main_windows) > 1:
                        raise RuntimeError("Multiple HEC-RAS main windows appeared")
                    if len(main_windows) == 1:
                        main = main_windows[0]
                        topology = tuple(
                            "|".join(
                                (
                                    str(item.pid),
                                    item.class_name,
                                    item.title,
                                    str(item.owner_hwnd),
                                    str(int(item.enabled)),
                                )
                            )
                            for item in windows
                        )
                        current = (*_observed_window_signature(main), *topology)
                        if current != main_candidate:
                            main_candidate = current
                            main_candidate_since = time.monotonic()
                        elif (
                            main_candidate_since is not None
                            and time.monotonic() - main_candidate_since
                            >= main_ready_seconds
                        ):
                            main_window_signature = _observed_window_signature(main)
                            completed_main_topology = current
                            break
                    else:
                        main_candidate = None
                        main_candidate_since = None
                    time.sleep(poll_interval_seconds)
                else:
                    raise TimeoutError("Timed out waiting for stable main window")

                final_windows = watchdog.observe_windows()
                final_main, final_unknown = _acceptance_window_partition(
                    final_windows,
                    title_markers,
                )
                final_topology = (
                    *_observed_window_signature(final_main[0]),
                    *tuple(
                        "|".join(
                            (
                                str(item.pid),
                                item.class_name,
                                item.title,
                                str(item.owner_hwnd),
                                str(int(item.enabled)),
                            )
                        )
                        for item in final_windows
                    ),
                ) if len(final_main) == 1 and not final_unknown else ()
                if final_topology != completed_main_topology:
                    raise RuntimeError("Final main-window topology did not remain exact")
            except BaseException as exc:
                session_error = exc
            finally:
                if process is not None:
                    try:
                        observed_pids.update(watchdog.scoped_pids())
                    except Exception as exc:
                        session_error = session_error or RuntimeError(
                            "Final UI-transfer process enumeration failed"
                        )
                        if session_error.__cause__ is None:
                            session_error.__cause__ = exc
                    try:
                        process_tree_terminated = watchdog.terminate_process_tree(
                            process.pid
                        )
                    except Exception as exc:
                        process_tree_terminated = False
                        session_error = session_error or RuntimeError(
                            "UI-transfer process-tree termination failed"
                        )
                        if session_error.__cause__ is None:
                            session_error.__cause__ = exc

            remaining: List[int] = []
            for pid in sorted(observed_pids):
                try:
                    if psutil.pid_exists(pid):
                        remaining.append(pid)
                except Exception:
                    remaining.append(pid)
            survivors = tuple(remaining)
            if not process_tree_terminated or survivors:
                raise RuntimeError(
                    "UI-transfer process-tree termination could not be verified"
                ) from session_error
            if session_error is not None:
                raise session_error.with_traceback(session_error.__traceback__)
            if interactions != 2:
                raise RuntimeError("Authorized UI transfer did not send exactly two clicks")
            if not main_window_signature:
                raise RuntimeError("Exact HEC-RAS main window was not verified")
            if watchdog.dismissed or watchdog.blocked or watchdog.supervision_error:
                raise RuntimeError("Generic watchdog activity is forbidden in UI transfer")

            restart_probes: List[AcceptanceProbeResult] = []
            quiet_observations: List[float] = []
            for restart_number in (1, 2):
                quiet_observations.append(
                    _verify_target_quiet_period(
                        identity,
                        _LEGACY_PRE_RESTART_QUIET_SECONDS,
                        poll_interval_seconds=poll_interval_seconds,
                    )
                )
                restart = RasAcceptanceState.probe(
                    identity.path,
                    expected_version=identity.version,
                    timeout_seconds=restart_timeout_seconds,
                    ready_seconds=restart_ready_seconds,
                    verify_executable_version=True,
                )
                restart_probes.append(restart)
                if not _strict_restart_probe_verified(
                    restart,
                    identity,
                    timeout_seconds=restart_timeout_seconds,
                    title_markers=title_markers,
                ):
                    raise RuntimeError(
                        f"HEC-RAS verification restart {restart_number} did not "
                        "produce strict full-duration zero-interaction evidence"
                    )

            created_at = _utc_now()
            receipt_payload = {
                "target": asdict(identity),
                "status": "authorized_ui_transfer_and_restarts_verified",
                "destination_is_disposable": True,
                "source_bundle_file_sha256": source_bundle_file_sha256,
                "source_bundle_fingerprint": source_bundle.fingerprint,
                "source_modal_signature_sha256": (
                    evidence.normalized_modal_signature_sha256
                ),
                "target_modal_signature_sha256": target_modal_hash,
                "authorization_reference_sha256": authorization_hash,
                "profile_instance_token_sha256": profile_instance_hash,
                "legal_dialog_body_sha256": target_body_hash,
                "control_contract_sha256": target_control_hash,
                "source_adapter_contract_sha256": (
                    evidence.source_adapter_contract_sha256
                ),
                "target_adapter_contract_sha256": target_adapter_hash,
                "source_full_tree_contract_sha256": (
                    evidence.source_full_tree_contract_sha256
                ),
                "target_full_tree_contract_sha256": target_full_tree_hash,
                "main_window_signature": main_window_signature,
                "observed_process_ids": tuple(sorted(observed_pids)),
                "process_tree_terminated": process_tree_terminated,
                "survivors": survivors,
                "automated_ui_interactions": interactions,
                "initial_session_elapsed_seconds": time.monotonic() - started_at,
                "pre_restart_quiet_seconds": _LEGACY_PRE_RESTART_QUIET_SECONDS,
                "pre_restart_quiet_observations": tuple(quiet_observations),
                "restart_timeout_seconds": restart_timeout_seconds,
                "restart_ready_seconds": restart_ready_seconds,
                "restart_probes": tuple(asdict(item) for item in restart_probes),
                "created_at_utc": created_at,
            }
            return AuthorizedLegacyUiTransferReceipt(
                target=identity,
                status="authorized_ui_transfer_and_restarts_verified",
                destination_is_disposable=True,
                source_bundle_file_sha256=source_bundle_file_sha256,
                source_bundle_fingerprint=source_bundle.fingerprint,
                source_modal_signature_sha256=(
                    evidence.normalized_modal_signature_sha256
                ),
                target_modal_signature_sha256=target_modal_hash,
                authorization_reference_sha256=authorization_hash,
                profile_instance_token_sha256=profile_instance_hash,
                legal_dialog_body_sha256=target_body_hash,
                control_contract_sha256=target_control_hash,
                source_adapter_contract_sha256=(
                    evidence.source_adapter_contract_sha256
                ),
                target_adapter_contract_sha256=target_adapter_hash,
                source_full_tree_contract_sha256=(
                    evidence.source_full_tree_contract_sha256
                ),
                target_full_tree_contract_sha256=target_full_tree_hash,
                main_window_signature=main_window_signature,
                observed_process_ids=tuple(sorted(observed_pids)),
                process_tree_terminated=process_tree_terminated,
                survivors=survivors,
                automated_ui_interactions=interactions,
                initial_session_elapsed_seconds=receipt_payload[
                    "initial_session_elapsed_seconds"
                ],
                pre_restart_quiet_seconds=_LEGACY_PRE_RESTART_QUIET_SECONDS,
                pre_restart_quiet_observations=tuple(quiet_observations),
                restart_timeout_seconds=restart_timeout_seconds,
                restart_ready_seconds=restart_ready_seconds,
                restart_probes=tuple(restart_probes),
                created_at_utc=created_at,
                fingerprint=_fingerprint(receipt_payload),
            )

    @staticmethod
    def _lock_for(key: str) -> threading.RLock:
        with RasAcceptanceState._locks_guard:
            return RasAcceptanceState._locks.setdefault(
                key.casefold(), threading.RLock()
            )

    @staticmethod
    @contextmanager
    @log_call
    def temporary_system_statistic(
        ras_executable: str | Path,
        value,
        *,
        expected_version: Optional[str] = None,
        registry_type: Optional[int] = None,
        diagnostic_label: str,
        verify_executable_version: bool = True,
        replace_application_subtree: bool = False,
        registry=None,
    ) -> Iterator[Tuple[RegistryValueSnapshot, RegistryValueSnapshot]]:
        """Apply one diagnostic value (or remove it) and restore in ``finally``.

        ``value`` may be ``None`` to create a missing-state negative control.
        The method is deliberately labelled diagnostic and never persists the
        candidate after the context exits.
        """
        if not diagnostic_label.strip():
            raise ValueError("A non-empty diagnostic_label is required")
        identity = RasAcceptanceState.executable_identity(
            ras_executable,
            expected_version=expected_version,
            verify_executable_version=verify_executable_version,
        )
        if RasAcceptanceState._target_running(identity):
            raise RuntimeError("Refusing registry transaction while target is running")
        key = RasAcceptanceState.registry_subkey(
            identity.path,
            expected_version=identity.version,
        )
        application_root = _application_root(key)
        backend = registry or _WinRegistryBackend()
        lock = RasAcceptanceState._lock_for(key)
        with lock, _cross_process_lock(key):
            if RasAcceptanceState._target_running(identity):
                raise RuntimeError(
                    "Refusing registry transaction while target is running"
                )
            before = backend.snapshot(key)
            before_subtree = (
                backend.subtree_snapshot(application_root)
                if hasattr(backend, "subtree_snapshot")
                else None
            )
            created: List[str] = []
            try:
                if replace_application_subtree:
                    if before_subtree is None or not hasattr(
                        backend, "restore_subtree"
                    ):
                        raise RuntimeError(
                            "Registry backend cannot replace the application subtree"
                        )
                    backend.restore_subtree(application_root, {})
                if value is None:
                    backend.delete_value(key)
                else:
                    value_type = registry_type
                    if value_type is None:
                        if winreg is None:
                            raise RuntimeError("registry_type is required outside Windows")
                        value_type = winreg.REG_SZ
                    created = backend.set_value(key, str(value), int(value_type))
                applied = backend.snapshot(key)
                if value is None:
                    applied_matches = not applied.exists
                else:
                    applied_matches = (
                        applied.exists
                        and applied.value == str(value)
                        and applied.registry_type == int(value_type)
                    )
                if not applied_matches:
                    raise RuntimeError(
                        "Acceptance-state diagnostic write failed exact readback"
                    )
                yield before, applied
            finally:
                if before_subtree is not None and hasattr(backend, "restore_subtree"):
                    backend.restore_subtree(application_root, before_subtree)
                else:
                    backend.restore_value(before, created)
                restored = backend.snapshot(key)
                restored_subtree = (
                    backend.subtree_snapshot(application_root)
                    if before_subtree is not None
                    and hasattr(backend, "subtree_snapshot")
                    else None
                )
                if restored != before or restored_subtree != before_subtree:
                    raise RuntimeError(
                        "Acceptance-state diagnostic failed to restore the exact "
                        "original application registry subtree"
                    )

    @staticmethod
    @log_call
    def diagnose_candidate(
        ras_executable: str | Path,
        *,
        candidate_value: str,
        candidate_registry_type: Optional[int] = None,
        source_version: str,
        expected_version: str,
        permitted_transition: Tuple[str, str],
        diagnostic_label: str,
        registry=None,
        timeout_seconds: float = 15.0,
        ready_seconds: float = 2.0,
        verify_executable_version: bool = True,
        candidate_origin: str = "captured_verified",
        source_bundle: Optional[AcceptanceStateBundle] = None,
        clean_application_subtree_for_probe: bool = False,
    ) -> AcceptanceDiagnosticReceipt:
        """Test exact-version captured state or an explicit negative control.

        A potentially effective candidate must come from an opaque source
        bundle whose source probe, exact version, and executable hash have all
        been verified. Arbitrary, cross-version, or derived positive candidates
        are deliberately outside this public API. ``synthetic_negative`` is
        retained only for reversible invalid-state controls and can never be
        provisioned persistently.
        """
        transition = (source_version, expected_version)
        if source_version != expected_version:
            raise ValueError(
                "Acceptance-state diagnostics require exact-version source evidence"
            )
        if transition != tuple(permitted_transition):
            raise ValueError(
                f"Transition {transition!r} is not the explicitly permitted pair "
                f"{tuple(permitted_transition)!r}"
            )
        allowed_origins = {"captured_verified", "synthetic_negative"}
        if candidate_origin not in allowed_origins:
            raise ValueError(f"Unsupported candidate_origin: {candidate_origin!r}")
        value_type = candidate_registry_type
        if value_type is None:
            if winreg is None:
                raise RuntimeError("candidate_registry_type is required outside Windows")
            value_type = winreg.REG_SZ
        identity = RasAcceptanceState.executable_identity(
            ras_executable,
            expected_version=expected_version,
            verify_executable_version=verify_executable_version,
        )
        if source_bundle is not None:
            expected_bundle_fingerprint = _fingerprint(
                _bundle_fingerprint_payload(
                    source_bundle.identity,
                    source_bundle.state,
                    source_bundle.source_probe,
                )
            )
            if source_bundle.fingerprint != expected_bundle_fingerprint:
                raise ValueError("Source bundle fingerprint is invalid")
            if not source_bundle.no_modal_verified:
                raise ValueError("Source bundle requires a verified no-modal source probe")
            if (
                source_bundle.source_probe is None
                or source_bundle.source_probe.identity != source_bundle.identity
            ):
                raise ValueError("Source bundle probe identity is inconsistent")
            if (
                source_bundle.identity.version != expected_version
                or source_bundle.identity.version != source_version
            ):
                raise ValueError("Source bundle version must exactly match the target")
            if source_bundle.identity.sha256 != identity.sha256:
                raise ValueError(
                    "Source bundle executable hash must exactly match the target"
                )
            expected_source_key = RasAcceptanceState.registry_subkey(
                source_bundle.identity.path,
                expected_version=source_bundle.identity.version,
            )
            if source_bundle.state.key.casefold() != expected_source_key.casefold():
                raise ValueError("Source bundle registry namespace is inconsistent")
            if (
                not source_bundle.state.exists
                or source_bundle.state.value is None
                or
                source_bundle.state.value != str(candidate_value)
                or source_bundle.state.registry_type != value_type
            ):
                raise ValueError("Candidate does not exactly match the source bundle")
            candidate_origin = "captured_verified"
        elif candidate_origin != "synthetic_negative":
            raise ValueError(
                "Potentially effective candidates require a captured_verified "
                "source_bundle"
            )
        backend = registry or _WinRegistryBackend()
        key = RasAcceptanceState.registry_subkey(
            identity.path,
            expected_version=identity.version,
        )
        application_root = _application_root(key)
        before = backend.snapshot(key)
        before_subtree = (
            backend.subtree_snapshot(application_root)
            if hasattr(backend, "subtree_snapshot")
            else None
        )
        applied = before
        after_probe = before
        after_probe_subtree = before_subtree
        probe: Optional[AcceptanceProbeResult] = None
        with RasAcceptanceState.temporary_system_statistic(
            identity.path,
            candidate_value,
            expected_version=identity.version,
            registry_type=value_type,
            diagnostic_label=diagnostic_label,
            verify_executable_version=verify_executable_version,
            replace_application_subtree=clean_application_subtree_for_probe,
            registry=backend,
        ) as (_before, _applied):
            before, applied = _before, _applied
            probe = RasAcceptanceState.probe(
                identity.path,
                expected_version=identity.version,
                timeout_seconds=timeout_seconds,
                ready_seconds=ready_seconds,
                verify_executable_version=verify_executable_version,
            )
            after_probe = backend.snapshot(key)
            after_probe_subtree = (
                backend.subtree_snapshot(application_root)
                if hasattr(backend, "subtree_snapshot")
                else None
            )
        restored = backend.snapshot(key)
        restored_subtree = (
            backend.subtree_snapshot(application_root)
            if hasattr(backend, "subtree_snapshot")
            else None
        )
        restored_exactly = (
            restored == before
            and (
                before_subtree is None
                or restored_subtree == before_subtree
            )
        )
        candidate_stayed_exact = after_probe == applied
        assert probe is not None
        candidate_fp = _fingerprint(
            {
                "source_version": source_version,
                "target_version": expected_version,
                "target_sha256": identity.sha256,
                "value": candidate_value,
                "registry_type": value_type,
                "candidate_origin": candidate_origin,
                "source_bundle_fingerprint": (
                    source_bundle.fingerprint if source_bundle else None
                ),
            }
        )
        passed = (
            probe.no_modal_verified
            and restored_exactly
            and candidate_stayed_exact
        )
        return AcceptanceDiagnosticReceipt(
            target=identity,
            source_version=source_version,
            transition=transition,
            candidate_value=str(candidate_value),
            candidate_registry_type=int(value_type),
            candidate_fingerprint=candidate_fp,
            before=before,
            applied=applied,
            restored=restored,
            probe=probe,
            registry_restored=restored_exactly,
            passed=passed,
            diagnostic_label=diagnostic_label,
            created_at_utc=_utc_now(),
            after_probe=after_probe,
            candidate_stayed_exact=candidate_stayed_exact,
            application_subtree_before_fingerprint=_subtree_fingerprint(
                before_subtree
            ),
            application_subtree_after_probe_fingerprint=_subtree_fingerprint(
                after_probe_subtree
            ),
            application_subtree_restored_fingerprint=_subtree_fingerprint(
                restored_subtree
            ),
            candidate_origin=candidate_origin,
            source_bundle_fingerprint=(
                source_bundle.fingerprint if source_bundle else None
            ),
            clean_application_subtree_for_probe=bool(
                clean_application_subtree_for_probe
            ),
        )

    @staticmethod
    @log_call
    def provision(
        ras_executable: str | Path,
        *,
        diagnostic: AcceptanceDiagnosticReceipt,
        authorization_reference: str,
        destination_is_disposable: bool,
        expected_version: Optional[str] = None,
        dry_run: bool = True,
        verify_executable_version: bool = True,
        source_bundle: Optional[AcceptanceStateBundle] = None,
        replace_application_subtree: bool = False,
        registry=None,
    ) -> AcceptanceProvisionReceipt:
        """Provision only a candidate proven by a matching diagnostic receipt."""
        if not diagnostic.passed:
            raise ValueError("A passed restoring diagnostic is required")
        if not diagnostic.candidate_stayed_exact:
            raise ValueError("The diagnostic candidate did not remain exact")
        if not diagnostic.probe.no_modal_verified:
            raise ValueError("The diagnostic probe is not a verified no-modal result")
        if not diagnostic.registry_restored or diagnostic.before != diagnostic.restored:
            raise ValueError("The diagnostic did not restore its exact prior value")
        if (
            diagnostic.application_subtree_before_fingerprint
            != diagnostic.application_subtree_restored_fingerprint
        ):
            raise ValueError("The diagnostic did not restore its application subtree")
        if (
            not diagnostic.applied.exists
            or diagnostic.applied.value != diagnostic.candidate_value
            or diagnostic.applied.registry_type != diagnostic.candidate_registry_type
            or diagnostic.after_probe != diagnostic.applied
        ):
            raise ValueError("The diagnostic applied/observed candidate is inconsistent")
        if diagnostic.transition != (
            diagnostic.target.version,
            diagnostic.target.version,
        ) or diagnostic.source_version != diagnostic.target.version:
            raise ValueError(
                "Persistent provisioning requires exact-version diagnostic evidence"
            )
        if (
            diagnostic.candidate_origin != "captured_verified"
            or not diagnostic.source_bundle_fingerprint
        ):
            raise ValueError(
                "Persistent provisioning requires captured_verified source evidence"
            )
        if (
            replace_application_subtree
            and not diagnostic.clean_application_subtree_for_probe
        ):
            raise ValueError(
                "Clean-subtree provisioning requires a clean-subtree diagnostic"
            )
        if not authorization_reference.strip():
            raise ValueError("An authorization_reference is required")
        if not destination_is_disposable:
            raise ValueError("Persistent provisioning is limited to disposable targets")
        identity = RasAcceptanceState.executable_identity(
            ras_executable,
            expected_version=expected_version or diagnostic.target.version,
            verify_executable_version=verify_executable_version,
        )
        if identity != diagnostic.target:
            raise ValueError("Target executable identity differs from the diagnostic")
        expected_candidate_fingerprint = _fingerprint(
            {
                "source_version": diagnostic.source_version,
                "target_version": diagnostic.target.version,
                "target_sha256": diagnostic.target.sha256,
                "value": diagnostic.candidate_value,
                "registry_type": diagnostic.candidate_registry_type,
                "candidate_origin": diagnostic.candidate_origin,
                "source_bundle_fingerprint": diagnostic.source_bundle_fingerprint,
            }
        )
        if diagnostic.candidate_fingerprint != expected_candidate_fingerprint:
            raise ValueError("Diagnostic candidate fingerprint is invalid")
        key = RasAcceptanceState.registry_subkey(
            identity.path,
            expected_version=identity.version,
        )
        application_root = _application_root(key)
        if source_bundle is None:
            raise ValueError(
                "captured_verified provisioning requires the original source bundle"
            )
        expected_bundle_fingerprint = _fingerprint(
            _bundle_fingerprint_payload(
                source_bundle.identity,
                source_bundle.state,
                source_bundle.source_probe,
            )
        )
        expected_source_key = RasAcceptanceState.registry_subkey(
            source_bundle.identity.path,
            expected_version=source_bundle.identity.version,
        )
        if (
            source_bundle.fingerprint != expected_bundle_fingerprint
            or diagnostic.source_bundle_fingerprint != source_bundle.fingerprint
            or not source_bundle.no_modal_verified
            or source_bundle.source_probe is None
            or source_bundle.source_probe.identity != source_bundle.identity
            or source_bundle.identity.version != identity.version
            or source_bundle.identity.sha256 != identity.sha256
            or source_bundle.state.key.casefold() != expected_source_key.casefold()
            or not source_bundle.state.exists
            or source_bundle.state.value != diagnostic.candidate_value
            or source_bundle.state.registry_type
            != diagnostic.candidate_registry_type
        ):
            raise ValueError(
                "captured_verified source bundle does not match the exact target"
            )
        written = False
        if not dry_run:
            backend = registry or _WinRegistryBackend()
            lock = RasAcceptanceState._lock_for(key)
            with lock, _cross_process_lock(key):
                if RasAcceptanceState._target_running(identity):
                    raise RuntimeError(
                        "Refusing provisioning while target executable is running"
                    )
                before = backend.snapshot(key)
                before_subtree = (
                    backend.subtree_snapshot(application_root)
                    if replace_application_subtree
                    and hasattr(backend, "subtree_snapshot")
                    else None
                )
                if replace_application_subtree and before_subtree is None:
                    raise RuntimeError(
                        "Registry backend cannot replace the application subtree"
                    )
                created: List[str] = []
                try:
                    if replace_application_subtree:
                        backend.restore_subtree(application_root, {})
                    created = backend.set_value(
                        key,
                        diagnostic.candidate_value,
                        diagnostic.candidate_registry_type,
                    )
                    observed = backend.snapshot(key)
                    if (
                        not observed.exists
                        or observed.value != diagnostic.candidate_value
                        or observed.registry_type
                        != diagnostic.candidate_registry_type
                    ):
                        raise RuntimeError(
                            "Provisioned acceptance state failed exact readback"
                        )
                    written = True
                except BaseException:
                    if replace_application_subtree:
                        backend.restore_subtree(application_root, before_subtree)
                    else:
                        backend.restore_value(before, created)
                    raise
        return AcceptanceProvisionReceipt(
            target=identity,
            key=key,
            value_name=_VALUE_NAME,
            value=diagnostic.candidate_value,
            registry_type=diagnostic.candidate_registry_type,
            diagnostic_fingerprint=diagnostic.candidate_fingerprint,
            authorization_reference=authorization_reference,
            dry_run=dry_run,
            written=written,
            created_at_utc=_utc_now(),
            application_subtree_replaced=(
                bool(replace_application_subtree) and not dry_run
            ),
        )


__all__ = [
    "AcceptanceDiagnosticReceipt",
    "AcceptanceProbeResult",
    "AcceptanceProvisionReceipt",
    "AcceptanceStateBundle",
    "AuthorizedLegacyUiTransferReceipt",
    "LegacyTcuContractEvidence",
    "LegacyUiTransferSourceCapture",
    "RasAcceptanceState",
    "RasExecutableIdentity",
    "RegistryValueSnapshot",
    "UserDrivenAcceptanceReceipt",
]
