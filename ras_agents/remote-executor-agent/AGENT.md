# Remote Executor Agent

**Purpose**: Production-ready reference documentation for distributed HEC-RAS execution across remote Windows machines via PsExec, Docker containers, and future cloud workers.

**Domain**: Remote execution, distributed computing, worker configuration

**Status**: Production (migrated from feature_dev_notes with security redaction)

---

## Primary Sources

**Complete Setup Guide**:
- `reference/REMOTE_WORKER_SETUP_GUIDE.md` - Comprehensive step-by-step worker setup (11 parts, 27KB)
  - Part 1-3: Network shares, user rights, registry
  - Part 4-6: Service configuration, firewall, session ID
  - Part 7-9: Testing, validation, troubleshooting
  - Part 10-11: Usage examples, multi-worker setup

**Critical Configuration Rules**:
- `.claude/rules/hec-ras/remote.md` - CRITICAL configuration requirements
  - session_id=2 requirement (GUI application)
  - Group Policy configuration (3 policies)
  - Registry key LocalAccountTokenFilterPolicy=1
  - Remote Registry service startup

**Implementation Details**:
- `ras_commander/remote/AGENTS.md` - Module structure and patterns
  - Worker types (PsexecWorker, LocalWorker, DockerWorker)
  - Factory pattern (init_ras_worker)
  - Lazy loading for optional dependencies

**Working Example**:
- `examples/23_remote_execution_psexec.ipynb` - Complete end-to-end workflow
  - Worker initialization
  - Remote plan execution
  - Troubleshooting tips

**Subagent Definition**:
- `.claude/subagents/remote-executor.md` - Expert subagent for remote execution tasks
  - Trigger phrases, architecture overview
  - Common troubleshooting workflows

---

## Quick Reference

### Basic PsExec Worker Setup

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Initialize project
init_ras_project("/path/to/project", "6.5")

# Create worker (CRITICAL: use session_id, NOT system_account)
worker = init_ras_worker(
    worker_type='psexec',
    hostname='192.168.1.100',          # Remote machine IP
    username='your_username',           # Admin username on remote machine
    password='YOUR_PASSWORD',           # Password (use secure credential management)
    session_id=2,                       # ⚠️ CRITICAL: Query with 'query session /server:hostname'
    remote_share=r'\\192.168.1.100\RasRemote',  # UNC path to network share
    hecras_version='6.5'
)

# Execute plans remotely
compute_parallel_remote(
    plans_to_run=["01", "02", "03"],
    workers=[worker]
)
```

### Query Session ID

**On control machine**, query active session on remote machine:
```bash
query session /server:REMOTE_MACHINE_IP
```

Look for **Active** session, use that **ID** value (typically 2 for workstations).

### Docker Worker Setup

```python
worker = init_ras_worker(
    worker_type='docker',
    hostname='192.168.1.100',
    ssh_key='/path/to/key.pem',
    container_image='hecras:6.5',
    docker_host='ssh://user@192.168.1.100'
)
```

### Local Parallel Worker

```python
worker = init_ras_worker(
    worker_type='local',
    num_workers=4  # Number of parallel processes
)
```

---

## Critical Warnings

### ⚠️ NEVER Use system_account=True

**HEC-RAS is a GUI application** and REQUIRES session-based execution:

```python
# ❌ WRONG - Will cause silent failure
worker = init_ras_worker(
    worker_type='psexec',
    system_account=True,  # NEVER DO THIS
    ...
)

# ✅ CORRECT - Session-based execution
worker = init_ras_worker(
    worker_type='psexec',
    session_id=2,  # ALWAYS specify session_id
    ...
)
```

### ⚠️ Required Remote Machine Configuration

**5 CRITICAL steps** (all must be completed):

1. **session_id=2** - Query with `query session /server:hostname`
2. **Group Policy** - Add user to 3 policies:
   - "Access this computer from the network"
   - "Allow log on locally"
   - "Log on as a batch job"
3. **Registry** - Set `LocalAccountTokenFilterPolicy=1`
4. **Remote Registry service** - Must be running
5. **Administrator group** - User must be admin on remote machine

**See**: `reference/REMOTE_WORKER_SETUP_GUIDE.md` for complete step-by-step instructions.

### ⚠️ Network Share Requirements

- **Format**: UNC path (`\\hostname\sharename`)
- **Permissions**: Read/Write for user account
- **NOT mapped drives**: Use `\\server\share`, not `Z:\`
- **NTFS permissions**: Modify permissions, not just share permissions

---

## Common Workflows

### 1. Setup New Remote Worker

**Complete guide**: `reference/REMOTE_WORKER_SETUP_GUIDE.md` (Parts 1-9)

**Summary**:
1. Create network share (Part 1)
2. Configure user rights (Part 2)
3. Set registry key (Part 3)
4. Configure services (Part 4-5)
5. Test session access (Part 6)
6. Verify configuration (Part 7)

**Time**: 20-30 minutes per machine

### 2. Troubleshoot Silent Failure

**Symptoms**: No error, but HDF file not created

**Diagnosis**:
1. Verify `session_id` (not `system_account`)
2. Check Group Policy settings
3. Verify Remote Registry service running
4. Test UNC path accessibility
5. Confirm user is Administrator

**See**: `reference/REMOTE_WORKER_SETUP_GUIDE.md` Part 9 (Troubleshooting)

### 3. Distribute Work Across Multiple Machines

**Pattern**: Heterogeneous worker pool

```python
workers = [
    init_ras_worker('psexec', hostname='192.168.1.100', session_id=2, ...),
    init_ras_worker('psexec', hostname='192.168.1.101', session_id=2, ...),
    init_ras_worker('local', num_workers=2),  # Local fallback
]

