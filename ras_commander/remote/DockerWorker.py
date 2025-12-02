"""
DockerWorker - Docker containerized execution worker.

This module implements the DockerWorker class for executing HEC-RAS in
Docker containers.

IMPLEMENTATION STATUS: STUB - Future Development

Requirements:
    pip install ras-commander[remote-docker]
    # or: pip install docker
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from .RasWorker import RasWorker
from ..LoggingConfig import get_logger

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
    Docker containerized execution worker.

    IMPLEMENTATION STATUS: STUB - Future Development

    IMPLEMENTATION NOTES:
    Docker containers provide isolation and reproducibility for HEC-RAS execution.

    When implemented, this worker will:
    1. Use docker-py library for container management
    2. Mount project directory as volume in container
    3. Execute HEC-RAS inside container with proper license handling
    4. Support local Docker or remote Docker hosts
    5. Enable reproducible execution environments

    Required Parameters:
        - docker_image: HEC-RAS Docker image name/tag
        - docker_host: Docker host URL (None for local)
        - volume_mount: Host path to mount in container
        - license_config: HEC-RAS license handling configuration

    Usage Pattern:
        docker_worker = init_ras_worker(
            "docker",
            docker_image="hecras:6.3",
            docker_host=None,
            volume_mount="/mnt/ras_projects",
            ras_exe_path="/opt/hecras/RAS.exe",
            license_config={"type": "network", "server": "license.example.com"}
        )

    Dependencies:
        - docker: Docker Python SDK

    Challenges:
        - HEC-RAS licensing in containers
        - GUI dependencies if using HECRASController
        - Windows-only nature of HEC-RAS (needs Wine on Linux)
    """
    docker_image: str = None
    docker_host: str = None
    volume_mount: str = None
    license_config: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        super().__post_init__()
        self.worker_type = "docker"
        raise NotImplementedError(
            "DockerWorker is not yet implemented. "
            "Planned for future release. "
            "Will use docker-py for containerized execution.\n"
            "Requires: pip install ras-commander[remote-docker]"
        )


def init_docker_worker(**kwargs) -> DockerWorker:
    """Initialize Docker worker (stub - raises NotImplementedError)."""
    check_docker_dependencies()
    kwargs['worker_type'] = 'docker'
    return DockerWorker(**kwargs)
