"""Small guard fixtures; native hydraulic qualification remains in notebook 917."""
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from types import SimpleNamespace

import nbformat
import numpy as np
import pandas as pd
import pytest
import xarray as xr


@pytest.fixture(scope="module")
def helpers():
    notebook = nbformat.read(Path("examples/917_mrms_precipitation_qpe.ipynb"), as_version=4)
    source = "\n".join(c.source for c in notebook.cells if c.cell_type == "code")
    wanted = {
        "align_mrms_hyetograph", "compare_native_cumulative", "readback_hyetograph",
        "verify_boundary_topology", "validate_source_hyetograph", "physical_support_from_topology",
        "align_animation_precipitation",
        "summarize_runtime_messages",
        "build_qualification_summary", "preserve_after_input_snapshots", "sha256_file",
    }
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=functions, type_ignores=[])
    namespace = {
        "np": np, "pd": pd, "xr": xr, "re": re, "Path": Path,
        "datetime": datetime, "timezone": timezone, "hashlib": hashlib,
        "json": json, "shutil": shutil, "time": time,
    }
    exec(compile(module, "notebook_helpers", "exec"), namespace)
    return namespace


def source_frame():
    return pd.DataFrame({"time": pd.date_range("2024-04-10", periods=4, freq="h"),
                         "hour": [1, 2, 3, 4], "incremental_depth": [.91, .0149, .2551, .13],
                         "cumulative_depth": [.91, .9249, 1.18, 1.31]})


def test_prestart_frame_removed_without_independent_rounding_and_tail_explicit(helpers):
    source = source_frame()
    snapshot = source.copy(deep=True)
    aligned = helpers["align_mrms_hyetograph"](source, "2024-04-10", "2024-04-10 03:00", "2024-04-10 05:00")
    pd.testing.assert_frame_equal(source, snapshot)
    assert aligned.hour.tolist() == [1, 2, 3, 4, 5]
    assert aligned.incremental_depth.tolist() == [.0149, .2551, .13, 0, 0]
    assert aligned.cumulative_depth.iloc[-1] == pytest.approx(.4)


@pytest.mark.parametrize(("defect", "message"), [
    ("gap", "missing/irregular interval"),
    ("duplicate", "unique and increasing"),
    ("unordered", "unique and increasing"),
    ("straddle", "straddles the boundary origin"),
    ("missing_first", "completely cover the requested rainfall window"),
    ("nonfinite", "Invalid source precipitation"),
    ("negative", "Invalid source precipitation"),
    ("timezone", "UTC-equivalent naive model-clock labels"),
])
def test_invalid_absolute_source_rejected(helpers, defect, message):
    frame = source_frame()
    if defect == "gap":
        frame = frame.drop(index=2)
    elif defect == "duplicate":
        frame.loc[2, "time"] = frame.loc[1, "time"]
    elif defect == "unordered":
        frame = frame.iloc[[0, 2, 1, 3]]
    elif defect == "straddle":
        frame["time"] += pd.Timedelta(minutes=30)
    elif defect == "missing_first":
        frame = frame.iloc[2:]
    elif defect == "nonfinite":
        frame.loc[2, "incremental_depth"] = np.nan
    elif defect == "negative":
        frame.loc[2, "incremental_depth"] = -.1
    elif defect == "timezone":
        frame["time"] = frame["time"].dt.tz_localize("UTC")
    with pytest.raises(ValueError, match=message):
        helpers["align_mrms_hyetograph"](frame, "2024-04-10", "2024-04-10 03:00", "2024-04-10 05:00")


@pytest.mark.parametrize("end", ["2024-04-10 02:00", "2024-04-10 05:30"])
def test_simulation_end_covers_qpe_on_hourly_lattice(helpers, end):
    with pytest.raises(ValueError, match="Simulation end must be on the hourly lattice"):
        helpers["align_mrms_hyetograph"](source_frame(), "2024-04-10", "2024-04-10 03:00", end)


def native_fixture():
    times = pd.date_range("2024-04-10", periods=37, freq="5min").as_unit("ns")
    expected = pd.DataFrame({"time": times[::12], "cumulative_depth": [0, .2, .3, .3]})
    curve = np.interp(times.asi8, pd.DatetimeIndex(expected.time).asi8, expected.cumulative_depth)
    cumulative = np.column_stack([curve, curve, np.zeros(len(times))])
    rates = np.zeros_like(cumulative)
    return times, np.array([0, 1, 2]), cumulative, rates, expected, (np.array([0, 1]), np.array([2]), np.arange(3)), times[0], times[-1]


