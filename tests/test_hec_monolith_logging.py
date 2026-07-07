import logging
import types

import pytest

from ras_commander.dss import _hec_monolith
from ras_commander.dss._hec_monolith import HecMonolithDownloader


LOGGER_NAME = "ras_commander.dss._hec_monolith"


def test_install_is_quiet_by_default(monkeypatch, caplog, capsys, tmp_path):
    downloader = HecMonolithDownloader(cache_dir=tmp_path)
    calls = []

    monkeypatch.setattr(downloader, "is_installed", lambda: False)
    monkeypatch.setattr(downloader, "download_jars", lambda: calls.append("jars"))
    monkeypatch.setattr(
        downloader,
        "download_native_library",
        lambda: calls.append("native"),
    )
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    downloader.install()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert calls == ["jars", "native"]

    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == logging.DEBUG
    ]
    assert any("Installing HEC Monolith libraries in:" in msg for msg in debug_messages)
    assert "HEC Monolith installation complete" in debug_messages


def test_install_already_installed_is_debug_only(
    monkeypatch, caplog, capsys, tmp_path
):
    downloader = HecMonolithDownloader(cache_dir=tmp_path)
    monkeypatch.setattr(downloader, "is_installed", lambda: True)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    downloader.install()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == logging.DEBUG
    ]
    assert "HEC Monolith already installed" in debug_messages


def test_download_file_cached_is_debug_only(
    monkeypatch, caplog, capsys, tmp_path
):
    downloader = HecMonolithDownloader(cache_dir=tmp_path)
    cached = tmp_path / "jar" / "hec-monolith.jar"
    cached.write_bytes(b"cached")

    def fail_request(*_args, **_kwargs):
        raise AssertionError("download_file should not request cached files")

    monkeypatch.setattr(_hec_monolith.requests, "get", fail_request)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    result = downloader.download_file("https://example.invalid/file.jar", cached)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert result == cached
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == logging.DEBUG
    ]
    assert "Using cached HEC Monolith file: hec-monolith.jar" in debug_messages


def test_download_file_disables_progress_for_non_tty(
    monkeypatch, capsys, tmp_path
):
    tqdm_calls = []
    updates = []

    class FakeResponse:
        headers = {"content-length": "4"}

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

        def update(self, amount):
            updates.append(amount)

    monkeypatch.setattr(
        _hec_monolith.requests,
        "get",
        lambda url, stream: FakeResponse(),
    )
    monkeypatch.setattr(_hec_monolith, "tqdm", FakeTqdm)
    monkeypatch.setattr(
        _hec_monolith.sys,
        "stderr",
        types.SimpleNamespace(isatty=lambda: False),
    )

    downloader = HecMonolithDownloader(cache_dir=tmp_path)
    dest = tmp_path / "jar" / "download.bin"

    result = downloader.download_file("https://example.invalid/download.bin", dest)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert result == dest
    assert dest.read_bytes() == b"abcd"
    assert updates == [2, 2]
    assert tqdm_calls == [
        {
            "total": 4,
            "unit": "B",
            "unit_scale": True,
            "unit_divisor": 1024,
            "leave": False,
            "disable": True,
        }
    ]


def test_download_file_can_explicitly_show_progress(monkeypatch, tmp_path):
    tqdm_calls = []

    class FakeResponse:
        headers = {"content-length": "1"}

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            assert chunk_size == 8192
            yield b"x"

    class FakeTqdm:
        def __init__(self, **kwargs):
            tqdm_calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, _amount):
            pass

    monkeypatch.setattr(
        _hec_monolith.requests,
        "get",
        lambda url, stream: FakeResponse(),
    )
    monkeypatch.setattr(_hec_monolith, "tqdm", FakeTqdm)

    downloader = HecMonolithDownloader(cache_dir=tmp_path, show_progress=True)

    downloader.download_file(
        "https://example.invalid/download.bin",
        tmp_path / "jar" / "download.bin",
    )

    assert tqdm_calls[0]["disable"] is False
    assert tqdm_calls[0]["leave"] is False
