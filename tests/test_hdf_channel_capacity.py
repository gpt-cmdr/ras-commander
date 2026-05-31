import logging

import h5py
import pytest

from ras_commander.hdf import HdfChannelCapacity


def _write_hdf_without_cross_section_wse(tmp_path):
    hdf_path = tmp_path / "twod_only.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_group("Results")
    return hdf_path


def test_extract_max_wse_warns_by_default_when_no_1d_wse(tmp_path, caplog):
    hdf_path = _write_hdf_without_cross_section_wse(tmp_path)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match="No WSE data extracted"):
            HdfChannelCapacity.extract_max_wse(
                hdf_path,
                profile_names=["max_wse"],
            )

    assert any(
        "Could not extract WSE from twod_only.p01.hdf" in record.getMessage()
        for record in caplog.records
    )


def test_extract_max_wse_can_probe_without_warning(tmp_path, caplog):
    hdf_path = _write_hdf_without_cross_section_wse(tmp_path)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match="No WSE data extracted"):
            HdfChannelCapacity.extract_max_wse(
                hdf_path,
                profile_names=["max_wse"],
                warn_on_missing=False,
            )

    assert not any(
        "Could not extract WSE from twod_only.p01.hdf" in record.getMessage()
        for record in caplog.records
    )
