import json
import os
import subprocess
from pathlib import Path

import pytest

import ras_commander.remote.execute_request as execute_request_cli
from ras_commander.remote import PortableExecution
from ras_commander.remote.ExecutionContract import RasExecutionRequest

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


# The Linux-host Wine delegate builds POSIX paths into LD_PRELOAD and the prefix
# (a Windows tmp_path contains ':') and binds abstract AF_UNIX X11 sockets.
linux_wine_host = pytest.mark.skipif(
    os.name == "nt", reason="Linux-host Wine delegate: POSIX paths and AF_UNIX X11 sockets"
)


@linux_wine_host
def test_linux_windows_request_uses_private_wine_prefix(tmp_path, monkeypatch):
    request_path = _request(tmp_path)
    request_bytes = request_path.read_bytes()
    source_path = request_path.parent / "input/sample.prj"
    source_bytes = source_path.read_bytes()
    seed = tmp_path / "seed-prefix"
    seed.mkdir()
    (seed / "system.reg").write_text("seed")
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    monkeypatch.setenv("RAS_COMMANDER_WINE_ARCH", "win64")
    runtime_parent = tmp_path / "runtime-temp"
    runtime_parent.mkdir()
    monkeypatch.setattr(
        execute_request_cli.tempfile, "gettempdir", lambda: str(runtime_parent)
    )
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
            converted = (
                r"Z:\job\request.json"
                if command[-1].endswith("request.json")
                else rf"Z:\runtime-temp\{Path(command[-1]).parent.name}\prefix"
            )
            return subprocess.CompletedProcess(
                command, 0, stdout=converted + "\n", stderr=""
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
    assert copy_calls[0][1].parent.parent == runtime_parent
    assert commands[2][:2] == ["/usr/bin/xvfb-run", "-n"]
    assert 100 <= int(commands[2][2]) < 32000
    assert commands[2][3:] == [
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
    assert "runtime-temp" in child_environment["RAS_COMMANDER_WINE_PREFIX_WINDOWS"]
    output = RasExecutionRequest.read(request_path).resolve_paths(request_path)[1]
    assert not any(output.iterdir())
    assert request_path.read_bytes() == request_bytes
    assert source_path.read_bytes() == source_bytes


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


@linux_wine_host
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
            converted = (
                r"Z:\job\request.json"
                if command[-1].endswith("request.json")
                else rf"Z:\runtime-temp\{Path(command[-1]).parent.name}\prefix"
            )
            return subprocess.CompletedProcess(
                command, 0, stdout=converted + "\n", stderr=""
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


@pytest.mark.parametrize(
    "invalid_parent", ["relative", "missing", "file", "bundle", "seed"]
)
def test_wine_runtime_rejects_unsafe_temporary_parent(
    tmp_path, monkeypatch, invalid_parent
):
    request_path = _request(tmp_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(
        execute_request_cli.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    bad = {
        "relative": Path("relative-temp"),
        "missing": tmp_path / "missing",
        "file": tmp_path / "file",
        "bundle": request_path.parent,
        "seed": seed,
    }[invalid_parent]
    if invalid_parent == "file":
        bad.write_text("not a directory")
    monkeypatch.setattr(execute_request_cli.tempfile, "gettempdir", lambda: str(bad))
    monkeypatch.setattr(
        execute_request_cli.shutil,
        "copytree",
        lambda *args, **kwargs: pytest.fail("prefix copy must not start"),
    )
    assert execute_request_cli.main(["execute-request", str(request_path)]) == 2


def test_wine_runtime_copy_failure_cleans_only_owned_temporary_root(
    tmp_path, monkeypatch
):
    request_path = _request(tmp_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    parent = tmp_path / "runtime-temp"
    parent.mkdir()
    foreign = parent / "foreign.txt"
    foreign.write_text("retain")
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(
        execute_request_cli.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(execute_request_cli.tempfile, "gettempdir", lambda: str(parent))
    destinations = []

    def copy_failure(source, destination, **kwargs):
        destinations.append(Path(destination))
        assert Path(destination).parent.parent == parent
        Path(destination).mkdir()
        (Path(destination) / "partial.txt").write_text("partial")
        raise OSError("synthetic seed copy failure")

    monkeypatch.setattr(execute_request_cli.shutil, "copytree", copy_failure)
    monkeypatch.setattr(
        execute_request_cli.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Wine must not start"),
    )
    assert execute_request_cli.main(["execute-request", str(request_path)]) == 2
    assert list(parent.iterdir()) == [foreign]
    assert foreign.read_text() == "retain"
    assert len(destinations) == 1 and destinations[0].parent.parent == parent


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
    assert (
        execute_request_cli._execute_portable_request
        is PortableExecution.execute_request
    )
    assert "execute_request" not in remote_package.__all__


@pytest.mark.skipif(os.name != "posix", reason="Wine drive mapping is a POSIX contract")
@pytest.mark.parametrize(
    "root_mapping,folder",
    [
        (True, "with spaces"),
        (False, "with spaces"),
        (True, "C:\\other"),
        (True, "back\\slash"),
    ],
)
def test_verified_root_drive_avoids_cold_winepath_startup(
    tmp_path, monkeypatch, root_mapping, folder
):
    request_path = _request(tmp_path / folder)
    fast_path = root_mapping and not any(c in folder for c in "\\:")
    seed = tmp_path / "seed"
    (seed / "dosdevices").mkdir(parents=True)
    mapping = Path("/") if root_mapping else tmp_path
    (seed / "dosdevices" / "z:").symlink_to(mapping, target_is_directory=True)
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(
        execute_request_cli.shutil, "which", lambda name: "/usr/bin/" + name
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0].endswith("winepath"):
            assert not fast_path or not command[-1].endswith("request.json")
            converted = (
                r"Z:\job\request.json"
                if command[-1].endswith("request.json")
                else rf"Z:\runtime-temp\{Path(command[-1]).parent.name}\prefix"
            )
            return subprocess.CompletedProcess(command, 0, stdout=converted, stderr="")
        if command[0].endswith("xvfb-run") and fast_path:
            from pathlib import PureWindowsPath

            expected = str(
                PureWindowsPath("Z:/") / request_path.relative_to("/").as_posix()
            )
            assert command[-1] == expected
            prefix = Path(kwargs["env"]["WINEPREFIX"])
            assert kwargs["env"]["RAS_COMMANDER_WINE_PREFIX_WINDOWS"] == str(
                PureWindowsPath("Z:/") / prefix.relative_to("/").as_posix()
            )
            assert not prefix.is_relative_to(request_path.parent)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(execute_request_cli.subprocess, "run", run)
    before = request_path.read_bytes()
    assert execute_request_cli.main(["execute-request", str(request_path)]) == 0
    expected_conversions = 0 if fast_path else 1 if root_mapping else 2
    assert sum(c[0].endswith("winepath") for c in calls) == expected_conversions
    assert request_path.read_bytes() == before
    assert (seed / "dosdevices" / "z:").resolve() == mapping


@pytest.mark.parametrize(
    "bad_prefix", ["relative/prefix", r"Z:\wrong-task\prefix", r"Z:\runtime\other"]
)
def test_wine_runtime_rejects_wrong_fallback_prefix(tmp_path, monkeypatch, bad_prefix):
    request_path = _request(tmp_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    parent = tmp_path / "runtime-temp"
    parent.mkdir()
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(
        execute_request_cli.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(execute_request_cli.tempfile, "gettempdir", lambda: str(parent))

    def run(command, **kwargs):
        if command[0].endswith("winepath"):
            converted = (
                r"Z:\job\request.json"
                if command[-1].endswith("request.json")
                else bad_prefix
            )
            return subprocess.CompletedProcess(command, 0, stdout=converted, stderr="")
        assert command[0].endswith("wineserver"), "delegated execution must not start"
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(execute_request_cli.subprocess, "run", run)
    assert execute_request_cli.main(["execute-request", str(request_path)]) == 2
    assert not any(parent.iterdir())


@pytest.mark.skipif(
    os.name != "posix", reason="temporary-parent symlink contract is POSIX"
)
def test_wine_runtime_rejects_symlink_temporary_parent(tmp_path, monkeypatch):
    request_path = _request(tmp_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    parent = tmp_path / "runtime-temp"
    parent.mkdir()
    link = tmp_path / "temp-link"
    link.symlink_to(parent, target_is_directory=True)
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(
        execute_request_cli.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(execute_request_cli.tempfile, "gettempdir", lambda: str(link))
    monkeypatch.setattr(
        execute_request_cli.shutil,
        "copytree",
        lambda *args, **kwargs: pytest.fail("prefix copy must not start"),
    )
    assert execute_request_cli.main(["execute-request", str(request_path)]) == 2
    assert not any(parent.iterdir())


def _wine_child_environment(tmp_path, monkeypatch):
    """Run one mocked Wine delegation and return the delegated environment."""
    request_path = _request(tmp_path)
    seed = tmp_path / "seed-prefix"
    seed.mkdir()
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    runtime_parent = tmp_path / "runtime-temp"
    runtime_parent.mkdir()
    monkeypatch.setattr(
        execute_request_cli.tempfile, "gettempdir", lambda: str(runtime_parent)
    )
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(
        execute_request_cli.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    child_environment = {}

    def run(command, **kwargs):
        if command[0].endswith("winepath"):
            converted = (
                r"Z:\job\request.json"
                if command[-1].endswith("request.json")
                else rf"Z:\runtime-temp\{Path(command[-1]).parent.name}\prefix"
            )
            return subprocess.CompletedProcess(command, 0, stdout=converted, stderr="")
        if command[0].endswith("xvfb-run"):
            child_environment.update(kwargs["env"])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(execute_request_cli.subprocess, "run", run)
    result = execute_request_cli.main(["execute-request", str(request_path)])
    return result, child_environment


@linux_wine_host
def test_wine_cpu_shim_is_preloaded_for_delegated_wine(tmp_path, monkeypatch):
    shim = tmp_path / "cpushim.so"
    shim.write_bytes(b"\x7fELF")
    monkeypatch.setenv("RAS_COMMANDER_WINE_CPU_SHIM", str(shim))
    monkeypatch.setenv("LD_PRELOAD", "/opt/other.so")

    result, environment = _wine_child_environment(tmp_path, monkeypatch)

    assert result == 0
    assert environment["LD_PRELOAD"] == f"{shim} /opt/other.so"
    assert environment["WINEDLLOVERRIDES"] == "winedbg.exe=d"


@linux_wine_host
@pytest.mark.parametrize("setting", ["", "0"])
def test_wine_cpu_shim_can_be_disabled(tmp_path, monkeypatch, setting):
    monkeypatch.setenv("RAS_COMMANDER_WINE_CPU_SHIM", setting)
    monkeypatch.delenv("LD_PRELOAD", raising=False)

    result, environment = _wine_child_environment(tmp_path, monkeypatch)

    assert result == 0
    assert "LD_PRELOAD" not in environment


def test_missing_wine_cpu_shim_fails_before_runtime_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RAS_COMMANDER_WINE_CPU_SHIM", str(tmp_path / "absent.so"))

    result, environment = _wine_child_environment(tmp_path, monkeypatch)

    assert result == 2
    assert environment == {}
    assert "RAS_COMMANDER_WINE_CPU_SHIM" in capsys.readouterr().err
    assert not any((tmp_path / "runtime-temp").iterdir())


@linux_wine_host
def test_existing_wine_debugger_override_is_kept(tmp_path, monkeypatch):
    monkeypatch.delenv("RAS_COMMANDER_WINE_CPU_SHIM", raising=False)
    monkeypatch.setenv("WINEDLLOVERRIDES", "mscoree=n;winedbg=b")

    result, environment = _wine_child_environment(tmp_path, monkeypatch)

    assert result == 0
    assert environment["WINEDLLOVERRIDES"] == "mscoree=n;winedbg=b"


@linux_wine_host
def test_free_x_display_skips_displays_bound_by_other_steps(monkeypatch):
    import socket

    taken = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    taken.bind("\0/tmp/.X11-unix/X31999")
    try:
        monkeypatch.setattr(
            execute_request_cli.random, "sample", lambda population, k: [31999, 31998]
        )
        assert execute_request_cli._free_x_display() == 31998
    finally:
        taken.close()


@linux_wine_host
def test_wine_disables_openmp_affinity_unless_caller_sets_it(tmp_path, monkeypatch):
    monkeypatch.delenv("RAS_COMMANDER_WINE_CPU_SHIM", raising=False)
    monkeypatch.delenv("KMP_AFFINITY", raising=False)
    result, environment = _wine_child_environment(tmp_path, monkeypatch)
    assert result == 0 and environment["KMP_AFFINITY"] == "disabled"


@linux_wine_host
def test_wine_keeps_a_caller_openmp_affinity(tmp_path, monkeypatch):
    monkeypatch.delenv("RAS_COMMANDER_WINE_CPU_SHIM", raising=False)
    monkeypatch.setenv("KMP_AFFINITY", "compact")
    result, environment = _wine_child_environment(tmp_path, monkeypatch)
    assert result == 0 and environment["KMP_AFFINITY"] == "compact"


LEGACY_RAS = r"C:\Program Files (x86)\HEC\HEC-RAS\6.0\Ras.exe"


def _legacy_wine_run(tmp_path, monkeypatch, *, verified=True):
    request_path = _request(tmp_path, ras_executable=LEGACY_RAS)
    seed = tmp_path / "seed-prefix"
    seed.mkdir()
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", WINDOWS_PYTHON)
    monkeypatch.delenv("RAS_COMMANDER_WINE_CPU_SHIM", raising=False)
    runtime = tmp_path / "runtime-temp"
    runtime.mkdir()
    monkeypatch.setattr(execute_request_cli.tempfile, "gettempdir", lambda: str(runtime))
    monkeypatch.setattr(execute_request_cli, "_is_linux", lambda: True)
    monkeypatch.setattr(execute_request_cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def run(command, **kwargs):
        calls.append((command, dict(kwargs.get("env", {}))))
        if command[0].endswith("winepath"):
            converted = (r"Z:\job\request.json" if command[-1].endswith("request.json")
                         else rf"Z:\runtime-temp\{Path(command[-1]).parent.name}\{Path(command[-1]).name}")
            return subprocess.CompletedProcess(command, 0, stdout=converted, stderr="")
        if any(part.endswith("accept_tcu.py") for part in command):
            probe = next(runtime.iterdir()) / "tcu-probe.json"
            probe.write_text(json.dumps({"executables": [{"verified": verified}]}))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(execute_request_cli.subprocess, "run", run)
    return execute_request_cli.main(["execute-request", str(request_path)]), calls


def test_legacy_release_without_opt_in_fails_before_wine(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("RAS_COMMANDER_WINE_ACCEPT_TCU", raising=False)
    result, calls = _legacy_wine_run(tmp_path, monkeypatch)
    assert result == 2
    assert "RAS_COMMANDER_WINE_ACCEPT_TCU=1" in capsys.readouterr().err
    assert not any(c[0][0].endswith("xvfb-run") for c in calls)


@linux_wine_host
def test_legacy_release_accepts_in_task_prefix_before_compute(tmp_path, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_WINE_ACCEPT_TCU", "1")
    result, calls = _legacy_wine_run(tmp_path, monkeypatch)
    wine_calls = [c for c in calls if c[0][0].endswith("xvfb-run")]
    assert result == 0 and len(wine_calls) == 2
    accept, compute = wine_calls
    assert any(part.endswith("accept_tcu.py") for part in accept[0]) and accept[0][-1] == "task"
    assert "execute-request" in compute[0]
    assert compute[1]["RAS_COMMANDER_TCU_PROBE"].endswith("tcu-probe.json")


@linux_wine_host
def test_legacy_release_refuses_unverified_task_acceptance(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RAS_COMMANDER_WINE_ACCEPT_TCU", "1")
    result, calls = _legacy_wine_run(tmp_path, monkeypatch, verified=False)
    assert result == 2 and "not verified" in capsys.readouterr().err
    assert not any("execute-request" in c[0] for c in calls if c[0][0].endswith("xvfb-run"))


@linux_wine_host
def test_release_61_and_later_never_runs_task_acceptance(tmp_path, monkeypatch):
    monkeypatch.delenv("RAS_COMMANDER_WINE_ACCEPT_TCU", raising=False)
    result, environment = _wine_child_environment(tmp_path, monkeypatch)
    assert result == 0 and "RAS_COMMANDER_TCU_PROBE" not in environment
