from __future__ import annotations

import logging
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf.HdfStruc import HdfStruc
from ras_commander.hdf.HdfBase import HdfBase


LOGGER_NAME = "ras_commander.hdf.HdfStruc"


def _hdf_struc_records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def _write_structure_hdf(
    path: Path,
    *,
    point_counts: tuple[int, ...] = (2,),
    include_centerline_points: bool = True,
) -> Path:
    attrs_dtype = np.dtype(
        [
            ("Type", "S16"),
            ("River", "S32"),
            ("Reach", "S32"),
            ("RS", "S16"),
        ]
    )
    attrs = np.array(
        [
            (b"Culvert", b"River A", b"Reach A", f"{1000 + i}".encode("utf-8"))
            for i in range(len(point_counts))
        ],
        dtype=attrs_dtype,
    )

    starts = []
    cursor = 0
    points = []
    for count in point_counts:
        starts.append(cursor)
        for offset in range(count):
            points.append((float(cursor + offset), float(offset)))
        cursor += count

    centerline_info = np.array(
        list(zip(starts, point_counts)),
        dtype=np.int32,
    )

    with h5py.File(path, "w") as hdf:
        structures = hdf.create_group("Geometry/Structures")
        structures.create_dataset("Attributes", data=attrs)
        structures.create_dataset("Centerline Info", data=centerline_info)
        if include_centerline_points:
            structures.create_dataset(
                "Centerline Points",
                data=np.array(points, dtype=np.float64),
            )
    return path


def _write_empty_plan_hdf(path: Path) -> Path:
    with h5py.File(path, "w"):
        pass
    return path


def test_optional_structure_datasets_absence_quiet_by_default(
    tmp_path,
    caplog,
    monkeypatch,
):
    hdf_path = _write_structure_hdf(tmp_path / "structures.g01.hdf")
    monkeypatch.setattr(HdfBase, "get_projection", staticmethod(lambda *_args, **_kwargs: None))

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        structures = HdfStruc.get_structures(hdf_path)

    assert len(structures) == 1
    assert [
        record for record in _hdf_struc_records(caplog)
        if record.levelno >= logging.WARNING
    ] == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        HdfStruc.get_structures(hdf_path)

    messages = [record.getMessage() for record in _hdf_struc_records(caplog)]
    assert any("Bridge Coefficient Attributes dataset absent" in msg for msg in messages)
    assert any("Table Info dataset is absent" in msg for msg in messages)
    assert any("Skipping Profile Data processing" in msg for msg in messages)
    assert any("structures.g01.hdf" in msg for msg in messages)


def test_missing_required_structure_dataset_warns_with_filename(
    tmp_path,
    caplog,
):
    hdf_path = _write_structure_hdf(
        tmp_path / "malformed.g01.hdf",
        include_centerline_points=False,
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        structures = HdfStruc.get_structures(hdf_path)

    assert structures.empty
    records = [
        record for record in _hdf_struc_records(caplog)
        if record.levelno >= logging.WARNING
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "Required structure dataset missing" in message
    assert "Geometry/Structures/Centerline Points" in message
    assert "malformed.g01.hdf" in message
    assert str(tmp_path) not in message


def test_invalid_centerline_geometry_logs_one_aggregate_warning(
    tmp_path,
    caplog,
    monkeypatch,
):
    hdf_path = _write_structure_hdf(
        tmp_path / "invalid_centerline.g01.hdf",
        point_counts=(2, 1),
    )
    monkeypatch.setattr(HdfBase, "get_projection", staticmethod(lambda *_args, **_kwargs: None))

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        structures = HdfStruc.get_structures(hdf_path)

    assert len(structures) == 1
    records = [
        record for record in _hdf_struc_records(caplog)
        if record.levelno >= logging.WARNING
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "Dropped 1 structure(s)" in message
    assert "invalid_centerline.g01.hdf" in message
    assert "indices: [1]" in message


def test_culvert_hydraulics_decodes_byte_type_values(
    tmp_path,
    caplog,
):
    hdf_path = _write_structure_hdf(tmp_path / "culvert.g02.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        culverts = HdfStruc.get_culvert_hydraulics(hdf_path)

    assert len(culverts) == 1
    assert culverts.iloc[0]["Type"] == "Culvert"
    assert culverts.iloc[0]["Structure_ID"] == 1

    records = [
        record for record in _hdf_struc_records(caplog)
        if record.levelno >= logging.WARNING
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "Culvert structures found in culvert.g02.hdf" in message
    assert "Geometry/Structures/Culvert Data is absent" in message
    assert "returning structure attributes only" in message
    assert str(tmp_path) not in message


def test_list_sa2d_connections_missing_group_is_debug_only(
    tmp_path,
    caplog,
):
    hdf_path = _write_empty_plan_hdf(tmp_path / "no_sa2d.p01.hdf")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert HdfStruc.list_sa2d_connections(hdf_path) == []

    assert [
        record for record in _hdf_struc_records(caplog)
        if record.levelno >= logging.WARNING
    ] == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        assert HdfStruc.list_sa2d_connections(hdf_path) == []

    assert any(
        record.levelno == logging.DEBUG
        and "No SA 2D Area Conn data found in no_sa2d.p01.hdf" in record.getMessage()
        for record in _hdf_struc_records(caplog)
    )
