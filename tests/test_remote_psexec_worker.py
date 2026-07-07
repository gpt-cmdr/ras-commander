import importlib
import logging
from pathlib import Path
from types import SimpleNamespace

import h5py
import pandas as pd

from ras_commander.RasCurrency import RasCurrency
from ras_commander.remote.PsexecWorker import PsexecWorker, execute_psexec_plan

psexec_module = importlib.import_module("ras_commander.remote.PsexecWorker")
utils_module = importlib.import_module("ras_commander.remote.Utils")


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


def test_init_psexec_worker_logging_is_concise(
    monkeypatch,
    tmp_path,
    caplog,
):
    psexec_path = tmp_path / "PsExec.exe"
    psexec_path.write_text("stub", encoding="utf-8")
    share_path = tmp_path / "share"
    worker_folder = tmp_path / "remote_worker"
    username = r".\bill"

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.PsexecWorker"):
        worker = psexec_module.init_psexec_worker(
            hostname="test-host",
            share_path=str(share_path),
            worker_folder=str(worker_folder),
            credentials={"username": username, "password": "secret"},
            ras_exe_path=r"C:\HEC-RAS\6.6\Ras.exe",
            psexec_path=str(psexec_path),
            cores_total=8,
            cores_per_plan=4,
        )

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
    ]
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    debug_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
    )
    info_text = "\n".join(info_messages)

    assert worker.max_parallel_plans == 2
    assert warning_messages == []
    assert len(info_messages) == 2
    assert "Initializing PsExec worker for test-host" in info_messages
    assert "PsExec worker configured: host=test-host" in info_text
    assert "auth=explicit credentials" in info_text
    assert "slots=2" in info_text
    assert "validation deferred to execution" in info_text
    assert str(share_path) not in info_text
    assert str(worker_folder) not in info_text
    assert str(psexec_path) not in info_text
    assert username not in info_text
    assert str(share_path) in debug_text
    assert str(worker_folder) in debug_text
    assert str(psexec_path) in debug_text
    assert username in debug_text


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


def test_execute_psexec_plan_paths_are_debug_not_info(
    monkeypatch,
    tmp_path,
    caplog,
):
    ras_obj = _seed_project(tmp_path / "project")
    share_path = tmp_path / "share"
    worker = _worker(share_path)

    def fake_subprocess_run(*args, **kwargs):
        _write_worker_outputs(share_path)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(psexec_module.subprocess, "run", fake_subprocess_run)

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.PsexecWorker"):
        assert execute_psexec_plan(
            worker=worker,
            plan_number="07",
            ras_obj=ras_obj,
            num_cores=2,
            clear_geompre=False,
            force_rerun=True,
        )

    info_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if (
            record.levelno == logging.INFO
            and record.name == "ras_commander.remote.PsexecWorker"
        )
    )
    debug_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if (
            record.levelno == logging.DEBUG
            and record.name == "ras_commander.remote.PsexecWorker"
        )
    )

    assert str(share_path) not in info_text
    assert "Executing PsExec command" not in info_text
    assert "HDF file created successfully" not in info_text
    assert "Copying project for plan 07 to worker folder" in debug_text
    assert str(share_path) in debug_text
    assert "Executing PsExec command" in debug_text
    assert "HDF file created successfully for plan 07" in debug_text


def test_execute_psexec_plan_preserve_folder_info_is_concise(
    monkeypatch,
    tmp_path,
    caplog,
):
    ras_obj = _seed_project(tmp_path / "project")
    share_path = tmp_path / "share"
    worker = _worker(share_path)

    def fake_subprocess_run(*args, **kwargs):
        _write_worker_outputs(share_path)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(psexec_module.subprocess, "run", fake_subprocess_run)

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.PsexecWorker"):
        assert execute_psexec_plan(
            worker=worker,
            plan_number="07",
            ras_obj=ras_obj,
            num_cores=2,
            clear_geompre=False,
            force_rerun=True,
            autoclean=False,
        )

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if (
            record.levelno == logging.INFO
            and record.name == "ras_commander.remote.PsexecWorker"
        )
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if (
            record.levelno == logging.DEBUG
            and record.name == "ras_commander.remote.PsexecWorker"
        )
    ]

    assert info_messages == [
        "Preserving PsExec worker folder for plan 07 for debugging; "
        "enable DEBUG logging for the path"
    ]
    assert str(share_path) not in info_messages[0]
    assert any(
        "Preserved worker folder:" in message and str(share_path) in message
        for message in debug_messages
    )


