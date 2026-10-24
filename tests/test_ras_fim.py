"""Tests for the optional ras2fim-2D FIM mapping API (ras_commander.fim.RasFim).

Unit tests use synthetic cells and a simulated ``ras2fim-batch`` process; they
do not need the engine. Real-fixture tests are opt-in:

- ``RAS_COMMANDER_FIM_FIXTURE``: folder with ``results.gpkg`` (ras2fim-2D
  layer ``02_cells_wsel_ar``), ``sample.p01.hdf`` and ``terrain.tif``.
- ``RAS_COMMANDER_FIM_REFERENCE_INPUTS``: folder of independently prepared
  ``ras2fim-step05-inputs/1`` profile folders for that fixture.
- ``RAS_COMMANDER_FIM_ENGINE``: built ``ras2fim-batch`` executable.

No test runs HEC-RAS.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import numpy as np
import pytest

gpd = pytest.importorskip("geopandas")
rasterio = pytest.importorskip("rasterio")
pytest.importorskip("scipy")
shapely = pytest.importorskip("shapely")

from affine import Affine  # noqa: E402
from geopandas.testing import assert_geodataframe_equal  # noqa: E402
from shapely.geometry import MultiPolygon, Point, Polygon, box  # noqa: E402

import ras_commander  # noqa: E402
from ras_commander.fim import (  # noqa: E402
    FimAoiError,
    FimEngineError,
    FimEngineNotFoundError,
    FimMappingError,
    FimUnsupportedError,
    RasFim,
)
from ras_commander.fim import _aoi, _engine, _prepare  # noqa: E402
from ras_commander.schemas import DATAFRAME_SCHEMAS  # noqa: E402

CRS_MODEL = "EPSG:32615"
CELL = 10.0


# --------------------------------------------------------------------------
# Synthetic data
# --------------------------------------------------------------------------

def _cells(rows=8, cols=10, x0=500000.0, y0=3300000.0):
    """Square cells; WSE profiles wet over different extents (NaN = dry)."""
    records = []
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            x, y = x0 + c * CELL, y0 + r * CELL
            wet_a = 2 <= c <= 7 and 1 <= r <= 6
            wet_b = 1 <= c <= 8 and 1 <= r <= 6
            records.append({
                "cell_idx": idx,
                "wsel_a": 101.0 + 0.01 * c if wet_a else np.nan,
                "wsel_b": 102.0 + 0.02 * r if wet_b else np.nan,
                "geometry": box(x, y, x + CELL, y + CELL),
            })
    # Reverse the row order: centres must still be taken in cell_idx order.
    return gpd.GeoDataFrame(records[::-1], geometry="geometry", crs=CRS_MODEL).reset_index(drop=True)


def _centers(cells):
    ordered = cells.sort_values("cell_idx")
    # Computational centres are offset from centroids, as in HEC-RAS.
    pts = [Point(g.centroid.x + 0.3, g.centroid.y - 0.2) for g in ordered.geometry]
    return gpd.GeoDataFrame({"cell_idx": ordered["cell_idx"].to_numpy(), "geometry": pts},
                            geometry="geometry", crs=CRS_MODEL)


def _terrain(path: Path, x0=499950.0, y0=3300150.0, res=2.0, width=110, height=100, value=100.0):
    data = np.full((height, width), value, dtype=np.float32)
    profile = dict(driver="GTiff", width=width, height=height, count=1, dtype="float32",
                   crs=CRS_MODEL, transform=Affine(res, 0, x0, 0, -res, y0), nodata=-9999.0)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
    return path


# --------------------------------------------------------------------------
# Literal upstream reference (ras2fim-2D Step 05, BSD 3-Clause, UT Austin)
# --------------------------------------------------------------------------

def _upstream_prepare(cells, centers, col, res):
    import pandas as pd
    from scipy.spatial import ConvexHull

    df_wsel = cells[["cell_idx", col]]
    pnt = pd.merge(centers, df_wsel, on="cell_idx", how="left").dropna(subset=[col]).copy()
    ar = cells.dropna(subset=[col]).copy()
    ar.loc[:, "val"] = 1
    dissolved = ar.dissolve(by="val")
    pts = pnt.geometry.apply(lambda p: (p.x, p.y)).tolist()
    hull = [pts[v] for v in ConvexHull(pts).vertices]
    created, wsel = [], []
    for _, cell in ar.iterrows():
        for x, y in cell.geometry.exterior.coords:
            if not Polygon(hull).contains(Point(x, y)):
                created.append(Point(x, y))
                wsel.append(cell[col])
    extra = gpd.GeoDataFrame(geometry=created)
    extra[col] = wsel
    merged = []
    for _, group in extra.groupby(extra.geometry.apply(lambda p: (round(p.x, 2), round(p.y, 2)))):
        if len(group) > 1:
            merged.append({"geometry": Point(group.geometry.x.mean(), group.geometry.y.mean()),
                           col: group[col].mean()})
        else:
            merged.append({"geometry": group.iloc[0].geometry, col: group.iloc[0][col]})
    extra = gpd.GeoDataFrame(merged)
    points = pd.concat([pnt[["geometry", col]].copy(), extra[["geometry", col]].copy()], axis=0)
    xmin, ymin, xmax, ymax = dissolved.total_bounds
    return (points.geometry.x.values, points.geometry.y.values, points[col].values,
            np.arange(xmin, xmax, res), np.arange(ymin, ymax, res))


# --------------------------------------------------------------------------
# Simulated engine
# --------------------------------------------------------------------------

class FakeEngine:
    """Stands in for subprocess.run of ras2fim-batch, following the request contract."""

    def __init__(self, terrain: Path, step05_exit=0, fail_profiles=(), bad_count=(), skip_units=()):
        self.terrain = terrain
        self.unit_edit = None  # callable(unit dict) to corrupt units in negative tests
        self.report_edit = None  # callable(report dict)
        self.step05_exit = step05_exit
        self.fail_profiles = set(fail_profiles)
        self.bad_count = set(bad_count)
        self.skip_units = set(skip_units)
        self.requests = []

    def __call__(self, args, what, timeout=None):
        command = args[1]
        if command == "method":
            # The real engine pretty-prints this record over several lines.
            return subprocess.CompletedProcess(args, 0, json.dumps({"method": {"name": "fake"}}, indent=2), "")
        if command == "terrain-info":
            with rasterio.open(args[2]) as src:
                info = {"width": src.width, "height": src.height,
                        "geo_transform": list(src.transform.to_gdal()), "epsg": src.crs.to_epsg(),
                        "crs_wkt_fnv1a64": "0"}
            return subprocess.CompletedProcess(args, 0, json.dumps(info) + "\n", "")
        assert command == "step05"
        request_path, out = Path(args[2]), Path(args[3])
        assert not out.exists()
        request = json.loads(request_path.read_text())
        self.requests.append(request)
        if self.step05_exit == 1:
            return subprocess.CompletedProcess(args, 1, "", "invalid request")
        for profile in request["profiles"]:
            inputs = request_path.parent / profile["inputs_dir"] / "inputs.json"
            assert inputs.is_file()
            dest = profile["dest_grid"]
            gt = dest["geotransform"]
            for aoi in profile["aois"]:
                col, row, w, h = aoi.get("window", [0, 0, dest["width"], dest["height"]])
                unit_dir = out / "units" / profile["id"] / aoi["id"]
                if profile["id"] in self.skip_units:
                    continue
                unit_dir.mkdir(parents=True)
                depth = np.full((h, w), 1.5, dtype="<f4")
                depth[0, :] = np.nan
                if "mask_u8" in aoi:
                    mask = np.fromfile(request_path.parent / aoi["mask_u8"], dtype=np.uint8).reshape(h, w)
                    depth[mask == 0] = np.nan
                wse = np.where(np.isfinite(depth), 101.5, np.nan).astype("<f4")
                depth.tofile(unit_dir / "depth.f32")
                wse.tofile(unit_dir / "wse.f32")
                count = int(np.isfinite(depth).sum()) + (1 if profile["id"] in self.bad_count else 0)
                status = "failed" if profile["id"] in self.fail_profiles else "complete"
                unit = {"schema": "ras2fim-step05-unit/1", "profile": profile["id"], "aoi": aoi["id"],
                        "status": status, "window": [col, row, w, h],
                        "window_geotransform": [gt[0] + col * gt[1], gt[1], 0.0, gt[3] + row * gt[5], 0.0, gt[5]],
                        "crs_epsg": request["nudge"]["dst_epsg"], "dtype": "<f4", "nodata": "nan",
                        "finite_counts": {"depth.f32": count, "wse.f32": int(np.isfinite(wse).sum())},
                        "polygon_mask_applied": "mask_u8" in aoi}
                if self.unit_edit is not None:
                    self.unit_edit(unit)
                (unit_dir / "unit.json").write_text(json.dumps(unit))
        code = self.step05_exit if self.step05_exit else (2 if self.fail_profiles else 0)
        report = {"schema": "ras2fim-step05-report/1", "status": "complete" if code == 0 else "failed",
                  "profiles": [{"id": prof["id"],
                                "status": "failed" if prof["id"] in self.fail_profiles else "complete",
                                "error_kind": "budget" if prof["id"] in self.fail_profiles else None}
                               for prof in request["profiles"]]}
        if self.report_edit is not None:
            self.report_edit(report)
        (out / "report.json").write_text(json.dumps(report))
        return subprocess.CompletedProcess(args, code, json.dumps({"status": "done"}) + "\n", "")


@pytest.fixture
def scene(tmp_path, monkeypatch):
    terrain = _terrain(tmp_path / "terrain.tif")
    engine = tmp_path / "bin" / "ras2fim-batch"
    engine.parent.mkdir()
    engine.write_text("not run")
    engine.chmod(engine.stat().st_mode | stat.S_IXUSR)
    fake = FakeEngine(terrain)
    monkeypatch.setattr(_engine, "run_engine", fake)
    cells = _cells()
    return {"tmp": tmp_path, "terrain": terrain, "engine": engine, "fake": fake,
            "cells": cells, "centers": _centers(cells)}


def _map(scene, out_name="out", **kwargs):
    kwargs.setdefault("centers", scene["centers"])
    kwargs.setdefault("output_resolution", 3.0)
    return RasFim.map_profiles(scene["cells"], scene["terrain"], scene["tmp"] / out_name,
                               engine_path=scene["engine"], **kwargs)


# --------------------------------------------------------------------------
# Public surface
# --------------------------------------------------------------------------

def test_lazy_exports_and_static_namespace():
    assert ras_commander.RasFim is RasFim
    for name in ("RasFim", "FimAoi", "FimMappingError", "FimEngineNotFoundError"):
        assert name in ras_commander.__all__
    for name in ("find_engine", "get_engine_info", "get_cells_from_results_gpkg", "get_cell_centers",
                 "get_cells_from_plan_hdf", "resolve_aoi", "prepare_profile", "map_profiles",
                 "map_ras2fim_results"):
        assert isinstance(RasFim.__dict__[name], staticmethod), name


def test_manifest_columns_match_schema():
    declared = [c["name"] for c in DATAFRAME_SCHEMAS["fim_product_manifest"]["columns"]]
    assert declared == list(RasFim.MANIFEST_COLUMNS)


# --------------------------------------------------------------------------
# Engine resolution
# --------------------------------------------------------------------------

def test_find_engine_explicit_missing_raises(tmp_path):
    with pytest.raises(FimEngineNotFoundError):
        RasFim.find_engine(tmp_path / "nope" / "ras2fim-batch")


def test_find_engine_env_and_path(tmp_path, monkeypatch):
    monkeypatch.setenv(_engine.ENGINE_ENV_VAR, str(tmp_path / "missing"))
    with pytest.raises(FimEngineNotFoundError, match=_engine.ENGINE_ENV_VAR):
        RasFim.find_engine()
    monkeypatch.delenv(_engine.ENGINE_ENV_VAR)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FimEngineNotFoundError, match="does not build or install"):
        RasFim.find_engine()


def test_map_profiles_without_engine_raises_before_writing(tmp_path, monkeypatch):
    monkeypatch.delenv(_engine.ENGINE_ENV_VAR, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    cells = _cells()
    terrain = _terrain(tmp_path / "terrain.tif")
    with pytest.raises(FimEngineNotFoundError):
        RasFim.map_profiles(cells, terrain, tmp_path / "out", centers=_centers(cells))
    assert not (tmp_path / "out").exists()


# --------------------------------------------------------------------------
# Areas of interest
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bbox", [(0, 0, 1), (1, 0, 0, 1), (0, 0, np.inf, 1), ("a", 0, 1, 1)])
def test_invalid_bbox(bbox):
    with pytest.raises(FimAoiError):
        RasFim.resolve_aoi(bbox=bbox, aoi_crs="EPSG:3857")


def test_aoi_argument_rules(tmp_path):
    assert RasFim.resolve_aoi() is None
    with pytest.raises(FimAoiError, match="mutually exclusive"):
        RasFim.resolve_aoi(bbox=(0, 0, 1, 1), polygon=box(0, 0, 1, 1), aoi_crs="EPSG:3857")
    with pytest.raises(FimAoiError, match="aoi_crs"):
        RasFim.resolve_aoi(polygon=box(0, 0, 1, 1))
    with pytest.raises(FimAoiError, match="invalid"):
        RasFim.resolve_aoi(polygon=Polygon([(0, 0), (1, 1), (1, 0), (0, 1)]), aoi_crs="EPSG:3857")
    with pytest.raises(FimAoiError, match="without polygon"):
        RasFim.resolve_aoi(bbox=(0, 0, 1, 1), polygon_layer="x", aoi_crs="EPSG:3857")
    path = tmp_path / "aoi.geojson"
    gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:4326").to_file(path)
    with pytest.raises(FimAoiError, match="conflicts"):
        RasFim.resolve_aoi(polygon=path, aoi_crs="EPSG:3857")
    aoi = RasFim.resolve_aoi(polygon=path)
    assert aoi.kind == "polygon" and aoi.crs.to_epsg() == 4326


def test_center_index_range_matches_brute_force():
    rng = np.random.default_rng(7)
    for _ in range(200):
        origin, step, count = rng.uniform(-50, 50), rng.choice([-1, 1]) * rng.uniform(0.5, 3), 40
        lo, hi = np.sort(rng.uniform(-150, 150, 2))
        expected = [i for i in range(count) if lo <= origin + (i + 0.5) * step < hi]
        start, stop = _aoi.center_index_range(lo, hi, origin, step, count)
        assert list(range(start, stop)) == expected


def test_polygon_window_masks_holes_and_parts():
    transform = Affine(1.0, 0, 0.0, 0, -1.0, 20.0)
    outer = Polygon([(1, 1), (9, 1), (9, 9), (1, 9)], holes=[[(4, 4), (6, 4), (6, 6), (4, 6)]])
    geom = MultiPolygon([outer, box(12, 12, 15, 15)])
    aoi = RasFim.resolve_aoi(polygon=geom, aoi_crs="EPSG:3857")
    win = _aoi.aoi_window(aoi, transform, 20, 20, "EPSG:3857")
    assert win.window == [1, 5, 14, 14]
    keep = win.mask

    def kept(x, y):
        return bool(keep[int(20 - y) - win.row_off, int(x) - win.col_off])

    assert kept(2.5, 2.5) and kept(13.5, 13.5)
    assert not kept(5.5, 5.5)  # hole
    assert not kept(10.5, 10.5)  # between parts


def test_bbox_window_in_grid_crs_has_no_mask_and_other_crs_is_masked():
    transform = Affine(100.0, 0, -10000.0, 0, -100.0, 10000.0)
    aoi = RasFim.resolve_aoi(bbox=(-5000, -5000, 5000, 5000), default_crs="EPSG:3857")
    win = _aoi.aoi_window(aoi, transform, 200, 200, "EPSG:3857")
    assert win.mask is None and win.window == [50, 50, 100, 100]
    geo = RasFim.resolve_aoi(bbox=(-0.04, -0.04, 0.04, 0.04), aoi_crs="EPSG:4326")
    win = _aoi.aoi_window(geo, transform, 200, 200, "EPSG:3857")
    assert win.mask is not None and win.mask.any()
    outside = RasFim.resolve_aoi(bbox=(50000, 50000, 60000, 60000), default_crs="EPSG:3857")
    assert _aoi.aoi_window(outside, transform, 200, 200, "EPSG:3857").is_empty


# --------------------------------------------------------------------------
# Preparation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("profile", ["wsel_a", "wsel_b"])
def test_prepare_profile_matches_upstream_and_leaves_inputs_unchanged(profile):
    cells, centers = _cells(), None
    centers = _centers(cells)
    cells_before, centers_before = cells.copy(), centers.copy()
    prep = RasFim.prepare_profile(cells, centers, profile, 2.0)
    x, y, z, xa, ya = _upstream_prepare(cells, centers, profile, 2.0)
    for got, want in ((prep.x, x), (prep.y, y), (prep.z, z), (prep.x_axis, xa), (prep.y_axis, ya)):
        assert got.dtype == want.dtype and np.array_equal(got, want)
    assert prep.wet_cell_count == int(cells[profile].notna().sum())
    assert prep.sample_count > prep.wet_cell_count
    assert_geodataframe_equal(cells, cells_before)
    assert_geodataframe_equal(centers, centers_before)


def test_prepare_profile_rejects_bad_inputs():
    cells, centers = _cells(), None
    centers = _centers(cells)
    dry = cells.copy()
    dry["wsel_a"] = np.nan
    with pytest.raises(FimUnsupportedError, match="no wet cells"):
        RasFim.prepare_profile(dry, centers, "wsel_a", 2.0)
    inf = cells.copy()
    inf.loc[inf["wsel_a"].notna().idxmax(), "wsel_a"] = np.inf
    with pytest.raises(FimUnsupportedError, match="infinite"):
        RasFim.prepare_profile(inf, centers, "wsel_a", 2.0)
    with pytest.raises(FimUnsupportedError, match="matching centres"):
        RasFim.prepare_profile(cells, centers.iloc[:-30], "wsel_a", 2.0)
    duplicate = gpd.GeoDataFrame(
        __import__("pandas").concat([cells, cells.iloc[:1]]), geometry="geometry", crs=cells.crs)
    with pytest.raises(ValueError, match="unique"):
        RasFim.prepare_profile(duplicate, centers, "wsel_a", 2.0)


def test_derive_grids_snaps_origin_and_rejects_terrain_overrun(tmp_path):
    cells = _cells()
    prep = RasFim.prepare_profile(cells, _centers(cells), "wsel_a", 2.0)
    with rasterio.open(_terrain(tmp_path / "t.tif")) as src:
        bounds = tuple(src.bounds)
    grids = _prepare.derive_grids(prep, bounds, "EPSG:3857", 3.0)
    assert grids.wet_mask.shape == prep.shape and grids.wet_mask.all()  # rectangular wet union
    assert grids.dest_transform.c % 3.0 == 0 and grids.dest_transform.f % 3.0 == 0
    small = (bounds[0], bounds[1], 500050.0, bounds[3])  # cuts through the wet cells
    with pytest.raises(FimUnsupportedError, match="beyond the terrain"):
        _prepare.derive_grids(prep, small, "EPSG:3857", 3.0)


def test_write_profile_inputs_layout_and_coplanar_rejection(tmp_path):
    cells = _cells()
    prep = RasFim.prepare_profile(cells, _centers(cells), "wsel_a", 2.0)
    with rasterio.open(_terrain(tmp_path / "t.tif")) as src:
        grids = _prepare.derive_grids(prep, tuple(src.bounds), "EPSG:3857", 3.0)
    record = _prepare.write_profile_inputs(tmp_path / "in", prep, grids)
    assert record["schema"] == "ras2fim-step05-inputs/1"
    for item in record["files"].values():
        size = (tmp_path / "in" / item["file"]).stat().st_size
        assert size == int(np.prod(item["shape"])) * np.dtype(item["dtype"]).itemsize
    assert record["files"]["samples"]["shape"] == [prep.sample_count, 3]
    flat = _prepare.FimPreparedProfile("p", np.array([0.0, 1.0, 2.0]), np.zeros(3), np.ones(3),
                                       prep.x_axis, prep.y_axis, prep.xmin, prep.ymin, 2.0,
                                       prep.wet_union, prep.crs, 3)
    with pytest.raises(Exception):
        _prepare.write_profile_inputs(tmp_path / "flat", flat, grids)


def _duplicate_sample(prep):
    """The prepared profile with its first sample repeated (a Qhull coplanar point)."""
    import dataclasses

    return dataclasses.replace(prep, x=np.append(prep.x, prep.x[0]), y=np.append(prep.y, prep.y[0]),
                               z=np.append(prep.z, prep.z[0]))


def test_write_profile_inputs_coplanar_policy(tmp_path):
    cells = _cells()
    prep = _duplicate_sample(RasFim.prepare_profile(cells, _centers(cells), "wsel_a", 2.0))
    with rasterio.open(_terrain(tmp_path / "t.tif")) as src:
        grids = _prepare.derive_grids(prep, tuple(src.bounds), "EPSG:3857", 3.0)
    with pytest.raises(FimUnsupportedError, match="1 coplanar"):
        _prepare.write_profile_inputs(tmp_path / "error", prep, grids)
    record = _prepare.write_profile_inputs(tmp_path / "ignore", prep, grids, coplanar="ignore")
    assert record["coplanar_samples"] == 1
    assert "coplanar_samples" not in json.loads((tmp_path / "ignore" / "inputs.json").read_text())
    simplices = np.fromfile(tmp_path / "ignore" / "simplices.u32", dtype="<u4")
    assert prep.sample_count - 1 not in set(simplices.tolist())  # the duplicate is not a vertex
    with pytest.raises(ValueError, match="coplanar must be"):
        _prepare.write_profile_inputs(tmp_path / "bad", prep, grids, coplanar="drop")


@pytest.mark.parametrize("origin", [(499950.7, 3300150.3), (499950.0, 3300150.0)])
def test_terrain_anchor_puts_axes_and_final_grid_on_the_terrain_lattice(tmp_path, origin):
    cells = _cells()
    centers = _centers(cells)
    plain = RasFim.prepare_profile(cells, centers, "wsel_a", 2.0)
    prep = RasFim.prepare_profile(cells, centers, "wsel_a", 2.0, lattice_origin=origin)
    assert prep.grid_anchor == "terrain" and plain.grid_anchor == "ras2fim"
    for got, want in ((prep.x, plain.x), (prep.y, plain.y), (prep.z, plain.z)):
        assert np.array_equal(got, want)  # samples never depend on the grid
    for low, union_low, o in ((prep.xmin, plain.xmin, origin[0]), (prep.ymin, plain.ymin, origin[1])):
        steps = (low - o) / 2.0
        assert abs(steps - round(steps)) < 1e-9 and low <= union_low < low + 2.0
    assert prep.x_axis[0] == prep.xmin and np.allclose(np.diff(prep.x_axis), 2.0)
    path = _terrain(tmp_path / "t.tif", x0=origin[0], y0=origin[1])
    with rasterio.open(path) as src:
        bounds = tuple(src.bounds)
    grids = _prepare.derive_grids(prep, bounds, CRS_MODEL, 2.0)
    t = grids.dest_transform
    assert (grids.dest_width, grids.dest_height) == (grids.cols, grids.rows)
    assert (t.a, t.e, t.c) == (2.0, -2.0, prep.xmin)
    for edge, o in ((t.c, origin[0]), (t.f, origin[1])):
        steps = (edge - o) / 2.0
        assert abs(steps - round(steps)) < 1e-9
    assert t.f == _prepare.snap_down(t.f, origin[1], 2.0)  # canonical lattice value
    with pytest.raises(FimUnsupportedError, match="output_resolution"):
        _prepare.derive_grids(prep, bounds, CRS_MODEL, 3.0)
    with pytest.raises(FimUnsupportedError, match="results CRS"):
        _prepare.derive_grids(prep, bounds, "EPSG:3857", 2.0)


@pytest.mark.parametrize("seed", range(6))
def test_terrain_anchor_keeps_the_extent_with_far_origin_and_non_binary_pixels(seed):
    # 0.3 units is not a binary fraction and the origin is tens of km away: a re-snapped
    # top edge used to land one pixel low and drop the northernmost wet row.
    rng = np.random.default_rng(seed)
    origin, res = (499950.7, 3300150.3), 0.3
    for _ in range(10):
        cells = _cells(x0=500000.0 + rng.uniform(0, 50), y0=3275171.79 + rng.uniform(0, 50))
        prep = RasFim.prepare_profile(cells, _centers(cells), "wsel_a", res, lattice_origin=origin)
        rows, cols = prep.shape
        grids = _prepare.derive_grids(prep, (0.0, 0.0, 1e7, 1e7), CRS_MODEL, res)
        t = grids.dest_transform
        assert (grids.dest_width, grids.dest_height) == (cols, rows)
        assert abs(t.c - prep.xmin) < 1e-6 * res
        assert abs(t.f - (prep.ymin + rows * res)) < 1e-6 * res  # same extent as raster 01
        kx, ky = prep.lattice_index
        assert t.c == origin[0] + kx * res and t.f == origin[1] + (ky + rows) * res
        union = cells.dropna(subset=["wsel_a"]).union_all().bounds
        assert prep.xmin <= union[0] + 1e-6 and t.f >= union[3] - 1e-6  # nothing cut off


def test_terrain_anchor_clamps_a_wet_union_that_pokes_outside_the_terrain(tmp_path):
    cells = _cells()  # wet union xmin 500020
    path = _terrain(tmp_path / "t.tif", x0=500020.3)  # left edge 0.3 inside the union
    with rasterio.open(path) as src:
        bounds, t = tuple(src.bounds), src.transform
    with pytest.raises(FimUnsupportedError, match="beyond the terrain"):
        unclamped = RasFim.prepare_profile(cells, _centers(cells), "wsel_a", 2.0,
                                           lattice_origin=(t.c, t.f))
        _prepare.derive_grids(unclamped, bounds, CRS_MODEL, 2.0)
    prep = _prepare.prepare_profile(cells, _centers(cells), "wsel_a", 2.0,
                                    lattice_origin=(t.c, t.f), lattice_bounds=bounds)
    assert prep.xmin == 500020.3 and prep.x_axis[0] == 500020.3
    grids = _prepare.derive_grids(prep, bounds, CRS_MODEL, 2.0)
    assert grids.dest_transform.c == 500020.3


def test_same_crs_compares_epsg_codes_across_wkt_spellings():
    from pyproj import CRS

    assert _prepare.same_crs(CRS.from_epsg(32615).to_wkt("WKT1_ESRI"), "EPSG:32615")
    assert not _prepare.same_crs("EPSG:32615", "EPSG:32616")


def test_snap_down_is_canonical_on_and_off_the_lattice():
    assert _prepare.snap_down(10.0, 0.5, 2.0) == 8.5
    assert _prepare.snap_down(8.5 + 1e-12, 0.5, 2.0) == 8.5  # within tolerance: on the lattice
    assert _prepare.snap_down(-3.0, 0.5, 2.0) == -3.5


# --------------------------------------------------------------------------
# Batch mapping with a simulated engine
# --------------------------------------------------------------------------

def test_map_profiles_full_grid(scene):
    terrain_before = scene["terrain"].read_bytes()
    manifest = _map(scene, profiles_per_request=1, max_inflight_profiles=2, threads=3)
    assert list(manifest.columns) == list(RasFim.MANIFEST_COLUMNS)
    assert manifest["profile"].tolist() == ["wsel_a", "wsel_b"]
    assert (manifest["status"] == "complete").all()
    assert len(scene["fake"].requests) == 2
    request = scene["fake"].requests[0]
    assert request["budgets"]["max_inflight_profiles"] == 2 and request["budgets"]["threads"] == 3
    assert request["profiles"][0]["aois"] == [{"id": "full"}]
    for row in manifest.itertuples():
        with rasterio.open(row.depth_tif) as src:
            assert src.dtypes[0] == "float32" and np.isnan(src.nodata)
            assert src.crs.to_epsg() == 3857 and (src.width, src.height) == (row.width, row.height)
            assert int(np.isfinite(src.read(1)).sum()) == row.depth_finite_pixels
        assert Path(row.wse_tif).is_file()
        assert len(gpd.read_file(row.floodplain_gpkg)) == 1
    document = json.loads((scene["tmp"] / "out" / "fim_manifest.json").read_text())
    assert document["schema"] == "ras-commander-fim-manifest/1"
    assert document["options"]["max_inflight_profiles"] == 2
    assert [p["profile"] for p in document["profiles"]] == ["wsel_a", "wsel_b"]
    assert scene["terrain"].read_bytes() == terrain_before
    assert not list((scene["tmp"] / "out").glob(".fim_work*"))


def test_map_profiles_polygon_aoi_crops_and_masks(scene):
    full = _map(scene, out_name="full", profiles=["wsel_a"])
    with rasterio.open(full.loc[0, "depth_tif"]) as src:
        bounds = src.bounds
    cx, cy = (bounds.left + bounds.right) / 2, (bounds.bottom + bounds.top) / 2
    ring = Polygon([(cx - 20, cy - 20), (cx + 20, cy - 20), (cx + 20, cy + 20), (cx - 20, cy + 20)],
                   holes=[[(cx - 5, cy - 5), (cx + 5, cy - 5), (cx + 5, cy + 5), (cx - 5, cy + 5)]])
    manifest = _map(scene, out_name="aoi", profiles=["wsel_a"], polygon=ring, aoi_crs="EPSG:3857")
    row = manifest.iloc[0]
    assert row.status == "complete" and row.width < full.loc[0, "width"]
    aoi = scene["fake"].requests[-1]["profiles"][0]["aois"][0]
    assert aoi["id"] == "aoi" and "mask_u8" in aoi and aoi["window"][2] == row.width
    with rasterio.open(row.depth_tif) as src:
        depth = src.read(1)
    centre = depth[depth.shape[0] // 2, depth.shape[1] // 2]
    assert np.isnan(centre)  # inside the hole


def test_map_profiles_empty_aoi(scene):
    manifest = _map(scene, bbox=(0, 0, 10, 10))
    assert (manifest["status"] == "empty_aoi").all()
    assert scene["fake"].requests == []


def test_engine_invalid_request_raises_and_writes_manifest(scene):
    scene["fake"].step05_exit = 1
    with pytest.raises(FimEngineError, match="exit 1"):
        _map(scene)
    document = json.loads((scene["tmp"] / "out" / "fim_manifest.json").read_text())
    assert {p["status"] for p in document["profiles"]} == {"failed"}


def test_failed_and_inconsistent_units(scene):
    scene["fake"].fail_profiles = {"wsel_a"}
    scene["fake"].bad_count = {"wsel_b"}
    with pytest.raises(FimMappingError) as info:
        _map(scene)
    manifest = info.value.manifest
    assert manifest.set_index("profile")["status"].to_dict() == {"wsel_a": "failed", "wsel_b": "failed"}
    assert "finite" in manifest.set_index("profile").loc["wsel_b", "error"]
    returned = _map(scene, out_name="out2", raise_on_failure=False)
    assert (returned["status"] == "failed").all()


@pytest.mark.parametrize("edit, message", [
    (lambda u: u.update(schema="other/1"), "schema"),
    (lambda u: u.update(profile="wsel_x"), "identifies"),
    (lambda u: u.update(window=[0, 0, 1.0, 2]), "non-negative integers"),
    (lambda u: u["window_geotransform"].__setitem__(0, float("nan")), "six finite"),
    (lambda u: u["finite_counts"].update({"wse.f32": True}), "finite values"),
])
def test_unit_reader_rejects_inconsistent_units(scene, edit, message):
    scene["fake"].unit_edit = edit
    scene["fake"].step05_exit = 2  # the engine itself would not report complete
    scene["fake"].report_edit = lambda r: r["profiles"][0].update(status="failed")
    with pytest.raises(FimMappingError) as info:
        _map(scene)
    errors = info.value.manifest.set_index("profile")["error"]
    assert message in errors["wsel_b"]
    assert "engine report status" in errors["wsel_a"]


@pytest.mark.parametrize("edit, message", [
    (lambda r: r.update(schema="x"), "schema"),
    (lambda r: r.update(status="failed"), "disagrees with exit"),
    (lambda r: r["profiles"].reverse(), "differ from the request"),
])
def test_report_is_required_and_authoritative(scene, edit, message):
    scene["fake"].report_edit = edit
    with pytest.raises(FimEngineError, match=message):
        _map(scene)


def test_exit_zero_with_missing_unit_raises(scene):
    scene["fake"].skip_units = {"wsel_b"}
    with pytest.raises(FimEngineError, match="not complete"):
        _map(scene)


def test_output_folder_must_be_empty_and_options_validated(scene):
    out = scene["tmp"] / "out"
    out.mkdir()
    (out / "keep.txt").write_text("x")
    with pytest.raises(FileExistsError):
        _map(scene)
    assert (out / "keep.txt").read_text() == "x"
    for kwargs in ({"max_inflight_profiles": 0}, {"profiles_per_request": 0}, {"nudge_method": "x"},
                   {"threads": True}, {"profiles": ["missing"]}):
        with pytest.raises((ValueError, KeyError)):
            _map(scene, out_name="other", **kwargs)
    with pytest.raises(ValueError, match="exactly one"):
        RasFim.map_profiles(scene["cells"], scene["terrain"], scene["tmp"] / "x",
                            engine_path=scene["engine"])


def test_map_profiles_terrain_anchor_requests_the_terrain_lattice(scene):
    scene["terrain"] = _terrain(scene["tmp"] / "offset.tif", x0=499950.7, y0=3300150.3)
    manifest = _map(scene, output_crs=CRS_MODEL, output_resolution=2.0, grid_anchor="terrain")
    assert (manifest["status"] == "complete").all()
    for request in scene["fake"].requests:
        gt = request["profiles"][0]["dest_grid"]["geotransform"]
        assert gt[1] == 2.0 and gt[5] == -2.0
        for edge, origin in ((gt[0], 499950.7), (gt[3], 3300150.3)):
            steps = (edge - origin) / 2.0
            assert abs(steps - round(steps)) < 1e-9
    document = json.loads((scene["tmp"] / "out" / "fim_manifest.json").read_text())
    assert document["options"]["grid_anchor"] == "terrain" and document["options"]["coplanar"] == "error"
    assert document["coplanar_samples"] == {}
    for kwargs, message in (({"output_resolution": 3.0}, "terrain pixel size"),
                            ({"output_resolution": 2.0, "output_crs": "EPSG:3857"}, "results CRS")):
        kwargs.setdefault("output_crs", CRS_MODEL)
        with pytest.raises(FimUnsupportedError, match=message):
            _map(scene, out_name="x", grid_anchor="terrain", **kwargs)
    for kwargs in ({"grid_anchor": "lattice"}, {"coplanar": "drop"}):
        with pytest.raises(ValueError):
            _map(scene, out_name="y", **kwargs)


def test_map_profiles_coplanar_ignore_maps_and_records_the_count(scene, monkeypatch):
    original = _prepare.prepare_profile

    def with_duplicate(*args, **kwargs):
        prep = original(*args, **kwargs)
        return _duplicate_sample(prep) if prep.profile == "wsel_a" else prep

    monkeypatch.setattr(_prepare, "prepare_profile", with_duplicate)
    rejected = _map(scene, raise_on_failure=False)
    assert rejected.set_index("profile")["status"].to_dict() == {"wsel_a": "failed", "wsel_b": "complete"}
    assert "coplanar" in rejected.set_index("profile").loc["wsel_a", "error"]
    manifest = _map(scene, out_name="ignored", coplanar="ignore")
    assert (manifest["status"] == "complete").all()
    document = json.loads((scene["tmp"] / "ignored" / "fim_manifest.json").read_text())
    assert document["coplanar_samples"] == {"wsel_a": 1} and document["options"]["coplanar"] == "ignore"


def test_crs_mismatch_is_unsupported(scene):
    cells = scene["cells"].to_crs("EPSG:32616")
    with pytest.raises(FimUnsupportedError):
        RasFim.map_profiles(cells, scene["terrain"], scene["tmp"] / "out",
                            centers=scene["centers"].to_crs("EPSG:32616"), engine_path=scene["engine"])


# --------------------------------------------------------------------------
# Opt-in real fixture qualification
# --------------------------------------------------------------------------

FIXTURE = os.environ.get("RAS_COMMANDER_FIM_FIXTURE")
REFERENCE = os.environ.get("RAS_COMMANDER_FIM_REFERENCE_INPUTS")
ENGINE = os.environ.get(_engine.ENGINE_ENV_VAR)


@pytest.mark.integration
@pytest.mark.skipif(not (FIXTURE and REFERENCE), reason="set RAS_COMMANDER_FIM_FIXTURE and _REFERENCE_INPUTS")
@pytest.mark.parametrize("profile", sorted(p.name for p in Path(REFERENCE).iterdir() if (p / "inputs.json").is_file())
                         if REFERENCE and Path(REFERENCE).is_dir() else ["wsel_max_1"])
def test_fixture_preparation_matches_reference_inputs(profile, tmp_path):
    fixture, reference = Path(FIXTURE), Path(REFERENCE) / profile
    cells = RasFim.get_cells_from_results_gpkg(fixture / "results.gpkg")
    centers = RasFim.get_cell_centers(fixture / "sample.p01.hdf", cells["cell_idx"])
    with rasterio.open(fixture / "terrain.tif") as src:
        res, bounds = src.res[0], tuple(src.bounds)
    prep = RasFim.prepare_profile(cells, centers, profile, res)
    grids = _prepare.derive_grids(prep, bounds, "EPSG:3857", 3.0)
    _prepare.write_profile_inputs(tmp_path / profile, prep, grids)
    for name in ("samples.f64", "x_axis.f64", "y_axis.f64", "wet_mask.u8", "simplices.u32"):
        assert (tmp_path / profile / name).read_bytes() == (reference / name).read_bytes(), name


@pytest.mark.integration
@pytest.mark.skipif(not ENGINE, reason="set RAS_COMMANDER_FIM_ENGINE")
def test_engine_terrain_anchor_takes_the_terrain_pixel_each_output_pixel_lies_on(tmp_path):
    # A terrain with a distinct value per pixel, an origin that is not a multiple of the pixel
    # size, and a non-binary pixel size: every wet output pixel must satisfy WSE - depth equal
    # to the terrain pixel at the same lattice position.
    res, x0, y0 = 0.3, 499950.7, 3300150.3
    width, height = 800, 700
    data = (100.0 + np.add.outer(np.arange(height) * 0.001, np.arange(width) * 0.0007)).astype("float32")
    path = tmp_path / "terrain.tif"
    profile = dict(driver="GTiff", width=width, height=height, count=1, dtype="float32",
                   crs=CRS_MODEL, transform=Affine(res, 0, x0, 0, -res, y0), nodata=-9999.0)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
    cells = _cells(x0=500000.0, y0=3300000.0)
    manifest = RasFim.map_profiles(cells, path, tmp_path / "out", centers=_centers(cells),
                                   profiles=["wsel_a"], output_crs=CRS_MODEL, output_resolution=res,
                                   grid_anchor="terrain", engine_path=ENGINE, threads=1,
                                   write_floodplain=False)
    row = manifest.iloc[0]
    assert row.status == "complete"
    with rasterio.open(row.depth_tif) as d, rasterio.open(row.wse_tif) as w:
        depth, wse, t = d.read(1).astype("f8"), w.read(1).astype("f8"), d.transform
    col0, row0 = (t.c - x0) / res, (y0 - t.f) / res
    assert abs(col0 - round(col0)) < 1e-6 and abs(row0 - round(row0)) < 1e-6
    ground = data[round(row0):round(row0) + depth.shape[0], round(col0):round(col0) + depth.shape[1]]
    wet = np.isfinite(depth)
    assert wet.sum() > 1000
    np.testing.assert_allclose((wse - depth)[wet], ground[wet].astype("f8"), atol=1e-3)


@pytest.mark.skipif(not (FIXTURE and ENGINE), reason="set RAS_COMMANDER_FIM_FIXTURE and RAS_COMMANDER_FIM_ENGINE")
def test_fixture_engine_full_bbox_and_polygon_equal_full_crop(tmp_path):
    fixture = Path(FIXTURE)
    inputs = [fixture / "results.gpkg", fixture / "sample.p01.hdf", fixture / "terrain.tif"]
    before = [p.read_bytes() for p in inputs]

    def run(name, **kwargs):
        frame = RasFim.map_ras2fim_results(*inputs, tmp_path / name, profiles=["wsel_max_10"], **kwargs)
        row = frame.iloc[0]
        assert row.status == "complete", row.error
        return row

    def read(row):
        with rasterio.open(row.depth_tif) as d, rasterio.open(row.wse_tif) as w:
            return d.read(1), w.read(1)

    full = run("full")
    t = Affine(*full["transform"])
    whole = read(full)
    assert full.flooded_pixels > 0 and Path(full.floodplain_gpkg).is_file()

    # Bounding box around the grid centre, in the output CRS.
    cx, cy = t.c + t.a * full.width / 2, t.f + t.e * full.height / 2
    half = 150 * t.a
    bbox = run("bbox", bbox=(cx - half, cy - half, cx + half, cy + half))
    part = read(bbox)
    for a, b in zip(whole, part):
        crop = a[bbox.row_off:bbox.row_off + bbox.height, bbox.col_off:bbox.col_off + bbox.width]
        assert crop.tobytes() == b.tobytes()

    # Two-part polygon with a hole, supplied as a file in the model CRS.
    outer = Polygon([(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)],
                    holes=[[(cx - 40 * t.a, cy - 40 * t.a), (cx + 40 * t.a, cy - 40 * t.a),
                            (cx + 40 * t.a, cy + 40 * t.a), (cx - 40 * t.a, cy + 40 * t.a)]])
    second = box(cx + half + 20 * t.a, cy - 30 * t.a, cx + half + 80 * t.a, cy + 30 * t.a)
    path = tmp_path / "aoi.gpkg"
    gpd.GeoDataFrame(geometry=[MultiPolygon([outer, second])], crs="EPSG:3857").to_crs(
        RasFim.get_cells_from_results_gpkg(inputs[0]).crs).to_file(path)
    poly = run("polygon", polygon=path)
    aoi = RasFim.resolve_aoi(polygon=path)
    window = _aoi.aoi_window(aoi, t, int(full.width), int(full.height), "EPSG:3857")
    assert window.window == [poly.col_off, poly.row_off, poly.width, poly.height]
    assert window.mask is not None and not window.mask.all()
    for a, b in zip(whole, read(poly)):
        crop = a[poly.row_off:poly.row_off + poly.height, poly.col_off:poly.col_off + poly.width].copy()
        crop[~window.mask] = np.nan
        assert crop.tobytes() == b.tobytes()

    assert [p.read_bytes() for p in inputs] == before


@pytest.mark.integration
@pytest.mark.skipif(not FIXTURE, reason="set RAS_COMMANDER_FIM_FIXTURE")
def test_fixture_plan_hdf_cells_and_centers():
    hdf = Path(FIXTURE) / "sample.p01.hdf"
    cells = RasFim.get_cells_from_plan_hdf(hdf)
    assert list(cells.columns) == ["cell_idx", "wsel_max", "geometry"]
    assert cells.crs is not None and cells["cell_idx"].is_unique
    wet = cells["wsel_max"].notna()
    assert 0 < wet.sum() < len(cells)
    centers = RasFim.get_cell_centers(hdf, cells["cell_idx"])
    assert centers["cell_idx"].tolist() == sorted(cells["cell_idx"])
    with pytest.raises(FimUnsupportedError, match="not in mesh"):
        RasFim.get_cell_centers(hdf, [10**9])
    with pytest.raises(FimUnsupportedError, match="not in"):
        RasFim.get_cell_centers(hdf, mesh_name="No Such Area")


@pytest.mark.parametrize("defect", ["duplicate", "float_id", "polygon"])
def test_prepare_rejects_invalid_centers(defect):
    cells = _cells()
    centers = _centers(cells)
    if defect == "duplicate":
        centers.loc[1, "cell_idx"] = centers.loc[0, "cell_idx"]
    elif defect == "float_id":
        centers["cell_idx"] = centers["cell_idx"].astype(float)
    else:
        centers.loc[0, "geometry"] = cells.geometry.iloc[0]
    with pytest.raises((ValueError, TypeError, FimUnsupportedError)):
        RasFim.prepare_profile(cells, centers, "wsel_a", 2.0)


def test_prepare_sorts_centers():
    cells = _cells()
    centers = _centers(cells)
    expected = RasFim.prepare_profile(cells, centers, "wsel_a", 2.0)
    actual = RasFim.prepare_profile(cells, centers.iloc[::-1], "wsel_a", 2.0)
    for name in ("x", "y", "z"):
        np.testing.assert_array_equal(getattr(actual, name), getattr(expected, name))


@pytest.mark.parametrize("names", [["wsel_a", "wsel_A"], ["wsel bad"]])
def test_profile_names_rejected_before_mapping(names):
    from ras_commander.fim.RasFim import _validate_cells
    cells = _cells()
    for name in names:
        cells[name] = cells["wsel_a"]
    with pytest.raises((ValueError, FimUnsupportedError)):
        _validate_cells(cells, names, "wsel")
