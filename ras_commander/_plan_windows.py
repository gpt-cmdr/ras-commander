"""Read-only window diagnostics constrained by exact plan process identities."""

import ctypes
from ctypes import wintypes
import ntpath
import time


class _WindowsUi:
    """Minimal Windows/Wine reader; intentionally provides no UI actions."""

    def __init__(self):
        if not hasattr(ctypes, "WinDLL"):
            raise OSError("Window inspection requires Windows or Wine Python")
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetACP.argtypes = []
        kernel.GetACP.restype = wintypes.UINT
        self.ansi_encoding = f"cp{kernel.GetACP()}"
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
        self.api.IsWindowVisible.argtypes = [wintypes.HWND]
        self.api.IsWindowVisible.restype = wintypes.BOOL
        self.api.IsWindowUnicode.argtypes = [wintypes.HWND]
        self.api.IsWindowUnicode.restype = wintypes.BOOL
        self.api.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.api.GetClassNameW.restype = ctypes.c_int
        self.api.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.api.GetWindowTextW.restype = ctypes.c_int
        self.api.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.api.GetWindowLongW.restype = ctypes.c_long
        for name in ("SendMessageTimeoutW", "SendMessageTimeoutA"):
            function = getattr(self.api, name)
            function.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
                wintypes.UINT,
                wintypes.UINT,
                ctypes.POINTER(ctypes.c_size_t),
            ]
            function.restype = ctypes.c_ssize_t

    def windows(self, parent=None):
        handles = []

        @self.callback
        def collect(hwnd, _parameter):
            handles.append(int(hwnd))
            return True

        ctypes.set_last_error(0)
        if parent is None:
            success = self.api.EnumWindows(collect, 0)
        else:
            success = self.api.EnumChildWindows(parent, collect, 0)
        if not success and ctypes.get_last_error():
            raise OSError(ctypes.get_last_error(), "Cannot enumerate plan windows")
        return handles

    def pid(self, hwnd):
        value = wintypes.DWORD()
        if not self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(value)):
            raise OSError(ctypes.get_last_error(), "Cannot establish window owner")
        return int(value.value)

    def visible(self, hwnd):
        return bool(self.api.IsWindowVisible(hwnd))

    def class_name(self, hwnd):
        buffer = ctypes.create_unicode_buffer(256)
        if not self.api.GetClassNameW(hwnd, buffer, len(buffer)):
            raise OSError(ctypes.get_last_error(), "Cannot read owned control class")
        return buffer.value

    def style(self, hwnd):
        ctypes.set_last_error(0)
        value = self.api.GetWindowLongW(hwnd, -16)  # GWL_STYLE
        if not value and ctypes.get_last_error():
            raise OSError(ctypes.get_last_error(), "Cannot inspect owned control style")
        return int(value) & 0xFFFFFFFF

    def _message(self, hwnd, message, wparam=0, lparam=0, *, unicode=True):
        result = ctypes.c_size_t()
        function = (
            self.api.SendMessageTimeoutW if unicode else self.api.SendMessageTimeoutA
        )
        timeout = 1000 if message == 0x000D else 200
        ctypes.set_last_error(0)
        if not function(
            hwnd,
            message,
            wparam,
            lparam,
            0x0001 | 0x0002,
            timeout,
            ctypes.byref(result),
        ):
            raise OSError(
                ctypes.get_last_error(),
                f"Cannot query owned window text hwnd={hwnd} message=0x{message:04X} "
                f"encoding={'W' if unicode else 'A'} timeout_ms={timeout}",
            )
        return ctypes.c_ssize_t(result.value).value

    def text(self, hwnd, maximum):
        # WM_GETTEXT is a read-only query. A hung engine must not hang the
        # execution callback; SMTO_BLOCK | SMTO_ABORTIFHUNG bounds each read.
        unicode = bool(self.api.IsWindowUnicode(hwnd))
        buffer = (
            ctypes.create_unicode_buffer(maximum + 1)
            if unicode
            else ctypes.create_string_buffer(maximum * 4 + 1)
        )
        self._message(
            hwnd,
            0x000D,
            len(buffer),
            ctypes.cast(buffer, ctypes.c_void_p).value,
            unicode=unicode,
        )
        value = (
            buffer.value
            if unicode
            else buffer.value.decode(self.ansi_encoding, errors="replace")
        )
        return value[:maximum]

    def caption(self, hwnd, maximum):
        """Read a foreign top-level caption without messaging its UI thread."""
        buffer = ctypes.create_unicode_buffer(maximum + 1)
        ctypes.set_last_error(0)
        count = self.api.GetWindowTextW(hwnd, buffer, len(buffer))
        if not count and ctypes.get_last_error():
            raise OSError(
                ctypes.get_last_error(),
                f"Cannot query owned window caption hwnd={hwnd}",
            )
        return buffer.value[:maximum]

    def listbox_text(self, hwnd, maximum, guard):
        """Query string items from the end; never select or modify an item."""
        guard()
        count = self._message(hwnd, 0x018B)  # LB_GETCOUNT
        if count < 0:
            raise OSError("Cannot query owned list-box count")
        values, skipped = [], []
        available = maximum
        # LB_GETTEXT has no capacity parameter. Follow LB_GETTEXTLEN first,
        # reject oversized items, and retain full diagnostic-capacity headroom
        # if a trusted control changes an item between those two queries.
        for index in range(count - 1, max(-1, count - 129), -1):
            guard()
            length = self._message(hwnd, 0x018A, index)  # LB_GETTEXTLEN
            budget = available - bool(values)
            if length < 0:
                raise OSError("Owned list-box contents changed during inspection")
            if length > budget:
                skipped.append({"index": index, "length": length})
                continue
            if budget <= 0:
                break
            buffer = ctypes.create_unicode_buffer(65537)
            guard()
            actual = self._message(
                hwnd,
                0x0189,
                index,
                ctypes.cast(buffer, ctypes.c_void_p).value,
            )  # LB_GETTEXT
            guard()
            if actual < 0 or actual > budget:
                raise OSError("Owned list-box item changed length during inspection")
            value = buffer.value[:budget]
            values.append(value)
            available -= len(value) + (len(values) > 1)
        return {
            "text": "\n".join(reversed(values)),
            "item_count": count,
            "items_read": len(values),
            "skipped_item_lengths": skipped,
            "items_truncated": count > len(values),
        }


