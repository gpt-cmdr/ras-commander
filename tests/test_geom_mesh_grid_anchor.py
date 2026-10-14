"""Grid anchor for 2D mesh regeneration and the breakout breakline crossing rule.

RAS Mapper starts a 2D area's regular computation-point grid half a cell
inside the area's bounding box. ``GeomMesh.generate(grid_anchor=...)`` lays the
grid on another area's lattice instead. The unit tests cover the anchor record,
reading it from a compiled geometry HDF, input validation and the breakout
crossing rule. The opt-in native test runs RAS Mapper's point generator on a
public example (Windows, HEC-RAS 6.6).
"""

import os
import platform
import shutil
from importlib import import_module
from pathlib import Path

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon, box

from ras_commander import Breakout2DSpec, GridAnchor
from ras_commander.geom import GeomMesh

gm = import_module("ras_commander.geom.GeomMesh")
b2d = import_module("ras_commander.RasBreakout2D")


def _write_geometry_hdf(path, areas):
    """Minimal compiled-geometry layout: names, spacing and perimeter rings."""
    dtype = np.dtype([("Name", "S16"), ("Spacing dx", "<f4"), ("Spacing dy", "<f4")])
    attrs = np.array([(name.encode(), dx, dy) for name, dx, dy, _ in areas], dtype=dtype)
    points, info = [], []
    for *_, ring in areas:
        info.append([len(points), len(ring), 0, 1])
        points.extend(ring)
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group("Geometry/2D Flow Areas")
        group["Attributes"] = attrs
        group["Polygon Info"] = np.array(info, dtype=np.int32)
        group["Polygon Points"] = np.array(points, dtype=float)
    return path


RING_A = [(1000.0, 2000.0), (1950.0, 2000.0), (1950.0, 2700.0), (1000.0, 2700.0)]
RING_B = [(-500.5, 10.25), (100.0, 10.25), (100.0, 900.75)]


def test_grid_anchor_record_validates_and_reports_phase():
    anchor = GridAnchor(1050.0, 2650.0, 100.0, 100.0, source="parent")
    assert anchor.phase == pytest.approx((50.0, 50.0))
    assert anchor.to_dict()["phase"] == pytest.approx([50.0, 50.0])
    assert GridAnchor(-30.0, -10.0, 100.0, 50.0).phase == pytest.approx((70.0, 40.0))
    with pytest.raises(ValueError):
        GridAnchor(0.0, 0.0, 0.0, 1.0)
    with pytest.raises(ValueError):
        GridAnchor(float("nan"), 0.0, 1.0, 1.0)
    with pytest.raises(TypeError):
        GridAnchor(True, 0.0, 1.0, 1.0)


def test_get_grid_anchor_matches_rasmapper_lattice_origin(tmp_path):
    hdf = _write_geometry_hdf(
        tmp_path / "Model.g01.hdf",
        [("Parent", 100.0, 100.0, RING_A), ("Other", 50.0, 0.0, RING_B)],
    )
    anchor = GeomMesh.get_grid_anchor(hdf, mesh_name="Parent")
    # RAS Mapper: first point at (min x + dx/2, max y - dy/2).
    assert (anchor.x, anchor.y) == pytest.approx((1050.0, 2650.0))
    assert (anchor.spacing_dx, anchor.spacing_dy) == (100.0, 100.0)
    assert anchor.source == "Model.g01.hdf:Parent"
    other = GeomMesh.get_grid_anchor(hdf, mesh_index=1)
    # A non-positive Spacing dy falls back to Spacing dx, as in RAS Mapper.
    assert (other.x, other.y, other.spacing_dy) == pytest.approx((-475.5, 875.75, 50.0))
    # A geometry text path resolves to its compiled HDF.
    text = tmp_path / "Model.g01"
    text.write_text("Geom Title=Model\n", encoding="utf-8")
    assert GeomMesh.get_grid_anchor(text, mesh_name="Parent") == anchor
    with pytest.raises(ValueError, match="not found"):
        GeomMesh.get_grid_anchor(hdf, mesh_name="Missing")


