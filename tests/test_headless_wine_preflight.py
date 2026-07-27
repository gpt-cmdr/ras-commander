"""Tests for the Linux/Wine/Ras2Cng skill preflight."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / ".claude"
    / "skills"
    / "hecras-setup-linux-wine-ras2cng"
    / "scripts"
    / "headless_wine_preflight.py"
)
SPEC = importlib.util.spec_from_file_location("headless_wine_preflight", SCRIPT)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_cpu_topology_accepts_coherent_zero_based_namespace(monkeypatch):
    monkeypatch.setattr(preflight.os, "sysconf", lambda _name: 8, raising=False)
    monkeypatch.setattr(
        preflight.os,
        "sched_getaffinity",
        lambda _pid: {0, 1, 2, 3},
        raising=False,
    )

    result = preflight.inspect_cpu_topology()

    assert result["wine_topology_safe"] is True
    assert result["out_of_range_cpu_ids"] == []
    assert result["single_cpu_fallback"] == 0


def test_cpu_topology_rejects_sparse_ids_outside_reported_count(monkeypatch):
    monkeypatch.setattr(preflight.os, "sysconf", lambda _name: 4, raising=False)
    monkeypatch.setattr(
        preflight.os,
        "sched_getaffinity",
        lambda _pid: {2, 5, 6, 7},
        raising=False,
    )

    result = preflight.inspect_cpu_topology()

    assert result["wine_topology_safe"] is False
    assert result["out_of_range_cpu_ids"] == [5, 6, 7]
    assert result["single_cpu_fallback"] == 2


def test_runtime_ready_requires_complete_prefix_and_same_tree(tmp_path, monkeypatch):
    prefix = tmp_path / "wine"
    dotnet = prefix / "drive_c/windows/Microsoft.NET/Framework64/v4.0.30319"
    dotnet.mkdir(parents=True)
    (dotnet / "mscorlib.dll").write_bytes(b"marker")

    ras_dir = prefix / "drive_c/HEC-RAS/7.0"
    ras_dir.mkdir(parents=True)
    for name in preflight.REQUIRED_RAS_FILES:
        (ras_dir / name).write_bytes(b"fixture")
    for name in preflight.REQUIRED_RAS_DIRECTORIES:
        (ras_dir / name).mkdir()
    (ras_dir / "x64").mkdir()

    monkeypatch.setattr(
        preflight,
        "_wine_version",
        lambda executable, env: (True, "wine-11.0", None),
    )
    monkeypatch.setattr(preflight, "_package_version", lambda name: "test")

    result = preflight.inspect_runtime("wine", str(prefix), str(ras_dir))

    assert result["runtime_ready"] is True
    assert result["missing_ras_files"] == []
    assert result["native_hdf_directories"] == ["x64"]


def test_runtime_reports_missing_components(tmp_path, monkeypatch):
    prefix = tmp_path / "wine"
    (prefix / "drive_c").mkdir(parents=True)
    ras_dir = prefix / "drive_c/HEC-RAS/7.0"
    ras_dir.mkdir(parents=True)
    monkeypatch.setattr(
        preflight,
        "_wine_version",
        lambda executable, env: (True, "wine-11.0", None),
    )

    result = preflight.inspect_runtime("wine", str(prefix), str(ras_dir))

    assert result["runtime_ready"] is False
    assert result["dotnet48_marker_found"] is False
    assert "RasProcess.exe" in result["missing_ras_files"]
    assert result["native_hdf_directories"] == []


def test_main_can_require_python_packages(monkeypatch, capsys):
    monkeypatch.setattr(
        preflight,
        "build_report",
        lambda _args: {
            "cpu_topology": {"wine_topology_safe": True},
            "runtime": {"runtime_ready": True, "python_packages_ready": False},
        },
    )
    monkeypatch.setattr(
        preflight.sys,
        "argv",
        ["headless_wine_preflight.py", "--require-python-packages"],
    )

    assert preflight.main() == 4
    assert "python_packages_ready" in capsys.readouterr().out
