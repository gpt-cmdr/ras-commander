"""Tests for river edge-line reading and the stored-edge 1D footprint path.

Covers get_river_edge_lines() and the edge_source='stored' branch of
get_1d_footprint(), which need a geometry HDF that already carries a
Geometry/River Edge Lines group. No bundled example project ships one, and
authoring genuine edge lines requires HEC-RAS (RasGeometryCompute), so these
tests synthesize the layer with _write_edge_lines() below — a local fixture
helper, deliberately not library API: ras-commander generates edge lines
through HEC-RAS, never by writing an approximation into the HDF itself.

Guards two reader regressions verified against a genuine HEC-RAS edge-line file:
  * genuine edge lines carry no "Attributes" dataset, so bank_side must be
    derived from row order (RASEdgeLines: IsLeft = i % 2 == 0);
  * the layer uses the native polyline schema (Polyline Info / Parts / Points
    with Row/Column/Feature Type attrs), which the fixture reproduces so the
    reader assertions below are meaningful.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

pytest.importorskip("geopandas")
pytest.importorskip("shapely")
h5py = pytest.importorskip("h5py")

from ras_commander import RasExamples, init_ras_project, RasPrj
from ras_commander.hdf import HdfXsec


def _write_edge_lines(geom_hdf, edge_lines) -> int:
    """Write edge lines into Geometry/River Edge Lines in HEC-RAS's native schema.

    Test-fixture only. Mirrors what HEC-RAS emits: a flat float64 point array
    indexed by a per-polyline [pnt_start, pnt_cnt, part_start, part_cnt] Info
    row plus one single-part Parts row, with no Attributes dataset. Rows are in
    Left, Right order per reach. The group-level Source Data Hash HEC-RAS writes
    is intentionally absent — the reader must not depend on it.
    """
    lines = [HdfXsec._as_single_linestring(g) for g in edge_lines.geometry]
    lines = [ln for ln in lines if ln is not None]

    points, info_rows, parts_rows = [], [], []
    pnt_offset = 0
    for idx, line in enumerate(lines):
        coords = [(float(x), float(y)) for x, y in (c[:2] for c in line.coords)]
        points.extend(coords)
        n = len(coords)
        info_rows.append((pnt_offset, n, idx, 1))
        parts_rows.append((0, n))
        pnt_offset += n

    with h5py.File(geom_hdf, "a") as f:
        geom = f.require_group("Geometry")
        if "River Edge Lines" in geom:
            del geom["River Edge Lines"]
        grp = geom.create_group("River Edge Lines")

        info_ds = grp.create_dataset("Polyline Info", data=np.asarray(info_rows, dtype=np.int32))
        info_ds.attrs.create("Row", np.bytes_("Feature"))
        info_ds.attrs.create("Column", np.array(
            [b"Point Starting Index", b"Point Count",
             b"Part Starting Index", b"Part Count"], dtype="S20"))
        info_ds.attrs.create("Feature Type", np.bytes_("Polyline"))

        parts_ds = grp.create_dataset("Polyline Parts", data=np.asarray(parts_rows, dtype=np.int32))
        parts_ds.attrs.create("Row", np.bytes_("Part"))
        parts_ds.attrs.create("Column", np.array(
            [b"Point Starting Index", b"Point Count"], dtype="S20"))

        points_ds = grp.create_dataset(
            "Polyline Points", data=np.asarray(points, dtype=np.float64).reshape(-1, 2))
        points_ds.attrs.create("Row", np.bytes_("Points"))
        points_ds.attrs.create("Column", np.array([b"X", b"Y"], dtype="S1"))

    return len(lines)


def _geom_hdf_with_xs(folder, ras):
    for cand in sorted(Path(folder).glob("*.g*.hdf")):
        xs = HdfXsec.get_cross_sections(cand, ras_object=ras)
        if xs is not None and not xs.empty:
            return cand
    return None


@pytest.fixture(scope="module")
def stored_edge_geom():
    """A geometry HDF with 1D cross sections and synthesized stored edge lines."""
    folder = RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="edgetest")
    ras = RasPrj()
    init_ras_project(folder, "6.6", ras_object=ras)
    geom_hdf = _geom_hdf_with_xs(folder, ras)
    if geom_hdf is None:
        pytest.skip("No 1D geometry available in example project")

    before = HdfXsec.get_river_edge_lines(geom_hdf)
    assert before is None or before.empty

    generated = HdfXsec.generate_river_edge_lines(geom_hdf, ras_object=ras)
    assert not generated.empty and len(generated) % 2 == 0
    n = _write_edge_lines(geom_hdf, generated)
    assert n == len(generated)
    return geom_hdf, ras, generated


def test_fixture_matches_genuine_schema(stored_edge_geom):
    """Guard the fixture itself: HEC-RAS writes no Attributes for this layer."""
    geom_hdf, _, _ = stored_edge_geom
    with h5py.File(geom_hdf, "r") as f:
        g = f["Geometry/River Edge Lines"]
        assert set(g.keys()) == {"Polyline Info", "Polyline Parts", "Polyline Points"}
        assert "Attributes" not in g
        assert g["Polyline Info"].attrs["Row"] == b"Feature"
        assert g["Polyline Info"].attrs["Feature Type"] == b"Polyline"
        assert list(g["Polyline Points"].attrs["Column"]) == [b"X", b"Y"]
        assert g["Polyline Points"].dtype.name == "float64"


def test_reader_roundtrips_stored_geometry(stored_edge_geom):
    geom_hdf, _, generated = stored_edge_geom
    stored = HdfXsec.get_river_edge_lines(geom_hdf)
    assert len(stored) == len(generated)
    for (_, gen), (_, red) in zip(generated.iterrows(), stored.iterrows()):
        assert gen.geometry.equals_exact(red.geometry, 1e-6)


def test_reader_derives_bank_side_without_attributes(stored_edge_geom):
    """No-Attributes branch (genuine schema) yields alternating Left/Right."""
    geom_hdf, _, _ = stored_edge_geom
    stored = HdfXsec.get_river_edge_lines(geom_hdf)
    assert not stored.empty
    assert {"edge_id", "bank_side", "geometry", "length"}.issubset(stored.columns)
    assert list(stored["bank_side"]) == \
        ["Left" if i % 2 == 0 else "Right" for i in range(len(stored))]


def test_stored_footprint_path(stored_edge_geom):
    geom_hdf, ras, _ = stored_edge_geom
    fp = HdfXsec.get_1d_footprint(geom_hdf, edge_source="stored", ras_object=ras)
    assert not fp.empty
    assert bool(fp.geometry.is_valid.all())
    assert set(fp["source"]) == {"stored_edge_lines"}


def test_stored_matches_generate(stored_edge_geom):
    geom_hdf, ras, _ = stored_edge_geom
    fp_stored = HdfXsec.get_1d_footprint(geom_hdf, edge_source="stored", ras_object=ras)
    fp_gen = HdfXsec.get_1d_footprint(geom_hdf, edge_source="generate", ras_object=ras)
    a_stored = float(fp_stored.geometry.area.sum())
    a_gen = float(fp_gen.geometry.area.sum())
    assert abs(a_stored - a_gen) / a_gen < 1e-6


def test_reads_genuine_hecras_edge_lines():
    """If a genuine HEC-RAS edge-line file (has Source Data Hash, no Attributes)
    is present on disk, the reader must decode it with correct bank sides."""
    genuine = None
    root = repo_root / "example_projects"
    for hdf in root.glob("**/*.g*.hdf"):
        try:
            with h5py.File(hdf, "r") as f:
                g = f.get("Geometry/River Edge Lines")
                if g is not None and "Attributes" not in g and "Source Data Hash" in g.attrs:
                    genuine = hdf
                    break
        except Exception:
            continue
    if genuine is None:
        pytest.skip("No genuine HEC-RAS edge-line file on disk")
    gdf = HdfXsec.get_river_edge_lines(genuine)
    assert not gdf.empty
    assert list(gdf["bank_side"]) == \
        ["Left" if i % 2 == 0 else "Right" for i in range(len(gdf))]
    assert bool(gdf.geometry.is_valid.all())


def test_complete_geometry_headless_edge_lines():
    """RasProcess.exe CompleteGeometry authors genuine edge lines + interpolation
    surface with no GUI. Skipped when HEC-RAS / RasProcess.exe is unavailable."""
    from ras_commander import RasProcess
    if RasProcess.find_rasprocess() is None:
        pytest.skip("RasProcess.exe (HEC-RAS) not installed")

    folder = RasExamples.extract_project("Muncie", suffix="complete_geom")
    ras = RasPrj()
    init_ras_project(folder, "6.6", ras_object=ras)
    geom_hdf = _geom_hdf_with_xs(folder, ras)
    if geom_hdf is None:
        pytest.skip("No 1D geometry available in example project")

    before = HdfXsec.get_river_edge_lines(geom_hdf)
    assert before is None or before.empty

    res = RasProcess.compute_geometry(geom_hdf, ras_object=ras, ras_version="6.6")
    assert res["success"], f"CompleteGeometry failed: {res['stdout']}\n{res['stderr']}"
    assert res["edge_lines_written"]
    assert res["interpolation_surface_written"]

    # Genuine HEC-RAS output: no Attributes dataset, carries the Source Data Hash.
    with h5py.File(geom_hdf, "r") as f:
        g = f["Geometry/River Edge Lines"]
        assert "Attributes" not in g
        assert "Source Data Hash" in g.attrs

    gdf = HdfXsec.get_river_edge_lines(geom_hdf)
    assert not gdf.empty
    assert list(gdf["bank_side"]) == \
        ["Left" if i % 2 == 0 else "Right" for i in range(len(gdf))]
    fp = HdfXsec.get_1d_footprint(geom_hdf, edge_source="stored", ras_object=ras)
    assert not fp.empty and set(fp["source"]) == {"stored_edge_lines"}
