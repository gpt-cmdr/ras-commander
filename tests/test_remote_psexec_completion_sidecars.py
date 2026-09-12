"""Transport/publication regressions; these fixtures do not run or qualify HEC-RAS."""

from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import h5py
import pandas as pd
import pytest

from ras_commander.ExecutionArtifacts import get_plan_result_artifact_paths
from ras_commander.RasBco import BcoMonitor
from ras_commander.RasCmdr import RasCmdr
from ras_commander.RasCurrency import RasCurrency
from ras_commander.RasPrj import RasPrj


psexec_module = import_module("ras_commander.remote.PsexecWorker")


def _seed(tmp_path, version="6.6"):
    source = tmp_path / "source"
    source.mkdir()
    share = tmp_path / "share"
    share.mkdir()
    prj = source / "TestProject.prj"
    prj.write_text("Proj Title=Test\nCurrent Plan=p02\nPlan File=p01\nPlan File=p02\n")
    (source / "TestProject.p01").write_text("Plan Title=Test\n")
    ras = RasPrj()
    ras.initialized = True
    ras.project_folder = source
    ras.project_name = "TestProject"
    ras.prj_file = prj
    ras.plan_df = pd.DataFrame({"plan_number": ["01", "02"]})
    artifacts = get_plan_result_artifact_paths("01", ras_object=ras)
    artifacts.hdf.write_bytes(b"old result")
    artifacts.legacy_output.write_bytes(b"old opposing output")
    for path in artifacts.message_sidecars:
        path.write_bytes(b"old completion evidence")
    worker = SimpleNamespace(
        worker_id="test", hostname="TESTHOST", share_path=str(share),
        worker_folder=r"C:\RasRemote", credentials={}, psexec_path="PsExec.exe",
        ras_exe_path=rf"C:\HEC-RAS\{version}\Ras.exe", system_account=True,
        session_id=7, process_priority="normal", max_runtime_minutes=0.00001,
    )
    return ras, worker, share, artifacts


def _transport(monkeypatch, ras, share, *, sidecar=0, complete=True, returncode=0):
    captured = {}
    monkeypatch.setattr(psexec_module, "convert_unc_to_local_path", lambda path, *_: str(path))
    monkeypatch.setattr(psexec_module.RasPlan, "set_num_cores", lambda *args, **kwargs: None)
    monkeypatch.setattr(BcoMonitor, "enable_detailed_logging", lambda path: None)
    monkeypatch.setattr(
        RasCmdr, "_destination_promotion_process_gate",
        staticmethod(lambda *args, **kwargs: (True, {})),
    )

    def run(command, **kwargs):
        staged = next(share.glob("TestProject_01_SW1_*/TestProject"))
        paths = get_plan_result_artifact_paths(
            "01", project_folder=staged, project_name="TestProject"
        )
        assert not paths.hdf.exists()
        assert not paths.legacy_output.exists()
        assert all(not path.exists() for path in paths.message_sidecars)
        captured["staged"] = staged
        captured["command"] = command
        captured["batch"] = (staged.parent / "run_plan_01.bat").read_text()
        captured["current_plan"] = (staged / "TestProject.prj").read_text()
        with h5py.File(paths.hdf, "w") as hdf:
            hdf.create_group("Plan Data/Plan Information")
            hdf.attrs["fixture"] = "fresh result"
            if sidecar is None and complete:
                hdf.create_dataset("Results/Summary/Compute Messages (text)", data=b"Complete Process\n")
        if sidecar is not None:
            paths.message_sidecars[sidecar].write_bytes(
                b"Complete Process\r\n" if complete else b"Calculation failed\r\n"
            )
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(psexec_module.subprocess, "run", run)
    return captured


def _execute(ras, worker):
    return psexec_module.execute_psexec_plan(
        worker, "01", ras, num_cores=2, clear_geompre=False,
        force_rerun=True, autoclean=True, copy_geometry_outputs=False,
    )