def test_complete_native_absolute_clock_and_geometry_support_pass(helpers):
    diagnostics, error, tolerance = helpers["compare_native_cumulative"](*native_fixture())
    assert len(diagnostics) == 37 and error == 0 and tolerance > 0


@pytest.mark.parametrize(("defect", "message"), [
    ("shift", "Absolute-time native cumulative mismatch"),
    ("dry_physical", "Absolute-time native cumulative mismatch"),
    ("nan", "Nonfinite native precipitation"),
    ("negative", "Negative native precipitation"),
    ("partial_time", "complete absolute simulation clock"),
    ("shifted_clock", "complete absolute simulation clock"),
    ("wrong_cells", "cell coordinates do not cover the geometry exactly"),
    ("dimensions", "Native array dimensions disagree"),
    ("boundary_rain", "Boundary-only cells contain precipitation"),
    ("boundary_rate", "Boundary-only cells contain precipitation"),
    ("source_window", "Serialized boundary does not cover the simulation window"),
])
def test_native_failures_do_not_hide_behind_equal_total_or_peak(helpers, defect, message):
    values = list(native_fixture())
    if defect == "shift":
        # Delay rainfall one hour, preserving final total and all curve increments.
        values[2][:, :2] = np.vstack([np.zeros((12, 2)), values[2][:-12, :2]])
        assert values[2][-1, 0] == .3
    elif defect == "dry_physical":
        values[2][:, 1] = 0
    elif defect == "nan":
        values[2][2, 0] = np.nan
    elif defect == "negative":
        values[3][2, 0] = -.1
    elif defect == "partial_time":
        values[0] = values[0][:-1]
        values[2], values[3] = values[2][:-1], values[3][:-1]
    elif defect == "shifted_clock":
        values[0] += pd.Timedelta(hours=1)
    elif defect == "wrong_cells":
        values[1] = np.array([0, 1, 1])
    elif defect == "dimensions":
        values[3] = values[3][:, :2]
    elif defect == "boundary_rain":
        values[2][1, 2] = .01
    elif defect == "boundary_rate":
        values[3][1, 2] = .01
    elif defect == "source_window":
        values[4].loc[0, "time"] += pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match=message):
        helpers["compare_native_cumulative"](*values)


@pytest.mark.parametrize(("field", "message"), [
    ("rate", "No-rain baseline"),
    ("cumulative", "Absolute-time native cumulative mismatch"),
])
def test_baseline_zero_required_in_rates_and_cumulative(helpers, field, message):
    values = list(native_fixture())
    values[2][:] = 0
    values[4]["cumulative_depth"] = 0
    helpers["compare_native_cumulative"](*values)
    values[3 if field == "rate" else 2][1, 1] = .001
    with pytest.raises(ValueError, match=message):
        helpers["compare_native_cumulative"](*values)


@pytest.fixture
def readback_case(helpers, monkeypatch):
    # Rounding each .0049 increment to two decimals loses all rain. Rounding
    # cumulative ordinates before differencing yields [0, .01, 0] instead.
    times = pd.date_range("2024-04-10 01:00", periods=3, freq="h")
    intended = pd.DataFrame({"time": times, "cumulative_depth": [.0049, .0098, .0147]})
    boundary = pd.Series({"Interval": "1HOUR", "hydrograph_values": [0, 0, .01, 0]})
    monkeypatch.setitem(helpers, "precipitation_boundary", lambda *args: boundary)
    case = {"precip_boundary": "area", "event_start": times[0] - pd.Timedelta(hours=1), "sim_end": times[-1]}
    return boundary, case, intended


def test_readback_preserves_absolute_clock_anchor_and_cumulative_rounding(helpers, readback_case, tmp_path):
    _, case, intended = readback_case
    snapshot = intended.copy(deep=True)
    result = helpers["readback_hyetograph"](None, "01", case, intended, "test", tmp_path)
    pd.testing.assert_frame_equal(intended, snapshot)
    assert pd.DatetimeIndex(result.time).equals(pd.date_range(case["event_start"], case["sim_end"], freq="h"))
    assert result.incremental_depth.tolist() == [0, 0, .01, 0]
    np.testing.assert_allclose(result.cumulative_depth, [0, 0, .01, .01])
    assert (tmp_path / "test_serialized.csv").is_file()


