# Remote Worker Setup Guide for PsExec-Based HEC-RAS Execution

**Purpose:** Configure a Windows machine to accept remote HEC-RAS execution via PsExec

**Tested Configuration:** Windows 10/11, HEC-RAS 6.x, Local Administrator Account

**Setup Time:** 20-30 minutes

**Difficulty:** Intermediate (requires administrator access)

---

## Prerequisites

### On Remote Worker Machine (e.g., WORKER-01):
- ✅ Windows 10 or Windows 11
- ✅ HEC-RAS installed (any version 5.x - 6.x)
- ✅ Local administrator account (e.g., "your_username")
- ✅ Network connectivity (same network or VPN)
- ✅ Administrator access to configure system

### On Control Machine (where Python runs):
- ✅ PsExec.exe downloaded (from Microsoft Sysinternals)
- ✅ ras-commander library installed
- ✅ Network access to remote worker

---

## Part 1: Create Network Share (5 minutes)

**On the remote worker machine:**

### Step 1.1: Create the folder
```cmd
mkdir C:\RasRemote
```

### Step 1.2: Share the folder via Command Prompt (as Administrator)
```cmd
net share RasRemote=C:\RasRemote /GRANT:Everyone,FULL
```

**Alternative: Share via GUI**
1. Right-click `C:\RasRemote` → Properties
2. Go to **Sharing** tab → **Advanced Sharing**
3. Check **"Share this folder"**
4. Share name: `RasRemote` (exactly, case-sensitive)
5. Click **Permissions** → Add **Everyone** → Grant **Full Control**
6. Click OK → OK

### Step 1.3: Verify the share
```cmd
net share RasRemote
```

You should see:
```
Share name   RasRemote
Path         C:\RasRemote
Remark
Maximum users No limit
...
```

### Step 1.4: Test local access
```cmd
dir \\localhost\RasRemote
```

Should list the folder contents (empty at first).

---

## Part 2: Configure User Rights (10 minutes)

**Critical:** PsExec with session-based execution requires specific User Rights assignments.

### Step 2.1: Open Local Group Policy Editor
```cmd
gpedit.msc
```

### Step 2.2: Navigate to User Rights Assignment
Computer Configuration → Windows Settings → Security Settings → Local Policies → **User Rights Assignment**

### Step 2.3: Add user to required policies

For each policy below, double-click it → Add User or Group → Type your username (e.g., "your_username") → Check Names → OK

**Required policies:**

1. **"Access this computer from the network"**
   - Allows PsExec network authentication
   - Add: `username` (your admin username)

2. **"Allow log on locally"**
   - Required for session-based execution
   - Add: `username`

3. **"Log on as a batch job"**
   - Required for batch file execution
   - Add: `username`

4. **"Replace a process level token"** (optional but recommended)
   - Sometimes needed for process creation
   - Add: `username`

### Step 2.4: Verify NOT denied
Check this policy to ensure your user is NOT listed:
- **"Deny log on through Remote Desktop Services"**
- If `username` is listed, remove it

### Step 2.5: Apply policies
```cmd
gpupdate /force
```

---

## Part 3: Configure Registry Keys (5 minutes)

**On the remote worker machine (as Administrator):**

### Step 3.1: Enable Admin Token Over Network
```cmd
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f
```

This allows local administrator accounts to have full admin privileges over the network.

### Step 3.2: Verify the registry key
```cmd
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy
```

Should show:
```
LocalAccountTokenFilterPolicy    REG_DWORD    0x1
```

---

## Part 4: Configure Windows Services (3 minutes)

### Step 4.1: Start and enable Remote Registry service
```cmd
sc config RemoteRegistry start= auto
net start RemoteRegistry
```

### Step 4.2: Verify service is running
```cmd
sc query RemoteRegistry
```

Should show:
```
STATE              : 4  RUNNING
```

---

## Part 5: Configure Windows Firewall (5 minutes)

### Step 5.1: Enable File and Printer Sharing rules
```cmd
netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes
```

