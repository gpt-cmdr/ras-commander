import importlib
import logging
from pathlib import Path
from types import SimpleNamespace


dockerworker_module = importlib.import_module("ras_commander.remote.DockerWorker")


class _FakeImageNotFound(Exception):
    pass


class _FakeDockerException(Exception):
    pass


class _FakeImages:
    def get(self, image):
        return object()


class _FakeContainers:
    def __init__(self, container):
        self._container = container

    def run(self, **kwargs):
        return self._container


class _FakeClient:
    def __init__(self, container=None):
        self.images = _FakeImages()
        self.containers = _FakeContainers(container or _FakeContainer())

    def ping(self):
        return True

    def close(self):
        pass


class _FakeContainer:
    short_id = "abc123"

    def __init__(self, exit_code=0, logs="container ok\n"):
        self._exit_code = exit_code
        self._logs = logs

    def wait(self, timeout=None):
        return {"StatusCode": self._exit_code}

    def logs(self, stdout=True, stderr=True):
        return self._logs.encode("utf-8")

    def remove(self):
        pass

    def kill(self):
        pass


class _FakeDockerModule:
    errors = SimpleNamespace(
        ImageNotFound=_FakeImageNotFound,
        DockerException=_FakeDockerException,
    )

    def __init__(self, client=None):
        self._client = client or _FakeClient()

    def DockerClient(self, **kwargs):
        return self._client

    def from_env(self):
        return self._client


class _FakeRasProject:
    def __init__(self, project_folder: Path):
        self.project_folder = Path(project_folder)
        self.project_name = "TestProject"
        self.ras_version = "6.6"


def _seed_project(project_folder: Path) -> _FakeRasProject:
    project_folder.mkdir(parents=True)
    (project_folder / "TestProject.prj").write_text(
        "Proj Title=TestProject\n",
        encoding="utf-8",
    )
    (project_folder / "TestProject.p07").write_text(
        "Plan Title=Docker Test\nGeom File=g03\n",
        encoding="utf-8",
    )
    return _FakeRasProject(project_folder)


def _dockerworker_messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == level
        and record.name == "ras_commander.remote.DockerWorker"
    ]


def _patch_docker(monkeypatch, fake_docker):
    monkeypatch.setattr(
        dockerworker_module,
        "check_docker_dependencies",
        lambda: fake_docker,
    )


def _patch_geometry_number(monkeypatch, geometry_number):
    raspreprocess_module = importlib.import_module("ras_commander.RasPreprocess")
    monkeypatch.setattr(
        raspreprocess_module.RasPreprocess,
        "_extract_geometry_number",
        staticmethod(lambda plan_path: geometry_number),
    )


def test_init_docker_worker_logging_is_concise(monkeypatch, tmp_path, caplog):
    fake_docker = _FakeDockerModule()
    _patch_docker(monkeypatch, fake_docker)
    ssh_key_path = tmp_path / "id_rsa"

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.DockerWorker"):
        worker = dockerworker_module.init_docker_worker(
            docker_image="hecras:6.6",
            docker_host="ssh://user@example-host",
            share_path=str(tmp_path / "share"),
            remote_staging_path=r"C:\RasRemote",
            use_ssh_client=True,
            ssh_key_path=str(ssh_key_path),
            cores_total=8,
            cores_per_plan=4,
        )

    info_text = "\n".join(_dockerworker_messages(caplog, logging.INFO))
    debug_text = "\n".join(_dockerworker_messages(caplog, logging.DEBUG))

    assert worker.max_parallel_plans == 2
    assert "Docker worker configured: image=hecras:6.6, host=remote" in info_text
    assert str(ssh_key_path) not in info_text
    assert "ssh://user@example-host" not in info_text
    assert str(ssh_key_path) in debug_text
    assert "ssh://user@example-host" in debug_text


