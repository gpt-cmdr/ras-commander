"""Refinement clipping and saved-point constraint regressions."""

import json
import os
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import Polygon, box
from test_geom_mesh import (
    MockPointM,
    MockPointMs,
    MockPolygon,
    _mock_generate_success,
    _write_containment_fixture,
)

gm = import_module("ras_commander.geom.GeomMesh")
PATCH = Path(__file__).parent / "fixtures/refinement_constraints/local_patch.json"


def test_constraint_default_excludes_regions_and_retains_structures():
    class Layer:
        def __init__(self, name):
            self.features = []

        def AddFeature(self, feature):
            self.features.append(feature)

        def CopyToMultiPartPolyline(self):
            return self.features

    features = SimpleNamespace(
        BreakLines=SimpleNamespace(Polylines=lambda: ["breakline"]),
        MeshRegions=SimpleNamespace(Polygons=lambda: ["region"]),
        Structures=SimpleNamespace(Polylines=lambda: ["structure"]),
    )
    area = SimpleNamespace(Geometry=features)
    ns = {
        "PolylineFeatureLayer": Layer,
        "Polyline": SimpleNamespace(IsValidPolyline=lambda feature: True),
    }
    assert gm._build_breaklines(area, ns) == ["breakline", "structure"]
    assert gm._build_breaklines(area, ns, True) == ["breakline", "region", "structure"]


def test_clip_keeps_native_properties_and_reports_fragments(tmp_path):
    path, hdf_path = _write_containment_fixture(tmp_path)
    patch = json.loads(PATCH.read_text())
    native = {
        "spacing_dx": 100.0,
        "spacing_dy": 75.0,
        "perimeter_spacing": 25.0,
        "near_repeats": 2,
        "far_spacing": 200.0,
        "protection_radius": 1,
        "shift_dx": 3.0,
        "shift_dy": 4.0,
    }
    source = [
        dict(name="trimmed", polygon=Polygon(patch["regions"][0]), **native),
        dict(name="large", polygon=box(-100, -100, 1100, 1100), **native),
        dict(name="tiny", polygon=box(10, 10, 11, 11), **native),
        dict(name="touch", polygon=box(-10, 20, 0, 30), **native),
    ]
    gm.GeomMesh.replace_refinement_regions(path, source)
    before = hdf_path.read_bytes()
    regions, report = gm.GeomMesh.clip_refinement_regions(path, box(0, 0, 500, 500))
    assert hdf_path.read_bytes() == before
    assert report.set_index("name").loc["large", "status"] == "clipped"
    assert report.set_index("name").loc["tiny", "status"] == "kept"
    assert report.set_index("name").loc["tiny", "below_one_cell_area"]
    assert report.set_index("name").loc["touch", "reason"] == "no_polygon_overlap"
    assert all(box(0, 0, 500, 500).covers(r["polygon"]) for r in regions)
    assert all(all(r[k] == v for k, v in native.items()) for r in regions)
    gm.GeomMesh.replace_refinement_regions(path, regions)
    regions_again, _ = gm.GeomMesh.clip_refinement_regions(path, box(0, 0, 500, 500))
    assert all(all(r[k] == v for k, v in native.items()) for r in regions_again)
    _, cutoff = gm.GeomMesh.clip_refinement_regions(
        path, box(0, 0, 500, 500), min_area=2
    )
    assert cutoff.set_index("name").loc["tiny", "reason"] == "below_min_area"


def test_clip_splits_disconnected_intersection_and_preserves_empty_schema(tmp_path):
    path, _ = _write_containment_fixture(tmp_path)
    # A connected U intersects the child in two disconnected legs.
    region = Polygon(
        [
            (0, 0),
            (40, 0),
            (40, 40),
            (30, 40),
            (30, 10),
            (10, 10),
            (10, 40),
            (0, 40),
            (0, 0),
        ]
    )
    gm.GeomMesh.replace_refinement_regions(
        path, [{"name": "u", "polygon": region, "spacing_dx": 10}]
    )
    regions, report = gm.GeomMesh.clip_refinement_regions(path, box(-5, 20, 45, 50))
    assert len(regions) == 2
    assert report.iloc[0].output_fids == [0, 1]
    assert report.iloc[0].status == "clipped"
    gm.GeomMesh.replace_refinement_regions(path, [])
    regions, report = gm.GeomMesh.clip_refinement_regions(path, box(0, 0, 100, 100))
    assert regions == [] and report.empty and "reason" in report.columns


def test_native_extent_gate_allows_large_and_touching_regions(tmp_path):
    path, _ = _write_containment_fixture(
        tmp_path,
        refinement_regions=[
            ("large", list(box(-100, -100, 1100, 1100).exterior.coords))
        ],
    )
    assert gm.GeomMesh.audit_domain_containment(path).ok
    assert not gm.GeomMesh.audit_domain_containment(
        path, strict_refinement_containment=True
    ).ok


