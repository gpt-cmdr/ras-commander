"""engine="native" with ``min_polygon_area_acres``: exact parity with the reference swap.

The reference swap (``_swap_small_polygons``) explodes the dissolved regions,
relabels small fluvial/pluvial parts and re-dissolves with ``aggfunc='first'``.
Its ``area_acres`` (and ``cell_id``) columns are therefore taken from the first
exploded part, i.e. the GEOS part order of the reference dissolve. That order
is deterministic for the canonical (sorted, normalized) dissolve input, so the
reference is presentation-invariant, but native ring assembly does not
reproduce it. The native engine therefore classifies natively and hands its
labels to the reference's own ``_dissolve_classified_cells`` and
``_swap_small_polygons`` over the same h5py cell polygons.

These tests require the result frames to be identical (same columns, dtypes,
values and WKB geometry) and prove the swap's input frame is byte-identical
across engines. Real fixtures come from ``RAS_FLUVIAL_PUBLIC_FIXTURES`` and
``RAS_FLUVIAL_FIXTURE_DIRS``; missing fixtures skip. The synthetic tests replace
the native snapshot with a stand-in that returns the reference labels in a
permuted native order, so they run without the extension.
"""
import importlib
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import box

from ras_commander.hdf import HdfMesh, HdfResultsMesh

module = importlib.import_module("ras_commander.hdf.HdfFluvialPluvial")
HdfFluvialPluvial = module.HdfFluvialPluvial

PRESENTATIONS = ["original", "rows_reversed", "rows_shuffled", "rings_reversed", "rings_rotated"]
LABELS = {"fluvial": 1, "pluvial": 2, "ambiguous": 3}


@pytest.fixture(autouse=True)
def _default_backend_policy(monkeypatch):
    """Explicit engines ignore the policy; pin it so native reads are not refused."""
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")


def present(cells, how):
    if how == "original":
        return cells.copy()
    if how == "rows_reversed":
        return cells.iloc[::-1].reset_index(drop=True)
    if how == "rows_shuffled":
        return cells.sample(frac=1.0, random_state=610).reset_index(drop=True)
    out = cells.copy()
    if how == "rings_reversed":
        out["geometry"] = shapely.reverse(cells.geometry.values)
        return out
    if how == "rings_rotated":
        rotated = []
        for geom in cells.geometry.values:
            ring = np.asarray(geom.exterior.coords)[:-1]
            rotated.append(shapely.polygons(np.vstack([ring[1:], ring[:1], ring[1:2]])))
        out["geometry"] = rotated
        return out
    raise ValueError(how)


def assert_identical(actual, expected):
    """Same columns, dtypes, values, CRS and byte-identical (WKB) geometry."""
    actual, expected = actual.copy(), expected.copy()
    actual.attrs, expected.attrs = {}, {}
    assert not expected.empty
    assert list(actual.columns) == list(expected.columns)
    assert list(actual.dtypes) == list(expected.dtypes)
    assert actual.crs == expected.crs
    pd.testing.assert_frame_equal(
        pd.DataFrame(actual.drop(columns="geometry")), pd.DataFrame(expected.drop(columns="geometry")),
        check_exact=True)
    assert list(shapely.to_wkb(actual.geometry.values)) == list(shapely.to_wkb(expected.geometry.values))


class Spy:
    """Record the inputs of the shared reference dissolve and swap."""

    def __init__(self, patch):
        self.dissolve, self.swap = [], []
        dissolve = HdfFluvialPluvial._dissolve_classified_cells
        swap = HdfFluvialPluvial._swap_small_polygons

        def spy_dissolve(cells, classifications):
            self.dissolve.append((cells.copy(), classifications.copy()))
            return dissolve(cells, classifications)

        def spy_swap(frame, area):
            self.swap.append(frame.copy())
            return swap(frame, area)
        patch.setattr(HdfFluvialPluvial, "_dissolve_classified_cells", staticmethod(spy_dissolve))
        patch.setattr(HdfFluvialPluvial, "_swap_small_polygons", staticmethod(spy_swap))


def assert_same_swap_inputs(native, reference):
    """The reference dissolve and swap received identical inputs under both engines."""
    (n_cells, n_classes), = native.dissolve
    (r_cells, r_classes), = reference.dissolve
    n_cells.attrs, r_cells.attrs = {}, {}
    pd.testing.assert_series_equal(n_classes, r_classes, check_exact=True)
    assert n_classes.index.equals(r_classes.index)
    assert_identical(n_cells, r_cells)
    (n_swap,), (r_swap,) = native.swap, reference.swap
    assert_identical(n_swap, r_swap)


