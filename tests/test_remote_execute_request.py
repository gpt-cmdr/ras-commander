from pathlib import Path
import subprocess

from ras_commander.remote.ExecutionContract import RasExecutionRequest
from ras_commander.remote import PortableExecution
import ras_commander.remote.execute_request as execute_request_cli


OCI = "registry.example/hecras/steady@sha256:" + "a" * 64
WINDOWS_RAS = r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe"
WINDOWS_PYTHON = r"C:\Python311\python.exe"


def _request(tmp_path: Path, *, ras_executable: str = WINDOWS_RAS) -> Path:
    bundle = tmp_path / "bundle"
    source = bundle / "input" / "sample.prj"
    source.parent.mkdir(parents=True)
    source.write_text("Proj Title=sample\nCurrent Plan=p01\nPlan File=p01\n")
    request = RasExecutionRequest.create(
        execution_id="sample-001",
        request_directory=bundle,
        source_project_path="input/sample.prj",
        plan_number="1",
        output_directory="output/sample-001",
        ras_executable=ras_executable,
        container_identity=OCI,
        timeout_seconds=60,
    )
    return request.write(bundle / "request.json")


def test_linux_windows_request_uses_private_wine_prefix(tmp_path, monkeypatch):
    request_path = _request(tmp_path)
    seed = tmp_path / "seed-prefix"
    seed.mkdir()
    (seed / "system.reg").write_text("seed")
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    monkeypatch.setenv("RAS_COMMANDER_WINE_ARCH", "win64")
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(
        execute_request_cli.shutil, "which", lambda name: f"/usr/bin/{name}"
    )

    copy_calls = []
    commands = []
    child_environment = {}
    original_copytree = execute_request_cli.shutil.copytree

    def copytree(source, destination, *, symlinks=False):
        copy_calls.append((Path(source), Path(destination), symlinks))
        return original_copytree(source, destination, symlinks=symlinks)

    def run(command, **kwargs):
        commands.append(command)
        if command[0].endswith("winepath"):
            assert kwargs["env"]["WINEPREFIX"].endswith("prefix")
            return subprocess.CompletedProcess(
                command, 0, stdout=r"Z:\job\request.json" + "\n", stderr=""
            )
        if command[0].endswith("xvfb-run"):
            child_environment.update(kwargs["env"])
            return subprocess.CompletedProcess(command, 0)
        assert command == ["/usr/bin/wineserver", "-w"]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(execute_request_cli.shutil, "copytree", copytree)
    monkeypatch.setattr(execute_request_cli.subprocess, "run", run)

    result = execute_request_cli.main(["execute-request", str(request_path)])

    assert result == 0
    assert copy_calls[0][0] == seed.resolve()
    assert copy_calls[0][2] is True
    assert not copy_calls[0][1].parent.exists()
    assert copy_calls[0][1].parent.parent == request_path.parent / "output" / "sample-001"
    assert commands[1] == [
        "/usr/bin/xvfb-run",
        "-a",
        "/usr/bin/wine",
        WINDOWS_PYTHON,
        "-m",
        "ras_commander.remote.execute_request",
        "execute-request",
        r"Z:\job\request.json",
    ]
    assert child_environment["WINEARCH"] == "win64"
    assert child_environment["WINEDEBUG"] == "-all"
    assert child_environment["RAS_COMMANDER_WINE_DELEGATED"] == "1"
    assert child_environment["RAS_COMMANDER_WINE_PREFIX_WINDOWS"].endswith(
        rf"{copy_calls[0][1].parent.name}\prefix"
    )


def test_linux_windows_request_fails_closed_without_image_environment(
    tmp_path, monkeypatch, capsys
):
    request_path = _request(tmp_path)
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.delenv("RAS_COMMANDER_WINE_PREFIX_SEED", raising=False)
    monkeypatch.delenv("RAS_COMMANDER_WINE_PYTHON", raising=False)

    result = execute_request_cli.main(["execute-request", str(request_path)])

    assert result == 2
    assert "requires trusted image variables" in capsys.readouterr().err


def test_linux_wine_delegate_timeout_cleans_prefix_and_wineserver(
    tmp_path, monkeypatch, capsys
):
    request_path = _request(tmp_path)
    seed = tmp_path / "seed-prefix"
    seed.mkdir()
    (seed / "system.reg").write_text("seed")
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(
        execute_request_cli.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[0].endswith("winepath"):
            return subprocess.CompletedProcess(
                command, 0, stdout=r"Z:\job\request.json" + "\n", stderr=""
            )
        if command[0].endswith("xvfb-run"):
            assert kwargs["timeout"] == 360
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(execute_request_cli.subprocess, "run", run)

    result = execute_request_cli.main(["execute-request", str(request_path)])

    output = RasExecutionRequest.read(request_path).resolve_paths(request_path)[1]
    assert result == 2
    assert output.is_dir() and not any(output.iterdir())
    assert commands[-1] == ["/usr/bin/wineserver", "-w"]
    assert "TimeoutExpired" in capsys.readouterr().err


def test_posix_request_keeps_native_execution_path(tmp_path, monkeypatch, capsys):
    request_path = _request(tmp_path, ras_executable="/opt/hecras/Ras.exe")
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(
        execute_request_cli,
        "_execute_with_wine",
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected Wine bridge")),
    )

    class Receipt:
        success = True

    monkeypatch.setattr(
        execute_request_cli, "_execute_portable_request", lambda path: Receipt()
    )

    result = execute_request_cli.main(["execute-request", str(request_path)])

    assert result == 0
    assert "execution_receipt.json" in capsys.readouterr().out


def test_recursive_linux_wine_delegation_is_rejected(tmp_path, monkeypatch):
    request_path = _request(tmp_path)
    request = RasExecutionRequest.read(request_path)
    monkeypatch.setenv("RAS_COMMANDER_WINE_DELEGATED", "1")

    try:
        execute_request_cli._execute_with_wine(
            request_path, request, request.resolve_paths(request_path)[1]
        )
    except RuntimeError as exc:
        assert "recursive" in str(exc)
    else:
        raise AssertionError("recursive delegation was accepted")


def test_portable_execute_function_is_reachable_beside_cli_submodule():
    import ras_commander.remote as remote_package

    assert callable(PortableExecution.execute_request)
    assert execute_request_cli._execute_portable_request is PortableExecution.execute_request
    assert "execute_request" not in remote_package.__all__
