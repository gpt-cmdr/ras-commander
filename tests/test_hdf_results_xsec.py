"""Tests for reference line and point time-series extraction."""

from pathlib import Path

import h5py
import numpy as np


BASE_TS_PATH = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series"
)


def _write_reference_group(hdf: h5py.File, group_name: str) -> None:
    group = hdf.create_group(f"{BASE_TS_PATH}/{group_name}")
    group.create_dataset(
        "Name",
        data=np.array([b"Feature 1|Mesh A", b"Feature 2|Mesh A"]),
    )

    variables = {
        "Flow": "cfs",
        "Velocity": "ft/s",
        "Area": "sq ft",
        "Top Width": "ft",
        "Depth Hydraulic": "ft",
        "Friction Slope": "ft/ft",
        "Water Surface": "ft",
    }
    values = np.arange(6, dtype=float).reshape(3, 2)
    for i, (name, units) in enumerate(variables.items(), start=1):
        dataset = group.create_dataset(name, data=values + i)
        dataset.attrs["Units"] = units.encode("utf-8")

    group.create_dataset(
        "Notes",
        data=np.array(
            [[b"a", b"b"], [b"c", b"d"], [b"e", b"f"]],
        ),
    )
    group.create_dataset("Feature Index", data=np.arange(6).reshape(3, 2))
    group.create_dataset("Units", data=np.array([b"cfs", b"ft/s"]))
    group.create_dataset("Wrong Shape", data=np.arange(3, dtype=float))


def _write_reference_hdf(path: Path) -> None:
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time Date Stamp (ms)",
            data=np.array(
                [
                    b"01Jan2020 00:00:00.000",
                    b"01Jan2020 01:00:00.000",
                    b"01Jan2020 02:00:00.000",
                ],
            ),
        )
        _write_reference_group(hdf, "Reference Lines")
        _write_reference_group(hdf, "Reference Points")


def test_ref_lines_timeseries_reads_all_numeric_matching_datasets(tmp_path):
    """Reference lines include all numeric time-series datasets dynamically."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "reference_lines.p01.hdf"
    _write_reference_hdf(hdf_path)

    ds = HdfResultsXsec.get_ref_lines_timeseries(hdf_path)

    assert set(ds.data_vars) == {
        "Flow",
        "Velocity",
        "Area",
        "Top Width",
        "Depth Hydraulic",
        "Friction Slope",
        "Water Surface",
    }
    assert "Notes" not in ds
    assert "Feature Index" not in ds
    assert "Units" not in ds
    assert "Wrong Shape" not in ds
    assert ds["Flow"].dims == ("time", "refln_id")
    assert ds["Flow"].shape == (3, 2)
    assert ds["Flow"].attrs["units"] == "cfs"
    assert ds["Friction Slope"].attrs["units"] == "ft/ft"
    assert list(ds.coords["refln_name"].values) == ["Feature 1", "Feature 2"]
    assert list(ds.coords["mesh_name"].values) == ["Mesh A", "Mesh A"]


def test_ref_points_timeseries_reads_all_numeric_matching_datasets(tmp_path):
    """Reference points use the same dynamic native dataset selection."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "reference_points.p01.hdf"
    _write_reference_hdf(hdf_path)

    ds = HdfResultsXsec.get_ref_points_timeseries(hdf_path)

    assert set(ds.data_vars) == {
        "Flow",
        "Velocity",
        "Area",
        "Top Width",
        "Depth Hydraulic",
        "Friction Slope",
        "Water Surface",
    }
    assert "Notes" not in ds
    assert "Feature Index" not in ds
    assert ds["Area"].dims == ("time", "refpt_id")
    assert ds["Area"].shape == (3, 2)
    assert ds["Area"].attrs["units"] == "sq ft"
    assert list(ds.coords["refpt_name"].values) == ["Feature 1", "Feature 2"]


def test_ref_lines_timeseries_supports_optional_variable_filter(tmp_path):
    """Existing calls still return all variables, while callers may filter."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "reference_filter.p01.hdf"
    _write_reference_hdf(hdf_path)

    ds = HdfResultsXsec.get_ref_lines_timeseries(
        hdf_path,
        variables=["Flow", "Area", "Missing Variable"],
    )

    assert set(ds.data_vars) == {"Flow", "Area"}


def test_ref_lines_timeseries_allows_names_without_mesh_suffix(tmp_path):
    """Some HDFs may omit the pipe-delimited mesh suffix on reference names."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "reference_names.p01.hdf"
    _write_reference_hdf(hdf_path)
    with h5py.File(hdf_path, "a") as hdf:
        del hdf[f"{BASE_TS_PATH}/Reference Lines/Name"]
        hdf.create_dataset(
            f"{BASE_TS_PATH}/Reference Lines/Name",
            data=np.array([b"Feature 1", b"Feature 2"]),
        )

    ds = HdfResultsXsec.get_ref_lines_timeseries(hdf_path, variables="Flow")

    assert list(ds.coords["refln_name"].values) == ["Feature 1", "Feature 2"]
    assert list(ds.coords["mesh_name"].values) == ["", ""]
