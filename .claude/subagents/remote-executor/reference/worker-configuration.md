# Worker Configuration Reference

Complete configuration guide for all worker types in `ras_commander.remote`.

## Table of Contents

1. [PsExec Worker (Windows Remote)](#psexec-worker)
2. [Docker Worker (Containers)](#docker-worker)
3. [Local Worker (Parallel)](#local-worker)
4. [SSH Worker (Stub)](#ssh-worker)
5. [WinRM Worker (Stub)](#winrm-worker)
6. [Slurm Worker (Stub)](#slurm-worker)
7. [AWS EC2 Worker (Stub)](#aws-ec2-worker)
8. [Azure Worker (Stub)](#azure-worker)

---

## PsExec Worker

**Status**: ✓ Fully Implemented
**Module**: `ras_commander/remote/PsexecWorker.py`
**Platform**: Windows → Windows
**Technology**: PsExec over network shares (SMB)

### Requirements

**Software:**
- PsExec installed on controlling machine (optional, ras-commander can use embedded version)
- HEC-RAS installed on remote machine
- Windows Server or Workstation (both machines)

**Network:**
- SMB file sharing enabled (port 445)
- Remote Registry service running on remote machine
- Network connectivity between machines

**Permissions:**
- User account in Administrators group on remote machine
- Group Policy configuration (see below)
- Registry key configuration (see below)

### Step-by-Step Setup

#### Step 1: Configure Remote Machine Group Policy

Navigate to Group Policy Editor on remote machine:

**How to open:**
```powershell
# Run as Administrator
gpedit.msc
```

**Navigate to:**
```
Computer Configuration
└── Windows Settings
    └── Security Settings
        └── Local Policies
            └── User Rights Assignment
```

**Configure these three policies:**

**1. Access this computer from the network**
- Double-click the policy
- Click "Add User or Group"
- Add the user account that will run HEC-RAS
- Click OK

**2. Allow log on locally**
- Double-click the policy
- Click "Add User or Group"
- Add the user account
- Click OK

**3. Log on as a batch job**
- Double-click the policy
- Click "Add User or Group"
- Add the user account
- Click OK

**Why this is required:**
PsExec needs these permissions to execute processes in a user session. Without them, you'll get "Access is denied" errors.

#### Step 2: Set Registry Key

On remote machine, run as Administrator:

```powershell
# Set LocalAccountTokenFilterPolicy registry key
New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy" -Value 1 -PropertyType DWORD -Force
```

**Verify:**
```powershell
Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy"
```

**Why this is required:**
This registry key allows remote administrative access for local accounts. Without it, even Administrator accounts will be treated as standard users remotely.

**Security Note:**
This reduces User Account Control (UAC) filtering for remote connections. Understand security implications before enabling in production environments.

#### Step 3: Start Remote Registry Service

On remote machine, run as Administrator:

```powershell
# Set service to automatic startup
Set-Service -Name "RemoteRegistry" -StartupType Automatic

# Start the service
Start-Service -Name "RemoteRegistry"

# Verify service is running
Get-Service -Name "RemoteRegistry"
```

**Why this is required:**
PsExec uses the Remote Registry service to deploy and execute processes on the remote machine.

#### Step 4: Add User to Administrators Group

On remote machine, run as Administrator:

```powershell
# Add user to Administrators group (replace USERNAME)
net localgroup Administrators USERNAME /add

# Verify membership
net localgroup Administrators
```

**Why this is required:**
HEC-RAS execution and file access require elevated permissions. The user account must have administrative rights on the remote machine.

#### Step 5: Create Network Share

On remote machine, run as Administrator:

```powershell
# Create folder for shared HEC-RAS projects
New-Item -Path "C:\RAS_Share" -ItemType Directory -Force

# Share the folder
New-SmbShare -Name "RAS_Share" -Path "C:\RAS_Share" `
    -FullAccess "USERNAME" -ReadAccess "Everyone"

# Set NTFS permissions (not just share permissions)
icacls "C:\RAS_Share" /grant "USERNAME:(OI)(CI)M"
```

**Verify from controlling machine:**
```bash
# Test access from controlling machine
dir \\REMOTE_HOSTNAME\RAS_Share
```

**Why this is required:**
The controlling machine needs read/write access to copy HEC-RAS project files and retrieve results.

#### Step 6: Determine Session ID

On controlling machine, query remote sessions:

```bash
# Query active sessions on remote machine
query session /server:REMOTE_HOSTNAME

# Alternative command
qwinsta /server:REMOTE_HOSTNAME
```

**Example output:**
```
 SESSION NAME     USERNAME           ID  STATE
 console          Administrator      2   Active
```

**Use the ID column value** (typically `2` for workstation desktops)

**Why this is required:**
HEC-RAS is a GUI application and must run in an active desktop session. Using session 0 (SYSTEM) will cause silent failure.

#### Step 7: Test PsExec Connection

From controlling machine:

```bash
# Test PsExec execution (replace values)
psexec \\REMOTE_HOSTNAME -u USERNAME -p PASSWORD -i 2 cmd /c echo "Test successful"
```

**Expected output:**
```
Test successful
```

If this fails, revisit Steps 1-6.

### Python Configuration

```python
from ras_commander.remote import init_ras_worker

worker = init_ras_worker(
    worker_type='psexec',

    # Remote machine identification
    hostname='192.168.1.100',  # IP address or hostname

    # Credentials (optional if Windows auth configured)
    username='ras_user',
    password='secure_password',

    # Session configuration (CRITICAL)
    session_id=2,  # From query session output - DO NOT use system_account=True

    # Path configuration
    remote_share=r'\\192.168.1.100\RAS_Share',  # UNC path
    local_path=r'C:\RAS_Share',  # Local mount on remote machine

    # HEC-RAS configuration
    hecras_version='6.5',  # Or '6.3', '5.0.7', etc.

    # Optional
    worker_id='worker1',  # Auto-generated if not provided
    max_jobs=1  # Number of simultaneous jobs this worker can handle
)
```

### Configuration Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `worker_type` | str | Yes | Must be `'psexec'` |
| `hostname` | str | Yes | Remote machine IP or hostname |
| `username` | str | No | Username for remote login (Windows auth if omitted) |
| `password` | str | No | Password for remote login |
| `session_id` | int | **Critical** | Session ID from `query session` (typically 2) |
| `remote_share` | str | Yes | UNC path to network share (e.g., `\\HOST\Share`) |
| `local_path` | str | Yes | Local path on remote machine (e.g., `C:\Share`) |
| `hecras_version` | str | Yes | HEC-RAS version (e.g., `'6.5'`, `'6.3'`) |
| `worker_id` | str | No | Unique worker identifier (auto-generated if omitted) |
| `max_jobs` | int | No | Max simultaneous jobs (default: 1) |

### Common Mistakes

**❌ Using `system_account=True`:**
```python
# WRONG - HEC-RAS will hang
worker = init_ras_worker(
    worker_type='psexec',
    system_account=True,  # Don't do this!
    ...
)
```

**❌ Omitting `session_id`:**
```python
# WRONG - May default to system account
worker = init_ras_worker(
    worker_type='psexec',
    # Missing session_id parameter
    ...
)
```

**❌ Using mapped drive instead of UNC path:**
```python
# WRONG - Mapped drives don't work remotely
remote_share = r'Z:\RAS_Share'  # Only works locally

# CORRECT - Use UNC path
remote_share = r'\\192.168.1.100\RAS_Share'
```

---

## Docker Worker

**Status**: ✓ Fully Implemented
**Module**: `ras_commander/remote/DockerWorker.py`
**Platform**: Any → Linux containers
**Technology**: Docker API over SSH
**Dependencies**: `docker`, `paramiko`

### Requirements

**Software:**
```bash
pip install ras-commander[remote-docker]
# Or manually:
pip install docker paramiko
```

**Docker Daemon:**
- Docker installed on remote machine (or local for testing)
- Docker daemon accessible (local socket or SSH)
- HEC-RAS Docker image available

**SSH (for remote Docker):**
- SSH server running on remote machine
- SSH key-based authentication configured
- User account has Docker permissions

### Docker Image Requirements

HEC-RAS Docker images must have:
- HEC-RAS installed (Windows container or Wine for Linux)
- Compute engine accessible via command line
- Working directory structure for project files

### Python Configuration

**Local Docker (testing):**
```python
worker = init_ras_worker(
    worker_type='docker',
    docker_host='unix:///var/run/docker.sock',  # Local Docker daemon
    container_image='hecras:6.5',
    hecras_version='6.5'
)
```

**Remote Docker via SSH:**
```python
worker = init_ras_worker(
    worker_type='docker',
    docker_host='ssh://user@192.168.1.100',  # SSH to remote Docker
    ssh_key='/path/to/private_key.pem',  # SSH key for authentication
    container_image='hecras:6.5',
    hecras_version='6.5',
    mount_path='/mnt/ras_projects'  # Container mount point
)
```

### Configuration Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `worker_type` | str | Yes | Must be `'docker'` |
| `docker_host` | str | Yes | Docker daemon URL (unix:// or ssh://) |
| `container_image` | str | Yes | Docker image name and tag |
| `ssh_key` | str | Conditional | SSH private key path (required for ssh://) |
| `hecras_version` | str | Yes | HEC-RAS version in container |
| `mount_path` | str | No | Container mount point (default: `/ras`) |
| `worker_id` | str | No | Unique worker identifier |
| `max_jobs` | int | No | Max simultaneous containers |

---

## Local Worker

**Status**: ✓ Fully Implemented
**Module**: `ras_commander/remote/LocalWorker.py`
**Platform**: Local machine only
**Technology**: Python multiprocessing

### Use Cases

- Baseline parallel execution without remote setup
- Development and testing
- Single machine with multiple cores

### Python Configuration

```python
worker = init_ras_worker(
    worker_type='local',
    num_workers=4,  # Number of parallel processes
    hecras_version='6.5'
)
```

### Configuration Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `worker_type` | str | Yes | Must be `'local'` |
| `num_workers` | int | No | Number of parallel processes (default: CPU count) |
| `hecras_version` | str | Yes | HEC-RAS version |
| `worker_id` | str | No | Unique worker identifier |

---

## SSH Worker

**Status**: Stub (Not Implemented)
**Module**: `ras_commander/remote/SshWorker.py`
**Technology**: Direct SSH command execution
**Dependencies**: `paramiko>=3.0`

### Planned Configuration

```python
# Not yet implemented - stub only
worker = init_ras_worker(
    worker_type='ssh',
    hostname='192.168.1.100',
    username='ras_user',
    ssh_key='/path/to/key.pem',
    remote_path='/home/ras_user/projects',
    hecras_version='6.5'
)
```

**Install when available:**
```bash
pip install ras-commander[remote-ssh]
```

---

## WinRM Worker

**Status**: Stub (Not Implemented)
**Module**: `ras_commander/remote/WinrmWorker.py`
**Technology**: Windows Remote Management protocol
**Dependencies**: `pywinrm>=0.4.3`

### Planned Configuration

```python
# Not yet implemented - stub only
worker = init_ras_worker(
    worker_type='winrm',
    hostname='192.168.1.100',
    username='ras_user',
    password='secure_password',
    transport='ntlm',  # Or 'kerberos', 'basic'
    hecras_version='6.5'
)
```

**Install when available:**
```bash
pip install ras-commander[remote-winrm]
```

---

## Slurm Worker

**Status**: Stub (Not Implemented)
**Module**: `ras_commander/remote/SlurmWorker.py`
**Technology**: Slurm workload manager (HPC clusters)

### Planned Configuration

```python
# Not yet implemented - stub only
worker = init_ras_worker(
    worker_type='slurm',
    partition='compute',
    account='ras_project',
    nodes=1,
    ntasks=16,
    time='04:00:00',
    hecras_version='6.5'
)
```

---

## AWS EC2 Worker

**Status**: Stub (Not Implemented)
**Module**: `ras_commander/remote/AwsEc2Worker.py`
**Technology**: AWS EC2 API
**Dependencies**: `boto3>=1.28`

### Planned Configuration

```python
# Not yet implemented - stub only
worker = init_ras_worker(
    worker_type='aws_ec2',
    region='us-east-1',
    instance_type='t3.xlarge',
    ami_id='ami-12345678',  # HEC-RAS AMI
    key_name='ras-keypair',
    hecras_version='6.5'
)
```

**Install when available:**
```bash
pip install ras-commander[remote-aws]
```

---

## Azure Worker

**Status**: Stub (Not Implemented)
**Module**: `ras_commander/remote/AzureFrWorker.py`
**Technology**: Azure Functions/Batch
**Dependencies**: `azure-identity`, `azure-mgmt-compute`

### Planned Configuration

```python
# Not yet implemented - stub only
worker = init_ras_worker(
    worker_type='azure',
    subscription_id='12345678-1234-1234-1234-123456789012',
    resource_group='ras-compute',
    vm_size='Standard_D4s_v3',
    hecras_version='6.5'
)
```

**Install when available:**
```bash
pip install ras-commander[remote-azure]
```

---

## Comparison Table

| Worker Type | Status | Platform | Use Case | Setup Complexity |
|-------------|--------|----------|----------|------------------|
| **PsExec** | ✓ Implemented | Win→Win | Windows network | High (Group Policy, Registry) |
| **Docker** | ✓ Implemented | Any→Linux | Containers | Medium (SSH keys, images) |
| **Local** | ✓ Implemented | Local | Testing/dev | Low (none) |
| **SSH** | Stub | Any→Unix | Linux servers | Medium (SSH setup) |
| **WinRM** | Stub | Win→Win | Modern Windows | Medium (WinRM config) |
| **Slurm** | Stub | Any→HPC | Large scale | High (cluster access) |
| **AWS EC2** | Stub | Any→Cloud | Cloud compute | Medium (AWS credentials) |
| **Azure** | Stub | Any→Cloud | Cloud compute | Medium (Azure credentials) |

---

## Next Steps

1. Choose worker type based on your infrastructure
2. Follow setup steps for your chosen worker
3. Test configuration with simple plan execution
4. Scale to parallel execution with multiple workers
5. Consult `common-issues.md` for troubleshooting
