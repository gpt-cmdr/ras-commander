---
description: |
  Distributed HEC-RAS execution across remote workers (PsExec, Docker, SSH, cloud).
  Handles worker initialization, queue scheduling, and result aggregation. Use when
  setting up remote execution, distributed computation, cloud workflows, scaling
  HEC-RAS across machines, parallel processing on multiple computers, Windows remote
  execution, container-based execution, session-based remote execution, PsExec
  configuration, Docker worker setup, or multi-machine HEC-RAS workflows.
triggers:
  - remote execution
  - distributed execution
  - PsExec
  - Docker worker
  - SSH execution
  - cloud execution
  - parallel remote
  - multi-machine
  - session_id
  - remote worker
  - worker initialization
  - queue scheduling
  - network share
  - container execution
related_skills:
  - executing-plans
  - processing-hdf-results
related_files:
  - ras_commander/remote/AGENTS.md
  - .claude/rules/hec-ras/remote.md
  - examples/23_remote_execution_psexec.ipynb
cross_references:
  - remote-executor (subagent)
---

# Executing Remote Plans

Execute HEC-RAS plans across multiple remote machines using distributed workers.

## Quick Start

```python
from ras_commander import init_ras_project, init_ras_worker, compute_parallel_remote

# Initialize project
init_ras_project("/path/to/project", "6.6")

# Create PsExec worker (Windows remote)
worker = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    session_id=2,  # CRITICAL: Query with "query session /server:hostname"
    cores_total=16,
    cores_per_plan=4
)

# Execute plans remotely
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03"],
    workers=[worker],
    num_cores=4
)

# Check results
for plan_num, result in results.items():
    if result.success:
        print(f"Plan {plan_num}: SUCCESS ({result.execution_time:.1f}s)")
        print(f"  HDF: {result.hdf_path}")
    else:
        print(f"Plan {plan_num}: FAILED - {result.error_message}")
```

## Core Concepts

### Worker Types

**Local Worker** - Parallel execution on local machine:
```python
worker = init_ras_worker(
    "local",
    worker_folder="C:/RasRemote",
    cores_total=8,
    cores_per_plan=2
)
```

**PsExec Worker** - Windows remote via network share:
```python
worker = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    session_id=2,  # CRITICAL: Must specify session ID
    cores_total=16,
    cores_per_plan=4
)
```

**Docker Worker** - Container execution (local or remote):
```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cores_total=8,
    cores_per_plan=4,
    preprocess_on_host=True  # Windows preprocessing, Linux execution
)
```

### Worker Initialization

**Factory Pattern**:
```python
worker = init_ras_worker(worker_type, **config)
```

All workers support:
- `worker_id` - Unique identifier (auto-generated)
- `ras_exe_path` - Path to RAS.exe (auto-detected from ras object)
- `cores_total` - Total CPU cores available
- `cores_per_plan` - Cores per HEC-RAS instance
- `queue_priority` - Execution priority (0-9, lower first)
- `process_priority` - OS priority ("low", "below normal", "normal")

### Distributed Execution

**Basic Usage**:
```python
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03"],
    workers=[worker1, worker2],
    num_cores=4
)
```

**Parameters**:
- `plan_numbers` - Plans to execute (string or list)
- `workers` - List of initialized workers
- `ras_object` - RasPrj object (uses global ras if None)
- `num_cores` - Cores per plan execution
- `clear_geompre` - Clear geometry preprocessor files
- `max_concurrent` - Max simultaneous executions (default: all worker slots)
- `autoclean` - Delete temp folders after execution (default: True)

**Returns**: `Dict[str, ExecutionResult]`
- `plan_number` - Plan that was executed
- `worker_id` - Worker that executed the plan
- `success` - True if successful
- `hdf_path` - Path to output HDF file
- `error_message` - Error message if failed
- `execution_time` - Execution time in seconds

### Queue-Aware Scheduling

Workers are sorted by `queue_priority` (ascending), then plans are distributed round-robin:

```python
# Local workers execute first (priority 0)
local = init_ras_worker("local", queue_priority=0, cores_total=8, cores_per_plan=2)

# Remote workers used when local full (priority 1)
remote = init_ras_worker("psexec", hostname="...", queue_priority=1, ...)

# Cloud workers for overflow (priority 2)
cloud = init_ras_worker("docker", docker_host="...", queue_priority=2, ...)

# Plans fill local slots first, then remote, then cloud
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04", "05", "06"],
    workers=[local, remote, cloud]
)
```

