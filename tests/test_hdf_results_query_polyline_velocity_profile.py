"""Tests for RAS Mapper-backed polyline velocity profile extraction."""

from __future__ import annotations

import json
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, shape

from ras_commander import HdfResultsQuery
from ras_commander.dotnet.clr_bootstrap import is_hecras_available

pytestmark = pytest.mark.skipif(
    not is_hecras_available(),
    reason="HEC-RAS install + pythonnet required",
)

EXPECTED_COLUMNS = [
    "station",
    "x",
    "y",
    "mesh_name",
    "face_id",
    "velocity_x",
    "velocity_y",
    "velocity_mag",
    "depth",
    "terrain_elev",
]
EXPECTED_WSE_COLUMNS = [
    "station",
    "x",
    "y",
    "mesh_name",
    "face_id",
    "wse",
    "depth",
    "terrain_elev",
]
EXPECTED_FLOW_COLUMNS = [
    "station",
    "x",
    "y",
    "mesh_name",
    "face_id",
    "flow",
    "depth",
    "terrain_elev",
]
EXPECTED_VELOCITY_TS_COLUMNS = [
    "time_index",
    "time",
    "station",
    "x",
    "y",
    "mesh_name",
    "face_id",
    "velocity_x",
    "velocity_y",
    "velocity_mag",
    "depth",
    "terrain_elev",
]

DATA_DIR = Path(__file__).parent / "data"
REFERENCE_CSV = DATA_DIR / "bald_eagle_velocity_profile_p06.csv"
REFERENCE_GEOJSON = DATA_DIR / "bald_eagle_velocity_profile_p06_polyline.geojson"
REFERENCE_MANIFEST = DATA_DIR / "bald_eagle_velocity_profile_p06_manifest.json"
CHIPPEWA_PLAN = Path(
    "H:/Symphony/ras-commander/CLB-214/profile_line_flow_validation/"
    "project/Chippewa_2D_profile_line_flow/Chippewa_2D.p02.hdf"
)
CHIPPEWA_POLYLINE = DATA_DIR / "chippewa_upstream_profile_line.geojson"
CHIPPEWA_VELOCITY_TS_CSV = DATA_DIR / "chippewa_velocity_timeseries_upstream_p02.csv"
CHIPPEWA_WSE_TS_CSV = DATA_DIR / "chippewa_wse_timeseries_upstream_p02.csv"
DEFAULT_BALD_EAGLE_PLAN = Path(
    "H:/Symphony/RASDecomp/CLB-850/inputs/"
    "BaldEagleCrkMulti2D_722_gridded/BaldEagleDamBrk.p06.hdf"
)


def _load_manifest() -> dict:
    return json.loads(REFERENCE_MANIFEST.read_text(encoding="utf-8"))


def _load_polyline() -> LineString:
    geojson = json.loads(REFERENCE_GEOJSON.read_text(encoding="utf-8"))
    return shape(geojson["features"][0]["geometry"])


def _load_chippewa_polyline() -> LineString:
    geojson = json.loads(CHIPPEWA_POLYLINE.read_text(encoding="utf-8"))
    return shape(geojson["features"][0]["geometry"])


def _bald_eagle_plan_hdf() -> Path:
    env_path = os.environ.get("RAS_COMMANDER_BALD_EAGLE_RESULTS")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_dir():
            direct = candidate / "BaldEagleDamBrk.p06.hdf"
            if direct.exists():
                return direct
            matches = sorted(candidate.glob("BaldEagleDamBrk.p*.hdf"))
            if matches:
                return matches[0]
        else:
            return candidate
    return DEFAULT_BALD_EAGLE_PLAN


def _bald_eagle_terrain_hdf(plan_hdf: Path) -> Path | None:
    candidate = plan_hdf.parent / "Terrain" / "Terrain50.hdf"
    return candidate if candidate.exists() else None


def _require_bald_eagle_plan() -> Path:
    plan_hdf = _bald_eagle_plan_hdf()
    if not plan_hdf.exists():
        pytest.skip(f"Bald Eagle plan HDF not staged: {plan_hdf}")
    return plan_hdf


def _require_chippewa_plan() -> Path:
    if not CHIPPEWA_PLAN.exists():
        pytest.skip(f"Chippewa validation plan HDF not staged: {CHIPPEWA_PLAN}")
    return CHIPPEWA_PLAN


