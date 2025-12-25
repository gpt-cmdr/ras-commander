---
name: remote-executor
description: >
  Remote and distributed HEC-RAS execution via PsExec, Docker, and cloud workers.
  Handles worker configuration, session management, network shares, and distributed compute.
  **CRITICAL**: HEC-RAS requires session_id=2 (desktop session), NOT system_account.
  Primary sources: ras_commander/remote/AGENTS.md (patterns), examples/500_remote_execution_psexec.ipynb (workflow),
  .claude/rules/hec-ras/remote.md (critical setup requirements).
model: sonnet
working_directory: ras_commander/remote
---

# Remote Executor Subagent

**Purpose**: Guide implementation and troubleshooting for distributed HEC-RAS execution across local, remote, and cloud compute resources.

**Status**: 3 workers implemented (PsExec, Docker, Local), 5 stubs (SSH, WinRM, Slurm, AWS, Azure)

---

## Primary Sources (Read These First)

This subagent is a **lightweight navigator**. For detailed information, consult these primary sources:

### 1. Implementation Guide
**File**: `C:\GH\ras-commander\ras_commander\remote\AGENTS.md` (156 lines)

**Contains**:
- Module structure and naming conventions
- Import patterns and lazy loading
- Worker implementation pattern
- Factory function routing
- **CRITICAL**: PsExec session_id=2 requirement (lines 94-101)
- Docker worker setup and path conversion
- Adding new worker types

**Use for**: Coding patterns, module architecture, worker development

### 2. Complete Workflow Example
**File**: `C:\GH\ras-commander\examples\500_remote_execution_psexec.ipynb`

**Contains**:
- Part 1: Setup and imports
- Part 2: Local parallel execution baseline
- Part 3: Remote execution setup (JSON config)
- Part 4: Remote parallel execution with multiple workers
- Part 5: Result verification
- Working code for all worker types

**Use for**: End-to-end workflows, JSON configuration format, testing patterns

### 3. Setup Instructions
**File**: `.claude/rules/hec-ras/remote.md` (authoritative setup guide)

**Contains**:
- Critical configuration requirements
- Group Policy configuration
- Registry key configuration (`LocalAccountTokenFilterPolicy=1`)
- Remote Registry service requirements
- Session ID determination procedure
- Docker worker setup (images, SSH keys)
- Troubleshooting guide with root cause analysis
- Security hardening for production

**Use for**: First-time worker setup, troubleshooting access issues, production deployment

---

## Quick Start

### Initialize Worker from JSON
```python
from ras_commander.remote import load_workers_from_json, compute_parallel_remote

# Load workers from configuration file
workers = load_workers_from_json("RemoteWorkers.json")

# Execute plans across distributed workers
results = compute_parallel_remote(
    plan_numbers=["01", "02", "03"],
    workers=workers,
    num_cores=4
)
```

### RemoteWorkers.json Format
```json
{
  "workers": [
    {
      "name": "Remote Workstation",
      "worker_type": "psexec",
      "hostname": "192.168.1.100",
      "share_path": "\\\\192.168.1.100\\RasRemote",
      "worker_folder": "C:\\RasRemote",
      "username": "your_username",
      "password": "your_password",
      "session_id": 2,
      "cores_total": 8,
      "cores_per_plan": 2,
      "enabled": true
    }
  ]
}
```

**CRITICAL**: Determine `session_id` with: `query session /server:HOSTNAME` (usually 2 for workstations)

---

## Worker Types

| Worker | Status | Platform | Primary Use |
|--------|--------|----------|-------------|
| **PsexecWorker** | ✓ Implemented | Windows → Windows | Network share + PsExec |
| **DockerWorker** | ✓ Implemented | Any → Linux | Containers (local/remote via SSH) |
| **LocalWorker** | ✓ Implemented | Local machine | Parallel baseline, testing |
| **SshWorker** | Stub | Any → Unix | Direct SSH execution |
| **WinrmWorker** | Stub | Windows → Windows | Modern Windows remoting |
| **SlurmWorker** | Stub | Any → HPC | Cluster job scheduler |
| **AwsEc2Worker** | Stub | Any → Cloud | AWS EC2 instances |
| **AzureFrWorker** | Stub | Any → Cloud | Azure Functions/Batch |

