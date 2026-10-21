"""Metadata regressions and real-producer checks for parent display probes."""

import hashlib
import json

import h5py
import numpy as np
import pytest

from ras_commander import parent_display as pd_mod
from ras_commander.parent_display import (
    EMPTY_IN_SOURCE,
    FEATURE_PRESENT,
    NOT_IN_SOURCE,
    READ_ERROR,
    SOURCE_TABLE_INCOMPLETE,
    probe_geometry_features,
)


def _table(hdf, path, rows):
    hdf.create_dataset(path, data=np.zeros((rows, 2)))


def _full_structures(hdf, rows):
    for name in ("Attributes", "Centerline Info", "Centerline Points"):
        _table(hdf, f"Geometry/Structures/{name}", rows)


@pytest.fixture
def make_hdf(tmp_path):
    def build(writer):
        path = tmp_path / "Model.g01.hdf"
        with h5py.File(path, "w") as hdf:
            writer(hdf)
        return path

    return build


def test_all_features_present_report_row_counts(make_hdf):
    def writer(hdf):
        _table(hdf, "Geometry/2D Flow Areas/Attributes", 1)
        _table(hdf, "Geometry/2D Flow Area Break Lines/Attributes", 2940)
        _table(hdf, "Geometry/2D Flow Area Refinement Regions/Attributes", 1)
        _full_structures(hdf, 3)

    probes = probe_geometry_features(make_hdf(writer))
    assert {k: (p.reason_code, p.source_rows) for k, p in probes.items()} == {
        "mesh_areas": (FEATURE_PRESENT, 1),
        "breaklines": (FEATURE_PRESENT, 2940),
        "refinement_regions": (FEATURE_PRESENT, 1),
        "structures": (FEATURE_PRESENT, 3),
    }
    assert not any(p.confirmed_zero for p in probes.values())


def test_absent_group_is_confirmed_zero(make_hdf):
    path = make_hdf(lambda hdf: _table(hdf, "Geometry/2D Flow Areas/Attributes", 1))
    probe = probe_geometry_features(path, ("structures",))["structures"]
    assert probe.reason_code == NOT_IN_SOURCE
    assert probe.source_rows == 0 and probe.confirmed_zero


def test_intact_empty_table_is_confirmed_zero(make_hdf):
    path = make_hdf(lambda hdf: _full_structures(hdf, 0))
    probe = probe_geometry_features(path, ("structures",))["structures"]
    assert probe.reason_code == EMPTY_IN_SOURCE
    assert probe.confirmed_zero


def test_group_without_required_tables_is_incomplete_not_zero(make_hdf):
    # The UPGU1 shape: a Geometry/Structures group exists but its tables do not.
    def writer(hdf):
        hdf.create_group("Geometry/Structures/Property Tables")
        _table(hdf, "Geometry/Structures/Attributes", 2)

    probe = probe_geometry_features(make_hdf(writer), ("structures",))["structures"]
    assert probe.reason_code == SOURCE_TABLE_INCOMPLETE
    assert probe.source_rows is None
    assert probe.missing_datasets == ("Centerline Info", "Centerline Points")
    assert not probe.confirmed_zero


def test_one_unreadable_feature_does_not_hide_the_others(make_hdf):
    def writer(hdf):
        hdf.create_group("Geometry/2D Flow Areas/Attributes")  # a group, not a table
        _table(hdf, "Geometry/2D Flow Area Break Lines/Attributes", 4)

    probes = probe_geometry_features(make_hdf(writer), ("mesh_areas", "breaklines"))
    assert probes["mesh_areas"].reason_code == READ_ERROR
    assert probes["mesh_areas"].detail
    assert not probes["mesh_areas"].confirmed_zero
    assert probes["breaklines"].reason_code == FEATURE_PRESENT


def test_unknown_feature_and_non_hdf_input_fail_loudly(tmp_path, make_hdf):
    path = make_hdf(lambda hdf: None)
    with pytest.raises(ValueError, match="Unknown geometry features"):
        probe_geometry_features(path, ("bridges",))
    bad = tmp_path / "not.hdf"
    bad.write_bytes(b"not an hdf file")
    with pytest.raises(OSError):
        probe_geometry_features(bad)


