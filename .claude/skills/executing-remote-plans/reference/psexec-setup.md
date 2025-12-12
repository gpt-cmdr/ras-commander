# PsExec Worker Setup Guide

Complete guide for configuring remote Windows machines for PsExec-based HEC-RAS execution.

## Critical Requirement

**HEC-RAS is a GUI application** and requires session-based execution. Using `system_account=True` causes silent failure.

## Quick Reference

| Setting | Value | Command |
|---------|-------|---------|
| **Session ID** | 2 (typical) | `query session /server:HOSTNAME` |
| **System Account** | False | NEVER use True for HEC-RAS |
| **Group Policy** | 3 rights | See Group Policy Settings |
| **Registry Key** | LocalAccountTokenFilterPolicy=1 | See Registry Configuration |
| **Service** | Remote Registry running | See Remote Registry Service |
| **User Permissions** | Administrators group | See User Permissions |

## Session ID Configuration

### Understanding Session IDs

| Session ID | User | Typical Use | Desktop |
|------------|------|-------------|---------|
| **0** | SYSTEM | Services, background tasks | ❌ No |
| **1** | Console/RDP | First interactive logon | ✓ Yes |
| **2** | Console/RDP | Second interactive logon (TYPICAL) | ✓ Yes |
| **3+** | Console/RDP | Additional sessions | ✓ Yes |

### Determining Session ID

**Method 1: Query Session (Recommended)**:
```bash
# From controlling machine
query session /server:192.168.1.100

# Output:
# SESSIONNAME       USERNAME        ID  STATE
# console           Administrator    2  Active
#                                    ^
#                            Use this value in session_id parameter
```

**Method 2: qwinsta Command**:
```bash
qwinsta /server:192.168.1.100
```

**Method 3: Task Manager (on remote machine)**:
1. Open Task Manager (Ctrl+Shift+Esc)
2. Go to Users tab
3. Look at Session ID column

### Why Session ID=2 is Typical

On a standard workstation with one logged-in user:
- **Session 0**: Reserved for SYSTEM services (NO DESKTOP)
- **Session 1**: Sometimes used by system (varies by Windows version)
- **Session 2**: Typical interactive user session (MOST COMMON)
- **Session 3+**: Additional RDP sessions

**Best Practice**: Always query session ID before configuring worker. Don't assume Session 2.

### CRITICAL: Never Use System Account

```python
# ✅ CORRECT: Session-based execution
worker = init_ras_worker(
    "psexec",
    session_id=2,  # User session with desktop
    ...
)

# ❌ WRONG: System account (no desktop)
worker = init_ras_worker(
    "psexec",
    system_account=True,  # HEC-RAS will hang!
    ...
)
```

**Why**: HEC-RAS is a GUI application that requires:
- Desktop session
- User profile
- Window manager
- Display capabilities

SYSTEM account has none of these → silent hang.

## Group Policy Configuration

### Required User Rights

Remote machine requires these Group Policy settings:

**Path**: Computer Configuration → Windows Settings → Security Settings → Local Policies → User Rights Assignment

**1. Access this computer from the network**:
- Add user account (e.g., `DOMAIN\user` or `HOSTNAME\user`)
- Required for PsExec to connect remotely

**2. Allow log on locally**:
- Add user account
- Required for session-based execution

**3. Log on as a batch job**:
- Add user account
- Required for PsExec process execution

### Applying Group Policy

**Method 1: Local Group Policy Editor (GUI)**:
```bash
# Run on remote machine as Administrator
gpedit.msc

# Navigate to each policy and add user:
# Computer Configuration
#   → Windows Settings
#     → Security Settings
#       → Local Policies
#         → User Rights Assignment
#           → [Policy Name]

# Right-click → Properties → Add User or Group
# Enter username → Check Names → OK

# Apply changes
gpupdate /force
```

**Method 2: Security Policy Export/Import**:
```bash
# On remote machine as Administrator

# Export current policy
secedit /export /cfg C:\security_policy.inf

# Edit C:\security_policy.inf:
# [Privilege Rights]
# SeNetworkLogonRight = *S-1-5-32-544,DOMAIN\user
# SeInteractiveLogonRight = *S-1-5-32-544,DOMAIN\user
# SeBatchLogonRight = *S-1-5-32-544,DOMAIN\user

# Import modified policy
secedit /configure /db secedit.sdb /cfg C:\security_policy.inf

# Apply changes
gpupdate /force
```

### Verifying Group Policy

