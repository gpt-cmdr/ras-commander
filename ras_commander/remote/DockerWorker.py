"""
DockerWorker - Docker containerized execution worker.

This module implements the DockerWorker class for executing HEC-RAS in
Docker containers using Rocky Linux 8 with native HEC-RAS 6.6 Linux binaries.

Workflow:
    1. Preprocess plan on Windows host (creates .tmp.hdf files)
    2. Execute simulation in Linux Docker container
    3. Copy results back to project folder

Prerequisites:
    1. Docker Desktop installed and running
       - Download: https://www.docker.com/products/docker-desktop
       - Ensure Linux containers mode is enabled (default)

    2. HEC-RAS 6.6 Linux binaries (not redistributable)
       - Users must obtain from HEC or build their own
       - Required structure in ras-commander-cloud repo:
         reference/Linux_RAS_v66/bin/  (RasUnsteady, RasGeomPreprocess, etc.)
         reference/Linux_RAS_v66/libs/ (Intel MKL and runtime libraries)

    3. Build the Docker image:
       cd path/to/ras-commander-cloud
       docker build -t hecras:6.6 .

       Image size: ~2.75 GB (includes full Intel MKL for AVX512 support)

Python Requirements:
    pip install ras-commander[remote-docker]
    # or: pip install docker paramiko

SSH Remote Docker Host Setup:
    For ssh:// URLs (e.g., docker_host="ssh://user@host"), you need:

    1. SSH key-based authentication (password auth NOT supported by Docker SDK)
       - Generate key: ssh-keygen -t ed25519
       - Copy to remote: ssh-copy-id user@host
       - Test: ssh user@host "docker info" (should work without password prompt)

    2. Alternative: use_ssh_client=True to use system's ssh command
       - Requires ssh client installed and configured
       - Supports more authentication options (agent, config file)

Technical Details:
    - Base image: Rocky Linux 8
    - HEC-RAS version: 6.6 (Linux native binaries)
    - Intel MKL included for optimal CPU performance (AVX512)
    - Two-step workflow required because Linux HEC-RAS has preprocessing limitations
"""

import shutil
import uuid
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Any

from .RasWorker import RasWorker
from ..LoggingConfig import get_logger
from ..Decorators import log_call
from ..RasUtils import RasUtils

logger = get_logger(__name__)


@log_call
def check_docker_dependencies():
    """
    Check if docker is available, raise clear error if not.

    This function is called lazily only when Docker functionality is actually used.
    """
    try:
        import docker
        return docker
    except ImportError:
        raise ImportError(
            "Docker worker requires docker.\n"
            "Install with: pip install ras-commander[remote-docker]\n"
            "Or: pip install docker"
        )


