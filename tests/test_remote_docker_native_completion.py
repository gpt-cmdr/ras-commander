"""Native Docker results need native completion evidence, not Windows messages."""

import importlib
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import h5py
import pytest


docker_module = importlib.import_module("ras_commander.remote.DockerWorker")
stager_module = importlib.import_module("ras_commander.remote.DockerSshStaging")


@pytest.mark.parametrize(
    "backend, scenario, expected",
    [(backend, scenario, expected) for backend in ("desktop", "ssh")
     for scenario, expected in (
        ("native_lf", True),
        ("native_crlf", True),
        ("nonzero_exit", False),
        ("in_band_error", False),
        ("missing_banner", False),
        ("empty_results", False),
        ("temporary_only", False),
        ("wrong_plan", False),
    )] + [("desktop", "stale_result", False)],
)
def test_native_container_completion_and_failure_preserve_prior_results(
    tmp_path, monkeypatch, backend, scenario, expected
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "Model.prj").write_text("Proj Title=Model\nPlan File=p07\n")
    (source / "Model.p07").write_text(
        "Plan Title=Native\nProgram Version=6.6\nGeom File=g03\n"
    )
    (source / "Model.p07.tmp.hdf").write_bytes(b"preserved preparation input")
    final = source / "Model.p07.hdf"
    final.write_bytes(b"prior final result")
    opposing = source / "Model.O07"
    opposing.write_bytes(b"prior opposing result")
    model = SimpleNamespace(project_folder=source, project_name="Model", ras_version="6.6")

    result_name = (
        "Model.p07.tmp.hdf" if scenario == "temporary_only"
        else "Model.p08.hdf" if scenario == "wrong_plan"
        else "Model.p07.hdf"
    )
    fixture = tmp_path / "native-output.hdf"
    with h5py.File(fixture, "w") as hdf:
        hdf.create_group("Plan Data/Plan Information")
        hdf.create_group("Event Conditions").attrs["Completed Successfully"] = True
        unsteady = hdf.create_group("Results/Unsteady")
        if scenario != "empty_results":
            unsteady.create_dataset("Water Surface", data=[[1.0, 2.0]])
        assert "Results/Summary/Compute Messages (text)" not in hdf

    captured = {}
    newline = "\r\n" if scenario == "native_crlf" else "\n"
    logs = "native solver started" + newline
    if scenario != "missing_banner":
        logs += "Finished Unsteady Flow Simulation" + newline
    if scenario == "in_band_error":
        logs += "HDF_ERROR: result could not be finalized" + newline

    class Container:
        short_id = "native-test"

        def wait(self, timeout):
            if backend == "desktop":
                output = Path(captured["output"])
                shutil.copy2(fixture, output / result_name)
                if scenario == "stale_result":
                    os.utime(output / result_name, (1, 1))
            return {"StatusCode": 1 if scenario == "nonzero_exit" else 0}

        def logs(self, **kwargs):
            return logs.encode("utf-8")

        def remove(self):
            pass

        def kill(self):
            pass

    def run_container(**kwargs):
        for path, mount in kwargs["volumes"].items():
            if mount["bind"] == "/app/output":
                captured["output"] = path
            if backend == "desktop" and mount["bind"] == "/app/input":
                assert not (Path(path) / "Model.p07.hdf").exists()
                assert not (Path(path) / "Model.O07").exists()
                assert (Path(path) / "Model.p07.tmp.hdf").read_bytes() == b"preserved preparation input"
        return Container()

    client = SimpleNamespace(containers=SimpleNamespace(run=run_container), close=lambda: None)
    docker = SimpleNamespace(from_env=lambda: client, DockerClient=lambda **kwargs: client)
    monkeypatch.setattr(docker_module, "check_docker_dependencies", lambda: docker)
    preprocess = importlib.import_module("ras_commander.RasPreprocess")
    monkeypatch.setattr(preprocess.RasPreprocess, "_extract_geometry_number", lambda _: "03")

    class Stager:
        def __init__(self, **kwargs):
            pass

        def mkdirs(self, paths):
            pass

        def upload_dir(self, local, remote):
            assert not (local / "Model.p07.hdf").exists()
            assert not (local / "Model.O07").exists()
            assert (local / "Model.p07.tmp.hdf").read_bytes() == b"preserved preparation input"
            return 3

        def list_matching(self, directory, patterns):
            if directory.endswith("/output") and result_name in patterns:
                return [directory + "/" + result_name]
            return []

        def download_files(self, paths, destination):
            path = Path(destination) / result_name
            shutil.copy2(fixture, path)
            return [path]

        def rmtree(self, path):
            pass

    monkeypatch.setattr(stager_module, "LinuxDockerSshStager", Stager)
    worker = docker_module.DockerWorker(
        worker_type="docker", docker_image="native:6.6", preprocess_on_host=False,
        staging_directory=str(tmp_path / "staging"),
        **({"docker_host": "ssh://user@test", "remote_staging_path": "/scratch/tests"}
           if backend == "ssh" else {}),
    )
    success = docker_module.execute_docker_plan(
        worker, "07", model, num_cores=2, clear_geompre=False, autoclean=True,
    )
    assert success is expected
    assert (source / "Model.p07.tmp.hdf").read_bytes() == b"preserved preparation input"
    if expected:
        with h5py.File(final, "r") as hdf:
            assert hdf["Results/Unsteady/Water Surface"].size == 2
        assert not opposing.exists()
    else:
        assert final.read_bytes() == b"prior final result"
        assert opposing.read_bytes() == b"prior opposing result"
