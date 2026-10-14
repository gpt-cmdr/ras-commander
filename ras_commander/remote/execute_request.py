"""Command-line entry point for portable steady HEC-RAS requests."""

from __future__ import annotations

import argparse
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Optional, Sequence

from .ExecutionContract import RasExecutionRequest
from .PortableExecution import execute_request as _execute_portable_request

_WINE_PREFIX_SEED = "RAS_COMMANDER_WINE_PREFIX_SEED"
_WINE_PYTHON = "RAS_COMMANDER_WINE_PYTHON"
_WINE_ARCH = "RAS_COMMANDER_WINE_ARCH"
_WINE_DELEGATED = "RAS_COMMANDER_WINE_DELEGATED"
_WINE_PREFIX_WINDOWS = "RAS_COMMANDER_WINE_PREFIX_WINDOWS"
_WINE_CPU_SHIM = "RAS_COMMANDER_WINE_CPU_SHIM"
_WINE_ACCEPT_TCU = "RAS_COMMANDER_WINE_ACCEPT_TCU"
_TCU_HELPER = r"C:\ras-commander-runtime\accept_tcu.py"
_WINDOWS_SAFE_PATH_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._()+-\\:"
)


def _is_linux() -> bool:
    """Return whether this interpreter is the Linux image entry point."""
    return sys.platform.startswith("linux")


def _is_absolute_windows_executable(value: str) -> bool:
    """Return whether *value* is a conservative drive-absolute executable path."""
    path = PureWindowsPath(value)
    return (
        path.is_absolute()
        and path.drive.endswith(":")
        and path.suffix.lower() == ".exe"
        and ".." not in path.parts
        and all(character in _WINDOWS_SAFE_PATH_CHARACTERS for character in value)
    )


def _required_tool(name: str) -> str:
    """Resolve one trusted image tool or fail before creating runtime state."""
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"Wine execution image is missing required tool: {name}")
    return executable


def _wine_environment(request: RasExecutionRequest) -> tuple[Path, str, str]:
    """Validate the explicit Wine image environment for a Windows RAS request."""
    seed_value = os.environ.get(_WINE_PREFIX_SEED, "")
    python_value = os.environ.get(_WINE_PYTHON, "")
    if not seed_value or not python_value:
        raise RuntimeError(
            "Windows ras_executable on Linux requires trusted image variables "
            f"{_WINE_PREFIX_SEED} and {_WINE_PYTHON}"
        )
    seed = Path(seed_value)
    if not seed.is_absolute() or seed.is_symlink() or not seed.is_dir():
        raise ValueError(f"{_WINE_PREFIX_SEED} must be an absolute regular directory")
    if not _is_absolute_windows_executable(python_value):
        raise ValueError(
            f"{_WINE_PYTHON} must be a conservative absolute Windows .exe path"
        )
    if not _is_absolute_windows_executable(request.ras_executable):
        raise ValueError("Wine execution requires an absolute Windows ras_executable")
    arch = os.environ.get(_WINE_ARCH, "win64")
    if arch not in {"win32", "win64"}:
        raise ValueError(f"{_WINE_ARCH} must be win32 or win64")
    return seed.resolve(), python_value, arch


def _wine_cpu_shim() -> Optional[Path]:
    """Return the image's CPU-numbering shim, or ``None`` when it is disabled.

    In a Slurm/cgroup CPU set that does not start at CPU 0, Wine reports the
    raw host CPU id as the Windows processor number. .NET code in HEC-RAS
    preprocessing indexes per-processor state with it and fails intermittently
    with 0xC0000005. The shim remaps ``sched_getcpu`` to the index within the
    process affinity mask. Images set ``RAS_COMMANDER_WINE_CPU_SHIM`` to the
    shim's absolute path; an unset, empty, or ``0`` value disables it.
    """
    setting = os.environ.get(_WINE_CPU_SHIM, "").strip()
    if setting in {"", "0"}:
        return None
    shim = Path(setting)
    if not shim.is_absolute() or shim.is_symlink() or not shim.is_file():
        raise ValueError(f"{_WINE_CPU_SHIM} must name an absolute regular file")
    if any(character in setting for character in " :"):
        raise ValueError(f"{_WINE_CPU_SHIM} cannot contain spaces or colons")
    return shim