### Step 5.2: Verify SMB port is accessible

**From the control machine**, test:
```powershell
Test-NetConnection -ComputerName 192.168.1.100 -Port 445
```

Should show `TcpTestSucceeded : True`

**Alternative: Temporarily disable firewall for testing**
```cmd
netsh advfirewall set allprofiles state off
```

⚠️ **Remember to re-enable after testing:**
```cmd
netsh advfirewall set allprofiles state on
```

---

## Part 6: Configure Network Discovery (3 minutes)

### Step 6.1: Enable network discovery and file sharing

**Via GUI:**
1. Settings → Network & Internet → Advanced sharing settings
2. Expand **Private** network profile
3. ✅ Turn on **network discovery**
4. ✅ Turn on **file and printer sharing**
5. Expand **All Networks**
6. ⚠️ Turn off **password protected sharing** (for testing - can re-enable later)
7. Click **Save changes**

**Via Command:**
```cmd
netsh advfirewall firewall set rule group="Network Discovery" new enable=Yes
netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes
```

---

## Part 7: Ensure User is Administrator (2 minutes)

### Step 7.1: Verify user is in Administrators group
```cmd
net localgroup Administrators
```

Should show `username` in the list.

### Step 7.2: Add user if not present
```cmd
net localgroup Administrators bill /add
```

---

## Part 8: Reboot (REQUIRED)

**After all configuration changes:**
```cmd
shutdown /r /t 0
```

⚠️ **This is critical!** Registry and Group Policy changes require a reboot to take effect.

---

## Part 9: Verification Tests

**After reboot, run these tests from the control machine:**

### Test 1: Network share access
```cmd
dir \\192.168.1.100\RasRemote
```

Should list the folder contents.

### Test 2: PsExec basic connectivity
```cmd
C:\path\to\PsExec.exe \\192.168.1.100 -u bill -p YOUR_PASSWORD -accepteula cmd /c echo SUCCESS
```

Should print "SUCCESS".

### Test 3: PsExec with session ID
```cmd
C:\path\to\PsExec.exe \\192.168.1.100 -u bill -p YOUR_PASSWORD -i 2 -accepteula cmd /c echo SUCCESS
```

Should print "SUCCESS" (no logon failure error).

### Test 4: Query sessions
```cmd
C:\path\to\PsExec.exe \\192.168.1.100 -u bill -p YOUR_PASSWORD -accepteula cmd /c query user
```

Should show user sessions with IDs.

---

## Part 10: Test HEC-RAS Execution

### Create test batch file:
```cmd
echo "C:\Program Files (x86)\HEC\HEC-RAS\6.6\RAS.exe" -c "C:\RasRemote\test\project.prj" "C:\RasRemote\test\project.p01" > \\192.168.1.100\RasRemote\test_ras.bat
```

### Execute via PsExec with session ID:
```cmd
C:\path\to\PsExec.exe \\192.168.1.100 -u bill -p YOUR_PASSWORD -i 2 -accepteula C:\RasRemote\test_ras.bat
```

---

## Complete Setup Checklist

**On Remote Worker (WORKER-01):**
- [ ] Folder created: `C:\RasRemote`
- [ ] Network share created: `RasRemote` → `C:\RasRemote`
- [ ] Share permissions: `Everyone` has Full Control
- [ ] Group Policy: User added to "Access this computer from the network"
- [ ] Group Policy: User added to "Allow log on locally"
- [ ] Group Policy: User added to "Log on as a batch job"
- [ ] Group Policy: User NOT in "Deny log on through Remote Desktop Services"
- [ ] Group Policy changes applied: `gpupdate /force`
- [ ] Registry: `LocalAccountTokenFilterPolicy = 1`
- [ ] Service: Remote Registry running and set to Automatic
- [ ] Firewall: File and Printer Sharing rules enabled
- [ ] Network: Discovery and file sharing turned on
- [ ] Network: Password protected sharing OFF (for testing)
- [ ] User: In Administrators group
- [ ] **REBOOTED**
- [ ] HEC-RAS installed and path verified
- [ ] Session ID identified (usually 2)

