# Worker Types

RAS Commander supports multiple worker backends for distributed HEC-RAS execution. Each worker type has specific requirements and use cases.

## Worker Overview

| Worker Type | Platform | Network | Use Case |
|-------------|----------|---------|----------|
| **LocalWorker** | Windows | None | Single machine parallelism |
| **PsexecWorker** | Windows | LAN/WAN | Windows workstations |
| **DockerWorker** | Linux/Windows | SSH | Container-based execution |

## LocalWorker

Executes HEC-RAS plans on the local machine using worker folders.

### Configuration

```python
from ras_commander.remote import init_ras_worker

worker = init_ras_worker(
    "local",
    ras_version="6.5",     # Required: HEC-RAS version
    num_cores=4,           # Cores per plan
    max_concurrent=2       # Simultaneous plans (optional)
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ras_version` | str | Required | HEC-RAS version (e.g., "6.5") |
| `num_cores` | int | 1 | CPU cores per plan |
| `max_concurrent` | int | 1 | Max simultaneous plans |

### Requirements

- Windows operating system
- HEC-RAS installed at standard location
- Sufficient disk space for worker folders

### Use Cases

- Single workstation batch processing
- Development and testing
- Combined with remote workers in hybrid pools

---

## PsexecWorker

Executes HEC-RAS on remote Windows machines using PsExec.

### Configuration

```python
from ras_commander.remote import init_ras_worker

worker = init_ras_worker(
    "psexec",
    host="192.168.1.100",           # Remote machine IP/hostname
    username="DOMAIN\\user",        # Windows credentials
    password="password",            # Or use secure credential store
    ras_version="6.5",              # HEC-RAS version
    session_id=2,                   # GUI session ID (required!)
    num_cores=8                     # Cores per plan
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | str | Required | Remote machine hostname/IP |
| `username` | str | Required | Windows username (DOMAIN\\user) |
| `password` | str | Required | Windows password |
| `ras_version` | str | Required | HEC-RAS version |
| `session_id` | int | Required | Windows session ID |
| `num_cores` | int | 1 | CPU cores per plan |

### Remote Machine Setup

#### 1. Install PsExec on Control Machine

Download from [Sysinternals](https://docs.microsoft.com/en-us/sysinternals/downloads/psexec) and add to PATH.

#### 2. Configure Remote Machine

```powershell
# Enable Remote Registry
Set-Service RemoteRegistry -StartupType Automatic
Start-Service RemoteRegistry

# Set LocalAccountTokenFilterPolicy
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f

# Add user to local Administrators
net localgroup Administrators "DOMAIN\user" /add

# Configure firewall (if needed)
netsh advfirewall firewall add rule name="PsExec" dir=in action=allow protocol=tcp localport=445
```

#### 3. Find Session ID

```powershell
# On remote machine
query session

# Output:
# SESSIONNAME   USERNAME    ID  STATE   TYPE
# console       user        2   Active
#                              ↑ Use this ID
```

### Why Session ID Matters

HEC-RAS is a GUI application that requires an interactive Windows session. Using `session_id` ensures:

- HEC-RAS can display UI elements (even if not visible)
- COM automation works correctly
- Process doesn't terminate unexpectedly

!!! warning "Session ID Required"
    Never use `system_account=True` or omit `session_id`. HEC-RAS will fail silently or crash.

### Network Requirements

- Port 445 (SMB) open between control and remote machines
- Admin share access (C$, ADMIN$)
- Same domain or workgroup, or explicit trust

### Complete Setup Checklist

!!! note "Remote Machine Checklist"
    Complete ALL steps before first PsExec connection:

    - [ ] Create shared folder: `net share RasRemote=C:\RasRemote /GRANT:Everyone,FULL`
    - [ ] Verify share: `net share RasRemote`
    - [ ] Enable Remote Registry service
    - [ ] Set registry key: `LocalAccountTokenFilterPolicy = 1`
    - [ ] Configure Group Policy (see below)
    - [ ] Add user to Administrators group
    - [ ] Enable firewall rules for ports 445, 135
    - [ ] **REBOOT the remote machine**
    - [ ] Find session ID: `query session`

### Group Policy Configuration

Navigate to: `Computer Configuration → Windows Settings → Security Settings → Local Policies → User Rights Assignment`

| Policy | Required Setting |
|--------|------------------|
| Access this computer from the network | Add your user |
| Allow log on locally | Add your user |
| Log on as a batch job | Add your user |
| Deny log on through Remote Desktop | Ensure user NOT listed |

After changes: `gpupdate /force`

### Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| "Access denied" | Credentials or permissions | Check username format, LocalAccountTokenFilterPolicy |
| "Network path not found" | Firewall or network | Check port 445, DNS resolution |
| "Session not found" | Wrong session ID | Re-query session on remote machine |
| HEC-RAS crashes | System account | Use session_id, not system_account |

??? tip "Detailed Troubleshooting"

    **"Logon failure: user has not been granted the requested logon type"**

    1. Open Local Security Policy (`secpol.msc`)
    2. Navigate to Local Policies → User Rights Assignment
    3. Add user to "Access this computer from the network"
    4. Run `gpupdate /force` and reboot

    **HEC-RAS hangs or produces no output**

    - Cause: Using SYSTEM account (`-s` flag) instead of user session
    - Solution: Always use `session_id` parameter, never `system_account=True`
    - Verify: `query session` shows user logged in with correct ID

    **First connection takes 10+ seconds**

    - Cause: PsExec installing PSEXESVC service on first run
    - Solution: Pre-install service on remote machine:
      ```powershell
      sc create PSEXESVC binPath= "C:\Windows\PSEXESVC.exe" start= demand
      ```

### Quick Setup Script

```powershell
# Run on REMOTE machine as Administrator
# Creates share, sets registry, enables services