@pytest.mark.parametrize(("defect", "message"), [
    ("interval", "Expected 1HOUR boundary interval"),
    ("missing_anchor", "Serialized ordinate count must equal intended plus one"),
    ("extra_anchor", "Serialized ordinate count must equal intended plus one"),
    ("nonzero_anchor", "Time-zero anchor must be zero"),
    ("short_window", "Serialized window ordinate count mismatch"),
    ("shifted_intended_clock", "Intended and serialized absolute times differ"),
    ("independently_rounded", "Cumulative serialization error exceeds 0.005 in"),
    ("intermediate_drift", "Cumulative serialization error exceeds 0.005 in"),
])
def test_readback_rejects_each_serialization_defect(helpers, readback_case, tmp_path, defect, message):
    boundary, case, intended = readback_case
    if defect == "interval":
        boundary["Interval"] = "30MIN"
    elif defect == "missing_anchor":
        boundary["hydrograph_values"] = boundary["hydrograph_values"][1:]
    elif defect == "extra_anchor":
        boundary["hydrograph_values"] = [0, *boundary["hydrograph_values"]]
    elif defect == "nonzero_anchor":
        boundary["hydrograph_values"][0] = .01
    elif defect == "short_window":
        case["sim_end"] -= pd.Timedelta(hours=1)
    elif defect == "shifted_intended_clock":
        intended["time"] += pd.Timedelta(hours=1)
    elif defect == "independently_rounded":
        boundary["hydrograph_values"] = [0, 0, 0, 0]
    elif defect == "intermediate_drift":
        # The final total still passes; the preceding ordinate does not.
        boundary["hydrograph_values"] = [0, 0, 0, .01]
    with pytest.raises(AssertionError, match=message):
        helpers["readback_hyetograph"](None, "01", case, intended, "test", tmp_path)
    assert not (tmp_path / "test_serialized.csv").exists()


@pytest.mark.parametrize(("error", "passes"), [(.005, True), (.005001, False)])
def test_readback_half_cent_cumulative_error_boundary(helpers, readback_case, tmp_path, error, passes):
    boundary, case, intended = readback_case
    boundary["hydrograph_values"] = [0, 0, 0, 0]
    intended["cumulative_depth"] = [0, 0, error]
    if passes:
        helpers["readback_hyetograph"](None, "01", case, intended, "test", tmp_path)
    else:
        with pytest.raises(AssertionError, match="Cumulative serialization error exceeds 0.005 in"):
            helpers["readback_hyetograph"](None, "01", case, intended, "test", tmp_path)


@pytest.fixture
def source_stack():
    return xr.DataArray(
        [[[1., 2.], [3., np.nan]], [[0., 4.], [8., 12.]], [[2., 6.], [10., 14.]]],
        dims=("time", "y", "x"),
        coords={"time": pd.date_range("2024-04-10", periods=3, freq="h"), "y": [0, 1], "x": [0, 1]},
        attrs={"units": "mm"},
    )


def source_hyetograph(stack):
    depths = np.array([2., 6., 8.]) / 25.4
    return pd.DataFrame({"time": stack.time.values, "incremental_depth": depths,
                         "cumulative_depth": depths.cumsum()})


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_source_hyetograph_matches_absolute_grib_times_and_unrounded_box_mean(helpers, source_stack, dtype):
    from ras_commander.precip import PrecipMrms

    # Exercise the public conversion as well as the notebook guard. The tiny
    # stack tests arithmetic/clock contracts, not MRMS or hydraulic validity.
    source_stack = source_stack.astype(dtype)
    frame = PrecipMrms.to_hyetograph(source_stack, depth_units="in")
    expected = source_hyetograph(source_stack)
    pd.testing.assert_series_equal(frame.time, expected.time)
    np.testing.assert_allclose(frame.incremental_depth, expected.incremental_depth, rtol=2 * np.finfo(dtype).eps)
    if dtype == np.float32:
        # The API divides in the source dtype before its float64 mean. Ensure
        # this fixture actually exercises the formerly rejected roundoff.
        assert np.max(np.abs(frame.incremental_depth - expected.incremental_depth)) > 1e-12
    helpers["validate_source_hyetograph"](frame, source_stack)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_source_depth_tolerance_rejects_meaningful_depth_changes(helpers, source_stack, dtype):
    from ras_commander.precip import PrecipMrms

    source_stack = source_stack.astype(dtype)
    frame = PrecipMrms.to_hyetograph(source_stack, depth_units="in")
    frame.loc[1, "incremental_depth"] += .0001
    with pytest.raises(AssertionError, match="Source hyetograph depths differ from unrounded spatial mean"):
        helpers["validate_source_hyetograph"](frame, source_stack)