def test_execute_docker_plan_remote_staging_paths_are_debug(
    monkeypatch,
    tmp_path,
    caplog,
):
    ras_obj = _seed_project(tmp_path / "project")
    share_path = tmp_path / "remote_share"
    worker = dockerworker_module.DockerWorker(
        worker_type="docker",
        docker_image="hecras:6.6",
        docker_host="ssh://user@example-host",
        share_path=str(share_path),
        remote_staging_path=r"C:\RasRemote",
        preprocess_on_host=False,
    )
    _patch_docker(monkeypatch, _FakeDockerModule())
    _patch_geometry_number(monkeypatch, None)

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.DockerWorker"):
        assert not dockerworker_module.execute_docker_plan(
            worker=worker,
            plan_number="07",
            ras_obj=ras_obj,
            num_cores=2,
            clear_geompre=False,
        )

    info_text = "\n".join(_dockerworker_messages(caplog, logging.INFO))
    debug_text = "\n".join(_dockerworker_messages(caplog, logging.DEBUG))
    error_text = "\n".join(_dockerworker_messages(caplog, logging.ERROR))

    assert "Linux Docker staging configured for plan 07" in info_text
    assert str(share_path) not in info_text
    assert "ssh://user@example-host" not in info_text
    assert "ssh://user@example-host" in debug_text
    assert "Could not extract geometry number for plan 07" in error_text
    assert "searched pattern '*.p07'" in error_text


def test_execute_docker_plan_failed_container_logs_tail_at_error(
    monkeypatch,
    tmp_path,
    caplog,
):
    ras_obj = _seed_project(tmp_path / "project")
    logs = "\n".join(f"line {i}" for i in range(1, 51))
    container = _FakeContainer(exit_code=1, logs=logs)
    worker = dockerworker_module.DockerWorker(
        worker_type="docker",
        docker_image="hecras:6.6",
        preprocess_on_host=False,
        staging_directory=str(tmp_path / "staging"),
    )
    _patch_docker(monkeypatch, _FakeDockerModule(_FakeClient(container)))
    _patch_geometry_number(monkeypatch, "03")

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.DockerWorker"):
        assert not dockerworker_module.execute_docker_plan(
            worker=worker,
            plan_number="07",
            ras_obj=ras_obj,
            num_cores=2,
            clear_geompre=False,
        )

    error_text = "\n".join(_dockerworker_messages(caplog, logging.ERROR))
    debug_text = "\n".join(_dockerworker_messages(caplog, logging.DEBUG))
    error_lines = error_text.splitlines()
    debug_lines = debug_text.splitlines()

    assert "Container failed with exit code 1; last 40 of 50 log line(s)" in error_text
    assert "line 1" not in error_lines
    assert "line 10" not in error_lines
    assert "line 11" in error_lines
    assert "line 50" in error_lines
    assert "line 1" in debug_lines


def test_execute_docker_plan_missing_hdf_and_preserve_paths(
    monkeypatch,
    tmp_path,
    caplog,
):
    ras_obj = _seed_project(tmp_path / "project")
    staging_directory = tmp_path / "staging"
    worker = dockerworker_module.DockerWorker(
        worker_type="docker",
        docker_image="hecras:6.6",
        preprocess_on_host=False,
        staging_directory=str(staging_directory),
    )
    _patch_docker(monkeypatch, _FakeDockerModule())
    _patch_geometry_number(monkeypatch, "03")

    with caplog.at_level(logging.DEBUG, logger="ras_commander.remote.DockerWorker"):
        assert not dockerworker_module.execute_docker_plan(
            worker=worker,
            plan_number="07",
            ras_obj=ras_obj,
            num_cores=2,
            clear_geompre=False,
            autoclean=False,
        )

    info_text = "\n".join(_dockerworker_messages(caplog, logging.INFO))
    debug_text = "\n".join(_dockerworker_messages(caplog, logging.DEBUG))
    error_text = "\n".join(_dockerworker_messages(caplog, logging.ERROR))

    assert "No HDF results found for plan 07" in error_text
    assert "output_staging=" in error_text
    assert "input_staging=" in error_text
    assert (
        "Preserving Docker staging for plan 07 for debugging; "
        "enable DEBUG logging for the path"
    ) in info_text
    assert str(staging_directory) not in info_text
    assert str(staging_directory) in debug_text
