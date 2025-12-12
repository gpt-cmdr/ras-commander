# Docker Worker Setup Guide

Complete guide for configuring Docker-based HEC-RAS execution.

## Overview

Execute HEC-RAS in Docker containers using Rocky Linux 8 and native Linux binaries.

**Workflow**:
1. **Preprocess** plan on Windows host (creates `.tmp.hdf` files)
2. **Execute** simulation in Linux container
3. **Copy** results back to project folder

**Why two-step**: Linux HEC-RAS has preprocessing limitations, so Windows preprocessing is required.

## Prerequisites

### 1. Docker Desktop

**Windows**:
```bash
# Download: https://www.docker.com/products/docker-desktop
# Install and ensure Linux containers mode (default)

# Verify installation
docker --version
docker ps
```

**Linux**:
```bash
# Install Docker Engine
# https://docs.docker.com/engine/install/

# Verify
docker --version
sudo docker ps
```

### 2. Python Packages

```bash
# Install Docker worker dependencies
pip install ras-commander[remote-docker]

# Or install manually
pip install docker paramiko
```

### 3. HEC-RAS Linux Binaries

**IMPORTANT**: HEC-RAS Linux binaries are NOT redistributable.

Users must obtain from:
- HEC directly (if available)
- Build their own from source

**Required files**:
```
Linux_RAS_v66/
├── bin/
│   ├── RasUnsteady
│   ├── RasGeomPreprocess
│   └── [other binaries]
└── libs/
    ├── Intel MKL libraries
    └── Runtime dependencies
```

### 4. Build Docker Image

**From ras-commander-cloud repository**:
```bash
# Clone repo
git clone https://github.com/billk-FM/ras-commander-cloud.git
cd ras-commander-cloud

# Place HEC-RAS binaries in reference/Linux_RAS_v66/

# Build image
docker build -t hecras:6.6 .

# Verify
docker images | grep hecras
# Should show: hecras  6.6  [IMAGE_ID]  [SIZE ~2.75 GB]
```

**Image Details**:
- Base: Rocky Linux 8
- HEC-RAS: 6.6 Linux native binaries
- Intel MKL: Full suite for AVX512 support
- Size: ~2.75 GB

## Local Docker Worker

Execute containers on local machine (Docker Desktop).

### Configuration

```python
from ras_commander import init_ras_worker

worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cores_total=8,
    cores_per_plan=4,
    preprocess_on_host=True
)
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `docker_image` | **Yes** | - | Image name (e.g., "hecras:6.6") |
| `cores_total` | No | None | Total cores available |
| `cores_per_plan` | No | 4 | Cores per plan |
| `preprocess_on_host` | No | True | Windows preprocessing first |
| `cpu_limit` | No | None | Container CPU limit (e.g., "4") |
| `memory_limit` | No | None | Memory limit (e.g., "8g") |
| `max_runtime_minutes` | No | 480 | Timeout (8 hours) |

### Execution Example

```python
from ras_commander import init_ras_project, compute_parallel_remote

# Initialize project
init_ras_project("/path/to/project", "6.6")

# Create local Docker worker
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cores_total=8,
    cores_per_plan=4
)

# Execute plans
results = compute_parallel_remote(
    plan_numbers=["01", "02"],
    workers=[worker],
    num_cores=4
)

# Check results
for plan_num, result in results.items():
    if result.success:
        print(f"Plan {plan_num}: SUCCESS")
        print(f"  HDF: {result.hdf_path}")
    else:
        print(f"Plan {plan_num}: FAILED - {result.error_message}")
```

### Path Conversion (Windows Docker Desktop)

Docker Desktop on Windows uses `/mnt/c/` paths:

```python
# Windows path
"C:/Projects/Model"

# Automatically converted to
"/mnt/c/Projects/Model"

# Conversion is automatic - no user action required
```

## Remote Docker Worker (SSH)

Execute containers on remote machine via SSH.

### SSH Configuration

**1. Generate SSH Key**:
```bash
# Generate key for Docker worker
ssh-keygen -t ed25519 -f ~/.ssh/docker_worker

# Key files created:
# ~/.ssh/docker_worker       (private key)
# ~/.ssh/docker_worker.pub   (public key)
```

**2. Copy Key to Remote**:
```bash
# Copy public key to remote Docker host
ssh-copy-id -i ~/.ssh/docker_worker.pub user@192.168.1.100

# Verify passwordless login
ssh -i ~/.ssh/docker_worker user@192.168.1.100
# Should connect without password prompt
```

**3. Test Docker Access**:
```bash
# Test remote Docker via SSH
ssh -i ~/.ssh/docker_worker user@192.168.1.100 "docker info"

