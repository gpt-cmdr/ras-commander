import logging
import importlib
import io
import types
import zipfile
from pathlib import Path

import pandas as pd
import pytest
import requests

from ras_commander.RasExamples import RasExamples


LOGGER_NAME = "ras_commander.RasExamples"
rasexamples_module = importlib.import_module("ras_commander.RasExamples")


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


def _set_project_catalog(monkeypatch, tmp_path, project_name="MiniProject"):
    zip_path = tmp_path / "Example_Projects_7_0.zip"
    with zipfile.ZipFile(zip_path, "w") as zip_ref:
        zip_ref.writestr(f"Category/{project_name}/{project_name}.prj", "Proj Title=Mini\n")

    monkeypatch.setattr(
        RasExamples,
        "_folder_df",
        pd.DataFrame([{"Category": "Category", "Project": project_name}]),
    )
    monkeypatch.setattr(RasExamples, "_zip_file_path", zip_path)
    return zip_path


def test_extract_project_success_info_is_concise_debug_has_full_path(
    monkeypatch,
    tmp_path,
    caplog,
):
    _set_project_catalog(monkeypatch, tmp_path)
    output_path = tmp_path / "out"

    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    extracted = RasExamples.extract_project("MiniProject", output_path=output_path)

    info_text = "\n".join(_messages(caplog, logging.INFO))
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))

    assert extracted == output_path / "MiniProject"
    assert "Successfully extracted project 'MiniProject' to MiniProject" in info_text
    assert str(output_path) not in info_text
    assert f"Full extracted project path: {extracted}" in debug_text
    assert "Calling extract_project" in debug_text


def test_regular_extraction_error_includes_target_path(
    monkeypatch,
    tmp_path,
    caplog,
):
    zip_path = tmp_path / "not_a_zip.zip"
    zip_path.write_text("not a zip", encoding="utf-8")
    monkeypatch.setattr(
        RasExamples,
        "_folder_df",
        pd.DataFrame([{"Category": "Category", "Project": "MiniProject"}]),
    )
    monkeypatch.setattr(RasExamples, "_zip_file_path", zip_path)
    output_path = tmp_path / "out"
    expected_target = output_path / "MiniProject"

    caplog.set_level(logging.ERROR, logger=LOGGER_NAME)

    with pytest.raises(RuntimeError):
        RasExamples.extract_project("MiniProject", output_path=output_path)

    error_text = "\n".join(_messages(caplog, logging.ERROR))
    assert "An error occurred while extracting project 'MiniProject'" in error_text
    assert str(expected_target) in error_text


def test_get_example_projects_download_error_includes_url_and_target(
    monkeypatch,
    tmp_path,
    caplog,
):
    user_data_dir = tmp_path / "ras_examples"
    monkeypatch.setattr(RasExamples, "_user_data_dir", user_data_dir)

    def fail_get(*_args, **_kwargs):
        raise requests.exceptions.RequestException("offline")

    monkeypatch.setattr(requests, "get", fail_get)

    caplog.set_level(logging.ERROR, logger=LOGGER_NAME)

    with pytest.raises(requests.exceptions.RequestException):
        RasExamples.get_example_projects("7.0")

    target_zip = user_data_dir / "Example_Projects_7_0.zip"
    error_text = "\n".join(_messages(caplog, logging.ERROR))
    assert "Failed to download HEC-RAS example projects version 7.0" in error_text
    assert "Example_Projects_7_0.zip" in error_text
    assert str(target_zip) in error_text
    assert "offline" in error_text


def test_clean_projects_directory_error_includes_target_path(
    monkeypatch,
    tmp_path,
    caplog,
):
    projects_dir = tmp_path / "example_projects"
    projects_dir.mkdir()
    monkeypatch.setattr(RasExamples, "projects_dir", projects_dir)
    monkeypatch.setattr(
        rasexamples_module.shutil,
        "rmtree",
        lambda _path: (_ for _ in ()).throw(PermissionError("locked")),
    )

    caplog.set_level(logging.ERROR, logger=LOGGER_NAME)

    RasExamples.clean_projects_directory()

    error_text = "\n".join(_messages(caplog, logging.ERROR))
    assert "Failed to remove projects directory" in error_text
    assert str(projects_dir) in error_text
    assert "locked" in error_text


