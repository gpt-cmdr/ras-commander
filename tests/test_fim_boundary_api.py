"""Boundary API protocol checks; numerical qualification remains engine-backed."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander.fim import _boundary
from ras_commander.fim.errors import FimEngineError, FimUnsupportedError


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box
    from ras_commander.fim.RasFim import RasFim
    hdf, terrain_hdf, engine = [tmp_path / name for name in ("plan.hdf", "terrain.hdf", "engine")]
    for path in (hdf, terrain_hdf, engine):
        path.write_bytes(b"input")
    terrain = tmp_path / "terrain.tif"
    with rasterio.open(terrain, "w", driver="GTiff", count=1, width=256, height=256,
                       dtype="float32", crs="EPSG:32615", transform=from_origin(0, 256, 1, 1),
                       tiled=True, blockxsize=256, blockysize=256, nodata=-9999) as raster:
        raster.write(np.ones((256, 256), dtype="float32"), 1)
    cells = gpd.GeoDataFrame({"mesh_name": ["mesh", "mesh"], "cell_id": [0, 1]},
                             geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)], crs="EPSG:32615")
    state = SimpleNamespace(failure=None, options=None, request=None)
    method = {"method_id": _boundary.METHOD_ID, "native_vector_parity": False, "coordinate_precision": 0.001}
    monkeypatch.setattr(_boundary._engine, "find_engine", lambda *a: engine)
    monkeypatch.setattr(_boundary._engine, "engine_method", lambda *a: {"boundary": method})

    class Context:
        def __init__(self, *args, **options):
            state.options = options
            self._temporary = tempfile.TemporaryDirectory()
            self._cells, self._meshes = cells, [{"mesh_name": "mesh"}]
            self._mesh_files = [str(Path(self._temporary.name) / "mesh.json")]
            self._units = {name: {"id": name, "values_files": ["values.bin"]} for name in options["profiles"]}
            self._terrain_identity = {"epsg": 32615, "crs_identity": {}}
            self._terrain_transform = [0, 1, 0, 256, 0, -1]
            self._info = {"planned_prepared_bytes": 1024, "prepare_seconds": 0.01}

        @property
        def info(self):
            return self._info

        def _check_sources(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self._temporary.cleanup()

    monkeypatch.setattr(RasFim, "prepare_sloping_model", Context)
    monkeypatch.setattr(_boundary, "stage_boundary_terrain", lambda *a, **k: {"selected_tiles": k["selected_tiles"]})

    def run(engine, request, output, timeout):
        state.request = json.loads(request.read_text())
        assert state.request["model"]["owner_cells"] == [[0, 0], [0, 1]]
        assert state.request["model"]["stream_outputs"] is False
        assert (request.parent / "boundary-cells.wkb").is_file()
        output.mkdir()
        profiles = []
        for index, profile in enumerate(state.request["model"]["profiles"]):
            name = profile["id"]
            ring = [[0,0],[10,0],[10,10],[0,10],[0,0]]
            if state.failure == "invalid" or (state.failure == "late" and index):
                ring = [[0,0],[10,10],[0,10],[10,0],[0,0]]
            if state.failure == "nonfinite":
                ring[1][0] = float("nan")
            product = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:32615"}},
                       "features": [{"type": "Feature", "properties": {"profile_id": name,
                           "interpolation": state.request["interpolation"], "method_id": _boundary.METHOD_ID,
                           "native_vector_parity": False}, "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}}]}
            if state.failure == "empty":
                product["features"][0]["geometry"]["coordinates"] = []
            (output / f"{name}.geojson").write_text(json.dumps(product))
            profiles.append({"id": name, "status": "complete", "file": f"{name}.geojson",
                             "polygon_count": 1, "hole_count": 0, "vertex_count": 5, "area": 100.0})
            if state.failure == "empty":
                profiles[-1].update(status="empty", polygon_count=0, vertex_count=0, area=0.0)
        report = {"schema": "ras-commander-boundary-report/1", "status": "complete", "method": method,
                  "interpolation": state.request["interpolation"], "profiles": profiles,
                  "threads": state.request["model"]["threads"], "effective_inflight_profiles": 1,
                  "planned_shared_bytes": 1024, "per_profile_contour_budget_bytes": 1024,
                  "prepare_seconds": 0.01, "render_seconds": 0.02}
        if state.failure == "admission":
            report["per_profile_contour_budget_bytes"] = state.request["model"]["max_working_bytes"]
        if state.failure == "concurrency":
            report["effective_inflight_profiles"] = True
        if state.failure == "profile":
            profiles[0]["id"] = "other"
        if state.failure == "path":
            profiles[0]["file"] = "../escape.geojson"
        if state.failure == "source":
            stat = hdf.stat()
            os.utime(hdf, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
        if state.failure == "missing":
            return 0, "diagnostic"
        if state.failure == "report_type":
            report = []
        (output / "report.json").write_text(json.dumps(report))
        if state.failure == "timeout":
            raise subprocess.TimeoutExpired("engine", timeout, stderr="timeout diagnostic")
        return (1 if state.failure == "exit" else 0), "engine diagnostic"

    monkeypatch.setattr(_boundary, "_run_boundary_engine", run)
    state.args = (hdf, terrain, tmp_path / "products")
    state.terrain_hdf = terrain_hdf
    return state


def test_boundary_adapter_delivers_global_model_request_and_method_evidence(adapter):
    result = _boundary.map_inundation_boundaries(*adapter.args, terrain_hdf=adapter.terrain_hdf,
                                               profiles={"max": "Max", "time": 3}, bbox=[0, 0, 20, 20])
    assert list(result.columns) == _boundary.COLUMNS
    assert list(result.profile) == ["max", "time"]
    assert result.area.tolist() == [100.0, 100.0]
    assert adapter.options["native_session"] is False
    assert adapter.request["model"]["window"] == [0, 0, 256, 256]
    assert adapter.request["terrain_metadata"]["selected_tiles"] == [0]
    assert adapter.request["model"]["aoi_file"] == "boundary-aoi.wkb"
    assert result.attrs["method_id"] == _boundary.METHOD_ID
    assert result.attrs["native_vector_parity"] is False
    assert result.attrs["performance"]["total_seconds"] > 0
    manifest = json.loads((adapter.args[2] / "boundary_manifest.json").read_text())
    assert manifest["status"] == "complete"


def test_empty_profile_is_a_valid_empty_multipolygon(adapter):
    adapter.failure = "empty"
    frame = _boundary.map_inundation_boundaries(*adapter.args, terrain_hdf=adapter.terrain_hdf)
    assert frame.status.tolist() == ["empty"]
    assert frame.polygons.tolist() == [0] and frame.area.tolist() == [0.0]
    assert json.loads(Path(frame.boundary_geojson.iloc[0]).read_text())["features"][0]["geometry"]["coordinates"] == []


@pytest.mark.parametrize("failure", ["profile", "path", "invalid", "nonfinite", "late", "source", "missing", "report_type", "exit", "timeout", "admission", "concurrency"])
def test_protocol_failure_cleans_all_delivered_products_and_records_abort(adapter, failure):
    adapter.failure = failure
    with pytest.raises(FimEngineError):
        _boundary.map_inundation_boundaries(*adapter.args, terrain_hdf=adapter.terrain_hdf,
                                           profiles={"first": "Max", "second": 1}, timeout=1)
    assert not list(adapter.args[2].glob("*.geojson"))
    manifest = json.loads((adapter.args[2] / "boundary_manifest.json").read_text())
    assert manifest["status"] == "aborted" and manifest["products"] == []


@pytest.mark.parametrize("options", [{"interpolation": "pretty"}, {"threads": True}, {"threads": 65},
                                    {"max_inflight_profiles": 0}, {"max_working_mib": 0},
                                    {"timeout": float("nan")}, {"profiles": {"CON": "Max"}}])
def test_invalid_controls_have_no_output_side_effect(adapter, options):
    with pytest.raises(ValueError):
        _boundary.map_inundation_boundaries(*adapter.args, terrain_hdf=adapter.terrain_hdf, **options)
    assert not adapter.args[2].exists()


def test_missing_boundary_capability_refuses_before_prepare(adapter, monkeypatch):
    monkeypatch.setattr(_boundary._engine, "engine_method", lambda *a: {"sloping": {}})
    with pytest.raises(FimEngineError, match="boundary capability"):
        _boundary.map_inundation_boundaries(*adapter.args, terrain_hdf=adapter.terrain_hdf)
    assert adapter.options is None


def test_geojson_admission_precedes_parsing(tmp_path, monkeypatch):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * 100)
    monkeypatch.setattr(json, "loads", lambda *a, **k: pytest.fail("parsed unadmitted file"))
    with pytest.raises(FimEngineError, match="admission"):
        _boundary._load_json(path, 99)


def test_tile_selection_keeps_neighbor_halo_and_rejects_outside():
    assert _boundary._selected_tiles([512, 512], [0, 1, 0, 512, 0, -1],
        __import__("shapely").box(256, 256, 257, 257)) == [0, 1, 2, 3]
    with pytest.raises(FimUnsupportedError, match="does not intersect"):
        _boundary._selected_tiles([256, 256], [0, 1, 0, 256, 0, -1], __import__("shapely").box(500, 500, 510, 510))


def test_optional_real_boundary_engine(tmp_path):
    hdf, tif, terrain_hdf, engine = [os.getenv(f"RAS_FIM_BOUNDARY_{key}") for key in ("PLAN", "TIFF", "TERRAIN_HDF", "ENGINE")]
    if not all((hdf, tif, terrain_hdf, engine)):
        pytest.skip("Set public plan/terrain/engine paths for real boundary qualification")
    result = _boundary.map_inundation_boundaries(hdf, tif, tmp_path / "products",
                                               terrain_hdf=terrain_hdf, engine_path=engine)
    assert len(result) == 1 and result.status.iloc[0] in ("complete", "empty")
