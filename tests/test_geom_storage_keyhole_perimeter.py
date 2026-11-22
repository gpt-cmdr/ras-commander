"""Keyhole perimeter rings for 2D flow areas with excluded areas."""

import itertools
import logging
import os
import platform
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, box

from ras_commander import RasExamples
from ras_commander.geom import GeomStorage
from ras_commander.geom._keyhole import build_keyhole_ring, validate_keyhole_ring

HECRAS_INTEGRATION_ENV = "RAS_COMMANDER_RUN_HECRAS_INTEGRATION"
OUTER = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
HOLE = [(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)]
HOLE2 = [(70.0, 70.0), (85.0, 70.0), (85.0, 85.0), (70.0, 85.0)]


def _signed_area(ring):
    pts = ring[:-1]
    return 0.5 * sum(
        x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])
    )


@pytest.mark.parametrize("holes", [[HOLE], [HOLE, HOLE2]], ids=["one", "two"])
def test_built_ring_is_a_proper_keyhole_of_the_domain(holes):
    ring = GeomStorage.build_keyhole_perimeter(outer=OUTER, holes=holes)
    domain = Polygon(OUTER, holes)
    assert ring[0] == ring[-1] == OUTER[0]
    assert not Polygon(ring).is_valid  # shapely sees the doubled cuts
    recovered = validate_keyhole_ring(ring)
    assert recovered.equals(domain)
    assert len(recovered.interiors) == len(holes)
    # Holes run opposite to the outer ring, so the shoelace area is the domain.
    assert abs(_signed_area(ring)) == pytest.approx(domain.area)
    # Every cut edge appears exactly twice, once in each direction.
    edges = list(itertools.pairwise(ring))
    doubled = {frozenset(e) for e in edges if edges.count((e[1], e[0])) == 1}
    assert len(doubled) == len(holes)


def test_polygon_geometry_input_equals_outer_and_holes():
    domain = Polygon(OUTER, [HOLE])
    assert GeomStorage.build_keyhole_perimeter(geometry=domain) == (
        GeomStorage.build_keyhole_perimeter(outer=OUTER, holes=[HOLE])
    )


@pytest.mark.parametrize(
    "ring, message",
    [
        ([(0, 0), (10, 10), (10, 0), (0, 10)], "no doubled cut"),
        (OUTER, "no doubled cut"),
        # Inward spur: a doubled edge that reaches no hole.
        ([(0, 0), (10, 0), (10, 10), (5, 10), (5, 5), (5, 10), (0, 10)], "no excluded area"),
        # Outward spur.
        ([(0, 0), (10, 0), (10, 10), (5, 10), (5, 15), (5, 10), (0, 10)], "no excluded area"),
        # Same edge twice in the same direction.
        (
            [(0, 0), (10, 0), (4, 4), (6, 4), (6, 6), (4, 6), (4, 4), (10, 0),
             (4, 4), (10, 0), (10, 10), (0, 10)],
            "repeats an edge",
        ),
    ],
    ids=["bowtie", "simple", "inward_spur", "outward_spur", "repeated_direction"],
)
def test_broken_rings_are_rejected(ring, message):
    with pytest.raises(ValueError, match=message):
        validate_keyhole_ring(ring)


def test_cut_crossing_another_hole_is_rejected():
    # Hole A (40..60) is joined from (50, 0). The cut to hole B, from (0, 50)
    # to (70, 50), passes straight through hole A.
    hole_a = [(50.0, 40.0), (40.0, 40.0), (40.0, 60.0), (60.0, 60.0), (60.0, 40.0)]
    hole_b = [(70.0, 50.0), (70.0, 55.0), (80.0, 55.0), (80.0, 45.0), (70.0, 45.0)]
    ring = (
        [(0.0, 0.0), (50.0, 0.0)] + hole_a + [(50.0, 40.0), (50.0, 0.0)]
        + [(100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 50.0)]
        + hole_b + [(70.0, 50.0), (0.0, 50.0)]
    )
    with pytest.raises(ValueError, match="cross or overlap"):
        validate_keyhole_ring(ring)


def test_overlapping_holes_are_rejected():
    with pytest.raises(ValueError, match="valid polygon"):
        build_keyhole_ring(OUTER, [HOLE, [(50, 50), (55, 50), (55, 55), (50, 55)]])


def test_hole_touching_outer_boundary_is_rejected():
    with pytest.raises(ValueError, match="valid polygon"):
        build_keyhole_ring(OUTER, [[(0, 40), (20, 40), (20, 60), (0, 60)]])


def _chippewa(tmp_path):
    project = Path(RasExamples.extract_project("Chippewa_2D", output_path=tmp_path))
    geom = project / "Chippewa_2D.g01"
    areas = GeomStorage.get_storage_area_polygons(geom, exclude_2d=False)
    outer = areas.loc[areas["Name"] == "Perimeter 1"].geometry.iloc[0]
    c = outer.representative_point()
    minx, miny, maxx, maxy = outer.bounds
    half = 0.08 * min(maxx - minx, maxy - miny)
    hole = box(c.x - half, c.y - half, c.x + half, c.y + half)
    return project, geom, outer, hole