def test_download_file_with_progress_is_quiet_at_info(
    monkeypatch,
    tmp_path,
    caplog,
    capsys,
):
    tqdm_calls = []
    updates = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            assert chunk_size == 8192
            yield b"ab"
            yield b"cd"

    class FakeTqdm:
        def __init__(self, **kwargs):
            tqdm_calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, size):
            updates.append(size)

    monkeypatch.setattr(
        rasexamples_module.requests,
        "get",
        lambda url, stream: FakeResponse(),
    )
    monkeypatch.setattr(rasexamples_module, "tqdm", FakeTqdm)
    monkeypatch.setattr(
        rasexamples_module.sys,
        "stderr",
        types.SimpleNamespace(isatty=lambda: True),
    )
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    downloaded = RasExamples._download_file_with_progress(
        "https://example.invalid/file.zip",
        tmp_path,
        file_size=4,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert downloaded == tmp_path / "file.zip"
    assert downloaded.read_bytes() == b"abcd"
    assert updates == [2, 2]
    assert _messages(caplog, logging.INFO) == []
    assert tqdm_calls == [
        {
            "desc": "file.zip",
            "total": 4,
            "unit": "iB",
            "unit_scale": True,
            "unit_divisor": 1024,
            "leave": False,
            "disable": True,
        }
    ]


def test_special_project_info_is_concise_debug_keeps_details(
    monkeypatch,
    tmp_path,
    caplog,
    capsys,
):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_ref:
        zip_ref.writestr("SpecialProject.prj", "Proj Title=Special\n")
    zip_bytes = zip_buffer.getvalue()
    tqdm_calls = []

    class FakeResponse:
        headers = {"content-length": str(len(zip_bytes))}

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            assert chunk_size == 8192
            yield zip_bytes

    class FakeTqdm:
        def __init__(self, **kwargs):
            tqdm_calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, _size):
            pass

    url = "https://example.invalid/special.zip"
    monkeypatch.setattr(RasExamples, "SPECIAL_PROJECTS", {"SpecialProject": url})
    monkeypatch.setattr(
        rasexamples_module.requests,
        "get",
        lambda request_url, stream, timeout: FakeResponse(),
    )
    monkeypatch.setattr(rasexamples_module, "tqdm", FakeTqdm)
    monkeypatch.setattr(
        rasexamples_module.sys,
        "stderr",
        types.SimpleNamespace(isatty=lambda: False),
    )
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    project_path = RasExamples._extract_special_project(
        "SpecialProject",
        output_path=tmp_path,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert (project_path / "SpecialProject.prj").exists()

    info_text = "\n".join(_messages(caplog, logging.INFO))
    debug_text = "\n".join(_messages(caplog, logging.DEBUG))
    assert "Downloading special project 'SpecialProject'..." in info_text
    assert (
        "Successfully extracted special project 'SpecialProject' to SpecialProject"
        in info_text
    )
    assert str(tmp_path) not in info_text
    assert url in debug_text
    assert str(tmp_path / "SpecialProject_temp.zip") in debug_text
    assert f"Full extracted special project path: {project_path}" in debug_text
    assert tqdm_calls[0]["leave"] is False
    assert tqdm_calls[0]["disable"] is True


def test_special_project_failure_logs_one_error(
    monkeypatch,
    tmp_path,
    caplog,
):
    url = "https://example.invalid/broken.zip"

    def fail_get(*_args, **_kwargs):
        raise requests.exceptions.RequestException("offline")

    monkeypatch.setattr(RasExamples, "SPECIAL_PROJECTS", {"BrokenSpecial": url})
    monkeypatch.setattr(
        RasExamples,
        "_folder_df",
        pd.DataFrame([{"Category": "Special", "Project": "BrokenSpecial"}]),
    )
    monkeypatch.setattr(RasExamples, "_zip_file_path", tmp_path / "unused.zip")
    monkeypatch.setattr(rasexamples_module.requests, "get", fail_get)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    with pytest.raises(RuntimeError):
        RasExamples.extract_project("BrokenSpecial", output_path=tmp_path)

    error_messages = _messages(caplog, logging.ERROR)
    debug_messages = _messages(caplog, logging.DEBUG)
    assert len(error_messages) == 1
    assert "Failed to download special project 'BrokenSpecial'" in error_messages[0]
    assert url in error_messages[0]
    assert not any(
        "Failed to extract special project 'BrokenSpecial':" in message
        for message in error_messages
    )
    assert any(
        "Special project 'BrokenSpecial' extraction failed after detailed error logging"
        in message
        for message in debug_messages
    )
