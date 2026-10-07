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

`DockerWorker` runs native HEC-RAS computation in a local or remote Docker
worker pool after host preprocessing. For the separate Wine preparation/native
compute image pair, use [RasDocker](../user-guide/container-execution.md).
Compare [execution backends](../user-guide/execution-backends.md) before choosing.

### Configuration

This example uses a **locally built worker-compatible image**. `hecras:6.6`
is not a public Docker Hub reference.

```python
from ras_commander.remote import init_ras_worker

worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    docker_host="ssh://user@docker-host.example",
    remote_host_os="linux",
    remote_staging_path="/shared/ras-staging",
    cores_total=8,
    cores_per_plan=2,
    cpu_limit="2",
    memory_limit="8g",
    preprocess_on_host=True,
)
```

Use a local daemon with `docker_host=None` and a host-accessible
`staging_directory`. For native Linux remote hosts, `ssh://` staging transfers
files over SFTP or system SSH/scp; no UNC share is required. Remote Windows Docker Desktop hosts
use `remote_host_os="windows"`, a UNC `share_path`, and the corresponding
Windows host `remote_staging_path`.

### Parameters

| Parameter | Purpose |
| --- | --- |
| `docker_image` | Required image implementing the configured shell runner and native runtime |
| `docker_host` | `None` for local daemon or `ssh://user@host` for remote Docker |
| `remote_host_os` | `linux` or `windows`; SSH defaults to Linux when omitted |
| `remote_staging_path` | Docker-host filesystem path for remote model staging |
| `share_path` | UNC transfer share for remote Windows hosts |
| `staging_directory` | Local-daemon staging path visible to the engine |
| `cores_total`, `cores_per_plan` | Worker-pool capacity and solver cores per plan |
| `cpu_limit`, `memory_limit` | Docker CPU quota and memory limit |
| `max_runtime_minutes` | Plan execution timeout; default 480 minutes |
| `preprocess_on_host` | Prepare on the Windows control host; default `True` |

### Advanced Parameters

`container_input_path`, `container_output_path`, and `container_script_path`
configure the image contract. Defaults are `/app/input`, `/app/output`, and
`/app/scripts/core_execution/run_ras.sh`. `ssh_key_path` selects an SSH identity;
`use_ssh_client` selects system SSH/scp for file staging and Docker's SSH connection.
See the [rendered source reference](../api/remote.md#dockerworker-source-reference)
for the complete dataclass.

### Docker Host Setup

Install Docker Engine or Docker Desktop using the
[official installation instructions](https://docs.docker.com/engine/install/).
The engine and staging user must be able to access the selected model paths.
Verify the runtime version and runner layout in a controlled local worker image.
The [published image catalog](../user-guide/container-images.md) supplies images
for the different `RasDocker` contract, not drop-in worker images.

### Requirements

- A working Docker daemon, locally or over SSH.
- Complete host-preprocessed native solver inputs and a compatible shell runner.
- Staging paths writable by the transfer user and accessible to the Docker daemon.
- An installed Windows HEC-RAS runtime for the host preprocessing route.

### Dependencies

```bash
pip install "ras-commander[remote-docker]" paramiko
```

The Docker extra supplies the SDK. The default SSH/SFTP staging route needs
`paramiko`; with `use_ssh_client=True`, staging uses installed system SSH/scp
and honors SSH agent/config settings.

### Two-Step Workflow

1. With `preprocess_on_host=True`, prepare the selected plan on the Windows host.
2. Stage the project on the Docker host and execute the native container runner.
3. Validate the native log/result HDF, then copy the selected final result family back.

Set `preprocess_on_host=False` only when valid prepared inputs already exist.
It does not add Wine preprocessing to an arbitrary image. Keep inputs and
working outputs separate; review retained results after computational checks.

### HEC-RAS Linux Versions

An image tag is a label, not runtime-version evidence. Inspect the vendor
runtime used by your local image. The public catalog documents tested versions
of the paired `RasDocker` images separately.

### Docker Troubleshooting

| Symptom | Check |
| --- | --- |
| Cannot connect to daemon | Run `docker info` locally or `docker -H ssh://user@docker-host.example info`; verify SSH access and daemon permissions |
| Image or runner missing | Confirm the local worker image, configured script path, native executable, and libraries |
| Staging or mounts fail | Check the Docker-host path and staging permissions; workstation paths alone are insufficient |
| HDF exists but solve fails | Inspect the native log and result validation; preprocessing may already have written completion attributes |
| Remote Linux staging fails | Verify `paramiko`, SSH key access, and the writable POSIX staging root |

### Remote Docker Host Setup

Use Docker over SSH with an account permitted to access the remote daemon:

```bash
ssh user@docker-host.example docker info
docker -H ssh://user@docker-host.example info
```

Pin the host key and configure the SSH identity using your normal SSH config
or `ssh_key_path`. Keep the daemon's local Unix socket; this route does not
require a network TCP listener or opening port 2375. Docker daemon access is
privileged, so restrict the account to authorized operators. Sites requiring
TCP should configure authenticated TLS using
[Docker's daemon protection guide](https://docs.docker.com/engine/security/protect-access/).

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

The following worker-factory backends remain placeholders. Implemented Slurm
execution uses the separate [RasSlurm](../user-guide/slurm-portable-execution.md)
and [RasApptainer](../user-guide/slurm-apptainer-execution.md) APIs:


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