def test_keyhole_written_to_real_2d_area_round_trips(tmp_path):
    _, geom, outer, hole = _chippewa(tmp_path)
    domain = Polygon(outer.exterior.coords, [hole.exterior.coords])
    ring = GeomStorage.build_keyhole_perimeter(geometry=domain)

    with pytest.raises(ValueError, match="valid polygons"):
        GeomStorage.set_2d_flow_area_perimeter(geom, "Perimeter 1", coordinates=ring)

    GeomStorage.set_2d_flow_area_perimeter(
        geom, "Perimeter 1", coordinates=ring, allow_keyhole=True, create_backup=False
    )
    areas = GeomStorage.get_storage_area_polygons(geom, exclude_2d=False)
    stored = areas.loc[areas["Name"] == "Perimeter 1"].geometry.iloc[0]
    # The reader returns the domain, a valid polygon with the excluded area.
    assert stored.is_valid and len(stored.interiors) == 1
    assert stored.symmetric_difference(domain).area < 1e-3
    plan = GeomStorage.plan_2d_flow_area_perimeter(coordinates=ring, allow_keyhole=True)
    assert plan["keyhole"] is True and plan["excluded_area_count"] == 1
    # Writing it again is idempotent.
    before = geom.read_bytes()
    GeomStorage.set_2d_flow_area_perimeter(
        geom, "Perimeter 1", geometry=stored, allow_keyhole=True, create_backup=False
    )
    after = GeomStorage.get_storage_area_polygons(geom, exclude_2d=False)
    assert after.loc[after["Name"] == "Perimeter 1"].geometry.iloc[0].equals(stored)
    assert len(before) > 0


def test_polygon_with_holes_without_opt_in_keeps_exterior_and_warns(tmp_path, caplog):
    _, geom, outer, hole = _chippewa(tmp_path)
    domain = Polygon(outer.exterior.coords, [hole.exterior.coords])
    with caplog.at_level(logging.WARNING):
        GeomStorage.set_2d_flow_area_perimeter(
            geom, "Perimeter 1", geometry=domain, create_backup=False
        )
    assert "interior ring(s) are ignored" in caplog.text
    areas = GeomStorage.get_storage_area_polygons(geom, exclude_2d=False)
    stored = areas.loc[areas["Name"] == "Perimeter 1"].geometry.iloc[0]
    assert len(stored.interiors) == 0


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(
    platform.system() != "Windows" or os.environ.get(HECRAS_INTEGRATION_ENV) != "1",
    reason="Requires Windows, HEC-RAS, and explicit opt-in integration execution",
)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "HEC-RAS 7.0.1 Ras.exe reports 'Error generating Mesh' for a keyhole "
        "perimeter ring; the same seeds mesh with the plain outer ring"
    ),
)
def test_hecras_meshes_keyhole_perimeter_excluding_the_hole(tmp_path):
    import h5py

    from ras_commander import RasPrj, init_ras_project
    from ras_commander.geom import GeomMesh, GeomPreprocessor

    project, geom, outer, hole = _chippewa(tmp_path)
    spacing = 300.0
    domain = Polygon(outer.exterior.coords, [hole.exterior.coords])
    ring = GeomStorage.build_keyhole_perimeter(geometry=domain)
    GeomStorage.set_2d_flow_area_perimeter(
        geom, "Perimeter 1", coordinates=ring, allow_keyhole=True,
        point_generation_data=(None, None, spacing, spacing), create_backup=False,
    )
    minx, miny, maxx, maxy = outer.bounds
    grid = np.array([
        (x, y)
        for x in np.arange(minx + spacing / 2, maxx, spacing)
        for y in np.arange(miny + spacing / 2, maxy, spacing)
    ])
    seeds = grid[shapely.contains_xy(domain.buffer(-spacing / 2), grid[:, 0], grid[:, 1])]
    ras = init_ras_project(project, "7.0.1", ras_object=RasPrj())
    assert GeomMesh.write_computation_points(geom, seeds, mesh_name="Perimeter 1", ras_object=ras).ok
    ras = init_ras_project(project, "7.0.1", ras_object=RasPrj())
    plan = ras.plan_df.loc[ras.plan_df.geometry_number == "01", "plan_number"].iloc[0]
    result = GeomPreprocessor.run_geometry_preprocessor(plan, ras_object=ras, max_wait=3600)
    assert result.success, result.error
    with h5py.File(project / "Chippewa_2D.g01.hdf", "r") as hdf:
        group = hdf["Geometry/2D Flow Areas"]
        real = int(group["Attributes"][()]["Cell Count"][0])
        centres = group["Perimeter 1/Cells Center Coordinate"][()][:real]
    assert not shapely.contains_xy(hole, centres[:, 0], centres[:, 1]).any()
