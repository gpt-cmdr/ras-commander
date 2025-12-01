"""
RasRemote - Remote and distributed execution operations for HEC-RAS simulations

This module extends ras-commander's parallel execution capabilities to support distributed
computing across multiple machines using various execution backends (PsExec, SSH, cloud services).

VISION: Flexible worker abstraction for heterogeneous execution environments
------------------------------------------------------------------------
The RasWorker abstraction enables seamless execution across:
- Local machines (using RasCmdr.compute_parallel internally)
- Remote Windows machines (PsExec over network shares) ✓ IMPLEMENTED
- Remote Linux/Mac (SSH with rsync/scp) [FUTURE]
- Windows Remote Management (WinRM native protocol) [FUTURE]
- Containerized execution (Docker) [FUTURE]
- HPC clusters (Slurm scheduler) [FUTURE]
- Cloud compute (AWS EC2, Azure Functions) [FUTURE]

This design enables:
1. Naive queueing: Round-robin across all available workers regardless of type
2. Focused bursting: Target specific worker types for specific workloads
3. Multi-cloud: Execute simultaneously across AWS, Azure, local resources
4. Cost optimization: Prefer local, burst to cloud when needed

ARCHITECTURE PATTERN:
- Worker objects are stateless configuration containers
- init_ras_worker() validates connection and returns ready-to-use worker
- compute_parallel_remote() handles queueing, execution, result collection
- Each worker type encapsulates its deployment/execution/cleanup logic

This module uses the centralized logging configuration from ras-commander.

Logging Configuration:
- Use @log_call decorator for automatic function call logging
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs written to console and rotating file handler

Example:
    # Initialize workers (heterogeneous mix)
    local_worker = init_ras_worker("local")

    psexec_worker1 = init_ras_worker(
        "psexec",
        hostname="WORKSTATION-01",
        share_path=r"\\\\WORKSTATION-01\\Temp\\RAS_Runs",
        credentials={"username": "domain\\\\user", "password": "pass"},
        ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe"
    )

    # Execute across all workers
    results = compute_parallel_remote(
        plan_number=["01", "02", "03", "04"],
        workers=[local_worker, psexec_worker1],
        ras_object=ras,
        dest_folder="distributed_results"
    )

List of Classes in RasRemote:
- RasWorker (base class)
- PsexecWorker (Windows remote execution via PsExec) ✓ IMPLEMENTED
- LocalWorker (local parallel execution) [STUB - uses RasCmdr]
- SshWorker (SSH-based remote execution) [FUTURE]
- WinrmWorker (WinRM-based remote execution) [FUTURE]
- DockerWorker (containerized execution) [FUTURE]
- SlurmWorker (HPC cluster execution) [FUTURE]
- AwsEc2Worker (AWS cloud execution) [FUTURE]
- AzureFrWorker (Azure Functions execution) [FUTURE]

List of Functions in RasRemote:
- init_ras_worker() - Factory function to create and validate workers
- compute_parallel_remote() - Execute plans across distributed worker pool
"""

import os
import subprocess
import shutil
import time
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from typing import Union, List, Optional, Dict, Any
from numbers import Number
from dataclasses import dataclass, field

from .RasPrj import ras, RasPrj, init_ras_project
from .RasCmdr import RasCmdr
from .LoggingConfig import get_logger
from .Decorators import log_call

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
        ras_exe_path: Path to HEC-RAS.exe on target machine
        capabilities: Dict of worker capabilities (cores, memory, etc.)
        metadata: Additional worker-specific configuration
    """
    worker_type: str
    worker_id: str
    hostname: Optional[str] = None
    ras_exe_path: str = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate worker configuration after initialization."""
        if not self.worker_type:
            raise ValueError("worker_type is required")
        if not self.ras_exe_path:
            raise ValueError("ras_exe_path is required")


# =============================================================================
# PSEXEC WORKER (FULLY IMPLEMENTED)
# =============================================================================