```bash
# Check user rights
secedit /export /cfg C:\temp_policy.inf
notepad C:\temp_policy.inf

# Look for user in:
# SeNetworkLogonRight
# SeInteractiveLogonRight
# SeBatchLogonRight
```

## Registry Configuration

### LocalAccountTokenFilterPolicy

**Purpose**: Allows remote administrative access for local accounts (non-domain).

**Registry Path**:
```
HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System
```

**Setting**: `LocalAccountTokenFilterPolicy` = `1` (DWORD)

### Setting via PowerShell

```powershell
# Run as Administrator on remote machine
New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy" `
    -Value 1 `
    -PropertyType DWORD `
    -Force

# Verify
Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy"
```

### Setting via Registry Editor

```bash
# Run on remote machine as Administrator
regedit

# Navigate to:
# HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System

# Right-click → New → DWORD (32-bit) Value
# Name: LocalAccountTokenFilterPolicy
# Value: 1
```

### Security Implications

**What it does**:
- Disables User Account Control (UAC) filtering for remote local account access
- Allows remote local accounts to perform administrative tasks

**Security considerations**:
- Only affects local accounts (not domain accounts)
- Required for PsExec with local account credentials
- Not required if using domain accounts on domain-joined machines
- Understand implications before changing in production environments

### Verification

```powershell
# Check if setting exists and is correct
$regPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
$regName = "LocalAccountTokenFilterPolicy"

$value = Get-ItemProperty -Path $regPath -Name $regName -ErrorAction SilentlyContinue

if ($value.$regName -eq 1) {
    Write-Host "LocalAccountTokenFilterPolicy is correctly set to 1"
} else {
    Write-Host "LocalAccountTokenFilterPolicy is NOT set or incorrect"
}
```

## Remote Registry Service

### Starting the Service

**PowerShell**:
```powershell
# Run as Administrator on remote machine

# Set to Automatic startup
Set-Service -Name "RemoteRegistry" -StartupType Automatic

# Start service
Start-Service -Name "RemoteRegistry"

# Verify
Get-Service -Name "RemoteRegistry"
```

**Command Prompt**:
```cmd
# Run as Administrator on remote machine

# Set to Automatic
sc config RemoteRegistry start= auto

# Start service
sc start RemoteRegistry

# Verify
sc query RemoteRegistry
```

**Services GUI**:
1. Run `services.msc` on remote machine
2. Find "Remote Registry" service
3. Right-click → Properties
4. Startup type: Automatic
5. Service status: Click "Start"
6. Click OK

### Why Remote Registry Required

PsExec uses Remote Registry to:
- Deploy executable to remote machine
- Configure remote process parameters
- Monitor remote process execution
- Retrieve remote process exit codes

### Verification

**From controlling machine**:
```bash
# Check if Remote Registry is running
sc \\192.168.1.100 query RemoteRegistry

# Output should show:
# STATE : 4 RUNNING
```

**From remote machine**:
```powershell
Get-Service -Name "RemoteRegistry" | Select-Object Status, StartType

# Should show:
# Status  StartType
# ------  ---------
# Running Automatic
```

## User Permissions

### Administrators Group

User must be in local **Administrators** group on remote machine.

**Adding User (PowerShell)**:
```powershell
# Run as Administrator on remote machine

# Add domain user
Add-LocalGroupMember -Group "Administrators" -Member "DOMAIN\user"

# Add local user
Add-LocalGroupMember -Group "Administrators" -Member "user"

# Verify
Get-LocalGroupMember -Group "Administrators"
```

**Adding User (Command Prompt)**:
```cmd
# Run as Administrator on remote machine

# Add user
net localgroup Administrators DOMAIN\user /add

# Verify
net localgroup Administrators
```

### Verifying User is Administrator

**From remote machine**:
```powershell
# Check if current user is Administrator
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($isAdmin) {
    Write-Host "Current user IS an Administrator"
} else {
    Write-Host "Current user is NOT an Administrator"
}
```

**From controlling machine**:
```bash
# Check if user is in Administrators group
net user USERNAME /domain
# Look for "Local Group Memberships" section
```

### Why Administrator Required

HEC-RAS execution requires:
- File system access to project folders
- Registry access for HEC-RAS settings
- Process creation permissions
- Network share access

## Network Share Configuration

### Creating Network Share

**PowerShell**:
```powershell
# Run as Administrator on remote machine

# Create folder
New-Item -Path "C:\RasRemote" -ItemType Directory -Force

