"""Tests for Linux-execution robustness fixes (CLB-882, CLB-883, CLB-884)."""
import os

import h5py
import pytest

from ras_commander.RasCmdr import RasCmdr
from ras_commander.RasUtils import RasUtils


def _write_log(path, text):
    path.write_text(text, encoding="utf-8")


def _make_hdf(path, *, results=True, unsteady=True):
    with h5py.File(str(path), "w") as hf:
        hf.create_group("Geometry")
        if results:
            r = hf.create_group("Results")
            if unsteady:
                r.create_group("Unsteady")


# --- CLB-882: validate solve beyond exit-code 0 ---

def test_validate_linux_solve_passes_on_clean_run(tmp_path):
    log = tmp_path / "compute_linux_01.log"
    _write_log(log, "Starting Unsteady Flow Computations\nFinished Unsteady Flow Simulation\n")
    hdf = tmp_path / "p01.hdf"
    _make_hdf(hdf, results=True, unsteady=True)
    ok, reason = RasCmdr._validate_linux_solve(log, hdf, "01")
    assert ok is True, reason


def test_validate_linux_solve_fails_on_in_band_error(tmp_path):
    # RasUnsteady can exit 0 yet log an in-band failure — must be caught.
    log = tmp_path / "compute_linux_01.log"
    _write_log(log, "Unsteady flow encountered an error and the simulation stopped\n")
    hdf = tmp_path / "p01.hdf"
    _make_hdf(hdf, results=True, unsteady=True)
    ok, reason = RasCmdr._validate_linux_solve(log, hdf, "01")
    assert ok is False
    assert "solver log reports failure" in reason


def test_validate_linux_solve_fails_when_no_results_group(tmp_path):
    log = tmp_path / "compute_linux_01.log"
    _write_log(log, "Finished Unsteady Flow Simulation\n")
    hdf = tmp_path / "p01.hdf"
    _make_hdf(hdf, results=False)
    ok, reason = RasCmdr._validate_linux_solve(log, hdf, "01")
    assert ok is False
    assert "/Results" in reason


def test_validate_linux_solve_fails_when_results_but_no_unsteady(tmp_path):
    # Skeleton /Results carried over from Phase-1 preprocessing, no real output.
    log = tmp_path / "compute_linux_01.log"
    _write_log(log, "Finished Unsteady Flow Simulation\n")
    hdf = tmp_path / "p01.hdf"
    _make_hdf(hdf, results=True, unsteady=False)
    ok, reason = RasCmdr._validate_linux_solve(log, hdf, "01")
    assert ok is False
    assert "Unsteady" in reason


def test_validate_linux_solve_fails_on_unreadable_log(tmp_path):
    ok, reason = RasCmdr._validate_linux_solve(tmp_path / "missing.log", tmp_path / "x.hdf", "01")
    assert ok is False
    assert "log" in reason.lower()


# --- CLB-883: native Linux install discovery ---

def _make_native_root(tmp_path):
    root = tmp_path / "hecras"
    for ver, binname in [("6.6", "RasUnsteady"), ("7.0", "RasUnsteady"), ("5.0.7", "rasUnsteady64")]:
        if binname == "rasUnsteady64":
            (root / ver / "bin_ras").mkdir(parents=True)
            (root / ver / "bin_ras" / binname).write_text("#!/bin/sh\n", encoding="utf-8")
        else:
            (root / ver).mkdir(parents=True)
            (root / ver / binname).write_text("#!/bin/sh\n", encoding="utf-8")
    return root


def test_scan_native_linux_ras_finds_versions(tmp_path):
    found = RasUtils._scan_native_linux_ras([_make_native_root(tmp_path)])
    assert set(found) == {"6.6", "7.0", "5.0.7"}, found
    assert found["6.6"].name == "RasUnsteady"
    assert found["5.0.7"].name == "rasUnsteady64"  # bin_ras/ nested layout


def test_scan_native_linux_ras_skips_missing_roots(tmp_path):
    assert RasUtils._scan_native_linux_ras([tmp_path / "nope", tmp_path / "gone"]) == {}


@pytest.mark.skipif(
    os.name == "nt",
    reason="full Linux discover branch can't be faked on Windows (pathlib); "
           "the native scan itself is covered by test_scan_native_linux_ras_*",
)
def test_discover_ras_versions_includes_native_on_linux(tmp_path, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_LINUX_RAS_ROOT", str(_make_native_root(tmp_path)))
    discovered = RasUtils.discover_ras_versions()
    assert "6.6" in discovered and discovered["6.6"].name == "RasUnsteady"
