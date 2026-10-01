"""Exercise the breakout/native handoff with real geometry text and HDF data."""

import hashlib
from pathlib import Path
from shutil import copyfile
from types import SimpleNamespace

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon, box

from ras_commander import (
    Breakout2DCloneResult,
    Breakout2DPreflight,
    Breakout2DSpec,
    RasBreakout2D,
)
from ras_commander.geom import GeomMesh, GeomStorage
from ras_commander.geom.GeomPreprocessor import GeomPreprocessor
from ras_commander.gui.workflows import MeshRegenerationWorkflow

RR = "Geometry/2D Flow Area Refinement Regions"
BL = "Geometry/2D Flow Area Break Lines"
CRS = "EPSG:3857"


def _text_breaklines(path):
    lines = path.read_text().splitlines()
    result = []
    for index, line in enumerate(lines):
        if not line.startswith("BreakLine Name="):
            continue
        cursor = index + 1
        while not lines[cursor].startswith("BreakLine Polyline="):
            cursor += 1
        count = int(lines[cursor].split("=", 1)[1])
        values = []
        while len(values) < count * 2:
            cursor += 1
            row = lines[cursor]
            values.extend(
                float(row[offset : offset + 16])
                for offset in range(0, len(row), 16)
                if row[offset : offset + 16].strip()
            )
        coordinates = list(zip(values[::2], values[1::2]))
        result.append((line.split("=", 1)[1], LineString(coordinates)))
    return result


def _sync_native_hdf(path):
    """Stand in for native import, retaining the HDF-only refinement group."""
    perimeter = GeomStorage.get_storage_area_polygons(
        path, exclude_2d=False
    ).geometry.iloc[0]
    coords = np.asarray(perimeter.exterior.coords)
    with h5py.File(Path(str(path) + ".hdf"), "a") as hdf:
        key = "Geometry/2D Flow Areas"
        if key in hdf:
            del hdf[key]
        areas = hdf.create_group(key)
        dtype = [
            ("Name", "S64"),
            ("Spacing dx", "f4"),
            ("Spacing dy", "f4"),
            ("Cell Count", "i4"),
        ]
        areas.create_dataset(
            "Attributes", data=np.array([(b"Area", 1, 1, 0)], dtype=dtype)
        )
        areas.create_dataset(
            "Polygon Info", data=np.array([[0, len(coords), 0, 1]], dtype="i4")
        )
        areas.create_dataset(
            "Polygon Parts", data=np.array([[0, len(coords)]], dtype="i4")
        )
        areas.create_dataset("Polygon Points", data=coords)
        areas.create_group("Area").create_dataset(
            "Cells Center Coordinate", data=np.empty((0, 2))
        )
        if BL in hdf:
            del hdf[BL]
        breaklines = _text_breaklines(path)
        if breaklines:
            group = hdf.create_group(BL)
            group.create_dataset(
                "Attributes",
                data=np.array(
                    [(name.encode(),) for name, _ in breaklines],
                    dtype=[("Name", "S64")],
                ),
            )
            points, info, parts = [], [], []
            for index, (_, geometry) in enumerate(breaklines):
                xy = list(geometry.coords)
                info.append((len(points), len(xy), index, 1))
                parts.append((0, len(xy)))
                points.extend(xy)
            group.create_dataset("Polyline Info", data=np.array(info, dtype="i4"))
            group.create_dataset("Polyline Parts", data=np.array(parts, dtype="i4"))
            group.create_dataset("Polyline Points", data=np.asarray(points))