**Worker Slots**: Workers with `max_parallel_plans > 1` create multiple slots:
- Worker with `cores_total=16` and `cores_per_plan=4` → 4 parallel slots
- Each slot can run one plan at a time
- Total slots = sum of all worker `max_parallel_plans`

## PsExec Worker Configuration

### CRITICAL: Session-Based Execution

**HEC-RAS is a GUI application** and REQUIRES session-based execution:

```python
worker = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    session_id=2,  # CRITICAL: NOT system account
    ...
)
```

**NEVER use `system_account=True`** - HEC-RAS will hang without desktop session.

### Determining Session ID

**Method 1: Query from controlling machine**:
```bash
query session /server:192.168.1.100

# Output:
# SESSIONNAME       USERNAME        ID  STATE
# console           Administrator    2  Active
#                                    ^
#                            Use this value
```

**Method 2: qwinsta command**:
```bash
qwinsta /server:192.168.1.100
```

**Typical Values**:
- Session 0: SYSTEM (services only, NO DESKTOP)
- Session 1: Sometimes system (varies by Windows version)
- **Session 2**: Typical interactive user (MOST COMMON)
- Session 3+: Additional RDP sessions

### Required Remote Machine Configuration

See `reference/psexec-setup.md` for complete instructions. Critical requirements:

1. **Group Policy Configuration**:
   - Access this computer from the network
   - Allow log on locally
   - Log on as a batch job

2. **Registry Key**:
   ```powershell
   # Run as Administrator on remote machine
   New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
       -Name "LocalAccountTokenFilterPolicy" -Value 1 -PropertyType DWORD -Force
   ```

3. **Remote Registry Service**:
   ```powershell
   Set-Service -Name "RemoteRegistry" -StartupType Automatic
   Start-Service -Name "RemoteRegistry"
   ```

4. **User Permissions**: User must be in local Administrators group

### Network Share Setup

**UNC Path Format**:
```python
# ✅ CORRECT: UNC path
share_path = r"\\192.168.1.100\RasRemote"
share_path = r"\\HOSTNAME\SharedFolder"

# ❌ WRONG: Mapped drive (doesn't work remotely)
share_path = r"Z:\RasRemote"
```

**Worker Folder Mapping**:
```python
worker = init_ras_worker(
    "psexec",
    share_path=r"\\192.168.1.100\RasRemote",  # UNC path from controlling machine
    worker_folder=r"C:\RasRemote",             # Local path on remote machine
    ...
)
```

If `worker_folder` not specified, auto-derived as `C:\{share_name}`.

### PsExec Worker Parameters

```python
worker = init_ras_worker(
    "psexec",
    # REQUIRED
    hostname="192.168.1.100",              # Remote machine IP or hostname
    share_path=r"\\192.168.1.100\RasRemote",  # UNC network share

    # RECOMMENDED
    session_id=2,                          # Session to run in (query session)
    cores_total=16,                        # Total cores on remote machine
    cores_per_plan=4,                      # Cores per HEC-RAS instance

    # OPTIONAL
    worker_folder=r"C:\RasRemote",         # Local path (auto-derived if omitted)
    credentials={                          # OPTIONAL - use Windows auth if possible
        "username": "DOMAIN\\user",
        "password": "password"
    },
    process_priority="low",                # OS priority (low/below normal/normal)
    queue_priority=0,                      # Execution priority (0-9, lower first)
    psexec_path=r"C:\Tools\PsExec.exe"     # PsExec location (auto-detected)
)
```

**Credentials**: OPTIONAL and NOT RECOMMENDED on trusted networks:
- When omitted: Uses Windows authentication (current user)
- Avoids "secondary logon" issues that prevent GUI access
- Recommended for domain-joined machines

When credentials provided:
- User must match logged-in session user
- Or have "Replace a process level token" privilege

### PsExec Auto-Download

PsExec.exe is automatically downloaded if not found:

**Search Order**:
1. System PATH
2. User profile directory (`~/PSTools/`)
3. Common locations (`C:/PSTools/`, `C:/Tools/PSTools/`)
4. **Auto-download** from Microsoft Sysinternals

**Manual Install**:
```bash
# Download PSTools
# https://live.sysinternals.com/PsExec.exe

# Place in PATH or specify psexec_path parameter
```

### Multi-Core Parallelism

Run multiple plans simultaneously on one worker:

