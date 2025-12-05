# Remote Execution

RAS Commander supports distributed computation across multiple machines using the `ras_commander.remote` subpackage.

**Tested Configuration:** Windows 10/11, HEC-RAS 5.x-6.x, Local Administrator Account

## Overview

The remote execution framework provides:

- **PsexecWorker**: Windows remote execution via PsExec over network shares
- **LocalWorker**: Local parallel execution (baseline)
- **DockerWorker**: Container execution via Docker over SSH
- **Future**: SshWorker, WinrmWorker, SlurmWorker, AwsEc2Worker, AzureFrWorker

## Architecture

```
Local Machine                    Remote Workers
     |                                |
     +-- compute_parallel_remote()    |
     |       |                        |
     |       +----------------------> Worker 1 (PsExec)
     |       +----------------------> Worker 2 (Docker)
     |       +----------------------> Worker 3 (Local)
     |                                |
     | <-- Results consolidated ------+
```

## Quick Start

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Initialize project
init_ras_project("/path/to/project", "6.6")

# Create workers
workers = [
    init_ras_worker("local", ras_version="6.6", num_cores=4),
    init_ras_worker("psexec",
        hostname="192.168.1.100",
        share_path=r"\\192.168.1.100\RasRemote",
        credentials={"username": "user", "password": "pass"},
        ras_exe_path=r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\RAS.exe",
        session_id=2
    ),
]

# Execute across workers
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03", "04"],
    workers=workers
)
```

---

## PsExec Worker Setup Guide

!!! warning "Critical: HEC-RAS GUI Requirement"
    HEC-RAS is a GUI application and **MUST run in a user session**.

    - Use `session_id=2` (typical for workstations)
    - **NEVER** use `system_account=True` - HEC-RAS will hang

**Setup Time:** 20-30 minutes | **Difficulty:** Intermediate (requires administrator access)

### Prerequisites

**On Remote Worker Machine:**

- Windows 10 or Windows 11
- HEC-RAS installed (any version 5.x - 6.x)
- Local administrator account
- Network connectivity (same network or VPN)
- Administrator access to configure system

**On Control Machine (where Python runs):**

- PsExec.exe downloaded (from [Microsoft Sysinternals](https://docs.microsoft.com/en-us/sysinternals/downloads/psexec))
- ras-commander library installed
- Network access to remote worker

### Part 1: Create Network Share (5 minutes)

**On the remote worker machine:**

```cmd
REM Create the folder
mkdir C:\RasRemote

REM Share the folder (as Administrator)
net share RasRemote=C:\RasRemote /GRANT:Everyone,FULL

REM Verify the share
net share RasRemote

REM Test local access
dir \\localhost\RasRemote
```

### Part 2: Configure User Rights (10 minutes)

**Critical:** PsExec with session-based execution requires specific User Rights assignments.

1. Open Local Group Policy Editor: `gpedit.msc`
2. Navigate to: `Computer Configuration > Windows Settings > Security Settings > Local Policies > User Rights Assignment`
3. Add your username to these policies:

| Policy | Purpose |
|--------|---------|
| Access this computer from the network | Allows PsExec network authentication |
| Allow log on locally | Required for session-based execution |
| Log on as a batch job | Required for batch file execution |
| Replace a process level token | Sometimes needed for process creation (optional) |

4. Verify user is **NOT** in "Deny log on through Remote Desktop Services"
5. Apply policies: `gpupdate /force`

### Part 3: Configure Registry Keys (5 minutes)

**On the remote worker machine (as Administrator):**

```cmd
REM Enable Admin Token Over Network
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f

REM Verify the registry key
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy
```

Should show: `LocalAccountTokenFilterPolicy    REG_DWORD    0x1`

### Part 4: Configure Windows Services (3 minutes)

```cmd
REM Start and enable Remote Registry service
sc config RemoteRegistry start= auto
net start RemoteRegistry

REM Verify service is running
sc query RemoteRegistry
```

### Part 5: Configure Windows Firewall (5 minutes)

```cmd
REM Enable File and Printer Sharing rules
netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes
netsh advfirewall firewall set rule group="Network Discovery" new enable=Yes
```

**From the control machine**, test:

```powershell
Test-NetConnection -ComputerName 192.168.3.8 -Port 445
# Should show: TcpTestSucceeded : True
```

### Part 6: Ensure User is Administrator

```cmd
REM Verify user is in Administrators group
net localgroup Administrators

