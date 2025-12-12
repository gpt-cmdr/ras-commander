# Worker Types Reference

Complete reference for all remote execution worker types.

## Worker Type Comparison

| Worker | Status | Platform | Use Case | Dependencies |
|--------|--------|----------|----------|--------------|
| **local** | ✓ Implemented | Same machine | Local parallel execution | None |
| **psexec** | ✓ Implemented | Windows → Windows | Windows remote via network share | None (PsExec auto-downloaded) |
| **docker** | ✓ Implemented | Any → Linux container | Container execution (local or remote) | docker, paramiko |
| **ssh** | Stub | Any → Any | SSH-based remote execution | paramiko |
| **winrm** | Stub | Windows → Windows | Windows Remote Management | pywinrm |
| **slurm** | Stub | Any → HPC cluster | High-performance computing | N/A |
| **aws_ec2** | Stub | Any → AWS cloud | AWS EC2 cloud execution | boto3 |
| **azure_fr** | Stub | Any → Azure cloud | Azure Functions/Batch execution | azure-* |

## Local Worker

Execute plans in parallel on the local machine.

### Configuration

```python
worker = init_ras_worker(
    "local",
    worker_folder="C:/RasRemote",
    cores_total=8,
    cores_per_plan=2,
    queue_priority=0,
    process_priority="low"
)
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `worker_folder` | No | Temp dir | Temporary folder for worker operations |
| `cores_total` | No | None | Total CPU cores available |
| `cores_per_plan` | No | 4 | Cores to allocate per plan |
| `queue_priority` | No | 0 | Execution queue priority (0-9) |
| `process_priority` | No | "low" | OS process priority |

### Use Cases

- Testing remote execution workflow locally
- Mixed local+remote worker pools (local as priority 0)
- Parallel execution without remote configuration

### Limitations

- Same machine as controlling process
- No remote deployment capabilities
- Executes in worker folders (not original project)

## PsExec Worker

Execute plans on remote Windows machines via Microsoft Sysinternals PsExec.

### Configuration

```python
worker = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    worker_folder=r"C:\RasRemote",
    session_id=2,
    cores_total=16,
    cores_per_plan=4,
    credentials={
        "username": "DOMAIN\\user",
        "password": "password"
    },
    process_priority="low",
    queue_priority=0
)
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `hostname` | **Yes** | - | Remote machine hostname or IP |
| `share_path` | **Yes** | - | UNC network share path |
| `worker_folder` | No | C:\{share_name} | Local path on remote machine |
| `session_id` | **Recommended** | 2 | Session to run in (query session) |
| `credentials` | No | {} | Username/password dict (use Windows auth if possible) |
| `cores_total` | No | None | Total cores on remote machine |
| `cores_per_plan` | No | 4 | Cores per HEC-RAS instance |
| `process_priority` | No | "low" | OS priority (low/below normal/normal) |
| `queue_priority` | No | 0 | Execution priority (0-9) |
| `system_account` | No | False | Run as SYSTEM (DON'T USE for HEC-RAS) |
| `psexec_path` | No | Auto | Path to PsExec.exe |

### Critical Configuration

**ALWAYS specify `session_id`**:
```bash
# Query session ID from controlling machine
query session /server:192.168.1.100

# Output:
# SESSIONNAME       USERNAME        ID  STATE
# console           Administrator    2  Active
#                                    ^
#                            Use this value
```

**NEVER use `system_account=True`** - HEC-RAS is a GUI application and requires desktop session.

### Remote Machine Requirements

1. **Group Policy**: Access network, log on locally, batch job rights
2. **Registry**: `LocalAccountTokenFilterPolicy=1`
3. **Service**: Remote Registry running
4. **Permissions**: User in Administrators group

See `psexec-setup.md` for complete configuration.

### Network Share Requirements

- UNC path accessible from controlling machine
- Read/Write permissions for user
- Share permissions AND NTFS permissions

### Multi-Core Parallelism

```python
worker = init_ras_worker(
    "psexec",
    cores_total=16,
    cores_per_plan=4
)

# Creates 16/4 = 4 parallel slots
# Worker can run 4 plans simultaneously
```

### Use Cases

- Windows workstations with network shares
- Domain-joined machines with trust
- Internal network environments
- Workstations with users logged in (desktop sessions)

### Limitations

- Windows → Windows only
- Requires network share configuration
- Requires Group Policy configuration
- Firewall must allow SMB (port 445) and PsExec

## Docker Worker

Execute plans in Docker containers using Rocky Linux 8 and native HEC-RAS Linux binaries.

### Configuration

**Local Docker**:
```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cores_total=8,
    cores_per_plan=4,
    preprocess_on_host=True
)
```

**Remote Docker (SSH)**:
```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    docker_host="ssh://user@192.168.1.100",
    ssh_key_path="~/.ssh/docker_worker",
    share_path=r"\\192.168.1.100\DockerShare",
    remote_staging_path=r"C:\DockerShare",
    cores_total=8,
    cores_per_plan=4
)
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `docker_image` | **Yes** | - | Docker image name (e.g., "hecras:6.6") |
| `docker_host` | No | None | Docker daemon URL (None=local, ssh://..., tcp://...) |
| `ssh_key_path` | Conditional | None | SSH key for ssh:// URLs |
| `share_path` | Conditional | None | UNC path for remote Docker file staging |
| `remote_staging_path` | Conditional | None | Local path on Docker host |
| `cores_total` | No | None | Total cores available |
| `cores_per_plan` | No | 4 | Cores per plan |
| `preprocess_on_host` | No | True | Windows preprocessing before Linux execution |
| `cpu_limit` | No | None | Container CPU limit (e.g., "4") |
| `memory_limit` | No | None | Container memory limit (e.g., "8g") |
| `max_runtime_minutes` | No | 480 | Timeout in minutes (8 hours) |
| `use_ssh_client` | No | False | Use system ssh command |
| `queue_priority` | No | 0 | Execution priority (0-9) |
| `process_priority` | No | "low" | OS priority |

### Prerequisites

**1. Docker Desktop**:
```bash
# Windows: https://www.docker.com/products/docker-desktop
# Linux: https://docs.docker.com/engine/install/
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

# Note: HEC-RAS Linux binaries not redistributable
# Users must obtain from HEC or build their own
```

### SSH Remote Docker Setup

**SSH Key-Based Auth**:
```bash
# Generate key
ssh-keygen -t ed25519 -f ~/.ssh/docker_worker

# Copy to remote
ssh-copy-id -i ~/.ssh/docker_worker.pub user@host

# Test
ssh -i ~/.ssh/docker_worker user@host "docker info"
```

**Using System SSH Client** (more auth options):
```python
worker = init_ras_worker(
    "docker",
    docker_host="ssh://user@host",
    use_ssh_client=True,  # Use system ssh command
    # Configure in ~/.ssh/config:
    # Host 192.168.1.100
    #   IdentityFile ~/.ssh/docker_worker
    ...
)
```

### Workflow

1. **Preprocess** on Windows host (creates `.tmp.hdf` files)
2. **Copy** project to Docker staging
3. **Execute** simulation in Linux container
4. **Copy** results back to project folder
5. **Cleanup** temporary files

### Use Cases

- Container-based execution for isolation
- Remote Linux execution from Windows
- Cloud execution (Docker on remote host)
- Reproducible environments

### Limitations

- Requires Docker image with HEC-RAS Linux binaries
- Two-step workflow (preprocess on Windows, execute on Linux)
- SSH key-based auth required for remote Docker
- Path conversion for Windows Docker Desktop

## SSH Worker

**Status**: Stub (not implemented)

Execute plans on remote machines via SSH.

### Planned Configuration

```python
worker = init_ras_worker(
    "ssh",
    hostname="192.168.1.100",
    ssh_key_path="~/.ssh/id_rsa",
    remote_folder="/opt/RasRemote",
    cores_total=32,
    cores_per_plan=8
)
```

### Use Cases

- Linux → Linux remote execution
- Windows → Linux remote execution
- SSH-based authentication without PsExec

## WinRM Worker

**Status**: Stub (not implemented)

Execute plans on remote Windows machines via Windows Remote Management.

### Planned Configuration

```python
worker = init_ras_worker(
    "winrm",
    hostname="192.168.1.100",
    credentials={
        "username": "DOMAIN\\user",
        "password": "password"
    },
    remote_folder=r"C:\RasRemote",
    cores_total=16,
    cores_per_plan=4
)
```

### Use Cases

- Windows → Windows without PsExec
- PowerShell remoting environments
- Corporate environments with WinRM enabled

## Slurm Worker

**Status**: Stub (not implemented)

Execute plans on HPC clusters using Slurm workload manager.

### Planned Configuration

```python
worker = init_ras_worker(
    "slurm",
    partition="compute",
    account="project123",
    time_limit="08:00:00",
    nodes=4,
    tasks_per_node=16
)
```

### Use Cases

- High-performance computing clusters
- Large-scale parallel execution
- Academic/research computing environments

## AWS EC2 Worker

**Status**: Stub (not implemented)

Execute plans on AWS EC2 instances.

### Planned Configuration

```python
worker = init_ras_worker(
    "aws_ec2",
    instance_type="c5.4xlarge",
    ami_id="ami-xxxxxxxxx",
    region="us-east-1",
    key_name="my-keypair",
    security_group="sg-xxxxxxxxx"
)
```

### Use Cases

- Cloud-based execution
- Auto-scaling compute capacity
- Burst execution for large batches

## Azure FR Worker

**Status**: Stub (not implemented)

Execute plans on Azure Functions or Azure Batch.

### Planned Configuration

```python
worker = init_ras_worker(
    "azure_fr",
    resource_group="ras-compute",
    batch_account="rascompute",
    pool_id="hecras-pool",
    vm_size="Standard_D16s_v3"
)
```

### Use Cases

- Azure cloud environments
- Serverless execution
- Enterprise Azure deployments
