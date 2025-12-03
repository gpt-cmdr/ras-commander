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
    # or: pip install docker

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
            For remote: "tcp://192.168.3.8:2375"
        share_path: UNC path for file transfer to remote Docker host (required for remote)
            Example: "\\\\\\\\192.168.3.8\\\\RasRemote"
        remote_staging_path: Path on Docker host for volume mounts (required for remote)
            Example: "C:\\\\RasRemote"
        worker_id: Custom worker ID (auto-generated if not provided)
        cores_total: Total CPU cores available for this worker
        cores_per_plan: CPU cores to allocate per plan
        max_runtime_minutes: Simulation timeout (default: 480)
        preprocess_on_host: Run Windows preprocessing first (default: True)
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

    Example (remote Docker):
        >>> worker = init_docker_worker(
        ...     docker_image="hecras:6.6",
        ...     docker_host="tcp://192.168.3.8:2375",
        ...     share_path="\\\\\\\\192.168.3.8\\\\RasRemote",
        ...     remote_staging_path="C:\\\\RasRemote",
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

    # Verify Docker daemon connectivity
    try:
        if worker.docker_host:
            client = docker.DockerClient(base_url=worker.docker_host)
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
        logger.error(f"Cannot connect to Docker daemon: {e}")
        raise

    logger.info(f"DockerWorker initialized:")
    logger.info(f"  Image: {worker.docker_image}")
    logger.info(f"  Host: {worker.docker_host or 'local'}")
    logger.info(f"  Preprocess on host: {worker.preprocess_on_host}")
    logger.info(f"  Max parallel plans: {worker.max_parallel_plans}")
    logger.info(f"  Timeout: {worker.max_runtime_minutes} minutes")

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
    stability_timeout: int = 10,
    max_wait: int = 300
) -> bool:
    """
    Preprocess a plan on Windows to create files needed for Linux execution.

    This runs HEC-RAS on Windows with EARLY TERMINATION to generate:
    - .tmp.hdf file (preprocessed geometry and initial conditions)
    - .b file (binary geometry)
    - .x file (execution file)

    The process is killed after .tmp.hdf is created and stabilizes, preserving
    the intermediate file for Linux execution.

    Args:
        ras_obj: RasPrj object
        plan_number: Plan number to preprocess
        project_staging: Path to staged project copy
        stability_timeout: Seconds to wait for file stability after creation
        max_wait: Maximum seconds to wait for .tmp.hdf to appear

    Returns:
        bool: True if preprocessing succeeded
    """
    import subprocess
    import psutil

    try:
        # Import here to avoid circular imports
        from ..RasPrj import init_ras_project
        from ..RasGeo import RasGeo
        from ..RasPlan import RasPlan

        # Initialize the staged project
        temp_ras = init_ras_project(str(project_staging), ras_obj.ras_version)
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

        # Clear existing HDF/binary files to force regeneration
        for pattern in [f"*.p{plan_number}.hdf", f"*.p{plan_number}.tmp.hdf",
                       f"*.b{plan_number}", f"*.x{geometry_number}"]:
            for f in project_staging.glob(pattern):
                try:
                    f.unlink()
                    logger.debug(f"Deleted: {f.name}")
                except:
                    pass

        # Set plan flags for preprocessing
        plan_file_path = project_staging / f"{project_name}.p{plan_number}"
        if plan_file_path.exists():
            RasPlan.update_run_flags(
                plan_number_or_path=str(plan_file_path),
                geometry_preprocessor=True,
                unsteady_flow_simulation=True,
                post_processor=True,
                ras_object=temp_ras
            )

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

        # Monitor for .tmp.hdf creation
        start_time = time.time()
        last_size = 0
        stable_count = 0
        check_interval = 0.5

        logger.info(f"Waiting for {tmp_hdf.name} to be created (max {max_wait}s)...")

        while time.time() - start_time < max_wait:
            # Check if process died
            if process.poll() is not None:
                logger.info(f"HEC-RAS process exited with code {process.returncode}")
                break

            # Check for .tmp.hdf
            if tmp_hdf.exists():
                current_size = tmp_hdf.stat().st_size

                if current_size > 0:
                    if current_size == last_size:
                        stable_count += 1
                        if stable_count >= (stability_timeout / check_interval):
                            logger.info(f"File stable at {current_size / 1024 / 1024:.1f} MB for {stability_timeout}s")
                            break
                    else:
                        stable_count = 0
                        logger.debug(f"File growing: {current_size / 1024 / 1024:.1f} MB")

                    last_size = current_size

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

    project_folder = Path(ras_obj.project_folder)
    project_name = ras_obj.project_name

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
            client = docker.DockerClient(base_url=worker.docker_host)
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
