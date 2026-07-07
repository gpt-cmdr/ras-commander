"""Logging regressions for GUI automation helpers."""

import ctypes
import logging
from types import SimpleNamespace

import pytest

from ras_commander.gui.workflow_base import WorkflowExecutor, WorkflowStep


def _messages(caplog, logger_name, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == logger_name and record.levelno == level
    ]


def test_workflow_executor_step_chatter_is_debug_only(caplog):
    def action(context):
        context["ran"] = True
        return "ok"

    context = {}
    with caplog.at_level(logging.DEBUG, logger="ras_commander.gui.workflow_base"):
        result = WorkflowExecutor.execute(
            [WorkflowStep(name="NoisyStep", action=action)],
            context,
            workflow_name="TestWorkflow",
        )

    assert result.success is True
    assert context["ran"] is True
    info = _messages(caplog, "ras_commander.gui.workflow_base", logging.INFO)
    debug = _messages(caplog, "ras_commander.gui.workflow_base", logging.DEBUG)

    assert "Starting TestWorkflow (1 steps)" in info
    assert any("TestWorkflow completed successfully" in message for message in info)
    assert not any("[1/1] NoisyStep" in message for message in info)
    assert any("[1/1] NoisyStep" in message for message in debug)


def test_win32_button_success_is_debug_not_info(monkeypatch, caplog):
    from ras_commander.gui import win32_primitives as primitives

    monkeypatch.setattr(
        primitives,
        "win32api",
        SimpleNamespace(SendMessage=lambda *args: None),
    )
    monkeypatch.setattr(primitives, "win32con", SimpleNamespace(BM_CLICK=1))
    monkeypatch.setattr(
        primitives,
        "win32gui",
        SimpleNamespace(GetWindowText=lambda hwnd: "Compute"),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.gui.win32_primitives"):
        assert primitives.Win32Primitives.click_button(1234) is True

    info = _messages(caplog, "ras_commander.gui.win32_primitives", logging.INFO)
    debug = _messages(caplog, "ras_commander.gui.win32_primitives", logging.DEBUG)

    assert info == []
    assert any("Clicked button: Compute" in message for message in debug)


def test_screenshot_saved_info_uses_filename_and_debug_keeps_path(
    tmp_path, monkeypatch, caplog
):
    Image = pytest.importorskip("PIL.Image")
    from ras_commander.gui import screenshots as screenshots_module

    output_path = tmp_path / "screens" / "window.png"
    fake_win32gui = SimpleNamespace(
        IsWindow=lambda hwnd: True,
        IsIconic=lambda hwnd: False,
        GetWindowText=lambda hwnd: "Test Window",
        GetWindowRect=lambda hwnd: (10, 20, 20, 30),
    )
    monkeypatch.setattr(screenshots_module, "win32gui", fake_win32gui)
    monkeypatch.setattr(
        screenshots_module.RasScreenshot,
        "_check_dependencies",
        staticmethod(lambda: (True, "ok")),
    )
    monkeypatch.setattr(
        screenshots_module.RasScreenshot,
        "_get_dwm_extended_frame_bounds",
        staticmethod(lambda hwnd: (10, 20, 20, 30)),
    )
    monkeypatch.setattr(
        screenshots_module.RasScreenshot,
        "_bring_window_to_front",
        staticmethod(lambda hwnd: True),
    )
    monkeypatch.setattr(
        screenshots_module.RasScreenshot,
        "_capture_screen_rect",
        staticmethod(lambda rect: Image.new("RGB", (10, 10))),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.gui.screenshots"):
        result = screenshots_module.RasScreenshot.capture_window(1234, output_path)

    assert result == output_path
    assert output_path.exists()
    info = _messages(caplog, "ras_commander.gui.screenshots", logging.INFO)
    debug = _messages(caplog, "ras_commander.gui.screenshots", logging.DEBUG)

    assert "Screenshot saved: window.png" in info
    assert str(tmp_path) not in "\n".join(info)
    assert any(str(output_path) in message for message in debug)


def test_treeview_high_level_helper_does_not_print(monkeypatch, capsys, caplog):
    if not hasattr(ctypes, "windll"):
        pytest.skip("treeview_automation requires Windows ctypes.windll")

    from ras_commander.gui import treeview_automation as treeview

    monkeypatch.setattr(treeview, "find_ras_mapper_window", lambda: 0)

    with caplog.at_level(logging.DEBUG, logger="ras_commander.gui.treeview_automation"):
        assert treeview.find_and_right_click("Geometry") is False

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    debug = _messages(caplog, "ras_commander.gui.treeview_automation", logging.DEBUG)
    assert any("Could not find RAS Mapper window" in message for message in debug)