def test_matches_ras_mapper_fixture() -> None:
    manifest = _load_manifest()
    plan_hdf = _require_bald_eagle_plan()
    terrain_hdf = _bald_eagle_terrain_hdf(plan_hdf)
    reference = pd.read_csv(REFERENCE_CSV)

    profile = HdfResultsQuery.query_polyline_velocity_profile(
        plan_hdf,
        _load_polyline(),
        time_index=int(manifest["time_index"]),
        sample_spacing=float(manifest["max_segment_len"]),
        terrain_raster=terrain_hdf,
    )

    assert len(profile) == int(manifest["row_count"])
    valid = reference["velocity_mag"].notna() & profile["velocity_mag"].notna()
    assert int(valid.sum()) == int(manifest["valid_velocity_rows"])

    error = (
        profile.loc[valid, "velocity_mag"].to_numpy(dtype=float)
        - reference.loc[valid, "velocity_mag"].to_numpy(dtype=float)
    )
    rms_error = float(np.sqrt(np.mean(error * error)))
    threshold = 0.05 * float(reference.loc[valid, "velocity_mag"].mean())
    assert rms_error <= threshold


def test_returns_expected_schema() -> None:
    manifest = _load_manifest()
    plan_hdf = _require_bald_eagle_plan()

    profile = HdfResultsQuery.query_polyline_velocity_profile(
        plan_hdf,
        _load_polyline(),
        time_index=int(manifest["time_index"]),
        sample_spacing=float(manifest["max_segment_len"]),
        terrain_raster=_bald_eagle_terrain_hdf(plan_hdf),
    )

    assert list(profile.columns) == EXPECTED_COLUMNS
    for key in [
        "unit_system",
        "length_units",
        "velocity_units",
        "depth_units",
        "sample_spacing",
        "velocity_source",
        "ras_version",
    ]:
        assert key in profile.attrs
    assert profile.attrs["velocity_source"] == [
        "RasMapperLib.Render.VelocityRenderer"
    ]


def test_rejects_2d_bridge(tmp_path: Path) -> None:
    plan_hdf = tmp_path / "BridgeModel.p01.hdf"
    geom_hdf = tmp_path / "BridgeModel.g01.hdf"

    with h5py.File(geom_hdf, "w") as hdf:
        hdf.require_group("Geometry").attrs["SI Units"] = np.bytes_("False")
        flow_areas = hdf.require_group("Geometry/2D Flow Areas")
        attrs_dtype = np.dtype([("Name", "S64")])
        flow_areas.create_dataset(
            "Attributes",
            data=np.array([(b"Bridge Mesh",)], dtype=attrs_dtype),
        )

    with h5py.File(plan_hdf, "w") as hdf:
        hdf.require_group("Plan Data/Plan Information").attrs[
            "Geometry Filename"
        ] = np.bytes_("BridgeModel.g01")
        hdf.require_group("Geometry/2D Bridges")

    with pytest.raises(NotImplementedError):
        HdfResultsQuery.query_polyline_velocity_profile(
            plan_hdf,
            LineString([(0.0, 0.0), (1.0, 0.0)]),
            time_index=0,
        )


def test_rejects_max_time_index(tmp_path: Path) -> None:
    plan_hdf = tmp_path / "minimal.p01.hdf"
    with h5py.File(plan_hdf, "w") as hdf:
        hdf.require_group("Plan Data/Plan Information")

    with pytest.raises(ValueError, match="max"):
        HdfResultsQuery.query_polyline_velocity_profile(
            plan_hdf,
            LineString([(0.0, 0.0), (1.0, 0.0)]),
            time_index="max",
        )


def test_handles_polyline_gap_rows() -> None:
    manifest = _load_manifest()
    plan_hdf = _require_bald_eagle_plan()

    profile = HdfResultsQuery.query_polyline_velocity_profile(
        plan_hdf,
        _load_polyline(),
        time_index=int(manifest["time_index"]),
        sample_spacing=float(manifest["max_segment_len"]),
        terrain_raster=_bald_eagle_terrain_hdf(plan_hdf),
    )

    gap_rows = profile["velocity_mag"].isna()
    assert gap_rows.any()
    assert profile.loc[gap_rows, "terrain_elev"].notna().any()


