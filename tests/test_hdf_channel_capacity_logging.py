import logging
from types import SimpleNamespace

import h5py
import pandas as pd
import pytest

from ras_commander.hdf import HdfChannelCapacity, HdfUtils


def test_system_capacity_summary_logs_one_concise_info_line(caplog):
    capacity_df = pd.DataFrame(
        {
            "RS": ["300", "200", "100", "050"],
            "capacity_level": [1, 1, 3, 7],
            "Len Channel": [100.0, 200.0, 300.0, 400.0],
        }
    )

    caplog.set_level(logging.INFO, logger="ras_commander.hdf.HdfChannelCapacity")

    summary = HdfChannelCapacity.system_capacity_summary(capacity_df)

    assert summary["channel_length_ft"].sum() == pytest.approx(1000.0)
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ras_commander.hdf.HdfChannelCapacity"
    ]
    assert messages == ["System capacity summary: levels=3 total_length_ft=1000 xs=4"]


def test_standardize_hdf_input_resolution_probe_is_debug_only(
    tmp_path, monkeypatch, caplog
):
    ras_object = SimpleNamespace(folder=tmp_path)

    def fail_resolve(*_args, **_kwargs):
        raise RuntimeError("resolver unavailable")

    monkeypatch.setattr(HdfUtils, "resolve_hdf_paths", fail_resolve)
    caplog.set_level(logging.DEBUG, logger="ras_commander.hdf.HdfChannelCapacity")

    result = HdfChannelCapacity._standardize_hdf_input("01", "plan", ras_object)

    assert result == tmp_path / "unknown.p01.hdf"
    records = [
        record
        for record in caplog.records
        if record.name == "ras_commander.hdf.HdfChannelCapacity"
    ]
    assert any(record.levelno == logging.DEBUG for record in records)
    assert not any(record.levelno >= logging.WARNING for record in records)


def test_extract_steady_profile_wse_missing_attrs_is_actionable(tmp_path):
    hdf_path = tmp_path / "steady.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/"
            "Cross Sections/Water Surface",
            data=[[10.0, 11.0]],
        )

    with pytest.raises(ValueError, match="cross-section attributes"):
        HdfChannelCapacity.extract_steady_profile_wse(hdf_path)


def test_extract_max_wse_empty_hdf_warning_is_actionable(tmp_path, caplog):
    hdf_path = tmp_path / "empty.p01.hdf"
    with h5py.File(hdf_path, "w"):
        pass

    caplog.set_level(logging.WARNING, logger="ras_commander.hdf.HdfChannelCapacity")

    with pytest.raises(ValueError, match="No WSE data extracted"):
        HdfChannelCapacity.extract_max_wse(hdf_path, profile_names=["AEP"])

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ras_commander.hdf.HdfChannelCapacity"
    ]
    assert any("Compute the plan" in message for message in messages)
    assert any("steady profiles or unsteady cross-section" in message for message in messages)


def test_determine_capacity_explicit_missing_storm_columns_raise():
    bank_elevations = pd.DataFrame(
        {
            "River": ["R"],
            "Reach": ["A"],
            "RS": ["100"],
            "controlling_bank_elev": [10.0],
            "Len Channel": [100.0],
        }
    )
    max_wse = pd.DataFrame(
        {
            "River": ["R"],
            "Reach": ["A"],
            "RS": ["100"],
            "10P": [9.5],
        }
    )

    with pytest.raises(ValueError, match="Storm columns not found"):
        HdfChannelCapacity.determine_capacity(
            bank_elevations,
            max_wse,
            storm_order=["10P", "1P"],
        )