@dataclass
class DockerWorker(RasWorker):
    """
    Docker containerized HEC-RAS execution worker.

    Uses Rocky Linux 8 container with native HEC-RAS 6.6 Linux binaries.
    Requires two-step workflow:
        1. Preprocess on Windows (creates .tmp.hdf files)
        2. Execute simulation in Linux container

    Attributes:
        docker_image: Docker image name/tag (e.g., "hecras:6.6")
        docker_host: Docker daemon URL (None for local, or "tcp://host:2375")
        container_input_path: Mount point for project files in container
        container_output_path: Mount point for results in container
        container_script_path: Path to run_ras.sh in container
        max_runtime_minutes: Timeout for simulation (default 480 = 8 hours)
        preprocess_on_host: Whether to run preprocessing on Windows host first
        cpu_limit: CPU limit for container (e.g., "4" or "0.5")
        memory_limit: Memory limit (e.g., "8g", "4096m")

    Example:
        >>> worker = init_docker_worker(
        ...     docker_image="hecras:6.6",
        ...     cores_total=8,
        ...     cores_per_plan=4,
        ...     preprocess_on_host=True
        ... )
    """

    # Docker configuration
    docker_image: str = None
    docker_host: Optional[str] = None  # e.g., "tcp://192.168.3.8:2375"

    # Remote Docker host file staging (required when docker_host is remote)
    share_path: Optional[str] = None  # UNC path for file transfer: \\\\host\\share
    remote_staging_path: Optional[str] = None  # Path on Docker host: C:\\RasRemote

    # Container paths (Linux paths inside container)
    container_input_path: str = "/app/input"
    container_output_path: str = "/app/output"
    container_script_path: str = "/app/scripts/core_execution/run_ras.sh"

    # Execution configuration
    max_runtime_minutes: int = 480
    preprocess_on_host: bool = True

    # SSH connection options (for ssh:// docker_host URLs)
    use_ssh_client: bool = False  # If True, use system ssh command instead of paramiko
    ssh_key_path: Optional[str] = None  # Path to SSH private key (e.g., "~/.ssh/docker_worker")

    # Resource limits
    cpu_limit: Optional[str] = None  # e.g., "4" for 4 cores
    memory_limit: Optional[str] = None  # e.g., "8g" for 8GB

    # Worker configuration
    process_priority: str = "low"
    queue_priority: int = 0
    cores_total: Optional[int] = None
    cores_per_plan: int = 4
    max_parallel_plans: Optional[int] = None

    # Staging directory for local file operations (used when docker_host is local)
    staging_directory: Optional[str] = None

    def __post_init__(self):
        """Validate Docker worker configuration."""
        super().__post_init__()
        self.worker_type = "docker"

        if not self.docker_image:
            raise ValueError("docker_image is required for DockerWorker")

        # Check if this is a remote Docker host
        self._is_remote = bool(self.docker_host and not self.docker_host.startswith("unix:"))

        # Validate remote Docker configuration
        if self._is_remote:
            if not self.share_path:
                raise ValueError(
                    "share_path is required for remote Docker hosts. "
                    "Example: '\\\\\\\\192.168.3.8\\\\RasRemote'"
                )
            if not self.remote_staging_path:
                raise ValueError(
                    "remote_staging_path is required for remote Docker hosts. "
                    "Example: 'C:\\\\RasRemote'"
                )

        # Calculate parallel capacity
        if self.cores_total is not None and self.cores_per_plan:
            self.max_parallel_plans = max(1, self.cores_total // self.cores_per_plan)
        elif self.max_parallel_plans is None:
            self.max_parallel_plans = 1

        # Set default staging directory for local Docker
        if self.staging_directory is None:
            import tempfile
            self.staging_directory = tempfile.gettempdir()

        logger.debug(f"DockerWorker initialized: image={self.docker_image}, "
                    f"host={self.docker_host or 'local'}, remote={self._is_remote}, "
                    f"max_parallel={self.max_parallel_plans}")


@log_call
def init_docker_worker(**kwargs) -> DockerWorker:
    """
    Initialize and validate a Docker worker.

    Args:
        docker_image: Docker image with HEC-RAS Linux (required, e.g., "hecras:6.6")
        docker_host: Docker daemon URL (optional, default: local)
            For remote TCP: "tcp://192.168.3.8:2375"
            For remote SSH: "ssh://user@192.168.3.8" (requires key-based auth)
        share_path: UNC path for file transfer to remote Docker host (required for remote)
            Example: "\\\\\\\\192.168.3.8\\\\RasRemote"
        remote_staging_path: Path on Docker host for volume mounts (required for remote)
            Example: "C:\\\\RasRemote" or "/mnt/c/RasRemote" (WSL paths)
        worker_id: Custom worker ID (auto-generated if not provided)
        cores_total: Total CPU cores available for this worker
        cores_per_plan: CPU cores to allocate per plan
        max_runtime_minutes: Simulation timeout (default: 480)
        preprocess_on_host: Run Windows preprocessing first (default: True)
        use_ssh_client: Use system ssh command instead of paramiko (default: False)
            Set True if you want to use SSH agent or ~/.ssh/config settings
        ssh_key_path: Path to SSH private key for authentication (e.g., "~/.ssh/docker_worker")
            Only used with ssh:// docker_host URLs. Supports ~ expansion.
        cpu_limit: Container CPU limit (e.g., "4" for 4 cores)
        memory_limit: Container memory limit (e.g., "8g")
        **kwargs: Additional DockerWorker parameters

    Returns:
        DockerWorker: Validated worker instance

    Raises:
        ImportError: If docker package not installed
        ValueError: If validation fails
        docker.errors.DockerException: If Docker daemon unreachable

    Example (local Docker):
        >>> worker = init_docker_worker(
        ...     docker_image="hecras:6.6",
        ...     cores_total=8,
        ...     cores_per_plan=4
        ... )

    Example (remote Docker via SSH):
        >>> worker = init_docker_worker(
        ...     docker_image="hecras:6.6",
        ...     docker_host="ssh://user@192.168.3.8",
        ...     share_path="\\\\\\\\192.168.3.8\\\\RasRemote",
        ...     remote_staging_path="/mnt/c/RasRemote",
        ...     use_ssh_client=True,  # Use system ssh command
        ...     cores_total=8,
        ...     cores_per_plan=4
        ... )
    """
    docker = check_docker_dependencies()

    kwargs['worker_type'] = 'docker'

    # Default ras_exe_path for Linux container
    if 'ras_exe_path' not in kwargs:
        kwargs['ras_exe_path'] = '/app/bin/RasUnsteady'

    worker = DockerWorker(**kwargs)

    # Check if SSH-based connection and paramiko availability
    is_ssh_host = worker.docker_host and worker.docker_host.startswith("ssh://")

    if is_ssh_host and not worker.use_ssh_client:
        # Check if paramiko is available for native SSH transport
        try:
            import paramiko
            logger.debug("paramiko available for SSH transport")
        except ImportError:
            raise ImportError(
                "SSH Docker connections require paramiko.\n"
                "Install with: pip install paramiko\n"
                "Or use use_ssh_client=True to use system ssh command instead.\n"
                "\n"
                "IMPORTANT: SSH key-based authentication is required.\n"
                "Password authentication is NOT supported by Docker SDK.\n"
                "Setup: ssh-keygen && ssh-copy-id user@host\n"
                "Test: ssh user@host 'docker info' (must work without password)"
            )

    # Handle SSH key path configuration
    if is_ssh_host and worker.ssh_key_path:
        import os
        # Expand ~ in path
        expanded_key_path = os.path.expanduser(worker.ssh_key_path)

        if worker.use_ssh_client:
            # For system SSH client, recommend ~/.ssh/config instead
            logger.debug(f"SSH key path specified: {worker.ssh_key_path}")
            logger.debug("When use_ssh_client=True, configure the key in ~/.ssh/config:")
            logger.debug(f"  Host {worker.docker_host.split('@')[-1] if '@' in worker.docker_host else 'your-host'}")
            logger.debug(f"    IdentityFile {expanded_key_path}")
        else:
            # For paramiko, set SSH_AUTH_SOCK or use paramiko's key loading
            # The Docker SDK will look in standard locations and SSH agent
            logger.debug(f"SSH key path: {expanded_key_path}")
            if not os.path.exists(expanded_key_path):
                logger.warning(f"SSH key file not found: {expanded_key_path}")
            else:
                # Set environment variable for paramiko to find the key
                # This is a workaround since Docker SDK doesn't expose key_filename param
                os.environ.setdefault('DOCKER_SSH_KEY_FILE', expanded_key_path)
                logger.debug("SSH key will be loaded via paramiko")

    # Verify Docker daemon connectivity
    try:
        if worker.docker_host:
            client_kwargs = {"base_url": worker.docker_host}
            if worker.use_ssh_client:
                client_kwargs["use_ssh_client"] = True
                logger.debug("Using system ssh client for Docker connection")
            client = docker.DockerClient(**client_kwargs)
        else:
            client = docker.from_env()

        client.ping()
        logger.info("Docker daemon connected")
        logger.debug(f"Docker daemon host: {worker.docker_host or 'local'}")

        # Check if image exists
        try:
            client.images.get(worker.docker_image)
            logger.info(f"Docker image found: {worker.docker_image}")
        except docker.errors.ImageNotFound:
            logger.warning(f"Docker image not found: {worker.docker_image}")
            logger.warning("Image must be built or pulled before execution")

        client.close()

    except docker.errors.DockerException as e:
        error_msg = str(e)

        # Provide helpful error messages for common SSH issues
        if is_ssh_host:
            if "paramiko" in error_msg.lower():
                raise ImportError(
                    f"SSH connection failed - paramiko issue: {e}\n"
                    "Install paramiko: pip install paramiko\n"
                    "Or set use_ssh_client=True in your worker config"
                )
            elif "authentication" in error_msg.lower() or "permission" in error_msg.lower():
                raise ConnectionError(
                    f"SSH authentication failed: {e}\n"
                    "Docker SDK requires SSH key-based authentication.\n"
                    "Password auth is NOT supported.\n"
                    "\n"
                    "Setup SSH keys:\n"
                    "  1. ssh-keygen -t ed25519\n"
                    "  2. ssh-copy-id user@host\n"
                    "  3. Test: ssh user@host 'docker info'\n"
                    "\n"
                    "Or try use_ssh_client=True to use system ssh command"
                )

        logger.error(f"Cannot connect to Docker daemon: {e}")
        raise

    host_scope = "remote" if worker._is_remote else "local"
    logger.info(
        "Docker worker configured: "
        f"image={worker.docker_image}, host={host_scope}, "
        f"preprocess_on_host={worker.preprocess_on_host}, "
        f"slots={worker.max_parallel_plans}, "
        f"timeout={worker.max_runtime_minutes} min"
    )
    logger.debug(f"Docker worker host: {worker.docker_host or 'local'}")
    logger.debug(f"Docker container input path: {worker.container_input_path}")
    logger.debug(f"Docker container output path: {worker.container_output_path}")
    logger.debug(f"Docker container script path: {worker.container_script_path}")
    if is_ssh_host:
        logger.debug(f"Docker SSH client: {'system' if worker.use_ssh_client else 'paramiko'}")
        if worker.ssh_key_path:
            logger.debug(f"Docker SSH key path: {worker.ssh_key_path}")

    return worker


@log_call
def execute_docker_plan(
    worker: DockerWorker,
    plan_number: str,
    ras_obj,
    num_cores: int,
    clear_geompre: bool,
    sub_worker_id: int = 1,
    autoclean: bool = True
) -> bool:
    """
    Execute a HEC-RAS plan in a Linux Docker container.

    Two-step workflow:
        1. Preprocess on Windows host (if preprocess_on_host=True)
        2. Run simulation in Linux container

    Args:
        worker: DockerWorker instance
        plan_number: Plan number to execute (e.g., "01")
        ras_obj: RasPrj object with project information
        num_cores: Number of cores for simulation
        clear_geompre: Whether to clear geometry preprocessor files
        sub_worker_id: Sub-worker identifier for parallel execution
        autoclean: Remove staging files after completion

    Returns:
        bool: True if execution succeeded, False otherwise
    """
    docker = check_docker_dependencies()

    # CRITICAL: Capture project info at the START of execution
    # This prevents issues if another thread modifies ras_obj during execution
    # (e.g., via init_ras_project calls in preprocessing)
    project_folder = Path(ras_obj.project_folder)
    project_name = ras_obj.project_name
    ras_version = ras_obj.ras_version

    # Validate project folder exists before proceeding
    if not project_folder.exists():
        logger.error(f"Project folder does not exist: {project_folder}")
        logger.error("This may indicate a thread-safety issue with ras_obj modification")
        return False

    logger.info(f"Starting Docker execution: plan {plan_number}, sub-worker {sub_worker_id}")

    # Create staging directory
    # For remote Docker hosts: preprocess LOCALLY first, then copy to remote share
    # For local Docker hosts: use staging_directory for both
    staging_id = f"ras_docker_{project_name}_p{plan_number}_sw{sub_worker_id}_{uuid.uuid4().hex[:8]}"

    # Import tempfile for local preprocessing
    import tempfile

    if worker._is_remote:
        # Remote Docker: preprocess locally, then copy to remote share
        local_preprocess_base = Path(tempfile.gettempdir())  # Local temp for preprocessing
        remote_staging_base = Path(worker.share_path)  # UNC path for remote file access
        docker_staging_base = Path(worker.remote_staging_path)  # Path on Docker host for mounts
        logger.info(f"Remote Docker staging configured for plan {plan_number}")
        logger.debug(f"Remote Docker host: {worker.docker_host}")
        logger.debug(f"Local preprocessing staging base: {local_preprocess_base}")
        logger.debug(f"Remote share staging base: {worker.share_path}")
        logger.debug(f"Docker mount staging base: {worker.remote_staging_path}")
    else:
        # Local Docker: same path for both
        local_preprocess_base = Path(worker.staging_directory)
        remote_staging_base = None  # Not used for local Docker
        docker_staging_base = Path(worker.staging_directory)

    # Local preprocessing paths (for HEC-RAS preprocessing on this machine)
    local_staging_folder = local_preprocess_base / staging_id
    local_input_staging = local_staging_folder / "input"
    local_output_staging = local_staging_folder / "output"

    # Remote staging paths (for Docker execution on remote host)
    if worker._is_remote:
        remote_staging_folder = remote_staging_base / staging_id
        remote_input_staging = remote_staging_folder / "input"
        remote_output_staging = remote_staging_folder / "output"
    else:
        remote_staging_folder = local_staging_folder
        remote_input_staging = local_input_staging
        remote_output_staging = local_output_staging

    # Docker mount paths (as seen by Docker daemon on the host)
    docker_staging_folder = docker_staging_base / staging_id
    docker_input_path = docker_staging_folder / "input"
    docker_output_path = docker_staging_folder / "output"

    # For result collection - use remote paths for remote Docker, local paths for local Docker
    input_staging = remote_input_staging if worker._is_remote else local_input_staging
    output_staging = remote_output_staging if worker._is_remote else local_output_staging

    try:
        # Create local staging for preprocessing
        local_staging_folder.mkdir(parents=True, exist_ok=True)
        local_input_staging.mkdir(parents=True, exist_ok=True)
        local_output_staging.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created local staging: {local_staging_folder}")

        # Copy project to LOCAL staging (for preprocessing)
        logger.info(f"Copying project to local staging for preprocessing...")
        for item in project_folder.iterdir():
            if RasUtils.is_windows_reserved_name(item.name):
                continue
            if item.is_file():
                shutil.copy2(item, local_input_staging / item.name)
            elif item.is_dir():
                shutil.copytree(item, local_input_staging / item.name, dirs_exist_ok=True, ignore=RasUtils.ignore_windows_reserved)

        # Step 1: Preprocess on Windows LOCALLY (if enabled)
        if worker.preprocess_on_host:
            logger.info(f"Running preprocessing locally (not on network share)...")
            from ..RasPreprocess import RasPreprocess
            from ..RasPrj import RasPrj, init_ras_project
            temp_ras = RasPrj()
            init_ras_project(str(local_input_staging), ras_obj.ras_version, ras_object=temp_ras)
            preprocess_result = RasPreprocess.preprocess_plan(plan_number, ras_object=temp_ras)
            if not preprocess_result:
                logger.error(f"Windows preprocessing failed: {preprocess_result.error}")
                return False

        # Step 1.5: For remote Docker, copy preprocessed files to remote share
        if worker._is_remote:
            logger.info(f"Copying preprocessed files to remote share...")
            remote_staging_folder.mkdir(parents=True, exist_ok=True)
            remote_input_staging.mkdir(parents=True, exist_ok=True)
            remote_output_staging.mkdir(parents=True, exist_ok=True)

            for item in local_input_staging.iterdir():
                if RasUtils.is_windows_reserved_name(item.name):
                    continue
                if item.is_file():
                    shutil.copy2(item, remote_input_staging / item.name)
                elif item.is_dir():
                    shutil.copytree(item, remote_input_staging / item.name, dirs_exist_ok=True, ignore=RasUtils.ignore_windows_reserved)
            logger.info("Preprocessed files copied to remote Docker staging")
            logger.debug(f"Remote Docker staging folder: {remote_staging_folder}")

        # Extract geometry number
        from ..RasPreprocess import RasPreprocess
        plan_pattern = f"*.p{plan_number}"
        plan_files = list(input_staging.glob(plan_pattern))
        if plan_files:
            geometry_number = RasPreprocess._extract_geometry_number(plan_files[0])
        else:
            geometry_number = None
        if not geometry_number:
            logger.error(
                f"Could not extract geometry number for plan {plan_number}; "
                f"searched pattern '{plan_pattern}' in {input_staging}"
            )
            return False

        logger.info(f"Plan {plan_number} uses geometry {geometry_number}")

        # Step 2: Run in Docker container
        if worker.docker_host:
            client_kwargs = {"base_url": worker.docker_host}
            if worker.use_ssh_client:
                client_kwargs["use_ssh_client"] = True
            client = docker.DockerClient(**client_kwargs)
        else:
            client = docker.from_env()

        # Volume mounts - use Docker host paths (not local paths for remote Docker)
        # Convert paths to Docker Desktop compatible format
        # WSL-style paths like /mnt/c/... need to be converted to C:/... for Docker Desktop
        def convert_to_docker_path(path_str):
            """Convert WSL-style or Windows paths to Docker Desktop format."""
            path_str = str(path_str).replace('\\', '/')
            # Convert /mnt/c/... to C:/...
            import re
            match = re.match(r'^/mnt/([a-zA-Z])/(.*)$', path_str)
            if match:
                drive = match.group(1).upper()
                rest = match.group(2)
                return f"{drive}:/{rest}"
            return path_str

        input_path = convert_to_docker_path(docker_input_path)
        output_path = convert_to_docker_path(docker_output_path)
        logger.debug(f"Docker mount paths: input={input_path}, output={output_path}")

        volumes = {
            input_path: {'bind': worker.container_input_path, 'mode': 'rw'},
            output_path: {'bind': worker.container_output_path, 'mode': 'rw'},
        }

        # Environment variables
        environment = {
            'MAX_RUNTIME_MINUTES': str(worker.max_runtime_minutes),
            'GEOMETRY_NUMBER': geometry_number,
        }

        # Container configuration
        container_kwargs = {
            'image': worker.docker_image,
            'command': [worker.container_script_path, str(int(plan_number))],
            'volumes': volumes,
            'environment': environment,
            'detach': True,
            'remove': False,
        }

        if worker.cpu_limit:
            container_kwargs['nano_cpus'] = int(float(worker.cpu_limit) * 1e9)
        if worker.memory_limit:
            container_kwargs['mem_limit'] = worker.memory_limit

        logger.info(f"Starting container: {worker.docker_image}")
        container = client.containers.run(**container_kwargs)
        container_id = container.short_id
        logger.info(f"Container started: {container_id}")

        # Wait for completion
        timeout_seconds = worker.max_runtime_minutes * 60
        start_time = time.time()

        try:
            result = container.wait(timeout=timeout_seconds)
            exit_code = result.get('StatusCode', -1)
            elapsed = time.time() - start_time

            logger.info(f"Container finished in {elapsed:.1f}s, exit code {exit_code}")

            logs = container.logs(stdout=True, stderr=True).decode('utf-8', errors='replace')
            if exit_code != 0:
                log_lines = logs.splitlines()
                if log_lines:
                    tail_lines = log_lines[-40:]
                    logger.error(
                        f"Container failed with exit code {exit_code}; "
                        f"last {len(tail_lines)} of {len(log_lines)} log line(s):\n"
                        + "\n".join(tail_lines)
                    )
                else:
                    logger.error(f"Container failed with exit code {exit_code}; no container logs captured")
                logger.debug(f"Full container logs:\n{logs}")
            else:
                logger.debug(f"Container logs:\n{logs}")

        except Exception as e:
            logger.error(f"Container execution failed: {e}")
            try:
                container.kill()
            except:
                pass
            return False
        finally:
            try:
                container.remove()
            except:
                pass
            client.close()

        if exit_code != 0:
            logger.debug(f"Simulation failed with exit code {exit_code}")
            return False

        # Copy results back
        # Look for HDF results in both output and input staging
        result_patterns = [
            f"{project_name}.p{plan_number}*.hdf",
            f"{project_name}.p{plan_number}.tmp.hdf",
        ]

        result_files = []
        for pattern in result_patterns:
            result_files.extend(output_staging.glob(pattern))
            result_files.extend(input_staging.glob(pattern))

        # Remove duplicates
        result_files = list(set(result_files))

        if not result_files:
            logger.error(
                f"No HDF results found for plan {plan_number}; "
                f"searched patterns {result_patterns} in output_staging={output_staging} "
                f"and input_staging={input_staging}"
            )
            return False

        for result_file in result_files:
            dest_file = project_folder / result_file.name
            logger.info(f"Copying result: {result_file.name}")
            shutil.copy2(result_file, dest_file)

        # Copy log files
        for log_pattern in ["*.log", "*.computeMsgs.txt", "ras_execution.log"]:
            for log_file in output_staging.glob(log_pattern):
                shutil.copy2(log_file, project_folder / log_file.name)
            for log_file in input_staging.glob(log_pattern):
                if not (project_folder / log_file.name).exists():
                    shutil.copy2(log_file, project_folder / log_file.name)

        logger.info(f"Docker execution completed for plan {plan_number}")
        return True

    except Exception as e:
        logger.error(f"Docker execution error: {e}", exc_info=True)
        return False

    finally:
        if autoclean and local_staging_folder.exists():
            try:
                shutil.rmtree(local_staging_folder, ignore_errors=True)
                logger.debug(f"Cleaned up staging: {local_staging_folder}")
            except:
                pass
        elif not autoclean:
            logger.info(
                f"Preserving Docker staging for plan {plan_number} for debugging; "
                "enable DEBUG logging for the path"
            )
            logger.debug(f"Preserved Docker staging folder: {local_staging_folder}")