def test_probe_never_modifies_the_source(make_hdf):
    path = make_hdf(lambda hdf: _full_structures(hdf, 1))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    probe_geometry_features(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_reason_codes_are_the_closed_documented_set():
    assert pd_mod.PROBE_CODES == (
        "FEATURE_PRESENT",
        "NOT_IN_SOURCE",
        "EMPTY_IN_SOURCE",
        "SOURCE_TABLE_INCOMPLETE",
        "READ_ERROR",
    )


# --- applied forcing probe -----------------------------------------------------------

from ras_commander.parent_display import (  # noqa: E402
    APPLIED_BC_GROUP,
    APPLIED_TIME_SERIES,
    probe_applied_forcing,
)


def _bc(hdf, name, steps, columns=(b"Stage", b"Flow"), units=None):
    ds = hdf.create_dataset(f"{APPLIED_BC_GROUP}/{name}", data=np.zeros((steps, len(columns))))
    ds.attrs["Columns"] = np.array(columns)
    if units:
        ds.attrs["Units"] = units


def _time(hdf, steps, units=None):
    ds = hdf.create_dataset(f"{APPLIED_TIME_SERIES}/Time", data=np.arange(steps, dtype="f8"))
    if units:
        ds.attrs["Units"] = units


def test_applied_forcing_lists_series_without_reading_values(make_hdf):
    def writer(hdf):
        _bc(hdf, "Upstream Inflow", 109, units="cfs")
        _bc(hdf, "Downstream", 109, columns=(b"Stage",))
        hdf.create_dataset(f"{APPLIED_BC_GROUP}/Upstream Inflow - Flow per Face", data=np.zeros((109, 3)))
        _time(hdf, 109, units="days")

    probe = probe_applied_forcing(make_hdf(writer))
    assert probe.reason_code == FEATURE_PRESENT and probe.time_steps == 109
    assert probe.time_units == "days" and not probe.confirmed_zero
    names = {b.name: b for b in probe.boundaries}
    assert set(names) == {"Upstream Inflow", "Downstream"}  # per-face tables are not series
    assert names["Upstream Inflow"].columns == ("Stage", "Flow")
    assert names["Upstream Inflow"].units == "cfs" and names["Upstream Inflow"].flow_per_face
    assert names["Downstream"].units is None  # absent attribute stays None, never guessed
    assert not names["Downstream"].flow_per_face and not names["Downstream"].stage_per_face


def test_applied_forcing_absent_empty_incomplete_and_error_are_distinct(make_hdf, tmp_path):
    absent = probe_applied_forcing(make_hdf(lambda hdf: hdf.create_group("Geometry")))
    assert (absent.reason_code, absent.confirmed_zero) == (NOT_IN_SOURCE, True)

    def empty(hdf):
        hdf.create_group(APPLIED_BC_GROUP)

    assert probe_applied_forcing(make_hdf(empty)).reason_code == EMPTY_IN_SOURCE

    def no_time(hdf):
        _bc(hdf, "Inflow", 5)

    incomplete = probe_applied_forcing(make_hdf(no_time))
    assert incomplete.reason_code == SOURCE_TABLE_INCOMPLETE and not incomplete.confirmed_zero
    assert "Time" in incomplete.detail

    def not_dataset(hdf):
        hdf.create_group(f"{APPLIED_BC_GROUP}/Inflow")
        _time(hdf, 5)

    assert probe_applied_forcing(make_hdf(not_dataset)).reason_code == SOURCE_TABLE_INCOMPLETE

    def bad_columns(hdf):
        _bc(hdf, "Inflow", 5)
        hdf[f"{APPLIED_BC_GROUP}/Inflow"].attrs["Columns"] = 7  # not iterable
        _time(hdf, 5)

    errored = probe_applied_forcing(make_hdf(bad_columns))
    assert errored.reason_code == READ_ERROR and not errored.confirmed_zero


def test_applied_probe_never_modifies_the_source_and_rejects_non_hdf(make_hdf, tmp_path):
    path = make_hdf(lambda hdf: (_bc(hdf, "Inflow", 5), _time(hdf, 5)))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    probe_applied_forcing(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    bad = tmp_path / "not.hdf"
    bad.write_bytes(b"nope")
    with pytest.raises(OSError):
        probe_applied_forcing(bad)


# --- configured forcing normalizer: exercised through the REAL parser ----------------

import types  # noqa: E402

import pandas as pd  # noqa: E402

from ras_commander import RasUnsteady  # noqa: E402
from ras_commander.parent_display import normalize_configured_boundaries  # noqa: E402

_LOC_2D = "                ,                ,        ,        ,                ,UPGU1_2DArea    ,                ,BC_1           ,"
_LOC_1D = "Brazos,Main,100.0,        ,                ,                ,                ,                ,"


def _u_file(tmp_path):
    rows = "   100.0   200.0   300.0"
    text = (
        "Flow Title=Synthetic\n"
        f"Boundary Location={_LOC_2D}\n"
        "DSS File=\n"
        "Flow Hydrograph= 3 \n"
        f"{rows}\n"
        f"Boundary Location={_LOC_1D}\n"
        "DSS File=C:/private/path/inflow.dss\n"
        "Stage Hydrograph= 3 \n"
        f"{rows}\n"
        f"Boundary Location={_LOC_2D}\n"
        "Friction Slope=0.001,0\n"
    )
    path = tmp_path / "Model.u01"
    path.write_text(text)
    return path


def _real_frame(tmp_path):
    stub = types.SimpleNamespace(check_initialized=lambda: None)
    return RasUnsteady.extract_boundary_and_tables(str(_u_file(tmp_path)), ras_object=stub)


def test_real_parser_output_is_normalized_without_inventing_fields(tmp_path):
    frame = _real_frame(tmp_path)
    assert {"DSS File", "Tables", "River Name", "Blank 1"} <= set(frame.columns)
    found = normalize_configured_boundaries(frame)
    assert len(found) == 3
    first, second, third = found
    assert first["location_fields"] == {"Storage Area Name": "UPGU1_2DArea", "Blank 1": "BC_1"}
    assert (first["bc_type"], first["has_table"], first["dss_linked"]) == ("Flow Hydrograph", True, False)
    assert second["location_fields"]["River Name"] == "Brazos" and second["dss_linked"] is True
    assert "private" not in json.dumps(found)  # the DSS path is never copied
    assert third["bc_type"] is None and third["table_types"] == []  # no table header: type unknown
    assert all(set(d) == {"location_fields", "table_types", "bc_type", "has_table", "dss_linked"}
               for d in found)  # no name, units or interval is made up


def test_empty_and_none_normalize_to_nothing_and_foreign_frames_are_rejected():
    assert normalize_configured_boundaries(None) == []
    assert normalize_configured_boundaries(pd.DataFrame()) == []
    with pytest.raises(ValueError, match="missing columns"):
        normalize_configured_boundaries(pd.DataFrame({"a": [1]}))


def test_blank_and_non_string_cells_do_not_become_identity():
    frame = pd.DataFrame(
        {"DSS File": [None], "Tables": [None], "River Name": [float("nan")], "Reach Name": ["  "]}
    )
    (descriptor,) = normalize_configured_boundaries(frame)
    assert descriptor["location_fields"] == {} and descriptor["dss_linked"] is False
    assert descriptor["table_types"] == [] and descriptor["bc_type"] is None


def test_several_known_tables_leave_the_type_unresolved():
    frame = pd.DataFrame(
        {"DSS File": [""], "Tables": [{"Flow Hydrograph": 1, "Stage Hydrograph": 2}], "River Name": ["R"]}
    )
    (descriptor,) = normalize_configured_boundaries(frame)
    assert descriptor["bc_type"] is None and len(descriptor["table_types"]) == 2


@pytest.mark.parametrize("table", ["Centerline Info", "Centerline Points"])
def test_declared_structures_with_empty_support_table_are_incomplete(make_hdf, table):
    def writer(hdf):
        _full_structures(hdf, 2)
        del hdf[f"Geometry/Structures/{table}"]
        _table(hdf, f"Geometry/Structures/{table}", 0)
    result = probe_geometry_features(make_hdf(writer), ("structures",))["structures"]
    assert result.reason_code == SOURCE_TABLE_INCOMPLETE
    assert result.source_rows == 2 and not result.confirmed_zero
    assert table in result.detail


@pytest.mark.parametrize("defect", ["short_series", "scalar_series", "time_group", "time_matrix", "column_count"])
def test_applied_forcing_rejects_shape_inconsistency(make_hdf, defect):
    def writer(hdf):
        _bc(hdf, "Inflow", 2 if defect == "short_series" else 3)
        _time(hdf, 3)
        series = f"{APPLIED_BC_GROUP}/Inflow"
        time = f"{APPLIED_TIME_SERIES}/Time"
        if defect == "scalar_series":
            del hdf[series]
            hdf.create_dataset(series, data=1.0)
        elif defect in ("time_group", "time_matrix"):
            del hdf[time]
            if defect == "time_group":
                hdf.create_group(time)
            else:
                hdf.create_dataset(time, data=np.zeros((3, 1)))
        elif defect == "column_count":
            hdf[series].attrs["Columns"] = [b"Stage"]
    result = probe_applied_forcing(make_hdf(writer))
    assert result.reason_code == SOURCE_TABLE_INCOMPLETE
    assert result.detail and not result.confirmed_zero and not result.boundaries


def test_probes_do_not_read_dataset_values(make_hdf, monkeypatch):
    path = make_hdf(lambda hdf: (_full_structures(hdf, 2), _bc(hdf, "Inflow", 3), _time(hdf, 3)))
    def reject_values(*args, **kwargs):
        raise AssertionError("Probe attempted to read a dataset value array")
    monkeypatch.setattr(h5py.Dataset, "__getitem__", reject_values)
    assert probe_geometry_features(path)["structures"].reason_code == FEATURE_PRESENT
    assert probe_applied_forcing(path).reason_code == FEATURE_PRESENT


@pytest.mark.parametrize("project,filename,structures,breaklines", [
    ("BaldEagleCrkMulti2D", "BaldEagleDamBrk.g02.hdf", 2, 7),
    ("Muncie", "Muncie.g02.hdf", 2, 2),
])
def test_real_geometry_producer_metadata(tmp_path, project, filename, structures, breaklines):
    from pathlib import Path
    from ras_commander import RasExamples
    folder = RasExamples.extract_project(project, output_path=tmp_path, suffix="probe")
    folder = Path(folder[0] if isinstance(folder, list) else folder)
    path = folder / filename
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = probe_geometry_features(path)
    assert result["mesh_areas"].reason_code == FEATURE_PRESENT
    assert result["structures"].reason_code == FEATURE_PRESENT
    assert result["structures"].source_rows == structures
    assert result["breaklines"].reason_code == FEATURE_PRESENT
    assert result["breaklines"].source_rows == breaklines
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_real_applied_forcing_metadata():
    import os
    from pathlib import Path
    value = os.environ.get("RAS_PARENT_DISPLAY_PLAN_HDF")
    if not value:
        pytest.skip("Set RAS_PARENT_DISPLAY_PLAN_HDF to a computed plan with applied BC series")
    path = Path(value)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with h5py.File(path, "r") as hdf:
        expected_steps = hdf[f"{APPLIED_TIME_SERIES}/Time"].shape[0]
        names = sorted(n for n in hdf[APPLIED_BC_GROUP] if not n.endswith((" - Flow per Face", " - Stage per Face")))
    result = probe_applied_forcing(path)
    assert result.reason_code == FEATURE_PRESENT
    assert result.time_steps == expected_steps
    assert [b.name for b in result.boundaries] == names
    assert all(b.time_steps == expected_steps for b in result.boundaries)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
