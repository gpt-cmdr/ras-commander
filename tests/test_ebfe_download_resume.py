import io
from datetime import datetime, timezone
import os
from pathlib import Path
import struct
import sys
import types
import zipfile

import pytest
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
    assert (
        extracted / RasEbfeModels._EXTRACTION_RECEIPT_NAME
    ).is_file()
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


def test_extract_component_rejects_partial_cache_without_modifying_it(tmp_path):
    zip_path = tmp_path / "archive.zip"
    zip_path.write_bytes(
        _make_zip_bytes({"one.txt": "one", "nested/two.txt": "two"})
    )
    destination = tmp_path / "archive_extracted"
    destination.mkdir()
    retained = destination / "one.txt"
    retained.write_text("one", encoding="utf-8")

    with pytest.raises(RuntimeError, match="preserved unchanged"):
        RasEbfeModels._extract_component(zip_path, destination)

    assert retained.read_text(encoding="utf-8") == "one"
    assert not (destination / "nested" / "two.txt").exists()
    assert not (
        destination / RasEbfeModels._EXTRACTION_RECEIPT_NAME
    ).exists()


def test_extract_component_rejects_same_size_crc_mismatch(tmp_path):
    zip_path = tmp_path / "archive.zip"
    zip_path.write_bytes(_make_zip_bytes({"same-size.txt": "GOOD"}))
    destination = tmp_path / "archive_extracted"
    destination.mkdir()
    retained = destination / "same-size.txt"
    retained.write_text("EVIL", encoding="utf-8")

    with pytest.raises(RuntimeError, match="preserved unchanged"):
        RasEbfeModels._extract_component(zip_path, destination)

    assert retained.read_text(encoding="utf-8") == "EVIL"
    assert not (
        destination / RasEbfeModels._EXTRACTION_RECEIPT_NAME
    ).exists()


def test_extract_component_audits_complete_legacy_cache(tmp_path):
    zip_path = tmp_path / "archive.zip"
    zip_path.write_bytes(_make_zip_bytes({"nested/test.txt": "complete"}))
    destination = tmp_path / "archive_extracted"
    target = destination / "nested" / "test.txt"
    target.parent.mkdir(parents=True)
    target.write_text("complete", encoding="utf-8")

    RasEbfeModels._extract_component(zip_path, destination)

    receipt = destination / RasEbfeModels._EXTRACTION_RECEIPT_NAME
    assert receipt.is_file()
    assert target.read_text(encoding="utf-8") == "complete"


def test_extract_component_preserves_dos_member_timestamp(tmp_path):
    zip_path = tmp_path / "archive.zip"
    member = zipfile.ZipInfo("dated.txt", date_time=(2022, 2, 28, 16, 48, 16))
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(member, "dated")

    destination = tmp_path / "archive_extracted"
    RasEbfeModels._extract_component(zip_path, destination)

    observed = datetime.fromtimestamp((destination / "dated.txt").stat().st_mtime)
    assert observed.replace(microsecond=0) == datetime(2022, 2, 28, 16, 48, 16)


def test_extract_component_preserves_extended_timestamp_clock_fields(tmp_path):
    zip_path = tmp_path / "archive.zip"
    epoch = int(datetime(2022, 8, 31, 21, 11, 43, tzinfo=timezone.utc).timestamp())
    member = zipfile.ZipInfo("extended.txt")
    member.extra = struct.pack("<HHBI", 0x5455, 5, 1, epoch)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(member, "extended")

    destination = tmp_path / "archive_extracted"
    RasEbfeModels._extract_component(zip_path, destination)

    observed = datetime.fromtimestamp(
        (destination / "extended.txt").stat().st_mtime
    )
    assert observed.replace(microsecond=0) == datetime(2022, 8, 31, 21, 11, 43)


def test_extract_component_rejects_path_traversal_without_receipt(tmp_path):
    zip_path = tmp_path / "archive.zip"
    zip_path.write_bytes(_make_zip_bytes({"../escape.txt": "escape"}))
    destination = tmp_path / "archive_extracted"

    with pytest.raises(ValueError, match="Unsafe ZIP member path"):
        RasEbfeModels._extract_component(zip_path, destination)

    assert not (tmp_path / "escape.txt").exists()
    assert not (
        destination / RasEbfeModels._EXTRACTION_RECEIPT_NAME
    ).exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows long-path regression")
def test_extract_component_supports_long_member_paths_on_windows(tmp_path):
    nested = "/".join(["segment" + ("x" * 35)] * 6)
    member_name = f"{nested}/file.txt"
    destination = tmp_path / "archive_extracted"
    member_path = Path(*member_name.split("/"))
    assert len(str(destination / member_path)) > 260
    zip_path = tmp_path / "archive.zip"
    zip_path.write_bytes(_make_zip_bytes({member_name: "long path"}))

    RasEbfeModels._extract_component(zip_path, destination)

    target = destination / member_path
    with open(RasEbfeModels._windows_extended_path(target), encoding="utf-8") as stream:
        assert stream.read() == "long path"
