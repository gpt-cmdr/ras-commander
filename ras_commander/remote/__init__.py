"""
Remote and distributed execution for HEC-RAS simulations.

This subpackage provides worker abstractions for executing HEC-RAS
across local, remote, and cloud compute resources.

Available Workers:
    - PsexecWorker: Windows remote execution via PsExec (IMPLEMENTED)
    - LocalWorker: Local parallel execution using RasCmdr.compute_plan() (IMPLEMENTED)
    - DockerWorker: Linux container execution using HEC-RAS 6.6 (IMPLEMENTED, requires: docker)
    - SshWorker: SSH-based remote execution (stub, requires: paramiko)
    - WinrmWorker: WinRM-based remote execution (stub, requires: pywinrm)
    - SlurmWorker: HPC cluster execution (stub)
    - AwsEc2Worker: AWS EC2 cloud execution (stub, requires: boto3)
    - AzureFrWorker: Azure cloud execution (stub, requires: azure-*)

Usage:
    from ras_commander import init_ras_worker, compute_parallel_remote

    # Or import directly from subpackage:
    from ras_commander.remote import init_ras_worker, compute_parallel_remote

    worker = init_ras_worker("psexec", hostname="PC1", ...)
    results = compute_parallel_remote(["01", "02"], workers=[worker])

Installation Options:
    pip install ras-commander                    # Base (includes PsExec worker)
    pip install ras-commander[remote-ssh]        # + SSH worker
    pip install ras-commander[remote-winrm]      # + WinRM worker
    pip install ras-commander[remote-docker]     # + Docker worker
    pip install ras-commander[remote-aws]        # + AWS EC2 worker
    pip install ras-commander[remote-azure]      # + Azure worker
    pip install ras-commander[remote-all]        # All remote backends
"""

# Base class and factory function
from .RasWorker import RasWorker, init_ras_worker, load_workers_from_json

# Worker implementations
from .PsexecWorker import PsexecWorker
from .LocalWorker import LocalWorker
from .SshWorker import SshWorker
from .WinrmWorker import WinrmWorker
from .DockerWorker import DockerWorker
from .SlurmWorker import SlurmWorker
from .AwsEc2Worker import AwsEc2Worker
from .AzureFrWorker import AzureFrWorker

# Execution functions
from .Execution import compute_parallel_remote, ExecutionResult, get_worker_status

__all__ = [
    # Base class
    'RasWorker',

    # Worker implementations
    'PsexecWorker',
    'LocalWorker',
    'SshWorker',
    'WinrmWorker',
    'DockerWorker',
    'SlurmWorker',
    'AwsEc2Worker',
    'AzureFrWorker',

    # Functions
    'init_ras_worker',
    'load_workers_from_json',
    'compute_parallel_remote',
    'ExecutionResult',
    'get_worker_status',
]