def parts(frame):
    return sum(len(getattr(geom, "geoms", [geom])) for geom in frame.geometry)


# --------------------------------------------------------------------------- #
# Synthetic: two meshes with colliding cell ids, small islands of each class
# --------------------------------------------------------------------------- #
def synthetic_model():
    cells, times = [], []
    start = pd.Timestamp("2000-01-01")
    for mesh, x0 in (("north", 0.0), ("south", 5000.0)):
        cell = 0
        for row in range(8):
            for col in range(8):
                cells.append({"mesh_name": mesh, "cell_id": cell,
                              "geometry": box(x0 + col * 100, row * 100, x0 + col * 100 + 100, row * 100 + 100)})
                # Late (fluvial) west half, early (pluvial) east half, plus
                # single-cell islands of the opposite timing in each half.
                late = col < 4
                if (row, col) in {(2, 1), (5, 2)}:
                    late = False
                if (row, col) in {(1, 6), (6, 5)}:
                    late = True
                if mesh == "south" and (row, col) == (3, 3):
                    late = not late
                times.append({"mesh_name": mesh, "cell_id": cell,
                              "maximum_water_surface_time": start + pd.Timedelta(hours=48 if late else 0)})
                cell += 1
    return (gpd.GeoDataFrame(cells, geometry="geometry", crs=2271),
            pd.DataFrame(times))


class FakeAnalysis:
    """Native snapshot stand-in: reference labels in a permuted native cell order."""

    def __init__(self, classifications, crs):
        keys = list(classifications.index)[::-1]  # native order differs from the frame order
        self.meshes = tuple(sorted({mesh for mesh, _ in keys}, reverse=True))
        self.sources = tuple((self.meshes.index(mesh), int(cell)) for mesh, cell in keys)
        self.labels = [LABELS[classifications[key]] for key in keys]
        self.crs = crs
        self.setup = {}

    def classify(self, delta_ms, tolerance_ms):
        return list(self.labels), {"label_4": 0, "label_5": 0, "waves": 1}, 0.0

    def polygons(self, labels):  # pragma: no cover - must not run with a min area
        raise AssertionError("native polygon assembly must not run with min_polygon_area_acres")


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.p01.hdf"
    import h5py
    with h5py.File(path, "w"):
        pass
    cells, times = synthetic_model()
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", staticmethod(lambda *a, **k: times.copy()))
    state = {"cells": cells}
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", staticmethod(lambda *a, **k: state["cells"].copy()))
    return path, cells, state


def synthetic_reference_labels(path, monkeypatch, delta_t):
    with pytest.MonkeyPatch.context() as patch:
        spy = Spy(patch)
        HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path, delta_t=delta_t, engine="h5py")
    return spy.dissolve[0][1]


@pytest.mark.parametrize("how", PRESENTATIONS)
@pytest.mark.parametrize("area", [0, 1.0, 5.0, 1e9])
def test_synthetic_native_swap_equals_reference(synthetic, monkeypatch, how, area):
    path, cells, state = synthetic
    labels = synthetic_reference_labels(path, monkeypatch, 12)
    assert set(labels) == {"fluvial", "pluvial"}
    monkeypatch.setattr(module, "_native_snapshot", lambda *a, **k: FakeAnalysis(labels, cells.crs))
    baseline = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
        path, delta_t=12, min_polygon_area_acres=area, engine="h5py")
    state["cells"] = present(cells, how)
    with pytest.MonkeyPatch.context() as patch:
        reference_spy = Spy(patch)
        reference = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
            path, delta_t=12, min_polygon_area_acres=area, engine="h5py")
    with pytest.MonkeyPatch.context() as patch:
        native_spy = Spy(patch)
        native = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
            path, delta_t=12, min_polygon_area_acres=area, engine="native", diagnostics=True)
    assert native.attrs["fluvial_engine"] == {"requested": "native", "used": "native", "fallback_reason": None}
    assert native.attrs["fluvial_native"]["geometry"]["assembly"] == "reference_dissolve"
    assert_identical(reference, baseline)  # the reference swap is presentation-invariant
    assert_same_swap_inputs(native_spy, reference_spy)
    assert_identical(native, reference)
    if area == 1.0:
        # 100 ft x 100 ft islands (0.23 acre) swap; 3200 ft^2 halves do not.
        assert parts(reference) < parts(HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
            path, delta_t=12, engine="h5py"))
        assert "area_acres" in reference.columns


