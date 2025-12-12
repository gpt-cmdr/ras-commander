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

logger = get_logger(__name__)


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
            logger.info(f"SSH key path specified: {worker.ssh_key_path}")
            logger.info("Note: When use_ssh_client=True, configure the key in ~/.ssh/config:")
            logger.info(f"  Host {worker.docker_host.split('@')[-1] if '@' in worker.docker_host else 'your-host'}")
            logger.info(f"    IdentityFile {expanded_key_path}")
        else:
            # For paramiko, set SSH_AUTH_SOCK or use paramiko's key loading
            # The Docker SDK will look in standard locations and SSH agent
            logger.info(f"SSH key path: {expanded_key_path}")
            if not os.path.exists(expanded_key_path):
                logger.warning(f"SSH key file not found: {expanded_key_path}")
            else:
                # Set environment variable for paramiko to find the key
                # This is a workaround since Docker SDK doesn't expose key_filename param
                os.environ.setdefault('DOCKER_SSH_KEY_FILE', expanded_key_path)
                logger.info("SSH key will be loaded via paramiko")

    # Verify Docker daemon connectivity
    try:
        if worker.docker_host:
            client_kwargs = {"base_url": worker.docker_host}
            if worker.use_ssh_client:
                client_kwargs["use_ssh_client"] = True
                logger.info("Using system ssh client for Docker connection")
            client = docker.DockerClient(**client_kwargs)
        else:
            client = docker.from_env()

        client.ping()
        logger.info(f"Docker daemon connected: {worker.docker_host or 'local'}")

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

    logger.info(f"DockerWorker initialized:")
    logger.info(f"  Image: {worker.docker_image}")
    logger.info(f"  Host: {worker.docker_host or 'local'}")
    logger.info(f"  Preprocess on host: {worker.preprocess_on_host}")
    logger.info(f"  Max parallel plans: {worker.max_parallel_plans}")
    logger.info(f"  Timeout: {worker.max_runtime_minutes} minutes")
    if is_ssh_host:
        logger.info(f"  SSH client: {'system' if worker.use_ssh_client else 'paramiko'}")
        if worker.ssh_key_path:
            logger.info(f"  SSH key: {worker.ssh_key_path}")

    return worker