@pytest.mark.parametrize("version", ["5.0.7", "6.6"])
@pytest.mark.parametrize("sidecar", [0, 1, 2, None])
def test_psexec_publishes_exact_fresh_completion_evidence(monkeypatch, tmp_path, version, sidecar):
    ras, worker, share, paths = _seed(tmp_path, version)
    original_project = ras.prj_file.read_bytes()
    captured = _transport(monkeypatch, ras, share, sidecar=sidecar)

    assert _execute(ras, worker)
    assert RasCurrency.check_plan_hdf_complete(paths.hdf)
    with h5py.File(paths.hdf, "r") as hdf:
        assert hdf.attrs["fixture"] == "fresh result"
    assert not paths.legacy_output.exists()
    for index, path in enumerate(paths.message_sidecars):
        assert path.exists() == (index == sidecar)
        if path.exists():
            assert path.read_bytes() == b"Complete Process\r\n"
    assert not captured["staged"].parent.exists()
    assert ras.prj_file.read_bytes() == original_project
    staged_prj = captured["staged"] / "TestProject.prj"
    staged_plan = captured["staged"] / "TestProject.p01"
    if version.startswith("5."):
        assert captured["batch"] == f'"{worker.ras_exe_path}" "{staged_prj}" -c'
        assert "Current Plan=p01" in captured["current_plan"]
    else:
        assert captured["batch"] == f'"{worker.ras_exe_path}" -c "{staged_prj}" "{staged_plan}"'
        assert "Current Plan=p02" in captured["current_plan"]
    assert "-s" in captured["command"]
    assert captured["command"][captured["command"].index("-i") + 1] == "7"


@pytest.mark.parametrize("failure", ["promotion", "busy", "locked", "incomplete", "nonzero"])
def test_psexec_retains_worker_and_old_source_on_failure(monkeypatch, tmp_path, failure):
    ras, worker, share, paths = _seed(tmp_path)
    originals = {path: path.read_bytes() for path in (paths.hdf, paths.legacy_output, *paths.message_sidecars)}
    captured = _transport(
        monkeypatch, ras, share, sidecar=0 if failure == "promotion" else None,
        complete=failure != "incomplete",
        returncode=1 if failure == "nonzero" else 0,
    )
    if failure == "busy":
        monkeypatch.setattr(RasCmdr, "_destination_promotion_process_gate", staticmethod(lambda *a, **k: (False, {"busy": True})))
    elif failure == "locked":
        monkeypatch.setattr(RasCmdr, "_acquire_destination_promotion_lock", staticmethod(lambda **k: (None, {"locked": True})))
    elif failure == "promotion":
        cmdr_module = import_module("ras_commander.RasCmdr")
        original_replace = cmdr_module.os.replace

        def fail_primary(source, destination):
            source = Path(source)
            if source.parent.name == "s" and Path(destination) == paths.hdf:
                captured["publication_failed"] = True
                raise OSError("injected primary publication failure")
            return original_replace(source, destination)

        monkeypatch.setattr(cmdr_module.os, "replace", fail_primary)

    assert not _execute(ras, worker)
    assert captured["staged"].exists()
    assert (captured["staged"] / "TestProject.p01.hdf").exists()
    assert {path: path.read_bytes() for path in originals} == originals
    if failure == "promotion":
        assert captured["publication_failed"]


def test_psexec_preserves_worker_when_geometry_copyback_raises(monkeypatch, tmp_path):
    ras, worker, share, paths = _seed(tmp_path)
    captured = _transport(monkeypatch, ras, share, sidecar=None)

    def fail_geometry(**kwargs):
        raise OSError("injected geometry copyback failure")

    monkeypatch.setattr(psexec_module, "copy_geometry_outputs_back", fail_geometry)
    assert not psexec_module.execute_psexec_plan(
        worker, "01", ras, num_cores=2, clear_geompre=False,
        force_rerun=True, autoclean=True, copy_geometry_outputs=True,
    )
    assert RasCurrency.check_plan_hdf_complete(paths.hdf)
    assert captured["staged"].exists()


@pytest.mark.parametrize("version", ["4.0", "4.1"])
def test_psexec_rejects_com_only_engine_before_staging(monkeypatch, tmp_path, caplog, version):
    ras, worker, share, paths = _seed(tmp_path, version)
    before = {path: path.read_bytes() for path in ras.project_folder.iterdir() if path.is_file()}

    def no_launch(*args, **kwargs):
        pytest.fail("Unsupported COM-only version must not launch PsExec")

    monkeypatch.setattr(psexec_module.subprocess, "run", no_launch)
    assert not _execute(ras, worker)
    assert list(share.iterdir()) == []
    assert {path: path.read_bytes() for path in before} == before
    assert "requires COM controller execution" in caplog.text
