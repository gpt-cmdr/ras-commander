import importlib
import logging
from datetime import datetime, timedelta
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.RasModPuls import RasModPuls


MODPULS_LOGGER = "ras_commander.RasModPuls"


def _modpuls_records(caplog):
    return [record for record in caplog.records if record.name == MODPULS_LOGGER]


def test_compute_subreach_count_is_quiet_at_info_and_detailed_at_debug(caplog):
    caplog.set_level(logging.INFO, logger=MODPULS_LOGGER)

    assert RasModPuls.compute_subreach_count(6.0, dt_hours=1.0) == 9
    assert _modpuls_records(caplog) == []

    caplog.clear()
    caplog.set_level(logging.DEBUG, logger=MODPULS_LOGGER)

    assert RasModPuls.compute_subreach_count(6.0, dt_hours=1.0) == 9

    messages = [record.getMessage() for record in _modpuls_records(caplog)]
    assert "Subreach count: n=9 (travel_time=6.0h, dt=1.0h, factor=1.5)" in messages


def test_write_stepped_hydrograph_logs_one_concise_info(monkeypatch, caplog):
    captured = {}

    def fake_set_boundary_inline_hydrograph(**kwargs):
        captured.update(kwargs)

    ras_unsteady_module = importlib.import_module("ras_commander.RasUnsteady")
    monkeypatch.setattr(
        ras_unsteady_module.RasUnsteady,
        "set_boundary_inline_hydrograph",
        staticmethod(fake_set_boundary_inline_hydrograph),
    )
    caplog.set_level(logging.DEBUG, logger=MODPULS_LOGGER)

    flows = RasModPuls.write_stepped_hydrograph(
        "project.u01",
        flows=[500, 1000, 2000, 5000],
        step_duration_hours=3.0,
        warmup_flow=100.0,
        warmup_duration_hours=1.0,
        river="River",
        reach="Reach",
        station="1000",
    )

    assert flows == [500, 1000, 2000, 5000]
    assert len(captured["hydrograph_df"]) == 14

    records = _modpuls_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == ["Stepped hydrograph written: 4 steps over 13.0 hours"]
    assert all("[500, 1000, 2000, 5000]" not in message for message in info_messages)
    assert any("[500, 1000, 2000, 5000]" in message for message in debug_messages)
    assert any("target=project.u01" in message for message in debug_messages)


