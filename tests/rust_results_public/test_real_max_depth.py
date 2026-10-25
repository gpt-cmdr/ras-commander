"""Public ``get_mesh_max_depth`` native route on real computed HEC-RAS plans.

Each plan is compared three ways: native-required versus the unchanged Python
route, both versus an independent raw-h5py oracle, and kernel fields (peak row,
counts, exceedance, peak time) versus the oracle. Stored 5.x/6.x/7.x coverage
is whatever ``fixture_manifest.json`` lists; absent files are unavailable.
"""
from datetime import datetime
import hashlib
import warnings

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import fast_results
from ras_commander.hdf.HdfBase import HdfBase
from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh
from rust_analysis_conformance.oracle import assert_matches, oracle

from .conftest import MANIFEST, entries, fixture_file

BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas"
THRESHOLD = 0.5
UNSTEADY = entries(unsteady=True)
# Some stored 5.0.3 plans name meshes in "Geometry/2D Flow Areas/Names" and have
# no "Attributes"; existing public mesh discovery (both routes) returns no rows.
# The public 5.0.7 eBFE AustinOyster.p03 plan has Attributes and is covered normally.
DISCOVERY_GAP = pytest.mark.xfail(
    strict=True, reason="pre-existing: mesh discovery needs Attributes (see OUTPUT.md)")
PUBLIC = [pytest.param(e, id=e["path"], marks=DISCOVERY_GAP)
          if e.get("discovery_gap") else pytest.param(e, id=e["path"])
          for e in UNSTEADY]


def ids(items):
    return [e["path"] for e in items]


def series(hdf, mesh):
    group = hdf[f"{BASE}/{mesh}"]
    if "Depth" in group:
        return group["Depth"], None
    offset = hdf[f"Geometry/2D Flow Areas/{mesh}/Cells Minimum Elevation"][()]
    return group["Water Surface"], offset


def raw_oracle(dataset, offset, threshold=None, width=20_000):
    """Oracle over raw h5py column blocks, bounding test memory on large meshes."""
    parts = []
    for start in range(0, dataset.shape[1], width):
        stop = min(start + width, dataset.shape[1])
        parts.append(oracle(dataset[:, start:stop],
                            None if offset is None else offset[start:stop], threshold))
    if not parts:
        return oracle(np.zeros(dataset.shape, np.float32), offset, threshold)
    return {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}


@pytest.mark.parametrize("entry", MANIFEST["fixtures"], ids=ids(MANIFEST["fixtures"]))
def test_fixture_integrity_and_stored_version(entry):
    path = fixture_file(entry)
    with h5py.File(path, "r") as hdf:
        version = hdf.attrs["File Version"].decode()
        assert version.startswith(f"HEC-RAS {entry['stored_version']}"), version
        assert (BASE in hdf) is entry["unsteady_2d"]
        if entry["unsteady_2d"]:
            for mesh, name in entry["series"].items():
                assert name in hdf[f"{BASE}/{mesh}"]


