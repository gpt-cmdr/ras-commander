"""
SlurmWorker - Slurm HPC cluster execution worker.

This module implements the SlurmWorker class for executing HEC-RAS on
HPC clusters using the Slurm job scheduler.

IMPLEMENTATION STATUS: STUB - Future Development
"""

from dataclasses import dataclass
from typing import Optional

from .RasWorker import RasWorker
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


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


def init_slurm_worker(**kwargs) -> SlurmWorker:
    """Initialize Slurm worker (stub - raises NotImplementedError)."""
    kwargs['worker_type'] = 'slurm'
    return SlurmWorker(**kwargs)
