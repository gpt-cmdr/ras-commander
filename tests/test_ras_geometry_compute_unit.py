"""Unit tests for RasGeometryCompute guard logic (no HEC-RAS required).

These verify the fail-closed safety behavior surfaced by the Codex review:
the overwrite/backup guard must never run a destructive compute when it cannot
confirm existing state or produce a backup, validation must fail closed, and the
Windows guard and deprecated alias must behave as documented. They monkeypatch
the platform and the pythonnet-touching internals so they run anywhere.
"""

import inspect
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

pytest.importorskip("geopandas")
pytest.importorskip("h5py")

from ras_commander import RasGeometryCompute, RasProcess


@pytest.fixture
def geom_file(tmp_path):
    p = tmp_path / "model.g01.hdf"
    p.write_bytes(b"\x89HDF\r\n\x1a\n")  # dummy; existence is all that's checked
    return p


@pytest.fixture
def on_windows(monkeypatch):
    """Make _require_windows pass regardless of the host OS."""
    monkeypatch.setattr("platform.system", lambda: "Windows")


def _forbid_compute(monkeypatch):
    """Make reaching the pythonnet layer a hard failure."""
    def _boom(*a, **k):
        raise AssertionError("destructive compute must not run")
    monkeypatch.setattr(RasGeometryCompute, "_ensure_clr", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_load_geometry", staticmethod(_boom))


def test_windows_guard_raises(monkeypatch, geom_file):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="Windows"):
        RasGeometryCompute.generate_edge_lines(geom_file, overwrite=True)


def test_skip_when_present_no_compute(monkeypatch, on_windows, geom_file):
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(lambda p, g: True))
    _forbid_compute(monkeypatch)
    r = RasGeometryCompute.generate_flow_paths(geom_file)  # overwrite=False
    assert r.success and r.skipped


def test_fail_closed_on_inspect_error(monkeypatch, on_windows, geom_file):
    def _raise(p, g):
        raise OSError("HDF locked")
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(_raise))
    _forbid_compute(monkeypatch)
    r = RasGeometryCompute.generate_flow_paths(geom_file, overwrite=True)
    assert not r.success and "inspect" in (r.error or "").lower()


def test_fail_closed_backup_returns_none(monkeypatch, on_windows, geom_file):
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(lambda p, g: True))
    monkeypatch.setattr(RasGeometryCompute, "_backup_layer", staticmethod(lambda p, t, r: None))
    _forbid_compute(monkeypatch)
    r = RasGeometryCompute.generate_flow_paths(geom_file, overwrite=True, backup=True)
    assert not r.success and "backup" in (r.error or "").lower()


def test_fail_closed_backup_raises(monkeypatch, on_windows, geom_file):
    def _raise_backup(p, t, r):
        raise IOError("disk full")
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(lambda p, g: True))
    monkeypatch.setattr(RasGeometryCompute, "_backup_layer", staticmethod(_raise_backup))
    _forbid_compute(monkeypatch)
    r = RasGeometryCompute.generate_flow_paths(geom_file, overwrite=True, backup=True)
    assert not r.success and "backup failed" in (r.error or "").lower()


def test_backup_false_allows_overwrite_without_backup(monkeypatch, on_windows, geom_file):
    """With backup=False the caller has explicitly opted out; compute proceeds."""
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(lambda p, g: True))
    reached = {"compute": False}
    monkeypatch.setattr(RasGeometryCompute, "_ensure_clr", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_resolve_rasmap", staticmethod(lambda *a, **k: None))

    class _FakeGeom:
        class FlowPathLines:
            @staticmethod
            def ComputeFlowPathLines():
                reached["compute"] = True
                return True
    monkeypatch.setattr(RasGeometryCompute, "_load_geometry", staticmethod(lambda *a, **k: _FakeGeom()))
    r = RasGeometryCompute.generate_flow_paths(geom_file, overwrite=True, backup=False)
    assert reached["compute"] is True
    assert r.backup_path is None


def test_compute_geometry_no_skip_when_interp_absent(monkeypatch, on_windows, geom_file):
    """overwrite=False must still run when edge lines exist but interp surface does not."""
    state = {"computed": False}

    def fake_layer_exists(p, group):
        if "River Edge Lines" in group:
            return True
        if "Interpolation Surface" in group:
            return state["computed"]   # absent before compute, present after
        return False  # flow paths

    class _FakeGeom:
        def CompleteForComputations(self, force, prog):
            state["computed"] = True
            return True

    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(fake_layer_exists))
    monkeypatch.setattr(RasGeometryCompute, "_ensure_clr", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_resolve_rasmap", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_load_geometry", staticmethod(lambda *a, **k: _FakeGeom()))

    cr = RasGeometryCompute.compute_geometry(geom_file)  # overwrite=False
    assert state["computed"] is True, "must not skip when interpolation surface is absent"
    assert cr.success and cr.edge_lines_written and cr.interpolation_surface_written


