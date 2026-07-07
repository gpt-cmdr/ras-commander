import logging
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf.HdfPlan import HdfPlan


LOGGER_NAME = "ras_commander.hdf.HdfPlan"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_plan_hdf(
    hdf_path: Path,
    *,
    include_plan_parameters: bool = False,
    program_version: str | None = "6.60",
):
    with h5py.File(hdf_path, "w") as hdf:
        plan_data = hdf.create_group("Plan Data")
        if program_version is not None:
            info = plan_data.create_group("Plan Information")
            info.attrs["Program Version"] = np.bytes_(program_version)
        if include_plan_parameters:
            params = plan_data.create_group("Plan Parameters")
            params.attrs["Example Parameter"] = np.bytes_("Example Value")


def test_optional_plan_metadata_absence_is_quiet_by_default(tmp_path, caplog):
    hdf_path = tmp_path / "Project.p01.hdf"
    _write_plan_hdf(hdf_path, include_plan_parameters=False)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        params = HdfPlan.get_plan_parameters(hdf_path)
        precip = HdfPlan.get_plan_met_precip(hdf_path)
        wse_method = HdfPlan.get_starting_wse_method(hdf_path)

    assert params.empty
    assert list(params.columns) == ["Plan", "Parameter", "Value"]
    assert precip == {}
    assert wse_method["method"] == "Unknown"
    assert _records(caplog) == []


def test_optional_plan_metadata_absence_has_debug_context(tmp_path, caplog):
    hdf_path = tmp_path / "Project.p01.hdf"
    _write_plan_hdf(hdf_path, include_plan_parameters=False)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        HdfPlan.get_plan_parameters(hdf_path)
        HdfPlan.get_plan_met_precip(hdf_path)
        HdfPlan.get_starting_wse_method(hdf_path)

    messages = [record.getMessage() for record in _records(caplog)]
    assert any("Plan Parameters not found in Project.p01.hdf" in message for message in messages)
    assert any("Precipitation data not found in Project.p01.hdf" in message for message in messages)
    assert any("Starting WSE method not found in Project.p01.hdf" in message for message in messages)


def test_get_2d_flow_options_missing_plan_parameters_mentions_legacy_output(
    tmp_path,
):
    hdf_path = tmp_path / "Project.p01.hdf"
    _write_plan_hdf(hdf_path, include_plan_parameters=False, program_version="4.10")
    (tmp_path / "Project.O01").write_text("legacy output\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        HdfPlan.get_2d_flow_options(hdf_path)

    message = str(exc_info.value)
    assert "HEC-RAS 5.x+ computed plan HDF" in message
    assert "Plan Data/Plan Parameters" in message
    assert "Project.p01.hdf does not contain that group" in message
    assert "Program Version 4.10 indicates HEC-RAS 4.x or earlier" in message
    assert "Found legacy output file Project.O01" in message
    assert "legacy .O## files" in message
    assert "RasControl" in message
    assert str(tmp_path) not in message


def test_get_2d_flow_options_missing_plan_parameters_without_legacy_file(
    tmp_path,
):
    hdf_path = tmp_path / "Project.p01.hdf"
    _write_plan_hdf(hdf_path, include_plan_parameters=False, program_version="6.60")

    with pytest.raises(ValueError) as exc_info:
        HdfPlan.get_2d_flow_options(hdf_path)

    message = str(exc_info.value)
    assert "HEC-RAS 5.x+ computed plan HDF" in message
    assert "Project.p01.hdf does not contain that group" in message
    assert "Found legacy output file" not in message
    assert "Program Version 6.60 indicates HEC-RAS 4.x or earlier" not in message
    assert "RasControl" in message
    assert str(tmp_path) not in message


def test_plan_number_filename_fallback_warning_is_explicit(tmp_path, caplog):
    hdf_path = tmp_path / "Project.results.hdf"
    _write_plan_hdf(hdf_path, include_plan_parameters=True)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        params = HdfPlan.get_plan_parameters(hdf_path)

    assert not params.empty
    assert params["Plan"].tolist() == ["00"]
    records = _records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "Could not extract plan number from filename Project.results.hdf" in message
    assert "using fallback Plan value '00'" in message
    assert str(tmp_path) not in message