---

## Critical Configuration Notes

### PsExec Worker Requirements

**CRITICAL**: HEC-RAS is a GUI application and MUST run in a desktop session.

✅ **Correct**:
```python
worker = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    session_id=2,  # Query with: query session /server:HOSTNAME
    share_path=r"\\192.168.1.100\RasRemote",
    worker_folder=r"C:\RasRemote",
    username="ras_user",
    password="secure_password"
)
```

❌ **Incorrect** (will hang):
```python
worker = init_ras_worker(
    "psexec",
    system_account=True,  # NO! HEC-RAS needs desktop
    # ...
)
```

### PsExec Setup Requirements (Details in SETUP_GUIDE)
1. Network share on remote machine (`C:\RasRemote` → `\\HOST\RasRemote`)
2. Group Policy: 3 policies configured (network access, local logon, batch job)
3. Registry key: `LocalAccountTokenFilterPolicy = 1`
4. Service: Remote Registry running
5. User: In Administrators group
6. **Reboot required** after configuration

### Docker Worker Requirements
- Docker image with HEC-RAS Linux binaries
- SSH key authentication for remote Docker hosts
- Preprocessing happens on Windows, execution in Linux container
- Path conversion: `/mnt/c/` → `C:/` for Docker Desktop

---

## Common Issues and Solutions

### Issue 1: HEC-RAS Doesn't Execute (Silent Failure)

**Symptoms**: Worker completes, no error, no HDF file

**Root Cause**: Wrong session_id or system_account=True

**Solution**:
```bash
# On control machine, query remote sessions
query session /server:HOSTNAME

# Use the ID column value (typically 2)
```

**See**: `AGENTS.md` lines 94-101, `SETUP_GUIDE.md` Part 6

---

### Issue 2: "Logon failure: the user has not been granted the requested logon type"

**Root Cause**: Missing Group Policy permissions

**Solution**: Configure 3 policies on remote machine:
1. "Access this computer from the network"
2. "Allow log on locally"
3. "Log on as a batch job"

**See**: `SETUP_GUIDE.md` Part 2, lines 74-117

---

### Issue 3: "Access is denied" with PsExec

**Root Cause**: UAC token filtering for network accounts

**Solution**: Set registry key on remote machine:
```powershell
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f
```

**See**: `SETUP_GUIDE.md` Part 3, lines 120-140

---

### Issue 4: Docker Worker Connection Failed

**Root Cause**: SSH key permissions or missing key

**Solution**:
```bash
# Generate SSH key
ssh-keygen -t ed25519 -f ~/.ssh/docker_worker

# Copy to remote host
ssh-copy-id -i ~/.ssh/docker_worker user@hostname

# Test connection
ssh -i ~/.ssh/docker_worker user@hostname "docker info"
```

**See**: `SETUP_GUIDE.md` Part 11, lines 982-995

---

### Issue 5: UNC Path Errors in Batch Files

**Root Cause**: Batch files use UNC paths instead of local paths

**Solution**: PsExec executes on remote filesystem, use local paths:
- ✅ Correct: `C:\RasRemote\project\...`
- ❌ Wrong: `\\192.168.1.100\RasRemote\project\...`

**Note**: ras-commander handles this conversion automatically

**See**: `AGENTS.md` line 99

---

## Module Architecture

### File Structure
```
ras_commander/remote/
├── __init__.py              # Public exports
├── RasWorker.py             # Base class + init_ras_worker() factory
├── PsexecWorker.py          # ✓ Windows remote (PsExec)
├── DockerWorker.py          # ✓ Container execution
├── LocalWorker.py           # ✓ Local parallel
├── SshWorker.py             # Stub
├── WinrmWorker.py           # Stub
├── SlurmWorker.py           # Stub
├── AwsEc2Worker.py          # Stub
├── AzureFrWorker.py         # Stub
├── Execution.py             # compute_parallel_remote()
├── Utils.py                 # Shared utilities
└── AGENTS.md                # ← Implementation guide
```