compute_parallel_remote(
    plans_to_run=["01", "02", "03", "04", "05"],
    workers=workers  # Queue-aware scheduling
)
```

**See**: `reference/REMOTE_WORKER_SETUP_GUIDE.md` Part 11 (Multi-Worker Setup)

### 4. Secure Credential Management

**NEVER hardcode passwords in scripts**:

```python
# ❌ BAD - Password in source code
worker = init_ras_worker(
    'psexec',
    username='admin',
    password='MyPassword123',  # Exposed in git!
    ...
)

# ✅ GOOD - Use environment variables
import os
worker = init_ras_worker(
    'psexec',
    username=os.environ['RAS_USERNAME'],
    password=os.environ['RAS_PASSWORD'],
    ...
)

# ✅ BETTER - Use keyring or credential manager
import keyring
worker = init_ras_worker(
    'psexec',
    username='admin',
    password=keyring.get_password('ras-commander', 'remote-worker'),
    ...
)
```

**See**: `reference/REMOTE_WORKER_SETUP_GUIDE.md` (includes security guidance)

---

## Worker Types

### Implemented (3)

**PsexecWorker** - Windows → Windows remote execution:
- Technology: PsExec over SMB network shares
- Status: ✓ Production ready
- Requirements: None (Windows native)
- Use case: Enterprise Windows networks

**LocalWorker** - Local parallel execution:
- Technology: Multiprocessing on same machine
- Status: ✓ Production ready
- Requirements: None
- Use case: Baseline parallelism without network

**DockerWorker** - Container execution over SSH:
- Technology: Docker API via SSH tunnel
- Status: ✓ Production ready
- Requirements: `pip install ras-commander[remote-docker]`
- Use case: Linux servers, cloud deployment

### Planned (5 stubs)

**SshWorker**, **WinrmWorker**, **SlurmWorker**, **AwsEc2Worker**, **AzureFrWorker**

**See**: `.claude/subagents/remote-executor.md` for complete architecture

---

## Testing and Validation

### Part 7: Basic Connectivity Test

From control machine:
```bash
# Test UNC path access
dir \\192.168.1.100\RasRemote

# Test PsExec connectivity
psexec \\192.168.1.100 -u username -p password cmd /c echo test
```

### Part 8: Session-Based Execution Test

```bash
# Test execution in user session
psexec \\192.168.1.100 -u username -p password -i 2 cmd /c echo "Session test"
```

### Part 9: Full HEC-RAS Execution Test

```python
# Execute single plan remotely
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

init_ras_project("/path/to/project", "6.5")

worker = init_ras_worker('psexec', hostname='192.168.1.100', session_id=2, ...)
compute_parallel_remote(plans_to_run=["01"], workers=[worker])

# Check for HDF file creation on remote share
```

**See**: `reference/REMOTE_WORKER_SETUP_GUIDE.md` Parts 7-9 for complete validation workflow.

---

## Navigation Map

**Need complete setup instructions?**
→ `reference/REMOTE_WORKER_SETUP_GUIDE.md` (comprehensive 11-part guide)

**Need critical configuration rules?**
→ `.claude/rules/hec-ras/remote.md` (session_id, Group Policy, Registry)

**Need implementation details?**
→ `ras_commander/remote/AGENTS.md` (module structure, patterns)

**Need working example?**
→ `examples/23_remote_execution_psexec.ipynb` (end-to-end workflow)

**Need expert assistance?**
→ Use `remote-executor` subagent (`.claude/subagents/remote-executor.md`)

**Troubleshooting?**
→ `reference/REMOTE_WORKER_SETUP_GUIDE.md` Part 9 (Common Issues)

---

## Migration Notes

**Source**: `docs_old/feature_dev_notes/RasRemote/` (gitignored, not tracked)

**Migrated**: 2025-12-12

**Security Redaction**: All credentials, IP addresses, usernames, and machine names replaced with generic placeholders:
- Password → `YOUR_PASSWORD`
- IP → `192.168.1.100` (RFC example)
- Username → `your_username`
- Machine name → `WORKER-01`

**Verification**: Security audit passed - zero sensitive information in tracked files.

**Original Content**: Available in gitignored `docs_old/` for reference (not accessible to automated agents).

---

**Last Updated**: 2025-12-12
**Status**: Production Ready ✅
**Security**: Audited and Verified ✅