# Create share
New-SmbShare -Name "RasRemote" -Path "C:\RasRemote" `
    -FullAccess "USERNAME" -ReadAccess "Everyone"

# Verify
Get-SmbShare -Name "RasRemote"
```

**Command Prompt**:
```cmd
# Run as Administrator on remote machine

# Create folder
mkdir C:\RasRemote

# Create share
net share RasRemote=C:\RasRemote /grant:USERNAME,FULL

# Verify
net share RasRemote
```

### Share Permissions

**Share-level permissions**:
- User: Full Control or Change
- Everyone: Read (optional, for visibility)

**NTFS permissions**:
```powershell
# Run as Administrator on remote machine

# Set NTFS permissions
icacls "C:\RasRemote" /grant "USERNAME:(OI)(CI)M"

# Verify
icacls "C:\RasRemote"
```

### UNC Path Format

```python
# ✅ CORRECT: UNC path
share_path = r"\\192.168.1.100\RasRemote"
share_path = r"\\HOSTNAME\RasRemote"

# ❌ WRONG: Mapped drive (only works on local machine)
share_path = r"Z:\RasRemote"

# ❌ WRONG: Local path (not accessible remotely)
share_path = r"C:\RasRemote"
```

### Worker Folder Mapping

```python
worker = init_ras_worker(
    "psexec",
    share_path=r"\\192.168.1.100\RasRemote",  # How controlling machine accesses
    worker_folder=r"C:\RasRemote",             # Local path on remote machine
    ...
)
```

**Why both paths needed**:
- `share_path`: Controlling machine copies files here via UNC
- `worker_folder`: PsExec executes HEC-RAS using local path

### Testing Share Access

**From controlling machine**:
```bash
# Test read access
dir \\192.168.1.100\RasRemote

# Test write access
echo test > \\192.168.1.100\RasRemote\test.txt

# Cleanup
del \\192.168.1.100\RasRemote\test.txt
```

## Firewall Configuration

### Required Ports

| Port | Protocol | Service | Purpose |
|------|----------|---------|---------|
| 445 | TCP | SMB | Network share access |
| 135 | TCP | RPC Endpoint Mapper | Remote Registry, PsExec |
| 139 | TCP | NetBIOS | Legacy network browsing |

### Firewall Rules (PowerShell)

```powershell
# Run as Administrator on remote machine

# Enable File and Printer Sharing (includes SMB and NetBIOS)
Set-NetFirewallRule -DisplayGroup "File and Printer Sharing" -Enabled True

# Verify
Get-NetFirewallRule -DisplayGroup "File and Printer Sharing" |
    Where-Object {$_.Enabled -eq "True"} |
    Select-Object DisplayName, Enabled
```

### Testing Network Connectivity

**From controlling machine**:
```bash
# Test ping
ping 192.168.1.100

# Test SMB port (445)
Test-NetConnection -ComputerName 192.168.1.100 -Port 445

# Test RPC port (135)
Test-NetConnection -ComputerName 192.168.1.100 -Port 135
```

## Complete Setup Script

### Remote Machine Configuration

```powershell
# Run as Administrator on remote machine

# 1. Set Registry key
New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy" -Value 1 -PropertyType DWORD -Force

# 2. Start Remote Registry service
Set-Service -Name "RemoteRegistry" -StartupType Automatic
Start-Service -Name "RemoteRegistry"

# 3. Add user to Administrators
Add-LocalGroupMember -Group "Administrators" -Member "USERNAME"

# 4. Create network share
New-Item -Path "C:\RasRemote" -ItemType Directory -Force
New-SmbShare -Name "RasRemote" -Path "C:\RasRemote" -FullAccess "USERNAME"
icacls "C:\RasRemote" /grant "USERNAME:(OI)(CI)M"

# 5. Enable firewall rules
Set-NetFirewallRule -DisplayGroup "File and Printer Sharing" -Enabled True

# 6. Configure Group Policy (manual - see Group Policy section above)
Write-Host "MANUAL STEP: Configure Group Policy (see guide)"

Write-Host "`nConfiguration complete. Next steps:"
Write-Host "1. Configure Group Policy (gpedit.msc)"
Write-Host "2. Run gpupdate /force"
Write-Host "3. Query session ID: query session"
Write-Host "4. Test from controlling machine"
```

### Verification Script

```powershell
# Run on remote machine to verify configuration

Write-Host "Checking PsExec Worker Configuration..."
Write-Host ""

# Check Registry
$regValue = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy" -ErrorAction SilentlyContinue

