"""Accept the HEC-RAS Terms and Conditions for Use in a Wine build prefix.

Run with Windows Python inside the target prefix, under a virtual display:

    xvfb-run -a wine C:\\Python311\\python.exe accept_tcu.py <Ras.exe> <probe.json>

This performs the operator's acceptance through HEC-RAS's own dialog for the
exact installed release: it launches only that ``Ras.exe``, acts only on that
process's window titled exactly "Terms and Conditions for Use (TCU)", selects
the exact "I agree ..." option, confirms the option is checked, then presses the
enabled "Next ..." / "OK" buttons until the dialog closes. It writes no
registry values itself and never copies acceptance state from another release
or machine. Run it only for releases whose terms the operator has accepted.
Read the terms at https://www.hec.usace.army.mil/software/hec-ras/.

After accepting, it relaunches ``Ras.exe`` and requires that the dialog no
longer appears. It then writes ``probe.json`` (schema
``ras-commander-tcu-probe/v1``): the exact executable path and SHA-256, every
label acted on, and ``verified: true``. Images set ``RAS_COMMANDER_TCU_PROBE``
to that file; ``RasTcu.status`` reports ``probe-verified`` only for the exact
executable bytes recorded.

Exit 0 when verified; non-zero otherwise.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import subprocess
import sys
import time

TITLE = "Terms and Conditions for Use (TCU)"
AGREE_PREFIX = "I agree to the above Terms and Conditions"
ADVANCE_LABELS = ("Next ...", "OK")
BM_GETCHECK, BM_CLICK, WM_CLOSE = 0x00F0, 0x00F5, 0x0010
# Seconds the dialog must stay closed (accepted) or never appear (relaunch).
DIALOG_SETTLE_SECONDS = 10
NO_DIALOG_SECONDS = 45

user32 = ctypes.windll.user32
EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _windows(pid: int) -> list[int]:
    found: list[int] = []

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _pid(hwnd) == pid:
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumProc(callback), 0)
    return found


def _children(hwnd: int) -> list[int]:
    found: list[int] = []

    def callback(child, _):
        found.append(child)
        return True

    user32.EnumChildWindows(hwnd, EnumProc(callback), 0)
    return found


def _session(ras_exe: str, timeout: float) -> dict:
    """Launch Ras.exe once; accept the dialog if it appears; close HEC-RAS."""
    evidence: dict = {"actions": [], "result": None}
    process = subprocess.Popen([ras_exe])
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    dialog_seen = False
    dialog_gone_since = None
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                evidence["result"] = "ras-exited"
                break
            windows = _windows(process.pid)
            dialogs = [h for h in windows if _text(h) == TITLE]
            if not dialogs:
                # Releases differ in what follows the dialog (5.0.7 shows a titled
                # main form; 6.x under Xvfb only its hidden "RAS" window), so the
                # evidence is the dialog's absence while Ras.exe keeps running.
                now = time.monotonic()
                dialog_gone_since = dialog_gone_since or now
                if dialog_seen and now - dialog_gone_since >= DIALOG_SETTLE_SECONDS:
                    evidence["result"] = "accepted"
                elif not dialog_seen and now - started >= NO_DIALOG_SECONDS:
                    evidence["result"] = "no-dialog"
                if evidence["result"]:
                    evidence["windows"] = [_text(h) or _class(h) for h in windows]
                    break
                time.sleep(1)
                continue
            dialog_gone_since = None
            dialog_seen = True
            dialog = dialogs[0]
            controls = {(_class(c), _text(c)): c for c in _children(dialog)}
            agree = [c for (kind, label), c in controls.items()
                     if kind.endswith("OptionButton") and label.startswith(AGREE_PREFIX)]
            if len(agree) != 1:
                evidence["result"] = "agree-option-not-unique"
                evidence["controls"] = [list(key) for key in controls]
                return evidence
            if user32.SendMessageW(agree[0], BM_GETCHECK, 0, 0) != 1:
                user32.SendMessageW(agree[0], BM_CLICK, 0, 0)
                evidence["actions"].append(["click", _text(agree[0])])
                time.sleep(0.5)
                if user32.SendMessageW(agree[0], BM_GETCHECK, 0, 0) != 1:
                    evidence["result"] = "agree-not-checked"
                    return evidence
            advance = [(label, controls[(kind, label)]) for (kind, label) in controls
                       if kind.endswith("CommandButton") and label in ADVANCE_LABELS
                       and user32.IsWindowEnabled(controls[(kind, label)])]
            advance.sort(key=lambda item: ADVANCE_LABELS.index(item[0]))
            if advance:
                label, button = advance[0]
                user32.SendMessageW(button, BM_CLICK, 0, 0)
                evidence["actions"].append(["click", label])
            time.sleep(1)
        else:
            evidence["result"] = "timeout"
        return evidence
    finally:
        for hwnd in _windows(process.pid):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()


def _wine_version() -> str:
    try:
        function = ctypes.windll.ntdll.wine_get_version
        function.restype = ctypes.c_char_p
        return function().decode()
    except Exception:
        return "not-wine"


def main(ras_exe: str, probe_path: str, timeout: float = 180.0, scope: str = "image") -> int:
    first = _session(ras_exe, timeout)
    second = _session(ras_exe, timeout) if first["result"] in {"accepted", "no-dialog"} else None
    verified = bool(second) and second["result"] == "no-dialog"
    with open(ras_exe, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    record = {
        "schema": "ras-commander-tcu-probe/v1",
        "terms": "https://www.hec.usace.army.mil/software/hec-ras/",
        "wine": _wine_version(),
        # "image": accepted at image build; "task": accepted in this task's prefix.
        "scope": scope,
        "executables": [{
            "ras_executable": ras_exe,
            "ras_executable_sha256": digest,
            "dialog_title": TITLE,
            "acceptance": first,
            "relaunch": second,
            "verified": verified,
        }],
    }
    with open(probe_path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
    return 0 if verified else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], scope=sys.argv[3] if len(sys.argv) > 3 else "image"))