def _fixture(tmp_path, all_dropped=False):
    source = tmp_path / "source"
    working = tmp_path / "working"
    source.mkdir()
    working.mkdir()
    geometry = source / "Model.g01"
    geometry.write_text("Geom Title=Feature Handoff\nProgram Version=6.60\n")
    parent, child = box(0, 0, 100, 100), box(10, 10, 90, 90)
    GeomStorage.set_2d_flow_area_perimeter(
        geometry,
        "Area",
        geometry=parent,
        point_generation_data=[None, None, 1, 1],
        create_backup=False,
    )
    breaklines = [
        LineString([(0, 50), (100, 50)]),
        LineString([(20, 60), (80, 60)]),
        LineString([(95, 20), (95, 80)]),
    ]
    names = ["Crossing", "Retained", "Dropped"]
    GeomStorage.replace_breaklines(
        geometry,
        "Area",
        [
            {
                "name": name,
                "coords": list(line.coords),
                "cell_size_near": 2,
                "cell_size_far": 4,
                "near_repeats": 1,
                "protection_radius": 0,
            }
            for name, line in zip(names, breaklines)
        ],
        create_backup=False,
    )
    _sync_native_hdf(geometry)
    regions = [box(0, 20, 40, 40), box(30, 60, 50, 80), box(95, 20, 99, 30)]
    GeomMesh.replace_refinement_regions(
        geometry,
        [
            {
                "name": name,
                "polygon": polygon,
                "spacing_dx": index + 2,
                "spacing_dy": index + 3,
            }
            for index, (name, polygon) in enumerate(zip(names, regions))
        ],
        create_backup=False,
    )
    plan, unsteady = source / "Model.p01", source / "Model.u01"
    plan.write_bytes(b"Plan Title=Source\r\nGeom File=g01\r\n")
    unsteady.write_bytes(b"Flow Title=Source\r\nBoundary Location=Area,Parent BC\r\n")
    clone_geometry = working / "Model.g02"
    copyfile(geometry, clone_geometry)
    copyfile(Path(str(geometry) + ".hdf"), Path(str(clone_geometry) + ".hdf"))
    clone_plan, clone_unsteady = working / "Model.p02", working / "Model.u02"
    copyfile(plan, clone_plan)
    copyfile(unsteady, clone_unsteady)
    digest = hashlib.sha256(unsteady.read_bytes()).hexdigest()
    clone = Breakout2DCloneResult(
        "01",
        "01",
        "01",
        "02",
        "02",
        "02",
        clone_plan,
        clone_geometry,
        Path(str(clone_geometry) + ".hdf"),
        clone_unsteady,
        digest,
        digest,
    )
    features = {
        kind: gpd.GeoDataFrame(geometry=[], crs=CRS)
        for kind in (
            "bc_line",
            "breakline",
            "refinement_region",
            "reference_line",
            "reference_point",
        )
    }
    features["breakline"] = gpd.GeoDataFrame(
        {
            "bl_id": [0, 1, 2],
            "Name": names,
            "cell_spacing_near": [2] * 3,
            "cell_spacing_far": [4] * 3,
            "near_repeats": [1] * 3,
            "protection_radius": [0] * 3,
        },
        geometry=breaklines,
        crs=CRS,
    )
    features["refinement_region"] = gpd.GeoDataFrame(
        {"rr_id": [0, 1, 2], "Name": names},
        geometry=regions,
        crs=CRS,
    )
    actions = []
    for kind, geometries in [("breakline", breaklines), ("refinement_region", regions)]:
        for index, (name, original) in enumerate(zip(names, geometries)):
            retained = original.intersection(child.buffer(-1))
            if kind == "refinement_region" and all_dropped:
                retained = Polygon()
            measure = original.area if kind == "refinement_region" else original.length
            kept = retained.area if kind == "refinement_region" else retained.length
            actions.append(
                {
                    "feature_type": kind,
                    "feature_id": str(index),
                    "name": name,
                    "action": "drop"
                    if retained.is_empty
                    else "keep"
                    if retained.equals(original)
                    else "clip",
                    "reason": "planned containment",
                    "source_measure": measure,
                    "retained_measure": kept,
                    "retained_fraction": kept / measure,
                    "geometry": None if retained.is_empty else retained,
                }
            )
    preflight = Breakout2DPreflight(
        spec=Breakout2DSpec("01", "Area", child, "handoff", child_boundary_crs=CRS),
        source_plan_path=plan,
        source_plan_hdf=None,
        source_geometry_number="01",
        source_geometry_path=geometry,
        source_geometry_hdf=Path(str(geometry) + ".hdf"),
        source_unsteady_number="01",
        source_unsteady_path=unsteady,
        base_cell_size=1,
        parent_boundary=gpd.GeoDataFrame(
            {"mesh_name": ["Area"]}, geometry=[parent], crs=CRS
        ),
        child_boundary=gpd.GeoDataFrame(geometry=[child], crs=CRS),
        boundary_segments=RasBreakout2D.classify_boundary_segments(
            parent, child, crs=CRS
        ),
        feature_actions=gpd.GeoDataFrame(actions, geometry="geometry", crs=CRS),
        existing_boundaries=pd.DataFrame(),
        checks=pd.DataFrame(
            [{"check_id": "ready", "passed": True, "blocking": True, "message": "ok"}]
        ),
        source_features=features,
    )
    ras = SimpleNamespace(
        project_folder=working,
        project_name="Model",
        check_initialized=lambda: None,
        geom_df=pd.DataFrame([{"geom_number": "02", "full_path": str(clone_geometry)}]),
    )
    ras.get_prj_entries = lambda _kind: ras.geom_df
    return preflight, clone, ras


def _assert_planned_files(preflight, clone):
    perimeter = GeomStorage.get_storage_area_polygons(
        clone.geometry_path, exclude_2d=False
    )
    assert perimeter.geometry.iloc[0].equals(preflight.child_boundary.geometry.iloc[0])
    actual_breaklines = _text_breaklines(clone.geometry_path)
    expected_breaklines = preflight.feature_actions.query(
        "feature_type == 'breakline' and action != 'drop'"
    )
    assert [name for name, _ in actual_breaklines] == expected_breaklines.name.tolist()
    for (_, actual), expected in zip(actual_breaklines, expected_breaklines.geometry):
        assert actual.equals(expected)
    expected_regions = preflight.feature_actions.query(
        "feature_type == 'refinement_region' and action != 'drop'"
    )
    with h5py.File(clone.geometry_hdf, "r") as hdf:
        if expected_regions.empty:
            assert RR not in hdf
            return
        group = hdf[RR]
        attributes = group["Attributes"][()]
        assert [
            row["Name"].decode() for row in attributes
        ] == expected_regions.name.tolist()
        info, points = group["Polygon Info"][()], group["Polygon Points"][()]
        for index, (_, expected) in enumerate(expected_regions.iterrows()):
            start, count = info[index][:2]
            assert Polygon(points[start : start + count]).equals(expected.geometry)
            fid = int(expected.feature_id)
            assert float(attributes[index]["Spacing dx"]) == fid + 2
            assert float(attributes[index]["Spacing dy"]) == fid + 3


