import importlib
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import RasUnsteady


def test_boundary_only_child_removes_met_dss_and_keeps_boundary_and_infiltration(
    tmp_path,
):
    flow = tmp_path / "child.u02"
    flow.write_bytes(
        b"Flow Title=Child\r\nProgram Version=6.60\r\n"
        b"Boundary Location=,,,,,Area,,Inlet,\r\n"
        b"DSS File=boundary.dss\r\nDSS Path=/A/B/FLOW//1HOUR/F/\r\n"
        b"Use DSS=True\r\nInfiltration=Keep\r\n"
        b"Met Station Name=Parent gage\r\nMet Station XY=10,20\r\n"
        b"Met Point Raster Parameters=1,2,3\r\nPrecipitation Mode=Enable\r\n"
        b"Met BC=Precipitation|Mode=Gridded\r\n"
        b"Met BC=Precipitation|Gridded DSS Filename=parent.dss\r\n"
        b"Met BC=Precipitation|Point Time Series=parent-point.dss\r\n"
        b"Met BC=Evapotranspiration|Gridded DSS Filename=parent-et.dss\r\n"
        b"Met BC=Wind Speed|Point Time Series=parent-wind.dss\r\n"
        b"Met BC=Precipitation|Expanded View=0\r\n"
    )
    sidecar = Path(str(flow) + ".hdf")
    with h5py.File(sidecar, "w") as hdf:
        met = hdf.create_group("Event Conditions/Meteorology")
        met.create_dataset("Meteorology Stations", data=[1, 2])
        rain = met.create_group("Precipitation")
        rain.attrs["DSS Filename"] = np.bytes_("parent.dss")
        rain.create_dataset("Values", data=[1, 2])
        hdf.create_dataset("Event Conditions/Boundary/Values", data=[3, 4])
        hdf.create_dataset("Geometry/Infiltration/Values", data=[5, 6])
    evidence = RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    raw = flow.read_bytes()
    assert b"parent" not in raw.lower()
    assert b"Met Station" not in raw
    assert b"Precipitation Mode=Disable\r\n" in raw
    assert b"Met BC=Precipitation|Mode=None\r\n" in raw
    assert b"DSS File=boundary.dss\r\n" in raw
    assert b"Infiltration=Keep\r\n" in raw
    assert b"Met BC=Precipitation|Expanded View=0\r\n" in raw
    assert evidence["source_references_removed"] is True
    assert (
        "Met BC=Precipitation|Gridded DSS Filename" in evidence["removed_source_keys"]
    )
    assert "Met BC=Precipitation|Point Time Series" in evidence["removed_source_keys"]
    with h5py.File(sidecar, "r") as hdf:
        met = hdf["Event Conditions/Meteorology"]
        assert all(int(g.attrs["Enabled"]) == 0 and not len(g) for g in met.values())
        assert list(hdf["Event Conditions/Boundary/Values"][:]) == [3, 4]
        assert list(hdf["Geometry/Infiltration/Values"][:]) == [5, 6]
    RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    assert flow.read_bytes() == raw


@pytest.mark.parametrize("prefix", ["Met Station=", "Meteorological Station="])
def test_legacy_station_trailer_is_not_a_boundary_record(tmp_path, prefix):
    flow = tmp_path / "child.u02"
    boundary = "Boundary Location=,,,,,Area,,Inlet,\nDSS File=boundary.dss\n"
    flow.write_text("Flow Title=Child\n" + boundary + prefix + "Gage,1,2,3,4,5\n")
    evidence = RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    assert prefix not in flow.read_text()
    assert boundary in flow.read_text()
    assert evidence["boundary_conditions_unchanged"]


@pytest.mark.parametrize("newline", [b"\r\n", b"\n", b"\r"])
@pytest.mark.parametrize("remove", [False, True])
@pytest.mark.parametrize("dss", [b"boundary.dss", b"caf\xe9.dss", "café.dss".encode()])
def test_default_and_removal_preserve_raw_boundary_bytes(
    tmp_path, newline, remove, dss
):
    flow = tmp_path / "child.u02"
    boundary = newline.join(
        [
            b"Boundary Location=,,,,,Area,,Inlet,",
            b"DSS File=" + dss,
            b"DSS Path=/A/B/FLOW//1HOUR/F/",
            b"Use DSS=True",
            b"",
        ]
    )
    flow.write_bytes(
        newline.join([b"Flow Title=Child", b"Program Version=6.60", b""])
        + boundary
        + newline.join(
            [
                b"Precipitation Mode=Enable",
                b"Met BC=Precipitation|Mode=Gridded",
                b"Met BC=Precipitation|Gridded DSS Filename=rain.dss",
                b"",
            ]
        )
    )
    evidence = RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
    assert boundary in flow.read_bytes()
    assert evidence["boundary_conditions_unchanged"]
    assert (
        "Met BC=Precipitation|Gridded DSS Filename" in evidence["removed_source_keys"]
    )
    first = flow.read_bytes()
    RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
    assert flow.read_bytes() == first