```python
worker = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    session_id=2,
    cores_total=16,      # Total cores available
    cores_per_plan=4     # Cores per HEC-RAS instance
)

# Creates 16/4 = 4 parallel slots
# Worker can run 4 plans simultaneously
print(f"Parallel capacity: {worker.max_parallel_plans} plans")
```

### Process Priority

Control CPU priority on remote machine:

```python
worker = init_ras_worker(
    "psexec",
    process_priority="low",  # Recommended: minimal impact on user
    ...
)
```

**Valid Values**:
- `"low"` (default) - Minimal CPU priority, won't disrupt user
- `"below normal"` - Slightly higher priority
- `"normal"` - Standard priority

Higher priorities (above normal, high, realtime) NOT supported to protect remote users.

## Docker Worker Configuration

### Overview

Execute HEC-RAS in Rocky Linux 8 container using native Linux binaries.

**Workflow**:
1. **Preprocess** on Windows host (creates `.tmp.hdf` files)
2. **Execute** simulation in Linux container
3. **Copy** results back to project folder

### Prerequisites

**1. Docker Desktop**:
```bash
# Download: https://www.docker.com/products/docker-desktop
# Ensure Linux containers mode enabled (default)
```

**2. Python Packages**:
```bash
pip install ras-commander[remote-docker]
# or: pip install docker paramiko
```

**3. HEC-RAS Docker Image**:
```bash
# Build from ras-commander-cloud repo
cd path/to/ras-commander-cloud
docker build -t hecras:6.6 .

# Image includes:
# - Rocky Linux 8 base
# - HEC-RAS 6.6 Linux binaries
# - Intel MKL libraries
# Size: ~2.75 GB
```

**Note**: HEC-RAS Linux binaries are not redistributable. Users must obtain from HEC or build their own.

### Basic Docker Worker

**Local Docker execution**:
```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cores_total=8,
    cores_per_plan=4,
    preprocess_on_host=True  # Windows preprocessing required
)
```

### Remote Docker Host (SSH)

Execute Docker containers on remote machine via SSH:

```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    docker_host="ssh://user@192.168.1.100",  # SSH connection
    ssh_key_path="~/.ssh/docker_worker",      # SSH key
    share_path=r"\\192.168.1.100\DockerShare",  # File staging
    remote_staging_path=r"C:\DockerShare",      # Remote path
    cores_total=8,
    cores_per_plan=4
)
```

**SSH Requirements**:
- SSH key-based authentication (password NOT supported by Docker SDK)
- Or use `use_ssh_client=True` for system SSH client (supports more auth methods)

**SSH Key Setup**:
```bash
# Generate key
ssh-keygen -t ed25519 -f ~/.ssh/docker_worker

# Copy to remote
ssh-copy-id -i ~/.ssh/docker_worker.pub user@192.168.1.100

# Test
ssh -i ~/.ssh/docker_worker user@192.168.1.100 "docker info"
```

**Using System SSH Client**:
```python
worker = init_ras_worker(
    "docker",
    docker_host="ssh://user@192.168.1.100",
    use_ssh_client=True,  # Use system ssh command
    # SSH config in ~/.ssh/config:
    # Host 192.168.1.100
    #   IdentityFile ~/.ssh/docker_worker
    ...
)
```

### Docker Worker Parameters

```python
worker = init_ras_worker(
    "docker",
    # REQUIRED
    docker_image="hecras:6.6",             # Docker image name

    # LOCAL DOCKER
    # (no additional parameters needed)

    # REMOTE DOCKER (via SSH)
    docker_host="ssh://user@host",         # SSH URL
    ssh_key_path="~/.ssh/docker_worker",   # SSH key
    share_path=r"\\host\share",            # UNC path for file staging
    remote_staging_path=r"C:\share",       # Local path on Docker host

    # OPTIONAL
    cores_total=8,                         # Total cores
    cores_per_plan=4,                      # Cores per plan
    preprocess_on_host=True,               # Windows preprocessing (default)
    cpu_limit="4",                         # Container CPU limit
    memory_limit="8g",                     # Container memory limit
    max_runtime_minutes=480,               # Timeout (default 8 hours)
    use_ssh_client=True,                   # Use system ssh client
    queue_priority=2,                      # Execution priority (0-9)
    process_priority="low"                 # OS priority
)
```

### Path Conversion

Docker Desktop on Windows uses `/mnt/c/` paths. Worker automatically converts:

```python
# Windows path
"C:/Projects/Model"

# Automatically converted to Docker path
"/mnt/c/Projects/Model"
```

### Container Resource Limits

