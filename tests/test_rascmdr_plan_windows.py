"""Exact process ownership precedes every read-only plan window text query."""

from types import SimpleNamespace
import ctypes

import psutil
import pytest

from ras_commander import RasCmdr
from ras_commander.ComputeResults import (
    PlanProcessInventory, RasProcessQueryError, RasProcessRecord,
)
from ras_commander import _plan_windows


def _inventory(*, complete=True, matched=True):
    return PlanProcessInventory(
        observed_at=1001.0, plan_number="01", project_path="C:/model/model.prj",
        plan_path="C:/model/model.p01", tmp_hdf_path="C:/model/model.p01.tmp.hdf",
        complete=complete,
        matched=(RasProcessRecord(
            pid=10, create_time=1000.0, name="Ras.exe",
            executable_path="C:/HEC/Ras.exe",
            command_line=("Ras.exe", "C:/model/model.prj", "C:/model/model.p01"),
        ),) if matched else (),
        query_errors=() if complete else (RasProcessQueryError(
            pid=99, operation="name", reason_code="access_denied",
            exception_type="AccessDenied", detail="Name unavailable",
        ),),
    )


class FakeUi:
    def __init__(self):
        self.reads = []
        self.actions = []

    def windows(self, parent=None):
        return [100, 200] if parent is None else [101, 102, 103]

    def pid(self, hwnd):
        return 10 if hwnd in {100, 101, 103} else 20

    def visible(self, hwnd):
        return True

    def class_name(self, hwnd):
        assert hwnd != 102, "Foreign child class must not be inspected"
        return "Edit" if hwnd == 103 else "Static"

    def style(self, hwnd):
        assert hwnd != 102, "Foreign child style must not be inspected"
        return 0

    def text(self, hwnd, maximum):
        assert hwnd not in {200, 102}, "Foreign same-title text must never be read"
        assert hwnd != 103, "Edit-box values must not be read"
        self.reads.append((hwnd, maximum))
        return {100: "Error", 101: "Solver could not initialize"}[hwnd][:maximum]

    def caption(self, hwnd, maximum):
        assert hwnd == 100, "Only owned top-level captions use the cached reader"
        return self.text(hwnd, maximum)

    def click(self, hwnd):
        self.actions.append(hwnd)
        raise AssertionError("Window diagnosis performs no UI action")


@pytest.fixture
def reader(monkeypatch):
    ui = FakeUi()
    monkeypatch.setattr(_plan_windows, "_WindowsUi", lambda: ui)
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(
        create_time=lambda: 1000.0, exe=lambda: "C:\\HEC\\Ras.exe",
    ))
    monkeypatch.setattr(RasCmdr, "inspect_plan_processes", lambda *_a, **_k: _inventory())
    return ui


def test_foreign_same_title_and_foreign_child_text_never_read(reader):
    result = RasCmdr.inspect_plan_windows("01")
    assert result["complete"] is True
    assert [window["hwnd"] for window in result["windows"]] == [100]
    assert result["windows"][0]["title"] == "Error"
    assert [item["hwnd"] for item in result["windows"][0]["controls"]] == [101]
    assert [hwnd for hwnd, _maximum in reader.reads] == [100, 101]
    assert reader.actions == []


def test_incomplete_inventory_does_not_initialize_or_query_ui(monkeypatch):
    calls = []

    def inventory(*_args, **_kwargs):
        calls.append("inventory")
        return _inventory(complete=False)

    def forbidden():
        raise AssertionError("Incomplete inventory grants no window query")

    monkeypatch.setattr(RasCmdr, "inspect_plan_processes", inventory)
    monkeypatch.setattr(_plan_windows, "_WindowsUi", forbidden)
    result = RasCmdr.inspect_plan_windows("01")
    assert calls == ["inventory"]
    assert result["complete"] is False
    assert result["windows"] == []
    assert result["query_errors"][0]["reason_code"] == "process_inventory_incomplete"


def test_pid_reuse_is_detected_before_text_read(reader, monkeypatch):
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(
        create_time=lambda: 1002.0,
    ))
    result = RasCmdr.inspect_plan_windows("01")
    assert result["complete"] is False
    assert result["windows"] == []
    assert reader.reads == []
    assert "PID was reused" in result["query_errors"][0]["detail"]


def test_pid_reuse_after_text_read_discards_snapshot(reader, monkeypatch):
    calls = iter([1000.0, 1000.0, 1002.0])
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(
        create_time=lambda: next(calls), exe=lambda: "C:/HEC/Ras.exe",
    ))
    result = RasCmdr.inspect_plan_windows("01")
    assert result["complete"] is False
    assert result["windows"] == []
    assert reader.reads == [(100, 4096)]


