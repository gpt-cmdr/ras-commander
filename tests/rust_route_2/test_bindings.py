"""Wave 3 binding boundary (bridge API 10) on real fixtures; h5py is the oracle.

Gate: ``RAS_ROUTE2_FIXTURES`` (Davis, Austin, the 7.0.1 reference-point geometry
and the 00-LandCover sidecar must be listed; absent ones skip explicitly).
"""
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pytest

MANIFEST = os.environ.get("RAS_ROUTE2_FIXTURES")
FIXTURES = ({f["name"]: f["path"] for f in json.loads(Path(MANIFEST).read_text())["fixtures"]}
            if MANIFEST else {})
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE2_FIXTURES to the PY-ROUTE-2 real-fixture JSON manifest")

DAVIS_TS = ("Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/"
            "Unsteady Time Series/Pipe Networks/Davis")


@pytest.fixture
def native():
    module = pytest.importorskip("ras_commander_fast_hdf")
    assert module.API_VERSION == 11
    return module


def _fixture(name):
    if name not in FIXTURES:
        pytest.skip(f"{name} not in manifest")
    return FIXTURES[name]


def test_read_families_and_unknown_family(native):
    assert native.read_families() == [
        "pipe_geometry", "pipe_run_summary", "pipe_results", "reference_line_results",
        "reference_point_results", "reference_summaries", "breach", "plan_metadata",
        "land_cover", "infiltration", "sediment", "encroachments", "terrain",
        "event_conditions", "steady_output"]
    with pytest.raises(ValueError, match="unknown read family"):
        native.read_family_inventory(_fixture("DavisStormSystem.p02"), "pipes")


def test_pipe_results_ids_values_slices_and_refusal(native):
    path = _fixture("DavisStormSystem.p02")
    inv = native.read_family_inventory(path, "pipe_results")
    assert inv["capability"]["status"] == "supported"
    by_path = {d["path"]: d for d in inv["datasets"]}
    nodes = by_path[f"{DAVIS_TS}/Nodes/Depth"]
    assert nodes["domain"] == "node" and nodes["capability"]["status"] == "supported"
    with h5py.File(path, "r") as f:
        ids = f["Geometry/Pipe Networks/Davis/Node Indices"][()]
        assert nodes["stored_location_ids"].dtype == ids.dtype
        assert nodes["stored_location_ids"].tobytes() == ids.tobytes()
        full = native.read_family_dataset(path, "pipe_results", f"{DAVIS_TS}/Nodes/Depth")
        assert full["storage"] == "numeric"
        expected = f[f"{DAVIS_TS}/Nodes/Depth"][()]
        assert full["values"].dtype == expected.dtype and full["values"].tobytes() == expected.tobytes()
        part = native.read_family_dataset(path, "pipe_results", f"{DAVIS_TS}/Nodes/Depth",
                                          [(1, 9, 2), (0, 5, 1)])
        assert part["values"].tobytes() == expected[1:9:2, 0:5].tobytes()
    summary = ("Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/"
               "Pipe Networks/Davis/Maximum Water Surface")
    assert by_path[summary]["capability"]["code"] == "identity_layout"
    with pytest.raises(native.UnsupportedError):
        native.read_family_dataset(path, "pipe_results", summary)


def test_pipe_geometry_compound_bytes(native):
    path = _fixture("DavisStormSystem.p02")
    out = native.read_family_dataset(path, "pipe_geometry", "Geometry/Pipe Conduits/Attributes")
    assert out["storage"] == "compound"
    with h5py.File(path, "r") as f:
        ds = f["Geometry/Pipe Conduits/Attributes"]
        assert tuple(out["values"]["shape"]) == ds.shape
        assert [c["name"] for c in out["values"]["columns"]] == list(ds.dtype.names)
        assert len(out["values"]["raw_bytes"]) == ds.size * ds.dtype.itemsize


def test_output_blocks(native):
    path = _fixture("DavisStormSystem.p02")
    blocks = native.output_block_inventory(path)
    assert [b["name"] for b in blocks] == ["Computation Block", "DSS Hydrograph Output",
                                           "DSS Profile Output"]
    with h5py.File(path, "r") as f:
        out = native.read_output_block(path, "DSS Hydrograph Output",
                                       "Unsteady Time Series/Pipe Networks/Davis/Nodes/Depth")
        assert out["values"].tobytes() == f[f"{DAVIS_TS}/Nodes/Depth"][()].tobytes()
    with pytest.raises(ValueError):
        native.read_output_block(path, "Base Output", "Unsteady Time Series/Time")


def test_reference_point_geometry(native):
    path = _fixture("BaldEagleDamBrk.g09.refpts.701")
    out = native.reference_point_geometry(path)
    assert out["capability"]["status"] == "supported"
    with h5py.File(path, "r") as f:
        points = f["Geometry/Reference Points/Points"][()]
        names = [n.decode().strip() for n in f["Geometry/Reference Points/Attributes"][()]["Name"]]
    assert out["value"]["points"].tobytes() == points.tobytes()
    assert [ft["name"] for ft in out["value"]["features"]] == names
    absent = native.reference_point_geometry(_fixture("AustinOyster.p01"))
    assert absent["capability"]["status"] == "unavailable" and absent["value"] is None


def test_classification_catalogue(native):
    path = _fixture("00-LandCover")
    out = native.classification_catalogue(path, "land_cover")
    assert out["capability"]["status"] == "supported"
    assert out["value"]["layout"] and out["value"]["entries"]
    with pytest.raises(ValueError):
        native.classification_catalogue(path, "terrain")


def test_stored_family_index_reports_failures_explicitly(native):
    index = native.stored_family_index(_fixture("DavisStormSystem.p02"))
    assert index["failures"] == []
    owners = {r["owner"] for r in index["datasets"]}
    assert {"pipe_geometry", "pipe_results", "output_block:DSS Hydrograph Output"} <= owners
    for row in index["datasets"]:
        assert row["status"] in {"supported", "unsupported", "unavailable", "corrupt"}
