import io
import sys
import types
import zipfile

import requests

county_module = types.ModuleType("ras_commander.sources.county")
county_module.M3Model = object
sys.modules.setdefault("ras_commander.sources.county", county_module)
import ras_commander.sources.federal.ebfe_models as ebfe_module
from ras_commander.sources.federal.ebfe_models import RasEbfeModels


class DummyTqdm:
    def __init__(self, *args, **kwargs):
        self.total = kwargs.get("total")
        self.initial = kwargs.get("initial", 0)
        self.progress = self.initial

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

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


def _make_zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_obj:
        for path, content in files.items():
            zip_obj.writestr(path, content)
    return buffer.getvalue()


def test_download_and_extract_downloads_and_extracts(monkeypatch, tmp_path):
    zip_bytes = _make_zip_bytes({"nested/test.txt": "hello"})
    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return FakeResponse(
            zip_bytes,
            headers={"content-length": str(len(zip_bytes))}
        )

    monkeypatch.setattr(ebfe_module.requests, "get", fake_get)
    monkeypatch.setattr(ebfe_module, "tqdm", DummyTqdm)

    extracted = RasEbfeModels._download_and_extract(
        url="https://example.com/archive.zip",
        output_folder=tmp_path,
        description="Archive"
    )

    assert extracted == tmp_path / "archive_extracted"
    assert (extracted / "nested" / "test.txt").read_text(
        encoding="utf-8"
    ) == "hello"
    assert len(calls) == 1
    assert calls[0]["kwargs"].get("headers") is None


def test_download_file_resumes_partial_download(monkeypatch, tmp_path):
    zip_bytes = _make_zip_bytes({"file.txt": "resumed"})
    dest = tmp_path / "archive.zip"
    part_path = RasEbfeModels._get_partial_download_path(dest)
    resume_from = len(zip_bytes) // 2
    part_path.write_bytes(zip_bytes[:resume_from])
    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return FakeResponse(
            zip_bytes[resume_from:],
            status_code=206,
            headers={
                "content-length": str(len(zip_bytes) - resume_from),
                "content-range": (
                    f"bytes {resume_from}-{len(zip_bytes) - 1}/"
                    f"{len(zip_bytes)}"
                ),
            }
        )

    monkeypatch.setattr(ebfe_module.requests, "get", fake_get)
    monkeypatch.setattr(ebfe_module, "tqdm", DummyTqdm)

    downloaded = RasEbfeModels._download_file(
        url="https://example.com/archive.zip",
        dest=dest,
        description="Archive"
    )

    assert downloaded == dest
    assert dest.read_bytes() == zip_bytes
    assert not part_path.exists()
    assert calls[0]["kwargs"]["headers"] == {
        "Range": f"bytes={resume_from}-"
    }


def test_download_file_restarts_when_server_ignores_range(monkeypatch, tmp_path):
    zip_bytes = _make_zip_bytes({"file.txt": "restart"})
    dest = tmp_path / "archive.zip"
    part_path = RasEbfeModels._get_partial_download_path(dest)
    resume_from = len(zip_bytes) // 3
    part_path.write_bytes(zip_bytes[:resume_from])
    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return FakeResponse(
            zip_bytes,
            status_code=200,
            headers={"content-length": str(len(zip_bytes))}
        )

    monkeypatch.setattr(ebfe_module.requests, "get", fake_get)
    monkeypatch.setattr(ebfe_module, "tqdm", DummyTqdm)

    RasEbfeModels._download_file(
        url="https://example.com/archive.zip",
        dest=dest,
        description="Archive"
    )

    assert dest.read_bytes() == zip_bytes
    assert not part_path.exists()
    assert len(calls) == 2
    assert calls[0]["kwargs"]["headers"] == {
        "Range": f"bytes={resume_from}-"
    }
    assert "headers" not in calls[1]["kwargs"]


def test_download_and_extract_redownloads_corrupt_existing_zip(
    monkeypatch,
    tmp_path
):
    zip_path = tmp_path / "archive.zip"
    zip_path.write_bytes(b"not a real zip file")
    zip_bytes = _make_zip_bytes({"fixed.txt": "ok"})
    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return FakeResponse(
            zip_bytes,
            headers={"content-length": str(len(zip_bytes))}
        )

    monkeypatch.setattr(ebfe_module.requests, "get", fake_get)
    monkeypatch.setattr(ebfe_module, "tqdm", DummyTqdm)

    extracted = RasEbfeModels._download_and_extract(
        url="https://example.com/archive.zip",
        output_folder=tmp_path,
        description="Archive"
    )

    assert (extracted / "fixed.txt").read_text(encoding="utf-8") == "ok"
    assert len(calls) == 1
