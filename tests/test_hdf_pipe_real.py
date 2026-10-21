"""Real Davis regressions; set HDFPIPE_TEST_HDF to a computed Davis p02 HDF."""
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import RasPrj
from ras_commander.hdf import HdfPipe


@pytest.fixture(scope="module")
def davis_hdf():
    source = os.environ.get("HDFPIPE_TEST_HDF")
    if not source:
        pytest.skip("Set HDFPIPE_TEST_HDF to computed DavisStormSystem.p02.hdf")
    path = Path(source)
    assert path.is_file(), f"Configured Davis HDF is missing: {path}"
    return path


@pytest.fixture(scope="module")
def davis_project(davis_hdf):
    # Exercise the real decorator's DataFrame-backed resolution without running RAS.
    project = RasPrj()
    project.plan_df = pd.DataFrame({"plan_number": ["02"], "HDF_Results_Path": [str(davis_hdf)]})
    project.initialized = True
    return project


@pytest.mark.parametrize("kind,stored_id", [("node", 121), ("conduit", 0)])
@pytest.mark.parametrize("block", ["Base Output", "DSS Hydrograph Output"])
@pytest.mark.parametrize("keyword", [False, True])
@pytest.mark.parametrize("plan", [2, "02", "p02"])
def test_extract_plan_number_uses_explicit_project(davis_hdf, davis_project, kind, stored_id, block, keyword, plan):
    extract = getattr(HdfPipe, f"extract_timeseries_for_{kind}")
    kwargs = {f"{kind}_id": stored_id, "output_block": block, "ras_object": davis_project}
    result = extract(plan_hdf_path=plan, **kwargs) if keyword else extract(plan, **kwargs)
    with h5py.File(davis_hdf) as raw:
        ids = raw[f"Geometry/Pipe Networks/Davis/{'Node' if kind == 'node' else 'Conduit'} Indices"][()]
        position = int(np.flatnonzero(ids == stored_id)[0])
        for variable, data in result.items():
            expected = raw[f"Results/Unsteady/Output/Output Blocks/{block}/Unsteady Time Series/Pipe Networks/Davis/{variable}"][()]
            np.testing.assert_array_equal(data.values, expected[:, position])
            assert data.coords[f"{kind}_id"].item() == stored_id
            assert data.coords["location"].item() == position
            assert data.attrs["output_block"] == block


@pytest.mark.parametrize("form", ["path", "str", "handle"])
def test_timeseries_flexible_inputs(davis_hdf, form):
    with h5py.File(davis_hdf) as raw:
        source = {"path": davis_hdf, "str": str(davis_hdf), "handle": raw}[form]
        result = HdfPipe.get_pipe_network_timeseries(source, "Nodes/Depth")
        np.testing.assert_array_equal(result.node_id, raw["Geometry/Pipe Networks/Davis/Node Indices"][()])
        assert raw.id.valid  # Caller-owned handles remain open.


@pytest.mark.parametrize("kind", ["node", "conduit"])
def test_unknown_stored_id_raises(davis_hdf, kind):
    with pytest.raises(KeyError, match=f"Pipe {kind} id"):
        getattr(HdfPipe, f"extract_timeseries_for_{kind}")(davis_hdf, -999)


def test_real_geometry_projection_and_row_alignment(davis_hdf):
    cells = HdfPipe.get_pipe_network(davis_hdf)
    with h5py.File(davis_hdf) as raw:
        group = raw["Geometry/Pipe Networks/Davis"]
        assert len(cells) == len(group["Cell Polygons Info"])
        assert len({g.wkb for g in cells.geometry}) == len(cells)
        np.testing.assert_array_equal(cells["Cell_Property_Info_Index"], group["Cell Property Table"][()]["Info Index"])
        for row in cells.loc[cells.Node_ID >= 0].itertuples():
            np.testing.assert_array_equal(row.Node_Point.coords[0], raw["Geometry/Pipe Nodes/Points"][int(row.Node_ID)])
    assert cells.crs.to_epsg() == 2871


def test_real_summary_retains_literal_rows(davis_hdf):
    summary = HdfPipe.get_pipe_network_summary(davis_hdf)
    with h5py.File(davis_hdf) as raw:
        for path, rows in summary[summary.source == "summary"].groupby("path"):
            stored = raw[path][()]
            assert len(rows) == stored.size
            np.testing.assert_array_equal(rows.value.to_numpy(dtype=float), stored.ravel())
        assert summary.loc[summary.source == "volume_accounting", "units"].isna().all()


@pytest.mark.parametrize("block", ["Base Output", "DSS Hydrograph Output"])
@pytest.mark.parametrize("variable", [
    "Cell Courant", "Cell Water Surface", "Face Flow", "Face Velocity", "Face Water Surface",
    "Pipes/Pipe Flow DS", "Pipes/Pipe Flow US", "Pipes/Vel DS", "Pipes/Vel US",
    "Nodes/Depth", "Nodes/Drop Inlet Flow", "Nodes/Water Surface",
])
def test_all_real_timeseries_match_stored_values(davis_hdf, block, variable):
    result = HdfPipe.get_pipe_network_timeseries(davis_hdf, variable, output_block=block)
    with h5py.File(davis_hdf) as raw:
        base = f"Results/Unsteady/Output/Output Blocks/{block}/Unsteady Time Series"
        stored = raw[f"{base}/Pipe Networks/Davis/{variable}"]
        np.testing.assert_array_equal(result.values, stored[()])
        stamps = raw[f"{base}/Time Date Stamp"][()]
        expected_time = pd.to_datetime([x.decode() for x in stamps], format="%d%b%Y %H:%M:%S")
        np.testing.assert_array_equal(result.time.values, expected_time.to_numpy())


@pytest.mark.parametrize("damage,match", [
    ("location", "unsupported stored Location"),
    ("ids", "unique rank-one"),
    ("timestamps", "timestamp count/shape mismatch"),
    ("profile_slice", "slice is out of bounds"),
    ("profile_partial", "partially present"),
])
def test_malformed_real_copy_is_rejected(davis_hdf, tmp_path, damage, match):
    import shutil

    copied = tmp_path / "damaged.p02.hdf"
    shutil.copyfile(davis_hdf, copied)
    base = "Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/Unsteady Time Series"
    with h5py.File(copied, "r+") as raw:
        if damage == "location":
            raw[f"{base}/Pipe Networks/Davis/Nodes/Depth"].attrs["Location"] = b"Unknown"
        elif damage == "ids":
            ids = raw["Geometry/Pipe Networks/Davis/Node Indices"]
            ids[1] = ids[0]
        elif damage == "timestamps":
            for name in ["Time Date Stamp (ms)", "Time Date Stamp"]:
                if f"{base}/{name}" in raw:
                    del raw[f"{base}/{name}"]
            raw.create_dataset(f"{base}/Time Date Stamp", data=np.array([b"01Jan2000 00:00:00"]))
        elif damage == "profile_slice":
            profiles = raw["Geometry/Pipe Conduits/Terrain Profiles Info"]
            profiles[0] = [len(raw["Geometry/Pipe Conduits/Terrain Profiles Values"]) + 1, 1]
        elif damage == "profile_partial":
            del raw["Geometry/Pipe Conduits/Terrain Profiles Values"]
    if damage.startswith("profile"):
        with pytest.raises((KeyError, ValueError), match=match):
            HdfPipe.get_pipe_conduits(copied)
    else:
        with pytest.raises(ValueError, match=match):
            HdfPipe.get_pipe_network_timeseries(copied, "Nodes/Depth")