@dataclass
class PsexecWorker(RasWorker):
    """
    PsExec-based Windows remote execution worker.

    Uses Microsoft Sysinternals PsExec to execute HEC-RAS on remote Windows machines
    via network share deployment.

    IMPLEMENTATION STATUS: ✓ FULLY IMPLEMENTED

    Attributes:
        share_path: UNC path to accessible network share (e.g., \\\\hostname\\RasRemote)
        local_path: Local path on remote machine that corresponds to share_path.
                   This is the actual folder path on the remote machine's filesystem.
                   Example: If share_path is \\\\hostname\\RasRemote and the share points
                   to C:\\RasRemote on the remote machine, set local_path="C:\\RasRemote".
                   If not specified, defaults to "C:\\{share_name}" (e.g., C:\\RasRemote).
        credentials: Dict with 'username' and 'password' for remote authentication.
                    OPTIONAL for trusted networks. When omitted (empty dict or None),
                    PsExec uses the current user's Windows authentication, which:
                    - Works on domain-joined machines with proper trust
                    - Avoids the "secondary logon" issue that prevents GUI access
                    - Is RECOMMENDED for most internal network setups
                    When credentials ARE provided, the specified user must be the same
                    user logged into the remote desktop session, or have
                    "Replace a process level token" (SeAssignPrimaryTokenPrivilege) right.
        session_id: Session ID to run in (default 2 - typical for single-user workstations)
        process_priority: OS process priority for HEC-RAS execution on remote machine.
                         Valid values: "low" (default), "below normal", "normal".
                         Recommended: "low" to minimize impact on remote user operations.
                         Note: Higher priorities (above normal, high, realtime) are NOT
                         supported to avoid impacting remote user operations.
        queue_priority: Execution queue priority level (0-9). Lower values execute first.
                       Workers at queue level 0 are fully utilized before queue level 1.
                       Default: 0. Use for tiered bursting (local=0, remote=1, cloud=2).
        system_account: Run as SYSTEM account (default False)
        psexec_path: Path to PsExec.exe (auto-detected from PATH if not specified)
        remote_temp_folder: Temporary folder name on remote machine
        cores_total: Total CPU cores available on remote machine (optional)
        cores_per_plan: Cores to allocate per HEC-RAS plan (default 4)
        max_parallel_plans: Max plans to run in parallel (calculated: cores_total/cores_per_plan)

    CRITICAL: HEC-RAS is a GUI application and REQUIRES session-based execution.
    - system_account=False (default) - Runs in user session with desktop (REQUIRED for HEC-RAS)
    - system_account=True - Runs as SYSTEM (no desktop, HEC-RAS will hang)

    Multi-Core Parallelism:
    - Set cores_total (e.g., 16) and cores_per_plan (e.g., 4) for parallel execution
    - Worker will run cores_total/cores_per_plan plans simultaneously (e.g., 4 plans)
    - Each plan gets cores_per_plan cores allocated
    - If not specified, executes plans sequentially (legacy behavior)

    Session-based execution requires additional Group Policy configuration on the remote machine.
    See REMOTE_WORKER_SETUP_GUIDE.md for complete setup instructions.

    Example:
        # RECOMMENDED: No credentials (uses Windows authentication, avoids GUI issues)
        worker = init_ras_worker(
            "psexec",
            hostname="WORKSTATION-01",
            share_path=r"\\\\WORKSTATION-01\\RasRemote",
            local_path=r"C:\\RasRemote",
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe",
            session_id=2
        )

        # With explicit credentials (only if required by network policy)
        worker = init_ras_worker(
            "psexec",
            hostname="WORKSTATION-01",
            share_path=r"\\\\WORKSTATION-01\\RasRemote",
            local_path=r"C:\\RasRemote",
            credentials={"username": "DOMAIN\\\\user", "password": "SecurePass123"},
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe",
            session_id=2,
            process_priority="low",
            queue_priority=0
        )
    """
    share_path: str = None
    local_path: str = None  # Local path on remote machine corresponding to share_path
    credentials: Dict[str, str] = field(default_factory=dict)
    session_id: int = 2
    process_priority: str = "low"  # OS priority: "low" (default), "below normal", "normal"
    queue_priority: int = 0  # Execution queue priority: 0-9, lower executes first
    system_account: bool = False  # REQUIRED: False for HEC-RAS GUI execution
    psexec_path: str = None
    remote_temp_folder: str = None
    cores_total: int = None  # Total cores on machine (for parallel execution)
    cores_per_plan: int = 4  # Cores per plan
    max_parallel_plans: int = None  # Calculated in __post_init__

    def __post_init__(self):
        """Validate PsExec worker configuration."""
        super().__post_init__()

        if not self.share_path:
            raise ValueError("share_path is required for PsExec workers")
        if not self.hostname:
            raise ValueError("hostname is required for PsExec workers")
        if not self.credentials:
            raise ValueError("credentials dict with 'username' and 'password' required")
        if "username" not in self.credentials or "password" not in self.credentials:
            raise ValueError("credentials must contain both 'username' and 'password' keys")
        if self.process_priority not in ["low", "below normal", "normal"]:
            raise ValueError(
                f"process_priority must be 'low', 'below normal', or 'normal' "
                f"(got '{self.process_priority}'). 'low' is recommended to minimize "
                f"impact on remote user operations."
            )
        if not isinstance(self.queue_priority, int) or self.queue_priority < 0 or self.queue_priority > 9:
            raise ValueError(
                f"queue_priority must be an integer from 0 to 9 (got {self.queue_priority}). "
                f"Lower values execute first. Default is 0."
            )

        # Auto-derive local_path from share_path if not specified
        # Default: \\hostname\ShareName -> C:\ShareName
        if not self.local_path:
            share_parts = self.share_path.strip('\\').split('\\')
            if len(share_parts) >= 2:
                share_name = share_parts[1]
                self.local_path = f"C:\\{share_name}"
            else:
                raise ValueError(
                    f"Cannot auto-derive local_path from share_path '{self.share_path}'. "
                    f"Please specify local_path explicitly."
                )

        # Calculate max parallel plans if cores_total specified
        if self.cores_total is not None:
            self.max_parallel_plans = self.cores_total // self.cores_per_plan
            if self.max_parallel_plans < 1:
                self.max_parallel_plans = 1
        else:
            # Sequential execution (legacy behavior)
            self.max_parallel_plans = 1


# =============================================================================
# FUTURE WORKER STUBS
# =============================================================================

@dataclass
class LocalWorker(RasWorker):
    """
    Local parallel execution worker (uses RasCmdr.compute_parallel internally).

    IMPLEMENTATION STATUS: STUB - Future Development

    IMPLEMENTATION NOTES:
    When implemented, this worker will:
    1. Use RasCmdr.compute_parallel() for actual execution
    2. Provide unified interface with remote workers
    3. Enable mixed local+remote execution pools
    4. Require: max_workers, num_cores parameters
    5. Return results in same format as remote workers

    Usage Pattern:
        local_worker = init_ras_worker(
            "local",
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe",
            max_workers=4,
            num_cores=2
        )
    """
    max_workers: int = 2
    num_cores: int = 2

    def __post_init__(self):
        super().__post_init__()
        self.worker_type = "local"
        self.hostname = "localhost"
        raise NotImplementedError(
            "LocalWorker is not yet implemented. "
            "Use RasCmdr.compute_parallel() directly for local parallel execution. "
            "Future implementation will wrap RasCmdr for unified interface."
        )


@dataclass
class SshWorker(RasWorker):
    """
    SSH-based remote execution worker for Linux/Mac systems.

    IMPLEMENTATION STATUS: STUB - Future Development

    IMPLEMENTATION NOTES:
    When implemented, this worker will:
    1. Use paramiko library for SSH connections
    2. Deploy projects via scp or rsync
    3. Execute HEC-RAS using SSH remote command execution
    4. Support SSH key-based or password authentication
    5. Work with Linux/Mac HEC-RAS installations (if available) or Wine

    Required Parameters:
        - hostname: SSH server hostname/IP
        - port: SSH port (default 22)
        - username: SSH username
        - auth_method: "password" or "key"
        - password or key_path: Authentication credentials
        - remote_path: Remote directory for project deployment

    Usage Pattern:
        ssh_worker = init_ras_worker(
            "ssh",
            hostname="linux-server.example.com",
            port=22,
            username="user",
            auth_method="key",
            key_path="/home/user/.ssh/id_rsa",
            remote_path="/tmp/ras_runs",
            ras_exe_path="/opt/hecras/bin/ras"
        )

    Dependencies:
        - paramiko: SSH client library
        - scp or subprocess for rsync: File transfer
    """
    port: int = 22
    username: str = None
    auth_method: str = "password"  # "password" or "key"
    password: str = None
    key_path: str = None
    remote_path: str = None

    def __post_init__(self):
        super().__post_init__()
        self.worker_type = "ssh"
        raise NotImplementedError(
            "SshWorker is not yet implemented. "
            "Planned for future release. "
            "Will use paramiko for SSH connections and scp/rsync for file transfer."
        )


