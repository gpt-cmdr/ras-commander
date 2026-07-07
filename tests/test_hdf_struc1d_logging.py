from __future__ import annotations

import logging
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf.HdfStruc1D import HdfStruc1D


LOGGER_NAME = "ras_commander.hdf.HdfStruc1D"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_empty_hdf(path: Path) -> Path:
    with h5py.File(path, "w"):
        pass
    return path


def _write_steady_shell(path: Path) -> Path:
    base_path = (
        "Results/Steady/Output/Output Blocks/Base Output/"
        "Steady Profiles/Cross Sections"
    )
    with h5py.File(path, "w") as hdf:
        hdf.require_group(base_path)
    return path


def _write_unsteady_shell(path: Path) -> Path:
    with h5py.File(path, "w") as hdf:
        hdf.require_group("Results/Unsteady")
    return path


def _write_steady_flanking_structure_hdf(path: Path) -> Path:
    base_path = (
        "Results/Steady/Output/Output Blocks/Base Output/"
        "Steady Profiles/Cross Sections"
    )
    attrs_dtype = np.dtype(
        [
            ("River", "S32"),
            ("Reach", "S32"),
            ("Station", "S16"),
        ]
    )
    attrs = np.array(
        [
            (b"River A", b"Reach A", b"52.38"),
            (b"River A", b"Reach A", b"52.00"),
        ],
        dtype=attrs_dtype,
    )
    water_surface = np.array(
        [
            [573.13, 334.44],
            [570.00, 330.00],
        ],
        dtype=np.float32,
    )
    flow = np.array(
        [
            [31500.0, 100.0],
            [30000.0, 95.0],
        ],
        dtype=np.float32,
    )

    with h5py.File(path, "w") as hdf:
        base = hdf.require_group(base_path)
        base.create_dataset("Attributes", data=attrs)
        base.create_dataset("Water Surface", data=water_surface)
        base.create_dataset("Flow", data=flow)

        geom_info = hdf.require_group("Results/Steady/Output/Geometry Info")
        geom_info.create_dataset("Node Info", data=np.array([b"RiverA ReachA 52.37 BR"]))

    return path


def _write_malformed_structure_list_hdf(path: Path) -> Path:
    attrs_path = (
        "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
        "Cross Sections/Cross Section Attributes"
    )
    attrs = np.array([(b"BR U",)], dtype=np.dtype([("Name", "S16")]))
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(attrs_path, data=attrs)
    return path


def test_empty_hdf_raises_actionable_error_without_warning_log(tmp_path, caplog):
    hdf_path = _write_empty_hdf(tmp_path / "no_results.p01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfStruc1D.get_structure_max_values(
                hdf_path,
                "River A",
                "Reach A",
                "52.37",
            )

    message = str(exc_info.value)
    assert "No steady or unsteady results were found" in message
    assert "no_results.p01.hdf" in message
    assert str(tmp_path) not in message
    assert [record for record in _records(caplog) if record.levelno >= logging.WARNING] == []


def test_unsteady_missing_cross_sections_raises_without_warning_log(tmp_path, caplog):
    hdf_path = _write_unsteady_shell(tmp_path / "missing_unsteady_xs.p01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfStruc1D.get_structure_max_values(
                hdf_path,
                "River A",
                "Reach A",
                "52.37",
            )

    message = str(exc_info.value)
    assert "Unsteady 1D structure extraction requires cross-section results" in message
    assert "Results/Unsteady/Output/Output Blocks" in message
    assert [record for record in _records(caplog) if record.levelno >= logging.WARNING] == []


def test_steady_missing_cross_section_attributes_raises_without_warning_log(
    tmp_path,
    caplog,
):
    hdf_path = _write_steady_shell(tmp_path / "missing_steady_attrs.p01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfStruc1D.get_structure_max_values(
                hdf_path,
                "River A",
                "Reach A",
                "52.37",
            )

    message = str(exc_info.value)
    assert "Steady 1D structure extraction requires cross-section attributes" in message
    assert "Cross Section Attributes" in message
    assert [record for record in _records(caplog) if record.levelno >= logging.WARNING] == []


def test_steady_flanking_structure_success_has_no_default_log_noise(
    tmp_path,
    caplog,
):
    hdf_path = _write_steady_flanking_structure_hdf(tmp_path / "bridge.p01.hdf")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = HdfStruc1D.get_structure_max_values(
            hdf_path,
            "River A",
            "Reach A",
            "52.37",
        )

    assert result["found"] is True
    assert result["max_hw"] == pytest.approx(573.13, abs=0.01)
    assert result["max_tw"] == pytest.approx(334.44, abs=0.01)
    assert result["max_flow"] == pytest.approx(31500.0)
    assert result["hw_source"] == "River A/Reach A/52.38 (US of 52.37)"
    assert result["tw_source"] == "River A/Reach A/52.00 (DS of 52.37)"
    assert _records(caplog) == []


def test_steady_flanking_structure_debug_retains_source_detail(tmp_path, caplog):
    hdf_path = _write_steady_flanking_structure_hdf(tmp_path / "bridge.p01.hdf")

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        HdfStruc1D.get_structure_max_values(
            hdf_path,
            "River A",
            "Reach A",
            "52.37",
        )

    messages = [record.getMessage() for record in _records(caplog)]
    assert any(
        "Steady structure 52.37: using flanking XS US=52.38, DS=52.00" in message
        for message in messages
    )
    assert [record for record in _records(caplog) if record.levelno >= logging.INFO] == []


def test_missing_target_structure_raises_without_error_log(tmp_path, caplog):
    hdf_path = _write_steady_flanking_structure_hdf(tmp_path / "bridge.p01.hdf")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfStruc1D.get_structure_max_values(
                hdf_path,
                "River A",
                "Reach A",
                "99.99",
            )

    message = str(exc_info.value)
    assert "No 1D structure results were found for River A/Reach A/RS 99.99" in message
    assert "bridge.p01.hdf" in message
    assert str(tmp_path) not in message
    assert _records(caplog) == []


def test_list_1d_structures_empty_hdf_is_quiet_by_default(tmp_path, caplog):
    hdf_path = _write_empty_hdf(tmp_path / "empty.p01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        structures = HdfStruc1D.list_1d_structures(hdf_path)

    assert structures.empty
    assert [record for record in _records(caplog) if record.levelno >= logging.WARNING] == []


def test_list_1d_structures_malformed_schema_raises_without_error_log(
    tmp_path,
    caplog,
):
    hdf_path = _write_malformed_structure_list_hdf(tmp_path / "malformed.p01.hdf")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises((KeyError, ValueError)):
            HdfStruc1D.list_1d_structures(hdf_path)

    assert _records(caplog) == []
