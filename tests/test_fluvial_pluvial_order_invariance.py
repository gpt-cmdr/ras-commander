"""Order-invariance acceptance tests for ``HdfFluvialPluvial``.

``generate_fluvial_pluvial_polygons`` and ``calculate_fluvial_pluvial_boundary``
must depend only on the *topology and times* of the mesh cells, never on the
GeoDataFrame row order, the ring winding, or the ring start vertex of the cell
polygons they are given.  The polygon source is patched with the same cells in
different presentations, so a difference in the output is attributable to the
fluvial/pluvial algorithm alone.

Real fixtures are read-only and HEC-RAS is never run.  Set
``RAS_FLUVIAL_FIXTURE_DIRS`` (``os.pathsep``-separated directories) to make
``<fixture>.hdf`` files discoverable; missing fixtures skip their tests.
Native-backend assertions skip when ``ras_commander_fast_hdf`` is absent.
"""
from __future__ import annotations

import importlib.util
import inspect
import itertools
import os
from pathlib import Path
from unittest import mock

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import Polygon, box

from ras_commander.hdf import HdfFluvialPluvial, HdfMesh, HdfResultsMesh

# --------------------------------------------------------------------------- #
# Fixture discovery
# --------------------------------------------------------------------------- #
_CACHE = Path.home() / ".cache" / "ras-fast-hdf-validation-fixtures"
_KNOWN_PATHS = {
    "AustinOyster.p01": [
        "C:/GH/rc-wt-956/working/austin_bayou_firehose/working_model/Input/AustinOyster.p01.hdf",
    ],
    "BaldEagleDamBrk.p07": [
        _CACHE / "BaldEagleDamBrk.p07.hdf",
        "C:/Users/jacob/scratch/ras-native-successor/structures-fixtures/BaldEagleDamBrk.p07.hdf",
    ],
    "DavisStormSystem.p02": [
        "H:/CLB-Repos/ras-commander/working/c05_preparation_2026-08-22/real_fixtures/DavisStormSystem.p02.hdf",
    ],
    "Homewood.p02": ["D:/RAS_Agent_Scratch/Homewood_Demo/HECRAS/Homewood.p02.hdf"],
    "BaldEagleDamBrk.refpts.701.p03": [
        "C:/Users/jacob/scratch/ras-native-successor/refpoint-fixtures/BaldEagleDamBrk.refpts.701.p03.hdf",
    ],
}
RESULT_FIXTURES = list(_KNOWN_PATHS)  # plan HDFs that carry max-WSE results

PRESENTATIONS = ["rows_reversed", "rows_shuffled_seed0", "rows_shuffled_seed1", "rings_reversed"]
DELTA_TS = [1.0, 12.0]
TOLERANCE_HOURS = 1.0
AREA_TOL = 1e-2  # sq ft; observed dissolve float noise is <= ~1e-5


def _resolve(name: str) -> Path | None:
    for candidate in _KNOWN_PATHS.get(name, []):
        if Path(candidate).is_file():
            return Path(candidate)
    for directory in filter(None, os.environ.get("RAS_FLUVIAL_FIXTURE_DIRS", "").split(os.pathsep)):
        hits = sorted(Path(directory).rglob(f"{name}.hdf"))
        if hits:
            return hits[0]
    return None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def present(cells: gpd.GeoDataFrame, how: str) -> gpd.GeoDataFrame:
    """Same cells and vertices, different row order / winding / start vertex."""
    if how == "original":
        return cells.copy()
    if how == "rows_reversed":
        return cells.iloc[::-1].reset_index(drop=True)
    if how.startswith("rows_shuffled_seed"):
        seed = int(how.rsplit("seed", 1)[1])
        return cells.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    if how == "rings_reversed":
        out = cells.copy()
        out["geometry"] = shapely.reverse(cells.geometry.values)
        return out
    if how == "rings_rotated":
        geoms = []
        for g in cells.geometry.values:
            ring = np.asarray(g.exterior.coords)[:-1]
            ring = np.vstack([ring[1:], ring[:1], ring[1:2]])
            geoms.append(shapely.polygons(ring))
        out = cells.copy()
        out["geometry"] = geoms
        return out
    raise ValueError(how)