@dataclass
class WinrmWorker(RasWorker):
    """
    Windows Remote Management (WinRM) worker.

    IMPLEMENTATION STATUS: STUB - Future Development

    IMPLEMENTATION NOTES:
    WinRM is the native Windows remote management protocol and may provide
    better performance than PsExec in enterprise environments with proper
    WinRM configuration.

    When implemented, this worker will:
    1. Use pywinrm library for Windows remote management
    2. Deploy projects via network shares or WinRM file copy
    3. Execute HEC-RAS using WinRM remote command execution
    4. Support Kerberos, NTLM, or CredSSP authentication
    5. Require WinRM to be enabled on target machines

    Required Parameters:
        - hostname: Windows machine hostname/IP
        - username: Windows username (domain\\user format)
        - password: Windows password
        - auth: Authentication method ("ntlm", "kerberos", "credssp")
        - transport: Transport protocol ("http" or "https")
        - share_path: UNC path for file deployment

    Usage Pattern:
        winrm_worker = init_ras_worker(
            "winrm",
            hostname="WORKSTATION-01",
            username="DOMAIN\\\\user",
            password="password",
            auth="ntlm",
            transport="https",
            share_path=r"\\\\WORKSTATION-01\\Temp\\RAS_Runs",
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe"
        )

    Dependencies:
        - pywinrm: Windows Remote Management client library

    Advantages over PsExec:
        - Native Windows protocol (no external tool required)
        - Better integration with Windows security
        - Can use Kerberos for enterprise authentication
    """
    username: str = None
    password: str = None
    auth: str = "ntlm"  # "ntlm", "kerberos", "credssp"
    transport: str = "https"  # "http" or "https"
    share_path: str = None

    def __post_init__(self):
        super().__post_init__()
        self.worker_type = "winrm"
        raise NotImplementedError(
            "WinrmWorker is not yet implemented. "
            "Planned for future release. "
            "Will use pywinrm for native Windows remote management."
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
            docker_host=None,  # Local Docker
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
            "Will use docker-py for containerized execution."
        )


@dataclass
class SlurmWorker(RasWorker):
    """
    Slurm HPC cluster execution worker.

    IMPLEMENTATION STATUS: STUB - Future Development

    IMPLEMENTATION NOTES:
    Slurm is a common job scheduler for HPC clusters and enables large-scale
    parallel execution across cluster nodes.

    When implemented, this worker will:
    1. Submit HEC-RAS jobs to Slurm queue using sbatch
    2. Monitor job status using squeue/sacct
    3. Use shared filesystem (NFS/Lustre) for project access
    4. Support array jobs for multiple plan execution
    5. Handle node allocation and resource requests

    Required Parameters:
        - partition: Slurm partition name
        - nodes: Number of nodes to request
        - cpus_per_task: CPUs per task
        - memory: Memory per node
        - time_limit: Wall time limit
        - shared_fs_path: Shared filesystem path accessible to all nodes
        - job_name_prefix: Prefix for Slurm job names

    Usage Pattern:
        slurm_worker = init_ras_worker(
            "slurm",
            partition="compute",
            nodes=4,
            cpus_per_task=8,
            memory="32G",
            time_limit="02:00:00",
            shared_fs_path="/mnt/shared/ras_projects",
            ras_exe_path="/software/hecras/6.3/RAS.exe"
        )

    Dependencies:
        - pyslurm or subprocess for sbatch/squeue commands

    Typical Use Case:
        - Large ensemble runs (100+ rainfall events)
        - Complex 2D models requiring significant compute time
        - Research institutions with HPC infrastructure
    """
    partition: str = None
    nodes: int = 1
    cpus_per_task: int = 8
    memory: str = "32G"
    time_limit: str = "02:00:00"
    shared_fs_path: str = None
    job_name_prefix: str = "ras_job"

    def __post_init__(self):
        super().__post_init__()
        self.worker_type = "slurm"
        raise NotImplementedError(
            "SlurmWorker is not yet implemented. "
            "Planned for future release. "
            "Will use pyslurm or subprocess for HPC cluster execution."
        )


@dataclass
class AwsEc2Worker(RasWorker):
    """
    AWS EC2 cloud compute worker.

    IMPLEMENTATION STATUS: STUB - Future Development

    IMPLEMENTATION NOTES:
    AWS EC2 enables elastic compute capacity for burst workloads and large-scale
    parallel execution without local hardware constraints.

    When implemented, this worker will:
    1. Use boto3 library for AWS API access
    2. Launch EC2 instances on-demand or use existing instances
    3. Deploy projects via S3 or direct instance connection
    4. Execute HEC-RAS on Windows EC2 instances
    5. Collect results to S3 and optionally terminate instances
    6. Support spot instances for cost optimization

    Required Parameters:
        - region: AWS region (e.g., "us-east-1")
        - instance_type: EC2 instance type (e.g., "c5.2xlarge")
        - ami_id: AMI with HEC-RAS pre-installed
        - key_name: EC2 key pair name
        - security_group: Security group ID
        - iam_role: IAM role for S3 access
        - s3_bucket: S3 bucket for project deployment
        - spot_instance: Use spot instances (default False)

    Usage Pattern:
        aws_worker = init_ras_worker(
            "aws_ec2",
            region="us-east-1",
            instance_type="c5.4xlarge",
            ami_id="ami-hecras-6.3-windows",
            key_name="my-keypair",
            security_group="sg-xxxxxxxxx",
            iam_role="HECRASExecutionRole",
            s3_bucket="my-ras-projects",
            spot_instance=True,
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe"
        )

    Dependencies:
        - boto3: AWS SDK for Python

    Cost Optimization Strategies:
        - Use spot instances for interruptible workloads
        - Terminate instances after execution
        - Use appropriate instance sizing
        - Store results in S3 Intelligent-Tiering
    """
    region: str = "us-east-1"
    instance_type: str = "c5.2xlarge"
    ami_id: str = None
    key_name: str = None
    security_group: str = None
    iam_role: str = None
    s3_bucket: str = None
    spot_instance: bool = False
    auto_terminate: bool = True

    def __post_init__(self):
        super().__post_init__()
        self.worker_type = "aws_ec2"
        raise NotImplementedError(
            "AwsEc2Worker is not yet implemented. "
            "Planned for future release. "
            "Will use boto3 for AWS EC2 cloud execution."
        )


@dataclass
class AzureFrWorker(RasWorker):
    """
    Azure Functions serverless execution worker.

    IMPLEMENTATION STATUS: STUB - Future Development

    IMPLEMENTATION NOTES:
    Azure Functions enables serverless execution with automatic scaling and
    pay-per-execution pricing. Note: HEC-RAS execution may exceed typical
    Function time limits and require Durable Functions or Container Instances.

    When implemented, this worker will:
    1. Use Azure SDK for Python (azure-functions, azure-storage-blob)
    2. Deploy projects to Azure Blob Storage
    3. Trigger function execution or Container Instances
    4. Monitor execution via Azure APIs
    5. Collect results from Blob Storage
    6. Support Azure Container Instances for long-running models

    Required Parameters:
        - subscription_id: Azure subscription ID
        - resource_group: Resource group name
        - function_app: Function App name (if using Functions)
        - container_registry: Container registry (if using Container Instances)
        - storage_account: Azure Storage account name
        - storage_container: Blob container for projects
        - region: Azure region (e.g., "eastus")

    Usage Pattern:
        azure_worker = init_ras_worker(
            "azure_fr",
            subscription_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            resource_group="ras-execution-rg",
            container_registry="myregistry.azurecr.io/hecras:6.3",
            storage_account="rasprojectsstorage",
            storage_container="ras-projects",
            region="eastus",
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe"
        )

    Dependencies:
        - azure-functions: Azure Functions SDK
        - azure-storage-blob: Azure Blob Storage client
        - azure-identity: Azure authentication

    Considerations:
        - Function time limits (5-10 minutes typical, longer with Premium)
        - Consider Azure Container Instances for long-running models
        - Azure Batch may be more suitable for large-scale parallel execution
    """
    subscription_id: str = None
    resource_group: str = None
    function_app: str = None
    container_registry: str = None
    storage_account: str = None
    storage_container: str = None
    region: str = "eastus"
    use_container_instances: bool = True

    def __post_init__(self):
        super().__post_init__()
        self.worker_type = "azure_fr"
        raise NotImplementedError(
            "AzureFrWorker is not yet implemented. "
            "Planned for future release. "
            "Will use Azure SDK for serverless/container-based execution. "
            "Note: Consider Azure Batch for large-scale parallel workloads."
        )


