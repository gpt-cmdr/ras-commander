"""Integration tests for RasGeometryCompute — in-process RASMapper geometry
completion via pythonnet. Skipped when HEC-RAS / RasMapperLib is unavailable
(e.g. CI without HEC-RAS).

NOTE ON STRUCTURE: RasMapperLib is an in-process .NET (pythonnet) library, and
running many geometry-generation calls in a single Python process eventually
exhausts/locks file handles ("Access to the path is denied" / "The handle is
invalid"). To stay within that budget these tests generate the layers ONCE in a
module-scoped fixture and then make mostly read-only assertions; the fail-closed
guard logic is covered separately (no HEC-RAS needed) in
test_ras_geometry_compute_unit.py.
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
def completed_geom():
    """Extract Muncie and generate all three layers ONCE (minimises CLR calls)."""
    from ras_commander import RasGeometryCompute
    project = RasExamples.extract_project("Muncie", suffix="rgc_suite")
    ras = RasPrj()
    init_ras_project(project, "6.6", ras_object=ras)
    geom = _geom_with_xs(project, ras)
    if geom is None:
        pytest.skip("No 1D geometry available")
    # compute_geometry writes edge lines + interpolation surface; flow paths
    # are generated separately (not part of the completion pipeline).
    cr = RasGeometryCompute.compute_geometry(geom, ras_object=ras, overwrite=True)
    assert cr.success and cr.edge_lines_written and cr.interpolation_surface_written
    assert cr.flow_paths_written is False
    fp = RasGeometryCompute.generate_flow_paths(geom, ras_object=ras)
    assert fp.success
    return geom, ras


# --- Read-only assertions on the generated layers (no CLR calls) ---

def test_edge_lines_generated(completed_geom):
    geom, ras = completed_geom
    el = HdfXsec.get_river_edge_lines(geom)
    assert not el.empty
    assert list(el["bank_side"]) == ["Left", "Right"] * (len(el) // 2)
    with h5py.File(geom, "r") as f:
        assert "Source Data Hash" in f["Geometry/River Edge Lines"].attrs
        assert "Attributes" not in f["Geometry/River Edge Lines"]  # genuine HEC-RAS schema


def test_interpolation_surface_generated(completed_geom):
    geom, ras = completed_geom
    surf = HdfXsec.get_xs_interpolation_surface(geom)
    assert not surf.empty
    assert {"surface_id", "us_xs_id", "ds_xs_id", "area", "geometry"}.issubset(surf.columns)
    assert bool(surf.geometry.is_valid.all())


def test_flow_paths_generated(completed_geom):
    geom, ras = completed_geom
    fp = HdfXsec.get_river_flow_paths(geom)
    assert not fp.empty


# --- Behavior tests (each a single CLR call) ---

def test_generate_flow_paths_skips_when_present(completed_geom):
    """Skip is a no-op that returns BEFORE loading the CLR (protects manual edits)."""
    from ras_commander import RasGeometryCompute
    geom, ras = completed_geom
    r = RasGeometryCompute.generate_flow_paths(geom, ras_object=ras)  # overwrite=False
    assert r.success and r.skipped


def test_validate_geometry(completed_geom):
    from ras_commander import RasGeometryCompute
    geom, ras = completed_geom
    diag = RasGeometryCompute.validate_geometry(geom, ras_object=ras)
    assert {"severity", "level", "layer", "River", "Reach", "RS",
            "feature", "process", "message", "geometry"}.issubset(diag.columns)
    assert RasGeometryCompute.is_valid_geometry(geom, ras_object=ras) in (True, False)


def test_windows_only_guard(monkeypatch, completed_geom):
    """Non-Windows raises before any CLR/pythonnet import."""
    from ras_commander import RasGeometryCompute
    geom, ras = completed_geom
    monkeypatch.setattr("platform.system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="Windows"):
        RasGeometryCompute.generate_edge_lines(geom, ras_object=ras, overwrite=True)


# NOTE: `generate_flow_paths(overwrite=True, backup=...)` and
# `audit_reach_lengths()` are heavy mutating operations that exhaust in-process
# .NET file handles when run after the other CLR calls above in the same pytest
# process (Windows can't fork to isolate them). Their end-to-end behavior is
# validated in examples/234_rasmapper_geometry_completion.ipynb (which asserts
# the original geometry is byte-identical after the audit and that drift is
# detected), and their logic (backup fail-closed, the reach-length diff, the
# no-op guard, tolerance/mode validation) is covered without HEC-RAS in
# test_ras_geometry_compute_unit.py.