@pytest.mark.parametrize("entry", entries(unsteady=False), ids=ids(entries(unsteady=False)))
def test_plan_without_results_is_an_error_not_an_empty_pass(entry, native_calls, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with pytest.raises(ValueError, match="Depth is absent"):
        HdfResultsMesh.get_mesh_max_depth(fixture_file(entry))
    assert not native_calls


@pytest.mark.parametrize("entry", PUBLIC)
def test_public_max_depth_native_equals_python_route(entry, native_calls, forbid_python,
                                                     monkeypatch):
    path = fixture_file(entry)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    accelerated = HdfResultsMesh.get_mesh_max_depth(path)
    assert len(native_calls) == len(entry["series"])
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    reference = HdfResultsMesh.get_mesh_max_depth(path)
    assert len(native_calls) == len(entry["series"])  # Python route made no native call
    assert set(accelerated["mesh_name"]) == set(entry["series"])
    pd.testing.assert_frame_equal(accelerated.drop(columns="geometry"),
                                  reference.drop(columns="geometry"), check_exact=True)
    assert accelerated.geometry.equals(reference.geometry)
    assert accelerated.crs == reference.crs
    assert accelerated["maximum_depth"].dtype == np.float32
    baseline = entry.get("baseline")
    if baseline:  # independent supervisor capture on the clean baseline
        assert len(accelerated) == baseline["rows"]
        assert accelerated.crs.to_string() == baseline["crs"]
        assert accelerated["maximum_depth"].notna().sum() == baseline["rows"]
        assert accelerated.groupby("mesh_name").size().to_dict() == baseline["per_mesh"]


@pytest.mark.parametrize("entry", PUBLIC)
def test_public_max_depth_matches_raw_oracle_including_ghosts(entry, native_calls,
                                                              monkeypatch):
    path = fixture_file(entry)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    result = HdfResultsMesh.get_mesh_max_depth(path, include_ghost_cells=True)
    with h5py.File(path, "r") as hdf:
        for mesh in entry["series"]:
            rows = result[result["mesh_name"] == mesh]
            dataset, offset = series(hdf, mesh)
            expected = raw_oracle(dataset, offset)["maximum"]
            np.testing.assert_array_equal(rows["cell_id"].to_numpy(), np.arange(len(expected)))
            np.testing.assert_array_equal(rows["maximum_depth"].to_numpy(), expected)


@pytest.mark.parametrize("entry", UNSTEADY, ids=ids(UNSTEADY))
def test_kernel_fields_and_peak_times_match_oracle(entry, native_calls):
    path = fixture_file(entry)
    with h5py.File(path, "r") as hdf:
        stamps = HdfBase.get_unsteady_timestamps(hdf)
        for mesh in entry["series"]:
            dataset, offset = series(hdf, mesh)
            expected = raw_oracle(dataset, offset, THRESHOLD)
            native = fast_results.temporal_reduce(dataset, offset, threshold=THRESHOLD,
                                                  backend="rust")
            assert_matches(native, expected)
            # One-chunk blocks exercise every block boundary on real chunk layouts.
            narrow = fast_results.temporal_reduce(dataset, offset, threshold=THRESHOLD,
                                                  backend="rust", max_block_bytes=1)
            assert native.maximum.tobytes() == narrow.maximum.tobytes()
            np.testing.assert_array_equal(native.peak_index, narrow.peak_index)
            assert_matches(fast_results.temporal_reduce(dataset, offset, threshold=THRESHOLD,
                                                        backend="python"), expected)
            times = fast_results.peak_times_ms(stamps, native.peak_index)
            epoch = datetime(1970, 1, 1)
            for cell in np.flatnonzero(expected["peak_index"] >= 0)[::97]:
                stamp = stamps[expected["peak_index"][cell]]
                assert times[cell] == round((stamp - epoch).total_seconds() * 1000)
            assert times.mask.tolist() == (expected["peak_index"] < 0).tolist()
    assert len(native_calls) == 2 * len(entry["series"])


def _family(prefix):
    return [e for e in UNSTEADY if e["path"].startswith(prefix)]


def _digest(dataset):
    return hashlib.sha256(np.ascontiguousarray(dataset[()]).tobytes()).hexdigest()


def test_cross_plan_envelope_on_distinct_ensemble_members(native, monkeypatch):
    members = _family("v66_BE_mc/")
    assert len(members) >= 3
    paths = [fixture_file(e) for e in members]
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    maxima, digests, centers = [], set(), None
    for path in paths:
        with h5py.File(path, "r") as hdf:
            mesh = next(iter(members[0]["series"]))
            here = hdf[f"Geometry/2D Flow Areas/{mesh}/Cells Center Coordinate"][()]
            centers = here if centers is None else centers
            np.testing.assert_array_equal(centers, here)  # element identity across plans
            dataset, offset = series(hdf, mesh)
            digests.add(_digest(dataset))
            maxima.append(fast_results.temporal_reduce(dataset, offset, backend="rust").maximum)
    assert len(digests) == len(paths), "duplicate plans are not ensemble coverage"
    assert any(not np.array_equal(maxima[0], m) for m in maxima[1:])
    envelope, plan = fast_results.cross_plan_maximum(maxima)
    stacked = np.stack(maxima)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN cells stay NaN
        expected = np.nanmax(stacked, axis=0)
    np.testing.assert_array_equal(envelope, expected.astype(np.float32))
    has = ~np.isnan(expected)
    first = (stacked == expected[np.newaxis, :]).argmax(axis=0)
    np.testing.assert_array_equal(plan, np.where(has, first, -1))


def test_cross_plan_envelope_rejects_misaligned_plans(native):
    first, second = (fixture_file(e) for e in _family("v503_P118/")[:2])
    maxima = []
    for path in (first, second):
        with h5py.File(path, "r") as hdf:
            dataset, offset = series(hdf, "2DFlow3")
            maxima.append(fast_results.temporal_reduce(dataset, offset, backend="rust").maximum)
    assert maxima[0].shape != maxima[1].shape
    with pytest.raises(ValueError, match="aligned"):
        fast_results.cross_plan_maximum(maxima)