### Import Pattern
```python
# Top-level (recommended)
from ras_commander import init_ras_worker, compute_parallel_remote

# Direct subpackage
from ras_commander.remote import init_ras_worker
from ras_commander.remote import PsexecWorker  # If needed
```

---

## Adding New Worker Types

**Steps** (see `AGENTS.md` lines 109-118 for complete pattern):

1. Create `NewWorker.py` in `ras_commander/remote/`
2. Define dataclass extending `RasWorker`
3. Implement `check_*_dependencies()` if optional deps required
4. Add `init_*_worker(**kwargs)` factory function
5. Implement `execute_*_plan()` if not a stub
6. Update `RasWorker.py` factory routing
7. Update `Execution.py` dispatch in `_execute_single_plan()`
8. Update `__init__.py` exports
9. Update `setup.py` extras_require for new deps

**Example stub**:
```python
# SshWorker.py
from dataclasses import dataclass
from .RasWorker import RasWorker

@dataclass
class SshWorker(RasWorker):
    hostname: str = ""
    ssh_key: str = ""

    def __post_init__(self):
        super().__post_init__()
        raise NotImplementedError("SSH worker not yet implemented")

def init_ssh_worker(**kwargs) -> SshWorker:
    return SshWorker(worker_type="ssh", **kwargs)
```

---

## Dependencies by Worker

| Worker | Install Command | Packages |
|--------|----------------|----------|
| PsexecWorker | (none) | Standard library only |
| DockerWorker | `pip install ras-commander[remote-docker]` | docker, paramiko |
| SshWorker | `pip install ras-commander[remote-ssh]` | paramiko>=3.0 |
| WinrmWorker | `pip install ras-commander[remote-winrm]` | pywinrm>=0.4.3 |
| AwsEc2Worker | `pip install ras-commander[remote-aws]` | boto3>=1.28 |
| AzureFrWorker | `pip install ras-commander[remote-azure]` | azure-identity, azure-mgmt-compute |

---

## Testing

**Notebook**: `C:\GH\ras-commander\examples\500_remote_execution_psexec.ipynb`

**Test sequence**:
1. Part 2: Local parallel (baseline, no remote setup needed)
2. Part 3: Configure RemoteWorkers.json
3. Part 4: Execute plans on remote workers
4. Part 5: Verify HDF results

**Example project**: BaldEagleCrkMulti2D (automatically extracted)

---

## Navigation Guide

**When to read AGENTS.md**:
- Implementing new worker types
- Understanding factory pattern
- Debugging import errors
- Adding lazy-loaded dependencies

**When to read SETUP_GUIDE.md**:
- First-time remote worker setup
- "Access denied" errors
- Session ID issues
- Group Policy configuration
- Docker image building
- Production security hardening

**When to read 500_remote_execution_psexec.ipynb**:
- End-to-end workflow example
- JSON configuration format
- Testing worker setup
- Result verification patterns

---

## Best Practices

### Configuration
- Use JSON files for worker configs (not hardcoded credentials)
- Add `RemoteWorkers.json` to `.gitignore`
- Document session_id determination in worker notes
- Test with single plan before batch execution

### Security
- Use strong passwords for worker accounts
- Limit share permissions (not "Everyone" in production)
- Enable Windows Firewall with specific rules
- Rotate credentials regularly
- Use domain accounts in enterprise environments

### Performance
- 2-4 workers per remote machine (depends on cores/RAM)
- Use Gigabit Ethernet for network shares
- SSD storage on remote workers for large models
- Monitor disk space on worker folders

### Debugging
- Start with LocalWorker to verify model runs
- Test PsExec manually before using in Python
- Check compute messages in HDF for execution errors
- Use `verify=True` in compute_parallel_remote() for HDF validation

---

## Related Documentation

- **Implementation**: `ras_commander/remote/AGENTS.md`
- **Setup Guide**: `.claude/rules/hec-ras/remote.md` (critical configuration)
- **Workflow Example**: `examples/500_remote_execution_psexec.ipynb`

---

**Last Updated**: 2025-12-24
**Total Lines**: ~390 (target: 300-400)
**Primary Sources**: 3 files (AGENTS.md, notebook, remote.md rule)
