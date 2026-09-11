"""Run the published HEC-RAS preprocessing and native Linux compute images.

The Docker CLI must address a local daemon that can bind the supplied host
paths. Docker Desktop in Linux-container mode is supported. These helpers do
not transfer files to a remote daemon or require HEC-RAS on the Python host.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from numbers import Integral
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union
import uuid

from .Decorators import log_call
from .LoggingConfig import get_logger
from ._container_process import run_streaming
from ._container_resume import find_resume, record_resume


logger = get_logger(__name__)
_VERSIONS = {"6.5", "6.6", "7.0.1"}
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_OWNER_LABEL = "info.rascommander.docker-run-owner"
_RESERVED_MOUNTS = {
    "job", "runtime", "opt", "usr", "etc", "proc", "dev", "sys", "run",
    "tmp", "bin", "sbin", "lib", "lib64", "home", "root",
}


@dataclass
class ContainerResult:
    """A Docker stage result, including its unmodified container receipt.

    ``success`` requires both Docker exit zero and a successful receipt matching
    this invocation. ``receipt_path`` is the expected host path, even when a
    failure prevented receipt creation. ``error`` explains host-side failures;
    container diagnostics remain available in ``receipt``, ``stdout`` and
    ``stderr``. The result is bool-compatible.
    """

    success: bool
    stage: str
    project_path: Path
    plan_number: str
    receipt_path: Path
    receipt: Dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    returncode: Optional[int] = None
    error: Optional[str] = None
    resumed: bool = False
    duration_seconds: float = 0.0

    def __bool__(self) -> bool:
        return self.success


@dataclass(frozen=True)
class ContainerEvent:
    """A host lifecycle or live output event, scoped to one project and stage.

    ``kind`` is ``start``, ``message``, ``complete`` or ``resumed``. Messages
    preserve the source stream. Completion success includes receipt validation.
    No estimated simulation percentage is inferred from elapsed time.
    """

    kind: str
    stage: str
    project_path: Path
    plan_number: str
    run_id: str
    message: str = ""
    stream: Optional[str] = None
    success: Optional[bool] = None


@dataclass
class ContainerBatchResult:
    """Ordered per-job stage results and a stable, exportable ``summary_df``.

    Failed jobs remain in the summary. ``success`` is true only if every job
    succeeded; an empty batch is successful. Batch execution is on the host.
    """

    results: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(row["success"] for row in self.rows)

    def __bool__(self) -> bool:
        return self.success

    @property
    def summary_df(self):
        """One row per submitted job, including skipped stages and failures."""
        import pandas as pd
        from .schemas import DATAFRAME_SCHEMAS

        columns = [item["name"] for item in DATAFRAME_SCHEMAS["container_batch_summary"]["columns"]]
        return pd.DataFrame(self.rows, columns=columns)


class RasDocker:
    """Static API for the two-container HEC-RAS workflow.

    Use a disposable, complete model copy: both stages modify the project bind
    mount. Dependency mounts are read-only. A preprocessing success means the
    compiled inputs are ready; native computation subsequently produces the
    final plan HDF with unsteady results.
    """

    @staticmethod
    @log_call
    def preprocess_plan(
        project_path: Union[str, Path], plan_number: Union[str, int], *,
        version: str = "6.5", image: Optional[str] = None,
        mounts: Optional[Mapping[str, Union[str, Path]]] = None,
        timeout: int = 900, num_cores: int = 2,
        replace_generated: bool = False, docker_executable: str = "docker",
        pull: str = "missing", run_id: Optional[str] = None, user: str = "root",
        stream_callback: Optional[Any] = None, resume: bool = False,
    ) -> ContainerResult:
        """Create ``.tmp.hdf``, ``.b##`` and ``.x##`` in the Wine image.

        Args:
            project_path: Explicit host ``.prj`` file in a working model copy.
            plan_number: Plan number, such as ``"01"`` or ``1``.
            version: Matching HEC-RAS image version: ``"6.5"``, ``"6.6"`` or ``"7.0.1"``.
            image: Image override. Defaults to the published version's ``v4``.
            mounts: Container absolute destination to host source mapping, for
                example ``{"/source_terrain": terrain, "/projection": crs}``.
                These mounts are read-only; the project folder is ``/job`` RW.
            timeout: In-container timeout in seconds. Docker startup, pulling
                and shutdown receive an additional 120 seconds on the host.
                Pull a large image separately if the initial download is slow.
            num_cores: Integer from 1 through 8 (default 2). Sets Docker's CPU
                quota for either stage. Native computation also passes this
                count to HEC-RAS. The published Wine CLI has no thread option.
            replace_generated: Explicit permission to replace existing outputs.
                Defaults to False; use a fresh model copy when enabling it.
            docker_executable: Docker CLI executable path, not a shell command.
            pull: Docker pull policy: ``"always"``, ``"missing"`` or ``"never"``.
                Use ``"always"`` to refresh an image published under the same tag.
            run_id: Optional unique 1–64 character run ID. IDs cannot be reused,
                including after failed launches; omitted IDs are generated.
            user: Container user; ``"root"`` supports Windows bind mounts.
            stream_callback: Partial ExecutionCallback object. An optional
                ``on_container_event(event)`` receives project/stage identity,
                live stdout/stderr, validated completion and resume events.
                Ordinary callback exceptions are logged; interrupts propagate.
            resume: Reuse an unchanged successful stage recorded by this host
                API. Checks model, dependencies, options and output contents.
                A miss executes normally; it does not authorize replacement.

        Returns:
            ContainerResult: Receipt and process diagnostics; failed receipts
            are retained. Invalid inputs or reused run IDs raise before launch.
        """
        return RasDocker._execute(
            "prepare", project_path, plan_number, version=version, image=image,
            mounts=mounts, timeout=timeout, num_cores=num_cores,
            replace_generated=replace_generated, docker_executable=docker_executable,
            pull=pull, run_id=run_id, user=user, prepare_receipt=None,
            stream_callback=stream_callback, resume=resume,
        )

    @staticmethod
    @log_call
    def compute_plan(
        project_path: Union[str, Path], plan_number: Union[str, int], *,
        version: str = "6.5", image: Optional[str] = None,
        mounts: Optional[Mapping[str, Union[str, Path]]] = None,
        timeout: int = 14400, num_cores: int = 2,
        replace_generated: bool = False, docker_executable: str = "docker",
        pull: str = "missing", run_id: Optional[str] = None, user: str = "root",
        prepare_receipt: Optional[Union[str, Path]] = None,
        stream_callback: Optional[Any] = None, resume: bool = False,
    ) -> ContainerResult:
        """Run preprocessed inputs with the native Linux unsteady solver image.

        Parameters follow :meth:`preprocess_plan`. The default image is
        ``rascommander/hec-ras-linux-unsteady_{version}:v1``. This stage passes
        ``num_cores`` to the container, whose worker calls
        :meth:`RasCmdr.compute_plan_linux`. Prepare matching-version inputs first.
        Successful native computation promotes ``.p##.tmp.hdf`` to ``.p##.hdf``.
        ``prepare_receipt`` may explicitly select a ``prepare.json`` inside the
        project folder. Otherwise the worker selects the latest matching valid
        preparation receipt.
        """
        return RasDocker._execute(
            "compute", project_path, plan_number, version=version, image=image,
            mounts=mounts, timeout=timeout, num_cores=num_cores,
            replace_generated=replace_generated, docker_executable=docker_executable,
            pull=pull, run_id=run_id, user=user, prepare_receipt=prepare_receipt,
            stream_callback=stream_callback, resume=resume,
        )

    @staticmethod
    @log_call
    def run_plan(
        project_path: Union[str, Path], plan_number: Union[str, int], *,
        version: str = "6.5", preprocess_image: Optional[str] = None,
        compute_image: Optional[str] = None,
        mounts: Optional[Mapping[str, Union[str, Path]]] = None,
        preprocess_timeout: int = 900, compute_timeout: int = 14400,
        num_cores: int = 2, replace_generated: bool = False,
        docker_executable: str = "docker", pull: str = "missing",
        run_id: Optional[str] = None, user: str = "root",
        stream_callback: Optional[Any] = None, resume: bool = False,
    ) -> Tuple[ContainerResult, Optional[ContainerResult]]:
        """Prepare then compute, stopping if preparation fails.

        Returns ``(preparation, computation)``; computation is None after a
        failed preparation. An optional run ID is a prefix of at most 56
        characters; ``-prepare`` and ``-compute`` identify separate receipts.
        """
        if run_id is not None and (
            not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id)
            or len(run_id) > 56
        ):
            raise ValueError("run_plan run_id must be a valid run ID of at most 56 characters")
        common = dict(
            version=version, mounts=mounts, num_cores=num_cores,
            replace_generated=replace_generated, docker_executable=docker_executable,
            pull=pull, user=user,
            stream_callback=stream_callback, resume=resume,
        )
        prepared = RasDocker.preprocess_plan(
            project_path, plan_number, image=preprocess_image,
            timeout=preprocess_timeout, run_id=f"{run_id}-prepare" if run_id else None,
            **common,
        )
        if not prepared:
            return prepared, None
        computed = RasDocker.compute_plan(
            project_path, plan_number, image=compute_image,
            timeout=compute_timeout, run_id=f"{run_id}-compute" if run_id else None,
            prepare_receipt=prepared.receipt_path,
            **common,
        )
        return prepared, computed

    @staticmethod
    @log_call
    def run_batch(jobs: Iterable[Mapping[str, Any]], *, stage: str = "run", **options) -> ContainerBatchResult:
        """Run independent working copies sequentially and collect every outcome.

        Each job maps ``project_path`` and ``plan_number`` plus optional overrides
        accepted by :meth:`run_plan` (``stage='run'``), :meth:`preprocess_plan`
        (``'prepare'``), or :meth:`compute_plan` (``'compute'``). Shared options,
        including ``resume`` and ``stream_callback``, are keyword arguments.
        Job overrides win. A failed job does not prevent later jobs from running.
        KeyboardInterrupt stops the batch and cleans up the active container.

        No pool runs inside a container. For concurrent jobs, an external
        scheduler can call the single-plan APIs on separate working folders.
        Summary rows identify success, reuse, durations, receipts and errors.
        """
        methods = {"run": RasDocker.run_plan, "prepare": RasDocker.preprocess_plan,
                   "compute": RasDocker.compute_plan}
        if stage not in methods:
            raise ValueError("stage must be 'run', 'prepare' or 'compute'")
        batch = ContainerBatchResult()
        for index, job in enumerate(jobs):
            prepared = computed = None
            started = time.monotonic()
            row = {"job_index": index, "project_path": None, "plan_number": None,
                   "stage": stage, "success": False, "resumed": False,
                   "status": "failed", "duration_seconds": 0.0,
                   "prepare_receipt": None, "compute_receipt": None, "error": None}
            try:
                if not isinstance(job, Mapping):
                    raise TypeError("Each batch job must be a mapping")
                kwargs = {**options, **job}
                row["project_path"] = str(Path(kwargs["project_path"]).expanduser().resolve())
                row["plan_number"] = RasDocker._normalize_plan(kwargs["plan_number"])
                value = methods[stage](**kwargs)
                if stage == "run":
                    prepared, computed = value
                elif stage == "prepare":
                    prepared = value
                else:
                    computed = value
                stages = [item for item in (prepared, computed) if item is not None]
                row["success"] = all(item.success for item in stages)
                if stage == "run" and computed is None:
                    row["success"] = False
                row["resumed"] = row["success"] and all(item.resumed for item in stages)
                row["status"] = "resumed" if row["resumed"] else ("succeeded" if row["success"] else "failed")
                row["error"] = "; ".join(item.error or str(item.receipt.get("error", "Container stage failed"))
                                            for item in stages if not item.success) or None
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            row["duration_seconds"] = time.monotonic() - started
            if prepared is not None:
                row["prepare_receipt"] = str(prepared.receipt_path)
            if computed is not None:
                row["compute_receipt"] = str(computed.receipt_path)
            batch.results.append((prepared, computed))
            batch.rows.append(row)
        return batch

    @staticmethod
    def _notify(callback, method, *args):
        if callback is None:
            return
        try:
            function = getattr(callback, method, None)
            if function is not None:
                function(*args)
        except Exception:
            logger.warning("Container callback %s failed", method, exc_info=True)

    @staticmethod
    def _execute(stage, project_path, plan_number, *, version, image, mounts,
                 timeout, num_cores, replace_generated, docker_executable, pull,
                 run_id, user, prepare_receipt, stream_callback=None, resume=False):
        started = time.monotonic()
        if version not in _VERSIONS:
            raise ValueError("version must be '6.5', '6.6' or '7.0.1'")
        for name, value in (("timeout", timeout), ("num_cores", num_cores)):
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if num_cores > 8:
            raise ValueError("num_cores must be between 1 and 8")
        if not isinstance(resume, bool):
            raise ValueError("resume must be a bool")
        if not isinstance(replace_generated, bool):
            raise ValueError("replace_generated must be a bool")
        if pull not in {"always", "missing", "never"}:
            raise ValueError("pull must be 'always', 'missing' or 'never'")
        for name, value in (("docker_executable", docker_executable), ("user", user)):
            if not isinstance(value, str) or not value.strip() or any(c in value for c in "\x00\r\n"):
                raise ValueError(f"{name} must be a nonempty string without control characters")
        project = Path(project_path).expanduser().resolve(strict=True)
        if not project.is_file() or project.suffix.lower() != ".prj":
            raise ValueError("project_path must point to an existing .prj file")
        plan = RasDocker._normalize_plan(plan_number)
        family = "wine-precompute" if stage == "prepare" else "linux-unsteady"
        tag = "v4" if stage == "prepare" else "v1"
        image = image if image is not None else f"rascommander/hec-ras-{family}_{version}:{tag}"
        if not isinstance(image, str) or not image or image.startswith("-") or any(c.isspace() or c == "\x00" for c in image):
            raise ValueError("image must be a Docker image reference, not CLI options")
        known_image = re.search(r"(?:^|/)hec-ras-(wine-precompute|linux-unsteady)_([^:@/]+)(?=[:@]|$)", image)
        if known_image and (known_image.group(1) != family or known_image.group(2) != version):
            raise ValueError("Image stage/version does not match the requested stage/version")
        mount_args = RasDocker._mount_arguments(project.parent, mounts)
        selected_receipt = None
        if prepare_receipt is not None:
            selected = Path(prepare_receipt).expanduser().resolve(strict=True)
            if (not selected.is_file() or selected.name != "prepare.json"
                    or not selected.is_relative_to(project.parent)):
                raise ValueError("prepare_receipt must be a prepare.json file inside the project folder")
            selected_receipt = "/job/" + selected.relative_to(project.parent).as_posix()
        if run_id is None:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:16]
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must use 1–64 letters, digits, periods, underscores or hyphens, starting with a letter or digit")
        identity = {"version": version, "image": image, "num_cores": int(num_cores),
                    "mounts": {str(dest): str(Path(source).expanduser().resolve())
                               for dest, source in (mounts or {}).items()},
                    "prepare_receipt": str(selected) if prepare_receipt is not None else None}
        if resume:
            cached = find_resume(project, plan, stage, identity)
            if cached is not None:
                result = ContainerResult(True, stage, project, plan, Path(cached["receipt_path"]),
                                         receipt=cached["receipt"], resumed=True,
                                         duration_seconds=time.monotonic() - started)
                RasDocker._notify(stream_callback, "on_container_event", ContainerEvent(
                    "resumed", stage, project, plan, result.receipt["run_id"], success=True))
                return result
        runs = project.parent / ".ras-commander" / "runs"
        # An exclusive claim prevents concurrent calls from crediting each
        # other's receipt. Keep it after launch failures to prohibit ID reuse.
        if not runs.resolve().is_relative_to(project.parent):
            raise ValueError("Receipt directory must remain inside the project folder")
        runs.mkdir(parents=True, exist_ok=True)
        run_dir = runs / run_id
        if run_dir.exists() or run_dir.is_symlink():
            raise FileExistsError(f"Run ID already exists: {run_id}")
        claim = runs / f".{run_id}.docker-claim"
        with claim.open("x", encoding="utf-8") as handle:
            json.dump({"run_id": run_id, "stage": stage, "image": image}, handle)
        receipt_path = run_dir / f"{'prepare' if stage == 'prepare' else 'compute'}.json"
        result = ContainerResult(False, stage, project, plan, receipt_path)
        owner = uuid.uuid4().hex
        name = f"ras-commander-{stage}-{owner}"
        logger.info("Starting Docker %s for plan %s with HEC-RAS %s", stage, plan, version)
        with tempfile.TemporaryDirectory(prefix="ras-docker-") as control_dir:
            cid_file = Path(control_dir) / "container.id"
            command = [docker_executable, "run", "--rm", "--pull", pull,
                       "--name", name, "--label", f"{_OWNER_LABEL}={owner}",
                       "--cidfile", str(cid_file), "--user", user,
                       "--cpus", str(num_cores), *mount_args,
                       image, stage, "--project", f"/job/{project.name}", "--plan", plan,
                       "--timeout", str(timeout), "--run-id", run_id]
            if stage == "compute":
                command += ["--num-cores", str(num_cores)]
            if selected_receipt is not None:
                command += ["--prepare-receipt", selected_receipt]
            if replace_generated:
                command.append("--replace-generated")
            try:
                RasDocker._notify(stream_callback, "on_container_event", ContainerEvent(
                    "start", stage, project, plan, run_id))
                if stage == "prepare":
                    RasDocker._notify(stream_callback, "on_prep_start", plan)
                else:
                    RasDocker._notify(stream_callback, "on_exec_start", plan, subprocess.list2cmdline(command))
                def on_line(stream, message):
                    RasDocker._notify(stream_callback, "on_container_event", ContainerEvent(
                        "message", stage, project, plan, run_id, message=message, stream=stream))
                    RasDocker._notify(stream_callback, "on_exec_message", plan, message)
                completed = run_streaming(command, timeout=int(timeout) + 120, on_line=on_line)
                result.stdout = completed.stdout or ""
                result.stderr = completed.stderr or ""
                result.returncode = completed.returncode
            except subprocess.TimeoutExpired as exc:
                result.stdout = RasDocker._text(exc.stdout)
                result.stderr = RasDocker._text(exc.stderr)
                result.error = f"Docker exceeded the {int(timeout) + 120}s host timeout"
                cleanup_error = RasDocker._cleanup_owned(docker_executable, name, owner, cid_file)
                if cleanup_error:
                    result.error += f"; {cleanup_error}"
            except OSError as exc:
                if getattr(exc, "_ras_container_cli_started", False):
                    result.error = f"Docker output transport failed: {exc}"
                    cleanup_error = RasDocker._cleanup_owned(docker_executable, name, owner, cid_file)
                    if cleanup_error:
                        result.error += f"; {cleanup_error}"
                else:
                    result.error = f"Could not launch Docker: {exc}"
            except BaseException:
                RasDocker._cleanup_owned(docker_executable, name, owner, cid_file)
                raise
        RasDocker._read_receipt(result, run_id, version)
        result.duration_seconds = time.monotonic() - started
        if result.success and resume:
            record_resume(project, plan, stage, identity, result.receipt_path)
        if stage == "prepare":
            if result.success:
                RasDocker._notify(stream_callback, "on_prep_complete", plan)
        else:
            RasDocker._notify(stream_callback, "on_exec_complete", plan, result.success, result.duration_seconds)
            RasDocker._notify(stream_callback, "on_verify_result", plan, result.success)
        RasDocker._notify(stream_callback, "on_container_event", ContainerEvent(
            "complete", stage, project, plan, run_id, success=result.success,
            message=result.error or ""))
        logger.info("Docker %s for plan %s: %s", stage, plan, "succeeded" if result else "failed")
        return result

    @staticmethod
    def _normalize_plan(value):
        if isinstance(value, bool) or not isinstance(value, (str, Integral)):
            raise ValueError("plan_number must be an integer or one or two digits")
        text = str(value)
        if not re.fullmatch(r"[0-9]{1,2}", text) or int(text) < 1:
            raise ValueError("plan_number must be between 01 and 99")
        return text.zfill(2)

    @staticmethod
    def _mount_arguments(project_folder, mounts):
        if mounts is not None and not isinstance(mounts, Mapping):
            raise TypeError("mounts must map container destinations to host paths")
        entries = [("/job", project_folder, False)]
        destinations = []
        for destination, source in (mounts or {}).items():
            if not isinstance(destination, str):
                raise ValueError("Mount destinations must be absolute container paths")
            path = PurePosixPath(destination)
            if (not destination.startswith("/") or destination.startswith("//")
                    or "\\" in destination or ".." in path.parts or len(path.parts) < 2
                    or path.parts[1] in _RESERVED_MOUNTS):
                raise ValueError(f"Unsafe or reserved mount destination: {destination}")
            normalized = path.as_posix()
            if any(path == prior or path in prior.parents or prior in path.parents for prior in destinations):
                raise ValueError(f"Overlapping dependency mount destination: {destination}")
            destinations.append(path)
            entries.append((normalized, Path(source).expanduser().resolve(strict=True), True))
        arguments = []
        for destination, source, readonly in entries:
            # Docker --mount is a CSV mini-language even with shell=False.
            # Reject delimiters rather than allowing extra mount properties.
            if any(char in str(source) + destination for char in ',"\x00\r\n'):
                raise ValueError("Docker bind paths cannot contain commas, quotes, NUL or newlines")
            spec = f"type=bind,src={source},dst={destination}"
            if readonly:
                spec += ",readonly"
            arguments += ["--mount", spec]
        return arguments

    @staticmethod
    def _read_receipt(result, run_id, version):
        diagnostics = []
        try:
            receipt_file = result.receipt_path.resolve(strict=True)
            if not receipt_file.is_relative_to(result.project_path.parent):
                raise ValueError("Receipt path escapes the project folder")
            receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
            if not isinstance(receipt, dict):
                raise ValueError("Receipt must be a JSON object")
            result.receipt = receipt
            expected = {"run_id": run_id, "command": result.stage,
                        "project": result.project_path.name, "plan": result.plan_number}
            for field_name, value in expected.items():
                if receipt.get(field_name) != value:
                    diagnostics.append(f"Receipt {field_name} does not match this invocation")
            versions = [receipt.get("hec_ras_version")]
            runtime = receipt.get("runtime")
            if isinstance(runtime, dict):
                versions.append(runtime.get("hec_ras_version"))
            if any(str(value) != version for value in versions if value is not None):
                diagnostics.append("Receipt HEC-RAS version does not match the requested version")
            if receipt.get("status") != "succeeded":
                diagnostics.append("Container receipt does not report success")
        except (OSError, ValueError) as exc:
            diagnostics.append(f"Could not validate container receipt: {exc}")
        if result.returncode != 0:
            diagnostics.append(f"Docker return code: {result.returncode}")
        if diagnostics:
            result.error = "; ".join(([result.error] if result.error else []) + diagnostics)
        result.success = result.error is None

    @staticmethod
    def _text(value):
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")

    @staticmethod
    def _cleanup_owned(executable, name, owner, cid_file):
        """Remove only a container carrying this invocation's random label."""
        target = name
        try:
            if cid_file.is_file():
                candidate = cid_file.read_text(encoding="utf-8").strip()
                if re.fullmatch(r"[a-f0-9]{64}", candidate):
                    target = candidate
            inspected = subprocess.run(
                [executable, "inspect", "--format", "{{json .Config.Labels}}", target],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                shell=False, timeout=15,
            )
            if inspected.returncode != 0:
                return "Container cleanup could not verify whether the owned container remains; check Docker"
            labels = json.loads(inspected.stdout)
            if not isinstance(labels, dict) or labels.get(_OWNER_LABEL) != owner:
                return "Container cleanup refused an ownership-label mismatch"
            removed = subprocess.run(
                [executable, "rm", "--force", target], capture_output=True,
                text=True, encoding="utf-8", errors="replace", shell=False, timeout=30,
            )
            if removed.returncode != 0:
                return "Docker could not remove the owned container: " + removed.stderr.strip()
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return f"Owned-container cleanup failed: {exc}"
        return None