def test_float64_source_guard_keeps_tighter_precision(helpers, source_stack):
    frame = source_hyetograph(source_stack)
    # A float32-scale discrepancy is not justified for float64 source data.
    frame.loc[1, "incremental_depth"] += 2e-8
    with pytest.raises(AssertionError, match="Source hyetograph depths differ from unrounded spatial mean"):
        helpers["validate_source_hyetograph"](frame, source_stack)


def test_float32_depth_roundoff_does_not_relax_exact_source_clock(helpers, source_stack):
    from ras_commander.precip import PrecipMrms

    source_stack = source_stack.astype(np.float32)
    frame = PrecipMrms.to_hyetograph(source_stack, depth_units="in")
    frame["time"] += pd.Timedelta(nanoseconds=1)
    with pytest.raises(AssertionError, match="Source hyetograph timestamps differ from GRIB stack"):
        helpers["validate_source_hyetograph"](frame, source_stack)


@pytest.mark.parametrize("added_depth", [0., 1e-8])
def test_float32_dry_source_interval_remains_exactly_zero(helpers, source_stack, added_depth):
    from ras_commander.precip import PrecipMrms

    source_stack = source_stack.astype(np.float32)
    source_stack.values[0] = 0
    frame = PrecipMrms.to_hyetograph(source_stack, depth_units="in")
    frame.loc[0, "incremental_depth"] = added_depth
    if added_depth == 0:
        helpers["validate_source_hyetograph"](frame, source_stack)
    else:
        with pytest.raises(AssertionError, match="Source hyetograph depths differ from unrounded spatial mean"):
            helpers["validate_source_hyetograph"](frame, source_stack)


def test_source_grid_unit_contract_is_checked_before_depth_comparison(helpers, source_stack):
    source_stack.attrs["units"] = "in"
    with pytest.raises(AssertionError, match="Source GRIB stack must use millimeters"):
        helpers["validate_source_hyetograph"](source_hyetograph(source_stack), source_stack)


@pytest.mark.parametrize(("defect", "message"), [
    ("one_hour_later", "Source hyetograph timestamps differ from GRIB stack"),
    ("missing_frame", "Source hyetograph timestamps differ from GRIB stack"),
    ("rounded_depths", "Source hyetograph depths differ from unrounded spatial mean"),
    ("wrong_units", "Source hyetograph depths differ from unrounded spatial mean"),
    ("depth_reordered", "Source hyetograph depths differ from unrounded spatial mean"),
])
def test_source_to_hyetograph_evidence_gap_rejected(helpers, source_stack, defect, message):
    frame = source_hyetograph(source_stack)
    if defect == "one_hour_later":
        frame["time"] += pd.Timedelta(hours=1)
    elif defect == "missing_frame":
        frame = frame.iloc[[0, 2]]
    elif defect == "rounded_depths":
        frame["incremental_depth"] = frame.incremental_depth.round(2)
    elif defect == "wrong_units":
        frame["incremental_depth"] *= 25.4
    elif defect == "depth_reordered":
        frame["incremental_depth"] = frame.incremental_depth.to_numpy()[::-1]
    with pytest.raises(AssertionError, match=message):
        helpers["validate_source_hyetograph"](frame, source_stack)


