from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.hdf.HdfResultsQuery import HdfResultsQuery


hdf_results_query_module = importlib.import_module(
    "ras_commander.hdf.HdfResultsQuery"
)
LOGGER_NAME = "ras_commander.hdf.HdfResultsQuery"


def _records(caplog: pytest.LogCaptureFixture):
    return [record for record in caplog.records if record.name == LOGGER_NAME]


def test_large_distance_warning_uses_query_context(caplog):
    distances = np.array([20.0, 1001.0, 1054.85])

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        hdf_results_query_module._warn_on_large_distances(
            distances,
            point_label="profile sample point",
        )

    records = _records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "2 profile sample points" in message
    assert "max distance 1054.85" in message
    assert "Verify CRS/units" in message
    assert "outside the 2D mesh" in message
    assert "This often indicates a CRS mismatch" not in message


def test_large_distance_warning_is_silent_below_threshold(caplog):
    distances = np.array([20.0, 999.99])

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        hdf_results_query_module._warn_on_large_distances(distances)

    assert _records(caplog) == []


def test_query_profile_labels_distance_warnings_as_profile_samples(
    tmp_path,
    monkeypatch,
):
    plan_hdf = tmp_path / "Example.p01.hdf"
    with h5py.File(plan_hdf, "w"):
        pass

    captured = {}

    def fake_query_points_core(
        plan_hdf_path,
        points_df,
        variable,
        time_index,
        method,
        ras_object=None,
        point_label="query point",
    ):
        captured["plan_hdf_path"] = plan_hdf_path
        captured["point_label"] = point_label
        captured["method"] = method
        return pd.DataFrame(
            {
                "x": points_df["x"].to_numpy(dtype=float),
                "y": points_df["y"].to_numpy(dtype=float),
                "value": np.arange(len(points_df), dtype=float),
                "cell_id": np.arange(len(points_df), dtype=int),
                "mesh_name": ["Mesh"] * len(points_df),
                "distance": np.zeros(len(points_df), dtype=float),
            }
        )

    monkeypatch.setattr(
        hdf_results_query_module,
        "_query_points_core",
        fake_query_points_core,
    )

    result = HdfResultsQuery.query_profile(
        plan_hdf,
        x1=0.0,
        y1=0.0,
        x2=100.0,
        y2=0.0,
        n_points=3,
    )

    assert captured["plan_hdf_path"] == plan_hdf
    assert captured["point_label"] == "profile sample point"
    assert captured["method"] == "nearest"
    assert result["station"].tolist() == [0.0, 50.0, 100.0]


def test_resolve_geometry_hdf_preserves_plan_metadata_missing_path(tmp_path):
    plan_hdf = tmp_path / "Example.p01.hdf"
    with h5py.File(plan_hdf, "w") as hdf:
        plan_info = hdf.require_group("Plan Data/Plan Information")
        plan_info.attrs["Geometry File"] = np.bytes_("Example.g09")

    ras_object = SimpleNamespace(
        plan_df=pd.DataFrame(),
        geom_df=pd.DataFrame(),
    )

    with pytest.raises(FileNotFoundError) as exc_info:
        hdf_results_query_module._resolve_geometry_hdf(
            plan_hdf,
            ras_object=ras_object,
        )

    message = str(exc_info.value)
    assert "Geometry HDF referenced by plan metadata was not found" in message
    assert "Example.g09.hdf" in message
    assert "Could not resolve geometry HDF" not in message
