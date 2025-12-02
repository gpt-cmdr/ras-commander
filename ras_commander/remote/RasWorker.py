"""
RasWorker - Base class and factory function for remote execution workers.

This module provides the RasWorker base dataclass and the init_ras_worker()
factory function for creating remote execution workers of various types.

Pattern follows RasPrj.py which contains both RasPrj class and init_ras_project().
"""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from ..LoggingConfig import get_logger
from ..Decorators import log_call

logger = get_logger(__name__)


# =============================================================================
# WORKER BASE CLASS
# =============================================================================

@dataclass
class RasWorker:
    """
    Base class for remote execution workers.

    All worker types inherit from this base class and implement type-specific
    connection, deployment, and execution logic.

    Attributes:
        worker_type: Type identifier ("psexec", "ssh", "local", etc.)
        worker_id: Unique identifier for this worker instance
        hostname: Remote machine hostname or IP (None for local)
        ras_exe_path: Path to HEC-RAS.exe on target machine (optional, obtained from ras object)
        capabilities: Dict of worker capabilities (cores, memory, etc.)
        metadata: Additional worker-specific configuration
    """
    worker_type: str
    worker_id: str = None
    hostname: Optional[str] = None
    ras_exe_path: str = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate worker configuration after initialization."""
        if not self.worker_type:
            raise ValueError("worker_type is required")
        # Note: ras_exe_path is optional - will be obtained from ras object during execution


# =============================================================================
# WORKER FACTORY FUNCTION
# =============================================================================

@log_call
def init_ras_worker(
    worker_type: str,
    ras_object=None,
    **kwargs
) -> RasWorker:
    """
    Initialize and validate a remote execution worker.

    This factory function creates worker objects of various types, validates
    connectivity, and ensures HEC-RAS is available on the target system.

    Args:
        worker_type: Type of worker - "psexec", "local", "ssh", "winrm", "docker",
                     "slurm", "aws_ec2", "azure_fr"
        ras_object: RasPrj object to get ras_exe_path from. If None, uses global ras.
        **kwargs: Worker-type specific configuration parameters

    Common kwargs (all worker types):
        ras_exe_path: Path to HEC-RAS.exe on target machine (optional - obtained from ras object if not provided)
        worker_id: Unique identifier (auto-generated if not provided)

    PsExec-specific kwargs:
        hostname: Remote machine hostname or IP (required)
        share_path: UNC path to network share (required, e.g., \\\\hostname\\RasRemote)
        worker_folder: Local path on remote machine corresponding to share_path (optional).
                      If not specified, defaults to C:\\{share_name} (e.g., C:\\RasRemote).
                      Set this if your share points to a different local path.
        credentials: Dict with 'username' and 'password' (OPTIONAL - recommended to omit).
                    When omitted, uses Windows authentication which avoids GUI access issues.
                    Only provide if your network requires explicit authentication.
        session_id: Session ID to run in (default 2). Use "query user" on remote to check.
        process_priority: OS process priority for HEC-RAS execution.
                         Valid values: "low" (default), "below normal", "normal".
                         Recommended: "low" to minimize impact on remote user operations.
        queue_priority: Execution queue priority (0-9). Lower values execute first.
                       Workers at queue level 0 are filled before queue level 1, etc.
                       Default: 0. Use for tiered bursting (local=0, remote=1, cloud=2).
        system_account: Run as SYSTEM (default False)
        psexec_path: Path to PsExec.exe (auto-detected if not provided)

    Returns:
        RasWorker: Initialized and validated worker object ready for execution

    Raises:
        ValueError: Invalid worker_type or missing required parameters
        ConnectionError: Cannot connect to remote machine
        FileNotFoundError: PsExec.exe or RAS.exe not found
        PermissionError: Insufficient permissions for remote execution
        NotImplementedError: Worker type not yet implemented

    Example:
        # Initialize PsExec worker - ras_exe_path obtained from ras object
        worker = init_ras_worker(
            "psexec",
            hostname="WORKSTATION-01",
            share_path=r"\\\\WORKSTATION-01\\RasRemote",
            session_id=2  # Check with "query user" on remote machine
        )

        # Or with explicit ras_object
        worker = init_ras_worker(
            "psexec",
            ras_object=my_ras_project,
            hostname="WORKSTATION-01",
            share_path=r"\\\\WORKSTATION-01\\RasRemote"
        )
    """
    logger.info(f"Initializing {worker_type} worker")

    # Validate worker_type
    valid_types = ["psexec", "local", "ssh", "winrm", "docker", "slurm", "aws_ec2", "azure_fr"]
    if worker_type not in valid_types:
        raise ValueError(
            f"Invalid worker_type '{worker_type}'. "
            f"Valid types: {', '.join(valid_types)}"
        )

    # Get ras_exe_path from ras object if not provided
    if "ras_exe_path" not in kwargs or kwargs.get("ras_exe_path") is None:
        from ..RasPrj import ras as global_ras, get_ras_exe

        ras_obj = ras_object if ras_object is not None else global_ras

        if ras_obj is not None and hasattr(ras_obj, 'ras_exe_path') and ras_obj.ras_exe_path:
            kwargs["ras_exe_path"] = ras_obj.ras_exe_path
            logger.debug(f"Using ras_exe_path from ras object: {kwargs['ras_exe_path']}")
        else:
            # Try to get from get_ras_exe() which uses default paths
            try:
                kwargs["ras_exe_path"] = get_ras_exe()
                logger.debug(f"Using ras_exe_path from get_ras_exe(): {kwargs['ras_exe_path']}")
            except Exception:
                logger.warning("Could not determine ras_exe_path - will need to be set before execution")

    # Auto-generate worker_id if not provided
    if "worker_id" not in kwargs or kwargs.get("worker_id") is None:
        kwargs["worker_id"] = f"{worker_type}_{uuid.uuid4().hex[:8]}"

    # Route to appropriate worker initialization
    # Using lazy imports inside function to avoid circular dependencies
    if worker_type == "psexec":
        from .PsexecWorker import init_psexec_worker
        return init_psexec_worker(**kwargs)

    elif worker_type == "local":
        from .LocalWorker import init_local_worker
        return init_local_worker(**kwargs)

    elif worker_type == "ssh":
        from .SshWorker import init_ssh_worker
        return init_ssh_worker(**kwargs)

    elif worker_type == "winrm":
        from .WinrmWorker import init_winrm_worker
        return init_winrm_worker(**kwargs)

    elif worker_type == "docker":
        from .DockerWorker import init_docker_worker
        return init_docker_worker(**kwargs)

    elif worker_type == "slurm":
        from .SlurmWorker import init_slurm_worker
        return init_slurm_worker(**kwargs)

    elif worker_type == "aws_ec2":
        from .AwsEc2Worker import init_aws_ec2_worker
        return init_aws_ec2_worker(**kwargs)

    elif worker_type == "azure_fr":
        from .AzureFrWorker import init_azure_fr_worker
        return init_azure_fr_worker(**kwargs)


@log_call
def load_workers_from_json(
    json_path: Union[str, Path],
    ras_object=None,
    enabled_only: bool = True
) -> List[RasWorker]:
    """
    Load worker configurations from a JSON file.

    Args:
        json_path: Path to JSON file containing worker configurations
        ras_object: RasPrj object to get ras_exe_path from. If None, uses global ras.
        enabled_only: If True, only load workers with "enabled": true (default True)

    Returns:
        List[RasWorker]: List of initialized worker objects

    JSON Format:
        {
            "workers": [
                {
                    "name": "Local Compute",
                    "worker_type": "local",
                    "worker_folder": "C:\\\\RasRemote",
                    "process_priority": "low",
                    "queue_priority": 0,
                    "cores_total": 4,
                    "cores_per_plan": 2,
                    "enabled": true
                },
                {
                    "name": "Remote PC",
                    "worker_type": "psexec",
                    "hostname": "192.168.1.100",
                    "share_path": "\\\\192.168.1.100\\RasRemote",
                    "worker_folder": "C:\\\\RasRemote",
                    "username": ".\\user",
                    "password": "password",
                    "session_id": 2,
                    "process_priority": "low",
                    "queue_priority": 0,
                    "cores_total": 8,
                    "cores_per_plan": 2,
                    "enabled": true
                }
            ]
        }

    Example:
        workers = load_workers_from_json("RemoteWorkers.json")
        results = compute_parallel_remote(["01", "02"], workers=workers)
    """
    json_path = Path(json_path)

    if not json_path.exists():
        raise FileNotFoundError(f"Worker configuration file not found: {json_path}")

    with open(json_path, 'r') as f:
        config = json.load(f)

    if "workers" not in config:
        raise ValueError("JSON file must contain a 'workers' array")

    workers = []
    for worker_config in config["workers"]:
        # Check if enabled
        if enabled_only and not worker_config.get("enabled", True):
            logger.debug(f"Skipping disabled worker: {worker_config.get('name', 'unnamed')}")
            continue

        # Extract worker_type (required)
        worker_type = worker_config.get("worker_type")
        if not worker_type:
            logger.warning(f"Skipping worker without worker_type: {worker_config.get('name', 'unnamed')}")
            continue

        # Build kwargs from config, excluding non-parameter fields
        kwargs = {}
        exclude_fields = {"name", "worker_type", "enabled"}

        for key, value in worker_config.items():
            if key not in exclude_fields:
                # Handle credentials - convert username/password to credentials dict
                if key == "username":
                    if "credentials" not in kwargs:
                        kwargs["credentials"] = {}
                    kwargs["credentials"]["username"] = value
                elif key == "password":
                    if "credentials" not in kwargs:
                        kwargs["credentials"] = {}
                    kwargs["credentials"]["password"] = value
                else:
                    kwargs[key] = value

        # Use name as worker_id if provided
        if "name" in worker_config:
            kwargs["worker_id"] = worker_config["name"]

        try:
            worker = init_ras_worker(worker_type, ras_object=ras_object, **kwargs)
            workers.append(worker)
            logger.info(f"Loaded worker: {worker.worker_id} ({worker_type})")
        except NotImplementedError as e:
            logger.warning(f"Skipping unimplemented worker type '{worker_type}': {e}")
        except Exception as e:
            logger.error(f"Failed to initialize worker '{worker_config.get('name', 'unnamed')}': {e}")

    logger.info(f"Loaded {len(workers)} workers from {json_path}")
    return workers