def test_seed_patch_refreshes_only_target_native_timestamp(monkeypatch, tmp_path):
    path, _ = _write_containment_fixture(tmp_path)
    old = "01Jan2020 00:00:00"
    text = path.read_text().replace(
        "Storage Area 2D Points=",
        f"Storage Area 2D PointsPerimeterTime={old}\nStorage Area 2D Points=",
    )
    text += f"Storage Area=Other,0,0\nStorage Area 2D PointsPerimeterTime={old}\n"
    path.write_text(text)
    from ras_commander.geom.GeomStorage import GeomStorage

    monkeypatch.setattr(GeomStorage, "_current_timestamp", lambda: old)
    gm._patch_text_seeds(path, np.array([[300.0, 300.0]]), mesh_name="MainArea")
    result = path.read_text()
    assert "Storage Area 2D PointsPerimeterTime=01Jan2020 00:00:01" in result
    assert (
        f"Storage Area=Other,0,0\nStorage Area 2D PointsPerimeterTime={old}" in result
    )


def test_generate_filters_region_points_and_persists_ratio(monkeypatch, tmp_path):
    path = tmp_path / "filter.g01"
    path.write_text(
        "Geom Title=Point filtering\nStorage Area=MainArea,0,0\n"
        "Storage Area Is2D=-1\nStorage Area Point Generation Data=,,50,50\n"
        "Storage Area 2D Points=0\n"
    )
    captured = _mock_generate_success(monkeypatch, path, has_breaklines=False)
    points = MockPointMs()
    for x, y in [(10, 10), (20, 20), (0, 20), (-10, 20)]:
        points.Add(MockPointM(x, y))
    monkeypatch.setattr(gm, "_generate_seeds_via_net", lambda *args, **kwargs: points)
    compute = gm._compute_mesh

    def check_seeds(perimeter, seeds, *args):
        assert seeds.Count == 2
        assert [(seeds[i].X, seeds[i].Y) for i in range(2)] == [(10, 10), (20, 20)]
        return compute(perimeter, seeds, *args)

    monkeypatch.setattr(gm, "_compute_mesh", check_seeds)
    captured[
        "geom"
    ].D2FlowArea.Geometry.MeshPerimeters.Polygon.return_value = MockPolygon(
        [(0, 0), (100, 0), (100, 100), (0, 100)]
    )
    result = gm.GeomMesh.generate(path, min_face_length_ratio=0.1)
    assert result.ok
    assert "removed_2_outside_or_boundary_seeds" in result.fixes_applied
    from ras_commander.geom import GeomStorage

    settings = GeomStorage.get_2d_flow_area_settings(path)
    assert (
        settings.loc[settings.name == "MainArea", "min_face_length_ratio"].iloc[0]
        == 0.1
    )


def test_replace_rejects_holes_before_writing(tmp_path):
    path, hdf = _write_containment_fixture(tmp_path)
    before = hdf.read_bytes()
    polygon = Polygon(
        box(10, 10, 100, 100).exterior.coords, [box(20, 20, 30, 30).exterior.coords]
    )
    with pytest.raises(ValueError, match="interior rings"):
        gm.GeomMesh.replace_refinement_regions(
            path, [{"polygon": polygon, "spacing_dx": 10}]
        )
    assert hdf.read_bytes() == before


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RAS_COMMANDER_RUN_HECRAS_INTEGRATION") != "1",
    reason="Opt-in native HEC-RAS 6.6 mesher regression",
)
def test_trimmed_real_mesh_exposes_masked_ninth_face():
    data = json.loads(PATCH.read_text())
    gm._load_dlls(os.environ.get("RAS_COMMANDER_HECRAS_DIR"))
    ns = gm._imports()

    def points(coords):
        out = ns["PointMs"]()
        for x, y in coords:
            out.Add(ns["PointM"](float(x), float(y)))
        return out

    lines = [ns["Polyline"](points(coords)) for coords in data["breaklines"]]
    regions = [ns["Polygon"](points(coords)) for coords in data["regions"]]
    geometry = SimpleNamespace(
        BreakLines=SimpleNamespace(Polylines=lambda: lines),
        MeshRegions=SimpleNamespace(Polygons=lambda: regions),
        Structures=SimpleNamespace(Polylines=list),
    )
    perimeter, seeds = ns["Polygon"](points(data["perimeter"])), points(data["points"])
    target = int(np.linalg.norm(data["points"], axis=1).argmin())
    for mode, expected in [(False, "breaklines"), (True, "mapper")]:
        constraints = gm._build_breaklines(SimpleNamespace(Geometry=geometry), ns, mode)
        mesh = gm._compute_mesh(perimeter, seeds, constraints, 0.05, ns)
        assert str(mesh.MeshCompletionState) == data["expected"][expected]["state"]
        assert (
            int(mesh.CellFacesCount(target))
            == data["expected"][expected]["target_sides"]
        )
