"""Self-contained stdlib-only launcher staged with each Slurm submission.

This file intentionally has no ras-commander imports. Compute nodes need only
Python 3, Slurm, and Apptainer; each hydraulic step runs in the pinned SIF.

Every step runs ``apptainer exec --contain --cleanenv`` with three binds: the
request bundle read-only at ``/job``, its empty output directory writable, and
a step-private node-scratch directory as ``/tmp``. Wine copies its prefix
there, so concurrent steps never share host ``/tmp`` or a writable image.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


LAUNCHER_VERSION = "ras-portable-slurm-launcher/v2"
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SAFE_STEP = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,30}\Z")


def _failure(output: Path, reason: str, detail: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = {"reason_code": reason, "detail": detail[:4096]}
    (output / "launcher_failure.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "," in value
        or ":" in value
    ):
        raise ValueError("Unsafe launcher-relative path")
    return path


def _run_step_process(
    command: list[str], *, bundle: Path, output: Path, timeout_seconds: int
) -> subprocess.CompletedProcess:
    """Run one step while keeping its writable result bind initially empty."""
    stdout_temporary = bundle / ".slurm_step.stdout.log"
    stderr_temporary = bundle / ".slurm_step.stderr.log"
    for temporary in (stdout_temporary, stderr_temporary):
        if temporary.exists() or temporary.is_symlink():
            raise ValueError("Stale Slurm step log exists in request bundle")
    try:
        with stdout_temporary.open("x", encoding="utf-8") as stdout, (
            stderr_temporary.open("x", encoding="utf-8")
        ) as stderr:
            return subprocess.run(
                command,
                stdout=stdout,
                stderr=stderr,
                text=True,
                check=False,
                shell=False,
                timeout=timeout_seconds,
            )
    finally:
        for temporary, destination in (
            (stdout_temporary, output / "slurm_step.stdout.log"),
            (stderr_temporary, output / "slurm_step.stderr.log"),
        ):
            if temporary.is_file():
                shutil.move(str(temporary), str(destination))


_CREATED_JOB_SCRATCH: set = set()


def _job_scratch(site: dict) -> Path:
    """Return ``<node_scratch_root>/<SLURM_JOB_ID>``, owned by this user.

    Sites whose prolog creates per-job scratch (``/scratch/$SLURM_JOB_ID``)
    keep a root-owned parent; elsewhere (for example ``/tmp``) the launcher
    creates it 0700. Either way it must be a real directory owned by the job
    user, so another user cannot pre-create or redirect it.
    """
    configured = Path(site["node_scratch_root"])
    job = os.environ.get("SLURM_JOB_ID", "")
    if not configured.is_absolute():
        raise ValueError("node_scratch_root must be an absolute directory")
    # Sites may point /scratch elsewhere (clb07-slurm: /scratch -> /projects/scratch).
    # The per-job directory below must still be a real directory owned by this user.
    root = configured.resolve()
    if not root.is_dir():
        raise ValueError("node_scratch_root must be an existing absolute directory")
    if not re.fullmatch(r"[0-9]+", job):
        raise ValueError("SLURM_JOB_ID is required for step scratch")
    if any("," in part or ":" in part for part in root.parts):
        raise ValueError("Apptainer bind host paths cannot contain ',' or ':'")
    job_dir = root / job
    try:
        job_dir.mkdir(mode=0o700)
        _CREATED_JOB_SCRATCH.add(job_dir)
    except FileExistsError:
        pass
    status = os.lstat(job_dir)
    if not job_dir.is_dir() or job_dir.is_symlink() or status.st_uid != os.getuid():
        raise ValueError(f"Job scratch {job_dir} must be a directory owned by this user")
    return job_dir


def _step_scratch(site: dict, execution_id: str) -> Path:
    """Create the step-private node-scratch directory bound as ``/tmp``."""
    # mkdtemp creates a new 0700 directory with an unpredictable name.
    return Path(tempfile.mkdtemp(prefix=f"ras-commander-{execution_id}-", dir=_job_scratch(site)))


def _remove_created_job_scratch() -> None:
    """Remove a job scratch directory this launcher created, once it is empty."""
    for job_dir in tuple(_CREATED_JOB_SCRATCH):
        try:
            job_dir.rmdir()
        except OSError:
            pass
        _CREATED_JOB_SCRATCH.discard(job_dir)


def _run_step(root: Path, site: dict, step: dict) -> bool:
    execution_id = str(step["execution_id"])
    if not SAFE_ID.fullmatch(execution_id):
        raise ValueError("Unsafe execution_id")
    expected_request = f"bundles/{execution_id}/request.json"
    if step["request_path"] != expected_request:
        raise ValueError("Non-canonical request path")
    request_path = (root / _safe_relative(step["request_path"])).resolve()
    request_path.relative_to(root)
    lexical_request = root / _safe_relative(step["request_path"])
    if any(
        item.is_symlink()
        for item in (lexical_request, *lexical_request.parents)
        if item != root.parent
    ):
        raise ValueError("Request path cannot traverse a symbolic link")
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    canonical_request = json.dumps(
        request_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if hashlib.sha256(canonical_request).hexdigest() != step["request_sha256"]:
        raise ValueError("Staged request digest does not match batch")
    bundle = request_path.parent
    output_relative = _safe_relative(step["output_directory"])
    output = (bundle / output_relative).resolve()
    output.relative_to(bundle)
    if any("," in str(path) or ":" in str(path) for path in (bundle, output)):
        raise ValueError("Apptainer bind host paths cannot contain ',' or ':'")
    output.mkdir(parents=True, exist_ok=True)
    try:
        scratch = _step_scratch(site, execution_id)
    except (OSError, ValueError) as exc:
        _failure(output, "SLURM_STEP_SCRATCH_FAILED", str(exc))
        return False
    command = [
        site["srun_executable"],
        "--exclusive",
        "--nodes=1",
        "--ntasks=1",
        "--cpus-per-task=1",
        "--kill-on-bad-exit=0",
        f"--job-name={step['step_name']}",
        site["apptainer_executable"],
        "exec",
        "--contain",
        "--cleanenv",
        "--env",
        "RAS_COMMANDER_RUNTIME_CONTAINER_IDENTITY="
        f"sif:sha256:{site['apptainer_image_sha256']}",
        "--bind",
        f"{bundle}:/job:ro",
        "--bind",
        f"{output}:/job/{output_relative.as_posix()}:rw",
        "--bind",
        f"{scratch}:/tmp:rw",
        site["apptainer_image"],
        site["python_executable"],
        "-m",
        "ras_commander.remote.execute_request",
        "execute-request",
        "/job/request.json",
    ]
    if site.get("slurm_memory"):
        command.insert(6, f"--mem={site['slurm_memory']}")
    try:
        completed = _run_step_process(
            command,
            bundle=bundle,
            output=output,
            # The Wine bridge owns a bounded solver timeout plus up to five
            # minutes for Windows-Python and task-private wineserver cleanup.
            timeout_seconds=int(step["timeout_seconds"]) + 420,
        )
    except subprocess.TimeoutExpired as exc:
        _failure(output, "SLURM_STEP_TIMEOUT", str(exc))
        return False
    except OSError as exc:
        _failure(output, "SLURM_STEP_LAUNCH_FAILED", str(exc))
        return False
    finally:
        # Wine prefixes are large; results and logs are already in ``output``.
        shutil.rmtree(scratch, ignore_errors=True)
    receipt = output / "execution_receipt.json"
    if completed.returncode != 0 or not receipt.is_file():
        _failure(
            output,
            "SLURM_STEP_FAILED",
            f"returncode={completed.returncode}; receipt_exists={receipt.is_file()}",
        )
        return False
    return True


def _validate_step(step: dict) -> None:
    if not isinstance(step, dict) or set(step) != {
        "execution_id",
        "step_name",
        "request_path",
        "request_sha256",
        "output_directory",
        "timeout_seconds",
    }:
        raise ValueError("Invalid launcher step fields")
    execution_id = str(step["execution_id"])
    if not SAFE_ID.fullmatch(execution_id):
        raise ValueError("Unsafe execution_id")
    if not SAFE_STEP.fullmatch(str(step["step_name"])):
        raise ValueError("Unsafe step_name")
    if step["request_path"] != f"bundles/{execution_id}/request.json":
        raise ValueError("Non-canonical request path")
    if not re.fullmatch(r"[0-9a-f]{64}", str(step["request_sha256"])):
        raise ValueError("Invalid request digest")
    _safe_relative(str(step["output_directory"]))
    if not isinstance(step["timeout_seconds"], int) or step["timeout_seconds"] < 1:
        raise ValueError("Invalid step timeout")


def run(batch_path: Path, array_index: int | None = None) -> bool:
    try:
        return _run_batch(batch_path, array_index)
    finally:
        _remove_created_job_scratch()


def _run_batch(batch_path: Path, array_index: int | None) -> bool:
    root = batch_path.resolve().parent
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    if payload.get("launcher", {}).get("version") != LAUNCHER_VERSION:
        raise ValueError("Launcher version does not match batch")
    site = payload["site"]
    image = Path(site["apptainer_image"])
    if image.is_symlink() or not image.is_file():
        raise ValueError("Apptainer image is not a regular SIF")
    steps = payload["steps"]
    try:
        for step in steps:
            _validate_step(step)
    except Exception as exc:
        _failure(root, "SLURM_BATCH_STEP_INVALID", str(exc))
        raise
    if site.get("execution_mode", "pool") == "array":
        if array_index is None or not 0 <= array_index < len(steps):
            raise ValueError("Array batch requires a valid --array-index")
        step = steps[array_index]
        try:
            return _run_step(root, site, step)
        except Exception as exc:
            output = root / f"bundles/{step['execution_id']}" / _safe_relative(
                step["output_directory"]
            )
            _failure(output, "SLURM_LAUNCHER_EXCEPTION", str(exc))
            return False
    if array_index is not None:
        raise ValueError("--array-index is only valid for array batches")
    results = {}
    with ThreadPoolExecutor(max_workers=int(site["slots_per_node"])) as executor:
        futures = {
            executor.submit(_run_step, root, site, step): step["execution_id"]
            for step in steps
        }
        for future in as_completed(futures):
            execution_id = futures[future]
            try:
                results[execution_id] = future.result()
            except Exception as exc:
                step = next(item for item in steps if item["execution_id"] == execution_id)
                output = root / f"bundles/{execution_id}" / _safe_relative(
                    step["output_directory"]
                )
                _failure(output, "SLURM_LAUNCHER_EXCEPTION", str(exc))
                results[execution_id] = False
    return all(results.get(step["execution_id"], False) for step in steps)


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    array_index = None
    if len(arguments) == 3 and arguments[1] == "--array-index":
        if not re.fullmatch(r"[0-9]{1,6}", arguments[2]):
            print("--array-index must be a non-negative integer", file=sys.stderr)
            return 2
        array_index = int(arguments.pop(2))
        arguments.pop(1)
    if len(arguments) != 1:
        print(
            "usage: portable_slurm_launcher.py BATCH [--array-index N]",
            file=sys.stderr,
        )
        return 2
    try:
        return 0 if run(Path(arguments[0]), array_index) else 1
    except Exception as exc:
        print(f"Slurm launcher failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