# Should show Docker daemon info
```

### Worker Configuration

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

### Parameters (Remote Docker)

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `docker_host` | **Yes** | - | SSH URL (ssh://user@host) |
| `ssh_key_path` | **Yes** | - | Path to SSH private key |
| `share_path` | **Yes** | - | UNC path for file staging |
| `remote_staging_path` | **Yes** | - | Local path on Docker host |
| `docker_image` | **Yes** | - | Image name |
| `cores_total` | No | None | Total cores |
| `cores_per_plan` | No | 4 | Cores per plan |

**File Staging**: Remote Docker requires network share for file transfer:
- Controlling machine → UNC share (`share_path`)
- Docker host → Local path (`remote_staging_path`)

### Remote Execution Example

```python
# Create remote Docker worker
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    docker_host="ssh://bill@192.168.1.100",
    ssh_key_path="~/.ssh/docker_worker",
    share_path=r"\\192.168.1.100\DockerShare",
    remote_staging_path=r"C:\DockerShare",
    cores_total=16,
    cores_per_plan=4
)

# Execute plans remotely
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04"],
    workers=[worker],
    num_cores=4
)
```

## Using System SSH Client

Alternative to paramiko for more authentication options.

### Configuration

```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    docker_host="ssh://user@192.168.1.100",
    use_ssh_client=True,  # Use system ssh command
    # ssh_key_path not required - configure in ~/.ssh/config
    ...
)
```

### SSH Config File

**~/.ssh/config**:
```
Host 192.168.1.100
    User bill
    IdentityFile ~/.ssh/docker_worker
    ForwardAgent yes
```

**Benefits**:
- Uses system SSH configuration
- Supports SSH agent forwarding
- More authentication methods (Kerberos, GSSAPI, etc.)
- Leverages existing SSH setup

## Container Resource Limits

### CPU Limit

```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cpu_limit="4",  # Limit to 4 CPU cores
    ...
)
```

**Values**:
- `"4"` - 4 full cores
- `"2.5"` - 2.5 cores (2 full + 1 half)
- `"0.5"` - Half a core

### Memory Limit

```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    memory_limit="8g",  # Limit to 8 GB RAM
    ...
)
```

**Values**:
- `"8g"` - 8 gigabytes
- `"4096m"` - 4096 megabytes
- `"512m"` - 512 megabytes

### Combined Limits

```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cpu_limit="4",
    memory_limit="8g",
    cores_total=16,      # Total available on host
    cores_per_plan=4     # Allocate 4 cores per plan
)

# Creates 16/4 = 4 parallel slots
# Each container limited to 4 CPU and 8g RAM
```

## Multi-Core Parallelism

Run multiple containers simultaneously:

```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cores_total=16,      # Total cores on host
    cores_per_plan=4     # Cores per container
)

# Creates 16/4 = 4 parallel slots
# Worker can run 4 containers simultaneously
print(f"Parallel capacity: {worker.max_parallel_plans} containers")
```

## Execution Workflow

### Step-by-Step Process

**1. Preprocessing (Windows)**:
```
- RasGeomPreprocess.exe runs on Windows host
- Creates .tmp.hdf geometry files
- Required because Linux preprocessing has limitations
```

**2. File Staging**:
```
- Project copied to staging directory
- For remote: copied to network share
- Includes .tmp.hdf files from preprocessing
```

**3. Container Execution (Linux)**:
```
- Docker container created from hecras:6.6 image
- Project mounted at /app/input
- RasUnsteady runs simulation
- Results written to /app/output
```

**4. Result Collection**:
```
- .hdf results copied back to original project
- Temporary staging cleaned up (if autoclean=True)
- HDF verification performed
```

### Files Transferred

**To container**:
- `.prj` - Project file
- `.p##` - Plan file
- `.g##` - Geometry file
- `.u##` - Unsteady file
- `.f##` - Flow file
- `.tmp.hdf` - Preprocessed geometry

**From container**:
- `.p##.hdf` - Results HDF file
- `.log` - Compute log (if exists)

## Network Share Setup (Remote Docker)

### Windows Remote Host

**Create Share (PowerShell)**:
```powershell
# Run as Administrator on Docker host

# Create folder
New-Item -Path "C:\DockerShare" -ItemType Directory -Force

# Create share
New-SmbShare -Name "DockerShare" -Path "C:\DockerShare" `
    -FullAccess "USERNAME" -ReadAccess "Everyone"

# Set NTFS permissions
icacls "C:\DockerShare" /grant "USERNAME:(OI)(CI)M"

# Verify
Get-SmbShare -Name "DockerShare"
```

### Linux Remote Host

**Create Share (Samba)**:
```bash
# Install Samba
sudo apt-get install samba

