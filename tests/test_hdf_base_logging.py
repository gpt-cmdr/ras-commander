from __future__ import annotations

import logging
from pathlib import Path

import h5py
import numpy as np
import pytest
from shapely.geometry import LineString

from ras_commander.hdf.HdfBase import HdfBase
from ras_commander.hdf.HdfUtils import HdfUtils


LOGGER_NAME = "ras_commander.hdf.HdfBase"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_empty_hdf(path: Path) -> Path:
    with h5py.File(path, "w"):
        pass
    return path


def _write_2d_flow_area_hdf(
    path: Path,
    *,
    include_cell_info: bool = True,
) -> Path:
    attrs = np.array(
        [(b"Mesh A",), (b"Mesh B",)],
        dtype=np.dtype([("Name", "S16")]),
    )
    with h5py.File(path, "w") as hdf:
        group = hdf.require_group("Geometry/2D Flow Areas")
        group.create_dataset("Attributes", data=attrs)
        if include_cell_info:
            group.create_dataset(
                "Cell Info",
                data=np.array([[0, 12], [0, 5]], dtype=np.int32),
            )
    return path


def _write_dataset_info_hdf(path: Path) -> Path:
    with h5py.File(path, "w") as hdf:
        group = hdf.require_group("Geometry")
        group.attrs["Description"] = "geometry root"
        group.create_dataset("Values", data=np.array([1, 2, 3], dtype=np.int32))
    return path


def _write_polyline_hdf(
    path: Path,
    *,
    include_parts: bool = True,
    include_points: bool = True,
) -> Path:
    with h5py.File(path, "w") as hdf:
        group = hdf.require_group("Geometry/River Centerlines")
        group.create_dataset(
            "Polyline Info",
            data=np.array([[0, 2, 0, 1]], dtype=np.int32),
        )
        if include_parts:
            group.create_dataset(
                "Polyline Parts",
                data=np.array([[0, 2]], dtype=np.int32),
            )
        if include_points:
            group.create_dataset(
                "Polyline Points",
                data=np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64),
            )
    return path


