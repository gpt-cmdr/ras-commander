import io
import logging
import sys
import types
import zipfile
from pathlib import Path

import requests

county_module = types.ModuleType("ras_commander.sources.county")
county_module.M3Model = object
sys.modules.setdefault("ras_commander.sources.county", county_module)

import ras_commander.sources.federal.ebfe_models as ebfe_module
import ras_commander.sources.federal.usgs_sciencebase as sciencebase_module
from ras_commander.sources.federal.ebfe_models import RasEbfeModels
from ras_commander.sources.federal.usgs_sciencebase import UsgsScienceBase


class DummyTqdm:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.iterable = args[0] if args else []
        self.progress = kwargs.get("initial", 0)

    def __iter__(self):
        yield from self.iterable

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_postfix(self, **kwargs):
        self.postfix = kwargs

    def update(self, amount):
        self.progress += amount


class FakeResponse:
    def __init__(self, body, status_code=200, headers=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def close(self):
        self.closed = True


def _zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_obj:
        for path, content in files.items():
            zip_obj.writestr(path, content)
    return buffer.getvalue()


def test_sciencebase_progress_is_quiet_by_default(monkeypatch):
    calls = []

    def fake_tqdm(*args, **kwargs):
        calls.append(kwargs)
        return DummyTqdm(*args, **kwargs)

    monkeypatch.setattr(sciencebase_module, "tqdm", fake_tqdm)

    assert list(UsgsScienceBase._progress(["query"], desc="Search")) == ["query"]
    assert calls[-1]["disable"] is True

    assert list(
        UsgsScienceBase._progress(["query"], desc="Search", show_progress=True)
    ) == ["query"]
    assert calls[-1]["disable"] is False


def test_sciencebase_verbose_summary_uses_logging_not_stdout(
    monkeypatch,
    capsys,
    caplog,
):
    captured_kwargs = []

    def fake_keyword_search(**kwargs):
        captured_kwargs.append(kwargs)
        return {
            "candidate-1": {
                "model_type_guess": "HEC-RAS",
                "confidence": "high",
                "ras_version_guess": "6.6",
            }
        }

    monkeypatch.setattr(
        UsgsScienceBase,
        "_discover_keyword_search",
        staticmethod(fake_keyword_search),
    )

    with caplog.at_level(logging.INFO, logger=sciencebase_module.logger.name):
        candidates = UsgsScienceBase.discover_models(
            strategies=["keyword"], verbose=True,
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert list(candidates) == ["candidate-1"]
    assert captured_kwargs[0]["show_progress"] is False
    assert "Discovered 1 candidate ScienceBase models" in caplog.text


def test_ebfe_emit_defaults_to_debug_not_stdout(capsys, caplog, tmp_path):
    with caplog.at_level(logging.DEBUG, logger=ebfe_module.logger.name):
        RasEbfeModels._emit("Output:", tmp_path / "organized")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert "Output:" in caplog.text
    assert str(tmp_path / "organized") in caplog.text


def test_ebfe_progress_is_quiet_by_default(monkeypatch):
    calls = []

    def fake_tqdm(*args, **kwargs):
        calls.append(kwargs)
        return DummyTqdm(*args, **kwargs)

    monkeypatch.setattr(ebfe_module, "tqdm", fake_tqdm)

    assert list(RasEbfeModels._progress(["component"])) == ["component"]
    assert calls[-1]["disable"] is True

    with RasEbfeModels._output_options(show_progress=True):
        assert list(RasEbfeModels._progress(["component"])) == ["component"]
    assert calls[-1]["disable"] is False


def test_ebfe_organize_model_is_quiet_by_default_but_verbose_opt_in(
    monkeypatch,
    capsys,
    tmp_path,
):
    def fake_organizer(downloaded_folder=None, output_folder=None):
        RasEbfeModels._emit("Organizing dummy model")
        RasEbfeModels._emit(f"Output: {output_folder}")
        return Path(output_folder)

    monkeypatch.setitem(
        RasEbfeModels._MODEL_REGISTRY,
        "dummy",
        {
            "study_area": "Dummy",
            "huc8": "00000000",
            "organizer": "_dummy_organizer",
            "download_subdir": "dummy_download",
            "output_name": "Dummy",
            "ras_version": "6.6",
            "notes": "Test model.",
        },
    )
    monkeypatch.setitem(RasEbfeModels._MODEL_ALIASES, "dummy", "dummy")
    monkeypatch.setattr(
        RasEbfeModels, "_dummy_organizer", staticmethod(fake_organizer), raising=False,
    )

    organized = RasEbfeModels.organize_model(
        "dummy",
        downloaded_folder=tmp_path / "download",
        output_folder=tmp_path / "organized",
    )
    captured = capsys.readouterr()
    assert organized == tmp_path / "organized"
    assert captured.out == ""
    assert captured.err == ""

    RasEbfeModels.organize_model(
        "dummy",
        downloaded_folder=tmp_path / "download",
        output_folder=tmp_path / "organized",
        verbose=True,
    )
    captured = capsys.readouterr()
    assert "Organizing dummy model" in captured.out
    assert str(tmp_path / "organized") in captured.out


def test_ebfe_download_extract_helper_emits_no_stdout_by_default(
    monkeypatch,
    capsys,
    tmp_path,
):
    zip_bytes = _zip_bytes({"nested/test.txt": "hello"})
    tqdm_calls = []

    def fake_get(url, **kwargs):
        return FakeResponse(
            zip_bytes,
            headers={"content-length": str(len(zip_bytes))},
        )

    def fake_tqdm(*args, **kwargs):
        tqdm_calls.append(kwargs)
        return DummyTqdm(*args, **kwargs)

    monkeypatch.setattr(ebfe_module.requests, "get", fake_get)
    monkeypatch.setattr(ebfe_module, "tqdm", fake_tqdm)

    extracted = RasEbfeModels._download_and_extract(
        url="https://example.com/archive.zip",
        output_folder=tmp_path,
        description="Archive",
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert extracted == tmp_path / "archive_extracted"
    assert (extracted / "nested" / "test.txt").read_text(encoding="utf-8") == "hello"
    assert tqdm_calls
    assert all(call["disable"] is True for call in tqdm_calls)