@pytest.mark.parametrize("remove", [False, True])
def test_empty_sidecar_is_initialized_safely(tmp_path, remove):
    flow = tmp_path / "child.u02"
    flow.write_bytes(b"Flow Title=Child\r\nProgram Version=6.60\r\n")
    sidecar = Path(str(flow) + ".hdf")
    with h5py.File(sidecar, "w"):
        pass
    RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
    with h5py.File(sidecar, "r") as hdf:
        assert all(
            group.attrs["Enabled"] == 0
            for group in hdf["Event Conditions/Meteorology"].values()
        )


def test_legacy_nul_boundary_location_fields_are_preserved(tmp_path):
    flow = tmp_path / "child.u02"
    boundary = b"Boundary Location=River,Reach,100," + b"\x00" * 8 + b",,,\r\n"
    flow.write_bytes(b"Flow Title=Child\r\nProgram Version=4.01\r\n" + boundary)
    result = RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    assert boundary in flow.read_bytes()
    assert result["boundary_conditions_unchanged"]


@pytest.mark.parametrize("remove", [False, True])
def test_sidecar_station_metadata_is_supported(tmp_path, remove):
    flow = tmp_path / "child.u02"
    flow.write_bytes(b"Flow Title=Child\r\nProgram Version=6.60\r\n")
    sidecar = Path(str(flow) + ".hdf")
    with h5py.File(sidecar, "w") as hdf:
        met = hdf.create_group("Event Conditions/Meteorology")
        met.create_dataset("Attributes", data=[1])
        met.create_dataset("Meteorology Stations", data=[2, 3])
        met.create_group("Precipitation").attrs["Enabled"] = 1
    RasUnsteady.disable_meteorology(flow, remove_source_references=remove)
    with h5py.File(sidecar, "r") as hdf:
        met = hdf["Event Conditions/Meteorology"]
        if remove:
            assert "Meteorology Stations" not in met and "Attributes" not in met
        else:
            assert list(met["Meteorology Stations"][()]) == [2, 3]
            assert list(met["Attributes"][()]) == [1]


@pytest.mark.parametrize("remove", [False, True])
@pytest.mark.parametrize(
    "bad",
    [
        "event_dataset",
        "met_dataset",
        "variable_dataset",
        "bad_enabled",
        "broken_link",
        "nonempty_sidecar",
        "text_nul",
        "text_unknown",
        "executed_tmp",
    ],
)
def test_invalid_inputs_leave_complete_owned_set_unchanged(tmp_path, remove, bad):
    flow = tmp_path / "child.u02"
    raw = b"Flow Title=Child\r\nPrecipitation Mode=Enable\r\n"
    if bad == "text_nul":
        raw += b"garbage\x00\r\n"
    elif bad == "text_unknown":
        raw = b"not an unsteady flow file\r\n"
    flow.write_bytes(raw)
    sidecar = Path(str(flow) + ".hdf")
    compiled = tmp_path / "child.p02.tmp.hdf"
    for target in (sidecar, compiled):
        with h5py.File(target, "w") as hdf:
            hdf.create_group("Event Conditions/Meteorology/Precipitation").attrs[
                "Enabled"
            ] = 1
    # A valid sidecar precedes the malformed compiled target in preflight.
    target = sidecar if bad == "nonempty_sidecar" else compiled
    with h5py.File(target, "w") as hdf:
        if bad == "event_dataset":
            hdf.create_dataset("Event Conditions", data=[1])
        elif bad == "met_dataset":
            hdf.create_dataset("Event Conditions/Meteorology", data=[1])
        elif bad == "variable_dataset":
            hdf.create_dataset("Event Conditions/Meteorology/Precipitation", data=[1])
        elif bad == "bad_enabled":
            hdf.create_group("Event Conditions/Meteorology/Precipitation").attrs[
                "Enabled"
            ] = [0, 1]
        elif bad == "broken_link":
            hdf["Event Conditions"] = h5py.SoftLink("/missing")
        elif bad == "nonempty_sidecar":
            hdf.create_group("Geometry")
        elif bad == "executed_tmp":
            hdf.create_group("Event Conditions")
            hdf.create_group("Results")
    original = {path: path.read_bytes() for path in (flow, sidecar, compiled)}
    with pytest.raises((ValueError, KeyError)):
        RasUnsteady.disable_meteorology(
            flow, compiled_plan_hdf=compiled, remove_source_references=remove
        )
    assert {path: path.read_bytes() for path in original} == original
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        path.name for path in original
    )


