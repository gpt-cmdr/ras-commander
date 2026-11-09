"""Opt-in terrain source CRS identity; the engine itself is never executed."""

import json
from pathlib import Path
from subprocess import CompletedProcess

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from pyproj import CRS
from pyproj.crs import BoundCRS
from pyproj.crs.coordinate_operation import ToWGS84Transformation

from ras_commander.fim import _engine
from ras_commander.fim.errors import FimEngineError, FimUnsupportedError


def bound(source, shift=1.25):
    return BoundCRS(source_crs=source, target_crs=CRS.from_epsg(4326),
        transformation=ToWGS84Transformation(source.geodetic_crs,
            x_axis_translation=shift, y_axis_translation=2 * shift, z_axis_translation=3 * shift))


@pytest.fixture
def terrain(tmp_path, monkeypatch):
    path = tmp_path / "terrain.tif"
    with rasterio.open(path, "w", driver="GTiff", width=257, height=256, count=1,
            dtype="float32", crs="EPSG:6588", transform=from_origin(1000, 2000, 1, 1),
            nodata=-9999, tiled=True, blockxsize=256, blockysize=256) as raster:
        raster.write(np.ones((256, 257), dtype="float32"), 1)
    with rasterio.open(path) as raster:
        info = {"width": raster.width, "height": raster.height,
            "geo_transform": list(raster.transform.to_gdal()), "epsg": 6588,
            "crs_wkt_fnv1a64": "original-raw-engine-hash"}
    calls = []
    def run(command, label, timeout=None):
        calls.append((command, label, timeout))
        return CompletedProcess(command, 0, json.dumps(info), "")
    monkeypatch.setattr(_engine, "run_engine", run)
    return path, info, calls


def test_default_refuses_bound_model_and_emits_no_optin_provenance(terrain):
    path, _, _ = terrain
    with pytest.raises(FimUnsupportedError, match="results CRS"):
        _engine.terrain_identity(Path("engine"), path, bound(CRS.from_epsg(6588)))
    result = _engine.terrain_identity(Path("engine"), path, "EPSG:6588")
    assert set(result) == {"path", "epsg", "crs_identity"}
    assert result["crs_identity"] == {"kind": "epsg"}


@pytest.mark.parametrize("shift", [0, 1.25])
def test_optin_accepts_same_actual_source_and_preserves_unapplied_model_binding(terrain, shift):
    path, info, calls = terrain
    model = bound(CRS.from_epsg(6588), shift)
    info["crs"] = {"wkt": model.to_wkt()}
    result = _engine.terrain_identity(Path("engine"), path, model,
        timeout=7.5, source_crs_identity=True)
    assert result["epsg"] == 6588 and result["crs_identity"] == {"kind": "epsg"}
    record = result["crs_provenance"]
    assert CRS.from_wkt(record["results"]["original_wkt"]) == model
    assert record["results"]["binding_operation"] == model.coordinate_operation.to_json_dict()
    assert CRS.from_wkt(record["engine"]["original_wkt"]) == model
    assert record["engine_crs_wkt_fnv1a64"] == "original-raw-engine-hash"
    assert len(calls) == 1 and calls[0][2] == 7.5


@pytest.mark.parametrize("epsg", [2278, 6587, 4326])
def test_optin_refuses_different_actual_source_datum_units_or_projection(terrain, epsg):
    path, _, _ = terrain
    with pytest.raises(FimUnsupportedError, match="results CRS"):
        _engine.terrain_identity(Path("engine"), path, bound(CRS.from_epsg(epsg)), source_crs_identity=True)


def test_optin_preserves_identified_epsg_authority_over_inconsistent_legacy_wkt(terrain):
    path, info, _ = terrain
    info["crs"] = {"wkt": bound(CRS.from_epsg(2278)).to_wkt()}
    accepted = _engine.terrain_identity(Path("engine"), path, "EPSG:6588", source_crs_identity=True)
    assert accepted["crs_identity"] == {"kind": "epsg"}
    assert CRS.from_wkt(accepted["crs_provenance"]["engine"]["original_wkt"]).source_crs == CRS.from_epsg(2278)


def test_known_epsg_does_not_gain_a_legacy_wkt_parser_requirement(terrain):
    path, info, _ = terrain
    info["crs"] = {"wkt": "legacy WKT not understood by this parser"}
    accepted = _engine.terrain_identity(Path("engine"), path, "EPSG:6588", source_crs_identity=True)
    assert accepted["crs_identity"] == {"kind": "epsg"}
    assert accepted["crs_provenance"]["engine"] is None
    assert accepted["crs_provenance"]["engine_wkt_parse_error"]


