"""Read-only IC station validation against an official 1D example geometry."""

import hashlib
import os
from pathlib import Path
import zipfile

import pytest

from ras_commander import RasExamples, RasPrj, RasUnsteady, init_ras_project
from ras_commander.geom import GeomCrossSection


def test_present_ic_missing_geometry_never_passes_without_project(tmp_path):
    # Synthetic missing-input control; native identity checks use real projects below.
    flow = tmp_path / "MissingGeometry.u01"
    flow.write_text("Initial Flow Loc=Validation River,Validation Reach,1,10\n")
    result = RasUnsteady.validate_initial_flow_stations(
        flow, tmp_path / "missing.g01", ras_object=RasPrj(),
    )
    assert result["valid"] is False
    assert result["status"] == "unavailable"
    assert result["reason"] == "geometry_file_missing"
    assert result["ic_count"] == len(result["unmatched"]) == 1


@pytest.fixture(scope="module")
def native_pair(tmp_path_factory):
    root = tmp_path_factory.mktemp("initial-flow-real")
    try:
        project = RasExamples.extract_project("Balde Eagle Creek", output_path=root, suffix="ic_validation")
    except Exception as exc:
        pytest.skip(f"Official example archive unavailable: {exc}")
    ras_object = init_ras_project(
        project, "7.0", ras_object="new", load_results_summary=False, hide_intro=True,
    )
    flows = ras_object.unsteady_df
    unsteady = Path(flows.loc[flows.unsteady_number == "02", "full_path"].iloc[0])
    plans = ras_object.plan_df
    geom_number = plans.loc[plans.unsteady_number == "02", "Geom File"].iloc[0]
    geom = Path(ras_object.geom_df.loc[
        ras_object.geom_df.geom_number == geom_number, "full_path",
    ].iloc[0])
    return unsteady, geom, ras_object


def test_real_initial_flow_matches_canonical_geometry_columns(native_pair):
    unsteady, geom, ras_object = native_pair
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (unsteady, geom)}
    result = RasUnsteady.validate_initial_flow_stations(str(unsteady), geom, ras_object=ras_object)
    assert result["valid"] is True
    assert result["status"] == "passed"
    assert result["reason"] == "stations_match_geometry"
    assert result["ic_count"] == len(result["matched"]) == 1
    assert result["geom_xs_count"] == 189
    assert result["unmatched"] == []
    assert result["matched"][0]["station"] == 138154.4
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before} == before


def test_real_present_ic_missing_geometry_is_unavailable(native_pair, tmp_path):
    unsteady, _, ras_object = native_pair
    result = RasUnsteady.validate_initial_flow_stations(unsteady, tmp_path / "missing.g99", ras_object=ras_object)
    assert result["valid"] is False
    assert result["status"] == "unavailable"
    assert result["reason"] == "geometry_file_missing"
    assert result["ic_count"] == len(result["unmatched"]) == 1
    assert result["geom_xs_count"] == 0


def test_real_present_ic_geometry_without_xs_is_unavailable(native_pair, tmp_path):
    unsteady, _, ras_object = native_pair
    empty = tmp_path / "incomplete.g99"
    empty.write_text("Geom Title=Incomplete\n")
    result = RasUnsteady.validate_initial_flow_stations(unsteady, empty, ras_object=ras_object)
    assert result["valid"] is False
    assert result["status"] == "unavailable"
    assert result["reason"] == "geometry_has_no_cross_sections"


def test_real_present_ic_geometry_reader_failure_is_unavailable(native_pair, monkeypatch):
    unsteady, geom, ras_object = native_pair
    def unreadable(*args, **kwargs):
        raise OSError("simulated geometry read failure")
    monkeypatch.setattr(GeomCrossSection, "get_cross_sections", staticmethod(unreadable))
    result = RasUnsteady.validate_initial_flow_stations(unsteady, geom, ras_object=ras_object)
    assert result["valid"] is False
    assert result["status"] == "unavailable"
    assert result["reason"] == "geometry_read_failed"


def test_mismatching_ic_against_real_geometry_fails(native_pair, tmp_path):
    unsteady, geom, ras_object = native_pair
    changed = tmp_path / "wrong-station.u02"
    raw = unsteady.read_bytes()
    old = b"Initial Flow Loc=Bald Eagle      ,Loc Hav         ,138154.4,2000"
    assert raw.count(old) == 1
    changed.write_bytes(raw.replace(old, old.replace(b"138154.4", b"999999.0")))
    result = RasUnsteady.validate_initial_flow_stations(changed, geom, ras_object=ras_object)
    assert result["valid"] is False
    assert result["status"] == "failed"
    assert result["reason"] == "unmatched_flow_stations"
    assert len(result["unmatched"]) == 1