# =============================================================================
# WORKER FACTORY FUNCTION
# =============================================================================

@log_call
def init_ras_worker(
    worker_type: str,
    **kwargs
) -> RasWorker:
    """
    Initialize and validate a remote execution worker.

    This factory function creates worker objects of various types, validates
    connectivity, and ensures HEC-RAS is available on the target system.

    Args:
        worker_type: Type of worker - "psexec", "local", "ssh", "winrm", "docker",
                     "slurm", "aws_ec2", "azure_fr"
        **kwargs: Worker-type specific configuration parameters

    Common kwargs (all worker types):
        ras_exe_path: Path to HEC-RAS.exe on target machine (required)
        worker_id: Unique identifier (auto-generated if not provided)

    PsExec-specific kwargs:
        hostname: Remote machine hostname or IP (required)
        share_path: UNC path to network share (required, e.g., \\\\hostname\\RasRemote)
        local_path: Local path on remote machine corresponding to share_path (optional).
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
        # Initialize PsExec worker (RECOMMENDED - no credentials, uses Windows auth)
        worker = init_ras_worker(
            "psexec",
            hostname="WORKSTATION-01",
            share_path=r"\\\\WORKSTATION-01\\RasRemote",
            ras_exe_path=r"C:\\Program Files\\HEC\\HEC-RAS\\6.3\\RAS.exe",
            session_id=2  # Check with "query user" on remote machine
        )

        # Initialize local worker (future)
        # local_worker = init_ras_worker("local", ras_exe_path=r"C:\\...\\RAS.exe")
    """
    logger.info(f"Initializing {worker_type} worker")

    # Validate worker_type
    valid_types = ["psexec", "local", "ssh", "winrm", "docker", "slurm", "aws_ec2", "azure_fr"]
    if worker_type not in valid_types:
        raise ValueError(
            f"Invalid worker_type '{worker_type}'. "
            f"Valid types: {', '.join(valid_types)}"
        )

    # Auto-generate worker_id if not provided
    if "worker_id" not in kwargs:
        import uuid
        kwargs["worker_id"] = f"{worker_type}_{uuid.uuid4().hex[:8]}"

    # Route to appropriate worker class
    if worker_type == "psexec":
        return _init_psexec_worker(**kwargs)
    elif worker_type == "local":
        return _init_local_worker(**kwargs)
    elif worker_type == "ssh":
        return _init_ssh_worker(**kwargs)
    elif worker_type == "winrm":
        return _init_winrm_worker(**kwargs)
    elif worker_type == "docker":
        return _init_docker_worker(**kwargs)
    elif worker_type == "slurm":
        return _init_slurm_worker(**kwargs)
    elif worker_type == "aws_ec2":
        return _init_aws_ec2_worker(**kwargs)
    elif worker_type == "azure_fr":
        return _init_azure_fr_worker(**kwargs)


# =============================================================================
# WORKER INITIALIZATION FUNCTIONS
# =============================================================================

def _init_psexec_worker(**kwargs) -> PsexecWorker:
    """
    Initialize PsExec worker.

    NOTE: Full validation (share access, remote connectivity) is deferred until
    execution time. This prevents false failures during initialization due to
    authentication and UAC complexities.

    Validation performed:
    1. Check PsExec.exe is available locally

    Validation deferred to execution:
    2. Network share accessibility (requires authenticated session)
    3. Remote execution permissions (depends on UAC, firewall, services)
    4. HEC-RAS.exe existence on remote machine

    Returns:
        PsexecWorker: Configured worker ready for execution

    Raises:
        FileNotFoundError: PsExec.exe not found locally
    """
    logger.info(f"Initializing PsExec worker for {kwargs.get('hostname', 'unknown')}")

    # Ensure worker_type is set
    kwargs['worker_type'] = 'psexec'

    # Create worker object (validates required parameters)
    worker = PsexecWorker(**kwargs)

    # Only validate: Find or validate PsExec.exe locally
    if not worker.psexec_path:
        worker.psexec_path = _find_psexec()
    else:
        if not Path(worker.psexec_path).exists():
            raise FileNotFoundError(f"PsExec.exe not found at {worker.psexec_path}")

    logger.debug(f"Using PsExec at: {worker.psexec_path}")

    # Log configuration but don't test yet (obfuscate credentials)
    logger.info(f"PsExec worker configured:")
    logger.info(f"  Hostname: {worker.hostname}")
    logger.info(f"  Share path: {worker.share_path}")
    logger.info(f"  Local path: {worker.local_path}")
    logger.info(f"  User: {worker.credentials.get('username', '<unknown>')}")
    logger.info(f"  System account: {worker.system_account}")
    logger.info(f"  Session ID: {worker.session_id if not worker.system_account else 'N/A'}")
    logger.info(f"  Process Priority: {worker.process_priority}")
    logger.info(f"  Queue Priority: {worker.queue_priority}")
    logger.warning(
        f"Validation deferred - share access and remote execution will be "
        f"tested during actual plan execution"
    )

    return worker


def _convert_unc_to_local_path(unc_path: str, share_path: str, local_path: str) -> str:
    """
    Convert UNC path to local path on remote machine.

    PsExec executes commands on the remote machine's local filesystem, so UNC paths
    must be converted to the corresponding local paths.

    Args:
        unc_path: Full UNC path (e.g., \\\\192.168.3.8\\RasRemote\\folder\\file.bat)
        share_path: Base share path (e.g., \\\\192.168.3.8\\RasRemote)
        local_path: Local path on remote machine that share_path maps to (e.g., C:\\RasRemote)

    Returns:
        str: Local path on remote machine (e.g., C:\\RasRemote\\folder\\file.bat)

    Example:
        >>> _convert_unc_to_local_path(
        ...     r"\\\\192.168.3.8\\RasRemote\\temp\\file.bat",
        ...     r"\\\\192.168.3.8\\RasRemote",
        ...     r"C:\\RasRemote"
        ... )
        'C:\\\\RasRemote\\\\temp\\\\file.bat'
    """
    # Replace UNC share_path prefix with local_path
    # \\192.168.3.8\RasRemote\folder\file.bat -> C:\RasRemote\folder\file.bat
    if unc_path.startswith(share_path):
        relative_path = unc_path[len(share_path):].lstrip('\\')
        if relative_path:
            result_path = f"{local_path}\\{relative_path}"
        else:
            result_path = local_path
        return result_path
    else:
        raise ValueError(f"UNC path {unc_path} does not start with share_path {share_path}")


