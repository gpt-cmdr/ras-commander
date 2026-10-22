"""Retained Lower Calcasieu coastal output; no authoring or native execution.

Set RAS_COASTAL_FIXTURE_ROOT to the qualified case root containing inputs/.
The fixture is private retained evidence and is never downloaded by this test.
"""

from datetime import datetime
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import HdfCompletion, HdfResultsMesh


BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
BOUNDARY_NAMES = {"CalcRi", "GIWW", "SabineLk", "SabineRiN", "SabineRiS"} | {
    f"GulfStage{index}" for index in range(10)
}


def _text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


@pytest.fixture(scope="module")
def coastal():
    value = os.environ.get("RAS_COASTAL_FIXTURE_ROOT")
    if not value:
        pytest.skip("Set RAS_COASTAL_FIXTURE_ROOT to the retained Lower Calcasieu case")
    root = Path(value)
    paths = {
        "plan": root / "inputs/LC_LowerCalcasieu.p05.hdf",
        "geometry": root / "inputs/LC_LowerCalcasieu.g01.hdf",
        "project": root / "inputs/LC_LowerCalcasieu.prj",
    }
    for path in paths.values():
        assert path.is_file(), f"Configured coastal fixture is incomplete: {path}"
    before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in paths.values()}
    # Read the combined public BC Dataset once; each oracle below is read
    # independently from the native HDF, never another public reader.
    dataset = HdfResultsMesh.get_boundary_conditions_timeseries(paths["plan"])
    yield paths, dataset
    assert {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in before} == before


def test_coastal_boundary_output_matches_native_values_units_and_face_ids(coastal):
    paths, dataset = coastal
    assert dict(dataset.sizes) == {"time": 279, "bc_name": 15, "face_id": 494}
    assert set(dataset.bc_name.values.tolist()) == BOUNDARY_NAMES
    assert set(dataset.data_vars) == {"stage", "flow", "stage_per_face", "flow_per_face"}
    native_face_ids = []
    with h5py.File(paths["plan"], "r") as hdf:
        group = hdf[f"{BASE}/Boundary Conditions"]
        native_names = {
            name for name in group
            if not name.endswith((" - Stage per Face", " - Flow per Face"))
        }
        assert native_names == BOUNDARY_NAMES
        for name in sorted(native_names):
            raw = group[name]
            assert raw.shape == (279, 2)
            columns = [_text(column) for column in raw.attrs["Columns"]]
            assert _text(raw.attrs["2D Area"]) == "LCalcRi"
            assert dataset.area_2d.sel(bc_name=name).item() == "LCalcRi"
            for native_column, variable, units in (("Stage", "stage", "ft"), ("Flow", "flow", "cfs")):
                assert _text(raw.attrs[native_column]) == units
                assert dataset[f"{variable}_units"].sel(bc_name=name).item() == units
                np.testing.assert_array_equal(
                    dataset[variable].sel(bc_name=name).values,
                    raw[:, columns.index(native_column)],
                )
                per_face = group[f"{name} - {native_column} per Face"]
                ids = per_face.attrs["Faces"]
                assert per_face.shape == (279, len(ids))
                assert _text(per_face.attrs["Units"]) == units
                assert len(np.unique(ids)) == len(ids)
                native_face_ids.extend(ids.tolist())
                np.testing.assert_array_equal(
                    dataset[f"{variable}_per_face"].sel(bc_name=name, face_id=ids).values,
                    per_face[:],
                )
    np.testing.assert_array_equal(np.sort(dataset.face_id.values), np.unique(native_face_ids))
    # A genuine signed tidal hydrograph must not be turned into absolute flow.
    gulf_flow = dataset.flow.sel(bc_name="GulfStage0").values
    assert gulf_flow.min() < 0 < gulf_flow.max()


def test_coastal_actual_clock_and_completion_coverage(coastal):
    paths, dataset = coastal
    with h5py.File(paths["plan"], "r") as hdf:
        # This 6.4.1 layout separates milliseconds with a colon. Parse the
        # stored strings directly, independently of the public time helpers.
        raw_stamps = hdf[f"{BASE}/Time Date Stamp (ms)"][:]
        expected = np.asarray([
            datetime.strptime(_text(value), "%d%b%Y %H:%M:%S:%f") for value in raw_stamps
        ], dtype="datetime64[ns]")
    assert expected.shape == (279,)
    assert expected[0] == np.datetime64("2018-06-17T09:00:00")
    assert expected[-1] == np.datetime64("2018-06-28T23:00:00")
    np.testing.assert_array_equal(np.diff(expected), np.full(278, np.timedelta64(1, "h")))
    np.testing.assert_array_equal(dataset.time.values, expected)
    coverage = HdfCompletion.inspect_time_coverage(paths["plan"])
    assert coverage["status"] == "covered"
    assert coverage["row_count"] == 279
    assert coverage["observed_start"] == coverage["declared_start"] == datetime(2018, 6, 17, 9)
    assert coverage["observed_end"] == coverage["declared_end"] == datetime(2018, 6, 28, 23)


def test_coastal_water_surface_uses_bounded_physical_cell_selection(coastal):
    paths, _ = coastal
    with h5py.File(paths["plan"], "r") as hdf:
        attributes = hdf["Geometry/2D Flow Areas/Attributes"][:]
        selected = [row for row in attributes if _text(row["Name"]) == "LCalcRi"]
        assert len(selected) == 1
        physical_count = int(selected[0]["Cell Count"])
        assert physical_count == 132178
        raw = hdf[f"{BASE}/2D Flow Areas/LCalcRi/Water Surface"]
        assert raw.shape == (279, 133981)
        assert raw.shape[1] - physical_count == 1803
        assert _text(raw.attrs["Location"]) == "Cells"
        assert _text(raw.attrs["Units"]) == "ft"
        expected = raw[0:3, 0:5]  # Never materialize the full mesh matrix.
    actual = HdfResultsMesh.get_mesh_timeseries(
        paths["plan"], "LCalcRi", "Water Surface", truncate=False,
        time_selection=slice(0, 3), spatial_selection=slice(0, 5),
    )
    assert actual.shape == (3, 5)
    assert actual.attrs["units"] == "ft"
    np.testing.assert_array_equal(actual.values, expected)
    np.testing.assert_array_equal(actual.cell_id.values, np.arange(5))
    assert not actual.is_ghost_cell.values.any()


def test_coastal_native_project_retains_datum_and_clock_provenance(coastal):
    paths, _ = coastal
    lines = paths["project"].read_text(encoding="utf-8").splitlines()
    assert "English Units" in lines
    assert "Vertical Datum: NAVD 1988 GEOID12B" in lines
    assert "Datetime Unit: Coordinated Universal Time (UTC)" in lines
    assert "Unit System: US Customary Units" in lines
    with h5py.File(paths["plan"], "r") as hdf:
        assert _text(hdf.attrs["File Type"]) == "HEC-RAS Results"
        assert _text(hdf.attrs["File Version"]) == "HEC-RAS 6.4.1 June 2023"
        assert _text(hdf.attrs["Units System"]) == "US Customary"
    # These assertions bind source metadata, not a datum conversion or an
    # executable-run qualification. No native model is run by these tests.