@pytest.mark.parametrize("failed_replace", [1, 2, 3])
@pytest.mark.parametrize("persistent", [False, True])
def test_failed_application_rolls_back_all_owned_files(
    tmp_path, monkeypatch, failed_replace, persistent
):
    module = importlib.import_module("ras_commander.RasUnsteady")
    flow = tmp_path / "child.u02"
    flow.write_bytes(b"Flow Title=Child\r\nPrecipitation Mode=Enable\r\n")
    sidecar = Path(str(flow) + ".hdf")
    compiled = tmp_path / "child.p02.tmp.hdf"
    for target in (sidecar, compiled):
        with h5py.File(target, "w") as hdf:
            hdf.create_group("Event Conditions/Meteorology/Precipitation").attrs[
                "Enabled"
            ] = 1
    original = {path: path.read_bytes() for path in (flow, sidecar, compiled)}
    replace = module.os.replace
    calls = 0

    def fail(source, destination):
        nonlocal calls
        calls += 1
        if calls == failed_replace or (persistent and calls >= failed_replace):
            raise PermissionError("injected apply failure")
        return replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(PermissionError, match="injected apply failure"):
        RasUnsteady.disable_meteorology(
            flow, compiled_plan_hdf=compiled, remove_source_references=True
        )
    assert {path: path.read_bytes() for path in original} == original
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        path.name for path in original
    )


def test_failed_hdf_staging_leaves_inputs_unchanged(tmp_path, monkeypatch):
    flow = tmp_path / "child.u02"
    flow.write_bytes(b"Flow Title=Child\r\nPrecipitation Mode=Enable\r\n")
    sidecar = Path(str(flow) + ".hdf")
    with h5py.File(sidecar, "w") as hdf:
        hdf.create_group("Event Conditions")
    original = {path: path.read_bytes() for path in (flow, sidecar)}
    hdf_file = h5py.File

    def fail(path, mode, **kwargs):
        if mode == "r+":
            raise PermissionError("injected staging failure")
        return hdf_file(path, mode, **kwargs)

    monkeypatch.setattr(h5py, "File", fail)
    with pytest.raises(PermissionError, match="injected staging failure"):
        RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    assert {path: path.read_bytes() for path in original} == original


def test_boundary_guard_runs_before_any_input_mutation(tmp_path, monkeypatch):
    flow = tmp_path / "child.u02"
    raw = b"Flow Title=Child\r\nBoundary Location=,,,,,Area,,Inlet,\r\nDSS File=caf\xe9.dss\r\n"
    flow.write_bytes(raw)
    render = RasUnsteady._render_met_precipitation_keys

    def corrupt(lines, desired):
        planned, completed = render(lines, desired)
        return [line.replace("café.dss", "corrupt.dss") for line in planned], completed

    monkeypatch.setattr(RasUnsteady, "_render_met_precipitation_keys", corrupt)
    with pytest.raises(RuntimeError, match="would change boundary condition bytes"):
        RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    assert flow.read_bytes() == raw


@pytest.mark.parametrize(
    "key",
    [
        "Constant Units",
        "Constant Value",
        "Point Interpolation",
        "Gridded DSS Filename",
        "Gridded DSS Pathname",
        "Gridded GDAL Group",
        "Gridded GDAL Folder",
        "Gridded GDAL Filter",
    ],
)
def test_removal_audit_includes_primary_source_keys(tmp_path, key):
    flow = tmp_path / "child.u02"
    source_key = "Met BC=Precipitation|" + key
    flow.write_bytes(
        ("Flow Title=Child\r\n" + source_key + "=source=value\r\n").encode()
    )
    result = RasUnsteady.disable_meteorology(flow, remove_source_references=True)
    assert result["removed_source_keys"] == [source_key]
    assert source_key.encode() not in flow.read_bytes()
