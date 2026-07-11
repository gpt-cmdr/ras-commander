"""Tests for river edge-line authoring and the stored-edge 1D footprint path.

Covers HdfXsec.set_river_edge_lines() (pure-Python authoring of the artifact
RASMapper's "Create Edge Lines at XS Limits" produces, in HEC-RAS's native
polyline schema) and the edge_source='stored' branch of get_1d_footprint().

Guards two reader regressions verified against a genuine HEC-RAS edge-line file:
  * genuine edge lines carry no "Attributes" dataset, so bank_side must be
    derived from row order (RASEdgeLines: IsLeft = i % 2 == 0);
  * the writer must emit that same schema (no Attributes; Row/Column/Feature
    Type attrs on the polyline datasets) rather than a fabricated Attributes set.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

pytest.importorskip("geopandas")
pytest.importorskip("shapely")
h5py = pytest.importorskip("h5py")

from ras_commander import RasExamples, init_ras_project, RasPrj
from ras_commander.hdf import HdfXsec


def _geom_hdf_with_xs(folder, ras):
    for cand in sorted(Path(folder).glob("*.g*.hdf")):
        xs = HdfXsec.get_cross_sections(cand, ras_object=ras)
        if xs is not None and not xs.empty:
            return cand
    return None


@pytest.fixture(scope="module")
def edge_line_geom():
    """A geometry HDF with 1D cross sections but no stored edge lines."""
    folder = RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="edgetest")
    ras = RasPrj()
    init_ras_project(folder, "6.6", ras_object=ras)
    geom_hdf = _geom_hdf_with_xs(folder, ras)
    if geom_hdf is None:
        pytest.skip("No 1D geometry available in example project")
    before = HdfXsec.get_river_edge_lines(geom_hdf)
    assert before is None or before.empty
    return geom_hdf, ras


def test_set_river_edge_lines_roundtrip(edge_line_geom):
    geom_hdf, ras = edge_line_geom
    generated = HdfXsec.generate_river_edge_lines(geom_hdf, ras_object=ras)
    assert not generated.empty and len(generated) % 2 == 0

    n = HdfXsec.set_river_edge_lines(geom_hdf, edge_lines=generated, ras_object=ras)
    assert n == len(generated)

    stored = HdfXsec.get_river_edge_lines(geom_hdf)
    assert len(stored) == n
    assert list(stored["bank_side"]) == ["Left", "Right"] * (n // 2)
    for (_, gen), (_, red) in zip(generated.iterrows(), stored.iterrows()):
        assert gen.geometry.equals_exact(red.geometry, 1e-6)


def test_writer_emits_native_schema(edge_line_geom):
    """Writer must match HEC-RAS: no Attributes dataset, stamped dataset attrs."""
    geom_hdf, ras = edge_line_geom
    HdfXsec.set_river_edge_lines(geom_hdf, ras_object=ras)
    with h5py.File(geom_hdf, "r") as f:
        g = f["Geometry/River Edge Lines"]
        assert set(g.keys()) == {"Polyline Info", "Polyline Parts", "Polyline Points"}
        assert "Attributes" not in g  # HEC-RAS writes none for this layer
        assert g["Polyline Info"].attrs["Row"] == b"Feature"
        assert g["Polyline Info"].attrs["Feature Type"] == b"Polyline"
        assert list(g["Polyline Points"].attrs["Column"]) == [b"X", b"Y"]
        assert g["Polyline Points"].dtype.name == "float64"


def test_reader_derives_bank_side_without_attributes(edge_line_geom):
    """No-Attributes branch (genuine schema) yields alternating Left/Right."""
    geom_hdf, ras = edge_line_geom
    HdfXsec.set_river_edge_lines(geom_hdf, ras_object=ras)
    with h5py.File(geom_hdf, "r") as f:
        assert "Attributes" not in f["Geometry/River Edge Lines"]
    stored = HdfXsec.get_river_edge_lines(geom_hdf)
    assert not stored.empty
    assert {"edge_id", "bank_side", "geometry", "length"}.issubset(stored.columns)
    assert list(stored["bank_side"]) == \
        ["Left" if i % 2 == 0 else "Right" for i in range(len(stored))]


def test_stored_footprint_path(edge_line_geom):
    geom_hdf, ras = edge_line_geom
    HdfXsec.set_river_edge_lines(geom_hdf, ras_object=ras)
    fp = HdfXsec.get_1d_footprint(geom_hdf, edge_source="stored", ras_object=ras)
    assert not fp.empty
    assert bool(fp.geometry.is_valid.all())
    assert set(fp["source"]) == {"stored_edge_lines"}


def test_stored_matches_generate(edge_line_geom):
    geom_hdf, ras = edge_line_geom
    HdfXsec.set_river_edge_lines(geom_hdf, ras_object=ras)
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

    res = RasProcess.complete_geometry(geom_hdf, ras_object=ras, ras_version="6.6")
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


def test_set_river_edge_lines_empty_is_noop():
    from geopandas import GeoDataFrame
    folder = RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="edgetest_noop")
    ras = RasPrj()
    init_ras_project(folder, "6.6", ras_object=ras)
    geom_hdf = _geom_hdf_with_xs(folder, ras)
    if geom_hdf is None:
        pytest.skip("No 1D geometry available in example project")
    n = HdfXsec.set_river_edge_lines(geom_hdf, edge_lines=GeoDataFrame(), ras_object=ras)
    assert n == 0
    assert HdfXsec.get_river_edge_lines(geom_hdf).empty
