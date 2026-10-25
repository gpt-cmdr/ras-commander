"""Actual raster/geometry tests for explicit horizontal mapping; no solver."""

import json
from pathlib import Path

import numpy as np
import pytest

gpd = pytest.importorskip("geopandas")
rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from ras_commander import RasFim
from ras_commander.fim import (
    FimMappingError,
    FimUnsupportedError,
    _engine,
    _horizontal,
    _prepare,
    _products,
)


@pytest.fixture
def scene(tmp_path):
    cells = gpd.GeoDataFrame(
        {
            "cell_idx": [0, 1, 2, 3],
            "wsel_a": [100.5, 101.0, 102.0, np.nan],
            "wsel_b": [103.0, np.nan, 100.1, 104.0],
            "geometry": [
                box(0, 0, 10, 10),
                box(10, 0, 20, 10),
                box(0, 10, 10, 20),
                box(10, 10, 20, 20),
            ],
        },
        crs="EPSG:2278",
    )
    terrain = tmp_path / "terrain.tif"
    data = np.full((20, 20), 100, dtype="float32")
    data[3, 3] = -9999
    with rasterio.open(
        terrain,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="float32",
        crs=cells.crs,
        transform=from_origin(0, 20, 1, 1),
        nodata=-9999,
    ) as dst:
        dst.write(data, 1)
    return cells, terrain, tmp_path


def run(scene, name="out", **kwargs):
    cells, terrain, root = scene
    return RasFim.map_horizontal_profiles(
        cells, terrain, root / name, backend="numpy", write_floodplain=False, **kwargs
    )


def test_horizontal_depth_filter_ownership_nodata_and_shared_prepare(scene, monkeypatch):
    cells, terrain, root = scene
    before = terrain.read_bytes()
    original = _horizontal.prepare_grid
    calls = []

    def prepare(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(_horizontal, "prepare_grid", prepare)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "horizontal mapping must not invoke triangulation or an external engine"
        )

    monkeypatch.setattr(_engine, "find_engine", forbidden)
    monkeypatch.setattr(_prepare, "prepare_profile", forbidden)
    rows = run(scene, min_depth=0.5)
    assert len(calls) == 1 and len(rows) == 2
    with rasterio.open(rows.iloc[0].depth_tif) as ds:
        depth = ds.read(1)
        assert ds.crs.to_epsg() == 2278 and ds.transform == from_origin(0, 20, 1, 1)
    assert np.isnan(depth[10:, :10]).all()  # exactly 0.5 is removed
    assert (depth[10:, 10:] == 1).all()
    assert np.isnan(depth[:10, 10:]).all()  # dry cell
    assert np.isnan(depth[3, 3])  # terrain nodata
    assert np.all(depth[:10, :10][np.isfinite(depth[:10, :10])] == 2)
    assert terrain.read_bytes() == before
    assert cells.wsel_a.iloc[0] == 100.5
    doc = json.loads((root / "out/fim_manifest.json").read_text())
    assert doc["status"] == "complete" and "numpy" in doc["method"]
    assert not (root / "out/fim_manifest.json.partial").exists()


def test_horizontal_polygon_hole_is_masked_crop(scene):
    full = run(scene, "full", min_depth=0.5)
    polygon = Polygon(
        [(1, 1), (19, 1), (19, 19), (1, 19)],
        holes=[[(5, 5), (15, 5), (15, 15), (5, 15)]],
    )
    cut = run(scene, "cut", min_depth=0.5, polygon=polygon, aoi_crs="EPSG:2278")
    with rasterio.open(full.iloc[0].depth_tif) as ds:
        expected = ds.read(1)[1:19, 1:19]
    expected[4:14, 4:14] = np.nan
    with rasterio.open(cut.iloc[0].depth_tif) as ds:
        np.testing.assert_array_equal(ds.read(1), expected)
        assert ds.transform == from_origin(1, 19, 1, 1)


def test_horizontal_preallocation_budget_and_fresh_folder(scene, monkeypatch):
    def forbidden(*args):
        raise AssertionError("raster arrays must not load before admission")

    monkeypatch.setattr(_horizontal, "prepare_grid", forbidden)
    with pytest.raises(FimUnsupportedError, match="planned"):
        run(scene, max_working_mib=1)
    assert not (scene[2] / "out").exists()
    (scene[2] / "out").mkdir()
    sentinel = scene[2] / "out/keep.txt"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError):
        run(scene)
    assert sentinel.read_text() == "keep"


def test_horizontal_overlaps_fail_with_manifest(scene):
    scene[0].loc[1, "geometry"] = box(5, 0, 20, 10)
    with pytest.raises(FimUnsupportedError, match="overlapping"):
        run(scene)
    document = json.loads((scene[2] / "out/fim_manifest.json").read_text())
    assert document["status"] == "aborted"
    assert all(p["status"] == "not_run" for p in document["profiles"])
    assert not list((scene[2] / "out").glob("*.tif"))


