"""Tests for reference line and point time-series extraction."""

import logging
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest


BASE_TS_PATH = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series"
)
XSEC_PATH = f"{BASE_TS_PATH}/Cross Sections"
LOGGER_NAME = "ras_commander.hdf.HdfResultsXsec"


def _write_xsec_results_hdf(path: Path, omit_dataset: str | None = None) -> None:
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time Date Stamp (ms)",
            data=np.array(
                [
                    b"01Jan2020 00:00:00:000",
                    b"01Jan2020 01:00:00:000",
                    b"01Jan2020 02:00:00:000",
                ],
            ),
        )

        attrs_dtype = np.dtype(
            [
                ("River", "S32"),
                ("Reach", "S32"),
                ("Station", "S32"),
                ("Name", "S32"),
            ]
        )
        hdf.create_dataset(
            f"{XSEC_PATH}/Cross Section Attributes",
            data=np.array(
                [
                    (b"River A", b"Reach A", b"1000", b"XS 1000"),
                    (b"River A", b"Reach A", b"2000", b"XS 2000"),
                ],
                dtype=attrs_dtype,
            ),
        )
        hdf.create_dataset(
            f"{XSEC_PATH}/Cross Section Only",
            data=np.array([b"XS 1000", b"XS 2000"]),
        )

        values = np.arange(6, dtype=float).reshape(3, 2)
        for i, dataset_name in enumerate(
            [
                "Water Surface",
                "Velocity Total",
                "Velocity Channel",
                "Flow Lateral",
                "Flow",
            ],
            start=1,
        ):
            if dataset_name != omit_dataset:
                hdf.create_dataset(f"{XSEC_PATH}/{dataset_name}", data=values + i)


def _write_minimal_plan_hdf(path: Path, program_version: str | None = None) -> None:
    with h5py.File(path, "w") as hdf:
        if program_version is not None:
            plan_info = hdf.create_group("Plan Data/Plan Information")
            plan_info.attrs["Program Version"] = program_version.encode("utf-8")


def _write_steady_results_hdf(path: Path) -> None:
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Results/Steady")


def _write_unsteady_without_xsec_hdf(path: Path) -> None:
    with h5py.File(path, "w") as hdf:
        hdf.create_group(BASE_TS_PATH)


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


def _assert_source_file_is_filename_only(ds, hdf_path: Path) -> None:
    """Notebook display of returned datasets should not expose local paths."""
    assert ds.attrs["source_file"] == hdf_path.name
    assert str(hdf_path.parent) not in ds.attrs["source_file"]
    assert str(hdf_path.parent) not in repr(ds)


def test_xsec_timeseries_success_emits_no_default_logs(tmp_path, caplog):
    """Successful direct cross-section extraction should stay quiet by default."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "xsec_results.p01.hdf"
    _write_xsec_results_hdf(hdf_path)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        ds = HdfResultsXsec.get_xsec_timeseries(hdf_path)

    assert set(ds.data_vars) == {
        "Water_Surface",
        "Velocity_Total",
        "Velocity_Channel",
        "Flow_Lateral",
        "Flow",
    }
    assert ds["Water_Surface"].shape == (3, 2)
    _assert_source_file_is_filename_only(ds, hdf_path)
    assert not [
        record for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.INFO
    ]


def test_xsec_timeseries_string_path_success_emits_no_default_logs(tmp_path, caplog):
    """Notebook-style direct string paths should not emit default logs."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "xsec_results.p01.hdf"
    _write_xsec_results_hdf(hdf_path)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        ds = HdfResultsXsec.get_xsec_timeseries(str(hdf_path))

    assert ds["Water_Surface"].shape == (3, 2)
    _assert_source_file_is_filename_only(ds, hdf_path)
    assert not [
        record for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.INFO
    ]


def test_xsec_timeseries_plan_number_uses_standardize_input(tmp_path, caplog):
    """Plan-number inputs should be resolved by @standardize_input."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "xsec_results.p01.hdf"
    _write_xsec_results_hdf(hdf_path)
    ras_object = SimpleNamespace(
        plan_df=pd.DataFrame(
            {
                "plan_number": ["01"],
                "HDF_Results_Path": [str(hdf_path)],
            }
        ),
        check_initialized=lambda: True,
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        ds = HdfResultsXsec.get_xsec_timeseries("01", ras_object=ras_object)

    assert ds["Water_Surface"].shape == (3, 2)
    _assert_source_file_is_filename_only(ds, hdf_path)
    assert not [
        record for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.INFO
    ]


def test_xsec_timeseries_missing_required_dataset_logs_error(tmp_path, caplog):
    """Missing requested cross-section outputs are direct API failures."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "xsec_missing.p01.hdf"
    _write_xsec_results_hdf(hdf_path, omit_dataset="Water Surface")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError):
            HdfResultsXsec.get_xsec_timeseries(hdf_path)

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    ]
    assert len(messages) == 1
    assert "Missing required 1D cross-section result dataset in xsec_missing.p01.hdf" in messages[0]
    assert f"{XSEC_PATH}/Water Surface" in messages[0]
    assert str(tmp_path) not in messages[0]