def _find_psexec() -> str:
    """
    Find PsExec.exe on the system, downloading if necessary.

    Searches:
    1. System PATH
    2. User profile folder: C:\\Users\\{username}\\psexec\\PsExec.exe
    3. Common installation locations
    4. If not found, downloads to user profile folder

    Returns:
        str: Path to PsExec.exe

    Raises:
        FileNotFoundError: PsExec.exe could not be found or downloaded
    """
    # Check if in PATH
    import shutil
    psexec_path = shutil.which("psexec.exe")
    if psexec_path:
        logger.debug(f"Found PsExec.exe in PATH: {psexec_path}")
        return psexec_path

    # Check user profile folder
    import os
    user_profile = os.path.expanduser("~")
    user_psexec_dir = Path(user_profile) / "psexec"
    user_psexec_exe = user_psexec_dir / "PsExec.exe"

    if user_psexec_exe.exists():
        logger.debug(f"Found PsExec.exe in user profile: {user_psexec_exe}")
        return str(user_psexec_exe)

    # Check common locations
    common_locations = [
        r"C:\PsTools\PsExec.exe",
        r"C:\Windows\System32\PsExec.exe",
        r"C:\Program Files\PsTools\PsExec.exe",
        Path.cwd() / "PsExec.exe"  # Current directory
    ]

    for location in common_locations:
        location_path = Path(location)
        if location_path.exists():
            logger.debug(f"Found PsExec.exe at: {location}")
            return str(location_path)

    # Not found - download to user profile folder
    logger.info("PsExec.exe not found locally. Downloading from Microsoft Sysinternals...")

    try:
        downloaded_path = _download_psexec(user_psexec_dir)
        logger.info(f"PsExec.exe downloaded to: {downloaded_path}")
        return str(downloaded_path)
    except Exception as e:
        raise FileNotFoundError(
            f"PsExec.exe not found and auto-download failed: {e}\n"
            "Please download manually from "
            "https://docs.microsoft.com/en-us/sysinternals/downloads/psexec "
            "and place in PATH or specify psexec_path parameter."
        )


def _download_psexec(target_dir: Path) -> Path:
    """
    Download PsExec.exe from Microsoft Sysinternals.

    Args:
        target_dir: Directory to download PsExec.exe to

    Returns:
        Path: Path to downloaded PsExec.exe

    Raises:
        Exception: Download or extraction failed
    """
    import urllib.request
    import zipfile
    import tempfile

    pstools_url = "https://download.sysinternals.com/files/PSTools.zip"

    # Create target directory
    target_dir.mkdir(parents=True, exist_ok=True)

    # Download to temp file
    logger.info(f"Downloading PSTools.zip from {pstools_url}...")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
        tmp_path = Path(tmp_file.name)
        urllib.request.urlretrieve(pstools_url, tmp_path)

    # Extract PsExec.exe
    logger.info(f"Extracting PsExec.exe to {target_dir}...")
    with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
        # Extract only PsExec.exe
        for file_info in zip_ref.filelist:
            if file_info.filename == "PsExec.exe":
                zip_ref.extract(file_info, target_dir)
                break

    # Cleanup temp file
    tmp_path.unlink()

    # Verify extraction
    psexec_exe = target_dir / "PsExec.exe"
    if not psexec_exe.exists():
        raise FileNotFoundError("PsExec.exe not found in downloaded archive")

    logger.info(f"PsExec.exe successfully downloaded to {psexec_exe}")
    return psexec_exe


def _init_local_worker(**kwargs) -> LocalWorker:
    """Initialize local worker (stub - raises NotImplementedError)."""
    kwargs['worker_type'] = 'local'
    return LocalWorker(**kwargs)


def _init_ssh_worker(**kwargs) -> SshWorker:
    """Initialize SSH worker (stub - raises NotImplementedError)."""
    kwargs['worker_type'] = 'ssh'
    return SshWorker(**kwargs)


def _init_winrm_worker(**kwargs) -> WinrmWorker:
    """Initialize WinRM worker (stub - raises NotImplementedError)."""
    kwargs['worker_type'] = 'winrm'
    return WinrmWorker(**kwargs)


def _init_docker_worker(**kwargs) -> DockerWorker:
    """Initialize Docker worker (stub - raises NotImplementedError)."""
    kwargs['worker_type'] = 'docker'
    return DockerWorker(**kwargs)


def _init_slurm_worker(**kwargs) -> SlurmWorker:
    """Initialize Slurm worker (stub - raises NotImplementedError)."""
    kwargs['worker_type'] = 'slurm'
    return SlurmWorker(**kwargs)


def _init_aws_ec2_worker(**kwargs) -> AwsEc2Worker:
    """Initialize AWS EC2 worker (stub - raises NotImplementedError)."""
    kwargs['worker_type'] = 'aws_ec2'
    return AwsEc2Worker(**kwargs)


def _init_azure_fr_worker(**kwargs) -> AzureFrWorker:
    """Initialize Azure Functions worker (stub - raises NotImplementedError)."""
    kwargs['worker_type'] = 'azure_fr'
    return AzureFrWorker(**kwargs)


# =============================================================================
# DISTRIBUTED EXECUTION FUNCTION
# =============================================================================