def test_reused_window_handle_is_detected_before_text_read(reader, monkeypatch):
    owners = iter([10, 20])
    monkeypatch.setattr(reader, "pid", lambda _hwnd: next(owners))
    result = RasCmdr.inspect_plan_windows("01")
    assert result["complete"] is False
    assert reader.reads == []
    assert "window identity changed" in result["query_errors"][0]["detail"]


def test_unreadable_owned_identity_fails_closed(reader, monkeypatch):
    def denied(_pid):
        raise psutil.AccessDenied(10)

    monkeypatch.setattr(psutil, "Process", denied)
    result = RasCmdr.inspect_plan_windows("01")
    assert result["complete"] is False
    assert result["windows"] == []
    assert reader.reads == []


def test_runtime_path_change_cannot_grant_window_access(reader, monkeypatch):
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(
        create_time=lambda: 1000.0, exe=lambda: "C:/other/Ras.exe",
    ))
    assert RasCmdr.inspect_plan_windows("01")["complete"] is False
    assert reader.reads == []


def test_total_title_and_caption_budget_is_bounded(reader):
    result = RasCmdr.inspect_plan_windows("01", max_text_chars=10)
    window = result["windows"][0]
    assert result["complete"] is True
    assert result["text_budget_exhausted"] is True
    assert window["title"] == "Error"
    assert window["controls"][0]["text"] == "Solve"
    assert reader.reads == [(100, 10), (101, 5)]


def test_no_matches_requires_no_ui_backend(monkeypatch):
    monkeypatch.setattr(RasCmdr, "inspect_plan_processes", lambda *_a, **_k: _inventory(matched=False))
    monkeypatch.setattr(_plan_windows, "_WindowsUi", lambda: pytest.fail("No owned process"))
    result = RasCmdr.inspect_plan_windows("01")
    assert result["complete"] is True
    assert result["windows"] == []


@pytest.mark.parametrize("maximum", [True, 0, -1, 65537, 1.5, "4096"])
def test_invalid_text_budget_rejected(maximum):
    with pytest.raises(ValueError, match="max_text_chars"):
        RasCmdr.inspect_plan_windows("01", max_text_chars=maximum)


@pytest.mark.parametrize("class_name", ["Edit", "RichTextWndClass"])
def test_editable_control_exposes_only_skipped_class_style(reader, monkeypatch, class_name):
    original = reader.class_name
    monkeypatch.setattr(reader, "class_name", lambda hwnd: class_name if hwnd == 103 else original(hwnd))
    result = RasCmdr.inspect_plan_windows("01")
    skipped = result["windows"][0]["skipped_controls"]
    assert skipped == [{
        "hwnd": 103, "pid": 10, "create_time": 1000.0,
        "class_name": class_name, "style": 0, "reason_code": "editable_control",
    }]
    assert all(hwnd != 103 for hwnd, _maximum in reader.reads)


@pytest.mark.parametrize("class_name", ["Edit", "RichTextWndClass"])
def test_readonly_nonpassword_edit_text_is_read_under_budget(reader, monkeypatch, class_name):
    original_class = reader.class_name
    monkeypatch.setattr(reader, "class_name", lambda hwnd: class_name if hwnd == 103 else original_class(hwnd))
    original = reader.text
    monkeypatch.setattr(reader, "style", lambda hwnd: 0x0800 if hwnd == 103 else 0)

    def text(hwnd, maximum):
        if hwnd == 103:
            reader.reads.append((hwnd, maximum))
            return "Actual solver error"[:maximum]
        return original(hwnd, maximum)

    monkeypatch.setattr(reader, "text", text)
    result = RasCmdr.inspect_plan_windows("01", max_text_chars=40)
    controls = result["windows"][0]["controls"]
    assert result["complete"] is True
    assert controls[-1]["control_type"] == "readonly_edit"
    assert controls[-1]["text"] == "Actual s"
    assert sum(len(row["text"]) for row in controls) + len(result["windows"][0]["title"]) == 40