def test_validate_fail_closed(monkeypatch, on_windows, geom_file):
    monkeypatch.setattr(RasGeometryCompute, "_ensure_clr", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_resolve_rasmap", staticmethod(lambda *a, **k: None))

    class _FakeGeom:
        def ValidateGeometry(self, flag):
            raise RuntimeError("validator crashed")
    monkeypatch.setattr(RasGeometryCompute, "_load_geometry", staticmethod(lambda *a, **k: _FakeGeom()))

    report = RasGeometryCompute.validate_geometry(geom_file)
    assert not report.empty
    assert (report["severity"] == "ERROR").any()
    assert RasGeometryCompute.is_valid_geometry(geom_file) is False


def test_parse_feature_name():
    assert RasGeometryCompute._parse_feature_name("White, Muncie (1980.776)") == \
        ("White", "Muncie", "1980.776")
    assert RasGeometryCompute._parse_feature_name("0, 0") == (None, None, None)
    assert RasGeometryCompute._parse_feature_name("") == (None, None, None)


def test_complete_geometry_alias_signature_preserved():
    assert (inspect.signature(RasProcess.complete_geometry)
            == inspect.signature(RasProcess.compute_geometry))


def _diff_frames(left, channel, right):
    import geopandas as gpd
    from shapely.geometry import LineString
    line = LineString([(0, 0), (1, 0)])
    stored = gpd.GeoDataFrame({
        "River": ["R", "R", "R", "R"], "Reach": ["A", "A", "A", "A"],
        "RS": ["4", "3", "2", "1"],
        "Len Left": [100.0, 200.0, 300.0, 400.0],
        "Len Channel": [100.0, 200.0, 300.0, 400.0],
        "Len Right": [100.0, 200.0, 300.0, 400.0],
        "geometry": [line] * 4,
    })
    recomputed = gpd.GeoDataFrame({
        "River": ["R", "R", "R", "R"], "Reach": ["A", "A", "A", "A"],
        "RS": ["4", "3", "2", "1"],
        "Len Left": left, "Len Channel": channel, "Len Right": right,
        "geometry": [line] * 4,
    })
    return stored, recomputed


def test_reach_length_diff():
    nan = float("nan")
    # RS4: <tol; RS3: +10; RS2: partial NaN (invalid); RS1: all-NaN reach end
    stored, recomputed = _diff_frames(
        left=[100.2, 210.0, nan, nan],
        channel=[100.0, 200.0, 300.0, nan],
        right=[100.0, 200.0, 300.0, nan],
    )
    d = RasGeometryCompute._reach_length_diff(stored, recomputed, tolerance=0.5).set_index("RS")
    assert bool(d.loc["4", "changed"]) is False            # 0.2 < 0.5 tolerance
    assert bool(d.loc["3", "changed"]) is True and abs(d.loc["3", "delta_left"] - 10.0) < 1e-6
    assert bool(d.loc["2", "invalid_recompute"]) is True   # only left NaN -> anomaly
    assert bool(d.loc["2", "changed"]) is True             # invalid recompute is flagged
    assert bool(d.loc["2", "reach_end"]) is False
    assert bool(d.loc["1", "reach_end"]) is True           # all recomputed NaN
    assert bool(d.loc["1", "invalid_recompute"]) is False
    assert bool(d.loc["1", "changed"]) is False


def test_reach_length_diff_row_count_mismatch_raises():
    stored, recomputed = _diff_frames([1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4])
    with pytest.raises(ValueError, match="counts differ"):
        RasGeometryCompute._reach_length_diff(stored, recomputed.iloc[:3], tolerance=0.5)


def test_reach_length_diff_identity_mismatch_raises():
    stored, recomputed = _diff_frames([1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4])
    recomputed = recomputed.copy()
    recomputed.loc[0, "RS"] = "99"  # reorder/relabel -> identity mismatch
    with pytest.raises(ValueError, match="identity/order"):
        RasGeometryCompute._reach_length_diff(stored, recomputed, tolerance=0.5)


def test_audit_reach_lengths_rejects_bad_flow_paths_mode(geom_file):
    with pytest.raises(ValueError, match="flow_paths"):
        RasGeometryCompute.audit_reach_lengths(geom_file, flow_paths="bogus")


def test_audit_reach_lengths_rejects_negative_tolerance(geom_file):
    with pytest.raises(ValueError, match="tolerance"):
        RasGeometryCompute.audit_reach_lengths(geom_file, tolerance=-1.0)