def _free_x_display() -> int:
    """Return an X display number not in use on this node.

    Contained steps have private ``/tmp`` directories, so ``xvfb-run -a``
    cannot see other steps' lock files, while Linux Xvfb also listens on an
    abstract socket shared through the host network namespace. Probe that
    socket name for a free display instead of relying on ``/tmp`` locks.
    """
    candidates = random.sample(range(100, 32000), 200)
    for display in candidates:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.bind(f"\0/tmp/.X11-unix/X{display}")
        except OSError:
            continue
        finally:
            probe.close()
        return display
    raise RuntimeError("No free X display number found for Xvfb")


def _xvfb_command(xvfb_run: str) -> list[str]:
    """Return an ``xvfb-run`` prefix bound to a free, node-unique display."""
    return [xvfb_run, "-n", str(_free_x_display())]


def _is_legacy_tcu_release(ras_executable: str) -> bool:
    """Return whether the release keeps per-machine TCU state (HEC-RAS 6.0 and earlier).

    Their acceptance recorded at image build time does not carry to another
    Wine host, so it must be given in the task's own prefix.
    """
    import re as _re

    match = _re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", PureWindowsPath(ras_executable).parent.name)
    return bool(match) and (int(match.group(1)), int(match.group(2))) <= (6, 0)


def _accept_legacy_tcu(tools, environment, windows_python, ras_executable, task_root, windows_path):
    """Accept the HEC-RAS TCU through its dialog in this task's private prefix.

    Only for HEC-RAS 6.0 and earlier, and only when the operator opts in with
    ``RAS_COMMANDER_WINE_ACCEPT_TCU=1`` (the operator's acceptance of HEC's
    terms for the runs it starts). Uses the image's ``accept_tcu.py`` and
    requires a verified relaunch; sets ``RAS_COMMANDER_TCU_PROBE`` to the
    task-scoped record so ``RasTcu`` reports the acceptance.
    """
    if os.environ.get(_WINE_ACCEPT_TCU) != "1":
        raise RuntimeError(
            "HEC-RAS 6.0 and earlier record TCU acceptance per machine, so an image's "
            "build-time acceptance does not apply here and HEC-RAS would wait on its "
            "Terms and Conditions dialog. Set RAS_COMMANDER_WINE_ACCEPT_TCU=1 to accept "
            "the terms (https://www.hec.usace.army.mil/software/hec-ras/) in each task."
        )
    probe = task_root / "tcu-probe.json"
    completed = subprocess.run(
        [*_xvfb_command(tools["xvfb-run"]), tools["wine"], windows_python, _TCU_HELPER,
         ras_executable, windows_path(probe), "task"],
        check=False, shell=False, env=environment, timeout=900,
    )
    try:
        import json as _json

        record = _json.loads(probe.read_text(encoding="utf-8"))
        verified = record["executables"][0]["verified"] is True
    except (OSError, ValueError, KeyError, IndexError):
        verified = False
    if completed.returncode != 0 or not verified:
        raise RuntimeError("HEC-RAS TCU acceptance in the task prefix was not verified")
    environment["RAS_COMMANDER_TCU_PROBE"] = windows_path(probe)
    print("ras-commander Wine runtime: TCU accepted in the task prefix", flush=True)


def _disable_openmp_affinity(environment: dict) -> None:
    """Disable Intel OpenMP thread pinning for Windows HEC-RAS under Wine.

    HEC-RAS 7.0 enables CPU affinity; under Wine in a Slurm CPU set its
    ``GetNumaNodeProcessorMaskEx()`` query fails and the unsteady engine aborts
    with ``OMP: Error #179``. The allocation already bounds the CPUs, so the
    pinning adds nothing. A caller-provided ``KMP_AFFINITY`` is kept.
    """
    environment.setdefault("KMP_AFFINITY", "disabled")