def _patch_points(monkeypatch, callback):
    monkeypatch.setattr(GeomMesh, "generate_computation_points", staticmethod(callback))


@pytest.mark.parametrize("method", ["rasexe", "rasmapper"])
@pytest.mark.parametrize(
    "all_dropped", [False, True], ids=["clip_keep_drop", "all_refinements_dropped"]
)
def test_native_refresh_receives_planned_features(
    tmp_path, monkeypatch, method, all_dropped
):
    preflight, clone, ras = _fixture(tmp_path, all_dropped)
    source_bytes = {
        path: path.read_bytes()
        for path in (
            preflight.source_plan_path,
            preflight.source_geometry_path,
            preflight.source_geometry_hdf,
            preflight.source_unsteady_path,
            clone.unsteady_path,
        )
    }
    evidence = preflight.feature_actions.copy(deep=True)
    order = []

    def points(*args, **kwargs):
        order.append("points")
        _assert_planned_files(preflight, clone)
        return SimpleNamespace(status="success", cell_count=10, error_message=None)

    def refresh(*args, **kwargs):
        order.append("refresh")
        _assert_planned_files(preflight, clone)
        _sync_native_hdf(clone.geometry_path)
        if method == "rasmapper":
            # RAS Mapper recreates HDF from text, which carries no refinements.
            with h5py.File(clone.geometry_hdf, "a") as hdf:
                if RR in hdf:
                    del hdf[RR]
        return SimpleNamespace(success=True, error=None, first_error_line=None)

    def mesh(*args, **kwargs):
        order.append("mesh")
        _assert_planned_files(preflight, clone)
        return SimpleNamespace(ok=True, error_message=None)

    _patch_points(monkeypatch, points)
    monkeypatch.setattr(
        GeomPreprocessor, "run_geometry_preprocessor", staticmethod(refresh)
    )
    monkeypatch.setattr(
        MeshRegenerationWorkflow,
        "refresh_geometry_hdf_from_text",
        staticmethod(refresh),
    )
    monkeypatch.setattr(GeomMesh, "generate", staticmethod(mesh))
    result = RasBreakout2D.prepare_cloned_geometry(
        preflight, clone, ras_object=ras, refresh_method=method
    )
    assert order == (
        ["points", "refresh", "mesh"] if method == "rasexe" else ["refresh", "mesh"]
    )
    assert result.boundaries_unchanged
    assert result.retained_breakline_count == 2
    assert result.retained_refinement_region_count == (0 if all_dropped else 2)
    assert result.retained_reference_line_count == 0
    assert result.containment_result.ok
    pd.testing.assert_frame_equal(result.feature_actions, evidence)
    pd.testing.assert_frame_equal(preflight.feature_actions, evidence)
    assert all(path.read_bytes() == content for path, content in source_bytes.items())


@pytest.mark.parametrize("method", ["rasexe", "rasmapper"])
def test_refresh_exception_keeps_original_cause(tmp_path, monkeypatch, method):
    preflight, clone, ras = _fixture(tmp_path)
    original = OSError("native refresh failed")

    def refresh(*args, **kwargs):
        raise original

    _patch_points(
        monkeypatch, lambda *a, **kw: SimpleNamespace(status="success", cell_count=10)
    )
    monkeypatch.setattr(
        GeomPreprocessor, "run_geometry_preprocessor", staticmethod(refresh)
    )
    monkeypatch.setattr(
        MeshRegenerationWorkflow,
        "refresh_geometry_hdf_from_text",
        staticmethod(refresh),
    )
    with pytest.raises(RuntimeError, match="refresh failed") as caught:
        RasBreakout2D.prepare_cloned_geometry(
            preflight, clone, ras_object=ras, refresh_method=method
        )
    assert caught.value.__cause__ is original


def test_gui_failure_result_keeps_exception_cause(tmp_path, monkeypatch):
    preflight, clone, ras = _fixture(tmp_path)
    original = OSError("native returned failure")
    monkeypatch.setattr(
        MeshRegenerationWorkflow,
        "refresh_geometry_hdf_from_text",
        staticmethod(lambda *a, **kw: SimpleNamespace(success=False, error=original)),
    )
    with pytest.raises(RuntimeError, match="refresh failed") as caught:
        RasBreakout2D.prepare_cloned_geometry(preflight, clone, ras_object=ras)
    assert caught.value.__cause__ is original
