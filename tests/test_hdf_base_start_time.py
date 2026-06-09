"""Regression tests for HdfBase.get_simulation_start_time version fallbacks.

HEC-RAS 6.x writes a 'Simulation Start Time' attribute on 'Plan Data/Plan Information'.
HEC-RAS 5.0.x does NOT; it stores 'Time Window' ("<start> to <end>") instead. A 5.0.x plan
HDF therefore made get_simulation_start_time() raise
("'NoneType' object has no attribute 'decode'"), which cascaded into get_mesh_max_ws /
get_mesh_summary_output failures on every 5.0.x 2D summary read.

These tests exercise the real on-disk attribute layout for each HEC-RAS version using tiny
synthetic HDFs. A committable real 5.0.x fixture is not available (the validated example is a
25 GB FEMA BLE plan), so the file-format layout is reproduced directly. Verified end-to-end
against real HEC-RAS 5.0.5 (FEMA LowerOuachita BLE) and 6.x (BaldEagle, Muncie) plan HDFs.
"""
from datetime import datetime

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfBase

PLAN_INFO = "Plan Data/Plan Information"
TS_PATH = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


def _make_hdf(path, *, sim_start=None, time_window=None, time_stamps=None):
    """Build a minimal plan HDF mirroring HEC-RAS byte-string attribute storage."""
    with h5py.File(path, "w") as f:
        pi = f.create_group(PLAN_INFO)
        if sim_start is not None:
            pi.attrs["Simulation Start Time"] = np.bytes_(sim_start.encode())
        if time_window is not None:
            pi.attrs["Time Window"] = np.bytes_(time_window.encode())
        if time_stamps is not None:
            ts = f.create_group(TS_PATH)
            ts.create_dataset(
                "Time Date Stamp",
                data=np.array([s.encode() for s in time_stamps], dtype="S20"),
            )


def test_start_time_6x_simulation_start_time(tmp_path):
    """6.x: explicit 'Simulation Start Time' attribute is used (primary path)."""
    p = tmp_path / "v6.p01.hdf"
    _make_hdf(p, sim_start="01Jan2019 00:00:00",
              time_window="01Jan2019 00:00:00 to 15Feb2019 18:00:00")
    with h5py.File(p, "r") as f:
        assert HdfBase.get_simulation_start_time(f) == datetime(2019, 1, 1, 0, 0, 0)


def test_start_time_50x_time_window_fallback(tmp_path):
    """5.0.x: no 'Simulation Start Time' -> fall back to 'Time Window' start."""
    p = tmp_path / "v50.p03.hdf"
    _make_hdf(p, time_window="01Jan2019 00:00:00 to 15Feb2019 18:00:00")
    with h5py.File(p, "r") as f:
        assert HdfBase.get_simulation_start_time(f) == datetime(2019, 1, 1, 0, 0, 0)


def test_start_time_timestamp_fallback(tmp_path):
    """No start-time attributes -> fall back to first unsteady output timestamp."""
    p = tmp_path / "ts_only.p01.hdf"
    _make_hdf(p, time_stamps=["02JAN2019 06:00:00", "02JAN2019 06:30:00"])
    with h5py.File(p, "r") as f:
        assert HdfBase.get_simulation_start_time(f) == datetime(2019, 1, 2, 6, 0, 0)


def test_start_time_uppercase_month(tmp_path):
    """'Time Window' months may be upper or mixed case; both must parse."""
    p = tmp_path / "upper.p01.hdf"
    _make_hdf(p, time_window="15FEB2019 18:00:00 to 20FEB2019 00:00:00")
    with h5py.File(p, "r") as f:
        assert HdfBase.get_simulation_start_time(f) == datetime(2019, 2, 15, 18, 0, 0)


def test_start_time_missing_plan_information(tmp_path):
    """No Plan Information group -> clear ValueError (unchanged contract)."""
    p = tmp_path / "empty.hdf"
    with h5py.File(p, "w"):
        pass
    with h5py.File(p, "r") as f:
        with pytest.raises(ValueError, match="Plan Information not found"):
            HdfBase.get_simulation_start_time(f)


def test_start_time_no_sources_raises(tmp_path):
    """Plan Information present but no start-time source -> informative ValueError."""
    p = tmp_path / "nostart.hdf"
    _make_hdf(p)  # empty Plan Information, no Time Window, no timestamps
    with h5py.File(p, "r") as f:
        with pytest.raises(ValueError, match="Could not determine simulation start time"):
            HdfBase.get_simulation_start_time(f)
