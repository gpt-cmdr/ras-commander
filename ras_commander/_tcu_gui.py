"""Explicit operator-authorized TCU UI action, isolated from compute watchdogs."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import ntpath
import time

from ._legal_dialogs import TCU_DIALOG_TITLE


def _normalized_caption(text: str) -> str:
    return " ".join(str(text).replace("&", "").split()).casefold()


def _select_agree_button(controls: list[dict]) -> dict:
    matches = [
        row
        for row in controls
        if _normalized_caption(row["text"])
        in {"i agree", "i agree to the above terms and conditions for use"}
        and row["visible"]
        and row["enabled"]
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one enabled I Agree control; controls={controls!r}"
        )
    return matches[0]


class _WindowsUi:
    def __init__(self):
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        for name in ("EnumWindows", "EnumChildWindows"):
            function = getattr(self.api, name)
            function.argtypes = (
                [wintypes.HWND] if name == "EnumChildWindows" else []
            ) + [self.callback, wintypes.LPARAM]
            function.restype = wintypes.BOOL
        self.api.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.api.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.api.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.api.GetClassNameW.restype = ctypes.c_int
        self.api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.api.GetWindowTextLengthW.restype = ctypes.c_int
        self.api.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.api.GetWindowTextW.restype = ctypes.c_int
        for name in ("IsWindow", "IsWindowVisible", "IsWindowEnabled"):
            function = getattr(self.api, name)
            function.argtypes = [wintypes.HWND]
            function.restype = wintypes.BOOL
        self.api.GetMenu.argtypes = [wintypes.HWND]
        self.api.GetMenu.restype = wintypes.HANDLE
        self.api.SendMessageTimeoutW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.api.SendMessageTimeoutW.restype = ctypes.c_ssize_t

    def windows(self, parent=None):
        result = []

        @self.callback
        def collect(hwnd, _):
            result.append(int(hwnd))
            return True

        if parent is None:
            if not self.api.EnumWindows(collect, 0):
                raise OSError(
                    ctypes.get_last_error(), "Cannot enumerate owned TCU windows"
                )
        else:
            self.api.EnumChildWindows(parent, collect, 0)
        return result

    def text(self, hwnd):
        size = self.api.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(size + 1)
        self.api.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def class_name(self, hwnd):
        buffer = ctypes.create_unicode_buffer(256)
        self.api.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value

    def pid(self, hwnd):
        owner = wintypes.DWORD()
        if not self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(owner)):
            raise OSError(ctypes.get_last_error(), "Cannot establish TCU window owner")
        return owner.value

    def controls(self, hwnd):
        return [
            {
                "hwnd": item,
                "text": self.text(item)[:160],
                "visible": bool(self.api.IsWindowVisible(item)),
                "enabled": bool(self.api.IsWindowEnabled(item)),
            }
            for item in self.windows(hwnd)
        ]

    def click(self, hwnd):
        result = ctypes.c_size_t()
        if not self.api.SendMessageTimeoutW(
            hwnd, 0x00F5, 0, 0, 0x0002, 2000, ctypes.byref(result)
        ):
            raise OSError(ctypes.get_last_error(), "TCU button click did not complete")

    def close(self, hwnd):
        result = ctypes.c_size_t()
        if not self.api.SendMessageTimeoutW(
            hwnd, 0x0010, 0, 0, 0x0002, 2000, ctypes.byref(result)
        ):
            raise OSError(
                ctypes.get_last_error(), "Owned HEC-RAS GUI did not acknowledge close"
            )


def accept_owned_terms(
    process,
    executable: str,
    timeout: float,
    *,
    keep_running: bool = False,
    expected_create_time: float | None = None,
) -> dict:
    """Click only an exact TCU dialog owned by the API-launched executable."""
    import psutil

    root = psutil.Process(process.pid)
    root_created = root.create_time()
    if expected_create_time is not None and root_created != expected_create_time:
        raise RuntimeError("TCU process creation time changed; no UI actions permitted")
    expected = ntpath.normcase(ntpath.normpath(executable))
    if ntpath.normcase(ntpath.normpath(root.exe())) != expected:
        raise RuntimeError("TCU process executable changed; no UI actions permitted")
    ui = _WindowsUi()
    owned = {(root.pid, root_created): root}
    deadline = time.monotonic() + timeout
    clicked = None
    next_clicked = False
    final_clicked = False
    main_ready_at = None
    verified_main = None
    receipt = {
        "launcher_pid": root.pid,
        "launcher_create_time": root_created,
        "executable": executable,
        "operator_acceptance": True,
        "clicked": False,
        "actions": [],
    }
    try:
        while time.monotonic() < deadline:
            # A detached launcher never grants permission for global window matching.
            for identity, candidate in list(owned.items()):
                try:
                    if candidate.create_time() != identity[1]:
                        continue
                    for child in candidate.children(recursive=True):
                        created = child.create_time()
                        if created >= root_created:
                            owned[(child.pid, created)] = child
                except psutil.NoSuchProcess:
                    continue
            allowed = {}
            for (pid, created), candidate in owned.items():
                try:
                    if (
                        candidate.create_time() == created
                        and ntpath.normcase(ntpath.normpath(candidate.exe()))
                        == expected
                    ):
                        allowed[pid] = candidate
                except psutil.NoSuchProcess:
                    continue
            if clicked is not None and (
                not ui.api.IsWindow(clicked) or not ui.api.IsWindowVisible(clicked)
            ):
                receipt["dialog_closed"] = True
                if keep_running:
                    return receipt
            ready_main = None
            saw_terms = False
            receipt["last_owned_windows"] = []
            for hwnd in ui.windows():
                pid = ui.pid(hwnd)
                if pid not in allowed or not ui.api.IsWindowVisible(hwnd):
                    continue
                receipt["last_owned_windows"].append(
                    {
                        "hwnd": hwnd,
                        "title": ui.text(hwnd),
                        "class": ui.class_name(hwnd),
                        "enabled": bool(ui.api.IsWindowEnabled(hwnd)),
                    }
                )
                if _normalized_caption(ui.text(hwnd)) != _normalized_caption(
                    TCU_DIALOG_TITLE
                ):
                    if (
                        ui.text(hwnd).casefold().startswith("hec-ras")
                        and ui.class_name(hwnd).casefold()
                        in {"thunderrt6mdiform", "thunderrt6formdc"}
                        and ui.api.IsWindowEnabled(hwnd)
                        and ui.api.GetMenu(hwnd)
                    ):
                        ready_main = hwnd
                    continue
                saw_terms = True
                controls = ui.controls(hwnd)
                receipt["last_controls"] = controls
                if clicked is None:
                    button = _select_agree_button(controls)
                    action = "agree"
                else:
                    candidates = [
                        row
                        for row in controls
                        if row["visible"]
                        and row["enabled"]
                        and _normalized_caption(row["text"])
                        == ("ok" if next_clicked else "next ...")
                    ]
                    if final_clicked or not candidates:
                        continue
                    if len(candidates) != 1:
                        raise RuntimeError("Ambiguous owned TCU confirmation control")
                    button = candidates[0]
                    action = "ok" if next_clicked else "next"
                candidate = allowed[pid]
                identity = (pid, candidate.create_time())
                if (
                    identity not in owned
                    or ui.pid(hwnd) != pid
                    or ui.pid(button["hwnd"]) != pid
                ):
                    raise RuntimeError(
                        "Owned TCU identity changed before explicit acceptance"
                    )
                if _normalized_caption(ui.text(hwnd)) != _normalized_caption(
                    TCU_DIALOG_TITLE
                ):
                    raise RuntimeError(
                        "Owned TCU title changed before explicit acceptance"
                    )
                ui.click(button["hwnd"])
                clicked = hwnd
                next_clicked = next_clicked or action == "next"
                final_clicked = final_clicked or action == "ok"
                receipt["actions"].append({"action": action, "caption": button["text"]})
                receipt.update(clicked=True, dialog_hwnd=hwnd)
                break
            if ready_main is not None and not saw_terms:
                if main_ready_at is None:
                    main_ready_at = time.monotonic()
                elif time.monotonic() - main_ready_at >= 5:
                    receipt.update(
                        already_accepted_profile=clicked is None,
                        ready_main_hwnd=ready_main,
                        gui_ready_verified=True,
                    )
                    verified_main = ready_main
                    return receipt
            else:
                main_ready_at = None
            time.sleep(0.1)
        raise TimeoutError(f"Explicit owned TCU acceptance did not finish: {receipt!r}")
    finally:
        if not keep_running:
            graceful = False
            close_error = None
            if verified_main is not None:
                try:
                    owner = ui.pid(verified_main)
                    candidates = [
                        (identity, candidate)
                        for identity, candidate in owned.items()
                        if identity[0] == owner
                        and candidate.create_time() == identity[1]
                    ]
                    if len(candidates) != 1:
                        raise RuntimeError(
                            "Owned main-window identity changed before graceful close"
                        )
                    ui.close(verified_main)
                    graceful = candidates[0][1].wait(timeout=5) == 0
                except Exception as error:
                    close_error = repr(error)
            # Only this API launch and witnessed descendants, protected against PID reuse.
            for (pid, created), candidate in reversed(list(owned.items())):
                try:
                    if candidate.create_time() == created:
                        if not graceful:
                            candidate.terminate()
                        try:
                            candidate.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            if candidate.create_time() == created:
                                candidate.kill()
                except psutil.NoSuchProcess:
                    pass
            receipt["graceful_exit"] = graceful
            if verified_main is not None and not graceful:
                raise RuntimeError(
                    f"TCU accepted but owned GUI did not exit gracefully; verification not saved: {close_error}"
                )