def test_grid_anchor_input_is_checked():
    anchor = gm._coerce_grid_anchor((10.0, 20.0), 50.0)
    assert anchor == GridAnchor(10.0, 20.0, 50.0, 50.0)
    with pytest.raises(ValueError, match="differs from the mesh cell size"):
        gm._coerce_grid_anchor(GridAnchor(0.0, 0.0, 100.0, 100.0), 50.0)
    for bad in ("1,2", (1.0,), (1.0, "2"), None):
        with pytest.raises(TypeError):
            gm._coerce_grid_anchor(bad, 50.0)


def test_generate_rejects_bad_grid_anchor_before_meshing(tmp_path):
    text = tmp_path / "Model.g01"
    text.write_text("Geom Title=Model\n", encoding="utf-8")
    with pytest.raises(TypeError, match="grid_anchor"):
        GeomMesh.generate(text, grid_anchor="origin")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (LineString([(2, 2), (8, 8)]), 0),  # wholly inside
        (LineString([(5, 5), (15, 5)]), 1),  # one end outside
        (LineString([(-5, 5), (15, 5)]), 2),  # passes through
        (LineString([(-5, 2), (5, 2), (5, 12), (5.5, 12), (5.5, 2), (15, 2)]), 4),
        (LineString([(20, 20), (30, 30)]), 0),  # outside
    ],
)
def test_boundary_crossings(line, expected):
    assert b2d._boundary_crossings(line, box(0, 0, 10, 10)) == expected


def test_breakline_crossing_limit_drops_instead_of_clipping():
    parent = gpd.GeoDataFrame({"mesh_name": ["A"]}, geometry=[box(-20, -20, 30, 30)], crs=2277)
    child = box(0, 0, 10, 10)
    lines = gpd.GeoDataFrame(
        {"bl_id": [1, 2, 3, 4], "Name": ["inside", "one", "through", "zigzag"]},
        geometry=[
            LineString([(2, 2), (8, 8)]),
            LineString([(5, 5), (15, 5)]),
            LineString([(-5, 5), (15, 5)]),
            LineString([(-5, 2), (5, 2), (5, 12), (5.5, 12), (5.5, 2), (15, 2)]),
        ],
        crs=2277,
    )

    def actions(limit):
        frame = b2d._build_feature_actions(
            parent, child, {"breakline": lines}, pd.DataFrame(), child,
            max_breakline_perimeter_crossings=limit,
        )
        rows = frame[frame.feature_type.eq("breakline")].set_index("name")
        return rows.action.to_dict(), rows.reason.to_dict()

    action, _ = actions(None)
    assert action == {"inside": "keep", "one": "clip", "through": "clip", "zigzag": "clip"}
    action, reason = actions(1)
    assert action == {"inside": "keep", "one": "clip", "through": "drop", "zigzag": "drop"}
    assert reason["through"] == reason["zigzag"] == "exceeds_child_perimeter_crossing_limit"
    action, _ = actions(2)
    assert action["through"] == "clip" and action["zigzag"] == "drop"


def test_breakout_spec_validates_crossing_limit():
    child = box(0, 0, 10, 10)
    assert Breakout2DSpec("01", "A", child, "x").max_breakline_perimeter_crossings is None
    assert Breakout2DSpec("01", "A", child, "x", max_breakline_perimeter_crossings=1)
    for bad in (-1, 1.5, True):
        with pytest.raises(ValueError):
            Breakout2DSpec("01", "A", child, "x", max_breakline_perimeter_crossings=bad)


def _hecras_dir():
    hd = Path(os.environ.get("RAS_COMMANDER_HECRAS_DIR", r"C:\Program Files (x86)\HEC\HEC-RAS\6.6"))
    if not (hd / "RasMapperLib.dll").is_file():
        pytest.skip("Configured HEC-RAS installation is unavailable")
    return hd


