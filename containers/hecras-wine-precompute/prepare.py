#!/usr/bin/env python3
"""Run HEC-RAS geometry preprocessing through ras-commander and Wine."""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

RUNTIME_SCHEMA = "ras-commander-runtime/v1"
JOB_SCHEMA = "ras-commander-job/v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ACCEPTED_SIGNALS = {"bco", "owned_process_artifacts"}
CPU_SHIM_VARIABLE = "RAS_COMMANDER_WINE_CPU_SHIM"
DEFAULT_CPU_SHIM = Path(__file__).with_name("cpushim.so")


class JobError(RuntimeError):
    """A job, mount, runtime profile, or HEC-RAS result is invalid."""


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def require_text(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise JobError("Runtime manifest field " + repr(key) + " must be nonempty text")
    return value.strip()


def require_sha256(value, field):
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value.lower()):
        raise JobError("Runtime manifest field " + repr(field) + " must be a SHA-256 digest")
    return value.lower()


def profile_path(root, value, field):
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise JobError("Runtime manifest field " + repr(field) + " must be a relative path")
    path = root.joinpath(*relative.parts).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise JobError("Runtime manifest field " + repr(field) + " escapes the profile") from exc
    return path


def windows_seed_path(prefix, value, field):
    windows_path = PureWindowsPath(value)
    if windows_path.drive.upper() != "C:" or not windows_path.is_absolute():
        raise JobError("Runtime manifest field " + repr(field) + " must be an absolute C: path")
    path = prefix.joinpath("drive_c", *windows_path.parts[1:]).resolve()
    try:
        path.relative_to(prefix.resolve())
    except ValueError as exc:
        raise JobError("Runtime manifest field " + repr(field) + " escapes the Wine prefix") from exc
    return path


def load_runtime(manifest_path, expected_version):
    path = Path(manifest_path).resolve(strict=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobError("Cannot read runtime manifest " + str(path) + ": " + str(exc)) from exc
    if not isinstance(data, dict) or data.get("schema") != RUNTIME_SCHEMA:
        raise JobError("Runtime manifest schema must be " + repr(RUNTIME_SCHEMA))
    if require_text(data, "kind") != "wine":
        raise JobError("The preparation image requires a Wine runtime profile")
    version = require_text(data, "hec_ras_version")
    if version != expected_version:
        raise JobError("Runtime HEC-RAS " + version + " does not match image " + expected_version)

    ras_commander = data.get("ras_commander")
    if not isinstance(ras_commander, dict):
        raise JobError("Runtime manifest requires a ras_commander object")
    commit = require_text(ras_commander, "commit").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise JobError("ras_commander.commit must be a full Git commit")
    wheel_sha = require_sha256(ras_commander.get("wheel_sha256"), "ras_commander.wheel_sha256")
    image_commit = os.environ.get("RAS_COMMANDER_PREPARE_RAS_COMMANDER_COMMIT", "").lower()
    image_wheel_sha = os.environ.get("RAS_COMMANDER_PREPARE_RAS_COMMANDER_WHEEL_SHA256", "").lower()
    if image_commit and commit != image_commit:
        raise JobError("Runtime ras-commander commit does not match the image")
    if image_wheel_sha and wheel_sha != image_wheel_sha:
        raise JobError("Runtime ras-commander wheel does not match the image")

    root = path.parent
    hashes = {}
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise JobError("Runtime manifest requires hashed artifacts")
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict):
            raise JobError("Runtime artifact " + str(index) + " must be an object")
        artifact = profile_path(root, require_text(item, "path"), "artifacts.path")
        expected_sha = require_sha256(item.get("sha256"), "artifacts.sha256")
        if not artifact.is_file() or sha256_file(artifact) != expected_sha:
            raise JobError("Runtime artifact failed verification: " + str(artifact))
        hashes[artifact] = expected_sha

    wine = data.get("wine")
    if not isinstance(wine, dict):
        raise JobError("Runtime manifest requires a wine object")
    prefix = profile_path(root, require_text(wine, "prefix_seed"), "wine.prefix_seed")
    if not prefix.is_dir():
        raise JobError("Wine prefix seed does not exist: " + str(prefix))
    selected = {}
    for key in ("windows_python", "ras_executable", "ras_commander_wheel"):
        value = require_text(wine, key)
        seeded = windows_seed_path(prefix, value, "wine." + key)
        if not seeded.is_file() or seeded not in hashes:
            raise JobError("Selected runtime file is not hash-declared: " + str(seeded))
        selected[key] = value
    retained_wheel = windows_seed_path(prefix, selected["ras_commander_wheel"], "wine.ras_commander_wheel")
    if hashes[retained_wheel] != wheel_sha:
        raise JobError("Selected ras-commander wheel has the wrong hash")

    return {
        "identity": {
            "schema": RUNTIME_SCHEMA,
            "kind": "wine",
            "hec_ras_version": version,
            "manifest_sha256": sha256_file(path),
            "ras_commander_commit": commit,
            "ras_commander_wheel_sha256": wheel_sha,
        },
        "prefix": prefix,
        "hashes": hashes,
        "wheel_sha": wheel_sha,
        **selected,
    }