def test_horizontal_profile_write_error_is_not_success(scene, monkeypatch):
    writer = _products.write_raster

    def failing(path, *args):
        if Path(path).name.startswith("10_wsel_a"):
            raise OSError("injected write failure")
        return writer(path, *args)

    monkeypatch.setattr(_products, "write_raster", failing)
    rows = run(scene, raise_on_failure=False)
    assert list(rows.status) == ["failed", "complete"]
    assert not (scene[2] / "out/09_wsel_a_depth_nudge.tif").exists()
    assert json.loads((scene[2] / "out/fim_manifest.json").read_text())["status"] == "failed"


def test_horizontal_empty_aoi_and_infinite_profile(scene):
    rows = run(scene, "empty", bbox=(50, 50, 60, 60), max_working_mib=1)
    assert (rows.status == "empty_aoi").all()
    scene[0].loc[0, "wsel_a"] = np.inf
    with pytest.raises(FimMappingError) as caught:
        run(scene, "invalid")
    assert list(caught.value.manifest.status) == ["failed", "complete"]


def test_horizontal_rejects_crs_mismatch(scene):
    scene[0].set_crs("EPSG:3857", allow_override=True, inplace=True)
    with pytest.raises(FimUnsupportedError, match="share a CRS"):
        run(scene)


def test_horizontal_floodplain_uses_filtered_depth(scene):
    cells, terrain, root = scene
    rows = RasFim.map_horizontal_profiles(
        cells, terrain, root / "floodplain", backend="numpy", min_depth=0.5
    )
    frame = gpd.read_file(rows.iloc[0].floodplain_gpkg)
    assert frame.crs.to_epsg() == 2278
    assert frame.geometry.area.sum() == 199.0  # two wet cells minus one terrain-nodata pixel


def test_horizontal_normalizes_float64_wse_before_depth_filter(scene):
    scene[0].loc[0, "wsel_a"] = 100.5000001
    rows = run(scene, min_depth=0.5)
    with rasterio.open(rows.iloc[0].depth_tif) as src:
        assert np.isnan(src.read(1)[10:, :10]).all()


def test_horizontal_requires_declared_terrain_nodata(scene):
    with rasterio.open(scene[1], "r+") as dst:
        dst.nodata = None
    with pytest.raises(FimUnsupportedError, match="declare its nodata"):
        run(scene)


def test_horizontal_aoi_between_disconnected_cells_is_empty(scene):
    cells, terrain, root = scene
    cells = cells.iloc[:2].copy()
    cells.geometry = [box(0, 0, 5, 20), box(15, 0, 20, 20)]
    rows = RasFim.map_horizontal_profiles(
        cells,
        terrain,
        root / "gap",
        backend="numpy",
        bbox=(6, 5, 14, 15),
        max_working_mib=1,
    )
    assert (rows.status == "empty_aoi").all()
    assert not list((root / "gap").glob("*.tif"))


def test_horizontal_ignores_overlapping_cells_outside_aoi(scene):
    cells, terrain, root = scene
    extra = gpd.GeoDataFrame(
        {
            "cell_idx": [8, 9],
            "wsel_a": [110.0, 120.0],
            "wsel_b": [110.0, 120.0],
            "geometry": [box(100, 100, 110, 110), box(101, 101, 111, 111)],
        },
        crs=cells.crs,
    )
    import pandas as pd

    extended = gpd.GeoDataFrame(pd.concat([cells, extra], ignore_index=True), crs=cells.crs)
    rows = RasFim.map_horizontal_profiles(
        extended,
        terrain,
        root / "out",
        backend="numpy",
        bbox=(0, 0, 20, 20),
        write_floodplain=False,
    )
    assert (rows.status == "complete").all()
    assert rows.iloc[0].wet_cells == 3


