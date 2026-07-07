"""Logging behavior tests for HdfBndry geometry extraction APIs."""

from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf import HdfBndry


LOGGER_NAME = "ras_commander.hdf.HdfBndry"


def _hdf_bndry_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME
    ]


def _write_empty_geometry_hdf(path: Path) -> None:
    with h5py.File(path, "w") as hdf_file:
        hdf_file.create_group("Geometry")


def _write_invalid_breaklines_hdf(path: Path) -> None:
    attributes_dtype = np.dtype([("Name", "S32")])
    attributes = np.array(
        [(b"ZeroLength",), (b"SinglePoint",), (b"MultipartInvalid",)],
        dtype=attributes_dtype,
    )

    with h5py.File(path, "w") as hdf_file:
        group = hdf_file.create_group("Geometry/2D Flow Area Break Lines")
        group.create_dataset("Attributes", data=attributes)
        group.create_dataset(
            "Polyline Info",
            data=np.array(
                [
                    (0, 0, 0, 1),
                    (0, 1, 0, 1),
                    (0, 2, 0, 2),
                ],
                dtype=np.int32,
            ),
        )
        group.create_dataset(
            "Polyline Parts",
            data=np.array([(0, 1), (1, 1)], dtype=np.int32),
        )
        group.create_dataset(
            "Polyline Points",
            data=np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64),
        )


def _write_reference_lines_without_type_hdf(path: Path) -> None:
    attributes_dtype = np.dtype([("Name", "S32"), ("SA-2D", "S32")])
    attributes = np.array([(b"Line A", b"Mesh 1")], dtype=attributes_dtype)

    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(4326).to_wkt()
        group = hdf_file.create_group("Geometry/Reference Lines")
        group.create_dataset("Attributes", data=attributes)
        group.create_dataset(
            "Polyline Info",
            data=np.array([(0, 2, 0, 1)], dtype=np.int32),
        )
        group.create_dataset("Polyline Parts", data=np.array([(0, 2)], dtype=np.int32))
        group.create_dataset(
            "Polyline Points",
            data=np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64),
        )


def test_optional_missing_boundary_groups_are_quiet_by_default(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_empty_geometry_hdf(geom_hdf)

    with caplog.at_level("WARNING", logger=LOGGER_NAME):
        assert HdfBndry.get_bc_lines(geom_hdf).empty
        assert HdfBndry.get_breaklines(geom_hdf).empty
        assert HdfBndry.get_refinement_regions(geom_hdf).empty
        assert HdfBndry.get_reference_lines(geom_hdf).empty
        assert HdfBndry.get_reference_points(geom_hdf).empty

    assert _hdf_bndry_messages(caplog) == []


def test_optional_missing_boundary_groups_log_debug_context(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_empty_geometry_hdf(geom_hdf)

    with caplog.at_level("DEBUG", logger=LOGGER_NAME):
        HdfBndry.get_breaklines(geom_hdf)
        HdfBndry.get_reference_lines(geom_hdf)

    messages = _hdf_bndry_messages(caplog)
    assert any("Breaklines group" in message for message in messages)
    assert any("Reference lines attributes group" in message for message in messages)
    optional_group_messages = [
        message
        for message in messages
        if "Breaklines group" in message
        or "Reference lines attributes group" in message
    ]
    assert all(str(tmp_path) not in message for message in optional_group_messages)


def test_invalid_breaklines_warning_includes_counts_not_full_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_invalid_breaklines_hdf(geom_hdf)

    with caplog.at_level("WARNING", logger=LOGGER_NAME):
        result = HdfBndry.get_breaklines(geom_hdf)

    assert result.empty
    messages = _hdf_bndry_messages(caplog)
    assert len(messages) == 1
    assert "No valid breaklines found in model.g01.hdf" in messages[0]
    assert "skipped 3 invalid breaklines" in messages[0]
    assert "zero_length=1" in messages[0]
    assert "single_point=1" in messages[0]
    assert "other=1" in messages[0]
    assert str(tmp_path) not in messages[0]


def test_boundary_parse_errors_include_hdf_path_and_group(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    with h5py.File(geom_hdf, "w") as hdf_file:
        hdf_file.create_group("Geometry/Boundary Condition Lines")

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = HdfBndry.get_bc_lines(geom_hdf)

    assert result.empty
    messages = _hdf_bndry_messages(caplog)
    assert len(messages) == 1
    assert str(geom_hdf) in messages[0]
    assert "Geometry/Boundary Condition Lines" in messages[0]


def test_reference_line_missing_type_logs_debug_fallback(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_reference_lines_without_type_hdf(geom_hdf)

    with caplog.at_level("DEBUG", logger=LOGGER_NAME):
        result = HdfBndry.get_reference_lines(geom_hdf)

    assert len(result) == 1
    assert result["Type"].tolist() == [""]
    messages = _hdf_bndry_messages(caplog)
    assert any("using blank Type values" in message for message in messages)
