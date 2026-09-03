import logging
from pathlib import Path

import h5py
import numpy as np

from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan


LOGGER_NAME = "ras_commander.hdf.HdfResultsPlan"


def _empty_hdf(path: Path) -> None:
    with h5py.File(path, "w"):
        pass


def _runtime_hdf_with_unknown_times(path: Path) -> None:
    with h5py.File(path, "w") as hdf:
        plan_info = hdf.require_group("Plan Data/Plan Information")
        plan_info.attrs["Plan Name"] = np.bytes_("Steady plan")
        plan_info.attrs["Simulation Start Time"] = np.bytes_("Unknown")
        plan_info.attrs["Simulation End Time"] = np.bytes_("Unknown")


def test_runtime_unknown_times_are_debug_only(tmp_path, caplog):
    hdf_path = tmp_path / "steady_unknown_times.p01.hdf"
    _runtime_hdf_with_unknown_times(hdf_path)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        result = HdfResultsPlan.get_runtime_data(hdf_path)

    assert result is None
    assert not [
        record for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    ]

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        HdfResultsPlan.get_runtime_data(hdf_path)

    assert any(
        record.name == LOGGER_NAME
        and record.levelno == logging.DEBUG
        and "Runtime metadata unavailable" in record.getMessage()
        for record in caplog.records
    )


def test_reference_output_absence_is_debug_only(tmp_path, caplog):
    hdf_path = tmp_path / "no_reference_outputs.p01.hdf"
    _empty_hdf(hdf_path)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = HdfResultsPlan.get_reference_timeseries(hdf_path, "lines")

    assert result.empty
    assert not [
        record for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.WARNING
    ]


def test_reference_timeseries_reads_modern_matrix_schema(tmp_path):
    hdf_path = tmp_path / "reference_lines.p01.hdf"
    base = (
        "Results/Unsteady/Output/Output Blocks/Base Output/"
        "Unsteady Time Series"
    )
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            f"{base}/Time Date Stamp (ms)",
            data=np.array(
                [b"01JAN2020 00:00:00:000", b"01JAN2020 01:00:00:000"]
            ),
        )
        group = hdf.create_group(f"{base}/Reference Lines")
        group.create_dataset(
            "Name",
            data=np.array([b"Line A|Mesh 1", b"Line B|Mesh 1"]),
        )
        flow = group.create_dataset(
            "Flow",
            data=np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
        )
        flow.attrs["Units"] = b"cfs"
        group.create_dataset(
            "Water Surface",
            data=np.array([[10.0, 20.0], [11.0, 21.0]], dtype=np.float32),
        )

    result = HdfResultsPlan.get_reference_timeseries(hdf_path, "lines")

    assert len(result) == 4
    assert {"time", "refln_id", "refln_name", "mesh_name"}.issubset(
        result.columns
    )
    assert {"Flow", "Water Surface"}.issubset(result.columns)
    assert result["refln_name"].tolist() == ["Line A", "Line B"] * 2
    assert result["Flow"].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_compute_messages_txt_fallback_success_is_debug_only(
    tmp_path,
    caplog,
    monkeypatch,
):
    from ras_commander.RasControl import RasControl

    hdf_path = tmp_path / "missing_compute_messages.p01.hdf"
    _empty_hdf(hdf_path)

    def fake_comp_msgs(_hdf_path):
        return "messages from txt fallback"

    monkeypatch.setattr(RasControl, "get_comp_msgs", staticmethod(fake_comp_msgs))

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = HdfResultsPlan.get_compute_messages(hdf_path)

    assert result == "messages from txt fallback"
    assert not [
        record for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.WARNING
    ]


def test_is_steady_plan_failure_is_debug_only(tmp_path, caplog):
    hdf_path = tmp_path / "not_hdf.p01.hdf"
    hdf_path.write_text("not an HDF file", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        result = HdfResultsPlan.is_steady_plan(hdf_path)

    assert result is False
    assert not [
        record for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    ]


def test_list_steady_variables_on_nonsteady_hdf_is_debug_only(tmp_path, caplog):
    hdf_path = tmp_path / "unsteady_only.p01.hdf"
    _empty_hdf(hdf_path)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = HdfResultsPlan.list_steady_variables(hdf_path)

    assert result == {"cross_sections": [], "additional": [], "structures": []}
    assert not [
        record for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.WARNING
    ]