@log_call
def compute_parallel_remote(
    plan_number: Union[str, Number, List[Union[str, Number]], None] = None,
    workers: List[RasWorker] = None,
    ras_object: Optional[RasPrj] = None,
    scheduling: str = "round_robin",
    num_cores: int = 2,
    dest_folder: Union[str, Path, None] = None,
    clear_geompre: bool = False,
    overwrite_dest: bool = False
) -> Dict[str, bool]:
    """
    Execute HEC-RAS plans across distributed worker pool.

    This function orchestrates parallel execution across multiple workers of
    potentially different types (local, remote, cloud). Plans are assigned to
    workers based on scheduling strategy, executed in parallel, and results
    are collected to a destination folder.

    Args:
        plan_number: Plan number(s) to execute. Can be:
                    - Single plan: "01" or 1
                    - Multiple plans: ["01", "02", "03"]
                    - None: Execute all plans in project
        workers: List of initialized RasWorker objects (from init_ras_worker)
        ras_object: RAS project object. If None, uses global ras instance
        scheduling: Plan assignment strategy:
                   - "round_robin": Cycle through workers (default)
                   - "least_loaded": Assign to least busy worker [FUTURE]
                   - "burst": Prefer local, burst to remote when needed [FUTURE]
        num_cores: Number of CPU cores per plan execution
        dest_folder: Destination folder for results collection
                    - String: Created in project parent directory
                    - Path: Used as-is
                    - None: Results collected to "{project}_[Distributed]"
        clear_geompre: Clear geometry preprocessor files before execution
        overwrite_dest: Overwrite destination folder if exists

    Returns:
        Dict[str, bool]: Execution results - {plan_number: success_bool}

    Raises:
        ValueError: Invalid parameters (no workers, no plans, etc.)
        RuntimeError: Execution errors

    Example:
        # Initialize heterogeneous worker pool
        workers = [
            init_ras_worker("psexec", hostname="PC1", ...),
            init_ras_worker("psexec", hostname="PC2", ...),
        ]

        # Execute plans across pool
        results = compute_parallel_remote(
            plan_number=["01", "02", "03", "04"],
            workers=workers,
            ras_object=ras,
            dest_folder="distributed_results"
        )

        # Check results
        for plan, success in results.items():
            print(f"Plan {plan}: {'Success' if success else 'Failed'}")
    """
    logger.info(f"Starting distributed execution with {len(workers)} workers")

    # Validate inputs
    if not workers:
        raise ValueError("At least one worker must be provided")

    # Get RAS object
    ras_obj = ras_object if ras_object is not None else ras
    if not ras_obj.initialized:
        raise ValueError("RAS project not initialized. Call init_ras_project() first.")

    # Parse plan numbers
    if plan_number is None:
        # Execute all plans
        plan_numbers = [str(p).zfill(2) for p in ras_obj.plan_df.index]
    elif isinstance(plan_number, (list, tuple)):
        plan_numbers = [str(p).zfill(2) for p in plan_number]
    else:
        plan_numbers = [str(plan_number).zfill(2)]

    logger.info(f"Executing {len(plan_numbers)} plans: {plan_numbers}")

    # Validate scheduling strategy
    valid_scheduling = ["round_robin", "least_loaded", "burst"]
    if scheduling not in valid_scheduling:
        logger.warning(
            f"Invalid scheduling '{scheduling}', using 'round_robin'. "
            f"Valid: {valid_scheduling}"
        )
        scheduling = "round_robin"

    # Only round_robin is currently implemented
    if scheduling != "round_robin":
        logger.warning(
            f"Scheduling '{scheduling}' not yet implemented, using 'round_robin'"
        )
        scheduling = "round_robin"

    # Expand workers into sub-workers based on max_parallel_plans
    # This enables parallel execution ON each remote machine
    sub_workers = _expand_workers_to_sub_workers(workers)

    logger.info(f"Expanded to {len(sub_workers)} sub-workers total:")
    for sw in sub_workers:
        logger.info(f"  {sw['parent'].worker_id} sub-worker #{sw['sub_id']} (queue {sw['queue_priority']})")

    # Assign plans to sub-workers (round-robin with wave scheduling)
    plan_assignments = _assign_plans_to_sub_workers(plan_numbers, sub_workers)

    logger.info("Plan assignments:")
    for idx, (sub_worker, assigned_plans) in plan_assignments.items():
        parent = sub_worker['parent']
        sub_id = sub_worker['sub_id']
        queue_p = sub_worker.get('queue_priority', 0)
        if assigned_plans:  # Only show workers with assignments
            logger.info(f"  {parent.worker_id}-SW{sub_id} (Q{queue_p}): {assigned_plans}")

    # Execute plans in parallel using ThreadPoolExecutor
    # Use len(sub_workers) for true parallelism across all sub-workers
    execution_results = {}

    with ThreadPoolExecutor(max_workers=len(sub_workers)) as executor:
        # Submit all plan executions
        future_to_plan = {}

        for idx, (sub_worker, assigned_plans) in plan_assignments.items():
            for plan in assigned_plans:
                future = executor.submit(
                    _execute_plan_on_sub_worker,
                    sub_worker,
                    plan,
                    ras_obj,
                    clear_geompre
                )
                future_to_plan[future] = (sub_worker, plan)

        # Collect results as they complete
        for future in as_completed(future_to_plan):
            sub_worker, plan = future_to_plan[future]
            parent = sub_worker['parent']
            sub_id = sub_worker['sub_id']
            try:
                success = future.result()
                execution_results[plan] = success
                status = "SUCCESS" if success else "FAILED"
                logger.info(f"Plan {plan} on {parent.worker_id}-SW{sub_id}: {status}")
            except Exception as e:
                logger.error(f"Plan {plan} on {parent.worker_id}-SW{sub_id} raised exception: {e}")
                execution_results[plan] = False

    # Collect results to destination folder
    if dest_folder is not None:
        logger.info(f"Collecting results to {dest_folder}")
        _collect_distributed_results(
            plan_assignments,
            ras_obj,
            dest_folder,
            overwrite_dest
        )

    # Log summary
    success_count = sum(1 for success in execution_results.values() if success)
    total_count = len(execution_results)
    logger.info(
        f"Distributed execution complete: {success_count}/{total_count} plans succeeded"
    )

    return execution_results


def _expand_workers_to_sub_workers(workers: List[RasWorker]) -> List[Dict]:
    """
    Expand workers into sub-workers based on max_parallel_plans.

    Each worker with max_parallel_plans > 1 is expanded into multiple virtual
    sub-workers that can execute plans in parallel on the same machine.

    Args:
        workers: List of initialized workers

    Returns:
        List of sub-worker dicts with 'parent' (worker), 'sub_id', 'cores', and 'queue_priority'
    """
    sub_workers = []

    for worker in workers:
        max_parallel = getattr(worker, 'max_parallel_plans', 1) or 1
        cores_per_plan = getattr(worker, 'cores_per_plan', 4)
        queue_priority = getattr(worker, 'queue_priority', 0)

        for sub_id in range(1, max_parallel + 1):
            sub_worker = {
                'parent': worker,
                'sub_id': sub_id,
                'cores': cores_per_plan,
                'queue_priority': queue_priority
            }
            sub_workers.append(sub_worker)

    return sub_workers


def _assign_plans_to_sub_workers(
    plan_numbers: List[str],
    sub_workers: List[Dict]
) -> Dict[int, tuple]:
    """
    Assign plans to sub-workers using queue-aware wave scheduling.

    Queue Priority Logic:
    - Workers are grouped by queue_priority (0, 1, 2, ...)
    - Queue level 0 is fully utilized before queue level 1, etc.
    - Within each queue level, wave scheduling applies:
      - Fill sub-worker #1 on all machines first, then #2, etc.
      - This ensures balanced load across machines before going deep

    This enables tiered bursting: local workers (queue 0) are used first,
    then remote workers (queue 1), then cloud workers (queue 2), etc.

    Args:
        plan_numbers: List of plan numbers to assign
        sub_workers: List of sub-worker dicts from _expand_workers_to_sub_workers
                    Each dict has 'parent', 'sub_id', 'cores', 'queue_priority'

    Returns:
        Dict mapping index to (sub_worker_dict, plan_list) tuples
    """
    # Initialize assignments for all sub-workers
    assignments = {i: (sw, []) for i, sw in enumerate(sub_workers)}

    if not sub_workers or not plan_numbers:
        return assignments

    # Group sub-workers by queue_priority
    queue_groups = {}
    for i, sw in enumerate(sub_workers):
        q = sw.get('queue_priority', 0)
        if q not in queue_groups:
            queue_groups[q] = []
        queue_groups[q].append(i)

    # Sort queue levels
    sorted_queue_levels = sorted(queue_groups.keys())

    # Create ordered list of sub-worker indices respecting queue priority
    # Within each queue level, order by sub_id for wave scheduling
    ordered_indices = []
    for q in sorted_queue_levels:
        # Get indices at this queue level
        indices_at_level = queue_groups[q]
        # Sort by sub_id within each queue level for wave scheduling
        # (sub-worker #1 on all machines first, then #2, etc.)
        indices_at_level_sorted = sorted(
            indices_at_level,
            key=lambda i: (sub_workers[i]['sub_id'], sub_workers[i]['parent'].worker_id)
        )
        ordered_indices.extend(indices_at_level_sorted)

    # Assign plans using the ordered indices
    # This naturally fills queue level 0 first, then 1, etc.
    for plan_idx, plan in enumerate(plan_numbers):
        sw_idx = ordered_indices[plan_idx % len(ordered_indices)]
        assignments[sw_idx][1].append(plan)

    return assignments


