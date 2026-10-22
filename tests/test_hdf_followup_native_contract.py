"""Immutable native controls for output cadence and cross-version rheology.

Set RAS_HDF_FOLLOWUP_FIXTURE_ROOT to the retained follow-up directory.
These tests never execute HEC-RAS or modify model data. Literal clock coverage
is separate from native execution completion and hydraulic convergence.
"""

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
pytest.importorskip("xarray")

from ras_commander import HdfCompletion, HdfResultsMesh, HdfResultsPlan


pytestmark = [pytest.mark.integration, pytest.mark.offline_evidence]
BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
MESH = "DebrisFlowArea"
SERIES = f"{BASE}/2D Flow Areas/{MESH}"
GEOMETRY = f"Geometry/2D Flow Areas/{MESH}"
VISCOSITY = "Face Mixture Dynamic Viscosity"
START = datetime(2000, 1, 1)
MANIFEST = json.loads((Path(__file__).parent / "data/hdf_followup_native_manifest.json").read_text(encoding="utf-8"))


def _text(value):
    return value.decode("utf-8") if isinstance(value, (bytes, np.bytes_)) else str(value)


@pytest.fixture(scope="module")
def fixture_root():
    configured = os.environ.get("RAS_HDF_FOLLOWUP_FIXTURE_ROOT")
    if not configured:
        pytest.skip("Set RAS_HDF_FOLLOWUP_FIXTURE_ROOT to retained native controls")
    root = Path(configured)
    assert root.is_dir(), f"Configured fixture root unavailable: {root}"
    return root