def test_unknown_unpinned_engine_still_requires_equivalent_source_wkt(terrain):
    path, info, _ = terrain
    info["epsg"] = None
    info["crs"] = {"wkt": bound(CRS.from_epsg(2278)).to_wkt()}
    with pytest.raises(FimUnsupportedError, match="engine terrain source CRS"):
        _engine.terrain_identity(Path("engine"), path, "EPSG:6588", source_crs_identity=True)


def test_unknown_engine_epsg_still_requires_wkt_or_verified_hash(terrain):
    path, info, _ = terrain
    info["epsg"] = None
    with pytest.raises(FimUnsupportedError, match="exposed no WKT"):
        _engine.terrain_identity(Path("engine"), path, "EPSG:6588", source_crs_identity=True)
    accepted = _engine.terrain_identity(Path("engine"), path, "EPSG:6588",
        "original-raw-engine-hash", source_crs_identity=True)
    assert accepted["crs_identity"] == {"kind": "caller_verified_wkt", "fnv1a64": "original-raw-engine-hash"}
    assert accepted["crs_provenance"]["engine"] is None
    with pytest.raises(FimEngineError, match="does not match"):
        _engine.terrain_identity(Path("engine"), path, "EPSG:6588", "wrong", source_crs_identity=True)


def test_unknown_engine_epsg_accepts_equivalent_bound_wkt_with_raw_hash(terrain):
    path, info, _ = terrain
    info["epsg"] = None
    info["crs"] = {"wkt": bound(CRS.from_epsg(6588)).to_wkt()}
    accepted = _engine.terrain_identity(Path("engine"), path, "EPSG:6588", source_crs_identity=True)
    assert accepted["epsg"] == 6588
    assert accepted["crs_identity"]["fnv1a64"] == info["crs_wkt_fnv1a64"]


@pytest.mark.parametrize("legacy_wkt", [CRS.from_epsg(2278).to_wkt(), "legacy WKT not understood by this parser"])
def test_verified_unknown_engine_pin_precedes_legacy_wkt_semantic_inference(terrain, legacy_wkt):
    path, info, _ = terrain
    info["epsg"] = None
    info["crs"] = {"wkt": legacy_wkt}
    accepted = _engine.terrain_identity(Path("engine"), path, "EPSG:6588",
        info["crs_wkt_fnv1a64"], source_crs_identity=True)
    assert accepted["epsg"] == 6588
    assert accepted["crs_identity"] == {"kind": "caller_verified_wkt", "fnv1a64": info["crs_wkt_fnv1a64"]}
    assert accepted["crs_provenance"]["engine_wkt"] == legacy_wkt
    with pytest.raises(FimEngineError, match="does not match"):
        _engine.terrain_identity(Path("engine"), path, "EPSG:6588", "wrong", source_crs_identity=True)


def test_verified_pin_never_overrides_an_identified_engine_epsg_mismatch(terrain):
    path, info, _ = terrain
    info["epsg"] = 2278
    info["crs"] = {"wkt": CRS.from_epsg(2278).to_wkt()}
    with pytest.raises(FimEngineError, match="EPSG differs"):
        _engine.terrain_identity(Path("engine"), path, "EPSG:6588",
            info["crs_wkt_fnv1a64"], source_crs_identity=True)


def test_optin_preserves_known_epsg_precedence_over_unused_raw_pin(terrain):
    path, info, _ = terrain
    accepted = _engine.terrain_identity(Path("engine"), path, "EPSG:6588", "unused-legacy-pin", source_crs_identity=True)
    assert accepted["crs_identity"] == {"kind": "epsg"}
    assert accepted["crs_provenance"]["terrain_crs_fnv1a64_requested"] == "unused-legacy-pin"


def test_bound_tiff_same_source_is_admitted_only_with_explicit_optin(terrain, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    path, info, _ = terrain
    original = bound(CRS.from_epsg(6588))
    open_raster = rasterio.open
    # This GDAL writer canonicalizes known-EPSG bindings when serializing a
    # synthetic TIFF. Exercise the reader's possible BoundCRS definition while
    # retaining actual TIFF dimensions/transform and never sampling pixels.
    @contextmanager
    def bound_header(filename):
        with open_raster(filename) as raster:
            yield SimpleNamespace(crs=original, transform=raster.transform,
                width=raster.width, height=raster.height)
    monkeypatch.setattr(rasterio, "open", bound_header)
    with pytest.raises(FimUnsupportedError):
        _engine.terrain_identity(Path("engine"), path, "EPSG:6588")
    info["crs"] = {"wkt": original.to_wkt()}
    accepted = _engine.terrain_identity(Path("engine"), path, "EPSG:6588", source_crs_identity=True)
    assert accepted["epsg"] == 6588
    assert CRS.from_wkt(accepted["crs_provenance"]["rasterio"]["original_wkt"]) == original
