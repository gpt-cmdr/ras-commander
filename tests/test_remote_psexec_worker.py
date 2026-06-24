import importlib
from pathlib import Path
from types import SimpleNamespace

import h5py
import pandas as pd

from ras_commander.RasCurrency import RasCurrency
from ras_commander.remote.PsexecWorker import PsexecWorker, execute_psexec_plan

psexec_module = importlib.import_module("ras_commander.remote.PsexecWorker")


class _FakeRasProject:
    def __init__(self, project_folder: Path):
        self.project_folder = Path(project_folder)
        self.project_name = "TestProject"
        self.ras_version = "6.6"
        self.ras_exe_path = r"C:\HEC-RAS\6.6\Ras.exe"
        self.plan_df = pd.DataFrame(
            [
                {
                    "plan_number": "07",
                    "geometry_number": "03",
                    "full_path": str(self.project_folder / "TestProject.p07"),
                    "Geom Path": str(self.project_folder / "TestProject.g03"),
                }
            ]
        )


def _seed_project(project_folder: Path) -> _FakeRasProject:
    project_folder.mkdir(parents=True)
    (project_folder / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    (project_folder / "TestProject.p07").write_text(
        "Plan Title=Remote Test\n",
        encoding="utf-8",
    )
    (project_folder / "TestProject.p07.hdf").write_text(
        "result\n",
        encoding="utf-8",
    )
    (project_folder / "TestProject.g03.hdf").write_text(
        "stale geometry\n",
        encoding="utf-8",
    )
    (project_folder / "TestProject.g03").write_text(
        "Geom Title=Test Geometry\n",
        encoding="utf-8",
    )
    (project_folder / "TestProject.c03").write_text(
        "stale preprocessor\n",
        encoding="utf-8",
    )
    return _FakeRasProject(project_folder)


def _worker(share_path: Path) -> PsexecWorker:
    share_path.mkdir(parents=True)
    return PsexecWorker(
        worker_type="psexec",
        worker_id="test-worker",
        hostname="test-host",
        share_path=str(share_path),
        worker_folder=str(share_path),
        ras_exe_path=r"C:\HEC-RAS\6.6\Ras.exe",
        psexec_path="psexec.exe",
    )


def _write_worker_outputs(share_path: Path, *, include_geometry: bool = True) -> None:
    share_path = Path(share_path)
    staged_projects = list(share_path.glob("TestProject_07_SW1_*/TestProject"))
    assert staged_projects
    staged_project = staged_projects[0]
    _write_complete_plan_hdf(staged_project / "TestProject.p07.hdf")
    if include_geometry:
        (staged_project / "TestProject.g03.hdf").write_text(
            "fresh geometry\n",
            encoding="utf-8",
        )
        (staged_project / "TestProject.c03").write_text(
            "fresh preprocessor\n",
            encoding="utf-8",
        )


def _write_complete_plan_hdf(hdf_path: Path) -> None:
    with h5py.File(hdf_path, "w") as hdf_file:
        hdf_file.create_group("Plan Data/Plan Information")
        hdf_file.create_dataset(
            "Results/Summary/Compute Messages (text)",
            data=b"Complete Process",
        )


def test_execute_psexec_plan_honors_clear_geompre_before_staging(
    monkeypatch,
    tmp_path,
):
    ras_obj = _seed_project(tmp_path / "project")
    worker = _worker(tmp_path / "share")
    calls = []
    real_copytree = psexec_module.shutil.copytree

    def fake_clear_geompre(plan_path, ras_object=None):
        calls.append(("clear_geompre", Path(plan_path).name))

    def fake_copytree(src, dst, *args, **kwargs):
        calls.append(("copytree", Path(src).name, Path(dst).name))
        return real_copytree(src, dst, *args, **kwargs)

    def fake_subprocess_run(*args, **kwargs):
        _write_worker_outputs(worker.share_path)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        psexec_module.GeomPreprocessor,
        "clear_geompre_files",
        staticmethod(fake_clear_geompre),
    )
    monkeypatch.setattr(psexec_module.shutil, "copytree", fake_copytree)
    monkeypatch.setattr(psexec_module.subprocess, "run", fake_subprocess_run)

    assert execute_psexec_plan(
        worker=worker,
        plan_number="07",
        ras_obj=ras_obj,
        num_cores=2,
        clear_geompre=True,
        force_rerun=True,
    )

    assert calls[:2] == [
        ("clear_geompre", "TestProject.p07"),
        ("copytree", "project", "TestProject"),
    ]