@pytest.fixture(params=[("66", "6.6"), ("701", "7.0.1")], ids=["6.6", "7.0.1"])
def native_version(request):
    return request.param


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda case: case["case_id"])
def test_retained_results_and_source_inputs_match_pinned_identity(fixture_root, case):
    for entry in [case, *case["source_inputs"]]:
        path = fixture_root / entry["path"]
        before = (path.stat().st_size, path.stat().st_mtime_ns)
        assert before[0] == entry["bytes"]
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(block)
        assert digest.hexdigest() == entry["sha256"], f"Changed native fixture: {entry['path']}"
        assert (path.stat().st_size, path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("kind,minutes,expected_status", [
    ("offcadence", 17, "not_covered"), ("aligned", 20, "covered"),
])
def test_completed_native_run_can_omit_off_cadence_endpoint(
    fixture_root, native_version, kind, minutes, expected_status,
):
    tag, version = native_version
    path = fixture_root / f"ether_hollow_{tag}_{kind}/EtherHollow.p01.hdf"
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    with h5py.File(path, "r") as hdf:
        assert version in _text(hdf.attrs["File Version"])
        assert "Results/Summary/Compute Messages (text)" in hdf
        stamps = [datetime.strptime(_text(value), "%d%b%Y %H:%M:%S")
                  for value in hdf[f"{BASE}/Time Date Stamp"][:]]
        expected = [START + timedelta(minutes=value) for value in range(0, minutes + 1, 5)]
        assert stamps == expected
        assert hdf[f"{SERIES}/Water Surface"].shape[0] == len(expected)
    messages = HdfResultsPlan.get_compute_messages_hdf_only(path)
    assert "Complete Process" in messages
    result = HdfCompletion.inspect_time_coverage(path)
    assert result["status"] == expected_status
    assert result["declared_start"] == result["observed_start"] == START
    assert result["declared_end"] == START + timedelta(minutes=minutes)
    assert result["observed_end"] == expected[-1]
    assert result["row_count"] == len(expected)
    if kind == "offcadence":
        assert result["reason"] == "end_not_observed"
        assert result["declared_end"] - result["observed_end"] == timedelta(minutes=2)
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("mode", ["eager", "view", "stream"])
def test_viscosity_contradiction_is_native_in_both_versions(
    fixture_root, native_version, mode,
):
    tag, version = native_version
    path = fixture_root / f"ether_hollow_{tag}_aligned/EtherHollow.p01.hdf"
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    with h5py.File(path, "r") as hdf:
        assert version in _text(hdf.attrs["File Version"])
        dataset = hdf[f"{SERIES}/{VISCOSITY}"]
        cell_count = hdf[f"{GEOMETRY}/Cells Center Coordinate"].shape[0]
        face_count = hdf[f"{GEOMETRY}/Faces Cell Indexes"].shape[0]
        assert dataset.shape == (5, cell_count) == (5, 10647)
        assert face_count == 20797
        assert _text(dataset.attrs["Location"]) == _text(dataset.attrs["Columns"]) == "Faces"
        assert _text(dataset.attrs["Units"]) == "lb/ft^2*s"
        # Observed native numbers do not establish a physical conversion rule.
        np.testing.assert_array_equal(dataset[:], np.full(dataset.shape, np.float32(4788.02490234375)))
        options = hdf["Event Conditions/Unsteady/Options/Non Newtonian"].attrs
        assert options["User Specified Sediment Laden Viscosity"] == 100
        assert options["User Specified Yield Strength"] == 700
    with pytest.raises(ValueError, match="Qualified series domain contradicts geometry count"):
        if mode == "stream":
            list(HdfResultsMesh.iter_mesh_timeseries(path, MESH, VISCOSITY, batch_size=2))
        else:
            result = HdfResultsMesh.get_mesh_timeseries(
                path, MESH, VISCOSITY, truncate=False,
                return_type="view" if mode == "view" else "xarray",
            )
            if mode == "view":
                result.to_numpy()
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("variable", ["Face Yield Stress", "Face Viscous Stress"])
@pytest.mark.parametrize("mode", ["eager", "view", "stream"])
def test_native_stress_reader_keeps_actual_output_clock(fixture_root, native_version, variable, mode):
    tag, _ = native_version
    path = fixture_root / f"ether_hollow_{tag}_offcadence/EtherHollow.p01.hdf"
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    with h5py.File(path, "r") as hdf:
        dataset = hdf[f"{SERIES}/{variable}"]
        expected = dataset[:]
        units = _text(dataset.attrs["Units"])
    if mode == "stream":
        import xarray as xr
        batches = list(HdfResultsMesh.iter_mesh_timeseries(path, MESH, variable, batch_size=2))
        assert [batch.shape[0] for batch in batches] == [2, 2]
        actual = xr.concat(batches, dim="time")
    else:
        result = HdfResultsMesh.get_mesh_timeseries(
            path, MESH, variable, truncate=False,
            return_type="view" if mode == "view" else "xarray",
        )
        actual = result.to_xarray() if mode == "view" else result
    assert actual.shape == expected.shape == (4, 20797)
    assert actual.dtype == expected.dtype
    assert actual.attrs["units"] == units == "lb/ft^2"
    np.testing.assert_array_equal(actual.values, expected)
    np.testing.assert_array_equal(actual.face_id.values, np.arange(20797))
    np.testing.assert_array_equal(actual.time.values, np.asarray([
        np.datetime64(START + timedelta(minutes=minute), "ns") for minute in (0, 5, 10, 15)
    ]))
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("direction", ["signed", "absolute"])
@pytest.mark.parametrize("truncate", [False, True])
@pytest.mark.parametrize("active", [False, True], ids=["zero-control", "active-control"])
def test_native_observed_flow_never_replaces_computed_flow(
    fixture_root, native_version, direction, truncate, active,
):
    tag, version = native_version
    suffix = "_active" if active else ""
    path = fixture_root / f"bald_eagle_{tag}_observed_computed{suffix}/BaldEagleDamBrk.p03.hdf"
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    with h5py.File(path, "r") as hdf:
        assert version in _text(hdf.attrs["File Version"])
        observed = hdf["Event Conditions/Observed Data/Flow"]
        identities = observed["Attributes"][:]
        assert len(identities) == 1
        identity = identities[0]
        assert _text(identity["Type"]) == "Ref Line"
        assert _text(identity["Name"]) == "RL_Mid"
        observation = observed[_text(identity["Dataset"])]
        assert _text(observation.attrs["Source"]) == "Constant"
        assert _text(observation.attrs["Data Units"]) == "cfs"
        assert observation.attrs["Constant Value"] == 12345
        np.testing.assert_array_equal(observation["Value"], [12345, 12345])
        assert [_text(value) for value in observation["Date"]] == [
            "01JAN1999 12:00:00", "01JAN1999 17:00:00" if active else "01JAN1999 14:00:00",
        ]
        reference = hdf[f"{BASE}/Reference Lines"]
        assert [_text(value) for value in reference["Name"][:]] == ["RL_Mid|BaldEagleCr"]
        expected = reference["Flow"][:, 0]
        assert len(expected) == (61 if active else 25)
        if active:
            assert np.any(expected < 0), "The active computed control must include nonzero signed flow"
        else:
            assert np.all(expected == 0)
        assert not np.any(expected == 12345)
        assert _text(reference["Flow"].attrs["Units"]) == "cfs"
        times = np.asarray([
            np.datetime64(datetime.strptime(_text(value), "%d%b%Y %H:%M:%S"), "ns")
            for value in hdf[f"{BASE}/Time Date Stamp"][:]
        ])
    assert len(times) == len(expected)
    if direction == "absolute":
        expected = np.abs(expected)
    if truncate:
        indices = np.flatnonzero(expected != 0)
        if len(indices):
            first, end = indices[0], indices[-1] + 1
            expected, times = expected[first:end], times[first:end]
        else:
            # Profile-flow truncation removes an all-zero series. The mesh
            # array reader has a separate all-zero preservation contract.
            expected, times = expected[:0], times[:0]
    actual = HdfResultsMesh.get_profile_line_flow_timeseries(
        path, "RL_Mid", mesh_name="BaldEagleCr", direction=direction, truncate=truncate,
    )
    np.testing.assert_array_equal(actual.flow.values, expected)
    np.testing.assert_array_equal(actual.time.values, times)
    if len(expected):
        assert actual.selection_source.unique().tolist() == ["reference_line_recorded_flow"]
        assert actual.mesh_name.unique().tolist() == ["BaldEagleCr"]
    else:
        assert actual.empty
        assert "selection_source" in actual.columns
        assert "mesh_name" in actual.columns
    assert actual.attrs["units"] == "cfs"
    assert actual.attrs["hdf_path"] == f"{BASE}/Reference Lines/Flow"
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before