def _caption_control(class_name):
    """Exclude edit boxes and arbitrary data controls from body inspection."""
    name = class_name.casefold()
    return name in {
        "static",
        "button",
        "thunderrt6label",
        "thunderrt6commandbutton",
        "thunderrt6checkbox",
        "thunderrt6optionbutton",
        "thunderrt6frame",
    } or name.startswith(("windowsforms10.static.", "windowsforms10.button."))


def _control_kind(class_name, style):
    name = class_name.casefold()
    if _caption_control(class_name):
        return "caption", None
    if name in {"listbox", "thunderrt6listbox"} or name.startswith(
        "windowsforms10.listbox."
    ):
        if style & (0x0010 | 0x0020) and not style & 0x0040:
            return None, "owner_draw_listbox_without_strings"
        return "listbox", None
    if name in {
        "edit",
        "thunderrt6textbox",
        "richedit20w",
        "richedit50w",
        "richtextwndclass",
    } or name.startswith("windowsforms10.edit."):
        if style & 0x0020:  # ES_PASSWORD
            return None, "password_control"
        if not style & 0x0800:  # ES_READONLY
            return None, "editable_control"
        return "readonly_edit", None
    return None, "unsupported_control_class"


def inspect_owned_plan_windows(inventory, max_text_chars):
    """Return bounded text only for complete, exact-plan process evidence."""
    result = {
        "observed_at": time.time(),
        "plan_number": inventory.plan_number,
        "read_only": True,
        "complete": False,
        "inventory": inventory.to_dict(),
        "windows": [],
        "query_errors": [],
        "max_text_chars": max_text_chars,
        "text_budget_exhausted": False,
    }
    if not inventory.complete:
        result["query_errors"].append(
            {
                "reason_code": "process_inventory_incomplete",
                "detail": "No window queries permitted without complete process ownership",
            }
        )
        return result
    if not inventory.matched:
        result["complete"] = True
        return result

    query_context = None
    try:
        import psutil

        ui = _WindowsUi()
        allowed = {record.pid: record for record in inventory.matched}
        remaining = max_text_chars

        def verify(hwnd, record):
            # Check the HWND owner before any caption/body read, then use a
            # fresh Process instance to detect reuse of the captured PID.
            if ui.pid(hwnd) != record.pid:
                raise RuntimeError("Owned window identity changed")
            process = psutil.Process(record.pid)
            if float(process.create_time()) != record.create_time:
                raise RuntimeError("Owned process PID was reused")
            if record.executable_path is not None:
                normalize = lambda value: ntpath.normcase(ntpath.normpath(str(value)))
                if normalize(process.exe()) != normalize(record.executable_path):
                    raise RuntimeError("Owned process executable changed")

        def text(hwnd, record):
            nonlocal remaining
            verify(hwnd, record)
            value = ui.caption(hwnd, remaining)[:remaining]
            verify(hwnd, record)
            remaining -= len(value)
            return value

        def verify_control(hwnd, record, class_name, style):
            verify(hwnd, record)
            if ui.class_name(hwnd) != class_name or ui.style(hwnd) != style:
                raise RuntimeError("Owned control class or style changed")

        for hwnd in ui.windows():
            query_context = None
            pid = ui.pid(hwnd)
            if pid not in allowed or not ui.visible(hwnd):
                continue
            if remaining <= 0 or len(result["windows"]) >= 128:
                result["text_budget_exhausted"] = True
                break
            record = allowed[pid]
            verify(hwnd, record)
            query_context = {
                "hwnd": hwnd,
                "pid": pid,
                "class_name": ui.class_name(hwnd),
            }
            window = {
                "hwnd": hwnd,
                "pid": pid,
                "create_time": record.create_time,
                "title": text(hwnd, record),
                "controls": [],
                "skipped_controls": [],
            }
            for child in ui.windows(hwnd):
                query_context = None
                child_pid = ui.pid(child)
                if child_pid not in allowed or not ui.visible(child):
                    continue
                if len(window["controls"]) + len(window["skipped_controls"]) >= 128:
                    result["text_budget_exhausted"] = True
                    break
                child_record = allowed[child_pid]
                verify(child, child_record)
                class_name = ui.class_name(child)
                style = ui.style(child)
                kind, skip_reason = _control_kind(class_name, style)
                metadata = {
                    "hwnd": child,
                    "pid": child_pid,
                    "create_time": child_record.create_time,
                    "class_name": class_name,
                    "style": style,
                }
                query_context = dict(metadata)
                if kind is None or remaining <= 0:
                    metadata["reason_code"] = skip_reason or "text_budget_exhausted"
                    window["skipped_controls"].append(metadata)
                    result["text_budget_exhausted"] |= remaining <= 0
                    continue
                # Styles can change at runtime. Recheck permission immediately
                # around a body read, especially ES_READONLY and ES_PASSWORD.
                verify_control(child, child_record, class_name, style)
                if kind == "listbox":
                    body = ui.listbox_text(
                        child,
                        remaining,
                        lambda: verify_control(child, child_record, class_name, style),
                    )
                    caption = body.pop("text")[:remaining]
                    metadata.update(body)
                else:
                    caption = ui.text(child, remaining)[:remaining]
                verify_control(child, child_record, class_name, style)
                remaining -= len(caption)
                if caption or kind in {"listbox", "readonly_edit"}:
                    metadata.update(text=caption, control_type=kind)
                    window["controls"].append(metadata)
            verify(hwnd, record)
            result["windows"].append(window)
        result["text_budget_exhausted"] = (
            result["text_budget_exhausted"] or remaining <= 0
        )
        result["complete"] = True
    except Exception as exc:
        # Do not return text captured across an uncertain identity transition.
        result["windows"] = []
        result["query_errors"].append(
            {
                "reason_code": "owned_window_query_failed",
                "exception_type": type(exc).__name__,
                "detail": str(exc),
                "owned_control": query_context,
            }
        )
    return result