@pytest.mark.parametrize("class_name", ["Edit", "RichTextWndClass"])
def test_password_edit_is_never_read_even_when_readonly(reader, monkeypatch, class_name):
    original_class = reader.class_name
    monkeypatch.setattr(reader, "class_name", lambda hwnd: class_name if hwnd == 103 else original_class(hwnd))
    monkeypatch.setattr(reader, "style", lambda hwnd: 0x0820 if hwnd == 103 else 0)
    result = RasCmdr.inspect_plan_windows("01")
    skipped = result["windows"][0]["skipped_controls"][0]
    assert skipped["reason_code"] == "password_control"
    assert skipped["style"] == 0x0820
    assert "text" not in skipped
    assert all(hwnd != 103 for hwnd, _maximum in reader.reads)


def test_edit_style_change_before_body_read_fails_closed(reader, monkeypatch):
    styles = iter([0x0800, 0])
    monkeypatch.setattr(reader, "style", lambda hwnd: next(styles) if hwnd == 103 else 0)
    result = RasCmdr.inspect_plan_windows("01")
    assert result["complete"] is False and result["windows"] == []
    assert all(hwnd != 103 for hwnd, _maximum in reader.reads)


def test_listbox_message_strings_are_read_without_selection(reader, monkeypatch):
    original = reader.class_name
    monkeypatch.setattr(reader, "class_name", lambda hwnd: "ListBox" if hwnd == 103 else original(hwnd))
    calls = []

    def listbox(hwnd, maximum, guard):
        guard()
        calls.append((hwnd, maximum))
        return {"text": "Actual solver failure", "item_count": 2, "items_read": 1}

    monkeypatch.setattr(reader, "listbox_text", listbox, raising=False)
    result = RasCmdr.inspect_plan_windows("01")
    control = result["windows"][0]["controls"][-1]
    assert result["complete"] is True
    assert control["control_type"] == "listbox"
    assert control["text"] == "Actual solver failure"
    assert calls == [(103, 4064)]
    assert reader.actions == []


def test_owner_draw_listbox_without_strings_is_metadata_only(reader, monkeypatch):
    original = reader.class_name
    monkeypatch.setattr(reader, "class_name", lambda hwnd: "ListBox" if hwnd == 103 else original(hwnd))
    monkeypatch.setattr(reader, "style", lambda hwnd: 0x0010 if hwnd == 103 else 0)
    monkeypatch.setattr(reader, "listbox_text", lambda *_a: pytest.fail("Item data is not text"), raising=False)
    result = RasCmdr.inspect_plan_windows("01")
    assert result["windows"][0]["skipped_controls"][0]["reason_code"] == "owner_draw_listbox_without_strings"


@pytest.mark.parametrize(("name", "style", "kind"), [
    ("ListBox", 0, "listbox"), ("ListBox", 0x0050, "listbox"),
    ("WindowsForms10.LISTBOX.app.0.demo", 0, "listbox"),
    ("ThunderRT6ListBox", 0, "listbox"),
    ("Edit", 0x0800, "readonly_edit"),
    ("RichEdit20W", 0x0800, "readonly_edit"),
    ("RichTextWndClass", 0x56A008C4, "readonly_edit"),
    ("RICHTEXTWNDCLASS", 0x0800, "readonly_edit"),
    ("ThunderRT6TextBox", 1409351872, None),
    ("WindowsForms10.EDIT.app.0.demo", 0x0800, "readonly_edit"),
    ("SysTreeView32", 0, None),
])
def test_control_kinds_are_explicit(name, style, kind):
    assert _plan_windows._control_kind(name, style)[0] == kind


def test_native_listbox_queries_tail_strings_and_global_budget_only(monkeypatch):
    ui = object.__new__(_plan_windows._WindowsUi)
    values = ["hello", "world", "bad"]
    events = []

    def message(hwnd, opcode, index=0, pointer=0):
        events.append(opcode)
        if opcode == 0x018B:
            return len(values)
        if opcode == 0x018A:
            return len(values[index])
        assert opcode == 0x0189
        buffer = ctypes.create_unicode_buffer(values[index])
        ctypes.memmove(pointer, buffer, ctypes.sizeof(buffer))
        return len(values[index])

    monkeypatch.setattr(ui, "_message", message)
    result = ui.listbox_text(103, 9, lambda: events.append("guard"))
    assert result["text"] == "world\nbad"
    assert result["items_read"] == 2 and result["items_truncated"] is True
    assert result["skipped_item_lengths"] == [{"index": 0, "length": 5}]
    assert set(event for event in events if event != "guard") == {0x0189, 0x018A, 0x018B}
    for index, event in enumerate(events):
        if event == 0x0189:
            assert events[index - 1] == "guard" and events[index + 1] == "guard"


