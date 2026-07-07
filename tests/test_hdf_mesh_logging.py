"""Logging behavior tests for direct HdfMesh 2D data APIs."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfMesh


LOGGER_NAME = "ras_commander.hdf.HdfMesh"


def _write_empty_hdf(path: Path) -> None:
    with h5py.File(path, "w") as hdf_file:
        hdf_file.create_group("Geometry")


def _write_mesh_hdf_without_preprocessor_tables(
    path: Path,
    mesh_name: str = "MainArea",
) -> None:
    attrs_dtype = np.dtype([("Name", "S32")])
    attrs = np.array([(mesh_name.encode("utf-8"),)], dtype=attrs_dtype)

    with h5py.File(path, "w") as hdf_file:
        hdf_file.create_dataset("Geometry/2D Flow Areas/Attributes", data=attrs)
        hdf_file.create_group(f"Geometry/2D Flow Areas/{mesh_name}")


def _hdf_mesh_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME
    ]


def test_missing_face_property_tables_logs_preprocessor_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Direct face-property table reads should explain the required preprocessing."""
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_mesh_hdf_without_preprocessor_tables(geom_hdf)

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = HdfMesh.get_mesh_face_property_tables(geom_hdf)

    assert list(result) == ["MainArea"]
    assert result["MainArea"].empty
    messages = _hdf_mesh_messages(caplog)
    assert len(messages) == 1
    assert "Face property tables not found for mesh 'MainArea'" in messages[0]
    assert "run the geometry preprocessor" in messages[0]
    assert "Faces Area Elevation Info" in messages[0]
    assert "Faces Area Elevation Values" in messages[0]


def test_missing_cell_property_tables_logs_preprocessor_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Direct cell volume/elevation table reads should point to geompre."""
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_mesh_hdf_without_preprocessor_tables(geom_hdf)

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = HdfMesh.get_mesh_cell_property_tables(geom_hdf)

    assert list(result) == ["MainArea"]
    assert result["MainArea"].empty
    messages = _hdf_mesh_messages(caplog)
    assert len(messages) == 1
    assert "Cell volume/elevation tables not found for mesh 'MainArea'" in messages[0]
    assert "run the geometry preprocessor" in messages[0]
    assert "Cells Volume Elevation Info" in messages[0]
    assert "Cells Volume Elevation Values" in messages[0]


@pytest.mark.parametrize(
    "method_name",
    ["get_mesh_face_property_tables", "get_mesh_cell_property_tables"],
)
def test_no_2d_mesh_areas_logs_direct_api_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    method_name: str,
):
    """No mesh areas is a direct API failure, not a silent optional branch."""
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_empty_hdf(geom_hdf)
    method = getattr(HdfMesh, method_name)

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = method(geom_hdf)

    assert result == {}
    messages = _hdf_mesh_messages(caplog)
    assert len(messages) == 1
    assert "No 2D mesh areas found" in messages[0]
    assert "requires a geometry HDF with 2D Flow Areas" in messages[0]


def test_missing_mannings_calibration_table_logs_direct_api_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """A direct calibration-table read should log that the requested data is absent."""
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_mesh_hdf_without_preprocessor_tables(geom_hdf)

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = HdfMesh.get_mannings_calibration_table(geom_hdf)

    assert result is None
    messages = _hdf_mesh_messages(caplog)
    assert len(messages) == 1
    assert "No Manning's n calibration table found" in messages[0]
    assert "create Manning's n calibration regions" in messages[0]
