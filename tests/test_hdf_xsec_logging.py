from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf.HdfBase import HdfBase
from ras_commander.hdf.HdfXsec import HdfXsec


LOGGER_NAME = "ras_commander.hdf.HdfXsec"


def _hdf_xsec_records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_empty_geometry_hdf(path: Path) -> Path:
    with h5py.File(path, "w") as hdf:
        hdf.create_group("Geometry")
    return path


def _write_2d_style_partial_xsec_hdf(path: Path) -> Path:
    with h5py.File(path, "w") as hdf:
        xsecs = hdf.create_group("Geometry/Cross Sections")
        xsecs.create_group("Flow Distribution")
        xsecs.create_group("Hyd Property Tables")
    return path


def _write_malformed_xsec_hdf(path: Path) -> Path:
    with h5py.File(path, "w") as hdf:
        xsecs = hdf.create_group("Geometry/Cross Sections")
        xsecs.create_dataset("Polyline Info", data=np.array([[0, 2, 0, 1]], dtype=np.int32))
    return path


def _write_minimal_xsec_hdf(path: Path) -> Path:
    attrs_dtype = np.dtype(
        [
            ("Left Bank", "f8"),
            ("Right Bank", "f8"),
            ("River", "S16"),
            ("Reach", "S16"),
            ("RS", "S16"),
        ]
    )
    attrs = np.array([(2.0, 8.0, b"River A", b"Reach A", b"1000")], dtype=attrs_dtype)

    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Projection"] = CRS.from_epsg(4326).to_wkt()
        xsecs = geometry.create_group("Cross Sections")
        xsecs.create_dataset("Polyline Info", data=np.array([[0, 2, 0, 1]], dtype=np.int32))
        xsecs.create_dataset("Polyline Parts", data=np.array([[0, 2]], dtype=np.int32))
        xsecs.create_dataset("Polyline Points", data=np.array([[0.0, 0.0], [10.0, 0.0]]))
        xsecs.create_dataset("Station Elevation Info", data=np.array([[0, 2]], dtype=np.int32))
        xsecs.create_dataset("Station Elevation Values", data=np.array([[0.0, 100.0], [10.0, 101.0]]))
        xsecs.create_dataset("Attributes", data=attrs)
        xsecs.create_dataset("Manning's n Info", data=np.array([[0, 3]], dtype=np.int32))
        xsecs.create_dataset("Manning's n Values", data=np.array([[0.0, 0.05], [3.0, 0.04], [9.0, 0.06]]))
    return path


def _write_polyline_group(parent, group_name: str, count: int):
    group = parent.create_group(group_name)
    poly_info = []
    poly_parts = []
    points = []
    point_cursor = 0
    for idx in range(count):
        poly_info.append((point_cursor, 2, idx, 1))
        poly_parts.append((0, 2))
        points.extend([(float(idx), 0.0), (float(idx), 1.0)])
        point_cursor += 2
    group.create_dataset("Polyline Info", data=np.array(poly_info, dtype=np.int32))
    group.create_dataset("Polyline Parts", data=np.array(poly_parts, dtype=np.int32))
    group.create_dataset("Polyline Points", data=np.array(points, dtype=np.float64))
    return group


def _write_centerline_hdf(path: Path) -> Path:
    attrs_dtype = np.dtype(
        [
            ("River Name", "S16"),
            ("Reach Name", "S16"),
            ("US Type", "S16"),
            ("US Name", "S16"),
            ("DS Type", "S16"),
            ("DS Name", "S16"),
            ("Junction to US XS", "f8"),
            ("DS XS to Junction", "f8"),
        ]
    )
    attrs = np.array(
        [(b"River A", b"Reach A", b"External", b"", b"External", b"", 0.0, 1.5)],
        dtype=attrs_dtype,
    )
    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        group = _write_polyline_group(geometry, "River Centerlines", 1)
        group.create_dataset("Attributes", data=attrs)
    return path


def _write_edge_lines_hdf(path: Path, count: int = 3) -> Path:
    attrs_dtype = np.dtype([("Last Edited", "S24"), ("Float Field", "f8")])
    attrs = np.array(
        [(b"01Jan2024 0100", float(idx)) for idx in range(count)],
        dtype=attrs_dtype,
    )
    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        group = _write_polyline_group(geometry, "River Edge Lines", count)
        group.create_dataset("Attributes", data=attrs)
    return path