def test_2d_flow_area_absence_is_quiet_empty_result(tmp_path, caplog):
    hdf_path = _write_empty_hdf(tmp_path / "empty.p01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = HdfBase.get_2d_flow_area_names_and_counts(hdf_path)

    assert result == []
    assert _records(caplog) == []


def test_2d_flow_area_names_and_counts_success_no_default_logs(tmp_path, caplog):
    hdf_path = _write_2d_flow_area_hdf(tmp_path / "mesh.g01.hdf")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = HdfBase.get_2d_flow_area_names_and_counts(hdf_path)

    assert result == [("Mesh A", 12), ("Mesh B", 5)]
    assert _records(caplog) == []


def test_2d_flow_area_malformed_schema_raises_without_error_log(tmp_path, caplog):
    hdf_path = _write_2d_flow_area_hdf(
        tmp_path / "malformed.g01.hdf",
        include_cell_info=False,
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfBase.get_2d_flow_area_names_and_counts(hdf_path)

    message = str(exc_info.value)
    assert "2D flow area name/count extraction requires dataset" in message
    assert "Geometry/2D Flow Areas/Cell Info" in message
    assert "malformed.g01.hdf" in message
    assert str(tmp_path) not in message
    assert _records(caplog) == []


def test_get_attrs_missing_path_is_debug_only(tmp_path, caplog):
    hdf_path = _write_empty_hdf(tmp_path / "attrs.p01.hdf")

    with h5py.File(hdf_path, "r") as hdf:
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert HdfBase.get_attrs(hdf, "Geometry/Missing") == {}

    assert [record for record in _records(caplog) if record.levelno >= logging.WARNING] == []

    caplog.clear()
    with h5py.File(hdf_path, "r") as hdf:
        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            assert HdfBase.get_attrs(hdf, "Geometry/Missing") == {}

    messages = [record.getMessage() for record in _records(caplog)]
    assert any("Attribute path 'Geometry/Missing' not found" in msg for msg in messages)
    assert [record for record in _records(caplog) if record.levelno >= logging.WARNING] == []


def test_get_attrs_conversion_failure_raises_without_error_log(
    tmp_path,
    caplog,
    monkeypatch,
):
    hdf_path = tmp_path / "attrs.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        group = hdf.require_group("Geometry")
        group.attrs["Description"] = "test"

    def fail_convert(_attrs, prefix=None):
        raise RuntimeError("decode failed")

    monkeypatch.setattr(
        HdfUtils,
        "convert_hdf5_attrs_to_dict",
        staticmethod(fail_convert),
    )

    with h5py.File(hdf_path, "r") as hdf:
        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            with pytest.raises(ValueError) as exc_info:
                HdfBase.get_attrs(hdf, "Geometry")

    message = str(exc_info.value)
    assert "Failed to read HDF attributes at 'Geometry'" in message
    assert "attrs.p01.hdf" in message
    assert "decode failed" in message
    assert str(tmp_path) not in message
    assert _records(caplog) == []


def test_get_dataset_info_success_prints_requested_structure(tmp_path, capsys):
    hdf_path = _write_dataset_info_hdf(tmp_path / "dataset_info.p01.hdf")

    HdfBase.get_dataset_info(hdf_path, group_path="/Geometry")

    captured = capsys.readouterr()
    assert "Exploring group: /Geometry" in captured.out
    assert "Dataset: /Geometry/Values" in captured.out
    assert "Shape: (3,)" in captured.out


def test_get_dataset_info_missing_group_raises_without_stdout_error(
    tmp_path,
    capsys,
    caplog,
):
    hdf_path = _write_dataset_info_hdf(tmp_path / "dataset_info.p01.hdf")

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(KeyError) as exc_info:
            HdfBase.get_dataset_info(hdf_path, group_path="/Missing")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Group path '/Missing' not found in dataset_info.p01.hdf" in str(exc_info.value)
    assert str(tmp_path) not in str(exc_info.value)
    assert _records(caplog) == []


def test_polylines_missing_group_is_quiet_empty_result(tmp_path, caplog):
    hdf_path = _write_empty_hdf(tmp_path / "polylines.g01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        geoms = HdfBase.get_polylines_from_parts(
            hdf_path,
            "Geometry/River Centerlines",
        )

    assert geoms == []
    assert [record for record in _records(caplog) if record.levelno >= logging.WARNING] == []


def test_polylines_success_has_no_default_log_noise(tmp_path, caplog):
    hdf_path = _write_polyline_hdf(tmp_path / "polylines.g01.hdf")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        geoms = HdfBase.get_polylines_from_parts(
            hdf_path,
            "Geometry/River Centerlines",
        )

    assert len(geoms) == 1
    assert isinstance(geoms[0], LineString)
    assert list(geoms[0].coords) == [(0.0, 0.0), (1.0, 1.0)]
    assert _records(caplog) == []


def test_polylines_malformed_schema_raises_without_error_log(tmp_path, caplog):
    hdf_path = _write_polyline_hdf(
        tmp_path / "malformed_polylines.g01.hdf",
        include_points=False,
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(ValueError) as exc_info:
            HdfBase.get_polylines_from_parts(
                hdf_path,
                "Geometry/River Centerlines",
            )

    message = str(exc_info.value)
    assert "Polyline extraction requires dataset" in message
    assert "Geometry/River Centerlines/Polyline Points" in message
    assert "malformed_polylines.g01.hdf" in message
    assert str(tmp_path) not in message
    assert _records(caplog) == []


def test_strip_results_success_logs_basename_only(tmp_path, caplog):
    hdf_path = tmp_path / "strip.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.require_group("Results")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert HdfBase.strip_results(hdf_path) is True

    records = _records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    message = records[0].getMessage()
    assert "Stripped /Results group from strip.p01.hdf" in message
    assert str(tmp_path) not in message

    with h5py.File(hdf_path, "r") as hdf:
        assert "Results" not in hdf


def test_strip_results_no_results_group_is_debug_only(tmp_path, caplog):
    hdf_path = _write_empty_hdf(tmp_path / "strip_empty.p01.hdf")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert HdfBase.strip_results(hdf_path) is False

    assert _records(caplog) == []
