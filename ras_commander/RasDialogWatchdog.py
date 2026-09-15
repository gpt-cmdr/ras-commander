"""
Auto-dismiss HEC-RAS GUI dialogs during headless execution.

Background thread detects Windows dialog boxes (#32770) spawned by Ras.exe,
PipeServer.exe, RasProcess.exe, and RasPlotDriver.exe. Logs the dialog
title and body text at INFO level, then clicks OK/Yes/Close to unblock
the process.

Usage as context manager:
    with DialogWatchdog() as wd:
        process = subprocess.Popen(cmd)
        wd.add_pid(process.pid)
        process.wait()
    print(f"Dismissed {len(wd.dismissed)} dialogs")

Usage standalone:
    wd = DialogWatchdog()
    wd.start()
    ...
    wd.stop()
"""

import hashlib
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

try:
    import win32gui
    import win32con
    import win32process
    _WIN32 = True
except ImportError:
    win32gui = win32con = win32process = None
    _WIN32 = False

try:
    import psutil
    _PSUTIL = True
except ImportError:
    psutil = None
    _PSUTIL = False

logger = logging.getLogger(__name__)

_DIALOG_CLASS = "#32770"

_RAS_PROCESS_NAMES = frozenset({
    "ras.exe",
    "pipeserver.exe",
    "rasprocess.exe",
    "rasplotdriver.exe",
})

_DISMISS_LABELS = ["OK", "&OK", "Yes", "&Yes", "Close", "&Close"]
_DECLINE_LABELS = ["No", "&No", "Cancel", "&Cancel", "Close", "&Close"]
_OPTIONAL_INSTALL_PATTERNS = ("install the example projects",)
_WIN32_UNAVAILABLE_WARNED = False

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_STRICT_EXAMPLE_INSTALL_PROMPTS = frozenset(
    {
        "do you want to install the example projects for hec-ras?",
    }
)
_STRICT_DECLINE_BUTTONS = ("no", "cancel")
_STRICT_ACTION_TIMEOUT_MS = 500
_STRICT_STOP_TIMEOUT_SECONDS = 5.0
_SMTO_BLOCK = 0x0001
_SMTO_ABORTIFHUNG = 0x0002


