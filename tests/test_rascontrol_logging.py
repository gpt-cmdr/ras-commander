import importlib
import logging
from types import SimpleNamespace

import h5py
import pandas as pd
import pytest


rascontrol_module = importlib.import_module("ras_commander.RasControl")
RasControl = rascontrol_module.RasControl
ProjectInfo = rascontrol_module.ProjectInfo


def test_registered_versions_use_their_exact_controllers():
    assert RasControl.VERSION_MAP["4.0"] == "RAS400.HECRASController"
    assert RasControl.VERSION_MAP["40"] == "RAS400.HECRASController"
    assert RasControl.VERSION_MAP["4.1.0"] == "RAS41.HECRASController"
    assert RasControl.VERSION_MAP["5.0"] == "RAS500.HECRASController"
    assert RasControl.VERSION_MAP["50"] == "RAS500.HECRASController"
    assert RasControl.VERSION_MAP["6.1"] == "RAS610.HECRASController"
    assert RasControl.VERSION_MAP["61"] == "RAS610.HECRASController"
    assert RasControl.VERSION_MAP["6.2"] == "RAS620.HECRASController"
    assert RasControl.VERSION_MAP["62"] == "RAS620.HECRASController"
    assert RasControl.VERSION_MAP["6.3"] == "RAS630.HECRASController"
    assert RasControl.VERSION_MAP["63"] == "RAS630.HECRASController"


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
        lambda project_path, before_snapshot: (None, None, 0, None, None),
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_create_session_lock",
        lambda session_id, lock_data: tmp_path / "session.lock",
    )
    monkeypatch.setattr(
        rascontrol_module,
        "_cleanup_session",
        lambda session_id: (
            rascontrol_module._active_sessions.pop(session_id, None),
            rascontrol_module._SessionCleanupResult(
                session_id=session_id,
                ras_pid=1234,
                identity_state="absent",
            ),
        )[1],
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


def test_get_comp_msgs_empty_bco_falls_back_to_hdf(monkeypatch, tmp_path):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    (tmp_path / "Demo.bco01").write_bytes(b"")
    (tmp_path / "Demo.p01.hdf").write_bytes(b"hdf placeholder")

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
    monkeypatch.setattr(
        RasControl,
        "_read_hdf_comp_msgs",
        staticmethod(lambda hdf_file: "messages from hdf"),
    )

    assert RasControl.get_comp_msgs("01") == "messages from hdf"


def test_get_comp_msgs_empty_text_sidecar_preserves_empty_result(
    monkeypatch,
    tmp_path,
):
    project_path = tmp_path / "Demo.prj"
    project_path.write_text("Proj Title=Demo\n", encoding="utf-8")
    (tmp_path / "Demo.p01.comp_msgs.txt").write_bytes(b"")
    (tmp_path / "Demo.p01.hdf").write_bytes(b"hdf placeholder")

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
    monkeypatch.setattr(
        RasControl,
        "_read_hdf_comp_msgs",
        staticmethod(
            lambda hdf_file: (_ for _ in ()).throw(
                AssertionError("empty text sidecar must not fall back")
            )
        ),
    )

    assert RasControl.get_comp_msgs("01") == ""


@pytest.mark.parametrize("input_kind", ["hdf", "plan", "number", "project"])
@pytest.mark.parametrize("sidecar", ["Demo.p01.comp_msgs.txt", "Demo.p01.computeMsgs.txt", "Demo.bco01"])
def test_exact_stored_messages_support_file_and_project_inputs(
    monkeypatch, tmp_path, input_kind, sidecar
):
    project = tmp_path / "Demo.prj"
    project.write_text("Proj Title=Demo\nCurrent Plan=p01\n", encoding="ascii")
    plan = tmp_path / "Demo.p01"
    plan.write_text("Plan Title=Plan 01\n", encoding="ascii")
    hdf = tmp_path / "Demo.p01.hdf"
    with h5py.File(hdf, "w") as source:
        source.create_group("Plan Data/Plan Information")
    (tmp_path / sidecar).write_bytes(b"Complete Process\r\n")
    # A neighboring plan/project must never supply the selected messages.
    (tmp_path / "Demo.p02.comp_msgs.txt").write_text("wrong plan", encoding="ascii")
    (tmp_path / "DemoExtra.p01.comp_msgs.txt").write_text("wrong project", encoding="ascii")
    ras_object = SimpleNamespace(
        prj_file=project, ras_version="6.6",
        plan_df=pd.DataFrame([{"plan_number": "01", "Plan Title": "Plan 01"}]),
    )
    monkeypatch.setattr(rascontrol_module, "ras", SimpleNamespace())
    monkeypatch.setattr(
        RasControl, "_com_open_close",
        staticmethod(lambda *_a, **_k: pytest.fail("Message inspection must never open COM")),
    )
    if input_kind in {"hdf", "plan"}:
        monkeypatch.setattr(
            RasControl, "_get_project_info",
            staticmethod(lambda *_a, **_k: pytest.fail("File inputs must not consult project metadata")),
        )
        selected = hdf if input_kind == "hdf" else plan
        assert RasControl.get_comp_msgs(selected) == "Complete Process\n"
    else:
        selected = "01" if input_kind == "number" else project
        assert RasControl.get_comp_msgs(selected, ras_object=ras_object) == "Complete Process\n"
    candidates = RasControl._read_stored_comp_msgs(hdf, hash_file=True)
    assert len(candidates) == 1
    assert candidates[0].path == tmp_path / sidecar
    assert candidates[0].source_sha256 is not None
    from ras_commander.RasCurrency import RasCurrency
    assert RasCurrency.check_plan_hdf_complete(hdf) is True


@pytest.mark.parametrize("embedded", [None, b"Complete Process\r\n", [b"Complete Process\r\n"]])
def test_direct_hdf_message_fallback_is_nonrecursive(monkeypatch, tmp_path, embedded):
    hdf = tmp_path / "Only.p01.hdf"
    with h5py.File(hdf, "w") as source:
        source.create_group("Plan Data/Plan Information")
        if embedded is not None:
            source.create_dataset("Results/Summary/Compute Messages (text)", data=embedded)
    monkeypatch.setattr(rascontrol_module, "ras", SimpleNamespace())
    from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan
    expected = "" if embedded is None else "Complete Process\r\n"
    assert RasControl.get_comp_msgs(hdf) == expected
    assert HdfResultsPlan.get_compute_messages(hdf) == expected


def test_direct_plan_messages_reject_outside_sidecar_symlink(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "other-project-messages.txt"
    outside.write_text("Complete Process", encoding="ascii")
    sidecar = project_dir / "Demo.p01.comp_msgs.txt"
    try:
        sidecar.symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit filesystem symlinks")
    with pytest.raises(ValueError, match="escapes the project folder"):
        RasControl.get_comp_msgs(project_dir / "Demo.p01.hdf")


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
