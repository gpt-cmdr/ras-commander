import importlib
import logging
from pathlib import Path

import pandas as pd


local_worker_module = importlib.import_module("ras_commander.remote.LocalWorker")


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
        "Plan Title=Local Worker Test\n",
        encoding="utf-8",
    )
    (project_folder / "TestProject.g03").write_text(
        "Geom Title=Test Geometry\n",
        encoding="utf-8",
    )
    return _FakeRasProject(project_folder)


def _local_worker(worker_folder: Path):
    worker_folder.mkdir(parents=True)
    return local_worker_module.LocalWorker(
        worker_type="local",
        worker_id="test-local-worker",
        worker_folder=str(worker_folder),
        ras_exe_path=r"C:\HEC-RAS\6.6\Ras.exe",
        process_priority="low",
        queue_priority=0,
    )


def _patch_local_execution(monkeypatch):
    rasprj_module = importlib.import_module("ras_commander.RasPrj")
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")

    def fake_init_ras_project(project_path, ras_version, ras_object=None, **kwargs):
        ras_object.project_folder = Path(project_path)
        ras_object.project_name = "TestProject"
        ras_object.ras_version = ras_version
        ras_object.ras_exe_path = r"C:\HEC-RAS\6.6\Ras.exe"
        return ras_object

    def fake_compute_plan(plan_number, ras_object, **kwargs):
        hdf_path = Path(ras_object.project_folder) / f"{ras_object.project_name}.p{plan_number}.hdf"
        hdf_path.write_text("result\n", encoding="utf-8")
        return True

    monkeypatch.setattr(rasprj_module, "init_ras_project", fake_init_ras_project)
    monkeypatch.setattr(
        rascmdr_module.RasCmdr,
        "compute_plan",
        staticmethod(fake_compute_plan),
    )
    monkeypatch.setattr(
        local_worker_module.RasCurrency,
        "get_plan_hdf_path",
        staticmethod(
            lambda plan_number, ras_obj: Path(ras_obj.project_folder)
            / f"{ras_obj.project_name}.p{plan_number}.hdf"
        ),
    )
    monkeypatch.setattr(
        local_worker_module.RasCurrency,
        "check_plan_hdf_complete",
        staticmethod(lambda path: True),
    )
    monkeypatch.setattr(
        local_worker_module,
        "clear_worker_plan_hdf_artifacts",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        local_worker_module,
        "copy_plan_hdf_back",
        lambda worker_project_path, plan_number, ras_obj: Path(ras_obj.project_folder)
        / f"{ras_obj.project_name}.p{plan_number}.hdf",
    )
    monkeypatch.setattr(
        local_worker_module,
        "copy_geometry_outputs_back",
        lambda **kwargs: [],
    )


def test_init_local_worker_logging_is_concise(tmp_path, caplog):
    worker_folder = tmp_path / "local_workers"
    ras_exe_path = r"C:\HEC-RAS\6.6\Ras.exe"

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.LocalWorker"):
        worker = local_worker_module.init_local_worker(
            worker_folder=str(worker_folder),
            ras_exe_path=ras_exe_path,
            process_priority="low",
            queue_priority=0,
            cores_total=8,
            cores_per_plan=2,
        )

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
        and record.name == "ras_commander.remote.LocalWorker"
    ]
    debug_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.remote.LocalWorker"
    )
    info_text = "\n".join(info_messages)

    assert worker.max_parallel_plans == 4
    assert info_messages == [
        "Local worker configured: priority=low, queue=0, slots=4",
    ]
    assert str(worker_folder) not in info_text
    assert ras_exe_path not in info_text
    assert str(worker_folder) in debug_text
    assert ras_exe_path in debug_text


def test_execute_local_plan_paths_are_debug_not_info(monkeypatch, tmp_path, caplog):
    ras_obj = _seed_project(tmp_path / "project")
    worker_folder = tmp_path / "workers"
    worker = _local_worker(worker_folder)
    _patch_local_execution(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.LocalWorker"):
        assert local_worker_module.execute_local_plan(
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
        if record.levelno == logging.INFO
        and record.name == "ras_commander.remote.LocalWorker"
    )
    debug_text = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.remote.LocalWorker"
    )

    assert str(worker_folder) not in info_text
    assert "Starting local execution" not in info_text
    assert "HDF file created successfully" not in info_text
    assert "Copying project for plan 07 to local worker folder" in debug_text
    assert str(worker_folder) in debug_text
    assert "Executing plan 07 with RasCmdr.compute_plan()" in debug_text
    assert "HDF file created successfully for plan 07" in debug_text


def test_execute_local_plan_preserve_folder_info_is_concise(
    monkeypatch,
    tmp_path,
    caplog,
):
    ras_obj = _seed_project(tmp_path / "project")
    worker_folder = tmp_path / "workers"
    worker = _local_worker(worker_folder)
    _patch_local_execution(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.LocalWorker"):
        assert local_worker_module.execute_local_plan(
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
        if record.levelno == logging.INFO
        and record.name == "ras_commander.remote.LocalWorker"
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.remote.LocalWorker"
    ]

    assert info_messages == [
        "Preserving local worker folder for plan 07 for debugging; "
        "enable DEBUG logging for the path"
    ]
    assert str(worker_folder) not in info_messages[0]
    assert any(
        "Preserved worker folder:" in message and str(worker_folder) in message
        for message in debug_messages
    )


def test_execute_local_plan_compute_failure_error_has_path_context(
    monkeypatch,
    tmp_path,
    caplog,
):
    ras_obj = _seed_project(tmp_path / "project")
    worker_folder = tmp_path / "workers"
    worker = _local_worker(worker_folder)
    _patch_local_execution(monkeypatch)
    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")

    monkeypatch.setattr(
        rascmdr_module.RasCmdr,
        "compute_plan",
        staticmethod(lambda **kwargs: False),
    )

    with caplog.at_level(logging.ERROR, logger="ras_commander.remote.LocalWorker"):
        assert not local_worker_module.execute_local_plan(
            worker=worker,
            plan_number="07",
            ras_obj=ras_obj,
            num_cores=2,
            clear_geompre=False,
            force_rerun=True,
        )

    error_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.ERROR
        and record.name == "ras_commander.remote.LocalWorker"
    ]

    assert len(error_messages) == 1
    assert "RasCmdr.compute_plan() returned False for plan 07" in error_messages[0]
    assert str(worker_folder) in error_messages[0]
    assert "TestProject_07_SW1_" in error_messages[0]
