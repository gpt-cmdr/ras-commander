# Common Issues and Troubleshooting

Troubleshooting guide for remote execution problems in `ras_commander.remote`.

## Table of Contents

1. [PsExec Worker Issues](#psexec-worker-issues)
2. [Docker Worker Issues](#docker-worker-issues)
3. [Network and Connectivity](#network-and-connectivity)
4. [Permission and Security](#permission-and-security)
5. [HEC-RAS Execution Problems](#hec-ras-execution-problems)

---

## PsExec Worker Issues

### Issue: HEC-RAS Doesn't Execute (Silent Failure)

**Symptoms:**
- Worker appears to complete successfully
- No error messages
- HDF file not created on remote machine
- Compute messages empty or missing

**Root Cause:**
Using `system_account=True` or wrong `session_id`. HEC-RAS is a GUI application and requires desktop session access.

**Diagnosis Steps:**

1. **Check worker configuration:**
```python
# Print worker config
print(worker)
print(f"Session ID: {worker.session_id}")
print(f"System account: {getattr(worker, 'system_account', None)}")
```

2. **Query remote session ID:**
```bash
query session /server:REMOTE_HOSTNAME
```

3. **Check if HEC-RAS process actually ran:**
```bash
# On remote machine, check recent processes
Get-Process | Where-Object {$_.Name -like "*HEC*"}
```

**Solution:**

✅ **Correct configuration:**
```python
worker = init_ras_worker(
    worker_type='psexec',
    hostname='192.168.1.100',
    session_id=2,  # Use actual session ID from query session
    # DO NOT use system_account=True
    ...
)
```

❌ **Incorrect configuration:**
```python
worker = init_ras_worker(
    worker_type='psexec',
    system_account=True,  # WRONG!
    ...
)
```

**Prevention:**
- Always query session ID: `query session /server:HOSTNAME`
- Never assume session ID (defaults vary by Windows version)
- Never use `system_account=True` for HEC-RAS

---

### Issue: PsExec Hangs Indefinitely

**Symptoms:**
- Process runs but never completes
- No output or error messages
- Must manually terminate Python script

**Root Cause:**
Missing Group Policy permissions or firewall blocking.

**Diagnosis Steps:**

1. **Test manual PsExec:**
```bash
psexec \\HOSTNAME -u USERNAME -p PASSWORD -i 2 cmd /c echo "Test"
```

2. **Check Group Policy on remote machine:**
```powershell
# Run on remote machine
secedit /export /cfg C:\secpol.cfg
notepad C:\secpol.cfg

# Look for:
# SeNetworkLogonRight = *S-1-5-...,USERNAME
# SeInteractiveLogonRight = *S-1-5-...,USERNAME
# SeBatchLogonRight = *S-1-5-...,USERNAME
```

3. **Check Remote Registry service:**
```powershell
Get-Service RemoteRegistry
# Should show Status: Running
```

**Solution:**

Configure Group Policy on remote machine:

**Navigate to:** `gpedit.msc` → Computer Configuration → Windows Settings → Security Settings → Local Policies → User Rights Assignment

**Add user to these policies:**
1. Access this computer from the network
2. Allow log on locally
3. Log on as a batch job

**Start Remote Registry:**
```powershell
Set-Service -Name "RemoteRegistry" -StartupType Automatic
Start-Service -Name "RemoteRegistry"
```

**Restart remote machine** after Group Policy changes.

---

### Issue: "Access is denied" Error

**Symptoms:**
```
ERROR: Access is denied.
```

**Root Causes:**
1. User not in Administrators group
2. Registry key `LocalAccountTokenFilterPolicy` not set
3. Missing Group Policy permissions
4. UAC blocking remote admin

**Diagnosis Steps:**

1. **Check Administrators group membership:**
```powershell
# On remote machine
net localgroup Administrators
# Should list your username
```

2. **Check Registry key:**
```powershell
Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy"
# Should return Value: 1
```

3. **Test with local admin account:**
```bash
psexec \\HOSTNAME -u Administrator -p PASSWORD -i 2 cmd /c whoami
```

**Solution:**

**1. Add user to Administrators:**
```powershell
net localgroup Administrators USERNAME /add
```

**2. Set Registry key:**
```powershell
New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy" -Value 1 -PropertyType DWORD -Force
```

**3. Configure Group Policy** (see "PsExec Hangs" section above)

**4. Restart remote machine**

---

### Issue: UNC Path Errors

**Symptoms:**
```
The network path was not found.
Could not find file '\\HOSTNAME\Share\...'
```

**Root Causes:**
1. Network share not accessible
2. Firewall blocking SMB (port 445)
3. Incorrect UNC path format
4. Share permissions insufficient

**Diagnosis Steps:**

1. **Test share access from controlling machine:**
```bash
dir \\HOSTNAME\RAS_Share
```

2. **Test from remote machine (local path):**
```powershell
# On remote machine
dir C:\RAS_Share
```

3. **Check share permissions:**
```powershell
Get-SmbShare -Name "RAS_Share"
Get-SmbShareAccess -Name "RAS_Share"
```

4. **Check firewall:**
```powershell
# On remote machine
Test-NetConnection -ComputerName localhost -Port 445
```

**Solution:**

**1. Verify share exists:**
```powershell
# On remote machine
Get-SmbShare
```

**2. Set share permissions:**
```powershell
Grant-SmbShareAccess -Name "RAS_Share" -AccountName "USERNAME" -AccessRight Full -Force
```

**3. Set NTFS permissions:**
```powershell
icacls "C:\RAS_Share" /grant "USERNAME:(OI)(CI)M"
```

**4. Allow SMB through firewall:**
```powershell
New-NetFirewallRule -DisplayName "SMB In" -Direction Inbound -Protocol TCP -LocalPort 445 -Action Allow
```

**5. Verify path mapping in worker:**
```python
worker = init_ras_worker(
    worker_type='psexec',
    remote_share=r'\\192.168.1.100\RAS_Share',  # UNC path from controller
    local_path=r'C:\RAS_Share',  # Local path on remote machine
    ...
)
```

---

## Docker Worker Issues

### Issue: "Cannot connect to Docker daemon"

**Symptoms:**
```
Error: Cannot connect to the Docker daemon at unix:///var/run/docker.sock
```

**Root Causes:**
1. Docker not running
2. Docker socket permissions
3. Wrong `docker_host` URL
4. SSH connection failed (for remote Docker)

**Diagnosis Steps:**

1. **Check Docker status:**
```bash
docker ps
```

2. **Check Docker socket permissions:**
```bash
ls -l /var/run/docker.sock
# Should show: srw-rw---- 1 root docker
```

3. **Test SSH connection (remote Docker):**
```bash
ssh user@remote-host docker ps
```

**Solution:**

**For local Docker:**
```python
worker = init_ras_worker(
    worker_type='docker',
    docker_host='unix:///var/run/docker.sock',
    ...
)
```

**For remote Docker via SSH:**
```python
worker = init_ras_worker(
    worker_type='docker',
    docker_host='ssh://user@192.168.1.100',
    ssh_key='/path/to/key.pem',
    ...
)
```

**Add user to docker group:**
```bash
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
```

---

### Issue: SSH Authentication Failed

**Symptoms:**
```
paramiko.ssh_exception.AuthenticationException: Authentication failed
```

**Root Causes:**
1. SSH key not found or wrong path
2. SSH key permissions too open
3. SSH agent not running
4. Public key not in authorized_keys

**Diagnosis Steps:**

1. **Test SSH manually:**
```bash
ssh -i /path/to/key.pem user@remote-host
```

2. **Check key permissions:**
```bash
ls -l /path/to/key.pem
# Should be: -rw------- (600)
```

3. **Check authorized_keys:**
```bash
ssh user@remote-host "cat ~/.ssh/authorized_keys"
# Should contain your public key
```

**Solution:**

**1. Fix key permissions:**
```bash
chmod 600 /path/to/key.pem
```

**2. Add public key to remote:**
```bash
ssh-copy-id -i /path/to/key.pem user@remote-host
```

**3. Specify key in worker config:**
```python
worker = init_ras_worker(
    worker_type='docker',
    docker_host='ssh://user@192.168.1.100',
    ssh_key='/path/to/key.pem',  # Absolute path
    ...
)
```

---

### Issue: Container Image Not Found

**Symptoms:**
```
docker.errors.ImageNotFound: 404 Client Error: No such image: hecras:6.5
```

**Root Cause:**
Docker image not built or pulled.

**Solution:**

**Pull image:**
```bash
docker pull hecras:6.5
```

**Or build image:**
```bash
docker build -t hecras:6.5 /path/to/Dockerfile
```

**List available images:**
```bash
docker images
```

---

## Network and Connectivity

### Issue: Cannot Reach Remote Host

**Symptoms:**
```
ping: cannot resolve HOSTNAME
No route to host
```

**Diagnosis Steps:**

1. **Test connectivity:**
```bash
ping HOSTNAME
ping 192.168.1.100
```

2. **Check DNS resolution:**
```bash
nslookup HOSTNAME
```

3. **Test specific ports:**
```bash
# SMB for PsExec
telnet HOSTNAME 445

# SSH for Docker
telnet HOSTNAME 22
```

**Solution:**

**Use IP address instead of hostname:**
```python
worker = init_ras_worker(
    worker_type='psexec',
    hostname='192.168.1.100',  # IP instead of 'HOSTNAME'
    ...
)
```

**Check firewall rules:**
```powershell
# On remote machine
Get-NetFirewallRule | Where-Object {$_.Enabled -eq 'True'} | Format-Table
```

**Add firewall rules:**
```powershell
# Allow PsExec (SMB)
New-NetFirewallRule -DisplayName "SMB In" -Direction Inbound -Protocol TCP -LocalPort 445 -Action Allow

# Allow SSH
New-NetFirewallRule -DisplayName "SSH In" -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow
```

---

### Issue: Network Share Intermittently Disconnects

**Symptoms:**
- Works initially, then loses connection
- "Network path not found" during execution
- Files partially copied

**Root Causes:**
1. Network timeout settings
2. SMB signing mismatch
3. Idle connection timeout
4. Credential caching issues

**Solution:**

**Increase SMB timeout:**
```powershell
# On remote machine
Set-SmbClientConfiguration -SessionTimeout 300  # 5 minutes
```

**Disable SMB signing requirement (if appropriate):**
```powershell
# On remote machine
Set-SmbServerConfiguration -RequireSecuritySignature $false
```

**Keep connection alive:**
```python
# Add retry logic in worker configuration
worker = init_ras_worker(
    worker_type='psexec',
    max_retries=3,  # Retry on connection failures
    ...
)
```

---

## Permission and Security

### Issue: Windows Defender Blocks Execution

**Symptoms:**
- PsExec.exe quarantined
- HEC-RAS.exe blocked
- Antivirus logs show detections

**Solution:**

**Add exceptions to Windows Defender:**
```powershell
# On remote machine
Add-MpPreference -ExclusionPath "C:\Program Files\HEC\HEC-RAS"
Add-MpPreference -ExclusionPath "C:\RAS_Share"
Add-MpPreference -ExclusionProcess "Ras.exe"
```

**Or disable real-time protection temporarily:**
```powershell
Set-MpPreference -DisableRealtimeMonitoring $true
```

---

### Issue: UAC Prompts Block Execution

**Symptoms:**
- Execution hangs waiting for UAC prompt
- Process requires elevation but runs as standard user

**Solution:**

**Set LocalAccountTokenFilterPolicy:**
```powershell
New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "LocalAccountTokenFilterPolicy" -Value 1 -PropertyType DWORD -Force
```

**Disable UAC for remote connections:**
```powershell
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name "EnableLUA" -Value 0
```

**Note:** Disabling UAC has security implications. Use with caution.

---

## HEC-RAS Execution Problems

### Issue: HDF File Not Created

**Symptoms:**
- Execution completes without error
- No .hdf file in output folder
- Compute messages show warnings or errors

**Diagnosis Steps:**

1. **Check compute messages:**
```python
from ras_commander import HdfResultsPlan

# After execution
hdf = HdfResultsPlan(plan_hdf_path)
messages = hdf.get_compute_messages()
print(messages)
```

2. **Check plan configuration:**
```python
from ras_commander import RasPlan

plan = RasPlan(plan_file_path)
# Verify plan settings are correct
```

3. **Run manually on remote machine:**
- Log into remote machine desktop
- Open HEC-RAS GUI
- Run plan manually to see error messages

**Common Solutions:**

**Missing geometry preprocessing:**
```python
RasCmdr.compute_plan(
    plan_number="01",
    clear_geompre=True,  # Force reprocessing
    ...
)
```

**Insufficient memory/disk space:**
- Check remote machine has adequate resources
- Reduce model size or increase RAM

**Invalid plan configuration:**
- Check boundary conditions exist
- Verify computation time window
- Ensure geometry is closed

---

### Issue: Results Differ from Local Execution

**Symptoms:**
- Remote execution produces different results than local
- Water surface elevations don't match
- Mass balance errors different

**Root Causes:**
1. Different HEC-RAS versions
2. Different number of cores (`num_cores` parameter)
3. Different geometry preprocessing
4. Cached preprocessor files

**Solution:**

**Match HEC-RAS versions:**
```python
worker = init_ras_worker(
    worker_type='psexec',
    hecras_version='6.5',  # Must match local version EXACTLY
    ...
)
```

**Use same core count:**
```python
RasCmdr.compute_plan(
    plan_number="01",
    num_cores=4,  # Same as local
    ...
)
```

**Clear preprocessor cache:**
```python
RasCmdr.compute_plan(
    plan_number="01",
    clear_geompre=True,  # Force clean preprocessing
    ...
)
```

---

### Issue: Execution Times Out

**Symptoms:**
- Worker stops before completion
- No error message
- Partial results

**Root Cause:**
Default timeout too short for large models.

**Solution:**

**Increase timeout in execution:**
```python
compute_parallel_remote(
    plans_to_run=["01"],
    workers=[worker],
    timeout=7200,  # 2 hours instead of default 30 minutes
)
```

**Or disable timeout:**
```python
compute_parallel_remote(
    plans_to_run=["01"],
    workers=[worker],
    timeout=None,  # No timeout
)
```

---

## Diagnostic Workflow

When encountering issues, follow this systematic approach:

### 1. Verify Basic Configuration

```python
# Print worker configuration
print(worker)

# Check connectivity
import subprocess
result = subprocess.run(['ping', '-n', '1', worker.hostname], capture_output=True)
print(result.stdout.decode())
```

### 2. Test Worker Independently

```bash
# PsExec worker
psexec \\HOSTNAME -u USER -p PASS -i 2 cmd /c echo "Test"

# Docker worker
docker run --rm hecras:6.5 echo "Test"

# SSH (for Docker)
ssh user@host docker ps
```

### 3. Check Remote Machine State

```powershell
# On remote machine

# Service status
Get-Service RemoteRegistry

# Permissions
net localgroup Administrators

# Registry key
Get-ItemProperty HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System `
    -Name LocalAccountTokenFilterPolicy

# Share access
Get-SmbShare
Get-SmbShareAccess -Name "RAS_Share"
```

### 4. Review Logs

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check ras-commander logs
import ras_commander
print(f"Log file: {ras_commander.LoggingConfig.log_file}")
```

### 5. Isolate the Problem

Test in this order:
1. Network connectivity (ping)
2. Service access (ports, shares)
3. Authentication (credentials, permissions)
4. Worker initialization (factory function)
5. Simple execution (single plan, local worker)
6. Full workflow (multiple plans, remote workers)

---

## Getting Help

If issues persist after following this guide:

1. **Check documentation:**
   - `ras_commander/remote/AGENTS.md` - Implementation details
   - `.claude/rules/hec-ras/remote.md` - Configuration requirements
   - `examples/23_remote_execution_psexec.ipynb` - Working examples

2. **Enable debug logging:**
```python
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

3. **Collect diagnostic information:**
   - Worker configuration (`print(worker)`)
   - Error messages (full stack trace)
   - Remote machine configuration (Group Policy, Registry, services)
   - Network topology (firewalls, VPNs, etc.)

4. **Create minimal reproducible example:**
   - Simplest configuration that reproduces the issue
   - Single plan, single worker
   - Include all relevant configuration

---

**Key Takeaway:** Most remote execution issues stem from incorrect session configuration (`session_id=2` vs `system_account=True`) or missing Windows permissions (Group Policy, Registry, Administrators group). Always start troubleshooting by verifying these critical settings.