def test_xsec_timeseries_minimal_hdf_logs_actionable_error(tmp_path, caplog):
    """A geometry-only or uncomputed HDF should fail with concise guidance."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "minimal.p01.hdf"
    _write_minimal_plan_hdf(hdf_path)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError):
            HdfResultsXsec.get_xsec_timeseries(hdf_path)

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    ]
    assert len(messages) == 1
    assert "Cannot extract 1D cross-section time series from minimal.p01.hdf" in messages[0]
    assert "/Results is absent" in messages[0]
    assert "minimal, geometry-only, or uncomputed HDF" in messages[0]
    assert str(tmp_path) not in messages[0]


def test_xsec_timeseries_steady_hdf_points_to_steady_api(tmp_path, caplog):
    """Steady plan HDFs should direct users to the steady results API."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "steady.p02.hdf"
    _write_steady_results_hdf(hdf_path)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError):
            HdfResultsXsec.get_xsec_timeseries(hdf_path)

    message = next(
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    )
    assert "Cannot extract 1D unsteady cross-section time series from steady.p02.hdf" in message
    assert "file contains steady results" in message
    assert "HdfResultsPlan.get_steady_wse()" in message
    assert str(tmp_path) not in message


def test_xsec_timeseries_unsteady_without_cross_sections_logs_error(tmp_path, caplog):
    """Unsteady output without 1D cross sections should fail specifically."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "unsteady_no_xs.p01.hdf"
    _write_unsteady_without_xsec_hdf(hdf_path)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError):
            HdfResultsXsec.get_xsec_timeseries(hdf_path)

    message = next(
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    )
    assert "Cannot extract 1D cross-section time series from unsteady_no_xs.p01.hdf" in message
    assert "unsteady results exist but Cross Sections output is absent" in message
    assert str(tmp_path) not in message


def test_ref_lines_missing_group_is_debug_only(tmp_path, caplog):
    """Reference outputs are optional probes and should not warn by default."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "no_reference_lines.p01.hdf"
    with h5py.File(hdf_path, "w"):
        pass

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        ds = HdfResultsXsec.get_ref_lines_timeseries(hdf_path)

    assert not ds.data_vars
    assert not [
        record for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.WARNING
    ]

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        HdfResultsXsec.get_ref_lines_timeseries(hdf_path)

    assert any(
        record.name == LOGGER_NAME
        and record.levelno == logging.DEBUG
        and "Reference line time-series group not found in no_reference_lines.p01.hdf" in record.getMessage()
        and str(tmp_path) not in record.getMessage()
        for record in caplog.records
    )


def test_ref_lines_missing_name_dataset_logs_error(tmp_path, caplog):
    """A present reference group without Name is malformed output."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "reference_missing_name.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time Date Stamp (ms)",
            data=np.array([b"01Jan2020 00:00:00.000"]),
        )
        hdf.create_group(f"{BASE_TS_PATH}/Reference Lines")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError):
            HdfResultsXsec.get_ref_lines_timeseries(hdf_path)

    message = next(
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    )
    assert "Reference line time-series group in reference_missing_name.p01.hdf" in message
    assert "missing required dataset 'Name'" in message
    assert str(tmp_path) not in message


def test_ref_points_missing_timestamps_logs_error(tmp_path, caplog):
    """Reference output without unsteady timestamps is incomplete results output."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "reference_missing_time.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        group = hdf.create_group(f"{BASE_TS_PATH}/Reference Points")
        group.create_dataset("Name", data=np.array([b"Point 1|Mesh A"]))

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError):
            HdfResultsXsec.get_ref_points_timeseries(hdf_path)

    message = next(
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    )
    assert "Reference point time-series group in reference_missing_time.p01.hdf exists" in message
    assert "unsteady timestamps are missing" in message
    assert str(tmp_path) not in message


def test_ref_lines_no_matching_numeric_datasets_is_debug_only(tmp_path, caplog):
    """A reference group can exist while containing no selected numeric variables."""
    from ras_commander.hdf import HdfResultsXsec

    hdf_path = tmp_path / "reference_no_numeric.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            f"{BASE_TS_PATH}/Time Date Stamp (ms)",
            data=np.array([b"01Jan2020 00:00:00.000"]),
        )
        group = hdf.create_group(f"{BASE_TS_PATH}/Reference Lines")
        group.create_dataset("Name", data=np.array([b"Line 1|Mesh A"]))
        group.create_dataset("Notes", data=np.array([[b"text"]]))

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        ds = HdfResultsXsec.get_ref_lines_timeseries(hdf_path)

    assert not ds.data_vars
    assert any(
        record.name == LOGGER_NAME
        and record.levelno == logging.DEBUG
        and "Reference line group found in reference_no_numeric.p01.hdf" in record.getMessage()
        and "no numeric datasets matched expected shape" in record.getMessage()
        and str(tmp_path) not in record.getMessage()
        for record in caplog.records
    )


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