def test_wse_and_flow_profiles_return_expected_schema() -> None:
    manifest = _load_manifest()
    plan_hdf = _require_bald_eagle_plan()
    terrain_hdf = _bald_eagle_terrain_hdf(plan_hdf)
    polyline = _load_polyline()

    wse = HdfResultsQuery.query_polyline_wse_profile(
        plan_hdf,
        polyline,
        time_index=int(manifest["time_index"]),
        sample_spacing=float(manifest["max_segment_len"]),
        terrain_raster=terrain_hdf,
    )
    flow = HdfResultsQuery.query_polyline_flow_profile(
        plan_hdf,
        polyline,
        time_index=int(manifest["time_index"]),
        sample_spacing=float(manifest["max_segment_len"]),
        terrain_raster=terrain_hdf,
    )

    assert list(wse.columns) == EXPECTED_WSE_COLUMNS
    assert list(flow.columns) == EXPECTED_FLOW_COLUMNS
    assert len(wse) == int(manifest["row_count"])
    assert len(flow) == int(manifest["row_count"])
    assert wse["wse"].notna().any()
    assert wse.attrs["wse_source"] == [
        "RasMapperLib.Render.WaterSurfaceRenderer"
    ]
    assert flow.attrs["flow_source"] == ["RasMapperLib.Render.FlowRenderer"]


def test_velocity_wse_flow_timeseries_return_long_schema() -> None:
    plan_hdf = _require_chippewa_plan()
    polyline = _load_chippewa_polyline()
    time_range = (0, 2)

    velocity = HdfResultsQuery.query_polyline_velocity_timeseries(
        plan_hdf,
        polyline,
        time_range=time_range,
        sample_spacing=50.0,
    )
    wse = HdfResultsQuery.query_polyline_wse_timeseries(
        plan_hdf,
        polyline,
        time_range=time_range,
        sample_spacing=50.0,
    )
    flow = HdfResultsQuery.query_polyline_flow_timeseries(
        plan_hdf,
        polyline,
        time_range=time_range,
        sample_spacing=50.0,
    )

    expected_velocity = pd.read_csv(CHIPPEWA_VELOCITY_TS_CSV)
    expected_wse = pd.read_csv(CHIPPEWA_WSE_TS_CSV)
    expected_rows = len(expected_velocity)
    assert list(velocity.columns) == EXPECTED_VELOCITY_TS_COLUMNS
    assert len(velocity) == expected_rows
    assert len(wse) == expected_rows
    assert len(flow) == expected_rows
    assert sorted(velocity["time_index"].unique().tolist()) == list(range(*time_range))
    assert velocity.attrs["velocity_source"] == [
        "RasMapperLib.Render.VelocityTimeSeries"
    ]
    assert wse.attrs["wse_source"] == ["RasMapperLib.Render.WaterSurfaceTimeSeries"]
    assert wse["wse"].notna().any()
    np.testing.assert_allclose(
        velocity["velocity_mag"].to_numpy(dtype=float),
        expected_velocity["velocity_mag"].to_numpy(dtype=float),
        equal_nan=True,
    )
    np.testing.assert_allclose(
        wse["wse"].to_numpy(dtype=float),
        expected_wse["wse"].to_numpy(dtype=float),
        equal_nan=True,
    )


def test_difference_same_plan_is_zero() -> None:
    manifest = _load_manifest()
    plan_hdf = _require_bald_eagle_plan()

    wse_diff = HdfResultsQuery.query_polyline_wse_difference(
        plan_hdf,
        plan_hdf,
        _load_polyline(),
        time_index=int(manifest["time_index"]),
        sample_spacing=float(manifest["max_segment_len"]),
        terrain_raster=_bald_eagle_terrain_hdf(plan_hdf),
    )
    velocity_diff = HdfResultsQuery.query_polyline_velocity_difference(
        plan_hdf,
        plan_hdf,
        _load_polyline(),
        time_index=int(manifest["time_index"]),
        sample_spacing=float(manifest["max_segment_len"]),
        terrain_raster=_bald_eagle_terrain_hdf(plan_hdf),
    )

    assert np.nanmax(np.abs(wse_diff["wse_delta"].to_numpy(dtype=float))) <= 1.0e-5
    assert (
        np.nanmax(np.abs(velocity_diff["velocity_mag_delta"].to_numpy(dtype=float)))
        <= 1.0e-5
    )


def test_pipe_profiles_reject_non_pipe_plan() -> None:
    manifest = _load_manifest()
    plan_hdf = _require_bald_eagle_plan()

    with pytest.raises(NotImplementedError, match="pipe network"):
        HdfResultsQuery.query_polyline_pipe_velocity_profile(
            plan_hdf,
            _load_polyline(),
            time_index=int(manifest["time_index"]),
            sample_spacing=float(manifest["max_segment_len"]),
            terrain_raster=_bald_eagle_terrain_hdf(plan_hdf),
        )
