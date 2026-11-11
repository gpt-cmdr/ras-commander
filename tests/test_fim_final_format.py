"""Engine-written final delivery format: option contract, gates and verification."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from affine import Affine
from rasterio.enums import Resampling
from rasterio.windows import Window

from ras_commander import FimUnsupportedError, RasFim
from ras_commander.fim import _final_format, _native_products, _sloping
from ras_commander.fim.errors import FimEngineError

CAPABILITY = {
    "control": "final_format", "compression": "DEFLATE", "layout": "tiled",
    "block_size": {"default": 256, "multiple_of": 16, "min": 16, "max": 4096},
    "zlevel": {"default": 6, "min": 1, "max": 9}, "nodata": "finite Float32",
    "full_grid": True, "overview_resampling": ["average"], "row_stream_rows": True,
}
METHOD = {"native_geotiff_outputs": True, "native_final_format": CAPABILITY}
TERRAIN = Affine(10.0, 0.0, 1000.0, 0.0, -10.0, 9000.0)


def plan(col=40, row=24, width=300, height=280):
    window = Window(col, row, width, height)
    return SimpleNamespace(
        window=window, shape=(height, width), source_transform=TERRAIN,
        transform=TERRAIN * Affine.translation(col, row), crs=rasterio.crs.CRS.from_epsg(2278),
    )


def test_defaults_and_normalised_keys():
    assert _final_format.normalize(None) is None
    assert _final_format.normalize({"nodata": -9999}) == dict(
        nodata=-9999.0, block_size=256, zlevel=6, overviews=[], grid="window")
    assert _final_format.normalize(
        {"nodata": np.float32(0.5), "block_size": 512, "zlevel": 9, "overviews": (2, 4, 8),
         "grid": (0, 0, 20, 30)}
    ) == dict(nodata=0.5, block_size=512, zlevel=9, overviews=[2, 4, 8], grid=[0, 0, 20, 30])


@pytest.mark.parametrize("value", [
    "deflate", [], {}, {"block_size": 256}, {"nodata": -9999, "tile": 256},
    {"nodata": 0.1}, {"nodata": 1e300}, {"nodata": float("nan")}, {"nodata": float("inf")},
    {"nodata": True}, {"nodata": "-9999"}, {"nodata": 0, "block_size": 100},
    {"nodata": 0, "block_size": 8}, {"nodata": 0, "block_size": 8192},
    {"nodata": 0, "block_size": 256.0}, {"nodata": 0, "zlevel": 0}, {"nodata": 0, "zlevel": 10},
    {"nodata": 0, "overviews": [4]}, {"nodata": 0, "overviews": [2, 8]},
    {"nodata": 0, "overviews": 2}, {"nodata": 0, "overviews": "24"},
    {"nodata": 0, "grid": "full"}, {"nodata": 0, "grid": [0, 0, 10]},
    {"nodata": 0, "grid": [0, 0, 0, 10]}, {"nodata": 0, "grid": [0, -1, 10, 10]},
    {"nodata": 0, "grid": [0, 0, 1.5, 10]},
])
def test_invalid_options_are_value_errors(value):
    with pytest.raises(ValueError, match="final_format"):
        _final_format.normalize(value)


@pytest.mark.parametrize("call", [
    lambda folder, option: RasFim.map_sloping_profiles(
        folder / "absent.hdf", folder / "absent.tif", folder / "out", final_format=option),
    lambda folder, option: RasFim.map_sloping_profiles(
        folder / "absent.hdf", folder / "absent.tif", folder / "out", final_format=option,
        product_writer="rasterio"),
])
def test_final_format_needs_the_native_writer_before_any_input_is_read(call, tmp_path):
    with pytest.raises(FimUnsupportedError, match="product_writer='native'"):
        call(tmp_path, {"nodata": -9999})
    with pytest.raises(ValueError, match="final_format"):
        call(tmp_path, {"nodata": 0.1})
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("extra", [
    {"write_floodplain": True}, {"velocity": True}, {"template_raster": "template.tif"},
])
def test_array_consumers_stay_refused_with_final_format(extra, tmp_path):
    with pytest.raises(FimUnsupportedError):
        RasFim.map_sloping_profiles(
            tmp_path / "absent.hdf", tmp_path / "absent.tif", tmp_path / "out",
            product_writer="native", final_format={"nodata": -9999}, **extra)


def test_catalog_refuses_final_format_without_native_writer(tmp_path):
    with pytest.raises(FimUnsupportedError, match="product_writer='native'"):
        RasFim.map_catalog([], tmp_path / "out", final_format={"nodata": -9999})
    with pytest.raises(ValueError, match="final_format"):
        RasFim.map_catalog([], tmp_path / "out", product_writer="native",
                           final_format={"nodata": 0.1})


def test_public_calls_forward_final_format(monkeypatch):
    seen = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        return "mapped"

    monkeypatch.setattr(_sloping, "map_profiles", capture)
    option = {"nodata": -9999, "overviews": [2, 4], "grid": "terrain"}
    assert RasFim.map_sloping_profiles(
        "model.hdf", "terrain.tif", "out", product_writer="native", final_format=option
    ) == "mapped"
    assert seen["final_format"] is option and seen["product_writer"] == "native"
    seen.clear()
    assert RasFim.map_sloping_profiles("model.hdf", "terrain.tif", "out") == "mapped"
    assert seen["final_format"] is None


def test_capability_gate_has_no_fallback():
    options = _final_format.normalize({"nodata": -9999, "overviews": [2], "grid": "terrain"})
    _final_format.require_engine(METHOD, options)
    _final_format.require_engine(METHOD, options, row_stream_rows=64)

    def without(key, value=None):
        capability = {k: v for k, v in CAPABILITY.items() if k != key}
        if value is not None:
            capability[key] = value
        return {"native_geotiff_outputs": True, "native_final_format": capability}

    refused = [
        {}, {"native_geotiff_outputs": True}, {"native_final_format": CAPABILITY},
        {"native_geotiff_outputs": True, "native_final_format": True},
        {"native_geotiff_outputs": True, "native_output_compression": ["NONE", "LZW", "DEFLATE"]},
        without("control"), without("compression", "LZW"), without("layout", "striped"),
        without("block_size"), without("block_size", {"min": 512, "max": 4096, "multiple_of": 16}),
        without("block_size", {"min": 16, "max": 4096}), without("zlevel", {"min": 7, "max": 9}),
        without("full_grid"), without("overview_resampling", ["nearest"]),
    ]
    for method in refused:
        with pytest.raises(FimUnsupportedError, match="native_final_format"):
            _final_format.require_engine(method, options)
    with pytest.raises(FimUnsupportedError, match="native_final_format"):
        _final_format.require_engine(without("row_stream_rows"), options, row_stream_rows=64)
    # A window delivery without overviews needs neither optional capability.
    _final_format.require_engine(
        without("full_grid"), _final_format.normalize({"nodata": 0}))


def test_grid_placement_on_the_terrain_lattice():
    planned = plan()
    wire, grid = _final_format.resolve(_final_format.normalize({"nodata": -9999}), planned, 800, 600)
    assert "full_grid" not in wire and wire["overview_resampling"] == "average"
    assert (grid["col_off"], grid["row_off"], grid["width"], grid["height"]) == (40, 24, 300, 280)
    assert grid["transform"] == planned.transform

    wire, grid = _final_format.resolve(
        _final_format.normalize({"nodata": -9999, "grid": "terrain", "overviews": [2, 4]}),
        planned, 800, 600)
    assert wire["full_grid"] == dict(width=800, height=600, row_offset=24, col_offset=40,
                                     transform=[1000.0, 10.0, 0.0, 9000.0, 0.0, -10.0])
    assert wire["overview_factors"] == [2, 4] and grid["transform"] == TERRAIN
    assert grid["window"] == Window(40, 24, 300, 280)

    wire, grid = _final_format.resolve(
        _final_format.normalize({"nodata": -9999, "grid": [32, 16, 400, 300]}), planned, 800, 600)
    assert wire["full_grid"] == dict(width=400, height=300, row_offset=8, col_offset=8,
                                     transform=[1320.0, 10.0, 0.0, 8840.0, 0.0, -10.0])
    assert (grid["col_off"], grid["row_off"]) == (32, 16)
    for outside in ([41, 16, 400, 300], [32, 25, 400, 300], [32, 16, 307, 300],
                    [32, 16, 400, 287], [600, 16, 400, 300], [32, 400, 400, 300]):
        with pytest.raises(FimUnsupportedError, match="contain the mapped window"):
            _final_format.resolve(
                _final_format.normalize({"nodata": -9999, "grid": outside}), planned, 800, 600)


def write_final(path, grid, crs, *, compress="deflate", nodata=-9999.0, block=256,
                overviews=(2, 4), tag=True, tiled=True, dtype="float32", predictor=1):
    extra = dict(tiled=True, blockxsize=block, blockysize=block) if tiled else {}
    with rasterio.open(
        path, "w", driver="GTiff", height=grid["height"], width=grid["width"], count=1,
        dtype=dtype, crs=crs, transform=grid["transform"], nodata=nodata, compress=compress,
        predictor=predictor, **extra,
    ) as target:
        target.write(np.full((grid["height"], grid["width"]), nodata, dtype=dtype), 1)
        if overviews:
            target.build_overviews(list(overviews), Resampling.average)
        if tag:
            target.update_tags(ns="rio_overview", resampling="average")


def header(wire, finite=7, flooded=5, **changes):
    record = {
        "id": "Max", "status": "complete", "pixels": 84000, "products": "native-geotiff/1",
        "depth_finite_pixels": finite, "flooded_pixels": flooded, "write_seconds": 0.25,
        "compression": "DEFLATE", "final_format": json.loads(json.dumps(wire)),
        "depth_final": {"valid_pixels": finite, "tiles": 12, "shared_nodata_tiles": 3, "file_bytes": 900},
        "wse_final": {"valid_pixels": finite, "tiles": 12, "shared_nodata_tiles": 3, "file_bytes": 901},
    }
    record.update(changes)
    return {k: v for k, v in record.items() if v is not ...}


@pytest.mark.parametrize("width,height", [(17, 17), (17, 5), (5, 3), (300, 299)])
def test_odd_sized_overviews_are_checked_by_stored_shape(tmp_path, width, height):
    # Rasterio reports a factor-4 overview of a 17-pixel grid (stored 5 wide) as
    # factor 3; a valid delivery must still pass, and a wrong pyramid must not.
    crs = rasterio.crs.CRS.from_epsg(26915)
    grid = dict(width=width, height=height, transform=rasterio.Affine(10, 0, 0, 0, -10, 0))
    wire = dict(block_size=16, overview_factors=[2, 4], nodata=-9999.0)
    path = tmp_path / "valid.tif"
    write_final(path, grid, crs, block=16, overviews=(2, 4))
    with rasterio.open(path) as image:
        _final_format.check_file(image, wire, grid, crs)
    wrong = tmp_path / "wrong.tif"
    write_final(wrong, grid, crs, block=16, overviews=(2, 8))
    with rasterio.open(wrong) as image, pytest.raises(FimEngineError, match="overviews"):
        _final_format.check_file(image, wire, grid, crs)


@pytest.fixture
def staged(tmp_path):
    planned = plan()
    options = _final_format.normalize({"nodata": -9999, "grid": "terrain", "overviews": [2, 4]})
    final = _final_format.resolve(options, planned, 800, 600)
    source, folder = tmp_path / "engine" / "Max", tmp_path / "delivered"
    source.mkdir(parents=True)
    folder.mkdir()
    return planned, final, source, folder


def test_delivery_accepts_the_requested_format_and_reports_the_delivered_grid(staged):
    planned, final, source, folder = staged
    for name in ("depth", "wse"):
        write_final(source / f"{name}.tif", final[1], planned.crs)
    row = _native_products.deliver(source, folder, "Max", header(final[0]), planned, final)
    assert Path(row["depth_tif"]).name == "09_Max_depth_nudge.tif"
    assert Path(row["wse_tif"]).name == "10_Max_wsel_nudge.tif"
    assert Path(row["depth_tif"]).is_file() and not (source / "depth.tif").exists()
    assert (row["col_off"], row["row_off"], row["width"], row["height"]) == (0, 0, 800, 600)
    assert row["transform"] == tuple(TERRAIN)[:6]
    assert row["status"] == "complete" and row["depth_finite_pixels"] == 7
    assert _final_format.check_header(header(final[0]), final[0])["depth_final"]["tiles"] == 12
    # Bounded row delivery reports no per-file counts.
    assert _final_format.check_header(header(final[0], depth_final=..., wse_final=...), final[0]) == {}


@pytest.mark.parametrize("fault", [
    dict(compress="lzw"), dict(nodata=-9998.0), dict(nodata=float("nan")), dict(block=512),
    dict(overviews=(2,)), dict(overviews=()), dict(tag=False), dict(tiled=False),
    dict(dtype="float64"), dict(predictor=3), dict(shape=(600, 799)), dict(shift=1),
    dict(crs=rasterio.crs.CRS.from_epsg(2277)),
])
def test_delivery_refuses_any_file_that_is_not_the_requested_format(fault, staged):
    planned, final, source, folder = staged
    grid = dict(final[1])
    if "shape" in fault:
        grid["height"], grid["width"] = fault.pop("shape")
    if "shift" in fault:
        grid["transform"] = grid["transform"] * Affine.translation(fault.pop("shift"), 0)
    crs = fault.pop("crs", planned.crs)
    write_final(source / "depth.tif", final[1], planned.crs)
    write_final(source / "wse.tif", grid, crs, **fault)
    with pytest.raises(FimEngineError, match="final-format GeoTIFF differs"):
        _native_products.deliver(source, folder, "Max", header(final[0]), planned, final)
    # Both files are checked before either is moved.
    assert not list(folder.iterdir()) and (source / "depth.tif").is_file()


@pytest.mark.parametrize("changes", [
    dict(final_format=...), dict(compression="LZW"), dict(compression=...),
    dict(final_format={"nodata": -9998.0}), dict(depth_final={"valid_pixels": 6, "tiles": 12,
                                                              "shared_nodata_tiles": 3, "file_bytes": 9}),
    dict(wse_final={"valid_pixels": 7}), dict(depth_final="done"),
])
def test_delivery_refuses_a_completion_record_that_differs_from_the_request(changes, staged):
    planned, final, source, folder = staged
    for name in ("depth", "wse"):
        write_final(source / f"{name}.tif", final[1], planned.crs)
    with pytest.raises(FimEngineError, match="completion"):
        _native_products.deliver(source, folder, "Max", header(final[0], **changes), planned, final)
    assert not list(folder.iterdir())


def test_legacy_native_delivery_refuses_an_unrequested_final_format(staged):
    planned, final, source, folder = staged
    with pytest.raises(FimEngineError, match="unrequested final_format"):
        _native_products.deliver(source, folder, "Max", header(final[0]), planned)


@pytest.fixture
def case():
    filename = os.environ.get("RAS_COMMANDER_SLOPING_CASE")
    if not filename:
        pytest.skip("set RAS_COMMANDER_SLOPING_CASE to a computed 2D model")
    case = json.loads(Path(filename).read_text(encoding="utf-8"))
    from ras_commander.fim import _engine

    method = _engine.engine_method(_engine.find_engine(case["engine"])).get("sloping", {})
    if not method.get("native_final_format"):
        pytest.skip("engine lacks native_final_format")
    return case


def mapped(case, folder, **options):
    selection = {"bbox": case["bbox"]} if case.get("bbox") else {}
    return RasFim.map_sloping_profiles(
        case["hdf"], case["terrain"], folder, engine_path=case["engine"],
        profiles=case["profiles"], threads=2, max_working_mib=case.get("max_working_mib", 4096),
        terrain_crs_fnv1a64=case.get("terrain_crs_fnv1a64"), **selection, **options)


@pytest.mark.parametrize("rows", [0, 64])
def test_real_engine_final_format_equals_the_rasterio_route(case, tmp_path, rows):
    baseline = mapped(case, tmp_path / "rasterio")
    option = {"nodata": -9999.0, "overviews": [2, 4], "grid": "terrain"}
    actual = mapped(case, tmp_path / "final", product_writer="native", row_stream_rows=rows,
                    final_format=option)
    receipt = json.loads((tmp_path / "final" / "fim_manifest.json").read_text())
    assert receipt["options"]["final_format"]["grid"] == "terrain"
    assert receipt["final_format"]["arrays_streamed"] is False
    assert actual.attrs["final_format"]["grid_on_terrain"][:2] == [0, 0]
    with rasterio.open(case["terrain"]) as terrain:
        shape, transform = terrain.shape, terrain.transform
    for a, b in zip(actual.itertuples(), baseline.itertuples(), strict=True):
        assert (a.depth_finite_pixels, a.flooded_pixels) == (b.depth_finite_pixels, b.flooded_pixels)
        assert (a.col_off, a.row_off, a.height, a.width) == (0, 0, *shape)
        for band in ("depth_tif", "wse_tif"):
            with rasterio.open(getattr(a, band)) as final, rasterio.open(getattr(b, band)) as stock:
                assert final.shape == shape and final.transform == transform
                assert final.nodata == -9999 and final.overviews(1) == [2, 4]
                assert final.compression.name == "deflate" and final.block_shapes == [(256, 256)]
                assert final.tags(ns="rio_overview") == {"resampling": "average"}
                # The mapped window keeps the product bits; NaN becomes the nodata value.
                values = stock.read(1)
                expected = np.where(np.isnan(values), np.float32(-9999), values)
                window = Window(b.col_off, b.row_off, b.width, b.height)
                np.testing.assert_array_equal(
                    final.read(1, window=window).view("u4"), expected.view("u4"))
                # Every other pixel is nodata: GDAL's coarsest overview sees no more
                # valid area than the window can cover.
                coarse = final.read(1, out_shape=(-(-shape[0] // 4), -(-shape[1] // 4)))
                rows_valid, cols_valid = np.nonzero(coarse != -9999)
                if len(rows_valid):
                    assert rows_valid.min() >= b.row_off // 4 - 1
                    assert rows_valid.max() <= (b.row_off + b.height) // 4 + 1
                    assert cols_valid.min() >= b.col_off // 4 - 1
                    assert cols_valid.max() <= (b.col_off + b.width) // 4 + 1
        counts = receipt["final_format"]["products"]
        if not rows:
            assert all(
                counts[a.profile][key]["valid_pixels"] == a.depth_finite_pixels
                for key in ("depth_final", "wse_final")
            )


def test_real_engine_refuses_a_nodata_value_that_a_valid_pixel_holds(case, tmp_path):
    baseline = mapped(case, tmp_path / "rasterio")
    with rasterio.open(baseline.iloc[0].depth_tif) as stock:
        values = stock.read(1)
    collision = float(values[np.isfinite(values)][0])
    with pytest.raises(FimUnsupportedError, match="cannot mark invalid pixels"):
        mapped(case, tmp_path / "final", product_writer="native",
               final_format={"nodata": collision})
    assert not list((tmp_path / "final").glob("*.tif"))
    receipt = json.loads((tmp_path / "final" / "fim_manifest.json").read_text())
    assert receipt["status"] == "aborted"
