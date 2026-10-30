"""Clock-corruption regressions and optional immutable native-output coverage."""

import os
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf.HdfCompletion import HdfCompletion


BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
START = datetime(2000, 1, 10, 12)
END = START + timedelta(minutes=20)


def test_public_exports_resolve_class_after_submodule_import():
    import ras_commander
    import ras_commander.hdf

    from ras_commander import HdfCompletion as root_export
    from ras_commander.hdf import HdfCompletion as hdf_export

    assert root_export is hdf_export is HdfCompletion
    assert "HdfCompletion" in ras_commander.__all__
    assert "HdfCompletion" in ras_commander.hdf.__all__


def _clock(path, *, minutes=(0, 10, 20), milliseconds=True, legacy=False):
    """Small format fixture for mutations impractical in immutable real files."""
    with h5py.File(path, "w") as hdf:
        info = hdf.create_group("Plan Data/Plan Information")
        window = f"{START:%d%b%Y %H:%M:%S} to {END:%d%b%Y %H:%M:%S}"
        info.attrs["Time Window"] = window
        if not legacy:
            info.attrs["Simulation Start Time"] = f"{START:%d%b%Y %H:%M:%S}"
            info.attrs["Simulation End Time"] = f"{END:%d%b%Y %H:%M:%S}"
        group = hdf.create_group(BASE)
        group["Time"] = np.asarray(minutes, dtype=float) / (24 * 60)
        stamps = [(START + timedelta(minutes=m)).strftime("%d%b%Y %H:%M:%S") for m in minutes]
        group["Time Date Stamp"] = np.asarray(stamps, dtype="S19")
        if milliseconds:
            group["Time Date Stamp (ms)"] = np.asarray([s + ".000" for s in stamps], dtype="S23")
    return path


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("milliseconds", [True, False])
def test_supported_clocks_and_declared_windows(tmp_path, legacy, milliseconds):
    path = _clock(tmp_path / "clock.p01.hdf", legacy=legacy, milliseconds=milliseconds)
    result = HdfCompletion.inspect_time_coverage(path)
    assert result["status"] == "covered"
    assert result["observed_end"] == END
    assert result["row_count"] == 3
    with h5py.File(path, "r") as hdf:
        assert HdfCompletion.inspect_time_coverage(hdf) == result


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("minutes,reason", [((0, 10), "end_not_observed"), ((10, 20), "start_not_observed")])
def test_requested_end_and_success_footer_are_not_result_clock(tmp_path, minutes, reason):
    path = _clock(tmp_path / "short.p01.hdf", minutes=minutes)
    with h5py.File(path, "r+") as hdf:
        hdf.create_dataset("Results/Summary/Compute Messages (text)", data=np.bytes_("Complete Process"))
    result = HdfCompletion.inspect_time_coverage(path)
    assert result["status"] == "not_covered"
    assert result["reason"] == reason


@pytest.mark.synthetic_hdf_layout
def test_off_cadence_end_has_no_fabricated_tolerance(tmp_path):
    path = _clock(tmp_path / "offcadence.p01.hdf", minutes=(0, 10))
    with h5py.File(path, "r+") as hdf:
        info = hdf["Plan Data/Plan Information"]
        del info.attrs["Time Window"]
        info.attrs["Simulation End Time"] = "10Jan2000 12:15:00"
        info.attrs["Base Output Interval"] = "10MIN"
    assert HdfCompletion.inspect_time_coverage(path)["status"] == "not_covered"