def test_native_listbox_oversized_item_text_is_not_read(monkeypatch):
    ui = object.__new__(_plan_windows._WindowsUi)

    def message(_hwnd, opcode, *_args):
        if opcode == 0x018B:
            return 1
        assert opcode == 0x018A, "Oversized LB_GETTEXT must not be issued"
        return 1000

    monkeypatch.setattr(ui, "_message", message)
    result = ui.listbox_text(103, 10, lambda: None)
    assert result["text"] == ""
    assert result["skipped_item_lengths"] == [{"index": 0, "length": 1000}]


@pytest.mark.parametrize("unicode", [False, True])
def test_native_text_matches_window_encoding_and_preserves_character_budget(monkeypatch, unicode):
    ui = object.__new__(_plan_windows._WindowsUi)
    ui.api = SimpleNamespace(IsWindowUnicode=lambda hwnd: unicode)
    ui.ansi_encoding = "cp1252"
    calls = []

    def message(hwnd, opcode, capacity, pointer, **kwargs):
        calls.append((hwnd, opcode, capacity, kwargs))
        value = "Caf\u00e9 solver error"
        buffer = (ctypes.create_unicode_buffer(value) if unicode
                  else ctypes.create_string_buffer(value.encode("cp1252")))
        ctypes.memmove(pointer, buffer, min(ctypes.sizeof(buffer), capacity * (ctypes.sizeof(ctypes.c_wchar) if unicode else 1)))
        return len(value)

    monkeypatch.setattr(ui, "_message", message)
    assert ui.text(103, 8) == "Caf\u00e9 sol"
    assert calls == [(103, 0x000D, 9 if unicode else 33, {"unicode": unicode})]


@pytest.mark.parametrize("unicode", [False, True])
def test_native_message_timeout_has_owned_handle_opcode_and_bounded_duration(monkeypatch, unicode):
    ui = object.__new__(_plan_windows._WindowsUi)
    calls = []

    def message(*args):
        calls.append(args)
        return 0

    ui.api = SimpleNamespace(SendMessageTimeoutW=message, SendMessageTimeoutA=message)
    monkeypatch.setattr(ctypes, "set_last_error", lambda _value: None, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 1460, raising=False)
    with pytest.raises(OSError, match=r"hwnd=103 message=0x000D encoding=.*timeout_ms=1000"):
        ui._message(103, 0x000D, unicode=unicode)
    assert calls[0][5] == 1000


def test_owned_text_failure_records_control_metadata_without_partial_text(reader, monkeypatch):
    original = reader.text

    def fail(hwnd, maximum):
        if hwnd == 101:
            raise OSError(1460, "Cannot query owned window text hwnd=101 message=0x000D")
        return original(hwnd, maximum)

    monkeypatch.setattr(reader, "text", fail)
    result = RasCmdr.inspect_plan_windows("01")
    assert result["complete"] is False and result["windows"] == []
    assert result["query_errors"][0]["owned_control"] == {
        "hwnd": 101, "pid": 10, "create_time": 1000.0,
        "class_name": "Static", "style": 0,
    }


def test_top_level_cached_caption_does_not_message_unresponsive_ui(reader, monkeypatch):
    captions = []
    original = reader.text

    def caption(hwnd, maximum):
        captions.append((hwnd, maximum))
        return "RAS"

    def text(hwnd, maximum):
        assert hwnd != 100, "Top-level WM_GETTEXT would hang"
        return original(hwnd, maximum)

    monkeypatch.setattr(reader, "caption", caption)
    monkeypatch.setattr(reader, "text", text)
    result = RasCmdr.inspect_plan_windows("01", max_text_chars=12)
    assert result["complete"] is True
    assert captions == [(100, 12)]
    assert result["windows"][0]["title"] == "RAS"
    assert result["windows"][0]["controls"][0]["text"] == "Solver co"
    assert sum(len(c["text"]) for c in result["windows"][0]["controls"]) + 3 == 12


def test_native_cached_caption_uses_only_bounded_getwindowtext(monkeypatch):
    ui = object.__new__(_plan_windows._WindowsUi)
    calls = []

    def caption(hwnd, buffer, capacity):
        calls.append((hwnd, capacity))
        buffer.value = "RAS"[:capacity - 1]
        return len(buffer.value)

    ui.api = SimpleNamespace(GetWindowTextW=caption)
    monkeypatch.setattr(ctypes, "set_last_error", lambda _value: None, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 0, raising=False)
    assert ui.caption(100, 2) == "RA"
    assert calls == [(100, 3)]