def _disable_wine_debugger(overrides: str) -> str:
    """Return DLL overrides that stop a crash from waiting in winedbg."""
    entries = [entry for entry in overrides.split(";") if entry.strip()]
    for entry in entries:
        names = entry.split("=", 1)[0].split(",")
        if any(name.strip().lower() in {"winedbg", "winedbg.exe"} for name in names):
            return ";".join(entries)
    return ";".join(entries + ["winedbg.exe=d"])


def _shutdown_wineserver(wineserver: str, environment: dict[str, str]) -> None:
    """Wait for the task-private server, terminating it if it does not exit."""
    try:
        completed = subprocess.run(
            [wineserver, "-w"],
            check=False,
            shell=False,
            env=environment,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(
            [wineserver, "-k"],
            check=True,
            shell=False,
            env=environment,
            timeout=30,
        )
        subprocess.run(
            [wineserver, "-w"],
            check=True,
            shell=False,
            env=environment,
            timeout=30,
        )
        return
    if completed.returncode != 0:
        raise RuntimeError(f"Task-private wineserver exited {completed.returncode}")


def _execute_with_wine(
    request_path: Path, request: RasExecutionRequest, output: Path
) -> int:
    """Execute one request through Windows Python in an isolated Wine prefix."""
    if os.environ.get(_WINE_DELEGATED):
        raise RuntimeError("Refusing recursive Wine request delegation")
    seed, windows_python, arch = _wine_environment(request)
    cpu_shim = _wine_cpu_shim()
    tools = {
        name: _required_tool(name)
        for name in ("wine", "winepath", "wineserver", "xvfb-run")
    }
    if output.exists() and any(output.iterdir()):
        raise ValueError("Wine request output directory must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    # Runtime support files are temporary, not execution artifacts. Fleet
    # callers bind TMPDIR to node-local scratch rather than a shared output.
    runtime_parent = Path(tempfile.gettempdir())
    if (
        not runtime_parent.is_absolute()
        or runtime_parent.is_symlink()
        or not runtime_parent.is_dir()
        or runtime_parent.resolve().is_relative_to(request_path.parent.resolve())
        or runtime_parent.resolve().is_relative_to(seed)
    ):
        raise ValueError(
            "Wine temporary runtime parent must be an absolute regular directory outside the request bundle and seed"
        )
    task_root = Path(
        tempfile.mkdtemp(
            prefix=f".ras-wine-runtime-{request.execution_id}-", dir=runtime_parent
        )
    )
    prefix = task_root / "prefix"
    if prefix.exists() or prefix.is_symlink():
        raise RuntimeError(f"Private Wine prefix destination already exists: {prefix}")
    environment = dict(os.environ)
    environment.update(
        {
            "WINEPREFIX": str(prefix),
            "WINEARCH": arch,
            "WINEDEBUG": "-all",
            _WINE_DELEGATED: "1",
        }
    )
    environment["WINEDLLOVERRIDES"] = _disable_wine_debugger(
        environment.get("WINEDLLOVERRIDES", "")
    )
    _disable_openmp_affinity(environment)
    if cpu_shim is not None:
        preload = environment.get("LD_PRELOAD", "").strip()
        if str(cpu_shim) not in preload.replace(":", " ").split():
            environment["LD_PRELOAD"] = f"{cpu_shim} {preload}".strip()
    wine_invoked = False
    try:
        print("ras-commander Wine runtime: copying task-private prefix", flush=True)
        shutil.copytree(seed, prefix, symlinks=True)
        print("ras-commander Wine runtime: task-private prefix ready", flush=True)
        if cpu_shim is not None:
            print(f"ras-commander Wine runtime: CPU shim {cpu_shim}", flush=True)
        wine_invoked = True
        # The image seed normally maps Z: to the POSIX root. Verify the copied
        # mapping before using it, avoiding a separate cold Wine startup merely
        # to translate a path. Other drive mappings keep winepath behavior.
        root_drive = prefix / "dosdevices" / "z:"
        root_mapping_verified = (
            os.name == "posix"
            and root_drive.is_symlink()
            and root_drive.resolve() == Path("/")
        )

        def windows_path(path: Path) -> str:
            if (
                root_mapping_verified
                and path.is_absolute()
                and ".." not in path.parts
                and all(not any(c in part for c in "\\:") for part in path.parts)
            ):
                converted_path = str(
                    PureWindowsPath("Z:/") / path.relative_to("/").as_posix()
                )
                if PureWindowsPath(converted_path).drive.casefold() != "z:":
                    raise ValueError("verified root mapping changed runtime drive")
                return converted_path
            converted = subprocess.run(
                [tools["winepath"], "-w", str(path)],
                capture_output=True,
                check=False,
                shell=False,
                text=True,
                env=environment,
                timeout=30,
            )
            converted_path = converted.stdout.strip()
            if converted.returncode != 0 or not converted_path:
                detail = converted.stderr.strip()
                raise RuntimeError(
                    f"winepath failed to convert path: {detail or converted.returncode}"
                )
            return converted_path

        windows_request = windows_path(request_path)
        request_windows_path = PureWindowsPath(windows_request)
        if (
            not request_windows_path.is_absolute()
            or request_windows_path.suffix.lower() != ".json"
            or ".." in request_windows_path.parts
        ):
            raise ValueError("winepath returned an unsafe request path")
        prefix_windows_path = PureWindowsPath(windows_path(prefix))
        if (
            not prefix_windows_path.is_absolute()
            or ".." in prefix_windows_path.parts
            or prefix_windows_path.name != prefix.name
            or prefix_windows_path.parent.name != task_root.name
        ):
            raise ValueError("winepath returned an unsafe private prefix path")
        environment[_WINE_PREFIX_WINDOWS] = str(prefix_windows_path)
        if _is_legacy_tcu_release(request.ras_executable):
            _accept_legacy_tcu(tools, environment, windows_python, request.ras_executable,
                               task_root, windows_path)
        print("ras-commander Wine runtime: starting delegated execution", flush=True)
        completed = subprocess.run(
            [
                *_xvfb_command(tools["xvfb-run"]),
                tools["wine"],
                windows_python,
                "-m",
                "ras_commander.remote.execute_request",
                "execute-request",
                str(request_windows_path),
            ],
            check=False,
            shell=False,
            env=environment,
            timeout=request.execution_timeout_seconds + 300,
        )
        return completed.returncode
    finally:
        try:
            if wine_invoked and prefix.is_dir():
                _shutdown_wineserver(tools["wineserver"], environment)
        finally:
            shutil.rmtree(task_root)


def build_parser() -> argparse.ArgumentParser:
    """Return the ``execute-request`` command-line parser."""
    parser = argparse.ArgumentParser(prog="ras-commander")
    subparsers = parser.add_subparsers(dest="command", required=True)
    execute = subparsers.add_parser(
        "execute-request",
        help="execute one immutable one-core HEC-RAS plan request (steady or unsteady)",
    )
    execute.add_argument("request", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the portable request CLI and return a process exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "execute-request":
        request_path = args.request.resolve()
        try:
            request = RasExecutionRequest.read(request_path)
            _, output = request.resolve_paths(request_path)
            if _is_linux() and _is_absolute_windows_executable(request.ras_executable):
                return _execute_with_wine(request_path, request, output)
            receipt = _execute_portable_request(request_path)
        except Exception as exc:
            print(
                f"ras-commander execute-request: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 2
        print(output / "execution_receipt.json")
        return 0 if receipt.success else 1
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
