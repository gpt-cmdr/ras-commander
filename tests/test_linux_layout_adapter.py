"""Unit tests for the Linux install-layout adapter in compute_plan_linux (CLB-886)."""
import os
import pytest

from ras_commander.RasCmdr import RasCmdr


def _make_canonical(root):
    """6.x/7.0 layout: RasUnsteady at root + libs/ tree."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "RasUnsteady").write_text("#!/bin/sh\n")
    libs = root / "libs"
    libs.mkdir(exist_ok=True)
    (libs / "libimf.so").write_text("x")
    (libs / "mkl").mkdir(exist_ok=True)
    (libs / "rhel_8").mkdir(exist_ok=True)
    return root


def _make_bin_ras(root, binname="rasUnsteady64"):
    """5.0.7 layout: bin_ras/rasUnsteady64 with libs colocated, no libs/ tree."""
    root.mkdir(parents=True, exist_ok=True)
    b = root / "bin_ras"
    b.mkdir(exist_ok=True)
    (b / binname).write_text("#!/bin/sh\n")
    (b / "libgfortran.so.3").write_text("x")
    (b / "libmkl_core.so").write_text("x")
    return root


def test_resolve_layout_canonical(tmp_path):
    root = _make_canonical(tmp_path / "6.6")
    lay = RasCmdr._resolve_linux_layout(root)
    assert lay["label"] == "canonical"
    assert lay["needs_c_file"] is False
    assert lay["ras_exe"] == root / "RasUnsteady"
    assert lay["lib_dirs"] == []


def test_resolve_layout_bin_ras(tmp_path):
    root = _make_bin_ras(tmp_path / "5.0.7")
    lay = RasCmdr._resolve_linux_layout(root)
    assert lay["label"].startswith("bin_ras")
    assert lay["needs_c_file"] is True
    assert lay["ras_exe"] == root / "bin_ras" / "rasUnsteady64"
    assert lay["lib_dirs"] == [root / "bin_ras"]


def test_resolve_layout_bin_ras_capitalized(tmp_path):
    root = _make_bin_ras(tmp_path / "5.0.7b", binname="RasUnsteady")
    lay = RasCmdr._resolve_linux_layout(root)
    assert lay["needs_c_file"] is True
    assert lay["ras_exe"].name == "RasUnsteady"
    assert lay["ras_exe"].parent.name == "bin_ras"


def test_resolve_layout_prefers_root_over_bin_ras(tmp_path):
    """If both a root RasUnsteady and bin_ras exist, canonical wins."""
    root = _make_canonical(tmp_path / "both")
    _make_bin_ras(root)
    lay = RasCmdr._resolve_linux_layout(root)
    assert lay["label"] == "canonical"
    assert lay["needs_c_file"] is False


def test_resolve_layout_missing_returns_canonical_guess(tmp_path):
    """Empty dir -> canonical guess so the caller raises a clear FileNotFoundError."""
    root = tmp_path / "empty"
    root.mkdir()
    lay = RasCmdr._resolve_linux_layout(root)
    assert lay["label"] == "canonical"
    assert lay["ras_exe"] == root / "RasUnsteady"


def test_build_ld_path_canonical(tmp_path):
    root = _make_canonical(tmp_path / "6.6")
    lay = RasCmdr._resolve_linux_layout(root)
    ld = RasCmdr._build_linux_ld_path(root, lay)
    parts = ld.split(":")
    assert str(root / "libs") in parts
    assert str(root / "libs" / "mkl") in parts
    assert str(root / "libs" / "rhel_8") in parts


def test_build_ld_path_bin_ras(tmp_path):
    root = _make_bin_ras(tmp_path / "5.0.7")
    lay = RasCmdr._resolve_linux_layout(root)
    ld = RasCmdr._build_linux_ld_path(root, lay)
    assert ld == str(root / "bin_ras")
