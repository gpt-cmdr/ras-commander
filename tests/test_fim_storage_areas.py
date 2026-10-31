"""Storage-area level pools (``storage-area-level-pool/1``) for Rust FIM mapping.

Unit tests use synthetic plan HDFs and a simulated engine method record.
Real-model qualification is opt-in: set RAS_COMMANDER_FIM_STORAGE_CASE to a
JSON document with ``hdf``, ``terrain``, optional ``engine`` and ``cases``, a
list of ``{"render_mode", "profile" ("Max" or index), "depth", "wse"}``
native HEC-RAS stored maps (same lattice as ``terrain``). No HEC-RAS
execution occurs here.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
rasterio = pytest.importorskip("rasterio")
shapely = pytest.importorskip("shapely")

from ras_commander.fim import RasFim, _engine, _horizontal, _storage_areas  # noqa: E402
from ras_commander.fim.errors import FimEngineError, FimUnsupportedError  # noqa: E402

BASE = "Results/Unsteady/Output/Output Blocks/Base Output"


def _plan(path, areas, series=None, maximum=None, swap_columns=False, names=None):
    """Synthetic plan HDF with storage areas ``[(name, exterior, holes), ...]``."""
    names = names or [a[0] for a in areas]
    points, info, parts = [], [], []
    for _, exterior, holes in areas:
        start, part_start = len(points), len(parts)
        for ring in [exterior, *holes]:
            parts.append((len(points) - start, len(ring)))
            points.extend(ring)
        info.append((start, len(points) - start, part_start, len(parts) - part_start))
    with h5py.File(path, "w") as f:
        g = f.create_group("Geometry/Storage Areas")
        dtype = np.dtype([("Name", "S16"), ("Mode", "S16"), ("Min Elev", "<f4")])
        g.create_dataset("Attributes", data=np.array(
            [(n.encode(), b"", 0.0) for n in names], dtype=dtype))
        g.create_dataset("Polygon Info", data=np.array(info, dtype=np.int32))
        g.create_dataset("Polygon Parts", data=np.array(parts, dtype=np.int32))
        g.create_dataset("Polygon Points", data=np.array(points, dtype=np.float64))
        if series is not None:
            series = np.asarray(series, dtype=np.float32)
            ts = f.create_group(f"{BASE}/Unsteady Time Series/Storage Areas")
            stored = series[:, ::-1] if swap_columns else series
            ts.create_dataset("Water Surface", data=stored)
            for column, name in enumerate(names):
                variables = np.zeros((len(series), 6), dtype=np.float32)
                variables[:, 0] = series[:, column]
                d = ts.create_group(name).create_dataset("Storage Area Variables", data=variables)
                d.attrs["Variable_Unit"] = np.array(
                    [[b"Stage", b"ft"]] + [[b"Other", b"x"]] * 5, dtype="S32")
        if maximum is not None:
            f.create_dataset(f"{BASE}/Summary Output/Storage Areas/Maximum Water Surface",
                             data=np.array([maximum, [0.0] * len(maximum)], dtype=np.float32))
    return path


def _square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def test_read_polygons_with_holes_in_geometry_order(tmp_path):
    hdf = _plan(tmp_path / "p.hdf", [
        ("Pool", _square(0, 0, 10, 10), [_square(4, 4, 6, 6)]),
        ("Pond", _square(20, 0, 30, 10), []),
    ])
    areas = _storage_areas.read(hdf)
    assert areas.names == ("Pool", "Pond") and len(areas) == 2
    assert areas.polygons[0].area == 96.0 and len(areas.polygons[0].interiors) == 1
    assert areas.polygons[1].bounds == (20.0, 0.0, 30.0, 10.0)
    assert not areas.polygons.flags.writeable


def test_read_without_storage_areas_is_none(tmp_path):
    path = tmp_path / "p.hdf"
    with h5py.File(path, "w") as f:
        f.create_group("Geometry")
    assert _storage_areas.read(path) is None


@pytest.mark.parametrize("areas, names, message", [
    ([("A", [(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)], [])], None, "not a valid polygon"),
    ([("A", _square(0, 0, 1, 1), []), ("A", _square(2, 0, 3, 1), [])], None, "unique"),
    ([("A", _square(0, 0, 1, 1), [])], [" "], "unique and non-empty"),
])
def test_unprovable_polygons_are_refused(tmp_path, areas, names, message):
    hdf = _plan(tmp_path / "p.hdf", areas, names=names)
    with pytest.raises(FimUnsupportedError, match=message):
        _storage_areas.read(hdf)


def test_values_prove_column_order_and_select_max_or_timestep(tmp_path):
    series = [[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]]
    areas = [("A", _square(0, 0, 1, 1), []), ("B", _square(2, 0, 3, 1), [])]
    hdf = _plan(tmp_path / "p.hdf", areas, series=series, maximum=[3.5, 30.5])
    sa = _storage_areas.read(hdf)
    values = _storage_areas.profile_values(hdf, sa, {"Max": "Max", "t1": 1})
    assert values["Max"].tolist() == [3.5, 30.5] and values["Max"].dtype == np.dtype("<f4")
    assert values["t1"].tolist() == [2.0, 20.0]
    assert _storage_areas.time_series(hdf, sa, 3).tolist() == series
    with pytest.raises(FimUnsupportedError, match="not the 4 output times"):
        _storage_areas.time_series(hdf, sa, 4)
    with pytest.raises(ValueError, match="outside"):
        _storage_areas.profile_values(hdf, sa, {"t9": 9})
    swapped = _plan(tmp_path / "s.hdf", areas, series=series, maximum=[1, 2], swap_columns=True)
    with pytest.raises(FimUnsupportedError, match="column order"):
        _storage_areas.profile_values(swapped, _storage_areas.read(swapped), {"Max": "Max"})


def test_nonfinite_or_missing_values_are_refused(tmp_path):
    areas = [("A", _square(0, 0, 1, 1), [])]
    hdf = _plan(tmp_path / "p.hdf", areas, series=[[1.0]], maximum=[np.nan])
    sa = _storage_areas.read(hdf)
    with pytest.raises(FimUnsupportedError, match="non-finite"):
        _storage_areas.profile_values(hdf, sa, {"Max": "Max"})
    bare = _plan(tmp_path / "b.hdf", areas)
    with pytest.raises(FimUnsupportedError, match="Water Surface series"):
        _storage_areas.profile_values(bare, sa, {"Max": "Max"})


def _terrain(path, width=200, height=100):
    from rasterio.transform import from_origin

    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32",
        crs="EPSG:26915", transform=from_origin(0, 100, 1.0, 1.0), nodata=-9999,
        tiled=True, blockxsize=64, blockysize=64,
    ) as dst:
        dst.write(np.zeros((height, width), dtype=np.float32), 1)
    return path


def test_plan_grid_window_covers_cells_and_storage_areas(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box

    terrain = _terrain(tmp_path / "t.tif")
    cells = gpd.GeoDataFrame({"cell_idx": [0]}, geometry=[box(10, 10, 20, 20)], crs="EPSG:26915")
    alone = _horizontal.plan_grid(cells, terrain, None, 1024, native=True)
    assert [int(v) for v in alone.window.flatten()] == [10, 80, 10, 10]
    pools = np.array([box(100, 50, 120, 60)], dtype=object)
    both = _horizontal.plan_grid(cells, terrain, None, 1024, native=True, storage_areas=pools)
    # Cells x 10..20, pool x 100..120 with one pixel of margin.
    assert [int(v) for v in both.window.flatten()] == [10, 39, 111, 51]
    assert both.planned_bytes > alone.planned_bytes
    # An AOI that holds a storage area but no cell is refused, not mapped empty.
    from ras_commander.fim import _aoi

    aoi = _aoi.resolve_aoi(bbox=(95, 45, 125, 65), default_crs=cells.crs)
    with pytest.raises(FimUnsupportedError, match="no 2D cells"):
        _horizontal.plan_grid(cells, terrain, aoi, 1024, native=True, storage_areas=pools)


@pytest.fixture
def model_files(tmp_path, monkeypatch):
    hdf = _plan(tmp_path / "m.p01.hdf", [("A", _square(0, 0, 1, 1), [])],
                series=[[1.0]], maximum=[1.0])
    tif = _terrain(tmp_path / "t.tif")
    scope = {"storage_areas": 1}
    monkeypatch.setattr(RasFim, "validate_2d_model", staticmethod(lambda *a, **k: dict(scope)))
    monkeypatch.setattr(_engine, "find_engine", lambda path=None: Path(tmp_path / "engine.exe"))
    return hdf, tif, scope


def _methods(storage=True):
    record = {"storage_area_surfaces": _storage_areas.METHOD_ID} if storage else {}
    return {
        "sloping": {"method_id": "rasmapper-plain-sloping/1", "stream_outputs": True, **record},
        "horizontal": {"method_id": "horizontal-cell-constant/2", "stream_outputs": True,
                       "native_ownership": True, **record},
        "whole_simulation": {"method_id": "native-whole-simulation-horizontal/1", **record},
    }


def test_capability_detection(monkeypatch, tmp_path):
    monkeypatch.setattr(_engine, "find_engine", lambda path=None: Path(tmp_path / "engine.exe"))
    monkeypatch.setattr(_engine, "engine_method", lambda engine: _methods(True))
    assert RasFim.supports_storage_areas() is True
    assert RasFim.STORAGE_AREA_METHOD == _storage_areas.METHOD_ID
    monkeypatch.setattr(_engine, "engine_method", lambda engine: _methods(False))
    assert RasFim.supports_storage_areas() is False

    def missing(path=None):
        raise FileNotFoundError("no engine")

    monkeypatch.setattr(_engine, "find_engine", missing)
    assert RasFim.supports_storage_areas() is False


@pytest.mark.parametrize("kwargs, error, message", [
    (dict(storage_areas=1), ValueError, "boolean"),
    (dict(storage_areas=True, velocity=True), FimUnsupportedError, "velocity"),
])
def test_sloping_option_refusals_precede_reads(model_files, tmp_path, kwargs, error, message):
    hdf, tif, _ = model_files
    with pytest.raises(error, match=message):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "out", **kwargs)
    assert not (tmp_path / "out").exists()


def test_sloping_storage_areas_refuse_supplied_profiles(model_files, tmp_path):
    import pandas as pd

    hdf, tif, _ = model_files
    with pytest.raises(FimUnsupportedError, match="caller-supplied"):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "out", storage_areas=True,
                                    wsel_profiles=pd.DataFrame())


def test_engine_without_capability_is_refused_before_output(model_files, tmp_path, monkeypatch):
    hdf, tif, _ = model_files
    monkeypatch.setattr(_engine, "engine_method", lambda engine: _methods(False))
    with pytest.raises(FimUnsupportedError, match="storage-area-level-pool/1"):
        RasFim.map_sloping_profiles(hdf, tif, tmp_path / "a", storage_areas=True)
    with pytest.raises(FimUnsupportedError, match="storage-area-level-pool/1"):
        RasFim.map_whole_simulation(hdf, tif, tmp_path / "b", threshold=0.5, storage_areas=True)
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()


def test_plans_without_storage_areas_refuse_the_option(model_files, tmp_path, monkeypatch):
    _, tif, scope = model_files
    empty = tmp_path / "e.p01.hdf"
    with h5py.File(empty, "w") as f:
        f.create_group("Geometry")
    scope["storage_areas"] = 0
    monkeypatch.setattr(_engine, "engine_method", lambda engine: _methods(True))
    with pytest.raises(FimUnsupportedError, match="no storage areas"):
        RasFim.map_sloping_profiles(empty, tif, tmp_path / "a", storage_areas=True)
    with pytest.raises(FimUnsupportedError, match="no storage areas"):
        RasFim.map_whole_simulation(empty, tif, tmp_path / "b", threshold=0.5, storage_areas=True)


def test_horizontal_storage_areas_need_provenance_and_full_selection(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box

    tif = _terrain(tmp_path / "t.tif")
    cells = gpd.GeoDataFrame({"cell_idx": [0], "wsel_max": [1.0]},
                             geometry=[box(10, 10, 20, 20)], crs="EPSG:26915")
    with pytest.raises(ValueError, match="hdf_path"):
        RasFim.map_horizontal_profiles(cells, tif, tmp_path / "a", storage_areas={"wsel_max": "Max"})


def test_check_report_requires_consistent_block():
    sa = _storage_areas.StorageAreas(("A",), np.array([None], dtype=object))
    good = {"storage_areas": {"method": {"method_id": _storage_areas.METHOD_ID},
                              "count": 1, "pixels": 5}}
    assert _storage_areas.check_report(good, sa)["pixels"] == 5
    for bad in ({}, {"storage_areas": {**good["storage_areas"], "count": 2}},
                {"storage_areas": {**good["storage_areas"], "pixels": True}}):
        with pytest.raises(FimEngineError):
            _storage_areas.check_report(bad, sa)


def test_public_signatures_expose_storage_areas():
    import inspect

    assert inspect.signature(RasFim.map_sloping_profiles).parameters["storage_areas"].default is False
    assert inspect.signature(RasFim.map_whole_simulation).parameters["storage_areas"].default is False
    assert inspect.signature(RasFim.map_horizontal_profiles).parameters["storage_areas"].default is None
    assert isinstance(RasFim.__dict__["supports_storage_areas"], staticmethod)


# ---------------------------------------------------------------------------
# Opt-in real-model qualification against native stored maps.
# ---------------------------------------------------------------------------

@pytest.fixture
def storage_case():
    filename = os.environ.get("RAS_COMMANDER_FIM_STORAGE_CASE")
    if not filename:
        pytest.skip("set RAS_COMMANDER_FIM_STORAGE_CASE for real native qualification")
    case = json.loads(Path(filename).read_text(encoding="utf-8"))
    if case.get("engine"):
        os.environ[_engine.ENGINE_ENV_VAR] = case["engine"]
    if not RasFim.supports_storage_areas():
        pytest.skip("engine lacks storage-area-level-pool/1")
    return case


def _on_grid(product, reference):
    """Product values resampled (by exact offset) onto the reference grid."""
    with rasterio.open(reference) as ref, rasterio.open(product) as src:
        expected = ref.read(1, masked=True).filled(np.nan).astype(np.float32)
        values = np.full(expected.shape, np.nan, dtype=np.float32)
        col = round((src.transform.c - ref.transform.c) / ref.transform.a)
        row = round((src.transform.f - ref.transform.f) / ref.transform.e)
        data = src.read(1, masked=True).filled(np.nan)
        r0, c0 = max(row, 0), max(col, 0)
        r1 = min(row + data.shape[0], expected.shape[0])
        c1 = min(col + data.shape[1], expected.shape[1])
        values[r0:r1, c0:c1] = data[r0 - row:r1 - row, c0 - col:c1 - col]
        outside = np.isfinite(data).sum() - np.isfinite(values).sum()
    return values, expected, int(outside)


def test_real_storage_area_maps_match_native(storage_case, tmp_path):
    for i, case in enumerate(storage_case["cases"]):
        mode = case["render_mode"]
        kwargs = dict(storage_areas=True, threads=4, max_working_mib=4096)
        profile = case.get("profile", "Max")
        if mode == "horizontal":
            cells = RasFim.get_cells_from_plan_hdf(storage_case["hdf"], mesh_name="*",
                                                   profile_name="wsel_max")
            if profile != "Max":
                pytest.skip("horizontal timestep cells need a timestep table")
            manifest = RasFim.map_horizontal_profiles(
                cells, storage_case["terrain"], tmp_path / f"h{i}", profiles=["wsel_max"],
                hdf_path=storage_case["hdf"], storage_areas={"wsel_max": "Max"},
                write_floodplain=False, threads=4, max_working_mib=4096)
        else:
            pretty = mode.startswith("slopingPretty")
            manifest = RasFim.map_sloping_profiles(
                storage_case["hdf"], storage_case["terrain"], tmp_path / f"s{i}",
                profiles={"P": profile}, render_mode="slopingPretty" if pretty else "sloping",
                reduce_shallow_to_horizontal=pretty and mode.endswith(":true"), **kwargs)
        row = manifest.iloc[0]
        assert manifest.attrs["storage_areas"]["pixels"] > 0
        for product in ("depth", "wse"):
            values, expected, outside = _on_grid(row[f"{product}_tif"], case[product])
            assert outside == 0
            assert np.array_equal(np.isfinite(values), np.isfinite(expected)), (mode, product)
            valid = np.isfinite(expected)
            assert np.array_equal(values[valid].view(np.uint32), expected[valid].view(np.uint32))