def run(func: str, cells: gpd.GeoDataFrame, max_ws: pd.DataFrame, hdf_path: Path, delta_t: float, **kwargs):
    """Run one public method with the polygon and results sources patched."""
    ws = max_ws.copy()
    # ``attrs["cell_polygon_diagnostics"]`` is deep-copied by every ``iterrows`` row in
    # ``_process_cell_adjacencies``; with thousands of ghost-cell diagnostics one adjacency
    # pass takes ~25 min instead of ~9 s.  It plays no role in classification, so drop it.
    cells = cells.copy()
    cells.attrs = {}
    with mock.patch.object(HdfMesh, "get_mesh_cell_polygons", staticmethod(lambda *_a, **_k: cells.copy())), \
         mock.patch.object(HdfResultsMesh, "get_mesh_max_ws", staticmethod(lambda *_a, **_k: ws.copy())):
        if func == "polygons":
            return HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
                hdf_path, delta_t=delta_t, temporal_tolerance_hours=TOLERANCE_HOURS, **kwargs)
        return HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf_path, delta_t=delta_t, **kwargs)


def regions(gdf: gpd.GeoDataFrame) -> dict:
    assert not gdf.empty, "fluvial/pluvial returned an empty frame (processing failure is swallowed)"
    assert not gdf.duplicated(["mesh_name", "classification"]).any()
    return {(r.mesh_name, r.classification): r.geometry for r in gdf.itertuples()}


def segment_set(gdf: gpd.GeoDataFrame, precision: int = 6) -> set:
    """Boundary lines as a set of undirected segments (agnostic to line merging)."""
    # A successful analysis with no qualifying edges (e.g. Homewood at dt=12h) returns an
    # empty frame that still has a geometry column and CRS; a swallowed processing
    # failure returns a bare GeoDataFrame() with neither.
    if gdf.empty:
        assert "geometry" in gdf.columns and gdf.crs is not None, "boundary frame is a processing-failure return"
    segs = set()
    for geom in gdf.geometry:
        for line in getattr(geom, "geoms", [geom]):
            xy = [tuple(round(c, precision) for c in p[:2]) for p in line.coords]
            segs.update(tuple(sorted((a, b))) for a, b in zip(xy[:-1], xy[1:]) if a != b)
    return segs


def assert_regions_equal(actual: dict, expected: dict, label: str) -> None:
    assert set(actual) == set(expected), f"{label}: region keys differ {sorted(actual)} vs {sorted(expected)}"
    deltas = {k: actual[k].symmetric_difference(expected[k]).area for k in expected}
    area_deltas = {k: actual[k].area - expected[k].area for k in expected}
    bad = {k: (d, area_deltas[k]) for k, d in deltas.items() if d > AREA_TOL}
    assert not bad, (
        f"{label}: classified regions are not topologically equal "
        f"(key: (symmetric-difference sq ft, class-area change sq ft)): {bad}"
    )


def assert_segments_equal(actual: set, expected: set, label: str) -> None:
    only_a, only_e = actual - expected, expected - actual
    assert not only_a and not only_e, (
        f"{label}: boundary segment sets differ "
        f"(+{len(only_a)} / -{len(only_e)} of {len(expected)} baseline segments)"
    )


# --------------------------------------------------------------------------- #
# Real-fixture invariance (cached per fixture so each configuration runs once)
# --------------------------------------------------------------------------- #
_MODELS: dict = {}
_RUNS: dict = {}