@pytest.fixture
def topology_case(helpers, monkeypatch):
    # Two adjacent unit squares and a one-face boundary cell. Cell 1 can be
    # absent from the detailed-polygon API while its native endpoint cycle
    # remains a valid physical cell. This fixture tests classification guards,
    # not the geometry or hydraulic validity of the real qualification models.
    topology = {
        "n_cells": 3,
        "cell_centers": np.array([[.5, .5], [1.5, .5], [2.1, .5]]),
        "cell_min_elev": np.array([0., 0., 0.]),
        "facepoint_coords": np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.], [2., 0.], [2., 1.]]),
        "face_facepoints": np.array([[0, 1], [1, 2], [2, 3], [3, 0], [1, 4], [4, 5], [5, 2]]),
        "cell_face_info": np.array([[0, 4], [4, 4], [8, 1]]),
        "cell_face_values": np.array([[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0], [1, 1], [5, 1]]),
        "face_cells": np.array([[0, -1], [0, 1], [0, -1], [0, -1], [1, -1], [1, 2], [1, -1]]),
    }
    monkeypatch.setitem(helpers, "HdfMesh", SimpleNamespace(get_mesh_sloped_topology=lambda *args: topology))
    support = (np.array([0, 1]), np.array([2]), np.arange(3))
    return topology, support


def test_one_face_complement_cell_joins_physical_mesh(helpers, topology_case):
    _, support = topology_case
    helpers["verify_boundary_topology"](None, "mesh", support)


@pytest.mark.parametrize(("defect", "message"), [
    ("cell_count", "Topology cell count mismatch"),
    ("multiple_faces", "Complement cell must have one face"),
    ("missing_complement", "Complement face must join one physical cell"),
    ("no_physical_neighbor", "Complement face must join one physical cell"),
])
def test_complement_topology_requires_supported_connectivity(helpers, topology_case, defect, message):
    topology, support = topology_case
    if defect == "cell_count":
        topology["n_cells"] = 4
    elif defect == "multiple_faces":
        topology["cell_face_info"][2, 1] = 2
    elif defect == "missing_complement":
        topology["face_cells"][5] = [1, -1]
    elif defect == "no_physical_neighbor":
        topology["face_cells"][5] = [2, -1]
    with pytest.raises(AssertionError, match=message):
        helpers["verify_boundary_topology"](None, "mesh", support)


@pytest.mark.parametrize("polygon_ids", [[0, 1], [0]])
def test_native_closed_cycle_keeps_physical_cell_missing_from_detailed_polygons(helpers, topology_case, polygon_ids):
    topology, expected_support = topology_case
    physical, boundary, all_ids, audit = helpers["physical_support_from_topology"](topology, polygon_ids)
    for actual, expected in zip((physical, boundary, all_ids), expected_support):
        np.testing.assert_array_equal(actual, expected)
    assert audit.cell_id.tolist() == [0, 1]
    np.testing.assert_allclose(audit.endpoint_area, [1., 1.])
    assert audit.center_covered.all()
    assert audit.loc[audit.polygon_api_omission, "cell_id"].tolist() == ([] if len(polygon_ids) == 2 else [1])


@pytest.mark.parametrize(("defect", "message"), [
    ("open_cycle", "Physical endpoint cycle is open or branched"),
    ("crossed_cycle", "Physical endpoint cycle must form one valid positive-area polygon"),
    ("zero_area", "Physical endpoint cycle must form one valid positive-area polygon"),
    ("duplicate_face", "Physical endpoint cycle contains duplicate faces"),
    ("nonfinite_vertex", "Physical endpoint cycle contains nonfinite coordinates"),
    ("nonfinite_elevation", "Physical cell has nonfinite minimum elevation"),
    ("omitted_center_outside", "Reconstructed omitted cell does not contain its native center"),
    ("disconnected_boundary", "Complement face must join one physical cell"),
])
def test_native_support_rejects_broken_geometry_before_rainfall_inspection(helpers, topology_case, defect, message):
    topology, _ = topology_case
    if defect == "open_cycle":
        topology["facepoint_coords"] = np.vstack([topology["facepoint_coords"], [.5, -1.]])
        topology["face_facepoints"][0, 1] = 6
    elif defect == "crossed_cycle":
        topology["facepoint_coords"][[1, 2]] = topology["facepoint_coords"][[2, 1]]
    elif defect == "zero_area":
        topology["facepoint_coords"][:, 1] = 0
    elif defect == "duplicate_face":
        topology["cell_face_values"][3, 0] = 0
    elif defect == "nonfinite_vertex":
        topology["facepoint_coords"][0, 0] = np.nan
    elif defect == "nonfinite_elevation":
        topology["cell_min_elev"][0] = np.nan
    elif defect == "omitted_center_outside":
        topology["cell_centers"][1] = [3., 3.]
    elif defect == "disconnected_boundary":
        topology["face_cells"][5] = [2, -1]
    with pytest.raises(AssertionError, match=message):
        helpers["physical_support_from_topology"](topology, [0])