def test_extract_storage_outflow_keeps_one_info_summary(
    tmp_path,
    monkeypatch,
    caplog,
):
    plan_hdf = tmp_path / "project.p01.hdf"
    flow_area_name = "Mesh"

    with h5py.File(plan_hdf, "w") as hdf:
        flow_group = hdf.create_group(
            "Results/Unsteady/Output/Output Blocks/Base Output/"
            f"Unsteady Time Series/2D Flow Areas/{flow_area_name}"
        )
        flow_group.create_dataset(
            "Face Flow",
            data=np.array(
                [
                    [10.0, -20.0],
                    [20.0, -30.0],
                    [30.0, -40.0],
                    [40.0, -50.0],
                ]
            ),
        )
        flow_group.create_dataset(
            "Water Surface",
            data=np.array(
                [
                    [101.0, 102.0, 100.0],
                    [102.0, 103.0, 100.0],
                    [103.0, 104.0, 100.0],
                    [104.0, 105.0, 100.0],
                ]
            ),
        )
        geom_group = hdf.create_group(f"Geometry/2D Flow Areas/{flow_area_name}")
        geom_group.create_dataset(
            "Cells Minimum Elevation",
            data=np.array([100.0, 100.0, 100.0]),
        )
        geom_group.create_dataset(
            "Cells Surface Area",
            data=np.array([1000.0, 2000.0, 3000.0]),
        )

    timestamps = [datetime(2026, 1, 1) + timedelta(hours=i) for i in range(4)]

    hdf_base_module = importlib.import_module("ras_commander.hdf.HdfBase")
    hdf_mesh_module = importlib.import_module("ras_commander.hdf.HdfMesh")
    monkeypatch.setattr(
        hdf_base_module.HdfBase,
        "get_unsteady_timestamps",
        staticmethod(lambda _hdf: timestamps),
    )
    monkeypatch.setattr(
        hdf_mesh_module.HdfMesh,
        "get_mesh_cell_faces",
        staticmethod(lambda _path: pd.DataFrame({"mesh_name": [flow_area_name, flow_area_name]})),
    )
    monkeypatch.setattr(
        hdf_mesh_module.HdfMesh,
        "get_faces_along_profile_line",
        staticmethod(lambda **_kwargs: pd.DataFrame({"face_id": [0, 1]})),
    )
    monkeypatch.setattr(
        RasModPuls,
        "_get_geom_hdf_path",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    caplog.set_level(logging.DEBUG, logger=MODPULS_LOGGER)

    sq_df = RasModPuls.extract_storage_outflow(
        plan_hdf,
        downstream_profile_line=object(),
        plan_number="01",
        step_duration_hours=1.0,
        warmup_duration_hours=0.0,
        n_steps=3,
        flow_area_name=flow_area_name,
    )

    assert list(sq_df.columns) == ["storage_acft", "outflow_cfs"]
    records = _modpuls_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]

    assert len(info_messages) == 1
    assert info_messages[0].startswith(
        "S-Q extraction complete: 4 rows, 3 plateau timesteps, 2 faces"
    )
    assert any(str(plan_hdf) in message for message in debug_messages)
    assert any("Found 2 faces" in message for message in debug_messages)
    assert any("Detected 3 plateau timesteps" in message for message in debug_messages)


def test_reference_line_failures_do_not_add_duplicate_generic_warning(
    tmp_path,
    monkeypatch,
    caplog,
):
    geom_hdf = tmp_path / "geometry.g01.hdf"
    geom_hdf.write_bytes(b"")

    hdf_bndry_module = importlib.import_module("ras_commander.hdf.HdfBndry")
    hdf_mesh_module = importlib.import_module("ras_commander.hdf.HdfMesh")
    monkeypatch.setattr(
        hdf_bndry_module.HdfBndry,
        "get_bc_lines",
        staticmethod(lambda _path: pd.DataFrame({"Name": ["Existing BC"]})),
    )
    monkeypatch.setattr(
        hdf_mesh_module.HdfMesh,
        "get_mesh_cell_faces",
        staticmethod(lambda _path: pd.DataFrame({"mesh_name": ["Mesh"]})),
    )
    caplog.set_level(logging.DEBUG, logger=MODPULS_LOGGER)

    assert RasModPuls.add_reference_lines_from_bc_lines(
        geom_hdf,
        ["Missing BC"],
    ) == 0

    warning_messages = [
        record.getMessage()
        for record in _modpuls_records(caplog)
        if record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage()
        for record in _modpuls_records(caplog)
        if record.levelno == logging.DEBUG
    ]
    assert warning_messages == ["BC line 'Missing BC' not found in geometry HDF"]
    assert "No reference lines created" in debug_messages


def test_write_reference_lines_failure_raises_without_error_log(tmp_path, caplog):
    geom_hdf = tmp_path / "not_hdf.g01.hdf"
    geom_hdf.write_text("not an hdf file", encoding="utf-8")
    caplog.set_level(logging.DEBUG, logger=MODPULS_LOGGER)

    with pytest.raises(OSError):
        RasModPuls._write_reference_lines_to_hdf(
            geom_hdf,
            [{"name": "Line A", "geometry": object()}],
            "Mesh",
        )

    records = _modpuls_records(caplog)
    assert all(record.levelno < logging.ERROR for record in records)
    assert any(
        record.levelno == logging.DEBUG
        and "Failed to write reference lines to HDF" in record.getMessage()
        and record.exc_info
        for record in records
    )
