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


def test_native_failure_restores_rasmap(tmp_path, monkeypatch):
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
    monkeypatch.setattr(RasMap, "list_terrain_layers", lambda *a, **k: pd.DataFrame([dict(name="terrain", resolved_path=str(terrain))]))
    def fail(*args, **kwargs):
        rasmap.write_bytes(b"temporary mutation")
        raise RuntimeError("native failed")
    monkeypatch.setattr(RasProcess, "store_maps", fail)
    state = {}
    with pytest.raises(RuntimeError, match="native failed"):
        comparison._generate_native(hdf, terrain, tmp_path / "out", {"Max": "Max"},
            "sloping", "02", None, obj, None, 1, state)
    assert rasmap.read_bytes() == b"original bytes"
    assert state["rasmap_restored"]
    assert state["rasmap_sha256_before"] == state["rasmap_sha256_after"]


def test_holes_survive_aoi_clip():
    candidate = Polygon(box(0, 0, 10, 10).exterior.coords, [box(3, 3, 7, 7).exterior.coords])
    clipped = comparison._polygonal(candidate.intersection(box(1, 1, 9, 9)))
    assert comparison._stats(clipped)[:2] == (1, 1)
    assert clipped.area == 48


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
    assert not result["quantized_coordinates_equal"]
