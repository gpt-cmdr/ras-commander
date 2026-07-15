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