def test_horizontal_abort_removes_committed_products_and_marks_manifest(scene, monkeypatch):
    writer = _products.write_raster

    def interrupted(path, *args):
        if "wsel_b" in Path(path).name:
            raise KeyboardInterrupt()
        return writer(path, *args)

    monkeypatch.setattr(_products, "write_raster", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run(scene)
    assert not list((scene[2] / "out").glob("*.tif"))
    doc = json.loads((scene[2] / "out/fim_manifest.json").read_text())
    assert doc["status"] == "aborted" and all(row["status"] == "not_run" for row in doc["profiles"])


def test_horizontal_changed_input_manifest_and_exception_agree(scene, monkeypatch):
    from ras_commander.fim.RasFim import _file_identity
    import importlib

    module = importlib.import_module("ras_commander.fim.RasFim")
    calls = []

    def changed(path):
        size, mtime = _file_identity(path)
        calls.append(1)
        return size, mtime + int(len(calls) > 1)

    monkeypatch.setattr(module, "_file_identity", changed)
    with pytest.raises(FimMappingError) as caught:
        run(scene)
    assert (caught.value.manifest.status == "not_run").all()
    assert json.loads((scene[2] / "out/fim_manifest.json").read_text())["status"] == "aborted"
    assert not list((scene[2] / "out").glob("*.tif"))


@pytest.mark.parametrize("other", [box(0, 0, 10, 10), box(2, 2, 8, 8)])
def test_horizontal_rejects_coincident_and_contained_cells(scene, other):
    scene[0].loc[1, "geometry"] = other
    with pytest.raises(FimUnsupportedError, match="overlapping"):
        run(scene)


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("postprocess", [False, True])
@pytest.mark.parametrize("independent", [False, True])
def test_native_comparison_uses_horizontal_and_restores_rasmap(scene, monkeypatch, failure, postprocess, independent):
    from types import SimpleNamespace
    import shutil
    import pandas as pd
    from ras_commander import RasMap, RasProcess, StoreMapPerformanceOptions

    cells, terrain, root = scene
    rasmap = root / "project.rasmap"
    original = b"<RASMapper><RenderMode>slopingPretty</RenderMode></RASMapper>"
    rasmap.write_bytes(original)
    hdf = root / "project.p01.hdf"
    import h5py
    with h5py.File(hdf, "w") as file:
        file.create_dataset("Geometry/2D Flow Areas/mesh/Cells Center Coordinate", data=[[0.0, 0.0]])
    obj = SimpleNamespace(
        project_folder=root,
        project_name="project",
        plan_df=pd.DataFrame([{"plan_number": "01", "full_path": str(hdf).removesuffix(".hdf")}]),
        check_initialized=lambda: None,
    )
    obj.get_plan_entries = lambda: obj.plan_df
    monkeypatch.setattr(RasMap, "get_rasmap_path", lambda ras_object=None: rasmap)
    monkeypatch.setattr(
        RasMap,
        "list_terrain_layers",
        lambda *a, **k: pd.DataFrame(
            [
                {
                    "name": "terrain",
                    "filename": str(terrain),
                    "resolved_path": str(terrain),
                }
            ]
        ),
    )
    monkeypatch.setattr(
        RasProcess,
        "get_store_maps_runtime_provenance",
        lambda *a: {"test_runtime": True},
    )
    mapper = RasFim.map_horizontal_profiles

    def reference(*a, **kw):
        return mapper(*a, backend="numpy", **kw)

    monkeypatch.setattr(RasFim, "map_horizontal_profiles", reference)

    def native(plan, **kw):
        assert (
            kw["render_mode"] == "horizontal" and kw["wse"] and kw["depth"] and not kw["velocity"]
        )
        assert kw["profile"] == "Max"
        assert kw["terrain_name"] == (None if independent else "terrain")
        assert (kw["performance"] is not None) == independent
        if failure:
            rasmap.write_bytes(b"changed during native failure")
            raise RuntimeError("injected native failure")
        folder = Path(kw["output_path"])
        depth = folder / "depth.tif"
        wse = folder / "wse.tif"
        shutil.copy2(root / "comparison/rust/09_wsel_a_depth_nudge.tif", depth)
        shutil.copy2(root / "comparison/rust/10_wsel_a_wsel_nudge.tif", wse)
        return {"depth": [depth], "wse": [wse]}

    monkeypatch.setattr(RasProcess, "store_maps", native)
    kwargs = dict(cells=cells, profiles={"wsel_a": "Max"}, ras_object=obj,
                  min_depth=0.5, postprocess_reference=postprocess,
                  native_performance=StoreMapPerformanceOptions(max_workers=2) if independent else None)
    if failure:
        with pytest.raises(RuntimeError, match="injected native failure"):
            RasFim.compare_with_rasmapper("01", terrain, root / "comparison", **kwargs)
    else:
        rows = RasFim.compare_with_rasmapper("01", terrain, root / "comparison", **kwargs)
        assert rows.iloc[0].csi == 1 and rows.iloc[0].wse_exact_fraction == 1
        assert rows.iloc[0].common_wet == 199
        assert rows.iloc[0].candidate_seconds > 0
        assert rows.iloc[0].native_total_seconds >= rows.iloc[0].native_seconds
        assert rows.attrs["performance"]["profile_count"] == 1
        from ras_commander.schemas import DATAFRAME_SCHEMAS
        assert list(rows.columns) == [c["name"] for c in DATAFRAME_SCHEMAS["fim_comparison"]["columns"]]
        assert not rows.attrs["performance"]["ratio_eligible"]
        if postprocess:
            with rasterio.open(rows.iloc[0].reference_filtered_depth_tif) as ds:
                actual = ds.read(1)
                assert np.count_nonzero(np.isfinite(actual)) == 199
        else:
            assert rows.iloc[0].reference_filtered_depth_tif is None
            assert rows.iloc[0].native_postprocess_seconds == 0
    doc = json.loads((root / "comparison/comparison.json").read_text())
    assert doc["rasmap_restored"] is True
    assert doc["rasmap_sha256_before"] == doc["rasmap_sha256_after"]
    assert doc["status"] == ("aborted" if failure else "complete")
    assert rasmap.read_bytes() == original
    assert not (root / ".project.storemaps.lock").exists()
    if not failure and not independent and not postprocess:
        def incomplete_native(*a, **kw):
            products = native(*a, **kw)
            with rasterio.open(products["wse"][0], "r+") as src:
                data = src.read(1)
                data[0, 0] = np.nan
                src.write(data, 1)
            return products
        monkeypatch.setattr(RasProcess, "store_maps", incomplete_native)
        invalid = RasFim.compare_with_rasmapper("01", terrain, root / "invalid-reference", **kwargs)
        assert invalid.reference_missing_wse.sum() > 0
        assert invalid.attrs["performance"]["observed_native_to_candidate_ratio"] is None
        assert any("do not match exactly" in x for x in invalid.attrs["performance"]["ratio_exclusions"])
    if independent:
        # An independent command cannot select among terrain registrations.
        # Reject ambiguity before creating outputs or invoking either mapper.
        monkeypatch.setattr(RasMap, "list_terrain_layers", lambda *a, **k: pd.DataFrame([
            {"name": "terrain", "resolved_path": str(terrain)},
            {"name": "other", "resolved_path": str(terrain)},
        ]))
        with pytest.raises(FimUnsupportedError, match="sole registered terrain"):
            RasFim.compare_with_rasmapper("01", terrain, root / "ambiguous",
                                         terrain_name="terrain", **kwargs)
        assert not (root / "ambiguous").exists()


def test_comparison_rejects_fractional_grid_shift(scene):
    from ras_commander.fim._comparison import compare_rasters

    rows = run(scene, min_depth=0.5)
    d = rows.iloc[0].depth_tif
    w = rows.iloc[0].wse_tif
    shifted = scene[2] / "shifted.tif"
    with rasterio.open(d) as src:
        meta = src.profile
        data = src.read(1)
    meta["transform"] = from_origin(0.5, 20, 1, 1)
    with rasterio.open(shifted, "w", **meta) as dst:
        dst.write(data, 1)
    with pytest.raises(FimUnsupportedError, match="integer pixel offsets"):
        compare_rasters(d, w, shifted, w, scene[0], None, 0.5)


def test_rust_horizontal_matches_reference(scene):
    import os

    engine = os.environ.get("RAS_COMMANDER_FIM_HORIZONTAL_ENGINE")
    if not engine:
        pytest.skip("set RAS_COMMANDER_FIM_HORIZONTAL_ENGINE to a horizontal-capable binary")
    cells, terrain, root = scene
    expected = run(scene, "reference", min_depth=0.5)
    for threads in (1, 4):
        actual = RasFim.map_horizontal_profiles(
            cells,
            terrain,
            root / f"rust-{threads}",
            engine_path=engine,
            threads=threads,
            writer_threads=threads,
            min_depth=0.5,
            write_floodplain=False,
        )
        for name in cells.columns[cells.columns.str.startswith("wsel")]:
            a = actual.loc[actual.profile == name].iloc[0]
            b = expected.loc[expected.profile == name].iloc[0]
            for product in ("depth_tif", "wse_tif"):
                with rasterio.open(a[product]) as x, rasterio.open(b[product]) as y:
                    np.testing.assert_array_equal(x.read(1), y.read(1))
                    assert x.transform == y.transform


@pytest.mark.parametrize("tiled", [True, False])
@pytest.mark.parametrize("threshold", [0.1, 0.15])
def test_rust_horizontal_block_seams_polygon_and_float32(scene, tiled, threshold):
    import os

    engine = os.environ.get("RAS_COMMANDER_FIM_HORIZONTAL_ENGINE")
    if not engine:
        pytest.skip("set RAS_COMMANDER_FIM_HORIZONTAL_ENGINE")
    _, _, root = scene
    terrain = root / "blocks.tif"
    data = np.full((37, 45), 100.0, dtype="float32")
    data[:, 20:] = 100.25
    data[16, 16] = np.nan
    layout = (
        dict(tiled=True, blockxsize=16, blockysize=16) if tiled else dict(tiled=False, blockysize=7)
    )
    with rasterio.open(
        terrain,
        "w",
        driver="GTiff",
        width=45,
        height=37,
        count=1,
        dtype="float32",
        crs="EPSG:2278",
        transform=from_origin(0, 37, 1, 1),
        nodata=np.nan,
        **layout,
    ) as dst:
        dst.write(data, 1)
    cells = gpd.GeoDataFrame(
        {
            "cell_idx": [0, 1],
            "wsel_a": [100.1, 101.15],
            "wsel_dry": [0.0, 0.0],
            "wsel_nan": [np.nan, np.nan],
            "geometry": [box(0, 0, 23, 37), box(23, 0, 45, 37)],
        },
        crs="EPSG:2278",
    )
    polygon = Polygon(
        [(3, 4), (43, 4), (43, 34), (3, 34)],
        holes=[[(8, 8), (12, 8), (12, 12), (8, 12)]],
    )
    reference = RasFim.map_horizontal_profiles(
        cells,
        terrain,
        root / "oracle",
        backend="numpy",
        polygon=polygon,
        aoi_crs=cells.crs,
        min_depth=threshold,
        write_floodplain=False,
    )
    for threads in (1, 4):
        actual = RasFim.map_horizontal_profiles(
            cells,
            terrain,
            root / f"native-{threads}",
            engine_path=engine,
            threads=threads,
            writer_threads=threads,
            polygon=polygon,
            aoi_crs=cells.crs,
            min_depth=threshold,
            write_floodplain=False,
        )
        for a, b in zip(actual.itertuples(), reference.itertuples()):
            for attr in ("depth_tif", "wse_tif"):
                with rasterio.open(getattr(a, attr)) as x, rasterio.open(getattr(b, attr)) as y:
                    np.testing.assert_array_equal(x.read(1).view("<u4"), y.read(1).view("<u4"))
                    assert x.transform == y.transform


def test_horizontal_rejects_dataset_mask(scene):
    with rasterio.open(scene[1], "r+") as dst:
        dst.write_mask(np.full((20, 20), 255, dtype="uint8"))
    with pytest.raises(FimUnsupportedError, match="dataset/alpha mask"):
        run(scene)


def test_horizontal_stream_report_mismatch_removes_products(scene, monkeypatch):
    import io
    import sys
    from ras_commander.fim import _horizontal_engine
    from ras_commander.fim.errors import FimEngineError

    method = {
        "method_id": "horizontal-cell-constant/1",
        "stream_outputs": True,
        "native_ownership": True,
    }
    monkeypatch.setattr(_engine, "engine_method", lambda *a: {"horizontal": method})
    monkeypatch.setattr(
        _engine,
        "terrain_identity",
        lambda *a: {"epsg": 2278, "crs_identity": {"kind": "epsg"}},
    )

    class FakeProcess:
        def __init__(self, args, **kwargs):
            request = json.loads(Path(args[2]).read_text())
            out = Path(args[3])
            out.mkdir()
            pixels = request["window"][2] * request["window"][3]
            raw = bytearray()
            units = []
            for item in request["profiles"]:
                name = item["id"]
                raw.extend(
                    (
                        json.dumps({"id": name, "status": "complete", "pixels": pixels}) + "\n"
                    ).encode()
                )
                raw.extend(np.full(pixels, 1, dtype="<f4").tobytes())
                raw.extend(np.full(pixels, 101, dtype="<f4").tobytes())
                unit = {
                    "id": name,
                    "status": "failed",
                    "error": "injected inconsistent terminal unit",
                }
                units.append(unit)
                directory = out / name
                directory.mkdir()
                (directory / "unit.json").write_text(json.dumps(unit))
            report = {
                "schema": "ras2fim-horizontal-report/1",
                "status": "failed",
                "window": request["window"],
                "method": method,
                "profiles": units,
            }
            (out / "report.json").write_text(json.dumps(report))
            self.stdout = io.BytesIO(raw)

        def wait(self):
            return 2

        def poll(self):
            return 2

        def kill(self):
            raise AssertionError("completed fake process must not be killed")

    monkeypatch.setattr(_horizontal_engine.subprocess, "Popen", FakeProcess)
    cells, terrain, root = scene
    with pytest.raises(FimEngineError, match="inconsistent horizontal engine report"):
        RasFim.map_horizontal_profiles(
            cells,
            terrain,
            root / "bad-report",
            engine_path=sys.executable,
            write_floodplain=False,
        )
    assert not list((root / "bad-report").glob("*.tif"))
    doc = json.loads((root / "bad-report/fim_manifest.json").read_text())
    assert doc["status"] == "aborted" and doc["engine_report"]["status"] == "failed"
    assert all(row["status"] == "not_run" for row in doc["profiles"])


def test_rust_horizontal_preserves_abort_reason(scene):
    import os
    from ras_commander.fim.errors import FimEngineError

    engine = os.environ.get("RAS_COMMANDER_FIM_HORIZONTAL_ENGINE")
    if not engine:
        pytest.skip("set RAS_COMMANDER_FIM_HORIZONTAL_ENGINE")
    cells, terrain, root = scene
    with rasterio.open(terrain, "r+") as dst:
        data = dst.read(1)
        data[0, 0] = np.inf
        dst.write(data, 1)
    with pytest.raises(FimEngineError, match="unmasked infinite terrain"):
        RasFim.map_horizontal_profiles(
            cells, terrain, root / "aborted", engine_path=engine, write_floodplain=False
        )
    doc = json.loads((root / "aborted/fim_manifest.json").read_text())
    assert doc["status"] == "aborted" and doc["engine_report"]["status"] == "aborted"
    assert not list((root / "aborted").glob("*.tif"))


@pytest.mark.parametrize("short", [1, 3, 65539])
def test_horizontal_chunked_read_preserves_bits_and_partial_reads(short):
    import io
    import threading
    from ras_commander.fim._horizontal_engine import _read_f32

    bits = np.tile(np.array([0, 0x80000000, 0x7FC01234, 0x3E19999A], dtype="<u4"), 80000)

    class Partial(io.BytesIO):
        def readinto(self, buffer):
            assert len(buffer) <= 1 << 20
            return super().readinto(buffer[:short])

    result = _read_f32(Partial(bits.tobytes()), (400, 800), threading.Event(), None, "depth")
    assert not result.flags.writeable
    np.testing.assert_array_equal(result.view("<u4").ravel(), bits)


@pytest.mark.parametrize("expired", [False, True])
def test_horizontal_chunked_read_rejects_truncation(expired):
    import io
    import threading
    from ras_commander.fim._horizontal_engine import _read_f32
    from ras_commander.fim.errors import FimEngineError

    event = threading.Event()
    if expired:
        event.set()
    with pytest.raises(FimEngineError, match="timed out" if expired else "truncated"):
        _read_f32(io.BytesIO(b"123"), (2, 2), event, 10, "wse")


def test_horizontal_staged_owner_bits_and_multiblock_write(tmp_path):
    from ras_commander.fim._horizontal_engine import _write_array

    owner = np.arange(800000, dtype="<i4")
    path = tmp_path / "owner.bin"
    _write_array(path, owner.view("<u4"))
    np.testing.assert_array_equal(np.fromfile(path, dtype="<u4"), owner)


@pytest.mark.parametrize("workers", [0, True, 65])
def test_horizontal_rejects_invalid_writer_worker_count(scene, workers):
    cells, terrain, root = scene
    with pytest.raises(ValueError, match="writer_threads"):
        RasFim.map_horizontal_profiles(
            cells,
            terrain,
            root / "bad-workers",
            backend="numpy",
            writer_threads=workers,
        )
    assert not (root / "bad-workers").exists()


def test_horizontal_writer_workers_are_scoped_and_restored(scene, monkeypatch):
    seen = []
    original = RasFim._write_products

    def inspect(*args):
        seen.append(rasterio.env.getenv()["GDAL_NUM_THREADS"])
        return original(*args)

    monkeypatch.setattr(RasFim, "_write_products", staticmethod(inspect))
    with rasterio.Env(GDAL_NUM_THREADS="2"):
        run(scene, "writers", profiles=["wsel_a"], writer_threads=4)
        assert rasterio.env.getenv()["GDAL_NUM_THREADS"] == "2"
    assert seen == ["4"]


@pytest.mark.parametrize("kind", ["hole", "corner", "extra_vertex", "sliver"])
def test_horizontal_overlap_topology_edge_cases(scene, kind):
    cells, terrain, root = scene
    first = box(0, 0, 10, 10)
    second = box(10, 0, 20, 10)
    if kind == "hole":
        first = Polygon(box(0, 0, 20, 20).exterior.coords, [box(5, 5, 15, 15).exterior.coords])
        second = box(5, 5, 10, 10)
    elif kind == "corner":
        second = box(10, 10, 20, 20)
    elif kind == "extra_vertex":
        first = Polygon([(0, 0), (10, 0), (10, 5), (10, 10), (0, 10)])
    else:
        second = box(9.999, 0, 20, 10)
    frame = gpd.GeoDataFrame(
        {"cell_idx": [0, 1], "wsel_a": [103.0, 103.0], "geometry": [first, second]},
        crs=cells.crs,
    )
    if kind == "sliver":
        with pytest.raises(FimUnsupportedError, match="overlapping interiors"):
            RasFim.map_horizontal_profiles(frame, terrain, root / kind, backend="numpy")
    else:
        result = RasFim.map_horizontal_profiles(
            frame, terrain, root / kind, backend="numpy", write_floodplain=False
        )
        assert result.iloc[0].status == "complete"


def test_horizontal_owner_view_does_not_copy_or_change_bits():
    owner = np.array([0, 1, np.iinfo(np.int32).max, -1], dtype="<i4")
    staged = owner.astype("<i4", copy=False).view("<u4")
    assert np.shares_memory(owner, staged)
    assert staged.tobytes() == owner.astype("<u4").tobytes()


@pytest.mark.parametrize("workers", [1, 4, 8])
@pytest.mark.parametrize("multipart", [False, True])
def test_native_terrio_owns_boundary_and_polygon_mask(scene, monkeypatch, workers, multipart):
    import os
    from shapely.geometry import MultiPolygon
    from rasterio import features

    engine = os.environ.get("RAS_COMMANDER_FIM_HORIZONTAL_ENGINE")
    if not engine:
        pytest.skip("set RAS_COMMANDER_FIM_HORIZONTAL_ENGINE to the rebuilt engine")
    cells, terrain, root = scene
    # Put a shared boundary exactly on pixel centres, with distinct cell values.
    cells.loc[0, "geometry"] = box(0, 0, 10.5, 10)
    cells.loc[1, "geometry"] = box(10.5, 0, 20, 10)
    polygon = Polygon(
        [(1, 1), (19, 1), (19, 19), (1, 19)], holes=[[(5, 5), (8, 5), (8, 8), (5, 8)]]
    )
    if multipart:
        polygon = MultiPolygon([polygon, box(0, 0, 0.75, 0.75)])
    kw = dict(polygon=polygon, aoi_crs=cells.crs, min_depth=0.5, write_floodplain=False)
    reference = RasFim.map_horizontal_profiles(
        cells, terrain, root / "reference", backend="numpy", **kw
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("native ownership and AOI masking must not call GDAL rasterization")

    monkeypatch.setattr(features, "rasterize", forbidden)
    monkeypatch.setattr(features, "geometry_mask", forbidden)
    actual = RasFim.map_horizontal_profiles(
        cells, terrain, root / "native", engine_path=engine, threads=workers, **kw
    )
    for expected, result in zip(reference.itertuples(), actual.itertuples()):
        for product in ("depth_tif", "wse_tif"):
            with rasterio.open(getattr(expected, product)) as a, rasterio.open(
                getattr(result, product)
            ) as b:
                assert a.transform == b.transform and a.crs == b.crs
                np.testing.assert_array_equal(a.read(1).view("u4"), b.read(1).view("u4"))
    details = json.loads((root / "native/fim_manifest.json").read_text())
    assert details["engine_report"]["ownership_backend"] == "terrio"
    assert details["engine_report"]["threads"] == workers


def test_native_ownership_rejects_old_engine_without_rasterizing(scene, monkeypatch):
    import sys
    from rasterio import features
    from ras_commander.fim.errors import FimEngineError

    monkeypatch.setattr(
        _engine,
        "engine_method",
        lambda *a: {
            "horizontal": {"method_id": "horizontal-cell-constant/1", "stream_outputs": True}
        },
    )
    monkeypatch.setattr(
        features, "rasterize", lambda *a, **k: pytest.fail("unexpected GDAL fallback")
    )
    with pytest.raises(FimEngineError, match="native terrio ownership"):
        RasFim.map_horizontal_profiles(
            scene[0], scene[1], scene[2] / "old", engine_path=sys.executable
        )


def test_native_geometry_transport_preserves_order_holes_and_multipart(tmp_path):
    import struct
    import shapely
    from shapely.geometry import MultiPolygon
    from ras_commander.fim._horizontal_engine import _write_geometry

    first = Polygon([(0, 0), (9, 0), (9, 9), (0, 9)], holes=[[(2, 2), (3, 2), (3, 3), (2, 3)]])
    geometries = [first, MultiPolygon([box(10, 0, 11, 1), box(12, 0, 13, 1)])]
    path = tmp_path / "geometry.wkb"
    _write_geometry(path, geometries)
    with path.open("rb") as source:
        for expected in geometries:
            length = struct.unpack("<I", source.read(4))[0]
            actual = shapely.from_wkb(source.read(length))
            assert actual.equals_exact(expected, 0)
        assert source.read(1) == b""


@pytest.mark.parametrize("element", ["River Centerlines", "Cross Sections", "text_reach", "malformed_reach", "orphan_node"])
def test_2d_only_gate_rejects_mixed_models_before_mapping(scene, monkeypatch, element):
    import h5py

    cells, terrain, root = scene
    hdf = root / "mixed.p01.hdf"
    geom = root / "mixed.g01"
    with h5py.File(hdf, "w") as src:
        src.create_dataset("Geometry/2D Flow Areas/mesh/Cells Center Coordinate", data=[[0., 0.]])
        if element in ("text_reach", "malformed_reach", "orphan_node"):
            src.require_group("Plan Data/Plan Information").attrs["Geometry Filename"] = geom.name
            declaration = {"text_reach": "Reach=Legacy river",
                           "malformed_reach": "River Reach=broken",
                           "orphan_node": "Type RM Length L Ch R=1,10,2,2,2"}[element]
            geom.write_text("Geom Title=Mixed\n" + declaration + "\n", encoding="utf-8")
        else:
            src.create_dataset(f"Geometry/{element}/Attributes", data=[1])
    def forbidden(*a, **k):
        raise AssertionError("engine must not run for a model containing 1D elements")
    monkeypatch.setattr(_engine, "find_engine", forbidden)
    with pytest.raises(FimUnsupportedError, match="2D-only"):
        RasFim.get_cells_from_plan_hdf(hdf, mesh_name="mesh")
    with pytest.raises(FimUnsupportedError, match="2D-only"):
        RasFim.map_horizontal_profiles(cells, terrain, root / "blocked", hdf_path=hdf)
    cells.attrs["fim_source_hdf"] = str(hdf)
    with pytest.raises(FimUnsupportedError, match="2D-only"):
        RasFim.map_horizontal_profiles(cells, terrain, root / "blocked-attrs")
    assert not (root / "blocked").exists()


def test_2d_scope_allows_pipe_hydraulic_tables_without_river_geometry(tmp_path):
    import h5py

    path = tmp_path / "pipes.p01.hdf"
    with h5py.File(path, "w") as src:
        src.create_dataset("Geometry/2D Flow Areas/surface/Cells Center Coordinate", data=[[0., 0.]])
        src.create_dataset("Geometry/Cross Sections/Property Tables/XSEC Info", data=[[0, 2, 3]])
        src.create_dataset("Geometry/Pipe Conduits/Attributes", data=[1, 2])
    assert RasFim.validate_2d_model(path)["dimension"] == "2D-only"


def test_canonical_terrain_preserves_pixel_bits_and_source(scene):
    import hashlib

    _, terrain, root = scene
    before = hashlib.sha256(terrain.read_bytes()).hexdigest()
    path = RasFim.canonicalize_terrain_crs(terrain, root / "canonical.tif")
    with rasterio.open(terrain) as a, rasterio.open(path) as b:
        np.testing.assert_array_equal(a.read(1).view("u4"), b.read(1).view("u4"))
        assert a.crs == b.crs and a.transform == b.transform and a.nodata == b.nodata
    assert hashlib.sha256(terrain.read_bytes()).hexdigest() == before
    receipt = json.loads(path.with_suffix(".tif.json").read_text())
    assert receipt["pixel_bits_and_grid_preserved"] and not receipt["reprojected"]
    with pytest.raises(FileExistsError):
        RasFim.canonicalize_terrain_crs(terrain, path)


def test_reference_postprocessing_independently_filters_depth_and_wse(scene):
    from ras_commander.fim._comparison import filter_reference

    rows = run(scene, min_depth=0.0)
    folder = scene[2] / "native-filtered"
    folder.mkdir()
    paths = filter_reference(rows.iloc[0].depth_tif, rows.iloc[0].wse_tif, folder, .5, 1)
    with rasterio.open(rows.iloc[0].depth_tif) as src:
        raw = src.read(1)
        assert (raw == .5).any()
    with rasterio.open(paths[0]) as d, rasterio.open(paths[1]) as w:
        depth, wse = d.read(1), w.read(1)
        keep = np.isfinite(raw) & (raw > np.float32(.5))
        assert np.array_equal(np.isfinite(depth), keep)
        assert np.array_equal(np.isfinite(wse), keep)


def test_all_meshes_keep_local_wse_identity_and_global_unique_ids(tmp_path, monkeypatch):
    import h5py
    import pandas as pd
    from ras_commander import HdfMesh, HdfResultsMesh

    path = tmp_path / "two.p01.hdf"
    with h5py.File(path, "w") as src:
        for mesh in ("left", "right"):
            src.create_dataset(f"Geometry/2D Flow Areas/{mesh}/Cells Center Coordinate", data=[[0., 0.]])
    polygons = gpd.GeoDataFrame({"mesh_name": ["left", "right"], "cell_id": [0, 0],
                                "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)]}, crs="EPSG:2278")
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda *a, **k: polygons)
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", lambda *a: pd.DataFrame(
        {"mesh_name": ["left", "right"], "cell_id": [0, 0], "maximum_water_surface": [103., 107.]}))
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_depth", lambda *a: pd.DataFrame(
        {"mesh_name": ["left", "right"], "cell_id": [0, 0], "maximum_depth": [3., 7.]}))
    cells = RasFim.get_cells_from_plan_hdf(path, mesh_name="*")
    assert cells.cell_idx.tolist() == [0, 1]
    assert cells.wsel_max.tolist() == [103., 107.]
    assert cells.attrs["fim_full_2d_coverage"]
    assert cells.attrs["fim_mesh_names"] == ["left", "right"]
