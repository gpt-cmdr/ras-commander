"""Docker adapter for portable, one-core steady-plan execution requests.

This class is intentionally separate from the native-unsteady
:class:`ras_commander.RasDocker` API. A later integration may delegate to this
adapter without changing either public method contract.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Mapping, Optional, Sequence, Union

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .ExecutionContract import (
    RasExecutionReceipt,
    RasExecutionRequest,
    validate_execution_receipt,
)


logger = get_logger(__name__)


def _oci_reference(identity: str) -> str:
    """Return the already validated Docker-usable immutable reference."""

    if identity.startswith("sif:sha256:"):
        raise ValueError("Docker execution requires an immutable OCI reference, not a SIF digest")
    return identity


def _container_name(request: RasExecutionRequest) -> str:
    """Return a deterministic daemon-visible name safe for timeout cleanup."""
    return f"ras-portable-{request.execution_id}-{request.digest[:12]}"


def _inspect_docker_image(
    docker_executable: str, image: str, *, pull: str
) -> None:
    """Require Docker to report the exact requested immutable RepoDigest."""
    inspect_command = (
        docker_executable,
        "image",
        "inspect",
        "--format={{json .RepoDigests}}",
        image,
    )
    inspected = subprocess.run(
        inspect_command,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=60,
    )
    if inspected.returncode != 0 and pull != "never":
        pulled = subprocess.run(
            (docker_executable, "pull", image),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=600,
        )
        if pulled.returncode != 0:
            raise RuntimeError(f"Docker could not pull immutable image: {pulled.stderr}")
        inspected = subprocess.run(
            inspect_command,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=60,
        )
    if inspected.returncode != 0:
        raise RuntimeError(f"Docker image inspection failed: {inspected.stderr}")
    try:
        repo_digests = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Docker image inspection returned invalid RepoDigests") from exc
    if not isinstance(repo_digests, list) or image not in repo_digests:
        raise RuntimeError(
            "Docker inspected RepoDigests do not contain the requested immutable image"
        )


def _cleanup_container(docker_executable: str, name: str) -> Optional[str]:
    """Force-remove a timed-out container and verify it is no longer present."""
    try:
        removed = subprocess.run(
            (docker_executable, "rm", "--force", name),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"cleanup invocation failed: {type(exc).__name__}: {exc}"
    if removed.returncode != 0:
        return f"cleanup failed: {removed.stderr.strip()}"
    try:
        inspected = subprocess.run(
            (docker_executable, "container", "inspect", name),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"cleanup verification failed: {type(exc).__name__}: {exc}"
    if inspected.returncode == 0:
        return "cleanup verification found the timed-out container still present"
    return None


@dataclass(frozen=True)
class PortableDockerExecutionResult:
    """Docker process evidence and the container's hydraulic receipt."""

    execution_id: str
    success: bool
    returncode: Optional[int]
    command: tuple[str, ...]
    receipt: Optional[RasExecutionReceipt] = None
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success


@dataclass(frozen=True)
class PortableDockerPoolResult:
    """Results keyed by globally unique ``execution_id`` values."""

    results: Mapping[str, PortableDockerExecutionResult]

    @property
    def success(self) -> bool:
        return all(result.success for result in self.results.values())

    def __bool__(self) -> bool:
        return self.success


def _mount(source: Path, target: str, *, readonly: bool = False) -> str:
    text = str(source.resolve())
    if "," in text:
        raise ValueError("Docker --mount source paths cannot contain commas")
    suffix = ",readonly" if readonly else ""
    return f"type=bind,source={text},target={target}{suffix}"


def _overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left in right.parents or right in left.parents


def _preflight_pool(paths: Sequence[Path]) -> None:
    resolved = []
    for path in paths:
        request = RasExecutionRequest.read(path)
        source, output = request.resolve_paths(path)
        resolved.append((request.execution_id, source.parent.resolve(), output.resolve()))
    outputs = [item[2] for item in resolved]
    if len(outputs) != len(set(outputs)):
        raise ValueError("Pooled output directories must be unique")
    for index, (execution_id, _, output) in enumerate(resolved):
        for other_id, source_tree, _ in resolved:
            if _overlap(output, source_tree):
                raise ValueError(
                    f"Output for {execution_id} overlaps source tree for {other_id}"
                )
        for other in outputs[index + 1 :]:
            if _overlap(output, other):
                raise ValueError("Pooled output directories cannot overlap")