@pytest.fixture
def animation_case():
    origin = pd.Timestamp("2024-04-10")
    source_times = pd.date_range(origin + pd.Timedelta(hours=1), periods=3, freq="h")
    source = xr.DataArray(
        np.array([np.full((2, 2), amount) for amount in (11., 22., 33.)]),
        dims=("time", "y", "x"),
        coords={"time": source_times, "y": [0, 1], "x": [0, 1]},
        attrs={"units": "mm", "source": "bounded hourly-accumulation fixture"},
    )
    flood_times = pd.DatetimeIndex([
        origin, origin + pd.Timedelta(minutes=5), origin + pd.Timedelta(hours=1),
        origin + pd.Timedelta(hours=1, minutes=5), origin + pd.Timedelta(hours=2),
        source_times[-1], source_times[-1] + pd.Timedelta(minutes=5),
        origin + pd.Timedelta(hours=5),
    ])
    return source, flood_times, origin, source_times[-1]


def test_animation_uses_covering_interval_and_preserves_observed_source(helpers, animation_case):
    source, flood_times, origin, last_qpe = animation_case
    before = source.copy(deep=True)
    display, audit = helpers["align_animation_precipitation"](source, flood_times, origin, last_qpe)
    xr.testing.assert_identical(source, before)
    assert pd.DatetimeIndex(display.time.values).equals(flood_times)
    assert display.attrs["units"] == "mm"
    assert display.dims == source.dims
    # t0 is zero; exact endpoints retain the preceding observed interval.
    # In particular 01:05 uses the observation ending 02:00, not 01:00.
    for position, amount in enumerate([0., 11., 11., 22., 22., 33., 0., 0.]):
        np.testing.assert_array_equal(display.isel(time=position).values, np.full((2, 2), amount))
    assert pd.DatetimeIndex(audit.flood_time).equals(flood_times)
    observed = audit.loc[audit.display_mode == "observed_interval"]
    assert observed.source_index.tolist() == [0, 0, 1, 1, 2]
    expected_ends = pd.DatetimeIndex(source.time.values)[[0, 0, 1, 1, 2]]
    assert pd.DatetimeIndex(observed.source_interval_end).equals(expected_ends)
    assert pd.DatetimeIndex(observed.source_interval_start).equals(expected_ends - pd.Timedelta(hours=1))


def test_animation_zero_frames_are_audited_without_inventing_observations(helpers, animation_case):
    source, flood_times, origin, last_qpe = animation_case
    display, audit = helpers["align_animation_precipitation"](source, flood_times, origin, last_qpe)
    assert audit.display_mode.tolist() == [
        "initial_zero", "observed_interval", "observed_interval", "observed_interval",
        "observed_interval", "observed_interval", "dry_tail", "dry_tail",
    ]
    zero_rows = audit.loc[audit.display_mode != "observed_interval"]
    assert zero_rows.source_index.isna().all()
    assert zero_rows.source_interval_start.isna().all()
    assert zero_rows.source_interval_end.isna().all()
    np.testing.assert_array_equal(display.sel(time=zero_rows.flood_time.to_numpy()).values, np.zeros((3, 2, 2)))
    assert (audit.loc[audit.display_mode == "dry_tail", "flood_time"] > last_qpe).all()


@pytest.mark.parametrize(("defect", "message"), [
    ("duplicate_display_time", "Display times must be unique and increasing"),
    ("unordered_display_time", "Display times must be unique and increasing"),
    ("before_origin", "Display times precede boundary origin"),
    ("missing_source_interval", "Observed source intervals do not cover the display window"),
    ("shifted_source_clock", "Observed source intervals do not cover the display window"),
])
def test_animation_alignment_rejects_ambiguous_clocks(helpers, animation_case, defect, message):
    source, flood_times, origin, last_qpe = animation_case
    if defect == "duplicate_display_time":
        flood_times = flood_times.insert(1, flood_times[0])
    elif defect == "unordered_display_time":
        flood_times = flood_times[[1, 0, *range(2, len(flood_times))]]
    elif defect == "before_origin":
        flood_times = flood_times.insert(0, origin - pd.Timedelta(minutes=5))
    elif defect == "missing_source_interval":
        source = source.isel(time=[0, 2])
    elif defect == "shifted_source_clock":
        source = source.assign_coords(time=source.time.values + np.timedelta64(1, "h"))
    with pytest.raises(AssertionError, match=message):
        helpers["align_animation_precipitation"](source, flood_times, origin, last_qpe)


