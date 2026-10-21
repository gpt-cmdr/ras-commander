"""The native compute worker accepts a run whose end is carried by another results series."""

from datetime import datetime

import h5py

from ras_commander import _container_compute as worker

BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time Date Stamp"
DSS = "Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/Unsteady Time Series/Time Date Stamp"
END = datetime(2018, 9, 9, 19, 20)


def _hdf(path, base_end, dss_end=None):
    with h5py.File(path, "w") as hdf:
        hdf[BASE] = [b"09SEP2018 18:00:00", base_end]
        if dss_end is not None:
            hdf[DSS] = [b"09SEP2018 18:00:00", dss_end]
    return h5py.File(path, "r")


def test_hec_ras_61_offset_base_output_is_accepted_when_another_series_ends_on_time(tmp_path):
    """HEC-RAS 6.1 BaldEagleCrkMulti2D p06: base output ends 19:10:20, DSS output at 19:20."""
    with _hdf(tmp_path / "a.hdf", b"09SEP2018 19:10:20", b"09SEP2018 19:20:00") as hdf:
        assert worker._any_series_reaches(hdf, END)


def test_a_run_that_stopped_early_is_not_accepted(tmp_path):
    with _hdf(tmp_path / "b.hdf", b"09SEP2018 19:10:20", b"09SEP2018 19:10:20") as hdf:
        assert not worker._any_series_reaches(hdf, END)
    with _hdf(tmp_path / "c.hdf", b"09SEP2018 19:10:20") as hdf:
        assert not worker._any_series_reaches(hdf, END)


def test_end_of_day_stamp_parses(tmp_path):
    with _hdf(tmp_path / "d.hdf", b"02JAN1900 23:55:00", b"03JAN1900 00:00:00") as hdf:
        assert worker._any_series_reaches(hdf, datetime(1900, 1, 3))