def _model(name: str):
    if name not in _MODELS:
        path = _resolve(name)
        if path is None:
            pytest.skip(f"fixture {name}.hdf not found (set RAS_FLUVIAL_FIXTURE_DIRS)")
        cells = HdfMesh.get_mesh_cell_polygons(path)
        max_ws = HdfResultsMesh.get_mesh_max_ws(path)
        assert len(cells) and len(max_ws)
        _MODELS[name] = (path, cells, max_ws)
    return _MODELS[name]


def _run(name: str, how: str, func: str, delta_t: float):
    key = (name, how, func, delta_t)
    if key not in _RUNS:
        path, cells, max_ws = _model(name)
        _RUNS[key] = run(func, present(cells, how), max_ws, path, delta_t)
    return _RUNS[key]


@pytest.mark.parametrize("delta_t", DELTA_TS, ids=lambda v: f"dt{v:g}h")
@pytest.mark.parametrize("how", PRESENTATIONS)
@pytest.mark.parametrize("name", RESULT_FIXTURES)
def test_generate_polygons_is_order_invariant(name, how, delta_t):
    baseline = regions(_run(name, "original", "polygons", delta_t))
    other = regions(_run(name, how, "polygons", delta_t))
    assert_regions_equal(other, baseline, f"{name} {how} dt={delta_t:g}h")


@pytest.mark.parametrize("delta_t", DELTA_TS, ids=lambda v: f"dt{v:g}h")
@pytest.mark.parametrize("how", PRESENTATIONS)
@pytest.mark.parametrize("name", RESULT_FIXTURES)
def test_calculate_boundary_is_order_invariant(name, how, delta_t):
    baseline = segment_set(_run(name, "original", "boundary", delta_t))
    other = segment_set(_run(name, how, "boundary", delta_t))
    assert_segments_equal(other, baseline, f"{name} {how} dt={delta_t:g}h")


@pytest.mark.parametrize("how", PRESENTATIONS)
def test_austin_oyster_headline_case_dt1(how):
    """Headline defect: ~55,000 sq ft moves between classes when only row order changes."""
    baseline = regions(_run("AustinOyster.p01", "original", "polygons", 1.0))
    other = regions(_run("AustinOyster.p01", how, "polygons", 1.0))
    moved = {k: round(other[k].area - baseline[k].area, 1) for k in baseline if k in other}
    assert_regions_equal(other, baseline, f"AustinOyster {how} dt=1h (class-area change {moved})")


@pytest.mark.parametrize("how", ["original", "rows_reversed", "rows_shuffled_seed0", "rings_reversed"])
@pytest.mark.parametrize("delta_t", DELTA_TS, ids=lambda v: f"dt{v:g}h")
def test_identical_cell_sets_and_coverage_across_presentations(how, delta_t):
    """The dissolve must cover exactly the same cells (union) whatever the presentation."""
    name = "DavisStormSystem.p02"
    path, cells, _ = _model(name)
    presented = present(cells, how)
    assert set(zip(presented.mesh_name, presented.cell_id)) == set(zip(cells.mesh_name, cells.cell_id))
    assert len(presented) == len(cells)
    out = regions(_run(name, how, "polygons", delta_t))
    base = regions(_run(name, "original", "polygons", delta_t))
    union = shapely.union_all(list(out.values()))
    union_base = shapely.union_all(list(base.values()))
    assert union.symmetric_difference(union_base).area <= AREA_TOL


# --------------------------------------------------------------------------- #
# Multi-mesh colliding ids vs per-mesh runs
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("how", ["original", "rows_reversed", "rows_shuffled_seed0", "rings_reversed"])
@pytest.mark.parametrize("delta_t", DELTA_TS, ids=lambda v: f"dt{v:g}h")
def test_real_multi_mesh_with_colliding_ids_equals_per_mesh_runs(how, delta_t):
    name = "DavisStormSystem.p02"
    path, cells, max_ws = _model(name)
    assert cells.cell_id.duplicated().any(), "fixture must have colliding native cell ids across meshes"
    # Per-mesh runs keep each mesh's rows in the combined frame's relative order, so only the
    # colliding-id / cross-mesh property is under test here (order invariance is tested above).
    presented = present(cells, how)
    combined = regions(run("polygons", presented, max_ws, path, delta_t))
    for mesh in sorted(cells.mesh_name.unique()):
        solo = regions(run("polygons", presented[presented.mesh_name == mesh],
                           max_ws[max_ws.mesh_name == mesh], path, delta_t))
        expected = {k: v for k, v in combined.items() if k[0] == mesh}
        assert_regions_equal(solo, expected, f"{name} mesh={mesh} {how} dt={delta_t:g}h per-mesh vs combined")


