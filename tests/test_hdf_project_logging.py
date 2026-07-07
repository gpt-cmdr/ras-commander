"""Logging behavior tests for HdfProject extent/bounds helpers."""

import logging
from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf import HdfProject


PROJECT_LOGGER = "ras_commander.hdf.HdfProject"
XSEC_LOGGER = "ras_commander.hdf.HdfXsec"


def _messages(caplog: pytest.LogCaptureFixture, logger_name: str) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == logger_name
    ]


def _write_2d_geometry_hdf(
    path: Path,
    *,
    epsg: int | None = 4326,
    perimeter: np.ndarray | None = None,
) -> None:
    perimeter = perimeter if perimeter is not None else np.array(
        [
            [-77.6, 40.9],
            [-77.3, 40.9],
            [-77.3, 41.1],
            [-77.6, 41.1],
            [-77.6, 40.9],
        ],
        dtype=np.float64,
    )
    attrs_dtype = np.dtype([("Name", "S32")])
    attrs = np.array([(b"Mesh 1",)], dtype=attrs_dtype)

    with h5py.File(path, "w") as hdf_file:
        if epsg is not None:
            hdf_file.attrs["Projection"] = CRS.from_epsg(epsg).to_wkt()
        hdf_file.create_dataset("Geometry/2D Flow Areas/Attributes", data=attrs)
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Mesh 1/Perimeter",
            data=perimeter,
        )


def _write_empty_geometry_hdf(path: Path, *, epsg: int | None = 4326) -> None:
    with h5py.File(path, "w") as hdf_file:
        if epsg is not None:
            hdf_file.attrs["Projection"] = CRS.from_epsg(epsg).to_wkt()
        hdf_file.create_group("Geometry")


def test_2d_only_bounds_skip_optional_1d_probe_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_2d_geometry_hdf(geom_hdf)

    with caplog.at_level(logging.WARNING):
        bounds = HdfProject.get_project_bounds_latlon(geom_hdf, buffer_percent=0.0)

    assert bounds[0] == pytest.approx(-77.6)
    assert bounds[2] == pytest.approx(-77.3)
    assert _messages(caplog, PROJECT_LOGGER) == []
    assert _messages(caplog, XSEC_LOGGER) == []


def test_empty_project_extent_logs_one_concise_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "empty.g01.hdf"
    _write_empty_geometry_hdf(geom_hdf)

    with caplog.at_level(logging.WARNING, logger=PROJECT_LOGGER):
        bounds = HdfProject.get_project_bounds_latlon(geom_hdf)

    assert bounds == (0.0, 0.0, 0.0, 0.0)
    messages = _messages(caplog, PROJECT_LOGGER)
    assert len(messages) == 1
    assert "No project geometries found in empty.g01.hdf" in messages[0]
    assert "returning empty extent and zero project-coordinate bounds" in messages[0]
    assert str(tmp_path) not in messages[0]


def test_missing_project_crs_logs_one_project_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "missing_crs.g01.hdf"
    _write_2d_geometry_hdf(geom_hdf, epsg=None)

    with caplog.at_level(logging.WARNING):
        bounds = HdfProject.get_project_bounds_latlon(geom_hdf, buffer_percent=0.0)

    assert bounds[0] == pytest.approx(-77.6)
    project_messages = _messages(caplog, PROJECT_LOGGER)
    assert len(project_messages) == 1
    assert "Project CRS unavailable for missing_crs.g01.hdf" in project_messages[0]
    assert "Pass project_crs=..." in project_messages[0]
    assert str(tmp_path) not in project_messages[0]


def test_invalid_wgs84_transform_logs_single_error_no_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "invalid_wgs84.g01.hdf"
    _write_2d_geometry_hdf(
        geom_hdf,
        epsg=4326,
        perimeter=np.array(
            [
                [1000.0, 1000.0],
                [1001.0, 1000.0],
                [1001.0, 1001.0],
                [1000.0, 1001.0],
                [1000.0, 1000.0],
            ],
            dtype=np.float64,
        ),
    )

    with caplog.at_level(logging.WARNING, logger=PROJECT_LOGGER):
        bounds = HdfProject.get_project_bounds_latlon(geom_hdf, buffer_percent=0.0)

    assert bounds == pytest.approx((1000.0, 1000.0, 1001.0, 1001.0))
    project_records = [
        record
        for record in caplog.records
        if record.name == PROJECT_LOGGER
    ]
    assert [record.levelno for record in project_records] == [logging.ERROR]
    assert (
        "CRS transformation failed for invalid_wgs84.g01.hdf"
        in project_records[0].getMessage()
    )
    assert "not WGS84" in project_records[0].getMessage()


def test_export_extent_geojson_info_uses_filename_debug_uses_full_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeExtent:
        crs = "EPSG:4326"

        def to_file(self, output_path, driver):
            Path(output_path).write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        HdfProject,
        "get_project_extent",
        staticmethod(lambda *args, **kwargs: (FakeExtent(), (0.0, 0.0, 1.0, 1.0))),
    )
    output_path = tmp_path / "nested" / "extent.geojson"
    output_path.parent.mkdir()

    with caplog.at_level(logging.DEBUG, logger=PROJECT_LOGGER):
        result = HdfProject.export_extent_geojson("model.g01.hdf", output_path)

    assert result == output_path
    messages = _messages(caplog, PROJECT_LOGGER)
    assert "Exported project extent to extent.geojson" in messages
    assert any(str(output_path) in message for message in messages)
    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == PROJECT_LOGGER and record.levelno == logging.INFO
    ]
    assert info_messages == ["Exported project extent to extent.geojson"]
