"""Narrow registry diagnostics never infer GUI acceptance."""

import contextlib
import importlib
import sys
import types
from ras_commander import RasTcu
from ras_commander.RasTcu import TcuStatus

module = importlib.import_module("ras_commander.RasTcu")


def test_inspection_reads_only_exact_sentinel_in_both_views(monkeypatch):
    state = TcuStatus(
        None,
        "6.0",
        "C:/HEC/6.0",
        r"Software\VB and VBA Program Settings\6.0\ras.exe",
        "gui-evidence-required",
    )
    monkeypatch.setattr(RasTcu, "status", staticmethod(lambda **kw: state))
    monkeypatch.setattr(module.os, "name", "nt")
    reads = []

    def open_key(hive, path, reserved, access):
        assert path in {
            state.registry_key + r"\Projects",
            state.registry_key.removesuffix("ras.exe") + r"ras\Projects",
        }
        return contextlib.nullcontext(access)

    def query_value(key, name):
        reads.append((key, name))
        assert name == "System Statistic"
        return ("1065353813", 1) if key & 32 else ("wrong", 1)

    registry = types.SimpleNamespace(
        KEY_WOW64_32KEY=32,
        KEY_WOW64_64KEY=64,
        KEY_READ=1,
        HKEY_CURRENT_USER=123,
        OpenKey=open_key,
        QueryValueEx=query_value,
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    result = RasTcu.inspect_acceptance(ras_version="6.0")
    assert len(reads) == 4
    assert result["status"]["accepted"] is None
    assert result["registry_views"][0]["matches_release"] is True
    assert result["registry_views"][1]["matches_release"] is False


def test_non_windows_inspection_does_not_import_registry(monkeypatch):
    state = TcuStatus(None, "6.0", None, None, "not-windows")
    monkeypatch.setattr(RasTcu, "status", staticmethod(lambda **kw: state))
    monkeypatch.setattr(module.os, "name", "posix")
    assert RasTcu.inspect_acceptance()["registry_views"] == []


def test_binary_sentinel_remains_json_serializable(monkeypatch):
    import json

    state = TcuStatus(
        None,
        "6.0",
        "C:/HEC/6.0",
        r"Software\VB and VBA Program Settings\6.0\ras.exe",
        "gui-evidence-required",
    )
    monkeypatch.setattr(RasTcu, "status", staticmethod(lambda **kw: state))
    monkeypatch.setattr(module.os, "name", "nt")
    registry = types.SimpleNamespace(
        KEY_WOW64_32KEY=32,
        KEY_WOW64_64KEY=64,
        KEY_READ=1,
        HKEY_CURRENT_USER=123,
        OpenKey=lambda *args: contextlib.nullcontext(None),
        QueryValueEx=lambda *args: (b"\x00\xff", 3),
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    result = RasTcu.inspect_acceptance(ras_version="6.0")
    assert result["registry_views"][0]["value"] == {"bytes_hex": "00ff"}
    assert result["registry_views"][0]["matches_release"] is False
    json.dumps(result, allow_nan=False)


def test_probe_only_acceptance_cannot_export_a_registry_value(monkeypatch):
    import pytest

    state = TcuStatus(True, "6.0", "C:/HEC/6.0", None, "probe-verified")
    monkeypatch.setattr(RasTcu, "status", staticmethod(lambda *a, **kw: state))
    with pytest.raises(ValueError, match="registry-backed"):
        RasTcu.export_acceptance(ras_version="6.0")


def test_gui_receipt_handles_probe_without_registry_key(monkeypatch, tmp_path):
    import subprocess
    from pathlib import PosixPath
    from ras_commander import _tcu_gui

    executable = tmp_path / "Ras.exe"
    executable.write_bytes(b"unit fixture")
    state = TcuStatus(True, "6.0", str(tmp_path), None, "probe-verified")
    process = types.SimpleNamespace(pid=42, poll=lambda: 0)
    monkeypatch.setattr(module, "Path", PosixPath)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(
        RasTcu, "_resolve_exe", staticmethod(lambda *a: str(executable))
    )
    monkeypatch.setattr(RasTcu, "status", staticmethod(lambda *a: state))
    monkeypatch.setattr(RasTcu, "_save_gui_verification", staticmethod(lambda *a: None))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(
        _tcu_gui,
        "accept_owned_terms",
        lambda *a, **kw: {"gui_ready_verified": True, "graceful_exit": True},
    )
    result = RasTcu.accept_gui_terms(operator_acceptance=True, write_ack=False)
    assert result["gui_ready_verified"] is True
    assert result["registry_status_accepted"] is None
    assert result["system_statistic"] is None
    assert result["acceptance_status_reason"] == "probe-verified"
