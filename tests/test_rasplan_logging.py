import logging
from pathlib import Path

import pandas as pd
import pytest

from ras_commander.RasPlan import RasPlan


LOGGER_NAME = "ras_commander.RasPlan"


class _DummyRas:
    def check_initialized(self):
        return None


class _RefreshableRas(_DummyRas):
    def get_plan_entries(self):
        return pd.DataFrame()


class _ProjectRas(_DummyRas):
    def __init__(self, project_folder: Path):
        self.project_folder = project_folder
        self.project_name = "Project"
        self.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "01",
                    "geom_number": "01",
                    "geometry_number": "01",
                    "Geom File": "g01",
                    "Geom Path": str(project_folder / "Project.g01"),
                }
            ]
        )
        self.geom_df = pd.DataFrame({"geom_number": ["01", "02"]})

    def get_plan_entries(self):
        return self.plan_df.copy()

    def get_geom_entries(self):
        return self.geom_df.copy()


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_plan(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "Plan Title=Logging Test",
                "Program Version=6.60",
                "Short Identifier=LogTest",
                "Simulation Date=01JAN1999,1200,04JAN1999,1200",
                "Geom File=g01",
                "Flow File=u01",
                "Computation Interval=10SEC",
                "Run HTab= 1 ",
                "Run UNet= 1 ",
                "HDF Compression= 4 ",
                "HDF Additional Output Variable=Face Flow",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_read_only_plan_getters_are_quiet_at_info(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)
    ras_obj = _DummyRas()

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        title = RasPlan.get_plan_title(plan_path, ras_object=ras_obj)
        short_id = RasPlan.get_shortid(plan_path, ras_object=ras_obj)
        hdf_variables = RasPlan.get_hdf_output_variables(plan_path, ras_object=ras_obj)
        description = RasPlan.read_plan_description(plan_path, ras_object=ras_obj)

    assert title == "Logging Test"
    assert short_id == "LogTest"
    assert hdf_variables == ["Face Flow"]
    assert description == ""
    assert _records(caplog) == []


def test_read_only_plan_getters_keep_debug_context(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)
    ras_obj = _DummyRas()

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasPlan.get_plan_title(plan_path, ras_object=ras_obj)
        RasPlan.get_shortid(plan_path, ras_object=ras_obj)
        RasPlan.get_hdf_output_variables(plan_path, ras_object=ras_obj)

    messages = [record.getMessage() for record in _records(caplog)]
    assert "Retrieved Plan Title: Logging Test" in messages
    assert "Retrieved Short Identifier: LogTest" in messages
    assert "Found 1 HDF output variables in plan" in messages


def test_update_run_flags_logs_filename_at_info_and_path_at_debug(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasPlan.update_run_flags(
            plan_path,
            geometry_preprocessor=False,
            unsteady_flow_simulation=False,
            ras_object=_DummyRas(),
        )

    info_messages = [
        record.getMessage()
        for record in _records(caplog)
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in _records(caplog)
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == [
        "Updated run flags in plan file: Project.p01 (flags modified: 2)"
    ]
    assert str(tmp_path) not in info_messages[0]
    assert any(str(plan_path) in message for message in debug_messages)


def test_unknown_plan_key_warning_is_concise(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        result = RasPlan.get_plan_value(plan_path, "Not A Real Key", _DummyRas())

    assert result is None
    warning_messages = [
        record.getMessage()
        for record in _records(caplog)
        if record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage()
        for record in _records(caplog)
        if record.levelno == logging.DEBUG
    ]

    assert warning_messages == ["Unknown plan key requested: Not A Real Key"]
    assert all("Valid keys are" not in message for message in warning_messages)
    assert any(
        message.startswith("Supported plan keys for get_plan_value():")
        for message in debug_messages
    )


def test_noop_plan_updates_are_quiet_at_info_and_visible_at_debug(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)
    ras_obj = _DummyRas()

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert RasPlan.set_2d_flow_options(plan_path, ras_object=ras_obj)
        assert RasPlan.set_hdf_write_parameters(plan_path, ras_object=ras_obj)
        assert RasPlan.set_hdf_write_parameters(
            plan_path,
            compression=4,
            ras_object=ras_obj,
        )
        assert RasPlan.add_hdf_output_variable(
            plan_path,
            "Face Flow",
            ras_object=ras_obj,
        )
        assert not RasPlan.remove_hdf_output_variable(
            plan_path,
            "Face Shear Stress",
            ras_object=ras_obj,
        )

    assert _records(caplog) == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasPlan.set_2d_flow_options(plan_path, ras_object=ras_obj)
        RasPlan.set_hdf_write_parameters(plan_path, ras_object=ras_obj)
        RasPlan.set_hdf_write_parameters(
            plan_path,
            compression=4,
            ras_object=ras_obj,
        )
        RasPlan.add_hdf_output_variable(
            plan_path,
            "Face Flow",
            ras_object=ras_obj,
        )
        RasPlan.remove_hdf_output_variable(
            plan_path,
            "Face Shear Stress",
            ras_object=ras_obj,
        )

    messages = [record.getMessage() for record in _records(caplog)]
    assert "No 2D flow options requested" in messages
    assert "No HDF write parameters requested" in messages
    assert "HDF write parameters already current in plan file: Project.p01" in messages
    assert "HDF output variable 'Face Flow' already exists in plan" in messages
    assert "HDF output variable 'Face Shear Stress' not found in plan" in messages


def test_set_geom_logs_single_info_summary(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    plan_path.write_text("Geom File=g01\n", encoding="utf-8")
    ras_obj = _ProjectRas(tmp_path)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasPlan.set_geom("01", "02", ras_object=ras_obj)

    info_messages = [
        record.getMessage()
        for record in _records(caplog)
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in _records(caplog)
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == ["Set geometry for plan p01 to g02"]
    assert "Updated Geom File in plan file Project.p01 to g02" in debug_messages
    assert plan_path.read_text(encoding="utf-8") == "Geom File=g02\n"


def test_get_plan_flow_type_missing_metadata_is_debug_not_warning(caplog):
    ras_obj = _DummyRas()
    ras_obj.plan_df = pd.DataFrame([{"plan_number": "01"}])

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        flow_type = RasPlan.get_plan_flow_type("01", ras_object=ras_obj)

    records = _records(caplog)
    assert flow_type == "Unknown"
    assert all(record.levelno < logging.WARNING for record in records)
    assert any(
        "plan_df missing unsteady_number column" in record.getMessage()
        for record in records
    )


def test_shortid_truncation_warning_is_concise(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)
    long_shortid = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        RasPlan.set_shortid(
            plan_path,
            long_shortid,
            ras_object=_RefreshableRas(),
        )

    warning_messages = [
        record.getMessage()
        for record in _records(caplog)
        if record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage()
        for record in _records(caplog)
        if record.levelno == logging.DEBUG
    ]

    assert warning_messages == [
        "Short Identifier exceeds 24 characters (received 26); truncating"
    ]
    assert long_shortid not in warning_messages[0]
    assert f"Original Short Identifier before truncation: {long_shortid}" in debug_messages


def test_removed_hdf_output_variable_logs_filename(tmp_path, caplog):
    plan_path = tmp_path / "Project.p01"
    _write_plan(plan_path)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert RasPlan.remove_hdf_output_variable(
            plan_path,
            "Face Flow",
            ras_object=_DummyRas(),
        )

    info_messages = [
        record.getMessage()
        for record in _records(caplog)
        if record.levelno == logging.INFO
    ]
    assert info_messages == [
        "Removed HDF output variable 'Face Flow' from plan file: Project.p01"
    ]