def _safe_wall_time() -> float:
    """Return a finite timestamp suitable for strict JSON serialization."""
    try:
        value = float(time.time())
    except (OverflowError, TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def _normalized_windows_path(path: Path | str) -> str:
    """Normalize a Windows executable path without requiring it to exist."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _file_identity(stat_result: os.stat_result) -> tuple[int, ...]:
    """Return the strongest stable file fields exposed by Python on Windows."""
    return (
        int(stat_result.st_dev),
        int(stat_result.st_ino),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
        int(stat_result.st_ctime_ns),
    )


def _stable_file_sha256(path: Path) -> str:
    """Hash bytes from one stable handle still bound to the requested path."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        path_before = _file_identity(path.stat())
        handle_before = _file_identity(os.fstat(stream.fileno()))
        if path_before[:4] != handle_before[:4]:
            raise OSError("executable path changed before hashing")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        handle_after = _file_identity(os.fstat(stream.fileno()))
        path_after = _file_identity(path.stat())
    if handle_before != handle_after:
        raise OSError("opened executable changed while hashing")
    # Windows can expose a slightly different ctime through a path lookup and
    # an open handle. Device, file ID/inode, size, and mtime must still bind the
    # post-hash path to the exact handle whose bytes were read.
    if handle_after[:4] != path_after[:4]:
        raise OSError("executable path was replaced while hashing")
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class _ExactRasProcessIdentity:
    """Private, immutable identity for one exact ``Ras.exe`` process."""

    pid: int
    create_time: float
    process_name: str
    executable_path: Path
    executable_sha256: str

    def __post_init__(self) -> None:
        if isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid <= 0:
            raise ValueError("pid must be a positive integer")
        try:
            create_time = float(self.create_time)
        except (TypeError, ValueError) as exc:
            raise ValueError("create_time must be a positive finite number") from exc
        if not math.isfinite(create_time) or create_time <= 0:
            raise ValueError("create_time must be a positive finite number")
        if (
            not isinstance(self.process_name, str)
            or self.process_name.casefold() != "ras.exe"
        ):
            raise ValueError("process_name must identify Ras.exe exactly")
        executable_path = Path(self.executable_path)
        if executable_path.name.casefold() != "ras.exe":
            raise ValueError("executable_path must name Ras.exe exactly")
        if not executable_path.is_absolute():
            raise ValueError("executable_path must be absolute")
        if not isinstance(self.executable_sha256, str) or not _SHA256_PATTERN.fullmatch(
            self.executable_sha256
        ):
            raise ValueError("executable_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "create_time", create_time)
        object.__setattr__(self, "executable_path", executable_path)

    def _as_evidence(self) -> dict:
        return {
            "pid": self.pid,
            "create_time": self.create_time,
            "process_name": self.process_name,
            "executable_path": str(self.executable_path),
            "executable_sha256": self.executable_sha256,
        }


@dataclass(frozen=True, slots=True)
class _StrictDialogActionRule:
    """Reviewed private allowlist rule for a single safe dialog action."""

    rule_id: str
    exact_bodies: frozenset[str]
    decline_buttons: tuple[str, ...]


_STRICT_DIALOG_ACTION_RULES = (
    _StrictDialogActionRule(
        rule_id="decline_optional_example_install",
        exact_bodies=_STRICT_EXAMPLE_INSTALL_PROMPTS,
        decline_buttons=_STRICT_DECLINE_BUTTONS,
    ),
)


class _ExactDialogObserver:
    """Observe dialogs for one exact process and preserve unknown dialogs.

    This private observer is used by the opt-in
    ``RasControl.run_plan(observe_dialogs=True)`` path. Unlike
    :class:`DialogWatchdog`, it never discovers processes, never clicks a generic
    first button, and never sends ``WM_CLOSE``. The sole reviewed action is to
    decline the exact optional example-install prompt.
    """

    def __init__(
        self,
        identity: _ExactRasProcessIdentity,
        poll_interval: float = 1.5,
    ) -> None:
        try:
            interval = float(poll_interval)
        except (TypeError, ValueError) as exc:
            raise ValueError("poll_interval must be a positive finite number") from exc
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("poll_interval must be a positive finite number")
        self._identity = identity
        self._poll_interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._observations: list[dict] = []
        self._identity_checks: list[dict] = []
        self._seen_hwnds: set[int] = set()
        self._lock = threading.Lock()
        self._action_gate = threading.Lock()
        self._available = bool(_WIN32 and _PSUTIL)
        self._start_attempted = False
        self._started = False
        self._start_status = "not_attempted"
        self._stop_requested = False
        self._stop_confirmed = False
        self._stop_timeout_seconds = _STRICT_STOP_TIMEOUT_SECONDS
        self._stop_status = "not_requested"
        self._stop_elapsed_seconds = 0.0
        self._identity_check_count = 0
        self._last_identity_check_timestamp: float | None = None
        self._lifecycle = "created"
        self._lifecycle_transitions = [
            {
                "sequence": 1,
                "state": "created",
                "reason": "observer_created",
                "timestamp": _safe_wall_time(),
            }
        ]

    def _transition_lifecycle(self, state: str, reason: str) -> None:
        with self._lock:
            self._lifecycle = state
            self._lifecycle_transitions.append(
                {
                    "sequence": len(self._lifecycle_transitions) + 1,
                    "state": state,
                    "reason": reason,
                    "timestamp": _safe_wall_time(),
                }
            )

    def _start(self) -> bool:
        self._start_attempted = True
        if self._thread and self._thread.is_alive():
            self._start_status = "restart_refused_thread_alive"
            self._transition_lifecycle(
                self._lifecycle,
                "restart_refused_thread_alive",
            )
            return False
        self._started = False
        self._available = bool(_WIN32 and _PSUTIL)
        if not self._available:
            self._record_identity_check("identity_unverified")
            self._start_status = "dependency_unavailable"
            self._transition_lifecycle("unavailable", "dependency_unavailable")
            return False
        self._stop.clear()
        self._stop_requested = False
        self._stop_confirmed = False
        self._stop_status = "not_requested"
        self._stop_elapsed_seconds = 0.0
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="ExactRasDialogObserver",
        )
        try:
            self._thread.start()
        except Exception as exc:
            self._start_status = "thread_start_failed"
            self._transition_lifecycle(
                "start_failed",
                f"thread_start_failed:{type(exc).__name__}",
            )
            raise
        self._started = True
        self._start_status = "started"
        self._transition_lifecycle("running", "thread_started")
        return True

    def _stop_observing(self) -> None:
        started = time.monotonic()
        deadline = started + self._stop_timeout_seconds
        self._stop_requested = True
        self._stop_confirmed = False
        self._stop.set()
        # If a bounded action already began, wait for its outcome. If a scan is
        # blocked before the action gate, it will observe the stop event inside
        # this gate and cannot click after this method returns.
        remaining = max(0.0, deadline - time.monotonic())
        acquired = self._action_gate.acquire(timeout=remaining)
        if not acquired:
            self._stop_status = "action_gate_timeout"
            self._stop_elapsed_seconds = max(0.0, time.monotonic() - started)
            self._transition_lifecycle("stop_timeout", "action_gate_timeout")
            return
        self._action_gate.release()

        if self._thread and self._thread.is_alive():
            remaining = max(0.0, deadline - time.monotonic())
            self._thread.join(timeout=remaining)
        self._stop_elapsed_seconds = max(0.0, time.monotonic() - started)
        if self._thread and self._thread.is_alive():
            self._stop_status = "thread_timeout"
            self._transition_lifecycle("stop_timeout", "thread_timeout")
        elif not self._started:
            self._stop_confirmed = True
            self._stop_status = "stopped_before_start"
            self._transition_lifecycle("stopped", "stopped_before_start")
        else:
            self._stop_confirmed = True
            self._stop_status = "completed"
            self._transition_lifecycle("stopped", "stop_confirmed")

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan_once()
            except Exception as exc:
                logger.debug("Exact dialog observer scan error: %s", exc)
            self._stop.wait(self._poll_interval)

    def _record_identity_check(self, state: str) -> None:
        timestamp = _safe_wall_time()
        with self._lock:
            self._identity_check_count += 1
            self._last_identity_check_timestamp = timestamp
            if self._identity_checks and self._identity_checks[-1]["state"] == state:
                return
            self._identity_checks.append(
                {
                    "state": state,
                    "first_check_count": self._identity_check_count,
                    "timestamp": timestamp,
                }
            )

    def _inspect_process_metadata(self, process) -> tuple[str, Path | None]:
        if int(getattr(process, "pid", -1)) != self._identity.pid:
            return "pid_reused", None
        try:
            observed_create_time = float(process.create_time())
        except Exception as exc:
            no_such_process = getattr(psutil, "NoSuchProcess", ())
            if no_such_process and isinstance(exc, no_such_process):
                return "absent", None
            return "identity_unverified", None
        if not math.isfinite(observed_create_time):
            return "identity_unverified", None
        if not math.isclose(
            observed_create_time,
            self._identity.create_time,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            return "pid_reused", None

        try:
            observed_name = process.name()
        except Exception:
            return "identity_unverified", None
        if not isinstance(observed_name, str):
            return "identity_unverified", None
        if observed_name.casefold() != self._identity.process_name.casefold():
            return "name_mismatch", None

        try:
            observed_path = Path(process.exe())
        except Exception:
            return "identity_unverified", None
        if _normalized_windows_path(observed_path) != _normalized_windows_path(
            self._identity.executable_path
        ):
            return "path_mismatch", None
        return "exact", observed_path

    def _verify_identity(self) -> str:
        if not _PSUTIL:
            return "identity_unverified"
        try:
            process = psutil.Process(self._identity.pid)
        except Exception as exc:
            no_such_process = getattr(psutil, "NoSuchProcess", ())
            if no_such_process and isinstance(exc, no_such_process):
                return "absent"
            return "identity_unverified"

        state, observed_path = self._inspect_process_metadata(process)
        if state != "exact" or observed_path is None:
            return state

        try:
            observed_sha256 = _stable_file_sha256(observed_path)
        except (OSError, PermissionError, ValueError):
            return "identity_unverified"

        final_state, final_path = self._inspect_process_metadata(process)
        if final_state != "exact" or final_path is None:
            return final_state
        if _normalized_windows_path(final_path) != _normalized_windows_path(observed_path):
            return "path_mismatch"
        if observed_sha256 != self._identity.executable_sha256:
            return "hash_mismatch"
        return "exact"

    def _scan_once(self) -> None:
        identity_state = self._verify_identity()
        self._record_identity_check(identity_state)
        if identity_state != "exact":
            return

        dialogs: list[tuple[int, int]] = []

        def _enum_cb(hwnd, _) -> bool:
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                if win32gui.GetClassName(hwnd) != _DIALOG_CLASS:
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == self._identity.pid:
                    dialogs.append((hwnd, pid))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_enum_cb, None)
        for hwnd, pid in dialogs:
            with self._lock:
                if hwnd in self._seen_hwnds:
                    continue
                self._seen_hwnds.add(hwnd)
            self._observe(hwnd, pid)

    @staticmethod
    def _normalize_dialog_text(value: str) -> str:
        return " ".join(value.split()).casefold()

    @staticmethod
    def _normalize_button_label(value: str) -> str:
        return value.replace("&", "").strip().casefold()

    def _read_dialog(self, hwnd: int) -> tuple[str, str, list[tuple[int, str]]]:
        title = win32gui.GetWindowText(hwnd)
        body_parts: list[str] = []
        buttons: list[tuple[int, str]] = []

        def _child_cb(child, _) -> bool:
            try:
                child_class = win32gui.GetClassName(child)
                text = win32gui.GetWindowText(child)
                if child_class == "Static" and text and text.strip():
                    body_parts.append(text.strip())
                elif child_class == "Button" and text:
                    buttons.append((child, text))
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(hwnd, _child_cb, None)
        except Exception:
            pass
        return title, " | ".join(body_parts), buttons

    def _match_allowlisted_action(
        self,
        body: str,
        buttons: list[tuple[int, str]],
    ) -> tuple[_StrictDialogActionRule, int, str] | None:
        normalized_body = self._normalize_dialog_text(body)
        for rule in _STRICT_DIALOG_ACTION_RULES:
            if normalized_body not in rule.exact_bodies:
                continue
            for requested_label in rule.decline_buttons:
                for button_hwnd, button_label in buttons:
                    if self._normalize_button_label(button_label) == requested_label:
                        return rule, button_hwnd, button_label
        return None

    def _dialog_window_is_exact(self, hwnd: int) -> bool:
        try:
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                return False
            if win32gui.GetClassName(hwnd) != _DIALOG_CLASS:
                return False
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return int(pid) == self._identity.pid
        except Exception:
            return False

    def _button_is_exact(
        self,
        dialog_hwnd: int,
        button_hwnd: int,
        expected_label: str,
    ) -> bool:
        try:
            if not win32gui.IsWindow(button_hwnd):
                return False
            if win32gui.GetClassName(button_hwnd) != "Button":
                return False
            if not win32gui.IsChild(dialog_hwnd, button_hwnd):
                return False
            _, pid = win32process.GetWindowThreadProcessId(button_hwnd)
            if int(pid) != self._identity.pid:
                return False
            observed_label = win32gui.GetWindowText(button_hwnd)
            return self._normalize_button_label(observed_label) == (
                self._normalize_button_label(expected_label)
            )
        except Exception:
            return False

    def _revalidate_allowlisted_action(
        self,
        hwnd: int,
    ) -> tuple[
        str,
        str | None,
        str | None,
        list[tuple[int, str]],
        tuple[_StrictDialogActionRule, int, str] | None,
        str,
    ]:
        identity_state = self._verify_identity()
        self._record_identity_check(identity_state)
        if identity_state != "exact":
            return (
                "identity_changed",
                None,
                None,
                [],
                None,
                identity_state,
            )
        if not self._dialog_window_is_exact(hwnd):
            return "dialog_window_changed", None, None, [], None, identity_state

        title, body, buttons = self._read_dialog(hwnd)
        matched = self._match_allowlisted_action(body, buttons)
        if matched is None:
            return "dialog_content_changed", title, body, buttons, None, identity_state
        _, button_hwnd, button_label = matched
        if not self._button_is_exact(hwnd, button_hwnd, button_label):
            return "button_window_changed", title, body, buttons, None, identity_state
        return "exact", title, body, buttons, matched, identity_state

    @staticmethod
    def _is_message_timeout(exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if getattr(exc, "winerror", None) == 1460:
            return True
        return bool(exc.args and exc.args[0] == 1460)

    def _bounded_click(self, button_hwnd: int) -> tuple[str, str | None]:
        if self._stop.is_set():
            return "stop_requested", None
        sender = getattr(win32gui, "SendMessageTimeout", None)
        if not callable(sender):
            return "unavailable", "SendMessageTimeoutUnavailable"
        try:
            sender(
                button_hwnd,
                0x00F5,
                0,
                0,
                _SMTO_BLOCK | _SMTO_ABORTIFHUNG,
                _STRICT_ACTION_TIMEOUT_MS,
            )
        except Exception as exc:
            if self._is_message_timeout(exc):
                return "timed_out", type(exc).__name__
            return "failed", type(exc).__name__
        return "completed", None

    def _observe(self, hwnd: int, pid: int) -> None:
        identity_state = self._verify_identity()
        self._record_identity_check(identity_state)
        if identity_state != "exact":
            with self._lock:
                self._seen_hwnds.discard(hwnd)
            return

        try:
            title, body, buttons = self._read_dialog(hwnd)
            matched = self._match_allowlisted_action(body, buttons)
            classification = "unknown_preserved"
            action = "none"
            button = None
            rule_id = None
            identity_state = "exact"
            action_status = "not_requested"
            action_error_type = None
            action_timeout_ms = None
            proof_state = "not_applicable"
            revalidated_title = None
            revalidated_body = None
            revalidated_buttons: list[tuple[int, str]] = []

            if matched is not None:
                action_timeout_ms = _STRICT_ACTION_TIMEOUT_MS
                with self._action_gate:
                    if self._stop.is_set():
                        proof_state = "stop_requested"
                        action_status = "stop_requested"
                        classification = "stop_requested_preserved"
                    else:
                        (
                            proof_state,
                            revalidated_title,
                            revalidated_body,
                            revalidated_buttons,
                            revalidated_match,
                            identity_state,
                        ) = self._revalidate_allowlisted_action(hwnd)
                        if self._stop.is_set():
                            proof_state = "stop_requested"
                            action_status = "stop_requested"
                            classification = "stop_requested_preserved"
                        elif proof_state == "exact" and revalidated_match is not None:
                            rule, button_hwnd, button_label = revalidated_match
                            action = "BM_CLICK"
                            button = button_label
                            rule_id = rule.rule_id
                            action_status, action_error_type = self._bounded_click(
                                button_hwnd
                            )
                            if action_status == "completed":
                                classification = "allowlisted_dialog_declined"
                            elif action_status == "stop_requested":
                                action = "none"
                                proof_state = "stop_requested"
                                classification = "stop_requested_preserved"
                            elif action_status == "timed_out":
                                classification = "action_timeout_outcome_unknown"
                            elif action_status == "unavailable":
                                action = "none"
                                classification = "bounded_action_unavailable_preserved"
                            else:
                                classification = "action_failed_outcome_unknown"
                        elif proof_state == "identity_changed":
                            classification = "identity_changed_preserved"
                        elif proof_state == "dialog_window_changed":
                            classification = "dialog_window_changed_preserved"
                        elif proof_state == "button_window_changed":
                            classification = "button_window_changed_preserved"
                        else:
                            classification = "dialog_content_changed_preserved"

            observation = {
                "hwnd": int(hwnd),
                "pid": int(pid),
                "title": str(title),
                "body": str(body),
                "button_labels": [str(label) for _, label in buttons],
                "classification": classification,
                "action": action,
                "button": button,
                "rule_id": rule_id,
                "identity_state": identity_state,
                "proof_state": proof_state,
                "action_status": action_status,
                "action_timeout_ms": action_timeout_ms,
                "action_error_type": action_error_type,
                "revalidated_title": revalidated_title,
                "revalidated_body": revalidated_body,
                "revalidated_button_labels": [
                    str(label) for _, label in revalidated_buttons
                ],
                "timestamp": _safe_wall_time(),
            }
            with self._lock:
                self._observations.append(observation)
        except Exception as exc:
            logger.debug("Exact dialog observer failed for hwnd %s: %s", hwnd, exc)
            with self._lock:
                self._seen_hwnds.discard(hwnd)

    def _evidence(self) -> dict:
        with self._lock:
            observations = [dict(item) for item in self._observations]
            identity_checks = [dict(item) for item in self._identity_checks]
            lifecycle_transitions = [
                dict(item) for item in self._lifecycle_transitions
            ]
            lifecycle = self._lifecycle
            identity_check_count = self._identity_check_count
            last_identity_check_timestamp = self._last_identity_check_timestamp
        thread_alive = bool(self._thread and self._thread.is_alive())
        return {
            "scope": "exact_controller_identity",
            "process_discovery": False,
            "lifecycle": lifecycle,
            "lifecycle_transitions": lifecycle_transitions,
            "available": self._available,
            "start_attempted": self._start_attempted,
            "started": self._started,
            "start_status": self._start_status,
            "stop_requested": self._stop_requested,
            "stop_confirmed": self._stop_confirmed,
            "thread_alive": thread_alive,
            "stop_status": self._stop_status,
            "stop_timeout_seconds": self._stop_timeout_seconds,
            "stop_elapsed_seconds": self._stop_elapsed_seconds,
            "target": self._identity._as_evidence(),
            "observed_count": len(observations),
            "action_count": sum(
                item["action_status"] == "completed" for item in observations
            ),
            "action_attempt_count": sum(
                item["action_status"] in {"completed", "timed_out", "failed"}
                for item in observations
            ),
            "stop_prevented_action_count": sum(
                item["action_status"] == "stop_requested" for item in observations
            ),
            "observations": observations,
            "identity_checks": identity_checks,
            "identity_check_count": identity_check_count,
            "last_identity_check_timestamp": last_identity_check_timestamp,
        }


class DismissedDialog:
    """Record of a single dismissed dialog."""

    __slots__ = ("pid", "process_name", "title", "body", "button", "timestamp")

    def __init__(self, pid: int, process_name: str, title: str, body: str, button: str):
        self.pid = pid
        self.process_name = process_name
        self.title = title
        self.body = body
        self.button = button
        self.timestamp = time.time()

    def __repr__(self) -> str:
        return (
            f"DismissedDialog(pid={self.pid}, process={self.process_name!r}, "
            f"title={self.title!r}, button={self.button!r})"
        )


class DialogWatchdog:
    """Auto-dismiss HEC-RAS dialog windows during headless execution.

    Parameters
    ----------
    pids : set[int], optional
        Explicit PIDs to monitor. If empty, auto-discovers all running
        RAS-related processes via psutil.
    poll_interval : float
        Seconds between window scans (default 1.5).
    process_names : set[str], optional
        Lowercase executable names to treat as RAS processes.
    """

    def __init__(
        self,
        pids: Optional[Set[int]] = None,
        poll_interval: float = 1.5,
        process_names: Optional[Set[str]] = None,
    ):
        self._pids: Set[int] = set(pids) if pids else set()
        self._poll_interval = poll_interval
        self._process_names = process_names or _RAS_PROCESS_NAMES
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._dismissed: List[DismissedDialog] = []
        self._lock = threading.Lock()
        self._seen_hwnds: Set[int] = set()
        self._psutil_unavailable_logged = False
        self._psutil_failure_logged = False

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> "DialogWatchdog":
        self.start()
        return self

    def __exit__(self, *exc) -> bool:
        self.stop()
        return False

    # -- public API --------------------------------------------------------

    def start(self) -> None:
        global _WIN32_UNAVAILABLE_WARNED

        if not _WIN32:
            if not _WIN32_UNAVAILABLE_WARNED:
                logger.warning(
                    "DialogWatchdog requires pywin32 (win32gui); dialogs will NOT "
                    "be auto-dismissed. Install pywin32 on Windows or pass "
                    "dialog_watchdog=False to disable this watchdog."
                )
                _WIN32_UNAVAILABLE_WARNED = True
            else:
                logger.debug("DialogWatchdog unavailable because pywin32 is not installed")
            return

        if self._started and self._thread and self._thread.is_alive():
            logger.debug("DialogWatchdog start requested while already running")
            return

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="DialogWatchdog"
        )
        self._thread.start()
        self._started = True
        logger.debug(
            "DialogWatchdog started — polling every %.1fs for RAS dialog windows",
            self._poll_interval,
        )

    def stop(self) -> None:
        if not self._started:
            logger.debug("DialogWatchdog stop requested while watchdog is not running")
            return

        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._started = False
        n = len(self._dismissed)
        if n:
            logger.info("DialogWatchdog stopped — dismissed %d dialog(s)", n)
        else:
            logger.debug("DialogWatchdog stopped — no dialogs encountered")

    def add_pid(self, pid: int) -> None:
        with self._lock:
            self._pids.add(pid)

    def remove_pid(self, pid: int) -> None:
        with self._lock:
            self._pids.discard(pid)

    @property
    def dismissed(self) -> List[DismissedDialog]:
        with self._lock:
            return list(self._dismissed)

    def summary(self) -> str:
        records = self.dismissed
        if not records:
            return "DialogWatchdog: no dialogs dismissed"
        lines = [f"DialogWatchdog: {len(records)} dialog(s) dismissed"]
        for i, d in enumerate(records, 1):
            lines.append(
                f"  {i}. [{d.process_name} PID {d.pid}] "
                f"title={d.title!r} button={d.button!r} body={d.body!r}"
            )
        return "\n".join(lines)

    # -- internals ---------------------------------------------------------

    def _collect_ras_pids(self) -> Set[int]:
        pids: Set[int] = set()
        with self._lock:
            pids.update(self._pids)
        if not _PSUTIL:
            if not self._psutil_unavailable_logged:
                logger.debug(
                    "DialogWatchdog process discovery is limited because psutil "
                    "is not installed"
                )
                self._psutil_unavailable_logged = True
            return pids

        try:
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    name = proc.info["name"]
                    if name and name.lower() in self._process_names:
                        pids.add(proc.info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as exc:
            if not self._psutil_failure_logged:
                logger.debug("DialogWatchdog process discovery failed: %s", exc)
                self._psutil_failure_logged = True
        return pids

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan_and_dismiss()
            except Exception as exc:
                logger.debug("DialogWatchdog scan error: %s", exc)
            self._stop.wait(self._poll_interval)

    def _scan_and_dismiss(self) -> None:
        ras_pids = self._collect_ras_pids()
        if not ras_pids:
            return

        dialogs: List[tuple] = []

        def _enum_cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                if win32gui.GetClassName(hwnd) != _DIALOG_CLASS:
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid in ras_pids:
                    dialogs.append((hwnd, pid))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_enum_cb, None)

        for hwnd, pid in dialogs:
            if hwnd in self._seen_hwnds:
                continue
            self._seen_hwnds.add(hwnd)
            self._dismiss(hwnd, pid)

    def _read_body(self, hwnd) -> str:
        texts: List[str] = []

        def _child_cb(child, _):
            try:
                if win32gui.GetClassName(child) == "Static":
                    t = win32gui.GetWindowText(child)
                    if t and t.strip():
                        texts.append(t.strip())
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(hwnd, _child_cb, None)
        except Exception:
            pass
        return " | ".join(texts) if texts else ""

    def _find_button(self, hwnd, preferred_labels=None):
        buttons: List[tuple] = []

        def _child_cb(child, _):
            try:
                if win32gui.GetClassName(child) == "Button":
                    text = win32gui.GetWindowText(child)
                    if text:
                        buttons.append((child, text))
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(hwnd, _child_cb, None)
        except Exception:
            pass

        labels = preferred_labels or _DISMISS_LABELS
        for target in labels:
            normalized = target.replace("&", "").strip().lower()
            for btn_hwnd, btn_text in buttons:
                if btn_text.replace("&", "").strip().lower() == normalized:
                    return btn_hwnd, btn_text

        if buttons:
            return buttons[0]
        return None, None

    def _process_name(self, pid: int) -> str:
        if _PSUTIL:
            try:
                return psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return f"PID:{pid}"

    def _dismiss(self, hwnd: int, pid: int) -> None:
        try:
            title = win32gui.GetWindowText(hwnd)
            body = self._read_body(hwnd)
            pname = self._process_name(pid)
            dialog_text = f"{title}\n{body}".casefold()
            preferred_labels = (
                _DECLINE_LABELS
                if any(
                    pattern in dialog_text
                    for pattern in _OPTIONAL_INSTALL_PATTERNS
                )
                else None
            )
            btn_hwnd, btn_text = self._find_button(
                hwnd,
                preferred_labels=preferred_labels,
            )

            if btn_hwnd:
                logger.info(
                    "DialogWatchdog: auto-dismissing dialog — "
                    "process=%s PID=%d title=%r body=%r → clicking [%s]",
                    pname, pid, title, body, btn_text,
                )
                # BM_CLICK = 0x00F5
                win32gui.SendMessage(btn_hwnd, 0x00F5, 0, 0)
                record = DismissedDialog(pid, pname, title, body, btn_text)
            else:
                logger.warning(
                    "DialogWatchdog: closing dialog (no button found) — "
                    "process=%s PID=%d title=%r body=%r → sending WM_CLOSE",
                    pname, pid, title, body,
                )
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                record = DismissedDialog(pid, pname, title, body, "WM_CLOSE")

            with self._lock:
                self._dismissed.append(record)
            self._seen_hwnds.discard(hwnd)

        except Exception as exc:
            logger.debug("DialogWatchdog: failed to dismiss hwnd %s: %s", hwnd, exc)
            self._seen_hwnds.discard(hwnd)