REM Add user if not present
net localgroup Administrators youruser /add
```

### Part 7: REBOOT (Required!)

```cmd
shutdown /r /t 0
```

!!! danger "Critical"
    Registry and Group Policy changes **require a reboot** to take effect. Do not skip this step.

### Part 8: Find Session ID

After reboot, determine the session ID:

```cmd
query user
```

Output example:
```
USERNAME    SESSIONNAME    ID  STATE
bill        console         2  Active
```

**The ID column (2 in this example) is what you use for `session_id`.**

Common Session IDs:

| ID | Description |
|----|-------------|
| 0 | Services session (not for GUI apps) |
| 1 | Console session (first user login) |
| **2** | Console session (typical for single-user workstations) |
| 3+ | Additional RDP sessions |

**For most workstations, use Session ID 2.**

### Part 9: Verification Tests

**From the control machine:**

```cmd
REM Test 1: Network share access
dir \\192.168.3.8\RasRemote

REM Test 2: PsExec basic connectivity
PsExec.exe \\192.168.3.8 -u username -p PASSWORD -accepteula cmd /c echo SUCCESS

REM Test 3: PsExec with session ID (required for HEC-RAS)
PsExec.exe \\192.168.3.8 -u username -p PASSWORD -i 2 -accepteula cmd /c echo SUCCESS

REM Test 4: Query sessions
PsExec.exe \\192.168.3.8 -u username -p PASSWORD -accepteula cmd /c query user
```

### Quick Setup Script

Run this on the remote worker machine as Administrator:

```batch
@echo off
REM Quick setup script for HEC-RAS remote worker

echo Creating share folder...
mkdir C:\RasRemote
net share RasRemote=C:\RasRemote /GRANT:Everyone,FULL

echo Setting registry key...
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f

echo Starting Remote Registry service...
sc config RemoteRegistry start= auto
net start RemoteRegistry

echo Enabling firewall rules...
netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes
netsh advfirewall firewall set rule group="Network Discovery" new enable=Yes

echo.
echo ====================================================================
echo IMPORTANT: You must now complete these manual steps:
echo ====================================================================
echo 1. Run gpedit.msc
echo 2. Add your username to User Rights Assignment policies
echo 3. Run: gpupdate /force
echo 4. REBOOT the machine
echo 5. After reboot, verify session ID using: query user
echo ====================================================================
pause
```

### Complete Setup Checklist

- [ ] Folder created: `C:\RasRemote`
- [ ] Network share created: `RasRemote` -> `C:\RasRemote`
- [ ] Share permissions: `Everyone` has Full Control
- [ ] Group Policy: User added to "Access this computer from the network"
- [ ] Group Policy: User added to "Allow log on locally"
- [ ] Group Policy: User added to "Log on as a batch job"
- [ ] Group Policy: User NOT in "Deny log on through Remote Desktop Services"
- [ ] Group Policy changes applied: `gpupdate /force`
- [ ] Registry: `LocalAccountTokenFilterPolicy = 1`
- [ ] Service: Remote Registry running and set to Automatic
- [ ] Firewall: File and Printer Sharing rules enabled
- [ ] User: In Administrators group
- [ ] **REBOOTED**
- [ ] HEC-RAS installed and path verified
- [ ] Session ID identified (usually 2)

---

## Docker Worker Setup

Docker workers provide Linux-based HEC-RAS execution, useful for:

- Leveraging Linux performance optimizations
- Running multiple isolated HEC-RAS instances
- Cloud/container orchestration compatibility

### Available Docker Images

Pre-built images for multiple HEC-RAS versions:

| Image Tag | HEC-RAS Version | Size | Notes |
|-----------|-----------------|------|-------|
| `hecras:6.6` | 6.6 | ~2.58 GB | Latest, recommended |
| `hecras:6.5` | 6.5 | ~2.95 GB | |
| `hecras:6.1` | 6.1 | ~2.71 GB | |
| `hecras:5.0.7` | 5.0.7 | ~2.43 GB | Binary: `rasUnsteady64` |

### HEC-RAS Linux Download URLs

```
6.6: https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v66.zip
6.5: https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v65.zip
6.1: https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_610_Linux.zip
5.0.7: https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_507_linux.zip
```

### Docker Worker Configuration

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Initialize project
init_ras_project(r"C:\Projects\MyProject", "6.6")

# Create Docker worker (remote Docker host via SSH)
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    docker_host="ssh://user@192.168.3.8",
    share_path=r"\\192.168.3.8\RasRemote",
    remote_staging_path=r"C:\RasRemote",
    use_ssh_client=True,  # Use system SSH instead of paramiko
    cores_total=8,
    cores_per_plan=4
)

# Execute plans
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03"],
    workers=[worker]
)
```

### SSH Key Setup

Docker workers using `ssh://` URLs require key-based authentication:

```bash
# Generate SSH key (on control machine)
ssh-keygen -t ed25519 -f ~/.ssh/docker_worker

# Copy to remote Docker host
ssh-copy-id -i ~/.ssh/docker_worker user@192.168.3.8

# Test connection
ssh -i ~/.ssh/docker_worker user@192.168.3.8 "docker info"
```

