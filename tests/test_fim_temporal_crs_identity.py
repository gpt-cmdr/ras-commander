"""Explicit terrain identity for temporal maps, without CRS relabelling."""
import json
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from affine import Affine
from pyproj import CRS

from ras_commander.fim import RasFim, FimEngineError, FimUnsupportedError
from ras_commander.fim import _engine, _whole_simulation


def test_public_temporal_api_forwards_explicit_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(_whole_simulation, "map_whole_simulation", lambda *a, **kw: kw)
    options = RasFim.map_whole_simulation("model.hdf", "terrain.tif", tmp_path,
        threshold=.5, terrain_crs_fnv1a64="verified-hash")
    assert options["terrain_crs_fnv1a64"] == "verified-hash"


def test_explicit_hash_keeps_model_terrain_crs_checks(tmp_path, monkeypatch):
    path = tmp_path / "terrain.tif"
    transform = Affine(1, 0, 0, 0, -1, 4)
    with rasterio.open(path, "w", driver="GTiff", width=4, height=4,
                       count=1, dtype="float32", crs="EPSG:2871", transform=transform,
                       nodata=-9999) as dst:
        dst.write(np.zeros((4, 4), dtype="f4"), 1)
    info = dict(width=4, height=4, geo_transform=list(transform.to_gdal()),
                epsg=None, crs_wkt_fnv1a64="verified-hash",
                crs={"wkt": CRS.from_epsg(2226).to_wkt()})
    monkeypatch.setattr(_engine, "run_engine", lambda *a, **kw:
        CompletedProcess([], 0, json.dumps(info), ""))
    with pytest.raises(FimUnsupportedError, match="differs"):
        _engine.terrain_identity(Path("engine"), path, "EPSG:2871")
    accepted = _engine.terrain_identity(Path("engine"), path, "EPSG:2871", "verified-hash")
    assert accepted["epsg"] == 2871
    assert accepted["crs_identity"] == {"kind": "caller_verified_wkt", "fnv1a64": "verified-hash"}
    with pytest.raises(FimEngineError, match="does not match"):
        _engine.terrain_identity(Path("engine"), path, "EPSG:2871", "wrong")
    with pytest.raises(FimUnsupportedError, match="results CRS must equal"):
        _engine.terrain_identity(Path("engine"), path, "EPSG:2226", "verified-hash")


def test_temporal_run_forwards_hash_timeout_and_records_identity(tmp_path, monkeypatch):
    class StopAfterIdentity(Exception):
        pass
    import geopandas as gpd
    from shapely.geometry import box
    cells = gpd.GeoDataFrame({"geometry": [box(0, 0, 1, 1)]}, crs="EPSG:2871")
    expected = {"epsg": 2871, "crs_identity": {"kind": "caller_verified_wkt", "fnv1a64": "verified-hash"}}
    calls = []
    def identity(*args, **kwargs):
        calls.append((args, kwargs))
        return expected
    monkeypatch.setattr(_engine, "terrain_identity", identity)
    def stop(*args):
        raise StopAfterIdentity
    monkeypatch.setattr(_whole_simulation, "_write_geometry", stop)
    details = {}
    with pytest.raises(StopAfterIdentity):
        _whole_simulation._run(Path("engine"), None, Path("terrain"), cells,
            SimpleNamespace(cell_positions=[0]), [0.], (), .5, False, None,
            1, 1, 64, 7.5, tmp_path, {}, details, {}, "EPSG:2871",
            None, None, None, terrain_crs_fnv1a64="verified-hash")
    assert calls[0][0][-1] == "verified-hash"
    assert calls[0][1] == {"timeout": 7.5}
    assert details["terrain_identity"] == expected