# 1. Create shared folder
mkdir C:\RasRemote
net share RasRemote=C:\RasRemote /GRANT:Everyone,FULL

# 2. Enable Remote Registry
Set-Service RemoteRegistry -StartupType Automatic
Start-Service RemoteRegistry

# 3. Set UAC remote policy
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f

# 4. Enable firewall rules
netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes

Write-Host "IMPORTANT: Configure Group Policy and REBOOT before using PsExec"
```

---

## DockerWorker

Executes HEC-RAS in Docker containers on remote Linux or Windows hosts.

### Configuration

```python
from ras_commander.remote import init_ras_worker

worker = init_ras_worker(
    "docker",
    host="docker-host.local",       # Docker host
    ssh_key="/path/to/id_rsa",      # SSH private key
    image="hec-ras:6.5",            # Docker image name
    ras_version="6.5",              # HEC-RAS version
    num_cores=4                     # Cores per container
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | str | Required | Docker host hostname |
| `ssh_key` | str | Required | Path to SSH private key |
| `ssh_user` | str | "root" | SSH username |
| `ssh_port` | int | 22 | SSH port |
| `image` | str | Required | Docker image name |
| `ras_version` | str | Required | HEC-RAS version in image |
| `num_cores` | int | 1 | Cores per container |

### Advanced Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `docker_host` | str | `None` | Remote Docker daemon URL (e.g., `tcp://192.168.1.100:2375`) |
| `share_path` | str | `None` | Network share path for project staging |
| `remote_staging_path` | str | `/tmp/ras` | Path inside container for staged files |
| `max_runtime_minutes` | int | `60` | Maximum execution time before timeout |
| `cpu_limit` | float | `None` | CPU limit (e.g., `2.0` for 2 cores) |
| `memory_limit` | str | `None` | Memory limit (e.g., `"4g"`, `"2048m"`) |
| `preprocess_on_host` | bool | `True` | Run geometry preprocessor on Windows host |
| `auto_cleanup` | bool | `True` | Remove container after execution |
| `network_mode` | str | `"bridge"` | Docker network mode |
| `volumes` | dict | `None` | Additional volume mounts |

#### preprocess_on_host Explained

HEC-RAS geometry preprocessing (`GeomPreprocess.exe`) requires Windows. When using Docker on Linux:

```python
worker = init_ras_worker(
    "docker",
    host="linux-server",
    image="hec-ras:6.6-linux",
    preprocess_on_host=True,  # Default - preprocess on Windows control machine
    ...
)
```

**Workflow with `preprocess_on_host=True`:**

1. Control machine (Windows) runs `GeomPreprocess.exe`
2. Preprocessed files (`.c##`, `.x##`) transferred to Docker host
3. Container runs `RasUnsteady.exe` (Linux) for compute
4. Results transferred back to control machine

**When to use `preprocess_on_host=False`:**

- Docker host is Windows (can run preprocessor itself)
- Using Wine-based HEC-RAS image that handles preprocessing
- Geometry is already preprocessed and won't change

#### Resource Limits

Control container resources to prevent oversubscription:

```python
worker = init_ras_worker(
    "docker",
    host="docker-host",
    image="hec-ras:6.6",
    cpu_limit=4.0,           # Max 4 CPU cores
    memory_limit="8g",        # Max 8GB RAM
    max_runtime_minutes=120,  # 2 hour timeout
    ...
)
```

!!! tip "Memory Sizing"
    HEC-RAS memory usage scales with mesh cell count:
    - < 100K cells: 2-4 GB
    - 100K-500K cells: 4-8 GB
    - 500K-1M cells: 8-16 GB
    - > 1M cells: 16+ GB

#### Remote Docker Daemon

Connect to Docker on a remote machine:

```python
worker = init_ras_worker(
    "docker",
    docker_host="tcp://192.168.1.100:2375",  # Remote daemon
    image="hec-ras:6.6",
    ...
)
```

!!! warning "Security"
    Remote Docker without TLS is insecure. For production:
    ```python
    docker_host="tcp://192.168.1.100:2376"  # TLS port
    # Configure TLS certificates via environment or docker config
    ```

#### Custom Volume Mounts

Mount additional directories into the container:

```python
worker = init_ras_worker(
    "docker",
    host="docker-host",
    image="hec-ras:6.6",
    volumes={
        "/data/terrain": "/terrain:ro",      # Read-only terrain data
        "/data/output": "/results:rw",       # Writable results directory
    },
    ...
)
```

### Docker Host Setup

#### 1. Install Docker

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

#### 2. HEC-RAS Linux Images

HEC-RAS provides native Linux binaries (no Wine needed). Download from HEC:

| Version | Download URL | Binary |
|---------|--------------|--------|
| 6.6 | `https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v66.zip` | `RasUnsteady` |
| 6.5 | `https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v65.zip` | `RasUnsteady` |
| 6.1 | `https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_610_Linux.zip` | `RasUnsteady` |
| 5.0.7 | `https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_507_linux.zip` | `rasUnsteady64` |

**Zip File Structures:**

```
# 6.6 / 6.5:
Linux_RAS_v6X/
├── RAS_v6X/Release/    # Binaries (RasUnsteady, RasGeomPreprocess, RasSteady)
├── libs/               # Intel MKL and runtime libraries
└── Muncie_6X0/         # Example project

# 6.1:
HEC-RAS_610_Linux/
└── RAS_Linux_test_setup.zip  # Nested zip
    ├── Ras_v61/Release/      # Binaries
    └── libs/                 # Libraries

# 5.0.7:
RAS_507_linux/
└── bin_ras/           # Both binaries AND libraries together
    ├── rasUnsteady64  # Note: different name than newer versions
    └── lib*.so        # MKL libraries
```

#### 3. Build Docker Images

```bash
cd /path/to/docker-builds

# Build HEC-RAS 6.6
docker build -f Dockerfile.6.6 -t hecras:6.6 .

# Build HEC-RAS 6.5
docker build -f Dockerfile.6.5 -t hecras:6.5 .

# Verify images
docker images | grep hecras
```

Expected sizes:

| Image | Size |
|-------|------|
| hecras:6.6 | ~2.58 GB |
| hecras:6.5 | ~2.95 GB |
| hecras:6.1 | ~2.71 GB |
| hecras:5.0.7 | ~2.43 GB |

#### 4. Test Docker Execution

```bash
# Test that HEC-RAS binaries are present
docker run --rm hecras:6.6 ls -la /app/bin/

# Test RasUnsteady can execute
docker run --rm hecras:6.6 /app/bin/RasUnsteady --help
```

#### 5. Configure SSH Access

```bash
# Generate key pair (on control machine)
ssh-keygen -t ed25519 -f ~/.ssh/docker_worker

# Copy public key to Docker host
ssh-copy-id -i ~/.ssh/docker_worker.pub user@docker-host

# Test connection with Docker
ssh -i ~/.ssh/docker_worker user@docker-host "docker info"
```

### Requirements

- Docker installed on remote host
- SSH access configured
- HEC-RAS Docker image available
- Sufficient storage for container volumes

### Dependencies

```bash
pip install ras-commander[remote-ssh]
# Or
pip install paramiko docker
```

### Two-Step Workflow

DockerWorker uses a two-step execution process because HEC-RAS geometry preprocessing requires Windows:

1. **Preprocess on Windows** (control machine): Run geometry preprocessor
2. **Compute on Linux** (Docker container): Execute HEC-RAS simulation

By default, `preprocess_on_host=True` handles this automatically.

### HEC-RAS Linux Versions

| Version | Base Image | Download Size | Notes |
|---------|------------|---------------|-------|
| 6.6 | CentOS 7 | ~2.75 GB | Intel MKL, AVX512 |
| 6.7 | Rocky Linux 8 | ~2.58 GB | Beta version |

### Docker Troubleshooting

??? tip "Docker Image Not Found"
    ```bash
    # Check available images
    docker images | grep hec-ras

    # Pull or build image
    docker pull your-registry/hec-ras:6.5
    # Or build locally
    docker build -t hec-ras:6.5 .
    ```

??? tip "Docker Daemon Unreachable"
    ```bash
    # Check Docker is running
    docker info

    # Check daemon socket
    ls -la /var/run/docker.sock

    # For remote Docker, verify TCP is enabled
    curl http://docker-host:2375/version
    ```

??? tip "Container Exits Immediately"
    ```bash
    # Check container logs
    docker logs <container_id>

    # Common causes:
    # - Missing Wine dependencies
    # - Incorrect HEC-RAS path in container
    # - Memory limits too restrictive
    ```

??? tip "CRLF Line Ending Errors"
    HEC-RAS files created on Windows have CRLF line endings. If running in Linux container:
    ```bash
    # Convert to Unix line endings
    dos2unix *.p* *.g* *.u*
    ```

### Remote Docker Host Setup

To enable remote Docker connections:

```bash
# On Docker host, edit /etc/docker/daemon.json
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2375"]
}

# Restart Docker
sudo systemctl restart docker

# Configure firewall
sudo ufw allow 2375/tcp
```

!!! warning "Security"
    Exposing Docker TCP without TLS is insecure. For production, configure TLS certificates.

---

## Creating Worker Pools

### Homogeneous Pool

All workers same type and configuration:

```python
workers = [
    init_ras_worker("local", ras_version="6.5", num_cores=4)
    for _ in range(4)
]
```

### Heterogeneous Pool

Mixed worker types and capabilities:

```python
workers = [
    # Local workers
    init_ras_worker("local", ras_version="6.5", num_cores=8),

    # Fast remote workstation
    init_ras_worker("psexec", host="fast-ws", num_cores=16, ...),

    # Standard remote workstations
    init_ras_worker("psexec", host="ws1", num_cores=8, ...),
    init_ras_worker("psexec", host="ws2", num_cores=8, ...),

    # Docker containers for burst
    init_ras_worker("docker", host="docker1", num_cores=4, ...),
    init_ras_worker("docker", host="docker2", num_cores=4, ...),
]
```

### Validation

Always validate workers before use:

```python
valid_workers = []
for worker in workers:
    try:
        if worker.validate():
            valid_workers.append(worker)
            print(f"✓ {worker} validated")
        else:
            print(f"✗ {worker} failed validation")
    except Exception as e:
        print(f"✗ {worker} error: {e}")

if not valid_workers:
    raise RuntimeError("No valid workers")

results = compute_parallel_remote(plans, workers=valid_workers)
```

---

## Worker Interface

All workers implement the same interface:

```python
class BaseWorker:
    def validate(self) -> bool:
        """Test connectivity and HEC-RAS availability."""
        ...

    def execute_plan(self, plan: str, dest: Path) -> bool:
        """Execute a single plan, return success status."""
        ...

    def cleanup(self):
        """Clean up resources (temp files, connections)."""
        ...
```

### Custom Workers

Implement the interface to create custom workers:

```python
from ras_commander.remote import BaseWorker

class CloudWorker(BaseWorker):
    """Custom worker for cloud VM execution."""

    def __init__(self, instance_id, ras_version, **kwargs):
        self.instance_id = instance_id
        self.ras_version = ras_version

    def validate(self):
        # Check cloud instance is running
        # Check HEC-RAS is installed
        return True

    def execute_plan(self, plan, dest):
        # Copy project to instance
        # Run HEC-RAS
        # Copy results back
        return True

    def cleanup(self):
        # Stop instance, clean temp files
        pass
```

---

## Future Worker Types

Planned for future releases:

| Worker | Description | Status |
|--------|-------------|--------|
| **SshWorker** | Direct SSH execution | Planned |
| **WinrmWorker** | Windows Remote Management | Planned |
| **SlurmWorker** | HPC cluster integration | Planned |
| **AwsEc2Worker** | AWS EC2 instances | Planned |
| **AzureFrWorker** | Azure Functions/VMs | Planned |

## Related

- [Remote Parallel Execution](remote-parallel.md)
- [Scaling Strategies](scaling-strategies.md)
- [API Reference - Remote Modules](../api/remote.md)