class RasPortableDocker:
    """Static Docker execution API for independent prepared projects."""

    @staticmethod
    @log_call
    def build_execute_command(
        request_path: Union[str, Path],
        *,
        image: Optional[str] = None,
        docker_executable: str = "docker",
        python_executable: str = "python",
        memory: Optional[str] = None,
        pull: str = "missing",
        security_options: Sequence[str] = (),
    ) -> tuple[str, ...]:
        """Render a shell-free, one-CPU Docker command for one request bundle.

        The bundle directory is mounted read-only at ``/job`` and only the
        request's output directory is mounted writable. The output directory
        is created (empty) as a side effect.

        Args:
            request_path (Union[str, Path]): ``request.json`` inside its bundle.
            image (Optional[str]): Image to run. Must equal the request's
                immutable OCI ``container_identity``; defaults to it.
            docker_executable (str): Docker CLI executable.
            python_executable (str): Python executable inside the image.
            memory (Optional[str]): Optional Docker ``--memory`` limit.
            pull (str): Docker ``--pull`` policy: ``always``, ``missing``, or
                ``never``.
            security_options (Sequence[str]): Docker ``--security-opt``
                values, one flag each, for example ``apparmor=unconfined``
                on hosts whose default AppArmor profile blocks Wine.

        Returns:
            tuple[str, ...]: The Docker argument vector.

        Raises:
            ValueError: If the image differs from ``container_identity``, the
                identity is a SIF digest, the output directory is not empty,
                a mount path contains a comma, the source project is missing,
                or ``security_options`` is a bare string or holds an empty
                option.
        """
        request_file = Path(request_path).resolve()
        request = RasExecutionRequest.read(request_file)
        source, output = request.resolve_paths(request_file)
        expected_image = _oci_reference(request.container_identity)
        selected_image = image or expected_image
        if selected_image != expected_image:
            raise ValueError(
                "Docker image must exactly match request.container_identity"
            )
        if not docker_executable or not python_executable:
            raise ValueError("Docker and container Python executables are required")
        if pull not in {"always", "missing", "never"}:
            raise ValueError("pull must be 'always', 'missing', or 'never'")
        if memory is not None and not memory.strip():
            raise ValueError("memory must be a non-empty Docker memory limit")

        if output.exists() and any(output.iterdir()):
            raise ValueError("Docker output directory must be absent or empty")
        output.mkdir(parents=True, exist_ok=True)
        bundle = request_file.parent
        request_relative = request_file.relative_to(bundle).as_posix()
        output_target = "/job/" + request.output_directory
        command = [
            docker_executable,
            "run",
            "--rm",
            "--name",
            _container_name(request),
            "--pull",
            pull,
            "--cpus",
            "1",
            "--env",
            f"RAS_COMMANDER_RUNTIME_CONTAINER_IDENTITY={request.container_identity}",
            "--mount",
            _mount(bundle, "/job", readonly=True),
            "--mount",
            _mount(output, output_target),
        ]
        if memory is not None:
            command.extend(("--memory", memory))
        if isinstance(security_options, (str, bytes)):
            raise ValueError(
                "security_options must be a sequence of options, not one string"
            )
        for option in security_options:
            if not str(option).strip():
                raise ValueError("security options must be non-empty strings")
            command.extend(("--security-opt", str(option)))
        # Name the executable as the entrypoint. An image's own ENTRYPOINT would
        # otherwise be prepended to these arguments; Apptainer's exec ignores
        # it, Docker does not.
        command.extend(
            (
                "--entrypoint",
                python_executable,
                selected_image,
                "-m",
                "ras_commander.remote.execute_request",
                "execute-request",
                f"/job/{request_relative}",
            )
        )
        # Resolve here so a missing source fails before Docker is started.
        if not source.is_file():
            raise ValueError(f"Missing source project: {source}")
        return tuple(command)

    @staticmethod
    @log_call
    def execute_request(
        request_path: Union[str, Path],
        *,
        image: Optional[str] = None,
        docker_executable: str = "docker",
        python_executable: str = "python",
        memory: Optional[str] = None,
        pull: str = "missing",
        security_options: Sequence[str] = (),
    ) -> PortableDockerExecutionResult:
        """Run one request in Docker and load its hydraulic receipt.

        Docker receives one CPU.  The bundle is mounted read-only with only the
        declared output directory over-mounted writable.  The input model is
        therefore immutable at both the host contract and container boundary.
        """
        request_file = Path(request_path).resolve()
        request = RasExecutionRequest.read(request_file)
        command = RasPortableDocker.build_execute_command(
            request_file,
            image=image,
            docker_executable=docker_executable,
            python_executable=python_executable,
            memory=memory,
            pull=pull,
            security_options=security_options,
        )
        _, output = request.resolve_paths(request_file)
        receipt_path = output / "execution_receipt.json"
        try:
            selected_image = image or _oci_reference(request.container_identity)
            _inspect_docker_image(docker_executable, selected_image, pull=pull)
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=request.execution_timeout_seconds + 120,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            cleanup_error = _cleanup_container(
                docker_executable, _container_name(request)
            )
            return PortableDockerExecutionResult(
                execution_id=request.execution_id,
                success=False,
                returncode=None,
                command=command,
                error=(
                    f"{type(exc).__name__}: {exc}"
                    + (f"; {cleanup_error}" if cleanup_error else "")
                ),
            )
        except OSError as exc:
            return PortableDockerExecutionResult(
                execution_id=request.execution_id,
                success=False,
                returncode=None,
                command=command,
                error=f"{type(exc).__name__}: {exc}",
            )

        receipt = None
        receipt_error = None
        if receipt_path.is_file():
            try:
                receipt = validate_execution_receipt(
                    request_file,
                    receipt_path,
                    expected_runtime_identity=request.container_identity,
                )
            except Exception as exc:
                receipt = None
                receipt_error = f"Invalid execution receipt: {exc}"
        else:
            receipt_error = f"Container did not produce {receipt_path}"

        success = bool(completed.returncode == 0 and receipt and receipt.success)
        return PortableDockerExecutionResult(
            execution_id=request.execution_id,
            success=success,
            returncode=completed.returncode,
            command=command,
            receipt=receipt,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error=None if success else receipt_error or "Container execution failed",
        )

    @staticmethod
    @log_call
    def execute_pool(
        request_paths: Sequence[Union[str, Path]],
        *,
        max_concurrent: int = 8,
        image: Optional[str] = None,
        docker_executable: str = "docker",
        python_executable: str = "python",
        memory: Optional[str] = None,
        pull: str = "missing",
        security_options: Sequence[str] = (),
    ) -> PortableDockerPoolResult:
        """Execute independent project requests with bounded concurrency.

        Args:
            request_paths (Sequence[Union[str, Path]]): Request files; each
                ``execution_id`` and output directory must be unique and no
                output may overlap any request's source tree.
            max_concurrent (int): Containers run at once (1-256).
            image, docker_executable, python_executable, memory, pull,
                security_options: Passed to :meth:`execute_request` for every
                request.

        Returns:
            PortableDockerPoolResult: Results keyed by ``execution_id`` in
            request order. A request that raises is recorded as a failed
            result rather than aborting the pool.

        Raises:
            ValueError: If ``max_concurrent`` is out of range, execution IDs
                repeat, or output directories collide or overlap sources.
        """
        if not isinstance(max_concurrent, int) or not 1 <= max_concurrent <= 256:
            raise ValueError("max_concurrent must be an integer from 1 through 256")
        paths = [Path(path).resolve() for path in request_paths]
        requests = [RasExecutionRequest.read(path) for path in paths]
        execution_ids = [request.execution_id for request in requests]
        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("Every pooled request must have a unique execution_id")
        _preflight_pool(paths)

        unordered = {}
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {
                executor.submit(
                    RasPortableDocker.execute_request,
                    path,
                    image=image,
                    docker_executable=docker_executable,
                    python_executable=python_executable,
                    memory=memory,
                    pull=pull,
                    security_options=security_options,
                ): request.execution_id
                for path, request in zip(paths, requests)
            }
            for future in as_completed(futures):
                execution_id = futures[future]
                try:
                    unordered[execution_id] = future.result()
                except Exception as exc:
                    unordered[execution_id] = PortableDockerExecutionResult(
                        execution_id=execution_id,
                        success=False,
                        returncode=None,
                        command=(),
                        error=f"{type(exc).__name__}: {exc}",
                    )
        ordered = {
            execution_id: unordered[execution_id] for execution_id in execution_ids
        }
        return PortableDockerPoolResult(results=ordered)