def _assign_plans_round_robin(
    plan_numbers: List[str],
    workers: List[RasWorker]
) -> Dict[int, tuple]:
    """
    Assign plans to workers using round-robin strategy.

    Args:
        plan_numbers: List of plan numbers to assign
        workers: List of available workers

    Returns:
        Dict mapping worker index to (worker, plan_list) tuples
    """
    # Use worker index as key since dataclasses aren't hashable
    assignments = {i: (worker, []) for i, worker in enumerate(workers)}
    worker_indices = cycle(range(len(workers)))

    for plan in plan_numbers:
        worker_idx = next(worker_indices)
        assignments[worker_idx][1].append(plan)

    return assignments


def _execute_plan_on_sub_worker(
    sub_worker: Dict,
    plan_number: str,
    ras_obj: RasPrj,
    clear_geompre: bool
) -> bool:
    """
    Execute a plan on a sub-worker (virtual worker instance).

    Args:
        sub_worker: Sub-worker dict with 'parent', 'sub_id', 'cores'
        plan_number: Plan number to execute
        ras_obj: RAS project object
        clear_geompre: Clear geometry preprocessor files

    Returns:
        bool: True if execution succeeded
    """
    parent_worker = sub_worker['parent']
    sub_id = sub_worker['sub_id']
    cores = sub_worker['cores']

    logger.info(f"Executing plan {plan_number} on {parent_worker.worker_id}-SW{sub_id}")

    try:
        if parent_worker.worker_type == "psexec":
            return _execute_psexec_plan(
                parent_worker,
                plan_number,
                ras_obj,
                cores,
                clear_geompre,
                sub_worker_id=sub_id
            )
        elif parent_worker.worker_type == "local":
            return _execute_local_plan(
                parent_worker,
                plan_number,
                ras_obj,
                cores,
                clear_geompre
            )
        else:
            logger.error(f"Worker type '{parent_worker.worker_type}' not yet implemented")
            return False

    except Exception as e:
        logger.error(f"Error executing plan {plan_number} on {parent_worker.worker_id}-SW{sub_id}: {e}")
        return False


def _execute_plan_on_worker(
    worker: RasWorker,
    plan_number: str,
    ras_obj: RasPrj,
    num_cores: int,
    clear_geompre: bool
) -> bool:
    """
    Execute a single plan on a specific worker (legacy function, kept for compatibility).

    This function dispatches to worker-type-specific execution logic.

    Args:
        worker: Worker to execute on
        plan_number: Plan number to execute
        ras_obj: RAS project object
        num_cores: Number of cores for execution
        clear_geompre: Clear geometry preprocessor files

    Returns:
        bool: True if execution succeeded, False otherwise
    """
    logger.info(f"Executing plan {plan_number} on {worker.worker_id}")

    try:
        if worker.worker_type == "psexec":
            return _execute_psexec_plan(
                worker,
                plan_number,
                ras_obj,
                num_cores,
                clear_geompre,
                sub_worker_id=1
            )
        elif worker.worker_type == "local":
            return _execute_local_plan(
                worker,
                plan_number,
                ras_obj,
                num_cores,
                clear_geompre
            )
        else:
            logger.error(f"Worker type '{worker.worker_type}' not yet implemented")
            return False

    except Exception as e:
        logger.error(f"Error executing plan {plan_number} on {worker.worker_id}: {e}")
        return False


# =============================================================================
# PSEXEC EXECUTION IMPLEMENTATION
# =============================================================================