def _extract_geometry_number(project_path: Path, plan_number: str) -> Optional[str]:
    """
    Extract geometry file number from plan file.

    HEC-RAS plan files reference geometry files with "Geom File=gXX" syntax.
    The geometry number is DIFFERENT from the plan number.

    Args:
        project_path: Path to project folder
        plan_number: Plan number (e.g., "01")

    Returns:
        Geometry number as string (e.g., "13") or None if not found
    """
    plan_files = list(project_path.glob(f"*.p{plan_number}"))
    if not plan_files:
        return None

    plan_file = plan_files[0]
    try:
        with open(plan_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if line.strip().startswith("Geom File="):
                    geom_ref = line.split('=')[1].strip()
                    if geom_ref.startswith('g'):
                        return geom_ref[1:]
        return None
    except Exception as e:
        logger.error(f"Error reading plan file {plan_file}: {e}")
        return None


def _preprocess_plan_for_linux(
    ras_obj,
    plan_number: str,
    project_staging: Path,
    max_wait: int = 300
) -> bool:
    """
    Preprocess a plan on Windows to create files needed for Linux execution.

    This runs HEC-RAS on Windows with EARLY TERMINATION to generate:
    - .tmp.hdf file (preprocessed geometry and initial conditions)
    - .b file (binary geometry)
    - .x file (execution file)

    Detection Method:
    The process is killed when the .bcoXX file (detailed log) contains
    "Starting Unsteady Flow Computations", indicating preprocessing is complete
    and the actual simulation is about to begin.

    To enable .bco file creation, "Write Detailed= 1" is set in the plan file.

    Args:
        ras_obj: RasPrj object
        plan_number: Plan number to preprocess
        project_staging: Path to staged project copy
        max_wait: Maximum seconds to wait for preprocessing to complete

    Returns:
        bool: True if preprocessing succeeded
    """
    import subprocess
    import psutil

    try:
        # Import here to avoid circular imports
        from ..RasPrj import init_ras_project, RasPrj
        from ..RasGeo import RasGeo
        from ..RasPlan import RasPlan

        # Initialize the staged project with a NEW RasPrj instance
        # CRITICAL: Pass ras_object to avoid modifying the global ras object
        # This is required for thread-safety when running multiple plans in parallel
        temp_ras = RasPrj()
        init_ras_project(str(project_staging), ras_obj.ras_version, ras_object=temp_ras)
        project_name = temp_ras.project_name

        logger.info(f"Preprocessing plan {plan_number} for Linux execution...")

        # Clear geometry preprocessor files
        logger.debug("Clearing geometry preprocessor files...")
        RasGeo.clear_geompre_files(plan_files=plan_number, ras_object=temp_ras)

        # Extract geometry number
        geometry_number = _extract_geometry_number(project_staging, plan_number)
        if not geometry_number:
            logger.error(f"Could not extract geometry number for plan {plan_number}")
            return False

        logger.info(f"Plan {plan_number} uses geometry {geometry_number}")

        # Clear existing HDF/binary/log files to force regeneration
        for pattern in [f"*.p{plan_number}.hdf", f"*.p{plan_number}.tmp.hdf",
                       f"*.b{plan_number}", f"*.x{geometry_number}", f"*.bco{plan_number}"]:
            for f in project_staging.glob(pattern):
                try:
                    f.unlink()
                    logger.debug(f"Deleted: {f.name}")
                except:
                    pass

        # Set plan flags for preprocessing AND enable detailed logging
        plan_file_path = project_staging / f"{project_name}.p{plan_number}"
        if plan_file_path.exists():
            RasPlan.update_run_flags(
                plan_number_or_path=str(plan_file_path),
                geometry_preprocessor=True,
                unsteady_flow_simulation=True,
                post_processor=True,
                ras_object=temp_ras
            )

            # Enable detailed logging (Write Detailed= 1) to create .bco file
            _enable_detailed_logging(plan_file_path)

        # Get HEC-RAS executable path from temp_ras
        ras_exe = temp_ras.ras_exe_path
        if not ras_exe or not Path(ras_exe).exists():
            logger.error(f"HEC-RAS executable not found: {ras_exe}")
            return False

        # Get project file path
        prj_file = project_staging / f"{project_name}.prj"
        if not prj_file.exists():
            logger.error(f"Project file not found: {prj_file}")
            return False

        # Build command line - matches RasCmdr format: RAS.exe -c project.prj plan.p##
        plan_file = project_staging / f"{project_name}.p{plan_number}"
        if not plan_file.exists():
            logger.error(f"Plan file not found: {plan_file}")
            return False

        # Use shell command format to match RasCmdr
        cmd = f'"{ras_exe}" -c "{prj_file}" "{plan_file}"'

        logger.info(f"Starting HEC-RAS preprocessing with early termination...")
        logger.debug(f"Command: {cmd}")

        # Record start time for .bco file detection
        execution_start_time = time.time()

        # Start HEC-RAS as subprocess
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(project_staging),
            shell=True
        )

        tmp_hdf = project_staging / f"{project_name}.p{plan_number}.tmp.hdf"
        hdf = project_staging / f"{project_name}.p{plan_number}.hdf"
        bco_file = project_staging / f"{project_name}.bco{plan_number}"

        check_interval = 0.5
        start_time = time.time()

        logger.info(f"Monitoring {bco_file.name} for 'Starting Unsteady Flow Computations' signal...")

        while time.time() - start_time < max_wait:
            # Check if process died
            if process.poll() is not None:
                logger.info(f"HEC-RAS process exited with code {process.returncode}")
                break

            # Check for .bco file with the signal that preprocessing is complete
            if bco_file.exists():
                # Verify file was modified after we started execution
                file_mtime = bco_file.stat().st_mtime
                if file_mtime >= execution_start_time:
                    try:
                        # Read the .bco file and check for the signal
                        content = bco_file.read_text(encoding='utf-8', errors='ignore')
                        if "Starting Unsteady Flow Computations" in content:
                            logger.info(f"Detected 'Starting Unsteady Flow Computations' in {bco_file.name}")
                            logger.info("Preprocessing complete - terminating HEC-RAS before computation starts")
                            break
                    except Exception as e:
                        logger.debug(f"Could not read .bco file: {e}")

            # Also check if .tmp.hdf exists and is being written (fallback)
            if tmp_hdf.exists() and tmp_hdf.stat().st_size > 0:
                logger.debug(f".tmp.hdf growing: {tmp_hdf.stat().st_size / 1024 / 1024:.1f} MB")

            time.sleep(check_interval)

        # Terminate HEC-RAS and all child processes
        if process.poll() is None:
            logger.info("Terminating HEC-RAS process...")
            try:
                # Kill the entire process tree
                parent = psutil.Process(process.pid)
                children = parent.children(recursive=True)

                # Kill children first
                for child in children:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass

                # Then kill parent
                parent.kill()
                process.wait(timeout=5)
                logger.info("HEC-RAS terminated successfully")
            except Exception as e:
                logger.warning(f"Error terminating process: {e}")
                try:
                    process.kill()
                except:
                    pass

        # Verify .tmp.hdf was created
        if tmp_hdf.exists() and tmp_hdf.stat().st_size > 0:
            logger.info(f"Preprocessing complete: {tmp_hdf.name} ({tmp_hdf.stat().st_size / 1024 / 1024:.1f} MB)")
            return True

        # If .hdf exists (process completed before we could kill it), we can still use it
        # but need to rename to .tmp.hdf for Linux container
        if hdf.exists() and hdf.stat().st_size > 0:
            logger.warning(f"Full simulation completed. Renaming {hdf.name} to {tmp_hdf.name}...")
            shutil.copy2(hdf, tmp_hdf)
            logger.info(f"Created {tmp_hdf.name} ({tmp_hdf.stat().st_size / 1024 / 1024:.1f} MB)")
            return True

        logger.error("Preprocessing did not create HDF file")
        return False

    except Exception as e:
        logger.error(f"Preprocessing failed: {e}", exc_info=True)
        return False