def normalize_plan(value):
    text = str(value).strip()
    if not text.isdigit() or len(text) > 2 or int(text) > 99:
        raise JobError("Invalid HEC-RAS plan number: " + repr(value))
    return text.zfill(2)


def normalize_run_id(value):
    if value is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        value = stamp + "-" + secrets.token_hex(4)
    if not RUN_ID_PATTERN.fullmatch(value):
        raise JobError("Run ID must use 1-64 letters, digits, periods, underscores, or hyphens")
    return value


def resolve_project(value, job_root):
    root = job_root.resolve(strict=True)
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    project = candidate.resolve(strict=True)
    try:
        project.relative_to(root)
    except ValueError as exc:
        raise JobError("Project must be inside " + str(root)) from exc
    if project.suffix.lower() != ".prj" or "Proj Title=" not in project.read_text(encoding="utf-8", errors="replace"):
        raise JobError("Project is not a readable HEC-RAS .prj file: " + str(project))
    return project


def geometry_number(project, plan):
    plan_path = project.with_suffix(".p" + plan)
    for line in plan_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Geom File="):
            digits = "".join(character for character in line.split("=", 1)[1] if character.isdigit())
            if digits:
                return digits
    raise JobError("Selected plan does not identify a geometry: " + str(plan_path))


def expected_outputs(project, plan, geometry):
    base = project.with_suffix("")
    return (
        Path(str(base) + ".p" + plan + ".tmp.hdf"),
        Path(str(base) + ".b" + plan),
        Path(str(base) + ".x" + geometry),
    )


def artifact_record(path, job_root):
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(job_root.resolve())
    except ValueError as exc:
        raise JobError("Preparation artifact is outside the job folder: " + str(resolved)) from exc
    size = resolved.stat().st_size
    if size <= 0:
        raise JobError("Preparation artifact is empty: " + str(resolved))
    return {"path": relative.as_posix(), "size_bytes": size, "sha256": sha256_file(resolved)}


def run_command(command, environment, timeout=None):
    return subprocess.run(
        list(command), capture_output=True, text=True, env=environment,
        timeout=timeout, check=False, shell=False
    )


def wine_path(value, environment, to_windows, runner):
    flag = "-w" if to_windows else "-u"
    result = runner(["winepath", flag, str(value)], environment, 60)
    if result.returncode or not result.stdout.strip():
        raise JobError("winepath could not translate " + str(value) + ": " + result.stderr.strip())
    return result.stdout.strip().splitlines()[-1]


def disable_wine_debugger(overrides):
    """Add ``winedbg.exe=d`` unless WINEDLLOVERRIDES already names winedbg.

    The prepared prefix starts ``winedbg --auto`` for an unhandled exception.
    Without a desktop it can block indefinitely and hold the crashed program
    until the preparation timeout. Disabled, the program ends at once and
    HEC-RAS records the failure.
    """
    entries = [entry for entry in (overrides or "").split(";") if entry.strip()]
    for entry in entries:
        names = entry.split("=", 1)[0].split(",")
        if any(name.strip().lower() in ("winedbg", "winedbg.exe") for name in names):
            return ";".join(entries)
    return ";".join(entries + ["winedbg.exe=d"])