# --------------------------------------------------------------------------- #
# Synthetic controls (no fixtures needed)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def hdf_stub(tmp_path):
    path = tmp_path / "synthetic.p01.hdf"
    with h5py.File(path, "w"):
        pass
    return path


def _ws(rows):
    """rows: (mesh, cell, hours) -> max-WSE frame in the shape the algorithm consumes."""
    t0 = pd.Timestamp("2020-01-01")
    return pd.DataFrame({
        "mesh_name": [r[0] for r in rows],
        "cell_id": [r[1] for r in rows],
        "maximum_water_surface_time": [t0 + pd.Timedelta(hours=r[2]) for r in rows],
    })


def _cells(rows):
    """rows: (mesh, cell, Polygon) with CW rings like get_mesh_cell_polygons."""
    return gpd.GeoDataFrame(
        {"mesh_name": [r[0] for r in rows], "cell_id": [r[1] for r in rows]},
        geometry=[shapely.reverse(r[2]) if shapely.is_ccw(r[2].exterior) else r[2] for r in rows], crs=3857)


def _strip(mesh="M", hours=(0.0, 10.0, 20.0), ids=(0, 1, 2)):
    cells = _cells([(mesh, i, box(x, 0, x + 1, 1)) for x, i in zip(range(len(ids)), ids)])
    return cells, _ws([(mesh, i, h) for i, h in zip(ids, hours)])


def test_competing_pairs_cell_is_classified_independently_of_row_order_and_winding(hdf_stub):
    """B sits in two boundary pairs with opposite labels (A<B<C); the result may not depend on input order.

    The rule that resolves the conflict is deliberately not asserted here, only that it is
    deterministic and that the unambiguous end cells keep their labels.
    """
    cells, ws = _strip()
    seen = {}
    for perm in itertools.permutations(range(3)):
        for how in ("original", "rings_reversed", "rings_rotated"):
            ordered = present(cells.iloc[list(perm)].reset_index(drop=True), how)
            out = regions(run("polygons", ordered, ws, hdf_stub, 5.0))
            # classification of each cell = the region that contains its centroid
            labels = {int(i): next(k[1] for k, g in out.items() if g.buffer(1e-9).contains(
                cells.geometry[i].representative_point())) for i in range(3)}
            seen[(perm, how)] = labels
    distinct = {tuple(sorted(v.items())) for v in seen.values()}
    assert len(distinct) == 1, f"competing-pair cell label depends on input order: {sorted(distinct)}"
    labels = dict(next(iter(distinct)))
    assert labels[0] == "pluvial" and labels[2] == "fluvial", labels  # earlier = pluvial, later = fluvial


def test_competing_pairs_with_sorted_input_is_stable_for_the_boundary_lines(hdf_stub):
    cells, ws = _strip()
    baseline = segment_set(run("boundary", cells, ws, hdf_stub, 5.0))
    for perm in itertools.permutations(range(3)):
        for how in ("original", "rings_reversed", "rings_rotated"):
            ordered = present(cells.iloc[list(perm)].reset_index(drop=True), how)
            assert_segments_equal(segment_set(run("boundary", ordered, ws, hdf_stub, 5.0)), baseline,
                                  f"perm={perm} {how}")