### Preprocessing Workflow

Docker workers use a two-step execution:

1. **Preprocess on Windows**: Creates `.tmp.hdf` file with geometry and initial conditions
2. **Execute on Linux**: Runs RasUnsteady in Docker container

The preprocessing monitors the `.bcoXX` file for "Starting Unsteady Flow Computations" signal to terminate early.

!!! note "Dependencies"
    DockerWorker requires: `pip install ras-commander[remote-ssh]` or `pip install docker paramiko`

---

## Troubleshooting

### PsExec Errors

| Error | Cause | Solution |
|-------|-------|----------|
| "Logon failure: the user has not been granted the requested logon type" | User Rights not configured | Re-check Group Policy (Part 2), run `gpupdate /force`, **reboot** |
| "The network path was not found" | Network share not accessible | Verify share with `net share RasRemote`, check firewall |
| "Access is denied" | Insufficient permissions | Check `LocalAccountTokenFilterPolicy = 1`, verify Administrators group |
| HEC-RAS hangs or doesn't execute | Wrong execution mode (SYSTEM vs session) | Use `-i {session_id}`, **never** `-s` |
| HEC-RAS runs but creates no output | File path issues | Use local paths in batch (C:\...) not UNC paths |

### Session vs SYSTEM Comparison

| Feature | `-s` (SYSTEM) | `-i {session_id}` (User Session) |
|---------|---------------|-----------------------------------|
| Setup Complexity | Simple | Complex (Group Policy required) |
| UAC Issues | None | Requires configuration |
| GUI Applications | Hangs | Works |
| HEC-RAS | **DO NOT USE** | **REQUIRED** |
| Session dependency | No | Yes (user must be logged in) |

### Pre-Install PSEXESVC for Faster Connections

First PsExec connection takes 5-15 seconds while installing the service. To eliminate this delay:

```cmd
REM Copy PSEXESVC.exe to remote machine
copy "C:\path\to\PsTools\PSEXESVC.exe" \\192.168.3.8\C$\Windows\PSEXESVC.exe

REM On remote machine, create the service
sc create PSEXESVC binPath= "C:\Windows\PSEXESVC.exe" start= demand
```

---

## Multi-Worker Setup

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

init_ras_project(r"C:\Projects\MyProject", "6.6")

workers = [
    init_ras_worker(
        "psexec",
        hostname="192.168.3.8",  # CLB-04
        share_path=r"\\192.168.3.8\RasRemote",
        credentials={"username": "bill", "password": "pass"},
        ras_exe_path=r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\RAS.exe",
        session_id=2,
        system_account=False
    ),
    init_ras_worker(
        "psexec",
        hostname="192.168.3.9",  # Another machine
        share_path=r"\\192.168.3.9\RasRemote",
        credentials={"username": "user2", "password": "pass2"},
        ras_exe_path=r"C:\Program Files\HEC\HEC-RAS\6.3\RAS.exe",
        session_id=2,
        system_account=False
    )
]

# Execute across all workers
results = compute_parallel_remote(
    plan_numbers=None,  # All plans
    workers=workers
)
```

---

## Security Considerations

### For Testing

- Turning off password protected sharing is acceptable on private networks
- Granting "Everyone" share permissions is convenient but not secure

### For Production

1. **Re-enable password protected sharing**
2. **Limit share permissions**: Remove "Everyone", add specific users with Modify (not Full Control)
3. **Enable Windows Firewall** with specific rules
4. **Use strong passwords** for worker accounts
5. **Consider domain accounts** instead of local accounts
6. **Use VPN** for remote office access
7. **Audit remote executions** via Windows Event Log
8. **Rotate credentials** regularly
9. **Never store passwords in source code** - use environment variables or secure credential stores

```python
import os
from ras_commander.remote import init_ras_worker

# Secure credential retrieval
worker = init_ras_worker(
    "psexec",
    hostname=os.environ["RAS_WORKER_HOST"],
    credentials={
        "username": os.environ["RAS_WORKER_USER"],
        "password": os.environ["RAS_WORKER_PASS"]
    },
    session_id=2
)
```

---

## Installation

```bash
# Basic remote support
pip install ras-commander

# SSH/Docker support
pip install ras-commander[remote-ssh]

# AWS EC2 support
pip install ras-commander[remote-aws]

# All remote backends
pip install ras-commander[remote-all]
```

---

## See Also

- [Worker Types](../parallel-compute/worker-types.md) - Detailed worker configuration
- [Remote Parallel Execution](../parallel-compute/remote-parallel.md) - compute_parallel_remote() details
- `examples/23_remote_execution_psexec.ipynb` - Complete PsExec example