def test_execute_psexec_plan_force_geompre_clears_hdf_and_geompre(
    monkeypatch,
    tmp_path,
):
    ras_obj = _seed_project(tmp_path / "project")
    worker = _worker(tmp_path / "share")
    calls = []

    monkeypatch.setattr(
        RasCurrency,
        "clear_geom_hdf",
        staticmethod(
            lambda plan_number, ras_object: (
                calls.append(("clear_hdf", plan_number)) or True
            )
        ),
    )
    monkeypatch.setattr(
        psexec_module.GeomPreprocessor,
        "clear_geompre_files",
        staticmethod(
            lambda plan_path, ras_object=None: calls.append(
                ("clear_geompre", Path(plan_path).name)
            )
        ),
    )
    monkeypatch.setattr(
        psexec_module.subprocess,
        "run",
        lambda *args, **kwargs: (
            _write_worker_outputs(worker.share_path)
            or SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )

    assert execute_psexec_plan(
        worker=worker,
        plan_number="07",
        ras_obj=ras_obj,
        num_cores=2,
        clear_geompre=False,
        force_geompre=True,
        force_rerun=True,
    )

    assert calls == [
        ("clear_hdf", "07"),
        ("clear_geompre", "TestProject.p07"),
    ]


def test_execute_psexec_plan_copies_geometry_outputs_back(
    monkeypatch,
    tmp_path,
):
    ras_obj = _seed_project(tmp_path / "project")
    share_path = tmp_path / "share"
    worker = _worker(share_path)

    def fake_subprocess_run(*args, **kwargs):
        _write_worker_outputs(share_path)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(psexec_module.subprocess, "run", fake_subprocess_run)

    assert execute_psexec_plan(
        worker=worker,
        plan_number="07",
        ras_obj=ras_obj,
        num_cores=2,
        clear_geompre=False,
        force_rerun=True,
    )

    assert (ras_obj.project_folder / "TestProject.g03.hdf").read_text(
        encoding="utf-8"
    ) == "fresh geometry\n"
    assert RasCurrency.check_plan_hdf_complete(
        ras_obj.project_folder / "TestProject.p07.hdf"
    )
    assert (ras_obj.project_folder / "TestProject.c03").read_text(
        encoding="utf-8"
    ) == "fresh preprocessor\n"


def test_execute_psexec_plan_rejects_stale_copied_hdf(
    monkeypatch,
    tmp_path,
):
    ras_obj = _seed_project(tmp_path / "project")
    worker = _worker(tmp_path / "share")

    monkeypatch.setattr(
        psexec_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert not execute_psexec_plan(
        worker=worker,
        plan_number="07",
        ras_obj=ras_obj,
        num_cores=2,
        clear_geompre=False,
        force_rerun=True,
    )

    assert (ras_obj.project_folder / "TestProject.p07.hdf").read_text(
        encoding="utf-8"
    ) == "result\n"


def test_execute_psexec_plan_requires_geometry_copyback(
    monkeypatch,
    tmp_path,
):
    ras_obj = _seed_project(tmp_path / "project")
    share_path = tmp_path / "share"
    worker = _worker(share_path)

    def fake_subprocess_run(*args, **kwargs):
        _write_worker_outputs(share_path, include_geometry=False)
        staged_project = next(share_path.glob("TestProject_07_SW1_*/TestProject"))
        (staged_project / "TestProject.g03.hdf").unlink()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(psexec_module.subprocess, "run", fake_subprocess_run)

    assert not execute_psexec_plan(
        worker=worker,
        plan_number="07",
        ras_obj=ras_obj,
        num_cores=2,
        clear_geompre=False,
        force_rerun=True,
    )

    assert (ras_obj.project_folder / "TestProject.g03.hdf").read_text(
        encoding="utf-8"
    ) == "stale geometry\n"
