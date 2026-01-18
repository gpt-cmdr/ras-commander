# Remote Execution - Critical Configuration

**Context**: HEC-RAS remote execution requirements
**Priority**: CRITICAL - incorrect configuration causes silent failures
**Auto-loads**: Yes (all code)
**Path-Specific**: Particularly relevant to `ras_commander/remote/`

## Critical Requirement Summary

**HEC-RAS is a GUI application** and requires session-based execution when run remotely. Using system account causes silent failure.

## The Golden Rules

### ✅ MUST DO

1. **Use `session_id=2`** (typical for workstations)
2. **Configure Group Policy** on remote machine
3. **Set Registry key** `LocalAccountTokenFilterPolicy=1`
4. **Start Remote Registry service**
5. **User must be in Administrators group**

### ❌ NEVER DO

1. **Never use `system_account=True`** - HEC-RAS is GUI app, won't work
2. **Never skip Group Policy configuration** - causes permission errors
3. **Never assume default session** - explicitly specify `session_id`

## Required Remote Machine Configuration

### Group Policy Settings

Remote machine requires these Group Policy rights:

**Computer Configuration → Windows Settings → Security Settings → Local Policies → User Rights Assignment**:

1. **Access this computer from the network**
   - Add user account

2. **Allow log on locally**
   - Add user account

3. **Log on as a batch job**
   - Add user account

**Why**: PsExec requires these permissions to execute processes in user session

### Registry Configuration

**Registry Key**: `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System`

**Setting**: `LocalAccountTokenFilterPolicy` = `1` (DWORD)

```powershell
# PowerShell command to set (run as Administrator on remote machine)
New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy" -Value 1 -PropertyType DWORD -Force
```

**Why**: Allows remote administrative access for local accounts

**Warning**: This is a security setting - understand implications before changing

### Remote Registry Service

**Service**: Remote Registry
**Status**: Must be Running
**Startup Type**: Automatic (recommended)

```powershell
# PowerShell command to start Remote Registry service
Set-Service -Name "RemoteRegistry" -StartupType Automatic
Start-Service -Name "RemoteRegistry"
```

**Why**: PsExec uses Remote Registry to deploy and execute processes

### User Permissions

**Requirement**: User account must be in local **Administrators** group on remote machine

**Verify**:
```powershell
# Check if user is in Administrators group (on remote machine)
net localgroup Administrators
```

**Why**: HEC-RAS execution and file access require elevated permissions

## Session ID Configuration

### Understanding Session IDs

| Session ID | User | Typical Use |
|------------|------|-------------|
| **0** | SYSTEM | Services, background tasks |
| **1** | Console/RDP | First interactive logon |
| **2** | Console/RDP | Second interactive logon (typical for workstations) |
| **3+** | Console/RDP | Additional sessions (Terminal Server) |

### Determining Correct Session ID

**Method 1: Query Session (Recommended)**:
```bash
# From controlling machine, query remote sessions
query session /server:REMOTE_MACHINE_NAME

# Output example:
# SESSION NAME     USERNAME           ID  STATE
# console          Administrator      2   Active

# Use ID column value (2 in this example)
```

**Method 2: qwinsta Command**:
```bash
qwinsta /server:REMOTE_MACHINE_NAME
```

### Why Session ID=2 is Typical

On a standard workstation with one logged-in user:
- Session 0: Reserved for SYSTEM services
- Session 1: Sometimes used by system (varies by Windows version)
- **Session 2**: Typical interactive user session (MOST COMMON)

**Best Practice**: Always query session ID, don't assume

## PsExec Worker Configuration

### Correct Configuration

```python
from ras_commander.remote import init_ras_worker

# ✅ CORRECT: Session-based execution
worker = init_ras_worker(
    worker_type='psexec',
    hostname='192.168.1.100',
    username='ras_user',
    password='secure_password',
    session_id=2,  # CRITICAL: Specify session ID
    remote_share=r'\\192.168.1.100\RAS_Share',
    hecras_version='6.5'
)
```

### Incorrect Configuration (Will Fail Silently)

```python
# ❌ WRONG: System account won't work for GUI app
worker = init_ras_worker(
    worker_type='psexec',
    hostname='192.168.1.100',
    username='ras_user',
    password='secure_password',
    system_account=True,  # WRONG! HEC-RAS is GUI app
    remote_share=r'\\192.168.1.100\RAS_Share',
    hecras_version='6.5'
)

# ❌ WRONG: No session ID specified
worker = init_ras_worker(
    worker_type='psexec',
    hostname='192.168.1.100',
    username='ras_user',
    password='secure_password',
    # Missing session_id!
    remote_share=r'\\192.168.1.100\RAS_Share',
    hecras_version='6.5'
)
```

## Network Share Requirements

### UNC Path Format

**Requirement**: Remote share must be accessible via UNC path

```python
# ✅ CORRECT: UNC path
remote_share = r'\\192.168.1.100\RAS_Share'
remote_share = r'\\HOSTNAME\SharedFolder'

# ❌ WRONG: Mapped drive (doesn't work remotely)
remote_share = r'Z:\RAS_Share'  # Only works on machine with mapping
```

### Share Permissions

Remote share folder requires:
- **Read/Write** permissions for user account
- **Share permissions**: Read/Write for user
- **NTFS permissions**: Modify for user

**Verify**:
```powershell
# From controlling machine
net use \\REMOTE_MACHINE\RAS_Share
dir \\REMOTE_MACHINE\RAS_Share
```

