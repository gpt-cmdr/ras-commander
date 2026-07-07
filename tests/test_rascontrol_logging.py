import importlib
import logging
from types import SimpleNamespace


rascontrol_module = importlib.import_module("ras_commander.RasControl")
RasControl = rascontrol_module.RasControl
ProjectInfo = rascontrol_module.ProjectInfo


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == level
        and record.name == "ras_commander.RasControl"
    ]


def test_com_open_close_logs_project_open_at_debug(
    monkeypatch,
    tmp_path,
    caplog,
):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    fake_com = SimpleNamespace(
        Project_Open=lambda path: None,
        QuitRas=lambda: None,
    )

    monkeypatch.setattr(
        rascontrol_module,
        "win32com",
        SimpleNamespace(
            client=SimpleNamespace(Dispatch=lambda com_string: fake_com)
        ),
    )
    monkeypatch.setattr(rascontrol_module.psutil, "process_iter", lambda attrs: [])
    monkeypatch.setattr(
        rascontrol_module,
        "_find_our_ras_process",
        lambda project_path, before_snapshot: (1234, 100),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_create_session_lock",
        lambda session_id, lock_data: tmp_path / "session.lock",
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_cleanup_session",
        lambda session_id: rascontrol_module._active_sessions.pop(session_id, None),
    )
    rascontrol_module._active_sessions.clear()

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasControl"):
        result = RasControl._com_open_close(
            project_path,
            "6.6",
            lambda com_rc: "operation result",
        )

    info_text = "\n".join(_messages(caplog, logging.INFO))
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert result == "operation result"
    assert "Opening project: Demo.prj" not in info_text
    assert str(tmp_path) not in info_text
    assert "Opening HEC-RAS:" in debug_text
    assert "Opening project: Demo.prj" in debug_text
    assert "Opening project path:" in debug_text
    assert str(project_path) in debug_text
    assert "Executing operation..." in debug_text
    assert "Operation completed successfully" in debug_text
    assert "Closing HEC-RAS..." in debug_text


def test_get_comp_msgs_logs_text_source_at_debug(
    monkeypatch,
    tmp_path,
    caplog,
):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    comp_msgs_file = tmp_path / "Demo.p01.comp_msgs.txt"
    comp_msgs_file.write_text("compute messages\n", encoding="utf-8")

    monkeypatch.setattr(
        RasControl,
        "_get_project_info",
        staticmethod(
            lambda plan, ras_object=None: ProjectInfo(
                project_path=project_path,
                version="6.6",
                plan_number="01",
                plan_name="Plan 01",
            )
        ),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasControl"):
        contents = RasControl.get_comp_msgs("01")

    info_text = "\n".join(_messages(caplog, logging.INFO))
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert contents == "compute messages\n"
    assert "Reading computation messages for plan 01 from comp_msgs file" not in info_text
    assert "Read 17 characters from comp_msgs file" not in info_text
    assert str(tmp_path) not in info_text
    assert "Reading computation messages for plan 01 from comp_msgs file" in debug_text
    assert "Read 17 characters from comp_msgs file" in debug_text
    assert str(comp_msgs_file) in debug_text


def test_failed_extraction_comp_msgs_full_text_is_debug(tmp_path, caplog):
    comp_msgs_file = tmp_path / "Demo.p01.comp_msgs.txt"
    comp_msgs = "line 1\nline 2\nline 3\n"

    with caplog.at_level(logging.DEBUG, logger="ras_commander.RasControl"):
        rascontrol_module._log_failed_extraction_comp_msgs(
            comp_msgs_file,
            comp_msgs,
        )

    error_text = "\n".join(_messages(caplog, logging.ERROR))
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert "Computation messages found for failed extraction: Demo.p01.comp_msgs.txt" in error_text
    assert "line 1" not in error_text
    assert str(comp_msgs_file) not in error_text
    assert str(comp_msgs_file) in debug_text
    assert comp_msgs in debug_text
