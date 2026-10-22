"""Recorded computed-flow provenance; synthetic files test routing, not hydraulics."""

import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import HdfResultsMesh, HdfResultsXsec


BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
REFERENCE = f"{BASE}/Reference Lines"
GOLDEN_ROOT = Path(os.environ.get(
    "RAS_COMMANDER_REFERENCE_FLOW_FIXTURES",
    "tests/data/external/golden",
))


def _write_recorded(path, names=(b"Line|Mesh A",), values=None):
    if values is None:
        values = np.array([[0.0], [-4.0], [0.0], [3.0], [0.0]])
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(f"{BASE}/Time Date Stamp (ms)", data=np.array([
            f"01Jan2020 0{i}:00:00.000".encode() for i in range(5)
        ]))
        hdf.create_dataset(f"{REFERENCE}/Name", data=np.array(names))
        flow = hdf.create_dataset(f"{REFERENCE}/Flow", data=values)
        flow.attrs["Units"] = b"cfs"
    return path


@pytest.fixture
def no_native(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Recorded computed flow must not select native/face routes")

    monkeypatch.setattr(HdfResultsMesh, "_get_native_profile_line_faces", staticmethod(fail))
    monkeypatch.setattr(HdfResultsMesh, "_read_rasmapper_face_flow_timeseries", staticmethod(fail))
    from ras_commander.dotnet import clr_bootstrap
    monkeypatch.setattr(clr_bootstrap, "load_clr", fail)


@pytest.mark.parametrize("version", ["66", "701"])
@pytest.mark.parametrize("direction", ["signed", "absolute"])
def test_recorded_real_f3_without_face_flow_or_native(version, direction, no_native):
    path = GOLDEN_ROOT / version / "BaldEagleCrkMulti2D/p03/F3_refpts_lines/BaldEagleDamBrk.p03.hdf"
    if not path.is_file():
        pytest.skip(f"Retained F3 fixture unavailable: {path}; set RAS_COMMANDER_REFERENCE_FLOW_FIXTURES")
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    expected = HdfResultsXsec.get_ref_lines_timeseries(path, variables="Flow").Flow.isel(refln_id=0)
    with h5py.File(path, "r") as hdf:
        assert "Event Conditions/Observed Data/Flow" not in hdf
        assert f"{BASE}/2D Flow Areas/BaldEagleCr/Face Flow" not in hdf
    result = HdfResultsMesh.get_profile_line_flow_timeseries(path, "RL_Mid", direction=direction)
    values = expected.values if direction == "signed" else np.abs(expected.values)
    np.testing.assert_array_equal(result.flow.values, values)
    np.testing.assert_array_equal(result.time.values, expected.time.values)
    assert len(result) == 145
    assert float(expected.min()) == {
        "66": -957.1029663085938, "701": -957.1030883789062,
    }[version]
    assert float(expected.max()) == 0.0
    assert result.time.iloc[0] == pd.Timestamp("1999-01-01 12:00")
    assert result.time.iloc[-1] == pd.Timestamp("1999-01-02 12:00")
    assert result.mesh_name.unique().tolist() == ["BaldEagleCr"]
    assert result.selection_source.unique().tolist() == ["reference_line_recorded_flow"]
    assert result.face_count.eq(0).all()
    assert result.attrs == {
        "face_ids": [], "units": "cfs", "variable": "Reference Line Flow",
        "hdf_path": f"{REFERENCE}/Flow", "refln_id": 0,
    }
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("direction,expected", [("signed", [-4, 0, 3]), ("absolute", [4, 0, 3])])
def test_observed_present_does_not_substitute_and_truncate_preserves_attrs(
    tmp_path, no_native, direction, expected,
):
    path = _write_recorded(tmp_path / "Project.p01.hdf")
    # A routing sentinel, not a claimed valid native observed-data fixture.
    with h5py.File(path, "a") as hdf:
        hdf.create_dataset("Event Conditions/Observed Data/Flow/Sentinel", data=[999999.0])
    result = HdfResultsMesh.get_profile_line_flow_timeseries(
        path, "Line", mesh_name="Mesh A", direction=direction, truncate=True,
    )
    assert result.flow.tolist() == expected
    assert result.time.tolist() == list(pd.date_range("2020-01-01 01:00", periods=3, freq="h"))
    assert result.attrs["units"] == "cfs"
    assert result.attrs["face_ids"] == []
    assert result.attrs["hdf_path"] == f"{REFERENCE}/Flow"
    assert list(result.columns) == [
        "time", "flow", "line_name", "mesh_name", "direction", "face_count", "selection_source",
    ]


def test_duplicate_name_requires_mesh_and_duplicate_pair_raises(tmp_path, no_native):
    path = _write_recorded(
        tmp_path / "Project.p01.hdf", names=(b"Line|Mesh A", b"Line|Mesh B"),
        values=np.tile([-7.0, 12.0], (5, 1)),
    )
    with pytest.raises(ValueError, match="Ambiguous recorded reference-line"):
        HdfResultsMesh.get_profile_line_flow_timeseries(path, "Line")
    result = HdfResultsMesh.get_profile_line_flow_timeseries(path, "Line", "Mesh B", direction="signed")
    assert result.flow.tolist() == [12.0] * 5
    assert result.mesh_name.unique().tolist() == ["Mesh B"]
    assert result.attrs["refln_id"] == 1
    with h5py.File(path, "a") as hdf:
        hdf[f"{REFERENCE}/Name"][:] = [b"Line|Mesh A", b"Line|Mesh A"]
    with pytest.raises(ValueError, match="Ambiguous recorded reference-line"):
        HdfResultsMesh.get_profile_line_flow_timeseries(path, "Line", "Mesh A")


@pytest.mark.parametrize("case", [
    "group", "flow_group", "rank", "dtype", "columns", "rows", "name_missing",
    "name_rank", "name_dtype", "time_missing", "time_invalid", "time_order", "units",
])
def test_malformed_present_recorded_flow_never_falls_back(tmp_path, no_native, case):
    path = _write_recorded(tmp_path / "Project.p01.hdf")
    with h5py.File(path, "a") as hdf:
        if case == "group":
            del hdf[REFERENCE]
            hdf.create_dataset(REFERENCE, data=[0.0])
        elif case in {"flow_group", "rank", "dtype", "columns", "rows"}:
            del hdf[f"{REFERENCE}/Flow"]
            if case == "flow_group":
                hdf.create_group(f"{REFERENCE}/Flow")
            else:
                value = {"rank": np.ones(5), "dtype": np.full((5, 1), b"x"),
                         "columns": np.ones((5, 2)), "rows": np.ones((4, 1))}[case]
                hdf.create_dataset(f"{REFERENCE}/Flow", data=value)
        elif case.startswith("name"):
            del hdf[f"{REFERENCE}/Name"]
            if case == "name_rank":
                hdf.create_dataset(f"{REFERENCE}/Name", data=[[b"Line|Mesh A"]])
            elif case == "name_dtype":
                hdf.create_dataset(f"{REFERENCE}/Name", data=[1])
        elif case == "time_missing":
            del hdf[f"{BASE}/Time Date Stamp (ms)"]
        elif case == "time_invalid":
            hdf[f"{BASE}/Time Date Stamp (ms)"][0] = b"bad timestamp"
        elif case == "time_order":
            hdf[f"{BASE}/Time Date Stamp (ms)"][0] = b"01Jan2020 09:00:00.000"
        elif case == "units":
            hdf[f"{REFERENCE}/Flow"].attrs["Units"] = [b"cfs", b"cms"]
    with pytest.raises((ValueError, KeyError)):
        HdfResultsMesh.get_profile_line_flow_timeseries(path, "Line")


@pytest.mark.parametrize("case", [
    "group_absent", "flow_absent", "name_absent", "mesh_absent", "case_differs",
    "unrelated_malformed_flow", "other_mesh_malformed_flow",
])
def test_valid_absence_uses_distinct_face_fallback(tmp_path, monkeypatch, case):
    path = _write_recorded(tmp_path / "Project.p01.hdf")
    name, mesh = "Line", "Mesh A"
    with h5py.File(path, "a") as hdf:
        if case == "group_absent":
            del hdf[REFERENCE]
        elif case == "flow_absent":
            del hdf[f"{REFERENCE}/Flow"]
        elif case == "name_absent":
            name = "Other"
        elif case == "mesh_absent":
            mesh = "Mesh B"
        elif case in {"unrelated_malformed_flow", "other_mesh_malformed_flow"}:
            if case == "unrelated_malformed_flow":
                name = "AdHoc"
            else:
                mesh = "Mesh B"
            del hdf[f"{REFERENCE}/Flow"]
            hdf.create_dataset(f"{REFERENCE}/Flow", data=[1.0, 2.0])
        else:
            name = "line"
    monkeypatch.setattr(HdfResultsMesh, "_get_native_profile_line_faces", staticmethod(
        lambda **kwargs: pd.DataFrame({"face_id": [3], "mesh_name": [mesh]}),
    ))
    def face_result(**kwargs):
        assert kwargs["selection_source"] == "reference_line_internal_faces"
        assert kwargs["face_ids"] == [3]
        return pd.DataFrame({"flow": [8.0], "selection_source": [kwargs["selection_source"]]})
    monkeypatch.setattr(HdfResultsMesh, "_read_rasmapper_face_flow_timeseries", staticmethod(face_result))
    result = HdfResultsMesh.get_profile_line_flow_timeseries(path, name, mesh)
    assert result.selection_source.tolist() == ["reference_line_internal_faces"]


def test_missing_units_and_mesh_are_not_guessed(tmp_path, no_native):
    path = _write_recorded(tmp_path / "Project.p01.hdf", names=(b"Line",))
    with h5py.File(path, "a") as hdf:
        del hdf[f"{REFERENCE}/Flow"].attrs["Units"]
    result = HdfResultsMesh.get_profile_line_flow_timeseries(path, "Line")
    assert result.mesh_name.eq("").all()
    assert result.attrs["units"] == ""


def test_signed_peak_preserves_recorded_sign(tmp_path, no_native):
    path = _write_recorded(tmp_path / "Project.p01.hdf")
    result = HdfResultsMesh.get_profile_line_peak_flow(path, "Line", direction="signed")
    assert result.peak_flow.tolist() == [-4.0]
    assert result.peak_time.tolist() == [pd.Timestamp("2020-01-01 01:00")]
    assert result.selection_source.tolist() == ["reference_line_recorded_flow"]