def wine_environment(prefix, base=None):
    """Return the environment for Wine processes and its receipt record.

    ``RAS_COMMANDER_WINE_CPU_SHIM`` selects the CPU-numbering shim (default:
    the image's ``cpushim.so``); ``0`` or an empty value disables it. The
    portable executor (``ras_commander.remote.execute_request``) reads the
    same variable. The shim makes the processor number Wine reports agree
    with its processor count in a CPU set that does not start at 0 (see
    cpushim.c).
    """
    environment = dict(os.environ if base is None else base)
    environment["WINEPREFIX"] = str(prefix)
    environment.setdefault("DISPLAY", ":99")
    environment["WINEDLLOVERRIDES"] = disable_wine_debugger(environment.get("WINEDLLOVERRIDES"))
    # HEC-RAS 7.0's OpenMP runtime aborts under Wine (OMP: Error #179) unless
    # affinity is disabled; the portable executor applies the same default.
    environment.setdefault("KMP_AFFINITY", "disabled")

    shim_record = None
    setting = environment.get(CPU_SHIM_VARIABLE)
    if setting is None:
        shim = DEFAULT_CPU_SHIM if DEFAULT_CPU_SHIM.is_file() else None
    elif setting.strip() in ("", "0"):
        shim = None
    else:
        shim = Path(setting)
        if not shim.is_file():
            raise JobError(CPU_SHIM_VARIABLE + " does not name a file: " + setting)
    if shim is not None:
        shim = shim.resolve()
        preload = environment.get("LD_PRELOAD", "").strip()
        if str(shim) not in re.split(r"[\s:]+", preload):
            environment["LD_PRELOAD"] = (str(shim) + " " + preload).strip()
        shim_record = {"path": str(shim), "sha256": sha256_file(shim)}
    record = {
        "WINEDEBUG": environment.get("WINEDEBUG"),
        "WINEDLLOVERRIDES": environment["WINEDLLOVERRIDES"],
        "KMP_AFFINITY": environment["KMP_AFFINITY"],
        "cpu_shim": shim_record,
    }
    return environment, record


