"""Tests for RasGeometryCompute — in-process RASMapper geometry completion.

These exercise real HEC-RAS geometry generation via pythonnet and are skipped
when HEC-RAS / RasMapperLib is not available (e.g. CI without HEC-RAS). The
pure-h5py readers in HdfXsec are tested separately in test_river_edge_lines.py.
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


def _hecras_available():
    try:
        from ras_commander.dotnet.clr_bootstrap import is_hecras_available
        return is_hecras_available()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _hecras_available(),
    reason="HEC-RAS / RasMapperLib (pythonnet) not available",
)


def _geom_with_xs(project, ras):
    for cand in sorted(Path(project).glob("*.g*.hdf")):
        xs = HdfXsec.get_cross_sections(cand, ras_object=ras)
        if xs is not None and not xs.empty:
            return cand
    return None


@pytest.fixture(scope="module")
def muncie_geom():
    project = RasExamples.extract_project("Muncie", suffix="rgc_pytest")
    ras = RasPrj()
    init_ras_project(project, "6.6", ras_object=ras)
    geom = _geom_with_xs(project, ras)
    if geom is None:
        pytest.skip("No 1D geometry available")
    return geom, ras


def test_generate_edge_lines(muncie_geom):
    from ras_commander import RasGeometryCompute
    geom, ras = muncie_geom
    r = RasGeometryCompute.generate_edge_lines(geom, ras_object=ras, overwrite=True)
    assert r.success and not r.skipped
    el = HdfXsec.get_river_edge_lines(geom)
    assert not el.empty and list(el["bank_side"]) == ["Left", "Right"] * (len(el) // 2)
    with h5py.File(geom, "r") as f:
        assert "Source Data Hash" in f["Geometry/River Edge Lines"].attrs


def test_generate_edge_lines_skip_when_present(muncie_geom):
    from ras_commander import RasGeometryCompute
    geom, ras = muncie_geom
    RasGeometryCompute.generate_edge_lines(geom, ras_object=ras, overwrite=True)
    r = RasGeometryCompute.generate_edge_lines(geom, ras_object=ras)  # overwrite=False
    assert r.success and r.skipped


def test_generate_interpolation_surface(muncie_geom):
    from ras_commander import RasGeometryCompute
    geom, ras = muncie_geom
    r = RasGeometryCompute.generate_interpolation_surface(geom, ras_object=ras, overwrite=True)
    assert r.success
    surf = HdfXsec.get_xs_interpolation_surface(geom)
    assert not surf.empty
    assert {"surface_id", "us_xs_id", "ds_xs_id", "area", "geometry"}.issubset(surf.columns)
    assert bool(surf.geometry.is_valid.all())


def test_generate_flow_paths_and_backup(muncie_geom):
    from ras_commander import RasGeometryCompute
    geom, ras = muncie_geom
    r = RasGeometryCompute.generate_flow_paths(geom, ras_object=ras, overwrite=True)
    assert r.success
    fp = HdfXsec.get_river_flow_paths(geom)
    assert not fp.empty

    # Second call without overwrite must skip (protects manual flow paths).
    skip = RasGeometryCompute.generate_flow_paths(geom, ras_object=ras)
    assert skip.success and skip.skipped

    # Overwrite with backup must write a dated .geojson.bak.
    r2 = RasGeometryCompute.generate_flow_paths(geom, ras_object=ras, overwrite=True, backup=True)
    assert r2.success and not r2.skipped
    assert r2.backup_path is not None and Path(r2.backup_path).exists()
    assert r2.backup_path.name.endswith(".geojson.bak")


def test_validate_geometry(muncie_geom):
    from ras_commander import RasGeometryCompute
    geom, ras = muncie_geom
    diag = RasGeometryCompute.validate_geometry(geom, ras_object=ras)
    assert set(["severity", "level", "layer", "River", "Reach", "RS",
                "feature", "process", "message", "geometry"]).issubset(diag.columns)
    # Muncie has a known XS length-mismatch diagnostic.
    assert (diag["message"].str.contains("Profile length", case=False, na=False)).any()
    assert RasGeometryCompute.is_valid_geometry(geom, ras_object=ras) in (True, False)


def test_compute_geometry_bundled():
    from ras_commander import RasGeometryCompute
    project = RasExamples.extract_project("Muncie", suffix="rgc_bundled_pytest")
    ras = RasPrj()
    init_ras_project(project, "6.6", ras_object=ras)
    geom = _geom_with_xs(project, ras)
    if geom is None:
        pytest.skip("No 1D geometry available")
    cr = RasGeometryCompute.compute_geometry(geom, ras_object=ras, overwrite=True)
    assert cr.success
    assert cr.edge_lines_written and cr.interpolation_surface_written
    # Flow paths are not part of the completion pipeline.
    assert cr.flow_paths_written is False


def test_compute_geometry_no_skip_when_interp_absent(muncie_geom):
    """Edge lines present but no interpolation surface must NOT be treated as complete."""
    from ras_commander import RasGeometryCompute
    geom, ras = muncie_geom
    RasGeometryCompute.generate_edge_lines(geom, ras_object=ras, overwrite=True)
    with h5py.File(geom, "a") as f:
        if "Geometry/Cross Section Interpolation Surfaces" in f:
            del f["Geometry/Cross Section Interpolation Surfaces"]
    # overwrite=False, but interp surface is absent -> must run the pipeline.
    cr = RasGeometryCompute.compute_geometry(geom, ras_object=ras)
    assert cr.success and cr.edge_lines_written and cr.interpolation_surface_written


def test_windows_only_guard(monkeypatch, muncie_geom):
    """Non-Windows raises a clear RuntimeError pointing at the Linux path."""
    from ras_commander import RasGeometryCompute
    geom, ras = muncie_geom
    # RasGeometryCompute imports `platform` and calls platform.system(); patch it globally.
    monkeypatch.setattr("platform.system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="Windows"):
        RasGeometryCompute.generate_edge_lines(geom, ras_object=ras, overwrite=True)
