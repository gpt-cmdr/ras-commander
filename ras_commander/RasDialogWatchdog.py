"""
Auto-dismiss HEC-RAS GUI dialogs during headless execution.

Background thread detects Windows dialog boxes (#32770) spawned by Ras.exe,
PipeServer.exe, RasProcess.exe, and RasPlotDriver.exe. It may dismiss an
explicitly allowlisted informational dialog with an OK/Close control.
Legal-assent and unrecognized dialogs are fail-closed: no control is clicked
and the affected process tree is terminated when possible.

Scoped usage (preflight before launch):
    wd = DialogWatchdog()
    wd.require_available()
    process = subprocess.Popen(cmd)
    wd.add_pid(process.pid)
    try:
        wd.start()
        process.wait()
    except Exception:
        process.kill()
        raise
    finally:
        wd.stop()
    print(f"Dismissed {len(wd.dismissed)} dialogs")

Explicit global-discovery usage (never implicit):
    wd = DialogWatchdog(discover_processes=True)
    wd.start()
    ...
    wd.stop()
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from ._legal_dialogs import legal_dialog_blocking_reason

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

_DISMISS_LABELS = ["OK", "&OK", "Close", "&Close"]


@dataclass(frozen=True)
class ObservedWindow:
    """Read-only description of one process-scoped visible top-level window."""

    hwnd: int
    pid: int
    class_name: str
    title: str
    body: str
    owner_hwnd: int
    enabled: bool
    legal_reason: Optional[str]

    @property
    def topology_signature(self) -> Tuple[int, str, str, int, bool]:
        """Stable fields used to reject splash/modal topology changes."""
        return (
            self.pid,
            self.class_name,
            self.title,
            self.owner_hwnd,
            self.enabled,
        )


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


class BlockedDialog:
    """Record of a dialog that the watchdog refused to interact with."""

    __slots__ = (
        "pid",
        "process_name",
        "title",
        "body",
        "reason",
        "termination_root_pid",
        "process_tree_terminated",
        "timestamp",
    )

    def __init__(
        self,
        pid: int,
        process_name: str,
        title: str,
        body: str,
        reason: str,
        termination_root_pid: int,
        process_tree_terminated: bool,
    ):
        self.pid = pid
        self.process_name = process_name
        self.title = title
        self.body = body
        self.reason = reason
        self.termination_root_pid = termination_root_pid
        self.process_tree_terminated = process_tree_terminated
        self.timestamp = time.time()

    def __repr__(self) -> str:
        return (
            f"BlockedDialog(pid={self.pid}, process={self.process_name!r}, "
            f"title={self.title!r}, root_pid={self.termination_root_pid}, "
            f"terminated={self.process_tree_terminated})"
        )


class DialogWatchdog:
    """Auto-dismiss HEC-RAS dialog windows during headless execution.

    Parameters
    ----------
    pids : set[int], optional
        Explicit launcher PIDs to monitor. If empty, no process is monitored
        unless ``discover_processes=True`` is explicitly requested.
    poll_interval : float
        Seconds between window scans (default 1.5).
    process_names : set[str], optional
        Lowercase executable names to treat as RAS processes.
    safe_dialog_titles : set[str], optional
        Exact, case-insensitive dialog titles that may be dismissed with an
        OK/Close control. The default is empty. Legal-dialog classification
        always takes precedence over this allowlist.
    discover_processes : bool
        If True and no PID is registered, discover all known RAS process names.
        Defaults to False so unrelated interactive/concurrent sessions are
        never monitored implicitly.
    """

    def __init__(
        self,
        pids: Optional[Set[int]] = None,
        poll_interval: float = 1.5,
        process_names: Optional[Set[str]] = None,
        safe_dialog_titles: Optional[Set[str]] = None,
        discover_processes: bool = False,
    ):
        self._pids: Set[int] = set(pids) if pids else set()
        self._poll_interval = poll_interval
        self._process_names = process_names or _RAS_PROCESS_NAMES
        self._safe_dialog_titles = {
            title.strip().casefold()
            for title in (safe_dialog_titles or set())
            if title and title.strip()
        }
        self._discover_processes = discover_processes
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._dismissed: List[DismissedDialog] = []
        self._blocked: List[BlockedDialog] = []
        self._supervision_error: Optional[str] = None
        self._supervision_termination: dict[int, bool] = {}
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
        self.require_available()
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

    def require_available(self) -> None:
        """Fail before launch when modal supervision is unavailable."""
        if not _WIN32:
            raise RuntimeError(
                "DialogWatchdog requires pywin32 (win32gui, win32process). "
                "ras-commander refused to launch HEC-RAS without modal "
                "supervision; install pywin32 or explicitly set "
                "dialog_watchdog=False."
            )
        if not _PSUTIL:
            raise RuntimeError(
                "DialogWatchdog requires psutil for process-tree scoping and "
                "verified termination. ras-commander refused to launch "
                "HEC-RAS without complete modal supervision; install psutil "
                "or explicitly set dialog_watchdog=False."
            )

    def stop(self) -> None:
        if not self._started and not (
            self._thread and self._thread.is_alive()
        ):
            logger.debug("DialogWatchdog stop requested while watchdog is not running")
            return

        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._thread and self._thread.is_alive():
            with self._lock:
                self._supervision_error = (
                    self._supervision_error
                    or "DialogWatchdog monitor thread did not stop within 5 seconds"
                )
        self._started = False
        dismissed_count = len(self._dismissed)
        blocked_count = len(self._blocked)
        if blocked_count or self._supervision_error:
            logger.error(
                "DialogWatchdog stopped — blocked %d unsafe dialog(s), "
                "dismissed %d, supervision_error=%r",
                blocked_count,
                dismissed_count,
                self._supervision_error,
            )
        elif dismissed_count:
            logger.info(
                "DialogWatchdog stopped — dismissed %d dialog(s)",
                dismissed_count,
            )
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

    @property
    def blocked(self) -> List[BlockedDialog]:
        with self._lock:
            return list(self._blocked)

    @property
    def blocked_reason(self) -> Optional[str]:
        records = self.blocked
        if records:
            return records[0].reason
        with self._lock:
            return self._supervision_error

    @property
    def supervision_error(self) -> Optional[str]:
        """Return a scan/supervision failure independently of blocked dialogs."""
        with self._lock:
            return self._supervision_error

    def terminate_process_tree(self, pid: int) -> bool:
        """Terminate and verify one explicitly scoped launcher process tree."""
        return self._terminate_process_tree(pid)

    def scoped_pids(self) -> Set[int]:
        """Return the currently observable registered launcher process tree."""
        return self._collect_ras_pids()

    def observe_windows(self) -> Tuple[ObservedWindow, ...]:
        """Inspect every visible top-level window in the scoped process tree.

        Inspection is read-only. Any enumeration/classification failure is
        propagated so callers fail closed instead of silently losing modal
        supervision.
        """
        ras_pids = self._collect_ras_pids()
        if not ras_pids:
            return ()

        observed: List[ObservedWindow] = []
        errors: List[str] = []

        def _enum_cb(hwnd, _context):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in ras_pids:
                    return True
                class_name = win32gui.GetClassName(hwnd)
                title = win32gui.GetWindowText(hwnd)
                body = self._read_body(hwnd)
                owner = (
                    int(win32gui.GetWindow(hwnd, win32con.GW_OWNER) or 0)
                    if hasattr(win32gui, "GetWindow")
                    else 0
                )
                enabled = (
                    bool(win32gui.IsWindowEnabled(hwnd))
                    if hasattr(win32gui, "IsWindowEnabled")
                    else True
                )
                observed.append(
                    ObservedWindow(
                        hwnd=int(hwnd),
                        pid=int(pid),
                        class_name=str(class_name),
                        title=str(title),
                        body=body,
                        owner_hwnd=owner,
                        enabled=enabled,
                        legal_reason=legal_dialog_blocking_reason(
                            title=title,
                            body=body,
                        ),
                    )
                )
            except Exception as exc:
                errors.append(f"hwnd={hwnd}: {type(exc).__name__}: {exc}")
            return True

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception as exc:
            raise RuntimeError(
                f"top-level window enumeration failed: {type(exc).__name__}: {exc}"
            ) from exc
        if errors:
            raise RuntimeError("; ".join(errors))
        return tuple(
            sorted(
                observed,
                key=lambda item: (item.pid, item.owner_hwnd, item.class_name, item.title),
            )
        )

    def scan_once(self) -> None:
        """Run one synchronous fail-closed modal scan."""
        self._scan_and_dismiss()

    def summary(self) -> str:
        records = self.dismissed
        blocked = self.blocked
        with self._lock:
            supervision_error = self._supervision_error
            supervision_termination = dict(self._supervision_termination)
        if not records and not blocked and not supervision_error:
            return "DialogWatchdog: no dialogs dismissed"
        lines = [
            f"DialogWatchdog: {len(records)} dialog(s) dismissed, "
            f"{len(blocked)} blocked"
        ]
        for i, d in enumerate(records, 1):
            lines.append(
                f"  {i}. [{d.process_name} PID {d.pid}] "
                f"title={d.title!r} button={d.button!r} body={d.body!r}"
            )
        for i, d in enumerate(blocked, 1):
            lines.append(
                f"  blocked {i}. [{d.process_name} PID {d.pid}] "
                f"title={d.title!r} reason={d.reason!r} body={d.body!r}"
            )
        if supervision_error:
            lines.append(f"  supervision error: {supervision_error}")
            lines.append(
                "  termination verification: "
                + repr(supervision_termination)
            )
        return "\n".join(lines)

    # -- internals ---------------------------------------------------------

    def _collect_ras_pids(self) -> Set[int]:
        explicit_pids: Set[int] = set()
        with self._lock:
            explicit_pids.update(self._pids)

        # Once a caller registers its launcher PID, restrict supervision to that
        # process tree.  This avoids observing or terminating an unrelated
        # interactive HEC-RAS session on the same workstation.
        if explicit_pids:
            pids = set(explicit_pids)
            if _PSUTIL:
                for pid in explicit_pids:
                    try:
                        parent = psutil.Process(pid)
                        pids.update(child.pid for child in parent.children(recursive=True))
                    except psutil.NoSuchProcess:
                        pass
                    except psutil.AccessDenied as exc:
                        raise RuntimeError(
                            "process-tree enumeration was denied for registered "
                            f"launcher PID {pid}"
                        ) from exc
            return pids

        if not self._discover_processes:
            return set()

        pids: Set[int] = set()
        if _PSUTIL:
            try:
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        name = proc.info["name"]
                        if name and name.lower() in self._process_names:
                            pids.add(proc.info["pid"])
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except Exception:
                pass
        return pids

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan_and_dismiss()
            except Exception as exc:
                reason = (
                    "DialogWatchdog modal supervision failed; registered "
                    f"launch-tree termination was initiated: {exc}"
                )
                with self._lock:
                    self._supervision_error = reason
                    roots = set(self._pids)
                logger.exception(reason)
                termination = {}
                for root_pid in roots:
                    termination[root_pid] = self._terminate_process_tree(root_pid)
                with self._lock:
                    self._supervision_termination = termination
                    if termination and all(termination.values()):
                        status = "verified for all registered roots"
                    elif termination:
                        status = "not verified for every registered root"
                    else:
                        status = "no registered root was available"
                    self._supervision_error = f"{reason} Termination {status}."
                self._stop.set()
                return
            self._stop.wait(self._poll_interval)

    def _scan_and_dismiss(self) -> None:
        # HEC-RAS is a mixed VB/.NET application. Its legal-assent form is not
        # consistently exposed as #32770 (notably under Wine), so every
        # process-scoped top-level window receives read-only title/control-text
        # inspection. Generic unknown handling remains restricted to #32770.
        dialogs = [
            (window.hwnd, window.pid)
            for window in self.observe_windows()
            if window.class_name == _DIALOG_CLASS or window.legal_reason
        ]
        for hwnd, pid in dialogs:
            if hwnd in self._seen_hwnds:
                continue
            self._seen_hwnds.add(hwnd)
            self._dismiss(hwnd, pid)

    def _read_body(self, hwnd) -> str:
        texts: List[str] = []
        errors: List[str] = []

        def _child_cb(child, _):
            try:
                # VB/.NET/Wine expose legal text under several control
                # classes. Read all non-empty child labels; no message is sent.
                t = win32gui.GetWindowText(child)
                if t and t.strip():
                    texts.append(t.strip())
            except Exception as exc:
                errors.append(
                    f"child hwnd={child}: {type(exc).__name__}: {exc}"
                )
            return True

        try:
            win32gui.EnumChildWindows(hwnd, _child_cb, None)
        except Exception as exc:
            raise RuntimeError(
                "child-window enumeration failed for "
                f"hwnd={hwnd}: {type(exc).__name__}: {exc}"
            ) from exc
        if errors:
            raise RuntimeError("; ".join(errors))
        return " | ".join(texts) if texts else ""

    def _find_button(self, hwnd):
        buttons: List[tuple] = []
        errors: List[str] = []

        def _child_cb(child, _):
            try:
                if win32gui.GetClassName(child) == "Button":
                    text = win32gui.GetWindowText(child)
                    if text:
                        buttons.append((child, text))
            except Exception as exc:
                errors.append(
                    f"button child hwnd={child}: {type(exc).__name__}: {exc}"
                )
            return True

        try:
            win32gui.EnumChildWindows(hwnd, _child_cb, None)
        except Exception as exc:
            raise RuntimeError(
                "button enumeration failed for "
                f"hwnd={hwnd}: {type(exc).__name__}: {exc}"
            ) from exc
        if errors:
            raise RuntimeError("; ".join(errors))

        for target in _DISMISS_LABELS:
            normalized = target.replace("&", "").strip().lower()
            for btn_hwnd, btn_text in buttons:
                if btn_text.replace("&", "").strip().lower() == normalized:
                    return btn_hwnd, btn_text

        return None, None

    def _process_name(self, pid: int) -> str:
        if _PSUTIL:
            try:
                return psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return f"PID:{pid}"

    def _is_explicitly_safe(self, title: str) -> bool:
        """Return True only for a caller-allowlisted exact dialog title."""
        return title.strip().casefold() in self._safe_dialog_titles

    def _termination_root_pid(self, dialog_pid: int) -> int:
        """Resolve a child-owned dialog back to its registered launcher root."""
        with self._lock:
            roots = set(self._pids)

        if not roots or dialog_pid in roots:
            return dialog_pid

        if _PSUTIL:
            for root_pid in roots:
                try:
                    root = psutil.Process(root_pid)
                    if any(
                        child.pid == dialog_pid
                        for child in root.children(recursive=True)
                    ):
                        return root_pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        # Current RasCmdr/GeomPreprocessor callers register exactly one launcher.
        # If its child disappeared during inspection, retain that explicit scope
        # instead of falling back to killing only an orphaned dialog owner.
        if len(roots) == 1:
            return next(iter(roots))
        return dialog_pid

    def _terminate_process_tree(self, pid: int) -> bool:
        """Terminate one blocked RAS process tree without touching the dialog."""
        if not _PSUTIL:
            logger.error(
                "DialogWatchdog cannot terminate blocked PID %d because psutil "
                "is unavailable",
                pid,
            )
            return False

        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied:
            logger.error(
                "DialogWatchdog cannot inspect blocked launcher PID %d: access denied",
                pid,
            )
            return False
        except Exception as exc:
            logger.error(
                "DialogWatchdog cannot inspect blocked launcher PID %d: %s",
                pid,
                exc,
            )
            return False

        try:
            children = parent.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            logger.error(
                "DialogWatchdog cannot enumerate blocked launcher PID %d: %s",
                pid,
                exc,
            )
            return False

        targets = list(reversed(children)) + [parent]
        kill_failed = False
        for target in targets:
            try:
                target.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                kill_failed = True
                logger.error(
                    "DialogWatchdog could not kill PID %d: access denied",
                    target.pid,
                )
            except Exception as exc:
                kill_failed = True
                logger.error(
                    "DialogWatchdog could not kill PID %d: %s",
                    target.pid,
                    exc,
                )

        try:
            _gone, alive = psutil.wait_procs(targets, timeout=5)
        except Exception as exc:
            logger.error(
                "DialogWatchdog could not verify termination for launcher PID %d: %s",
                pid,
                exc,
            )
            return False

        if alive:
            kill_failed = True
            logger.error(
                "DialogWatchdog termination verification failed; PIDs still alive: %s",
                ", ".join(str(proc.pid) for proc in alive),
            )

        return not kill_failed

    def _dismiss(self, hwnd: int, pid: int) -> None:
        try:
            title = win32gui.GetWindowText(hwnd)
            body = self._read_body(hwnd)
            pname = self._process_name(pid)
            legal_reason = legal_dialog_blocking_reason(title=title, body=body)
            btn_hwnd, btn_text = self._find_button(hwnd)
            safe_informational = bool(btn_hwnd) and self._is_explicitly_safe(title)

            if legal_reason or not safe_informational:
                reason = legal_reason or (
                    "HEC-RAS displayed an unrecognized modal dialog. "
                    "ras-commander refused to click or close it."
                )
                termination_root_pid = self._termination_root_pid(pid)
                record = BlockedDialog(
                    pid,
                    pname,
                    title,
                    body,
                    reason,
                    termination_root_pid,
                    False,
                )
                # Publish the diagnostic before termination. The launcher wait
                # may return immediately once its tree is killed, so callers must
                # be able to observe ``blocked_reason`` without a race.
                with self._lock:
                    self._blocked.append(record)
                terminated = self._terminate_process_tree(termination_root_pid)
                with self._lock:
                    record.process_tree_terminated = terminated
                logger.error(
                    "DialogWatchdog: blocked unsafe dialog without interaction — "
                    "process=%s PID=%d root_PID=%d title=%r body=%r terminated=%s",
                    pname,
                    pid,
                    termination_root_pid,
                    title,
                    body,
                    terminated,
                )
                return

            logger.info(
                "DialogWatchdog: auto-dismissing informational dialog — "
                "process=%s PID=%d title=%r body=%r → clicking [%s]",
                pname,
                pid,
                title,
                body,
                btn_text,
            )
            # BM_CLICK = 0x00F5
            win32gui.SendMessage(btn_hwnd, 0x00F5, 0, 0)
            record = DismissedDialog(pid, pname, title, body, btn_text)

            with self._lock:
                self._dismissed.append(record)
            self._seen_hwnds.discard(hwnd)

        except Exception as exc:
            self._seen_hwnds.discard(hwnd)
            raise RuntimeError(
                f"DialogWatchdog failed to inspect/process hwnd {hwnd}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
