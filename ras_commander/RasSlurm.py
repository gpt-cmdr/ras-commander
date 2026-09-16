"""Slurm/Apptainer adapter for portable one-core steady-plan requests.

Local and SSH transports use the same staged directory. Remote jobs never
contain workstation paths: each request is rebuilt as a self-contained bundle
under ``bundles/<execution_id>`` and the batch manifest stores relative paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
from typing import Mapping, Optional, Sequence, Union
import uuid

from .Decorators import log_call
from .LoggingConfig import get_logger
from .remote.ExecutionContract import (
    RasExecutionReceipt,
    RasExecutionRequest,
    atomic_write_json,
    sha256_file,
    validate_execution_receipt,
)
from .remote.portable_slurm_launcher import LAUNCHER_VERSION


logger = get_logger(__name__)
SLURM_BATCH_SCHEMA = "ras-commander-slurm-batch/v1"
SLURM_SUBMISSION_SCHEMA = "ras-commander-slurm-submission/v1"
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")
_MODULE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}\Z")
_MEMORY = re.compile(r"[1-9][0-9]*(?:[KMGTP])?\Z", re.IGNORECASE)
_TIME = re.compile(r"(?:[0-9]+-)?[0-9]{1,2}:[0-9]{2}:[0-9]{2}\Z")
_REMOTE_PATH = re.compile(r"/[A-Za-z0-9._/+-]+(?:/[A-Za-z0-9._+-]+)*\Z")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_CONTAINER_IDENTITY = re.compile(
    r"(?:sif:sha256:[0-9a-f]{64}|[A-Za-z0-9._-]+(?::[0-9]+)?"
    r"(?:/[A-Za-z0-9._-]+)+@sha256:[0-9a-f]{64})\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _allocation_memory(per_task: str, slots: int) -> str:
    """Return the node allocation needed for ``slots`` bounded task steps."""

    match = re.fullmatch(r"([1-9][0-9]*)([KMGTP]?)", per_task, re.IGNORECASE)
    if match is None:  # SlurmSiteConfig validates this before rendering.
        raise ValueError("per-task Slurm memory has an unsupported format")
    amount, suffix = match.groups()
    return f"{int(amount) * slots}{suffix.upper()}"


@dataclass(frozen=True)
class SlurmSiteConfig:
    """Scheduler-only settings kept outside hydraulic request manifests."""

    site_name: str
    apptainer_image: str
    apptainer_image_sha256: str
    container_identity: str
    slots_per_node: int = 8
    memory_per_task: str = "3G"
    slurm_memory: Optional[str] = None
    time_limit: str = "02:00:00"
    partition: Optional[str] = None
    account: Optional[str] = None
    qos: Optional[str] = None
    modules: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    sbatch_executable: str = "sbatch"
    sacct_executable: str = "sacct"
    squeue_executable: str = "squeue"
    scancel_executable: str = "scancel"
    srun_executable: str = "srun"
    apptainer_executable: str = "apptainer"
    python_executable: str = "python"
    launcher_python_executable: str = "python3"

    def __post_init__(self) -> None:
        object.__setattr__(self, "modules", tuple(self.modules))
        object.__setattr__(self, "environment", dict(self.environment))
        for name, value in (
            ("site_name", self.site_name),
            ("partition", self.partition),
            ("account", self.account),
            ("qos", self.qos),
        ):
            if value is not None and not _TOKEN.fullmatch(value):
                raise ValueError(f"{name} contains unsupported Slurm characters")
        if not 1 <= self.slots_per_node <= 256:
            raise ValueError("slots_per_node must be from 1 through 256")
        if not _MEMORY.fullmatch(self.memory_per_task):
            raise ValueError("memory_per_task must look like '3072M' or '3G'")
        if self.slurm_memory is not None and not _MEMORY.fullmatch(self.slurm_memory):
            raise ValueError("slurm_memory must be omitted or look like '3072M' or '3G'")
        if not _TIME.fullmatch(self.time_limit):
            raise ValueError("time_limit must use [[days-]HH:]MM:SS form")
        if not _REMOTE_PATH.fullmatch(self.apptainer_image) or any(
            part in {".", ".."} for part in self.apptainer_image.split("/")
        ):
            raise ValueError("apptainer_image must be a safe absolute POSIX path")
        if not _SHA256.fullmatch(self.apptainer_image_sha256):
            raise ValueError("apptainer_image_sha256 must be a lowercase SHA-256")
        if not _CONTAINER_IDENTITY.fullmatch(self.container_identity):
            raise ValueError(
                "container_identity must be an immutable OCI reference or SIF digest"
            )
        if any(not _MODULE.fullmatch(module) for module in self.modules):
            raise ValueError("module names contain unsupported shell characters")
        for name, value in self.environment.items():
            if not _ENV_NAME.fullmatch(name) or "\x00" in str(value):
                raise ValueError("Invalid environment name or value")
        for name in (
            "sbatch_executable",
            "sacct_executable",
            "squeue_executable",
            "scancel_executable",
            "srun_executable",
            "apptainer_executable",
            "python_executable",
            "launcher_python_executable",
        ):
            value = str(getattr(self, name))
            if not _MODULE.fullmatch(value):
                raise ValueError(f"{name} contains unsupported shell characters")


@dataclass(frozen=True)
class SlurmTransportConfig:
    """Local scheduler or SSH transport using rsync or recursive SCP."""

    mode: str = "local"
    transfer_mode: str = "rsync"
    hostname: Optional[str] = None
    username: Optional[str] = None
    remote_scratch: Optional[str] = None
    port: int = 22
    identity_file: Optional[str] = None
    ssh_executable: str = "ssh"
    rsync_executable: str = "rsync"
    scp_executable: str = "scp"

    def __post_init__(self) -> None:
        if self.mode not in {"local", "ssh"}:
            raise ValueError("transport mode must be 'local' or 'ssh'")
        if self.transfer_mode not in {"rsync", "scp"}:
            raise ValueError("transfer_mode must be 'rsync' or 'scp'")
        if not 1 <= self.port <= 65535:
            raise ValueError("SSH port must be from 1 through 65535")
        if self.mode == "ssh":
            if not self.hostname or not _TOKEN.fullmatch(self.hostname):
                raise ValueError("SSH hostname contains unsupported characters")
            if not self.username or not _TOKEN.fullmatch(self.username):
                raise ValueError("SSH username contains unsupported characters")
            if not self.remote_scratch or not _REMOTE_PATH.fullmatch(
                self.remote_scratch
            ) or any(
                part in {".", ".."} for part in self.remote_scratch.split("/")
            ):
                raise ValueError("remote_scratch must be an absolute safe POSIX path")
        if self.identity_file is not None and "\x00" in self.identity_file:
            raise ValueError("identity_file contains a null byte")
        for name in ("ssh_executable", "rsync_executable", "scp_executable"):
            if not _MODULE.fullmatch(str(getattr(self, name))):
                raise ValueError(f"{name} contains unsupported characters")


@dataclass(frozen=True)
class SlurmTaskAccounting:
    """One ``sacct`` allocation, batch, extern, or step record."""

    job_id: str
    job_name: str
    state: str
    exit_code: str
    max_rss: str
    elapsed: str


@dataclass(frozen=True)
class SlurmStatus:
    """Allocation state plus task-level exit and peak-memory evidence."""

    allocation_state: str
    records: tuple[SlurmTaskAccounting, ...] = ()


@dataclass(frozen=True)
class SlurmSubmission:
    """Rendered, staged, or submitted allocation identity."""

    submission_id: str
    submission_directory: Path
    request_paths: tuple[Path, ...]
    site: SlurmSiteConfig
    batch_sha256: str
    launcher_sha256: str
    submit_sha256: str
    launcher_version: str
    transport: SlurmTransportConfig = field(default_factory=SlurmTransportConfig)
    remote_directory: Optional[str] = None
    job_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not _TOKEN.fullmatch(self.submission_id):
            raise ValueError("Slurm submission_id contains unsupported characters")
        directory = Path(self.submission_directory)
        if not directory.is_absolute():
            raise ValueError("Slurm submission_directory must be absolute")
        if directory.is_symlink():
            raise ValueError("Slurm submission_directory cannot be a symbolic link")
        object.__setattr__(self, "submission_directory", directory.resolve())
        raw_request_paths = tuple(Path(p) for p in self.request_paths)
        object.__setattr__(
            self, "request_paths", tuple(path.resolve() for path in raw_request_paths)
        )
        if not self.request_paths:
            raise ValueError("Slurm submission must contain request paths")
        for raw_path, path in zip(raw_request_paths, self.request_paths):
            if raw_path.is_symlink() or raw_path.parent.is_symlink():
                raise ValueError("Slurm request path cannot traverse a symbolic link")
            try:
                relative = path.relative_to(self.submission_directory)
            except ValueError as exc:
                raise ValueError("Slurm request path is outside submission directory") from exc
            if (
                len(relative.parts) != 3
                or relative.parts[0] != "bundles"
                or relative.parts[2] != "request.json"
                or not _TOKEN.fullmatch(relative.parts[1])
            ):
                raise ValueError("Slurm request path is not canonical")
            if path.is_file():
                request = RasExecutionRequest.read(path)
                if request.execution_id != relative.parts[1]:
                    raise ValueError(
                        "Slurm request execution_id does not match bundle directory"
                    )
        if not _SHA256.fullmatch(self.batch_sha256):
            raise ValueError("Slurm batch_sha256 must be a lowercase SHA-256")
        if not _SHA256.fullmatch(self.launcher_sha256):
            raise ValueError("Slurm launcher_sha256 must be a lowercase SHA-256")
        if not _SHA256.fullmatch(self.submit_sha256):
            raise ValueError("Slurm submit_sha256 must be a lowercase SHA-256")
        if self.launcher_version != LAUNCHER_VERSION:
            raise ValueError("Unsupported portable Slurm launcher version")
        if self.job_id is not None and not re.fullmatch(r"[0-9]+", self.job_id):
            raise ValueError("Slurm job_id must contain digits only")
        if self.transport.mode == "local":
            if self.remote_directory is not None:
                raise ValueError("Local Slurm transport cannot have remote_directory")
        else:
            if self.remote_directory is None:
                raise ValueError("SSH Slurm handle requires remote_directory")
            expected = str(
                PurePosixPath(self.transport.remote_scratch) / self.submission_id
            )
            if self.remote_directory != expected:
                raise ValueError("Slurm remote_directory is not canonical")

    def to_dict(self) -> dict:
        """Serialize the complete later-process lifecycle handle."""
        return {
            "schema": SLURM_SUBMISSION_SCHEMA,
            "submission_id": self.submission_id,
            "submission_directory": str(self.submission_directory),
            "request_paths": [str(path) for path in self.request_paths],
            "site": asdict(self.site),
            "batch_sha256": self.batch_sha256,
            "launcher_sha256": self.launcher_sha256,
            "submit_sha256": self.submit_sha256,
            "launcher_version": self.launcher_version,
            "transport": asdict(self.transport),
            "remote_directory": self.remote_directory,
            "job_id": self.job_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "SlurmSubmission":
        """Validate and rehydrate a stored lifecycle handle."""
        values = dict(payload)
        if values.pop("schema", None) != SLURM_SUBMISSION_SCHEMA:
            raise ValueError("Unsupported Slurm submission schema")
        expected = {
            "submission_id",
            "submission_directory",
            "request_paths",
            "site",
            "batch_sha256",
            "launcher_sha256",
            "submit_sha256",
            "launcher_version",
            "transport",
            "remote_directory",
            "job_id",
        }
        if set(values) != expected:
            raise ValueError("Slurm submission fields do not match the v1 schema")
        values["submission_directory"] = Path(values["submission_directory"])
        values["request_paths"] = tuple(Path(path) for path in values["request_paths"])
        values["site"] = SlurmSiteConfig(**values["site"])
        values["transport"] = SlurmTransportConfig(**values["transport"])
        return cls(**values)

    def write(self, path: Union[str, Path]) -> Path:
        """Write this lifecycle handle atomically."""
        return atomic_write_json(path, self.to_dict())

    @classmethod
    def read(cls, path: Union[str, Path]) -> "SlurmSubmission":
        """Rehydrate a lifecycle handle in a later process."""
        with Path(path).open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("Slurm submission JSON must contain an object")
        return cls.from_dict(payload)


@dataclass(frozen=True)
class SlurmCollection:
    """Collected receipts and scheduler accounting evidence."""

    receipts: Mapping[str, Optional[RasExecutionReceipt]]
    errors: Mapping[str, str]
    accounting: Optional[SlurmStatus] = None

    @property
    def success(self) -> bool:
        receipts_ok = bool(self.receipts) and all(
            receipt is not None and receipt.success
            for receipt in self.receipts.values()
        )
        scheduler_ok = (
            self.accounting is None
            or self.accounting.allocation_state == "COMPLETED"
        )
        return receipts_ok and scheduler_ok and not self.errors


def _ssh_base(transport: SlurmTransportConfig) -> list[str]:
    command = [transport.ssh_executable, "-p", str(transport.port)]
    if transport.identity_file:
        command.extend(("-i", transport.identity_file))
    command.append(f"{transport.username}@{transport.hostname}")
    return command


def _scp_base(transport: SlurmTransportConfig) -> list[str]:
    command = [
        transport.scp_executable,
        "-r",
        "-P",
        str(transport.port),
    ]
    if transport.identity_file:
        command.extend(("-i", transport.identity_file))
    return command


def _copy_request_bundle(request_path: Path, destination: Path) -> Path:
    request = RasExecutionRequest.read(request_path)
    source, _ = request.resolve_paths(request_path)
    destination.mkdir(parents=True, exist_ok=False)
    source_destination = destination / request.source_project_path
    source_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source.parent, source_destination.parent, dirs_exist_ok=True)
    staged = destination / "request.json"
    request.write(staged)
    # Resolve the staged copy before it is eligible to submit.
    RasExecutionRequest.read(staged).resolve_paths(staged)
    return staged


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left in right.parents or right in left.parents


def _preflight_request_paths(paths: Sequence[Path]) -> None:
    resolved = []
    for path in paths:
        request = RasExecutionRequest.read(path)
        source, output = request.resolve_paths(path)
        resolved.append((request.execution_id, source.parent.resolve(), output.resolve()))
    outputs = [item[2] for item in resolved]
    if len(outputs) != len(set(outputs)):
        raise ValueError("Execution request output directories must be unique")
    for index, (execution_id, _, output) in enumerate(resolved):
        for other_id, source_tree, _ in resolved:
            if _paths_overlap(output, source_tree):
                raise ValueError(
                    f"Output for {execution_id} overlaps source tree for {other_id}"
                )
        for other in outputs[index + 1 :]:
            if _paths_overlap(output, other):
                raise ValueError("Execution request output directories overlap")


def _validate_submission_files(submission: SlurmSubmission) -> None:
    batch = submission.submission_directory / "slurm_batch.json"
    launcher = submission.submission_directory / "portable_slurm_launcher.py"
    submit = submission.submission_directory / "submit.sbatch"
    if sha256_file(batch) != submission.batch_sha256:
        raise ValueError("Slurm batch manifest digest does not match submission")
    if sha256_file(launcher) != submission.launcher_sha256:
        raise ValueError("Slurm launcher digest does not match submission")
    if sha256_file(submit) != submission.submit_sha256:
        raise ValueError("Slurm submit script digest does not match submission")
    payload = json.loads(batch.read_text(encoding="utf-8"))
    if payload.get("schema") != SLURM_BATCH_SCHEMA:
        raise ValueError("Slurm batch schema does not match submission")
    if payload.get("submission_id") != submission.submission_id:
        raise ValueError("Slurm batch submission_id does not match handle")
    normalized_site = json.loads(json.dumps(asdict(submission.site)))
    if payload.get("site") != normalized_site:
        raise ValueError("Slurm batch site does not match handle")
    if payload.get("launcher") != {
        "path": launcher.name,
        "version": submission.launcher_version,
        "sha256": submission.launcher_sha256,
    }:
        raise ValueError("Slurm batch launcher does not match handle")
    relative_paths = [
        path.relative_to(submission.submission_directory).as_posix()
        for path in submission.request_paths
    ]
    if payload.get("request_paths") != relative_paths:
        raise ValueError("Slurm batch request set does not match handle")
    steps = payload.get("steps")
    if not isinstance(steps, list) or len(steps) != len(submission.request_paths):
        raise ValueError("Slurm batch steps do not match handle")
    for step, path, relative in zip(steps, submission.request_paths, relative_paths):
        request = RasExecutionRequest.read(path)
        if not (
            step.get("execution_id") == request.execution_id
            and step.get("request_path") == relative
            and step.get("request_sha256") == request.digest
            and step.get("output_directory") == request.output_directory
            and step.get("timeout_seconds") == request.timeout_seconds
        ):
            raise ValueError("Slurm batch request digest or contract does not match")


def _validate_local_apptainer_paths(submission: SlurmSubmission) -> None:
    paths = [submission.submission_directory]
    for request_path in submission.request_paths:
        request = RasExecutionRequest.read(request_path)
        _, output = request.resolve_paths(request_path)
        paths.extend((request_path.parent, output))
    for path in paths:
        text = str(path)
        if "," in text or (os.name != "nt" and ":" in text):
            raise ValueError(
                "Local Apptainer bind host paths cannot contain ',' or ':'"
            )


class RasSlurm:
    """Render, transport, and manage one exclusive-node Slurm allocation."""

    @staticmethod
    @log_call
    def render_submission(
        request_paths: Sequence[Union[str, Path]],
        submission_directory: Union[str, Path],
        *,
        site: SlurmSiteConfig,
        submission_id: Optional[str] = None,
    ) -> SlurmSubmission:
        """Stage self-contained bundles and write a safe static sbatch script."""
        source_paths = tuple(Path(path).resolve() for path in request_paths)
        requests = tuple(RasExecutionRequest.read(path) for path in source_paths)
        if not source_paths:
            raise ValueError("At least one execution request is required")
        _preflight_request_paths(source_paths)
        execution_ids = [request.execution_id for request in requests]
        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("Every Slurm request must have a unique execution_id")
        for request in requests:
            if request.container_identity != site.container_identity:
                raise ValueError(
                    f"Request {request.execution_id} container identity does not "
                    "match the Slurm site configuration"
                )

        identifier = submission_id or f"ras-{uuid.uuid4().hex[:12]}"
        if not _TOKEN.fullmatch(identifier):
            raise ValueError("submission_id contains unsupported characters")
        directory = Path(submission_directory).resolve()
        if directory.exists() and any(directory.iterdir()):
            raise ValueError("submission_directory must be absent or empty")
        directory.mkdir(parents=True, exist_ok=True)

        staged_paths = tuple(
            _copy_request_bundle(path, directory / "bundles" / request.execution_id)
            for path, request in zip(source_paths, requests)
        )
        relative_paths = [
            path.relative_to(directory).as_posix() for path in staged_paths
        ]
        steps = [
            {
                "execution_id": request.execution_id,
                "step_name": f"rc-{index:03d}-{request.digest[:12]}",
                "request_path": relative,
                "request_sha256": request.digest,
                "output_directory": request.output_directory,
                "timeout_seconds": request.timeout_seconds,
            }
            for index, (request, relative) in enumerate(zip(requests, relative_paths))
        ]
        launcher_path = directory / "portable_slurm_launcher.py"
        shutil.copyfile(
            Path(__file__).parent / "remote" / "portable_slurm_launcher.py",
            launcher_path,
        )
        launcher_sha256 = sha256_file(launcher_path)
        batch_payload = {
            "schema": SLURM_BATCH_SCHEMA,
            "submission_id": identifier,
            "request_paths": relative_paths,
            "steps": steps,
            "site": asdict(site),
            "launcher": {
                "path": launcher_path.name,
                "version": LAUNCHER_VERSION,
                "sha256": launcher_sha256,
            },
        }
        atomic_write_json(directory / "slurm_batch.json", batch_payload)
        batch_sha256 = sha256_file(directory / "slurm_batch.json")

        directives = [
            "#!/bin/bash",
            f"#SBATCH --job-name={identifier}",
            "#SBATCH --nodes=1",
            f"#SBATCH --ntasks={site.slots_per_node}",
            "#SBATCH --cpus-per-task=1",
            f"#SBATCH --time={site.time_limit}",
            "#SBATCH --exclusive",
            "#SBATCH --output=slurm-%j.out",
            "#SBATCH --error=slurm-%j.err",
        ]
        if site.slurm_memory is not None:
            # An exclusive allocation receives every CPU on the node even when
            # the request pool uses fewer slots.  --mem-per-cpu would therefore
            # be multiplied by the physical CPU count and can make a valid
            # one-task retry unschedulable.  Reserve the reviewed per-step
            # budget for exactly the configured slots; the launcher still
            # enforces site.slurm_memory independently on every srun step.
            directives.append(
                f"#SBATCH --mem={_allocation_memory(site.slurm_memory, site.slots_per_node)}"
            )
        for option, value in (
            ("partition", site.partition),
            ("account", site.account),
            ("qos", site.qos),
        ):
            if value:
                directives.append(f"#SBATCH --{option}={value}")
        directives.append("set -euo pipefail")
        if site.modules:
            directives.append("module load " + " ".join(site.modules))
        directives.extend(
            f"export {name}={shlex.quote(str(value))}"
            for name, value in sorted(site.environment.items())
        )
        directives.extend(
            (
                (
                    f"echo '{launcher_sha256}  portable_slurm_launcher.py' "
                    "| sha256sum --check --strict -"
                ),
                (
                    f"echo '{batch_sha256}  slurm_batch.json' "
                    "| sha256sum --check --strict -"
                ),
                (
                    f"{site.launcher_python_executable} "
                    "portable_slurm_launcher.py slurm_batch.json"
                ),
                "",
            )
        )
        (directory / "submit.sbatch").write_text(
            "\n".join(directives), encoding="utf-8", newline="\n"
        )
        submit_sha256 = sha256_file(directory / "submit.sbatch")
        submission = SlurmSubmission(
            submission_id=identifier,
            submission_directory=directory,
            request_paths=staged_paths,
            site=site,
            batch_sha256=batch_sha256,
            launcher_sha256=launcher_sha256,
            submit_sha256=submit_sha256,
            launcher_version=LAUNCHER_VERSION,
        )
        submission.write(directory / "slurm_submission.json")
        return submission

    @staticmethod
    @log_call
    def stage(
        submission: SlurmSubmission,
        transport: SlurmTransportConfig,
    ) -> SlurmSubmission:
        """Stage locally or transfer the complete bundle with rsync over SSH."""
        _validate_submission_files(submission)
        if transport.mode == "local":
            _validate_local_apptainer_paths(submission)
            staged = SlurmSubmission(
                submission_id=submission.submission_id,
                submission_directory=submission.submission_directory,
                request_paths=submission.request_paths,
                site=submission.site,
                batch_sha256=submission.batch_sha256,
                launcher_sha256=submission.launcher_sha256,
                submit_sha256=submission.submit_sha256,
                launcher_version=submission.launcher_version,
                transport=transport,
            )
            staged.write(staged.submission_directory / "slurm_submission.json")
            return staged
        remote_directory = str(
            PurePosixPath(transport.remote_scratch) / submission.submission_id
        )
        # ``mkdir`` without ``-p`` is an ownership claim: staging fails rather
        # than merging into or deleting an unproven pre-existing directory.
        mkdir = subprocess.run(
            (*_ssh_base(transport), "mkdir", remote_directory),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if mkdir.returncode != 0:
            raise RuntimeError(f"Remote staging mkdir failed: {mkdir.stderr.strip()}")
        if transport.transfer_mode == "scp":
            names = (
                "bundles",
                "portable_slurm_launcher.py",
                "slurm_batch.json",
                "submit.sbatch",
            )
            entries = [submission.submission_directory / name for name in names]
            if any(not entry.exists() or entry.is_symlink() for entry in entries):
                raise ValueError("SCP staging entries are missing or symbolic links")
            transfer = _scp_base(transport)
            transfer.extend(str(entry) for entry in entries)
            transfer.append(
                f"{transport.username}@{transport.hostname}:{remote_directory}/"
            )
        else:
            transfer = [
                transport.rsync_executable,
                "--archive",
                "--exclude=slurm_submission.json",
            ]
            if transport.port != 22 or transport.identity_file:
                remote_shell = [transport.ssh_executable, "-p", str(transport.port)]
                if transport.identity_file:
                    remote_shell.extend(("-i", transport.identity_file))
                transfer.extend(("-e", shlex.join(remote_shell)))
            transfer.extend(
                (
                    str(submission.submission_directory) + "/",
                    f"{transport.username}@{transport.hostname}:{remote_directory}/",
                )
            )
        copied = subprocess.run(
            transfer,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if copied.returncode != 0:
            raise RuntimeError(
                f"{transport.transfer_mode} staging failed: {copied.stderr.strip()}"
            )
        staged = SlurmSubmission(
            submission_id=submission.submission_id,
            submission_directory=submission.submission_directory,
            request_paths=submission.request_paths,
            site=submission.site,
            batch_sha256=submission.batch_sha256,
            launcher_sha256=submission.launcher_sha256,
            submit_sha256=submission.submit_sha256,
            launcher_version=submission.launcher_version,
            transport=transport,
            remote_directory=remote_directory,
        )
        staged.write(staged.submission_directory / "slurm_submission.json")
        return staged

    @staticmethod
    def _scheduler_command(
        submission: SlurmSubmission, executable: str, *arguments: str
    ) -> tuple[str, ...]:
        if submission.transport.mode == "local":
            return (executable, *arguments)
        return tuple((*_ssh_base(submission.transport), executable, *arguments))

    @staticmethod
    @log_call
    def submit(submission: SlurmSubmission) -> SlurmSubmission:
        """Submit a staged batch without invoking a local shell."""
        _validate_submission_files(submission)
        if submission.job_id is not None:
            raise ValueError("Submission already has a Slurm job_id")
        if submission.transport.mode == "ssh":
            if not submission.remote_directory:
                raise ValueError("SSH submission must be staged before submit")
            script = str(PurePosixPath(submission.remote_directory) / "submit.sbatch")
            command = RasSlurm._scheduler_command(
                submission,
                submission.site.sbatch_executable,
                f"--chdir={submission.remote_directory}",
                "--parsable",
                script,
            )
            cwd = None
        else:
            command = RasSlurm._scheduler_command(
                submission,
                submission.site.sbatch_executable,
                "--parsable",
                str(submission.submission_directory / "submit.sbatch"),
            )
            cwd = submission.submission_directory
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"sbatch failed: {completed.stderr.strip()}")
        job_id = completed.stdout.strip().split(";", 1)[0]
        if not re.fullmatch(r"[0-9]+", job_id):
            raise RuntimeError(f"sbatch returned an invalid job ID: {completed.stdout!r}")
        submitted = SlurmSubmission(
            submission_id=submission.submission_id,
            submission_directory=submission.submission_directory,
            request_paths=submission.request_paths,
            site=submission.site,
            batch_sha256=submission.batch_sha256,
            launcher_sha256=submission.launcher_sha256,
            submit_sha256=submission.submit_sha256,
            launcher_version=submission.launcher_version,
            transport=submission.transport,
            remote_directory=submission.remote_directory,
            job_id=job_id,
        )
        submitted.write(submitted.submission_directory / "slurm_submission.json")
        return submitted

    @staticmethod
    @log_call
    def submit_batch(
        request_paths: Sequence[Union[str, Path]],
        submission_directory: Union[str, Path],
        *,
        site: SlurmSiteConfig,
        transport: SlurmTransportConfig = SlurmTransportConfig(),
        submission_id: Optional[str] = None,
    ) -> SlurmSubmission:
        """Render, stage, and submit one exclusive-node request pool."""
        rendered = RasSlurm.render_submission(
            request_paths,
            submission_directory,
            site=site,
            submission_id=submission_id,
        )
        return RasSlurm.submit(RasSlurm.stage(rendered, transport))

    @staticmethod
    @log_call
    def status(submission: SlurmSubmission) -> SlurmStatus:
        """Read allocation and per-step state, exit, elapsed, and MaxRSS."""
        if submission.job_id is None:
            return SlurmStatus("NOT_SUBMITTED")
        command = RasSlurm._scheduler_command(
            submission,
            submission.site.sacct_executable,
            "--jobs",
            submission.job_id,
            "--noheader",
            "--parsable2",
            "--format=JobIDRaw,JobName,State,ExitCode,MaxRSS,Elapsed",
        )
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            active = subprocess.run(
                RasSlurm._scheduler_command(
                    submission,
                    submission.site.squeue_executable,
                    "--jobs",
                    submission.job_id,
                    "--noheader",
                    "--format=%T",
                ),
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
            if active.returncode == 0 and active.stdout.strip():
                return SlurmStatus(
                    allocation_state=active.stdout.strip().splitlines()[0].upper()
                )
            raise RuntimeError(
                f"sacct failed and squeue had no active job: {completed.stderr.strip()}"
            )
        records = []
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            columns = (line.split("|") + ["", "", "", "", "", ""])[:6]
            records.append(
                SlurmTaskAccounting(
                    job_id=columns[0].strip(),
                    job_name=columns[1].strip(),
                    state=columns[2].strip().split("+", 1)[0],
                    exit_code=columns[3].strip(),
                    max_rss=columns[4].strip(),
                    elapsed=columns[5].strip(),
                )
            )
        allocation = next(
            (item.state for item in records if item.job_id == submission.job_id),
            records[0].state if records else "UNKNOWN",
        )
        if not records or allocation in {"PENDING", "RUNNING", "CONFIGURING", "UNKNOWN"}:
            active = subprocess.run(
                RasSlurm._scheduler_command(
                    submission,
                    submission.site.squeue_executable,
                    "--jobs",
                    submission.job_id,
                    "--noheader",
                    "--format=%T",
                ),
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
            if active.returncode == 0 and active.stdout.strip():
                allocation = active.stdout.strip().splitlines()[0].strip().upper()
        return SlurmStatus(allocation_state=allocation, records=tuple(records))

    @staticmethod
    @log_call
    def cancel(submission: SlurmSubmission) -> bool:
        """Cancel a submitted allocation through its configured transport."""
        if submission.job_id is None:
            return False
        completed = subprocess.run(
            RasSlurm._scheduler_command(
                submission, submission.site.scancel_executable, submission.job_id
            ),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"scancel failed: {completed.stderr.strip()}")
        return True

    @staticmethod
    @log_call
    def collect(submission: SlurmSubmission) -> SlurmCollection:
        """Retrieve remote outputs only, then bind receipts to frozen requests."""
        _validate_submission_files(submission)
        receipts = {}
        errors = {}
        if submission.transport.mode == "ssh":
            if not submission.remote_directory:
                raise ValueError("SSH submission has no remote staging directory")
            for request_path in submission.request_paths:
                request = RasExecutionRequest.read(request_path)
                _, output = request.resolve_paths(request_path)
                output.mkdir(parents=True, exist_ok=True)
                remote_output = PurePosixPath(submission.remote_directory) / (
                    f"bundles/{request.execution_id}/{request.output_directory}"
                )
                remote = (
                    f"{submission.transport.username}@{submission.transport.hostname}:"
                    f"{remote_output}/"
                )
                if submission.transport.transfer_mode == "scp":
                    command = _scp_base(submission.transport)
                    command.extend((remote + ".", str(output)))
                else:
                    command = [
                        submission.transport.rsync_executable,
                        "--archive",
                        remote,
                    ]
                    if (
                        submission.transport.port != 22
                        or submission.transport.identity_file
                    ):
                        remote_shell = [
                            submission.transport.ssh_executable,
                            "-p",
                            str(submission.transport.port),
                        ]
                        if submission.transport.identity_file:
                            remote_shell.extend(
                                ("-i", submission.transport.identity_file)
                            )
                        command.extend(("-e", shlex.join(remote_shell)))
                    command.append(str(output) + "/")
                try:
                    completed = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        check=False,
                        shell=False,
                    )
                    if completed.returncode != 0:
                        errors[request.execution_id] = (
                            f"{submission.transport.transfer_mode} output collection failed: "
                            f"{completed.stderr.strip()}"
                        )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    errors[request.execution_id] = (
                        f"{submission.transport.transfer_mode} output collection failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
        for path in submission.request_paths:
            request = RasExecutionRequest.read(path)
            _, output = request.resolve_paths(path)
            receipt_path = output / "execution_receipt.json"
            try:
                expected_runtime = (
                    f"sif:sha256:{submission.site.apptainer_image_sha256}"
                )
                receipt = validate_execution_receipt(
                    path,
                    receipt_path,
                    expected_runtime_identity=expected_runtime,
                    verify_result_hdf_digest=submission.transport.mode == "ssh",
                )
                receipts[request.execution_id] = receipt
            except Exception as exc:
                receipts[request.execution_id] = None
                receipt_error = f"{type(exc).__name__}: {exc}"
                if request.execution_id in errors:
                    errors[request.execution_id] += f"; {receipt_error}"
                else:
                    errors[request.execution_id] = receipt_error
        accounting = None
        if submission.job_id:
            try:
                accounting = RasSlurm.status(submission)
            except Exception as exc:
                errors["__scheduler__"] = f"{type(exc).__name__}: {exc}"
        if accounting is not None:
            batch = json.loads(
                (submission.submission_directory / "slurm_batch.json").read_text(
                    encoding="utf-8"
                )
            )
            step_names = {
                item["execution_id"]: item["step_name"] for item in batch["steps"]
            }
            for execution_id, step_name in step_names.items():
                matches = [item for item in accounting.records if item.job_name == step_name]
                if len(matches) != 1:
                    errors[execution_id] = (
                        f"Expected exactly one scheduler record for {step_name}; "
                        f"found {len(matches)}"
                    )
                    receipts[execution_id] = None
                elif matches[0].state != "COMPLETED" or matches[0].exit_code != "0:0":
                    errors[execution_id] = (
                        f"Scheduler step {step_name} ended {matches[0].state} "
                        f"with {matches[0].exit_code}"
                    )
                    receipts[execution_id] = None
        return SlurmCollection(
            receipts=receipts, errors=errors, accounting=accounting
        )