@pytest.mark.parametrize("geometry_available", [True, False])
def test_no_flow_entries_is_explicitly_not_applicable(native_pair, tmp_path, geometry_available):
    unsteady, geom, ras_object = native_pair
    empty = tmp_path / "no-initial-flow.u02"
    empty.write_bytes(b"".join(
        line for line in unsteady.read_bytes().splitlines(keepends=True)
        if not line.startswith(b"Initial Flow Loc=")
    ))
    result = RasUnsteady.validate_initial_flow_stations(
        empty, geom if geometry_available else tmp_path / "missing.g99", ras_object=ras_object,
    )
    assert result["valid"] is True
    assert result["status"] == "not_applicable"
    assert result["reason"] == "no_initial_flow_entries"
    assert result["ic_count"] == 0
    assert result["matched"] == result["unmatched"] == []


@pytest.fixture
def example6_geometry(tmp_path):
    archive = os.environ.get("RAS_COMMANDER_FLOODWAY_EXAMPLES_ZIP")
    if archive:
        with zipfile.ZipFile(archive) as source:
            raw = source.read("Applications Guide/Example 6 - Floodway Determination/FLODENCR.g01")
        path = tmp_path / "FLODENCR.g01"
        path.write_bytes(raw)
    else:
        try:
            project = RasExamples.extract_project(
                "Example 6 - Floodway Determination", output_path=tmp_path,
            )
        except Exception as exc:
            pytest.skip(f"Official Example 6 unavailable: {exc}")
        path = project / "FLODENCR.g01"
    xs = GeomCrossSection.get_cross_sections(path)
    assert len(xs) == 13
    assert {"5.875*", "5.685*", "5.49*", "5.24*", "5.065*"} <= set(xs.RS)
    return path


@pytest.mark.parametrize("station", ["5.99", "5.875"])
def test_example6_interpolation_markers_do_not_invalidate_matching_ic_control(
    example6_geometry, native_pair, tmp_path, station,
):
    # Authentic native geometry with a synthetic one-entry IC matching control;
    # this tests station identity, not native Example 6 unsteady computation.
    # Native geometry's trailing '*' annotates the numeric RS. The IC reader's
    # supported numeric station representation deliberately has no '*'.
    unsteady = tmp_path / "matching-control.u01"
    unsteady.write_text(f"Initial Flow Loc=Beaver Creek,Kentwood,{station},1\n")
    before = hashlib.sha256(example6_geometry.read_bytes()).hexdigest()
    result = RasUnsteady.validate_initial_flow_stations(
        unsteady, example6_geometry, ras_object=native_pair[2],
    )
    assert result["valid"] is True
    assert result["status"] == "passed"
    assert result["reason"] == "stations_match_geometry"
    assert result["geom_xs_count"] == 13
    assert result["ic_count"] == len(result["matched"]) == 1
    assert result["unmatched"] == []
    assert result["matched"][0]["station"] == float(station)
    assert hashlib.sha256(example6_geometry.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("bad_station", ["5.875**", "5.875*extra", "nan", "inf", "-inf"])
def test_malformed_or_nonfinite_geometry_station_is_unavailable(
    example6_geometry, native_pair, bad_station,
):
    raw = example6_geometry.read_bytes()
    assert raw.count(b",5.875*") == 1
    example6_geometry.write_bytes(raw.replace(b",5.875*", b"," + bad_station.encode()))
    result = RasUnsteady.validate_initial_flow_stations(
        native_pair[0], example6_geometry, ras_object=native_pair[2],
    )
    assert result["valid"] is False
    assert result["status"] == "unavailable"
    assert result["reason"] == "geometry_read_failed"
    assert result["geom_xs_count"] == 0


@pytest.mark.parametrize("station", ["nan", "inf", "-inf"])
def test_nonfinite_initial_station_never_matches(native_pair, tmp_path, station):
    unsteady = tmp_path / "invalid-station.u01"
    unsteady.write_text(f"Initial Flow Loc=Bald Eagle,Loc Hav,{station},1\n")
    result = RasUnsteady.validate_initial_flow_stations(
        unsteady, native_pair[1], ras_object=native_pair[2],
    )
    assert result["valid"] is False
    assert result["status"] == "failed"
    assert result["reason"] == "unmatched_flow_stations"
    assert result["geom_xs_count"] == 189
    assert len(result["unmatched"]) == 1


@pytest.mark.parametrize("river,reach", [("bald eagle", "Loc Hav"), ("Bald Eagle", "loc hav")])
def test_river_and_reach_matching_remains_exact(native_pair, tmp_path, river, reach):
    unsteady = tmp_path / "different-name.u01"
    unsteady.write_text(f"Initial Flow Loc={river},{reach},138154.4,1\n")
    result = RasUnsteady.validate_initial_flow_stations(
        unsteady, native_pair[1], ras_object=native_pair[2],
    )
    assert result["valid"] is False
    assert result["status"] == "failed"