ITERATION_HEADERS = [
    "Maximum iteration location\tCell\t WSEL\tERROR\tITERATIONS",
    "Pipe Network Iter\tType\tCell\tERROR\tNode or Conduit",
]
PIPE_ITERATION_ROW = "10APR2024 14:32:28 Base\tNode\t       426\t   0.450\tMine Blvd - Node 1"


def test_runtime_iteration_row_is_retained_without_warning_or_error_token(helpers, capsys):
    messages = "\n".join([
        "Complete Process", ITERATION_HEADERS[0], "", ITERATION_HEADERS[1],
        PIPE_ITERATION_ROW, "", "Overall Volume Accounting", "Unparsed volume-table detail remains visible",
    ])
    result = helpers["summarize_runtime_messages"](messages, "", "event")
    output = capsys.readouterr().out
    assert "ERROR" not in PIPE_ITERATION_ROW
    assert result["diagnostic_line_count"] == 0
    assert result["diagnostic_lines"] == []
    assert result["iteration_diagnostic_lines"] == [*ITERATION_HEADERS, PIPE_ITERATION_ROW]
    assert result["volume_accounting_lines"] == ["Overall Volume Accounting"]
    assert result["hydraulic_acceptance"] == "not_established"
    assert result["complete_process"] is True
    assert messages in output, "Display the full HDF message text, not only token-matched diagnostics"


def test_runtime_iteration_headings_alone_do_not_imply_an_error(helpers, capsys):
    messages = "\n".join([
        "Complete Process", ITERATION_HEADERS[0], "", ITERATION_HEADERS[1], "", "Overall Volume Accounting",
    ])
    result = helpers["summarize_runtime_messages"](messages, "", "baseline")
    assert result["iteration_diagnostic_lines"] == ITERATION_HEADERS
    assert result["diagnostic_line_count"] == 0
    assert result["diagnostic_lines"] == []
    assert PIPE_ITERATION_ROW not in result["iteration_diagnostic_lines"]
    # Context lines are retained; their count is not a hydraulic error count.
    assert result["hydraulic_acceptance"] == "not_established"
    assert messages in capsys.readouterr().out


def test_runtime_warning_patterns_preserve_both_source_labels_and_full_hdf_text(helpers, capsys):
    messages = "Complete Process\nWarning: inspect numerical convergence\nOther diagnostic context"
    bco_text = "Error reading retained input path"
    result = helpers["summarize_runtime_messages"](messages, bco_text, "event")
    assert result["diagnostic_line_count"] == 2
    assert result["diagnostic_lines"] == [
        "HDF: Warning: inspect numerical convergence", "BCO: Error reading retained input path",
    ]
    assert result["iteration_diagnostic_lines"] == []
    assert result["bco_exists"] is True
    assert result["hydraulic_acceptance"] == "not_established"
    output = capsys.readouterr().out
    assert messages in output
    assert "BCO: Error reading retained input path" in output