if ($regValue.LocalAccountTokenFilterPolicy -eq 1) {
    Write-Host "[OK] Registry: LocalAccountTokenFilterPolicy = 1"
} else {
    Write-Host "[FAIL] Registry: LocalAccountTokenFilterPolicy not set"
}

# Check Remote Registry service
$service = Get-Service -Name "RemoteRegistry"
if ($service.Status -eq "Running" -and $service.StartType -eq "Automatic") {
    Write-Host "[OK] Service: Remote Registry running (Automatic)"
} else {
    Write-Host "[FAIL] Service: Remote Registry not running or not Automatic"
}

# Check share exists
$share = Get-SmbShare -Name "RasRemote" -ErrorAction SilentlyContinue
if ($share) {
    Write-Host "[OK] Share: RasRemote exists at $($share.Path)"
} else {
    Write-Host "[FAIL] Share: RasRemote not found"
}

# Check firewall
$fwRules = Get-NetFirewallRule -DisplayGroup "File and Printer Sharing" |
    Where-Object {$_.Enabled -eq "True"}
if ($fwRules.Count -gt 0) {
    Write-Host "[OK] Firewall: File and Printer Sharing enabled"
} else {
    Write-Host "[FAIL] Firewall: File and Printer Sharing not enabled"
}

# Show session information
Write-Host ""
Write-Host "Current Sessions:"
query session

Write-Host ""
Write-Host "MANUAL CHECKS REQUIRED:"
Write-Host "- Group Policy: Run gpedit.msc and verify 3 user rights"
Write-Host "- User: Verify user in Administrators group (net localgroup Administrators)"
```

## Testing from Controlling Machine

### Test 1: Network Share Access

```bash
# Test from controlling machine
dir \\192.168.1.100\RasRemote
echo test > \\192.168.1.100\RasRemote\test.txt
type \\192.168.1.100\RasRemote\test.txt
del \\192.168.1.100\RasRemote\test.txt
```

### Test 2: PsExec Connectivity

```bash
# Test PsExec connection (no HEC-RAS)
psexec \\192.168.1.100 -u USERNAME -p PASSWORD -i 2 cmd /c echo test

# Should output: "test"
# If fails, check Group Policy and Registry
```

### Test 3: Full ras-commander Test

```python
from ras_commander import init_ras_project, init_ras_worker, compute_parallel_remote

# Initialize project
init_ras_project("/path/to/project", "6.6")

# Create worker
worker = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    session_id=2,
    credentials={
        "username": "USERNAME",
        "password": "PASSWORD"
    }
)

# Test with one plan
results = compute_parallel_remote(
    plan_numbers=["01"],
    workers=[worker]
)

# Check result
if results["01"].success:
    print("SUCCESS: Remote execution working!")
else:
    print(f"FAILED: {results['01'].error_message}")
```

## Troubleshooting

### HEC-RAS Doesn't Execute (Silent Failure)

**Symptom**: No error, but HDF not created

**Diagnosis**:
1. Wrong session ID → Check: `query session /server:hostname`
2. System account used → Check: `system_account=False`
3. User not Administrator → Check: `net localgroup Administrators`
4. Remote Registry not running → Check: `sc query RemoteRegistry`

### Access Denied Errors

**Symptom**: "Access is denied" when connecting

**Diagnosis**:
1. Registry not set → Check: `LocalAccountTokenFilterPolicy=1`
2. Group Policy missing → Check: gpedit.msc user rights
3. Share permissions → Check: NTFS and Share permissions
4. Firewall blocking → Check: port 445, 135 open

### Network Path Not Found

**Symptom**: Cannot access `\\hostname\share`

**Diagnosis**:
1. Share doesn't exist → Check: `net share` on remote
2. Firewall blocking → Check: port 445 open
3. Remote Registry not running → Check: `sc query RemoteRegistry`
4. Network connectivity → Check: `ping hostname`

### PsExec Hangs or Times Out

**Symptom**: PsExec command never completes

**Diagnosis**:
1. Remote Registry not running → Start service
2. Firewall blocking RPC → Open port 135
3. User rights missing → Configure Group Policy
4. Session ID incorrect → Query correct session

## See Also

- **Worker Reference**: `workers.md` - All worker types
- **Docker Setup**: `docker-setup.md` - Docker worker configuration
- **Rule**: `.claude/rules/hec-ras/remote.md` - Remote execution requirements
- **AGENTS.md**: `ras_commander/remote/AGENTS.md` - Remote subpackage guidance