# Create folder
sudo mkdir -p /opt/DockerShare
sudo chown $USER:$USER /opt/DockerShare

# Configure Samba (/etc/samba/smb.conf)
[DockerShare]
path = /opt/DockerShare
browseable = yes
writable = yes
valid users = USERNAME

# Set Samba password
sudo smbpasswd -a USERNAME

# Restart Samba
sudo systemctl restart smbd
```

### Testing Share Access

```bash
# From controlling machine (Windows)
dir \\192.168.1.100\DockerShare
echo test > \\192.168.1.100\DockerShare\test.txt
type \\192.168.1.100\DockerShare\test.txt
del \\192.168.1.100\DockerShare\test.txt
```

## Troubleshooting

### Docker Connection Failed

**Symptom**: "Cannot connect to Docker daemon"

**Diagnosis**:
```bash
# Check Docker running
docker ps

# Check Docker daemon
docker info
```

**Fix**:
- Windows: Start Docker Desktop
- Linux: `sudo systemctl start docker`

### SSH Connection Failed

**Symptom**: "SSH connection failed" or "Permission denied"

**Diagnosis**:
```bash
# Test SSH connection
ssh -i ~/.ssh/docker_worker user@192.168.1.100

# Test Docker via SSH
ssh -i ~/.ssh/docker_worker user@192.168.1.100 "docker info"

# Check SSH key permissions
ls -l ~/.ssh/docker_worker
# Should be: -rw------- (600)
```

**Fix**:
```bash
# Fix key permissions
chmod 600 ~/.ssh/docker_worker

# Ensure key copied to remote
ssh-copy-id -i ~/.ssh/docker_worker.pub user@192.168.1.100
```

### Image Not Found

**Symptom**: "Image 'hecras:6.6' not found"

**Diagnosis**:
```bash
# Check local images
docker images | grep hecras

# For remote Docker
ssh user@host "docker images | grep hecras"
```

**Fix**:
```bash
# Build image locally
cd ras-commander-cloud
docker build -t hecras:6.6 .

# Or for remote: build on remote machine
ssh user@host "cd /path/to/ras-commander-cloud && docker build -t hecras:6.6 ."
```

### Container Timeout

**Symptom**: "Container execution timeout"

**Diagnosis**:
- Check `max_runtime_minutes` setting
- Check container logs: `docker logs [container_id]`

**Fix**:
```python
worker = init_ras_worker(
    "docker",
    max_runtime_minutes=960,  # Increase to 16 hours
    ...
)
```

### Preprocessing Failed

**Symptom**: ".tmp.hdf files not created"

**Diagnosis**:
- Check Windows RAS.exe path
- Check HEC-RAS version compatibility
- Check geometry file validity

**Fix**: Ensure `preprocess_on_host=True` and HEC-RAS installed on Windows host.

### File Permission Errors

**Symptom**: "Permission denied" when accessing results

**Diagnosis**:
- Check staging directory permissions
- Check network share permissions (remote Docker)

**Fix**:
```bash
# Windows
icacls C:\DockerShare /grant USERNAME:(OI)(CI)F

# Linux
chmod -R 777 /opt/DockerShare  # For testing only
```

## Performance Optimization

### Container Caching

Docker images are cached after first use:
```bash
# Check cached images
docker images

# Remove unused images
docker image prune
```

### Volume Mounts

Worker uses volume mounts for I/O:
- `/app/input` - Read-only project files
- `/app/output` - Write results

Mounts are created per execution and cleaned up automatically.

### Parallel Execution

Maximize throughput with multiple containers:
```python
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    cores_total=32,      # 32 cores available
    cores_per_plan=8,    # 8 cores per container
    memory_limit="16g"   # 16 GB per container
)

# Creates 32/8 = 4 parallel containers
# Each limited to 8 cores and 16 GB
```

### Queue Priority

Use Docker for overflow capacity:
```python
# Local execution first (priority 0)
local = init_ras_worker("local", queue_priority=0, ...)

# PsExec remote second (priority 1)
psexec = init_ras_worker("psexec", queue_priority=1, ...)

# Docker for overflow (priority 2)
docker = init_ras_worker("docker", queue_priority=2, ...)

results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04", "05", "06"],
    workers=[local, psexec, docker]
)
# Fills local first, then psexec, then Docker
```

## See Also

- **Worker Reference**: `workers.md` - All worker types
- **PsExec Setup**: `psexec-setup.md` - PsExec configuration
- **AGENTS.md**: `ras_commander/remote/AGENTS.md` - Remote subpackage guidance
- **Dockerfile**: ras-commander-cloud repository