def _write_bank_lines_hdf(path: Path, count: int = 3) -> Path:
    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        _write_polyline_group(geometry, "River Bank Lines", count)
    return path


def test_2d_style_cross_sections_absence_is_debug_only(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    hdf_path = _write_2d_style_partial_xsec_hdf(tmp_path / "partial_2d.g01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        xsecs = HdfXsec.get_cross_sections(hdf_path)

    assert xsecs.empty
    assert [
        record for record in _hdf_xsec_records(caplog)
        if record.levelno >= logging.WARNING
    ] == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        HdfXsec.get_cross_sections(hdf_path)

    assert any(
        "No cross-section geometry datasets found in partial_2d.g01.hdf" in record.getMessage()
        for record in _hdf_xsec_records(caplog)
    )


def test_malformed_cross_sections_warn_once_with_filename(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    hdf_path = _write_malformed_xsec_hdf(tmp_path / "malformed.g01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        xsecs = HdfXsec.get_cross_sections(hdf_path)

    assert xsecs.empty
    records = [
        record for record in _hdf_xsec_records(caplog)
        if record.levelno >= logging.WARNING
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "Cross-section geometry in malformed.g01.hdf is missing required dataset(s)" in message
    assert "Geometry/Cross Sections/Polyline Parts" in message
    assert str(tmp_path) not in message


def test_optional_river_geometry_absence_quiet_by_default(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    hdf_path = _write_empty_geometry_hdf(tmp_path / "empty.g01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert HdfXsec.get_river_centerlines(hdf_path).empty
        assert HdfXsec.get_river_edge_lines(hdf_path).empty
        assert HdfXsec.get_river_bank_lines(hdf_path).empty
        assert HdfXsec.get_river_stationing(gpd.GeoDataFrame()).empty

    assert [
        record for record in _hdf_xsec_records(caplog)
        if record.levelno >= logging.WARNING
    ] == []


def test_river_reaches_handles_mixed_byte_and_numeric_attributes(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    hdf_path = _write_centerline_hdf(tmp_path / "centerlines.g01.hdf")
    monkeypatch.setattr(HdfBase, "get_projection", staticmethod(lambda *_args, **_kwargs: "EPSG:4326"))

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        reaches = HdfXsec.get_river_reaches(hdf_path)

    assert len(reaches) == 1
    assert reaches.iloc[0]["River Name"] == "River A"
    assert reaches.iloc[0]["DS XS to Junction"] == pytest.approx(1.5)
    assert [
        record for record in _hdf_xsec_records(caplog)
        if record.levelno >= logging.ERROR
    ] == []


def test_river_edge_lines_handles_attributes_and_odd_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    hdf_path = _write_edge_lines_hdf(tmp_path / "edges.g01.hdf", count=3)
    monkeypatch.setattr(HdfBase, "get_projection", staticmethod(lambda *_args, **_kwargs: "EPSG:4326"))

    edges = HdfXsec.get_river_edge_lines(hdf_path)

    assert len(edges) == 3
    assert edges["bank_side"].tolist() == ["Left", "Right", "Left"]
    assert edges["Float Field"].tolist() == [0.0, 1.0, 2.0]


def test_river_bank_lines_handles_odd_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    hdf_path = _write_bank_lines_hdf(tmp_path / "banks.g01.hdf", count=3)
    monkeypatch.setattr(HdfBase, "get_projection", staticmethod(lambda *_args, **_kwargs: "EPSG:4326"))

    banks = HdfXsec.get_river_bank_lines(hdf_path)

    assert len(banks) == 3
    assert banks["bank_side"].tolist() == ["Left", "Right", "Left"]


def test_cross_sections_assigns_geometry_crs(tmp_path: Path):
    hdf_path = _write_minimal_xsec_hdf(tmp_path / "xsecs.g01.hdf")

    xsecs = HdfXsec.get_cross_sections(hdf_path)

    assert len(xsecs) == 1
    assert xsecs.crs == CRS.from_epsg(4326)