```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cpu_limit="4",       # 4 CPU cores max
    memory_limit="8g",   # 8 GB RAM max
    ...
)
```

## Mixed Worker Pools

Combine local, remote, and cloud workers:

```python
# Local worker (priority 0)
local = init_ras_worker(
    "local",
    worker_folder="C:/RasRemote",
    cores_total=8,
    cores_per_plan=2,
    queue_priority=0
)

# Remote PsExec worker (priority 1)
remote1 = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    session_id=2,
    cores_total=16,
    cores_per_plan=4,
    queue_priority=1
)

# Docker worker (priority 2)
docker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    docker_host="ssh://user@192.168.1.200",
    ssh_key_path="~/.ssh/docker",
    cores_total=8,
    cores_per_plan=4,
    queue_priority=2
)

# Execute with queue-aware scheduling
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04", "05", "06", "07", "08"],
    workers=[local, remote1, docker]
)

# Execution order:
# 1. Fill local worker slots (4 plans: 8 cores / 2 cores each)
# 2. Fill remote worker slots (4 plans: 16 cores / 4 cores each)
# 3. Fill Docker worker slots (2 plans: 8 cores / 4 cores each)
```

## Result Collection

```python
results = compute_parallel_remote(plan_numbers=["01", "02"], workers=[worker])

for plan_num, result in results.items():
    print(f"\nPlan {plan_num}:")
    print(f"  Worker: {result.worker_id}")
    print(f"  Success: {result.success}")
    print(f"  Time: {result.execution_time:.1f}s")

    if result.success:
        print(f"  HDF: {result.hdf_path}")

        # Verify HDF
        from ras_commander import HdfResultsPlan
        msgs = HdfResultsPlan.get_compute_messages(result.hdf_path)
        if "completed successfully" in msgs.lower():
            print(f"  Status: Verified successful")
    else:
        print(f"  Error: {result.error_message}")
```

## Cleanup

**Auto-cleanup** (default):
```python
results = compute_parallel_remote(
    plan_numbers=["01", "02"],
    workers=[worker],
    autoclean=True  # Delete temp folders after execution
)
```

**Manual cleanup** (for debugging):
```python
results = compute_parallel_remote(
    plan_numbers=["01", "02"],
    workers=[worker],
    autoclean=False  # Preserve temp folders
)

# Temp folders remain in worker_folder for inspection
# Manual deletion required
```

## Troubleshooting

### PsExec Worker Hangs

**Symptom**: No error, HDF not created

**Diagnosis**:
```bash
# Check session ID
query session /server:192.168.1.100

# Verify user is Administrator
net localgroup Administrators

# Check Remote Registry service
sc query RemoteRegistry
```

**Fix**: Ensure `session_id=2` (or correct session) and all configuration requirements met.

### Permission Denied

**Symptom**: "Access is denied"

**Diagnosis**:
1. Check Registry key: `LocalAccountTokenFilterPolicy=1`
2. Verify Group Policy settings
3. Confirm share permissions (Share + NTFS)

**Fix**: See `reference/psexec-setup.md`

### Network Path Not Found

**Symptom**: Cannot access `\\hostname\share`

**Diagnosis**:
```bash
# Test from controlling machine
dir \\192.168.1.100\RasRemote

# Check firewall (port 445 SMB)
Test-NetConnection -ComputerName 192.168.1.100 -Port 445

# Verify Remote Registry running
sc \\192.168.1.100 query RemoteRegistry
```

### Docker Connection Failed

**Symptom**: Cannot connect to Docker daemon

**Diagnosis**:
```bash
# Test Docker locally
docker ps

# Test remote Docker via SSH
ssh user@192.168.1.100 "docker info"
```

**Fix**: Ensure Docker Desktop running (local) or SSH keys configured (remote)

## See Also

- **Reference**: `reference/workers.md` - Complete worker type reference
- **Reference**: `reference/psexec-setup.md` - PsExec critical configuration
- **Reference**: `reference/docker-setup.md` - Docker worker setup
- **Examples**: `examples/psexec-worker.py` - PsExec execution example
- **Examples**: `examples/docker-worker.py` - Docker execution example
- **Subagent**: remote-executor - Expert subagent for remote execution
- **AGENTS.md**: `ras_commander/remote/AGENTS.md` - Remote subpackage guidance
- **Rule**: `.claude/rules/hec-ras/remote.md` - Remote execution rules
- **Notebook**: `examples/23_remote_execution_psexec.ipynb` - Complete workflow