def _authenticate_network_share(share_path: str, username: str, password: str) -> bool:
    """
    Authenticate to a network share using net use command.

    This establishes a connection to the remote share using the provided credentials,
    allowing subsequent file operations (copy, mkdir) to succeed.

    Args:
        share_path: UNC path to share (e.g., \\\\hostname\\ShareName)
        username: Username for authentication (e.g., .\\user or DOMAIN\\user)
        password: Password for authentication

    Returns:
        bool: True if authentication succeeded or share already accessible
    """
    # Extract base share path (\\hostname\ShareName) from full path
    share_parts = share_path.strip('\\').split('\\')
    if len(share_parts) >= 2:
        base_share = f"\\\\{share_parts[0]}\\{share_parts[1]}"
    else:
        base_share = share_path

    # First, try to disconnect any existing connection (ignore errors)
    try:
        subprocess.run(
            ["net", "use", base_share, "/delete", "/y"],
            capture_output=True,
            timeout=30
        )
    except Exception:
        pass

    # Establish new connection with credentials
    try:
        result = subprocess.run(
            ["net", "use", base_share, f"/user:{username}", password],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            logger.debug(f"Successfully authenticated to {base_share}")
            return True
        else:
            # Check if already connected (error 1219 = multiple connections not allowed)
            if "1219" in result.stderr or "already" in result.stderr.lower():
                logger.debug(f"Share {base_share} already connected")
                return True
            logger.error(f"Failed to authenticate to {base_share}: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout authenticating to {base_share}")
        return False
    except Exception as e:
        logger.error(f"Error authenticating to {base_share}: {e}")
        return False


def _execute_psexec_plan(
    worker: PsexecWorker,
    plan_number: str,
    ras_obj: RasPrj,
    num_cores: int,
    clear_geompre: bool,
    sub_worker_id: int = 1
) -> bool:
    """
    Execute a plan on a PsExec worker.

    Execution flow:
    1. Authenticate to network share (if credentials provided)
    2. Create temporary worker folder in network share
    3. Copy project to worker folder
    4. Generate batch file for HEC-RAS execution
    5. Execute batch file via PsExec
    6. Monitor execution (poll for .hdf file)
    7. Copy results back
    8. Cleanup temporary folder

    Args:
        worker: PsexecWorker instance
        plan_number: Plan number to execute
        ras_obj: RAS project object
        num_cores: Number of cores
        clear_geompre: Clear geompre files
        sub_worker_id: Sub-worker ID for parallel execution (default 1)

    Returns:
        bool: True if successful
    """
    logger.info(f"Starting PsExec execution of plan {plan_number} (sub-worker #{sub_worker_id})")

    project_folder = Path(ras_obj.project_folder)
    project_name = ras_obj.project_name

    # Step 0: Authenticate to network share using provided credentials
    # This allows subsequent file operations (mkdir, copy) to work
    if worker.credentials:
        auth_success = _authenticate_network_share(
            worker.share_path,
            worker.credentials["username"],
            worker.credentials["password"]
        )
        if not auth_success:
            logger.error(f"Failed to authenticate to share {worker.share_path}")
            return False

    # Step 1: Create temporary worker folder with sub-worker ID
    import uuid
    worker_temp_folder = Path(worker.share_path) / f"{project_name}_{plan_number}_SW{sub_worker_id}_{uuid.uuid4().hex[:8]}"
    worker_temp_folder.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created worker folder: {worker_temp_folder}")

    try:
        # Step 2: Copy project to worker folder
        logger.info(f"Copying project to {worker_temp_folder}")
        shutil.copytree(project_folder, worker_temp_folder / project_name, dirs_exist_ok=True)

        worker_project_path = worker_temp_folder / project_name
        prj_file = list(worker_project_path.glob("*.prj"))[0]
        plan_file = worker_project_path / f"{project_name}.p{plan_number}"

        # Step 3: Generate batch file
        # Convert UNC paths to local paths for batch file content
        prj_file_local = _convert_unc_to_local_path(str(prj_file), worker.share_path, worker.local_path)
        plan_file_local = _convert_unc_to_local_path(str(plan_file), worker.share_path, worker.local_path)

        batch_file = worker_temp_folder / f"run_plan_{plan_number}.bat"
        batch_content = f'"{worker.ras_exe_path}" -c "{prj_file_local}" "{plan_file_local}"'
        batch_file.write_text(batch_content)
        logger.debug(f"Created batch file: {batch_file}")
        logger.debug(f"Batch file content: {batch_content}")

        # Step 4: Execute via PsExec
        # Build PsExec command
        psexec_cmd = [
            worker.psexec_path,
            f"\\\\{worker.hostname}",
            "-u", worker.credentials["username"],
            "-p", worker.credentials["password"],
            "-accepteula"
        ]

        # Add -h for elevated token (helps with UAC on Vista+)
        # This allows the process to run with full admin rights
        psexec_cmd.append("-h")

        # Add session or system account flag
        if worker.system_account:
            psexec_cmd.append("-s")
        else:
            psexec_cmd.extend(["-i", str(worker.session_id)])

        # Add process priority flag (OS-level CPU priority)
        priority_flags = {
            "low": "-low",
            "below normal": "-belownormal",
            "normal": ""
        }
        priority_flag = priority_flags.get(worker.process_priority, "")
        if priority_flag:
            psexec_cmd.append(priority_flag)

        # Add batch file path (convert UNC to local path on remote machine)
        # PsExec running as SYSTEM cannot access UNC paths
        # Convert: \\192.168.3.8\RasRemote\folder\file.bat -> C:\RasRemote\folder\file.bat
        batch_file_local = _convert_unc_to_local_path(str(batch_file), worker.share_path, worker.local_path)
        psexec_cmd.append(batch_file_local)
        logger.debug(f"Batch file UNC path: {batch_file}")
        logger.debug(f"Batch file local path: {batch_file_local}")

        # Log command with obfuscated credentials
        cmd_display = ' '.join(psexec_cmd[:2]) + " -u <user> -p <password> -accepteula -h ..."
        logger.info(f"Executing: {cmd_display}")

        # Execute PsExec command
        result = subprocess.run(
            psexec_cmd,
            capture_output=True,
            text=True,
            timeout=7200  # 2 hour timeout
        )

        # Step 5: Check for HDF file (indicates completion)
        hdf_file = worker_project_path / f"{project_name}.p{plan_number}.hdf"

        # Poll for HDF file creation (it may take time after batch completes)
        max_wait = 60  # Wait up to 60 seconds after batch completes
        wait_interval = 5
        elapsed = 0

        while not hdf_file.exists() and elapsed < max_wait:
            time.sleep(wait_interval)
            elapsed += wait_interval
            logger.debug(f"Waiting for HDF file... ({elapsed}s)")

        if not hdf_file.exists():
            logger.error(f"HDF file not created: {hdf_file}")
            logger.error(f"PsExec stdout: {result.stdout}")
            logger.error(f"PsExec stderr: {result.stderr}")
            return False

        logger.info(f"HDF file created successfully: {hdf_file}")

        # Step 6: Copy results back to original project
        # Copy HDF file back
        dest_hdf = project_folder / hdf_file.name
        shutil.copy2(hdf_file, dest_hdf)
        logger.info(f"Copied results to {dest_hdf}")

        # Step 7: Cleanup
        shutil.rmtree(worker_temp_folder, ignore_errors=True)
        logger.debug(f"Cleaned up worker folder: {worker_temp_folder}")

        return True

    except Exception as e:
        logger.error(f"Error in PsExec execution: {e}")
        # Attempt cleanup
        try:
            if worker_temp_folder.exists():
                shutil.rmtree(worker_temp_folder, ignore_errors=True)
        except:
            pass
        return False


def _execute_local_plan(
    worker: LocalWorker,
    plan_number: str,
    ras_obj: RasPrj,
    num_cores: int,
    clear_geompre: bool
) -> bool:
    """
    Execute a plan on a local worker (stub - not yet implemented).

    When implemented, this will call RasCmdr.compute_plan() internally.
    """
    raise NotImplementedError(
        "LocalWorker execution not yet implemented. "
        "Use RasCmdr.compute_plan() directly for local execution."
    )


def _collect_distributed_results(
    plan_assignments: Dict[int, tuple],
    ras_obj: RasPrj,
    dest_folder: Union[str, Path],
    overwrite_dest: bool
):
    """
    Collect distributed execution results to destination folder.

    Args:
        plan_assignments: Dict mapping worker index to (worker, plan_list) tuples
        ras_obj: RAS project object
        dest_folder: Destination folder for results
        overwrite_dest: Overwrite if exists
    """
    logger.info("Collecting distributed results")

    project_folder = Path(ras_obj.project_folder)
    project_name = ras_obj.project_name

    # Determine destination folder path
    if isinstance(dest_folder, str):
        dest_path = project_folder.parent / dest_folder
    else:
        dest_path = Path(dest_folder)

    # Create or validate destination
    if dest_path.exists():
        if not overwrite_dest:
            logger.warning(f"Destination exists: {dest_path}. Not overwriting.")
            return
        else:
            shutil.rmtree(dest_path)

    dest_path.mkdir(parents=True, exist_ok=True)

    # Copy entire project to destination
    dest_project = dest_path / project_name
    shutil.copytree(project_folder, dest_project, dirs_exist_ok=True)

    logger.info(f"Results collected to: {dest_project}")