def test_copy_plan_hdf_back_info_uses_basename_debug_has_paths(
    monkeypatch,
    tmp_path,
    caplog,
):
    worker_project = tmp_path / "worker_project"
    worker_project.mkdir()
    dest_project = tmp_path / "source_project"
    dest_project.mkdir()
    dest_hdf = dest_project / "TestProject.p07.hdf"
    worker_hdf = worker_project / dest_hdf.name
    worker_hdf.write_text("result", encoding="utf-8")

    monkeypatch.setattr(
        RasCurrency,
        "get_plan_hdf_path",
        staticmethod(lambda plan_number, ras_obj: dest_hdf),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.Utils"):
        result = utils_module.copy_plan_hdf_back(
            worker_project,
            "07",
            ras_obj=object(),
        )

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.name == "ras_commander.remote.Utils"
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.remote.Utils"
    ]

    assert result == dest_hdf
    assert dest_hdf.read_text(encoding="utf-8") == "result"
    assert info_messages == [
        "Copied plan result HDF for plan 07: TestProject.p07.hdf"
    ]
    assert str(dest_project) not in info_messages[0]
    assert any(
        str(worker_hdf) in message and str(dest_hdf) in message
        for message in debug_messages
    )


def test_copy_geometry_outputs_back_info_uses_basenames_debug_has_paths(
    monkeypatch,
    tmp_path,
    caplog,
):
    worker_project = tmp_path / "worker_project"
    worker_project.mkdir()
    source_project = tmp_path / "source_project"
    source_project.mkdir()

    source_geom_hdf = source_project / "TestProject.g03.hdf"
    source_geompre = source_project / "TestProject.c03"
    worker_geom_hdf = worker_project / source_geom_hdf.name
    worker_geompre = worker_project / source_geompre.name
    worker_geom_hdf.write_text("fresh geometry", encoding="utf-8")
    worker_geompre.write_text("fresh geompre", encoding="utf-8")

    monkeypatch.setattr(
        RasCurrency,
        "get_geom_hdf_path",
        staticmethod(lambda plan_number, ras_obj: source_geom_hdf),
    )
    monkeypatch.setattr(
        RasCurrency,
        "get_plan_input_files",
        staticmethod(
            lambda plan_number, ras_obj: {
                "geom": source_project / "TestProject.g03"
            }
        ),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.Utils"):
        copied = utils_module.copy_geometry_outputs_back(
            worker_project_path=worker_project,
            project_folder=source_project,
            project_name="TestProject",
            plan_number="07",
            ras_obj=object(),
        )

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.name == "ras_commander.remote.Utils"
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.remote.Utils"
    ]

    assert copied == [source_geom_hdf, source_geompre]
    assert source_geom_hdf.read_text(encoding="utf-8") == "fresh geometry"
    assert source_geompre.read_text(encoding="utf-8") == "fresh geompre"
    assert info_messages == [
        "Copied geometry HDF for plan 07: TestProject.g03.hdf",
        "Copied geometry preprocessor file for plan 07: TestProject.c03",
    ]
    assert all(str(source_project) not in message for message in info_messages)
    assert any(
        str(worker_geom_hdf) in message and str(source_geom_hdf) in message
        for message in debug_messages
    )
    assert any(
        str(worker_geompre) in message and str(source_geompre) in message
        for message in debug_messages
    )


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
