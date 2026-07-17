"""Tests for HdfProject.get_project_extent(fill_holes=...).

Combining 1D reach footprints with 2D flow-area perimeters leaves thin interior
sliver gaps (holes) where the two boundaries overlap without aligning exactly.
fill_holes (default True) drops those interior rings while preserving the outer
boundary and any genuinely separate parts.

The helper behavior is covered without HEC-RAS on synthetic geometry; the
end-to-end behavior is verified against the bundled Muncie project, which has a
1D river + 2D mesh in one geometry and produces real slivers.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

pytest.importorskip("geopandas")
pytest.importorskip("shapely")
pytest.importorskip("h5py")

from ras_commander import RasExamples, init_ras_project, RasPrj
from ras_commander.hdf import HdfMesh, HdfXsec, HdfProject


# --- CI-safe helper tests (no HEC-RAS, synthetic geometry) -------------------

def _square_with_hole():
    from shapely.geometry import Polygon
    outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6)]
    return Polygon(outer, [hole])


def test_count_holes_polygon():
    assert HdfProject._count_holes(_square_with_hole()) == 1


def test_fill_polygon_holes_drops_interiors():
    filled = HdfProject._fill_polygon_holes(_square_with_hole())
    assert HdfProject._count_holes(filled) == 0
    assert filled.area == 100.0  # 4-unit hole is filled back in (was 96)


def test_fill_polygon_holes_preserves_parts():
    """A genuinely multipart geometry keeps all its parts; only holes are dropped."""
    from shapely.geometry import Polygon, MultiPolygon
    a = _square_with_hole()
    b = Polygon([(20, 0), (25, 0), (25, 5), (20, 5)])  # separate island, no hole
    filled = HdfProject._fill_polygon_holes(MultiPolygon([a, b]))
    parts = list(filled.geoms) if filled.geom_type == "MultiPolygon" else [filled]
    assert len(parts) == 2
    assert HdfProject._count_holes(filled) == 0


def test_fill_polygon_holes_passthrough_non_polygon():
    from shapely.geometry import LineString
    line = LineString([(0, 0), (1, 1)])
    assert HdfProject._fill_polygon_holes(line) == line


# --- Real-project integration test (Muncie, bundled) -------------------------

@pytest.fixture(scope="module")
def muncie_2d_geom():
    project = RasExamples.extract_project("Muncie", suffix="fillholes_test")
    ras = RasPrj()
    init_ras_project(project, "6.6", ras_object=ras)
    for cand in sorted(Path(project).glob("*.g[0-9][0-9].hdf")):
        if HdfMesh.get_mesh_area_names(cand):
            xs = HdfXsec.get_cross_sections(cand, ras_object=ras)
            if xs is not None and not xs.empty:
                return cand
    pytest.skip("No combined 1D+2D Muncie geometry available")


def _parts_holes(gdf):
    g = gdf.geometry.iloc[0]
    parts = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    return len(parts), HdfProject._count_holes(g), g


def test_fill_holes_default_removes_slivers(muncie_2d_geom):
    on, _ = HdfProject.get_project_extent(muncie_2d_geom, buffer_percent=0.0)
    off, _ = HdfProject.get_project_extent(muncie_2d_geom, buffer_percent=0.0, fill_holes=False)

    parts_on, holes_on, g_on = _parts_holes(on)
    parts_off, holes_off, g_off = _parts_holes(off)

    assert holes_off > 0, "Muncie's 1D+2D union should have interior sliver gaps"
    assert holes_on == 0, "fill_holes=True must remove every interior sliver"
    assert parts_on == parts_off, "fill_holes must not drop any real part (no island removal)"
    # Filling holes only adds the gap area; the outer boundary is unchanged.
    assert g_on.area >= g_off.area
    assert on.geometry.is_valid.all()


def test_fill_holes_leaves_bounds_unchanged(muncie_2d_geom):
    _, b_on = HdfProject.get_project_extent(muncie_2d_geom, buffer_percent=0.0)
    _, b_off = HdfProject.get_project_extent(muncie_2d_geom, buffer_percent=0.0, fill_holes=False)
    assert tuple(round(v, 3) for v in b_on) == tuple(round(v, 3) for v in b_off)


def test_bbox_mode_ignores_fill_holes(muncie_2d_geom):
    """bbox mode returns a box; fill_holes is accepted and irrelevant."""
    box_on, _ = HdfProject.get_project_extent(
        muncie_2d_geom, geometry_type="bbox", buffer_percent=0.0, fill_holes=True)
    box_off, _ = HdfProject.get_project_extent(
        muncie_2d_geom, geometry_type="bbox", buffer_percent=0.0, fill_holes=False)
    assert box_on.geometry.iloc[0].equals(box_off.geometry.iloc[0])
    assert HdfProject._count_holes(box_on.geometry.iloc[0]) == 0
