"""Regression coverage for PsExec force_geompre staging semantics."""

from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from ras_commander.RasBco import BcoMonitor
from ras_commander.RasCurrency import RasCurrency
from ras_commander.geom import GeomPreprocessor


psexec_module = import_module("ras_commander.remote.PsexecWorker")


def test_force_geompre_bypasses_skip_and_preserves_source(monkeypatch, tmp_path):
    """force_geompre clears only the staged copy, even when source results are current."""
    source = tmp_path / "source"
    source.mkdir()
    share = tmp_path / "share"
    share.mkdir()

    (source / "TestProject.prj").write_text("Proj Title=Test\n", encoding="utf-8")
    (source / "TestProject.p01").write_text("Plan Title=Test\n", encoding="utf-8")
    source_geom = source / "TestProject.g01.hdf"
    source_geom.write_text("source geometry association", encoding="utf-8")
    source_geompre = source / "TestProject.c01"
    source_geompre.write_text("source preprocessor", encoding="utf-8")

    ras_obj = SimpleNamespace(project_folder=source, project_name="TestProject")
    worker = SimpleNamespace(
        worker_id="psexec-test",
        hostname="TESTHOST",
        share_path=str(share),
        worker_folder=r"C:\\RasRemote",
        credentials={},
        psexec_path="PsExec.exe",
        ras_exe_path=r"C:\\HEC-RAS\\Ras.exe",
        system_account=False,
        session_id=2,
        process_priority="normal",
        max_runtime_minutes=1,
    )

    currency_calls = {"count": 0}
    cleared = {}

    def fake_currency(*args, **kwargs):
        currency_calls["count"] += 1
        return True, "results are current"

    def fake_clear(plan_files, ras_object=None):
        staged_plan = Path(plan_files)
        assert share in staged_plan.parents
        assert source not in staged_plan.parents
        staged_geom = staged_plan.with_name("TestProject.g01.hdf")
        staged_geompre = staged_plan.with_name("TestProject.c01")
        assert staged_geom.read_text(encoding="utf-8") == "source geometry association"
        staged_geom.write_text("staged tables cleared in place", encoding="utf-8")
        staged_geompre.unlink()
        cleared["plan"] = staged_plan

    def fake_run(*args, **kwargs):
        staged_projects = list(share.glob("TestProject_01_SW1_*/TestProject"))
        assert len(staged_projects) == 1
        staged = staged_projects[0]
        assert (staged / "TestProject.g01.hdf").read_text(
            encoding="utf-8"
        ) == "staged tables cleared in place"
        assert not (staged / "TestProject.c01").exists()
        (staged / "TestProject.p01.hdf").write_text(
            "completed result", encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        RasCurrency, "are_plan_results_current", staticmethod(fake_currency)
    )
    monkeypatch.setattr(
        RasCurrency, "check_plan_hdf_complete", staticmethod(lambda path: True)
    )
    monkeypatch.setattr(
        GeomPreprocessor, "clear_geompre_files", staticmethod(fake_clear)
    )
    monkeypatch.setattr(
        BcoMonitor, "enable_detailed_logging", staticmethod(lambda path: None)
    )
    monkeypatch.setattr(
        psexec_module,
        "RasPlan",
        SimpleNamespace(set_num_cores=lambda *args, **kwargs: None),
        raising=False,
    )
    monkeypatch.setattr(
        psexec_module, "convert_unc_to_local_path", lambda value, *_: str(value)
    )
    monkeypatch.setattr(psexec_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        psexec_module,
        "copy_plan_hdf_back",
        lambda *args, **kwargs: source / "TestProject.p01.hdf",
    )
    monkeypatch.setattr(
        psexec_module, "copy_geometry_outputs_back", lambda *args, **kwargs: []
    )

    success = psexec_module.execute_psexec_plan(
        worker=worker,
        plan_number="01",
        ras_obj=ras_obj,
        num_cores=2,
        clear_geompre=False,
        force_geompre=True,
        force_rerun=False,
        autoclean=False,
    )

    assert success is True
    assert currency_calls["count"] == 0
    assert "plan" in cleared
    assert source_geom.read_text(encoding="utf-8") == "source geometry association"
    assert source_geompre.read_text(encoding="utf-8") == "source preprocessor"