def test_qualification_provenance_uses_supplied_sources_and_actual_utc_date(helpers):
    native_sources = {"ras_commander/native_producer.py": "b" * 64}
    inspection_sources = {"ras_commander/inspection_reader.py": "a" * 64}
    runs = [{"native_runtime_seconds": 2.5, "native_started_epoch": 1600000000.,
             "native_source_module_sha256": native_sources}]
    # Local January 1 is still December 31 in UTC; neither a literal date nor
    # the local calendar date can stand in for this inspection's UTC date.
    inspection_time = datetime(2031, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    summary = helpers["build_qualification_summary"](
        runs, mode="inspect_retained", source_module_sha256=inspection_sources,
        library_version="9.9.test", inspection_time=inspection_time,
    )
    assert summary["execution_date"] == "2030-12-31"
    assert summary["inspection_utc"].endswith("Z")
    assert datetime.fromisoformat(summary["inspection_utc"].replace("Z", "+00:00")) == inspection_time
    assert summary["library_version"] == "9.9.test"
    assert summary["source_module_sha256"] == inspection_sources
    assert summary["runs"] == runs
    assert summary["runs"][0]["native_source_module_sha256"] == native_sources
    assert summary["native_runtime_seconds_total"] == 2.5


def test_qualification_inspection_timestamp_defaults_to_current_utc(helpers):
    before = datetime.now(timezone.utc)
    summary = helpers["build_qualification_summary"](
        [], mode="compute", source_module_sha256={"reader.py": "c" * 64}, library_version="1.2.test",
    )
    after = datetime.now(timezone.utc)
    inspection = datetime.fromisoformat(summary["inspection_utc"].replace("Z", "+00:00"))
    assert inspection.utcoffset() == timedelta(0)
    assert before - timedelta(seconds=1) <= inspection <= after
    assert summary["execution_date"] == inspection.date().isoformat()
    assert summary["native_runtime_seconds_total"] == 0


def test_exact_existing_postcompute_snapshot_is_used_without_other_recovery_sources(helpers, tmp_path):
    evidence = tmp_path / "evidence"
    destination = evidence / "baseline_inputs_after"
    destination.mkdir(parents=True)
    target = destination / "case.p01"
    target.write_bytes(b"exact postcompute input")
    expected_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    original = tmp_path / "missing_model" / target.name
    before = evidence / "baseline_inputs"
    before.mkdir()
    (before / target.name).write_bytes(b"different precompute input")
    receipt = {"input_sha256_after": {str(original): expected_hash}}

    helpers["preserve_after_input_snapshots"](receipt, evidence, "baseline")

    assert target.read_bytes() == b"exact postcompute input"
    assert not original.exists()
    assert (before / target.name).read_bytes() == b"different precompute input"
    manifest = json.loads((destination / "capture_manifest.json").read_text())
    assert manifest["files"][0]["sha256"] == expected_hash
    assert Path(manifest["files"][0]["snapshot"]) == target


def test_corrupt_existing_postcompute_snapshot_is_not_overwritten(helpers, tmp_path):
    original = tmp_path / "case.p01"
    original.write_bytes(b"valid current input")
    expected_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    evidence = tmp_path / "evidence"
    destination = evidence / "event_inputs_after"
    destination.mkdir(parents=True)
    target = destination / original.name
    target.write_bytes(b"corrupt retained snapshot")
    receipt = {"input_sha256_after": {str(original): expected_hash}}

    with pytest.raises(AssertionError, match="Postcompute snapshot hash mismatch"):
        helpers["preserve_after_input_snapshots"](receipt, evidence, "event")

    assert target.read_bytes() == b"corrupt retained snapshot"
    assert original.read_bytes() == b"valid current input"
    assert not (destination / "capture_manifest.json").exists()


def test_postcompute_recovery_checks_all_sources_before_copying(helpers, tmp_path):
    original = tmp_path / "case.p01"
    original.write_bytes(b"recoverable plan input")
    missing = tmp_path / "case.u01"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    receipt = {"input_sha256_after": {
        str(original): hashlib.sha256(original.read_bytes()).hexdigest(),
        str(missing): hashlib.sha256(b"unavailable input").hexdigest(),
    }}

    with pytest.raises(ValueError, match="Cannot recover exact postcompute input bytes"):
        helpers["preserve_after_input_snapshots"](receipt, evidence, "baseline")

    destination = evidence / "baseline_inputs_after"
    assert not (destination / original.name).exists()
    assert not (destination / "capture_manifest.json").exists()


def test_existing_postcompute_manifest_and_snapshot_remain_immutable(helpers, tmp_path):
    original = tmp_path / "case.p01"
    original.write_bytes(b"recorded input")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    receipt = {"input_sha256_after": {str(original): hashlib.sha256(original.read_bytes()).hexdigest()}}
    helpers["preserve_after_input_snapshots"](receipt, evidence, "event")
    destination = evidence / "event_inputs_after"
    manifest_path = destination / "capture_manifest.json"
    manifest_before = manifest_path.read_bytes()
    original.write_bytes(b"subsequently changed current model")

    helpers["preserve_after_input_snapshots"](receipt, evidence, "event")

    assert manifest_path.read_bytes() == manifest_before
    assert (destination / original.name).read_bytes() == b"recorded input"
