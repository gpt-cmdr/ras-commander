"""Tests for Linux-execution robustness fixes (CLB-882, CLB-883, CLB-884)."""
import os

import h5py
import numpy as np
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
                u = r.create_group("Unsteady")
                u.create_dataset("Output", data=[1.0])


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


@pytest.mark.parametrize(
    "message",
    [
        " ERROR: READ_UN_MET_EVAPO_DATA: Evapotranspiration values not found\n",
        "HDF_ERROR with the Geometry\n",
    ],
)
def test_validate_linux_solve_fails_on_explicit_native_error_lines(
    tmp_path,
    message,
):
    log = tmp_path / "compute_linux_01.log"
    _write_log(log, message)
    hdf = tmp_path / "p01.hdf"
    _make_hdf(hdf, results=True, unsteady=True)

    ok, reason = RasCmdr._validate_linux_solve(log, hdf, "01")

    assert ok is False
    assert "solver log reports failure" in reason


def test_validate_linux_solve_requires_finished_banner(tmp_path):
    log = tmp_path / "compute_linux_01.log"
    _write_log(log, "Starting Unsteady Flow Computations\n")
    hdf = tmp_path / "p01.hdf"
    _make_hdf(hdf, results=True, unsteady=True)

    ok, reason = RasCmdr._validate_linux_solve(log, hdf, "01")

    assert ok is False
    assert "Finished Unsteady Flow Simulation" in reason


def test_validate_linux_solve_ignores_volume_accounting_error_label(tmp_path):
    log = tmp_path / "compute_linux_01.log"
    _write_log(
        log,
        "Overall Volume Accounting Error as percentage: 0.0001\n"
        "Finished Unsteady Flow Simulation\n",
    )
    hdf = tmp_path / "p01.hdf"
    _make_hdf(hdf, results=True, unsteady=True)

    ok, reason = RasCmdr._validate_linux_solve(log, hdf, "01")

    assert ok is True, reason


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


def test_validate_linux_solve_fails_when_unsteady_has_no_populated_datasets(tmp_path):
    log = tmp_path / "compute_linux_01.log"
    _write_log(log, "Finished Unsteady Flow Simulation\n")
    hdf = tmp_path / "p01.hdf"
    with h5py.File(hdf, "w") as hf:
        hf.create_group("Results/Unsteady")

    ok, reason = RasCmdr._validate_linux_solve(log, hdf, "01")

    assert ok is False
    assert "no populated" in reason


def test_validate_linux_solve_fails_on_unreadable_log(tmp_path):
    ok, reason = RasCmdr._validate_linux_solve(tmp_path / "missing.log", tmp_path / "x.hdf", "01")
    assert ok is False
    assert "log" in reason.lower()


def test_effective_linux_core_count_caps_to_affinity(monkeypatch):
    monkeypatch.setattr(
        os,
        "sched_getaffinity",
        lambda _pid: {0, 2, 4},
        raising=False,
    )

    assert RasCmdr._effective_linux_core_count(8) == 3
    assert RasCmdr._effective_linux_core_count(2) == 2


@pytest.mark.parametrize("invalid", [True, 0, -1, 1.5, "4"])
def test_effective_linux_core_count_rejects_invalid_values(invalid):
    with pytest.raises(ValueError, match="positive integer"):
        RasCmdr._effective_linux_core_count(invalid)


def test_set_linux_hdf_num_cores_updates_1d_and_each_2d_mesh(tmp_path):
    tmp_hdf = tmp_path / "Model.p01.tmp.hdf"
    with h5py.File(tmp_hdf, "w") as hdf:
        parameters = hdf.require_group("Plan Data/Plan Parameters")
        parameters.attrs["1D Cores"] = np.int32(2)
        parameters.attrs["2D Cores (per mesh)"] = np.array([2, 1], dtype=np.int32)

    evidence = RasCmdr._set_linux_hdf_num_cores(tmp_hdf, 3)

    with h5py.File(tmp_hdf, "r") as hdf:
        parameters = hdf["Plan Data/Plan Parameters"]
        assert int(parameters.attrs["1D Cores"]) == 3
        assert list(parameters.attrs["2D Cores (per mesh)"]) == [3, 3]
    assert len(evidence["updated_attributes"]) == 2
    assert evidence["effective_cores"] == 3


def test_set_linux_hdf_num_cores_rejects_result_hdf(tmp_path):
    result_hdf = tmp_path / "Model.p01.hdf"
    _make_hdf(result_hdf)

    with pytest.raises(ValueError, match=r"\*\.tmp\.hdf"):
        RasCmdr._set_linux_hdf_num_cores(result_hdf, 2)


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