def _enable_detailed_logging(plan_file_path: Path) -> bool:
    """
    Enable detailed logging in a plan file by setting 'Write Detailed= 1'.

    This creates a .bcoXX file during HEC-RAS execution that can be monitored
    for the "Starting Unsteady Flow Computations" signal.

    Args:
        plan_file_path: Path to the plan file (.pXX)

    Returns:
        bool: True if successful
    """
    try:
        content = plan_file_path.read_text(encoding='utf-8', errors='ignore')

        # Check if Write Detailed line exists
        if "Write Detailed=" in content:
            # Replace existing setting
            import re
            new_content = re.sub(
                r'Write Detailed=\s*\d+',
                'Write Detailed= 1',
                content
            )
            if new_content != content:
                plan_file_path.write_text(new_content, encoding='utf-8')
                logger.debug(f"Enabled detailed logging in {plan_file_path.name}")
        else:
            # Add the setting after Run HTab line or at the end
            if "Run HTab=" in content:
                new_content = content.replace(
                    "Run HTab=",
                    "Write Detailed= 1\nRun HTab="
                )
            else:
                new_content = content + "\nWrite Detailed= 1\n"
            plan_file_path.write_text(new_content, encoding='utf-8')
            logger.debug(f"Added detailed logging setting to {plan_file_path.name}")

        return True
    except Exception as e:
        logger.warning(f"Could not enable detailed logging: {e}")
        return False


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
        logger.info(f"Remote Docker host: {worker.docker_host}")
        logger.info(f"  Local preprocessing: {local_preprocess_base}")
        logger.info(f"  Remote share (UNC): {worker.share_path}")
        logger.info(f"  Docker mounts: {worker.remote_staging_path}")
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
            if item.is_file():
                shutil.copy2(item, local_input_staging / item.name)
            elif item.is_dir():
                shutil.copytree(item, local_input_staging / item.name, dirs_exist_ok=True)

        # Step 1: Preprocess on Windows LOCALLY (if enabled)
        if worker.preprocess_on_host:
            logger.info(f"Running preprocessing locally (not on network share)...")
            if not _preprocess_plan_for_linux(ras_obj, plan_number, local_input_staging):
                logger.error("Windows preprocessing failed")
                return False

        # Step 1.5: For remote Docker, copy preprocessed files to remote share
        if worker._is_remote:
            logger.info(f"Copying preprocessed files to remote share...")
            remote_staging_folder.mkdir(parents=True, exist_ok=True)
            remote_input_staging.mkdir(parents=True, exist_ok=True)
            remote_output_staging.mkdir(parents=True, exist_ok=True)

            for item in local_input_staging.iterdir():
                if item.is_file():
                    shutil.copy2(item, remote_input_staging / item.name)
                elif item.is_dir():
                    shutil.copytree(item, remote_input_staging / item.name, dirs_exist_ok=True)
            logger.info(f"Files copied to: {remote_staging_folder}")

        # Extract geometry number
        geometry_number = _extract_geometry_number(input_staging, plan_number)
        if not geometry_number:
            logger.error(f"Could not extract geometry number for plan {plan_number}")
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
            'command': [worker.container_script_path, plan_number],
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
                logger.error(f"Container logs:\n{logs}")
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
            logger.error(f"Simulation failed with exit code {exit_code}")
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
            logger.error(f"No HDF results found")
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
                logger.debug(f"Cleaned up staging")
            except:
                pass
        elif not autoclean:
            logger.info(f"Preserving staging: {local_staging_folder}")