@pytest.mark.integration
@pytest.mark.destructive_copy
@pytest.mark.slow
@pytest.mark.skipif(
    platform.system() != "Windows"
    or os.environ.get("RAS_COMMANDER_RUN_HECRAS_INTEGRATION") != "1",
    reason="Requires Windows, HEC-RAS 6.6 and explicit integration opt-in",
)
def test_anchored_point_generation_native(tmp_path):
    """Own anchor reproduces RAS Mapper exactly; another anchor moves the lattice."""
    from shapely import contains_xy

    from ras_commander import RasExamples, init_ras_project

    hd = _hecras_dir()
    project = RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=tmp_path, suffix="anchor")
    gm._load_dlls(hd)
    ns = gm._imports()

    def xy(points):
        return np.array([(float(points[i].X), float(points[i].Y)) for i in range(points.Count)])

    def on_lattice(points, anchor):
        px, py = anchor.phase
        rx = np.abs(((points[:, 0] - px + anchor.spacing_dx / 2) % anchor.spacing_dx) - anchor.spacing_dx / 2)
        ry = np.abs(((points[:, 1] - py + anchor.spacing_dy / 2) % anchor.spacing_dy) - anchor.spacing_dy / 2)
        return (rx < 1e-6) & (ry < 1e-6)

    # Single 2D area (g12): anchored generation with the area's own anchor is RAS Mapper's own result.
    hdf = tmp_path / "g12.hdf"
    shutil.copy2(project / "BaldEagleDamBrk.g12.hdf", hdf)
    own = GeomMesh.get_grid_anchor(hdf, mesh_name="BaldEagleCr")
    native = xy(gm._generate_seeds_via_net(str(hdf), ns))
    evidence = {}
    anchored = xy(gm._generate_seeds_via_net(str(hdf), ns, grid_anchor=own, evidence=evidence))
    assert len(native) == len(anchored) == evidence["lattice_points"]
    assert np.array_equal(np.sort(native, axis=0), np.sort(anchored, axis=0))
    shifted = GridAnchor(own.x + 0.37 * own.spacing_dx, own.y - 0.21 * own.spacing_dy, own.spacing_dx, own.spacing_dy)
    moved = xy(gm._generate_seeds_via_net(str(hdf), ns, grid_anchor=shifted))
    assert on_lattice(moved, shifted).all() and not on_lattice(moved, own).any()

    # Two 2D areas (g11): the anchored area moves with its breakline rows; the other area is RAS Mapper's own.
    hdf = tmp_path / "g11.hdf"
    shutil.copy2(project / "BaldEagleDamBrk.g11.hdf", hdf)
    a = GeomMesh.get_grid_anchor(hdf, mesh_name="BaldEagleCr")
    shifted = GridAnchor(a.x + 0.37 * a.spacing_dx, a.y - 0.21 * a.spacing_dy, a.spacing_dx, a.spacing_dy)
    evidence = {}
    moved = xy(gm._generate_seeds_via_net(str(hdf), ns, fid=0, grid_anchor=shifted, evidence=evidence))
    with h5py.File(hdf, "r") as h:
        info = h["Geometry/2D Flow Areas/Polygon Info"][()]
        ring = h["Geometry/2D Flow Areas/Polygon Points"][()]
    area = Polygon(ring[info[0][0] : info[0][0] + info[0][1]])
    inside = moved[contains_xy(area, moved[:, 0], moved[:, 1])]
    share = on_lattice(inside, shifted).mean()
    assert 0.9 < share < 1.0  # lattice plus breakline rows
    assert evidence["area_points_after_enforcement"] != evidence["lattice_points"]

    # End to end: generate() writes the anchored points to the geometry text.
    ras = init_ras_project(project, hd / "Ras.exe", hide_intro=True, accept_tcu=True, load_results_summary=False)
    base = GeomMesh.get_grid_anchor("02", mesh_name="BaldEagleCr", ras_object=ras)
    anchor = GridAnchor(base.x + 46.25, base.y - 26.25, 125.0, 125.0)
    result = GeomMesh.generate(
        "02", mesh_name="BaldEagleCr", cell_size=125, hecras_dir=hd, ras_object=ras, grid_anchor=anchor,
    )
    assert result.ok, result.error_message
    assert result.grid_anchor["anchor"]["phase"] == pytest.approx(list(anchor.phase))
    assert "grid_anchor:lattice_phase_locked" in result.fixes_applied
    with pytest.raises(TypeError):
        GeomMesh.generate("02", mesh_name="BaldEagleCr", ras_object=ras, grid_anchor=[1, 2, 3])