@pytest.mark.synthetic_hdf_layout(
    "backward-nonmonotonic_timestamp_axis",
    "bad_stamp-invalid_timestamp_axis",
    "conflict-conflicting_timestamp_axes",
    "count-invalid_numeric_time_axis",
    "empty_clock-invalid_timestamp_axis",
    "missing_clock-missing_timestamp_axis",
    "nan-invalid_numeric_time_axis",
    "numeric_backward-invalid_numeric_time_axis",
    "window_conflict-conflicting_declared_windows",
)
@pytest.mark.parametrize("mutation,reason", [
    ("missing_clock", "missing_timestamp_axis"),
    ("empty_clock", "invalid_timestamp_axis"),
    ("bad_stamp", "invalid_timestamp_axis"),
    ("backward", "nonmonotonic_timestamp_axis"),
    ("count", "invalid_numeric_time_axis"),
    ("nan", "invalid_numeric_time_axis"),
    ("numeric_backward", "invalid_numeric_time_axis"),
    ("conflict", "conflicting_timestamp_axes"),
    ("window_conflict", "conflicting_declared_windows"),
    ("missing_window", "missing_declared_window"),
])
def test_unknown_or_malformed_evidence_is_not_covered(tmp_path, mutation, reason):
    path = _clock(tmp_path / "bad.p01.hdf", milliseconds=False)
    with h5py.File(path, "r+") as hdf:
        group = hdf[BASE]
        info = hdf["Plan Data/Plan Information"]
        if mutation == "missing_clock":
            del group["Time Date Stamp"]
        elif mutation == "empty_clock":
            del group["Time Date Stamp"]
            group["Time Date Stamp"] = np.asarray([], dtype="S19")
        elif mutation == "bad_stamp":
            group["Time Date Stamp"][1] = b"not a timestamp"
        elif mutation == "backward":
            group["Time Date Stamp"][1] = b"10Jan2000 11:59:00"
        elif mutation == "count":
            del group["Time"]
            group["Time"] = [0., 1.]
        elif mutation == "nan":
            group["Time"][1] = np.nan
        elif mutation == "numeric_backward":
            group["Time"][1] = -1
        elif mutation == "conflict":
            group["Time Date Stamp (ms)"] = np.asarray(["10Jan2000 12:00:00.000"] * 3, dtype="S23")
        elif mutation == "window_conflict":
            info.attrs["Time Window"] = "10Jan2000 12:00:00 to 11Jan2000 12:00:00"
        elif mutation == "missing_window":
            for key in list(info.attrs):
                del info.attrs[key]
    result = HdfCompletion.inspect_time_coverage(path)
    assert result["status"] == "unsupported"
    assert result["reason"] == reason


def test_steady_unknown_and_mixed_layouts(tmp_path):
    path = tmp_path / "layout.p01.hdf"
    with h5py.File(path, "w") as hdf:
        assert HdfCompletion.inspect_time_coverage(hdf)["status"] == "unsupported"
        hdf.create_group("Results/Steady")
        assert HdfCompletion.inspect_time_coverage(hdf)["status"] == "not_applicable"
        hdf.create_group("Results/Unsteady")
        assert HdfCompletion.inspect_time_coverage(hdf)["status"] == "unsupported"


def test_native_davis_clock_read_only():
    """Configure a retained native fixture; never run a solver or modify it."""
    value = os.environ.get("RAS_COMPLETION_DAVIS_HDF")
    if not value:
        pytest.skip("Set RAS_COMPLETION_DAVIS_HDF to retained native Davis plan output")
    path = Path(value)
    assert path.is_file(), f"Configured native fixture unavailable: {path}"
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    result = HdfCompletion.inspect_time_coverage(path)
    assert result["status"] == "covered"
    assert result["declared_start"] == datetime(2000, 1, 10, 12)
    assert result["declared_end"] == datetime(2000, 1, 12)
    assert result["observed_end"] == result["declared_end"]
    assert result["row_count"] == 217
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before


def test_native_20261021_corpus_read_only():
    value = os.environ.get("RAS_COMPLETION_GOLDEN_ROOT")
    if not value:
        pytest.skip("Set RAS_COMPLETION_GOLDEN_ROOT to the retained 20261021 fixture corpus")
    root = Path(value)
    paths = sorted(root.rglob("*.p*.hdf"))
    assert len(paths) == 33
    counts = Counter()
    warmup = []
    for path in paths:
        before = (path.stat().st_size, path.stat().st_mtime_ns)
        result = HdfCompletion.inspect_time_coverage(path)
        counts[result["status"]] += 1
        assert result["status"] in ("covered", "not_applicable"), (path, result)
        if result["status"] == "covered":
            assert result["observed_end"] == result["declared_end"], path
            if result["observed_start"] < result["declared_start"]:
                warmup.append(path)
        assert (path.stat().st_size, path.stat().st_mtime_ns) == before
    assert counts == {"covered": 26, "not_applicable": 7}
    assert len(warmup) == 2