def test_synthetic_native_rejects_mismatched_cell_sets(synthetic, monkeypatch):
    path, cells, state = synthetic
    labels = synthetic_reference_labels(path, monkeypatch, 12)
    monkeypatch.setattr(module, "_native_snapshot", lambda *a, **k: FakeAnalysis(labels.iloc[1:], cells.crs))
    with pytest.raises(module.FluvialNativeUnsupportedError, match="native cells differ"):
        HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
            path, delta_t=12, min_polygon_area_acres=1, engine="native")
    auto = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
        path, delta_t=12, min_polygon_area_acres=1, engine="auto")
    assert auto.attrs["fluvial_engine"]["used"] == "h5py"
    assert_identical(auto, HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
        path, delta_t=12, min_polygon_area_acres=1, engine="h5py"))


# --------------------------------------------------------------------------- #
# Real computed fixtures
# --------------------------------------------------------------------------- #
def _resolve(name):
    public = Path(os.environ.get("RAS_FLUVIAL_PUBLIC_FIXTURES", "missing")) / f"{name}.hdf"
    if public.is_file():
        return public
    for directory in filter(None, os.environ.get("RAS_FLUVIAL_FIXTURE_DIRS", "").split(os.pathsep)):
        hits = sorted(Path(directory).rglob(f"{name}.hdf"))
        if hits:
            return hits[0]
    pytest.skip(f"fixture {name}.hdf unavailable (RAS_FLUVIAL_PUBLIC_FIXTURES / RAS_FLUVIAL_FIXTURE_DIRS)")


def run_pair(path, **kwargs):
    with pytest.MonkeyPatch.context() as patch:
        reference_spy = Spy(patch)
        reference = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path, engine="h5py", **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        native_spy = Spy(patch)
        # Classification must come from the native kernel, not the Python growth loop.
        patch.setattr(module, "tqdm", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Python region growth ran under engine='native'")))
        native = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
            path, engine="native", diagnostics=True, **kwargs)
    assert native.attrs["fluvial_engine"]["used"] == "native"
    return reference, native, reference_spy, native_spy


REAL = [("BaldEagleDamBrk.p18", 1), ("BaldEagleDamBrk.p18", 12), ("AustinOyster.p01", 1),
        ("Homewood.p02", 12), ("DavisStormSystem.p02", 12), ("BaldEagleDamBrk.p06", 12)]


@pytest.mark.parametrize("area", [None, 0, 5, 200, 1e9])
@pytest.mark.parametrize("name,delta_t", REAL)
def test_real_native_swap_equals_reference(name, delta_t, area):
    path = _resolve(name)
    reference, native, reference_spy, native_spy = run_pair(
        path, delta_t=delta_t, min_polygon_area_acres=area)
    if area is None:
        # Unswapped native output keeps native ring assembly: topologically equal rows.
        assert list(native.columns) == list(reference.columns)
        assert list(zip(native.mesh_name, native.classification, native.cell_id)) == list(
            zip(reference.mesh_name, reference.classification, reference.cell_id))
        assert all(a.equals(b) for a, b in zip(native.geometry, reference.geometry))
        assert native_spy.swap == [] and native_spy.dissolve == []
        return
    assert native.attrs["fluvial_native"]["geometry"]["assembly"] == "reference_dissolve"
    assert_same_swap_inputs(native_spy, reference_spy)
    assert_identical(native, reference)


@pytest.mark.parametrize("how", PRESENTATIONS[1:])
def test_real_native_swap_equals_reference_for_any_presentation(how):
    path = _resolve("BaldEagleDamBrk.p18")
    cells = HdfMesh.get_mesh_cell_polygons(path)
    cells.attrs = {}
    baseline = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
        path, delta_t=12, min_polygon_area_acres=200, engine="h5py")
    frame = present(cells, how)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module.HdfMesh, "get_mesh_cell_polygons", staticmethod(lambda *a, **k: frame.copy()))
        reference, native, reference_spy, native_spy = run_pair(
            path, delta_t=12, min_polygon_area_acres=200)
    assert_identical(reference, baseline)
    assert_same_swap_inputs(native_spy, reference_spy)
    assert_identical(native, reference)


def test_real_swap_changes_the_regions():
    """Guard against a vacuous parity: 200 acres swaps parts on p18 at delta_t=12."""
    path = _resolve("BaldEagleDamBrk.p18")
    unswapped = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(path, delta_t=12, engine="h5py")
    swapped = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
        path, delta_t=12, min_polygon_area_acres=200, engine="h5py")
    assert parts(swapped) < parts(unswapped)
    assert swapped.geometry.area.sum() == pytest.approx(unswapped.geometry.area.sum(), rel=1e-12)
