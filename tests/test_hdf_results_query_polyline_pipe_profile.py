"""Tests for RAS Mapper-backed pipe-network polyline profile extraction."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import shape

from ras_commander import HdfResultsQuery
from ras_commander.dotnet.clr_bootstrap import is_hecras_available

pytestmark = pytest.mark.skipif(
    not is_hecras_available(),
    reason="HEC-RAS install + pythonnet required",
)

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_DAVIS_PIPE_PLAN = Path(
    "C:/GH/ras-commander-hydro/testdata/DavisStormSystem.p02.hdf"
)
DAVIS_POLYLINE = DATA_DIR / "davis_pipe_conduit_134_polyline.geojson"
DAVIS_VELOCITY_PROFILE = DATA_DIR / "davis_pipe_velocity_profile_p02_t005.csv"
DAVIS_FLOW_PROFILE = DATA_DIR / "davis_pipe_flow_profile_p02_t005.csv"
DAVIS_VELOCITY_TS = DATA_DIR / "davis_pipe_velocity_timeseries_p02_t005_t006.csv"
DAVIS_FLOW_TS = DATA_DIR / "davis_pipe_flow_timeseries_p02_t005_t006.csv"


def _davis_pipe_plan() -> Path:
    env_path = os.environ.get("RAS_COMMANDER_DAVIS_PIPE_RESULTS")
    return Path(env_path) if env_path else DEFAULT_DAVIS_PIPE_PLAN


def _require_davis_pipe_plan() -> Path:
    plan_hdf = _davis_pipe_plan()
    if not plan_hdf.exists():
        pytest.skip(f"Davis pipe-network plan HDF not staged: {plan_hdf}")
    return plan_hdf


def _load_polyline():
    geojson = json.loads(DAVIS_POLYLINE.read_text(encoding="utf-8"))
    return shape(geojson["features"][0]["geometry"])


def _assert_numeric_matches(actual: pd.DataFrame, expected: pd.DataFrame, column: str) -> None:
    np.testing.assert_allclose(
        actual[column].to_numpy(dtype=float),
        expected[column].to_numpy(dtype=float),
        equal_nan=True,
    )


def test_pipe_velocity_and_flow_profiles_match_rasmapper_fixtures() -> None:
    plan_hdf = _require_davis_pipe_plan()
    polyline = _load_polyline()

    velocity = HdfResultsQuery.query_polyline_pipe_velocity_profile(
        plan_hdf,
        polyline,
        time_index=5,
        sample_spacing=40.0,
        terrain_raster=plan_hdf,
    )
    flow = HdfResultsQuery.query_polyline_pipe_flow_profile(
        plan_hdf,
        polyline,
        time_index=5,
        sample_spacing=40.0,
        terrain_raster=plan_hdf,
    )

    expected_velocity = pd.read_csv(DAVIS_VELOCITY_PROFILE)
    expected_flow = pd.read_csv(DAVIS_FLOW_PROFILE)
    assert len(velocity) == len(expected_velocity) == 29
    assert len(flow) == len(expected_flow) == 29
    assert velocity["velocity_mag"].notna().sum() == 22
    assert flow["flow"].notna().sum() == 22
    assert velocity.attrs["velocity_source"] == [
        "RasMapperLib.Render.VelocityRendererPipe"
    ]
    assert flow.attrs["flow_source"] == ["RasMapperLib.Render.FlowRendererPipe"]
    _assert_numeric_matches(velocity, expected_velocity, "velocity_mag")
    _assert_numeric_matches(flow, expected_flow, "flow")


def test_pipe_velocity_and_flow_timeseries_match_rasmapper_fixtures() -> None:
    plan_hdf = _require_davis_pipe_plan()
    polyline = _load_polyline()

    velocity = HdfResultsQuery.query_polyline_pipe_velocity_timeseries(
        plan_hdf,
        polyline,
        time_range=(5, 7),
        sample_spacing=40.0,
        terrain_raster=plan_hdf,
    )
    flow = HdfResultsQuery.query_polyline_pipe_flow_timeseries(
        plan_hdf,
        polyline,
        time_range=(5, 7),
        sample_spacing=40.0,
        terrain_raster=plan_hdf,
    )

    expected_velocity = pd.read_csv(DAVIS_VELOCITY_TS)
    expected_flow = pd.read_csv(DAVIS_FLOW_TS)
    assert len(velocity) == len(expected_velocity) == 58
    assert len(flow) == len(expected_flow) == 58
    assert sorted(velocity["time_index"].unique().tolist()) == [5, 6]
    assert velocity.attrs["velocity_source"] == [
        "RasMapperLib.Render.VelocityPipeTimeSeries"
    ]
    assert flow.attrs["flow_source"] == ["RasMapperLib.Render.FlowPipeTimeSeries"]
    _assert_numeric_matches(velocity, expected_velocity, "velocity_mag")
    _assert_numeric_matches(flow, expected_flow, "flow")
