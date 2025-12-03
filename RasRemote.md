# RasRemote - Distributed HEC-RAS Execution Guide

This guide covers the remote and distributed execution capabilities of ras-commander, enabling HEC-RAS simulations to run across local machines, remote Windows workstations, and Linux Docker containers.

## Table of Contents

1. [Overview](#overview)
2. [Worker Types](#worker-types)
3. [LocalWorker](#localworker)
4. [PsexecWorker](#psexecworker)
5. [DockerWorker](#dockerworker)
6. [API Reference](#api-reference)
7. [Examples](#examples)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The `ras_commander.remote` module provides a unified interface for executing HEC-RAS plans across different compute environments:

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Initialize project
ras = init_ras_project(r"C:\Projects\MyProject", "6.6")

# Create workers (can mix different types)
local_worker = init_ras_worker("local", cores_total=8, cores_per_plan=4)
docker_worker = init_ras_worker("docker", docker_image="hecras:6.6")

# Execute plans across all workers
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04"],
    workers=[local_worker, docker_worker],
    ras_object=ras
)
```

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    compute_parallel_remote()                │
├─────────────────────────────────────────────────────────────┤
│                      Worker Pool                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ LocalWorker │  │PsexecWorker │  │DockerWorker │   ...   │
│  │  (Windows)  │  │  (Remote)   │  │  (Linux)    │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         ▼                ▼                ▼                 │
│    Local HEC-RAS    PsExec to        Docker Container      │
│    Execution        Remote PC        with Linux RAS        │
└─────────────────────────────────────────────────────────────┘
```

---

## Worker Types

| Worker | Platform | Use Case | Requirements |
|--------|----------|----------|--------------|
| LocalWorker | Windows | Parallel local execution | HEC-RAS installed |
| PsexecWorker | Windows | Remote Windows machines | PsExec, network access |
| DockerWorker | Linux | Container-based execution | Docker Desktop |
| SshWorker | Linux | Remote Linux machines | (stub - not implemented) |
| SlurmWorker | HPC | Cluster computing | (stub - not implemented) |

---

## LocalWorker

Execute plans in parallel on the local Windows machine using multiple CPU cores.

### Usage

```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote

worker = init_ras_worker(
    "local",
    cores_total=16,      # Total cores available
    cores_per_plan=4,    # Cores per simulation
    queue_priority=0     # Lower = higher priority
)

# This worker can run 4 plans in parallel (16/4)
results = compute_parallel_remote(["01", "02", "03", "04"], workers=[worker])
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| cores_total | int | None | Total CPU cores to use |
| cores_per_plan | int | 4 | Cores allocated per plan |
| queue_priority | int | 0 | Scheduling priority (lower = first) |

---

## PsexecWorker

Execute plans on remote Windows machines via PsExec over network shares.

### Prerequisites

1. **PsExec** from Sysinternals (auto-downloaded if missing)
2. **Network share** on remote machine for file transfer
3. **Administrative access** to remote machine
4. **HEC-RAS installed** on remote machine

### Remote Machine Setup

See [REMOTE_WORKER_SETUP_GUIDE.md](feature_dev_notes/RasRemote/REMOTE_WORKER_SETUP_GUIDE.md) for detailed setup instructions.

Quick checklist:
- [ ] Enable network share (e.g., `\\REMOTE\RasRemote`)
- [ ] Add user to Administrators group
- [ ] Enable Remote Registry service
- [ ] Set `LocalAccountTokenFilterPolicy=1` in registry
- [ ] Configure Group Policy for network access

### Usage

```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote

worker = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    credentials={"username": "admin", "password": "secret"},
    ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.6\RAS.exe",
    session_id=2,        # User session ID (important!)
    cores_total=8,
    cores_per_plan=4
)

results = compute_parallel_remote(["01", "02"], workers=[worker])
```

### Critical: Session ID

HEC-RAS requires a user session to run properly. Use `session_id=2` for workstations (not `system_account=True`).

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| hostname | str | Required | Remote machine IP/hostname |
| share_path | str | Required | UNC path to network share |
| credentials | dict | Required | `{"username": "...", "password": "..."}` |
| ras_exe_path | str | Required | Path to RAS.exe on remote machine |
| session_id | int | 2 | Windows session ID |
| cores_total | int | None | Total cores on remote machine |
| cores_per_plan | int | 4 | Cores per simulation |

---

## DockerWorker

Execute plans in Linux Docker containers using native HEC-RAS Linux binaries.

### Prerequisites

1. **Docker Desktop** installed and running
   - Download: https://www.docker.com/products/docker-desktop
   - Ensure Linux containers mode is enabled

2. **Build the Docker image** (one-time setup)

### Building Docker Images

Use the setup script to download HEC-RAS Linux binaries and build Docker images:

```bash
# Navigate to the docker folder
cd ras_commander/remote/docker

# List available versions
python setup_docker.py --list

# Build specific version (downloads from HEC website)
python setup_docker.py --version 6.6

# Build from local Windows installation (for 6.7 which includes Linux)
python setup_docker.py --version 6.7 --ras-install "C:\Program Files (x86)\HEC\HEC-RAS\6.7 Beta 5"

# Build all versions
python setup_docker.py --version all
```

### Available HEC-RAS Linux Versions

| Version | Download Source | Base Image | Notes |
|---------|----------------|------------|-------|
| 5.07 | [HEC Download](https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_507_linux.zip) | CentOS 7 | Oldest supported |
| 6.10 | [HEC Download](https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_610_Linux.zip) | Rocky Linux 8 | |
| 6.5 | [HEC Download](https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v65.zip) | Rocky Linux 8 | |
| 6.6 | [HEC Download](https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v66.zip) | Rocky Linux 8 | Current stable |
| 6.7 | Windows installer | Rocky Linux 8 | Beta - included with Windows installer |

### Docker Image Sizes

| Version | Image Size | Notes |
|---------|------------|-------|
| 6.6 | ~2.75 GB | Includes Intel MKL for AVX512 |
| 6.7 | ~2.58 GB | Includes Intel MKL for AVX512 |

### Local Docker Usage

```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote

worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cores_total=8,
    cores_per_plan=4,
    max_runtime_minutes=60,
    preprocess_on_host=True  # Run preprocessing on Windows first
)

results = compute_parallel_remote(["01", "02"], workers=[worker])
```

### Remote Docker Usage

Execute simulations on Docker containers running on remote machines:

```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote

worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    docker_host="tcp://192.168.3.8:2375",  # Remote Docker daemon
    share_path=r"\\192.168.3.8\RasRemote",  # UNC path for file transfer
    remote_staging_path=r"C:\RasRemote",    # Path on Docker host
    cores_total=8,
    cores_per_plan=4,
    max_runtime_minutes=60
)

results = compute_parallel_remote(["01", "02"], workers=[worker])
```

### Remote Docker Host Setup

To enable remote Docker execution on a Windows machine with Docker Desktop:

1. **Enable TCP daemon** in Docker Desktop:
   - Settings → General → Check "Expose daemon on tcp://localhost:2375 without TLS"
   - Or configure Docker Desktop for remote access via `daemon.json`

2. **Configure Windows Firewall** to allow port 2375

3. **Create network share** (e.g., `\\HOSTNAME\RasRemote` → `C:\RasRemote`)

4. **Build Docker images** on the remote machine:
   ```bash
   cd ras_commander/remote/docker
   python setup_docker.py --version 6.6
   ```

### Two-Step Workflow

The DockerWorker uses a two-step workflow because Linux HEC-RAS requires preprocessing:

1. **Windows Preprocessing**: Creates `.tmp.hdf` file with preprocessed geometry
2. **Linux Execution**: Runs the actual simulation in Docker container

This happens automatically when `preprocess_on_host=True` (default).

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| docker_image | str | Required | Docker image name (e.g., "hecras:6.6") |
| docker_host | str | None | Docker daemon URL (e.g., "tcp://host:2375") |
| share_path | str | None | UNC path for remote file transfer |
| remote_staging_path | str | None | Path on Docker host for volume mounts |
| cores_total | int | None | CPU cores available on Docker host |
| cores_per_plan | int | 4 | Cores per simulation |
| max_runtime_minutes | int | 480 | Timeout (default 8 hours) |
| preprocess_on_host | bool | True | Run Windows preprocessing first |
| cpu_limit | str | None | Container CPU limit (e.g., "4") |
| memory_limit | str | None | Container memory limit (e.g., "8g") |

---

## API Reference

### init_ras_worker()

Factory function to create and validate any worker type.

```python
from ras_commander.remote import init_ras_worker

worker = init_ras_worker(
    worker_type,     # "local", "psexec", "docker", etc.
    **kwargs         # Worker-specific parameters
)
```

### compute_parallel_remote()

Execute plans across multiple workers with round-robin scheduling.

```python
from ras_commander.remote import compute_parallel_remote

results = compute_parallel_remote(
    plan_numbers,        # str or List[str] - plans to execute
    workers,             # List[RasWorker] - worker pool
    ras_object=None,     # RasPrj object (uses global if None)
    num_cores=4,         # Cores per execution
    clear_geompre=False, # Clear geometry preprocessor
    max_concurrent=None, # Max concurrent executions
    autoclean=True       # Delete temp folders after
)
```

**Returns**: `Dict[str, ExecutionResult]`

### ExecutionResult

```python
@dataclass
class ExecutionResult:
    plan_number: str       # Plan that was executed
    worker_id: str         # Worker that executed it
    success: bool          # True if successful
    hdf_path: str          # Path to output HDF (if successful)
    error_message: str     # Error message (if failed)
    execution_time: float  # Seconds
```

---

## Examples

### Mixed Worker Pool

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Initialize project
ras = init_ras_project(r"C:\Projects\FloodStudy", "6.6")

# Create mixed worker pool
workers = [
    # Local Windows execution (4 parallel slots)
    init_ras_worker("local", cores_total=16, cores_per_plan=4, queue_priority=0),

    # Remote Windows machine
    init_ras_worker("psexec",
        hostname="192.168.1.50",
        share_path=r"\\192.168.1.50\RasRemote",
        credentials={"username": "admin", "password": "pass"},
        ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.6\RAS.exe",
        session_id=2,
        cores_total=8,
        cores_per_plan=4,
        queue_priority=1  # Lower priority than local
    ),

    # Docker Linux container
    init_ras_worker("docker",
        docker_image="hecras:6.6",
        cores_total=8,
        cores_per_plan=4,
        queue_priority=2  # Lowest priority
    )
]

# Execute 12 plans across all workers
results = compute_parallel_remote(
    [f"{i:02d}" for i in range(1, 13)],
    workers=workers,
    ras_object=ras
)

# Print results
for plan_num, result in results.items():
    status = "SUCCESS" if result.success else "FAILED"
    print(f"Plan {plan_num}: {status} ({result.worker_id}, {result.execution_time:.1f}s)")
```

### Docker-Only Batch Processing

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

ras = init_ras_project(r"C:\Projects\Sensitivity", "6.6")

# Create Docker worker with resource limits
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cores_total=16,
    cores_per_plan=4,
    max_runtime_minutes=120,
    memory_limit="16g"
)

# Execute all plans in project
all_plans = list(ras.plan_df['plan_number'])
results = compute_parallel_remote(all_plans, workers=[worker])

# Summarize
successful = sum(1 for r in results.values() if r.success)
print(f"Completed: {successful}/{len(all_plans)} plans")
```

---

## Troubleshooting

### Docker Issues

**"Docker image not found"**
```bash
python ras_commander/remote/docker/setup_docker.py --version 6.6
```

**"Docker daemon unreachable"**
- Start Docker Desktop
- Ensure Linux containers mode is enabled

**Container exits immediately**
- Check container logs: `docker logs <container_id>`
- Verify `.tmp.hdf` file exists (preprocessing may have failed)

**CRLF line ending errors**
- The Dockerfile includes automatic line ending conversion
- If issues persist, rebuild the image

### PsExec Issues

**"Access denied"**
- Verify credentials are correct
- Ensure user is in Administrators group on remote machine
- Check `LocalAccountTokenFilterPolicy` registry setting

**"Network path not found"**
- Verify network share is accessible: `dir \\HOSTNAME\ShareName`
- Check firewall settings

**HEC-RAS starts but produces no output**
- Use `session_id=2` instead of `system_account=True`
- Verify HEC-RAS is installed and working on remote machine

### General Issues

**Plans fail with "geometry number not found"**
- The plan file may reference a different geometry than expected
- Check plan file for `Geom File=gXX` line

**Results not copied back**
- Verify `autoclean=False` to preserve staging folders for debugging
- Check file permissions on project folder

---

## File Locations

```
ras_commander/
├── remote/
│   ├── __init__.py           # Module exports
│   ├── RasWorker.py          # Base worker class
│   ├── LocalWorker.py        # Local execution
│   ├── PsexecWorker.py       # PsExec remote execution
│   ├── DockerWorker.py       # Docker container execution
│   ├── Execution.py          # compute_parallel_remote()
│   └── docker/
│       ├── setup_docker.py   # Image build script
│       └── scripts/
│           └── run_ras.sh    # Container execution script
```

---

## Additional Resources

- [PsExec Setup Guide](feature_dev_notes/RasRemote/REMOTE_WORKER_SETUP_GUIDE.md)
- [Docker Setup Guide](feature_dev_notes/RasRemote/DOCKER_WORKER_SETUP.md)
- [Example Notebook](examples/23_remote_execution_psexec.ipynb)
