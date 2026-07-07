"""Tests for geometry metadata extraction from HDF files."""

from datetime import datetime

import h5py
import numpy as np

from ras_commander.hdf.HdfPlan import HdfPlan


def test_get_geometry_information_handles_mixed_attribute_shapes(tmp_path):
    hdf_path = tmp_path / "Project.g09.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Extents"] = np.array([1.0, 2.0, 3.0, 4.0])
        geometry.attrs["Geometry Time"] = np.bytes_("27Jun2026 12:04:02")
        geometry.attrs["Title"] = np.bytes_("Single 2D Area - Internal Dam Structure")
        geometry.attrs["Version"] = np.bytes_("1.0.22 (07Apr2026)")

    attrs_df = HdfPlan.get_geometry_information(hdf_path)

    assert list(attrs_df.columns) == ["Value"]
    assert np.array_equal(attrs_df.loc["Extents", "Value"], np.array([1.0, 2.0, 3.0, 4.0]))
    assert attrs_df.loc["Geometry Time", "Value"] == datetime(2026, 6, 27, 12, 4, 2)
    assert attrs_df.loc["Title", "Value"] == "Single 2D Area - Internal Dam Structure"
    assert attrs_df.loc["Version", "Value"] == "1.0.22 (07Apr2026)"
