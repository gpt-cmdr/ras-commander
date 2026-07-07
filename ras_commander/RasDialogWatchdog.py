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

import logging
import threading
import time
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
_WIN32_UNAVAILABLE_WARNED = False


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

    def _find_button(self, hwnd):
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

        for target in _DISMISS_LABELS:
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
            btn_hwnd, btn_text = self._find_button(hwnd)

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