def load_worker_result(path):
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobError("Wine worker did not produce result evidence: " + str(exc)) from exc
    if not isinstance(result, dict):
        raise JobError("Wine worker result must be a JSON object")
    return result


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_prepare(project, plan, timeout, replace_generated, run_id, job_root,
                runtime_manifest, expected_version, runner=run_command, num_cores=2):
    if isinstance(num_cores, bool) or not isinstance(num_cores, int) or not 1 <= num_cores <= 8:
        raise JobError("num_cores must be an integer from 1 to 8")
    plan = normalize_plan(plan)
    run_id = normalize_run_id(run_id)
    root = Path(job_root).resolve(strict=True)
    project = resolve_project(project, root)
    geometry = geometry_number(project, plan)
    outputs = expected_outputs(project, plan, geometry)
    runtime = load_runtime(runtime_manifest, expected_version)
    scratch_root = Path(os.environ.get("RAS_COMMANDER_PREPARE_SCRATCH_ROOT", "/run/ras-job"))
    scratch = scratch_root / run_id
    prefix = scratch / "wineprefix"
    environment, wine_settings = wine_environment(prefix)

    receipt_dir = root / ".ras-commander" / "runs" / run_id
    if receipt_dir.exists():
        raise JobError("Run ID already exists: " + run_id)
    if any(path.exists() for path in outputs) and not replace_generated:
        raise JobError("Generated files already exist; use --replace-generated for a disposable job")
    receipt_dir.mkdir(parents=True)
    receipt_path = receipt_dir / "prepare.json"

    if scratch.exists():
        raise JobError("Private scratch already exists for run ID " + run_id)
    scratch.mkdir(parents=True)
    started = time.monotonic()
    base_receipt = {
        "schema": JOB_SCHEMA,
        "run_id": run_id,
        "command": "prepare",
        "project": project.relative_to(root).as_posix(),
        "plan": plan,
        "geometry": geometry,
        "runtime": runtime["identity"],
        "arguments": {
            "timeout_seconds": timeout,
            "replace_generated": replace_generated,
            "num_cores": num_cores,
        },
        "wine_environment": wine_settings,
        "started_at": utc_now(),
    }

    try:
        shutil.copytree(runtime["prefix"], prefix, symlinks=True)
        worker = Path(__file__).with_name("windows_worker.py").resolve(strict=True)
        result_file = scratch / "worker-result.json"
        command = [
            "xvfb-run", "-a", "-s", "-screen 0 1024x768x24", "wine",
            runtime["windows_python"],
            wine_path(worker, environment, True, runner),
            "--project", wine_path(project, environment, True, runner),
            "--plan", plan,
            "--ras-executable", runtime["ras_executable"],
            "--ras-commander-wheel", runtime["ras_commander_wheel"],
            "--expected-ras-commander-wheel-sha256", runtime["wheel_sha"],
            "--timeout", str(timeout),
            "--num-cores", str(num_cores),
            "--result", wine_path(result_file, environment, True, runner),
        ]
        if replace_generated:
            command.append("--replace-generated")
        completed = runner(command, environment, timeout + 120)
        (receipt_dir / "worker.stdout.log").write_text(completed.stdout or "", encoding="utf-8", newline="\n")
        (receipt_dir / "worker.stderr.log").write_text(completed.stderr or "", encoding="utf-8", newline="\n")
        result = load_worker_result(result_file)
        if completed.returncode or result.get("success") is not True:
            raise JobError(str(result.get("error") or "Wine preparation worker failed"))
        if result.get("plan") != plan or result.get("geometry") != geometry:
            raise JobError("Wine worker returned a different plan or geometry")
        worker_cores = result.get("num_cores")
        if isinstance(worker_cores, bool) or not isinstance(worker_cores, int) or worker_cores != num_cores:
            raise JobError("Wine worker returned a different core count")
        if result.get("timed_out") is not False:
            raise JobError("Wine preparation timed out")
        if result.get("full_result_copied") is not False:
            raise JobError("Wine preparation used a full-result-copy fallback")
        if result.get("signal_source") not in ACCEPTED_SIGNALS:
            raise JobError("Wine preparation has no accepted early-stop signal")
        if result.get("ras_commander_wheel_sha256") != runtime["wheel_sha"]:
            raise JobError("Wine worker imported a different ras-commander wheel")
        validation = result.get("hdf_validation")
        if not isinstance(validation, dict) or not all(
                validation.get(key) for key in ("geometry", "temporary_plan")):
            raise JobError("Wine worker did not validate the 2D geometry and hydraulic tables")

        paths = []
        for key, expected in zip(("tmp_hdf_path", "b_file_path", "x_file_path"), outputs):
            value = result.get(key)
            if not isinstance(value, str) or not value:
                raise JobError("Wine preparation omitted " + key)
            actual = Path(wine_path(value, environment, False, runner)).resolve()
            if actual != expected.resolve():
                raise JobError("Wine worker returned an unexpected " + key + ": " + str(actual))
            paths.append(actual)
        receipt = {
            **base_receipt,
            "status": "succeeded",
            "finished_at": utc_now(),
            "duration_seconds": time.monotonic() - started,
            "artifacts": [artifact_record(path, root) for path in paths],
            "result": {
                "signal_source": result.get("signal_source"),
                "full_result_copied": False,
                "timed_out": False,
                "worker_elapsed_seconds": result.get("elapsed_seconds"),
                "ras_commander_wheel_sha256": result.get("ras_commander_wheel_sha256"),
                "ras_commander_distribution_version": result.get("ras_commander_distribution_version"),
                "input_preparation": result.get("input_preparation"),
                "hdf_validation": validation,
            },
        }
        write_json(receipt_path, receipt)
        return True, receipt_path
    except Exception as exc:
        receipt = {
            **base_receipt,
            "status": "failed",
            "finished_at": utc_now(),
            "duration_seconds": time.monotonic() - started,
            "artifacts": [],
            "result": {
                "signal_source": None,
                "full_result_copied": False,
                "timed_out": isinstance(exc, subprocess.TimeoutExpired),
            },
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        write_json(receipt_path, receipt)
        return False, receipt_path


def positive_integer(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def build_parser():
    parser = argparse.ArgumentParser(prog="hecras-prepare")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="create compute-ready HEC-RAS artifacts")
    prepare.add_argument("--project", required=True)
    prepare.add_argument("--plan", default="01")
    prepare.add_argument("--timeout", type=positive_integer, default=300)
    prepare.add_argument("--num-cores", type=int, choices=range(1, 9), default=2,
                         help="HEC-RAS cores; match Docker --cpus (default: 2)")
    prepare.add_argument("--run-id")
    prepare.add_argument("--replace-generated", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        success, receipt = run_prepare(
            args.project,
            args.plan,
            args.timeout,
            args.replace_generated,
            args.run_id,
            Path(os.environ.get("RAS_COMMANDER_PREPARE_JOB_ROOT", "/job")),
            Path(os.environ.get("RAS_COMMANDER_PREPARE_RUNTIME_MANIFEST", "/runtime/wine-seed/runtime.json")),
            os.environ.get("RAS_COMMANDER_PREPARE_HECRAS_VERSION", "6.6"),
            num_cores=args.num_cores,
        )
    except (JobError, OSError, ValueError) as exc:
        print("hecras-prepare: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"success": success, "receipt": str(receipt)}, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