def _curved_pair():
    """Two cells sharing a 4-segment (curved-perimeter style) face."""
    shared = [(1, 0), (1.2, 0.5), (1, 1), (1.2, 1.5), (1, 2)]
    a = Polygon([(0, 0), *shared, (0, 2)])
    b = Polygon([*shared, (2, 2), (2, 0)])
    assert a.is_valid and b.is_valid
    length = shapely.length(shapely.linestrings(shared))
    return a, b, shared, length


@pytest.mark.parametrize("how", ["original", "rings_reversed", "rings_rotated", "rows_reversed"])
def test_curved_perimeter_boundary_keeps_every_shared_segment(hdf_stub, how):
    a, b, shared, length = _curved_pair()
    cells = _cells([("M", 0, a), ("M", 1, b)])
    ws = _ws([("M", 0, 0.0), ("M", 1, 30.0)])
    out = run("boundary", present(cells, how), ws, hdf_stub, 12.0)
    segs = segment_set(out)
    expected = {tuple(sorted((tuple(p), tuple(q)))) for p, q in zip(shared[:-1], shared[1:])}
    assert segs == expected, f"{how}: kept {len(segs)} of {len(expected)} shared segments"
    assert sum(g.length for g in out.geometry) == pytest.approx(length)


def test_synthetic_multi_mesh_colliding_ids_equal_per_mesh_runs_for_any_mesh_order(hdf_stub):
    cells_a, ws_a = _strip("A", hours=(0.0, 10.0, 20.0))
    cells_b, ws_b = _strip("B", hours=(20.0, 10.0, 0.0))
    cells_b["geometry"] = cells_b.geometry.translate(0, 5)
    cells = pd.concat([cells_a, cells_b], ignore_index=True)
    ws = pd.concat([ws_a, ws_b], ignore_index=True)
    assert cells.cell_id.duplicated().any()
    for how in ("original", "rows_reversed", "rows_shuffled_seed0", "rows_shuffled_seed1", "rings_reversed"):
        presented = present(cells, how)  # per-mesh runs keep each mesh's relative row order
        out = regions(run("polygons", presented, ws, hdf_stub, 5.0))
        for mesh in ("A", "B"):
            solo = regions(run("polygons", presented[presented.mesh_name == mesh],
                               ws[ws.mesh_name == mesh], hdf_stub, 5.0))
            assert_regions_equal({k: v for k, v in out.items() if k[0] == mesh}, solo, f"mesh {mesh} {how}")


# --------------------------------------------------------------------------- #
# Native backend (skips cleanly when the extension or the backend switch is absent)
# --------------------------------------------------------------------------- #
def _native_unavailable_reason() -> str | None:
    if importlib.util.find_spec("ras_commander_fast_hdf") is None:
        return "ras_commander_fast_hdf is not installed"
    if "backend" not in inspect.signature(HdfMesh.get_mesh_cell_polygons).parameters:
        return "HdfMesh.get_mesh_cell_polygons has no backend= switch on this checkout"
    return None


@pytest.mark.parametrize("func", ["polygons", "boundary"])
@pytest.mark.parametrize("delta_t", DELTA_TS, ids=lambda v: f"dt{v:g}h")
@pytest.mark.parametrize("name", ["DavisStormSystem.p02", "BaldEagleDamBrk.p07"])
def test_native_backend_gives_same_fluvial_pluvial_as_python_backend(name, delta_t, func):
    reason = _native_unavailable_reason()
    if reason:
        pytest.skip(reason)
    path, _, max_ws = _model(name)
    py_cells = HdfMesh.get_mesh_cell_polygons(path, backend="python")
    native_cells = HdfMesh.get_mesh_cell_polygons(path, backend="native")
    a = run(func, py_cells, max_ws, path, delta_t)
    b = run(func, native_cells, max_ws, path, delta_t)
    if func == "polygons":
        assert_regions_equal(regions(b), regions(a), f"{name} native vs python dt={delta_t:g}h")
    else:
        assert_segments_equal(segment_set(b), segment_set(a), f"{name} native vs python dt={delta_t:g}h")
