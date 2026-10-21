"""HdfBase timestamp readers accept a path as well as an open HDF handle.

``get_unsteady_timestamps`` and ``get_simulation_start_time`` previously
required an open ``h5py.File``; a ``str`` or ``Path`` failed with an opaque
``TypeError`` ("string indices must be integers"). They also read only
``Time Date Stamp (ms)``, which HEC-RAS 5.0.x plan HDFs do not write.
"""
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfBase

PLAN_INFO = "Plan Data/Plan Information"
TS_PATH = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


def _make_hdf(path, *, ms_stamps=None, stamps=None):
    with h5py.File(path, "w") as f:
        f.create_group(PLAN_INFO).attrs["Simulation Start Time"] = np.bytes_(
            b"01Jan2019 00:00:00"
        )
        if ms_stamps is not None:
            f.create_dataset(
                f"{TS_PATH}/Time Date Stamp (ms)",
                data=np.array([s.encode() for s in ms_stamps], dtype="S24"),
            )
        if stamps is not None:
            f.create_dataset(
                f"{TS_PATH}/Time Date Stamp",
                data=np.array([s.encode() for s in stamps], dtype="S20"),
            )
    return path


EXPECTED = [datetime(2019, 1, 1, 0, 0), datetime(2019, 1, 1, 1, 0)]


@pytest.mark.parametrize("as_type", [str, Path])
def test_timestamps_accept_paths(tmp_path, as_type):
    p = _make_hdf(
        tmp_path / "v6.p01.hdf",
        ms_stamps=["01Jan2019 00:00:00:000", "01Jan2019 01:00:00:000"],
    )
    assert HdfBase.get_unsteady_timestamps(as_type(p)) == EXPECTED
    assert HdfBase.get_unsteady_timestamps(hdf_file=as_type(p)) == EXPECTED
    assert HdfBase.get_simulation_start_time(as_type(p)) == EXPECTED[0]


def test_timestamps_still_accept_open_handle(tmp_path):
    p = _make_hdf(
        tmp_path / "v6.p01.hdf",
        ms_stamps=["01Jan2019 00:00:00:000", "01Jan2019 01:00:00:000"],
    )
    with h5py.File(p, "r") as f:
        assert HdfBase.get_unsteady_timestamps(f) == EXPECTED
        assert HdfBase.get_simulation_start_time(f) == EXPECTED[0]


def test_timestamps_fall_back_without_millisecond_dataset(tmp_path):
    """HEC-RAS 5.0.x writes only 'Time Date Stamp'."""
    p = _make_hdf(
        tmp_path / "v50.p01.hdf",
        stamps=["01Jan2019 00:00:00", "01Jan2019 01:00:00"],
    )
    assert HdfBase.get_unsteady_timestamps(p) == EXPECTED


def test_timestamps_without_results_raise_clear_error(tmp_path):
    p = _make_hdf(tmp_path / "geometry_only.p01.hdf")
    with pytest.raises(ValueError, match="No unsteady output timestamps"):
        HdfBase.get_unsteady_timestamps(p)


def test_timestamps_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        HdfBase.get_unsteady_timestamps(tmp_path / "missing.p01.hdf")
