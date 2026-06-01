"""Unit tests for RasCmdr.preprocess_geometry_linux + _validate_geom_preprocess (CLB-885)."""
import sys
import h5py
import pytest

from ras_commander.RasCmdr import RasCmdr


def _write_log(tmp_path, text):
    p = tmp_path / "geompre_linux_04.log"
    p.write_text(text)
    return p


def _make_tmp_hdf(tmp_path, with_geompre=True, geompre_keys=("XSEC Properties",)):
    h = tmp_path / "Muncie.p04.tmp.hdf"
    with h5py.File(h, "w") as f:
        g = f.create_group("Geometry")
        if with_geompre:
            gp = g.create_group("GeomPreprocess")
            for k in geompre_keys:
                gp.create_dataset(k, data=[1, 2, 3])
    return h


def test_validate_geom_preprocess_ok(tmp_path):
    log = _write_log(tmp_path, "PROGRESS= 1.0\n IBOPER= Finished\n\nFinished Processing Geometry\n")
    hdf = _make_tmp_hdf(tmp_path, with_geompre=True)
    ok, reason = RasCmdr._validate_geom_preprocess(log, hdf)
    assert ok, reason


def test_validate_geom_preprocess_fails_on_error_marker(tmp_path):
    log = _write_log(tmp_path, "Finished Processing Geometry\nHDF_ERROR trying to close HDF output file\n")
    hdf = _make_tmp_hdf(tmp_path, with_geompre=True)
    ok, reason = RasCmdr._validate_geom_preprocess(log, hdf)
    assert not ok
    assert "hdf_error" in reason.lower() or "must be closed" in reason.lower()


def test_validate_geom_preprocess_fails_without_banner(tmp_path):
    log = _write_log(tmp_path, "PROGRESS= 0.5\n(no completion banner)\n")
    hdf = _make_tmp_hdf(tmp_path, with_geompre=True)
    ok, reason = RasCmdr._validate_geom_preprocess(log, hdf)
    assert not ok
    assert "finished processing geometry" in reason.lower()


def test_validate_geom_preprocess_fails_when_group_missing(tmp_path):
    log = _write_log(tmp_path, "Finished Processing Geometry\n")
    hdf = _make_tmp_hdf(tmp_path, with_geompre=False)
    ok, reason = RasCmdr._validate_geom_preprocess(log, hdf)
    assert not ok
    assert "geompreprocess" in reason.lower()


def test_validate_geom_preprocess_fails_on_unreadable_log(tmp_path):
    hdf = _make_tmp_hdf(tmp_path, with_geompre=True)
    ok, reason = RasCmdr._validate_geom_preprocess(tmp_path / "nope.log", hdf)
    assert not ok
    assert "unreadable" in reason.lower()


def test_preprocess_geometry_linux_missing_binary(tmp_path):
    """Missing RasGeomPreprocess binary must raise FileNotFoundError before any project work."""
    class _Stub:
        project_folder = str(tmp_path)
        project_name = "Muncie"
        def check_initialized(self):
            return True
    with pytest.raises(FileNotFoundError):
        RasCmdr.preprocess_geometry_linux(
            "04", ras_exe_dir=str(tmp_path / "no_such_ras_dir"), ras_object=_Stub()
        )
