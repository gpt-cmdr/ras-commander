"""Bounded vector comparison tests using actual GeoJSON and TIFF files."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

pytest.importorskip("rasterio")
shapely = pytest.importorskip("shapely")
from shapely.geometry import Polygon, box, mapping

from ras_commander.fim import _boundary_comparison as comparison


def write_polygon(path, geometry, crs="EPSG:2871"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(type="FeatureCollection",
        crs=dict(type="name", properties=dict(name=crs)),
        features=[dict(type="Feature", properties={}, geometry=mapping(geometry))])))
    return path


def test_complete_geometry_holes_and_both_directions():
    outer = box(0, 0, 10, 10)
    reference = Polygon(outer.exterior.coords, [box(2, 2, 4, 4).exterior.coords])
    candidate = Polygon(box(1, 0, 11, 10).exterior.coords, [box(6, 6, 7, 7).exterior.coords])
    result = comparison._metrics(candidate, reference)
    assert result["candidate_holes"] == result["reference_holes"] == 1
    assert result["extra_area"] == 14
    assert result["missing_area"] == 11
    assert result["symmetric_difference_area"] == 25
    assert not result["geometry_equal"]
    assert not result["quantized_coordinates_equal"]


def test_raw_difference_is_not_hidden_by_lattice():
    candidate, reference = box(0, 0, 1.0001, 1), box(0, 0, 1, 1)
    result = comparison._metrics(candidate, reference)
    assert result["quantized_coordinates_equal"]
    assert not result["coordinates_equal"]
    assert not result["geometry_equal"]
    assert result["extra_area"] == pytest.approx(.0001)
    assert not comparison._metrics(box(0, 0, 1.001, 1), reference)["quantized_coordinates_equal"]


def test_canonical_orientation_start_and_part_order():
    a, b = box(0, 0, 1, 1), box(3, 3, 4, 4)
    coords = list(a.exterior.coords)[:-1]
    rotated = coords[2:] + coords[:2]
    reversed_a = Polygon(list(reversed(rotated)))
    assert comparison._canonical(shapely.MultiPolygon([a, b])) == comparison._canonical(shapely.MultiPolygon([b, reversed_a]))


def test_crs_invalid_geometry_and_budget(tmp_path):
    path = write_polygon(tmp_path / "ref.geojson", box(0, 0, 1, 1))
    with pytest.raises(ValueError, match="CRS"):
        comparison._read_geometry(path, "EPSG:4326", 1024**2)
    with pytest.raises(ValueError, match="budget"):
        comparison._read_geometry(path, "EPSG:2871", 32)
    write_polygon(path, Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]))
    with pytest.raises(ValueError, match="invalid"):
        comparison._read_geometry(path, "EPSG:2871", 1024**2)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    import rasterio
    import numpy as np
    from rasterio.transform import from_origin
    from ras_commander.fim.RasFim import RasFim
    hdf, terrain_hdf = tmp_path / "model.hdf", tmp_path / "terrain.hdf"
    hdf.write_bytes(b"qualification input")
    terrain_hdf.write_bytes(b"terrain input")
    terrain = tmp_path / "terrain.tif"
    with rasterio.open(terrain, "w", driver="GTiff", width=2, height=2, count=1,
                       dtype="float32", crs="EPSG:2871", transform=from_origin(0, 2, 1, 1)) as dst:
        dst.write(np.zeros((2, 2), dtype="float32"), 1)
    def candidate(_hdf, _terrain, output, **kwargs):
        rows = []
        for name in kwargs["profiles"]:
            path = write_polygon(Path(output) / f"{name}.geojson", box(0, 0, 1, 1))
            rows.append(dict(profile=name, status="complete", boundary_geojson=str(path)))
        return pd.DataFrame(rows)
    monkeypatch.setattr(RasFim, "map_inundation_boundaries", candidate)
    return hdf, terrain, terrain_hdf


def test_retained_reference_timings_aoi_and_receipt(inputs, tmp_path):
    hdf, terrain, terrain_hdf = inputs
    ref = write_polygon(tmp_path / "reference.geojson", box(0, 0, 2, 1))
    result = comparison.run(hdf, terrain, tmp_path / "out", terrain_hdf=terrain_hdf,
        profiles={"a": "Max", "b": 0}, native_boundaries={"a": ref, "b": ref}, bbox=(0, 0, .5, 1))
    assert result.geometry_equal.all()
    assert list(result.candidate_area) == [.5, .5]
    assert result.native_seconds.isna().all()
    performance = result.attrs["performance"]
    assert performance["native_store_maps_seconds"] is None
    assert not performance["ratio_eligible"]
    assert result.candidate_batch_seconds.nunique() == 1
    assert performance["candidate_batch_seconds"] == result.candidate_batch_seconds.iloc[0]
    report = json.loads(Path(result.attrs["comparison_report"]).read_text())
    assert report["status"] == "complete"
    assert report["rows"][0]["native_seconds"] is None
    assert report["native_vector_parity"] is False
    assert report["sources"][str(hdf)]["sha256"]
    with pytest.raises(FileExistsError):
        comparison.run(hdf, terrain, tmp_path / "out", terrain_hdf=terrain_hdf, native_boundaries={"Max": ref})


def test_native_execution_policy_is_forwarded_and_receipted(inputs, tmp_path, monkeypatch):
    from ras_commander import StoreMapPerformanceOptions
    hdf, terrain, terrain_hdf = inputs
    ref = write_polygon(tmp_path / "native.geojson", box(0, 0, 1, 1))
    policy = StoreMapPerformanceOptions(native_polygon_serial=True)
    def generate(*args, native_performance):
        assert native_performance is policy
        return {"Max": ref}, {"Max": "Max"}, {"Max": 1.0}
    monkeypatch.setattr(comparison, "_generate_native", generate)
    result = comparison.run(hdf, terrain, tmp_path / "out", terrain_hdf=terrain_hdf,
        native_performance=policy, plan_number="02")
    assert result.iloc[0].coordinates_equal
    receipt = json.loads(Path(result.attrs["comparison_report"]).read_text())
    assert receipt["native_performance_requested"]["native_polygon_serial"] is True


def test_native_execution_policy_cannot_relabel_retained_references(tmp_path):
    from ras_commander import StoreMapPerformanceOptions
    with pytest.raises(ValueError, match="retained"):
        comparison.run("absent", "absent", tmp_path / "out", terrain_hdf="absent",
            native_boundaries={"Max": "absent"},
            native_performance=StoreMapPerformanceOptions(native_polygon_serial=True))
    assert not (tmp_path / "out").exists()


def test_serial_worker_policy_refuses_before_candidate_or_inputs(tmp_path):
    from ras_commander import StoreMapPerformanceOptions
    with pytest.raises(ValueError, match="max_workers=1"):
        comparison.run("absent", "absent", tmp_path / "out", terrain_hdf="absent",
            method="native_serial", allow_unqualified=True,
            native_performance=StoreMapPerformanceOptions(native_polygon_serial=True, max_workers=4))
    assert not (tmp_path / "out").exists()


def test_aborted_manifest_keeps_evidence(inputs, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("native exit 99")
    monkeypatch.setattr(comparison, "_generate_native", fail)
    hdf, terrain, terrain_hdf = inputs
    with pytest.raises(RuntimeError, match="exit 99"):
        comparison.run(hdf, terrain, tmp_path / "out", terrain_hdf=terrain_hdf, plan_number="02")
    receipt = json.loads((tmp_path / "out/boundary_comparison.json").read_text())
    assert receipt["status"] == "aborted"
    assert (tmp_path / "out/rust/Max.geojson").exists()


@pytest.mark.parametrize("serial", [False, True])
def test_native_failure_restores_rasmap(tmp_path, monkeypatch, serial):
    from ras_commander.RasProcess import RasProcess
    from ras_commander.RasPlan import RasPlan
    from ras_commander.RasMap import RasMap
    from ras_commander import StoreMapPerformanceOptions
    from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan
    plan = tmp_path / "model.p02"
    plan.write_bytes(b"plan")
    hdf = Path(str(plan) + ".hdf")
    hdf.write_bytes(b"hdf")
    terrain = tmp_path / "terrain.hdf"
    terrain.write_bytes(b"terrain")
    rasmap = tmp_path / "model.rasmap"
    rasmap.write_bytes(b"original bytes")
    obj = SimpleNamespace(project_folder=tmp_path, project_name="model",
        plan_df=pd.DataFrame([dict(plan_number="02")]), check_initialized=lambda: None)
    monkeypatch.setattr(RasPlan, "get_plan_path", lambda *a, **k: plan)
    monkeypatch.setattr(RasMap, "get_rasmap_path", lambda *a, **k: rasmap)
    monkeypatch.setattr(RasMap, "list_terrain_layers", lambda *a, **k: pd.DataFrame([dict(name="terrain", resolved_path=str(terrain))]))
    def fail(*args, **kwargs):
        rasmap.write_bytes(b"temporary mutation")
        raise RuntimeError("native failed")
    monkeypatch.setattr(RasProcess, "store_maps", fail)
    runtime = {"helper": {"sha256": "helper"}, "libraries": {"RasMapperLib.dll": {"sha256": "mapper"}}}
    monkeypatch.setattr(RasProcess, "get_store_maps_runtime_provenance", lambda *_: runtime)
    monkeypatch.setattr(HdfResultsPlan, "is_steady_plan", lambda *_: False)
    state = {}
    with pytest.raises(RuntimeError, match="native failed"):
        comparison._generate_native(hdf, terrain, tmp_path / "out", {"Max": "Max"},
            "sloping", "02", None, obj, "6.6", 1, state,
            native_performance=StoreMapPerformanceOptions(native_polygon_serial=True) if serial else None)
    assert rasmap.read_bytes() == b"original bytes"
    assert state["rasmap_restored"]
    assert state["rasmap_sha256_before"] == state["rasmap_sha256_after"]
    if serial:
        assert state["native_runtime_requested"] == "6.6"
        assert state["native_runtime_unchanged"]
        assert state["native_runtime_before"] == state["native_runtime_after"] == runtime


def test_holes_survive_aoi_clip():
    candidate = Polygon(box(0, 0, 10, 10).exterior.coords, [box(3, 3, 7, 7).exterior.coords])
    clipped = comparison._polygonal(candidate.intersection(box(1, 1, 9, 9)))
    assert comparison._stats(clipped)[:2] == (1, 1)
    assert clipped.area == 48


@pytest.mark.parametrize("changed", [False, True])
def test_generated_serial_reference_binds_runtime_through_completion(tmp_path, monkeypatch, changed):
    from ras_commander import StoreMapPerformanceOptions
    from ras_commander.RasProcess import RasProcess
    from ras_commander.RasPlan import RasPlan
    from ras_commander.RasMap import RasMap
    from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan

    plan, terrain, rasmap = (tmp_path / name for name in ("model.p02", "terrain.hdf", "model.rasmap"))
    hdf = Path(str(plan) + ".hdf")
    for path in (plan, terrain, rasmap, hdf):
        path.write_bytes(b"original")
    obj = SimpleNamespace(project_folder=tmp_path, project_name="model",
        plan_df=pd.DataFrame([dict(plan_number="02")]), check_initialized=lambda: None)
    monkeypatch.setattr(RasPlan, "get_plan_path", lambda *a, **k: plan)
    monkeypatch.setattr(RasMap, "get_rasmap_path", lambda *a, **k: rasmap)
    monkeypatch.setattr(RasMap, "list_terrain_layers", lambda *a, **k:
        pd.DataFrame([dict(name="terrain", resolved_path=str(terrain))]))
    monkeypatch.setattr(HdfResultsPlan, "is_steady_plan", lambda *_: False)
    runtimes = iter([{"helper": {"sha256": "before"}},
        {"helper": {"sha256": "after" if changed else "before"}}])
    monkeypatch.setattr(RasProcess, "get_store_maps_runtime_provenance", lambda *_: next(runtimes))
    def export(*args, output_path, **kwargs):
        output_path.mkdir(parents=True)
        vector = output_path / "boundary.geojson"
        vector.write_text("{}")
        return {"inundation_boundary": [vector]}
    monkeypatch.setattr(RasProcess, "store_maps", export)
    state = {}
    def generate():
        return comparison._generate_native(hdf, terrain, tmp_path / "out", {"Max": "Max"},
            "sloping", "02", None, obj, "6.6", 1, state,
            native_performance=StoreMapPerformanceOptions(native_polygon_serial=True))
    if changed:
        with pytest.raises(RuntimeError, match="runtime/helper identity changed"):
            generate()
    else:
        paths, profiles, clocks = generate()
        assert profiles == {"Max": "Max"} and paths["Max"].is_file() and clocks["Max"] >= 0
    assert state["native_runtime_requested"] == "6.6"
    assert state["native_runtime_unchanged"] is (not changed)
    assert state["rasmap_restored"] and rasmap.read_bytes() == b"original"


@pytest.mark.parametrize("receipt", [None, {},
    {"clip_geometry_wkb_hex": box(1, 1, 2, 2).wkb_hex, "clip_crs": "EPSG:2871"},
    {"clip_geometry_wkb_hex": box(0, 0, 1, 1).wkb_hex, "clip_crs": "EPSG:2227"},
    {"clip_geometry_wkb_hex": box(0, 0, 1, 1).wkb_hex, "clip_crs": "invalid"}])
def test_preclipped_candidate_requires_exact_aoi_receipt(receipt):
    candidate = pd.DataFrame()
    candidate.attrs.update(aoi_clipping_method="unrounded-geos-intersection/1", aoi=receipt)
    with pytest.raises(RuntimeError, match="exact comparison AOI"):
        comparison._candidate_preclipped(candidate, "native_serial", box(0, 0, 1, 1), "EPSG:2871")


def test_preclipped_candidate_accepts_exact_receipt_only_for_native_method():
    clip = box(0, 0, 1, 1)
    candidate = pd.DataFrame()
    candidate.attrs.update(aoi_clipping_method="unrounded-geos-intersection/1",
        aoi={"clip_geometry_wkb_hex": clip.wkb_hex, "clip_crs": "EPSG:2871"})
    assert comparison._candidate_preclipped(candidate, "native_serial", clip, "EPSG:2871")
    assert not comparison._candidate_preclipped(candidate, "deterministic", clip, "EPSG:2871")


def test_comparison_keeps_all_mosaic_sources_bound_after_candidate(inputs, tmp_path, monkeypatch):
    from ras_commander.fim.RasFim import RasFim
    hdf, terrain, terrain_hdf = inputs
    extra = tmp_path / "extra.tif"
    extra.write_bytes(b"original extra")
    ref = write_polygon(tmp_path / "native.geojson", box(0, 0, 1, 1))
    original = RasFim.map_inundation_boundaries
    def candidate(*args, **kwargs):
        frame = original(*args, **kwargs)
        root = Path(args[2])
        records = [dict(path=str(path), effective_index=index, **comparison._identity(path))
                   for index, path in enumerate([terrain, extra])]
        manifest = root / "boundary_manifest.json"
        manifest.write_text(json.dumps({"terrain_source_receipt": {
            "schema": "ras-commander-boundary-terrain-sources/1", "source_identities": records},
            "additional_terrains": [{"terrain": str(extra)}]}))
        frame.attrs["manifest"] = str(manifest)
        return frame
    def generate(*args, **kwargs):
        extra.write_bytes(b"changed extra")
        return {"Max": ref}, {"Max": "Max"}, {"Max": 1.0}
    monkeypatch.setattr(RasFim, "map_inundation_boundaries", candidate)
    monkeypatch.setattr(comparison, "_generate_native", generate)
    from ras_commander import StoreMapPerformanceOptions
    with pytest.raises(RuntimeError, match="source changed"):
        comparison.run(hdf, terrain, tmp_path / "out", terrain_hdf=terrain_hdf,
            method="native_serial", allow_unqualified=True,
            native_performance=StoreMapPerformanceOptions(native_polygon_serial=True))
    report = json.loads((tmp_path / "out/boundary_comparison.json").read_text())
    assert report["status"] == "aborted"
    assert str(extra) in report["sources"]


def test_candidate_cannot_return_stale_product(inputs, tmp_path, monkeypatch):
    from ras_commander.fim.RasFim import RasFim
    hdf, terrain, terrain_hdf = inputs
    old = write_polygon(tmp_path / "old.geojson", box(0, 0, 1, 1))
    monkeypatch.setattr(RasFim, "map_inundation_boundaries", lambda *a, **k:
        pd.DataFrame([dict(profile="Max", status="complete", boundary_geojson=str(old))]))
    with pytest.raises(RuntimeError, match="fresh output"):
        comparison.run(hdf, terrain, tmp_path / "out", terrain_hdf=terrain_hdf,
            native_boundaries={"Max": old})
    assert json.loads((tmp_path / "out/boundary_comparison.json").read_text())["status"] == "aborted"


def test_input_change_detected(inputs, tmp_path, monkeypatch):
    from ras_commander.fim.RasFim import RasFim
    hdf, terrain, terrain_hdf = inputs
    ref = write_polygon(tmp_path / "ref.geojson", box(0, 0, 1, 1))
    original = RasFim.map_inundation_boundaries
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        hdf.write_bytes(b"changed")
        return result
    monkeypatch.setattr(RasFim, "map_inundation_boundaries", mutate)
    with pytest.raises(RuntimeError, match="source changed"):
        comparison.run(hdf, terrain, tmp_path / "out", terrain_hdf=terrain_hdf,
            native_boundaries={"Max": ref})


@pytest.mark.skipif(not os.environ.get("RAS_COMMANDER_FIM_BOUNDARY_REFERENCE"),
                    reason="Retained native polygon reference not configured")
def test_retained_native_reference_identity():
    path = Path(os.environ["RAS_COMMANDER_FIM_BOUNDARY_REFERENCE"])
    crs = os.environ.get("RAS_COMMANDER_FIM_BOUNDARY_REFERENCE_CRS", "EPSG:2871")
    geometry = comparison._read_geometry(path, crs, 1024**3)
    result = comparison._metrics(geometry, geometry)
    assert result["geometry_equal"] and result["quantized_coordinates_equal"]
    assert result["extra_area"] == result["missing_area"] == 0
    assert result["intersection_over_union"] == 1


def test_source_audit_failure_cannot_skip_rasmap_restoration(tmp_path, monkeypatch):
    from ras_commander.RasProcess import RasProcess
    from ras_commander.RasPlan import RasPlan
    from ras_commander.RasMap import RasMap
    plan = tmp_path / "model.p02"
    plan.write_bytes(b"plan")
    hdf = Path(str(plan) + ".hdf")
    hdf.write_bytes(b"hdf")
    terrain = tmp_path / "terrain.hdf"
    terrain.write_bytes(b"terrain")
    rasmap = tmp_path / "model.rasmap"
    rasmap.write_bytes(b"original bytes")
    obj = SimpleNamespace(project_folder=tmp_path, project_name="model",
        plan_df=pd.DataFrame([dict(plan_number="02")]), check_initialized=lambda: None)
    monkeypatch.setattr(RasPlan, "get_plan_path", lambda *a, **k: plan)
    monkeypatch.setattr(RasMap, "get_rasmap_path", lambda *a, **k: rasmap)
    monkeypatch.setattr(RasMap, "list_terrain_layers", lambda *a, **k:
        pd.DataFrame([dict(name="terrain", resolved_path=str(terrain))]))
    identity = comparison._identity
    changed = False
    def audit(path):
        if changed and Path(path) == hdf:
            raise PermissionError("injected HDF lock during source audit")
        return identity(path)
    def fail(*a, **k):
        nonlocal changed
        rasmap.write_bytes(b"temporary mutation")
        changed = True
        raise RuntimeError("native failed")
    monkeypatch.setattr(comparison, "_identity", audit)
    monkeypatch.setattr(RasProcess, "store_maps", fail)
    state = {}
    with pytest.raises(RuntimeError, match="native failed"):
        comparison._generate_native(hdf, terrain, tmp_path / "out", {"Max": "Max"},
            "sloping", "02", None, obj, None, 1, state)
    assert rasmap.read_bytes() == b"original bytes"
    assert state["rasmap_restored"]
    assert state["native_sources_unchanged"] is False
    assert "injected HDF lock" in state["native_source_audit_error"]


def test_reference_reader_retains_stored_collinear_vertices(tmp_path):
    with_midpoint = Polygon([(0, 0), (1, 0), (2, 0), (2, 2), (0, 2), (0, 0)])
    path = write_polygon(tmp_path / "native.geojson", with_midpoint)
    reference = comparison._read_geometry(path, "EPSG:2871", 1024**2)
    assert comparison._stats(reference)[2] == 6
    result = comparison._metrics(box(0, 0, 2, 2), reference)
    assert result["geometry_equal"]
    assert result["extra_area"] == result["missing_area"] == 0
    assert not result["coordinates_equal"]
    assert not result["quantized_coordinates_equal"]


def test_unrounded_vertices_ignore_only_ring_order_start_and_orientation():
    a = Polygon([(0, 0), (1.00001, 0), (1.00001, 1), (0, 1)])
    points = list(a.exterior.coords)[:-1]
    b = Polygon(list(reversed(points[1:] + points[:1])))
    assert comparison._metrics(a, b)["coordinates_equal"]
    c = Polygon([(0, 0), (1.00002, 0), (1.00002, 1), (0, 1)])
    result = comparison._metrics(a, c)
    assert result["quantized_coordinates_equal"]
    assert not result["coordinates_equal"]


def test_native_pair_budget_counts_both_full_geometries_and_scratch():
    infos = [dict(vertices=950441, features=1, file_bytes=size)
             for size in (30 << 20, 15 << 20)]
    # Each input would fit alone, but their simultaneous comparison does not.
    assert all(comparison._admit_native_pair([info], 1024**3) < 1024**3 for info in infos)
    with pytest.raises(ValueError, match="comparison pair"):
        comparison._admit_native_pair(infos, 1024**3)
    assert comparison._admit_native_pair(infos, 2 * 1024**3) < 2 * 1024**3


def test_native_geojson_large_vertex_extension_preserves_legacy_limit(tmp_path):
    # A valid rectangle retains half a million collinear stored boundary points.
    points = [(i, 0) for i in range(500001)] + [(500000, 1), (0, 1), (0, 0)]
    geometry = Polygon(points)
    path = write_polygon(tmp_path / "large.geojson", geometry)
    del points, geometry
    budget = 2 * 1024**3
    plan = comparison._native_pair_plan(path, path, budget)
    assert plan[str(path.resolve())]["vertices"] == 500004
    native = comparison._read_geometry(path, "EPSG:2871", budget, native_plan=plan)
    assert int(shapely.count_coordinates(native)) == 500004
    assert native.is_valid
    with pytest.raises(ValueError, match="vertices"):
        comparison._read_geometry(path, "EPSG:2871", budget)


def test_geojson_preflight_validates_nested_arrays_and_chunk_boundaries(tmp_path):
    path = write_polygon(tmp_path / "nested.geojson", Polygon(box(0, 0, 4, 4).exterior.coords,
                                                             [box(1, 1, 2, 2).exterior.coords]))
    text = path.read_text()
    # Padding puts string escapes and coordinate punctuation across read chunks.
    text = text.replace('"properties": {}', '"properties": {"padding": "' + "x" * 65510 + '\\"[]{}"}')
    path.write_text(text)
    assert comparison._geojson_size_counts(path) == (10, 1)
    path.write_text('{"features":[], "coordinates":[[0,0],[1,2,3]]}')
    with pytest.raises(ValueError, match="finite XY"):
        comparison._geojson_size_counts(path)
    path.write_text('{"features":[], "coordinates":[[0,0]]} trailing')
    with pytest.raises(ValueError, match="Trailing"):
        comparison._geojson_size_counts(path)


def test_shp_vertex_headers_admitted_before_geos_or_gdal_read(tmp_path, monkeypatch):
    import geopandas as gpd
    import pyogrio
    path = tmp_path / "reference.shp"
    gpd.GeoDataFrame(geometry=[box(0, 0, 3, 3)], crs="EPSG:2871").to_file(path)
    monkeypatch.setattr(pyogrio, "read_dataframe", lambda *a, **k: pytest.fail("preflight must not parse geometry"))
    plan = comparison._native_pair_plan(path, None, 128 << 20)
    assert plan[str(path.resolve())]["vertices"] == 5
    raw = bytearray(path.read_bytes())
    import struct
    struct.pack_into("<i", raw, 100 + 8 + 40, 950441)
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="counts"):
        comparison._native_pair_plan(path, None, 2 * 1024**3)


def test_native_pair_preflight_refuses_before_json_materialization(tmp_path, monkeypatch):
    path = write_polygon(tmp_path / "small.geojson", box(0, 0, 1, 1))
    monkeypatch.setattr(comparison, "_load_json", lambda *a: pytest.fail("preflight must not materialize JSON"))
    with pytest.raises(ValueError, match="budget"):
        comparison._native_pair_plan(path, path, 64 << 20)


@pytest.mark.parametrize("shift", [0, 12.5])
def test_native_reader_bound_crs_uses_only_identical_projected_source(tmp_path, shift):
    from pyproj import CRS
    from pyproj.crs import BoundCRS, CompoundCRS
    from pyproj.crs.coordinate_operation import ToWGS84Transformation
    source = CRS.from_epsg(6479)
    bound = BoundCRS(source_crs=source, target_crs=CRS.from_epsg(4326),
        transformation=ToWGS84Transformation(source.geodetic_crs, x_axis_translation=shift))
    path = write_polygon(tmp_path / "bound.geojson", box(0, 0, 1, 1), bound.to_wkt())
    budget = 128 << 20
    plan = comparison._native_pair_plan(path, None, budget)
    assert comparison._read_geometry(path, source, budget, native_plan=plan).area == 1
    with pytest.raises(ValueError, match="CRS"):
        comparison._read_geometry(path, source, budget)  # Deterministic remains strict.
    for different in (CRS.from_epsg(6478), CRS.from_epsg(3452),
                      CompoundCRS("horizontal plus vertical", [source, CRS.from_epsg(5703)])):
        with pytest.raises(ValueError, match="CRS"):
            comparison._read_geometry(path, different, budget, native_plan=plan)


def test_native_comparison_reports_pair_admission_policy(inputs, tmp_path, monkeypatch):
    from ras_commander.fim.RasFim import RasFim
    hdf, terrain, terrain_hdf = inputs
    ref = write_polygon(tmp_path / "native.geojson", box(0, 0, 1, 1))
    original = RasFim.map_inundation_boundaries
    def candidate(*args, **kwargs):
        frame = original(*args, **kwargs)
        manifest = Path(args[2]) / "boundary_manifest.json"
        manifest.write_text(json.dumps(dict(terrain_source_receipt=dict(
            schema="ras-commander-boundary-terrain-sources/1",
            source_identities=[dict(path=str(terrain), effective_index=0, **comparison._identity(terrain))]),
            additional_terrains=[])))
        frame.attrs["manifest"] = str(manifest)
        return frame
    monkeypatch.setattr(RasFim, "map_inundation_boundaries", candidate)
    result = comparison.run(hdf, terrain, tmp_path / "native-out", terrain_hdf=terrain_hdf,
        native_boundaries={"Max": ref}, method="native_serial", allow_unqualified=True)
    policy = result.attrs["performance"]["geometry_admission"]
    assert policy["method"] == "native-vector-pair/1"
    assert policy["bytes_per_pair_vertex"] == 768
    assert policy["gpkg_large_vector_extension"] is False
    observed = []
    admit = comparison._admit_native_pair
    def record(infos, budget):
        observed.append([info["vertices"] for info in infos])
        return admit(infos, budget)
    monkeypatch.setattr(comparison, "_admit_native_pair", record)
    clip = Polygon([(.5, -.25), (1.25, .5), (.5, 1.25), (-.25, .5)])
    clipped = comparison.run(hdf, terrain, tmp_path / "native-aoi-out", terrain_hdf=terrain_hdf,
        native_boundaries={"Max": ref}, method="native_serial", allow_unqualified=True,
        polygon=clip, aoi_crs="EPSG:2871")
    assert list(clipped.candidate_vertices) == [9]
    assert [5, 5] in observed  # Full pair admitted before any GIS intersection.
    assert observed[-1] == [9, 9]  # Overlay can increase stored vertices.


@pytest.fixture
def raw_candidate(inputs, tmp_path, monkeypatch):
    """Synthetic public-map transport with real retained bytes and source receipts."""
    from ras_commander.fim.RasFim import RasFim
    from ras_commander.fim import FimGeometryError, _boundary_raw
    hdf, terrain, terrain_hdf = inputs
    engine = tmp_path / "raw-engine.exe"
    engine.write_bytes(b"frozen synthetic engine")
    state = SimpleNamespace(invalid=False, missing=set(), calls=0, failure=None, tamper=False)
    def candidate(_hdf, _terrain, output, **kwargs):
        state.calls += 1
        assert kwargs["method"] == "native_serial" and kwargs["allow_unqualified"] is True
        assert kwargs["preserve_raw_geometry"] is True
        output = Path(output)
        output.mkdir()
        rows, receipts, invalid = [], {}, {}
        manifest = output / "boundary_manifest.json"
        for name in kwargs["profiles"]:
            if name in state.missing:
                continue
            geom = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]) if state.invalid else box(0, 0, 1, 1)
            path = write_polygon(output / f"{name}.geojson", geom)
            rows.append(dict(profile=name, status="complete", boundary_geojson=str(path)))
            if state.invalid:
                raw = output / "raw_geometry"
                raw.mkdir(exist_ok=True)
                invalid[name] = "Self-intersection[1 1]"
                receipts[name] = _boundary_raw.retain_raw_geometry(path, raw / name, "EPSG:2871", 128 << 20,
                    validity_reason=invalid[name], topology_valid=False)
                path.unlink()
        sources = {}
        for name, path in (("hdf", hdf), ("terrain", terrain), ("terrain_hdf", terrain_hdf), ("engine", engine)):
            identity = comparison._identity(path)
            sources[name] = dict(path=str(path), identity=[identity["size"], identity["mtime_ns"]],
                                 sha256=identity["sha256"])
        details = dict(schema="ras-commander-boundary-manifest/1", status="aborted" if state.invalid else "complete",
            method_id="rasmapper-serial-zero-depth-contours/1", aoi=None, sources=sources,
            terrain_source_receipt=dict(schema="ras-commander-boundary-terrain-sources/1",
                source_identities=[dict(path=str(terrain), effective_index=0, **comparison._identity(terrain))]),
            additional_terrains=[])
        if state.invalid:
            details["raw_geometry"] = dict(diagnostic_only=True, qualified=False, provenance_verified=True,
                profiles=receipts, invalid_profiles=invalid, complete_raw_profile_coverage=not state.missing)
        manifest.write_text(json.dumps(details))
        if state.failure == "source":
            hdf.write_bytes(b"changed source")
        if state.failure == "interrupt":
            raise KeyboardInterrupt("injected owned interrupt")
        if state.failure == "engine":
            from ras_commander.fim import FimEngineError
            raise FimEngineError("injected engine refusal")
        if state.invalid:
            paths = [a["path"] for receipt in receipts.values() for a in receipt["artifacts"]]
            if state.tamper:
                Path(paths[0]).write_bytes(b"changed raw artifact")
            raise FimGeometryError("synthetic invalid topology", diagnostic_manifest=str(manifest),
                artifacts=paths, validity_reason="Self-intersection[1 1]")
        frame = pd.DataFrame(rows)
        frame.attrs["manifest"] = str(manifest)
        return frame
    monkeypatch.setattr(RasFim, "map_inundation_boundaries", candidate)
    return state


def _raw_run(inputs, output, references=None, **kwargs):
    hdf, terrain, terrain_hdf = inputs
    return comparison.run(hdf, terrain, output, terrain_hdf=terrain_hdf,
        native_boundaries=references, method="native_serial", allow_unqualified=True,
        preserve_raw_geometry=True, max_working_mib=128, **kwargs)


def _forbid_overlays(monkeypatch):
    from shapely.geometry.base import BaseGeometry
    def fail(*args, **kwargs):
        pytest.fail("invalid raw comparison must not invoke geometry overlays or metrics")
    monkeypatch.setattr(comparison, "_metrics", fail)
    for name in ("difference", "union", "intersection", "hausdorff_distance"):
        monkeypatch.setattr(BaseGeometry, name, fail)
    monkeypatch.setattr(BaseGeometry, "area", property(fail))


@pytest.mark.parametrize("invalid_candidate", [False, True])
def test_raw_invalid_reference_still_maps_candidate_and_never_completes(inputs, raw_candidate,
        tmp_path, monkeypatch, invalid_candidate):
    from ras_commander.fim import FimGeometryError
    raw_candidate.invalid = invalid_candidate
    ref = write_polygon(tmp_path / "bad-ref.geojson", Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]))
    _forbid_overlays(monkeypatch)
    with pytest.raises(FimGeometryError) as caught:
        _raw_run(inputs, tmp_path / "raw-out", {"Max": ref})
    assert raw_candidate.calls == 1
    error = caught.value
    receipt = json.loads(Path(error.diagnostic_manifest).read_text())
    assert receipt["status"] == "aborted" and receipt["rows"] == []
    assert receipt["diagnostic_only"] and not receipt["normal_comparison_eligible"]
    assert receipt["complete_raw_profile_coverage"] and not receipt["raw_profile_missing"]
    assert not (tmp_path / "raw-out/boundary_comparison.csv").exists()
    row = receipt["raw_profiles"][0]
    assert row["candidate_topology_valid"] is (not invalid_candidate)
    assert row["reference_topology_valid"] is False
    assert row["raw_comparison"]["raw_ring_bits_equal"] is invalid_candidate
    assert all(Path(path).is_file() for path in error.artifacts)
    assert not any(key in row for key in ("geometry_equal", "candidate_area", "hausdorff_distance"))


def test_raw_invalid_candidate_valid_reference_is_diagnostic_only(inputs, raw_candidate, tmp_path, monkeypatch):
    from ras_commander.fim import FimGeometryError
    raw_candidate.invalid = True
    ref = write_polygon(tmp_path / "valid-ref.geojson", box(0, 0, 1, 1))
    _forbid_overlays(monkeypatch)
    with pytest.raises(FimGeometryError) as caught:
        _raw_run(inputs, tmp_path / "out", {"Max": ref})
    state = json.loads(Path(caught.value.diagnostic_manifest).read_text())
    assert state["raw_profiles"][0]["reference_topology_valid"] is True
    assert state["raw_profiles"][0]["candidate_topology_valid"] is False
    assert not state["raw_profiles"][0]["raw_comparison"]["raw_ring_bits_equal"]


def test_raw_valid_pair_still_returns_ordinary_metrics(inputs, raw_candidate, tmp_path):
    ref = write_polygon(tmp_path / "valid.geojson", box(0, 0, 1, 1))
    result = _raw_run(inputs, tmp_path / "out", {"Max": ref})
    assert isinstance(result, pd.DataFrame) and result.geometry_equal.tolist() == [True]
    assert json.loads((tmp_path / "out/boundary_comparison.json").read_text())["status"] == "complete"
    assert not (tmp_path / "out/raw_geometry").exists()


@pytest.mark.parametrize("failure", ["source", "interrupt", "engine"])
def test_raw_reference_cannot_mask_candidate_source_engine_or_interrupt(inputs, raw_candidate, tmp_path, failure):
    from ras_commander.fim import FimGeometryError, FimEngineError
    raw_candidate.invalid = True
    raw_candidate.failure = failure
    ref = write_polygon(tmp_path / "bad.geojson", Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]))
    expected = KeyboardInterrupt if failure == "interrupt" else (RuntimeError, FimEngineError)
    with pytest.raises(expected) as caught:
        _raw_run(inputs, tmp_path / "out", {"Max": ref})
    assert not isinstance(caught.value, FimGeometryError)
    state = json.loads((tmp_path / "out/boundary_comparison.json").read_text())
    assert state["status"] == "aborted" and not state.get("complete_raw_profile_coverage", False)
    assert not state.get("rows")


def test_raw_partial_profile_coverage_cannot_produce_normal_success(inputs, raw_candidate, tmp_path):
    from ras_commander.fim import FimGeometryError
    raw_candidate.invalid, raw_candidate.missing = True, {"saved"}
    ref = write_polygon(tmp_path / "ref.geojson", box(0, 0, 1, 1))
    with pytest.raises(FimGeometryError) as caught:
        _raw_run(inputs, tmp_path / "out", {"Max": ref, "saved": ref}, profiles={"Max": "Max", "saved": 108})
    state = json.loads(Path(caught.value.diagnostic_manifest).read_text())
    assert not state["complete_raw_profile_coverage"]
    assert state["raw_profile_missing"] == ["saved"] and state["rows"] == []
    missing = state["raw_profiles"][1]
    assert not missing["candidate_available"] and "raw_comparison" not in missing
    assert not missing["normal_comparison_eligible"]


def test_raw_artifact_tampering_is_source_failure_not_geometry_result(inputs, raw_candidate, tmp_path):
    from ras_commander.fim import FimGeometryError
    raw_candidate.invalid = raw_candidate.tamper = True
    ref = write_polygon(tmp_path / "ref.geojson", box(0, 0, 1, 1))
    with pytest.raises(RuntimeError, match="artifact changed") as caught:
        _raw_run(inputs, tmp_path / "out", {"Max": ref})
    assert not isinstance(caught.value, FimGeometryError)


def test_raw_generated_reference_waits_for_verified_candidate_then_retains(inputs, raw_candidate, tmp_path, monkeypatch):
    from ras_commander import StoreMapPerformanceOptions
    from ras_commander.fim import FimGeometryError
    raw_candidate.invalid = True
    ref = write_polygon(tmp_path / "generated.geojson", Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]))
    calls = []
    def generate(*args, **kwargs):
        assert raw_candidate.calls == 1
        calls.append(True)
        return {"Max": ref}, {"Max": "Max"}, {"Max": .25}
    monkeypatch.setattr(comparison, "_generate_native", generate)
    _forbid_overlays(monkeypatch)
    with pytest.raises(FimGeometryError) as caught:
        _raw_run(inputs, tmp_path / "out", native_performance=StoreMapPerformanceOptions(native_polygon_serial=True))
    assert calls == [True]
    state = json.loads(Path(caught.value.diagnostic_manifest).read_text())
    assert state["raw_profiles"][0]["raw_comparison"]["raw_ring_bits_equal"]


@pytest.mark.parametrize("bad", ["unclosed", "nonfinite", "wrongcrs"])
def test_raw_malformed_reference_is_not_typed_topology_refusal(inputs, raw_candidate, tmp_path, bad):
    from ras_commander.fim import FimGeometryError
    ref = write_polygon(tmp_path / "bad.geojson", Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]))
    data = json.loads(ref.read_text())
    if bad == "unclosed": data["features"][0]["geometry"]["coordinates"][0][-1] = [9, 9]
    if bad == "nonfinite": data["features"][0]["geometry"]["coordinates"][0][0][0] = float("nan")
    if bad == "wrongcrs": data["crs"]["properties"]["name"] = "EPSG:4326"
    ref.write_text(json.dumps(data))
    with pytest.raises((ValueError, RuntimeError)) as caught:
        _raw_run(inputs, tmp_path / "out", {"Max": ref})
    assert not isinstance(caught.value, FimGeometryError)
    assert raw_candidate.calls == 0



def test_raw_pair_budget_refusal_precedes_candidate_and_retention(inputs, raw_candidate, tmp_path):
    from ras_commander.fim import FimGeometryError
    ref = write_polygon(tmp_path / "bad.geojson", Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]))
    hdf, terrain, terrain_hdf = inputs
    with pytest.raises(ValueError, match="budget") as caught:
        comparison.run(hdf, terrain, tmp_path / "out", terrain_hdf=terrain_hdf,
            native_boundaries={"Max": ref}, method="native_serial", allow_unqualified=True,
            preserve_raw_geometry=True, max_working_mib=1)
    assert not isinstance(caught.value, FimGeometryError) and raw_candidate.calls == 0
    assert not (tmp_path / "out/raw_geometry").exists()


def test_raw_invalid_reference_does_not_mask_interrupt_if_manifest_write_fails(inputs,
        raw_candidate, tmp_path, monkeypatch):
    raw_candidate.failure = "interrupt"
    ref = write_polygon(tmp_path / "bad.geojson", Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]))
    original = comparison._atomic_json
    def write(path, state):
        if state.get("status") == "aborted":
            raise OSError("injected aborted receipt write failure")
        return original(path, state)
    monkeypatch.setattr(comparison, "_atomic_json", write)
    with pytest.raises(KeyboardInterrupt, match="owned interrupt"):
        _raw_run(inputs, tmp_path / "out", {"Max": ref})
