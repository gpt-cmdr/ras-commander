"""Native-order boundary transport and delivery contracts; no model execution."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander.fim import _boundary, _boundary_native as native
from ras_commander.fim.errors import FimEngineError, FimUnsupportedError


@pytest.fixture
def mapping(tmp_path, monkeypatch):
    from ras_commander.fim.RasFim import RasFim
    from ras_commander.hdf.HdfBase import HdfBase
    from pyproj import CRS

    hdf, terrain_hdf, engine = (tmp_path / name for name in ("source.hdf", "terrain.hdf", "engine.exe"))
    for path in (hdf, terrain_hdf, engine):
        path.write_bytes(b"source")
    terrain = tmp_path / "terrain.tif"
    with rasterio.open(terrain, "w", driver="GTiff", width=512, height=256, count=1,
            dtype="float32", tiled=True, blockxsize=256, blockysize=256,
            crs="EPSG:6588", transform=from_origin(0, 256, 1, 1), nodata=-9999) as out:
        out.write(np.ones((256, 512), dtype="float32"), 1)
    state = SimpleNamespace(dimension="1d", failure=None, request=None, prepared=False, cleaned=False)
    method = {"method_id": native.METHOD_ID, "native_vector_parity": False}
    registry = {"native_boundary": method,
        "capabilities_schema": "ras-commander-fast-map-capabilities/1",
        "capabilities": [{"key": "native_boundary", "method_id": native.METHOD_ID,
            "request_schemas": [native.REQUEST_SCHEMA], "cli_command": "boundary",
            "api_contract": "stable", "intended_use": "mapping", "flags": method,
            "numerical_qualification": {"status": "unqualified", "flags": {}}}]}
    state.registry = registry
    scope = SimpleNamespace(dimension="1d", geometry_path=None, storage_area_names=(),
        to_dict=lambda: {"dimension": state.dimension})
    def inspect(*_):
        scope.dimension = state.dimension
        return scope
    monkeypatch.setattr(RasFim, "inspect_model_scope", inspect)
    monkeypatch.setattr(HdfBase, "get_projection", lambda *_: CRS.from_epsg(6588).to_wkt())
    monkeypatch.setattr(HdfBase, "get_result_unit_metadata", lambda *_: {"unit_system": "US Customary"})
    monkeypatch.setattr(native._engine, "find_engine", lambda *_: engine)
    monkeypatch.setattr(native._engine, "engine_method", lambda *_: registry)
    monkeypatch.setattr(native._engine, "terrain_identity", lambda *_args, **_kwargs:
        {"path": str(terrain), "epsg": 6588, "crs_identity": {"kind": "epsg"}})
    @contextmanager
    def prepare(hdf, terrain, root, selected, scope, *args):
        state.prepared = True
        payload = root / "payload.bin"
        payload.write_bytes(b"payload")
        mesh = ({"geometry_file": str(payload), "mesh_files": [str(payload)],
            "owner_cells": [[0, 0]], "profiles": [{"id": name, "values_files": [str(payload)]}
                for name in selected]} if scope.dimension in ("2d", "mixed_1d_2d") else None)
        xs = ({"point_count": 3, "points_file": str(payload),
            "profiles": [{"id": name, "levels_file": str(payload)} for name in selected]}
            if scope.dimension in ("1d", "mixed_1d_2d") else None)
        storage = ({"polygons": str(payload), "count": 1, "levels": [str(payload) for _ in selected]}
                   if scope.dimension in ("1d", "storage_only") else None)
        try:
            yield {"mesh": mesh, "xs": xs, "storage": storage, "receipt": {"test_prepared": True},
                "retained": 1024, "check": lambda: None}
            if state.failure == "receipt":
                raise FimUnsupportedError("receipt changed after engine use")
        finally:
            state.cleaned = True
    monkeypatch.setattr(native, "_prepare", prepare)
    def stage(*args, **kwargs):
        state.selected_tiles_requested = None
        state.terrain_staging_options = kwargs
        paths = [terrain] + getattr(state, "extra_terrains", [])
        records = [{"path": str(path), "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns, "sha256": native._one_d.digest(path),
            "effective_index": index, "raw_group_name": f"source-{index}",
            "native_group_index": index, "raw_priority": index}
            for index, path in enumerate(paths)]
        metadata = {"selected_tiles": [0, 1], "scope": "complete-original-terrain",
                    "shape": [256, 512], "transform": [0, 1, 0, 256, 0, -1],
                    "stitch_points": {"path": "global-stitch.bin"}, "stitch_triangles": None}
        result = {"terrain_metadata": metadata, "crs_identity": {"kind": "epsg"},
            "additional_terrains": [{"terrain": str(path), "crs_identity": {"kind": "epsg"},
                "terrain_metadata": {**metadata, "transform": [512 * index, 1, 0, 256, 0, -1],
                    "stitch_points": None}} for index, path in enumerate(paths) if index],
            "source_identities": records,
            "terrain_hdf_identity": {"path": str(terrain_hdf), "size": terrain_hdf.stat().st_size,
                "mtime_ns": terrain_hdf.stat().st_mtime_ns, "sha256": native._one_d.digest(terrain_hdf)},
            "staged_bytes": 1024}
        state.terrain_receipt = result
        if state.failure == "terrain_receipt":
            records[0]["effective_index"] = 1
        if state.failure == "terrain_pre_engine":
            stat = paths[-1].stat()
            paths[-1].write_bytes(b"change")
            os.utime(paths[-1], ns=(stat.st_atime_ns, stat.st_mtime_ns))
        return result
    monkeypatch.setattr(native, "stage_native_terrain_sources", stage)

    def run(engine, request, output, timeout):
        state.request = json.loads(request.read_text())
        output.mkdir()
        units = []
        for index, profile in enumerate(state.request["model"]["profiles"]):
            name = profile["id"]
            ring = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
            if (state.failure == "late" and index) or name in getattr(state, "invalid_profiles", set()):
                ring = [[0, 0], [10, 10], [0, 10], [10, 0], [0, 0]]
            product = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:6588"}},
                "features": [{"type": "Feature", "properties": {"profile_id": name,
                    "interpolation": state.request["interpolation"], "method_id": native.METHOD_ID,
                    "native_vector_parity": False}, "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}}]}
            unit = {"id": name, "file": f"{name}.geojson", "status": "complete",
                "polygon_count": 1, "hole_count": 0, "vertex_count": 5, "area": 100.}
            if state.failure == "empty":
                product["features"][0]["geometry"]["coordinates"] = []
                unit.update(status="empty", polygon_count=0, vertex_count=0, area=0.)
            if state.failure == "product_method":
                product["features"][0]["properties"]["method_id"] = _boundary.METHOD_ID
            (output / f"{name}.geojson").write_text(json.dumps(product))
            units.append(unit)
        report = {"schema": "ras-commander-boundary-report/1", "status": "complete", "method": method,
            "interpolation": state.request["interpolation"], "profiles": units,
            "threads": state.request["model"]["threads"], "effective_inflight_profiles": 1,
            "planned_shared_bytes": 1024, "per_profile_contour_budget_bytes": 1024,
            "prepare_seconds": 0.01, "render_seconds": 0.02}
        if state.failure == "path": units[0]["file"] = "../escape.geojson"
        if state.failure == "count": units[0]["vertex_count"] = 6
        if state.failure == "area": units[0]["area"] = 200.
        if state.failure == "profiles": units[0]["id"] = "other"
        if state.failure == "report_method": report["method"] = {"method_id": _boundary.METHOD_ID}
        if state.failure == "concurrency": report["effective_inflight_profiles"] = True
        if state.failure == "budget": report["planned_shared_bytes"] = state.request["model"]["max_working_bytes"]
        if state.failure == "source":
            stat = hdf.stat()
            hdf.write_bytes(b"change")
            os.utime(hdf, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        if state.failure == "terrain_after_engine":
            path = state.extra_terrains[-1]
            stat = path.stat()
            path.write_bytes(b"change")
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        if state.failure == "report_type": report = []
        if state.failure not in ("missing", "exit_missing"):
            (output / "report.json").write_text(json.dumps(report))
        if state.failure == "timeout": raise subprocess.TimeoutExpired("engine", timeout, stderr="bounded diagnostics")
        if state.failure == "interrupt": raise KeyboardInterrupt("owned interrupt")
        return (99 if state.failure == "exit_missing" else 1 if state.failure == "exit" else 0), "bounded diagnostics"
    monkeypatch.setattr(_boundary, "_run_boundary_engine", run)
    state.args = (hdf, terrain, tmp_path / "output")
    state.terrain_hdf = terrain_hdf
    return state


def invoke(mapping, **kwargs):
    return native.map_native_boundaries(*mapping.args, terrain_hdf=mapping.terrain_hdf,
        allow_unqualified=True, **kwargs)


def test_default_gate_is_before_engine_files_or_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(native._engine, "find_engine", lambda *_: pytest.fail("engine lookup before gate"))
    with pytest.raises(FimUnsupportedError, match="unqualified"):
        native.map_native_boundaries("missing.hdf", "missing.tif", tmp_path / "output", terrain_hdf="missing.hdf")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("schemas", [[], ["ras-commander-boundary-request/1"]])
def test_schema_mismatch_refuses_before_preparation_or_output(mapping, schemas):
    mapping.registry["capabilities"][0]["request_schemas"] = schemas
    with pytest.raises(FimEngineError, match="request|schemas"):
        invoke(mapping)
    assert not mapping.prepared
    assert not mapping.args[2].exists()


@pytest.mark.parametrize("dimension", ["1d", "mixed_1d_2d", "2d", "storage_only"])
def test_native_schema_scope_profiles_aoi_and_provenance(mapping, dimension):
    mapping.dimension = dimension
    frame = invoke(mapping, profiles={"maximum": "Max", "saved": 7}, threads=4,
        max_inflight_profiles=2, bbox=[255.5, 2, 256.5, 20])
    request = mapping.request
    assert request["schema"] == native.REQUEST_SCHEMA
    assert request["contour_method"] == native.METHOD_ID
    assert request["terrain_metadata"]["selected_tiles"] == [0, 1]
    assert request["additional_terrains"] == []
    assert mapping.selected_tiles_requested is None
    assert request["model"]["window"] == [0, 0, 512, 256]
    assert "aoi_file" not in request["model"]
    assert ("one_d" in request) == (dimension in ("1d", "mixed_1d_2d"))
    if dimension in ("1d", "storage_only"):
        assert request["model"]["geometry_file"] == ""
        assert request["model"]["mesh_files"] == []
        assert request["model"]["owner_cells"] == []
        assert all(p["values_files"] == [] for p in request["model"]["profiles"])
        assert request["model"]["storage_area_count"] == 1
    assert frame.profile.tolist() == ["maximum", "saved"]
    assert frame.crs.tolist() == ["EPSG:6588"] * 2
    assert frame.attrs["method_id"] == native.METHOD_ID
    assert frame.attrs["qualified"] is False and frame.attrs["native_vector_parity"] is False
    assert frame.attrs["aoi_clipping_method"] == native.AOI_CLIPPING_METHOD
    manifest = json.loads(Path(frame.attrs["manifest"]).read_text())
    assert manifest["status"] == "complete" and manifest["request_schema"] == native.REQUEST_SCHEMA
    assert manifest["sources"]["hdf"]["sha256"]
    assert manifest["terrain_source_receipt"]["source_identities"][0]["effective_index"] == 0
    assert manifest["aoi"]["clip_crs"] == "EPSG:6588"
    assert manifest["aoi"]["clip_geometry_wkb_hex"]
    assert manifest["aoi_clipping_method"] == native.AOI_CLIPPING_METHOD
    assert [unit["polygons"] for unit in manifest["full_engine_products"]] == [1, 1]
    assert mapping.cleaned


@pytest.mark.parametrize("failure", ["path", "count", "area", "profiles", "report_method",
    "product_method", "concurrency", "budget", "source", "report_type", "missing", "timeout", "exit", "exit_missing", "late", "receipt"])
def test_protocol_and_binding_failures_clean_all_products(mapping, failure):
    mapping.failure = failure
    with pytest.raises((FimEngineError, FimUnsupportedError)):
        invoke(mapping, profiles={"first": "Max", "second": 7}, timeout=1)
    assert not list(mapping.args[2].glob("*.geojson"))
    manifest = json.loads((mapping.args[2] / "boundary_manifest.json").read_text())
    assert manifest["status"] == "aborted" and manifest["products"] == []
    assert mapping.cleaned


def test_interrupt_cleans_owned_outputs_and_aborts_manifest(mapping):
    mapping.failure = "interrupt"
    with pytest.raises(KeyboardInterrupt): invoke(mapping)
    assert not list(mapping.args[2].glob("*.geojson"))
    assert json.loads((mapping.args[2] / "boundary_manifest.json").read_text())["status"] == "aborted"


def test_empty_native_boundary_is_explicit(mapping):
    mapping.failure = "empty"
    result = invoke(mapping)
    assert result.status.tolist() == ["empty"] and result.area.tolist() == [0.]


def test_aoi_never_prunes_native_predecessor_tile_or_global_ring_order(mapping):
    invoke(mapping, bbox=[1, 1, 5, 5])
    assert mapping.selected_tiles_requested is None
    assert mapping.request["terrain_metadata"]["selected_tiles"] == [0, 1]
    assert mapping.request["model"]["window"] == [0, 0, 512, 256]
    assert "aoi_file" not in mapping.request["model"]


def test_fractional_angled_aoi_and_hole_use_exact_unrounded_geos_delivery(mapping):
    from shapely.geometry import MultiPolygon, Polygon, shape
    outer = [(-1.123456789, 0.123456789), (11.23456789, 1.23456789),
             (9.87654321, 11.11111111), (-0.123456789, 9.87654321)]
    hole = [(3.1111111, 3.2222222), (5.9999999, 3.4444444),
            (5.7777777, 5.8888888), (3.3333333, 5.6666666)]
    aoi = Polygon(outer, [hole])
    frame = invoke(mapping, polygon=aoi, aoi_crs="EPSG:6588")
    payload = json.loads(Path(frame.boundary_geojson.iloc[0]).read_text())
    actual = shape(payload["features"][0]["geometry"])
    full = MultiPolygon([Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])])
    expected = full.intersection(aoi)
    if expected.geom_type == "Polygon": expected = MultiPolygon([expected])
    assert actual.equals_exact(expected, 0)
    assert frame.holes.tolist() == [1] and frame.area.iloc[0] == actual.area
    assert any(abs(value * 1000 - round(value * 1000)) > 1e-7
               for polygon in actual.geoms for ring in [polygon.exterior, *polygon.interiors]
               for xy in ring.coords for value in xy)
    assert payload["features"][0]["properties"]["aoi_clipping_method"] == native.AOI_CLIPPING_METHOD
    assert "aoi_file" not in mapping.request["model"]
    manifest = json.loads(Path(frame.attrs["manifest"]).read_text())
    assert manifest["full_engine_products"][0]["area"] == 100.
    assert manifest["full_engine_products"][0]["holes"] == 0
    assert manifest["engine_report"]["profiles"][0]["area"] == 100.
    assert manifest["products"][0]["area"] == actual.area


@pytest.mark.parametrize("bbox", [[20, 20, 30, 30], [10, 2, 12, 4]])
def test_final_gis_clipping_can_be_empty_or_line_only_with_full_engine_polygon(mapping, bbox):
    frame = invoke(mapping, bbox=bbox)
    payload = json.loads(Path(frame.boundary_geojson.iloc[0]).read_text())
    assert frame.status.tolist() == ["empty"]
    assert frame.polygons.tolist() == [0] and frame.area.tolist() == [0.]
    assert payload["features"][0]["geometry"] == {"type": "MultiPolygon", "coordinates": []}
    assert frame.attrs["aoi_clipping_method"] == native.AOI_CLIPPING_METHOD
    manifest = json.loads(Path(frame.attrs["manifest"]).read_text())
    assert manifest["full_engine_products"][0]["polygons"] == 1
    assert manifest["full_engine_products"][0]["area"] == 100.


def test_late_full_engine_geometry_failure_rolls_back_previously_clipped_products(mapping):
    mapping.failure = "late"
    with pytest.raises(FimEngineError):
        invoke(mapping, profiles={"first": "Max", "second": 7}, bbox=[1.123456, 2.345678, 8.765432, 9.876543])
    assert not list(mapping.args[2].glob("*.geojson"))
    manifest = json.loads((mapping.args[2] / "boundary_manifest.json").read_text())
    assert manifest["status"] == "aborted"
    assert manifest["aoi_clipping_method"] == native.AOI_CLIPPING_METHOD


def test_final_gis_delivery_discards_only_zero_area_geometrycollection_parts():
    from shapely.geometry import MultiPolygon, box, mapping, shape
    full = MultiPolygon([box(0, 0, 2, 2), box(4, 0, 6, 2)])
    aoi = box(1.123456789, 0, 4, 2)
    reference = full.intersection(aoi)
    assert reference.geom_type == "GeometryCollection"
    assert any(part.geom_type == "LineString" for part in reference.geoms)
    expected = MultiPolygon([part for part in reference.geoms if part.geom_type == "Polygon"])
    product = {"features": [{"properties": {}, "geometry": mapping(full)}]}
    clipped, counts = native._clip_product(product, aoi, (2, 0, 10, 8.), 1 << 20)
    actual = shape(clipped["features"][0]["geometry"])
    assert actual.equals_exact(expected, 0, normalize=True)
    assert counts == (1, 0, 5, expected.area)


def test_without_aoi_delivery_keeps_full_geometry_and_no_clip_marker(mapping):
    frame = invoke(mapping)
    assert frame.attrs["aoi_clipping_method"] is None
    payload = json.loads(Path(frame.boundary_geojson.iloc[0]).read_text())
    assert "aoi_clipping_method" not in payload["features"][0]["properties"]
    assert frame.area.tolist() == [100.] and frame.polygons.tolist() == [1]


def test_3d_aoi_refuses_instead_of_delivering_non_xy_geojson(mapping):
    from shapely.geometry import Polygon
    polygon = Polygon([(1, 1, 10), (5, 1, 10), (5, 5, 10), (1, 5, 10)])
    with pytest.raises(FimUnsupportedError, match="two-dimensional XY"):
        invoke(mapping, polygon=polygon, aoi_crs="EPSG:6588")
    assert mapping.request is None
    assert not list(mapping.args[2].glob("*.geojson"))


def test_failed_engine_without_report_preserves_exit_and_stderr_before_parsing(mapping, monkeypatch):
    mapping.failure = "exit_missing"
    monkeypatch.setattr(_boundary, "_load_json", lambda *_: pytest.fail("parsed report before handling exit99"))
    with pytest.raises(FimEngineError, match="exit 99.*bounded diagnostics"):
        invoke(mapping)
    manifest = json.loads((mapping.args[2] / "boundary_manifest.json").read_text())
    assert manifest["engine_returncode"] == 99
    assert manifest["engine_stderr_tail"] == "bounded diagnostics"
    assert manifest["status"] == "aborted" and manifest["products"] == []


@pytest.mark.parametrize("bbox", [[1000, 1000, 1010, 1010], [512, 1, 513, 2], [-1, 1, 0, 2]])
def test_out_of_source_aoi_refuses_before_engine_after_all_source_admission(mapping, bbox):
    with pytest.raises(FimUnsupportedError, match="does not intersect"):
        invoke(mapping, bbox=bbox)
    assert mapping.request is None
    assert mapping.selected_tiles_requested is None
    assert not list(mapping.args[2].glob("*.geojson"))


@pytest.mark.parametrize("registry", [None, [], {"boundary": {"method_id": _boundary.METHOD_ID}}])
def test_native_capability_refuses_before_output_or_preparation(mapping, monkeypatch, registry):
    monkeypatch.setattr(native._engine, "engine_method", lambda *_: registry)
    with pytest.raises(FimEngineError, match="capability"): invoke(mapping)
    assert not mapping.prepared and not mapping.args[2].exists()


@pytest.mark.parametrize("options", [{"threads": True}, {"threads": 65}, {"max_working_mib": 0},
    {"max_prepared_mib": 0}, {"max_inflight_profiles": 0}, {"timeout": float("nan")},
    {"profiles": {"CON": "Max"}}, {"interpolation": "face"}])
def test_invalid_controls_refuse_before_outputs(mapping, options):
    with pytest.raises(ValueError): invoke(mapping, **options)
    assert not mapping.args[2].exists() and not mapping.prepared


def test_units_must_be_english_without_crs_relabelling(mapping, monkeypatch):
    from ras_commander.hdf.HdfBase import HdfBase
    monkeypatch.setattr(HdfBase, "get_result_unit_metadata", lambda *_: {"unit_system": "SI"})
    with pytest.raises(FimUnsupportedError, match="English"): invoke(mapping)
    assert not mapping.args[2].exists()


@pytest.mark.parametrize("dimension,expected", [("1d", "one_d"), ("mixed_1d_2d", "coupled")])
def test_prepare_routes_xs_through_canonical_adapter(tmp_path, monkeypatch, dimension, expected):
    calls = []
    @contextmanager
    def adapter(*args, **kwargs):
        calls.append(kwargs)
        yield {"receipt": {"point_count": 3, "triangle_count": 1, "cross_section_count": 2},
            "xs": {"profiles": []}, "mesh": None, "storage": None}
    monkeypatch.setattr(native._boundary_model, "prepare_boundary_xs", adapter)
    with native._prepare(Path("hdf"), Path("tif"), tmp_path, {"max": "Max"},
            SimpleNamespace(dimension=dimension), Path("engine"), 4, 64, 32, None) as staged:
        assert staged["xs"] is not None
    assert calls[0]["scope"] == expected and calls[0]["max_working_mib"] == 32


def test_storage_only_preparation_has_no_fabricated_xs(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "_stage_storage", lambda *_: {"count": 1})
    with native._prepare(Path("hdf"), Path("tif"), tmp_path, {"max": "Max"},
            SimpleNamespace(dimension="storage_only"), Path("engine"), 1, 64, 32, None) as staged:
        assert staged["xs"] is None and staged["mesh"] is None and staged["storage"] == {"count": 1}


@pytest.mark.parametrize("oversized", [False, True])
def test_prepare_2d_uses_complete_sloping_context_and_admits_transport_before_write(tmp_path, monkeypatch, oversized):
    import geopandas as gpd
    from shapely.geometry import box
    from ras_commander.fim.RasFim import RasFim
    source_root = tmp_path / "canonical"
    source_root.mkdir()
    for name in ("mesh.json", "values.bin"):
        (source_root / name).write_bytes(b"canonical")
    output_root = tmp_path / "boundary"
    output_root.mkdir()
    checks, options = [], []
    class Context:
        def __init__(self, *args, **kwargs):
            options.append(kwargs)
            self._temporary = SimpleNamespace(name=str(source_root))
            self._cells = gpd.GeoDataFrame({"mesh_name": ["a"], "cell_id": [0]}, geometry=[box(0, 0, 10, 10)], crs=6588)
            self._meshes = [{"mesh_name": "a"}]
            self._mesh_files = ["mesh.json"]
            self._units = {"max": {"id": "max", "values_files": ["values.bin"]}}
            self._info = {"planned_prepared_bytes": 1 << 30 if oversized else 1024}
        def _check_sources(self): checks.append(True)
        def __enter__(self): return self
        def __exit__(self, *_): pass
    monkeypatch.setattr(RasFim, "prepare_sloping_model", Context)
    context = native._prepare(Path("hdf"), Path("tif"), output_root, {"max": "Max"},
        SimpleNamespace(dimension="2d", storage_area_names=()), Path("engine"), 4, 64, 32, None)
    if oversized:
        with pytest.raises(FimUnsupportedError, match="geometry"):
            with context: pytest.fail("unadmitted geometry yielded")
        assert not (output_root / "boundary-cells.wkb").exists()
    else:
        with context as staged:
            assert staged["xs"] is None and staged["mesh"]["owner_cells"] == [[0, 0]]
            assert Path(staged["mesh"]["mesh_files"][0]).is_absolute()
            assert Path(staged["mesh"]["profiles"][0]["values_files"][0]).is_absolute()
            assert Path(staged["mesh"]["geometry_file"]).is_file()
        assert len(checks) == 2
    assert options[0]["native_session"] is False
    assert "bbox" not in options[0] and "polygon" not in options[0]


def test_mosaic_protocol_and_manifest_preserve_exact_original_source_order(mapping, tmp_path):
    extras = [tmp_path / "z-before-a.tif", tmp_path / "a-after-z.tif"]
    for path in extras:
        path.write_bytes(b"source")
    mapping.extra_terrains = extras
    frame = invoke(mapping, threads=4, profiles={"second": 7, "first": "Max"})
    assert [unit["terrain"] for unit in mapping.request["additional_terrains"]] == [str(path) for path in extras]
    assert all(unit["terrain_metadata"]["selected_tiles"] == [0, 1]
               for unit in mapping.request["additional_terrains"])
    assert all(unit["terrain_metadata"]["stitch_points"] is None
               for unit in mapping.request["additional_terrains"])
    assert mapping.request["terrain_metadata"]["stitch_points"]
    assert "aoi_file" not in mapping.request["model"]
    assert mapping.terrain_staging_options["engine_path"].name == "engine.exe"
    assert mapping.terrain_staging_options["threads"] == 4
    manifest = json.loads(Path(frame.attrs["manifest"]).read_text())
    receipt = manifest["terrain_source_receipt"]
    assert receipt["schema"] == "ras-commander-boundary-terrain-sources/1"
    assert [row["path"] for row in receipt["source_identities"]] == [str(mapping.args[1]), *map(str, extras)]
    assert [row["effective_index"] for row in receipt["source_identities"]] == [0, 1, 2]
    assert manifest["additional_terrains"] == mapping.request["additional_terrains"]
    assert manifest["sources"]["terrain_source_0001"]["sha256"] == native._one_d.digest(extras[0])
    assert frame.attrs["native_vector_parity"] is False


def test_aoi_on_additional_source_is_admitted_and_only_final_vectors_are_clipped(mapping, tmp_path):
    extra = tmp_path / "additional.tif"
    extra.write_bytes(b"source")
    mapping.extra_terrains = [extra]
    frame = invoke(mapping, bbox=[520.123456789, 2.3456789, 530.987654321, 20.123456789])
    assert frame.status.tolist() == ["empty"]
    assert frame.attrs["aoi_clipping_method"] == native.AOI_CLIPPING_METHOD
    assert "aoi_file" not in mapping.request["model"]
    assert mapping.request["terrain_metadata"]["selected_tiles"] == [0, 1]
    assert mapping.request["additional_terrains"][0]["terrain_metadata"]["selected_tiles"] == [0, 1]


@pytest.mark.parametrize("failure", ["terrain_receipt", "terrain_pre_engine", "terrain_after_engine"])
def test_mosaic_receipt_and_same_stat_source_drift_refuse_and_rollback(mapping, tmp_path, failure):
    extra = tmp_path / "additional.tif"
    extra.write_bytes(b"source")
    mapping.extra_terrains = [extra]
    mapping.failure = failure
    with pytest.raises(FimEngineError):
        invoke(mapping, profiles={"first": "Max", "second": 7})
    if failure != "terrain_after_engine":
        assert mapping.request is None
    assert not list(mapping.args[2].glob("*.geojson"))
    manifest = json.loads((mapping.args[2] / "boundary_manifest.json").read_text())
    assert manifest["status"] == "aborted" and manifest["products"] == []


def test_native_api_stages_actual_two_source_hdf_tiff_without_flattening(mapping, tmp_path, monkeypatch):
    import h5py
    from ras_commander import fast_hdf
    from ras_commander.fim import _boundary_inputs, _boundary_terrain_sources
    terrain = mapping.args[1]
    extra = tmp_path / "additional.tif"
    with rasterio.open(extra, "w", driver="GTiff", width=257, height=256, count=1,
            dtype="float32", tiled=True, blockxsize=256, blockysize=256,
            crs="EPSG:6588", transform=from_origin(512, 256, 1, 1), nodata=-9999) as out:
        out.write(np.ones((256, 257), dtype="float32"), 1)
    with h5py.File(mapping.terrain_hdf, "w") as h:
        h.attrs["Projection"] = np.bytes_(rasterio.crs.CRS.from_epsg(6588).to_wkt())
        for index, path in enumerate((terrain, extra)):
            source = h.create_group(f"Terrain/source-{index}")
            source.attrs["File"] = np.bytes_(path.name)
            source.attrs["Priority"] = index
            level = source.create_group("0")
            count = 2
            level["Mask"] = np.zeros((count, 65536), dtype="uint8")
            level["Perimeter"] = np.ones((count, 513), dtype="float32")
        h["Terrain/Stitch TIN Points"] = np.array([[0, 0, 0, 0], [1, 0, 0, 0], [0, 1, 0, 0]], dtype="<f8")
        h["Terrain/Stitch TIN Triangles"] = np.array([[0, 1, 2]], dtype="<i4")
    calls = []
    def read(dataset, selection, **kwargs):
        assert kwargs["backend"] == "rust"
        calls.append(dataset.name)
        return dataset[selection]
    monkeypatch.setattr(fast_hdf, "read_dataset", read)
    monkeypatch.setattr(_boundary_inputs, "_native_bitfields", lambda *args: False)
    monkeypatch.setattr(native, "stage_native_terrain_sources", _boundary_terrain_sources.stage_native_terrain_sources)
    frame = invoke(mapping, bbox=[520.123456789, 2, 530.987654321, 20])
    request = mapping.request
    assert request["model"]["terrain"] == str(terrain)
    assert request["additional_terrains"][0]["terrain"] == str(extra)
    assert request["terrain_metadata"]["selected_tiles"] == [0, 1]
    assert request["additional_terrains"][0]["terrain_metadata"]["selected_tiles"] == [0, 1]
    assert request["terrain_metadata"]["stitch_points"]["shape"] == [3, 4]
    assert request["additional_terrains"][0]["terrain_metadata"]["stitch_points"] is None
    assert calls.count("/Terrain/Stitch TIN Points") == 1
    assert calls.count("/Terrain/Stitch TIN Triangles") == 1
    manifest = json.loads(Path(frame.attrs["manifest"]).read_text())
    assert [row["path"] for row in manifest["terrain_source_receipt"]["source_identities"]] == [str(terrain), str(extra)]
    assert frame.status.tolist() == ["empty"] and mapping.cleaned


def test_public_raw_opt_in_retains_all_profiles_and_raises_typed_refusal(mapping):
    from ras_commander.fim.RasFim import RasFim
    from ras_commander.fim import FimGeometryError
    mapping.invalid_profiles = {"second"}
    with pytest.raises(FimGeometryError) as caught:
        RasFim.map_inundation_boundaries(*mapping.args, terrain_hdf=mapping.terrain_hdf,
            method="native_serial", allow_unqualified=True, preserve_raw_geometry=True,
            profiles={"first": "Max", "second": 7})
    error = caught.value
    manifest = json.loads(Path(error.diagnostic_manifest).read_text())
    assert manifest["status"] == "aborted" and manifest["products"] == []
    assert manifest["raw_geometry"]["provenance_verified"] is True
    assert manifest["raw_geometry"]["complete_raw_profile_coverage"] is True
    assert set(manifest["raw_geometry"]["profiles"]) == {"first", "second"}
    assert len(error.artifacts) == 2 and all(Path(p).is_file() for p in error.artifacts)
    assert "Self-intersection" in error.validity_reason
    assert not list(mapping.args[2].glob("*.geojson"))
    assert mapping.cleaned
    receipts = manifest["raw_geometry"]["profiles"]
    assert receipts["first"]["topology_validity"] is True
    assert receipts["second"]["topology_validity"] is False
    invalid = json.loads(Path(error.artifacts[1]).read_text())
    assert invalid["features"][0]["geometry"]["coordinates"][0][0] == [
        [0, 0], [10, 10], [0, 10], [10, 0], [0, 0]]


def test_raw_false_still_refuses_without_artifact_retention(mapping):
    from ras_commander.fim import FimGeometryError
    mapping.invalid_profiles = {"Max"}
    with pytest.raises(FimGeometryError) as caught:
        invoke(mapping)
    assert caught.value.diagnostic_manifest is None and not caught.value.artifacts
    assert not (mapping.args[2] / "raw_geometry").exists()
    assert not list(mapping.args[2].glob("*.geojson"))


def test_valid_raw_opt_in_returns_normal_products(mapping):
    result = invoke(mapping, preserve_raw_geometry=True)
    assert result.status.tolist() == ["complete"]
    assert Path(result.iloc[0].boundary_geojson).is_file()
    assert not (mapping.args[2] / "raw_geometry").exists()


@pytest.mark.parametrize("failure", ["source", "receipt", "interrupt", "count", "product_method", "exit"])
def test_raw_topology_never_masks_source_protocol_or_interrupt_failure(mapping, failure):
    from ras_commander.fim import FimGeometryError
    mapping.invalid_profiles = {"Max"}
    mapping.failure = failure
    error_type = KeyboardInterrupt if failure == "interrupt" else (FimEngineError, FimUnsupportedError)
    with pytest.raises(error_type) as caught:
        invoke(mapping, preserve_raw_geometry=True)
    assert not isinstance(caught.value, FimGeometryError)
    manifest = json.loads((mapping.args[2] / "boundary_manifest.json").read_text())
    assert manifest["status"] == "aborted" and manifest["products"] == []
    assert not manifest.get("raw_geometry", {}).get("provenance_verified", False)
    assert not list(mapping.args[2].glob("*.geojson"))


@pytest.mark.parametrize("kwargs", [{"preserve_raw_geometry": 1},
    {"preserve_raw_geometry": True, "bbox": [0, 0, 1, 1]},
    {"preserve_raw_geometry": True, "aoi_crs": "EPSG:6588"}])
def test_native_raw_guard_precedes_engine_and_outputs(mapping, monkeypatch, kwargs):
    monkeypatch.setattr(native._engine, "find_engine", lambda *_: pytest.fail("engine before raw guard"))
    with pytest.raises((TypeError, FimUnsupportedError)):
        invoke(mapping, **kwargs)
    assert not mapping.args[2].exists()