**Verification Tests:**
- [ ] Can access `\\192.168.1.100\RasRemote` from control machine
- [ ] PsExec basic test works (no session flag)
- [ ] PsExec session test works (`-i 2`)
- [ ] HEC-RAS can be executed remotely

---

## Troubleshooting

### Error: "Logon failure: the user has not been granted the requested logon type"

**Cause:** User Rights not properly configured

**Solution:**
1. Re-check Group Policy settings (Part 2)
2. Run `gpupdate /force`
3. Reboot again
4. Verify user is in Administrators group

### Error: "The network path was not found"

**Cause:** Network share not created or accessible

**Solution:**
1. On remote machine: `net share RasRemote`
2. Should show the share - if not, recreate it
3. Check firewall rules (Part 5)

### Error: "Access is denied"

**Cause:** Insufficient permissions or UAC filtering

**Solution:**
1. Check `LocalAccountTokenFilterPolicy = 1` (Part 3)
2. Verify user in Administrators group (Part 7)
3. Reboot after registry changes

### HEC-RAS hangs or doesn't execute

**Cause:** Wrong execution mode (SYSTEM vs session)

**Solution:**
1. Do NOT use `-s` flag for HEC-RAS (it's a GUI app)
2. DO use `-i {session_id}` flag (session 2 typically)
3. Verify session ID with `query user` on remote machine

### HEC-RAS runs but creates no output

**Cause:** File paths incorrect or permissions issues

**Solution:**
1. Check batch file uses local paths (C:\RasRemote\...) not UNC paths
2. Ensure HEC-RAS has write permissions to working directory
3. Check compute messages for HEC-RAS errors

---

## Security Considerations

### For Testing:
- Turning off password protected sharing is acceptable on private networks
- Granting "Everyone" share permissions is convenient but not secure

### For Production:
1. **Re-enable password protected sharing**
2. **Limit share permissions:**
   - Remove "Everyone"
   - Add only specific users with Modify (not Full Control)
3. **Enable Windows Firewall** with specific rules
4. **Use strong passwords** for worker accounts
5. **Consider domain accounts** instead of local accounts
6. **Use VPN** for remote office access
7. **Audit remote executions** via Windows Event Log
8. **Rotate credentials** regularly

### Recommended Production Setup:
```cmd
REM Restrict share to specific user
net share RasRemote /delete
net share RasRemote=C:\RasRemote /GRANT:DOMAIN\username,CHANGE

REM Re-enable password protected sharing
REM (Settings → Network → Advanced sharing settings)

REM Enable firewall with specific rules only
netsh advfirewall set allprofiles state on
```

---

## Required Configuration Summary

### Minimal Configuration (what we tested):
1. ✅ Network share: `C:\RasRemote` shared as `RasRemote`
2. ✅ Group Policy: User added to network access, local logon, batch job policies
3. ✅ Registry: `LocalAccountTokenFilterPolicy = 1`
4. ✅ Service: Remote Registry running
5. ✅ User: In Administrators group
6. ✅ Reboot after changes
7. ✅ Use `-i 2` (session ID), NOT `-s` (SYSTEM)

### Key Insight:
**HEC-RAS is a GUI application and MUST run in a user session.**
- ❌ `-s` (SYSTEM) = No desktop, HEC-RAS hangs
- ✅ `-i {session_id}` = User desktop, HEC-RAS runs normally

---

## Quick Setup Script

**Run this on the remote worker machine (as Administrator):**

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
echo.
echo 1. Run gpedit.msc
echo 2. Navigate to: Computer Configuration → Windows Settings →
echo    Security Settings → Local Policies → User Rights Assignment
echo.
echo 3. Add your username to these policies:
echo    - Access this computer from the network
echo    - Allow log on locally
echo    - Log on as a batch job
echo.
echo 4. Run: gpupdate /force
echo.
echo 5. REBOOT the machine
echo.
echo 6. After reboot, verify session ID using: query user
echo    (Usually session 2 for single-user workstations)
echo.
pause
```

---

## Session ID Determination

### Method 1: On the remote machine directly
```cmd
query user
```

Output example:
```
USERNAME    SESSIONNAME    ID  STATE
bill        console         2  Active
```

The **ID** column (2 in this example) is what you use for `-i` flag.

### Method 2: Via PsExec from control machine
```cmd
PsExec.exe \\192.168.1.100 -u bill -p PASSWORD -accepteula cmd /c query user
```

### Common Session IDs:
- **0** = Services session (not for GUI apps)
- **1** = Console session (first user login)
- **2** = Console session (typical for single-user workstations)
- **3+** = Additional RDP sessions

**For most workstations, use Session ID 2.**

---

## PsExec Command Templates

### Basic command execution:
```cmd
PsExec.exe \\HOSTNAME -u USERNAME -p PASSWORD -accepteula cmd /c COMMAND
```

### Execute in user session (for HEC-RAS):
```cmd
PsExec.exe \\HOSTNAME -u USERNAME -p PASSWORD -i 2 -accepteula BATCH_FILE.bat
```

### With priority control (recommended for multi-user machines):
```cmd
PsExec.exe \\HOSTNAME -u USERNAME -p PASSWORD -i 2 -low -accepteula BATCH_FILE.bat
```

Priority flags:
- `-low` = Low priority (recommended for background work)
- `-belownormal` = Below normal priority
- (no flag) = Normal priority

---

## Common Issues and Solutions

### Issue 1: "Logon failure: the user has not been granted the requested logon type"

**Symptoms:**
- PsExec with `-i {session_id}` fails
- PsExec without `-i` or with `-s` works fine

**Root Cause:**
- User Rights not configured in Group Policy

**Solution:**
1. Open `gpedit.msc`
2. Add user to all policies listed in Part 2
3. Run `gpupdate /force`
4. **Reboot** (critical!)
5. Test again

### Issue 2: "The network path was not found" (Error 53)

**Symptoms:**
- Cannot access `\\192.168.1.100\RasRemote`

**Root Cause:**
- Network share not created or firewall blocking

**Solution:**
1. On remote: `net share RasRemote` (verify exists)
2. Enable firewall rules: `netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes`
3. Check network profile is Private (not Public)

### Issue 3: HEC-RAS hangs when using `-s` (SYSTEM)

**Symptoms:**
- PsExec connects but never returns
- No HDF file created

**Root Cause:**
- HEC-RAS is a GUI application
- SYSTEM account has no desktop/display

**Solution:**
- ✅ Use `-i {session_id}` instead of `-s`
- ❌ Never use `-s` for HEC-RAS execution

### Issue 4: "The system cannot find the path specified"

**Symptoms:**
- Batch file executes but HEC-RAS can't find files
- Paths in batch file use UNC format (`\\hostname\share\...`)

**Root Cause:**
- SYSTEM account cannot access UNC paths
- Or incorrect path format

**Solution:**
- Ensure batch file uses local paths: `C:\RasRemote\...`
- Not UNC paths: `\\192.168.1.100\RasRemote\...`
- ras-commander's RasRemote module handles this automatically

---

## Testing the Setup

### Test Script Template:

```batch
@echo off
SET PSEXEC=C:\path\to\PsExec.exe
SET HOST=192.168.1.100
SET USER=bill
SET PASS=YOUR_PASSWORD
SET SESSION=2

REM Test 1: Basic connectivity
%PSEXEC% \\%HOST% -u %USER% -p %PASS% -accepteula cmd /c echo SUCCESS

REM Test 2: Session-based execution
%PSEXEC% \\%HOST% -u %USER% -p %PASS% -i %SESSION% -accepteula cmd /c echo SUCCESS

REM Test 3: Check HEC-RAS exists
%PSEXEC% \\%HOST% -u %USER% -p %PASS% -accepteula cmd /c dir "C:\Program Files (x86)\HEC\HEC-RAS\6.6\RAS.exe"

REM Test 4: Run simple HEC-RAS command
echo "C:\Program Files (x86)\HEC\HEC-RAS\6.6\RAS.exe" -v > \\%HOST%\RasRemote\test_ras.bat
%PSEXEC% \\%HOST% -u %USER% -p %PASS% -i %SESSION% -accepteula C:\RasRemote\test_ras.bat
```

If all tests pass, the worker is ready for ras-commander remote execution!

---

## Using with ras-commander

### Python Example:

```python
from ras_commander import init_ras_worker, compute_distributed, init_ras_project

# Initialize HEC-RAS project
init_ras_project(r"C:\Projects\MyRASProject", "6.6")

# Initialize remote worker
worker = init_ras_worker(
    "psexec",
    hostname="192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
    credentials={"username": "your_username", "password": "YOUR_PASSWORD"},
    ras_exe_path=r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\RAS.exe",
    session_id=2,  # Your verified session ID
    system_account=False,  # Must be False for HEC-RAS GUI
    priority="low"
)

# Execute plans remotely
results = compute_distributed(
    plan_number=["01", "02", "03"],
    workers=[worker],
    dest_folder="remote_results"
)
```

---

## Multi-Worker Setup

To add multiple remote workers, repeat this setup on each machine:

```python
workers = [
    init_ras_worker(
        "psexec",
        hostname="192.168.1.100",  # WORKER-01
        share_path=r"\\192.168.1.100\RasRemote",
        credentials={"username": "your_username", "password": "pass"},
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
results = compute_distributed(
    plan_number=None,  # All plans
    workers=workers
)
```

---

## Important Notes

### Session ID Stability:
- Session ID can change if users log off/on
- For unattended execution, keep a user logged in on the remote machine
- Or use RDP to maintain a consistent session

### HEC-RAS Licensing:
- Ensure HEC-RAS license is valid on remote machine
- Network licenses should work
- Node-locked licenses require license on each worker

### Performance Considerations:
- Network share speed affects file transfer time
- Use Gigabit Ethernet for best performance
- Large models benefit from SSD storage on worker
- Consider 2-4 workers per machine (depends on cores/RAM)

### Firewall Notes:
- Port 445 (SMB) - Required for file sharing
- Port 135 (RPC) - Required for Remote Registry
- Port 139 (NetBIOS) - Legacy SMB support
- Dynamic ports 49152-65535 - May be needed for PsExec

---

## Advanced Configuration

### For Enterprise/Domain Environments:

Use domain accounts for better security:
```python
credentials={
    "username": "DOMAIN\\username",
    "password": "password"
}
```

### For Multiple Parallel Runs per Worker:

Create multiple share folders:
```cmd
mkdir C:\RasRemote\Worker1
mkdir C:\RasRemote\Worker2
net share Worker1=C:\RasRemote\Worker1 /GRANT:Everyone,FULL
net share Worker2=C:\RasRemote\Worker2 /GRANT:Everyone,FULL
```

Then create multiple worker objects pointing to different shares.

---

## Maintenance

### Regular Tasks:
- Monitor disk space on `C:\RasRemote`
- Clean old temporary folders
- Rotate passwords periodically
- Review Windows Event Logs for issues
- Update HEC-RAS versions consistently

### Monitoring Worker Health:
```cmd
REM Check disk space
PsExec.exe \\192.168.1.100 -u bill -p pass -accepteula cmd /c dir C:\

REM Check HEC-RAS version
PsExec.exe \\192.168.1.100 -u bill -p pass -accepteula cmd /c dir "C:\Program Files (x86)\HEC\HEC-RAS\"

REM Check temp folder size
PsExec.exe \\192.168.1.100 -u bill -p pass -accepteula cmd /c dir C:\RasRemote
```

---

## Pre-Install PSEXESVC for Faster Connections (Optional)

**Purpose:** Eliminate 5-15 second delay on first PsExec connection to each machine.

### Why This Helps

When PsExec first connects to a remote machine, it:
1. Copies `PSEXESVC.exe` to `C:\Windows` on the remote machine
2. Creates and starts the PSEXESVC Windows service
3. This service handles command execution on behalf of PsExec

This process takes 5-15 seconds on first connection. Subsequent connections reuse the service and are much faster. Pre-installing the service eliminates this first-connection delay.

### Step 1: Copy PSEXESVC.exe to Remote Machine

From your control machine (where PsExec is installed), copy the service executable:

```cmd
REM Copy from PSTools folder to remote machine's Windows directory
copy "C:\path\to\PsTools\PSEXESVC.exe" \\192.168.1.100\C$\Windows\PSEXESVC.exe
```

Note: This requires admin access to the admin share (`C$`).

### Step 2: Create the Service (on Remote Machine)

On the remote machine, run as Administrator:

```cmd
sc create PSEXESVC binPath= "C:\Windows\PSEXESVC.exe" start= demand
```

Note: The space after `binPath=` and `start=` is required.

### Step 3: Verify Installation

```cmd
sc query PSEXESVC
```

Should show:
```
SERVICE_NAME: PSEXESVC
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 1  STOPPED
        ...
```

The service should be **STOPPED** but installed. PsExec will start it automatically when needed.

### Step 4: Test Connection Speed

First connection should now be nearly instant:

```cmd
PsExec.exe \\192.168.1.100 -u user -p pass -accepteula cmd /c echo FAST
```

### Alternative: Let PsExec Auto-Install

If you prefer not to pre-install, PsExec will automatically install the service on first use. The delay only occurs once per machine (until reboot or service removal).

### Removing PSEXESVC

If you need to remove the service:

```cmd
sc stop PSEXESVC
sc delete PSEXESVC
del C:\Windows\PSEXESVC.exe
```

---

## Comparison: Session vs SYSTEM

| Feature | `-s` (SYSTEM) | `-i {session_id}` (User Session) |
|---------|---------------|-----------------------------------|
| Setup Complexity | Simple | Complex (Group Policy required) |
| UAC Issues | None | Requires configuration |
| GUI Applications | ❌ Hangs | ✅ Works |
| HEC-RAS | ❌ No desktop | ✅ Runs normally |
| Security | Higher privileges | User-level privileges |
| Session dependency | No | Yes (user must be logged in) |
| **For HEC-RAS** | **DO NOT USE** | **REQUIRED** |

---

## Estimated Setup Time by Experience Level

- **Experienced IT Admin:** 15-20 minutes
- **Developer/Engineer:** 25-35 minutes
- **First-time setup:** 45-60 minutes (including troubleshooting)

---

## Next Steps After Setup

1. ✅ Verify all tests pass
2. ✅ Test with small HEC-RAS project (like Muncie)
3. ✅ Test with production HEC-RAS project
4. ✅ Monitor performance and logs
5. ✅ Document worker-specific configuration (HEC-RAS version, cores, etc.)
6. ✅ Set up additional workers if needed
7. ✅ Implement production security hardening

---

---

## Part 11: Docker Worker Setup (Alternative to PsExec)

Docker workers provide Linux-based HEC-RAS execution, useful for:
- Leveraging Linux performance optimizations
- Running multiple isolated HEC-RAS instances
- Cloud/container orchestration compatibility

### Prerequisites for Docker Workers

**On the Docker host machine:**
- Docker Desktop installed and running (Linux containers mode)
- SSH server enabled (for remote Docker hosts)
- Network share accessible for file transfer

### Available Docker Images

Pre-built images are available for multiple HEC-RAS versions:

| Image Tag | HEC-RAS Version | Size | Notes |
|-----------|-----------------|------|-------|
| `hecras:6.6` | 6.6 | ~2.58 GB | Latest, recommended |
| `hecras:6.5` | 6.5 | ~2.95 GB | |
| `hecras:6.1` | 6.1 | ~2.71 GB | |
| `hecras:5.0.7` | 5.0.7 | ~2.43 GB | Binary: `rasUnsteady64` |

### Building Docker Images

#### Option 1: Use Pre-Built Dockerfiles

Download Dockerfiles from the ras-commander repository and build:

```cmd
cd C:\RasRemote\docker-builds

REM Build HEC-RAS 6.6
docker build -f Dockerfile.6.6 -t hecras:6.6 .

REM Build HEC-RAS 6.5
docker build -f Dockerfile.6.5 -t hecras:6.5 .

REM Build HEC-RAS 6.1
docker build -f Dockerfile.6.1 -t hecras:6.1 .

REM Build HEC-RAS 5.0.7
docker build -f Dockerfile.5.0.7 -t hecras:5.0.7 .
```

#### Option 2: Build All Images at Once

```cmd
C:\RasRemote\docker-builds\build_all_images.bat
```

### HEC-RAS Linux Download URLs

The Dockerfiles automatically download from HEC:

- **6.6**: `https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v66.zip`
- **6.5**: `https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v65.zip`
- **6.1**: `https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_610_Linux.zip`
- **5.0.7**: `https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_507_linux.zip`

### Zip File Structures

Different HEC-RAS versions have different zip structures:

**6.6 / 6.5:**
```
Linux_RAS_v6X/
├── RAS_v6X/Release/    # Binaries (RasUnsteady, RasGeomPreprocess, RasSteady)
├── libs/               # Intel MKL and runtime libraries
└── Muncie_6X0/         # Example project
```

**6.1:**
```
HEC-RAS_610_Linux/
└── RAS_Linux_test_setup.zip  # Nested zip
    ├── Ras_v61/Release/      # Binaries
    └── libs/                 # Libraries
```

**5.0.7:**
```
RAS_507_linux/
└── bin_ras/           # Both binaries AND libraries together
    ├── rasUnsteady64  # Note: different name than newer versions
    └── lib*.so        # MKL libraries
```

### Docker Worker Configuration in ras-commander

```python
from ras_commander import init_ras_project
from ras_commander.remote import init_ras_worker, compute_parallel_remote

# Initialize project
init_ras_project(r"C:\Projects\MyProject", "6.6")

# Create Docker worker (remote Docker host via SSH)
worker = init_ras_worker(
    "docker",
    docker_image="hecras:6.6",
    docker_host="ssh://user@192.168.1.100",
    share_path=r"\\192.168.1.100\RasRemote",
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

### SSH Key Setup for Docker Workers

Docker workers using `ssh://` URLs require key-based authentication:

```bash
# Generate SSH key (on control machine)
ssh-keygen -t ed25519 -f ~/.ssh/docker_worker

# Copy to remote Docker host
ssh-copy-id -i ~/.ssh/docker_worker user@192.168.1.100

# Test connection
ssh -i ~/.ssh/docker_worker user@192.168.1.100 "docker info"
```

### Preprocessing Workflow

Docker workers use a two-step workflow:

1. **Preprocess on Windows**: Creates `.tmp.hdf` file with geometry and initial conditions
2. **Execute on Linux**: Runs RasUnsteady in Docker container

The preprocessing monitors the `.bcoXX` file for "Starting Unsteady Flow Computations" signal to terminate early, avoiding running the full simulation on Windows.

### Verifying Docker Images

```cmd
docker images | findstr hecras
```

Expected output:
```
hecras:6.6       2.58GB
hecras:6.5       2.95GB
hecras:6.1       2.71GB
hecras:5.0.7     2.43GB
```

### Testing Docker Execution

```cmd
REM Test that HEC-RAS binaries are present
docker run --rm hecras:6.6 ls -la /app/bin/

REM Test RasUnsteady can execute
docker run --rm hecras:6.6 /app/bin/RasUnsteady --help
```

---

**Setup Guide Version:** 1.1
**Last Updated:** 2025-12-04
**Tested Configuration:** Windows 11, HEC-RAS 6.6, Local Admin Account, Docker Desktop
**Status:** ✅ VERIFIED WORKING (PsExec and Docker workers)