## Worker Types

### PsExec Worker (Windows Remote)

**Technology**: PsExec over network shares
**Platform**: Windows → Windows
**Status**: ✓ Implemented
**Requirements**: All above configuration

```python
worker = init_ras_worker(
    worker_type='psexec',
    hostname='192.168.1.100',
    session_id=2,
    remote_share=r'\\192.168.1.100\RAS_Share',
    ...
)
```

### Docker Worker (Container Execution)

**Technology**: Docker over SSH
**Platform**: Any → Linux container
**Status**: ✓ Implemented
**Requirements**: `docker`, `paramiko` packages

```python
worker = init_ras_worker(
    worker_type='docker',
    hostname='192.168.1.100',
    ssh_key='/path/to/key.pem',
    container_image='hecras:6.5',
    ...
)
```

### Local Worker (Parallel Local)

**Technology**: Local multiprocessing
**Platform**: Same machine
**Status**: ✓ Implemented
**Requirements**: None (no remote configuration)

```python
worker = init_ras_worker(
    worker_type='local',
    num_workers=4,
    ...
)
```

### Future Workers

**Planned**:
- `SshWorker` - SSH-based execution
- `WinrmWorker` - Windows Remote Management
- `SlurmWorker` - HPC cluster execution
- `AwsEc2Worker` - AWS cloud execution
- `AzureFrWorker` - Azure cloud execution

## Troubleshooting

### HEC-RAS Doesn't Execute

**Symptoms**: No error, but HDF file not created

**Diagnosis**:
1. Check session ID: `query session /server:HOSTNAME`
2. Verify user in Administrators group
3. Check Remote Registry service running
4. Confirm Group Policy settings
5. Test manual RAS execution on remote machine

**Fix**: Ensure all configuration requirements met

### Permission Denied Errors

**Symptoms**: "Access is denied" or permission errors

**Diagnosis**:
1. Check Registry key `LocalAccountTokenFilterPolicy`
2. Verify Group Policy settings (especially "Access this computer from the network")
3. Confirm share permissions (both Share and NTFS)

### Network Path Not Found

**Symptoms**: Cannot access `\\HOSTNAME\Share`

**Diagnosis**:
1. Test from controlling machine: `dir \\HOSTNAME\Share`
2. Check firewall (port 445 for SMB)
3. Verify Remote Registry service running
4. Confirm network connectivity: `ping HOSTNAME`

## Example: Complete Setup

### Step 1: Configure Remote Machine

```powershell
# Run on remote machine as Administrator

# 1. Set Registry key
New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy" -Value 1 -PropertyType DWORD -Force

# 2. Start Remote Registry
Set-Service -Name "RemoteRegistry" -StartupType Automatic
Start-Service -Name "RemoteRegistry"

# 3. Add user to Administrators (replace USERNAME)
net localgroup Administrators USERNAME /add

# 4. Configure Group Policy (use gpedit.msc GUI)
# ... See Group Policy Settings section above
```

### Step 2: Create Network Share

```powershell
# Run on remote machine as Administrator

# Create folder
New-Item -Path "C:\RAS_Share" -ItemType Directory

# Share folder
New-SmbShare -Name "RAS_Share" -Path "C:\RAS_Share" `
    -FullAccess "USERNAME" -ReadAccess "Everyone"

# Set NTFS permissions
icacls "C:\RAS_Share" /grant "USERNAME:(OI)(CI)M"
```

### Step 3: Test from Controlling Machine

```bash
# Query session ID
query session /server:192.168.1.100

# Test share access
dir \\192.168.1.100\RAS_Share

# Test PsExec
psexec \\192.168.1.100 -u USERNAME -p PASSWORD -i 2 cmd /c echo test
```

### Step 4: Configure ras-commander Worker

```python
from ras_commander.remote import init_ras_worker, compute_parallel_remote
from ras_commander import init_ras_project

# Initialize project
init_ras_project("/local/project", "6.5")

# Create worker
worker = init_ras_worker(
    worker_type='psexec',
    hostname='192.168.1.100',
    username='ras_user',
    password='secure_password',
    session_id=2,  # From query session output
    remote_share=r'\\192.168.1.100\RAS_Share',
    hecras_version='6.5'
)

# Execute plans remotely
compute_parallel_remote(
    plans_to_run=["01", "02", "03"],
    workers=[worker]
)
```

## DataFrame Updates

**Important**: `compute_parallel_remote()` does NOT automatically update `plan_df` or `results_df`.

This is by design because:
- Results stay on remote workers (not consolidated to local project)
- User receives `ExecutionResult` objects with HDF paths on remote systems
- Manual DataFrame refresh requires copying results back first

**To update DataFrames after remote execution**:
```python
results = compute_parallel_remote(plans, workers)

# If results copied back to local project manually:
ras.plan_df = ras.get_plan_entries()
ras.update_results_df(list(results.keys()))
```

## See Also

- **Remote Subpackage**: `ras_commander/remote/AGENTS.md` - Complete remote execution documentation
- **Worker Setup Guide**: `feature_dev_notes/RasRemote/REMOTE_WORKER_SETUP_GUIDE.md`
- **Example Notebook**: `examples/500_remote_execution_psexec.ipynb`

---

**Key Takeaway**: HEC-RAS remote execution REQUIRES session-based execution (`session_id=2`). Never use `system_account=True`. Configure Group Policy, Registry, Remote Registry service, and ensure user is Administrator.
